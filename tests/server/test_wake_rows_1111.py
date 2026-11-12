# -*- coding: utf-8 -*-
"""Card 1111 P1/P2: webhook failures land in the book; wake edges carry desk_id
and new wake rows fill cause_type/cause_id.

P1: post_desk's fail branch used to log and arm retry only, so wake_fail /
wake_retry edges were never written. A failed POST must write missed|queued
to error / wake_fail (meta: status, short why, retry 0|1). Arming retry
writes error to retry_armed / wake_retry.

P2: mill_push_put left cause_type, cause_id and route NULL, and every
non-done wake transition hardcoded desk_id=0 role=office. New rows must
set cause_type/cause_id when the payload names a letter or typed item;
wake edges must use wake.desk_id.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from agent_coord.server import wake as wake_mod
from agent_coord.server.records import push as rec_push
from tests.server.records.conftest import seed_names
from tests.server.webhook_fixtures import HOOK_URL, arm, opener

pytestmark = pytest.mark.sql

DESK = "ww1111d"
ROSTER = "ww1111"


def _desk_id(cn) -> int:
    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM name WHERE type='desk' AND name=%s", (DESK,))
        row = cur.fetchone()
        return int(row[0])
    finally:
        cur.close()


def _seed(cn) -> int:
    seed_names(cn, (ROSTER, "roster"), (DESK, "desk"))
    cn.commit()
    return _desk_id(cn)


def _wake_row(cn, wid: int) -> dict:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, desk_id, cause, cause_type, cause_id, route, state FROM wake WHERE id=%s",
            (wid,),
        )
        return dict(cur.fetchone() or {})
    finally:
        cur.close()


def _edges(cn, wid: int) -> list[dict]:
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT from_state, to_state, reason, desk_id, role, meta"
            " FROM transition WHERE activity_type='wake' AND activity_id=%s"
            " ORDER BY id",
            (wid,),
        )
        return list(cur.fetchall() or [])
    finally:
        cur.close()


def _meta(row: dict) -> dict:
    raw = row.get("meta")
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    if isinstance(raw, str):
        return json.loads(raw)
    return dict(raw)


def test_mail_wake_put_fills_cause_and_edge_desk(cn) -> None:
    """A letter wake stores cause_type=mail, cause_id, and edges use wake.desk_id."""
    did = _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "mail", {"kind": "mail", "id": 4211, "route": "r1"}, "missed"))
    cn.commit()
    row = _wake_row(cn, wid)
    assert int(row["desk_id"]) == did
    assert row["cause"] == "mail"
    assert row["cause_type"] == "mail"
    assert int(row["cause_id"] or 0) == 4211
    assert row["route"] == "r1"
    edges = _edges(cn, wid)
    assert edges
    assert all(int(e["desk_id"]) == did for e in edges)
    assert all(int(e["desk_id"]) != 0 for e in edges)
    reasons = {(e["from_state"], e["to_state"], e["reason"]) for e in edges}
    assert ("none", "queued", "wake_queue") in reasons
    assert ("queued", "missed", "wake_owed") in reasons


def test_hint_todo_wake_put_fills_cause(cn) -> None:
    _seed(cn)
    wid = rec_push.row_id(
        rec_push.put(cn, DESK, "hint", {"kind": "hint", "type": "todo", "id": 77}, "queued")
    )
    cn.commit()
    row = _wake_row(cn, wid)
    assert row["cause_type"] == "todo"
    assert int(row["cause_id"] or 0) == 77


def test_receipt_wake_put_fills_mail_cause(cn) -> None:
    _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "receipt", {"kind": "receipt", "id": 4212}, "missed"))
    cn.commit()
    row = _wake_row(cn, wid)
    assert row["cause_type"] == "mail"
    assert int(row["cause_id"] or 0) == 4212


def test_push_mark_and_take_use_wake_desk(cn) -> None:
    did = _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "mail", {"kind": "mail", "id": 4213}, "queued"))
    cn.commit()
    assert rec_push.mark(cn, wid, "missed") >= 0
    cn.commit()
    mark_edges = [e for e in _edges(cn, wid) if e["reason"] == "wake_owed" and e["from_state"] == "queued"]
    assert mark_edges
    assert all(int(e["desk_id"]) == did for e in mark_edges)
    rec_push.take(cn, DESK)
    cn.commit()
    deliver = [e for e in _edges(cn, wid) if e["reason"] == "wake_deliver"]
    assert deliver
    assert all(int(e["desk_id"]) == did for e in deliver)


class _Http:
    def __init__(self, status: int):
        self.status = status

    def read(self, _n: int = 0) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


def _http(status: int, body: bytes = b""):
    def fn(req, timeout=0):
        if 200 <= status <= 299:
            return _Http(status)
        raise urllib.error.HTTPError(HOOK_URL, status, "err", {}, io.BytesIO(body))

    return fn


def test_post_desk_http_fail_writes_wake_fail(cn, monkeypatch) -> None:
    """A 400 POST writes missed->error wake_fail; mark is not an action, no retry."""
    did = _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "mail", {"kind": "mail", "id": 4214}, "missed"))
    cn.commit()
    arm(monkeypatch)
    wake_mod.gate_clear(DESK, cn=cn)
    with opener(_http(400, b'{"message":"automation is paused"}')):
        assert wake_mod.post_desk(
            cn, DESK, {"kind": "mail", "id": 4214, "idem": "letter:4214:ww1111d"}, hint_id=4214, wake_id=wid
        ) == "error"
    cn.commit()
    row = _wake_row(cn, wid)
    assert row["state"] == "error"
    fails = [e for e in _edges(cn, wid) if e["reason"] == "wake_fail"]
    assert len(fails) == 1
    assert fails[0]["from_state"] in ("missed", "queued")
    assert fails[0]["to_state"] == "error"
    assert int(fails[0]["desk_id"]) == did
    meta = _meta(fails[0])
    assert int(meta.get("status") or 0) == 400
    assert meta.get("why") == "http"
    assert int(meta.get("retry") or 0) == 0
    assert not any(e["reason"] == "wake_retry" for e in _edges(cn, wid))
    # no host, url, or long receiver text in meta
    blob = json.dumps(meta)
    assert "hooks.example" not in blob
    assert "automation" not in blob.lower()


def test_post_desk_retryable_fail_writes_retry_armed(cn, monkeypatch) -> None:
    """A retryable 503 writes wake_fail with retry=1 and an error->retry_armed edge."""
    did = _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "mail", {"kind": "mail", "id": 4215}, "missed"))
    cn.commit()
    arm(monkeypatch)
    wake_mod.gate_clear(DESK, cn=cn)
    with opener(_http(503)):
        assert wake_mod.post_desk(
            cn, DESK, {"kind": "mail", "id": 4215, "idem": "letter:4215:ww1111d"}, hint_id=4215, wake_id=wid
        ) == "error"
    cn.commit()
    fails = [e for e in _edges(cn, wid) if e["reason"] == "wake_fail"]
    assert len(fails) == 1
    assert int(_meta(fails[0]).get("retry") or 0) == 1
    assert int(fails[0]["desk_id"]) == did
    retries = [e for e in _edges(cn, wid) if e["reason"] == "wake_retry"]
    assert len(retries) == 1
    assert retries[0]["from_state"] == "error"
    assert retries[0]["to_state"] == "retry_armed"
    assert int(retries[0]["desk_id"]) == did
    assert _wake_row(cn, wid)["state"] == "retry_armed"

def test_retry_armed_row_is_visible_to_waiting(cn, monkeypatch) -> None:
    """#832 ring_waiting still sees a hint whose POST failed and armed retry."""
    _seed(cn)
    wid = rec_push.row_id(
        rec_push.put(cn, DESK, "hint", {"kind": "hint", "type": "todo", "id": 991}, "missed")
    )
    cn.commit()
    arm(monkeypatch)
    monkeypatch.setattr(wake_mod, "_schedule", lambda *a, **k: None)
    wake_mod.gate_clear(DESK, cn=cn)
    with opener(_http(503)):
        assert (
            wake_mod.post_desk(
                cn,
                DESK,
                {"kind": "hint", "type": "todo", "id": 991, "idem": "todo:991:ww1111d"},
                hint_id=991,
                wake_id=wid,
            )
            == "error"
        )
    cn.commit()
    assert _wake_row(cn, wid)["state"] == "retry_armed"
    got = rec_push.waiting(cn, DESK)
    assert got is not None
    assert int(got["id"]) == wid


def test_post_without_wake_row_does_not_stamp_other_row(cn, monkeypatch) -> None:
    """A POST with no wake row (wake_id=0, tw.event) must not stamp another row."""
    _seed(cn)
    wid = rec_push.row_id(rec_push.put(cn, DESK, "mail", {"kind": "mail", "id": 5501}, "missed"))
    cn.commit()
    arm(monkeypatch)
    monkeypatch.setattr(wake_mod, "_schedule", lambda *a, **k: None)
    wake_mod.gate_clear(DESK, cn=cn)
    with opener(_http(400)):
        assert wake_mod.post_desk(cn, DESK, {"kind": "tw", "event": "exit", "task": 7}) == "error"
    cn.commit()
    row = _wake_row(cn, wid)
    assert row["state"] == "missed"
    assert not any(e["reason"] in ("wake_fail", "wake_retry") for e in _edges(cn, wid))

