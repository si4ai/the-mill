"""Card 1147: check_dead_commands reports dead mill forms beyond check_doc_commands.

The command is a fact report: a scan of the repo exits 0 even when it finds
something (it is not a CI gate). --strict fails on a doctored tree and passes
on a clean one.
"""
from __future__ import annotations

from pathlib import Path

from tools import check_dead_commands as cdc

ROOT = Path(__file__).resolve().parents[2]


def _write(scan: Path, rel: str, text: str) -> None:
    path = scan / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _clean(scan: Path) -> None:
    _write(
        scan,
        "docs/security/regression/F-demo.md",
        "| F-demo | A desk runs `mill inbox` and `mill connect DESK`. |\n",
    )
    _write(
        scan,
        "agent_coord/server/hints.py",
        'HINT = "mill connect DESK first"\nUSAGE = "mill inbox"\n',
    )


def _doctored(scan: Path) -> None:
    _write(
        scan,
        "docs/security/regression/F-demo.md",
        "| F-demo | A desk runs `mill leftover` and `mill inbox --not-a-flag`. |\n",
    )
    _write(
        scan,
        "agent_coord/server/hints.py",
        'HINT = "mill leftover after work"\nUSAGE = "mill inbox --not-a-flag"\n',
    )


def test_doctored_tree_fails_strict(tmp_path: Path) -> None:
    _doctored(tmp_path)
    assert cdc.main(["--root", str(ROOT), "--scan", str(tmp_path), "--strict"]) == 1


def test_clean_tree_passes_strict(tmp_path: Path) -> None:
    _clean(tmp_path)
    assert cdc.main(["--root", str(ROOT), "--scan", str(tmp_path), "--strict"]) == 0


def test_repo_scan_is_a_report_not_a_gate() -> None:
    # Existing findings must not fail the default command (card 1147: checks over blocks).
    assert cdc.main(["--root", str(ROOT)]) == 0


def _readme_dead_command_argvs() -> list[list[str]]:
    text = (ROOT / "tools" / "README.md").read_text(encoding="utf-8")
    start = text.find("## check_dead_commands.py")
    assert start != -1, "tools/README.md is missing the check_dead_commands section"
    rest = text[start + 1 :]
    end = rest.find("\n## ")
    section = text[start:] if end < 0 else text[start : start + 1 + end]
    argvs: list[list[str]] = []
    for line in section.splitlines():
        raw = line.strip()
        if not raw.startswith("python tools/check_dead_commands.py"):
            continue
        code = raw.split("#", 1)[0].strip()
        parts = code.split()
        argvs.append(parts[2:])
    assert argvs, "README examples for check_dead_commands.py are missing"
    return argvs


def test_readme_examples_exit_0() -> None:
    """The documented commands must not fail on a missing --root (usage exit 2)."""
    argvs = _readme_dead_command_argvs()
    for args in argvs:
        if "--strict" in args:
            assert cdc.main(args) != 2
        else:
            assert cdc.main(args) == 0


def test_default_root_is_the_repo() -> None:
    assert cdc.main([]) == 0

