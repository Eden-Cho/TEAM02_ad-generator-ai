"""아키타입 = 상세페이지 "프롬프트 가이드" 레지스트리.

카테고리(다나와 등)를 6개 아키타입으로 매핑하고, 각 아키타입은
프론트 입력과 합쳐져 프롬프트/카피/페이지가 되는 '가이드'를 담는다.

각 아키타입 4축:
  - page_blocks : 페이지 블록 구성 (composer용). 이미지 블록은 role/mode/text_zone/brief 포함.
  - spec_hint   : 어떤 종류의 스펙이 중요한지 LLM 가이드 (한국어). 실제 항목은 LLM이 제품별로 결정.
  - spec_fields : 권장 예시 항목 (LLM이 제품에 맞게 가감). [] 이면 완전 자동(예: tech·general).
  - copy_focus  : 카피 강조점 (copy_generator용, 한국어 지시)
  - (연출 가이드는 각 이미지 블록의 brief에 영어로)

주의: 스펙 항목은 '고정'이 아니라 'adaptive' — spec_hint로 방향만 주고 LLM이 제품에 맞춰 확정.
특히 tech는 제품 유형(모바일/가전/TV 등)이 크게 달라 spec_fields를 비우고 hint로만 분기.

블록 타입: hero / feature (이미지) · text / spec_table / cta / divider (비이미지)
mode: edit=실제 제품 보존 / t2i=연출 생성
"""

_IMAGE_TYPES = ("hero", "feature")

# 사용/장면 컷 역할 (여기 속하면 kind="usage", 그 외 "product")
# → 손·모델·사용장면 사진을 이 슬롯에만 배정해 hero 등 제품컷 오염을 막는다.
_USAGE_ROLES = {"lifestyle", "styling", "space", "serving"}


def _kind(role: str) -> str:
    return "usage" if role in _USAGE_ROLES else "product"

