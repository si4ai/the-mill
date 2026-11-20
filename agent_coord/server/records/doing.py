"""Doing (card 1207, the owner 2026-11-13): a doing row is one tw.exe (TaskWrapper) run, written only by
mill_doing_task through task_event. The row is the start; later states and the end are transition rows. A desk's
current doings are its rows with no terminal transition (finished, failed, stale, cleared); a desk may run many.
There is no --doing, no focus, clear or finish row, and no seat pointer.

Reads: `mill connected` (now), its history, and the tw cap and sweep helpers.
"""

from __future__ import annotations

from typing import Any

from agent_coord.const import CONST_DESK

from .db import call, rows_done


def now(cn, desk: str = "", roster: str = "", all_desks: bool = False) -> list[dict[str, Any]]:
    from agent_coord.server.records.name import bare

    rows = call(
        cn,
        "mill_doing_now",
        [bare(desk, CONST_DESK) if desk else "", roster or "", 1 if all_desks else 0],
    ) or []
    return rows


def history(
    cn,
    desk: str = "",
    since: str | None = None,
    page: int = 1,
    size: int = 50,
    on_type: str = "",
    on_id: int | None = None,
) -> list[dict[str, Any]]:
    """Past doings (tw runs), newest first; on_type/on_id keep one item (a card's runs and its moves)."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_doing_history",
        [bare(desk, CONST_DESK) if desk else "", since, int(page), int(size),
         on_type or "", int(on_id) if on_type and on_id is not None else None],
    ) or []


# Card 970 step 4: live (non-terminal) doing rows a desk may hold.
TASK_CAP = 8
_TASK_TERMINAL = ("finished", "failed", "stale", "cleared")


def live_tasks(cn, desk_id: int) -> int:
    """Count the desk's doing rows with no terminal transition."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM doing g WHERE g.desk_id=%s AND NOT EXISTS ("
            " SELECT 1 FROM transition t WHERE t.activity_type='doing' AND t.activity_id=g.id"
            " AND t.to_state IN (%s, %s, %s, %s)) FOR SHARE",
            (desk_id, *_TASK_TERMINAL),
        )
        return int(cur.fetchone()[0])
    finally:
        cur.close()


# Card 1090 step 4: a live task row is stale once its desk has been offline
# (no connected seat) this long. A connected desk's rows are never stale, at
# any age. Swept only when a start would hit TASK_CAP (one tw_stale edge each).
STALE_AFTER_S = 24 * 3600
CAP_HINT_N = 3

# Offline since: seat.time_disconnect (mill_join_socket p_up=0, or a reset);
# a never-connected seat counts from seat.created. NULL while the seat is
# alive (the sp_floor_scope / seat_connected rule). Seat stamps use MILL_NOW().
_SEAT_OFFLINE_S = (
    "IF(j.time_connect IS NOT NULL AND (j.time_disconnect IS NULL"
    " OR j.time_connect >= j.time_disconnect), NULL,"
    " TIMESTAMPDIFF(SECOND, COALESCE(j.time_disconnect, j.created), MILL_NOW()))"
)
_TASK_LIVE = (
    "NOT EXISTS ("
    "SELECT 1 FROM transition e WHERE e.activity_type='doing' AND e.activity_id=g.id"
    " AND e.to_state IN (" + ", ".join(f"'{x}'" for x in _TASK_TERMINAL) + "))"
)


