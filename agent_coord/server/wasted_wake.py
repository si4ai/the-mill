# -*- coding: utf-8 -*-
"""Card 1002: count no-action (wasted) wakes and tag each by its trigger.

Measure only. A wake lease that ends in mill wake-done with no action command
(send, reply, claim, note, pass, hold, label) between start and done is wasted;
mark and read alone still count as waste. Trigger tags (human 2026-11-01):
hold_release, room_or_fyi_mail, rering_handled, version_notice, other.

Emits ``op=wake.done`` (wasted=0|1) on mill-perf for score_tick; also ``op=wake.wasted`` when wasted. Keeps per-desk and
per-office counts for mill score (share + trigger breakdown). Does not change
wake behavior (card 949 rules stay on hold).
"""
from __future__ import annotations

import threading
from typing import Any

TRIGGERS = (
    "hold_release",
    "room_or_fyi_mail",
    "rering_handled",
    "version_notice",
    "other",
)

# Card 1002: actions that make a wake useful. Mark/read/inbox alone still waste.
ACTION_COMMANDS = frozenset(
    {
        "send",
        "reply",
        "claim",
        "note",
        "pass",
        "hold",
        "label",
        "label-add",
        "label-remove",
        "drop",  # drop is a hold action
        "assign",
        "unclaim",
        "open",  # create todo
        "unpark",
        "attach",
        "move",
        "retire",
    }
)

_SKIP = frozenset({"heartbeat", "session", "join", "wake-done", "wake"})

KPI_WASTED = "mill-office.wasted_wake_n"
KPI_SHARE = "mill-office.wasted_wake_share"
BOOK_PERF: dict[str, str] = {
    KPI_WASTED: "count of no-action wakes in window (book); target 0",
    KPI_SHARE: "percent of wakes that were no-action in window (book); target 0",
}

_lock = threading.Lock()
# desk -> {trigger, acted, stamped}
_leases: dict[str, dict[str, Any]] = {}
# desk -> {wakes, wasted, triggers: dict[str,int]}
_desk: dict[str, dict[str, Any]] = {}
# office totals
_office: dict[str, Any] = {"wakes": 0, "wasted": 0, "triggers": {}}


def _who(desk: str) -> str:
    return str(desk or "").strip()


def _empty_triggers() -> dict[str, int]:
    return {t: 0 for t in TRIGGERS}


def classify_trigger(
    *,
    frame: dict[str, Any] | None = None,
    reason: str = "addressed",
    opened: bool = False,
    ring: str = "",
    trailing: str = "",
) -> str:
    """Map a wake's frame/reason to one of the five trigger tags."""
    del ring, trailing  # reserved for later callers; tag from frame/reason/opened
    frame = frame or {}
    kind = str(frame.get("kind") or "").strip().lower()
    typ = str(frame.get("type") or "").strip().lower()
    reason_s = str(reason or "").strip().lower()
    if typ in ("version", "older", "client-older", "version_notice") or kind in (
        "version",
        "older",
    ):
        return "version_notice"
    if typ == "hold" or (kind == "hint" and typ == "hold"):
        return "hold_release"
    if reason_s == "room" or typ in ("room", "fyi", "broadcast"):
        return "room_or_fyi_mail"
    if opened or bool(frame.get("handled")) or bool(frame.get("opened")):
        return "rering_handled"
    return "other"


def mark_lease(desk: str, *, trigger: str = "other") -> None:
    """Start (or reset) the desk's wake-lease tracker when a wake POST goes out."""
    who = _who(desk)
    if not who:
        return
    tag = trigger if trigger in TRIGGERS else "other"
    with _lock:
        _leases[who] = {"trigger": tag, "acted": False, "stamped": False}


def clear_lease(desk: str) -> None:
    """Drop the lease tracker with no stamp (Admin reset / gate_clear)."""
    who = _who(desk)
    if not who:
        return
    with _lock:
        _leases.pop(who, None)


