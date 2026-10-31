"""mill CLI language (0.7.x): `mill <action> <type> <name>` words -> wall RPC commands.

The wall keeps its RPC commands (roster, label, member-add, label-add, add, remove, ...).
This module maps the CLI words onto them, asks before create and destructive
actions, and makes rename/retire retype the name. --yes skips every prompt.
"""
from __future__ import annotations

import sys
from typing import Any, Callable

from agent_coord.helpers.errors import CoordError

GAP_ROOM = (
    "{command} room: not yet by name. To put a desk on a room: mill add mail:<root_id> DESK; "
    "to join one yourself, reply to any letter in it"
)


def _tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def confirm(question: str, *, yes: bool, ask: Callable[[str], str] | None = None) -> None:
    """y/N prompt. --yes skips it. No terminal and no --yes refuses plainly."""
    if yes:
        return
    if ask is None:
        if not _tty():
            raise CoordError(f"{question}: no terminal to answer; add --yes")
        ask = input
    ans = str(ask(f"{question} [y/N] ") or "").strip().lower()
    if ans not in ("y", "yes"):
        raise CoordError("cancelled")


def retype(name: str, what: str, *, yes: bool, ask: Callable[[str], str] | None = None) -> None:
    """Rename and retire: type the name again. --yes skips it."""
    if yes:
        return
    if ask is None:
        if not _tty():
            raise CoordError(f"{what}: no terminal to retype the name; add --yes")
        ask = input
    got = str(ask(f"{what}: type {name} again to confirm: ") or "").strip()
    if got != name:
        raise CoordError(f"{what}: names did not match; nothing changed")


def _type_id(raw: str, command: str) -> tuple[str, int | str]:
    from agent_coord.const import ACTIVITY_TYPES

    kind, _, num = str(raw or "").strip().partition(":")
    kind = kind.strip().lower()
    hint = (
        f"{command}: TARGET is type:id (for example todo:256, todo:cold-test/fix-login or mail:1866), type one of "
        + "|".join(sorted(ACTIVITY_TYPES))
    )
    if kind not in ACTIVITY_TYPES:
        raise CoordError(hint)
    try:
        return kind, card_ref(num, kind, command)
    except CoordError:
        raise CoordError(hint) from None


def _desks(raw: str) -> list[str]:
    return [d.strip() for d in str(raw or "").split(",") if d.strip()]


# #706: (type arg, id arg, ref body key) per tree command; a ROSTER/NEED id rides as the ref key.
_TREE_IDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "attach": (("type_a", "id_a", "ref_a"), ("type_b", "id_b", "ref_b")),
    "move": (("type", "id", "ref"), ("parent_type", "parent_id", "parent_ref")),
    "prune": (("type", "id", "ref"),),
    "detach": (("type", "id", "ref"),),
}


def card_ref(raw: str, typ: str, command: str) -> int | str:
    """An activity id (a number above 0), a todo as ROSTER/NEED (#274), or a hold by name (#327).

    Returns the int id, or the "roster/need" or hold name string for the server to resolve.
    """
    text = str(raw or "").strip()
    if text.isdigit() and int(text) > 0:
        return int(text)
    if typ == "todo" and "/" in text:
        roster, _, need = text.partition("/")
        roster, need = roster.strip(), need.strip()
        if (
            roster and need and len(roster) <= 64 and len(need) <= 64
            and not any(ch.isspace() for ch in text)
        ):
            return f"{roster}/{need}"
    if typ == "todo":
        raise CoordError(
            f"{command} todo: give the todo id (a number above 0) or ROSTER/NEED (for example cold-test/fix-login)"
        )
    # #327: a hold by its resource name; the server resolves it to the hold id.
    if typ == "hold" and text and not text.isdigit():
        from agent_coord.helpers.bounds import resource_name

        return resource_name(text)
    raise CoordError(f"{command} {typ}: give the {typ} id (a number above 0)")


