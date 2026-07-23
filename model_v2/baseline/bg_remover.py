"""제품 배경 제거 → GPT-Image edit용 마스크 생성.  [팀원 담당 baseline]

목적: 지금 edit이 제품을 재해석해 모양이 바뀌는 문제(예: 맥미니→일반 박스)를,
      "제품은 보존 / 배경만 재생성"하는 마스크로 해결한다.

GPT-Image edit 규칙: 마스크에서 **알파가 투명(0)인 영역이 편집(재생성) 대상**.
 → 제품=불투명(보존), 배경=투명(재생성) 이 되도록 만든다.
 → rembg 출력(제품 불투명 / 배경 투명)이 이 조건을 그대로 만족한다.

TODO(팀원):
 - rembg(u2net) → SAM2 등으로 경계 정밀도 개선
 - 반사체/투명/의류 등 제품 유형별 품질 비교 (연구 항목)
 - 마스크 가장자리 feather(블러)로 합성 자연스럽게
"""
from PIL import Image

_session = None


def _load():
    """rembg 세션 지연 로드 (미설치여도 import는 되게)."""
    global _session
    if _session is None:
        try:
            from rembg import new_session, remove
        except ImportError as e:
            raise ImportError(
                "rembg가 필요합니다. `pip install rembg` 후 다시 실행하세요."
            ) from e
        _session = (new_session(), remove)
    return _session


def cutout(image: Image.Image) -> Image.Image:
    """배경이 제거된 RGBA (제품=불투명, 배경=투명)."""
    session, remove = _load()
    return remove(image.convert("RGBA"), session=session)


def make_edit_mask(image: Image.Image) -> Image.Image:
    """GPT-Image edit용 마스크 (RGBA). 배경=투명(편집), 제품=불투명(보존).

    cutout 결과의 알파가 곧 편집 마스크이므로 그대로 사용한다.
    """
    return cutout(image)


def mask_preview(rgba: Image.Image) -> Image.Image:
    """노트북 확인용: 마스크(알파)를 흑백으로 시각화 (제품=흰색)."""
    return rgba.convert("RGBA").getchannel("A").convert("RGB")
