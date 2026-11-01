"""7-day push rollup writes one expired line per desk and does not age that line out.

F17 / card 1022: the drop is mill_push_expire (wall start, then twice a day), not every take.
Hand-back marks wake taken (row stays); expire rolls untaken hint/mail/receipt older than 7 days.
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.sql

from agent_coord.install import migrate
from agent_coord.server.records import push as rec_push
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

def _desk(cn, name: str) -> int:
    return seed_names(cn, (name, "desk"))[0]

def _push(cn, desk_name: str, desk_id: int, kind: str, outcome: str, days_ago: int, payload: dict) -> int:
    rid = rec_push.row_id(rec_push.put(cn, desk_name, kind, payload, outcome))
    cur = cn.cursor()
    try:
        cur.execute(
            "UPDATE wake SET created = DATE_SUB(NOW(6), INTERVAL %s DAY) WHERE id = %s",
            (int(days_ago), rid),
        )
        cn.commit()
    finally:
        cur.close()
    return rid

def _rows(cn, desk_id: int, *, include_taken: bool = False) -> list[dict]:
    cur = cn.cursor(dictionary=True)
    try:
        sql = (
            "SELECT id, cause AS kind, payload, state AS outcome, created FROM wake "
            "WHERE desk_id = %s"
        )
        if not include_taken:
            sql += " AND state <> 'taken'"
        sql += " ORDER BY id"
        cur.execute(sql, (desk_id,))
        out = []
        for row in cur.fetchall():
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            row["payload"] = payload
            out.append(row)
        return out
    finally:
        cur.close()

def _counts(item: dict) -> dict:
    return {k: int(item[k]) for k in ("hint", "mail", "receipt", "missed", "error")}

def _blob(item: dict) -> str:
    return json.dumps(item, default=str)

def test_fresh_rows_have_no_expired_line(cn) -> None:
    desk = _desk(cn, "push-expire-fresh")
    _push(cn, "push-expire-fresh", desk, "mail", "missed", 1, {"id": 1, "body": "still-here"})
    items = rec_push.take(cn, "push-expire-fresh")
    assert [item["kind"] for item in items] == ["mail"]
    assert items[0]["body"] == "still-here"
    assert _rows(cn, desk) == []

def test_other_desk_sync_writes_one_line_and_take_returns_it(cn) -> None:
    away = _desk(cn, "push-expire-away")
    other = _desk(cn, "push-expire-other")
    _push(cn, "push-expire-away", away, "hint", "missed", 40, {"type": "todo", "id": 9, "body": "old-hint"})
    _push(cn, "push-expire-away", away, "mail", "error", 35, {"id": 8, "body": "old-mail"})
    _push(cn, "push-expire-away", away, "receipt", "sent", 31, {"id": 8, "body": "old-receipt"})
    _push(cn, "push-expire-other", other, "hint", "sent", 1, {"type": "todo", "id": 3, "hint": "TODO"})
    rec_push.expire(cn)
    other_items = rec_push.take(cn, "push-expire-other")
    assert [item["kind"] for item in other_items] == ["hint"]
    queued = _rows(cn, away)
    assert [row["kind"] for row in queued] == ["expired"]
    payload = queued[0]["payload"]
    assert set(payload) == {
        "window_start",
        "window_end",
        "hint",
        "mail",
        "receipt",
        "missed",
        "error",
    }
    assert payload["window_start"] <= payload["window_end"]
    assert [int(payload[k]) for k in ("hint", "mail", "receipt", "missed", "error")] == [
        1,
        1,
        1,
        1,
        1,
    ]
    assert "old-hint" not in json.dumps(payload)
    items = rec_push.take(cn, "push-expire-away")
    assert len(items) == 1
    assert items[0]["kind"] == "expired"
    assert items[0]["outcome"] == "missed"
    assert _counts(items[0]) == {
        "hint": 1,
        "mail": 1,
        "receipt": 1,
        "missed": 1,
        "error": 1,
    }
    assert "body" not in items[0]
    assert rec_push.take(cn, "push-expire-away") == []

def test_later_window_updates_the_same_line(cn) -> None:
    away = _desk(cn, "push-expire-later")
    other = _desk(cn, "push-expire-later-other")
    _push(cn, "push-expire-later", away, "hint", "missed", 40, {"body": "first"})
    rec_push.expire(cn)
    first = _rows(cn, away)
    assert len(first) == 1
    line_id = int(first[0]["id"])
    created = str(first[0]["created"])
    _push(cn, "push-expire-later", away, "mail", "missed", 40, {"body": "second"})
    _push(cn, "push-expire-later-other", other, "hint", "sent", 1, {"hint": "TODO"})
    rec_push.expire(cn)
    again = _rows(cn, away)
    assert [int(row["id"]) for row in again] == [line_id]
    assert int(again[0]["payload"]["hint"]) == 1
    assert int(again[0]["payload"]["mail"]) == 1
    assert int(again[0]["payload"]["missed"]) == 2
    assert str(again[0]["created"]) >= created
    items = rec_push.take(cn, "push-expire-later")
    assert [item["kind"] for item in items] == ["expired"]
    assert _counts(items[0])["mail"] == 1
    assert "second" not in _blob(items[0])

def test_fresh_row_comes_out_before_the_expired_line(cn) -> None:
    desk = _desk(cn, "push-expire-order")
    _push(cn, "push-expire-order", desk, "hint", "missed", 40, {"body": "gone"})
    _push(cn, "push-expire-order", desk, "mail", "sent", 1, {"id": 4, "body": "kept"})
    rec_push.expire(cn)
    items = rec_push.take(cn, "push-expire-order")
    assert [item["kind"] for item in items] == ["mail", "expired"]
    assert items[0]["body"] == "kept"
    assert "gone" not in _blob(items[1])
    assert _counts(items[1])["hint"] == 1

def test_expired_line_does_not_age_out(cn) -> None:
    away = _desk(cn, "push-expire-stay")
    _push(cn, "push-expire-stay", away, "hint", "error", 40, {"body": "drop-me"})
    rec_push.expire(cn)
    cur = cn.cursor()
    try:
        cur.execute(
            "UPDATE wake SET created = DATE_SUB(NOW(6), INTERVAL 40 DAY) "
            "WHERE desk_id = %s AND cause = 'expired'",
            (away,),
        )
        cn.commit()
    finally:
        cur.close()
    other = _desk(cn, "push-expire-stay-other")
    _push(cn, "push-expire-stay-other", other, "mail", "sent", 40, {"body": "other-old"})
    rec_push.expire(cn)
    still = _rows(cn, away)
    assert [row["kind"] for row in still] == ["expired"]
    items = rec_push.take(cn, "push-expire-stay")
    assert [item["kind"] for item in items] == ["expired"]
    assert _counts(items[0])["error"] == 1

def test_put_rejects_expired_kind(cn) -> None:
    _desk(cn, "push-expire-put")
    with pytest.raises(Exception, match="push: kind"):
        rec_push.put(cn, "push-expire-put", "expired", {"hint": 1}, "missed")

def test_ensure_refreshes_sp_and_expire_works(cn) -> None:
    """Tip books use VARCHAR cause on wake; ensure refreshes mill_push_* and expire still works."""
    out = migrate.ensure(cn)
    # No ENUM widen on folded books; sp_push may or may not re-apply depending on hash.
    assert "wake.kind.expired" not in out.get("applied", [])
    assert "push_queue.kind.expired" not in out.get("applied", [])
    desk = _desk(cn, "push-expire-ensure")
    _push(cn, "push-expire-ensure", desk, "mail", "missed", 40, {"body": "via-ensure"})
    rec_push.expire(cn)
    items = rec_push.take(cn, "push-expire-ensure")
    assert [item["kind"] for item in items] == ["expired"]
    assert "via-ensure" not in _blob(items[0])

def _clear(cn) -> None:
    cur = cn.cursor()
    try:
        # Mark everything taken so expire/take see an empty untaken queue.
        cur.execute("UPDATE wake SET state = 'taken' WHERE state <> 'taken'")
        cn.commit()
    finally:
        cur.close()

def test_take_does_not_sweep_other_desks(cn) -> None:
    """F17: a take reads only this desk. Another desk's old rows wait for the sweep."""
    _clear(cn)
    away = _desk(cn, "push-f17-away")
    me = _desk(cn, "push-f17-me")
    _push(cn, "push-f17-away", away, "mail", "missed", 40, {"body": "away-old"})
    _push(cn, "push-f17-me", me, "hint", "sent", 1, {"hint": "TODO"})
    assert [i["kind"] for i in rec_push.take(cn, "push-f17-me")] == ["hint"]
    left = _rows(cn, away)
    assert [r["kind"] for r in left] == ["mail"]
    assert left[0]["payload"]["body"] == "away-old"

