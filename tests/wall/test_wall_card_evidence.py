# -*- coding: utf-8 -*-
"""#898 rule-card-evidence: evidence from doing.evidence on ship/done rows."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
DATA = ROOT / "lib" / "data.js"


def _run(rows):
    harness = r"""
const fs = require('fs');
const dataFile = process.argv[1];
const rows = JSON.parse(process.argv[2]);
global.window = global;
(0, eval)(fs.readFileSync(dataFile, 'utf8'));
process.stdout.write(JSON.stringify(wallCardEvidenceFromTrail(rows)));
"""
    return subprocess.run(
        ["node", "-e", harness, str(DATA), json.dumps(rows)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_newest_ship_or_done_wins_and_back_clears():
    assert _run([
        {"act": "claim"},
        {"act": "ship", "evidence": "one"},
        {"act": "done", "evidence": "two"},
    ]) == '"two"'
    assert _run([
        {"act": "ship", "evidence": "one"},
        {"act": "done", "evidence": "two"},
        {"act": "back"},
    ]) == '""'
    assert _run([
        {"act": "ship", "evidence": "one"},
        {"act": "focus", "doing": "still working"},
    ]) == '"one"'


def test_never_reads_todo_dot_evidence_in_wall_js():
    for path in sorted((ROOT / "default").rglob("*.js")):
        src = path.read_text(encoding="utf-8")
        assert "todo.evidence" not in src
