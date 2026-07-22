"""워커 격리 검증 — 팀 model/과 model_v2/는 최상위 패키지명(baseline·composer·geo)이 겹쳐
한 인터프리터에 한 트리만 live다. 따라서 같은 프로세스에서 두 워커를 함께 import해 비교할 수
없다 → **각 워커를 독립 subprocess로 실행**하고, 각자 resolve된 절대경로로 baseline 출처를 판정한다.

- 팀 워커(main:app): baseline.__file__ 이 `/model/baseline/` 아래.
- v2 워커(main_v2:app): baseline.__file__ 이 `/model_v2/baseline/` 아래.
- 팀 endpoint mock 회귀도 팀 워커 subprocess 안에서 수행(run_pipeline mock, 200).
- 두 subprocess 모두 실제 LLM·이미지 API·CLIP 다운로드 0회(팀은 scorer를 가짜로 주입).
- 팀 파일이 upstream/main과 바이트 동일한지 재확인.
"""
import subprocess
import sys
import unittest
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent
_BACKEND = _REPO / "backend"


def _run(script: str) -> str:
    """격리 subprocess 실행 — 표준출력의 KEY=VALUE 마커를 문자열로 반환."""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_BACKEND), capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"subprocess 실패 rc={proc.returncode}\n--- stdout ---\n{proc.stdout}\n"
            f"--- stderr ---\n{proc.stderr[-2000:]}")
    return proc.stdout


def _markers(out: str) -> dict:
    d = {}
    for line in out.splitlines():
        if "=" in line and line.split("=", 1)[0].isupper():
            k, v = line.split("=", 1)
            d[k] = v
    return d


# 팀 워커: main.py와 동일한 sys.path. scorer는 가짜 주입(CLIP·torch·open_clip 미로드).
_TEAM_SCRIPT = r'''
import sys, io, types, json
from pathlib import Path
BACKEND = Path(r"{backend}").resolve()
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "model"))
fs = types.ModuleType("app.services.scorer")
fs.score_images = lambda *a, **k: {{}}
fs.attach_scores_to_langfuse = lambda *a, **k: None
sys.modules["app.services.scorer"] = fs
from unittest import mock
from PIL import Image
import main as team_main            # 팀 워커(model/ 트리)
import baseline
print("BASELINE=" + str(Path(baseline.__file__).resolve()))
from fastapi.testclient import TestClient
c = TestClient(team_main.app)
b = io.BytesIO(); Image.new("RGB", (20, 20)).save(b, "PNG"); png = b.getvalue()
spy = mock.Mock(return_value={{"page": Image.new("RGB", (2, 2)),
    "main": Image.new("RGB", (2, 2)), "gallery": [], "seconds": 1.0,
    "warnings": [], "trace": {{}}}})
req_json = json.dumps({{"product_name": "P", "category": "test"}})
with mock.patch.object(team_main, "run_pipeline", spy):
    r = c.post("/api/generate-detail-page",
               data={{"req_json": req_json}},
               files=[("product_files", ("p.png", png, "image/png"))])
print("STATUS=" + str(r.status_code))
print("PIPELINE_CALLS=" + str(spy.call_count))
'''

# v2 워커: main_v2가 model_v2/를 sys.path 맨 앞에 둔다.
_V2_SCRIPT = r'''
import sys
from pathlib import Path
BACKEND = Path(r"{backend}").resolve()
sys.path.insert(0, str(BACKEND))
import main_v2                      # v2 워커(model_v2/ 트리)
import baseline
print("BASELINE=" + str(Path(baseline.__file__).resolve()))
'''


class WorkerBaselineIsolationTest(unittest.TestCase):
    def test_team_worker_resolves_team_baseline_and_endpoint_ok(self):
        out = _run(_TEAM_SCRIPT.format(backend=str(_BACKEND)))
        m = _markers(out)
        base = m.get("BASELINE", "")
        # resolve된 절대경로로 판정 — 팀 baseline은 /model/baseline/ 아래(‥/model_v2/‥ 아님)
        self.assertIn("/model/baseline/", base, base)
        self.assertNotIn("/model_v2/baseline/", base, base)
        self.assertTrue(Path(base).is_absolute())
        # 팀 endpoint mock 회귀 — run_pipeline 정확히 1회, 200
        self.assertEqual(m.get("STATUS"), "200", out)
        self.assertEqual(m.get("PIPELINE_CALLS"), "1", out)

    def test_v2_worker_resolves_vendored_baseline(self):
        out = _run(_V2_SCRIPT.format(backend=str(_BACKEND)))
        base = _markers(out).get("BASELINE", "")
        self.assertIn("/model_v2/baseline/", base, base)
        self.assertTrue(Path(base).is_absolute())


class TeamFilesUnchangedTest(unittest.TestCase):
    """팀 파일이 upstream/main과 바이트 동일한지 재확인(병렬 추가가 팀 코드를 건드리지 않음)."""

    _TEAM_FILES = [
        "backend/main.py",
        "backend/app/api/v1/generate.py",
        "backend/app/services/pipeline_service.py",
        "backend/app/services/scorer.py",
        "frontend/app.py",
        "docker-compose.yml",
        "backend/Dockerfile",
    ]

    def test_team_files_byte_identical_with_upstream_main(self):
        for rel in self._TEAM_FILES:
            with self.subTest(file=rel):
                r = subprocess.run(
                    ["git", "diff", "--exit-code", "upstream/main", "--", rel],
                    cwd=str(_REPO), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0,
                                 f"{rel} 이 upstream/main과 다름:\n{r.stdout[:1000]}")


if __name__ == "__main__":
    unittest.main()
