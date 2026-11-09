# -*- coding: utf-8 -*-
"""card 1098: Book tab type table, transitions block, wake-health alert row."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SERVICE = ROOT / "default" / "session" / "service-paint.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const packet = JSON.parse(process.argv[3]);
const mode = process.argv[4] || 'book';

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

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
    querySelector() { return null; },
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
  'svc-tr-compress','svc-tr-capture','svc-tr-error','svc-tr-stats','svc-tr-by-type',
  'svc-tr-by-pair','svc-tr-wake','svc-tr-wake-body','svc-tr-note','svc-tr-wait',
  'svc-tr-mode-line','svc-tr-since-all','svc-tr-since-24h','svc-tr-since-7d',
  'svc-tr-refresh','svc-tr-block','svc-wake-alert','wall-service-body'
].forEach(id => el(id));

global.document = {
  getElementById(id) { return el(id); },
  querySelectorAll() { return []; }
};
global.window = global;
global.localStorage = { getItem() { return null; }, setItem() {} };
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
global.esc = esc;
global.wallHumanReadonly = () => true;
global._svcPacket = { book: packet.book || {}, alerts: packet.alerts || {} };
global._svcSection = mode === 'alerts' ? 'alerts' : 'book';
global.glanceMarkSection = function () {};

(0, eval)(src);
const api = global.WallServiceBook;
if (!api) throw new Error('no WallServiceBook');

if (mode === 'book') {
  const html = api.typeTableHtml(packet.book || {});
  const shell = api.transitionsShellHtml();
  process.stdout.write(JSON.stringify({ html, shell }));
} else if (mode === 'analysis') {
  api.paintAnalysis(packet);
  process.stdout.write(JSON.stringify({
    modeLine: els['svc-tr-mode-line'].textContent,
    compressOn: els['svc-tr-compress'].classList.contains('on'),
    captureOn: els['svc-tr-capture'].classList.contains('on'),
    errorHidden: !!els['svc-tr-error'].hidden,
    errorText: els['svc-tr-error'].textContent,
    stats: els['svc-tr-stats'].textContent,
    byType: els['svc-tr-by-type'].innerHTML,
    byPair: els['svc-tr-by-pair'].innerHTML,
    wakeHidden: !!els['svc-tr-wake'].hidden,
    wakeBody: els['svc-tr-wake-body'].innerHTML,
    since: api.getSince(),
  }));
} else if (mode === 'wake') {
  const html = api.wakeAlertHtml(packet.wake || []);
  const counts = api.wakeCounts(packet.wake || []);
  process.stdout.write(JSON.stringify({ html, counts }));
} else if (mode === 'error') {
  api.paintAnalysis(packet);
  process.stdout.write(JSON.stringify({
    modeLine: els['svc-tr-mode-line'].textContent,
    compressPressed: els['svc-tr-compress'].getAttribute('aria-pressed'),
    errorHidden: !!els['svc-tr-error'].hidden,
    errorText: els['svc-tr-error'].textContent,
    byType: els['svc-tr-by-type'].innerHTML,
    byPair: els['svc-tr-by-pair'].innerHTML,
  }));
} else {
  throw new Error('unknown mode ' + mode);
}
"""


def _run(packet: dict, *, mode: str = "book") -> dict:
    node = shutil.which("node")
    assert node, "node required"
    with tempfile.TemporaryDirectory() as td:
        harness = Path(td) / "h.js"
        harness.write_text(HARNESS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), str(SERVICE), json.dumps(packet), mode],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(proc.stdout)


BOOK = {
    "book": {
        "open": True,
        "types": {
            "mail": {"activity": 100, "live": 12},
            "todo": {"activity": 50, "live": 8},
            "doing": {"activity": 40},
            "hold": {"activity": 20, "live": 3},
            "score": {"activity": 15, "live": 15},
            "name": {"live": 9, "retired": 2},
        },
        "seats_here": 4,
        "promises_held": 3,
        "retired_names": 2,
        "activity_touched_last_hour": {"stored": True, "value": 7},
        "admin": ["wall-ui"],
        "routines": {"pack": 3, "live": 3, "missing": [], "extra": [], "watch": {}},
    }
}

TR_OK = {
    "mode": "compress",
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


def test_book_type_table_order_doing_blank_names_footnote():
    got = _run(BOOK, mode="book")
    html = got["html"]
    assert "ever written" in html
    assert "live now" in html
    # order: mail before todo before doing before hold before score before seats
    pos = [html.index(f">{name}</td>") for name in ("mail", "todo", "doing", "hold", "score", "seats")]
    assert pos == sorted(pos)
    # doing has em-dash live cell, not a count
    assert "--</td>" in html or "--</td></tr>" in html
    assert "name</td>" not in html.split("names,")[0]  # name not a table row
    assert "9 names, 2 retired" in html
    assert "touched last hour: 7" in html
    shell = got["shell"]
    assert "Transition rows: compress or capture" in shell
    assert "last 24h" in shell
    assert ">7d<" in shell or ">7d</button>" in shell
    assert "by type" in shell
    assert "by pair" in shell


def test_transitions_paint_mode_line_tables_zero_fire_wake():
    got = _run(TR_OK, mode="analysis")
    assert got["modeLine"] == "Mode: compress"
    assert got["compressOn"] is True
    assert got["captureOn"] is False
    assert got["errorHidden"] is True
    assert "10 rows / 40 events (saved 30)" in got["stats"]
    assert 'data-table="svc-tr-by-type"' in got["byType"]
    assert "80%" in got["byType"]
    assert 'data-table="svc-tr-by-pair"' in got["byPair"]
    assert "held -&gt; held" in got["byPair"]
    assert ">0<" in got["byPair"]
    assert got["wakeHidden"] is False
    assert "missed" in got["wakeBody"]
    assert "receipt_unopened" in got["wakeBody"]


def test_transitions_error_keeps_mode_and_shows_inline():
    packet = {
        "mode": "capture",
        "note": "n",
        "analysis": {
            "error": "boom <x>",
            "by_type": [],
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
            "wake": [],
        },
    }
    got = _run(packet, mode="error")
    assert got["modeLine"] == "Mode: capture"
    assert got["compressPressed"] == "false"
    assert got["errorHidden"] is False
    assert got["errorText"] == "boom <x>"
    assert "&lt; -&gt; y" in got["byPair"]
    assert "<script>" not in got["byPair"]


def test_wake_alert_row_links_book():
    wake = TR_OK["analysis"]["wake"]
    got = _run({"wake": wake}, mode="wake")
    assert got["counts"]["missed"] == 3
    assert got["counts"]["receipt_unopened"] == 1
    assert "Wake health: missed 3" in got["html"]
    assert "receipts unopened 1" in got["html"]
    assert 'data-svc-jump="book"' in got["html"]
    assert _run({"wake": []}, mode="wake")["html"] == ""
