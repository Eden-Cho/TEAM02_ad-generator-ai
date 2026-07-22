"""요청(dict) + 장수 -> 이미지 생성 스펙 N개.

역할/mode/text_zone은 section_templates에서 고정되고,
GPT는 각 슬롯의 장면 프롬프트(scene)만 채운다.
text_zone(여백)·no-text 지시는 코드에서 결정론적으로 덧붙여 보장한다.

출력 계약(image_spec):
    {"role", "mode", "prompt", "text_zone"}
"""
import baseline.config as config
from baseline.llm import chat_json
from baseline.section_templates import clamp_count, resolve_slots
from baseline.style_presets import build_style_context


# text_zone(여백)을 실제로 비우도록 강제하는 결정론적 지시
TEXT_ZONE_CLAUSE = {
    "top": ("keep the entire top portion as clean empty negative space "
            "reserved for a text overlay, no objects or focal elements at the top"),
    "bottom": ("keep the entire bottom portion as clean empty negative space "
               "reserved for a text overlay, no objects or focal elements at the bottom"),
    "none": "",
}
# 모델이 이미지 안에 글자를 그리지 않도록 (텍스트는 PIL이 담당)
NO_TEXT_CLAUSE = "no text, no letters, no words, no watermark, no logo"
QUALITY_SUFFIX = "professional product photography, high detail, sharp focus, 8k"

SYSTEM_PROMPT = (
    "You are a professional product photography prompt engineer for a Korean "
    "e-commerce detail page image generator. You are given a FIXED list of image "
    "slots and must write ONE English scene prompt per slot. "
    "Output ONLY valid JSON. No markdown, no explanation."
)

USER_TEMPLATE = """[Product]
product_name: {product_name}
color: {color}
category: {category}
emphasis(강조 요청): {emphasis}
product_details(스펙/특징): {product_details}

[Style keywords — from user selections]
{style_keywords}

You must write scene prompts for these {n} FIXED slots (keep the order):
{slots_desc}

Rules for each "prompt":
1. English only.
2. Weave the style keywords into every prompt for a consistent look.
3. Follow the slot's brief.
4. For mode=edit slots: describe ONLY the background / scene / lighting.
   Do NOT describe the product itself (it is preserved from the uploaded photo).
5. For mode=t2i slots: describe the full lifestyle scene freely.
6. Do NOT add role/mode/text_zone — only the scene description.
7. Keep each prompt concise — under 40 words.

Output JSON (a list of prompt strings, same order as slots):
{{"prompts": ["slot 1 scene prompt", "slot 2 scene prompt"]}}
"""


def _assemble(scene: str, text_zone: str) -> str:
    """GPT 장면 프롬프트 + text_zone 여백 지시 + no-text + 품질 접미."""
    parts = [scene.strip().rstrip(".")]
    zone = TEXT_ZONE_CLAUSE.get(text_zone, "")
    if zone:
        parts.append(zone)
    parts.append(NO_TEXT_CLAUSE)
    parts.append(QUALITY_SUFFIX)
    return ", ".join(p for p in parts if p)


def generate(req: dict, image_keywords: list[str] | None = None,
             slots: list[dict] | None = None) -> list[dict]:
    n = clamp_count(req.get("num_images", 3))
    if slots is None:
        slots = resolve_slots(n, None)  # 사진 미지정 시 전부 t2i
    if image_keywords is None:
        image_keywords = build_style_context(req)["image_keywords"]

    slots_desc = "\n".join(
        f'{i + 1}. role={s["role"]}, mode={s["mode"]}, '
        f'text_zone={s["text_zone"]}, brief="{s["brief"]}"'
        for i, s in enumerate(slots)
    )
    user = USER_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        color=req.get("color", ""),
        category=req.get("category", ""),
        emphasis=req.get("emphasis", ""),
        product_details=req.get("product_details", ""),
        style_keywords=", ".join(image_keywords),
        n=len(slots),
        slots_desc=slots_desc,
    )
    scene_prompts = chat_json(SYSTEM_PROMPT, user).get("prompts", [])

    # 골격은 템플릿에서, 프롬프트만 GPT 결과로 조립 (여백 지시는 코드가 보장)
    specs: list[dict] = []
    for i, slot in enumerate(slots):
        scene = scene_prompts[i] if i < len(scene_prompts) else slot["brief"]
        specs.append({
            "role": slot["role"],
            "mode": slot["mode"],
            "text_zone": slot["text_zone"],
            "image_path": slot.get("image_path"),
            "source": slot.get("source"),      # usage=직접 사용 / product=합성
            "angle": slot.get("angle"),        # 씬 템플릿 각도 매칭용
            "prompt": _assemble(scene, slot["text_zone"]),
        })
    return specs


