"""Transition enums and allowed edges (card 1022).

Module path: agent_coord/server/transition_enums.py

Enums in code, text in rows: from_state/to_state/reason/wake.state/wake.cause are
VARCHAR(32) ascii_bin; ActivityType/State/Reason/WakeCause are the only names
code may use. Insert helper refuses a raw str. State map:
docs/protocol/state-instrumentation.md (about 70 transitions; expansions noted
in AMBIGUOUS_MAP_NOTES). Enum member is the stable key for display/localization
(no translations in this card).
"""
from __future__ import annotations

from enum import Enum

class ActivityType(str, Enum):
    mail = "mail"
    todo = "todo"
    doing = "doing"
    hold = "hold"
    score = "score"
    wake = "wake"

class State(str, Enum):
    none = "none"
    error = "error"
    missed = "missed"
    sent = "sent"
    taken = "taken"
    queued = "queued"
    any = "any"
    same = "same"
    prior = "prior"
    idle = "idle"
    push_pending = "push_pending"
    unread_owed = "unread_owed"
    lease_live = "lease_live"
    retry_armed = "retry_armed"
    sitting = "sitting"
    lost_unread = "lost_unread"
    drained = "drained"
    left = "left"
    coalesced = "coalesced"
    skipped = "skipped"
    expire = "expire"
    fail = "fail"
    trail = "trail"
    ring = "ring"
    live = "live"
    deleted = "deleted"
    unread = "unread"
    handled = "handled"
    removed = "removed"
    delivered = "delivered"
    woken = "woken"
    answered = "answered"
    refused = "refused"
    open = "open"
    parked = "parked"
    claimed = "claimed"
    shipped = "shipped"
    done = "done"
    retired = "retired"
    no_seat = "no_seat"
    seated = "seated"
    connected = "connected"
    reset = "reset"
    active = "active"
    waiting = "waiting"
    finished = "finished"
    cleared = "cleared"
    stale = "stale"
    failed = "failed"
    cycle = "cycle"
    no_row = "no_row"
    free = "free"
    held = "held"
    expired = "expired"
    defined = "defined"

class Reason(str, Enum):
    other = "other"
    send_or_queue = "send_or_queue"
    reply = "reply"
    mark = "mark"
    thread_read = "thread_read"
    preview = "preview"
    add_recipient = "add_recipient"
    remove_recipient = "remove_recipient"
    delete_probe = "delete_probe"
    create = "create"
    create_parked = "create_parked"
    unpark = "unpark"
    claim = "claim"
    assign = "assign"
    take_over = "take_over"
    unclaim = "unclaim"
    pass_ship = "pass_ship"
    pass_done = "pass_done"
    pass_back = "pass_back"
    retire = "retire"
    reclaim = "reclaim"
    note = "note"
    join = "join"
    connect = "connect"
    disconnect = "disconnect"
    doing_put = "doing_put"
    doing_wait = "doing_wait"
    doing_newer = "doing_newer"
    finish_reply = "finish_reply"
    finish_pass = "finish_pass"
    finish_drop = "finish_drop"
    clear = "clear"
    reset_seat = "reset_seat"
    tw_start = "tw_start"
    tw_wait = "tw_wait"
    tw_resume = "tw_resume"
    tw_finished = "tw_finished"
    tw_failed = "tw_failed"
    tw_stale = "tw_stale"
    wait_cycle = "wait_cycle"
    hold_grant = "hold_grant"
    hold_refresh = "hold_refresh"
    hold_drop = "hold_drop"
    hold_force = "hold_force"
    hold_peek = "hold_peek"
    hold_refuse = "hold_refuse"
    hold_wait_acquire = "hold_wait_acquire"
    hold_expire = "hold_expire"
    score_point = "score_point"
    score_define = "score_define"
    score_retarget = "score_retarget"
    score_retire = "score_retire"
    score_revive = "score_revive"
    score_refuse = "score_refuse"
    wake_queue = "wake_queue"
    wake_owed = "wake_owed"
    wake_sent = "wake_sent"
    wake_fail = "wake_fail"
    wake_retry = "wake_retry"
    wake_drain = "wake_drain"
    wake_trail = "wake_trail"
    wake_ring = "wake_ring"
    wake_done = "wake_done"
    wake_stale = "wake_stale"
    wake_sitting = "wake_sitting"
    wake_expire = "wake_expire"
    wake_coalesce = "wake_coalesce"
    wake_skip = "wake_skip"
    wake_sit = "wake_sit"
    wake_leave = "wake_leave"
    wake_deliver = "wake_deliver"
    wake_lost = "wake_lost"
    delivered = "delivered"
    woken = "woken"
    answered = "answered"
    size_limit = "size_limit"
    orphan_refuse = "orphan_refuse"

