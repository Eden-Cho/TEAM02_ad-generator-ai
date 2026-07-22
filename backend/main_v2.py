"""model-v2 전용 FastAPI 진입점 (별도 워커).

실행: uvicorn main_v2:app --host 0.0.0.0 --port 8010

팀 model/과 model_v2/는 최상위 패키지명(baseline·composer·geo)이 겹친다. 한 인터프리터에 두
트리를 동시에 올릴 수 없으므로 **model-v2는 이 별도 워커로만** 로드한다(팀 main:app은 그대로
팀 model/을 쓴다). 여기서는 model_v2/를 sys.path 맨 앞에 두어 baseline 등이 model_v2로 해석된다.
"""
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(_BACKEND))                       # backend/ (app import)
# model_v2/를 맨 앞에 — 이 워커에서 baseline/composer/geo/evaluation은 model_v2로 해석된다.
sys.path.insert(0, str(_BACKEND.parent / "model_v2"))

from fastapi import FastAPI  # noqa: E402

from app.api.v1.model_v2 import router as v2_router  # noqa: E402

app = FastAPI(title="AI 상세페이지 생성 API — model-v2", version="2.0.0")
app.include_router(v2_router)


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "detail-page-generator-v2"}
