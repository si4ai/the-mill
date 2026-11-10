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
    writeNeedMsg: api.writeNeedMsg(),
    pairToggleDisabled: /svc-tr-pair-toggle[^>]*disabled/.test(els['svc-tr-by-pair'].innerHTML),
    pairToggleCount: (els['svc-tr-by-pair'].innerHTML.match(/svc-tr-pair-toggle/g) || []).length,
    byPairHasCompressing: els['svc-tr-by-pair'].innerHTML.indexOf('compressing') >= 0,
    byPairHasCapturing: els['svc-tr-by-pair'].innerHTML.indexOf('capturing every flip') >= 0,
    byPairHasFreeHeld: els['svc-tr-by-pair'].innerHTML.indexOf('free -&gt; held') >= 0,
    pairNeed: els['svc-tr-by-pair'].innerHTML.indexOf('svc-tr-pair-need') >= 0,
    pairNeedMsg: (function () {
      const m = els['svc-tr-by-pair'].innerHTML.match(/svc-tr-pair-need-msg[^>]*>([^<]*)</);
      return m ? m[1] : '';
    })(),
    pairNeedFor: (function () {
      const m = els['svc-tr-by-pair'].innerHTML.match(/data-tr-pair-need="([^"]+)"/);
      return m ? m[1] : '';
    })(),
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
            "pairs_state": [
                {
                    "pair": "doing:connected/seated",
                    "activity_type": "doing",
                    "from_state": "connected",
                    "to_state": "seated",
                    "compress": True,
                },
                {
                    "pair": "hold:free/held",
                    "activity_type": "hold",
                    "from_state": "free",
                    "to_state": "held",
                    "compress": False,
                },
                {
                    "pair": "hold:held/held",
                    "activity_type": "hold",
                    "from_state": "held",
                    "to_state": "held",
                    "compress": True,
                },
            ],
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
    assert got["modeHint"] == "Changing this needs a write voucher (a desk vouch)."
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
    assert got["modeHint"] == "Changing this needs a write voucher (a desk vouch)."
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
    # pairs_state still paints when the window is unavailable
    assert got7["byPairWrapHidden"] is False
    assert got7["pairToggleCount"] == 3


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


def test_pairs_state_labels_and_switched_off_row():
    got = _run(BOOK, mode="paint")
    assert got["byPairWrapHidden"] is False
    assert got["byPairHasCompressing"] is True
    assert got["byPairHasCapturing"] is True  # hold:free/held is off
    assert got["byPairHasFreeHeld"] is True
    assert "compressing" in got["byPair"]
    assert "capturing every flip" in got["byPair"]
    assert 'data-tr-pair="doing:connected/seated"' in got["byPair"]
    assert 'data-tr-pair="hold:free/held"' in got["byPair"]
    assert got["pairToggleCount"] == 3
    # per-pair toggles stay enabled even when human-readonly
    assert got["pairToggleDisabled"] is False
    assert got["compressDisabled"] is True  # global mode buttons still gated
    assert got["modeHint"] == "Changing this needs a write voucher (a desk vouch)."


def test_capture_mode_overrides_pair_labels():
    pkt = {
        "book": {
            "transition": {
                "mode": "capture",
                "pairs": ["doing:connected/seated"],
                "pairs_state": [
                    {
                        "pair": "doing:connected/seated",
                        "activity_type": "doing",
                        "from_state": "connected",
                        "to_state": "seated",
                        "compress": True,
                    },
                    {
                        "pair": "hold:free/held",
                        "activity_type": "hold",
                        "from_state": "free",
                        "to_state": "held",
                        "compress": False,
                    },
                ],
                "windows": {
                    "all": {
                        "stored": True,
                        "total_rows": 1,
                        "total_events": 1,
                        "saved_rows": 0,
                        "by_type": [],
                        "by_pair": [],
                        "wake": [],
                    }
                },
            }
        }
    }
    got = _run(pkt, mode="paint")
    assert got["modeLine"] == "Mode: capture"
    assert "capturing every flip" in got["byPair"]
    assert "compressing" not in got["byPair"]
    assert got["pairToggleCount"] == 2


