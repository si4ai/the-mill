"""Card 1311, slice 3 (card status): the todo trace replay.

Each rule has its own planted fixture. The done-when plant for card status is a claim row
on a card that is already claimed: reported by event id, and the command exits nonzero.
"""
from __future__ import annotations

import json
import random

import pytest

from agent_coord.server import trace_conform as tc
from tools import trace_conform as cli

D1, D2 = 7, 8


def ev(i, frm, to, reason, *, card=1, desk=D1, at=None, n=1, meta=None):
    return {"id": i, "at": at or f"2026-11-26 10:{i:02d}:00", "activity_type": "todo", "activity_id": card,
            "from_state": frm, "to_state": to, "reason": reason, "desk_id": desk,
            "join_key": f"card:{card}", "meta": meta, "n": n}


def life():
    return [
        ev(1, "none", "open", "create"),
        ev(2, "open", "claimed", "claim"),
        ev(3, "claimed", "shipped", "pass_ship"),
        ev(4, "shipped", "done", "pass_done"),
    ]


def rules(rep, bucket):
    return [(f["rule"], f["event_id"]) for f in rep[bucket]]


def counts(rep):
    return rep["counts"]


def test_step_table_matches_the_model_edges():
    assert set(tc.TODO_STEPS) == set(tc.model_edges("todo"))


def test_clean_card_life_has_no_findings():
    rep = tc.replay_todo(life(), stored_states={1: "done"})
    assert counts(rep) == {"forbidden": 0, "silent": 0, "unmodelled": 0}
    assert rep["events"] == 4
    assert "T4" not in rep["quiet_steps"] and "T7" in rep["quiet_steps"]


def test_every_status_move_has_a_clean_path():
    rows = [
        ev(1, "none", "parked", "create_parked"),
        ev(2, "parked", "open", "unpark"),
        ev(3, "open", "claimed", "assign", meta={"to": D2}),
        ev(4, "claimed", "claimed", "take_over", desk=D2),
        ev(5, "claimed", "open", "unclaim"),
        ev(6, "open", "claimed", "claim"),
        ev(7, "claimed", "shipped", "pass_ship"),
        ev(8, "shipped", "claimed", "pass_back"),
        ev(9, "claimed", "shipped", "pass_ship"),
        ev(10, "shipped", "open", "pass_back"),
        ev(11, "open", "claimed", "claim"),
        ev(12, "claimed", "shipped", "pass_ship"),
        ev(13, "shipped", "done", "pass_done"),
        ev(14, "done", "shipped", "pass_back"),
        ev(15, "any", "same", "note"),
        ev(16, "any", "same", "rename"),
    ]
    rep = tc.replay_todo(rows, stored_states={1: "shipped"})
    assert counts(rep) == {"forbidden": 0, "silent": 0, "unmodelled": 0}


def test_planted_claim_on_a_claimed_card_is_forbidden_by_id():
    rows = life()[:2] + [ev(3, "open", "claimed", "claim")]
    rep = tc.replay_todo(rows)
    assert rules(rep, "forbidden") == [("from_state", 3)]
    assert rep["forbidden"][0]["path"] == [1, 2, 3]
    assert rep["forbidden"][0]["step"] == "T4"


def test_a_step_from_the_wrong_status_is_forbidden():
    rows = [ev(1, "none", "open", "create"), ev(2, "shipped", "done", "pass_done")]
    assert rules(tc.replay_todo(rows), "forbidden") == [("from_state", 2)]


def test_second_create_on_a_card_made_in_this_log_is_a_seed_row_not_forbidden():
    rows = life()[:2] + [ev(3, "none", "open", "create")]
    rep = tc.replay_todo(rows)
    assert rules(rep, "silent") == [("create_on_live_card", 3)]
    assert counts(rep)["forbidden"] == 0


