"""Card 1276: a reply stores the body stamp of the letter it answers. Row F229.

A root send leaves read_stamp NULL. A reply stores the answered letter's
body_updated, or created when that body was never replaced. Replacing the
answered letter afterwards keeps the reply on the old text through
activity_history. A second ensure adds nothing when the column is already there.
"""
from __future__ import annotations

import pytest

from agent_coord.install import migrate
from agent_coord.server.records import body as rec_body
from agent_coord.server.records.db import rows_done, scalar_done
from agent_coord.server.records.mail import text_at_stamp
from tests.server.records.conftest import seed_names
from tests.server.records.test_doing_only_tw_1207 import World, _dispatch

pytestmark = pytest.mark.sql

ME = "d1276-me"
PEER = "d1276-peer"
R = "r1276"


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for d in (ME, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d))
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d1276"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d1276home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


def _send(w, text: str, desk=PEER) -> dict:
    w.body.write_text(text, encoding="utf-8")
    return w.ok(["send", "--to-desk", ME if desk == PEER else PEER, "--body-file", str(w.body)], desk=desk)


def _reply(w, mid: int, text: str, desk=ME) -> dict:
    w.body.write_text(text, encoding="utf-8")
    return w.ok(["reply", str(mid), "--body-file", str(w.body)], desk=desk)


def _stamp(cn, mid: int):
    return scalar_done(cn, "SELECT IFNULL(body_updated, created) FROM mail WHERE id = %s", (int(mid),))


def _shown(value) -> str:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    return str(value)


def test_a_reply_keeps_the_text_it_read(w):
    root = _send(w, "root text 1276")
    assert "read_stamp" not in root
    assert scalar_done(w.cn, "SELECT read_stamp FROM mail WHERE id = %s", (int(root["id"]),)) is None
    reply = _reply(w, int(root["id"]), "reply text 1276")
    stored = scalar_done(w.cn, "SELECT read_stamp FROM mail WHERE id = %s", (int(reply["id"]),))
    parent_stamp = _stamp(w.cn, int(root["id"]))
    assert stored == parent_stamp
    assert reply["read_stamp"] == _shown(stored)
    assert text_at_stamp(w.cn, int(root["id"]), stored) == "root text 1276"
    rec_body.replace(w.cn, "mail", int(root["id"]), PEER, "root rewritten 1276", parent_stamp)
    assert scalar_done(w.cn, "SELECT body FROM mail WHERE id = %s", (int(root["id"]),)) == "root rewritten 1276"
    assert text_at_stamp(w.cn, int(root["id"]), stored) == "root text 1276"


def test_a_reply_after_a_replace_reads_that_stamp(w):
    root = _send(w, "first 1276")
    first = _stamp(w.cn, int(root["id"]))
    rec_body.replace(w.cn, "mail", int(root["id"]), PEER, "second 1276", first)
    second = _stamp(w.cn, int(root["id"]))
    assert second != first
    reply = _reply(w, int(root["id"]), "answer 1276")
    stored = scalar_done(w.cn, "SELECT read_stamp FROM mail WHERE id = %s", (int(reply["id"]),))
    assert stored == second
    assert text_at_stamp(w.cn, int(root["id"]), stored) == "second 1276"
    rec_body.replace(w.cn, "mail", int(root["id"]), PEER, "third 1276", second)
    assert text_at_stamp(w.cn, int(root["id"]), stored) == "second 1276"
    assert scalar_done(w.cn, "SELECT body FROM mail WHERE id = %s", (int(root["id"]),)) == "third 1276"


def test_ensure_read_stamp_is_quiet_when_the_column_exists(w):
    assert migrate._ensure_mail_read_stamp(w.cn) == []
    assert migrate._ensure_mail_read_stamp(w.cn) == []
    rows = rows_done(
        w.cn,
        "SELECT DATA_TYPE, DATETIME_PRECISION, IS_NULLABLE FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND COLUMN_NAME = 'read_stamp'",
    )
    assert len(rows) == 1
    assert str(rows[0]["DATA_TYPE"]).lower() == "datetime"
    assert int(rows[0]["DATETIME_PRECISION"]) == 6
    assert rows[0]["IS_NULLABLE"] == "YES"
