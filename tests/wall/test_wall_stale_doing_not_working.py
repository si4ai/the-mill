# -*- coding: utf-8 -*-
"""A stale doing view is never "working".

GET /api/v1/doing?all=1 keeps a desk's last doing text after the desk goes quiet, and
flags the view itself with alive false / stale true (heartbeat_flags on the server). The
Wall trusts those flags and adds no time threshold of its own:

- the leftover text reads "last: <doing>, <age> ago", never as the current doing;
- a connected seat with a stale view is idle (with that last), not gone;
- a seat that is not alive with a stale view is away (dimmed, last seen).

Covers the DESKS rows (session/desks-rows.js), boot.js hereGlance / wallDoingText and the
doing paint (doing/doing-paint.js wallDoingRowHtml, wallDoingMetaHtml, wallDoingDeskHtml).
"""
from __future__ import annotations

import json
import os
import subprocess

from ._wall_src import BOOT, ROOT

ROWS = ROOT / "default" / "session" / "desks-rows.js"
DOING = ROOT / "default" / "doing" / "doing-paint.js"
NOW = "2026-11-13T03:00:00Z"

LEFT = {"owner": "auditor", "alive": False, "stale": True, "doing": "auditing run 41", "on": "todo-1180",
        "age": "17h", "waiting_on_it": {"letters": {"n": 0, "newest": [], "n_over_day": 0, "oldest_at": ""},
                                        "cards": {"n": 0, "newest": []}}}
FRESH = {"owner": "builder", "alive": True, "stale": False, "doing": "filing the stations route", "on": "mail-6035",
         "age": "47m", "waiting_on_it": {"letters": {"n": 0, "newest": [], "n_over_day": 0, "oldest_at": ""},
                                         "cards": {"n": 0, "newest": []}}}


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


def test_connected_seat_with_a_stale_view_is_idle_with_its_last():
    # The glance (old boot) still said "working"; the view's own flags win.
    got = _rows([{"owner": "auditor", "state": "working", "seat": "", "seatAlive": True}], {"auditor": LEFT})
    row = got["model"]["connected"][0]
    assert row["state"] == "idle"
    assert row["doing"] == ""
    assert row["lastDoing"] == "auditing run 41, 17h ago"
    assert row["time"] == ""
    assert got["model"]["away"] == []
    html = got["html"]
    assert 'class="here-state">idle<' in html
    assert "last: auditing run 41, 17h ago" in html
    assert 'class="here-state">working<' not in html
    assert '<span class="desk-text">auditing run 41' not in html


def test_seat_not_alive_with_a_stale_view_is_away_with_last_seen():
    stations = [{"name": "auditor", "connected": False, "last_connected": "2026-11-12T10:00:00Z",
                 "recent_activity": {"type": "doing", "at": "2026-11-12T10:00:00Z", "thing": "auditing run 41"}}]
    got = _rows([{"owner": "auditor", "state": "working", "seat": "", "seatAlive": False}], {"auditor": LEFT}, stations)
    assert got["model"]["connected"] == []
    assert [r["desk"] for r in got["model"]["away"]] == ["auditor"]
    html = got["html"]
    assert "Disconnected \u00b7 1" in html
    assert "last seen 17h ago" in html
    assert "last: auditing run 41, 17h ago" in html
    assert "working" not in html


def test_fresh_view_still_reads_working():
    got = _rows([{"owner": "builder", "state": "working", "seat": "", "seatAlive": True}], {"builder": FRESH})
    row = got["model"]["connected"][0]
    assert row["state"] == "working" and row["doing"] == "filing the stations route" and row["time"] == "47m"


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
  text: wallDoingText('auditor', 'auditing run 41'),
  row: wallDoingRowHtml('auditor', ''),
  meta: wallDoingMetaHtml('auditor'),
  desk: wallDoingDeskHtml('auditor', ''),
  freshRow: wallDoingRowHtml('builder', ''),
}));
"""


def _boot() -> dict:
    return _node(BOOT_HARNESS, str(BOOT), str(DOING), json.dumps([LEFT, FRESH]))


def test_glance_trusts_the_view_flags_not_the_leftover_text():
    got = _boot()
    assert got["seatLive"] == {"state": "idle", "note": "last: auditing run 41, 17h ago", "doing": ""}
    assert got["seatGone"]["state"] == "gone"
    assert got["seatGone"]["note"] == "last: auditing run 41, 17h ago"
    assert got["fresh"]["state"] == "working"
    assert got["text"] == ""


def test_doing_paint_reads_the_leftover_as_last():
    got = _boot()
    assert got["row"] == '<span class="here-doing is-idle is-stale" title="">last: auditing run 41, 17h ago</span>'
    assert "doing this for" not in got["meta"] and "17h" not in got["meta"]
    assert 'data-doing-go="todo-1180"' in got["meta"]
    assert 'is-stale">last: auditing run 41, 17h ago<' in got["desk"]
    assert "for 17h" not in got["desk"]
    assert ">filing the stations route<" in got["freshRow"]
