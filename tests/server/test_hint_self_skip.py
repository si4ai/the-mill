"""Card #280: the writer gets no hint for its own change; a label hint time is fresh.

Regression row F26 (hint-self-skip).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_coord.server import push
from agent_coord.server.api.mill import rpc

ROOT = Path(__file__).resolve().parents[2]


def _rows():
    return [
        {"desk": "DESK_a", "hint": None, "delivery_mode": "polling", "endpoint_url": ""},
        {"desk": "DESK_b", "hint": None, "delivery_mode": "polling", "endpoint_url": ""},
    ]


def _fan(**kw):
    notified, logged = [], []
    with patch("agent_coord.server.records.watcher.select", return_value=_rows()), patch.object(
        push, "_cheap_detail", return_value='{"what":"todo","id":5}'
    ), patch.object(push, "_desk_room_keys", side_effect=lambda d: [d] if d else []), patch.object(
        push.HUB, "rooms", {"DESK_a": {object()}, "DESK_b": {object()}}
    ), patch.object(push.HUB, "notify", side_effect=lambda d, p: notified.append(d)), patch(
        "agent_coord.server.records.push.put", side_effect=lambda cn, d, *a, **k: logged.append(d)
    ):
        push.fanout(MagicMock(), "todo", 5, "TODO", **kw)
    return notified, logged


def test_writer_gets_no_hint_for_own_change():
    notified, logged = _fan(skip_desk="DESK_a")
    assert notified == ["DESK_b"]
    assert logged == ["DESK_b"]


def test_other_watchers_still_get_the_hint():
    notified, _ = _fan()
    assert sorted(notified) == ["DESK_a", "DESK_b"]


def test_poke_skips_the_acting_desk():
    seen = {}
    with patch("agent_coord.server.push.fanout", side_effect=lambda *a, **k: seen.update(k)):
        rpc._poke(MagicMock(), "todo", 5, "note", owner="DESK_a")
    assert seen["skip_desk"] == "DESK_a"
    assert seen["when"] == ""


def test_label_poke_stamps_a_fresh_hint_time():
    seen = {}
    with patch("agent_coord.server.push.fanout", side_effect=lambda *a, **k: seen.update(k)), patch(
        "agent_coord.server.records.db.scalar", return_value="2026-10-18 05:00:00.000001"
    ):
        rpc._poke(MagicMock(), "todo", 5, "label-add", owner="DESK_a", fresh=True)
    assert seen["when"] == "2026-10-18 05:00:00.000001"


def test_fresh_time_overrides_the_activity_time():
    cn = MagicMock()
    cn.cursor.return_value.fetchall.return_value = []
    with patch("agent_coord.server.records.activity.get", return_value={"updated": "2026-10-01 00:00:00"}):
        old = json.loads(push._cheap_detail(cn, "todo", 5, []))
        new = json.loads(push._cheap_detail(cn, "todo", 5, [], when="2026-10-18 05:00:00"))
    assert old["when"] == "2026-10-01 00:00:00"
    assert new["when"] == "2026-10-18 05:00:00"


def test_every_desk_acting_poke_names_its_owner():
    src = (ROOT / "agent_coord" / "server" / "api" / "mill" / "rpc.py").read_text(encoding="utf-8")
    calls = re.findall(r"^\s+_poke(?:_tree)?\(c, .*\)$", src, flags=re.M)
    acting = [c for c in calls if 'got.get("id"), "join")' not in c]
    assert acting and all("owner=owner" in c for c in acting), acting
    assert any("fresh=True" in c for c in acting)


def test_regression_row_f26_documented():
    doc = (ROOT / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "Regression row F26 (hint-self-skip)" in doc
