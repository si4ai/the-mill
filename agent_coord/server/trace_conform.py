# -*- coding: utf-8 -*-
"""Card 1311: replay recorded protocol events against the model's allowed steps.

SPIN shows a model is sound; this checks that the running code stayed inside it.
Input is the transition log (one dict per row, in id order). No LLM, no clock:
the same rows give the same report.

Wake (slice 1) has two machines on one wake row:

  queue   rows with no lease join_key: none -> queued -> sent|missed|error -> taken
          (edges Q1-Q11, W5c in transition_enums, mapped from verify/spin/wake.pml)
  lease   rows with join_key ``lease:TOKEN``: ring -> lease_live, then one end
          (done W9, expired W12, cleared W12b). A row leaving ring or lease_live
          with no lease key (written before card 1140) is checked as an edge only.

Todo (card status) has one machine per card, rows joined by ``card:ID``:
none -> parked|open -> claimed -> shipped -> done, with the back moves (T7, T10, T11),
retire (T12, from any state) and reclaim (T13, back to the status it had). Status moves
T1-T11 follow todo.pml's table; a retired card takes no status move until reclaimed
(todo.pml DELETED_GUARD).

A step is checked three ways:
  unmodelled  its (from, to, reason) is no model edge
  forbidden   a model edge taken from the wrong state, or a step a wake.pml
              property rules out: a lease ended twice (no_dup_done), ended by
              another desk or on another wake (no_stale_done), rung twice
  silent      a transition the model needs that left no event: history that
              starts mid-life, a lease end with no ring, a lease still open past
              the cap, a wake row whose stored state is not where its events end
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Iterable

LEASE_PREFIX = "lease:"
LEASE_ENDS = ("done", "expired", "cleared")
# A step out of these states is a lease step even when the row has no lease key
# (rows written before card 1140 keyed leases): it is checked as an edge only.
LEASE_FROM = ("ring", "lease_live")
# wake_lease.CAP_LEASES (4) times the default lease_s (900).
LEASE_CAP_S = 3600.0

# Model step id for each wake edge (transition_enums.ALLOWED_TRANSITIONS, wake rows).
# A test keeps this table equal to the edge set, so a new edge must get its id here.
WAKE_STEPS: dict[tuple[str, str, str], str] = {
    ("none", "queued", "wake_queue"): "Q1",
    ("queued", "sent", "wake_sent"): "Q2",
    ("queued", "missed", "wake_owed"): "Q3",
    ("queued", "error", "wake_fail"): "Q4",
    ("sent", "taken", "wake_deliver"): "Q5",
    ("missed", "taken", "wake_deliver"): "Q6",
    ("error", "taken", "wake_deliver"): "Q7",
    ("queued", "taken", "wake_deliver"): "Q8",
    ("sent", "missed", "wake_owed"): "Q9",
    ("missed", "sent", "wake_sent"): "Q10",
    ("missed", "error", "wake_fail"): "Q11",
    ("idle", "push_pending", "wake_queue"): "W1",
    ("none", "unread_owed", "wake_owed"): "W2",
    ("push_pending", "lease_live", "wake_sent"): "W3a",
    ("unread_owed", "lease_live", "wake_sent"): "W3b",
    ("ring", "lease_live", "wake_sent"): "W3c",
    ("push_pending", "lease_live", "wake_fail"): "W4a",
    ("unread_owed", "lease_live", "wake_fail"): "W4b",
    ("fail", "retry_armed", "wake_retry"): "W5",
    ("error", "retry_armed", "wake_retry"): "W5c",
    ("retry_armed", "drained", "wake_drain"): "W6a",
    ("retry_armed", "idle", "wake_drain"): "W6b",
    ("lease_live", "trail", "wake_trail"): "W7",
    ("left", "ring", "wake_ring"): "W8",
    ("lease_live", "done", "wake_done"): "W9",
    ("lease_live", "idle", "wake_stale"): "W10",
    ("lease_live", "idle", "wake_sitting"): "W11",
    ("lease_live", "expired", "wake_expire"): "W12",
    ("lease_live", "cleared", "clear"): "W12b",
    ("any", "coalesced", "wake_coalesce"): "W13",
    ("any", "skipped", "wake_skip"): "W14",
    ("any", "sitting", "wake_sit"): "W15",
    ("sitting", "left", "wake_leave"): "W16",
    ("push_pending", "drained", "wake_deliver"): "W17",
    ("unread_owed", "lost_unread", "wake_lost"): "W18",
}

# Model step id for each todo edge (transition_enums.ALLOWED_TRANSITIONS, todo rows; todo.pml T1-T16).
TODO_STEPS: dict[tuple[str, str, str], str] = {
    ("none", "open", "create"): "T1",
    ("none", "parked", "create_parked"): "T2",
    ("parked", "open", "unpark"): "T3",
    ("open", "claimed", "claim"): "T4",
    ("open", "claimed", "assign"): "T5",
    ("claimed", "claimed", "take_over"): "T6",
    ("claimed", "open", "unclaim"): "T7",
    ("claimed", "shipped", "pass_ship"): "T8",
    ("shipped", "done", "pass_done"): "T9",
    ("done", "shipped", "pass_back"): "T10",
    ("shipped", "claimed", "pass_back"): "T11a",
    ("shipped", "open", "pass_back"): "T11b",
    ("any", "retired", "retire"): "T12",
    ("retired", "prior", "reclaim"): "T13",
    ("any", "same", "note"): "T14",
    ("live", "deleted", "delete_probe"): "T15",
    ("any", "same", "rename"): "T16",
}
# Statuses a card row holds; any other from or to state on a todo row is a model token.
TODO_STATUSES = ("parked", "open", "claimed", "shipped", "done")

PROTOCOLS = ("wake", "todo")


def model_edges(activity_type: str) -> frozenset[tuple[str, str, str]]:
    """(from, to, reason) edges the code's model table allows for one activity type."""
    from agent_coord.server.transition_enums import ALLOWED_TRANSITIONS

    return frozenset(
        (f.value, t.value, r.value) for a, f, t, r in ALLOWED_TRANSITIONS if a.value == activity_type
    )


