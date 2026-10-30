"""Three office installs. Coding agents write configs and enable OS units.

They do not host the book or the wall in a chat.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_coord.config import DEFAULTS, config_path, settings

ROLES = ("book", "records", "wall", "desk", "check", "cloud", "server", "client")
HTTP_KINDS = ("service", "nginx", "caddy", "iis", "litespeed")
MIN_PY = (3, 10)


def mill_agent_mode(flag: bool | None = None) -> bool:
    """True when mill --agent / MILL_AGENT=1 / install --agent. Hidden UAC path."""
    if flag:
        return True
    v = (os.environ.get("MILL_AGENT") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def consume_mill_agent(argv: list[str] | None) -> list[str]:
    """mill --agent <cmd> sets MILL_AGENT=1. Subcommand --agent NAME is unchanged."""
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "--agent":
        os.environ["MILL_AGENT"] = "1"
        return raw[1:]
    return raw


def mill_ca_crt(dest: Path | None = None) -> Path:
    """Office mill CA. Trust this file; never import wall.crt."""
    return (dest or office_dir()) / "ssl" / "ca.crt"


def slash_compat_path(value: str | Path) -> Path:
    """Accept / and \\\\ fixtures on Windows/WSL. Real Path; use tmp_path, not Users/home."""
    raw = str(value or "")
    if not raw:
        return Path(raw)
    if os.name == "nt":
        return Path(raw.replace("/", "\\"))
    return Path(raw.replace("\\", "/"))


def ios_wall_contract(html: str, css: str) -> bool:
    """iOS is Safari on the Wall: viewport + apple-mobile meta in HTML, 720px in CSS."""
    return (
        'name="viewport"' in html
        and "width=device-width" in html
        and "apple-mobile-web-app" in html
        and "max-width: 720px" in css
    )


def _ios_wall_ok(dest: Path) -> bool:
    html = ""
    css = ""
    for p in (
        wall_ui_default_dir() / "board.html",
        dest / "www" / "board.html",
        static_dir() / "board.html",
    ):
        if p.is_file():
            html = p.read_text(encoding="utf-8")
            break
    for p in (
        wall_ui_default_dir() / "board.css",
        dest / "www" / "board.css",
        static_dir() / "board.css",
    ):
        if p.is_file():
            css = p.read_text(encoding="utf-8")
            break
    return ios_wall_contract(html, css)


def launch_hidden_scm_helper(
    helper: Path,
    *,
    run_cmd: Any = None,
    already_admin: bool | None = None,
) -> list[str]:
    """Agent apply: Hidden UAC helper Wait + auto-exit. Do not close a human Admin window."""
    admin = windows_is_admin() if already_admin is None else bool(already_admin)
    argv = elevate_windows_scm_helper_argv(helper, already_admin=admin)
    runner = run_cmd or subprocess.run
    rec = runner(list(argv), capture_output=True, text=True)
    code = getattr(rec, "returncode", 0) if rec is not None else 0
    if code not in (0, None):
        err = ((getattr(rec, "stderr", "") or "") + "\n" + (getattr(rec, "stdout", "") or "")).strip()
        return [f"FAILED: Hidden UAC helper {err[:160]}"]
    return ["Hidden UAC helper (auto-exit)"]


def format_uninstall_lines(result):
    """Short English uninstall report. No home paths, no probe dump."""
    ok = bool((result or {}).get("ok"))
    mutated = bool((result or {}).get("mutated"))
    dry = bool((result or {}).get("dry_run"))
    failed = list((result or {}).get("failed") or [])
    applied = list((result or {}).get("applied") or [])
    plan = (result or {}).get("plan") or {}
    lines = []
    if dry:
        lines.append("mill uninstall: dry-run (no changes)")
    elif ok:
        lines.append("mill uninstall: ok" + (" (changed)" if mutated else ""))
    else:
        lines.append("mill uninstall: FAILED")
    kept, removed, skipped = [], [], []
    for a in plan.get("actions") or []:
        piece = str(a.get("piece") or "")
        act = str(a.get("action") or "")
        if act == "keep":
            kept.append(piece)
        elif act in ("skip",):
            skipped.append(piece)
        elif act in ("unregister", "wipe", "uninstall", "kill"):
            removed.append(piece)
    if kept:
        lines.append("  kept: " + ", ".join(kept))
    if removed:
        lines.append("  removed: " + ", ".join(removed))
    if skipped:
        lines.append("  skipped: " + ", ".join(skipped) + " (absent or not requested)")
    for f in failed:
        # never echo expanded home paths
        lines.append("  fail: " + redact_user_paths(str(f)))
    if not failed and not dry:
        if (result or {}).get("dest"):
            lines.append("  dest wiped")
        if (result or {}).get("packages"):
            lines.append("  packages removed (not Python)")
    # do not include applied cmd lines (they carry paths)
    _ = applied
    return lines

def redact_user_paths(obj):
    """Replace home / user-profile paths with ~ so mill JSON has no home paths."""
    homes = []
    for cand in (
        str(Path.home()),
        os.path.expanduser("~"),
        os.environ.get("USERPROFILE") or "",
        os.environ.get("HOME") or "",
    ):
        c = (cand or "").rstrip("\\/")
        if c and c not in homes:
            homes.append(c)
            try:
                homes.append(str(Path(c).resolve()))
            except Exception:
                pass
    homes = sorted({h for h in homes if len(h) > 2}, key=len, reverse=True)

    def _one(s):
        out = s
        for h in homes:
            out = out.replace(h, "~")
            out = out.replace(h.replace("\\", "/"), "~")
            out = out.replace(h.replace("/", "\\"), "~")
        return out

    if isinstance(obj, str):
        return _one(obj)
    if isinstance(obj, Path):
        return _one(str(obj))
    if isinstance(obj, list):
        return [redact_user_paths(x) for x in obj]
    if isinstance(obj, tuple):
        return [redact_user_paths(x) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_user_paths(v) for k, v in obj.items()}
    return obj




PREFLIGHT_VERDICTS = ("server-ready", "missing-deps", "foreign-only", "already-configured", "python-too-old")


def human_install_warn_lines(
    *,
    nt: bool | None = None,
    wsl: bool | None = None,
) -> list[str]:
    """Short HUMAN install warns. Branch by OS; keep clean (no wipe diary, no wizard novel)."""
    if nt is None or wsl is None:
        plat = detect_platform()
        if nt is None:
            nt = bool(plat.get("nt"))
        if wsl is None:
            wsl = bool(plat.get("wsl"))
    nt = bool(nt)
    wsl = bool(wsl)
    if nt:
        return [
            "HUMAN: This PC: https://127.0.0.1/ and https://localhost/ should open without a warning after install (mill trusts the office CA for this user).",
            "HUMAN: Share LAN/WAN URL on another device may still warn: Advanced -> Proceed. Do not import wall.crt.",
            "HUMAN: Share URL after install is LAN (or WAN) HTTPS - not localhost-first.",
        ]
    lines = [
        "HUMAN: Share LAN/WAN URL on another device may still warn: Advanced -> Proceed. Do not import wall.crt.",
        "HUMAN: Share URL after install is LAN (or WAN) HTTPS - not localhost-first.",
        "HUMAN: sudo may be required for MySQL OS services and systemd mill-wall.",
    ]
    if wsl:
        lines.insert(
            1,
            "HUMAN: WSL must not hijack Windows MySQL on 127.0.0.1:3306; use this-OS book or mill install client.",
        )
    return lines


def print_human_install_warn(*, stream=None, nt: bool | None = None, wsl: bool | None = None) -> list[str]:
    """Print human warn block to stderr (start of mill install server)."""
    lines = human_install_warn_lines(nt=nt, wsl=wsl)
    out = stream if stream is not None else sys.stderr
    bar = "-" * 64
    print(bar, file=out, flush=True)
    for line in lines:
        print(line, file=out, flush=True)
    print(bar, file=out, flush=True)
    return lines


def print_loud_access_denied(detail: str, *, stream=None) -> None:
    """Loud HUMAN Access Denied on stderr immediately (fail-closed still returns FAILED)."""
    out = stream if stream is not None else sys.stderr
    msg = (detail or "").strip() or "Access Denied"
    print(f"HUMAN: Access Denied (Admin/UAC required). {msg}", file=out, flush=True)


def share_wall_urls(
    *,
    public_bind: str = "127.0.0.1",
    public: bool = False,
    private_ips: list[str] | None = None,
) -> list[str]:
    """Reachable Wall share URLs for HUMAN next_steps. Lead with LAN (or WAN); never localhost-first."""
    from agent_coord.server.netbind import is_private_ip, is_wildcard_bind, private_ipv4s

    bind = (public_bind or "").strip() or "127.0.0.1"
    lan = [
        ip
        for ip in (list(private_ips) if private_ips is not None else private_ipv4s())
        if ip and not str(ip).startswith("127.")
    ]
    urls: list[str] = []
    loop = bind in ("127.0.0.1", "localhost", "::1") or bind.startswith("127.")
    wild = is_wildcard_bind(bind)

    # Concrete non-loopback host (LAN IP, WAN IP, or hostname) leads when given or --public.
    if not loop and not wild:
        urls.append(f"https://{bind}/")
    elif public and not loop and not wild:
        urls.append(f"https://{bind}/")
    if not urls and lan:
        urls.append(f"https://{lan[0]}/")
    for ip in lan:
        u = f"https://{ip}/"
        if u not in urls:
            urls.append(u)
    local = "https://127.0.0.1/"
    if local not in urls:
        urls.append(local)
    # Never lead with localhost when another URL exists.
    if len(urls) > 1 and urls[0] == local:
        urls = [u for u in urls if u != local] + [local]
    return urls


def with_session_hash(url: str) -> str:
    """Human share URL fragment #session. Probe URLs stay unhashed."""
    u = (url or "").strip()
    if not u or "#session" in u:
        return u
    if "#" in u:
        return u
    return u.rstrip("/") + "/#session"


def mill_source_tree(cwd: Path | None = None) -> bool:
    """True when cwd is the mill source tree (pyproject name the-mill + agent_coord)."""
    here = Path(cwd or Path.cwd()).resolve()
    if not (here / "agent_coord").is_dir():
        return False
    pyproject = here / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "the-mill"' in text or "name = 'the-mill'" in text


def update_pip_cmd() -> list[str]:
    """PyPI bump only. Never pip install ."""
    cmd = [sys.executable or "python", "-m", "pip", "install", "-U"]
    if os.name != "nt" and getattr(sys, "prefix", "") == getattr(sys, "base_prefix", ""):
        cmd.append("--break-system-packages")
    cmd.append("the-mill")
    return cmd


def wall_stop_cmds() -> list[list[str]]:
    """Stop mill-wall before pip so site-packages are not locked. sudo -n on Linux."""
    if os.name == "nt":
        return [["sc", "stop", "mill-wall"]]
    return [["sudo", "-n", "systemctl", "stop", "mill-wall"]]


def wall_start_cmds() -> list[list[str]]:
    """Start mill-wall after pip. sudo -n on Linux (never hang on a password prompt)."""
    if os.name == "nt":
        return [["sc", "start", "mill-wall"]]
    return [["sudo", "-n", "systemctl", "start", "mill-wall"]]


def wall_query_cmds() -> list[list[str]]:
    """Read mill-wall state. Windows sc query; Linux systemctl is-active."""
    if os.name == "nt":
        return [["sc", "query", "mill-wall"]]
    return [["systemctl", "is-active", "mill-wall"]]


def wall_service_state(text: str, code: int = 0) -> str:
    """absent, stopped, pending, running, or unknown."""
    blob = text or ""
    low = blob.lower()
    if (
        "does not exist" in low
        or "1060" in low
        or "could not be found" in low
        or "not-found" in low
        or "not found" in low
    ):
        return "absent"
    if "stop_pending" in low or "start_pending" in low or "deactivating" in low or "activating" in low:
        return "pending"
    upper = blob.upper()
    if "STOPPED" in upper or "inactive" in low or low.strip() in {"failed", "dead"}:
        return "stopped"
    if "RUNNING" in upper or low.strip() == "active":
        return "running"
    _ = code
    return "unknown"


def _wait_wall_stopped(runner, *, wait_s: float, poll_s: float) -> tuple[bool, str]:
    """Stop mill-wall and do not return until it is STOPPED or absent.

    sc stop on Windows returns at STOP_PENDING. Pip waits for STOPPED.
    """
    query = wall_query_cmds()[0]
    deadline = time.monotonic() + max(0.0, float(wait_s))
    issued = False
    last = "unknown"
    while True:
        try:
            rec = runner(list(query), check=False, capture_output=True, text=True)
        except OSError as e:
            return False, str(e)
        text = (getattr(rec, "stdout", None) or "") + "\n" + (getattr(rec, "stderr", None) or "")
        code = int(getattr(rec, "returncode", 1) or 0)
        state = wall_service_state(text, code)
        if state in ("absent", "stopped"):
            return True, ""
        last = state
        if not issued:
            for step in wall_stop_cmds():
                try:
                    runner(list(step), check=False, capture_output=True, text=True)
                except OSError as e:
                    return False, str(e)
            issued = True
            continue
        if time.monotonic() >= deadline:
            return False, f"mill-wall still {last}; pip not run"
        time.sleep(max(0.0, float(poll_s)))


def wall_recycle_cmds() -> list[list[str]]:
    """Stop then start mill-wall. Prefer wall_stop_cmds + wall_start_cmds around pip."""
    return wall_stop_cmds() + wall_start_cmds()


# pip replaces this file. A live `mill connect` locks it on Windows.
CONNECT_HOLDS_MILL = (
    "a running mill connect holds Scripts\\mill.exe; stop that connect before install"
)


def mill_script_exe() -> Path:
    """Console script pip install -U will replace for this interpreter."""
    name = "mill.exe" if os.name == "nt" else "mill"
    return Path(sysconfig.get_path("scripts")) / name


def cmdline_is_connect(command_line: str) -> bool:
    """True when an argv word is connect (a live mill connect, not update)."""
    for part in (command_line or "").split():
        base = part.strip('"').strip("'")
        leaf = base.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if leaf == "connect":
            return True
    return False


def _image_matches_mill_exe(image: str, exe: Path) -> bool:
    if not image:
        return False
    try:
        got = Path(image).resolve()
        want = exe.resolve()
    except OSError:
        got = Path(image)
        want = exe
    return str(got).casefold() == str(want).casefold()


def _windows_connect_pids(exe: Path, me: int) -> list[int]:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='mill.exe'\" | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise OSError("connect scan failed") from e
    if proc.returncode != 0:
        raise OSError("connect scan failed")
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise OSError("connect scan failed") from e
    rows = data if isinstance(data, list) else [data]
    found: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid == me:
            continue
        image = str(row.get("ExecutablePath") or "")
        # Name filter is already mill.exe. A different path is a different install.
        if image and not _image_matches_mill_exe(image, exe):
            continue
        if cmdline_is_connect(str(row.get("CommandLine") or "")):
            found.append(pid)
    return found


def _posix_connect_pids(exe: Path, me: int) -> list[int]:
    root = Path("/proc")
    if not root.is_dir():
        return []
    try:
        want = str(exe.resolve())
    except OSError:
        want = str(exe)
    found: list[int] = []
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            image = os.readlink(entry / "exe")
        except OSError:
            continue
        image = image.split(" (deleted)", 1)[0]
        if not _image_matches_mill_exe(image, exe) and image != want:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        args = [part.decode("utf-8", "replace") for part in raw.split(b"\x00") if part]
        if any(cmdline_is_connect(arg) for arg in args):
            found.append(pid)
    return found


def default_connect_pids() -> list[int]:
    """Other pids whose image is this interpreter's mill script and argv is connect.

    Read-only. Does not stop those processes.
    """
    exe = mill_script_exe()
    me = os.getpid()
    if os.name == "nt":
        return _windows_connect_pids(exe, me)
    return _posix_connect_pids(exe, me)


def _connect_holders(connect_pids) -> tuple[list[int], str]:
    fn = default_connect_pids if connect_pids is None else connect_pids
    try:
        raw = fn()
    except OSError:
        return [], "could not check for a running mill connect"
    pids: list[int] = []
    for item in raw or []:
        try:
            pid = int(item)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.append(pid)
    return pids, ""


def wall_import_check_cmd() -> list[str]:
    """Import the installed package and the ASGI app. Not an HTTP probe."""
    code = (
        "import agent_coord; "
        "from agent_coord.server.asgi import make_asgi_app; "
        "raise SystemExit(0 if callable(make_asgi_app) else 1)"
    )
    return [sys.executable or "python", "-c", code]


def sql_install_cmd(*, apply: bool) -> list[str]:
    """mill install sql with the pack just installed: check the book's SQL stamp;
    apply adds --apply (migrate.ensure, the one migration entry). mill update
    passes apply=False: it flags stale SQL and never applies it (#616)."""
    cmd = [sys.executable or "python", "-m", "agent_coord", "install", "sql"]
    return cmd + ["--apply"] if apply else cmd


SQL_STALE_NEXT = (
    "SQL is not applied by mill update. Back up the book and run the throwaway A/B"
    " (BUILD.md), then run: mill install sql --apply. /health is 503 while the"
    " book's SQL is not this pack's."
)


def _sql_check(rec) -> tuple[str, dict[str, str], str]:
    """Read mill install sql (no apply): schema current|stale|unchecked, book/pack, error."""
    code = int(getattr(rec, "returncode", 1) or 0)
    if code == 0:
        return "current", {}, ""
    out = getattr(rec, "stdout", None) or ""
    try:
        row = json.loads(out)
    except (TypeError, ValueError):
        row = None
    if isinstance(row, dict) and row.get("ok") is False and "book" in row:
        st = {"book": str(row.get("book") or ""), "pack": str(row.get("pack") or "")}
        return "stale", st, "book SQL is not this pack's (book %s, pack %s); run: mill install sql --apply" % (
            st["book"] or "none",
            st["pack"],
        )
    err = (getattr(rec, "stderr", None) or out or "")[:300].strip() or f"sql check exit {code}"
    return "unchecked", {}, err + "; the SQL stamp was not read. Check the book, then run: mill install sql"


def update_plan(*, cwd: Path | None = None, dest: Path | None = None) -> dict[str, Any]:
    """Dry-run mill update. Refuse mill source tree; reuse dest; no wipe/smash."""
    here = Path(cwd or Path.cwd()).resolve()
    office = dest or office_dir()
    already = (office / "config.toml").is_file()
    base: dict[str, Any] = {
        "cwd": str(here),
        "dest": str(office),
        "dest_action": "keep" if already else "absent",
        "wipe": False,
        "smash": False,
        "schema": "not-run",
        "cmd": update_pip_cmd(),
        "sql": sql_install_cmd(apply=False),
        "recycle": wall_recycle_cmds(),
    }
    if mill_source_tree(here):
        return {
            **base,
            "ok": False,
            "refused": "mill-source-tree",
            "reason": "mill update refuses mill git/source tree; pack/PyPI only (not pip install .)",
        }
    return {
        **base,
        "ok": True,
        "note": "non-git cwd pip install -U the-mill; does not smash dest",
        "skill": "after mill update: copy the pack skill.md (path in the mill join note) over mill-desk/SKILL.md (mill briefing howto-ai). Restart the TUI.",
    }


