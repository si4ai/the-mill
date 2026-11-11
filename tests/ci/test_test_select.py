"""Card 1127: ci/test_select.py and the real ci/test-select.toml.

Every map assertion loads the map CI reads, not a copy of it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ci import test_select as ts  # noqa: E402

SCRIPT = ROOT / "ci" / "test_select.py"
SQL_MARK_RE = re.compile(r"pytest\.mark\.sql\b|pytestmark\s*=.*\bsql\b")
IMPORT_RE = re.compile(r"^\s*(?:from\s+((?:tests|tools)(?:\.\w+)*)\s+import\s+([\w, ]+)|import\s+((?:tests|tools)(?:\.\w+)+))", re.M)
TOOL_PATH_RE = re.compile(r"""["'/](tools/[\w.-]+\.(?:py|sh))\b|"tools"\s*/\s*"([\w.-]+\.(?:py|sh))\"""")
BOTH = {"pytest_no_sql_run", "pytest_sql_run"}


@pytest.fixture(scope="module")
def rules() -> ts.Rules:
    return ts.load_map()


def _tracked(*prefixes: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", *prefixes], cwd=ROOT, check=True, capture_output=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def test_star_star_matches_zero_or_more_directories() -> None:
    assert ts.match_glob("a.py", "**/*.py")
    assert ts.match_glob("agent_coord/server/sql/tables.sql", "**/*.sql")
    assert ts.match_glob("tests/x.py", "tests/**")
    assert not ts.match_glob("tests", "tests/*.py")
    assert not ts.match_glob("a.txt", "**/*.py")


def test_single_star_stays_in_one_directory() -> None:
    assert ts.match_glob("tests/conftest.py", "tests/*.py")
    assert not ts.match_glob("tests/server/conftest.py", "tests/*.py")
    assert ts.match_glob("tools/ci-lock/ci.txt", "tools/ci-lock/*.txt")
    assert not ts.match_glob("x/tools/ci-lock/ci.txt", "tools/ci-lock/*.txt")


def test_real_map_names_only_jobs_ci_yml_gates_on_select() -> None:
    """The selectable jobs are exactly the ci.yml jobs whose if reads the select output."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gated = set(re.findall(r"^\s+if: needs\.select\.outputs\.(\w+) == 'true'$", ci, re.M))
    assert gated == set(ts.KNOWN_JOBS)
    used = {job for _, jobs in ts.load_map() for job in jobs}
    assert used == set(ts.KNOWN_JOBS)


def test_one_file_matching_two_rules_gets_the_union(rules: ts.Rules) -> None:
    """ci.yml matches the .github/** rule (no SQL) and its own rule (both)."""
    matched = [jobs for globs, jobs in rules if any(ts.match_glob(".github/workflows/ci.yml", g) for g in globs)]
    assert len(matched) >= 2 and set(matched[0]) != set(matched[-1])
    assert ts.select_jobs([".github/workflows/ci.yml"], rules) == BOTH
    assert ts.select_jobs([".github/workflows/codeql.yml"], rules) == {"pytest_no_sql_run"}


def test_two_rules_with_disjoint_jobs_union(tmp_path: Path) -> None:
    path = tmp_path / "map.toml"
    path.write_text(
        '[[rule]]\npaths = ["a/**"]\njobs = ["pytest_no_sql_run"]\n'
        '[[rule]]\npaths = ["**/*.sql"]\njobs = ["pytest_sql_run"]\n', encoding="utf-8")
    rules = ts.load_map(path)
    assert ts.select_jobs(["a/b.sql"], rules) == BOTH
    assert ts.select_jobs(["a/b.py", "c/d.sql"], rules) == BOTH
    assert ts.select_jobs(["c/d.md"], rules) == set()


@pytest.mark.parametrize("paths,want", [
    (["agent_coord/server/sql/tables.sql"], BOTH),
    (["docs/requirements/beta/beta_ddl.sql"], BOTH),
    (["agent_coord/client/cli.py"], BOTH),
    (["pyproject.toml"], BOTH),
    (["tools/ci-lock/ci.txt"], BOTH),
    (["tools/check_pr_text.py"], {"pytest_no_sql_run"}),
    (["tests/client/test_x.py"], {"pytest_no_sql_run"}),
    (["scripts/bootstrap.sh"], {"pytest_no_sql_run"}),
    (["ci/test-select.toml"], {"pytest_no_sql_run"}),
    (["ci/test_select.py"], {"pytest_no_sql_run"}),
    (["README.md", "docs/JOIN.md", "CHANGELOG.md", "LICENSE", ".gitignore", "Makefile"], set()),
])
def test_real_map_selects(rules: ts.Rules, paths: list[str], want: set[str]) -> None:
    assert ts.select_jobs(paths, rules) == want


def test_docs_only_change_selects_no_test_job(rules: ts.Rules) -> None:
    """Same outcome detect_docs_only gave: docs and LICENSE run no pytest."""
    docs = [p for p in _tracked("docs", "*.md", "LICENSE")
            if p == "LICENSE" or (p.endswith(".md") and (p.startswith("docs/") or "/" not in p))]
    assert docs
    assert ts.select_jobs(docs, rules) == set()


def test_every_package_tests_and_tools_python_file_runs_no_sql(rules: ts.Rules) -> None:
    files = [p for p in _tracked("agent_coord", "tests", "tools", "build_backend", "ci") if p.endswith(".py")]
    missing = [p for p in files if "pytest_no_sql_run" not in ts.select_jobs([p], rules)]
    assert not missing, missing


def _module_files(module: str, names: str) -> list[str]:
    """Repo files an import line can load: the module and, for from-imports, submodules."""
    base = module.replace(".", "/")
    out = [f"{base}.py", f"{base}/__init__.py"]
    out += [f"{base}/{n.strip()}.py" for n in names.split(",") if n.strip()]
    return [p for p in out if (ROOT / p).is_file()]


def test_sql_suites_and_what_they_load_run_sql(rules: ts.Rules) -> None:
    """A SQL-marked test file, its conftest chain and the tests/tools modules it imports select pytest_sql_run."""
    todo = [p for p in _tracked("tests") if p.endswith(".py")
            and SQL_MARK_RE.search((ROOT / p).read_text(encoding="utf-8", errors="replace"))]
    assert len(todo) > 100, len(todo)
    seen: set[str] = set()
    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        parts = Path(path).parts
        for i in range(1, len(parts)):
            conftest = "/".join(parts[:i] + ("conftest.py",))
            if (ROOT / conftest).is_file():
                todo.append(conftest)
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        for m in IMPORT_RE.finditer(text):
            todo += _module_files(m.group(1) or m.group(3), m.group(2) or "")
        for m in TOOL_PATH_RE.finditer(text):
            tool = m.group(1) or f"tools/{m.group(2)}"
            if (ROOT / tool).is_file():
                seen.add(tool)
    missing = sorted(p for p in seen if "pytest_sql_run" not in ts.select_jobs([p], rules))
    assert not missing, missing


@pytest.mark.parametrize("text,err", [
    ('[[rule]]\npaths = ["a"]\njobs = ["lint"]\n', "unknown job name: lint"),
    ('[[rule]]\npaths = []\njobs = ["pytest_sql_run"]\n', "paths must be a non-empty list"),
    ('[[rule]]\npaths = ["a"]\n', "exactly paths and jobs"),
    ('rule = 1\n', "at least one"),
    ('[[rul]]\npaths = ["a"]\njobs = ["pytest_sql_run"]\n', "unknown top-level keys"),
    ('[[rule]\n', "not valid toml"),
])
def test_bad_map_is_an_error(tmp_path: Path, text: str, err: str) -> None:
    path = tmp_path / "map.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ts.MapError, match=re.escape(err)):
        ts.load_map(path)


def _run(tmp_path: Path, *args: str, event: dict | None = None, name: str = "push",
         output: bool = True) -> tuple[subprocess.CompletedProcess, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    out = tmp_path / "out.txt"
    if output:
        env["GITHUB_OUTPUT"] = str(out)
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event or {}), encoding="utf-8")
    env.update(GITHUB_EVENT_NAME=name, GITHUB_EVENT_PATH=str(ev))
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True)
    return proc, out.read_text(encoding="utf-8") if out.exists() else ""


