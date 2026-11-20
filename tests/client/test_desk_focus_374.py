"""Desk focus: the label named after the desk ranks its cards (#374). Regression row F58 (desk-focus).

`todo --mine` lists the focus cards first in rank order, then the desk's
claimed cards; `mill connect` prints the top open focus cards once seated.
"""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from agent_coord.client import focus, http
from agent_coord.client import ws as ws_mod
from agent_coord.client.todo_rows import TODO_PAGE


def _card(i, volunteer="", status="open", labels=(), tree=None):
    return {"project_id": "the-mill", "need_id": f"need-{i}", "id": i, "status": status,
            "doing": f"title {i}", "detail": "body", "volunteer": volunteer,
            "asker": "desk-z", "tree": tree, "labels": list(labels)}


def _label_reply(pairs, truncated=False, label="desk-a"):
    rows = [{"id": i, "type": "todo", "ord": o, "body": "", "need": f"need-{i}", "created": ""} for i, o in pairs]
    return {"id": "t1", "ok": True, "result": {"label": label, "hint": "", "rows": rows, "truncated": truncated}}


def _wall(monkeypatch, board, label_pairs=(), owner="desk-a", calls=None, truncated=False):
    from agent_coord.server.mill_json import with_bytes

    def fake_todo(args, body):
        reply, _ = with_bytes({"id": "r1", "ok": True, "result": list(board), "sync": [], "mill": "t"})
        return dict(reply, note="your rosters only (the-mill); mill todo --all lists every roster")

    def fake_call(body):
        if calls is not None:
            calls.append(dict(body))
        assert body["verb"] == "trail" and body["label"] == owner
        return _label_reply(label_pairs, truncated, owner)

    monkeypatch.setattr(http, "_todo_call", fake_todo)
    monkeypatch.setattr(http, "mill_http_call", fake_call)
    monkeypatch.setattr("agent_coord.client.outbound.body_from_args",
                        lambda args: {"verb": "todo", "owner": owner})


def _run(capsys, **kw):
    base = dict(cmd="todo", project="", need="", find="", group_by="", raw=False,
                said_command="", full=False, page=0, mine=True)
    base.update(kw)
    rc = http.mill_http_from_args(SimpleNamespace(**base))
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def _ids(row):
    res = row["result"]
    if isinstance(res, dict):
        return [r["id"] for g in res["groups"] for r in g["items"]]
    return [r["id"] for r in res]


def board_mixed():
    return [
        _card(1, "desk-a", "claimed", tree="a1b2c3d4e5"),
        _card(2, "", "open", labels=["desk-a"]),                 # focus, unclaimed
        _card(3, "desk-b", "claimed", labels=["desk-a", "ux"]),  # focus label, held by another desk: skipped
        _card(4, "desk-a", "shipped", labels=["desk-a"]),        # focus and mine: listed once
        _card(5, "desk-b", "claimed", labels=["desk-b"]),        # another desk's focus
        _card(6, "desk-a", "claimed"),
        _card(7, "", "parked", labels=["desk-a"]),               # focus label, parked: skipped
    ]


def test_focus_first_in_rank_order_then_claimed_no_duplicates(monkeypatch, capsys):
    _wall(monkeypatch, board_mixed(), [(7, 0), (3, 1), (4, 5), (2, 9)])
    rc, row = _run(capsys)
    assert rc == 0
    # 7 parked and 3 held by desk-b are skipped; 4 is mine and focus: listed once, in focus.
    assert _ids(row) == [4, 2, 1, 6]
    rows = row["result"]
    assert [r.get("focus") for r in rows] == [5, 9, None, None]
    assert set(rows[0]) <= {"id", "need_id", "status", "volunteer", "project_id", "focus"}
    assert row["page"]["cards"] == 4
    assert "2 focus" in row["note"] and "2 claimed" in row["note"]


