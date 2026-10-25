# -*- coding: utf-8 -*-
"""Wall Nest URL paths /project|/station|/role."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOOT = ROOT / "default" / "boot.js"


def _boot() -> str:
    return BOOT.read_text(encoding="utf-8")


def test_path_helpers_and_families():
    src = _boot()
    for name in (
        "nestEncodeSlug",
        "nestDecodeSlug",
        "parseNestPath",
        "compatNestQueryToPath",
        "applyRailNestUrl",
        "nestPickFromPath",
        "nestFamilyForKind",
    ):
        assert f"function {name}(" in src
    assert "/(project|station|role)" in src
    assert 'family === "station"' in src
    assert 'family === "role"' in src
    assert 'family === "project"' in src


def test_projects_path_not_query():
    src = _boot()
    assert "Projects live under /project/<slug>" in src or "/project/<slug>" in src
    assert "NEST_PATH_WRITE" in src
    assert "var NEST_PATH_WRITE = true" in src or "NEST_PATH_WRITE = true" in src
    af = src.split("function applyFilterToUrl(", 1)[1].split("function applyRailNestUrl(", 1)[0]
    assert 'searchParams.set("projects"' in af
    assert "NEST_PATH_WRITE" in af
    assert 'applyNestPathToUrl(u, "project"' in af


def test_current_filter_reads_path_and_query():
    src = _boot()
    cf = src.split("function currentFilter(", 1)[1].split("function urlHasFilter(", 1)[0]
    assert "parseNestPath" in cf
    assert 'nest.family === "project"' in cf
    assert 'q.get("projects")' in cf


def test_compat_accepts_old_query_shapes():
    src = _boot()
    compat = src.split("function compatNestQueryToPath(", 1)[1].split("function nestPickFromPath(", 1)[0]
    assert 'q.get("projects")' in compat
    assert 'q.get("stations")' in compat
    assert 'q.get("lan")' in compat
    assert 'q.get("roles")' in compat
    assert "history.replaceState" in compat
    head = src.split("WALL_NEST_PATH_WOW175", 1)[1][:800]
    assert "/project|station|role/<slug>" in head
    assert "IPv4 dots" in head or "dots stay literal" in head


def test_station_ip_encoding_safe():
    src = _boot()
    enc = src.split("function nestEncodeSlug(", 1)[1].split("function nestDecodeSlug(", 1)[0]
    assert "encodeURIComponent" in enc
    head = src.split("WALL_NEST_PATH_WOW175", 1)[1][:900]
    assert "IPv4 dots" in head or "dots stay literal" in head
    assert "IPv6" in head


def test_select_rail_writes_station_role_paths():
    src = _boot()
    sr = src.split("async function selectRail(", 1)[1].split("function paintRailBook(", 1)[0]
    assert 'applyRailNestUrl("lan"' in sr
    assert 'applyRailNestUrl("role"' in sr
    assert 'applyRailNestUrl("project"' in sr


def test_boot_calls_compat_on_load():
    src = _boot()
    assert "compatNestQueryToPath()" in src
    compat = src.split("function compatNestQueryToPath(", 1)[1].split("function nestPickFromPath(", 1)[0]
    assert "if (!NEST_PATH_WRITE) return false" in compat
