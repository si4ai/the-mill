# -*- coding: utf-8 -*-
"""Async mill backchannel: WebSocket rooms + webhook POST. Polling is mill wake."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any

from agent_coord.const import CONST_ADMIN, CONST_ROSTER
from agent_coord.server import perf
from agent_coord.server.redact import redact_format, redact_secrets

_log = logging.getLogger("mill.push")


# All mill-home logs rotate through log_rotate (#797). Perf lines keep ms stamps (F171).
_PERF_LOG = "mill-perf.log"


def dest_log(filename: str, msg: str) -> None:
    line = redact_secrets(msg).rstrip()
    try:
        _log.info(line)
    except Exception:
        pass
    try:
        from datetime import datetime, timezone

        from agent_coord.config import mill_home, settings
        from agent_coord.server import log_rotate as lr

        s = settings()
        lr.set_limits(
            max_bytes=int(s.get("log_max_bytes") or lr.MAX_BYTES),
            retain_days=int(s.get("log_retain_days") or lr.RETAIN_DAYS),
        )
        p = mill_home() / filename
        now = datetime.now(timezone.utc)
        if filename == _PERF_LOG:
            # Milliseconds, so the lines of one command sort and join (F171).
            text = now.isoformat(timespec="milliseconds")[:23] + "Z " + line + "\n"
        else:
            text = now.strftime("%Y-%m-%dT%H:%M:%SZ ") + line + "\n"
        lr.append_line(p, text)
    except Exception:
        pass


def _bc_log(msg: str) -> None:
    dest_log("mill-backchannel.log", msg)


def api_log(msg: str) -> None:
    dest_log("mill-api.log", msg)


def perf_write(op: str, ms: float, kv: dict[str, Any], rid: str | None = None) -> None:
    """One mill-perf.log line: op, ms, the command's rid when there is one, then kv."""
    try:
        parts = [f"op={op}", f"ms={ms:.2f}"]
        if rid:
            parts.append(f"rid={rid}")
        for k, v in kv.items():
            if v is None:
                continue
            parts.append(f"{k}={v}")
        dest_log(_PERF_LOG, " ".join(parts))
    except Exception:
        pass


def perf_log(op: str, ms: float, **kv: Any) -> None:
    """A perf line, unless perf is off (F171). Inside a /ws command it carries its rid."""
    if not perf.ON:
        return
    try:
        perf_write(op, ms, kv, perf.note(op, ms, kv))
    except Exception:
        pass


# Close code when a newer mill connect takes the same desk /ws seat.
WS_REPLACED = 4000

# Frame pushed to the older socket before close (not a HINT activity).
WS_REPLACED_REASON = "superseded: new connect same tokenHash"

