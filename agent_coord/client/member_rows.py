"""mill member --all text rows (card 1204)."""
from __future__ import annotations

from typing import Any


def applies(args: Any) -> bool:
    """Text form of mill member --all, unless --json or --raw."""
    return (
        str(getattr(args, "cmd", "") or "") == "member"
        and bool(getattr(args, "all", False))
        and not bool(getattr(args, "as_json", False))
        and not bool(getattr(args, "raw", False))
    )


def render(rows: list[dict[str, Any]] | None) -> str:
    """Align roster name and member count, one roster per line."""
    items: list[tuple[str, int]] = []
    for rec in rows or []:
        name = str(rec.get("name") or "").strip()
        if not name:
            continue
        try:
            n = int(rec.get("desks") or 0)
        except (TypeError, ValueError):
            n = 0
        items.append((name, n))
    if not items:
        return ""
    width = max(len(name) for name, _ in items)
    return "\n".join(f"{name:<{width}}  {n}" for name, n in items) + "\n"
