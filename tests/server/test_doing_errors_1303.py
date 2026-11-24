"""Card 1303: the cmd word on the tw start hop, and the doing-error counts (no SQL)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing_errors as de


class _Book:
    _cn = object()


@pytest.fixture
def stored(monkeypatch):
    got = []
    monkeypatch.setattr("agent_coord.server.records.doing.task_event",
                        lambda cn, desk, meta, **kw: got.append(dict(meta)))
    monkeypatch.setattr("agent_coord.server.records.db.request_tx", lambda cn, run: run())
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **kw: None)
    return got


def _send(kind, **extra):
    body = {"verb": "tw.event", "watch_id": "w1", "kind": kind, **extra}
    return rpc._h_tw_event(_Book(), body, "the-mill", "builder")


@pytest.mark.parametrize("cmd", ["pytest", "git push", "rco pack", "python3.12", "g++", "mill score"])
def test_start_keeps_a_command_word(stored, cmd):
    _send("start", cmd=cmd)
    assert stored[-1]["cmd"] == cmd
    assert "dropped" not in stored[-1]


@pytest.mark.parametrize("bad", ["", "Pytest", "git push origin", "pytest tests/x.py", "git --no-pager",
                                 "a" * 33, "git " + "b" * 33, 7, {"x": 1}, ["git"], "curl http://x"])
def test_bad_cmd_is_dropped_and_named_and_the_start_still_stored(stored, bad):
    _send("start", cmd=bad, card=1303)
    assert "cmd" not in stored[-1]
    assert stored[-1]["dropped"] == ["cmd"]
    assert stored[-1]["card"] == 1303


def test_cmd_rides_the_start_only(stored):
    _send("exit", exit_code=4, cmd="pytest")
    _send("stall", cmd="pytest")
    for meta in stored:
        assert "cmd" not in meta and "dropped" not in meta


def test_exit_reply_survives_a_failed_count_read(stored):
    # The count is a read after the store; a failing read never costs the event or the ok reply.
    got = _send("exit", exit_code=4)
    assert got["ok"] is True and "errors" not in got


@pytest.mark.parametrize("reason,code,cause,want", [
    ("tw_finished", 0, None, None),
    (None, None, None, None),
    ("tw_failed", 4, None, "usage"),
    ("tw_failed", 128, None, "git_fatal"),
    ("tw_failed", 1, None, "other_nonzero"),
    ("tw_failed", None, "lost", "other_nonzero"),
    ("tw_failed", b"128", None, "git_fatal"),
    ("tw_failed", None, "reconcile", "left_open"),
    ("tw_failed", None, "sweep", "left_open"),
    ("tw_stale", None, "sweep", "left_open"),
])
def test_kind_of(reason, code, cause, want):
    assert de.kind_of(reason, code, cause) == want


T0 = datetime(2026, 11, 24, 12, 0, 0)


def _run(i, start_s, end_s, reason, ec=None, cause=None, cmd=None):
    start = T0 + timedelta(seconds=start_s)
    return {"id": i, "start_at": start, "end_at": None if end_s is None else T0 + timedelta(seconds=end_s),
            "end_reason": reason, "ec": ec, "cause": cause, "cmd": cmd}


def _fake_rows(monkeypatch, runs):
    def rows(cn, sql, args):
        if "UTC_TIMESTAMP" in sql:
            return [{"now": T0 + timedelta(hours=1)}]
        out = sorted((dict(r) for r in runs), key=lambda r: r["start_at"], reverse=True)
        if "LIMIT" in sql:
            return out[: args[-1]]
        return [r for r in out if r["start_at"] >= args[-1]]
    monkeypatch.setattr(de, "_rows", rows)


def test_counts_kinds_reruns_open_and_items(monkeypatch):
    _fake_rows(monkeypatch, [
        _run(1, 0, 5, "tw_failed", 4, cmd="pytest"),
        _run(2, 60, 70, "tw_failed", 4, cmd="pytest"),     # rerun of 1 (55 s after its end)
        _run(3, 400, 410, "tw_finished", 0, cmd="pytest"),  # 2 is not a rerun: 330 s gap
        _run(4, 500, 510, "tw_failed", 128, cmd="git push"),
        _run(5, 520, 530, "tw_failed", 2),                  # 4 reran at 10 s; no cmd
        _run(6, 700, 800, "tw_failed", None, "reconcile"),  # left open; 170 s after 5, never a rerun source
        _run(7, 801, None, None),                           # still live
    ])
    got = de.desk_errors(None, 1)
    last = got["windows"]["last_n"]
    assert got["kinds"] == ["usage", "git_fatal", "other_nonzero", "reruns_2m", "left_open"]
    assert set(got["next"]) == set(got["kinds"])
    assert last["n"] == last["runs"] == 7          # fewer than 100: n is the actual total
    assert last["failed"] == {"usage": 2, "git_fatal": 1, "other_nonzero": 1}
    assert last["failed_n"] == 4
    assert last["reruns_2m"] == 2 and last["items"]["reruns_2m"] == [1, 4]
    assert last["left_open"] == 1 and last["items"]["left_open"] == [6]
    assert last["items"]["usage"] == [1, 2]
    assert last["span_s"] == 3600 and last["anchor_at"] == "2026-11-24T12:00:00Z"
    assert [g["cmd"] for g in last["by_cmd"]] == ["pytest", "git push"]
    py = last["by_cmd"][0]
    assert (py["runs"], py["failed_n"], py["reruns_2m"], py["p50_s"], py["max_s"]) == (3, 2, 1, 10.0, 10.0)
    assert got["windows"]["7d"]["runs"] == 7 and got["reasons"]["7d"] is None
    assert len(got["hourly"]) == 24 and len(got["daily"]) == 30
    assert got["hourly"][-2]["runs"] == 7 and got["hourly"][-1]["runs"] == 0
    assert got["hourly"][-2]["failed"]["usage"] == 2
    assert sum(b["runs"] for b in got["daily"]) == 7


def test_kind_keys_are_fixed_with_zeros(monkeypatch):
    _fake_rows(monkeypatch, [_run(1, 0, 5, "tw_finished", 0)])
    last = de.desk_errors(None, 1)["windows"]["last_n"]
    assert last["failed"] == {"usage": 0, "git_fatal": 0, "other_nonzero": 0}
    assert last["items"] == {k: [] for k in de.KINDS} and last["by_cmd"] == []


def test_no_runs_gives_null_windows_with_a_reason(monkeypatch):
    _fake_rows(monkeypatch, [])
    got = de.desk_errors(None, 1)
    assert got["windows"] == {"last_n": None, "7d": None, "30d": None}
    assert got["reason"] == "no tw runs"
    assert all(got["reasons"].values())


def test_last_n_caps_at_100_and_items_at_5(monkeypatch):
    _fake_rows(monkeypatch, [_run(i, i * 20, i * 20 + 1, "tw_failed", 4) for i in range(130)])
    last = de.desk_errors(None, 1)["windows"]["last_n"]
    assert last["n"] == last["runs"] == 100
    assert last["failed"]["usage"] == 100
    assert last["items"]["usage"] == [30, 31, 32, 33, 34]   # oldest first
    assert last["span_s"] == 3600 - 30 * 20


def test_exit_count_matches_kind_and_cmd(monkeypatch):
    _fake_rows(monkeypatch, [
        _run(1, 0, 5, "tw_failed", 4, cmd="pytest"),
        _run(2, 10, 15, "tw_failed", 4, cmd="gh pr"),
        _run(3, 20, 25, "tw_failed", 128, cmd="pytest"),
        _run(4, 30, 35, "tw_finished", 0, cmd="pytest"),
        _run(5, 40, 45, "tw_failed", 4, cmd="pytest"),
    ])
    got = de.exit_count(None, 1, 5)
    assert (got["kind"], got["cmd"], got["count"], got["n"], got["span_s"]) == ("usage", "pytest", 2, 5, 3600)
    assert de.exit_count(None, 1, 4) is None          # a clean exit carries nothing
    assert de.exit_count(None, 1, 99) is None         # not in the last N


def test_exit_count_without_cmd_counts_the_kind(monkeypatch):
    _fake_rows(monkeypatch, [_run(1, 0, 5, "tw_failed", 4, cmd="pytest"), _run(2, 10, 15, "tw_failed", 4)])
    got = de.exit_count(None, 1, 2)
    assert (got["cmd"], got["count"], got["n"]) == (None, 2, 2)


def test_exit_count_skips_a_run_left_open(monkeypatch):
    _fake_rows(monkeypatch, [_run(1, 0, 5, "tw_failed", None, "reconcile")])
    assert de.exit_count(None, 1, 1) is None
