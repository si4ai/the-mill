# -*- coding: utf-8 -*-
"""Watcher push matches hints.md per activity: default detail, or that desk's recipe."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push

PROGRAM = Path(__file__).resolve().parents[1] / "programs" / "hint_check.py"
_spec = importlib.util.spec_from_file_location("hint_check", PROGRAM)
assert _spec and _spec.loader
hint_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hint_check)
ACTIVITIES = hint_check.ACTIVITIES
check_frame = hint_check.check_frame

# Activity, route hint, example watcher.hint recipe (hints.md).
RECIPES = [
    ("mail", "MAIL", "src,dst,body"),
    ("todo", "TODO", "need,status,assigned"),
    ("hold", "HOLD", "resource,desk"),
    ("score", "SCORE", "kpi,value,target"),
    ("doing", "DOING", "session"),
    ("name", "NAME", "slug"),
]


def _fanout(activity: str, nid: int, rows: list[dict], *, tree: list[dict] | None = None, sitting: set[str] | None = None):
    cn = MagicMock()
    cur = MagicMock()
    cn.cursor.return_value = cur
    cur.fetchall.return_value = tree or []
    notified: list[tuple[str, dict]] = []
    rooms = {desk: {object()} for desk in (sitting if sitting is not None else {r["desk"] for r in rows})}

    def capture(desk, payload):
        notified.append((desk, dict(payload)))

    with patch("agent_coord.server.records.watcher.select", return_value=rows), patch(
        "agent_coord.server.records.activity.get",
        return_value={"type": activity, "id": nid, "updated": "2026-09-19 16:00:00.000000"},
    ), patch.object(push.HUB, "rooms", rooms), patch.object(push.HUB, "notify", side_effect=capture):
        push.fanout(cn, activity, nid, activity.upper())
    return notified


def _run_program(payload: dict, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROGRAM), *extra],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("activity,hint,recipe", RECIPES)
def test_default_push_and_program(activity, hint, recipe) -> None:
    tree = [{"name_id": 58, "lft": 1, "rgt": 10}] if activity == "todo" else []
    rows = [{"desk": "DESK_watcher", "hint": None, "delivery_mode": "polling", "endpoint_url": ""}]
    notified = _fanout(activity, 14, rows, tree=tree)
    assert [d for d, _ in notified] == ["DESK_watcher"]
    payload = notified[0][1]
    assert payload["type"] == activity
    assert payload["id"] == 14
    assert payload["hint"] == hint
    check_frame(payload)
    if activity == "todo":
        assert json.loads(payload["detail"])["tree"] == [{"tree": 58, "lft": 1, "rgt": 10}]
    proc = _run_program(payload)
    assert proc.returncode == 0, proc.stderr
    assert f"ok hint={hint}" in proc.stdout


@pytest.mark.parametrize("activity,hint,recipe", RECIPES)
def test_custom_recipe_only_that_desk(activity, hint, recipe) -> None:
    rows = [
        {"desk": "DESK_custom", "hint": recipe, "delivery_mode": "polling", "endpoint_url": ""},
        {"desk": "DESK_default", "hint": None, "delivery_mode": "polling", "endpoint_url": ""},
        {"desk": "DESK_cleared", "hint": "", "delivery_mode": "polling", "endpoint_url": ""},
    ]
    tree = [{"name_id": 58, "lft": 1, "rgt": 10}] if activity == "todo" else []
    notified = _fanout(activity, 14, rows, tree=tree)
    by = {d: p for d, p in notified}
    assert set(by) == {"DESK_custom", "DESK_default", "DESK_cleared"}
    assert by["DESK_custom"]["hint"] == hint
    assert by["DESK_custom"]["detail"] == recipe
    check_frame(by["DESK_custom"], recipe)
    check_frame(by["DESK_default"])
    check_frame(by["DESK_cleared"])
    custom = _run_program(by["DESK_custom"], "--custom", recipe)
    assert custom.returncode == 0, custom.stderr
    default = _run_program(by["DESK_default"])
    assert default.returncode == 0, default.stderr
    wrong = _run_program(by["DESK_default"], "--custom", recipe)
    assert wrong.returncode == 1


def test_unwatched_desk_gets_no_push() -> None:
    rows = [{"desk": "DESK_watcher", "hint": None, "delivery_mode": "polling", "endpoint_url": ""}]
    notified = _fanout("mail", 3, rows, sitting={"DESK_watcher", "DESK_other"})
    assert [d for d, _ in notified] == ["DESK_watcher"]


def test_watcher_not_connected_gets_no_socket_push() -> None:
    rows = [{"desk": "DESK_away", "hint": "src,dst", "delivery_mode": "polling", "endpoint_url": ""}]
    notified = _fanout("mail", 3, rows, sitting=set())
    assert notified == []


def test_program_rejects_body_and_ping() -> None:
    leak = {
        "type": "mail",
        "id": 1,
        "hint": "MAIL",
        "detail": json.dumps({"what": "mail", "id": 1, "when": "t", "watchers": 1, "tree": [], "body": "hi"}),
    }
    assert _run_program(leak).returncode == 1
    ping = {"type": "heartbeat", "id": 0, "hint": "PING", "detail": ""}
    assert _run_program(ping).returncode == 1


def test_table_covers_hints_md() -> None:
    assert ACTIVITIES == {a: h for a, h, _ in RECIPES}


def test_h13_label_add_pokes_todo_not_label() -> None:
    """Gardener H13: label-add on a todo wakes watchers of that todo."""
    from unittest.mock import MagicMock, patch

    from agent_coord.server.api.mill import rpc

    calls: list[tuple] = []

    def fake_fanout(cn, typ, nid, hint, **kw):
        calls.append((typ, nid, hint))
        # #280: the labelling desk is skipped; the hint time is the label's own.
        assert kw.get("skip_desk") == "builder"

    book = MagicMock()
    with patch("agent_coord.server.records.label.put", return_value=[{"ok": True}]), patch(
        "agent_coord.server.push.fanout", side_effect=fake_fanout
    ):
        rpc._h_label(
            book,
            {"verb": "label-add", "type": "todo", "id": 14, "label": "bug"},
            "the-mill",
            "builder",
        )
    assert calls == [("todo", 14, "TODO")]


def test_h14_star_mail_notifies_watchers_only() -> None:
    """Gardener H14: dst=* still pushes only desks watching that mail."""
    rows = [{"desk": "DESK_watcher", "hint": None, "delivery_mode": "polling", "endpoint_url": ""}]
    notified = _fanout(
        "mail",
        88,
        rows,
        sitting={"DESK_watcher", "DESK_bystander"},
    )
    assert [d for d, _ in notified] == ["DESK_watcher"]
    assert notified[0][1]["hint"] == "MAIL"
    assert notified[0][1]["id"] == 88


def test_h15_reconnect_does_not_replay_jsonl(tmp_path, monkeypatch) -> None:
    """Gardener H15: a new mill connect does not flood frames missed while down."""
    from agent_coord.server.hint_buf import HintBuf

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    first = HintBuf("builder")
    first.append_file({"type": "mail", "id": 1, "hint": "MAIL", "detail": "missed"})
    assert first.path.is_file()
    again = HintBuf("builder")
    assert again.get_work(timeout=0.01) is None


def test_route_program_receives_mail_notification(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    rows = [{"desk": "DESK_builder", "hint": None, "delivery_mode": "polling", "endpoint_url": ""}]
    payload = _fanout("mail", 7, rows)[0][1]
    stamp = tmp_path / "got.json"
    from agent_coord.client.dispatch import dispatch_hint
    from agent_coord.client.route_chain import save_routes

    save_routes(
        "builder",
        {"mail:MAIL": subprocess.list2cmdline([sys.executable, str(PROGRAM), "--stamp", str(stamp)])},
    )
    kind = dispatch_hint("builder", payload)
    assert kind == "work"
    for _ in range(80):
        if stamp.is_file() and stamp.stat().st_size:
            break
        import time

        time.sleep(0.05)
    assert stamp.is_file(), "route program was not notified"
    got = json.loads(stamp.read_text(encoding="utf-8"))
    assert got == {"ok": True, "hint": "MAIL", "id": 7}
