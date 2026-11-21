# -*- coding: utf-8 -*-
"""Card 1240: the Wall paints the tw-run tree from the display contract (letter 6456).

Server side is card 1239. The live desk list (GET /api/v1/doing?all=1) gives each row a
watch_id and a parent_watch_id; the Wall nests a child under its parent when the parent
is live on the same desk, and keeps a child whose parent ended at the top, marked
"child of PARENT". A row's runs button reads GET /api/v1/doing?run=WATCH_ID&desk=DESK
({n, runs}: the asked run first, then its descendants) and nests those runs, each with
state, start, end and how, exit_code and its forwarded mill calls (verb, ok, err).
An older server (no watch_id on the rows, or a desk list back for run=, or a 404) keeps
today's flat list and gets no invented tree.

doing_run_tree_1240_fixture.json holds the contract shapes. boot.js's doing helpers,
score.js (the row cleaner) and doing/doing-paint.js run in Node against it.
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
SCORE = ROOT / "default" / "score" / "score.js"
DATA = ROOT / "lib" / "data.js"
CSS = ROOT / "default" / "doing" / "doing.css"
FIXTURE = Path(__file__).with_name("doing_run_tree_1240_fixture.json")

_HARNESS = r"""
const fs = require('fs');
const [bootFile, doingFile, scoreFile, dataFile, fxFile] = process.argv.slice(2);
const fx = JSON.parse(fs.readFileSync(fxFile, 'utf8'));
const calls = [];
let mode = 'new';
const slots = [];
const buttons = [];
let clicker = null;
global.window = global;
global.document = {
  _wallDoingWired: false,
  addEventListener(kind, fn) { if (kind === 'click') clicker = fn; },
  querySelectorAll(sel) {
    if (sel === '[data-doing-run-tree]') return slots;
    if (sel === 'button[data-doing-run]') return buttons;
    return [];
  },
  querySelector() { return null; },
};
const res = (status, body) => ({ status, ok: status >= 200 && status < 300, json: () => Promise.resolve(body) });
global.fetch = (url) => {
  calls.push(url);
  const q = new URLSearchParams(url.split('?')[1] || '');
  if (q.get('run')) {
    if (mode === '404') return Promise.resolve(res(404, { error: 'not found' }));
    if (mode === 'old') return Promise.resolve(res(200, { result: fx.doing, mill: 'test' }));
    if (mode === 'served') return Promise.resolve(res(200, fx.served.run));
    const tree = fx.runs[q.get('run')];
    if (!tree || q.get('desk') !== 'builder') return Promise.resolve(res(400, { error: 'connected --run: no tw run ' + q.get('run') + ' for desk ' + q.get('desk') }));
    return Promise.resolve(res(200, Object.assign({ mill: 'test', later_field: 1 }, tree)));
  }
  if (mode === 'served') return Promise.resolve(res(200, { result: [fx.served.doing], mill: '0.8.15' }));
  return Promise.resolve(res(200, { result: fx.doing, mill: 'test' }));
};
global.esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.t = v => (v ? String(v) : '-');
global.dt = v => (v ? String(v).replace('T', ' ').slice(0, 19) : '-');
global.millName = (k, v) => String(v || '');
global.millGid = r => (r && r.roster_id) || '';
global.millJobsForOwner = () => [];
global.wallLazyCall = () => Promise.resolve();
global.board = () => {};
(0, eval)(fs.readFileSync(dataFile, 'utf8'));
(0, eval)(fs.readFileSync(scoreFile, 'utf8'));
const src = fs.readFileSync(bootFile, 'utf8');
(0, eval)(src.slice(src.indexOf('function wallDoingView('), src.indexOf('function sgChip(')));
window.WALL_DOING = { state: 'unknown', byOwner: null, at: 0, sig: '', inflight: null, trails: {}, historyAbsentAt: 0 };
(0, eval)(fs.readFileSync(doingFile, 'utf8'));
const slot = (key) => { const el = { getAttribute: () => key, innerHTML: '' }; slots.push(el); return el; };
const out = {};
(async () => {
  window._floor = {};
  await wallDoingSync(true);
  out.builder = wallDoingBlock('builder');
  out.validator = wallDoingBlock('validator');
  /* The runs button: a click opens the tree, a second closes it. */
  const btn = { attrs: { 'data-doing-run': 'tw-aaa', 'data-doing-desk': 'builder' }, textContent: 'runs',
    getAttribute(k) { return this.attrs[k]; }, setAttribute(k, v) { this.attrs[k] = v; } };
  buttons.push(btn);
  const el = slot('builder|tw-aaa');
  let stopped = 0;
  clicker({ target: { closest: (sel) => (sel === 'button[data-doing-run]' ? btn : null) }, preventDefault() {}, stopPropagation() { stopped++; } });
  out.loading = el.innerHTML;
  await window.WALL_DOING.runs['builder|tw-aaa'].inflight;
  out.tree = el.innerHTML;
  out.btnOpen = { expanded: btn.attrs['aria-expanded'], text: btn.textContent, stopped };
  out.runUrl = calls.filter(u => u.indexOf('run=') >= 0);
  out.builderOpen = wallDoingBlock('builder');
  await wallDoingRunToggle('builder', 'tw-aaa');
  out.closed = { html: el.innerHTML, expanded: btn.attrs['aria-expanded'], text: btn.textContent };
  const one = async (desk, watch) => {
    const e = slot(desk + '|' + watch);
    await wallDoingRunToggle(desk, watch);
    return e.innerHTML;
  };
  out.lone = await one('builder', 'tw-eee');
  out.endedParent = await one('builder', 'tw-zzz');
  out.childAsked = await one('builder', 'tw-ddd');
  out.orphan = await one('builder', 'tw-orph');
  out.unknown = await one('builder', 'tw-nope');
  mode = '404';
  out.absent404 = await one('builder', 'tw-x404');
  mode = 'old';
  out.oldServer = await one('builder', 'tw-xold');
  /* Refresh: an open tree reads again once its TTL is past, a closed one never does. */
  mode = 'new';
  const before = calls.length;
  window.WALL_DOING.runs['builder|tw-eee'].at = 0;
  window.WALL_DOING.runs['builder|tw-aaa'].at = 0;
  await wallDoingRunRefresh();
  out.refreshed = calls.slice(before);
  /* The shapes the card 1239 server sent on the dev box. */
  mode = 'served';
  await wallDoingSync(true);
  out.served = wallDoingBlock('grok-tui');
  out.servedTree = await one('grok-tui', 'tw-535d9c73e8eb49d2');
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is not on PATH, so the run tree cannot run.")
    with tempfile.TemporaryDirectory() as folder:
        js = Path(folder) / "harness.js"
        js.write_text(_HARNESS, encoding="utf-8", newline="\n")
        proc = subprocess.run(
            [node, str(js), str(BOOT), str(DOING), str(SCORE), str(DATA), str(FIXTURE)],
            capture_output=True, text=True, encoding="utf-8",
        )
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "node failed")[-2000:])
    return json.loads(proc.stdout)


