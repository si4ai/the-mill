"""Card 1303: the cmd word and the doing-error counts on the real book."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing_errors, join, score_part1

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def _rows(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


def _exec(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()
    cn.commit()


@pytest.fixture
def desk(cn, monkeypatch):
    name = "builder-" + uuid4().hex[:8]
    join.upsert(cn, "Office", name, "", "a" * 64)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    return name


def _desk_id(cn, desk):
    return int(_rows(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0]["id"])


def _event(cn, desk, wid, kind, **kw):
    return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", desk)


def _run(cn, desk, end, cmd=None, **extra):
    wid = "w" + uuid4().hex[:8]
    _event(cn, desk, wid, "start", **({"cmd": cmd} if cmd else {}))
    reply = _event(cn, desk, wid, end, **extra) if end else None
    return wid, reply


def _age(cn, desk, wid, start_ago_s, end_ago_s=None):
    """Pin a run's start (and end) to seconds before now."""
    key = f"task:{desk}:{wid}"
    _exec(cn, "UPDATE transition SET at = UTC_TIMESTAMP(6) - INTERVAL %s SECOND"
              " WHERE join_key=%s AND reason='tw_start'", (start_ago_s, key))
    if end_ago_s is not None:
        _exec(cn, "UPDATE transition SET at = UTC_TIMESTAMP(6) - INTERVAL %s SECOND"
                  " WHERE join_key=%s AND reason IN ('tw_finished','tw_failed','tw_stale')", (end_ago_s, key))


def test_cmd_stored_on_start_and_bad_cmd_dropped(cn, desk):
    wid, _ = _run(cn, desk, None, cmd="git push")
    meta = json.loads(_rows(cn, "SELECT meta FROM transition WHERE join_key=%s AND reason='tw_start'",
                            (f"task:{desk}:{wid}",))[0]["meta"])
    assert meta["cmd"] == "git push"
    wid2 = "w" + uuid4().hex[:8]
    _event(cn, desk, wid2, "start", cmd="pytest tests/secret_path.py")
    meta2 = json.loads(_rows(cn, "SELECT meta FROM transition WHERE join_key=%s AND reason='tw_start'",
                             (f"task:{desk}:{wid2}",))[0]["meta"])
    assert "cmd" not in meta2 and meta2["dropped"] == ["cmd"]


def test_exit_reply_carries_kind_count_n_span(cn, desk):
    _, first = _run(cn, desk, "exit", cmd="pytest", exit_code=4)
    assert first["ok"] is True
    assert first["errors"]["kind"] == "usage" and first["errors"]["count"] == 1 and first["errors"]["n"] == 1
    _run(cn, desk, "exit", cmd="pytest", exit_code=0)
    _run(cn, desk, "exit", cmd="gh pr", exit_code=4)        # same kind, other cmd: not counted
    _, again = _run(cn, desk, "exit", cmd="pytest", exit_code=4)
    err = again["errors"]
    assert (err["kind"], err["cmd"], err["count"], err["n"]) == ("usage", "pytest", 2, 4)
    assert isinstance(err["span_s"], int) and err["span_s"] >= 0
    assert err["next"] == doing_errors.NEXT["usage"]
    # The hop kind stays the reply's own kind; the count rides under errors.
    assert again["kind"] == "exit"


@pytest.mark.parametrize("end,extra,want", [
    ("exit", {"exit_code": 128}, "git_fatal"),
    ("exit", {"exit_code": 1}, "other_nonzero"),
    ("crash", {"cause": "lost"}, "other_nonzero"),
])
def test_exit_and_crash_kinds(cn, desk, end, extra, want):
    _, reply = _run(cn, desk, end, **extra)
    assert reply["errors"]["kind"] == want and reply["errors"]["count"] == 1


def test_clean_exit_and_replayed_exit_carry_no_errors(cn, desk):
    _, ok = _run(cn, desk, "exit", exit_code=0)
    assert "errors" not in ok
    wid, _ = _run(cn, desk, "exit", exit_code=4)
    replay = _event(cn, desk, wid, "exit", exit_code=4)
    assert "errors" not in replay


