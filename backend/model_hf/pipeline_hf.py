"""model_hf/pipeline_hf.py — 허깅페이스 오픈소스(Qwen+FLUX) 전용 파이프라인.

기존 OpenAI 파이프라인과 완벽히 분리되어 로컬 모델 기반으로 상세페이지 및 썸네일을 생성합니다.
"""
import time
from pathlib import Path
from PIL import Image

# 기존 프로토타입의 레이아웃 조립 및 아키타입 자원 재활용
from baseline.archetypes import get_profile, resolve_image_slots
from baseline.style_presets import build_style_context
from composer.build import build_rich_page
from composer import thumbnails

# 🎯 새로 구축한 허깅페이스 전용 모듈 로드
from model_hf import copy_generator
from model_hf.generator import NewOpenSourceEngine

def _log(msg: str):
    print(f"[HF-파이프라인] {msg}", flush=True)

def run_pipeline_hf(req: dict, product_paths: list[str], app_paths: list[str],
                    theme_name: str = "light") -> dict:
    """제품 정보와 이미지를 받아 로컬 Qwen + FLUX 엔진으로 상세페이지를 조립 및 생성합니다."""
    t0 = time.time()
    
    # 1. 아키타입 매핑 및 컨텍스트 빌드
    profile = get_profile(req["category"])
    ctx = build_style_context(req)
    slots = resolve_image_slots(profile, product_paths, app_paths)
    
    _log(f"시작 — 아키타입={profile['label']}, 이미지 {len(slots)}컷 세팅 완료.")

    # 2. 🧠 로컬 Qwen 엔진 기반 dynamic 카피라이팅 생성
    _log("1/4 [Qwen] 로컬 마케팅 카피 및 섹션 텍스트 생성 중...")
    page_copy = copy_generator.generate_page_copy(req, profile, [s["role"] for s in slots])
    
    # 스펙표(가짜 혹은 기본 UI 템플릿용) 바인딩
    spec_table = {k: v for i, (k, v) in enumerate(req.get("product_details", "").split("\n")) if ":" in v and i < 6}
    if not spec_table:
        spec_table = {"제품명": req.get("product_name", "기본 제품")}

    # 3. 🎨 [FLUX.1-schnell] 실물급 광고 스튜디오 이미지 생성
    _log(f"2/4 [FLUX] {len(slots)}개의 소구점 이미지 순차 생성 시작 (VRAM 방어 가동)...")
    images_by_role = {}
    engine_hf = copy_generator.get_engine()  # 싱글톤으로 선언된 HF 통합 엔진 인스턴스 획득
    
    for i, slot in enumerate(slots, 1):
        role = slot["role"]
        _log(f"   · [{i}/{len(slots)}] {role} 컷 렌더링 중...")
        
        # UI 키워드 지시문을 조합하여 FLUX 프롬프트 완성
        concept_prompt = ", ".join(ctx.get("image_keywords", ["premium setup"]))
        
        # FLUX 구동 후 로컬 디스크 저장 경로 획득
        saved_img_path = engine_hf.generate_huggingface_image(concept_prompt, f"{req.get('product_name')}_{role}")
        
        # 컴포저가 인식할 수 있도록 PIL Image 객체로 오픈하여 매핑
        images_by_role[role] = Image.open(saved_img_path)

    # 4. 🎛️ 상세페이지 레이아웃 최종 조립
    _log("3/4 리치 상세페이지 캔버스 조립 및 컴포징...")
    page = build_rich_page(profile, images_by_role, page_copy, spec_table,
                           theme_name, ctx["page_width"])
    
    # 5. 썸네일 레이어 추출
    _log("4/4 크롭 및 마케팅 썸네일 레이아웃 생성...")
    main_thumb = thumbnails.main_thumbnail(product_paths[0])
    gallery_thumbs = thumbnails.gallery_thumbnails(images_by_role, list(images_by_role.keys()))

    secs = round(time.time() - t0, 1)
    _log(f"완료 — 총 소요시간: {secs}초")
    
    return {
        "page": page,
        "main": main_thumb,
        "gallery": gallery_thumbs,
        "seconds": secs
    }