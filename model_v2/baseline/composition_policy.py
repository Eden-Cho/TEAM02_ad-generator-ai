"""역할별 좌우 구도 정책 — **순수·폐쇄형**. 다른 모듈을 import하지 않는다(순환 방지).

왜 별도 모듈인가:
    제품의 좌우 위치를 배경 생성(scene_templates)·실제 합성(compositor)·LLM 구도 지시
    (prompt_generator)가 **같은 값으로** 써야 배경 소품과 제품이 겹치지 않는다. 세 곳이
    각자 정하면 배경은 오른쪽을 비우라 하고 합성은 왼쪽에 놓는 식으로 어긋난다.
    → 단일 원본을 여기 하나로 둔다.

이 모듈은 '제품을 어느 쪽 자리에 놓을지'만 정한다. 새로운 제품 각도를 만들지 않는다.
문구는 사용자 입력을 받지 않는 내부 고정 문자열이다.
"""
import math
from dataclasses import dataclass
from typing import Literal

CompositionAnchor = Literal["left", "center", "right"]
CopyAnchor = Literal["top_left", "top_right", "top_center"]

# 런타임 검증용 폐쇄형 값 (image_plan이 이 단일 원본을 import한다)
ANCHORS: tuple[str, ...] = ("left", "center", "right")
COPY_ANCHORS: tuple[str, ...] = ("top_left", "top_right", "top_center")

# 배경 생성 문구 — **제품을 배경에 미리 그리라고 지시하지 않는다.** 제품이 놓일 표면
# 영역을 비우고, 시각적 무게·소품은 반대쪽에 두라고만 한다. (composite 배경 전용)
_ANCHOR_CLAUSE: dict[str, str] = {
    "left": ("keep the left area of the surface open and empty as the spot for the product "
             "to be placed later, put the visual weight and any decorative props on the "
             "right side"),
    "right": ("keep the right area of the surface open and empty as the spot for the product "
              "to be placed later, put the visual weight and any decorative props on the "
              "left side"),
    "center": ("keep the center of the surface open and empty as the spot for the product "
               "to be placed later"),
}

# 이미지 구도 문구 — **제품까지 포함해 생성·편집**하는 creative_edit·t2i 전용.
# 배경 문구(_ANCHOR_CLAUSE)와 달리 제품 자체를 프레임 어디에 둘지 지시한다.
_IMAGE_ANCHOR_CLAUSE: dict[str, str] = {
    "left": ("place the product in the left third of the frame with balanced visual "
             "breathing room on the right"),
    "right": ("place the product in the right third of the frame with balanced visual "
              "breathing room on the left"),
    "center": "place the product centered in the frame",
}


@dataclass(frozen=True)
class CompositionPlacement:
    """제품 배치 의도 1건. anchor + 정규화 x비율 + 파생 문구.

    **런타임에서 닫혀 있다** — Literal은 정적 힌트일 뿐이므로 생성 시 직접 강제한다.
    잘못된 값이 만들어져 .clause 접근 때 뒤늦게 KeyError가 나는 경로를 없앤다.
    """
    anchor: CompositionAnchor
    x_ratio: float

    def __post_init__(self) -> None:
        if self.anchor not in ANCHORS:
            raise ValueError(
                f"anchor는 {ANCHORS} 중 하나여야 한다 (받은 값: {self.anchor!r}).")
        x = self.x_ratio
        if not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x):
            raise ValueError(f"x_ratio는 유한한 숫자여야 한다 (받은 값: {x!r}).")
        if not (0.0 <= x <= 1.0):
            raise ValueError(f"x_ratio는 0.0~1.0 이어야 한다 (받은 값: {x!r}).")

    @property
    def clause(self) -> str:
        """composite 배경 생성용 고정 문구. 폐쇄형 맵에서 파생 — 자유 문자열 없음."""
        return _ANCHOR_CLAUSE[self.anchor]

    @property
    def image_clause(self) -> str:
        """creative_edit·t2i 최종 프롬프트용 고정 구도 문구. 폐쇄형 맵에서 파생."""
        return _IMAGE_ANCHOR_CLAUSE[self.anchor]


# 역할 → (anchor, x_ratio). **단일 원본.** left=0.38 / right=0.62 / center=0.50.
_ROLE_POLICY: dict[str, tuple[str, float]] = {
    "hero":         ("left", 0.38),
    "build":        ("right", 0.62),
    "connectivity": ("left", 0.38),
    "detail":       ("right", 0.62),
    "material":     ("right", 0.62),
    "fabric":       ("right", 0.62),
    "ingredient":   ("right", 0.62),
    "texture":      ("right", 0.62),
    "lifestyle":    ("left", 0.38),
    "styling":      ("left", 0.38),
    "space":        ("left", 0.38),
    "serving":      ("left", 0.38),
}
_DEFAULT_POLICY: tuple[str, float] = ("center", 0.50)


def placement_for(role) -> CompositionPlacement:
    """역할 → 배치 정책. **순수 함수.** 알 수 없는 역할·None은 center/0.5.

    입력·전역 상태를 바꾸지 않으며 같은 입력은 항상 같은 결과를 준다.
    """
    anchor, x_ratio = _ROLE_POLICY.get(role, _DEFAULT_POLICY)
    return CompositionPlacement(anchor=anchor, x_ratio=x_ratio)