def test_status_parked_asked_lists_parked_focus(monkeypatch, capsys):
    _wall(monkeypatch, [c for c in board_mixed() if c["status"] == "parked"], [(7, 0)])
    _, row = _run(capsys, status="parked")
    assert _ids(row) == [7] and row["result"][0]["focus"] == 0


def test_rank_is_ord_then_card_id_whatever_the_reply_order(monkeypatch, capsys):
    board = [_card(i, "", "open", labels=["desk-a"]) for i in (11, 12, 13, 14)]
    _wall(monkeypatch, board, [(14, 3), (13, 65535), (12, 3), (11, 0)])
    _, row = _run(capsys)
    assert _ids(row) == [11, 12, 14, 13]


def test_no_focus_label_on_the_board_skips_the_label_read(monkeypatch, capsys):
    calls: list = []
    _wall(monkeypatch, [_card(1, "desk-a", "claimed"), _card(2, "")], calls=calls)
    _, row = _run(capsys)
    assert _ids(row) == [1] and calls == []
    assert "focus" not in row["result"][0]


def test_empty_names_how_to_set_focus(monkeypatch, capsys):
    _wall(monkeypatch, [_card(1, "desk-b", "claimed")])
    _, row = _run(capsys)
    assert row["result"] == []
    assert "a desk name cannot be a label; rank cards under another label" in row["note"]


def test_label_read_failure_keeps_board_order(monkeypatch, capsys):
    _wall(monkeypatch, board_mixed())

    def boom(body):
        raise http.CoordError("ws rpc: sitting socket closed")

    monkeypatch.setattr(http, "mill_http_call", boom)
    _, row = _run(capsys)
    assert _ids(row) == [2, 4, 1, 6]  # every focus card unplaced: by card id


def test_labelled_but_not_in_the_label_reply_follows_the_ranked(monkeypatch, capsys):
    # trail --label is byte-capped: a focus card past the cap still lists, after the ranked ones.
    _wall(monkeypatch, board_mixed(), [(4, 0)], truncated=True)
    _, row = _run(capsys)
    assert _ids(row) == [4, 2, 1, 6]
    assert [r.get("focus") for r in row["result"]][:2] == [0, 65535]


def test_done_focus_cards_stay_hidden_with_the_board(monkeypatch, capsys):
    # The wall hides done unless --done; --mine never adds cards the board did not list.
    _wall(monkeypatch, [_card(1, "desk-a", "claimed")], [(9, 0), (1, 1)])
    _, row = _run(capsys)
    assert _ids(row) == [1]


def test_paging_counts_the_combined_set(monkeypatch, capsys):
    n_focus, n_claim = 30, TODO_PAGE
    board = [_card(i, "", "open", labels=["desk-a"]) for i in range(1, n_focus + 1)]
    board += [_card(100 + i, "desk-a", "claimed") for i in range(n_claim)]
    board += [_card(500 + i, "desk-b", "claimed") for i in range(40)]
    pairs = [(i, n_focus - i) for i in range(1, n_focus + 1)]  # card 30 has ord 0
    _wall(monkeypatch, board, pairs)
    _, first = _run(capsys)
    assert first["page"]["cards"] == n_focus + n_claim and first["page"]["of"] == 2
    _, second = _run(capsys, page=2)
    seen = _ids(first) + _ids(second)
    assert seen == list(range(n_focus, 0, -1)) + [100 + i for i in range(n_claim)]


def test_full_lists_the_same_cards_in_the_same_order(monkeypatch, capsys):
    _wall(monkeypatch, board_mixed(), [(3, 0), (4, 5), (2, 9)])
    _, row = _run(capsys, full=True)
    assert _ids(row) == [4, 2, 1, 6] and "page" not in row
    assert all("detail" in r for r in row["result"])
    assert row["result"][0]["focus"] == 5


def test_explicit_group_by_still_groups(monkeypatch, capsys):
    _wall(monkeypatch, board_mixed(), [(3, 0), (4, 5), (2, 9)])
    _, row = _run(capsys, group_by="tree")
    assert isinstance(row["result"], dict) and row["result"]["group_by"] == "tree"