class WakeCause(str, Enum):
    mail = "mail"
    hint = "hint"
    receipt = "receipt"
    expired = "expired"
    room = "room"
    retry = "retry"
    test = "test"


AMBIGUOUS_MAP_NOTES: tuple[str, ...] = (
    "W3/W4: map from 'push/unread' expanded to push_pending and unread_owed",
    "W6: map to 'drained/idle' expanded to drained and idle",
    "T11: map to 'claimed/open' expanded to claimed and open",
    "T13: reclaim 'prior status' modeled as to_state=prior (status kept on todo row)",
    'T15/M9: live used for letter/card before delete (map says live)',
    "Tsk4-6: from 'active/waiting' expanded to both",
    "S3/S5: from 'defined/live' expanded to both",
    'D3: connect leave modeled seated (desk still seated, socket gone)',
    'M1: also emits unread per recipient (M1r) alongside letter live',
    'M12: answered from handled or unread',
)

ALLOWED_TRANSITIONS: frozenset[tuple[ActivityType, State, State, Reason]] = frozenset(
    {

        (ActivityType.wake, State.none, State.queued, Reason.wake_queue),  # Q1
        (ActivityType.wake, State.queued, State.sent, Reason.wake_sent),  # Q2
        (ActivityType.wake, State.queued, State.missed, Reason.wake_owed),  # Q3
        (ActivityType.wake, State.queued, State.error, Reason.wake_fail),  # Q4
        (ActivityType.wake, State.sent, State.taken, Reason.wake_deliver),  # Q5
        (ActivityType.wake, State.missed, State.taken, Reason.wake_deliver),  # Q6
        (ActivityType.wake, State.error, State.taken, Reason.wake_deliver),  # Q7
        (ActivityType.wake, State.queued, State.taken, Reason.wake_deliver),  # Q8
        (ActivityType.wake, State.sent, State.missed, Reason.wake_owed),  # Q9 put_back
        (ActivityType.wake, State.missed, State.sent, Reason.wake_sent),  # Q10 mark live
        (ActivityType.wake, State.missed, State.error, Reason.wake_fail),  # Q11 mark error
        (ActivityType.wake, State.idle, State.push_pending, Reason.wake_queue),  # W1
        (ActivityType.wake, State.none, State.unread_owed, Reason.wake_owed),  # W2
        (ActivityType.wake, State.push_pending, State.lease_live, Reason.wake_sent),  # W3a
        (ActivityType.wake, State.unread_owed, State.lease_live, Reason.wake_sent),  # W3b
        (ActivityType.wake, State.push_pending, State.lease_live, Reason.wake_fail),  # W4a
        (ActivityType.wake, State.unread_owed, State.lease_live, Reason.wake_fail),  # W4b
        (ActivityType.wake, State.fail, State.retry_armed, Reason.wake_retry),  # W5
        (ActivityType.wake, State.retry_armed, State.drained, Reason.wake_drain),  # W6a
        (ActivityType.wake, State.retry_armed, State.idle, Reason.wake_drain),  # W6b
        (ActivityType.wake, State.lease_live, State.trail, Reason.wake_trail),  # W7
        (ActivityType.wake, State.left, State.ring, Reason.wake_ring),  # W8
        (ActivityType.wake, State.lease_live, State.idle, Reason.wake_done),  # W9
        (ActivityType.wake, State.lease_live, State.idle, Reason.wake_stale),  # W10
        (ActivityType.wake, State.lease_live, State.idle, Reason.wake_sitting),  # W11
        (ActivityType.wake, State.lease_live, State.expire, Reason.wake_expire),  # W12
        (ActivityType.wake, State.any, State.coalesced, Reason.wake_coalesce),  # W13
        (ActivityType.wake, State.any, State.skipped, Reason.wake_skip),  # W14
        (ActivityType.wake, State.any, State.sitting, Reason.wake_sit),  # W15
        (ActivityType.wake, State.sitting, State.left, Reason.wake_leave),  # W16
        (ActivityType.wake, State.push_pending, State.drained, Reason.wake_deliver),  # W17
        (ActivityType.wake, State.unread_owed, State.lost_unread, Reason.wake_lost),  # W18
        (ActivityType.mail, State.none, State.live, Reason.send_or_queue),  # M1
        (ActivityType.mail, State.none, State.unread, Reason.send_or_queue),  # M1r
        (ActivityType.mail, State.none, State.live, Reason.reply),  # M2
        (ActivityType.mail, State.unread, State.handled, Reason.mark),  # M3
        (ActivityType.mail, State.unread, State.handled, Reason.thread_read),  # M4
        (ActivityType.mail, State.unread, State.unread, Reason.preview),  # M5
        (ActivityType.mail, State.handled, State.handled, Reason.mark),  # M6
        (ActivityType.mail, State.none, State.unread, Reason.add_recipient),  # M7
        (ActivityType.mail, State.unread, State.removed, Reason.remove_recipient),  # M8a
        (ActivityType.mail, State.handled, State.removed, Reason.remove_recipient),  # M8b
        (ActivityType.mail, State.live, State.deleted, Reason.delete_probe),  # M9
        (ActivityType.mail, State.live, State.delivered, Reason.delivered),  # M10
        (ActivityType.mail, State.delivered, State.woken, Reason.woken),  # M11
        (ActivityType.mail, State.handled, State.answered, Reason.answered),  # M12
        (ActivityType.mail, State.unread, State.answered, Reason.answered),  # M12b
        (ActivityType.mail, State.any, State.refused, Reason.size_limit),  # M13
        (ActivityType.mail, State.any, State.refused, Reason.orphan_refuse),  # M14
        (ActivityType.todo, State.none, State.open, Reason.create),  # T1
        (ActivityType.todo, State.none, State.parked, Reason.create_parked),  # T2
        (ActivityType.todo, State.parked, State.open, Reason.unpark),  # T3
        (ActivityType.todo, State.open, State.claimed, Reason.claim),  # T4
        (ActivityType.todo, State.open, State.claimed, Reason.assign),  # T5
        (ActivityType.todo, State.claimed, State.claimed, Reason.take_over),  # T6
        (ActivityType.todo, State.claimed, State.open, Reason.unclaim),  # T7
        (ActivityType.todo, State.claimed, State.shipped, Reason.pass_ship),  # T8
        (ActivityType.todo, State.shipped, State.done, Reason.pass_done),  # T9
        (ActivityType.todo, State.done, State.shipped, Reason.pass_back),  # T10
        (ActivityType.todo, State.shipped, State.claimed, Reason.pass_back),  # T11a
        (ActivityType.todo, State.shipped, State.open, Reason.pass_back),  # T11b
        (ActivityType.todo, State.any, State.retired, Reason.retire),  # T12
        (ActivityType.todo, State.retired, State.prior, Reason.reclaim),  # T13
        (ActivityType.todo, State.any, State.same, Reason.note),  # T14
        (ActivityType.todo, State.live, State.deleted, Reason.delete_probe),  # T15
        (ActivityType.doing, State.no_seat, State.seated, Reason.join),  # D1
        (ActivityType.doing, State.seated, State.connected, Reason.connect),  # D2
        (ActivityType.doing, State.connected, State.seated, Reason.disconnect),  # D3
        (ActivityType.doing, State.idle, State.active, Reason.doing_put),  # D4
        (ActivityType.doing, State.active, State.waiting, Reason.doing_wait),  # D5
        (ActivityType.doing, State.active, State.active, Reason.doing_newer),  # D6
        (ActivityType.doing, State.active, State.finished, Reason.finish_reply),  # D7
        (ActivityType.doing, State.active, State.finished, Reason.finish_pass),  # D8
        (ActivityType.doing, State.active, State.finished, Reason.finish_drop),  # D9
        (ActivityType.doing, State.any, State.cleared, Reason.clear),  # D10
        (ActivityType.doing, State.seated, State.reset, Reason.reset_seat),  # D11
        (ActivityType.doing, State.idle, State.active, Reason.tw_start),  # Tsk1
        (ActivityType.doing, State.active, State.waiting, Reason.tw_wait),  # Tsk2
        (ActivityType.doing, State.waiting, State.active, Reason.tw_resume),  # Tsk3
        (ActivityType.doing, State.active, State.finished, Reason.tw_finished),  # Tsk4a
        (ActivityType.doing, State.waiting, State.finished, Reason.tw_finished),  # Tsk4b
        (ActivityType.doing, State.active, State.failed, Reason.tw_failed),  # Tsk5a
        (ActivityType.doing, State.waiting, State.failed, Reason.tw_failed),  # Tsk5b
        (ActivityType.doing, State.active, State.stale, Reason.tw_stale),  # Tsk6a
        (ActivityType.doing, State.waiting, State.stale, Reason.tw_stale),  # Tsk6b
        (ActivityType.doing, State.any, State.cleared, Reason.clear),  # Tsk7
        (ActivityType.doing, State.waiting, State.waiting, Reason.wait_cycle),  # Tsk8
        (ActivityType.hold, State.no_row, State.held, Reason.hold_grant),  # H1
        (ActivityType.hold, State.free, State.held, Reason.hold_grant),  # H2
        (ActivityType.hold, State.held, State.held, Reason.hold_refresh),  # H3
        (ActivityType.hold, State.held, State.free, Reason.hold_drop),  # H4
        (ActivityType.hold, State.held, State.free, Reason.hold_force),  # H5
        (ActivityType.hold, State.any, State.same, Reason.hold_peek),  # H6
        (ActivityType.hold, State.any, State.refused, Reason.hold_refuse),  # H7
        (ActivityType.hold, State.refused, State.held, Reason.hold_wait_acquire),  # H8
        (ActivityType.hold, State.held, State.expired, Reason.hold_expire),  # H9
        (ActivityType.score, State.none, State.live, Reason.score_point),  # S1
        (ActivityType.score, State.none, State.defined, Reason.score_define),  # S2
        (ActivityType.score, State.defined, State.live, Reason.score_point),  # S3a
        (ActivityType.score, State.live, State.live, Reason.score_point),  # S3b
        (ActivityType.score, State.live, State.live, Reason.score_retarget),  # S4
        (ActivityType.score, State.live, State.retired, Reason.score_retire),  # S5a
        (ActivityType.score, State.defined, State.retired, Reason.score_retire),  # S5b
        (ActivityType.score, State.retired, State.live, Reason.score_revive),  # S6a
        (ActivityType.score, State.retired, State.defined, Reason.score_revive),  # S6b
        (ActivityType.score, State.any, State.refused, Reason.score_refuse),  # S7
    }
)



