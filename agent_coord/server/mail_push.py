"""MAIL pushes. No watcher. Recipients hear the mail. A receipt returns to the sender."""

from __future__ import annotations

from agent_coord.server.records import mail as rec_mail


def _nm(value: object) -> str:
    """Stored desk name."""
    return str(value or "").strip()

# A typical letter arrives whole; a letter is at most 4096 characters, so a
# connect sync of many missed letters stays bounded (#584).
BODY_CAP = 1024
# Addressed live wakes carry the whole letter (card 902); letters cap at 4096.
LETTER_CAP = 4096


def cut_marker(mail_id: int, remaining: int) -> str:
    """Visible ASCII tail when a body is cut (card 902). Counts inside the cap."""
    return f"... [cut: {int(remaining)} more chars, mill mail-thread {int(mail_id)}]"


def clip_body(raw: object, mail_id: int, cap: int) -> dict:
    """The body, whole when it fits. A cut ends with a visible tail inside cap."""
    text = str(raw or "")
    limit = int(cap)
    if limit < 1:
        limit = BODY_CAP
    if len(text) <= limit:
        return {"body": text}
    # Tail counts inside the cap. Remaining digit width can shift length; settle.
    rem = len(text)
    prefix = 0
    tail = cut_marker(mail_id, rem)
    for _ in range(12):
        tail = cut_marker(mail_id, rem)
        prefix = max(0, limit - len(tail))
        rem2 = len(text) - prefix
        if rem2 == rem and prefix + len(tail) <= limit:
            break
        rem = rem2
    else:
        tail = cut_marker(mail_id, rem)
        prefix = max(0, limit - len(tail))
        rem = len(text) - prefix
        tail = cut_marker(mail_id, rem)
        prefix = max(0, limit - len(tail))
        rem = len(text) - prefix
        tail = cut_marker(mail_id, rem)
        prefix = max(0, limit - len(tail))
    return {
        "body": text[:prefix] + tail,
        "body_trunc": True,
        "body_chars": len(text),
        "read": f"mill mail-thread {int(mail_id)}",
    }


def _body(raw: object, mail_id: int, *, reason: str | None = None) -> dict:
    """Preview cap for room/replay; whole letter for addressed (card 902)."""
    cap = LETTER_CAP if (reason or "").strip().lower() == "addressed" else BODY_CAP
    return clip_body(raw, mail_id, cap)


def compact_mail(
    letter: dict,
    dest_rows: list[dict],
    for_desk: str,
    *,
    reason: str | None = None,
) -> dict:
    """Short mail for one mail_to desk."""
    want = _nm(for_desk)
    tos: list[str] = []
    mine: dict = {}
    for row in dest_rows or []:
        desk = _nm(row.get("desk"))
        if desk:
            tos.append(desk)
        if desk == want:
            mine = row
    mid = int(letter.get("id") or 0)
    return {
        "kind": "mail",
        "id": mid,
        "created": letter.get("created"),
        "from": _nm(letter.get("desk") or letter.get("sender")),
        "sender": _nm(letter.get("desk") or letter.get("sender")),
        "mail_tos": tos,
        "to": list(tos),
        "roster_id": letter.get("sender_roster"),
        "opened": mine.get("opened"),
        "receipt": int(mine.get("receipt") or 0),
        **_body(letter.get("body"), mid, reason=reason),
    }


def compact_receipt(row: dict) -> dict:
    """Open of a receipt-flagged mail, for the sender."""
    mid = int(row.get("id") or row.get("mail_id") or 0)
    return {
        "kind": "receipt",
        "id": mid,
        "created": row.get("created"),
        **_body(row.get("body"), mid),
        "mail_to": _nm(row.get("desk") or row.get("opener")),
        "opened": row.get("opened") or row.get("updated"),
    }


def _room_name(cn, mail_id: int) -> str | None:
    """The letter's room name, or None off a room or on a minted thread tree (#627)."""
    from agent_coord.server.records.tree import is_hidden_tree

    try:
        name = str((rec_mail.tree_crumbs(cn, int(mail_id)) or {}).get("tree") or "")
    except Exception:
        return None
    return name if name and not is_hidden_tree(name) else None


def push_mail(cn, mail_id: int, *, room_only: set[str] | None = None) -> None:
    """Async MAIL item to every mail_to desk. Does not plant a watcher.

    room_only (#627): dests that get this letter as room members (reply-all);
    their wake says reason room. Every other dest was named: addressed.
    """
    from agent_coord.server.push import emit

    letter = rec_mail.letter_row(cn, int(mail_id))
    if not letter:
        return
    dests = rec_mail.to_list(cn, int(mail_id))
    room = _room_name(cn, int(mail_id))
    members = set(room_only or ())
    for row in dests:
        desk = str(row.get("desk") or "")
        if not desk:
            continue
        reason = "room" if desk.strip() in members else "addressed"
        emit(
            cn,
            desk,
            "mail",
            compact_mail(letter, dests, desk, reason=reason),
            reason=reason,
            room=room,
        )


def push_receipt(cn, row: dict) -> None:
    """Async receipt to the sender when this open is the first and receipt is set."""
    from agent_coord.server.push import emit

    if int(row.get("push_receipt") or 0) != 1:
        return
    sender = str(row.get("sender") or "")
    if not sender:
        return
    emit(cn, sender, "receipt", compact_receipt(row))
