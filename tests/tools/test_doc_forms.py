"""F42 (doc-forms): every mill form the agent docs teach parses with the mill parser (#303, #304).

Checked: code spans that start with `mill COMMAND`, fenced lines that start with
`mill COMMAND`, and every code span in the Command column of the commands.md idiom tables.
A retired form (label-add, member-add, invite-seat) fails. A word that is named
only to say it is not a command passes when its line says so (not, no, never).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_coord.__main__ import _build_parser

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(
    {
        ROOT / "docs" / "JOIN.md",
        ROOT / "README.md",
        *(ROOT / "docs" / "protocol").glob("*.md"),
        *(ROOT / "docs" / "install").glob("*.md"),
        *(ROOT / "docs" / "skills").glob("*.md"),
        *(ROOT / "docs" / "skills").glob("*/SKILL.md"),
    }
)
# Named in the docs only to say there is no such command.
NOT_COMMANDS = {"waiting", "sync", "register", "heartbeat", "use"}
_NEG = re.compile(r"\b(?:not|no|never)\b", re.I)
_MILL = re.compile(r"^\s*(?:\$ )?mill (?:--office \S+ )?([a-z][a-z-]*)")
_SPAN = re.compile(r"`([^`]+)`")


def _commands() -> set[str]:
    p = _build_parser()
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    return set(sub.choices)


def _ok(word: str, line: str, commands: set[str]) -> bool:
    return word in commands or (word in NOT_COMMANDS and bool(_NEG.search(line)))


def bad_forms(path: Path, commands: set[str]) -> list[str]:
    out: list[str] = []
    fence = idiom = False
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if ln.startswith("```"):
            fence = not fence
            continue
        where = f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path.name}:{i}"
        if fence:
            m = _MILL.match(ln)
            if m and not _ok(m.group(1), ln, commands):
                out.append(f"{where}: mill {m.group(1)}")
            continue
        if ln.startswith("| Human idiom"):
            idiom = True
            continue
        if not ln.startswith("|"):
            idiom = False
        spans = _SPAN.findall(ln)
        for sp in spans:
            m = _MILL.match(sp)
            if m and not _ok(m.group(1), ln, commands):
                out.append(f"{where}: mill {m.group(1)}")
        if idiom and not ln.startswith("| :-") and not ln.startswith("|--"):
            # Command column: drop the idiom cell (first column), keep every span after it.
            rest = _SPAN.sub(lambda m: "`" + m.group(1).replace("|", "\0") + "`", ln).split("|", 2)[-1]
            for sp in _SPAN.findall(rest):
                words = sp.replace("\0", "|").split()
                w = words[1] if words[0] == "mill" and len(words) > 1 else words[0]
                if re.fullmatch(r"[a-z][a-z-]*", w) and not _ok(w, ln, commands):
                    out.append(f"{where}: idiom command {w}")
    return out


def test_every_taught_form_parses() -> None:
    commands = _commands()
    bad = [b for f in FILES for b in bad_forms(f, commands)]
    assert not bad, "retired or unknown mill forms:\n" + "\n".join(bad)


@pytest.mark.parametrize(
    "text,hits",
    [
        ("Use `mill invite-seat x`.\n", 1),
        ("| Human idiom | Command |\n| :--- | :--- |\n| *\"tag\"* | `label-add <mail|todo> <id>` |\n", 1),
        ("| Human idiom | Command |\n| :--- | :--- |\n| *\"join\"* | `member-add <group>` |\n", 1),
        ("```\nmill label-add mail 1 bug\n```\n", 1),
        ("No `mill sync` command.\n", 0),
        ("Run `mill sync` now.\n", 1),
        ("Use `mill invite --seat DESK`.\n", 0),
        ("| Human idiom | Command |\n| :--- | :--- |\n| *\"tag\"* | `label <mail|todo> <id> <label>` |\n", 0),
    ],
)
def test_retired_forms_fail(tmp_path, text, hits) -> None:
    f = tmp_path / "probe.md"
    f.write_text(text, encoding="utf-8")
    assert len(bad_forms(f, _commands())) == hits
