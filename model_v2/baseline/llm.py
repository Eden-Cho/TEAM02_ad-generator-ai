"""텍스트 LLM 클라이언트 — OpenAI 또는 Ollama 등 OpenAI-호환 엔드포인트.

기본은 config(.env) 값 사용. 노트북에서 configure()로 런타임 전환 가능.
- baseline_01: configure 안 함 → config 기본값 (OpenAI, gpt-5-mini)
- baseline_02: configure(base_url="http://localhost:11434/v1", model="gemma4:12b")
               → 로컬 Ollama

이미지(GPT-Image)는 baseline.image_generator가 별도로 OpenAI를 쓰므로 영향 없음.
"""
import contextvars
import hashlib
import time

from openai import OpenAI
from langchain_openai import ChatOpenAI

import baseline.config as config
from baseline._json import parse_json
from baseline.observability import record_llm_attempt

# ── LLM 호출 회계 ────────────────────────────────────────────────
# 논리 호출(chat_json 1회)과 실제 API 시도를 분리해서 센다. chat_json은 내부에서
# 최대 retries+1회 재시도하고, generate_page_copy는 chat_json을 또 2회까지 부른다.
# → "LLM 1회"라는 말이 실제 비용과 전혀 맞지 않으므로 둘을 따로 기록한다.
# 페이지 단위 집계이므로 역할별이 아니라 PipelineTrace가 소비한다.
_accounting: contextvars.ContextVar = contextvars.ContextVar("llm_accounting", default=None)

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


def reset_accounting() -> None:
    """페이지 단위 회계 시작. 호출하지 않으면 집계하지 않는다(노트북·CLI 안전)."""
    _accounting.set({"logical_chat_calls": 0, "actual_api_attempts": 0})


def accounting() -> dict:
    """지금까지의 LLM 호출 회계. reset_accounting() 전이면 0."""
    v = _accounting.get()
    return dict(v) if v else {"logical_chat_calls": 0, "actual_api_attempts": 0}


def _bump(key: str) -> None:
    v = _accounting.get()
    if v is not None:
        v[key] += 1


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
        # max_retries=0: SDK 내부 자동 재시도를 끈다 — 켜져 있으면 actual_api_attempts
        # 집계(시도 전 _bump)가 실제 네트워크 시도 수와 어긋난다. 재시도 정책은
        # chat_json의 애플리케이션 루프(retries)가 단일 원본이다.
        kwargs = dict(model=text_model(), temperature=1, max_retries=0,
                      api_key=config.OPENAI_API_KEY or "ollama")
        if base:
            kwargs["base_url"] = base
        _chat = ChatOpenAI(**kwargs)
    return _chat


def _observe_attempt(t0: float, attempt: int, sha: str, plen: int) -> None:
    """시도 1건의 metadata 관측. 프롬프트 본문은 넘기지 않는다(해시·길이만).

    해시는 동일성 추적용이며 익명화가 아니다 — 근거는 observability.record_llm_attempt.
    """
    record_llm_attempt(
        model=text_model(),
        attempt=attempt + 1,                     # 1-based — 로그를 사람이 읽는다
        latency_ms=int((time.perf_counter() - t0) * 1000),
        prompt_sha256=sha,
        prompt_len=plen,
    )


def chat_json(system: str, user: str, retries: int = 3) -> dict:
    """JSON 응답 chat — LangChain(ChatOpenAI) 호출 + LangFuse 추적. 계약은 동일.

    - response_format으로 JSON 강제 (A)
    - parse_json이 코드펜스·주변텍스트·트레일링콤마 복구 (B)
    - 빈 응답·파싱 실패 시 재시도 (B). temperature는 기본값(비결정적) 유지 — 재시도마다
      다른(정상) 출력이 나오게.

    LangFuse 콜백은 부착하지 않는다 — 그 핸들러는 system/user 프롬프트 **본문**을
    전송한다. 관측은 시도별 metadata만 남긴다(observability.record_llm_attempt).
    """
    is_local = _effective_base() is not None
    _bump("logical_chat_calls")
    # 재시도 힌트는 고정 접미라 논리 프롬프트가 아니다 → 해시·길이는 원본 기준으로 한 번만.
    sha = hashlib.sha256(f"{system}\x00{user}".encode()).hexdigest()[:12]
    plen = len(system) + len(user)
    last = None
    for attempt in range(retries + 1):
        hint = "" if attempt == 0 else "\n\n(중요: 설명·코드펜스 없이 유효한 JSON만 출력하세요.)"
        bind = {"response_format": {"type": "json_object"}}
        if is_local:   # Ollama num_predict — 긴 출력 잘림(truncation) 방지
            bind["max_tokens"] = 2048
        _bump("actual_api_attempts")   # 실패도 비용이므로 시도 전에 센다
        t0 = time.perf_counter()
        try:
            resp = _chat_model().bind(**bind).invoke(
                [("system", system), ("human", user + hint)],
            )
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            content = content.strip()
            if not content:
                raise ValueError("빈 응답")
            data = parse_json(content)
        except Exception as e:   # 빈 응답 / API 오류 / JSON 파싱 실패 → 재시도
            _observe_attempt(t0, attempt, sha, plen)   # 실패한 시도도 1건 남긴다
            last = e
            if "connect" in str(e).lower():   # 연결 오류는 재시도해도 소용 X → 즉시 안내
                raise ConnectionError(
                    "텍스트 LLM 서버에 연결 실패. Ollama 서버 실행을 확인하세요: "
                    "`brew services start ollama` 또는 `ollama serve`") from e
            if attempt < retries:   # 빈 응답(모델 로딩 중)·일시 오류 → 점진 대기 후 재시도
                time.sleep(2 * (attempt + 1))
        else:
            _observe_attempt(t0, attempt, sha, plen)
            return data
    raise ValueError(f"chat_json: {retries + 1}회 실패 — {last}")
