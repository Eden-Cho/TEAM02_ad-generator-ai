"""model-v2 파이프라인 — ae9cfc8 pipeline_service를 벤더링한 v2 오케스트레이터.

ae9cfc8 model/(= model_v2/)을 import해 상세페이지+썸네일을 생성한다. 팀 model/과 최상위
패키지명(baseline·composer·geo)이 겹치므로 **별도 워커(main_v2)** 로만 로드한다(6A 결정).
"""
import sys
import time
from collections import Counter
from pathlib import Path

# high_service_01/model 을 import 경로에 추가
_MODEL = Path(__file__).resolve().parents[3] / "model_v2"
if str(_MODEL) not in sys.path:
    sys.path.insert(0, str(_MODEL))

import baseline.config as config  # noqa: E402  (.env·모델ID 로드)
from baseline import copy_generator, image_generator, llm, prompt_generator  # noqa: E402
from baseline.archetypes import (get_profile, resolve_archetype,  # noqa: E402
                                 resolve_image_slots)
from baseline.image_plan import (GenerationTrace, PipelineTrace,  # noqa: E402
                                 WarningCode)
from baseline.image_planner import (build_image_plan, decide_path,  # noqa: E402
                                    enforce_evidence_grounding,
                                    enforce_solid_stick_context)
from baseline.style_presets import normalize_evidence  # noqa: E402
from composer.scene_templates import pick_scene  # noqa: E402  (씬 템플릿)
from baseline import grounding_boundary  # noqa: E402  (근거 기반 카피 경계)
from baseline.grounding_boundary import validate_public_fields  # noqa: E402,F401  (API 재노출)
from baseline.style_presets import (build_style_context, creativity_warning,  # noqa: E402,F401
                                    natural_warning, ui_dimensions, export_targets)  # (재노출)
from composer import thumbnails  # noqa: E402
from composer.build import build_rich_page  # noqa: E402
from geo.geo_layer import (geo_main, build_geo_html,  # noqa: E402  (GEO 텍스트 레이어)
                           build_product_jsonld, build_faq_jsonld)
from baseline.observability import observe, flush  # noqa: E402  (LangFuse 관측)

# 다나와식 대분류 → 내부 6 아키타입으로 자동 매핑
CATEGORIES = ["가전·TV", "컴퓨터·노트북·조립PC", "태블릿·모바일·디카", "패션·잡화",
              "뷰티", "식품", "가구·조명", "생활·주방·건강", "스포츠·골프", "반려·취미·사무"]

# 활용(사용 맥락) 컷 역할 — 이 컷에만 LLM 사용 맥락을 적용
USAGE_ROLES = ("lifestyle", "styling", "space", "serving")

# PlanWarning 폐쇄형 코드 → 사용자용 고정 한국어 문구. 사용자 입력·프롬프트·scene detail을
# 절대 섞지 않는다. 새 코드는 여기 명시적으로 추가해야만 노출된다.
_PLAN_WARNING_TEXT = {
    WarningCode.NO_SCENE_FOR_BACKGROUND:
        "선택한 배경 유형에 맞는 씬이 없어 대체 씬을 사용한 컷이 있습니다.",
    WarningCode.GENERIC_SCENE_USED:
        "일부 컷에 범용 씬 템플릿이 사용됐습니다.",
    WarningCode.USAGE_CONTEXT_UNAVAILABLE:
        "사용 맥락 조사가 없어 기본 연출로 대체된 컷이 있습니다.",
    WarningCode.LLM_SLOT_INVALID:
        "일부 컷의 AI 연출 제안이 검증을 통과하지 못해 기본값으로 대체됐습니다.",
    WarningCode.ROLE_EVIDENCE_MISSING:
        "성분·제형 근거가 확인되지 않아 일부 컷을 제품 외관·패키지 디테일로 전환했습니다"
        " (확인되지 않은 성분·제형·효능의 임의 생성을 방지).",
}


def _log(msg: str):
    print(f"[생성] {msg}", flush=True)


