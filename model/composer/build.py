"""아키타입 page_blocks + 생성물(이미지·카피·스펙) → 긴 상세페이지 조립.

아키타입이 정한 블록 순서대로:
  - hero/feature 블록 : 해당 role의 생성 이미지 + 카피
  - spec_table 블록   : 구조화된 스펙 dict
  - cta 블록          : CTA 문구
  - divider           : 구분선
  - text 블록         : (현재는 생략 — 추후 섹션 카피 연결)
"""
from composer.layout import compose
from composer.theme import get_theme


def build_page(profile: dict, images_by_role: dict, copies_by_role: dict,
               specs: dict, cta: str = "", theme_name: str = "dark",
               page_width: int | None = None):
    """아키타입 블록 구성대로 composer 블록 목록을 만들어 합성한다.

    page_width: 사이트별 상세폭(px). 미지정 시 테마 기본(1080).
    """
    blocks = []
    for b in profile["page_blocks"]:
        t = b["type"]

        if t in ("hero", "feature"):
            role = b.get("role")
            img = images_by_role.get(role)
            if img is None:
                continue   # 이미지가 없는 슬롯은 건너뜀
            copy = copies_by_role.get(role, {})
            block = {"type": t, "image": img,
                     "headline": copy.get("headline", ""),
                     "sub": copy.get("sub", "")}
            if t == "feature":
                block["points"] = copy.get("points", [])
            blocks.append(block)

        elif t == "spec_table":
            if specs:
                blocks.append({"type": "spec_table", "title": "제품 사양",
                               "rows": list(specs.items())})

        elif t == "cta":
            blocks.append({"type": "cta", "text": cta or "자세히 보기"})

        elif t == "divider":
            blocks.append({"type": "divider"})

        # t == "text" 는 현재 생략 (섹션 카피 연결은 다음 단계)

    return compose(blocks, get_theme(theme_name, page_width))


def build_rich_page(profile: dict, images_by_role: dict, page_copy: dict,
                    specs: dict, theme_name: str = "dark",
                    page_width: int | None = None):
    """리치 콘텐츠 조립 — 섹션별 본문 카피(intro/body/points)까지 렌더.

    page_copy = {"intro": {headline, body}, "sections": {role: {...}}, "cta": str}
    """
    intro = page_copy.get("intro", {})
    sections = page_copy.get("sections", {})
    cta = page_copy.get("cta", "")
    blocks = []

    for b in profile["page_blocks"]:
        t = b["type"]

        if t in ("hero", "feature"):
            role = b.get("role")
            img = images_by_role.get(role)
            if img is None:
                continue
            sec = sections.get(role, {})
            if t == "hero":
                blocks.append({"type": "hero", "image": img,
                               "headline": sec.get("headline", ""),
                               "sub": sec.get("sub", "")})
            else:
                blocks.append({"type": "feature", "image": img,
                               "headline": sec.get("headline", ""),
                               "sub": sec.get("sub", ""),
                               "body": sec.get("body", ""),
                               "points": sec.get("points", [])})

        elif t == "text":
            if intro:
                blocks.append({"type": "text",
                               "headline": intro.get("headline", ""),
                               "body": intro.get("body", "")})

        elif t == "spec_table":
            if specs:
                blocks.append({"type": "spec_table", "title": "제품 사양",
                               "rows": list(specs.items())})

        elif t == "cta":
            blocks.append({"type": "cta", "text": cta or "자세히 보기"})

        elif t == "divider":
            blocks.append({"type": "divider"})

    return compose(blocks, get_theme(theme_name, page_width))
