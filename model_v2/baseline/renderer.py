"""생성 이미지 위에 한글 카피를 PIL로 오버레이한다.

헤드라인 + 서브 + 소구 포인트(points)를 그리며, 내용 양에 따라
반투명 띠 높이를 자동 조절한다.
"""
from PIL import Image, ImageDraw, ImageFont

import baseline.config as config


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(config.FONT_PATH, size)


def _text_h(draw, text, font) -> int:
    b = draw.textbbox((0, 0), text, font=font)
    return b[3] - b[1]


def render(img: Image.Image, copy: dict, text_zone: str = "bottom") -> Image.Image:
    """text_zone 위치에 반투명 띠 + 한글 카피(헤드라인/서브/포인트)를 얹는다."""
    if text_zone == "none" or not copy:
        return img.convert("RGB")

    img = img.convert("RGB")
    w, h = img.size

    headline_font = _font(int(w * 0.055))
    sub_font = _font(int(w * 0.032))
    point_font = _font(int(w * 0.028))

    # 그릴 줄 구성 (텍스트, 폰트, 색)
    lines: list[tuple[str, ImageFont.FreeTypeFont, tuple]] = []
    if copy.get("headline"):
        lines.append((copy["headline"], headline_font, (255, 255, 255)))
    if copy.get("sub"):
        lines.append((copy["sub"], sub_font, (232, 232, 232)))
    for p in (copy.get("points") or [])[:3]:
        lines.append((f"· {p}", point_font, (215, 215, 215)))
    if not lines:
        return img

    draw = ImageDraw.Draw(img)
    gap = int(h * 0.013)
    heights = [_text_h(draw, t, f) for t, f, _ in lines]
    band_h = min(sum(heights) + gap * (len(lines) + 2), int(h * 0.5))
    y0 = 0 if text_zone == "top" else h - band_h

    # 가독성용 반투명 검정 띠
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle([0, y0, w, y0 + band_h], fill=(0, 0, 0, 135))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    y = y0 + gap
    for (text, font, color), th in zip(lines, heights):
        b = draw.textbbox((0, 0), text, font=font)
        tw = b[2] - b[0]
        draw.text(((w - tw) / 2, y), text, font=font, fill=color)
        y += th + gap
    return img
