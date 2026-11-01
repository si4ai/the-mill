# -*- coding: utf-8 -*-
"""Card 975: mill rooms --digest is a zero-token room summary (one SQL query)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import seed_names

ROOM_ROOT_LINE_CAP = 200


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    # Keep parity with other rooms suites; digest itself must not need this
    # (see test_dispatch_ws_rooms_digest_without_require_live_ws_patch).
    monkeypatch.setattr(
        "agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None
    )


@pytest.fixture(scope="module")
def digest_office(cn):
    """Named rooms: empty first line, one-letter, and a cut-off first line."""
    seed_names(
        cn,
        ("dg", "roster"),
        ("dg_a", "desk"),
        ("dg_b", "desk"),
        ("dg_c", "desk"),
    )
    book = _Book(cn)
    empty = int(
        rpc._h_send(
            book,
            # Leading newline: first line is empty; body still meets 1..4096.
            {
                "src": "dg_a",
                "dst": "dg_b",
                "body": "\nsecond line only",
                "name": "dg-empty",
            },
            "dg",
            "dg_a",
        )["id"]
    )
    one = int(
        rpc._h_send(
            book,
            {
                "src": "dg_a",
                "dst": "dg_b",
                "body": "one letter first line\nsecond line ignored",
                "name": "dg-one",
            },
            "dg",
            "dg_a",
        )["id"]
    )
    long_line = ("x" * (ROOM_ROOT_LINE_CAP + 40)) + "\nmore"
    cut = int(
        rpc._h_send(
            book,
            {"src": "dg_b", "dst": "dg_a,dg_c", "body": long_line, "name": "dg-cut"},
            "dg",
            "dg_b",
        )["id"]
    )
    # one reply on cut so last_at can move past created and members grow
    rpc._h_reply(
        book,
        {"mail_id": cut, "body": "reply on cut", "mail_tos": ["dg_b"]},
        "dg",
        "dg_a",
    )
    return {"book": book, "empty": empty, "one": one, "cut": cut}


def _dg(rows):
    return [r for r in rows if str(r.get("tree") or "").startswith("dg-")]


def test_digest_empty_room_first_line(cn, digest_office):
    out = rpc._h_rooms(digest_office["book"], {"digest": True}, "dg", "dg_a")
    by = {r["tree"]: r for r in _dg(out["rooms"])}
    assert "dg-empty" in by
    row = by["dg-empty"]
    assert row["size"] == 1
    assert row.get("root") == ""
    assert row.get("starter") == "dg_a"
    assert row.get("tags") == []
    assert "members" not in row


def test_digest_one_letter_room(cn, digest_office):
    out = rpc._h_rooms(digest_office["book"], {"digest": True}, "dg", "dg_a")
    by = {r["tree"]: r for r in _dg(out["rooms"])}
    row = by["dg-one"]
    assert row["size"] == 1
    assert row["root"] == "one letter first line"
    assert row["starter"] == "dg_a"
    assert row["created"]
    assert row["last_at"]
    assert int(row["breadth"]) >= 2
    assert row["tags"] == []
    assert "members" not in row
    assert "depth" not in row


def test_digest_first_line_cut_off(cn, digest_office):
    out = rpc._h_rooms(digest_office["book"], {"digest": True}, "dg", "dg_a")
    by = {r["tree"]: r for r in _dg(out["rooms"])}
    row = by["dg-cut"]
    assert len(row["root"]) == ROOM_ROOT_LINE_CAP
    assert row["root"] == ("x" * ROOM_ROOT_LINE_CAP)
    assert row["size"] == 2
    assert int(row["breadth"]) >= 2
    assert row["tags"] == []


def test_digest_hides_hex_plan_rooms(cn, digest_office):
    """Digest lists named rooms only; hex-minted plan rooms stay hidden."""
    book = digest_office["book"]
    direct = int(
        rpc._h_send(
            book, {"src": "dg_a", "dst": "dg_b", "body": "plain"}, "dg", "dg_a"
        )["id"]
    )
    reply = int(
        rpc._h_reply(
            book, {"mail_id": direct, "body": "opens hidden room"}, "dg", "dg_b"
        )["id"]
    )
    crumbs = __import__(
        "agent_coord.server.records.mail", fromlist=["tree_crumbs"]
    ).tree_crumbs(cn, reply)
    hidden = str(crumbs.get("tree") or "")
    assert rec_tree.is_hidden_tree(hidden)
    out = rpc._h_rooms(book, {"digest": True}, "dg", "dg_a")
    assert out.get("digest") is True
    names = {r["tree"] for r in out["rooms"]}
    assert hidden not in names
    assert "dg-one" in names


def test_digest_is_one_sql_query_no_members_walk(cn, digest_office, monkeypatch):
    calls = {"n": 0}
    real = rec_tree._room_member_names_by_root

    def boom(cn, root_id):  # noqa: ANN001
        calls["n"] += 1
        return real(cn, root_id)

    monkeypatch.setattr(rec_tree, "_room_member_names_by_root", boom)
    out = rpc._h_rooms(digest_office["book"], {"digest": True}, "dg", "dg_a")
    assert _dg(out["rooms"]), "expected digest rows"
    assert calls["n"] == 0, "digest must not walk members per room"


