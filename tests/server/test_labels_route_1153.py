"""Card 1153: GET /api/v1/labels for the Wall PRIORITIES tab, and label.updated.

GET /api/v1/labels?project=Office[&names=a,b][&limit=][&cursor=] answers
{rows, next, checks}: label, type, id, ord, updated and, for a todo, card
{roster, need, status, volunteer, eta_at?, progress?, last_activity_at?,
last_activity_kind?, off_roster?}. tw_ms and needs_human are not served.
label.updated is when ord was last set: attach or a re-rank to a new ord.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROW_KEYS = {"label", "type", "id", "ord", "updated"}
CARD_KEYS = {"roster", "need", "status", "volunteer"}
OPTIONAL = {"eta_at", "progress", "last_activity_at", "last_activity_kind", "off_roster"}


class _Office:
    def __init__(self, cn=None):
        self._cn = cn
        self._tokens: dict = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client(monkeypatch, cn=None) -> TestClient:
    import agent_coord.server.middleware as mw
    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(mw, "_office", lambda **k: _Office(cn))
    root = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))


@pytest.mark.parametrize("url,word", [
    ("/api/v1/labels", "project=Office"),
    ("/api/v1/labels?project=the-mill", "project=Office"),
    ("/api/v1/labels?project=Office&role=x", "project=Office"),
    ("/api/v1/labels?project=Office&names=a,b%20c", "names"),
])
def test_refusals_are_400_and_never_read_the_book(monkeypatch, url, word) -> None:
    def boom(*a, **k):
        raise AssertionError("a refused read must not query the book")

    monkeypatch.setattr("agent_coord.server.records.label.wall_rows", boom)
    r = _client(monkeypatch).get(url)
    assert r.status_code == 400, r.text
    assert word in r.json()["error"]


def test_shape_paging_names_and_checks(monkeypatch) -> None:
    seen: list = []
    canned = [
        {"label": "builder", "type": "todo", "id": 7, "ord": 0, "updated": "2026-11-11 09:00:00.000000",
         "card": {"roster": "the-mill", "need": "x", "status": "open", "volunteer": "", "off_roster": True}},
        {"label": "builder", "type": "mail", "id": 9, "ord": 3, "updated": "2026-11-11 10:00:00.000000"},
    ]

    def fake(cn, names):
        seen.append(names)
        return [dict(r) for r in canned]

    monkeypatch.setattr("agent_coord.server.records.label.wall_rows", fake)
    client = _client(monkeypatch)
    body = client.get("/api/v1/labels?project=Office&limit=1").json()
    assert seen[-1] is None
    assert body["project"] == "Office" and body["parts"] == ["labels"]
    assert len(body["rows"]) == 1 and body["next"] == "builder|todo|7"
    assert body["checks"] == {"off_roster": [{"label": "builder", "id": 7, "roster": "the-mill"}]}
    rest = client.get("/api/v1/labels?project=Office&limit=1&cursor=" + body["next"]).json()
    assert [r["id"] for r in rest["rows"]] == [9] and rest["next"] is None
    client.get("/api/v1/labels?project=Office&names=builder,human-priorities")
    assert seen[-1] == ["builder", "human-priorities"]


# --- seeded book ---------------------------------------------------------


def _exec(cn, sql: str, args: tuple = ()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()
    cn.commit()


def _one(cn, sql: str, args: tuple = ()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchone()
    finally:
        cur.close()


@pytest.fixture
def book(cn):
    from agent_coord.server.records import label as rec_label
    from agent_coord.server.records import member as rec_member
    from agent_coord.server.records import todo as rec_todo
    from tests.server.records.conftest import seed_names

    tag = uuid4().hex[:6]
    desk, home, away = f"d1153{tag}", f"r1153{tag}", f"x1153{tag}"
    seed_names(cn, (home, "roster"), (away, "roster"), (desk, "desk"), (desk, "label"),
               ("human-priorities", "label"), (f"misc{tag}", "label"))
    rec_member.put(cn, home, desk)
    on_home = int(rec_todo.insert(cn, home, desk, "open", "on a member roster")[0]["id"])
    off_home = int(rec_todo.insert(cn, away, desk, "parked", "on another roster")[0]["id"])
    rec_label.put(cn, "todo", on_home, desk, 5)
    rec_label.put(cn, "todo", off_home, desk, 0)
    rec_label.put(cn, "todo", on_home, "human-priorities", 0)
    rec_label.put(cn, "todo", on_home, f"misc{tag}", 1)
    cn.commit()
    return {"desk": desk, "home": home, "away": away, "on": on_home, "off": off_home, "misc": f"misc{tag}"}


@pytest.mark.sql
def test_seeded_rows_cards_and_off_roster_check(cn, book) -> None:
    from agent_coord.server.records import label as rec_label

    rows = [r for r in rec_label.wall_rows(cn) if r["id"] in (book["on"], book["off"])]
    assert {r["label"] for r in rows} == {book["desk"], "human-priorities"}  # misc is not a desk list
    mine = [r for r in rows if r["label"] == book["desk"]]
    assert [(r["id"], r["ord"]) for r in mine] == [(book["off"], 0), (book["on"], 5)]
    for r in rows:
        assert set(r) == ROW_KEYS | {"card"} and r["updated"]
        assert CARD_KEYS <= set(r["card"]) <= CARD_KEYS | OPTIONAL
        assert "tw_ms" not in r["card"] and "needs_human" not in r["card"]
    on, off = mine[1]["card"], mine[0]["card"]
    assert (on["roster"], on["status"], on["volunteer"]) == (book["home"], "open", "")
    assert (off["roster"], off["status"]) == (book["away"], "parked")
    assert off.get("off_roster") is True and "off_roster" not in on
    picked = rec_label.wall_rows(cn, [book["misc"]])
    assert [r["id"] for r in picked] == [book["on"]]


@pytest.mark.sql
def test_seeded_last_activity_kind_from_the_card_move(cn, book) -> None:
    from agent_coord.server.records import label as rec_label

    def card():
        return [r for r in rec_label.wall_rows(cn, [book["desk"]]) if r["id"] == book["on"]][0]["card"]

    assert "last_activity_kind" not in card()  # create is not one of claim, note, pass, letter, tw
    _exec(cn, "UPDATE activity SET act = 'claim' WHERE type = 'todo' AND id = %s", (book["on"],))
    assert card()["last_activity_kind"] == "claim" and card()["last_activity_at"]
    _exec(cn, "UPDATE activity SET act = 'ship' WHERE type = 'todo' AND id = %s", (book["on"],))
    assert card()["last_activity_kind"] == "pass"


@pytest.mark.sql
def test_rerank_moves_updated_and_same_ord_does_not(cn, book) -> None:
    from agent_coord.server.records import label as rec_label

    old = "2026-01-01 00:00:00.000000"
    where = ("FROM label l JOIN name n ON n.id = l.name_id"
             " WHERE l.type = 'todo' AND l.id = %s AND n.name = %s")
    _exec(cn, "UPDATE label l JOIN name n ON n.id = l.name_id SET l.updated = %s"
              " WHERE l.type = 'todo' AND l.id = %s AND n.name = %s", (old, book["on"], book["desk"]))

    def stamp() -> str:
        return str(_one(cn, "SELECT l.updated " + where, (book["on"], book["desk"]))[0])

    rec_label.put(cn, "todo", book["on"], book["desk"], 5)
    rec_label.put(cn, "todo", book["on"], book["desk"], None)
    cn.commit()
    assert stamp().startswith("2026-01-01")
    rec_label.put(cn, "todo", book["on"], book["desk"], 2)
    cn.commit()
    assert not stamp().startswith("2026-01-01")


@pytest.mark.sql
def test_existing_book_gains_label_updated_from_created(cn, book) -> None:
    from agent_coord.install import migrate

    try:
        _exec(cn, "ALTER TABLE label DROP COLUMN updated")
        assert migrate._ensure_label_updated(cn) == ["label.updated"]
        assert migrate._ensure_label_updated(cn) == []
        assert _one(cn, "SELECT COUNT(*) FROM label WHERE updated <> created")[0] == 0
    finally:
        cur = cn.cursor()
        try:
            if not migrate._column_exists(cur, "label", "updated"):
                cur.execute("ALTER TABLE label ADD COLUMN updated DATETIME(6) NOT NULL"
                            " DEFAULT CURRENT_TIMESTAMP(6) AFTER created")
        finally:
            cur.close()
        cn.commit()


@pytest.mark.sql
def test_seeded_route_over_http(cn, book, monkeypatch) -> None:
    body = _client(monkeypatch, cn).get("/api/v1/labels?project=Office&limit=500").json()
    ids = {(r["label"], r["id"]) for r in body["rows"]}
    assert {(book["desk"], book["on"]), (book["desk"], book["off"]), ("human-priorities", book["on"])} <= ids
    assert {"label": book["desk"], "id": book["off"], "roster": book["away"]} in body["checks"]["off_roster"]
