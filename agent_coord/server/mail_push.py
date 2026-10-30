"""MAIL pushes. No watcher. Recipients hear the mail. A receipt returns to the sender."""

from __future__ import annotations

from agent_coord.server.records import mail as rec_mail


def _nm(value: object) -> str:
    """Stored desk name."""
    return str(value or "").strip()

# A typical letter arrives whole; a letter is at most 4096 characters, so a
# connect sync of many missed letters stays bounded (#584).
BODY_CAP = 1024


def _body(raw: object, mail_id: int) -> dict:
    """The body, whole when it fits. A cut says so, like inbox rows (body_trunc),
    with the full length and the command that reads the letter whole (#584)."""
    text = str(raw or "")
    if len(text) <= BODY_CAP:
        return {"body": text}
    return {
        "body": text[:BODY_CAP],
        "body_trunc": True,
        "body_chars": len(text),
        "read": f"mill mail-thread {int(mail_id)}",
    }


def compact_mail(letter: dict, dest_rows: list[dict], for_desk: str) -> dict:
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
        **_body(letter.get("body"), mid),
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
        emit(cn, desk, "mail", compact_mail(letter, dests, desk), reason=reason, room=room)


def push_receipt(cn, row: dict) -> None:
    """Async receipt to the sender when this open is the first and receipt is set."""
    from agent_coord.server.push import emit

    if int(row.get("push_receipt") or 0) != 1:
        return
    sender = str(row.get("sender") or "")
    if not sender:
        return
    emit(cn, sender, "receipt", compact_receipt(row))
