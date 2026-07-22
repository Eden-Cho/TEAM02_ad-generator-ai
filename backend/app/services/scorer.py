from __future__ import annotations
from typing import Any, Iterable

# ── 전역 싱글톤 캐시 (최초 1회만 채워짐) ──────────────────────────────────
_clip_bundle = None      # (model, processor, device) 또는 False(사용불가)
_CLIP_MODEL_ID = "openai/clip-vit-base-patch32"   # 가볍고 표준적인 기본 모델


# ── 입력 정규화 ──────────────────────────────────────────────────────────
def _iter_images(images: Any) -> list:
    """dict{role: PIL} · list[PIL] · 단일 PIL 무엇이 와도 [PIL, ...]로 통일."""
    if images is None:
        return []
    if isinstance(images, dict):
        return [v for v in images.values() if v is not None]
    if isinstance(images, (list, tuple)):
        return [v for v in images if v is not None]
    return [images]  # 단일 이미지


def _build_caption(req: dict | None) -> str:
    """req에서 CLIP용 캡션을 조립한다."""
    if not req:
        return "a product photo"
    parts = []
    for key in ("color", "brand", "product_name", "category"):
        v = req.get(key)
        if v:
            parts.append(str(v))
    emphasis = req.get("emphasis")
    base = " ".join(parts) if parts else "a product"
    caption = f"a product photo of {base}"
    if emphasis:
        caption += f", {emphasis}"
    return caption[:300]


# ── CLIP: 텍스트-이미지 정렬 점수 ────────────────────────────────────────
def _get_clip():
    """CLIP (model, processor, device)를 최초 1회만 로드. 실패 시 False."""
    global _clip_bundle
    if _clip_bundle is None:
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = CLIPModel.from_pretrained(_CLIP_MODEL_ID).to(device).eval()
            processor = CLIPProcessor.from_pretrained(_CLIP_MODEL_ID)
            _clip_bundle = (model, processor, device)
        except Exception as e:
            print(f"[scoring] CLIP 비활성화: {e}", flush=True)
            _clip_bundle = False
    return _clip_bundle


def clip_score(images: Any, req: dict | None) -> float | None:
    """생성 이미지들과 상품 설명(caption)의 평균 CLIP 코사인 유사도."""
    imgs = _iter_images(images)
    if not imgs:
        return None
    bundle = _get_clip()
    if not bundle:
        return None
    model, processor, device = bundle
    caption = _build_caption(req)
    try:
        import torch

        with torch.no_grad():
            inputs = processor(
                text=[caption], images=imgs,
                return_tensors="pt", padding=True, truncation=True,
            ).to(device)
            out = model(**inputs)
            img_emb = out.image_embeds / out.image_embeds.norm(dim=-1, keepdim=True)
            txt_emb = out.text_embeds / out.text_embeds.norm(dim=-1, keepdim=True)
            sims = (img_emb @ txt_emb.T).squeeze(-1)
            return round(float(sims.mean().item()), 4)
    except Exception as e:
        print(f"[scoring] clip_score 실패: {e}", flush=True)
        return None


# ── 배치 텐서 변환 ───────────────────────────────────────────────────────
def _to_batch_tensor(imgs: list, device: str):
    """PIL 이미지 리스트 -> 단일 배치 텐서 (N, 3, H, W), float32 [0.0, 1.0]."""
    import torch
    import numpy as np

    tensors = []
    for im in imgs:
        rgb_img = im.convert("RGB")
        arr = np.asarray(rgb_img, dtype="float32") / 255.0
        # (H, W, C) -> (C, H, W)
        t = torch.from_numpy(arr).permute(2, 0, 1)
        tensors.append(t)

    # (N, C, H, W) 형태로 병합 후 지정된 장치(GPU/CPU)로 전송
    return torch.stack(tensors).to(device)


def brisque_score(images: Any) -> float | None:
    """생성 이미지들의 평균 BRISQUE(무참조 화질) 배치 연산 버전. 값이 '낮을수록' 화질 좋음."""
    imgs = _iter_images(images)
    if not imgs:
        return None
    try:
        import torch
        import piq

        bundle = _get_clip()
        device = bundle[2] if (bundle and isinstance(bundle, tuple)) else ("cuda" if torch.cuda.is_available() else "cpu")
    except Exception as e:
        print(f"[scoring] BRISQUE 비활성화(piq/torch 로드 실패): {e}", flush=True)
        return None

    try:
        with torch.no_grad():
            # 1. N장 이미지 전체를 하나의 배치 텐서 (N, 3, H, W)로 변환
            batch_x = _to_batch_tensor(imgs, device)
            
            # 2. 루프 없이 단 1회의 텐서 연산으로 전체 이미지 BRISQUE 동시 계산
            scores_tensor = piq.brisque(batch_x, data_range=1.0)
            
            # 3. 단일 이미지 또는 여러 이미지에 대해 평균값 추출
            if scores_tensor.ndim == 0:
                mean_score = float(scores_tensor.item())
            else:
                mean_score = float(scores_tensor.mean().item())

            return round(mean_score, 3)

    except Exception as e:
        print(f"[scoring] brisque 배치 연산 실패 원인: {e}", flush=True)
        return None


# ── 진입점 ──────────────────────────────────────────────────────────────
def score_images(images: Any, req: dict | None = None) -> dict:
    imgs = _iter_images(images)
    return {
        "clip": clip_score(imgs, req),
        "brisque": brisque_score(imgs),
        "n_images": len(imgs),
    }


# ── Langfuse 트레이스에 점수 첨부 ────────────────────────
from baseline.observability import observe, flush

def attach_scores_to_langfuse(scores: dict) -> bool:
    """현재 실행 중인 Langfuse Trace에 CLIP/BRISQUE 점수를 안전하게 매핑합니다."""
    if not scores:
        return False
        
    items = [(k, float(v)) for k, v in scores.items() 
             if k in ("clip", "brisque") and isinstance(v, (int, float))]
    
    if not items:
        return False

    # 1. observability 모듈의 langfuse 객체 직접 활용
    try:
        from baseline.observability import langfuse
        if langfuse and hasattr(langfuse, "score"):
            for name, val in items:
                langfuse.score(name=name, value=val, comment="Automated Quality Score")
            print(f"[scoring] langfuse.score() 점수 전송 성공! {items}", flush=True)
            return True
    except Exception as e:
        print(f"[scoring] langfuse.score 매핑 실패: {e}", flush=True)

    # 2. observe 데코레이터 맥락 활용 (Alternative)
    try:
        import langfuse
        client = langfuse.Langfuse()
        for name, val in items:
            client.score(name=name, value=val)
        print(f"[scoring] Langfuse SDK 직접 전송 성공! {items}", flush=True)
        return True
    except Exception as e:
        print(f"[scoring] Langfuse SDK 점수 전송 실패: {e}", flush=True)

    return False