# Close code for mill connect -r/--refuse when another live /ws holds the seat (#332).
WS_IN_USE = 4409


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[str, set[Any]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def add(self, desk: str, ws: Any, *, refuse: bool = False) -> dict[str, str] | None:
        """Sit desk on /ws. The room key is the desk name.

        refuse (mill connect -r): when another live socket holds the seat, do not
        sit and do not kick; return {desk, since} for the refusal. The check and
        the sit run with no await between them, so two connects cannot both pass.
        """
        from agent_coord.helpers.ident import desk as room_stem
        from agent_coord.helpers.ident import desk_name

        try:
            room_key = room_stem(desk)
            stored = desk_name(desk)
            if not room_key:
                return None
            room = self.rooms.setdefault(room_key, set())
            if refuse:
                # A socket already closed but not yet discarded does not hold the seat.
                for prev in [p for p in room if p is not ws and _ws_gone(p)]:
                    room.discard(prev)
                live = [p for p in room if p is not ws]
                if live:
                    since = min(float(getattr(p, "_mill_sat_at", 0) or 0) for p in live)
                    _bc_log(f"ws refuse desk={stored} reason=in-use")
                    return {"desk": stored, "since": _utc_iso(since)}
            old = [prev for prev in list(room) if prev is not ws]
            first = not room
            room.add(ws)
            try:
                ws._mill_sat_at = time.time()
            except Exception:
                pass
            for prev in old:
                await _kick_replaced(room_key, prev)
                room.discard(prev)
            if first:
                _mark_join_socket(stored, up=True)
            _bc_log(f"ws sit desk={stored} n={len(self.rooms.get(room_key) or ())}")
        except Exception as e:
            _bc_log(f"ws sit fail desk={desk} err={e}")
        return None

    def discard(self, desk: str, ws: Any) -> None:
        from agent_coord.helpers.ident import desk as room_stem
        from agent_coord.helpers.ident import desk_name

        try:
            room_key = room_stem(desk)
            stored = desk_name(desk)
            room = self.rooms.get(room_key)
            if not room:
                return
            room.discard(ws)
            last = not room
            if last:
                self.rooms.pop(room_key, None)
                _mark_join_socket(stored, up=False)
                # #832: the last socket left; rows it never got live ring an armed desk.
                _off_loop(_ring_after, stored, "leave")
            _bc_log(f"ws leave desk={stored} n={len(self.rooms.get(room_key) or ())}")
        except Exception as e:
            _bc_log(f"ws leave fail desk={desk} err={e}")

    async def _broadcast(self, desk: str, payload: dict[str, Any], row: tuple | None = None) -> None:
        try:
            room = list(self.rooms.get(desk) or ())
            dead = []
            from agent_coord.server.mill_json import stamp_mill

            stamped = stamp_mill(payload if isinstance(payload, dict) else {"payload": payload})
            text = json.dumps(stamped, default=str)
            hint = str((stamped or {}).get("hint") or "")
            n_ok = 0
            for ws in room:
                try:
                    await ws.send_text(text)
                    n_ok += 1
                except Exception as e:
                    _bc_log(f"ws send fail desk={desk} hint={hint} err={e}")
                    dead.append(ws)
            for ws in dead:
                try:
                    self.discard(desk, ws)
                except Exception:
                    pass
            _bc_log(f"ws push desk={desk} hint={hint} ok={n_ok} dead={len(dead)} frame_b={len(text.encode('utf-8'))}")
            if row and row[1]:
                # #832: a frame that reached a socket marks its row sent; one that found
                # no socket (the desk left after the sitting read) leaves it missed and rings.
                _off_loop(_settle_row, row[0], int(row[1]), n_ok > 0)
        except Exception as e:
            _bc_log(f"ws broadcast fail desk={desk} err={e}")

    def notify(self, desk: str, payload: dict[str, Any], row: tuple | None = None) -> None:
        """Thread-safe: mill RPC is sync inside uvicorn.

        row (#832): (desk, push_queue id) of the row this frame stands for; the
        broadcast marks it sent when a socket took the frame.
        """
        try:
            loop = self.loop
            if loop is None or not loop.is_running():
                _bc_log(f"ws skip no-loop desk={desk} hint={(payload or {}).get('hint')}")
                return
            asyncio.run_coroutine_threadsafe(self._broadcast(desk, payload, row), loop)
        except Exception as e:
            _bc_log(f"ws notify fail desk={desk} err={e}")



def _off_loop(fn, *args) -> None:
    """Run fn(*args) off the event loop: a worker of the running loop, else a thread."""
    try:
        asyncio.get_running_loop().run_in_executor(None, fn, *args)
    except RuntimeError:
        threading.Thread(target=fn, args=args, daemon=True).start()
    except Exception as e:
        _bc_log(f"ws off-loop fail err={type(e).__name__}")


def _settle_row(desk: str, rid: int, delivered: bool) -> None:
    """#832: mark a live-sent row sent, or ring when its frame reached no socket."""
    try:
        from agent_coord.server.book import Book
        from agent_coord.server.records import push as rec_push

        with Book() as c:
            if delivered:
                rec_push.mark(c._cn, rid, "sent")
            else:
                ring_waiting(c._cn, desk, "unsent")
    except Exception as e:
        _bc_log(f"push settle err desk={desk} err={type(e).__name__}")


def _ring_after(desk: str, why: str) -> None:
    try:
        from agent_coord.server.book import Book

        with Book() as c:
            ring_waiting(c._cn, desk, why)
    except Exception as e:
        _bc_log(f"push ring err desk={desk} why={why} err={type(e).__name__}")


def ring_waiting(cn, desk: str, why: str) -> str:
    """#832: wake an armed desk that is not sitting and has rows it never got live.

    Runs when its last socket leaves and when a live frame found no socket. The POST
    names the newest waiting hint or letter; post_desk's window, wake_on and checks
    apply as for any other wake. sitting | none | post_desk's result.
    """
    from agent_coord.server.mill_json import stamp_mill
    from agent_coord.server.poke_key import FIELD, hint_key, letter_key
    from agent_coord.server.records import push as rec_push
    from agent_coord.server.wake import ADDRESSED, ROOM, post_desk

    if any(k in HUB.rooms for k in _desk_room_keys(desk)):
        return "sitting"
    row = rec_push.waiting(cn, desk)
    if not row:
        # #949 / #826: push may be empty after a short connect marked rows sent, while
        # the mailbox letter is still unread. Ring on that unread so the desk wakes.
        unread = unread_mail_frames(cn, desk, limit=1)
        if not unread:
            return "none"
        frame = dict(unread[0])
        kind = "mail"
        reason = ADDRESSED
    else:
        kind = str(row.get("kind") or "hint")
        frame = dict(row.get("payload") or {})
        frame.setdefault("kind", kind)
        reason = ROOM if frame.pop(rec_push.WAKE_REASON, None) == "room" else ADDRESSED
    num = int(frame.get("id") or 0)
    if kind == "mail":
        frame[FIELD] = letter_key(num, desk)
    else:
        frame[FIELD] = hint_key(str(frame.get("type") or ""), num, desk)
    return post_desk(cn, desk, stamp_mill(frame), hint_id=num, reason=reason, ring=why)


def _ws_gone(ws: Any) -> bool:
    """True when the socket state already says disconnected (no I/O)."""
    for attr in ("client_state", "application_state"):
        state = getattr(ws, attr, None)
        if getattr(state, "name", "") == "DISCONNECTED":
            return True
    return False


def _utc_iso(ts: float) -> str:
    if not ts:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


async def _kick_replaced(desk: str, ws: Any) -> None:
    """Tell the older /ws why it is going away, then close it."""
    from agent_coord.server.mill_json import stamp_mill

    payload = stamp_mill({
        "type": "session",
        "id": 0,
        "hint": "DISCONNECTED",
        "detail": WS_REPLACED_REASON,
        "reason": WS_REPLACED_REASON,
    })
    try:
        send = getattr(ws, "send_text", None)
        if send is not None:
            await send(json.dumps(payload, default=str))
    except Exception as e:
        _bc_log(f"ws kick push fail desk={desk} err={e}")
    try:
        close = getattr(ws, "close", None)
        if close is not None:
            await close(code=WS_REPLACED)
    except Exception as e:
        _bc_log(f"ws kick close fail desk={desk} err={e}")
    _bc_log(f"ws kick desk={desk} reason=replaced")


def _mark_join_socket(desk: str, *, up: bool) -> None:
    try:
        from agent_coord.server.records import join as rec_join
        from agent_coord.server.book import Book

        with Book() as c:
            rec_join.mark_socket(c._cn, desk, up=up)
    except Exception as e:
        _bc_log(f"ws join time desk={desk} up={int(up)} err={e}")
    # A1: wake clock on first /ws; clear on last socket down.
    try:
        from agent_coord.server import wake_first

        if up:
            wake_first.mark_wake(desk)
        else:
            wake_first.clear_wake(desk)
    except Exception:
        pass


HUB = Hub()


def desk_sitting(desk: str) -> bool:
    """True when Hub has at least one live /ws socket for this desk seat."""
    keys = _desk_room_keys(desk)
    if not keys:
        return False
    rooms = HUB.rooms or {}
    return any(bool(rooms.get(k)) for k in keys)

def socket_seated(desk: str, ws: Any) -> bool:
    """True when this exact websocket is still in the Hub room for desk."""
    if ws is None:
        return False
    keys = _desk_room_keys(desk)
    if not keys:
        return False
    rooms = HUB.rooms or {}
    for k in keys:
        room = rooms.get(k)
        if room and ws in room:
            return True
    return False


def _cheap_detail(cn, type: str, id: int, watchers: list[dict], *, when: str = "") -> str:
    """NULL watcher.hint default: what/when/state, light tree crumbs, watcher count. No body dump.

    state comes from mill_activity_get (same rule as mill_activity_select): deleted
    (any type), sent (live letter), or None. One primary-key read, not the newest 40 rows.
    """
    import json as _json

    what = str(type or "")
    stamp = str(when or "")
    when = ""
    state = None
    crumbs: list[dict] = []
    try:
        from agent_coord.server.records import activity as rec_activity

        r = rec_activity.get(cn, what, int(id))
        if r:
            when = str(r.get("updated") or r.get("created") or "")
            state = r.get("state") or None
    except Exception:
        pass
    if stamp:
        when = stamp
    try:
        cur = cn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT name_id, lft, rgt FROM tree WHERE type=%s AND id=%s LIMIT 3",
                (what, int(id)),
            )
            for r in cur.fetchall() or []:
                crumbs.append(
                    {
                        "tree": int(r.get("name_id") or 0),
                        "lft": int(r.get("lft") or 0),
                        "rgt": int(r.get("rgt") or 0),
                    }
                )
        finally:
            cur.close()
    except Exception:
        pass
    return _json.dumps(
        {
            "what": what,
            "id": int(id),
            "when": when,
            "state": state,
            "watchers": len(watchers or []),
            "tree": crumbs,
        },
        default=str,
        separators=(",", ":"),
    )[:4096]




