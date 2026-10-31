"""Wall honest empty vs mill API down - pure classifiers (Path A).

SoR: wall-contract; tests/wall/test_wall_honest_empty_vs_down.py
Parent: ACCEPTANCE-OOTB-UX.md items 4-5; SCORECARDS token-detail honesty.

Paint/render throws are NOT API down. Empty JSON/rows are honest empty.
Fetch/HTTP/unreachable mill = down. Never fake LLM zeros.
"""
from __future__ import annotations

from typing import Any, Mapping

MARKER = "WALL_HONEST_EMPTY_VS_DOWN"

API_DOWN_RECOVERY = (
    "Tell your Mill desk agent to restart the wall "
    "(install wall --apply / restart wall service). Humans do not run schtasks."
)

EMPTY_MESSAGES = {
    "session": "No desks are here. Ask your agent to join.",
    "score_kpi": "Honest empty - no agent_kpi yet.",
    "score_progress": "Honest empty - no desks/needs/spend yet.",
    "score_bottlenecks": "None - no waiting_on / stalled JOBs.",
    "mail": "no mail for this filter (floor-only or empty)",
    "floor": "Honest empty - no floor glance yet.",
    "spend": "no spend yet",
}


def classify_fetch(
    *,
    ok: bool | None = None,
    status: int | None = None,
    content_type: str | None = None,
    network_error: bool = False,
    body: Any = None,
) -> str:
    """Classify transport outcome: 'down' | 'ok'.

    Empty / null JSON body with HTTP 200+json is still 'ok' (honest empty upstream).
    """
    if network_error:
        return "down"
    if ok is False:
        return "down"
    if status is not None and int(status) >= 400:
        return "down"
    if status is not None and int(status) > 0 and int(status) < 200:
        return "down"
    ct = (content_type or "").lower()
    if status is not None and int(status) >= 200 and int(status) < 300:
        if ct and "json" not in ct:
            return "down"
        return "ok"
    if ok is True:
        return "ok"
    if ok is None and status is None and not network_error:
        return "ok"
    return "down"


def classify_outcome(
    *,
    fetch: str | None = None,
    paint_error: bool = False,
    payload: Any = None,
) -> str:
    """Top-level wall outcome: 'down' | 'empty' | 'ok' | 'paint_error'.

    paint_error never upgrades to down. Empty agents/kpis/mail != down.
    """
    if fetch == "down":
        return "down"
    if paint_error:
        return "paint_error"
    if payload is None:
        return "empty"
    if isinstance(payload, Mapping):
        agents = payload.get("agents") or payload.get("live_agents") or []
        live = [a for a in agents if a and a.get("alive")]
        kpis = payload.get("kpis") or []
        mailbox = payload.get("mailbox")
        needs = payload.get("needs") or []
        if not live and not kpis and (mailbox == [] or mailbox is None) and not needs:
            return "empty"
        if not live and not kpis:
            return "empty"
        return "ok"
    if payload == {} or payload == []:
        return "empty"
    return "ok"


def honest_llm_display(tokens: Any = None, tokens_est: Any = None) -> str:
    """LLM pulse cell: exact wins; else est; else em-dash (never fake 0)."""
    if tokens is not None and tokens != "":
        try:
            f = float(tokens)
            return str(int(f) if f == int(f) else f)
        except (TypeError, ValueError):
            pass
    if tokens_est is not None and tokens_est != "":
        try:
            f = float(tokens_est)
            return str(int(f) if f == int(f) else f)
        except (TypeError, ValueError):
            pass
    return "\u2014"


def honest_mill_bytes_display(mill_bytes: Any = None, mill_rows: int = 0) -> str:
    """Mill bytes: real 0 only when mill rows exist; else em-dash."""
    if not mill_rows:
        return "\u2014"
    if mill_bytes is None or mill_bytes == "":
        return "\u2014"
    try:
        v = float(mill_bytes)
        return str(int(v) if v == int(v) else v)
    except (TypeError, ValueError):
        return "\u2014"


def sum_llm_tokens(rows: list[Mapping[str, Any]] | None) -> float | None:
    """Sum non-null LLM tokens; ignore mill; never coerce null to 0."""
    total: float | None = None
    for r in rows or []:
        src = str(r.get("source") or "")
        if src == "mill":
            continue
        tok = r.get("tokens")
        if tok is None or tok == "":
            continue
        try:
            v = float(tok)
        except (TypeError, ValueError):
            continue
        if total is None:
            total = 0.0
        total += v
    return total


def api_down_banner_html() -> str:
    return (
        "<b>mill API down.</b> Last-good wall kept if any \u2014 do not treat this as an empty office. "
        '<span style="color:var(--ink)">Recovery:</span> ' + API_DOWN_RECOVERY
    )


def honest_contract() -> dict[str, Any]:
    return {
        "marker": MARKER,
        "path": "A",
        "fetch_down_only": True,
        "paint_throw_not_down": True,
        "empty_not_down": True,
        "llm_empty_is_dash": True,
        "no_fake_zeros": True,
        "last_good_ok": True,
        "empty_messages": dict(EMPTY_MESSAGES),
        "recovery": API_DOWN_RECOVERY,
    }
