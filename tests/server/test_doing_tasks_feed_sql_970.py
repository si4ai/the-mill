"""Card 970 / card 1207: a desk's live doings are its tw runs (the wall-ui shape)."""
from types import SimpleNamespace

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join, todo
from agent_coord.server.records.db import call, rows_done
from tests import sql_book

pytestmark = pytest.mark.sql

ROW = {"id", "created", "text", "state", "state_at", "card"}


@pytest.fixture
def feed(cn, monkeypatch):
    # cn is module-scoped; start each test from an empty book so one test's tasks never leak into the next.
    sql_book.reset_data(cn)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    join.upsert(cn, "Office", "Builder", "", "a" * 64)
    book = SimpleNamespace(_cn=cn)

    def event(wid, kind, **kw):
        return rpc._h_tw_event(book, {"watch_id": wid, "kind": kind, **kw}, "Office", "Builder")

    def read():
        return rpc._h_session(book, {"desk": "Builder", "all": True}, "", None)[0]

    return event, read


def test_live_runs_newest_first_with_state_and_no_card_link(cn, feed):
    event, read = feed
    card = todo.insert(cn, "Office", "Builder", body="card for feed")[0]["id"]
    assert event("a", "start", card=card)["ok"]
    assert event("b", "start")["ok"]
    assert event("a", "stall", cause="quiet")["ok"]
    view = read()
    assert view["n"] == 2 and len(view["doings"]) == 2
    assert all(set(r) == ROW for r in view["doings"])
    by_state = {r["state"] for r in view["doings"]}
    assert by_state == {"waiting", "active"}
    assert [r["id"] for r in view["doings"]] == sorted((r["id"] for r in view["doings"]), reverse=True)
    assert all(r["created"].endswith("Z") and r["state_at"].endswith("Z") for r in view["doings"])
    assert all(r["card"] is None and r["text"] == "" for r in view["doings"])
    assert "doing" not in view and "tasks" not in view and "waiting_on_it" not in view


@pytest.mark.parametrize("state", ["finished", "failed", "stale", "cleared"])
def test_terminal_run_is_not_listed(cn, feed, state):
    event, read = feed
    assert event("a", "start")["ok"]
    rows_done(cn, "UPDATE transition SET to_state=%s WHERE join_key=%s", (state, "task:Builder:a"))
    assert read()["doings"] == [] and read()["n"] == 0


def test_list_caps_at_twenty_and_n_is_the_true_count(cn, feed):
    _, read = feed
    for i in range(23):
        call(cn, "mill_doing_task", ["Builder", f"task:Builder:w{i}", None, 1])
    join.upsert(cn, "Office", "Validator", "", "b" * 64)
    call(cn, "mill_doing_task", ["Validator", "task:Validator:a", None, 1])
    views = {v["owner"]: v for v in rpc._h_session(SimpleNamespace(_cn=cn), {"all": True}, "", None)}
    assert views["Builder"]["n"] == 23 and len(views["Builder"]["doings"]) == doing.DOINGS_CAP == 20
    # A run born with no transition yet reads as started, at its created time.
    assert views["Validator"]["n"] == 1
    only = views["Validator"]["doings"][0]
    assert only["state"] == "started" and only["state_at"] == only["created"]
    assert read()["n"] == 23