# ---------- 사용 맥락(활용 이미지용) ----------
_USAGE_CTX_SYSTEM = (
    "You design the BACKGROUND of a scene that shows a product in use, "
    "for an image the real product will be composited into. "
    "First reason about how the product is actually used, then describe that scene. "
    "Output ONLY valid JSON. No markdown, no explanation."
)

# 카테고리별 규칙을 열거하지 않는다 — LLM이 '사용 행위'를 먼저 추론하게 해서
# 그 제품에 맞는 '사용의 흔적'을 스스로 도출하도록 한다(확장성).
#
# 손·사람 금지(규칙 3)는 취향이 아니라 컴포지팅의 구조적 제약이다: 제품이 항상 최상위
# 레이어라 가림(occlusion)이 불가능해, 배경의 손은 제품 뒤에서 허공을 쥔다
# (experiments/20260715/sun2_usage.png). 리파인 재투입으로 가림을 만드는 안은 제품을
# 재렌더해 폐기됨(맥미니 3회, 유지율 83.7%, 각도까지 변형 — experiments/20260716/refine).
# composer/scene_templates.py의 _SUFFIX와 반드시 함께 유지할 것 — 한쪽만 바꾸면 서로 싸운다.
_USAGE_CTX_TEMPLATE = """[Product]
name: {name}
category: {category}
details: {details}
emphasis(seller's focus): {emphasis}

Step 1 — Think: how is this product actually used? (the action, where, when)
Step 2 — Describe the SCENE at that moment of use, as a background only.

The scene must contain BOTH:
  a) the surroundings where it is used, and
  b) visible EVIDENCE that it is being used — whatever naturally fits THIS product
     (e.g. the substance dispensed nearby, the finished result, the setup it connects to).

Rules:
1. English, ONE phrase, under 25 words.
2. Do NOT describe the product itself — the real product is composited in afterwards.
3. NO hands, NO people, NO body parts anywhere in the scene. Show use only through
   traces left behind (the substance dispensed on a surface, the finished result,
   the connected setup, tools set down mid-task).
4. Keep the center empty for the product.
5. If the emphasis suggests a place or situation, reflect it.

Output JSON:
{{"how_used": "<one line: how/where it is used>",
  "usage_context": "<the scene phrase>"}}
"""


def generate_usage_context(req: dict) -> tuple[str, str]:
    """제품이 '실제 쓰이는 순간'의 배경 장면 (활용 컷용).

    LLM이 사용 행위를 먼저 추론(how_used)하게 해서, 그 제품에 맞는
    '사용의 흔적'이 담긴 장면을 도출한다. how_used는 로그·확인용.

    반환: (usage_context, how_used) — 실패 시 ("", "")
    """
    try:
        data = chat_json(_USAGE_CTX_SYSTEM, _USAGE_CTX_TEMPLATE.format(
            name=req.get("product_name", ""),
            category=req.get("category", ""),
            details=req.get("product_details", ""),
            emphasis=req.get("emphasis", ""),
        ))
        return (str(data.get("usage_context", "")).strip(),
                str(data.get("how_used", "")).strip())
    except Exception:
        return "", ""


