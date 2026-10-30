# -*- coding: utf-8 -*-
"""Check one watcher HINT against the hints.md default-by-activity table.

stdin is one frame: {"type","id","hint","detail"}.

Default (no --custom): hint is the table key, detail is cheap JSON
(what, id, when, state, watchers, tree) and does not carry a letter or card body.

--custom TEXT: detail is that watcher.hint recipe. hint stays the table key.

Exit 0 on pass, 1 on fail. One reason on stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

# hints.md "Default by activity"
ACTIVITIES: dict[str, str] = {
    "mail": "MAIL",
    "todo": "TODO",
    "hold": "HOLD",
    "score": "SCORE",
    "doing": "DOING",
    "name": "NAME",
}

CHEAP_KEYS = {"what", "id", "when", "state", "watchers", "tree"}
# Bodies and recipe fields stay off the default push.
LEAK_KEYS = {
    "body",
    "src",
    "dst",
    "need",
    "status",
    "resource",
    "kpi",
    "value",
    "target",
    "password",
    "token",
    "authorization",
}


def check_frame(obj: Mapping[str, Any], custom: str | None = None) -> None:
    if not isinstance(obj, Mapping):
        raise ValueError("frame is not an object")
    typ = str(obj.get("type") or "")
    hint = str(obj.get("hint") or "")
    if typ not in ACTIVITIES:
        raise ValueError(f"type {typ!r} is not in the activity table")
    expect = ACTIVITIES[typ]
    if hint != expect:
        raise ValueError(f"hint {hint!r} != {expect} for type {typ}")
    if hint == "PING" or typ == "heartbeat":
        raise ValueError("PING is not an activity watcher")
    if "id" not in obj or obj.get("id") in (None, ""):
        raise ValueError("frame id missing")
    detail = obj.get("detail")
    if custom is not None:
        if detail != custom:
            raise ValueError(f"custom detail {detail!r} != {custom!r}")
        if isinstance(detail, str) and detail[:1] in "{[":
            raise ValueError("custom watcher.hint must be a recipe, not a body dump")
        return
    if not isinstance(detail, str):
        raise ValueError("default detail is not a string")
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError as e:
        raise ValueError(f"default detail is not JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("default detail is not an object")
    if set(parsed) != CHEAP_KEYS:
        extra = set(parsed) - CHEAP_KEYS
        missing = CHEAP_KEYS - set(parsed)
        raise ValueError(f"default keys extra={sorted(extra)} missing={sorted(missing)}")
    leaked = LEAK_KEYS & set(parsed)
    if leaked:
        raise ValueError(f"default detail leaked {sorted(leaked)}")
    if parsed["what"] != typ:
        raise ValueError(f"what {parsed['what']!r} != {typ}")
    if int(parsed["id"]) != int(obj["id"]):
        raise ValueError(f"detail id {parsed['id']!r} != frame id {obj['id']!r}")
    if typ != "name" and not str(parsed["when"] or "").strip():
        raise ValueError("default detail missing when")
    if not isinstance(parsed["watchers"], int) or parsed["watchers"] < 1:
        raise ValueError(f"watchers {parsed['watchers']!r}")
    tree = parsed["tree"]
    if not isinstance(tree, list) or len(tree) > 3:
        raise ValueError("tree must be a list of at most 3 crumbs")
    for crumb in tree:
        if not isinstance(crumb, dict) or set(crumb) != {"tree", "lft", "rgt"}:
            raise ValueError(f"bad tree crumb {crumb!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate one watcher HINT frame")
    p.add_argument("--custom", default=None, help="expected watcher.hint recipe")
    p.add_argument("--stamp", default="", help="write ok JSON here on pass")
    p.add_argument("--require-tree", action="store_true", help="TODO crumb check (default for type todo)")
    args = p.parse_args(argv)
    raw = sys.stdin.read()
    try:
        obj = json.loads(raw or "{}")
        if args.require_tree and str(obj.get("type") or "") != "todo":
            raise ValueError("--require-tree is for todo")
        check_frame(obj, args.custom)
    except (ValueError, json.JSONDecodeError, TypeError) as e:
        print(f"hint_check: {e}", file=sys.stderr)
        return 1
    if args.stamp:
        Path(args.stamp).write_text(
            json.dumps({"ok": True, "hint": obj.get("hint"), "id": obj.get("id")}, separators=(",", ":")),
            encoding="utf-8",
        )
    print(f"ok hint={obj.get('hint')} id={obj.get('id')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
