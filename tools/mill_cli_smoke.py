"""Fail-closed mill CLI smoke: mill 0.4 verbs on PATH. No mill here / leftover."""
from __future__ import annotations

import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

MUST = ("connect", "hold", "drop", "send", "inbox", "todo", "create", "unclaim", "pass", "attach", "move", "prune")
BAN = ("leftover", "spend", "issues", "here", "presence", "acquire", "yield", "done", "heartbeat")


def _run(mill: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [mill, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _cmd_listed(help_text: str, verb: str) -> bool:
    return bool(re.search(rf"^\s+{re.escape(verb)}\s", help_text, re.M))


# Real-path rows: each runs a verb body, not only argparse. --help never
# reaches the code after parsing, which is how a stale name in connect (0.6.40)
# shipped green. Add a row when a verb gains a code path --help cannot see.
RUN_ROWS = ("connect",)
CONNECT_WAIT_S = 20.0


def run_connect_real(
    argv0: list[str], *, wait_s: float = CONNECT_WAIT_S, roster: str = "smoke-roster"
) -> str:
    """Run the real connect path against a closed local port.

    roster="" runs `mill connect smoke-desk` (Office roster by default).

    A throwaway mill home holds a session token. connect must get through its
    whole body and reach the socket loop (a backchannel reconnect line). A
    traceback or an early exit fails. Returns "" on success, else the reason.
    """
    home = tempfile.mkdtemp(prefix="mill-smoke-")
    env = dict(os.environ)
    env.update(
        AGENT_COORD_MILL_HOME=home,
        HOME=home,
        USERPROFILE=home,
        AGENT_COORD_MILL_URL="http://127.0.0.1:9",
        PYTHONUNBUFFERED="1",
    )
    env.pop("AGENT_COORD_VENDOR", None)
    env.pop("AGENT_COORD_GROK_SESSION", None)
    py = subprocess.run(
        [sys.executable, "-c",
         "from agent_coord.client.tokens import write_session_token as w; w('smoke-desk', 's' * 40)"],
        env=env, capture_output=True, text=True,
    )
    if py.returncode != 0:
        return "could not write the smoke session token: " + (py.stderr or py.stdout)[-400:]
    proc = subprocess.Popen(
        [*argv0, "connect", *([roster] if roster else []), "smoke-desk"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    lines: list[str] = []
    reached = threading.Event()

    def _read() -> None:
        for ln in proc.stdout:  # type: ignore[union-attr]
            lines.append(ln)
            if '"backchannel"' in ln:
                reached.set()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and not reached.is_set() and proc.poll() is None:
        time.sleep(0.1)
    alive = proc.poll() is None
    if alive:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    t.join(2)
    out = "".join(lines)
    if "Traceback" in out:
        return "connect raised:\n" + out[-1500:]
    if not reached.is_set():
        why = "exited rc=%s" % proc.returncode if not alive else "no socket loop in %.0fs" % wait_s
        return "connect did not reach the socket loop (%s):\n%s" % (why, out[-1500:])
    return ""


def smoke(mill: str) -> None:
    ver = _run(mill, "-V")
    if ver.returncode != 0:
        raise SystemExit(f"mill -V failed: {ver.stderr or ver.stdout}")
    got = (ver.stdout or "").strip()
    meta = importlib.metadata.version("the-mill")
    if got != meta:
        raise SystemExit(f"mill -V {got!r} != the-mill {meta!r}")

    h = _run(mill, "--help")
    if h.returncode != 0:
        raise SystemExit("mill --help failed")
    help_text = h.stdout or ""
    missing = [v for v in MUST if not _cmd_listed(help_text, v)]
    if missing:
        raise SystemExit(f"mill --help missing verbs: {missing}")
    banned = [v for v in BAN if _cmd_listed(help_text, v)]
    if banned:
        raise SystemExit(f"mill --help still lists leftover verbs: {banned}")

    c = _run(mill, "connect", "--help")
    if c.returncode != 0:
        raise SystemExit("mill connect --help failed")

    for roster in ("smoke-roster", ""):
        bad = run_connect_real([mill], roster=roster)
        if bad:
            how = "with roster" if roster else "without a roster (Office)"
            raise SystemExit("mill connect real path %s: %s" % (how, bad))

    here = _run(mill, "here")
    if here.returncode == 0:
        raise SystemExit("mill here must not be a verb")
    left = _run(mill, "leftover")
    if left.returncode == 0:
        raise SystemExit("mill leftover must not succeed")


def main() -> int:
    mill = shutil.which("mill")
    if not mill:
        print("mill not on PATH", file=sys.stderr)
        return 1
    tw = shutil.which("tw")
    if not tw:
        print("tw not on PATH", file=sys.stderr)
        return 1
    smoke(mill)
    print(f"ok mill-cli-smoke {mill} {tw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
