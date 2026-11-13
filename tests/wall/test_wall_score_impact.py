# -*- coding: utf-8 -*-
"""Score tab redesign: Scores in impact groups, Spend as tw doing time.

Runs default/score/score-impact.js in Node against tests/wall/score_impact_fixture.json,
a labeled sample captured from the route and field shapes in letter 5492:
/api/v1/scores rows with updated, /api/v1/activity-buckets rows
(updated, type, act, desk, items) and /api/v1/score-runs rows (desk, phase,
dwell_active_ms, seed). Checks the agreed rules from the design review: every row
listed in group order, gaps never painted as 0, rates only from activity, time only
from doing.task.dwell_*_ms, and no total without finished-run history.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score.js"
IMPACT = ROOT / "default" / "score" / "score-impact.js"
FIXTURE = Path(__file__).resolve().parent / "score_impact_fixture.json"
BARE = re.compile(r"^(wake\.|mill-office\.wasted|mail\.|todo\.|hold\.|connect\.|cards$)")

HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
(0, eval)(fs.readFileSync(process.argv[2], 'utf8'));
const fx = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const mode = process.argv[4];
const now = Date.parse(fx.now);
let kpis = fx.scores_page.kpis;
let routes = fx.routes;
if (mode === 'bare') {
  // Shape of main today: no seeded families, no updated, no new routes answering.
  kpis = kpis.filter(k => !new RegExp(process.argv[5]).test(k.kpi)).map(k => { const c = Object.assign({}, k); delete c.updated; return c; });
  routes = { activityAll: null, runs: null, transitions: null };
}
if (mode === 'noactivity') routes = Object.assign({}, routes, { activityAll: null });
const ctx = scoreImpactCtxFromRoutes(routes, now);
const m = scoreImpactModel(kpis, ctx, now);
const sm = scoreSpendModel(kpis, ctx);
process.stdout.write(JSON.stringify({
  groups: m.groups.map(g => ({ id: g.def.id, rows: g.rows.map(r => [r.kpi, r.desk, r.state]) })),
  tally: m.tally,
  scoresHtml: scoreImpactHtml(m),
  spendHtml: scoreSpendHtml(sm, now),
  office: sm.office,
  sums: sm.sums,
  ctxKeys: Object.keys(ctx),
  actKeys: Object.keys(ctx.activity || {}).sort(),
  fmt: [scoreImpactFmtMs(40), scoreImpactFmtMs(1086), scoreImpactFmtMs(366220041.908)],
  wake: scoreImpactActivity(ctx, 'wake', 'Office', now),
  doingBuilder: scoreImpactActivity(ctx, 'doing', 'builder', now),
}));
"""


