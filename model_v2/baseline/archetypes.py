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
from baseline.composition_policy import placement_for

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
            {"type": "feature", "role": "lifestyle", "mode": "t2i", "text_zone": "bottom",
             "brief": "the product in a real usage moment"},
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


# 역할별 '선호 각도' — 다각도 사진이 있으면 이 각도의 실제 사진을 매칭 (정확 보존 모드)
_ROLE_ANGLE = {
    "hero": "정면", "build": "측면", "connectivity": "후면",
    "detail": "디테일",
    "lifestyle": "사용장면", "styling": "사용장면",
    "space": "사용장면", "serving": "사용장면",
}

# 자연 연출(natural) 모드 역할별 '선호 각도 우선순위'. 앞에서부터 일치하는 실제 사진을 쓴다.
# 정확 보존(preserve)은 _ROLE_ANGLE(단일)을 그대로 쓰므로 기존 배정이 완전히 동일하다.
_NATURAL_ROLE_ANGLES = {
    "hero": ["전면 3/4", "정면"],
    "build": ["측면", "전면 3/4", "정면"],
    "connectivity": ["후면 3/4", "후면", "측면", "정면"],
    "detail": ["디테일", "전면 3/4", "정면"],
    "material": ["디테일", "전면 3/4", "정면"],
    "fabric": ["디테일", "전면 3/4", "정면"],
    "ingredient": ["디테일", "전면 3/4", "정면"],
    "texture": ["디테일", "전면 3/4", "정면"],
    "lifestyle": ["사용장면", "전면 3/4", "정면"],
    "styling": ["사용장면", "전면 3/4", "정면"],
    "space": ["사용장면", "전면 3/4", "정면"],
    "serving": ["사용장면", "전면 3/4", "정면"],
}


def _role_angle_prefs(role: str, presentation_mode: str) -> list:
    """역할 → 선호 각도 우선순위 리스트.

    preserve는 단일 원소 리스트라 _pick_priority가 기존 _pick과 동치가 된다 → 배정 불변.
    """
    if presentation_mode == "natural":
        return _NATURAL_ROLE_ANGLES.get(role, [_ROLE_ANGLE.get(role)])
    return [_ROLE_ANGLE.get(role)]


def _pick(pool: list, angles: list, want: str | None):
    """want 각도와 일치하는 사진 우선(재사용 허용), 없으면 대표(첫) 사진.

    반환: (경로, 그 사진의 각도) — 각도는 씬 템플릿 매칭에 쓰임.
    """
    if not pool:
        return None, None
    if want:
        for i, p in enumerate(pool):
            if i < len(angles) and angles[i] == want:
                return p, angles[i]
    return pool[0], (angles[0] if angles else None)


def _pick_priority(pool: list, angles: list, wants: list):
    """선호 각도를 우선순위대로 시도, 일치 사진 우선. 없으면 대표(첫) 사진.

    wants가 단일 원소면 _pick과 완전히 동치 → 정확 보존 모드 배정이 불변이다.
    한 슬롯에 한 장만 고른다 — 여러 이미지를 동시에 API로 보내지 않는다.
    """
    if not pool:
        return None, None
    for want in wants:
        if not want:
            continue
        for i, p in enumerate(pool):
            if i < len(angles) and angles[i] == want:
                return p, angles[i]
    return pool[0], (angles[0] if angles else None)


def resolve_image_slots(profile: dict, product_images=None, app_images=None,
                        product_angles=None, app_angles=None, *,
                        presentation_mode: str = "preserve") -> list[dict]:
    """제품/응용 사진을 슬롯의 역할·선호각도에 맞춰 라우팅.

    - product_angles/app_angles: 각 사진의 각도 태그(정면/측면/후면/탑/디테일/사용장면).
      있으면 역할별 선호 각도와 매칭 → 컷마다 실제 다른 각도 사용(다각도, 옵션①).
      없으면 대표(첫) 사진 재사용 → 정면 반복(폴백).
    - kind=usage 슬롯: 응용 사진 우선, 없으면 제품 사진으로 대체(작게 합성=옵션②).
    - presentation_mode(키워드 전용, 기본 preserve): natural이면 역할별 선호 각도 우선순위가
      확장된다(전면 3/4 등). preserve면 기존 단일 각도라 배정 결과가 완전히 동일하다.
      선택된 실제 각도는 slot["angle"]에 그대로 남아 planner·LLM이 쓴다.
    """
    slots = image_slots(profile)
    prod = list(product_images or [])
    app = list(app_images or [])
    pa = list(product_angles or [])
    aa = list(app_angles or [])

    for s in slots:
        wants = _role_angle_prefs(s["role"], presentation_mode)
        if s["kind"] == "usage":
            path, ang = _pick_priority(app, aa, wants)
            if path:
                s["source"] = "usage"      # 실제 사용 사진 → 직접 사용
            else:
                path, ang = _pick_priority(prod, pa, wants)
                s["source"] = "product"    # 제품 사진 폴백 → 작게 합성
        else:
            path, ang = _pick_priority(prod, pa, wants)
            s["source"] = "product"
        s["image_path"] = path
        s["angle"] = ang                   # 씬 템플릿 각도 매칭용 (실제 각도 그대로)
        s["mode"] = "edit" if path else "t2i"
        placement = placement_for(s["role"])   # 역할별 좌우 구도 단일 원본
        s["composition_anchor"] = placement.anchor
        s["anchor_x_ratio"] = placement.x_ratio
    return slots


if __name__ == "__main__":
    for cat in ["노트북", "패션·잡화·뷰티", "유기농 사과", "식품·유아·완구", "골프채", None]:
        key = resolve_archetype(cat)
        prof = ARCHETYPES[key]
        imgs = image_slots(prof)
        print(f"{str(cat):18s} → {key:8s} ({prof['label']}) | 이미지 {len(imgs)}컷 | "
              f"스펙 {len(prof['spec_fields'])}항목")
