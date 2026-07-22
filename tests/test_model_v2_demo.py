"""데모 모드 검증 — manifest 폐쇄 계약(무결성·스키마·조합·경로/중복) + 실제 app 배선(AppTest).

전부 hermetic(임시 디렉터리에 합성 샘플 패키지를 만들어 사용)이며, 실제 LLM·이미지 API·외부
HTTP 호출은 0회다. 데모 모듈은 HTTP 클라이언트를 import하지 않아 구조적으로 호출이 불가능하다.
실제 6C 패키지가 있으면 38장 전량(SHA·bytes·해상도·counts·total_bytes)을 추가로 검증한다.
"""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

_REPO = Path(__file__).resolve().parent.parent
_FRONTEND = _REPO / "frontend"
if str(_FRONTEND) not in sys.path:
    sys.path.insert(0, str(_FRONTEND))

import model_v2_demo as demo  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest
    import streamlit.testing.v1.element_tree as _et
    _HAS_APPTEST = True
    # AppTest가 image 엘리먼트를 추적하는가(1.51.0은 미지원 — file_uploader와 같은 버전 격차).
    _TRACKS_IMAGES = hasattr(_et, "Image")
except Exception:                        # pragma: no cover
    _HAS_APPTEST = False
    _TRACKS_IMAGES = False

_DEMO_APP = str(_FRONTEND / "model_v2_demo_app.py")
_REAL_PKG = Path("/Users/who/Desktop/code_it/project/model_v2_handoff_samples_20260722")


def _write_img(path: Path, fmt: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (120, 120, 120)).save(path, fmt)


def _sync_entry(e: dict, root: Path, dims: bool = False):
    """항목의 sha256·bytes(선택적으로 해상도/형식)를 실제 파일에 맞춘다."""
    p = root / e["path"]
    data = p.read_bytes()
    e["bytes"] = len(data)
    e["sha256"] = hashlib.sha256(data).hexdigest()
    if dims:
        with Image.open(p) as im:
            e["image"] = {"width": im.width, "height": im.height, "format": im.format}


def _entry(path, product, mode, asset_type, verdict, fmt, role=None,
           scope="full_result_set", **extra):
    e = {"path": path, "product": product, "product_label": product.upper(),
         "mode": mode, "asset_type": asset_type, "role": role,
         "purpose": "테스트 자산", "verdict": verdict, "known_limits": ["한계 예시"],
         "scope": scope, "image": {"width": 8, "height": 8, "format": fmt}}
    e.update(extra)
    return e


def build_package(root: Path, mutate=None, recount: bool = True) -> Path:
    """합성 샘플 패키지 생성 — 정상 2세트 + 오류 1컷 + 수정 전/후 1쌍.

    이미지를 먼저 쓰고 실제 sha256·bytes를 채운 뒤 mutate를 적용한다. recount=True면
    최종 files 목록 기준으로 counts·total_bytes를 다시 계산해, 구조 변형 테스트가
    집계 불일치 때문에 엉뚱하게 거부되지 않도록 한다.
    """
    files = [
        _entry("full_results/apple_preserve/detail_page.png", "apple", "preserve",
               "detail_page", "usable_reference", "PNG"),
        _entry("full_results/apple_preserve/main.jpg", "apple", "preserve",
               "main_thumbnail", "usable_reference", "JPEG"),
        _entry("full_results/apple_preserve/gallery_hero.jpg", "apple", "preserve",
               "gallery_cut", "usable_reference", "JPEG", role="hero"),
        _entry("full_results/apple_natural/detail_page.png", "apple", "natural",
               "detail_page", "review_required", "PNG"),
        _entry("full_results/sunstick_natural_ERROR_DO_NOT_SHIP/gallery_texture.jpg",
               "sunstick", "natural", "gallery_cut", "error_reference_only", "JPEG",
               role="texture"),
        _entry("fix_single_cuts/apple_ingredient_before.jpg", "apple", "natural",
               "fix_single_cut", "error_reference_only", "JPEG", role="ingredient",
               scope="single_cut_only", fix_stage="before", full_page_regenerated=False),
        _entry("fix_single_cuts/apple_ingredient_after_v2.png", "apple", "natural",
               "fix_single_cut", "fixed_single_cut", "PNG", role="ingredient",
               scope="single_cut_only", fix_stage="after", full_page_regenerated=False),
    ]
    for e in files:
        _write_img(root / e["path"], e["image"]["format"])
        _sync_entry(e, root)
    manifest = {"package": "test_samples", "created": "2026-07-22",
                "warnings": ["오류 세트는 운영 사용 금지"],
                "verdict_legend": {"usable_reference": "사용 가능"},
                "counts": {"image_files": len(files)},
                "total_bytes": sum(e["bytes"] for e in files),
                "files": files}
    if mutate:
        mutate(manifest, root)
    if recount and isinstance(manifest.get("files"), list):
        def _size(e):
            # mutate가 path를 지우거나 망가뜨렸을 수 있다 — 집계는 방어적으로 건너뛴다.
            if not isinstance(e, dict) or not isinstance(e.get("path"), str):
                return 0
            try:
                p = root / e["path"]
                return p.stat().st_size if p.is_file() else 0
            except OSError:
                return 0
        manifest.setdefault("counts", {})
        if isinstance(manifest["counts"], dict):
            manifest["counts"]["image_files"] = len(manifest["files"])
        manifest["total_bytes"] = sum(_size(e) for e in manifest["files"])
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


