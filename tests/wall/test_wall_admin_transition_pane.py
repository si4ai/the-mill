# -*- coding: utf-8 -*-
"""card 1098: admin transition pane paint (mode, since, chips, tables, wake)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
INVITE = ROOT / "default" / "admin" / "invite.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const packet = JSON.parse(process.argv[3]);
const mode = process.argv[4] || 'paint';

const els = {};
function el(id, extra) {
  if (els[id]) return els[id];
  const o = Object.assign({
    id,
    innerHTML: '',
    hidden: false,
    disabled: false,
    value: '',
    className: '',
    classList: {
      _on: false,
      toggle(name, on) { if (name === 'on') this._on = !!on; },
      contains(name) { return name === 'on' && this._on; }
    },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
    querySelectorAll() { return []; },
    addEventListener() {}
  }, extra || {});
  Object.defineProperty(o, 'textContent', {
    get() { return this._text || ''; },
    set(v) { this._text = String(v); },
    configurable: true
  });
  els[id] = o;
  return o;
}

[
  'admin-tr-compress','admin-tr-capture','admin-tr-chips','admin-tr-pairs-input',
  'admin-tr-error','admin-tr-stats','admin-tr-by-type','admin-tr-by-pair',
  'admin-tr-compressed','admin-tr-wake','admin-tr-wake-body','admin-tr-note',
  'admin-tr-save-pairs','admin-tr-refresh','admin-tr-add-pair','admin-tr-reset-pairs',
  'admin-tr-pair-add','admin-tr-since-all','admin-tr-since-24h','admin-tr-since-7d',
  'admin-tr-since-label','admin-tr-host-note'
].forEach(id => el(id));

global.document = {
  getElementById(id) { return el(id); },
  querySelectorAll() { return []; }
};
global.window = global;
global.localStorage = { getItem() { return null; }, setItem() {} };
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });

(0, eval)(src);
const api = global.WallAdminInvites;
if (!api) throw new Error('no WallAdminInvites');

if (mode === 'save') {
  api.paintTransitions(packet);
  const joined = api.joinPairs(packet.pairs || []);
  process.stdout.write(JSON.stringify({
    joined,
    chips: els['admin-tr-chips'].innerHTML,
    modeCompress: els['admin-tr-compress'].getAttribute('aria-pressed'),
  }));
} else if (mode === 'since') {
  const want = String(process.argv[5] || '24h');
  api.setSinceUi(want);
  const body = api.sincePayload();
  const withMode = api.sincePayload({ mode: 'compress' });
  const withPairs = api.sincePayload({ pairs: 'a:b/c' });
  const label = els['admin-tr-since-label'].textContent;
  const pressed24 = els['admin-tr-since-24h'].getAttribute('aria-pressed');
  const pressedAllOnWindow = els['admin-tr-since-all'].getAttribute('aria-pressed');
  api.setSinceUi('');
  const all = api.sincePayload();
  process.stdout.write(JSON.stringify({
    sinceOnWindow: want,
    body,
    withMode,
    withPairs,
    all,
    label,
    pressed24,
    pressedAllOnWindow,
    sinceAfterClear: api.getSince(),
    pressedAllAfterClear: els['admin-tr-since-all'].getAttribute('aria-pressed'),
  }));
} else {
  api.paintTransitions(packet);
  const out = {
    modeCompress: els['admin-tr-compress'].getAttribute('aria-pressed'),
    modeCapture: els['admin-tr-capture'].getAttribute('aria-pressed'),
    compressOn: els['admin-tr-compress'].classList.contains('on'),
    captureOn: els['admin-tr-capture'].classList.contains('on'),
    chips: els['admin-tr-chips'].innerHTML,
    pairsInput: els['admin-tr-pairs-input'].value,
    stats: els['admin-tr-stats'].textContent,
    byType: els['admin-tr-by-type'].innerHTML,
    byPair: els['admin-tr-by-pair'].innerHTML,
    compressed: els['admin-tr-compressed'].innerHTML,
    wakeHidden: !!els['admin-tr-wake'].hidden,
    wakeBody: els['admin-tr-wake-body'].innerHTML,
    errorHidden: !!els['admin-tr-error'].hidden,
    errorText: els['admin-tr-error'].textContent,
    note: els['admin-tr-note'].textContent,
    since: api.getSince(),
    sinceLabel: els['admin-tr-since-label'].textContent,
    typeSavedMissing: api.typeSaved({ rows: 2, events: 5 }),
    typeSavedPresent: api.typeSaved({ rows: 2, events: 5, saved_rows: 9 }),
    share: api.sharePct(3, 10),
    join: api.joinPairs(['a:b/c', ' d:e/f ', '']),
    wakeEmpty: api.htmlWake([]),
    wakeNull: api.htmlWake(null),
  };
  process.stdout.write(JSON.stringify(out));
}
"""


def _run(packet: dict, *, mode: str = "paint", since: str = "") -> dict:
    node = shutil.which("node")
    assert node, "node required"
    with tempfile.TemporaryDirectory() as td:
        harness = Path(td) / "h.js"
        harness.write_text(HARNESS, encoding="utf-8")
        cmd = [node, str(harness), str(INVITE), json.dumps(packet), mode]
        if mode == "since":
            cmd.append(since or "24h")
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


