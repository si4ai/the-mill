"""#216: payload first. The payload table assigns the id, LAST_INSERT_ID() is that id,
then the activity row. Activity is the timeline, not a parent: mail, todo, join, hold and
score have no FK to it. label and tree keep theirs. No writer turns FK checks off.

Supersedes the #205 activity-first allocator (Office lock + information_schema peek).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from agent_coord.install import migrate
from agent_coord.server.records import apply
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_insert_216")
SQL = Path("agent_coord/server/sql")
PAYLOAD_FKS = (
    ("mail", "fk_mail_activity"),
    ("todo", "fk_todo_activity"),
    # fk_join_activity: a book that still has it has a `join` table, and the
    # #818 migration drops it while turning that table into doing.
    ("hold", "fk_hold_activity"),
    ("score", "fk_score_activity"),
)
KEPT_FKS = (("label", "fk_label_activity"), ("tree", "fk_tree_activity"))


def _direct():
    """A direct connection to TEST_DB (not the shared pool, which may point at another suite's DB)."""
    import mysql.connector

    kw = dict(_conn_kwargs())
    kw["database"] = TEST_DB
    return mysql.connector.connect(**kw)


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
    cn = _direct()
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    yield c
    c.close()


def _proc(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("CREATE PROCEDURE " + name + "(", 1)[1].split("CREATE PROCEDURE", 1)[0]


def _n(cn, sql: str, args: tuple = ()) -> int:
    cur = cn.cursor()
    cur.execute(sql, args)
    row = cur.fetchone()
    cur.close()
    return int(row[0]) if row and row[0] is not None else 0


def _exec(cn, sql: str, args: tuple = ()) -> None:
    cur = cn.cursor()
    cur.execute(sql, args)
    cn.commit()
    cur.close()


def _fk(cn, table: str, name: str) -> bool:
    return _n(
        cn,
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'",
        (table, name),
    ) == 1


# ---- source shape ----


def test_insert_sources_are_payload_first() -> None:
    for path, name, table in (
        (SQL / "sp_mail.sql", "mill_mail_insert", "mail"),
        (SQL / "sp_todo.sql", "mill_todo_insert", "todo"),
        (SQL / "sp_todo.sql", "mill_todo_insert_attached", "todo"),
    ):
        body = _proc(path, name)
        for gone in ("FOREIGN_KEY_CHECKS", "information_schema", "AUTO_INCREMENT", "v_gate", "WHERE id = 1 FOR UPDATE"):
            assert gone not in body, (name, gone)
        ins = body.index(f"INSERT INTO {table} (")
        lid = body.index("SET v_id = LAST_INSERT_ID()")
        put = body.index(f"CALL mill_activity_put('{table}', v_id")
        assert ins < lid < put, name
        assert f"INSERT INTO {table} (id," not in body


def test_no_writer_turns_fk_checks_off() -> None:
    for name in ("sp_mail.sql", "sp_todo.sql", "sp_join.sql", "sp_hold.sql", "sp_score.sql", "tables.sql"):
        assert "FOREIGN_KEY_CHECKS" not in (SQL / name).read_text(encoding="utf-8"), name
    tick = Path("agent_coord/server/score_tick.py").read_text(encoding="utf-8")
    assert "FOREIGN_KEY_CHECKS" not in tick


def test_touched_sp_files_are_fully_refreshed() -> None:
    for name in ("sp_mail.sql", "sp_todo.sql", "sp_join.sql", "sp_hold.sql", "sp_score.sql"):
        assert name in migrate._SP_FULL_REFRESH, name
    rules = {r[1] for r in migrate._FK_RULES}
    for _t, name in PAYLOAD_FKS:
        assert name not in rules, name


# ---- fresh book ----


def test_fresh_book_has_no_payload_fks(cn) -> None:
    for table, name in PAYLOAD_FKS:
        assert not _fk(cn, table, name), name
    for table, name in KEPT_FKS:
        assert _fk(cn, table, name), name
    assert _n(cn, "SELECT @@FOREIGN_KEY_CHECKS") == 1
    # seeded system scores still have their timeline rows
    assert _n(cn, "SELECT COUNT(*) FROM score WHERE kpi IN ('mill-wall.ticks','mill-desk.idle_verbs','mill-desk.hint_drop')") == 3
    assert _n(
        cn,
        "SELECT COUNT(*) FROM score s JOIN activity a ON a.type='score' AND a.id=s.id"
        " WHERE s.kpi IN ('mill-wall.ticks','mill-desk.idle_verbs','mill-desk.hint_drop')",
    ) == 3


# ---- inserts ----


def test_mail_and_todo_ids_come_from_the_table(cn) -> None:
    one = int(rec_mail.insert(cn, "unit", "a", "b", "first")[0]["id"])
    two = int(rec_mail.insert(cn, "unit", "a", "b", "second")[0]["id"])
    assert two > one
    for mid in (one, two):
        assert _n(cn, "SELECT COUNT(*) FROM mail WHERE id=%s", (mid,)) == 1
        assert _n(cn, "SELECT COUNT(*) FROM activity WHERE type='mail' AND id=%s", (mid,)) == 1
        assert _n(cn, "SELECT COUNT(*) FROM mail_to WHERE type='mail' AND id=%s", (mid,)) >= 1
    card = int(rec_todo.insert(cn, "unit", "a", "open", "plain")[0]["id"])
    assert _n(cn, "SELECT MAX(id) FROM todo") == card
    assert _n(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (card,)) == 1
    assert _n(cn, "SELECT @@FOREIGN_KEY_CHECKS") == 1


def test_deleted_id_is_not_reused(cn) -> None:
    card = int(rec_todo.insert(cn, "unit", "a", "open", "gone soon")[0]["id"])
    _exec(cn, "DELETE FROM watcher WHERE type='todo' AND id=%s", (card,))
    _exec(cn, "DELETE FROM activity WHERE type='todo' AND id=%s", (card,))
    _exec(cn, "DELETE FROM todo WHERE id=%s", (card,))
    nxt = int(rec_todo.insert(cn, "unit", "a", "open", "after")[0]["id"])
    assert nxt > card


def _act_fail_trigger(cn, kind: str) -> None:
    _exec(cn, "DROP TRIGGER IF EXISTS t216_act_fail")
    _exec(
        cn,
        "CREATE TRIGGER t216_act_fail BEFORE INSERT ON activity FOR EACH ROW "
        f"BEGIN IF NEW.type = '{kind}' THEN "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced activity failure'; END IF; END",
    )


def test_failed_activity_put_rolls_back_mail(cn) -> None:
    letters = _n(cn, "SELECT COUNT(*) FROM mail")
    tos = _n(cn, "SELECT COUNT(*) FROM mail_to")
    _act_fail_trigger(cn, "mail")
    try:
        with pytest.raises(Exception, match="forced activity failure"):
            rec_mail.insert(cn, "unit", "a", "b", "doomed")
    finally:
        _exec(cn, "DROP TRIGGER IF EXISTS t216_act_fail")
    assert _n(cn, "SELECT COUNT(*) FROM mail") == letters
    assert _n(cn, "SELECT COUNT(*) FROM mail_to") == tos
    assert _n(cn, "SELECT COUNT(*) FROM mail m LEFT JOIN activity a ON a.type='mail' AND a.id=m.id WHERE a.id IS NULL") == 0
    assert _n(cn, "SELECT @@FOREIGN_KEY_CHECKS") == 1


def test_failed_activity_put_rolls_back_todo_and_attached(cn) -> None:
    root = int(rec_mail.insert(cn, "unit", "a", "b", "root")[0]["id"])
    cards = _n(cn, "SELECT COUNT(*) FROM todo")
    trees = _n(cn, "SELECT COUNT(*) FROM tree")
    _act_fail_trigger(cn, "todo")
    try:
        with pytest.raises(Exception, match="forced activity failure"):
            rec_todo.insert(cn, "unit", "a", "open", "doomed")
        with pytest.raises(Exception, match="forced activity failure"):
            rec_todo.insert_attached(cn, "unit", "a", "open", "doomed child", "mail", root)
    finally:
        _exec(cn, "DROP TRIGGER IF EXISTS t216_act_fail")
    assert _n(cn, "SELECT COUNT(*) FROM todo") == cards
    assert _n(cn, "SELECT COUNT(*) FROM tree") == trees
    assert _n(cn, "SELECT COUNT(*) FROM todo t LEFT JOIN activity a ON a.type='todo' AND a.id=t.id WHERE a.id IS NULL") == 0


def test_failed_tree_place_rolls_back_attached_card(cn) -> None:
    root = int(rec_mail.insert(cn, "unit", "a", "b", "root2")[0]["id"])
    cards = _n(cn, "SELECT COUNT(*) FROM todo")
    acts = _n(cn, "SELECT COUNT(*) FROM activity WHERE type='todo'")
    _exec(cn, "DROP TRIGGER IF EXISTS t216_tree_fail")
    _exec(
        cn,
        "CREATE TRIGGER t216_tree_fail BEFORE INSERT ON tree FOR EACH ROW "
        "BEGIN IF NEW.type = 'todo' THEN "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced tree failure'; END IF; END",
    )
    try:
        with pytest.raises(Exception, match="forced tree failure"):
            rec_todo.insert_attached(cn, "unit", "a", "open", "no place", "mail", root)
    finally:
        _exec(cn, "DROP TRIGGER IF EXISTS t216_tree_fail")
    assert _n(cn, "SELECT COUNT(*) FROM todo") == cards
    assert _n(cn, "SELECT COUNT(*) FROM activity WHERE type='todo'") == acts


def test_attached_places_its_own_id_on_the_tree(cn) -> None:
    root = int(rec_mail.insert(cn, "unit", "a", "b", "plan root")[0]["id"])
    # a mail and a todo may share a number; the tree row must be the todo's (type, id)
    first = rec_todo.insert_attached(cn, "unit", "a", "open", "child one", "mail", root)[0]
    second = rec_todo.insert_attached(cn, "unit", "a", "open", "child two", "mail", root)[0]
    c1, c2 = int(first["id"]), int(second["id"])
    assert c2 > c1
    for cid, body in ((c1, "child one"), (c2, "child two")):
        assert _n(cn, "SELECT COUNT(*) FROM todo WHERE id=%s AND body=%s", (cid, body)) == 1
        assert _n(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (cid,)) == 1
        assert _n(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (cid,)) == 1
    plan = _n(cn, "SELECT name_id FROM tree WHERE type='mail' AND id=%s", (root,))
    assert _n(cn, "SELECT name_id FROM tree WHERE type='todo' AND id=%s", (c1,)) == plan
    assert _n(cn, "SELECT name_id FROM tree WHERE type='todo' AND id=%s", (c2,)) == plan
    lft = _n(cn, "SELECT lft FROM tree WHERE type='mail' AND id=%s", (root,))
    rgt = _n(cn, "SELECT rgt FROM tree WHERE type='mail' AND id=%s", (root,))
    assert lft < _n(cn, "SELECT lft FROM tree WHERE type='todo' AND id=%s", (c2,)) < rgt


def test_concurrent_inserts_get_distinct_ids_without_office_lock(cn) -> None:
    # Hold the Office row the #205 allocator used to lock. Inserts must not wait on it.
    blocker = _direct()
    bcur = blocker.cursor()
    bcur.execute("START TRANSACTION")
    bcur.execute("SELECT id FROM name WHERE id = 1 FOR UPDATE")
    bcur.fetchall()
    ids: dict[str, list[int]] = {"mail": [], "todo": []}
    errs: list[BaseException] = []
    lock = threading.Lock()

    def work(i: int) -> None:
        c = None
        try:
            c = _direct()
            cur = c.cursor()
            cur.execute("SET SESSION innodb_lock_wait_timeout = 3")
            cur.close()
            for j in range(5):
                m = int(rec_mail.insert(c, "unit", "a", "b", f"race {i}.{j}")[0]["id"])
                t = int(rec_todo.insert(c, "unit", "a", "open", f"race {i}.{j}")[0]["id"])
                with lock:
                    ids["mail"].append(m)
                    ids["todo"].append(t)
        except BaseException as e:  # noqa: BLE001
            errs.append(e)
        finally:
            if c is not None:
                c.close()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    try:
        for th in threads:
            th.start()
        for th in threads:
            th.join(60)
    finally:
        blocker.rollback()
        bcur.close()
        blocker.close()
    assert not errs, errs
    cn.commit()  # end this connection's read snapshot so the other sessions' rows show
    for kind in ("mail", "todo"):
        got = ids[kind]
        assert len(got) == 20
        assert len(set(got)) == 20, kind
        marks = ",".join(str(x) for x in got)
        assert _n(cn, f"SELECT COUNT(*) FROM activity WHERE type='{kind}' AND id IN ({marks})") == 20
        assert _n(cn, f"SELECT COUNT(*) FROM {kind} WHERE id IN ({marks})") == 20


# ---- existing book ----


def test_existing_book_with_payload_fks_migrates(cn) -> None:
    # Build the pre-#216 shape: payload FKs present and an old insert procedure.
    for table, name in PAYLOAD_FKS:
        if not _fk(cn, table, name):
            _exec(
                cn,
                f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` FOREIGN KEY (type, id) "
                "REFERENCES activity (type, id) ON DELETE RESTRICT",
            )
    _exec(cn, "DROP PROCEDURE IF EXISTS mill_todo_insert")
    _exec(
        cn,
        "CREATE PROCEDURE mill_todo_insert("
        "IN p_project VARCHAR(64), IN p_desk VARCHAR(64), IN p_status VARCHAR(16), IN p_body VARCHAR(4096)) "
        "BEGIN SET FOREIGN_KEY_CHECKS = 0; SELECT 1 AS id; END",
    )
    for table, name in PAYLOAD_FKS:
        assert _fk(cn, table, name), name

    out = migrate.ensure(cn)
    applied = out["applied"]
    for table, name in PAYLOAD_FKS:
        assert f"drop:{name}" in applied, name
        assert not _fk(cn, table, name), name
    for table, name in KEPT_FKS:
        assert _fk(cn, table, name), name
    cur = cn.cursor()
    cur.execute(
        "SELECT ROUTINE_NAME, ROUTINE_DEFINITION FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE'"
    )
    bodies = {str(r[0]): str(r[1] or "") for r in cur.fetchall()}
    cur.close()
    assert "LAST_INSERT_ID" in bodies["mill_todo_insert"]
    for name, body in bodies.items():
        if name.startswith(("mill_mail_", "mill_todo_", "mill_join_", "mill_hold_", "mill_score_", "mill_wall_")):
            assert "FOREIGN_KEY_CHECKS" not in body, name
    for name in ("mill_mail_insert", "mill_todo_insert", "mill_todo_insert_attached"):
        assert "information_schema" not in bodies[name].lower(), name

    # second ensure is a no-op for the FK step
    again = migrate.ensure(cn)["applied"]
    assert not [a for a in again if str(a).startswith("drop:")]
    card = int(rec_todo.insert(cn, "unit", "a", "open", "after migrate")[0]["id"])
    assert _n(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (card,)) == 1
