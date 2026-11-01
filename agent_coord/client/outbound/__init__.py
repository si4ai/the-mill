# -*- coding: utf-8 -*-
"""Desk outbound: skill.md commands -> POST /mill/v1/<command>.

mill-wall may still accept /api/mill/<command> as an alias.
"""
from __future__ import annotations

import os
from typing import Any

from agent_coord.helpers.ident import slug

PATH = "/mill/v1"
_ALIAS_PATH = "/api/mill"

# skill.md outbound (canonical)
COMMANDS = frozenset(
    {
        "open",
        "unpark",
        "claim",
        "assign",
        "unclaim",
        "note",
        "pass",
        "todo",
        "send",
        "reply",
        "mail-thread",
        "mark",
        "inbox",
        "rooms",
        "hold",
        "drop",
        "attach",
        "move",
        "prune",
        "detach",
        "label-add",
        "member-add",
        "add",
        "remove",
        "score",
        "trail",
        "wake-done",
    }
)

ALIASES: dict[str, str] = {}

# mill connect / JOIN (not skill.md chat idioms). project is the connect check (#237).
SIT = frozenset({"join", "session", "project"})
# Test-only RPC (#160). Not in skill.md, no mill subcommand; only
# tools/probe_deleted_rows.py sends it. Own t-<8 hex> fixture rows only.
PROBE = frozenset({"probe-delete"})
# mill-wall also serves these skill.md-adjacent commands
WALL = COMMANDS | SIT | PROBE | frozenset(
    {
        "label-remove",
        "member-remove",
        "rename",
        "retire",
        "label",
        "member",
        "roster",
        "reclaim",
        "delete",
        "restore",
        "purge",
        "reset",
        "invite",
        "invite-seat",
        "trust",
        "glance",
    }
)

_STR = (
    "need",
    "detail",
    "doing",
    "waiting_on",
    "status",
    "desk",
    "dst",
    "src",
    "body",
    "tree",
    "parent_type",
    "type_a",
    "type_b",
    "note",
    "supersedes",
    "eta",
    "msg",
    "resource",
    "type",
    "label",
    "type_a",
    "type_b",
    "name",
    "kpi",
    "value",
    "target",
    "group",
    "old",
    "new",
    "slug",
    "role",
    "root",
    "confirm",
    "desk",
    "hint",
    "roster",
    "ref",
    "ref_a",
    "ref_b",
    "parent_ref",
    "better",
    "unit",
    "at",
    "since",
    "lease",
    "sort",
)
_INT = ("id", "id_a", "id_b", "rm_id", "after", "limit", "parent_id", "page")


def canonical_command(raw: str) -> str:
    v = slug(str(raw or ""))
    return ALIASES.get(v, v)


def command_path(command: str) -> str:
    return f"{PATH}/{canonical_command(command)}"


def parse_path(path: str) -> str | None:
    """Command from URL, or None if this is not a mill-command path with a command segment."""
    p = (path or "").split("?", 1)[0]
    if p.startswith("/api/v1/"):
        p = "/api/" + p[len("/api/v1/") :]
    for pre in (PATH + "/", _ALIAS_PATH + "/"):
        if p.startswith(pre):
            rest = p[len(pre) :].strip("/")
            return canonical_command(rest) if rest else None
    return None


def is_mill_command_path(path: str) -> bool:
    p = (path or "").split("?", 1)[0]
    if p.startswith("/api/v1/"):
        p = "/api/" + p[len("/api/v1/") :]
    if parse_path(p) is not None:
        return True
    return p in (PATH, _ALIAS_PATH) or p.startswith(PATH + "/") or p.startswith(_ALIAS_PATH + "/")



