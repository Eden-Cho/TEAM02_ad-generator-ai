"""다제품 품질 평가 — 자동 검증 + 수동 육안 평가 2층 계약. **로컬 전용, API 호출 없음.**

경계를 정직하게 긋는다:
  · 자동 층은 코드가 판정 가능한 것만 본다 — 파일/형식/크기, 출력 폭, 정사각형,
    역할·경로·trace·회계·warnings 일치.
  · 실제 이미지 품질(제품 정확성·비율·포트·로고·배경 조화·접지·구도·카피 가독성·자연
    연출 정확성)은 **코드가 판정할 수 없다** — 수동 육안 평가 층이 담당하며, 수동 항목이
    pending인 한 전체 결과는 절대 pass가 되지 않는다.

케이스 기대값(역할·경로·출력 폭)은 실제 라우팅 코드(resolve_image_slots·decide_path·
build_style_context)에서 **순수하게** 파생한다 — 제품·카테고리가 달라도 같은 기준으로
평가된다.
"""
import base64
import io
import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path

from PIL import Image

from baseline.archetypes import get_profile, resolve_image_slots
from baseline.image_planner import decide_path
from baseline.style_presets import build_style_context


class AutoCheckCode(str, Enum):
    """자동 검증 항목 — 폐쇄형. 코드가 실제로 판정 가능한 것만 둔다."""
    DETAIL_DECODABLE = "detail_decodable"
    DETAIL_FORMAT_PNG = "detail_format_png"
    DETAIL_WIDTH_MATCHES_SITE = "detail_width_matches_site"
    DETAIL_LONGFORM = "detail_longform"
    MAIN_FORMAT_JPEG = "main_format_jpeg"
    MAIN_SQUARE = "main_square"
    GALLERY_FORMAT_JPEG = "gallery_format_jpeg"
    GALLERY_SQUARE = "gallery_square"
    GALLERY_COUNT_MATCHES_ROLES = "gallery_count_matches_roles"
    TRACE_FIELDS_PRESENT = "trace_fields_present"
    TRACE_TYPES_VALID = "trace_types_valid"
    PROMPT_SHA_FORMAT = "prompt_sha_format"
    ROLES_MATCH_EXPECTED = "roles_match_expected"
    PATHS_MATCH_EXPECTED = "paths_match_expected"
    ATTEMPTS_MATCH_PATHS = "attempts_match_paths"
    TRACE_ACCOUNTING_CONSISTENT = "trace_accounting_consistent"
    WARNINGS_MATCH_TRACE = "warnings_match_trace"
    WARNINGS_TYPES_VALID = "warnings_types_valid"
    FILES_EXIST_NONEMPTY = "files_exist_nonempty"


class ManualCriterion(str, Enum):
    """수동 육안 평가 항목 — 폐쇄형. 코드가 판정을 대신할 수 없는 것들."""
    PRODUCT_ACCURACY = "product_accuracy"          # 제품 정확성
    PROPORTION_PORTS_LOGO = "proportion_ports_logo"  # 비율·포트·로고
    BACKGROUND_HARMONY = "background_harmony"      # 배경 조화
    GROUNDING_SHADOW = "grounding_shadow"          # 접지·그림자
    COMPOSITION = "composition"                    # 구도
    COPY_READABILITY = "copy_readability"          # 카피 가독성
    NATURAL_ACCURACY = "natural_accuracy"          # 자연 연출 정확성 (natural 전용)
    FEATURE_ACCURACY = "feature_accuracy"          # 기능 컷 정확성 (공통)
    SECTION_CONTINUITY = "section_continuity"      # 섹션 흐름·연속성 (공통)
    CUTOUT_EDGE_QUALITY = "cutout_edge_quality"    # 누끼 경계 품질 (preserve 전용)
    SOURCE_ANGLE_PRESERVED = "source_angle_preserved"  # 입력 각도 유지 (preserve 전용)
    RERENDER_DISTORTION = "rerender_distortion"    # 재렌더 왜곡 (natural 전용)
    LIGHTING_PERSPECTIVE_INTEGRATION = "lighting_and_perspective_integration"  # (natural 전용)


class ReviewStatus(str, Enum):
    """수동 평가 항목 상태 — 폐쇄형."""
    PENDING = "pending"
    PASS = "pass"
    CONDITIONAL = "conditional"        # 통과이나 조건부(경미한 문제 관찰)
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"  # 해당 케이스에 적용 안 됨(예: preserve의 자연 연출)


class Verdict(str, Enum):
    """최종 판정 — pending이 남아 있으면 판정 자체가 성립하지 않는다(별도 상태)."""
    PASS = "pass"
    CONDITIONAL = "conditional"
    FAIL = "fail"


@dataclass(frozen=True)
class AutoCheck:
    """자동 검증 1건. measured는 측정치 요약(형식·크기 등) — 사용자 입력·프롬프트 아님."""
    code: AutoCheckCode
    ok: bool
    measured: str = ""

    def __post_init__(self):
        if not isinstance(self.code, AutoCheckCode):
            raise ValueError(f"code는 AutoCheckCode여야 한다: {self.code!r}")