ARCHETYPES: dict[str, dict] = {
    # 1) 테크·전자 — 스펙/성능 중심
    "tech": {
        "label": "테크·전자",
        "categories": ["가전·TV", "컴퓨터·노트북·조립PC", "태블릿·모바일·디카",
                       "자동차·용품·공구", "반려동물·취미·사무", "전자제품"],
        "copy_focus": "성능·사양을 구체적 수치로 강조. 효율·호환성·전문성. 신뢰감 있는 담백한 톤.",
        # 제품 유형이 크게 다르므로 스펙 항목은 LLM이 제품 보고 선택 (adaptive)
        "spec_hint": ("제품 유형에 맞는 핵심 사양만 선택. "
                      "모바일/PC=칩·RAM·저장·배터리·디스플레이 / "
                      "가전=용량·에너지효율등급·소비전력·소음·설치형태 / "
                      "TV=화면크기·해상도·패널·주사율 / "
                      "자동차용품·공구=규격·호환·출력. 제품에 없는 항목은 생략."),
        "spec_fields": [],
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "main hero shot on a clean minimal studio desk, soft lighting, tech workspace"},
            {"type": "feature", "role": "build", "mode": "edit", "text_zone": "top",
             "brief": "close-up emphasizing premium build quality and material finish"},
            {"type": "feature", "role": "connectivity", "mode": "edit", "text_zone": "top",
             "brief": "detailed close-up of the ports and connections"},
            {"type": "text"},
            {"type": "spec_table"},
            {"type": "feature", "role": "lifestyle", "mode": "t2i", "text_zone": "bottom",
             "brief": "the product in use in a modern productive workspace, natural light"},
            {"type": "cta"},
        ],
    },

    # 2) 패션·잡화 — 핏/소재/코디
    "fashion": {
        "label": "패션·잡화",
        "categories": ["패션·잡화·뷰티", "패션·의류", "패션"],
        "copy_focus": "핏·실루엣·소재감·코디 활용을 강조. 감각적이고 트렌디한 톤.",
        "spec_hint": "소재·사이즈·색상·핏·세탁방법·원산지 중심. 제품에 맞게 가감.",
        "spec_fields": ["소재", "사이즈", "색상", "핏", "세탁방법", "원산지"],
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "clean fashion backdrop, soft studio light, editorial mood"},
            {"type": "feature", "role": "fabric", "mode": "edit", "text_zone": "top",
             "brief": "extreme close-up of fabric texture and stitching detail"},
            {"type": "feature", "role": "styling", "mode": "t2i", "text_zone": "bottom",
             "brief": "model wearing the item in a stylish lifestyle coordination, natural pose"},
            {"type": "text"},
            {"type": "spec_table"},
            {"type": "cta"},
        ],
    },

    # 3) 뷰티 — 성분/텍스처/효능
    "beauty": {
        "label": "뷰티",
        "categories": ["뷰티", "화장품"],
        "copy_focus": "성분·효능·사용감을 강조. 감성적이면서 신뢰감 있는 톤.",
        "spec_hint": "용량·주요성분·피부타입·사용법·사용시기·유통기한 중심. 제품에 맞게 가감.",
        "spec_fields": ["용량", "주요 성분", "피부 타입", "사용법", "사용 시기", "유통기한"],
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "clean beauty aesthetic, marble surface, soft diffused light, water droplets"},
            {"type": "feature", "role": "ingredient", "mode": "edit", "text_zone": "top",
             "brief": "product with botanical ingredients, glass bottles and greenery, clean beauty"},
            {"type": "feature", "role": "texture", "mode": "t2i", "text_zone": "bottom",
             "brief": "macro close-up of the creamy product texture and swatch"},
            {"type": "text"},
            {"type": "spec_table"},
            {"type": "cta"},
        ],
    },

    # 4) 식품 — 원산지/영양/신선함
    "food": {
        "label": "식품",
        "categories": ["식품·유아·완구", "식품"],
        "categories_note": "생활·주방·건강은 living으로 매핑 (중복 방지)",
        "copy_focus": "맛·신선함·원산지·건강을 강조. 먹음직스럽고 신뢰감 있는 톤.",
        "spec_hint": "중량·원재료·원산지·영양성분·보관방법·유통기한·알레르기 중심. 제품에 맞게 가감.",
        "spec_fields": ["중량", "원재료", "원산지", "영양성분", "보관방법", "유통기한", "알레르기 정보"],
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "fresh product on a rustic wooden board, natural window light, appetizing"},
            {"type": "feature", "role": "ingredient", "mode": "edit", "text_zone": "top",
             "brief": "fresh natural ingredients arranged around the product, organic feel"},
            {"type": "feature", "role": "serving", "mode": "t2i", "text_zone": "bottom",
             "brief": "the food beautifully plated and served, appetizing close-up"},
            {"type": "spec_table"},
            {"type": "text"},
            {"type": "cta"},
        ],
    },

    # 5) 리빙·홈 — 소재/공간/치수
    "living": {
        "label": "리빙·홈",
        "categories": ["가구·조명", "생활·주방·건강", "가구"],
        "copy_focus": "소재·마감·공간 활용·실용성·분위기를 강조. 따뜻하고 감각적인 톤.",
        "spec_hint": "소재·사이즈(가로x세로x높이)·색상·하중·조립여부·관리방법 중심. 제품에 맞게 가감.",
        "spec_fields": ["소재", "사이즈(가로x세로x높이)", "색상", "하중/내구성", "조립 여부", "관리방법"],
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "styled interior lifestyle scene, warm home environment, soft daylight"},
            {"type": "feature", "role": "material", "mode": "edit", "text_zone": "top",
             "brief": "close-up of the material and finish texture, tactile detail"},
            {"type": "feature", "role": "space", "mode": "t2i", "text_zone": "bottom",
             "brief": "the product placed in a beautifully styled living space"},
            {"type": "text"},
            {"type": "spec_table"},
            {"type": "cta"},
        ],
    },

    # 6) 범용 (default) — 그 외 전부. 스펙 항목은 LLM이 제품 보고 판단.
    "general": {
        "label": "범용",
        "categories": ["스포츠·골프", "반려동물", "취미"],
        "copy_focus": "제품의 핵심 강점을 균형 있게 강조. 신뢰감 있는 톤. 제품에 맞는 소구점 자동 판단.",
        "spec_hint": "제품 특성에 맞는 핵심 사양을 LLM이 자유롭게 선택.",
        "spec_fields": [],   # 비어 있으면 copy_generator가 제품 보고 항목까지 생성
        "page_blocks": [
            {"type": "hero", "role": "hero", "mode": "edit", "text_zone": "bottom",
             "brief": "clean product shot with a simple complementary background"},
            {"type": "feature", "role": "detail", "mode": "edit", "text_zone": "top",
             "brief": "close-up highlighting the product's key detail or material"},
            {"type": "feature", "role": "lifestyle", "mode": "t2i", "text_zone": "bottom",
             "brief": "the product used in a realistic everyday context"},
            {"type": "spec_table"},
            {"type": "cta"},
        ],
    },
}

