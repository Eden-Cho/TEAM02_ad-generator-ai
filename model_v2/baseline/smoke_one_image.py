"""단일 역할 1장 스모크 러너 — 실제 프롬프트 품질을 **한 장만** 확인한다.

왜 필요한가:
    `/api/generate-detail-page`에 제품 1장을 올려도 테크 프로필은 hero·build·
    connectivity·lifestyle 4개 슬롯을 만든다 → 이미지 API가 4회 나간다. 그건 "1장 테스트"가
    아니라 상세페이지 전체 테스트다. 이 러너는 지정한 역할 **하나만** 골라 실제 파이프라인
    조각(decide_path → generate_slot_contexts → pick_scene → build_image_plan →
    generate_image_v2)을 그대로 태워 딱 1장만 생성한다.

주의: **이 러너를 실행하면 유료 LLM·이미지 API가 호출된다.** (슬롯 컨텍스트 1회 + 이미지 1회)
    무과금 테스트는 이 모듈의 함수를 mock으로 검증하고, 실제 실행은 사람이 판단해서 돌린다.

실행 예:
    PYTHONPATH=model /Users/who/Desktop/code_it/.venv/bin/python \\
      -m baseline.smoke_one_image \\
      --request model/baseline/sample_request.json \\
      --image /absolute/path/to/product.png \\
      --role hero \\
      --output model/outputs/smoke_hero.png \\
      --check
"""
import argparse
import json
from pathlib import Path

from baseline import image_generator, prompt_generator
from baseline.archetypes import get_profile, image_slots, resolve_archetype
from baseline.composition_policy import placement_for
from baseline.image_plan import BackgroundContext, FullSceneContext
from baseline.image_planner import build_image_plan, decide_path
from baseline.style_presets import build_style_context
from composer.scene_templates import pick_scene

# 활용(사용 맥락) 역할 — composite로 갈 때만 usage_context를 조사한다.
_USAGE_ROLES = ("lifestyle", "styling", "space", "serving")

# CLI --angle 허용값 = 프로덕션 ANGLE_OPTIONS와 동일(전면/후면 3/4 포함).
_ANGLE_CHOICES = ("정면", "전면 3/4", "측면", "후면 3/4", "후면", "디테일", "사용장면")


def _find_slot(profile: dict, role: str) -> dict:
    """프로필의 이미지 슬롯 중 role 하나를 고른다. 없으면 사용 가능한 role을 알려준다."""
    slots = image_slots(profile)
    for s in slots:
        if s["role"] == role:
            return dict(s)
    available = ", ".join(s["role"] for s in slots)
    raise ValueError(f"role={role!r}가 이 프로필에 없다. 사용 가능: {available}")


def _stub_context(role: str, intended_path: str, brief: str):
    """LLM 없이 만드는 결정론적 stub 컨텍스트 — dry-run 미리보기 전용.

    composite는 빈 role_context(→ fill이 넣지 않음), full_scene은 brief를 그대로 쓴다.
    유료 호출을 하지 않으므로 최종 프롬프트가 LLM으로 풍부해지기 전 '골격'만 보여준다.
    """
    if intended_path == "composite":
        return BackgroundContext(role=role, role_context="", optional_props=())
    return FullSceneContext(role=role, full_scene=brief.strip())


