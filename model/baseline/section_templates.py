"""장수(2/3/4) -> 고정 섹션 골격.

역할(role) / mode / text_zone 은 여기서 고정된다.
GPT는 각 슬롯의 이미지 프롬프트(scene)만 채우고, 골격은 지어내지 않는다.
누적 구조: 2 -> 3 -> 4 로 갈수록 앞 구성은 유지하고 뒤 섹션만 추가.

- mode: "edit" = 실제 제품 보존 / "t2i" = 제품 없이 연출
- brief: GPT에 넘길 장면 지시 (영어)
"""

_HERO = {
    "role": "hero", "mode": "edit", "text_zone": "bottom",
    "brief": ("Main hero shot with the product as the clear focal point, "
              "spacious and balanced composition, front or three-quarter angle."),
}
_DETAIL = {
    "role": "detail", "mode": "edit", "text_zone": "top",
    "brief": ("Close-up styling emphasizing the product's material and texture "
              "on a tactile surface."),
}
_FEATURE_1 = {
    "role": "feature_1", "mode": "edit", "text_zone": "top",
    "brief": "Close-up emphasizing the material and texture quality of the product.",
}
_FEATURE_2 = {
    "role": "feature_2", "mode": "edit", "text_zone": "top",
    "brief": "Close-up emphasizing a key function or a usage moment of the product.",
}
_LIFESTYLE = {
    "role": "lifestyle", "mode": "t2i", "text_zone": "bottom",
    "brief": ("Lifestyle scene showing the product used in a real everyday "
              "context with mood and atmosphere."),
}

SECTION_TEMPLATES: dict[int, list[dict]] = {
    2: [_HERO, _DETAIL],
    3: [_HERO, _DETAIL, _LIFESTYLE],
    4: [_HERO, _FEATURE_1, _FEATURE_2, _LIFESTYLE],
}

ALLOWED_COUNTS = (2, 3, 4)


def clamp_count(n) -> int:
    """허용 범위(2~4)로 보정. 잘못된 값은 기본 3."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return 3
    return min(max(n, 2), 4)


def get_template(n) -> list[dict]:
    """장수 -> 슬롯 목록(복사본). 호출자가 수정해도 원본 불변."""
    return [dict(slot) for slot in SECTION_TEMPLATES[clamp_count(n)]]


def resolve_slots(n, image_paths=None) -> list[dict]:
    """슬롯에 업로드 사진을 순서대로 매핑하고 mode를 결정한다.

    - 사진이 매핑된 슬롯 → mode="edit" (실제 제품 보존)
    - 사진이 없는 슬롯   → mode="t2i"  (연출 생성)
    각 슬롯에 image_path 키를 추가한다.
    """
    slots = get_template(n)
    image_paths = list(image_paths or [])
    for i, s in enumerate(slots):
        img = image_paths[i] if i < len(image_paths) else None
        s["image_path"] = img
        s["mode"] = "edit" if img else "t2i"
    return slots


if __name__ == "__main__":
    for count in ALLOWED_COUNTS:
        print(f"[{count}장]")
        for i, s in enumerate(get_template(count), 1):
            print(f"  {i}. {s['role']:10s} mode={s['mode']:4s} text={s['text_zone']}")