@dataclass(frozen=True)
class ManualReview:
    """수동 육안 평가 1건. 기본 pending — 사람이 채우기 전에는 통과가 아니다."""
    criterion: ManualCriterion
    status: ReviewStatus = ReviewStatus.PENDING
    note: str = ""

    def __post_init__(self):
        if not isinstance(self.criterion, ManualCriterion):
            raise ValueError(f"criterion은 ManualCriterion이어야 한다: {self.criterion!r}")
        try:   # 문자열 값도 폐쇄형으로 강제 변환 — 허용 외 값은 즉시 거부
            object.__setattr__(self, "status", ReviewStatus(self.status))
        except ValueError:
            raise ValueError(
                f"status는 {[s.value for s in ReviewStatus]} 중 하나: {self.status!r}") from None
        if not isinstance(self.note, str):
            raise ValueError(f"note는 문자열이어야 한다: {self.note!r}")


@dataclass(frozen=True)
class EvalCase:
    """제품 1건의 평가 케이스 — 기대값은 실제 라우팅에서 파생된 값."""
    case_id: str
    category: str
    presentation_mode: str
    site_spec: str
    expected_page_width: int
    expected_paths: tuple            # ((role, intended_path), ...) 순서 포함


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    auto_checks: tuple = ()
    manual_reviews: tuple = ()

    @property
    def overall(self) -> str:
        """게이팅: fail > pending > conditional > pass.

        자동 실패 또는 수동 fail → fail. 수동 pending 잔존 → **pending(절대 pass 아님)**.
        수동 conditional 있으면 → conditional. not_applicable은 판정에서 제외.
        """
        if any(not c.ok for c in self.auto_checks):
            return Verdict.FAIL.value
        statuses = [m.status for m in self.manual_reviews
                    if m.status is not ReviewStatus.NOT_APPLICABLE]
        if any(s is ReviewStatus.FAIL for s in statuses):
            return Verdict.FAIL.value
        if any(s is ReviewStatus.PENDING for s in statuses):
            return "pending"
        if any(s is ReviewStatus.CONDITIONAL for s in statuses):
            return Verdict.CONDITIONAL.value
        return Verdict.PASS.value

    def final_verdict(self) -> Verdict:
        """확정 판정. **pending이 남아 있으면 판정이 성립하지 않으므로 ValueError** —
        수동 평가를 건너뛴 채 결과를 확정하는 경로를 계약으로 차단한다."""
        o = self.overall
        if o == "pending":
            pend = [m.criterion.value for m in self.manual_reviews
                    if m.status is ReviewStatus.PENDING]
            raise ValueError(f"수동 평가 미완(pending) — 판정 불가: {pend}")
        return Verdict(o)

    def to_safe_dict(self) -> dict:
        return {
            "case_id": self.case.case_id,
            "category": self.case.category,
            "presentation_mode": self.case.presentation_mode,
            "overall": self.overall,
            "auto": [{"code": c.code.value, "ok": c.ok, "measured": c.measured}
                     for c in self.auto_checks],
            "manual": [{"criterion": m.criterion.value, "status": m.status.value,
                        "note": m.note} for m in self.manual_reviews],
        }


def case_for(case_id: str, category: str, presentation_mode: str = "preserve",
             site_spec: str = "네이버 스마트스토어", creativity: int = 2,
             n_product: int = 1, product_angles=None,
             n_usage: int = 0, usage_angles=None) -> EvalCase:
    """실제 라우팅 코드로 기대 역할·경로·출력 폭을 **순수하게** 파생한다 (API 0회)."""
    req = {"category": category, "site_spec": site_spec, "creativity": creativity,
           "presentation_mode": presentation_mode}
    ctx = build_style_context(req)
    slots = resolve_image_slots(
        get_profile(category),
        [f"p{i}" for i in range(n_product)], [f"u{i}" for i in range(n_usage)],
        product_angles=product_angles, app_angles=usage_angles,
        presentation_mode=presentation_mode)
    expected = tuple(
        (s["role"], decide_path(s["source"], s["image_path"], creativity,
                                presentation_mode=presentation_mode))
        for s in slots)
    return EvalCase(case_id=case_id, category=category,
                    presentation_mode=presentation_mode, site_spec=site_spec,
                    expected_page_width=ctx["page_width"], expected_paths=expected)


def manual_reviews_for(case: EvalCase) -> tuple:
    """케이스별 수동 평가 템플릿 — 7개 기준을 항상 포함해 케이스 간 비교 가능하게 한다.

    natural 전용 항목(NATURAL_ACCURACY)은 preserve 케이스에서 **not_applicable**로
    미리 표시된다(누락이 아니라 명시적 제외 — pending 게이팅에 걸리지 않음).
    """
    common = [ManualCriterion.PRODUCT_ACCURACY, ManualCriterion.PROPORTION_PORTS_LOGO,
              ManualCriterion.BACKGROUND_HARMONY, ManualCriterion.GROUNDING_SHADOW,
              ManualCriterion.COMPOSITION, ManualCriterion.COPY_READABILITY,
              ManualCriterion.FEATURE_ACCURACY, ManualCriterion.SECTION_CONTINUITY]
    preserve_only = [ManualCriterion.CUTOUT_EDGE_QUALITY,
                     ManualCriterion.SOURCE_ANGLE_PRESERVED]
    natural_only = [ManualCriterion.NATURAL_ACCURACY,
                    ManualCriterion.RERENDER_DISTORTION,
                    ManualCriterion.LIGHTING_PERSPECTIVE_INTEGRATION]
    is_natural = case.presentation_mode == "natural"
    reviews = [ManualReview(criterion=c) for c in common]
    for c in preserve_only:
        reviews.append(ManualReview(
            c, ReviewStatus.NOT_APPLICABLE if is_natural else ReviewStatus.PENDING,
            "natural 모드 — 해당 없음" if is_natural else ""))
    for c in natural_only:
        reviews.append(ManualReview(
            c, ReviewStatus.PENDING if is_natural else ReviewStatus.NOT_APPLICABLE,
            "" if is_natural else "preserve 모드 — 해당 없음"))
    return tuple(reviews)


