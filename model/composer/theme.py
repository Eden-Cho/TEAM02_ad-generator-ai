"""상세페이지 디자인 시스템 — 테마(색)와 타이포 계층.

composer의 모든 블록이 이 Theme을 참조해 색·폰트·여백을 통일한다.
"""
from dataclasses import dataclass, replace

import baseline.config as config


@dataclass
class Theme:
    name: str = "dark"
    page_width: int = 1080     # 상세페이지 폭 (px)
    margin: int = 80           # 좌우 여백

    # 색상 (RGB)
    bg: tuple = (0, 0, 0)
    text: tuple = (255, 255, 255)
    sub: tuple = (195, 195, 195)
    muted: tuple = (120, 120, 120)
    accent: tuple = (10, 132, 255)

    # 폰트
    font_path: str = config.FONT_PATH
    h1: int = 66               # 대헤드라인
    h2: int = 44               # 소제목
    body: int = 30             # 본문
    caption: int = 24          # 캡션/불릿


DARK = Theme(name="dark", bg=(0, 0, 0), text=(255, 255, 255),
             sub=(195, 195, 195), muted=(120, 120, 120))

LIGHT = Theme(name="light", bg=(255, 255, 255), text=(24, 24, 24),
              sub=(90, 90, 90), muted=(160, 160, 160))


import os

def get_theme(name: str = "dark", page_width: int | None = None) -> Theme:
    theme = LIGHT if name == "light" else DARK
    
    # 호출되는 순간 실제 환경 변수(도커 리눅스 나눔폰트)가 있으면 
    # 기존 맥 경로를 무시하고 온전하게 새 경로를 복사해서 전달.
    current_font = os.getenv("FONT_PATH", theme.font_path)
    theme = replace(theme, font_path=current_font)
    
    if page_width:   # 사이트별 상세폭 오버라이드
        theme = replace(theme, page_width=page_width)
    return theme
