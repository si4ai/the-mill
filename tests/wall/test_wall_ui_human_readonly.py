# -*- coding: utf-8 -*-
"""Wall human-readonly: humans only read on the Wall, with no escape (#770)."""
from __future__ import annotations

from agent_coord.web.wall_logic.packs import wall_ui_root

from ._wall_src import boot_source

ROOT = wall_ui_root()
BOARD = ROOT / "default" / "board.html"
CSS = ROOT / "default" / "board.css"


def _boot() -> str:
    return boot_source()


def test_marker_and_helpers():
    src = _boot()
    assert "Marker: WALL_HUMAN_READONLY" in src
    assert "function wallHumanReadonly()" in src
    assert "function wallApplyHumanReadonly()" in src
    assert "wall-human-readonly" in src


def test_readonly_has_no_escape():
    src = _boot()
    fn = src.split("function wallHumanReadonly()", 1)[1].split(
        "function wallApplyHumanReadonly()", 1
    )[0]
    assert "return true" in fn
    assert "return false" not in fn
    assert "factory-human-readonly" not in src
    assert "human_write" not in src


def test_human_write_paths_are_gone():
    src = _boot()
    for gone in (
        "function markMailReadHuman(",
        "function ackMailHuman(",
        "function openMailPopup(",
        "function setCompose(",
        "function planPost(",
        "function persistPlanOrder(",
        "function collectBadge(",
        "mail-ack-human",
        "mail-rooms-reply",
        'class="sg-mail"',
        "data-plan-act",
    ):
        assert gone not in src, gone


def test_only_drag_is_the_todo_list_column_order():
    """Dragging is view-only: TODO list headings reorder columns kept in localStorage.
    No other drag source, and the list wiring never writes to the server."""
    src = _boot()
    assert src.count('draggable="true"') == 1
    paint = src.split("function wallTodoListPaint()", 1)[1].split("function wireTodoList()", 1)[0]
    assert 'draggable="true"' in paint
    wire = src.split("function wireTodoList()", 1)[1].split("/* nest time window", 1)[0]
    for write in ("fetch(", "method:", "POST", "XMLHttpRequest"):
        assert write not in wire, write


def test_get_polls_still_present():
    src = _boot()
    assert "setInterval(function () { tick(); }, 15000)" in src
    assert "/api/v1/" in src
    assert "/api/floor" not in src
    assert "wallStartFloorPoll" in src


def test_css_keeps_admin_hidden():
    css = CSS.read_text(encoding="utf-8")
    assert "html.wall-human-readonly #admin-mint" in css
    assert "html.wall-human-readonly #mail-compose" not in css


def test_board_has_no_compose_sheet():
    html = BOARD.read_text(encoding="utf-8")
    for gone in ('id="mail-compose"', 'id="compose-overlay"', 'id="desk-form"', 'data-human-write="1"'):
        assert gone not in html, gone
