"""GEO 텍스트 레이어 — 이미지와 별개로 'AI가 읽는' 구조화 산출물 생성.

입력(req)·확정 스펙(specs)에 근거해서만 생성한다(사실 가드레일).
경쟁팀과 달리 허위 평점·가짜 인용·근거 없는 수치를 만들지 않는다.

산출물:
    {
      "geo_html": str,               # 시맨틱 HTML(JSON-LD 임베드) — AI 검색용 부가 산출물
      "structured_data": list[dict], # Product / FAQPage JSON-LD
      "faq": list[{"q","a"}],
      "warnings": list[str],         # 사실 가드레일 경고
    }
"""
import html
import json
import re
from datetime import datetime, timezone

from baseline.llm import chat_json  # noqa: E402


# ----------------------------- (A) FAQ (LLM, 근거 기반) -----------------------------
_FAQ_SYSTEM = (
    "너는 이커머스 상세페이지 FAQ 작성자다. 주어진 제품 정보에 실제로 있는 사실로만 답한다. "
    "없는 수치·수상·후기·전문가 인용을 지어내지 마라. 모르면 '판매자에게 문의'로 답한다. JSON만 출력."
)


def generate_faq(req: dict, n: int = 5) -> list[dict]:
    """구매자가 궁금해할 Q&A n개 — product_details 범위 내에서만."""
    user = (
        f"제품명: {req.get('product_name', '')}\n"
        f"카테고리: {req.get('category', '')}\n"
        f"특징/스펙: {req.get('product_details', '')}\n"
        f"강조: {req.get('emphasis', '')}\n\n"
        f"구매자가 궁금해할 질문 {n}개와 답을 만들어라. 답은 반드시 위 정보 범위 안에서만.\n"
        '{"faq":[{"q":"...","a":"..."}]}'
    )
    try:
        faq = chat_json(_FAQ_SYSTEM, user).get("faq", [])
        return [f for f in faq if isinstance(f, dict) and f.get("q") and f.get("a")][:n]
    except Exception:
        return []


# ----------------------- (B) Product JSON-LD (결정론적, 있는 필드만) -----------------------
def build_product_jsonld(req: dict, specs: dict) -> dict:
    d = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": req.get("product_name", ""),
        "category": req.get("category", ""),
        "dateModified": datetime.now(timezone.utc).date().isoformat(),  # 신선도(recency)
    }
    if req.get("color"):
        d["color"] = req["color"]
    if req.get("product_details"):
        d["description"] = req["product_details"]
    if req.get("brand"):
        d["brand"] = {"@type": "Brand", "name": req["brand"]}
    if specs:
        d["additionalProperty"] = [
            {"@type": "PropertyValue", "name": str(k), "value": str(v)} for k, v in specs.items()
        ]
    for key in ("gtin", "mpn", "sku"):  # 식별자 = GEO 최강, 있을 때만
        if req.get(key):
            d[key] = req[key]
    if req.get("price"):
        d["offers"] = {
            "@type": "Offer", "price": str(req["price"]),
            "priceCurrency": "KRW", "availability": "https://schema.org/InStock",
        }
    # ⚠️ aggregateRating/review 는 '실제 리뷰' 있을 때만 → 지금은 생성 안 함(정직)
    return d


def build_faq_jsonld(faq: list[dict]) -> dict | None:
    if not faq:
        return None
    return {
        "@context": "https://schema.org/", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq
        ],
    }


# --------------------------- (C) 사실 가드레일 ---------------------------
def guardrail_warnings(req: dict, texts: list[str]) -> list[str]:
    """생성 텍스트의 수치가 입력 근거에 없으면 경고(허위 수치 방지)."""
    src = " ".join(str(req.get(k, "")) for k in ("product_details", "emphasis", "price"))
    src_nums = set(re.findall(r"\d[\d,.]*", src))
    warns = {
        f"근거 없는 수치 의심: '{m}'"
        for t in texts for m in re.findall(r"\d[\d,.]*", t or "")
        if m not in src_nums and len(m) >= 2
    }
    return sorted(warns)


# --------------------- (D) 시맨틱 HTML + JSON-LD 임베드 ---------------------
def _intro_text(page_copy: dict) -> str:
    intro = page_copy.get("intro", {})
    if isinstance(intro, dict):
        return intro.get("body") or intro.get("headline") or ""
    return str(intro or "")


def build_geo_html(req: dict, page_copy: dict, specs: dict, faq: list[dict],
                   jsonlds: list[dict]) -> str:
    esc = html.escape
    name = esc(req.get("product_name", ""))
    rows = "".join(
        f"<tr><th scope=\"row\">{esc(str(k))}</th><td>{esc(str(v))}</td></tr>"
        for k, v in (specs or {}).items()
    )
    faqs = "".join(f"<dt>{esc(f['q'])}</dt><dd>{esc(f['a'])}</dd>" for f in (faq or []))
    ld = "\n".join(
        f'<script type="application/ld+json">{json.dumps(j, ensure_ascii=False)}</script>'
        for j in jsonlds
    )
    spec_block = f"<h2>제품 사양</h2><table>{rows}</table>" if rows else ""
    faq_block = f"<h2>자주 묻는 질문</h2><dl>{faqs}</dl>" if faqs else ""
    return (
        f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f"<title>{name}</title>{ld}</head><body>"
        f"<h1>{name}</h1>"
        f"<p>{esc(_intro_text(page_copy))}</p>"
        f"{spec_block}{faq_block}"
        f"</body></html>"
    )


# --------------------------- (E) 오케스트레이션 ---------------------------
def geo_main(req: dict, profile: dict, page_copy: dict, specs: dict) -> dict:
    faq = generate_faq(req)
    jsonlds = [j for j in (build_product_jsonld(req, specs), build_faq_jsonld(faq)) if j]
    texts = (
        [_intro_text(page_copy)]
        + [s.get("body", "") for s in page_copy.get("sections", {}).values() if isinstance(s, dict)]
        + [f.get("a", "") for f in faq]
    )
    return {
        "geo_html": build_geo_html(req, page_copy, specs, faq, jsonlds),
        "structured_data": jsonlds,
        "faq": faq,
        "warnings": guardrail_warnings(req, texts),
    }
