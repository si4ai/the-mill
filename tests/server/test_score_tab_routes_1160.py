"""Card 1160: the Wall Score tab's two server routes, plus score.updated.

GET /api/v1/activity-buckets?project=R[&bucket=min|hour|day][&since=][&type=][&act=]
GET /api/v1/score-runs?project=R[&phase=start|finished|failed]

Both answer {rows, next} (the list key the Score tab pins, letter 5500). Times
are naive book-clock iso6. The route checks run without a book; the seeded
cases at the bottom read a real one.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

BUCKET_KEYS = {"updated", "type", "act", "desk", "desk_id", "roster", "items", "id"}


class _Office:
    def __init__(self, cn=None):
        self._cn = cn
        self._tokens: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client(monkeypatch, cn=None) -> TestClient:
    import agent_coord.server.middleware as mw
    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(mw, "_office", lambda **k: _Office(cn))
    root = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))


@pytest.mark.parametrize("url,word", [
    ("/api/v1/activity-buckets", "project"),
    ("/api/v1/score-runs", "project"),
    ("/api/v1/activity-buckets?project=a;b", "project"),  # card 1193: a comma list is allowed
    ("/api/v1/activity-buckets?project=Office&role=x", "project"),
    ("/api/v1/activity-buckets?project=Office&bucket=week", "bucket"),
    ("/api/v1/activity-buckets?project=Office&type=letter", "type"),
    ("/api/v1/activity-buckets?project=Office&act=Task;", "act"),
    ("/api/v1/activity-buckets?project=Office&since=yesterday", "since"),
    ("/api/v1/activity-buckets?project=Office&since=2026-11-11T00:00:00Z", "since"),
    ("/api/v1/score-runs?project=Office&phase=done", "phase"),
])
def test_refusals_are_400_and_never_read_the_book(monkeypatch, url, word) -> None:
    def boom(*a, **k):
        raise AssertionError("a refused read must not query the book")

    monkeypatch.setattr("agent_coord.server.records.activity.buckets", boom)
    monkeypatch.setattr("agent_coord.server.records.score.runs", boom)
    r = _client(monkeypatch).get(url)
    assert r.status_code == 400, r.text
    assert word in r.json()["error"]


def test_activity_buckets_shape_params_and_paging(monkeypatch) -> None:
    seen: list = []
    canned = [
        {"updated": "2026-11-11 09:00:00.000000", "type": "doing", "act": "task", "desk": "builder",
         "desk_id": 3, "roster": "Office", "items": 4},
        {"updated": "2026-11-11 10:00:00.000000", "type": "doing", "act": "task", "desk": "builder",
         "desk_id": 3, "roster": "Office", "items": 2},
    ]

    def fake(cn, roster, grain, since, type_s, act):
        seen.append((roster, grain, since, type_s, act))
        return [dict(r) for r in canned]

    monkeypatch.setattr("agent_coord.server.records.activity.buckets", fake)
    client = _client(monkeypatch)
    url = "/api/v1/activity-buckets?project=Office&limit=1&bucket=hour&type=doing&act=task&since=2026-11-11T00:00:00"
    body = client.get(url).json()
    assert seen[-1] == ("Office", "hour", datetime(2026, 11, 11), "doing", "task")
    assert body["bucket"] == "hour" and body["parts"] == ["activity-buckets"]
    assert len(body["rows"]) == 1 and set(body["rows"][0]) == BUCKET_KEYS
    assert body["rows"][0]["items"] == 4
    assert body["next"] == body["rows"][0]["id"]
    rest = client.get(url + "&cursor=" + body["next"]).json()
    assert [r["items"] for r in rest["rows"]] == [2] and rest["next"] is None
    # Defaults: hour buckets, no since (the book picks its own window), no filters.
    client.get("/api/v1/activity-buckets?project=Office")
    assert seen[-1] == ("Office", "hour", None, "", "")


def test_score_runs_shape_and_phase(monkeypatch) -> None:
    seen: list = []
    canned = [
        {"id": 9, "desk": "builder", "phase": "finished", "last_run": "finished",
         "at": "2026-11-11 09:10:00.000000", "watch_id": "w1", "end_reason": "tw_finished",
         "dwell_active_ms": 540000},
    ]

    def fake(cn, roster, phase):
        seen.append((roster, phase))
        return [dict(r) for r in canned]

    monkeypatch.setattr("agent_coord.server.records.score.runs", fake)
    body = _client(monkeypatch).get("/api/v1/score-runs?project=Office&phase=finished").json()
    assert seen == [("Office", "finished")]
    assert body["rows"] == canned and body["next"] is None
    assert body["parts"] == ["score-runs"]


def test_scores_rows_carry_updated(monkeypatch) -> None:
    from agent_coord.server.records import floor

    stamp = datetime(2026, 11, 11, 12, 5, 0, 123456)
    monkeypatch.setattr("agent_coord.server.admin.guard.office_name", lambda cn: "Office")
    monkeypatch.setattr(floor, "_score_by_aff", lambda cn, names: [("Office", [
        {"id": 1, "roster": "Office", "roster_id": 1, "kpi": "wake.wakes_n", "value": "3",
         "target": "", "note": "", "desk": "builder", "updated": stamp},
    ])])
    rows = floor.build_scores(None, ["Office"], {"Office"})
    assert rows[0]["updated"] == "2026-11-11 12:05:00.123456"


# --- seeded book ---------------------------------------------------------


def _desk(cn) -> str:
    from agent_coord.server.records import join

    desk = "b1160-" + uuid4().hex[:8]
    join.upsert(cn, "Office", desk, "", "a" * 64, "reviewing")
    cn.commit()
    return desk


def _tw(cn, monkeypatch, desk: str, watch: str, *kinds: tuple[str, dict]) -> None:
    from agent_coord.server.api.mill import rpc

    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    for kind, kw in kinds:
        rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": watch, "kind": kind, **kw}, "Office", desk)
    cn.commit()


@pytest.mark.sql
def test_seeded_activity_buckets_count_task_items_per_hour(cn, monkeypatch) -> None:
    from agent_coord.server.records import activity

    desk = _desk(cn)
    _tw(cn, monkeypatch, desk, "w1160a", ("start", {}))
    _tw(cn, monkeypatch, desk, "w1160b", ("start", {}))
    mine = [r for r in activity.buckets(cn, "Office", "hour", None, "doing", "task") if r["desk"] == desk]
    assert sum(r["items"] for r in mine) == 2
    for r in mine:
        assert set(r) == BUCKET_KEYS - {"id"}
        assert (r["type"], r["act"], r["roster"]) == ("doing", "task", "Office")
        start = datetime.fromisoformat(r["updated"])
        assert (start.minute, start.second, start.microsecond) == (0, 0, 0)
    day = [r for r in activity.buckets(cn, "Office", "day", None, "", "") if r["desk"] == desk]
    assert day and all(datetime.fromisoformat(r["updated"]).hour == 0 for r in day)
    future = datetime(2999, 1, 1)
    assert activity.buckets(cn, "Office", "min", future, "", "") == []


@pytest.mark.sql
def test_seeded_score_runs_from_last_run_transitions(cn, monkeypatch) -> None:
    from agent_coord.server.records import score

    desk = _desk(cn)
    _tw(cn, monkeypatch, desk, "w1160c", ("start", {}), ("exit", {"exit_code": 0}))
    _tw(cn, monkeypatch, desk, "w1160d", ("start", {}))
    mine = [r for r in score.runs(cn, "Office") if r["desk"] == desk]
    assert [r["phase"] for r in mine] == ["start", "finished", "start"]
    done = mine[1]
    assert done["last_run"] == "finished" and done["end_reason"] == "tw_finished"
    assert done["watch_id"] == "w1160c" and done["dwell_active_ms"] >= 0
    assert mine[0]["last_run"] == "active" and "dwell_active_ms" not in mine[0]
    assert datetime.fromisoformat(done["at"])
    finished = [r for r in score.runs(cn, "Office", "finished") if r["desk"] == desk]
    assert [r["watch_id"] for r in finished] == ["w1160c"]


@pytest.mark.sql
def test_seeded_routes_answer_rows_over_http(cn, monkeypatch) -> None:
    desk = _desk(cn)
    _tw(cn, monkeypatch, desk, "w1160e", ("start", {}), ("exit", {"exit_code": 0}))
    client = _client(monkeypatch, cn)
    acts = client.get("/api/v1/activity-buckets?project=Office&bucket=hour&type=doing&act=task&limit=500").json()
    assert any(r["desk"] == desk and r["items"] >= 1 for r in acts["rows"]), acts
    runs = client.get("/api/v1/score-runs?project=Office&phase=finished&limit=500").json()
    assert [r["watch_id"] for r in runs["rows"] if r["desk"] == desk] == ["w1160e"]