def _at(value: Any) -> _dt.datetime | None:
    if isinstance(value, _dt.datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip().replace("T", " ").rstrip("Z")
    if not text:
        return None
    try:
        return _dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    """One transition row as the replay reads it (bad or missing fields are blank, not raised)."""
    meta = row.get("meta")
    if isinstance(meta, str) and meta:
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    try:
        n = int(row.get("n") or 1)
    except (TypeError, ValueError):
        n = 1
    return {
        "id": int(row.get("id") or 0),
        "at": str(row.get("at") or ""),
        "activity_type": str(row.get("activity_type") or ""),
        "activity_id": int(row.get("activity_id") or 0),
        "from_state": str(row.get("from_state") or "none"),
        "to_state": str(row.get("to_state") or ""),
        "reason": str(row.get("reason") or ""),
        "desk_id": int(row.get("desk_id") or 0),
        "join_key": row.get("join_key") or None,
        "meta": meta if isinstance(meta, dict) else None,
        "n": n if n > 0 else 1,
    }


def _state_after(ev: dict[str, Any]) -> str:
    # Card 1098 compress: odd n is at to_state, even n is back at from_state.
    return ev["to_state"] if ev["n"] % 2 == 1 else ev["from_state"]


class _Report:
    def __init__(self, protocol: str, edges: frozenset[tuple[str, str, str]], steps: dict) -> None:
        self.protocol = protocol
        self.edges = edges
        self.steps = steps
        self.forbidden: list[dict[str, Any]] = []
        self.silent: list[dict[str, Any]] = []
        self.unmodelled: list[dict[str, Any]] = []
        self.seen: set[tuple[str, str, str]] = set()
        self.events = 0

    def edge_ok(self, ev: dict[str, Any], obj: str) -> bool:
        edge = (ev["from_state"], ev["to_state"], ev["reason"])
        self.seen.add(edge)
        if edge in self.edges:
            return True
        self.unmodelled.append({"event_id": ev["id"], "object": obj, "edge": list(edge)})
        return False

    def step(self, ev: dict[str, Any]) -> str:
        return self.steps.get((ev["from_state"], ev["to_state"], ev["reason"]), "")

    def as_dict(self) -> dict[str, Any]:
        quiet = sorted(self.steps.get(e, "") or "|".join(e) for e in self.edges - self.seen)
        return {
            "protocol": self.protocol,
            "events": self.events,
            "counts": {
                "forbidden": len(self.forbidden),
                "silent": len(self.silent),
                "unmodelled": len(self.unmodelled),
            },
            "forbidden": self.forbidden,
            "silent": self.silent,
            "unmodelled": self.unmodelled,
            "quiet_steps": quiet,
        }


def _replay_queue(rep: _Report, obj: str, evs: list[dict[str, Any]], stored: str | None) -> None:
    state = "none"
    path: list[int] = []
    for i, ev in enumerate(evs):
        path.append(ev["id"])
        modelled = rep.edge_ok(ev, obj)
        frm = ev["from_state"]
        if i == 0 and frm != "none" and frm != "any":
            rep.silent.append(
                {"object": obj, "rule": "no_start_event", "event_id": ev["id"],
                 "detail": f"first event leaves {frm}; nothing recorded entering it", "path": list(path)}
            )
        elif modelled and frm != "any" and frm != state:
            rep.forbidden.append(
                {"object": obj, "rule": "from_state", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": f"{rep.step(ev) or 'step'} leaves {frm} but the wake is at {state}",
                 "path": list(path)}
            )
        state = _state_after(ev)
    if stored is not None and evs and stored != state:
        rep.silent.append(
            {"object": obj, "rule": "state_ahead", "event_id": evs[-1]["id"],
             "detail": f"stored state {stored}, events end at {state}", "path": list(path)}
        )


def _replay_lease(
    rep: _Report, obj: str, evs: list[dict[str, Any]], *, cap_s: float, end_at: _dt.datetime | None
) -> None:
    ring: dict[str, Any] | None = None
    end: dict[str, Any] | None = None
    path: list[int] = []
    for ev in evs:
        path.append(ev["id"])
        rep.edge_ok(ev, obj)
        to = ev["to_state"]
        if to == "lease_live":
            if ring is not None or end is not None:
                rep.forbidden.append(
                    {"object": obj, "rule": "lease_rerung", "event_id": ev["id"], "step": rep.step(ev),
                     "detail": "a second ring on a lease that already started", "path": list(path)}
                )
            else:
                ring = ev
            continue
        if to not in LEASE_ENDS:
            continue
        if end is not None:
            rep.forbidden.append(
                {"object": obj, "rule": "no_dup_done", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": f"lease ended {end['to_state']} at event {end['id']}, then {to} again",
                 "path": list(path)}
            )
            continue
        end = ev
        if ring is None:
            rep.silent.append(
                {"object": obj, "rule": "lease_no_ring", "event_id": ev["id"],
                 "detail": f"lease ended {to} with no ring recorded", "path": list(path)}
            )
            continue
        if ev["desk_id"] != ring["desk_id"] or ev["activity_id"] != ring["activity_id"]:
            rep.forbidden.append(
                {"object": obj, "rule": "no_stale_done", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": (f"lease rung for desk {ring['desk_id']} on wake {ring['activity_id']}"
                            f" ended by desk {ev['desk_id']} on wake {ev['activity_id']}"),
                 "path": list(path)}
            )
    if ring is not None and end is None and end_at is not None:
        rung = _at(ring["at"])
        if rung is not None and (end_at - rung).total_seconds() > cap_s:
            rep.silent.append(
                {"object": obj, "rule": "lease_open_past_cap", "event_id": ring["id"],
                 "detail": f"rung at {ring['at']}, no end within {int(cap_s)} s", "path": list(path)}
            )


