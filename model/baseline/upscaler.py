"""업스케일 + 사이트 규격 후처리.  [팀원 담당 baseline]

baseline: PIL Lanczos (CPU, 무료, 디테일 복원은 없음).
TODO(팀원):
 - Real-ESRGAN(주로 L4)으로 교체해 디테일까지 복원
 - 사이트별 실제 규격(네이버 860px 등)으로 리사이즈 규칙 확정
 - 업스케일은 '카피 오버레이 전'에 수행 (글자 계단현상 방지)
"""
from PIL import Image


def upscale(image: Image.Image, scale: int = 2) -> Image.Image:
    """단순 확대 (baseline). scale배 Lanczos 리샘플."""
    w, h = image.size
    return image.resize((w * scale, h * scale), Image.LANCZOS)


def fit_width(image: Image.Image, width: int) -> Image.Image:
    """가로 폭을 플랫폼 규격에 맞춰 비율 유지 리사이즈."""
    w, h = image.size
    if w == width:
        return image
    return image.resize((width, round(h * width / w)), Image.LANCZOS)
