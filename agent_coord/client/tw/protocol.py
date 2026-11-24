# -*- coding: utf-8 -*-
"""Newline JSON for the local tw link. Same bytes on every OS."""
from __future__ import annotations

import json
import re
from typing import Any

LINE_MAX = 8192
MAX_SESSIONS = 8


def dumps(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, separators=(",", ":"), default=str).encode("utf-8") + b"\n"


def loads(line: bytes) -> dict[str, Any]:
    msg = json.loads(line.decode("utf-8"))
    if not isinstance(msg, dict):
        raise ValueError("bad line")
    return msg


def reply(
    ok: bool,
    msg: str,
    watch_id: str | None = None,
    *,
    code: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "reply", "ok": bool(ok), "msg": msg}
    if watch_id:
        out["watch_id"] = watch_id
    if code:
        out["code"] = code
    return out


def line_too_long() -> dict[str, Any]:
    return {"type": "error", "code": "line_too_long", "max": LINE_MAX}


# JSON numbers the office stores. A bool is an int in Python and is not one of these.
_OFFICE_INT_MAX = 2**53 - 1


def bounded_int(value: Any, *, positive: bool = False) -> int | None:
    """A plain integer in range, or None when the office would drop the key."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or (positive and value < 1) or value > _OFFICE_INT_MAX:
        return None
    return value


# Card 1303: a program, plus one subcommand word. Same pattern the office stores.
_CMD_RE = re.compile(r"[a-z0-9][a-z0-9._+-]{0,31}( [a-z][a-z0-9-]{0,31})?")
_SUBCOMMANDS = frozenset({"git", "gh", "mill", "rco", "pip", "npm", "docker", "uv", "cargo"})
_MODULE_PROGRAMS = frozenset({"python", "python3", "py"})
_ERROR_LABELS = {
    "usage": "usage error",
    "git_fatal": "fatal error",
    "other_nonzero": "nonzero exit",
}


def command_text(value: Any) -> str | None:
    """A command word the office would store, or None."""
    if isinstance(value, str) and _CMD_RE.fullmatch(value):
        return value
    return None


def _program_name(part: str) -> str | None:
    name = part.replace("\\", "/").rsplit("/", 1)[-1]
    if name.casefold().endswith(".exe"):
        name = name[:-4]
    name = name.casefold()
    if command_text(name) == name and " " not in name:
        return name
    return None


def command_word(argv: list) -> str | None:
    """The start-hop command word for one argv, or None when it would not match.

    The program is the basename of argv[0], one trailing exe suffix removed, in
    lower case. python, python3, and py with an immediate -m use the module.
    A second word is added only for the subcommand programs, and only when that
    word is the very next part. A flag stops the word.
    """
    if not argv or not isinstance(argv[0], str) or argv[0] == "":
        return None
    program = _program_name(argv[0])
    if program is None:
        return None
    rest = list(argv[1:])
    if (
        program in _MODULE_PROGRAMS
        and len(rest) >= 2
        and rest[0] == "-m"
        and isinstance(rest[1], str)
    ):
        module = _program_name(rest[1])
        if module is not None:
            program = module
            rest = rest[2:]
    if program in _SUBCOMMANDS and rest and isinstance(rest[0], str):
        word = rest[0].casefold()
        if re.fullmatch(r"[a-z][a-z0-9-]{0,31}", word):
            joined = program + " " + word
            if command_text(joined) == joined:
                return joined
    return program


def wait_for_errors(kind: Any, exit_code: Any) -> bool:
    """True when this hop should wait for the office errors reply."""
    if kind == "crash":
        return True
    if kind != "exit":
        return False
    return isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0


def relay_errors(got: Any) -> dict[str, Any] | None:
    """The errors object from an office reply, slimmed to the keys tw prints."""
    raw = None
    if isinstance(got, dict):
        if isinstance(got.get("errors"), dict):
            raw = got["errors"]
        else:
            result = got.get("result")
            if isinstance(result, dict) and isinstance(result.get("errors"), dict):
                raw = result["errors"]
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    kind = raw.get("kind")
    if isinstance(kind, str) and kind in _ERROR_LABELS:
        out["kind"] = kind
    kept = command_text(raw.get("cmd"))
    if kept is not None:
        out["cmd"] = kept
    for key in ("count", "n", "span_s"):
        val = raw.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and 0 <= val <= _OFFICE_INT_MAX:
            out[key] = val
    nxt = raw.get("next")
    if (
        isinstance(nxt, str)
        and nxt
        and len(nxt) <= 200
        and "\n" not in nxt
        and "\r" not in nxt
        and nxt.isprintable()
    ):
        out["next"] = nxt
    return out or None


def error_lines(errors: Any) -> list[str]:
    """The stderr lines for one errors object. Empty when the count is not above 1."""
    if not isinstance(errors, dict):
        return []
    kind = errors.get("kind")
    label = _ERROR_LABELS.get(kind) if isinstance(kind, str) else None
    count = errors.get("count")
    total = errors.get("n")
    span = errors.get("span_s")
    if label is None:
        return []
    if isinstance(count, bool) or not isinstance(count, int) or count <= 1:
        return []
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        return []
    if isinstance(span, bool) or not isinstance(span, int) or span < 0 or span > _OFFICE_INT_MAX:
        return []
    if span < 86400:
        shown = max(1, round(span / 3600))
        unit = "h"
    else:
        shown = max(1, round(span / 86400))
        unit = "d"
    kept = command_text(errors.get("cmd"))
    head = (kept + " " + label) if kept is not None else label
    lines = [
        "%s: %s of your last %s runs, over the past %s%s"
        % (head, count, total, shown, unit)
    ]
    nxt = errors.get("next")
    if isinstance(nxt, str) and nxt:
        lines.append(nxt)
    return lines


def stop_frame(watch_id: str, reason: str) -> dict[str, Any]:
    return {"type": "stop", "watch_id": watch_id, "reason": reason}