def replay_wake(
    rows: Iterable[dict[str, Any]],
    *,
    stored_states: dict[int, str] | None = None,
    lease_cap_s: float = LEASE_CAP_S,
    window_end: Any = None,
) -> dict[str, Any]:
    """Replay wake transition rows. stored_states: wake id -> wake.state (optional).
    window_end: the read's end time (UTC); a lease still open then past the cap is silent."""
    rep = _Report("wake", model_edges("wake"), WAKE_STEPS)
    queues: dict[int, list[dict[str, Any]]] = {}
    leases: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        ev = normalize(raw)
        if ev["activity_type"] != "wake":
            continue
        rep.events += 1
        key = ev["join_key"]
        if isinstance(key, str) and key.startswith(LEASE_PREFIX):
            leases.setdefault(key, []).append(ev)
        elif ev["from_state"] in LEASE_FROM:
            rep.edge_ok(ev, f"wake:{ev['activity_id']}")
        else:
            queues.setdefault(ev["activity_id"], []).append(ev)
    stored = stored_states or {}
    for wid in sorted(queues):
        _replay_queue(rep, f"wake:{wid}", sorted(queues[wid], key=lambda e: e["id"]), stored.get(wid))
    end_at = _at(window_end)
    # A lease is named by its wake and first event id, never by its token.
    for evs in sorted((sorted(v, key=lambda e: e["id"]) for v in leases.values()), key=lambda v: v[0]["id"]):
        obj = f"wake:{evs[0]['activity_id']}/lease@{evs[0]['id']}"
        _replay_lease(rep, obj, evs, cap_s=lease_cap_s, end_at=end_at)
    for bucket in (rep.forbidden, rep.silent, rep.unmodelled):
        bucket.sort(key=lambda f: (f["event_id"], f.get("rule", "")))
    return rep.as_dict()


