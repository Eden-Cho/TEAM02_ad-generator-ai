"""model-v2 테스트 UI 로직 검증 — 실제 LLM·이미지 API·외부 HTTP 0회(requests 전부 mock).

Streamlit 런타임 없이 model_v2_client(순수 로직·HTTP 헬퍼)만 검증한다. 화면 파일
(model_v2_app.py)은 이 헬퍼만 호출하므로 유료 게이트·오류 비노출·멀티파트 보존이 여기서 고정된다.
"""
import base64
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import requests
from PIL import Image

_REPO = Path(__file__).resolve().parent.parent
_FRONTEND = _REPO / "frontend"
if str(_FRONTEND) not in sys.path:
    sys.path.insert(0, str(_FRONTEND))

import model_v2_client as mc  # noqa: E402


def _img_b64(fmt: str) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (120, 120, 120)).save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


_PNG_B64 = _img_b64("PNG")
_JPEG_B64 = _img_b64("JPEG")


class _Resp:
    """가짜 HTTP 응답 — 실제 네트워크 없이 status_code·json()만 흉내낸다."""
    def __init__(self, status=200, payload=None, raise_on_json=False):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self._raise = raise_on_json

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._payload


def _imgs():
    prod = [mc.ImageFile("a.png", b"AAA", "image/png"),
            mc.ImageFile("b.jpg", b"BBB\x00\xff", "image/jpeg")]
    app = [mc.ImageFile("u.png", b"UUU", "image/png")]
    return prod, app


_REQ = {"product_name": "P", "category": "test", "presentation_mode": "preserve"}
_PREVIEW_PAYLOAD = {"presentation_mode": "preserve", "product_form": "unknown",
                    "roles": ["hero", "lifestyle"],
                    "cuts": [{"role": "hero", "intended_path": "composite",
                              "angle": "정면", "scene_id": "s1"}],
                    "expected_calls": {"images_generate": 1, "images_edit": 0,
                                       "passthrough": 1, "llm_logical_max": 5}}
_GEN_PAYLOAD = {"detail_page": _PNG_B64, "main": _JPEG_B64, "gallery": [_JPEG_B64],
                "seconds": 1.0, "geo_html": "", "structured_data": [], "faq": [],
                "warnings": ["W1"], "trace": {"generations": [1]},
                "evaluation": {"clip": 0.9}}