def test_move_on_a_retired_card_is_forbidden_until_reclaim():
    rows = life()[:2] + [
        ev(3, "any", "retired", "retire"),
        ev(4, "claimed", "shipped", "pass_ship"),
        ev(5, "retired", "prior", "reclaim"),
        ev(6, "claimed", "shipped", "pass_ship"),
    ]
    rep = tc.replay_todo(rows, stored_states={1: "shipped"})
    assert rules(rep, "forbidden") == [("move_on_retired", 4)]
    assert counts(rep)["silent"] == 0


def test_reclaim_restores_the_status_it_had():
    rows = life()[:2] + [ev(3, "any", "retired", "retire"), ev(4, "retired", "prior", "reclaim")]
    assert counts(tc.replay_todo(rows, stored_states={1: "claimed"}))["silent"] == 0
    rep = tc.replay_todo(rows, stored_states={1: "open"})
    assert rules(rep, "silent") == [("state_ahead", 4)]


def test_retire_twice_and_reclaim_of_a_live_card_are_forbidden():
    twice = life()[:1] + [ev(2, "any", "retired", "retire"), ev(3, "any", "retired", "retire")]
    assert rules(tc.replay_todo(twice), "forbidden") == [("retired_twice", 3)]
    live = life()[:1] + [ev(2, "retired", "prior", "reclaim")]
    assert rules(tc.replay_todo(live), "forbidden") == [("reclaim_not_retired", 2)]


def test_note_and_rename_on_a_retired_card_are_not_status_moves():
    rows = life()[:1] + [ev(2, "any", "retired", "retire"), ev(3, "any", "same", "note")]
    assert counts(tc.replay_todo(rows, stored_states={1: "retired"})) == {
        "forbidden": 0, "silent": 0, "unmodelled": 0}


def test_unmodelled_edge_is_counted_not_forbidden():
    rows = life()[:1] + [ev(2, "open", "done", "pass_done")]
    rep = tc.replay_todo(rows)
    assert counts(rep) == {"forbidden": 0, "silent": 0, "unmodelled": 1}
    assert rep["unmodelled"][0]["edge"] == ["open", "done", "pass_done"]


def test_silent_rules_each_fire():
    start = tc.replay_todo([ev(5, "claimed", "shipped", "pass_ship")])
    assert rules(start, "silent") == [("no_start_event", 5)]
    ahead = tc.replay_todo(life(), stored_states={1: "shipped"})
    assert rules(ahead, "silent") == [("state_ahead", 4)]
    ship = tc.replay_todo([
        ev(1, "none", "open", "create"),
        ev(2, "claimed", "shipped", "pass_ship"),
    ])
    assert rules(ship, "silent") == [("ship_from_open", 2)]
    assert counts(ship)["forbidden"] == 0


def test_a_mid_life_start_checks_the_steps_after_it():
    rows = [ev(5, "claimed", "shipped", "pass_ship"), ev(6, "claimed", "shipped", "pass_ship")]
    rep = tc.replay_todo(rows)
    assert rules(rep, "silent") == [("no_start_event", 5)]
    assert rules(rep, "forbidden") == [("from_state", 6)]


def test_compress_even_count_is_back_at_from_state():
    rows = [ev(1, "none", "open", "create"), ev(2, "open", "claimed", "claim", n=2),
            ev(3, "open", "claimed", "claim")]
    assert counts(tc.replay_todo(rows, stored_states={1: "claimed"}))["forbidden"] == 0


def test_a_backfilled_row_is_ordered_by_time_not_id():
    rows = [
        ev(10, "open", "claimed", "claim", at="2026-11-01 12:01:00"),
        ev(11, "claimed", "shipped", "pass_ship", at="2026-11-01 12:02:00"),
        ev(99, "none", "open", "create", at="2026-11-01 12:00:00"),
    ]
    assert counts(tc.replay_todo(rows, stored_states={1: "shipped"})) == {
        "forbidden": 0, "silent": 0, "unmodelled": 0}