# ---------- 슬롯 컨텍스트 (tagged-union 배치) ----------
#
# 왜 generate()를 대체하지 않고 새로 만드는가:
#   generate()는 {"prompts": [...]} 위치 기반이라 role이 없다. 누락·중복·순서 오류를
#   식별할 수 없고, composite와 creative_edit/t2i가 요구하는 출력 형태가 다른데 같은
#   문자열 계약을 쓴다. 그래서 composite용 LLM 결과가 실행에서 버려진다.
#   → 슬롯마다 output_type을 붙여 role로 매칭하고, 검증·폴백을 슬롯 단위로 한다.
#   generate()는 CLI·copy_generator가 아직 쓰므로 그대로 둔다.

from baseline.image_plan import (BackgroundContext, FullSceneContext,  # noqa: E402
                                 PlanWarning, WarningCode, prop_budget_for)

_SLOT_CTX_SYSTEM = (
    "You write background/scene context for e-commerce product images. Each slot has an "
    "intended_path that decides WHAT to write and its output_type:\n"
    "- composite (background_context): the REAL product photo is composited in afterwards. "
    "Give role_context (the setting/surface/material affinity/lighting framing for this "
    "role) and optional_props (a few peripheral background objects). NEVER describe the "
    "product itself — it is preserved from the uploaded photo.\n"
    "- creative_edit (full_scene): the real product is edited into a new scene. Describe the "
    "full scene and composition only. Do NOT invent a new product identity, colors or "
    "features — the product comes from the input image.\n"
    "- t2i (full_scene): there is NO input product image. You MUST include the product "
    "itself as the clear subject of the scene, grounded ONLY in the given product_name, "
    "category and product_details.\n"
    "When a creative_edit slot has presentation_mode=natural: place the input product as a "
    "real object in the scene; match the background lighting and the product lighting; connect "
    "the surface contact shadow and ambient light naturally; use perspective matching the "
    "product photo's camera angle (source_angle); keep the exact number and placement of "
    "ports, the logo and the proportions visible in the photo; do NOT add features, text, "
    "buttons or ports the product does not have; do NOT create a different or duplicated "
    "product; keep the given source_angle (do not invent a new product angle).\n"
    "Every slot must reflect the requested_background.\n"
    "Composition (composition_anchor): if 'left', place the product in the left third of the "
    "scene and leave visual breathing room on the right; if 'right', do the opposite; if "
    "'center', place it centered. Keep the given source_angle and do NOT invent any other "
    "product angle that was not uploaded.\n"
    "All paths: never invent features, brands, logos or text that are not given. "
    "NO hands, people or body parts anywhere.\n"
    "Limits: role_context 12 words max (space/surface/material/lighting only, no countable "
    "props); each optional_prop 8 words max, placed at the periphery (e.g. 'at the edge', "
    "'in the background', 'off-center'), no text/screens/logos/hands/people; full_scene "
    "40 words max.\n"
    "Match every requested role and output_type exactly. Output ONLY valid JSON, no markdown."
)

_SLOT_CTX_TEMPLATE = """[Product]
product_name: {product_name}
category: {category}
emphasis: {emphasis}
product_details: {product_details}
requested_background: {requested_background}

[Style keywords]
{style_keywords}

Write context for these {n} slots (match role and output_type exactly):
{slots_desc}

Output JSON:
{{"slots": [
  {{"role": "...", "output_type": "background_context", "role_context": "...", "optional_props": ["..."]}},
  {{"role": "...", "output_type": "full_scene", "full_scene": "..."}}
]}}
"""

_VALID_OUTPUT_TYPES = ("background_context", "full_scene")

# 경로 → 출력형태. passthrough는 LLM에 넣지 않으므로 여기 없다 — 오면 ValueError.
# t2i와 creative_edit은 같은 full_scene을 쓰지만 시스템 프롬프트가 경로별로 규칙을 가른다:
# t2i는 제품을 장면에 반드시 포함(입력 이미지 없음), creative_edit은 제품 정체성 발명 금지.
_ALLOWED_PATH_OUTPUT = {
    ("composite", "background_context"),
    ("creative_edit", "full_scene"),
    ("t2i", "full_scene"),
}

