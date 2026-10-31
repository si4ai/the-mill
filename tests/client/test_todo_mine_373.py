"""todo --mine lists only the cards the sitting desk volunteered for (#373). Regression row F57 (todo-mine)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser, main
from agent_coord.client import http
from agent_coord.client.todo_rows import TODO_PAGE
from agent_coord.helpers.errors import CoordError


def _card(i, volunteer="", status="open", roster="the-mill", detail="line"):
    return {"project_id": roster, "need_id": f"need-{i}", "id": i, "status": status,
            "doing": f"title {i}", "detail": detail, "volunteer": volunteer,
            "asker": "desk-z", "tree": None, "labels": []}


def _wall(monkeypatch, rows, owner="desk-a", seen=None):
    from agent_coord.server.mill_json import with_bytes

    def fake(args, body):
        if seen is not None:
            seen.append(dict(body))
        reply, _ = with_bytes({"id": "r1", "ok": True, "result": list(rows), "sync": [], "mill": "t"})
        reply = dict(reply)
        reply["note"] = "your rosters only (the-mill); mill todo --all lists every roster"
        return reply

    monkeypatch.setattr(http, "_todo_call", fake)
    monkeypatch.setattr("agent_coord.client.outbound.body_from_args",
                        lambda args: {"verb": "todo", "owner": owner})


def _run(capsys, **kw):
    base = dict(cmd="todo", project="", need="", find="", group_by="roster", raw=False,
                said_command="", full=False, page=0, mine=True)
    base.update(kw)
    rc = http.mill_http_from_args(SimpleNamespace(**base))
    out = capsys.readouterr().out.strip().splitlines()
    return rc, (json.loads(out[-1]) if out else None)


def _items(result):
    if isinstance(result, list):
        return result
    return [r for g in result["groups"] for r in g["items"]]


def mixed():
    # Desk names that contain the sitting desk's name must not match (exact only).
    return [_card(1, "desk-a", "claimed"), _card(2, ""), _card(3, "desk-b", "claimed"),
            _card(4, "desk-a", "shipped"), _card(5, "desk-a-2", "claimed"), _card(6, "x-desk-a", "shipped"),
            _card(7, "DESK-A", "claimed")]


def test_only_the_sitting_desks_cards(monkeypatch, capsys):
    _wall(monkeypatch, mixed())
    rc, row = _run(capsys)
    assert rc == 0
    assert [r["id"] for r in _items(row["result"])] == [1, 4]
    assert all(r["volunteer"] == "desk-a" for r in _items(row["result"]))
    assert row["page"]["cards"] == 2 and row["page"]["of"] == 1
    assert "desk-a" in row["note"]


def test_no_claimed_cards_is_an_empty_page_with_a_hint(monkeypatch, capsys):
    _wall(monkeypatch, [_card(1, ""), _card(2, "desk-b", "claimed")])
    rc, row = _run(capsys)
    assert rc == 0 and _items(row["result"]) == []
    assert row["page"]["cards"] == 0 and row["page"]["of"] == 1
    assert "--done" in row["note"] and "desk-a" in row["note"]


def test_mine_empty_omits_done_when_already_passed(monkeypatch, capsys):
    """#649: --mine with --done already set does not say add --done."""
    _wall(monkeypatch, [_card(1, ""), _card(2, "desk-b", "claimed")])
    rc, row = _run(capsys, done=True)
    assert rc == 0 and _items(row["result"]) == []
    assert "--done" not in row["note"]
    assert "asker-only" in row["note"]


def test_without_mine_the_board_is_unchanged(monkeypatch, capsys):
    _wall(monkeypatch, mixed())
    _, row = _run(capsys, mine=False)
    assert len(_items(row["result"])) == 7


def test_paging_counts_the_filtered_set(monkeypatch, capsys):
    n = TODO_PAGE + 3
    rows = []
    for i in range(1, 3 * n + 1):
        rows.append(_card(i, "desk-a" if i % 3 == 0 else "desk-b", "claimed"))
    _wall(monkeypatch, rows)
    _, first = _run(capsys)
    assert first["page"]["cards"] == n and first["page"]["of"] == 2
    assert first["page"]["next"] == "--page 2"
    assert len(_items(first["result"])) == TODO_PAGE
    _, second = _run(capsys, page=2)
    got = [r["id"] for r in _items(first["result"])] + [r["id"] for r in _items(second["result"])]
    assert got == [i for i in range(1, 3 * n + 1) if i % 3 == 0]
    with pytest.raises(CoordError, match=r"todo --page 3: 53 card\(s\) make 2 page"):
        _run(capsys, page=3)


def test_status_and_done_ride_to_the_wall_unchanged(monkeypatch, capsys):
    seen: list = []
    _wall(monkeypatch, [_card(1, "desk-a", "claimed")], seen=seen)
    _run(capsys, status="claimed", done=True)
    # The wall still filters status/done in SQL; --mine adds no wall field.
    assert "mine" not in seen[0] and "volunteer" not in seen[0]


def test_with_find_keeps_only_my_matches(monkeypatch, capsys):
    rows = [_card(1, "desk-a", "claimed", detail="the login bug"),
            _card(2, "desk-b", "claimed", detail="the login bug"),
            _card(3, "desk-a", "claimed", detail="other")]
    _wall(monkeypatch, rows)
    _, row = _run(capsys, find="login", group_by="")
    assert [r["id"] for r in row["result"]] == [1]
    assert "snippet" in row["result"][0] and "page" not in row


def test_with_full_prints_every_field_of_my_cards(monkeypatch, capsys):
    _wall(monkeypatch, mixed())
    _, row = _run(capsys, full=True)
    items = _items(row["result"])
    assert [r["id"] for r in items] == [1, 4]
    assert all("detail" in r and "doing" in r for r in items) and "page" not in row


def test_raw_with_mine_is_filtered_too(monkeypatch, capsys):
    _wall(monkeypatch, mixed())
    _, row = _run(capsys, raw=True)
    assert [r["id"] for r in row] == [1, 4]


def test_no_sitting_connect_is_refused_with_the_recipe(monkeypatch, capsys):
    _wall(monkeypatch, mixed(), owner="")
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *a, **k: "")
    with pytest.raises(CoordError) as e:
        _run(capsys)
    msg = str(e.value)
    assert msg.startswith("todo --mine:") and "mill connect" in msg and "sitting" in msg


def test_owner_found_after_the_connect_sits(monkeypatch, capsys):
    # `mill connect DESK & mill todo --mine`: the body is built before the connect sits.
    _wall(monkeypatch, mixed(), owner="")
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *a, **k: "desk-a")
    _, row = _run(capsys)
    assert [r["id"] for r in _items(row["result"])] == [1, 4]


def test_peek_with_mine_is_refused(monkeypatch, capsys):
    _wall(monkeypatch, mixed())
    with pytest.raises(CoordError, match="todo --mine: a NEED peek is one card; drop --mine"):
        _run(capsys, project="the-mill", need="need-1")


def test_parser_and_help(capsys):
    p = _build_parser()
    a = p.parse_args(["todo", "--mine", "--status", "claimed", "--done", "--all", "--find", "x"])
    assert a.mine is True and a.status == "claimed" and a.all and a.done and a.find == "x"
    assert p.parse_args(["todo", "--mine", "--page", "2"]).page == 2
    assert p.parse_args(["todo", "--mine", "--full"]).full is True
    assert p.parse_args(["todo"]).mine is False
    with pytest.raises(SystemExit):
        main(["todo", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "--mine" in out and "volunteer" in out and "sitting" in out
