"""Card 1193: the Wall left-pane scope, shared by every list route the six tabs read.

?desks=d1,d2 narrows rows to the selected desks (omit = no desk filter).
?window=1d|7d|30d cuts rows on each type's own clock (omit = all). 1w is kept as
the tree routes' old name for 7d; it is the same window, not a second value.

The scope is parsed once at the door and applied to the full row list before the
page cut, so ?limit= / ?cursor= page the filtered list. Times are naive office
clock, the same clock every Wall route already emits.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

WINDOW_DAYS = {"1d": 1, "7d": 7, "1w": 7, "30d": 30}
WINDOW_WORDS = "1d|7d|30d"
DESKS_MAX = 100
_DESK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class ScopeError(ValueError):
    """A bad ?desks= or ?window= value. The door answers 400 {"error"}."""


@dataclass(frozen=True)
class WallScope:
    desks: frozenset[str] | None = None  # casefolded desk names; None = every desk
    window: str = ""  # the value as sent, "" = all
    since: datetime | None = None  # window cutoff on the office clock

    @property
    def active(self) -> bool:
        return self.desks is not None or self.since is not None

    def key(self) -> str:
        """Cache-key part. A window key carries the minute so a cached page ages out."""
        desks = ",".join(sorted(self.desks)) if self.desks is not None else ""
        minute = self.since.strftime("%Y%m%d%H%M") if self.since is not None else ""
        return f"desks={desks}|window={self.window}|{minute}"

    def desk_hit(self, *names: Any) -> bool:
        """True when no desk filter is set, or any of names is a selected desk."""
        if self.desks is None:
            return True
        for n in names:
            if isinstance(n, (list, tuple, set, frozenset)):
                if self.desk_hit(*n):
                    return True
                continue
            s = str(n or "").strip().casefold()
            if s and s in self.desks:
                return True
        return False

    def in_window(self, *stamps: Any) -> bool:
        """True when no window is set, or the newest of stamps is inside it."""
        if self.since is None:
            return True
        best = None
        for s in stamps:
            at = as_time(s)
            if at is not None and (best is None or at > best):
                best = at
        return best is not None and best >= self.since


ALL = WallScope()


def as_time(value: Any) -> datetime | None:
    """A datetime or an office-clock string (19-char or iso6) as a naive datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        at = datetime.fromisoformat(str(value).strip().replace("T", " "))
    except ValueError:
        return None
    return at.replace(tzinfo=None) if at.tzinfo else at


def parse_window(raw: str | None, *, now: datetime | None = None) -> tuple[str, datetime | None]:
    key = str(raw or "").strip().lower()
    if not key:
        return "", None
    if key not in WINDOW_DAYS:
        raise ScopeError(f"window= is {WINDOW_WORDS} (or omit for all)")
    n = now if now is not None else datetime.now()
    return key, n - timedelta(days=WINDOW_DAYS[key])


def parse_desks(raws: Iterable[str] | None) -> frozenset[str] | None:
    names: list[str] = []
    seen = False
    for raw in raws or []:
        seen = True
        names.extend(x.strip() for x in str(raw or "").split(",") if x.strip())
    if not seen:
        return None
    if not names:
        raise ScopeError("desks= is a comma list of desk names (omit for every desk)")
    if len(names) > DESKS_MAX or any(not _DESK.fullmatch(n) for n in names):
        raise ScopeError(f"desks= is up to {DESKS_MAX} desk names, comma separated")
    return frozenset(n.casefold() for n in names)


def parse_scope(qs: dict[str, list[str]] | None, *, now: datetime | None = None) -> WallScope:
    """?desks= and ?window= from a parsed query string. Raises ScopeError."""
    qs = qs or {}
    desks = parse_desks(qs.get("desks")) if "desks" in qs else None
    window, since = parse_window((qs.get("window") or [""])[0], now=now)
    return WallScope(desks=desks, window=window, since=since)


def project_list(qs: dict[str, list[str]] | None, *keys: str) -> list[str]:
    """?project= / ?projects= as one comma list, order kept, no repeats."""
    out: list[str] = []
    for key in keys or ("project", "projects"):
        for raw in (qs or {}).get(key) or []:
            for x in str(raw or "").split(","):
                x = x.strip()
                if x and x not in out:
                    out.append(x)
    return out