def resolve_send_body(raw: str) -> str:
    """Inline body, '-' = stdin, '@path' = UTF-8 file. Limit 1..MAIL_BODY_MAX.

    PowerShell: quote '@file' (bare @ is splat). Pipe into '-' for stdin.
    Never return the literal '@path' or '-' - expand or raise CoordError.
    """
    import sys
    from pathlib import Path

    from agent_coord.helpers.errors import CoordError
    from agent_coord.protocol.mail import MAIL_BODY_MAX

    s = "" if raw is None else str(raw)
    if s == "-":
        if sys.stdin.isatty():
            raise CoordError(
                "send: body '-' requires stdin (pipe or redirect; not a TTY). "
                "PowerShell: Get-Content letter.txt | mill send ... -"
            )
        data = sys.stdin.read()
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        s = data
    elif s.startswith("@") and len(s) > 1:
        path = Path(s[1:]).expanduser()
        try:
            s = path.read_text(encoding="utf-8")
        except OSError as e:
            raise CoordError(
                f"send: body file not found: {path} "
                "(quote '@path' in PowerShell so @ is not splat)"
            ) from e
    s = s.lstrip("\ufeff").strip()
    if not s or len(s) > MAIL_BODY_MAX:
        raise CoordError(f"body must be 1..{MAIL_BODY_MAX} chars")
    return s


def resolve_body_file(path: str, what: str = "body") -> str:
    """UTF-8 text from --body-file / --detail-file PATH. Same limits as resolve_send_body."""
    from pathlib import Path

    from agent_coord.helpers.errors import CoordError
    from agent_coord.protocol.mail import MAIL_BODY_MAX

    p = Path(str(path or "")).expanduser()
    try:
        s = p.read_text(encoding="utf-8")
    except OSError as e:
        raise CoordError(f"{what}-file: not found: {p}") from e
    except UnicodeDecodeError as e:
        raise CoordError(f"{what}-file: not UTF-8: {p}") from e
    s = s.lstrip("\ufeff").strip()
    if not s or len(s) > MAIL_BODY_MAX:
        raise CoordError(f"{what} must be 1..{MAIL_BODY_MAX} chars")
    return s


def _note_text(raw: Any) -> str:
    """note text: '@path' reads a UTF-8 file, '-' reads stdin, else inline."""
    s = "" if raw is None else str(raw)
    if s == "-" or (s.startswith("@") and len(s) > 1):
        return resolve_send_body(s)
    return s.strip()


def _note_fields(args: Any, body: dict[str, Any]) -> None:
    """mill note: send the positional text, @file, --note, --eta, --started (#102).

    Progress is the positional token (9/12, 75%, done, git <sha>).
    """
    text = _note_text(getattr(args, "text", ""))
    if text:
        body["text"] = text
    if body.get("note"):
        body["note"] = _note_text(body["note"])
    eta = str(getattr(args, "eta", "") or "").strip()
    if eta:
        body["eta"] = eta
    if bool(getattr(args, "started", False)):
        body["started"] = True


# Commands whose project and --doing are checked before the call (#243-#245).
_PROJECT_GUARD = {"open", "todo", "label-add", "label-remove", "unpark"}
# #818 PR B: every command that takes --doing (the doing entry links to its item).
_DOING_GUARD = {"send", "reply", "mark", "open", "claim", "unclaim", "assign", "pass", "note", "unpark", "hold", "drop", "score"}
DOING_MAX = 512


def _guard_args(command: str, cmd: str, args: Any) -> None:
    """Refuse an empty or over-length project and an over-length --doing, plainly."""
    from agent_coord.helpers.errors import CoordError

    name = cmd or command
    if command in _PROJECT_GUARD and hasattr(args, "project"):
        raw = getattr(args, "project")
        if raw is not None:
            p = str(raw).strip()
            if not p and command != "todo":
                raise CoordError(f"{name}: project required")
            if len(p) > 64:
                raise CoordError(f"{name}: no such roster {p[:64]}. list them: mill member")
    # #326: hold with no resource is the lock list, with or without --peek.
    if command == "hold" and not str(getattr(args, "resource", "") or "").strip():
        if str(getattr(args, "doing", "") or ""):
            raise CoordError(f"{name}: --doing needs a resource")
    if command in _DOING_GUARD:
        doing = str(getattr(args, "doing", "") or "")
        if len(doing) > DOING_MAX:
            raise CoordError(f"{name}: --doing must be 0..{DOING_MAX} chars")
        # #822: blocked-on rides the doing entry; alone it has nothing to sit on.
        if str(getattr(args, "waiting_on", "") or "").strip() and not doing.strip():
            raise CoordError(f"{name}: --waiting-on goes with --doing; nothing was changed")