def run_update(
    *,
    apply: bool = True,
    cwd: Path | None = None,
    dest: Path | None = None,
    run_cmd=None,
    private_ips: list[str] | None = None,
    already_admin: bool | None = None,
    stop_wait_s: float = 30.0,
    stop_poll_s: float = 0.25,
    connect_pids=None,
) -> dict[str, Any]:
    """pip -U the-mill from a non-mill cwd.

    Refuse when a mill connect holds the console script. Then stop, pip,
    import the new package, check its SQL (never apply it), then start. Never
    wipes. A failed pip or import does not start the wall; stale SQL is flagged.
    """
    plan = update_plan(cwd=cwd, dest=dest)
    urls = [with_session_hash(u) for u in share_wall_urls(private_ips=private_ips)]
    plan["share_urls"] = urls
    plan["url"] = urls[0] if urls else with_session_hash("https://127.0.0.1/")
    plan["pip_applied"] = False
    plan["restart_ok"] = False
    if not plan.get("ok"):
        plan["applied"] = False
        return plan
    if not apply:
        plan["applied"] = False
        plan["dry_run"] = True
        return plan
    # Windows: Admin check up front (service stop/start needs elevation).
    if update_requires_admin():
        admin = windows_is_admin() if already_admin is None else bool(already_admin)
        if not admin:
            return {
                **plan,
                "ok": False,
                "applied": False,
                "pip_applied": False,
                "restart_ok": False,
                "refused": "not-admin",
                "reason": "mill update needs Admin to stop/start mill-wall; re-run from an elevated console",
                "error": "not elevated Admin",
            }
    runner = run_cmd or subprocess.run
    cmd = list(plan["cmd"])
    if "." in cmd[4:] or cmd[-1] == ".":
        return {
            **plan,
            "ok": False,
            "applied": False,
            "pip_applied": False,
            "restart_ok": False,
            "reason": "refused pip install . as update",
        }

    # Before stop: a live connect locks Scripts\mill.exe. Do not kill it.
    holders, scan_err = _connect_holders(connect_pids)
    if scan_err:
        return {
            **plan,
            "ok": False,
            "applied": False,
            "pip_applied": False,
            "restart_ok": False,
            "refused": "connect-scan-failed",
            "error": scan_err,
            "wall_restart": "skipped",
        }
    if holders:
        return {
            **plan,
            "ok": False,
            "applied": False,
            "pip_applied": False,
            "restart_ok": False,
            "refused": "connect-holds-mill",
            "error": CONNECT_HOLDS_MILL,
            "wall_restart": "skipped",
        }

    def _run_steps(steps: list[list[str]], *, label: str) -> tuple[bool, str]:
        for step in steps:
            try:
                rec = runner(list(step), check=False, capture_output=True, text=True)
            except OSError as e:
                return False, str(e)
            rec_code = int(getattr(rec, "returncode", 1) or 0)
            if rec_code != 0:
                err = (getattr(rec, "stderr", None) or getattr(rec, "stdout", None) or "")[:300]
                return False, err.strip() or f"{label} exit {rec_code}"
        return True, ""

    # Order: stop, wait until STOPPED, then pip, then start.
    # A failed or pending stop does not run pip (the wall must not serve mid-upgrade).
    stopped, stop_err = _wait_wall_stopped(runner, wait_s=stop_wait_s, poll_s=stop_poll_s)
    plan["wall_stop"] = "ok" if stopped else "failed"
    if not stopped:
        plan["ok"] = False
        plan["applied"] = False
        plan["pip_applied"] = False
        plan["restart_ok"] = False
        plan["wall_stop_error"] = stop_err
        plan["error"] = stop_err or "mill-wall did not reach STOPPED; pip not run"
        plan["wall_restart"] = "skipped"
        return plan

    try:
        proc = runner(cmd, check=False, capture_output=True, text=True)
    except OSError as e:
        return {
            **plan,
            "ok": False,
            "applied": False,
            "pip_applied": False,
            "restart_ok": False,
            "error": str(e),
            "wall_restart": "skipped",
        }
    code = int(getattr(proc, "returncode", 1) or 0)
    plan["pip_exit"] = code
    plan["pip_applied"] = code == 0
    plan["applied"] = code == 0
    if code != 0:
        err = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "")[:300]
        plan["ok"] = False
        plan["error"] = err.strip() or f"pip exit {code}"
        plan["wall_restart"] = "skipped"
        plan["restart_ok"] = False
        return plan

    check_ok, check_err = _run_steps([wall_import_check_cmd()], label="import check")
    if not check_ok:
        plan["ok"] = False
        plan["restart_ok"] = False
        plan["wall_restart"] = "skipped"
        plan["error"] = check_err or "import check failed; mill-wall not started"
        return plan
    # #616: check the book's SQL with the new pack; never apply it here. A stale
    # book is flagged (exit 1, the apply command) and the wall still starts:
    # its /health answers 503 naming the same command until the SQL is applied.
    try:
        sql_rec = runner(sql_install_cmd(apply=False), check=False, capture_output=True, text=True)
    except OSError as e:
        schema, sql_seen, sql_err = "unchecked", {}, f"{e}; the SQL stamp was not read. Check the book, then run: mill install sql"
    else:
        schema, sql_seen, sql_err = _sql_check(sql_rec)
    plan["schema"] = schema
    if sql_seen:
        plan["sql"] = sql_seen
    start_ok, start_err = _run_steps(wall_start_cmds(), label="wall start")
    plan["restart_ok"] = start_ok
    plan["wall_restart"] = "ok" if start_ok else "failed"
    if not start_ok:
        plan["ok"] = False
        plan["error"] = (
            start_err
            or "wall start failed after pip; mill-wall is down - start it manually"
        )
    if sql_err:
        plan["ok"] = False
        plan["error"] = "; ".join(x for x in (plan.get("error"), sql_err) if x)
    plan["next"] = [
        f"Share URL (HTTPS): {plan['url']}",
        "mill install check (probe/reuse dest; no smash)",
        "Does not smash dest or mill-wall SCM",
        "SQL is a separate step: mill update checks the book's SQL and never applies it.",
        "Copy mill desk skill: the pack skill.md (path in the mill join note) over mill-desk/SKILL.md (mill briefing howto-ai). Restart the TUI.",
    ]
    if schema != "current":
        plan["next"].insert(0, SQL_STALE_NEXT)
    if plan.get("pip_applied") and not plan.get("restart_ok"):
        plan["next"].insert(
            0,
            "pip applied but mill-wall start failed; wall is down - fix service then start mill-wall",
        )
    return plan


def mill_wall_service_binpath(
    *,
    python: str,
    bind: str = "127.0.0.1",
    port: int = 8765,
    api_only: bool = False,
) -> str:
    """binPath for sc create mill-wall (quotes for paths with spaces)."""
    py = str(python or "python").strip() or "python"
    extra = " --api-only" if api_only else ""
    # sc create wants the whole command line; quote python when it has spaces.
    if " " in py:
        exe = f'"{py}"'
    else:
        exe = py
    return f"{exe} -m agent_coord.server.win_wall_svc --bind {bind} --port {int(port)}{extra}"