def test_without_mine_the_board_is_unchanged(monkeypatch, capsys):
    calls: list = []
    _wall(monkeypatch, board_mixed(), [(3, 0)], calls=calls)
    _, row = _run(capsys, mine=False, group_by="roster")
    items = [r for g in row["result"]["groups"] for r in g["items"]]
    assert calls == [] and len(items) == 7 and all("focus" not in r for r in items)


# --- connect focus block (#536: one board read, any roster) ------------------

class Wall:
    """A small model of the 0.7.8 wall for the reads connect makes.

    member lists the desk's rosters; todo with rosters reads those boards (done
    hidden); a todo peek with an empty project reads the-mill only, as the wall
    defaults it; trail --label answers ord then created.
    """

    def __init__(self, cards, rank, rosters=("Office", "fx-r9"), fail=None):
        self.cards, self.rank, self.rosters, self.fail = list(cards), list(rank), list(rosters), fail or {}
        self.commands: list = []

    def __call__(self, body):
        command = body["verb"]
        self.commands.append(command)
        if command in self.fail:
            err = self.fail[command]
            if isinstance(err, BaseException):
                raise err
            return {"ok": False, "error": err}
        if command == "member":
            return {"ok": True, "result": [{"slot": r} for r in self.rosters]}
        if command == "trail":
            return _label_reply(sorted(self.rank, key=lambda t: t[1]))
        if command == "todo" and "rosters" in body:
            on = [c for c in self.cards if c["project_id"] in body["rosters"] and c["status"] != "done"]
            return {"ok": True, "result": {"cards": on, "rosters": len(body["rosters"])}}
        if command == "todo":
            roster = body.get("project") or "the-mill"
            hit = [c for c in self.cards if c["project_id"] == roster and str(c["id"]) == str(body.get("need"))]
            return {"ok": True, "result": hit} if hit else {"ok": False, "error": f"todo: no card {body.get('need')} in {roster}"}
        raise AssertionError(command)


def _fx(i, volunteer="", status="open", roster="fx-r9", labels=("desk-a",)):
    return dict(_card(i, volunteer, status, labels=labels), project_id=roster)


def test_block_reads_focus_cards_on_any_roster_of_the_desk():
    # The A/B fixture: focus cards on the desk's own roster, not the-mill.
    wall = Wall([_fx(i) for i in (41, 42, 43, 44, 45, 46)], [(43, 0), (41, 5), (46, 10), (42, 15), (44, 20), (45, 25)])
    block = focus.connect_block(wall, "desk-a")
    assert [c["id"] for c in block["cards"]] == [43, 41, 46, 42, 44]
    assert block["cards"][0] == {"id": 43, "project_id": "fx-r9", "need_id": "need-43", "status": "open",
                                 "volunteer": "", "rank": 0}
    assert wall.commands == ["member", "todo", "trail"]


def test_block_top_five_actionable_in_rank_order():
    status = {2: "done", 3: "parked"}
    who = {4: "desk-b"}  # held by another desk
    cards = [_fx(i, who.get(i, "desk-a" if i % 2 else ""), status.get(i, "claimed" if i % 2 else "open"))
             for i in range(1, 10)]
    block = focus.connect_block(Wall(cards, [(c["id"], c["id"] - 1) for c in cards]), "desk-a")
    assert block["kind"] == "focus" and block["label"] == "desk-a"
    assert [c["id"] for c in block["cards"]] == [1, 5, 6, 7, 8]
    assert [c["rank"] for c in block["cards"]] == [0, 4, 5, 6, 7]
    assert "mill todo --mine" in block["rest"]


def test_block_rank_is_ord_then_card_id():
    wall = Wall([_fx(i) for i in (21, 22, 23)], [(23, 1), (22, 1), (21, 9)])
    block = focus.connect_block(wall, "desk-a")
    assert [(c["id"], c["rank"]) for c in block["cards"]] == [(22, 1), (23, 1), (21, 9)]


