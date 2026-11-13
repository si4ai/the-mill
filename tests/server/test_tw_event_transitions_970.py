"""Card 970 step 3: real-book task transitions and delivery."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


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
    pings = []
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: pings.append((a, k)))

    def event(kind, **kw):
        return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": "recipe", "kind": kind, **kw}, "Office", desk)

    def edges():
        # Card 1098: score last_run rows share the task join_key; doing edges only here.
        return rows(
            cn,
            "SELECT * FROM transition WHERE activity_type='doing' AND join_key=%s ORDER BY id",
            (f"task:{desk}:recipe",),
        )

    return desk, event, edges, pings


def test_birth_then_later_event_has_one_task_and_no_birth_edge(cn, task):
    desk, event, edges, _ = task
    event("start", card=970, title="SECRET", argv=["SECRET"], pattern="SECRET")
    first = edges()
    assert [(e["from_state"], e["to_state"], e["reason"]) for e in first] == [("idle", "active", "tw_start")]
    doing = rows(cn, "SELECT * FROM doing WHERE id=%s", (first[0]["activity_id"],))[0]
    # Card 1207: six columns; the card rides the tw_start meta, never the doing row.
    assert set(doing) == {"type", "id", "created", "desk_id", "roster_id", "text"}
    assert json.loads(first[0]["meta"])["card"] == 970
    assert doing["text"] == ""
    event("start")
    event("stall", cause="quiet")
    assert [e["reason"] for e in edges()] == ["tw_start", "tw_wait"]
    assert {e["activity_id"] for e in edges()} == {doing["id"]}
    assert len(rows(cn, "SELECT * FROM doing WHERE desk_id=%s", (doing["desk_id"],))) == 1


@pytest.mark.parametrize("kind,extra,reason,state", [
    ("exit", {"exit_code": 0}, "tw_finished", "finished"),
    ("exit", {"exit_code": 9}, "tw_failed", "failed"),
    ("crash", {}, "tw_failed", "failed"),
])
@pytest.mark.parametrize("waiting", [False, True])
def test_kind_map_and_terminal_lifecycle(cn, task, kind, extra, reason, state, waiting):
    _, event, edges, _ = task
    event("start")
    event("stall", cause="quiet")
    if not waiting:
        event("resume")
        assert edges()[-1]["reason"] == "tw_resume"
    event(kind, **extra)
    assert edges()[-1]["reason"] == reason
    assert edges()[-1]["to_state"] == state
    assert len({e["activity_id"] for e in edges()}) == 1
    n = len(edges())
    # Replayed or late hops on a terminal watch write nothing and reply ok (card 970 step 4).
    for late in ("start", "stall", "resume", "exit", "crash"):
        assert event(late, exit_code=0, cause="quiet")["ok"] is True
    assert len(edges()) == n
    assert edges()[-1]["to_state"] == state


def test_recipe_one_start_one_exit(cn, task):
    _, event, edges, _ = task
    event("start")
    event("exit", exit_code=0)
    assert [e["reason"] for e in edges()] == ["tw_start", "tw_finished"]
    assert "card" not in json.loads(edges()[0]["meta"] or "{}")


@pytest.mark.parametrize("kind", ["match", "overflow", "retry"])
def test_non_transition_kinds(cn, task, kind):
    _, event, edges, _ = task
    event("start")
    event(kind, cause="pattern", counts={"dropped": 3}, outcome="give_up", attempt=2)
    assert [e["reason"] for e in edges()] == ["tw_start"]


@pytest.mark.parametrize("kind", ["start", "stall", "resume", "match", "exit", "crash", "overflow", "retry"])
@pytest.mark.parametrize("wake", [False, True, None])
def test_wake_kind_gate_uses_existing_path(cn, task, kind, wake):
    _, event, _, pings = task
    if kind != "start":
        event("start")
    if kind == "resume":
        event("stall", wake=False)
    pings.clear()
    event(kind, exit_code=0, **({} if wake is None else {"wake": wake}))
    assert bool(pings) == (kind in {"stall", "match", "exit", "crash"} and wake is not False)


def test_stored_meta_privacy_and_score_values(cn, task):
    desk, event, edges, _ = task
    banned = dict.fromkeys(rpc._TW_EVENT_PRIVACY, "SECRET")
    event("start", **banned, ts="1900-01-01", wake=False)
    event("stall", cause="pattern", **banned, counts={"lines": 3}, wake=False)
    event("resume", wake=False)
    event("exit", exit_code=0, wake=False)
    for edge in edges():
        meta = json.loads(edge["meta"])
        assert not (set(meta) & (set(rpc._TW_EVENT_PRIVACY) | {"wake", "ts"}))
        assert "SECRET" not in json.dumps(meta)
    got = {r["kpi"]: r["value"] for r in rows(cn, "SELECT kpi, value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s", (desk,))}
    assert {"doing.task.dwell_idle_ms", "doing.task.dwell_active_ms", "doing.task.dwell_waiting_ms", "doing.task.wait_by_cause", "doing.task.end_reason"} <= got.keys()
    assert json.loads(got["doing.task.wait_by_cause"])["pattern"] == 1
    assert got["doing.task.end_reason"] == "tw_finished"
    assert all(float(got[f"doing.task.dwell_{s}_ms"]) >= 0 for s in ("idle", "active", "waiting"))
    assert "doing.task.stale_n" not in got and "doing.task.wait_cycle_n" not in got
    assert not any(k.startswith("connect.") for k in got)


def test_metric_counts_emit_without_transition(cn, task):
    desk, event, edges, _ = task
    event("start")
    event("overflow", counts={"dropped": 4})
    event("retry", outcome="give_up", attempt=3)
    got = {r["kpi"]: r["value"] for r in rows(cn, "SELECT kpi, value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s", (desk,))}
    assert got["doing.task.buffer_overflow_n"] == "4"
    assert got["doing.task.retry_give_up_n"] == "1"
    assert len(edges()) == 1


def test_connect_does_not_bump_task_activity(cn, task):
    from agent_coord.server import connect_activity
    _, event, edges, _ = task
    event("start")
    aid = edges()[0]["activity_id"]
    before = rows(cn, "SELECT * FROM activity WHERE type='doing' AND id=%s", (aid,))[0]
    connect_activity._ensure_activity(cn, aid)
    assert rows(cn, "SELECT * FROM activity WHERE type='doing' AND id=%s", (aid,))[0] == before


def test_task_enum_existing_book_migration(cn, task):
    from agent_coord.install import migrate
    cur = cn.cursor()
    try:
        for table, default in (("activity", "create"),):  # card 1207: doing has no act
            cur.execute(f"UPDATE {table} SET act='create' WHERE act='task'")
            cur.execute("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='act'", (table,))
            old = cur.fetchone()[0].replace(",'task'", "")
            cur.execute(f"ALTER TABLE {table} MODIFY act {old} NOT NULL DEFAULT '{default}'")
        cn.commit()
        assert migrate.task_970_needed(cn)
        assert migrate.apply_task_970(cn) == ["migrate_970_task.sql"]
        assert not migrate.task_970_needed(cn)
        assert migrate.apply_task_970(cn) == []
        # The SQL script itself is also a no-op on task-capable books.
        for stmt in migrate.split_script((migrate.sql_dir() / migrate.TASK_970).read_text()):
            cur.execute(stmt)
            if cur.with_rows:
                cur.fetchall()
        assert not migrate.task_970_needed(cn)
        # A partial upgrade is detected, and the real existing-book loader repairs it.
        cur.execute("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='activity' AND COLUMN_NAME='act'")
        old = cur.fetchone()[0].replace(",'task'", "")
        cur.execute(f"ALTER TABLE activity MODIFY act {old} NOT NULL DEFAULT 'create'")
        assert migrate.task_970_needed(cn)
        assert migrate.TASK_970 in migrate.ensure(cn)["applied"]
        assert not migrate.task_970_needed(cn)
        desk = task[0]
        cur.execute("INSERT INTO doing (desk_id) SELECT id FROM name WHERE name=%s AND type='desk'", (desk,))
        aid = cur.lastrowid
        cur.execute("INSERT INTO activity (type, id, desk_id, act) SELECT 'doing', %s, id, 'task' FROM name WHERE name=%s AND type='desk'", (aid, desk))
        cn.commit()
    finally:
        cur.close()


def test_birth_is_idle_before_first_transition_and_rolls_back_on_failure(cn, task, monkeypatch):
    from agent_coord.server import transition
    desk, event, edges, pings = task

    def refuse(cn, **kw):
        assert kw["from_state"].value == "idle"
        assert edges() == []
        born = rows(cn, "SELECT text FROM doing WHERE id=%s", (kw["activity_id"],))[0]
        assert born == {"text": ""}
        raise CoordError("test refused")

    monkeypatch.setattr(transition, "put", refuse)
    with pytest.raises(CoordError, match="test refused"):
        event("start")
    assert edges() == [] and pings == []
    assert rows(cn, "SELECT g.id FROM doing g JOIN name n ON n.id=g.desk_id WHERE n.name=%s", (desk,)) == []


def test_wake_is_deferred_until_outer_commit_and_dropped_on_rollback(cn, task):
    from agent_coord.server.records.db import request_tx
    _, event, edges, pings = task
    event("start")

    def fail():
        event("stall")
        assert pings == []
        raise CoordError("test rollback")

    with pytest.raises(CoordError, match="test rollback"):
        request_tx(cn, fail)
    assert [e["reason"] for e in edges()] == ["tw_start"]
    assert pings == []
    request_tx(cn, lambda: event("stall"))
    assert len(pings) == 1


@pytest.mark.parametrize("extra", [
    {"counts": {"stdout": 4}},
    {"counts": {"lines": {"sample": "SECRET"}}},
    {"cause": "SECRET pattern text"},
    {"exit_code": True},
])
def test_bad_meta_is_refused_before_birth(cn, task, extra):
    _, event, edges, pings = task
    with pytest.raises(CoordError):
        event("start", **extra)
    assert edges() == [] and pings == []


def test_no_mapped_event_can_birth_without_start(cn, task):
    _, event, edges, pings = task
    with pytest.raises(CoordError, match="start required"):
        event("exit", exit_code=0)
    assert edges() == [] and pings == []


def test_wrapper_clock_does_not_set_dwell(cn, task):
    desk, event, edges, _ = task
    event("start", ts="1900-01-01T00:00:00Z")
    event("exit", exit_code=0, ts="2999-01-01T00:00:00Z")
    got = rows(cn, "SELECT value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s AND kpi='doing.task.dwell_active_ms'", (desk,))[0]
    assert 0 <= float(got["value"]) < 60_000
    assert all("ts" not in json.loads(e["meta"]) for e in edges())


def scores(cn, desk):
    return {r["kpi"]: r["value"] for r in rows(cn, "SELECT kpi, value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s", (desk,))}


@pytest.mark.parametrize("kind,extra", [("exit", {"exit_code": 0}), ("exit", {"exit_code": 3}), ("crash", {})])
def test_replayed_start_and_terminal_hop_write_nothing(cn, task, kind, extra):
    desk, event, edges, pings = task
    banned = dict.fromkeys(rpc._TW_EVENT_PRIVACY, "SECRET")
    assert event("start", card=970, **banned)["ok"] is True
    assert event("start", card=970, **banned)["ok"] is True
    assert [e["reason"] for e in edges()] == ["tw_start"]
    assert event(kind, **extra)["ok"] is True
    after, n, woke = scores(cn, desk), len(edges()), len(pings)
    for _ in range(2):
        reply = event(kind, **extra)
        assert reply["ok"] is True and "code" not in reply
    assert len(edges()) == n and scores(cn, desk) == after
    assert len(pings) == woke  # a replay that writes nothing does not ping again
    assert len(rows(cn, "SELECT g.id FROM doing g JOIN name n ON n.id=g.desk_id WHERE n.name=%s", (desk,))) == 1
    for edge in edges():
        assert "SECRET" not in edge["meta"]
        assert not set(json.loads(edge["meta"])) & set(rpc._TW_EVENT_PRIVACY)


def test_replayed_stall_and_resume_are_noops_but_later_hops_still_write(cn, task):
    desk, event, edges, pings = task
    event("start")
    pings.clear()
    assert event("stall", cause="quiet")["ok"] is True
    assert event("stall", cause="quiet")["ok"] is True
    assert len(pings) == 1
    assert event("resume")["ok"] is True
    assert event("resume")["ok"] is True
    assert [e["reason"] for e in edges()] == ["tw_start", "tw_wait", "tw_resume"]
    # A later stall after resume is a new hop, and a later resume after it too.
    assert event("stall", cause="quiet")["ok"] is True
    assert event("resume")["ok"] is True
    assert [e["reason"] for e in edges()] == ["tw_start", "tw_wait", "tw_resume", "tw_wait", "tw_resume"]
    assert len(pings) == 2
    assert json.loads(scores(cn, desk)["doing.task.wait_by_cause"]) == {"quiet": 2}
    assert not {"tw_stale", "wait_cycle", "clear"} & {e["reason"] for e in edges()}
