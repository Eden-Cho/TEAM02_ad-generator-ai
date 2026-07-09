# AI 상세페이지 생성 서비스 (Service 01)

제품 사진 + 정보 + 스타일 → **상세페이지(긴 이미지) + 메인/부가 썸네일** 자동 생성.

## 스택
- 텍스트(프롬프트·카피): **gpt-5-mini** (OpenAI API)
- 이미지: **gpt-image-1-mini** (OpenAI API)
- 조립: PIL (composer)
- 프론트: Streamlit

## 디렉토리
```
├── frontend/app.py       # Streamlit UI → 백엔드 HTTP 호출
├── backend/              # FastAPI (model/ 파이프라인을 API로 서빙)
│   ├── main.py           #   앱 진입점 (uvicorn)
│   ├── schemas.py        #   응답 규격
│   └── app/api/v1/generate.py · app/services/pipeline_service.py
├── model/                # 모델 파이프라인 + 데이터
│   ├── baseline/         #   아키타입·프롬프트·카피·이미지 생성
│   ├── composer/         #   상세페이지 조립·썸네일
│   ├── image/ image/usage/   #   업로드 (gitignore)
│   ├── outputs/          #   결과 (gitignore)
│   └── .env              #   API 키 (gitignore)
├── requirements.txt
```

## 실행
```bash
pip install -r requirements.txt
cp model/.env.example model/.env    # → OPENAI_API_KEY 입력

# 터미널 1 — 백엔드 (FastAPI, 포트 8000)
cd backend && uvicorn main:app --reload

# 터미널 2 — 프론트 (Streamlit, 포트 8501)
streamlit run frontend/app.py
```
> 프론트가 백엔드(`localhost:8000`)에 요청 → 상세페이지·썸네일을 받아 표시.
> 업로드/결과는 서버에 저장되지 않음(임시폴더 자동 삭제 — 휘발성).

## 사용
1. 사이드바에서 스타일(사이트규격·밝기·무드·톤 등) 선택
2. 상품명·카테고리·스펙 입력 + 제품 이미지 업로드 (+응용 이미지 선택)
3. **[상세페이지 생성]** → 상세이미지 + 썸네일 출력·다운로드

> 비용: 생성마다 이미지 컷 수 × ~$0.02 (gpt-image-1-mini).
