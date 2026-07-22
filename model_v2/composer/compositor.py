"""제품 컷 컴포지팅 — 생성한 배경 위에 '실제 제품 누끼'를 합성.

핵심: 제품을 생성(재합성)하지 않고 원본 픽셀을 그대로 얹어 보존한다.
배경만 t2i로 생성 → 누끼(RGBA)를 배치 → 접지 그림자로 지면에 고정한다.

그림자는 접촉(contact)·앰비언트(ambient) 두 겹으로 나눈다. 실제 물체는 닿는
지점이 가장 어둡고 멀어질수록 밝아지므로, 최암부가 접촉선을 벗어나면 제품이
바닥 얼룩 위에 떠 보인다. 단일 타원 그림자가 '붕 뜬 느낌'을 만들던 원인.
"""
from PIL import Image, ImageChops, ImageFilter, ImageStat

# 역할별 배치(폭 비율, 바닥선 비율). 바닥선은 배경의 '하단 1/3 표면'에 맞춰 ~0.80으로 통일
# → 제품이 표면에 놓인 느낌. 빈 공간·부유감을 줄이려 폭도 키움.
_PLACEMENT = {
    "hero":         (0.66, 0.82),
    "build":        (0.60, 0.80),
    "connectivity": (0.66, 0.81),
    "detail":       (0.58, 0.80),
    "spec":         (0.58, 0.80),
    # usage(사용장면) — 살짝 작게(맥락 여백) 하되 너무 작지 않게
    "lifestyle":    (0.50, 0.80),
    "styling":      (0.50, 0.80),
    "space":        (0.48, 0.80),
    "serving":      (0.52, 0.80),
}

_ALPHA_FLOOR = 16       # 이 값 이하는 rembg 잔여 노이즈로 보고 버린다


def _trim_alpha(rgba: Image.Image) -> Image.Image:
    """투명 여백을 잘라 제품 bbox만 남긴다.

    getbbox()를 알파>0으로 그냥 쓰면 rembg가 남긴 희미한 잔여 픽셀까지 제품으로
    쳐서 bbox가 커진다. 바닥선 정렬이 그 bbox 하단 기준이므로, 잔여 픽셀 한 점이
    제품을 실제보다 위에 띄운다. → 문턱값을 넘긴 알파로만 bbox를 잡는다.
    """
    rgba = rgba.convert("RGBA")
    solid = rgba.getchannel("A").point(lambda v: 255 if v > _ALPHA_FLOOR else 0)
    bbox = solid.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def _refine_edge(rgba: Image.Image, feather: float = 0.6) -> Image.Image:
    """알파 경계를 1px 깎고 페더 → 누끼 테두리(halo) 제거.

    rembg 경계 픽셀의 RGB는 제품색과 '원본 촬영' 배경색이 섞인 값이다. 새 배경에
    얹으면 그 띠가 회색 윤곽선으로 남아 오려붙인 티가 난다. 경계를 알파에서 빼는
    게 가장 확실하다. 축소 리샘플이 프린지를 최종 해상도의 ~1px로 뭉치므로,
    리사이즈 뒤에 깎아야 실제로 지워진다.
    """
    a = rgba.getchannel("A").filter(ImageFilter.MinFilter(3))   # 1px 침식
    if feather:
        a = a.filter(ImageFilter.GaussianBlur(feather))         # 계단현상 완화
    out = rgba.copy()
    out.putalpha(a)
    return out


