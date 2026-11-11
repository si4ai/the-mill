# -*- coding: utf-8 -*-
"""Score tab redesign: Scores in impact groups, Spend as tw doing time.

Runs default/score/score-impact.js in Node against tests/wall/score_impact_fixture.json
(a labeled sample: doing values from the review, wake/activity/transition/run shapes
fake until the live payload lands). Checks the agreed rules from the design review:
every row listed in group order, gaps never painted as 0, rates only from activity,
time only from doing.task.dwell_*_ms, and no total without finished-run history.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score.js"
IMPACT = ROOT / "default" / "score" / "score-impact.js"
FIXTURE = Path(__file__).resolve().parent / "score_impact_fixture.json"

HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
(0, eval)(fs.readFileSync(process.argv[2], 'utf8'));
const fx = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const mode = process.argv[4];
const now = Date.parse(fx.now);
let kpis = fx.kpis, ctx = fx.ctx;
if (mode === 'live') {
  kpis = kpis.filter(k => !/^(wake\.|mill-office\.wasted|cards$)/.test(k.kpi)).map(k => { const c = Object.assign({}, k); delete c.updated; return c; });
  ctx = {};
}
const m = scoreImpactModel(kpis, ctx, now);
const sm = scoreSpendModel(kpis, ctx);
process.stdout.write(JSON.stringify({
  groups: m.groups.map(g => ({ id: g.def.id, rows: g.rows.map(r => [r.kpi, r.desk, r.state]) })),
  tally: m.tally,
  scoresHtml: scoreImpactHtml(m),
  spendHtml: scoreSpendHtml(sm, now),
  office: sm.office,
  sums: sm.sums,
  fmt: [scoreImpactFmtMs(40), scoreImpactFmtMs(1086), scoreImpactFmtMs(366220041.908)],
  act: scoreImpactActivity(ctx, 'wake', 'Office', now),
}));
"""


def _run(mode: str = "sample") -> dict:
    out = subprocess.run(
        ["node", "-e", HARNESS, str(SCORE), str(IMPACT), str(FIXTURE), mode],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def sample() -> dict:
    return _run("sample")


@pytest.fixture(scope="module")
def live() -> dict:
    return _run("live")


def test_fixture_is_labeled_sample():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fx["_sample"].startswith("SAMPLE")
    assert "fake" in fx["ctx"]["sample"]


def test_groups_in_impact_order_every_row_listed(sample):
    ids = [g["id"] for g in sample["groups"]]
    assert ids == ["wakes", "doing", "mail", "todo", "hold", "connect", "platform", "system", "other"]
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    listed = sum(1 for g in sample["groups"] for r in g["rows"] if r[2] in ("ok", "omitted"))
    assert listed == len(fx["kpis"])
    html = sample["scoresHtml"]
    for title in ("Wakes", "Doing (tw)", "Mail", "Todo", "Hold", "Connect", "Platform", "System commands"):
        assert f">{title}</a>" in html and f"<span>{title}</span>" in html
    assert "collapsed" not in html
    assert not re.search(r"<[^>]*\shidden[\s>=]", html)  # no hidden attribute on any row or group


def test_unfiled_keys_and_no_kpi_rows(live):
    by = {g["id"]: g["rows"] for g in live["groups"]}
    assert ["mail.send_to_wake_ms", "Office", "not filed"] in by["mail"]
    assert ["connect.reconnect_n", "Office", "not filed"] in by["connect"]
    assert ["stale wake-done", "\u2014", "no kpi"] in by["wakes"]
    assert all(r[2] in ("not filed", "no kpi") for r in by["wakes"])
    assert "Nothing filed yet on this Office." in live["scoresHtml"]
    assert "other" not in by  # Other shows only when something falls outside the groups


def test_gaps_never_zero_and_written_not_sent(live):
    html = live["scoresHtml"]
    assert "not sent" in html
    assert "~0" not in html and "/hr" not in html  # no activity fetched -> no invented rate
    spend = live["spendHtml"]
    assert "unavailable" in spend
    assert "omitted" in spend  # dwell_waiting_ms missing on most desks


def test_doing_tags_partial_previous_run_and_outlier(sample):
    html = sample["scoresHtml"]
    doing = html.split('id="si-g-doing"', 1)[1].split("</section>", 1)[0]
    assert "partial, run open" in doing
    assert "previous run" in doing
    assert doing.count("outlier: multi-day, shown as stored") == 2
    assert "3 finished \u00b7 1 active \u00b7 2 failed" in doing
    assert "/hr" not in doing  # durations carry no rate column
    assert sample["tally"] == {"finished": 3, "active": 1, "failed": 2, "desks": 6}
    assert sample["fmt"] == ["40 ms", "1.1s", "4d 5h 43m"]


def test_rate_and_spark_from_activity_only(sample):
    act = sample["act"]
    assert act["today"] == 28 and round(act["rate"], 2) == round(28 / 12, 2)
    wakes = sample["scoresHtml"].split('id="si-g-wakes"', 1)[1].split("</section>", 1)[0]
    assert "~2.3/hr" in wakes and "si-spark" in wakes


def test_spend_time_only_from_doing_leaves_and_finished_runs(sample):
    # Only phase=finished runs sum; the active start and the failed run do not.
    assert sample["sums"]["builder"]["n"] == 2
    assert sample["sums"]["builder"]["dwell_active_ms"] == 3486
    assert "validator" not in sample["sums"] and "auditor" not in sample["sums"]
    assert sample["office"] == {"n": 4, "dwell_active_ms": 4798}  # 1086 + 2400 + 1272 + 40
    spend = sample["spendHtml"]
    assert "sum of 4 finished runs" in spend
    assert "token" not in spend.lower() and "usd" not in spend.lower()
    trans = spend.split("Transitions", 1)[1]
    assert "doing pairs." in trans and "sent" not in trans  # doing pairs preferred
    assert re.search(r"context only", spend)
