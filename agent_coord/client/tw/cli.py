# -*- coding: utf-8 -*-
"""tw CMD ARGS. End a run by killing the printed pid (taskkill on windows). The desk is the sitting connect, not a flag."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

from agent_coord.client.tw.proc import running_runs, run_argv

_HELP = """\
usage: tw CMD ARGS
       tw --card N --pr N CMD ARGS
       tw
       tw --help
       tw -h
       tw --version
       tw -V
       tw --list
       tw -l
       tw --list-json

run CMD while this process shares a parent with a sitting connect.
one stderr line at start is the watch id, this pid, and the log path.
the command output passes through and is copied to the log.
tw exits with the command exit code.
with no arguments, print this help.
--list and -l list this desk's running runs.
--list-json prints that list as one JSON object per run.
--card N and --pr N are leading flags. N is a positive integer.
a flag is tw's own only when it is the whole command.
"""


def _positive(text: str) -> int | None:
    from agent_coord.client.tw.protocol import bounded_int

    if not text.isdigit():
        return None
    return bounded_int(int(text), positive=True)


def _peel_links(args: list[str]) -> tuple[str, int | None, int | None, list[str]]:
    """Leading --card and --pr. 'bad' when a flag is present and not a positive integer."""
    card = None
    pr = None
    saw_card = False
    saw_pr = False
    index = 0
    while index < len(args):
        flag = args[index]
        if flag == "--card" and not saw_card:
            saw_card = True
            if index + 1 >= len(args):
                return "bad", None, None, []
            card = _positive(args[index + 1])
            if card is None:
                return "bad", None, None, []
            index += 2
            continue
        if flag == "--pr" and not saw_pr:
            saw_pr = True
            if index + 1 >= len(args):
                return "bad", None, None, []
            pr = _positive(args[index + 1])
            if pr is None:
                return "bad", None, None, []
            index += 2
            continue
        break
    return "ok", card, pr, args[index:]


def _sitting() -> str:
    """The sitting connect's desk; waits for a connect still starting, as a mill command does."""
    from agent_coord.client.tokens import resolve_desk_owner
    from agent_coord.client.ws import wait_for_sitting_desk

    return (resolve_desk_owner("") or wait_for_sitting_desk() or "").strip()


def _recipe() -> None:
    from agent_coord.client.session_errors import tw_bridge_hint

    print(tw_bridge_hint(), file=sys.stderr)


def _print_running(desk: str, *, as_json: bool) -> int:
    rows = running_runs(desk)
    for row in rows:
        if as_json:
            print(json.dumps(row, separators=(",", ":")))
            continue
        print("%s %s %s" % (row["watch_id"], row["tw_pid"], row["start"]))
        print(row["log"])
        print(subprocess.list2cmdline(row["command"]) if os.name == "nt" else shlex.join(row["command"]))
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args == ["--help"] or args == ["-h"]:
        print(_HELP, end="")
        return 0
    if args == ["--version"] or args == ["-V"]:
        from agent_coord.install.packver import package_version

        print(package_version())
        return 0
    if args in (["--list"], ["-l"], ["--list-json"]):
        who = _sitting()
        if not who:
            _recipe()
            return 1
        return _print_running(who, as_json=args == ["--list-json"])
    status, card, pr, command = _peel_links(args)
    if status == "bad":
        print("tw: --card and --pr take a positive integer", file=sys.stderr)
        return 2
    if not command:
        print(_HELP, end="")
        return 2
    args = command
    from agent_coord.client.tokens import resolve_desk_owner

    who = (resolve_desk_owner("") or "").strip()
    if not who:
        from agent_coord.client.tw.run_ipc import lookup_parent, open_child, relay_call

        parent = lookup_parent()
        if parent:
            try:
                linked, watch_id, desk = open_child(parent, args)
            except OSError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            return run_argv(
                desk,
                args,
                arm_forward=True,
                linked=linked,
                watch_id=watch_id,
                call_fn=relay_call(parent, watch_id),
                card=card,
                pr=pr,
                stdin_stream=sys.stdin.buffer,
            )
        from agent_coord.client.ws import wait_for_sitting_desk

        who = (wait_for_sitting_desk() or "").strip()
    if not who:
        _recipe()
        return 1
    return run_argv(
        who, args, arm_forward=True, card=card, pr=pr, stdin_stream=sys.stdin.buffer
    )


if __name__ == "__main__":
    raise SystemExit(main())
