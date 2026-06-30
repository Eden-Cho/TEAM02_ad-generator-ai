from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from model import generator  # 🤖 방금 만든 AI 모듈 불러오기

app = FastAPI(title="AI 광고 생성 분리형 백엔드 시스템")

# API 요청 규격 정의
class AdRequest(BaseModel):
    prompt: str
    steps: int = 25

# 서버 시작 시 AI 모듈 초기화
@app.on_event("startup")
def startup_event():
    generator.initialize_model()

# 이미지 생성 API 엔드포인트
@app.post("/api/generate-ad")
async def generate_ad(request: AdRequest):
    if generator.pipe is None:
        raise HTTPException(status_code=500, detail="AI 모델이 로드되지 않았습니다.")
    
    try:
        print(f"📥 [Main Server] 요청 접수: {request.prompt}")
        
        # AI 전용 파일에 연산 요청 후 결과 스트림 받기
        img_stream = generator.generate_stream(request.prompt, request.steps)
        
        print("✨ [Main Server] 프론트엔드로 휘발성 이미지 스트림 전송")
        return StreamingResponse(img_stream, media_type="image/png")
        
    except Exception as e:
        print(f"🔴 [Main Server] 에러 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))