"""Label order for 0.6.33: #196 schema, #197 put, #198 --ord, #199 trail --label."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.install import migrate
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records import tree as rec_tree
from agent_coord.server.records.db import conn_kwargs
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _cur(cn):
    cur = cn.cursor()
    return cur


def _indexes(cn) -> set[str]:
    cur = _cur(cn)
    cur.execute(
        "SELECT INDEX_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label'"
    )
    names = {str(r[0]) for r in cur.fetchall()}
    cur.close()
    return names


def _column(cn, name: str):
    cur = _cur(cn)
    cur.execute(
        "SELECT COLUMN_TYPE, COLUMN_DEFAULT, IS_NULLABLE, ORDINAL_POSITION "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label' AND COLUMN_NAME = %s",
        (name,),
    )
    row = cur.fetchone()
    cur.close()
    return row


def _ord(cn, typ: str, nid: int, label: str) -> int:
    hit = [r for r in rec_label.select(cn, typ, nid) if str(r.get("label") or "") == label]
    assert len(hit) == 1
    return int(hit[0]["ord"])


def _count(cn, typ: str, nid: int) -> int:
    cur = _cur(cn)
    cur.execute("SELECT COUNT(*) FROM label WHERE type=%s AND id=%s", (typ, nid))
    n = int(cur.fetchone()[0])
    cur.close()
    return n


def _routine(cn, name: str) -> str:
    cur = _cur(cn)
    cur.execute(
        "SELECT ROUTINE_DEFINITION FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME = %s",
        (name,),
    )
    row = cur.fetchone()
    cur.close()
    return "" if not row or row[0] is None else str(row[0])


def _exec(cn, sql: str, args: tuple = ()) -> None:
    cur = _cur(cn)
    cur.execute(sql, args)
    cn.commit()
    cur.close()


def test_fresh_book_never_has_idx_name(cn) -> None:
    names = _indexes(cn)
    assert "idx_name" not in names
    assert "idx_label_ord" in names
    col = _column(cn, "ord")
    assert col is not None
    kind = str(col[0]).lower()
    assert "smallint" in kind and "unsigned" in kind
    assert str(col[1]) == "65535"
    assert str(col[2]).upper() == "NO"
    # 0.8.0: name_kind sits between name_id and ord
    kind_pos = int(_column(cn, "name_kind")[3])
    assert int(col[3]) == kind_pos + 1



def test_ord_sort_pin_and_created_tie(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("pin", "label"), ("early", "label"), ("late", "label"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "sorted")[0]["id"])
    rec_label.put(cn, "todo", tid, "late", 5)
    rec_label.put(cn, "todo", tid, "early", 5)
    rec_label.put(cn, "todo", tid, "pin", 0)
    _exec(
        cn,
        "UPDATE label l JOIN name n ON n.id = l.name_id "
        "SET l.created = '2026-01-02 00:00:00.000000' "
        "WHERE l.type = 'todo' AND l.id = %s AND n.name = 'late'",
        (tid,),
    )
    _exec(
        cn,
        "UPDATE label l JOIN name n ON n.id = l.name_id "
        "SET l.created = '2026-01-01 00:00:00.000000' "
        "WHERE l.type = 'todo' AND l.id = %s AND n.name = 'early'",
        (tid,),
    )
    _exec(
        cn,
        "UPDATE label l JOIN name n ON n.id = l.name_id "
        "SET l.created = '2026-06-01 00:00:00.000000' "
        "WHERE l.type = 'todo' AND l.id = %s AND n.name = 'pin'",
        (tid,),
    )
    names = [str(r.get("label") or "") for r in rec_label.select(cn, "todo", tid)]
    assert names == ["pin", "early", "late"]
    assert [int(r["ord"]) for r in rec_label.select(cn, "todo", tid)] == [0, 5, 5]


def test_ord_refused_on_the_server(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("bug", "label"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "bounds")[0]["id"])
    book = _Book(cn)
    for bad in (65536, -1, "nope"):
        with pytest.raises(CoordError, match="65535"):
            rpc._h_label(
                book,
                {"verb": "label-add", "type": "todo", "id": tid, "label": "bug", "ord": bad},
                "unit",
                "a",
            )
    assert _count(cn, "todo", tid) == 0


def test_add_without_ord_keeps_and_moves(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("move-me", "label"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "mover")[0]["id"])
    book = _Book(cn)
    body = {"verb": "label-add", "type": "todo", "id": tid, "label": "move-me"}
    rpc._h_label(book, body, "unit", "a")
    assert _ord(cn, "todo", tid, "move-me") == 65535
    rpc._h_label(book, body, "unit", "a")
    assert _ord(cn, "todo", tid, "move-me") == 65535
    assert _count(cn, "todo", tid) == 1
    rpc._h_label(book, {**body, "ord": 0}, "unit", "a")
    assert _ord(cn, "todo", tid, "move-me") == 0
    rpc._h_label(book, body, "unit", "a")
    assert _ord(cn, "todo", tid, "move-me") == 0
    assert _count(cn, "todo", tid) == 1
    rpc._h_label(book, {**body, "ord": 7}, "unit", "a")
    assert _ord(cn, "todo", tid, "move-me") == 7
    assert _count(cn, "todo", tid) == 1


def test_high_trust_label_created_on_first_use(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "first-use")[0]["id"])
    rpc._h_label(_Book(cn), {"verb": "label-add", "type": "todo", "id": tid, "label": "fresh-lab"}, "unit", "a")
    assert rec_name.get(cn, "fresh-lab", "label") is not None
    assert _count(cn, "todo", tid) == 1


def test_unknown_name_and_colon_round_trip(cn, monkeypatch) -> None:
    # 0.7.x: high trust creates a label on first use; limited still refuses.
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("rule:cards", "label"))
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "colon")[0]["id"])
    book = _Book(cn)
    with pytest.raises(CoordError, match=r"mill create label missing-lab"):
        rpc._h_label(
            book,
            {"verb": "label-add", "type": "todo", "id": tid, "label": "missing-lab"},
            "unit",
            "a",
        )
    assert rec_name.get(cn, "missing-lab", "label") is None
    assert _count(cn, "todo", tid) == 0
    rpc._h_label(
        book,
        {"verb": "label-add", "type": "todo", "id": tid, "label": "rule:cards", "ord": 2},
        "unit",
        "a",
    )
    assert _ord(cn, "todo", tid, "rule:cards") == 2
    gone = rpc._h_label(
        book,
        {"verb": "label-remove", "type": "todo", "id": tid, "label": "rule:cards"},
        "unit",
        "a",
    )
    assert gone[0]["op"] == "removed"
    assert _count(cn, "todo", tid) == 0


def test_trail_label_order_access_deleted_and_bound(cn, monkeypatch) -> None:
    seed_names(
        cn,
        ("unit", "roster"),
        ("a", "desk"),
        ("b", "desk"),
        ("c", "desk"),
        ("d", "desk"),
        ("pack", "label"),
    )
    book = _Book(cn)
    early = int(rec_todo.insert(cn, "unit", "a", "open", "first card")[0]["id"])
    late = int(rec_todo.insert(cn, "unit", "a", "open", "last card " + ("x" * 400))[0]["id"])
    rec_label.put(cn, "todo", early, "pack", 0)
    rec_label.put(cn, "todo", late, "pack", 65535)
    secret = int(rec_mail.insert(cn, "unit", "a", "b", "private letter")[0]["id"])
    room = int(rec_mail.insert(cn, "unit", "a", "b", "room letter")[0]["id"])
    other = int(rec_mail.insert(cn, "unit", "a", "d", "room side")[0]["id"])
    rec_tree.create(cn, "room-lab", "mail", room)
    rec_tree.add(cn, "mail", room, "mail", other, "room-lab")
    rec_label.put(cn, "mail", secret, "pack", 4)
    rec_label.put(cn, "mail", room, "pack", 4)
    _exec(
        cn,
        "UPDATE label l JOIN name n ON n.id = l.name_id "
        "SET l.created = '2026-03-01 00:00:00.000000' "
        "WHERE n.name = 'pack' AND l.type = 'mail' AND l.id = %s",
        (secret,),
    )
    _exec(
        cn,
        "UPDATE label l JOIN name n ON n.id = l.name_id "
        "SET l.created = '2026-03-02 00:00:00.000000' "
        "WHERE n.name = 'pack' AND l.type = 'mail' AND l.id = %s",
        (room,),
    )

    def _ids(desk: str) -> list[tuple[str, int]]:
        got = rpc._h_trail(book, {"label": "pack"}, "unit", desk)
        assert got["hint"] == ""
        return [(str(r["type"]), int(r["id"])) for r in got["rows"]]

    # #672 S-3: every desk in the office reads every labelled letter, on it or not.
    for desk in ("a", "b", "c", "d"):
        assert ("mail", secret) in _ids(desk), desk
        assert ("mail", room) in _ids(desk), desk
    sender = rpc._h_trail(book, {"label": "pack"}, "unit", "a")
    assert [(r["type"], r["id"]) for r in sender["rows"]] == [
        ("todo", early),
        ("mail", secret),
        ("mail", room),
        ("todo", late),
    ]
    assert [r["ord"] for r in sender["rows"]] == [0, 4, 4, 65535]
    assert sender["rows"][0]["need"] == "first card"
    assert sender["rows"][-1]["need"].endswith("...")
    assert len(sender["rows"][-1]["need"]) <= 120

    _exec(cn, "UPDATE activity SET deleted = CURRENT_TIMESTAMP(6) WHERE type='todo' AND id=%s", (early,))
    after = _ids("a")
    assert ("todo", early) not in after

    rec_member.put_admin(cn, "c")
    admin_ids = _ids("c")
    assert ("mail", secret) in admin_ids
    assert ("mail", room) in admin_ids

    empty = rpc._h_trail(book, {"label": "no-such-pack"}, "unit", "a")
    assert empty["rows"] == []
    assert "no-such-pack" in empty["hint"]
    # #709: high trust points to plain first use, not create.
    assert "first use creates it" in empty["hint"] and "mill create label" not in empty["hint"]
    assert rec_name.get(cn, "no-such-pack", "label") is None

    monkeypatch.setattr(rpc, "LABEL_LIST_MAX_BYTES", 80)
    capped = rpc._h_trail(book, {"label": "pack"}, "unit", "a")
    assert capped["truncated"] is True
    assert len(capped["rows"]) < 3
    blob = b"".join(json.dumps(r, separators=(",", ":")).encode("utf-8") for r in capped["rows"])
    assert len(blob) <= 80 or len(capped["rows"]) == 1


def _mysql_bin() -> str:
    import shutil

    found = shutil.which("mysql")
    if found:
        return found
    cand = r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
    if os.path.isfile(cand):
        return cand
    return ""


def test_label_add_missing_and_deleted_activity(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("bug", "label"))
    book = _Book(cn)
    cur = _cur(cn)
    cur.execute("SELECT DATABASE()")
    db = str(cur.fetchone()[0])
    cur.close()
    with pytest.raises(CoordError, match="label-add: no todo 999999") as missing:
        rpc._h_label(
            book,
            {"verb": "label-add", "type": "todo", "id": 999999, "label": "bug"},
            "unit",
            "a",
        )
    assert db not in str(missing.value)
    assert "1452" not in str(missing.value)
    tid = int(rec_todo.insert(cn, "unit", "a", "open", "gone")[0]["id"])
    _exec(
        cn,
        "UPDATE activity SET deleted = CURRENT_TIMESTAMP(6) WHERE type='todo' AND id=%s",
        (tid,),
    )
    with pytest.raises(CoordError, match="label-add: no todo %s" % tid) as gone:
        rpc._h_label(
            book,
            {"verb": "label-add", "type": "todo", "id": tid, "label": "bug"},
            "unit",
            "a",
        )
    assert db not in str(gone.value)
    assert _count(cn, "todo", tid) == 0


def test_routines_compile_split_script_and_whole_file(cn, tmp_path) -> None:
    names = ("mill_label_put", "mill_label_delete", "mill_label_select")
    path = migrate.sql_dir() / "sp_label.sql"
    blob = path.read_text(encoding="utf-8")
    cur = _cur(cn)
    for name in names:
        cur.execute("DROP PROCEDURE IF EXISTS %s" % name)
    for stmt in migrate.split_script(blob):
        cur.execute(stmt)
    cn.commit()
    cur.close()
    assert "COALESCE" in _routine(cn, "mill_label_put")
    assert "no such name" in _routine(cn, "mill_label_delete")
    assert "ORDER BY" in _routine(cn, "mill_label_select")

    cur = _cur(cn)
    for name in names:
        cur.execute("DROP PROCEDURE IF EXISTS %s" % name)
    cn.commit()
    cur.execute("SELECT DATABASE()")
    db = str(cur.fetchone()[0])
    cur.close()

    mysql = _mysql_bin()
    if not mysql:
        # CI's python image has no mysql client. The split_script half above still runs;
        # the whole-file half is covered by the release throwaway A/B.
        # Restore tip routines before skip: the second DROP above would otherwise
        # poison the shared schema for later modules (card 986).
        from tests import sql_book

        sql_book.restore_tip_routines(cn)
        pytest.skip("mysql client not on PATH; whole-file apply not checked here")
    kw = conn_kwargs()
    cnf = tmp_path / ("mill-label-ord-%s.cnf" % os.getpid())
    try:
        cnf.write_text(
            "[client]\n"
            "host=%s\n" % (kw.get("host") or "127.0.0.1")
            + "port=%s\n" % (kw.get("port") or 3306)
            + "user=%s\n" % (kw.get("user") or "")
            + "password=%s\n" % (kw.get("password") or ""),
            encoding="ascii",
            newline="\n",
        )
        proc = subprocess.run(
            [mysql, "--defaults-extra-file=" + str(cnf), db],
            input=blob.encode("utf-8"),
            capture_output=True,
        )
    finally:
        if cnf.is_file():
            cnf.unlink()
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[:400]
    for name in names:
        assert _routine(cn, name)
    assert "ORDER BY" in _routine(cn, "mill_label_select")

