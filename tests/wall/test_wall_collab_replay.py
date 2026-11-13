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
OFFICE = {
    "agents": {"Office": [
        {"owner": "builder", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
        {"owner": "validator", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
        {"owner": "gardener", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
    ]},
    "doing": {"builder": {"owner": "builder", "alive": True, "stale": False, "doing": "wiring", "on": "todo-7",
                        "waiting_on_it": {"cards": {"newest": [{"id": "todo-7", "watchers": ["validator", "gardener"], "roster": "Office"}]}}}},
    "rosterList": [{"name": "Office", "desks": 3}],
    "todos": {"Office": {"needs": [{"id": 7, "status": "shipped", "detail": "Stations route", "assigned": "builder", "creator": "validator"}]}},
    "holds": {"Office": [{"id": 3, "resource": "docs-lock", "owner": "gardener"}]},
    "scores": {"Office": [{"id": 40, "kpi": "mill-desk.hint_drop", "owner": "builder", "value": "2", "target": "0"}]},
    "mail": {"Office": [
        {"id": 100, "created": "2026-11-13 04:30:00", "from": "builder", "body": "re-measure #450\nmore",
         "mail_tos": [{"deskId": "validator", "receipt": 1}], "tree": "r-450"},
        {"id": 101, "created": "2026-11-13 04:31:00", "from": "builder", "body": "ping", "mail_tos": [{"deskId": "scout", "receipt": 0}],
         "tree": "r-ping", "root_id": 90},
        {"id": 102, "created": "2026-11-13 04:32:00", "from": "scout", "body": "outside only", "mail_tos": [{"deskId": "auditor", "receipt": 0}]},
    ]},
    "events": {"Office": [
        {"id": 7, "kind": "todo", "at": "2026-11-13 04:20:00", "owner": "builder", "roster_id": "Office"},
        {"id": 3, "kind": "hold", "at": "2026-11-13 04:25:00", "owner": "gardener", "roster_id": "Office"},
        {"id": 9, "kind": "wake", "at": "2026-11-13 04:26:00", "owner": "System", "roster_id": "Office"},
        {"id": 40, "kind": "score", "at": "2026-11-13 04:27:00", "owner": "builder", "roster_id": "Office"},
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
    "moves": {"todo-7": [
        {"id": 1, "desk": "validator", "at": "2026-11-13 04:00:00", "on": "todo-7", "act": "create"},
        {"id": 2, "desk": "builder", "at": "2026-11-13 04:10:00", "on": "todo-7", "act": "claim"},
        {"id": 3, "desk": "builder", "at": "2026-11-13 04:20:00", "on": "todo-7", "act": "ship", "peer": "validator"},
    ]},
    "trail": {"builder": [
        {"id": 50, "desk": "builder", "at": "2026-11-13 04:05:00", "doing": "wiring the route", "on": "todo-7", "act": "focus"},
        {"id": 51, "desk": "builder", "at": "2026-11-13 04:33:00", "doing": "asked for a re-measure", "on": "mail-100", "act": "focus",
         "waiting_on": {"on": "desk-validator", "why": "re-measure of #450"}},
    ], "validator": [
        {"id": 60, "desk": "validator", "at": "2026-11-13 04:28:00", "doing": "waiting for the lock", "on": "todo-7", "act": "focus",
         "waiting_on": {"on": "hold-3", "why": "docs"}},
    ]},
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
      mail: V.replayTip(by['mail-100'], now),
      todo: V.replayTip(by['move-2'], now),
      doing: V.replayTip(by['focus-50'], now),
      wake: V.replayTip(by['act-wake-9'], now),
      score: V.replayTip(by['act-score-40'], now),
      hold: V.replayTip(by['act-hold-3'], now),
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
    return V.replayOverflowTip([by['mail-100'], by['mail-101']].filter(Boolean), now);
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
    assert "builder mailed validator re-measure #450 opened" in rows["mail-100"]["text"]
    assert "builder claimed card 7" in rows["move-2"]["text"]
    assert "builder shipped card 7 for validator CLAIMED" in rows["move-3"]["text"] and "SHIPPED" in rows["move-3"]["text"]
    assert "validator filed card 7" in rows["move-1"]["text"]
    assert "validator is waiting for docs-lock held by gardener" in rows["focus-60"]["text"]
    assert rows["focus-60"]["kind"] == "hold" and rows["focus-60"]["act"] == "wait"
    assert "the office sent a wake" in rows["act-wake-9"]["text"]
    assert "builder score Dropped hints now 2 / 0" in rows["act-score-40"]["text"]
    assert 'rd-sdot off' in rows["act-score-40"]["html"]
    assert "builder is waiting on validator letter 100 re-measure of #450" in rows["focus-51"]["text"]
    assert "builder started card 7 wiring the route" in rows["focus-50"]["text"]
    for r in rows.values():
        assert not re.search(r"\b(desk_id|roster_id|waiting_on|act=|kind=)\b", r["text"]), r["text"]
        assert 'class="rd-ki k-' + r["kind"] + '"' in r["html"]


def test_a_card_move_stands_in_for_its_activity_row():
    keys = set(by_key(run()))
    assert "act-todo-7" not in keys, "the move rows of card 7 replace its activity row"
    assert "act-hold-3" in keys, "a promise with no move rows keeps its activity row"


def test_scope_keeps_rows_touching_the_focused_desks_and_clouds_the_rest():
    rows = by_key(run({"only": ["builder"]}))
    assert "mail-102" not in rows, "a letter with no focused desk on either side is not shown"
    assert "focus-60" not in rows
    letter = rows["mail-100"]
    assert "outside" in letter["text"] and "validator" not in letter["text"].replace("title", "")
    assert 'class="rd-cloud"' in letter["html"] and "outside this scope: validator" in letter["html"]
    assert 'data-rd-desk="builder"' in letter["html"]
    out = by_key(run())["mail-101"]
    assert "outside" in out["text"], "a desk off the roster is a cloud"


def test_the_window_is_a_row_count_defaulting_to_300():
    got = run()
    assert got["counts"] == [100, 300, 1000] and got["defaultCount"] == 300
    assert got["count"] == 300
    assert run(count="100")["count"] == 100
    assert run(count="1000")["count"] == 1000
    assert run(count="auto")["count"] == 300, "an unknown pick falls back to 300"
    assert got["at"][0] == "focus-51", "newest first at the playhead"
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
    assert not any(".rd-rp-bar { order: 2" in ln for ln in fs), "controls stay on top in full screen"
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
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "cursor: grab;" in css and "cursor: grabbing;" in css


def test_stage_lanes_follow_the_pick_with_the_cloud_pinned_last():
    got = run()
    assert got["lanes"][0] == "@office", "rows no desk sent (a wake) get the office lane"
    assert got["lanes"][-1] == "@out", "outside sits at the end"
    assert {"builder", "validator", "gardener"} <= set(got["lanes"])
    shell = got["shell"]
    for lane in got["lanes"]:
        assert f'data-lane="{lane}"' in shell and f'data-col="{lane}"' in shell
    rain = shell[shell.index('data-rp-rain="1">'):shell.index('data-rp-field="desks"')]
    assert "rd-rp-item" not in rain, "the field starts empty; items are placed by the playhead"


def test_pickup_is_read_from_the_records_per_kind():
    fl = run()["flows"]
    assert fl["mail-100"] == [["builder", "validator", 0]], "read with no later row: picked up on arrival"
    assert fl["mail-101"] == [["builder", "@out", None]], "unread: waits in the receiver's column"
    assert fl["move-3"] == [["builder", "validator", None]], "shipped for the desk the row names: waits for its next move"
    assert fl["focus-60"] == [["gardener", "validator", None]], "a contested promise waits until the waiter takes it"
    got = run()
    assert got["waitingNow"].get("@out") or got["waitingNow"].get("validator")
    assert any(x["wait"] and x["item"] == "hold-3" for x in got["locksNow"]["validator"])
    assert any(not x["wait"] and x["text"] == "docs-lock" for x in got["locksNow"]["gardener"]), "at now the holds table says who holds"
    assert any(x["wait"] for x in got["locksPast"]["validator"])


def test_desk_pills_stay_fixed():
    got = run()
    desks = [l for l in got["lanes"] if not l.startswith("@")]
    assert desks == ["builder", "validator", "gardener"], "the DESKS list order, not a layout that moves"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "replayLayout" not in app and "placeLanes" not in app, "no gravity: pills never move"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "--lane-pitch" in css
    assert "grid-template-rows: repeat(var(--lanes, 1), var(--lane-pitch))" in css


def test_activity_view_is_six_kind_lanes_of_the_same_instances():
    got = run()
    act = got["activity"]
    assert got["kinds"] == ["mail", "todo", "hold", "wake", "doing", "score"]
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
    assert "mail-100" not in p["keys"] and "focus-50" in p["keys"], "the window re-scopes: rows after its end are out"
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
    assert "ev.shiftKey" in app and "PAN_PX" in app and "onVp" in app
    assert "rpJump" in app and "!d.moved && n === \"pointerup\"" in app


def test_the_record_is_cached_and_only_gaps_are_read():
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "&page=1" in app and '"&page=" + page' in app, "the tail is page 1; older pages only on a pan"
    assert "sessionStorage" in app and "TRAIL_KEEP" in app and "TRAIL_LRU" in app, "kept across reloads, capped, least recent desk dropped"
    assert "c.byId[r.id]" in app, "rows merge by id, so shifting pages never duplicate"


def test_every_activity_carries_its_labels_and_trees():
    got = run()
    rows = {r["key"]: r for r in got["rows"]}
    card = rows["move-2"]["tags"]
    assert [l["name"] for l in card["labels"]] == ["validator"], "joined from the labels rows by type and id"
    assert card["trees"] == [{"name": "stations", "kind": "tree", "depth": 1, "root": "Stations epic", "rootKey": "todo-5", "hidden": False}]
    assert card["watchers"] == ["validator", "gardener"], "watchers from the doing feed's card lists"
    assert card["roster"] == "Office"
    assert rows["focus-50"]["tags"] == card, "a focus on the card carries the card's tags"
    mail = rows["mail-100"]["tags"]
    assert [l["name"] for l in mail["labels"]] == ["builder"]
    assert [(t["name"], t["root"]) for t in mail["trees"]] == [("r-450", "re-measure #450")]
    ping = rows["mail-101"]["tags"]
    assert ping["labels"] == [] and ping["trees"][0]["name"] == "r-ping" and ping["trees"][0]["rootKey"] == "mail-90", "the letter's own room"
    for key, r in rows.items():
        if r["kind"] in ("hold", "wake", "score"):
            t = r["tags"]
            assert t is None or (t["labels"] == [] and t["trees"] == [] and t["watchers"] == []), key + ": no labels, trees or watchers in the data, so none are drawn"
    assert rows["move-2"]["html"].count("rd-tag-r") == 1 and 'title="roster Office"' in rows["move-2"]["html"]
    assert 'title="watched by gardener"' in rows["move-2"]["html"]
    html = rows["move-2"]["html"]
    assert 'class="rd-tag rd-tag-l" title="label validator, position 1">validator<' in html
    assert 'class="rd-tag rd-tag-t" title="card tree stations, 1 deep: Stations epic"' in html
    assert "label gardener" not in html, "a label on another card is not this card's"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "firstTag(tags)" in app and "V.tagsHtml(one, 1)" in app, "the desk-view icons carry one chip; the rest is on hover"
    assert '"labels", "trees", "rooms"' in app


def test_links_come_only_from_two_desk_transition_rows():
    got = run()
    flows = got["flows"]
    assert flows["move-3"][0][:2] == ["builder", "validator"], "the ship row names its second desk: that is the link"
    assert "move-2" not in flows, "a claim row with no second desk draws no link"
    assert flows.get("mail-100") and flows["mail-100"][0][:2] == ["builder", "validator"], "a letter links sender and recipient"
    model = (RD / "rd-model.js").read_text(encoding="utf-8")
    assert "card.creator !== desk) peers.push" not in model and "card.desk !== desk) peers.push" not in model


STATE_SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
const R = WallRd, cases = JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(e => R.stateDesks(Object.assign({peers: []}, e)))));
"""


def state_of(*events):
    out = subprocess.run([NODE, "-e", STATE_SCRIPT, str(RD), json.dumps(list(events))], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_state_desks_per_kind():
    todo = state_of(
        {"kind": "todo", "act": "claim", "actor": "builder", "vol": "builder", "prevVol": ""},
        {"kind": "todo", "act": "claim", "actor": "builder", "vol": "builder", "prevVol": "gardener"},
        {"kind": "todo", "act": "unclaim", "actor": "builder", "vol": "", "prevVol": "builder"},
        {"kind": "todo", "act": "ship", "actor": "builder", "vol": "builder", "prevVol": "builder"},
        {"kind": "todo", "act": "assign", "actor": "builder", "vol": "", "prevVol": "", "rowPeer": "validator", "dir": "out"},
    )
    assert todo[0] == {"holders": ["builder"], "from": [], "waiting": []}, "a claim: the claimer has it"
    assert todo[1]["from"] == ["gardener"], "a claim handoff moves it from the earlier claimer"
    assert todo[2] == {"holders": [], "from": ["builder"], "waiting": []}
    assert todo[3] == {"holders": ["builder"], "from": [], "waiting": []}, "a ship keeps it on its claimer: no link"
    assert todo[4] == {"holders": ["validator"], "from": ["builder"], "waiting": []}, "the row's own second desk"
    mail = state_of({"kind": "mail", "actor": "builder", "peers": ["validator", "auditor", "builder"]})[0]
    assert mail == {"holders": ["validator", "auditor"], "from": ["builder"], "waiting": []}
    hold = state_of(
        {"kind": "hold", "act": "hold", "actor": "gardener", "prevHolder": "builder"},
        {"kind": "hold", "act": "hold", "actor": "gardener", "prevHolder": ""},
        {"kind": "hold", "act": "drop", "actor": "gardener"},
        {"kind": "hold", "act": "wait", "actor": "validator", "peers": ["gardener"]},
    )
    assert hold[0]["from"] == ["builder"] and hold[0]["holders"] == ["gardener"], "release then take by another desk"
    assert hold[1]["from"] == []
    assert hold[2] == {"holders": [], "from": ["gardener"], "waiting": []}
    assert hold[3] == {"holders": ["gardener"], "from": [], "waiting": ["validator"]}, "contention: holder and waiter"
    wake, wake2, doing, score = state_of(
        {"kind": "wake", "actor": "", "office": True},
        {"kind": "wake", "woken": "builder", "waker": "validator"},
        {"kind": "doing", "act": "wait", "actor": "builder", "peers": ["validator"]},
        {"kind": "score", "actor": "builder"},
    )
    assert wake == {"holders": [], "from": [], "waiting": []}, "the activity row names no woken desk today"
    assert wake2 == {"holders": ["builder"], "from": ["validator"], "waiting": []}, "ready for a row that names them"
    assert doing == {"holders": ["builder"], "from": [], "waiting": []}, "doing is who is doing it; a wait is not a transfer"
    assert score == {"holders": ["builder"], "from": [], "waiting": []}


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
    for k in kinds:
        assert f'class="k-{k}"' in act, "bar or legend named for " + k
        assert f"rd-pill rd-kind k-{k}" in act
        assert f'class="rd-ki k-{k}"' in desks
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert 'rd-rp-dchip k-" + it.kind' in app and 'k-" + kind' in app
    # no second hex palette for kinds in the javascript
    assert not re.search(r"#[0-9a-fA-F]{6}", app)

def test_hover_shows_one_shared_details_card():
    got = run()
    mail, todo, doing, wake, score, hold = (got["tips"][k] for k in ("mail", "todo", "doing", "wake", "score", "hold"))
    # kind row with a colour swatch, then title, local time and relative age
    assert 'class="rd-rp-tip-k k-mail"' in mail and 'class="rd-rp-swatch"' in mail and ">mail</div>" in mail
    assert "re-measure #450" in mail
    assert "<time>" in mail and "ago" in mail
    assert "sender builder" in mail and "receiver validator" in mail
    assert "rd-tag-l" in mail and "builder" in mail  # label
    assert "rd-tag-t" in mail  # mail room
    assert 'class="rd-rp-tip-k k-todo"' in todo and "Stations route" in todo
    assert "claimer builder" in todo
    assert "rd-tag-l" in todo and "rd-tag-t" in todo and "rd-tag-w" in todo and "rd-tag-r" in todo
    assert 'class="rd-rp-tip-k k-doing"' in doing and "wiring the route" in doing and "doing builder" in doing
    assert 'class="rd-rp-tip-k k-wake"' in wake
    assert 'class="rd-rp-tip-k k-score"' in score and "score builder" in score
    assert 'class="rd-rp-tip-k k-hold"' in hold and "holder gardener" in hold
    assert "3 in the window" in got["tips"]["lane"] and "builder" in got["tips"]["lane"]
    assert 'class="rd-rp-tip-k k-mail"' in got["tips"]["kind"] and "1 in the window" in got["tips"]["kind"] and 'class="rd-rp-swatch"' in got["tips"]["kind"]
    assert "0 in the window" in got["tips"]["empty"]
    # one shared popup in the shell, reused for every item
    for html in (got["shell"], got["activity"]):
        assert html.count('id="rd-rp-tip"') == 1
        assert 'role="tooltip"' in html and "rd-rp-tip" in html
        assert 'data-rp-tip="lane"' in html
    assert got["activity"].count('data-rp-tip="lane"') == 6, "each activity-type pill is hoverable"
    assert 'data-rd-desk="builder"' in got["shell"] and 'data-rp-tip="lane"' in got["shell"]
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "#rd .rd-rp-tip { position: fixed;" in css
    assert "#rd .rd-rp-tip { " in css and "pointer-events: none;" in css
    assert "#rd .rd-rp-swatch" in css
    for k in ("mail", "todo", "hold", "wake", "doing", "score"):
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

