"""Desk focus: the desk's stored focus list ranks that desk's cards (#374).

A desk name cannot also be a label, so `mill label todo <id> <desk>` is refused.
A focus list stored before 0.8.16 is still read. Rank new cards under another label.
Two readers, both on existing read paths.

Focus skips cards that are done, parked, or held by another desk. Rank is
ord ascending (0 pinned first), ties by card id. Client only: the wall
serves the same reads it did in 0.7.8, so an older client sees nothing new.

- `todo --mine` lists the focus cards on the board first, in label rank
  order (one `trail --label <desk>` read, only when a board card wears it),
  then the desk's claimed cards.
- `mill connect`, once seated, prints one `{"kind": "focus"}` line with the
  top FOCUS_TOP focus cards from the same board `todo --mine` reads (the
  desk's rosters), so the desk knows what to work on next without asking;
  nothing when there are none, and one stderr line naming the cause when a
  read fails (#536).
"""
from __future__ import annotations

from typing import Any, Callable

FOCUS_TOP = 5
UNPLACED = 65535
# What a desk needs to act on a card: which one, where (claim takes roster and need),
# its state, who has it, and its rank on the label.
CARD_KEYS = ("id", "project_id", "need_id", "status", "volunteer")
REST = "mill todo --mine lists every focus card, then your claimed ones"


def set_focus_hint(_desk: str) -> str:
    return "a desk name cannot be a label; rank cards under another label"


def _result(reply: Any) -> Any:
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        return None
    return reply.get("result")


class FocusError(Exception):
    """A focus read failed; the text names the read and its cause."""


def _read(call: Callable[[dict], Any], body: dict) -> Any:
    """One read for the connect focus line; FocusError names the command and cause."""
    command = str(body.get("verb") or "")
    try:
        reply = call(body)
    except Exception as e:
        raise FocusError(f"{command} read failed: {e or type(e).__name__}") from e
    if not isinstance(reply, dict) or reply.get("ok") is not True:
        err = reply.get("error") if isinstance(reply, dict) else None
        raise FocusError(f"{command} read refused: {err or 'no answer'}")
    return reply.get("result")


def _rank_rows(res: Any) -> list[tuple[int, int]]:
    rows = res.get("rows") if isinstance(res, dict) else None
    out: list[tuple[int, int]] = []
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and r.get("type") == "todo":
            try:
                out.append((int(r["id"]), int(r.get("ord") or 0)))
            except (KeyError, TypeError, ValueError):
                continue
    out.sort(key=lambda t: (t[1], t[0]))
    return out


def label_rank(call: Callable[[dict], Any], desk: str) -> list[tuple[int, int]]:
    """(todo id, ord) wearing label desk, ord ascending (0 pinned first), ties by card id.

    [] on any failure: todo --mine then lists focus cards by card id.
    """
    try:
        return _rank_rows(_read(call, {"verb": "trail", "label": desk}))
    except FocusError:
        return []


def actionable(card: dict, desk: str, status_asked: str = "") -> bool:
    """A focus card the desk can work on: not done, not parked (unless --status
    parked was asked), and not held by another desk (volunteer empty or desk)."""
    st = str(card.get("status") or "")
    if st == "done" and status_asked != "done":
        return False
    if st == "parked" and status_asked != "parked":
        return False
    return str(card.get("volunteer") or "") in ("", desk)


def order_mine(
    cards: list, desk: str, rank: list[tuple[int, int]], status_asked: str = ""
) -> tuple[list, int, int]:
    """Focus cards (label desk, actionable) by rank, then cards desk volunteered for.

    Rank is ord ascending, ties by card id; a focus card the label read did not
    return counts as ord UNPLACED. A card is listed once: a focus card the desk
    already holds sits in the focus part. Only cards already on the board are
    listed, so the board's status and done filters hold.
    Returns (cards, focus n, claimed n).
    """
    ords = {cid: o for cid, o in rank}
    focus: list[tuple[int, int, dict]] = []
    claimed: list[dict] = []
    for r in cards:
        if not isinstance(r, dict):
            continue
        labels = r.get("labels") if isinstance(r.get("labels"), list) else []
        mine = str(r.get("volunteer") or "") == desk
        if desk in labels and actionable(r, desk, status_asked):
            o = ords.get(r.get("id"), UNPLACED)
            focus.append((o, int(r.get("id") or 0), dict(r, focus=o)))
        elif mine:
            claimed.append(r)
    focus.sort(key=lambda t: (t[0], t[1]))
    return [c for _, _, c in focus] + claimed, len(focus), len(claimed)


def wears(cards: list, desk: str) -> bool:
    return any(isinstance(r, dict) and desk in (r.get("labels") or []) for r in cards)


TODO_ROSTERS_PER_READ = 200  # the wall's TODO_ROSTERS_MAX


def connect_block(call: Callable[[dict], Any], desk: str) -> dict | None:
    """The focus line connect prints once seated, or None when there is nothing to show.

    The same reads as `todo --mine` (#536): the desk's rosters (member), their
    board in one read per 200 rosters (done hidden), then the label rank only
    when a card wears the label. The top FOCUS_TOP focus cards in rank order.
    A card is read on its own roster, never by a bare id: the wall defaults an
    empty project to the-mill. A failed read raises FocusError naming it.
    """
    res = _read(call, {"verb": "member"})
    rosters: list[str] = []
    for r in res if isinstance(res, list) else []:
        slot = str(r.get("slot") or "") if isinstance(r, dict) else ""
        if slot and slot not in rosters:
            rosters.append(slot)
    cards: list = []
    for at in range(0, len(rosters), TODO_ROSTERS_PER_READ):
        part = rosters[at : at + TODO_ROSTERS_PER_READ]
        got = _read(call, {"verb": "todo", "project": part[0], "rosters": part})
        if not isinstance(got, dict) or not isinstance(got.get("cards"), list):
            raise FocusError("todo read: the wall did not answer {cards}")
        cards.extend(got["cards"])
    if not wears(cards, desk):
        return None
    rank = _rank_rows(_read(call, {"verb": "trail", "label": desk}))
    listed, n_focus, _ = order_mine(cards, desk, rank)
    top = [
        dict({k: c.get(k, "") for k in CARD_KEYS}, rank=c.get("focus", UNPLACED))
        for c in listed[: min(n_focus, FOCUS_TOP)]
    ]
    if not top:
        return None
    return {"kind": "focus", "label": desk, "cards": top, "rest": REST}
