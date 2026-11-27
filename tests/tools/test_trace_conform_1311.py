"""Card 1311: the wake trace replay reports forbidden, silent and unmodelled steps.

Each rule has its own planted fixture, so a mutant that drops one rule fails
one test. The done-when plant (a wake lease marked done twice) is reported by
event id and makes the replay command exit nonzero.
"""
from __future__ import annotations

import json
import random

from agent_coord.server import trace_conform as tc
from tools import trace_conform as cli

D1, D2 = 7, 8


def ev(i, frm, to, reason, *, wake=1, desk=D1, key=None, at="2026-11-26 10:00:00", n=1):
    return {"id": i, "at": at, "activity_type": "wake", "activity_id": wake, "from_state": frm,
            "to_state": to, "reason": reason, "desk_id": desk, "join_key": key, "meta": None, "n": n}


def clean():
    return [
        ev(1, "none", "queued", "wake_queue"),
        ev(2, "queued", "sent", "wake_sent"),
        ev(3, "ring", "lease_live", "wake_sent", key="lease:t1"),
        ev(4, "sent", "taken", "wake_deliver"),
        ev(5, "lease_live", "done", "wake_done", key="lease:t1", at="2026-11-26 10:05:00"),
    ]


def rules(rep, bucket):
    return [(f["rule"], f["event_id"]) for f in rep[bucket]]


def test_step_table_matches_the_model_edges():
    assert set(tc.WAKE_STEPS) == set(tc.model_edges("wake"))


def test_clean_wake_has_no_findings():
    rep = tc.replay_wake(clean(), stored_states={1: "taken"}, window_end="2026-11-26 12:00:00")
    assert rep["counts"] == {"forbidden": 0, "silent": 0, "unmodelled": 0}
    assert rep["events"] == 5
    assert "W9" not in rep["quiet_steps"] and "W12" in rep["quiet_steps"]


def test_planted_done_twice_is_forbidden_by_id():
    rows = clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")]
    rep = tc.replay_wake(rows)
    assert rules(rep, "forbidden") == [("no_dup_done", 6)]
    assert rep["forbidden"][0]["path"] == [3, 5, 6]


def test_end_by_another_desk_is_stale_done():
    rows = clean()[:4] + [ev(5, "lease_live", "done", "wake_done", key="lease:t1", desk=D2)]
    assert rules(tc.replay_wake(rows), "forbidden") == [("no_stale_done", 5)]


def test_end_on_another_wake_is_stale_done():
    rows = clean()[:4] + [ev(5, "lease_live", "expired", "wake_expire", key="lease:t1", wake=2)]
    assert rules(tc.replay_wake(rows), "forbidden") == [("no_stale_done", 5)]


def test_second_ring_is_forbidden():
    rows = clean()[:3] + [ev(4, "ring", "lease_live", "wake_sent", key="lease:t1")]
    assert rules(tc.replay_wake(rows), "forbidden") == [("lease_rerung", 4)]


def test_queue_step_from_the_wrong_state_is_forbidden():
    rows = [ev(1, "none", "queued", "wake_queue"), ev(2, "queued", "sent", "wake_sent"),
            ev(3, "missed", "taken", "wake_deliver")]
    rep = tc.replay_wake(rows)
    assert rules(rep, "forbidden") == [("from_state", 3)]
    assert rep["forbidden"][0]["step"] == "Q6"


def test_unmodelled_edge_is_counted_not_forbidden():
    rows = [ev(1, "none", "queued", "wake_queue"), ev(2, "queued", "error", "wake_fail"),
            ev(3, "error", "retry_armed", "wake_retry"), ev(4, "retry_armed", "taken", "wake_deliver")]
    rep = tc.replay_wake(rows)
    assert rep["counts"]["forbidden"] == 0
    assert [u["event_id"] for u in rep["unmodelled"]] == [4]
    assert rep["unmodelled"][0]["edge"] == ["retry_armed", "taken", "wake_deliver"]