class UnknownTransition(ValueError):
    """Emitter refused: tuple not in ALLOWED_TRANSITIONS."""


def _require_enum(val, cls: type, name: str):
    if not isinstance(val, cls):
        raise TypeError(
            f"{name} must be {cls.__name__}, not {type(val).__name__}"
        )


def check_edge(
    activity_type: ActivityType,
    from_state: State,
    to_state: State,
    reason: Reason,
) -> None:
    _require_enum(activity_type, ActivityType, "activity_type")
    _require_enum(from_state, State, "from_state")
    _require_enum(to_state, State, "to_state")
    _require_enum(reason, Reason, "reason")
    if (activity_type, from_state, to_state, reason) not in ALLOWED_TRANSITIONS:
        raise UnknownTransition(
            f"unknown transition ({activity_type.value}, {from_state.value}, "
            f"{to_state.value}, {reason.value})"
        )


def put(
    cn,
    *,
    activity_type: ActivityType,
    activity_id: int,
    from_state: State,
    to_state: State,
    reason: Reason,
    desk_id: int | None = 0,
    role: str = "actor",
    join_key: str | None = None,
    meta=None,
) -> None:
    """Insert one transition via mill_transition_put. Enums only (no bare strings)."""
    import json

    from agent_coord.server.records.db import call

    check_edge(activity_type, from_state, to_state, reason)
    meta_arg = None if meta is None else (meta if isinstance(meta, str) else json.dumps(meta))
    call(
        cn,
        "mill_transition_put",
        [
            activity_type.value,
            int(activity_id),
            from_state.value,
            to_state.value,
            reason.value,
            0 if desk_id is None else int(desk_id),
            role or "actor",
            join_key,
            meta_arg,
        ],
    )
