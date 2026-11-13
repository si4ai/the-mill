# -*- coding: utf-8 -*-
"""Card 1191: the Wall rail shows stations seen in the last 7 days; Admin lists them all.

Runs lib/data.js in Node against rows in the GET /api/pov?part=desks shape that
card 1191 serves (rows[].lan_ip, connected, last_connected ISO UTC or null).
A station's last connection is the latest last_connected among its rows.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
DATA = ROOT / "lib" / "data.js"
BOOT = ROOT / "default" / "boot.js"
BOARD = ROOT / "default" / "board.html"

NOW = "2026-11-13T02:00:00Z"
ROWS = [
    {"name": "builder", "connected": True, "lan_ip": "192.0.2.10", "last_connected": "2026-11-13T00:58:12Z"},
    {"name": "validator", "connected": False, "lan_ip": "192.0.2.10", "last_connected": "2026-11-10T00:00:00Z"},
    {"name": "wall-ui", "connected": False, "lan_ip": "192.0.2.20", "last_connected": "2026-11-12T23:00:00Z"},
    {"name": "old-a", "connected": False, "lan_ip": "192.0.2.30", "last_connected": "2026-11-01T00:00:00Z"},
    {"name": "old-b", "connected": False, "lan_ip": "192.0.2.30", "last_connected": "2026-11-06T02:00:00Z"},
    {"name": "stale", "connected": False, "lan_ip": "192.0.2.40", "last_connected": "2026-11-06T01:59:00Z"},
    {"name": "never-desk", "connected": False, "lan_ip": "", "last_connected": None},
]

HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const rows = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const pick = s => ({ip: s.ip, n: s.n, live: s.live, ago: s.ago, desks: s.desks});
process.stdout.write(JSON.stringify({
  all: wallStations(rows, now).map(pick),
  rail: wallRailStations(rows, now).map(pick),
  days: WALL_STATION_RAIL_DAYS,
}));
"""