def _light_dx(bg: Image.Image, baseline: int) -> float:
    """배경 좌우 밝기차로 광원 방향 추정 → 그림자가 누울 방향(-1 왼쪽 ~ +1 오른쪽).

    빛이 왼쪽에서 오면 그림자는 오른쪽으로 눕는다. 배경은 매번 새로 생성되므로
    조명 방향을 상수로 둘 수 없다 — 정중앙 대칭 그림자가 부자연스러웠던 이유.
    """
    W, _ = bg.size
    top = bg.convert("L").crop((0, 0, W, max(1, int(baseline * 0.75))))
    third = max(1, W // 3)
    left = ImageStat.Stat(top.crop((0, 0, third, top.height))).mean[0]
    right = ImageStat.Stat(top.crop((W - third, 0, W, top.height))).mean[0]
    return max(-1.0, min(1.0, (left - right) / 40.0))    # 밝기차 40 => 최대 편향


def _surface_rgb(bg: Image.Image, baseline: int) -> tuple[float, float, float]:
    """접촉선 바로 아래 표면 띠의 평균 RGB — 그림자 색·세기의 근거."""
    W, H = bg.size
    y0 = min(H - 1, baseline + 2)
    y1 = min(H, y0 + max(4, int(H * 0.04)))
    return tuple(ImageStat.Stat(bg.convert("RGB").crop((0, y0, W, y1))).mean[:3])


def _shadow_color(surf: tuple[float, float, float]) -> tuple[int, int, int]:
    """그림자 색 — 표면색을 어둡게. 순수 검정은 표면에서 뜬다."""
    return tuple(int(c * 0.30) for c in surf)


def _auto_shadow(surf: tuple[float, float, float]) -> float:
    """표면 밝기로 그림자 진하기 산출 — 씬마다 배경이 새로 생성되므로 상수로 못 둔다.

    어두운 표면에 진한 그림자를 얹으면 형태를 잃은 검은 뭉치가 되고, 밝은 표면은
    그림자를 받을 여지가 커 같은 세기로도 접지가 또렷하다. → 밝을수록 진하게.
    """
    lum = 0.299 * surf[0] + 0.587 * surf[1] + 0.114 * surf[2]
    return max(0.85, min(1.8, 0.7 + lum / 255 * 0.95))


def _shadow_alpha(size: tuple[int, int], alpha: Image.Image,
                  cx: int, baseline: int, dx: float, strength: float) -> Image.Image:
    """접촉 + 앰비언트 2겹 그림자의 알파 맵.

    alpha: 배치될 최종 크기의 제품 알파 (실루엣·접지 폭의 근거)
    """
    W, H = size
    nw, nh = alpha.size

    def _scale(v_max: float):
        return lambda v: min(255, int(v * v_max * strength))

    # ── 앰비언트: 전체 실루엣을 바닥으로 눌러 넓고 옅게, 광원 반대로 눕힌다.
    amb_h = max(6, int(nh * 0.10))
    amb_w = max(2, int(nw * 1.06))
    amb = alpha.resize((amb_w, amb_h), Image.LANCZOS).point(_scale(0.34))
    layer = Image.new("L", (W, H), 0)
    layer.paste(amb, (cx - amb_w // 2 + int(dx * nw * 0.10),
                      baseline - int(amb_h * 0.30)), amb)
    layer = layer.filter(ImageFilter.GaussianBlur(max(6, int(nw * 0.045))))

    # ── 접촉: 실제 닿는 하단 밴드만 → 접지 폭이 제품 최대폭이 아니라 밑면을 따른다.
    #    (아래로 좁아지는 제품은 최대폭 그림자가 양옆으로 삐져나와 얼룩이 된다)
    band_h = max(1, int(nh * 0.05))
    band = alpha.crop((0, nh - band_h, nw, nh))
    con_h = max(3, int(nh * 0.018))
    con = band.resize((nw, con_h), Image.LANCZOS).point(_scale(0.78))
    con_layer = Image.new("L", (W, H), 0)
    con_layer.paste(con, (cx - nw // 2, baseline - con_h // 2), con)   # 접촉선에 정렬
    con_layer = con_layer.filter(ImageFilter.GaussianBlur(max(1.5, nw * 0.006)))

    # max 합성 — 겹치는 접촉선에서 진한 쪽(접촉)이 이겨 최암부가 접촉선에 온다.
    return ImageChops.lighter(layer, con_layer)


def _harmonize(prod: Image.Image, bg: Image.Image, strength: float) -> Image.Image:
    """배경의 색온도로 제품을 약하게 끌어당긴다.

    누끼는 원본 촬영의 화이트밸런스를 그대로 갖고 있어, 색온도가 다른 배경에
    얹으면 분리돼 보인다. 강하면 제품색 자체가 바뀌므로 게인을 좁게 제한한다.
    """
    if strength <= 0:
        return prod
    a = prod.getchannel("A")
    rgb = prod.convert("RGB")
    ref = ImageStat.Stat(bg.convert("RGB")).mean[:3]
    cur = ImageStat.Stat(rgb, mask=a).mean[:3]

    lut: list[int] = []
    for i in range(3):
        gain = 1.0 + (ref[i] / max(cur[i], 1e-3) - 1.0) * strength
        gain = max(0.88, min(1.14, gain))       # 제품색이 바뀔 만큼은 절대 안 움직임
        lut.extend(min(255, int(v * gain)) for v in range(256))

    out = rgb.point(lut).convert("RGBA")
    out.putalpha(a)
    return out


def place_and_shadow(background: Image.Image, cutout_rgba: Image.Image,
                     role: str | None = None,
                     width_ratio: float = 0.6, base_ratio: float = 0.78,
                     harmonize: float = 0.12, shadow: float | None = None,
                     anchor_x_ratio: float = 0.5) -> Image.Image:
    """배경 위에 제품 누끼를 배치 + 접지 그림자.

    role         : 있으면 역할별 배치 프리셋 적용(컷마다 크기·위치 변화)
    width_ratio  : 제품 폭 / 배경 폭
    base_ratio   : 제품 바닥이 놓일 세로 위치 비율
    harmonize    : 배경 색온도로 제품을 끌어당기는 세기(0=끔, 제품 픽셀 완전 보존)
    shadow       : 접지 그림자 진하기 배수. None=표면 밝기로 자동 산출
    anchor_x_ratio: 제품 중심의 정규화 x(0~1). **기본 0.5는 기존 중앙 배치와 동일**
                    (int(W*0.5)==W//2). 제품이 잘리지 않게 반폭 기준으로 clamp한다.
                    그림자와 제품은 같은 cx를 쓴다. 제품은 회전·왜곡하지 않는다.
    """
    if role in _PLACEMENT:
        width_ratio, base_ratio = _PLACEMENT[role]
    bg = background.convert("RGBA")
    W, H = bg.size

    prod = _trim_alpha(cutout_rgba)
    # 스케일 — 폭 기준, 높이도 배경의 55%로 제한
    scale = (W * width_ratio) / prod.width
    max_h = H * 0.55
    if prod.height * scale > max_h:
        scale = max_h / prod.height
    nw, nh = max(1, int(prod.width * scale)), max(1, int(prod.height * scale))
    prod = _refine_edge(prod.resize((nw, nh), Image.LANCZOS))
    prod = _harmonize(prod, bg, harmonize)

    # 정규화 x비율 → 픽셀 중심. int(W*0.5)==W//2라 기본값은 기존 중앙과 바이트 동일하다.
    # 제품은 x = cx - (nw//2)에서 시작하므로 좌우 반폭이 비대칭이다(홀수 폭). 오른쪽 반폭을
    # 왼쪽과 같은 nw//2로 잡으면 홀수 폭에서 오른쪽 1px가 잘린다 → 좌우 extent를 분리한다.
    left_extent = nw // 2
    right_extent = nw - left_extent           # 홀수면 right가 1px 크다
    if nw < W:
        cx = max(left_extent, min(W - right_extent, int(W * anchor_x_ratio)))
    else:
        cx = W // 2                           # 제품이 캔버스보다 넓으면 중앙
    baseline = int(H * base_ratio)      # 제품이 '놓이는' 바닥선
    x, y = cx - left_extent, baseline - nh

    dx = _light_dx(bg, baseline)
    surf = _surface_rgb(bg, baseline)
    if shadow is None:
        shadow = _auto_shadow(surf)
    layer = Image.new("RGBA", (W, H), _shadow_color(surf) + (0,))
    layer.putalpha(_shadow_alpha((W, H), prod.getchannel("A"), cx, baseline, dx, shadow))
    bg = Image.alpha_composite(bg, layer)

    # 실제 제품 픽셀 합성 (보존)
    bg.alpha_composite(prod, (x, y))
    return bg.convert("RGB")