def mill_admin_alert(cn, text: str, *, command: str = "") -> None:
    """Backchannel/API host faults -> MAIL dest Admin (W3). Not CoordError 400s."""
    v = (command or "").strip().lower()
    if v in ("heartbeat", "session"):
        return
    try:
        from agent_coord.server.records import mail as rec_mail
        from agent_coord.server.records import member as rec_member

        rows = rec_member.select(cn, CONST_ADMIN, "", CONST_ROSTER)
        if not rows:
            return
        src = str(rows[0].get("desk") or "").strip()
        if not src:
            return
        from agent_coord.server.redact import redact_text

        body = redact_text(text or "mill-wall")[0][:4000]
        from agent_coord.server.admin.guard import office_name

        ins = rec_mail.insert(cn, office_name(cn), src, CONST_ADMIN, body, 0, dst_kind=CONST_ROSTER)
        mid = int((ins[0] or {}).get("id") or 0) if ins else 0
        if mid:
            from agent_coord.server.mail_push import push_mail

            push_mail(cn, mid)
    except Exception as e:
        _log.warning("%s", redact_format("mill_admin_alert: %s", e))


def fanout(
    cn,
    type: str,
    id: int,
    hint: str,
    *,
    rows: list[dict] | None = None,
    skip_desk: str = "",
    when: str = "",
) -> list[dict]:
    """After a records write: poke watchers (ws / webhook / poll no-op).

    skip_desk leaves out the desk whose own act caused the write. Its /ws connect
    runs before its socket sits in the Hub, so without this the desk's own DOING
    would be queued as missed and handed straight back in its connect sync.

    rows, when passed, is the watcher list to poke. probe-delete reads it before
    the delete procedure drops those rows, then stamps, then pokes (#185).

    when, when passed, is the hint time; a write that leaves the activity row
    alone (a label) passes its own time so the hint is not stale (#280).

    Inside a request transaction (#818) the pokes wait for its commit and are
    dropped if it rolls back; the return is then [].
    """
    import time

    from agent_coord.server.records.db import after_commit, in_request_tx

    if in_request_tx(cn):
        after_commit(cn, lambda: fanout(cn, type, id, hint, rows=rows, skip_desk=skip_desk, when=when))
        return []
    t0 = time.perf_counter()
    try:
        from agent_coord.server.wake import post_desk
        from agent_coord.server.records import watcher as rec_w

        if rows is None:
            rows = rec_w.select(cn, type, int(id)) or []
        else:
            rows = list(rows)
        cheap = _cheap_detail(cn, type, int(id), rows, when=when)
        n_sit = n_hook = n_miss = 0
        skip_keys = _desk_room_keys(skip_desk) if skip_desk else []
        for row in rows:
            try:
                desk = str(row.get("desk") or "")
                if skip_keys and _desk_room_keys(desk) == skip_keys:
                    continue
                mode = str(row.get("delivery_mode") or "polling")
                url = str(row.get("endpoint_url") or "")
                wh = row.get("hint")
                detail = str(wh).strip() if wh not in (None, "") else cheap
                # hint stays type.upper() for route_key; detail = per-listener recipe
                from agent_coord.server.mill_json import stamp_mill

                payload = stamp_mill({"type": type, "id": int(id), "hint": hint, "detail": detail})
                from agent_coord.server.poke_key import FIELD, hint_key

                payload[FIELD] = hint_key(type, int(id), desk)
                keys = _desk_room_keys(desk)
                report = {
                    "kind": "hint",
                    "type": type,
                    "id": int(id),
                    "hint": hint,
                    "detail": detail,
                }
                from agent_coord.server.records import push as rec_push

                # #832: the row goes in first, as missed, so a sync at any later point
                # (the woken desk's connect included) hands it over. A live send that
                # reaches a socket marks it sent.
                rid = 0
                try:
                    rid = rec_push.row_id(rec_push.put(cn, desk, "hint", report, "missed"))
                except Exception as e:
                    _bc_log(f"push log err desk={desk} kind=hint err={e}")
                sitting = any(k in HUB.rooms for k in keys)
                if sitting:
                    n_sit += 1
                    try:
                        _notify_rooms(keys or [desk], payload, row=(desk, rid))
                    except Exception as e:
                        _mark_error(cn, rid)
                        _bc_log(f"fanout notify err desk={desk} err={e}")
                elif mode == "webhook" and url:
                    # #618: a doorbell, one per desk per window. The hint is already queued as
                    # missed, so the woken desk's connect sync hands it over and its chain walks it.
                    try:
                        got = post_desk(cn, desk, payload, hint_id=int(id))
                    except Exception as e:
                        got = "error"
                        _bc_log(f"webhook desk={desk} id={id} err={type(e).__name__}")
                    if got in ("sent", "error"):
                        n_hook += 1
                    else:
                        n_miss += 1
                    # post_desk logged this desk's wake line (#625).
                else:
                    n_miss += 1
                    _bc_log(f"fanout miss desk={desk} type={type} id={id} hint={hint} mode={mode}")
            except Exception as e:
                _bc_log(f"fanout row err type={type} id={id} err={e}")
        ms = (time.perf_counter() - t0) * 1000.0
        _bc_log(
            f"fanout type={type} id={id} hint={hint} watchers={len(rows)} sit={n_sit} hook={n_hook} miss={n_miss} ms={ms:.1f}"
        )
        frame_b = len(json.dumps({"type": type, "id": int(id), "hint": hint, "detail": cheap}, default=str).encode("utf-8"))
        perf_log(
            "fanout",
            ms,
            type=type,
            id=id,
            hint=hint,
            watchers=len(rows),
            sit=n_sit,
            miss=n_miss,
            frame_b=frame_b,
        )
        return rows
    except Exception as e:
        try:
            perf_log("fanout", (time.perf_counter() - t0) * 1000.0, type=type, id=id, ok=0, err=str(e)[:160])
        except Exception:
            pass
        _bc_log(f"fanout fail type={type} id={id} hint={hint} err={e}")
        try:
            mill_admin_alert(cn, f"fanout {type} {id}: {e}", command="fanout")
        except Exception:
            pass
        return []


