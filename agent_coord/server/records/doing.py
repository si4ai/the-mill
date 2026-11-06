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

from .db import call

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

    return call(
        cn,
        "mill_doing_now",
        [bare(desk, CONST_DESK) if desk else "", roster or "", 1 if all_desks else 0],
    ) or []


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
            " AND t.to_state IN (%s, %s, %s, %s))",
            (desk_id, *_TASK_TERMINAL),
        )
        return int(cur.fetchone()[0])
    finally:
        cur.close()


def task_event(cn, desk: str, meta: dict[str, Any], *, outcome: str = "") -> str:
    """Card 970: one serialized task lifecycle, inside the caller's request tx.

    Returns "cap" (a 9th live start; nothing written), "noop" (a replayed or
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
        if live_tasks(cn, row["desk_id"]) >= TASK_CAP:
            return "cap"
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
    else:
        # Overflow/retry are metrics, never Tsk8 or any other transition.
        measures = {}
        if kind == "overflow" and meta.get("counts", {}).get("dropped") is not None:
            measures["buffer_overflow_n"] = meta["counts"]["dropped"]
        if kind == "retry" and outcome == "give_up":
            measures["retry_give_up_n"] = 1
    for name, value in measures.items():
        score.upsert(cn, "Office", desk, "doing.task." + name, str(value))
    return "wrote" if kind in mapped else "metric"
