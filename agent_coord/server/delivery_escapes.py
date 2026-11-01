"""Card 955: delivery KPI escapes guard (no new schema).

Escapes = Validator Fails + post-release reverts per shipped card. These are
pack/ship process events (like open-PRs / release scores), not a mill
activity.type. Counts come from EscapeSample rows (fixtures in tests;
production may inject via set_live_fetch). Never log tokens, hosts, or emails.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

KINDS = frozenset({"validator_fail", "revert"})


@dataclass(frozen=True)
class EscapeSample:
    kind: str  # validator_fail | revert
    card_id: int = 0


def samples_from_payload(rows: Iterable[dict[str, Any]]) -> list[EscapeSample]:
    out: list[EscapeSample] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip()
        if kind not in KINDS:
            continue
        try:
            card_id = int(raw.get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
        out.append(EscapeSample(kind=kind, card_id=card_id))
    return out


def escapes_view(
    samples: Iterable[EscapeSample] | None,
    *,
    shipped: int,
) -> dict[str, Any] | None:
    """Escapes summary. Empty omitted (card 1019). per_shipped uses shipped count."""
    rows = list(samples or [])
    if not rows:
        return None
    fail_n = sum(1 for s in rows if s.kind == "validator_fail")
    revert_n = sum(1 for s in rows if s.kind == "revert")
    n = fail_n + revert_n
    if n <= 0:
        return None
    ship = max(0, int(shipped))
    per = (float(n) / float(ship)) if ship > 0 else None
    return {
        "n": n,
        "validator_fail_n": fail_n,
        "revert_n": revert_n,
        "per_shipped": per,
        "unit": "count",
    }


_Fetch = Callable[[], list[EscapeSample]]
_live_fetch: _Fetch | None = None


def set_live_fetch(fn: _Fetch | None) -> None:
    global _live_fetch
    _live_fetch = fn


def escapes_view_live(*, shipped: int) -> dict[str, Any] | None:
    samples: list[EscapeSample] = []
    if _live_fetch is not None:
        try:
            samples = list(_live_fetch() or [])
        except Exception:
            samples = []
    return escapes_view(samples, shipped=shipped)
