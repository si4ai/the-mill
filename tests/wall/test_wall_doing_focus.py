# -*- coding: utf-8 -*-
"""#897 rule-doing-focus: a move row is never painted as current."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
DOING = ROOT / "default" / "doing" / "doing-paint.js"
DATA = ROOT / "lib" / "data.js"
FIXTURE = Path(__file__).with_name("doing_818_fixture.json")

_HARNESS = r"""
const fs = require('fs');
const [dataFile, doingFile, fxFile] = process.argv.slice(1);
const fx = JSON.parse(fs.readFileSync(fxFile, 'utf8'));
global.window = global;
global.document = { querySelectorAll() { return []; }, addEventListener() {} };
global.esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.dt = v => (v ? String(v).replace('T', ' ').slice(0, 19) : '-');
global.millName = (k, v) => String(v || '');
(0, eval)(fs.readFileSync(dataFile, 'utf8'));
window.WALL_DOING = { state: 'ok', byOwner: null, at: 0, sig: '', inflight: null, trails: {}, historyAbsentAt: 0 };
(0, eval)(fs.readFileSync(doingFile, 'utf8'));
const rows = fx.history.filter(e => e.on === 'todo-1').sort((a, b) => a.at.localeCompare(b.at));
window.WALL_DOING.trails['todo-1'] = { state: 'ok', rows, at: Date.now(), entries: rows.length };
const html = wallDoingTrailHtml('todo-1');
const bits = [...html.matchAll(/data-act="([^"]*)"[\s\S]*?class="doing-ended"[^>]*>([^<]*)</g)].map(m => [m[1], m[2]]);
const evidence = wallDoingCardEvidence('todo-1');
process.stdout.write(JSON.stringify({ bits, evidence, html }));
"""


def test_move_rows_never_current_and_evidence_clears_on_back():
    out = json.loads(
        subprocess.run(
            ["node", "-e", _HARNESS, str(DATA), str(DOING), str(FIXTURE)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    acts = [a for a, _ in out["bits"]]
    assert "claim" in acts and "ship" in acts and "done" in acts and "back" in acts
    for act, how in out["bits"]:
        if act in ("claim", "ship", "done", "back", "hold", "drop", "park", "note", "assign", "unclaim", "unpark"):
            assert how != "current", (act, how)
    assert out["evidence"] == ""