@observe(name="run_pipeline")
def run_pipeline(req: dict, product_paths: list[str], app_paths: list[str],
                 theme_name: str = "light") -> dict:
    """제품정보+사진 → 상세페이지(PIL) + 메인/부가 썸네일(PIL) + 소요시간."""
    t0 = time.time()
    # 유료 호출(슬롯 LLM·이미지) 前 계약 검증 — 모든 진입점(API·직접 호출) 공통. 잘못된 필드·
    # evidence는 여기서 ValueError로 끝나 chat_json·이미지 API가 0회가 된다. evidence는 여기서
    # 한 번 정규화해 아래에서 재계산 없이 그대로 쓴다.
    validate_public_fields(req)
    evidence = normalize_evidence(req.get("evidence"))
    llm.reset_accounting()      # 페이지 단위 회계 — 연속 요청 사이 누적 방지
    profile = get_profile(req["category"])
    ctx = build_style_context(req)
    presentation_mode = ctx["presentation_mode"]     # preserve | natural (검증됨)
    slots = resolve_image_slots(profile, product_paths, app_paths,
                                product_angles=req.get("product_angles"),
                                app_angles=req.get("app_angles"),
                                presentation_mode=presentation_mode)
    _log(f"시작 — 아키타입={profile['label']}, 이미지 {len(slots)}컷, 제품{len(product_paths)}/응용{len(app_paths)}장")

    arch_key = resolve_archetype(req.get("category"))

    # ── 1/5 경로 결정 → 슬롯 컨텍스트 배치 (LLM 최대 1회) ───────────────────────
    # 각 슬롯의 실행 경로를 먼저 정하고, passthrough를 뺀 슬롯만 한 배치로 LLM에 보낸다.
    # 전에는 generate()가 위치 기반 프롬프트를 만들어 composite 컷에서 그 결과가 통째로
    # 버려졌다 — 이제 role로 매칭되는 검증된 컨텍스트가 실제 프롬프트에 반영된다.
    _log("1/5 슬롯 컨텍스트 생성…")
    ctx_slots = []
    for slot in slots:
        path = decide_path(slot.get("source"), slot.get("image_path"), ctx["creativity"],
                           presentation_mode=presentation_mode)
        slot["intended_path"] = path
        if path == "passthrough":
            continue                      # 실사용 사진 → LLM 컨텍스트 불필요
        ctx_slots.append({
            "role": slot["role"],
            "output_type": "background_context" if path == "composite" else "full_scene",
            "brief": slot["brief"],
            "intended_path": path,
            "presentation_mode": presentation_mode,
            "source_angle": slot.get("angle") or "",   # 선택된 실제 제품 각도
            "composition_anchor": slot.get("composition_anchor", "center"),
        })
    # 모든 슬롯이 passthrough면 LLM을 호출하지 않는다.
    contexts = (prompt_generator.generate_slot_contexts(req, ctx_slots)
                if ctx_slots else ())
    # 근거 기반 역할 접지 — 근거 없는 ingredient/texture를 제품 외관 디테일로 전환(+경고).
    # 그 다음 제품 형태 안전 규칙(solid_stick texture 제형 문구 차단). 둘 다 pick_scene 전에
    # 적용해 composite scene["prompt"]와 creative_edit full_scene 양쪽을 덮는다. 폴백 포함.
    # evidence는 run_pipeline 시작부에서 이미 정규화됨(재계산 없음).
    contexts = tuple(enforce_evidence_grounding(evidence, c.role, c)
                     for c in contexts)
    product_form = ctx.get("product_form", "unknown")
    contexts = tuple(enforce_solid_stick_context(product_form, c.role, c)
                     for c in contexts)
    ctx_by_role = {c.role: c for c in contexts}

    # 활용(사용) 컷이 **합성될 때만** 제품이 실제 쓰이는 맥락을 LLM으로 1회 조사.
    usage_ctx = ""
    if any(s["intended_path"] == "composite" and s["role"] in USAGE_ROLES
           for s in slots):
        usage_ctx, _how_used = prompt_generator.generate_usage_context(req)
        if usage_ctx:
            _log("   · 사용 맥락 생성 완료")     # 원문은 로그로 내보내지 않는다

    # ── 2/5 슬롯별 ImagePlan 조립 (순수 — API 호출 없음) ──────────────────────
    # 컷별 씬 다양성 — pick_scene이 사용 횟수가 가장 적은 후보를 골라 배경 유형을 지키며
    # 균형 있게 돈다. composite 슬롯은 검증된 BackgroundContext를 pick_scene의 extra로 넘겨
    # role_context·optional_props가 최종 프롬프트에 정확히 1회 반영되게 한다.
    _log("2/5 이미지 플랜 조립…")
    used_scenes: Counter = Counter()
    plans = []
    for slot in slots:
        role = slot["role"]
        context = ctx_by_role.get(role)          # passthrough면 None
        scene = None
        if slot["intended_path"] == "composite":
            extra = {"usage_context": usage_ctx,
                     "role_context": context.role_context,
                     "optional_props": list(context.optional_props)}
            scene = pick_scene(arch_key, role, slot.get("angle"),
                               req, used_scenes, extra)
            used_scenes[scene["id"]] += 1
        plans.append(build_image_plan(slot, ctx, context, scene))

    roles = [p.role for p in plans]

    _log("3/5 카피·스펙 생성…")
    # 근거 경계 — evidence-sensitive 역할(ingredient/texture)이 있는 요청은 공개 카피·스펙을
    # 결정론적 안전 객체에서 조립하고 **LLM 카피/스펙/GEO를 호출하지 않는다**(불필요한 유료
    # 호출·유출 원천 제거). 비민감 요청(tech 등)은 기존 LLM 호출·결과를 그대로 유지(하위호환).
    sensitive = grounding_boundary.is_sensitive(roles)
    if sensitive:
        page_copy = grounding_boundary.safe_page_copy(req, roles, evidence)
        spec_table = grounding_boundary.safe_specs(req)
    else:
        page_copy = copy_generator.generate_page_copy(req, profile, roles,
                                                      ctx["copy_directives"])
        spec_table, _ = copy_generator.generate_page_extras(req, profile)

    # ── 4/5 이미지 실행 — 플랜의 prompt를 그대로 API에 보낸다 ─────────────────
    _log(f"4/5 이미지 {len(plans)}컷 생성…")
    images_by_role = {}
    generations: list[GenerationTrace] = []
    for i, (slot, plan) in enumerate(zip(slots, plans), 1):
        _log(f"   · [{i}/{len(plans)}] {plan.role} ({plan.intended_path}) 생성 중…")
        image_generator.reset_image_attempts()      # 플랜별 이미지 API 시도 수집
        images_by_role[plan.role] = image_generator.generate_image_v2(
            plan, slot.get("image_path"))
        # v2는 폴백 없이 계획 경로 그대로 실행 — actual_path=intended_path, outcome=ok.
        # geometry/text_placement는 아직 실행기가 계측하지 않으므로 None을 유지한다.
        generations.append(GenerationTrace(
            role=plan.role, actual_path=plan.intended_path, outcome="ok",
            scene_id=plan.scene_id, scene_is_generic=plan.scene_is_generic,
            image_api_calls=image_generator.image_attempts(),
            final_prompt_sha256=plan.prompt_sha256, prompt_len=plan.prompt_len))

    _log("상세페이지 조립…")
    page = build_rich_page(profile, images_by_role, page_copy, spec_table,
                           theme_name, ctx["page_width"])
    _log("5/5 썸네일 생성…")
    main = thumbnails.main_thumbnail(product_paths[0])
    gallery = thumbnails.gallery_thumbnails(images_by_role, roles)

    _log("GEO 텍스트 레이어 생성…")
    # 민감 요청은 FAQ·structured_data·geo_html도 결정론적 안전 객체에서 조립하고 geo_main
    # (FAQ LLM 포함)을 호출하지 않는다. Product JSON-LD description은 raw product_details를
    # 복사하지 않는다(jsonld_request). 비민감 요청만 geo_main으로 기존 GEO를 생성한다.
    if sensitive:
        _faq = grounding_boundary.safe_faq(req, roles, evidence)
        _jreq = grounding_boundary.jsonld_request(req)
        _jsonlds = [j for j in (build_product_jsonld(_jreq, spec_table),
                                build_faq_jsonld(_faq)) if j]
        geo = {"faq": _faq, "structured_data": _jsonlds, "warnings": [],
               "geo_html": build_geo_html(_jreq, page_copy, spec_table, _faq, _jsonlds)}
    else:
        geo = geo_main(req, profile, page_copy, spec_table)

    secs = round(time.time() - t0, 1)
    _log(f"완료 — {secs}초")
    flush()  # 대기 중 LangFuse 트레이스 전송 (비활성이면 no-op)

    # ── 경고 통합 — creativity → natural → plan 경고(폐쇄형 코드→고정 문구, 최초 등장
    # 순서) → GEO 가드레일. 최초 등장 순서로 중복 제거. geo["warnings"]는 pop해서 병합
    # 하므로 아래 **geo가 기존 경고를 덮어쓰지 못한다(이전 결함).
    geo_warnings = geo.pop("warnings", []) or []
    plan_warning_msgs = [
        _PLAN_WARNING_TEXT[w.code]
        for plan in plans for w in plan.constraint_warnings
        if w.code in _PLAN_WARNING_TEXT]
    warnings: list[str] = []
    for w in ([creativity_warning(req), natural_warning(req)]
              + plan_warning_msgs + list(geo_warnings)):
        if w and w not in warnings:
            warnings.append(w)

    # ── PipelineTrace — 기존 계약 재사용. safe dict만 밖으로 나간다.
    acct = llm.accounting()
    trace = PipelineTrace(
        logical_chat_calls=acct["logical_chat_calls"],
        actual_api_attempts=acct["actual_api_attempts"],
        image_api_attempts=sum(len(g.image_api_calls) for g in generations),
        seconds=secs, outcome="ok",
        image_warnings=tuple(warnings), generations=tuple(generations))

    return {"page": page, "main": main, "gallery": gallery, "seconds": secs,
            "warnings": warnings, "trace": trace.to_safe_dict(), **geo}
