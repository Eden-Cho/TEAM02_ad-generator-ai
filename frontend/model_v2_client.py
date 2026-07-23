"""model-v2 테스트 UI의 순수 로직·HTTP 헬퍼 (Streamlit 비의존 — 단위 테스트 대상).

계약:
- worker 주소는 `MODEL_V2_BACKEND_URL`(기본 http://127.0.0.1:8010). 그 외 주소는 쓰지 않는다.
- 엔드포인트는 /api/model-v2/{options,preview,generate-detail-page} 만 사용.
- 유료 생성은 **preview 성공 + 사용자 확인 + 입력 지문 일치**가 모두 참일 때만 가능(can_generate).
- 입력·파일이 바뀌면 지문이 달라져 preview·확인이 무효화된다.
- 네트워크 예외·non-200은 **고정 문구**만 반환한다(URL·응답 body·예외 원문 비노출).
- API 키·토큰은 요청 body에 넣지 않는다(worker가 자체 환경에서 사용).
"""
import base64
import binascii
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

import requests
from PIL import Image

DEFAULT_BACKEND_URL = "http://127.0.0.1:8010"

# 고정 오류 문구 — URL·응답 body·예외 원문을 절대 담지 않는다.
ERR_NETWORK = "model-v2 워커에 연결하지 못했습니다. 워커(포트 8010)가 실행 중인지 확인하세요."
ERR_SERVER = "요청을 처리하지 못했습니다. 입력을 확인하고 잠시 후 다시 시도해주세요."

_OPTIONS_PATH = "/api/model-v2/options"
_PREVIEW_PATH = "/api/model-v2/preview"
_GENERATE_PATH = "/api/model-v2/generate-detail-page"