def _run(rows=ROWS, now=NOW):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(
        ["node", "-e", HARNESS, str(DATA), json.dumps(rows), now],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_rail_keeps_live_and_last_7_days_newest_first():
    r = _run()
    assert r["days"] == 7
    assert [s["ip"] for s in r["rail"]] == ["192.0.2.10", "192.0.2.20", "192.0.2.30"]
    assert [s["ago"] for s in r["rail"]] == ["live", "3h ago", "7d ago"]


def test_station_last_connection_is_its_latest_row():
    r = _run()
    by = {s["ip"]: s for s in r["all"]}
    assert by["192.0.2.30"]["n"] == 2 and by["192.0.2.30"]["ago"] == "7d ago"
    assert by["192.0.2.10"]["desks"] == ["builder", "validator"]


def test_admin_list_keeps_every_station_including_never():
    r = _run()
    assert [s["ip"] for s in r["all"]] == ["192.0.2.10", "192.0.2.20", "192.0.2.30", "192.0.2.40", ""]
    assert r["all"][-1]["ago"] == "never"
    assert "192.0.2.40" not in [s["ip"] for s in r["rail"]]


def test_short_ago_steps():
    rows = [
        {"name": "a", "connected": False, "lan_ip": "a", "last_connected": "2026-11-13T01:59:30Z"},
        {"name": "b", "connected": False, "lan_ip": "b", "last_connected": "2026-11-13T01:55:00Z"},
        {"name": "c", "connected": False, "lan_ip": "c", "last_connected": "2026-11-11T03:00:00Z"},
    ]
    assert [s["ago"] for s in _run(rows)["rail"]] == ["now", "5m ago", "47h ago"]


def test_boot_and_admin_paint_from_the_same_rows():
    boot = BOOT.read_text(encoding="utf-8")
    assert "wallRailStations(rows, now)" in boot
    assert "paintAdminStations(rows, now, mine)" in boot
    assert 'id="admin-stations-body"' in BOARD.read_text(encoding="utf-8")


def test_station_last_is_the_max_whatever_the_row_order():
    # Newest row in the middle, a null row on either side: the max survives.
    for rows in (
        [{"name": "a", "connected": False, "lan_ip": "s", "last_connected": "2026-11-10T00:00:00Z"},
         {"name": "b", "connected": False, "lan_ip": "s", "last_connected": "2026-11-12T23:00:00Z"},
         {"name": "c", "connected": False, "lan_ip": "s", "last_connected": "2026-11-11T00:00:00Z"},
         {"name": "d", "connected": False, "lan_ip": "s", "last_connected": None}],
        [{"name": "d", "connected": False, "lan_ip": "s", "last_connected": None},
         {"name": "b", "connected": False, "lan_ip": "s", "last_connected": "2026-11-12T23:00:00Z"},
         {"name": "a", "connected": False, "lan_ip": "s", "last_connected": "2026-11-10T00:00:00Z"}],
    ):
        assert [s["ago"] for s in _run(rows)["all"]] == ["3h ago"]


def test_live_station_stays_on_rail_without_a_recent_date():
    rows = [
        {"name": "a", "connected": True, "lan_ip": "old-live", "last_connected": "2026-10-01T00:00:00Z"},
        {"name": "b", "connected": True, "lan_ip": "never-live", "last_connected": None},
    ]
    assert sorted(s["ip"] for s in _run(rows)["rail"]) == ["never-live", "old-live"]


def test_rows_of_one_station_merge_even_when_not_adjacent():
    rows = [
        {"name": "a", "connected": False, "lan_ip": "s1", "last_connected": "2026-11-12T00:00:00Z"},
        {"name": "b", "connected": False, "lan_ip": "s2", "last_connected": "2026-11-12T00:00:00Z"},
        {"name": "c", "connected": False, "lan_ip": "s1", "last_connected": "2026-11-12T01:00:00Z"},
    ]
    all_ = _run(rows)["all"]
    assert [(s["ip"], s["n"]) for s in all_] == [("s1", 2), ("s2", 1)]
    assert all_[0]["desks"] == ["a", "c"]


# The rail and Admin paint, run in Node against boot.js's own paintDesks with a stub DOM.
PAINT = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const boot = fs.readFileSync(process.argv[2], 'utf8');
function fn(name) {
  const i = boot.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('no ' + name);
  let d = 0;
  for (let k = boot.indexOf('{', i); k < boot.length; k++) {
    if (boot[k] === '{') d++;
    if (boot[k] === '}' && --d === 0) return boot.slice(i, k + 1);
  }
}
const esc = boot.match(/const esc = .*\n/)[0];
const hosts = {};
global.document = {getElementById: id => (hosts[id] = hosts[id] || {id, dataset: {}, innerHTML: ''})};
let fetches = 0;
global.fetch = () => { fetches++; return Promise.reject(new Error('no fetch')); };
global.XMLHttpRequest = function () { fetches++; };
Date.now = () => Date.parse(process.argv[4]);
(0, eval)(esc + fn('paintRailBook') + '\n' + fn('paintAdminStations') + '\n' + fn('paintDesks') +
  '\nglobal.paintDesks = paintDesks;');
const out = [];
for (const rows of JSON.parse(process.argv[3])) {
  paintDesks({mine: '', rows});
  const rail = hosts['rail-desks'].innerHTML, admin = hosts['admin-stations-body'].innerHTML;
  out.push({
    rail_ids: [...rail.matchAll(/data-id="([^"]*)"/g)].map(m => m[1]),
    rail_empty: (rail.match(/class="rail-empty">([^<]*)</) || [])[1] || null,
    admin_rows: (admin.match(/<tr class=/g) || []).length,
  });
}
process.stdout.write(JSON.stringify({out, fetches}));
"""


def _paint(*row_sets):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(
        ["node", "-e", PAINT, str(DATA), str(BOOT), json.dumps(list(row_sets)), NOW],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_paint_rail_window_admin_everything_and_no_extra_fetch():
    old = [r for r in ROWS if r["lan_ip"] in ("192.0.2.40", "")]
    r = _paint(ROWS, old)
    full, empty = r["out"]
    assert full["rail_ids"] == ["192.0.2.10", "192.0.2.20", "192.0.2.30"]
    assert full["admin_rows"] == 5
    assert empty["rail_ids"] == [] and empty["rail_empty"] == "none in 7 days"
    assert empty["admin_rows"] == 2
    assert r["fetches"] == 0


def test_narrow_rail_hides_the_time_label():
    css = (ROOT / "default" / "board.css").read_text(encoding="utf-8")
    assert "body.rail-narrow .rail-book .ago { display: none; }" in css