def test_build_pairs_string_on_off_sorted_ends():
    node = shutil.which("node")
    assert node
    state = [
        {
            "pair": "doing:connected/seated",
            "activity_type": "doing",
            "from_state": "connected",
            "to_state": "seated",
            "compress": True,
        },
        {
            "pair": "hold:free/held",
            "activity_type": "hold",
            "from_state": "free",
            "to_state": "held",
            "compress": False,
        },
        {
            "pair": "hold:held/held",
            "activity_type": "hold",
            "from_state": "held",
            "to_state": "held",
            "compress": True,
        },
    ]
    harness = HARNESS.replace(
        "if (mode === 'book') {\n  const html = api.typeTableHtml((packet.book) || {});\n  const shell = api.transitionsShellHtml();\n  process.stdout.write(JSON.stringify({ html, shell }));\n}",
        "if (mode === 'book') {\n"
        "  const state = JSON.parse(process.argv[5]);\n"
        "  const off = api.buildPairsString(state, 'doing:connected/seated', false);\n"
        "  const on = api.buildPairsString(state, 'hold:free/held', true);\n"
        "  const empty = api.buildPairsString([\n"
        "    {pair:'doing:connected/seated', compress:true}\n"
        "  ], 'doing:connected/seated', false);\n"
        "  const labelOn = api.pairStateLabel({compress:true}, 'compress');\n"
        "  const labelOff = api.pairStateLabel({compress:false}, 'compress');\n"
        "  const labelCap = api.pairStateLabel({compress:true}, 'capture');\n"
        "  process.stdout.write(JSON.stringify({\n"
        "    off, on, empty, labelOn, labelOff, labelCap, msg: api.writeNeedMsg()\n"
        "  }));\n"
        "}",
    )
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "h.js"
        h.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [node, str(h), str(SERVICE), json.dumps({"book": {}}), "book", json.dumps(state)],
            check=True,
            capture_output=True,
            text=True,
        )
    got = json.loads(proc.stdout)
    assert got["off"] == "hold:held/held"
    assert got["on"] == "doing:connected/seated,hold:free/held,hold:held/held"
    assert got["empty"] == ""
    assert got["labelOn"] == "compressing"
    assert got["labelOff"] == "capturing every flip"
    assert got["labelCap"] == "capturing every flip"
    assert got["msg"] == "Changing this needs a write voucher (a desk vouch)."


def test_write_need_message_constant():
    got = _run(BOOK, mode="paint")
    assert got["writeNeedMsg"] == "Changing this needs a write voucher (a desk vouch)."
    assert got["modeHint"] == got["writeNeedMsg"]


def _run_async_paint(packet: dict, js_body: str, *, fetch_js: str) -> dict:
    node = shutil.which("node")
    assert node
    harness = HARNESS
    harness = harness.replace(
        "global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });",
        "global.fetch = " + fetch_js + ";",
    )
    old = "if (mode === 'paint') {\n  api.paintFromPacket();\n  process.stdout.write(JSON.stringify(snap()));\n}"
    new = "if (mode === 'paint') {\n" + js_body + "\n}"
    if old not in harness:
        raise AssertionError("paint branch missing")
    harness = harness.replace(old, new, 1)
    wrapped = (
        "async function main() {\n"
        + harness
        + "\n}\nmain().catch((e) => { console.error(e); process.exit(1); });\n"
    )
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "h.js"
        h.write_text(wrapped, encoding="utf-8")
        proc = subprocess.run(
            [node, str(h), str(SERVICE), json.dumps(packet), "paint"],
            check=False,
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout or "node failed")
    return json.loads(proc.stdout)


def test_flip_pair_refuses_without_admin_reverts():
    body = """
  api.paintFromPacket();
  const beforeState = JSON.stringify((_svcPacket.book.transition.pairs_state || []));
  let threw = false;
  try { await api.flipPair('doing:connected/seated', false); }
  catch (e) { threw = true; }
  const after = snap();
  after.threw = threw;
  after.afterState = JSON.stringify((_svcPacket.book.transition.pairs_state || []));
  after.beforeState = beforeState;
  process.stdout.write(JSON.stringify(after));
"""
    got = _run_async_paint(
        BOOK,
        body,
        fetch_js="async () => ({ ok: false, status: 403, json: async () => ({ error: 'admin required' }) })",
    )
    assert got["threw"] is True
    assert got["errorHidden"] is True
    assert got["errorText"] == ""
    assert got["pairNeed"] is True
    assert got["pairNeedFor"] == "doing:connected/seated"
    assert got["pairNeedMsg"] == "Changing this needs a write voucher (a desk vouch)."
    assert "svc-tr-pair-need" in got["byPair"]
    assert got["beforeState"] == got["afterState"]
    assert 'data-tr-compress="1"' in got["byPair"]


