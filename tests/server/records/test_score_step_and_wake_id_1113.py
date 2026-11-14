"""Card 1113 (audit defects 1-3, 14, 15): no swallowed deadlock, no duplicate wake id, no leaked lock.

Every call goes straight to the procedure on its own session (no call() retry). A gate session
forces the interleaving: it holds the contended row, the worker queues behind it, then the gate
asks for the worker's row (deadlock) or commits.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import _run_proc
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names


def _direct():
    import mysql.connector

    kw = dict(_conn_kwargs())
    kw["database"] = sql_book.shared_db_name()
    c = mysql.connector.connect(**kw)
    c.autocommit = False
    cur = c.cursor()
    cur.execute("SET SESSION innodb_lock_wait_timeout = 8")
    cur.close()
    return c


@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("unit", "roster"), ("a", "desk"), ("b", "desk"))
    yield c
    cur = c.cursor()
    cur.execute("DROP TABLE IF EXISTS gate_ballast_1113")
    cur.close()
    c.commit()
    c.close()


def _q(c, sql: str, args: tuple = ()) -> list[tuple]:
    cur = c.cursor()
    cur.execute(sql, args)
    rows = cur.fetchall() if cur.with_rows else []
    cur.close()
    return rows


def _call(c, name: str, args: list) -> list[dict]:
    cur = c.cursor()
    try:
        return _run_proc(cur, name, args)
    finally:
        cur.close()


def _id(c, typ: str, name: str) -> int:
    return int(_q(c, "SELECT id FROM name WHERE type = %s AND name = %s", (typ, name))[0][0])


def _push(c, desk: str, payload: dict, outcome: str = "queued") -> int:
    rows = _call(c, "mill_push_put", [desk, "hint", json.dumps(payload), outcome])
    return int(rows[0]["id"])


def test_a_deadlock_in_the_claim_score_step_fails_the_claim(cn) -> None:
    # The score step's CONTINUE HANDLER FOR SQLEXCEPTION caught 1213 after InnoDB had rolled the
    # claim back; cmd_claim then returned 'claimed' with the card still open.
    rid = _id(cn, "roster", "unit")
    desk = _id(cn, "desk", "b")
    _call(cn, "mill_card_score_event", [rid, desk, "doing", None, None, None, 1, None])
    cn.commit()
    _q(cn, "CREATE TABLE IF NOT EXISTS gate_ballast_1113 (id INT AUTO_INCREMENT PRIMARY KEY, v INT) ENGINE=InnoDB")
    cn.commit()
    outcomes = []
    for k in range(3):
        card = int(rec_todo.insert(cn, "unit", "a", "open", json.dumps({"need_id": f"swallow-{k}"}))[0]["id"])
        cn.commit()
        gate = _direct()
        # More undo than the claim, so InnoDB rolls the claim back as the deadlock victim.
        _q(gate, "INSERT INTO gate_ballast_1113 (v) SELECT 1 FROM information_schema.columns LIMIT 3000")
        _q(gate, "SELECT id FROM score WHERE desk_id = %s AND kpi = 'cards' FOR UPDATE", (desk,))
        out: dict = {}

        def claim(card=card, out=out) -> None:
            c = _direct()
            try:
                out["rows"] = _call(c, "cmd_claim", [desk, card, 0, None, None])
                c.commit()
                out["ok"] = True
            except Exception as e:  # noqa: BLE001
                out["err"] = getattr(e, "errno", None)
                c.rollback()
            finally:
                c.close()

        th = threading.Thread(target=claim)
        th.start()
        time.sleep(1.5)
        try:
            _q(gate, "SELECT id FROM todo WHERE id = %s FOR UPDATE", (card,))
        finally:
            gate.rollback()
            gate.close()
        th.join(30)
        status = _q(cn, "SELECT status FROM todo WHERE id = %s", (card,))[0][0]
        cn.commit()
        outcomes.append((out.get("ok", False), out.get("err"), status))
    for ok, err, status in outcomes:
        # Either the claim reports the failure, or it really happened. Never 'claimed' and open.
        assert (not ok and err in (1213, 1205)) or (ok and status == "claimed"), outcomes
    assert any(err == 1213 for _ok, err, _s in outcomes), outcomes


def test_a_put_waiting_on_an_open_put_gets_its_own_wake_id(cn) -> None:
    # MAX(id) + 1 under a named lock released before commit: the second put saw the same MAX.
    a = _direct()
    _push(a, "a", {"id": 1})  # not committed yet
    out: list = []

    def second() -> None:
        c = _direct()
        try:
            out.append(("ok", _push(c, "b", {"id": 2})))
            c.commit()
        except Exception as e:  # noqa: BLE001
            out.append(("err", getattr(e, "errno", None)))
            c.rollback()
        finally:
            c.close()

    th = threading.Thread(target=second)
    th.start()
    time.sleep(1.0)
    a.commit()
    a.close()
    th.join(30)
    assert out and out[0][0] == "ok", out


def test_a_put_from_an_older_snapshot_gets_its_own_wake_id(cn) -> None:
    b = _direct()
    _q(b, "SELECT COUNT(*) FROM activity")  # b's snapshot starts (as in a request transaction)
    a = _direct()
    first = _push(a, "a", {"id": 3})
    a.commit()
    a.close()
    try:
        second = _push(b, "b", {"id": 4})
        b.commit()
    finally:
        b.close()
    assert second != first


def test_a_failed_put_leaves_no_lock_behind(cn) -> None:
    # An error after GET_LOCK('mill_wake_alloc') skipped RELEASE_LOCK: the pooled session kept it,
    # and every later put waited 10 s and failed.
    a = _direct()
    with pytest.raises(Exception):
        _push(a, "no-such-desk-1113", {"id": 5})
    with pytest.raises(Exception):
        _call(a, "mill_push_put", ["a", "hint", json.dumps({"id": 6, "route": "r" * 40}), "queued"])
    a.rollback()
    # A wake row planted at the next id (on main, MAX(id) + 1 then collided inside the locked step).
    top = int(_q(a, "SELECT IFNULL(MAX(id), 0) FROM activity WHERE type = 'wake'")[0][0])
    _q(a, "SET FOREIGN_KEY_CHECKS = 0")
    _q(a, "INSERT INTO wake (id, type, desk_id, cause, state, payload)"
          " VALUES (%s, 'wake', %s, 'hint', 'queued', '{}')", (top + 1, _id(a, "desk", "a")))
    _q(a, "SET FOREIGN_KEY_CHECKS = 1")
    a.commit()
    try:
        try:
            _push(a, "a", {"id": 7})
        except Exception:  # noqa: BLE001
            pass
        a.rollback()
        b = _direct()
        try:
            assert _q(b, "SELECT IS_USED_LOCK('mill_wake_alloc')")[0][0] is None
            t0 = time.monotonic()
            _push(b, "b", {"id": 8})
            b.commit()
            assert time.monotonic() - t0 < 3
        finally:
            b.close()
    finally:
        _q(a, "SET FOREIGN_KEY_CHECKS = 0")
        _q(a, "DELETE FROM wake WHERE id = %s AND payload = CAST('{}' AS JSON)", (top + 1,))
        _q(a, "SET FOREIGN_KEY_CHECKS = 1")
        a.commit()
        a.close()


def test_a_null_payload_id_is_no_id(cn) -> None:
    # CAST('null' AS UNSIGNED) raised 1292 under strict mode and the wake was not stored.
    c = _direct()
    try:
        wid = _push(c, "a", {"id": None, "type": "todo"})
        c.commit()
        payload = json.loads(_q(c, "SELECT payload FROM wake WHERE type = 'wake' AND id = %s", (wid,))[0][0])
    finally:
        c.close()
    assert "id" not in payload


def test_a_route_over_32_characters_is_refused_not_cut(cn) -> None:
    c = _direct()
    try:
        with pytest.raises(Exception, match="route"):
            _push(c, "a", {"id": 9, "route": "r" * 33})
        c.rollback()
        wid = _push(c, "a", {"id": 10, "route": "r" * 32})
        c.commit()
        assert _q(c, "SELECT route FROM wake WHERE type = 'wake' AND id = %s", (wid,))[0][0] == "r" * 32
    finally:
        c.close()


def test_doing_text_over_512_characters_is_refused_not_cut(cn) -> None:
    c = _direct()
    try:
        with pytest.raises(Exception):
            _q(c, "CALL mill_doing_insert(%s, 1, %s, NOW(6), @mill_t1113)", (_id(c, "desk", "a"), "x" * 513))
        c.rollback()
    finally:
        c.close()


def test_migrate_makes_wake_ids_auto_increment_past_every_wake_id(cn) -> None:
    from agent_coord.install.migrate import _ensure_wake_auto_id

    c = _direct()
    try:
        _push(c, "a", {"id": 11})
        c.commit()
        # A book from before card 1113: no AUTO_INCREMENT, the activity FK, and an activity row whose wake
        # row rollup deleted (its id must not come back).
        _q(c, "ALTER TABLE wake MODIFY id BIGINT UNSIGNED NOT NULL")
        _q(c, "ALTER TABLE wake ADD CONSTRAINT fk_wake_activity FOREIGN KEY (type, id)"
              " REFERENCES activity (type, id) ON DELETE RESTRICT")
        top = int(_q(c, "SELECT MAX(id) FROM activity WHERE type = 'wake'")[0][0]) + 5
        _q(c, "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('wake', %s, 0, 1, 'ring')", (top,))
        c.commit()
        assert _ensure_wake_auto_id(c) == ["wake_drop_fk_activity", "wake_auto_id"]
        assert _ensure_wake_auto_id(c) == []
        assert _push(c, "a", {"id": 12}) > top
        c.commit()
    finally:
        c.close()