def _replay_todo_card(rep: _Report, obj: str, evs: list[dict[str, Any]], stored: str | None) -> None:
    status = "none"
    retired = False  # a retired card keeps its status; no move may change it until reclaim
    moved = False  # a status move was seen: before it the card's status is unknown
    retire_seen = False
    path: list[int] = []
    for i, ev in enumerate(evs):
        path.append(ev["id"])
        modelled = rep.edge_ok(ev, obj)
        frm, to, why = ev["from_state"], ev["to_state"], ev["reason"]
        if not modelled:
            continue
        if why == "reclaim":
            if not retired and not moved and not retire_seen:
                # the retire row is not in the log (card retired before retire wrote rows)
                rep.silent.append(
                    {"object": obj, "rule": "no_start_event", "event_id": ev["id"],
                     "detail": "first event reclaims a card; nothing recorded retiring it",
                     "path": list(path)}
                )
                retire_seen = True
            elif not retired:
                rep.forbidden.append(
                    {"object": obj, "rule": "reclaim_not_retired", "event_id": ev["id"],
                     "step": rep.step(ev), "detail": f"reclaim of a card that is {status}, not retired",
                     "path": list(path)}
                )
            else:
                retired = False
            continue
        if why == "retire":
            if retired:
                rep.forbidden.append(
                    {"object": obj, "rule": "retired_twice", "event_id": ev["id"], "step": rep.step(ev),
                     "detail": "retire of a card that is already retired", "path": list(path)}
                )
            else:
                retired = True
                retire_seen = True
            continue
        if to in ("same", "deleted"):
            continue
        # a status move, T1-T11
        if retired:
            rep.forbidden.append(
                {"object": obj, "rule": "move_on_retired", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": f"{rep.step(ev) or 'step'} on a retired card (todo.pml refuses it until reclaim)",
                 "path": list(path)}
            )
            continue
        first_move, moved = not moved, True
        if first_move and frm != "none":
            rep.silent.append(
                {"object": obj, "rule": "no_start_event", "event_id": ev["id"],
                 "detail": f"first status move leaves {frm}; nothing recorded entering it",
                 "path": list(path)}
            )
            status = frm
        elif frm == "none" and status != "none":
            # todo.pml MIGRATED: a seed row written for a card that already had a life
            rep.silent.append(
                {"object": obj, "rule": "create_on_live_card", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": f"{rep.step(ev)} for a card that is already {status} (a seed row)",
                 "path": list(path)}
            )
        elif why == "pass_ship" and frm == "claimed" and status == "open":
            # todo.pml T8: a ship also leaves open-with-volunteer; the row cannot show the volunteer
            rep.silent.append(
                {"object": obj, "rule": "ship_from_open", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": "T8 row leaves claimed but the card is open (legal only with a volunteer)",
                 "path": list(path)}
            )
        elif frm != status:
            rep.forbidden.append(
                {"object": obj, "rule": "from_state", "event_id": ev["id"], "step": rep.step(ev),
                 "detail": f"{rep.step(ev) or 'step'} leaves {frm} but the card is {status}",
                 "path": list(path)}
            )
        status = to if ev["n"] % 2 == 1 else frm
    if stored is not None and (moved or retired):
        end = "retired" if retired else status
        if stored != end:
            rep.silent.append(
                {"object": obj, "rule": "state_ahead", "event_id": evs[-1]["id"],
                 "detail": f"stored state {stored}, events end at {end}", "path": list(path)}
            )


def replay_todo(
    rows: Iterable[dict[str, Any]],
    *,
    stored_states: dict[int, str] | None = None,
    **_unused: Any,
) -> dict[str, Any]:
    """Replay todo transition rows. stored_states: card id -> "retired" or todo.status (optional)."""
    rep = _Report("todo", model_edges("todo"), TODO_STEPS)
    cards: dict[int, list[dict[str, Any]]] = {}
    for raw in rows:
        ev = normalize(raw)
        if ev["activity_type"] != "todo":
            continue
        rep.events += 1
        cards.setdefault(ev["activity_id"], []).append(ev)
    stored = stored_states or {}
    for cid in sorted(cards):
        _replay_todo_card(rep, f"todo:{cid}", sorted(cards[cid], key=lambda e: (e["at"], e["id"])), stored.get(cid))
    for bucket in (rep.forbidden, rep.silent, rep.unmodelled):
        bucket.sort(key=lambda f: (f["event_id"], f.get("rule", "")))
    return rep.as_dict()


def replay(protocol: str, rows: Iterable[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    if protocol == "wake":
        return replay_wake(rows, **kw)
    if protocol == "todo":
        return replay_todo(rows, **kw)
    raise ValueError(f"unknown protocol {protocol!r}; known: {', '.join(PROTOCOLS)}")