def _outline(html: str) -> list[tuple[int, str]]:
    """(depth, watch_id) for each live row, depth from the doing-run-kids nesting."""
    rows = []
    level = 0
    stack = []
    for m in re.finditer(r'<div class="doing-run(?:-kids)?"[^>]*>|<div class="doing-run-tree"[^>]*>|</div>|<span class="doing-task-row"[^>]*data-watch="([^"]+)"', html):
        tok = m.group(0)
        if tok.startswith("<div"):
            kind = "kids" if 'doing-run-kids' in tok else "other"
            stack.append(kind)
            level += kind == "kids"
        elif tok == "</div>":
            if stack:
                level -= stack.pop() == "kids"
        else:
            rows.append((level, m.group(1)))
    return rows


def test_live_list_nests_by_watch_id_and_parent_watch_id():
    got = _run()
    # tw-aaa (live) holds tw-bbb, which holds tw-ccc; tw-ddd's parent tw-zzz has ended, so it
    # stays at the top marked child of tw-zzz; tw-eee is a lone root. Tops stay newest first.
    assert _outline(got["builder"]) == [(0, "tw-eee"), (0, "tw-ddd"), (0, "tw-aaa"), (1, "tw-bbb"), (2, "tw-ccc")]
    assert got["builder"].count("child of ") == 1
    assert '<span class="dt-child-of" title="its parent run is not live">child of tw-zzz</span>' in got["builder"]
    # every live row with a watch_id gets a runs button for its desk, closed until clicked
    assert len(re.findall(r'<button type="button" class="dt-tree" data-doing-run="tw-\w+" data-doing-desk="builder" aria-expanded="false"', got["builder"])) == 5
    # the child still running shows its own state
    assert re.search(r'data-state="waiting" data-id="102" data-watch="tw-bbb"', got["builder"])


def test_old_server_rows_stay_flat_with_no_tree():
    got = _run()
    v = got["validator"]
    assert re.findall(r'class="doing-task-row" data-state="(\w+)" data-id="(\d+)">', v) == [("started", "201")]
    for gone in ("data-watch", "doing-run", "dt-tree", "child of", "data-doing-run"):
        assert gone not in v, gone