def backend_url() -> str:
    return os.getenv("MODEL_V2_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


@dataclass(frozen=True)
class ImageFile:
    """업로드 이미지 한 장 — 멀티파트 전송 시 순서·이름·바이트를 그대로 보존한다."""
    name: str
    data: bytes
    content_type: str = "image/png"


@dataclass
class Result:
    """HTTP 결과 — ok면 payload, 아니면 error(고정 문구). 원문·URL은 담지 않는다."""
    ok: bool
    payload: Optional[dict] = None
    error: Optional[str] = None


def read_uploads(uploads) -> list:
    """Streamlit UploadedFile 목록 → ImageFile 목록(순서 보존).

    UI와 배선 테스트의 공통 진입점(테스트에서 이 함수만 mock하면 file_uploader 없이도
    실제 app 배선을 실행할 수 있다). name·bytes·content_type를 그대로 담는다.
    """
    out = []
    for u in uploads or []:
        out.append(ImageFile(name=u.name, data=u.getvalue(),
                             content_type=(getattr(u, "type", None) or "image/png")))
    return out


def build_multipart(product: list, app: Optional[list]) -> list:
    """requests files= 인자 — (필드명, (파일명, 바이트, content_type)) 튜플 목록.

    product_files 먼저, 이어서 app_files. 목록 내 순서·파일명·바이트를 그대로 보존한다.
    """
    parts = []
    for f in product or []:
        parts.append(("product_files", (f.name, f.data, f.content_type)))
    for f in app or []:
        parts.append(("app_files", (f.name, f.data, f.content_type)))
    return parts


def input_fingerprint(req: dict, product: list, app: Optional[list],
                      theme_name: str = "light") -> str:
    """입력 전체의 결정론적 지문. req·테마·(파일 필드/이름/바이트해시)가 하나라도 바뀌면 달라진다.

    파일 바이트는 sha256으로 요약해 지문에 반영 → 같은 이름의 다른 파일도 구분한다.
    """
    h = hashlib.sha256()
    h.update(json.dumps(req, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    h.update(b"\x00theme\x00")
    h.update(theme_name.encode("utf-8"))
    for field_name, files in (("product_files", product), ("app_files", app)):
        h.update(b"\x00" + field_name.encode("utf-8") + b"\x00")
        for f in files or []:
            h.update(f.name.encode("utf-8"))
            h.update(b"\x00")
            h.update(hashlib.sha256(f.data).digest())
            h.update(b"\x00")
    return h.hexdigest()


# ── 승인 상태 머신 (순수) ─────────────────────────────────────────────────────
@dataclass
class ApprovalState:
    preview: Optional[dict] = None       # preview 응답(성공 시)
    preview_fp: Optional[str] = None     # preview 시점 입력 지문
    approved: bool = False               # "유료 호출을 확인했습니다" 체크 여부


def initial_state() -> ApprovalState:
    return ApprovalState()


def apply_preview(state: ApprovalState, fp: str, preview_payload: dict) -> ApprovalState:
    """preview 성공 반영 — 지문 고정, 승인은 항상 초기화(다시 명시 체크 필요)."""
    state.preview = preview_payload
    state.preview_fp = fp
    state.approved = False
    return state


def set_approval(state: ApprovalState, checked: bool) -> ApprovalState:
    state.approved = bool(checked)
    return state


def sync_inputs(state: ApprovalState, current_fp: str) -> ApprovalState:
    """매 렌더 호출 — 입력 지문이 preview 시점과 다르면 preview·승인을 무효화한다."""
    if state.preview_fp is not None and current_fp != state.preview_fp:
        state.preview = None
        state.preview_fp = None
        state.approved = False
    return state


def can_generate(state: ApprovalState, current_fp: str) -> bool:
    """유료 생성 허용 조건 — preview 성공 + 명시 승인 + 현재 입력이 preview와 동일."""
    return (state.preview is not None
            and state.approved
            and current_fp == state.preview_fp)


# ── 응답 폐쇄 검증 (잘못된 JSON·필드·base64·이미지·타입을 UI 前에서 차단) ──────
class _BadResponse(Exception):
    """검증 실패 — 원문은 담지 않는다(호출부가 고정 문구로 대체)."""


def _require(cond) -> None:
    if not cond:
        raise _BadResponse()


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _decode_image(b64, fmt: str) -> bytes:
    """base64 → 바이트, 실제 디코딩·포맷 검증. 손상·형식불일치는 _BadResponse."""
    _require(isinstance(b64, str) and b64)
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise _BadResponse()
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.verify()                      # 손상 검출
        with Image.open(io.BytesIO(raw)) as im2:
            actual = im2.format              # verify 후 재오픈해야 안전
    except Exception:
        raise _BadResponse()
    _require(actual == fmt)
    return raw


def parse_preview(payload) -> dict:
    """preview 응답 폐쇄 검증 — 역할·경로·씬·예상 호출 수 타입 확인. 위반은 _BadResponse."""
    _require(isinstance(payload, dict))
    _require(isinstance(payload.get("presentation_mode"), str))
    _require(isinstance(payload.get("product_form"), str))
    _require(_str_list(payload.get("roles")))
    cuts = payload.get("cuts")
    _require(isinstance(cuts, list))
    for c in cuts:
        _require(isinstance(c, dict))
        _require(isinstance(c.get("role"), str))
        _require(isinstance(c.get("intended_path"), str))
        _require(c.get("angle") is None or isinstance(c.get("angle"), str))
        _require(c.get("scene_id") is None or isinstance(c.get("scene_id"), str))
    ec = payload.get("expected_calls")
    _require(isinstance(ec, dict))
    for k in ("images_generate", "images_edit", "passthrough", "llm_logical_max"):
        _require(_is_int(ec.get(k)))
    return payload


def parse_generate(payload) -> dict:
    """generate 응답 폐쇄 검증 — 이미지를 실제 디코딩(PNG·JPEG)하고 필드 타입을 확인한다.

    성공 시 UI가 예외 위험 없이 바로 쓸 수 있게 **디코딩된 바이트**를 담아 돌려준다.
    """
    _require(isinstance(payload, dict))
    dp = _decode_image(payload.get("detail_page"), "PNG")
    main = _decode_image(payload.get("main"), "JPEG")
    gallery = payload.get("gallery")
    _require(isinstance(gallery, list))
    gal = [_decode_image(g, "JPEG") for g in gallery]
    _require(_is_num(payload.get("seconds")))
    warnings = payload.get("warnings", [])
    _require(_str_list(warnings))
    trace = payload.get("trace", {})
    _require(isinstance(trace, dict))
    geo_html = payload.get("geo_html", "")
    _require(isinstance(geo_html, str))
    structured_data = payload.get("structured_data", [])
    _require(isinstance(structured_data, list))
    faq = payload.get("faq", [])
    _require(isinstance(faq, list))
    out = {"seconds": payload["seconds"], "warnings": warnings, "trace": trace,
           "geo_html": geo_html, "structured_data": structured_data, "faq": faq,
           "detail_page_png": dp, "main_jpeg": main, "gallery_jpeg": gal}
    if "evaluation" in payload:
        _require(isinstance(payload["evaluation"], dict))
        out["evaluation"] = payload["evaluation"]
    return out


# ── HTTP (requests는 모듈 속성 — 테스트에서 patch) ────────────────────────────
def _post(path: str, data: dict, product: list, app: Optional[list],
          timeout: int, validate: Callable[[object], dict]) -> Result:
    """공통 POST — 네트워크 예외·non-200·비-JSON·검증 실패를 모두 고정 문구로 흡수한다.

    URL·응답 body·경로·예외 원문·Traceback을 결과에 담지 않는다.
    """
    try:
        resp = requests.post(f"{backend_url()}{path}", data=data,
                             files=build_multipart(product, app), timeout=timeout)
    except requests.RequestException:
        return Result(ok=False, error=ERR_NETWORK)
    if resp.status_code != 200:
        return Result(ok=False, error=ERR_SERVER)
    try:
        payload = resp.json()
    except Exception:
        return Result(ok=False, error=ERR_SERVER)
    try:
        return Result(ok=True, payload=validate(payload))
    except _BadResponse:
        return Result(ok=False, error=ERR_SERVER)


def fetch_options() -> Result:
    try:
        resp = requests.get(f"{backend_url()}{_OPTIONS_PATH}", timeout=10)
    except requests.RequestException:
        return Result(ok=False, error=ERR_NETWORK)
    if resp.status_code != 200:
        return Result(ok=False, error=ERR_SERVER)
    try:
        data = resp.json()
    except Exception:
        return Result(ok=False, error=ERR_SERVER)
    if not isinstance(data, dict):
        return Result(ok=False, error=ERR_SERVER)
    return Result(ok=True, payload=data)


def run_preview(req: dict, product: list, app: Optional[list]) -> Result:
    """무과금 preview — 역할·경로·씬·예상 호출 수만. 유료 호출 없음. 응답은 폐쇄 검증."""
    return _post(_PREVIEW_PATH,
                 {"req_json": json.dumps(req, ensure_ascii=False)},
                 product, app, 30, parse_preview)


def run_generate(req: dict, product: list, app: Optional[list],
                 theme_name: str = "light") -> Result:
    """유료 생성 — 호출부(attempt_generate)가 승인 확인·소비 후에만 부른다. 응답은 폐쇄 검증."""
    return _post(_GENERATE_PATH,
                 {"req_json": json.dumps(req, ensure_ascii=False),
                  "theme_name": theme_name},
                 product, app, 600, parse_generate)


def attempt_generate(state: ApprovalState, current_fp: str, req: dict,
                     product: list, app: Optional[list], theme_name: str,
                     poster: Optional[Callable[..., Result]] = None) -> Result:
    """유료 호출의 유일한 관문 — can_generate가 아니면 **poster 미호출**로 차단한다.

    조건 충족 시 **poster 호출 직전에 승인을 소비**(approved=False)한다. 성공·실패와 무관하게
    다음 유료 호출에는 재승인이 필요하다(연속 클릭·재실행으로 1회 승인이 2회 생성되지 않음).
    preview·preview_fp는 유지한다(같은 입력은 재승인만으로 다시 생성 가능).
    """
    if not can_generate(state, current_fp):
        return Result(ok=False, error="preview·확인 후에만 생성할 수 있습니다.")
    state.approved = False                          # 승인 1회 소비(호출 직전)
    poster = poster or run_generate                 # 호출 시점 해석 → 테스트에서 patch 가능
    return poster(req, product, app, theme_name)