def test_cli_push_runs_every_job_and_writes_output(tmp_path: Path) -> None:
    proc, out = _run(tmp_path, "--github")
    assert proc.returncode == 0, proc.stderr
    assert out.splitlines() == ["pytest_no_sql_run=true", "pytest_sql_run=true"]


def test_cli_unknown_job_exits_nonzero_and_writes_nothing(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[[rule]]\npaths = ["a"]\njobs = ["lint"]\n', encoding="utf-8")
    proc, out = _run(tmp_path, "--github", "--map", str(bad))
    assert proc.returncode == 1
    assert "unknown job name: lint" in proc.stderr
    assert out == ""


def test_cli_without_github_output_exits_nonzero(tmp_path: Path) -> None:
    proc, _ = _run(tmp_path, "--github", output=False)
    assert proc.returncode == 1
    assert "GITHUB_OUTPUT is not set" in proc.stderr


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=builder", "-c", "user.email=builder@example.com", "commit", "-qm", "c")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    monkeypatch.setattr(ts, "ROOT", path)
    return path


def _pr(base: str, head: str) -> dict:
    return {"pull_request": {"base": {"sha": base}, "head": {"sha": head}}}


def test_pull_request_selects_from_the_diff(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"README.md": "a\n"})
    docs = _commit(repo, {"README.md": "b\n", "docs/JOIN.md": "c\n"})
    assert ts.github_selection(rules, "pull_request", _pr(base, docs))[0] == set()
    tool = _commit(repo, {"tools/check_pr_text.py": "x = 1\n"})
    assert ts.github_selection(rules, "pull_request", _pr(docs, tool))[0] == {"pytest_no_sql_run"}
    sql = _commit(repo, {"agent_coord/server/sql/t.sql": "select 1;\n"})
    assert ts.github_selection(rules, "pull_request", _pr(base, sql))[0] == BOTH