def image_clause_for(anchor) -> str:
    """anchor 코드 → creative_edit·t2i 최종 프롬프트용 고정 구도 문구.

    폐쇄형 맵에서 결정론적으로 파생한다. 알 수 없는 anchor는 center 문구로 안전 폴백.
    """
    return _IMAGE_ANCHOR_CLAUSE.get(anchor, _IMAGE_ANCHOR_CLAUSE["center"])


# ── Hero 카피 배치 정책 (step3F) ─────────────────────────────────────────────
# 제품 구도(left/right/center)에서 카피 위치를 **같은 단일 원본**으로 파생한다.
# 제품 반대편 상단을 카피 자리로 쓴다: left→top_right, right→top_left, center→top_center.
_PRODUCT_TO_COPY: dict[str, str] = {
    "left": "top_right",
    "right": "top_left",
    "center": "top_center",
}

# 카피 anchor → 안전영역 정규화 비율 (x0, x1, y0, y1). left/right는 0.5 기준 좌우 대칭.
_COPY_SAFE_ZONE: dict[str, tuple[float, float, float, float]] = {
    "top_left":   (0.08, 0.45, 0.08, 0.38),
    "top_right":  (0.55, 0.92, 0.08, 0.38),
    "top_center": (0.18, 0.82, 0.08, 0.36),
}

# copy-safe **이미지** 문구 — 제품 anchor 기준. 카피가 놓일 상단 반대편을 negative space로
# 비우고 보조 소품은 하단 반대편으로 제한한다(소품 전면 금지가 아니라 위치 제한).
# Hero 최종 이미지 프롬프트에서 legacy bottom text-zone 문구를 **대체**한다(공존 금지).
_COPY_SAFE_CLAUSE: dict[str, str] = {
    "left": ("keep the upper-right area as clean empty negative space reserved for headline "
             "and subcopy text, with no flowers, branches, books, letters, strong reflections "
             "or high-contrast decoration there, and limit any secondary props to the "
             "lower-right"),
    "right": ("keep the upper-left area as clean empty negative space reserved for headline "
              "and subcopy text, with no flowers, branches, books, letters, strong reflections "
              "or high-contrast decoration there, and limit any secondary props to the "
              "lower-left"),
    "center": ("keep the upper-center area as clean empty negative space reserved for headline "
               "and subcopy text, with no letters, strong reflections or high-contrast "
               "decoration there"),
}


@dataclass(frozen=True)
class CopyPlacement:
    """Hero 카피 배치 1건. copy_anchor + 안전영역 정규화 비율. **런타임에서 닫혀 있다.**"""
    copy_anchor: CopyAnchor
    x0: float
    x1: float
    y0: float
    y1: float

    def __post_init__(self) -> None:
        if self.copy_anchor not in COPY_ANCHORS:
            raise ValueError(
                f"copy_anchor는 {COPY_ANCHORS} 중 하나여야 한다 (받은 값: {self.copy_anchor!r}).")
        for name in ("x0", "x1", "y0", "y1"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise ValueError(f"CopyPlacement.{name}은 유한한 숫자여야 한다 (받은 값: {v!r}).")
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"CopyPlacement.{name}은 0.0~1.0 이어야 한다 (받은 값: {v!r}).")
        if not (self.x0 < self.x1 and self.y0 < self.y1):
            raise ValueError("CopyPlacement 안전영역은 x0<x1, y0<y1 이어야 한다.")


def copy_placement_for(product_anchor) -> CopyPlacement:
    """제품 anchor(left/center/right) → Hero 카피 배치. 잘못된 anchor는 **즉시 ValueError**.

    알 수 없는 role은 placement_for가 center를 주므로 여기선 center→top_center로 이어진다.
    """
    if product_anchor not in ANCHORS:
        raise ValueError(
            f"product_anchor는 {ANCHORS} 중 하나여야 한다 (받은 값: {product_anchor!r}).")
    ca = _PRODUCT_TO_COPY[product_anchor]
    return CopyPlacement(ca, *_COPY_SAFE_ZONE[ca])


def copy_placement_of(copy_anchor) -> CopyPlacement:
    """카피 anchor 코드 → 안전영역 (렌더러용). 잘못된 anchor는 **즉시 ValueError**(조용한 폴백 금지)."""
    if copy_anchor not in COPY_ANCHORS:
        raise ValueError(
            f"copy_anchor는 {COPY_ANCHORS} 중 하나여야 한다 (받은 값: {copy_anchor!r}).")
    return CopyPlacement(copy_anchor, *_COPY_SAFE_ZONE[copy_anchor])


def copy_safe_clause_for(product_anchor) -> str:
    """제품 anchor → Hero copy-safe 이미지 문구. 잘못된 anchor는 즉시 ValueError."""
    if product_anchor not in ANCHORS:
        raise ValueError(
            f"product_anchor는 {ANCHORS} 중 하나여야 한다 (받은 값: {product_anchor!r}).")
    return _COPY_SAFE_CLAUSE[product_anchor]