# Card 866: a done-when note writes only the done-when, so other note fields beside it would be lost.
_NOTE_WITH_DONE_WHEN = ("text", "note", "supersedes", "eta", "started")
_DONE_WHEN_ALONE = "note: --done-when goes alone; send the note in its own mill note. Nothing changed"


def body_from_args(args: Any) -> dict[str, Any]:
    cmd = str(getattr(args, "cmd", "") or "")
    obj = str(getattr(args, "object", "") or "")
    if cmd == "create":
        if obj != "todo":
            raise ValueError("mill create todo ROSTER NEED | create roster NAME | create label NAME")
        command = "open"
    else:
        command = canonical_command(cmd)
    from agent_coord.client.tokens import resolve_desk_owner
    from agent_coord.helpers.errors import CoordError
    from agent_coord.helpers.ident import desk as desk_stem

    _guard_args(command, cmd, args)
    # Actor = sitting connect for this parent pid (never argv, never host active).
    owner = resolve_desk_owner("")
    dst = str(getattr(args, "dst", "") or "")
    src = str(getattr(args, "src", "") or "")
    # inbox dst is mailbox data only; actor/Bearer = connect session (no dst spoof)
    body: dict[str, Any] = {
        "verb": command,
        "project": str(getattr(args, "project", "") or "") or "the-mill",
        "owner": owner,
    }
    need = str(getattr(args, "need", "") or getattr(args, "need_id", "") or "")
    if need:
        body["need"] = need
    # #333: a blank OLD_LINE would fall through to a plain note .
    sup = getattr(args, "supersedes", None)
    if sup is not None and not str(sup).strip():
        from agent_coord.helpers.errors import CoordError

        raise CoordError("note: --supersedes needs the old line; copy it from mill todo")
    for key in _STR:
        if key == "need":
            continue
        if not hasattr(args, key):
            continue
        val = getattr(args, key)
        if val is None or val == "":
            continue
        body[key] = str(val)
    for key in _INT:
        if not hasattr(args, key):
            continue
        val = getattr(args, key)
        if val is None or val == "":
            continue
        body[key] = int(val)
    if command == "mark":
        raw_ids = getattr(args, "ids", None) or []
        if isinstance(raw_ids, (list, tuple)):
            body["ids"] = [str(x) for x in raw_ids]
        elif raw_ids not in ("", None):
            body["ids"] = [part for part in str(raw_ids).replace(",", " ").split() if part]
    if hasattr(args, "all"):
        body["all"] = bool(args.all)
    if hasattr(args, "asc"):
        body["asc"] = bool(args.asc)
    if hasattr(args, "star"):
        body["star"] = bool(args.star)
    if command == "pass":
        # #615: the step is named; a repeat never moves a card on by itself.
        body["step"] = "done" if getattr(args, "done", False) else ("back" if getattr(args, "back", False) else "ship")
        # Card 866: evidence rides the pass. The server stores it. Blank is omitted.
        # --back still sends it; the server stores none.
        ev = str(getattr(args, "evidence", "") or "").strip()
        if ev:
            if len(ev) > 2000:
                raise CoordError(
                    "pass: evidence would be %s chars (max 2000); refused, nothing changed" % len(ev)
                )
            body["evidence"] = ev
    if command in ("open", "note"):
        raw_dw = getattr(args, "done_when", None)
        if raw_dw is not None:
            dw = str(raw_dw).strip()
            if len(dw) > 1000:
                tail = "nothing stored" if command == "open" else "nothing changed"
                raise CoordError(
                    "done-when would be %s chars (max 1000); refused, %s" % (len(dw), tail)
                )
            if command == "note" or dw:
                body["done_when"] = dw
            if command == "note" and any(
                getattr(args, k, None) not in (None, "", False) for k in _NOTE_WITH_DONE_WHEN
            ):
                raise CoordError(_DONE_WHEN_ALONE)
    if command == "glance":
        body.pop("project", None)
    if bool(getattr(args, "yes", False)):
        body["yes"] = True
    if command == "claim" and bool(getattr(args, "take_over", False)):
        body["take_over"] = True
    # send/reply: the sender project comes from the seat, never a silent the-mill (#241).
    if command in ("send", "reply"):
        body.pop("project", None)
    # mill send: From is the connect desk only.
    if command == "send":
        if body.get("owner"):
            body["src"] = str(body["owner"])
        if src and body.get("owner"):
            if desk_stem(src) != desk_stem(str(body["owner"])):
                raise CoordError(
                    "send: src must be the mill connect desk "
                    f"(got {src!r}; connect is {body.get('owner')!r})"
                )
    # #818 PR B: mill connected reads every roster when none is named.
    if command == "session":
        if not str(getattr(args, "project", "") or "").strip():
            body.pop("project", None)
        if bool(getattr(args, "history", False)):
            body["history"] = True
        if int(getattr(args, "page", 0) or 0):
            body["page"] = int(args.page)
        # Card 647: released clients always send limit=10. Move a typed --limit
        # onto connected_limit so those bodies stay uncapped, including history.
        raw_limit = body.pop("limit", None)
        if raw_limit is not None:
            if int(raw_limit) < 1:
                raise CoordError("connected: --limit must be at least 1")
            if body.get("history"):
                raise CoordError("connected: --limit is for the live list, not --history")
            body["connected_limit"] = int(raw_limit)
    if command in ("hold", "drop"):
        from agent_coord.helpers.bounds import resource_name

        if str(body.get("resource") or "").strip() or command == "drop":
            body["resource"] = resource_name(str(body.get("resource") or ""))
        else:
            body.pop("resource", None)
    if command == "hold" and (bool(getattr(args, "peek", False)) or "resource" not in body):
        body["peek"] = True
    detail_file = str(getattr(args, "detail_file", "") or "").strip()
    if detail_file:
        body["detail"] = resolve_body_file(detail_file, "detail")
    if command in ("send", "reply"):
        body_file = str(getattr(args, "body_file", "") or "").strip()
        if not body_file:
            raise CoordError(f"{command}: --body-file required")
        body["body"] = resolve_body_file(body_file)
    if command == "mail-thread":
        mid = getattr(args, "mail_id", None)
        if mid is None:
            mid = getattr(args, "id", None)
        if mid is not None and mid != "":
            s = str(mid).strip()
            if s.isdigit():
                body["mail_id"] = int(s)
            else:
                # Host room handle = tree name. p_tree is VARCHAR(64) (#208).
                if len(s) > 64:
                    raise CoordError(f"mail-thread: no mail room named {s[:64]}")
                body["tree"] = s
        scope = str(getattr(args, "scope", "") or "").strip()
        if scope:
            body["scope"] = scope
    # reply <mail_id> --body-file PATH [--to-desk D]
    if command == "reply":
        mid = getattr(args, "mail_id", None)
        if mid is None:
            mid = getattr(args, "id", None)
        if mid is not None and mid != "":
            body["mail_id"] = int(mid)
    # add|remove TYPE:ID [WHO] (#265). argparse already checked TARGET.
    if command in ("add", "remove"):
        tgt = getattr(args, "target", None)
        if isinstance(tgt, tuple):
            body["type"] = tgt[0]
            if isinstance(tgt[1], str):
                body["ref"] = tgt[1]  # a todo by ROSTER/NEED; the wall resolves it (#274)
                body.pop("id", None)
            else:
                body["id"] = int(tgt[1])
        body.pop("target", None)
        who = str(getattr(args, "who", "") or "").strip()
        if who:
            body["who"] = who
    # --to-desk (send/reply), repeatable
    if command in ("send", "reply"):
        raw_desks = getattr(args, "to_desk", None)
        if raw_desks is not None:
            to_desk = [str(x).strip() for x in raw_desks]
            if not all(to_desk):
                raise CoordError(f"{command}: --to-desk needs a desk name")
            kinds = getattr(args, "to_kinds", None) or {}
            if command == "send" and isinstance(kinds, dict) and kinds:
                # send desk|roster NAME: the word rides along so the wall checks it (#274).
                body["mail_tos"] = [
                    {"deskId": d, "kind": kinds[d]} if d in kinds else d for d in to_desk
                ]
            else:
                body["mail_tos"] = to_desk
    if cmd in ("retire", "rename", "reclaim", "delete", "restore", "purge") and str(getattr(args, "kind", "") or "") in ("roster", "label", "desk", "tree"):
        # #537: the wall acts on the type named; a label may share its desk's name.
        body["name_type"] = str(args.kind)
    if cmd == "rename" and str(getattr(args, "kind", "") or "") == "todo":
        # #926: rename a card need; project is ROSTER, need is OLD, new is NEW.
        body["name_type"] = "todo"
        body.pop("slug", None)
        why = str(getattr(args, "why", "") or "").strip()
        if why:
            body["why"] = why
    if cmd in ("retire", "rename") and str(getattr(args, "kind", "") or "") == "desk" and getattr(args, "desk_admin", False):
        # Card 880: another desk's name goes to the wall's Admin path (yes + the name twice);
        # your own desk keeps the self path, which needs no Admin.
        target = str(body.get("slug" if cmd == "retire" else "old") or "").strip()
        if target and target != desk_stem(owner):
            body["yes"] = True
            body["confirm"] = target if cmd == "retire" else str(body.get("new") or "").strip()
    if cmd in ("retire", "reclaim") and str(getattr(args, "kind", "") or "") == "todo":
        # #19: retire / reclaim a card; project is the ROSTER, need the NEED (or a comma list).
        body["name_type"] = "todo"
        body.pop("slug", None)
        body.pop("confirm", None)
    if command == "todo" and bool(getattr(args, "done", False)):
        body["done"] = True
    if command == "todo" and bool(getattr(args, "fixtures", False)):
        body["fixtures"] = True
    if command == "todo" and bool(getattr(args, "mine", False)):
        # #667: the wall sends only this desk's cards; focus.order_mine still ranks them.
        body["mine"] = True
    if bool(getattr(args, "dead", False)):
        body["dead"] = True
    if command == "score" and bool(getattr(args, "retire_score", False)):
        body["retire"] = True
    if command == "note":
        _note_fields(args, body)
    if command == "label-add" and hasattr(args, "ord") and getattr(args, "ord") is not None:
        from agent_coord.helpers.label_ord import parse_label_ord

        body["ord"] = parse_label_ord(getattr(args, "ord"))
    if command == "trail":
        node = str(getattr(args, "node", "") or "").strip()
        label = str(body.get("label") or getattr(args, "label", "") or "").strip()
        if label and node:
            raise CoordError("trail: say a node or --label, not both")
        if not label and not node:
            raise CoordError("trail: give a mail id, a todo id, or --label NAME")
        if node:
            body["node"] = node
        if label:
            body["label"] = label
    if command == "watcher" and bool(getattr(args, "remove", False)):
        body["remove"] = True
    if command == "trust":
        level = str(getattr(args, "level", "") or "").strip()
        if level:
            body["level"] = level
    if command == "invite":
        seat = str(getattr(args, "seat", "") or "").strip()
        if seat:
            body["verb"] = "invite-seat"
            body["desk"] = seat
            # Seat roster is --roster only. Server defaults to that desk's one
            # non-Office roster; do not send the minter connect default (#252).
            proj = str(getattr(args, "seat_roster", "") or "").strip()
            if proj:
                body["project"] = proj
            else:
                body.pop("project", None)
            return body
        if bool(getattr(args, "mint", False)):
            body["mint"] = True
        if bool(getattr(args, "rotate", False)):
            body["rotate"] = True
        for key in ("door", "enable", "revoke", "ttl", "ttl_for", "lan_only"):
            if not hasattr(args, key):
                continue
            val = getattr(args, key)
            if val is None or val == "":
                continue
            body[key] = val
    return body
