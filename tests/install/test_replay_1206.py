"""Cards 1205 and 1206: replay keyset is an index seek, and mail edges ignore the 500 cap."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def _up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:
        pytest.skip(f"no MySQL for the replay test: {exc}")


def _q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def test_replay_keyset_is_flat_and_mail_edges_pass_the_500_cap():
    _up()
    from agent_coord.server.records.replay import v1_replay
    from tests.beta_book import drop_db, make_fresh_book

    cn, db = make_fresh_book("mill_replay")
    try:
        cur = cn.cursor()
        cur.execute("INSERT INTO name (type, name) VALUES ('roster', 'r1206'), ('desk', 'from-desk'), ('desk', 'to-a'), ('desk', 'to-b'), ('desk', 'to-c')")
        cur.execute(
            "INSERT INTO seat (desk_id, token_hash) "
            "SELECT id, %s FROM name WHERE name IN ('from-desk', 'to-a', 'to-b', 'to-c') "
            "AND id NOT IN (SELECT desk_id FROM seat)",
            ("c" * 64,),
        )
        cur.execute("SELECT id FROM name WHERE name = 'r1206'")
        roster = cur.fetchone()[0]
        cur.execute("SELECT id FROM name WHERE name = 'from-desk'")
        desk = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('mail', 1, %s, %s, 'send')",
            (desk, roster),
        )
        cur.execute(
            "INSERT INTO mail (id, desk_id, roster_id, body) VALUES (1, %s, %s, 'old')",
            (desk, roster),
        )
        cur.execute(
            "INSERT INTO mail_to (id, desk_id) SELECT 1, id FROM name WHERE name IN ('to-a', 'to-b', 'to-c')"
        )
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id) "
            "VALUES ('mail', 1, 'none', 'sent', 'send', %s)",
            (desk,),
        )
        cur.execute("SELECT id FROM name WHERE name = 'to-a'")
        other = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES "
            "('todo', 2, %s, %s, 'claim'), ('hold', 3, %s, %s, 'hold')",
            (desk, roster, desk, roster),
        )
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id) VALUES "
            "('todo', 2, 'open', 'claimed', 'claim', %s), "
            "('todo', 2, 'claimed', 'claimed', 'take_over', %s), "
            "('hold', 3, 'free', 'held', 'hold_grant', %s)",
            (desk, other, desk),
        )
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, meta) "
            "VALUES ('hold', 3, 'held', 'free', 'hold_force', %s, %s)",
            (desk, '{"by": %d}' % int(other)),
        )
        # 6000 later rows on the same activity. The old letter stays reachable by id.
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id) "
            "SELECT 'mail', 1, 'none', 'sent', 'send', %s FROM "
            "(SELECT 1 AS n UNION SELECT 2) a, "
            "(SELECT 1 AS n UNION SELECT 2) b, "
            "(SELECT 1 AS n UNION SELECT 2) c, "
            "(SELECT 1 AS n UNION SELECT 2) d, "
            "(SELECT 1 AS n UNION SELECT 2) e, "
            "(SELECT 1 AS n UNION SELECT 2) f, "
            "(SELECT 1 AS n UNION SELECT 2) g, "
            "(SELECT 1 AS n UNION SELECT 2) h, "
            "(SELECT 1 AS n UNION SELECT 2) i, "
            "(SELECT 1 AS n UNION SELECT 2) j, "
            "(SELECT 1 AS n UNION SELECT 2) k, "
            "(SELECT 1 AS n UNION SELECT 2) l, "
            "(SELECT 1 AS n UNION SELECT 2) m",
            (desk,),
        )
        cn.commit()
        cur.close()
        assert _q(cn, "SELECT COUNT(*) FROM transition")[0][0] >= 6000
        bulk = _q(
            cn,
            "SELECT MIN(id) FROM transition WHERE activity_type = 'mail' AND activity_id = 1 AND id > "
            "(SELECT MIN(id) FROM transition WHERE activity_type = 'mail' AND activity_id = 1)",
        )[0][0]
        early = v1_replay(cn, {"limit": ["10"], "before": [str(bulk)], "project": ["r1206"]})
        by_reason = {(r["type"], r["reason"]): r for r in early["rows"]}
        claim = by_reason[("todo", "claim")]
        takeover = by_reason[("todo", "take_over")]
        assert claim["to_desks"] == ["from-desk"]
        assert takeover["from_desk"] == "from-desk" and takeover["to_desks"] == ["to-a"]
        assert claim["to_desks"] != takeover["to_desks"]
        assert by_reason[("hold", "hold_grant")]["to_desks"] == ["from-desk"]
        assert by_reason[("hold", "hold_force")]["to_desks"] == ["to-a"]

        head = v1_replay(cn, {"limit": ["100"], "project": ["r1206"]})
        assert len(head["rows"]) == 100
        assert head["has_more"] is True
        assert head["newest_id"] > head["oldest_id"]
        ids = [r["id"] for r in head["rows"]]
        assert ids == sorted(ids, reverse=True)

        older = v1_replay(cn, {"limit": ["100"], "before": [str(head["oldest_id"])], "project": ["r1206"]})
        assert older["rows"]
        assert max(r["id"] for r in older["rows"]) < head["oldest_id"]
        assert older["has_more"] is True

        plan = _q(
            cn,
            "EXPLAIN SELECT id FROM transition WHERE id < %s ORDER BY id DESC LIMIT 100",
            (head["oldest_id"],),
        )
        # columns vary by server; the key column is the one that says PRIMARY
        flat = " ".join(str(cell) for row in plan for cell in row)
        assert "PRIMARY" in flat

        # walk to the first mail edge; its three recipients are still on the row
        cursor = head["oldest_id"]
        found = None
        for _ in range(80):
            page = v1_replay(cn, {"limit": ["100"], "before": [str(cursor)], "project": ["r1206"]})
            for row in page["rows"]:
                if row["activity_id"] == 1 and row["to_desks"]:
                    found = row
                    break
            if found or not page["has_more"]:
                break
            cursor = page["oldest_id"]
        assert found is not None
        assert found["from_desk"] == "from-desk"
        assert found["to_desks"] == ["to-a", "to-b", "to-c"]
        assert found["from_state"] == "none" and found["to_state"] == "sent"
    finally:
        drop_db(cn, db)
