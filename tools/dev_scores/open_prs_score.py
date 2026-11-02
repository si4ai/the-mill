"""Card 983: open-PRs queue score (no new schema / activity type).

PR lifecycle is not a mill activity.type (see state-instrumentation.md).
Scores are derived from structured PR samples (GitHub via the safe gh path
in production; fixtures in tests) plus optional Validator Pass stamps from
card 961 (pass-step-timing). Never log or return tokens, PATs, or hosts.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

KPI_OPEN_N = "pr.open_n"
KPI_RED_N = "pr.red_n"
KPI_OPEN_AGE = "pr.open_age_ms"
KPI_TO_GREEN = "pr.open_to_green_ci_ms"
KPI_TO_PASS = "pr.open_to_validator_pass_ms"
KPI_TO_MERGE = "pr.open_to_merge_ms"
KPI_CI_GATE = "pr.ci_gate_wait_ms"
KPI_VALIDATOR_GATE = "pr.validator_gate_wait_ms"
KPI_MERGE_GATE = "pr.merge_gate_wait_ms"

SCORE_NAMES = {
    KPI_OPEN_N,
    KPI_RED_N,
    KPI_OPEN_AGE,
    KPI_TO_GREEN,
    KPI_TO_PASS,
    KPI_TO_MERGE,
    KPI_CI_GATE,
    KPI_VALIDATOR_GATE,
    KPI_MERGE_GATE,
    "open-prs-open-n",
    "open-prs-red-n",
    "open-prs-open-age",
    "open-prs-open-to-green",
    "open-prs-open-to-pass",
    "open-prs-open-to-merge",
    "open-prs-ci-gate",
    "open-prs-validator-gate",
    "open-prs-merge-gate",
}


@dataclass(frozen=True)
class PrSample:
    number: int
    opened_at: datetime | None
    first_green_ci_at: datetime | None = None
    validator_pass_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    red: bool = False
    open: bool = True
    head_sha: str = ""


@dataclass(frozen=True)
class PassStamp:
    """Card 961 hook: Validator Pass moment for a PR head (ids only)."""

    pr_number: int
    head_sha: str
    passed_at: datetime


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


def samples_from_gh(
    pulls: Iterable[dict[str, Any]],
    *,
    checks: dict[int, dict[str, Any]] | None = None,
) -> list[PrSample]:
    """Map gh pull JSON (+ optional check overlay) to PrSample. Drops secrets."""
    checks = checks or {}
    out: list[PrSample] = []
    for raw in pulls or []:
        if not isinstance(raw, dict):
            continue
        try:
            number = int(raw.get("number") or 0)
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        head = raw.get("head") if isinstance(raw.get("head"), dict) else {}
        sha = str(head.get("sha") or "")[:40]
        overlay = checks.get(number) or {}
        merged = _parse_iso(raw.get("merged_at"))
        closed = _parse_iso(raw.get("closed_at"))
        is_open = merged is None and closed is None and bool(raw.get("state", "open") == "open" or raw.get("state") is None)
        if "open" in overlay:
            is_open = bool(overlay["open"])
        out.append(
            PrSample(
                number=number,
                opened_at=_parse_iso(raw.get("created_at") or raw.get("opened_at")),
                first_green_ci_at=_parse_iso(overlay.get("first_green_at")),
                validator_pass_at=_parse_iso(overlay.get("validator_pass_at")),
                merged_at=merged,
                closed_at=closed,
                red=bool(overlay.get("red") or False),
                open=is_open if merged is None else False,
                head_sha=sha,
            )
        )
    return out


def apply_pass_stamps(samples: list[PrSample], stamps: Iterable[PassStamp]) -> list[PrSample]:
    """Overlay 961 Pass stamps onto samples (match pr_number, prefer head_sha)."""
    by_num: dict[int, PassStamp] = {}
    by_sha: dict[str, PassStamp] = {}
    for s in stamps or []:
        by_num[int(s.pr_number)] = s
        if s.head_sha:
            by_sha[str(s.head_sha)] = s
    out: list[PrSample] = []
    for p in samples:
        stamp = None
        if p.head_sha and p.head_sha in by_sha:
            stamp = by_sha[p.head_sha]
        elif p.number in by_num:
            stamp = by_num[p.number]
        if stamp is None or p.validator_pass_at is not None:
            out.append(p)
            continue
        out.append(
            PrSample(
                number=p.number,
                opened_at=p.opened_at,
                first_green_ci_at=p.first_green_ci_at,
                validator_pass_at=stamp.passed_at,
                merged_at=p.merged_at,
                closed_at=p.closed_at,
                red=p.red,
                open=p.open,
                head_sha=p.head_sha,
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


def score_view_from_samples(
    samples: Iterable[PrSample],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Medians/worst for open-PR queue speed. Empty series omitted (card 1019)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    open_n = 0
    red_n = 0
    open_ages: list[float] = []
    to_green: list[float] = []
    to_pass: list[float] = []
    to_merge: list[float] = []
    ci_gate: list[float] = []
    val_gate: list[float] = []
    merge_gate: list[float] = []

    for p in samples or []:
        if p.open:
            open_n += 1
            ms = _ms(p.opened_at, now)
            if ms is not None:
                open_ages.append(ms)
        if p.red:
            red_n += 1
        ms = _ms(p.opened_at, p.first_green_ci_at)
        if ms is not None:
            to_green.append(ms)
            ci_gate.append(ms)
        ms = _ms(p.opened_at, p.validator_pass_at)
        if ms is not None:
            to_pass.append(ms)
        # Validator gate: green CI -> Pass (or open -> Pass when no green stamp)
        ms = _ms(p.first_green_ci_at or p.opened_at, p.validator_pass_at)
        if ms is not None and p.validator_pass_at is not None:
            val_gate.append(ms)
        ms = _ms(p.opened_at, p.merged_at)
        if ms is not None:
            to_merge.append(ms)
        # Merge gate: Pass (or green) -> merge
        start = p.validator_pass_at or p.first_green_ci_at
        ms = _ms(start, p.merged_at)
        if ms is not None and p.merged_at is not None:
            merge_gate.append(ms)

    out: dict[str, Any] = {"unit": "pr"}
    if open_n or red_n or to_green or to_pass or to_merge or open_ages:
        out["open_n"] = _count(open_n)
        out["red_n"] = _count(red_n)
    for key, vals in (
        ("open_age_ms", open_ages),
        ("open_to_green_ci_ms", to_green),
        ("open_to_validator_pass_ms", to_pass),
        ("open_to_merge_ms", to_merge),
        ("ci_gate_wait_ms", ci_gate),
        ("validator_gate_wait_ms", val_gate),
        ("merge_gate_wait_ms", merge_gate),
    ):
        s = _summary(vals)
        if s is not None:
            out[key] = s
    return out


_NAME_MAP = {
    KPI_OPEN_N: "open_n",
    "open-prs-open-n": "open_n",
    KPI_RED_N: "red_n",
    "open-prs-red-n": "red_n",
    KPI_OPEN_AGE: "open_age_ms",
    "open-prs-open-age": "open_age_ms",
    KPI_TO_GREEN: "open_to_green_ci_ms",
    "open-prs-open-to-green": "open_to_green_ci_ms",
    KPI_TO_PASS: "open_to_validator_pass_ms",
    "open-prs-open-to-pass": "open_to_validator_pass_ms",
    KPI_TO_MERGE: "open_to_merge_ms",
    "open-prs-open-to-merge": "open_to_merge_ms",
    KPI_CI_GATE: "ci_gate_wait_ms",
    "open-prs-ci-gate": "ci_gate_wait_ms",
    KPI_VALIDATOR_GATE: "validator_gate_wait_ms",
    "open-prs-validator-gate": "validator_gate_wait_ms",
    KPI_MERGE_GATE: "merge_gate_wait_ms",
    "open-prs-merge-gate": "merge_gate_wait_ms",
}


def score_view_for_name_from_samples(
    samples: Iterable[PrSample],
    name: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    view = score_view_from_samples(samples, now=now)
    key = _NAME_MAP.get(name)
    if not key:
        return {}
    part = view.get(key)
    if part is None:
        return {"score": name, "missing": True}
    return {"score": name, **part}


# Optional live fetch hook (production). Tests inject samples instead.
_Fetch = Callable[[], list[PrSample]]
_live_fetch: _Fetch | None = None
_pass_stamps_fetch: Callable[[], list[PassStamp]] | None = None


def set_live_fetch(fn: _Fetch | None) -> None:
    global _live_fetch
    _live_fetch = fn


def set_pass_stamps_fetch(fn: Callable[[], list[PassStamp]] | None) -> None:
    """961 owner wires Pass stamps here (or tests)."""
    global _pass_stamps_fetch
    _pass_stamps_fetch = fn


def score_view() -> dict[str, Any]:
    samples: list[PrSample] = []
    if _live_fetch is not None:
        try:
            samples = list(_live_fetch() or [])
        except Exception:
            samples = []
    if _pass_stamps_fetch is not None:
        try:
            samples = apply_pass_stamps(samples, _pass_stamps_fetch() or [])
        except Exception:
            pass
    return score_view_from_samples(samples)


def score_view_for_name(name: str) -> dict[str, Any]:
    samples: list[PrSample] = []
    if _live_fetch is not None:
        try:
            samples = list(_live_fetch() or [])
        except Exception:
            samples = []
    if _pass_stamps_fetch is not None:
        try:
            samples = apply_pass_stamps(samples, _pass_stamps_fetch() or [])
        except Exception:
            pass
    return score_view_for_name_from_samples(samples, name)
