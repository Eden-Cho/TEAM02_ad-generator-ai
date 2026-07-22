"""파이프라인 서비스 — model/ 파이프라인을 감싸 한 번에 실행."""
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PIL import Image, ImageDraw

_MODEL = Path(__file__).resolve().parents[3] / "model"
if str(_MODEL) not in sys.path:
    sys.path.insert(0, str(_MODEL))

import baseline.config as config  # noqa: E402
from baseline import copy_generator, image_generator, prompt_generator  # noqa: E402
from baseline.archetypes import get_profile, resolve_image_slots  # noqa: E402
from baseline.style_presets import build_style_context, ui_dimensions, export_targets  # noqa: E402
from composer import thumbnails  # noqa: E402
from composer.build import build_rich_page  # noqa: E402
from geo.geo_layer import geo_main  # noqa: E402
from baseline.observability import observe, flush  # noqa: E402

from app.services.scorer import score_images, attach_scores_to_langfuse

CATEGORIES = ["가전·TV", "컴퓨터·노트북·조립PC", "태블릿·모바일·디카", "패션·잡화",
              "뷰티", "식품", "가구·조명", "생활·주방·건강", "스포츠·골프", "반려·취미·사무"]


def _log(msg: str):
    print(f"[생성] {msg}", flush=True)


def _create_fallback_image(role: str, size: tuple[int, int] = (1024, 1024)) -> Image.Image:
    img = Image.new("RGB", size, color=(240, 242, 245))
    draw = ImageDraw.Draw(img)
    text = f"[{role}]\nImage Generation Failed"
    w, h = size
    draw.text((w // 2, h // 2), text, fill=(100, 100, 100), anchor="mm")
    return img


# 🎯 [핵심] 스레드 내부 개별 함수에서는 @observe를 떼어내어 Trace 파편화 원인을 차단합니다.
def _gen_single_image(spec: dict, size: Any, creativity: Any, max_retries: int = 2) -> tuple[str, Any]:
    role = spec["role"]
    _log(f"   · [{role}] 이미지 생성 개시…")
    
    for attempt in range(1, max_retries + 2):
        try:
            img = image_generator.generate_image(
                spec, spec.get("image_path"), size, creativity=creativity
            )
            if img is not None:
                _log(f"   · [{role}] 이미지 생성 성공! (시도 {attempt}회)")
                return role, img
        except Exception as e:
            _log(f"   ⚠️ [{role}] 생성 시도 {attempt}/{max_retries + 1} 실패: {e}")
            if attempt <= max_retries:
                time.sleep(1.5 * attempt)
    
    _log(f"   🚨 [{role}] 최종 생성 실패! 대체(Fallback) 이미지로 전환합니다.")
    fallback_img = _create_fallback_image(role, size=(1024, 1024) if not size else size)
    return role, fallback_img


# 🎯 최상위 단일 관측 단위 (Root Trace)
@observe(name="run_pipeline")
def run_pipeline(req: dict, product_paths: list[str], app_paths: list[str],
                 theme_name: str = "light") -> dict:
    t0 = time.time()
    profile = get_profile(req["category"])
    ctx = build_style_context(req)
    slots = resolve_image_slots(profile, product_paths, app_paths)
    _log(f"시작 — 아키타입={profile['label']}, 이미지 {len(slots)}컷, 제품{len(product_paths)}/응용{len(app_paths)}장")

    _log("1/5 이미지 프롬프트 생성…")
    specs = prompt_generator.generate(req, ctx["image_keywords"], slots)
    roles = [s["role"] for s in specs]

    _log(f"2/5 & 3/5 카피 생성 및 이미지 {len(specs)}컷 동시 병렬 작업 시작…")
    
    images_by_role = {}
    page_copy = None
    spec_table = None

    max_workers = len(specs) + 2
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_copy = executor.submit(
            copy_generator.generate_page_copy, req, profile, roles, ctx["copy_directives"]
        )
        future_extras = executor.submit(
            copy_generator.generate_page_extras, req, profile
        )

        future_images = [
            executor.submit(_gen_single_image, spec, ctx["size"], ctx["creativity"])
            for spec in specs
        ]

        page_copy = future_copy.result()
        spec_table, _ = future_extras.result()

        for f in future_images:
            role, img = f.result()
            images_by_role[role] = img

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

    # 🎯 메인 스레드의 run_pipeline Root Trace에 품질 점수를 확실하게 매핑
    eval_scores = {"clip": None, "brisque": None, "n_images": 0}
    try:
        if gallery:
            _log("품질 평가 및 모니터링(CLIP & BRISQUE) 연산 시작…")
            eval_scores = score_images(gallery, req)
            _log(f"품질 점수 측정 성공: {eval_scores}")
            
            # 메인 스레드에서 점수 등록
            attach_scores_to_langfuse(eval_scores)
            _log("Langfuse 대시보드 점수 매핑 완료!")
    except Exception as eval_err:
        _log(f"[에러] 품질 평가 도중 예외 발생: {eval_err}")

    flush()  # 대기 전송 큐 즉시 비우기
    
    return {
        "page": page, 
        "main": main, 
        "gallery": gallery, 
        "seconds": secs, 
        "evaluation": eval_scores,
        **geo
    }