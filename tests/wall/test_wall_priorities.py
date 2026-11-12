# -*- coding: utf-8 -*-
"""PRIORITIES tab (card 1153, first slice): each desk's ranked list on the Wall.

Runs default/priorities/priorities-paint.js in Node against
tests/wall/priorities_fixture.json, a labeled SAMPLE in the GET /api/v1/labels
contract shape asked of Loop 2 on card 1153. The fixture keeps three real past
cases from dogfood-office label reads (2026-11-11): the validator and wall-ui lists
each hold one parked card, so their connect prints no focus line, and
human-priorities has cards 985 and 1112 tied at ord 0.

The Wall column and the connect focus line (client/focus.py) must pick the same
top 5 from the same data (validator letter 5566); test_wall_column_matches_connect_focus
runs both on the fixture.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from agent_coord.client import focus

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
PRIO = ROOT / "default" / "priorities" / "priorities-paint.js"
FIXTURE = Path(__file__).resolve().parent / "priorities_fixture.json"
LAZY = ROOT / "lib" / "lazy.js"
BOOT = ROOT / "default" / "boot.js"
OPTIONAL = ("eta_at", "needs_human", "last_activity_at", "last_activity_kind", "progress", "tw_ms")

HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const fx = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const mode = process.argv[3];
const optional = JSON.parse(process.argv[4]);
let rows = fx.rows;
if (mode === 'bare') {
  rows = rows.map(r => {
    const c = Object.assign({}, r);
    delete c.updated;
    if (c.card) { c.card = Object.assign({}, c.card); optional.forEach(k => delete c.card[k]); }
    return c;
  });
}
if (mode === 'unavailable') rows = null;
const m = prioModel({ rows: rows, desks: fx.desks, now: Date.parse(fx.now) });
const cards = rows ? prioCards(rows) : [];
const top = {};
fx.desks.concat(['human-priorities']).forEach(d => {
  top[d] = prioFocusTop(cards, d, prioRank(rows || [], d)).map(c => c.id);
});
process.stdout.write(JSON.stringify({
  available: m.available,
  served: m.served,
  columns: (m.columns || []).map(c => ({
    desk: c.desk, top: c.top.map(r => r.id), rows: c.top, empty: c.empty, conflicts: c.conflicts,
    drift: c.drift, more: c.more, held: c.held, parked: c.parked, ranked: c.ranked, reranked: c.rerankedAt != null,
  })),
  human: m.human,
  top: top,
  html: prioHtml(m),
}));
"""


def _run(mode: str) -> dict:
    env = dict(os.environ, TZ="America/Los_Angeles")
    out = subprocess.run(
        ["node", "-e", HARNESS, str(PRIO), str(FIXTURE), mode, json.dumps(OPTIONAL)],
        capture_output=True, text=True, check=True, env=env,
    ).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sample() -> dict:
    return _run("sample")


@pytest.fixture(scope="module")
def bare() -> dict:
    return _run("bare")


def _col(got: dict, desk: str) -> dict:
    return next(c for c in got["columns"] if c["desk"] == desk)


def _connect_top(fx: dict, desk: str) -> list[int]:
    """client/focus.connect_block on the fixture: the board hides done cards, each card wears its labels."""
    labels: dict[int, list[str]] = {}
    cards: dict[int, dict] = {}
    for r in fx["rows"]:
        if r["type"] != "todo":
            continue
        labels.setdefault(r["id"], []).append(r["label"])
        c = r["card"]
        cards[r["id"]] = {
            "id": r["id"], "project_id": c["roster"], "need_id": c["need"],
            "status": c["status"], "volunteer": c["volunteer"],
        }
    board = [dict(c, labels=labels[i]) for i, c in cards.items() if c["status"] != "done"]

    def call(body: dict) -> dict:
        if body["verb"] == "member":
            return {"ok": True, "result": [{"slot": "Office"}]}
        if body["verb"] == "todo":
            return {"ok": True, "result": {"cards": board}}
        if body["verb"] == "trail":
            rows = [{"type": r["type"], "id": r["id"], "ord": r["ord"]} for r in fx["rows"] if r["label"] == body["label"]]
            return {"ok": True, "result": {"rows": rows}}
        raise AssertionError(body)

    got = focus.connect_block(call, desk)
    return [c["id"] for c in got["cards"]] if got else []


def test_fixture_is_labeled_sample_and_covers_each_focus_filter(fx):
    assert fx["_sample"].startswith("SAMPLE")
    builder = {r["id"]: r for r in fx["rows"] if r["label"] == "builder"}
    st = {i: r["card"]["status"] for i, r in builder.items()}
    assert "done" in st.values() and "parked" in st.values()
    assert any(r["card"]["volunteer"] not in ("", "builder") for r in builder.values())  # held by another desk
    assert any(r["ord"] == focus.UNPLACED for r in builder.values())  # unplaced
    ords = [r["ord"] for r in builder.values()]
    assert len(ords) != len(set(ords))  # a tie, broken by card id
    assert sum(1 for r in builder.values() if focus.actionable(r["card"], "builder")) > focus.FOCUS_TOP


