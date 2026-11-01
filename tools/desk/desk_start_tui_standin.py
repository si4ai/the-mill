"""desk-start TUI stand-in (cross-platform). Mirror of desk-start-tui-standin.ps1.

Checks that stdin/stdout are TTYs (not redirected), draws a simple frame with
VT alternate-screen sequences when stdout is a TTY, optionally reads one byte
from stdin, restores the screen, exits with --exit-code.

Used by tests on Linux; on Windows, desk-start.ps1 -StubTui prefers the .ps1.
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def is_interactive() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="desk-start TUI stand-in")
    p.add_argument("--exit-code", type=int, default=0)
    p.add_argument(
        "--auto-exit",
        action="store_true",
        help="do not wait for a key (CI / non-interactive probe after isatty check)",
    )
    args = p.parse_args(argv)

    interactive = is_interactive()
    print(
        f"desk-start-tui-standin: interactive={interactive} "
        f"in_tty={sys.stdin.isatty()} out_tty={sys.stdout.isatty()}",
        flush=True,
    )
    if not interactive:
        print("desk-start-tui-standin: FAIL not a console (stdin or stdout not a tty)", flush=True)
        return 2

    esc = "\x1b"
    sys.stdout.write(
        f"{esc}[?1049h{esc}[2J{esc}[H"
        f"{esc}[1;1Hdesk-start-tui-standin\n"
        f"{esc}[2;1H---------------------\n"
        f"{esc}[3;1Hconsole attached; press any key to exit {args.exit_code}\n"
        f"{esc}[4;1H(or wait if --auto-exit)\n"
    )
    sys.stdout.flush()

    if args.auto_exit:
        time.sleep(0.05)
    else:
        # One byte; works for a real tty. In CI prefer --auto-exit.
        try:
            os.read(sys.stdin.fileno(), 1)
        except OSError:
            pass

    sys.stdout.write(f"{esc}[?1049l")
    sys.stdout.flush()
    print(f"desk-start-tui-standin: exit {args.exit_code}", flush=True)
    return int(args.exit_code) & 0xFF


if __name__ == "__main__":
    raise SystemExit(main())
