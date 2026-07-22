"""이미지 생성의 데이터 계약 — 실행 전 '의도'(ImagePlan)와 실행 후 '기록'(Trace).

왜 둘을 나누는가:
    지금은 파이프라인이 컷별 프롬프트를 LLM으로 만들고도 씬 프롬프트만 API에 보낸다.
    의도와 실제가 어긋나는데 아무도 모른다. 계획과 기록을 따로 두면 그 불일치가
    'plan.prompt_sha256 != trace.final_prompt_sha256'으로 드러난다.

    단, 불일치가 항상 버그는 아니다 — 폴백(degraded/failed)은 의도적으로 다른 경로를
    타므로 해시가 달라진다. 일치를 요구할 수 있는 건 outcome == "ok"일 때뿐이다.

프롬프트 원문 취급:
    prompt와 PromptParts의 문자열은 **메모리 내 실행 전달용**이다. repr·safe dict·로그
    어디에도 나가지 않는다. 프롬프트는 제품 자산이고 usage_context·role_context에는
    사용자 입력(emphasis 등)에서 파생된 내용이 섞인다.

    prompt_sha256의 용도는 **동일성 확인**뿐이다. 이것은 익명화가 아니다 — 우리 프롬프트는
    씬 템플릿 조합이라 후보 공간이 좁은 저엔트로피 입력이고, 후보를 나열해 해시를 맞춰보는
    사전 대조가 가능하다. 해시를 내보낸다는 건 '원문을 직접 저장하지 않는다'는 뜻이지
    '내용을 알 수 없다'는 뜻이 아니다.

실행 인자는 계획이 아니다:
    mask와 product_image_path는 ImagePlan에 넣지 않는다. 계획은 '무엇을 만들 것인가'이고
    그 둘은 '무엇을 가지고 만드는가'라서 성격이 다르다. 후속 구현의 실행 시그니처는
        generate_image_v2(plan, product_image_path=None, *, mask=None)
    이며, 기존 7인자 generate_image는 LegacyPlanAdapter로 plan을 만들고
    product_image_path·mask는 실행 인자로 따로 넘긴다. (둘 다 3A 범위 밖)
"""
import hashlib
import json
import math
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Literal

from baseline.composition_policy import ANCHORS as _COMPOSITION_ANCHORS

IntendedPath = Literal["composite", "creative_edit", "t2i", "passthrough"]
ActualPath = Literal["composite", "creative_edit", "t2i", "passthrough",
                     "local_bg_composite", "original_passthrough"]
OutputType = Literal["background_context", "full_scene"]
Outcome = Literal["ok", "degraded", "failed"]
TextPlacement = Literal["bottom", "top", "panel"]

_SHA_DISPLAY = 12          # 외부 표시용 길이. 내부 필드는 전체 64자리를 유지한다.


