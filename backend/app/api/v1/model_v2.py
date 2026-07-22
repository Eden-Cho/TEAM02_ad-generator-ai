"""model-v2 API (병렬 추가) — /api/model-v2/{options,preview,generate-detail-page}.

팀의 기존 /api/generate-detail-page(generate.py)와 별개다. 최신 run_pipeline 계약을 노출한다.
preview는 유료 호출 0회(역할·경로·씬·예상 호출 수만). 응답 evaluation은 선택 필드.
"""
import base64
import io
import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.services import model_v2_service as svc

router = APIRouter(prefix="/api/model-v2")

_BAD_JSON_MSG = "요청 JSON이 유효하지 않습니다. JSON 객체(object)를 보내주세요."
_BAD_FIELD_MSG = "요청 필드 형식이 올바르지 않습니다."
_PIPELINE_FAIL_MSG = "상세페이지 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
_UPLOAD_LIMIT_MSG = "업로드 파일 수 또는 크기가 허용 범위를 초과했습니다."
PAID_DISABLED_MSG = "유료 생성이 비활성화되어 있습니다. 서버 설정에서 명시적으로 활성화해야 합니다."

# 유료 경로 폐쇄형 스위치 — **기본 비활성**. 명시적으로 "1"일 때만 허용한다
# ("true"·"yes"·"0"·빈 값·오타는 전부 비활성 → 실수로 켜지지 않는다).
PAID_ENABLED_ENV = "MODEL_V2_PAID_ENABLED"
GENERATE_PATH = "/api/model-v2/generate-detail-page"


def paid_enabled() -> bool:
    """요청 시점에 평가한다(테스트·운영에서 재기동 없이 확인 가능)."""
    return os.getenv(PAID_ENABLED_ENV, "").strip() == "1"


def _env_positive_int(name: str, default: int, maximum: int) -> int:
    """양의 정수 env를 폐쇄적으로 검증(기동 시점). 미설정·공백은 기본값, 잘못된 값(비정수·0·
    음수·과도한 값)은 **원문 비노출** 고정 오류로 조기 종료 — read(음수)로 전체 파일이
    적재되는 경로를 원천 차단한다."""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = int(raw.strip())
    except (ValueError, TypeError):
        raise RuntimeError(f"환경변수 {name} 값이 올바르지 않습니다") from None
    if v < 1 or v > maximum:
        raise RuntimeError(f"환경변수 {name} 값이 허용 범위를 벗어났습니다")
    return v


# 항상 양수(파일 수 ≤1000, 파일당 ≤1024MB) — read(상한+1)에 음수가 들어가지 않는다.
_MAX_UPLOAD_FILES = _env_positive_int("MAX_UPLOAD_FILES", 12, 1000)
_MAX_UPLOAD_MB = _env_positive_int("MAX_UPLOAD_MB", 15, 1024)


def _reject_nonstandard(_t):
    raise ValueError("nonstandard-json-number")


def _parse_req(req_json: str) -> dict:
    try:
        req = json.loads(req_json, parse_constant=_reject_nonstandard)
    except Exception:
        raise HTTPException(400, _BAD_JSON_MSG) from None
    if not isinstance(req, dict):
        raise HTTPException(400, _BAD_JSON_MSG)
    return req


def _safe_name(filename, default: str) -> str:
    name = Path(str(filename or "").replace("\\", "/")).name
    return name if name and name not in (".", "..") else default


async def _save(files, folder: Path) -> list:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, uf in enumerate(files or []):
        data = await uf.read(_MAX_UPLOAD_MB * 1024 * 1024 + 1)
        if len(data) > _MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(400, _UPLOAD_LIMIT_MSG)
        p = folder / f"{i:02d}_{_safe_name(uf.filename, 'upload')}"
        p.write_bytes(data)
        paths.append(str(p))
    return paths


def _b64(img, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


@router.get("/options")
def options():
    return svc.options()


@router.post("/preview")
async def preview(
    req_json: str = Form(...),
    product_files: List[UploadFile] = File(...),
    app_files: Optional[List[UploadFile]] = File(None),
):
    """유료 호출 0회 — 역할·경로·씬·예상 호출 수만 반환."""
    if not product_files:
        raise HTTPException(400, "제품 이미지가 1장 이상 필요합니다.")
    if len(product_files) + len(app_files or []) > _MAX_UPLOAD_FILES:
        raise HTTPException(400, _UPLOAD_LIMIT_MSG)
    req = _parse_req(req_json)
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        product_paths = await _save(product_files, tp / "product")
        app_paths = await _save(app_files, tp / "usage")
        try:
            return svc.preview(req, product_paths, app_paths)
        except ValueError:
            raise HTTPException(400, _BAD_FIELD_MSG) from None
        except Exception as e:
            print(f"[model-v2/preview] error_type={type(e).__name__}", flush=True)
            raise HTTPException(500, _PIPELINE_FAIL_MSG) from None


@router.post("/generate-detail-page")
async def generate(
    req_json: str = Form(...),
    theme_name: str = Form("light"),
    product_files: List[UploadFile] = File(...),
    app_files: Optional[List[UploadFile]] = File(None),
):
    """최신 run_pipeline 계약. 응답: detail_page·main·gallery·seconds·geo_html·structured_data·
    faq·warnings·trace (+ evaluation 선택)."""
    if not product_files:
        raise HTTPException(400, "제품 이미지가 1장 이상 필요합니다.")
    if len(product_files) + len(app_files or []) > _MAX_UPLOAD_FILES:
        raise HTTPException(400, _UPLOAD_LIMIT_MSG)
    req = _parse_req(req_json)
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        product_paths = await _save(product_files, tp / "product")
        app_paths = await _save(app_files, tp / "usage")
        try:
            r = svc.run(req, product_paths, app_paths, theme_name)
        except ValueError:
            raise HTTPException(400, _BAD_FIELD_MSG) from None
        except Exception as e:
            print(f"[model-v2/generate] error_type={type(e).__name__}", flush=True)
            raise HTTPException(500, _PIPELINE_FAIL_MSG) from None

    body = {
        "detail_page": _b64(r["page"], "PNG"),
        "main": _b64(r["main"], "JPEG"),
        "gallery": [_b64(g, "JPEG") for g in r["gallery"]],
        "seconds": r["seconds"],
        "geo_html": r.get("geo_html", ""),
        "structured_data": r.get("structured_data", []),
        "faq": r.get("faq", []),
        "warnings": r.get("warnings", []),
        "trace": r.get("trace", {}),
    }
    if "evaluation" in r:                        # 선택 필드
        body["evaluation"] = r["evaluation"]
    return JSONResponse(content=body)
