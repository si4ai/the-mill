# -*- coding: utf-8 -*-
"""Wall UI: consume versioned part routes for a project, a role, or a station."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOOT = ROOT / "default" / "boot.js"

# Locked v1 surface set (joined map/timeline; no invent beyond Builder Claim).
LOCKED_V1 = (
    "/api/v1/rooms",
    "/api/v1/mailbox",
    "/api/v1/tree-mail",
    "/api/v1/tree-todo",
    "/api/v1/todos",
    "/api/v1/agents",
    "/api/v1/scores",
    "/api/v1/holds",
    "/api/v1/watchers",
    "/api/v1/events",
    "/api/v1/names",
    "/api/v1/map",
    "/api/v1/timeline",
)


def _boot() -> str:
    return BOOT.read_text(encoding="utf-8")


def _routes() -> str:
    return _boot().split("function wallV1Routes", 1)[1].split(
        "function wallMergeV1Isolates", 1
    )[0]


def test_v1_helpers_present():
    src = _boot()
    for name in (
        "wallV1Routes",
        "wallMergeV1Isolates",
        "wallFetchFloorV1",
    ):
        assert name in src, f"missing {name}"
    assert "/api/floor" not in src


def test_mail_rooms_hits_rooms_mailbox_tree_mail():
    routes = _routes()
    assert '"/api/v1/rooms"' in routes
    assert '"/api/v1/mailbox"' in routes
    assert '"/api/v1/tree-mail"' in routes
    assert 'mailView === "rooms"' in routes


def test_mail_list_mailbox_only():
    """nest/list (non-rooms) uses mailbox isolate; wallParts stays mail-only."""
    routes = _routes()
    assert 'return [{ path: "/api/v1/mailbox", kind: "mailbox" }];' in routes
    assert 'mailView === "rooms") ? "mail,trees" : "mail"' in _boot()


def test_todo_nest_list_board_todos_and_tree_todo():
    routes = _routes()
    assert '"/api/v1/todos"' in routes
    assert '"/api/v1/tree-todo"' in routes
    assert 'tab === "jobs"' in routes
    assert 'core = "todos,trees"' in _boot()


def test_role_and_lan_use_the_same_part_routes():
    routes = _routes()
    assert 'indexOf("project:") !== 0) return null' not in routes
    assert "scope.query" in routes


def test_session_now_routes_agents_v1():
    """SESSION Now (agents-only) hits GET /api/v1/agents; multi-part stays floor."""
    routes = _routes()
    assert '"/api/v1/agents"' in routes
    assert 'kind: "agents"' in routes
    assert 'return [{ path: "/api/v1/agents", kind: "agents" }];' in routes
    assert 'parts === "agents"' in routes
    assert 'tab === "session"' in routes
    assert "data-session-mode" in routes


def test_score_glossary_session_modes_route_v1():
    """single-part score/glossary/leases/watch/history -> v1 isolates."""
    routes = _routes()
    assert 'tab === "score"' in routes
    assert 'return [{ path: "/api/v1/scores", kind: "scores" }];' in routes
    assert 'tab === "glossary"' in routes
    assert 'return [{ path: "/api/v1/names", kind: "names" }];' in routes
    assert 'parts === "holds"' in routes
    assert 'return [{ path: "/api/v1/holds", kind: "holds" }];' in routes
    assert 'parts === "watchers"' in routes
    assert 'return [{ path: "/api/v1/watchers", kind: "watchers" }];' in routes
    assert 'parts === "events"' in routes
    assert 'return [{ path: "/api/v1/events", kind: "events" }];' in routes
    # wallParts still scopes these single parts
    src = _boot()
    assert 'core = "scores"' in src
    assert 'core = "names"' in src
    assert 'core = "holds"' in src
    assert 'core = "watchers"' in src
    assert 'core = "events"' in src


def test_floor_hybrids_hit_joined_map_timeline():
    """FLOOR map/timeline hybrids hit joined v1 (one RTT); not Promise.all fan-out."""
    routes = _routes()
    src = _boot()
    assert 'core = mode === "timeline" ? "agents,timeline" : "agents,mail"' in src
    assert '"agents,events"' in src or "agents,events" in src
    # joined isolates
    assert 'parts === "agents,mail"' in routes
    assert 'path: "/api/v1/map"' in routes
    assert 'kind: "map"' in routes
    assert 'parts === "agents,events"' in routes
    assert 'path: "/api/v1/timeline"' in routes
    assert 'kind: "timeline"' in routes
    assert 'parts === "agents,timeline"' in routes
    assert 'queryParts: "agents,timeline"' in routes
    # must NOT reintroduce parallel agents+mailbox fan-out for Map
    map_block = routes.split('parts === "agents,mail"', 1)[1].split(
        'parts === "agents,events"', 1
    )[0]
    assert '"/api/v1/agents"' not in map_block
    assert '"/api/v1/mailbox"' not in map_block
    assert "Promise.all" not in map_block
    assert "activityBetweenQuery()" in map_block
    assert 'kind: "between"' in map_block
    assert "absolute: true" in map_block
    assert "/api/v1/map?" not in map_block
    between = src.split("function activityBetweenQuery(", 1)[1].split("function paintFloorSpan(", 1)[0]
    assert "/api/activity?" in between
    assert "window=between" in between
    assert "/api/v1/map" not in between
    merge = src.split("function wallMergeV1Isolates", 1)[1].split("async function wallFetchFloorV1", 1)[0]
    assert 'kind === "between"' in merge
    assert "out.between = json.rows" in merge
    shared = src.split("function floorShared(", 1)[1].split("function normalizeFloorEdges(", 1)[0]
    assert "Array.isArray(d.between)" in shared
    book = src.split("function mergeFloorSlice(", 1)[1].split("function cutFloor(", 1)[0]
    assert "base.between = slice.between" in book
    assert "delete base.between" in book
    # single-part still on v1
    assert 'parts === "agents"' in routes


def test_merge_prefers_tree_mail_over_rooms_trees():
    src = _boot()
    merge = src.split("function wallMergeV1Isolates", 1)[1].split(
        "async function wallFetchFloorV1", 1
    )[0]
    assert "treesTyped" in merge
    assert "treesRooms" in merge
    assert "if (treesTyped) out.trees = treesTyped;" in merge
    assert "else if (treesRooms) out.trees = treesRooms;" in merge
    # contract field keys reused
    assert "out.mailbox" in merge
    assert "out.needs" in merge
    assert "out.issues" in merge
    assert 'addPart("mail")' in merge
    assert 'addPart("todos")' in merge
    assert 'addPart("trees")' in merge
    assert 'addPart("agents")' in merge
    assert "out.agents" in merge
    assert "out.next_agents" in merge
    # kill-slice merge kinds
    assert 'addPart("scores")' in merge
    assert "out.kpis" in merge
    assert "out.next_scores" in merge
    assert 'addPart("holds")' in merge
    assert "out.locks" in merge
    assert "out.next_holds" in merge
    assert 'addPart("watchers")' in merge
    assert "out.watchers" in merge
    assert "out.next_watchers" in merge
    assert 'addPart("events")' in merge
    assert "out.events" in merge
    assert "out.next_events" in merge
    assert 'addPart("names")' in merge
    assert "out.catalog" in merge
    assert "out.next_names" in merge


def test_v1_down_paints_the_wall_down():
    src = _boot()
    fetch_fn = src.split("async function wallFetchFloorV1", 1)[1].split(
        "function wallMailRoomsWantEarlyRail", 1
    )[0]
    assert "r.status === 404" in fetch_fn
    assert "down: true" in fetch_fn
    body = src.split("async function _tickBody()", 1)[1]
    assert "paintApiDown" in body
    assert "/api/floor" not in body
    assert "floorFpQuery(projectKey, partsStr)" not in body


def test_pageable_fetch_limit_and_fp():
    """pageable isolates limit=50 + fp + remember; map/timeline pageable; mailbox fp key mail."""
    src = _boot()
    fetch_fn = src.split("async function wallFetchFloorV1", 1)[1].split(
        "function wallMailRoomsWantEarlyRail", 1
    )[0]
    assert "pageKinds" in fetch_fn
    assert "fpKinds" in fetch_fn
    assert "limit=50" in fetch_fn
    assert "floorFpQuery(scope.key, fpPart)" in fetch_fn
    assert "wallRememberListNext" in fetch_fn
    for k in ("scores", "holds", "watchers", "events", "names", "agents", "map", "timeline", "tree-mail", "tree-todo"):
        assert k in fetch_fn
    assert "depth=1" in fetch_fn
    assert 'mailbox: "mail"' in fetch_fn
    assert "fpParts" in fetch_fn
    assert "queryParts" in fetch_fn


def test_list_next_uses_v1_when_up():
    src = _boot()
    page = src.split("async function wallFetchListNextPage", 1)[1][:4000]
    for path in (
        "/api/v1/agents",
        "/api/v1/scores",
        "/api/v1/holds",
        "/api/v1/watchers",
        "/api/v1/events",
        "/api/v1/names",
    ):
        assert path in page
    assert "/api/floor" not in page


def test_mail_rooms_fetch_staggers_mailbox():
    """MAIL Rooms: mailbox first; tree-mail/rooms after. Jobs: todos before tree-todo."""
    src = _boot()
    fetch_fn = src.split("async function wallFetchFloorV1", 1)[1].split(
        "function wallMailRoomsWantEarlyRail", 1
    )[0]
    assert "phaseA" in fetch_fn
    assert "phaseB" in fetch_fn
    assert 'r.kind === "mailbox"' in fetch_fn
    assert 'r.kind === "todos"' in fetch_fn
    assert "hasMailTree" in fetch_fn
    assert "hasTodoTree" in fetch_fn


def test_human_readonly_get_only_no_invented_routes():
    src = _boot()
    assert "Marker: WALL_HUMAN_READONLY" in src
    for locked in LOCKED_V1:
        assert locked in src, f"missing locked route {locked}"
    # do not invent beyond locked set (map/timeline now allowed)
    for banned in (
        "/api/v1/activity",
        "/api/v1/locks",
        "/api/v1/kpis",
        "/api/v1/catalog",
    ):
        assert banned not in src, f"invented route {banned}"
    assert src.count('"/api/v1/glance"') == 1
    assert src.count('"/api/v1/glance/tap"') == 1
    assert "/api/v1/glance" not in src.split("async function _tickBody()", 1)[1]
    opener = src.split("async function loadWallService()", 1)[1].split("function openWallService()", 1)[0]
    assert "timings" not in opener
    assert "function glanceKeyName" in src
    assert "glanceSpots" not in src
    assert "wall-keypad-grid" in src
    assert "i < 100" in src
    assert "trees_depth" not in src
    assert "depth=1" in src
    assert "progressive trees PARKED" not in src


def test_no_builder_server_sor_in_wall_surface():
    """Wall claim must not embed Builder floor.py / middleware SoR."""
    src = _boot()
    assert "v1_rooms" not in src
    assert "v1_agents" not in src
    assert "v1_scores" not in src
    assert "mail_room_root_rows" not in src
    assert "build_rooms" not in src


def test_floor_hybrid_early_absorb_not_on_floor_tab():
    """early-absorb stays session/score/glossary; FLOOR hybrids settle via joined v1."""
    body = _boot().split("async function _tickBody()", 1)[1][:8000]
    absorb_ifs = [ln for ln in body.splitlines() if "tabNow ===" in ln and "session" in ln]
    assert absorb_ifs, "missing early-absorb tabNow check"
    absorb_if = absorb_ifs[0]
    assert 'tabNow === "floor"' not in absorb_if
    lines = body.splitlines()
    idx = lines.index(absorb_if)
    chunk = "\n".join(lines[idx: idx + 4])
    assert 'kind === "mailbox"' not in chunk
