"""Card 1289: the tw.event boundary for pr and the run byte counts (no SQL)."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


class _Book:
    _cn = object()


@pytest.fixture
def stored(monkeypatch):
    got = []
    monkeypatch.setattr("agent_coord.server.records.doing.task_event",
                        lambda cn, desk, meta, **kw: got.append(dict(meta)))
    monkeypatch.setattr("agent_coord.server.records.db.request_tx", lambda cn, run: run())
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **kw: None)
    return got


def _send(kind, **extra):
    body = {"verb": "tw.event", "watch_id": "w1", "kind": kind, **extra}
    return rpc._h_tw_event(_Book(), body, "the-mill", "builder")


def test_start_keeps_card_and_pr(stored):
    _send("start", card=1289, pr=512)
    assert stored[-1]["card"] == 1289
    assert stored[-1]["pr"] == 512


@pytest.mark.parametrize("kind,extra", [("exit", {"exit_code": 0}), ("exit", {"exit_code": 3}), ("crash", {})])
def test_terminal_hops_keep_byte_counts(stored, kind, extra):
    _send(kind, bytes_in=0, bytes_out=2**53 - 1, **extra)
    assert stored[-1]["bytes_in"] == 0
    assert stored[-1]["bytes_out"] == 2**53 - 1


def test_keys_on_other_kinds_are_not_stored(stored):
    _send("start", bytes_in=5, bytes_out=6)
    _send("exit", exit_code=0, pr=7)
    _send("stall", cause="quiet", bytes_in=5, pr=7)
    for meta in stored:
        assert not {"bytes_in", "bytes_out", "pr"} & set(meta)


@pytest.mark.parametrize("kind,name,bad", [
    ("exit", "bytes_in", -1),
    ("exit", "bytes_out", True),
    ("crash", "bytes_in", 1.5),
    ("crash", "bytes_out", "12"),
    ("exit", "bytes_in", 2**53),
    ("start", "pr", 0),
    ("start", "pr", False),
    ("start", "pr", "512"),
])
def test_bad_counts_are_refused_and_nothing_is_stored(stored, kind, name, bad):
    with pytest.raises(CoordError, match=f"tw.event: {name} must be a"):
        _send(kind, exit_code=0, **{name: bad})
    assert stored == []