def test_run_detail_nests_runs_with_their_calls():
    got = _run()
    assert got["loading"] == '<span class="dt-none">Loading run tree.</span>'
    assert got["runUrl"][0] == "/api/v1/doing?run=tw-aaa&desk=builder"
    assert got["btnOpen"] == {"expanded": "true", "text": "hide runs", "stopped": 1}
    tree = got["tree"]
    assert '<span class="dt-head">Run tree: 3 runs</span>' in tree
    # the asked run is the root; tw-bbb under it; tw-ccc under tw-bbb
    order = re.findall(r'<div class="rt-run" data-watch="([^"]+)"|(<div class="doing-run-kids">)|(</div>)', tree)
    depth, seen = 0, []
    for watch, kids, close in order:
        if kids:
            depth += 1
        elif watch:
            seen.append((depth, watch))
    assert seen == [(0, "tw-aaa"), (1, "tw-bbb"), (2, "tw-ccc")]
    # forwarded calls: verb and ok, or the err word when not ok; newest 200 means older are counted
    assert '<span class="rt-verb">inbox</span> <span class="rt-ok">ok</span>' in tree
    assert '<span class="rt-call" data-ok="false"><span class="dt-at" title="2026-11-20T09:00:06Z">09:00:06</span> <span class="rt-verb">todo</span> <span class="rt-ok">refused</span>' in tree
    assert '<span class="dt-more">248 older not shown</span>' in tree
    assert '<span class="rt-counts">250 calls, 248 ok, 2 failed</span>' in tree
    # a live run says live, with no end and no exit code
    assert 'data-ended-by="">live</span>' in tree and "exit " not in tree
    # a run with no calls says so
    assert tree.count("No mill calls on this run.") == 1
    # repaints keep the open tree in place
    assert '<div class="doing-run-tree" data-doing-run-tree="builder|tw-aaa"><span class="dt-head">Run tree: 3 runs' in got["builderOpen"]
    assert 'data-doing-run="tw-aaa" data-doing-desk="builder" aria-expanded="true"' in got["builderOpen"]


def test_closing_the_tree_empties_its_slot():
    got = _run()
    assert got["closed"] == {"html": "", "expanded": "false", "text": "runs"}


def test_contract_edge_cases():
    got = _run()
    # no children: n=1, that run and its (empty) calls
    assert '<span class="dt-head">Run tree: 1 run</span>' in got["lone"]
    assert got["lone"].count('class="rt-run"') == 1 and "No mill calls on this run." in got["lone"]
    assert "child of" not in got["lone"]
    # parent ended before the child: the parent shows its end, how and exit code; the child is live under it
    ep = got["endedParent"]
    assert 'data-watch="tw-zzz" data-state="finished" data-ended-by="finished"' in ep
    assert '<span class="dt-at" title="2026-11-20T09:04:00Z">to 11-20 09:04</span>' in ep
    assert '<span class="rt-exit">exit 0</span>' in ep
    assert '<span class="rt-ok">error</span>' in ep
    assert re.search(r'<div class="doing-run-kids"><div class="rt-run" data-watch="tw-ddd"', ep)
    # asking for the child: only the child, labeled with its parent
    assert got["childAsked"].count('class="rt-run"') == 1
    assert '<span class="dt-child-of">child of tw-zzz</span>' in got["childAsked"]
    # orphan: parent row missing, parent_watch_id kept, no error
    assert '<span class="dt-child-of">child of tw-gone</span>' in got["orphan"]
    # unknown run: the server's 400 words, no tree
    assert got["unknown"] == '<span class="dt-none">connected --run: no tw run tw-nope for desk builder</span>'


def test_no_tree_is_invented_for_an_older_server():
    got = _run()
    assert got["absent404"] == '<span class="dt-none">This server sends no run tree.</span>'
    # an older server ignores run= and sends the desk list: not a tree
    assert got["oldServer"] == got["absent404"]


def test_open_trees_refresh_with_the_live_list():
    got = _run()
    assert got["refreshed"] == ["/api/v1/doing?run=tw-eee&desk=builder"]


def test_run_tree_uses_palette_tokens_only():
    css = CSS.read_text(encoding="utf-8")
    part = css[css.index("Card 1240"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", part)
    for cls in (".doing-run-kids", ".dt-child-of", "button.dt-tree", ".doing-run-tree", ".rt-call"):
        assert cls in part, cls


def test_served_shapes_from_the_card_1239_server():
    got = _run()
    # one live root run with no parent: a row with a runs button, no nesting, no child label
    assert _outline(got["served"]) == [(0, "tw-535d9c73e8eb49d2")]
    assert 'data-doing-run="tw-535d9c73e8eb49d2" data-doing-desk="grok-tui"' in got["served"]
    assert "child of" not in got["served"]
    t = got["servedTree"]
    assert '<span class="dt-head">Run tree: 1 run</span>' in t
    assert '<span class="rt-counts">0 calls, 0 ok, 0 failed</span>' in t
    assert "No mill calls on this run." in t
