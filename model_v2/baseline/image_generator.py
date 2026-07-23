"""image_spec -> PIL 이미지. GPT-Image 호출.  [image_generator: 팀원 고도화 대상]

- mode="edit" + 제품사진 -> 플랫폼 비율 전처리 후 images.edit (제품 보존)
    - mask 전달 시: 배경만 재생성하고 제품 픽셀은 보존 (bg_remover와 연결)
- 그 외 -> images.generate (text-to-image)
"""
import base64
import contextvars
import io
import time

from openai import OpenAI
from PIL import Image

import baseline.config as config
from baseline.image_plan import ImageApiAttempt, sha256_of
from baseline.observability import observe
from baseline.preprocess import fit_to_ratio, parse_size

_client = None

# ── 이미지 API 시도 회계 ──────────────────────────────────────────
# generate_image_v2가 실제 images.generate/edit를 호출한 지점에서만 1건씩 기록한다.
# 성공·API 실패 모두 기록하고, 로컬 실패(경로·누끼)·passthrough는 0건이다.
# reset_image_attempts()를 호출하지 않으면 기록하지 않는다(노트북·CLI 안전).
_attempts: contextvars.ContextVar = contextvars.ContextVar("image_attempts", default=None)


def reset_image_attempts() -> None:
    """플랜 1건 실행 전에 호출 — 이후 시도를 새로 센다."""
    _attempts.set([])


def image_attempts() -> tuple:
    """reset 이후의 ImageApiAttempt들. reset 전이면 빈 튜플."""
    v = _attempts.get()
    return tuple(v) if v else ()


def _record_attempt(api: str, prompt: str, size: str, t0: float) -> None:
    v = _attempts.get()
    if v is not None:
        v.append(ImageApiAttempt(
            api=api, model=config.IMAGE_MODEL, size=size,
            prompt_sha256=sha256_of(prompt), prompt_len=len(prompt),
            milliseconds=int((time.perf_counter() - t0) * 1000)))


def client() -> OpenAI:
    global _client
    if _client is None:
        # max_retries=0: SDK 내부 자동 재시도를 끈다 — 회계(시도 1건)와 실제 네트워크
        # 시도 수를 일치시킨다. 재시도·폴백은 애플리케이션 정책이 단일 원본이다.
        _client = OpenAI(api_key=config.OPENAI_API_KEY, max_retries=0)
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


def _keep_clause(creativity: int) -> str:
    """창의성 단계별 제품 보존 강도 지시.

    1~2=엄격 보존(기존) · 3=각도·구도 자유(정체성 유지) · 4~5=대담한 재해석(참고용).
    """
    if creativity <= 2:
        return ("Keep the product from the input image exactly as it is "
                "(same shape, color, proportions, details). "
                "Replace only the surrounding background and scene with: ")
    if creativity == 3:
        return ("Keep the product's identity, colors, logo and key proportions clearly "
                "recognizable, but you MAY change the camera angle, composition, styling "
                "and background creatively for: ")
    return ("Use the input product as a reference for its identity and colors, but "
            "reimagine it in a fresh, striking scene with a new angle and bold, "
            "artistic composition: ")


