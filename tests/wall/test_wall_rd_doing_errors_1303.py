"""Card 1303: the DESKS desk detail (rd shell) paints the doing-error block in the desk's score row.

GET /api/pov?part=scores gives each desk row doing_errors (null when the server's read failed).
The pane names the score and says what it is for (what to fix next, not a grade), lists the
kinds in the server's order each with its next line and up to five doing ids linked to the
desk's doing history, heads with the last N runs and their span, toggles 7d / 30d for the
window counts and the commands worst first, and draws hourly and daily sparks. A null block or
a reason is said in words; an older server with no block paints no pane. The payloads come from
the server's own desk_errors (agent_coord/server/records/doing_errors.py). Runs in Node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_coord.server.records import doing_errors as de

RD = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

T0 = datetime(2026, 11, 24, 12, 0, 0)
NOW = "2026-11-24T13:00:00Z"


def _run(i, start_s, end_s, reason, ec=None, cause=None, cmd=None):
    return {"id": i, "start_at": T0 + timedelta(seconds=start_s),
            "end_at": None if end_s is None else T0 + timedelta(seconds=end_s),
            "end_reason": reason, "ec": ec, "cause": cause, "cmd": cmd}


RUNS = [
    _run(1, 0, 5, "tw_failed", 4, cmd="pytest"),
    _run(2, 60, 70, "tw_failed", 4, cmd="pytest"),
    _run(3, 400, 410, "tw_finished", 0, cmd="pytest"),
    _run(4, 500, 510, "tw_failed", 128, cmd="git push"),
    _run(5, 520, 530, "tw_failed", 2),
    _run(6, 700, 800, "tw_failed", None, "reconcile"),
    _run(7, 801, None, None),
    _run(8, -9 * 86400, -9 * 86400 + 30, "tw_failed", 128, cmd="git push"),  # in 30d only
]


def block(monkeypatch, runs) -> dict:
    """The server's real doing_errors block for RUNS (its SQL replaced by the rows)."""
    def rows(cn, sql, args):
        if "UTC_TIMESTAMP" in sql:
            return [{"now": T0 + timedelta(hours=1)}]
        out = sorted((dict(r) for r in runs), key=lambda r: r["start_at"], reverse=True)
        if "LIMIT" in sql:
            return out[: args[-1]]
        return [r for r in out if r["start_at"] >= args[-1]]
    monkeypatch.setattr(de, "_rows", rows)
    return json.loads(json.dumps(de.desk_errors(None, 1)))


def office(errs, key=True) -> dict:
    row = {"desk": "wall-ui", "roster": "Office", "scores": []}
    if key:
        row["doing_errors"] = errs
    return {
        "agents": {"Office": [{"owner": "wall-ui", "alive": True, "stale": False, "heartbeat": "2026-11-24 12:59:00"}]},
        "povScores": {"desks": [row]},
    }


SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const R = WallRd, V = WallRdView;
const data = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const b = R.base(data, {rosters: ['Office'], range: '7d'}, now);
const dd = R.deskDetail(b, 'wall-ui');
dd.errWin = process.argv[4];
console.log(JSON.stringify({errors: dd.errors === undefined ? "undefined" : dd.errors, html: V.deskDetail(dd, now)}));
"""


def paint(data: dict, win: str = "7d") -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), json.dumps(data), NOW, win],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def pane(html: str) -> str:
    assert 'class="rd-sg errs"' in html
    return html.split('class="rd-sg errs"', 1)[1]


def test_kinds_in_server_order_each_with_its_next_line_and_linked_ids(monkeypatch):
    errs = block(monkeypatch, RUNS)
    html = pane(paint(office(errs))["html"])
    assert "Doing errors" in html and "not a grade" in html and "what to fix" in html
    kinds = re.findall(r'class="rd-de-k[^"]*" data-kind="([a-z_0-9]+)"', html)
    assert kinds == errs["kinds"] == ["usage", "git_fatal", "other_nonzero", "reruns_2m", "left_open"]
    for k in kinds:
        assert errs["next"][k].replace("'", "&#39;") in html
    usage = html.split('data-kind="usage"', 1)[1].split('data-kind="git_fatal"', 1)[0]
    assert '<b class="rd-de-n">2</b>' in usage
    assert re.findall(r'data-doing-id="(\d+)"', usage) == ["1", "2"]
    assert 'href="/api/v1/doing/history?desk=wall-ui"' in usage
    assert 'data-kind="left_open"><span class="rd-sname">Left open' in html.replace('rd-de-k hit" ', 'rd-de-k" ')


def test_headline_is_the_last_n_runs_with_their_span(monkeypatch):
    errs = block(monkeypatch, RUNS[:7])
    html = pane(paint(office(errs))["html"])
    # Fewer than 100 runs: all of them, n is the actual total; span 3600 s reads 1h.
    assert "All 7 runs over 1h: 4 failed runs" in html
    errs = block(monkeypatch, [_run(i, i * 20, i * 20 + 1, "tw_failed", 4) for i in range(130)])
    html = pane(paint(office(errs))["html"])
    assert "Last 100 runs over 50m: 100 failed runs" in html


def test_window_toggle_switches_counts_and_commands_worst_first(monkeypatch):
    errs = block(monkeypatch, RUNS)
    week = pane(paint(office(errs), "7d")["html"])
    month = pane(paint(office(errs), "30d")["html"])
    assert 'data-rd-derr-win="7d" aria-pressed="true"' in week
    assert 'data-rd-derr-win="30d" aria-pressed="true"' in month
    assert "7 runs \u00b7 usage errors 2 \u00b7 git errors 1 \u00b7 other failures 1 \u00b7 quick reruns 2 \u00b7 left open 1" in week
    assert "8 runs \u00b7 usage errors 2 \u00b7 git errors 2" in month
    cmds = re.findall(r"<td><code>([^<]+)</code></td><td>(\d+)</td><td>(\d+)</td>", month)
    # The server's order (most failed, then most runs) is kept as sent.
    assert [c["cmd"] for c in errs["windows"]["30d"]["by_cmd"]] == ["pytest", "git push"]
    assert cmds == [("pytest", "3", "2"), ("git push", "2", "2")]
    assert re.findall(r"<td><code>([^<]+)</code>", week) == ["pytest", "git push"]


def test_hourly_and_daily_sparks_follow_the_buckets(monkeypatch):
    errs = block(monkeypatch, RUNS)
    html = pane(paint(office(errs))["html"])
    sparks = re.findall(r'<span class="rd-si-spark"[^>]*>((?:<i class="s\d"></i>)+)</span>', html)
    assert len(sparks) == 2
    hourly = re.findall(r's(\d)', sparks[0])
    assert len(hourly) == 24 and len(re.findall(r's(\d)', sparks[1])) == 30
    assert hourly[-2] == "8" and hourly[-1] == "0"  # all 4 failures sit in the hour before now


def test_null_block_and_reasons_are_said_in_words(monkeypatch):
    assert "could not read" in pane(paint(office(None))["html"])
    none = pane(paint(office(block(monkeypatch, [])))["html"])
    assert "No tw runs from this desk yet" in none and "rd-de-k" not in none
    old = block(monkeypatch, [_run(8, -9 * 86400, -9 * 86400 + 30, "tw_failed", 128)])
    assert old["windows"]["7d"] is None
    week = pane(paint(office(old), "7d")["html"])
    assert "no tw runs in this window" in week


def test_older_server_without_the_block_paints_no_pane():
    got = paint(office(None, key=False))
    assert got["errors"] == "undefined" and "rd-sg errs" not in got["html"]
