"""COLLAB replay: the desks' recorded activity, played back.

Runs rd-model.js and rd-view.js in Node against a small office and checks what a
reader sees: one plain sentence per kind (mail, todo, hold, wake, doing, score),
the picked roster or station decides which desks the rows are about, a desk off
it is drawn as "outside", a card move stands in for the activity row of the same
card, the window rolls back from now, and the playback length is one constant.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RD = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

NOW = "2026-11-13T04:40:00Z"


def _row(i, typ, aid, at, frm, to, fs, ts, reason, ended=None):
    return {"id": i, "type": typ, "activity_id": aid, "at": at, "from_desk": frm, "to_desks": to,
            "from_state": fs, "to_state": ts, "reason": reason, "ended_at": ended}


# The replay page, as GET /api/v1/replay sends it (cards 1205, 1206): one transition per row,
# each with its own edges. The rows a reader should not see (create, recipient bookkeeping,
# preview, peek, score) are in it on purpose.
REPLAY_ROWS = [
    _row(1, "todo", 7, "2026-11-13 04:00:00", "validator", [], "none", "open", "create"),
    _row(2, "todo", 7, "2026-11-13 04:02:00", "validator", ["builder"], "open", "claimed", "assign"),
    _row(3, "doing", 31, "2026-11-13 04:05:00", "builder", [], "idle", "active", "tw_start"),
    _row(4, "hold", 3, "2026-11-13 04:06:00", "builder", [], "free", "held", "hold_grant"),
    _row(5, "doing", 32, "2026-11-13 04:07:00", "validator", [], "idle", "active", "tw_start"),
    _row(6, "hold", 3, "2026-11-13 04:12:00", "gardener", ["builder"], "held", "refused", "hold_refuse"),
    _row(7, "todo", 7, "2026-11-13 04:15:00", "builder", [], "claimed", "shipped", "pass_ship"),
    _row(8, "doing", 32, "2026-11-13 04:16:00", "validator", [], "active", "finished", "tw_finished", "2026-11-13 04:16:00"),
    _row(9, "hold", 3, "2026-11-13 04:18:00", "builder", [], "held", "free", "hold_drop"),
    _row(10, "hold", 3, "2026-11-13 04:19:00", "gardener", ["builder"], "refused", "held", "hold_wait_acquire"),
    _row(11, "doing", 33, "2026-11-13 04:20:00", "gardener", [], "idle", "active", "tw_start"),
    _row(12, "doing", 33, "2026-11-13 04:24:00", "gardener", [], "active", "failed", "tw_failed", "2026-11-13 04:24:00"),
    _row(13, "todo", 7, "2026-11-13 04:26:00", "validator", ["builder"], "shipped", "claimed", "pass_back"),
    _row(14, "mail", 100, "2026-11-13 04:30:00", "builder", ["validator"], "none", "live", "send_or_queue"),
    _row(15, "mail", 100, "2026-11-13 04:30:00", "validator", ["validator"], "none", "unread", "send_or_queue"),
    _row(16, "mail", 100, "2026-11-13 04:30:30", "validator", ["validator"], "unread", "unread", "preview"),
    _row(21, "mail", 101, "2026-11-13 04:31:00", "builder", ["scout"], "none", "live", "send_or_queue"),
    _row(22, "mail", 102, "2026-11-13 04:31:30", "scout", ["auditor"], "none", "live", "send_or_queue"),
    _row(17, "mail", 100, "2026-11-13 04:32:00", "validator", ["validator"], "unread", "handled", "mark"),
    _row(18, "doing", 31, "2026-11-13 04:33:00", "builder", [], "active", "waiting", "tw_wait"),
    _row(19, "hold", 3, "2026-11-13 04:34:00", "gardener", [], "held", "held", "hold_peek"),
    _row(20, "score", 40, "2026-11-13 04:35:00", "builder", [], "live", "live", "score_point"),
    _row(23, "todo", 8, "2026-11-13 04:36:00", "validator", [], "open", "claimed", "assign"),
]

OFFICE = {
    "agents": {"Office": [
        {"owner": "builder", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
        {"owner": "validator", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
        {"owner": "gardener", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
    ]},
    "doing": {"builder": {"owner": "builder", "alive": True, "stale": False, "n": 1, "doings": [
        {"id": 31, "created": "2026-11-13T04:05:00Z", "text": "", "state": "waiting", "state_at": "2026-11-13T04:33:00Z", "card": None}],
        "watchers_feed": [{"id": "todo-7", "watchers": ["validator", "gardener"], "roster": "Office"}]}},
    "rosterList": [{"name": "Office", "desks": 3}],
    "todos": {"Office": {"needs": [{"id": 7, "status": "shipped", "detail": "Stations route", "assigned": "builder", "creator": "validator"}]}},
    "holds": {"Office": [{"id": 3, "resource": "docs-lock", "owner": "gardener"}]},
    "mail": {"Office": [
        {"id": 100, "created": "2026-11-13 04:30:00", "from": "builder", "body": "re-measure #450\nmore",
         "mail_tos": [{"deskId": "validator", "receipt": 1}], "tree": "r-450"},
        {"id": 101, "created": "2026-11-13 04:31:00", "from": "builder", "body": "ping", "mail_tos": [{"deskId": "scout", "receipt": 0}],
         "tree": "r-ping", "root_id": 90},
    ]},
    "labels": {"Office": {"rows": [
        {"label": "validator", "type": "todo", "id": 7, "ord": 0},
        {"label": "builder", "type": "mail", "id": 100, "ord": 2},
        {"label": "gardener", "type": "todo", "id": 999, "ord": 0},
    ], "checks": {}}},
    "trees": {"Office": [{"name": "stations", "nodes": [
        {"type": "todo", "id": 5, "depth": 0, "title": "Stations epic"},
        {"type": "todo", "id": 7, "depth": 1, "title": "Stations route"},
    ]}]},
    "rooms": {"Office": [{"name": "r-450", "hidden": False, "nodes": [{"type": "mail", "id": 100, "depth": 0, "title": "re-measure #450"}]}]},
    "replay": {"loaded": True, "more": False, "missing": False, "oldest_id": 1, "newest_id": 23, "rows": REPLAY_ROWS},
}

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const data = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const sc = JSON.parse(process.argv[4]);
const count = process.argv[5];
const R = WallRd, V = WallRdView;
const b = R.base(data, Object.assign({rosters: ['Office'], range: '7d'}, sc), now);
const rep = R.collabReplay(b, {count: count === 'auto' ? undefined : Number(count) || count});
const txt = h => h.replace(/<[^>]+>/g, ' ').replace(/&[a-z#0-9]+;/g, ' ').replace(/\s+/g, ' ').trim();
const mid = rep.since + (rep.until - rep.since) / 2;
const ov = R.replayOverview(rep, 160);
console.log(JSON.stringify({
  count: rep.count, total: rep.total, counts: R.REPLAY_COUNTS, defaultCount: R.REPLAY_COUNT_DEFAULT,
  rows: rep.rows.map(r => ({key: r.key, kind: r.kind, act: r.act, text: txt(V.replayRows([r])), html: V.replayRows([r]), tags: r.tags})),
  at: R.replayAt(rep, now, 3).map(r => r.key),
  playMs: R.REPLAY_PLAY_MS, speeds: R.REPLAY_SPEEDS,
  rate: V.speedText(rep, 1), rateSlow: V.speedText(rep, 0.25),
  stateBefore: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:01:00Z')),
  stateWorking: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:06:00Z')),
  stateWaiting: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:34:00Z')),
  shell: V.replay(rep, {speed: 1, view: 'desks'}),
  activity: V.replay(rep, {speed: 1, view: 'activity'}),
  head: V.paneHead('collab', b, V.viewSwitch([{key:'desks',label:'Desks'},{key:'activity',label:'Activity'}], 'desks')),
  overview: {n: ov.n, sum: ov.total.reduce((a,c)=>a+c,0), peak: ov.peak,
    kinds: Object.fromEntries(Object.entries(ov.kinds).map(([k,v]) => [k, v.reduce((a,c)=>a+c,0)])),
    quiet: ov.total.filter(c => c === 0).length},
  lanes: rep.lanes.map(l => l.id),
  kinds: R.replayKindLanes().map(l => l.id),
  flows: Object.fromEntries(rep.rows.filter(r => r.flows.length).map(r => [r.key, r.flows.map(f => [f.from, f.to, f.pickAt == null ? null : f.pickAt - r.at])])),
  waitingNow: R.replayWaitingAt(rep, now),
  locksNow: R.replayLocksAt(rep, now),
  locksPast: R.replayLocksAt(rep, Date.parse('2026-11-13T04:29:00Z')),
  past: (() => { const p = R.collabReplay(b, {count: 100, end: now - 25 * 60000});
    return {live: p.live, until: p.until, keys: p.rows.map(r => r.key), oldest: p.oldest, count: p.count,
      locksEnd: R.replayLocksAt(p, p.until),
      panShort: R.replayPan(p, null, -10 * 60000)}; })(),
  pan: (() => {
    const r = {now: now, floorEnd: now - 4 * 3600000, ms: 3600000};
    return {now: R.replayPan(r, null, 60000), back: R.replayPan(r, null, -10 * 60000), far: R.replayPan(r, null, -365 * 86400000),
      fwd: R.replayPan(r, now - 25 * 60000, 24 * 60000), none: R.replayPan({now: now, ms: 3600000}, null, -60000)};
  })(),
  nowMs: now,
  dirs: Object.fromEntries(['desks', 'activity'].flatMap(v => ['lr', 'tb', null].map(d => [v + '-' + d, V.replay(rep, {speed: 1, view: v, dirs: d ? {[v]: d} : {}})]))),
  axis: {lr: R.replayAxis('lr'), tb: R.replayAxis('tb'), dflt: R.REPLAY_DIR_DEFAULT},
  age: {before: R.replayAge(mid, mid + 1, rep.ms), at: R.replayAge(mid, mid, rep.ms), half: R.replayAge(mid + rep.ms / 2, mid, rep.ms), gone: R.replayAge(mid + rep.ms + 1, mid, rep.ms)},
  keysDesks: R.replayVisibleKeys(rep, mid),
  keysActivity: R.replayItemsAt(rep, mid, 400, 'activity').items.map(i => i.key).sort(),
  keysDesksItems: [...new Set(R.replayItemsAt(rep, mid, 400, 'desks').items.map(i => i.key))].sort(),
  shellFull: V.replay(rep, {speed: 1, full: true, view: 'desks'}),
  vp: R.replayViewport(rep, mid, ov),
  tips: (() => {
    const by = Object.fromEntries(rep.rows.map(r => [r.key, r]));
    return {
      mail: V.replayTip(by['tr-14'], now),
      todo: V.replayTip(by['tr-2'], now),
      doing: V.replayTip(by['run-31'], now),
      hold: V.replayTip(by['tr-10'], now),
      holdSpan: (() => { const sp = R.replayDoingSpans(rep, now, 'desks').find(x => x.key === 'tr-4'); return sp ? V.replayTip(sp.row, now, sp) : ''; })(),
      lane: V.replayLaneTip({ name: 'builder', count: 3 }),
      kind: V.replayLaneTip({ kind: 'mail', name: 'mail', count: 1 }),
      empty: V.replayLaneTip({ name: 'office', count: 0 }),
    };
  })(),
  cluster: { dflt: R.REPLAY_CLUSTER_DEFAULT, scale: [R.groupScale(1), R.groupScale(4), R.groupScale(100)], buckets: R.REPLAY_GROUP_BUCKETS },
  pack: (() => {
    const items = [
      {id:'a', lane:'mail', pos:0.10}, {id:'b', lane:'mail', pos:0.10}, {id:'c', lane:'mail', pos:0.10},
      {id:'d', lane:'mail', pos:0.10}, {id:'e', lane:'mail', pos:0.10},
      {id:'f', lane:'mail', pos:0.80},
      {id:'g', lane:'todo', pos:0.20}, {id:'h', lane:'todo', pos:0.90},
    ];
    const p = R.replayPack(items, {len: 1000, sizeOf: () => ({main: 40, cross: 16}), maxRows: 4, gap: 2});
    return { place: p.place, rows: p.rows, overflow: p.overflow.map(o => ({n: o.n, ids: o.ids, lane: o.lane, pos: o.pos, row: o.row})) };
  })(),
  groups: (() => {
    const at = (ms) => ({at: Date.parse('2026-11-13T04:00:00Z') + ms});
    const items = [
      {id:'m1', lane:'builder', kind:'mail', pos:0.2, row: at(0)},
      {id:'m2', lane:'builder', kind:'mail', pos:0.21, row: at(1000)},
      {id:'m3', lane:'builder', kind:'mail', pos:0.8, row: at(3*3600000)},
      {id:'t1', lane:'builder', kind:'todo', pos:0.2, row: at(500)},
      {id:'m4', lane:'validator', kind:'mail', pos:0.2, row: at(0)},
    ];
    const g = R.replayGroup(items, {span: 6*3600000, buckets: 36});
    return g.map(x => ({id: x.id, lane: x.lane, kind: x.kind, n: x.n, scale: x.scale, ids: x.items.map(i => i.id), pos: x.pos}));
  })(),
  overflowTip: (() => {
    const by = Object.fromEntries(rep.rows.map(r => [r.key, r]));
    return V.replayOverflowTip([by['tr-14'], by['tr-21']].filter(Boolean), now);
  })(),
  clusterShell: {
    group: V.replay(rep, {speed: 1, view: 'desks', clusters: {desks: 'group'}}),
    spread: V.replay(rep, {speed: 1, view: 'activity', clusters: {activity: 'spread'}}),
    defDesks: V.replay(rep, {speed: 1, view: 'desks'}),
    defActivity: V.replay(rep, {speed: 1, view: 'activity'}),
  },
}));
"""


