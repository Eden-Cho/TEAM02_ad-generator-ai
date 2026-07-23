"""씬 템플릿 레지스트리 — 검증된 배경 씬을 '슬롯 채움' 방식으로 제공.

원칙 (편차 제거의 핵심):
  - 구조(씬 종류·카메라 앵글·표면 위치·구도)는 **고정** → 각도 호환·배경/제품 정합 보장
  - 마감(조명·색조·무드·소품)만 **슬롯**으로 가변 → 스타일 축 반영
  - 씬을 LLM이 매번 창작하지 않음 → 밋밋함↔산만함 편차가 사라짐

템플릿 필드:
    id/label        식별자·UI명
    angle           호환 카메라 관점 (현재 전부 "정면" = straight-on eye-level)
    background_type 스타일 축 '배경 유형' → 템플릿 선택자
    archetypes/roles 어울리는 아키타입·역할 (None=전체)
    surface_ratio   배경의 표면(바닥선) 위치 → 합성 배치 기준
    product_scale   권장 제품 폭 비율
    allowed         축별 허용 선택값 (깨지는 조합 차단)
    structure       고정 뼈대를 이루는 '절 목록' — 단일 원본. skeleton_of()가 조립한다.
    base_props      씬에 딸린 장식 소품 (list[str], 없으면 []). {base_props} 슬롯으로
                    들어가며 prop_density 예산의 통제를 받는다.

structure가 단일 원본인 이유:
    뼈대를 통짜 문자열로 두면 "이 문구가 구조인가 장식인가"를 코드가 알 수 없어,
    소품 예산(prop_density)이 뼈대 안의 소품을 통제하지 못한다. 또 테스트가 구조 보존을
    검사하려면 절 목록이 따로 필요한데, 문자열과 절 목록을 각각 관리하면 둘이 어긋난다.
    → 절 목록만 두고 문자열은 항상 파생한다.
"""
from collections import Counter

from baseline.composition_policy import placement_for
from baseline.image_plan import prop_budget_for
from baseline.style_presets import STYLE_DIMENSIONS, image_keyword_map

# 활용(사용 맥락) 컷 역할 — 배경 유형보다 '맥락'이 우선인 슬롯
_USAGE_ROLES = {"lifestyle", "styling", "space", "serving"}

# 모든 템플릿 공통 접미 (컴포지팅 전제: 배경에 제품이 없어야 함)
#
# 손·사람 배제가 필수인 이유: 컴포지팅은 제품이 항상 최상위 레이어라 가림(occlusion)이
# 구조적으로 불가능하다. 배경에 손이 나오면 제품 뒤에서 허공을 쥔다. 요청하지 않아도
# 모델이 자발적으로 손을 그려 넣는다(experiments/20260715/sun2_usage.png).
# 리파인 재투입으로 가림을 만들려는 시도는 제품을 재렌더해 폐기됨 → 손을 안 만드는 게 답.
_SUFFIX = ("no product in the center, empty surface ready for a product, "
           "no hands, no people, no body parts, "
           "no text, no watermark")

