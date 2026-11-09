# -*- coding: utf-8 -*-
"""card 1098: Book tab type table, transitions from glance packet, wake-health alert row."""
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
  'svc-tr-by-pair','svc-tr-wake','svc-tr-wake-body','svc-tr-note',
  'svc-tr-mode-line','svc-tr-mode-wrap','svc-tr-mode-hint',
  'svc-tr-by-type-wrap','svc-tr-by-pair-wrap',
  'svc-tr-since-all','svc-tr-since-24h','svc-tr-since-7d',
  'svc-tr-refresh','svc-tr-block','svc-wake-alert','wall-service-body'
].forEach(id => el(id));
['svc-tr-mode-line','svc-tr-by-type-wrap','svc-tr-by-pair-wrap',
 'svc-tr-stats','svc-tr-note','svc-tr-wake','svc-tr-mode-hint','svc-tr-error'].forEach(id => { els[id].hidden = true; });

global.document = {
  getElementById(id) { return el(id); },
  querySelectorAll() { return []; }
};
global.window = global;
global.localStorage = { getItem() { return null; }, setItem() {} };
global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
global.esc = esc;
global.wallHumanReadonly = () => true;
global._svcPacket = packet;
global._svcSection = mode === 'alerts' ? 'alerts' : 'book';
global.glanceMarkSection = function () {};

(0, eval)(src);
const api = global.WallServiceBook;
if (!api) throw new Error('no WallServiceBook');

function snap() {
  return {
    modeLine: els['svc-tr-mode-line'].textContent,
    modeLineHidden: !!els['svc-tr-mode-line'].hidden,
    modeWrapHidden: !!els['svc-tr-mode-wrap'].hidden,
    modeHint: els['svc-tr-mode-hint'].textContent,
    modeHintHidden: !!els['svc-tr-mode-hint'].hidden,
    compressDisabled: !!els['svc-tr-compress'].disabled,
    captureDisabled: !!els['svc-tr-capture'].disabled,
    compressOn: els['svc-tr-compress'].classList.contains('on'),
    captureOn: els['svc-tr-capture'].classList.contains('on'),
    errorHidden: !!els['svc-tr-error'].hidden,
    errorText: els['svc-tr-error'].textContent,
    stats: els['svc-tr-stats'].textContent,
    statsHidden: !!els['svc-tr-stats'].hidden,
    byType: els['svc-tr-by-type'].innerHTML,
    byPair: els['svc-tr-by-pair'].innerHTML,
    byTypeWrapHidden: !!els['svc-tr-by-type-wrap'].hidden,
    byPairWrapHidden: !!els['svc-tr-by-pair-wrap'].hidden,
    wakeHidden: !!els['svc-tr-wake'].hidden,
    wakeBody: els['svc-tr-wake-body'].innerHTML,
    since: api.getSince(),
  };
}

