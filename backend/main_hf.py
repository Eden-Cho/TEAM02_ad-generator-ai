"""FastAPI 진입점 — HuggingFace 오픈소스 전용 API 엔드포인트."""
import sys
from pathlib import Path
import json
import time
import base64
import os
from fastapi import FastAPI, Form, UploadFile, File
from typing import List, Optional
from langfuse import observe

NANUM_FONT = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
os.environ["FONT_PATH"] = NANUM_FONT

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "model_hf"))

# 🎯 허깅페이스 전용 파이프라인 직접 연결
from model_hf.pipeline_hf import run_pipeline_hf
from baseline.style_presets import ui_dimensions

app = FastAPI(title="HuggingFace 전용 로컬 AI 광고 생성 엔진", version="1.0.0")

@app.get("/")
def health():
    return {"status": "ok", "engine": "huggingface-local-only"}

@app.post("/api/generate-detail-page")
@observe(name="hf_detail_page_pipeline") # 🎯 랭퓨즈 트레이스 이름을 HF 전용으로 박제
async def generate_detail_page(
    req_json: str = Form(...),
    theme_name: str = Form("light"),
    product_files: List[UploadFile] = File(...),
    app_files: Optional[List[UploadFile]] = File(None)
):
    start_time = time.time()
    req = json.loads(req_json)
    
    product_paths = []
    app_paths = []
    upload_dir = Path("/tmp/hf_uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. 임시 이미지 파일 로컬 저장
        for i, f in enumerate(product_files):
            suffix = Path(f.filename).suffix if f.filename else ".png"
            file_path = upload_dir / f"prod_{i}_{int(time.time())}{suffix}"
            with open(file_path, "wb") as buffer:
                buffer.write(await f.read())
            product_paths.append(str(file_path))
            
        for i, f in enumerate(app_files or []):
            suffix = Path(f.filename).suffix if f.filename else ".png"
            file_path = upload_dir / f"app_{i}_{int(time.time())}{suffix}"
            with open(file_path, "wb") as buffer:
                buffer.write(await f.read())
            app_paths.append(str(file_path))

        # 🎯 2. 분기 없이 100% 로컬 허깅페이스 파이프라인으로 다이렉트 런!
        result = run_pipeline_hf(req, product_paths, app_paths, theme_name=theme_name)
        
        # 3. Base64 인코딩 반환
        import io
        def to_b64(pil_img):
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        return {
            "detail_page": to_b64(result["page"]),
            "main": to_b64(result["main"]),
            "gallery": [to_b64(g) for g in result["gallery"]],
            "seconds": round(time.time() - start_time, 1)
        }

    finally:
        for path in product_paths + app_paths:
            if os.path.exists(path):
                os.remove(path)