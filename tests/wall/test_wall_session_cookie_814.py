# -*- coding: utf-8 -*-
"""The Wall human session stays in the HttpOnly door cookie (card 814).

Javascript must not name the storage key. The door cookie rides the
same-origin invite fetch, and the server already accepts that cookie.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WALL = REPO / "agent_coord" / "web" / "wall_ui"
KEY = "factory-human-token"
TEXT = {".js", ".html"}


def _hits() -> list[str]:
    out = []
    for path in sorted(WALL.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or "node_modules" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if KEY in line:
                out.append(f"{path.relative_to(WALL).as_posix()}:{n}")
    return out


def test_wall_scripts_do_not_name_the_human_session_key():
    hits = _hits()
    assert not hits, "human session key in javascript-readable Wall source:\n" + "\n".join(hits)


def test_detector_flags_the_storage_key(tmp_path):
    probe = tmp_path / "x.js"
    probe.write_text(
        'token = localStorage.getItem("factory-human-token") || "";\n',
        encoding="utf-8",
    )
    assert KEY in probe.read_text(encoding="utf-8")
