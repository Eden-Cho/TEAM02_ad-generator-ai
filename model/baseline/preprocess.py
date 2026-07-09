"""제품 사진을 선택한 플랫폼 규격(비율)에 맞춰 전처리.

edit 모드로 보내기 전에 원본을 목표 비율 캔버스에 contain(레터박스)해서
제품이 잘리거나 늘어나지 않도록 하고, 남는 여백은 배경/텍스트 공간으로 쓴다.
"""
from PIL import Image


def parse_size(size: str) -> tuple[int, int]:
    """'1024x1536' -> (1024, 1536)."""
    w, h = size.lower().split("x")
    return int(w), int(h)


def fit_to_ratio(img: Image.Image, target_w: int, target_h: int,
                 bg: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """제품 비율을 유지한 채 target 크기 캔버스 중앙에 배치(레터박스)."""
    img = img.convert("RGB")
    w, h = img.size
    scale = min(target_w / w, target_h / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), bg)
    canvas.paste(resized, ((target_w - nw) // 2, (target_h - nh) // 2))
    return canvas


def fit_path_to_size(image_path: str, size: str) -> Image.Image:
    """파일 경로 + 크기 문자열 -> 전처리된 PIL 이미지."""
    w, h = parse_size(size)
    return fit_to_ratio(Image.open(image_path), w, h)
