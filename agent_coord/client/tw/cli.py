# -*- coding: utf-8 -*-
"""tw CMD ARGS. The desk is the sitting connect, not a flag."""
from __future__ import annotations

import sys

from agent_coord.client.tw.proc import list_runs, run_argv

_HELP = """\
usage: tw CMD ARGS
       tw
       tw --help
       tw --version

run CMD while this process shares a parent with a sitting connect.
one stderr line at start is the watch id, this pid, and the log path.
the command output passes through and is copied to the log.
tw exits with the command exit code.
with no arguments, list this desk's runs.
--help and --version are the only flags, and only when they are the whole command.
"""


def _sitting() -> str:
    from agent_coord.client.tokens import resolve_desk_owner

    return (resolve_desk_owner("") or "").strip()


def _recipe() -> None:
    from agent_coord.client.session_errors import bridge_hint

    print(bridge_hint(), file=sys.stderr)


def _print_runs(desk: str) -> int:
    for row in list_runs(desk):
        if row.get("exit_code") is not None:
            print("%s %s %s" % (row["watch_id"], row["pid"], row["exit_code"]))
        else:
            print("%s %s" % (row["watch_id"], row["pid"]))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--help"]:
        print(_HELP, end="")
        return 0
    if args == ["--version"]:
        from agent_coord.install.packver import package_version

        print(package_version())
        return 0
    who = _sitting()
    if not who:
        _recipe()
        return 1
    if not args:
        return _print_runs(who)
    return run_argv(who, args, arm_forward=True)


if __name__ == "__main__":
    raise SystemExit(main())
