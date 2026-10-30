"""Pass evidence is not written onto the card body (card 866). Row F143.

The server stores evidence. On today's book the client sends it and this
handler leaves the body alone.
"""
from __future__ import annotations

import json

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_pass_does_not_store_evidence_on_the_card_body(cn):
    seed_names(cn, ("unit", "roster"), ("a866", "desk"), ("v866", "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": "b866-b"}, "unit", "a866")
    rpc._h_claim(book, {"need": "b866-b"}, "unit", "v866")
    rpc._h_pass(book, {"need": "b866-b", "step": "ship", "evidence": "the log"}, "unit", "v866")
    raw = rec_todo.find(cn, "unit", "b866-b").get("body") or ""
    body = json.loads(raw) if raw else {}
    assert "evidence" not in body
    assert rec_todo.find(cn, "unit", "b866-b")["status"] == "shipped"


def _client_body(argv):
    """The request body the mill CLI sends for ARGV."""
    from agent_coord.__main__ import _build_parser
    from agent_coord.client.outbound import body_from_args

    return body_from_args(_build_parser().parse_args(argv))


def _read(cn, need):
    """The card as `mill todo unit NEED` shows it."""
    got = rpc._h_todo(_Book(cn), {"need": need}, "unit", "v866")
    return got[0] if isinstance(got, list) else got


def test_client_done_when_and_evidence_are_stored_by_the_server(cn):
    """The bodies the CLI sends reach the 0.7.18 store (card 867) and read back on the card."""
    seed_names(cn, ("unit", "roster"), ("a866", "desk"), ("v866", "desk"))
    book = _Book(cn)
    made = rpc._h_open(book, _client_body(["create", "todo", "unit", "b866-c", "--done-when", "CI green"]), "unit", "a866")
    assert made["done_when"] == "CI green"
    assert _read(cn, "b866-c")["done_when"] == "CI green"
    rpc._h_claim(book, {"need": "b866-c"}, "unit", "v866")
    got = rpc._h_pass(book, _client_body(["pass", "unit", "b866-c", "--evidence", "CI run 1 green"]), "unit", "v866")
    assert got["status"] == "shipped" and got["evidence"] == "CI run 1 green"
    assert _read(cn, "b866-c")["evidence"] == "CI run 1 green"
    raw = rec_todo.find(cn, "unit", "b866-c").get("body") or ""
    assert "CI run 1 green" not in raw and "CI green" not in raw
    cleared = rpc._h_note(book, _client_body(["note", "unit", "b866-c", "--done-when", ""]), "unit", "a866")
    assert cleared["done_when"] is None
    assert "done_when" not in _read(cn, "b866-c")
