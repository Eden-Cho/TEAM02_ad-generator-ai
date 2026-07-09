"""스타일 옵션 레지스트리 — 단일 진실 공급원(single source of truth).

UI는 이 테이블을 읽어 선택지를 그리고,
prompt_generator / copy_generator 는 여기서 키워드/지시문을 가져온다.

각 축(dimension) 속성:
    type   : "scale"(단계 1~N) | "choice"(선택지)
    target : "image"(이미지 프롬프트) | "copy"(카피) | "output"(출력 규격)
    label  : UI 표기명
    default: 기본값
    order  : UI 노출 순서
    levels : {단계값: 키워드}        # type == "scale"
    options: {선택라벨: 키워드/값}    # type == "choice"
"""
import baseline.config as config

STYLE_DIMENSIONS: dict[str, dict] = {
    # 1) 사이트 규격 — 최상단, 출력 크기 결정
    "site_spec": {
        "type": "choice", "target": "output", "label": "사이트 규격",
        "default": "네이버 스마트스토어", "order": 1,
        # 값 = GPT-Image 지원 크기 (필요 시 후처리에서 실제 규격으로 리사이즈)
        "options": {
            "네이버 스마트스토어": "1024x1536",
            "쿠팡": "1024x1536",
            "인스타 정사각": "1024x1024",
            "가로 배너": "1536x1024",
        },
    },
    # 2) 카피 톤
    "copy_tone": {
        "type": "choice", "target": "copy", "label": "카피 톤",
        "default": "신뢰·전문", "order": 2,
        "options": {
            "신뢰·전문": "신뢰감 있고 전문적인 톤. 제품 스펙과 근거를 담백하게 강조.",
            "감성·따뜻": "감성적이고 따뜻한 톤. 일상 속 가치와 분위기를 부드럽게 전달.",
            "활기·경쾌": "활기차고 경쾌한 톤. 짧고 리듬감 있는 문장으로 에너지 있게.",
            "프리미엄": "고급스럽고 절제된 톤. 품격과 완성도를 강조.",
            "위트": "위트 있고 가벼운 톤. 재치 있는 표현으로 눈길을 끌기.",
        },
    },
    # 3) 밝기 (단계 1~7)
    "brightness": {
        "type": "scale", "target": "image", "label": "밝기",
        "default": 4, "order": 3,
        "levels": {
            1: "very dark, low-key lighting, deep shadows, moody atmosphere",
            2: "dark, dim ambient light, dramatic shadows",
            3: "slightly dark, soft moody lighting",
            4: "balanced natural lighting, neutral exposure",
            5: "bright, soft diffused daylight, airy",
            6: "very bright, clean white light, high-key",
            7: "extremely bright, pure white studio background, luminous, high-key",
        },
    },
    # 4) 색조 팔레트
    "color_palette": {
        "type": "choice", "target": "image", "label": "색조 팔레트",
        "default": "화이트·크림", "order": 4,
        "options": {
            "화이트·크림": "white and cream palette, ivory tones, soft and airy",
            "다크": "dark palette, deep charcoal and black tones, moody",
            "파스텔": "pastel palette, soft muted colors, gentle tones",
            "어스톤": "earth tone palette, warm browns, terracotta, beige",
            "비비드": "vivid palette, bold saturated colors, high contrast",
        },
    },
    # 5) 배경 유형
    "background": {
        "type": "choice", "target": "image", "label": "배경 유형",
        "default": "스튜디오 단색", "order": 5,
        "options": {
            "스튜디오 단색": "seamless solid color studio backdrop, clean",
            "자연 야외": "natural outdoor setting, organic environment, daylight",
            "인테리어 공간": "styled interior lifestyle space, home environment",
            "질감 표면": "textured surface, marble or wood tabletop, tactile detail",
            "그라디언트": "smooth gradient background, soft color transition",
        },
    },
    # 6) 무드
    "mood": {
        "type": "choice", "target": "image", "label": "무드",
        "default": "미니멀", "order": 6,
        "options": {
            "미니멀": "minimalist, clean lines, uncluttered, modern, negative space",
            "럭셔리": "luxury, premium, elegant, sophisticated, high-end",
            "내추럴": "natural, organic, botanical, eco, wood and plants",
            "트렌디": "trendy, contemporary, vibrant, youthful, dynamic",
            "빈티지": "vintage, retro, nostalgic, aged texture, classic",
        },
    },
    # 7) 소품 연출 밀도 (단계 1~5)
    "prop_density": {
        "type": "scale", "target": "image", "label": "소품 연출 밀도",
        "default": 2, "order": 7,
        "levels": {
            1: "no props, clean empty background, maximal negative space",
            2: "very few props, mostly empty, simple composition",
            3: "a few complementary props, balanced styling",
            4: "styled with several props and decorative elements",
            5: "richly styled scene, abundant complementary props and decor",
        },
    },
    # 8) 시즌감
    "season": {
        "type": "choice", "target": "image", "label": "시즌감",
        "default": "무관", "order": 8,
        "options": {
            "무관": "",
            "봄": "spring season mood, fresh blossoms, soft green tones, light",
            "여름": "summer season mood, bright sunlight, fresh cool tones",
            "가을": "autumn season mood, warm amber, cozy, fallen leaves",
            "겨울": "winter season mood, cool tones, cozy warm accents, snow",
        },
    },
    # 9) 타깃 고객 (카피에 반영)
    "target_audience": {
        "type": "choice", "target": "copy", "label": "타깃 고객",
        "default": "직장인", "order": 9,
        "options": {
            "2030 여성": "20~30대 여성 타깃. 트렌디하고 감각적인 표현.",
            "직장인": "직장인 타깃. 실용성과 효율, 일상 속 편의를 강조.",
            "가족": "가족 단위 타깃. 안심·신뢰·함께하는 가치를 강조.",
            "시니어": "시니어 타깃. 쉽고 명확한 표현, 편리함과 안심을 강조.",
            "자유": "",
        },
    },
    # 10) 포지셔닝 (단계 1~5, 카피에 반영)
    "positioning": {
        "type": "scale", "target": "copy", "label": "포지셔닝",
        "default": 3, "order": 10,
        "levels": {
            1: "가성비와 실용성을 최우선으로 강조.",
            2: "합리적 가격 대비 만족을 강조.",
            3: "가격과 품질의 균형을 강조.",
            4: "품질과 완성도를 우선 강조.",
            5: "프리미엄 가치와 고급감을 최우선으로 강조.",
        },
    },
}


