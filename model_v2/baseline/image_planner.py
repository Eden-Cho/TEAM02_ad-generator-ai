"""경로 결정 + ImagePlan 조립 — **순수**. LLM·이미지 API를 호출하지 않는다.

이 모듈이 하는 일은 딱 두 가지다:
    1) decide_path: 슬롯의 source·이미지 유무·창의성으로 실행 경로를 정한다.
    2) build_image_plan: 이미 결정된 조각(slot·스타일·SlotContext·scene)을 합쳐
       실행기(generate_image_v2)가 그대로 쓸 단일 ImagePlan을 만든다.

핵심 계약: **최종 prompt는 여기서 완성된다.** 실행기는 plan.prompt를 그대로 API에
보낼 뿐, 보존 문구·스타일·금지문을 덧붙이지 않는다. 그래야 plan.prompt_sha256가
실제로 나간 프롬프트와 일치한다(의도=실제).

경로별 출력형태(generate_slot_contexts와 동일 계약):
    composite      ← BackgroundContext (배경만)
    creative_edit  ← FullSceneContext  (제품 편집)
    t2i            ← FullSceneContext  (제품 포함 생성)
    passthrough    ← context 없음, prompt="" (API 호출 안 함)
"""
from baseline.composition_policy import copy_safe_clause_for, image_clause_for
from baseline.image_plan import (BackgroundContext, FullSceneContext, ImagePlan,
                                 PlanWarning, PromptParts, PropBudget, WarningCode)
from baseline.prompt_generator import QUALITY_SUFFIX, TEXT_ZONE_CLAUSE

# ── 고체 스틱 결정론적 안전 규칙 ────────────────────────────────────────────────
# 확인되지 않은 제형(크림·로션·액체·흰 스와치·웅덩이·누출·용융)을 사실처럼 표현하는
# 커머스 오류를 LLM 문구와 무관하게 최종 프롬프트에서 차단한다. product_form=="solid_stick"
# 일 때만 켠다(미지정 unknown은 기존 동작·스냅샷 불변).
PRODUCT_FORM_SOLID_STICK = "solid_stick"

# 최종 프롬프트에 결정론적으로 붙는 금지문(모든 역할·경로 공통). 닫힌 완제품만, 내용물 없음.
_SOLID_STICK_NEGATIVE = (
    "closed finished product only",
    "no cream", "no lotion", "no liquid", "no paste", "no gel",
    "no white swatch", "no smear", "no puddle", "no droplet",
    "no leaking, melting or exposed inner product",
    "no product residue on the surrounding surface")

# texture 역할 전용 대체 — 일반 화장품 제형 연출 대신 확인 가능한 외관 디테일로 **대체**한다
# (상충하는 no-cream을 덧붙이는 게 아니라 LLM의 크림 문구 자체를 치운다).
_SOLID_STICK_TEXTURE_DETAIL = (
    "macro detail of the closed stick exterior: vertical grooves and surface finish, "
    "the curved top edge, the dial and package material, verifiable outer details only")


def solid_stick_texture_detail() -> str:
    return _SOLID_STICK_TEXTURE_DETAIL


# ── 근거 기반 역할 접지 ─────────────────────────────────────────────────────────
# ingredient·texture는 제품 외관만으로 검증 불가한 성분·제형을 주장한다. 사용자가 입력한
# 검증 값(normalize_evidence)이 있으면 그 값만으로 결정론적 재조립, 없으면 제품 외관·패키지·
# 재질 디테일 컷으로 전환하고 ROLE_EVIDENCE_MISSING 경고를 컨텍스트에 실어 응답·trace로 흐른다.
from baseline.style_presets import EVIDENCE_REQUIRED_ROLES   # noqa: E402  (순환 없음)

_EVIDENCE_SAFE_DETAIL = (
    "detail shot of the product's own exterior, packaging and material — surface finish, "
    "form and verifiable outer details of the actual product only; no separate ingredients, "
    "no formulation, no swatch, no efficacy or benefit props")

