"""Card 1277: send names a webhook wake, and offline only when no wake is armed.

A desk with a webhook armed and no recent join is not called offline.
A desk with neither still gets the offline line. A failing run replaces the wake line.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.sql

from agent_coord.client.tokens import token_hash
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join
from tests import sql_book
from tests.server.records.conftest import seed_names

ME = "s1277-me"
HOOK = "s1277-hook"
QUIET = "s1277-quiet"
ROSTER = "r1277"
URL = "https://hooks.example.test/wake/s1277"
KEY = "s1277-key-0123456789"
FAIL = (
    "failing: 1 wake in a row since 2026-11-23T00:00Z, last 400 (no); "
    "letters wait for mill connect"
)


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, (ROSTER, "roster"), (ME, "desk"), (HOOK, "desk"), (QUIET, "desk"))
    rec_join.upsert(c, ROSTER, HOOK, "", token_hash=token_hash("seat-" + HOOK))
    rec_join.wake_arm(c, HOOK, URL, KEY)
    cur = c.cursor()
    cur.execute(
        "UPDATE seat h JOIN name n ON n.id = h.desk_id "
        "SET h.updated = %s WHERE n.type = 'desk' AND n.name = %s",
        (datetime.now() - timedelta(minutes=30), HOOK),
    )
    c.commit()
    cur.close()
    yield c
    c.close()


def _send(cn, monkeypatch) -> dict:
    monkeypatch.setattr("agent_coord.server.mail_push.push_mail", lambda *a, **k: None)
    return rpc._h_send(
        _Book(cn),
        {"src": ME, "dst": f"{HOOK},{QUIET}", "body": "hello"},
        ROSTER,
        ME,
    )


def test_an_armed_desk_wakes_and_a_quiet_desk_stays_offline(cn, monkeypatch):
    rec = _send(cn, monkeypatch)
    assert rec.get("id")
    lines = rec.get("warnings") or []
    text = "\n".join(lines)
    assert "example.test" not in text
    hook = [line for line in lines if HOOK in line]
    quiet = [line for line in lines if QUIET in line]
    assert hook and all("offline" not in line for line in hook)
    assert any("will wake by webhook" in line for line in hook)
    assert quiet and all("offline" in line for line in quiet)
    assert all(HOOK not in line for line in quiet)


def test_a_recent_failure_replaces_the_wake_line(cn, monkeypatch):
    monkeypatch.setattr(
        "agent_coord.server.wake.fail_note",
        lambda desk: FAIL if desk == HOOK else "",
    )
    rec = _send(cn, monkeypatch)
    lines = rec.get("warnings") or []
    hook = [line for line in lines if HOOK in line]
    assert hook
    assert all("will wake by webhook" not in line for line in hook)
    assert all("offline" not in line for line in hook)
    assert any("400" in line for line in hook)
    quiet = [line for line in lines if QUIET in line]
    assert quiet and all("offline" in line for line in quiet)
