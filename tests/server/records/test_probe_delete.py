"""probe-delete (#160): own t-<8 hex> fixture rows go deleted live; nothing else moves."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import activity, apply, connect, floor, score, todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

FIX = "t-0a1b2c3d"
FIX2 = "t-0a1b2c3e"

class _Book:
    def __init__(self, cn):
        self._cn = cn

@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(
        c,
        ("pd_real", "roster"),
        (FIX, "roster"),
        (FIX2, "roster"),
        ("pd_me", "desk"),
        ("pd_other", "desk"),
    )
    yield c
    c.close()

def _probe(cn, owner: str, typ: str, rid) -> dict:
    return rpc.HANDLERS["probe-delete"](_Book(cn), {"type": typ, "id": rid}, "the-mill", owner)

def _card(cn, project: str, desk: str, need: str) -> int:
    return int(todo.insert(cn, project, desk, "open", todo.pack({"slug": need}))[0]["id"])

def _card_0630(cn, project: str, desk: str, need: str) -> int:
    """A card as the 0.6.30 delete saw it (0.8.0: no todo_event table; doing holds history)."""
    return _card(cn, project, desk, need)

def _score(cn, project: str, desk: str, kpi: str) -> int:
    return int(score.upsert(cn, project, desk, kpi, "1", "", "")[0]["id"])

def _gone(cn, typ: str, rid: int):
    return scalar(cn, "SELECT deleted FROM activity WHERE type=%s AND id=%s", (typ, rid))

def test_own_fixture_rows_go_deleted_everywhere(cn) -> None:
    tid = _card(cn, FIX, "pd_me", "pd-card")
    sid = _score(cn, FIX, "pd_me", "pd_kpi")
    out_t = _probe(cn, "pd_me", "todo", tid)
    out_s = _probe(cn, "pd_me", "score", str(sid))
    assert out_t["state"] == "deleted" and out_t["project"] == FIX and out_t["deleted"]
    assert out_s["state"] == "deleted" and out_s["project"] == FIX and out_s["deleted"]
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) is None
    # mill_activity_select (the /api/v1/events source and Wire stamp)
    desk_id = scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,))
    rows = activity.select(cn, desk_id=int(desk_id), limit=50)
    states = {(r["type"], int(r["id"])): r.get("state") for r in rows}
    assert states[("todo", tid)] == "deleted"
    assert states[("score", sid)] == "deleted"
    # mill_between lists each member desk's newest rows, whatever their project:
    # the desk's own fixture rows show under a real project it sits in.
    from agent_coord.server.records.db import call

    call(cn, "mill_member_put", ["roster", "pd_real", "pd_me"])
    btw = activity.between_rows(cn, "project", "pd_real", 50)
    bstates = {(r.get("type"), int(r.get("id") or 0)): r.get("state") for r in btw}
    assert bstates.get(("todo", tid)) == "deleted"
    assert bstates.get(("score", sid)) == "deleted"
    # /api/v1/events body
    ev = floor.v1_events(cn, project=FIX)
    estates = {(e.get("type"), int(e.get("id") or 0)): e.get("state") for e in ev.get("events") or []}
    assert estates.get(("todo", tid)) == "deleted"
    assert estates.get(("score", sid)) == "deleted"

def test_real_project_rows_refused_and_untouched(cn) -> None:
    tid = _card(cn, "pd_real", "pd_me", "pd-real-card")
    sid = _score(cn, "pd_real", "pd_me", "pd_real_kpi")
    for typ, rid in (("todo", tid), ("score", sid)):
        with pytest.raises(CoordError, match="not in a fixture project"):
            _probe(cn, "pd_me", typ, rid)
        assert _gone(cn, typ, rid) is None
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) == tid

def test_other_desk_fixture_rows_refused_and_untouched(cn) -> None:
    tid = _card(cn, FIX2, "pd_other", "pd-other-card")
    sid = _score(cn, FIX2, "pd_other", "pd_other_kpi")
    for typ, rid in (("todo", tid), ("score", sid)):
        with pytest.raises(CoordError, match="not made by this desk"):
            _probe(cn, "pd_me", typ, rid)
        assert _gone(cn, typ, rid) is None

def test_todo_delete_restamps_when_activity_row_is_removed(cn) -> None:
    """#185: if the card delete also drops the activity row, the stamp is put back."""
    tid = _card(cn, FIX, "pd_me", "pd-restamp")
    cur = cn.cursor()
    try:
        cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity")
        cur.execute(
            "CREATE TRIGGER todo_del_drop_activity AFTER DELETE ON todo "
            "FOR EACH ROW DELETE FROM activity WHERE type = 'todo' AND id = OLD.id"
        )
        cn.commit()
    finally:
        cur.close()
    try:
        out = _probe(cn, "pd_me", "todo", tid)
        assert out["state"] == "deleted" and out["deleted"]
        assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) is None
        assert _gone(cn, "todo", tid) is not None
    finally:
        cur = cn.cursor()
        try:
            cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity")
            cn.commit()
        finally:
            cur.close()

