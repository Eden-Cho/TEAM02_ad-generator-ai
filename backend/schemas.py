"""요청/응답 규격 (Pydantic)."""
from typing import List

from pydantic import BaseModel


class GenerateResponse(BaseModel):
    detail_page: str        # 상세이미지 (base64 PNG)
    main: str               # 메인 썸네일 (base64 JPG)
    gallery: List[str]      # 부가 썸네일들 (base64 JPG)
    seconds: float          # 생성 소요시간