def _decode(b64: str):
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def _image_checks(case: EvalCase, page, main, gallery) -> list:
    """PIL 이미지 기반 검사 — base64 응답과 파일 artifact가 같은 기준을 공유한다."""
    checks = []
    if page is not None:
        checks.append(AutoCheck(AutoCheckCode.DETAIL_DECODABLE, True,
                                f"{page.format} {page.size}"))
        checks.append(AutoCheck(AutoCheckCode.DETAIL_FORMAT_PNG,
                                page.format == "PNG", str(page.format)))
        checks.append(AutoCheck(AutoCheckCode.DETAIL_WIDTH_MATCHES_SITE,
                                page.width == case.expected_page_width,
                                f"{page.width}!={case.expected_page_width}"
                                if page.width != case.expected_page_width
                                else str(page.width)))
        checks.append(AutoCheck(AutoCheckCode.DETAIL_LONGFORM,
                                page.height > page.width, f"{page.size}"))
    else:
        checks.append(AutoCheck(AutoCheckCode.DETAIL_DECODABLE, False, "decode-error"))

    if main is not None:
        checks.append(AutoCheck(AutoCheckCode.MAIN_FORMAT_JPEG,
                                main.format == "JPEG", str(main.format)))
        checks.append(AutoCheck(AutoCheckCode.MAIN_SQUARE,
                                main.width == main.height, f"{main.size}"))
    else:
        checks.append(AutoCheck(AutoCheckCode.MAIN_FORMAT_JPEG, False, "decode-error"))

    fmts, squares = [], []
    for g in gallery:
        if g is None:
            fmts.append(False)
            continue
        fmts.append(g.format == "JPEG")
        squares.append(g.width == g.height)
    # gallery는 역할 컷마다 1장 — 0장이거나 수가 다르면 그 자체가 실패다.
    expected_n = len(case.expected_paths)
    checks.append(AutoCheck(AutoCheckCode.GALLERY_COUNT_MATCHES_ROLES,
                            len(gallery) == expected_n,
                            f"{len(gallery)}!={expected_n}"
                            if len(gallery) != expected_n else str(expected_n)))
    checks.append(AutoCheck(AutoCheckCode.GALLERY_FORMAT_JPEG,
                            bool(fmts) and all(fmts), f"n={len(fmts)}"))
    checks.append(AutoCheck(AutoCheckCode.GALLERY_SQUARE,
                            bool(squares) and all(squares), f"n={len(squares)}"))
    return checks


def _auto_image_checks(case: EvalCase, response: dict) -> list:
    def safe(b64):
        try:
            return _decode(b64)
        except Exception:
            return None
    page = safe(response.get("detail_page", ""))
    main = safe(response.get("main", ""))
    gallery = [safe(g) for g in response.get("gallery", [])]
    return _image_checks(case, page, main, gallery)


_TRACE_REQUIRED = ("generations", "image_api_attempts", "logical_chat_calls",
                   "actual_api_attempts", "image_warnings")
_GEN_REQUIRED = ("role", "actual_path", "outcome", "image_api_calls",
                 "final_prompt_sha256", "prompt_len")
_CALL_REQUIRED = ("api", "model", "size", "prompt_sha256", "prompt_len", "milliseconds")
_SHA12 = re.compile(r"^[0-9a-f]{12}$")


def _nonneg_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def _trace_type_errors(trace: dict) -> list:
    """잘못된 타입의 안전한 경로 목록 — 예외 없이 수집한다."""
    bad = []
    for k in ("logical_chat_calls", "actual_api_attempts", "image_api_attempts"):
        if k in trace and not _nonneg_int(trace[k]):
            bad.append(k)
    if "image_warnings" in trace and not isinstance(trace["image_warnings"], list):
        bad.append("image_warnings")
    gens = trace.get("generations")
    if gens is not None and not isinstance(gens, list):
        bad.append("generations")
        gens = []
    for gi, g in enumerate(gens or []):
        if not isinstance(g, dict):
            bad.append(f"generations[{gi}]")
            continue
        for k in ("role", "actual_path", "outcome"):
            if k in g and not _nonempty_str(g[k]):
                bad.append(f"generations[{gi}].{k}")
        if "prompt_len" in g and not _nonneg_int(g["prompt_len"]):
            bad.append(f"generations[{gi}].prompt_len")
        calls = g.get("image_api_calls")
        if calls is not None and not isinstance(calls, list):
            bad.append(f"generations[{gi}].image_api_calls")
            continue
        for ci, a in enumerate(calls or []):
            if not isinstance(a, dict):
                bad.append(f"generations[{gi}].image_api_calls[{ci}]")
                continue
            for k in ("api", "model", "size", "prompt_sha256"):
                if k in a and not _nonempty_str(a[k]):
                    bad.append(f"generations[{gi}].image_api_calls[{ci}].{k}")
            for k in ("prompt_len", "milliseconds"):
                if k in a and not _nonneg_int(a[k]):
                    bad.append(f"generations[{gi}].image_api_calls[{ci}].{k}")
    return bad


