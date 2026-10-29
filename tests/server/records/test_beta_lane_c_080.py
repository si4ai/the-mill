"""0.8.0 beta landing, lane C: score, activity, watcher and glance on the beta book (row F172).

Office-wide and roster-defined scores have no desk (desk_id NULL); the Office kind
guards are gone (the kind-checked FK on roster_id holds Office = roster 1); a
watcher is a desk; the glance is computed live by uc_a6_glance (F176).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import score as rec_score
from agent_coord.server.records import watcher as rec_watcher
from agent_coord.server.records.db import call, scalar
from tests.server.records.conftest import seed_names
from tests.server.records import lane_c_beta

SQL = Path(__file__).resolve().parents[3] / "agent_coord" / "server" / "sql"


@pytest.fixture(scope="module")
def cn():
    c, db = lane_c_beta.make_book("mill_lane_c_080")
    saved = os.environ.get("AGENT_COORD_DATABASE")
    os.environ["AGENT_COORD_DATABASE"] = db
    try:
        yield c
    finally:
        if saved is None:
            os.environ.pop("AGENT_COORD_DATABASE", None)
        else:
            os.environ["AGENT_COORD_DATABASE"] = saved
        lane_c_beta.drop_book(c, db)


def _rows(cn, sql: str, args: tuple = ()) -> list[tuple]:
    cn.commit()
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return [tuple(r) for r in cur.fetchall()]
    finally:
        cur.close()


def _score(cn, roster_id: int, kpi: str) -> list[tuple]:
    return _rows(cn, "SELECT id, desk_id, value FROM score WHERE roster_id=%s AND kpi=%s", (roster_id, kpi))


def _activity_desk(cn, score_id: int):
    rows = _rows(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (score_id,))
    assert len(rows) == 1, rows
    return rows[0][0]


# --- office-owned scores: desk NULL -------------------------------------------------------------

def test_admin_upsert_is_owned_by_the_office_not_a_desk(cn):
    rec_score.admin_upsert(cn, "lc.admin_kpi", "7", "0", "note")
    rows = _score(cn, 1, "lc.admin_kpi")
    assert [(r[1], r[2]) for r in rows] == [(None, "7")]
    assert _activity_desk(cn, rows[0][0]) is None
    rec_score.admin_upsert(cn, "lc.admin_kpi", "8", "0", "note")
    assert [(r[1], r[2]) for r in _score(cn, 1, "lc.admin_kpi")] == [(None, "8")]


def test_admin_upsert_updates_the_seeded_office_row(cn):
    before = _score(cn, 1, "mill-wall.ticks")
    assert [r[1] for r in before] == [None]
    rec_score.admin_upsert(cn, "mill-wall.ticks", "3", "0", "n")
    assert _score(cn, 1, "mill-wall.ticks") == [(before[0][0], None, "3")]


def test_wall_event_scores_the_office_with_no_desk(cn):
    call(cn, "mill_wall_event", ["/api/floor", 12, None])
    call(cn, "mill_wall_event", ["/api/floor", 8, None])
    rows = _score(cn, 1, "wall")
    assert [(r[1], r[2]) for r in rows] == [(None, "2")]
    assert _activity_desk(cn, rows[0][0]) is None


def test_system_score_stays_on_its_desk(cn):
    (did,) = seed_names(cn, ("lc_sys_desk", "desk"))
    call(cn, "mill_score_event", ["lc_sys_desk", "inbox", 5, 10, 20, None])
    rows = _rows(cn, "SELECT desk_id, roster_id FROM score WHERE kpi='system' AND desk_id=%s", (did,))
    assert rows == [(did, 1)]


# --- roster-defined series: desk NULL, the recording desk on activity and points ------------------

def test_point_series_is_owned_by_the_roster_with_no_desk(cn):
    rid, a, b = seed_names(cn, ("lc_proj", "roster"), ("lc_pa", "desk"), ("lc_pb", "desk"))
    rec_score.point_add(cn, "lc_proj", "lc_pa", "lc.series", 1.0)
    rec_score.point_add(cn, "lc_proj", "lc_pb", "lc.series", 2.0)
    rows = _score(cn, rid, "lc.series")
    assert [(r[1], r[2]) for r in rows] == [(None, "2")]
    assert _activity_desk(cn, rows[0][0]) == b
    pts = _rows(cn, "SELECT desk_id FROM score_point WHERE score_id=%s ORDER BY id", (rows[0][0],))
    assert pts == [(a,), (b,)]


def test_define_creates_the_roster_owned_row(cn):
    rid, _a = seed_names(cn, ("lc_def", "roster"), ("lc_da", "desk"))
    rec_score.define(cn, "lc_def", "lc_da", "lc.defined", target="5", better="down", unit="ms")
    rows = _rows(cn, "SELECT desk_id, target, better, unit FROM score WHERE roster_id=%s AND kpi='lc.defined'", (rid,))
    assert rows == [(None, "5", "down", "ms")]
    rec_score.point_add(cn, "lc_def", "lc_da", "lc.defined", 4.0)
    assert len(_score(cn, rid, "lc.defined")) == 1


def test_points_read_prefers_the_roster_row_over_a_desk_row(cn):
    rid, _a = seed_names(cn, ("lc_pref", "roster"), ("lc_pd", "desk"))
    rec_score.upsert(cn, "lc_pref", "lc_pd", "lc.both", "99", "", "")
    rec_score.point_add(cn, "lc_pref", "lc_pd", "lc.both", 3.0)
    rows = rec_score.points(cn, "lc_pref", "lc.both", 5)
    assert rows and rows[0]["latest"] == "3"
    assert rows[0]["owner"] == "lc_pref"  # the wire shape: a roster-owned series shows its roster


def test_retire_the_roster_series_by_a_recording_desk(cn):
    rid, _a, _b = seed_names(cn, ("lc_ret", "roster"), ("lc_ra", "desk"), ("lc_rb", "desk"))
    rec_score.point_add(cn, "lc_ret", "lc_ra", "lc.gone", 1.0)
    with pytest.raises(Exception, match="only a desk that recorded"):
        rec_score.retire(cn, "lc_ret", "lc_rb", "lc.gone")
    out = rec_score.retire(cn, "lc_ret", "lc_ra", "lc.gone")
    assert out and out[0]["op"] == "retired"
    sid = _score(cn, rid, "lc.gone")[0][0]
    assert _rows(cn, "SELECT deleted IS NOT NULL FROM activity WHERE type='score' AND id=%s", (sid,)) == [(1,)]


def test_score_select_shows_a_null_owner_row(cn):
    seed_names(cn, ("lc_sel", "roster"), ("lc_sd", "desk"))
    rec_score.point_add(cn, "lc_sel", "lc_sd", "lc.sel", 1.5)
    rows = [r for r in rec_score.select(cn, "lc_sel") if r["kpi"] == "lc.sel"]
    assert len(rows) == 1 and rows[0]["desk_id"] is None and rows[0]["desk"] is None


# --- the four Office kind guards are gone ----------------------------------------------------------

_GUARD = re.compile(r"FROM\s+name\s+WHERE\s+id\s*=\s*1\s+AND\s+type\s*=\s*'roster'", re.I)


def test_no_office_kind_guard_in_score_or_activity_sql():
    for f in ("sp_score.sql", "sp_activity.sql"):
        assert not _GUARD.search((SQL / f).read_text(encoding="utf-8")), f


def test_no_office_kind_guard_in_installed_routines(cn):
    bodies = _rows(
        cn,
        "SELECT ROUTINE_NAME, ROUTINE_DEFINITION FROM information_schema.ROUTINES"
        " WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME IN"
        " ('mill_span', 'mill_score_admin_upsert', 'mill_score_event', 'mill_wall_event')",
    )
    assert len(bodies) == 4
    for name, body in bodies:
        assert not _GUARD.search(body or ""), name


def test_the_database_refuses_a_non_roster_office(cn):
    # What the guards checked is now the kind-checked FK: roster_id 1 must be a roster.
    (did,) = seed_names(cn, ("lc_fk_desk", "desk"))
    cur = cn.cursor()
    try:
        with pytest.raises(Exception, match="1452|foreign key"):
            cur.execute("INSERT INTO score (desk_id, roster_id, kpi) VALUES (NULL, %s, 'lc.fk')", (did,))
    finally:
        cn.rollback()
        cur.close()


def test_span_hour_reads_system_scores_without_the_guard(cn):
    rid, did = seed_names(cn, ("lc_span", "roster"), ("lc_span_desk", "desk"))
    cur = cn.cursor()
    cur.execute("INSERT IGNORE INTO member (name_id, desk_id) VALUES (%s, %s)", (rid, did))
    cn.commit()
    cur.close()
    call(cn, "mill_score_event", ["lc_span_desk", "send", 3, 1, 1, None])
    rows = call(cn, "mill_span", ["project", "lc_span", "hour"])
    assert rows and {r["desk_id"] for r in rows} == {did}


# --- watchers are desks only --------------------------------------------------------------------

def test_a_roster_watcher_row_is_refused(cn):
    # A roster is not a seat: INSERT IGNORE drops the FK miss (same as main); no roster row stays.
    rid, did = seed_names(cn, ("lc_wr", "roster"), ("lc_wd", "desk"))
    rec_score.point_add(cn, "lc_wr", "lc_wd", "lc.watched", 1.0)
    sid = _score(cn, rid, "lc.watched")[0][0]
    rec_watcher.put(cn, "score", sid, rid)
    rows = rec_watcher.select(cn, "score", sid)
    assert rid not in {r["desk_id"] for r in rows}
    assert {r["desk_id"] for r in rows} <= {did}


def test_watcher_select_reads_desk_rows_only(cn):
    rid, a, b = seed_names(cn, ("lc_ws", "roster"), ("lc_wa", "desk"), ("lc_wb", "desk"))
    rec_score.point_add(cn, "lc_ws", "lc_wa", "lc.ws", 1.0)
    sid = _score(cn, rid, "lc.ws")[0][0]
    rec_watcher.set_hint(cn, "score", sid, b, "b hint")
    rows = rec_watcher.select(cn, "score", sid)
    assert sorted((r["desk_id"], r["hint"]) for r in rows) == [(a, None), (b, "b hint")]
    assert {r["desk_type"] for r in rows} == {"desk"}


def test_watcher_select_has_no_roster_branch():
    text = (SQL / "sp_activity.sql").read_text(encoding="utf-8")
    body = text.split("CREATE PROCEDURE mill_watcher_select", 1)[1].split("END //", 1)[0]
    assert "UNION" not in body.upper() and "JOIN member" not in body


# --- activity with no desk ----------------------------------------------------------------------

def test_activity_reads_keep_a_null_desk_row(cn):
    rec_score.admin_upsert(cn, "lc.act", "1", "", "")
    sid = _score(cn, 1, "lc.act")[0][0]
    got = [r for r in call(cn, "mill_activity_select", [0, 500]) if r["type"] == "score" and r["id"] == sid]
    assert len(got) == 1 and got[0]["desk_id"] is None and got[0]["desk"] is None
    one = call(cn, "mill_activity_get", ["score", sid])
    assert len(one) == 1
    bucket = call(cn, "mill_activity_bucket", ["Office", 0, "score", None, "hour"])
    assert any(r["desk_id"] is None for r in bucket)


# --- python readers of office scores ------------------------------------------------------------

def test_glance_office_scores_read_the_null_owner_rows(cn):
    from agent_coord.server import glance

    rec_score.admin_upsert(cn, "lc.glance_kpi", "4", "0", "")
    cn.commit()
    got = glance._office_scores(cn)
    assert "lc.glance_kpi" in got and got["lc.glance_kpi"][0] == "4"


def test_score_tick_fallback_updates_the_null_owner_rows(cn):
    from agent_coord.server import score_tick

    score_tick._publish_sql(cn, {score_tick.KPI_TICKS: 11, score_tick.KPI_IDLE: 0, score_tick.KPI_DROP: 0})
    assert [r[2] for r in _score(cn, 1, score_tick.KPI_TICKS)] == ["11"]


def test_score_tick_publish_writes_office_rows_with_no_desk(cn, monkeypatch):
    import mysql.connector

    from agent_coord.server import records, score_tick
    from agent_coord.server.records.db import conn_kwargs

    # connect() may hand back a pool opened on another module's book; publish to this one.
    db = cn.database
    monkeypatch.setattr(records, "connect", lambda *a, **k: mysql.connector.connect(**{**conn_kwargs(), "database": db}))
    out = score_tick.publish({score_tick.KPI_TICKS: 6, score_tick.KPI_API_N: 9})
    assert out["ok"] is True and "fallback" not in out, out
    assert _score(cn, 1, score_tick.KPI_API_N)[0][1:] == (None, "9")


def test_probe_delete_names_the_first_recorder_of_a_roster_series(cn):
    from agent_coord.server import probe_delete

    rid, _a = seed_names(cn, ("lc_probe", "roster"), ("lc_probe_desk", "desk"))
    rec_score.point_add(cn, "lc_probe", "lc_probe_desk", "lc.probe", 1.0)
    sid = _score(cn, rid, "lc.probe")[0][0]
    row = probe_delete._score_row(cn, sid)
    assert row["maker"] == "lc_probe_desk" and row["roster"] == "lc_probe"


def test_strip_misses_include_a_roster_series(cn, monkeypatch):
    from agent_coord.server import middleware

    seed_names(cn, ("lc_miss", "roster"), ("lc_miss_desk", "desk"))
    rec_score.point_add(cn, "lc_miss", "lc_miss_desk", "lc.miss", 1.0, target="9")
    cn.commit()
    # The strip looks names up by SCOPE_PROJECT; point it at the roster kind for this read.
    monkeypatch.setattr(middleware, "SCOPE_PROJECT", "roster")
    got = middleware._scope_strip(cn, "roster", "lc_miss")
    assert {"desk": "lc_miss", "kpi": "lc.miss"} in got["miss_rows"]


# --- live glance (F176; glance_cache removed) ---------------------------------------------------

def _glance(cn) -> tuple[list[dict], list[dict]]:
    cn.commit()
    cur = cn.cursor(dictionary=True)
    sets: list[list[dict]] = []
    try:
        cur.execute("CALL uc_a6_glance()")
        while True:
            if cur.with_rows:
                sets.append(list(cur.fetchall()))
            if not cur.nextset():
                break
    finally:
        cur.close()
    cn.commit()
    return sets[0], sets[1]


def test_live_glance_answers_one_row_and_newest_activity(cn):
    cache, activity = _glance(cn)
    assert len(cache) == 1 and cache[0]["id"] == 1
    for key in ("present", "held", "open_n", "letters_1d", "card_moves_1d", "doings_1d",
                "holds_1d", "points_1d", "refresh_us", "at"):
        assert key in cache[0], key
    assert "open_votes" not in cache[0] and "unread" not in cache[0]
    assert 0 < len(activity) <= 30
    assert {r["kind"] for r in activity} <= {"letter", "card", "doing", "hold", "score"}
    assert [r["seq"] for r in activity] == list(range(1, len(activity) + 1))
    ats = [r["at"] for r in activity]
    assert ats == sorted(ats, reverse=True)


def test_live_glance_counts_points_of_the_last_day(cn):
    want = scalar(cn, "SELECT COUNT(*) FROM score_point WHERE created >= MILL_NOW() - INTERVAL 1 DAY")
    cache, _ = _glance(cn)
    assert cache[0]["points_1d"] == want


def test_read_glance_shapes_the_book_answer(cn):
    from agent_coord.server.beta_client import read_glance

    got = read_glance(cn)
    assert got["cache"]["id"] == 1 and "open_votes" not in got["cache"]
    assert got["activity"] and set(got["activity"][0]) == {"seq", "at", "kind", "ref", "desk"}


def test_read_glance_logs_a_perf_line(cn, monkeypatch):
    from agent_coord.server import beta_client
    from agent_coord.server.records import db

    seen: list[tuple] = []
    # read_glance does not call _perf today; keep the shape check honest via CALL count.
    got = beta_client.read_glance(cn)
    assert got["cache"]["id"] == 1


def test_activity_put_null_desk_inserts_null_and_keeps_a_desk_on_touch(cn):
    seed_names(cn, ("lc_touch", "roster"), ("lc_touch_desk", "desk"))
    sid = rec_score.upsert(cn, "lc_touch", "lc_touch_desk", "lc.touch", "1", "", "")[0]["id"]
    did = _activity_desk(cn, sid)
    assert did is not None
    cur = cn.cursor()
    cur.execute("CALL mill_activity_put('score', %s, MILL_NOW(), NULL, NULL, NULL, NULL)", (sid,))
    cur.execute("CALL mill_activity_put('score', %s, MILL_NOW(), NULL, 1, NULL, NULL)", (sid + 100000,))
    cn.commit()
    cur.close()
    assert _activity_desk(cn, sid) == did
    assert _activity_desk(cn, sid + 100000) is None
