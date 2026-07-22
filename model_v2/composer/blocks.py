"""블록별 렌더러 — 각 함수는 page_width 폭의 PIL 이미지(RGB)를 반환한다.

블록 종류: hero / feature / text / spec_table / cta / divider
공통 규칙: 폭 = theme.page_width, 높이 = 내용에 따라 가변.
"""
import unicodedata
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from baseline.composition_policy import copy_placement_of
from composer.theme import Theme


# ---------- 공통 헬퍼 ----------

def _font(theme: Theme, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(theme.font_path, size)


# 폰트에 없어 깨지는 특수문자(비표준 하이픈·공백·zero-width) → 안전한 문자로 정규화
def _clean(s: str) -> str:
    if not s:
        return s
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat == "Pd":            # 각종 대시/하이픈 → '-'
            out.append("-")
        elif cat == "Zs":          # 각종 공백 → 일반 공백
            out.append(" ")
        elif cat == "Cf" or ch == "\uFE0F":  # format/zero-width·variation selector 제거
            continue
        else:
            out.append(ch)
    return "".join(out)


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
    text = _clean(text)
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

def render_hero(theme: Theme, image, headline: str = "", sub: str = "",
                copy_anchor: str | None = None) -> Image.Image:
    """풀블리드 제품 이미지 + 헤드라인.

    copy_anchor=None → **기존 하단 중앙 렌더링(호환 폴백)**. 폐쇄형 copy_anchor가 주어지면
    제품 반대편 상단 안전영역에만 카피를 배치하고, 오버레이도 그 주변에만 둔다(하단 55%
    전체를 덮지 않는다). 렌더러는 role·픽셀을 보지 않고 전달받은 copy_anchor만 쓴다.
    """
    img = fit_width(_load(image), theme.page_width).convert("RGBA")
    w, h = img.size
    if copy_anchor is None:
        return _hero_bottom(theme, img, w, h, headline, sub)
    return _hero_placed(theme, img, w, h, headline, sub, copy_anchor)


def _hero_bottom(theme: Theme, img: Image.Image, w: int, h: int,
                 headline: str, sub: str) -> Image.Image:
    """기존 동작 — 하단 55% 그라디언트 + 하단 중앙 카피 (copy_anchor 없을 때의 폴백)."""
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


def _ellipsize(draw, line: str, font, max_w: int) -> str:
    """줄 끝에 …를 붙여 max_w 안에 들어오게 글자를 깎는다."""
    ell = "…"
    if draw.textlength(line + ell, font=font) <= max_w:
        return line + ell
    s = line
    while s and draw.textlength(s + ell, font=font) > max_w:
        s = s[:-1]
    return (s + ell) if s else ell


def _truncate_to_box(draw, hlines, slines, hf, sf, gap, box_w, box_h):
    """box_h를 넘지 않도록 라인 수를 자른다. 헤드라인 우선, 잘린 마지막 줄에 …를 붙인다.

    **완료 조건을 실제로 닫는다** — 반환 라인들의 총 높이는 box_h를 넘지 않는다.
    """
    hlh, slh = _line_h(hf, hf.size), _line_h(sf, sf.size)
    kept_h, used = [], 0
    for ln in hlines:
        if used + hlh <= box_h:
            kept_h.append(ln)
            used += hlh
        else:
            break
    # 서브카피는 남은 공간에만 (헤드라인이 있으면 gap 포함)
    kept_s = []
    used_s = used + (gap if (kept_h and slines) else 0)
    for ln in slines:
        if used_s + slh <= box_h:
            kept_s.append(ln)
            used_s += slh
        else:
            break
    # 잘림 표시: 서브가 잘렸으면 서브 마지막 줄에, 아니면 헤드라인이 잘렸을 때 그 마지막 줄에
    if kept_s and len(kept_s) < len(slines):
        kept_s[-1] = _ellipsize(draw, kept_s[-1], sf, box_w)
    elif kept_h and (len(kept_h) < len(hlines) or (slines and not kept_s)):
        kept_h[-1] = _ellipsize(draw, kept_h[-1], hf, box_w)
    return kept_h, kept_s


def _fit_hero_text(draw, theme: Theme, headline: str, sub: str,
                   box_w: int, box_h: int):
    """headline+subcopy를 안전영역(box_w×box_h)에 맞게 줄바꿈+폰트 축소.

    반환: (hlines, slines, hf, sf, gap). **반환 라인의 총 높이는 항상 box_h 이하다** —
    최소 폰트로도 안 맞으면 라인 수를 잘라(…) 세로 오버플로우를 막는다.
    """
    hlines, slines, hf, sf, gap = [], [], _font(theme, theme.h1), _font(theme, theme.body), 0
    for scale in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        hsize = max(20, int(theme.h1 * scale))
        ssize = max(15, int(theme.body * scale))
        hf, sf = _font(theme, hsize), _font(theme, ssize)
        hlines = _wrap(draw, headline, hf, box_w) if headline else []
        slines = _wrap(draw, sub, sf, box_w) if sub else []
        gap = 16 if (hlines and slines) else 0
        total = (_line_h(hf, hsize) * len(hlines) + gap
                 + _line_h(sf, ssize) * len(slines))
        if total <= box_h:
            return hlines, slines, hf, sf, gap
    # 최소 폰트로도 안 맞음 → 라인 수를 box_h 안으로 잘라 오버플로우를 닫는다.
    hlines, slines = _truncate_to_box(draw, hlines, slines, hf, sf, gap, box_w, box_h)
    gap = 16 if (hlines and slines) else 0
    return hlines, slines, hf, sf, gap


def _hero_placed(theme: Theme, img: Image.Image, w: int, h: int,
                 headline: str, sub: str, copy_anchor: str) -> Image.Image:
    """제품 반대편 상단 안전영역에 카피 배치 + 국소 스크림. 텍스트 없으면 오버레이 없음."""
    if not (headline or sub):
        return img.convert("RGB")            # 텍스트 없으면 오버레이 만들지 않음

    place = copy_placement_of(copy_anchor)   # 잘못된 anchor면 ValueError
    bx0, bx1 = int(w * place.x0), int(w * place.x1)
    by0, by1 = int(h * place.y0), int(h * place.y1)
    box_w, box_h = bx1 - bx0, by1 - by0

    measure = ImageDraw.Draw(img)
    hlines, slines, hf, sf, gap = _fit_hero_text(measure, theme, headline, sub, box_w, box_h)
    hlh, slh = _line_h(hf, hf.size), _line_h(sf, sf.size)
    def _x(line_w: float) -> float:
        if copy_anchor == "top_left":
            return bx0
        if copy_anchor == "top_right":
            return bx1 - line_w
        return bx0 + (box_w - line_w) / 2    # top_center

    # 국소 스크림 — **텍스트 '모양'을 블러한 소프트 헤일로.** 채워진 사각 카드가 아니라
    # 글자 주변에만 은은히 얹혀, 텍스트에서 멀어지면 알파가 자연히 0으로 감쇠한다
    # (밝은 배경에서 흰 카드처럼 보이지 않고 사각 경계가 드러나지 않음). 은은한 상한으로
    # 밝은·어두운 배경 모두 가독성을 확보하고, 안전영역 밖은 하드 클립으로 0 보장한다
    # (제품·소품 영역은 불변, copy anchor·텍스트 좌표·줄바꿈은 그대로).
    pad = max(10, int(theme.margin * 0.5))
    halo = Image.new("L", (w, h), 0)
    hd = ImageDraw.Draw(halo)
    ty = by0
    for ln in hlines:
        hd.text((_x(measure.textlength(ln, font=hf)), ty), ln, font=hf, fill=255)
        ty += hlh
    ty += gap
    for ln in slines:
        hd.text((_x(measure.textlength(ln, font=sf)), ty), ln, font=sf, fill=255)
        ty += slh
    halo = halo.filter(ImageFilter.GaussianBlur(pad * 1.4))   # 넓게 퍼져 카드 경계 제거
    halo = halo.point(lambda v: min(140, v * 3))              # 은은한 상한(진한 카드 방지)
    clip = Image.new("L", (w, h), 0)
    ImageDraw.Draw(clip).rectangle([bx0, by0, bx1, by1], fill=255)
    scrim = Image.new("RGBA", (w, h), theme.bg + (0,))
    scrim.putalpha(ImageChops.multiply(halo, clip))
    img = Image.alpha_composite(img, scrim)

    draw = ImageDraw.Draw(img)
    y = by0
    for ln in hlines:
        draw.text((_x(draw.textlength(ln, font=hf)), y), ln, font=hf, fill=theme.text)
        y += hlh
    y += gap
    for ln in slines:
        draw.text((_x(draw.textlength(ln, font=sf)), y), ln, font=sf, fill=theme.sub)
        y += slh
    return img.convert("RGB")


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
    """스펙/비교 표. rows = [(label, value), ...]. 긴 값은 줄바꿈(오버플로우 방지)."""
    width = theme.page_width
    title_f, cell_f = _font(theme, theme.h2), _font(theme, theme.body)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    x_label, x_val = theme.margin, width // 2
    max_w_val = width - theme.margin - x_val      # 값 컬럼 가용 폭
    lh = _line_h(cell_f, theme.body)
    v_pad = int(theme.body * 0.6)                 # 셀 상하 여백

    # 행별로 값을 줄바꿈하고 행 높이를 계산
    prepared = []   # (label, value_lines, row_h)
    for label, value in rows:
        vlines = _wrap(measure, str(value), cell_f, max_w_val) or [""]
        rh = max(int(theme.body * 2.1), lh * len(vlines) + v_pad * 2)
        prepared.append((_clean(str(label)), vlines, rh))

    pad = 60
    th = _line_h(title_f, theme.h2)
    height = pad + th + 24 + sum(rh for _, _, rh in prepared) + pad

    img = Image.new("RGB", (width, height), theme.bg)
    draw = ImageDraw.Draw(img)
    title = _clean(title)
    draw.text(((width - draw.textlength(title, font=title_f)) / 2, pad),
              title, font=title_f, fill=theme.text)

    y = pad + th + 24
    for label, vlines, rh in prepared:
        draw.line([(theme.margin, y), (width - theme.margin, y)], fill=theme.muted, width=1)
        draw.text((x_label, y + v_pad), label, font=cell_f, fill=theme.sub)
        vy = y + v_pad
        for vl in vlines:
            draw.text((x_val, vy), vl, font=cell_f, fill=theme.text)
            vy += lh
        y += rh
    draw.line([(theme.margin, y), (width - theme.margin, y)], fill=theme.muted, width=1)
    return img


def render_cta(theme: Theme, text: str) -> Image.Image:
    """구매 유도 — 가운데 버튼형."""
    width = theme.page_width
    f = _font(theme, theme.h2)
    text = _clean(text)
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