def run(scope: dict | None = None, count: str = "300", data: dict = OFFICE) -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW, json.dumps(scope or {}), str(count)],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def by_key(got: dict) -> dict:
    return {r["key"]: r for r in got["rows"]}


def test_each_kind_reads_as_a_plain_sentence():
    rows = by_key(run())
    assert "builder mailed validator re-measure #450" in rows["tr-14"]["text"]
    assert "validator assigned card 7 to builder" in rows["tr-2"]["text"] and "CLAIMED" in rows["tr-2"]["text"]
    assert "builder shipped card 7" in rows["tr-7"]["text"] and "SHIPPED" in rows["tr-7"]["text"]
    assert "validator sent back card 7 back to builder" in rows["tr-13"]["text"]
    assert "validator read letter 100" in rows["tr-17"]["text"]
    assert "gardener was refused docs-lock" in rows["tr-6"]["text"] and rows["tr-6"]["kind"] == "hold"
    assert "gardener took docs-lock from builder" in rows["tr-10"]["text"]
    assert "builder is running a task" in rows["run-31"]["text"]
    assert "validator ran a task and finished it" in rows["run-32"]["text"]
    assert "gardener ran a task and failed it" in rows["run-33"]["text"]
    for r in rows.values():
        assert not re.search(r"\b(desk_id|roster_id|from_state|to_state|act=|kind=)\b", r["text"]), r["text"]
        assert 'class="rd-ki k-' + r["kind"] + '"' in r["html"]


def test_hidden_rows_draw_nothing():
    keys = set(by_key(run()))
    for hidden in ("tr-1", "tr-15", "tr-16", "tr-19", "tr-20"):
        assert hidden not in keys, hidden + ": create, recipient bookkeeping, preview, peek and score are not drawn"
    assert "tr-3" not in keys and "tr-18" not in keys and "run-31" in keys, "a tw run is one span, not a row per state"
    assert "tr-9" not in keys, "a drop ends the held span; it is not a tick of its own"


def test_scope_keeps_rows_touching_the_focused_desks_and_clouds_the_rest():
    rows = by_key(run({"only": ["builder"]}))
    assert "tr-22" not in rows, "a letter with no focused desk on either side is not shown"
    assert "run-32" not in rows
    letter = rows["tr-14"]
    assert "outside" in letter["text"] and "validator" not in letter["text"].replace("title", "")
    assert 'class="rd-cloud"' in letter["html"] and "outside this scope: validator" in letter["html"]
    assert 'data-rd-desk="builder"' in letter["html"]
    out = by_key(run())["tr-21"]
    assert "outside" in out["text"], "a desk off the roster is a cloud"


def test_the_window_is_a_row_count_defaulting_to_300():
    got = run()
    assert got["counts"] == [100, 300, 1000] and got["defaultCount"] == 300
    assert got["count"] == 300
    assert run(count="100")["count"] == 100
    assert run(count="1000")["count"] == 1000
    assert run(count="auto")["count"] == 300, "an unknown pick falls back to 300"
    assert got["at"][0] == "tr-23", "newest first at the playhead"
    shell = got["shell"]
    assert 'data-rp-count="100"' in shell and 'data-rp-count="300" class="on"' in shell and 'data-rp-count="1000"' in shell
    assert "data-rp-win" not in shell, "hour, day, week and auto are gone"


def test_playback_is_one_constant_and_slower_speeds_exist():
    got = run()
    assert got["playMs"] == 120000
    assert got["speeds"][:2] == [0.25, 0.5]
    assert got["rate"].endswith("in 2 min") and "row" in got["rate"]
    assert "in 8 min" in got["rateSlow"]
    assert 'data-rp-step="1"' in got["shell"] and 'data-rp-play="1"' in got["shell"]


def test_desk_state_at_the_playhead_comes_from_its_recorded_changes():
    got = run()
    assert got["stateBefore"] == ""
    assert got["stateWorking"] == "working"
    assert got["stateWaiting"] == "waiting"


def test_collab_has_no_between_ring_view():
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert '{ key: "map", label: "Between" }' not in app
    assert '{ key: "desks", label: "Desks" }' in app
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css


def test_collab_has_only_the_two_subtabs_and_no_list_or_blocking():
    got = run()
    shell, activity, head = got["shell"], got["activity"], got["head"]
    assert 'data-rd-view="desks"' in head and 'data-rd-view="activity"' in head
    for html in (shell, activity):
        assert "data-rp-list" not in html and "data-rp-blocking" not in html
        assert "BLOCKING SOMEONE NOW" not in html
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert '{ key: "desks", label: "Desks" }, { key: "activity", label: "Activity" }' in app
    assert '"rd-collab-subtab"' in app
    assert "Replay" not in re.findall(r'label: "(\w+)"', app) and "Timeline" not in re.findall(r'label: "(\w+)"', app)


def test_controls_sit_above_the_stage_in_the_dom():
    got = run()
    for html in (got["shell"], got["activity"]):
        play = html.index('data-rp-play="1"')
        ov = html.index('data-rp-ov="1"')
        stage = html.index('data-rp-lanes=')
        assert play < ov < stage, "play and the bar graph sit above the stage"
        assert 'rd-rp-go' in html and 'data-rp-play="1"' in html


