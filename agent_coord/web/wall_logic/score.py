"""Scorecards glance pure rules - SoR for acceptance-locked behavior (pack-callable).

SoR: `agent_coord.web.wall_logic.score` (this module) is the **single source of truth** for
score pure decision rules used by the default Wall pack:

- scoreDeskRows aggregation (hot = miss | missing Last | stale publish)
- Needs attention filter vs in-window pass (ACCEPTANCE-SCORECARDS-GLANCE)
- Desk table fallback when Needs is empty but desks still have KPIs (SCORE_BOOT_FIX)
- Pulse strip counts (KPIs / Desks / tokens / cmds / waiting / stale / trend) even when Needs empty
- ensureScorePaint cold-load / tab-enter contract flags (pure; no DOM)

Default pack paint still lives in `agent_coord/wall_ui/default/board.html`.
**board.html must call-equivalent** these helpers (same semantics; camelCase mirrors).
Do not fork hot / Needs / pulse / fallback rules in chrome without updating this
module + `tests/wall`.

See wall-contract; tests/wall score suites.
"""

from __future__ import annotations

import re
import time
from typing import Any, Mapping, Sequence

# Marker for board.html / pack authors (searchable). Path A: Python SoR;
# board remains call-equivalent paint (no mega rewrite this cut).
BOARD_EQUIVALENT_MARKER = "WALL_LOGIC_SCORE_SOR"


def numish(s: Any) -> float | None:
    t = str(s or "").replace("*", "").strip()
    if re.match(r"^(not run|leftover|pass|stay|shipped|none|-)$", t, re.I):
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def kpi_miss(last: Any, target: Any) -> bool:
    L = str(last or "").lower()
    if not L or re.search(r"not run|leftover|shipped|stay|none", L):
        return False
    if re.search(r"\bfail\b|\bstarve\b|\bmiss\b", L):
        return True
    # Informational KPIs (empty/blank target, e.g. mill-office.activities): never red on numeric Last.
    T = str("" if target is None else target).strip()
    if not T:
        return False
    ln, tn = numish(last), numish(target)
    if ln is None or tn is None:
        return False
    if tn == 0:
        return ln != 0
    return ln < tn


def score_parse_at(at: Any) -> float | None:
    if not at:
        return None
    s = str(at).replace(" ", "T")
    try:
        from datetime import datetime, timezone

        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() * 1000.0
    except Exception:
        return None


def score_window_ms(span: str = "24h") -> int:
    if span == "7d":
        return 7 * 24 * 3600 * 1000
    return 24 * 3600 * 1000


def score_in_window(at: Any, span: str = "24h", now_ms: float | None = None) -> bool:
    t = score_parse_at(at)
    if t is None:
        return False
    now = time.time() * 1000.0 if now_ms is None else float(now_ms)
    return (now - t) <= score_window_ms(span)


def score_source_job(note: Any, kpi: Any = "") -> str:
    """Extract JOB id from kpi note (board scoreDeskRows sourceJob)."""
    m = re.search(r"JOB[:\s]+([^\s;]+)", str(note or ""), re.I)
    if m:
        return m.group(1)
    return str(kpi or "")


