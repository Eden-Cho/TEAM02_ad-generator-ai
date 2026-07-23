"""근거 기반 공개 출력 경계 — 이미지 evidence 제한을 카피·FAQ·specs·GEO·structured data까지.

핵심: **키워드 필터를 의미 안전성의 최종 경계로 쓰지 않는다.** evidence-sensitive 역할
(ingredient/texture)이 있는 요청은 intro·모든 섹션·CTA·FAQ·specs·JSON-LD·geo_html을
**결정론적 안전 객체에서 조립**한다 — LLM 자유 텍스트를 공개 결과에 통과시키지 않는다.

- 근거 없음: 명시적으로 안전한 요청 필드(product_name·color 등)만 사용, 성분·제형·효능 주장 없음.
- 근거 있음: **해당 role의 입력 evidence 값만** 사용(교차 역할 불가), 같은 문장에 섞인 다른
  LLM 주장은 전부 폐기.
- Product JSON-LD description도 raw product_details를 복사하지 않고 안전 객체에서 생성/생략.
- 신뢰 표현은 '사용자가 입력한 확인 정보 기준'(출처 미검증이라 '공식 자료 기준'으로 단정 안 함).
- 잘못된 LLM 타입(list/dict/None)은 크래시 없이 폐기.
- ingredient/texture 역할이 없는 요청(tech 등)은 통과 — 기존 동작 유지.

검증 원문은 공개 카피(사용자 자산)까지만 — trace·warnings·safe dict·로그에는 나가지 않는다.
"""
import math

from baseline.style_presets import EVIDENCE_REQUIRED_ROLES