def test_full_screen_toggle_with_a_viewport_fallback():
    got = run()
    assert 'data-rp-full="1" aria-label="Full screen" aria-pressed="false"' in got["shell"]
    assert 'aria-pressed="true" title="Leave full screen (Esc)"' in got["shellFull"]
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "requestFullscreen" in app and "fullscreenchange" in app and '"Escape"' in app
    css = (RD / "rd.css").read_text(encoding="utf-8")
    fs = [ln for ln in css.splitlines() if "rd-rp-fs" in ln]
    assert any("position: fixed; inset: 0" in ln for ln in fs), "covers the viewport without the API"
    assert not any(".rd-rp-lapse { order: 2" in ln for ln in fs), "controls stay on top in full screen"
    assert any(".rd-pill" in ln and "font-size: 18px" in ln for ln in fs), "desk pills scale up"


def test_the_overview_is_a_bar_graph_of_row_counts_with_a_viewport():
    got = run()
    ov = got["overview"]
    assert ov["n"] == 160 and ov["sum"] == got["total"], "every loaded row lands in a bucket"
    assert ov["peak"] >= 1 and ov["quiet"] > 0, "bursts rise, quiet stretches stay flat"
    assert sum(ov["kinds"].values()) == ov["sum"] and ov["kinds"]["mail"] >= 1
    shell = got["shell"]
    assert "polyline" not in shell and "rd-rp-tr-lit" not in shell, "the ekg line is gone"
    assert 'class="rd-rp-bars rd-rp-bars-dim"' in shell and 'class="rd-rp-bars rd-rp-bars-lit"' in shell
    assert 'clip-path="url(#rd-rp-played)"' in shell
    assert 'data-rp-vp="1"' in shell and 'data-rp-ov="1" data-lo="' in shell
    assert re.search(r'<rect class="k-(mail|todo|hold|wake|doing|score)"', shell), "a bar coloured by kind"
    assert got["vp"]["lo"] < got["vp"]["hi"] or got["vp"]["hi"] > 0
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "rpJump" in app and "onVp" in app and "[data-rp-ov]" in app
    assert 'data-rp-ov-dir="-1"' in shell and 'data-rp-ov-dir="1"' in shell
    assert 'aria-label="Previous 100"' in shell and 'aria-label="Next 100"' in shell
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "cursor: grab;" in css and "cursor: grabbing;" in css
    assert "rd-rp-ov-btn" in css and "rd-rp-ov-row" in css


def test_stage_lanes_follow_the_pick_with_the_cloud_pinned_last():
    got = run()
    assert "@office" not in got["lanes"], "every replay row names its desk; wakes are not drawn"
    assert got["lanes"][-1] == "@out", "outside sits at the end"
    assert {"builder", "validator", "gardener"} <= set(got["lanes"])
    shell = got["shell"]
    for lane in got["lanes"]:
        assert f'data-lane="{lane}"' in shell and f'data-col="{lane}"' in shell
    rain = shell[shell.index('data-rp-rain="1">'):shell.index('data-rp-field="desks"')]
    assert "rd-rp-item" not in rain, "the field starts empty; items are placed by the playhead"


def test_pickup_is_read_from_the_records_per_kind():
    fl = run()["flows"]
    assert fl["tr-14"] == [["builder", "validator", 2 * 60000]], "picked up at the recipient's own mark row"
    assert fl["tr-21"] == [["builder", "@out", None]], "no later row by the recipient: it waits in the receiver's column"
    assert fl["tr-2"] == [["validator", "builder", 13 * 60000]], "a card handed on is picked up at the receiver's next move"
    assert fl["tr-10"] == [["builder", "gardener", 0]], "the waiter that acquires a promise has it on the spot"
    got = run()
    assert got["waitingNow"].get("@out")
    assert any(x["text"] == "docs-lock" for x in got["locksNow"]["gardener"]), "at now the holds table says who holds"
    assert any(x["item"] == "hold-3" for x in got["locksPast"]["gardener"]), "in the past, the held span says who holds"
    assert "builder" not in got["locksPast"], "builder had dropped it by then"


def test_desk_pills_stay_fixed():
    got = run()
    desks = [l for l in got["lanes"] if not l.startswith("@")]
    assert desks == ["builder", "validator", "gardener"], "the DESKS list order, not a layout that moves"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "replayLayout" not in app and "placeLanes" not in app, "no gravity: pills never move"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "--lane-pitch" in css
    assert "grid-template-rows: repeat(var(--lanes, 1), var(--lane-pitch))" in css


def test_activity_view_is_one_lane_per_drawn_kind_of_the_same_instances():
    got = run()
    act = got["activity"]
    assert got["kinds"] == ["mail", "todo", "hold", "doing"], "wake and score rows are hidden, so they get no lane"
    for k in got["kinds"]:
        assert f'data-lane="{k}"' in act and f'data-col="{k}"' in act
    assert 'data-rp-subtab="activity"' in act and 'data-rp-view="activity"' in act
    assert 'data-rp-subtab="desks"' in got["shell"]
    assert 'rd-pill rd-kind k-mail' in act
    # same instances: unique keys on both views match the visible set
    assert got["keysDesks"] == got["keysActivity"] == got["keysDesksItems"]
    assert got["keysDesks"], "the mid-window playhead shows some rows"


def test_position_is_a_function_of_the_playhead_the_time_and_the_window():
    got = run()
    age = got["age"]
    assert age["before"] is None and age["gone"] is None
    assert age["at"] == 0
    assert abs(age["half"] - 0.5) < 1e-9
    ax, d = got["axis"], got["dirs"]
    assert ax["dflt"] == {"desks": "lr", "activity": "lr"}
    assert ax["lr"]["main"] == "x" and ax["lr"]["cross"] == "y" and ax["tb"]["main"] == "y" and ax["tb"]["cross"] == "x"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "it.pos * L.len" in app and "replayItemsAt(rep, t, RP_ITEMS, rp.view)" in app
    assert "el.style.transform" in app and "el.style.opacity" in app


def test_stage_motion_is_transform_and_opacity_only():
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    body = app[app.index("function placePacked"):app.index("function drawStage")]
    assert "el.style.transform" in body and "el.style.opacity" in body
    assert "placePacked" in body and "drawSpreadItems" in body and "drawGroupItems" in body
    assert "RP_ITEMS" in app and "moving()" in app


def test_panning_slides_the_window_through_the_record():
    got = run()
    p, now = got["past"], got["nowMs"]
    assert p["live"] is False and p["until"] == now - 25 * 60000
    assert p["count"] == 100
    assert "tr-14" not in p["keys"] and "tr-7" in p["keys"], "the window re-scopes: rows after its end are out"
    assert "gardener" not in p["locksEnd"], "a past window does not borrow the holds table of now"
    assert p["panShort"] is None, "a record shorter than the window has nowhere to pan"
    pan = got["pan"]
    assert pan["now"] is None, "never past now: the window ends now"
    assert pan["back"] == now - 10 * 60000
    assert pan["far"] == now - 4 * 3600000, "clamped so the window still holds its row count"
    assert pan["fwd"] == now - 60000
    assert pan["none"] is None, "no floor means the record is shorter than the window"
    shell = got["shell"]
    assert 'data-rp-span="1"' in shell, "the window's start and end show while panning"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "PAN_PX" in app and "onVp" in app
    assert "rpJump" in app and "!d.moved && n === \"pointerup\"" in app
    assert "function ovStep" in app and "holdOv" in app
    assert 'data-rp-ov-dir' in (RD / "rd-view.js").read_text(encoding="utf-8")


def test_the_record_is_read_in_keyset_pages_and_cached_by_id_range():
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert '"/api/v1/replay?project="' in app and '"&limit="' in app
    assert '"&after=" + rpl.newest' in app, "the head reads only rows newer than the cache"
    assert '"&before=" + rpl.oldest' in app, "a pan past the oldest row reads the next older page"
    assert 'rpl.pages[j.oldest_id + "-" + j.newest_id]' in app, "each page kept under its id range"
    assert "rpl.byId[r.id] = r" in app, "rows merge by id, so overlapping pages never duplicate"
    for gone in ("/api/v1/doing/history?on=", "TRAIL_KEEP", "data.trail", "data.moves"):
        assert gone not in app, gone + ": the old per-desk and per-item joins are gone"
    assert '"events"' not in app[app.index("collab: ["):app.index("collab: [") + 120], "COLLAB does not read the activity table"


def test_missing_replay_route_shows_a_notice_and_no_lines():
    data = json.loads(json.dumps(OFFICE))
    data["replay"] = {"rows": [], "missing": True, "loaded": False}
    got = run(data=data)
    assert got["rows"] == [] and got["flows"] == {}
    for html in (got["shell"], got["activity"]):
        assert 'data-rp-missing="1"' in html and "/api/v1/replay" in html
        assert "data-rp-lanes=" not in html, "no stage is drawn from other reads"
    data["replay"] = None
    got = run(data=data)
    assert "Loading COLLAB" in got["shell"] and got["rows"] == []


