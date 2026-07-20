"""FastAPI 진입점 — 상세페이지 생성 API 메인 구간이다.

실행: uvicorn main:app --reload
"""
import sys
from pathlib import Path
import json
import time
import base64
import os

# 🎯 랭퓨즈 관측용 데코레이터 임포트
from langfuse import observe

NANUM_FONT = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
os.environ["FONT_PATH"] = NANUM_FONT
os.environ["font_path"] = NANUM_FONT
os.environ["APPLE_FONT"] = NANUM_FONT
os.environ["SYSTEM_FONT"] = NANUM_FONT

# backend/ 및 상위 경로를 파이썬 경로에 주입하여 모듈 누락을 방지하는 구간이다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "model"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "model"))

from fastapi import FastAPI, Form, UploadFile, File
from typing import List, Optional

# 파이프라인 핵심 함수 및 10대 옵션 명세를 로드하는 구간이다.
from app.services.pipeline_service import run_pipeline, CATEGORIES
from baseline.style_presets import ui_dimensions

app = FastAPI(title="AI 상세페이지 생성 API", version="0.1.0")


@app.get("/")
def health():
    return {"status": "ok", "service": "detail-page-generator"}


@app.get("/api/options")
def get_options():
    """style_presets 테이블에서 10가지 옵션을 실시간 추출해 반환하는 구간이다."""
    return {
        "style_dimensions": ui_dimensions(),
        "categories": CATEGORIES
    }


# 🎯 [수정] 랭퓨즈 추적 레이어 주입 (대시보드에 나타날 트레이스 이름 지정)
@app.post("/api/generate-detail-page")
@observe(name="generate_detail_page_pipeline")
async def generate_detail_page(
    req_json: str = Form(...),
    theme_name: str = Form("light"),
    product_files: List[UploadFile] = File(...),
    app_files: Optional[List[UploadFile]] = File(None)
):
    """팀원의 원본 파이프라인 규격(물리 파일 경로 문자열)에 100% 맞춰 안전하게 파일을 쓰는 구간이다."""
    start_time = time.time()
    req = json.loads(req_json)
    
    product_paths = []
    app_paths = []
    
    # 도커 컨테이너 내부의 안전한 임시 디렉토리를 물리적으로 활용한다.
    upload_dir = Path("/tmp/app_uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. 제품 이미지 파일 저장 (팀원의 이미지 생성 로직이 읽을 수 있는 온전한 물리 경로 빌드)
        for i, f in enumerate(product_files):
            suffix = Path(f.filename).suffix if f.filename else ".png"
            file_path = upload_dir / f"prod_{i}_{int(time.time())}{suffix}"
            
            content = await f.read()
            with open(file_path, "wb") as buffer:
                buffer.write(content)
                
            product_paths.append(str(file_path))
            
        # 2. 응용 이미지 파일 저장
        for i, f in enumerate(app_files or []):
            suffix = Path(f.filename).suffix if f.filename else ".png"
            file_path = upload_dir / f"app_{i}_{int(time.time())}{suffix}"
            
            content = await f.read()
            with open(file_path, "wb") as buffer:
                buffer.write(content)
                
            app_paths.append(str(file_path))

        # 3. 파이프라인 함수 실행 (내부에서 이미지 생성 및 품질 채점/Langfuse 저장이 한 번에 일어납니다)
        result = run_pipeline(req, product_paths, app_paths, theme_name=theme_name)
        
        # 4. 반환된 PIL 이미지를 프론트엔드가 그릴 수 있게 Base64로 안전하게 변환한다.
        import io
        def to_b64(pil_img):
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")

        # pipeline_service가 계산해서 건네준 evaluation 점수를 파싱해 프론트엔드로 전달합니다.
        eval_scores = result.get("evaluation", {"clip": None, "brisque": None, "n_images": 0})

        return {
            "detail_page": to_b64(result["page"]),
            "main": to_b64(result["main"]),
            "gallery": [to_b64(g) for g in result["gallery"]],
            "seconds": round(time.time() - start_time, 1),
            "evaluation": eval_scores  # 🎯 프론트엔드로 최종 전달되는 점수 정보!
        }

    finally:
        # 연산 완료 후 생성된 임시 물리 파일들을 깔끔하게 정리하여 디스크 유실을 방지한다.
        for path in product_paths + app_paths:
            if os.path.exists(path):
                os.remove(path)