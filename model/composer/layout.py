"""세로 롱폼 합성기 — 블록 목록을 받아 하나의 긴 상세페이지 PNG로 조립.

block = {"type": ..., 필요 데이터}
    hero       : {image, headline, sub}
    feature    : {image, headline, sub, points}
    text       : {headline, sub}
    spec_table : {title, rows: [(label, value), ...]}
    cta        : {text}
    divider    : {}
"""
from PIL import Image

from composer import blocks
from composer.theme import Theme, get_theme


def render_block(block: dict, theme: Theme) -> Image.Image:
    t = block.get("type")
    if t == "hero":
        return blocks.render_hero(theme, block["image"],
                                  block.get("headline", ""), block.get("sub", ""))
    if t == "feature":
        return blocks.render_feature(theme, block["image"], block.get("headline", ""),
                                     block.get("sub", ""), block.get("body", ""),
                                     block.get("points"))
    if t == "text":
        return blocks.render_text(theme, block.get("headline", ""), block.get("sub", ""),
                                  block.get("body", ""))
    if t == "spec_table":
        return blocks.render_spec_table(theme, block.get("title", ""), block.get("rows", []))
    if t == "cta":
        return blocks.render_cta(theme, block.get("text", ""))
    if t == "divider":
        return blocks.render_divider(theme)
    raise ValueError(f"알 수 없는 블록 타입: {t}")


def compose(block_list: list[dict], theme: Theme | None = None) -> Image.Image:
    """블록들을 세로로 쌓아 긴 상세페이지 이미지를 만든다."""
    theme = theme or get_theme("dark")
    rendered = []
    for b in block_list:
        img = render_block(b, theme)
        if img.width != theme.page_width:
            img = blocks.fit_width(img, theme.page_width)
        rendered.append(img)

    total_h = sum(im.height for im in rendered)
    page = Image.new("RGB", (theme.page_width, total_h), theme.bg)
    y = 0
    for im in rendered:
        page.paste(im, (0, y))
        y += im.height
    return page
