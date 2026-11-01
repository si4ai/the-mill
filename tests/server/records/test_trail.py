# -*- coding: utf-8 -*-
"""mill trail on a throwaway DB: finding -> tries -> dead end / solved (agent-ux findings)."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.trail_text import render
from agent_coord.server.api.mill import rpc
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

class _Book:
    def __init__(self, cn):
        self._cn = cn

@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)

def _branch(cn):
    """Room root, a finding reply, try A (dead end, done), try B (solved, shipped) with a deeper try."""
    seed_names(cn, ("unit", "roster"), ("asker", "desk"), ("tester", "desk"), ("outsider", "desk"))
    book = _Book(cn)
    room = "ux-" + uuid.uuid4().hex[:6]
    root = rpc._h_send(book, {"src": "asker", "dst": "tester", "body": "room root", "name": room}, "unit", "asker")
    rid = int(root["id"])
    fnd = rpc._h_reply(
        book,
        {"mail_id": rid, "body": "command: todo\\nerror: no sitting connect", "src": "asker"},
        "unit",
        "asker",
    )
    fid = int(fnd["id"])
    tag = uuid.uuid4().hex[:6]
    a = rpc._h_open(
        book,
        {"need": f"f{fid}-rerun-{tag}", "detail": "rerun the command", "parent_type": "mail", "parent_id": fid},
        "unit",
        "asker",
    )
    b = rpc._h_open(
        book,
        {"need": f"f{fid}-same-launcher-{tag}", "detail": "same launcher", "parent_type": "mail", "parent_id": fid},
        "unit",
        "asker",
    )
    a_need, b_need = f"f{fid}-rerun-{tag}", f"f{fid}-same-launcher-{tag}"
    a_id, b_id = int(a["id"]), int(b["id"])
    deep = rpc._h_open(
        book,
        {"need": f"f{fid}-deeper-{tag}", "detail": "try python -m", "parent_type": "todo", "parent_id": b_id},
        "unit",
        "asker",
    )
    for need in (a_need, b_need):
        rpc._h_claim(book, {"need": need}, "unit", "tester")
    rpc._h_note(book, {"need": a_need, "note": "dead-end: same error after rerun"}, "unit", "tester")
    rpc._h_pass(book, {"need": a_need}, "unit", "tester")  # claimed -> shipped (volunteer)
    rpc._h_pass(book, {"need": a_need, "step": "done"}, "unit", "asker")  # shipped -> done (asker, agent-ux 1213)
    rpc._h_note(book, {"need": b_need, "note": "solved: same launcher both sides, exit 0"}, "unit", "tester")
    rpc._h_pass(book, {"need": b_need}, "unit", "tester")
    return {"book": book, "room": room, "rid": rid, "fid": fid, "a": a_id, "b": b_id, "deep": int(deep["id"])}

def test_trail_from_finding_shows_branch(cn) -> None:
    br = _branch(cn)
    out = rpc._h_trail(br["book"], {"node": f"mail:{br['fid']}"}, "unit", "tester")
    nodes = out["nodes"]
    assert out["tree"] == br["room"]
    got = [(n["kind"], n["id"], n["depth"]) for n in nodes]
    assert got[0] == ("mail", br["fid"], 0)
    assert ("todo", br["a"], 1) in got
    assert ("todo", br["b"], 1) in got
    assert ("todo", br["deep"], 2) in got
    by = {(n["kind"], n["id"]): n for n in nodes}
    a, b = by[("todo", br["a"])], by[("todo", br["b"])]
    assert a["state"] == "done" and a["mark"] == "DEAD END"
    assert b["state"] == "shipped" and b["mark"] == "SOLVED"
    assert by[("todo", br["deep"])]["state"] == "open"
    assert all(n["at_pt"].endswith(" PT") for n in nodes)
    assert all(n["at_utc"].endswith("Z") for n in nodes)
    text = render(out)
    assert "[DEAD END]" in text and "[SOLVED]" in text
    assert "1 dead end(s), 1 solved" in text
    assert "\n  todo " in text and "\n    todo " in text

def test_trail_from_room_root_and_todo(cn) -> None:
    br = _branch(cn)
    root = rpc._h_trail(br["book"], {"node": f"mail:{br['rid']}"}, "unit", "asker")
    ids = [(n["kind"], n["id"]) for n in root["nodes"]]
    assert ids[0] == ("mail", br["rid"]) and ("mail", br["fid"]) in ids
    sub = rpc._h_trail(br["book"], {"node": f"todo:{br['b']}"}, "unit", "outsider")
    assert [(n["kind"], n["id"], n["depth"]) for n in sub["nodes"]] == [
        ("todo", br["b"], 0),
        ("todo", br["deep"], 1),
    ]

def test_trail_mail_reads_without_cast(cn) -> None:
    # #672 S-3: every desk in the office trails any mail.
    br = _branch(cn)
    out = rpc._h_trail(br["book"], {"node": f"mail:{br['fid']}"}, "unit", "outsider")
    assert out["nodes"][0]["id"] == br["fid"]
    assert all(n["state"] != "hidden" for n in out["nodes"])

def test_trail_bad_and_missing_ids(cn) -> None:
    book = _Book(cn)
    with pytest.raises(CoordError):
        rpc._h_trail(book, {"node": "abc"}, "unit", "asker")
    with pytest.raises(CoordError):
        rpc._h_trail(book, {"node": "todo:99999999"}, "unit", "asker")

def test_trail_off_tree_todo(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("asker", "desk"))
    book = _Book(cn)
    t = rpc._h_open(book, {"need": "lone-" + uuid.uuid4().hex[:6]}, "unit", "asker")
    out = rpc._h_trail(book, {"node": f"todo:{t['id']}"}, "unit", "asker")
    assert out["tree"] == ""
    assert out["on_tree"] is False
    assert [n["id"] for n in out["nodes"]] == [int(t["id"])]

def test_trail_reply_opened_room_header(cn) -> None:
    """Validator 0.6.26: a reply-opened room (hidden tree) is still on a tree."""
    from agent_coord.helpers.trail_text import render

    seed_names(cn, ("unit", "roster"), ("asker", "desk"), ("other", "desk"))
    book = _Book(cn)
    root = rpc._h_send(book, {"src": "asker", "dst": "other", "body": "plain"}, "unit", "asker")
    rpc._h_reply(book, {"mail_id": int(root["id"]), "body": "solved: ok"}, "unit", "other")
    out = rpc._h_trail(book, {"node": f"mail:{root['id']}"}, "unit", "asker")
    assert out["tree"] == "" and out["on_tree"] is True
    head = render(out).splitlines()[0]
    assert "not on a tree" not in head and "unnamed tree" in head

def test_todo_done_visible_over_rpc(cn) -> None:
    """agent-ux 1215 against real SQL: done cards readable with --done / --status done."""
    br = _branch(cn)
    book = br["book"]
    plain = {int(r["id"]) for r in rpc._h_todo(book, {}, "unit", "asker")}
    assert br["a"] not in plain
    with_done = {int(r["id"]) for r in rpc._h_todo(book, {"done": True}, "unit", "asker")}
    assert br["a"] in with_done
    only_done = rpc._h_todo(book, {"status": "done"}, "unit", "asker")
    assert {r["status"] for r in only_done} == {"done"}
    assert br["a"] in {int(r["id"]) for r in only_done}
