# -*- coding: utf-8 -*-
"""tw run, tw list, tw stop, tw status."""
from __future__ import annotations

import argparse
import sys

from agent_coord.client.tw.proc import list_runs, query_status, run_argv, stop_run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tw")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run")
    run.add_argument("--desk", required=True)
    run.add_argument("--log", default=None)
    run.add_argument("cmd_argv", nargs=argparse.REMAINDER)

    listed = sub.add_parser("list")
    listed.add_argument("--desk", required=True)

    stop = sub.add_parser("stop")
    stop.add_argument("--desk", required=True)
    stop.add_argument("watch_id")

    status = sub.add_parser("status")
    status.add_argument("--desk", required=True)
    status.add_argument("watch_id", nargs="?")

    args = parser.parse_args(argv)
    if args.cmd == "status":
        reply = query_status(args.desk, args.watch_id)
        if not isinstance(reply, dict) or reply.get("ok") is not True:
            print("missing" if not isinstance(reply, dict) else reply.get("msg") or "missing", file=sys.stderr)
            return 1
        snap = reply.get("snapshot")
        rows = snap if isinstance(snap, list) else [snap]
        for row in rows:
            if not isinstance(row, dict):
                continue
            print(
                "%s %s %s %s"
                % (
                    row.get("watch_id") or "",
                    row.get("pid") or 0,
                    row.get("stdout_bytes") or 0,
                    row.get("stderr_bytes") or 0,
                )
            )
        return 0
    if args.cmd == "list":
        for row in list_runs(args.desk):
            print("%s %s" % (row["watch_id"], row["pid"]))
        return 0
    if args.cmd == "stop":
        return stop_run(args.desk, args.watch_id)
    cmd_argv = list(args.cmd_argv)
    if cmd_argv and cmd_argv[0] == "--":
        cmd_argv = cmd_argv[1:]
    if not cmd_argv:
        print("argv required", file=sys.stderr)
        return 2
    return run_argv(args.desk, cmd_argv, log_path=args.log)


if __name__ == "__main__":
    raise SystemExit(main())
