# -*- coding: utf-8 -*-
"""Wall reads a row's roster from roster_id only (card #869, wall-contract rule-roster-fields #873).

Rosters replaced roles and projects. The retired group_id and project_id
fields must not come back into the Wall code, not even as a fallback.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
RETIRED = re.compile(r"\b(group_id|project_id)\b")
TEXT = {".js", ".css", ".html", ".py", ".json"}


def _hits() -> list[str]:
    out = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or "node_modules" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RETIRED.search(line):
                out.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    return out


def test_no_retired_roster_fields_in_wall():
    hits = _hits()
    assert not hits, "retired group_id/project_id in the Wall; read roster_id:\n" + "\n".join(hits)


def test_mill_gid_reads_roster_id():
    for rel in ("default/boot.js", "default/todo/todo.js"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        body = src.split("function millGid(r)", 1)[1].split("}", 1)[0]
        assert "r.roster_id" in body, rel


def test_check_finds_a_retired_field(tmp_path):
    probe = tmp_path / "x.js"
    probe.write_text("const g = r.group_id || r.project_id;\n", encoding="utf-8")
    assert RETIRED.findall(probe.read_text(encoding="utf-8")) == ["group_id", "project_id"]
