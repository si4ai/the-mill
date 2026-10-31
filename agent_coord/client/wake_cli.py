"""mill join delivery options (#618): websocket, or a webhook the wall POSTs to.

`mill join --link-file PATH --webhook-url URL --webhook-key-file PATH` joins and
arms the webhook in one command; `mill join DESK --webhook-url URL --webhook-key-file PATH`
changes a seated desk's delivery with no new link, authenticated by that desk's
own seat token (the same credential connect presents); `mill join DESK --websocket`
switches back. The key never comes from argv (a file, an env var name, or
stdin), is sent once to the wall, and is never printed. The wall row is the one
place the URL and key live; nothing is kept on this machine. One line prints:
{"kind": "wake", ...} with the host and the test POST status, never the path or key.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_coord.helpers.errors import CoordError

KEY_ARGV = (
    "join: --webhook-key on the command line is refused (shell history and process lists keep it); "
    "use --webhook-key-file PATH, --webhook-key-env NAME or --webhook-key-stdin"
)


def _read_file(path: str, what: str) -> str:
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        raise CoordError(f"join: no webhook {what} file at {path}")
    try:
        return p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise CoordError(f"join: could not read the webhook {what} file ({type(e).__name__})") from None


def _key_picks(args: Any) -> list[bool]:
    return [
        bool(str(getattr(args, "webhook_key_file", "") or "").strip()),
        bool(str(getattr(args, "webhook_key_env", "") or "").strip()),
        bool(getattr(args, "webhook_key_stdin", False)),
    ]


def read_key(args: Any, stdin=None) -> str:
    """The raw key text from exactly one of the three key options."""
    picks = _key_picks(args)
    if sum(picks) == 0:
        raise CoordError(
            "join: webhook key required: --webhook-key-file PATH, --webhook-key-env NAME "
            "or --webhook-key-stdin (the routine's key)"
        )
    if sum(picks) > 1:
        raise CoordError("join: give the webhook key one way: --webhook-key-file, --webhook-key-env or --webhook-key-stdin")
    if picks[0]:
        return _read_file(str(args.webhook_key_file).strip(), "key")
    if picks[1]:
        name = str(args.webhook_key_env).strip()
        val = os.environ.get(name)
        if not val:
            raise CoordError(f"join: env var {name} is empty or unset")
        return val
    return (stdin or sys.stdin).read()


def read_url(args: Any) -> str:
    url = str(getattr(args, "webhook_url", "") or "")
    path = str(getattr(args, "webhook_url_file", "") or "").strip()
    if url and path:
        raise CoordError("join: give the webhook URL one way: --webhook-url or --webhook-url-file")
    if path:
        url = _read_file(path, "URL")
    return url.strip()


def delivery_body(args: Any, stdin=None) -> dict[str, Any] | None:
    """None: plain join (delivery unchanged). {"mode": "websocket"} or {"mode": "webhook", url, key[, wake_on]}.

    The URL and key shape are checked here, before anything is sent; the wall
    checks again and alone knows its host allowlist.
    """
    from agent_coord.server.wake import WakeRefused, check_url, normalize_key

    if getattr(args, "webhook_key", None) is not None:
        raise CoordError(KEY_ARGV)
    has_url = bool(str(getattr(args, "webhook_url", "") or "").strip() or str(getattr(args, "webhook_url_file", "") or "").strip())
    has_key = any(_key_picks(args))
    ws = bool(getattr(args, "websocket", False))
    wake_on = str(getattr(args, "wake_on", "") or "").strip().lower()
    if wake_on and (ws or not (has_url or has_key)):
        raise CoordError("join: --wake-on goes with --webhook-url-file and --webhook-key-file")
    if ws and (has_url or has_key):
        raise CoordError("join: --websocket takes no webhook options")
    if ws:
        return {"mode": "websocket"}
    if not has_url and not has_key:
        return None
    raw_url = read_url(args)
    if not raw_url:
        raise CoordError("join: webhook URL required: --webhook-url URL or --webhook-url-file PATH")
    raw_key = read_key(args, stdin)
    try:
        url, _host = check_url(raw_url, allow_only=False)
        key = normalize_key(raw_key)
    except WakeRefused as e:
        raise CoordError(str(e)) from None
    out = {"mode": "webhook", "url": url, "key": key}
    if wake_on:
        out["wake_on"] = wake_on  # #628; the wall checks the word
    return out


def _wall_error(e: BaseException) -> str:
    """The wall's refusal text, without the HTTP wrapper."""
    text = str(e)
    if text.startswith("mill-wall ") and "{" in text:
        try:
            got = json.loads(text[text.index("{"):])
            if isinstance(got, dict) and got.get("error"):
                return str(got["error"])
        except (ValueError, json.JSONDecodeError):
            pass
    return text


def run_seated(desk: str, delivery: dict[str, Any]) -> int:
    """Ask the wall to set this seated desk's delivery. One {"kind": "wake"} line."""
    from agent_coord.client.http import mill_http_call
    from agent_coord.client.tokens import read_session_token
    from agent_coord.const import CONST_OFFICE
    from agent_coord.helpers.ident import desk_name

    who = desk_name(desk)
    if not who or not read_session_token(who).strip():
        print(f"join: no seat for desk {desk or '?'} on this machine; mill join --link-file PATH first", file=sys.stderr, flush=True)
        return 2
    body = {
        "verb": "join",
        "cmd": "join",
        "project": CONST_OFFICE,
        "placeholder": True,
        "owner": who,
        "delivery": delivery,
    }
    try:
        row = mill_http_call(body)
    except CoordError as e:
        print(json.dumps({"kind": "wake", "desk": who, "webhook": "not armed", "error": _wall_error(e)}), file=sys.stderr, flush=True)
        return 1
    wake = (row or {}).get("wake") if isinstance(row, dict) else None
    if not isinstance(wake, dict):
        print(json.dumps({"kind": "wake", "desk": who, "error": "join: this wall does not set delivery; update the wall"}), file=sys.stderr, flush=True)
        return 1
    print(json.dumps(dict({"kind": "wake", "desk": who}, **wake)), flush=True)
    return 0