# 검증된 값만으로 역할 컨텍스트를 **결정론적으로 재조립**하는 문구(LLM 문구는 버린다).
_EVIDENCE_LEAD = {
    "ingredient": "clean product detail featuring only these officially verified "
                  "components: {items}. Show only these; no other ingredients, "
                  "no added efficacy or benefit claims, no invented props.",
    "texture": "detail showing only this officially verified product texture: {items}. "
               "Only the described texture; no other formulation, no invented swatch.",
}


def evidence_safe_detail() -> str:
    return _EVIDENCE_SAFE_DETAIL


def _reassemble_from_evidence(role, items) -> str:
    """검증 항목만으로 결정론적 역할 문구를 만든다. LLM 원문은 쓰지 않는다."""
    return _EVIDENCE_LEAD[role].format(items=", ".join(items))


def enforce_evidence_grounding(evidence, role, context):
    """ingredient/texture를 검증 근거 기준으로 **결정론적으로 재조립**한다.

    **순수·idempotent.** evidence는 {role: (검증 문자열, ...)}(style_presets.normalize_evidence).
    - 검증 근거 있음: 기존 LLM role_context/full_scene/optional_props를 버리고 검증 항목만으로
      재조립(주입된 botanical/cream/효능/소품 제거). 경고 없음.
    - 근거 없음: 제품 외관·패키지 디테일로 전환 + ROLE_EVIDENCE_MISSING 경고(폐쇄형 코드).
    LLM·폴백 컨텍스트 모두, preserve(composite)·natural(creative_edit) 공통.
    검증 원문은 이 컨텍스트(→이미지 프롬프트)까지만 — trace·warnings·safe dict로는 안 나간다.
    """
    if role not in EVIDENCE_REQUIRED_ROLES or context is None:
        return context
    items = (evidence or {}).get(role)
    if items:                                    # 검증 근거 있음 → 검증 값만으로 재조립
        text = _reassemble_from_evidence(role, items)
        if isinstance(context, BackgroundContext):
            if context.role_context == text:
                return context
            return BackgroundContext(role=context.role, role_context=text,
                                     optional_props=(), warnings=context.warnings)
        if isinstance(context, FullSceneContext):
            if context.full_scene == text:
                return context
            return FullSceneContext(role=context.role, full_scene=text,
                                    warnings=context.warnings)
        return context
    # 근거 없음 → 안전 외관 디테일 + 경고
    warn = (PlanWarning(WarningCode.ROLE_EVIDENCE_MISSING),)
    if isinstance(context, BackgroundContext):
        if context.role_context == _EVIDENCE_SAFE_DETAIL:
            return context                              # 이미 전환됨(idempotent)
        return BackgroundContext(
            role=context.role, role_context=_EVIDENCE_SAFE_DETAIL, optional_props=(),
            warnings=context.warnings + warn)
    if isinstance(context, FullSceneContext):
        if context.full_scene == _EVIDENCE_SAFE_DETAIL:
            return context
        return FullSceneContext(role=context.role, full_scene=_EVIDENCE_SAFE_DETAIL,
                                warnings=context.warnings + warn)
    return context


def enforce_solid_stick_context(product_form, role, context):
    """solid_stick + texture면 내부 제형 연출을 결정론적 외관 디테일 컨텍스트로 **대체**한다.

    **순수·idempotent.** 그 외 형태/역할은 원본 그대로. LLM이 넣은 cream/lotion/smear가
    role_context·optional_props·full_scene에 긍정 지시로 남지 않게 만든다. composite는 이
    치환된 role_context가 pick_scene→scene["prompt"]에 반영되고, creative_edit/t2i는
    치환된 full_scene이 최종 프롬프트에 쓰인다. 폴백 컨텍스트에도 동일하게 적용된다.
    """
    if (product_form != PRODUCT_FORM_SOLID_STICK or role != "texture"
            or context is None):
        return context
    if isinstance(context, BackgroundContext):
        return BackgroundContext(role=context.role,
                                 role_context=_SOLID_STICK_TEXTURE_DETAIL,
                                 optional_props=(), warnings=context.warnings)
    if isinstance(context, FullSceneContext):
        return FullSceneContext(role=context.role,
                                full_scene=_SOLID_STICK_TEXTURE_DETAIL,
                                warnings=context.warnings)
    return context

