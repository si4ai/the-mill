"""Card 1193: the Wall left-pane scope on every list route the six tabs read.

?desks=d1,d2 narrows rows to the selected desks, ?window=1d|7d|30d cuts rows on
each type's own clock (omit = all), doing / labels / activity-buckets / score-runs
take a comma ?project= list, and GET /api/pov?part=rosters names each roster's
member desks. A refusal is 400 {"error"}. The route checks run without a book;
the seeded cases at the bottom read a real one.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_coord.server.records import floor, wall_scope
from agent_coord.server.records.wall_scope import ScopeError, WallScope, parse_scope

NOW = datetime.now()
FRESH = NOW - timedelta(hours=2)
WEEK = NOW - timedelta(days=3)
OLD = NOW - timedelta(days=40)


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
    monkeypatch.setattr("agent_coord.server.middleware.cached_read", lambda key, produce, **k: (produce(), False))
    monkeypatch.setattr(floor, "_projects_part_fp", lambda *a, **k: "")
    root = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))


# --- the parse -------------------------------------------------------------


def test_parse_scope_desks_and_window() -> None:
    now = datetime(2026, 11, 12, 12, 0, 0)
    assert parse_scope({}) == WallScope()
    assert not parse_scope({}).active
    got = parse_scope({"desks": ["builder,Wall-UI", "grok-tui"], "window": ["7d"]}, now=now)
    assert got.desks == frozenset({"builder", "wall-ui", "grok-tui"})
    assert got.window == "7d" and got.since == now - timedelta(days=7)
    assert parse_scope({"window": ["1d"]}, now=now).since == now - timedelta(days=1)
    assert parse_scope({"window": ["30d"]}, now=now).since == now - timedelta(days=30)
    assert parse_scope({"window": ["1w"]}, now=now).since == now - timedelta(days=7)


@pytest.mark.parametrize("qs", [
    {"window": ["2d"]},
    {"window": ["24h"]},
    {"desks": [","]},
    {"desks": ["bad name"]},
    {"desks": [",".join(f"d{i}" for i in range(101))]},
])
def test_parse_scope_refusals(qs) -> None:
    with pytest.raises(ScopeError):
        parse_scope(qs)


def test_scope_hits_and_window_edges() -> None:
    s = WallScope(desks=frozenset({"builder"}), window="1d", since=NOW - timedelta(days=1))
    assert s.desk_hit("Builder") and s.desk_hit("", ["x", "builder"]) and not s.desk_hit("wall-ui", None)
    assert s.in_window(FRESH) and s.in_window(FRESH.isoformat(sep=" ")) and s.in_window(str(FRESH)[:19])
    assert not s.in_window(WEEK) and not s.in_window(None) and not s.in_window("")
    assert s.in_window(OLD, FRESH)  # the newest stamp decides
    assert WallScope().desk_hit("anyone") and WallScope().in_window(None)


# --- the v1 list routes ---------------------------------------------------


def _todo_rows():
    def row(i, assigned, creator, updated, status="open"):
        return {"id": i, "roster": "the-mill", "status": status, "body": "", "assigned": assigned,
                "creator": creator, "updated": updated}

    return [("the-mill", [
        row(1, "builder", "wall-ui", FRESH, "done"),
        row(2, "", "wall-ui", WEEK),
        row(3, "grok-tui", "gardener", OLD),
        row(4, "", "gardener", FRESH, "parked"),
    ])]


def test_todos_desks_and_window(monkeypatch) -> None:
    monkeypatch.setattr(floor, "_todo_by_aff", lambda cn, names: _todo_rows())
    client = _client(monkeypatch)

    def ids(url):
        body = client.get(url).json()
        return sorted(int(c["id"]) for c in body["needs"] + body["issues"])

    assert ids("/api/v1/todos?project=the-mill") == [1, 2, 3, 4]
    assert ids("/api/v1/todos?project=the-mill&desks=builder") == [1]
    assert ids("/api/v1/todos?project=the-mill&desks=wall-ui") == [1, 2]
    assert ids("/api/v1/todos?project=the-mill&window=1d") == [1, 4]  # a card done today stays
    assert ids("/api/v1/todos?project=the-mill&window=7d") == [1, 2, 4]
    assert ids("/api/v1/todos?project=the-mill&window=30d&desks=gardener") == [4]


def test_mailbox_sender_or_recipient_and_created(monkeypatch) -> None:
    def letter(i, sender, to, created):
        return {"id": i, "created": str(created), "from": sender, "to": to,
                "mail_tos": [{"deskId": d, "receipt": 0} for d in to]}

    mail = [letter(1, "builder", ["wall-ui"], FRESH), letter(2, "gardener", ["builder"], WEEK),
            letter(3, "gardener", ["grok-tui"], OLD)]
    monkeypatch.setattr(floor, "build_mailbox", lambda cn, ps, want: (list(mail), {}))
    client = _client(monkeypatch)
    body = client.get("/api/v1/mailbox?project=the-mill&desks=builder").json()
    assert [m["id"] for m in body["mailbox"]] == [1, 2]
    assert body["desk_unread"] == {"wall-ui": 1, "builder": 1}
    assert [m["id"] for m in client.get("/api/v1/mailbox?project=the-mill&window=7d").json()["mailbox"]] == [1, 2]
    assert [m["id"] for m in client.get("/api/v1/mailbox?project=the-mill&window=1d&desks=grok-tui").json()["mailbox"]] == []


def test_holds_holder_and_held_since(monkeypatch) -> None:
    rows = [
        {"id": 1, "desk_id": 3, "desk": "builder", "roster": "Office", "resource": "pr-1", "updated": FRESH},
        {"id": 2, "desk_id": 4, "desk": "wall-ui", "roster": "Office", "resource": "pr-2", "updated": OLD},
        {"id": 3, "desk_id": None, "desk": None, "roster": "Office", "resource": "free", "updated": FRESH},
    ]
    monkeypatch.setattr("agent_coord.server.records.hold.find", lambda cn, **k: [dict(r) for r in rows])
    client = _client(monkeypatch)
    assert [r["id"] for r in client.get("/api/v1/holds?project=Office").json()["locks"]] == [1, 2]
    assert [r["id"] for r in client.get("/api/v1/holds?project=Office&desks=wall-ui").json()["locks"]] == [2]
    assert [r["id"] for r in client.get("/api/v1/holds?project=Office&window=1d").json()["locks"]] == [1]


def test_scores_desk_and_updated(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.admin.guard.office_name", lambda cn: "Office")
    rows = [
        {"id": 1, "roster": "the-mill", "roster_id": 9, "kpi": "a", "desk": "builder", "updated": FRESH},
        {"id": 2, "roster": "the-mill", "roster_id": 9, "kpi": "b", "desk": "wall-ui", "updated": OLD},
    ]
    monkeypatch.setattr(floor, "_score_by_aff", lambda cn, names: [("the-mill", [dict(r) for r in rows])])
    client = _client(monkeypatch)
    assert [r["id"] for r in client.get("/api/v1/scores?project=the-mill").json()["kpis"]] == [1, 2]
    assert [r["id"] for r in client.get("/api/v1/scores?project=the-mill&desks=wall-ui").json()["kpis"]] == [2]
    assert [r["id"] for r in client.get("/api/v1/scores?project=the-mill&window=30d").json()["kpis"]] == [1]


def test_rooms_desks_and_last_letter(monkeypatch) -> None:
    trees = [{"name": "TREE_a", "nodes": []}, {"name": "TREE_b", "nodes": []}, {"name": "TREE_c", "nodes": []}]
    facts = {"TREE_a": {"last_at": FRESH, "desks": {"builder", "wall-ui"}},
             "TREE_b": {"last_at": OLD, "desks": {"wall-ui"}},
             "TREE_c": {"last_at": None, "desks": set()}}
    seen: list = []
    monkeypatch.setattr(floor, "build_rooms", lambda cn, want: [dict(t) for t in trees])

    def fake_facts(cn, names):
        seen.append(list(names))
        return facts

    monkeypatch.setattr("agent_coord.server.records.tree.room_scope_facts", fake_facts)
    client = _client(monkeypatch)

    def names(url):
        return [t["name"] for t in client.get(url).json()["trees"]]

    assert names("/api/v1/rooms?project=the-mill") == ["TREE_a", "TREE_b", "TREE_c"]
    assert seen == []  # no scope, no extra read
    assert names("/api/v1/rooms?project=the-mill&desks=wall-ui") == ["TREE_a", "TREE_b"]
    assert names("/api/v1/rooms?project=the-mill&desks=builder&window=1d") == ["TREE_a"]
    assert names("/api/v1/rooms?project=the-mill&window=7d") == ["TREE_a"]
    assert names("/api/v1/rooms?project=the-mill&desk=builder") == ["TREE_a", "TREE_b", "TREE_c"]  # old desk= stays a no-op


def test_trees_desks_keep_forests_with_a_selected_desk() -> None:
    trees = [{"name": "a", "nodes": [{"who": "builder"}, {"who": "wall-ui"}]},
             {"name": "b", "nodes": [{"who": "gardener"}]}]
    assert [t["name"] for t in floor.filter_trees_by_desks(trees, WallScope(desks=frozenset({"wall-ui"})))] == ["a"]
    assert floor.filter_trees_by_desks(trees, WallScope()) == trees


def test_tree_routes_take_7d_and_pass_the_scope(monkeypatch) -> None:
    seen: dict = {}

    def fake(cn, **k):
        seen.update(k)
        return {"trees": [], "next": None}

    monkeypatch.setattr(floor, "v1_tree_todo", fake)
    r = _client(monkeypatch).get("/api/v1/tree-todo?project=the-mill&window=7d&desks=builder,wall-ui")
    assert r.status_code == 200, r.text
    assert seen["window"] == "7d"
    assert seen["scope"].desks == frozenset({"builder", "wall-ui"}) and seen["scope"].window == "7d"


@pytest.mark.parametrize("url,word", [
    ("/api/v1/todos?project=the-mill&window=2d", "window"),
    ("/api/v1/mailbox?project=the-mill&desks=a%20b", "desks"),
    ("/api/v1/holds?role=builder&desks=builder", "project"),
    ("/api/v1/scores?lan=192.0.2.1&window=1d", "project"),
    ("/api/v1/labels?project=Office&window=week", "window"),
    ("/api/v1/doing?desks=,", "desks"),
    ("/api/v1/doing?desk=builder&desks=wall-ui", "desks"),
    ("/api/v1/activity-buckets?project=Office&window=1h", "window"),
    ("/api/v1/score-runs?project=Office&desks=x%3By", "desks"),
    ("/api/activity?project=Office&desks=a%20b", "desks"),
])
def test_scope_refusals_are_400(monkeypatch, url, word) -> None:
    def boom(*a, **k):
        raise AssertionError("a refused read must not query the book")

    for target in ("agent_coord.server.records.floor._todo_by_aff", "agent_coord.server.records.floor.build_mailbox",
                   "agent_coord.server.records.hold.find", "agent_coord.server.records.label.wall_rows",
                   "agent_coord.server.records.activity.buckets", "agent_coord.server.records.score.runs",
                   "agent_coord.server.api.mill.rpc._h_session"):
        monkeypatch.setattr(target, boom)
    r = _client(monkeypatch).get(url)
    assert r.status_code == 400, r.text
    assert word in r.json()["error"]


# --- labels ---------------------------------------------------------------


def _label_rows():
    return [
        {"label": "builder", "type": "todo", "id": 1, "ord": 1, "updated": str(FRESH),
         "card": {"roster": "the-mill", "volunteer": "builder"}},
        {"label": "human-priorities", "type": "todo", "id": 2, "ord": 1, "updated": str(OLD),
         "card": {"roster": "r-one", "volunteer": "wall-ui", "last_activity_at": str(FRESH)}},
        {"label": "the-mill", "type": "mail", "id": 3, "ord": 1, "updated": str(OLD)},
        {"label": "gardener", "type": "todo", "id": 4, "ord": 2, "updated": str(OLD),
         "card": {"roster": "r-two", "volunteer": "gardener"}},
    ]


def test_labels_project_list_desks_and_window(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.records.label.wall_rows", lambda cn, names=None: _label_rows())
    client = _client(monkeypatch)

    def ids(url):
        body = client.get(url).json()
        return [r["id"] for r in body["rows"]], body["project"]

    assert ids("/api/v1/labels?project=Office") == ([1, 2, 3, 4], "Office")
    assert ids("/api/v1/labels?project=the-mill,r-one") == ([1, 2, 3], "the-mill,r-one")
    assert ids("/api/v1/labels?project=Office,r-two") == ([4], "r-two")
    assert ids("/api/v1/labels?project=Office&desks=wall-ui,gardener") == ([2, 4], "Office")
    assert ids("/api/v1/labels?project=Office&window=1d") == ([1, 2], "Office")


# --- doing ----------------------------------------------------------------


def test_doing_desks_and_project_list(monkeypatch) -> None:
    from agent_coord.server.api.mill import rpc

    calls: list = []
    by_roster = {
        "": [{"owner": "builder", "heartbeat": FRESH}, {"owner": "wall-ui", "heartbeat": OLD},
             {"owner": "gardener", "heartbeat": WEEK}],
        "the-mill": [{"owner": "builder", "heartbeat": FRESH, "project_id": "the-mill"},
                     {"owner": "wall-ui", "heartbeat": OLD, "project_id": "the-mill"}],
        "r-two": [{"owner": "builder", "heartbeat": FRESH, "project_id": "r-two"},
                 {"owner": "gardener", "heartbeat": WEEK, "project_id": "r-two"}],
    }

    def fake(c, body, project, owner):
        calls.append((body.get("desk"), project, bool(body.get("all"))))
        if body.get("desk"):
            return [v for v in by_roster[""] if v["owner"] == body["desk"]]
        return [dict(v) for v in by_roster[project or ""]]

    monkeypatch.setattr(rpc, "_h_session", fake)
    client = _client(monkeypatch)

    def owners(url):
        r = client.get(url)
        assert r.status_code == 200, r.text
        return [v["owner"] for v in r.json()["result"]]

    assert owners("/api/v1/doing?all=1") == ["builder", "wall-ui", "gardener"]
    assert owners("/api/v1/doing?desks=wall-ui,gardener") == ["wall-ui", "gardener"]
    assert calls[-1] == ("", "", True)
    assert owners("/api/v1/doing?project=the-mill,r-two") == ["builder", "wall-ui", "gardener"]  # one row per desk
    assert calls[-2:] == [("", "the-mill", False), ("", "r-two", False)]
    assert owners("/api/v1/doing?project=the-mill,r-two&desks=gardener") == ["gardener"]
    assert owners("/api/v1/doing?all=1&window=7d") == ["builder", "gardener"]
    assert owners("/api/v1/doing?desk=builder&window=1d") == ["builder"]  # the old single forms stay
    r = client.get("/api/v1/doing?project=the-mill,r-two")
    assert [v["project_id"] for v in r.json()["result"]] == ["the-mill", "the-mill", "r-two"]


# --- activity-buckets and score-runs --------------------------------------


def test_activity_buckets_project_list_desks_and_window(monkeypatch) -> None:
    seen: list = []

    def fake(cn, roster, grain, since, type_s, act):
        seen.append((roster, since))
        return [{"updated": "2026-11-12 0%d:00:00.000000" % (1 if roster == "a" else 2), "type": "mail",
                 "act": "send", "desk": "builder" if roster == "a" else "wall-ui", "desk_id": 3,
                 "roster": roster, "items": 1}]

    monkeypatch.setattr("agent_coord.server.records.activity.buckets", fake)
    client = _client(monkeypatch)
    body = client.get("/api/v1/activity-buckets?project=b,a").json()
    assert [r["roster"] for r in body["rows"]] == ["a", "b"]  # oldest bucket first across rosters
    assert len({r["id"] for r in body["rows"]}) == 2
    assert [r["roster"] for r in client.get("/api/v1/activity-buckets?project=a,b&desks=wall-ui").json()["rows"]] == ["b"]
    client.get("/api/v1/activity-buckets?project=a&window=7d&since=2000-01-01T00:00:00")
    assert seen[-1][1] > datetime.now() - timedelta(days=7, minutes=1)  # the later cut wins
    client.get("/api/v1/activity-buckets?project=a&window=30d&since=2999-01-01T00:00:00")
    assert seen[-1][1] == datetime(2999, 1, 1)


def test_score_runs_project_list_desks_and_window(monkeypatch) -> None:
    def fake(cn, roster, phase):
        return {
            "a": [{"id": 5, "desk": "builder", "phase": "start", "at": str(FRESH)},
                  {"id": 1, "desk": "builder", "phase": "start", "at": str(OLD)}],
            "b": [{"id": 7, "desk": "wall-ui", "phase": "finished", "at": str(WEEK)}],
        }[roster]

    monkeypatch.setattr("agent_coord.server.records.score.runs", fake)
    client = _client(monkeypatch)

    def ids(url):
        return [r["id"] for r in client.get(url).json()["rows"]]

    assert ids("/api/v1/score-runs?project=a,b") == [5, 7, 1]  # newest first across rosters
    assert ids("/api/v1/score-runs?project=a,b&desks=wall-ui") == [7]
    assert ids("/api/v1/score-runs?project=a,b&window=7d") == [5, 7]
    assert ids("/api/v1/score-runs?project=a") == [5, 1]


# --- /api/activity ----------------------------------------------------------


def test_activity_desks_and_long_windows(monkeypatch) -> None:
    seen: list = []

    def fake(cn, project, window="24h"):
        seen.append(window)
        return [{"updated": "2026-11-12 01:00:00.000000", "type": "mail", "desk_id": 3, "owner": "builder",
                 "roster_id": project, "n": 1},
                {"updated": "2026-11-12 02:00:00.000000", "type": "mail", "desk_id": 4, "owner": "wall-ui",
                 "roster_id": project, "n": 2}]

    monkeypatch.setattr(floor, "_timeline", fake)
    client = _client(monkeypatch)
    body = client.get("/api/activity?project=the-mill&window=30d&desks=wall-ui").json()
    assert [r["owner"] for r in body["rows"]] == ["wall-ui"] and body["bucket"] == "day"
    assert client.get("/api/activity?project=the-mill&window=1d").json()["bucket"] == "hour"
    assert len(client.get("/api/activity?project=the-mill&window=7d").json()["rows"]) == 2
    assert seen == ["30d", "1d", "7d"]


def test_window_bucket_long_windows() -> None:
    since, grain = floor.window_bucket("30d")
    assert grain == "day" and since < datetime.now() - timedelta(days=29)
    assert floor.window_bucket("1d")[1] == "hour" and floor.window_bucket("1w")[1] == "day"


# --- seeded book ----------------------------------------------------------


@pytest.mark.sql
def test_seeded_pov_rosters_list_member_desks(cn, monkeypatch) -> None:
    from uuid import uuid4

    from agent_coord.server.records import join

    roster = "r1193-" + uuid4().hex[:6]
    desks = sorted("d1193-" + uuid4().hex[:6] for _ in range(2))
    for d in desks:
        join.upsert(cn, roster, d, "", "b" * 64)
    cn.commit()
    rows = _client(monkeypatch, cn).get("/api/pov?part=rosters").json()["rows"]
    mine = [r for r in rows if r["name"] == roster]
    assert mine == [{"name": roster, "desks": 2, "members": desks}]
    assert all(isinstance(r["members"], list) and len(r["members"]) == r["desks"] for r in rows)


@pytest.mark.sql
def test_seeded_room_scope_facts_name_senders_and_recipients(cn) -> None:
    from uuid import uuid4

    from agent_coord.server.records import join
    from agent_coord.server.records import tree as rec_tree
    from agent_coord.server.records.db import rows_done

    a, b, c = ("d1193f-" + uuid4().hex[:6] for _ in range(3))
    for d in (a, b, c):
        join.upsert(cn, "Office", d, "", "c" * 64)
    cn.commit()
    from agent_coord.server.records import mail as rec_mail

    mid = int(rec_mail.insert(cn, "Office", a, b, "first letter for #1193")[0]["id"])
    reply = int(rec_mail.insert(cn, "Office", b, a, "a reply for #1193")[0]["id"])
    room = "r1193room-" + uuid4().hex[:6]
    rec_tree.create(cn, room, "mail", mid)
    rec_tree.add(cn, "mail", mid, "mail", reply, tree=room)
    cn.commit()
    newest = rows_done(cn, "SELECT MAX(created) AS at FROM mail WHERE id IN (%s, %s)", (mid, reply))[0]["at"]
    facts = rec_tree.room_scope_facts(cn, [room, "no-such-room"])
    assert facts[room] == {"last_at": newest, "desks": {a, b}}
    assert facts["no-such-room"] == {"last_at": None, "desks": set()}
    assert c not in facts[room]["desks"]
    assert rec_tree.room_scope_facts(cn, []) == {}