def test_every_activity_carries_its_labels_and_trees():
    got = run()
    rows = {r["key"]: r for r in got["rows"]}
    card = rows["tr-2"]["tags"]
    assert [l["name"] for l in card["labels"]] == ["validator"], "joined from the labels rows by type and id"
    assert card["trees"] == [{"name": "stations", "kind": "tree", "depth": 1, "root": "Stations epic", "rootKey": "todo-5", "hidden": False}]
    assert card["watchers"] == ["validator", "gardener"], "watchers from the doing feed's card lists"
    assert card["roster"] == "Office"
    assert rows["tr-7"]["tags"] == card, "every row on the card carries the card's tags"
    mail = rows["tr-14"]["tags"]
    assert [l["name"] for l in mail["labels"]] == ["builder"]
    assert [(t["name"], t["root"]) for t in mail["trees"]] == [("r-450", "re-measure #450")]
    ping = rows["tr-21"]["tags"]
    assert ping["labels"] == [] and ping["trees"][0]["name"] == "r-ping" and ping["trees"][0]["rootKey"] == "mail-90", "the letter's own room"
    for key, r in rows.items():
        if r["kind"] in ("hold", "doing"):
            t = r["tags"]
            assert t is None or (t["labels"] == [] and t["trees"] == [] and t["watchers"] == []), key + ": no labels, trees or watchers in the data, so none are drawn"
    assert rows["tr-2"]["html"].count("rd-tag-r") == 1 and 'title="roster Office"' in rows["tr-2"]["html"]
    assert 'title="watched by gardener"' in rows["tr-2"]["html"]
    html = rows["tr-2"]["html"]
    assert 'class="rd-tag rd-tag-l" title="label validator, position 1">validator<' in html
    assert 'class="rd-tag rd-tag-t" title="card tree stations, 1 deep: Stations epic"' in html
    assert "label gardener" not in html, "a label on another card is not this card's"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "firstTag(tags)" in app and "V.tagsHtml(one, 1)" in app, "the desk-view icons carry one chip; the rest is on hover"
    assert '"labels", "trees", "rooms"' in app


def test_links_come_only_from_the_row_edges():
    got = run()
    flows = got["flows"]
    assert flows["tr-2"][0][:2] == ["validator", "builder"], "assign: from_desk to to_desks"
    assert flows["tr-13"][0][:2] == ["validator", "builder"], "pass back: from_desk to to_desks"
    assert flows["tr-14"][0][:2] == ["builder", "validator"], "a letter links sender and recipient"
    assert "tr-7" not in flows, "a ship row names no second desk: a tick, no line"
    assert "tr-23" not in flows and "tr-23" in by_key(got), "an assign that names no other desk degrades to a tick"
    assert "tr-6" not in flows, "a refused promise stays a tick on the waiter"
    assert "tr-17" not in flows, "a mark is the recipient's own tick"
    model = (RD / "rd-model.js").read_text(encoding="utf-8")
    assert "mail_tos" not in model[model.index("function replayEvents"):model.index("function sentence")], "no mailbox join for edges"