def _live_task_ages(cn, desk_id: int) -> list[dict[str, Any]]:
    """The desk's live doing rows, oldest latest hop first, with that hop's
    effective state (card 1098 compress: even n means back at from_state) and
    offline_s: seconds the desk has been offline, None while it is connected."""
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT g.id, t.join_key,"
            " IF(MOD(t.n, 2) = 1, t.to_state, t.from_state) AS state,"
            " TIMESTAMPDIFF(SECOND, t.at, UTC_TIMESTAMP(6)) AS age_s,"
            f" {_SEAT_OFFLINE_S} AS offline_s"
            " FROM doing g LEFT JOIN seat j ON j.desk_id = g.desk_id"
            " JOIN transition t ON t.id = ("
            "  SELECT MAX(l.id) FROM transition l"
            "   WHERE l.activity_type='doing' AND l.activity_id=g.id)"
            " WHERE g.desk_id=%s AND NOT EXISTS ("
            "  SELECT 1 FROM transition e WHERE e.activity_type='doing' AND e.activity_id=g.id"
            "   AND e.to_state IN (%s, %s, %s, %s))"
            " ORDER BY t.at, g.id FOR SHARE",
            (desk_id, *_TASK_TERMINAL),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def sweep_stale_tasks(cn, desk_id: int) -> int:
    """Close the desk's live task rows once the desk is offline STALE_AFTER_S.

    Runs inside the caller's request tx, under the seat lock mill_doing_task
    took. Each swept row gets one tw_stale edge (meta cause=sweep, age_s,
    offline_s). A connected desk sweeps nothing.
    Returns how many rows it closed.
    """
    from agent_coord.server import transition as tr

    n = 0
    for r in _live_task_ages(cn, desk_id):
        off = r["offline_s"]
        if off is None or int(off) < STALE_AFTER_S or r["state"] not in ("active", "waiting"):
            continue
        key = str(r["join_key"])
        tr.put(cn, activity_type=tr.ActivityType.doing, activity_id=int(r["id"]),
               from_state=tr.State(r["state"]), to_state=tr.State.stale,
               reason=tr.Reason.tw_stale, desk_id=desk_id, join_key=key,
               meta={"watch_id": key.split(":", 2)[-1], "cause": "sweep",
                     "age_s": int(r["age_s"]), "offline_s": int(off)})
        n += 1
    return n


def _lock_seat(cn, desk_id: int) -> None:
    """Take the desk's seat row lock (the same lock mill_doing_task takes)."""
    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM seat WHERE desk_id=%s FOR UPDATE", (desk_id,))
        cur.fetchall()
    finally:
        cur.close()


def sweep_offline_desks(cn) -> dict[str, int]:
    """Card 1090 timer sweep (score tick): sweep_stale_tasks for every desk
    offline >= STALE_AFTER_S that still holds live task rows. One request tx
    per desk under its seat lock; the offline test is re-read under the lock."""
    from agent_coord.server.records.db import request_tx

    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT DISTINCT g.desk_id FROM doing g JOIN seat j ON j.desk_id = g.desk_id"
            f" WHERE {_TASK_LIVE} AND {_SEAT_OFFLINE_S} >= %s ORDER BY g.desk_id",
            (STALE_AFTER_S,),
        )
        desks = [int(r[0]) for r in cur.fetchall()]
    finally:
        cur.close()
    cn.commit()  # end the read snapshot before the per-desk txs
    swept = 0
    for desk_id in desks:
        def run(d=desk_id):
            _lock_seat(cn, d)
            return sweep_stale_tasks(cn, d)
        swept += int(request_tx(cn, run) or 0)
    return {"desks": len(desks), "swept": swept}


RECONCILE_MAX = 256


def reconcile_tasks(cn, desk: str, live_ids: list[str]) -> dict[str, Any]:
    """Card 1090: connect's start-up report of the watch ids it believes live.

    Inside the caller's request tx. Closes every other live doing row of
    this desk only, through the crash path (tw_failed, meta cause=reconcile).
    Listed ids that are live are kept; unknown ids are ignored, never created.
    An empty list closes all of the desk's live rows. A repeat closes nothing.
    """
    from agent_coord.server.records.name import bare

    desk = bare(desk, CONST_DESK)
    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))
        got = cur.fetchone()
    finally:
        cur.close()
    keep = set(live_ids)
    closed: list[str] = []
    kept: list[str] = []
    if got:
        desk_id = int(got[0])
        _lock_seat(cn, desk_id)
        for r in _live_task_ages(cn, desk_id):
            wid = str(r["join_key"]).split(":", 2)[-1]
            if wid in keep:
                kept.append(wid)
                continue
            if r["state"] not in ("active", "waiting"):
                continue
            meta = {"watch_id": wid, "desk": desk, "kind": "crash", "cause": "reconcile"}
            if task_event(cn, desk, meta) == "wrote":
                closed.append(wid)
    return {"closed": closed, "kept": kept, "unknown_n": len(keep - set(kept))}