def _notify_rooms(rooms: list[str], frame: dict, row: tuple | None = None) -> None:
    """One /ws send. If the frame has an idempotency key, a raised send retries once.

    row (#832): (desk, push_queue id); the broadcast marks that row sent.
    """
    from agent_coord.server.poke_key import FIELD

    idem = str((frame or {}).get(FIELD) or "")
    extra = {"row": row} if row and row[1] else {}  # no stored row: nothing to settle
    for room in rooms:
        try:
            HUB.notify(room, frame, **extra)
        except Exception:
            if not idem:
                raise
            HUB.notify(room, frame, **extra)


def _mark_error(cn, rid: int) -> None:
    """#832: a live send that raised leaves its row as error (still waiting)."""
    try:
        from agent_coord.server.records import push as rec_push

        rec_push.mark(cn, rid, "error")
    except Exception as e:
        _bc_log(f"push mark err id={rid} err={type(e).__name__}")


def emit(cn, desk: str, kind: str, payload: dict, *, reason: str = "addressed", room: str | None = None) -> str:
    """Hand one async item to a sitting socket, and keep it for the sync report.

    outcome is sent, missed, or error (deferred inside a #818 request transaction). The book row is what a later mill sync returns.
    The live frame carries an idempotency key. The stored row does not: connect
    drain picking up that key is a later change.
    """
    from agent_coord.server.mill_json import stamp_mill
    from agent_coord.server.poke_key import FIELD, letter_key, receipt_key
    from agent_coord.server.records import push as rec_push
    from agent_coord.server.records.db import after_commit, in_request_tx

    if in_request_tx(cn):
        # #818: the letter goes out after its command commits, never for a rolled-back one.
        after_commit(cn, lambda: emit(cn, desk, kind, payload, reason=reason, room=room))
        return "deferred"
    frame = dict(payload)
    frame.setdefault("kind", kind)
    who = str(desk or "").strip()
    mid = int(frame.get("id") or 0)
    live = dict(frame)
    if kind == "receipt":
        live[FIELD] = receipt_key(mid, who)
    else:
        live[FIELD] = letter_key(mid, who)
    if reason == "room":
        # #627: kept on the stored row only, so a later wake knows the burst
        # held no addressed item; take() drops it before the sync.
        frame[rec_push.WAKE_REASON] = "room"
    # #832: the row goes in first, as missed. A sync at any later point (the woken
    # desk's connect included) hands it over; a live send that reaches a socket
    # marks it sent. Before, the row was written after the wake POST, so a desk
    # woken fast enough synced before the row existed and was not woken again.
    rid = 0
    try:
        rid = rec_push.row_id(rec_push.put(cn, desk, kind, frame, "missed"))
    except Exception as e:
        _bc_log(f"push log err desk={desk} kind={kind} err={e}")
    outcome = "missed"
    keys = _desk_room_keys(desk)
    sitting = any(k in HUB.rooms for k in keys)
    if sitting:
        try:
            _notify_rooms(keys or [desk], stamp_mill(live), row=(who, rid))
            outcome = "sent"
        except Exception as e:
            outcome = "error"
            _mark_error(cn, rid)
            _bc_log(f"push notify err desk={desk} kind={kind} err={e}")
    elif kind == "mail":
        # #618: a letter rings an armed desk's webhook too. The letter text never
        # rides the POST; the row is already queued, so the connect sync hands it over.
        try:
            from agent_coord.server.wake import post_desk

            post_desk(cn, desk, live, hint_id=mid, reason=reason, room=room)
        except Exception as e:
            _bc_log(f"webhook desk={desk} kind=mail err={type(e).__name__}")
    return outcome


