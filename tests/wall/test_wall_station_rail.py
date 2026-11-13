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
