"""#663 (F113): a regression test the matrix cites is not skipped or dropped by collection.

A conftest hook sees every collected item in the session, not only the
items under its own directory. tests/validator/conftest.py marked every
item whose path contained "validator" as skipped unless MILL_LIVE=1, so the
F110 and F111 tests in tests/install were skipped in CI's no-SQL run and
the job stayed green. These tests run in pytest_no_sql and fail it when a
cited regression test is skipped at collection there again, when a cited
file collects no test at all (a module-level skip, importorskip or
collect_ignore), or when a cited node id names no collected test.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"
F110_F111 = (
    "tests/install/test_validator_pass_810.py",
    "tests/install/test_validator_status_identity_811.py",
)
LIVE_DIR = "tests/validator"

# Loaded into the child pytest with -p: records each selected item and the
# skip its marks evaluate to (skip or a true skipif), the items -m "not sql"
# deselected, and every collector that was skipped (a module-level skip or
# importorskip).
PROBE = '''
import json, os
from _pytest.skipping import evaluate_skip_marks

_deselected = []
_collect_skips = []

def pytest_deselected(items):
    _deselected.extend(item.nodeid for item in items)

def pytest_collectreport(report):
    if report.skipped:
        rep = report.longrepr
        _collect_skips.append([report.nodeid, str(rep[-1] if isinstance(rep, tuple) else rep)])

def pytest_collection_finish(session):
    items = []
    for item in session.items:
        skip = evaluate_skip_marks(item)
        items.append([item.nodeid, skip.reason if skip else None])
    with open(os.environ["MILL_ROW_PROBE_OUT"], "w", encoding="utf-8") as fh:
        json.dump({"items": items, "deselected": _deselected,
                   "collect_skips": _collect_skips}, fh)
'''

_FILE = re.compile(r"^(tests/[\w/.-]+\.py)(?:::(.+))?$")
_BARE = re.compile(r"^test_\w+\*?$")


def _env(tmp: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("MILL_LIVE", None)  # the CI no-SQL run is not live
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp), *filter(None, [env.get("PYTHONPATH")])])
    return env


def _pytest(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-m", "not sql", *args],
        cwd=ROOT, env=_env(tmp), capture_output=True, text=True, timeout=600,
    )


def _citations(text: str) -> tuple[set[str], list[tuple[str, str, str]]]:
    """Files and node ids in the regression-test column of each matrix row.

    `tests/x.py` names a file; `tests/x.py::name`, a following `::name` and
    a following bare `test_name` (a trailing * is a glob) name tests in the
    last file named in that cell. Returns (files, [(row, file, name)]).
    """
    files: set[str] = set()
    ids: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| ID "):
            continue
        cells = line.strip().strip("|").split(" | ")
        row = cells[0].split()[0]
        files.update(re.findall(r"(tests/[\w/.-]+\.py)", cells[-1]))
        current = None
        for span in re.findall(r"`([^`]+)`", cells[-1]):
            m = _FILE.match(span)
            if m:
                current = m.group(1)
                if m.group(2):
                    ids.append((row, current, m.group(2)))
            elif current and span.startswith("::"):
                ids.append((row, current, span[2:]))
            elif current and _BARE.match(span):
                ids.append((row, current, span))
    return files, ids


def _cited_files() -> set[str]:
    return _citations(MATRIX.read_text(encoding="utf-8"))[0]


def _resolves(file: str, name: str, nodeids: list[str]) -> bool:
    for nodeid in nodeids:
        path, _, rest = nodeid.partition("::")
        if path != file or not rest:
            continue
        if rest == name:  # a parametrized id names one case: exact match
            return True
        base = re.sub(r"\[.*\]$", "", rest)
        if fnmatchcase(base, name) or base.startswith(name + "::"):
            return True
    return False


def _row_problems(root: Path, matrix: Path, tmp: Path) -> tuple[list[str], dict]:
    """Collect root's tests as pytest_no_sql does and list every way a cited
    regression test would not run there."""
    (tmp / "_mill_row_probe.py").write_text(PROBE, encoding="utf-8")
    out = tmp / "items.json"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "_mill_row_probe",
         "-m", "not sql", "--collect-only", "-q", "tests"],
        cwd=root, env={**_env(tmp), "MILL_ROW_PROBE_OUT": str(out)},
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode in (0, 5), proc.stdout[-4000:] + proc.stderr[-2000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    files, ids = _citations(matrix.read_text(encoding="utf-8"))
    problems = [f"{f}: file does not exist" for f in sorted(files) if not (root / f).is_file()]
    for nodeid, reason in data["items"]:
        if nodeid.split("::", 1)[0] in files and reason is not None:
            problems.append(f"{nodeid}: skipped at collection: {reason}")
    # A file deselected as sql still counts: it runs in pytest_sql. A file
    # with neither a selected nor a deselected item runs nowhere.
    nodeids = [n for n, _r in data["items"]] + data["deselected"]
    collected = {n.split("::", 1)[0] for n in nodeids}
    skips = {n: r for n, r in data["collect_skips"]}
    for f in sorted(files):
        # A cited helper module (fixtures built for a test) holds no test.
        if Path(f).name.startswith("test_") and (root / f).is_file() and f not in collected:
            why = skips.get(f, "not collected (collect_ignore or no test in it)")
            problems.append(f"{f}: collects no test: {why}")
    for row, f, name in ids:
        if f in collected and not _resolves(f, name, nodeids):
            problems.append(f"{row}: {f}::{name} names no collected test")
    return problems, data


def test_the_matrix_cites_test_files():
    files, ids = _citations(MATRIX.read_text(encoding="utf-8"))
    assert set(F110_F111) <= files
    assert len(files) > 50, sorted(files)
    assert len(ids) > 50, ids


def test_every_cited_regression_test_file_exists():
    missing = sorted(f for f in _cited_files() if not (ROOT / f).is_file())
    assert not missing, f"REGRESSION-MATRIX.md cites test files that do not exist: {missing}"


def _fixture_tree(root: Path) -> Path:
    """A tiny repo whose matrix cites files that collect nothing and a node
    id that names no test, beside ones that are fine."""
    tests = root / "tests"
    tests.mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\nmarkers =\n    sql: needs MySQL\n", encoding="utf-8")
    (tests / "conftest.py").write_text('collect_ignore = ["test_ignored.py"]\n', encoding="utf-8")
    (tests / "test_ok.py").write_text(
        "def test_ok():\n    pass\n\ndef test_other():\n    pass\n", encoding="utf-8")
    (tests / "test_all_sql.py").write_text(
        "import pytest\npytestmark = pytest.mark.sql\n\ndef test_in_mysql():\n    pass\n",
        encoding="utf-8")
    (tests / "test_module_skip.py").write_text(
        "import pytest\npytest.skip('gone', allow_module_level=True)\n\ndef test_a():\n    pass\n",
        encoding="utf-8")
    (tests / "test_importorskip.py").write_text(
        "import pytest\npytest.importorskip('no_such_module_663')\n\ndef test_a():\n    pass\n",
        encoding="utf-8")
    (tests / "test_ignored.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (tests / "test_params.py").write_text(
        "import pytest\n\ndef _p(v):\n    pass\n\ntest_p = pytest.mark.parametrize('v', ['a b', 'c'])(_p)\n",
        encoding="utf-8")
    (tests / "fixtures_helper.py").write_text("DATA = 1\n", encoding="utf-8")
    matrix = root / "MATRIX.md"
    matrix.write_text(
        "| ID | Claim | Code | Tests |\n"
        "| F1 (ok) | c | k | `tests/test_ok.py::test_ok`, `::test_other`, `tests/test_all_sql.py` |\n"
        "| F2 (glob) | c | k | `tests/test_ok.py` (`test_o*`) |\n"
        "| F3 (module-skip) | c | k | `tests/test_module_skip.py` (all cases) |\n"
        "| F4 (importorskip) | c | k | `tests/test_importorskip.py` (all cases) |\n"
        "| F5 (ignored) | c | k | `tests/test_ignored.py` (all cases) |\n"
        "| F6 (stale-id) | c | k | `tests/test_ok.py::test_renamed_away` |\n"
        "| F7 (params) | c | k | `tests/test_params.py::test_p[a b]`, `tests/fixtures_helper.py` |\n"
        "| F8 (stale-param) | c | k | `tests/test_params.py::test_p[gone]` |\n",
        encoding="utf-8")
    return matrix


def test_checker_flags_cited_files_that_collect_nothing(tmp_path: Path):
    """W1: a module-level skip, importorskip or collect_ignore on a cited
    file leaves it with no item to skip; the file itself must be flagged."""
    root = tmp_path / "repo"
    matrix = _fixture_tree(root)
    probe = tmp_path / "probe"
    probe.mkdir()
    problems, _data = _row_problems(root, matrix, probe)
    text = "\n".join(problems)
    for name in ("test_module_skip.py", "test_importorskip.py", "test_ignored.py"):
        assert f"tests/{name}" in text, problems
    assert "tests/test_all_sql.py" not in text, problems  # deselected, runs in pytest_sql


def test_checker_flags_cited_node_ids_that_name_no_test(tmp_path: Path):
    """W3: a cited file::test must name a collected test, not only a file."""
    root = tmp_path / "repo"
    matrix = _fixture_tree(root)
    probe = tmp_path / "probe"
    probe.mkdir()
    problems, _data = _row_problems(root, matrix, probe)
    stale = [p for p in problems if "test_ok.py" in p or "test_params.py" in p]
    assert stale == [
        "F6: tests/test_ok.py::test_renamed_away names no collected test",
        "F8: tests/test_params.py::test_p[gone] names no collected test",
    ], problems
    assert not [p for p in problems if "fixtures_helper" in p], problems


def test_no_cited_regression_test_is_skipped_at_collection(tmp_path: Path):
    """Collect the whole tree as pytest_no_sql does (MILL_LIVE unset, every
    conftest loaded) and fail on any cited test that would not run there."""
    problems, data = _row_problems(ROOT, MATRIX, tmp_path)
    assert not problems, "cited regression tests that do not run in the no-SQL run:\n" + "\n".join(problems)
    by_file: dict[str, int] = {}
    for nodeid, _reason in data["items"]:
        path = nodeid.split("::", 1)[0]
        by_file[path] = by_file.get(path, 0) + 1
    for path in F110_F111:
        assert by_file.get(path, 0) > 0, f"{path} collected nothing"
    # the live probes stay gated: collection still skips tests/validator
    live = [(n, r) for n, r in data["items"] if n.startswith(LIVE_DIR + "/")]
    assert live and all(r for _n, r in live), live


def test_f110_f111_tests_pass_beside_the_live_package(tmp_path: Path):
    """Run the F110/F111 files with tests/validator in the same session, as
    `pytest tests` does: every F110/F111 case passes, none is skipped, and
    every tests/validator case is still skipped without MILL_LIVE=1."""
    junit = tmp_path / "junit.xml"
    proc = _pytest(tmp_path, "-rs", f"--junitxml={junit}", *F110_F111, LIVE_DIR)
    assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr[-2000:]
    rows: dict[str, list[str]] = {"f110_f111": [], "live": []}
    for case in ET.parse(junit).iter("testcase"):
        cls = case.get("classname", "")
        outcome = "passed"
        for tag in ("skipped", "failure", "error"):
            if case.find(tag) is not None:
                outcome = tag
        if cls.startswith("tests.validator."):
            rows["live"].append(outcome)
        elif any(cls == f[:-3].replace("/", ".") for f in F110_F111):
            rows["f110_f111"].append(outcome)
    assert rows["f110_f111"], proc.stdout[-2000:]
    assert set(rows["f110_f111"]) == {"passed"}, (rows, proc.stdout[-3000:])
    assert rows["live"] and set(rows["live"]) == {"skipped"}, rows
