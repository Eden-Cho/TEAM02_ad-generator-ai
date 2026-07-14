FROM python:3.10-slim

WORKDIR /app

# 1. 시스템 의존성 설치 (한글 폰트)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum && rm -rf /var/lib/apt/lists/*

# 2. 패키지 설치 최적화
COPY requirements.txt .

RUN pip install --upgrade pip

# pip 캐시 디렉토리를 도커 빌드 캐시에 마운트하여 대용량 패키지 다운로드 중 튕김 현상을 방지합니다.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

# 소스코드 내부에서 import 경로가 꼬이지 않도록 파이썬 경로 매핑
ENV PYTHONPATH=/app:/app/backend:/app/model

ENV FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]