def windows_scm_register_ps1(
    *,
    python: str = "",
    bind: str = "127.0.0.1",
    port: int = 8765,
    api_only: bool = True,
) -> str:
    """Elevated helper: WinGet leaves binaries; Admin SCM register is required.

    Registers mill-wall as a Windows SERVICE (nssm-free via
    python -m agent_coord.server.win_wall_svc). May start existing MySQL84 (mill book).
    mill-wall SERVICE only. Not schtasks. Hidden + auto-exit.
    """
    py = (python or "").strip() or "python"
    binpath = mill_wall_service_binpath(python=py, bind=bind, port=port, api_only=api_only)
    bin_ps = binpath.replace("'", "''")
    py_ps = py.replace("'", "''")
    # Build as list then join so backslashes stay literal (no invalid escape warnings).
    lines = [
        "# mill: register mill-wall Windows SERVICE (Admin/UAC).",
        "# WinGet/MSI packages leave binaries only - packages are not services.",
        "# mill-wall is a Windows SERVICE (sc create), not ONLOGON schtasks powershell.",
        "# Launch Hidden + auto-exit. Do not leave a console - closing it must not be a human step.",
        "# MySQL84 start only if already the mill book.",
        '$ErrorActionPreference = "Continue"',
        'Write-Host "HUMAN: packages != services. Registering SCM (Admin required)."',
        "$mysqld = Get-Command mysqld.exe -ErrorAction SilentlyContinue",
        "if ($mysqld) {",
        '  $dataDir = Join-Path $env:ProgramData "MySQL\\MySQL Server 8.4\\Data"',
        "  if (-not (Test-Path $dataDir)) {",
        "    & $mysqld.Source --initialize-insecure",
        "  }",
        "  & $mysqld.Source --install MySQL84",
        '  Write-Host "MySQL84: set root password to mill default (config password) after first start."',
        "} else {",
        '  Write-Host "mysqld.exe not on PATH; install MySQL via winget/MSI first."',
        "}",
        "# mill-wall Windows SERVICE (nssm-free service wrapper; not schtasks)"
        f"$py = '{py_ps}'",
        "$svc = 'mill-wall'",
        f"$binPath = '{bin_ps}'",
        "$q = sc.exe query $svc 2>&1",
        "if ($LASTEXITCODE -ne 0) {",
        '  sc.exe create $svc binPath= $binPath start= auto DisplayName= "mill wall API" | Out-Null',
        '  sc.exe description $svc "mill wall API (FastAPI behind nginx TLS)" | Out-Null',
        "  sc.exe failure $svc reset= 86400 actions= restart/5000/restart/5000/restart/5000 | Out-Null",
        '  Write-Host "sc create mill-wall SERVICE"',
        "} else {",
        "  sc.exe config $svc binPath= $binPath start= auto | Out-Null",
        '  Write-Host "sc config mill-wall SERVICE"',
        "}",
        "# Prefer SERVICE over leftover ONLOGON schtasks (Ctrl+C 0xC000013A)",
        "schtasks /Delete /TN mill-wall /F 2>$null | Out-Null",
        "sc.exe start MySQL84 2>$null | Out-Null",
        "sc.exe start mill-wall 2>$null | Out-Null",
        'Write-Host "SCM: mill-wall SERVICE (MySQL84 started if present)"',
        'Write-Host "Done. Helper auto-exit."',
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def write_windows_scm_helper(
    dest: Path,
    *,
    python: str | None = None,
    bind: str = "127.0.0.1",
    port: int = 8765,
    api_only: bool = True,
) -> Path:
    """Write elevated SCM register script under dest (template; elevate Hidden + Wait)."""
    path = Path(dest) / "register-windows-services.ps1"
    path.parent.mkdir(parents=True, exist_ok=True)
    py = python or python_exe()
    path.write_text(
        windows_scm_register_ps1(python=py, bind=bind, port=port, api_only=api_only),
        encoding="utf-8",
    )
    return path




def update_requires_admin() -> bool:
    """True when mill update must be elevated (Windows SCM). Overridable in tests."""
    return os.name == "nt"


def windows_is_admin() -> bool:
    """True if this process is already elevated Admin. False on non-Windows."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_windows_scm_helper_argv(
    helper: Path, extra_args: str = "", *, already_admin: bool = False
) -> list[str]:
    """Launch SCM helper.

    already_admin=False (default): Hidden + RunAs + Wait + auto-exit
    (unelevated / agent UAC path). leftover helper windows Hidden.

    already_admin=True: -File in THIS window (no Hidden, no RunAs, no
    Start-Process). Human-created Admin console stays.
    """
    extra = (extra_args or "").strip()
    extra_parts: list[str] = shlex.split(extra, posix=False) if extra else []
    if already_admin:
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            *extra_parts,
        ]
    hp = str(helper)
    arglist = f'-NoProfile -ExecutionPolicy Bypass -File "{hp}"'
    if extra:
        arglist = f"{arglist} {extra}"
    cmd = (
        "Start-Process -FilePath powershell.exe -Command RunAs -WindowStyle Hidden -Wait "
        f"-ArgumentList '{arglist}'"
    )
    return [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-Command",
        cmd,
    ]


def windows_scm_unregister_ps1() -> str:
    """Elevated helper: stop+delete mill-wall SERVICE (+ leftover schtask).

    Hidden + auto-exit (exit 0). mill-wall SERVICE + dest only.
    Do not uninstall Python. Dest wipe only with -Dest.
    """
    lines = [
        "# mill: unregister mill-wall Windows SERVICE (Admin/UAC).",
        "# Already Admin: do the work in this window (no re-elevate).",
        "# Unelevated / double-click: Hidden Start-Process then exit 0.",
        "# mill-wall SERVICE and leftover mill-wall schtask only.",
        "# Stop+delete mill-wall SERVICE and leftover mill-wall schtask.",
        "# Do NOT uninstall Python. Dest wipe only with -Dest.",
        "param(",
        "  [switch]$Dest,",
        '  [string]$DestPath = "",',
        "  [switch]$Packages",
        ")",
        '$ErrorActionPreference = "Continue"',
        'Write-Host "HUMAN: mill uninstall SCM (Admin). In-window if already Admin; else Hidden auto-exit."',
        "$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
        "if (-not $admin) {",
        '  $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`""',
        '  if ($Dest) { $arg += " -Dest" }',
        '  if ($DestPath) { $arg += " -DestPath `"$DestPath`"" }',
        '  if ($Packages) { $arg += " -Packages" }',
        "  Start-Process powershell -Command RunAs -WindowStyle Hidden -Wait -ArgumentList $arg",
        "  exit 0",
        "}",
        "schtasks /End /TN mill-wall /F 2>$null | Out-Null",
        "schtasks /Delete /TN mill-wall /F 2>$null | Out-Null",
        "foreach ($svc in @('mill-wall')) {",
        "  $q = sc.exe query $svc 2>&1",
        "  if ($LASTEXITCODE -eq 0) {",
        "    sc.exe stop $svc 2>$null | Out-Null",
        "    sc.exe delete $svc 2>$null | Out-Null",
        '    Write-Host "sc stop+delete $svc"',
        "  }",
        "}",
        "if ($Dest -and $DestPath) {",
        "  if (Test-Path -LiteralPath $DestPath) {",
        "    Remove-Item -LiteralPath $DestPath -Recurse -Force -ErrorAction SilentlyContinue",
        '    Write-Host "wiped dest $DestPath"',
        "  }",
        "}",
        'if ($Packages) { Write-Host "0.4: mill uninstall is mill-wall + dest" }',
        'Write-Host "Done. Helper auto-exit."',
        "exit 0",
        "",
    ]
    return "\n".join(lines)


def write_windows_scm_unhelper(dest: Path) -> Path:
    """Write elevated SCM unregister script under dest (mirrors write_windows_scm_helper)."""
    path = Path(dest) / "unregister-windows-services.ps1"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(windows_scm_unregister_ps1(), encoding="utf-8")
    return path


def winget_uninstall_argv(package_id: str, *, winget_bin: str = "winget") -> list[str]:
    """Silent unattended winget uninstall argv (mirrors winget_install_argv; not Python)."""
    cmd = [
        winget_bin,
        "uninstall",
        "--id",
        package_id,
        "-e",
        *WINGET_SILENT,
    ]
    if package_id == WINGET_MYSQL_ID:
        cmd.extend(["--override", "/quiet /norestart"])
    return cmd


def uninstall_plan(
    *,
    probe: dict[str, Any] | None = None,
    dest: bool = False,
    packages: bool = False,
    dest_path: Path | None = None,
    nt: bool | None = None,
    wsl: bool | None = None,
    **probe_kwargs: Any,
) -> dict[str, Any]:
    """Probe-first uninstall plan. Skip absent pieces. Never uninstall Python."""
    pr = probe if probe is not None else probe_deps(nt=nt, wsl=wsl, **probe_kwargs)
    plat = pr.get("platform") or {}
    nt = bool(plat.get("nt") if nt is None else nt)
    wsl = bool(plat.get("wsl") if wsl is None else wsl)
    actions: list[dict[str, Any]] = []
    cmds: list[list[str]] = []
    skip: list[str] = []
    reuse: list[str] = []

    actions.append({"piece": "python", "action": "keep", "reason": "never uninstall Python"})

    mysql = pr.get("mysql") or {}
    mill_wall = pr.get("mill_wall") or pr.get("mill_wall_task") or pr.get("wall") or {}
    leftover = list(pr.get("leftover_console") or [])
    off = pr.get("dest") or {}
    raw_dest = dest_path or off.get("dest") or ""
    dest_str = str(slash_compat_path(raw_dest)) if raw_dest else ""
    def _present(row: dict[str, Any]) -> bool:
        if not row:
            return False
        if row.get("ok"):
            return True
        state = str(row.get("state") or "").upper()
        return state not in ("", "ABSENT")

    if _present(mill_wall) or mill_wall.get("ok") is True:
        reuse.append("mill-wall")
        if nt:
            cmd = ["sc", "stop", "mill-wall"]
            actions.append(
                {
                    "piece": "mill-wall",
                    "action": "unregister",
                    "cmd": cmd,
                    "reason": "mill-only: stop+delete mill-wall SERVICE and leftover schtask",
                }
            )
            cmds.append(cmd)
            cmds.append(["sc", "delete", "mill-wall"])
            cmds.append(["schtasks", "/Delete", "/TN", "mill-wall", "/F"])
        else:
            cmd = ["systemctl", "stop", "mill-wall"]
            actions.append(
                {
                    "piece": "mill-wall",
                    "action": "unregister",
                    "cmd": cmd,
                    "reason": "mill-only: systemd stop+disable mill-wall (never sc/winget)",
                }
            )
            cmds.append(cmd)
            cmds.append(["systemctl", "disable", "mill-wall"])
    else:
        skip.append("mill-wall")
        actions.append({"piece": "mill-wall", "action": "skip", "reason": "mill-wall SERVICE/unit absent"})

    skip.append("mysql")
    actions.append(
        {
            "piece": "mysql",
            "action": "skip",
            "reason": "mill dest/book stay unless --dest; OS MySQL is not mill-wall",
        }
    )

    skip.append("leftover-console")
    actions.append(
        {
            "piece": "leftover-console",
            "action": "skip",
            "reason": "never kill mysqld; it may not be mill's",
        }
    )

    dest_exists = bool(off.get("already") or (dest_str and Path(dest_str).exists()))
    if dest and dest_exists:
        reuse.append("dest")
        actions.append(
            {
                "piece": "dest",
                "action": "wipe",
                "cmd": ["rmtree", dest_str],
                "reason": "--dest flag: wipe office dest",
            }
        )
        cmds.append(["rmtree", dest_str])
    else:
        skip.append("dest")
        reason = "dest wipe only with explicit --dest" if not dest else "dest absent"
        actions.append({"piece": "dest", "action": "skip", "reason": reason})

    skip.append("packages")
    actions.append(
        {
            "piece": "packages",
            "action": "skip",
            "reason": "0.4 mill uninstall is mill-wall + dest",
        }
    )

    extra = ""
    if dest and dest_str:
        extra += f' -Dest -DestPath "{dest_str}"'
    if packages:
        extra += " -Packages"
    elevate = None
    if nt and reuse:
        elevate = ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", "Start-Process"]

    return {
        "probe": pr,
        "actions": actions,
        "cmds": cmds,
        "reuse": reuse,
        "skip": skip,
        "dest": bool(dest),
        "packages": bool(packages),
        "dest_path": dest_str,
        "silent": True,
        "wizard": False,
        "elevate_extra": extra.strip(),
        "elevate": elevate,
        "note": "probe-first; mill-wall + dest; never uninstall Python",
    }


def uninstall(
    *,
    apply: bool = False,
    dest: bool = False,
    packages: bool = False,
    dest_path: Path | None = None,
    probe: dict[str, Any] | None = None,
    nt: bool | None = None,
    wsl: bool | None = None,
    run_cmd=None,
    **probe_kwargs: Any,
) -> dict[str, Any]:
    """Dry-run default (JSON plan, no mutate). --apply mutates present pieces only."""
    plan = uninstall_plan(
        probe=probe,
        dest=dest,
        packages=packages,
        dest_path=dest_path,
        nt=nt,
        wsl=wsl,
        **probe_kwargs,
    )
    if not apply:
        return {
            "ok": True,
            "dry_run": True,
            "mutated": False,
            "plan": plan,
            "applied": [],
            "failed": [],
            "dest": bool(dest),
            "packages": bool(packages),
        }

    runner = run_cmd
    applied: list[str] = []
    failed: list[str] = []
    helper_path: Path | None = None
    nt_eff = bool((plan.get("probe") or {}).get("platform", {}).get("nt") if nt is None else nt)
    if nt_eff:
        helper_dir = Path(dest_path) if dest_path else Path(tempfile.gettempdir()) / "mill-uninstall"
        helper_path = write_windows_scm_unhelper(helper_dir)
        extra = plan.get("elevate_extra") or ""
        elevate_cmd = elevate_windows_scm_helper_argv(helper_path, extra_args=extra, already_admin=windows_is_admin())
        plan = dict(plan)
        plan["unhelper"] = str(helper_path)
        plan["elevate_cmd"] = elevate_cmd

    def _run(argv: list[str]) -> None:
        if argv and argv[0] == "rmtree":
            if runner is not None:
                runner(argv)
                applied.append("rmtree " + " ".join(argv[1:]))
                return
            target = Path(argv[1]) if len(argv) > 1 else None
            if target is not None and target.exists():
                shutil.rmtree(target, ignore_errors=True)
                applied.append(f"rmtree {target}")
            return
        if runner is not None:
            rec = runner(argv)
            applied.append(" ".join(str(x) for x in argv))
            code = getattr(rec, "returncode", 0) if rec is not None else 0
            if code not in (0, None):
                err = (getattr(rec, "stderr", "") or getattr(rec, "stdout", "") or "").strip()
                if _scm_needs_admin(err) or code:
                    if _scm_needs_admin(err):
                        print_loud_access_denied(err)
                    failed.append(f"FAILED: {' '.join(str(x) for x in argv)} {err[:160]}")
            return
        rec = subprocess.run(list(argv), capture_output=True, text=True)
        applied.append(" ".join(str(x) for x in argv))
        if rec.returncode != 0:
            err = ((rec.stderr or "") + "\n" + (rec.stdout or "")).strip()
            if _scm_needs_admin(err):
                print_loud_access_denied(err)
            failed.append(f"FAILED: {' '.join(str(x) for x in argv)} {err[:160]}")

    helper_applied_scm = False
    if helper_path is not None:
        extra = plan.get("elevate_extra") or ""
        _run(elevate_windows_scm_helper_argv(helper_path, extra_args=extra, already_admin=windows_is_admin()))
        helper_applied_scm = True
    for action in plan.get("actions") or []:
        if helper_applied_scm and action.get("piece") in ("mill-wall", "mysql") and action.get("action") == "unregister":
            applied.append(f"{action.get('piece')}: unregister via helper (one SCM pass)")
            continue
        if action.get("action") in ("skip", "keep"):
            applied.append(f"{action.get('piece')}: {action.get('action')} ({action.get('reason')})")
            continue
        if action.get("piece") == "packages":
            for c in action.get("cmds") or ([action.get("cmd")] if action.get("cmd") else []):
                if c:
                    _run(list(c))
            continue
        cmd = action.get("cmd")
        if cmd:
            _run(list(cmd))
            if action.get("piece") in ("mill-wall", "mysql") and action.get("action") == "unregister":
                name = {
                    "mill-wall": "mill-wall",
                    "mysql": str(((plan.get("probe") or {}).get("mysql") or {}).get("service") or "MySQL84"),
                }[str(action.get("piece"))]
                _run(["sc", "delete", name])
                if action.get("piece") == "mill-wall":
                    _run(["schtasks", "/Delete", "/TN", "mill-wall", "/F"])

    return {
        "ok": not failed,
        "dry_run": False,
        "mutated": True,
        "plan": plan,
        "applied": applied,
        "failed": failed,
        "dest": bool(dest),
        "packages": bool(packages),
        "unhelper": str(helper_path) if helper_path else None,
    }


def uninstall_office(
    *,
    apply: bool = False,
    dest_wipe: bool = False,
    packages: bool = False,
    dest_path: Path | None = None,
    probe: dict[str, Any] | None = None,
    nt: bool | None = None,
    wsl: bool | None = None,
    run_cmd=None,
    **probe_kwargs: Any,
) -> dict[str, Any]:
    """Alias for uninstall(..., dest=dest_wipe). Dry-run default; mutate nothing unless apply."""
    return uninstall(
        apply=apply,
        dest=dest_wipe,
        packages=packages,
        dest_path=dest_path,
        probe=probe,
        nt=nt,
        wsl=wsl,
        run_cmd=run_cmd,
        **probe_kwargs,
    )


def packaged_scripts_dir() -> Path:
    """Product scripts shipped inside the wheel (Path next to install.py)."""
    return Path(__file__).resolve().parent / "scripts"


WINGET_SILENT = (
    "--disable-interactivity",
    "--accept-package-agreements",
    "--accept-source-agreements",
)

# Silent WinGet package ids (CLI only; no MSI GUI / MySQL Configurator wizard).
WINGET_PYTHON_ID = "Python.Python.3.12"
WINGET_MYSQL_ID = "Oracle.MySQL"


def winget_install_argv(package_id: str, *, winget_bin: str = "winget") -> list[str]:
    """Silent unattended winget install argv (no wizard UI).

    Oracle.MySQL is an MSI: winget flags alone still pop msiexec. --override
    /quiet /norestart is required so the Configurator never opens.
    """
    cmd = [
        winget_bin,
        "install",
        "--id",
        package_id,
        "-e",
        *WINGET_SILENT,
    ]
    if package_id == WINGET_MYSQL_ID:
        cmd.extend(["--override", "/quiet /norestart"])
    return cmd


def apt_install_argv(*packages: str) -> list[str]:
    """Non-interactive apt install argv."""
    return ["sudo", "apt-get", "install", "-y", *packages]


def dnf_install_argv(*packages: str) -> list[str]:
    return ["sudo", "dnf", "install", "-y", *packages]


def apk_install_argv(*packages: str) -> list[str]:
    return ["sudo", "apk", "add", "--no-cache", *packages]


def probe_deps(
    *,
    nt: bool | None = None,
    wsl: bool | None = None,
    py_version: tuple[int, ...] | None = None,
    which_map: dict[str, str] | None = None,
    book_services: list[dict[str, str]] | None = None,
    httpd: dict[str, str] | None = None,
    office: dict[str, Any] | None = None,
    mill_on_path: bool | None = None,
    mysql_service_state: str | None = None,
    wall_service_state: str | None = None,
) -> dict[str, Any]:
    """Probe Python/mill/MySQL/mill-wall/dest. Healthy real OS services -> reuse."""
    plat = detect_platform()
    if nt is None:
        nt = bool(plat.get("nt"))
    if wsl is None:
        wsl = bool(plat.get("wsl"))
    nt = bool(nt)
    wsl = bool(wsl)

    ver = tuple(py_version) if py_version is not None else tuple(sys.version_info[:3])
    py_ok = len(ver) >= 2 and tuple(ver[:2]) >= MIN_PY
    py_row = {
        "ok": py_ok,
        "version": list(ver[:3]) if len(ver) >= 3 else list(ver),
        "min": list(MIN_PY),
        "path": sys.executable if py_version is None else None,
    }

    if mill_on_path is None:
        mill_path = shutil.which("mill") or shutil.which("agent-coord")
    else:
        mill_path = "mill" if mill_on_path else None
    mill_row = {"ok": bool(mill_path), "path": mill_path}

    http = httpd if httpd is not None else detect_httpd_bins(nt=nt, which_map=which_map)
    bk = detect_book_native(services=book_services, nt=nt) if book_services is not None else detect_book_native(nt=nt)
    off = office if office is not None else detect_office_dest()

    if nt:
        mysql_state = mysql_service_state
        if mysql_state is None:
            mysql_state = _windows_service_state("MySQL84")
            if mysql_state == "ABSENT" and bk.get("services"):
                mysql_state = _windows_service_state(str(bk["services"][0].get("name") or "MySQL84"))
        mysql_svc_names = [str(s.get("name") or "") for s in (bk.get("services") or []) if s.get("name")]
        if mysql_state == "RUNNING":
            mysql_ok = True
        elif mysql_state in ("STOPPED", "START_PENDING") and (mysql_svc_names or bk.get("bins")):
            mysql_ok = True
        elif bk.get("present") and mysql_svc_names:
            mysql_ok = True
        else:
            mysql_ok = False
        nginx_row = {
            "ok": bool(http.get("nginx")),
            "service": "nginx",
            "state": "PRESENT" if http.get("nginx") else "ABSENT",
            "bin": http.get("nginx"),
        }
        mysql_row = {
            "ok": bool(mysql_ok),
            "service": (mysql_svc_names[0] if mysql_svc_names else "MySQL84"),
            "state": mysql_state,
            "bins": bk.get("bins") or {},
            "services": bk.get("services") or [],
        }
    else:
        nginx_row = {
            "ok": bool(http.get("nginx")),
            "service": "nginx",
            "state": "PRESENT" if http.get("nginx") else "ABSENT",
            "bin": http.get("nginx"),
        }
        services = list(bk.get("services") or [])
        active = any(str(s.get("status") or "") == "active" for s in services)
        server_bin = any(k in (bk.get("bins") or {}) for k in ("mysqld", "mysqld.exe", "mariadbd", "mariadbd.exe"))
        mysql_row = {
            "ok": bool(active or server_bin),
            "service": "mysql",
            "state": "PRESENT" if (active or server_bin or services) else "ABSENT",
            "bins": bk.get("bins") or {},
            "services": bk.get("services") or [],
            "wsl_no_hijack": bool(wsl),
        }

    wall_ok = bool(off.get("www_exists") or off.get("vhost_exists"))
    wall_svc_state = "N/A"
    if nt:
        wall_svc_state = wall_service_state
        if wall_svc_state is None:
            wall_svc_state = _windows_service_state("mill-wall")
        if wall_svc_state == "RUNNING":
            wall_ok = True
    wall_row = {
        "ok": wall_ok,
        "www_exists": off.get("www_exists"),
        "vhost_exists": off.get("vhost_exists"),
        "service": "mill-wall" if nt else "mill-wall.service",
        "state": wall_svc_state if nt else ("PRESENT" if wall_ok else "ABSENT"),
    }

    missing: list[str] = []
    reuse: list[str] = []
    for key, row in (
        ("python", py_row),
        ("mill", mill_row),
        ("mysql", mysql_row),
    ):
        if row.get("ok"):
            reuse.append(key)
        else:
            missing.append(key)

    return {
        "platform": {"nt": nt, "wsl": wsl, "os": plat.get("os")},
        "python": py_row,
        "mill": mill_row,
        "nginx": nginx_row,
        "mysql": mysql_row,
        "dest": off,
        "wall": wall_row,
        "missing": missing,
        "reuse": reuse,
    }


def ensure_deps_plan(
    *,
    probe: dict[str, Any] | None = None,
    nt: bool | None = None,
    wsl: bool | None = None,
    **probe_kwargs: Any,
) -> dict[str, Any]:
    """Dry-run ensure-deps plan: silent CLI cmds for missing pieces only; reuse healthy."""
    pr = probe if probe is not None else probe_deps(nt=nt, wsl=wsl, **probe_kwargs)
    nt = bool((pr.get("platform") or {}).get("nt") if nt is None else nt)
    wsl = bool((pr.get("platform") or {}).get("wsl") if wsl is None else wsl)
    actions: list[dict[str, Any]] = []
    cmds: list[list[str]] = []

    for piece in pr.get("reuse") or []:
        actions.append({"piece": piece, "action": "reuse", "reason": "present and healthy (real OS service/bin)"})

    missing = list(pr.get("missing") or [])
    if "python" in missing:
        if nt:
            cmd = winget_install_argv(WINGET_PYTHON_ID)
        else:
            cmd = apt_install_argv("python3", "python3-pip", "python3-venv")
        actions.append({"piece": "python", "action": "install", "cmd": cmd, "reason": "missing or too old"})
        cmds.append(cmd)
    if "mill" in missing:
        # Prefer repo pip install . when running from tree; else the-mill
        repo = _repo_cwd()
        if (repo / "pyproject.toml").is_file() and (repo / "agent_coord").is_dir():
            cmd = [sys.executable or "python", "-m", "pip", "install", "."]
        else:
            cmd = [sys.executable or "python", "-m", "pip", "install", "the-mill"]
        actions.append({"piece": "mill", "action": "install", "cmd": cmd, "reason": "mill/agent-coord not on PATH"})
        cmds.append(cmd)
    if "nginx" in missing:
        actions.append(
            {
                "piece": "nginx",
                "action": "skip",
                "reason": "0.4 mill-wall is FastAPI; nginx TLS is optional",
            }
        )
    if "mysql" in missing:
        if nt:
            cmd = winget_install_argv(WINGET_MYSQL_ID)
            actions.append({"piece": "mysql", "action": "install", "cmd": cmd, "reason": "MySQL SCM/bin missing"})
            cmds.append(cmd)
            scm = ["mysqld", "--install", "MySQL84"]
            actions.append({"piece": "mysql-scm", "action": "register", "cmd": scm, "reason": "packages != services; SCM register"})
            cmds.append(scm)
        else:
            if wsl:
                actions.append(
                    {
                        "piece": "mysql",
                        "action": "install-this-os",
                        "cmd": apt_install_argv("mysql-community-server"),
                        "reason": "WSL: install this-OS MySQL 8; do not hijack Windows MySQL on 127.0.0.1:3306",
                    }
                )
            else:
                actions.append(
                    {
                        "piece": "mysql",
                        "action": "install",
                        "cmd": apt_install_argv("mysql-community-server"),
                        "reason": "MySQL 8 missing on this OS",
                    }
                )
            repo = Path(__file__).resolve().parent / "scripts" / "mysql84-ubuntu.sh"
            cmds.append(["sudo", "bash", str(repo)])
            cmd = apt_install_argv("mysql-community-server")
            cmds.append(cmd)
            en = ["sudo", "systemctl", "enable", "--now", "mysql"]
            actions.append({"piece": "mysql-systemd", "action": "enable", "cmd": en, "reason": "systemd enable/start"})
            cmds.append(en)

    # Dest: never smash already-configured
    if (pr.get("dest") or {}).get("already"):
        actions.append(
            {
                "piece": "dest",
                "action": "keep",
                "reason": "already-configured dest; refuse silent rewrite of live office",
            }
        )
    else:
        actions.append({"piece": "dest", "action": "init", "reason": "write ~/.mill office after deps ready"})

    return {
        "probe": pr,
        "actions": actions,
        "cmds": cmds,
        "silent": True,
        "wizard": False,
        "note": "probe then ensure-missing only; reuse healthy OS services; dry-run prints plan without installing",
    }


def ensure_deps(
    *,
    apply: bool = False,
    probe: dict[str, Any] | None = None,
    nt: bool | None = None,
    wsl: bool | None = None,
    run_cmd=None,
    **probe_kwargs: Any,
) -> dict[str, Any]:
    """Ensure missing deps via silent CLI. Reuse healthy. Fail-closed on Access Denied. No wizard."""
    plan = ensure_deps_plan(probe=probe, nt=nt, wsl=wsl, **probe_kwargs)
    if not apply:
        return {"ok": True, "dry_run": True, "mutated": False, "plan": plan, "applied": [], "failed": []}

    runner = run_cmd or (
        lambda argv: subprocess.run(list(argv), capture_output=True, text=True)
    )
    applied: list[str] = []
    failed: list[str] = []
    for action in plan.get("actions") or []:
        if action.get("action") in ("reuse", "keep", "init"):
            applied.append(f"{action.get('piece')}: {action.get('action')} ({action.get('reason')})")
            continue
        cmd = action.get("cmd")
        if not cmd:
            continue
        # Skip Linux apt/dnf in unit tests unless injected; on real apply run them
        try:
            result = runner(cmd)
        except OSError as exc:
            msg = f"FAILED: {action.get('piece')} could not run {cmd!r}: {exc}"
            failed.append(msg)
            continue
        rc = getattr(result, "returncode", 1)
        out = ((getattr(result, "stderr", "") or "") + "\n" + (getattr(result, "stdout", "") or "")).strip()
        if rc != 0:
            if _scm_needs_admin(out):
                print_loud_access_denied(f"{action.get('piece')}: {out.replace(chr(10), ' ')[:160]}")
                failed.append(
                    f"FAILED: {action.get('piece')} SCM/install denied (Admin/UAC). "
                    "Do not use mysqld --console as Pass."
                )
            else:
                failed.append(
                    f"FAILED: {action.get('piece')} exit {rc}: {out.replace(chr(10), ' ')[:200]}"
                )
        else:
            applied.append(f"{action.get('piece')}: ok {' '.join(str(c) for c in cmd[:6])}")

    ok = not failed
    return {
        "ok": ok,
        "dry_run": False,
        "mutated": bool(applied),
        "plan": plan,
        "applied": applied,
        "failed": failed,
    }







def _scm_needs_admin(text: str) -> bool:
    t = (text or "").lower()
    needles = (
        "access is denied",
        "access denied",
        "requires elevation",
        "elevation required",
        "administrator",
        "not privileged",
        "privilege",
        "permission denied",
        "error 5",
        "system error 5",
    )
    return any(n in t for n in needles)


def _windows_service_state(name: str) -> str:
    """Return RUNNING|STOPPED|ABSENT|UNKNOWN from `sc query` (injectable via subprocess)."""
    run = subprocess.run(["sc", "query", name], capture_output=True, text=True)
    out = (run.stdout or "") + (run.stderr or "")
    if run.returncode != 0 and "1060" in out:  # service does not exist
        return "ABSENT"
    upper = out.upper()
    if "RUNNING" in upper:
        return "RUNNING"
    if "STOPPED" in upper or "STOP_PENDING" in upper or "START_PENDING" in upper:
        return "STOPPED" if "START_PENDING" not in upper else "START_PENDING"
    if run.returncode != 0:
        return "ABSENT"
    return "UNKNOWN"


def _start_windows_service(name: str) -> tuple[bool, str]:
    """Start a Windows SCM service. Fail-closed on denial. No console fallback."""
    state = _windows_service_state(name)
    if state == "RUNNING":
        return True, f"{name} Windows service already RUNNING"
    if state == "ABSENT":
        return False, f"FAILED: Windows service {name} not installed (Admin/UAC may be required to create it)."
    run = subprocess.run(["sc", "start", name], capture_output=True, text=True)
    msg = ((run.stderr or "") + "\n" + (run.stdout or "")).strip()
    if run.returncode == 0 or "RUNNING" in msg.upper() or "1056" in msg:  # already starting/running
        # 1056 = service already running
        if _windows_service_state(name) == "RUNNING" or run.returncode == 0 or "1056" in msg:
            return True, f"{name} Windows service started (SCM)"
    if _scm_needs_admin(msg) or run.returncode != 0:
        detail = msg.replace("\n", " ")[:160] if msg else f"exit {run.returncode}"
        print_loud_access_denied(f"{name}: {detail}")
        return (
            False,
            f"FAILED: {name} SCM start denied or failed (Admin/UAC required). {detail}. "
            "Do not use console mysqld as Pass.",
        )
    if _windows_service_state(name) != "RUNNING":
        return (
            False,
            f"FAILED: {name} service not RUNNING after SCM start (Admin/UAC required). "
            "Do not use console servers as Pass.",
        )
    return True, f"{name} Windows service started (SCM)"


def python_too_old(*, py_version: tuple[int, ...] | None = None) -> dict[str, Any] | None:
    """Refuse payload when interpreter is below MIN_PY; None if OK. Injectable for tests."""
    ver = tuple(py_version) if py_version is not None else tuple(sys.version_info[:2])
    if len(ver) < 2:
        ver = (ver[0], 0) if ver else (0, 0)
    if ver >= MIN_PY:
        return None
    major, minor = int(ver[0]), int(ver[1])
    return {
        "verdict": "python-too-old",
        "ok_apply": False,
        "hints": [
            f"Python {major}.{minor} is too old; mill needs Python {MIN_PY[0]}.{MIN_PY[1]}+.",
            "Hint: use uv + CPython 3.12 (e.g. uv python install 3.12; uv venv --python 3.12).",
        ],
        "python": {"major": major, "minor": minor, "min": list(MIN_PY)},
    }


def detect_platform(
    *,
    platform: str | None = None,
    environ: dict[str, str] | None = None,
    proc_version: str | None = None,
) -> dict[str, Any]:
    """Classify OS for install targeting. WSL is Linux, not a green light for a foreign mill-wall."""
    plat = (platform if platform is not None else sys.platform) or ""
    env = environ if environ is not None else os.environ
    wsl = False
    if plat.startswith("linux"):
        if (env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP") or "").strip():
            wsl = True
        else:
            ver = proc_version
            if ver is None:
                try:
                    ver = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    ver = ""
            low = (ver or "").lower()
            if "microsoft" in low or "wsl" in low:
                wsl = True
    if plat.startswith("win"):
        kind = "windows"
    elif plat == "darwin":
        kind = "darwin"
    elif plat.startswith("linux"):
        kind = "wsl" if wsl else "linux"
    else:
        kind = plat or "unknown"
    return {
        "os": kind,
        "platform": plat,
        "wsl": bool(wsl),
        "nt": plat.startswith("win"),
        "posix": not plat.startswith("win"),
    }


def _is_foreign_windows_path(path: str | Path, *, nt: bool | None = None) -> bool:
    """True when path belongs to Windows while we are on POSIX/WSL (or looks like Win PE)."""
    if nt is None:
        nt = os.name == "nt"
    if nt:
        return False
    raw = str(path or "")
    s = raw.replace("\\", "/")
    low = s.lower()
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return True
    if low.startswith("/mnt/") and len(low) >= 6 and low[5].isalpha() and (len(low) == 6 or low[6] == "/"):
        return True
    if low.endswith(".exe"):
        return True
    return False


def _native_which(cmd: str, *, nt: bool | None = None) -> str | None:
    path = shutil.which(cmd)
    if not path:
        return None
    if _is_foreign_windows_path(path, nt=nt):
        return None
    return path


def detect_httpd_bins(
    *,
    which_map: dict[str, str] | None = None,
    candidates: list[str] | None = None,
    nt: bool | None = None,
) -> dict[str, str]:
    """nginx binary on this OS (0.4 TLS edge). mill-wall is FastAPI."""
    if nt is None:
        nt = os.name == "nt"
    found: dict[str, str] = {}
    keys = ("nginx", "nginx.exe")
    if which_map is not None:
        for key in keys:
            path = which_map.get(key)
            if path and not _is_foreign_windows_path(path, nt=nt):
                found["nginx"] = path
                break
    else:
        for key in keys:
            path = _native_which(key, nt=nt)
            if path:
                found["nginx"] = path
                break
    if candidates:
        for cand in candidates:
            if _is_foreign_windows_path(cand, nt=nt):
                continue
            p = Path(cand)
            if p.is_file() and "nginx" in p.name.lower():
                found.setdefault("nginx", str(p))
    return found


def detect_book_native(
    *,
    services: list[dict[str, str]] | None = None,
    bins: dict[str, str] | None = None,
    nt: bool | None = None,
) -> dict[str, Any]:
    """MySQL/MariaDB installed on this OS (service or native binary) - not merely a open port."""
    if nt is None:
        nt = os.name == "nt"
    svc = list(services) if services is not None else _book_services()
    if bins is not None:
        native_bins = {k: v for k, v in bins.items() if v and not _is_foreign_windows_path(v, nt=nt)}
    else:
        native_bins = {}
        for key in ("mysqld", "mariadbd", "mysqld.exe", "mariadbd.exe", "mysql", "mariadb"):
            path = _native_which(key, nt=nt)
            if path:
                native_bins[key] = path
    present = bool(svc) or bool(native_bins)
    return {"present": present, "services": svc, "bins": native_bins}


def detect_office_dest(dest: Path | None = None) -> dict[str, Any]:
    """Existing mill dest under this OS home (never a silent Windows live-office rewrite)."""
    if dest is None:
        cfg = config_path()
        d = office_dir(cfg)
    else:
        d = Path(dest)
        cfg = d / "config.toml"
    www = d / "www"
    vhost = d / "nginx-wall.conf"
    return {
        "dest": str(d),
        "config": str(cfg),
        "config_exists": cfg.is_file(),
        "www_exists": www.is_dir(),
        "vhost_exists": vhost.is_file(),
        "already": cfg.is_file(),
    }


def preflight_server(
    *,
    dest: Path | None = None,
    platform_info: dict[str, Any] | None = None,
    httpd: dict[str, str] | None = None,
    book: dict[str, Any] | None = None,
    reachable: dict[str, Any] | None = None,
    office: dict[str, Any] | None = None,
    host_windows_office: bool = False,
    py_version: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    """Probe before install server --apply. Verdicts include python-too-old|server-ready|missing-deps|foreign-only|already-configured."""
    gate = python_too_old(py_version=py_version)
    if gate is not None:
        off = office if office is not None else detect_office_dest(dest)
        plat = platform_info or detect_platform()
        return {
            "verdict": gate["verdict"],
            "ok_apply": False,
            "platform": plat,
            "httpd": httpd if httpd is not None else {},
            "book": book if book is not None else {},
            "reachable": reachable if reachable is not None else {},
            "office": off,
            "hints": list(gate["hints"]),
            "plan": {
                "dest": off.get("dest"),
                "config": off.get("config"),
                "would_write": [],
                "apply_targets": "none (python too old)",
            },
            "python": gate.get("python"),
            "foreign_httpd_refused": [],
        }
    plat = platform_info or detect_platform()
    http = httpd if httpd is not None else detect_httpd_bins(nt=bool(plat.get("nt")))
    bk = book if book is not None else detect_book_native(nt=bool(plat.get("nt")))
    reach = reachable if reachable is not None else _book_reachable()
    off = office if office is not None else detect_office_dest(dest)
    hints: list[str] = []
    foreign_httpd = []
    # surface foreign-only httpd that we refused
    if not http.get("nginx") and plat.get("wsl") and not host_windows_office:
        hints.append("WSL: use this-OS nginx or mill-wall --http service.")
    foreign_book = bool(reach.get("ok")) and not bool(bk.get("present"))
    missing_book = not bool(bk.get("present")) and not bool(reach.get("ok"))
    has_httpd = bool(http.get("nginx"))
    # service-mode wall is OK without nginx if book is native
    if off.get("already"):
        verdict = "already-configured"
        hints.append(
            f"Existing office config at {off.get('config')}. "
            "Prefer install client / join unless you intend a fresh this-OS office."
        )
        hints.append("Refusing --apply against an already-configured dest (no live overwrite).")
        if foreign_book:
            hints.append("Reachable DB looks foreign to this OS; do not treat it as a new WSL office.")
        # Never green-light live --apply on an existing office (side-office is a later JOB).
        ok_apply = False
    elif foreign_book and not bk.get("present"):
        verdict = "foreign-only"
        hints.append("MySQL/MariaDB port is reachable but no server is installed on this OS.")
        hints.append("Install mariadb/mysql on this OS, or use: mill install client (join existing office).")
        if plat.get("wsl"):
            hints.append("WSL: 127.0.0.1:3306 may be Windows MySQL - that is not a new Linux office.")
        ok_apply = False
    elif missing_book:
        verdict = "missing-deps"
        if plat.get("nt"):
            hints.append("Install MySQL or MariaDB as a Windows service (winget/MySQL installer), then re-run.")
        else:
            hints.append("Install MariaDB/MySQL on this OS (e.g. sudo apt install mariadb-server), then re-run.")
        hints.append("Or join an existing office: mill install client")
        ok_apply = False
    elif not bk.get("present"):
        verdict = "missing-deps"
        hints.append("No MySQL/MariaDB on this OS.")
        ok_apply = False
    else:
        # native book present
        if plat.get("wsl") and not has_httpd:
            # still server-ready via --http service (mill wall process)
            verdict = "server-ready"
            hints.append("No Linux nginx on PATH; wall can use --http service.")
        else:
            verdict = "server-ready"
        ok_apply = True
    # foreign httpd-only with no native book already handled; foreign httpd with native book is still server-ready (service)
    if not ok_apply and verdict == "server-ready":
        verdict = "missing-deps"
    plan = {
        "dest": off.get("dest"),
        "config": off.get("config"),
        "would_write": [
            "mysqld-office.cnf",
            "nginx-wall.conf",
            "nginx-wall.conf",
            "mill-wall.service",
            "wall.cmd / wall.ps1",
            "www/ (wall UI)",
        ],
        "httpd_this_os": http,
        "book_this_os": {"present": bk.get("present"), "services": bk.get("services"), "bins": bk.get("bins")},
        "book_reachable": reach,
        "apply_targets": "this-OS only",
        "host_windows_office": bool(host_windows_office),
    }
    return {
        "verdict": verdict,
        "ok_apply": bool(ok_apply),
        "platform": plat,
        "httpd": http,
        "book": bk,
        "reachable": reach,
        "office": off,
        "hints": hints,
        "plan": plan,
        "foreign_httpd_refused": list(foreign_httpd),
    }



def static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "web" / "static"


def mill_git_root() -> Path | None:
    """MILL_GIT_ROOT, else walk from cwd / this file for a mill checkout."""
    env = (os.environ.get("MILL_GIT_ROOT") or "").strip()
    if env:
        p = Path(env).expanduser()
        if (p / "agent_coord" / "web" / "wall_ui" / "default").is_dir():
            return p.resolve()
        return None
    here = Path(__file__).resolve()
    for start in (Path.cwd(), *here.parents):
        if (start / ".git").exists() and (start / "agent_coord" / "web" / "wall_ui" / "default").is_dir():
            return start
    return None


def mill_wall_src() -> str:
    """pip (site-packages) or git (MILL_GIT_ROOT / checkout). Env MILL_WALL_SRC."""
    v = (os.environ.get("MILL_WALL_SRC") or "").strip().lower()
    if v in ("git", "pip"):
        return v
    dest = office_dir()
    marker = dest / "wall-src"
    if marker.is_file():
        got = marker.read_text(encoding="utf-8").strip().lower()
        if got in ("git", "pip"):
            return got
    return "pip"


def wall_ui_from_src(src: str | None = None) -> Path:
    mode = (src or mill_wall_src()).strip().lower()
    if mode == "git":
        root = mill_git_root()
        if root is not None:
            p = root / "agent_coord" / "web" / "wall_ui" / "default"
            if p.is_dir():
                return p
    p = Path(__file__).resolve().parent.parent / "web" / "wall_ui" / "default"
    return p if p.is_dir() else static_dir()


def wall_ui_default_dir() -> Path:
    """OOTB Wall. Honors MILL_WALL_SRC=git|pip and MILL_GIT_ROOT."""
    return wall_ui_from_src()



def wall_ui_lib_dir() -> Path:
    """Shared Wall JS/CSS lib (popup/data/tabs/table/graph/theme)."""
    p = Path(__file__).resolve().parent.parent / "web" / "wall_ui" / "lib"
    return p if p.is_dir() else wall_ui_default_dir()


def wall_ui_components_dir() -> Path:
    """Shared Wall UI components (gutter, etc.)."""
    p = Path(__file__).resolve().parent.parent / "web" / "wall_ui" / "components"
    return p if p.is_dir() else wall_ui_default_dir()

def deploy_www(dest: Path) -> Path:
    """Copy wall files mill-wall should serve. New markdown/html is picked up on the next GET."""
    import shutil

    www = dest / "www"
    www.mkdir(parents=True, exist_ok=True)
    for src in static_dir().iterdir():
        if src.is_file():
            shutil.copy2(src, www / src.name)
    for src in wall_ui_default_dir().iterdir():
        if src.is_file() and src.suffix.lower() in {".html", ".js", ".css", ".md", ".json"}:
            name = "board.html" if src.name == "board.html" else src.name
            shutil.copy2(src, www / name)
    comps = wall_ui_components_dir()
    libdir = wall_ui_lib_dir()
    if libdir.is_dir():
        dest_lib = www / "lib"
        dest_lib.mkdir(parents=True, exist_ok=True)
        for src in libdir.iterdir():
            if src.is_file() and src.suffix.lower() in {".js", ".css", ".md", ".json"}:
                shutil.copy2(src, dest_lib / src.name)
    if comps.is_dir():
        for src in comps.iterdir():
            if src.is_file() and src.suffix.lower() in {".js", ".css", ".md", ".json"}:
                # basename serve (mill-wall + dogfood _safe_static)
                shutil.copy2(src, www / src.name)
    # cut 5: default pack domain folders (mail/score/floor) - nested www paths
    for domain in ("mail", "score", "floor"):
        src_dir = wall_ui_default_dir() / domain
        if not src_dir.is_dir():
            continue
        dest_dir = www / domain
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src in src_dir.iterdir():
            if src.is_file() and src.suffix.lower() in {".js", ".css", ".md", ".json"}:
                shutil.copy2(src, dest_dir / src.name)
    try:
        from agent_coord.install.office import mill_markdown

        shutil.copy2(mill_markdown("docs", "protocol", "usecases.md"), www / "usecases.md")
    except FileNotFoundError:
        pass
    return www


def switch_wall_src(
    src: str,
    *,
    dest: Path | None = None,
    git_root: str | Path | None = None,
    apply: bool = False,
) -> dict:
    """Point mill www at pip mill or git wall_ui. Env: MILL_WALL_SRC, MILL_GIT_ROOT."""
    mode = (src or mill_wall_src()).strip().lower()
    if mode not in ("pip", "git"):
        raise ValueError("wall-src must be pip or git")
    if git_root:
        os.environ["MILL_GIT_ROOT"] = str(Path(git_root).expanduser().resolve())
    os.environ["MILL_WALL_SRC"] = mode
    dest = dest or office_dir()
    www = dest / "www"
    ui = wall_ui_from_src(mode)
    out: dict = {
        "src": mode,
        "ui": str(ui),
        "www": str(www),
        "git_root": str(mill_git_root() or ""),
        "applied": False,
        "mill_wall": None,
    }
    if mode == "git" and mill_git_root() is None:
        out["ok"] = False
        out["error"] = "MILL_GIT_ROOT unset and no mill checkout found"
        return out
    if not apply:
        out["ok"] = True
        out["next"] = [f"mill wall-src {mode} --apply  # copy to {www} + recycle mill-wall"]
        return out
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "wall-src").write_text(mode + "\n", encoding="utf-8")
    deploy_www(dest)
    out["applied"] = True
    out["ok"] = True
    rec = None
    if os.name == "nt":
        rec = subprocess.run(["sc.exe", "stop", "mill-wall"], capture_output=True, text=True)
        rec = subprocess.run(["sc.exe", "start", "mill-wall"], capture_output=True, text=True)
        out["mill_wall"] = rec.returncode
    out["next"] = [
        f"mill www stays {www} (files copied from {ui})",
        "hard-refresh Wall",
    ]
    return out


def host_from_wall_url(raw: str) -> str:
    """https://office-lan/#session or a bare host -> hostname. Any LAN address."""
    from urllib.parse import urlparse

    s = (raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    return (urlparse(s).hostname or "").strip()


def installed_skill_md() -> str:
    """Installed pack skill.md path. The file body is not returned."""
    from agent_coord.install.office import mill_root

    try:
        path = mill_root() / "docs" / "protocol" / "skill.md"
    except FileNotFoundError:
        return ""
    return str(path) if path.is_file() else ""


def _join_home(dest: Path | None) -> Path:
    path = dest or config_path()
    return path.parent if path.suffix == ".toml" else path


def mill_join(
    host: str,
    *,
    node: str | None = None,
    dest: Path | None = None,
    ca_pem: str = "",
    seat: str = "",
    desk: str = "",
) -> dict:
    """Point this machine at a Wall, trust its CA, and store a session token when possible.

    Invite validation is against the *target Wall* (not the local door/db).
    """
    from agent_coord.config import load_file, save_config
    from agent_coord.client.http import ca_fp_on_url, invite_on_url, seat_on_url

    h = host_from_wall_url(host) or (host or "").strip()
    if not h:
        from agent_coord.server.netbind import preferred_office_host

        h = preferred_office_host()
    mill_url = f"https://{h}" if h and not h.startswith("http") else (h if h.startswith("http") else "")
    if mill_url.startswith("http://"):
        mill_url = "https://" + mill_url[len("http://") :]
    if h.startswith("http"):
        h = host_from_wall_url(h)
    invite_tok = invite_on_url(host)
    seat_tok = (seat or "").strip() or ("" if invite_tok else seat_on_url(host))
    expect_fp = ca_fp_on_url(host)
    path = dest or config_path()
    home = _join_home(path)
    ca_dest = home / "ssl" / "ca.crt"
    if (ca_pem or "").strip():
        from agent_coord.client.http import materialize_mill_ca

        # --ca is already trusted material; do not send invite over the network first.
        ca = materialize_mill_ca(ca_pem, dest=ca_dest)
        if ca is None:
            return {
                "ok": False,
                "mill_url": mill_url,
                "ca": "",
                "trust": ["mill CA PEM from the mint was not a certificate"],
                "note": "mill join failed: --ca is not a CA PEM.",
            }
        if expect_fp:
            from agent_coord.client.http import ca_fingerprint, parse_mill_ca_pem

            pem = parse_mill_ca_pem(ca.read_text(encoding="utf-8")) or ""
            if ca_fingerprint(pem).lower() != expect_fp.lower():
                try:
                    ca.unlink()
                except OSError:
                    pass
                return {
                    "ok": False,
                    "mill_url": mill_url,
                    "ca": "",
                    "trust": ["CA fingerprint mismatch"],
                    "note": "mill join failed: --ca fingerprint does not match ca= pin on the URL.",
                }
    else:
        from agent_coord.client.http import fetch_mill_ca

        ca = fetch_mill_ca(
            mill_url if not expect_fp else host,
            dest=ca_dest,
            invite=invite_tok or seat_tok,
            expect_fp=expect_fp,
        )
    if ca is None:
        note = (
            "mill join failed: Wall did not serve a valid CA PEM at /api/ca.crt or /ca.crt"
            " (or ca= fingerprint mismatched). Nothing written. Fix URL/network/TLS/pin, then retry."
            " Pass --ca with the CA PEM, or the base64 of that PEM."
        )
        return {
            "ok": False,
            "mill_url": mill_url,
            "ca": "",
            "trust": ["wall unreachable or CA not trusted"],
            "note": note,
        }
    trust = ["received mill CA"]
    data = dict(load_file(path))
    data["mill_url"] = mill_url
    if node:
        data["node"] = node
    save_config(data, path)
    if invite_tok:
        from agent_coord.client.offices import write_legacy_invite

        write_legacy_invite(invite_tok, dest=home)
    who = (desk or "").strip()
    from agent_coord.client.offices import project_on_url
    from agent_coord.const import CONST_OFFICE

    seat_project = project_on_url(host)
    if seat_project == CONST_OFFICE:
        seat_project = ""
    if who and seat_tok:
        from agent_coord.client.tokens import write_session_token

        try:
            write_session_token(who, seat_tok, dest=home)
        except (OSError, ValueError) as exc:
            return {
                "ok": False,
                "mill_url": mill_url,
                "ca": str(ca),
                "trust": trust,
                "error": "seat token was not stored",
                "note": str(exc),
            }
        # Seat-form join (--url --desk --seat --ca) often has no project= on the
        # URL. Ask the Wall: join with Office placeholder returns the seat project (#252).
        if not seat_project:
            try:
                from agent_coord.client.http import mill_http_call

                row = mill_http_call(
                    {
                        "verb": "join",
                        "cmd": "join",
                        "project": CONST_OFFICE,
                        "owner": who,
                        "token": seat_tok,
                    }
                )
            except Exception:
                row = None
            if isinstance(row, dict):
                gid = str(row.get("group_id") or row.get("project") or "").strip()
                if gid == CONST_OFFICE:
                    gid = ""
                if gid:
                    seat_project = gid
    elif invite_tok:
        # Invite join: mint a session token against the *remote* Wall (closes #510).
        if not who:
            next_cmd = f"mill join --url {mill_url}/?invite={invite_tok} --desk <desk>"
            return {
                "ok": False,
                "mill_url": mill_url,
                "ca": str(ca),
                "trust": trust,
                "invite": True,
                "error": "invite join needs --desk to mint a session token",
                "next": [next_cmd],
                "note": f"CA trusted. Re-run with --desk so connect works: {next_cmd}",
            }
        try:
            from agent_coord.client.http import mill_http_call

            row = mill_http_call(
                {
                    "verb": "join",
                    "cmd": "join",
                    "project": seat_project or CONST_OFFICE,
                    "owner": who,
                }
            )
        except Exception as exc:
            next_cmd = f"mill join --url {mill_url}/?invite={invite_tok} --desk {who}"
            return {
                "ok": False,
                "mill_url": mill_url,
                "ca": str(ca),
                "trust": trust,
                "invite": True,
                "error": f"remote Wall join failed: {exc}",
                "next": [next_cmd],
                "note": (
                    "CA trusted but session token was not minted against the Wall. "
                    f"Fix network/invite, then: {next_cmd}"
                ),
            }
        tok = ""
        if isinstance(row, dict):
            tok = str(row.get("token") or "").strip()
            gid = str(row.get("group_id") or row.get("project") or "").strip()
            if gid == CONST_OFFICE:
                gid = ""
            if gid:
                seat_project = gid
        if not tok:
            next_cmd = f"mill join --url {mill_url}/?invite={invite_tok} --desk {who}"
            return {
                "ok": False,
                "mill_url": mill_url,
                "ca": str(ca),
                "trust": trust,
                "invite": True,
                "error": "remote Wall join returned no session token",
                "next": [next_cmd],
                "note": f"CA trusted; Wall did not return a token. Retry: {next_cmd}",
            }
        # mill_http_call already writes the session token when join succeeds; ensure dest home.
        from agent_coord.client.tokens import read_session_token, write_session_token

        stored = ""
        try:
            stored = (read_session_token(who, dest=home) or "").strip()
        except ValueError:
            stored = ""
        if stored != tok:
            try:
                write_session_token(who, tok, dest=home, desk_id=(row or {}).get("desk_id"))
            except (OSError, ValueError) as exc:
                return {
                    "ok": False,
                    "mill_url": mill_url,
                    "ca": str(ca),
                    "trust": trust,
                    "error": "session token was not stored",
                    "note": str(exc),
                }
        trust.append("session token stored for desk")
    skill = installed_skill_md()
    note = (
        "mill here issues the access token. Received the mill CA. "
        "It was not installed in the OS trust store."
    )
    if skill:
        note = note + " skill " + skill
    from agent_coord.client.offices import current_host_key, current_office, next_connect_line, write_seat_project

    office = current_office(dest=home) or ""
    missed = ""
    if who and seat_project and office:
        host_key = current_host_key(dest=home)
        if host_key:
            try:
                write_seat_project(who, seat_project, host=host_key, dest=home)
            except (OSError, ValueError) as exc:
                missed = " seat project was not stored: " + str(exc)
    if missed:
        note = note + missed
    line = next_connect_line(office, seat_project, who)
    out = {
        "ok": True,
        "config": str(path),
        "mill_url": mill_url,
        "ca": str(ca),
        "trust": trust,
        "skill": skill,
        "note": note,
        "desk": who or None,
        "project": seat_project or None,
    }
    if line:
        out["next"] = line
    return out


def office_dir(path: Path | None = None) -> Path:
    return (path or config_path()).parent


def python_exe() -> str:
    return sys.executable


def _repo_cwd() -> Path:
    here = Path.cwd().resolve()
    def _has_scorecard(base: Path) -> bool:
        return (base / "SCORECARD.md").is_file() or (base / "docs" / "SCORECARD.md").is_file()
    if _has_scorecard(here) and (here / "pyproject.toml").is_file():
        return here
    pkg = Path(__file__).resolve().parent.parent
    if _has_scorecard(pkg):
        return pkg
    return here


def nginx_server(
    *,
    public_bind: str,
    public_port: int,
    api_bind: str,
    api_port: int,
    docroot: Path,
    door: str = "path",
    lan_only: bool = False,
    logs_dir: Path | None = None,
    ssl_dir: Path | None = None,
) -> str:
    """TLS edge: FastAPI mill-wall serves Wall + /api. Nginx combined access/error logs."""
    from agent_coord.server.netbind import resolve_listen_hosts

    hosts = resolve_listen_hosts(lan_only=lan_only, public_bind=public_bind)
    mill = f"http://{api_bind}:{api_port}"
    ssl = (ssl_dir or (docroot.parent / "ssl")).resolve().as_posix()
    logs = (logs_dir or (docroot.parent / "logs")).resolve().as_posix()
    loc = f"""    location / {{
        proxy_pass {mill};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $http_connection;
        proxy_read_timeout 86400s;
    }}"""
    blocks: list[str] = [
        "# mill wall 0.4 - nginx TLS edge; FastAPI mill-wall behind it. "
        f"door={door or 'path'} lan_only={'1' if lan_only else '0'}"
    ]
    for h in hosts:
        if h == "*":
            listen80 = "80"
            listen443 = "443 ssl"
        else:
            listen80 = f"{h}:80"
            listen443 = f"{h}:443 ssl"
        blocks.append(
            f"""server {{
    listen {listen80};
    server_name wall.local;
    return 301 https://$host$request_uri;
}}
server {{
    listen {listen443};
    server_name wall.local;
    server_tokens off;
    ssl_certificate {ssl}/wall.crt;
    ssl_certificate_key {ssl}/wall.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    access_log {logs}/nginx-access.log combined;
    error_log {logs}/nginx-error.log;
{loc}
}}"""
        )
    return "\n".join(blocks) + "\n"


def mill_user_site_pythonpath() -> str | None:
    """User site-packages when the mill pack lives under a --user install; else None."""
    import site

    try:
        user_site = site.getusersitepackages()
    except Exception:
        return None
    if not user_site:
        return None
    try:
        import agent_coord as _ac

        root = Path(_ac.__file__).resolve().parent.parent
        us = Path(user_site).resolve()
        if root == us or us in root.parents or str(root).startswith(str(us) + os.sep):
            return str(us)
    except Exception:
        return None
    return None


def systemd_unit(
    *,
    python: str,
    bind: str,
    port: int,
    cwd: Path,
    api_only: bool,
    user: str | None = None,
    mill_home: Path | str | None = None,
    pythonpath: str | None = None,
) -> str:
    """Linux mill-wall unit. User= invoking user (not a dedicated account). Explicit MILL_HOME/env."""
    import getpass

    extra = " --api-only" if api_only else ""
    cap = ""
    if int(port) < 1024:
        cap = "AmbientCapabilities=CAP_NET_BIND_SERVICE\nCapabilityBoundingSet=CAP_NET_BIND_SERVICE\n"
    who = (user or "").strip() or getpass.getuser()
    home = str(mill_home or office_dir())
    env_lines = [
        "Environment=PYTHONUNBUFFERED=1",
        f"Environment=AGENT_COORD_MILL_HOME={home}",
    ]
    pp = pythonpath if pythonpath is not None else mill_user_site_pythonpath()
    if pp:
        env_lines.append(f"Environment=PYTHONPATH={pp}")
    env_block = "\n".join(env_lines)
    return f"""[Unit]
Description=mill wall (FastAPI mill API; nginx is the public httpd)
After=network.target mysql.service mysqld.service

[Service]
Type=simple
User={who}
WorkingDirectory={cwd}
{cap}ExecStart={python} -m agent_coord wall --bind {bind} --port {port}{extra}
Restart=on-failure
RestartSec=5
{env_block}

[Install]
WantedBy=multi-user.target
"""


def wall_cmd(*, python: str, bind: str, port: int, cwd: Path, log: Path, api_only: bool) -> str:
    extra = " --api-only" if api_only else ""
    return (
        "@echo off\r\n"
        "set PYTHONUNBUFFERED=1\r\n"
        f'cd /d "{cwd}"\r\n'
        f'"{python}" -m agent_coord wall --bind {bind} --port {port}{extra}'
        f' >> "{log}" 2>&1\r\n'
    )


def wall_ps1(*, python: str, bind: str, port: int, cwd: Path, log: Path, api_only: bool) -> str:
    extra = " --api-only" if api_only else ""
    # UTF-8 log via cmd >> (PowerShell *>> is UTF-16). Loop = crash stay-up without schtasks RestartCount.
    # Health-check: if port listening AND Office agents return 200, skip spawn (sleep 5s); log one calm skip line.
    q = chr(39)
    brace0 = "{" + "0}"
    brace1 = "{" + "1}"
    brace2 = "{" + "2}"
    body: list[str] = []
    body.append("$ErrorActionPreference = " + q + "Continue" + q)
    body.append("Set-Location -LiteralPath " + q + str(cwd) + q)
    body.append("$env:PYTHONUNBUFFERED = " + q + "1" + q)
    body.append("$py = " + q + python + q)
    body.append("$log = " + q + str(log) + q)
    body.append("$port = " + str(port))
    body.append("# Watchdog: mill API crash must not stay down until a human.")
    body.append("# Legacy watchdog artifact; product mill-wall on Windows is the SCM SERVICE (win_wall_svc).")
    body.append("try { [Console]::TreatControlCAsInput = $true } catch {}")
    body.append(
        "Register-ObjectEvent -InputObject ([System.Console]) "
        "-EventName CancelKeyPress -Action { $_.EventArgs.Cancel = $true } "
        "-ErrorAction SilentlyContinue | Out-Null"
    )
    body.append("# If port is listening AND /api/v1/agents?project=Office returns 200, do NOT spawn another wall.")
    body.append("$loggedHealthy = $false")
    body.append("while ($true) {")
    body.append("  $listening = $false")
    body.append("  try {")
    body.append("    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue")
    body.append("    if ($conns) { $listening = $true }")
    body.append("  } catch {}")
    body.append("  $healthy = $false")
    body.append("  if ($listening) {")
    body.append("    try {")
    body.append(
        "      $code = & curl.exe -s -o NUL -w "
        + q
        + "%{http_code}"
        + q
        + " --max-time 3 "
        + q
        + "http://127.0.0.1:$port/api/v1/agents?project=Office"
        + q
    )
    body.append("      if ($code -eq " + q + "200" + q + ") { $healthy = $true }")
    body.append("    } catch {}")
    body.append("  }")
    body.append("  if ($healthy) {")
    body.append("    if (-not $loggedHealthy) {")
    body.append("      $ts = Get-Date -Format " + q + "yyyy-MM-dd HH:mm:ss" + q)
    body.append(
        "      Add-Content -LiteralPath $log -Value ("
        + q
        + "["
        + brace0
        + "] mill API healthy on "
        + brace1
        + "; skip spawn"
        + q
        + " -f $ts, $port) -Encoding utf8"
    )
    body.append("      $loggedHealthy = $true")
    body.append("    }")
    body.append("    Start-Sleep -Seconds 5")
    body.append("    continue")
    body.append("  }")
    body.append("  $loggedHealthy = $false")
    body.append(
        "  $line = "
        + q
        + '"'
        + brace0
        + '"'
        + " -m agent_coord wall --bind "
        + bind
        + " --port "
        + brace1
        + extra
        + " >> "
        + '"'
        + brace2
        + '"'
        + " 2>&1"
        + q
        + " -f $py, $port, $log"
    )
    body.append("  try {")
    body.append("    cmd.exe /c $line")
    body.append("  } catch {")
    body.append("    # Ctrl+C / cancel must not kill the watchdog outer loop")
    body.append("  }")
    body.append("  $code = $LASTEXITCODE")
    body.append("  if ($code -eq -1073741510 -or $code -eq 3221225786) {")
    body.append("    # STATUS_CONTROL_C_EXIT (0xC000013A) - stay up")
    body.append("    $code = " + q + "CtrlC" + q)
    body.append("  }")
    body.append("  $ts = Get-Date -Format " + q + "yyyy-MM-dd HH:mm:ss" + q)
    body.append(
        "  Add-Content -LiteralPath $log -Value ("
        + q
        + "["
        + brace0
        + "] mill API exited code="
        + brace1
        + "; restart in 2s"
        + q
        + " -f $ts, $code) -Encoding utf8"
    )
    body.append("  Start-Sleep -Seconds 2")
    body.append("}")
    body.append("")
    return chr(10).join(body)



def mysqld_snippet(*, bind: str = "127.0.0.1") -> str:
    local = bind if bind not in ("0.0.0.0", "::") else "127.0.0.1"
    return f"""# Office book. Enable in the server's my.cnf / mysqld.cnf (or MySQL installer options).
# Do not run mysqld from a coding-agent chat. The OS service hosts the book.
# Secure default: loopback (or private LAN bind), no public 0.0.0.0/0.
[mysqld]
bind-address = {local}
skip-symbolic-links
local-infile = 0
slow_query_log = 1
long_query_time = 0.1
log_output = FILE
# Remote workers: VPN or SSH tunnel. Do not bind 0.0.0.0 on the public internet.
"""


def write_role(
    role: str,
    *,
    dest: Path | None = None,
    http: str = "service",
    apply: bool = False,
    dry_run: bool = False,
    agent: bool = False,
    bind: str | None = None,
    port: int | None = None,
    book: str = "mysql",
    provider: str = "self",
    lan_only: bool | None = None,
    public: bool = False,
    py_version: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    from agent_coord.install.catalog import HTTPDS, normalize_book, normalize_cloud, normalize_httpd
    from agent_coord.server.admin.door import mode as door_mode

    name = (role or "").strip().lower()
    if mill_agent_mode(agent):
        os.environ["MILL_AGENT"] = "1"
    if name not in ROLES:
        raise ValueError(f"install role must be one of {', '.join(ROLES)}")
    kind = normalize_httpd(http or "service")
    if (http or "service").strip().lower() == "service":
        kind = "service"
    engine = normalize_book(book)
    cloud = normalize_cloud(provider)
    s = settings()
    public_bind = bind or s["dashboard_bind"] or DEFAULTS["dashboard_bind"]
    public_port = int(port if port is not None else s["dashboard_port"])
    dest = dest or office_dir()

    # --dry-run and --apply are mutually exclusive for every role.
    if dry_run and apply:
        return {
            "ok": False,
            "role": name,
            "dry_run": True,
            "mutated": False,
            "warnings": ["--dry-run and --apply are mutually exclusive"],
            "next": ["Use --dry-run alone to print the plan with no writes."],
        }

        # --public and --lan-only are mutually exclusive (also enforced in CLI).
    if public and lan_only is True:
        return {
            "ok": False,
            "role": name,
            "dry_run": bool(dry_run),
            "mutated": False,
            "warnings": ["--public and --lan-only are mutually exclusive"],
            "next": ["Pass only one of --public or --lan-only."],
        }
    if public:
        lan_only = False
    elif lan_only is True:
        lan_only = True

    # --public: door must be invite (set on --apply, or refuse if set_door fails).
    door_plan: dict[str, Any] | None = None
    if public and name in ("server", "wall"):
        current_door = str(door_mode() or "path")
        if current_door != "invite":
            if dry_run:
                door_plan = {
                    "action": "set-door-invite",
                    "current": current_door,
                    "note": "--public dry-run: would set door=invite before apply (or refuse if door cannot be set)",
                }
            elif apply:
                try:
                    from agent_coord.server.admin.door import set_door

                    door_plan = set_door("invite")
                except Exception as exc:
                    return {
                        "ok": False,
                        "role": name,
                        "mutated": False,
                        "error": f"--public requires door=invite; set_door failed: {exc}",
                        "door": current_door,
                        "next": ["mill invite --door invite, then re-run mill install server --apply --public"],
                    }
                if str(door_mode() or "") != "invite":
                    return {
                        "ok": False,
                        "role": name,
                        "mutated": False,
                        "error": "--public requires door=invite; door is still not invite after set_door",
                        "door": door_mode(),
                        "door_plan": door_plan,
                        "next": ["mill invite --door invite, then re-run mill install server --apply --public"],
                    }
            else:
                # Neither dry-run nor apply: still report the requirement.
                door_plan = {
                    "action": "require-door-invite",
                    "current": current_door,
                    "note": "--public without --apply: door stays; --apply will set door=invite",
                }
        else:
            door_plan = {"action": "door-already-invite", "current": "invite"}

# Global early Python gate (before mkdir / role writers). Injectable for tests.
    gate = python_too_old(py_version=py_version)
    if gate is not None:
        return {
            "ok": False,
            "role": name,
            "dry_run": bool(dry_run),
            "mutated": False,
            "verdict": gate["verdict"],
            "warnings": list(gate["hints"]),
            "next": list(gate["hints"]),
            "python": gate.get("python"),
            "plan": {"dest": str(dest), "would_write": [], "apply_targets": "none (python too old)"},
        }

    pf: dict[str, Any] | None = None
    human_warn: list[str] = []
    if name == "server":
        human_warn = print_human_install_warn()
        host_win = bool(getattr(write_role, "_host_windows_office", False))
        env_hatch = (os.environ.get("AGENT_COORD_HOST_WINDOWS_OFFICE") or "").strip().lower()
        if env_hatch in ("1", "true", "yes", "on"):
            host_win = True
        pf = preflight_server(dest=dest, host_windows_office=host_win, py_version=py_version)
        ed_plan = ensure_deps_plan(nt=bool((pf.get("platform") or {}).get("nt")), wsl=bool((pf.get("platform") or {}).get("wsl")))
        if isinstance(pf.get("plan"), dict):
            pf = dict(pf)
            plan_out = dict(pf.get("plan") or {})
            plan_out["ensure_deps"] = ed_plan
            pf["plan"] = plan_out
        if dry_run:
            refuse = ("foreign-only", "python-too-old", "already-configured")
            # missing-deps dry-run is still ok for plan printing (ensure-deps cmds shown)
            ok_dry = pf.get("verdict") not in refuse
            if pf.get("verdict") == "missing-deps":
                ok_dry = True  # plan includes silent ensure-deps cmds
            dry_out = {
                "ok": ok_dry,
                "role": "server",
                "dry_run": True,
                "preflight": pf,
                "verdict": pf.get("verdict"),
                "ensure_deps": ed_plan,
                "human_warn": list(human_warn),
                "warnings": list(human_warn) + list(pf.get("hints") or []),
                "next": list(pf.get("hints") or [])
                + [
                    "Dry-run only: no files written, no services changed.",
                    "Ensure-deps plan printed (silent CLI; reuse healthy; install missing only).",
                    "Apply this-OS only when verdict allows: mill install server --apply",
                    "Client join: mill install client",
                ],
                "plan": pf.get("plan"),
                "mutated": False,
                "lan_only": lan_only,
                "public": bool(public),
                "door": door_mode(),
            }
            if door_plan is not None:
                dry_out["door_plan"] = door_plan
                note = (door_plan.get("note") or "")
                if note:
                    dry_out["next"] = [note] + list(dry_out["next"])
            return dry_out
        if apply and pf.get("verdict") == "missing-deps":
            ed = ensure_deps(apply=True, nt=bool((pf.get("platform") or {}).get("nt")), wsl=bool((pf.get("platform") or {}).get("wsl")))
            if not ed.get("ok"):
                return {
                    "ok": False,
                    "role": "server",
                    "preflight": pf,
                    "verdict": "missing-deps",
                    "ensure_deps": ed,
                    "mutated": bool(ed.get("mutated")),
                    "human_warn": list(human_warn),
                    "warnings": list(human_warn) + list(ed.get("failed") or []) + list(pf.get("hints") or []),
                    "next": list(ed.get("failed") or [])
                    + [
                        "Ensure-deps failed (fail-closed). Fix Access Denied / missing package, then re-run --apply.",
                        "Do not use mysqld --console as Pass.",
                    ],
                    "plan": pf.get("plan"),
                }
            # re-probe after silent ensure
            pf = preflight_server(dest=dest, host_windows_office=host_win, py_version=py_version)
            if isinstance(pf.get("plan"), dict):
                pf = dict(pf)
                plan_out = dict(pf.get("plan") or {})
                plan_out["ensure_deps"] = ed
                pf["plan"] = plan_out
        if apply and not pf.get("ok_apply"):
            return {
                "ok": False,
                "role": "server",
                "preflight": pf,
                "verdict": pf.get("verdict"),
                "ensure_deps": ed_plan,
                "mutated": False,
                "human_warn": list(human_warn),
                "warnings": list(human_warn) + list(pf.get("hints") or []),
                "next": list(pf.get("hints") or [])
                + [
                    "Preflight refused --apply (no partial writes).",
                    "Dry-run: mill install server   # prints plan",
                    "Client join: mill install client",
                ],
                "plan": pf.get("plan"),
            }
        if not apply and pf.get("verdict") in ("missing-deps", "foreign-only", "python-too-old"):
            return {
                "ok": False,
                "role": "server",
                "preflight": pf,
                "verdict": pf.get("verdict"),
                "dry_run": True,
                "mutated": False,
                "human_warn": list(human_warn),
                "warnings": list(human_warn) + list(pf.get("hints") or []),
                "next": list(pf.get("hints") or []),
                "plan": pf.get("plan"),
            }
        # fall through to mkdir + write after preflight pass (server-ready only)

    # Global dry-run: never mkdir / never call role writers (client/desk/book/wall/cloud/check).
    if dry_run:
        would = {
            "client": ["desk.txt"],
            "desk": ["desk.txt"],
            "book": ["mysqld-office.cnf"],
            "records": ["mysqld-office.cnf"],
            "wall": ["wall configs / www"],
            "cloud": ["cloud notes"],
            "check": [],
            "server": ["mysqld-office.cnf", "wall configs / www"],
        }.get(name, [])
        return {
            "ok": True,
            "role": name,
            "dry_run": True,
            "mutated": False,
            "warnings": [],
            "next": ["Dry-run only: no files written, no services changed."],
            "plan": {"dest": str(dest), "would_write": would},
        }

    dest.mkdir(parents=True, exist_ok=True)
    if name == "client" or name == "desk":
        return _write_desk(dest, apply=apply)
    if name in ("book", "records"):
        row = _write_book(dest, apply=apply, bind=str(s["host"]), engine=engine)
        if name == "records":
            row = dict(row)
            row["role"] = "records"
        return row
    if name == "cloud":
        return _write_cloud(dest, provider=cloud)
    if name == "check":
        return check_office(dest=dest, live=True)
    if name == "server":
        # pf computed above (before mkdir) for no-partial-writes
        if not (kind or "").strip():
            kind = "service" if os.name == "nt" else "nginx"
        wall_http = kind if HTTPDS.get(kind, {}).get("wired") else "nginx"
        bins_now = _httpd_bins()
        if wall_http == "service" and apply and "nginx" in bins_now and os.name != "nt":
            wall_http = "nginx"
        if os.name != "nt" and wall_http == "nginx" and "nginx" not in bins_now:
            wall_http = "service"
        book_row = _write_book(dest, apply=apply, bind=str(s["host"]), engine=engine)
        wall_row = _write_wall(
            dest,
            http=wall_http,
            apply=apply,
            public_bind=str(public_bind),
            public_port=public_port,
            door=door_mode(),
            lan_only=lan_only,
            agent=mill_agent_mode(agent),
        )
        invite_info = {}
        try:
            from agent_coord.server.admin.door import ensure_ootb_invite

            invite_info = ensure_ootb_invite(created_by="installer")
        except Exception:
            invite_info = {}
        wall_url = (wall_row.get("url") or "https://127.0.0.1/").rstrip("/")
        invite_link = None
        if invite_info.get("token") and invite_info.get("invite_path"):
            invite_link = wall_url + invite_info["invite_path"]
        next_steps = [
            "Out of the box: install server --apply, then init --yes, then presence.",
            "Other agents: pip install the-mill (client CLI, least tokens).",
            "Humans: door URL. Useful work is SESSION / FLOOR / JOBS / ADMIN, not this installer.",
        ]
        if invite_link:
            next_steps.insert(0, f"OOTB invite link (admin=installer): {invite_link}")
            next_steps.insert(1, "Enable door gate: mill invite --door invite (keys already minted).")
        out = {
            "ok": bool(book_row.get("ok") and wall_row.get("ok")),
            "role": "server",
            "book": book_row,
            "wall": wall_row,
            "engine": engine,
            "http": wall_http,
            "door": door_mode(),
            "invite": invite_info,
            "invite_link": invite_link,
            "lan_only": lan_only,
            "public": bool(public),
            "admin": "installer",
            "preflight": pf,
            "verdict": pf.get("verdict"),
            "plan": pf.get("plan"),
            "dry_run": not apply,
            "human_warn": list(human_warn),
            "warnings": list(human_warn)
            + list(book_row.get("warnings") or [])
            + list(wall_row.get("warnings") or []),
            "next": next_steps,
        }
        if door_plan is not None:
            out["door_plan"] = door_plan
        return out
    if name == "wall" and kind == "service" and apply:
        if "nginx" in _httpd_bins():
            kind = "nginx"
    if kind not in ("service", "nginx"):
        leftover = dest / f"httpd-{kind}.txt"
        leftover.write_text(
            f"{kind} is allowed but not wired. OOTB wall is nginx + FastAPI mill-wall. "
            "Same mill API behind it. Re-run install wall --http nginx.\n",
            encoding="utf-8",
        )
        kind = "nginx"
    wall_out = dict(
        _write_wall(
            dest,
            http=kind,
            apply=apply,
            public_bind=str(public_bind),
            public_port=public_port,
            door=door_mode(),
            lan_only=lan_only,
            agent=mill_agent_mode(agent),
        )
    )
    wall_out["door"] = door_mode()
    wall_out["lan_only"] = lan_only
    wall_out["public"] = bool(public)
    if door_plan is not None:
        wall_out["door_plan"] = door_plan
    return wall_out


def _write_book(dest: Path, *, apply: bool, bind: str, engine: str = "mysql") -> dict[str, Any]:
    cnf = dest / "mysqld-office.cnf"
    cnf.write_text(mysqld_snippet(bind=bind if bind not in ("0.0.0.0", "::") else "127.0.0.1"), encoding="utf-8")
    found = _book_services()
    reachable = _book_reachable()
    warnings: list[str] = []
    next_steps = [
        f"Book is an RDBMS OS service (engine={engine}). Do not start it in a chat.",
        f"Merge {cnf} into the server config if bind-address is still public.",
        "Then: mill init --yes",
    ]
    if not found:
        warnings.append("no mysql/mariadb OS service name found; install the database as a service, then re-run")
        next_steps.insert(0, "Install MySQL (or MariaDB/Postgres) as an OS service and make it Automatic")
    if not reachable["ok"]:
        warnings.append(f"cannot reach the book: {reachable.get('error')}")
    # OOTB Pass = OS service present (and on Windows --apply: SCM Running). Port-only / console is not enough.
    ok_book = bool(found)
    result: dict[str, Any] = {
        "ok": ok_book,
        "role": "book",
        "engine": engine,
        "files": [str(cnf)],
        "services": found,
        "reachable": reachable,
        "warnings": warnings,
        "next": next_steps,
    }
    if apply and os.name == "nt":
        applied: list[str] = []
        if not found:
            result["applied"] = []
            result["ok"] = False
            warnings.append(
                "FAILED: --apply did not find a MySQL/MariaDB Windows service. "
                "Install it as a service (Admin/UAC). Do not use mysqld --console as Pass."
            )
        else:
            any_ok = False
            for row in found:
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                status = str(row.get("status") or "").lower()
                if status == "running":
                    applied.append(f"{name} Windows service already RUNNING start={row.get('start_type')}")
                    any_ok = True
                    continue
                started, note = _start_windows_service(name)
                applied.append(note)
                if started:
                    any_ok = True
                else:
                    warnings.append(note)
            result["applied"] = applied
            result["ok"] = bool(any_ok)
            if not any_ok:
                warnings.append(
                    "FAILED: no MySQL/MariaDB Windows service RUNNING after SCM start "
                    "(Admin/UAC required). Do not use mysqld --console as Pass."
                )
    elif apply and not found:
        result["applied"] = []
        result["ok"] = False
        warnings.append("--apply did not start a database; install the RDBMS as a service first")
    return result


def _write_desk(dest: Path, *, apply: bool) -> dict[str, Any]:
    note = dest / "desk.txt"
    note.write_text(
        "Client / mill CLI (least tokens)\n"
        "1. python -m pip install the-mill   (or pip install . from this repo)\n"
        "2. Use the CLI: leftover, peek, needs, inbox, presence. Do not dump /api/floor into Grok.\n"
        "   Do not take a MySQL password onto this desk. Wall host may use local Coord.\n"
        "Any client agent can be assigned admin (manage book + wall).\n"
        "Do not start the wall or the database from this desk chat.\n"
        "If the wall is down: an admin runs install server --apply on the wall host, not `dashboard` in Grok.\n"
        "Shapes: this PC (127.0.0.1), LAN/local (office IP), WAN/company (VPN). VPN into LAN is still LAN.\n",
        encoding="utf-8",
    )
    return {
        "ok": True,
        "role": "desk",
        "files": [str(note)],
        "warnings": [],
        "next": [
            "pip install the-mill  (client CLI)",
            "mill briefing join",
            "presence - not one-shot register",
        ],
        "applied": ["desk is the CLI; nothing to register as an OS service"] if apply else [],
    }


def _write_wall(
    dest: Path,
    *,
    http: str,
    apply: bool,
    public_bind: str,
    public_port: int,
    door: str = "path",
    lan_only: bool | None = None,
    agent: bool = False,
) -> dict[str, Any]:
    api_only = http == "nginx"
    api_bind = "127.0.0.1"
    api_port = public_port if not api_only else (18765 if public_port != 18765 else 18766)
    from agent_coord.server.netbind import assert_mill_api_bind, cert_paths, lan_only_enabled, resolve_listen_hosts

    if lan_only is None:
        lan_only = lan_only_enabled()
    lan_only = bool(lan_only)
    assert_mill_api_bind(api_bind, api_only=True)
    process_bind = public_bind if not api_only else api_bind
    process_port = public_port if not api_only else api_port
    if api_only:
        process_bind = "127.0.0.1"
    cwd = _repo_cwd()
    py = python_exe()
    log = dest / "wall.log"
    files: dict[str, Path] = {
        "nginx": dest / "nginx-wall.conf",
        "systemd": dest / "mill-wall.service",
        "cmd": dest / "wall.cmd",
        "ps1": dest / "wall.ps1",
    }
    www = deploy_www(dest)
    files["www"] = www
    # HTTPS-only product: never leave a cleartext convenience Listen on public wildcard
    # when lan_only. Cloud/public: lan_only=False -> * / 0.0.0.0 still HTTPS+redirect.
    if http == "nginx":
        vhost_bind = public_bind if (lan_only or public_bind not in ("",)) else "0.0.0.0"
        if not lan_only and public_bind in ("127.0.0.1", "localhost"):
            vhost_bind = "0.0.0.0"
        if lan_only:
            vhost_bind = public_bind if public_bind not in ("0.0.0.0", "::", "*") else "127.0.0.1"
    else:
        vhost_bind = public_bind
    (dest / "logs").mkdir(parents=True, exist_ok=True)
    files["nginx"].write_text(
        nginx_server(
            public_bind=vhost_bind,
            public_port=public_port,
            api_bind=api_bind,
            api_port=api_port,
            docroot=www,
            door=door,
            lan_only=lan_only,
            logs_dir=dest / "logs",
            ssl_dir=dest / "ssl",
        ),
        encoding="utf-8",
    )
    files["systemd"].write_text(
        systemd_unit(
            python=py,
            bind=process_bind,
            port=process_port,
            cwd=cwd,
            api_only=api_only,
            mill_home=dest,
        ),
        encoding="utf-8",
    )
    files["cmd"].write_text(
        wall_cmd(python=py, bind=process_bind, port=process_port, cwd=cwd, log=log, api_only=api_only),
        encoding="utf-8",
    )
    files["ps1"].write_text(
        wall_ps1(python=py, bind=process_bind, port=process_port, cwd=cwd, log=log, api_only=api_only),
        encoding="utf-8",
    )
    scm_helper: Path | None = None
    if os.name == "nt":
        scm_helper = write_windows_scm_helper(
            dest, python=py, bind=process_bind, port=process_port, api_only=api_only
        )
        files["scm_helper"] = scm_helper
    httpd = _httpd_bins()
    warnings: list[str] = []
    if http == "nginx" and http not in httpd:
        warnings.append(f"{http} binary not on PATH; files written. Install the httpd as an OS service, then include the vhost.")
    if "AGENT_COORD_OWNER" in files["cmd"].read_text(encoding="utf-8"):
        raise RuntimeError("wall wrapper must not set AGENT_COORD_OWNER")
    share_urls = share_wall_urls(
        public_bind=public_bind,
        public=(not lan_only and public_bind not in ("127.0.0.1", "localhost", "")),
    )
    public_url = share_urls[0] if share_urls else "https://127.0.0.1/"
    next_steps = [
        "Wall is an OS web service. Do not keep `mill wall` running in a coding-agent session.",
        f"Share URL (HTTPS): {with_session_hash(public_url)}",
    ]
    for extra_url in share_urls[1:]:
        next_steps.append(f"Also: {extra_url}")
    next_steps.append(
        "This PC: https://127.0.0.1/ and https://localhost/ should open without a warning (mill trusts office CA). Other devices may warn: Advanced -> Proceed. Do not import wall.crt."
    )
    next_steps.append(
        "Apply mints ~/.mill/ssl/ca.crt and wall.crt with openssl. Trust ca.crt. Do not import wall.crt."
    )
    if os.name == "nt" and scm_helper is not None:
        next_steps.append(
            "HUMAN: packages != services. mill-wall is a Windows SERVICE (not schtasks). "
            "ONE Hidden elevate (auto-exit): "
            + " ".join(elevate_windows_scm_helper_argv(scm_helper, already_admin=windows_is_admin()))
        )
    elif os.name != "nt":
        next_steps.append(
            "Linux/WSL: enable MySQL via systemd (sudo); mill-wall.service for FastAPI mill-wall."
        )
    
        next_steps.append(f"Mill API loopback behind TLS (not public cleartext): {api_bind}:{api_port}")
        next_steps.append("HTTPS only: http:// -> 301 https://. LAN-only: install wall --lan-only; cloud: --public.")
    elif http == "nginx":
        next_steps.append(f"Include {files['nginx']} and reload nginx.")
    else:
        next_steps.append("No nginx on this box: the mill wall process is the httpd (`--http service`).")
        next_steps.append("When nginx exists: mill install wall --http nginx --apply")
    if os.name != "nt":
        next_steps.append(f"Linux: sudo cp {files['systemd']} /etc/systemd/system/ && sudo systemctl enable --now mill-wall")
    certs = cert_paths(dest)
    listens = resolve_listen_hosts(lan_only=lan_only, public_bind=vhost_bind)
    result: dict[str, Any] = {
        "ok": True,
        "role": "wall",
        "http": http,
        "url": public_url,
        "process_bind": process_bind,
        "process_port": process_port,
        "api_only": api_only,
        "https_only": True,
        "lan_only": lan_only,
        "listen_hosts": listens,
        "cert_path": certs.get("cert"),
        "key_path": certs.get("key"),
        "ssl_dir": certs.get("ssl_dir"),
        "files": [str(p) for p in files.values()],
        "httpd": httpd,
        "warnings": warnings,
        "next": next_steps,
    }
    if apply:
        applied = _apply_wall(
            files,
            http=http,
            httpd=httpd,
            dest=dest,
            agent=mill_agent_mode(agent),
            run_cmd=subprocess.run if os.name != "nt" else None,
        )
        result["applied"] = applied.get("steps") if isinstance(applied, dict) else applied
        result["apply_ok"] = bool(applied.get("ok")) if isinstance(applied, dict) else True
        if isinstance(applied, dict) and applied.get("failed_step"):
            result["failed_step"] = applied["failed_step"]
        if isinstance(applied, dict) and not applied.get("ok"):
            result["ok"] = False
    return result


def _apply_wall(
    files: dict[str, Path],
    *,
    http: str,
    httpd: dict[str, str],
    dest: Path,
    agent: bool = False,
    run_cmd=None,
) -> dict[str, Any]:
    """Apply wall unit/certs. Any non-zero sudo/systemctl => ok:false with failed_step.

    Returns {"ok": bool, "steps": list[str], "failed_step": str|None}.
    """
    done: list[str] = []
    failed_step: str | None = None
    openssl = shutil.which("openssl")
    if not openssl:
        done.append("FAILED: openssl not on PATH; cannot mint ~/.mill/ssl/ca.crt and wall.crt")
        failed_step = "openssl"
    else:
        try:
            crt, _key = _make_wall_cert(dest / "ssl", Path(openssl))
            done.append(
                f"minted {crt.name} under {crt.parent} (trust ca.crt, never import wall.crt)"
            )
        except Exception as exc:
            done.append(f"FAILED: mill CA cert: {exc}")
            failed_step = "mill-ca-cert"
    if os.name == "nt":
        win_steps = _apply_mill_wall_service(files, dest=dest, agent=mill_agent_mode(agent))
        done.extend(win_steps)
        if any(str(x).startswith("FAILED:") for x in win_steps) and failed_step is None:
            failed_step = "windows-service"
    else:
        unit = files.get("systemd")
        if run_cmd is not None and unit and failed_step is None:
            steps = [
                ("sudo-cp-unit", ["sudo", "-n", "cp", str(unit), "/etc/systemd/system/mill-wall.service"]),
                ("systemctl-daemon-reload", ["sudo", "-n", "systemctl", "daemon-reload"]),
                ("systemctl-enable-now", ["sudo", "-n", "systemctl", "enable", "--now", "mill-wall"]),
            ]
            for name, argv in steps:
                try:
                    proc = run_cmd(argv, check=False, capture_output=True, text=True)
                except TypeError:
                    # Test fakes / older callables may not accept kwargs.
                    try:
                        proc = run_cmd(argv)
                    except Exception as exc:
                        failed_step = name
                        done.append(f"FAILED: {name}: {exc}")
                        break
                except Exception as exc:
                    failed_step = name
                    done.append(f"FAILED: {name}: {exc}")
                    break
                code = int(getattr(proc, "returncode", 1) or 0)
                if code != 0:
                    err = (getattr(proc, "stderr", None) or getattr(proc, "stdout", None) or "")[:200]
                    failed_step = name
                    done.append(f"FAILED: {name} exit {code}" + (f": {err.strip()}" if err else ""))
                    break
                done.append(" ".join(argv))
            if failed_step is None:
                done.append("systemctl enable --now mill-wall")
        elif failed_step is None:
            done.append(f"wrote {files['systemd']} - copy to /etc/systemd/system as root and enable")
    if http == "nginx" and "nginx" in httpd:
        done.append(f"nginx at {httpd['nginx']}: include {files['nginx']} and reload (needs admin)")
    return {"ok": failed_step is None, "steps": done, "failed_step": failed_step}


def _apply_mill_wall_service(files: dict[str, Path], *, dest: Path, agent: bool = False) -> list[str]:
    """Register mill-wall as a Windows SERVICE (sc create), not schtasks ONLOGON."""
    done: list[str] = []
    py = python_exe()
    # Prefer bind/port encoded in wall.cmd when present
    bind, port, api_only = "127.0.0.1", 8765, True
    cmd_path = files.get("cmd")
    if cmd_path and Path(cmd_path).is_file():
        body = Path(cmd_path).read_text(encoding="utf-8", errors="replace")
        import re as _re

        m = _re.search(r"--bind\s+(\S+)", body)
        if m:
            bind = m.group(1)
        m = _re.search(r"--port\s+(\d+)", body)
        if m:
            port = int(m.group(1))
        api_only = "--api-only" in body
    binpath = mill_wall_service_binpath(python=py, bind=bind, port=port, api_only=api_only)
    state = _windows_service_state("mill-wall")
    if state == "ABSENT":
        create = subprocess.run(
            [
                "sc",
                "create",
                "mill-wall",
                "binPath=",
                binpath,
                "start=",
                "auto",
                "DisplayName=",
                "mill wall API",
            ],
            capture_output=True,
            text=True,
        )
        msg = ((create.stderr or "") + "\n" + (create.stdout or "")).strip()
        if create.returncode != 0:
            if _scm_needs_admin(msg):
                print_loud_access_denied(f"mill-wall sc create: {msg.replace(chr(10), ' ')[:160]}")
                done.append(
                    f"FAILED: mill-wall SERVICE create needs Admin/UAC. {msg[:160]}. "
                    "Use Hidden elevate helper (register-windows-services.ps1). "
                    "Do not use schtasks powershell as Pass."
                )
            else:
                done.append(f"sc create mill-wall failed: {msg[:200]}")
        else:
            done.append("sc create mill-wall SERVICE")
            subprocess.run(
                ["sc", "description", "mill-wall", "mill wall API (FastAPI behind nginx TLS)"],
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "sc",
                    "failure",
                    "mill-wall",
                    "reset=",
                    "86400",
                    "actions=",
                    "restart/5000/restart/5000/restart/5000",
                ],
                capture_output=True,
                text=True,
            )
    else:
        config = subprocess.run(
            ["sc", "config", "mill-wall", "binPath=", binpath, "start=", "auto"],
            capture_output=True,
            text=True,
        )
        if config.returncode != 0:
            msg = ((config.stderr or "") + "\n" + (config.stdout or "")).strip()
            if _scm_needs_admin(msg):
                print_loud_access_denied(f"mill-wall sc config: {msg.replace(chr(10), ' ')[:160]}")
                done.append(f"FAILED: mill-wall SERVICE config needs Admin/UAC. {msg[:160]}")
            else:
                done.append(f"sc config mill-wall: {msg[:160]}")
        else:
            done.append("sc config mill-wall SERVICE")
    # Drop leftover schtasks so Ctrl+C window close cannot kill the API path
    subprocess.run(["schtasks", "/Delete", "/TN", "mill-wall", "/F"], capture_output=True, text=True)
    done.append("schtasks mill-wall removed if present (SERVICE is SoR)")
    started, note = _start_windows_service("mill-wall")
    done.append(note)
    if not started:
        helper = files.get("scm_helper") or (Path(dest) / "register-windows-services.ps1")
        if mill_agent_mode(agent):
            done.extend(launch_hidden_scm_helper(Path(helper)))
        else:
            done.append(
                "HUMAN: ONE Hidden elevate (auto-exit): "
                + " ".join(elevate_windows_scm_helper_argv(Path(helper), already_admin=windows_is_admin()))
            )
    # Keep helper text synced with SERVICE registration
    if files.get("scm_helper") or True:
        write_windows_scm_helper(
            dest, python=py, bind=bind, port=port, api_only=api_only
        )
        files["scm_helper"] = Path(dest) / "register-windows-services.ps1"
        done.append("register-windows-services.ps1 (MySQL+mill-wall SERVICE)")
    return done


def _lan_sans() -> str:
    names = ["DNS:localhost", "DNS:wall.local", "IP:127.0.0.1"]
    try:
        host = socket.gethostbyname(socket.gethostname())
        if host and not host.startswith("127."):
            names.append(f"IP:{host}")
    except OSError:
        pass
    extra = (os.environ.get("AGENT_COORD_WALL_IPS") or "").replace(";", ",")
    for raw in extra.split(","):
        ip = raw.strip()
        if ip and f"IP:{ip}" not in names and f"DNS:{ip}" not in names:
            names.append(f"IP:{ip}" if ip[:1].isdigit() else f"DNS:{ip}")
    return ",".join(names)

def _openssl_env(openssl: Path) -> dict[str, str]:
    env = os.environ.copy()
    cnf = openssl.parent.parent / "conf" / "openssl.cnf"
    if cnf.is_file():
        env["OPENSSL_CONF"] = str(cnf)
    return env

def _wall_leaf_issued_by_ca(openssl: Path, leaf: Path, ca: Path, env: dict[str, str]) -> bool:
    """True when wall.crt verifies against mill CA (not a leftover self-signed leaf)."""
    if not leaf.is_file() or not ca.is_file():
        return False
    run = subprocess.run(
        [str(openssl), "verify", "-CAfile", str(ca), str(leaf)],
        capture_output=True,
        text=True,
        env=env,
    )
    out = ((run.stdout or "") + (run.stderr or "")).strip()
    return run.returncode == 0 and "OK" in out

def browser_trust_note(trust: list[str]) -> str:
    """What the human should do with the OS certificate prompt. Never wall.crt."""
    blob = " ".join(trust)
    if "system store" in blob and "trusted mill CA" in blob:
        return (
            "The mill CA is in the system trust store. Restart the browser. "
            "Do not import wall.crt."
        )
    if "trusted mill CA" in blob:
        return (
            "Windows asked to trust the mill CA (mill-wall-ca). Accept that prompt. "
            "Restart the browser. Do not import wall.crt."
        )
    if "already in CurrentUser Root" in blob:
        return (
            "This mill CA is already trusted for this user. Restart the browser if it was open. "
            "Do not import wall.crt."
        )
    if "trust mill CA failed" in blob or "trust skipped" in blob:
        return (
            "mill join could not trust ca.crt. Accept the mill CA prompt if it appears, "
            "or import ca.crt into this user. Do not import wall.crt. Restart the browser."
        )
    return "mill join trusts ca.crt for this user (never wall.crt). Restart the browser."


def _trust_mill_ca_current_user(ca_crt: Path) -> list[str]:
    """Trust mill CA in CurrentUser Root (Windows). Idempotent. Never import wall.crt."""
    if os.name != "nt":
        return []
    if not ca_crt.is_file():
        return ["trust skipped: no ca.crt"]
    ps_thumb = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "(New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('"
            + str(ca_crt).replace("'", "''")
            + "')).Thumbprint",
        ],
        capture_output=True,
        text=True,
    )
    thumb = (ps_thumb.stdout or "").strip().upper().replace(" ", "")
    if thumb and ps_thumb.returncode == 0:
        check = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "if (Get-ChildItem Cert:\\CurrentUser\\Root | Where-Object { $_.Thumbprint -eq '"
                + thumb
                + "' }) { 'YES' } else { 'NO' }",
            ],
            capture_output=True,
            text=True,
        )
        if "YES" in (check.stdout or ""):
            return ["mill CA already in CurrentUser Root (" + thumb[:8] + "...)"]
    run = subprocess.run(
        ["certutil", "-user", "-addstore", "Root", str(ca_crt)],
        capture_output=True,
        text=True,
    )
    msg = ((run.stdout or "") + "\n" + (run.stderr or "")).strip().replace("\n", " ")[:200]
    if run.returncode == 0:
        return ["trusted mill CA in CurrentUser Root (" + (msg or "ok") + ")"]
    return ["trust mill CA failed: " + (msg or ("exit " + str(run.returncode)))]


