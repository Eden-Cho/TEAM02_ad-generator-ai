"""composer 데모 — 실제/더미 이미지로 긴 상세페이지 생성 테스트.

실행: python -m composer.demo         (다크)
      python -m composer.demo light   (라이트)
"""
import sys

from PIL import Image

import baseline.config as config
from composer.layout import compose
from composer.theme import get_theme


def _sample_image():
    p = config.find_product_image()
    return str(p) if p else Image.new("RGB", (1024, 1024), (44, 44, 52))


def build_sample_blocks(img) -> list[dict]:
    return [
        {"type": "hero", "image": img,
         "headline": "손바닥 위의 데스크톱", "sub": "M4의 압도적 성능"},
        {"type": "feature", "image": img,
         "headline": "어디에나 어울리는 디자인", "sub": "미니멀한 알루미늄 바디",
         "points": ["12.7cm 정사각", "0.67kg 초경량", "무소음 설계"]},
        {"type": "text",
         "headline": "필요한 모든 연결", "sub": "Thunderbolt 4 x3 · HDMI · 10Gb 이더넷"},
        {"type": "spec_table", "title": "제품 사양",
         "rows": [("칩", "M4 (10코어 CPU/GPU)"), ("메모리", "16GB 통합"),
                  ("저장장치", "512GB SSD"), ("크기", "12.7 x 12.7 x 5 cm"),
                  ("무게", "0.67kg")]},
        {"type": "divider"},
        {"type": "cta", "text": "지금 만나보세요"},
    ]


def main(theme_name: str = "dark"):
    img = _sample_image()
    page = compose(build_sample_blocks(img), get_theme(theme_name))
    out = config.OUTPUT_DIR / f"page_demo_{theme_name}.png"
    page.save(out)
    print(f"저장: {out}  크기 {page.size}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dark")