def _price_ok(value) -> bool:
    """가격 유효성 단일 기준(타입별 분리). **모든 가격 지점이 이 함수를 재사용한다.**

    - bool: 거부
    - int: math.isfinite() **호출하지 않음**(큰 정수 OverflowError 방지). 양수만 유효.
    - float: math.isfinite()가 True인 양수만(NaN·±Infinity·음수 거부).
    - 그 외(str·list·dict·None): 거부.
    0은 유효하지 않음(미입력 취급 — 출력 생략).
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, float):
        return math.isfinite(value) and value > 0
    return False


def finite_price(value):
    """유효 가격(양수 int/유한 양수 float)만 int로 정규화, 그 외는 None.

    큰 정수를 float로 바꾸지 않는다 — int(value)는 임의 정밀도라 안전하다.
    """
    return int(value) if _price_ok(value) else None

_TRUST = "사용자가 입력한 확인 정보 기준"

# 근거 없는 민감 역할의 안전 외관 카피(외관·패키지 디테일 이미지와 의미 일치).
_SAFE_APPEARANCE = {
    "ingredient": {
        "headline": "제품 외관 디테일", "sub": "확인 가능한 외형 중심",
        "body": "제품의 외관·패키지·표면 마감 등 확인 가능한 특징을 보여줍니다. "
                "확인 정보가 없어 성분·효능은 표기하지 않았습니다.",
        "points": ["외관·마감", "패키지 형태"]},
    "texture": {
        "headline": "제품 외관 디테일", "sub": "확인 가능한 외형 중심",
        "body": "제품의 외형과 마감 등 확인 가능한 특징을 보여줍니다. "
                "확인 정보가 없어 제형·사용감은 표기하지 않았습니다.",
        "points": ["외관·마감", "형태 디테일"]},
}

# 기타(비민감) 역할 — 역할 의미에 맞는 중립 제목·본문(검증 안 된 효능·사실 없음).
_ROLE_LABEL = {
    "hero": "대표 이미지", "build": "제품 구성", "connectivity": "연결",
    "lifestyle": "사용 예시", "serving": "제공 예시", "styling": "스타일링",
    "fabric": "소재", "material": "소재", "space": "공간 연출", "detail": "디테일",
}
_ROLE_BODY = {
    "hero": "제품의 대표 이미지입니다.",
    "build": "제품의 구성과 마감을 보여주는 컷입니다.",
    "connectivity": "제품의 연결·포트 구성을 보여주는 컷입니다.",
    "lifestyle": "제품을 실제 사용 맥락에서 보여주는 컷입니다.",
    "serving": "제품을 제공·연출한 모습을 보여주는 컷입니다.",
    "styling": "제품의 스타일링을 보여주는 컷입니다.",
    "fabric": "제품의 소재와 질감을 보여주는 컷입니다.",
    "material": "제품의 소재와 마감을 보여주는 컷입니다.",
    "space": "제품이 놓인 공간 연출을 보여주는 컷입니다.",
    "detail": "제품의 외형 디테일을 보여주는 컷입니다.",
}


def is_sensitive(roles) -> bool:
    """ingredient/texture 역할이 있으면 근거 경계 대상(민감 요청)."""
    return any(r in (roles or ()) for r in EVIDENCE_REQUIRED_ROLES)


def _sf(req, key) -> str:
    """안전한 요청 문자열 필드(없거나 비문자열이면 '')."""
    v = req.get(key)
    return str(v).strip() if isinstance(v, (str, int, float)) and str(v).strip() else ""


def _role_evidence(evidence, role) -> tuple:
    """해당 role의 입력 evidence만(교차 역할 불가). 문자열 항목만 남긴다."""
    items = (evidence or {}).get(role)
    if not isinstance(items, (list, tuple)):
        return ()
    return tuple(s.strip() for s in items if isinstance(s, str) and s.strip())


def _evidence_section(role, items) -> dict:
    joined = ", ".join(items)
    if role == "ingredient":
        return {"headline": "확인된 성분", "sub": _TRUST,
                "body": f"사용자가 입력한 확인 성분: {joined}. "
                        "그 외 성분·효능은 표기하지 않았습니다.",
                "points": list(items)[:3]}
    return {"headline": "확인된 제형", "sub": _TRUST,
            "body": f"사용자가 입력한 확인 제형: {joined}. "
                    "그 외 제형·사용감은 표기하지 않았습니다.",
            "points": list(items)[:3]}


def _appearance(role) -> dict:
    """_SAFE_APPEARANCE의 **깊은 사본** — 중첩 points 리스트를 호출마다 새로 만든다.

    얕은 dict() 복사는 points 리스트를 공유해, 반환값의 points를 변경하면 다음 호출 결과와
    모듈 상수까지 오염된다(공유 가변 상태). 새 리스트로 끊는다.
    """
    base = _SAFE_APPEARANCE[role]
    return {**base, "points": list(base["points"])}


def _safe_section(role, req, evidence) -> dict:
    if role in EVIDENCE_REQUIRED_ROLES:
        items = _role_evidence(evidence, role)      # 역할별 분리 — 교차 사용 없음
        return _evidence_section(role, items) if items else _appearance(role)
    name, color = _sf(req, "product_name"), _sf(req, "color")
    prefix = f"{color + ' ' if color else ''}{name}".strip()
    role_body = _ROLE_BODY.get(role, "제품의 외형을 보여주는 컷입니다.")
    body = f"{prefix} — {role_body}" if prefix else role_body
    return {"headline": _ROLE_LABEL.get(role, "제품 컷"), "sub": "",
            "body": body, "points": []}


def safe_page_copy(req, roles, evidence) -> dict:
    """민감 요청의 intro·모든 섹션·CTA를 결정론적 안전 객체로 조립."""
    name, color = _sf(req, "product_name"), _sf(req, "color")
    intro_body = (f"{color + ' ' if color else ''}{name} 제품을 소개합니다.").strip()
    return {
        "intro": {"headline": name, "body": intro_body or "제품을 소개합니다."},
        "sections": {r: _safe_section(r, req, evidence) for r in (roles or ())},
        "cta": "자세히 보기"}


def safe_specs(req) -> dict:
    """명시적으로 허용된 구조화 요청값만 스펙으로 사용(근거 없는 LLM specs 폐기)."""
    out = {}
    if _sf(req, "brand"):
        out["브랜드"] = _sf(req, "brand")
    if _sf(req, "color"):
        out["색상"] = _sf(req, "color")
    pv = finite_price(req.get("price"))
    if pv is not None:
        out["가격"] = f"{pv}원"
    return out


def safe_faq(req, roles, evidence) -> list:
    """검증된 요청값으로만 만든 결정론적 안전 FAQ(없으면 빈 목록).

    **활성 role 격리** — 요청에 없는 역할의 evidence는 무시한다(ingredient-only 요청에
    stray texture evidence가 있어도 texture FAQ를 만들지 않는다).
    """
    faq = []
    if "ingredient" in (roles or ()):
        ing = _role_evidence(evidence, "ingredient")
        if ing:
            faq.append({"q": "확인된 주요 성분은 무엇인가요?",
                        "a": f"사용자가 입력한 확인 성분은 {', '.join(ing)}입니다."})
    if "texture" in (roles or ()):
        tex = _role_evidence(evidence, "texture")
        if tex:
            faq.append({"q": "제형은 어떤가요?",
                        "a": f"사용자가 입력한 확인 제형은 {', '.join(tex)}입니다."})
    color = _sf(req, "color")
    if color:
        faq.append({"q": "색상은 무엇인가요?", "a": f"{color}입니다."})
    return faq


# 공개 구조화 필드 계약 — 문자열 필드와 숫자(price) 필드.
_PUBLIC_STR_FIELDS = ("product_name", "category", "color", "brand",
                      "gtin", "mpn", "sku")


def validate_public_fields(req) -> None:
    """공개 구조화 필드 타입을 폐쇄적으로 검증(유료 호출 전). 위반 시 ValueError.

    문자열 필드는 str만(list/dict/bool/숫자 거부), price는 bool 아닌 int/float만.
    필드 생략은 허용(하위호환). 값 원문은 예외 메시지에 넣지 않는다(필드명만).
    """
    if not isinstance(req, dict):
        raise ValueError("request")
    for k in _PUBLIC_STR_FIELDS:
        if k in req and not isinstance(req[k], str):
            raise ValueError(k)
    if "price" in req:
        p = req["price"]
        # 유효 가격(_price_ok, 타입별 분리 — 큰 int에 isfinite 호출 안 함) 또는 0(미입력
        # 하위호환)만 허용. bool·비숫자·비유한·음수는 거부. 값 원문은 메시지에 넣지 않는다.
        zero = isinstance(p, (int, float)) and not isinstance(p, bool) and p == 0
        if not (_price_ok(p) or zero):
            raise ValueError("price")


def jsonld_request(req) -> dict:
    """Product JSON-LD용 안전 요청 — raw product_details를 우회 경로로 두지 않고,
    잘못된 타입(list/dict/None/bool)이 HTML 생성까지 통과하지 않게 방어적으로 좁힌다.

    description 제거. 문자열 필드는 비어 있지 않은 str만, price는 bool 아닌 양수만 통과.
    """
    out = {}
    for k in _PUBLIC_STR_FIELDS:
        v = req.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v
    pv = finite_price(req.get("price"))
    if pv is not None:
        out["price"] = pv
    return out