class _PkgTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "pkg"
        self.root.mkdir()

    def _load(self, mutate=None, **kw):
        build_package(self.root, mutate, **kw)
        return demo.load_package(self.root)

    def _expect_reject(self, mutate, **kw):
        build_package(self.root, mutate, **kw)
        with self.assertRaises(demo.DemoAssetError):
            demo.load_package(self.root)


class LoadAndGroupTest(_PkgTestCase):
    def test_loads_and_sorts(self):
        pkg = self._load()
        self.assertEqual(pkg.name, "test_samples")
        self.assertEqual(len(pkg.assets), 7)
        show = demo.showcase_assets(pkg)
        self.assertEqual(len(show), 4)
        self.assertTrue(all(not a.is_error_reference for a in show))
        self.assertTrue(all(a.asset_type != "fix_single_cut" for a in show))

    def test_error_set_excluded_from_default_view(self):
        pkg = self._load()
        err_paths = {a.rel_path for a in demo.error_assets(pkg)}
        show_paths = {a.rel_path for a in demo.showcase_assets(pkg)}
        self.assertIn("full_results/sunstick_natural_ERROR_DO_NOT_SHIP/gallery_texture.jpg",
                      err_paths)
        self.assertFalse(err_paths & show_paths, "오류본이 기본 화면에 섞이면 안 된다")
        self.assertNotIn("sunstick", [p for p, _ in demo.products(pkg)])

    def test_set_assets_deterministic_order(self):
        pkg = self._load()
        order = [a.asset_type for a in demo.set_assets(pkg, "apple", "preserve")]
        self.assertEqual(order, ["detail_page", "main_thumbnail", "gallery_cut"])

    def test_fix_pairs_matched(self):
        pkg = self._load()
        pairs = demo.fix_pairs(pkg)
        self.assertEqual(len(pairs), 1)
        before, after = pairs[0]
        self.assertEqual(before.fix_stage, "before")
        self.assertEqual(after.fix_stage, "after")
        self.assertEqual(after.verdict, "fixed_single_cut")
        self.assertIs(after.full_page_regenerated, False)
        self.assertEqual(after.scope, "single_cut_only")

    def test_asset_dir_env(self):
        with mock.patch.dict(os.environ, {demo.ENV_ASSET_DIR: str(self.root)}):
            self.assertEqual(demo.asset_dir(), self.root)
        with mock.patch.dict(os.environ, {demo.ENV_ASSET_DIR: "   "}):
            with self.assertRaises(demo.DemoAssetError):
                demo.asset_dir()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(demo.ENV_ASSET_DIR, None)
            with self.assertRaises(demo.DemoAssetError):
                demo.asset_dir()


