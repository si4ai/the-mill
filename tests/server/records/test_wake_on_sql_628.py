"""#628 on a real book: join.wake_on is stored by the arm, read by wake_state,
and reset to addressed (the default, card 836) when the webhook is forgotten. Row F74 (wake-on)."""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.db import call
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

URL = "https://hooks.example.test/automations/webhook/fx628-routine"
KEY = "fx628-key-0123456789"


def test_wake_on_round_trip(cn):
    seed_names(cn, ("fx628", "roster"), ("fx628-d1", "desk"))
    rec_join.upsert(cn, "fx628", "fx628-d1", "", token_hash("seat-fx628"), None)
    cn.commit()
    rec_join.wake_arm(cn, "fx628-d1", URL, KEY)
    assert rec_join.wake_state(cn, "fx628-d1")["wake_on"] == "addressed"
    rec_join.wake_arm(cn, "fx628-d1", URL, KEY, wake_on="all")
    assert rec_join.wake_state(cn, "fx628-d1")["wake_on"] == "all"
    rec_join.wake_arm(cn, "fx628-d1", URL, KEY, wake_on="addressed")
    assert rec_join.wake_state(cn, "fx628-d1") == {"armed": True, "host": "hooks.example.test", "wake_on": "addressed"}
    assert rec_join.wake_target(cn, "fx628-d1") == (URL, KEY)
    with pytest.raises(Exception):
        call(cn, "mill_join_wake_arm", ["fx628-d1", URL, KEY, "room"])
    rec_join.wake_off(cn, "fx628-d1")
    assert rec_join.wake_state(cn, "fx628-d1")["wake_on"] == "addressed"