def _age(s: int) -> str:
    d, rest = divmod(max(0, int(s)), 86400)
    h, rest = divmod(rest, 3600)
    m, sec = divmod(rest, 60)
    if d:
        return f"{d}d{h}h"
    if h:
        return f"{h}h"
    return f"{m}m" if m else f"{sec}s"


def cap_msg(oldest: list[tuple[str, int]]) -> str:
    """The cap reply text: the plain line, then the oldest live watch ids."""
    msg = f"tw.event: desk already has {TASK_CAP} live tasks"
    if not oldest:
        return msg
    named = ", ".join(f"{w} ({_age(a)})" for w, a in oldest[:CAP_HINT_N])
    return (f"{msg}; oldest: {named}; end one with kill PID, or it is swept"
            f" after the desk is offline {_age(STALE_AFTER_S)}")


def cap_hint(cn, desk: str) -> str:
    """Read-only: the cap msg for this desk, naming its oldest live watch ids."""
    from agent_coord.server.records.name import bare

    cur = cn.cursor()
    try:
        cur.execute("SELECT id FROM name WHERE type='desk' AND name=%s",
                    (bare(desk, CONST_DESK),))
        got = cur.fetchone()
    finally:
        cur.close()
    if not got:
        return cap_msg([])
    oldest = [(str(r["join_key"]).split(":", 2)[-1], int(r["age_s"]))
              for r in _live_task_ages(cn, int(got[0]))]
    return cap_msg(oldest)


# Card 1090 step 4 health fact: offline desks still holding live tw rows.
# Read-only, no params; glance runs it through its own _q.
OFFLINE_TASKS_SQL = (
    f"SELECT n.name, {_SEAT_OFFLINE_S} AS offline_s, COUNT(*) AS live_n"
    " FROM doing g JOIN seat j ON j.desk_id = g.desk_id"
    " JOIN name n ON n.id = g.desk_id AND n.type = 'desk'"
    f" WHERE {_TASK_LIVE}"
    " GROUP BY n.name, j.time_connect, j.time_disconnect, j.created"
    f" HAVING offline_s IS NOT NULL ORDER BY offline_s DESC, n.name"
    " /* glance:tw-offline */"
)


def offline_tasks(rows) -> list[dict[str, Any]]:
    """Shape OFFLINE_TASKS_SQL rows: a fact per desk, never a gate."""
    out = []
    for name, off, live in rows or []:
        try:
            off_s, live_n = max(0, int(off)), int(live)
        except (TypeError, ValueError):
            continue
        out.append({"desk": str(name or ""), "offline_s": off_s, "offline": _age(off_s),
                    "live_n": live_n, "sweepable": off_s >= STALE_AFTER_S})
    return out


DOINGS_CAP = 20


def _utc_iso(at: Any, off: int = 0) -> str | None:
    """A UTC DATETIME as ISO UTC with Z. doing.created (book clock) is converted per row in SQL first
    (CONVERT_TZ from the session zone), so a run from the other side of a DST change reads right."""
    if at is None:
        return None
    from datetime import datetime, timedelta

    if not isinstance(at, datetime):
        at = datetime.fromisoformat(str(at))
    return (at + timedelta(seconds=off)).isoformat(timespec="seconds") + "Z"