def build_single_plan(req: dict, role: str, image_path: str | None, *,
                      source: str = "product", image_angle: str = "정면",
                      use_llm: bool = True):
    """지정 역할 1개의 ImagePlan을 만든다. 프로덕션 run_pipeline과 동일한 조각을 쓴다.

    presentation_mode(preserve|natural)는 build_style_context가 검증한 값을 쓴다 —
    natural이면 decide_path가 creative_edit로 라우팅한다. 단일 스모크는 이미지가 한 장뿐이라
    역할별 각도 매칭 대신 CLI로 받은 image_angle을 실제 입력 각도로 그대로 쓴다(임의 각도를
    발명하지 않고 이 각도를 LLM에 전달).

    use_llm=True  : 실제 파이프라인과 동일 — 슬롯 컨텍스트 LLM 최대 1회(+ composite 활용
                    역할이면 usage_context 1회). **유료.**
    use_llm=False : LLM을 부르지 않고 stub 컨텍스트로 골격만 조립한다. **무과금 dry-run.**

    반환: (plan, slot).
    """
    profile = get_profile(req["category"])
    arch_key = resolve_archetype(req.get("category"))
    ctx = build_style_context(req)
    presentation_mode = ctx["presentation_mode"]     # preserve | natural (검증됨)

    slot = _find_slot(profile, role)
    slot["source"] = source
    slot["image_path"] = image_path
    slot["angle"] = image_angle                       # 실제 입력 각도 — 임의 각도 발명 금지
    slot["intended_path"] = decide_path(source, image_path, ctx["creativity"],
                                        presentation_mode=presentation_mode)
    placement = placement_for(role)                   # 프로덕션과 같은 공통 구도 정책
    slot["composition_anchor"] = placement.anchor
    slot["anchor_x_ratio"] = placement.x_ratio
    path = slot["intended_path"]

    context = None
    if path != "passthrough":
        if use_llm:
            ctx_slots = [{
                "role": role,
                "output_type": ("background_context"
                                if path == "composite" else "full_scene"),
                "brief": slot["brief"],
                "intended_path": path,
                "presentation_mode": presentation_mode,
                "source_angle": slot.get("angle") or "",   # 프로덕션과 동일 전달
                "composition_anchor": slot["composition_anchor"],
            }]
            context = prompt_generator.generate_slot_contexts(req, ctx_slots)[0]  # LLM 1회
        else:
            context = _stub_context(role, path, slot["brief"])

    scene = None
    if path == "composite":
        usage_ctx = ""
        if role in _USAGE_ROLES and use_llm:
            usage_ctx, _ = prompt_generator.generate_usage_context(req)
        extra = {"usage_context": usage_ctx,
                 "role_context": context.role_context,
                 "optional_props": list(context.optional_props)}
        from collections import Counter
        scene = pick_scene(arch_key, role, slot["angle"], req, Counter(), extra)

    plan = build_image_plan(slot, ctx, context, scene)
    return plan, slot


def would_call(req: dict, plan) -> dict:
    """dry-run 회계 — 이 플랜을 --execute로 돌리면 나갈 유료 호출 수(무과금 계산)."""
    slot_llm = 0 if plan.intended_path == "passthrough" else 1
    usage_llm = (1 if (plan.intended_path == "composite"
                       and plan.role in _USAGE_ROLES) else 0)
    image_api = 0 if plan.intended_path == "passthrough" else 1
    return {"slot_context_llm": slot_llm, "usage_context_llm": usage_llm,
            "image_api": image_api}


def generate_one(req: dict, role: str, image_path: str | None, output: str, *,
                 source: str = "product", image_angle: str = "정면"):
    """플랜 1개를 실행해 1장 생성 → output에 저장. **유료 이미지 API 1회.**"""
    plan, slot = build_single_plan(req, role, image_path, source=source,
                                   image_angle=image_angle)
    img = image_generator.generate_image_v2(plan, slot["image_path"])
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return plan, img


def preservation_score(product_path: str, output_img) -> float:
    """제품 보존 점수 — 멀티스케일 정규화 상호상관(skimage match_template)의 최대 피크.

    CLAUDE.md 규칙: 실루엣 IoU는 rembg가 손·소품까지 잡아 오염되므로 쓰지 않는다.
    합성본(제품=원본)의 기준선 ≈ 0.825, 드리프트 실패 ≈ 0.22. 이 값은 **동일성 지표**이지
    "완벽 보존"의 증거가 아니다 — 측정한 수치만 보고한다.

    composite 경로에서만 의미가 있다. creative_edit·t2i는 제품을 재렌더하므로 낮게 나오는
    것이 정상이다(픽셀 보존을 약속한 경로가 아니다).
    """
    import numpy as np
    from PIL import Image
    from skimage.color import rgb2gray
    from skimage.feature import match_template
    from skimage.transform import resize as sk_resize

    from baseline import bg_remover

    rgba = bg_remover.cutout(Image.open(product_path))     # RGBA 누끼
    bbox = rgba.getbbox()
    template_img = rgba.convert("RGB")
    if bbox:
        template_img = template_img.crop(bbox)             # 제품 영역만

    t = rgb2gray(np.asarray(template_img))
    o = rgb2gray(np.asarray(output_img.convert("RGB")))
    oh, ow = o.shape[:2]

    best = -1.0
    for ratio in (0.35, 0.45, 0.55, 0.65, 0.75, 0.85):
        tw = int(ow * ratio)
        if tw < 8 or t.shape[1] < 2:
            continue
        scale = tw / t.shape[1]
        th = int(t.shape[0] * scale)
        if th < 8 or th >= oh or tw >= ow:
            continue
        tt = sk_resize(t, (th, tw), anti_aliasing=True)
        if float(tt.std()) < 1e-6:
            continue                     # 분산 0 템플릿은 NCC가 정의되지 않는다 → 건너뜀
        res = match_template(o, tt)
        peak = float(res.max())
        if np.isfinite(peak):
            best = max(best, peak)
    return best