def translate(args: Any, ask: Callable[[str], str] | None = None) -> Any:
    """Rewrite args in place for the new CLI words; other commands pass through."""
    cmd = str(getattr(args, "cmd", "") or "")
    yes = bool(getattr(args, "yes", False))

    if cmd == "create":
        obj = str(getattr(args, "object", "") or "")
        if obj in ("roster", "label"):
            name = str(args.slug or "").strip()
            if not name:
                raise CoordError(f"create {obj}: name required")
            confirm(f"create {obj} {name}?", yes=yes, ask=ask)
            args.cmd = obj
            args.object = ""
            args.confirm = name
            args.yes = True
        return args

    if cmd in ("add", "remove"):
        kind = str(getattr(args, "kind", "") or "").strip()
        if ":" in kind:
            # #265 form: add|remove TYPE:ID [WHO] (mail recipient or watcher row).
            if getattr(args, "desks", ""):
                raise CoordError(f"{cmd} {kind}: one WHO at most (a desk or roster)")
            args.target = _type_id(kind, cmd)
            args.who = str(getattr(args, "group", "") or "").strip()
            args.yes = False
            return args
        if kind == "room":
            raise CoordError(GAP_ROOM.format(command=cmd))
        if kind != "roster":
            raise CoordError(f"{cmd}: TYPE is roster (mill {cmd} roster NAME [d1,d2]) or TYPE:ID (mill {cmd} todo:256)")
        if not str(getattr(args, "group", "") or "").strip():
            raise CoordError(f"{cmd} roster: NAME required")
        desks = _desks(getattr(args, "desks", ""))
        if cmd == "remove":
            who = ",".join(desks) if desks else "you"
            confirm(f"remove {who} from roster {args.group}?", yes=yes, ask=ask)
        args.cmd = "member-add" if cmd == "add" else "member-remove"
        args.batch_desks = desks
        args.desk = desks[0] if desks else ""
        args.yes = False
        return args

    if cmd in ("label", "unlabel"):
        typ = str(getattr(args, "type", "") or "").strip().lower()
        ref = card_ref(getattr(args, "id", ""), typ, cmd)
        if isinstance(ref, str):
            args.ref, args.id = ref, ""
        else:
            args.id = ref
        args.cmd = "label-add" if cmd == "label" else "label-remove"
        return args

    if cmd in _TREE_IDS:
        # #706: a todo goes by ROSTER/NEED here too, as in label and watch; the wall resolves it.
        for typ_key, id_key, ref_key in _TREE_IDS[cmd]:
            raw = getattr(args, id_key, None)
            if raw is None or str(raw).strip() == "":
                continue
            typ = str(getattr(args, typ_key, "") or "").strip().lower()
            ref = card_ref(raw, typ, cmd)
            if isinstance(ref, str):
                setattr(args, ref_key, ref)
                setattr(args, id_key, None)
            else:
                setattr(args, id_key, ref)
        return args

    if cmd == "connected":
        # The wall RPC command stays session (like member-add); the CLI word is connected (#274).
        args.cmd = "session"
        return args

    if cmd in ("watch", "unwatch"):
        if args.type == "room":
            raise CoordError(GAP_ROOM.format(command=cmd))
        ref = card_ref(args.target, args.type, cmd)
        # Rides the #265 add/remove RPC for this desk (server unwatch is #265's remove).
        args.target = (args.type, ref)
        args.who = ""
        args.cmd = "add" if cmd == "watch" else "remove"
        # The reply names the command the desk typed, not the RPC it rides (ux12).
        args.said_command = cmd
        if cmd == "unwatch":
            args.hint = ""
        return args

    if cmd == "rename":
        if args.kind == "desk":
            # Card 880: your own desk stays on the self path; another desk needs --yes (Admin path, outbound).
            args.desk_admin = yes
            args.yes = False
            return args
        retype(args.new, f"rename {args.kind} {args.old}", yes=yes, ask=ask)
        args.confirm = args.new
        args.yes = True
        return args

    if cmd == "retire":
        if args.kind == "score":
            # mill retire score ROSTER NAME rides the score RPC (#302).
            name = str(getattr(args, "score_name", "") or "").strip()
            if not name:
                raise CoordError("retire: mill retire score ROSTER NAME")
            retype(name, f"retire score {args.slug} {name}", yes=yes, ask=ask)
            args.cmd = "score"
            args.project = args.slug
            args.name = name
            args.retire_score = True
            args.yes = False
            return args
        if args.kind == "todo":
            # #19: mill retire todo ROSTER NEED[,NEED...] (asker or Admin); reclaim undoes it.
            need = str(getattr(args, "score_name", "") or "").strip()
            if not need:
                raise CoordError("retire: mill retire todo ROSTER NEED")
            confirm(f"retire todo {args.slug} {need}?", yes=yes, ask=ask)
            args.project = args.slug
            args.need = need
            args.slug = ""
            args.yes = False
            return args
        if str(getattr(args, "score_name", "") or ""):
            raise CoordError(f"retire: {args.kind} takes one NAME")
        if args.kind == "desk":
            retype(args.slug, f"retire desk {args.slug}", yes=yes, ask=ask)
            # Card 880: the name was typed twice; outbound sends the Admin path for another desk.
            args.desk_admin = True
            args.yes = False
            args.confirm = ""
            return args
        retype(args.slug, f"retire {args.kind} {args.slug}", yes=yes, ask=ask)
        args.confirm = args.slug
        args.yes = True
        return args


    if cmd == "delete":
        # Card 879: mill delete roster|label|tree NAME stamps trashed (restorable).
        kind = str(getattr(args, "kind", "") or "").strip().lower()
        if kind not in ("roster", "label", "tree"):
            raise CoordError("delete: mill delete roster|label|tree NAME")
        if str(getattr(args, "score_name", "") or getattr(args, "need", "") or ""):
            raise CoordError(f"delete: {kind} takes one NAME")
        retype(args.slug, f"delete {kind} {args.slug}", yes=yes, ask=ask)
        args.confirm = args.slug
        args.yes = True
        return args

    if cmd == "restore":
        kind = str(getattr(args, "kind", "") or "").strip().lower()
        if kind not in ("roster", "label", "tree"):
            raise CoordError("restore: mill restore roster|label|tree NAME")
        retype(args.slug, f"restore {kind} {args.slug}", yes=yes, ask=ask)
        args.confirm = args.slug
        args.yes = True
        return args

    if cmd == "purge":
        kind = str(getattr(args, "kind", "") or "").strip().lower()
        if kind not in ("roster", "label", "tree"):
            raise CoordError("purge: mill purge roster|label|tree NAME")
        retype(args.slug, f"purge {kind} {args.slug}", yes=yes, ask=ask)
        args.confirm = args.slug
        args.yes = True
        return args

    if cmd == "reclaim":
        if args.kind == "todo":
            need = str(getattr(args, "need", "") or "").strip()
            if not need:
                raise CoordError("reclaim: mill reclaim todo ROSTER NEED")
            confirm(f"reclaim todo {args.slug} {need}?", yes=yes, ask=ask)
            args.project = args.slug
            args.slug = ""
            args.yes = False
            return args
        if str(getattr(args, "need", "") or ""):
            raise CoordError(f"reclaim: {args.kind} takes one NAME")
        confirm(f"reclaim {args.kind} {args.slug}?", yes=yes, ask=ask)
        args.confirm = args.slug
        args.yes = True
        return args

    if cmd == "reset":
        if bool(getattr(args, "dead", False)):
            return args
        if args.kind != "seat" or not str(args.desk or "").strip():
            raise CoordError("reset: mill reset seat DESK (or mill reset --dead)")
        confirm(f"reset seat {args.desk}? The desk must join again.", yes=yes, ask=ask)
        args.yes = False
        return args

    if cmd in ("hold", "drop"):
        # Holds are office-wide; the record is tagged with the Office roster.
        from agent_coord.const import CONST_OFFICE

        args.project = CONST_OFFICE
        return args

    if cmd == "send":
        pairs = list(getattr(args, "to", None) or [])
        if len(pairs) % 2:
            raise CoordError("send: say roster NAME or desk NAME")
        tos = list(getattr(args, "to_desk", None) or [])
        kinds: dict[str, str] = {}
        words = iter(pairs)
        for kind, name in zip(words, words):
            if kind not in ("roster", "desk"):
                raise CoordError(f"send: {kind!r} is not roster or desk")
            if kinds.get(name, kind) != kind:
                raise CoordError(f"send: {name} is named as both desk and roster")
            kinds[name] = kind
            tos.append(name)
        # The server checks each word against the name's type (#274).
        args.to_kinds = kinds
        if not tos:
            raise CoordError("send: To required: roster NAME, desk NAME or --to-desk DESK")
        args.to_desk = tos
        return args

    return args
