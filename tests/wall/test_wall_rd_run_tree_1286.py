"""Card 1286: the DESKS desk detail (rd shell) nests live tw runs by parent_watch_id (card 1240's tree).

GET /api/v1/doing gives each live doing a watch_id and parent_watch_id; the DOING TRAIL
(GET /api/v1/doing/history) has the same doing id. A live run sits under its live parent,
indented, with a "runs" toggle that opens doing-paint.js's run tree; a run whose parent is
not live keeps its place marked "child of PARENT". Ended rows keep the trail's order, and
a server that sends no watch_id paints the flat trail with no toggle. Runs in Node.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

RD = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

NOW = "2026-11-22T01:50:00Z"
OUTER, INNER, GONE = "tw-79133d7f563d4f1f", "tw-c466dfa83f0741b0", "tw-0000aaaa1111bbbb"


def doing(i: int, created: str, watch: str, parent) -> dict:
    return {"id": i, "created": created, "text": "", "state": "started", "state_at": created,
            "card": None, "watch_id": watch, "parent_watch_id": parent}


def hist(i: int, at: str, ended: bool = False) -> dict:
    return {"id": i, "src": "doing", "desk": "wall-ui", "at": at, "text": "", "on": "",
            "roster": "Office", "ended": ended, "ended_by": "finished" if ended else None}


OFFICE = {
    "agents": {"Office": [{"owner": "wall-ui", "alive": True, "stale": False, "heartbeat": "2026-11-22 01:49:00"}]},
    "doing": {"wall-ui": {"owner": "wall-ui", "alive": True, "stale": False, "n": 2, "doings": [
        doing(41, "2026-11-22T01:43:32Z", INNER, OUTER), doing(40, "2026-11-22T01:43:31Z", OUTER, None)]}},
    "history": {"wall-ui": [hist(41, "2026-11-22 01:43:32"), hist(40, "2026-11-22 01:43:31"),
                            hist(39, "2026-11-22 01:30:00", ended=True)]},
}

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const R = WallRd, V = WallRdView;
const data = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const b = R.base(data, {rosters: ['Office'], range: '7d'}, now);
const dd = R.deskDetail(b, 'wall-ui');
console.log(JSON.stringify({trail: dd.trail, html: V.deskDetail(dd, now)}));
"""


def run(data: dict) -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def trail_html(html: str) -> str:
    return html.split('class="rd-block trail"', 1)[1]


def test_live_child_nests_under_its_live_parent_with_a_runs_toggle():
    got = run(OFFICE)
    assert [(t["watch"], t["depth"], t["childOf"]) for t in got["trail"]] == [
        (OUTER, 0, ""), (INNER, 1, ""), ("", 0, "")]
    html = trail_html(got["html"])
    assert html.index('data-watch="%s"' % OUTER) < html.index('data-watch="%s"' % INNER)
    assert re.search(r'class="rd-tl current rd-d1" data-watch="%s"' % INNER, html)
    assert 'data-doing-run="%s" data-doing-desk="wall-ui"' % OUTER in html
    assert 'data-doing-run-tree="wall-ui|%s"' % INNER in html
    assert "child of" not in html
    assert "ended: finished" in html and html.count("data-doing-run=") == 2


def test_child_whose_parent_is_not_live_keeps_its_place_marked_child_of():
    data = copy.deepcopy(OFFICE)
    data["doing"]["wall-ui"]["doings"][0]["parent_watch_id"] = GONE
    got = run(data)
    assert [(t["watch"], t["depth"], t["childOf"]) for t in got["trail"]] == [
        (INNER, 0, GONE), (OUTER, 0, ""), ("", 0, "")]
    assert "child of " + GONE in trail_html(got["html"])
    assert "rd-d1" not in got["html"]


def test_older_server_without_watch_id_paints_the_flat_trail():
    data = copy.deepcopy(OFFICE)
    for x in data["doing"]["wall-ui"]["doings"]:
        del x["watch_id"], x["parent_watch_id"]
    got = run(data)
    assert [t["watch"] for t in got["trail"]] == ["", "", ""]
    html = trail_html(got["html"])
    assert "data-doing-run" not in html and "child of" not in html and "rd-d1" not in html
    assert html.count('class="rd-tl current"') == 2


def test_parent_loop_drops_no_row():
    data = copy.deepcopy(OFFICE)
    data["doing"]["wall-ui"]["doings"][1]["parent_watch_id"] = INNER
    got = run(data)
    assert sorted(t["watch"] for t in got["trail"]) == ["", OUTER, INNER]
