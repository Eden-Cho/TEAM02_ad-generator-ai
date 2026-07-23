"""model-v2 병렬 통합 회귀 — 별도 워커(main_v2). 실제 LLM·이미지 API·외부 HTTP 0회.

- preview: 유료 호출 0회, 역할·경로·씬·예상 호출 수.
- generate: fake 경계에서 응답 필드·warnings·trace 무손실.
- scorer 인자 계약(gallery, req)·업로드 상한 env 폐쇄 검증.
주의: 팀 model/과 model_v2/는 최상위 패키지명이 겹쳐 한 프로세스에 한 트리만 live —
이 테스트는 model_v2를 baseline으로 로드한다(별도 워커 설계). 팀 워커와의 격리는 한
인터프리터에서 확인할 수 없으므로 독립 subprocess로 test_model_v2_isolation.py에서 검증한다.
"""
import io
import os
import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from PIL import Image

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import main_v2  # noqa: E402  (model_v2/를 sys.path에 올린다)
from app.api.v1 import model_v2 as mv2_api  # noqa: E402  (유료 스위치)
from app.services import model_v2_pipeline as mv2  # noqa: E402


def _png():
    b = io.BytesIO()
    Image.new("RGB", (20, 20)).save(b, "PNG")
    return b.getvalue()


_TECH_REQ = ('{"product_name":"Mac Mini","category":"컴퓨터·노트북·조립PC",'
             '"presentation_mode":"preserve","product_angles":["정면","후면"],'
             '"app_angles":["사용장면"]}')


def _files():
    return [("product_files", ("front.png", _png(), "image/png")),
            ("product_files", ("back.png", _png(), "image/png")),
            ("app_files", ("use.png", _png(), "image/png"))]


class OptionsPreviewTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main_v2.app)

    def test_options(self):
        d = self.client.get("/api/model-v2/options").json()
        self.assertEqual(set(d), {"style_dimensions", "categories", "export_targets"})
        self.assertGreater(len(d["categories"]), 0)

    def test_preview_zero_paid_calls(self):
        with mock.patch.object(mv2.llm, "chat_json",
                               side_effect=AssertionError("LLM 호출")), \
             mock.patch.object(mv2.prompt_generator, "chat_json",
                               side_effect=AssertionError("LLM 호출")), \
             mock.patch.object(mv2.image_generator, "generate_image_v2",
                               side_effect=AssertionError("이미지 API 호출")):
            r = self.client.post("/api/model-v2/preview",
                                 data={"req_json": _TECH_REQ}, files=_files())
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["roles"], ["hero", "build", "connectivity", "lifestyle"])
        self.assertEqual(d["expected_calls"],
                         {"images_generate": 3, "images_edit": 0, "passthrough": 1,
                          "llm_logical_max": 5})
        # composite 컷에 scene, passthrough엔 None
        scenes = {c["role"]: c["scene_id"] for c in d["cuts"]}
        self.assertIsNotNone(scenes["hero"])
        self.assertIsNone(scenes["lifestyle"])


