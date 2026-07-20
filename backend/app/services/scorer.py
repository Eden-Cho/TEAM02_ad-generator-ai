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
    """req에서 CLIP용 캡션을 조립한다(CLIP 토큰 77 한도라 짧고 핵심만).

    정렬(alignment)을 재는 거라, '생성 이미지가 이 상품 설명과 얼마나 맞는지'를
    나타내는 자연스러운 한 문장
    """
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
    return caption[:300]  # 프로세서가 어차피 자르지만 방어적으로 컷


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
        except Exception as e:  # 미설치·다운로드 실패 등 → 비활성화
            print(f"[scoring] CLIP 비활성화: {e}", flush=True)
            _clip_bundle = False
    return _clip_bundle


def clip_score(images: Any, req: dict | None) -> float | None:
    """생성 이미지들과 상품 설명(caption)의 평균 CLIP 코사인 유사도.

    반환: 대략 -1~1 (매칭되는 이미지는 보통 0.2~0.35). 값이 클수록 정렬↑.
          이미지 없음/CLIP 비활성이면 None.
    """
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
            sims = (img_emb @ txt_emb.T).squeeze(-1)  # [n_images]
            return round(float(sims.mean().item()), 4)
    except Exception as e:
        print(f"[scoring] clip_score 실패: {e}", flush=True)
        return None


def _to_tensor(pil_img):
    """PIL → torch 텐서 (1,3,H,W), [0,1]. piq.brisque 입력 규격."""
    import torch
    import numpy as np

    arr = np.asarray(pil_img.convert("RGB"), dtype="float32") / 255.0
    return torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)


def brisque_score(images: Any) -> float | None:
    """생성 이미지들의 평균 BRISQUE(무참조 화질). 값이 '낮을수록' 화질 좋음.

    반환: 대략 0~100. 이미지 없음/piq 미설치면 None.
    """
    imgs = _iter_images(images)
    if not imgs:
        return None
    try:
        import torch
        import piq
    except Exception as e:
        print(f"[scoring] BRISQUE 비활성화(piq 미설치?): {e}", flush=True)
        return None

    vals = []
    for im in imgs:
        try:
            with torch.no_grad():
                x = _to_tensor(im)
                vals.append(float(piq.brisque(x, data_range=1.0).item()))
        except Exception as e:
            print(f"[scoring] brisque 개별 실패(스킵): {e}", flush=True)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 3)


# ── 한 방에 쓰는 진입점 ──────────────────────────────────────────────────
def score_images(images: Any, req: dict | None = None) -> dict:
    """CLIP + BRISQUE를 한 번에. 파이프라인에서 이거 하나만 부르면 된다.

    반환 예: {"clip": 0.284, "brisque": 23.11, "n_images": 4}
    (개별 지표는 계산 불가 시 None으로 담긴다 — 키는 항상 존재)
    """
    imgs = _iter_images(images)
    return {
        "clip": clip_score(imgs, req),
        "brisque": brisque_score(imgs),
        "n_images": len(imgs),
    }


# ── Langfuse 트레이스에 점수 첨부 (SDK 버전 관용) ────────────────────────
def attach_scores_to_langfuse(scores: dict) -> bool:
    """@observe로 열린 '현재 트레이스'에 점수를 첨부. 성공 시 True.

    langfuse v3 / v2 SDK를 모두 시도하고, 어느 쪽도 안 되면 조용히 no-op.
    (run_pipeline이 이미 @observe 안이라 '현재 트레이스'가 존재한다는 전제)
    """
    if not scores:
        return False
    items = [(k, v) for k, v in scores.items()
             if k in ("clip", "brisque") and isinstance(v, (int, float))]
    if not items:
        return False

    # v3: get_client().score_current_trace(name=, value=)
    try:
        from langfuse import get_client
        client = get_client()
        for name, value in items:
            client.score_current_trace(name=name, value=float(value))
        return True
    except Exception:
        pass

    # v2: langfuse.decorators.langfuse_context.score_current_trace(...)
    try:
        from langfuse.decorators import langfuse_context
        for name, value in items:
            langfuse_context.score_current_trace(name=name, value=float(value))
        return True
    except Exception:
        pass

    return False