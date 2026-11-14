# -*- coding: utf-8 -*-
"""A stale doing view is never "working".

GET /api/v1/doing?all=1 lists a desk's live doings (tw runs, card 1207) and flags the view
itself with alive false / stale true (heartbeat_flags on the server). A run can stay live
after its desk goes quiet (until the cap sweep or reconcile marks it stale). The Wall trusts
those flags and adds no time threshold of its own:

- a stale view's runs never read as the current doing (and there is no "last:" leftover);
- a connected seat with a stale view is idle, not gone;
- a seat that is not alive with a stale view is away (dimmed, last seen).

Covers the DESKS rows (session/desks-rows.js), boot.js hereGlance / wallDoingText and the
doing paint (doing/doing-paint.js wallDoingRowHtml, wallDoingMetaHtml, wallDoingDeskHtml).
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from ._wall_src import BOOT, ROOT

ROWS = ROOT / "default" / "session" / "desks-rows.js"
DOING = ROOT / "default" / "doing" / "doing-paint.js"
NOW = "2026-11-13T03:00:00Z"

LEFT = {"owner": "auditor", "alive": False, "stale": True, "n": 1,
        "doings": [{"id": 41, "created": "2026-11-12T10:00:00Z", "text": "auditing run 41", "state": "started",
                    "state_at": "2026-11-12T10:00:00Z", "card": 1180}]}
FRESH = {"owner": "builder", "alive": True, "stale": False, "n": 1,
         "doings": [{"id": 42, "created": "2026-11-13T02:13:00Z", "text": "filing the stations route",
                     "state": "started", "state_at": "2026-11-13T02:13:00Z", "card": 6035}]}


def _node(script: str, *args: str) -> dict:
    env = dict(os.environ, TZ="America/Los_Angeles")
    out = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True, check=True, env=env).stdout
    return json.loads(out)


# ---- DESKS rows

ROWS_HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const ctx = JSON.parse(process.argv[2]);
ctx.now = Date.parse(ctx.now);
const m = desksModel(ctx);
process.stdout.write(JSON.stringify({ model: m, html: desksHtml(m) }));
"""


def _rows(live: list, doing: dict, stations: list | None = None) -> dict:
    ctx = {"now": NOW, "live": live, "doing": doing, "stations": stations or [], "prios": {}, "kpis": []}
    return _node(ROWS_HARNESS, str(ROWS), json.dumps(ctx))


def test_connected_seat_with_a_stale_view_is_idle():
    # The glance (old boot) still said "working"; the view's own flags win.
    got = _rows([{"owner": "auditor", "state": "working", "seatAlive": True}], {"auditor": LEFT})
    row = got["model"]["connected"][0]
    assert row["state"] == "idle"
    assert row["doing"] == ""
    assert "lastDoing" not in row
    assert row["time"] == ""
    assert got["model"]["away"] == []
    html = got["html"]
    assert 'class="here-state">idle<' in html
    assert "auditing run 41" not in html and "last:" not in html
    assert 'class="here-state">working<' not in html


@pytest.mark.parametrize("flags", [{"alive": False, "stale": False}, {"alive": True, "stale": True}],
                         ids=["alive-false-only", "stale-true-only"])
def test_either_flag_alone_makes_the_view_a_leftover(flags):
    # Either server flag alone is enough; a fresh 47m age does not make it working.
    view = dict(FRESH, **flags)
    got = _rows([{"owner": "builder", "state": "working", "seatAlive": True}], {"builder": view})
    row = got["model"]["connected"][0]
    assert row["state"] == "idle"
    assert row["doing"] == ""
    assert "filing the stations route" not in got["html"]


def test_seat_not_alive_with_a_stale_view_is_away_with_last_seen():
    stations = [{"name": "auditor", "connected": False, "last_connected": "2026-11-12T10:00:00Z",
                 "recent_activity": {"type": "doing", "at": "2026-11-12T10:00:00Z", "thing": "auditing run 41"}}]
    got = _rows([{"owner": "auditor", "state": "working", "seatAlive": False}], {"auditor": LEFT}, stations)
    assert got["model"]["connected"] == []
    assert [r["desk"] for r in got["model"]["away"]] == ["auditor"]
    html = got["html"]
    assert "Disconnected \u00b7 1" in html
    assert "last seen 17h ago" in html
    assert "working" not in html


def test_fresh_view_still_reads_working():
    got = _rows([{"owner": "builder", "state": "working", "seatAlive": True}], {"builder": FRESH})
    row = got["model"]["connected"][0]
    assert row["state"] == "working" and row["doing"] == "filing the stations route" and row["time"] == "47m ago"


# ---- boot.js glance and the doing paint

BOOT_HARNESS = r"""
const fs = require('fs');
const [bootFile, doingFile, viewsJson] = process.argv.slice(1);
global.window = global;
global.document = { addEventListener() {}, querySelectorAll() { return []; }, querySelector() { return null; } };
global.esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
global.t = v => (v ? String(v) : '-');
global.dt = v => (v ? String(v).replace('T', ' ').slice(0, 19) : '-');
global.millName = (k, v) => String(v || '');
global.millGid = r => (r && r.roster_id) || '';
global.millJobsForOwner = () => [];
global.wallLazyCall = () => Promise.resolve();
const src = fs.readFileSync(bootFile, 'utf8');
(0, eval)(src.slice(src.indexOf('function wallDoingView('), src.indexOf('function sgChip(')));
(0, eval)(fs.readFileSync(doingFile, 'utf8'));
const views = JSON.parse(viewsJson);
window.WALL_DOING = { state: 'ok', byOwner: Object.fromEntries(views.map(v => [v.owner, v])), at: 0, sig: '', inflight: null, trails: {} };
const g = (owner, seat) => { const x = hereGlance({ events: [] }, seat); return { state: x.state, note: x.note, doing: x.doing }; };
process.stdout.write(JSON.stringify({
  seatLive: g('auditor', { owner: 'auditor', doing: 'auditing run 41', alive: true }),
  seatGone: g('auditor', { owner: 'auditor', doing: 'auditing run 41', alive: false }),
  fresh: g('builder', { owner: 'builder', doing: '', alive: true }),
  text: wallDoingText('auditor'),
  row: wallDoingRowHtml('auditor'),
  meta: wallDoingMetaHtml('auditor'),
  desk: wallDoingDeskHtml('auditor'),
  freshRow: wallDoingRowHtml('builder'),
}));
"""


def _boot() -> dict:
    return _node(BOOT_HARNESS, str(BOOT), str(DOING), json.dumps([LEFT, FRESH]))


def test_glance_trusts_the_view_flags_not_the_live_runs():
    got = _boot()
    assert got["seatLive"] == {"state": "idle", "note": "idle", "doing": ""}
    assert got["seatGone"]["state"] == "gone"
    assert got["seatGone"]["note"] == "gone"
    assert got["fresh"]["state"] == "working"
    assert got["text"] == ""


def test_doing_paint_reads_a_stale_view_as_idle():
    got = _boot()
    assert got["row"] == '<span class="here-doing is-idle is-stale">idle</span>'
    assert "data-doing-go" not in got["meta"] and "auditing" not in got["meta"]
    assert 'is-stale">idle<' in got["desk"]
    assert ">filing the stations route<" in got["freshRow"]
