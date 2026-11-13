"""The redesigned Wall shell (rd/): what the six tabs show from served data.

Runs rd-model.js and rd-view.js in Node against a small office and checks what
a reader sees: working desks lead, a stale seat never reads as working, groups
carry plain words, and a spot whose field is not served stays hidden.
"""
from __future__ import annotations

import json
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
        {"owner": "gardener", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
        {"owner": "scout", "alive": True, "stale": True, "heartbeat": "2026-11-13 04:00:00"},
        {"owner": "auditor", "alive": False, "stale": True, "heartbeat": "2026-11-12 20:00:00"},
        {"owner": "retired", "alive": True, "stale": False, "heartbeat": "2026-11-13 04:39:00"},
    ]},
    "names": {"Office": [{"kind": "desk", "name": "retired", "deleted": True}]},
    "doing": {
        "builder": {"owner": "builder", "alive": True, "stale": False, "doing": "wiring the stations route", "on": "todo-1191", "age": "47m"},
        "gardener": {"owner": "gardener", "alive": True, "stale": False, "doing": "", "idle": "3h"},
        "scout": {"owner": "scout", "alive": True, "stale": True, "doing": "sweeping the tree", "on": "todo-9"},
    },
    "todos": {"Office": {"needs": [
        {"id": 1191, "status": "claimed", "detail": "Desks last-connection on the stations route", "assigned": "builder"},
        {"id": 1188, "status": "open", "detail": "Review labels route", "assigned": ""},
        {"id": 1100, "status": "done", "detail": "Old work", "assigned": "gardener"},
    ]}},
}

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const data = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const R = WallRd, V = WallRdView;
const b = R.base(data, {rosters: ['Office'], range: '7d'}, now);
const desks = R.desks(b, {sort: process.argv[4] || 'urgency'});
const todo = R.todo(b, {});
const score = R.score(b, {});
console.log(JSON.stringify({
  connected: desks.connected.map(d => [d.name, d.state]),
  away: desks.away.map(d => d.name),
  todo: todo.groups.map(g => [g.label, g.rows.length]),
  scoreKnown: score !== null,
  html: V.desksList(desks, now) + V.todo(todo) + (score ? V.score(score) : ''),
}));
"""


def run(data: dict = OFFICE, sort: str = "urgency") -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW, sort],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def test_working_desk_leads_and_stale_seat_is_never_working():
    got = run()
    assert got["connected"][0] == ["builder", "working"]
    names = [n for n, _ in got["connected"]]
    assert "scout" not in names, "a stale seat is not connected"
    assert "scout" in got["away"] and "auditor" in got["away"]
    assert all(state != "working" for n, state in got["connected"] if n != "builder")


def test_urgency_puts_working_before_idle_and_az_is_by_name():
    states = [s for _, s in run(sort="urgency")["connected"]]
    assert states.index("working") < states.index("idle")
    assert [n for n, _ in run(sort="za")["connected"]] == ["gardener", "builder"]


def test_deleted_desk_is_left_out():
    got = run()
    assert "retired" not in [n for n, _ in got["connected"]] + got["away"]
    assert "retired" not in got["html"]


def test_todo_groups_use_plain_words_with_counts():
    labels = dict(run()["todo"])
    assert labels.get("Claimed", 0) + labels.get("Doing", 0) >= 1
    assert labels.get("Open") == 1
    assert labels.get("Done") == 1
    html = run()["html"]
    for raw in ("roster_id", "mail_tos", "waiting_on_it", "n_over_day", "last_activity_at"):
        assert raw not in html


def test_unserved_scores_stay_hidden():
    got = run()
    assert not got["scoreKnown"]
    assert "NaN" not in got["html"] and "undefined" not in got["html"]
