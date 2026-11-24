"""Card 1288: a forced stale replace-body, on the tip book, names the editor and the UTC time and writes nothing.

mill_body_replace signals ``body:stale by DESK at YYYY-MM-DD HH:MM:SS`` (the stamp it compared, in UTC); the server
handler turns that into the one-line refusal with the next step. The duplicate-key lookup reads the same two fields.
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import body as rec_body
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import book_trust, seed_names

pytestmark = pytest.mark.sql

ROSTER = "b1288"


@pytest.fixture(scope="module", autouse=True)
def _desks(cn):
    seed_names(cn, (ROSTER, "roster"), ("s_ask", "desk"), ("s_peer", "desk"))


def _q(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        cn.commit()


def _row(cn, kind: str, item: int) -> dict:
    return _q(cn, f"SELECT body, body_updated, body_updater_id, created FROM {kind} WHERE id = %s", (item,))[0]


def _utc(cn, stamp) -> str:
    """The book stamp in UTC, to the second (the book clock is the session time zone)."""
    off = int(_q(cn, "SELECT TIMESTAMPDIFF(SECOND, NOW(), UTC_TIMESTAMP()) AS s")[0]["s"])
    return (stamp + timedelta(seconds=off)).strftime("%Y-%m-%d %H:%M:%S")


def _history_n(cn, kind: str, item: int) -> int:
    return int(_q(cn, "SELECT COUNT(*) AS n FROM activity_history WHERE type = %s AND activity_id = %s",
                  (kind, item))[0]["n"])


def _card(cn, need: str) -> int:
    doc = json.dumps({"slug": need, "detail": "first text"})
    return int(rec_todo.insert(cn, ROSTER, "s_ask", "open", doc)[0]["id"])


def _letter(cn) -> int:
    return int(rec_mail.insert(cn, ROSTER, "s_ask", "s_peer", "first text")[0]["id"])


def _force_stale(cn, kind: str, item: int, editor: str, me: str) -> tuple[str, dict, int, str]:
    """`editor` edits from the first stamp; `me` then replaces from that same old stamp through the handler."""
    first = _row(cn, kind, item)
    old_stamp = first["body_updated"] or first["created"]
    with book_trust(cn, "high"):
        rec_body.replace(cn, kind, item, editor, "their edit", old_stamp)
        after = _row(cn, kind, item)
        n0 = _history_n(cn, kind, item)
        body = {"type": kind, "id": item, "body": "my edit", "expected": old_stamp}
        with pytest.raises(CoordError) as err:
            rpc._h_replace_body(SimpleNamespace(_cn=cn), body, ROSTER, me)
        cn.rollback()
    at = _utc(cn, after["body_updated"])
    return str(err.value), after, n0, at


@pytest.mark.parametrize("kind", ["todo", "mail"])
def test_forced_stale_names_the_editor_the_utc_time_and_the_next_step(cn, kind):
    item = _card(cn, "stale-hint-peer") if kind == "todo" else _letter(cn)
    msg, after, n0, at = _force_stale(cn, kind, item, "s_peer", "s_ask")
    who = "s_peer"
    noun, read = (("card", f"mill todo {ROSTER} {item}") if kind == "todo"
                  else ("letter", f"mill mail-thread {item} --full"))
    assert msg == (
        f"body:stale: {noun} {item} changed after your read: {who} edited it at {at} UTC. Nothing was written. "
        f"Next: read it again ({read}), put your edit on top of that text, then run replace-body again. "
        f"Their old text: mill replace-body {kind} {item} --history"
    )
    assert _row(cn, kind, item) == after
    assert _history_n(cn, kind, item) == n0


def test_forced_stale_by_this_same_desk_says_another_session(cn):
    item = _card(cn, "stale-hint-self")
    msg, after, n0, at = _force_stale(cn, "todo", item, "s_ask", "s_ask")
    assert f": this desk (another session) edited it at {at} UTC. Nothing was written." in msg
    assert _row(cn, "todo", item) == after and _history_n(cn, "todo", item) == n0


@pytest.mark.parametrize("kind", ["todo", "mail"])
def test_duplicate_path_lookup_reads_the_editor_and_time(cn, kind):
    item = _card(cn, "stale-hint-lookup") if kind == "todo" else _letter(cn)
    assert rpc._body_editor(cn, kind, item) == (
        "s_ask", _utc(cn, _row(cn, kind, item)["created"]))
    first = _row(cn, kind, item)
    with book_trust(cn, "high"):
        rec_body.replace(cn, kind, item, "s_peer", "edited", first["created"])
    after = _row(cn, kind, item)
    assert rpc._body_editor(cn, kind, item) == ("s_peer", _utc(cn, after["body_updated"]))
    assert rpc._body_editor(cn, kind, 987654321) is None
