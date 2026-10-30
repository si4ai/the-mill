# -*- coding: utf-8 -*-
"""Activity state (#92): events and between rows carry state; Wall paints a read-only pill."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOOT = ROOT / "default" / "boot.js"
CSS = ROOT / "default" / "board.css"
SHELL_CSS = ROOT / "default" / "shell.css"


def _pill_src() -> str:
    src = BOOT.read_text(encoding="utf-8")
    start = src.index("function activityStatePill(")
    end = src.index("\n    }\n", start) + len("\n    }\n")
    return src[start:end]


def test_pill_paints_only_known_states():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        "const esc = s => String(s == null ? '' : s);\n"
        + _pill_src()
        + "\nconsole.log(JSON.stringify(["
        "activityStatePill({state: 'deleted'}), activityStatePill({state: 'sent'}),"
        "activityStatePill({state: null}), activityStatePill({}), activityStatePill(null),"
        "activityStatePill({state: '<b>x</b>'}), activityStatePill({state: 'DELETED'})]));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    deleted, sent, none1, none2, none3, junk, upper = json.loads(out)
    assert 'class="act-state st-deleted"' in deleted and ">deleted<" in deleted
    assert 'class="act-state st-sent"' in sent and ">sent<" in sent
    assert none1 == none2 == none3 == junk == ""
    assert upper == deleted


def test_state_rides_events_into_diary_and_wire():
    src = BOOT.read_text(encoding="utf-8")
    assert "WALL_ACTIVITY_STATE_92" in src
    rows_at = src.index("function presenceRowsForUi(")
    rows = src[rows_at: src.index("\n    function ", rows_at + 1)]
    assert "state: r.state || null" in rows
    diary = src[src.index("function paintSessionWire("): src.index("function wire(d)")]
    assert "activityStatePill(p)" in diary
    start = src.index("function wire(d)")
    wire = src[start: src.index("\n    function ", start + 1)]
    assert "activityStatePill(p)" in wire


def test_pill_is_read_only_and_styled_outside_shell():
    pill = _pill_src()
    for bad in ("<button", "<input", "onclick", "data-human-write", "fetch(", "planPost", "adminPost"):
        assert bad not in pill
    css = CSS.read_text(encoding="utf-8")
    assert ".act-state {" in css and ".act-state.st-deleted" in css and ".act-state.st-sent" in css
    shell = SHELL_CSS.read_text(encoding="utf-8")
    assert "act-state" not in shell
    assert len(shell.encode("utf-8")) < 16_000


def _presence_src() -> str:
    src = BOOT.read_text(encoding="utf-8")
    start = src.index("function presenceRowsForUi(")
    end = src.index("\n    function ", start + 1)
    return src[start:end]


def test_history_diary_paints_events_not_daily_evidence():
    """Live #92 miss: daily span rows are score_evidence (no type/updated/state).

    History must paint the per-item events (at/kind/state); the minute chart still
    reads activity buckets.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    script = (
        "const millGid = r => r.roster_id || '';\n"
        "let _q = {key: 'lan:x|daily'};\n"
        "const activitySpanQuery = () => _q;\n"
        "let _presenceKey = 'lan:x|daily';\n"
        "let _presenceSource = 'score_evidence';\n"
        "let _presenceRows = [{desk_id: 1, owner: 'a', timestamp: '2026-10-09T00:00:00', value: {n: 3}}];\n"
        "globalThis.window = {_floor: {timeline: [], events: [\n"
        "  {id: 1247, kind: 'mail', type: 'mail', at: '2026-10-09T13:23:05', owner: 'validator', n: 1, state: 'sent'},\n"
        "  {id: 9, kind: 'todo', type: 'todo', at: '2026-10-09T13:00:00', owner: 'b', n: 1, state: null}]}};\n"
        + _presence_src()
        + "\nconst diary = presenceRowsForUi({diary: true});\n"
        "const chartDaily = presenceRowsForUi();\n"
        "_q = {key: 'lan:x|min'}; _presenceKey = 'lan:x|min'; _presenceSource = 'activity';\n"
        "_presenceRows = [{updated: '2026-10-09T13:22:00', type: 'mail', owner: 'a', items: 2}];\n"
        "const chartMin = presenceRowsForUi();\n"
        "const diaryMin = presenceRowsForUi({diary: true});\n"
        "console.log(JSON.stringify({diary, chartDaily, chartMin, diaryMin}));"
    )
    out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
    d = out["diary"]
    assert [r["kind"] for r in d] == ["mail", "todo"]
    assert d[0]["at"] == "2026-10-09T13:23:05" and d[0]["state"] == "sent"
    assert d[1]["state"] is None
    # Evidence rows never become kind-less, time-less list rows.
    assert all(r["kind"] for r in out["chartDaily"])
    assert out["chartMin"][0]["kind"] == "mail" and out["chartMin"][0]["items"] == 2
    assert "n" not in out["chartMin"][0]
    assert "n" not in d[0]
    assert [r["kind"] for r in out["diaryMin"]] == ["mail", "todo"]
    src = BOOT.read_text(encoding="utf-8")
    diary_src = src[src.index("function paintSessionWire("): src.index("function wire(d)")]
    assert "presenceRowsForUi({ diary: true })" in diary_src