def _is_str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _auto_trace_checks(case: EvalCase, response: dict) -> list:
    checks = []
    raw = response.get("trace")
    # 최상위 trace가 dict가 아니면(None·문자열·리스트·숫자) 정규화 전에 오류를 보존한다.
    top_bad = not isinstance(raw, dict)
    trace = raw if isinstance(raw, dict) else {}
    # 타입 오류는 예외로 터지지 않고 check fail로 보고한다.
    type_errors = (["trace"] if top_bad else []) + _trace_type_errors(trace)
    checks.append(AutoCheck(AutoCheckCode.TRACE_TYPES_VALID, not type_errors,
                            f"bad={type_errors[:6]}" if type_errors else "ok"))
    if not isinstance(trace.get("generations"), list):   # 이후 검사 안전화
        trace = {**trace, "generations": []}
    # (image_warnings는 원본 타입 그대로 두고 WARNINGS_TYPES_VALID가 검사한다)
    # 후속 계산은 dict인 generation·dict인 call만 사용 — 잘못된 원소로 중단되지 않는다.
    trace = {**trace, "generations": [
        {**g, "image_api_calls": [a for a in g.get("image_api_calls", [])
                                  if isinstance(a, dict)]
              if isinstance(g.get("image_api_calls"), list) else []}
        for g in trace["generations"] if isinstance(g, dict)]}
    # 필수 필드 누락을 기본값으로 조용히 흡수하지 않는다 — 최상위·generation·call
    # 중첩 구조 전체를 검사하고, 누락 위치를 안전한 경로 문자열로 기록한다.
    missing = [k for k in _TRACE_REQUIRED if k not in trace]
    for gi, g in enumerate(trace.get("generations", []) or []):
        if not isinstance(g, dict):
            missing.append(f"generations[{gi}]")
            continue
        missing += [f"generations[{gi}].{k}" for k in _GEN_REQUIRED if k not in g]
        for ci, a in enumerate(g.get("image_api_calls", []) or []):
            if not isinstance(a, dict):
                missing.append(f"generations[{gi}].image_api_calls[{ci}]")
                continue
            missing += [f"generations[{gi}].image_api_calls[{ci}].{k}"
                        for k in _CALL_REQUIRED if k not in a]
    checks.append(AutoCheck(AutoCheckCode.TRACE_FIELDS_PRESENT, not missing,
                            f"missing={missing[:6]}" if missing else "ok"))
    gens = trace.get("generations", [])
    # 외부 SHA 계약: 모든 gen의 final + 모든 call의 SHA가 정확히 12자리 소문자 hex.
    # None·빈 문자열·누락도 후보로 세어 실패시킨다 — all([])로 통과하는 경로 없음.
    shas = [g.get("final_prompt_sha256") for g in gens]
    shas += [a.get("prompt_sha256") for g in gens for a in g.get("image_api_calls", [])]
    expected_n = len(case.expected_paths) * 1   # 최소 gen당 final 1개는 있어야 한다
    sha_ok = (len(shas) >= expected_n and bool(shas)
              and all(isinstance(x, str) and _SHA12.match(x) for x in shas))
    checks.append(AutoCheck(AutoCheckCode.PROMPT_SHA_FORMAT, sha_ok,
                            f"n={len(shas)}/expected>={expected_n}"))
    got = tuple((g.get("role"), g.get("actual_path")) for g in gens)
    checks.append(AutoCheck(AutoCheckCode.ROLES_MATCH_EXPECTED,
                            tuple(r for r, _ in got) == tuple(r for r, _ in case.expected_paths),
                            f"{[r for r, _ in got]}"))
    checks.append(AutoCheck(AutoCheckCode.PATHS_MATCH_EXPECTED,
                            got == case.expected_paths, f"{list(got)}"))
    # 경로별 이미지 시도 규칙: passthrough=0, 그 외(성공 시)=1
    attempts_ok = all(
        len(g.get("image_api_calls", [])) == (0 if g.get("actual_path") == "passthrough" else 1)
        for g in gens)
    checks.append(AutoCheck(AutoCheckCode.ATTEMPTS_MATCH_PATHS, attempts_ok,
                            f"{[len(g.get('image_api_calls', [])) for g in gens]}"))
    total = sum(len(g.get("image_api_calls", []))
                for g in gens if isinstance(g, dict)
                if isinstance(g.get("image_api_calls"), list))
    logical = trace.get("logical_chat_calls", 0)
    actual = trace.get("actual_api_attempts", 0)
    # 타입이 어긋나면 비교 자체가 성립하지 않는다 → 예외 없이 실패로 본다.
    acct_ok = (_nonneg_int(logical) and _nonneg_int(actual)
               and trace.get("image_api_attempts") == total
               and logical <= actual)
    checks.append(AutoCheck(AutoCheckCode.TRACE_ACCOUNTING_CONSISTENT, acct_ok,
                            f"image={trace.get('image_api_attempts')}/{total} "
                            f"llm={trace.get('logical_chat_calls')}<={trace.get('actual_api_attempts')}"))
    # warnings 타입 안전 — 응답·trace 모두 list[str]이어야 하며, 아니면 크래시 없이
    # 타입 실패로 보고하고 일치 검사도 성공 처리하지 않는다.
    resp_w = response.get("warnings", [])
    trace_w = trace.get("image_warnings", [])
    w_types_ok = _is_str_list(resp_w) and _is_str_list(trace_w)
    checks.append(AutoCheck(AutoCheckCode.WARNINGS_TYPES_VALID, w_types_ok,
                            "ok" if w_types_ok
                            else f"resp={type(resp_w).__name__} trace={type(trace_w).__name__}"))
    checks.append(AutoCheck(AutoCheckCode.WARNINGS_MATCH_TRACE,
                            w_types_ok and list(resp_w) == list(trace_w),
                            f"n={len(resp_w) if isinstance(resp_w, list) else '?'}"))
    return checks


