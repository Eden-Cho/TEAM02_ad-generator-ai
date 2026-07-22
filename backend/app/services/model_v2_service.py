"""model-v2 어댑터 — 벤더링한 v2 오케스트레이터(model_v2_pipeline)를 감싸 options·preview·run을
제공한다. **신규 파일(병렬 추가)** 이며 팀의 pipeline_service·scorer·endpoint를 건드리지 않는다.

- options(): 스타일 옵션·카테고리·내보내기 규격(유료 호출 0).
- preview(): 역할·경로·씬·예상 호출 수만 반환(**LLM·이미지 API 0회** — pick_scene은 순수).
- run(): v2 run_pipeline 실행 + (선택) 팀 scorer 후처리(기본 비활성·실패 비치명·CLIP 미다운로드).
"""
import os
from collections import Counter

from app.services import model_v2_pipeline as _mv2


def options() -> dict:
    return {"style_dimensions": _mv2.ui_dimensions(),
            "categories": _mv2.CATEGORIES,
            "export_targets": _mv2.export_targets()}


def preview(req: dict, product_paths: list, app_paths: list) -> dict:
    """유료 호출 前 계산만 — 역할·경로·씬·예상 호출 수. LLM·이미지 API 0회.

    generate_slot_contexts(LLM)·이미지 생성은 부르지 않는다. pick_scene은 순수 함수라 안전하다.
    """
    _mv2.validate_public_fields(req)                 # 계약 검증(외부 호출 없음)
    evidence = _mv2.normalize_evidence(req.get("evidence"))  # noqa: F841 (검증용)
    profile = _mv2.get_profile(req["category"])
    ctx = _mv2.build_style_context(req)
    mode = ctx["presentation_mode"]
    slots = _mv2.resolve_image_slots(
        profile, product_paths, app_paths,
        product_angles=req.get("product_angles"), app_angles=req.get("app_angles"),
        presentation_mode=mode)
    arch = _mv2.resolve_archetype(req.get("category"))
    used: Counter = Counter()
    cuts, n, usage_llm = [], dict(composite=0, creative_edit=0, t2i=0, passthrough=0), 0
    for s in slots:
        path = _mv2.decide_path(s.get("source"), s.get("image_path"),
                                ctx["creativity"], presentation_mode=mode)
        n[path] += 1
        scene_id = None
        if path == "composite":
            if s["role"] in _mv2.USAGE_ROLES:
                usage_llm = 1
            scene = _mv2.pick_scene(arch, s["role"], s.get("angle"), req, used,
                                    {"usage_context": "", "role_context": "",
                                     "optional_props": []})
            used[scene["id"]] += 1
            scene_id = scene["id"]
        cuts.append({"role": s["role"], "intended_path": path,
                     "angle": s.get("angle"), "scene_id": scene_id})
    nonpass = len(slots) - n["passthrough"]
    slot_llm = 1 if nonpass else 0
    # 논리 LLM ≤ 슬롯배치 + usage_context + page_copy(≤2) + extras + FAQ
    llm_logical_max = slot_llm + usage_llm + 2 + 1 + 1
    return {
        "presentation_mode": mode,
        "product_form": ctx.get("product_form", "unknown"),
        "roles": [c["role"] for c in cuts],
        "cuts": cuts,
        "expected_calls": {
            "images_generate": n["composite"] + n["t2i"],
            "images_edit": n["creative_edit"],
            "passthrough": n["passthrough"],
            "llm_logical_max": llm_logical_max,
        },
    }


def _scoring_enabled() -> bool:
    # 기본 비활성 — 명시적 설정(MODEL_V2_SCORING=1)일 때만 팀 scorer 후처리.
    return os.getenv("MODEL_V2_SCORING", "").strip().lower() in ("1", "true", "yes")


def run(req: dict, product_paths: list, app_paths: list, theme_name: str = "light") -> dict:
    """v2 run_pipeline 실행. 선택적으로 팀 scorer 후처리(실패는 생성 결과를 실패시키지 않음)."""
    result = _mv2.run_pipeline(req, product_paths, app_paths, theme_name)
    if _scoring_enabled():
        try:
            from app.services.scorer import score_images   # 지연 import — 미설정 시 CLIP 미로드
            # 팀 scorer 계약: (gallery PIL 목록, 원본 req). 무손실로 evaluation에 싣는다.
            scores = score_images(result.get("gallery", []), req)
            result = {**result, "evaluation": scores}
        except Exception as e:
            # scorer 실패는 후처리일 뿐 — 생성 결과를 버리지 않는다(비치명, 원문 비노출).
            print(f"[model-v2] scoring skipped error_type={type(e).__name__}", flush=True)
    return result
