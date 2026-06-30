# 🎨 AI 브랜드 광고 제작소 (Ad Generator AI)

본 프로젝트는 로컬 GPU 인프라를 활용하여 사용자가 입력한 문장을 기반으로 광고 이미지를 실시간 생성하는 서비스의 **AI 파이프라인 및 백엔드 베이스라인 프로토타입**. 

효율적인 비용 관리를 위해 **휘발성 아키텍처**와 **기능별 모듈화 구조**로 제작.

---

## 🏗️ 서비스 아키텍처 (Architecture)

본 시스템은 협업 최적화 및 향후 GCP(Google Cloud Platform)로의 매끄러운 이전을 위해 프론트엔드와 백엔드를 분리된 구조로 설계.

```text
[프론트엔드: Streamlit] ──(HTTP API 요청)──> [백엔드 API: FastAPI]
          │                                            │
   (화면 즉시 렌더링)                                (한글 자동 번역)
          │                                            │
[유저 선택적 다운로드] <──(메모리 스트림 반환)── [AI 모델 추론: SD 1.5]
```

# 📁 폴더 구조 (Directory Structure)
ad-generator-ai/
├── backend/
│   ├── main.py       # FastAPI 웹 서버 구동 및 API 엔드포인트 관리 (CORS 설정 포함)
│   └── model.py      # AI 모델(Stable Diffusion) 로드, 한글 번역 및 추론 연산 전용 모듈
├── frontend/
│   └── app.py        # Streamlit 기반 UI 화면 및 이미지 다운로드 인터페이스
└── README.md         # 프로젝트 가이드 문서

# 🚀 로컬 실행 방법 (How to Run)
1. 가상환경 활성화
conda activate ad-env
2. 백엔드 서버 가동 (Terminal 1)
cd backend
uvicorn main:app --reload --port 8000
3. 프론트엔드 웹 가동 (Terminal 2)
cd frontend
streamlit run app.py