"""Pack seams + fungibility ladder (knobs -> pack override -> share)."""
from __future__ import annotations

from pathlib import Path

from agent_coord.server.middleware import wall_asset_id, wall_ui_default_board
from agent_coord.web.wall_logic import (
    DEFAULT_PACK_ID,
    default_board_path,
    default_pack_dir,
    pack_seam_inventory,
    wall_ui_root,
)
from agent_coord.web.wall_logic.knobs import (
    BOARD_EQUIVALENT_MARKER,
    FUNGIBILITY_LADDER,
    KNOBS_DO_NOT_REPLACE_PACK,
    PROPOSED_DB_KNOBS,
    apply_chrome_flags,
    css_vars_style_attr,
    knobs_contract,
    merge_knob_layer,
    resolve_density,
    resolve_land_tab,
    resolve_mail_default_view,
    resolve_pack_id,
    resolve_pane_order,
    resolve_score_default_filter,
)


def test_default_pack_is_sor_board():
    board = default_board_path()
    assert board.is_file()
    assert "wall_ui" in str(board).replace("\\", "/")
    assert board.name == "board.html"
    assert default_pack_dir().name == DEFAULT_PACK_ID
    # middleware seam agrees
    assert wall_ui_default_board().resolve() == board.resolve()
    aid = wall_asset_id(board)
    assert len(aid) == 16


def test_seam_inventory_honest_about_p1():
    inv = pack_seam_inventory()
    assert inv["shipped"]["p0_folder_layout"] is True
    assert inv["shipped"]["p0_default_board"] is True
    assert inv["parked_p1"]["live_in_browser_tweak"] is False
    assert inv["parked_p1"]["marketplace_private_public"] is False
    assert inv["parked_p1"]["office_share_adopt"] is False
    assert inv["shipped"].get("p0_domain_folders") is True
    assert any("domain folders" in b or "board.html still large" in b for b in inv["blockers_for_live_share"])
    assert (wall_ui_root() / "components").is_dir()


def test_fungibility_ladder_not_knobs_only():
    assert FUNGIBILITY_LADDER[0] == "db_knobs"
    assert "pack_css_js_override" in FUNGIBILITY_LADDER
    assert FUNGIBILITY_LADDER[-1] == "office_share"
    # knobs are easy path; full pack assets remain allowed
    names = {k["name"] for k in PROPOSED_DB_KNOBS}
    assert "pane_order" in names
    assert "css_vars" in names
    assert "chrome_flags" in names


def test_knob_helpers_pure():
    assert resolve_pane_order(None)[0] == "session"
    ordered = resolve_pane_order(["mail", "session"])
    assert ordered[:2] == ["mail", "session"]
    assert set(ordered) == {"session", "floor", "jobs", "score", "mail", "plan", "priorities"}
    flags = apply_chrome_flags({"show_wire": True, "land_tab": "floor"})
    assert flags["show_wire"] is True
    assert flags["land_tab"] == "floor"
    assert flags["show_admin_chrome"] is True  # default



def test_marker_wall_logic_knobs_sor():
    assert BOARD_EQUIVALENT_MARKER == "WALL_LOGIC_KNOBS_SOR"
    c = knobs_contract()
    assert c["marker"] == "WALL_LOGIC_KNOBS_SOR"
    assert c["knobs_do_not_replace_pack"] is True
    assert c["schema_migrated"] is False
    assert c["pure"] is True
    assert c["path"] == "A"
    assert KNOBS_DO_NOT_REPLACE_PACK is True


def test_proposed_knob_names_ladder_complete():
    names = {k["name"] for k in PROPOSED_DB_KNOBS}
    for need in (
        "pane_order",
        "land_tab",
        "density",
        "css_vars",
        "chrome_flags",
        "mail_default_view",
        "score_default_filter",
        "pack_id",
    ):
        assert need in names
    assert list(FUNGIBILITY_LADDER) == ["db_knobs", "pack_css_js_override", "office_share"]


def test_resolve_land_density_mail_score_pack():
    assert resolve_land_tab(None)["hash"] == "session"
    assert resolve_land_tab("floor")["pane"] == "floor"
    assert resolve_land_tab("scorecards")["pane"] == "score"
    assert resolve_land_tab("nope-unknown")["hash"] == "session"
    dens = resolve_density("compact")
    assert dens["density"] == "compact"
    assert dens["full_stylesheet"] is False
    assert "--row-pad" in dens["css_vars"]
    assert resolve_density("weird")["density"] == "comfortable"
    assert resolve_mail_default_view("graph") == "graph"
    assert resolve_mail_default_view("nope") == "list"
    assert resolve_score_default_filter("all") == "all"
    assert resolve_score_default_filter("") == "needs"
    assert resolve_pack_id(None) == "default"
    assert resolve_pack_id("office-a") == "office-a"


def test_merge_knob_layer_ladder_pack_assets_survive():
    """db knobs easy path; pack override may still supply full CSS/JS."""
    merged = merge_knob_layer(
        db_knobs={
            "pane_order": ["mail", "session"],
            "land_tab": "mail",
            "density": "compact",
            "mail_default_view": "graph",
            "score_default_filter": "all",
            "chrome_flags": {"show_wire": True},
        },
        pack_override={
            "pack_id": "custom",
            "pack_css": "custom.css",
            "pack_js": "custom.js",
            "css_vars": {"--accent": "#f00"},
        },
        share=None,
    )
    assert merged["applied_layers"] == ["defaults", "db_knobs", "pack_css_js_override"]
    assert merged["pane_order"][:2] == ["mail", "session"]
    assert set(merged["pane_order"]) == {"session", "floor", "jobs", "score", "mail", "plan", "priorities"}
    assert merged["land_tab"] == "mail"
    assert merged["density"] == "compact"
    assert merged["mail_default_view"] == "graph"
    assert merged["score_default_filter"] == "all"
    assert merged["chrome_flags"]["show_wire"] is True
    assert merged["pack_id"] == "custom"
    assert merged["pack_css"] == "custom.css"
    assert merged["pack_js"] == "custom.js"
    assert merged["knobs_do_not_replace_pack"] is True
    assert merged["css_vars"]["--accent"] == "#f00"
    assert "--row-pad" in merged["css_vars"]  # density still applied
    assert "pack_css_js_override" in merged["ladder"]
    # knobs alone never invent pack_css
    db_only = merge_knob_layer(db_knobs={"land_tab": "floor"})
    assert db_only["pack_css"] is None
    assert db_only["pack_js"] is None


def test_css_vars_style_attr_sanitizes():
    assert css_vars_style_attr(None) == ""
    assert css_vars_style_attr({"accent": "x"}) == ""  # must be --*
    s = css_vars_style_attr({"--a": "1;{hack}", "--b": "2"})
    assert s == "--a:1hack;--b:2" or "--a:1hack" in s


def test_seam_inventory_exposes_ladder():
    inv = pack_seam_inventory()
    assert inv["fungibility_ladder"][0] == "db_knobs"
    assert inv["knobs_do_not_replace_pack"] is True