def live_doings(cn, desks: list[str]) -> dict[str, dict[str, Any]]:
    """Card 1207 (wall-ui shape, 2026-11-13): each desk's live doings (tw runs with no terminal transition),
    newest created first, at most DOINGS_CAP, plus n, the true count of those live runs (not the nested-run
    count from run_tree). A row: id, created (ISO UTC), text, state (its latest transition's to_state, or
    'started' when it has none yet), state_at (ISO UTC of that transition, else created), card (None: the
    tw-to-card link is not decided), watch_id (the run id, or None before the first transition), and
    parent_watch_id (the nesting parent, or None). A tw_call row (card 1223) is a descendant's mill call,
    not a state, so it never moves state_at."""
    out: dict[str, dict[str, Any]] = {str(d): {"n": 0, "doings": []} for d in desks}
    if not desks:
        return out
    live = ("NOT EXISTS (SELECT 1 FROM transition ended WHERE ended.activity_type='doing'"
            " AND ended.activity_id=g.id AND ended.to_state IN (%s, %s, %s, %s))")
    rows = rows_done(cn, """
        SELECT d.name AS desk, x.id, x.created_utc, x.text, x.state, x.state_at, x.n,
               x.join_key, x.parent_watch_id
          FROM name d
          JOIN LATERAL (
            SELECT g.id, g.created, g.text, t.to_state AS state, t.at AS state_at,
                   IFNULL(CONVERT_TZ(g.created, @@session.time_zone, '+00:00'),
                          g.created + INTERVAL TIMESTAMPDIFF(SECOND, NOW(6), UTC_TIMESTAMP(6)) SECOND) AS created_utc,
                   COUNT(*) OVER () AS n,
                   (SELECT s.join_key FROM transition s
                     WHERE s.activity_type='doing' AND s.activity_id=g.id
                     ORDER BY s.id LIMIT 1) AS join_key,
                   (SELECT JSON_UNQUOTE(JSON_EXTRACT(s.meta, '$.parent_watch_id'))
                      FROM transition s
                     WHERE s.activity_type='doing' AND s.activity_id=g.id AND s.reason='tw_start'
                       AND JSON_TYPE(JSON_EXTRACT(s.meta, '$.parent_watch_id'))='STRING'
                     ORDER BY s.id LIMIT 1) AS parent_watch_id
              FROM doing g
              LEFT JOIN transition t ON t.id=(
                SELECT latest.id FROM transition latest
                 WHERE latest.activity_type='doing' AND latest.activity_id=g.id
                   AND latest.reason <> 'tw_call'
                 ORDER BY latest.id DESC LIMIT 1)
             WHERE g.desk_id=d.id AND """ + live + """
             ORDER BY g.created DESC, g.id DESC
          ) x ON TRUE
         WHERE d.type='desk' AND d.name IN (""" + ",".join(["%s"] * len(desks)) + """)
         ORDER BY d.name, x.created DESC, x.id DESC""",
        (*_TASK_TERMINAL, *desks),
    )
    for r in rows:
        slot = out.setdefault(str(r["desk"]), {"n": 0, "doings": []})
        slot["n"] = int(r.get("n") or 0)
        if len(slot["doings"]) >= DOINGS_CAP:
            continue
        created = _utc_iso(r.get("created_utc"))
        watch = _watch_from_join(str(r["desk"]), r.get("join_key"))
        parent_raw = r.get("parent_watch_id")
        if isinstance(parent_raw, bytes):
            parent_raw = parent_raw.decode("utf-8", "replace")
        parent = parent_raw.strip() if isinstance(parent_raw, str) else ""
        slot["doings"].append({
            "id": int(r["id"]),
            "created": created,
            "text": str(r.get("text") or ""),
            "state": str(r.get("state") or "started"),
            "state_at": _utc_iso(r.get("state_at")) if r.get("state_at") is not None else created,
            "card": None,
            "watch_id": watch,
            "parent_watch_id": parent if parent and parent != watch else None,
        })
    return out