@observe(name="generate_image")
def generate_image(spec: dict, product_image_path: str | None = None,
                   size: str | None = None,
                   mask: Image.Image | None = None,
                   creativity: int = 2, style: str = "",
                   scene: dict | None = None) -> Image.Image:
    """spec 대로 이미지 생성.

    mask: (선택) bg_remover.make_edit_mask() 결과. 주면 제품 보존 정밀도가 올라감.
    creativity: 1~5. 낮을수록 제품 보존, 높을수록 자유로운 재해석(정확도↓).
    """
    mode = spec.get("mode", "t2i")
    prompt = spec["prompt"]
    size = size or config.IMAGE_SIZE

    if mode == "edit" and product_image_path:
        w, h = parse_size(size)

        # 실제 사용 사진(usage)은 그대로 사용 — 이미 리치·자연·정확(생성/합성 안 함)
        if spec.get("source") == "usage":
            return Image.open(product_image_path).convert("RGB")

        fitted = fit_to_ratio(Image.open(product_image_path), w, h)

        # ── 컴포지팅 경로 (보존 모드, 창의성 ≤2) ──
        # 배경만 t2i로 생성 → 실제 제품 누끼를 합성 → 제품 픽셀 100% 보존.
        # (edit은 제품을 재합성해 비율이 어긋나므로, 제품 컷은 합성이 더 정확)
        if creativity <= 2:
            try:
                from baseline import bg_remover
                from composer import compositor
                cutout = bg_remover.cutout(Image.open(product_image_path))  # RGBA
                # 씬 템플릿이 주어지면 그것을 사용(검증된 씬 + 표면·크기 정합)
                if scene:
                    bg_resp = client().images.generate(
                        model=config.IMAGE_MODEL, prompt=scene["prompt"], size=size)
                    background = _decode(bg_resp)
                    return compositor.place_and_shadow(
                        background, cutout,
                        width_ratio=scene["product_scale"],
                        base_ratio=scene["surface_ratio"])

                # (폴백) 템플릿 없을 때 — 기존 하드코딩 배경
                _usage = spec.get("role") in ("lifestyle", "styling", "space", "serving")
                if _usage:
                    # 데스크 셋업(모니터·키보드 흐릿) → 제품이 실제 쓰이는 맥락처럼
                    bg_prompt = (
                        "a real desk workspace set up for use, straight-on front-facing camera angle, "
                        "a clear desk surface in the foreground where a device sits, with a computer "
                        "monitor, keyboard, mouse and tasteful desk accessories softly blurred behind, "
                        "shallow depth of field, warm natural office lighting, cohesive styling"
                        + (", " + style if style else "")
                        + ", no product in the foreground center, an empty spot on the desk for the "
                        "device, no text, no watermark")
                else:
                    # 정면(eye-level) 앵글 + 앞엔 제품 놓일 표면 + 뒤엔 흐릿한 소품(환경감)
                    bg_prompt = (
                        "front-facing product photography scene, straight-on eye-level camera angle, "
                        "a clean surface across the lower area where a product rests, "
                        "softly blurred tasteful decor behind (plants, books, warm minimal interior), "
                        "shallow depth of field, cohesive soft natural lighting, "
                        "a subtle soft shadow area on the surface"
                        + (", " + style if style else "")
                        + ", no product in the center, empty surface ready for a product, "
                        "no text, no watermark")
                bg_resp = client().images.generate(
                    model=config.IMAGE_MODEL, prompt=bg_prompt, size=size)
                background = _decode(bg_resp)
                return compositor.place_and_shadow(
                    background, cutout, role=spec.get("role"))
            except Exception:
                pass  # 누끼·배경 실패 → 아래 기존 edit(마스크) 경로로 폴백

        edit_prompt = _keep_clause(creativity) + prompt

        # 폴백/생성형 edit: 마스크로 제품 픽셀 보존, 배경만 재생성.
        # (마스크 없으면 edit이 전체를 재생성해 제품 비율·디테일이 어긋남)
        if mask is None and creativity <= 2:
            try:
                from baseline import bg_remover
                mask = bg_remover.make_edit_mask(fitted)   # 제품=불투명 / 배경=투명
            except Exception:
                mask = None   # rembg 미설치 등 → 마스크 없이 진행

        kwargs = dict(
            model=config.IMAGE_MODEL,
            image=_png_upload(fitted, "product.png"),
            prompt=edit_prompt,
            size=size,
        )
        if mask is not None:
            # 투명(배경)=편집영역 / 불투명(제품)=보존. 동일 크기로 맞춰 전달.
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


def _open_product(product_image_path: str | None, path: str) -> Image.Image:
    """제품 경로를 검증하고 연다. **유료 API보다 먼저** 호출된다.

    경로 누락은 ValueError, 파일 열기 실패는 PIL 예외 — 어느 쪽이든 이미지 API가
    호출되기 전에 터진다. client()에 손도 대기 전이라 배경만 유료로 새는 일이 없다.
    """
    if not product_image_path:
        raise ValueError(f"{path} 경로는 product_image_path가 필요하다.")
    return Image.open(product_image_path)


