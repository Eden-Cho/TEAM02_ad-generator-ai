"""파이프라인 서비스 — model/ 파이프라인을 감싸 한 번에 실행.

backend가 model/(baseline·composer)을 import해 상세페이지+썸네일을 생성한다.
"""
import sys
import time
from pathlib import Path

# high_service_01/model 을 import 경로에 추가
_MODEL = Path(__file__).resolve().parents[3] / "model"
if str(_MODEL) not in sys.path:
    sys.path.insert(0, str(_MODEL))

import baseline.config as config  # noqa: E402  (.env·모델ID 로드)
from baseline import copy_generator, image_generator, prompt_generator  # noqa: E402
from baseline.archetypes import get_profile, resolve_image_slots  # noqa: E402
from baseline.style_presets import build_style_context, ui_dimensions, export_targets  # noqa: E402,F401  (재노출)
from composer import thumbnails  # noqa: E402
from composer.build import build_rich_page  # noqa: E402
from geo.geo_layer import geo_main  # noqa: E402  (GEO 텍스트 레이어)
from baseline.observability import observe, flush  # noqa: E402  (LangFuse 관측)

# 🎯 [추가] 강사님이 주신 이미지 품질 평가(CLIP, BRISQUE) 모듈 임포트
from app.services.scorer import score_images, attach_scores_to_langfuse

# 다나와식 대분류 → 내부 6 아키타입으로 자동 매핑
CATEGORIES = ["가전·TV", "컴퓨터·노트북·조립PC", "태블릿·모바일·디카", "패션·잡화",
              "뷰티", "식품", "가구·조명", "생활·주방·건강", "스포츠·골프", "반려·취미·사무"]


def _log(msg: str):
    print(f"[생성] {msg}", flush=True)


@observe(name="run_pipeline")
def run_pipeline(req: dict, product_paths: list[str], app_paths: list[str],
                 theme_name: str = "light") -> dict:
    """제품정보+사진 → 상세페이지(PIL) + 메인/부가 썸네일(PIL) + 소요시간."""
    t0 = time.time()
    profile = get_profile(req["category"])
    ctx = build_style_context(req)
    slots = resolve_image_slots(profile, product_paths, app_paths)
    _log(f"시작 — 아키타입={profile['label']}, 이미지 {len(slots)}컷, 제품{len(product_paths)}/응용{len(app_paths)}장")

    _log("1/5 이미지 프롬프트 생성…")
    specs = prompt_generator.generate(req, ctx["image_keywords"], slots)
    roles = [s["role"] for s in specs]

    _log("2/5 카피·스펙 생성…")
    page_copy = copy_generator.generate_page_copy(req, profile, roles, ctx["copy_directives"])
    spec_table, _ = copy_generator.generate_page_extras(req, profile)

    _log(f"3/5 이미지 {len(specs)}컷 생성…")
    images_by_role = {}
    for i, spec in enumerate(specs, 1):
        _log(f"   · [{i}/{len(specs)}] {spec['role']} 생성 중…")
        images_by_role[spec["role"]] = image_generator.generate_image(
            spec, spec.get("image_path"), ctx["size"], creativity=ctx["creativity"])

    _log("4/5 상세페이지 조립…")
    page = build_rich_page(profile, images_by_role, page_copy, spec_table,
                            theme_name, ctx["page_width"])
    _log("5/5 썸네일 생성…")
    main = thumbnails.main_thumbnail(product_paths[0])
    gallery = thumbnails.gallery_thumbnails(images_by_role, roles)

    _log("GEO 텍스트 레이어 생성…")
    geo = geo_main(req, profile, page_copy, spec_table)

    secs = round(time.time() - t0, 1)
    _log(f"완료 — {secs}초")

    # 🎯 [추가] 이미지 생성 품질 검증 (CLIP & BRISQUE) 구간
    # 썸네일 갤러리에 들어간 PIL 이미지 후보군을 모아 정교하게 품질을 실시간 평가합니다.
    eval_scores = {"clip": None, "brisque": None, "n_images": 0}
    try:
        if gallery:
            _log("품질 평가 및 모니터링(CLIP & BRISQUE) 연산 시작…")
            eval_scores = score_images(gallery, req)
            _log(f"품질 점수 측정 성공: {eval_scores}")
            
            # 🎯 Langfuse 관측 서버로 점수 전송
            logged = attach_scores_to_langfuse(eval_scores)
            if logged:
                _log("Langfuse 대시보드 점수 매핑 완료!")
    except Exception as eval_err:
        _log(f"[에러] 품질 평가 도중 무해한 예외 발생(스킵): {eval_err}")

    flush()  # 대기 중 LangFuse 트레이스 전송 (비활성이면 no-op)
    
    # 🎯 리턴 딕셔너리에 'evaluation' 항목으로 점수를 탑재해 main.py 및 프론트엔드로 전달합니다.
    return {
        "page": page, 
        "main": main, 
        "gallery": gallery, 
        "seconds": secs, 
        "evaluation": eval_scores,  # 추가된 품질 점수 결과
        **geo
    }