"""model_v2_app.py 실제 배선 테스트 (Streamlit AppTest, hermetic).

순수 client 테스트(test_model_v2_ui.py)와 별개로, **실제 app 스크립트를 실행**해 위젯 배선을
검증한다. mock 경계는 HTTP 헬퍼(fetch_options·run_preview·run_generate)뿐이라 실제 LLM·이미지
API·외부 HTTP는 0회다.

파일 주입은 Streamlit 버전에 따라 두 경로를 **feature-detect**한다:
  - `file_uploader.upload()` 지원(≈1.52+): **실제 file_uploader**로 바이트를 올려 read_uploads까지
    실제 배선을 검증한다(AppWiringRealUploadTest).
  - 미지원(예: 1.51.0): AppTest가 file_uploader 값을 주입할 수 없으므로, **mock UploadedFile**을
    read_uploads에 주입하는 hermetic 대체 경로로 나머지 배선(지문·상태머신·승인 소비)을 검증한다
    (AppWiringMockUploadTest). 이 경우 **실제 file_uploader 위젯 자체는 검증되지 않으며**,
    RealUpload 테스트는 사유를 명시해 **skip으로 표시**된다(조용한 전체 skip이 아니다).
"""
import io
import itertools
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

_REPO = Path(__file__).resolve().parent.parent
_FRONTEND = _REPO / "frontend"
if str(_FRONTEND) not in sys.path:
    sys.path.insert(0, str(_FRONTEND))

import model_v2_client as mc  # noqa: E402

_ORIG_READ_UPLOADS = mc.read_uploads   # 대체 경로에서 실제 read_uploads를 mock 파일에 적용

try:
    from streamlit.testing.v1 import AppTest
    import streamlit.testing.v1.element_tree as _et
    _HAS_APPTEST = True
    _UPLOAD_SUPPORTED = hasattr(getattr(_et, "FileUploader", object), "upload")
except Exception:                        # pragma: no cover
    _HAS_APPTEST = False
    _UPLOAD_SUPPORTED = False

_APP = str(_FRONTEND / "model_v2_app.py")
_OPTIONS = {"style_dimensions": [], "categories": ["가전·TV", "test"],
            "export_targets": []}
_PREVIEW = {"presentation_mode": "preserve", "product_form": "unknown",
            "roles": ["hero", "lifestyle"],
            "cuts": [{"role": "hero", "intended_path": "composite",
                      "angle": "정면", "scene_id": "s1"},
                     {"role": "lifestyle", "intended_path": "passthrough",
                      "angle": None, "scene_id": None}],
            "expected_calls": {"images_generate": 1, "images_edit": 0,
                               "passthrough": 1, "llm_logical_max": 5}}


def _png_bytes():
    b = io.BytesIO()
    Image.new("RGB", (8, 8)).save(b, "PNG")
    return b.getvalue()


def _jpeg_bytes():
    b = io.BytesIO()
    Image.new("RGB", (8, 8)).save(b, "JPEG")
    return b.getvalue()


def _decoded_gen_payload():
    """run_generate가 성공 시 돌려주는 parse_generate 형태(디코딩된 바이트)."""
    return {"seconds": 1.0, "warnings": ["W1"], "trace": {"generations": [1]},
            "geo_html": "", "structured_data": [], "faq": [],
            "detail_page_png": _png_bytes(), "main_jpeg": _jpeg_bytes(),
            "gallery_jpeg": [], "evaluation": {"clip": 0.9}}


class _MockUploadedFile:
    """Streamlit UploadedFile 최소 모사 — read_uploads가 쓰는 name·getvalue()·type만 제공."""
    def __init__(self, name, data, mime="image/png"):
        self.name = name
        self._data = data
        self.type = mime

    def getvalue(self):
        return self._data


def _find(seq, key):
    for el in seq:
        if el.key == key:
            return el
    raise AssertionError(f"위젯 key={key} 없음")


