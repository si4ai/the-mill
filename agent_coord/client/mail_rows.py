"""Short rows and paging for inbox, mail-thread --room and the note reply (#295).

Same design as todo_rows: short rows by default, at most MAIL_PAGE letters a
reply, a page block that says where you are, --page N for page N, and --full
for today's reply byte-for-byte (every letter, every field, no paging).

inbox: the wall's order. mail-thread --room: page 1 is the newest letters
(oldest first within the page); --page 2 is the letters before them.
A short letter row is id, created, from (desk), parent_id, tree (only when the
list is not grouped by tree) and the body's first BODY_PREVIEW characters on
one line, with body_trunc true when the body was cut. `mill mail-thread <id>`
reads one letter whole.
The note reply drops the card's whole detail for detail_chars and the last
detail line; --full prints the detail as before.
"""
from __future__ import annotations

from typing import Any

from agent_coord.helpers.errors import CoordError

MAIL_PAGE = 50
BODY_PREVIEW = 100
FULL_HINT = "short rows; --full prints every field of every letter"


def _page(args: Any) -> int:
    return int(getattr(args, "page", 0) or 0)


def _refuse_page(command: str, why: str, args: Any) -> bool:
    if _page(args):
        raise CoordError(f"{command} --page: {why}; drop --page")
    return False


def inbox_applies(args: Any) -> bool:
    """True when this call is an inbox list printed in short rows."""
    if str(getattr(args, "cmd", "") or "") != "inbox" or bool(getattr(args, "full", False)):
        return False
    if bool(getattr(args, "raw", False)):
        return _refuse_page("inbox", "--raw prints every letter", args)
    return True


def room_applies(args: Any) -> bool:
    """True when this call is a whole-room read (--room, no --after) in short rows."""
    if str(getattr(args, "cmd", "") or "") != "mail-thread":
        return False
    if bool(getattr(args, "full", False)):
        return False
    if str(getattr(args, "scope", "") or "") != "room":
        return _refuse_page("mail-thread", "only a --room read pages", args)
    if int(getattr(args, "after", 0) or 0):
        return _refuse_page("mail-thread", "--after already reads only the newer letters", args)
    if bool(getattr(args, "raw", False)):
        return _refuse_page("mail-thread", "--raw prints every letter", args)
    return True


def _block(command: str, n: int, total: int) -> tuple[int, int, dict]:
    of = max(1, -(-total // MAIL_PAGE))
    if n > of:
        raise CoordError(f"{command} --page {n}: {total} letter(s) make {of} page(s)")
    block: dict[str, Any] = {"n": n, "of": of, "size": MAIL_PAGE, "letters": total}
    return n, of, block


def cut(rows: list, page: int, command: str = "inbox") -> tuple[list, dict]:
    """inbox: the letters on page (1-based; 0 = first), wall order, and the page block."""
    n, of, block = _block(command, max(1, page), len(rows))
    if n < of:
        block["next"] = f"--page {n + 1}"
    block["full"] = FULL_HINT
    return rows[(n - 1) * MAIL_PAGE : n * MAIL_PAGE], block


def cut_newest(rows: list, page: int, command: str = "mail-thread") -> tuple[list, dict]:
    """A room: page 1 is the newest MAIL_PAGE letters, kept oldest first."""
    n, of, block = _block(command, max(1, page), len(rows))
    hi = len(rows) - (n - 1) * MAIL_PAGE
    lo = max(0, hi - MAIL_PAGE)
    block["order"] = "page 1 is the newest letters; a higher page is older"
    if n < of:
        block["next"] = f"--page {n + 1}"
    block["full"] = FULL_HINT
    return rows[lo:hi], block


def _preview(body: Any) -> tuple[str, bool]:
    text = " ".join(str(body or "").split())
    if len(text) <= BODY_PREVIEW and text == str(body or ""):
        return text, False
    return text[:BODY_PREVIEW], True


def short_letter(r: Any, keep_tree: bool = True) -> Any:
    if not isinstance(r, dict):
        return r
    out: dict[str, Any] = {"id": r.get("id")}
    if "created" in r:
        out["created"] = str(r.get("created") or "")[:19]
    sender = r.get("sender")
    out["from"] = sender.get("deskId") if isinstance(sender, dict) else sender
    if r.get("parent_id") is not None:
        out["parent_id"] = r.get("parent_id")
    if keep_tree and r.get("tree"):
        out["tree"] = r.get("tree")
    body, trunc = _preview(r.get("body"))
    out["body"] = body
    if trunc or r.get("body_trunc"):
        out["body_trunc"] = True
    return out


def short_inbox(result: Any) -> Any:
    """Short rows in a flat or grouped inbox; groups and order stay."""
    if isinstance(result, list):
        return [short_letter(r) for r in result]
    if isinstance(result, dict) and isinstance(result.get("groups"), list):
        by_tree = str(result.get("group_by") or "") == "tree"
        out = dict(result)
        out["groups"] = [
            dict(g, items=[short_letter(r, keep_tree=not by_tree) for r in g.get("items") or []])
            for g in result["groups"]
        ]
        return out
    return result


def short_room(result: dict) -> dict:
    """A room reply's chain in short rows; tree is on the envelope once."""
    out = dict(result)
    out["chain"] = [short_letter(r, keep_tree=False) for r in result.get("chain") or []]
    return out