def test_take_never_hands_out_an_old_row_before_the_sweep(cn) -> None:
    """F17: a row past 7 days is not returned, even when the sweep has not run yet."""
    _clear(cn)
    desk = _desk(cn, "push-f17-old")
    _push(cn, "push-f17-old", desk, "mail", "missed", 40, {"body": "too-old"})
    fresh = _push(cn, "push-f17-old", desk, "mail", "sent", 1, {"id": 5, "body": "fresh"})
    items = rec_push.take(cn, "push-f17-old")
    assert [i["body"] for i in items] == ["fresh"]
    assert "too-old" not in _blob(items)
    left = _rows(cn, desk)
    assert [r["kind"] for r in left] == ["mail"]
    assert int(left[0]["id"]) != fresh
    out = rec_push.expire(cn)
    assert out["deleted"] == 1
    items = rec_push.take(cn, "push-f17-old")
    assert [i["kind"] for i in items] == ["expired"]
    assert _counts(items[0])["mail"] == 1
    assert _rows(cn, desk) == []

def test_expire_counts_and_second_pass_is_a_no_op(cn) -> None:
    """F17: the sweep reports what it dropped; running it again changes nothing."""
    _clear(cn)
    a = _desk(cn, "push-f17-a")
    b = _desk(cn, "push-f17-b")
    _push(cn, "push-f17-a", a, "hint", "missed", 31, {"body": "a1"})
    _push(cn, "push-f17-a", a, "mail", "error", 45, {"body": "a2"})
    _push(cn, "push-f17-b", b, "receipt", "sent", 60, {"body": "b1"})
    _push(cn, "push-f17-b", b, "mail", "sent", 2, {"body": "b-fresh"})
    first = rec_push.expire(cn)
    assert first["deleted"] == 3
    assert first["cut"]
    snap = [(r["id"], r["kind"], json.dumps(r["payload"], sort_keys=True)) for d in (a, b) for r in _rows(cn, d)]
    assert sorted(k for _i, k, _p in snap) == ["expired", "expired", "mail"]
    second = rec_push.expire(cn)
    assert second["deleted"] == 0
    again = [(r["id"], r["kind"], json.dumps(r["payload"], sort_keys=True)) for d in (a, b) for r in _rows(cn, d)]
    assert again == snap