def check_output_files(paths) -> AutoCheck:
    """저장 산출물 존재·비어있지 않음 확인 (저장 경로 검증용 보조)."""
    missing = [str(p) for p in paths
               if not Path(p).exists() or Path(p).stat().st_size == 0]
    return AutoCheck(AutoCheckCode.FILES_EXIST_NONEMPTY, not missing,
                     f"missing={len(missing)}")


def evaluate_case(case: EvalCase, response: dict,
                  output_files=None) -> CaseResult:
    """API 응답(dict) 1건 → 자동 검증 + pending 수동 템플릿. **판정을 과장하지 않는다** —
    자동 층이 전부 통과해도 수동 육안 평가 전에는 overall이 pass가 될 수 없다."""
    checks = _auto_image_checks(case, response) + _auto_trace_checks(case, response)
    if output_files is not None:
        checks.append(check_output_files(output_files))
    return CaseResult(case=case, auto_checks=tuple(checks),
                      manual_reviews=manual_reviews_for(case))


def apply_manual(result: CaseResult, verdicts: dict) -> CaseResult:
    """사람이 채운 수동 평가 반영. verdicts: {ManualCriterion: (status, note)}.

    케이스에 정의되지 않은 criterion은 **조용히 무시하지 않고 즉시 거부**한다 —
    오타·잘못된 키로 평가가 누락된 채 확정되는 것을 막는다.
    """
    defined = {m.criterion for m in result.manual_reviews}
    unknown = [k for k in verdicts if k not in defined]
    if unknown:
        raise ValueError(f"케이스에 정의되지 않은 criterion: {unknown}")
    # 원래 적용 가능성(manual_reviews_for 템플릿) 기준으로 N/A 우회를 차단한다.
    baseline = {m.criterion: m.status for m in manual_reviews_for(result.case)}
    for k, v in verdicts.items():
        if not isinstance(v, (tuple, list)) or len(v) != 2:
            raise ValueError(f"{k.value} 값은 (status, note) 2-tuple이어야 한다: {v!r}")
        if not isinstance(v[1], str):
            raise ValueError(f"{k.value} note는 문자열이어야 한다: {v[1]!r}")
        try:
            new_status = ReviewStatus(v[0])
        except ValueError:
            raise ValueError(
                f"{k.value} status 허용 외: {v[0]!r}") from None
        orig = baseline.get(k, ReviewStatus.PENDING)
        if orig is ReviewStatus.NOT_APPLICABLE:
            if new_status is not ReviewStatus.NOT_APPLICABLE:
                raise ValueError(
                    f"{k.value}는 이 모드({result.case.presentation_mode})에서 "
                    f"not_applicable — {new_status.value}로 변경 불가")
        elif new_status is ReviewStatus.NOT_APPLICABLE:
            raise ValueError(
                f"{k.value}는 필수 평가 기준 — not_applicable로 우회 불가")
    updated = []
    for m in result.manual_reviews:
        if m.criterion in verdicts:
            status, note = verdicts[m.criterion]
            updated.append(ManualReview(m.criterion, status, note))
        else:
            updated.append(m)
    return replace(result, manual_reviews=tuple(updated))


def summarize(results) -> dict:
    """여러 케이스 집계 — fail > pending > conditional > pass. 빈 목록은 pending."""
    overalls = [r.overall for r in results]
    if any(o == "fail" for o in overalls):
        agg = "fail"
    elif any(o == "pending" for o in overalls):
        agg = "pending"
    elif any(o == "conditional" for o in overalls):
        agg = "conditional"
    else:
        agg = "pass" if overalls else "pending"
    return {"overall": agg,
            "cases": {r.case.case_id: r.to_safe_dict() for r in results}}


# ── 로컬 artifact manifest 계약 ─────────────────────────────────────────────
_MANIFEST_REQUIRED = ("case_id", "product_name", "archetype", "category",
                      "presentation_mode", "site_spec", "expected_roles",
                      "expected_paths", "warnings", "artifacts")
_ARTIFACT_KEYS = ("detail_page", "main", "gallery", "trace")
_VALID_PATHS = ("composite", "creative_edit", "t2i", "passthrough")


@dataclass(frozen=True)
class Manifest:
    """실행 산출물 1건의 로컬 manifest — 폐쇄형. 검증은 load_manifest가 한다."""
    case_id: str
    product_name: str
    archetype: str
    category: str
    presentation_mode: str
    site_spec: str
    expected_roles: tuple
    expected_paths: tuple            # expected_roles 순서의 ((role, path), ...)
    warnings: tuple
    detail_page: str
    main: str
    gallery: tuple
    trace_path: str


_ARCHETYPES = ("tech", "fashion", "beauty", "food", "living", "general")


def _require_nonempty_str(data, key):
    v = data.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{key}는 비어 있지 않은 문자열이어야 한다: {v!r}")
    return v


