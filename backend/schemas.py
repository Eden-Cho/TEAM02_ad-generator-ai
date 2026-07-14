"""요청/응답 규격 (Pydantic)."""
from typing import Any, Dict, List

from pydantic import BaseModel


class GenerateResponse(BaseModel):
    detail_page: str        # 상세이미지 (base64 PNG)
    main: str               # 메인 썸네일 (base64 JPG)
    gallery: List[str]      # 부가 썸네일들 (base64 JPG)
    seconds: float          # 생성 소요시간
    # --- GEO 텍스트 레이어 (AI 검색용 부가 산출물) ---
    geo_html: str = ""                              # 시맨틱 HTML(JSON-LD 임베드)
    structured_data: List[Dict[str, Any]] = []      # Product / FAQPage JSON-LD
    faq: List[Dict[str, str]] = []                  # 자주 묻는 질문
    warnings: List[str] = []                        # 사실 가드레일 경고
