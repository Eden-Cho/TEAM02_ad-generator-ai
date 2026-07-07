import os

MODEL_ID = "runwayml/stable-diffusion-v1-5"
SAVE_DIR = "saved_images"

# 저장 폴더가 없으면 자동 생성
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)