class ApprovalGateTest(unittest.TestCase):
    """유료 생성 게이트 — preview·확인·입력지문이 모두 맞아야만 poster 호출."""

    def setUp(self):
        self.prod, self.app = _imgs()
        self.fp = mc.input_fingerprint(_REQ, self.prod, self.app)
        self.calls = []

        def poster(req, product, app, theme):
            self.calls.append((req, product, app, theme))
            return mc.Result(ok=True, payload=dict(_GEN_PAYLOAD))
        self.poster = poster

    def test_initial_screen_no_generate(self):
        # 최초 상태 — preview 없음 → 유료 생성 불가, poster 0회
        state = mc.initial_state()
        self.assertFalse(mc.can_generate(state, self.fp))
        res = mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                                  "light", poster=self.poster)
        self.assertFalse(res.ok)
        self.assertEqual(len(self.calls), 0)

    def test_preview_only_no_generate(self):
        # preview만 성공(승인 미체크) → poster 0회
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        self.assertFalse(mc.can_generate(state, self.fp))
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self.poster)
        self.assertEqual(len(self.calls), 0)

    def test_no_generate_without_preview_even_if_approved(self):
        state = mc.initial_state()
        mc.set_approval(state, True)           # 승인만 하고 preview 없음
        self.assertFalse(mc.can_generate(state, self.fp))
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self.poster)
        self.assertEqual(len(self.calls), 0)

    def test_generate_allowed_after_preview_and_approval(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        self.assertTrue(mc.can_generate(state, self.fp))
        res = mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                                  "light", poster=self.poster)
        self.assertTrue(res.ok)
        self.assertEqual(len(self.calls), 1)   # 정확히 1회

    def test_input_change_invalidates_preview_and_approval(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        self.assertTrue(mc.can_generate(state, self.fp))
        # 입력이 바뀌면 지문이 달라진다 → can_generate False, sync_inputs가 승인·preview 무효화
        new_req = {**_REQ, "product_name": "CHANGED"}
        new_fp = mc.input_fingerprint(new_req, self.prod, self.app)
        self.assertNotEqual(new_fp, self.fp)
        self.assertFalse(mc.can_generate(state, new_fp))
        mc.sync_inputs(state, new_fp)
        self.assertIsNone(state.preview)
        self.assertFalse(state.approved)
        mc.attempt_generate(state, new_fp, new_req, self.prod, self.app,
                            "light", poster=self.poster)
        self.assertEqual(len(self.calls), 0)

    def test_file_change_invalidates(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        # 같은 이름, 다른 바이트 → 지문 변경
        prod2 = [mc.ImageFile("a.png", b"DIFFERENT", "image/png"), self.prod[1]]
        fp2 = mc.input_fingerprint(_REQ, prod2, self.app)
        self.assertNotEqual(fp2, self.fp)
        self.assertFalse(mc.can_generate(state, fp2))


class SingleUseApprovalTest(unittest.TestCase):
    """승인 1회용 — 재승인 없이는 연속 클릭·재실행으로 2회 이상 생성되지 않는다."""

    def setUp(self):
        self.prod, self.app = _imgs()
        self.fp = mc.input_fingerprint(_REQ, self.prod, self.app)
        self.calls = []

    def _poster(self, ok=True):
        def poster(req, product, app, theme):
            self.calls.append(1)
            return mc.Result(ok=ok, payload=dict(_GEN_PAYLOAD) if ok else None,
                             error=None if ok else mc.ERR_SERVER)
        return poster

    def test_one_approval_generates_once_then_blocks(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        # 승인 1회 → 연속 3회 시도해도 첫 번째만 poster 호출
        for _ in range(3):
            mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                                "light", poster=self._poster())
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(state.approved)          # 승인 소비됨
        self.assertIsNotNone(state.preview)       # preview·지문은 유지

    def test_approval_consumed_even_on_failure(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self._poster(ok=False))
        # 실패해도 승인은 소비 — 재시도는 재승인 필요
        self.assertFalse(state.approved)
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self._poster())
        self.assertEqual(len(self.calls), 1)      # 두 번째(실패 후 재시도)는 poster 미호출

    def test_reapproval_allows_second_generate(self):
        state = mc.initial_state()
        mc.apply_preview(state, self.fp, dict(_PREVIEW_PAYLOAD))
        mc.set_approval(state, True)
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self._poster())
        mc.set_approval(state, True)              # 명시적 재승인
        mc.attempt_generate(state, self.fp, _REQ, self.prod, self.app,
                            "light", poster=self._poster())
        self.assertEqual(len(self.calls), 2)