class PaidGateTest(unittest.TestCase):
    """유료 생성 폐쇄 스위치 — 기본 비활성. 차단은 multipart 파싱·파일 저장·파이프라인 前."""

    def setUp(self):
        self.client = TestClient(main_v2.app)
        # 파이프라인·유료 경계가 단 한 번도 불리지 않아야 한다
        self.run_spy = mock.patch.object(
            mv2, "run_pipeline", side_effect=AssertionError("run_pipeline 호출됨"))
        self.img_spy = mock.patch.object(
            mv2.image_generator, "generate_image_v2",
            side_effect=AssertionError("이미지 API 호출됨"))
        self.llm_spy = mock.patch.object(
            mv2.llm, "chat_json", side_effect=AssertionError("LLM 호출됨"))
        for p in (self.run_spy, self.img_spy, self.llm_spy):
            p.start()
            self.addCleanup(p.stop)

    @contextmanager
    def _disabled_env(self, value=None):
        """MODEL_V2_PAID_ENABLED만 조작하고 복원한다(다른 환경변수는 건드리지 않는다)."""
        key = "MODEL_V2_PAID_ENABLED"
        old = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        try:
            yield
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_disabled_by_default_blocks_generate(self):
        with self._disabled_env():
            r = self.client.post("/api/model-v2/generate-detail-page",
                                 data={"req_json": _TECH_REQ, "theme_name": "light"},
                                 files=_files())
        self.assertEqual(r.status_code, 503, r.text[:200])
        self.assertEqual(r.json()["detail"], mv2_api.PAID_DISABLED_MSG)

    def test_blocked_before_multipart_parse(self):
        """필수 폼 필드가 아예 없는 요청도 422가 아니라 503 — 파싱 前 차단의 증거."""
        with self._disabled_env():
            r = self.client.post("/api/model-v2/generate-detail-page")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["detail"], mv2_api.PAID_DISABLED_MSG)
        # 잘못된 body를 보내도 동일(본문을 읽지 않는다)
        with self._disabled_env():
            r2 = self.client.post("/api/model-v2/generate-detail-page",
                                  content=b"\x00\x01 not multipart",
                                  headers={"content-type": "multipart/form-data; boundary=x"})
        self.assertEqual(r2.status_code, 503)

    def test_only_literal_one_enables(self):
        for val in ("", "0", "true", "TRUE", "yes", "on", "2", "1x", "enabled"):
            with self.subTest(value=val):
                with self._disabled_env(val):
                    self.assertFalse(mv2_api.paid_enabled())
                    r = self.client.post("/api/model-v2/generate-detail-page",
                                         data={"req_json": _TECH_REQ}, files=_files())
                self.assertEqual(r.status_code, 503)
        with self._disabled_env("1"):
            self.assertTrue(mv2_api.paid_enabled())
        with self._disabled_env(" 1 "):
            self.assertTrue(mv2_api.paid_enabled())

    def test_path_variants_do_not_bypass_gate(self):
        """canonical·trailing slash·URL 인코딩·대소문자 변형으로 유료 실행에 도달하지 못한다.

        파이프라인·LLM·이미지 mock은 호출 시 AssertionError를 던지므로, 어떤 변형이든
        핸들러에 도달했다면 이 테스트가 실패한다.
        """
        variants = [
            "/api/model-v2/generate-detail-page",        # canonical
            "/api/model-v2/generate-detail-page/",       # trailing slash
            "/api/model-v2/generate-detail-page?x=1",    # 쿼리스트링
            "/api/model-v2/generate%2Ddetail%2Dpage",    # URL 인코딩(하이픈)
            "/api/model-v2/./generate-detail-page",      # 점 세그먼트
            "//api/model-v2/generate-detail-page",       # 중복 슬래시
            "/API/MODEL-V2/GENERATE-DETAIL-PAGE",        # 대문자
            "/api/model-v2/other/../generate-detail-page",   # 상위 참조
        ]
        for path in variants:
            with self.subTest(path=path):
                with self._disabled_env():
                    r = self.client.post(path, data={"req_json": _TECH_REQ},
                                         files=_files())
                self.assertNotEqual(r.status_code, 200,
                                    f"{path} 가 유료 경로로 통과했다")
                # 성공적으로 생성된 응답 본문이 아니어야 한다
                self.assertNotIn("detail_page", r.text[:500])

    def test_preview_stays_free_while_paid_disabled(self):
        """preview는 무과금이라 스위치와 무관하게 동작한다(유료 호출 0회)."""
        with self._disabled_env(), \
             mock.patch.object(mv2.prompt_generator, "chat_json",
                               side_effect=AssertionError("LLM 호출")):
            r = self.client.post("/api/model-v2/preview",
                                 data={"req_json": _TECH_REQ}, files=_files())
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(r.json()["expected_calls"]["images_generate"], 3)

    def test_options_unaffected(self):
        with self._disabled_env():
            self.assertEqual(self.client.get("/api/model-v2/options").status_code, 200)


