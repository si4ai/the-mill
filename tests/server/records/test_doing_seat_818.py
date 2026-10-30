"""#818 on a real book: join becomes doing, the seat splits off. Row F117 (doing-schema).

(a) the migration keeps every join id, and every activity, watcher and label
    row that pointed at a join now resolves as doing;
(b) the seat holds the per-desk state and connect, socket, wake and reset
    behave as before;
(c) mill doing appends a new entry, it never overwrites;
(d) the migration is idempotent (a second ensure changes nothing);
(e) on_type points at any activity but doing, and a narrower list converges;
(f) a run killed between any two statements converges on the next ensure;
(g) so does a run killed inside the routine reload, after the rename;
(h) sql_state flags a missing or changed routine.

The pre-818 book is built on a wiped tip book: drop seat and doing, put the
old type lists back, create the old `join` table and fill it.
"""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.install import migrate
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.db import call, rows_done, scalar_done
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

OLD5 = "ENUM('mail','todo','join','hold','score')"
TYPE_TABLES = ("activity", "label", "tree", "mail", "mail_to", "todo", "hold", "score")

OLD_JOIN = (
    "CREATE TABLE `join` ("
    " type ENUM('mail','todo','join','hold','score') NOT NULL DEFAULT 'join',"
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
    " updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),"
    " desk_id BIGINT UNSIGNED NOT NULL,"
    " token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,"
    " doing VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',"
    " delivery_mode ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling',"
    " endpoint_url VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,"
    " endpoint_key VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NULL,"
    " wake_on ENUM('all','addressed') NOT NULL DEFAULT 'all',"
    " lan_ip VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,"
    " time_connect DATETIME(6) NULL,"
    " time_disconnect DATETIME(6) NULL,"
    " PRIMARY KEY (type, id), UNIQUE KEY idx_id (id), UNIQUE KEY idx_desk (desk_id),"
    " KEY idx_lan_updated (lan_ip, updated), KEY idx_token_hash (token_hash),"
    " CONSTRAINT fk_join_desk FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)

# Old rows: (desk, id, doing, token, delivery, url, key, wake_on, lan, connected)
OLD_ROWS = (
    ("fx818-a", 7, "reading letter 2516 | tests running", "tok-a", "webhook",
     "https://hooks.example.test/fx818-a", "fx818-key-a", "addressed", "192.0.2.7", True),
    ("fx818-b", 11, "present", None, "websocket", None, None, "all", None, False),
    ("fx818-c", 12, "", "tok-c", "polling", None, None, "all", "192.0.2.12", True),
)


def _x(cn, sql: str, args: tuple = ()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()


def _ctype(cn, table: str) -> str:
    return str(scalar_done(
        cn,
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = 'type'",
        (table,),
    ) or "")


def _has_table(cn, table: str) -> bool:
    return bool(scalar_done(
        cn,
        "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (table,),
    ))


def _desk_id(cn, desk: str) -> int:
    return int(scalar_done(cn, "SELECT id FROM name WHERE type = 'desk' AND name = %s", (desk,)))


def _old_book(cn) -> dict:
    """Turn the wiped tip book into a pre-818 book with three seats."""
    seed_names(cn, ("fx818", "roster"), ("fx818-lbl", "label"),
               *[(r[0], "desk") for r in OLD_ROWS])
    _x(cn, "SET FOREIGN_KEY_CHECKS = 0")
    try:
        _x(cn, "DROP TRIGGER IF EXISTS doing_no_delete_in_tree")
        _x(cn, "DROP TABLE IF EXISTS doing")
        _x(cn, "DROP TABLE IF EXISTS seat")
        for t in TYPE_TABLES:
            dflt = {"mail": " DEFAULT 'mail'", "mail_to": " DEFAULT 'mail'", "todo": " DEFAULT 'todo'",
                    "hold": " DEFAULT 'hold'", "score": " DEFAULT 'score'"}.get(t, "")
            _x(cn, f"ALTER TABLE `{t}` MODIFY type {OLD5} NOT NULL{dflt}")
        # A drifted watcher list, as on the cloud book: an older pack's 'name' value stays.
        _x(cn, "ALTER TABLE watcher MODIFY type ENUM('todo','join','hold','score','name') NOT NULL")
        _x(cn, OLD_JOIN)
    finally:
        _x(cn, "SET FOREIGN_KEY_CHECKS = 1")
    for desk, jid, doing, tok, mode, url, key, wake_on, lan, up in OLD_ROWS:
        did = _desk_id(cn, desk)
        _x(cn,
           "INSERT INTO `join` (id, desk_id, token_hash, doing, delivery_mode, endpoint_url,"
           " endpoint_key, wake_on, lan_ip, time_connect, time_disconnect)"
           " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,"
           " IF(%s, NOW(6), NULL), IF(%s, NULL, NOW(6)))",
           (jid, did, token_hash(tok) if tok else None, doing, mode, url, key, wake_on, lan, up, up))
        _x(cn, "INSERT INTO activity (type, id, desk_id, roster_id) VALUES ('join', %s, %s, 1)", (jid, did))
        _x(cn, "INSERT INTO watcher (type, id, desk_id) VALUES ('join', %s, %s)", (jid, did))
    # Distinct, fixed times: the migration must keep them (2557 warnings 1 and 2).
    _x(cn, "UPDATE `join` SET created = '2025-12-01 00:00:00' + INTERVAL id SECOND,"
           " updated = '2026-01-05 06:07:08.123456' + INTERVAL id SECOND")
    _x(cn, "UPDATE activity SET updated = '2026-01-02 03:04:05.5' + INTERVAL id SECOND WHERE type = 'join'")
    _x(cn, "UPDATE watcher SET updated = '2026-01-03 03:04:05.5' + INTERVAL id SECOND")
    lbl = int(scalar_done(cn, "SELECT id FROM name WHERE type = 'label' AND name = 'fx818-lbl'"))
    _x(cn, "INSERT INTO label (type, id, name_id) VALUES ('join', 7, %s)", (lbl,))
    _x(cn, "INSERT INTO watcher (type, id, desk_id) VALUES ('name', 1, %s)", (_desk_id(cn, "fx818-b"),))
    cn.commit()
    return {r[0]: rows_done(cn, "SELECT * FROM `join` WHERE id = %s", (r[1],))[0] for r in OLD_ROWS}


@pytest.fixture(scope="module")
def migrated(cn):
    before = _old_book(cn)
    stamps = lambda: {
        t: {(r["type"], int(r["id"]), int(r["desk_id"])): r["updated"] for r in rows_done(
            cn, f"SELECT type, id, desk_id, updated FROM `{t}`")}
        for t in ("activity", "watcher")
    }
    was = stamps()
    assert migrate.doing_818_needed(cn)
    first = migrate.ensure(cn)
    doing = {int(r["id"]): r["created"] for r in rows_done(cn, "SELECT id, created FROM doing")}
    seat = {int(r["id"]): r["created"] for r in rows_done(cn, "SELECT id, created FROM seat")}
    return {"before": before, "first": first, "updated_before": was, "updated_after": stamps(),
            "doing_created": doing, "seat_created": seat}


def test_a_ids_and_pointers_resolve_as_doing(cn, migrated):
    assert "migrate_818_doing.sql" in migrated["first"]["applied"]
    assert not _has_table(cn, "join")
    rows = {int(r["id"]): r for r in rows_done(cn, "SELECT * FROM doing ORDER BY id")}
    for desk, jid, doing, *_ in OLD_ROWS:
        got = rows[jid]
        assert got["type"] == "doing"
        assert got["desk_id"] == _desk_id(cn, desk)
        assert got["text"] == doing
        assert got["on_type"] is None and got["on_id"] is None
        assert got["waiting_type"] is None and got["waiting_id"] is None
    for table in ("activity", "watcher", "label"):
        assert scalar_done(cn, f"SELECT COUNT(*) FROM `{table}` WHERE type = 'join'") == 0
        dangling = scalar_done(
            cn,
            f"SELECT COUNT(*) FROM `{table}` x WHERE x.type = 'doing'"
            " AND NOT EXISTS (SELECT 1 FROM doing d WHERE d.id = x.id)",
        )
        assert dangling == 0, table
    assert scalar_done(cn, "SELECT COUNT(*) FROM activity WHERE type = 'doing'") == 3
    assert scalar_done(cn, "SELECT COUNT(*) FROM watcher WHERE type = 'doing'") == 3
    assert scalar_done(cn, "SELECT COUNT(*) FROM label WHERE type = 'doing' AND id = 7") == 1
    # The drifted watcher value keeps its row.
    assert scalar_done(cn, "SELECT COUNT(*) FROM watcher WHERE type = 'name'") == 1
    for t in TYPE_TABLES + ("doing",):
        assert _ctype(cn, t) == "enum('mail','todo','doing','hold','score')", t
    assert _ctype(cn, "watcher") == "enum('todo','doing','hold','score','name')"
    # label/tree/mail_to keep their FKs on (type, id).
    fks = {r["CONSTRAINT_NAME"] for r in rows_done(
        cn,
        "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS"
        " WHERE TABLE_SCHEMA = DATABASE() AND CONSTRAINT_TYPE = 'FOREIGN KEY'")}
    assert {"fk_label_activity", "fk_tree_activity", "fk_mail_to_mail",
            "fk_seat_desk", "fk_doing_desk", "fk_doing_roster"} <= fks


def test_a2_the_move_keeps_times(cn, migrated):
    """2557 warn 1: the type move is not an edit, activity/watcher.updated stay.
    Warn 2: a migrated doing entry dates from when its text was set (join.updated);
    the seat keeps when it was made (join.created)."""
    was, now = migrated["updated_before"], migrated["updated_after"]
    for t in ("activity", "watcher"):
        moved = {(("doing" if typ == "join" else typ), i, d): v for (typ, i, d), v in was[t].items()}
        assert now[t] == moved, t
    for desk, jid, *_ in OLD_ROWS:
        old = migrated["before"][desk]
        assert migrated["doing_created"][jid] == old["updated"], desk
        assert migrated["doing_created"][jid] != old["created"], desk
        assert migrated["seat_created"][jid] == old["created"], desk


def test_b_seat_holds_state_and_behaves(cn, migrated):
    cols = {r["COLUMN_NAME"] for r in rows_done(
        cn,
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'seat'")}
    assert "type" not in cols  # not an activity
    assert not {"token_hash", "endpoint_key", "lan_ip", "updated"} & {
        r["COLUMN_NAME"] for r in rows_done(
            cn,
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing'")}
    for desk, jid, *_ in OLD_ROWS:
        old = migrated["before"][desk]
        seat = rows_done(cn, "SELECT * FROM seat WHERE desk_id = %s", (_desk_id(cn, desk),))
        assert len(seat) == 1
        for k in ("token_hash", "delivery_mode", "endpoint_url", "endpoint_key", "wake_on",
                  "lan_ip", "time_connect", "time_disconnect", "created", "updated"):
            # Card 836 (F127): seats on the old default move to addressed once.
            want = "addressed" if k == "wake_on" and old[k] == "all" else old[k]
            assert seat[0][k] == want, (desk, k)
    # Same behavior as before through the procedures.
    assert rec_join.token_matches(cn, "fx818-a", token_hash("tok-a"))
    assert rec_join.desk_for_token_hash(cn, token_hash("tok-c")) == "fx818-c"
    assert rec_join.wake_state(cn, "fx818-a") == {
        "armed": True, "host": "hooks.example.test", "wake_on": "addressed"}
    assert rec_join.wake_target(cn, "fx818-a") == ("https://hooks.example.test/fx818-a", "fx818-key-a")
    rec_join.mark_socket(cn, "fx818-b", up=True)
    seat_b = rows_done(cn, "SELECT time_connect, time_disconnect FROM seat WHERE desk_id = %s",
                       (_desk_id(cn, "fx818-b"),))[0]
    assert seat_b["time_connect"] is not None and seat_b["time_disconnect"] is None
    got = call(cn, "mill_join_connect", ["fx818-b"])[0]
    assert int(got["id"]) == 11  # the bump lands on the desk's current entry
    rec_join.set_lan_ip(cn, "fx818-b", "192.0.2.11")
    assert scalar_done(cn, "SELECT lan_ip FROM seat WHERE desk_id = %s", (_desk_id(cn, "fx818-b"),)) == "192.0.2.11"
    rec_join.wake_off(cn, "fx818-a")
    assert rec_join.wake_target(cn, "fx818-a") is None
    rec_join.reset(cn, "fx818", "fx818-c")
    assert rec_join.token_hash_for_desk(cn, "fx818-c") == ""
    sel = {r["desk"]: r for r in rec_join.select(cn, "")}
    assert sel["fx818-c"]["doing"] == ""
    assert sel["fx818-b"]["type"] == "doing" and sel["fx818-b"]["doing"] == "present"
    # A bump command writes no new entry.
    n = scalar_done(cn, "SELECT COUNT(*) FROM doing")
    rec_join.touch(cn, "fx818", "fx818-b")
    assert scalar_done(cn, "SELECT COUNT(*) FROM doing") == n


def test_c_doing_appends(cn, migrated):
    did = _desk_id(cn, "fx818-a")
    before = rows_done(cn, "SELECT id, text FROM doing WHERE desk_id = %s ORDER BY id", (did,))
    # #818 PR B: a doing is written by --doing on a command, linked to its item.
    from agent_coord.server.records import doing as rec_doing
    from agent_coord.server.records import todo as rec_todo

    tid = int(rec_todo.insert(cn, "fx818", "fx818-a", "open", '{"slug":"c818"}')[0]["id"])
    one = [rec_doing.put(cn, "fx818-a", "pr open, waiting on ci", "todo", tid)]
    two = [rec_doing.put(cn, "fx818-a", "done", "todo", tid)]
    after = rows_done(cn, "SELECT id, text FROM doing WHERE desk_id = %s ORDER BY id", (did,))
    assert after[: len(before)] == before  # nothing overwritten
    assert [r["text"] for r in after[len(before):]] == ["pr open, waiting on ci", "done"]
    assert int(one[0]["id"]) < int(two[0]["id"])
    for r in after[len(before):]:
        assert scalar_done(cn, "SELECT COUNT(*) FROM activity WHERE type = 'doing' AND id = %s", (r["id"],)) == 1
    sel = {r["desk"]: r for r in rec_join.select(cn, "")}
    assert sel["fx818-a"]["doing"] == "done"
    assert int(sel["fx818-a"]["id"]) == int(two[0]["id"])


def test_d_migration_is_idempotent(cn, migrated):
    snap = lambda: {
        t: scalar_done(cn, f"SELECT COUNT(*) FROM `{t}`")
        for t in ("activity", "watcher", "label", "seat", "doing")
    }
    types = {t: _ctype(cn, t) for t in TYPE_TABLES + ("doing", "watcher")}
    was = snap()
    assert not migrate.doing_818_needed(cn)
    second = migrate.ensure(cn)
    assert "migrate_818_doing.sql" not in second["applied"]
    assert migrate.apply_doing_818(cn) == []
    assert snap() == was
    assert {t: _ctype(cn, t) for t in TYPE_TABLES + ("doing", "watcher")} == types
    # run the file again by hand on a migrated book: nothing changes either.
    cur = cn.cursor()
    try:
        for stmt in migrate.split_script((migrate.sql_dir() / migrate.DOING_818).read_text(encoding="utf-8")):
            cur.execute(stmt)
        cn.commit()
    finally:
        cur.close()
    assert snap() == was
    assert {t: _ctype(cn, t) for t in TYPE_TABLES + ("doing", "watcher")} == types


def _col(cn, table: str, col: str) -> str:
    return str(scalar_done(
        cn,
        "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, col),
    ) or "")


def test_e_on_points_at_any_activity_but_doing(cn, migrated):
    """on_type is any activity type except doing itself; a narrower list converges."""
    want = "enum('mail','todo','hold','score')"
    assert _col(cn, "doing", "on_type") == want
    did = _desk_id(cn, "fx818-a")
    _x(cn, "INSERT INTO doing (desk_id, text, on_type, on_id) VALUES (%s, 'on a hold', 'hold', 1)", (did,))
    _x(cn, "INSERT INTO doing (desk_id, text, on_type, on_id) VALUES (%s, 'on a score', 'score', 1)", (did,))
    with pytest.raises(Exception):
        _x(cn, "INSERT INTO doing (desk_id, text, on_type, on_id) VALUES (%s, 'on itself', 'doing', 1)", (did,))
    cn.rollback()
    # A book migrated by an earlier build (mail/todo only) widens on the next ensure.
    _x(cn, "DELETE FROM doing WHERE on_type IN ('hold', 'score')")
    _x(cn, "INSERT INTO doing (desk_id, text, on_type, on_id) VALUES (%s, 'on a card', 'todo', 9)", (did,))
    _x(cn, "ALTER TABLE doing MODIFY on_type ENUM('mail','todo') NULL")
    cn.commit()
    assert migrate.doing_818_needed(cn)
    migrate.ensure(cn)
    assert _col(cn, "doing", "on_type") == want
    assert not migrate.doing_818_needed(cn)
    assert scalar_done(cn, "SELECT COUNT(*) FROM doing WHERE on_type = 'todo' AND on_id = 9") == 1


# ---- resumable: a run killed between any two statements converges on ensure ----

FKS_818 = ("fk_label_activity", "fk_tree_activity", "fk_mail_to_mail", "fk_seat_desk", "fk_doing_desk", "fk_doing_roster")


def _shape(cn) -> dict:
    """Everything the migration decides: lists, columns, keys, rows."""
    out: dict = {t: _ctype(cn, t) for t in TYPE_TABLES + ("doing", "watcher")}
    out["tables"] = (_has_table(cn, "join"), _has_table(cn, "seat"), _has_table(cn, "doing"))
    out["doing_cols"] = [tuple(r.values()) for r in rows_done(
        cn,
        "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' ORDER BY ORDINAL_POSITION")]
    out["keys"] = sorted(tuple(r.values()) for r in rows_done(
        cn,
        "SELECT TABLE_NAME, INDEX_NAME FROM information_schema.STATISTICS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN ('seat', 'doing') GROUP BY TABLE_NAME, INDEX_NAME"))
    out["fks"] = sorted(tuple(r.values()) for r in rows_done(
        cn,
        "SELECT TABLE_NAME, CONSTRAINT_NAME, DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS"
        " WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME IN (" + ",".join(["%s"] * len(FKS_818)) + ")",
        FKS_818))
    out["doing_rows"] = [tuple(r.values()) for r in rows_done(
        cn, "SELECT id, desk_id, roster_id, text, on_type, waiting_type FROM doing ORDER BY id")]
    out["seat_rows"] = [tuple(r.values()) for r in rows_done(
        cn, "SELECT id, desk_id, token_hash, delivery_mode, endpoint_url, endpoint_key, wake_on, lan_ip FROM seat ORDER BY id")]
    for t in ("activity", "watcher", "label"):
        out[t + "_rows"] = [tuple(r.values()) for r in rows_done(
            cn, f"SELECT type, id FROM `{t}` WHERE id IN (1, 7, 11, 12) ORDER BY type, id")]
    cur = cn.cursor()
    try:
        out["routines"] = migrate._routine_rows(cur)
    finally:
        cur.close()
    out["triggers"] = sorted(r["TRIGGER_NAME"] for r in rows_done(
        cn, "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()"))
    return out


def _helpers(cn) -> None:
    """Create the file's retype helper, as a killed run would have left it."""
    stmts = migrate.split_script((migrate.sql_dir() / migrate.DOING_818).read_text(encoding="utf-8"))
    body = [s for s in stmts if s.lstrip().upper().startswith("CREATE PROCEDURE MILL_MIGRATE_818_RETYPE")]
    assert len(body) == 1
    _x(cn, "DROP PROCEDURE IF EXISTS mill_migrate_818_retype")
    _x(cn, body[0])


ALL10 = ("activity", "label", "tree", "mail", "mail_to", "todo", "join", "hold", "score", "watcher")
SEAT_CREATE = next(
    s for s in migrate.split_script((migrate.sql_dir() / "tables.sql").read_text(encoding="utf-8"))
    if s.lstrip().startswith("CREATE TABLE IF NOT EXISTS seat")
)
SEAT_COPY = (
    "INSERT IGNORE INTO seat (id, desk_id, created, updated, token_hash, delivery_mode, endpoint_url,"
    " endpoint_key, wake_on, lan_ip, time_connect, time_disconnect)"
    " SELECT id, desk_id, created, updated, token_hash, delivery_mode, endpoint_url, endpoint_key,"
    " wake_on, lan_ip, time_connect, time_disconnect FROM `join`"
)
DROP_FKS = [
    "ALTER TABLE label DROP FOREIGN KEY fk_label_activity",
    "ALTER TABLE tree DROP FOREIGN KEY fk_tree_activity",
    "ALTER TABLE mail_to DROP FOREIGN KEY fk_mail_to_mail",
]
WIDEN = [f"CALL mill_migrate_818_retype('{t}', 'widen')" for t in ALL10]
MOVE = [f"UPDATE `{t}` SET type = 'doing' WHERE type = 'join'" for t in ALL10]
FINAL = [f"CALL mill_migrate_818_retype('{t}', 'final')" for t in ALL10]
ADD_FKS = [
    "ALTER TABLE label ADD CONSTRAINT fk_label_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE CASCADE",
    "ALTER TABLE tree ADD CONSTRAINT fk_tree_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT",
    "ALTER TABLE mail_to ADD CONSTRAINT fk_mail_to_mail FOREIGN KEY (type, id) REFERENCES mail (type, id) ON DELETE CASCADE",
]
RESHAPE_PREP = [
    "ALTER TABLE `join` DROP FOREIGN KEY fk_join_desk",
    "ALTER TABLE `join` DROP INDEX idx_desk",
    "ALTER TABLE `join` DROP INDEX idx_lan_updated",
    "ALTER TABLE `join` DROP INDEX idx_token_hash",
]
RESHAPE = (
    "ALTER TABLE `join` RENAME COLUMN doing TO text,"
    " ADD COLUMN roster_id BIGINT UNSIGNED NOT NULL DEFAULT 1 AFTER desk_id,"
    " ADD COLUMN on_type ENUM('mail','todo','hold','score') NULL AFTER text,"
    " ADD COLUMN on_id BIGINT UNSIGNED NULL AFTER on_type,"
    " ADD COLUMN waiting_type ENUM('mail','todo') NULL AFTER on_id,"
    " ADD COLUMN waiting_id BIGINT UNSIGNED NULL AFTER waiting_type,"
    " DROP COLUMN updated, DROP COLUMN token_hash, DROP COLUMN delivery_mode, DROP COLUMN endpoint_url,"
    " DROP COLUMN endpoint_key, DROP COLUMN wake_on, DROP COLUMN lan_ip, DROP COLUMN time_connect,"
    " DROP COLUMN time_disconnect,"
    " ADD KEY idx_desk_created (desk_id, created), ADD KEY idx_on (on_type, on_id),"
    " ADD CONSTRAINT fk_doing_desk FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT,"
    " ADD CONSTRAINT fk_doing_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"
)
# The file's statements in order. A cut at k means the run died after the first k.
STEPS = [SEAT_CREATE, SEAT_COPY, *DROP_FKS, *WIDEN, *MOVE, *FINAL, *ADD_FKS, *RESHAPE_PREP, RESHAPE]
# Every boundary inside each phase, plus mid-phase cuts.
CUTS = sorted({0, 1, 2, 3, 5, 6, 8, 15, 16, 20, 25, 26, 30, 35, 36, 38, 39, 40, 41, 43, 44, len(STEPS)})


def _fresh_old_book(cn) -> None:
    from agent_coord.server.records import apply

    apply(cn, wipe=True)
    migrate.ensure(cn)
    _old_book(cn)


def test_f_a_killed_run_converges_from_every_cut(cn):
    """Validator stage 1: kill between alters, run ensure again, same end state."""
    _fresh_old_book(cn)
    migrate.ensure(cn)
    want = _shape(cn)
    assert want["tables"] == (False, True, True)
    for cut in CUTS:
        _fresh_old_book(cn)
        _helpers(cn)
        _x(cn, "DROP TRIGGER IF EXISTS join_no_delete_in_tree")
        for stmt in STEPS[:cut]:
            _x(cn, stmt)
        cn.commit()
        assert migrate.doing_818_needed(cn), cut
        migrate.ensure(cn)
        assert not migrate.doing_818_needed(cn), cut
        got = _shape(cn)
        assert got == want, (cut, {k: (got[k], want[k]) for k in want if got[k] != want[k]})


def _run_file(cn) -> None:
    cur = cn.cursor()
    try:
        for stmt in migrate.split_script((migrate.sql_dir() / migrate.DOING_818).read_text(encoding="utf-8")):
            cur.execute(stmt)
        cn.commit()
    finally:
        cur.close()


def _reload_stmts() -> list[str]:
    out: list[str] = []
    for path in migrate.sql_apply_order():
        if path.stem.startswith("fn_") or path.stem.startswith("sp_"):
            out.extend(migrate.split_script(path.read_text(encoding="utf-8-sig")))
    return out


def test_g_a_run_killed_in_the_routine_reload_converges(cn):
    """2557 claim 6: killed after RENAME TABLE join TO doing, inside the routine
    reload. The book is flagged (sql_state not ok) and the next ensure reloads,
    so routine bodies equal a clean run's, with none missing."""
    _fresh_old_book(cn)
    migrate.ensure(cn)
    want = _shape(cn)
    assert migrate.sql_state(cn)["ok"] is True
    stmts = _reload_stmts()
    n = len(stmts)
    # None: the file finished, the reload never started. 0: functions dropped only.
    for cut in (None, 0, 1, n // 4, n // 2, n - 1):
        _fresh_old_book(cn)
        # The old pack's routine, as on the cloud book: names the old table.
        _x(cn, "DROP PROCEDURE IF EXISTS mill_floor_fp")
        _x(cn, "CREATE PROCEDURE mill_floor_fp() SELECT COUNT(*) FROM `join`")
        cn.commit()
        _run_file(cn)
        assert not _has_table(cn, "join") and not migrate.doing_818_needed(cn), cut
        if cut is not None:
            cur = cn.cursor()
            try:
                migrate._drop_functions(cur)
                for stmt in stmts[:cut]:
                    migrate._apply_stmt(cur, stmt)
                cn.commit()
            finally:
                cur.close()
        st = migrate.sql_state(cn)
        assert st["ok"] is False and st.get("routines"), (cut, st)
        migrate.ensure(cn)
        assert migrate.sql_state(cn)["ok"] is True, cut
        migrate.ensure(cn)  # and a further run changes nothing
        got = _shape(cn)
        assert got == want, (cut, {k: "differs" for k in want if got[k] != want[k]})
        assert scalar_done(cn, "SELECT COUNT(*) FROM information_schema.ROUTINES"
                               " WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_DEFINITION LIKE %s", ("%`join`%",)) == 0


def test_h_sql_state_flags_a_missing_or_changed_routine(cn):
    """A routine dropped or changed by hand after ensure is not this pack's SQL."""
    from agent_coord.server.records import apply

    apply(cn, wipe=True)
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    _x(cn, "DROP FUNCTION IF EXISTS MILL_SCORE_DOC_ADD")
    cn.commit()
    st = migrate.sql_state(cn)
    assert st["ok"] is False and "mill_score_doc_add" in st["routines"].lower()
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    _x(cn, "DROP PROCEDURE IF EXISTS mill_floor_scope_load")
    _x(cn, "CREATE PROCEDURE mill_floor_scope_load() SELECT 1")
    cn.commit()
    assert migrate.sql_state(cn)["ok"] is False
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True


def test_i_a_book_whose_routines_name_a_missing_definer_converges(cn):
    """A dump restored on another server keeps DEFINER = a user that is not
    there; calling the stamp then fails with 1449. ensure must read that as
    unstamped and reload, not crash before the reload."""
    from agent_coord.server.records import apply

    apply(cn, wipe=True)
    migrate.ensure(cn)
    gone = "`gone_818`@`localhost`"
    redefined = 0
    for r in rows_done(cn, "SELECT ROUTINE_TYPE AS t, ROUTINE_NAME AS n FROM information_schema.ROUTINES"
                           " WHERE ROUTINE_SCHEMA = DATABASE()"):
        rtype, name = r["t"], r["n"]
        ddl = rows_done(cn, f"SHOW CREATE {rtype} `{name}`")[0][f"Create {rtype.title()}"]
        rest = ddl.partition(f" {rtype} ")[2]
        try:
            _x(cn, f"DROP {rtype} `{name}`")
            _x(cn, f"CREATE DEFINER={gone} {rtype} {rest}")
        except Exception as e:  # no SET_USER_ID here: the case cannot be built
            if getattr(e, "errno", None) in (1227, 1044):
                pytest.skip("this server user cannot create routines for another definer")
            raise
        redefined += 1
    cn.commit()
    assert redefined > 2
    st = migrate.sql_state(cn)
    assert st["ok"] is False
    migrate.ensure(cn)
    assert migrate.sql_state(cn)["ok"] is True
    assert scalar_done(cn, "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()"
                           " AND DEFINER = 'gone_818@localhost'") == 0