STATE_SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
const R = WallRd, cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(e => R.stateDesks(Object.assign({peers: []}, e)))));
"""


def state_of(*events):
    out = subprocess.run([NODE, "-e", STATE_SCRIPT, str(RD), json.dumps(list(events))], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_state_desks_read_from_the_row_alone():
    tick, line, mail, hand, run_ = state_of(
        {"kind": "todo", "act": "claim", "actor": "builder"},
        {"kind": "todo", "act": "assign", "actor": "validator", "peers": ["builder"]},
        {"kind": "mail", "actor": "builder", "peers": ["validator", "auditor", "builder"]},
        {"kind": "hold", "act": "hold", "actor": "gardener", "handFrom": "builder"},
        {"kind": "doing", "act": "run", "actor": "builder"},
    )
    assert tick == {"holders": ["builder"], "from": [], "waiting": []}, "a tick sits on its own desk"
    assert line == {"holders": ["builder"], "from": ["validator"], "waiting": []}
    assert mail == {"holders": ["validator", "auditor"], "from": ["builder"], "waiting": []}
    assert hand == {"holders": ["gardener"], "from": ["builder"], "waiting": []}, "a promise handed on"
    assert run_ == {"holders": ["builder"], "from": [], "waiting": []}


def test_direction_toggles_per_subtab_and_both_start_left_to_right():
    got = run()
    ax, d = got["axis"], got["dirs"]
    assert ax["dflt"] == {"desks": "lr", "activity": "lr"}
    assert ax["lr"]["main"] == "x" and ax["tb"]["main"] == "y"
    for v in ("desks", "activity"):
        assert "rd-dir-lr" in d[v + "-null"] and 'data-rp-dir="tb"' in d[v + "-null"], v + " starts left to right; the toggle offers top to bottom"
        assert "rd-dir-tb" in d[v + "-tb"] and 'data-rp-dir="lr"' in d[v + "-tb"]
        assert 'data-rp-rain="1"' in d[v + "-lr"] and 'data-rp-rain="1"' in d[v + "-tb"], v + " uses the same stage in both directions"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "#rd .rd-dir-lr .rd-rp-stage { flex-direction: row;" in css, "left to right: pills in a column on the left"
    assert "#rd .rd-dir-tb .rd-rp-stage { flex-direction: column; }" in css, "top to bottom: pills in a row on top"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert 'RP_DIR_KEY = "rd-replay-dir-"' in app and "save(RP_DIR_KEY + rp.view" in app, "each subtab keeps its own choice"
    assert "el.style.transform" in app and "ax.main === \"x\"" in app, "placement follows the axis"


def test_kind_palette_is_single_sourced_and_used_on_bars_icons_and_chips():
    css = (RD / "rd.css").read_text(encoding="utf-8")
    kinds = ["mail", "todo", "hold", "wake", "doing", "score"]
    values = {}
    for k in kinds:
        hits = re.findall(rf"--rd-k-{k}:\s*(#[0-9a-fA-F]{{6}})", css)
        assert len(hits) == 1, k
        values[k] = hits[0].lower()
        assert css.count(f"var(--rd-k-{k})") >= 5, k + " should be used, not restated"
    # not the desk state-ring green or waiting amber
    assert values["doing"] != "#4fdd9b" and values["todo"] != "#e4b56a"
    assert len(set(values.values())) == 6, "each kind has its own colour"
    assert "#rd .rd-rp-bars .k-mail { fill: var(--rd-k-mail); }" in css
    assert "#rd .rd-ki.k-mail { color: var(--rd-k-mail); }" in css
    assert "fill: color-mix(in srgb, currentColor" in css, "icons are filled, not a faint outline"
    assert "#rd .rd-rp-dchip.k-mail, #rd .rd-rp-dchip .rd-dnm.k-mail { --rd-k: var(--rd-k-mail); }" in css
    assert "#rd .rd-pill.rd-kind.k-mail { --rd-k: var(--rd-k-mail); }" in css
    assert "#rd .rd-rp-links .k-mail { stroke: var(--rd-k-mail); }" in css
    assert "#rd .rd-rp-legend > span.k-mail { color: var(--rd-k-mail); }" in css
    assert "#rd .rd-rp-bars-dim rect { opacity: .32; }" in css
    assert "#rd .rd-rp-bars-lit rect { opacity: 1; }" in css
    got = run()
    act, desks = got["activity"], got["shell"]
    for k in ("mail", "todo", "hold", "doing"):
        assert f'class="k-{k}"' in act, "bar or legend named for " + k
        assert f"rd-pill rd-kind k-{k}" in act
        assert f'class="rd-ki k-{k}"' in desks
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function tickItem" in app and "rd-rp-tick k-" in app
    assert "#rd .rd-rp-tick.k-mail" in (RD / "rd.css").read_text(encoding="utf-8")
    # no second hex palette for kinds in the javascript
    assert not re.search(r"#[0-9a-fA-F]{6}", app)

def test_hover_shows_one_shared_details_card():
    got = run()
    mail, todo, doing, hold = (got["tips"][k] for k in ("mail", "todo", "doing", "hold"))
    # kind row with a colour swatch, then title, local time and relative age
    assert 'class="rd-rp-tip-k k-mail"' in mail and 'class="rd-rp-swatch"' in mail and ">mail</div>" in mail
    assert "re-measure #450" in mail
    assert "<time>" in mail and "ago" in mail
    assert "sender builder" in mail and "receiver validator" in mail
    assert "rd-tag-l" in mail and "builder" in mail  # label
    assert "rd-tag-t" in mail  # mail room
    assert 'class="rd-rp-tip-k k-todo"' in todo and "Stations route" in todo
    assert "from validator" in todo and "to builder" in todo
    assert "rd-tag-l" in todo and "rd-tag-t" in todo and "rd-tag-w" in todo and "rd-tag-r" in todo
    assert 'class="rd-rp-tip-k k-doing"' in doing and "doing builder" in doing
    assert 'class="rd-rp-tip-k k-hold"' in hold and "holder gardener" in hold and "from builder" in hold
    assert "rd-rp-tip-span" in got["tips"]["holdSpan"] and "released" in got["tips"]["holdSpan"], "a held span says how it ended"
    assert "3 in the window" in got["tips"]["lane"] and "builder" in got["tips"]["lane"]
    assert 'class="rd-rp-tip-k k-mail"' in got["tips"]["kind"] and "1 in the window" in got["tips"]["kind"] and 'class="rd-rp-swatch"' in got["tips"]["kind"]
    assert "0 in the window" in got["tips"]["empty"]
    # one shared popup in the shell, reused for every item
    for html in (got["shell"], got["activity"]):
        assert html.count('id="rd-rp-tip"') == 1
        assert 'role="tooltip"' in html and "rd-rp-tip" in html
        assert 'data-rp-tip="lane"' in html
    assert got["activity"].count('data-rp-tip="lane"') == 4, "each activity-type pill is hoverable"
    assert 'data-rd-desk="builder"' in got["shell"] and 'data-rp-tip="lane"' in got["shell"]
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "#rd .rd-rp-tip { position: fixed;" in css
    assert "#rd .rd-rp-tip { " in css and "pointer-events: none;" in css
    assert "#rd .rd-rp-swatch" in css
    for k in ("mail", "todo", "hold", "doing"):
        assert f"#rd .rd-rp-tip-k.k-{k} {{ --rd-k: var(--rd-k-{k});" in css
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "TIP_ID = " in app and "aria-describedby" in app
    assert "tabIndex = 0" in app and 'data-rp-tip", "item"' in app
    assert "pointerover" in app and "focusin" in app and "function tipTick" in app
    assert "function prepItem" in app, "items are tagged, not given their own tip nodes"
    assert app.count('id = TIP_ID') == 1 or app.count('id="rd-rp-tip"') <= 1
    view = (RD / "rd-view.js").read_text(encoding="utf-8")
    assert "function replayTip" in view and "function replayLaneTip" in view

def test_items_pack_into_subrows_then_overflow():
    p = run()["pack"]
    place, rows, overflow = p["place"], p["rows"], p["overflow"]
    assert rows["mail"] == 5, "four visible rows plus an overflow strip"
    assert rows["todo"] == 1
    for i, k in enumerate("abcd"):
        assert place[k]["row"] == i and not place[k]["hide"], k
    assert place["e"]["hide"] is True
    assert place["f"]["row"] == 0 and not place["f"]["hide"], "far along the time axis, same first row"
    assert place["g"]["row"] == place["h"]["row"] == 0 and not place["g"]["hide"]
    assert len(overflow) == 1 and overflow[0]["n"] == 1 and overflow[0]["ids"] == ["e"]
    assert overflow[0]["pos"] == 0.10, "the +N stays at the hidden item's time"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function drawSpreadItems" in app and "R.replayPack" in app


def test_group_mode_merges_by_lane_kind_and_time_and_is_the_default():
    got = run()
    assert got["cluster"]["dflt"] == {"desks": "group", "activity": "group"}
    assert got["cluster"]["scale"] == [1, 2, 2.6]
    groups = {(g["lane"], g["kind"], g["n"]): g for g in got["groups"]}
    near = [g for g in got["groups"] if g["lane"] == "builder" and g["kind"] == "mail"]
    assert len(near) == 2, "two mail buckets on builder: the close pair, and the far one"
    close = next(g for g in near if g["n"] == 2)
    assert close["ids"] == ["m1", "m2"] and close["scale"] == 2 ** 0.5 or abs(close["scale"] - (2 ** 0.5)) < 1e-9
    far = next(g for g in near if g["n"] == 1)
    assert far["ids"] == ["m3"] and far["scale"] == 1
    todo = next(g for g in got["groups"] if g["kind"] == "todo")
    assert todo["n"] == 1 and todo["ids"] == ["t1"], "a different kind on the same lane stays its own mark"
    other = next(g for g in got["groups"] if g["lane"] == "validator")
    assert other["n"] == 1 and other["ids"] == ["m4"], "the same kind on another lane is not merged"
    tip = got["overflowTip"]
    assert "+2 mail" in tip and "rd-rp-tip-list" in tip and "re-measure #450" in tip
    sh = got["clusterShell"]
    assert 'data-rp-cluster-now="group"' in sh["group"] and 'data-rp-cluster-now="group"' in sh["defDesks"]
    assert 'data-rp-cluster-now="group"' in sh["defActivity"], "both subtabs start in group"
    assert 'data-rp-cluster-now="spread"' in sh["spread"]
    assert "data-rp-cluster=" in sh["defDesks"] and "rd-rp-cluster" in sh["defDesks"]
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "RP_CLUSTER_KEY" in app and "save(RP_CLUSTER_KEY + rp.view" in app
    assert "function drawGroupItems" in app and "replayOverflowTip" in app
    assert 'data-rp-tip", "group"' in app



def _node(script: str) -> dict:
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def test_anticipation_scale_grows_with_n_returns_after_emit_and_is_deterministic():
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
const ms = 120000;
const lead = (R.REPLAY_LEAD_PLAY_MS / R.REPLAY_PLAY_MS) * ms;
const settle = (R.REPLAY_SETTLE_PLAY_MS / R.REPLAY_PLAY_MS) * ms;
const at = 60000;
const row = (lane, kind, t) => ({{lane, kind, at: t}});
const one = {{ms, pool: [row('a','mail',at)]}};
const four = {{ms, pool: [row('a','mail',at), row('a','todo',at+10), row('a','todo',at+20), row('a','hold',at+30)]}};
const t = at - lead * 0.2;
const A = R.replayAnticipate(one, t, 'desks');
const B = R.replayAnticipate(four, t, 'desks');
const after = R.replayAnticipate(four, at + 30 + settle + 1, 'desks');
const mid = R.replayAnticipate(four, at + 30 + settle * 0.2, 'desks');
const idle = R.replayAnticipate(one, at - lead - 1, 'desks');
const same = JSON.stringify(R.replayAnticipate(four, t, 'desks')) === JSON.stringify(R.replayAnticipate(four, t, 'desks'));
const act = R.replayAnticipate({{ms, pool: [row('x','mail',at), row('y','mail',at+5)]}}, t, 'activity');
console.log(JSON.stringify({{
  leadPlay: R.REPLAY_LEAD_PLAY_MS, settlePlay: R.REPLAY_SETTLE_PLAY_MS,
  scale1: A.a.scale, n1: A.a.n, scale4: B.a.scale, n4: B.a.n, kind4: B.a.kind,
  after: after.a ? after.a.scale : 1, mid: mid.a && mid.a.scale, idle: !idle.a,
  same, s1: R.replayAnticipateScale(1), s4: R.replayAnticipateScale(4),
  s9: R.replayAnticipateScale(9), s100: R.replayAnticipateScale(100),
  actN: act.mail && act.mail.n, actScale: act.mail && act.mail.scale
}}));
"""
    got = _node(script)
    assert got["leadPlay"] == 1250 and got["settlePlay"] == 500
    assert got["n1"] == 1 and got["n4"] == 4
    assert got["scale4"] > got["scale1"] > 1, "scale grows with the number of upcoming emits"
    assert got["s4"] > got["s1"] > 1 and got["s9"] == 1.25 and got["s100"] == 1.25
    assert got["after"] == 1, "after the last emit and its settle, the pill is back at 1"
    assert got["mid"] > 1, "just after emit it is still easing back"
    assert got["idle"] is True and got["same"] is True
    assert got["kind4"] == "todo", "dominant kind is the most frequent in the lead window"
    assert got["actN"] == 2 and got["actScale"] > 1, "activity view groups the same function by kind"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function applyAnticipate" in app and '"--rd-ant"' in app
    assert "pill.animate" not in app, "pickup must not WAAPI-scale the pill"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "scale(var(--rd-ant, 1))" in css
    assert "@media (prefers-reduced-motion: reduce)" in css and "transform: none;" in css