def score_desk_rows(
    d: Mapping[str, Any] | None,
    *,
    span: str = "24h",
    now_ms: float | None = None,
) -> list[dict[str, Any]]:
    """Aggregate agent_kpi into per-desk rows; hot = miss|missing|stale.

    Mirrors board `scoreDeskRows` (SCORECARDS_GLANCE).
    """
    d = d or {}
    by: dict[str, dict[str, Any]] = {}
    for k in d.get("kpis") or []:
        desk = str(k.get("owner") or k.get("project_id") or "").strip() or "(unknown)"
        if desk not in by:
            by[desk] = {
                "desk": desk,
                "kpis": [],
                "miss": 0,
                "missing": 0,
                "stale": 0,
                "latest": None,
            }
        by[desk]["kpis"].append(k)
        last = k.get("value")
        tgt = k.get("target")
        if last is None or last == "":
            by[desk]["missing"] += 1
        elif kpi_miss(last, tgt):
            by[desk]["miss"] += 1
        ut = score_parse_at(k.get("updated_at"))
        if ut is not None and (by[desk]["latest"] is None or ut > by[desk]["latest"]):
            by[desk]["latest"] = ut

    now = time.time() * 1000.0 if now_ms is None else float(now_ms)
    stale_cut = score_window_ms(span)
    for desk, row in by.items():
        if row["latest"] is None or (now - row["latest"]) > stale_cut:
            row["stale"] += 1
        row["hot"] = (row["miss"] > 0) or (row["missing"] > 0) or (row["stale"] > 0)
        reasons: list[str] = []
        if row["miss"]:
            reasons.append(f"{row['miss']} over Target")
        if row["missing"]:
            reasons.append(f"{row['missing']} missing Last")
        if row["stale"]:
            reasons.append("stale publish")
        row["reasons"] = reasons
        primary = next((k for k in row["kpis"] if kpi_miss(k.get("value"), k.get("target"))), None)
        if primary is None:
            primary = row["kpis"][0] if row["kpis"] else {}
        row["last"] = "" if primary.get("value") is None else primary.get("value")
        row["target"] = "" if primary.get("target") is None else primary.get("target")
        row["kpi"] = primary.get("kpi") or ""
        row["project_id"] = primary.get("project_id") or ""
        row["note"] = primary.get("note") or ""
        row["published"] = primary.get("updated_at") or ""
        row["sourceJob"] = score_source_job(primary.get("note"), primary.get("kpi") or "")
    return [by[k] for k in sorted(by.keys())]


def score_hot_list(
    rows: Sequence[Mapping[str, Any]] | None,
    filter_mode: str = "needs",
) -> list[Mapping[str, Any]]:
    """Hot / Needs attention short list (paintScoreHot) - **no** desk-table fallback.

    filter_mode=all -> all rows; needs -> hot only (may be empty while KPIs exist).
    """
    rows = list(rows or [])
    if filter_mode == "all":
        return rows
    return [r for r in rows if r.get("hot")]


def score_desk_table_list(
    rows: Sequence[Mapping[str, Any]] | None,
    filter_mode: str = "needs",
) -> tuple[list[Mapping[str, Any]], bool]:
    """Needs filter + KPI fallback when all in-window pass (SCORE_BOOT_FIX).

    Returns (list, fell_back). Hot list (score_hot_list) does **not** use this
    fallback - only the desk table peer pane.
    """
    rows = list(rows or [])
    if filter_mode == "all":
        return rows, False
    hot = [r for r in rows if r.get("hot")]
    if not hot and rows:
        return rows, True
    return hot, False


def score_delta(row: Mapping[str, Any] | None) -> str:
    """Desk-table Delta cell: miss count, missing Last '?', or middle-dot."""
    if not row:
        return "|"
    if row.get("miss"):
        return "-" + str(row["miss"])
    if row.get("missing"):
        return "?"
    return "|"


def score_prefer_desk(
    rows: Sequence[Mapping[str, Any]] | None,
    selected: str | None = "",
) -> str:
    """Autoselect desk for detail: keep selected if present; else first hot else first."""
    rows = list(rows or [])
    sel = str(selected or "").strip()
    if sel and any(str(r.get("desk") or "") == sel for r in rows):
        return sel
    if not rows:
        return ""
    prefer = next((r for r in rows if r.get("hot")), rows[0])
    return str(prefer.get("desk") or "").strip()