class _WiringMixin:
    """실제 app 배선 시나리오 — USE_MOCK로 파일 주입 경로만 갈아끼운다(단언은 동일)."""
    USE_MOCK = True

    def _new_app(self, gen_spy):
        at = AppTest.from_file(_APP)
        patches = [
            mock.patch.object(mc, "fetch_options",
                              return_value=mc.Result(ok=True, payload=_OPTIONS)),
            mock.patch.object(mc, "run_preview",
                              return_value=mc.Result(ok=True, payload=dict(_PREVIEW))),
            mock.patch.object(mc, "run_generate", gen_spy),
        ]
        if self.USE_MOCK:
            # file_uploader 주입 불가 버전 대체 경로 — 실제 read_uploads를 mock UploadedFile에
            # 적용. app은 매 run에서 read_uploads를 (제품, 사용) 순으로 정확히 2회 호출하므로,
            # 짝수번째(제품)=[mock], 홀수번째(사용)=[]로 결정론적으로 주입한다.
            counter = itertools.count()

            def fake_read(uploads):
                if next(counter) % 2 == 0:
                    return _ORIG_READ_UPLOADS([_MockUploadedFile("prod.png", _png_bytes())])
                return []
            patches.append(mock.patch.object(mc, "read_uploads", side_effect=fake_read))
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        return at

    def _provide_product_file(self, at):
        if self.USE_MOCK:
            at.run(timeout=30)                      # mock 주입은 매 run에서 자동 적용
        else:
            at.get("file_uploader")[0].upload("prod.png", _png_bytes()).run(timeout=30)

    def _spy(self):
        return mock.Mock(return_value=mc.Result(ok=True, payload=_decoded_gen_payload()))

    def test_initial_no_generate(self):
        spy = self._spy()
        at = self._new_app(spy)
        at.run(timeout=30)
        self.assertEqual(len(list(at.exception)), 0)
        self.assertEqual(spy.call_count, 0)
        with self.assertRaises(AssertionError):      # preview 전 → generate 버튼 없음
            _find(at.button, "mv2_gen_btn")

    def test_preview_then_no_generate_until_approval(self):
        spy = self._spy()
        at = self._new_app(spy)
        at.run(timeout=30)
        self._provide_product_file(at)
        _find(at.button, "mv2_preview_btn").click().run(timeout=30)
        self.assertIsNotNone(at.session_state["mv2_state"].preview)
        self.assertEqual(spy.call_count, 0)
        self.assertTrue(_find(at.button, "mv2_gen_btn").disabled)   # 미승인 → 비활성

    def test_preview_approve_generate_once(self):
        spy = self._spy()
        at = self._new_app(spy)
        at.run(timeout=30)
        self._provide_product_file(at)
        _find(at.button, "mv2_preview_btn").click().run(timeout=30)
        _find(at.checkbox, "mv2_approve_cb").set_value(True).run(timeout=30)
        _find(at.button, "mv2_gen_btn").click().run(timeout=30)
        self.assertEqual(spy.call_count, 1)          # 정확히 1회
        self.assertEqual(len(list(at.exception)), 0)
        self.assertFalse(at.session_state["mv2_state"].approved)    # 승인 소비
        at.run(timeout=30)                            # 다음 run: 체크박스도 False로 초기화
        self.assertFalse(_find(at.checkbox, "mv2_approve_cb").value)
        self.assertTrue(_find(at.button, "mv2_gen_btn").disabled)
        self.assertEqual(spy.call_count, 1)          # 재승인 전 재생성 없음

    def test_input_change_invalidates_approval(self):
        spy = self._spy()
        at = self._new_app(spy)
        at.run(timeout=30)
        self._provide_product_file(at)
        _find(at.button, "mv2_preview_btn").click().run(timeout=30)
        _find(at.checkbox, "mv2_approve_cb").set_value(True).run(timeout=30)
        state = at.session_state["mv2_state"]
        self.assertTrue(mc.can_generate(state, state.preview_fp))
        _find(at.text_input, "mv2_product_name").set_value("CHANGED").run(timeout=30)
        self.assertIsNone(at.session_state["mv2_state"].preview)     # preview 무효화
        self.assertFalse(at.session_state["mv2_state"].approved)     # 승인 무효화
        with self.assertRaises(AssertionError):
            _find(at.button, "mv2_gen_btn")
        self.assertEqual(spy.call_count, 0)


@unittest.skipUnless(_HAS_APPTEST, "streamlit AppTest 미지원")
class AppWiringMockUploadTest(_WiringMixin, unittest.TestCase):
    """모든 버전에서 실행 — mock UploadedFile 주입으로 배선을 검증(실제 file_uploader 제외)."""
    USE_MOCK = True


@unittest.skipUnless(_HAS_APPTEST and _UPLOAD_SUPPORTED,
                     "file_uploader.upload() 미지원 — 실제 file_uploader 위젯 배선 미검증")
class AppWiringRealUploadTest(_WiringMixin, unittest.TestCase):
    """upload() 지원 버전 전용 — 실제 file_uploader→read_uploads 배선까지 검증."""
    USE_MOCK = False


@unittest.skipUnless(_HAS_APPTEST and _UPLOAD_SUPPORTED,
                     "file_uploader.upload() 미지원 — 실제 업로드 경로 미검증")
class RealUploadReadUploadsTest(unittest.TestCase):
    """실제 file_uploader.upload → 실제 read_uploads → 지문/preview까지(HTTP만 mock)."""

    def test_real_upload_reaches_preview(self):
        spy = mock.Mock(return_value=mc.Result(ok=True, payload=_decoded_gen_payload()))
        at = AppTest.from_file(_APP)
        patches = [
            mock.patch.object(mc, "fetch_options",
                              return_value=mc.Result(ok=True, payload=_OPTIONS)),
            mock.patch.object(mc, "run_preview",
                              return_value=mc.Result(ok=True, payload=dict(_PREVIEW))),
            mock.patch.object(mc, "run_generate", spy),
        ]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        at.run(timeout=30)
        # read_uploads는 mock하지 않는다 — 실제 UploadedFile을 실제 read_uploads가 처리
        at.get("file_uploader")[0].upload("prod.png", _png_bytes()).run(timeout=30)
        _find(at.button, "mv2_preview_btn").click().run(timeout=30)
        self.assertIsNotNone(at.session_state["mv2_state"].preview)
        self.assertEqual(len(list(at.exception)), 0)
        self.assertEqual(spy.call_count, 0)


if __name__ == "__main__":
    unittest.main()
