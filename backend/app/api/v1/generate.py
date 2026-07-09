"""상세페이지 생성 API 엔드포인트."""
import base64
import io
import json
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.services.pipeline_service import CATEGORIES, run_pipeline, ui_dimensions
from schemas import GenerateResponse

router = APIRouter(prefix="/api")


@router.get("/options")
def options():
    """프론트가 사이드바를 그리기 위한 스타일 옵션·카테고리 목록."""
    return {"style_dimensions": ui_dimensions(), "categories": CATEGORIES}


def _b64(img, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


async def _save(files, folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, uf in enumerate(files or []):
        p = folder / f"{i:02d}_{uf.filename}"
        p.write_bytes(await uf.read())
        paths.append(str(p))
    return paths


@router.post("/generate-detail-page", response_model=GenerateResponse)
async def generate_detail_page(
    req_json: str = Form(...),
    theme_name: str = Form("light"),
    product_files: List[UploadFile] = File(...),
    app_files: Optional[List[UploadFile]] = File(None),
):
    """제품정보(JSON) + 이미지(multipart) → 상세페이지 + 썸네일 (base64)."""
    if not product_files:
        raise HTTPException(400, "제품 이미지가 1장 이상 필요합니다.")
    req = json.loads(req_json)

    # 업로드를 임시 폴더에 저장 → 파이프라인 실행 → 자동 정리 (서버에 안 남김)
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        product_paths = await _save(product_files, tp / "product")
        app_paths = await _save(app_files, tp / "usage")
        try:
            r = run_pipeline(req, product_paths, app_paths, theme_name)
        except Exception as e:
            raise HTTPException(500, f"생성 실패: {e}")

    return GenerateResponse(
        detail_page=_b64(r["page"], "PNG"),
        main=_b64(r["main"], "JPEG"),
        gallery=[_b64(g, "JPEG") for g in r["gallery"]],
        seconds=r["seconds"],
    )
