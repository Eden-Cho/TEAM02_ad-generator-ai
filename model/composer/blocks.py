"""블록별 렌더러 — 각 함수는 page_width 폭의 PIL 이미지(RGB)를 반환한다.

블록 종류: hero / feature / text / spec_table / cta / divider
공통 규칙: 폭 = theme.page_width, 높이 = 내용에 따라 가변.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from composer.theme import Theme


# ---------- 공통 헬퍼 ----------

def _font(theme: Theme, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(theme.font_path, size)


def _load(image) -> Image.Image:
    if isinstance(image, (str, Path)):
        image = Image.open(image)
    return image.convert("RGB")


def fit_width(img: Image.Image, width: int) -> Image.Image:
    w, h = img.size
    if w == width:
        return img
    return img.resize((width, round(h * width / w)), Image.LANCZOS)


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """공백 우선, 넘치면 글자 단위로 줄바꿈 (한글 대응)."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        if draw.textlength(word, font=font) > max_w:   # 단어 자체가 김 → 글자 단위
            s = ""
            for ch in word:
                if draw.textlength(s + ch, font=font) <= max_w:
                    s += ch
                else:
                    lines.append(s)
                    s = ch
            cur = s
        else:
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _line_h(font, size) -> int:
    asc, desc = font.getmetrics()
    return asc + desc + int(size * 0.18)


def _text_panel(theme: Theme, width: int, items: list, align: str = "center",
                pad_top: int = 56, pad_bottom: int = 56) -> Image.Image:
    """items: [(text, size, color, gap_after), ...] → 텍스트 패널 이미지."""
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_w = width - 2 * theme.margin

    prepared = []   # (lines, font, color, gap, line_h)
    total = pad_top + pad_bottom
    for text, size, color, gap in items:
        if not text:
            continue
        font = _font(theme, size)
        lines = _wrap(measure, text, font, max_w)
        lh = _line_h(font, size)
        prepared.append((lines, font, color, gap, lh))
        total += lh * len(lines) + gap

    img = Image.new("RGB", (width, max(total, 1)), theme.bg)
    draw = ImageDraw.Draw(img)
    y = pad_top
    for lines, font, color, gap, lh in prepared:
        for ln in lines:
            if align == "center":
                x = (width - draw.textlength(ln, font=font)) / 2
            else:
                x = theme.margin
            draw.text((x, y), ln, font=font, fill=color)
            y += lh
        y += gap
    return img


# ---------- 블록 렌더러 ----------

def render_hero(theme: Theme, image, headline: str = "", sub: str = "") -> Image.Image:
    """풀블리드 제품 이미지 + 하단 그라디언트 위 헤드라인."""
    img = fit_width(_load(image), theme.page_width).convert("RGBA")
    w, h = img.size

    # 하단 그라디언트 (가독성)
    gh = int(h * 0.55)
    grad = Image.new("L", (1, gh))
    for i in range(gh):
        grad.putpixel((0, i), int(235 * (i / gh)))
    alpha = grad.resize((w, gh))
    band = Image.new("RGBA", (w, gh), theme.bg + (0,))
    band.putalpha(alpha)
    img.alpha_composite(band, (0, h - gh))
    img = img.convert("RGB")

    draw = ImageDraw.Draw(img)
    hf, sf = _font(theme, theme.h1), _font(theme, theme.body)
    max_w = w - 2 * theme.margin
    hlines = _wrap(draw, headline, hf, max_w) if headline else []
    slines = _wrap(draw, sub, sf, max_w) if sub else []
    block_h = sum(_line_h(hf, theme.h1) for _ in hlines) + \
        sum(_line_h(sf, theme.body) for _ in slines) + (20 if slines else 0)
    y = h - block_h - int(h * 0.06)
    for ln in hlines:
        draw.text(((w - draw.textlength(ln, font=hf)) / 2, y), ln, font=hf, fill=theme.text)
        y += _line_h(hf, theme.h1)
    y += 20 if slines else 0
    for ln in slines:
        draw.text(((w - draw.textlength(ln, font=sf)) / 2, y), ln, font=sf, fill=theme.sub)
        y += _line_h(sf, theme.body)
    return img


