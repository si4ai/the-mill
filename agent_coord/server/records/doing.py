"""#818 PR B: doing entries written by `--doing` on an activity command, and
the reads behind `mill connected` (what each desk is doing, and its history).

Writes: one entry per command, linked to the item that command wrote. The
newest entry is the desk's current doing. It ends on a real event, derived on
read (see sp_doing.sql): a reply by the desk under the letter, a pass or done
of the card or the drop of the hold by the desk without --doing (finish
appends an empty row on that item), clock-out or reset (an empty row with no
item), or a newer entry.
"""

from __future__ import annotations

from typing import Any

from agent_coord.const import CONST_DESK

from .db import call, rows_done

TEXT_MAX = 512
ON_TYPES = ("mail", "todo", "hold", "score")


WHY_MAX = 200


def put(cn, desk: str, text: str, on_type: str, on_id: int,
        waiting: tuple[str, str, str] | None = None) -> dict[str, Any]:
    """waiting (#822): (type, ref, why), type desk (ref the name) or mail, todo,
    hold (ref the id). Stored as fields on this row; no edge or link table."""
    from agent_coord.server.records.name import bare

    w_type, w_ref, w_why = waiting or (None, None, None)
    if w_type == "desk":
        w_ref = bare(str(w_ref), CONST_DESK)
    rows = call(cn, "mill_doing_put", [
        bare(desk, CONST_DESK), text[:TEXT_MAX], on_type, int(on_id),
        w_type, w_ref, (w_why or "")[:WHY_MAX] if w_type else None,
    ])
    return rows[0] if rows else {}


def finish(cn, desk: str, on_type: str, on_id: int) -> None:
    """A pass, done or drop by the desk without --doing: end its entry on this item."""
    from agent_coord.server.records.name import bare

    call(cn, "mill_doing_finish", [bare(desk, CONST_DESK), on_type, int(on_id)])


def now(cn, desk: str = "", roster: str = "", all_desks: bool = False) -> list[dict[str, Any]]:
    from agent_coord.server.records.name import bare

    rows = call(
        cn,
        "mill_doing_now",
        [bare(desk, CONST_DESK) if desk else "", roster or "", 1 if all_desks else 0],
    ) or []
    rows.extend(task_rows(cn, [r["desk"] for r in rows if r.get("part") == "desk"]))
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
    """Past entries, newest first; on_type/on_id keep one item's entries (desk may be empty)."""
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_doing_history",
        [bare(desk, CONST_DESK) if desk else "", since, int(page), int(size),
         on_type or "", int(on_id) if on_type and on_id is not None else None],
    ) or []


# Card 970 step 4: live (non-terminal) act=task doing rows a desk may hold.
TASK_CAP = 8
_TASK_TERMINAL = ("finished", "failed", "stale", "cleared")


