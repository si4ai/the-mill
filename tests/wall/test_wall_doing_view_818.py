# -*- coding: utf-8 -*-
"""#818 PR C: the Wall shows the server's doing view and computes nothing.

The view is GET /api/v1/doing (the `mill connected` desk views) and the trails are
GET /api/v1/doing/history (entries with ended_by). doing_818_fixture.json copies those
shapes. boot.js's doing helpers and doing/doing-paint.js run in Node against it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
BOOT = ROOT / "default" / "boot.js"
DOING = ROOT / "default" / "doing" / "doing-paint.js"
FIXTURE = Path(__file__).with_name("doing_818_fixture.json")
WALL_JS = sorted((ROOT / "default").rglob("*.js")) + sorted((ROOT / "lib").glob("*.js"))

_HARNESS = r"""
const fs = require('fs');
const [bootFile, doingFile, fxFile] = process.argv.slice(2);
const fx = JSON.parse(fs.readFileSync(fxFile, 'utf8'));
const calls = [];
let reply = null;
const els = [];
global.window = global;
global.document = {
  _wallDoingWired: false,
  addEventListener() {},
  querySelectorAll(sel) { return sel === '[data-doing-trail]' ? els : []; },
  querySelector() { return null; },
};
global.fetch = (url) => { calls.push(url); return Promise.resolve(reply(url)); };
const res = (status, body) => ({ status, ok: status >= 200 && status < 300, json: () => Promise.resolve(body) });
global.esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.t = v => (v ? String(v) : '-');
global.dt = v => (v ? String(v).replace('T', ' ').slice(0, 19) : '-');
global.millName = (k, v) => String(v || '');
global.millGid = r => (r && r.roster_id) || '';
global.millJobsForOwner = () => [];
global.wallLazyCall = () => Promise.resolve();
global.board = () => { calls.push('repaint'); };
const src = fs.readFileSync(bootFile, 'utf8');
const body = src.slice(src.indexOf('function wallDoingView('), src.indexOf('function sgChip('));
(0, eval)(body);
const bootRow = wallDoingRow, bootBlock = wallDoingBlock;
const out = {};
(async () => {
  window.WALL_DOING = { state: 'unknown', byOwner: null, at: 0, sig: '', inflight: null, trails: {}, historyAbsentAt: 0 };
  const seat = { owner: 'builder', doing: 'blocked on validator', alive: true, heartbeat: '' };
  out.seatRow = bootRow('builder', 'blocked on validator');
  out.seatGlance = hereGlance({ events: [] }, seat).state;
  (0, eval)(fs.readFileSync(doingFile, 'utf8'));
  reply = () => res(404, { error: 'not found' });
  await wallDoingSync();
  await wallDoingSync();
  out.absent = { state: window.WALL_DOING.state, by: window.WALL_DOING.byOwner, fetches: calls.filter(c => c !== 'repaint').length };
  out.absentRow = wallDoingRow('builder', 'blocked on validator');
  out.absentMeta = wallDoingMeta('builder');
  out.absentGlance = hereGlance({ events: [] }, seat).state;
  els.push({ getAttribute: () => 'todo-2', innerHTML: '' });
  await wallDoingTrail();
  out.trailSkipped = { html: wallDoingTrailHtml('todo-2'), fetches: calls.filter(c => c !== 'repaint').length };
  window.WALL_DOING.state = 'ok';
  await wallDoingTrail();
  out.trailAbsent = { html: wallDoingTrailHtml('todo-2'), at: !!window.WALL_DOING.historyAbsentAt };
  window.WALL_DOING.state = 'absent';
  calls.length = 0;
  window.WALL_DOING = { state: 'unknown', byOwner: null, at: 0, sig: '', inflight: null, trails: {}, historyAbsentAt: 0 };
  window._floor = {};
  reply = (url) => {
    if (url.indexOf('/api/v1/doing/history') === 0) {
      const q = new URLSearchParams(url.split('?')[1] || '');
      const rows = fx.history.filter(e => (!q.get('on') || e.on === q.get('on')) && (!q.get('desk') || e.desk === q.get('desk')))
        .sort((a, b) => b.at.localeCompare(a.at));
      return res(200, { history: rows, page: { n: 1, of: 1, size: 50, entries: rows.length }, mill: 'test' });
    }
    /* The server wraps a bare list as {result, mill} (mill_json.stamp_mill). */
    return res(200, { result: fx.doing, mill: 'test' });
  };
  await wallDoingSync();
  out.urls = calls.slice();
  out.ok = window.WALL_DOING.state;
  out.glance = Object.fromEntries(fx.doing.map(v => [v.owner, hereGlance({ events: [] }, { owner: v.owner, doing: 'seat text', alive: true }).state]));
  out.row = Object.fromEntries(fx.doing.map(v => [v.owner, wallDoingRow(v.owner, 'seat text')]));
  out.meta = Object.fromEntries(fx.doing.map(v => [v.owner, wallDoingMeta(v.owner)]));
  out.desk = wallDoingBlock('gardener', 'seat text');
  await wallDoingTrail('todo-2');
  out.trail = wallDoingTrailHtml('todo-2');
  out.claimedBlank = wallClaimedSlot({});
  out.claimed = wallClaimedSlot({ claimed_at: '2026-10-23 02:00:00' });
  out.waitN = wallDoingWaitN(window.WALL_DOING.byOwner.builder);
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is not on PATH, so the doing view cannot run.")
    with tempfile.TemporaryDirectory() as folder:
        js = Path(folder) / "harness.js"
        js.write_text(_HARNESS, encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [node, str(js), str(BOOT), str(DOING), str(FIXTURE)],
            capture_output=True, text=True, encoding="utf-8",
        )
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "node failed")[-2000:])
    return json.loads(proc.stdout)