# The 30-day queue sweep runs at wall start and then twice a day, not on every take.
PUSH_EXPIRE_EVERY_S = 12 * 60 * 60


def expire_sweep() -> dict[str, Any]:
    """One mill_push_expire pass on its own book connection. Logs op=push.expire."""
    import time

    from agent_coord.server.records import push as rec_push
    from agent_coord.server.records.db import connect

    t0 = time.perf_counter()
    cn = None
    try:
        cn = connect()
        out = rec_push.expire(cn)
        perf_log("push.expire", (time.perf_counter() - t0) * 1000.0, deleted=out["deleted"], ok=1)
        return {"ok": True, **out}
    except Exception as e:
        perf_log("push.expire", (time.perf_counter() - t0) * 1000.0, ok=0, err=str(e)[:160])
        return {"ok": False, "error": str(e)[:240]}
    finally:
        if cn is not None:
            try:
                cn.close()
            except Exception:
                pass


def take_sync(cn, desk: str, *, hold: bool = False) -> list[dict]:
    """Rows pushed since this desk's last mill sync. Deletes them.

    hold=True (#831) reads them without deleting: the list carries .ids, and the
    caller deletes them with ack_sync once the frame that carries them is sent.
    """
    from agent_coord.server.records import push as rec_push

    try:
        return rec_push.peek(cn, desk) if hold else rec_push.take(cn, desk)
    except Exception as e:
        _bc_log(f"push take err desk={desk} err={e}")
        return []