def test_desk_errors_counts_each_kind_reruns_open_and_by_cmd(cn, desk):
    a, _ = _run(cn, desk, "exit", cmd="pytest", exit_code=4)
    b, _ = _run(cn, desk, "exit", cmd="pytest", exit_code=4)
    c, _ = _run(cn, desk, "exit", cmd="git push", exit_code=128)
    d, _ = _run(cn, desk, "crash", cause="reconcile")
    e, _ = _run(cn, desk, "exit", cmd="pytest", exit_code=0)
    _age(cn, desk, a, 3000, 2990)       # b starts 50 s after a ends: a rerun
    _age(cn, desk, b, 2940, 2930)       # c starts 930 s after b ends: not a rerun
    _age(cn, desk, c, 2000, 1990)       # d starts 30 s after c ends: a rerun
    _age(cn, desk, d, 1960, 1000)       # left open, not a failed kind
    _age(cn, desk, e, 100, 90)
    got = doing_errors.desk_errors(cn, _desk_id(cn, desk))
    last = got["windows"]["last_n"]
    assert last["n"] == last["runs"] == 5
    assert last["failed"] == {"usage": 2, "git_fatal": 1, "other_nonzero": 0}
    assert last["reruns_2m"] == 2 and last["left_open"] == 1
    assert 2995 <= last["span_s"] <= 3100
    assert [g["cmd"] for g in last["by_cmd"]] == ["pytest", "git push"]
    assert last["by_cmd"][0]["runs"] == 3 and last["by_cmd"][0]["failed_n"] == 2
    assert got["windows"]["7d"]["runs"] == got["windows"]["30d"]["runs"] == 5
    assert sum(h["runs"] for h in got["hourly"]) == 5
    assert sum(h["failed_n"] for h in got["daily"]) == 3


def test_window_edges_7d_and_30d(cn, desk):
    old, _ = _run(cn, desk, "exit", exit_code=4)
    mid, _ = _run(cn, desk, "exit", exit_code=128)
    new, _ = _run(cn, desk, "exit", exit_code=1)
    _age(cn, desk, old, 31 * 86400, 31 * 86400 - 5)
    _age(cn, desk, mid, 8 * 86400, 8 * 86400 - 5)
    _age(cn, desk, new, 60, 55)
    got = doing_errors.desk_errors(cn, _desk_id(cn, desk))
    w = got["windows"]
    assert w["30d"]["runs"] == 2 and w["30d"]["failed"]["usage"] == 0
    assert w["7d"]["runs"] == 1 and w["7d"]["failed"] == {"usage": 0, "git_fatal": 0, "other_nonzero": 1}
    assert w["last_n"]["runs"] == 3 and w["last_n"]["failed"]["usage"] == 1   # last N has no time bound
    assert sum(d["runs"] for d in got["daily"]) == 2


def test_no_runs_gives_null_windows(cn, desk):
    got = doing_errors.desk_errors(cn, _desk_id(cn, desk))
    assert got["windows"] == {"last_n": None, "7d": None, "30d": None}
    assert got["reason"] == "no tw runs"


def test_score_view_and_wall_read_carry_the_block(cn, desk):
    _run(cn, desk, "exit", cmd="pytest", exit_code=4)
    one = rpc._with_doing_errors(SimpleNamespace(_cn=cn), {"score": rpc.DOING_ERRORS_SCORE, "owner": desk})
    assert one["errors"]["windows"]["last_n"]["failed"]["usage"] == 1
    assert rpc._with_doing_errors(SimpleNamespace(_cn=cn), {"owner": "no-such-desk"}) == {"owner": "no-such-desk"}
    wall = score_part1.read_scores(cn, "7d")
    row = next(d for d in wall["desks"] if d["desk"] == desk)
    assert row["doing_errors"]["windows"]["last_n"]["runs"] == 1


def test_mill_score_end_reason_reads_the_callers_row(cn, desk):
    _run(cn, desk, "exit", cmd="git push", exit_code=128)
    got = rpc._h_score(SimpleNamespace(_cn=cn), {"name": rpc.DOING_ERRORS_SCORE}, "Office", desk)
    assert got["owner"] == desk
    assert got["errors"]["windows"]["last_n"]["failed"]["git_fatal"] == 1
    assert got["errors"]["windows"]["last_n"]["by_cmd"][0]["cmd"] == "git push"
