"""Card 1163: every name row is unique, retired rows included, and a live focus list survives."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def _mysql_up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:
        pytest.skip(f"no MySQL for the 1163 migration test: {exc}")


def _rows(cn, sql: str, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def test_retired_loser_is_renamed_and_live_focus_stays_linked():
    """Live desk foo + retired label foo, and live desk bar + live label bar.

    The retired label is renamed. The live label is renamed and stays the desk's focus list.
    A second ensure changes nothing.
    """
    _mysql_up()
    from agent_coord.install import migrate
    from tests.beta_book import drop_db, make_main_book

    cn, db = make_main_book("mill_1163_ret", routines=True)
    try:
        cur = cn.cursor()
        cur.execute(
            "INSERT INTO name (type, name) VALUES"
            " ('desk', 'foo'), ('label', 'foo'), ('desk', 'bar'), ('label', 'bar')"
        )
        cur.execute(
            "UPDATE name SET deleted = CURRENT_TIMESTAMP(6) WHERE type = 'label' AND name = 'foo'"
        )
        cn.commit()
        cur.close()

        res = migrate.ensure(cn)
        applied = [str(a) for a in res["applied"]]
        assert "migrate_1163:renamed(2)" in applied, applied

        names = _rows(
            cn,
            "SELECT type, name, deleted IS NOT NULL FROM name"
            " WHERE name LIKE 'foo%' OR name LIKE 'bar%' ORDER BY name, type",
        )
        assert ("desk", "bar", 0) in [(r[0], r[1], int(r[2])) for r in names]
        assert ("label", "bar-1", 0) in [(r[0], r[1], int(r[2])) for r in names]
        assert ("desk", "foo", 0) in [(r[0], r[1], int(r[2])) for r in names]
        assert ("label", "foo-1", 1) in [(r[0], r[1], int(r[2])) for r in names]
        assert _rows(cn, "SELECT name FROM name GROUP BY name HAVING COUNT(*) > 1") == []

        linked = _rows(
            cn,
            "SELECT d.name, l.name, l.deleted IS NULL"
            " FROM seat s"
            " JOIN name d ON d.id = s.desk_id"
            " JOIN name l ON l.id = s.focus_label_id"
            " WHERE d.name IN ('foo', 'bar') ORDER BY d.name",
        )
        assert [(r[0], r[1], int(r[2])) for r in linked] == [("bar", "bar-1", 1)]

        body = _rows(
            cn,
            "SELECT ACTION_STATEMENT FROM information_schema.TRIGGERS"
            " WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME = 'name_fixed'",
        )
        assert body and "mill_allow_retired_rename" in str(body[0][0])

        again = migrate.ensure(cn)
        assert not any(str(a).startswith("migrate_1163:renamed") for a in again["applied"])
        assert _rows(cn, "SELECT name FROM name WHERE type = 'label' AND name IN ('foo', 'bar')") == []
    finally:
        drop_db(cn, db)
