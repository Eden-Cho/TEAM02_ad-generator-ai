FROM python:3.10-slim

WORKDIR /app

# 1. --no-install-recommends 철자 오류를 완벽하게 교정하여 한글 폰트를 설치하는 구간이다.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum && rm -rf /var/lib/apt/lists/*

# 2. 필수 패키지 설치
RUN pip install --no-cache-dir uvicorn fastapi python-multipart python-dotenv openai Pillow

COPY . .

# 3. 팀원들의 config.py가 정확한 나눔고딕 확장자(.ttf) 경로를 바라보도록 환경 변수를 매핑한다.
ENV FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]