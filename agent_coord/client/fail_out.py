"""One failure shape for a desk command (card 1238).

Stdout is one UTF-8 JSON object, no BOM. stderr is one ASCII line: code, then
the request id. Success printing is unchanged. The office's own refusal text
stays off both streams.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

_CAP = 200
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PATH = re.compile(r"(?:[A-Za-z]:\\|\\\\|/home/|/Users/)")

# code -> class, whether a retry can help, the public next step.
# busy and transport are the retryable classes. applied is false when nothing
# changed for sure, and omitted when a commit may have happened.
_CODES = {
    "refused": (
        "refusal",
        False,
        "The office refused this command. Change it and retry. The server log line has this id.",
    ),
    "tw_refused": (
        "refusal",
        False,
        "Run the command as a child of the shell that started mill connect.",
    ),
    "transport": (
        "transport",
        True,
        "Start mill connect in this shell and retry.",
    ),
    "busy": (
        "busy",
        True,
        "The office is busy. Retry this command.",
    ),
    "internal": (
        "internal",
        False,
        "The office hit an internal error. The server log line has this id.",
    ),
}


def classify(text: str, envelope: dict | None, exc: BaseException | None) -> str:
    """Stable code. The bridge hint names the same-parent rule, so that wins."""
    low = (text or "").lower()
    if "same parent process" in low:
        return "tw_refused"
    if "no sitting mill connect" in low or "disconnected:" in low:
        return "transport"
    err = ""
    if isinstance(envelope, dict):
        err = str(envelope.get("error") or "")
    if "busy" in (err or text or "").lower():
        return "busy"
    if isinstance(envelope, dict) and envelope.get("ok") is False:
        return "refused"
    if isinstance(envelope, dict) and envelope.get("error") and envelope.get("ok") is not True:
        return "refused"
    if exc is not None and any(c.__name__ == "CoordError" for c in type(exc).__mro__):
        return "refused"
    if exc is None and text:
        return "refused"
    return "internal"


def _env_secrets() -> list[str]:
    found: list[str] = []
    for value in os.environ.values():
        text = str(value or "")
        if len(text) >= 6 and text not in found:
            found.append(text)
    found.sort(key=len, reverse=True)
    return found


def _tainted(text: str, secrets: list[str]) -> bool:
    if _EMAIL.search(text) or _IPV4.search(text) or _PATH.search(text):
        return True
    from agent_coord.install.host import redact_user_paths

    if redact_user_paths(text) != text:
        return True
    for secret in secrets:
        if secret in text:
            return True
    return False


def _public_command(args: Any) -> str:
    argv: list[str] = []
    try:
        from agent_coord.client.session_errors import _typed

        argv = [str(a) for a in (_typed or [])]
    except Exception:
        argv = []
    if not argv and args is not None:
        cmd = str(getattr(args, "cmd", "") or getattr(args, "said_command", "") or "").strip()
        return cmd
    if not argv:
        return ""
    parts = [argv[0]]
    i = 1
    while i < len(argv):
        word = argv[i]
        if word.startswith("-") and not word.startswith("---"):
            parts.append(word.split("=", 1)[0])
            if "=" not in word and i + 1 < len(argv) and not str(argv[i + 1]).startswith("-"):
                i += 1
        i += 1
    return " ".join(parts)


def _activity(args: Any) -> str:
    if args is None:
        return ""
    typ = str(getattr(args, "type", "") or "").strip().lower()
    raw = getattr(args, "id", None)
    if typ in ("todo", "doing", "hold", "score", "mail", "wake") and str(raw or "").isdigit():
        nid = int(raw)
        if nid > 0:
            return "%s:%s" % (typ, nid)
    return ""


def _desk(args: Any) -> str:
    if args is None:
        return ""
    return str(getattr(args, "desk", "") or "").strip()


def _put(obj: dict, key: str, value: Any, secrets: list[str], cuts: list[int]) -> None:
    if value is None or value == "" or value == []:
        return
    blob = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=True)
    if _tainted(blob, secrets):
        return
    original = len(blob)
    if original > _CAP:
        if isinstance(value, str):
            obj[key] = value[:_CAP]
        elif isinstance(value, list):
            kept: list[Any] = []
            for item in value:
                trial = json.dumps(kept + [item], default=str, ensure_ascii=True)
                if len(trial) > _CAP:
                    break
                kept.append(item)
            obj[key] = kept
        else:
            obj[key] = blob[:_CAP]
        cuts.append(original)
        return
    obj[key] = value


def emit_failure(
    exc: BaseException | None = None,
    *,
    args: Any = None,
    text: str = "",
    envelope: dict | None = None,
) -> int:
    """Write the failure and return 1. Does not raise."""
    if exc is not None:
        text = text or str(exc)
        got = getattr(exc, "envelope", None)
        if envelope is None and isinstance(got, dict):
            envelope = got
    code = classify(text, envelope, exc)
    klass, _retry, nxt = _CODES[code]
    rid = ""
    if isinstance(envelope, dict):
        rid = str(envelope.get("id") or "").strip()
    if not rid:
        rid = str(uuid.uuid4())
    secrets = _env_secrets()
    cuts: list[int] = []
    obj: dict[str, Any] = {"ok": False, "code": code, "class": klass, "id": rid}
    if code != "internal":
        obj["applied"] = False
    _put(obj, "command", _public_command(args), secrets, cuts)
    _put(obj, "desk", _desk(args), secrets, cuts)
    _put(obj, "activity", _activity(args), secrets, cuts)
    server_mill = ""
    if isinstance(envelope, dict) and code not in ("transport", "tw_refused"):
        server_mill = str(envelope.get("mill") or "").strip()
        sync = envelope.get("sync")
        if isinstance(sync, list):
            _put(obj, "sync", sync, secrets, cuts)
        warns = envelope.get("label_warnings")
        if not isinstance(warns, list):
            result = envelope.get("result")
            if isinstance(result, dict):
                warns = result.get("label_warnings")
        if isinstance(warns, list):
            _put(obj, "label_warnings", [str(w) for w in warns], secrets, cuts)
    if server_mill and not _tainted(server_mill, secrets):
        obj["mill"] = server_mill[:_CAP]
        if len(server_mill) > _CAP:
            cuts.append(len(server_mill))
        try:
            from agent_coord.install.packver import package_version

            client = str(package_version() or "").strip()
        except Exception:
            client = ""
        if client and client != server_mill and not _tainted(client, secrets):
            obj["client_mill"] = client
    when = ""
    if isinstance(envelope, dict):
        when = str(envelope.get("time") or "").strip()
    if not when:
        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj["time"] = when
    _put(obj, "next", nxt, secrets, cuts)
    if cuts:
        obj["truncated"] = True
        obj["original_length"] = max(cuts)
    raw = json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(("%s %s\n" % (code, rid)).encode("ascii"))
    sys.stderr.buffer.flush()
    return 1