# creative_edit·t2i 금지문 — **no logo를 넣지 않는다.**
# 실제 제품에는 로고가 있는데 "no logo"를 함께 주면 편집 시 제품 로고를 지우라는 지시와
# 충돌한다(문제 D). 텍스트 배제까지만 한다.
_EDIT_T2I_NEGATIVE = ("no text", "no letters", "no words", "no watermark")

# 자연 연출(natural) creative_edit 전용 보존 '지시'.
# 주의: 자연 연출은 제품을 재렌더한다 — 이 문구는 모델에 주는 지시일 뿐 결과 보장이 아니다.
# 코드·문서 어디에서도 "정확히 보존된다"고 단정하지 않는다. "Scene: "로 끝나 full_scene이
# 자연스럽게 이어진다.
_NATURAL_PRESERVE_CLAUSE = (
    "Preserve the exact product identity, geometry, proportions, colors, "
    "visible ports, markings and logo from the input image. "
    "Keep the supplied product view and integrate it naturally into the scene "
    "by matching lighting, perspective, contact shadow and ambient color. "
    "Do not add, remove or redesign any product feature. Scene: ")


def decide_path(source, image_path, creativity, *,
                presentation_mode: str = "preserve") -> str:
    """실행 경로 결정. **순수 함수.** presentation_mode는 키워드 전용(하위호환).

    - source == "usage"이고 이미지가 있으면 → passthrough (실사용 사진 그대로)
    - 이미지가 없으면 → t2i
    - presentation_mode == "natural"이고 제품 이미지가 있으면 → creative_edit
      (mask 없는 이미지 편집으로 제품과 배경을 함께 렌더 = 자연 연출)
    - preserve + 제품 이미지 + 창의성 ≤ 2 → composite (배경 생성 + 누끼 합성 = 픽셀 보존)
    - preserve + 제품 이미지 + 창의성 ≥ 3 → creative_edit (기존 재해석)

    기존 3인자 호출은 presentation_mode 기본값 "preserve"라 지금과 완전히 동일하다.
    """
    if source == "usage" and image_path:
        return "passthrough"
    if not image_path:
        return "t2i"
    if presentation_mode == "natural":
        return "creative_edit"
    try:
        c = int(creativity)
    except (TypeError, ValueError):
        c = 2
    return "composite" if c <= 2 else "creative_edit"


def _keep_clause(creativity: int) -> str:
    """creative_edit용 제품 보존 강도 지시 (창의성 3=정체성 유지, 4~5=대담한 재해석)."""
    if int(creativity) == 3:
        return ("Keep the product's identity, colors, logo and key proportions clearly "
                "recognizable, but you MAY change the camera angle, composition, styling "
                "and background creatively for: ")
    return ("Use the input product as a reference for its identity and colors, but "
            "reimagine it in a fresh, striking scene with a new angle and bold, "
            "artistic composition: ")


def _text_zone_clause(text_zone) -> str:
    return TEXT_ZONE_CLAUSE.get(text_zone or "none", "")


def _join(segments) -> str:
    return ", ".join(s for s in segments if s)


def _merge_warnings(scene_warning_dicts, ctx_warnings) -> tuple:
    """씬의 자유 형식 경고 dict(code만 읽음) + SlotContext 경고 → PlanWarning 튜플.

    같은 코드는 중복시키지 않는다. 알 수 없는 code는 버린다(폐쇄형 계약 유지).
    scene 경고의 나머지 detail(background·role 등)은 읽지 않고 버린다 —
    그 안에는 사용자 입력에서 파생된 문자열이 섞여 있다.
    """
    out: list[PlanWarning] = []
    seen: set = set()
    for w in scene_warning_dicts or []:
        try:
            code = WarningCode(w.get("code"))
        except (ValueError, AttributeError):
            continue                                  # 폐쇄형에 없는 코드 → 버림
        if code not in seen:
            seen.add(code)
            out.append(PlanWarning(code))
    for pw in ctx_warnings or ():
        if pw.code not in seen:
            seen.add(pw.code)
            out.append(pw)
    return tuple(out)


