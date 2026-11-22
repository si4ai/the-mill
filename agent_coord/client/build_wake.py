# -*- coding: utf-8 -*-
"""Parent shell for a Grok Build desk.

Runs ``mill connect``, prints one short line per hint, and runs mill commands
as children of this process. A zero exit prints nothing. Letter bodies and
the socket address are never printed.

Card 1285. The sit-exit restart is implemented and not yet observed live.
"""
from __future__ import annotations

import argparse
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from agent_coord.client.offices import bind_cli_office, pull_office_flag
from agent_coord.helpers.ident import desk_name

_HINT_KIND = re.compile(r"'kind': '([A-Za-z0-9_-]+)'")
_HINT_ID = re.compile(r"'id': (\d+)")
_HINT_FROM = re.compile(r"'from': '([^']+)'")


def session_paths(desk: str) -> tuple[Path, Path, Path, Path]:
    """Request, done, stdout, and stderr files for this desk."""
    base = Path.home() / ".mill" / "session"
    return (
        base / f"{desk}.wake-req.json",
        base / f"{desk}.wake-done.txt",
        base / f"{desk}.wake-out.txt",
        base / f"{desk}.wake-err.txt",
    )


def command_line(code: int) -> str | None:
    """A child command line. Zero is quiet."""
    if int(code) == 0:
        return None
    return "CMD exit %d" % int(code)


def seat_after(saw_drop: bool, restarts: int) -> str:
    """What the shell does when mill connect exits.

    ``restart`` once after a sit-exit or a closed socket. A second immediate
    close, or an exit that was not a drop, stops the shell.
    """
    if saw_drop and restarts < 1:
        return "restart"
    if saw_drop:
        return "hold-drop"
    return "hold-end"


def classify(text: str, seen: set[str], sit: set[str]) -> list[str]:
    """Safe lines for one connect stdout line. ``seen`` and ``sit`` accumulate."""
    raw = (text or "").strip()
    if not raw:
        return []
    if raw.startswith("{'connector'") or raw.startswith('{"connector"'):
        return ["POKE error"]
    if raw.startswith("{") and not raw.startswith("{'HINT'"):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            return _from_json(obj, seen, sit)
    if "HINT" not in raw:
        return []
    kind_m = _HINT_KIND.search(raw)
    id_m = _HINT_ID.search(raw)
    if not kind_m or not id_m or kind_m.group(1).lower() == "ping":
        return []
    brief = kind_m.group(1).lower() + " " + id_m.group(1)
    from_m = _HINT_FROM.search(raw)
    if from_m and from_m.group(1) != "grok-tui":
        brief += " from " + from_m.group(1).split()[0]
    if brief in seen:
        return []
    seen.add(brief)
    return ["HINT " + brief]


def _brief(obj: dict) -> str | None:
    kind = str(obj.get("kind") or obj.get("type") or "").strip().lower()
    if kind in ("", "ping", "sync", "heartbeat", "session"):
        return None
    ident = obj.get("id")
    if ident in (None, ""):
        return None
    line = kind + " " + str(ident)
    sender = str(obj.get("from") or obj.get("sender") or "").strip()
    if sender and sender != "grok-tui":
        line += " from " + sender.split()[0]
    return line


def _from_json(obj: dict, seen: set[str], sit: set[str]) -> list[str]:
    if obj.get("mode") == "ws" or obj.get("backchannel") or obj.get("ready") is True:
        if obj.get("ready") is True:
            desk = str(obj.get("desk") or "").strip()
            return ["SEATED " + desk] if desk else ["SEATED"]
        return []
    if obj.get("connector") == "error":
        return ["POKE error"]
    if obj.get("error") == "connect closed":
        return ["CONNECT_CLOSED"]
    if obj.get("mode") == "sit-exit" and isinstance(obj.get("hint"), dict):
        brief = _brief(obj["hint"])
        if brief is None or brief in sit:
            return []
        seen.add(brief)
        sit.add(brief)
        return ["HINT " + brief + " sit-exit"]
    if obj.get("kind") == "sync":
        rows = obj.get("sync") if isinstance(obj.get("sync"), list) else []
        newest = 0
        mail = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                newest = max(newest, int(row.get("id") or 0))
            except (TypeError, ValueError):
                pass
            if str(row.get("kind") or "").lower() == "mail":
                mail += 1
        return ["SYNC n=%d newest=%d mail=%d" % (len(rows), newest, mail)]
    brief = _brief(obj)
    if brief is None or brief in seen:
        return []
    seen.add(brief)
    return ["HINT " + brief]


