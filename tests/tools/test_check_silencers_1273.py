"""Card 1273: a new silencer without a written reason does not pass."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools import check_silencers as cs

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.com",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.update(_GIT_ENV)
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, env=env, text=True
    )
    return proc.stdout


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--allow-empty", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(
        repo,
        "mod.py",
        "import sys  # noqa: E402\n"
        "x = 1  # type: ignore[attr-defined]\n"
        "y = 2  # pragma: no cover\n",
    )
    _write(
        repo,
        ".github/codeql/codeql-config.yml",
        "name: demo\nquery-filters: []\n",
    )
    _write(
        repo,
        ".github/dependabot.yml",
        "version: 2\nupdates: []\n",
    )
    base = _commit(repo, "base")
    return repo, base


def test_new_noqa_without_reason_fails(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(repo, "mod.py", "import sys  # noqa: E402\nimport os  # noqa: F401\n")
    head = _commit(repo, "add noqa")
    findings = cs.scan(base, head, cwd=repo)
    assert len(findings) == 1
    assert findings[0].kind == "noqa"
    assert findings[0].path == "mod.py"
    assert cs.main(["--base", base, "--head", head, "--cwd", str(repo)]) == 1


def test_new_noqa_with_reason_passes(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "mod.py",
        "import sys  # noqa: E402\n"
        "import os  # noqa: F401  # re-export for the public hook\n"
        "z = 3  # noqa: S310 (fixed https API base)\n",
    )
    head = _commit(repo, "reasoned noqa")
    assert cs.scan(base, head, cwd=repo) == []
    assert cs.main(["--base", base, "--head", head, "--cwd", str(repo)]) == 0


def test_existing_silencer_without_reason_is_baselined(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "mod.py",
        "import sys  # noqa: E402\n"
        "x = 1  # type: ignore[attr-defined]\n"
        "y = 2  # pragma: no cover\n"
        "print('ok')\n",
    )
    head = _commit(repo, "no new silencer")
    assert cs.scan(base, head, cwd=repo) == []


def test_moved_silencer_is_not_new(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "mod.py",
        "x = 1  # type: ignore[attr-defined]\n"
        "import sys  # noqa: E402\n"
        "y = 2  # pragma: no cover\n",
    )
    head = _commit(repo, "reorder")
    assert cs.scan(base, head, cwd=repo) == []


def test_type_ignore_and_no_cover_and_nosec_need_reason(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "mod.py",
        "import sys  # noqa: E402\n"
        "x = 1  # type: ignore[attr-defined]\n"
        "y = 2  # pragma: no cover\n"
        "a = 3  # type: ignore[union-attr]\n"
        "b = 4  # pragma: no cover\n"
        "c = 5  # nosec B105\n",
    )
    head = _commit(repo, "three new")
    kinds = sorted(f.kind for f in cs.scan(base, head, cwd=repo))
    assert kinds == ["no-cover", "nosec", "type-ignore"]


def test_type_ignore_with_reason_passes(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        "mod.py",
        "import sys  # noqa: E402\n"
        "x = 1  # type: ignore[attr-defined]\n"
        "y = 2  # pragma: no cover\n"
        "a = 3  # type: ignore[union-attr]  # added on the instance at runtime\n"
        "b = 4  # pragma: no cover  # no MySQL in this suite\n"
        "c = 5  # nosec B105  # fixture password, never a real secret\n",
    )
    head = _commit(repo, "reasoned others")
    assert cs.scan(base, head, cwd=repo) == []


def test_codeql_exclude_needs_reason(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        ".github/codeql/codeql-config.yml",
        "name: demo\n"
        "query-filters:\n"
        "  - exclude:\n"
        "      id: py/polynomial-redos\n",
    )
    head = _commit(repo, "bare exclude")
    kinds = {f.kind for f in cs.scan(base, head, cwd=repo)}
    assert "codeql-exclude" in kinds
    _write(
        repo,
        ".github/codeql/codeql-config.yml",
        "name: demo\n"
        "query-filters:\n"
        "  # Drop the stock pair so only the redactor-aware copies run.\n"
        "  - exclude:\n"
        "      id: py/clear-text-logging-sensitive-data  # stock query, no redactor\n",
    )
    head = _commit(repo, "reasoned exclude")
    assert cs.scan(base, head, cwd=repo) == []


def test_dependabot_ignore_needs_reason(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _write(
        repo,
        ".github/dependabot.yml",
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: npm\n"
        "    directory: /\n"
        "    ignore:\n"
        "      - dependency-name: minimatch\n",
    )
    head = _commit(repo, "bare ignore")
    kinds = {f.kind for f in cs.scan(base, head, cwd=repo)}
    assert "dependabot-ignore" in kinds
    _write(
        repo,
        ".github/dependabot.yml",
        "version: 2\n"
        "updates:\n"
        "  - package-ecosystem: npm\n"
        "    directory: /\n"
        "    ignore:\n"
        "      - dependency-name: minimatch  # no 10.x patch; eslint still pins 10\n",
    )
    head = _commit(repo, "reasoned ignore")
    assert cs.scan(base, head, cwd=repo) == []