def build_image_plan(slot: dict, style_ctx: dict, context, scene: dict | None) -> ImagePlan:
    """결정된 조각 → 단일 ImagePlan. **LLM·이미지 API를 호출하지 않는다.**

    slot: {"role", "intended_path", "text_zone", "source", "angle", ...}
    style_ctx: build_style_context 결과 (image_keywords·size·creativity)
    context: SlotContext(BackgroundContext|FullSceneContext) 또는 None(passthrough)
    scene: composite일 때 pick_scene 결과, 그 외 None
    """
    path = slot["intended_path"]
    role = slot["role"]
    product_form = style_ctx.get("product_form", "unknown")
    # solid_stick texture면 크림 등 제형 문구를 결정론적 외관 디테일로 치환(idempotent).
    # creative_edit/t2i는 이 치환된 full_scene을 바로 쓰고, composite는 이미 pipeline이
    # pick_scene 전에 같은 함수로 치환해 scene["prompt"]에 반영돼 있다(여기선 기록만 정합).
    context = enforce_solid_stick_context(product_form, role, context)
    solid = product_form == PRODUCT_FORM_SOLID_STICK
    style = tuple(style_ctx.get("image_keywords") or [])
    size = style_ctx.get("size", "")
    source = slot.get("source")
    angle = slot.get("angle")
    # 구도 — 기본은 slot 값(없으면 center/0.5). composite는 아래에서 scene 값으로 덮는다
    # (충돌 시 composite의 단일 원본은 scene이다 — 배경·합성이 같은 값을 봐야 하므로).
    anchor = slot.get("composition_anchor", "center")
    x_ratio = slot.get("anchor_x_ratio", 0.5)

    if path == "passthrough":
        return ImagePlan(
            role=role, intended_path="passthrough", prompt="",
            prompt_parts=PromptParts(), size=size, source=source,
            angle_wanted=angle, angle_used=angle,
            composition_anchor=anchor, anchor_x_ratio=x_ratio)

    if path == "composite":
        if not isinstance(context, BackgroundContext):
            raise TypeError("composite 경로는 BackgroundContext가 필요하다.")
        if scene is None:
            raise ValueError("composite 경로는 선택된 scene이 필요하다.")
        # 최종 prompt는 pick_scene→fill이 이미 조립했다:
        #   구조+base_props → usage_context → role_context → optional_props → 스타일 → 접미
        # Hero 컷이면 그 뒤에 copy-safe 문구를 **정확히 1회** 덧붙인다(scene prompt는 불변,
        # fill/pick_scene 미변경 → 씬 스냅샷 0줄). 비-Hero(feature) 컷은 붙이지 않는다.
        prompt = scene["prompt"]
        # composite 구도의 단일 원본은 scene → copy-safe도 scene anchor에서 파생한다.
        copy_safe = (copy_safe_clause_for(scene.get("composition_anchor", "center"))
                     if role == "hero" else "")
        if copy_safe:
            prompt = _join([prompt, copy_safe])
        negative = _composite_negative()
        if solid:   # 고체 스틱 금지문을 최종 프롬프트에 정확히 1회 결정론적으로 덧붙인다
            prompt = _join([prompt, ", ".join(_SOLID_STICK_NEGATIVE)])
            negative = negative + _SOLID_STICK_NEGATIVE
        parts = PromptParts(
            structure=scene.get("structure", ""),
            usage_context=scene.get("usage_context", ""),
            role_context=context.role_context,
            base_props=tuple(scene.get("base_props", ())),
            optional_props=context.optional_props,
            style=style,
            negative=negative,
            copy_safe=copy_safe,
        )
        budget = scene.get("prop_budget") or PropBudget(0, 0)
        return ImagePlan(
            role=role, intended_path="composite", prompt=prompt, prompt_parts=parts,
            output_type="background_context",
            scene_id=scene.get("id"), scene_is_generic=bool(scene.get("is_generic")),
            size=size,
            width_ratio=scene.get("product_scale", 0.0),   # 씬 권장 제품 폭
            base_ratio=scene.get("surface_ratio", 0.0),    # 씬 표면(바닥선) 위치
            source=source, angle_wanted=angle, angle_used=angle,
            # composite 구도의 단일 원본은 scene — 배경 프롬프트와 실제 합성이 일치한다.
            composition_anchor=scene.get("composition_anchor", "center"),
            anchor_x_ratio=scene.get("anchor_x_ratio", 0.5),
            prop_budget=budget,
            constraint_warnings=_merge_warnings(scene.get("constraint_warnings"),
                                                context.warnings))

    # creative_edit · t2i — 둘 다 FullSceneContext
    if not isinstance(context, FullSceneContext):
        raise TypeError(f"{path} 경로는 FullSceneContext가 필요하다.")
    text_zone = _text_zone_clause(slot.get("text_zone"))
    creativity = int(style_ctx.get("creativity", 2))
    presentation = style_ctx.get("presentation_mode", "preserve")

    if path == "creative_edit":
        # 자연 연출이면 전용 보존 지시, 그 외(preserve 창의성 3+)는 기존 creativity별 문구.
        lead = (_NATURAL_PRESERVE_CLAUSE if presentation == "natural"
                else _keep_clause(creativity))         # 보존 문구 + full_scene
    elif path == "t2i":
        lead = ""                                      # 제품 포함은 full_scene 자체가 담당
    else:
        raise ValueError(f"알 수 없는 intended_path: {path!r}")

    # 고정 구도 문구를 **결정론적으로** plan.prompt에 넣는다. LLM 응답이 구도를 생략하거나
    # brief 폴백이 쓰여도 최종 프롬프트에 정확히 1회 남는다 → left/right가 프롬프트·SHA까지
    # 달라진다. (natural 결과 정확도를 보장한다는 뜻은 아니다 — 지시일 뿐이다.)
    composition_clause = image_clause_for(anchor)
    # Hero는 legacy bottom text-zone 문구 **대신** copy-safe 문구를 쓴다(공존 금지).
    # feature 등 비-Hero는 기존 text-zone 문구를 그대로 유지 → 바이트 동일.
    if role == "hero":
        copy_safe = copy_safe_clause_for(anchor)
        layout_seg, tz_record, cs_record = copy_safe, "", copy_safe
    else:
        copy_safe, layout_seg, tz_record, cs_record = "", text_zone, text_zone, ""
    # 고체 스틱이면 텍스트 금지문 뒤에 제형 금지문을 정확히 1회 덧붙인다(texture는 위에서
    # full_scene이 이미 외관 디테일로 치환됐으므로 크림 긍정 지시와 상충하지 않는다).
    negative = _EDIT_T2I_NEGATIVE + (_SOLID_STICK_NEGATIVE if solid else ())
    prompt = _join([lead + context.full_scene.strip().rstrip("."),
                    composition_clause, ", ".join(style), layout_seg,
                    ", ".join(negative), QUALITY_SUFFIX])
    parts = PromptParts(
        full_scene=context.full_scene, style=style,
        negative=negative, text_zone=tz_record,
        composition=composition_clause, copy_safe=cs_record)
    return ImagePlan(
        role=role, intended_path=path, prompt=prompt, prompt_parts=parts,
        output_type="full_scene", size=size, source=source,
        angle_wanted=angle, angle_used=angle,
        # creative_edit·t2i는 로컬 합성이 없다 — slot 구도 값을 그대로 계획에 싣는다.
        composition_anchor=anchor, anchor_x_ratio=x_ratio,
        constraint_warnings=_merge_warnings(None, context.warnings))


# composite 금지문 — scene_templates._SUFFIX와 **같은 문구**를 PromptParts에 기록한다.
# 실제 프롬프트의 금지문은 fill()이 붙인 _SUFFIX이므로, 그 단일 원본을 쪼개 쓴다.
def _composite_negative() -> tuple:
    from composer.scene_templates import _SUFFIX
    return tuple(c.strip() for c in _SUFFIX.split(",") if c.strip())
