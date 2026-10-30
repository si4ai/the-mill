# -*- coding: utf-8 -*-
"""#897 rule-doing-focus: a move row is never painted as current.
#898 rule-card-evidence: the card trail's evidence slot shows the newest ship/done
evidence and a later back clears it. Trails hold rows newest first, as the history
route serves them."""
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
const extra = JSON.parse(process.argv[4] || '[]');
const rows = fx.history.filter(e => e.on === 'todo-1').concat(extra).sort((a, b) => b.at.localeCompare(a.at));
window.WALL_DOING.trails['todo-1'] = { state: 'ok', rows, at: Date.now(), entries: rows.length };
const html = wallDoingTrailHtml('todo-1');
const bits = [...html.matchAll(/data-act="([^"]*)"[\s\S]*?class="doing-ended"[^>]*>([^<]*)</g)].map(m => [m[1], m[2]]);
const evidence = wallDoingCardEvidence('todo-1');
const slot = (html.match(/<span class="dt-card-evidence"[^>]*>([\s\S]*?)<\/span><span class="dt-/) || [null, null])[1];
process.stdout.write(JSON.stringify({ bits, evidence, slot, html }));
"""


def _paint(extra=()):
    return json.loads(
        subprocess.run(
            ["node", "-e", _HARNESS, str(DATA), str(DOING), str(FIXTURE), json.dumps(list(extra))],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )


def test_move_rows_never_current_and_evidence_clears_on_back():
    out = _paint()
    acts = [a for a, _ in out["bits"]]
    assert "claim" in acts and "ship" in acts and "done" in acts and "back" in acts
    for act, how in out["bits"]:
        if act in ("claim", "ship", "done", "back", "hold", "drop", "park", "note", "assign", "unclaim", "unpark"):
            assert how != "current", (act, how)
    assert out["evidence"] == ""
    # The slot is painted on the card trail, and back left it blank.
    assert out["slot"] == ""


def test_open_move_row_is_never_current():
    # A move row the server has not ended yet: only the act may paint, never "current".
    out = _paint([{"id": 9100, "desk": "builder", "at": "2026-10-23 04:00:00", "doing": "",
                   "on": "todo-1", "act": "claim", "ended": False, "ended_by": None}])
    claims = [how for act, how in out["bits"] if act == "claim"]
    assert claims and "current" not in claims, out["bits"]


def test_card_slot_paints_ship_then_back_clears_it():
    shipped = _paint([{"id": 9101, "desk": "builder", "at": "2026-10-23 04:00:00", "doing": "",
                       "on": "todo-1", "act": "ship", "evidence": "stage 2 landed",
                       "ended": True, "ended_by": "finished"}])
    assert shipped["evidence"] == "stage 2 landed"
    assert "stage 2 landed" in (shipped["slot"] or "")
    backed = _paint([
        {"id": 9101, "desk": "builder", "at": "2026-10-23 04:00:00", "doing": "",
         "on": "todo-1", "act": "ship", "evidence": "stage 2 landed", "ended": True, "ended_by": "finished"},
        {"id": 9102, "desk": "builder", "at": "2026-10-23 04:30:00", "doing": "",
         "on": "todo-1", "act": "back", "ended": True, "ended_by": "finished"},
    ])
    assert backed["evidence"] == ""
    assert backed["slot"] == ""
    # The ship row's own evidence still sits in the trail history.
    assert "stage 2 landed" in backed["html"]
