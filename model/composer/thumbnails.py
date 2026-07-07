"""썸네일 출력 트랙 — 텍스트 없는 1:1 정사각 (메인이미지·부가이미지용).

상세이미지(composer 긴 페이지, 텍스트 O)와 별개로,
같은 생성 이미지를 재활용해 플랫폼 규격 썸네일을 만든다.

- 메인이미지: 제품 누끼 → 흰배경 1:1 (텍스트/로고 금지 규격)
- 부가이미지: 생성 이미지(연출) → 1:1 크롭, 최대 9장
- 저장: JPG, 모바일 권장 장당 1MB 이하
"""
from pathlib import Path

from PIL import Image


def to_square(img: Image.Image, size: int = 1000, mode: str = "crop",
              bg: tuple = (255, 255, 255)) -> Image.Image:
    """1:1 정사각. mode='crop'=중앙 크롭 / 'pad'=흰 여백 채움."""
    img = img.convert("RGB")
    w, h = img.size
    if mode == "pad":
        s = max(w, h)
        canvas = Image.new("RGB", (s, s), bg)
        canvas.paste(img, ((s - w) // 2, (s - h) // 2))
        img = canvas
    else:
        s = min(w, h)
        left, top = (w - s) // 2, (h - s) // 2
        img = img.crop((left, top, left + s, top + s))
    return img.resize((size, size), Image.LANCZOS)


def main_thumbnail(product_image_path: str, size: int = 1000,
                   bg: tuple = (255, 255, 255)) -> Image.Image:
    """메인이미지: 제품 누끼 → 흰배경 1:1. (rembg 실패 시 원본 crop 폴백)"""
    try:
        from baseline import bg_remover
        rgba = bg_remover.cutout(Image.open(product_image_path))
        canvas = Image.new("RGB", rgba.size, bg)
        canvas.paste(rgba, (0, 0), rgba.convert("RGBA"))
        return to_square(canvas, size, mode="pad", bg=bg)
    except Exception:
        return to_square(Image.open(product_image_path), size, mode="pad", bg=bg)


def gallery_thumbnails(images_by_role: dict, order=None, size: int = 1000,
                       limit: int = 8) -> list[Image.Image]:
    """부가이미지: 생성 이미지들 → 1:1 크롭 (최대 limit장)."""
    roles = order or list(images_by_role.keys())
    imgs = [images_by_role[r] for r in roles if r in images_by_role]
    return [to_square(im, size, mode="crop") for im in imgs[:limit]]


def save_jpg(img: Image.Image, path, max_kb: int = 1000, quality: int = 92) -> Path:
    """JPG 저장. 모바일 권장 용량(max_kb) 초과 시 품질을 낮춰 재저장."""
    path = Path(path)
    q = quality
    while True:
        img.save(path, "JPEG", quality=q, optimize=True)
        if path.stat().st_size <= max_kb * 1024 or q <= 40:
            break
        q -= 8
    return path