def test_overview_arrows_jump_a_fixed_100_rows_and_clamp_at_the_ends():
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
const now = 600000;
const ticks = Array.from({{length: 500}}, (_, i) => ({{at: 1000 + i * 1000, kind: 'mail'}}));
const floor = ticks[299].at;
const rep = {{now, ticks, floorEnd: floor, ms: 10000, count: 300}};
const prev = R.replayPanRows(rep, null, -1);
const prev2 = R.replayPanRows(rep, prev, -1);
const stuck = R.replayPanRows(rep, prev2, -1);
const nxt = R.replayPanRows(rep, prev, 1);
const fromLast = R.replayPanRows(rep, ticks[499].at, 1);
console.log(JSON.stringify({{
  rows: R.REPLAY_PAN_ROWS,
  prev, expectPrev: ticks[399].at,
  prev2, floor, stuck,
  nxt, expectNxt: ticks[499].at,
  fromLast,
  canNowBack: R.replayPanCan(rep, null, -1),
  canNowFwd: R.replayPanCan(rep, null, 1),
  canFloorBack: R.replayPanCan(rep, floor, -1),
  canFloorFwd: R.replayPanCan(rep, floor, 1)
}}));
"""
    got = _node(script)
    assert got["rows"] == 100, "the jump size is one constant"
    assert got["prev"] == got["expectPrev"]
    assert got["prev2"] == got["floor"] and got["stuck"] == got["floor"]
    assert got["nxt"] == got["expectNxt"]
    assert got["fromLast"] is None, "the last step later lands at now"
    assert got["canNowBack"] is True and got["canNowFwd"] is False
    assert got["canFloorBack"] is False and got["canFloorFwd"] is True
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function ovStep" in app and "setInterval" in app and "400" in app
    assert 'ev.key === "ArrowLeft"' in app and 'ev.key === "ArrowRight"' in app
    view = (RD / "rd-view.js").read_text(encoding="utf-8")
    assert 'ovBtn(-1, "Previous 100")' in view and 'ovBtn(1, "Next 100")' in view
    assert "disabled" in view


def test_doing_spans_use_row_times_open_at_playhead_and_are_deterministic():
    got = run()
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
const now = {got['nowMs']};
const data = {json.dumps(OFFICE)};
const b = R.base(data, {{rosters: ['Office'], range: '7d'}}, now);
const rep = R.collabReplay(b, {{count: 300}});
const T = s => Date.parse('2026-11-13T' + s + 'Z');
function find(spans, key) {{ return spans.find(s => s.key === key) || null; }}
const atNow = R.replayDoingSpans(rep, now, 'desks');
const at10 = R.replayDoingSpans(rep, T('04:10:00'), 'desks');
const act = R.replayDoingSpans(rep, now, 'activity');
const sig = x => JSON.stringify(x.map(s => [s.key, s.start, s.end, s.open, s.pos0, s.pos1, s.lane, s.rowIndex, s.how]));
const same = sig(R.replayDoingSpans(rep, now, 'desks')) === sig(R.replayDoingSpans(rep, now, 'desks'));
// two runs on one desk at once: both drawn, stacked, neither ends the other
const two = JSON.parse(JSON.stringify(data));
two.replay.rows.push({{id: 30, type: 'doing', activity_id: 34, at: '2026-11-13 04:08:00', from_desk: 'builder', to_desks: [], from_state: 'idle', to_state: 'active', reason: 'tw_start', ended_at: null}});
const rep2 = R.collabReplay(R.base(two, {{rosters: ['Office'], range: '7d'}}, now), {{count: 300}});
const both = R.replayDoingSpans(rep2, now, 'desks').filter(s => s.desk === 'builder' && s.kind === 'doing');
const evAt = R.replayDoingEnd({{endedAt: 1000, endedBy: 'finished'}}, 2000);
const evOpen = R.replayDoingEnd({{}}, null);
const evEndedUnknown = R.replayDoingEnd({{ended: true, endedBy: 'cleared'}}, null);
console.log(JSON.stringify({{
  r31: find(atNow, 'run-31'), r32: find(atNow, 'run-32'), r33: find(atNow, 'run-33'),
  h4: find(atNow, 'tr-4'), h10: find(atNow, 'tr-10'),
  r32at10: find(at10, 'run-32'), h4at10: find(at10, 'tr-4'), r33at10: find(at10, 'run-33'),
  t: {{s31: T('04:05:00'), s32: T('04:07:00'), e32: T('04:16:00'), e33: T('04:24:00'), e4: T('04:18:00')}},
  actLanes: [...new Set(act.map(s => s.lane))].sort(),
  both: both.map(s => [s.key, s.open, s.rowIndex]),
  same, evAt, evOpen, evEndedUnknown
}}));
"""
    out = _node(script)
    t = out["t"]
    r31, r32, r33 = out["r31"], out["r32"], out["r33"]
    assert r31["start"] == t["s31"] and r31["open"] is True and r31["pos0"] == 0, "a run with no end row runs to the playhead"
    assert len(r31["shade"]) == 1 and r31["shade"][0][0] == 0, "its waiting stretch (tw_wait, still waiting) is shaded up to now"
    assert r32["ended"] is True and r32["how"] == "finished" and r32["end"] == t["e32"], "ended_at is the end"
    assert r33["ended"] is True and r33["how"] == "failed" and r33["end"] == t["e33"]
    assert out["r32at10"]["open"] is True and out["r32at10"]["how"] == "", "before the playhead reaches the end, the span is live"
    assert out["r33at10"] is None, "a later run has not started yet"
    h4, h10 = out["h4"], out["h10"]
    assert h4["kind"] == "hold" and h4["ended"] and h4["how"] == "drop" and h4["end"] == t["e4"] and h4["lane"] == "builder"
    assert h10["kind"] == "hold" and h10["open"] is True and h10["pos0"] == 0 and h10["lane"] == "gardener", "a promise still held runs to the playhead"
    assert out["h4at10"]["open"] is True
    assert out["actLanes"] == ["doing", "hold"]
    assert sorted(x[2] for x in out["both"]) == [0, 1] and all(x[1] for x in out["both"]), "runs overlap freely and stack"
    assert out["same"] is True
    assert out["evAt"] == {"end": 1000, "open": False, "how": "finished"}
    assert out["evOpen"] == {"end": None, "open": True, "how": ""}
    assert out["evEndedUnknown"] == {"end": None, "open": False, "how": "cleared"}, "ended with no time: no invented end"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "rd-rp-doing" in css and "rd-dir-tb .rd-rp-lapse" in css and "#rd .rd-rp-hold {" in css
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function drawDoingSpans" in app and "scaleY(" in app and "scaleX(" in app
    assert "rd-rp-playing" in app
    view = (RD / "rd-view.js").read_text(encoding="utf-8")
    assert '"ongoing"' in view and "rd-rp-tip-span" in view


def test_spans_recolor_by_outcome_with_a_short_settle_only_while_playing():
    css = (RD / "rd.css").read_text(encoding="utf-8")
    for how in ("finished", "failed", "stale", "cleared", "drop", "force", "expire"):
        hits = re.findall(rf"--rd-end-{how}:\s*(#[0-9a-fA-F]{{6}})", css)
        assert len(hits) == 1, how
        assert f'[data-end="{how}"]' in css, how + " recolors the whole bar"
    assert "#rd .rd-rp-playing .rd-rp-lapse { transition: background-color .3s" in css, "a short settle while playing"
    assert "#rd .rd-rp-lapse {" in css and "transition" not in css[css.index("#rd .rd-rp-lapse {"):css.index("#rd .rd-rp-hold {")], "paused or scrubbing: no motion"
    rm = css[css.index("@media (prefers-reduced-motion: reduce) {\n  #rd .rd-rp-playing .rd-rp-lapse"):]
    assert "transition: none" in rm[:200], "reduced motion just swaps the colour"
    for cap in ("rd-cap-lock", "rd-cap-drop", "rd-cap-force", "rd-cap-expire"):
        assert "#rd .rd-rp-cap." + cap in css, cap
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert 'el.setAttribute("data-end", end)' in app and '"rd-cap-lock"' in app and '"rd-cap-" + sp.how' in app
    assert not re.search(r"#[0-9a-fA-F]{6}", app)


def test_a_forced_promise_hands_on_only_when_the_row_names_the_other_desk():
    model = str(RD / "rd-model.js")
    rows = [
        {"id": 1, "type": "hold", "activity_id": 5, "at": "2026-11-13 04:00:00", "from_desk": "builder", "to_desks": [], "from_state": "free", "to_state": "held", "reason": "hold_grant"},
        {"id": 2, "type": "hold", "activity_id": 5, "at": "2026-11-13 04:10:00", "from_desk": "builder", "to_desks": ["validator"], "from_state": "held", "to_state": "free", "reason": "hold_force"},
        {"id": 3, "type": "hold", "activity_id": 5, "at": "2026-11-13 04:20:00", "from_desk": "validator", "to_desks": [], "from_state": "held", "to_state": "expired", "reason": "hold_expire"},
        {"id": 4, "type": "hold", "activity_id": 6, "at": "2026-11-13 04:05:00", "from_desk": "gardener", "to_desks": [], "from_state": "free", "to_state": "held", "reason": "hold_grant"},
        {"id": 5, "type": "hold", "activity_id": 6, "at": "2026-11-13 04:15:00", "from_desk": "gardener", "to_desks": [], "from_state": "held", "to_state": "free", "reason": "hold_force"},
        {"id": 6, "type": "hold", "activity_id": 6, "at": "2026-11-13 04:16:00", "from_desk": "gardener", "to_desks": [], "from_state": "held", "to_state": "held", "reason": "hold_refresh"},
    ]
    data = json.loads(json.dumps(OFFICE))
    data["replay"] = {"loaded": True, "more": False, "rows": rows, "oldest_id": 1, "newest_id": 6}
    script = f"""
require({model!r});
const R = WallRd;
const now = Date.parse('2026-11-13T04:40:00Z');
const rep = R.collabReplay(R.base({json.dumps(data)}, {{rosters: ['Office'], range: '7d'}}, now), {{count: 300}});
const spans = R.replayDoingSpans(rep, now, 'desks').map(s => [s.key, s.lane, s.how]);
const it = R.replayItemsAt(rep, now, 400, 'desks');
console.log(JSON.stringify({{spans, links: it.links.map(l => l.id), items: it.items.map(i => i.key),
  keys: rep.rows.map(r => r.key)}}));
"""
    out = _node(script)
    assert ["tr-1", "builder", "handoff"] in out["spans"], "the force that names the other desk ends one holder"
    assert ["tr-2", "validator", "expire"] in out["spans"], "and starts the next, which then expires"
    assert ["tr-4", "gardener", "force"] in out["spans"], "a force that names no other desk only ends the span"
    assert out["links"] == ["tr-2>builder>validator"], "one hand-off line, from the row's own edge"
    assert not out["items"], "held promises are spans, not ticks"
    assert "tr-6" not in out["keys"], "a refresh draws nothing"


def test_panning_the_window_keeps_connection_lines_for_in_window_transitions():
    got = run()
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
const now = {got['nowMs']};
const data = {json.dumps(OFFICE)};
const b = R.base(data, {{rosters: ['Office'], range: '7d'}}, now);
const live = R.collabReplay(b, {{count: 300}});
const liveLinks = R.replayItemsAt(live, live.until, 400, 'desks').links;
const end = Date.parse('2026-11-13T04:32:00Z');
const past = R.collabReplay(b, {{count: 100, end}});
const atEnd = R.replayItemsAt(past, past.until, 400, 'desks').links;
const mid = (past.since + past.until) / 2;
const atMid = R.replayItemsAt(past, mid, 400, 'desks').links;
console.log(JSON.stringify({{
  liveIds: liveLinks.map(l => l.id),
  livePos: Object.fromEntries(liveLinks.map(l => [l.id, l.pos])),
  pastKeys: past.rows.map(r => r.key),
  pastIds: atEnd.map(l => l.id),
  pastPos: Object.fromEntries(atEnd.map(l => [l.id, l.pos])),
  midIds: atMid.map(l => l.id)
}}));
"""
    out = _node(script)
    assert "tr-14>builder>validator" in out["liveIds"]
    assert out["livePos"]["tr-2>validator>builder"] > 0.08, "older in-window transitions still get a line"
    assert "tr-13>validator>builder" in out["liveIds"] and "tr-10>builder>gardener" in out["liveIds"]
    assert "tr-14" in out["pastKeys"] and "tr-2" in out["pastKeys"]
    assert "tr-14>builder>validator" in out["pastIds"], "after a pan, lines for transitions in the new window are present"
    assert "tr-2>validator>builder" in out["pastIds"]
    assert out["pastPos"]["tr-2>validator>builder"] > 0.08
    model_js = (RD / "rd-model.js").read_text(encoding="utf-8")
    assert "REPLAY_LINK_AGE" not in model_js


def test_in_window_lines_stay_visible_and_only_dim_slightly():
    """A line stays near full strength while its tick is in the window.

    The line is not drawn before the playhead reaches the activity, and
    age never fades it out: opacity stays at or above REPLAY_LINK_FADE.
    A hover on a tick or a line highlights that line.
    """
    got = run()
    model = str(RD / "rd-model.js")
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    css = (RD / "rd.css").read_text(encoding="utf-8")
    script = f"""
require({model!r});
const R = WallRd;
const now = {got['nowMs']};
const data = {json.dumps(OFFICE)};
const b = R.base(data, {{rosters: ['Office'], range: '7d'}}, now);
const live = R.collabReplay(b, {{count: 300}});
const floor = R.REPLAY_LINK_FADE;
const atEnd = R.replayItemsAt(live, live.until, 40, 'desks');
const midT = (live.since + live.until) / 2;
const atMid = R.replayItemsAt(live, midT, 40, 'desks');
const fades = atEnd.links.map(l => l.fade);
const midFades = atMid.links.map(l => l.fade);
const future = live.rows.filter(r => r.at > midT && r.flows.length).map(r => r.key);
const midKeys = atMid.links.map(l => l.key || l.id.split('>')[0]);
const far = atEnd.links.filter(l => l.pos >= 0.99);
console.log(JSON.stringify({{
  floor, fade0: R.replayLinkFade(0), fade1: R.replayLinkFade(1), fadeHalf: R.replayLinkFade(0.5),
  fadeBefore: R.replayLinkFade(-0.1), fadeAfter: R.replayLinkFade(1.1),
  endN: atEnd.links.length, endMin: fades.length ? Math.min(...fades) : null,
  midN: atMid.links.length, midMin: midFades.length ? Math.min(...midFades) : null,
  future, midKeys, farFades: far.map(l => [l.id, l.pos, l.fade]),
  mail: atEnd.links.find(l => l.id === 'tr-14>builder>validator')
}}));
"""
    out = _node(script)
    assert out["floor"] == 0.7
    assert out["fade0"] == 1
    assert out["fade1"] >= out["floor"]
    assert out["fadeHalf"] >= out["floor"]
    assert out["fadeBefore"] == 0 and out["fadeAfter"] == 0
    assert out["endN"] and out["endMin"] >= out["floor"]
    assert out["midN"] and out["midMin"] >= out["floor"]
    assert out["mail"] and out["mail"]["fade"] >= out["floor"]
    for key in out["future"]:
        assert key not in out["midKeys"], "a line is not drawn before its activity"
    assert "function applyLinkHot" in app and "function linkKeysOf" in app
    assert 'data-rp-tip="link"' in app and "rd-rp-hit" in app
    assert "#rd .rd-rp-links.is-hot" in css and "path.is-hot" in css


def test_time_scale_collapses_empty_voids_and_keeps_doing_spans():
    """A quiet gap longer than the threshold collapses; a doing-covered gap does not.

    The map is monotonic and inverts on the display axis. Playback crosses a
    void faster than the same stretch of active time. In-window lines still
    stay at or above the fade floor.
    """
    model = str(RD / "rd-model.js")
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    css = (RD / "rd.css").read_text(encoding="utf-8")
    got = run()
    script = f"""
require({model!r});
const R = WallRd;
const lo = 0, hi = 10000;
const rows = [{{at:0}},{{at:1000}},{{at:9000}},{{at:10000}}];
const sc = R.timeScale(rows, [], lo, hi, {{threshold: 2000, mark: 200}});
const covered = R.timeScale([{{at:0}},{{at:10000}}], [{{start:500,end:9000}}], lo, hi, {{threshold: 2000, mark: 200}});
let mono = true;
for (let t = 0; t < 10000; t += 50) if (sc.toPos(t + 50) + 1e-9 < sc.toPos(t)) mono = false;
let inv = true;
for (let p = 0; p <= 1; p += 0.01) if (Math.abs(sc.toPos(sc.toTime(p)) - p) > 1e-9) inv = false;
let act = true;
[0, 500, 1000, 9000, 9500, 10000].forEach(t => {{ if (Math.abs(sc.toTime(sc.toPos(t)) - t) > 1e-6) act = false; }});
const voidW = sc.toPos(9000) - sc.toPos(1000);
const voidWall = voidW * R.REPLAY_PLAY_MS;
const activeWall = (sc.toPos(1000) - sc.toPos(0)) * R.REPLAY_PLAY_MS;
const through = R.replayPlayhead(sc, 0, voidWall + activeWall, 1);
const data = {json.dumps(OFFICE)};
const now = {got['nowMs']};
const b = R.base(data, {{rosters: ['Office'], range: '7d'}}, now);
const live = R.collabReplay(b, {{count: 300}});
const scale = R.replayScale(live);
const atEnd = R.replayItemsAt(live, live.until, 400, 'desks');
const mail = atEnd.links.find(l => l.id === 'tr-14>builder>validator');
const fades = atEnd.links.map(l => l.fade);
const when = 1700000000000, t0 = when - 6 * 3600000, t1 = when - 30 * 60000;
function iso(ms) {{ return new Date(ms).toISOString().replace("T", " ").replace("Z", "").slice(0, 19); }}
function rr(id, type, aid, ms, from, to, fs, ts, reason, endedMs) {{ return {{id, type, activity_id: aid, at: iso(ms), from_desk: from, to_desks: to, from_state: fs, to_state: ts, reason, ended_at: endedMs ? iso(endedMs) : null}}; }}
const gapData = {{
  agents: {{Office: [{{owner: "builder", alive: true, stale: false, heartbeat: iso(when - 60000)}}]}},
  doing: {{}}, rosterList: [{{name: "Office", desks: 1}}], todos: {{Office: {{needs: []}}}},
  holds: {{Office: []}}, mail: {{Office: []}},
  labels: {{Office: {{rows: [], checks: {{}}}}}}, trees: {{Office: []}}, rooms: {{Office: []}},
  replay: {{loaded: true, more: false, oldest_id: 1, newest_id: 3, rows: [
    rr(1, "doing", 1, t0, "builder", [], "idle", "active", "tw_start"),
    rr(2, "doing", 1, t0 + 60000, "builder", [], "active", "finished", "tw_finish", t0 + 60000),
    rr(3, "todo", 4, t1, "builder", [], "open", "claimed", "claim")
  ]}}
}};
const gapB = R.base(gapData, {{rosters: ["Office"], range: "7d"}}, when);
const gapRep = R.collabReplay(gapB, {{count: 300}});
const focus = (gapRep.pool || []).find(r => r.key === "run-1");
const gapScale = R.replayScale(gapRep);
const ruler = R.replayRulerTimes(gapScale, gapRep.until);
const rulerInVoid = (gapScale.breaks || []).some(br => ruler.some(tk => tk.at >= br.start && tk.at <= br.end));
console.log(JSON.stringify({{
  breaks: sc.breaks.length, skip: sc.breaks[0] && sc.breaks[0].skip, display: sc.display,
  coveredN: covered.breaks.length, coveredDisplay: covered.display,
  mono, inv, act, voidW, voidWall, activeWall, through,
  officeBreaks: (scale && scale.breaks || []).length,
  mailId: mail && mail.id, mailFade: mail && mail.fade, fadeMin: fades.length ? Math.min(...fades) : null,
  floor: R.REPLAY_LINK_FADE,
  endedAt: focus && focus.endedAt, ended: focus && focus.ended,
  gapBreaks: (gapScale && gapScale.breaks || []).length,
  gapSkip: gapScale && gapScale.breaks[0] && gapScale.breaks[0].skip,
  rulerInVoid: rulerInVoid
}}));
"""
    out = _node(script)
    assert out["breaks"] == 1 and out["skip"] == 8000
    assert out["display"] == 2200
    assert out["coveredN"] == 0 and out["coveredDisplay"] == 10000
    assert out["mono"] and out["inv"] and out["act"]
    assert out["voidW"] < 0.2, "the void is a short fixed band, not 80% of the axis"
    assert out["voidWall"] < out["activeWall"], "playback crosses the void faster than 1s of active time"
    assert abs(out["through"] - 9000) < 1
    assert out["officeBreaks"] == 0, "the short office fixture has no void to collapse"
    assert out["mailId"] == "tr-14>builder>validator"
    assert out["fadeMin"] >= out["floor"] and out["mailFade"] >= out["floor"]
    assert out["ended"] and out["endedAt"] == 1700000000000 - 6 * 3600000 + 60000
    assert out["gapBreaks"] >= 1 and out["gapSkip"] > 3 * 3600000
    assert not out["rulerInVoid"]
    assert "function timeScale" in (RD / "rd-model.js").read_text(encoding="utf-8")
    assert "function drawRuler" in app and "function rpNow" in app
    assert "replayPlayhead" in app
    assert "#rd .rd-rp-ruler" in css and "#rd .rd-rp-void" in css and "#rd .rd-rp-rlabel" in css
    assert "#rd .rd-rp-links.is-hot" in css

def test_stale_doing_does_not_cover_idle_tail_or_drop_lines():
    """A leftover doing on a stale desk ends at last-seen, so the idle tail collapses.

    A desk that is still working keeps its open span to now, and that gap
    does not collapse. In-window mail lines stay at or above the fade floor
    after the stale desk's window is scaled.
    """
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
function iso(ms) {{ return new Date(ms).toISOString().replace("T", " ").replace("Z", "").slice(0, 19); }}
const now = Date.parse("2026-11-13T08:00:00Z");
const t0 = now - 8 * 3600000, tMail = t0 + 60000, seen = t0 + 30 * 60000;
function rr(id, type, aid, ms, from, to, fs, ts, reason, endedMs) {{ return {{id, type, activity_id: aid, at: iso(ms), from_desk: from, to_desks: to, from_state: fs, to_state: ts, reason, ended_at: endedMs ? iso(endedMs) : null}}; }}
const stale = {{
  agents: {{Office: [
    {{owner: "builder", alive: false, stale: true, heartbeat: iso(seen)}},
    {{owner: "validator", alive: true, stale: false, heartbeat: iso(now - 60000)}}
  ]}},
  doing: {{builder: {{n: 1, doings: [{{id: 1, created: new Date(t0).toISOString(), text: "leftover work", state: "active", state_at: new Date(t0).toISOString(), card: null}}]}}}},
  rosterList: [{{name: "Office", desks: 2}}],
  todos: {{Office: {{needs: []}}}}, holds: {{Office: []}}, mail: {{Office: []}},
  labels: {{Office: {{rows: [], checks: {{}}}}}}, trees: {{Office: []}}, rooms: {{Office: []}},
  replay: {{loaded: true, more: false, oldest_id: 1, newest_id: 2, rows: [
    rr(1, "doing", 1, t0, "builder", [], "idle", "active", "tw_start"),
    rr(2, "mail", 200, tMail, "builder", ["validator"], "none", "live", "send_or_queue")
  ]}}
}};
const liveDoing = JSON.parse(JSON.stringify(stale));
liveDoing.agents.Office[0] = {{owner: "builder", alive: true, stale: false, heartbeat: iso(now - 60000)}};
const bStale = R.base(stale, {{rosters: ["Office"], range: "7d"}}, now);
const bLive = R.base(liveDoing, {{rosters: ["Office"], range: "7d"}}, now);
const staleRep = R.collabReplay(bStale, {{count: 300}});
const liveRep = R.collabReplay(bLive, {{count: 300}});
const staleScale = R.replayScale(staleRep);
const liveScale = R.replayScale(liveRep);
const iv = R.replayDoingIntervals(staleRep, staleRep.until);
const liv = R.replayDoingIntervals(liveRep, liveRep.until);
const at = R.replayItemsAt(staleRep, staleRep.until, 400, "desks");
const mail = at.links.find(l => l.id === "tr-2>builder>validator");
const fades = at.links.map(l => l.fade);
console.log(JSON.stringify({{
  staleBreaks: (staleScale && staleScale.breaks || []).length,
  staleSkip: staleScale && staleScale.breaks[0] && staleScale.breaks[0].skip,
  liveBreaks: (liveScale && liveScale.breaks || []).length,
  staleIvEnd: iv[0] && iv[0].end, staleIvOpen: iv[0] && iv[0].open, seen: seen,
  liveIvOpen: liv[0] && liv[0].open, liveIvEnd: liv[0] && liv[0].end, now: now,
  close: staleRep.doingClose && staleRep.doingClose.builder,
  mailId: mail && mail.id, mailFade: mail && mail.fade,
  fadeMin: fades.length ? Math.min(...fades) : null, floor: R.REPLAY_LINK_FADE,
  desk: bStale.byName && bStale.byName.builder && {{
    connected: bStale.byName.builder.connected, doing: bStale.byName.builder.doing,
    stale: bStale.byName.builder.stale, lastSeenAt: bStale.byName.builder.lastSeenAt
  }}
}}));
"""
    out = _node(script)
    assert out["desk"]["stale"] and not out["desk"]["connected"]
    assert out["close"] == out["seen"]
    assert out["staleIvEnd"] == out["seen"] and out["staleIvOpen"] is False
    assert out["staleBreaks"] >= 1 and out["staleSkip"] > 6 * 3600000
    assert out["liveBreaks"] == 0
    assert out["liveIvOpen"] is True and out["liveIvEnd"] == out["now"]
    assert out["mailId"] == "tr-2>builder>validator"
    assert out["fadeMin"] >= out["floor"] and out["mailFade"] >= out["floor"]

def test_labels_request_uses_office_and_failure_is_not_fatal():
    """Labels are office-wide, so the Wall asks project=Office, not the focused roster.

    A 400 or a dropped read must not throw, and must be remembered so the
    next paint does not keep retrying.
    """
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "function partRoster" in app
    assert 'kind === "labels" ? "Office"' in app
    assert 'kind === "labels"' in app and "gotAt[key] = Date.now()" in app
    assert "A 400 or a dropped read must not block the tab" in app

def test_stale_doing_last_run_does_not_cover_a_later_quiet_gap():
    """A leftover doing stops at the last run of work, not at a later last-seen.

    When last-seen is days after the last activity on that desk, the quiet
    stretch in between collapses, and mail in the later cluster keeps its
    line. A last-seen still inside the grace stays on the run, as in the
    earlier stale-doing case.
    """
    model = str(RD / "rd-model.js")
    script = f"""
require({model!r});
const R = WallRd;
function iso(ms) {{ return new Date(ms).toISOString().replace("T", " ").replace("Z", "").slice(0, 19); }}
const now = Date.parse("2026-11-13T08:00:00Z");
const t0 = now - 5 * 86400000, tMail0 = t0 + 60000, tMail1 = now - 12 * 3600000, seen = now - 60000;
function rr(id, type, aid, ms, from, to, fs, ts, reason, endedMs) {{ return {{id, type, activity_id: aid, at: iso(ms), from_desk: from, to_desks: to, from_state: fs, to_state: ts, reason, ended_at: endedMs ? iso(endedMs) : null}}; }}
const data = {{
  agents: {{Office: [
    {{owner: "builder", alive: false, stale: true, heartbeat: iso(seen)}},
    {{owner: "validator", alive: true, stale: false, heartbeat: iso(now - 60000)}}
  ]}},
  doing: {{builder: {{n: 2, doings: []}}}},
  rosterList: [{{name: "Office", desks: 2}}],
  todos: {{Office: {{needs: []}}}}, holds: {{Office: []}}, mail: {{Office: []}},
  labels: {{Office: {{rows: [], checks: {{}}}}}}, trees: {{Office: []}}, rooms: {{Office: []}},
  replay: {{loaded: true, more: false, oldest_id: 1, newest_id: 5, rows: [
    rr(1, "todo", 9, t0, "validator", [], "none", "open", "create"),
    rr(2, "doing", 1, t0, "builder", [], "idle", "active", "tw_start"),
    rr(3, "mail", 200, tMail0, "builder", ["validator"], "none", "live", "send_or_queue"),
    rr(4, "mail", 201, tMail1, "builder", ["validator"], "none", "live", "send_or_queue"),
    rr(5, "doing", 2, now - 3600000, "builder", [], "idle", "active", "tw_start")
  ]}}
}};
const b = R.base(data, {{rosters: ["Office"], range: "7d"}}, now);
const rep = R.collabReplay(b, {{count: 300}});
const scale = R.replayScale(rep);
const iv = R.replayDoingIntervals(rep, rep.until);
const at = R.replayItemsAt(rep, rep.until, 400, "desks");
const early = at.links.find(l => l.id === "tr-3>builder>validator");
const late = at.links.find(l => l.id === "tr-4>builder>validator");
const skip = (scale && scale.breaks || []).reduce((s, br) => s + (br.skip || 0), 0);
console.log(JSON.stringify({{
  since: rep.since, until: rep.until, t0: t0, tMail0: tMail0, tMail1: tMail1, seen: seen,
  grace: R.REPLAY_DOING_GRACE_MS,
  nIv: iv.length, ivEnd: iv[0] && iv[0].end, ivOpen: iv[0] && iv[0].open, ivHow: iv[0] && iv[0].how, laterStart: iv[1] && iv[1].start,
  breaks: (scale && scale.breaks || []).length, skip: skip,
  earlyId: early && early.id, lateId: late && late.id,
  earlyPos: early && early.pos, latePos: late && late.pos,
  fadeMin: at.links.length ? Math.min(...at.links.map(l => l.fade)) : null,
  floor: R.REPLAY_LINK_FADE
}}));
"""
    out = _node(script)
    assert out["ivEnd"] == out["tMail0"]
    assert out["ivOpen"] is False
    assert out["breaks"] >= 1
    assert out["skip"] > 3 * 86400000
    assert out["earlyId"] and out["lateId"]
    assert out["fadeMin"] >= out["floor"]
    assert out["latePos"] is not None and out["earlyPos"] is not None
    assert abs(out["latePos"] - out["earlyPos"]) > 0.2
