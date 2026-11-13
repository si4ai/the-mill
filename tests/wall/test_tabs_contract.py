"""showTab / ensure*Paint pure contract - Path A SoR (WALL_LOGIC_TABS_SOR)."""
from __future__ import annotations

import pytest

from agent_coord.web.wall_logic import (
    ensure_floor_paint_contract,
    ensure_mail_paint_contract,
    ensure_paint_contracts,
    ensure_paint_for_tab,
    ensure_score_paint_contract_flags,
    normalize_tab,
    show_tab_alias_map,
    show_tab_contract,
)
from agent_coord.web.wall_logic.tabs import (
    BOARD_EQUIVALENT_MARKER,
    DEFAULT_MAIN_TABS,
    HASH_SHOW_TAB,
    PLAN_ALIASES,
    SCORE_ALIASES,
)


def test_marker_wall_logic_tabs_sor():
    assert BOARD_EQUIVALENT_MARKER == "WALL_LOGIC_TABS_SOR"
    c = show_tab_contract("floor")
    assert c["marker"] == "WALL_LOGIC_TABS_SOR"
    assert c["pure"] is True
    assert c["path"] == "A"


@pytest.mark.parametrize(
    "name,ensure",
    [
        ("floor", "ensureFloorPaint"),
        ("mail", "ensureMailPaint"),
        ("score", "ensureScorePaint"),
        ("scorecards", "ensureScorePaint"),
        ("priorities", "ensurePrioritiesPaint"),
        ("session", None),
        ("jobs", None),
        ("plan", None),
        ("stations", None),
        ("guide", None),
        ("admin", None),
    ],
)
def test_ensure_paint_contract(name, ensure):
    assert ensure_paint_for_tab(name) == ensure
    sc = show_tab_contract(name)
    assert sc["ensure_paint"] == ensure
    assert sc["admin_is_main_tab"] is False


def test_plan_aliases_and_admin_not_main():
    for alias in ("plan", "backlog", "board", "issues"):
        c = show_tab_contract(alias)
        assert c["pane"] == "backlog"
        assert c["nav"] == "plan"
        assert c["plan_alias"] == alias
        assert c["admin_is_main_tab"] is False
        assert c["ensure_paint"] is None
    assert PLAN_ALIASES == frozenset({"plan", "backlog", "board", "issues"})
    st = normalize_tab("stations")
    assert st["pane"] == "jobs" and st["jobs_view"] == "stations"
    assert st["hash"] == "stations"


def test_score_aliases():
    assert SCORE_ALIASES == frozenset({"score", "scorecards"})
    sc = show_tab_contract("scorecards")
    assert sc["pane"] == "score" and sc["nav"] == "score"
    assert sc["hash"] == "scorecards"
    assert sc["ensure_paint"] == "ensureScorePaint"
    assert show_tab_contract("score")["pane"] == "score"


def test_default_main_tab_order_lock():
    assert DEFAULT_MAIN_TABS == ("session", "jobs", "mail", "priorities", "score", "floor", "plan")
    assert "admin" not in DEFAULT_MAIN_TABS
    assert "guide" not in DEFAULT_MAIN_TABS
    assert "wire" not in DEFAULT_MAIN_TABS


def test_hash_show_tab_accepted():
    assert "floor" in HASH_SHOW_TAB
    assert "scorecards" in HASH_SHOW_TAB
    assert "stations" in HASH_SHOW_TAB
    for name in ("floor", "mail", "score", "scorecards", "session", "jobs", "plan"):
        assert show_tab_contract(name)["hash_accepted"] is True


def test_ensure_paint_contracts_flags():
    floor = ensure_floor_paint_contract()
    assert floor["ensure_fn"] == "ensureFloorPaint"
    assert floor["tabs"] == ("floor",)
    assert floor["repaint_on_show"] is True
    assert floor["raf_second_paint"] is True
    assert floor["load_glance_if_empty"] is True
    assert floor["marker"] == "WALL_LOGIC_TABS_SOR"

    mail = ensure_mail_paint_contract()
    assert mail["ensure_fn"] == "ensureMailPaint"
    assert mail["tabs"] == ("mail",)
    assert mail["default_view"] == "list"
    assert mail["raf_second_paint"] is True

    score = ensure_score_paint_contract_flags()
    assert score["ensure_fn"] == "ensureScorePaint"
    assert "score" in score["tabs"] and "scorecards" in score["tabs"]
    assert score["hash_aliases"]["scorecards"] == "score"
    assert score["default_filter"] == "needs"
    assert score["default_span"] == "24h"

    allc = ensure_paint_contracts()
    assert set(allc) == {"ensureFloorPaint", "ensureMailPaint", "ensureScorePaint"}


def test_show_tab_alias_map_covers_board_hashes():
    m = show_tab_alias_map()
    for h in ("session", "floor", "jobs", "score", "scorecards", "mail", "plan", "stations", "backlog"):
        assert h in m
    assert m["stations"]["jobs_view"] == "stations"
    assert m["issues"]["nav"] == "plan"
