"""Card 1029: release pipeline score (no new schema / activity type).

Release ship stages (consensus -> GOs -> tag -> PyPI -> installed live) are a
pack/ship process, not a mill activity.type (parallel to open-PRs / card 983).
Scores come from structured ReleaseSample rows (fixtures in tests; production
may inject via set_live_fetch). Durable transition rows would need activity.type
ENUM + edges ALTER - that is a separate schema proposal, not this land.

Never log or return tokens, PATs, hosts, or emails.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

KPI_RELEASE_N = "release.release_n"
KPI_CONSENSUS_TO_GOS = "release.consensus_to_gos_ms"
KPI_GOS_TO_TAG = "release.gos_to_tag_ms"
KPI_TAG_TO_PYPI = "release.tag_to_pypi_ms"
KPI_PYPI_TO_LIVE = "release.pypi_to_live_ms"
KPI_CONSENSUS_TO_LIVE = "release.consensus_to_live_ms"

SCORE_NAMES = {
    KPI_RELEASE_N,
    KPI_CONSENSUS_TO_GOS,
    KPI_GOS_TO_TAG,
    KPI_TAG_TO_PYPI,
    KPI_PYPI_TO_LIVE,
    KPI_CONSENSUS_TO_LIVE,
    "release-n",
    "release-consensus-to-gos",
    "release-gos-to-tag",
    "release-tag-to-pypi",
    "release-pypi-to-live",
    "release-consensus-to-live",
}


@dataclass(frozen=True)
class ReleaseSample:
    version: str
    consensus_at: datetime | None
    gos_at: datetime | None = None
    tagged_at: datetime | None = None
    pypi_at: datetime | None = None
    live_at: datetime | None = None


def _parse_iso(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        text = str(raw).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def samples_from_payload(rows: Iterable[dict[str, Any]]) -> list[ReleaseSample]:
    """Map release JSON to ReleaseSample. Keeps version + stage stamps only."""
    out: list[ReleaseSample] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        version = str(raw.get("version") or "").strip()
        if not version:
            continue
        # never carry token/host/email fields into the sample
        out.append(
            ReleaseSample(
                version=version[:32],
                consensus_at=_parse_iso(raw.get("consensus_at")),
                gos_at=_parse_iso(raw.get("gos_at")),
                tagged_at=_parse_iso(raw.get("tagged_at")),
                pypi_at=_parse_iso(raw.get("pypi_at")),
                live_at=_parse_iso(raw.get("live_at")),
            )
        )
    return out


def _ms(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    try:
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return max(0.0, (b - a).total_seconds() * 1000.0)
    except Exception:
        return None


def _summary(vals: list[float]) -> dict[str, Any] | None:
    if not vals:
        return None
    vals = sorted(float(v) for v in vals)
    return {
        "n": len(vals),
        "median": int(statistics.median(vals)),
        "worst": int(vals[-1]),
        "unit": "ms",
    }


def _count(n: int) -> dict[str, Any]:
    return {"n": int(n), "unit": "count"}


def score_view_from_samples(samples: Iterable[ReleaseSample]) -> dict[str, Any]:
    """Medians/worst for release stage gates. Empty series omitted (card 1019)."""
    consensus_to_gos: list[float] = []
    gos_to_tag: list[float] = []
    tag_to_pypi: list[float] = []
    pypi_to_live: list[float] = []
    consensus_to_live: list[float] = []
    n = 0

    for s in samples or []:
        n += 1
        ms = _ms(s.consensus_at, s.gos_at)
        if ms is not None:
            consensus_to_gos.append(ms)
        ms = _ms(s.gos_at, s.tagged_at)
        if ms is not None:
            gos_to_tag.append(ms)
        ms = _ms(s.tagged_at, s.pypi_at)
        if ms is not None:
            tag_to_pypi.append(ms)
        ms = _ms(s.pypi_at, s.live_at)
        if ms is not None:
            pypi_to_live.append(ms)
        ms = _ms(s.consensus_at, s.live_at)
        if ms is not None:
            consensus_to_live.append(ms)

    out: dict[str, Any] = {"unit": "release"}
    if n:
        out["release_n"] = _count(n)
    for key, vals in (
        ("consensus_to_gos_ms", consensus_to_gos),
        ("gos_to_tag_ms", gos_to_tag),
        ("tag_to_pypi_ms", tag_to_pypi),
        ("pypi_to_live_ms", pypi_to_live),
        ("consensus_to_live_ms", consensus_to_live),
    ):
        summary = _summary(vals)
        if summary is not None:
            out[key] = summary
    return out


_NAME_MAP = {
    KPI_RELEASE_N: "release_n",
    "release-n": "release_n",
    KPI_CONSENSUS_TO_GOS: "consensus_to_gos_ms",
    "release-consensus-to-gos": "consensus_to_gos_ms",
    KPI_GOS_TO_TAG: "gos_to_tag_ms",
    "release-gos-to-tag": "gos_to_tag_ms",
    KPI_TAG_TO_PYPI: "tag_to_pypi_ms",
    "release-tag-to-pypi": "tag_to_pypi_ms",
    KPI_PYPI_TO_LIVE: "pypi_to_live_ms",
    "release-pypi-to-live": "pypi_to_live_ms",
    KPI_CONSENSUS_TO_LIVE: "consensus_to_live_ms",
    "release-consensus-to-live": "consensus_to_live_ms",
}


def score_view_for_name_from_samples(
    samples: Iterable[ReleaseSample],
    name: str,
) -> dict[str, Any]:
    view = score_view_from_samples(samples)
    key = _NAME_MAP.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    return {"score": name, **part}


_Fetch = Callable[[], list[ReleaseSample]]
_live_fetch: _Fetch | None = None


def set_live_fetch(fn: _Fetch | None) -> None:
    global _live_fetch
    _live_fetch = fn


def score_view() -> dict[str, Any]:
    samples: list[ReleaseSample] = []
    if _live_fetch is not None:
        try:
            samples = list(_live_fetch() or [])
        except Exception:
            samples = []
    return score_view_from_samples(samples)


def score_view_for_name(name: str) -> dict[str, Any]:
    samples: list[ReleaseSample] = []
    if _live_fetch is not None:
        try:
            samples = list(_live_fetch() or [])
        except Exception:
            samples = []
    return score_view_for_name_from_samples(samples, name)