def test_probe_delete_hints_state_deleted(cn) -> None:
    """#185: a probe-delete hint detail carries state deleted for the watcher."""
    import json

    tid = _card(cn, FIX, "pd_me", "pd-hint")
    desk_id = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", ("pd_me",)))
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted"
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT payload FROM push_queue WHERE desk_id=%s AND kind='hint' ORDER BY id DESC",
            (desk_id,),
        )
        blobs = [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
    found = False
    for raw in blobs:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        if int(payload.get("id") or 0) != tid:
            continue
        detail = payload.get("detail")
        if isinstance(detail, str):
            detail = json.loads(detail)
        if (detail or {}).get("state") == "deleted":
            found = True
    assert found

def test_second_delete_and_missing_rows_refused(cn) -> None:
    tid = _card(cn, FIX, "pd_me", "pd-twice")
    sid = _score(cn, FIX, "pd_me", "pd_twice_kpi")
    _probe(cn, "pd_me", "todo", tid)
    _probe(cn, "pd_me", "score", sid)
    with pytest.raises(CoordError, match="already deleted"):
        _probe(cn, "pd_me", "todo", tid)
    with pytest.raises(CoordError, match="already deleted"):
        _probe(cn, "pd_me", "score", sid)
    with pytest.raises(CoordError, match="no such todo"):
        _probe(cn, "pd_me", "todo", 987654321)

def _deleted_hints(cn, typ: str, rid: int) -> int:
    import json

    cur = cn.cursor()
    try:
        cur.execute("SELECT payload FROM push_queue WHERE kind='hint'")
        blobs = [r[0] for r in cur.fetchall()]
    finally:
        cur.close()
    n = 0
    for raw in blobs:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode()
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        if str(payload.get("type") or "") != typ or int(payload.get("id") or 0) != rid:
            continue
        detail = payload.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception:
                detail = {}
        if isinstance(detail, dict) and detail.get("state") == "deleted":
            n += 1
    return n

def _assert_deleted(cn, typ: str, rid: int) -> None:
    """state=deleted in the three reads, and exactly one deleted hint."""
    from agent_coord.server.records.db import call

    call(cn, "mill_member_put", ["roster", "pd_real", "pd_me"])
    if typ == "todo":
        assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (rid,)) is None
    desk_id = scalar(cn, "SELECT desk_id FROM activity WHERE type=%s AND id=%s", (typ, rid))
    assert desk_id is not None
    rows = activity.select(cn, desk_id=int(desk_id), limit=100)
    states = {(r["type"], int(r["id"])): r.get("state") for r in rows}
    assert states[(typ, rid)] == "deleted"
    btw = activity.between_rows(cn, "project", "pd_real", 100)
    bstates = {(r.get("type"), int(r.get("id") or 0)): r.get("state") for r in btw}
    assert bstates.get((typ, rid)) == "deleted"
    ev = floor.v1_events(cn, project=FIX)
    estates = {(e.get("type"), int(e.get("id") or 0)): e.get("state") for e in ev.get("events") or []}
    assert estates.get((typ, rid)) == "deleted"
    assert _deleted_hints(cn, typ, rid) == 1

