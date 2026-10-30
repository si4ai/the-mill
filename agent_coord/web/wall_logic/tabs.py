"""showTab / ensure*Paint contract as pure flags - SoR (default pack Path A).

SoR: `agent_coord.web.wall_logic.tabs` (this module) is the **single source of truth** for
tab normalize / hash aliases / ensure*Paint *which-hook* contracts used by the
default Wall pack:

- showTab aliases (plan/backlog/board/issues -> pane-backlog; scorecards -> score;
  stations -> jobs+stations view; floor/mail/score cold-load paint hooks)
- ensureFloorPaint / ensureMailPaint / ensureScorePaint contract flags (pure; no DOM)
- DEFAULT_MAIN_TABS order lock (WALL-UI-LOCK) - Admin stays top chrome, not main-tab peer

Default pack paint still lives in `agent_coord/wall_ui/default/board.html`.
**board.html must call-equivalent** these helpers (same semantics; camelCase mirrors).
Do not fork alias / ensure* paint *contracts* in chrome without updating this
module + `tests/wall`.

See wall-contract; tests/wall tabs/knobs.
"""

from __future__ import annotations

from typing import Any

# Marker for board.html / pack authors (searchable). Path A: Python SoR;
# board remains call-equivalent paint (no mega rewrite this cut).
BOARD_EQUIVALENT_MARKER = "WALL_LOGIC_TABS_SOR"

# Plan aliases -> pane-backlog; nav highlight stays "plan"
PLAN_ALIASES = frozenset({"plan", "backlog", "board", "issues"})

# Score alias: #scorecards -> score pane (SCORE_BOOT_FIX)
SCORE_ALIASES = frozenset({"score", "scorecards"})

# Hash names board accepts into showTab (cold load + hashchange)
HASH_SHOW_TAB = frozenset({
    "session", "jobs", "plan", "backlog", "board", "issues",
    "mail", "wire", "stations", "score", "scorecards", "guide", "admin", "floor",
})

# Tab name (after alias normalize of plan family) -> ensure* paint hook
ENSURE_PAINT = {
    "floor": "ensureFloorPaint",
    "mail": "ensureMailPaint",
    "score": "ensureScorePaint",
    "scorecards": "ensureScorePaint",
}

# Main nav order lock (WALL-UI-LOCK) - default pack chrome; offices may tweak live later
DEFAULT_MAIN_TABS = ("session", "floor", "jobs", "score", "mail", "plan")


def normalize_tab(name: str | None) -> dict[str, Any]:
    """Return pane id stem, nav highlight, and plan alias if any."""
    raw = str(name or "").strip().lower()
    if raw == "stations":
        return {
            "raw": raw,
            "pane": "jobs",
            "nav": "jobs",
            "jobs_view": "stations",
            "plan_alias": None,
            "hash": "stations",
        }
    if raw in PLAN_ALIASES:
        return {
            "raw": raw,
            "pane": "backlog",
            "nav": "plan",
            "jobs_view": None,
            "plan_alias": raw,
            "hash": "plan" if raw == "plan" else raw,
        }
    if raw == "scorecards":
        return {
            "raw": raw,
            "pane": "score",
            "nav": "score",
            "jobs_view": None,
            "plan_alias": None,
            "hash": "scorecards",
        }
    return {
        "raw": raw,
        "pane": raw,
        "nav": raw,
        "jobs_view": "needs" if raw == "jobs" else None,
        "plan_alias": None,
        "hash": raw,
    }


def ensure_paint_for_tab(name: str | None) -> str | None:
    """Which ensure*Paint must run on tab enter (cold load contract)."""
    info = normalize_tab(name)
    return ENSURE_PAINT.get(info["raw"]) or ENSURE_PAINT.get(info["pane"])


def ensure_floor_paint_contract() -> dict[str, Any]:
    """Cold-load / tab-enter Floor paint contract flags (FLOOR_DEFAULT_MAP) - pure."""
    return {
        "ensure_fn": "ensureFloorPaint",
        "tabs": ("floor",),
        "hash_aliases": {},
        "repaint_on_show": True,
        "raf_second_paint": True,
        "load_glance_if_empty": True,
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
    }


def ensure_mail_paint_contract() -> dict[str, Any]:
    """Cold-load / tab-enter Mail paint contract flags (MAIL_BOOT_FIX) - pure."""
    return {
        "ensure_fn": "ensureMailPaint",
        "tabs": ("mail",),
        "hash_aliases": {},
        "repaint_on_show": True,
        "raf_second_paint": True,
        "default_view": "list",
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
    }


def ensure_score_paint_contract_flags() -> dict[str, Any]:
    """Score ensure* flags mirrored here for showTab SoR (full score SoR in score.py)."""
    return {
        "ensure_fn": "ensureScorePaint",
        "tabs": ("score", "scorecards"),
        "hash_aliases": {"scorecards": "score"},
        "repaint_on_show": True,
        "raf_second_paint": True,
        "default_filter": "needs",
        "default_span": "24h",
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
    }


def ensure_paint_contracts() -> dict[str, dict[str, Any]]:
    """All ensure*Paint contracts keyed by ensure_fn (Path A flag surface)."""
    return {
        "ensureFloorPaint": ensure_floor_paint_contract(),
        "ensureMailPaint": ensure_mail_paint_contract(),
        "ensureScorePaint": ensure_score_paint_contract_flags(),
    }


def show_tab_contract(name: str | None) -> dict[str, Any]:
    """Pure showTab outcome flags - no DOM."""
    info = normalize_tab(name)
    ensure = ensure_paint_for_tab(name)
    return {
        **info,
        "ensure_paint": ensure,
        "admin_is_main_tab": False,  # Admin lives in top chrome, not main-tab peer
        "hash_accepted": info["raw"] in HASH_SHOW_TAB or info["pane"] in HASH_SHOW_TAB,
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
    }


def show_tab_alias_map() -> dict[str, dict[str, Any]]:
    """Canonical alias -> normalize outcome for Acceptance / pack authors."""
    names = sorted(HASH_SHOW_TAB | PLAN_ALIASES | SCORE_ALIASES | {"stations"})
    return {n: show_tab_contract(n) for n in names}
