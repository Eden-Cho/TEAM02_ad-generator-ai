"""model_hf/copy_generator.py — 허깅페이스 Qwen 로컬 엔진 전용 카피라이팅 빌더."""
from model_hf.generator import NewOpenSourceEngine
from baseline.style_presets import build_style_context

# 싱글톤 패턴으로 로컬 엔진 객체를 1회만 생성하여 공유합니다.
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = NewOpenSourceEngine()
    return _engine


def generate(req: dict, specs: list[dict],
             copy_directives: dict | None = None,
             copy_focus: str = "") -> list[dict]:
    """Qwen 로컬 엔진을 호출하여 컷별 한글 카피 문구를 생성합니다."""
    engine = get_engine()
    
    if copy_directives is None:
        copy_directives = build_style_context(req)["copy_directives"]

    roles = [s.get("role", f"cut{i}") for i, s in enumerate(specs)]
    
    # 🎯 기존 OpenAI API 대신, 새로 고도화된 Qwen 엔진 호출!
    # 루프를 돌며 각 이미지 역할(Role)별로 한 줄 카피를 생성해 리스트로 빌드합니다.
    copies = []
    for role in roles:
        # 제품명과 아키타입 카테고리를 활용해 로컬 Qwen 추론 요청
        raw_copy = engine.generate_huggingface_copy(
            product_name=req.get("product_name", "제품"),
            category=req.get("category", "일반")
        )
        
        # 템플릿 규격에 맞게 딕셔너리로 조립 (오픈소스 안전 가공)
        copies.append({
            "headline": f"[{role.upper()}] " + raw_copy[:12],
            "sub": raw_copy,
            "points": [raw_copy[:10]]
        })

    # 기존 파이프라인 안전장치 적용
    while len(copies) < len(specs):
        copies.append({"headline": req.get("product_name", ""), "sub": "", "points": []})
    for c in copies:
        c.setdefault("points", [])
        
    return copies[:len(specs)]


def generate_page_copy(req: dict, profile: dict, roles: list[str],
                       copy_directives: dict | None = None) -> dict:
    """상세페이지 전체 카피 문단을 생성합니다."""
    engine = get_engine()
    
    if copy_directives is None:
        copy_directives = build_style_context(req)["copy_directives"]
        
    product_name = req.get("product_name", "제품")
    category = req.get("category", "일반")

    # 1. 🎯 [개선] 고정 문구 대신, 제품을 수식할 한 줄 대제목(Headline)을 모델에 직접 요청합니다!
    headline_prompt = f"제품명 '{product_name}'에 어울리는 신뢰감 있고 매력적인 한글 대제목 한 줄(10자 내외)"
    intro_headline = engine.generate_huggingface_copy(headline_prompt, category)
    
    # 2. 제품 소개 본문(Body) 생성
    title_copy = engine.generate_huggingface_copy(f"{product_name}의 핵심 강점을 소개하는 마케팅 문구", category)
    
    # 각 특징(role)별 소구점 생성 구간
    sections_data = {}
    for r in roles:
        section_copy = engine.generate_huggingface_copy(f"{product_name}의 {r} 특징", category)
        sections_data[r] = {
            "headline": f"{r.upper()} 소구점",
            "sub": section_copy[:20],
            "body": section_copy,
            "points": [section_copy[:12]]
        }

    return {
        "intro": {
            # 🎯 이제 "혁신적인" 대신 모델이 생성한 생생한 제목이 들어갑니다!
            "headline": intro_headline,
            "body": title_copy
        },
        "sections": sections_data,
        "cta": "지금 바로 구매하기"
    }