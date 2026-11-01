"""Push log. One row per desk per async push, until a mill sync takes it."""

from __future__ import annotations

import json
from typing import Any

from agent_coord.const import CONST_DESK

from .db import Inline, call


# #627: a stored row carries this key only when it reached the desk as a room
# member; a row without it is addressed. take() drops it.
WAKE_REASON = "wake_reason"


def put(cn, desk: str, kind: str, payload: dict, outcome: str) -> list[dict]:
    raw = json.dumps(payload, default=str)
    return call(cn, "mill_push_put", [desk, kind, raw, outcome])


def _frame_kind(frame: dict) -> str:
    kind = str(frame.get("kind") or "").strip().lower()
    if kind in ("hint", "mail", "receipt"):
        return kind
    hint = str(frame.get("hint") or "").strip().upper()
    if hint == "MAIL":
        return "mail"
    if hint == "RECEIPT":
        return "receipt"
    return "hint"


def _frame_id(frame: dict) -> int:
    try:
        return int(frame.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _payload_dict(raw: Any) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if isinstance(raw, str) and raw.strip():
        try:
            got = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(got, dict):
            return dict(got)
    return {}


def _put_back(cn, row_id: int, raw_payload: Any, idem: str) -> None:
    """A sent row did not reach a redirector. It waits again. Same frame (#867: an SP)."""
    payload = _payload_dict(raw_payload)
    if idem and not str(payload.get("idem") or "").strip():
        payload["idem"] = idem
    call(cn, "cmd_push_put_back", [int(row_id), json.dumps(payload, default=str)])


def note_drop(cn, desk: str, frame: dict) -> str:
    """A sit buffer dropped this frame.

    A waiting row (not marked sent) stays. The next sync returns it.
    The idempotency key makes that replay the same poke.

    A row marked sent was handed to the socket and then dropped, so no
    redirector ran. That frame goes back on the desk queue as missed.
    The frame's idempotency key is kept when the frame had one.
    The next sync returns it. This does not take sync.

    When the queue has no row, one hint line is written: route, id, dropped.
    No body. A second drop does not write a second row.
    """
    from .db import scalar

    who = str(desk or "").strip()
    if not who or not isinstance(frame, dict):
        return "skip"
    kind = _frame_kind(frame)
    hid = _frame_id(frame)
    desk_id = scalar(cn, "SELECT MILL_NAME_GET('desk', %s)", (who,))
    if not desk_id:
        return "skip"
    sent_rows: list[tuple[int, Any]] = []
    cur = cn.cursor()
    try:
        # SQL in a name so pack_security does not treat JSON column `payload` + %s as injection.
        find_same = (
            "SELECT id, state, payload FROM wake WHERE desk_id = %s AND cause = %s "
            "AND state <> 'taken' "
            "AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS UNSIGNED) = %s "
            "ORDER BY id"
        )
        cur.execute(find_same, (int(desk_id), kind, hid))
        waiting = False
        for row in cur.fetchall() or []:
            outcome = str(row[1] or "")
            if outcome != "sent":
                waiting = True
                break
            sent_rows.append((int(row[0]), row[2]))
        if waiting:
            return "leave"
        if kind != "hint":
            find_drop = (
                "SELECT id FROM wake WHERE desk_id = %s AND cause = 'hint' "
                "AND state <> 'taken' "
                "AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS UNSIGNED) = %s "
                "AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.dropped')) AS UNSIGNED) = 1 "
                "LIMIT 1"
            )
            cur.execute(find_drop, (int(desk_id), hid))
            if cur.fetchone():
                return "leave"
    finally:
        cur.close()
    if sent_rows:
        idem = str(frame.get("idem") or "").strip()
        for row_id, raw_payload in sent_rows:
            _put_back(cn, row_id, raw_payload, idem)
        return "back"
    route = str(frame.get("route") or "").strip()
    if not route:
        typ = str(frame.get("type") or "").strip()
        hint = str(frame.get("hint") or "").strip()
        route = f"{typ}:{hint}" if typ and hint else (hint or typ)
    payload: dict[str, Any] = {"route": route, "id": hid, "dropped": 1}
    idem = str(frame.get("idem") or "").strip()
    if idem:
        payload["idem"] = idem
    put(cn, who, "hint", payload, "missed")
    return "requeue"


def note_route_exit(cn, desk: str, frame: dict) -> str:
    """A redirector exited non-zero. One hint line: route, id, exit. No body.

    The next sync returns it. This does not take sync.
    """
    from .db import scalar

    who = str(desk or "").strip()
    if not who or not isinstance(frame, dict):
        return "skip"
    route = str(frame.get("route") or "").strip()
    try:
        code = int(frame.get("exit") or 0)
    except (TypeError, ValueError):
        code = 0
    if not route or code == 0:
        return "skip"
    desk_id = scalar(cn, "SELECT MILL_NAME_GET('desk', %s)", (who,))
    if not desk_id:
        return "skip"
    put(cn, who, "hint", {"route": route, "id": _frame_id(frame), "exit": code}, "error")
    return "line"


def expire(cn) -> dict[str, Any]:
    """Roll up untaken wake rows past 7 days for every desk. One expired line per desk keeps the counts."""
    rows = call(cn, "mill_push_expire", [])
    row = rows[0] if rows else {}
    return {"deleted": int(row.get("deleted") or 0), "cut": str(row.get("cut") or "")}


class Held(list):
    """Sync items read without deleting their rows. ids are the wake rows behind
    them; ack(cn, ids) marks those rows taken once the frame that carries them is sent (#831)."""

    ids: tuple = ()


# #831: the same rows mill_push_take hands out, read without deleting them.
_PEEK_SQL = (
    "SELECT p.id, p.cause AS kind, p.payload, p.state AS outcome, p.created FROM wake p"
    " WHERE p.desk_id = MILL_NAME_GET('desk', %s)"
    " AND p.state <> 'taken'"
    " AND (p.cause = 'expired' OR p.created >= CURRENT_TIMESTAMP(6) - INTERVAL 7 DAY)"
    " ORDER BY p.id"
)


def peek(cn, desk: str) -> Held:
    """#831: the desk's sync items, rows left in place. A frame that is never sent
    (the socket was superseded or closed) leaves them for the next sync."""
    from .db import rows_done

    rows = rows_done(cn, _PEEK_SQL, (str(desk or "").strip(),))
    out = Held(_items(rows))
    out.ids = tuple(int(r["id"]) for r in rows if r.get("id") is not None)
    return out


def ack(cn, desk: str, ids) -> int:
    """#831: delete the rows a sent frame carried. Only those ids: a row put after the
    read stays queued. A second ack of the same ids deletes nothing. #867: only the
    desk's own rows, in cmd_push_sent."""
    from agent_coord.server.records.name import bare

    keep = [int(i) for i in ids or () if int(i) > 0]
    if not keep:
        return 0
    rows = call(cn, "cmd_push_sent", [Inline("MILL_DESK_ID(%s)", bare(desk, CONST_DESK)), json.dumps(keep)])
    return int((rows[0].get("sent") if rows else 0) or 0)


def take(cn, desk: str) -> list[dict]:
    return _items(call(cn, "mill_push_take", [desk]))


def _items(rows) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        payload = row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        item = dict(payload)
        item.pop(WAKE_REASON, None)  # #627: wall-side only; the sync item is unchanged
        item["kind"] = row.get("kind") or item.get("kind")
        item["outcome"] = row.get("outcome")
        item["time"] = row.get("created")
        out.append(item)
    return fold_hints(out)


def _hint_object(item: dict) -> tuple | None:
    """(type, id, outcome) for a hint poke about one object; None for anything else
    (a letter, a receipt, an expired line, a route exit or drop line)."""
    if item.get("kind") != "hint" or "exit" in item or "dropped" in item:
        return None
    typ = str(item.get("type") or "").strip()
    num = _frame_id(item)
    if not typ or not num:
        return None
    return (typ, num, str(item.get("outcome") or ""))


def fold_hints(items: list[dict]) -> list[dict]:
    """#671: one sync item per hinted object. A hint is a poke about an object, with
    the same poke key on every change, so a desk away for days would get one row per
    change (61 HOLD hints for one hold). The rows for one (type, id, outcome) become
    the latest of them, at its place, with n (how many) and first (the oldest time).
    A sent row and a missed row never merge: one was walked live, one was not."""
    counts: dict[tuple, int] = {}
    first: dict[tuple, Any] = {}
    last: dict[tuple, int] = {}
    for pos, item in enumerate(items):
        key = _hint_object(item)
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        first.setdefault(key, item.get("time"))
        last[key] = pos
    if all(n == 1 for n in counts.values()):
        return items
    out: list[dict] = []
    for pos, item in enumerate(items):
        key = _hint_object(item)
        if key is None or counts[key] == 1:
            out.append(item)
        elif last[key] == pos:
            out.append({**item, "n": counts[key], "first": first[key]})
    return out


# #832: the newest hint or letter this desk has not had live (receipts never ring).
_WAITING_SQL = (
    "SELECT p.id, p.cause AS kind, p.payload FROM wake p"
    " WHERE p.desk_id = MILL_NAME_GET('desk', %s)"
    " AND p.state IN ('missed', 'error') AND p.cause IN ('hint', 'mail') AND p.state <> 'taken'"
    " ORDER BY p.id DESC LIMIT 1"
)


def row_id(got) -> int:
    """The id put() returned (0 when unknown)."""
    try:
        return int(((got or [{}])[0] or {}).get("id") or 0)
    except (TypeError, ValueError, IndexError, AttributeError):
        return 0


def mark(cn, rid: int, outcome: str) -> int:
    """#832: set a missed row's outcome (sent or error). 0 when the row is gone.
    Emit and fanout put a row as missed before the live send; a send that reached a
    socket marks it sent. A row already taken by a sync is left alone (cmd_push_mark)."""
    if int(rid or 0) <= 0 or outcome not in ("sent", "error"):
        return 0
    rows = call(cn, "cmd_push_mark", [int(rid), outcome])
    return int((rows[0].get("marked") if rows else 0) or 0)


def waiting(cn, desk: str) -> dict | None:
    """#832: the newest hint or letter row not handed over live, or None."""
    from .db import rows_done

    rows = rows_done(cn, _WAITING_SQL, (str(desk or "").strip(),))
    if not rows:
        return None
    row = rows[0]
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {"id": int(row.get("id") or 0), "kind": row.get("kind"), "payload": payload}


def pending(cn, desk: str) -> int:
    """How many push rows wait for this desk's next sync (#618 wake body). 0 on error."""
    cur = cn.cursor()
    try:
        count_rows = (
            "SELECT COUNT(*) FROM wake p JOIN name d ON d.id = p.desk_id"
            " WHERE d.type = 'desk' AND d.name = %s AND p.state <> 'taken'"
        )
        cur.execute(count_rows, (str(desk or "").strip(),))
        row = cur.fetchone()
        return int((row or [0])[0] or 0)
    except Exception:
        return 0
    finally:
        cur.close()


def pending_addressed(cn, desk: str) -> bool:
    """#627: does any item waiting for this desk name it directly (a hint, a
    receipt, or a letter not marked as a room-member copy)? False on error."""
    cur = cn.cursor()
    try:
        any_addressed = (
            "SELECT 1 FROM wake p JOIN name d ON d.id = p.desk_id"
            " WHERE d.type = 'desk' AND d.name = %s AND p.cause <> 'expired' AND p.state NOT IN ('sent', 'taken')"
            " AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.wake_reason')), 'addressed') = 'addressed'"
            " LIMIT 1"
        )
        cur.execute(any_addressed, (str(desk or "").strip(),))
        return cur.fetchone() is not None
    except Exception:
        return False
    finally:
        cur.close()