def task_event(cn, desk: str, meta: dict[str, Any], *, outcome: str = "") -> str:
    """Card 970: one serialized task lifecycle, inside the caller's request tx.

    Returns "cap" (a 9th live start after the stale sweep; nothing written), "noop" (a replayed or
    late hop; nothing written), "wrote" (a transition) or "metric".
    """
    import json

    from agent_coord.helpers.errors import CoordError
    from agent_coord.server import transition as tr
    from agent_coord.server.records import score
    from agent_coord.server.records.name import bare

    desk = bare(desk, CONST_DESK)
    kind = meta["kind"]
    key = f"task:{desk}:{meta['watch_id']}"
    # The seat row lock in mill_doing_task serializes this desk's births.
    row = call(cn, "mill_doing_task", [desk, key, meta.get("card"), 0])[0]
    if kind == "start" and row["id"] is None:
        if live_tasks(cn, row["desk_id"]) >= TASK_CAP and (
            sweep_stale_tasks(cn, row["desk_id"]) == 0
            or live_tasks(cn, row["desk_id"]) >= TASK_CAP
        ):
            return "cap"  # card 1090: swept only at the cap; still full refuses
        row = call(cn, "mill_doing_task", [desk, key, meta.get("card"), 1])[0]
    mapped = {
        "start": (tr.State.active, tr.Reason.tw_start),
        "stall": (tr.State.waiting, tr.Reason.tw_wait),
        "resume": (tr.State.active, tr.Reason.tw_resume),
        "exit": (tr.State.finished, tr.Reason.tw_finished) if meta.get("exit_code") == 0
                else (tr.State.failed, tr.Reason.tw_failed),
        "crash": (tr.State.failed, tr.Reason.tw_failed),
    }
    if kind in mapped:
        if row["id"] is None:
            raise CoordError("tw.event: start required before a transition")
        state = tr.State(row["state"])
        if state.value in _TASK_TERMINAL:
            return "noop"  # a replayed or late hop never reopens a terminal watch
        if kind == "start" and state != tr.State.idle:
            # open_call may have written the one tw_start before tw's own start arrived.
            # That repeat must keep the parent link instead of dropping it (card 1239).
            _attach_parent(cn, int(row["id"]), meta.get("parent_watch_id"))
            return "noop"  # repeated delivery is not a second birth or transition
        to_state, reason = mapped[kind]
        if state == to_state:
            return "noop"  # a replayed stall while waiting, or resume while active
        try:
            tr.check_edge(tr.ActivityType.doing, state, to_state, reason)
        except tr.UnknownTransition as e:
            raise CoordError("tw.event: kind does not follow the task state") from e
        tr.put(cn, activity_type=tr.ActivityType.doing, activity_id=row["id"],
               from_state=state, to_state=to_state, reason=reason,
               desk_id=row["desk_id"], join_key=key, meta=meta)
        cur = cn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT at, from_state, to_state, reason, meta FROM transition"
                " WHERE activity_type='doing' AND activity_id=%s AND join_key=%s ORDER BY id FOR UPDATE",
                (row["id"], key),
            )
            events = cur.fetchall()
        finally:
            cur.close()
        measures: dict[str, Any] = {}
        waits: dict[str, int] = {}
        previous, prev_ts = row["created"], None
        for event in events:
            if event["reason"] == "tw_call":
                continue  # card 1223: a descendant's mill call is not a state change; dwell skips it
            emeta = json.loads(event["meta"]) if event["meta"] else {}
            ts = emeta.get("ts_ms") if isinstance(emeta, dict) else None
            ts = ts if isinstance(ts, int) and not isinstance(ts, bool) else None
            state_name = event["from_state"]
            if state_name in ("idle", "active", "waiting"):
                name = f"dwell_{state_name}_ms"
                # Card 1090: tw's own stamps when both hops carry one (a spool
                # replay arrives late); host receive time otherwise.
                if ts is not None and prev_ts is not None:
                    elapsed = max(0, ts - prev_ts)
                else:
                    elapsed = max(0, (event["at"] - previous).total_seconds() * 1000)
                measures[name] = measures.get(name, 0) + elapsed
            previous, prev_ts = event["at"], ts
            if event["reason"] == "tw_wait":
                cause = emeta.get("cause")
                if cause:
                    waits[cause] = waits.get(cause, 0) + 1
        if waits:
            measures["wait_by_cause"] = json.dumps(waits, sort_keys=True)
        if to_state in (tr.State.finished, tr.State.failed):
            measures["end_reason"] = reason.value
        # Card 1098: last_run lives in the score ledger with one score transition
        # per start/exit/crash (S1 none->live, S3b live->live). Stall/resume skip.
        if kind in ("start", "exit", "crash"):
            if kind == "start":
                phase = "start"
                last = "active"
            elif to_state == tr.State.finished:
                phase = "finished"
                last = "finished"
            else:
                phase = "failed"
                last = "failed"
            measures["last_run"] = last
            score_meta: dict[str, Any] = {
                "watch_id": meta.get("watch_id"),
                "phase": phase,
            }
            if "exit_code" in meta:
                score_meta["exit_code"] = meta["exit_code"]
            if meta.get("cause"):
                score_meta["cause"] = meta["cause"]
            if "end_reason" in measures:
                score_meta["end_reason"] = measures["end_reason"]
            for dwell_key in ("dwell_active_ms", "dwell_waiting_ms"):
                if dwell_key in measures:
                    score_meta[dwell_key] = measures[dwell_key]
            score_rows = score.upsert(
                cn, "Office", desk, "doing.task.last_run", str(last)
            )
            score_id = int(score_rows[0]["id"])
            cur = cn.cursor(dictionary=True)
            try:
                cur.execute(
                    "SELECT 1 FROM transition"
                    " WHERE activity_type=%s AND activity_id=%s"
                    " ORDER BY at DESC LIMIT 1",
                    (tr.ActivityType.score.value, score_id),
                )
                prior = cur.fetchone() is not None
            finally:
                cur.close()
            tr.put(
                cn,
                activity_type=tr.ActivityType.score,
                activity_id=score_id,
                from_state=tr.State.live if prior else tr.State.none,
                to_state=tr.State.live,
                reason=tr.Reason.score_point,
                desk_id=row["desk_id"],
                join_key=key,
                meta=score_meta,
            )
    else:
        # Overflow/retry are metrics, never Tsk8 or any other transition.
        measures = {}
        if kind == "overflow" and meta.get("counts", {}).get("dropped") is not None:
            measures["buffer_overflow_n"] = meta["counts"]["dropped"]
        if kind == "retry" and outcome == "give_up":
            measures["retry_give_up_n"] = 1
    for name, value in measures.items():
        if name == "last_run":
            continue  # already upserted above with the score transition
        score.upsert(cn, "Office", desk, "doing.task." + name, str(value))
    return "wrote" if kind in mapped else "metric"