def sync_ids(items) -> list[int]:
    """#831: the queue rows behind a held sync list ([] for a plain list)."""
    return [int(i) for i in getattr(items, "ids", ()) or ()]


def ack_sync(cn, desk: str, ids) -> int:
    """#831: delete the rows a sent frame carried. Logs and returns 0 on error; the
    rows then stay queued and the next sync hands them over again."""
    from agent_coord.server.records import push as rec_push

    try:
        return rec_push.ack(cn, desk, ids)
    except Exception as e:
        _bc_log(f"push ack err desk={desk} err={e}")
        return 0



def unread_mail_frames(cn, desk: str, *, limit: int = 20) -> list[dict]:
    """#949: newest unread mailbox letters as sync/wake frames (opened IS NULL).

    Soft-fails to [] so connect and wake keep working if the inbox read fails.
    A short connect that drained the push queue without opening the letter still
    sees these on the next connect-wait, and wake-done / leave can ring again.
    """
    try:
        from agent_coord.server.records import mail as rec_mail

        rows = rec_mail.inbox(cn, desk, all_mail=False, limit=max(1, int(limit or 20)))
    except Exception as e:
        _bc_log(f"unread mail err desk={desk} err={type(e).__name__}")
        return []
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            mid = int(row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if mid <= 0:
            continue
        out.append(
            {
                "kind": "mail",
                "id": mid,
                "outcome": "missed",
                "body": row.get("body"),
                "sender": row.get("desk") or row.get("sender"),
            }
        )
    return out


def _merge_unread_into_sync(cn, desk: str, sync):
    """#949: after take/peek, append unread mailbox mail not already in the sync.

    Frames with no push_queue id stay for the next sit until the desk opens the
    letter (hold/ack does not drop them). Mutates the sync list in place so a
    held peek keeps its row ids.
    """
    try:
        unread = unread_mail_frames(cn, desk)
    except Exception:
        return sync if sync is not None else []
    if not unread:
        return sync if sync is not None else []
    base = sync if isinstance(sync, list) else list(sync or [])
    seen: set[int] = set()
    for item in base:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "mail":
            continue
        try:
            seen.add(int(item.get("id") or 0))
        except (TypeError, ValueError):
            pass
    for frame in unread:
        try:
            mid = int(frame.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if mid and mid not in seen:
            base.append(frame)
            seen.add(mid)
    return base


def connect_sync_frame(cn, desk: str, *, hold: bool = False) -> dict:
    """Connect sync plus this desk's holds. Holds are not queue items.

    An empty push queue stays an empty list. If the hold read fails, holds is [].
    hold=True (#831): the queue rows stay until ack_sync after the frame is sent.
    #949: unread mailbox mail (opened IS NULL) not already in the queue is merged
    into sync so the next connect-wait exits at once after a short connect drained
    the push rows without opening the letter.
    """
    sync = _merge_unread_into_sync(cn, desk, take_sync(cn, desk, hold=hold))
    holds: list = []
    try:
        from agent_coord.server.records import hold as rec_hold

        got = rec_hold.own(cn, desk)
        holds = got if isinstance(got, list) else []
    except Exception as e:
        _bc_log(f"hold own err desk={desk} err={e}")
        holds = []
    # F144: a sync does not end the desk's wake lease. A routine run connects once
    # per shell call; only mill wake-done or the lease timeout lets the next item POST.
    # The sync did hand over what was held back, so those no longer count.
    try:
        from agent_coord.server.wake import lease_synced

        lease_synced(desk)
    except Exception:
        pass
    return {"kind": "sync", "sync": sync, "holds": holds, "wake": wake_line(cn, desk), "hello": hello_line(cn)}


def sp_stamp() -> str:
    """The SP stamp this pack ships: sp-<first 12 hex of its SQL digest> (#614, #867).
    The book's mill_sp_version() reads the same digest from MILL_SQL_STAMP."""
    try:
        from agent_coord.install.migrate import sql_digest

        return "sp-" + sql_digest()[:12]
    except Exception:
        return ""


def hello_line(cn) -> str:
    """#867: the pack's SP stamp against the office's (mill_hello, warn mode).
    'ok' on a match, else the SP's warn line. A failed check says so; connect goes on."""
    from agent_coord.server.records.db import call

    try:
        rows = call(cn, "mill_hello", [sp_stamp() or None, "warn"])
    except Exception as e:
        _bc_log(f"mill_hello err={type(e).__name__}")
        return "check failed"
    row = rows[-1] if rows else {}
    if str(row.get("status") or "") == "ok":
        return "ok"
    return str(row.get("message") or row.get("status") or "").strip() or "check failed"


def wake_line(cn, desk: str) -> str:
    """Glanceable wake state (#618): 'webhook armed (host H)' or 'off'. Never the path or key."""
    try:
        from agent_coord.server.records import join as rec_join

        st = rec_join.wake_state(cn, desk)
    except Exception as e:
        _bc_log(f"wake state err desk={desk} err={type(e).__name__}")
        return "unknown"
    if st.get("armed"):
        on = ", wake on addressed" if st.get("wake_on") == "addressed" else ""
        line = f"webhook armed (host {st.get('host') or '?'}{on})"
        try:
            from agent_coord.server.wake import fail_note

            note = fail_note(desk)
        except Exception:
            note = ""
        return f"{line}; {note}" if note else line
    return "off"


def _desk_room_keys(desk: str) -> list[str]:
    """Hub room is the desk name. mill connect sits /ws/<name>."""
    d = str(desk or "").strip()
    if not d:
        return []
    from agent_coord.helpers.ident import desk as slug_desk

    room = slug_desk(d)
    return [room] if room else []