def _require_abs_path(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}는 비어 있지 않은 경로 문자열이어야 한다: {value!r}")
    if not Path(value).is_absolute():
        # 상대경로를 cwd 기준으로 조용히 해석하지 않는다 — 실행 위치에 따라 결과가 달라진다.
        raise ValueError(f"{where}는 절대경로여야 한다: {value!r}")
    return value


def load_manifest(path) -> Manifest:
    """manifest JSON 로드·검증. 계약 위반은 조용히 흡수하지 않고 ValueError.
    입력 dict/list는 변형하지 않는다(튜플로 복사만)."""
    mp = Path(path)
    if not mp.is_file():
        raise ValueError(f"manifest 파일이 없다: {path}")
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except Exception as e:                    # JSON 오류를 ValueError로 정규화
        raise ValueError(f"manifest JSON 파싱 실패: {type(e).__name__}") from None
    if not isinstance(data, dict):
        raise ValueError("manifest 최상위는 object여야 한다")
    missing = [k for k in _MANIFEST_REQUIRED if k not in data]
    if missing:
        raise ValueError(f"manifest 필수 키 누락: {missing}")
    for key in ("case_id", "product_name", "category", "site_spec"):
        _require_nonempty_str(data, key)
    if data["archetype"] not in _ARCHETYPES:
        raise ValueError(f"archetype 허용 외({_ARCHETYPES}): {data['archetype']!r}")
    if data["presentation_mode"] not in ("preserve", "natural"):
        raise ValueError(f"presentation_mode 허용 외: {data['presentation_mode']!r}")
    roles = data["expected_roles"]
    if (not isinstance(roles, list) or not roles
            or not all(isinstance(r, str) and r.strip() for r in roles)):
        raise ValueError(f"expected_roles는 비어 있지 않은 list[str]: {roles!r}")
    if len(set(roles)) != len(roles):
        raise ValueError(f"expected_roles에 중복이 있다: {roles!r}")
    paths_map = data["expected_paths"]
    if not isinstance(paths_map, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in paths_map.items()):
        raise ValueError("expected_paths는 dict[str,str]이어야 한다")
    if list(paths_map) != list(roles):        # 집합뿐 아니라 **순서**까지 동일해야 한다
        raise ValueError(
            f"expected_paths의 키 순서·집합이 expected_roles와 다르다: "
            f"{list(paths_map)} != {list(roles)}")
    bad = {r: p for r, p in paths_map.items() if p not in _VALID_PATHS}
    if bad:
        raise ValueError(f"허용 외 경로: {bad}")
    warns = data["warnings"]
    if not isinstance(warns, list) or not all(isinstance(w, str) for w in warns):
        raise ValueError(f"warnings는 list[str]이어야 한다: {warns!r}")
    art = data["artifacts"]
    if not isinstance(art, dict) or set(art) != set(_ARTIFACT_KEYS):
        raise ValueError(f"artifacts 키는 {_ARTIFACT_KEYS} 정확히: {art!r}")
    for key in ("detail_page", "main", "trace"):
        _require_abs_path(art[key], f"artifacts.{key}")
    if not isinstance(art["gallery"], list) or not art["gallery"]:
        raise ValueError("artifacts.gallery는 비어 있지 않은 배열이어야 한다")
    for i, g in enumerate(art["gallery"]):
        _require_abs_path(g, f"artifacts.gallery[{i}]")
    return Manifest(
        case_id=data["case_id"], product_name=data["product_name"],
        archetype=data["archetype"], category=data["category"],
        presentation_mode=data["presentation_mode"], site_spec=data["site_spec"],
        expected_roles=tuple(roles),
        expected_paths=tuple((r, paths_map[r]) for r in roles),
        warnings=tuple(data["warnings"]),
        detail_page=str(art["detail_page"]), main=str(art["main"]),
        gallery=tuple(str(g) for g in art["gallery"]),
        trace_path=str(art["trace"]))


def case_from_manifest(m: Manifest) -> EvalCase:
    ctx = build_style_context({"site_spec": m.site_spec})
    return EvalCase(case_id=m.case_id, category=m.category,
                    presentation_mode=m.presentation_mode, site_spec=m.site_spec,
                    expected_page_width=ctx["page_width"],
                    expected_paths=m.expected_paths)


def _open_or_none(path):
    """context manager로 열고 load() 후 독립 복사본 반환 — 파일 핸들 누수 없음.
    복사본은 format을 잃으므로 원본 format을 보존해 검사 계약을 유지한다."""
    try:
        with Image.open(path) as im:
            im.load()
            fmt = im.format
            copy = im.copy()
        copy.format = fmt
        return copy
    except Exception:
        return None


def evaluate_manifest(m: Manifest) -> CaseResult:
    """로컬 파일 artifact 평가 — base64 응답 평가와 같은 자동 기준을 공유한다."""
    case = case_from_manifest(m)
    files = [m.detail_page, m.main, *m.gallery, m.trace_path]
    checks = [check_output_files(files)]
    checks += _image_checks(case, _open_or_none(m.detail_page),
                            _open_or_none(m.main),
                            [_open_or_none(g) for g in m.gallery])
    try:
        trace = json.loads(Path(m.trace_path).read_text(encoding="utf-8"))
    except Exception:
        trace = {}
    checks += _auto_trace_checks(case, {"trace": trace, "warnings": list(m.warnings)})
    return CaseResult(case=case, auto_checks=tuple(checks),
                      manual_reviews=manual_reviews_for(case))


