from __future__ import annotations

import argparse
import json
import os
import sys

from agent_coord.lib.py_gate import exit_if_too_old

exit_if_too_old()  # belt: __init__ already gated; keep console-script entry safe

from agent_coord.helpers.errors import CoordError
from .install import consume_mill_agent

from agent_coord.install.packver import package_version

def _format_error(exc: BaseException) -> str:
    """Host failures print JSON. A local error with no sync list stays plain text."""
    env = getattr(exc, "envelope", None)
    if isinstance(env, dict) and "ok" in env:
        out = dict(env)
        if not isinstance(out.get("sync"), list):
            out["sync"] = list(getattr(exc, "sync", None) or out.get("sync") or [])
        if "error" not in out or out.get("error") is None:
            out["error"] = str(exc)
        if "result" not in out:
            out["result"] = None
        return json.dumps(out, default=str)
    sync = getattr(exc, "sync", None)
    if not isinstance(sync, list):
        return str(exc)
    return json.dumps({"ok": False, "error": str(exc), "sync": sync}, default=str)


def normalize_seat_argv(argv: list[str]) -> list[str]:
    """`--seat -value` becomes `--seat=-value` so a leading dash is the value (#145)."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        item = argv[i]
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        if item == "--seat" and nxt.startswith("-") and not nxt.startswith("--"):
            out.append("--seat=" + nxt)
            i += 2
            continue
        out.append(item)
        i += 1
    return out


BODY_FILE_FIX = "write the body to a UTF-8 file and pass --body-file PATH (a body in the command line is not read)"
_BODY_COMMANDS = ("reply", "send")


class MillArgumentParser(argparse.ArgumentParser):
    _command = ""

    def parse_known_args(self, args=None, namespace=None):
        words = list(sys.argv[1:] if args is None else args)
        self._command = next((w for w in words if not str(w).startswith("-")), "")
        return super().parse_known_args(args, namespace)

    def error(self, message: str) -> None:
        if "--seat" in message and "expected one argument" in message:
            message = message + "; if the value starts with '-', use --seat=VALUE"
        elif "required: --body-file" in message or (
            "unrecognized arguments" in message and self._command in _BODY_COMMANDS
        ):
            # #638: one line that names the fix, not just the missing flag.
            message = message + "; " + BODY_FILE_FIX
        super().error(message)


def _attach_office_help(parser: argparse.ArgumentParser) -> None:
    """Put --office on every -h. pull_office_flag still reads the value (#158)."""
    parser.add_argument(
        "--office",
        default="",
        metavar="ALIAS",
        help="office alias; place it before or after the command",
    )
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for child in action.choices.values():
                _attach_office_help(child)


class _GenerateCount(argparse.Action):
    """Bare --generate asks; --generate 6 keeps that count."""

    def __call__(self, parser, namespace, values, option_string=None):
        if values is None:
            setattr(namespace, self.dest, "ask")
            return
        try:
            count = int(values)
        except (TypeError, ValueError):
            parser.error("digit count must be a number")
        setattr(namespace, self.dest, count)


def _print(obj) -> int:
    from .install import redact_user_paths

    raw = json.dumps(redact_user_paths(obj), default=str, indent=2)
    print(raw, flush=True)
    return len(raw.encode("utf-8"))

def _print_err(obj) -> int:
    """Error JSON object: same shape as _print, on stderr."""
    from .install import redact_user_paths

    raw = json.dumps(redact_user_paths(obj), default=str, indent=2)
    print(raw, file=sys.stderr, flush=True)
    return len(raw.encode("utf-8"))


def _connect_json_error(error: str, desk: str) -> int:
    """Stdout JSON, same shape as the desk-required refusal inside mill connect."""
    print(json.dumps({"ok": False, "error": error, "desk": desk}, default=str), flush=True)
    return 1


def _invite_url(path: str) -> str:
    from agent_coord.client.http import mill_url

    base = (mill_url() or "").strip().rstrip("/")
    rel = path or ""
    if base and rel.startswith("/"):
        return base + rel
    return rel


def _welcome_desk_bare(url: str) -> str:
    """Welcome URLs hand the stored desk name."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    from agent_coord.helpers.ident import desk_name

    parts = urlsplit(url)
    if not parts.query or "desk=" not in parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    changed = False
    bare_pairs: list[tuple[str, str]] = []
    for key, val in pairs:
        if key == "desk":
            who = desk_name(val)
            if who != val:
                changed = True
            bare_pairs.append((key, who))
        else:
            bare_pairs.append((key, val))
    if not changed:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(bare_pairs), parts.fragment)
    )

_INVITE_SECRET_KEYS = ("token", "seat", "invite_url", "invite_path")
WITHHELD = "<withheld: see link_file>"


def _withhold(obj, secrets):
    """Copy of obj with every minted secret replaced, wherever it sits (#607).

    #359 dropped a fixed list of key names, so join_argv (mill join <welcome
    link>) still printed the seat. Matching the secret value covers any field.
    """
    from urllib.parse import quote

    vals = sorted({str(s) for s in secrets if s and len(str(s)) >= 8}, key=len, reverse=True)
    if not vals:
        return obj
    forms = sorted({f for v in vals for f in (v, quote(v, safe=""))}, key=len, reverse=True)

    def walk(x):
        if isinstance(x, str):
            for f in forms:
                if f in x:
                    x = x.replace(f, WITHHELD)
            return x
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v) for v in x]
        return x

    return walk(obj)


def _install_secrets(result: dict) -> tuple[list[str], list[str]]:
    """Secrets and links that mill init / mill install server minted (#607)."""
    secrets: list[str] = []
    links: list[str] = []
    inv = result.get("invite") if isinstance(result.get("invite"), dict) else {}
    seat = result.get("seat_welcome") if isinstance(result.get("seat_welcome"), dict) else {}
    if inv.get("token"):
        secrets.append(str(inv["token"]))
        link = str(result.get("invite_link") or inv.get("invite_path") or "")
        if link:
            links.append(link)
    if seat.get("seat"):
        secrets.append(str(seat["seat"]))
        if seat.get("invite_url"):
            links.append(str(seat["invite_url"]))
    return secrets, links


def _print_install(args, result) -> None:
    """Print an init or install result; minted links go to an owner-only file (#607)."""
    if not isinstance(result, dict):
        _print(result)
        return
    secrets, links = _install_secrets(result)
    if not secrets:
        _print(result)
        return
    out = _withhold(result, secrets)
    try:
        where = _invite_link_file(args, "install", "\n".join(links))
    except OSError as e:
        _print(out)
        print(
            f"mill: could not write the link file ({e.strerror or e}); the minted links were not printed. "
            "Rerun mill invite --seat DESK or mill invite --mint for new ones",
            file=sys.stderr,
            flush=True,
        )
        return
    out["link_file"] = str(where)
    out["link"] = "minted links written to link_file (owner-only); hand them over privately"
    _print(out)


def _invite_link_file(args, name: str, link: str) -> "Path":
    """Write a welcome or invite link to a file only this user can read (#359).

    Default: <mill home>/invites/<name>-<UTC stamp>.link, the folder 0700 and
    the file 0600 (icacls on Windows), like the seat token. --link-file PATH
    picks the file; an existing file is never overwritten.
    """
    from datetime import datetime, timezone
    from pathlib import Path

    from agent_coord.client.tokens import _restrict_owner_only, mill_home

    chosen = str(getattr(args, "link_file", "") or "").strip()
    if chosen:
        path = Path(chosen).expanduser()
    else:
        folder = mill_home() / "invites"
        folder.mkdir(parents=True, exist_ok=True)
        _restrict_owner_only(folder, is_dir=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in (name or "invite"))[:64]
        path = folder / f"{safe}-{stamp}.link"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(link + "\n")
    _restrict_owner_only(path)
    return path


def _invite_cmd(args) -> int:
    """POST /mill/v1/invite. The wall opens the book. This machine does not.

    A minted link carries a secret (the seat or the invite key), so it goes to
    a 0600 file and stdout names the file (#359); --print-link prints it.
    """
    from agent_coord.client.outbound import body_from_args
    from agent_coord.client.http import mill_http_call

    try:
        body = body_from_args(args)
        row = mill_http_call(body)
    except CoordError as e:
        print(str(e), file=sys.stderr, flush=True)
        return 1
    if not isinstance(row, dict):
        print(json.dumps(row, default=str), flush=True)
        return 0
    row = dict(row)
    # The wall answers an envelope {ok, result: {...}}; older walls a flat row.
    inner = dict(row["result"]) if isinstance(row.get("result"), dict) else row
    found = {k: inner.pop(k, None) or row.pop(k, None) for k in _INVITE_SECRET_KEYS}
    if inner is not row:
        row["result"] = inner
    path = str(found["invite_path"] or "")
    token = found["token"]
    seat = found["seat"]
    invite_url = str(found["invite_url"] or "")
    if not path and token:
        path = "/?invite=" + str(token)
    if inner.get("desk"):
        from agent_coord.helpers.ident import desk_name

        inner["desk"] = desk_name(str(inner["desk"]))
    link = ""
    if invite_url:
        link = _welcome_desk_bare(invite_url)
    elif path:
        link = _invite_url(path)
    elif seat and inner.get("desk"):
        from urllib.parse import urlencode

        link = _invite_url("/welcome?" + urlencode({"desk": inner["desk"], "seat": seat}))
    # #607: withhold the secret in any field (join_argv, or one a later wall adds).
    row = _withhold(row, [token, seat])
    inner = row["result"] if isinstance(row.get("result"), dict) else row
    if link and bool(getattr(args, "print_link", False)):
        _print(row)
        print(link, flush=True)
    elif link:
        try:
            where = _invite_link_file(args, str(inner.get("desk") or inner.get("key_id") or "invite"), link)
        except OSError as e:
            _print(row)
            print(
                f"mill invite: could not write the link file ({e.strerror or e}); "
                "nothing printed. Rerun with --link-file PATH, or --print-link to print it",
                file=sys.stderr,
                flush=True,
            )
            return 1
        inner["link_file"] = str(where)
        inner["link"] = "written to link_file (owner-only); hand it over privately; the desk saves it and runs mill join --link-file PATH; --print-link prints it instead"
        _print(row)
    else:
        _print(row)
    if body.get("mint") or body.get("rotate"):
        print(
            f"mill invite --enable {inner.get('key_id')}  # connect desk={body.get('owner') or ''}",
            flush=True,
        )
    if row.get("ok") is False or row.get("error") or inner.get("ok") is False:
        return 1
    return 0

def _resolve_send_body(raw: str) -> str:
    """Delegate to outbound.resolve_send_body (wired for mill send)."""
    from agent_coord.client.outbound import resolve_send_body

    return resolve_send_body(raw)

def _label_ord_arg(raw: str) -> int:
    """argparse type for label-add --ord. Plain refusal outside 0..65535 (#198)."""
    import argparse

    from agent_coord.helpers.label_ord import parse_label_ord

    try:
        got = parse_label_ord(raw)
    except CoordError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    if got is None:
        raise argparse.ArgumentTypeError("ord must be a whole number from 0 to 65535")
    return got


def _add_target_arg(raw: str) -> tuple[str, int]:
    """argparse type for add/remove TARGET: type:id, never a bare id (#265).

    Ids repeat across activity kinds, so the kind is always named.
    """
    import argparse

    from agent_coord.const import ACTIVITY_TYPES

    text = str(raw or "").strip()
    kind, sep, num = text.partition(":")
    kind = kind.strip().lower()
    num = num.strip()
    if not sep or kind not in ACTIVITY_TYPES or not num.isdigit() or int(num) <= 0:
        raise argparse.ArgumentTypeError(
            "TARGET is type:id (for example todo:256 or mail:1866), type one of "
            + "|".join(ACTIVITY_TYPES)
        )
    return kind, int(num)



def seatless_connect_line(who: str) -> str:
    """The one refusal for mill connect NAME with no seat on this computer (#281)."""
    return (
        f"mill connect: no seat for {who} on this computer; a desk joins once with "
        f"mill join --link-file PATH (the welcome link from the office host) (a roster is not a desk: "
        f"mill connected ROSTER lists its desks)"
    )


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    from agent_coord.install.packver import checkout_dist_line

    mismatch = checkout_dist_line()
    if mismatch:
        print(mismatch, file=sys.stderr, flush=True)
    commands = [a for a in raw if not a.startswith("-")]
    if commands and commands[0] in ("leftover", "leftover-done"):
        print(
            '{"ok": false, "error": "unknown mill command. Idle is mill connect + HINT."}',
            flush=True,
        )
        return 2

    p = _build_parser()
    return _run_parsed(p, argv)


class _ThreadFull(argparse._StoreTrueAction):
    """mail-thread --full: alone, the whole branch (scope full) as before #295;
    with --room, every field of every letter and no paging (#295)."""

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[override]
        namespace.full = True
        if not getattr(namespace, "scope", ""):
            namespace.scope = "full"


def _page_number(raw: str) -> int:
    """todo --page N: a whole number from 1 (#295)."""
    try:
        n = int(raw)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError("N is a whole number from 1")
    return n


def _link_flags(sp) -> None:
    """--link-file for commands that mint an invite key or a host seat (#607).

    No --print-link here: the links are read from the owner-only file.
    """
    sp.add_argument(
        "--link-file",
        default="",
        dest="link_file",
        metavar="PATH",
        help="write the minted links here (owner-only; default under ~/.mill/invites)",
    )


DOING_HELP = (
    "what you are doing now, in a few words; mill connected shows it on this command's item. "
    "No end step: a reply or pass without --doing ends it"
)
WAITING_ON_HELP = (
    "with --doing: what this doing is blocked on, then why: a desk, mail-ID, todo-ID or hold-ID "
    "(--waiting-on \"gardener the column names\"). mill connected shows it, and the desk you wait on sees you"
)
DOING_FLAG_COMMANDS = (
    "send", "reply", "mark", "create", "claim", "unclaim", "assign", "pass", "note", "unpark", "hold", "drop", "score",
)


def _build_parser() -> MillArgumentParser:
    p = MillArgumentParser(
        prog="mill",
        description="The mill office. mill join then mill connect. mill send inbox todo hold. Humans: Wall.",
    )
    p.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="print the-mill version; a build that is not a release adds +g<commit> when known",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="debug: print POST /mill/v1 and /ws frames (PING too)",
    )
    p.add_argument(
        "--raw",
        action="store_true",
        help="desk commands: print lean result (old unwrap) instead of full ok/mill/id/result/sync envelope",
    )
    sub = p.add_subparsers(dest="cmd", required=False, metavar="COMMAND")

    
    br = sub.add_parser(
        "briefing",
        help="print bootstrap / join / human / usecases / commands / skill / connect / spawn / howto-ai / improve",
    )
    br.add_argument(
        "kind",
        nargs="?",
        default="",
        help="join / connect / skill / ...  (omit = list kinds). mill briefing is local printout.",
    )
    hp = sub.add_parser("help", help="mill CLI for desks (docs/protocol/cli-desk.md); mill help COMMAND = one command")
    hp.add_argument("command", nargs="?", default="", help="optional command (join, inbox, send, ...)")

    ini = sub.add_parser(
        "init",
        help="stand up the office (database, sql/, config). Does not mint a session token",
    )
    ini.add_argument("--yes", action="store_true", help="no prompts; flags and defaults")
    ini.add_argument("--host")
    ini.add_argument("--port", type=int)
    ini.add_argument("--user")
    ini.add_argument("--password")
    ini.add_argument("--database")
    ini.add_argument("--node")
    ini.add_argument("--bind", dest="dashboard_bind", help="dashboard bind (default 127.0.0.1)")
    ini.add_argument("--dashboard-port", type=int)
    ini.add_argument("--lan", action="store_true", help="dashboard on 0.0.0.0 for the office LAN")
    ini.add_argument("--config", dest="config_path", default="", help="config path")
    _link_flags(ini)

    a = sub.add_parser(
        "hold",
        help="take or refresh an office-wide lock: mill hold NAME (bare mill hold lists every lock)",
    )
    a.add_argument(
        "resource",
        nargs="?",
        default="",
        help="resource name; none lists every lock (same as --peek alone)",
    )
    a.add_argument(
        "--peek",
        action="store_true",
        help="show who holds the resource, or every lock when no resource; never takes or refreshes",
    )
    a.add_argument(
        "--group-by",
        dest="group_by",
        default="",
        choices=("tree", "label", "roster"),
        help="group the list by label or roster (default: flat; holds sit on no tree)",
    )

    r = sub.add_parser(
        "drop",
        help="release your lock: mill drop NAME",
    )
    r.add_argument("resource")

    dn = sub.add_parser(
        "wake-done",
        help="end this woken run: mill wake-done [--lease ID] [--note TEXT] (the last step of a webhook-woken run)",
        description=(
            "F144: the office sends one webhook wake at a time. mill wake-done ends this desk's wake lease; "
            "letters that came during the run ring once more, carrying pending_count and the note. "
            "Without it the lease lapses after the office's wake_lease_s (default 900 s). "
            "It closes no card: that is mill pass ROSTER NEED --done."
        ),
    )
    dn.add_argument("--note", default="", help="one line for the next wake (last_note): what you did, what is next")
    dn.add_argument("--lease", default="",
                    help="the wake.lease token of the wake that started this run: a run that outlived its lease ends nothing")

    m = sub.add_parser(
        "send",
        help="send a letter: mill send roster NAME | desk NAME --body-file PATH",
        description=(
            "mill send roster NAME --body-file PATH (every desk on the roster), "
            "or mill send desk NAME / --to-desk DESK (repeatable). [--room ROOM] opens a new room. "
            "--roster names the sender roster; omitted, the seat's single non-Office roster, else Office."
        ),
    )
    m.add_argument(
        "to",
        nargs="*",
        metavar="TYPE NAME",
        help="roster NAME or desk NAME, repeatable",
    )
    m.add_argument(
        "--to-desk",
        action="append",
        default=None,
        dest="to_desk",
        metavar="DESK",
        help="desk To (repeatable)",
    )
    m.add_argument(
        "--body-file",
        required=True,
        dest="body_file",
        metavar="PATH",
        help="UTF-8 body file (1..4096 chars)",
    )
    m.add_argument(
        "--roster",
        default="",
        dest="roster",
        help="sender roster (a live one); default: the seat's single non-Office roster, else Office",
    )
    m.add_argument(
        "--room",
        default="",
        dest="name",
        metavar="ROOM",
        help="open a new room with this name (a room that exists is refused; reply to it instead)",
    )

    rp = sub.add_parser(
        "reply",
        help="nest under mail_id; default reply-all (sender U mail_tos); "
        "--body-file; --to-desk replaces",
    )
    rp.add_argument("mail_id", type=int, help="parent mail id")
    rp.add_argument(
        "--body-file",
        required=True,
        dest="body_file",
        metavar="PATH",
        help="UTF-8 body file (1..4096 chars)",
    )
    rp.add_argument(
        "--to-desk",
        action="append",
        default=None,
        dest="to_desk",
        metavar="DESK",
        help="replace the reply-all list with these desks (repeatable)",
    )
    rp.add_argument(
        "--roster",
        default="",
        dest="roster",
        help="replying desk's sender roster; default as on send",
    )

    mt = sub.add_parser(
        "mail-thread",
        help="read mail: a letter's branch by default; --room for whole-room catch-up (lean MAIL)",
        description=(
            "mail-thread <mail_id> = letters on that branch after this desk's last read. "
            "A later read leaves out a letter this desk sent, unless you asked for that letter. "
            "--full = the whole branch. "
            "--subtree = that letter and every reply under it. "
            "--room = the whole room in short rows, 50 letters a page, newest page first "
            "(--page N reads page N; --room --full prints every field of every letter); "
            "--after <id> = only id > after "
            "(implies --room). A room name with no flag = short summary "
            "(root, latest few, counts). Envelope latest_id, room_letters, hint. "
            "Not a participant? mill reply <root id> --body-file PATH joins. "
            "A read that prints letters whole marks them (listed in marked); --room previews "
            "and a summary do not. reply marks the parent, mill mark marks the rest."
        ),
    )
    mt.add_argument(
        "mail_id",
        help="mail id (any node) or TREE/room name (Host room handle)",
    )
    scope = mt.add_mutually_exclusive_group()
    scope.add_argument(
        "--room",
        action="store_const",
        const="room",
        dest="scope",
        default="",
        help="whole room (every letter on the TREE); use for catch-up",
    )
    scope.add_argument(
        "--subtree",
        action="store_const",
        const="subtree",
        dest="scope",
        help="this letter and every reply under it",
    )
    mt.add_argument(
        "--full",
        action=_ThreadFull,
        help="whole branch, ignoring the read cursor; with --room, every field of every letter, no paging",
    )
    mt.add_argument(
        "--page",
        type=_page_number,
        default=0,
        metavar="N",
        help="--room in short rows, page N (1 = the newest %d letters)" % 50,
    )
    mt.add_argument(
        "--after",
        type=int,
        default=0,
        help="catch-up: letters with id > after (implies --room unless --subtree); envelope latest_id",
    )
    mk = sub.add_parser(
        "mark",
        help="mark mail ids handled for this desk",
    )
    mk.add_argument("ids", nargs="+", help="one or more mail ids")

    tr = sub.add_parser(
        "trail",
        help="read-only: the branch under a finding (mail) or card (todo), any depth, as text",
        description=(
            "Walk the tree from a mail or todo and print mail and todo children with "
            "state, title, last note, and PT time. Notes starting dead-end: or solved: "
            "are marked. Done and shipped cards stay in. --json for machines. "
            "--label NAME lists mail and todo wearing that label, by ord then created."
        ),
    )
    tr.add_argument(
        "node",
        nargs="?",
        default="",
        help="mail id or todo id (mail:N or todo:N when both exist)",
    )
    tr.add_argument(
        "--label",
        default="",
        help="list mail and todo wearing this label, by ord then created",
    )
    tr.add_argument("--json", action="store_true", dest="as_json", help="print the JSON result")

    ch = sub.add_parser(
        "clear-human",
        help=argparse.SUPPRESS,
    )
    ch.add_argument("project")
    ch.add_argument("ids", help="comma-separated mail ids")
    ch.add_argument("--human", default="", help="human badge name")
    ch.add_argument("--token", default="", help="human badge token")
    ch.add_argument(
        "--by-agent",
        action="store_true",
        default=False,
        help="agent clear only if policy allows (explicit)",
    )

    i = sub.add_parser(
        "inbox",
        help="MAIL: this desk's unread mail across projects. Not room catch-up (prefer mail-thread).",
        description=(
            "This desk's unread mailbox (since last read). The desk is the sitting connect. "
            "A fetch does not mark handled. Not room catch-up: "
            "mail-thread <latest_id> is the room read. "
            "Catch-up: --all (read mail too). "
            "Reply marks the parent; mill mark <id> marks the rest."
        ),
    )
    i.add_argument(
        "--all",
        action="store_true",
        help="print read mail too (default: unread only)",
    )
    i.add_argument(
        "--limit",
        type=int,
        default=100,
        help="max rows (default 100)",
    )
    i.add_argument(
        "--group-by",
        dest="group_by",
        default="",
        choices=("tree", "label", "roster"),
        help="group the list by tree (room) or roster (default: tree; mail has no labels yet)",
    )
    iview = i.add_mutually_exclusive_group()
    iview.add_argument(
        "--full",
        action="store_true",
        help="every field of every letter, no paging (default: short rows, 50 a page)",
    )
    iview.add_argument(
        "--page",
        type=_page_number,
        default=0,
        metavar="N",
        help="short rows, page N (1 = first); the reply's page block names the next",
    )

    kp = sub.add_parser(
        "score",
        help="a number series: score ROSTER NAME VALUE records a point; score ROSTER NAME reads latest, gap, trend; "
        "score ROSTER NAME --target N sets the target without a point",
    )
    kp.add_argument("project", metavar="ROSTER")
    kp.add_argument("name", nargs="?", default="", metavar="NAME")
    kp.add_argument("value", nargs="?", default="", metavar="VALUE")
    kp.add_argument("--target", default="", help="the number to reach (gap and met are read against it); alone, sets it without a point")
    kp.add_argument("--note", default="", help="what this try changed (one line, at most 200 characters, kept with the point)")
    kp.add_argument("--better", default="", choices=("", "up", "down"), help="up (default) or down, e.g. tokens")
    kp.add_argument("--unit", default="", help="unit shown with the points, e.g. ms, bytes, tokens")
    kp.add_argument("--limit", type=int, default=0, help="points to show on a read (default 10)")
    kp.add_argument("--at", default="", help="when the point happened: YYYY-MM-DD[THH:MM] (book clock) or 90m, 2h, 3d ago")

    sadd = sub.add_parser(
        "score-add",
        help="opt in mill-known book KPI (todo.shipped|todo.open|join.n); 15m SQL COUNT",
    )
    sadd.add_argument("name", help="todo.shipped | todo.open | join.n")
    sadd.add_argument("--target", default="0")
    sadd.add_argument("--note", default="")

    stik = sub.add_parser(
        "score-tick",
        help="measure mill-wall.ticks + mill-desk.idle_verbs from dest logs; mill score Office/Admin",
    )
    stik.add_argument("--once", action="store_true", help="measure+publish once and exit (default)")
    stik.add_argument("--loop", action="store_true", help="repeat (Windows SERVICE uses win_score_svc)")
    stik.add_argument("--every", type=int, default=900, help="loop seconds (default 900)")
    stik.add_argument("--window", type=int, default=3600, help="lookback seconds (default 3600)")
    stik.add_argument(
        "--register",
        action="store_true",
        help="write ~/.mill/mill-score-register.ps1 (elevated sc create mill-score)",
    )

    kimp = sub.add_parser(
        "kpi-import",
        help=argparse.SUPPRESS,
        description="DEPRECATED. Prefer mill score.",
    )
    kimp.add_argument("project")
    kimp.add_argument("--root", default=".")

    wall = sub.add_parser(
        "wall",
        help="wall HTTP for an OS service (observer, no mill connect)",
    )
    wall.add_argument("--bind", default=None)
    wall.add_argument("--port", type=int, default=None)
    wall.add_argument("--roots", default="", help="name=path;name=path (or AGENT_COORD_ROOTS)")
    wall.add_argument("--api-only", action="store_true")

    upd = sub.add_parser(
        "update",
        help="pip install -U the-mill from a non-git cwd; then copy the pack skill.md over mill-desk SKILL.md and restart TUI",
    )
    upd.add_argument(
        "--dry-run",
        action="store_true",
        help="print plan only; do not run pip",
    )

    ins = sub.add_parser(
        "install",
        help="write OS configs for records / wall / desk; --dry-run prints plan only; --apply enables the service",
    )
    ins.add_argument(
        "role",
        choices=["server", "client", "book", "records", "wall", "desk", "check", "cloud", "glance-tap", "sql"],
        help="server=records+wall (admin); client=mill CLI; records (alias book)/wall/desk; check; cloud runbook; "
        "sql: does the book hold this pack's SQL (--apply runs ensure, then checks)",
    )
    ins.add_argument("--apply", action="store_true", help="register/enable the OS unit when possible")
    ins.add_argument(
        "--dry-run",
        action="store_true",
        help="print preflight verdict + plan only; mutate nothing (no dest writes, no services)",
    )
    ins.add_argument(
        "--http",
        default="",
        help="wall httpd: Windows default service; else nginx. leftover caddy/iis/litespeed",
    )
    ins.add_argument("--book", default="mysql", help="records engine: mysql/mariadb (wired); postgres/sqlserver/oracle leftover")
    ins.add_argument("--provider", default="self", help="cloud provider id (aws, azure, gcp, ...) for install cloud")
    ins.add_argument("--bind", dest="dashboard_bind", default=None)
    ins.add_argument("--port", type=int, default=None)
    ins.add_argument("--dest", default="", help="write configs here (default ~/.mill)")
    _link_flags(ins)
    ins.add_argument("--lan-only", dest="lan_only", action="store_true", help="Listen on private/loopback only (not 0.0.0.0)")
    ins.add_argument("--public", dest="lan_only_off", action="store_true", help="Allow public/wildcard bind (cloud); still HTTPS-only")
    ins.add_argument(
        "--agent",
        dest="mill_agent",
        action="store_true",
        help="agent path: MILL_AGENT=1; launch Hidden UAC helper auto-exit",
    )
    ins.add_argument(
        "--tap",
        action="append",
        default=None,
        help="glance-tap: one tap value, repeat in order (prompted when omitted)",
    )
    ins.add_argument(
        "--generate",
        nargs="?",
        action=_GenerateCount,
        default=None,
        help="glance-tap: pick random keys, ask how many (Enter keeps 4, 1-16), show the symbols once, store the digest",
    )

    unins = sub.add_parser(
        "uninstall",
        help="probe-first office cleanup; short English (use --json for the object); --apply mutates",
    )
    unins.add_argument("--apply", action="store_true", help="mutate: stop/delete present SCM pieces")
    unins.add_argument(
        "--dest",
        action="store_true",
        help="wipe office dest (default ~/.mill / configured dest). Omit to leave dest.",
    )
    unins.add_argument(
        "--packages",
        action="store_true",
        help="ignored: mill uninstall is mill-wall + dest",
    )
    unins.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only; mutate nothing (default when --apply omitted)",
    )
    unins.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print full result JSON (redacted). Default is short English.",
    )
    unins.add_argument(
        "--agent",
        dest="mill_agent",
        action="store_true",
        help="agent path: MILL_AGENT=1; Hidden UAC helper auto-exit",
    )

    dr = sub.add_parser(
        "drain",
        help=argparse.SUPPRESS,
    )
    dr.add_argument("project")
    dr.add_argument(
        "--eta",
        "--eta-at",
        dest="eta_at",
        required=True,
        help="ISO eta_at (host-local or Z)",
    )
    dr.add_argument("--reason", default="", help="optional short reason")
    dr.add_argument("--down-for", dest="down_for_s", type=int, default=None, help="optional seconds")
    dr.add_argument("--drain-id", default="", help="optional drain id")
    dr.add_argument("--dst", default="*", help="MAIL dst (default *)")

    # Card 834: connect refuses a held seat by default (busy, exit 0); --take takes it.
    # -r/--refuse (#332) is kept; it is now the default.
    _REFUSE_HELP = "the default: refuse when another connect holds this desk's seat (busy, exit 0)"
    _TAKE_HELP = (
        "take the seat from the connect holding it (it exits 5, superseded); "
        "for a dead or stale seat"
    )
    cnct = sub.add_parser(
        "connect",
        help="establish desk id + sit on /ws (token from mill join). Does not write the join row.",
    )
    cnct.add_argument(
        "project",
        nargs="?",
        default="",
        help="roster (default Office). One positional is the desk.",
    )
    cnct.add_argument(
        "desk",
        nargs="?",
        default="",
        help="desk id this connect sits (required)",
    )
    cnct.add_argument(
        "--vendor",
        default="",
        help="AGENT_COORD_VENDOR for HINT poke (grok-bot, grok-build, claude, ...)",
    )
    cnct.add_argument("-r", "--refuse", dest="refuse", action="store_true", default=True, help=_REFUSE_HELP)
    cnct.add_argument("--take", dest="refuse", action="store_false", help=_TAKE_HELP)

    rt = sub.add_parser(
        "route",
        help="this-PC HINT->program map (not mill-wall). list|add|rm. See mill briefing route.",
    )
    rt_sub = rt.add_subparsers(dest="route_cmd", required=True)
    rtl = rt_sub.add_parser("list", help="print ~/.mill/session/<name>.route")

    rta = rt_sub.add_parser("add", help="mill route add KEY -- argv...  (* or mail:MAIL)")
    rta.add_argument("key", help="mail:MAIL or *")
    rta.add_argument(
        "argv",
        nargs=argparse.REMAINDER,
        help="program argv after -- (empty = suppress spawn for that HINT)",
    )

    rtr = rt_sub.add_parser("rm", help="remove a route key")
    rtr.add_argument("key")


    cnct.add_argument(
        "--session",
        default="",
        help="Grok session UUID for grok-build poke (grok -p -r). One mill desk -> one Grok session.",
    )

    cw = sub.add_parser(
        "connect-wait",
        help="connect, block until one HINT (not PING), print it as JSON, exit. No route spawn. Ctrl+C breaks out.",
    )
    cw.add_argument("project", nargs="?", default="", help="roster (default Office). One positional is the desk.")
    cw.add_argument("desk", nargs="?", default="", help="desk id this connect sits (required)")
    cw.add_argument("--vendor", default="", help="AGENT_COORD_VENDOR for HINT poke")
    cw.add_argument("--session", default="", help="Grok session UUID for grok-build poke")
    cw.add_argument("-r", "--refuse", dest="refuse", action="store_true", default=True, help=_REFUSE_HELP)
    cw.add_argument("--take", dest="refuse", action="store_false", help=_TAKE_HELP)

    rst = sub.add_parser(
        "reset",
        help="Admin: clear a desk token_hash (stamps time_disconnect), or --dead count join rows with no token",
    )
    rst.add_argument("kind", nargs="?", default="", choices=("", "seat"), help="seat")
    rst.add_argument(
        "desk",
        nargs="?",
        default="",
        help="desk whose seat to clear (omit with --dead)",
    )
    rst.add_argument("--yes", action="store_true", help="skip the prompt")
    rst.add_argument(
        "--dead",
        action="store_true",
        help="count join rows with no token_hash; deletes nothing (disconnect history stays)",
    )

    _NAME_TYPES = ("roster", "label", "desk")
    recm = sub.add_parser(
        "reclaim",
        help="undo a retire: mill reclaim TYPE NAME (Admin). "
        "mill reclaim todo ROSTER NEED brings a retired card back (asker or Admin)",
    )
    recm.add_argument("kind", metavar="TYPE", choices=_NAME_TYPES + ("todo",))
    recm.add_argument("slug", metavar="NAME", help="roster, label or desk name; for todo, the ROSTER")
    recm.add_argument("need", metavar="NEED", nargs="?", default="", help="todo form only: NEED or a comma list")
    recm.add_argument("--yes", action="store_true", help="skip the prompt")

    rnm = sub.add_parser(
        "rename",
        help="mill rename TYPE OLD NEW; you retype NEW. "
        "mill rename todo ROSTER OLD NEW changes a card's need (asker or Admin; id stays)",
    )
    rnm.add_argument("kind", metavar="TYPE", choices=_NAME_TYPES + ("todo",))
    rnm.add_argument("old", help="old name; for todo, the ROSTER")
    rnm.add_argument("new", help="new name; for todo, the OLD need")
    rnm.add_argument(
        "to",
        nargs="?",
        default="",
        metavar="NEW_NEED",
        help="todo form only: the NEW need",
    )
    rnm.add_argument(
        "--why",
        default="",
        help="todo rename: why (stored on the activity timeline)",
    )
    rnm.add_argument("--yes", action="store_true", help="skip the retype prompt")

    rtr = sub.add_parser(
        "retire",
        help="soft delete: mill retire TYPE NAME; you retype NAME. Office never. "
        "mill retire score ROSTER NAME removes a score (points kept). "
        "mill retire todo ROSTER NEED takes a card off every list (asker or Admin)",
    )
    rtr.add_argument("kind", metavar="TYPE", choices=_NAME_TYPES + ("score", "todo"))
    rtr.add_argument("slug", metavar="NAME", help="roster, label or desk name; for score or todo, the ROSTER")
    rtr.add_argument(
        "score_name", metavar="SCORE|NEED", nargs="?", default="",
        help="score form: the score NAME; todo form: NEED or a comma list",
    )
    rtr.add_argument("--yes", action="store_true", help="skip the retype prompt")

    memb = sub.add_parser("member", help="list this desk's rosters (Office first)")
    for _command, _what in (("add", "put desks on"), ("remove", "take desks off")):
        _ap = sub.add_parser(
            _command,
            help=f"mill {_command} roster NAME [d1,d2]: {_what} a roster (no desks = you). "
            f"mill {_command} TYPE:ID [WHO]: mail recipient or watcher (#265).",
        )
        _ap.add_argument("kind", metavar="TYPE", help="roster, or TYPE:ID (mail|todo|join|hold|score)")
        _ap.add_argument("group", metavar="NAME|WHO", nargs="?", default="")
        _ap.add_argument("desks", nargs="?", default="", help="roster form: comma list of desks; omit for yourself")
        if _command == "add":
            _ap.add_argument("--hint", default="", help="TYPE:ID form, watched kinds only: per-listener wake recipe")
        if _command == "remove":
            _ap.add_argument("--yes", action="store_true", help="skip the prompt")
    for _command, _what in (("watch", "wake me on"), ("unwatch", "stop waking me on")):
        _wp = sub.add_parser(_command, help=f"mill {_command} TYPE ID: {_what} a todo, hold, score or doing (self only); a todo also by ROSTER/NEED")
        _wp.add_argument("type", metavar="TYPE", choices=("todo", "hold", "score", "doing", "room"))
        _wp.add_argument("target", metavar="ID", help="activity id; a todo also by ROSTER/NEED (cold-test/fix-login)")
        if _command == "watch":
            _wp.add_argument("--hint", default="", help="per-listener wake recipe")
    lab = sub.add_parser("label", help="mill label TYPE ID NAME: tag an activity; a new label is created on first use")
    lab.add_argument("type")
    lab.add_argument("id", metavar="ID|ROSTER/NEED", help="activity id; a todo also by ROSTER/NEED")
    lab.add_argument("label")
    lab.add_argument(
        "--ord",
        type=_label_ord_arg,
        default=None,
        help="place this label: 0 pinned, 65535 unplaced. Outside 0..65535 is refused",
    )
    lrm = sub.add_parser("unlabel", help="mill unlabel TYPE ID NAME: remove a tag")
    lrm.add_argument("type")
    lrm.add_argument("id", metavar="ID|ROSTER/NEED", help="activity id; a todo also by ROSTER/NEED")
    lrm.add_argument("label")

    def _todo_create_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("project")
        p.add_argument("need")
        dg = p.add_mutually_exclusive_group()
        dg.add_argument("--detail", default="", help="card text, 1..4096 characters")
        dg.add_argument(
            "--detail-file",
            default="",
            dest="detail_file",
            metavar="PATH",
            help="card text from a UTF-8 file (same 4096 cap as a mail body)",
        )
        p.add_argument(
            "--status",
            default="open",
            help="parked|open",
        )
        p.add_argument(
            "--parent-type",
            default="",
            dest="parent_type",
            help="optional TREE parent type (attach on create)",
        )
        p.add_argument(
            "--parent-id",
            type=int,
            default=None,
            dest="parent_id",
            help="optional TREE parent id (attach on create)",
        )
        p.add_argument(
            "--done-when",
            default=None,
            dest="done_when",
            help="acceptance line, 0..1000 chars; the asker or Admin",
        )

    cr = sub.add_parser(
        "create",
        help="mill create todo ROSTER NEED | mill create roster NAME | mill create label NAME",
    )
    cr_sub = cr.add_subparsers(dest="object", required=True)
    _ct = cr_sub.add_parser("todo", help="file a card")
    _todo_create_args(_ct)
    _ct.add_argument("--yes", action="store_true", help="accepted for symmetry; create todo never prompts")
    for _obj in ("roster", "label"):
        _cp = cr_sub.add_parser(_obj, help=f"create a {_obj} name (type it once; prompt unless --yes)")
        _cp.add_argument("slug", metavar="NAME")
        _cp.add_argument("--yes", action="store_true", help="skip the prompt")

    nd = sub.add_parser(
        "todo",
        help="list cards in short rows, 50 a page (optional NEED peek)",
        description="List cards: short rows (id, need, status, volunteer), 50 a page; "
        "--page N reads page N, --full prints every field of every card; "
        "--mine lists this desk's focus cards in rank order, then the ones it volunteered for.",
    )
    nd.add_argument("project", nargs="?", default="")
    nd.add_argument(
        "--group-by",
        dest="group_by",
        default="",
        choices=("tree", "label", "roster"),
        help="group the list by tree (plan), label or roster (default: tree)",
    )
    nd.add_argument(
        "need",
        nargs="?",
        default="",
        help="optional need_id peek - one card, not the whole board",
    )
    nd.add_argument("--done", action="store_true", help="include finished needs")
    nd.add_argument(
        "--mine",
        action="store_true",
        help="this desk's cards (the sitting mill connect): first its focus cards (label named after the desk) in rank order, "
        "then the cards it volunteered for; works with --status, --done, --all, --find, --full and --page, "
        "and pages count only these cards",
    )
    nd.add_argument("--all", action="store_true", help="every roster in the office (default: your rosters)")
    nd.add_argument(
        "--find",
        default="",
        metavar="TEXT",
        help="only cards whose roster, need or detail contains TEXT (any case, 1..64 chars)",
    )
    nd.add_argument(
        "--status",
        default="",
        help="filter cards: parked|open|claimed|shipped|done (protocol todo)",
    )
    view = nd.add_mutually_exclusive_group()
    view.add_argument(
        "--full",
        action="store_true",
        help="every field of every card, no paging (default: short rows, 50 a page)",
    )
    view.add_argument(
        "--page",
        type=_page_number,
        default=0,
        metavar="N",
        help="short rows, page N (1 = first); the reply's page block names the next",
    )
    nd.add_argument(
        "--fixtures",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    pg = sub.add_parser(
        "note",
        help="update a claimed card body/pct",
    )
    pg.add_argument("project")
    pg.add_argument("need")
    pg.add_argument(
        "text",
        nargs="?",
        default="",
        help="9/12, 75%%, done or git <sha> = progress; other text = diary line; @file reads a file",
    )
    pg.add_argument("--note", default="")
    pg.add_argument(
        "--supersedes",
        default=None,
        metavar="OLD_LINE",
        help="asker or Admin: mark this exact detail line superseded and put --note under it",
    )
    pg.add_argument("--eta", default="", help="20m / 2h / datetime so the other desk can see when you expect to finish")
    pg.add_argument("--started", action="store_true", help="set started_at to now")
    pg.add_argument(
        "--full",
        action="store_true",
        help="reply with the card's whole detail (default: detail_chars and the last line)",
    )
    pg.add_argument(
        "--done-when",
        default=None,
        dest="done_when",
        help="set or clear the acceptance line (asker or Admin); a blank value clears it",
    )

    vo = sub.add_parser("claim", help="claim a card")
    vo.add_argument("project")
    vo.add_argument("need")
    vo.add_argument("--eta", default="", help="20m / 2h / datetime; a bad value is refused")
    vo.add_argument("--msg", default="", help="note on the card, at most 4096 characters")
    vo.add_argument(
        "--take-over",
        action="store_true",
        dest="take_over",
        help="take a card another desk holds; the card records the prior volunteer",
    )

    yd = sub.add_parser(
        "unclaim",
        help="drop the claim; card is open again (not mill drop hold)",
    )
    yd.add_argument("project")
    yd.add_argument("need")

    unp = sub.add_parser("unpark", help="parked -> open (protocol unpark)")
    unp.add_argument("project")
    unp.add_argument("need")
    unp.add_argument(
        "--parent-type",
        choices=("mail", "todo"),
        default="",
        dest="parent_type",
        help="TREE parent type to attach the card under (mail|todo)",
    )
    unp.add_argument(
        "--parent-id",
        type=int,
        default=None,
        dest="parent_id",
        help="TREE parent id to attach the card under",
    )

    _assign_help = (
        "Put DESK on an unassigned card: mill assign ROSTER NEED DESK. A claimed card is"
        " refused; to hand off your own card, unclaim it first. Trust: high any desk, limited Admin."
    )
    asn = sub.add_parser("assign", help=_assign_help, description=_assign_help)
    asn.add_argument("project")
    asn.add_argument("need")
    asn.add_argument("desk")

    psd = sub.add_parser(
        "pass",
        help="claimed -> shipped (volunteer); --done: shipped -> done (asker); --back: one step back",
    )
    psd.add_argument("project")
    psd.add_argument("need", help="NEED, or a comma list (a,b,c): one result row per card")
    pstep = psd.add_mutually_exclusive_group()
    pstep.add_argument("--done", action="store_true", help="asker or Admin: accept a shipped card (shipped -> done)")
    pstep.add_argument("--back", action="store_true", help="asker or volunteer: done -> shipped, shipped -> claimed")
    psd.add_argument(
        "--evidence",
        default="",
        help="text stored with a ship or a done step (0..2000 chars); --back stores none",
    )
    sub.add_parser(
        "glance",
        help="office glance from the cached read: one summary row and the newest activity",
    )

    inv = sub.add_parser(
        "invite",
        help="office door + invite key board: path|invite; mint/list/revoke/TTL; OIDC stub elsewhere",
    )
    inv.add_argument("--door", choices=["path", "ip", "invite"], default="", help="set door mode (ip = LAN CIDR, no invite passphrase)")
    inv.add_argument("--rotate", action="store_true", help="mint a new invite token (prints once)")
    inv.add_argument("--mint", action="store_true", help="mint a pending invite (prints URL once; host --enable before mill join)")
    inv.add_argument("--enable", default="", metavar="KEY", help="enable a pending invite key_id so mill join can finish")
    inv.add_argument("--list", action="store_true", dest="invite_list", help="list invite keys (pending/active/expired/revoked)")
    inv.add_argument("--revoke", default="", metavar="KEY", help="revoke key_id")
    inv.add_argument("--ttl", default="", metavar="TTL", help="with --mint: duration (7d/24h); or KEY then DURATION via --for")
    inv.add_argument("--for", dest="ttl_for", default="", metavar="KEY", help="key_id when setting TTL (invite --ttl 7d --for KEY)")
    inv.add_argument("--seat", default="", metavar="DESK", help="mint one-seat agent invite URL for DESK (ready; trust-gated)")
    inv.add_argument(
        "--roster",
        default="",
        dest="seat_roster",
        metavar="ROSTER",
        help="with --seat: seat roster (default: that desk's one non-Office roster)",
    )
    inv.add_argument("--label", default="", help="label for --mint")
    inv.add_argument(
        "--link-file",
        default="",
        dest="link_file",
        metavar="PATH",
        help="with --seat/--mint/--rotate: write the link here (owner-only; default under ~/.mill/invites)",
    )
    inv.add_argument(
        "--print-link",
        action="store_true",
        dest="print_link",
        help="print the secret link on stdout instead of writing a file",
    )
    inv.add_argument("--join", default="", metavar="KEY", help="record a join under key_id")
    inv.add_argument("--party", choices=["human", "agent"], default="human", help="with --join")
    inv.add_argument("party_id", nargs="?", default="", help="human/agent id for --join")
    inv.add_argument("--lan-only", nargs="?", const="on", default=None, help="on|off - LAN-only bind (private interfaces); persist + note re-install wall")

    ad = sub.add_parser(
        "admin",
        help=argparse.SUPPRESS,
    )
    ad.add_argument("owner", nargs="?", default="", help="target desk to add as admin (blank = list); actor = connect session")
    ad.add_argument("--by", default="", help="who is assigning (default: active from mill connect)")

    se = sub.add_parser(
        "connected",
        help="mill connected [ROSTER] [--desk X] [--limit N]: what each desk is doing, on which letter or card, "
        "what it waits on and who is blocked on it; --history lists past entries",
    )
    se.add_argument(
        "project", nargs="?", default="", metavar="ROSTER",
        help="only desks on this roster (default: desks active in the last day)",
    )
    se.add_argument("--desk", default="", help="only this desk")
    se.add_argument("--all", action="store_true", help="every desk, not only those active in the last day")
    se.add_argument("--history", action="store_true", help="past doing entries, newest first, 50 a page")
    se.add_argument("--since", default="", metavar="DATE", help="with --history: entries from DATE on (office clock)")
    se.add_argument("--page", type=int, default=0, help="with --history: page N")
    se.add_argument(
        "--limit",
        type=int,
        default=None,
        help="at most N desks on the live list, newest heartbeat first",
    )

    att = sub.add_parser(
        "attach",
        help="put child under parent (hidden plan name). type_a/id_a parent, type_b/id_b child. --tree if on two plans",
    )
    att.add_argument("project")
    att.add_argument("type_a", nargs="?", default="")
    att.add_argument("id_a", nargs="?", default=None, help="parent id; a todo also by ROSTER/NEED")
    att.add_argument("type_b", nargs="?", default="")
    att.add_argument("id_b", nargs="?", default=None, help="child id; a todo also by ROSTER/NEED")
    att.add_argument("--tree", default="", help="plan name when the card is on more than one plan")

    mv = sub.add_parser(
        "move",
        help="move that under that (same plan). --tree if on two plans",
    )
    mv.add_argument("project")
    mv.add_argument("type", nargs="?", default="")
    mv.add_argument("id", nargs="?", default=None, help="id; a todo also by ROSTER/NEED")
    mv.add_argument("parent_type", nargs="?", default="")
    mv.add_argument("parent_id", nargs="?", default=None, help="parent id; a todo also by ROSTER/NEED")
    mv.add_argument("--tree", default="")

    prn = sub.add_parser("prune", help="kill that branch")
    prn.add_argument("project")
    prn.add_argument("type", nargs="?", default="")
    prn.add_argument("id", nargs="?", default=None, help="id; a todo also by ROSTER/NEED")
    prn.add_argument("--tree", default="")

    det = sub.add_parser("detach", help="take off the plan, keep children")
    det.add_argument("project")
    det.add_argument("type", nargs="?", default="")
    det.add_argument("id", nargs="?", default=None, help="id; a todo also by ROSTER/NEED")
    det.add_argument("--tree", default="")

    wchk = sub.add_parser(
        "wall-check",
        help="compare Wall HTML + Office agents vs a stale ?projects= filter; cheap JSON, no dump",
    )
    wchk.add_argument("--base", default="", help="https://office/ (default share_wall_urls)")
    wchk.add_argument(
        "--filter",
        dest="project_filter",
        default="the-mill",
        help="stale product id to compare (default the-mill)",
    )
    wchk.add_argument(
        "--expect-empty",
        action="store_true",
        help="exit 2 when filter zeros a live office",
    )

    wsrc = sub.add_parser(
        "wall-src",
        help="point mill www at pip mill or git wall_ui (MILL_WALL_SRC, MILL_GIT_ROOT)",
    )
    wsrc.add_argument("src", nargs="?", default="", help="pip or git (default: show current)")
    wsrc.add_argument("--apply", action="store_true", help="copy files to dest/www and recycle mill-wall")
    wsrc.add_argument("--git-root", default="", help="mill checkout (default MILL_GIT_ROOT or walk)")
    wsrc.add_argument("--dest", default="", help="office dest (default ~/.mill)")

    jn = sub.add_parser(
        "join",
        help="mill join --link-file PATH (the seat welcome link, from a file or stdin; never on the command line)",
        usage="mill join --link-file PATH | --link-stdin [--webhook-url URL --webhook-key-file PATH] | mill join DESK (--webhook-... | --websocket)",
        description="Join an office with a seat welcome link read from a file (--link-file PATH, "
        "the file mill invite writes) or stdin (--link-stdin). The link carries the seat secret, "
        "so a link on the command line is refused. "
        "The office alias defaults to the link's host and becomes the default office; "
        "--office ALIAS picks another local name. Then run the printed next: line.",
    )
    jn.add_argument(
        "link",
        nargs="?",
        default="",
        metavar="DESK",
        help="a desk seated on this machine, to change its delivery (never the welcome link)",
    )
    # #620: the welcome link carries the seat secret: a file or stdin, never argv.
    jn.add_argument("--link-file", default="", metavar="PATH", help="a file holding the seat welcome link (mill invite writes one)")
    jn.add_argument("--link-stdin", action="store_true", help="read the seat welcome link from stdin")
    # #618: join picks the desk's delivery. Plain join = websocket; the webhook
    # options = the wall POSTs a wake while the desk's connect is down.
    jn.add_argument("--webhook-url", default="", help="the routine's https webhook URL")
    jn.add_argument("--webhook-url-file", default="", help="a file holding the webhook URL")
    jn.add_argument("--webhook-key-file", default="", help="a file holding the webhook key (or its Authorization line)")
    jn.add_argument("--webhook-key-env", default="", help="the NAME of an env var holding the webhook key")
    jn.add_argument("--webhook-key-stdin", action="store_true", help="read the webhook key from stdin")
    # Refused with a plain line; never echoed (argparse would print an unknown flag's value).
    jn.add_argument("--webhook-key", default=None, help=argparse.SUPPRESS)
    jn.add_argument("--websocket", action="store_true", help="switch the desk back to websocket only (forget the webhook)")
    # #628: which items wake this desk. addressed: room-only letters wait for its next connect.
    jn.add_argument("--wake-on", default="", choices=("addressed", "all"),
                    help="with the webhook options: wake only for items addressed to this desk (addressed, the default) or for room copies too (all)")

    sub.add_parser(
        "local",
        help="list servers on this machine and the local alias for each",
    )
    trust = sub.add_parser(
        "trust",
        help="show office trust, or set high or limited (Admin, via the wall)",
    )
    trust.add_argument("level", nargs="?", default="", help="high or limited")

    sub._choices_actions = [
        a
        for a in sub._choices_actions
        if getattr(a, "help", None) not in (argparse.SUPPRESS, "==SUPPRESS==")
    ]
    _attach_office_help(p)
    _no_abbrev(p)
    _yes_everywhere(p)
    # #818 PR B: every activity write takes --doing; the doing entry links to the
    # item that command wrote (no separate doing command).
    for _name in DOING_FLAG_COMMANDS:
        _dp = _ct if _name == "create" else sub.choices[_name]
        _dp.add_argument("--doing", default="", metavar="TEXT", help=DOING_HELP)
        _dp.add_argument("--waiting-on", dest="waiting_on", default="", metavar="WHAT [WHY]", help=WAITING_ON_HELP)
    return p


def _yes_everywhere(parser: argparse.ArgumentParser, top: bool = True) -> None:
    """Every command takes --yes (0.7.x): it skips a prompt, or is a no-op where none exists."""
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for child in act.choices.values():
                has_sub = any(isinstance(a, argparse._SubParsersAction) for a in child._actions)
                if not has_sub and "--yes" not in child._option_string_actions:
                    child.add_argument(
                        "--yes", action="store_true", help="skip any prompt (this command has none)"
                    )
                _yes_everywhere(child, top=False)


def _no_abbrev(parser: argparse.ArgumentParser) -> None:
    """Whole flags only (#254): a removed flag must not resolve as a prefix of a kept one.

    0.7.0: a positional stored as project is shown as roster (one name type).
    """
    parser.allow_abbrev = False
    for act in parser._actions:
        if not act.option_strings and act.dest == "project" and act.metavar is None:
            act.metavar = "roster"
        if isinstance(act, argparse._SubParsersAction):
            for child in act.choices.values():
                _no_abbrev(child)


def _subparser(p: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    """The named command's parser, found on the built parser."""
    for act in p._actions:
        if isinstance(act, argparse._SubParsersAction) and name in act.choices:
            return act.choices[name]
    raise KeyError(name)


def _run_parsed(p: MillArgumentParser, argv: list[str] | None) -> int:
    from agent_coord.helpers.errors import CoordError

    raw = consume_mill_agent(argv)
    if raw and raw[0] in ("-V", "--version"):
        from agent_coord.install.packver import version_line

        print(version_line(), flush=True)
        return 0
    from agent_coord.client.offices import bind_cli_office, pull_office_flag

    _office, raw = pull_office_flag(list(raw))
    bind_cli_office(_office)
    args = p.parse_args(normalize_seat_argv(raw))
    if bool(getattr(args, "verbose", False)):
        import os as _dbg_os

        _dbg_os.environ["AGENT_COORD_DEBUG"] = "1"
    if bool(getattr(args, "version", False)) and not args.cmd:
        from agent_coord.install.packver import version_line

        print(version_line(), flush=True)
        return 0
    if not args.cmd:
        p.error("the following arguments are required: cmd")
    from agent_coord.client.grouping import refusal as _group_refusal

    _never = _group_refusal(str(args.cmd), str(getattr(args, "group_by", "") or ""))
    if _never:
        # A --group-by that can never apply to this list (#274): one line, exit 2.
        print(_never, file=sys.stderr, flush=True)
        return 2
    if args.cmd == "mail-thread" and bool(getattr(args, "full", False)) and getattr(args, "scope", "") == "subtree":
        # --full was one scope with --subtree before #295; the pair stays a usage error.
        p.error("mail-thread: argument --full: not allowed with argument --subtree")
    if args.cmd == "mail-thread" and bool(getattr(args, "full", False)) and int(getattr(args, "page", 0) or 0):
        p.error("mail-thread: argument --page: not allowed with argument --full")
    try:
        from agent_coord.client.language import translate

        args = translate(args)
    except (CoordError, ValueError) as e:
        print(_format_error(e), file=sys.stderr)
        return 1
    try:
        from agent_coord.client.tokens import apply_session_token_env

        apply_session_token_env(None)
        if args.cmd == "help":
            from agent_coord.install.office import help_text

            text = help_text(getattr(args, "command", "") or "")
            if text.startswith("mill help: no such topic"):
                sys.stderr.write(text)
                return 2
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
            return 0
        
        if args.cmd == "briefing":
            from agent_coord.install.office import briefing_text

            text = briefing_text(getattr(args, "kind", "") or "")
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
            return 0
        if args.cmd == "init":
            from pathlib import Path

            from agent_coord.install.office import gather, init_office

            data = gather(
                host=args.host,
                port=args.port,
                user=args.user,
                password=args.password,
                database=args.database,
                node=args.node,
                dashboard_bind=args.dashboard_bind,
                dashboard_port=args.dashboard_port,
                lan=args.lan,
                prompt=not args.yes,
            )
            result = init_office(data, path=Path(args.config_path) if args.config_path else None)
            _print_install(args, result)
            return 0
        if args.cmd == "update":
            from .install import run_update

            result = run_update(apply=not bool(getattr(args, "dry_run", False)))
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "install" and args.role == "sql":
            # #614: the book's SQL against this pack. --apply runs ensure on the configured book.
            from agent_coord.install.migrate import install_sql
            from agent_coord.server.records.db import connect

            cn = connect()
            try:
                result = install_sql(cn, apply=bool(args.apply))
            finally:
                cn.close()
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "install" and args.role == "glance-tap":
            from agent_coord.install.glance_tap import configure_cli

            result = configure_cli(
                taps=list(args.tap or []),
                dest=args.dest or "",
                generate=args.generate,
            )
            _print(result)
            return 0 if result.get("ok") else 1
        if args.cmd == "install":
            from pathlib import Path

            from .install import write_role

            if bool(getattr(args, "mill_agent", False)):
                import os as _os

                _os.environ["MILL_AGENT"] = "1"
            want_lan = bool(getattr(args, "lan_only", False))
            want_public = bool(getattr(args, "lan_only_off", False))
            if want_lan and want_public:
                _print({
                    "ok": False,
                    "error": "--public and --lan-only are mutually exclusive",
                    "mutated": False,
                })
                return 1
            lan_only = True if want_lan else (False if want_public else None)
            result = write_role(
                args.role,
                dest=Path(args.dest) if args.dest else None,
                http=args.http,
                apply=args.apply,
                dry_run=bool(getattr(args, "dry_run", False)),
                agent=bool(getattr(args, "mill_agent", False)),
                bind=args.dashboard_bind,
                port=args.port,
                book=getattr(args, "book", "mysql"),
                provider=getattr(args, "provider", "self"),
                lan_only=lan_only,
                public=want_public,
            )
            _print_install(args, result)
            return 0 if result.get("ok") else 1
        if args.cmd == "uninstall":
            from .install import uninstall

            if bool(getattr(args, "mill_agent", False)):
                import os as _os

                _os.environ["MILL_AGENT"] = "1"
            apply = bool(getattr(args, "apply", False))
            dry_run = bool(getattr(args, "dry_run", False))
            if dry_run and apply:
                _print({
                    "ok": False,
                    "dry_run": True,
                    "mutated": False,
                    "warnings": ["--dry-run and --apply are mutually exclusive"],
                })
                return 1
            result = uninstall(
                apply=apply and not dry_run,
                dest=bool(getattr(args, "dest", False)),
                packages=bool(getattr(args, "packages", False)),
            )
            if bool(getattr(args, "as_json", False)):
                _print(result)
            else:
                from .install import format_uninstall_lines

                print("\n".join(format_uninstall_lines(result)))
            return 0 if result.get("ok") else 1
        if args.cmd == "wall":
            from agent_coord.server.records.driver import ensure_c_path

            ensure_c_path()  # C driver by default; restarts once on the OpenSSL clash (F34)
            from .config import settings
            from agent_coord.lib.observe import parse_roots
            from agent_coord.server.asgi import run_uvicorn

            s = settings()
            host = args.bind or s["dashboard_bind"]
            port = int(s["dashboard_port"] if args.port is None else args.port)
            run_uvicorn(
                host,
                port,
                parse_roots(args.roots or None),
                api_only=bool(getattr(args, "api_only", False)),
            )
            return 0
            print("mill watch: list|add|rm", file=sys.stderr, flush=True)
            return 1
        if args.cmd == "route":
            import shlex

            from agent_coord.client.route_chain import add_route, list_lines, rm_route, route_path

            from agent_coord.client.tokens import resolve_desk_owner
            from agent_coord.client.ws import wait_for_sitting_desk

            # Like the RPC commands: wait for a connect started just before in this shell (#358).
            owner = resolve_desk_owner("") or wait_for_sitting_desk()
            if not owner:
                print("mill route: mill connect DESK first", file=sys.stderr, flush=True)
                return 1
            subc = getattr(args, "route_cmd", "") or ""
            if subc == "list":
                lines = list_lines(owner)
                for line in lines:
                    print(line, flush=True)
                _print({"ok": True, "desk": owner, "path": str(route_path(owner)), "routes": lines})
                return 0
            if subc == "add":
                key = str(args.key or "").strip()
                if not key:
                    print("mill route add: key required", file=sys.stderr, flush=True)
                    return 1
                argv = list(getattr(args, "argv", None) or [])
                if argv and argv[0] == "--":
                    argv = argv[1:]
                # REMAINDER may keep leading --
                while argv and argv[0] == "--":
                    argv = argv[1:]
                val = (__import__('subprocess').list2cmdline(argv) if os.name == 'nt' else shlex.join(argv))
                if not argv:
                    val = ""
                path = add_route(owner, key, val)
                _print({"ok": True, "desk": owner, "key": key, "argv": val, "path": str(path)})
                return 0
            if subc == "rm":
                key = str(args.key or "").strip()
                try:
                    path = rm_route(owner, key)
                except KeyError:
                    _print_err({"ok": False, "error": f"no route {key!r}", "desk": owner})
                    return 1
                _print({"ok": True, "desk": owner, "removed": key, "path": str(path)})
                return 0
            print("mill route: list|add|rm", file=sys.stderr, flush=True)
            return 1
        if args.cmd == "connect-wait":
            args.cmd = "connect"
            args.foreground = True
        if args.cmd == "connect":
            from agent_coord.client.offices import (
                current_office,
                looks_like_host,
                write_global_active,
            )
            from agent_coord.client.http import mill_here_over_http, mill_url

            project = str(getattr(args, "project", "") or "").strip()
            desk = str(getattr(args, "desk", "") or "").strip()
            for word in (project, desk):
                if word and looks_like_host(word):
                    # The wall is chosen at join under --office, never per connect.
                    print(
                        f"mill connect: {word[:64]!r} looks like a host; "
                        "name the wall with --office ALIAS (set at mill join)",
                        file=sys.stderr,
                        flush=True,
                    )
                    return 2
            _off = current_office()
            if _off:
                try:
                    write_global_active(_off)
                except ValueError as exc:
                    print(str(exc), file=sys.stderr, flush=True)
                    return 1

            # One positional used to bind as project and then report desk required (#250).
            if not desk and project:
                desk = project
                project = ""
                args.desk = desk
                args.project = ""

            # #489: shared config.toml node= must not linger across desks
            try:
                from agent_coord.config import clear_shared_node_if_owner

                clear_shared_node_if_owner(desk)
            except Exception:
                pass
            if not mill_url():
                print("mill join https://<wall>/ first (mill CLI is mill-wall-only)", file=sys.stderr, flush=True)
                return 1
            if not desk:
                return _connect_json_error("mill connect: desk required", "")
            from agent_coord.client.tokens import read_session_token
            from agent_coord.helpers.ident import desk_name as _desk_name

            _who = _desk_name(desk)
            if _who and not read_session_token(_who).strip():
                # #281: no seat here. One line for a roster or an unknown name alike;
                # no server lookup, so the refusal never tells which names exist.
                print(seatless_connect_line(_who), file=sys.stderr, flush=True)
                return 2
            if not project:
                # 0.7.x: no roster named = the Office roster; a named roster overrides it.
                from agent_coord.const import CONST_OFFICE

                project = CONST_OFFICE
                args.project = project
            args.desk = desk
            print(
                "mill connect: %s on roster %s; connecting (a ready line follows)" % (desk, project),
                file=sys.stderr,
                flush=True,
            )
            return mill_here_over_http(args)
        if args.cmd == "wall-check":
            from agent_coord.client.offices import cli_office, origin_url, read_alias
            from agent_coord.server.wall_check import wall_check

            base = getattr(args, "base", "") or ""
            office = cli_office()
            if office and not base:
                try:
                    host = read_alias(office)
                except ValueError:
                    host = ""
                if not host:
                    _print_err(
                        {
                            "ok": False,
                            "error": "wall-check: --office %s has no local alias; pass --base" % office,
                        }
                    )
                    return 1
                base = origin_url(host)
                if not base:
                    _print_err(
                        {
                            "ok": False,
                            "error": "wall-check: --office %s has no Wall URL; pass --base" % office,
                        }
                    )
                    return 1
            row, code = wall_check(
                base=base,
                project_filter=getattr(args, "project_filter", None) or "the-mill",
                expect_empty=bool(getattr(args, "expect_empty", False)),
            )
            _print(row)
            return code
        if args.cmd == "score-add":
            from agent_coord.server.score_tick import score_add

            row = score_add(
                str(args.name or ""),
                target=str(getattr(args, "target", "") or "0"),
                note=str(getattr(args, "note", "") or ""),
            )
            _print(row)
            return 0 if row.get("ok") else 1
        if args.cmd == "score-tick":
            from agent_coord.config import mill_home
            from agent_coord.server.score_tick import run_loop, tick
            from agent_coord.server.win_score_svc import register_ps1

            if getattr(args, "register", False):
                dest = mill_home()
                dest.mkdir(parents=True, exist_ok=True)
                ps1 = dest / "mill-score-register.ps1"
                ps1.write_text(register_ps1(), encoding="utf-8")
                _print(
                    {
                        "ok": True,
                        "ps1": str(ps1),
                        "svc": "mill-score",
                        "run": "elevated: powershell -File " + str(ps1),
                    }
                )
                return 0
            if getattr(args, "loop", False):
                return run_loop(every_s=int(args.every or 900), window_s=int(args.window or 3600))
            _print(tick(window_s=int(args.window or 3600)))
            return 0
        if args.cmd == "wall-src":
            from pathlib import Path as _P

            from .install import mill_wall_src, switch_wall_src

            src = (getattr(args, "src", None) or "").strip()
            if not src:
                _print({"src": mill_wall_src(), "env": "MILL_WALL_SRC", "git": "MILL_GIT_ROOT"})
                return 0
            row = switch_wall_src(
                src,
                dest=_P(args.dest) if args.dest else None,
                git_root=args.git_root or None,
                apply=bool(args.apply),
            )
            _print(row)
            return 0 if row.get("ok") else 1
        from agent_coord.helpers.errors import CoordError
        from agent_coord.client.http import mill_http_from_args, mill_url
        from .config import settings as _settings

        host_cmds = (
            "join",
            "wall-src",
            "install",
            "init",
            "update",
            "score-tick",
            "score-add",
        )
        if args.cmd == "invite":
            return _invite_cmd(args)
        if args.cmd == "local":
            from agent_coord.client.offices import local_servers

            rows = local_servers()
            if not rows:
                print("no office aliases", flush=True)
                return 0
            for row in rows:
                aliases = ", ".join(row["aliases"])
                mark = "  active" if row["active"] else ""
                print(f"{row['host']}  {aliases}{mark}", flush=True)
            return 0
        if args.cmd not in host_cmds:
            if not (mill_url() or str(_settings().get("mill_url") or "").strip()):
                print("mill join https://<wall>/ first (mill CLI is mill-wall-only)", file=sys.stderr, flush=True)
                return 1
            try:
                batch = list(getattr(args, "batch_desks", None) or [])
                if len(batch) > 1:
                    rc = 0
                    for one in batch:
                        args.desk = one
                        rc = max(rc, mill_http_from_args(args))
                    return rc
                return mill_http_from_args(args)
            except CoordError as e:
                print(str(e), file=sys.stderr, flush=True)
                return 1
        if args.cmd == "join":
            from agent_coord.client.offices import (
                alias_from_link,
                cli_office,
                current_office,
                join_office,
                next_connect_line,
            )

            from agent_coord.client import wake_cli as _wake
            from agent_coord.client.offices import LINK_ON_ARGV, looks_like_link, read_link

            desk_arg = (getattr(args, "link", None) or "").strip()
            link_file = str(getattr(args, "link_file", "") or "").strip()
            link_stdin = bool(getattr(args, "link_stdin", False))
            if looks_like_link(desk_arg):
                # #620: the link holds the seat secret. Refuse it on argv; never echo it.
                print(LINK_ON_ARGV, file=sys.stderr, flush=True)
                return 2
            if link_file and link_stdin:
                print("join: pick one: --link-file PATH or --link-stdin", file=sys.stderr, flush=True)
                return 2
            if (link_file or link_stdin) and desk_arg:
                print(
                    "join: either a welcome link (--link-file / --link-stdin) or a seated DESK, not both",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
            if link_stdin and getattr(args, "webhook_key_stdin", False):
                print(
                    "join: stdin carries one value: the link (--link-stdin) or the key (--webhook-key-stdin); "
                    "put the other in a file",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
            try:
                _deliv = _wake.delivery_body(args)
            except CoordError as e:
                print(str(e), file=sys.stderr, flush=True)
                return 2
            if desk_arg and _deliv is not None:
                # #618: `mill join DESK --webhook-...` or `--websocket`: a desk seated on this
                # machine changes its own delivery with no new link; its seat token is the auth.
                return _wake.run_seated(desk_arg, _deliv)
            # `mill join join ...` used to ignore the extra word and exit 0 (#157).
            if desk_arg.lower() in ("join", "mill"):
                _print_err(
                    {
                        "ok": False,
                        "error": (
                            "mill join: drop the extra join word; "
                            "pass the seat welcome link with --link-file PATH"
                        ),
                    }
                )
                return 1
            if desk_arg:
                print(
                    f"join: {desk_arg[:64]} changes a seated desk's delivery: add --webhook-url-file and "
                    "--webhook-key-file, or --websocket; a new seat joins with --link-file PATH",
                    file=sys.stderr,
                    flush=True,
                )
                return 1
            if not (link_file or link_stdin):
                print(
                    "join: need a seat welcome link: mill join --link-file PATH (the file mill invite wrote), "
                    "or mill join --link-stdin",
                    file=sys.stderr,
                )
                print(_subparser(p, "join").format_usage(), file=sys.stderr, end="")
                return 1
            try:
                link = read_link(link_file, sys.stdin if link_stdin else None)
            except ValueError as e:
                print(str(e), file=sys.stderr, flush=True)
                return 2
            explicit = (cli_office() or "").strip()
            office = explicit or alias_from_link(link) or (current_office() or "").strip()
            if not office:
                print("join: could not read a host from the link; check the link file, or pass --office ALIAS", file=sys.stderr)
                return 1
            row = join_office(link, office)
            if row.get("ok") and not explicit:
                # No --office: this office becomes the default for later commands.
                try:
                    from agent_coord.client.offices import write_global_active

                    write_global_active(office)
                    row["next"] = next_connect_line("", "", str(row.get("desk") or ""))
                except (OSError, ValueError) as e:
                    # Join stands; later commands need --office (#274). The next line keeps it.
                    print(
                        f"join: joined, but could not save {office} as the default office ({e}); "
                        f"pass --office {office} on later commands",
                        file=sys.stderr,
                        flush=True,
                    )
            if row.get("ok"):
                # next: is printed once, as its own line after the JSON (#274).
                line = str(row.pop("next", "") or "").strip()
                _print(row)
                rc = 0
                if _deliv is not None:
                    rc = _wake.run_seated(str(row.get("desk") or ""), _deliv)
                if line:
                    print(line, flush=True)
                return rc
            _print_err(row)
            return 1
        print("unknown mill cmd", getattr(args, "cmd", ""), flush=True)
        return 1
    except (CoordError, RuntimeError, ValueError) as e:
        print(_format_error(e), file=sys.stderr)
        return 1
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