class ResponseValidationTest(unittest.TestCase):
    """응답 폐쇄 검증 — 잘못된 JSON·필드·base64·이미지·타입은 고정 문구로 처리(예외 비노출)."""

    def setUp(self):
        self.prod, self.app = _imgs()

    def _generate_with(self, resp):
        with mock.patch.object(mc.requests, "post", return_value=resp):
            return mc.run_generate(_REQ, self.prod, self.app, "light")

    def _preview_with(self, resp):
        with mock.patch.object(mc.requests, "post", return_value=resp):
            return mc.run_preview(_REQ, self.prod, self.app)

    def test_valid_generate_ok(self):
        self.assertTrue(self._generate_with(_Resp(200, dict(_GEN_PAYLOAD))).ok)

    def test_non_dict_json_rejected(self):
        self.assertEqual(self._generate_with(_Resp(200, ["not", "a", "dict"])).error,
                         mc.ERR_SERVER)

    def test_non_json_body_rejected(self):
        self.assertEqual(self._generate_with(_Resp(200, raise_on_json=True)).error,
                         mc.ERR_SERVER)

    def test_bad_base64_rejected(self):
        bad = {**_GEN_PAYLOAD, "detail_page": "!!!not-base64!!!"}
        self.assertEqual(self._generate_with(_Resp(200, bad)).error, mc.ERR_SERVER)

    def test_wrong_image_format_rejected(self):
        # detail_page 자리에 PNG가 아닌 JPEG를 넣으면 포맷 검증 실패
        bad = {**_GEN_PAYLOAD, "detail_page": _JPEG_B64}
        self.assertEqual(self._generate_with(_Resp(200, bad)).error, mc.ERR_SERVER)

    def test_corrupt_image_rejected(self):
        bad = {**_GEN_PAYLOAD, "main": base64.b64encode(b"\xff\xd8notjpeg").decode()}
        self.assertEqual(self._generate_with(_Resp(200, bad)).error, mc.ERR_SERVER)

    def test_missing_field_rejected(self):
        bad = {k: v for k, v in _GEN_PAYLOAD.items() if k != "detail_page"}
        self.assertEqual(self._generate_with(_Resp(200, bad)).error, mc.ERR_SERVER)

    def test_bad_types_rejected(self):
        for key, val in [("warnings", "oops"), ("trace", []), ("seconds", "1"),
                         ("gallery", "x"), ("evaluation", ["a"])]:
            with self.subTest(key=key):
                bad = {**_GEN_PAYLOAD, key: val}
                self.assertEqual(self._generate_with(_Resp(200, bad)).error, mc.ERR_SERVER)

    def test_preview_valid_ok_and_bad_rejected(self):
        self.assertTrue(self._preview_with(_Resp(200, dict(_PREVIEW_PAYLOAD))).ok)
        bad_ec = {**_PREVIEW_PAYLOAD,
                  "expected_calls": {"images_generate": "3", "images_edit": 0,
                                     "passthrough": 1, "llm_logical_max": 5}}
        self.assertEqual(self._preview_with(_Resp(200, bad_ec)).error, mc.ERR_SERVER)
        bad_cut = {**_PREVIEW_PAYLOAD, "cuts": [{"role": 1, "intended_path": "x"}]}
        self.assertEqual(self._preview_with(_Resp(200, bad_cut)).error, mc.ERR_SERVER)


class MultipartAndHttpTest(unittest.TestCase):
    def setUp(self):
        self.prod, self.app = _imgs()

    def test_multipart_preserves_order_name_bytes(self):
        parts = mc.build_multipart(self.prod, self.app)
        self.assertEqual(parts, [
            ("product_files", ("a.png", b"AAA", "image/png")),
            ("product_files", ("b.jpg", b"BBB\x00\xff", "image/jpeg")),
            ("app_files", ("u.png", b"UUU", "image/png")),
        ])

    def test_generate_posts_exactly_once_to_generate_endpoint(self):
        post = mock.Mock(return_value=_Resp(200, dict(_GEN_PAYLOAD)))
        with mock.patch.object(mc.requests, "post", post):
            res = mc.run_generate(_REQ, self.prod, self.app, "light")
        self.assertTrue(res.ok)
        self.assertEqual(post.call_count, 1)
        url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
        self.assertTrue(url.endswith("/api/model-v2/generate-detail-page"), url)
        self.assertIn("127.0.0.1:8010", url)   # 기본 worker 주소
        # 멀티파트가 순서·이름·바이트 그대로 전달됐는지
        self.assertEqual(post.call_args.kwargs["files"],
                         mc.build_multipart(self.prod, self.app))

    def test_preview_uses_preview_endpoint_and_no_generate(self):
        post = mock.Mock(return_value=_Resp(200, dict(_PREVIEW_PAYLOAD)))
        with mock.patch.object(mc.requests, "post", post):
            res = mc.run_preview(_REQ, self.prod, self.app)
        self.assertTrue(res.ok)
        self.assertEqual(post.call_count, 1)
        url = post.call_args.args[0] if post.call_args.args else post.call_args.kwargs["url"]
        self.assertTrue(url.endswith("/api/model-v2/preview"), url)

    def test_backend_url_env_override(self):
        with mock.patch.dict("os.environ", {"MODEL_V2_BACKEND_URL": "http://host:9999/"}):
            self.assertEqual(mc.backend_url(), "http://host:9999")
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("MODEL_V2_BACKEND_URL", None)
            self.assertEqual(mc.backend_url(), "http://127.0.0.1:8010")

    def test_result_payload_validated_and_decoded(self):
        post = mock.Mock(return_value=_Resp(200, dict(_GEN_PAYLOAD)))
        with mock.patch.object(mc.requests, "post", post):
            res = mc.run_generate(_REQ, self.prod, self.app, "light")
        self.assertTrue(res.ok)
        # warnings·trace·evaluation 무손실
        self.assertEqual(res.payload["warnings"], ["W1"])
        self.assertEqual(res.payload["trace"], {"generations": [1]})
        self.assertEqual(res.payload["evaluation"], {"clip": 0.9})
        # 이미지는 실제 디코딩된 바이트로 반환(UI가 예외 위험 없이 사용)
        self.assertIsInstance(res.payload["detail_page_png"], bytes)
        self.assertEqual(Image.open(io.BytesIO(res.payload["detail_page_png"])).format, "PNG")
        self.assertEqual(Image.open(io.BytesIO(res.payload["main_jpeg"])).format, "JPEG")
        self.assertEqual(len(res.payload["gallery_jpeg"]), 1)


