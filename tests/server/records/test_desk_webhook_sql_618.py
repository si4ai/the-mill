"""#618 on a real book: the seat holds the desk's own webhook URL and key. Row F68 (desk-webhook).

Seen live: nothing wrote join.endpoint_url or delivery_mode, so no desk could be
armed. The key is per desk now, and only the POST-time read returns it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import call, rows_done, scalar_done
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql

URL = "https://hooks.example.test/automations/webhook/fx618-routine"
KEY = "fx618-key-0123456789"


def _seat(cn, desk: str) -> None:
    seed_names(cn, ("fx618", "roster"), (desk, "desk"))
    rec_join.upsert(cn, "fx618", desk, "", token_hash("seat-" + desk), None)
    cn.commit()


def _updated(cn, desk: str):
    return scalar_done(
        cn,
        "SELECT j.updated FROM seat j JOIN name d ON d.id = j.desk_id WHERE d.type = 'desk' AND d.name = %s",
        (desk,),
    )


def test_arm_then_off_and_reads_never_carry_the_key(cn):
    _seat(cn, "fx618-d1")
    assert rec_join.wake_state(cn, "fx618-d1") == {"armed": False, "host": "", "wake_on": "addressed"}
    assert rec_join.wake_target(cn, "fx618-d1") is None
    before = _updated(cn, "fx618-d1")
    rec_join.wake_arm(cn, "fx618-d1", URL, KEY)
    assert _updated(cn, "fx618-d1") == before  # arming is not a heartbeat
    assert rec_join.wake_state(cn, "fx618-d1") == {"armed": True, "host": "hooks.example.test", "wake_on": "addressed"}
    assert rec_join.wake_target(cn, "fx618-d1") == (URL, KEY)
    seats = [r for r in rec_join.select(cn, "fx618") if r.get("desk") == "fx618-d1"]
    assert seats and seats[0]["delivery_mode"] == "webhook"
    assert "endpoint_key" not in seats[0] and KEY not in repr(seats[0])
    rec_join.wake_off(cn, "fx618-d1")
    assert rec_join.wake_state(cn, "fx618-d1") == {"armed": False, "host": "", "wake_on": "addressed"}
    assert rec_join.wake_target(cn, "fx618-d1") is None
    mode = scalar_done(
        cn,
        "SELECT j.delivery_mode FROM seat j JOIN name d ON d.id = j.desk_id WHERE d.type = 'desk' AND d.name = %s",
        ("fx618-d1",),
    )
    assert mode == "websocket"


def test_two_desks_keep_two_keys(cn):
    _seat(cn, "fx618-d2")
    _seat(cn, "fx618-d3")
    rec_join.wake_arm(cn, "fx618-d2", URL + "-a", KEY + "-a")
    rec_join.wake_arm(cn, "fx618-d3", URL + "-b", KEY + "-b")
    assert rec_join.wake_target(cn, "fx618-d2") == (URL + "-a", KEY + "-a")
    assert rec_join.wake_target(cn, "fx618-d3") == (URL + "-b", KEY + "-b")


def test_watcher_rows_never_carry_the_key(cn):
    _seat(cn, "fx618-d4")
    rec_join.wake_arm(cn, "fx618-d4", URL, KEY)
    jid = scalar_done(
        cn,
        "SELECT MAX(j.id) FROM doing j JOIN name d ON d.id = j.desk_id WHERE d.type = 'desk' AND d.name = %s",
        ("fx618-d4",),
    )
    rows = call(cn, "mill_watcher_select", ["doing", int(jid)]) or []
    assert rows and all(KEY not in repr(r) for r in rows)


def test_reset_and_retire_forget_the_webhook(cn):
    from agent_coord.server.admin import catalog

    _seat(cn, "fx618-d5")
    rec_join.wake_arm(cn, "fx618-d5", URL, KEY)
    rec_join.reset(cn, "fx618", "fx618-d5")
    cn.commit()
    assert rec_join.wake_target(cn, "fx618-d5") is None
    _seat(cn, "fx618-d6")
    rec_join.wake_arm(cn, "fx618-d6", URL, KEY)
    with patch("agent_coord.server.admin.catalog.require_admin", lambda cn, desk: None):
        catalog.retire(cn, admin_desk(cn, "admin-desk"), {"slug": "fx618-d6", "confirm": "fx618-d6", "yes": True, "name_type": "desk"})
    cn.commit()
    key = scalar_done(
        cn,
        "SELECT j.endpoint_key FROM seat j JOIN name d ON d.id = j.desk_id WHERE d.type = 'desk' AND d.name = %s",
        ("fx618-d6",),
    )
    assert key is None


def test_arm_refuses_an_unjoined_desk_and_empty_values(cn):
    seed_names(cn, ("fx618-d7", "desk"))
    with pytest.raises(Exception) as ei:
        rec_join.wake_arm(cn, "fx618-d7", URL, KEY)
    assert "has not joined" in str(ei.value)
    _seat(cn, "fx618-d8")
    with pytest.raises(Exception) as ei:
        rec_join.wake_arm(cn, "fx618-d8", URL, "")
    assert "url and key required" in str(ei.value)


def test_pending_counts_the_desk_queue(cn):
    from agent_coord.server.records import push as rec_push

    _seat(cn, "fx618-d9")
    assert rec_push.pending(cn, "fx618-d9") == 0
    rec_push.put(cn, "fx618-d9", "hint", {"type": "todo", "id": 1}, "missed")
    rec_push.put(cn, "fx618-d9", "hint", {"type": "todo", "id": 2}, "missed")
    cn.commit()
    assert rec_push.pending(cn, "fx618-d9") == 2
    assert len(rec_push.take(cn, "fx618-d9")) == 2