# Card 1223 part B: a mill call a run's descendant made through tw's per-run endpoint. tw stamps the run's
# watch id on the call; the office keeps one tw_call row (same state in and out) on that run's doing row.
# The row's meta is the watch id, the command word and ok, plus err (refused or error) on a failure.
CALL_WATCH_MAX = 64
RUN_CALLS_SHOWN = 200
_LIVE = ("active", "waiting")


def call_watch_id(raw: Any) -> str:
    """The watch id a forwarded call carries, or a refusal (it never reaches the command)."""
    import re

    from agent_coord.helpers.errors import CoordError

    wid = "" if raw is None or isinstance(raw, bool) else str(raw).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,%d}" % CALL_WATCH_MAX, wid):
        raise CoordError("tw run: the watch id on this call is not a tw watch id; nothing was changed")
    return wid


def parent_watch_id(raw: Any, wid: str) -> str:
    """The parent a nested start names. A start that omits the field has no parent link."""
    import re

    from agent_coord.helpers.errors import CoordError

    if isinstance(raw, bool) or not isinstance(raw, str):
        raise CoordError("tw.event: parent_watch_id must be a watch id")
    parent = raw.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,%d}" % CALL_WATCH_MAX, parent):
        raise CoordError("tw.event: parent_watch_id must be a watch id")
    if parent == wid:
        raise CoordError("tw.event: parent_watch_id must name another run")
    return parent


def open_call(cn, desk: str, wid: str) -> None:
    """Inside the caller's request tx, before the command runs: the call's run must be live.

    A run tw has not reported yet starts here (the hop that names it can land after its first child's
    call); tw's own start then is a repeat. An ended run, or a start past the task cap, refuses.
    """
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server.records.name import bare

    desk = bare(desk, CONST_DESK)
    row = call(cn, "mill_doing_task", [desk, f"task:{desk}:{wid}", None, 0])[0]
    if row["id"] is None:
        done = task_event(cn, desk, {"watch_id": wid, "desk": desk, "kind": "start", "cause": "call"})
        if done == "cap":
            raise CoordError(cap_hint(cn, desk) + "; nothing was changed")
        return
    if str(row["state"]) not in _LIVE:
        raise CoordError(f"tw run {wid} has ended ({row['state']}); nothing was changed")


