"""model-v2 전용 FastAPI 진입점 (별도 워커).

실행: uvicorn main_v2:app --host 127.0.0.1 --port 8010

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
from starlette.responses import JSONResponse  # noqa: E402

from app.api.v1.model_v2 import (GENERATE_PATH, PAID_DISABLED_MSG,  # noqa: E402
                                 paid_enabled)
from app.api.v1.model_v2 import router as v2_router  # noqa: E402


class PaidGateMiddleware:
    """유료 생성 차단 게이트 — **순수 ASGI 미들웨어**(기본 비활성).

    비활성일 때 generate 요청을 **body를 읽기 전에** 고정 응답으로 끊는다. receive를 호출하지
    않으므로 multipart 파싱·임시파일 저장·run_pipeline·LLM·이미지 API에 도달하지 않는다
    (엔드포인트 핸들러에 진입 자체를 못 한다). preview·options는 무과금이라 통과시킨다.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope.get("type") == "http"
                and scope.get("method") == "POST"
                and scope.get("path") == GENERATE_PATH
                and not paid_enabled()):
            response = JSONResponse({"detail": PAID_DISABLED_MSG}, status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app = FastAPI(title="AI 상세페이지 생성 API — model-v2", version="2.0.0")
app.add_middleware(PaidGateMiddleware)
app.include_router(v2_router)


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "detail-page-generator-v2"}