# ── 수동 평가 rubric (고정 한국어 — 사용자 입력·프롬프트 미포함) ────────────────
RUBRIC = {
    ManualCriterion.PRODUCT_ACCURACY:
        "제품이 업로드 실물과 같은 물건으로 보이는가(형상·색·재질). 다른 제품·중복 생성 없음",
    ManualCriterion.PROPORTION_PORTS_LOGO:
        "본체 비율이 실물과 유사한가. 포트 수·배치, 로고·마킹이 추가·삭제·이동되지 않았는가",
    ManualCriterion.BACKGROUND_HARMONY:
        "배경 톤·조명·색온도가 제품과 어울리는가. 요청한 배경 유형·무드가 반영됐는가",
    ManualCriterion.GROUNDING_SHADOW:
        "제품이 표면에 실제로 놓인 듯한가. 접촉 그림자 정렬, 부유감·오려붙인 티 없음",
    ManualCriterion.COMPOSITION:
        "역할별 좌우 구도(left/right/center)가 반영됐는가. 소품이 제품·카피를 침범하지 않는가",
    ManualCriterion.COPY_READABILITY:
        "Hero 카피가 잘리거나 배경에 묻히지 않는가. 이미지 안에 원치 않는 문자가 없는가",
    ManualCriterion.NATURAL_ACCURACY:
        "(natural 전용) 재렌더된 제품의 정체성·포트·비율이 허용 범위인가 — 지시는 보장이 아님",
    ManualCriterion.FEATURE_ACCURACY:
        "feature 컷들이 각 역할(빌드·연결 등)의 의도를 정확히 보여주는가. 잘못된 면·기능 없음",
    ManualCriterion.SECTION_CONTINUITY:
        "상세페이지 섹션 흐름이 자연스러운가. 톤·조명이 컷 간 튀지 않고 이어지는가",
    ManualCriterion.CUTOUT_EDGE_QUALITY:
        "(preserve 전용) 누끼 경계가 깨끗한가 — halo·잔여 배경·톱니 없음",
    ManualCriterion.SOURCE_ANGLE_PRESERVED:
        "(preserve 전용) 각 컷이 업로드된 실제 각도 사진을 그대로 사용했는가(각도 발명 없음)",
    ManualCriterion.RERENDER_DISTORTION:
        "(natural 전용) 재렌더로 비율·형상이 실물 대비 왜곡되지 않았는가 — 프롬프트 지시는 결과 보장이 아니다",
    ManualCriterion.LIGHTING_PERSPECTIVE_INTEGRATION:
        "(natural 전용) 제품 조명·원근이 배경과 한 장면처럼 통합됐는가 — 프롬프트 지시는 결과 보장이 아니다",
}


def rubric_for(criterion: ManualCriterion) -> str:
    if not isinstance(criterion, ManualCriterion):
        raise ValueError(f"criterion은 ManualCriterion이어야 한다: {criterion!r}")
    return RUBRIC[criterion]


# ── 12조합 coverage: 아키타입 6종 × 연출 모드 2종 ─────────────────────────────
_ARCHETYPE_CATEGORY = {
    "tech": "컴퓨터·노트북·조립PC", "fashion": "패션·잡화", "beauty": "뷰티",
    "food": "식품", "living": "가구·조명", "general": "반려·취미·사무",
}
_MODES = ("preserve", "natural")


def standard_cases() -> tuple:
    """12조합 표준 케이스 — 아키타입 6종 × preserve/natural. 전부 순수 파생(API 0회)."""
    cases = []
    for arch in _ARCHETYPES:
        for mode in _MODES:
            cases.append(case_for(
                f"{arch}_{mode}", _ARCHETYPE_CATEGORY[arch], presentation_mode=mode,
                n_product=2, product_angles=["정면", "후면"],
                n_usage=1, usage_angles=["사용장면"]))
    return tuple(cases)


def coverage(cases) -> dict:
    """(archetype, mode) 12조합 커버리지 — 어떤 조합이 비었는지 보고한다."""
    from baseline.archetypes import resolve_archetype
    covered = {(resolve_archetype(c.category), c.presentation_mode) for c in cases}
    want = [(a, m) for a in _ARCHETYPES for m in _MODES]
    missing = [f"{a}/{m}" for a, m in want if (a, m) not in covered]
    return {"required": len(want), "covered": len(want) - len(missing),
            "missing": missing, "complete": not missing}


# ── report ───────────────────────────────────────────────────────────────────
_STATUS_MARK = {ReviewStatus.PENDING: "[ ]", ReviewStatus.PASS: "[x]",
                ReviewStatus.CONDITIONAL: "[~]", ReviewStatus.FAIL: "[✗]",
                ReviewStatus.NOT_APPLICABLE: "[-]"}


def render_report(results) -> str:
    """사람이 읽는 평가 리포트(markdown). 자동 결과 + 수동 rubric 체크리스트.

    pending은 pass로 표기되지 않는다 — summarize와 같은 게이팅을 그대로 보여준다.
    """
    agg = summarize(results)
    lines = ["# 다제품 품질 평가 리포트", "",
             f"전체 판정: **{agg['overall']}**"
             " (수동 평가가 pending이면 pass가 될 수 없음)", "",
             "| case | category | mode | overall |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.case.case_id} | {r.case.category} | "
                     f"{r.case.presentation_mode} | {r.overall} |")
    cov = coverage([r.case for r in results])
    lines += ["", f"12조합 커버리지: {cov['covered']}/{cov['required']}"
              + ("" if cov["complete"] else f" — 누락: {', '.join(cov['missing'])}")]
    for r in results:
        lines += ["", f"## {r.case.case_id} — {r.overall}"]
        failed = [c for c in r.auto_checks if not c.ok]
        if failed:
            lines.append("자동 실패:")
            lines += [f"- {c.code.value}: {c.measured}" for c in failed]
        else:
            lines.append(f"자동 검증: {len(r.auto_checks)}건 전부 통과")
        lines.append("")
        lines.append("수동 육안 평가:")
        for m in r.manual_reviews:
            note = f" — {m.note}" if m.note else ""
            lines.append(f"- {_STATUS_MARK[m.status]} {m.criterion.value}: "
                         f"{RUBRIC[m.criterion]}{note}")
    return "\n".join(lines) + "\n"


