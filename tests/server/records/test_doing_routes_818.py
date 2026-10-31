"""#818 PR B: the Wall's two read-only doing routes (PR C reads them), on a real book. Row F118.

GET /api/v1/doing?all=1 | ?desk=D | ?project=R   the `mill connected` desk views (a list)
GET /api/v1/doing/history?desk=D | ?on=ITEM       the `--history` page {history, page}, ended_by

Same door as every other Wall GET (a refused door never reads the book), one
book per wall (middleware._office). Also: `last` carries ended_by, and cards
no longer carry the title-era `doing` key.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_coord.server.records.db import scalar_done
from tests.server.records.test_doing_flag_818 import ME, PEER, R, World, _hist, _joined, w  # noqa: F401

pytestmark = pytest.mark.sql


class _Office:
    def __init__(self, cn, seen: list):
        self._cn = cn
        self._tokens: dict = {}
        seen.append(1)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def wall(w, monkeypatch):
    """The real Wall app (uvicorn's handler) with an open door, reading w's book."""
    import agent_coord.server.middleware as mw
    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    opened: list = []
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(mw, "_office", lambda **k: _Office(w.cn, opened))
    root = Path(__file__).resolve().parents[3]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    client.opened = opened
    return client


def _get(wall, url: str):
    """Status and body; a list reply comes wrapped as {"result": [...], "mill": ver} like every Wall GET."""
    r = wall.get(url, headers={"Accept": "application/json"})
    if not r.headers.get("content-type", "").startswith("application/json"):
        return r.status_code, r.text
    got = r.json()
    if isinstance(got, dict):
        got.pop("mill", None)
        if set(got) == {"result"}:
            got = got["result"]
    return r.status_code, got


def test_doing_all_is_the_connected_view(w, wall):
    mid = w.letter()
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "on the route"])
    code, got = _get(wall, "/api/v1/doing?all=1")
    assert code == 200 and isinstance(got, list), got
    mine = [d for d in got if d["owner"] == ME]
    assert len(mine) == 1
    view = mine[0]
    assert view["doing"] == "on the route" and view["on"] == f"mail-{mid}"
    assert set(view) >= {"owner", "alive", "stale", "doing", "on", "age", "waiting_on_it", "line"}
    # asked (#160) and claimed_at (#161) are checked in test_mail_asked_818 and test_todo_claimed_at_818.


def test_doing_one_desk_or_one_roster(w, wall):
    code, got = _get(wall, f"/api/v1/doing?desk={ME}")
    assert code == 200 and [d["owner"] for d in got] == [ME]
    code, got = _get(wall, f"/api/v1/doing?project={R}")
    assert code == 200 and {ME, PEER} <= {d["owner"] for d in got}
    assert all(d.get("project_id") == R for d in got)


def test_doing_needs_one_scope_and_refuses_unknowns(wall):
    code, got = _get(wall, "/api/v1/doing")
    assert code == 400 and "all=1" in got["error"]
    code, got = _get(wall, "/api/v1/doing?all=1&desk=x")
    assert code == 400
    code, got = _get(wall, "/api/v1/doing?desk=d818-nobody")
    assert code == 400 and "no desk" in got["error"]
    code, got = _get(wall, "/api/v1/doing?project=r818-nothing")
    assert code == 400


def test_history_by_desk_has_ended_by(w, wall):
    mid, mid2 = w.letter(), w.letter()
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "first"])
    w.ok(["reply", str(mid2), "--body-file", str(w.body), "--doing", "second"])
    code, got = _get(wall, f"/api/v1/doing/history?desk={ME}")
    assert code == 200 and set(got) == {"history", "page"}
    assert got["history"] == _hist(w, ME)[: len(got["history"])]
    first = [e for e in got["history"] if e["doing"] == "first"][0]
    assert first["ended_by"] == "newer" and all("ended_by" in e for e in got["history"])
    assert got["page"]["n"] == 1


def test_history_on_one_card_without_a_desk(w, wall):
    """A card trail: every desk's doing rows on that card, newest first, nobody else's.

    Card 901 / F213: at least one move row is present (act not focus/clear/finish;
    evidence when ship/done), not only that focus rows survive.
    """
    need, tid = w.card()
    w.ok(["claim", R, need, "--doing", "mine on the card"])
    w.ok(["note", R, need, "--note", "peer looks", "--doing", "peer on the card"], desk=PEER)
    mid = w.letter()
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "not the card"])
    w.ok(["pass", R, need, "--evidence", "shipped for 901", "--doing", "closing"])
    code, got = _get(wall, f"/api/v1/doing/history?on=todo-{tid}")
    assert code == 200, got
    rows = got["history"]
    # Focus entries that name the two desks' --doing text (F188 keeps them).
    named = {(e["desk"], e["doing"]) for e in rows if e.get("doing") in ("peer on the card", "mine on the card")}
    assert named == {(PEER, "peer on the card"), (ME, "mine on the card")}
    assert {e["on"] for e in rows} == {f"todo-{tid}"}
    moves = [e for e in rows if e.get("act") not in (None, "focus", "clear", "finish")]
    assert moves, rows
    ship = [e for e in moves if e.get("act") == "ship"]
    assert ship and ship[0].get("evidence") == "shipped for 901", ship
    mine = [e for e in rows if e["desk"] == ME and e.get("doing") == "mine on the card"][0]
    assert mine["ended_by"] in ("newer", "finished")
    assert got["page"]["entries"] >= 2
    code, got = _get(wall, f"/api/v1/doing/history?on=todo-{tid}&desk={PEER}")
    assert code == 200 and got["history"] and {e["desk"] for e in got["history"]} == {PEER}


def test_history_on_hold_includes_move_rows(w, wall):
    """Card 901 / F213: GET /api/v1/doing/history?on=hold-N returns take/drop moves with act."""
    res = w.ok(["hold", "h901/lock"])
    hid = int(res["id"])
    w.ok(["drop", "h901/lock"])
    code, got = _get(wall, f"/api/v1/doing/history?on=hold-{hid}")
    assert code == 200, got
    rows = got["history"]
    assert {e["on"] for e in rows} == {f"hold-{hid}"}
    acts = [e.get("act") for e in rows]
    assert "hold" in acts and "drop" in acts, acts


def test_history_needs_a_desk_or_an_item(wall):
    code, got = _get(wall, "/api/v1/doing/history")
    assert code == 400 and "desk=" in got["error"] and "on=" in got["error"]
    for bad in ("todo", "card-3", "todo-x", "todo-0", "join-4"):
        code, got = _get(wall, f"/api/v1/doing/history?on={bad}")
        assert code == 400, (bad, got)
    code, got = _get(wall, f"/api/v1/doing/history?desk={ME}&page=0")
    assert code == 400


def test_a_refused_door_never_reads_the_book(w, wall, monkeypatch):
    """Same door as /api/v1/agents: the invite door with no key answers the same
    way for the doing routes, and the book is never opened."""
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "invite")
    monkeypatch.setattr("agent_coord.server.admin.door.check", lambda token: False)
    base, _ = _get(wall, f"/api/v1/agents?project={R}")
    assert base != 200
    for url in ("/api/v1/doing?all=1", f"/api/v1/doing/history?desk={ME}", "/api/v1/doing/history?on=todo-1"):
        code, _ = _get(wall, url)
        assert code == base, url
    assert wall.opened == []


def test_last_says_how_it_ended(w):
    from agent_coord.server.records import join as here

    desk = _joined(w, "d818-last-" + uuid.uuid4().hex[:4])
    mid = w.letter(to=desk)
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "answering"], desk=desk)
    w.ok(["reply", str(mid), "--body-file", str(w.body)], desk=desk)
    view = w.me(desk)
    assert view["doing"] == "" and view["last"]["doing"] == "answering"
    assert view["last"]["ended_by"] == "finished"
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "again"], desk=desk)
    here.reset(w.cn, R, desk)
    assert w.me(desk)["last"]["ended_by"] == "cleared"


def test_cards_carry_no_doing_key(w):
    """The title-era card `doing` key is gone from every card shape; a legacy
    stored one is still shown as the head of detail."""
    from agent_coord.server.records import floor
    from agent_coord.server.records.todo import unpack

    assert "doing" not in unpack(json.dumps({"slug": "s", "doing": "old", "detail": "d"}), 1)
    need, tid = w.card()
    cur = w.cn.cursor()
    cur.execute("UPDATE todo SET body = %s WHERE id = %s",
                (json.dumps({"slug": need, "doing": "old title", "detail": "card for #818"}), tid))
    cur.close()
    w.cn.commit()
    one = floor.v1_todo(w.cn, tid)["todo"]
    assert "doing" not in one and one["detail"].startswith("old title")
    needs, issues = floor.build_todos(w.cn, [R])
    card = [c for c in needs + issues if int(c["id"]) == tid][0]
    assert "doing" not in card and "doing_trunc" not in card and card["detail"].startswith("old title")
    board = floor.floor(w.cn, project=R, parts=["todos"])
    card = [c for c in board.get("needs", []) + board.get("issues", []) if int(c["id"]) == tid][0]
    assert "doing" not in card and "doing_trunc" not in card
    assert scalar_done(w.cn, "SELECT COUNT(*) FROM todo WHERE id = %s", (tid,)) == 1


# Validator 2595: a bad page= was a 500. Every query parameter on both routes,
# whatever it holds, is a 200 or a 400, never a 500.

@pytest.mark.parametrize("page", [
    "%C2%B2",        # superscript two: str.isdigit() says yes, int() says no
    "%EF%BC%91",     # full-width one: int() reads it as 1
    "99999999999",   # over the book's INT
    "2147483647",    # (page - 1) * 50 overflows the offset
    "100001",        # over the page bound
    "1.5", "%2B2", "0x2", "-1", "0", "",  # (a space, + in a query, is stripped like on every parameter)
])
def test_a_bad_history_page_is_a_400(wall, page):
    code, got = _get(wall, f"/api/v1/doing/history?desk={ME}&page={page}")
    if page == "":
        assert code == 200  # an empty page= is page 1, like no page=
        return
    assert code == 400 and "page=" in got["error"] and "1 to 100000" in got["error"], (page, code, got)


LONG = "x" * 300


@pytest.mark.parametrize("query,want", [
    (f"/api/v1/doing/history?desk={ME}&since=junk", 400),
    (f"/api/v1/doing/history?desk={ME}&since=2026-10-23+25:00", 400),
    (f"/api/v1/doing/history?desk={ME}&since=%EF%BC%92026-10-23", 400),
    (f"/api/v1/doing/history?desk={ME}&since=" + "2" * 5000, 400),
    (f"/api/v1/doing/history?desk={ME}&since=0001-01-01", 200),
    (f"/api/v1/doing/history?desk={ME}&since=9999-12-31T23:59:59.999999", 200),
    ("/api/v1/doing/history?desk=" + LONG, 400),
    ("/api/v1/doing/history?desk=%00", 400),
    ("/api/v1/doing/history?desk=%F0%9F%98%80", 400),
    ("/api/v1/doing/history?desk=%FF%FE", 400),
    ("/api/v1/doing?desk=" + LONG, 400),
    ("/api/v1/doing?desk=%F0%9F%98%80", 400),
    ("/api/v1/doing?project=" + LONG, 400),
    ("/api/v1/doing?project=%00", 400),
    ("/api/v1/doing?project=%F0%9F%98%80", 400),
    ("/api/v1/doing?all=2", 400),
    ("/api/v1/doing?all=%C2%B2", 400),
    ("/api/v1/doing?all=" + LONG, 400),
    ("/api/v1/doing/history?on=todo-9999999999999999999", 200),
    ("/api/v1/doing/history?on=todo-99999999999999999999", 400),
    ("/api/v1/doing/history?on=todo-%C2%B2", 400),
    ("/api/v1/doing/history?on=TODO-1", 400),
    ("/api/v1/doing/history?on=" + LONG, 400),
    ("/api/v1/doing/history?on=todo-1&desk=" + LONG, 400),
])
def test_no_query_parameter_is_a_500(wall, query, want):
    code, got = _get(wall, query)
    assert code == want, (query[:80], code, got)
    if code == 400:
        assert isinstance(got, dict) and got.get("error") and "mill API error" not in got["error"]


def test_the_cli_page_bound_matches_the_route(w):
    """The same overflow on `mill connected --history --page` (older than the routes)."""
    code, out, err = w.run(["connected", "--history", "--desk", ME, "--page", "99999999999"])
    txt = err + out
    assert code != 0 and "--page" in txt and "1 to 100000" in txt, txt


@pytest.mark.parametrize("page", ["x", "²", "１", "-3", 2.5, True, 10**12])
def test_a_crafted_rpc_page_is_refused_not_crashed(w, page):
    """A client that sends page as anything but a small int gets a refusal."""
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server.api.mill import rpc

    for body in ({"history": True, "desk": ME, "page": page}, {"desk": ME, "page": page}):
        with pytest.raises(CoordError) as got:
            rpc._h_session(w.book, dict(body), "", ME)
        assert "--page" in str(got.value) and "1 to 100000" in str(got.value), (page, body, str(got.value))