def test_block_none_when_nothing_to_work_on():
    assert focus.connect_block(Wall([_fx(1, labels=())], []), "desk-a") is None
    held = [_fx(1, "desk-b", "claimed"), _fx(2, "", "parked"), _fx(3, "", "done")]
    assert focus.connect_block(Wall(held, [(1, 0), (2, 1), (3, 2)]), "desk-a") is None


def test_block_skips_the_label_read_when_no_card_wears_it():
    wall = Wall([_fx(1, "desk-a", "claimed", labels=())], [])
    assert focus.connect_block(wall, "desk-a") is None
    assert wall.commands == ["member", "todo"]


def test_card_on_a_roster_the_desk_is_not_on_is_not_focus():
    wall = Wall([_fx(1, roster="elsewhere"), _fx(2)], [(1, 0), (2, 1)])
    assert [c["id"] for c in focus.connect_block(wall, "desk-a")["cards"]] == [2]


@pytest.mark.parametrize("command,err,said", [
    ("member", "member: refused", "member: refused"),
    ("todo", "todo: unknown project fx-r9", "todo: unknown project fx-r9"),
    ("trail", "trail: owner required", "trail: owner required"),
    ("todo", OSError("timed out"), "timed out"),
])
def test_block_names_the_failed_read(command, err, said):
    wall = Wall([_fx(1)], [(1, 0)], fail={command: err})
    with pytest.raises(focus.FocusError) as e:
        focus.connect_block(wall, "desk-a")
    assert said in str(e.value) and command in str(e.value)


def _socket(monkeypatch, wall, project_reply=None):
    def fake(who, body, **k):
        if body["verb"] == "project":
            return project_reply or {"ok": True, "result": {"ok": True}}
        return wall(body)

    monkeypatch.setattr(ws_mod, "own_bridge_call", fake)


def test_connect_prints_the_block_after_the_project_check(monkeypatch, capsys):
    _socket(monkeypatch, Wall([_fx(1, "desk-a", "claimed")], [(1, 0)]))
    stop = threading.Event()
    ws_mod.hold_sync_lines()
    ws_mod.gate_line('{"kind": "sync", "sync": []}')
    http.seat_then_focus("desk-a", "fx-r9", stop, {})
    cap = capsys.readouterr()
    lines = cap.out.strip().splitlines()
    assert json.loads(lines[0])["kind"] == "sync"
    block = json.loads(lines[1])
    assert block["kind"] == "focus" and block["cards"][0]["id"] == 1
    assert cap.err == ""


def test_connect_says_why_when_focus_cannot_be_read(monkeypatch, capsys):
    _socket(monkeypatch, Wall([_fx(1)], [(1, 0)], fail={"trail": "trail: owner required"}))
    stop = threading.Event()
    outcome: dict = {}
    ws_mod.hold_sync_lines()
    http.seat_then_focus("desk-a", "fx-r9", stop, outcome)
    cap = capsys.readouterr()
    assert "focus" not in cap.out
    assert cap.err.count("\n") == 1
    assert cap.err.startswith("connect: focus not shown: ") and "trail: owner required" in cap.err
    # Focus never fails or stops a connect.
    assert not stop.is_set() and "exit" not in outcome


def test_connect_prints_nothing_without_focus_or_after_refusal(monkeypatch, capsys):
    _socket(monkeypatch, Wall([], []))
    stop = threading.Event()
    ws_mod.hold_sync_lines()
    http.seat_then_focus("desk-a", "fx-r9", stop, {})
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == ""

    wall = Wall([_fx(1)], [(1, 0)])
    _socket(monkeypatch, wall, {"ok": False, "error": "connect: no such project x"})
    stop = threading.Event()
    ws_mod.hold_sync_lines()
    http.seat_then_focus("desk-a", "x", stop, {})
    assert wall.commands == [] and "focus" not in capsys.readouterr().out