class ManifestIntegrityTest(_PkgTestCase):
    """무결성 — sha256·bytes·해상도·형식·집계가 실제 파일과 다르면 패키지 전체 거부."""

    def test_wrong_sha256_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"sha256": "0" * 64}))

    def test_malformed_sha256_rejected(self):
        for bad in ("deadbeef", "X" * 64, "A" * 64, "", None, 123, "0" * 63, "0" * 65):
            with self.subTest(sha=bad):
                self.setUp()
                self._expect_reject(lambda m, r, b=bad: m["files"][0].update({"sha256": b}))

    def test_wrong_bytes_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"bytes": 999999}))

    def test_nonpositive_bytes_rejected(self):
        for bad in (0, -1, True, "12", None):
            with self.subTest(b=bad):
                self.setUp()
                self._expect_reject(lambda m, r, v=bad: m["files"][0].update({"bytes": v}))

    def test_wrong_dimensions_rejected(self):
        self._expect_reject(
            lambda m, r: m["files"][0]["image"].update({"width": 9999, "height": 1}))

    def test_nonpositive_dimensions_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0]["image"].update({"width": 0}))

    def test_counts_mismatch_rejected(self):
        self._expect_reject(
            lambda m, r: m["counts"].update({"image_files": 999}), recount=False)

    def test_total_bytes_mismatch_rejected(self):
        self._expect_reject(lambda m, r: m.update({"total_bytes": 1}), recount=False)

    def test_missing_counts_or_total_bytes_rejected(self):
        for key in ("counts", "total_bytes"):
            with self.subTest(key=key):
                self.setUp()
                self._expect_reject(lambda m, r, k=key: m.pop(k), recount=False)

    def test_corrupt_image_rejected(self):
        def mutate(m, r):
            (r / m["files"][0]["path"]).write_bytes(b"\x89PNG\r\n\x1a\nGARBAGE")
            _sync_entry(m["files"][0], r)     # sha·bytes는 맞춰 이미지 디코딩만 실패시킨다
        self._expect_reject(mutate)

    def test_format_mismatch_rejected(self):
        def mutate(m, r):
            p = r / m["files"][0]["path"]
            Image.new("RGB", (8, 8)).save(p, "JPEG")   # 선언은 PNG인데 실제는 JPEG
            _sync_entry(m["files"][0], r)
        self._expect_reject(mutate)

    def test_disallowed_declared_format_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0]["image"].update({"format": "GIF"}))


class ClosedSchemaTest(_PkgTestCase):
    """폐쇄형 enum·타입·빈 값."""

    def test_unknown_enum_values_rejected(self):
        cases = [("product", "banana"), ("mode", "weird"), ("asset_type", "nope"),
                 ("verdict", "totally_fine"), ("scope", "whatever"),
                 ("role", "unknown_role"), ("fix_stage", "midway")]
        for field, val in cases:
            with self.subTest(field=field, value=val):
                self.setUp()
                self._expect_reject(lambda m, r, f=field, v=val: m["files"][0].update({f: v}))

    def test_empty_or_wrong_typed_strings_rejected(self):
        cases = [("product_label", ""), ("product_label", "   "), ("product_label", 5),
                 ("purpose", ""), ("purpose", None),
                 ("known_limits", []), ("known_limits", ["", " "]),
                 ("known_limits", "x"), ("known_limits", [1]),
                 ("image", "x"), ("full_page_regenerated", "false")]
        for field, val in cases:
            with self.subTest(field=field, value=val):
                self.setUp()
                self._expect_reject(lambda m, r, f=field, v=val: m["files"][0].update({f: v}))

    def test_missing_required_field_rejected(self):
        for field in ("path", "product", "product_label", "mode", "asset_type",
                      "verdict", "purpose", "known_limits", "image", "sha256",
                      "bytes", "scope"):
            with self.subTest(field=field):
                self.setUp()
                self._expect_reject(lambda m, r, f=field: m["files"][0].pop(f))

    def test_top_level_empty_or_missing_rejected(self):
        for mut in (lambda m, r: m.pop("files"),
                    lambda m, r: m.update({"files": []}),
                    lambda m, r: m.pop("package"),
                    lambda m, r: m.update({"package": "  "}),
                    lambda m, r: m.pop("created"),
                    lambda m, r: m.update({"created": ""}),
                    lambda m, r: m.update({"warnings": [""]}),
                    lambda m, r: m.update({"warnings": "x"}),
                    lambda m, r: m.update({"verdict_legend": {"k": ""}}),
                    lambda m, r: m.update({"verdict_legend": {"": "v"}}),
                    lambda m, r: m.update({"verdict_legend": []})):
            with self.subTest(mut=str(mut)):
                self.setUp()
                self._expect_reject(mut, recount=False)

    def test_invalid_or_missing_manifest_rejected(self):
        for content in ("{not json", "[1,2]", '"str"', "null"):
            with self.subTest(content=content):
                self.setUp()
                build_package(self.root)
                (self.root / "manifest.json").write_text(content, encoding="utf-8")
                with self.assertRaises(demo.DemoAssetError):
                    demo.load_package(self.root)
        self.setUp()
        build_package(self.root)
        (self.root / "manifest.json").unlink()
        with self.assertRaises(demo.DemoAssetError):
            demo.load_package(self.root)

    def test_missing_dir_rejected(self):
        with self.assertRaises(demo.DemoAssetError):
            demo.load_package(self.tmp / "nope")


