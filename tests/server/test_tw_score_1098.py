"""Card 1098 item 3: score transitions on tw start/finish/fail; last_run ledger."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from agent_coord.server import transition as tr
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join
from agent_coord.server.transition_enums import ActivityType, Reason, State


def rows(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


@pytest.fixture
def task(cn, monkeypatch):
    desk = "builder-" + uuid4().hex[:8]
    join.upsert(cn, "Office", desk, "", "a" * 64)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)

    def event(kind, **kw):
        return rpc._h_tw_event(
            SimpleNamespace(_cn=cn),
            {"watch_id": "recipe", "kind": kind, **kw},
            "Office",
            desk,
        )

    def score_edges():
        return rows(
            cn,
            "SELECT * FROM transition WHERE activity_type='score'"
            " AND join_key=%s ORDER BY id",
            (f"task:{desk}:recipe",),
        )

    def last_run():
        got = rows(
            cn,
            "SELECT value FROM score JOIN name ON name.id=score.desk_id"
            " WHERE name.name=%s AND kpi='doing.task.last_run'",
            (desk,),
        )
        return got[0]["value"] if got else None

    return desk, event, score_edges, last_run


@pytest.mark.sql
def test_start_writes_score_none_to_live(cn, task):
    desk, event, score_edges, last_run = task
    event("start")
    edges = score_edges()
    assert len(edges) == 1
    assert (edges[0]["from_state"], edges[0]["to_state"], edges[0]["reason"]) == (
        "none",
        "live",
        "score_point",
    )
    meta = json.loads(edges[0]["meta"])
    assert meta["phase"] == "start"
    assert meta["watch_id"] == "recipe"
    assert last_run() == "active"


@pytest.mark.sql
def test_exit_zero_live_to_live_finished(cn, task):
    _, event, score_edges, last_run = task
    event("start")
    event("exit", exit_code=0)
    edges = score_edges()
    assert len(edges) == 2
    assert (edges[1]["from_state"], edges[1]["to_state"]) == ("live", "live")
    meta = json.loads(edges[1]["meta"])
    assert meta["phase"] == "finished"
    assert meta["exit_code"] == 0
    assert meta.get("end_reason") == "tw_finished"
    assert last_run() == "finished"


@pytest.mark.sql
def test_exit_nonzero_phase_failed(cn, task):
    _, event, score_edges, last_run = task
    event("start")
    event("exit", exit_code=3)
    edges = score_edges()
    assert len(edges) == 2
    meta = json.loads(edges[1]["meta"])
    assert meta["phase"] == "failed"
    assert meta["exit_code"] == 3
    assert meta.get("end_reason") == "tw_failed"
    assert last_run() == "failed"


@pytest.mark.sql
def test_replayed_exit_adds_no_score_row(cn, task):
    _, event, score_edges, _ = task
    event("start")
    event("exit", exit_code=0)
    n = len(score_edges())
    assert event("exit", exit_code=0)["ok"] is True
    assert len(score_edges()) == n


def test_task_event_score_put_once_per_lifecycle_kind(monkeypatch):
    """No-MySQL: score tr.put once for start/exit/crash; never for stall/resume/overflow/retry."""
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    score_puts: list[dict] = []
    score_put_n = {"n": 0}
    state_box = {"state": "idle"}

    def fake_call(cn, name, args=()):
        if name == "mill_doing_task":
            return [{
                "id": 42,
                "desk_id": 7,
                "state": state_box["state"],
                "created": created,
            }]
        raise AssertionError(f"unexpected call {name}")

    def fake_put(cn, **kw):
        if kw["activity_type"] == ActivityType.score:
            score_puts.append(kw)
            score_put_n["n"] += 1
        else:
            state_box["state"] = kw["to_state"].value

    def fake_upsert(cn, project, desk, kpi, value="", target="", note=""):
        assert kpi.startswith("doing.task.")
        if kpi == "doing.task.last_run":
            return [{"id": 99, "kpi": kpi, "updated": created}]
        return [{"id": 100, "kpi": kpi, "updated": created}]

    class _Cur:
        def __init__(self):
            self._looking_prior = False

        def execute(self, sql, args=()):
            # Prior-score probe uses activity_type=%s with the score id.
            self._looking_prior = (
                "activity_type=%s" in sql and "activity_id=%s" in sql and "ORDER BY at" in sql
            )

        def fetchall(self):
            return []

        def fetchone(self):
            if self._looking_prior:
                return {"x": 1} if score_put_n["n"] > 0 else None
            return None

        def close(self):
            return None

    cn = MagicMock()
    cn.cursor.return_value = _Cur()

    monkeypatch.setattr(doing, "call", fake_call)
    monkeypatch.setattr("agent_coord.server.transition.put", fake_put)
    monkeypatch.setattr("agent_coord.server.records.score.upsert", fake_upsert)

    def run(kind, **meta_extra):
        score_puts.clear()
        meta = {"watch_id": "w1", "kind": kind, "desk": "builder", **meta_extra}
        return doing.task_event(cn, "builder", meta)

    state_box["state"] = "idle"
    assert run("start") == "wrote"
    assert len(score_puts) == 1
    assert score_puts[0]["from_state"] == State.none
    assert score_puts[0]["to_state"] == State.live
    assert score_puts[0]["reason"] == Reason.score_point
    assert score_puts[0]["meta"]["phase"] == "start"

    state_box["state"] = "active"
    assert run("exit", exit_code=0) == "wrote"
    assert len(score_puts) == 1
    assert score_puts[0]["from_state"] == State.live
    assert score_puts[0]["meta"]["phase"] == "finished"

    state_box["state"] = "active"
    assert run("exit", exit_code=3) == "wrote"
    assert len(score_puts) == 1
    assert score_puts[0]["meta"]["phase"] == "failed"
    assert score_puts[0]["meta"]["exit_code"] == 3

    state_box["state"] = "active"
    assert run("crash", cause="lost") == "wrote"
    assert len(score_puts) == 1
    assert score_puts[0]["meta"]["phase"] == "failed"
    assert score_puts[0]["meta"]["cause"] == "lost"

    for kind, extra in (
        ("stall", {"cause": "quiet"}),
        ("resume", {}),
        ("overflow", {"counts": {"dropped": 1}}),
        ("retry", {}),
    ):
        score_puts.clear()
        if kind == "stall":
            state_box["state"] = "active"
        elif kind == "resume":
            state_box["state"] = "waiting"
        else:
            state_box["state"] = "active"
        out = run(kind, **extra)
        assert out in ("wrote", "metric")
        assert score_puts == [], kind


def test_default_transition_pairs_hold_no_score(monkeypatch, tmp_path):
    """Guard: score:live/live must not be a default compress pair (#371 meta drop)."""
    from agent_coord.config import transition_pairs

    monkeypatch.delenv("AGENT_COORD_TRANSITION_PAIRS", raising=False)
    monkeypatch.delenv("AGENT_COORD_CONFIG", raising=False)
    # Empty config so DEFAULT_TRANSITION_PAIRS wins.
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    monkeypatch.setenv("AGENT_COORD_CONFIG", str(cfg))
    pairs = transition_pairs()
    assert not any(typ == "score" for typ, _states in pairs)
