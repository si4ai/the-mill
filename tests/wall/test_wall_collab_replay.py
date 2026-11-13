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
    "doing": {"builder": {"owner": "builder", "alive": True, "stale": False, "doing": "wiring", "on": "todo-7"}},
    "rosterList": [{"name": "Office", "desks": 3}],
    "todos": {"Office": {"needs": [{"id": 7, "status": "shipped", "detail": "Stations route", "assigned": "builder", "creator": "validator"}]}},
    "holds": {"Office": [{"id": 3, "resource": "docs-lock", "owner": "gardener"}]},
    "scores": {"Office": [{"id": 40, "kpi": "mill-desk.hint_drop", "owner": "builder", "value": "2", "target": "0"}]},
    "mail": {"Office": [
        {"id": 100, "created": "2026-11-13 04:30:00", "from": "builder", "body": "re-measure #450\nmore",
         "mail_tos": [{"deskId": "validator", "receipt": 1}]},
        {"id": 101, "created": "2026-11-13 04:31:00", "from": "builder", "body": "ping", "mail_tos": [{"deskId": "scout", "receipt": 0}]},
        {"id": 102, "created": "2026-11-13 04:32:00", "from": "scout", "body": "outside only", "mail_tos": [{"deskId": "auditor", "receipt": 0}]},
    ]},
    "events": {"Office": [
        {"id": 7, "kind": "todo", "at": "2026-11-13 04:20:00", "owner": "builder", "roster_id": "Office"},
        {"id": 3, "kind": "hold", "at": "2026-11-13 04:25:00", "owner": "gardener", "roster_id": "Office"},
        {"id": 9, "kind": "wake", "at": "2026-11-13 04:26:00", "owner": "System", "roster_id": "Office"},
        {"id": 40, "kind": "score", "at": "2026-11-13 04:27:00", "owner": "builder", "roster_id": "Office"},
    ]},
    "moves": {"todo-7": [
        {"id": 1, "desk": "validator", "at": "2026-11-13 04:00:00", "on": "todo-7", "act": "create"},
        {"id": 2, "desk": "builder", "at": "2026-11-13 04:10:00", "on": "todo-7", "act": "claim"},
        {"id": 3, "desk": "builder", "at": "2026-11-13 04:20:00", "on": "todo-7", "act": "ship"},
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
const win = process.argv[5];
const R = WallRd, V = WallRdView;
const b = R.base(data, Object.assign({rosters: ['Office'], range: '7d'}, sc), now);
const rep = R.collabReplay(b, {window: win});
const txt = h => h.replace(/<[^>]+>/g, ' ').replace(/&[a-z#0-9]+;/g, ' ').replace(/\s+/g, ' ').trim();
console.log(JSON.stringify({
  window: rep.window, want: rep.want, counts: rep.counts,
  rows: rep.rows.map(r => ({key: r.key, kind: r.kind, act: r.act, text: txt(V.replayRows([r])), html: V.replayRows([r])})),
  at: R.replayAt(rep, now, 3).map(r => r.key),
  playMs: R.REPLAY_PLAY_MS, speeds: R.REPLAY_SPEEDS,
  rate: V.speedText(rep.window, 1), rateSlow: V.speedText('week', 0.25),
  stateBefore: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:01:00Z')),
  stateWorking: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:06:00Z')),
  stateWaiting: R.replayStateAt(rep, 'builder', Date.parse('2026-11-13T04:34:00Z')),
  shell: V.replay(rep, R.collab(b, {}).groups[0].rows, {speed: 1}),
  trace: (() => { const t = R.replayTrace(rep, 40); return {n: t.n, sum: t.total.reduce((a, c) => a + c, 0), peak: t.peak,
    kinds: Object.fromEntries(Object.entries(t.kinds).map(([k, v]) => [k, v.reduce((a, c) => a + c, 0)])),
    quiet: t.total.filter(c => c === 0).length}; })(),
  lanes: rep.lanes.map(l => l.id),
  flows: Object.fromEntries(rep.rows.filter(r => r.flows.length).map(r => [r.key, r.flows.map(f => [f.from, f.to, f.pickAt == null ? null : f.pickAt - r.at])])),
  pendingNow: Object.fromEntries(Object.entries(R.replayPending(rep, now)).map(([k, v]) => [k, v.map(x => x.key)])),
  locksNow: R.replayLocksAt(rep, now),
  locksPast: R.replayLocksAt(rep, Date.parse('2026-11-13T04:29:00Z')),
  layout: R.replayLayout(rep, now), layout2: R.replayLayout(rep, now),
  laneTrace: (() => { const t = R.replayLaneTrace(rep, 30); return Object.fromEntries(Object.entries(t.by).map(([k, v]) => [k, v.reduce((a, c) => a + c, 0)])); })(),
  monitor: V.replay(rep, [], {speed: 1, view: 'activity'}),
  shellFull: V.replay(rep, R.collab(b, {}).groups[0].rows, {speed: 1, full: true, blockOpen: true}),
}));
"""


def run(scope: dict | None = None, window: str = "auto", data: dict = OFFICE) -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW, json.dumps(scope or {}), window],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def by_key(got: dict) -> dict:
    return {r["key"]: r for r in got["rows"]}


def test_each_kind_reads_as_a_plain_sentence():
    rows = by_key(run())
    assert rows["mail-100"]["text"].endswith("builder mailed validator re-measure #450 opened")
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


def test_window_rolls_back_from_now_and_auto_picks_the_shortest_watchable():
    got = run()
    assert got["want"] == "auto" and got["window"] == "week", "too few rows for an hour or a day"
    assert got["counts"]["hour"] == len(got["rows"])
    assert run(window="hour")["window"] == "hour"
    assert got["at"][0] == "focus-51", "newest first at the playhead"


def test_playback_is_one_constant_and_slower_speeds_exist():
    got = run()
    assert got["playMs"] == 120000
    assert got["speeds"][:2] == [0.25, 0.5]
    assert got["rate"] == "1 week in 2 min"
    assert got["rateSlow"] == "1 week in 8 min"
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


def test_the_stage_leads_and_blocking_folds_below_it():
    got = run()
    shell = got["shell"]
    assert shell.index('data-rp-stage="1"') < shell.index('data-rp-blocking="1"'), "the replay stage comes first"
    assert re.search(r'<details class="rd-block rd-rp-blocking" data-rp-blocking="1">', shell), "folded by default"
    assert 'data-rp-blocking="1" open>' in got["shellFull"], "an opened list stays open on repaint"
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "min-height: 70vh" in css and "flex-wrap: nowrap" in css


def test_full_screen_toggle_with_a_viewport_fallback():
    got = run()
    assert 'data-rp-full="1" aria-label="Full screen" aria-pressed="false"' in got["shell"]
    assert 'aria-pressed="true" title="Leave full screen (Esc)"' in got["shellFull"]
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "requestFullscreen" in app and "fullscreenchange" in app and '"Escape"' in app
    css = (RD / "rd.css").read_text(encoding="utf-8")
    fs = [ln for ln in css.splitlines() if "rd-rp-fs" in ln]
    assert any("position: fixed; inset: 0" in ln for ln in fs), "covers the viewport without the API"
    assert any(".rd-rp-bar { order: 2" in ln for ln in fs), "controls sit along the bottom"
    assert any(".rd-pill" in ln and "font-size: 18px" in ln for ln in fs), "desk pills scale up"


def test_the_timeline_is_a_heart_monitor_trace_that_scrubs():
    got = run()
    tr = got["trace"]
    assert tr["n"] == 40 and tr["sum"] == len(got["rows"]), "every row in the window lands in a bucket"
    assert tr["peak"] >= 1 and tr["quiet"] > 0, "bursts spike, quiet stretches stay flat"
    assert sum(tr["kinds"].values()) == tr["sum"] and tr["kinds"]["mail"] >= 1
    shell = got["shell"]
    assert 'type="range"' not in shell, "the plain scrubber is gone"
    assert 'data-rp-trace="1" role="slider" tabindex="0"' in shell
    assert 'class="rd-rp-tr-dim"' in shell and 'clip-path="url(#rd-rp-clip)"' in shell, "dim ahead, lit behind the playhead"
    assert 'data-rp-head="1"' in shell and 'data-rp-clip="1"' in shell
    assert re.search(r'<rect class="k-(mail|todo|hold|wake|doing|score)"', shell), "a lane coloured by kind"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert "pointerdown" in app and "[data-rp-trace]" in app and "ArrowLeft" in app


def test_stage_lanes_follow_the_pick_with_the_cloud_pinned_last():
    got = run()
    assert got["lanes"][0] == "@office", "rows no desk sent (a wake) get the office lane"
    assert got["lanes"][-1] == "@out", "outside sits at the end"
    assert {"builder", "validator", "gardener"} <= set(got["lanes"])
    shell = got["shell"]
    for lane in got["lanes"]:
        assert f'data-lane="{lane}"' in shell and f'data-rp-tray="{lane}"' in shell
    rain = shell[shell.index('data-rp-rain="1">') + 17:shell.index('<ol class="rd-rp-list"')]
    assert re.sub(r"<[^>]+>", "", rain).strip() == "", "nothing but the kind icons ever falls: the columns start empty"


def test_pickup_is_read_from_the_records_per_kind():
    fl = run()["flows"]
    assert fl["mail-100"] == [["builder", "validator", 0]], "read with no later row: picked up on arrival"
    assert fl["mail-101"] == [["builder", "@out", None]], "unread: waits in the receiver's column"
    assert fl["move-3"] == [["builder", "validator", None]], "shipped for the creator: waits for its next move"
    assert fl["focus-60"] == [["gardener", "validator", None]], "a contested promise waits until the waiter takes it"
    got = run()
    assert "mail-101~0" in got["pendingNow"]["@out"] and "move-3~0" in got["pendingNow"]["validator"]
    assert any(x["wait"] and x["item"] == "hold-3" for x in got["locksNow"]["validator"])
    assert any(not x["wait"] and x["text"] == "docs-lock" for x in got["locksNow"]["gardener"]), "at now the holds table says who holds"
    assert any(x["wait"] for x in got["locksPast"]["validator"])


def test_gravity_pulls_talking_desks_together_and_is_deterministic():
    got = run()
    lay = got["layout"]
    assert lay == got["layout2"]
    assert lay["@out"] == max(lay.values()), "the cloud stays pinned at the right end"
    xs = sorted(lay.values())
    n = len(xs)
    assert all(b - a >= 0.5 / n - 1e-3 for a, b in zip(xs, xs[1:])), "pills never closer than the spacing floor"
    assert abs(lay["builder"] - lay["validator"]) < abs(lay["builder"] - lay["@office"]), "the pair that talks sits closer"


def test_activity_subtab_is_the_same_replay_one_trace_per_desk():
    got = run()
    mon = got["monitor"]
    assert mon.count('data-rp-mlane="') == len(got["lanes"])
    assert [m for m in re.findall(r'data-rp-mlane="([^"]+)"', mon)] == got["lanes"], "same order as the stage"
    assert 'data-rp-lanes=' not in mon and 'data-rp-subtab="activity"' in mon, "Activity has no stage"
    assert 'data-rp-subtab="desks"' in got["shell"] and 'data-rp-mlane=' not in got["shell"], "Desks has no per-desk lines"
    assert mon.count('data-rp-trace="1"') == len(got["lanes"]) + 1, "every lane scrubs, plus the total in the bar"
    assert got["laneTrace"]["builder"] >= 4 and got["laneTrace"]["validator"] >= 2
    assert mon.count('data-rp-trace="1"') == got["shell"].count('data-rp-trace="1"') + len(got["lanes"]), "same controls row, one clock"
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    assert '{ key: "desks", label: "Desks" }, { key: "activity", label: "Activity" }' in app, "two subtabs"
    assert '"rd-collab-subtab"' in app, "the subtab is remembered"
    assert "Replay" not in re.findall(r'label: "(\w+)"', app) and "Timeline" not in re.findall(r'label: "(\w+)"', app)


def test_stage_motion_is_transform_and_opacity_only():
    app = (RD / "rd-app.js").read_text(encoding="utf-8")
    body = app[app.index("function dropRow"):app.index("window.addEventListener(\"resize\"")]
    for frame in re.findall(r"\{ (?:transform|opacity)[^}]*\}", body):
        keys = set(re.findall(r"(\w+):", frame))
        assert keys <= {"transform", "opacity", "offset"}, frame
    assert "RP_LIVE" in app and "moving()" in app
    css = (RD / "rd.css").read_text(encoding="utf-8")
    assert "transition: transform 1.2s" in css


def test_density_trace_sits_on_top_of_both_subtabs():
    got = run()
    for html, body in ((got["shell"], 'data-rp-lanes='), (got["monitor"], 'data-rp-mlane=')):
        top = html.index('<div class="rd-rp-top">')
        assert top < html.index(body) < html.index('class="rd-rp-bar"'), "density on top, the subtab under it, controls last"
        assert html.index('data-rp-trace="1" role="slider" tabindex="0"') > top