# 코드가 판별할 수 있는 것만 검증한다 — 의미 판단은 시스템 프롬프트에 맡긴다.
_ROLE_CONTEXT_MAX_WORDS = 12
_OPTIONAL_PROP_MAX_WORDS = 8
_FULL_SCENE_MAX_WORDS = 40

_PERIPHERY_PHRASES = (
    "at the edge", "along the edge", "near the side", "at the side",
    "in the background", "off-center", "near the frame edge",
)
_PROP_BANNED = (
    "text", "letters", "words", "screen", "display", "monitor showing",
    "code", "label", "logo", "hand", "hands", "person", "people", "finger", "body",
)


def _words(s: str) -> int:
    return len(s.split())


def _invalid_slot_warning() -> tuple:
    return (PlanWarning(WarningCode.LLM_SLOT_INVALID),)


def _clean_role_context(value) -> str | None:
    """검증 통과 시 role_context, 아니면 None (슬롯 폴백 신호)."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or _words(v) > _ROLE_CONTEXT_MAX_WORDS:
        return None
    return v


def _clean_optional_props(value, budget: int) -> tuple[tuple[str, ...], bool]:
    """정상 항목만 남기고 예산만큼 자른다.

    반환: (정리된 props, changed) — changed면 잘못된 항목 제거나 예산 절단이 있었다.
    """
    if not isinstance(value, list):
        return (), bool(value)          # 리스트가 아니면 통째로 버림(있었으면 변경으로 표시)
    kept: list[str] = []
    changed = False
    for item in value:
        if not isinstance(item, str):
            changed = True
            continue
        v = item.strip()
        low = v.lower()
        ok = (v and _words(v) <= _OPTIONAL_PROP_MAX_WORDS
              and any(p in low for p in _PERIPHERY_PHRASES)
              and not any(b in low for b in _PROP_BANNED))
        if ok:
            kept.append(v)
        else:
            changed = True
    if len(kept) > budget:
        kept = kept[:budget]
        changed = True
    return tuple(kept), changed


def _clean_full_scene(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v or _words(v) > _FULL_SCENE_MAX_WORDS:
        return None
    return v


def _validate_slots_input(slots: list[dict]) -> None:
    """LLM 호출 **전에** 입력 계약을 강제한다. 잘못된 요청으로 유료 호출을 낭비하지 않는다."""
    if not slots:
        raise ValueError("slots가 비어 있다.")
    seen = set()
    for i, s in enumerate(slots):
        for key in ("role", "output_type", "brief", "intended_path"):
            if key not in s:
                raise ValueError(f"slots[{i}]에 '{key}'가 없다.")
        role = s["role"]
        if not isinstance(role, str) or not role.strip():
            raise ValueError(f"slots[{i}].role이 비었거나 문자열이 아니다.")
        if role in seen:
            raise ValueError(f"role 중복: {role!r}")
        seen.add(role)
        if s["output_type"] not in _VALID_OUTPUT_TYPES:
            raise ValueError(f"slots[{i}].output_type이 잘못됐다: {s['output_type']!r}")
        # 경로·출력형태 조합 강제 — passthrough나 어긋난 조합은 여기서 걸러진다.
        if (s["intended_path"], s["output_type"]) not in _ALLOWED_PATH_OUTPUT:
            raise ValueError(
                f"slots[{i}] 경로·출력형태 조합이 허용되지 않는다: "
                f"{s['intended_path']!r}→{s['output_type']!r}")
        # full_scene의 brief는 폴백값이 되므로 실제 비어 있지 않은 str만 허용한다.
        # None·list·dict를 str()로 삼키면 "None" 같은 프롬프트가 API로 나간다.
        if s["output_type"] == "full_scene":
            if not isinstance(s["brief"], str) or not s["brief"].strip():
                raise ValueError(
                    f"slots[{i}] full_scene 슬롯의 brief는 비어 있지 않은 문자열이어야 한다.")


def _fallback_context(slot: dict):
    """슬롯 폴백 — output_type에 맞는 결정론적 기본값 + LLM_SLOT_INVALID 경고."""
    if slot["output_type"] == "full_scene":
        # brief는 _validate_slots_input에서 비어 있지 않은 str로 검증됐다.
        return FullSceneContext(role=slot["role"],
                                full_scene=slot["brief"].strip(),
                                warnings=_invalid_slot_warning())
    return BackgroundContext(role=slot["role"], role_context="",
                             optional_props=(), warnings=_invalid_slot_warning())


def _context_from_response(slot: dict, data: dict | None, opt_budget: int):
    """응답 dict(이미 role로 매칭됨) → 검증된 SlotContext. 무효면 슬롯 폴백."""
    if not isinstance(data, dict) or data.get("output_type") != slot["output_type"]:
        return _fallback_context(slot)

    if slot["output_type"] == "background_context":
        rc = _clean_role_context(data.get("role_context"))
        if rc is None:
            return _fallback_context(slot)          # role_context 무효 = 슬롯 전체 무효
        props, changed = _clean_optional_props(data.get("optional_props"), opt_budget)
        warnings = _invalid_slot_warning() if changed else ()
        return BackgroundContext(role=slot["role"], role_context=rc,
                                 optional_props=props, warnings=warnings)

    fs = _clean_full_scene(data.get("full_scene"))
    if fs is None:
        return _fallback_context(slot)
    return FullSceneContext(role=slot["role"], full_scene=fs)


def generate_slot_contexts(req: dict, slots: list[dict]) -> tuple:
    """슬롯별 검증된 tagged-union 컨텍스트. 배치 chat_json 1회.

    입력 slots: [{"role", "output_type", "brief"}]. 반환 순서 = 입력 순서.
    한 슬롯 오류가 다른 정상 슬롯을 폴백시키지 않는다. 배치 전체 실패 시 모든 슬롯을
    각자 폴백하고 추가 LLM 호출은 하지 않는다.
    """
    _validate_slots_input(slots)                    # LLM 호출 전 계약 검증
    opt_budget = prop_budget_for(req.get("prop_density")).optional

    ctx = build_style_context(req)
    # presentation_mode·source_angle은 필수 계약이 아니다 — 누락 시 preserve·빈 값으로 흡수해
    # 기존 호출자·테스트를 보호한다.
    slots_desc = "\n".join(
        f'{i + 1}. role={s["role"]}, intended_path={s["intended_path"]}, '
        f'output_type={s["output_type"]}, '
        f'presentation_mode={s.get("presentation_mode", "preserve")}, '
        f'composition_anchor={s.get("composition_anchor", "center")}, '
        f'source_angle={s.get("source_angle") or ""}, brief="{s["brief"]}"'
        for i, s in enumerate(slots))
    user = _SLOT_CTX_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        category=req.get("category", ""),
        emphasis=req.get("emphasis", ""),
        product_details=req.get("product_details", ""),
        requested_background=req.get("background", ""),
        style_keywords=", ".join(ctx["image_keywords"]),
        n=len(slots), slots_desc=slots_desc,
    )

    by_role: dict = {}
    try:
        resp = chat_json(_SLOT_CTX_SYSTEM, user)
        for item in (resp.get("slots") or []):
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                by_role.setdefault(item["role"], item)   # 요청 role만, 첫 등장 우선
    except Exception:
        by_role = {}                                # 배치 실패 → 전 슬롯 폴백. 재호출 안 함.

    return tuple(_context_from_response(s, by_role.get(s["role"]), opt_budget)
                 for s in slots)


if __name__ == "__main__":
    import json

    sample = {
        "product_name": "무선 기계식 키보드", "color": "화이트",
        "category": "전자제품", "emphasis": "타건감과 미니멀 디자인",
        "num_images": 3, "brightness": 6, "mood": "미니멀",
        "color_palette": "화이트·크림", "background": "질감 표면",
    }
    print(json.dumps(generate(sample), ensure_ascii=False, indent=2))
