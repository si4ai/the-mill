# -*- coding: utf-8 -*-
"""Hold /ws until a non-empty kind:sync queue or the next hint.

Reads the seat token already stored by mill join. Does not join, does not
install a CA, and does not run mill connect-wait.
"""
from __future__ import annotations

import argparse
import json
import sys

from agent_coord.client.offices import bind_cli_office, pull_office_flag
from agent_coord.client.tokens import read_session_token
from agent_coord.client.ws import wait_one_hint
from agent_coord.helpers.ident import desk_name


def main(argv: list[str] | None = None) -> int:
    """Sit on /ws. Print a non-empty sync list, or the next hint, and exit 0."""
    raw = list(sys.argv[1:] if argv is None else argv)
    office, raw = pull_office_flag(raw)
    bind_cli_office(office)
    parser = argparse.ArgumentParser(
        prog="mill-hold",
        description="Hold /ws. Empty kind:sync stays up. A non-empty queue prints and exits.",
    )
    parser.add_argument("project", nargs="?", default="the-mill")
    parser.add_argument("desk", nargs="?", default="")
    args = parser.parse_args(raw)
    who = desk_name(str(args.desk or ""))
    if not who:
        print(
            json.dumps({"ok": False, "error": "mill-hold: desk required", "desk": ""}, default=str),
            flush=True,
        )
        return 1
    try:
        tok = read_session_token(who).strip()
    except ValueError:
        tok = ""
    if not tok:
        print(
            json.dumps(
                {"ok": False, "error": "no session token; mill join first", "desk": who},
                default=str,
            ),
            flush=True,
        )
        return 1
    try:
        got = wait_one_hint(
            who,
            tok,
            skip_ping=True,
            timeout_s=None,
            skip_kinds=(),
            hold_empty_sync=True,
        )
    except KeyboardInterrupt:
        print(
            json.dumps({"ok": False, "error": "interrupted", "desk": who}, default=str),
            flush=True,
        )
        return 130
    if not got.get("ok"):
        print(json.dumps(got, default=str), flush=True)
        return 1
    hint = got.get("hint")
    if isinstance(hint, dict):
        from agent_coord.client.older import attach_older_once

        hint = attach_older_once(hint)
    print(json.dumps(hint, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