def test_flip_pair_success_repaints_from_response():
    resp = {
        "mode": "compress",
        "pairs": ["hold:held/held"],
        "pairs_raw": "hold:held/held",
        "default_pairs": "doing:seated/connected,hold:free/held,hold:held/held",
        "note": "ok",
    }
    body = """
  api.paintFromPacket();
  await api.flipPair('doing:connected/seated', false);
  const after = snap();
  after.state = _svcPacket.book.transition.pairs_state;
  after.pairs = _svcPacket.book.transition.pairs;
  process.stdout.write(JSON.stringify(after));
"""
    got = _run_async_paint(
        BOOK,
        body,
        fetch_js="async () => ({ ok: true, status: 200, json: async () => (" + json.dumps(resp) + ") })",
    )
    assert got["errorHidden"] is True
    assert got["pairNeed"] is False
    assert got["pairNeedMsg"] == ""
    pairs = {e["pair"]: e["compress"] for e in got["state"]}
    assert pairs["doing:connected/seated"] is False
    assert pairs["hold:held/held"] is True
    assert pairs["hold:free/held"] is False
    assert "hold:held/held" in got["pairs"]
    assert "doing:connected/seated" not in got["pairs"]
    assert got["byPairHasFreeHeld"] is True
    assert 'data-tr-pair="doing:connected/seated"' in got["byPair"]
    assert 'data-tr-compress="0"' in got["byPair"]


def test_pair_need_clears_on_window_switch():
    """Inline refusal under a pair clears when the window buttons repaint."""
    body = """
  api.paintFromPacket();
  let threw = false;
  try { await api.flipPair('doing:connected/seated', false); }
  catch (e) { threw = true; }
  const mid = snap();
  api.setSinceUi('24h');
  api.clearPairNeed();
  api.paintFromPacket();
  const after = snap();
  after.threw = threw;
  after.midNeed = mid.pairNeed;
  after.midFor = mid.pairNeedFor;
  process.stdout.write(JSON.stringify(after));
"""
    got = _run_async_paint(
        BOOK,
        body,
        fetch_js="async () => ({ ok: false, status: 403, json: async () => ({ error: 'admin required' }) })",
    )
    assert got["threw"] is True
    assert got["midNeed"] is True
    assert got["midFor"] == "doing:connected/seated"
    assert got["pairNeed"] is False
    assert got["pairNeedMsg"] == ""
    assert got["since"] == "24h"


def test_pair_need_clears_on_success_after_refuse():
    """A later successful flip clears the inline refusal under the row."""
    body = """
  api.paintFromPacket();
  let firstThrew = false;
  try { await api.flipPair('doing:connected/seated', false); }
  catch (e) { firstThrew = true; }
  const mid = snap();
  await api.flipPair('hold:free/held', true);
  const after = snap();
  after.firstThrew = firstThrew;
  after.midNeed = mid.pairNeed;
  after.midFor = mid.pairNeedFor;
  process.stdout.write(JSON.stringify(after));
"""
    resp = {
        "mode": "compress",
        "pairs": ["doing:connected/seated", "hold:free/held", "hold:held/held"],
        "pairs_raw": "doing:connected/seated,hold:free/held,hold:held/held",
        "default_pairs": "doing:seated/connected,hold:free/held,hold:held/held",
        "note": "ok",
    }
    fetch_js = (
        "(function () {"
        "  let n = 0;"
        "  return async () => {"
        "    n += 1;"
        "    if (n === 1) return { ok: false, status: 403, json: async () => ({ error: 'admin required' }) };"
        "    return { ok: true, status: 200, json: async () => ("
        + json.dumps(resp)
        + ") };"
        "  };"
        "})()"
    )
    got = _run_async_paint(BOOK, body, fetch_js=fetch_js)
    assert got["firstThrew"] is True
    assert got["midNeed"] is True
    assert got["midFor"] == "doing:connected/seated"
    assert got["pairNeed"] is False
    assert got["pairNeedMsg"] == ""
    assert got["errorHidden"] is True