SCENE_TEMPLATES: list[dict] = [
    {
        "id": "white_studio", "label": "화이트 스튜디오",
        # 뼈대가 'straight-on eye-level'이므로 탑뷰와는 호환되지 않음 → 정면
        "angle": "정면", "background_type": "스튜디오 단색",
        "archetypes": None, "roles": None,          # 전체 (폴백)
        "surface_ratio": 0.80, "product_scale": 0.60,
        "allowed": {},                               # 제한 없음
        "is_generic": False,
        "structure": [
            "a clean seamless product photography studio backdrop",
            "straight-on eye-level camera angle",
            "a smooth surface across the lower area where a product rests",
            "{base_props}",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 스튜디오는 소품 없음이 정체성
    },
    {
        "id": "wood_desk", "label": "밝은 원목 책상",
        "angle": "정면", "background_type": "질감 표면",
        "archetypes": ["tech", "living", "general"],
        "roles": ["hero", "build", "connectivity", "detail", "material"],
        "surface_ratio": 0.78, "product_scale": 0.60,
        "allowed": {"brightness": [3, 4, 5, 6, 7]},  # 어두운 톤은 원목 씬과 부조화
        "is_generic": False,
        "structure": [
            "a front-facing bright wooden desk scene",
            "straight-on eye-level camera angle",
            "a clear wooden surface across the lower area where a device rests",
            "a softly blurred background behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": ["a small potted plant", "stacked books"],
    },
    {
        "id": "usage_scene", "label": "사용 장면 (맥락)",
        "angle": "정면", "background_type": "인테리어 공간",
        # 맥락을 LLM이 제품별로 채우므로 카테고리 무관하게 사용 가능
        "archetypes": None,
        "roles": ["lifestyle", "styling", "space", "serving"],   # 활용 컷 전용
        "surface_ratio": 0.80, "product_scale": 0.50,
        "allowed": {"brightness": [3, 4, 5, 6, 7]},
        "is_generic": False,
        # usage_context는 이 템플릿의 슬롯이 아니다 — 활용 역할이면 어떤 템플릿에
        # 착지하든 fill()이 공통 파트로 넣는다. 여기 슬롯으로 두면 usage 역할이
        # 다른 템플릿에 착지할 때 LLM 조사 결과가 조용히 사라진다(그게 원래 버그였다).
        "structure": [
            "a real product usage scene",
            "straight-on front-facing camera angle",
            "a clear surface in the foreground where the product sits",
            "{base_props}",
            "shallow depth of field",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 맥락은 usage_context가 담당 — 고정 소품 없음
    },
    {
        "id": "warm_shelf", "label": "따뜻한 선반",
        "angle": "정면", "background_type": "인테리어 공간",
        "archetypes": ["living", "general", "beauty"],
        "roles": ["hero", "build", "detail", "styling", "space", "material"],
        "surface_ratio": 0.76, "product_scale": 0.55,
        "allowed": {"brightness": [3, 4, 5, 6, 7]},
        "is_generic": False,
        "structure": [
            "a front-facing warm interior shelf ledge",
            "straight-on eye-level camera angle",
            "a clear ledge surface across the lower area where a product rests",
            "softly blurred cozy interior behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 'cozy interior'는 구조 — 명시 소품은 없음
    },
    # ── 증설분 ─────────────────────────────────────────────
    {
        "id": "concrete_matte", "label": "무광 콘크리트",
        "angle": "정면", "background_type": "질감 표면",
        "archetypes": ["tech", "general"],
        "roles": ["hero", "build", "connectivity", "detail", "material"],
        "surface_ratio": 0.79, "product_scale": 0.62,
        "allowed": {},                               # 어두운 톤도 어울림
        "is_generic": False,
        "structure": [
            "a front-facing matte concrete surface scene",
            "straight-on eye-level camera angle",
            "a clean concrete surface across the lower area where a device rests",
            "a softly blurred background behind",
            "a subtle textured wall",      # 벽은 씬의 구조 — 소품이 아니다
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": ["a matte ceramic vase", "stacked books"],
    },
    {
        "id": "window_light_desk", "label": "창가 자연광 데스크",
        "angle": "정면", "background_type": "인테리어 공간",
        "archetypes": ["tech", "living", "general"],
        "roles": ["hero", "build", "detail", "lifestyle"],
        "surface_ratio": 0.78, "product_scale": 0.56,
        "allowed": {"brightness": [4, 5, 6, 7]},     # 창가 = 밝은 톤 전제
        "is_generic": False,
        "structure": [
            "a front-facing desk beside a bright window",
            "straight-on eye-level camera angle",
            "a clear desk surface across the lower area where a device rests",
            "soft daylight from the side",
            # 커튼은 '창가' 정체성이라 구조다 — 소품을 다 빼도 남아야 씬이 성립한다
            "a softly blurred sheer curtain behind",
            "{base_props}",
            "shallow depth of field",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": ["a potted plant"],
    },
    {
        "id": "soft_gradient", "label": "부드러운 그라디언트",
        "angle": "정면", "background_type": "그라디언트",   # 뼈대가 eye-level
        "archetypes": None, "roles": None,
        "surface_ratio": 0.80, "product_scale": 0.60,
        "allowed": {},
        "is_generic": False,
        "structure": [
            "a smooth gradient studio background",
            "straight-on eye-level camera angle",
            "a soft seamless surface across the lower area where a product rests",
            "a gentle color transition",
            "{base_props}",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 그라디언트는 소품 없음이 정체성
    },
    {
        "id": "marble_top", "label": "대리석 상판",
        "angle": "정면", "background_type": "질감 표면",
        "archetypes": ["beauty", "food", "living"],
        "roles": ["hero", "build", "detail", "serving", "styling", "ingredient", "texture"],
        "surface_ratio": 0.77, "product_scale": 0.55,
        "allowed": {"brightness": [4, 5, 6, 7]},     # 대리석 = 밝고 청결한 톤
        "is_generic": False,
        "structure": [
            "a front-facing polished marble countertop scene",
            "straight-on eye-level camera angle",
            "a clean marble surface across the lower area where a product rests",
            "a softly blurred bright interior behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 'bright interior'는 구조 — 명시 소품은 없음
    },
    {
        "id": "linen_fabric", "label": "리넨 패브릭",
        "angle": "정면", "background_type": "질감 표면",
        "archetypes": ["fashion", "living", "beauty"],
        "roles": ["hero", "build", "detail", "styling", "fabric", "texture"],
        "surface_ratio": 0.78, "product_scale": 0.55,
        "allowed": {},
        "is_generic": False,
        "structure": [
            "a front-facing soft linen fabric surface scene",
            "straight-on eye-level camera angle",
            "gently draped linen across the lower area where a product rests",
            "a softly blurred warm neutral backdrop behind",
            "{base_props}",
            "shallow depth of field",
            "a soft natural shadow",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],          # 리넨 자체가 표면 — 명시 소품은 없음
    },
    {
        "id": "natural_outdoor", "label": "자연 야외",
        "angle": "정면", "background_type": "자연 야외",
        "archetypes": ["living", "general", "food"],
        "roles": ["hero", "lifestyle", "space", "serving", "ingredient"],
        "surface_ratio": 0.78, "product_scale": 0.52,
        "allowed": {"brightness": [4, 5, 6, 7]},
        "is_generic": False,
        "structure": [
            "a front-facing natural outdoor setting",
            "straight-on eye-level camera angle",
            "a natural wooden table surface across the lower area where a product rests",
            # 초록은 소품이라 예산을 받는다 — 빠져도 '야외 + 원목 상판 + 자연광'으로 성립한다
            "softly blurred daylight behind",
            "{base_props}",
            "shallow depth of field",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": ["soft greenery"],
    },

    # ── 범용 템플릿 ────────────────────────────────────────
    # 사용자가 고른 배경 유형을 지키기 위한 안전망. 전에는 배경 유형 5개 중 3개
    # (스튜디오 단색·그라디언트·자연 야외)만 무제약 템플릿이 있어, 나머지 배경에서는
    # 아키타입·역할·밝기 조건에 걸리면 후보가 0개가 됐다 — 그러면 사용자가 고른 배경을
    # 벗어난 씬이 나온다(자연 야외 70% / 인테리어 40% / 질감 45%).
    # white_studio·soft_gradient가 자기 배경에서 하던 역할을 나머지 3개 배경으로
    # 대칭 확장한 것뿐이다.
    #
    # 제약 없음(archetypes/roles=None, allowed={}, angle="any")이 존재 이유다 —
    # 여기에 조건을 붙이면 안전망에 다시 구멍이 뚫린다.
    # 구조에 밝기·색·소품을 하드코딩하지 않는다. 그건 전부 스타일 슬롯의 몫이다.
    {
        "id": "generic_outdoor", "label": "야외 (범용)",
        "angle": "any", "background_type": "자연 야외",
        "archetypes": None, "roles": None,
        "surface_ratio": 0.78, "product_scale": 0.55,
        "allowed": {},
        "is_generic": True,
        "structure": [
            "a natural outdoor setting",
            "straight-on eye-level camera angle",
            "a clear natural surface across the lower area where a product rests",
            "a softly blurred outdoor background behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],
    },
    {
        "id": "generic_interior", "label": "실내 (범용)",
        "angle": "any", "background_type": "인테리어 공간",
        "archetypes": None, "roles": None,
        "surface_ratio": 0.78, "product_scale": 0.55,
        "allowed": {},
        "is_generic": True,
        "structure": [
            "an interior living space scene",
            "straight-on eye-level camera angle",
            "a clear surface across the lower area where a product rests",
            "a softly blurred interior background behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],
    },
    {
        "id": "generic_texture", "label": "질감 표면 (범용)",
        "angle": "any", "background_type": "질감 표면",
        "archetypes": None, "roles": None,
        "surface_ratio": 0.78, "product_scale": 0.58,
        "allowed": {},
        "is_generic": True,
        "structure": [
            "a textured tabletop surface scene",
            "straight-on eye-level camera angle",
            "a clear textured surface across the lower area where a product rests",
            "a softly blurred background behind",
            "{base_props}",
            "shallow depth of field",
            "a subtle soft shadow on the surface",
            "{mood}", "{palette}", "{light}", "{props}", "{season}",
        ],
        "base_props": [],
    },
]

_FALLBACK_ID = "white_studio"

# 동률일 때의 우선순위 = 선언 순서. 범용 템플릿이 목록 끝에 있으므로,
# 처음 고를 때는 전용 템플릿이 항상 먼저 온다.
_ORDER = {t["id"]: i for i, t in enumerate(SCENE_TEMPLATES)}

# 사진 각도(제품의 '어느 면')  →  템플릿 각도(카메라 관점)
# 정면/후면/측면/디테일 모두 카메라는 straight-on → "정면" 템플릿과 호환.
# (탑뷰는 컴포지터가 제대로 그라운딩하지 못해 미지원 — 수요 생기면 함께 구현)
_ANGLE_TO_CAMERA = {
    "정면": "정면", "후면": "정면", "측면": "정면", "디테일": "정면",
    "사용장면": None,
}


def _camera(angle: str | None) -> str | None:
    """사진 각도를 카메라 관점으로 정규화 (없으면 제한 없음)."""
    if not angle:
        return None
    return _ANGLE_TO_CAMERA.get(angle, angle)


def select_base_props(base_props, prop_density) -> list[str]:
    """밀도에 따라 프롬프트에 명시할 base_props를 고른다. **순수 함수.**

    예산의 단일 원본은 baseline.image_plan.PROP_BUDGET이다. 여기와 planner가 같은 표를
    봐야 하므로 중복 테이블을 두지 않는다. base가 "all"이면 전체, 정수면 앞에서부터 그 수.

    "0개"는 프롬프트에 명시하는 소품이 0개라는 뜻이지 생성 이미지에 소품이 없다는 뜻이
    아니다 — 모델은 지시하지 않은 소품도 그린다.
    """
    base = prop_budget_for(prop_density).base
    return list(base_props) if base == "all" else list(base_props[:base])


def skeleton_of(t: dict) -> str:
    """structure(단일 원본) → 조립된 뼈대 문자열.

    뼈대를 저장하지 않고 항상 여기서 파생한다 — 문자열과 절 목록을 둘 다 두면 어긋난다.
    """
    return ", ".join(t["structure"])


def structure_clauses(t: dict) -> list[str]:
    """슬롯이 없는 순수 구조 절 — 최종 프롬프트에 **축자 그대로** 남아야 하는 것들.

    슬롯이 든 절({mood} 등)은 치환되므로 축자 보존 검사 대상이 아니다.
    """
    return [c for c in t["structure"] if "{" not in c]


# 모든 템플릿 structure의 꼬리 — 스타일 축 슬롯. 조립 순서를 여기서 고정한다.
_STYLE_TAIL = ("{mood}", "{palette}", "{light}", "{props}", "{season}")

# 활용 역할 공통 파트 — 특정 템플릿의 슬롯이 아니다.
_USAGE_PART = "{usage_context}, softly blurred in the background"

_USAGE_CTX_DEFAULT = "tasteful contextual objects"


def _split_style_tail(structure: list[str]) -> tuple[list[str], list[str]]:
    """구조 본문과 스타일 꼬리를 나눈다.

    맥락 파트(usage_context, 향후 role_context)는 '구조 본문 뒤 · 스타일 앞'에 들어가야
    한다. 스타일은 마감이라 맨 뒤에 와야 하고, 맥락은 씬이 무엇인지에 관한 내용이라
    구조에 붙어야 한다.
    """
    n = len(_STYLE_TAIL)
    if tuple(structure[-n:]) == _STYLE_TAIL:
        return list(structure[:-n]), list(structure[-n:])
    return list(structure), []          # 꼬리가 없는 템플릿(현재 없음) → 본문만


def usage_context_missing(role: str | None, extra: dict | None) -> bool:
    """활용 역할인데 LLM 사용 맥락이 비어 있는가 (공백만 있는 것도 비었다고 본다)."""
    if role not in _USAGE_ROLES:
        return False
    return not str((extra or {}).get("usage_context") or "").strip()


def _tidy(s: str) -> str:
    """슬롯이 비어 생긴 빈 조각·중복 콤마 정리."""
    return ", ".join(p.strip() for p in s.split(",") if p.strip())


def _by_id(tid: str) -> dict:
    return next(t for t in SCENE_TEMPLATES if t["id"] == tid)


def _allowed_ok(t: dict, selections: dict) -> bool:
    """템플릿의 허용값 위반 여부 (깨지는 조합 차단)."""
    for dim_id, allowed_vals in (t.get("allowed") or {}).items():
        v = selections.get(dim_id, STYLE_DIMENSIONS[dim_id]["default"])
        if v not in allowed_vals:
            return False
    return True


def _extra_role_context(extra: dict | None) -> str:
    return str((extra or {}).get("role_context") or "").strip()


def _extra_optional_props(extra: dict | None) -> list[str]:
    return [str(p).strip() for p in ((extra or {}).get("optional_props") or [])
            if str(p).strip()]


def fill(t: dict, selections: dict, extra: dict | None = None, *,
         role: str | None = None) -> str:
    """템플릿 뼈대 + 맥락 파트 + 스타일 슬롯 → 최종 배경 프롬프트.

    조립 순서:
        구조 본문(+ base_props) → usage_context → role_context → optional_props
        → 스타일(mood…season) → 접미

    role: 활용 역할이면 템플릿 종류와 무관하게 usage_context 파트를 **정확히 1회** 넣는다.
          비활용 역할이면 extra에 usage_context가 있어도 넣지 않는다.
          (키워드 전용 인자 — 기존 3개 위치 인자 호출을 깨지 않는다)
    extra: {"usage_context", "role_context", "optional_props"} — LLM 결과.
        role_context는 검증된 BackgroundContext.role_context, optional_props는 예산·검증을
        통과한 소품이다. 각각 있으면 최종 프롬프트에 **정확히 1회** 들어간다.
        **셋 다 비어 있으면 기존 프롬프트와 바이트 단위로 같다** — 스냅샷 불변의 근거.

    prop_density는 base_props만 통제한다 — 맥락·role_context·optional_props는 소품 예산이
    아니라 LLM 계약(generate_slot_contexts)에서 이미 통제됐다.
    """
    kw = image_keyword_map(selections)
    density = selections.get("prop_density", STYLE_DIMENSIONS["prop_density"]["default"])

    body, tail = _split_style_tail(t["structure"])
    context_parts: list[str] = []
    # 제품 배치 영역 문구 — 실제 합성 좌표(compositor)와 같은 left/center/right를 배경에
    # 지시한다. role=None 저수준 호출은 문구를 넣지 않아 기존 프롬프트와 바이트 동일하다.
    if role is not None:
        context_parts.append(placement_for(role).clause)
    if role in _USAGE_ROLES:
        context_parts.append(_USAGE_PART)
    role_context = _extra_role_context(extra)
    if role_context:
        context_parts.append("{role_context}")           # usage_context 뒤
    optional_props = _extra_optional_props(extra)
    if optional_props:
        context_parts.append("{optional_props}")          # role_context 뒤, 스타일 앞

    raw = ", ".join(body + context_parts + tail).format(
        base_props=", ".join(select_base_props(t.get("base_props", []), density)),
        mood=kw.get("mood", ""),
        palette=kw.get("color_palette", ""),
        light=kw.get("brightness", ""),
        props=kw.get("prop_density", ""),
        season=kw.get("season", ""),      # "무관"이면 빈 문자열 → _tidy가 제거
        usage_context=(str((extra or {}).get("usage_context") or "").strip()
                       or _USAGE_CTX_DEFAULT),
        role_context=role_context,
        optional_props=", ".join(optional_props),
    )
    return _tidy(raw) + ", " + _SUFFIX


def _use_counts(used) -> Counter:
    """set(구버전) · Counter · dict · None → 사용 '횟수' 매핑. 입력은 변형하지 않는다.

    점수제에서는 '썼는가'만 알면 됐지만(-5), 이제 균형 있게 돌리려면 '몇 번 썼는가'가
    필요하다. 기존 호출부가 set을 넘기던 것을 깨지 않기 위해 여기서 흡수한다.
    """
    if not used:
        return Counter()
    if isinstance(used, dict):        # Counter도 dict — 횟수를 그대로 읽는다
        return Counter(used)
    return Counter(used)              # set·list → 각 1회로 본다


def _least_used(cands: list[dict], counts: Counter) -> dict:
    """사용 횟수가 가장 적은 템플릿. 동률이면 선언 순서 → 완전 결정론.

    선언 순서상 전용이 범용보다 앞이므로, 첫 선택에서는 전용이 항상 이긴다.
    """
    return min(cands, key=lambda t: (counts.get(t["id"], 0), _ORDER[t["id"]]))


def _compatible(t: dict, archetype, role, cam, selections) -> bool:
    """배경 유형을 뺀 나머지 호환 조건."""
    if cam and t["angle"] != "any" and t["angle"] != cam:
        return False
    if t["archetypes"] and archetype not in t["archetypes"]:
        return False
    if t["roles"] and role not in t["roles"]:
        return False
    return _allowed_ok(t, selections)


def pick_scene(archetype: str | None, role: str | None, angle: str | None,
               selections: dict, used=None, extra: dict | None = None) -> dict:
    """역할·각도·스타일에 맞는 씬 템플릿 선택 → 완성 프롬프트와 배치값 반환.

    2단계 정책 (점수 합산이 아니다):
      1) 하드 필터 — 사용자가 고른 background_type은 **타협하지 않는다**.
         카메라·아키타입·역할·allowed까지 모두 만족하는 후보만 남긴다.
      2) 그 안에서 사용 횟수가 가장 적은 것. 동률이면 선언 순서.

    점수제였을 때는 중복 회피(-5)가 배경 일치(+3)를 이겨서, 2번째 컷부터 사용자가 고른
    배경을 벗어났다. 다양성은 '배경 유형 안에서' 확보할 문제지 배경을 바꿔서 얻을 게 아니다.

    후보가 하나도 없을 때만 explicit fallback으로 내려간다 — 이때는 배경 유형을 못 지켰다는
    뜻이므로 no_scene_for_background 경고를 남긴다.

    used: set(구버전) · Counter · dict 모두 허용. 변형하지 않는다.
    반환: {id, label, prompt, surface_ratio, product_scale, is_generic, constraint_warnings}
    """
    counts = _use_counts(used)
    bg_type = selections.get("background", STYLE_DIMENSIONS["background"]["default"])
    cam = _camera(angle)          # 사진 각도 → 카메라 관점(후면도 straight-on)
    warnings: list[dict] = []

    # ── 1단계: background_type 하드 필터
    cands = [t for t in SCENE_TEMPLATES
             if t["background_type"] == bg_type
             and _compatible(t, archetype, role, cam, selections)]

    if cands:
        best = _least_used(cands, counts)
    else:
        # ── explicit fallback — 배경 유형을 지키지 못한다
        warnings.append({
            "code": "no_scene_for_background",
            "background": bg_type, "archetype": archetype, "role": role,
        })
        if role in _USAGE_ROLES:                       # 활용 컷은 맥락이 배경보다 우선
            best = _by_id("usage_scene")
        else:
            relaxed = [t for t in SCENE_TEMPLATES
                       if _compatible(t, archetype, role, cam, selections)]
            best = _least_used(relaxed, counts) if relaxed else _by_id(_FALLBACK_ID)

    # 범용 착지는 폴백이 아니다 — 배경 유형은 지켰고 씬의 구체성만 얕아진 것.
    if best.get("is_generic"):
        warnings.append({
            "code": "generic_scene_used",
            "scene_id": best["id"], "background": bg_type, "role": role,
        })

    # 활용 컷인데 맥락 조사가 비었다 → 기본값으로 채우되 조용히 넘어가지 않는다.
    if usage_context_missing(role, extra):
        warnings.append({
            "code": "usage_context_unavailable",
            "scene_id": best["id"], "role": role, "fallback": _USAGE_CTX_DEFAULT,
        })

    # planner가 PromptParts를 정확히 재구성할 수 있는 **최소 조각**만 함께 돌려준다.
    # 템플릿 dict(mutable) 자체는 넘기지 않는다 — 외부에서 구조가 바뀌면 안 된다.
    density = selections.get("prop_density", STYLE_DIMENSIONS["prop_density"]["default"])
    placed_usage = ""
    if role in _USAGE_ROLES:
        placed_usage = (str((extra or {}).get("usage_context") or "").strip()
                        or _USAGE_CTX_DEFAULT)

    return {
        "id": best["id"], "label": best["label"],
        "prompt": fill(best, selections, extra, role=role),
        "surface_ratio": best["surface_ratio"],
        "product_scale": best["product_scale"],
        "is_generic": bool(best.get("is_generic")),
        "constraint_warnings": warnings,
        # planner용 최소 조각 (PromptParts·prop_budget 재구성 전용)
        "structure": ", ".join(structure_clauses(best)),
        "base_props": select_base_props(best.get("base_props", []), density),
        "usage_context": placed_usage,
        "prop_budget": prop_budget_for(density),
        # 구도 — fill()의 배치 문구와 같은 정책. build_image_plan이 실행기로 전달한다.
        "composition_anchor": placement_for(role).anchor,
        "anchor_x_ratio": placement_for(role).x_ratio,
    }
