"""Card 1127: ci/test_select.py and the real ci/test-select.toml.

The suites run once per change: a pull request runs every suite unless its
diff selects nothing (docs, a version-only pyproject.toml bump), and the
merge queue never runs them: it passes only if the queue base is an ancestor
of the PR head (nothing merged ahead), and fails otherwise.

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


def _path_forms(path: str) -> list[str]:
    """How a test can name a tracked file: the quoted path, or a quoted
    `"dir" / "name"` join of its last two or more segments (ROOT / ..., spec_from_file_location)."""
    parts = path.split("/")
    forms = [f'"{path}"', f"'{path}'"]
    forms += [" / ".join(f'"{seg}"' for seg in parts[i:]) for i in range(len(parts) - 1)]
    if len(parts) == 1:
        forms.append(f'/ "{path}"')
    return forms


def _referenced(text: str, candidates: list[str]) -> list[str]:
    return [p for p in candidates if any(form in text for form in _path_forms(p))]


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
    (["Makefile"], {"pytest_no_sql_run"}),
    (["tests/programs/hint_check.py"], BOTH),
    (["README.md", "docs/JOIN.md", "CHANGELOG.md", "LICENSE", ".gitattributes", ".gitignore"], set()),
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
    loadable = [p for p in _tracked("tests", "tools") if p.endswith((".py", ".sh"))]
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
        todo += [p for p in _referenced(text, loadable) if p.endswith(".py")]
        seen.update(_referenced(text, loadable))
    missing = sorted(p for p in seen if "pytest_sql_run" not in ts.select_jobs([p], rules))
    assert not missing, missing


# Docs are read by many tests but stay unmapped by design (the detect_docs_only
# outcome): their checks are check_pack, mill_cli_smoke and precheck, which run on every change.
DOCS_EXEMPT = ("docs/",)


def test_every_tracked_file_a_test_names_is_mapped(rules: ts.Rules) -> None:
    """A tracked file a test names by path selects at least one test job (Makefile, MANIFEST.in, ...)."""
    tests = [p for p in _tracked("tests") if p.endswith(".py") and p != "tests/ci/test_test_select.py"]
    text = "\n".join((ROOT / p).read_text(encoding="utf-8", errors="replace") for p in tests)
    candidates = [p for p in _tracked() if not p.startswith(DOCS_EXEMPT) and not p.endswith(".md") and p != "LICENSE"]
    named = _referenced(text, candidates)
    assert "Makefile" in named and "MANIFEST.in" in named, named
    missing = sorted(p for p in named if not ts.select_jobs([p], rules))
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


def test_pull_request_runs_every_suite_unless_nothing_is_selected(repo: Path, rules: ts.Rules) -> None:
    """The PR run is the one Validator measures: any mapped change runs both
    suites on the whole branch, not the subset the map names."""
    base = _commit(repo, {"README.md": "a\n"})
    docs = _commit(repo, {"README.md": "b\n", "docs/JOIN.md": "c\n"})
    assert ts.github_selection(rules, "pull_request", _pr(base, docs))[0] == set()
    tool = _commit(repo, {"tools/check_pr_text.py": "x = 1\n"})
    assert ts.select_jobs(["tools/check_pr_text.py"], rules) == {"pytest_no_sql_run"}
    assert ts.github_selection(rules, "pull_request", _pr(docs, tool))[0] == BOTH
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


def _queue(repo: Path, number: int, pr_head: str, queued: str, base: str) -> dict:
    """A merge_group event whose PR head is published as refs/pull/N/head on
    an origin that is the repo itself, as GitHub serves it."""
    if not _git(repo, "remote"):
        _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "update-ref", f"refs/pull/{number}/head", pr_head)
    ref = f"refs/heads/gh-readonly-queue/main/pr-{number}-{base}"
    return {"merge_group": {"base_sha": base, "head_sha": queued, "head_ref": ref}}


def _queued_squash(repo: Path, base: str, pr_head: str) -> str:
    """The commit the queue builds: the PR head's tree on top of base."""
    tree = _git(repo, "rev-parse", f"{pr_head}^{{tree}}")
    return _git(repo, "-c", "user.name=q", "-c", "user.email=q@example.com", "commit-tree", tree, "-p", base, "-m", "squash")


def test_merge_group_on_an_ancestor_base_passes_with_no_suite(repo: Path, rules: ts.Rules) -> None:
    """The queue base is an ancestor of the PR head: nothing merged ahead, so
    the queued code is what the PR run tested."""
    base = _commit(repo, {"README.md": "a\n"})
    pr_head = _commit(repo, {"agent_coord/server/sql/t.sql": "select 1;\n"})
    queued = _queued_squash(repo, base, pr_head)
    chosen, reason = ts.github_selection(rules, "merge_group", _queue(repo, 7, pr_head, queued, base))
    assert chosen == set()
    assert "#7" in reason


def test_merge_group_on_a_moved_main_fails(repo: Path, rules: ts.Rules) -> None:
    """Main moved after the PR was tested: the queue fails, it never runs the suites."""
    _commit(repo, {"README.md": "a\n"})
    _git(repo, "switch", "-q", "-c", "pr")
    pr_head = _commit(repo, {"docs/x.md": "b\n"})
    _git(repo, "switch", "-q", "main")
    base = _commit(repo, {"agent_coord/x.py": "y = 2\n"})
    queued = _commit(repo, {"docs/x.md": "b\n"})
    with pytest.raises(ts.QueueCheckFailed, match=re.escape(ts.MOVED)):
        ts.github_selection(rules, "merge_group", _queue(repo, 8, pr_head, queued, base))


