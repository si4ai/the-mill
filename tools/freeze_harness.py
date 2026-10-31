# -*- coding: utf-8 -*-
"""Freeze-r1 harness for rows A1, A2, A7, and F3. Not part of the wheel.

Runs an in-process office on 127.0.0.1 with a temp mill home and a throwaway
MySQL schema whose name starts with freeze_. Injects one frame through the
office hub. No server inject verb.

  freeze_harness.py run ROW --desk NAME [--agent-cmd CMD] [--pack VER]
      [--timeout 600] [--out DIR] [--green FILE] [--frame ping] [--db NAME]
      [--url http://127.0.0.1:PORT]
  freeze_harness.py compare ROW [--out DIR] [--green FILE]
  freeze_harness.py bless ROW RUN_ID [--out DIR] [--green FILE]

Exit 0 green, 1 red, 2 harness error. Refuses --office, a non-loopback URL,
and a database name that does not start with freeze_.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROWS = ("A1", "A2", "A7", "F3")
LOOPBACK = {"127.0.0.1", "localhost"}
DAY_ONE = frozenset(
    {
        "open",
        "todo",
        "claim",
        "assign",
        "unclaim",
        "note",
        "pass",
        "send",
        "reply",
        "mail-thread",
        "inbox",
        "hold",
        "drop",
    }
)
# Real refusal text from records.todo.require_status, as the todo verb reports it.
TODO_REFUSAL = "todo: status must be parked, open, claimed, shipped, or done"
# The sitting client stops waiting at 30s. The first send must outlast that.
SEND_DELAY_S = 31.0
SCORE_KEYS = (
    "frame",
    "verb",
    "wrong",
    "retry",
    "decision",
    "err",
    "mail_rows",
    "fanout",
    "same_req",
    "result",
)


def _field(raw: object) -> str:
    return str(raw or "").replace(" ", "_")[:80]


def judge(row: str, obs: dict[str, Any]) -> tuple[str, str]:
    """green|red and a short err. obs holds the measured stamp fields."""
    if row == "A1" and str(obs.get("frame") or "") == "PING":
        if obs.get("verb") or int(obs.get("mail_rows") or 0):
            return "red", "ping ran a verb or inbox"
        return "green", ""
    if row == "A1":
        verb = str(obs.get("verb") or "")
        if verb not in DAY_ONE:
            return "red", "wake stamp missing a day-one verb"
        return "green", ""
    if row == "A2":
        wrong = int(obs.get("wrong") or 0)
        retry = int(obs.get("retry") or 0)
        if not obs.get("verb"):
            if obs.get("client_exit"):
                return "red", "client exit %s" % obs.get("client_exit")
            return "red", "no wake stamp"
        if wrong < 1:
            return "red", "wrong count stayed 0"
        if retry > 1:
            return "red", "retry %s" % retry
        if obs.get("resent_same"):
            return "red", "refused verb was resent unchanged"
        if str(obs.get("verb") or "") not in DAY_ONE:
            return "red", "wake verb outside the day-one set"
        return "green", ""
    if row == "A7":
        if str(obs.get("decision") or "") != "work":
            return "red", "decision %s" % (obs.get("decision") or "missing")
        if obs.get("sentinel_ran"):
            return "red", "sentinel ran"
        return "green", ""
    if row == "F3":
        if not obs.get("same_req"):
            return "red", "retry used a different request id"
        if int(obs.get("mail_rows") or 0) != 1:
            return "red", "mail_rows %s" % obs.get("mail_rows")
        if int(obs.get("fanout") or 0) != 1:
            return "red", "fanout %s" % obs.get("fanout")
        if int(obs.get("send_runs") or 0) != 1:
            return "red", "send ran %s times" % obs.get("send_runs")
        return "green", ""
    return "red", "unknown row"


def note_client_exit(mill_home: Path, code: int, row: str = "A2") -> None:
    """Perf line when a client-side invalid choice never reaches the office."""
    line = "op=hint.client_exit code=%s row=%s" % (int(code), _field(row))
    path = Path(mill_home) / "mill-perf.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import timezone

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(stamp + line + "\n")


def _refuse(argv: list[str]) -> str:
    """Return an error string when the invocation targets a live office."""
    for i, item in enumerate(argv):
        if item == "--office" or item.startswith("--office="):
            return "refused --office"
        if item == "--db" and i + 1 < len(argv):
            name = argv[i + 1]
            if not str(name).startswith("freeze_"):
                return "refused db name"
        if item.startswith("--db=") and not item.split("=", 1)[1].startswith("freeze_"):
            return "refused db name"
        if item == "--url" and i + 1 < len(argv):
            why = _bad_url(argv[i + 1])
            if why:
                return why
        if item.startswith("--url="):
            why = _bad_url(item.split("=", 1)[1])
            if why:
                return why
    return ""


def _bad_url(url: str) -> str:
    from urllib.parse import urlparse

    raw = (url or "").strip()
    if not raw:
        return "refused url"
    parsed = urlparse(raw if "://" in raw else "http://" + raw)
    host = (parsed.hostname or "").lower()
    if host not in LOOPBACK:
        return "refused remote url"
    return ""


def _pack_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"', text)
    return match.group(1) if match else ""


def _sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except Exception:
        return ""
    return out.strip()


def _minute() -> str:
    """Local minute labeled PT when this machine's zone is Pacific."""
    now = datetime.now().astimezone()
    name = (now.tzname() or "").lower()
    label = "PT" if "pacific" in name else (now.tzname() or "local")
    return now.strftime("%Y-%m-%d %H:%M ") + label