def render_feature(theme: Theme, image, headline: str = "", sub: str = "",
                   body: str = "", points: list | None = None) -> Image.Image:
    """제품 이미지(위) + 텍스트 패널(아래: 헤드라인/서브/본문/포인트) 스택."""
    top = fit_width(_load(image), theme.page_width)
    items = [(headline, theme.h2, theme.text, 14), (sub, theme.body, theme.sub, 14)]
    if body:
        items.append((body, theme.body, theme.sub, 16))     # 기능 상세 설명 문단
    for p in (points or []):
        items.append((f"· {p}", theme.caption, theme.muted, 6))
    bottom = _text_panel(theme, theme.page_width, items, pad_top=44, pad_bottom=56)

    out = Image.new("RGB", (theme.page_width, top.height + bottom.height), theme.bg)
    out.paste(top, (0, 0))
    out.paste(bottom, (0, top.height))
    return out


def render_text(theme: Theme, headline: str = "", sub: str = "",
                body: str = "") -> Image.Image:
    """텍스트 전용 섹션 (헤드라인 + 서브 + 본문 문단)."""
    items = [(headline, theme.h1, theme.text, 18)]
    if sub:
        items.append((sub, theme.body, theme.sub, 14))
    if body:
        items.append((body, theme.body, theme.sub, 0))
    return _text_panel(theme, theme.page_width, items, pad_top=80, pad_bottom=80)


def render_spec_table(theme: Theme, title: str, rows: list) -> Image.Image:
    """스펙/비교 표. rows = [(label, value), ...]."""
    width = theme.page_width
    title_f, cell_f = _font(theme, theme.h2), _font(theme, theme.body)
    row_h = int(theme.body * 2.1)
    pad = 60
    th = _line_h(title_f, theme.h2)
    height = pad + th + 24 + row_h * len(rows) + pad

    img = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(img)
    draw.text(((width - draw.textlength(title, font=title_f)) / 2, pad),
              title, font=title_f, fill=theme.text)

    y = pad + th + 24
    x_label, x_val = theme.margin, width // 2
    for label, value in rows:
        draw.line([(theme.margin, y), (width - theme.margin, y)], fill=theme.muted, width=1)
        ty = y + (row_h - theme.body) // 2 - 4
        draw.text((x_label, ty), str(label), font=cell_f, fill=theme.sub)
        draw.text((x_val, ty), str(value), font=cell_f, fill=theme.text)
        y += row_h
    draw.line([(theme.margin, y), (width - theme.margin, y)], fill=theme.muted, width=1)
    return img


def render_cta(theme: Theme, text: str) -> Image.Image:
    """구매 유도 — 가운데 버튼형."""
    width = theme.page_width
    f = _font(theme, theme.h2)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    tw = measure.textlength(text, font=f)
    th = _line_h(f, theme.h2)
    btn_w, btn_h, pad = int(tw + 90), int(th + 32), 60
    img = Image.new("RGB", (width, pad * 2 + btn_h), theme.bg)
    draw = ImageDraw.Draw(img)
    x0, y0 = (width - btn_w) // 2, pad
    draw.rounded_rectangle([x0, y0, x0 + btn_w, y0 + btn_h],
                           radius=btn_h // 2, fill=theme.accent)
    draw.text((x0 + (btn_w - tw) / 2, y0 + (btn_h - th) / 2 - 2),
              text, font=f, fill=(255, 255, 255))
    return img


def render_divider(theme: Theme, pad: int = 44) -> Image.Image:
    img = Image.new("RGB", (theme.page_width, pad * 2 + 2), theme.bg)
    ImageDraw.Draw(img).line(
        [(theme.margin, pad), (theme.page_width - theme.margin, pad)],
        fill=theme.muted, width=1)
    return img