def live_tasks(cn, desk_id: int) -> int:
    """Count the desk's act=task doing rows with no terminal transition."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) FROM doing g WHERE g.desk_id=%s AND g.act='task' AND NOT EXISTS ("
            " SELECT 1 FROM transition t WHERE t.activity_type='doing' AND t.activity_id=g.id"
            " AND t.to_state IN (%s, %s, %s, %s)) FOR SHARE",
            (desk_id, *_TASK_TERMINAL),
        )
        return int(cur.fetchone()[0])
    finally:
        cur.close()


# Card 1090 step 4: a live task row whose latest hop is older than this is
# stale. Swept only when a start would hit TASK_CAP (one tw_stale edge each).
STALE_AFTER_S = 24 * 3600
CAP_HINT_N = 3


def _live_task_ages(cn, desk_id: int) -> list[dict[str, Any]]:
    """The desk's live act=task rows, oldest latest hop first, with that hop's
    effective state (card 1098 compress: even n means back at from_state)."""
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT g.id, t.join_key,"
            " IF(MOD(t.n, 2) = 1, t.to_state, t.from_state) AS state,"
            " TIMESTAMPDIFF(SECOND, t.at, UTC_TIMESTAMP(6)) AS age_s"
            " FROM doing g JOIN transition t ON t.id = ("
            "  SELECT MAX(l.id) FROM transition l"
            "   WHERE l.activity_type='doing' AND l.activity_id=g.id)"
            " WHERE g.desk_id=%s AND g.act='task' AND NOT EXISTS ("
            "  SELECT 1 FROM transition e WHERE e.activity_type='doing' AND e.activity_id=g.id"
            "   AND e.to_state IN (%s, %s, %s, %s))"
            " ORDER BY t.at, g.id FOR SHARE",
            (desk_id, *_TASK_TERMINAL),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def sweep_stale_tasks(cn, desk_id: int) -> int:
    """Close the desk's live task rows idle longer than STALE_AFTER_S.

    Runs inside the caller's request tx, under the seat lock mill_doing_task
    took. Each swept row gets one tw_stale edge (meta cause=sweep, age_s).
    Returns how many rows it closed.
    """
    from agent_coord.server import transition as tr

    n = 0
    for r in _live_task_ages(cn, desk_id):
        if int(r["age_s"]) < STALE_AFTER_S or r["state"] not in ("active", "waiting"):
            continue
        key = str(r["join_key"])
        tr.put(cn, activity_type=tr.ActivityType.doing, activity_id=int(r["id"]),
               from_state=tr.State(r["state"]), to_state=tr.State.stale,
               reason=tr.Reason.tw_stale, desk_id=desk_id, join_key=key,
               meta={"watch_id": key.split(":", 2)[-1], "cause": "sweep",
                     "age_s": int(r["age_s"])})
        n += 1
    return n


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
    return (f"{msg}; oldest: {named}; end one with tw stop, or it is swept"
            f" after {_age(STALE_AFTER_S)} idle")


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


def task_rows(cn, desks: list[str]) -> list[dict[str, Any]]:
    """One bounded batch for the connected desks; no focus pointer or private payloads."""
    if not desks:
        return []
    return rows_done(cn, """
        SELECT 'task' AS part, d.name AS desk, x.state, x.join_key, x.cause, x.card_id
          FROM name d
          JOIN LATERAL (
            SELECT COALESCE(t.to_state, 'idle') AS state, t.join_key,
                   CASE WHEN t.to_state='waiting'
                        THEN JSON_UNQUOTE(JSON_EXTRACT(t.meta, '$.cause')) END AS cause,
                   card.id AS card_id
              FROM doing g
              LEFT JOIN transition t ON t.id=(
                SELECT latest.id FROM transition latest
                 WHERE latest.activity_type='doing' AND latest.activity_id=g.id
                 ORDER BY latest.id DESC LIMIT 1)
              LEFT JOIN todo card ON g.on_type='todo' AND card.id=g.on_id
             WHERE g.desk_id=d.id AND g.act='task' AND NOT EXISTS (
                SELECT 1 FROM transition ended
                 WHERE ended.activity_type='doing' AND ended.activity_id=g.id
                   AND ended.to_state IN (%s, %s, %s, %s))
             ORDER BY g.created DESC, g.id DESC LIMIT %s
          ) x ON TRUE
         WHERE d.type='desk' AND d.name IN (""" + ",".join(["%s"] * len(desks)) + ")",
        (*_TASK_TERMINAL, TASK_CAP, *desks),
    )


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
        previous = row["created"]
        for event in events:
            state_name = event["from_state"]
            if state_name in ("idle", "active", "waiting"):
                name = f"dwell_{state_name}_ms"
                elapsed = max(0, (event["at"] - previous).total_seconds() * 1000)
                measures[name] = measures.get(name, 0) + elapsed
            previous = event["at"]
            if event["reason"] == "tw_wait":
                cause = json.loads(event["meta"]).get("cause")
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
