"""Card roster NOT NULL punch: throwaway A/B backfill + insert-without fails.

Standing rule: prove on a local throwaway DB before live office SQL.
Live apply (mail/todo/score backfill + ALTER NOT NULL) is out of band.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import apply, connect
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_card_affil_nn_test")

_BACKFILL = [
    """
    UPDATE mail m JOIN activity a ON a.type = 'mail' AND a.id = m.id
      SET m.roster_id = a.roster_id WHERE m.roster_id IS NULL
    """,
    """
    UPDATE todo t JOIN activity a ON a.type = 'todo' AND a.id = t.id
      SET t.roster_id = a.roster_id WHERE t.roster_id IS NULL
    """,
    """
    UPDATE score s JOIN activity a ON a.type = 'score' AND a.id = s.id
      SET s.roster_id = a.roster_id WHERE s.roster_id IS NULL
    """,
]
_ALTER_NN = [
    "ALTER TABLE mail  MODIFY roster_id BIGINT UNSIGNED NOT NULL",
    "ALTER TABLE todo  MODIFY roster_id BIGINT UNSIGNED NOT NULL",
    "ALTER TABLE score MODIFY roster_id BIGINT UNSIGNED NOT NULL",
]


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


def _exec(cn, sql: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        cn.commit()
    finally:
        cur.close()


def _null_counts(cn) -> dict[str, int]:
    return {
        "mail": int(scalar(cn, "SELECT COUNT(*) FROM mail WHERE roster_id IS NULL") or 0),
        "todo": int(scalar(cn, "SELECT COUNT(*) FROM todo WHERE roster_id IS NULL") or 0),
        "score": int(scalar(cn, "SELECT COUNT(*) FROM score WHERE roster_id IS NULL") or 0),
    }


def test_insert_without_roster_id_fails(cn) -> None:
    """Alpha NOT NULL: omitting roster_id must fail (no DEFAULT 1 / Office)."""
    seed_names(cn, ("nn_desk", "desk"))
    desk = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name='nn_desk'"))
    office = int(scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'"))
    _exec(cn, "SET FOREIGN_KEY_CHECKS=0")
    with pytest.raises(Exception) as ei:
        _exec(
            cn,
            "INSERT INTO mail (desk_id, body) VALUES (%s, 'missing-affil')",
            (desk,),
        )
    msg = str(ei.value).lower()
    assert "roster_id" in msg or "doesn't have a default" in msg or "cannot be null" in msg
    with pytest.raises(Exception):
        _exec(
            cn,
            "INSERT INTO todo (updated_id, creator_id, status, body) "
            "VALUES (%s, %s, 'open', 'missing-affil')",
            (desk, desk),
        )
    with pytest.raises(Exception):
        _exec(
            cn,
            "INSERT INTO score (desk_id, kpi, value, target, note) "
            "VALUES (%s, 'nn.kpi', '0', '', '')",
            (desk,),
        )
    # Explicit value still works (seed path shape).
    _exec(
        cn,
        "INSERT INTO score (desk_id, roster_id, kpi, value, target, note) "
        "VALUES (%s, %s, 'nn.kpi.ok', '0', '', '')",
        (desk, office),
    )
    _exec(cn, "SET FOREIGN_KEY_CHECKS=1")


def test_throwaway_ab_backfill_then_alter(cn) -> None:
    """A/B: soften to NULL, plant NULLs + activity, backfill, ALTER NOT NULL, 0 nulls."""
    seed_names(cn, ("ab_proj", "roster"), ("ab_desk", "desk"))
    proj = int(scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='ab_proj'"))
    desk = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name='ab_desk'"))
    office = int(scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='Office'"))

    # Soften alpha NOT NULL -> live-book NULL shape for the prove.
    _exec(cn, "ALTER TABLE mail  MODIFY roster_id BIGINT UNSIGNED NULL")
    _exec(cn, "ALTER TABLE todo  MODIFY roster_id BIGINT UNSIGNED NULL")
    _exec(cn, "ALTER TABLE score MODIFY roster_id BIGINT UNSIGNED NULL")

    _exec(cn, "SET FOREIGN_KEY_CHECKS=0")
    # mail with NULL card affil + matching activity
    _exec(cn, "INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, NULL, 'ab-mail')", (desk,))
    mid = int(scalar(cn, "SELECT LAST_INSERT_ID()"))
    _exec(
        cn,
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('mail', %s, NOW(6), %s, %s, 'create', 1)",
        (mid, desk, proj),
    )
    # todo
    _exec(
        cn,
        "INSERT INTO todo (updated_id, roster_id, creator_id, status, body) "
        "VALUES (%s, NULL, %s, 'open', 'ab-todo')",
        (desk, desk),
    )
    tid = int(scalar(cn, "SELECT LAST_INSERT_ID()"))
    _exec(
        cn,
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('todo', %s, NOW(6), %s, %s, 'create', 1)",
        (tid, desk, proj),
    )
    # score
    _exec(
        cn,
        "INSERT INTO score (desk_id, roster_id, kpi, value, target, note) "
        "VALUES (%s, NULL, 'ab.kpi', '0', '', '')",
        (desk,),
    )
    sid = int(scalar(cn, "SELECT LAST_INSERT_ID()"))
    _exec(
        cn,
        "INSERT INTO activity (type, id, updated, desk_id, roster_id, act, bytes) "
        "VALUES ('score', %s, NOW(6), %s, %s, 'create', 1)",
        (sid, desk, office),
    )
    # Orphan card with no activity row (cannot backfill) - risk documented.
    _exec(
        cn,
        "INSERT INTO mail (desk_id, roster_id, body) VALUES (%s, NULL, 'orphan-no-act')",
        (desk,),
    )
    orphan = int(scalar(cn, "SELECT LAST_INSERT_ID()"))
    _exec(cn, "SET FOREIGN_KEY_CHECKS=1")

    before = _null_counts(cn)
    assert before == {"mail": 2, "todo": 1, "score": 1}, before

    for stmt in _BACKFILL:
        _exec(cn, stmt)

    after_bf = _null_counts(cn)
    assert after_bf["todo"] == 0 and after_bf["score"] == 0
    assert after_bf["mail"] == 1  # orphan with no activity remains NULL
    assert int(scalar(cn, "SELECT roster_id FROM mail WHERE id=%s", (mid,))) == proj
    assert int(scalar(cn, "SELECT roster_id FROM todo WHERE id=%s", (tid,))) == proj
    assert int(scalar(cn, "SELECT roster_id FROM score WHERE id=%s", (sid,))) == office

    # ALTER NOT NULL fails while orphan NULL remains.
    with pytest.raises(Exception) as ei:
        _exec(cn, _ALTER_NN[0])
    assert "cannot be null" in str(ei.value).lower() or "1048" in str(ei.value) or "1138" in str(
        ei.value
    ) or "invalid use of null" in str(ei.value).lower() or "column" in str(ei.value).lower()

    # Fix orphan (live would delete or manual-affil), then ALTER succeeds.
    _exec(cn, "UPDATE mail SET roster_id=%s WHERE id=%s", (office, orphan))
    assert _null_counts(cn) == {"mail": 0, "todo": 0, "score": 0}
    for stmt in _ALTER_NN:
        _exec(cn, stmt)

    # Post-ALTER: insert without roster_id fails.
    _exec(cn, "SET FOREIGN_KEY_CHECKS=0")
    with pytest.raises(Exception):
        _exec(cn, "INSERT INTO mail (desk_id, body) VALUES (%s, 'post-alter')", (desk,))
    _exec(cn, "SET FOREIGN_KEY_CHECKS=1")