@pytest.mark.parametrize("merge_group", [
    {},
    {"base_sha": "a" * 40, "head_sha": "b" * 40},
    {"base_sha": "a" * 40, "head_sha": "b" * 40, "head_ref": "refs/heads/main"},
    {"base_sha": "a" * 40, "head_sha": "b" * 40, "head_ref": "refs/heads/gh-readonly-queue/main/pr-x-" + "a" * 40},
    {"base_sha": "main", "head_sha": "b" * 40, "head_ref": "refs/heads/gh-readonly-queue/main/pr-1-" + "a" * 40},
])
def test_merge_group_it_cannot_read_fails(rules: ts.Rules, merge_group: dict) -> None:
    with pytest.raises(ts.QueueCheckFailed):
        ts.github_selection(rules, "merge_group", {"merge_group": merge_group})


def test_merge_group_without_the_pr_head_fails(repo: Path, rules: ts.Rules) -> None:
    """No refs/pull/N/head to fetch (or no origin): fail safe."""
    base = _commit(repo, {"README.md": "a\n"})
    head = _commit(repo, {"README.md": "b\n"})
    event = {"merge_group": {"base_sha": base, "head_sha": head,
                             "head_ref": f"refs/heads/gh-readonly-queue/main/pr-9-{base}"}}
    with pytest.raises(ts.QueueCheckFailed):
        ts.github_selection(rules, "merge_group", event)
    _git(repo, "remote", "add", "origin", str(repo))
    with pytest.raises(ts.QueueCheckFailed):
        ts.github_selection(rules, "merge_group", event)


def test_cli_merge_group_check_failure_exits_nonzero(tmp_path: Path) -> None:
    """A failed select job turns the required pytest_sql and pytest_no_sql gates red."""
    proc, out = _run(tmp_path, "--github", name="merge_group", event={"merge_group": {"base_sha": "a" * 40, "head_sha": "b" * 40}})
    assert proc.returncode == 1
    assert "rebase" in proc.stderr
    assert out == ""


PYPROJECT = '[project]\nname = "the-mill"\nversion = "0.8.13"\ndependencies = ["a>=1"]\n'


def test_version_only_bump_pull_request_runs_no_suite(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"pyproject.toml": PYPROJECT, "CHANGELOG.md": "a\n"})
    head = _commit(repo, {"pyproject.toml": PYPROJECT.replace("0.8.13", "0.8.14"), "CHANGELOG.md": "b\n"})
    assert ts.github_selection(rules, "pull_request", _pr(base, head))[0] == set()


def test_pyproject_change_beyond_the_version_runs_every_suite(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"pyproject.toml": PYPROJECT})
    head = _commit(repo, {"pyproject.toml": PYPROJECT.replace("0.8.13", "0.8.14").replace("a>=1", "a>=2")})
    assert ts.github_selection(rules, "pull_request", _pr(base, head))[0] == BOTH
    pin = _commit(repo, {"pyproject.toml": PYPROJECT.replace("0.8.13", "0.8.14").replace("a>=1", "a>=3")})
    assert ts.github_selection(rules, "pull_request", _pr(head, pin))[0] == BOTH


def test_version_bump_with_a_mapped_file_runs_every_suite(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"pyproject.toml": PYPROJECT})
    head = _commit(repo, {"pyproject.toml": PYPROJECT.replace("0.8.13", "0.8.14"), "tools/check_pr_text.py": "x = 1\n"})
    assert ts.github_selection(rules, "pull_request", _pr(base, head))[0] == BOTH


def test_new_pyproject_is_not_a_version_only_change(repo: Path, rules: ts.Rules) -> None:
    base = _commit(repo, {"README.md": "a\n"})
    head = _commit(repo, {"pyproject.toml": 'version = "0.8.14"\n'})
    assert ts.github_selection(rules, "pull_request", _pr(base, head))[0] == BOTH


def test_local_mode_skips_a_version_only_bump(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _commit(repo, {"pyproject.toml": PYPROJECT})
    _commit(repo, {"pyproject.toml": PYPROJECT.replace("0.8.13", "0.8.14")})
    assert ts.main(["--base", base]) == 0
    assert capsys.readouterr().out.splitlines() == ["pytest_no_sql_run=false", "pytest_sql_run=false"]


@pytest.mark.parametrize("name,event", [
    ("push", {}),
    ("workflow_dispatch", {}),
    ("", {}),
    ("pull_request", {}),
    ("pull_request", _pr("0" * 40, "a" * 40)),
    ("pull_request", _pr("main", "HEAD")),
])
def test_other_events_and_bad_shas_run_every_job(rules: ts.Rules, name: str, event: dict) -> None:
    assert ts.github_selection(rules, name, event)[0] == BOTH


def test_failed_or_empty_diff_runs_every_job(repo: Path, rules: ts.Rules) -> None:
    head = _commit(repo, {"README.md": "a\n"})
    assert ts.github_selection(rules, "pull_request", _pr(head, head)) == (BOTH, "empty diff: every job")
    chosen, reason = ts.github_selection(rules, "pull_request", _pr("1" * 40, head))
    assert chosen == BOTH and reason.startswith("diff failed")