def _drop_activity(cn, tid: int) -> None:
    cur = cn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("DELETE FROM activity WHERE type = 'todo' AND id = %s", (tid,))
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cn.commit()
    finally:
        cur.close()

def test_todo_with_no_activity_row_is_stamped(cn) -> None:
    """#185: a card whose activity row is already gone still ends state=deleted."""
    tid = _card(cn, FIX, "pd_me", "pd-no-activity")
    _drop_activity(cn, tid)
    assert scalar(cn, "SELECT id FROM activity WHERE type='todo' AND id=%s", (tid,)) is None
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted" and out["deleted"]
    _assert_deleted(cn, "todo", tid)

def test_claim_note_pass_history_is_one_activity_row(cn) -> None:
    """#185: activity's key is (type, id), so claim, note, and pass keep one row (no n column)."""
    tid = _card(cn, FIX, "pd_me", "pd-history")
    todo.update(cn, tid, "pd_me", status="claimed", volunteer="pd_me")
    rpc._h_note(_Book(cn), {"need": "pd-history", "note": "noted"}, FIX, "pd_me")
    todo.update(cn, tid, "pd_me", status="shipped")
    todo.update(cn, tid, "pd_me", status="done")
    assert scalar(cn, "SELECT status FROM todo WHERE id=%s", (tid,)) == "done"
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (tid,)) == 1
    assert scalar(cn, "SELECT act FROM activity WHERE type='todo' AND id=%s", (tid,)) is not None
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted"
    _assert_deleted(cn, "todo", tid)
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='todo' AND id=%s", (tid,)) == 1

def test_second_delete_keeps_the_first_stamp_and_one_hint(cn) -> None:
    """#185: a second delete does not move the stamp and does not emit another hint."""
    from agent_coord.helpers.ident import iso6
    from agent_coord.server.records.db import call

    tid = _card(cn, FIX, "pd_me", "pd-second-stamp")
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted"
    _assert_deleted(cn, "todo", tid)
    first = scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,))
    assert iso6(first) == out["deleted"]
    with pytest.raises(CoordError, match="already deleted"):
        _probe(cn, "pd_me", "todo", tid)
    call(cn, "mill_todo_delete", [tid, "pd_me"])
    again = scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,))
    assert again == first
    assert _deleted_hints(cn, "todo", tid) == 1

def test_delete_while_hold_and_watcher_point_at_it(cn) -> None:
    """#185: a watcher on the card and a hold in the project do not block the stamp."""
    from agent_coord.server.records import hold

    tid = _card(cn, FIX, "pd_me", "pd-held")
    watched = scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='todo' AND id=%s", (tid,))
    assert int(watched or 0) >= 1
    hid = int(hold.upsert(cn, FIX, "pd_me", "pdlock")[0]["id"])
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted"
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='todo' AND id=%s", (tid,)) == 0
    assert scalar(cn, "SELECT id FROM hold WHERE id=%s", (hid,)) == hid
    _assert_deleted(cn, "todo", tid)

def test_delete_on_a_tree_keeps_the_parent(cn) -> None:
    """#185: the parent card and its tree row stay; the deleted card is gone and stamped."""
    from agent_coord.server.records import tree as rec_tree

    root = _card(cn, FIX, "pd_me", "pd-tree-root")
    tid = _card(cn, FIX, "pd_me", "pd-tree-card")
    kid = _card(cn, FIX, "pd_me", "pd-tree-kid")
    rec_tree.create(cn, "pd_plan", "todo", root)
    rec_tree.add(cn, "todo", root, "todo", tid, tree="pd_plan")
    rec_tree.add(cn, "todo", tid, "todo", kid, tree="pd_plan")
    out = _probe(cn, "pd_me", "todo", tid)
    assert out["state"] == "deleted"
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (root,)) == root
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (kid,)) == kid
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (root,)) == 1
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (tid,)) == 0
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (kid,)) == 1
    _assert_deleted(cn, "todo", tid)

