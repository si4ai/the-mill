"""System SCORE: one JSON history per desk, 4096 byte cap."""

from __future__ import annotations

import json
import os
from datetime import datetime

import pytest

from agent_coord.server.records import apply, connect
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.score_system import KEEP_BYTES, KEEP_DAYS, SPILL, _note, _wall, note_command, wall_route
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_records_test")
DESK = "score_sys"


def _cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


def _loads(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    return json.loads(value)


def _doc(cn, stamp: str) -> tuple[dict, str, str] | None:
    cur = cn.cursor()
    cur.execute(
        """SELECT e.value, s.value, a.act
             FROM score s
             JOIN name d ON d.id = s.desk_id
             JOIN score_evidence e ON e.score_id = s.id
             LEFT JOIN activity a ON a.type = 'score' AND a.id = s.id
            WHERE d.name = %s AND s.kpi = 'system' AND e.`timestamp` = %s""",
        (DESK, stamp),
    )
    row = cur.fetchone()
    cur.close()
    if row is None:
        return None
    return _loads(row[0]), str(row[1]), str(row[2] or "")


def test_note_command_swallows_a_missing_book() -> None:
    class Closed:
        def cursor(self):
            raise RuntimeError("PROCEDURE mill_score_event does not exist")

    note_command("a", "todo", req_b=4, resp_b=6, ms=3, cn=Closed())


def test_hour_resets_day_keeps_and_bytes_follow_the_command(cn) -> None:
    assert KEEP_DAYS == 30
    assert KEEP_BYTES == 4096
    seed_names(cn, ("score_sys", "desk"))
    day1 = datetime(2026, 10, 1, 14, 10, 0)
    later = datetime(2026, 10, 1, 14, 40, 0)
    day2 = datetime(2026, 10, 2, 14, 5, 0)
    leap = datetime(2024, 2, 29, 8, 0, 0)

    _note(cn, DESK, "inbox", req_b=10, resp_b=30, ms=25, now=day1)
    _note(cn, DESK, "inbox", req_b=5, resp_b=5, ms=15, now=later)
    hour, value, n_act = _doc(cn, "1970-01-01 14:00:00")
    assert hour["n"] == 2
    assert hour["inbox"] == {"n": 2, "ms": 40}
    assert hour["bytes"]["mail"] == 50
    assert "todo" not in hour.get("bytes", {})
    assert value == "2"
    assert n_act in ("score", "create")
    day, _, _ = _doc(cn, "2026-10-01 00:00:00")
    assert day["n"] == 2
    assert day["inbox"]["n"] == 2

    _note(cn, DESK, "hold", req_b=100, resp_b=80, ms=10, now=later)
    _note(cn, DESK, "todo", req_b=4, resp_b=6, ms=8, now=later)
    hour, value, _ = _doc(cn, "1970-01-01 14:00:00")
    assert hour["n"] == 4
    assert hour["hold"] == {"n": 1, "ms": 10}
    assert hour["todo"] == {"n": 1, "ms": 8}
    assert hour["bytes"]["mail"] == 50
    assert hour["bytes"]["todo"] == 10
    assert value == "4"

    _note(cn, DESK, "inbox", req_b=7, resp_b=3, ms=10, now=day2)
    hour, value, n_act = _doc(cn, "1970-01-01 14:00:00")
    assert hour["n"] == 1
    assert hour["inbox"] == {"n": 1, "ms": 10}
    assert hour["bytes"]["mail"] == 10
    assert "hold" not in hour
    assert value == "1"
    assert n_act in ("score", "create")
    kept, _, _ = _doc(cn, "2026-10-01 00:00:00")
    assert kept["n"] == 4
    assert kept["inbox"]["n"] == 2
    today, _, _ = _doc(cn, "2026-10-02 00:00:00")
    assert today["n"] == 1

    cur = cn.cursor()
    cur.execute(
        """INSERT INTO score_evidence (score_id, `timestamp`, value, taken)
           SELECT s.id, '2026-08-01 00:00:00.000000', JSON_OBJECT('n', 9), '2026-08-01'
             FROM score s
             JOIN name d ON d.id = s.desk_id
            WHERE d.name = %s AND s.kpi = 'system'""",
        (DESK,),
    )
    cur.close()
    cn.commit()
    _note(cn, DESK, "inbox", req_b=1, resp_b=1, ms=5, now=day2)
    # A score write does not drop the tail (#204). The purge does.
    assert _doc(cn, "2026-08-01 00:00:00") is not None
    from agent_coord.server.records.db import call

    call(cn, "mill_score_evidence_purge", [day2])
    assert _doc(cn, "2026-08-01 00:00:00") is None
    assert _doc(cn, "2026-10-01 00:00:00")[0]["n"] == 4
    assert _doc(cn, "1970-01-01 14:00:00")[0]["n"] == 2

    mail_before = _doc(cn, "2026-10-02 00:00:00")[0]["bytes"]["mail"]
    _note(cn, DESK, "session", req_b=50, resp_b=50, ms=4, now=leap)
    leap_doc, _, _ = _doc(cn, "2024-02-29 00:00:00")
    assert leap_doc["n"] == 1
    assert leap_doc["session"] == {"n": 1, "ms": 4}
    assert "bytes" not in leap_doc
    assert _doc(cn, "1970-01-01 08:00:00")[0]["session"]["n"] == 1
    assert _doc(cn, "2026-10-02 00:00:00")[0]["bytes"]["mail"] == mail_before


def test_spill_keeps_the_document_and_is_logged(cn, monkeypatch) -> None:
    seed_names(cn, ("score_sys", "desk"))
    when = datetime(2026, 10, 1, 9, 0, 0)
    _note(cn, DESK, "inbox", req_b=1, resp_b=1, ms=5, now=when)
    before = _doc(cn, "2026-10-01 00:00:00")
    fat = json.dumps({"n": 1, "pad": "x" * 5000})
    assert len(fat.encode()) > KEEP_BYTES
    cur = cn.cursor()
    cur.execute(
        """UPDATE score_evidence e
             JOIN score s ON s.id = e.score_id
             JOIN name d ON d.id = s.desk_id
              SET e.value = CAST(%s AS JSON)
            WHERE d.name = %s AND s.kpi = 'system' AND e.`timestamp` = %s""",
        (fat, DESK, "2026-10-01 00:00:00"),
    )
    cur.close()
    cn.commit()

    with pytest.raises(Exception) as caught:
        _note(cn, DESK, "doing", req_b=1, resp_b=1, ms=5, now=when)
    assert SPILL in str(caught.value)
    assert _doc(cn, "2026-10-01 00:00:00")[0].get("pad", "").startswith("xxx")
    assert "doing" not in _doc(cn, "2026-10-01 00:00:00")[0]
    assert _doc(cn, "2026-10-01 00:00:00")[1] == before[1]

    logged = []

    def capture(op, ms, **kv):
        logged.append((op, kv))

    monkeypatch.setattr("agent_coord.server.push.perf_log", capture)
    note_command(DESK, "doing", req_b=1, resp_b=1, ms=5, cn=cn, now=when)
    assert logged
    assert logged[0][0] == "score.history"
    assert logged[0][1]["ok"] == 0
    assert SPILL in logged[0][1]["err"]
    assert logged[0][1]["verb"] == "doing"
    assert "doing" not in _doc(cn, "2026-10-01 00:00:00")[0]


def test_span_reads_each_desk_once(cn) -> None:
    from agent_coord.server.records.activity import span
    from agent_coord.server.records.db import call
    from agent_coord.server.records import join as rec_join

    desk = "span_a"
    seed_names(cn, ("span_a", "desk"), ("span", "roster"), ("span_b", "roster"), ("span_none", "roster"), ("span", "roster"))
    call(cn, "mill_member_put", ["roster", "span", desk])
    call(cn, "mill_member_put", ["roster", "span_b", desk])
    call(cn, "mill_member_put", ["roster", "span", desk])
    when = datetime(2026, 10, 2, 11, 15, 0)
    _note(cn, desk, "hold", req_b=0, resp_b=0, ms=4, now=when)

    hours = span(cn, "project", "span", "hour")
    assert len(hours) == 1
    assert str(hours[0]["timestamp"]).startswith("1970-01-01 11:")
    other = span(cn, "project", "span_b", "hour")
    assert len(other) == 1
    assert other[0]["desk_id"] == hours[0]["desk_id"]
    assert span(cn, "project", "span_none", "hour") == []

    days = span(cn, "role", "span", "day")
    assert len(days) == 1
    assert str(days[0]["timestamp"]).startswith("2026-10-02")
    assert _loads(days[0]["value"])["n"] == 1

    rec_join.upsert(cn, "Office", desk, "span", "a" * 64, "present")
    call(cn, "mill_join_lan", [desk, "192.0.2.10"])
    lan = span(cn, "lan", "192.0.2.10", "day")
    assert len(lan) == 1
    assert lan[0]["desk_id"] == hours[0]["desk_id"]

    mins = span(cn, "role", "span", "min")
    assert any(r.get("type") == "score" for r in mins)


def test_between_reads_recent_rows_for_the_scope_desks(cn) -> None:
    from agent_coord.server.records.activity import between_rows
    from agent_coord.server.records.db import call
    from agent_coord.server.records import hold as rec_hold
    from agent_coord.server.records import join as rec_join
    from agent_coord.server.records import mail as rec_mail
    from agent_coord.server.records import todo as rec_todo

    desk_a = "between_a"
    desk_b = "between_b"
    desk_c = "between_c"
    seed_names(
        cn,
        ("between_a", "desk"),
        ("between_b", "desk"),
        ("between_c", "desk"),
        ("between", "roster"),
        ("between_empty", "roster"),
        ("between", "roster"),
    )
    call(cn, "mill_member_put", ["roster", "between", desk_a])
    call(cn, "mill_member_put", ["roster", "between", desk_b])
    call(cn, "mill_member_put", ["roster", "between", desk_a])
    _note(cn, desk_a, "hold", req_b=0, resp_b=0, ms=4, now=datetime(2026, 10, 2, 9, 0, 0))

    card = rec_todo.insert(cn, "between", desk_a, "open", "card")
    rec_todo.update(cn, card[0]["id"], desk_a, "claimed", desk_b, "card")
    letter = rec_mail.insert(cn, "between", desk_a, "between_c", "hello", 0)
    call(cn, "mill_mail_to_put", [letter[0]["id"], "between", "desk", desk_b, 0])
    rec_hold.upsert(cn, "between", desk_b, "between-file")

    rows = between_rows(cn, "project", "between", 50)
    mail_rows = [r for r in rows if r["type"] == "mail" and r["owner"] == "between_a"]
    assert sorted(r["other"] for r in mail_rows) == ["between_b", "between_c"]
    assert len({r["id"] for r in mail_rows}) == 1
    cards = [r for r in rows if r["type"] == "todo" and r["owner"] == "between_a"]
    assert len(cards) == 1
    assert cards[0]["other"] == "between_b"
    holds = [r for r in rows if r["type"] == "hold"]
    assert len(holds) == 1
    assert holds[0]["owner"] == "between_b"
    assert holds[0]["other"] is None
    scores = [r for r in rows if r["type"] == "score" and r["owner"] == "between_a"]
    assert scores and scores[0]["other"] is None
    assert len([r for r in rows if r["owner"] == "between_a" and r["type"] == "mail"]) == 2

    tight = between_rows(cn, "project", "between", 1)
    assert any(r["type"] == "mail" and r["owner"] == "between_a" for r in tight)
    assert not any(r["type"] == "todo" for r in tight)
    assert not any(r["type"] == "score" and r["owner"] == "between_a" for r in tight)
    assert any(r["type"] == "hold" and r["owner"] == "between_b" for r in tight)

    # 0.7.0: one roster namespace, so both scope tokens read the same members.
    role_rows = between_rows(cn, "role", "between", 50)
    assert {r["owner"] for r in role_rows} == {"between_a", "between_b"}
    assert between_rows(cn, "project", "between_empty", 50) == []

    rec_join.upsert(cn, "Office", desk_a, "between", "b" * 64, "present")
    call(cn, "mill_join_lan", [desk_a, "192.0.2.11"])
    lan_rows = between_rows(cn, "lan", "192.0.2.11", 50)
    assert lan_rows
    assert {r["owner"] for r in lan_rows} == {"between_a"}


def test_wall_route_collapses_to_the_api() -> None:
    assert wall_route("/api/floor?project=the-mill") == "/api/floor"
    assert wall_route("/api/v1/mail/42") == "/api/v1/mail"
    assert wall_route("/api/admin/invites") == "/api/admin/invites"
    assert wall_route("/api/mill/send") == ""
    assert wall_route("/") == ""


def test_wall_routes_share_one_office_score(cn) -> None:
    when = datetime(2026, 10, 2, 15, 1, 0)
    _wall(cn, "/api/floor", ms=12, now=when)
    _wall(cn, "/api/floor", ms=8, now=when)
    _wall(cn, "/api/activity", ms=5, now=when)
    cur = cn.cursor()
    try:
        cur.execute(
            """SELECT e.value, s.value, s.desk_id, s.roster_id
                 FROM score s
                 JOIN score_evidence e ON e.score_id = s.id
                WHERE s.kpi = 'wall' AND e.`timestamp` = %s""",
            ("1970-01-01 15:00:00",),
        )
        row = cur.fetchone()
        assert cur.fetchall() == []
        # activity.id is per type. Other rows from this module share the score's number.
        cur.execute(
            """SELECT a.act FROM activity a
                 JOIN score s ON s.type = 'score' AND s.id = a.id
                WHERE a.type = 'score' AND s.kpi = 'wall'"""
        )
        act_rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM score WHERE kpi = 'wall'")
        nscore = cur.fetchone()[0]
        assert cur.fetchall() == []
    finally:
        cur.close()
    doc = _loads(row[0])
    assert len(act_rows) == 1
    assert nscore == 1
    assert row[2] is None  # 0.8.0: office wall score desk_id NULL
    assert row[3] == 1
    assert doc["n"] == 3
    assert doc["/api/floor"] == {"n": 2, "ms": 20}
    assert doc["/api/activity"] == {"n": 1, "ms": 5}
    assert row[1] == "3"
    assert act_rows[0][0] in ("score", "create")


def test_unread_activity_read_releases_its_metadata_lock(cn) -> None:
    """A fetchone that leaves rows must not park a pooled thread on activity."""
    import mysql.connector

    other = connect(TEST_DB)
    sid = None
    close_err = None
    try:
        cur = other.cursor()
        cur.execute("SELECT CONNECTION_ID()")
        sid = int(cur.fetchone()[0])
        cur.close()
        cur = other.cursor()
        cur.execute("SELECT id FROM activity UNION ALL SELECT 1 UNION ALL SELECT 2")
        cur.fetchone()
    finally:
        try:
            other.close()
        except Exception as exc:
            close_err = exc

    kw = _conn_kwargs()
    kw["database"] = TEST_DB
    admin = mysql.connector.connect(**kw)
    try:
        chk = admin.cursor()
        locks: list = []
        if sid is not None:
            chk.execute(
                """SELECT ml.OBJECT_NAME
                     FROM performance_schema.metadata_locks ml
                     JOIN performance_schema.threads th
                       ON th.THREAD_ID = ml.OWNER_THREAD_ID
                    WHERE th.PROCESSLIST_ID = %s
                      AND ml.OBJECT_SCHEMA = %s
                      AND ml.OBJECT_NAME = 'activity'""",
                (sid, TEST_DB),
            )
            locks = list(chk.fetchall())
            if locks:
                try:
                    chk.execute("KILL %s", (sid,))
                except Exception:
                    pass
        chk.close()
        assert close_err is None
        assert locks == []
        from agent_coord.server.records.db import _POOL_SIZE

        # The module connection already holds one slot.
        held = []
        try:
            for _ in range(_POOL_SIZE - 1):
                held.append(connect(TEST_DB))
            for held_cn in held:
                held_cur = held_cn.cursor()
                held_cur.execute("SELECT 1")
                assert held_cur.fetchone()[0] == 1
                held_cur.close()
        finally:
            for held_cn in held:
                held_cn.close()
        still = cn.cursor()
        still.execute("SELECT 1")
        assert still.fetchone()[0] == 1
        still.close()
    finally:
        admin.close()