def test_silent_rules_each_fire():
    no_start = [ev(1, "queued", "sent", "wake_sent")]
    assert rules(tc.replay_wake(no_start), "silent") == [("no_start_event", 1)]
    no_ring = [ev(1, "lease_live", "done", "wake_done", key="lease:x")]
    assert rules(tc.replay_wake(no_ring), "silent") == [("lease_no_ring", 1)]
    open_lease = [ev(1, "ring", "lease_live", "wake_sent", key="lease:x", at="2026-11-26 10:00:00")]
    assert rules(tc.replay_wake(open_lease, window_end="2026-11-26 11:00:01"), "silent") == [
        ("lease_open_past_cap", 1)]
    assert tc.replay_wake(open_lease, window_end="2026-11-26 10:59:59")["counts"]["silent"] == 0
    ahead = clean()[:2]
    assert rules(tc.replay_wake(ahead, stored_states={1: "taken"}), "silent") == [("state_ahead", 2)]


def test_compress_even_count_is_back_at_from_state():
    rows = [ev(1, "none", "queued", "wake_queue"), ev(2, "queued", "sent", "wake_sent", n=2),
            ev(3, "queued", "taken", "wake_deliver")]
    assert tc.replay_wake(rows)["counts"]["forbidden"] == 0


def test_other_activity_types_are_ignored():
    rows = clean() + [dict(ev(9, "held", "free", "hold_drop"), activity_type="hold")]
    assert tc.replay_wake(rows)["events"] == 5


def test_order_of_input_does_not_change_the_report():
    rows = clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")]
    shuffled = rows[:]
    random.Random(4).shuffle(shuffled)
    assert tc.replay_wake(rows) == tc.replay_wake(shuffled)


def _write(tmp_path, rows, states=None, window=None):
    lines = []
    if window:
        lines.append({"kind": "window", **window})
    lines += [{"kind": "state", "id": k, "state": v} for k, v in (states or {}).items()]
    lines += [{"kind": "event", **r} for r in rows]
    p = tmp_path / "events.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return p


def test_command_exits_nonzero_on_the_plant_and_names_the_event(tmp_path, capsys):
    p = _write(tmp_path, clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")])
    assert cli.main(["replay", "wake", str(p)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["forbidden"] == 1 and out["forbidden"][0]["event_id"] == 6


def test_command_is_clean_and_byte_stable(tmp_path, capsys):
    p = _write(tmp_path, clean(), {1: "taken"}, {"since": "2026-11-26 00:00:00", "until": "2026-11-26 12:00:00"})
    assert cli.main(["replay", "wake", str(p)]) == 0
    first = capsys.readouterr().out
    assert cli.main(["replay", "wake", str(p)]) == 0
    assert capsys.readouterr().out == first
    assert json.loads(first)["window"]["until"] == "2026-11-26 12:00:00"


def test_strict_fails_on_silent_and_unmodelled(tmp_path):
    p = _write(tmp_path, [ev(1, "queued", "sent", "wake_sent")])
    assert cli.main(["replay", "wake", str(p)]) == 0
    assert cli.main(["replay", "wake", str(p), "--strict"]) == 1


def test_bad_input_exits_2(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    assert cli.main(["replay", "wake", str(p)]) == 2
    assert cli.main(["replay", "wake", str(tmp_path / "missing.jsonl")]) == 2


def test_unkeyed_lease_row_is_an_edge_check_only():
    rows = clean()[:2] + [ev(3, "lease_live", "idle", "wake_done"), ev(4, "sent", "taken", "wake_deliver")]
    rep = tc.replay_wake(rows, stored_states={1: "taken"})
    assert rep["counts"] == {"forbidden": 0, "silent": 0, "unmodelled": 1}
    assert rep["unmodelled"][0]["event_id"] == 3


def test_report_never_carries_a_lease_token():
    rows = clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")]
    rep = tc.replay_wake(rows)
    assert "t1" not in json.dumps(rep)
    assert rep["forbidden"][0]["object"] == "wake:1/lease@3"
