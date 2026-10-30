# -*- coding: utf-8 -*-
"""#900 rule-timeline-count: minute buckets use items; never activity.n."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
FLOOR = ROOT / "default" / "floor" / "floor-paint.js"
BOOT = ROOT / "default" / "boot.js"


def test_minute_bucket_reads_items_not_n():
    floor = FLOOR.read_text(encoding="utf-8")
    assert "e.items" in floor
    assert not re.search(r"e\.n\s*!=\s*null\s*\?\s*e\.n", floor)
    boot = BOOT.read_text(encoding="utf-8")
    assert "items: r.items" in boot
    assert "n: r.n" not in boot.split("function presenceRowsForUi", 1)[1].split("function evidenceHour", 1)[0]


_TL_HARNESS = r"""
const fs = require('fs');
global.window = global;
const el = { innerHTML: '', querySelectorAll() { return []; } };
global.document = { getElementById(id) { return id === 'floor-timeline' ? el : null; }, querySelectorAll() { return []; }, addEventListener() {} };
global.esc = s => String(s ?? '');
const now = Date.now();
global.activitySpanQuery = () => ({ key: 'k', window: '15m' });
global._presenceMiss = false;
global._presenceKey = 'k';
global._presenceRows = [];
global.floorWindowSpec = () => ({ ms: 15 * 60000, bucket: 60000 });
global.presenceRowsForUi = () => [
  { owner: 'builder', at: now - 30000, kind: 'mail', items: 3, n: 7 },
  { owner: 'builder', at: now - 30000, kind: 'todo', n: 5 },
];
global.floorDeskKey = o => String(o || '');
global.floorParseTs = v => Number(v);
global.floorTlSplit = 'desk';
global.PRESENCE_SERIES = [['mail', '#a'], ['todo', '#b'], ['hold', '#c']];
global.DESK_PALETTE = ['#d'];
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const seen = [];
global.floorTlSvg = (named) => { named.forEach(s => seen.push(Math.max.apply(null, s.values))); return ''; };
paintFloorTimeline({ desks: [{ owner: 'builder' }] });
process.stdout.write(JSON.stringify(seen));
"""


def test_minute_bucket_counts_items_when_row_has_n_too():
    import json
    import subprocess

    out = subprocess.run(["node", "-e", _TL_HARNESS, str(FLOOR)], capture_output=True, text=True, check=True).stdout
    mail, todo, hold = json.loads(out)
    assert mail == 3  # items wins over n
    assert todo == 1  # no items: one row is one, never n
    assert hold == 0