class FieldCombinationTest(_PkgTestCase):
    """asset_type × scope × fix_stage × verdict × role 조합."""

    def _fix_idx(self, m, stage):
        return next(i for i, e in enumerate(m["files"])
                    if e["asset_type"] == "fix_single_cut" and e.get("fix_stage") == stage)

    def test_full_result_cannot_be_fixed_single_cut_verdict(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"verdict": "fixed_single_cut"}))

    def test_full_result_cannot_have_fix_stage(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"fix_stage": "before"}))

    def test_full_result_cannot_have_full_page_regenerated(self):
        self._expect_reject(
            lambda m, r: m["files"][0].update({"full_page_regenerated": False}))

    def test_full_result_requires_full_result_set_scope(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"scope": "single_cut_only"}))

    def test_detail_and_main_must_have_no_role(self):
        for idx in (0, 1):     # detail_page, main_thumbnail
            with self.subTest(idx=idx):
                self.setUp()
                self._expect_reject(lambda m, r, i=idx: m["files"][i].update({"role": "hero"}))

    def test_gallery_requires_role(self):
        self._expect_reject(lambda m, r: m["files"][2].update({"role": None}))

    def test_fix_cut_requires_role(self):
        self._expect_reject(
            lambda m, r: m["files"][self._fix_idx(m, "after")].update({"role": None}))

    def test_fix_before_requires_error_verdict(self):
        self._expect_reject(lambda m, r: m["files"][self._fix_idx(m, "before")].update(
            {"verdict": "fixed_single_cut"}))

    def test_fix_after_requires_fixed_verdict(self):
        self._expect_reject(lambda m, r: m["files"][self._fix_idx(m, "after")].update(
            {"verdict": "usable_reference"}))

    def test_fix_cut_requires_single_cut_scope(self):
        self._expect_reject(lambda m, r: m["files"][self._fix_idx(m, "after")].update(
            {"scope": "full_result_set"}))

    def test_fix_cut_requires_full_page_regenerated_false(self):
        for bad in (True, None):
            with self.subTest(v=bad):
                self.setUp()
                self._expect_reject(lambda m, r, v=bad: m["files"][
                    self._fix_idx(m, "after")].update({"full_page_regenerated": v}))

    def test_fix_cut_requires_fix_stage(self):
        self._expect_reject(lambda m, r: m["files"][self._fix_idx(m, "after")].pop("fix_stage"))

    def test_error_reference_never_in_showcase(self):
        pkg = self._load()
        self.assertTrue(all(not a.is_error_reference for a in demo.showcase_assets(pkg)))