@observe(name="generate_image_v2")
def generate_image_v2(plan, product_image_path: str | None = None, *,
                      mask: Image.Image | None = None) -> Image.Image:
    """ImagePlan 하나를 실행한다. **프롬프트는 plan.prompt를 그대로 쓴다.**

    실행기는 프롬프트를 조립하지 않는다 — 보존 문구·스타일·금지문은 이미 build_image_plan이
    plan.prompt에 넣었다. 여기서 무엇을 덧붙이면 plan.prompt_sha256와 실제 프롬프트가
    어긋나 정합 검사가 무의미해진다. 그래서 어떤 경로에서도 API에 보내는 prompt는
    정확히 plan.prompt다. (프롬프트 원문은 로그로 출력하지 않는다.)

    이번 최소 연결에서는 composite 실패를 조용히 edit으로 강등하지 않고 예외를 그대로 올린다.

    **비용 안전 규칙(순서 고정):** 제품 이미지가 필요한 경로는 로컬 준비(경로 검증·열기·
    누끼·전처리)를 **전부 마친 뒤에만** 유료 API를 부른다. client() 접근조차 그 뒤다.
    그래야 제품 경로 오류·rembg 실패로 배경만 유료로 생성되는 낭비가 없다.
    """
    path = plan.intended_path
    size = plan.size or config.IMAGE_SIZE

    if path == "passthrough":
        # 실사용 사진 그대로 — 이미지 API 0회. 경로가 없으면 명확히 실패.
        return _open_product(product_image_path, "passthrough").convert("RGB")

    if path == "composite":
        from baseline import bg_remover
        from composer import compositor
        # ── 로컬 사전 준비 (유료 호출 전) — 순서: 검증 → 열기 → 누끼 ──
        product = _open_product(product_image_path, "composite")
        cutout = bg_remover.cutout(product)                          # RGBA 누끼
        # 여기까지 성공했을 때에만 배경을 유료로 생성한다. 실패해도 시도 1건은 기록
        # (원문·예외 메시지는 기록하지 않음 — ImageApiAttempt 계약 필드만).
        t0 = time.perf_counter()
        try:
            bg_resp = client().images.generate(
                model=config.IMAGE_MODEL, prompt=plan.prompt, size=size)
        finally:
            _record_attempt("images.generate", plan.prompt, size, t0)
        background = _decode(bg_resp)
        # 실제 합성 x좌표 = 배경 프롬프트에 지시한 것과 같은 plan.anchor_x_ratio.
        kwargs = dict(width_ratio=plan.width_ratio, base_ratio=plan.base_ratio,
                      anchor_x_ratio=plan.anchor_x_ratio)
        if plan.harmonize is not None:
            kwargs["harmonize"] = plan.harmonize
        if plan.shadow is not None:
            kwargs["shadow"] = plan.shadow
        return compositor.place_and_shadow(background, cutout, **kwargs)

    if path == "creative_edit":
        # ── 로컬 사전 준비 (유료 호출 전) — 검증 → 열기 → 전처리 ──
        product = _open_product(product_image_path, "creative_edit")
        w, h = parse_size(size)
        fitted = fit_to_ratio(product, w, h)
        kwargs = dict(model=config.IMAGE_MODEL,
                      image=_png_upload(fitted, "product.png"),
                      prompt=plan.prompt, size=size)
        if mask is not None:
            kwargs["mask"] = _png_upload(mask.resize((w, h)).convert("RGBA"), "mask.png")
        t0 = time.perf_counter()
        try:
            resp = client().images.edit(**kwargs)
        finally:
            _record_attempt("images.edit", plan.prompt, size, t0)
        return _decode(resp)

    if path == "t2i":
        # 입력 제품 이미지가 없다 — 제품 경로를 요구하지 않는다.
        t0 = time.perf_counter()
        try:
            resp = client().images.generate(
                model=config.IMAGE_MODEL, prompt=plan.prompt, size=size)
        finally:
            _record_attempt("images.generate", plan.prompt, size, t0)
        return _decode(resp)

    raise ValueError(f"알 수 없는 intended_path: {path!r}")