def _out_dir(path: str) -> Path:
    if path:
        dest = Path(path)
    else:
        dest = Path.home() / ".mill" / "freeze"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def _green_path(out: Path, given: str) -> Path:
    return Path(given) if given else out / "green.json"


def _append(out: Path, row: str, rec: dict[str, Any]) -> None:
    path = out / ("%s.jsonl" % row)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _load_green(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _diff(rec: dict[str, Any], blessed: dict[str, Any] | None) -> dict[str, Any]:
    if not blessed:
        return {}
    changed: dict[str, Any] = {}
    for key in SCORE_KEYS:
        if rec.get(key) != blessed.get(key):
            changed[key] = {"green": blessed.get(key), "run": rec.get(key)}
    return changed


def _last_run(out: Path, row: str) -> dict[str, Any] | None:
    path = out / ("%s.jsonl" % row)
    if not path.is_file():
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    return last if isinstance(last, dict) else None


def _find_run(out: Path, row: str, run_id: str) -> dict[str, Any] | None:
    path = out / ("%s.jsonl" % row)
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and str(rec.get("run_id") or "") == run_id:
            return rec
    return None


def cmd_compare(row: str, out: Path, green: Path) -> int:
    rec = _last_run(out, row)
    if rec is None:
        print("no run for %s" % row)
        return 2
    blessed = _load_green(green).get(row)
    if not isinstance(blessed, dict):
        print("no blessed run for %s" % row)
        return 2
    changed = _diff(rec, blessed)
    if not changed:
        print("no change")
        return 0
    for key, pair in changed.items():
        print("%s green=%s run=%s" % (key, pair.get("green"), pair.get("run")))
    return 1


def cmd_bless(row: str, run_id: str, out: Path, green: Path) -> int:
    rec = _find_run(out, row, run_id)
    if rec is None:
        print("run not found")
        return 2
    book = _load_green(green)
    book[row] = rec
    green.write_text(json.dumps(book, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("blessed %s %s" % (row, run_id))
    return 0


def _perf_text(home: Path) -> str:
    path = home / "mill-perf.log"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _wake(text: str) -> dict[str, Any]:
    for line in text.splitlines():
        if "op=wake.first_ok" not in line:
            continue
        out: dict[str, Any] = {}
        for key in ("verb", "wrong", "retry", "desk"):
            match = re.search(r"\b%s=(\S+)" % key, line)
            if match:
                out[key] = match.group(1)
        if "verb" in out:
            out["wrong"] = int(out.get("wrong") or 0)
            out["retry"] = int(out.get("retry") or 0)
            return out
    return {}


def _decision(text: str) -> str:
    for line in reversed(text.splitlines()):
        if "op=hint.dispatch" not in line:
            continue
        match = re.search(r"\bdecision=(\S+)", line)
        if match:
            return match.group(1)
    return ""


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _db_name(row: str, frame: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9_]", "", row.lower())
    if frame == "PING":
        tag += "ping"
    stamp = time.strftime("%Y%m%d%H%M%S")
    return ("freeze_%s_%s_%s" % (tag, stamp, os.getpid()))[:64]


def _prepare_env(home: Path, database: str, port: int) -> None:
    os.environ["AGENT_COORD_MILL_HOME"] = str(home)
    os.environ["AGENT_COORD_DATABASE"] = database
    os.environ["AGENT_COORD_HOST"] = "127.0.0.1"
    os.environ["AGENT_COORD_MILL_URL"] = "http://127.0.0.1:%s" % port
    os.environ.pop("AGENT_COORD_PORT", None)
    os.environ.pop("AGENT_COORD_SPAWN", None)
    real = Path.home() / ".mill" / "config.toml"
    if real.is_file():
        os.environ["AGENT_COORD_CONFIG"] = str(real)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _create_db(name: str) -> None:
    if not name.startswith("freeze_"):
        raise RuntimeError("refused db name")
    import mysql.connector

    from agent_coord.config import mysql_kwargs

    kw = mysql_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    try:
        cur = admin.cursor()
        cur.execute(
            "CREATE DATABASE `%s` DEFAULT CHARACTER SET utf8mb4 "
            "DEFAULT COLLATE utf8mb4_0900_ai_ci" % name
        )
        cur.close()
    finally:
        admin.close()


def _drop_db(name: str) -> None:
    if not str(name).startswith("freeze_"):
        return
    try:
        import mysql.connector

        from agent_coord.config import mysql_kwargs

        kw = mysql_kwargs()
        kw.pop("database", None)
        kw["autocommit"] = True
        admin = mysql.connector.connect(**kw)
    except Exception:
        return
    try:
        cur = admin.cursor()
        cur.execute("DROP DATABASE IF EXISTS `%s`" % name)
        cur.close()
    finally:
        admin.close()


def _wait_until(pred, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _hint_seen(home: Path, desk: str, idem: str) -> bool:
    from agent_coord.helpers.ident import desk as slug_desk

    path = home / "session" / ("%s.hints.jsonl" % slug_desk(desk))
    if not path.is_file():
        return False
    try:
        return idem in path.read_text(encoding="utf-8")
    except OSError:
        return False


def run_row(opts: argparse.Namespace) -> int:
    row = opts.row
    frame_name = "PING" if str(opts.frame or "").strip().lower() == "ping" else ""
    if frame_name and row != "A1":
        print("ping frame is an A1 variant")
        return 2
    if opts.db and not str(opts.db).startswith("freeze_"):
        print("refused db name")
        return 2
    if opts.url and _bad_url(opts.url):
        print(_bad_url(opts.url))
        return 2
    desk = str(opts.desk or "").strip()
    if not desk:
        print("desk required")
        return 2
    home = Path(opts.home) if getattr(opts, "home", "") else Path(
        os.environ.get("TEMP") or "."
    ) / ("freeze-home-%s" % uuid.uuid4().hex[:8])
    home.mkdir(parents=True, exist_ok=True)
    database = str(opts.db or _db_name(row, frame_name))
    if not database.startswith("freeze_"):
        print("refused db name")
        return 2
    port = _free_port()
    if opts.url:
        from urllib.parse import urlparse

        parsed = urlparse(opts.url)
        if parsed.port:
            port = int(parsed.port)
    _prepare_env(home, database, port)
    if row == "A7":
        os.environ["AGENT_COORD_VENDOR"] = "freeze-sentinel"
    else:
        os.environ["AGENT_COORD_VENDOR"] = "freeze-stub"
    out = _out_dir(opts.out)
    green = _green_path(out, opts.green)
    obs: dict[str, Any] = {
        "frame": frame_name or "todo:TODO",
        "verb": "",
        "wrong": 0,
        "retry": 0,
        "decision": "",
        "mail_rows": 0,
        "fanout": 0,
        "same_req": False,
        "send_runs": 0,
        "sentinel_ran": False,
        "resent_same": False,
        "client_exit": 0,
    }
    err = ""
    code = 0
    try:
        code = _office(opts, row, desk, home, database, port, frame_name, obs)
    except Exception as exc:
        errno = getattr(exc, "errno", None)
        err = "harness %s errno=%s" % (type(exc).__name__, errno)
        code = 2
    finally:
        _drop_db(database)
    if not err:
        result, err = judge(row, obs)
    else:
        result = "red"
    rec = {
        "run_id": uuid.uuid4().hex[:12],
        "row": row,
        "pack": opts.pack or _pack_version(),
        "sha": _sha(),
        "minute": _minute(),
        "frame": obs.get("frame") or "",
        "verb": obs.get("verb") or "",
        "wrong": int(obs.get("wrong") or 0),
        "retry": int(obs.get("retry") or 0),
        "decision": obs.get("decision") or "",
        "err": err,
        "mail_rows": int(obs.get("mail_rows") or 0),
        "fanout": int(obs.get("fanout") or 0),
        "same_req": bool(obs.get("same_req")),
        "result": result if code != 2 else "red",
        "diff": {},
    }
    if code == 2 and not rec["err"]:
        rec["err"] = err or "harness error"
    rec["diff"] = _diff(rec, _load_green(green).get(row) if isinstance(_load_green(green).get(row), dict) else None)
    _append(out, row, rec)
    print(json.dumps(rec, sort_keys=True))
    if code == 2:
        return 2
    return 0 if rec["result"] == "green" else 1


def _office(opts, row, desk, home, database, port, frame_name, obs) -> int:
    _create_db(database)
    from agent_coord.config import settings
    from agent_coord.server.records.db import apply, connect

    if not str(settings()["database"]).startswith("freeze_"):
        raise RuntimeError("refused db name")
    cn = connect(database)
    try:
        apply(cn, wipe=True)
        cn.commit()
        card_id = _seed(cn, desk)
        cn.commit()
    finally:
        cn.close()

    from agent_coord.server.asgi import make_asgi_app
    from agent_coord.server.push import HUB

    import uvicorn

    app = make_asgi_app(api_only=True, host="127.0.0.1", port=port)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    server_thread = threading.Thread(target=server.run, name="freeze-office", daemon=True)
    server_thread.start()
    if not _wait_until(lambda: bool(getattr(server, "started", False)), 30):
        raise RuntimeError("office did not listen")

    secret = _seat(database, desk)
    stop = threading.Event()
    from agent_coord.client.ws import run_ws_loop
    from agent_coord.server.hint_buf import HintBuf, drain_loop

    buf = HintBuf(desk)
    drain = threading.Thread(target=drain_loop, args=(buf, stop), name="freeze-drain", daemon=True)
    drain.start()
    ws = threading.Thread(
        target=run_ws_loop,
        args=(desk, secret, stop, buf),
        name="freeze-ws",
        daemon=True,
    )
    ws.start()
    from agent_coord.client.ws import read_rpc_bridge

    if not _wait_until(lambda: read_rpc_bridge(desk) is not None, 20):
        stop.set()
        raise RuntimeError("desk did not sit")
    _arm(row, home, desk, obs)
    try:
        _inject(desk, card_id, frame_name, obs)
        _act(row, desk, home, opts, obs)
        _collect(row, home, database, obs, float(opts.timeout or 600))
    finally:
        stop.set()
        server.should_exit = True
        server_thread.join(timeout=5)
    return 0


def _seed(cn, desk: str) -> int:
    from agent_coord.server.api.mill.rpc import _h_open
    from agent_coord.server.records import name as rec_name

    rec_name.get_or_insert(cn, "the-mill", "roster")
    rec_name.get_or_insert(cn, desk, "desk")
    rec_name.get_or_insert(cn, "freeze-peer", "desk")

    class _Book:
        def __init__(self, conn):
            self._cn = conn

    rec = _h_open(
        _Book(cn),
        {"need": "freeze-card", "detail": "seed"},
        "the-mill",
        desk,
    )
    return int(rec.get("id") or 0)


def _seat(database: str, desk: str) -> str:
    import secrets

    from agent_coord.client.tokens import token_hash, write_session_token
    from agent_coord.server.records import join as rec_join
    from agent_coord.server.records.db import connect

    secret = secrets.token_urlsafe(24)
    cn = connect(database)
    try:
        rec_join.upsert(cn, "the-mill", desk, "", token_hash(secret), None)
        cn.commit()
    finally:
        cn.close()
    write_session_token(desk, secret)
    return secret


def _arm(row: str, home: Path, desk: str, obs: dict[str, Any]) -> None:
    if row == "A2":
        from agent_coord.helpers.errors import CoordError
        from agent_coord.server.api.mill import rpc

        orig = rpc.HANDLERS["todo"]
        state = {"left": 1, "first": None, "second": None}

        def refuse_once(c, body, project, owner):
            if state["left"]:
                state["left"] = 0
                state["first"] = {k: body.get(k) for k in body if k != "verb"}
                raise CoordError(TODO_REFUSAL)
            state["second"] = {k: body.get(k) for k in body if k != "verb"}
            return orig(c, body, project, owner)

        rpc.HANDLERS["todo"] = refuse_once
        obs["_a2"] = state
    if row == "A7":
        from agent_coord.client.route_chain import save_routes

        marker = home / "sentinel-ran"
        script = home / "sentinel.py"
        script.write_text(
            "import os\nfrom pathlib import Path\n"
            "Path(os.environ['FREEZE_SENTINEL']).write_text('ran', encoding='utf-8')\n",
            encoding="utf-8",
        )
        os.environ["FREEZE_SENTINEL"] = str(marker)
        noop = subprocess.list2cmdline([sys.executable, "-c", "raise SystemExit(0)"])
        sentinel = subprocess.list2cmdline([sys.executable, str(script)])
        save_routes(desk, {"todo:TODO": noop})
        from agent_coord.client.connectors.spawn import spawn_path

        spawn = spawn_path(desk)
        spawn.parent.mkdir(parents=True, exist_ok=True)
        spawn.write_text("todo:TODO = %s\n" % sentinel, encoding="utf-8")
        obs["marker"] = str(marker)
    if row == "F3":
        from agent_coord.server.api.mill import rpc
        from agent_coord.server import push as push_mod

        orig = rpc.HANDLERS["send"]
        state = {"runs": 0}

        def slow_send(c, body, project, owner):
            state["runs"] += 1
            if state["runs"] == 1:
                time.sleep(SEND_DELAY_S)
            return orig(c, body, project, owner)

        rpc.HANDLERS["send"] = slow_send
        orig_emit = push_mod.emit

        def count_emit(*args, **kwargs):
            # push_mail passes reason= and room= by keyword (#795).
            kind = args[2] if len(args) > 2 else kwargs.get("kind")
            if kind == "mail":
                obs["fanout"] = int(obs.get("fanout") or 0) + 1
            return orig_emit(*args, **kwargs)

        push_mod.emit = count_emit
        obs["_f3"] = state


def _inject(desk: str, card_id: int, frame_name: str, obs: dict[str, Any]) -> None:
    from agent_coord.server.push import HUB

    if frame_name == "PING":
        HUB.notify(desk, {"type": "heartbeat", "id": 0, "hint": "PING"})
        obs["frame"] = "PING"
        return
    idem = "freeze-%s" % uuid.uuid4().hex[:8]
    obs["idem"] = idem
    obs["frame"] = "todo:TODO"
    HUB.notify(
        desk,
        {
            "type": "todo",
            "id": int(card_id or 0),
            "hint": "TODO",
            "idem": idem,
            "detail": "freeze",
        },
    )


def _act(row: str, desk: str, home: Path, opts, obs: dict[str, Any]) -> None:
    if opts.agent_cmd:
        _run_agent(opts.agent_cmd, home, obs, float(opts.timeout or 600))
        return
    if row == "A1" and obs.get("frame") == "PING":
        time.sleep(2)
        return
    if row == "A7":
        return
    idem = str(obs.get("idem") or "")
    _wait_until(lambda: _hint_seen(home, desk, idem), 15)
    if row == "A1":
        _call({"verb": "todo", "project": "the-mill"})
        return
    if row == "A2":
        first = {"verb": "todo", "project": "the-mill", "status": "open"}
        second = {"verb": "todo", "project": "the-mill", "status": "open", "done": "1"}
        try:
            _call(first)
        except Exception:
            pass
        try:
            _call(second)
        except Exception:
            pass
        state = obs.get("_a2") or {}
        obs["resent_same"] = state.get("first") is not None and state.get("first") == state.get("second")
        return
    if row == "F3":
        body = {
            "verb": "send",
            "project": "the-mill",
            "body": "freeze f3",
            "dst": "freeze-peer",
        }
        ids = [_call_id(body), _call_id(body)]
        obs["same_req"] = bool(ids[0]) and ids[0] == ids[1]


def _call(body: dict[str, Any]) -> str:
    from agent_coord.client.ws import mill_ws_call

    out = mill_ws_call(dict(body))
    return str((out or {}).get("id") or "")


def _call_id(body: dict[str, Any]) -> str:
    from agent_coord.helpers.errors import CoordError

    try:
        return _call(body)
    except CoordError as exc:
        env = exc.envelope if isinstance(exc.envelope, dict) else {}
        return str(env.get("id") or "")
    except Exception:
        return ""


def _run_agent(cmd: str, home: Path, obs: dict[str, Any], timeout: float) -> None:
    proc = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(home),
    )
    err = proc.stderr or ""
    if proc.returncode and "invalid choice" in err:
        note_client_exit(home, int(proc.returncode), "A2")
        obs["client_exit"] = int(proc.returncode)


def _collect(row: str, home: Path, database: str, obs: dict[str, Any], timeout: float) -> None:
    if row == "F3":
        obs["send_runs"] = int((obs.get("_f3") or {}).get("runs") or 0)
    if row == "A7":
        marker = Path(str(obs.get("marker") or ""))
        deadline = time.monotonic() + min(timeout, 30)
        while time.monotonic() < deadline:
            if _decision(_perf_text(home)) == "work":
                break
            time.sleep(0.05)
        obs["sentinel_ran"] = marker.is_file()
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _wake(_perf_text(home)):
                break
            if row == "A1" and obs.get("frame") == "PING" and time.monotonic() + timeout - deadline > 2:
                break
            time.sleep(0.05)
    text = _perf_text(home)
    wake = _wake(text)
    if wake:
        obs["verb"] = str(wake.get("verb") or "")
        obs["wrong"] = int(wake.get("wrong") or 0)
        obs["retry"] = int(wake.get("retry") or 0)
    obs["decision"] = _decision(text)
    if row == "F3":
        obs["mail_rows"] = _mail_count(database)
        obs["send_runs"] = int((obs.get("_f3") or {}).get("runs") or 0)


def _mail_count(database: str) -> int:
    from agent_coord.server.records.db import connect

    cn = connect(database)
    try:
        cur = cn.cursor()
        cur.execute("SELECT COUNT(*) FROM mail")
        row = cur.fetchone()
        cur.close()
    finally:
        cn.close()
    return int(row[0] if row else 0)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="freeze_harness.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("row", choices=ROWS)
    run.add_argument("--desk", default="")
    run.add_argument("--agent-cmd", default="")
    run.add_argument("--pack", default="")
    run.add_argument("--timeout", type=float, default=600)
    run.add_argument("--out", default="")
    run.add_argument("--green", default="")
    run.add_argument("--frame", default="")
    run.add_argument("--db", default="")
    run.add_argument("--url", default="")
    run.add_argument("--home", default="")
    comp = sub.add_parser("compare")
    comp.add_argument("row", choices=ROWS)
    comp.add_argument("--out", default="")
    comp.add_argument("--green", default="")
    bless = sub.add_parser("bless")
    bless.add_argument("row", choices=ROWS)
    bless.add_argument("run_id")
    bless.add_argument("--out", default="")
    bless.add_argument("--green", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    why = _refuse(raw)
    if why:
        print(why)
        return 2
    try:
        opts = _parser().parse_args(raw)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2
    if opts.cmd == "compare":
        out = _out_dir(opts.out)
        return cmd_compare(opts.row, out, _green_path(out, opts.green))
    if opts.cmd == "bless":
        out = _out_dir(opts.out)
        return cmd_bless(opts.row, opts.run_id, out, _green_path(out, opts.green))
    return run_row(opts)


if __name__ == "__main__":
    sys.exit(main())