# ── 수동 평가 입력(JSON) 로드·적용 ────────────────────────────────────────────
def load_manual(path, results) -> list:
    """수동 평가 JSON을 결과 목록에 적용해 새 결과 목록을 반환한다.

    형식: {case_id: {criterion_value: {"status": "...", "note": "..."}}}
    알 수 없는 case_id·criterion·status, dict가 아닌 항목, 문자열 아닌 note는 ValueError.
    입력되지 않은 pending 항목은 그대로 pending으로 남는다.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"manual JSON 파싱 실패: {type(e).__name__}") from None
    if not isinstance(data, dict):
        raise ValueError("manual 최상위는 object여야 한다")
    by_id = {r.case.case_id: r for r in results}
    unknown_cases = [c for c in data if c not in by_id]
    if unknown_cases:
        raise ValueError(f"알 수 없는 case_id: {unknown_cases}")
    out = []
    for r in results:
        if r.case.case_id not in data:      # JSON에 없으면 기존 pending 유지
            out.append(r)
            continue
        entries = data[r.case.case_id]
        if not isinstance(entries, dict):   # []·""·0·null·false 전부 거부
            raise ValueError(
                f"{r.case.case_id} 항목은 object여야 한다: {type(entries).__name__}")
        if not entries:                     # 빈 object는 허용 — pending 유지
            out.append(r)
            continue
        verdicts = {}
        for crit_key, entry in entries.items():
            try:
                crit = ManualCriterion(crit_key)
            except ValueError:
                raise ValueError(f"알 수 없는 criterion: {crit_key!r}") from None
            if not isinstance(entry, dict):
                raise ValueError(f"{crit_key} 값은 object여야 한다: {entry!r}")
            status = entry.get("status")
            if not isinstance(status, str) or status not in [s.value for s in ReviewStatus]:
                raise ValueError(f"{crit_key} status 허용 외: {status!r}")
            note = entry.get("note", "")
            if not isinstance(note, str):
                raise ValueError(f"{crit_key} note는 문자열이어야 한다: {note!r}")
            verdicts[crit] = (status, note)
        out.append(apply_manual(r, verdicts))
    return out


# ── 구조화 리포트 (JSON) ─────────────────────────────────────────────────────
def build_report(results) -> dict:
    """JSON 직렬화 가능한 구조화 리포트. **pending을 pass로 표기하지 않는다** —
    pending이 남아 있으면 evaluation_state=pending·verdict=None이다.
    프롬프트 원문·절대 파일 경로는 포함하지 않는다(safe dict만 사용)."""
    agg = summarize(results)
    pending = agg["overall"] == "pending"
    return {
        "schema_version": "1.0",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_state": "pending" if pending else "complete",
        "verdict": None if pending else agg["overall"],
        "coverage": coverage([r.case for r in results]),
        "cases": [r.to_safe_dict() for r in results],
    }


# ── CLI: manifest들을 평가하고 리포트 출력 (API 0회) ──────────────────────────
def main(argv=None) -> int:
    """python -m evaluation.quality_eval m1.json … [--manual m.json]
       [--report out.md] [--json-report out.json]

    순서 고정: manifest 평가 → manual 적용 → 집계/리포트.
    종료 코드: 1=fail, 2=pending(수동 평가 미완 — pass 아님), 0=pass/conditional.
    """
    import argparse
    ap = argparse.ArgumentParser(prog="evaluation.quality_eval",
                                 description="다제품 품질 평가 (로컬, API 0회)")
    ap.add_argument("manifests", nargs="+", help="manifest JSON 경로들")
    ap.add_argument("--manual", default=None, help="수동 평가 JSON 경로")
    ap.add_argument("--report", default=None, help="markdown 리포트 저장 경로")
    ap.add_argument("--json-report", default=None, help="구조화 JSON 리포트 저장 경로")
    args = ap.parse_args(argv)

    results = [evaluate_manifest(load_manifest(m)) for m in args.manifests]
    if args.manual:
        results = load_manual(args.manual, results)
    agg = summarize(results)
    for r in results:
        print(f"[{r.overall}] {r.case.case_id}")
    cov = coverage([r.case for r in results])
    print(f"전체: {agg['overall']} | 커버리지 {cov['covered']}/{cov['required']}")
    if args.report:
        Path(args.report).write_text(render_report(results), encoding="utf-8")
        print(f"리포트 저장: {args.report}")
    if args.json_report:
        Path(args.json_report).write_text(
            json.dumps(build_report(results), ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"JSON 리포트 저장: {args.json_report}")
    return {"fail": 1, "pending": 2}.get(agg["overall"], 0)


if __name__ == "__main__":
    raise SystemExit(main())
