"""retire/rename/reclaim act on the name type the CLI names (#537). Regression row F60 (name-type).

A desk-focus label shares its name with the desk. The wall used to look the
type up by name alone with a one-row read, which failed ("Unread result
found") or could pick the wrong type.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.admin import catalog


def _rows(types):
    return lambda cn, sql, args=(): [{"type": t} for t in types]


@pytest.fixture(autouse=True)
def _admin():
    with patch("agent_coord.server.admin.catalog.require_admin", lambda cn, desk: None):
        yield


@pytest.mark.parametrize("command,body,call", [
    ("retire", {"slug": "d1", "confirm": "d1", "yes": True}, "retire"),
    ("reclaim", {"slug": "d1", "confirm": "d1", "yes": True}, "reclaim"),
    ("rename", {"old": "d1", "new": "d2", "confirm": "d2", "yes": True}, "rename"),
])
def test_the_named_type_is_used_without_a_lookup(command, body, call):
    seen = {}

    def fake(cn, *a, **kw):
        seen["args"] = a
        return [{"ok": 1}]

    with patch(f"agent_coord.server.records.name.{call}", fake), \
            patch("agent_coord.server.records.db.rows_done", side_effect=AssertionError("no lookup")):
        getattr(catalog, command)(object(), "admin-desk", dict(body, name_type="label"))
    assert seen["args"][-1] == "label"


def test_a_shared_name_without_a_type_is_refused_naming_both():
    with patch("agent_coord.server.records.db.rows_done", _rows(["desk", "label"])):
        with pytest.raises(CoordError) as e:
            catalog.retire(object(), "admin-desk", {"slug": "d1", "confirm": "d1", "yes": True})
    msg = str(e.value)
    assert "desk" in msg and "label" in msg and "mill retire label d1" in msg


def test_one_live_type_still_works_without_a_type():
    seen = {}
    with patch("agent_coord.server.records.db.rows_done", _rows(["roster"])), \
            patch("agent_coord.server.records.name.retire", lambda cn, n, k="", **kw: seen.setdefault("k", k) and []):
        catalog.retire(object(), "admin-desk", {"slug": "r1", "confirm": "r1", "yes": True})
    assert seen["k"] == "roster"


def test_unknown_name_and_bad_type_are_refused():
    with patch("agent_coord.server.records.db.rows_done", _rows([])):
        with pytest.raises(CoordError, match="not in the name table"):
            catalog.retire(object(), "admin-desk", {"slug": "nope", "confirm": "nope", "yes": True})
    with pytest.raises(CoordError, match="name type"):
        catalog.retire(object(), "admin-desk", {"slug": "x", "confirm": "x", "yes": True, "name_type": "score"})


@pytest.mark.parametrize("argv,kind", [
    (["retire", "label", "d1", "--yes"], "label"),
    (["retire", "roster", "r1", "--yes"], "roster"),
    (["rename", "label", "a", "b", "--yes"], "label"),
    (["reclaim", "label", "d1", "--yes"], "label"),
])
def test_the_cli_sends_the_type(argv, kind, monkeypatch):
    from agent_coord.__main__ import _build_parser
    from agent_coord.client import language
    from agent_coord.client.outbound import body_from_args

    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *a, **k: "admin-desk")
    args = _build_parser().parse_args(argv)
    args = language.translate(args)
    body = body_from_args(args)
    assert body.get("name_type") == kind