class PathAndDuplicateTest(_PkgTestCase):
    def test_path_traversal_rejected(self):
        (self.tmp / "outside.png").write_bytes(b"x")
        self._expect_reject(lambda m, r: m["files"][0].update({"path": "../outside.png"}))

    def test_nested_traversal_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update(
            {"path": "full_results/../../outside.png"}))

    def test_absolute_path_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"path": "/etc/hosts"}))

    def test_backslash_path_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update(
            {"path": "full_results\\apple_preserve\\detail_page.png"}))

    def test_home_expansion_rejected(self):
        self._expect_reject(lambda m, r: m["files"][0].update({"path": "~/secret.png"}))

    def test_symlinked_file_rejected(self):
        outside = self.tmp / "outside.png"
        _write_img(outside, "PNG")

        def mutate(m, r):
            link = r / "full_results" / "linked.png"
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(outside)
            m["files"][0]["path"] = "full_results/linked.png"
        self._expect_reject(mutate)

    def test_symlinked_directory_rejected(self):
        outside_dir = self.tmp / "outdir"
        outside_dir.mkdir()
        _write_img(outside_dir / "x.png", "PNG")

        def mutate(m, r):
            (r / "linkdir").symlink_to(outside_dir, target_is_directory=True)
            m["files"][0]["path"] = "linkdir/x.png"
        self._expect_reject(mutate)

    def test_package_root_symlink_rejected(self):
        build_package(self.root)
        link_root = self.tmp / "linkroot"
        link_root.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(demo.DemoAssetError):
            demo.load_package(link_root)

    def test_symlinked_manifest_rejected(self):
        build_package(self.root)
        real = self.tmp / "outside_manifest.json"
        shutil.move(str(self.root / "manifest.json"), str(real))
        (self.root / "manifest.json").symlink_to(real)
        with self.assertRaises(demo.DemoAssetError):
            demo.load_package(self.root)

    def test_missing_file_rejected(self):
        self._expect_reject(lambda m, r: (r / m["files"][0]["path"]).unlink(),
                            recount=False)

    def test_duplicate_relative_path_rejected(self):
        self._expect_reject(lambda m, r: m["files"].append(dict(m["files"][0])))

    def test_duplicate_path_normalized_form_rejected(self):
        def mutate(m, r):
            dup = dict(m["files"][0])
            dup["path"] = "full_results/apple_preserve/./detail_page.png"
            m["files"].append(dup)
        self._expect_reject(mutate)

    def test_duplicate_fix_cut_rejected(self):
        """동일 (product, role, fix_stage) 수정 컷 중복 — 조용한 덮어쓰기 대신 거부."""
        def mutate(m, r):
            src = next(e for e in m["files"] if e.get("fix_stage") == "after")
            dup = dict(src)
            dup["path"] = "fix_single_cuts/apple_ingredient_after_dup.png"
            _write_img(r / dup["path"], "PNG")
            _sync_entry(dup, r)
            m["files"].append(dup)
        self._expect_reject(mutate)

    def test_fix_pairs_does_not_silently_overwrite(self):
        """DemoPackage를 직접 구성해도 중복이면 조용히 덮어쓰지 않고 거부한다."""
        pkg = self._load()
        after = next(a for a in pkg.assets if a.fix_stage == "after")
        clone = demo.DemoAsset(
            rel_path="fix_single_cuts/other.png", abs_path=after.abs_path,
            product=after.product, product_label=after.product_label, mode=after.mode,
            asset_type="fix_single_cut", role=after.role, purpose=after.purpose,
            verdict=after.verdict, known_limits=list(after.known_limits),
            scope=after.scope, fix_stage="after", full_page_regenerated=False)
        pkg.assets.append(clone)
        with self.assertRaises(demo.DemoAssetError):
            demo.fix_pairs(pkg)


class NoHttpClientTest(unittest.TestCase):
    def test_no_http_client_imported(self):
        """데모 모듈은 HTTP 클라이언트를 import하지 않는다 — `ast`로 import 문만 검사."""
        banned = {"requests", "httpx", "urllib", "urllib3", "http", "socket",
                  "aiohttp", "model_v2_client"}
        for fname in ("model_v2_demo.py", "model_v2_demo_app.py"):
            with self.subTest(file=fname):
                tree = ast.parse((_FRONTEND / fname).read_text(encoding="utf-8"))
                mods = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        mods |= {a.name.split(".")[0] for a in node.names}
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.level == 0:
                            mods.add(node.module.split(".")[0])
                self.assertFalse(mods & banned, f"{fname}: 금지된 import {mods & banned}")
        self.assertFalse(hasattr(demo, "requests"))


