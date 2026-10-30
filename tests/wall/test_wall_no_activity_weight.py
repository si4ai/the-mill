# -*- coding: utf-8 -*-
"""#896 rule-no-activity-weight: the Wall never reads activity.n or activity.weight."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score-paint.js"
BOOT = ROOT / "default" / "boot.js"
WALL_JS = sorted((ROOT / "default").rglob("*.js")) + sorted((ROOT / "lib").glob("*.js"))


def test_no_presence_spend_fallback_and_unavailable():
    score = SCORE.read_text(encoding="utf-8")
    assert "presenceSpendLines" not in score
    assert "Number(e.n || 0) * Number(e.weight" not in score
    assert "unavailable" in score
    assert re.search(r"function millSpend\(", score)


def test_wall_js_never_reads_event_weight_field():
    for path in WALL_JS:
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for m in re.finditer(r"(?<![a-zA-Z])e\.weight\b|(?<![a-zA-Z])r\.weight\b|event\.weight\b", src):
            full = src[max(0, m.start() - 60) : m.start() + 40]
            raise AssertionError(f"{rel}: activity weight read: {full!r}")


def test_boot_comment_does_not_teach_n_weight_spend():
    boot = BOOT.read_text(encoding="utf-8")
    assert "presence.n*weight" not in boot


_SPEND_HARNESS = r"""
const fs = require('fs');
const lines = JSON.parse(process.argv[2]);
global.window = global;
const el = { innerHTML: '' };
global.document = { getElementById(id) { return id === 'score-spend' ? el : null; }, querySelectorAll() { return []; }, addEventListener() {} };
global.esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.dt = v => String(v || '');
global.millGid = () => '';
global.rowDay = r => String(r.at || '').slice(0, 10);
global.spendWindow = 'all';
global.spendOwner = '';
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
millSpend({ spend_lines: lines, spend: [], presence: [{ kind: 'mail', n: 9, weight: 3 }] });
process.stdout.write(el.innerHTML);
"""


def _spend_head(lines):
    import json
    import subprocess

    return subprocess.run(
        ["node", "-e", _SPEND_HARNESS, str(SCORE), json.dumps(lines)],
        capture_output=True, text=True, check=True,
    ).stdout


def test_spend_head_paints_unavailable_without_spend_lines():
    # Activity n and weight are on the payload; the head still says unavailable.
    assert _spend_head([]) == "MILL SPEND<b>unavailable</b>"
    head = _spend_head([{"owner": "builder", "at": "2026-10-23 01:00:00", "bytes_out": 120, "usd": 0.001}])
    assert "unavailable" not in head
    assert "MILL SPEND<b>120</b> B" in head