def _ensure_mill_ca(ssl_dir: Path, openssl: Path, env: dict[str, str]) -> tuple[Path, Path]:
    """Persistent mill CA (CN=mill-wall-ca, 3650d). Never overwrite existing CA files."""
    ca_crt, ca_key = ssl_dir / "ca.crt", ssl_dir / "ca.key"
    if ca_crt.is_file() and ca_key.is_file():
        return ca_crt, ca_key
    subprocess.run(
        [
            str(openssl),
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-days",
            "3650",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_crt),
            "-subj",
            "/CN=mill-wall-ca",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    return ca_crt, ca_key

def _mint_wall_leaf(
    ssl_dir: Path,
    openssl: Path,
    env: dict[str, str],
    ca_crt: Path,
    ca_key: Path,
    crt: Path,
    key: Path,
) -> None:
    """Mint wall.crt/wall.key as a leaf signed by the mill CA (SAN = _lan_sans())."""
    csr = ssl_dir / "wall.csr"
    sans = _lan_sans()
    subprocess.run(
        [
            str(openssl),
            "req",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            "/CN=wall.local",
            "-addext",
            f"subjectAltName={sans}",
        ],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    ext = ssl_dir / "wall_leaf.ext"
    ext.write_text(
        "basicConstraints=CA:FALSE\n"
        "keyUsage=digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        f"subjectAltName={sans}\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                str(openssl),
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_crt),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(crt),
                "-days",
                "825",
                "-extfile",
                str(ext),
            ],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
    finally:
        try:
            csr.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            ext.unlink(missing_ok=True)
        except OSError:
            pass

def _make_wall_cert(ssl_dir: Path, openssl: Path) -> tuple[Path, Path]:
    """Ensure mill CA + CA-signed wall leaf. Windows: trust CA in CurrentUser Root (not wall.crt)."""
    ssl_dir.mkdir(parents=True, exist_ok=True)
    crt, key = ssl_dir / "wall.crt", ssl_dir / "wall.key"
    env = _openssl_env(openssl)
    ca_crt, ca_key = _ensure_mill_ca(ssl_dir, openssl, env)
    if not (crt.is_file() and key.is_file() and _wall_leaf_issued_by_ca(openssl, crt, ca_crt, env)):
        _mint_wall_leaf(ssl_dir, openssl, env, ca_crt, ca_key, crt, key)
    if os.name == "nt":
        _trust_mill_ca_current_user(ca_crt)
    return crt, key

def _firewall_https() -> list[str]:
    # WSL/Linux: never bare `powershell` (FileNotFoundError). Windows: powershell.exe only.
    if os.name != "nt":
        return ["firewall skipped (non-Windows)"]
    out: list[str] = []
    for port, name in ((443, "mill wall 443"), (80, "mill wall 80")):
        run = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"New-NetFirewallRule -DisplayName '{name}' -Direction Inbound "
                f"-Protocol TCP -LocalPort {port} -Action Allow -Profile Private "
                "-ErrorAction SilentlyContinue | Out-Null",
            ],
            capture_output=True,
            text=True,
        )
        if run.returncode == 0:
            out.append(f"firewall {port} Private")
    return out