@unittest.skipUnless(_REAL_PKG.is_dir(), "실제 6C 샘플 패키지 없음")
class RealPackageTest(unittest.TestCase):
    """실제 6C 패키지 38장 전량 — SHA·bytes·해상도·counts·total_bytes까지 검증."""

    def test_real_package_fully_validates(self):
        pkg = demo.load_package(_REAL_PKG)
        self.assertEqual(len(pkg.assets), 38)
        manifest = json.loads((_REAL_PKG / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["image_files"], 38)
        self.assertEqual(sum(a.bytes_size for a in pkg.assets), manifest["total_bytes"])
        self.assertEqual(sum(a.bytes_size for a in pkg.assets), 26882856)
        for a in pkg.assets:
            self.assertRegex(a.sha256, r"^[0-9a-f]{64}$")
            self.assertEqual(a.bytes_size, a.abs_path.stat().st_size)
            self.assertIn(a.image_format, ("PNG", "JPEG"))
            self.assertGreater(a.width, 0)
            self.assertGreater(a.height, 0)

    def test_real_package_grouping(self):
        pkg = demo.load_package(_REAL_PKG)
        self.assertEqual(len(demo.showcase_assets(pkg)), 28)
        self.assertEqual(len(demo.error_assets(pkg)), 6)
        self.assertEqual(len(demo.fix_pairs(pkg)), 2)
        self.assertFalse([a for a in demo.showcase_assets(pkg)
                          if "ERROR_DO_NOT_SHIP" in a.rel_path])
        self.assertEqual([p for p, _ in demo.products(pkg)],
                         ["apple", "sunstick", "macmini"])


@unittest.skipUnless(_HAS_APPTEST, "streamlit AppTest 미지원")
class DemoAppWiringTest(_PkgTestCase):
    """실제 데모 app 실행 — 자산 주입은 env, HTTP mock 자체가 필요 없다(호출 코드 없음)."""

    def _run_app(self):
        at = AppTest.from_file(_DEMO_APP)
        with mock.patch.dict(os.environ, {demo.ENV_ASSET_DIR: str(self.root)}):
            import streamlit as stmod
            stmod.cache_resource.clear()
            at.run(timeout=60)
        return at

    def test_app_renders_samples(self):
        build_package(self.root)
        at = self._run_app()
        self.assertEqual(len(list(at.exception)), 0)
        text = " ".join(str(e.value) for e in at.caption) + " ".join(
            str(e.value) for e in at.info)
        self.assertIn("사전 생성 샘플", text)
        self.assertIn("실제 API 호출 없음", text)

    @unittest.skipUnless(_TRACKS_IMAGES,
                         "이 Streamlit의 AppTest는 image 엘리먼트를 추적하지 않음 — 이미지 렌더 미검증")
    def test_app_renders_image_elements(self):
        build_package(self.root)
        at = self._run_app()
        self.assertGreater(len(at.get("image")), 0, "샘플 이미지가 표시돼야 한다")

    def test_app_shows_fixed_message_on_bad_package(self):
        build_package(self.root)
        (self.root / "manifest.json").write_text("{bad", encoding="utf-8")
        at = self._run_app()
        errs = " ".join(str(e.value) for e in at.error)
        self.assertIn(demo.ERR_INVALID_PACKAGE, errs)
        self.assertNotIn(str(self.root), errs)
        self.assertNotIn("json", errs.lower())

    def test_app_hides_details_on_integrity_failure(self):
        """무결성 실패도 동일한 고정 문구 — 해시·경로·manifest 값 비노출."""
        def mutate(m, r):
            m["files"][0]["sha256"] = "a" * 64
        build_package(self.root, mutate)
        at = self._run_app()
        errs = " ".join(str(e.value) for e in at.error)
        self.assertIn(demo.ERR_INVALID_PACKAGE, errs)
        self.assertNotIn("a" * 64, errs)
        self.assertNotIn(str(self.root), errs)
        self.assertNotIn("sha256", errs.lower())

    def test_app_warns_single_cut_scope(self):
        build_package(self.root)
        at = self._run_app()
        blob = " ".join(str(e.value) for e in at.error) + " ".join(
            str(e.value) for e in at.warning)
        self.assertIn("전체 상세페이지 재생성 결과가 아닙니다", blob)
        self.assertIn("운영에 사용하지 마세요", blob)

    def test_app_emits_no_deprecation_warning(self):
        """use_container_width 폐기 경고 없이 렌더돼야 한다(1.51·1.59 공통)."""
        import warnings
        build_package(self.root)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            at = self._run_app()
        self.assertEqual(len(list(at.exception)), 0)
        msgs = [str(w.message) for w in caught]
        self.assertFalse([m for m in msgs if "use_container_width" in m], msgs)


if __name__ == "__main__":
    unittest.main()
