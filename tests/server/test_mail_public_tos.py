"""Public mail cast: sender{deskId,roster} + mail_tos lean shape."""
from __future__ import annotations

from agent_coord.server.records import mail as rec_mail


def test_public_mail_tos_desk_receipt():
    rows = [
        {"desk": "alice", "roster": None, "receipt": 0, "opened": None},
        {"desk": "bob", "roster": "unit", "receipt": 1, "opened": "2026-01-01 00:00:00"},
        {"desk": "", "roster": None, "receipt": 0, "opened": None},
    ]
    tos = rec_mail.public_mail_tos(rows)
    assert tos == [
        {"deskId": "alice", "receipt": 0},
        {"deskId": "bob", "receipt": 1},
    ]
    for t in tos:
        assert "opened" not in t
        assert set(t.keys()) == {"deskId", "receipt"}


def test_public_mail_tos_empty():
    assert rec_mail.public_mail_tos([]) == []
    assert rec_mail.public_mail_tos(None) == []  # type: ignore[arg-type]


def test_public_mail_lean_letter():
    row = {
        "id": 7,
        "created": "2026-01-02 03:04:05",
        "desk": "alice",
        "sender_roster": "builder",
        "body": "hello",
        "src": "should-not-win",
        "roster": "leak",
        "roster_id": 99,
    }
    dest = [
        {"desk": "bob", "roster": None, "receipt": 0, "opened": "x"},
        {"desk": "carol", "roster": "unit", "receipt": 0, "opened": None},
    ]
    pub = rec_mail.public_mail(row, dest, crumbs={"tree": "stand-up", "root_id": 7, "root_type": "mail"})
    assert set(pub.keys()) == {
        "id", "created", "from", "sender", "body", "mail_tos", "to", "tree", "root_id", "root_type"
    }
    assert pub["from"] == "alice"  # card 837: one sender key on every letter row
    assert pub["to"] == ["bob", "carol"]
    assert pub["sender"] == {"deskId": "alice", "roster": "builder"}
    assert pub["body"] == "hello"
    assert "opened" not in pub["mail_tos"][0]
    assert "src" not in pub and "dst" not in pub and "dests" not in pub
    assert "tos" not in pub and "roster" not in pub and "read" not in pub


def test_public_mail_sender_roster_null():
    pub = rec_mail.public_mail(
        {"id": 1, "created": "t", "desk": "alice", "body": "x"},
        [{"desk": "bob", "roster": None, "receipt": 0}],
    )
    assert pub["sender"] == {"deskId": "alice", "roster": None}


def test_room_cast_sender_union_tos():
    pub = {
        "sender": {"deskId": "alice", "roster": "builder"},
        "mail_tos": [
            {"deskId": "bob", "roster": "unit", "receipt": 0},
            {"deskId": "alice", "roster": None, "receipt": 0},
        ],
    }
    cast = rec_mail.room_cast(pub)
    assert cast == [
        {"deskId": "alice", "roster": "builder"},
        {"deskId": "bob", "roster": "unit"},
    ]


def test_mail_crumb_root_is_the_first_letter():
    """A non-mail ancestor is not the room. The outermost mail card is."""
    packed = [
        {"tree": "stand-up", "anc_type": "name", "anc_id": 7, "lft": 1},
        {"tree": "stand-up", "anc_type": "mail", "anc_id": 101, "lft": 2},
        {"tree": "stand-up", "anc_type": "mail", "anc_id": 102, "lft": 3},
    ]
    crumb = rec_mail._mail_crumb(packed, 102)
    assert crumb["tree"] == "stand-up"
    assert crumb["root_type"] == "mail"
    assert crumb["root_id"] == 101
    assert crumb["parent_type"] == "mail"
    assert crumb["parent_id"] == 101
    root = rec_mail._mail_crumb(packed[:2], 101)
    assert root == {"tree": "stand-up", "root_id": 101, "root_type": "mail"}
