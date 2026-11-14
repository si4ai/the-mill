"""Card 1200: foreign keys cascade on id change, and bearer salts copy by desk name."""
from __future__ import annotations

import pytest

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]

SALT_LOCAL = "a" * 64
SALT_OTHER = "b" * 64


def _mysql_up() -> None:
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:
        pytest.skip(f"no MySQL for the 1200 migration test: {exc}")


def _rows(cn, sql: str, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def test_id_change_cascades_only_with_the_flag_and_salts_copy():
    _mysql_up()
    from agent_coord.install import migrate
    from tests.beta_book import drop_db, make_main_book

    cn, db = make_main_book("mill_1200", routines=True)
    upload = db + "_up"
    try:
        res = migrate.ensure(cn)
        assert "migrate_1200:cascade" in [str(a) for a in res["applied"]]
        assert migrate.apply_1200(cn) == []
        rule = _rows(
            cn,
            "SELECT UPDATE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'fk_member_name'",
        )
        assert str(rule[0][0]).upper() == "CASCADE"

        cur = cn.cursor()
        cur.execute(
            "INSERT INTO name (type, name) VALUES ('desk', 'd1200'), ('roster', 'r1200')"
        )
        cur.execute(
            "INSERT INTO seat (desk_id, token_hash) "
            "SELECT id, %s FROM name WHERE type = 'desk' AND name = 'd1200'",
            (SALT_LOCAL,),
        )
        cur.execute(
            "INSERT INTO member (name_id, desk_id) "
            "SELECT r.id, d.id FROM name r JOIN name d "
            "WHERE r.name = 'r1200' AND d.name = 'd1200'"
        )
        cn.commit()
        desk_id = _rows(cn, "SELECT id FROM name WHERE name = 'd1200'")[0][0]
        roster_id = _rows(cn, "SELECT id FROM name WHERE name = 'r1200'")[0][0]
        with pytest.raises(Exception, match="id is fixed"):
            cur.execute("UPDATE name SET id = %s WHERE id = %s", (int(roster_id) + 5000, roster_id))
            cn.commit()
        cn.rollback()
        cur.execute("SET @mill_allow_name_id_change = 1")
        new_id = int(roster_id) + 5000
        cur.execute("UPDATE name SET id = %s WHERE id = %s", (new_id, roster_id))
        cur.execute("SET @mill_allow_name_id_change = NULL")
        cn.commit()
        cur.close()
        assert _rows(
            cn,
            "SELECT m.name_id FROM member m JOIN name d ON d.id = m.desk_id WHERE d.name = 'd1200'",
        )[0][0] == new_id

        cur = cn.cursor()
        cur.execute(f"CREATE DATABASE `{upload}`")
        cur.execute(
            f"CREATE TABLE `{upload}`.name ("
            "id BIGINT UNSIGNED NOT NULL PRIMARY KEY, "
            "type VARCHAR(16) NOT NULL, name VARCHAR(64) NOT NULL)"
        )
        cur.execute(
            f"CREATE TABLE `{upload}`.seat ("
            "desk_id BIGINT UNSIGNED NOT NULL PRIMARY KEY, token_hash CHAR(64) NULL)"
        )
        cur.execute(
            f"INSERT INTO `{upload}`.name (id, type, name) VALUES (%s, 'desk', 'd1200')",
            (int(desk_id),),
        )
        cur.execute(
            f"INSERT INTO `{upload}`.seat (desk_id, token_hash) VALUES (%s, %s)",
            (int(desk_id), SALT_OTHER),
        )
        cur.execute("CALL mill_import_bearer_salts(%s)", (upload,))
        cn.commit()
        got = _rows(cn, f"SELECT token_hash FROM `{upload}`.seat")
        assert got[0][0] == SALT_LOCAL
        with pytest.raises(Exception, match="plain identifier"):
            cur.execute("CALL mill_import_bearer_salts(%s)", ("bad-name",))
        cur.close()
    finally:
        cur = cn.cursor()
        cur.execute(f"DROP DATABASE IF EXISTS `{upload}`")
        cn.commit()
        cur.close()
        drop_db(cn, db)