DEFAULT = "general"


def resolve_archetype(category: str | None) -> str:
    """카테고리 문자열 → 아키타입 키. 못 찾으면 general."""
    if not category:
        return DEFAULT
    cat = category.strip()
    for key, prof in ARCHETYPES.items():
        if cat == key or cat == prof["label"] or cat in prof["categories"]:
            return key
    # 부분 일치 (예: "노트북" 이 "컴퓨터·노트북·조립PC" 에 포함)
    for key, prof in ARCHETYPES.items():
        if any(cat in c or c in cat for c in prof["categories"]):
            return key
    return DEFAULT


def get_profile(category_or_key: str | None) -> dict:
    key = category_or_key if category_or_key in ARCHETYPES else resolve_archetype(category_or_key)
    return ARCHETYPES[key]


def image_slots(profile: dict) -> list[dict]:
    """페이지 블록에서 이미지 블록만 뽑아 프롬프트 생성용 슬롯으로 (kind 포함)."""
    return [
        {"role": b["role"], "mode": b["mode"], "text_zone": b["text_zone"],
         "brief": b["brief"], "kind": _kind(b["role"])}
        for b in profile["page_blocks"]
        if b["type"] in _IMAGE_TYPES and "brief" in b
    ]


def page_blocks(profile: dict) -> list[dict]:
    return [dict(b) for b in profile["page_blocks"]]


def resolve_image_slots(profile: dict, product_images=None,
                        app_images=None) -> list[dict]:
    """제품/응용 두 리스트를 슬롯 kind에 맞춰 라우팅.

    - kind="product" 슬롯 ← 제품 이미지(단독컷)를 순서대로
    - kind="usage"   슬롯 ← 응용 이미지(손·사용장면)를 순서대로
    → 손 든 사진은 lifestyle 같은 usage 슬롯에만 가고, hero 등 제품컷엔 안 들어감.

    각 리스트가 부족하면 다른 리스트로 보충하고, 둘 다 없으면 t2i(연출)로 대체.
    (product_images만 넘기면 예전처럼 전부 제품컷으로 동작)
    """
    slots = image_slots(profile)
    prod = list(product_images or [])
    app = list(app_images or [])
    pi = ai = 0

    def take_product():
        nonlocal pi, ai
        if pi < len(prod):
            pi += 1
            return prod[pi - 1]
        if ai < len(app):
            ai += 1
            return app[ai - 1]
        return None

    def take_usage():
        nonlocal pi, ai
        if ai < len(app):
            ai += 1
            return app[ai - 1]
        if pi < len(prod):
            pi += 1
            return prod[pi - 1]
        return None

    for s in slots:
        path = take_usage() if s["kind"] == "usage" else take_product()
        s["image_path"] = path
        s["mode"] = "edit" if path else "t2i"
    return slots


if __name__ == "__main__":
    for cat in ["노트북", "패션·잡화·뷰티", "유기농 사과", "식품·유아·완구", "골프채", None]:
        key = resolve_archetype(cat)
        prof = ARCHETYPES[key]
        imgs = image_slots(prof)
        print(f"{str(cat):18s} → {key:8s} ({prof['label']}) | 이미지 {len(imgs)}컷 | "
              f"스펙 {len(prof['spec_fields'])}항목")