def score_spend_pulse(
    d: Mapping[str, Any] | None,
    span: str = "24h",
    now_ms: float | None = None,
) -> dict[str, Any]:
    """SCORECARDS_TOKEN_DETAIL + TOKENS_EST: exact LLM tokens vs tokens_est vs mill bytes.

    Never coerce mill bytes_out into tokens. Exact ``tokens`` wins over ``tokens_est``.
    """
    d = d or {}
    now = time.time() * 1000.0 if now_ms is None else float(now_ms)
    lines = d.get("spend_lines") or []
    if not lines:
        lines = d.get("spend") or []
    exact: float | None = None
    est: float | None = None
    mill_bytes = 0.0
    mill_rows = 0
    cmds = 0
    llm_rows = 0
    for r in lines:
        at = r.get("at") or ""
        if at and not score_in_window(at, span, now):
            continue
        src = str(r.get("source") or "mill")
        if src == "mill":
            mill_rows += 1
            try:
                mill_bytes += float(r.get("bytes_out") or r.get("bytes") or 0)
            except (TypeError, ValueError):
                pass
            if r.get("cmds"):
                try:
                    cmds += int(r.get("cmds") or 0)
                except (TypeError, ValueError):
                    pass
            else:
                cmds += 1
            continue
        llm_rows += 1
        cmds += 1
        tok_raw = r.get("tokens")
        if tok_raw is not None and tok_raw != "":
            try:
                tok = float(tok_raw)
            except (TypeError, ValueError):
                tok = None
            if tok is not None:
                if exact is None:
                    exact = 0.0
                exact += tok
                continue
        est_raw = r.get("tokens_est")
        if est_raw is not None and est_raw != "":
            try:
                e = float(est_raw)
            except (TypeError, ValueError):
                e = None
            if e is not None:
                if est is None:
                    est = 0.0
                est += e
    # Fallback aggregates without at (board-compatible): non-mill only for LLM
    if exact is None and est is None and (d.get("spend") or []):
        for r in d.get("spend") or []:
            src = str(r.get("source") or "")
            if src == "mill":
                continue
            tok_raw = r.get("tokens")
            if tok_raw is not None and tok_raw != "":
                try:
                    if exact is None:
                        exact = 0.0
                    exact += float(tok_raw)
                except (TypeError, ValueError):
                    pass
            else:
                est_raw = r.get("tokens_est")
                if est_raw is not None and est_raw != "":
                    try:
                        if est is None:
                            est = 0.0
                        est += float(est_raw)
                    except (TypeError, ValueError):
                        pass
            try:
                cmds += int(r.get("cmds") or 0)
            except (TypeError, ValueError):
                pass
    return {
        "tokens": exact,
        "tokens_est": est,
        "millBytes": mill_bytes if mill_rows else None,
        "millRows": mill_rows,
        "cmds": cmds,
        "llmRows": llm_rows,
        "exact": exact is not None,
    }


def score_waiting(d: Mapping[str, Any] | None) -> int:
    d = d or {}
    n = 0
    for a in d.get("agents") or d.get("live_agents") or []:
        if a and a.get("waiting_on"):
            n += 1
    return n


def score_trend(rows: Sequence[Mapping[str, Any]] | None) -> dict[str, str]:
    rows = list(rows or [])
    hot = sum(1 for r in rows if r.get("hot"))
    total = len(rows) or 1
    if not rows:
        return {"word": "flat", "cls": ""}
    if hot == 0:
        return {"word": "better", "cls": "better"}
    if hot / total >= 0.5:
        return {"word": "worse", "cls": "worse"}
    return {"word": "flat", "cls": ""}


def score_pulse_counts(
    d: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]] | None,
    *,
    span: str = "24h",
    now_ms: float | None = None,
) -> dict[str, Any]:
    """Pulse strip numbers - always from kpis/rows even when Needs is empty."""
    d = d or {}
    rows = list(rows or [])
    sp = score_spend_pulse(d, span, now_ms)
    stale_n = sum(1 for r in rows if r.get("stale"))
    tok = sp.get("tokens")
    if tok is None and sp.get("tokens_est") is not None:
        tok = sp["tokens_est"]
    return {
        "kpi_n": len(d.get("kpis") or []),
        "desk_n": len(rows),
        "tokens": tok,  # None when no LLM - never fake 0 (WALL_HONEST_EMPTY_VS_DOWN)
        "tokens_est": sp.get("tokens_est"),
        "millBytes": sp.get("millBytes"),  # None when no mill rows
        "millRows": sp.get("millRows", 0),
        "exact": bool(sp.get("exact")),
        "cmds": sp["cmds"],
        "waiting": score_waiting(d),
        "stale_n": stale_n,
        "trend": score_trend(rows),
    }


def score_ensure_paint_contract() -> dict[str, Any]:
    """Cold-load / tab-enter paint contract flags (SCORE_BOOT_FIX) - pure, no DOM.

    board `ensureScorePaint` must run on `#score` / `#scorecards` enter and when
    Score pane is on during tick. Path A locks the *flags*; paint stays in board.html.
    """
    return {
        "ensure_fn": "ensureScorePaint",
        "tabs": ("score", "scorecards"),
        "hash_aliases": {"scorecards": "score"},
        "default_filter": "needs",
        "default_span": "24h",
        "pulse_always_from_kpis": True,
        "desk_table_fallback_when_needs_empty": True,
        "hot_list_no_fallback": True,
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
    }
