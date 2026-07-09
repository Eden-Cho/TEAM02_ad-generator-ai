"""GPT 응답에서 JSON을 안전하게 파싱하는 헬퍼."""
import json
import re


def parse_json(text: str) -> dict:
    """코드펜스·주변 텍스트·트레일링 콤마가 섞여도 최대한 JSON을 복구해 파싱한다."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # {…} 구간만 추출 + 트레일링 콤마 제거로 복구 시도
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        snippet = re.sub(r",(\s*[}\]])", r"\1", m.group(0))
        return json.loads(snippet)
