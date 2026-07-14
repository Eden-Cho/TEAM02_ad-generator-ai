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


def observe(func=None, *, name=None):
    """@observe / @observe(name=...) — 활성 시 LangFuse 추적, 아니면 원본 함수 그대로."""
    def wrap(fn):
        if not enabled():
            return fn
        try:
            from langfuse import observe as _obs
            return _obs(name=name)(fn) if name else _obs()(fn)
        except Exception:
            return fn
    return wrap(func) if callable(func) else wrap


def langchain_handler():
    """LangChain 콜백 핸들러 (비활성·미설치 시 None)."""
    if not enabled():
        return None
    try:
        from langfuse.langchain import CallbackHandler   # langfuse v3
        return CallbackHandler()
    except Exception:
        try:
            from langfuse.callback import CallbackHandler  # 구버전 폴백
            return CallbackHandler()
        except Exception:
            return None


def flush():
    """대기 중 트레이스 전송 (요청 종료 시 호출). 비활성이면 no-op."""
    if not enabled():
        return
    try:
        from langfuse import Langfuse
        Langfuse().flush()
    except Exception:
        pass
