# -*- coding: utf-8 -*-
"""#672 S-3, F88: collaboration by default. Every desk in the office reads every
letter, room and thread; a read joins no one, delivers nothing and wakes no one.

Direct letters, named rooms and rooms opened by replying to a direct letter are
all readable by a desk that is on none of them, through mail-thread and trail
(node and --label). Inbox and wake routing are unchanged: a letter still lands
only in its addressees' inbox. A secret in a stored body reads back redacted.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.const import CONST_LABEL
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)


@pytest.fixture
def pushes(monkeypatch):
    """Every push and webhook wake the wall tries during the test."""
    seen: list[tuple] = []
    from agent_coord.server import push, wake

    real_emit = push.emit

    def _emit(cn, desk, kind, payload, **kw):
        seen.append(("emit", desk, kind))
        return real_emit(cn, desk, kind, payload, **kw)

    monkeypatch.setattr(push, "emit", _emit)
    monkeypatch.setattr(wake, "fire_wake_hook", lambda *a, **k: seen.append(("wake",) + a) or True)
    return seen


@pytest.fixture(scope="module")
def office(cn):
    seed_names(
        cn,
        ("ora", "roster"),
        ("or_a", "desk"),
        ("or_b", "desk"),
        ("or_c", "desk"),
        ("or_out", "desk"),
    )
    book = _Book(cn)
    direct = int(rpc._h_send(book, {"src": "or_a", "dst": "or_b", "body": "direct note"}, "ora", "or_a")["id"])
    root = int(rpc._h_send(book, {"src": "or_a", "dst": "or_b", "body": "room root", "name": "or-room"}, "ora", "or_a")["id"])
    r1 = int(rpc._h_reply(book, {"mail_id": root, "body": "r1"}, "ora", "or_b")["id"])
    # a side letter that leaves or_b off: still readable by every desk
    side = int(rpc._h_reply(book, {"mail_id": r1, "body": "side", "mail_tos": ["or_c"]}, "ora", "or_a")["id"])
    opened = int(rpc._h_send(book, {"src": "or_a", "dst": "or_b", "body": "will be a thread"}, "ora", "or_a")["id"])
    o1 = int(rpc._h_reply(book, {"mail_id": opened, "body": "thread reply"}, "ora", "or_b")["id"])
    return {
        "book": book,
        "direct": direct,
        "room": [root, r1, side],
        "opened": [opened, o1],
    }


def _ids(out) -> set[int]:
    return {int(m["id"]) for m in out["chain"]}


def _inbox_ids(book, desk) -> set[int]:
    out = rpc._h_inbox(book, {"all": True}, "ora", desk)
    rows = out.get("mailbox") or out.get("inbox") or out.get("mail") or [] if isinstance(out, dict) else out
    return {int(r.get("id") or 0) for r in rows if isinstance(r, dict)}


def test_outsider_reads_direct_letter(cn, office) -> None:
    got = rpc._h_mail_thread(office["book"], {"mail_id": office["direct"], "scope": "full"}, "ora", "or_out")
    assert _ids(got) == {office["direct"]}
    assert got["chain"][0]["body"] == "direct note"


def test_outsider_reads_whole_named_room(cn, office) -> None:
    root = office["room"][0]
    got = rpc._h_mail_thread(office["book"], {"mail_id": root, "scope": "room"}, "ora", "or_out")
    assert _ids(got) == set(office["room"])
    assert got["room_letters"] == len(office["room"])
    # a participant sees the same letters, side letter included
    mine = rpc._h_mail_thread(office["book"], {"mail_id": root, "scope": "room"}, "ora", "or_b")
    assert _ids(mine) == _ids(got)


def test_outsider_reads_room_opened_from_direct_letter(cn, office) -> None:
    got = rpc._h_mail_thread(office["book"], {"mail_id": office["opened"][0], "scope": "room"}, "ora", "or_out")
    assert _ids(got) == set(office["opened"])


def test_outsider_trails_every_kind(cn, office) -> None:
    for mid in (office["direct"], office["room"][0], office["opened"][0]):
        out = rpc._h_trail(office["book"], {"node": f"mail:{mid}"}, "ora", "or_out")
        assert all(n["state"] != "hidden" for n in out["nodes"]), mid
        assert out["nodes"][0]["id"] == mid


def test_outsider_trail_label_lists_direct_letter(cn, office) -> None:
    rec_name.host_put(cn, "or-lbl", CONST_LABEL)
    rec_label.put(cn, "mail", office["direct"], "or-lbl", 0)
    rec_label.put(cn, "mail", office["room"][2], "or-lbl", 1)
    out = rpc._h_trail(office["book"], {"label": "or-lbl"}, "ora", "or_out")
    assert {int(r["id"]) for r in out["rows"]} == {office["direct"], office["room"][2]}


def test_read_joins_no_one_delivers_nothing_wakes_no_one(cn, office, pushes) -> None:
    before = _inbox_ids(office["book"], "or_out")
    for mid in (office["direct"], office["room"][0], office["opened"][0]):
        rpc._h_mail_thread(office["book"], {"mail_id": mid, "scope": "room"}, "ora", "or_out")
        rpc._h_trail(office["book"], {"node": f"mail:{mid}"}, "ora", "or_out")
        assert "or_out" not in rec_mail.room_participants(cn, mid)
    assert pushes == []
    assert _inbox_ids(office["book"], "or_out") == before
    assert not (before & ({office["direct"]} | set(office["room"]) | set(office["opened"])))


def test_inbox_and_push_still_go_only_to_addressees(cn, office, pushes) -> None:
    book = office["book"]
    mid = int(rpc._h_send(book, {"src": "or_a", "dst": "or_b", "body": "for b only"}, "ora", "or_a")["id"])
    assert mid in _inbox_ids(book, "or_b")
    assert mid not in _inbox_ids(book, "or_out")
    assert {p[1] for p in pushes if p[0] == "emit"} <= {"or_b"}


def test_stored_secret_reads_back_redacted(cn, office) -> None:
    # A body stored without the write-side scrub (a letter from before #504).
    secret = "ghp_" + "a1B2" * 9
    book = office["book"]
    mid = int(rpc._h_send(book, {"src": "or_a", "dst": "or_b", "body": f"token {secret} end"}, "ora", "or_a")["id"])
    got = rpc._h_mail_thread(book, {"mail_id": mid, "scope": "full"}, "ora", "or_out")
    body = got["chain"][0]["body"]
    assert secret not in body and "[REDACTED:" in body
    out = rpc._h_trail(book, {"node": f"mail:{mid}"}, "ora", "or_out")
    assert secret not in out["nodes"][0]["title"]
    rec_name.host_put(cn, "or-sec", CONST_LABEL)
    rec_label.put(cn, "mail", mid, "or-sec", 0)
    rows = rpc._h_trail(book, {"label": "or-sec"}, "ora", "or_out")["rows"]
    assert rows and secret not in rows[0]["body"]