def test_expire_on_a_fresh_queue_writes_no_line(cn) -> None:
    _clear(cn)
    desk = _desk(cn, "push-f17-fresh")
    _push(cn, "push-f17-fresh", desk, "mail", "sent", 1, {"body": "inside-window"})
    assert rec_push.expire(cn)["deleted"] == 0
    assert [r["kind"] for r in _rows(cn, desk)] == ["mail"]

def test_take_for_an_unknown_desk_is_empty(cn) -> None:
    assert rec_push.take(cn, "push-f17-nobody") == []

def test_second_expire_window_after_take_gets_new_marker(cn) -> None:
    """R2 / card 1032: after the desk takes the expired marker, a later window gets a new one."""
    away = _desk(cn, "push-expire-retaken")
    _push(cn, "push-expire-retaken", away, "mail", "missed", 40, {"body": "first-window"})
    rec_push.expire(cn)
    take1 = rec_push.take(cn, "push-expire-retaken")
    assert [i["kind"] for i in take1] == ["expired"]
    assert _counts(take1[0])["mail"] == 1
    assert _rows(cn, away) == []
    # later window while the first marker is taken
    _push(cn, "push-expire-retaken", away, "mail", "missed", 40, {"body": "second-mail"})
    _push(cn, "push-expire-retaken", away, "hint", "missed", 40, {"body": "second-hint"})
    rec_push.expire(cn)
    take2 = rec_push.take(cn, "push-expire-retaken")
    assert [i["kind"] for i in take2] == ["expired"], take2
    assert _counts(take2[0])["mail"] == 1
    assert _counts(take2[0])["hint"] == 1
    assert "second-mail" not in _blob(take2[0])
    assert "second-hint" not in _blob(take2[0])

