"""Card 926 / F220: guarded mill rename todo - id key, old need reserved, one timeline row."""
from __future__ import annotations

import json

import mysql.connector
import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs, call, scalar_done

def _seat(cn, name: str) -> str:
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as rec_join

    rec_join.upsert(cn, "Office", name, "", token_hash("seat-" + name), None)
    return name

def _mk_card(cn, roster: str, asker: str, need: str, detail: str = "d") -> int:
    rec_name.get_or_insert(cn, roster, "roster")
    rec_member.put(cn, roster, asker)
    rows = rec_todo.insert(
        cn, roster, asker, "open", json.dumps({"slug": need, "detail": detail})
    )
    return int(rows[0]["id"])

def test_rename_updates_slug_keeps_id_and_old_resolves(cn) -> None:
    asker = _seat(cn, "d926a")
    tid = _mk_card(cn, "r926a", asker, "old-need-a")
    out = rec_todo.rename(cn, tid, asker, "old-need-a", "new-need-a", why="wider scope")
    assert out["id"] == tid
    assert out["need_id"] == "new-need-a"
    assert out["was"] == "old-need-a"
    hit_new = rec_todo.find(cn, "r926a", "new-need-a")
    hit_old = rec_todo.find(cn, "r926a", "old-need-a")
    assert hit_new is not None and int(hit_new["id"]) == tid
    assert hit_old is not None and int(hit_old["id"]) == tid
    fields = rec_todo.unpack(hit_new.get("body") or "", tid)
    assert fields["need_id"] == "new-need-a"
    assert "old-need-a" in fields["aliases"]

def test_create_refuses_old_need(cn) -> None:
    asker = _seat(cn, "d926b")
    tid = _mk_card(cn, "r926b", asker, "old-need-b")
    rec_todo.rename(cn, tid, asker, "old-need-b", "new-need-b", why="x")
    # create path uses find(); a hit means refuse
    assert rec_todo.find(cn, "r926b", "old-need-b") is not None
    assert int(rec_todo.find(cn, "r926b", "old-need-b")["id"]) == tid

def test_one_timeline_row_with_old_new_who_why(cn) -> None:
    asker = _seat(cn, "d926c")
    tid = _mk_card(cn, "r926c", asker, "old-need-c")
    before = scalar_done(
        cn,
        "SELECT COUNT(*) FROM doing WHERE on_type='todo' AND on_id=%s AND act='rename'",
        (tid,),
    )
    rec_todo.rename(cn, tid, asker, "old-need-c", "new-need-c", why="goal name")
    after = call(
        cn,
        "mill_todo_get",  # may not return moves; query doing directly below
        [tid],
    )
    assert after and int(after[0]["id"]) == tid
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT act, desk_id, evidence FROM doing "
            "WHERE on_type='todo' AND on_id=%s AND act='rename' ORDER BY id",
            (tid,),
        )
        rows = list(cur.fetchall())
    finally:
        cur.close()
    assert len(rows) == int(before or 0) + 1
    ev = json.loads(rows[-1]["evidence"] or "{}")
    assert ev["old"] == "old-need-c"
    assert ev["new"] == "new-need-c"
    assert ev["why"] == "goal name"
    desk_id = scalar_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", ("d926c",))
    assert int(rows[-1]["desk_id"]) == int(desk_id)
    act = scalar_done(
        cn, "SELECT act FROM activity WHERE type='todo' AND id=%s", (tid,)
    )
    assert act == "rename"

def test_second_rename_keeps_prior_aliases(cn) -> None:
    asker = _seat(cn, "d926d")
    tid = _mk_card(cn, "r926d", asker, "need-v1")
    rec_todo.rename(cn, tid, asker, "need-v1", "need-v2", why="one")
    rec_todo.rename(cn, tid, asker, "need-v2", "need-v3", why="two")
    hit = rec_todo.find(cn, "r926d", "need-v1")
    assert hit is not None and int(hit["id"]) == tid
    hit2 = rec_todo.find(cn, "r926d", "need-v2")
    assert hit2 is not None and int(hit2["id"]) == tid
    fields = rec_todo.unpack(hit["body"], tid)
    assert fields["need_id"] == "need-v3"
    assert fields["was"] == "need-v2"
    assert "need-v1" in fields["aliases"]

def test_was_on_unpack(cn) -> None:
    asker = _seat(cn, "d926e")
    tid = _mk_card(cn, "r926e", asker, "old-need-e")
    rec_todo.rename(cn, tid, asker, "old-need-e", "new-need-e", why="admin")
    hit = rec_todo.find(cn, "r926e", "new-need-e")
    fields = rec_todo.unpack(hit["body"], tid)
    assert fields["was"] == "old-need-e"

def test_rename_onto_taken_need_refused(cn) -> None:
    asker = _seat(cn, "d926f")
    a = _mk_card(cn, "r926f", asker, "need-keep")
    b = _mk_card(cn, "r926f", asker, "need-move")
    with pytest.raises(CoordError, match=r"exists|taken|nothing"):
        rec_todo.rename(cn, b, asker, "need-move", "need-keep", why="clash")
    assert rec_todo.unpack(rec_todo.find(cn, "r926f", "need-move")["body"], b)["need_id"] == "need-move"
    assert int(rec_todo.find(cn, "r926f", "need-keep")["id"]) == a