def _httpd_bins() -> dict[str, str]:
    return detect_httpd_bins()


def _book_services() -> list[dict[str, str]]:
    if os.name != "nt":
        return _posix_book_services()
    cmd = (
        "Get-Service | Where-Object { $_.Name -match 'mysql|maria' } | "
        "Select-Object @{n='Name';e={$_.Name}}, "
        "@{n='Status';e={$_.Status.ToString()}}, "
        "@{n='StartType';e={$_.StartType.ToString()}} | ConvertTo-Json -Compress"
    )
    run = subprocess.run(
        ["powershell", "-NoProfile", "-Command", cmd],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0 or not (run.stdout or "").strip():
        return []
    raw = run.stdout.strip()
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    out: list[dict[str, str]] = []
    for row in data or []:
        out.append(
            {
                "name": str(row.get("Name") or ""),
                "status": str(row.get("Status") or ""),
                "start_type": str(row.get("StartType") or ""),
            }
        )
    return [r for r in out if r["name"]]


def _posix_book_services() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not shutil.which("systemctl"):
        return out
    for unit in ("mysql", "mysqld", "mariadb"):
        try:
            run = subprocess.run(
                ["systemctl", "show", unit, "-p", "LoadState", "-p", "ActiveState"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            return out
        fields = {}
        for line in (run.stdout or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                fields[k.strip()] = v.strip()
        if fields.get("LoadState") != "loaded":
            continue
        out.append(
            {
                "name": unit,
                "status": fields.get("ActiveState") or "unknown",
                "start_type": "systemd",
            }
        )
    return out


def _book_reachable() -> dict[str, Any]:
    try:
        import mysql.connector

        from agent_coord.config import mysql_kwargs

        kw = mysql_kwargs()
        kw.pop("database", None)
        kw["autocommit"] = True
        kw["connection_timeout"] = 5
        cn = mysql.connector.connect(**kw)
        cn.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}



def probe_cloud_local(*, dest: Path | None = None) -> dict[str, Any]:
    """Local-only S3 probes for mill install cloud. No cloud API calls; no key storage."""
    dest = dest or office_dir()
    probes: dict[str, Any] = {}

    # https_443_intent - listening or configs intend 443
    listening_443 = False
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            listening_443 = s.connect_ex(("127.0.0.1", 443)) == 0
    except OSError:
        listening_443 = False
    conf_443 = False
    for name in ("nginx-wall.conf", "httpd-wall.conf", "wall.env"):
        p = dest / name
        if p.is_file():
            try:
                blob = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                blob = ""
            if "443" in blob:
                conf_443 = True
                break
    https_ok = bool(listening_443 or conf_443)
    probes["https_443_intent"] = {
        "id": "https_443_intent",
        "ok": https_ok,
        "skip": False,
        "detail": (
            "443 listening on loopback"
            if listening_443
            else ("wall/httpd config intends 443" if conf_443 else "443 not listening yet; configs do not show 443 - expected before install server --apply --public")
        ),
    }

    # mysql_not_public_bind - mysqld-office.cnf or common cnf bind-address
    bind_detail = "no mysqld bind snippet found yet (default after install: private/loopback)"
    bind_ok = True  # fail-open until configured; warn only if clearly public
    bind_skip = True
    cnf_candidates = [
        dest / "mysqld-office.cnf",
        Path("/etc/mysql/mysql.conf.d/mysqld.cnf"),
        Path("/etc/mysql/mariadb.conf.d/50-server.cnf"),
        Path("/etc/my.cnf"),
    ]
    for cnf in cnf_candidates:
        if not cnf.is_file():
            continue
        try:
            blob = cnf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        bind_skip = False
        public = False
        for line in blob.splitlines():
            raw = line.split("#", 1)[0].strip().lower()
            if raw.startswith("bind-address") and "=" in raw:
                val = raw.split("=", 1)[1].strip().strip('"').strip("'")
                if val in ("0.0.0.0", "::", "*"):
                    public = True
                    bind_detail = f"{cnf}: bind-address={val} (public - refuse for S3)"
                else:
                    bind_detail = f"{cnf}: bind-address={val}"
                break
        if "Never 0.0.0.0/0" in blob or "bind-address = 127.0.0.1" in blob.replace(" ", ""):
            # office snippet style
            if not public:
                bind_detail = f"{cnf}: private bind intent"
        bind_ok = not public
        break
    probes["mysql_not_public_bind"] = {
        "id": "mysql_not_public_bind",
        "ok": bind_ok,
        "skip": bind_skip,
        "detail": bind_detail,
    }

    # ssh_hardened_signal - readable sshd_config cues only
    ssh_ok = False
    ssh_skip = True
    ssh_detail = "sshd_config not readable on this host (skip)"
    if os.name != "nt":
        for sshd in (Path("/etc/ssh/sshd_config"), Path("/etc/sshd_config")):
            if not sshd.is_file():
                continue
            try:
                blob = sshd.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ssh_skip = False
            lines = []
            for line in blob.splitlines():
                raw = line.split("#", 1)[0].strip()
                if not raw:
                    continue
                low = raw.lower()
                if low.startswith("passwordauthentication") or low.startswith("permitrootlogin"):
                    lines.append(raw)
            joined = " | ".join(lines) if lines else "no PasswordAuthentication/PermitRootLogin lines"
            hardened = False
            lowblob = "\n".join(lines).lower()
            if "passwordauthentication no" in lowblob:
                hardened = True
            if "permitrootlogin no" in lowblob or "permitrootlogin prohibit-password" in lowblob or "permitrootlogin without-password" in lowblob:
                hardened = True
            ssh_ok = hardened
            ssh_detail = joined
            break
    else:
        ssh_detail = "Windows host: lock RDP to operator (no sshd_config probe)"
        ssh_skip = True
        ssh_ok = False
    probes["ssh_hardened_signal"] = {
        "id": "ssh_hardened_signal",
        "ok": ssh_ok,
        "skip": ssh_skip,
        "detail": ssh_detail,
    }

    # door_invite - invite is default on public hosts
    door = "path"
    try:
        from agent_coord.server.admin.door import mode as door_mode

        door = str(door_mode() or "path")
    except Exception:
        door = "path"
    door_ok = door == "invite"
    probes["door_invite"] = {
        "id": "door_invite",
        "ok": door_ok,
        "skip": False,
        "detail": f"door={door}" + ("" if door_ok else " (public hosts: mill invite --door invite)"),
    }

    return {
        "probes": probes,
        "summary": {
            "https_443_intent": probes["https_443_intent"]["ok"],
            "mysql_not_public_bind": probes["mysql_not_public_bind"]["ok"] or probes["mysql_not_public_bind"]["skip"],
            "ssh_hardened_signal": probes["ssh_hardened_signal"]["ok"] or probes["ssh_hardened_signal"]["skip"],
            "door_invite": probes["door_invite"]["ok"],
        },
    }


def cloud_notes(provider: str = "self") -> str:
    from agent_coord.install.catalog import (
        PRINTED_CLOUD_IDS,
        cloud_runbook,
        normalize_cloud,
        printed_cloud_id,
    )

    requested = normalize_cloud(provider)
    pid = printed_cloud_id(requested)
    printed = "|".join(PRINTED_CLOUD_IDS)
    return f"""# Cloud office - S3 agent spine (wording + local probes)

Single-tenant office on a VM: same product as a local host. Mill never stores cloud access keys and never calls cloud APIs.

## Spine (on the VM)

```
python -m pip install the-mill
mill install server --apply --public
mill init --yes
```

`--public` = Wall/API reachability off-box - **not** open MySQL.

## Door

**Invite door DEFAULT** on public hosts. Mint/enable invite; desks `mill join` + `mill connect`.
**No VPN-as-door.**

## Printed providers

First-class in this runbook: `{printed}`. This runbook: **{pid}** (requested `{requested}`).
Other provider ids normalize to generic Linux (`self`) for printing.
Playbook: `docs/install/cloud/{pid}.md` (installed pack: `share/the-mill/docs/install/cloud/{pid}.md`).

## Local probe contract

Named probes (this machine only): `https_443_intent`, `mysql_not_public_bind`, `ssh_hardened_signal`, `door_invite`.
See docs/install/CLOUD.md. Not a substitute for live cloud VM measure.

## Status

**not measured OOTB** until #502 (`ootb-cloud-aws-azure-gcp`). Linux systemd mill-wall OOTB also deferred.

## Day-2

`mill update` then recycle mill-wall - see docs/install/HOST.md.

## Book

Default: **MySQL 8 (InnoDB)** on the VM, bind `127.0.0.1`. Managed DB later. Do not invent migrate.

## Done-report shape

- Wall: `https://<dns-or-ip>/`
- Join: `mill invite --seat <desk> --roster <roster>` mints the welcome link; the desk saves it to a file and runs `mill join --link-file LINKFILE` then `mill connect DESK` (docs/JOIN.md)
- Security checklist ticks: MySQL not public; Wall HTTPS on 443; SSH/RDP locked; invite door; no cloud keys in mill; join fail-closed if CA missing

{cloud_runbook(requested)}
"""


def _write_cloud(dest: Path, provider: str = "self") -> dict[str, Any]:
    from agent_coord.install.catalog import normalize_cloud, printed_cloud_id

    path = dest / "cloud-office.txt"
    requested = normalize_cloud(provider)
    pid = printed_cloud_id(requested)
    text = cloud_notes(provider)
    path.write_text(text, encoding="utf-8")
    probe_row = probe_cloud_local(dest=dest)
    probes = probe_row.get("probes") or {}
    # Append probe snapshot to runbook for agent evidence
    lines = ["", "## Local probe snapshot (this machine)", ""]
    for key in ("https_443_intent", "mysql_not_public_bind", "ssh_hardened_signal", "door_invite"):
        row = probes.get(key) or {}
        state = "skip" if row.get("skip") else ("pass" if row.get("ok") else "warn")
        lines.append(f"- `{key}`: {state} - {row.get('detail') or ''}")
    lines.append("")
    lines.append("Status: **not measured OOTB** / #502 until measured.")
    lines.append("")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    warnings: list[str] = []
    if "0.0.0.0/0" in text and "never 0.0.0.0/0" not in text.lower():
        warnings.append("cloud notes must refuse a public MySQL security group")
    mysql_probe = probes.get("mysql_not_public_bind") or {}
    if mysql_probe.get("ok") is False and not mysql_probe.get("skip"):
        warnings.append(str(mysql_probe.get("detail") or "MySQL bind looks public"))

    next_steps = [
        "Wall https://<dns-or-ip>/",
        "Invite/join: mill invite --seat <desk> --roster <roster>; the desk saves it to a file and runs mill join --link-file LINKFILE then mill connect DESK (docs/JOIN.md)",
        "Security checklist: MySQL not public; Wall HTTPS 443; SSH/RDP locked; invite door; no cloud keys in mill; CA fail-closed",
        "not measured OOTB / #502 until measured",
        f"Provider appendix printed as {pid} (requested {requested}); first-class: aws|azure|gcp|self",
    ]
    if not (probes.get("door_invite") or {}).get("ok"):
        next_steps.insert(1, "Public host: mill invite --door invite (then mint/enable)")

    return {
        "ok": not warnings,
        "role": "cloud",
        "provider": pid,
        "provider_requested": requested,
        "files": [str(path)],
        "probes": probes,
        "probe_summary": probe_row.get("summary") or {},
        "warnings": warnings,
        "next": next_steps,
        "measured_ootb": False,
        "issue": 502,
    }


def _check(cid: str, ok: bool, detail: str, *, skip: bool = False) -> dict[str, Any]:
    return {"id": cid, "ok": bool(ok), "skip": bool(skip), "detail": detail}


def check_office(*, dest: Path | None = None, live: bool = True) -> dict[str, Any]:
    """Judge the three installs on this machine. Skip what this OS cannot host."""
    dest = dest or office_dir()
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / "nginx-wall.conf").is_file():
        _write_wall(dest, http="service", apply=False, public_bind="127.0.0.1", public_port=8765)
    if not (dest / "cloud-office.txt").is_file():
        _write_cloud(dest)
    html = (wall_ui_default_dir() / "board.html").read_text(encoding="utf-8")
    css_path = wall_ui_default_dir() / "board.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""
    checks: list[dict[str, Any]] = []
    py_ok = sys.version_info >= MIN_PY
    checks.append(
        _check(
            "python",
            py_ok,
            f"{sys.version.split()[0]} (need {MIN_PY[0]}.{MIN_PY[1]}+ for mill desk)",
        )
    )
    from agent_coord.client.http import mill_here_over_http as _here

    mill_ok = callable(_here)
    checks.append(
        _check(
            "cli_mill_connect",
            mill_ok,
            "pip install gives mill connect",
        )
    )
    vhost = (dest / "nginx-wall.conf").read_text(encoding="utf-8") if (dest / "nginx-wall.conf").is_file() else ""
    unit = (dest / "mill-wall.service").read_text(encoding="utf-8") if (dest / "mill-wall.service").is_file() else ""
    cmd = (dest / "wall.cmd").read_text(encoding="utf-8") if (dest / "wall.cmd").is_file() else ""
    cloud = (dest / "cloud-office.txt").read_text(encoding="utf-8") if (dest / "cloud-office.txt").is_file() else ""
    mill_tls = (dest / "ssl" / "wall.crt").is_file() and (dest / "ssl" / "wall.key").is_file()
    win_svc = os.name == "nt" and _windows_service_state("mill-wall") == "RUNNING"
    if os.name == "nt":
        checks.append(_check("linux_unit", True, "Windows mill-wall SERVICE (not systemd)", skip=True))
    else:
        checks.append(_check("linux_unit", "ExecStart=" in unit and "agent_coord wall" in unit, str(dest / "mill-wall.service")))
    if win_svc and mill_tls:
        checks.append(_check("nginx_vhost", True, "Windows --http service; mill-wall TLS (not nginx)", skip=True))
        checks.append(_check("https_redirect", True, "mill-wall HTTPS; no nginx redirect", skip=True))
        checks.append(_check("https_only_product", True, "mill-wall SERVICE TLS wall.crt"))
        checks.append(_check("no_cleartext_mode", mill_tls, "mill-wall TLS certs present"))
    else:
        checks.append(_check("nginx_vhost", "proxy_pass" in vhost and "ssl_certificate" in vhost, str(dest / "nginx-wall.conf")))
        checks.append(_check("https_redirect", "RewriteRule ^ https://" in vhost or "return 301 https://" in vhost, "HTTP->HTTPS redirect present"))
        checks.append(_check("https_only_product", "ssl_certificate" in vhost and "listen" in vhost and "443 ssl" in vhost, "Wall vhost terminates TLS"))
        checks.append(_check("no_cleartext_mode", "return 301 https://" in vhost, "no HTTP convenience mode"))
    checks.append(_check("wall_wrapper_no_owner", "AGENT_COORD_OWNER" not in cmd and "AGENT_COORD_OWNER" not in unit, "wall unit must not clock in"))
    lan_blob = vhost + ((dest / "nginx-wall.conf").read_text(encoding="utf-8") if (dest / "nginx-wall.conf").is_file() else "")
    if "LAN-only" in lan_blob or "lan_only=1" in lan_blob:
        lan_ok = "Listen 0.0.0.0" not in vhost and "VirtualHost *:" not in vhost
        checks.append(_check("lan_only_listen", lan_ok, "lan-only Listen is private/loopback"))
    else:
        checks.append(_check("lan_only_listen", True, "not lan-only (wildcard Listen allowed)", skip=True))
    ca = mill_ca_crt(dest)
    checks.append(
        _check(
            "mill_ca",
            ca.is_file() and ca.name == "ca.crt" and ca.name.lower() != "wall.crt",
            "trust mill ca.crt; never wall.crt",
            skip=not ca.is_file(),
        )
    )
    ios_ok = ios_wall_contract(html, css) or _ios_wall_ok(dest)
    checks.append(
        _check(
            "ios_wall_html",
            ios_ok,
            "iOS is a wall (Safari): viewport + home-screen meta + narrow layout. Not a mill desk.",
        )
    )
    cloud_ok = ("not measured OOTB" in cloud and "#502" in cloud and "mill install server --apply --public" in cloud and "No VPN-as-door" in cloud and "mill join" in cloud and "mill connect" in cloud and "never 0.0.0.0/0" in cloud.lower())
    checks.append(_check("cloud_notes", cloud_ok, str(dest / "cloud-office.txt")))

    s = settings()
    book = _book_reachable()
    if live:
        checks.append(_check("book_reachable", book["ok"], book.get("error") or f"{s['host']}:{s['port']}"))
        services = _book_services()
        host = str(s["host"])
        local_book = host in ("127.0.0.1", "localhost", "::1")
        if local_book:
            checks.append(
                _check(
                    "book_service",
                    bool(services),
                    ", ".join(f"{r['name']} {r.get('status')}" for r in services) or "no mysql/mariadb OS service",
                )
            )
        else:
            checks.append(
                _check(
                    "book_service",
                    True,
                    f"book host {host} is remote; OS service is on that VM (AWS RDS/EC2, etc.)",
                    skip=True,
                )
            )
        urls = [u for u in share_wall_urls() if str(u).startswith("https://")]
        wall_http = _wall_http(urls=urls, ca=mill_ca_crt(dest))
        checks.append(
            _check(
                "wall_http",
                wall_http["ok"],
                wall_http.get("detail") or (urls[0] if urls else "https://127.0.0.1/"),
            )
        )
        not_session = wall_http.get("not_session")
        if wall_http["ok"] and wall_http.get("floor_ok") is False:
            checks.append(
                _check(
                    "wall_not_session",
                    True,
                    "floor down; cannot judge HERE",
                    skip=True,
                )
            )
        elif wall_http["ok"]:
            checks.append(
                _check(
                    "wall_not_session",
                    bool(not_session),
                    "HERE must not list the wall as a mill owner",
                )
            )
        else:
            checks.append(_check("wall_not_session", False, "wall HTTP down; cannot judge HERE", skip=True))
        if os.name == "nt":
            task = _wall_task()
            checks.append(_check("wall_os_unit", task["ok"], task.get("detail") or "SERVICE mill-wall"))
        else:
            checks.append(
                _check(
                    "wall_os_unit",
                    True,
                    "systemd unit written; enable on the wall host with systemctl",
                    skip=True,
                )
            )
    else:
        checks.append(_check("book_reachable", True, "skipped (live=false)", skip=True))
        checks.append(_check("book_service", True, "skipped (live=false)", skip=True))
        checks.append(_check("wall_http", True, "skipped (live=false)", skip=True))
        checks.append(_check("wall_not_session", True, "skipped (live=false)", skip=True))
        checks.append(_check("wall_os_unit", True, "skipped (live=false)", skip=True))

    matrix = _matrix(checks)
    failed = [c for c in checks if not c["skip"] and not c["ok"]]
    return {
        "ok": not failed,
        "role": "check",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "checks": checks,
        "matrix": matrix,
        "failed": [c["id"] for c in failed],
        "warnings": [f"{c['id']}: {c['detail']}" for c in failed],
        "next": [
            "Mill desk: Windows, macOS, Linux (Python 3.10+). Not iOS.",
            "iOS/Android: wall URL only.",
            "Cloud/S3: mill install cloud writes spine runbook + local probes (no cloud APIs); #502 until measured.",
            "Linux mill: Ubuntu 22.04+ / Amazon Linux 2023. Ubuntu 20.04 python3.8 is below the mill.",
        ],
    }


def _wall_http(
    url: str | None = None,
    *,
    urls: list[str] | None = None,
    ca: Path | None = None,
    urlopen: Any = None,
    ssl_context: Any = None,
) -> dict[str, Any]:
    """Probe mill HTTPS :443 with mill CA. Never wall.crt. :8765 down is not a Fail."""
    import json
    import ssl
    import urllib.error
    import urllib.request

    probe = list(urls or [])
    if url:
        probe.append(url)
    https: list[str] = []
    for raw in probe:
        u = str(raw or "").strip()
        if not u or ":8765" in u:
            continue
        if u.startswith("https://"):
            https.append(u)
    if not https:
        https = [u for u in share_wall_urls() if str(u).startswith("https://")]
    ca_path = Path(ca) if ca is not None else mill_ca_crt()
    opener = urlopen or urllib.request.urlopen
    ctx = ssl_context
    if ctx is None:
        if ca_path.name.lower() == "wall.crt":
            return {"ok": False, "detail": "never import wall.crt; use mill ca.crt"}
        if not ca_path.is_file():
            return {"ok": False, "detail": "mill ca.crt missing; never import wall.crt"}
        ctx = ssl.create_default_context(cafile=str(ca_path))
    last = "HTTPS :443 down"
    for u in https:
        try:
            with opener(u, timeout=5, context=ctx) as resp:
                html = resp.read()
                code = resp.status
        except (urllib.error.URLError, TimeoutError, OSError, TypeError) as e:
            last = f"{u} {e}"
            continue
        if code != 200 or b"factory" not in html.lower():
            last = f"{u} status={code}"
            continue
        not_session = True
        try:
            with opener(u.rstrip("/") + "/api/v1/agents?project=Office", timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for rec in data.get("agents") or []:
                if (rec.get("doing") or "") == "standup-wall":
                    not_session = False
                    break
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, TypeError, ValueError) as e:
            return {
                "ok": True,
                "detail": f"{u} html ok; floor {e}",
                "not_session": None,
                "floor_ok": False,
            }
        return {"ok": True, "detail": u, "not_session": not_session, "floor_ok": True}
    return {"ok": False, "detail": last}


def _wall_task() -> dict[str, Any]:
    """Windows mill-wall must be an SCM SERVICE (not schtasks ONLOGON)."""
    state = _windows_service_state("mill-wall")
    if state == "RUNNING":
        return {"ok": True, "detail": "SERVICE mill-wall RUNNING"}
    if state in ("STOPPED", "START_PENDING", "UNKNOWN"):
        return {"ok": False, "detail": f"SERVICE mill-wall {state}"}
    return {"ok": False, "detail": "SERVICE mill-wall ABSENT (not schtasks)"}


def _matrix(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {c["id"]: c for c in checks}

    def status(cid: str) -> str:
        c = by.get(cid)
        if c is None:
            return "skip"
        if c.get("skip"):
            return "skip"
        return "pass" if c.get("ok") else "fail"

    return [
        {
            "target": "windows-desk",
            "kind": "mill",
            "status": "pass" if sys.platform == "win32" and by["python"]["ok"] else ("skip" if sys.platform != "win32" else "fail"),
            "note": "this process" if sys.platform == "win32" else "run install check on Windows",
        },
        {
            "target": "linux-desk",
            "kind": "mill",
            "status": "pass" if sys.platform.startswith("linux") and by["python"]["ok"] else ("skip" if not sys.platform.startswith("linux") else "fail"),
            "note": "Python 3.10+ (Ubuntu 22.04 / AL2023). Not Ubuntu 20.04 python3.8.",
        },
        {
            "target": "macos-desk",
            "kind": "mill",
            "status": "pass" if sys.platform == "darwin" and by["python"]["ok"] else "skip",
            "note": "pip install + presence; not live on this box unless darwin",
        },
        {
            "target": "ios-wall",
            "kind": "wall",
            "status": status("ios_wall_html"),
            "note": "Safari / PWA. No mill CLI, no presence.",
        },
        {
            "target": "linux-wall-unit",
            "kind": "wall",
            "status": status("linux_unit"),
            "note": "systemd unit written; enable on the Linux wall host",
        },
        {
            "target": "windows-wall-unit",
            "kind": "wall",
            "status": status("wall_os_unit") if os.name == "nt" else ("pass" if (by.get("wall_wrapper_no_owner") or {}).get("ok") else "skip"),
            "note": "SERVICE mill-wall",
        },
        {
            "target": "aws-office",
            "kind": "cloud",
            "status": "skip" if by["cloud_notes"]["ok"] else "fail",
            "note": "runbook+local probes; cloud VM OOTB not measured (#502). MySQL never public; invite door; no cloud keys.",
        },
    ]
