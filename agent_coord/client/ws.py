# -*- coding: utf-8 -*-
"""mill connect backchannel: sit on mill-wall /ws/{desk}. Recv enqueues; drain prints.

Desk-acting commands use JSON RPC on that same sitting socket via a localhost bridge.
The bridge records the parent pid of the mill connect process. A command may use
only the bridge whose parent pid equals its own parent pid. On Windows the
parent pid skips console-script launchers (mill.exe), so `mill` and
`python -m agent_coord` agree on the shell. mill_ws_call never
opens a second /ws and never reads the host active file to choose a desk.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import sys
import threading
import time
import uuid
from collections.abc import Collection
from pathlib import Path
from typing import Any

from agent_coord.helpers.ident import desk as slug_desk


def _stored_desk(value: str) -> str:
    return (value or "").strip()
from agent_coord.server.hint_buf import HintBuf, drain_loop, drop_notice
from agent_coord.server.push import dest_log, perf_log


def _bc_log(msg: str) -> None:
    dest_log("mill-backchannel.log", msg)


async def _notify_drop(ws: Any, frame: dict[str, Any]) -> None:
    """Tell the office a frame left the 256 cap. Do not wait for a reply."""
    try:
        await ws.send(json.dumps(drop_notice(frame), default=str))
    except Exception as e:
        _bc_log(f"hint drop notify err={type(e).__name__}")


def refuse_url(url: str, refuse: bool) -> str:
    """mill connect -r asks the office not to take a held seat (#332)."""
    return url + "?refuse=1" if refuse else url


def mill_ws_url(desk: str) -> str:
    from agent_coord.config import settings
    from agent_coord.client.http import mill_url

    who = slug_desk(desk)
    base = (mill_url() or "").rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://") :] + "/ws/" + who
    if base.startswith("http://"):
        return "ws://" + base[len("http://") :] + "/ws/" + who
    s = settings()
    bind = str(s.get("dashboard_bind") or "127.0.0.1")
    port = int(s.get("dashboard_port") or 8765)
    return f"ws://{bind}:{port}/ws/{who}"


def rpc_bridge_path(desk: str) -> Path:
    """Endpoint file for the sitting mill connect localhost RPC bridge."""
    from agent_coord.client.offices import desk_local_file
    from agent_coord.config import mill_home

    hosted = desk_local_file(desk, "ws.rpc")
    if hosted is not None:
        return hosted
    who = slug_desk(desk)
    dest = mill_home() / "session"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / f"{who}.ws.rpc"


def _shell_ppid() -> int:
    """Launching shell pid; skips Windows console-script launchers (agent-ux 1214)."""
    from agent_coord.lib.proc import shell_parent_pid

    return shell_parent_pid()


def _pid_alive(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    # Windows: os.kill(pid, 0) raises WinError 87; use lib.proc.
    if sys.platform == "win32":
        from agent_coord.lib.proc import proc_token
        return proc_token(int(pid)) is not None
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def write_rpc_bridge(
    desk: str,
    *,
    port: int,
    secret: str,
    pid: int | None = None,
    parent_pid: int | None = None,
) -> Path:
    """Publish 127.0.0.1 bridge for this desk (secret authenticates).

    pid is the mill connect process. parent_pid is the process that launched
    connect. A later command may send only when its own parent pid matches.
    """
    path = rpc_bridge_path(desk)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "desk": _stored_desk(desk),
        "host": "127.0.0.1",
        "port": int(port),
        "secret": str(secret or ""),
        "pid": int(pid if pid is not None else os.getpid()),
        "parent_pid": int(parent_pid if parent_pid is not None else _shell_ppid()),
    }
    raw = json.dumps(row, separators=(",", ":")) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _load_rpc_bridge(path: Path, *, fallback_desk: str = "") -> dict[str, Any] | None:
    """Load one bridge file. None when missing, corrupt, or the connect pid is dead."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    port = int(row.get("port") or 0)
    secret = str(row.get("secret") or "")
    pid = int(row.get("pid") or 0)
    parent_pid = int(row.get("parent_pid") or 0)
    host = str(row.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    if port <= 0 or not secret:
        return None
    if pid and not _pid_alive(pid):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    file_desk = str(row.get("desk") or fallback_desk or "").strip()
    who = _stored_desk(file_desk) if file_desk else ""
    if not who:
        return None
    return {
        "host": host,
        "port": port,
        "secret": secret,
        "pid": pid,
        "parent_pid": parent_pid,
        "desk": who,
    }


def read_rpc_bridge(desk: str) -> dict[str, Any] | None:
    """Load live bridge endpoint. None when missing, corrupt, or connect process gone."""
    return _load_rpc_bridge(rpc_bridge_path(desk), fallback_desk=desk)


def _rpc_bridge_files() -> list[Path]:
    """Endpoint files for the selected office, else the legacy session directory."""
    from agent_coord.client.offices import current_host_key, host_dir
    from agent_coord.config import mill_home

    roots: list[Path] = []
    try:
        host = current_host_key()
    except ValueError:
        host = ""
    if host:
        try:
            roots.append(host_dir(host))
        except ValueError:
            roots = []
    else:
        roots.append(mill_home() / "session")
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(p for p in root.glob("*.ws.rpc") if p.is_file()))
        found.extend(sorted(p for p in root.glob("*/ws.rpc") if p.is_file()))
    return found


def bridge_for_parent(parent_pid: int | None = None) -> dict[str, Any] | None:
    """The one live bridge launched by this parent. None if not exactly one.

    Does not read the host active file and does not fall back to it.
    """
    want = int(_shell_ppid() if parent_pid is None else parent_pid)
    if want <= 0:
        return None
    hits: list[dict[str, Any]] = []
    for path in _rpc_bridge_files():
        # A dead pid stays on disk. _load would delete it, and the died
        # check needs the file after this returns None (#228).
        peeked = _peek_json(path)
        if isinstance(peeked, dict):
            pid = int(peeked.get("pid") or 0)
            if pid and not _pid_alive(pid):
                continue
        row = _load_rpc_bridge(path)
        if not row:
            continue
        if int(row.get("parent_pid") or 0) != want:
            continue
        hits.append(row)
    if len(hits) != 1:
        return None
    return hits[0]


def _peek_json(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    return row if isinstance(row, dict) else None


def dead_connect_for_parent(parent_pid: int | None = None) -> bool:
    """True when a bridge or starting file for this parent has a dead pid (#228).

    Those files are removed. Call this only after bridge_for_parent returns None.
    """
    want = int(_shell_ppid() if parent_pid is None else parent_pid)
    if want <= 0:
        return False
    dead_paths: list[Path] = []
    for path in list(_rpc_bridge_files()) + list(_starting_files()):
        row = _peek_json(path)
        if not row or int(row.get("parent_pid") or 0) != want:
            continue
        pid = int(row.get("pid") or 0)
        if pid and not _pid_alive(pid):
            dead_paths.append(path)
    for path in dead_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return bool(dead_paths)


# #121 GO A: sync can print before the localhost bridge file exists; one short
# wait then fail closed. 0.5s is longer than the usual port-bind poll (0.02s
# steps) and far shorter than reconnect backoff (3s).
SITTING_BRIDGE_RETRY_WAIT_S = 0.5
# No starting file yet: how long a command looks for a connect launched just before it.
SITTING_FIRST_WAIT_S = 3.0
# Handshake can take the websocket open timeout (10s) after mode:ws prints
# and before the bridge file exists (#210). Poll only while that connect is starting.
CONNECT_START_WAIT_S = 10.0
CONNECT_START_POLL_S = 0.2


def connect_starting_path(desk: str) -> Path:
    """Marker that this desk's connect is in the handshake, before the bridge exists."""
    path = rpc_bridge_path(desk)
    name = path.name
    if name == "ws.rpc":
        leaf = "ws.starting"
    elif name.endswith(".ws.rpc"):
        leaf = name[: -len(".rpc")] + ".starting"
    else:
        leaf = name + ".starting"
    return path.with_name(leaf)


def write_connect_starting(
    desk: str,
    *,
    pid: int | None = None,
    parent_pid: int | None = None,
) -> Path:
    """Publish that a connect in this process tree is still opening the socket."""
    path = connect_starting_path(desk)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "desk": _stored_desk(desk),
        "pid": int(pid if pid is not None else os.getpid()),
        "parent_pid": int(parent_pid if parent_pid is not None else _shell_ppid()),
    }
    raw = json.dumps(row, separators=(",", ":")) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)
    return path