def note_call(cn, desk: str, wid: str, verb: str, ok: bool, err: str = "") -> str:
    """Inside the caller's request tx, after the command: one tw_call row on the live run.

    Returns "wrote", or "ended" when the run ended while the command ran (nothing written).
    """
    from agent_coord.server import transition as tr
    from agent_coord.server.records.name import bare

    desk = bare(desk, CONST_DESK)
    key = f"task:{desk}:{wid}"
    row = call(cn, "mill_doing_task", [desk, key, None, 0])[0]
    if row["id"] is None or str(row["state"]) not in _LIVE:
        return "ended"
    meta: dict[str, Any] = {"watch_id": wid, "verb": str(verb)[:32], "ok": bool(ok)}
    if not ok:
        meta["err"] = err if err in ("refused", "error") else "error"
    state = tr.State(row["state"])
    tr.put(cn, activity_type=tr.ActivityType.doing, activity_id=row["id"], from_state=state,
           to_state=state, reason=tr.Reason.tw_call, desk_id=row["desk_id"], join_key=key, meta=meta)
    return "wrote"


def _meta_obj(raw: Any) -> dict[str, Any]:
    import json

    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _watch_from_join(desk: str, join_key: Any) -> str | None:
    prefix = f"task:{desk}:"
    key = "" if join_key is None else str(join_key)
    if not key.startswith(prefix):
        return None
    wid = key[len(prefix):]
    return wid or None


def _attach_parent(cn, doing_id: int, parent: Any) -> None:
    """A later start is still one tw_start. Keep a parent link the first row did not have."""
    import json

    if not isinstance(parent, str) or not parent:
        return
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT id, meta FROM transition"
            " WHERE activity_type='doing' AND activity_id=%s AND reason='tw_start'"
            " ORDER BY id LIMIT 1 FOR UPDATE",
            (int(doing_id),),
        )
        start = cur.fetchone()
        if not start:
            return
        existing = _meta_obj(start.get("meta"))
        if existing.get("parent_watch_id"):
            return
        existing["parent_watch_id"] = parent
        cur.execute(
            "UPDATE transition SET meta=%s WHERE id=%s",
            (json.dumps(existing), int(start["id"])),
        )
    finally:
        cur.close()


def _stored_parent(meta: dict[str, Any], wid: str) -> str | None:
    raw = meta.get("parent_watch_id")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str):
        return None
    parent = raw.strip()
    if not parent or parent == wid:
        return None
    return parent


def _run_from_hops(desk: str, wid: str, created: Any, hops: list[dict[str, Any]]) -> dict[str, Any]:
    """One run. A tw_call is a call on this run, never a change of state or state time."""
    state, end, ended_by, exit_code = "started", None, None, None
    calls: list[dict[str, Any]] = []
    ok_n = 0
    parent = None
    seen_start = False
    for hop in hops:
        meta = _meta_obj(hop.get("meta"))
        if hop["reason"] == "tw_call":
            good = meta.get("ok") is True
            ok_n += 1 if good else 0
            row: dict[str, Any] = {"at": _utc_iso(hop["at"]), "verb": str(meta.get("verb") or ""), "ok": good}
            if not good:
                row["err"] = str(meta.get("err") or "error")
            calls.append(row)
            continue
        if hop["reason"] == "tw_start" and not seen_start:
            parent = _stored_parent(meta, wid)
            seen_start = True
        state = str(hop["to_state"])
        if state in _TASK_TERMINAL and end is None:
            end, ended_by = _utc_iso(hop["at"]), state
            code = meta.get("exit_code")
            exit_code = code if isinstance(code, int) and not isinstance(code, bool) else None
    return {
        "watch_id": wid,
        "parent_watch_id": parent,
        "desk": desk,
        "start": _utc_iso(created),
        "end": end,
        "ended_by": ended_by,
        "exit_code": exit_code,
        "state": state,
        "calls_n": len(calls),
        "ok_n": ok_n,
        "failed_n": len(calls) - ok_n,
        "calls": calls[-RUN_CALLS_SHOWN:],
    }


