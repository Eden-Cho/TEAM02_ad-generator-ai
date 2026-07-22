"""베이스라인 전역 설정. .env에서 값을 읽어온다."""
import os
from pathlib import Path

from dotenv import load_dotenv

# 경로
BASE_DIR = Path(__file__).resolve().parent.parent

# 실행 위치(cwd)와 무관하게 항상 프로젝트 루트의 .env를 읽는다.
# override=False: **실제 프로세스 환경변수가 .env보다 우선한다** — 배포 환경(컨테이너·
# CI·PaaS)이 주입한 값을 로컬 .env가 덮어쓰면 안 된다. .env는 비어 있는 값의 폴백일 뿐.
# (이전 override=True에서는 OS env로 IMAGE_MODEL을 지정해도 .env가 덮어써, 모델 전환에
#  런타임 monkeypatch가 필요했다 — step4D에서 재현된 결함.)
load_dotenv(BASE_DIR / ".env", override=False)

INPUT_DIR = BASE_DIR / "image"   # 제품 사진을 넣어두는 폴더
OUTPUT_DIR = BASE_DIR / "outputs"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def find_product_images() -> list[Path]:
    """image/ 폴더의 제품 사진을 이름순으로 모두 반환.

    파일명을 원하는 슬롯 순서로 지어두면 그 순서대로 컷에 매핑된다.
    (예: 01_hero.jpg, 02_detail.jpg, 03_lifestyle.jpg)
    """
    return sorted(f for f in INPUT_DIR.iterdir()
                  if f.suffix.lower() in _IMAGE_EXTS)


def find_product_image() -> Path | None:
    """첫 번째 제품 사진 (단일 사용 호환용)."""
    files = find_product_images()
    return files[0] if files else None


def find_usage_images() -> list[Path]:
    """응용/사용 이미지 (image/usage/ 하위). 손·모델·사용장면 사진 → usage 슬롯 전용.

    프론트의 '응용 이미지' 버킷에 대응. 폴더 없으면 빈 리스트.
    """
    d = INPUT_DIR / "usage"
    if not d.exists():
        return []
    return sorted(f for f in d.iterdir() if f.suffix.lower() in _IMAGE_EXTS)

# API / 모델
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TEXT_MODEL = os.getenv("TEXT_MODEL", "gpt-5.4-mini")
# 텍스트 LLM 엔드포인트. 비우면 OpenAI. Ollama면 http://localhost:11434/v1
TEXT_BASE_URL = os.getenv("TEXT_BASE_URL", "")
# 운영 기본 이미지 모델 — gpt-image-2 (2026-07-17 실호출 성공: generate 2회·다중참조 edit 1회).
# 환경변수 IMAGE_MODEL이 지정되면 그 값이 우선. 자동 폴백 없음 — 모델 API 오류는 그대로 올라온다.
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")

# 한글 폰트 — Docker(fonts-nanum) 기본, 없으면 존재하는 후보로 자동 폴백.
# FONT_PATH 로 명시하면 그 경로 우선. (Docker=Nanum / macOS=AppleSDGothicNeo 둘 다 동작)
_FONT_CANDIDATES = [
    os.getenv("FONT_PATH"),                                    # 명시 경로(우선)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",        # Docker/Linux (fonts-nanum)
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",             # macOS
]
FONT_PATH = next(
    (p for p in _FONT_CANDIDATES if p and os.path.exists(p)),
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",        # 최종 기본(Docker)
)

# 로컬 SDXL 실험 (baseline_02) 설정
SDXL_BASE_MODEL = os.getenv("SDXL_BASE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
SDXL_INPAINT_MODEL = os.getenv("SDXL_INPAINT_MODEL",
                               "diffusers/stable-diffusion-xl-1.0-inpainting-0.1")
SDXL_VAE = os.getenv("SDXL_VAE", "madebyollin/sdxl-vae-fp16-fix")
SDXL_STEPS = int(os.getenv("SDXL_STEPS", "30"))
# MPS(Apple)에서 float16은 검은 이미지(NaN) 발생 → 기본 float32.
# 빠르게 실험하려면 bfloat16 시도 (float16은 비권장).
SDXL_DTYPE = os.getenv("SDXL_DTYPE", "float32")