def test_score_delete_next_to_todo_delete(cn) -> None:
    """#185: a score delete and a todo delete in one project both end state=deleted."""
    tid = _card(cn, FIX, "pd_me", "pd-beside")
    sid = _score(cn, FIX, "pd_me", "pd_beside_kpi")
    out_t = _probe(cn, "pd_me", "todo", tid)
    out_s = _probe(cn, "pd_me", "score", sid)
    assert out_t["state"] == "deleted" and out_s["state"] == "deleted"
    _assert_deleted(cn, "todo", tid)
    _assert_deleted(cn, "score", sid)

def test_detail_column_counts_characters(cn) -> None:
    """#188/#292: VARCHAR and the 4096 cap count characters. 500 e-acute is 1000 bytes."""
    import json

    text = "é" * 500
    rec = rpc._h_open(_Book(cn), {"need": "pd-mb", "detail": text}, FIX, "pd_me")
    body = scalar(cn, "SELECT body FROM todo WHERE id=%s", (rec["id"],))
    if isinstance(body, (bytes, bytearray)):
        body = body.decode()
    assert json.loads(body)["detail"] == text
    assert int(scalar(cn, "SELECT CHAR_LENGTH(%s)", (text,)) or 0) == 500
    assert int(scalar(cn, "SELECT LENGTH(%s)", (text,)) or 0) == 1000
    with pytest.raises(CoordError, match="max 4096"):
        rpc._h_open(_Book(cn), {"need": "pd-mb-over", "detail": "é" * 4097}, FIX, "pd_me")
    assert todo.find(cn, FIX, "pd-mb-over") is None
    empty = rpc._h_open(_Book(cn), {"need": "pd-empty", "detail": ""}, FIX, "pd_me")
    assert empty["detail"] == ""

def test_probe_tool_run_exits_0(cn, capsys) -> None:
    """#185: tools/probe_deleted_rows.py run exits 0 when both rows stamp deleted."""
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "probe_deleted_rows_edge", root / "tools" / "probe_deleted_rows.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def call(body):
        command = body["verb"]
        project = str(body.get("project") or FIX)
        result = rpc.HANDLERS[command](_Book(cn), body, project, "pd_me")
        return {"ok": True, "result": result}

    assert mod.main(["run", "--project", FIX], call=call) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["trail_state"] == "deleted"

# Installed on the live office as 0.6.30 (f7a7058). Comments omitted; the statements match.
_OLD_0630_DELETE = """
CREATE PROCEDURE mill_todo_delete(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_gone INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  START TRANSACTION;
  SET v_ts = MILL_NOW();
  IF EXISTS (SELECT 1 FROM todo WHERE id = p_id) THEN
    CALL mill_tree_detach('todo', p_id);
  END IF;
  DELETE FROM todo WHERE id = p_id;
  SET v_gone = ROW_COUNT();
  IF v_gone = 1 THEN
    DELETE FROM watcher WHERE type = 'todo' AND id = p_id;
    UPDATE activity SET deleted = v_ts, updated = v_ts
     WHERE type = 'todo' AND id = p_id;
  END IF;
  COMMIT;
  SELECT p_id AS id, 'deleted' AS op;
END
"""

def _install_proc(cn, create_sql: str) -> None:
    from agent_coord.install.migrate import split_script

    blob = (
        "DROP PROCEDURE IF EXISTS mill_todo_delete;\nDELIMITER //\n"
        + create_sql.strip()
        + "\n//\nDELIMITER ;\n"
    )
    cur = cn.cursor()
    try:
        for stmt in split_script(blob):
            cur.execute(stmt)
        cn.commit()
    finally:
        cur.close()

def _proc_from_source() -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    text = (root / "agent_coord" / "server" / "sql" / "sp_todo.sql").read_text(encoding="utf-8")
    mark = "CREATE PROCEDURE mill_todo_delete("
    start = text.index(mark)
    end = text.index("\nEND //", start)
    return text[start:end] + "\nEND"

