"""Card 1242: the DESKS tab reads reach and last_wake from GET /api/v1/doing.

reach "wake" (no connect sits, the webhook can wake it) is not disconnected: the row
reads "reachable by wake" and "last wake T", T in the viewer's local time (left out when
last_wake is null). reach "connect" and "offline" keep today's rows, and a server that
sends no reach keeps today's behavior exactly. Runs rd-model.js and rd-view.js in Node.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RD = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

NOW = "2026-11-13T04:40:00Z"
OLD = "2026-11-13 02:00:00"


def seat(owner: str, live: bool) -> dict:
    hb = "2026-11-13 04:39:00" if live else OLD
    return {"owner": owner, "alive": live, "stale": not live, "heartbeat": hb}


def view(owner: str, **reach) -> dict:
    return dict({"owner": owner, "n": 0, "doings": [], "alive": True, "stale": False}, **reach)


OFFICE = {
    "agents": {"Office": [seat("builder", True), seat("waker", False), seat("napper", False),
                          seat("gone", False), seat("old", False)]},
    "doing": {
        "builder": view("builder", reach="connect", last_wake=None),
        "waker": view("waker", reach="wake", last_wake="2026-11-13T04:10:00Z"),
        "napper": view("napper", reach="wake", last_wake=None),
        "gone": view("gone", reach="offline", last_wake="2026-11-12T20:00:00Z"),
        "old": view("old"),  # an older server: no reach key
    },
}

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const R = WallRd, V = WallRdView;
const data = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const b = R.base(data, {rosters: ['Office'], range: '7d'}, now);
const m = R.desks(b, {sort: 'urgency'});
const rows = {};
V.desksList(m, now).split('<div class="rd-here-line').slice(1).forEach(x => {
  rows[/data-rd-pickdesk="([^"]+)"/.exec(x)[1]] = x;
});
const detail = {};
Object.keys(rows).forEach(n => { detail[n] = V.deskDetail(R.deskDetail(b, n), now); });
console.log(JSON.stringify({
  connected: m.connected.map(d => d.name), away: m.away.map(d => [d.name, d.state]),
  head: V.desksList(m, now).split('</div>')[0], lead: R.hero(b, 'desks', m).lead, rows, detail,
}));
"""


def run(data: dict = OFFICE, tz: str = "America/Los_Angeles") -> dict:
    env = dict(os.environ, TZ=tz)
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW],
                         capture_output=True, text=True, check=True, timeout=30, env=env)
    return json.loads(out.stdout)


def state_of(row: str) -> str:
    return re.search(r'class="rd-here-state ([^"]+)">([^<]*)<', row).group(2)


def test_wake_with_last_wake_is_not_disconnected_and_shows_local_time():
    got = run()
    row = got["rows"]["waker"]
    assert state_of(row) == "reachable by wake"
    assert "disconnected" not in row and not row.startswith(' away"')
    # 04:10 UTC reads 20:10 the evening before on a UTC-8 viewer clock.
    assert "last wake 12 Nov 20:10:00" in row and "last seen" not in row
    assert "last wake 12 Nov 20:10:00" in got["detail"]["waker"]
    assert "reachable by wake" in got["detail"]["waker"]
    assert "last wake 13 Nov 04:10:00" in run(tz="UTC")["rows"]["waker"]


def test_wake_with_null_last_wake_leaves_the_time_out():
    got = run()
    row = got["rows"]["napper"]
    assert state_of(row) == "reachable by wake"
    assert "last wake" not in row and "last seen" not in row
    assert "last wake" not in got["detail"]["napper"]


def test_offline_is_todays_disconnected_row():
    got = run()
    row = got["rows"]["gone"]
    assert row.startswith(' away"') and state_of(row) == "disconnected"
    assert "last seen" in row and "last wake" not in row


def test_connect_is_todays_connected_row():
    got = run()
    assert got["connected"] == ["builder"]
    assert state_of(got["rows"]["builder"]) == "idle"


def test_missing_reach_is_todays_behavior():
    got = run()
    row = got["rows"]["old"]
    assert row.startswith(' away"') and state_of(row) == "disconnected" and "last seen" in row
    # A whole feed without reach paints exactly as before card 1242.
    bare = json.loads(json.dumps(OFFICE))
    for v in bare["doing"].values():
        v.pop("reach", None)
        v.pop("last_wake", None)
    old = run(bare)
    assert "reachable by wake" not in json.dumps(old)
    assert all(s == "disconnected" for _, s in old["away"])
    assert old["lead"] == "1 desk connected, 4 disconnected on Office."
    assert old["head"].endswith("1 connected")


def test_wake_desks_lead_the_away_rows_and_counts_say_so():
    got = run()
    assert sorted(n for n, _ in got["away"][:2]) == ["napper", "waker"]
    assert got["lead"] == "1 desk connected, 2 reachable by wake, 2 disconnected on Office."
    assert got["head"].endswith("1 connected \u00b7 2 reachable by wake")
