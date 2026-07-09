"""요청 + 이미지 스펙 -> 컷별 한글 카피 문구. GPT 텍스트 모델 1회 호출.

카피 톤/타깃/포지셔닝 지시문은 style_presets 레지스트리에서 가져온다.

출력: specs와 같은 순서/길이의 리스트
    [{"headline": str, "sub": str}, ...]
"""
import baseline.config as config
from baseline.llm import chat_json
from baseline.style_presets import build_style_context

SYSTEM_PROMPT = (
    "당신은 한국 이커머스 상세페이지 전문 카피라이터입니다. "
    "제품 정보를 바탕으로 구매 전환율이 높은 짧은 카피를 씁니다. "
    "출력은 반드시 JSON만 사용하세요."
)

USER_TEMPLATE = """[제품 정보]
product_name: {product_name}
color: {color}
emphasis(강조 요청): {emphasis}
product_details(스펙/특징): {product_details}

[카피 지시 — 사용자 선택]
톤: {tone}
타깃: {target}
포지셔닝: {positioning}
아키타입 포커스: {copy_focus}

아래 이미지 컷 목록에 각각 올릴 한글 카피를 작성하세요.
images(roles): {roles}

규칙:
- 위 톤/타깃/포지셔닝 지시를 반영
- product_details의 실제 스펙/수치를 적극 활용해 구체적으로 작성
- headline: 12자 내외, 임팩트 있게
- sub: 20자 내외, 핵심 가치 전달
- points: 그 컷에서 강조할 소구 포인트 2~3개 (각 12자 내외, 스펙/수치 기반)
- images와 같은 순서, 같은 개수로 작성
- JSON만 출력:

{{
  "copies": [
    {{"headline": "...", "sub": "...", "points": ["...", "...", "..."]}}
  ]
}}
"""


def generate(req: dict, specs: list[dict],
             copy_directives: dict | None = None,
             copy_focus: str = "") -> list[dict]:
    if copy_directives is None:
        copy_directives = build_style_context(req)["copy_directives"]

    roles = [s.get("role", f"cut{i}") for i, s in enumerate(specs)]
    user = USER_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        color=req.get("color", ""),
        emphasis=req.get("emphasis", ""),
        product_details=req.get("product_details", ""),
        tone=copy_directives.get("copy_tone", ""),
        target=copy_directives.get("target_audience", ""),
        positioning=copy_directives.get("positioning", ""),
        copy_focus=copy_focus,
        roles=roles,
    )
    copies = chat_json(SYSTEM_PROMPT, user).get("copies", [])

    # 길이 안전장치: 개수가 안 맞아도 파이프라인이 멈추지 않게 보정
    while len(copies) < len(specs):
        copies.append({"headline": req.get("product_name", ""), "sub": "", "points": []})
    for c in copies:
        c.setdefault("points", [])
    return copies[:len(specs)]


_EXTRAS_TEMPLATE = """[제품 정보]
product_name: {product_name}
product_details: {product_details}

[스펙 가이드]
{spec_hint}
권장 예시 항목: {spec_fields}

product_details를 바탕으로 상세페이지 스펙표와 구매 유도 문구를 작성하세요.
규칙:
- specs: 제품에 실제로 해당하는 항목만 (항목:값) 최대 6개. product_details에 근거 없으면 생략(추측 금지).
- cta: 구매 유도 문구 12자 내외.
- JSON만 출력:

{{"specs": {{"항목1": "값1", "항목2": "값2"}}, "cta": "..."}}
"""


def generate_page_extras(req: dict, profile: dict) -> tuple[dict, str]:
    """아키타입 스펙 가이드 + 제품정보 → (스펙표 dict, CTA 문구).

    스펙 항목은 spec_hint 방향에 맞춰 LLM이 제품별로 확정한다.
    """
    fields = profile.get("spec_fields") or "(제품에 맞게 자유 선택)"
    user = _EXTRAS_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        product_details=req.get("product_details", ""),
        spec_hint=profile.get("spec_hint", ""),
        spec_fields=fields,
    )
    data = chat_json(SYSTEM_PROMPT, user)
    return data.get("specs", {}), data.get("cta", "자세히 보기")


