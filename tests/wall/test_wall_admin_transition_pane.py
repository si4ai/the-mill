# -*- coding: utf-8 -*-
"""card 1098: admin transition pane paint (mode, chips, tables, save string)."""
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
const wantSave = process.argv[4] === '1';

const els = {};
function el(id, extra) {
  if (els[id]) return els[id];
  const o = Object.assign({
    id,
    innerHTML: '',
    textContent: '',
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
  // keep textContent and innerHTML loosely linked for asserts
  Object.defineProperty(o, 'textContent', {
    get() { return this._text || ''; },
    set(v) { this._text = String(v); this.innerHTML = ''; },
    configurable: true
  });
  els[id] = o;
  return o;
}

['admin-tr-compress','admin-tr-capture','admin-tr-chips','admin-tr-pairs-input',
 'admin-tr-error','admin-tr-stats','admin-tr-by-type','admin-tr-by-pair',
 'admin-tr-compressed','admin-tr-wake','admin-tr-wake-body','admin-tr-note',
 'admin-tr-save-pairs','admin-tr-refresh','admin-tr-add-pair','admin-tr-reset-pairs',
 'admin-tr-pair-add'].forEach(id => el(id));

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

const posts = [];
if (wantSave) {
  // re-bind adminPost path by painting pairs then calling save via joinPairs
  api.paintTransitions(packet);
  const joined = api.joinPairs(packet.pairs || []);
  posts.push(joined);
  const out = {
    joined,
    chips: els['admin-tr-chips'].innerHTML,
    modeCompress: els['admin-tr-compress'].getAttribute('aria-pressed'),
    modeCapture: els['admin-tr-capture'].getAttribute('aria-pressed'),
  };
  process.stdout.write(JSON.stringify(out));
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
    typeSavedMissing: api.typeSaved({ rows: 2, events: 5 }),
    typeSavedPresent: api.typeSaved({ rows: 2, events: 5, saved_rows: 9 }),
    share: api.sharePct(3, 10),
    join: api.joinPairs(['a:b/c', ' d:e/f ', '']),
  };
  process.stdout.write(JSON.stringify(out));
}
"""


def _run(packet: dict, *, want_save: bool = False) -> dict:
    node = shutil.which("node")
    assert node, "node required"
    with tempfile.TemporaryDirectory() as td:
        harness = Path(td) / "h.js"
        harness.write_text(HARNESS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), str(INVITE), json.dumps(packet), "1" if want_save else "0"],
            check=True,
            capture_output=True,
            text=True,
        )
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
            {"activity_type": "doing", "rows": 4, "events": 20},
            {"activity_type": "hold", "rows": 6, "events": 20},
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
    },
}


def test_paint_compress_mode_chips_and_tables():
    got = _run(BASE)
    assert got["modeCompress"] == "true"
    assert got["modeCapture"] == "false"
    assert got["compressOn"] is True
    assert got["captureOn"] is False
    assert "doing:seated/connected" in got["chips"]
    assert "hold:free/held" in got["chips"]
    assert got["pairsInput"] == "doing:seated/connected,hold:free/held"
    assert "10 rows / 40 events (saved 30)" in got["stats"]
    assert 'data-table="admin-tr-by-type"' in got["byType"]
    assert "<code>doing</code>" in got["byType"]
    assert "<code>hold</code>" in got["byType"]
    # client-side saved when by_type.saved_rows missing: 20-4=16, 20-6=14
    assert ">16<" in got["byType"]
    assert ">14<" in got["byType"]
    assert "40%" in got["byType"] or "80%" in got["byType"]  # 16/20=80%, 14/20=70%
    assert "80%" in got["byType"]
    assert "70%" in got["byType"]
    assert "total" in got["byType"]
    assert got["byPair"] == ""
    assert "seated -&gt; connected" in got["compressed"]
    assert ">12<" in got["compressed"]
    assert got["wakeHidden"] is True
    assert got["errorHidden"] is True
    assert got["note"] == "compress note"
    assert got["typeSavedMissing"] == 3
    assert got["typeSavedPresent"] == 9
    assert got["share"] == "30%"
    assert got["join"] == "a:b/c,d:e/f"


def test_paint_capture_with_by_pair_wake_and_error_escape():
    packet = {
        "mode": "capture",
        "pairs": ["x:<script>/y"],
        "default_pairs": "doing:seated/connected",
        "note": "n",
        "analysis": {
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
            "wake": {"owed_ratio": "0.1", "wasted_wake_done": 2},
            "error": "boom <x>",
        },
    }
    got = _run(packet)
    assert got["modeCompress"] == "false"
    assert got["modeCapture"] == "true"
    assert got["captureOn"] is True
    assert "&lt;script&gt;" in got["chips"]
    assert "<script>" not in got["chips"]
    assert 'data-table="admin-tr-by-pair"' in got["byPair"]
    assert "&lt; -&gt; y" in got["byPair"]
    assert got["wakeHidden"] is False
    assert "owed_ratio" in got["wakeBody"]
    assert "0.1" in got["wakeBody"]
    assert "wasted_wake_done" in got["wakeBody"]
    assert got["errorHidden"] is False
    assert got["errorText"] == "boom <x>"
    assert "no compressed rows yet" in got["compressed"]


def test_save_posts_one_comma_string():
    got = _run(BASE, want_save=True)
    assert got["joined"] == "doing:seated/connected,hold:free/held"
    assert "," in got["joined"]
    assert got["joined"].count(",") == 1
