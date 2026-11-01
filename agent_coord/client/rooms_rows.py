"""mill rooms short rows + paging (card 958); digest shaping (card 975)."""
from __future__ import annotations

from typing import Any

ROOMS_PAGE = 50

_SHORT_KEYS = (
    "tree",
    "root_id",
    "size",
    "depth",
    "breadth",
    "last_at",
    "starter",
    "root",
    "members",
)

_DIGEST_KEYS = (
    "tree",
    "root_id",
    "size",
    "breadth",
    "created",
    "last_at",
    "starter",
    "root",
    "tags",
)


def applies(args: Any) -> bool:
    if str(getattr(args, "cmd", "") or "") != "rooms":
        return False
    if bool(getattr(args, "full", False)) or bool(getattr(args, "raw", False)):
        return False
    if bool(getattr(args, "digest", False)):
        # Digest returns every named room in one shot; no short-row paging.
        return False
    return True


def digest_applies(args: Any) -> bool:
    return (
        str(getattr(args, "cmd", "") or "") == "rooms"
        and bool(getattr(args, "digest", False))
        and not bool(getattr(args, "raw", False))
    )


def digest_short(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        item = {k: r.get(k) for k in _DIGEST_KEYS if k in r}
        if "tags" not in item:
            item["tags"] = []
        out.append(item)
    return out


def cut(rows: list[dict[str, Any]], page: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    n = int(page or 0) or 1
    of = max(1, -(-len(rows) // ROOMS_PAGE))
    if n > of:
        n = of
    part = rows[(n - 1) * ROOMS_PAGE : n * ROOMS_PAGE]
    block: dict[str, Any] = {"n": n, "of": of, "size": ROOMS_PAGE, "rooms": len(rows)}
    if n < of:
        block["next"] = f"--page {n + 1}"
    block["full"] = "short rows; --full prints every field of every room"
    return part, block


def short(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({k: r.get(k) for k in _SHORT_KEYS if k in r})
    return out