def _run(mode: str) -> dict:
    env = dict(os.environ, TZ="America/Los_Angeles")
    out = subprocess.run(
        ["node", "-e", HARNESS, str(SCORE), str(IMPACT), str(FIXTURE), mode, BARE.pattern],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def sample() -> dict:
    return _run("routes")


@pytest.fixture(scope="module")
def bare() -> dict:
    return _run("bare")


def _group(html: str, gid: str) -> str:
    return html.split(f'id="si-g-{gid}"', 1)[1].split("</section>", 1)[0]


def test_fixture_is_labeled_sample():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fx["_sample"].startswith("SAMPLE")
    assert all(r.get("seed") is True for r in fx["routes"]["runs"]["rows"])


def test_groups_in_impact_order_every_row_listed(sample):
    ids = [g["id"] for g in sample["groups"]]
    assert ids == ["wakes", "doing", "mail", "todo", "hold", "connect", "platform", "system", "other"]
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    listed = sum(1 for g in sample["groups"] for r in g["rows"] if r[2] in ("ok", "omitted"))
    assert listed == len(fx["scores_page"]["kpis"])
    html = sample["scoresHtml"]
    for title in ("Wakes", "Doing (tw)", "Mail", "Todo", "Hold", "Connect", "Platform", "System commands"):
        assert f">{title}</a>" in html and f"<span>{title}</span>" in html
    assert "collapsed" not in html
    assert not re.search(r"<[^>]*\shidden[\s>=]", html)  # no hidden attribute on any row or group


def test_seeded_rows_show_written_and_seed_tag(sample):
    wakes = _group(sample["scoresHtml"], "wakes")
    assert "Nov 11 12:05" in wakes  # updated "2026-11-11 12:05:00.123456"
    assert "si-tag\">seed" in wakes
    assert "Nothing filed yet" not in wakes
    by = {g["id"]: g["rows"] for g in sample["groups"]}
    # office wake rows have an empty owner and land on the roster
    assert ["mill-office.wasted_wake_n", "Office", "ok"] in by["wakes"]
    # keys in code that the seed did not file still read "not filed"
    assert ["todo.open_age_ms", "Office", "not filed"] in by["todo"]
    assert ["hold.expired_n", "Office", "not filed"] in by["hold"]


def test_bare_payload_keeps_legend_fallbacks(bare):
    by = {g["id"]: g["rows"] for g in bare["groups"]}
    assert ["mail.send_to_wake_ms", "Office", "not filed"] in by["mail"]
    assert ["stale wake-done", "\u2014", "no kpi"] in by["wakes"]
    assert all(r[2] in ("not filed", "no kpi") for r in by["wakes"])
    assert "other" not in by
    html = bare["scoresHtml"]
    assert "Nothing filed yet on this Office." in html
    assert "not sent" in html
    assert "/hr" not in html  # no activity route -> no invented rate
    assert bare["ctxKeys"] == []
    spend = bare["spendHtml"]
    assert "unavailable" in spend and "omitted" in spend
    assert "\u2014 not fetched" in spend  # transitions


def test_doing_tags_partial_previous_run_and_outlier(sample):
    doing = _group(sample["scoresHtml"], "doing")
    assert "partial, run open" in doing
    assert "previous run" in doing
    assert doing.count("outlier: multi-day, shown as stored") == 2
    assert "3 finished \u00b7 1 active \u00b7 2 failed" in doing
    assert "/hr" not in doing  # durations carry no rate column
    assert sample["tally"] == {"finished": 3, "active": 1, "failed": 2, "desks": 6}
    assert sample["fmt"] == ["40 ms", "1.1s", "4d 5h 43m"]
    assert "10215.395 ms" in _run_raw()  # stored ms shown without float noise


def _run_raw() -> str:
    js = (
        "global.window=global;const fs=require('fs');"
        f"(0,eval)(fs.readFileSync({json.dumps(str(SCORE))},'utf8'));"
        f"(0,eval)(fs.readFileSync({json.dumps(str(IMPACT))},'utf8'));"
        "const k=[{kpi:'doing.task.dwell_active_ms',owner:'auditor',value:'10215.394999999999'}];"
        "process.stdout.write(scoreSpendHtml(scoreSpendModel(k,{}),0));"
    )
    return subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout


def test_activity_buckets_today_by_type_and_task_only(sample):
    assert sample["actKeys"] == ["doing", "hold", "mail", "todo", "wake"]
    wake = sample["wake"]
    assert wake["today"] == 6  # yesterday's 23:00 bucket is not today
    assert round(wake["rate"], 2) == 0.5  # 6 items by 12:00
    # card 1207: every doing row is a tw run, so the all-type read counts doing (no act=task read)
    assert sample["doingBuilder"]["today"] == 6
    wakes = _group(sample["scoresHtml"], "wakes")
    assert "~0.5/hr" in wakes and "si-spark" in wakes
    hold = _group(sample["scoresHtml"], "hold")
    assert ">0</td>" in hold  # route answered with no hold rows: 0, not a dash


def test_no_activity_route_leaves_doing_unfetched():
    out = _run("noactivity")
    assert "doing" not in out["actKeys"]
    assert out["doingBuilder"] is None


def test_spend_sums_finished_runs_only(sample):
    sums = sample["sums"]
    assert sums["builder"]["n"] == 2 and sums["builder"]["dwell_active_ms"] == 2340000
    assert sums["gardener"]["dwell_active_ms"] == 2400000
    assert "grok-tui" not in sums  # phase=start (open run) never sums
    assert sample["office"] == {"n": 4, "seed": 4, "dwell_active_ms": 177540000}
    spend = sample["spendHtml"]
    assert "sum of 4 finished runs (4 seeded stub)" in spend
    assert "2 runs, 2 seed" in spend
    assert "token" not in spend.lower() and "usd" not in spend.lower()
    trans = spend.split("Transitions", 1)[1]
    assert "doing pairs." in trans and "held" not in trans  # doing pairs preferred
    assert "context only" in spend
