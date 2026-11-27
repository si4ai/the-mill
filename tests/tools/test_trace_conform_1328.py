"""Card 1328: trace_conform follow-ups from Validator's #525 warnings.

W1 a bad field is a data error (exit 2), never a conformance failure (exit 1).
W2 collected rows hold no lease token in the clear.
W3 a ring after the lease has ended is a forbidden second ring.
"""
from __future__ import annotations

import json

import pytest

from agent_coord.server import trace_conform as tc
from tools import trace_conform as cli

D1 = 7


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

GOOD = {"kind": "event", "id": 1, "at": "2026-11-26 10:00:00", "activity_type": "wake",
        "activity_id": 1, "from_state": "none", "to_state": "queued", "reason": "wake_queue",
        "desk_id": 7, "join_key": None, "meta": None, "n": 1}


def _log(tmp_path, *objs):
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(o if isinstance(o, str) else json.dumps(o) for o in objs) + "\n", encoding="utf-8")
    return p


@pytest.mark.parametrize("bad", [
    {"kind": "state", "id": "x", "state": "taken"},
    {"kind": "state", "id": 5},
    {"kind": "state", "state": "taken"},
    {"kind": "event", "id": "abc", "activity_type": "wake", "activity_id": 1, "to_state": "queued"},
    {"kind": "event", "activity_type": "wake", "activity_id": 1, "to_state": "queued"},
    {"kind": "event", "id": 1, "activity_type": "wake", "to_state": "queued"},
    {"kind": "event", "id": 1, "activity_type": "wake", "activity_id": 1},
    {"kind": "event", "id": 1, "activity_type": "wake", "activity_id": [1], "to_state": "queued"},
    {"kind": "event", "id": None, "activity_type": "wake", "activity_id": 1, "to_state": "queued"},
    {**GOOD, "desk_id": "me"},
    {**GOOD, "n": "many"},
])
def test_bad_field_exits_2_not_1(tmp_path, capsys, bad):
    assert cli.main(["replay", "wake", str(_log(tmp_path, GOOD, bad))]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and "bad" in err


def test_good_line_still_replays(tmp_path):
    assert cli.main(["replay", "wake", str(_log(tmp_path, GOOD))]) == 0


def test_a_forbidden_step_is_still_exit_1(tmp_path):
    rows = clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")]
    p = _log(tmp_path, *[{"kind": "event", **r} for r in rows])
    assert cli.main(["replay", "wake", str(p)]) == 1


def test_redact_hides_the_token_and_keeps_the_grouping():
    key = b"k" * 32
    a = cli.redact_row(ev(3, "ring", "lease_live", "wake_sent", key="lease:SECRET1"), key)
    b = cli.redact_row(dict(ev(5, "lease_live", "done", "wake_done", key="lease:SECRET1"),
                            meta=json.dumps({"lease": "SECRET1", "late_s": 2})), key)
    c = cli.redact_row(ev(7, "ring", "lease_live", "wake_sent", key="lease:OTHER"), key)
    assert "SECRET1" not in json.dumps([a, b, c]) and "OTHER" not in json.dumps(c)
    assert a["join_key"] == b["join_key"] != c["join_key"]
    assert a["join_key"].startswith("lease:") and len(a["join_key"]) == len("lease:") + 12
    assert b["meta"] == {"lease": b["meta"]["lease"], "late_s": 2} and b["meta"]["lease"] != "SECRET1"
    assert cli.redact_row(ev(1, "none", "queued", "wake_queue"), key)["join_key"] is None


def test_redact_key_differs_per_run():
    row = ev(3, "ring", "lease_live", "wake_sent", key="lease:SECRET1")
    assert cli.redact_row(row, b"a" * 32)["join_key"] != cli.redact_row(row, b"b" * 32)["join_key"]


def test_redacted_rows_replay_the_same_as_raw_rows():
    rows = clean() + [ev(6, "lease_live", "done", "wake_done", key="lease:t1")]
    red = [cli.redact_row(r, b"k" * 32) for r in rows]
    raw_rep, red_rep = tc.replay_wake(rows), tc.replay_wake(red)
    assert raw_rep["counts"] == red_rep["counts"]
    assert rules(raw_rep, "forbidden") == rules(red_rep, "forbidden") == [("no_dup_done", 6)]


def test_ring_after_the_lease_ended_is_a_second_ring():
    rows = clean() + [ev(6, "ring", "lease_live", "wake_sent", key="lease:t1")]
    rep = tc.replay_wake(rows)
    assert rules(rep, "forbidden") == [("lease_rerung", 6)]
    assert rep["forbidden"][0]["path"] == [3, 5, 6]


def test_ring_after_expire_and_after_clear_too():
    for frm, to, reason in (("lease_live", "expired", "wake_expire"), ("lease_live", "cleared", "clear")):
        rows = [ev(1, "ring", "lease_live", "wake_sent", key="lease:t1"), ev(2, frm, to, reason, key="lease:t1"),
                ev(3, "ring", "lease_live", "wake_sent", key="lease:t1")]
        assert rules(tc.replay_wake(rows), "forbidden") == [("lease_rerung", 3)]


def test_ring_after_an_end_that_had_no_ring_is_a_second_ring():
    rows = [ev(1, "lease_live", "done", "wake_done", key="lease:t1"),
            ev(2, "ring", "lease_live", "wake_sent", key="lease:t1")]
    rep = tc.replay_wake(rows)
    assert rules(rep, "forbidden") == [("lease_rerung", 2)]
    assert rules(rep, "silent") == [("lease_no_ring", 1)]


class _FakeCursor:
    def __init__(self, rows):
        self.rows, self.last = rows, []

    def execute(self, sql, args=()):
        if "UTC_TIMESTAMP" in sql:
            self.last = [("2026-11-26 12:00:00",)]
        elif "DISTINCT activity_id" in sql:
            self.last = [(1,)]
        elif "FROM transition" in sql:
            self.last = list(self.rows)
        elif "FROM wake" in sql:
            self.last = [(1, "taken")]

    def fetchone(self):
        return self.last[0]

    def fetchall(self):
        return self.last

    def close(self):
        pass


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self, **kw):
        return _FakeCursor(self.rows)

    def rollback(self):
        pass

    def close(self):
        pass


def test_collect_writes_no_token_and_a_private_file(tmp_path, monkeypatch):
    import os
    import stat

    from agent_coord.server.records import db

    cols = ("id", "at", "activity_type", "activity_id", "from_state", "to_state", "reason", "desk_id",
            "role", "join_key", "meta", "n")
    rows = [
        (3, "2026-11-26 10:00:00", "wake", 1, "ring", "lease_live", "wake_sent", 7, "office",
         "lease:SECRETTOKEN", '{"lease": "SECRETTOKEN"}', 1),
        (5, "2026-11-26 10:05:00", "wake", 1, "lease_live", "done", "wake_done", 7, "actor",
         "lease:SECRETTOKEN", '{"lease": "SECRETTOKEN"}', 1),
    ]
    assert len(cols) == len(rows[0])
    monkeypatch.setattr(db, "connect", lambda *a, **k: _FakeConn(rows))
    out = tmp_path / "w.jsonl"
    assert cli.main(["collect", "wake", "--since", "2026-11-26 00:00:00", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "SECRETTOKEN" not in text
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    events, states, window = cli.read_log(str(out))
    assert len(events) == 2 and events[0]["join_key"] == events[1]["join_key"]
    assert tc.replay_wake(events, stored_states=states)["counts"] == {"forbidden": 0, "silent": 0, "unmodelled": 0}