def note_rpc(desk: str | None, command: str, *, ok: bool) -> None:
    """Mark the live lease as acted when an action command succeeds."""
    if not ok:
        return
    who = _who(desk or "")
    if not who:
        return
    v = (command or "").strip().lower()
    if not v or v in _SKIP:
        return
    if v not in ACTION_COMMANDS:
        return
    with _lock:
        row = _leases.get(who)
        if not row or row.get("stamped"):
            return
        row["acted"] = True


def _bump(store: dict[str, Any], *, wasted: bool, trigger: str) -> None:
    store["wakes"] = int(store.get("wakes") or 0) + 1
    trig = store.setdefault("triggers", _empty_triggers())
    if not isinstance(trig, dict):
        trig = _empty_triggers()
        store["triggers"] = trig
    if wasted:
        store["wasted"] = int(store.get("wasted") or 0) + 1
        trig[trigger] = int(trig.get(trigger) or 0) + 1


def finish_lease(desk: str) -> dict[str, Any] | None:
    """End the lease on wake-done. When wasted, emit op=wake.wasted and bump counts."""
    who = _who(desk)
    if not who:
        return None
    stamp: dict[str, Any] | None = None
    with _lock:
        row = _leases.pop(who, None)
        if not row or row.get("stamped"):
            return None
        row["stamped"] = True
        trigger = str(row.get("trigger") or "other")
        if trigger not in TRIGGERS:
            trigger = "other"
        wasted = not bool(row.get("acted"))
        desk_row = _desk.setdefault(who, {"wakes": 0, "wasted": 0, "triggers": _empty_triggers()})
        _bump(desk_row, wasted=wasted, trigger=trigger)
        _bump(_office, wasted=wasted, trigger=trigger)
        stamp = {
            "wasted": wasted,
            "trigger": trigger,
            "desk": who,
            "wakes": int(desk_row["wakes"]),
            "wasted_n": int(desk_row["wasted"]),
        }
    if stamp is None:
        return None
    try:
        from agent_coord.server.push import perf_log

        # Every finished lease logs once so share = wasted / all wakes (card 1002 Fail).
        wasted_i = 1 if stamp["wasted"] else 0
        perf_log(
            "wake.done",
            0.0,
            trigger=stamp["trigger"],
            desk=stamp["desk"],
            wasted=wasted_i,
            wakes=1,
        )
        if stamp["wasted"]:
            perf_log(
                "wake.wasted",
                0.0,
                trigger=stamp["trigger"],
                desk=stamp["desk"],
                wasted=1,
                wakes=1,
            )
    except Exception:
        pass
    return {
        "wasted": stamp["wasted"],
        "trigger": stamp["trigger"],
        "wakes": stamp["wakes"],
        "wasted_n": stamp["wasted_n"],
    }


def desk_snapshot(desk: str) -> dict[str, Any]:
    who = _who(desk)
    with _lock:
        row = dict(_desk.get(who) or {"wakes": 0, "wasted": 0, "triggers": _empty_triggers()})
    wakes = int(row.get("wakes") or 0)
    wasted = int(row.get("wasted") or 0)
    trig = dict(row.get("triggers") or _empty_triggers())
    return {
        "wakes": wakes,
        "wasted": wasted,
        "share": (float(wasted) / float(wakes)) if wakes else 0.0,
        "triggers": trig,
    }


def office_snapshot() -> dict[str, Any]:
    with _lock:
        row = {
            "wakes": int(_office.get("wakes") or 0),
            "wasted": int(_office.get("wasted") or 0),
            "triggers": dict(_office.get("triggers") or _empty_triggers()),
        }
    wakes = row["wakes"]
    wasted = row["wasted"]
    row["share"] = (float(wasted) / float(wakes)) if wakes else 0.0
    return row


def score_view(desk: str | None = None) -> dict[str, Any]:
    """Shape for mill score: count, share, trigger breakdown."""
    snap = desk_snapshot(desk) if desk else office_snapshot()
    return {
        "wasted": snap["wasted"],
        "wakes": snap["wakes"],
        "share": snap["share"],
        "triggers": snap["triggers"],
        "unit": "wakes",
    }


def reset_for_tests() -> None:
    with _lock:
        _leases.clear()
        _desk.clear()
        _office.clear()
        _office.update({"wakes": 0, "wasted": 0, "triggers": _empty_triggers()})