def _open_db(name: str):
    import mysql.connector

    prev = os.environ.get("AGENT_COORD_DATABASE")
    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{name}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = name
    cn = connect(name)
    apply(cn, wipe=True)
    if prev is None:
        os.environ.pop("AGENT_COORD_DATABASE", None)
    else:
        os.environ["AGENT_COORD_DATABASE"] = prev
    return cn

@pytest.fixture(scope="module")
def aws_cn():
    """Throwaway copy. Not the live cloud or lan book."""
    try:
        c = _open_db(throwaway_db("mill_probe_aws"))
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("pd_real", "roster"), (FIX, "roster"), ("pd_me", "desk"))
    yield c
    c.close()

def test_aws_0630_procedure_replay_explains_unchanged(aws_cn) -> None:
    """#185: why the live office probe-delete returned state unchanged.

    The wall routes do not return SHOW CREATE PROCEDURE. mill_floor_fp
    fingerprints mail and trees, not routines. This replays the 0.6.30
    procedure (the pack installed on the live office) on a throwaway. A clean card
    stamps. A card with no activity row does not. A trigger that drops the
    activity row inside the delete does not. The branch procedure stamps both.
    """
    cn = aws_cn
    _install_proc(cn, _OLD_0630_DELETE)
    clean = _card_0630(cn, FIX, "pd_me", "aws-clean")
    _probe(cn, "pd_me", "todo", clean)
    assert _gone(cn, "todo", clean) is not None

    missing = _card_0630(cn, FIX, "pd_me", "aws-missing")
    _drop_activity(cn, missing)
    out = _probe(cn, "pd_me", "todo", missing)
    assert out["state"] == "unchanged"
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (missing,)) is None
    assert scalar(cn, "SELECT id FROM activity WHERE type='todo' AND id=%s", (missing,)) is None

    tripped = _card_0630(cn, FIX, "pd_me", "aws-trigger")
    cur = cn.cursor()
    try:
        cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity_aws")
        cur.execute(
            "CREATE TRIGGER todo_del_drop_activity_aws AFTER DELETE ON todo "
            "FOR EACH ROW DELETE FROM activity WHERE type = 'todo' AND id = OLD.id"
        )
        cn.commit()
    finally:
        cur.close()
    try:
        out = _probe(cn, "pd_me", "todo", tripped)
        assert out["state"] == "unchanged"
        assert scalar(cn, "SELECT id FROM activity WHERE type='todo' AND id=%s", (tripped,)) is None
    finally:
        cur = cn.cursor()
        try:
            cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity_aws")
            cn.commit()
        finally:
            cur.close()

    _install_proc(cn, _proc_from_source())
    missing2 = _card(cn, FIX, "pd_me", "aws-missing-new")
    _drop_activity(cn, missing2)
    out = _probe(cn, "pd_me", "todo", missing2)
    assert out["state"] == "deleted"
    _assert_deleted(cn, "todo", missing2)

    tripped2 = _card(cn, FIX, "pd_me", "aws-trigger-new")
    cur = cn.cursor()
    try:
        cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity_aws")
        cur.execute(
            "CREATE TRIGGER todo_del_drop_activity_aws AFTER DELETE ON todo "
            "FOR EACH ROW DELETE FROM activity WHERE type = 'todo' AND id = OLD.id"
        )
        cn.commit()
    finally:
        cur.close()
    try:
        out = _probe(cn, "pd_me", "todo", tripped2)
        assert out["state"] == "deleted"
        _assert_deleted(cn, "todo", tripped2)
    finally:
        cur = cn.cursor()
        try:
            cur.execute("DROP TRIGGER IF EXISTS todo_del_drop_activity_aws")
            cn.commit()
        finally:
            cur.close()

@pytest.mark.parametrize(
    "body",
    [
        {"type": "mail", "id": 1},
        {"type": "hold", "id": 1},
        {"type": "todo", "id": 0},
        {"type": "todo", "id": "x"},
        {"type": "score"},
    ],
)
def test_bad_target_refused(cn, body) -> None:
    with pytest.raises(CoordError, match="probe-delete: (type|id)"):
        rpc.HANDLERS["probe-delete"](_Book(cn), body, "the-mill", "pd_me")
