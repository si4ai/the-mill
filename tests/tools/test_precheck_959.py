"""Card 959 / F-precheck: tools/precheck.sh exits non-zero on each class of finding."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    import sys
    name = "precheck_959"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "precheck.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pc():
    path = ROOT / "tools" / "precheck.py"
    if not path.is_file():
        pytest.fail("tools/precheck.py missing")
    return _load()


def test_precheck_sh_exists_and_is_executable():
    sh = ROOT / "tools" / "precheck.sh"
    assert sh.is_file(), "tools/precheck.sh missing"
    assert os.access(sh, os.X_OK) or sh.read_text(encoding="utf-8").startswith("#!"), sh


def test_makefile_has_precheck_target():
    mk = ROOT / "Makefile"
    assert mk.is_file(), "Makefile missing"
    assert "precheck" in mk.read_text(encoding="utf-8")


def test_changelog_flags_pr_cite_without_card(pc, tmp_path):
    """New CHANGELOG bullets must cite a card, not only a PR number."""
    text = textwrap.dedent(
        """\
        # Changelog

        ## TBD (upcoming)

        Upcoming changes are our current plan, not a promise; they can change or move at release time.

        ## New changes

        0.9.0

        - #999 only a PR cite

        ## Last changes

        0.8.1 (2026-10-31)

        - card 1: old
        """
    )
    p = tmp_path / "CHANGELOG.md"
    p.write_text(text, encoding="utf-8")
    findings = pc.check_changelog(p, base_text="")
    assert any(f.rule == "changelog-card" for f in findings), findings


def test_changelog_flags_entry_under_shipped_without_date(pc, tmp_path):
    text = textwrap.dedent(
        """\
        # Changelog

        ## TBD (upcoming)

        Upcoming changes are our current plan, not a promise; they can change or move at release time.

        ## New changes

        ## Last changes

        0.8.1

        - card 1: undated shipped heading
        """
    )
    p = tmp_path / "CHANGELOG.md"
    p.write_text(text, encoding="utf-8")
    findings = pc.check_changelog(p, base_text="")
    assert any(f.rule == "changelog-date" for f in findings), findings


def test_frow_flags_new_numbered_file(pc, tmp_path):
    reg = tmp_path / "docs" / "security" / "regression"
    reg.mkdir(parents=True)
    (reg / "F999.md").write_text("| F999 | x | y | z |\n", encoding="utf-8")
    (reg / "F-ok.md").write_text("| F-ok | x | y | z |\n", encoding="utf-8")
    findings = pc.check_frows(tmp_path, new_paths=["docs/security/regression/F999.md", "docs/security/regression/F-ok.md"])
    assert any(f.rule == "frow-numbered" and "F999" in f.message for f in findings), findings
    assert not any("F-ok" in f.message and f.rule == "frow-numbered" for f in findings)


def test_frow_flags_duplicate_id(pc, tmp_path):
    reg = tmp_path / "docs" / "security" / "regression"
    reg.mkdir(parents=True)
    (reg / "F-dup-a.md").write_text("| F-dup | a | b | c |\n", encoding="utf-8")
    (reg / "F-dup-b.md").write_text("| F-dup | a | b | c |\n", encoding="utf-8")
    findings = pc.check_frows(tmp_path, new_paths=[])
    assert any(f.rule == "frow-dup" for f in findings), findings


def test_mill_verb_flags_unknown_in_hint(pc, tmp_path):
    src = tmp_path / "agent_coord" / "hints.py"
    src.parent.mkdir(parents=True)
    src.write_text('HINT = "Next: mill roster then go"\n', encoding="utf-8")
    findings = pc.check_mill_verbs(tmp_path, paths=[src.relative_to(tmp_path).as_posix()])
    assert any(f.rule == "mill-verb" and "roster" in f.message for f in findings), findings


def test_schema_flags_non_bigint_id(pc, tmp_path):
    ddl = tmp_path / "docs" / "requirements" / "beta" / "beta_ddl.sql"
    ddl.parent.mkdir(parents=True)
    ddl.write_text(
        "CREATE TABLE t (\n  id INT NOT NULL AUTO_INCREMENT,\n  desk_id BIGINT UNSIGNED NOT NULL\n);\n",
        encoding="utf-8",
    )
    findings = pc.check_schema_ids(tmp_path)
    assert any(f.rule == "schema-id" and "INT" in f.message for f in findings), findings


def test_finding_line_format(pc):
    f = pc.Finding("CHANGELOG.md", 3, "changelog-card", "cite card not PR")
    line = pc.format_finding(f)
    assert line == "CHANGELOG.md:3 changelog-card cite card not PR"


def test_ok_line_names_sha(pc):
    assert pc.ok_line("abc123def") == "precheck OK abc123def"


def test_ci_runs_precheck():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "precheck" in text
    assert "tools/precheck.sh" in text or "tools/precheck.py" in text


_STUB_CHECK_PACK = textwrap.dedent(
    """\
    import os, subprocess, sys
    args = sys.argv[1:]
    log = os.environ["PRECHECK_STUB_LOG"]
    if args[:1] == ["--commits"]:
        r = subprocess.run(["git", "rev-list", args[1]], capture_output=True, text=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"commits rc={r.returncode} n={len(r.stdout.split())}\\n")
        sys.exit(r.returncode)
    sys.exit(0)
    """
)


def _git_t(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("detached", [False, True])
def test_pack_fresh_commits_from_non_main_branch(pc, tmp_path, monkeypatch, detached):
    """check_pack_fresh resolves origin/main from a release branch or a detached head."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git_t(upstream, "init", "-q", "-b", "main")
    (upstream / "tools").mkdir()
    (upstream / "tools" / "check_pack.py").write_text(_STUB_CHECK_PACK, encoding="utf-8")
    _git_t(upstream, "add", ".")
    _git_t(upstream, "commit", "-q", "-m", "base")
    work = tmp_path / "work"
    _git_t(tmp_path, "clone", "-q", str(upstream), str(work))
    _git_t(work, "checkout", "-q", "-b", "release/9.9.9")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    _git_t(work, "add", ".")
    _git_t(work, "commit", "-q", "-m", "release change")
    if detached:
        _git_t(work, "checkout", "-q", "--detach")
    sha = pc._rev_parse("HEAD", cwd=work)

    fake_py = tmp_path / "fake-python"
    fake_py.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-m" ] && [ "$2" = "build" ]; then exit 0; fi\n'
        f'exec "{pc.sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    fake_py.chmod(0o755)
    log = tmp_path / "stub.log"
    monkeypatch.setenv("PRECHECK_STUB_LOG", str(log))
    monkeypatch.setattr(pc.sys, "executable", str(fake_py))

    findings = pc.check_pack_fresh(work, sha)

    assert findings == [], findings
    assert log.read_text(encoding="utf-8").splitlines() == ["commits rc=0 n=1"]


def test_pack_fresh_unresolvable_base_is_a_finding(pc, tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git_t(repo, "init", "-q", "-b", "feature")
    (repo / "x").write_text("x\n", encoding="utf-8")
    _git_t(repo, "add", ".")
    _git_t(repo, "commit", "-q", "-m", "x")
    findings = pc.check_pack_fresh(repo, pc._rev_parse("HEAD", cwd=repo), base="origin/main")
    assert [f.rule for f in findings] == ["check-pack"]
    assert "does not resolve" in findings[0].message
