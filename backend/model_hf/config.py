# model_hf/config.py
import os
import torch
from dotenv import load_dotenv
from pathlib import Path

# 🎯 실행 위치에 상관없이 현재 model_hf 폴더 바로 밑의 .env를 강제로 로드합니다.
current_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=current_dir / ".env")

# .env에서 허깅페이스 토큰 안전하게 로드
token_raw = os.getenv("HF_TOKEN", "").strip()
HF_TOKEN = token_raw if token_raw else None

# 모델 서열 1위 세팅
NEW_TEXT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
NEW_IMAGE_MODEL = "black-forest-labs/FLUX.1-schnell" 

# 하드웨어 가속 사양 체크
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
TORCH_DTYPE = torch.bfloat16 if DEVICE == "cuda" else torch.float32

# 물리 이미지 파일 저장 경로
OUTPUT_DIR = "./backend/app/static/generated_images"
os.makedirs(OUTPUT_DIR, exist_ok=True)