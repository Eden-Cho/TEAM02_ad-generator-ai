"""LangFuse 관측 헬퍼 — 키 있으면 추적, 없으면 no-op(그레이스풀 저하).

활성 조건: LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY (+ 선택 LANGFUSE_HOST) 환경변수.
langfuse 미설치·키 없음 어느 경우든 import/실행이 깨지지 않고 원본 동작 유지.
"""
import os

_state = None  # None=미확인 / True·False=활성 여부


def enabled() -> bool:
    """LangFuse 사용 가능 여부 (키 + 패키지). 1회 판정 후 캐시."""
    global _state
    if _state is None:
        if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
            _state = False
        else:
            try:
                from langfuse import Langfuse
                Langfuse()  # 환경변수에서 키 로드 (싱글톤)
                _state = True
            except Exception:
                _state = False
    return _state


def observe(func=None, *, name=None, capture_input=False, capture_output=False):
    """@observe / @observe(name=...) — 활성 시 LangFuse 추적, 아니면 원본 함수 그대로.

    **기본적으로 입력·출력을 캡처하지 않는다.** 캡처를 켜두면 run_pipeline(req)의
    req(product_name·emphasis·product_details)와 generate_image(spec)의 프롬프트
    원문이 그대로 외부로 나간다. 프롬프트는 제품 자산이고 req는 사용자 입력이다.
    → 관측은 metadata(이름·지연·성공여부)만으로 충분하다.

    원문이 필요한 감사(audit)는 별도 설계 대상이다(인증·redaction·보존기간).
    지금은 그 기능이 없으므로 캡처를 켤 이유도 없다.
    """
    def wrap(fn):
        if not enabled():
            return fn
        try:
            from langfuse import observe as _obs
            return _obs(name=name, capture_input=capture_input,
                        capture_output=capture_output)(fn)
        except Exception:
            return fn
    return wrap(func) if callable(func) else wrap


def langchain_handler():
    """LangChain 콜백 핸들러 — **항상 None**.

    이 핸들러는 system/user 프롬프트 **본문**을 LangFuse로 전송한다. observe()가
    캡처를 끄더라도 이 경로가 열려 있으면 본문이 그대로 나가므로 함께 막아야 한다.

    llm.chat_json이 이 함수를 참조하지 않게 바뀌었지만, 외부(노트북 등) 호출 대비로
    함수 자체는 남기고 None을 돌려준다. 본문 전송을 되살리려면 audit 정책부터 필요하다.
    """
    return None


def record_llm_attempt(*, model: str, attempt: int, latency_ms: int,
                       prompt_sha256: str, prompt_len: int) -> None:
    """LLM API 시도 1건을 **metadata만으로** 기록. 비활성이면 no-op.

    성공·실패 모두 1건씩 남긴다 — 실패한 재시도도 비용이므로 관측에서 빠지면 안 된다.

    본문을 안 보내는 근거(langfuse 4.14.0 실측):
        Langfuse.create_event(*, name, input=None, output=None, metadata=None, ...)
      input·output이 선택적이고 기본 None이라, 넘기지 않으면 프롬프트·응답이
      전송될 경로 자체가 없다.

    prompt_sha256의 용도는 **동일성 추적**뿐이다 — 두 시도가 같은 프롬프트였는지만
    알려준다. 이것은 익명화가 아니다:
      - 우리 프롬프트는 씬 템플릿 조합이라 후보 공간이 좁은 **저엔트로피 입력**이고,
        후보를 나열해 해시를 맞춰보는 **사전 대조가 가능**하다.
      - 즉 해시 전송은 '원문을 직접 저장하지 않는다'는 의미이지
        '내용을 알 수 없다'는 뜻이 아니다.
    원문 자체가 필요한 감사(audit)는 인증·redaction·보존기간을 갖춘 별도 설계 대상이다.

    관측 실패가 생성 파이프라인을 죽이면 안 되므로 예외는 삼킨다.
    """
    if not enabled():
        return
    try:
        from langfuse import get_client
        get_client().create_event(
            name="llm_attempt",
            metadata={
                "model": model,
                "attempt": attempt,
                "latency_ms": latency_ms,
                "prompt_sha256": prompt_sha256,
                "prompt_len": prompt_len,
            },
        )
    except Exception:
        pass


def flush():
    """대기 중 트레이스 전송 (요청 종료 시 호출). 비활성이면 no-op."""
    if not enabled():
        return
    try:
        from langfuse import Langfuse
        Langfuse().flush()
    except Exception:
        pass
