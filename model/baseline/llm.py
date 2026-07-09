"""텍스트 LLM 클라이언트 — OpenAI 또는 Ollama 등 OpenAI-호환 엔드포인트.

기본은 config(.env) 값 사용. 노트북에서 configure()로 런타임 전환 가능.
- baseline_01: configure 안 함 → config 기본값 (OpenAI, gpt-5-mini)
- baseline_02: configure(base_url="http://localhost:11434/v1", model="gemma4:12b")
               → 로컬 Ollama

이미지(GPT-Image)는 baseline.image_generator가 별도로 OpenAI를 쓰므로 영향 없음.
"""
import time

from openai import OpenAI

import baseline.config as config
from baseline._json import parse_json

_client = None
_base_url = None   # None이면 config.TEXT_BASE_URL 사용
_model = None      # None이면 config.TEXT_MODEL 사용


def configure(base_url: str | None = None, model: str | None = None):
    """런타임 텍스트 백엔드 지정. base_url을 주면 그쪽(Ollama 등)을 사용."""
    global _client, _base_url, _model
    _base_url = base_url
    _model = model
    _client = None  # 다음 호출 때 재생성


def _effective_base() -> str | None:
    base = _base_url if _base_url is not None else config.TEXT_BASE_URL
    return base or None


def text_model() -> str:
    return _model or config.TEXT_MODEL


def text_client() -> OpenAI:
    global _client
    if _client is None:
        base = _effective_base()
        if base:  # Ollama 등 로컬 엔드포인트 (api_key는 형식상 필요)
            _client = OpenAI(base_url=base, api_key=config.OPENAI_API_KEY or "ollama")
        else:     # OpenAI
            _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def chat_json(system: str, user: str, retries: int = 3) -> dict:
    """JSON 응답 chat — JSON 강제(A) + 관대한 파싱·재시도(B). 로컬 LLM의 간헐적 깨짐/빈응답 방어.

    - response_format으로 JSON 강제 (A)
    - parse_json이 코드펜스·주변텍스트·트레일링콤마 복구 (B)
    - 빈 응답·파싱 실패 시 재시도 (B). temperature는 건드리지 않음 — 기본값은 비결정적이라
      재시도할 때마다 다른(정상) 출력이 나옴. (temp=0으로 고정하면 빈응답이 그대로 반복됨)
    """
    is_local = _effective_base() is not None
    last = None
    for attempt in range(retries + 1):
        hint = "" if attempt == 0 else "\n\n(중요: 설명·코드펜스 없이 유효한 JSON만 출력하세요.)"
        kwargs = dict(
            model=text_model(),
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user + hint}],
            response_format={"type": "json_object"},
        )
        if is_local:   # Ollama num_predict — 긴 출력 잘림(truncation) 방지
            kwargs["max_tokens"] = 2048
        try:
            resp = text_client().chat.completions.create(**kwargs)
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("빈 응답")
            return parse_json(content)
        except Exception as e:   # 빈 응답 / API 오류 / JSON 파싱 실패 → 재시도
            last = e
            if "connect" in str(e).lower():   # 연결 오류는 재시도해도 소용 X → 즉시 안내
                raise ConnectionError(
                    "텍스트 LLM 서버에 연결 실패. Ollama 서버 실행을 확인하세요: "
                    "`brew services start ollama` 또는 `ollama serve`") from e
            if attempt < retries:   # 빈 응답(모델 로딩 중)·일시 오류 → 점진 대기 후 재시도
                time.sleep(2 * (attempt + 1))
    raise ValueError(f"chat_json: {retries + 1}회 실패 — {last}")