if (mode === 'book') {
  const html = api.typeTableHtml((packet.book) || {});
  const shell = api.transitionsShellHtml();
  process.stdout.write(JSON.stringify({ html, shell }));
} else if (mode === 'paint') {
  api.paintFromPacket();
  process.stdout.write(JSON.stringify(snap()));
} else if (mode === 'wake') {
  const html = api.wakeAlertHtml(packet.wake || []);
  const counts = api.wakeCounts(packet.wake || []);
  process.stdout.write(JSON.stringify({ html, counts }));
} else if (mode === 'wake-packet') {
  api.paintWakeAlert();
  process.stdout.write(JSON.stringify({
    hidden: !!els['svc-wake-alert'].hidden,
    html: els['svc-wake-alert'].innerHTML,
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


WIN_OK = {
    "stored": True,
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
    "top_compressed": [],
    "wake": [
        {"label": "queued", "value": 10},
        {"label": "sent", "value": 4},
        {"label": "missed", "value": 3},
        {"label": "done", "value": 5},
        {"label": "auto_done", "value": 2},
        {"label": "receipt_unopened", "value": 1},
        {"label": "receipt_opened", "value": 2},
    ],
}

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
        "transition": {
            "mode": "compress",
            "pairs": ["doing:connected/seated", "hold:held/held"],
            "windows": {
                "all": WIN_OK,
                "24h": {**WIN_OK, "total_rows": 3, "total_events": 9, "saved_rows": 6, "since": "24h"},
                "7d": {"stored": False},
            },
        },
    }
}


def test_book_type_table_order_doing_blank_names_footnote():
    got = _run(BOOK, mode="book")
    html = got["html"]
    assert "ever written" in html
    assert "live now" in html
    pos = [html.index(f">{name}</td>") for name in ("mail", "todo", "doing", "hold", "score", "seats")]
    assert pos == sorted(pos)
    assert "--</td>" in html or "--</td></tr>" in html
    assert "name</td>" not in html.split("names,")[0]
    assert "9 names, 2 retired" in html
    assert "touched last hour: 7" in html
    shell = got["shell"]
    assert "Transition rows: compress or capture" in shell
    assert "last 24h" in shell
    assert ">7d<" in shell or ">7d</button>" in shell
    assert "by type" in shell
    assert "by pair" in shell
    assert "svc-tr-mode-wrap" in shell
    assert "Mode: (unknown)" not in shell
    assert "Mode: ..." not in shell
    assert "admin session needed" not in shell
    assert "loading transition analysis" not in shell


def test_paint_from_packet_shows_mode_tables_and_write_gate():
    got = _run(BOOK, mode="paint")
    assert got["modeLine"] == "Mode: compress"
    assert got["modeLineHidden"] is False
    assert got["modeWrapHidden"] is False
    assert got["compressOn"] is True
    assert got["captureOn"] is False
    assert got["compressDisabled"] is True
    assert got["captureDisabled"] is True
    assert got["modeHintHidden"] is False
    assert got["modeHint"] == "sign in as Admin to change"
    assert "10 rows / 40 events (saved 30)" in got["stats"]
    assert got["statsHidden"] is False
    assert got["byTypeWrapHidden"] is False
    assert got["byPairWrapHidden"] is False
    assert 'data-table="svc-tr-by-type"' in got["byType"]
    assert "80%" in got["byType"]
    assert 'data-table="svc-tr-by-pair"' in got["byPair"]
    assert "held -&gt; held" in got["byPair"]
    assert got["wakeHidden"] is False
    assert "missed" in got["wakeBody"]
    assert "receipt_unopened" in got["wakeBody"]
    assert got["errorHidden"] is True
    assert "admin session needed" not in got["errorText"]
    assert "unknown" not in got["modeLine"].lower()


def test_stored_false_window_shows_unavailable_not_zeros():
    pkt = {
        "book": {
            "transition": {
                "mode": "capture",
                "pairs": [],
                "windows": {"all": {"stored": False}, "24h": {"stored": False}, "7d": {"stored": False}},
            }
        }
    }
    got = _run(pkt, mode="paint")
    assert got["modeLine"] == "Mode: capture"
    assert got["modeLineHidden"] is False
    assert got["modeWrapHidden"] is False
    assert got["stats"] == "window unavailable"
    assert got["statsHidden"] is False
    assert got["byTypeWrapHidden"] is True
    assert got["byPairWrapHidden"] is True
    assert got["byType"] == ""
    assert got["byPair"] == ""
    assert "0 rows" not in got["stats"]
    assert got["wakeHidden"] is True


def test_missing_transition_hides_unknown_mode_keeps_buttons():
    pkt = {"book": {"types": {"mail": {"activity": 1, "live": 1}}}}
    got = _run(pkt, mode="paint")
    assert got["modeLineHidden"] is True
    assert "unknown" not in got["modeLine"].lower()
    assert "Mode:" not in got["modeLine"]
    assert got["modeWrapHidden"] is False
    assert got["compressDisabled"] is True
    assert got["modeHint"] == "sign in as Admin to change"
    assert got["stats"] == "window unavailable"
    assert got["byTypeWrapHidden"] is True
    assert got["byPairWrapHidden"] is True


def test_window_selector_reads_packet_not_admin():
    got = _run(BOOK, mode="paint")
    assert got["since"] == ""
    # switch via API
    node = shutil.which("node")
    harness = HARNESS + r"""
; api.setSinceUi('24h'); api.paintFromPacket();
process.stdout.write('\n' + JSON.stringify(snap()));
"""
    # simpler: use a dedicated packet paint after setSince through a second mode
    # Re-run with since already set by injecting into harness via packet flag
    # Use paint then call setSince in a custom one-off:
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "h.js"
        h.write_text(
            HARNESS.replace(
                "if (mode === 'paint') {\n  api.paintFromPacket();\n  process.stdout.write(JSON.stringify(snap()));\n}",
                "if (mode === 'paint') {\n  api.paintFromPacket();\n  api.setSinceUi('24h');\n  api.paintFromPacket();\n  process.stdout.write(JSON.stringify(snap()));\n}",
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [node, str(h), str(SERVICE), json.dumps(BOOK), "paint"],
            check=True,
            capture_output=True,
            text=True,
        )
    got24 = json.loads(proc.stdout)
    assert got24["since"] == "24h"
    assert "3 rows / 9 events (saved 6)" in got24["stats"]
    assert got24["byTypeWrapHidden"] is False

    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "h.js"
        h.write_text(
            HARNESS.replace(
                "if (mode === 'paint') {\n  api.paintFromPacket();\n  process.stdout.write(JSON.stringify(snap()));\n}",
                "if (mode === 'paint') {\n  api.paintFromPacket();\n  api.setSinceUi('7d');\n  api.paintFromPacket();\n  process.stdout.write(JSON.stringify(snap()));\n}",
            ),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [node, str(h), str(SERVICE), json.dumps(BOOK), "paint"],
            check=True,
            capture_output=True,
            text=True,
        )
    got7 = json.loads(proc.stdout)
    assert got7["since"] == "7d"
    assert got7["stats"] == "window unavailable"
    assert got7["byTypeWrapHidden"] is True
    assert got7["byPairWrapHidden"] is True


def test_wake_alert_row_links_book():
    wake = WIN_OK["wake"]
    got = _run({"wake": wake}, mode="wake")
    assert got["counts"]["missed"] == 3
    assert got["counts"]["receipt_unopened"] == 1
    assert "Wake health: missed 3" in got["html"]
    assert "receipts unopened 1" in got["html"]
    assert 'data-svc-jump="book"' in got["html"]
    assert _run({"wake": []}, mode="wake")["html"] == ""


def test_wake_alert_from_packet_all_window():
    got = _run(BOOK, mode="wake-packet")
    assert got["hidden"] is False
    assert "Wake health: missed 3" in got["html"]
    assert 'data-svc-jump="book"' in got["html"]
    empty = _run({"book": {"transition": {"mode": "compress", "pairs": [], "windows": {"all": {"stored": False}}}}}, mode="wake-packet")
    assert empty["hidden"] is True
    assert empty["html"] == ""


def test_touched_last_hour_absent_when_missing_or_not_stored():
    base = {
        "book": {
            "open": True,
            "types": {"mail": {"activity": 1, "live": 1}},
            "seats_here": 2,
        }
    }
    html = _run(base, mode="book")["html"]
    assert "touched last hour" not in html

    stored_false = {
        "book": {
            "open": True,
            "types": {"mail": {"activity": 1, "live": 1}},
            "activity_touched_last_hour": {"stored": False, "value": None},
        }
    }
    html2 = _run(stored_false, mode="book")["html"]
    assert "touched last hour" not in html2
    assert "not written" not in html2


def test_touched_last_hour_renders_number_object_or_plain():
    as_obj = {
        "book": {
            "open": True,
            "types": {"mail": {"activity": 1, "live": 1}},
            "activity_touched_last_hour": {"stored": True, "value": 7},
        }
    }
    assert "touched last hour: 7" in _run(as_obj, mode="book")["html"]
    as_num = {
        "book": {
            "open": True,
            "types": {"mail": {"activity": 1, "live": 1}},
            "activity_touched_last_hour": 12,
        }
    }
    assert "touched last hour: 12" in _run(as_num, mode="book")["html"]
