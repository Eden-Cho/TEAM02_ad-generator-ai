"""image_spec -> PIL 이미지. GPT-Image 호출.  [image_generator: 팀원 고도화 대상]

- mode="edit" + 제품사진 -> 플랫폼 비율 전처리 후 images.edit (제품 보존)
    - mask 전달 시: 배경만 재생성하고 제품 픽셀은 보존 (bg_remover와 연결)
- 그 외 -> images.generate (text-to-image)
"""
import base64
import io

from openai import OpenAI
from PIL import Image

import baseline.config as config
from baseline.preprocess import fit_to_ratio, parse_size

_client = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _png_upload(img: Image.Image, name: str):
    """PIL 이미지를 OpenAI 업로드용 PNG 파일 객체로."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.name = name
    buf.seek(0)
    return buf


def _decode(resp) -> Image.Image:
    d = resp.data[0]
    b64 = getattr(d, "b64_json", None)
    if b64:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    raise RuntimeError(f"이미지 응답에 b64_json이 없습니다: {d}")


def generate_image(spec: dict, product_image_path: str | None = None,
                   size: str | None = None,
                   mask: Image.Image | None = None) -> Image.Image:
    """spec 대로 이미지 생성.

    mask: (선택) bg_remover.make_edit_mask() 결과. 주면 제품 보존 정밀도가 올라감.
    """
    mode = spec.get("mode", "t2i")
    prompt = spec["prompt"]
    size = size or config.IMAGE_SIZE

    if mode == "edit" and product_image_path:
        w, h = parse_size(size)
        fitted = fit_to_ratio(Image.open(product_image_path), w, h)

        edit_prompt = (
            "Keep the product from the input image exactly as it is "
            "(same shape, color, proportions, details). "
            "Replace only the surrounding background and scene with: " + prompt
        )
        kwargs = dict(
            model=config.IMAGE_MODEL,
            image=_png_upload(fitted, "product.png"),
            prompt=edit_prompt,
            size=size,
        )
        if mask is not None:
            # 마스크도 동일 크기로 맞춰 전달 (투명=배경=편집영역)
            kwargs["mask"] = _png_upload(mask.resize((w, h)).convert("RGBA"),
                                         "mask.png")
        resp = client().images.edit(**kwargs)
    else:
        resp = client().images.generate(
            model=config.IMAGE_MODEL,
            prompt=prompt,
            size=size,
        )
    return _decode(resp)
