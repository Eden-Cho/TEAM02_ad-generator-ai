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
    # 각 축은 자기 축만 말한다 — 밝기는 '조명'만 규정하고 배경을 규정하지 않는다.
    # (시즌이 톤 전용이어야 하는 것과 같은 원칙. 아래 season 주석 참고)
    # 7단계가 "pure white studio background"를 말하던 시절엔 그 문구가 씬 골격의
    # {light} 슬롯에 박혀 원목·대리석 씬과 정면 충돌했다 → 조명 어휘만 남긴다.
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
            7: "extremely bright, luminous high-key lighting",
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
        # 시즌은 '분위기·색조'만 — 실물 오브젝트(낙엽·눈·꽃) 지시는 넣지 않는다.
        # (오브젝트를 넣으면 실내 제품컷에 낙엽/눈이 흩뿌려져 인위적으로 보임)
        "options": {
            "무관": "",
            "봄": "spring mood, soft fresh green and pastel tones, light and airy",
            "여름": "summer mood, bright clear daylight, fresh cool tones",
            "가을": "autumn mood, warm amber and terracotta tones, cozy soft light",
            "겨울": "winter mood, cool crisp tones with warm accents, soft diffused light",
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
    # 11) 창의성 (단계 1~5) — 낮을수록 제품 보존, 높을수록 자유로운 재해석(정확도↓)
    #
    # ui_levels: 일반 상품 UI에는 1~2(보존 모드)만 노출한다. 3 이상은 마스크 없는
    # images.edit 경로라 제품을 재렌더한다 — 상세페이지에서 제품이 곧 상품이므로
    # 기본 노출 대상이 아니다. 백엔드는 하위호환을 위해 3~5를 계속 수락하되,
    # creativity_warning()으로 재해석 경고를 돌려준다.
    "creativity": {
        "type": "scale", "target": "image", "label": "창의성 (↑=자유, 제품정확도↓)",
        "default": 2, "order": 11,
        "ui_levels": [1, 2],
        "levels": {
            1: "faithful, product-focused composition",
            2: "clean, product-focused composition",
            3: "varied camera angle and creative composition",
            4: "bold creative composition, dynamic angle, artistic styling",
            5: "highly artistic reinterpretation, dramatic and unique composition",
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

# 상세페이지(세로 긴 이미지) 마켓별 내보내기 폭 — 한 번 생성 후 규격별로 리사이즈 export
DETAIL_EXPORT_TARGETS = [
    {"name": "네이버 스마트스토어", "width": 860},
    {"name": "쿠팡", "width": 780},
    {"name": "고해상 (1080)", "width": 1080},
]


def export_targets() -> list[dict]:
    """마켓별 상세페이지 내보내기 대상(이름·폭). UI가 다운로드 버튼을 그린다."""
    return [dict(t) for t in DETAIL_EXPORT_TARGETS]


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
    creativity = int(selections.get("creativity", STYLE_DIMENSIONS["creativity"]["default"]))
    return {
        "image_keywords": image_keywords,
        "copy_directives": copy_directives,
        "size": size,
        "page_width": DETAIL_PAGE_WIDTH.get(site, DEFAULT_PAGE_WIDTH),
        "creativity": creativity,   # 1~5, 이미지 생성 보존↔재해석 강도
        "presentation_mode": normalize_presentation_mode(
            selections.get("presentation_mode")),   # preserve | natural
        "product_form": normalize_product_form(
            selections.get("product_form")),        # 폐쇄형 물리 형태 코드
    }


def image_keyword_map(selections: dict) -> dict[str, str]:
    """축별 이미지 키워드 맵 — 씬 템플릿 슬롯({mood}/{palette}/{light}/{props}) 채움용.

    build_style_context는 이미지 키워드를 리스트로 합치지만, 템플릿은 축별로 따로 필요.
    반환: {dim_id: keyword}  (예: {"mood": "minimalist...", "brightness": "very bright..."})
    """
    out: dict[str, str] = {}
    for dim_id, dim in STYLE_DIMENSIONS.items():
        if dim.get("target") != "image":
            continue
        kw = _keyword_for(dim, selections.get(dim_id, dim["default"]))
        if kw:
            out[dim_id] = kw
    return out


# 이 값 이상이면 제품을 재해석(재렌더)한다 — 보존 모드가 아니다.
CREATIVITY_REINTERPRET_MIN = 3

# 연출 모드 — 정확 보존(픽셀 합성) vs 자연 연출(제품+배경 함께 재렌더)
_PRESENTATION_MODES = ("preserve", "natural")

# 자연 연출 경고 — **결과 보장이 아니라 재렌더 주의**다. 자연 연출은 제품을 재렌더하므로
# "정확히 보존된다"고 단정하지 않는다.
_NATURAL_WARNING = ("자연 연출 모드는 제품을 재렌더합니다. 조명과 원근은 자연스러워지지만 "
                    "로고·포트·비율이 실제 상품과 달라질 수 있습니다.")


def normalize_presentation_mode(value) -> str:
    """허용값(preserve|natural)만 통과. 누락·오류·범위 밖은 preserve로 보정한다."""
    return value if value in _PRESENTATION_MODES else "preserve"


# 제품의 물리적 형태 — 폐쇄형 코드. 미지정은 unknown(기존 동작 유지). 자유 문자열·other 금지.
# solid_stick은 image_planner의 결정론적 안전 규칙(크림·용융·누출 표현 차단)을 켠다.
_PRODUCT_FORMS = ("unknown", "solid_stick", "cream", "liquid", "powder", "solid")


def normalize_product_form(value) -> str:
    """허용 코드만 통과. 미지정(None·"")은 unknown. 허용 외 값은 조기 ValueError로 거부한다.

    presentation_mode처럼 조용히 보정하지 않는다 — 잘못된 형태를 unknown으로 삼키면
    안전 규칙이 잘못된 제품에 적용/미적용될 수 있어 명시적으로 실패시킨다.
    """
    if value in (None, ""):
        return "unknown"
    if value not in _PRODUCT_FORMS:
        raise ValueError(
            f"허용되지 않은 product_form: {value!r} (허용: {_PRODUCT_FORMS})")
    return value


# ── 입력 품질·모드 추천 (폐쇄형 코드 + 고정 문구) ──────────────────────────────
# 제품 이미지 해상도·업로드 각도 수·product_form·presentation_mode로 안전한 추천·경고를
# 만든다. **선택한 모드를 바꾸지 않는다** — 코드와 고정 문구만 돌려주고 표시는 프론트가 한다.
from enum import Enum   # noqa: E402  (모듈 상단 import 최소화 — 이 블록 전용)

# 이 미만이면 저해상도로 본다(최소 변 기준). apple 190·sunstick 349 = 저해상, macmini 2160=정상.
LOW_RES_MIN_PX = 512


class InputAdvice(str, Enum):
    LOW_RES_LIMITS_BOTH_MODES = "low_res_limits_both_modes"
    FEW_ANGLES_NATURAL_INVENTS = "few_angles_natural_invents"
    NATURAL_RERENDER_CAUTION = "natural_rerender_caution"
    CREATIVITY_REINTERPRETS = "creativity_reinterprets"
    SOLID_STICK_PREFER_PRESERVE = "solid_stick_prefer_preserve"


_INPUT_ADVICE_TEXT = {
    InputAdvice.LOW_RES_LIMITS_BOTH_MODES:
        "제품 이미지 해상도가 낮습니다. 정확 보존은 누끼 경계가 뭉개지고, 자연 연출은 재렌더 "
        "왜곡이 생길 수 있어 두 모드 모두 제품 정확도에 한계가 있습니다. 자연 연출이 저해상도를 "
        "해결한다고 볼 수 없습니다 — 가능하면 고해상 원본을 올리세요.",
    InputAdvice.FEW_ANGLES_NATURAL_INVENTS:
        "업로드한 실제 각도가 적습니다. 자연 연출은 보지 못한 각도를 임의로 생성할 수 있으니 "
        "필요한 각도의 실제 사진을 추가하면 정확도가 좋아집니다.",
    InputAdvice.NATURAL_RERENDER_CAUTION: _NATURAL_WARNING,
    InputAdvice.CREATIVITY_REINTERPRETS:
        "창의성 3단계 이상은 제품을 재해석합니다 — 생성된 제품이 실제 상품과 다를 수 있습니다. "
        "실물 그대로가 필요하면 1~2단계를 사용하세요.",
    InputAdvice.SOLID_STICK_PREFER_PRESERVE:
        "고체 스틱형은 패키지 외관 정확도가 중요합니다 — 정확 보존(preserve)을 권장합니다. "
        "확인되지 않은 제형(크림·로션 등) 생성은 자동으로 차단됩니다.",
}


# 근거(성분·제형)가 있어야 안전한 역할 — 제품 외관만으로는 검증 불가한 내용을 주장한다.
# 사용자가 '공식 자료로 확인한' 성분명·제형 설명을 실제로 입력해야 해당 역할이 적용된다.
EVIDENCE_REQUIRED_ROLES = ("ingredient", "texture")
_EVIDENCE_MAX_ITEMS = 12          # 역할당 검증 항목 수 상한
_EVIDENCE_MAX_ITEM_LEN = 80       # 항목 문자열 길이 상한(과도하게 긴 값 거부)


def normalize_evidence(value) -> dict:
    """사용자가 입력한 검증 근거 → {role: (검증 문자열, ...)}. **역할 적용은 내용에서 파생**한다.

    구조 계약(위반은 조기 ValueError):
      - dict(또는 미지정 None → {})만 허용
      - 키는 ingredient·texture만(미지원 역할 거부)
      - 값은 **공백 아닌 문자열의 비어 있지 않은 리스트**
      - 항목은 공백 아닌 str, {_EVIDENCE_MAX_ITEM_LEN}자 이하, 역할당 {_EVIDENCE_MAX_ITEMS}개 이하
    빈 값·잘못된 타입·미지원 역할·과도하게 긴 값을 조용히 흡수하지 않는다.
    검증 원문은 여기서 정규화만 하고, 이미지 프롬프트 외(trace·warnings·safe dict·로그)로는
    내보내지 않는다(호출부 계약).
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("evidence는 object여야 한다")
    out = {}
    for role, items in value.items():
        if role not in EVIDENCE_REQUIRED_ROLES:
            raise ValueError(f"지원하지 않는 근거 역할: {role!r} "
                             f"(허용: {EVIDENCE_REQUIRED_ROLES})")
        if not isinstance(items, list) or not items:
            raise ValueError(f"{role} 근거는 비어 있지 않은 list여야 한다: {items!r}")
        if len(items) > _EVIDENCE_MAX_ITEMS:
            raise ValueError(f"{role} 근거 항목이 너무 많다(>{_EVIDENCE_MAX_ITEMS})")
        cleaned = []
        for it in items:
            if not isinstance(it, str) or not it.strip():
                raise ValueError(f"{role} 근거 항목은 공백 아닌 문자열이어야 한다: {it!r}")
            s = it.strip()
            if len(s) > _EVIDENCE_MAX_ITEM_LEN:
                raise ValueError(f"{role} 근거 항목이 너무 길다(>{_EVIDENCE_MAX_ITEM_LEN}자)")
            cleaned.append(s)
        out[role] = tuple(cleaned)
    return out


def input_advice(selections: dict, *, min_resolution=None,
                 n_product_angles: int = 0) -> tuple:
    """입력·선택값 → 폐쇄형 추천·경고 코드(등장 순서). **선택 모드를 변경하지 않는다.**

    브랜드·라벨은 추측하지 않는다 — presentation_mode·product_form·명시 수치만 본다.
    저해상도는 두 모드 모두 한계임을 알린다(natural이 해결한다고 단정하지 않는다).
    """
    mode = normalize_presentation_mode(selections.get("presentation_mode"))
    form = normalize_product_form(selections.get("product_form"))
    creativity = int(selections.get("creativity",
                                    STYLE_DIMENSIONS["creativity"]["default"]))
    codes = []
    if isinstance(min_resolution, (int, float)) and min_resolution < LOW_RES_MIN_PX:
        codes.append(InputAdvice.LOW_RES_LIMITS_BOTH_MODES)
    if mode == "natural" and n_product_angles <= 1:
        codes.append(InputAdvice.FEW_ANGLES_NATURAL_INVENTS)
    if mode == "natural":
        codes.append(InputAdvice.NATURAL_RERENDER_CAUTION)
    if creativity >= CREATIVITY_REINTERPRET_MIN:
        codes.append(InputAdvice.CREATIVITY_REINTERPRETS)
    if form == "solid_stick":
        codes.append(InputAdvice.SOLID_STICK_PREFER_PRESERVE)
    return tuple(codes)


def advice_messages(codes) -> list:
    """폐쇄형 코드 → 고정 한국어 문구. 알 수 없는 코드는 조용히 무시하지 않고 KeyError."""
    return [_INPUT_ADVICE_TEXT[c] for c in codes]


def creativity_warning(selections: dict) -> str | None:
    """창의성 3+ 요청 시 사용자에게 돌려줄 경고. 보존 모드면 None.

    UI는 1~2만 노출하지만 API는 하위호환으로 3~5를 수락하므로, 수락하되 알린다.
    """
    v = int(selections.get("creativity", STYLE_DIMENSIONS["creativity"]["default"]))
    if v < CREATIVITY_REINTERPRET_MIN:
        return None
    return (f"창의성 {v}단계는 제품을 재해석합니다 — 생성된 제품이 실제 상품과 "
            "다를 수 있습니다. 실물 그대로가 필요하면 1~2단계를 사용하세요.")


def natural_warning(selections: dict) -> str | None:
    """자연 연출 모드일 때만 재렌더 주의 문구. 그 외에는 None. **순수 함수.**"""
    if normalize_presentation_mode(selections.get("presentation_mode")) != "natural":
        return None
    return _NATURAL_WARNING


def ui_dimensions() -> list[dict]:
    """UI 노출용 — order 순으로 정렬된 축 목록 (선택지/기본값 포함).

    ui_levels가 있으면 그 범위만 노출한다(예: creativity는 보존 모드 1~2만).
    levels 원본은 건드리지 않으므로 API는 계속 전 범위를 수락한다.
    """
    dims = []
    for dim_id, dim in sorted(STYLE_DIMENSIONS.items(), key=lambda x: x[1]["order"]):
        if dim["type"] == "scale":
            choices = list(dim.get("ui_levels") or dim["levels"].keys())
        else:
            choices = list(dim.get("ui_options") or dim["options"].keys())
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