_PAGE_COPY_TEMPLATE = """[제품 정보]
product_name: {product_name}
color: {color}
emphasis(강조): {emphasis}
product_details(스펙/특징): {product_details}

[카피 지시]
톤: {tone} / 타깃: {target} / 포지셔닝: {positioning}
아키타입 포커스: {copy_focus}

[섹션 목록(role)]: {roles}

상세페이지용 한국어 카피를 구매 전환이 높게, 구체적이고 매력적으로 작성하세요.
- intro: headline(제품 한줄 소개, 15자 내외) + body(제품 전체 소개, 2~3문장)
- 각 role 섹션:
  - headline: 12자 내외, 임팩트
  - sub: 20자 내외
  - body: 그 특징/기능을 구매자 관점에서 설명하는 2~3문장 (product_details의 수치·이점 활용)
  - points: 소구 포인트 2~3개 (각 12자 내외)
- cta: 구매 유도 문구 (12자 내외)

JSON만 출력:
{{
  "intro": {{"headline": "...", "body": "..."}},
  "sections": {{
    "<role>": {{"headline": "...", "sub": "...", "body": "...", "points": ["...", "..."]}}
  }},
  "cta": "..."
}}
"""


def generate_page_copy(req: dict, profile: dict, roles: list[str],
                       copy_directives: dict | None = None) -> dict:
    """상세페이지 전체 카피 — intro(소개 문단) + 섹션별(headline/sub/body/points) + cta.

    반환: {"intro": {...}, "sections": {role: {...}}, "cta": str}
    """
    if copy_directives is None:
        copy_directives = build_style_context(req)["copy_directives"]
    user = _PAGE_COPY_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        color=req.get("color", ""),
        emphasis=req.get("emphasis", ""),
        product_details=req.get("product_details", ""),
        tone=copy_directives.get("copy_tone", ""),
        target=copy_directives.get("target_audience", ""),
        positioning=copy_directives.get("positioning", ""),
        copy_focus=profile.get("copy_focus", ""),
        roles=list(roles),
    )
    # 모든 role 섹션에 본문이 채워질 때까지 최대 2회 시도 (일부 누락 방어)
    best = None
    for _ in range(2):
        best = _normalize_page_copy(chat_json(SYSTEM_PROMPT, user))
        if all(best["sections"].get(r, {}).get("body") for r in roles):
            break
    return best


def _norm_section(v) -> dict:
    """섹션 값을 항상 {headline, sub, body, points} dict로 정규화 (문자열 등 방어)."""
    if isinstance(v, dict):
        pts = v.get("points", [])
        return {
            "headline": str(v.get("headline", "")),
            "sub": str(v.get("sub", "")),
            "body": str(v.get("body", "")),
            "points": pts if isinstance(pts, list) else [str(pts)],
        }
    if isinstance(v, str):   # 문자열만 준 경우 → 본문으로
        return {"headline": "", "sub": "", "body": v, "points": []}
    return {"headline": "", "sub": "", "body": "", "points": []}


def _normalize_page_copy(data: dict) -> dict:
    """LLM 출력 구조가 어긋나도(문자열/누락/타입오류) 안전한 형태로 맞춘다."""
    intro = data.get("intro", {})
    if isinstance(intro, str):
        intro = {"headline": "", "body": intro}
    elif not isinstance(intro, dict):
        intro = {}

    sections = data.get("sections", {})
    if not isinstance(sections, dict):
        sections = {}
    sections = {k: _norm_section(v) for k, v in sections.items()}

    cta = data.get("cta", "자세히 보기")
    return {"intro": intro, "sections": sections, "cta": str(cta) if cta else "자세히 보기"}


if __name__ == "__main__":
    import json

    sample = {"product_name": "무선 기계식 키보드", "color": "화이트",
              "emphasis": "타건감", "copy_tone": "신뢰·전문",
              "target_audience": "직장인", "positioning": 4}
    specs = [{"role": "hero"}, {"role": "lifestyle"}]
    print(json.dumps(generate(sample, specs), ensure_ascii=False, indent=2))