def clear_connect_starting(desk: str, *, pid: int | None = None) -> bool:
    """Remove the starting marker. True only when a file was removed."""
    path = connect_starting_path(desk)
    if not path.is_file():
        return False
    if pid is not None:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            row = None
        if isinstance(row, dict):
            file_pid = int(row.get("pid") or 0)
            if file_pid and file_pid != int(pid):
                return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _starting_files(leaf: str = "ws.starting") -> list[Path]:
    """Starting markers (or busy notes) for the selected office, else the legacy session directory."""
    from agent_coord.client.offices import current_host_key, host_dir
    from agent_coord.config import mill_home

    roots: list[Path] = []
    try:
        host = current_host_key()
    except ValueError:
        host = ""
    if host:
        try:
            roots.append(host_dir(host))
        except ValueError:
            roots = []
    else:
        roots.append(mill_home() / "session")
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(sorted(p for p in root.glob(f"*.{leaf}") if p.is_file()))
        found.extend(sorted(p for p in root.glob(f"*/{leaf}") if p.is_file()))
    return found


def _load_starting(path: Path) -> dict[str, Any] | None:
    """One starting marker. None when missing, corrupt, or the connect pid is dead."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    pid = int(row.get("pid") or 0)
    if not _pid_alive(pid):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    who = _stored_desk(str(row.get("desk") or ""))
    if not who:
        return None
    return {
        "desk": who,
        "pid": pid,
        "parent_pid": int(row.get("parent_pid") or 0),
    }


def starting_for_parent(parent_pid: int | None = None) -> dict[str, Any] | None:
    """The one live starting connect launched by this parent. None unless exactly one."""
    want = int(_shell_ppid() if parent_pid is None else parent_pid)
    if want <= 0:
        return None
    hits: list[dict[str, Any]] = []
    for path in _starting_files():
        row = _load_starting(path)
        if not row:
            continue
        if int(row.get("parent_pid") or 0) != want:
            continue
        hits.append(row)
    if len(hits) != 1:
        return None
    return hits[0]


_READY_DESKS: set[str] = set()
# connect sets the roster it sits on; printed on the ready line.
READY_ROSTER: dict[str, str] = {}
READY_NOTE = (
    "connected; keep this connect running and run desk commands from this same "
    "parent shell (they find it through the parent process)"
)


def with_connect_roster(command: str, args: dict[str, Any]) -> dict[str, Any]:
    """send/reply without --roster carry the roster this connect named (#337).

    The server checks the desk is on it; an explicit --roster is left alone.
    """
    named = str(READY_ROSTER.get("roster") or "").strip()
    if command not in ("send", "reply") or not named or str(args.get("roster") or "").strip():
        return args
    return dict(args, connect_roster=named)


def note_bridge_ready(desk: str) -> None:
    """One JSON line when this process first publishes the bridge (#210)."""
    who = slug_desk(desk)
    if not who or who in _READY_DESKS:
        return
    _READY_DESKS.add(who)
    row: dict[str, Any] = {"ready": True, "desk": who}
    if READY_ROSTER.get("roster"):
        row["roster"] = READY_ROSTER["roster"]
    row["note"] = READY_NOTE
    line = json.dumps(row, default=str)
    if not gate_line(line):
        print(line, flush=True)
    tip = foreground_tip(who)
    if tip:
        print(tip, file=sys.stderr, flush=True)


def foreground_tip(desk: str) -> str:
    """Interactive foreground connect: say how every mill command runs (0.7.x)."""
    try:
        interactive = bool(sys.stdin.isatty() and sys.stderr.isatty())
    except (AttributeError, ValueError):
        interactive = False
    if not interactive:
        return ""
    from agent_coord.client.session_errors import ONE_LINER

    return (
        "mill connect: ready; it blocks this shell. Every mill command runs as: "
        + ONE_LINER.replace("DESK", desk)
    )


def wait_for_sitting_desk() -> str:
    """Desk of this parent's bridge.

    A connect still starting in this process tree is polled until the bridge
    file exists, the connect pid exits, or 10s pass. Nothing starting: one
    short wait and one more look (#121). Empty when there is still no bridge.
    """
    parent = _shell_ppid()
    start = starting_for_parent(parent)
    pid = int((start or {}).get("pid") or 0)
    if start and _pid_alive(pid):
        deadline = time.monotonic() + CONNECT_START_WAIT_S
        while time.monotonic() < deadline:
            ep = bridge_for_parent(parent)
            if ep:
                return str(ep.get("desk") or "").strip()
            if not _pid_alive(pid):
                break
            time.sleep(CONNECT_START_POLL_S)
        ep = bridge_for_parent(parent)
        return str(ep.get("desk") or "").strip() if ep else ""
    # `mill connect DESK & mill COMMAND`: the connect may not have written its
    # starting file yet. Look for a while before giving up (0.7.x one-liner).
    wait_s = max(SITTING_FIRST_WAIT_S, SITTING_BRIDGE_RETRY_WAIT_S) if SITTING_BRIDGE_RETRY_WAIT_S else 0.0
    deadline = time.monotonic() + wait_s
    while True:
        ep = bridge_for_parent(parent)
        if ep:
            return str(ep.get("desk") or "").strip()
        start = starting_for_parent(parent)
        if start and _pid_alive(int(start.get("pid") or 0)):
            return wait_for_sitting_desk()
        if time.monotonic() >= deadline:
            return ""
        time.sleep(CONNECT_START_POLL_S)


def clear_rpc_bridge(desk: str, *, pid: int | None = None) -> None:
    """Remove bridge file. If pid set, only clear when file pid matches (no race)."""
    path = rpc_bridge_path(desk)
    if pid is not None:
        row = None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            row = None
        if isinstance(row, dict) and int(row.get("pid") or 0) not in (0, int(pid)):
            return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _is_rpc_reply(msg: dict[str, Any]) -> bool:
    return isinstance(msg, dict) and "ok" in msg and "id" in msg


def _is_push_frame(msg: dict[str, Any]) -> bool:
    if not isinstance(msg, dict):
        return False
    if _is_rpc_reply(msg):
        return False
    hint = str(msg.get("hint") or "")
    typ = str(msg.get("type") or "")
    return bool(hint or typ in ("heartbeat", "session"))


# Server close code for a refused mill connect -r (#332); same as push.WS_IN_USE.
WS_IN_USE_CLOSE = 4409

# 4401 seat rejected, 4000 superseded and 4409 seat in use end the sit. Other closes reconnect.
_TERMINAL_CLOSE = frozenset({4401, 4000, WS_IN_USE_CLOSE})
_RECONNECT_CAP_S = 60.0
_RECONNECT_HEALTHY_S = 30.0
# After a drop the office can still hold this desk's old socket until its ping
# timeout; a -r reconnect refused (4409) inside this window retries (#336).
_STALE_SEAT_S = 45.0


def close_code_of(exc: BaseException | None) -> int | None:
    """Close code from a socket error, or None when the error is not a close."""
    if exc is None:
        return None
    rcvd = getattr(exc, "rcvd", None)
    code = getattr(rcvd, "code", None)
    if isinstance(code, int):
        return code
    text = str(exc)
    marker = "received "
    i = text.find(marker)
    if i < 0:
        return None
    digits: list[str] = []
    for ch in text[i + len(marker) :]:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    return int("".join(digits))


def reconnect_delay_s(attempt: int, *, jitter: float | None = None) -> float:
    """Backoff 1s, 2s, 4s, ... capped at 60s, with +/- 20% jitter.

    attempt is 0-based. Pass jitter in [-0.2, 0.2] from tests; None draws one.
    """
    import random

    step = max(0, int(attempt))
    base = min(_RECONNECT_CAP_S, float(2 ** step))
    if jitter is None:
        span = random.uniform(-0.2, 0.2)
    else:
        span = max(-0.2, min(0.2, float(jitter)))
    return max(0.0, min(_RECONNECT_CAP_S, base * (1.0 + span)))


def reconnect_stopped(code: int | None, outcome: dict | None) -> bool:
    """True when this close must not start another sit.

    4401, 4000 and 4409 stop. Other closes keep the 60s cap. A sit that already
    stored one of those exits stops too.
    """
    if outcome is not None and code in _CLOSE_EXIT and "exit" not in outcome:
        outcome["exit"] = _CLOSE_EXIT[code]
    if code in _TERMINAL_CLOSE:
        return True
    if outcome is not None and outcome.get("exit") in _CLOSE_EXIT.values():
        return True
    return False


def ws_host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def open_retry_notice(host: str, exc: BaseException) -> str:
    """JSON line for a failed first open. Host and error class, not a Python repr (#139)."""
    return json.dumps(
        {"backchannel": "reconnect", "host": host or "", "error": type(exc).__name__},
        separators=(",", ":"),
    )


def _json_line(row: dict[str, Any]) -> str:
    return json.dumps(row, separators=(",", ":"), default=str)


def bad_frame_notice(raw: Any) -> dict[str, Any]:
    """Non-JSON wall bytes. Head is the first 120 characters (#141)."""
    if isinstance(raw, str):
        data = raw.encode("utf-8", "replace")
        head = raw[:120]
    elif isinstance(raw, (bytes, bytearray)):
        data = bytes(raw)
        head = data[:120].decode("utf-8", "replace")
    else:
        data = b""
        head = ""
    return {"backchannel": "bad_frame", "bytes": len(data), "head": head}


def fail_lone_rpc(pending: dict[str, Any], raw: Any) -> bool:
    """Log a bad frame. If exactly one RPC is waiting, fail it now (#141)."""
    print(_json_line(bad_frame_notice(raw)), flush=True)
    if len(pending) != 1:
        return False
    rid, q = next(iter(pending.items()))
    try:
        q.put_nowait({"id": rid, "ok": False, "error": "ws rpc: bad frame"})
    except Exception:
        return False
    pending.pop(rid, None)
    return True


def rpc_timeout_error(
    command: str, req_id: str, args: dict[str, Any] | None = None
) -> str:
    """A command that never answered may already have been applied (#137, #177)."""
    where = "mill inbox / mill todo"
    if str(command or "") == "reply":
        mid = ""
        if isinstance(args, dict):
            mid = str(
                args.get("mail_id") or args.get("id") or args.get("parent_id") or ""
            ).strip()
        where = f"mill mail-thread {mid}" if mid else "mill mail-thread <root>"
    return (
        f"ws rpc: no reply in 30s for {command} (id {req_id}); "
        f"it may have applied - check with {where} before retrying"
    )


def stash_rpc_reply(late: dict[str, dict[str, Any]], msg: dict[str, Any]) -> None:
    """Keep a bridge reply that arrived after its waiter gave up (#176)."""
    rid = str(msg.get("id") or "")
    if rid:
        late[rid] = msg


def pop_rpc_reply(late: dict[str, dict[str, Any]], req_id: str) -> dict[str, Any] | None:
    """Return a stashed reply for this request id, if one is waiting (#176)."""
    return late.pop(str(req_id or ""), None)


def _retry_key(command: str, args: dict[str, Any]) -> str:
    import hashlib

    blob = json.dumps({"verb": command, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _retry_path(key: str) -> Path:
    root = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    folder = Path(root) / "mill-rpc-retry"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (key + ".json")


def load_retry_id(command: str, args: dict[str, Any], *, now: float | None = None) -> str:
    """Reuse the id from a recent no-reply, so the wall can dedupe (#137)."""
    path = _retry_path(_retry_key(command, args))
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    stamp = now if now is not None else time.time()
    try:
        age = stamp - float(row.get("at") or 0)
    except (TypeError, ValueError):
        age = 10_000
    if age > 180 or age < 0:
        try:
            path.unlink()
        except OSError:
            pass
        return ""
    return str(row.get("id") or "")


def save_retry_id(command: str, args: dict[str, Any], req_id: str) -> None:
    path = _retry_path(_retry_key(command, args))
    path.write_text(
        json.dumps({"id": req_id, "at": time.time()}, separators=(",", ":")),
        encoding="utf-8",
    )


def clear_retry_id(command: str, args: dict[str, Any]) -> None:
    path = _retry_path(_retry_key(command, args))
    try:
        path.unlink()
    except OSError:
        pass


def retry_notice_seconds(delay_s: float) -> int:
    """Whole seconds named in the stderr retry line. At least 1, at most 60."""
    return max(1, min(60, int(round(float(delay_s)))))


def foreground_close_result(exc: BaseException, desk: str) -> dict[str, Any] | None:
    """JSON for a socket close in mill connect-wait. None means re-raise.

    ConnectionClosed is not an OSError. Both must become ok:false, not a traceback (#140).
    """
    if close_code_of(exc) == WS_IN_USE_CLOSE:
        return {"ok": False, **close_line(WS_IN_USE_CLOSE, exc, desk),
                "exit": _CLOSE_EXIT[WS_IN_USE_CLOSE]}
    if isinstance(exc, OSError) or "ConnectionClosed" in type(exc).__name__:
        return {"ok": False, "error": "connect closed", "desk": desk}
    return None


# 4401 and 4000 are distinct from exit 0 and from each other (#136, #332). A busy
# seat (4409) exits 0 (card 834): the session holding the seat gets the letters.
_CLOSE_EXIT = {4401: 4, 4000: 5, WS_IN_USE_CLOSE: 0}
_CLOSE_ERROR = {
    4401: "token rejected (4401): mill join again or ask the office to reset this seat",
    4000: "superseded (4000): another connect took this seat",
    WS_IN_USE_CLOSE: "busy",
}


def close_error(code: int, exc: BaseException | None, desk: str) -> str:
    """Line for a terminal close. Busy (4409) says to stop and names --take (card 834)."""
    if code != WS_IN_USE_CLOSE:
        return _CLOSE_ERROR[code]
    reason = str(getattr(getattr(exc, "rcvd", None), "reason", "") or "")
    since = reason.split(" since ", 1)[1].strip() if " since " in reason else ""
    when = f" (since {since})" if since else ""
    return (
        f"busy: another session has the seat for {desk}{when} and gets this desk's letters; "
        f"stop. To take a dead or stale seat: mill connect --take {desk}"
    )


def close_line(code: int, exc: BaseException | None, desk: str) -> dict[str, Any]:
    """The one JSON line a terminal close prints. Busy is not an error (card 834)."""
    text = close_error(code, exc, desk)
    if code == WS_IN_USE_CLOSE:
        return {"busy": True, "desk": desk, "next": text}
    return {"ok": False, "error": text}


# Card 834: a first refusal retries after these waits, so a per-call connect whose
# socket the office has not dropped yet does not read as busy.
BUSY_SETTLE_S: tuple[float, ...] = (1.0, 2.0)
# A busy note answers commands in the same shell for this long.
BUSY_NOTE_S = 120.0


def connect_busy_path(desk: str) -> Path:
    """Note that this desk's connect in some shell was refused as busy (card 834)."""
    start = connect_starting_path(desk)
    return start.with_name(start.name.removesuffix(".starting") + ".busy")


def write_connect_busy(desk: str, text: str, *, parent_pid: int | None = None) -> Path:
    path = connect_busy_path(desk)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "desk": _stored_desk(desk),
        "parent_pid": int(parent_pid if parent_pid is not None else _shell_ppid()),
        "next": text,
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def busy_for_parent(parent_pid: int | None = None) -> str:
    """The busy text a connect of this parent left in the last BUSY_NOTE_S, else ""."""
    want = int(_shell_ppid() if parent_pid is None else parent_pid)
    if want <= 0:
        return ""
    for busy in _starting_files("ws.busy"):
        try:
            if time.time() - busy.stat().st_mtime > BUSY_NOTE_S:
                continue
            row = json.loads(busy.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(row, dict) and int(row.get("parent_pid") or 0) == want:
            return str(row.get("next") or "busy")
    return ""


def bridge_close_error(exc: BaseException | None) -> str:
    """Honest error for in-flight bridge RPCs when the sitting /ws ends (#66)."""
    code = close_code_of(exc)
    if code == 4000:
        return (
            "ws rpc: superseded (4000): another connect took this seat; "
            "mill connect again"
        )
    if code == 4401:
        return (
            "ws rpc: token rejected (4401): mill join again or ask the office "
            "to reset this seat"
        )
    return "ws rpc: sitting socket closed"


def sync_view(msg: dict[str, Any]) -> dict[str, Any]:
    """Printed connect sync. holds is this desk's locks.

    A missing or non-list holds becomes []. The key is always printed, including [].
    """
    from agent_coord.install.packver import package_version

    holds = msg.get("holds")
    if not isinstance(holds, list):
        holds = []
    out = {
        "kind": "sync",
        "sync": msg.get("sync") or [],
        "mill": msg.get("mill") or package_version(),
        "holds": holds,
    }
    # #618: armed or off, from the wall; an older wall sends none.
    if isinstance(msg.get("wake"), str) and msg.get("wake"):
        out["wake"] = msg["wake"]
    # Card 866: the office version check. A match is quiet. A warning is the message text.
    hello = msg.get("hello")
    if isinstance(hello, dict):
        hello = hello.get("message") or hello.get("status") or ""
    if isinstance(hello, str):
        hello = hello.strip()
        if hello and hello != "ok":
            out["hello"] = hello
    # 923: once per process, when this pack is older than the office mill field.
    from agent_coord.client.older import attach_older_once

    return attach_older_once(out)


# connect holds the ready and sync lines until the project check passes (#237).
_SYNC_LOCK = threading.Lock()
_SYNC_GATE: dict[str, Any] = {"held": None}


def hold_sync_lines() -> None:
    """Keep sync lines back until release_sync_lines or drop_sync_lines."""
    with _SYNC_LOCK:
        _SYNC_GATE["held"] = []


def gate_line(text: str) -> bool:
    """True when the line was held back. False means print it now."""
    with _SYNC_LOCK:
        held = _SYNC_GATE["held"]
        if held is None:
            return False
        held.append(text)
        return True


def release_sync_lines() -> None:
    """Print held sync lines and stop holding."""
    with _SYNC_LOCK:
        held = _SYNC_GATE["held"] or []
        _SYNC_GATE["held"] = None
        for text in held:
            print(text, flush=True)


def drop_sync_lines() -> None:
    """Forget held sync lines. A refused connect never prints one."""
    with _SYNC_LOCK:
        _SYNC_GATE["held"] = None


def own_bridge_call(desk: str, body: dict[str, Any], *, timeout_s: float = 35.0) -> dict[str, Any]:
    """One RPC over this process's own sitting /ws. Returns the raw bridge reply.

    Only the connect process uses it: the bridge file must name this pid.
    Raises CoordError when the bridge is not up.
    """
    from agent_coord.helpers.errors import CoordError

    ep = read_rpc_bridge(desk)
    if not ep or int(ep.get("pid") or 0) != os.getpid():
        raise CoordError("socket not ready")
    command = str(body.get("verb") or "")
    args = {k: v for k, v in dict(body).items() if k not in ("verb", "cmd", "owner", "token")}
    req_id = str(uuid.uuid4())
    req = {"id": req_id, "verb": command, "args": args, "secret": ep["secret"]}
    raw_req = (json.dumps(req, default=str) + "\n").encode("utf-8")
    buf = b""
    with socket.create_connection((str(ep["host"]), int(ep["port"])), timeout=10.0) as sock:
        sock.settimeout(timeout_s)
        sock.sendall(raw_req)
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace")
    try:
        msg = json.loads(line) if line else {}
    except json.JSONDecodeError as e:
        raise CoordError("bad bridge reply") from e
    if not isinstance(msg, dict) or "ok" not in msg:
        raise CoordError("bad bridge reply")
    return msg


async def _sit_session(
    ws: Any,
    desk: str,
    stop: threading.Event,
    buf: HintBuf | None,
    *,
    bridge_host: str = "127.0.0.1",
    reconnect: Any = None,
    outcome: dict | None = None,
    first_frame: str | None = None,
) -> None:
    """One sitting /ws: multiplex HINT vs RPC; thread TCP bridge for mill_ws_call.

    first_frame is a frame the caller already read (connect -r reads the first
    frame before this bridge is published, #332); it is handled first.

    reconnect, when set, is an async callable that returns a new socket.
    A recoverable close keeps this bridge up and calls it after backoff.
    4401 and 4000 do not reconnect.
    """
    who = slug_desk(desk)
    pending: dict[str, asyncio.Queue] = {}
    late_box: dict[str, dict[str, Any]] = {}
    rpc_reqs: asyncio.Queue = asyncio.Queue()
    secret = secrets.token_urlsafe(24)
    my_pid = os.getpid()
    parent_pid = _shell_ppid()
    loop = asyncio.get_running_loop()
    err_box: dict[str, BaseException] = {}
    if buf is not None:
        def _send_exit(notice: dict[str, Any]) -> None:
            async def _go() -> None:
                try:
                    await ws.send(json.dumps(notice, default=str))
                except Exception as e:
                    _bc_log(f"route exit notify err={type(e).__name__}")

            try:
                loop.call_soon_threadsafe(lambda: asyncio.create_task(_go()))
            except Exception:
                pass

        buf.set_sender(_send_exit)

    async def on_frame(msg: dict[str, Any]) -> None:
        if str(msg.get("kind") or "") == "sync" and "sync" in msg:
            line = json.dumps(sync_view(msg), default=str)
            if not gate_line(line):
                print(line, flush=True)
            if buf is not None:
                # #618: what was missed (or rung by a webhook doorbell) walks this desk's
                # chain now, the same walk a live hint takes; no vendor poke on replay.
                from agent_coord.client.dispatch import replay_items

                for item in replay_items(buf.desk, msg.get("sync") or []):
                    buf.put_recv(item)
            return
        if _is_rpc_reply(msg):
            rid = str(msg.get("id") or "")
            q = pending.get(rid)
            if q is not None:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    stash_rpc_reply(late_box, msg)
            elif rid:
                stash_rpc_reply(late_box, msg)
            return
        if buf is not None:
            buf.put_recv(msg)
            for old in buf.pop_drops():
                asyncio.create_task(_notify_drop(ws, old))
        else:
            print({"HINT": msg}, flush=True)

    async def multiplex() -> None:
        ws_task: asyncio.Task | None = asyncio.create_task(ws.recv())
        rpc_task: asyncio.Task | None = asyncio.create_task(rpc_reqs.get())
        try:
            while not stop.is_set():
                tasks = {t for t in (ws_task, rpc_task) if t is not None}
                if not tasks:
                    break
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                if ws_task is not None and ws_task in done:
                    try:
                        raw = ws_task.result()
                    except Exception as e:
                        err_box["exc"] = e
                        break
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        fail_lone_rpc(pending, raw)
                        ws_task = asyncio.create_task(ws.recv())
                        continue
                    try:
                        from agent_coord.config import mill_debug

                        if mill_debug():
                            print(
                                {"DEBUG": "ws", **(msg if isinstance(msg, dict) else {"raw": raw})},
                                flush=True,
                            )
                    except Exception:
                        pass
                    if isinstance(msg, dict):
                        await on_frame(msg)
                    elif buf is not None:
                        buf.put_recv({"raw": raw})
                    ws_task = asyncio.create_task(ws.recv())
                if rpc_task is not None and rpc_task in done:
                    try:
                        wire, wait_q = rpc_task.result()
                    except Exception:
                        break
                    req_id = str((wire or {}).get("id") or "")
                    pending[req_id] = wait_q
                    try:
                        await ws.send(json.dumps(wire, default=str))
                        _bc_log(
                            f"ws rpc bridge send desk={who} verb={wire.get('verb')} id={req_id}"
                        )
                    except Exception as e:
                        try:
                            wait_q.put_nowait(
                                {"id": req_id, "ok": False, "error": str(e)[:240]}
                            )
                        except asyncio.QueueFull:
                            pass
                        pending.pop(req_id, None)
                    rpc_task = asyncio.create_task(rpc_reqs.get())
        finally:
            for t in (ws_task, rpc_task):
                if t is not None and not t.done():
                    t.cancel()
            # Prefer superseded/token-rejected over opaque "sitting socket closed" (#66).
            closed_err = bridge_close_error(err_box.get("exc"))
            for rid, q in list(pending.items()):
                try:
                    q.put_nowait(
                        {
                            "id": rid,
                            "ok": False,
                            "error": closed_err,
                        }
                    )
                except asyncio.QueueFull:
                    pass

    def _bridge_serve(port_box: dict[str, int], srv_box: dict[str, Any]) -> None:
        """Sync TCP accept loop (thread). Avoids asyncio Proactor cross-thread stalls."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_box["srv"] = srv
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((bridge_host, 0))
            srv.listen(16)
            port_box["port"] = int(srv.getsockname()[1])
            srv.settimeout(0.4)
            while not stop.is_set():
                try:
                    conn, _addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    conn.settimeout(30.0)
                    buf_b = b""
                    while b"\n" not in buf_b:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf_b += chunk
                    line = buf_b.split(b"\n", 1)[0].decode("utf-8", "replace")
                    try:
                        req = json.loads(line) if line else {}
                    except json.JSONDecodeError:
                        req = {}
                    reply: dict[str, Any]
                    if not isinstance(req, dict):
                        reply = {"id": None, "ok": False, "error": "ws rpc: bad shape"}
                    elif str(req.get("secret") or "") != secret:
                        reply = {
                            "id": req.get("id"),
                            "ok": False,
                            "error": "ws rpc: bridge auth failed",
                        }
                    else:
                        req_id = str(req.get("id") or "")
                        command = str(req.get("verb") or req.get("cmd") or "").strip()
                        args = req.get("args", {})
                        if not req_id:
                            reply = {"id": None, "ok": False, "error": "ws rpc: id required"}
                        elif not command:
                            reply = {"id": req_id, "ok": False, "error": "ws rpc: command required"}
                        elif args is not None and not isinstance(args, dict):
                            reply = {
                                "id": req_id,
                                "ok": False,
                                "error": "ws rpc: args must be an object",
                            }
                        else:
                            if args is None:
                                args = {}
                            stashed = pop_rpc_reply(late_box, req_id)
                            if stashed is not None:
                                reply = stashed
                            else:
                                wire = {"id": req_id, "verb": command, "args": with_connect_roster(command, args)}
                                wait_q: asyncio.Queue = asyncio.Queue(maxsize=1)

                                async def _submit(
                                    _wire: dict[str, Any] = wire,
                                    _q: asyncio.Queue = wait_q,
                                    _rid: str = req_id,
                                ) -> dict[str, Any]:
                                    hit = pop_rpc_reply(late_box, _rid)
                                    if hit is not None:
                                        return hit
                                    await rpc_reqs.put((_wire, _q))
                                    try:
                                        return await asyncio.wait_for(_q.get(), timeout=30.0)
                                    except TimeoutError:
                                        pending.pop(_rid, None)
                                        try:
                                            return _q.get_nowait()
                                        except asyncio.QueueEmpty:
                                            hit = pop_rpc_reply(late_box, _rid)
                                            if hit is not None:
                                                return hit
                                            raise

                                try:
                                    fut = asyncio.run_coroutine_threadsafe(_submit(), loop)
                                    reply = fut.result(timeout=35.0)
                                except TimeoutError:
                                    pending.pop(req_id, None)
                                    reply = {
                                        "id": req_id,
                                        "ok": False,
                                        "error": rpc_timeout_error(command, req_id, args),
                                    }
                                except Exception as e:
                                    text = str(e)[:240]
                                    reply = {
                                        "id": req_id,
                                        "ok": False,
                                        "error": text or rpc_timeout_error(command, req_id, args),
                                    }
                                if str(reply.get("id") or "") != req_id:
                                    if reply.get("id"):
                                        stash_rpc_reply(late_box, reply)
                                    reply = {
                                        "id": req_id,
                                        "ok": False,
                                        "error": rpc_timeout_error(command, req_id, args),
                                    }
                    conn.sendall((json.dumps(reply, default=str) + "\n").encode("utf-8"))
                except Exception as e:
                    _bc_log(f"ws rpc bridge client err desk={who} err={e}")
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
        finally:
            try:
                srv.close()
            except OSError:
                pass

    port_box: dict[str, int] = {}
    srv_box: dict[str, Any] = {}
    bridge_thread = threading.Thread(
        target=_bridge_serve,
        args=(port_box, srv_box),
        name=f"mill-ws-rpc-{who}",
        daemon=True,
    )
    bridge_thread.start()
    for _ in range(50):
        if port_box.get("port"):
            break
        await asyncio.sleep(0.02)
    port = int(port_box.get("port") or 0)
    if not port:
        srv = srv_box.get("srv")
        if srv is not None:
            try:
                srv.close()
            except OSError:
                pass
        bridge_thread.join(timeout=2.0)
        raise RuntimeError("ws rpc bridge: no local port")
    write_rpc_bridge(who, port=port, secret=secret, pid=my_pid, parent_pid=parent_pid)
    clear_connect_starting(who, pid=my_pid)
    note_bridge_ready(who)
    _bc_log(f"ws rpc bridge up desk={who} port={port}")
    if first_frame is not None:
        try:
            first = json.loads(first_frame)
        except json.JSONDecodeError:
            first = None
        if isinstance(first, dict):
            await on_frame(first)
    attempt = 0
    opened = time.monotonic()
    mux_task: asyncio.Task | None = None
    terminal_code: int | None = None
    dropped_at: float | None = None

    async def _pause(code: int | None) -> None:
        nonlocal attempt, opened
        if time.monotonic() - opened >= _RECONNECT_HEALTHY_S:
            attempt = 0
        opened = time.monotonic()
        delay = reconnect_delay_s(attempt)
        attempt += 1
        secs = retry_notice_seconds(delay)
        what = "seat still held by the dropped socket" if code == WS_IN_USE_CLOSE else "server restarting"
        print(f"{what}, retrying in {secs}s", file=sys.stderr, flush=True)
        _bc_log(f"ws reconnect desk={who} in {secs}s code={code}")
        deadline = time.monotonic() + secs
        while not stop.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    try:
        while not stop.is_set():
            err_box.clear()
            mux_task = asyncio.create_task(multiplex())
            while not stop.is_set() and not mux_task.done():
                await asyncio.sleep(0.2)
            if stop.is_set():
                break
            exc = err_box.get("exc")
            code = close_code_of(exc)
            stale = (
                code == WS_IN_USE_CLOSE
                and dropped_at is not None
                and time.monotonic() - dropped_at < _STALE_SEAT_S
            )
            if reconnect is None or (code in _TERMINAL_CLOSE and not stale) or exc is None:
                if code in _TERMINAL_CLOSE:
                    terminal_code = code
                break
            if code != WS_IN_USE_CLOSE:
                dropped_at = time.monotonic()
            await _pause(code)
            if stop.is_set():
                break
            fresh = None
            while not stop.is_set():
                try:
                    fresh = await reconnect()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    await _pause(close_code_of(e))
                    continue
                break
            if fresh is None:
                break
            ws = fresh
            opened = time.monotonic()
    finally:
        if terminal_code in _CLOSE_EXIT:
            line = close_line(terminal_code, err_box.get("exc"), who)
            print(json.dumps(line), flush=True)
            if line.get("busy"):
                write_connect_busy(who, line["next"])
            if outcome is not None:
                outcome["exit"] = _CLOSE_EXIT[terminal_code]
        clear_rpc_bridge(who, pid=my_pid)
        stop.set()
        if mux_task is not None and not mux_task.done():
            mux_task.cancel()
        if mux_task is not None:
            try:
                await mux_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        try:
            srv = srv_box.get("srv")
            if srv is not None:
                srv.close()
        except OSError:
            pass
        bridge_thread.join(timeout=2.0)
        _bc_log(f"ws rpc bridge down desk={who}")



def run_ws_loop(
    desk: str,
    token: str,
    stop: threading.Event,
    buf: HintBuf | None = None,
    outcome: dict | None = None,
    refuse: bool = False,
) -> None:
    """Recv thread: sit /ws, serve localhost RPC bridge, enqueue HINTs. Reconnect on drop."""
    try:
        import websockets
    except ImportError:
        print(
            "mill here: websockets not installed; backchannel off (mill wake catch-up still works)",
            flush=True,
        )
        return
    import asyncio

    url = refuse_url(mill_ws_url(desk), refuse)
    hdrs = {}
    if token:
        hdrs["Authorization"] = "Bearer " + token

    async def _once() -> None:
        kw: dict[str, Any] = {"open_timeout": 10}
        if url.startswith("wss://"):
            try:
                from agent_coord.client.http import mill_ssl_context

                kw["ssl"] = mill_ssl_context()
            except Exception as e:
                print(_json_line({"backchannel": "ssl", "error": type(e).__name__}), flush=True)
                raise
        if hdrs:
            kw["additional_headers"] = hdrs

        def _connect() -> Any:
            try:
                return websockets.connect(url, **kw)
            except TypeError:
                kw.pop("additional_headers", None)
                if hdrs:
                    kw["extra_headers"] = hdrs
                return websockets.connect(url, **kw)

        extras: list[Any] = []

        async def _reopen() -> Any:
            ctx = _connect()
            sock = await ctx.__aenter__()
            extras.append(ctx)
            who_re = slug_desk(desk)
            again = url.split("?")[0]
            print(_json_line({"backchannel": "ws", "url": again, "desk": who_re}), flush=True)
            _bc_log(f"ws recv sit desk={who_re} url={again}")
            return sock

        conn = _connect()
        async with conn as ws:
            who = slug_desk(desk)
            sit_url = url.split("?")[0]
            print(_json_line({"backchannel": "ws", "url": sit_url, "desk": who}), flush=True)
            _bc_log(f"ws recv sit desk={who} url={sit_url}")
            # connect -r: the office sends the sync only once the seat is ours, so
            # read it before publishing a bridge; a refusal (4409) raises here and
            # never touches the holder's bridge file on this computer (#332).
            first = await ws.recv() if refuse else None
            try:
                await _sit_session(
                    ws, who, stop, buf, reconnect=_reopen, outcome=outcome, first_frame=first
                )
            finally:
                for ctx in extras:
                    try:
                        await ctx.__aexit__(None, None, None)
                    except Exception:
                        pass

    write_connect_starting(desk, pid=os.getpid(), parent_pid=_shell_ppid())
    attempt = 0
    first_open = True
    settle = list(BUSY_SETTLE_S) if refuse else []
    try:
        while not stop.is_set():
            try:
                asyncio.run(_once())
            except Exception as e:
                code = close_code_of(e)
                if first_open and code == WS_IN_USE_CLOSE and settle:
                    # Card 834: the holder may be a per-call connect the office has
                    # not dropped yet. Look again before calling the seat busy.
                    stop.wait(settle.pop(0))
                    continue
                if first_open:
                    clear_connect_starting(desk, pid=os.getpid())
                first_open = False
                if stop.is_set():
                    return
                if reconnect_stopped(code, outcome):
                    if code in _CLOSE_ERROR:
                        line = close_line(code, e, slug_desk(desk))
                        print(json.dumps(line), flush=True)
                        if line.get("busy"):
                            write_connect_busy(desk, line["next"])
                    stop.set()
                    return
                print(open_retry_notice(ws_host(url), e), flush=True)
                _bc_log(
                    f"ws recv leave desk={slug_desk(desk)} reconnect err={type(e).__name__}"
                )
                perf_log("ws.reconnect", 0.0, desk=slug_desk(desk), err=type(e).__name__)
                delay = reconnect_delay_s(attempt)
                attempt += 1
                stop.wait(delay)
            else:
                first_open = False
                if reconnect_stopped(None, outcome):
                    stop.set()
                    return
                attempt = 0
    finally:
        clear_connect_starting(desk, pid=os.getpid())


def _undelivered(item: Any) -> bool:
    """A sync item not already handed to a live socket of this desk (#328)."""
    return not (isinstance(item, dict) and str(item.get("outcome") or "") == "sent")


def wait_one_hint(
    desk: str,
    token: str,
    *,
    skip_ping: bool = True,
    timeout_s: float | None = None,
    skip_kinds: Collection[str] | None = None,
    hold_empty_sync: bool = False,
    parent_pid: int | None = None,
    refuse: bool = False,
) -> dict[str, Any]:
    """Block on /ws until one work frame, then return.

    Does not spawn mill route / drain. Caller prints JSON and exits.
    timeout_s None = wait until a frame or interrupt (KeyboardInterrupt).
    Does not publish the RPC bridge (one-shot wait, then exit).

    skip_ping drops hub PING. skip_kinds drops those top-level kinds.
    kind sync is not in the default skip set: it is the push queue.
    A missed DOING inside that list is a queue item, not a frame to ignore.

    hold_empty_sync defaults false: an empty sync list returns. mill
    connect-wait and mill-hold pass true: an empty list keeps the socket
    until the next hint or a non-empty list (card #278). A list whose items
    were all sent live already counts as empty (card #328).
    """
    try:
        import websockets
    except ImportError:
        return {"ok": False, "error": "websockets not installed"}
    import asyncio

    from agent_coord.client.inbound import ignore

    url = refuse_url(mill_ws_url(desk), refuse)
    who = slug_desk(desk)
    hdrs: dict[str, str] = {}
    if token:
        hdrs["Authorization"] = "Bearer " + token

    async def _go() -> dict[str, Any]:
        kw: dict[str, Any] = {"open_timeout": 10}
        if url.startswith("wss://"):
            try:
                from agent_coord.client.http import mill_ssl_context

                kw["ssl"] = mill_ssl_context()
            except Exception as e:
                return {"ok": False, "error": f"ssl: {e}", "desk": who}
        if hdrs:
            kw["additional_headers"] = hdrs
        try:
            conn = websockets.connect(url, **kw)
        except TypeError:
            kw.pop("additional_headers", None)
            if hdrs:
                kw["extra_headers"] = hdrs
            conn = websockets.connect(url, **kw)
        async with conn as wsock:
            sit_url = url.split("?")[0]
            mode = "hold" if hold_empty_sync else "foreground"
            skipped = {
                str(kind).strip().lower()
                for kind in (skip_kinds or ())
                if str(kind).strip()
            }
            print(
                json.dumps(
                    {"backchannel": "ws", "mode": mode, "url": sit_url, "desk": who},
                    default=str,
                ),
                flush=True,
            )
            _bc_log(f"ws {mode} sit desk={who} url={sit_url}")
            deadline = None
            if timeout_s is not None and float(timeout_s) > 0:
                deadline = asyncio.get_event_loop().time() + float(timeout_s)
            while True:
                wait = 2.0
                if deadline is not None:
                    left = deadline - asyncio.get_event_loop().time()
                    if left <= 0:
                        return {"ok": False, "error": "timeout", "desk": who, "url": sit_url}
                    wait = min(2.0, left)
                try:
                    raw = await asyncio.wait_for(wsock.recv(), timeout=wait)
                except asyncio.TimeoutError:
                    if parent_pid:
                        from agent_coord.lib.proc import parent_gone

                        if parent_gone(int(parent_pid)):
                            from agent_coord.client.session_errors import parent_exited_notice

                            out = parent_exited_notice(who, url=sit_url)
                            out["mode"] = mode
                            return out
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    print(_json_line(bad_frame_notice(raw)), flush=True)
                    continue
                if not isinstance(msg, dict):
                    print(_json_line(bad_frame_notice(raw)), flush=True)
                    continue
                kind = str(msg.get("kind") or "").strip().lower()
                if kind and kind in skipped:
                    continue
                if kind == "sync":
                    items = msg.get("sync")
                    queued = items if isinstance(items, list) else []
                    # Whole list is the queue. Do not drop a missed DOING inside it.
                    # An item a sitting connect of this desk already got (outcome
                    # sent) does not end the wait; an undelivered one does (#328).
                    if hold_empty_sync and not any(_undelivered(it) for it in queued):
                        continue
                    return {
                        "ok": True,
                        "mode": mode,
                        "hint": msg,
                        "desk": who,
                        "url": sit_url,
                    }
                if skip_ping and ignore(msg):
                    continue
                hint = str(msg.get("hint") or "")
                if skip_ping and hint.upper() == "PING":
                    continue
                return {
                    "ok": True,
                    "mode": mode,
                    "hint": msg,
                    "desk": who,
                    "url": sit_url,
                }

    settle = list(BUSY_SETTLE_S) if refuse else []
    while True:
        try:
            return asyncio.run(_go())
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if close_code_of(exc) == WS_IN_USE_CLOSE and settle:
                time.sleep(settle.pop(0))  # card 834: a holder that just closed is not busy
                continue
            closed = foreground_close_result(exc, who)
            if closed is not None:
                return closed
            raise


def start_ws_thread(
    desk: str,
    token: str,
    stop: threading.Event,
    outcome: dict | None = None,
    refuse: bool = False,
) -> threading.Thread:
    buf = HintBuf(desk)
    who = slug_desk(desk)
    drain = threading.Thread(
        target=drain_loop, args=(buf, stop), name=f"mill-hint-drain-{who}", daemon=True
    )
    drain.start()
    t = threading.Thread(
        target=run_ws_loop,
        args=(desk, token, stop, buf, outcome, refuse),
        name=f"mill-ws-{who}",
        daemon=True,
    )
    t.start()
    return t


def mill_ws_call(body: dict[str, Any], *, token: str = "", desk: str = "") -> Any:
    """Desk-acting command over the sitting mill connect /ws via localhost bridge.

    Requires mill connect (bridge file). Does not open a second /ws (would kick).
    token is unused for bridge auth (local secret); kept for call-site compat.

    Success returns the full host reply object (ok/mill/id/result/sync). Failure
    raises CoordError with sync (+ envelope) so the CLI can print the same shape.

    #121 GO A: on the exact sitting-miss error, one short wait and one retry,
    then fail closed. Other errors are not retried.
    """
    from agent_coord.helpers.errors import CoordError
    from agent_coord.client.outbound import canonical_command
    from agent_coord.client.session_errors import (
        SESSION_CONNECT_DIED,
        SESSION_WS_BRIDGE_REQUIRED,
    )

    _ = token  # Bearer already authenticated the sitting connect
    _ = desk  # not the sender; the parent pid selects the bridge

    command = canonical_command(str(body.get("verb") or body.get("cmd") or ""))
    if not command:
        raise CoordError("ws rpc: command required")
    if command == "join":
        raise CoordError("join stays HTTP only; not a /ws RPC command")

    args = {k: v for k, v in dict(body).items() if k not in ("verb", "cmd", "owner", "token")}
    req_id = load_retry_id(command, args) or str(uuid.uuid4())

    def _once() -> Any:
        ep = bridge_for_parent()
        if not ep:
            died = dead_connect_for_parent()
            raise CoordError(SESSION_CONNECT_DIED if died else SESSION_WS_BRIDGE_REQUIRED)
        who = str(ep.get("desk") or "")
        if not who:
            raise CoordError(SESSION_WS_BRIDGE_REQUIRED)

        req = {
            "id": req_id,
            "verb": command,
            "args": args,
            "secret": ep["secret"],
        }
        host = str(ep["host"])
        port = int(ep["port"])
        raw_req = (json.dumps(req, default=str) + "\n").encode("utf-8")

        try:
            with socket.create_connection((host, port), timeout=10.0) as sock:
                sock.settimeout(35.0)
                sock.sendall(raw_req)
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
        except OSError as e:
            clear_rpc_bridge(who)
            raise CoordError(SESSION_WS_BRIDGE_REQUIRED) from e

        line = buf.split(b"\n", 1)[0].decode("utf-8", "replace")
        try:
            msg = json.loads(line) if line else {}
        except json.JSONDecodeError as e:
            raise CoordError("ws rpc: bad bridge reply") from e
        if not isinstance(msg, dict) or "ok" not in msg:
            raise CoordError("ws rpc: bad bridge reply")
        if msg.get("id") != req_id:
            # Prefer the bridge's error (e.g. superseded) over opaque mismatch (#66).
            erred = str(msg.get("error") or "").strip()
            if erred:
                raise CoordError(erred)
            raise CoordError(
                "ws rpc: bridge reply id mismatch; "
                "if another connect took this seat, mill connect again"
            )
        err_text = msg.get("error")
        result = msg.get("result")
        # Full reply envelope by default (ok/mill/id/result/sync). Bare arrays
        # blocked warm teach; --raw unwraps at CLI print only.
        # A refused hold is ok false, a result dict, and no error (#207).
        # An error string still raises.
        if msg.get("ok") is True or (
            msg.get("ok") is False and not err_text and isinstance(result, dict)
        ):
            out = dict(msg)
            if not isinstance(out.get("sync"), list):
                out["sync"] = list(out.get("sync") or [])
            clear_retry_id(command, args)
            return out
        err = str(err_text or "ws rpc failed")
        if err.startswith("ws rpc: no reply in 30s"):
            save_retry_id(command, args, req_id)
        sync = msg.get("sync") if isinstance(msg.get("sync"), list) else list(msg.get("sync") or [])
        raise CoordError(err, sync=sync, envelope=dict(msg))

    try:
        return _once()
    except CoordError as e:
        if str(e) != SESSION_WS_BRIDGE_REQUIRED:
            raise
        parent = _shell_ppid()
        start = starting_for_parent(parent)
        pid = int((start or {}).get("pid") or 0)
        if not (start and _pid_alive(pid)):
            time.sleep(SITTING_BRIDGE_RETRY_WAIT_S)
            return _once()
        deadline = time.monotonic() + CONNECT_START_WAIT_S
        while time.monotonic() < deadline:
            if bridge_for_parent(parent):
                return _once()
            if not _pid_alive(pid):
                break
            time.sleep(CONNECT_START_POLL_S)
        return _once()