# 사이트별 상세페이지 가로폭(px) — composer가 이 폭으로 조립
DETAIL_PAGE_WIDTH = {
    "네이버 스마트스토어": 860,
    "쿠팡": 780,
    "인스타 정사각": 1080,
    "가로 배너": 1080,
}
DEFAULT_PAGE_WIDTH = 1080


def _keyword_for(dim: dict, value):
    """축의 선택값 -> 키워드/지시문."""
    if dim["type"] == "scale":
        return dim["levels"].get(int(value), "")
    return dim["options"].get(value, "")


def build_style_context(selections: dict) -> dict:
    """사용자 선택값 -> 파이프라인이 쓰는 형태로 변환.

    반환:
        {
          "image_keywords": list[str],   # 이미지 프롬프트용 영어 키워드
          "copy_directives": dict,       # 카피용 한글 지시문 {dim_id: str}
          "size": str,                   # 출력 크기 (예: "1024x1536")
        }
    """
    image_keywords: list[str] = []
    copy_directives: dict[str, str] = {}
    size = config.IMAGE_SIZE

    for dim_id, dim in STYLE_DIMENSIONS.items():
        value = selections.get(dim_id, dim["default"])
        keyword = _keyword_for(dim, value)

        if dim["target"] == "output":
            size = dim["options"].get(value, config.IMAGE_SIZE)
        elif not keyword:
            continue
        elif dim["target"] == "image":
            image_keywords.append(keyword)
        elif dim["target"] == "copy":
            copy_directives[dim_id] = keyword

    site = selections.get("site_spec", STYLE_DIMENSIONS["site_spec"]["default"])
    return {
        "image_keywords": image_keywords,
        "copy_directives": copy_directives,
        "size": size,
        "page_width": DETAIL_PAGE_WIDTH.get(site, DEFAULT_PAGE_WIDTH),
    }


def ui_dimensions() -> list[dict]:
    """UI 노출용 — order 순으로 정렬된 축 목록 (선택지/기본값 포함)."""
    dims = []
    for dim_id, dim in sorted(STYLE_DIMENSIONS.items(), key=lambda x: x[1]["order"]):
        choices = (list(dim["levels"].keys()) if dim["type"] == "scale"
                   else list(dim["options"].keys()))
        dims.append({"id": dim_id, "label": dim["label"], "type": dim["type"],
                     "default": dim["default"], "choices": choices})
    return dims


if __name__ == "__main__":
    import json

    sample = {"site_spec": "네이버 스마트스토어", "brightness": 6, "mood": "미니멀",
              "color_palette": "화이트·크림", "background": "질감 표면",
              "prop_density": 2, "season": "무관", "copy_tone": "신뢰·전문",
              "target_audience": "직장인", "positioning": 4}
    print(json.dumps(build_style_context(sample), ensure_ascii=False, indent=2))