BASE = {
    "mode": "compress",
    "pairs": ["doing:seated/connected", "hold:free/held"],
    "pairs_raw": "doing:seated/connected,hold:free/held",
    "default_pairs": "doing:seated/connected,hold:free/held,hold:held/held",
    "note": "compress note",
    "analysis": {
        "total_rows": 10,
        "total_events": 40,
        "saved_rows": 30,
        "by_type": [
            {"activity_type": "doing", "rows": 4, "events": 20, "saved_rows": 16},
            {"activity_type": "hold", "rows": 6, "events": 20, "saved_rows": 14},
        ],
        "by_pair": [
            {
                "activity_type": "doing",
                "from_state": "connected",
                "to_state": "seated",
                "rows": 4,
                "events": 20,
                "saved_rows": 16,
            },
            {
                "activity_type": "hold",
                "from_state": "held",
                "to_state": "held",
                "rows": 0,
                "events": 0,
                "saved_rows": 0,
            },
        ],
        "top_compressed": [
            {
                "activity_type": "doing",
                "from_state": "seated",
                "to_state": "connected",
                "n": 12,
                "at": "2026-11-09 10:00:00",
            }
        ],
        "wake": [
            {"label": "queued", "value": 10},
            {"label": "sent", "value": 4},
            {"label": "missed", "value": 3},
            {"label": "done", "value": 5},
            {"label": "auto_done", "value": 2},
            {"label": "receipt_unopened", "value": 1},
            {"label": "receipt_opened", "value": 2},
        ],
    },
}


def test_paint_compress_mode_chips_tables_and_wake():
    got = _run(BASE)
    assert got["modeCompress"] == "true"
    assert got["modeCapture"] == "false"
    assert got["compressOn"] is True
    assert "doing:seated/connected" in got["chips"]
    assert got["pairsInput"] == "doing:seated/connected,hold:free/held"
    assert "10 rows / 40 events (saved 30)" in got["stats"]
    assert 'data-table="admin-tr-by-type"' in got["byType"]
    assert ">16<" in got["byType"]
    assert ">14<" in got["byType"]
    assert "80%" in got["byType"]
    assert "70%" in got["byType"]
    assert 'data-table="admin-tr-by-pair"' in got["byPair"]
    assert "held -&gt; held" in got["byPair"]
    assert ">0<" in got["byPair"]  # zero-fire pair
    assert "seated -&gt; connected" in got["compressed"]
    assert got["wakeHidden"] is False
    assert "missed" in got["wakeBody"]
    assert "wake owed never delivered" in got["wakeBody"]
    assert "receipt_unopened" in got["wakeBody"]
    assert "receipt row not yet opened" in got["wakeBody"]
    assert ">3<" in got["wakeBody"] or ">3</dd>" in got["wakeBody"] or "3</dd>" in got["wakeBody"]
    assert got["errorHidden"] is True
    assert got["typeSavedMissing"] == 3
    assert got["typeSavedPresent"] == 9
    assert got["share"] == "30%"
    assert got["join"] == "a:b/c,d:e/f"
    assert got["wakeEmpty"] == ""
    assert got["wakeNull"] == ""


def test_paint_capture_with_error_escape_hides_wake():
    packet = {
        "mode": "capture",
        "pairs": ["x:<script>/y"],
        "default_pairs": "doing:seated/connected",
        "note": "n",
        "analysis": {
            "since": "24h",
            "total_rows": 2,
            "total_events": 2,
            "saved_rows": 0,
            "by_type": [
                {"activity_type": "x", "rows": 2, "events": 2, "saved_rows": 0},
            ],
            "by_pair": [
                {
                    "activity_type": "x",
                    "from_state": "<",
                    "to_state": "y",
                    "rows": 0,
                    "events": 0,
                    "saved_rows": 0,
                }
            ],
            "top_compressed": [],
            "error": "boom <x>",
        },
    }
    got = _run(packet)
    assert got["modeCapture"] == "true"
    assert "&lt;script&gt;" in got["chips"]
    assert "<script>" not in got["chips"]
    assert "&lt; -&gt; y" in got["byPair"]
    assert got["wakeHidden"] is True
    assert got["errorHidden"] is False
    assert got["errorText"] == "boom <x>"
    assert got["since"] == "24h"
    assert "24h" in got["sinceLabel"]
    assert "no compressed rows yet" in got["compressed"]


def test_since_selector_payload_includes_or_omits_since():
    got = _run({}, mode="since", since="24h")
    assert got["body"] == {"action": "transition", "since": "24h"}
    assert got["withMode"] == {"action": "transition", "mode": "compress", "since": "24h"}
    assert got["withPairs"] == {"action": "transition", "pairs": "a:b/c", "since": "24h"}
    assert got["all"] == {"action": "transition"}
    assert "since" not in got["all"]
    assert got["pressed24"] == "true"
    assert got["pressedAllOnWindow"] == "false"
    assert "24h" in got["label"]
    assert got["sinceAfterClear"] == ""
    assert got["pressedAllAfterClear"] == "true"


def test_save_posts_one_comma_string():
    got = _run(BASE, mode="save")
    assert got["joined"] == "doing:seated/connected,hold:free/held"
    assert got["joined"].count(",") == 1