def _descendant_keys(cn, desk: str, root: str) -> list[tuple[Any, int, str]]:
    """Runs nested under root on this desk, by start time then id. A cycle stops."""
    found: list[tuple[Any, int, str]] = []
    seen = {root}
    frontier = [root]
    while frontier:
        marks = ",".join(["%s"] * len(frontier))
        rows = rows_done(cn, f"""
            SELECT g.id, t.join_key,
                   IFNULL(CONVERT_TZ(g.created, @@session.time_zone, '+00:00'),
                          g.created + INTERVAL TIMESTAMPDIFF(SECOND, NOW(6), UTC_TIMESTAMP(6)) SECOND) AS created_utc
              FROM transition t
              JOIN doing g ON g.id = t.activity_id
              JOIN name d ON d.id = g.desk_id AND d.type = 'desk'
             WHERE d.name = %s AND t.activity_type = 'doing' AND t.reason = 'tw_start'
               AND JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.parent_watch_id')) IN ({marks})
             ORDER BY g.created, g.id""",
            (desk, *frontier),
        )
        frontier = []
        for row in rows:
            wid = _watch_from_join(desk, row.get("join_key"))
            if not wid or wid in seen:
                continue
            seen.add(wid)
            found.append((row.get("created_utc"), int(row["id"]), wid))
            frontier.append(wid)
    found.sort(key=lambda item: (item[0] is None, item[0] or "", item[1]))
    return found


def run_tree(cn, desk: str, wid: str) -> dict[str, Any]:
    """`mill connected --run WATCH_ID`: that run and the runs nested under it.

    The requested run is first. Descendants follow by start time. Each run carries
    parent_watch_id from its tw_start meta (null when it has none). n is how many
    runs that is. Asking for a nested run does not include the run above it. A
    parent id with no row is kept and is not an error. A tw_call stays a call on
    its run (card 1239).
    """
    from agent_coord.helpers.errors import CoordError
    from agent_coord.server.records.name import bare

    desk = bare(desk, CONST_DESK)
    wid = str(wid or "").strip()
    key = f"task:{desk}:{wid}"
    run = rows_done(cn, """
        SELECT g.id,
               IFNULL(CONVERT_TZ(g.created, @@session.time_zone, '+00:00'),
                      g.created + INTERVAL TIMESTAMPDIFF(SECOND, NOW(6), UTC_TIMESTAMP(6)) SECOND) AS created_utc
          FROM doing g JOIN name d ON d.id = g.desk_id AND d.type = 'desk'
         WHERE d.name = %s AND g.id = (
           SELECT t.activity_id FROM transition t
            WHERE t.activity_type = 'doing' AND t.join_key = %s ORDER BY t.id LIMIT 1)""",
        (desk, key),
    )
    if not run:
        raise CoordError(f"connected --run: no tw run {wid[:64]} for desk {desk}")
    nodes = [(run[0].get("created_utc"), int(run[0]["id"]), wid)]
    nodes.extend(_descendant_keys(cn, desk, wid))
    keys = [f"task:{desk}:{node[2]}" for node in nodes]
    marks = ",".join(["%s"] * len(keys))
    hop_rows = rows_done(cn, f"""
        SELECT join_key, at, to_state, reason, meta FROM transition
         WHERE activity_type = 'doing' AND join_key IN ({marks})
         ORDER BY id""",
        tuple(keys),
    )
    by_key: dict[str, list] = {one: [] for one in keys}
    for hop in hop_rows:
        by_key.setdefault(str(hop["join_key"]), []).append(hop)
    runs = [
        _run_from_hops(desk, node[2], node[0], by_key.get(f"task:{desk}:{node[2]}", []))
        for node in nodes
    ]
    return {"runs": runs, "n": len(runs)}