def test_other_activity_types_are_ignored():
    rows = life() + [{**ev(9, "none", "queued", "wake_queue"), "activity_type": "wake"}]
    assert tc.replay_todo(rows)["events"] == 4


def test_cards_are_kept_apart():
    rows = life() + [ev(7, "none", "open", "create", card=2), ev(8, "open", "claimed", "claim", card=2)]
    rep = tc.replay_todo(rows, stored_states={1: "done", 2: "claimed"})
    assert counts(rep) == {"forbidden": 0, "silent": 0, "unmodelled": 0}


def test_order_of_input_does_not_change_the_report():
    rows = life()[:2] + [ev(3, "open", "claimed", "claim")] + [ev(6, "claimed", "shipped", "pass_ship", card=2)]
    a = json.dumps(tc.replay_todo(rows, stored_states={1: "claimed"}), sort_keys=True)
    shuffled = rows[:]
    random.Random(4).shuffle(shuffled)
    assert json.dumps(tc.replay_todo(shuffled, stored_states={1: "claimed"}), sort_keys=True) == a


def test_replay_dispatches_on_the_protocol():
    assert tc.replay("todo", life())["protocol"] == "todo"
    with pytest.raises(ValueError):
        tc.replay("hold", [])


def _write(tmp_path, rows, states=None):
    lines = [{"kind": "event", **r} for r in rows]
    lines += [{"kind": "state", "id": i, "state": s} for i, s in (states or {}).items()]
    p = tmp_path / "todo.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


def test_command_exits_nonzero_on_the_plant_and_names_the_event(tmp_path, capsys):
    p = _write(tmp_path, life()[:2] + [ev(3, "open", "claimed", "claim")])
    assert cli.main(["replay", "todo", str(p)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["protocol"] == "todo"
    assert out["counts"]["forbidden"] == 1 and out["forbidden"][0]["event_id"] == 3


def test_command_is_clean_and_byte_stable(tmp_path, capsys):
    p = _write(tmp_path, life(), {1: "done"})
    assert cli.main(["replay", "todo", str(p)]) == 0
    first = capsys.readouterr().out
    assert cli.main(["replay", "todo", str(p)]) == 0
    assert capsys.readouterr().out == first


class _Cur:
    def __init__(self, rows, status):
        self.rows, self.status, self.last, self.sql = rows, status, [], []

    def execute(self, sql, args=()):
        self.sql.append(sql)
        if "UTC_TIMESTAMP" in sql:
            self.last = [("2026-11-26 12:00:00",)]
        elif "DISTINCT activity_id" in sql:
            self.last = [(1,)]
        elif "FROM transition" in sql:
            self.last = [tuple(r[k] for k in ("id", "at", "activity_type", "activity_id", "from_state",
                                              "to_state", "reason", "desk_id", "role", "join_key", "meta", "n"))
                         for r in self.rows]
        elif "FROM todo" in sql:
            self.last = [(1, self.status)]
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.last[0]

    def fetchall(self):
        return self.last

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, **kw):
        return self.cur

    def rollback(self):
        pass

    def close(self):
        pass


def test_collect_writes_the_card_rows_and_stored_state_and_selects_only(tmp_path, monkeypatch):
    from agent_coord.server.records import db

    rows = [{**r, "role": "actor", "at": "2026-11-26 10:00:00"} for r in life()]
    cur = _Cur(rows, "retired")
    monkeypatch.setattr(db, "connect", lambda *a, **k: _Conn(cur))
    out = tmp_path / "t.jsonl"
    assert cli.main(["collect", "todo", "--since", "2026-11-26 00:00:00", "--out", str(out)]) == 0
    events, states, _ = cli.read_log(str(out))
    assert len(events) == 4 and states == {1: "retired"}
    assert all(s.lstrip().upper().startswith("SELECT") for s in cur.sql)
    assert any("a.deleted" in s for s in cur.sql)
    rep = tc.replay_todo(events, stored_states=states)
    assert rules(rep, "silent") == [("state_ahead", 4)]
