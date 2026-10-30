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
