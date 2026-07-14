"""텍스트 LLM 클라이언트 — OpenAI 또는 Ollama 등 OpenAI-호환 엔드포인트.

기본은 config(.env) 값 사용. 노트북에서 configure()로 런타임 전환 가능.
- baseline_01: configure 안 함 → config 기본값 (OpenAI, gpt-5-mini)
- baseline_02: configure(base_url="http://localhost:11434/v1", model="gemma4:12b")
               → 로컬 Ollama

이미지(GPT-Image)는 baseline.image_generator가 별도로 OpenAI를 쓰므로 영향 없음.
"""
import time

from openai import OpenAI
from langchain_openai import ChatOpenAI

import baseline.config as config
from baseline._json import parse_json
from baseline.observability import langchain_handler

_client = None
_base_url = None   # None이면 config.TEXT_BASE_URL 사용
_model = None      # None이면 config.TEXT_MODEL 사용
_chat = None       # LangChain ChatOpenAI 캐시


def configure(base_url: str | None = None, model: str | None = None):
    """런타임 텍스트 백엔드 지정. base_url을 주면 그쪽(Ollama 등)을 사용."""
    global _client, _base_url, _model, _chat
    _base_url = base_url
    _model = model
    _client = None  # 다음 호출 때 재생성
    _chat = None


def _effective_base() -> str | None:
    base = _base_url if _base_url is not None else config.TEXT_BASE_URL
    return base or None


def text_model() -> str:
    return _model or config.TEXT_MODEL


def text_client() -> OpenAI:
    """raw OpenAI 클라이언트 (하위호환 — 노트북 등 직접 호출용)."""
    global _client
    if _client is None:
        base = _effective_base()
        if base:  # Ollama 등 로컬 엔드포인트 (api_key는 형식상 필요)
            _client = OpenAI(base_url=base, api_key=config.OPENAI_API_KEY or "ollama")
        else:     # OpenAI
            _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _chat_model() -> ChatOpenAI:
    """LangChain ChatOpenAI (base_url·model 반영, 캐시). Ollama는 base_url로 지원."""
    global _chat
    if _chat is None:
        base = _effective_base()
        kwargs = dict(model=text_model(), temperature=1,
                      api_key=config.OPENAI_API_KEY or "ollama")
        if base:
            kwargs["base_url"] = base
        _chat = ChatOpenAI(**kwargs)
    return _chat


def chat_json(system: str, user: str, retries: int = 3) -> dict:
    """JSON 응답 chat — LangChain(ChatOpenAI) 호출 + LangFuse 추적. 계약은 동일.

    - response_format으로 JSON 강제 (A)
    - parse_json이 코드펜스·주변텍스트·트레일링콤마 복구 (B)
    - 빈 응답·파싱 실패 시 재시도 (B). temperature는 기본값(비결정적) 유지 — 재시도마다
      다른(정상) 출력이 나오게. LangFuse 키가 있으면 각 호출이 자동 추적됨.
    """
    is_local = _effective_base() is not None
    handler = langchain_handler()
    invoke_cfg = {"callbacks": [handler]} if handler else {}
    last = None
    for attempt in range(retries + 1):
        hint = "" if attempt == 0 else "\n\n(중요: 설명·코드펜스 없이 유효한 JSON만 출력하세요.)"
        bind = {"response_format": {"type": "json_object"}}
        if is_local:   # Ollama num_predict — 긴 출력 잘림(truncation) 방지
            bind["max_tokens"] = 2048
        try:
            resp = _chat_model().bind(**bind).invoke(
                [("system", system), ("human", user + hint)],
                config=invoke_cfg,
            )
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            content = content.strip()
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
