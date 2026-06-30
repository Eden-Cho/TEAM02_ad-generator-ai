from pydantic import BaseModel
from typing import List, Optional

# 이미지 생성 요청 규격
class AdRequest(BaseModel):
    prompt: str
    steps: int = 25