def sha256_of(text: str) -> str:
    """프롬프트의 UTF-8 SHA-256 전체 64자리."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_sha(sha: str | None) -> str | None:
    """외부 표시용 축약. safe dict는 이 값만 내보낸다."""
    return sha[:_SHA_DISPLAY] if sha else sha


def _frozen_seq(values, expected_type, field_name: str) -> tuple:
    """시퀀스를 tuple로 굳히고 **원소 타입까지** 강제한다.

    tuple로만 바꾸는 것은 껍데기다 — 안에 dict나 list가 있으면 그건 계속 바뀐다.
    깊은 불변성이 필요한 이유: prompt_sha256은 생성 시점에 한 번 계산되므로, 그 뒤
    구성 정보가 바뀌면 해시가 가리키는 프롬프트와 실제 조각이 어긋난다.

    폐쇄형 코드 필드에서는 원소 타입 강제가 계약 그 자체다 — dict를 받아주는 순간
    거기에 사용자 입력이 섞여 들어오고 safe dict가 그걸 내보낸다.
    """
    if isinstance(values, (str, bytes)):
        # tuple("abc") == ('a','b','c') — 원소가 전부 str이라 검증을 통과해 버린다.
        # 문자열 하나를 넣은 건 시퀀스를 넣은 게 아니므로 조용히 쪼개지 않고 거부한다.
        raise TypeError(
            f"{field_name}에는 시퀀스를 넣어야 한다 (받은 값: {type(values).__name__}). "
            "문자열 하나를 넣으면 글자 단위로 쪼개진다.")
    out = tuple(values)
    for v in out:
        if type(v) is not expected_type and not isinstance(v, expected_type):
            raise TypeError(
                f"{field_name}의 원소는 {expected_type.__name__}여야 한다 "
                f"(받은 값: {type(v).__name__}). dict·list 등 중첩 컬렉션은 "
                "깊은 불변성을 깨므로 허용하지 않는다.")
        if isinstance(v, (dict, list, set)):
            raise TypeError(
                f"{field_name}의 원소로 {type(v).__name__}은 허용하지 않는다 "
                "— 생성 뒤에도 내용이 바뀐다.")
    return out


def _require_str(value, field_name: str) -> str:
    """문자열 필드가 실제 str인지 강제한다.

    dict·list가 들어오면 그 안은 계속 바뀌고, repr·safe dict가 예상 못 한 모양을 낸다.
    """
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name}는 str이어야 한다 (받은 값: {type(value).__name__}).")
    return value


class WarningCode(str, Enum):
    """계획 단계 경고 — **폐쇄형**. 자유 문자열을 허용하지 않는다.

    자유 문자열을 두면 호출부가 사용자 입력이 섞인 설명을 넣게 되고, 그게 그대로
    safe dict로 나간다. 새 경고가 필요하면 여기에 명시적으로 추가해야 한다 —
    그 추가가 곧 "이 문자열이 밖으로 나가도 되는가"를 검토하는 지점이다.
    """
    NO_SCENE_FOR_BACKGROUND = "no_scene_for_background"
    GENERIC_SCENE_USED = "generic_scene_used"
    USAGE_CONTEXT_UNAVAILABLE = "usage_context_unavailable"
    LLM_SLOT_INVALID = "llm_slot_invalid"
    ROLE_EVIDENCE_MISSING = "role_evidence_missing"


class DroppedRequestCode(str, Enum):
    """배경 생성으로 달성할 수 없어 버린 요구 — **폐쇄형 기계 코드**.

    "포트 클로즈업" 같은 자연어를 담으면 사용자의 emphasis·product_details에서 파생된
    문자열이 밖으로 나간다. 무엇을 못 했는지는 코드로 충분하다.

    'other + 자유 문자열' 우회 필드는 두지 않는다 — 그게 있으면 폐쇄형이 아니다.
    필요한 코드가 생기면 여기에 명시적으로 추가한다.
    """
    CLOSEUP_NOT_SUPPORTED = "closeup_not_supported"
    OCCLUSION_NOT_SUPPORTED = "occlusion_not_supported"
    INTERACTION_NOT_SUPPORTED = "interaction_not_supported"
    TEXT_ZONE_NOT_APPLICABLE = "text_zone_not_applicable"


@dataclass(frozen=True)
class PlanWarning:
    """경고 1건. 코드만 담는다.

    detail·dict·자유 문자열 필드를 두지 않는다. 맥락(어느 씬·어느 역할)은 ImagePlan의
    scene_id·role 같은 검증된 안전 필드로 확인할 수 있으므로, 경고에 또 담을 이유가 없다.
    """
    code: WarningCode

    def __post_init__(self) -> None:
        if not isinstance(self.code, WarningCode):
            raise TypeError(
                f"PlanWarning.code는 WarningCode여야 한다 (받은 값: {type(self.code).__name__}). "
                "자유 문자열 코드는 허용하지 않는다.")


@dataclass(frozen=True)
class PropBudget:
    """프롬프트에 명시할 소품 개수.

    'all'은 보유한 base_props 전체를 뜻한다. 이 값들은 **프롬프트에 적는 소품 수**이지
    생성 이미지에 실제로 나올 소품 수가 아니다 — 모델은 지시하지 않은 소품도 그린다.

    정책 테이블(어떤 prop_density가 몇 개인가)의 단일 원본은 아래 PROP_BUDGET이다.
    composer.scene_templates.select_base_props와 planner가 모두 prop_budget_for()로
    이 표를 읽는다 — 중복 테이블을 두지 않는다.
    """
    base: int | Literal["all"]
    optional: int


# prop_density → 소품 예산. **단일 원본.**
#
# 이 값들은 '프롬프트에 명시하는 소품 수'이지 생성 이미지에 실제로 나올 소품 수가 아니다.
# 모델은 지시하지 않은 소품도 그린다 — 프롬프트에서 뺀다고 화면에서 사라지지 않는다.
#
# base는 씬 템플릿이 자기 정체성으로 갖고 있는 소품(원목 책상의 화분 등),
# optional은 LLM이 제품·역할을 보고 제안한 소품이다. 앞에서부터 자른다.
PROP_BUDGET: dict[int, PropBudget] = {
    1: PropBudget(base=0, optional=0),
    2: PropBudget(base=0, optional=0),
    3: PropBudget(base=1, optional=1),
    4: PropBudget(base="all", optional=2),
    5: PropBudget(base="all", optional=3),
}

# 잘못된 값·범위 밖 값이 오면 이 밀도의 정책을 쓴다.
# (style_presets의 prop_density 기본값과 같아야 한다 — 여기서 import하지 않는 이유는
#  image_plan을 스타일 레지스트리에 의존시키지 않기 위해서다)
_DEFAULT_DENSITY = 2


def prop_budget_for(prop_density) -> PropBudget:
    """밀도 → 예산. 정책의 단일 원본이며 planner와 씬 조립이 같은 표를 본다."""
    try:
        density = int(prop_density)
    except (TypeError, ValueError):
        density = _DEFAULT_DENSITY
    return PROP_BUDGET.get(density, PROP_BUDGET[_DEFAULT_DENSITY])


@dataclass(frozen=True, repr=False)
class PromptParts:
    """최종 프롬프트를 이루는 조각 — 무엇이 어디서 왔는지 추적 가능하게.

    structure  : 씬 골격 (composer.scene_templates의 structure에서 조립)
    usage_context: 활용 역할 공통 맥락 (LLM). 역할이 활용이 아니면 ""
    role_context : 제품·역할별 의미 (LLM). prop_density와 무관하게 항상 쓴다
    base_props   : 씬 고정 소품 중 예산이 허용한 것
    optional_props: LLM이 제안한 소품 중 예산이 허용한 것
    full_scene   : creative_edit·t2i 전용 전체 장면 (LLM tagged-union의 다른 갈래)
    style        : 스타일 축 키워드
    negative     : 경로별 금지 항목
    text_zone    : 오버레이가 실재하는 경로에서만 채운다

    'skeleton'이라는 이름은 쓰지 않는다 — 뼈대 문자열을 저장하던 옛 구조의 잔재이고,
    지금 단일 원본은 절 목록(structure)이다.

    repr에 원문을 싣지 않는다 → 길이·개수만 보여준다.
    """
    structure: str = ""
    usage_context: str = ""
    role_context: str = ""
    base_props: tuple[str, ...] = ()
    optional_props: tuple[str, ...] = ()
    full_scene: str = ""
    style: tuple[str, ...] = ()
    negative: tuple[str, ...] = ()
    text_zone: str = ""
    composition: str = ""      # 고정 구도 문구 (creative_edit·t2i). 원문 아님·폐쇄형 파생
    copy_safe: str = ""        # Hero copy-safe 문구. text_zone(bottom)과 **동시 기록 금지**

    def __post_init__(self) -> None:
        # 문자열 필드가 실제 str인가
        for name in ("structure", "usage_context", "role_context", "full_scene",
                     "text_zone", "composition", "copy_safe"):
            _require_str(getattr(self, name), f"PromptParts.{name}")
        # 컬렉션은 tuple[str, ...]로 굳힌다. tuple로 바꾸기만 하면 껍데기뿐이라
        # 원소 타입까지 강제해야 안의 dict·list가 나중에 바뀌는 일이 없다.
        for name in ("base_props", "optional_props", "style", "negative"):
            object.__setattr__(self, name,
                               _frozen_seq(getattr(self, name), str,
                                           f"PromptParts.{name}"))

    def __repr__(self) -> str:                       # 원문 비노출
        return (f"PromptParts(structure={len(self.structure)}c, "
                f"usage_context={len(self.usage_context)}c, "
                f"role_context={len(self.role_context)}c, "
                f"base_props={len(self.base_props)}, "
                f"optional_props={len(self.optional_props)}, "
                f"full_scene={len(self.full_scene)}c, "
                f"style={len(self.style)}, negative={len(self.negative)}, "
                f"text_zone={len(self.text_zone)}c, "
                f"composition={len(self.composition)}c, "
                f"copy_safe={len(self.copy_safe)}c)")


@dataclass(frozen=True)
class ImagePlan:
    """실행 전 의도. 순수 결정론 — API 호출 없이 전량 생성할 수 있어야 한다.

    prompt_sha256·prompt_len은 **생성자가 받지 않는다.** 외부에서 넣게 두면 프롬프트와
    해시가 어긋난 계획이 만들어져, 정합 검사가 무의미해진다. prompt에서만 파생한다.
    """
    role: str
    intended_path: IntendedPath
    prompt: str = field(repr=False)                  # 실행 전달용 — repr 비노출
    prompt_parts: PromptParts = field(repr=False)

    output_type: OutputType | None = None
    scene_id: str | None = None
    scene_is_generic: bool = False
    size: str = ""
    width_ratio: float = 0.0
    base_ratio: float = 0.0
    max_h_ratio: float = 0.0
    harmonize: float | None = None                   # None = 자동
    shadow: float | None = None                      # None = 자동
    angle_wanted: str | None = None
    angle_used: str | None = None
    source: str | None = None                        # product | usage
    # 좌우 구도 — composition_policy 단일 원본에서 온다. 기본은 기존 동작과 같은 중앙.
    composition_anchor: str = "center"               # left | center | right
    anchor_x_ratio: float = 0.5                      # 제품 중심의 정규화 x (0~1)
    prop_budget: PropBudget = field(default_factory=lambda: PropBudget(0, 0))
    # 폐쇄형 코드만 — 자유 문자열·dict를 담으면 사용자 입력에서 파생된 내용이 새어 나간다
    constraint_warnings: tuple[PlanWarning, ...] = ()
    dropped_requests: tuple[DroppedRequestCode, ...] = ()

    # 파생 — init=False라 위조할 수 없다
    prompt_sha256: str = field(init=False, repr=False, default="")
    prompt_len: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_sha256", sha256_of(self.prompt))
        object.__setattr__(self, "prompt_len", len(self.prompt))
        # 구도 값 검증 — 폐쇄형 anchor·유한한 0~1 x비율만 허용한다. 잘못된 값이 계획에 실려
        # 실행기·배경 프롬프트로 흘러가면 배경과 합성 위치가 어긋난다.
        if self.composition_anchor not in _COMPOSITION_ANCHORS:
            raise ValueError(
                f"composition_anchor는 {_COMPOSITION_ANCHORS} 중 하나여야 한다 "
                f"(받은 값: {self.composition_anchor!r}).")
        x = self.anchor_x_ratio
        if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
            raise ValueError(f"anchor_x_ratio는 유한한 숫자여야 한다 (받은 값: {x!r}).")
        if not (0.0 <= x <= 1.0):
            raise ValueError(f"anchor_x_ratio는 0.0~1.0 이어야 한다 (받은 값: {x!r}).")
        # 깊은 불변성 — frozen은 최상위 재할당만 막는다. 안에 dict·list가 있으면
        # 계획이 만들어진 뒤에도 바뀔 수 있고, 그러면 해시와 내용이 어긋난다.
        object.__setattr__(self, "constraint_warnings",
                           _frozen_seq(self.constraint_warnings, PlanWarning,
                                       "constraint_warnings"))
        object.__setattr__(self, "dropped_requests",
                           _frozen_seq(self.dropped_requests, DroppedRequestCode,
                                       "dropped_requests"))

    def to_safe_dict(self) -> dict[str, Any]:
        """외부로 나가도 되는 표현. **사용자 입력에서 파생된 문자열은 어떤 형태로도 없다.**

        prompt_parts를 통째로 뺀다 — usage_context·role_context·optional_props·
        full_scene이 전부 그 안에 있다. 해시는 표시용 12자리만 내보낸다.
        경고·버린 요구는 폐쇄형 **코드값만** 내보낸다.
        """
        return {
            "role": self.role,
            "intended_path": self.intended_path,
            "output_type": self.output_type,
            "scene_id": self.scene_id,
            "scene_is_generic": self.scene_is_generic,
            "prompt_sha256": short_sha(self.prompt_sha256),
            "prompt_len": self.prompt_len,
            "size": self.size,
            "width_ratio": self.width_ratio,
            "base_ratio": self.base_ratio,
            "max_h_ratio": self.max_h_ratio,
            "harmonize": self.harmonize,
            "shadow": self.shadow,
            "angle_wanted": self.angle_wanted,
            "angle_used": self.angle_used,
            "source": self.source,
            "composition_anchor": self.composition_anchor,   # 폐쇄형 코드
            "anchor_x_ratio": self.anchor_x_ratio,           # 숫자
            "prop_budget": {"base": self.prop_budget.base,
                            "optional": self.prop_budget.optional},
            "constraint_warnings": [w.code.value for w in self.constraint_warnings],
            "dropped_requests": [d.value for d in self.dropped_requests],
        }


@dataclass(frozen=True, repr=False)
class BackgroundContext:
    """composite 슬롯의 검증된 LLM 결과 — 골격에 얹을 배경 의미.

    role_context는 제품·역할별 의미(prop_density 무관 항상 사용), optional_props는
    LLM이 제안한 소품 중 예산·검증을 통과한 것. 원문은 repr에 싣지 않는다.
    """
    role: str
    role_context: str = ""
    optional_props: tuple[str, ...] = ()
    warnings: tuple[PlanWarning, ...] = ()
    output_type: str = "background_context"

    def __post_init__(self) -> None:
        _require_str(self.role_context, "BackgroundContext.role_context")
        object.__setattr__(self, "optional_props",
                           _frozen_seq(self.optional_props, str,
                                       "BackgroundContext.optional_props"))
        object.__setattr__(self, "warnings",
                           _frozen_seq(self.warnings, PlanWarning,
                                       "BackgroundContext.warnings"))

    def __repr__(self) -> str:                       # 원문 비노출
        return (f"BackgroundContext(role={self.role!r}, "
                f"role_context={len(self.role_context)}c, "
                f"optional_props={len(self.optional_props)}, "
                f"warnings={[w.code.value for w in self.warnings]})")

    def to_safe_dict(self) -> dict[str, Any]:
        return {"role": self.role, "output_type": self.output_type,
                "role_context_len": len(self.role_context),
                "optional_props_count": len(self.optional_props),
                "warnings": [w.code.value for w in self.warnings]}


@dataclass(frozen=True, repr=False)
class FullSceneContext:
    """creative_edit·t2i 슬롯의 검증된 LLM 결과 — 전체 장면 묘사.

    composite와 출력 형태가 다르다: 배경 조각이 아니라 완결된 한 장면이다. 원문 비노출.
    """
    role: str
    full_scene: str = ""
    warnings: tuple[PlanWarning, ...] = ()
    output_type: str = "full_scene"

    def __post_init__(self) -> None:
        _require_str(self.full_scene, "FullSceneContext.full_scene")
        object.__setattr__(self, "warnings",
                           _frozen_seq(self.warnings, PlanWarning,
                                       "FullSceneContext.warnings"))

    def __repr__(self) -> str:                       # 원문 비노출
        return (f"FullSceneContext(role={self.role!r}, "
                f"full_scene={len(self.full_scene)}c, "
                f"warnings={[w.code.value for w in self.warnings]})")

    def to_safe_dict(self) -> dict[str, Any]:
        return {"role": self.role, "output_type": self.output_type,
                "full_scene_len": len(self.full_scene),
                "warnings": [w.code.value for w in self.warnings]}


SlotContext = BackgroundContext | FullSceneContext


@dataclass(frozen=True)
class ImageApiAttempt:
    """이미지 API 시도 1건. 성공·실패 모두 남긴다 — 실패한 시도도 비용이다."""
    api: str                       # images.generate | images.edit
    model: str
    size: str
    prompt_sha256: str
    prompt_len: int
    milliseconds: int

    def to_safe_dict(self) -> dict[str, Any]:
        return {"api": self.api, "model": self.model, "size": self.size,
                "prompt_sha256": short_sha(self.prompt_sha256),
                "prompt_len": self.prompt_len, "milliseconds": self.milliseconds}


@dataclass(frozen=True)
class GeometryTrace:
    """컴포지팅이 실제로 놓은 결과. 텍스트 배치가 이 값을 보고 제품을 피한다."""
    product_bbox: tuple[int, int, int, int]
    shadow_bbox: tuple[int, int, int, int]
    surface_y: int
    applied_scale: float
    height_capped: bool            # 높이 제한이 width_ratio를 눌렀는가

    def to_safe_dict(self) -> dict[str, Any]:
        return {"product_bbox": list(self.product_bbox),
                "shadow_bbox": list(self.shadow_bbox),
                "surface_y": self.surface_y,
                "applied_scale": self.applied_scale,
                "height_capped": self.height_capped}


@dataclass(frozen=True)
class TraceError:
    """어디서 어떤 종류의 실패가 났는가.

    예외 메시지를 저장하지 않는다 — parse 실패나 API 오류 메시지에는 프롬프트·응답
    본문이 그대로 실려 오는 경우가 있다. 진단에 필요한 건 '어느 단계에서 무슨 유형'까지다.
    """
    stage: str
    error_type: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "error_type": self.error_type}


@dataclass(frozen=True)
class GenerationTrace:
    """역할 1건의 실행 기록.

    final_prompt 필드는 두지 않는다 — 원문을 남길 자리를 아예 만들지 않는 것이
    "실수로 로깅되지 않게" 하는 가장 확실한 방법이다. 해시로 동일성만 확인한다.

    LLM 회계(logical_chat_calls·actual_api_attempts)는 여기 없다. 배치 호출·카피·GEO는
    역할에 귀속되지 않으므로 페이지 단위(PipelineTrace)에서 센다.
    """
    role: str
    actual_path: ActualPath
    outcome: Outcome
    scene_id: str | None = None
    scene_is_generic: bool = False
    fallback_chain: tuple[str, ...] = ()
    image_api_calls: tuple[ImageApiAttempt, ...] = ()
    geometry: GeometryTrace | None = None
    text_placement: TextPlacement | None = None
    errors: tuple[TraceError, ...] = ()
    final_prompt_sha256: str | None = None
    prompt_len: int = 0

    def matches_plan(self, plan: ImagePlan) -> bool:
        """계획한 프롬프트가 실제로 나갔는가.

        outcome == "ok"에서만 True를 요구할 수 있다. degraded·failed는 폴백이 다른
        프롬프트(또는 프롬프트 없음)로 갔다는 뜻이라 불일치가 **의도된 동작**이다.
        """
        return self.final_prompt_sha256 == plan.prompt_sha256

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "scene_id": self.scene_id,
            "scene_is_generic": self.scene_is_generic,
            "actual_path": self.actual_path,
            "fallback_chain": list(self.fallback_chain),
            "image_api_calls": [a.to_safe_dict() for a in self.image_api_calls],
            "geometry": self.geometry.to_safe_dict() if self.geometry else None,
            "text_placement": self.text_placement,
            "errors": [e.to_safe_dict() for e in self.errors],
            "outcome": self.outcome,
            "final_prompt_sha256": short_sha(self.final_prompt_sha256),
            "prompt_len": self.prompt_len,
        }


@dataclass(frozen=True)
class PipelineTrace:
    """페이지 1건의 실행 기록.

    LLM 회계가 여기 있는 이유: chat_json은 내부에서 최대 retries+1회 재시도하고
    generate_page_copy는 그걸 또 2회까지 부른다. "LLM 1회"가 실제 비용과 맞지 않으므로
    논리 호출과 실제 시도를 따로 센다. 둘 다 역할이 아니라 페이지에 귀속된다.
    """
    logical_chat_calls: int = 0
    actual_api_attempts: int = 0
    image_api_attempts: int = 0
    seconds: float = 0.0
    outcome: Outcome = "ok"
    image_warnings: tuple[str, ...] = ()        # 사용자에게 보여줄 문구 (프롬프트 아님)
    generations: tuple[GenerationTrace, ...] = ()

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "logical_chat_calls": self.logical_chat_calls,
            "actual_api_attempts": self.actual_api_attempts,
            "image_api_attempts": self.image_api_attempts,
            "seconds": self.seconds,
            "outcome": self.outcome,
            "image_warnings": list(self.image_warnings),
            "generations": [g.to_safe_dict() for g in self.generations],
        }


def safe_json(obj: Any) -> str:
    """safe dict를 JSON으로. 로그·응답에 쓸 때 원문이 섞이지 않았는지 확인하기 쉽게."""
    return json.dumps(obj.to_safe_dict(), ensure_ascii=False, sort_keys=True)


def field_names(cls) -> set[str]:
    """계약 검증용 — 어떤 필드가 있고 없는지 테스트가 확인한다."""
    return {f.name for f in fields(cls)}