def test_route_missing_keeps_the_seat_text_and_guesses_nothing():
    got = _run()
    assert got["seatRow"] == '<span class="here-doing">blocked on validator</span>'
    # "blocked on ..." in a desk's text is not a state: no parsing of the text.
    assert got["seatGlance"] == "working"
    assert got["absent"] == {"state": "absent", "by": None, "fetches": 1}
    assert got["absentRow"] == got["seatRow"]
    assert got["absentMeta"] == ""
    assert got["absentGlance"] == "working"
    # No view: the history route is not probed as well (one 404, not two).
    assert got["trailSkipped"] == {"html": "", "fetches": 1}
    assert got["trailAbsent"] == {"html": "", "at": True}


def test_strip_shows_the_view_text_link_age_ended_by_and_pill():
    got = _run()
    assert got["ok"] == "ok"
    assert got["urls"][0] == "/api/v1/doing?all=1"
    assert got["glance"] == {"builder": "working", "wall-ui": "working", "validator": "working", "gardener": "idle", "grok-tui": "idle"}
    assert ">landing the doing routes<" in got["row"]["builder"]
    assert "seat text" not in "".join(got["row"].values())
    b = got["meta"]["builder"]
    assert 'data-doing-go="todo-1"' in b and 'href="#jobs"' in b
    assert ">42m<" in b
    assert ">5 waiting<" in b
    # The popover lists the newest 3 letters the server sent, in its order, and the card.
    assert [m for m in re.findall(r'data-doing-go="(mail-\d+)"', b)] == ["mail-29", "mail-26", "mail-21"]
    assert 'data-doing-go="todo-2"' in b
    assert got["waitN"] == 5
    assert ">0 waiting<" in got["meta"]["validator"]
    assert 'data-doing-go="mail-1"' in got["meta"]["validator"] and 'href="#mail"' in got["meta"]["validator"]
    g = got["meta"]["gardener"]
    assert 'data-ended-by="finished"' in g and "ended: finished" in g and 'data-doing-go="todo-3"' in g
    assert "idle 14m" in got["row"]["gardener"] and "last: skill.md doing bullet" in got["row"]["gardener"]
    assert 'data-ended-by="cleared"' in got["meta"]["grok-tui"]
    assert "ended: finished" in got["desk"]


def test_waiting_on_and_claimed_slots_are_blank_until_the_server_sends_them():
    got = _run()
    assert got["meta"]["builder"].count('<span class="doing-asked" data-slot="asked"></span>') == 3
    assert got["claimedBlank"] == '<span class="card-claimed" data-slot="claimed_at"></span>'
    assert got["claimed"] == '<span class="card-claimed" data-slot="claimed_at">claimed 10-23 02:00</span>'


def test_card_trail_lists_doing_rows_in_order_with_ended_by():
    got = _run()
    rows = re.findall(r'<span class="dt-text">([^<]*)</span>.*?data-ended-by="([^"]*)">([^<]*)<', got["trail"])
    assert rows == [
        ("stage 1 read of the strip brief", "cleared", "cleared"),
        ("route gap write-up", "finished", "finished"),
        ("routes sketch for PR C", "newer", "newer"),
        ("PR C doing glass", "", "current"),
    ]


def test_the_wall_never_splits_guesses_or_reads_card_doing():
    for path in WALL_JS:
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for gone in ("wallDoingSplit", "wallDoingFace", "parseWaitingOn", "doing_trunc", "doingOlder"):
            assert gone not in src, f"{rel}: {gone}"
        # A card (todo row or tree node) has no doing (#818); only a desk does.
        assert not re.search(r"\b(card|node|parent|rowFace)\.doing\b", src), rel
        assert not re.search(r"\.doing\s*\|\|\s*\w+\.(detail|need_id|title)\b", src), rel


def test_display_kind_is_doing_not_join_or_here():
    html = (ROOT / "default" / "board.html").read_text(encoding="utf-8")
    assert 'data-wire-type="doing"' in html and 'data-wire-type="here"' not in html
    for css in (ROOT / "default").rglob("*.css"):
        src = css.read_text(encoding="utf-8")
        assert "ty-join" not in src and "kind-here" not in src, css.name
    boot = BOOT.read_text(encoding="utf-8")
    assert '"here", "hold"' not in boot and '"doing", "hold", "score"' in boot
    assert 'kind === "doing" ? " muted" : ""' in boot


def test_doing_reads_are_get_only():
    src = DOING.read_text(encoding="utf-8")
    assert "method" not in src
    assert re.findall(r'"/api/v1/doing[^"]*"', src) == ['"/api/v1/doing?all=1"', '"/api/v1/doing/history"']