def test_wall_column_matches_connect_focus(fx, sample):
    """Validator 5566: the Wall column and connect's focus line pick the same top 5 from the same data."""
    assert sample["top"]["builder"] == [993, 282, 950, 937, 1141]
    for desk in fx["desks"] + ["human-priorities"]:
        assert sample["top"][desk] == _connect_top(fx, desk), desk
        if desk in fx["desks"]:
            assert _col(sample, desk)["top"] == _connect_top(fx, desk), desk


def test_no_focus_line_on_parked_only_lists(sample):
    """Real past case: the validator and wall-ui lists held one parked card each (dogfood office, 2026-11-11)."""
    for desk in ("validator", "wall-ui"):
        col = _col(sample, desk)
        assert col["top"] == []
        assert col["empty"] == {"why": "1 ranked, all parked", "fix": f"mill label todo <id> {desk} --ord 0"}
    assert _col(sample, "build-ui")["empty"]["why"] == "0 ranked"
    html = sample["html"]
    assert html.count('data-prio-check="no-focus"') == 3
    assert "No focus line: 1 ranked, all parked." in html
    assert "<code>mill label todo &lt;id&gt; validator --ord 0</code>" in html
    for desk in ("builder", "grok-tui", "auditor", "gardener"):
        assert _col(sample, desk)["empty"] is None


def test_tied_ranks_on_human_list_are_a_visible_check(sample):
    """Real past case: human-priorities had cards 985 and 1112 both at ord 0."""
    assert sample["human"]["ties"] == [{"ord": 0, "ids": [985, 1112]}]
    assert '<p class="prio-tie" data-prio-check="tie">tied rank #0: 985, 1112</p>' in sample["html"]


def test_human_top3_missing_from_desk_top5_warns_on_that_desk(sample):
    assert [r["id"] for r in sample["human"]["top"]] == [985, 1112, 826]
    assert _col(sample, "builder")["conflicts"] == [{"id": 985, "ord": 0, "where": "not on this desk's list"}]
    assert _col(sample, "grok-tui")["conflicts"] == [{"id": 1112, "ord": 0, "where": "position 7 on this list"}]
    assert _col(sample, "auditor")["conflicts"] == []
    assert sample["human"]["noDesk"] == [{"id": 826, "ord": 1}]
    assert sample["html"].count('data-prio-check="conflict"') == 2
    assert "unowned shared list" in sample["html"]


def test_row_fields_eta_overdue_and_dimmed_extras(sample):
    rows = {r["id"]: r for r in _col(sample, "builder")["rows"]}
    assert rows[950]["overdue"] == "4h" and rows[993]["overdue"] is None
    assert _col(sample, "auditor")["rows"][0]["overdue"] == "23h"
    assert any(r["needsYou"] for r in _col(sample, "auditor")["rows"])
    html = sample["html"]
    assert "overdue 4h" in html and "needs you" in html
    assert 'title="tw doing time on this card">tw 2h 45m' in html
    assert 'title="progress (card meta)">2/4 steps' in html
    assert _col(sample, "builder")["more"] == 1 and _col(sample, "builder")["held"] == 1


def test_rank_staleness_and_zero_activity_drift(sample):
    assert _col(sample, "auditor")["drift"] == {"id": 890, "days": 6}
    assert "ranked #0, no activity 6d" in sample["html"]
    assert _col(sample, "builder")["drift"] is None  # #0 had tw time an hour ago
    assert _col(sample, "builder")["reranked"] is True
    assert "re-ranked 31h ago" in sample["html"]


def test_fields_the_server_does_not_send_are_left_out(bare):
    assert not any(bare["served"].values())
    html = bare["html"]
    grid = html.split('<div class="prio-grid">', 1)[1]
    for absent in ("ETA", "overdue", "needs you", "re-ranked", "no activity", "steps", "tw "):
        assert absent not in grid, absent
    assert "Not served yet, so not shown: re-rank time, #0 card activity, ETA, needs-you." in html
    assert all(c["drift"] is None for c in bare["columns"])
    # The lists and checks do not depend on the optional fields.
    assert _col(bare, "builder")["top"] == [993, 282, 950, 937, 1141]
    assert html.count('data-prio-check="no-focus"') == 3


def test_route_missing_paints_unavailable_not_empty():
    got = _run("unavailable")
    assert got["available"] is False and got["columns"] == []
    assert 'data-prio-state="unavailable"' in got["html"]
    assert "0 ranked" not in got["html"] and "No focus line" not in got["html"]


def test_tab_is_lazy_and_wired():
    lazy = LAZY.read_text(encoding="utf-8")
    assert '"/priorities/priorities-paint.js?v=' in lazy and '"/priorities/priorities.css?v=' in lazy
    boot = BOOT.read_text(encoding="utf-8")
    assert 'function ensurePrioritiesPaint() { return wallLazyCall("prioritiesPaint", "ensurePrioritiesPaint", ensurePrioritiesPaint, arguments); }' in boot
    assert 'if (name === "priorities") ensurePrioritiesPaint();' in boot
    src = PRIO.read_text(encoding="utf-8")
    assert '"/api/v1/labels?project="' in src
    # Every trusted viewer sees every list: nothing in the paint filters by viewer.
    assert "signed_in" not in src and "/api/v1/me" not in src
