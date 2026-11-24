"""Card 1289: run bytes on the real book, and the per-card and per-PR rollup."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def _rows(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


@pytest.fixture
def desk(cn, monkeypatch):
    name = "builder-" + uuid4().hex[:8]
    join.upsert(cn, "Office", name, "", "a" * 64)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    return name


def _event(cn, desk, wid, kind, **kw):
    return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", desk)


def _meta(cn, desk, wid, reason):
    got = _rows(cn, "SELECT meta FROM transition WHERE activity_type='doing' AND join_key=%s AND reason=%s",
                (f"task:{desk}:{wid}", reason))
    assert len(got) == 1
    return json.loads(got[0]["meta"])


def _one(rows, key, value):
    hit = [r for r in rows if r[key] == value]
    assert len(hit) == 1, rows
    return hit[0]


def _card():
    return 10**6 + int(uuid4().hex[:6], 16)


@pytest.mark.parametrize("kind,extra,reason", [
    ("exit", {"exit_code": 0}, "tw_finished"),
    ("exit", {"exit_code": 2}, "tw_failed"),
    ("crash", {"cause": "lost"}, "tw_failed"),
])
def test_terminal_meta_carries_bytes(cn, desk, kind, extra, reason):
    wid = "w" + uuid4().hex[:6]
    _event(cn, desk, wid, "start", card=_card(), pr=9001)
    _event(cn, desk, wid, kind, bytes_in=120, bytes_out=4500, **extra)
    meta = _meta(cn, desk, wid, reason)
    assert (meta["bytes_in"], meta["bytes_out"]) == (120, 4500)
    start = _meta(cn, desk, wid, "tw_start")
    assert start["pr"] == 9001 and isinstance(start["card"], int)


def test_rollup_sums_finished_failed_crash_and_open_runs(cn, desk):
    card, pr = _card(), _card()
    plan = [("a", "exit", {"exit_code": 0}, 10, 100), ("b", "exit", {"exit_code": 1}, 20, 200),
            ("c", "crash", {"cause": "lost"}, 30, 300)]
    for wid, kind, extra, bin_, bout in plan:
        _event(cn, desk, wid + str(card), "start", card=card, pr=pr)
        _event(cn, desk, wid + str(card), kind, bytes_in=bin_, bytes_out=bout, **extra)
    # A crash with no counts (reconcile) and a run still open count as runs with no bytes.
    _event(cn, desk, "d" + str(card), "start", card=card)
    _event(cn, desk, "d" + str(card), "crash", cause="reconcile")
    _event(cn, desk, "e" + str(card), "start", card=card)
    # Pin run a to 90 seconds so the minutes are exact.
    cur = cn.cursor()
    cur.execute("UPDATE transition e JOIN transition s ON s.activity_id = e.activity_id"
                " AND s.activity_type = 'doing' AND s.reason = 'tw_start' SET e.at = s.at + INTERVAL 90 SECOND"
                " WHERE e.activity_type = 'doing' AND e.join_key = %s AND e.reason = 'tw_finished'",
                (f"task:{desk}:a{card}",))
    cur.close()
    by_card = _one(doing.run_rollup(cn, "card", limit=1000), "card", card)
    assert (by_card["runs"], by_card["bytes_in"], by_card["bytes_out"]) == (5, 60, 600)
    assert 1.5 <= by_card["run_min"] < 1.6
    by_pr = _one(doing.run_rollup(cn, "pr", limit=1000), "pr", pr)
    assert (by_pr["runs"], by_pr["bytes_in"], by_pr["bytes_out"]) == (3, 60, 600)


def test_repeat_start_adds_card_and_pr_to_the_one_start(cn, desk):
    card = _card()
    doing.open_call(cn, desk, "early")  # a child's mill call opens the run first (card 1223)
    _event(cn, desk, "early", "start", card=card, pr=77)
    start = _meta(cn, desk, "early", "tw_start")
    assert (start["card"], start["pr"]) == (card, 77)
    _event(cn, desk, "early", "exit", exit_code=0, bytes_in=1, bytes_out=2)
    assert _one(doing.run_rollup(cn, "card", limit=1000), "card", card)["bytes_out"] == 2


def test_rollup_skips_old_runs_and_refuses_unknown_keys(cn, desk):
    card = _card()
    _event(cn, desk, "old" + str(card), "start", card=card)
    cur = cn.cursor()
    cur.execute("UPDATE transition SET at = at - INTERVAL 40 DAY WHERE activity_type = 'doing' AND join_key = %s",
                (f"task:{desk}:old{card}",))
    cur.close()
    assert [r for r in doing.run_rollup(cn, "card", limit=1000) if r["card"] == card] == []
    assert _one(doing.run_rollup(cn, "card", days=60, limit=1000), "card", card)["runs"] == 1
    with pytest.raises(ValueError):
        doing.run_rollup(cn, "desk")


def test_cards_score_view_carries_the_rollup(cn, desk):
    card = _card()
    _event(cn, desk, "v" + str(card), "start", card=card, pr=4242)
    _event(cn, desk, "v" + str(card), "exit", exit_code=0, bytes_in=3, bytes_out=4)
    out = rpc._cards_score_view(SimpleNamespace(_cn=cn), {"score": "cards"}, "Office", desk)
    runs = out["tw_runs"]
    assert runs["days"] == 30
    assert set(runs) == {"days", "by_card", "by_pr"}
    assert {"runs", "bytes_in", "bytes_out", "run_min"} <= set(runs["by_card"][0])