class GenerateFakeBoundaryTest(unittest.TestCase):
    """유료 경계만 fake — 응답 필드·warnings·trace 무손실 확인(paid 활성 상태 계약)."""

    def setUp(self):
        self.client = TestClient(main_v2.app)
        # 유료 스위치를 명시적으로 켠 상태의 기존 generate 계약을 검증한다
        paid = mock.patch.dict(os.environ, {"MODEL_V2_PAID_ENABLED": "1"})
        paid.start()
        self.addCleanup(paid.stop)
        self.geo = {"geo_html": "<html>x</html>",
                    "structured_data": [{"@type": "Product"}],
                    "faq": [{"q": "Q", "a": "A"}], "warnings": ["GEO_W"]}
        from baseline.image_plan import BackgroundContext, FullSceneContext

        def _fake_slot_ctx(req, slots):
            out = []
            for s in slots:
                if s["output_type"] == "background_context":
                    out.append(BackgroundContext(role=s["role"], role_context="RC"))
                else:
                    out.append(FullSceneContext(role=s["role"], full_scene="a scene"))
            return tuple(out)

        self.patches = [
            mock.patch.object(mv2.image_generator, "generate_image_v2",
                              side_effect=lambda plan, path, **k: Image.new("RGB", (8, 8))),
            mock.patch.object(mv2.prompt_generator, "generate_slot_contexts",
                              side_effect=_fake_slot_ctx),
            mock.patch.object(mv2.prompt_generator, "generate_usage_context",
                              side_effect=lambda req: ("", "")),
            mock.patch.object(mv2.copy_generator, "generate_page_copy",
                              side_effect=lambda *a, **k: {"intro": {}, "sections": {}, "cta": ""}),
            mock.patch.object(mv2.copy_generator, "generate_page_extras",
                              side_effect=lambda *a, **k: ({}, "")),
            mock.patch.object(mv2, "build_rich_page",
                              side_effect=lambda *a, **k: Image.new("RGB", (4, 4))),
            mock.patch.object(mv2.thumbnails, "main_thumbnail",
                              side_effect=lambda *a, **k: Image.new("RGB", (4, 4))),
            mock.patch.object(mv2.thumbnails, "gallery_thumbnails",
                              side_effect=lambda *a, **k: [Image.new("RGB", (4, 4))]),
            mock.patch.object(mv2, "geo_main", side_effect=lambda *a, **k: dict(self.geo)),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def test_generate_response_contract_lossless(self):
        r = self.client.post("/api/model-v2/generate-detail-page",
                             data={"req_json": _TECH_REQ, "theme_name": "light"},
                             files=_files())
        self.assertEqual(r.status_code, 200, r.text[:300])
        d = r.json()
        for f in ("detail_page", "main", "gallery", "seconds", "geo_html",
                  "structured_data", "faq", "warnings", "trace"):
            self.assertIn(f, d, f)
        # warnings에 GEO 가드레일 통합, trace 필드 존재
        self.assertIn("GEO_W", d["warnings"])
        self.assertIn("generations", d["trace"])
        self.assertEqual(d["structured_data"], [{"@type": "Product"}])
        # evaluation은 기본 비활성 → 응답에 없음
        self.assertNotIn("evaluation", d)


class ScorerArgsContractTest(unittest.TestCase):
    """팀 scorer 계약: score_images(gallery PIL 목록, req). 기본 비활성·비치명·CLIP 미로드."""

    def setUp(self):
        from app.services import model_v2_service as svc
        self.svc = svc
        self.g1, self.g2 = Image.new("RGB", (4, 4)), Image.new("RGB", (4, 4))
        self.result = {"page": Image.new("RGB", (2, 2)), "main": Image.new("RGB", (2, 2)),
                       "gallery": [self.g1, self.g2], "seconds": 1.0,
                       "warnings": [], "trace": {"generations": []}}
        self.req = {"product_name": "P", "category": "뷰티"}
        self.rp = mock.patch.object(mv2, "run_pipeline",
                                    side_effect=lambda *a, **k: dict(self.result))
        self.rp.start()
        self.addCleanup(self.rp.stop)

    def _fake_scorer(self, score_fn):
        m = types.ModuleType("app.services.scorer")
        m.score_images = score_fn
        m.attach_scores_to_langfuse = lambda *a, **k: None
        return m

    def test_disabled_by_default_no_scorer_import(self):
        # MODEL_V2_SCORING 미설정 → scorer import·호출 0회, evaluation 없음.
        spy = mock.Mock()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_V2_SCORING", None)
            with mock.patch.dict(sys.modules,
                                 {"app.services.scorer": self._fake_scorer(spy)}):
                out = self.svc.run(self.req, ["p.jpg"], [])
        self.assertEqual(spy.call_count, 0, "비활성 시 scorer 0회")
        self.assertNotIn("evaluation", out)

    def test_enabled_calls_scorer_once_with_gallery_and_req(self):
        spy = mock.Mock(return_value={"clip": 0.9, "brisque": 12.3})
        with mock.patch.dict(os.environ, {"MODEL_V2_SCORING": "1"}), \
             mock.patch.dict(sys.modules, {"app.services.scorer": self._fake_scorer(spy)}):
            out = self.svc.run(self.req, ["p.jpg"], [])
        self.assertEqual(spy.call_count, 1, "활성 시 정확히 1회")
        args, _ = spy.call_args
        self.assertEqual(args[0], [self.g1, self.g2], "첫 인자 = gallery PIL 목록")
        self.assertIs(args[1], self.req, "둘째 인자 = 원본 req")
        self.assertEqual(out["evaluation"], {"clip": 0.9, "brisque": 12.3}, "무손실")

    def test_scorer_exception_non_fatal_no_raw(self):
        def boom(*a, **k):
            raise RuntimeError("SECRET_SCORER_TRACE /private/x")
        with mock.patch.dict(os.environ, {"MODEL_V2_SCORING": "1"}), \
             mock.patch.dict(sys.modules, {"app.services.scorer": self._fake_scorer(boom)}):
            out = self.svc.run(self.req, ["p.jpg"], [])   # 예외 전파 안 함
        self.assertNotIn("evaluation", out, "scorer 실패 → 생성 결과 유지, evaluation 없음")
        self.assertIn("gallery", out)


class UploadEnvHelperTest(unittest.TestCase):
    def setUp(self):
        from app.api.v1 import model_v2 as m
        self.m = m

    def test_default_on_unset_or_blank(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X_UP", None)
            self.assertEqual(self.m._env_positive_int("X_UP", 12, 1000), 12)
        with mock.patch.dict(os.environ, {"X_UP": "   "}):
            self.assertEqual(self.m._env_positive_int("X_UP", 7, 1000), 7)

    def test_valid_positive(self):
        with mock.patch.dict(os.environ, {"X_UP": "20"}):
            self.assertEqual(self.m._env_positive_int("X_UP", 12, 1000), 20)

    def test_bad_values_rejected_without_raw(self):
        for bad in ("abc", "0", "-5", "99999", "1.5"):
            with mock.patch.dict(os.environ, {"X_UP": bad}):
                with self.assertRaises(RuntimeError) as cm:
                    self.m._env_positive_int("X_UP", 12, 1000)
                self.assertNotIn(bad, str(cm.exception), "값 원문 비노출")
                self.assertIn("X_UP", str(cm.exception))

    def test_read_size_always_positive(self):
        self.assertGreaterEqual(self.m._MAX_UPLOAD_MB, 1)
        self.assertGreaterEqual(self.m._MAX_UPLOAD_MB * 1024 * 1024 + 1, 2)


if __name__ == "__main__":
    unittest.main()
