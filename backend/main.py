"""FastAPI 진입점 — 상세페이지 생성 API.

실행: uvicorn main:app --reload   (backend/ 폴더에서)
"""
import sys
from pathlib import Path

# backend/ 를 경로에 추가 (app, schemas import)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI  # noqa: E402

from app.api.v1.generate import router  # noqa: E402

app = FastAPI(title="AI 상세페이지 생성 API", version="0.1.0")
app.include_router(router)


@app.get("/")
def health():
    return {"status": "ok", "service": "detail-page-generator"}
