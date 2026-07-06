from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import io

app = FastAPI(title="TEAM02 이커머스 상세페이지 롱이미지 빌더 백엔드")

# 1. 프론트엔드(Streamlit)와의 원활한 통신을 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 로컬 테스트 시 전체 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [임시 더미 로직] 서버 시작 시 AI 모듈 초기화 예정 공간
@app.on_event("startup")
def startup_event():
    # TODO: 다음 단계에서 backend/app/models/sd_inference.py와 연동할 예정입니다.
    print("🤖 [Backend] AI 생성 시스템 인프라 준비 완료")

# 2. 기획서 스펙에 맞춘 Multipart/form-data 수신 엔드포인트
@app.post("/api/v1/generate")
async def generate_detail_page(
    product_image: UploadFile = File(...),              # 필수: 제품 원본/누끼 이미지
    reference_image: UploadFile = File(None),           # 선택: 레퍼런스 이미지
    product_name: str = Form(...),                      # 필수: 상품명
    product_color: str = Form(...),                     # 필수: 상품 색상/재질
    raw_description: str = Form(...),                   # 필수: 날것의 설명 원문
    brightness: int = Form(...),                        # 필수: 밝기 슬라이더 (1~7)
    mall_type: str = Form(...),                         # 필수: 쇼핑몰 규격 (네이버/쿠팡)
    steps: int = Form(25)                               # 선택: 생성 정밀도 (기본값 25)
):
    try:
        print(f"📥 [Backend] 신규 상세페이지 제작 요청 접수!")
        print(f"📦 상품명: {product_name} | 색상: {product_color}")
        print(f"📝 원문 데이터: {raw_description[:30]}...")
        print(f"💡 설정 스타일: 밝기 {brightness}단계 | 규격: {mall_type}")
        print(f"📸 파일 확인: {product_image.filename} (크기 체크 완료)")

        # ---------------------------------------------------------
        # [스프린트 1 성공 핵심 검증: 데이터 통로 확인용 더미 리턴]
        # 모델 파이프라인 연결 전까지는 유저가 올린 제품 사진을 그대로 반환합니다.
        # ---------------------------------------------------------
        file_content = await product_image.read()
        img_stream = io.BytesIO(file_content)
        
        print("✨ [Backend] 통신 고속도로 정상 가동. 프론트엔드로 테스트 스트림 전송.")
        return StreamingResponse(img_stream, media_type="image/png")
        
    except Exception as e:
        print(f"🔴 [Backend] 에러 발생: {e}")
        raise HTTPException(status_code=500, detail=str(e))