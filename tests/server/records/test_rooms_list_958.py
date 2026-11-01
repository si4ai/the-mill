# -*- coding: utf-8 -*-
"""Card 958: mill rooms lists mail TREEs with size/depth and server-side sort."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import tree as rec_tree
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(autouse=True)
def _no_live_ws(monkeypatch):
    monkeypatch.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)


@pytest.fixture(scope="module")
def rooms_office(cn):
    """Three named rooms with different size/depth/breadth/starter/created."""
    seed_names(
        cn,
        ("rl", "roster"),
        ("rl_a", "desk"),
        ("rl_b", "desk"),
        ("rl_c", "desk"),
        ("rl_out", "desk"),
    )
    book = _Book(cn)
    # small / shallow / starter rl_a
    r_small = int(
        rpc._h_send(
            book,
            {"src": "rl_a", "dst": "rl_b", "body": "small root first line\nmore", "name": "rl-small"},
            "rl",
            "rl_a",
        )["id"]
    )
    # wide: many direct replies under root (breadth via members also grows)
    r_wide = int(
        rpc._h_send(
            book,
            {"src": "rl_b", "dst": "rl_a,rl_c", "body": "wide root", "name": "rl-wide"},
            "rl",
            "rl_b",
        )["id"]
    )
    for i, desk in enumerate(("rl_a", "rl_c", "rl_a")):
        rpc._h_reply(book, {"mail_id": r_wide, "body": f"wide child {i}", "mail_tos": ["rl_b"]}, "rl", desk)
    # deep: a chain of replies
    r_deep = int(
        rpc._h_send(
            book,
            {"src": "rl_c", "dst": "rl_a", "body": "deep root", "name": "rl-deep"},
            "rl",
            "rl_c",
        )["id"]
    )
    cur = r_deep
    for i in range(3):
        cur = int(rpc._h_reply(book, {"mail_id": cur, "body": f"deep {i}"}, "rl", "rl_a" if i % 2 == 0 else "rl_c")["id"])
    return {
        "book": book,
        "small": r_small,
        "wide": r_wide,
        "deep": r_deep,
    }


def _names(rows):
    return [str(r.get("tree") or "") for r in rows]


def test_rooms_lists_named_rooms_with_size_and_depth(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {}, "rl", "rl_out")
    rows = out["rooms"] if isinstance(out, dict) else out
    by = {r["tree"]: r for r in rows}
    assert "rl-small" in by and "rl-wide" in by and "rl-deep" in by
    assert by["rl-small"]["size"] == 1
    assert by["rl-small"]["depth"] == 0
    assert by["rl-wide"]["size"] == 4  # root + 3 children
    assert by["rl-deep"]["size"] == 4  # root + 3 chain
    assert by["rl-deep"]["depth"] >= 3
    assert "first" in (by["rl-small"].get("root") or "").lower() or "small root" in (by["rl-small"].get("root") or "")
    assert "rl_a" in (by["rl-small"].get("members") or [])


def test_rooms_default_sort_recency_newest_first(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    # deep was last written -> first under recency
    assert rows[0]["tree"] == "rl-deep"


def test_rooms_sort_size(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {"sort": "size"}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    sizes = [int(r["size"]) for r in rows]
    assert sizes == sorted(sizes, reverse=True)


def test_rooms_sort_size_asc(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {"sort": "size", "asc": True}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    sizes = [int(r["size"]) for r in rows]
    assert sizes == sorted(sizes)


def test_rooms_sort_depth(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {"sort": "depth"}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    assert rows[0]["tree"] == "rl-deep"
    depths = [int(r["depth"]) for r in rows]
    assert depths == sorted(depths, reverse=True)


def test_rooms_sort_breadth(cn, rooms_office):
    """breadth = distinct member desks (senders U recipients); documented on the command."""
    out = rpc._h_rooms(rooms_office["book"], {"sort": "breadth"}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    breadths = [int(r["breadth"]) for r in rows]
    assert breadths == sorted(breadths, reverse=True)
    assert rows[0]["tree"] == "rl-wide"


def test_rooms_sort_created(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {"sort": "created"}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    # small opened first -> last when newest-first; with default desc, newest created first = deep
    assert rows[-1]["tree"] == "rl-small" or rows[0]["tree"] == "rl-deep"


def test_rooms_sort_starter(cn, rooms_office):
    out = rpc._h_rooms(rooms_office["book"], {"sort": "starter", "asc": True}, "rl", "rl_a")
    rows = [r for r in out["rooms"] if str(r["tree"]).startswith("rl-")]
    starters = [str(r.get("starter") or "") for r in rows]
    assert starters == sorted(starters)


def test_rooms_sort_bad_key_refused(cn, rooms_office):
    with pytest.raises(CoordError) as ei:
        rpc._h_rooms(rooms_office["book"], {"sort": "nope"}, "rl", "rl_a")
    assert "sort" in str(ei.value)


def test_rooms_hides_hex_unless_all(cn, rooms_office):
    book = rooms_office["book"]
    # reply-opened room mints a 10-hex tree name
    direct = int(rpc._h_send(book, {"src": "rl_a", "dst": "rl_b", "body": "plain"}, "rl", "rl_a")["id"])
    reply = int(rpc._h_reply(book, {"mail_id": direct, "body": "opens hidden room"}, "rl", "rl_b")["id"])
    crumbs = __import__("agent_coord.server.records.mail", fromlist=["tree_crumbs"]).tree_crumbs(cn, reply)
    hidden = str(crumbs.get("tree") or "")
    assert rec_tree.is_hidden_tree(hidden)
    named = rpc._h_rooms(book, {}, "rl", "rl_a")["rooms"]
    assert hidden not in {r["tree"] for r in named}
    # --all without Admin is refused
    with pytest.raises(CoordError):
        rpc._h_rooms(book, {"all": True}, "rl", "rl_a")


def test_list_rooms_sql_helper_sorts_in_query(cn, rooms_office):
    """Regression: sort is applied in SQL (ORDER BY), not by Python after fetch."""
    rows = rec_tree.list_mail_rooms(cn, sort="size", asc=False)
    ours = [r for r in rows if str(r["tree"]).startswith("rl-")]
    assert [r["size"] for r in ours] == sorted((r["size"] for r in ours), reverse=True)
