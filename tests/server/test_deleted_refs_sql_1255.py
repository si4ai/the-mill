"""Card 1255: activities keep a retired or trashed name, marked; live lists hide trashed.

A trashed roster and a retired desk stay on the cards, letters, holds and
scores that name them (a retired desk's holds are freed), in the Wall feeds (/api/v1/todos, mailbox, holds,
scores, labels) and in a CLI reply, each row with deleted_names. A trashed
label leaves the PRIORITIES lists and a trashed tree leaves mill rooms.
Card 1241 removes those rows, so mill restore does not put them back.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import hold, join, label as rec_label, mail, score, todo
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import admin_desk
from tests.server.test_wall_scope_filters_1193 import _client

pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)


def _world(cn) -> dict:
    tag = uuid4().hex[:6]
    w = {"roster": "r1255m-" + tag, "gone": "d1255g-" + tag, "live": "d1255l-" + tag}
    join.upsert(cn, w["roster"], w["gone"], "", "e" * 64)
    join.upsert(cn, w["roster"], w["live"], "", "f" * 64)
    join.upsert(cn, "Office", w["gone"], "", "e" * 64)
    join.upsert(cn, "Office", w["live"], "", "f" * 64)
    cn.commit()
    w["todo"] = int(todo.insert(cn, w["roster"], w["gone"], "open", "need: n" + tag)[0]["id"])
    w["mail"] = int(mail.insert(cn, w["roster"], w["gone"], w["live"], "hello " + tag)[0]["id"])
    hold.upsert(cn, "Office", w["gone"], "res1255-" + tag)
    score.upsert(cn, w["roster"], w["gone"], "kpi1255" + tag, "1", "2", "n")
    cn.commit()
    return w


def _retire(cn, desk: str) -> None:
    rec_name.retire(cn, desk, "desk", by=admin_desk(cn))
    cn.commit()


def _rows(client, route: str, key: str) -> list[dict]:
    body = client.get(route).json()
    assert key in body, body
    return body[key]


def test_wall_feeds_keep_rows_and_mark_a_retired_desk(cn, monkeypatch) -> None:
    w = _world(cn)
    client = _client(monkeypatch, cn)
    route = f"/api/v1/todos?project={w['roster']}"
    before = [r for r in _rows(client, route, "needs") if r["id"] == w["todo"]]
    assert before and "deleted_names" not in before[0]
    _retire(cn, w["gone"])

    needs = [r for r in _rows(client, route, "needs") if r["id"] == w["todo"]]
    assert len(needs) == 1 and needs[0]["deleted_names"] == [w["gone"]]
    assert needs[0]["asker"] == w["gone"]  # the name stays on the card

    letters = [r for r in _rows(client, f"/api/v1/mailbox?project={w['roster']}", "mailbox") if r["id"] == w["mail"]]
    assert len(letters) == 1 and letters[0]["deleted_names"] == [w["gone"]]
    assert letters[0]["sender"]["deleted_names"] == [w["gone"]]
    assert "deleted_names" not in letters[0]["mail_tos"][0]  # the live recipient

    # sp_name_retire frees the desk's holds, so no live lock names it (the helper's hold shape
    # is covered in test_name_marks_1255).
    assert not [r for r in _rows(client, "/api/v1/holds?project=Office", "locks") if r.get("owner") == w["gone"]]

    kpis = [r for r in _rows(client, f"/api/v1/scores?project={w['roster']}", "kpis") if r.get("owner") == w["gone"]]
    assert kpis and all(r["deleted_names"] == [w["gone"]] for r in kpis)


def test_card_on_a_trashed_roster_stays_on_priorities_marked(cn, monkeypatch) -> None:
    w = _world(cn)
    lbl = "l1255r-" + uuid4().hex[:6]
    rec_name.get_or_insert(cn, lbl, "label")
    rec_label.put(cn, "todo", w["todo"], lbl)
    cn.commit()
    client = _client(monkeypatch, cn)
    route = f"/api/v1/labels?project=Office&names={lbl}"
    rec_name.trash(cn, w["roster"], "roster", by=admin_desk(cn))
    cn.commit()
    rows = _rows(client, route, "rows")
    assert [r["id"] for r in rows] == [w["todo"]]
    assert rows[0]["card"]["roster"] == w["roster"]
    assert rows[0]["card"]["deleted_names"] == [w["roster"]]
    assert "deleted_names" not in rows[0]  # the live label itself


def test_cli_reply_marks_a_retired_desk_on_a_card(cn) -> None:
    w = _world(cn)
    _retire(cn, w["gone"])
    out = rpc._run_command(_Book(cn), rpc._h_todo, "todo", {"need": str(w["todo"])}, w["roster"], w["live"])
    rows = out if isinstance(out, list) else [out]
    card = [r for r in rows if int(r.get("id") or 0) == w["todo"]]
    assert card and card[0]["deleted_names"] == [w["gone"]]


def test_trashed_label_leaves_priorities_until_restore(cn, monkeypatch) -> None:
    w = _world(cn)
    lbl = "l1255-" + uuid4().hex[:6]
    rec_name.get_or_insert(cn, lbl, "label")
    rec_label.put(cn, "todo", w["todo"], lbl)
    cn.commit()
    client = _client(monkeypatch, cn)
    route = f"/api/v1/labels?project=Office&names={lbl}"
    assert [r["id"] for r in _rows(client, route, "rows")] == [w["todo"]]
    admin = admin_desk(cn)
    rec_name.trash(cn, lbl, "label", by=admin)
    cn.commit()
    assert _rows(client, route, "rows") == []
    assert rec_label.rows_for(cn, lbl) == []
    rec_name.restore_trashed(cn, lbl, "label", by=admin)
    cn.commit()
    assert _rows(client, route, "rows") == []
    assert rec_label.rows_for(cn, lbl) == []


def test_trashed_tree_leaves_rooms_until_restore(cn) -> None:
    w = _world(cn)
    room = "t1255-" + uuid4().hex[:6]
    book = _Book(cn)
    rpc._h_send(book, {"src": w["live"], "dst": w["gone"], "body": "room root", "name": room}, w["roster"], w["live"])
    cn.commit()

    def rooms() -> set[str]:
        return {r["tree"] for r in rec_tree.list_mail_rooms(cn)}

    assert room in rooms()
    admin = admin_desk(cn)
    rec_name.trash(cn, room, "tree", by=admin)
    cn.commit()
    assert room not in rooms()
    rec_name.restore_trashed(cn, room, "tree", by=admin)
    cn.commit()
    assert room not in rooms()


def test_part_fingerprints_move_on_retire_trash_and_restore(cn) -> None:
    """The Wall polls with ?fp=; a mark change must not hide behind an unchanged fingerprint."""
    from agent_coord.server.records import floor

    w = _world(cn)
    parts = ("todos", "mail", "scores", "holds", "events")

    def fps() -> dict[str, str]:
        return {p: floor._projects_part_fp(cn, [w["roster"]], p) for p in parts}

    a = fps()
    _retire(cn, w["gone"])
    b = fps()
    admin = admin_desk(cn)
    rec_name.trash(cn, w["roster"], "roster", by=admin)
    cn.commit()
    c = fps()
    rec_name.restore_trashed(cn, w["roster"], "roster", by=admin)
    cn.commit()
    d = fps()
    for p in parts:
        # each step changes the marks a client holds; after restore the marks equal b's again
        assert a[p] != b[p] and b[p] != c[p] and c[p] != d[p], p
