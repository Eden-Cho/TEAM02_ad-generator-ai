"""데모 모드 자산 로더 — 사전 생성 샘플 패키지를 manifest 단일 기준으로 검증해 읽는다.

**이 모듈은 HTTP 클라이언트를 import하지 않는다.** 데모 화면은 이 모듈만 쓰므로 데모 모드에서
generate·preview를 포함한 **HTTP 호출이 구조적으로 0회**다(호출할 코드가 없다).

자산 경로는 `MODEL_V2_DEMO_ASSET_DIR` 환경변수로 주입한다(이미지·ZIP은 저장소에 넣지 않는다).

검증은 **폐쇄형**이다 — 아래 중 하나라도 위반이면 패키지 **전체를 거부**하고, 화면에는 경로·해시·
manifest 값·예외 원문이 없는 고정 문구만 낸다.

무결성:
  - `sha256`은 64자리 소문자 hex이며, 실제 파일을 **스트리밍 해싱**한 값과 일치해야 한다
  - `bytes`·`image.width`·`image.height`·`image.format`이 실제 파일과 일치해야 한다
  - `counts.image_files`·`total_bytes`가 실제 집계와 일치해야 한다
스키마:
  - product·mode·asset_type·verdict·role·scope·fix_stage는 허용값만
  - product_label·purpose·known_limits·package·created·verdict_legend 타입·빈 값 검사
조합:
  - fix_single_cut(before) → scope=single_cut_only, verdict=error_reference_only,
    full_page_regenerated=False, role 필수
  - fix_single_cut(after)  → scope=single_cut_only, verdict=fixed_single_cut,
    full_page_regenerated=False, role 필수
  - 전체 결과 → scope=full_result_set, fix_stage 없음, full_page_regenerated 없음,
    fixed_single_cut 판정 금지
  - detail_page·main_thumbnail → role 없음 / gallery_cut·fix_single_cut → 허용 role 필수
경로·중복:
  - 패키지 root 자체 심볼릭 링크 거부, manifest·패키지 내부 심볼릭 링크 거부
  - 상대경로 강제(절대경로·`..` 이탈·백슬래시·`~`), 동일 상대경로 중복 거부
  - 동일 (product, role, fix_stage) 수정 컷 중복 거부
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

from PIL import Image

ENV_ASSET_DIR = "MODEL_V2_DEMO_ASSET_DIR"

# 고정 오류 문구 — 경로·해시·manifest 값·예외 원문을 담지 않는다.
ERR_NOT_CONFIGURED = ("데모 샘플 경로가 설정되지 않았습니다. "
                      f"{ENV_ASSET_DIR} 환경변수를 지정한 뒤 다시 실행하세요.")
ERR_INVALID_PACKAGE = "데모 샘플 패키지를 읽을 수 없습니다. 패키지 구성을 확인하세요."

# ── 폐쇄형 허용값 (현재 6C 패키지에서 실제 사용하는 값만) ─────────────────────
_PRODUCTS = ("apple", "sunstick", "macmini")
_MODES = ("preserve", "natural")
_ASSET_TYPES = ("detail_page", "main_thumbnail", "gallery_cut", "fix_single_cut")
_VERDICTS = ("usable_reference", "review_required", "error_reference_only",
             "fixed_single_cut")
_ROLES = ("hero", "build", "connectivity", "lifestyle", "ingredient", "texture",
          "serving")
_SCOPES = ("full_result_set", "single_cut_only")
_FIX_STAGES = ("before", "after")
_ALLOWED_FORMATS = ("PNG", "JPEG")

_ROLELESS_TYPES = ("detail_page", "main_thumbnail")
_ROLE_REQUIRED_TYPES = ("gallery_cut", "fix_single_cut")
_FULL_RESULT_VERDICTS = ("usable_reference", "review_required", "error_reference_only")
# fix_stage → (요구 verdict, 요구 scope)
_FIX_STAGE_RULES = {"before": ("error_reference_only", "single_cut_only"),
                    "after": ("fixed_single_cut", "single_cut_only")}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_TOP = ("package", "created", "files", "counts", "total_bytes")
_REQUIRED_FILE = ("path", "product", "product_label", "mode", "asset_type", "verdict",
                  "purpose", "known_limits", "image", "sha256", "bytes", "scope")

# 정렬 순서
_PRODUCT_ORDER = _PRODUCTS
_MODE_ORDER = _MODES
_ASSET_ORDER = _ASSET_TYPES

ERROR_VERDICT = "error_reference_only"


class DemoAssetError(Exception):
    """검증 실패 — 원문을 담지 않는다(호출부가 고정 문구로 대체)."""


def _fail():
    raise DemoAssetError()


def _req(cond):
    if not cond:
        _fail()


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _pos_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


@dataclass
class DemoAsset:
    rel_path: str
    abs_path: Path
    product: str
    product_label: str
    mode: str
    asset_type: str
    role: Optional[str]
    purpose: str
    verdict: str
    known_limits: list
    scope: Optional[str] = None
    fix_stage: Optional[str] = None
    full_page_regenerated: Optional[bool] = None
    width: int = 0
    height: int = 0
    image_format: str = ""
    sha256: str = ""
    bytes_size: int = 0

    @property
    def is_error_reference(self) -> bool:
        return self.verdict == ERROR_VERDICT


@dataclass
class DemoPackage:
    name: str
    created: str
    warnings: list = field(default_factory=list)
    verdict_legend: dict = field(default_factory=dict)
    assets: list = field(default_factory=list)


def asset_dir() -> Path:
    raw = os.getenv(ENV_ASSET_DIR, "")
    if not raw or not raw.strip():
        raise DemoAssetError()
    return Path(raw.strip())


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        _fail()
    return h.hexdigest()


def _safe_target(root: Path, rel) -> Path:
    """manifest의 상대경로를 안전하게 해석 — 절대경로·이탈·심볼릭 링크를 모두 거부."""
    _req(_nonempty_str(rel))
    _req("\\" not in rel and not rel.startswith("/") and not rel.startswith("~"))
    _req(not Path(rel).is_absolute() and not PurePosixPath(rel).is_absolute())
    parts = PurePosixPath(rel).parts
    _req(parts and not any(p in ("..", "", ".") for p in parts))
    # 각 구성요소가 심볼릭 링크면 거부(루트 밖으로 나가는 링크 차단)
    cur = root
    for p in parts:
        cur = cur / p
        if cur.is_symlink():
            _fail()
    target = root / Path(*parts)
    try:
        resolved = target.resolve()
        root_resolved = root.resolve()
    except OSError:
        _fail()
    _req(root_resolved in resolved.parents)
    _req(resolved.is_file())
    return target


def _check_file_integrity(path: Path, e: dict) -> tuple:
    """실제 파일과 manifest 선언값(sha256·bytes·해상도·형식)을 대조한다."""
    img = e["image"]
    declared_fmt = img.get("format")
    _req(declared_fmt in _ALLOWED_FORMATS)
    _req(_pos_int(img.get("width")) and _pos_int(img.get("height")))
    _req(_pos_int(e.get("bytes")))
    _req(isinstance(e.get("sha256"), str) and _SHA256_RE.match(e["sha256"]))

    try:
        actual_size = path.stat().st_size
    except OSError:
        _fail()
    _req(actual_size == e["bytes"])

    try:
        with Image.open(path) as im:
            im.verify()                      # 손상 검출
        with Image.open(path) as im2:
            fmt, w, h = im2.format, im2.width, im2.height
    except Exception:
        _fail()
    _req(fmt == declared_fmt)
    _req(w == img["width"] and h == img["height"])
    _req(_sha256_file(path) == e["sha256"])   # 스트리밍 해싱 대조
    return fmt, w, h, actual_size


def _check_schema(e: dict) -> None:
    """폐쇄형 enum·타입·빈 값 검사."""
    _req(e["product"] in _PRODUCTS)
    _req(e["mode"] in _MODES)
    _req(e["asset_type"] in _ASSET_TYPES)
    _req(e["verdict"] in _VERDICTS)
    _req(e["scope"] in _SCOPES)
    _req(_nonempty_str(e["product_label"]))
    _req(_nonempty_str(e["purpose"]))
    kl = e["known_limits"]
    _req(isinstance(kl, list) and kl and all(_nonempty_str(x) for x in kl))
    _req(isinstance(e["image"], dict))
    role = e.get("role")
    _req(role is None or role in _ROLES)
    fs = e.get("fix_stage")
    _req(fs is None or fs in _FIX_STAGES)
    fpr = e.get("full_page_regenerated")
    _req(fpr is None or isinstance(fpr, bool))


def _check_combination(e: dict) -> None:
    """asset_type × scope × fix_stage × verdict × role 조합 폐쇄 검증."""
    at, verdict = e["asset_type"], e["verdict"]
    role, fs, scope = e.get("role"), e.get("fix_stage"), e["scope"]
    fpr = e.get("full_page_regenerated")

    if at == "fix_single_cut":
        _req(fs in _FIX_STAGE_RULES)
        want_verdict, want_scope = _FIX_STAGE_RULES[fs]
        _req(verdict == want_verdict)
        _req(scope == want_scope)
        _req(fpr is False)                    # 전체 재생성이 아님을 명시해야 한다
    else:
        _req(scope == "full_result_set")
        _req(fs is None)
        _req(fpr is None)
        _req(verdict in _FULL_RESULT_VERDICTS)   # 전체 결과에 fixed_single_cut 금지

    if at in _ROLELESS_TYPES:
        _req(role is None)
    elif at in _ROLE_REQUIRED_TYPES:
        _req(role in _ROLES)


def _entry_to_asset(root: Path, e) -> DemoAsset:
    _req(isinstance(e, dict))
    for k in _REQUIRED_FILE:
        _req(k in e)
    _check_schema(e)
    _check_combination(e)
    target = _safe_target(root, e["path"])
    fmt, w, h, size = _check_file_integrity(target, e)
    return DemoAsset(
        rel_path=e["path"], abs_path=target, product=e["product"],
        product_label=e["product_label"], mode=e["mode"],
        asset_type=e["asset_type"], role=e.get("role"), purpose=e["purpose"],
        verdict=e["verdict"], known_limits=list(e["known_limits"]),
        scope=e["scope"], fix_stage=e.get("fix_stage"),
        full_page_regenerated=e.get("full_page_regenerated"),
        width=w, height=h, image_format=fmt, sha256=e["sha256"], bytes_size=size)


def load_package(root: Optional[Path] = None) -> DemoPackage:
    """manifest를 단일 기준으로 패키지를 검증·적재한다. 위반은 DemoAssetError."""
    root = root or asset_dir()
    _req(isinstance(root, Path))
    _req(not root.is_symlink())               # 패키지 root 자체가 심볼릭 링크면 거부
    _req(root.is_dir())

    mf = root / "manifest.json"
    _req(not mf.is_symlink() and mf.is_file())
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        _fail()
    _req(isinstance(data, dict))
    for k in _REQUIRED_TOP:
        _req(k in data)
    _req(_nonempty_str(data["package"]))
    _req(_nonempty_str(data["created"]))

    files = data["files"]
    _req(isinstance(files, list) and files)

    assets = []
    seen_paths = set()
    seen_fix = set()
    for e in files:
        a = _entry_to_asset(root, e)
        key = str(PurePosixPath(a.rel_path))
        _req(key not in seen_paths)           # 동일 상대경로 중복 거부
        seen_paths.add(key)
        if a.asset_type == "fix_single_cut":
            fk = (a.product, a.role, a.fix_stage)
            _req(fk not in seen_fix)          # 동일 (product, role, stage) 중복 거부
            seen_fix.add(fk)
        assets.append(a)

    # 집계 대조 — manifest가 선언한 수치와 실제 결과가 같아야 한다
    counts = data["counts"]
    _req(isinstance(counts, dict))
    _req(counts.get("image_files") == len(assets))
    _req(data["total_bytes"] == sum(a.bytes_size for a in assets))

    warnings = data.get("warnings", [])
    _req(isinstance(warnings, list) and all(_nonempty_str(x) for x in warnings))
    legend = data.get("verdict_legend", {})
    _req(isinstance(legend, dict))
    _req(all(_nonempty_str(k) and _nonempty_str(v) for k, v in legend.items()))

    return DemoPackage(name=data["package"], created=data["created"],
                       warnings=list(warnings), verdict_legend=dict(legend),
                       assets=assets)


# ── 정렬·그룹핑 (화면 구성용, 결정론적) ───────────────────────────────────────
def _product_key(p: str) -> tuple:
    return (_PRODUCT_ORDER.index(p) if p in _PRODUCT_ORDER else len(_PRODUCT_ORDER), p)


def _mode_key(m: str) -> tuple:
    return (_MODE_ORDER.index(m) if m in _MODE_ORDER else len(_MODE_ORDER), m)


def _asset_key(a: DemoAsset) -> tuple:
    return (_ASSET_ORDER.index(a.asset_type) if a.asset_type in _ASSET_ORDER
            else len(_ASSET_ORDER), a.role or "", a.rel_path)


def showcase_assets(pkg: DemoPackage) -> list:
    """기본 전시 대상 — 오류 비교용(error_reference_only)과 수정 단일 컷은 제외한다."""
    return [a for a in pkg.assets
            if a.asset_type != "fix_single_cut" and not a.is_error_reference]


def error_assets(pkg: DemoPackage) -> list:
    """오류 비교용 전용 — 기본 화면에 노출하지 않는다(별도 영역에서 경고와 함께)."""
    return sorted([a for a in pkg.assets
                   if a.asset_type != "fix_single_cut" and a.is_error_reference],
                  key=_asset_key)


def products(pkg: DemoPackage) -> list:
    """기본 전시 대상의 제품 목록(결정론적 순서)."""
    seen = {}
    for a in showcase_assets(pkg):
        seen.setdefault(a.product, a.product_label)
    return sorted(seen.items(), key=lambda kv: _product_key(kv[0]))


def modes_for(pkg: DemoPackage, product: str) -> list:
    ms = {a.mode for a in showcase_assets(pkg) if a.product == product}
    return sorted(ms, key=_mode_key)


def set_assets(pkg: DemoPackage, product: str, mode: str) -> list:
    return sorted([a for a in showcase_assets(pkg)
                   if a.product == product and a.mode == mode], key=_asset_key)


def fix_pairs(pkg: DemoPackage) -> list:
    """(before, after) 쌍 — (product, role)로 매칭.

    중복은 load_package에서 이미 거부되지만, 여기서도 **조용히 덮어쓰지 않고** 방어적으로
    거부한다(다른 경로로 만들어진 DemoPackage에도 같은 계약이 적용되도록).
    """
    befores, afters = {}, {}
    for a in pkg.assets:
        if a.asset_type != "fix_single_cut":
            continue
        key = (a.product, a.role or "")
        bucket = befores if a.fix_stage == "before" else afters
        _req(key not in bucket)               # 덮어쓰기 금지
        bucket[key] = a
    keys = sorted(set(befores) & set(afters),
                  key=lambda k: (_product_key(k[0]), k[1]))
    return [(befores[k], afters[k]) for k in keys]