class ErrorNoLeakTest(unittest.TestCase):
    _SECRET = "SECRET_MARKER_sk-svcacct-XYZ"
    _URL = "http://127.0.0.1:8010/api/model-v2/generate-detail-page"

    def setUp(self):
        self.prod, self.app = _imgs()

    def test_network_exception_fixed_message_no_leak(self):
        exc = requests.exceptions.ConnectionError(f"{self._SECRET} at {self._URL}")
        with mock.patch.object(mc.requests, "post", side_effect=exc):
            res = mc.run_generate(_REQ, self.prod, self.app, "light")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, mc.ERR_NETWORK)
        self._assert_clean(res.error)

    def test_non200_fixed_message_no_leak(self):
        body = {"detail": f"{self._SECRET} {self._URL}"}
        with mock.patch.object(mc.requests, "post", return_value=_Resp(500, body)):
            res = mc.run_generate(_REQ, self.prod, self.app, "light")
        self.assertFalse(res.ok)
        self.assertEqual(res.error, mc.ERR_SERVER)
        self._assert_clean(res.error)

    def test_preview_error_no_leak(self):
        with mock.patch.object(mc.requests, "post",
                               side_effect=requests.exceptions.Timeout(self._SECRET)):
            res = mc.run_preview(_REQ, self.prod, self.app)
        self.assertEqual(res.error, mc.ERR_NETWORK)
        self._assert_clean(res.error)

    def _assert_clean(self, msg):
        self.assertNotIn(self._SECRET, msg)
        self.assertNotIn("sk-svcacct", msg)
        self.assertNotIn("/api/model-v2", msg)
        self.assertNotIn("http", msg)


class TeamFilesUnchangedTest(unittest.TestCase):
    """팀 frontend·backend·model·Docker 파일이 upstream/main과 바이트 동일(신규는 병렬 추가만)."""

    _PATHS = ["frontend/app.py", "model", "docker-compose.yml",
              "backend/Dockerfile", "frontend/Dockerfile", "backend/main.py",
              "backend/app/api/v1/generate.py",
              "backend/app/services/pipeline_service.py",
              "backend/app/services/scorer.py"]

    def test_team_paths_byte_identical_with_upstream_main(self):
        for rel in self._PATHS:
            with self.subTest(path=rel):
                r = subprocess.run(
                    ["git", "diff", "--exit-code", "upstream/main", "--", rel],
                    cwd=str(_REPO), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0,
                                 f"{rel} 이 upstream/main과 다름:\n{r.stdout[:800]}")


if __name__ == "__main__":
    unittest.main()