def _say(text: str) -> None:
    if text:
        print(text, flush=True)


def _mill_bin() -> str:
    found = shutil.which("mill") or shutil.which("mill.exe")
    if not found:
        raise FileNotFoundError("mill")
    return found


def _popen(argv: list[str]) -> subprocess.Popen:
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs["startupinfo"] = startup
    return subprocess.Popen(argv, **kwargs)


def _read_stdout(proc: subprocess.Popen, out: queue.Queue) -> None:
    stream = proc.stdout
    if stream is None:
        out.put(None)
        return
    for line in stream:
        out.put(line)
    out.put(None)


def _run_req(mill: str, spec: dict, out_path: Path, err_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if spec.get("op") == "exec":
        argv = [str(part) for part in (spec.get("argv") or [])]
        if not argv:
            return 2
    else:
        args = [str(part) for part in (spec.get("args") or [])]
        if not args:
            return 2
        argv = [mill, *args]
    with out_path.open("w", encoding="utf-8") as out, err_path.open("w", encoding="utf-8") as err:
        proc = subprocess.run(argv, stdout=out, stderr=err, check=False)
    return int(proc.returncode or 0)


def _serve_one(proc: subprocess.Popen, req: Path, done: Path, out_path: Path, err_path: Path, mill: str) -> bool:
    """Read hints until connect exits. Return true when the exit was a drop."""
    seen: set[str] = set()
    sit: set[str] = set()
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_read_stdout, args=(proc, lines), daemon=True).start()
    drop = False
    while True:
        try:
            line = lines.get(timeout=0.4)
        except queue.Empty:
            line = ""
        if line is None:
            break
        if line:
            for event in classify(line, seen, sit):
                _say(event)
                if event.endswith(" sit-exit") or event == "CONNECT_CLOSED":
                    drop = True
        if req.is_file():
            raw = req.read_text(encoding="utf-8")
            req.unlink(missing_ok=True)
            code = 2
            if raw.strip():
                try:
                    spec = json.loads(raw)
                except json.JSONDecodeError:
                    spec = {}
                if isinstance(spec, dict):
                    code = _run_req(mill, spec, out_path, err_path)
            done.write_text("EXIT %d\n" % code, encoding="ascii")
            note = command_line(code)
            if note:
                _say(note)
        if proc.poll() is not None and lines.empty():
            break
    proc.wait(timeout=5)
    return drop


def run_shell(desk: str, office: str, req: Path, done: Path, out_path: Path, err_path: Path) -> int:
    """Sit until a second drop, or until connect ends without one."""
    mill = _mill_bin()
    restarts = 0
    while True:
        argv = [mill]
        if office:
            argv.extend(["--office", office])
        argv.extend(["connect", desk])
        proc = _popen(argv)
        try:
            drop = _serve_one(proc, req, done, out_path, err_path, mill)
        finally:
            if proc.poll() is None:
                proc.kill()
        step = seat_after(drop, restarts)
        if step == "restart":
            restarts += 1
            _say("RESTART 1")
            time.sleep(1)
            continue
        _say("HOLD second close" if step == "hold-drop" else "HOLD connect ended")
        return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    office, raw = pull_office_flag(raw)
    bind_cli_office(office)
    parser = argparse.ArgumentParser(
        prog="mill-build-wake",
        description="Sit mill connect and print one short line per hint.",
    )
    parser.add_argument("desk", help="desk id this shell sits")
    parser.add_argument("--req", default="", help="JSON file of one child command")
    args = parser.parse_args(raw)
    who = desk_name(str(args.desk or ""))
    if not who:
        print("HOLD desk required", flush=True)
        return 1
    req, done, out_path, err_path = session_paths(who)
    if args.req:
        req = Path(args.req)
        done = req.with_name(req.name + ".done")
        out_path = req.with_name(req.name + ".out")
        err_path = req.with_name(req.name + ".err")
    try:
        return run_shell(who, office, req, done, out_path, err_path)
    except FileNotFoundError:
        print("HOLD no mill", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