def main(argv=None) -> int:
    """기본은 **무과금 dry-run**이다. 실제 유료 생성은 --execute를 명시해야만 일어난다.

    비용 안전: 옵션과 무관하게 무조건 생성하던 이전 동작을 뒤집었다. --execute 없이는
    LLM·이미지 API를 한 번도 부르지 않고, 무엇이 어떻게 나갈지(경로·씬·유료 호출 수)만
    보여준다.
    """
    ap = argparse.ArgumentParser(
        prog="baseline.smoke_one_image",
        description="단일 역할 1장 스모크 — 기본 dry-run(무과금), --execute로만 실제 생성")
    ap.add_argument("--request", required=True, help="요청 JSON 경로")
    ap.add_argument("--image", default=None,
                    help="제품 이미지 절대경로 (없으면 t2i 경로)")
    ap.add_argument("--role", default="hero", help="생성할 슬롯 역할 (기본 hero)")
    ap.add_argument("--output", required=True, help="저장 경로 (.png) — --execute일 때만 씀")
    ap.add_argument("--source", default="product", choices=("product", "usage"),
                    help="슬롯 소스 (usage+이미지면 passthrough)")
    ap.add_argument("--angle", default="정면", choices=_ANGLE_CHOICES,
                    help="제품 이미지의 실제 각도 (기본 정면). 자연 연출은 이 각도를 유지한다.")
    ap.add_argument("--execute", action="store_true",
                    help="실제로 유료 LLM·이미지 API를 호출해 1장 생성 (기본은 dry-run)")
    ap.add_argument("--check", action="store_true",
                    help="--execute와 함께: 생성 후 제품 보존 점수(멀티스케일 NCC) 측정")
    args = ap.parse_args(argv)

    req = json.loads(Path(args.request).read_text(encoding="utf-8"))

    # ── 기본: dry-run — 유료 호출 0회 ──────────────────────────────────────
    if not args.execute:
        plan, slot = build_single_plan(req, args.role, args.image,
                                       source=args.source, image_angle=args.angle,
                                       use_llm=False)
        wc = would_call(req, plan)
        # 안전 필드만 출력 — 프롬프트 원문은 내보내지 않는다.
        print(f"[dry-run] role={plan.role} path={plan.intended_path} "
              f"scene={plan.scene_id} source_angle={slot.get('angle') or ''} "
              f"anchor={plan.composition_anchor} x={plan.anchor_x_ratio} "
              f"(유료 호출 없음 — 골격만)")
        print(f"[dry-run] --execute 시 예상 유료 호출: 슬롯 LLM {wc['slot_context_llm']} + "
              f"usage LLM {wc['usage_context_llm']} + 이미지 API {wc['image_api']}")
        if args.check:
            print("[dry-run] --check는 실제 생성물이 필요하다 → --execute와 함께 쓰라.")
        return 0

    # ── --execute: 실제 생성 (유료) ───────────────────────────────────────
    plan, img = generate_one(req, args.role, args.image, args.output,
                             source=args.source, image_angle=args.angle)
    # 프롬프트 원문은 출력하지 않는다 — 안전 필드만.
    print(f"[스모크] role={plan.role} path={plan.intended_path} "
          f"prompt_len={plan.prompt_len} sha={plan.prompt_sha256[:12]} → {args.output}")

    if args.check:
        if plan.intended_path == "composite" and args.image:
            score = preservation_score(args.image, img)
            print(f"[보존] 멀티스케일 NCC 최대 피크 = {score:.3f} "
                  f"(합성 기준선 ≈ 0.825 / 드리프트 실패 ≈ 0.22 — 동일성 지표일 뿐)")
        else:
            print(f"[보존] path={plan.intended_path}: 픽셀 보존을 약속하는 경로가 아니라 "
                  "보존 점수를 측정하지 않는다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