def test_pull_request_diffs_from_the_merge_base(repo: Path, rules: ts.Rules) -> None:
    """Three dots: a later main commit does not count as the PR's change."""
    fork = _commit(repo, {"README.md": "a\n"})
    _git(repo, "switch", "-q", "-c", "pr")
    head = _commit(repo, {"docs/x.md": "b\n"})
    _git(repo, "switch", "-q", "main")
    main = _commit(repo, {"agent_coord/x.py": "y = 2\n"})
    assert fork != main
    assert ts.github_selection(rules, "pull_request", _pr(main, head))[0] == set()


def test_merge_group_selects_from_base_to_queued_head(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"README.md": "a\n"})
    head = _commit(repo, {"scripts/bootstrap.sh": "echo\n"})
    event = {"merge_group": {"base_sha": base, "head_sha": head}}
    chosen, reason = ts.github_selection(rules, "merge_group", event)
    assert chosen == {"pytest_no_sql_run"}
    assert ".." in reason and "..." not in reason


@pytest.mark.parametrize("name,event", [
    ("push", {}),
    ("workflow_dispatch", {}),
    ("", {}),
    ("pull_request", {}),
    ("pull_request", _pr("0" * 40, "a" * 40)),
    ("pull_request", _pr("main", "HEAD")),
    ("merge_group", {"merge_group": {"base_sha": "x"}}),
])
def test_other_events_and_bad_shas_run_every_job(rules: ts.Rules, name: str, event: dict) -> None:
    assert ts.github_selection(rules, name, event)[0] == BOTH


def test_failed_or_empty_diff_runs_every_job(repo: Path, rules: ts.Rules) -> None:
    head = _commit(repo, {"README.md": "a\n"})
    assert ts.github_selection(rules, "pull_request", _pr(head, head)) == (BOTH, "empty diff: every job")
    chosen, reason = ts.github_selection(rules, "pull_request", _pr("1" * 40, head))
    assert chosen == BOTH and reason.startswith("diff failed")
