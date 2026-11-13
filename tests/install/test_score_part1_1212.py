"""Card 1212: part 1 scores come from the book, and a wall read does not record a view."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def _up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:
        pytest.skip(f"no MySQL for the score test: {exc}")


def test_scores_skip_inactive_and_wall_reads_do_not_count():
    _up()
    from agent_coord.server.records.score_part1 import SCORE_NAMES, active_desk_ids, read_scores
    from tests.beta_book import drop_db, make_fresh_book

    cn, db = make_fresh_book("mill_score1212")
    try:
        cur = cn.cursor()
        cur.execute(
            "INSERT INTO name (type, name) VALUES ('roster', 'r1212'), "
            "('desk', 'desk-a'), ('desk', 'desk-b')"
        )
        cur.execute(
            "INSERT INTO seat (desk_id, token_hash) "
            "SELECT id, %s FROM name WHERE name IN ('desk-a', 'desk-b')",
            ("d" * 64,),
        )
        cur.execute("SELECT id, name FROM name WHERE type='desk'")
        ids = {name: i for i, name in cur.fetchall()}
        cur.execute("SELECT id FROM name WHERE name='r1212'")
        roster = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO member (name_id, desk_id) VALUES (%s, %s)",
            (roster, ids["desk-a"]),
        )
        cur.execute(
            "INSERT INTO activity (type, id, desk_id, roster_id, act) "
            "VALUES ('mail', 1, %s, %s, 'send'), ('wake', 1, %s, %s, 'ring')",
            (ids["desk-a"], roster, ids["desk-b"], roster),
        )
        cur.execute(
            "INSERT INTO mail (id, desk_id, roster_id, body) VALUES (1, %s, %s, 'ask')",
            (ids["desk-a"], roster),
        )
        cur.execute(
            "INSERT INTO mail_to (id, desk_id, asked, receipt, opened) VALUES "
            "(1, %s, 1, 0, NULL), (1, %s, 0, 0, NULL)",
            (ids["desk-a"], ids["desk-b"]),
        )
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id) "
            "VALUES ('mail', 1, 'none', 'sent', 'send', %s), "
            "('wake', 1, 'none', 'queued', 'wake_sent', %s)",
            (ids["desk-a"], ids["desk-b"]),
        )
        cn.commit()
        cur.close()

        active = active_desk_ids(cn, "7d")
        assert ids["desk-a"] in active
        assert ids["desk-b"] not in active

        wall = read_scores(cn, "7d")
        assert [d["desk"] for d in wall["desks"]] == ["desk-a"]
        names = [s["name"] for s in wall["desks"][0]["scores"]]
        assert list(names) == list(SCORE_NAMES)
        unread = next(s for s in wall["desks"][0]["scores"] if s["name"] == "oldest_unread_ask_age_ms")
        assert unread["items"] == [1]
        required = next(s for s in wall["desks"][0]["scores"] if s["name"] == "unanswered_required_n")
        assert required["value"] == 1
        assert wall["desks"][0]["scores"][0]["rollup"]["n_active"] == 1
        assert wall["desks"][0]["scores"][0]["rollup"]["median"] is None

        cur = cn.cursor()
        cur.execute("SELECT COUNT(*) FROM score_view")
        assert cur.fetchone()[0] == 0
        cur.close()
        read_scores(cn, "7d", viewer="desk-a")
        read_scores(cn, "7d", viewer="desk-a")
        cur = cn.cursor()
        cur.execute("SELECT n FROM score_view WHERE viewer_id=%s LIMIT 1", (ids["desk-a"],))
        assert cur.fetchone()[0] == 2
        cur.close()
    finally:
        drop_db(cn, db)
