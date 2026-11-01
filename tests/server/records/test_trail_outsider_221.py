"""#221 then #672 (S-3): an outsider trails any mail; reading never joins it."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from tests.server.records.conftest import seed_names

class _Book:
    def __init__(self, cn):
        self._cn = cn

@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("unit", "roster"), ("asker", "desk"), ("tester", "desk"), ("outsider", "desk"))
    yield c
    c.close()

@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)

def _room(cn):
    book = _Book(cn)
    room = "ux-" + uuid.uuid4().hex[:6]
    root = rpc._h_send(
        book,
        {"src": "asker", "dst": "tester", "body": "room root", "name": room},
        "unit",
        "asker",
    )
    rid = int(root["id"])
    finding = rpc._h_reply(book, {"mail_id": rid, "body": "command: trail"}, "unit", "asker")
    fid = int(finding["id"])
    card = rpc._h_open(
        book,
        {
            "need": f"f{fid}-try-" + uuid.uuid4().hex[:6],
            "detail": "one try",
            "parent_type": "mail",
            "parent_id": fid,
        },
        "unit",
        "asker",
    )
    return book, rid, fid, int(card["id"])

def test_outsider_trails_a_room_mail(cn) -> None:
    book, rid, fid, card = _room(cn)
    out = rpc._h_trail(book, {"node": f"mail:{fid}"}, "unit", "outsider")
    nodes = {(n["kind"], n["id"]): n for n in out["nodes"]}
    assert nodes[("mail", fid)]["title"] == "command: trail"
    assert nodes[("mail", fid)]["state"] == "sent"
    assert ("todo", card) in nodes
    from agent_coord.server.records import mail as rec_mail

    assert "outsider" not in rec_mail.room_participants(cn, rid)

def test_outsider_trails_a_direct_letter(cn) -> None:
    # #672 S-3: a direct (off-tree) letter is readable too; nothing is private.
    book = _Book(cn)
    sent = rpc._h_send(book, {"src": "asker", "dst": "tester", "body": "plain"}, "unit", "asker")
    mid = int(sent["id"])
    out = rpc._h_trail(book, {"node": f"mail:{mid}"}, "unit", "outsider")
    assert out["nodes"][0]["title"] == "plain"

def test_participant_mail_trail_still_reads(cn) -> None:
    book, rid, fid, card = _room(cn)
    out = rpc._h_trail(book, {"node": f"mail:{fid}"}, "unit", "tester")
    ids = [(n["kind"], n["id"]) for n in out["nodes"]]
    assert ("mail", fid) in ids
    assert ("todo", card) in ids
    root = rpc._h_trail(book, {"node": f"mail:{rid}"}, "unit", "asker")
    assert ("mail", rid) in [(n["kind"], n["id"]) for n in root["nodes"]]

def test_outsider_todo_trail_still_reads(cn) -> None:
    book, _rid, _fid, card = _room(cn)
    out = rpc._h_trail(book, {"node": f"todo:{card}"}, "unit", "outsider")
    assert [(n["kind"], n["id"]) for n in out["nodes"]][0] == ("todo", card)

def test_hold_id_is_not_a_trail_target(cn) -> None:
    book = _Book(cn)
    held = rpc._h_hold(book, {"resource": "docs/a.md"}, "unit", "asker")
    hid = int(held["id"])
    with pytest.raises(CoordError) as ei:
        rpc._h_trail(book, {"node": f"hold:{hid}"}, "unit", "outsider")
    assert "mail id or todo id" in str(ei.value)
