# -*- coding: utf-8 -*-
"""tw CMD ARGS. The desk is the sitting connect, not a flag."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

from agent_coord.client.tw.proc import running_runs, run_argv

_HELP = """\
usage: tw CMD ARGS
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
a flag is tw's own only when it is the whole command.
"""


def _sitting() -> str:
    from agent_coord.client.tokens import resolve_desk_owner

    return (resolve_desk_owner("") or "").strip()


def _recipe() -> None:
    from agent_coord.client.session_errors import bridge_hint

    print(bridge_hint(), file=sys.stderr)


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
    who = _sitting()
    if not who:
        _recipe()
        return 1
    return run_argv(who, args, arm_forward=True)


if __name__ == "__main__":
    raise SystemExit(main())
