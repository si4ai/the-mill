# -*- coding: utf-8 -*-
"""reply --to-desk SELF: refused with the working form, nothing written (F80)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _room(cn, tag: str) -> tuple[_Book, int]:
    seed_names(cn, ("unit", "roster"), (tag + "a", "desk"), (tag + "b", "desk"))
    book = _Book(cn)
    root = rpc._h_send(
        book,
        {"project": "unit", "src": tag + "a", "dst": tag + "b", "body": "root", "name": tag + "-room"},
        "unit",
        tag + "a",
    )
    return book, int(root["id"])


def _letters(cn) -> int:
    return int(scalar(cn, "SELECT COUNT(*) FROM mail") or 0)


def test_to_desk_self_names_the_working_form(cn) -> None:
    book, rid = _room(cn, "sf")
    before = _letters(cn)
    with pytest.raises(CoordError) as ei:
        rpc._h_reply(book, {"mail_id": rid, "body": "quiet", "src": "sfb", "mail_tos": ["sfb"]}, "unit", "sfb")
    msg = str(ei.value)
    assert "reply-all default" not in msg
    assert "--to-desk names only you" in msg
    assert f"mill reply {rid} --body-file PATH" in msg
    assert "mill replace-body todo ID TEXT" in msg
    assert "mill note" not in msg
    assert _letters(cn) == before


def test_to_desk_self_and_another_reaches_the_other(cn) -> None:
    book, rid = _room(cn, "so")
    rec = rpc._h_reply(
        book, {"mail_id": rid, "body": "both", "src": "sob", "mail_tos": ["sob", "soa"]}, "unit", "sob"
    )
    assert [t["deskId"] for t in rec["mail_tos"]] == ["soa"]


def test_alone_in_reply_all_names_to_desk(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("ln", "desk"))
    book = _Book(cn)
    root = rpc._h_send(book, {"project": "unit", "src": "ln", "dst": "ln", "body": "self"}, "unit", "ln")
    with pytest.raises(CoordError) as ei:
        rpc._h_reply(book, {"mail_id": int(root["id"]), "body": "again", "src": "ln"}, "unit", "ln")
    msg = str(ei.value)
    assert "you are the only desk on it" in msg
    assert "--to-desk DESK" in msg
