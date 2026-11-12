"""#656: mill_mail_delete acts only for the letter's sender or an Admin desk.

Card 1125: mill_mail_update is gone. A letter's text changes through mill_body_replace; at limited trust only the sender or Admin.
"""
from __future__ import annotations

import mysql.connector
import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import body as rec_body
from agent_coord.server.records import mail
from agent_coord.server.records.db import call
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import book_trust, seed_names

REFUSED = "only the sender or an Admin desk"


def _letter(cn, body: str) -> int:
    seed_names(cn, ("ms_proj", "roster"), ("ms_from", "desk"), ("ms_to", "desk"), ("ms_other", "desk"), ("ms_admin", "desk"))
    return int(mail.insert(cn, "ms_proj", "ms_from", "ms_to", body)[0]["id"])


def _make_admin(cn, desk: str) -> None:
    did = int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,)))
    aid = 2  # the reserved Admin roster id (#722)
    cur = cn.cursor()
    cur.execute("INSERT IGNORE INTO member (name_id, desk_id) VALUES (%s, %s)", (aid, did))
    cur.close()
    cn.commit()


def _body(cn, mid: int):
    return scalar(cn, "SELECT body FROM mail WHERE id=%s", (mid,))


def _replace(cn, mid: int, desk: str, text: str):
    got = call(cn, "mill_mail_get", [mid])[0]
    return rec_body.replace(cn, "mail", mid, desk, text, got["body_updated"] or got["created"])


@pytest.mark.parametrize("caller", ["ms_other", "ms_to"])
def test_non_sender_replace_changes_nothing_at_limited_trust(cn, caller) -> None:
    mid = _letter(cn, "original")
    with book_trust(cn, "limited"), pytest.raises(Exception, match="body:rights"):
        _replace(cn, mid, caller, "rewritten")
    assert _body(cn, mid) == "original"


def test_missing_desk_replace_changes_nothing(cn) -> None:
    mid = _letter(cn, "original")
    with pytest.raises(Exception, match="body:no_desk"):
        _replace(cn, mid, "ms_nobody", "rewritten")
    assert _body(cn, mid) == "original"


@pytest.mark.parametrize("caller", ["ms_other", "ms_to", "ms_nobody"])
def test_non_sender_delete_leaves_the_row(cn, caller) -> None:
    mid = _letter(cn, "keep me")
    with pytest.raises(mysql.connector.Error) as ei:
        mail.delete(cn, mid, caller)
    assert REFUSED in str(ei.value)
    assert _body(cn, mid) == "keep me"
    assert scalar(cn, "SELECT COUNT(*) FROM mail_to WHERE type='mail' AND id=%s", (mid,)) >= 1
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (mid,)) is None


def test_sender_can_replace_and_delete(cn) -> None:
    mid = _letter(cn, "one")
    _replace(cn, mid, "ms_from", "two")
    assert _body(cn, mid) == "two"
    mail.delete(cn, mid, "ms_from")
    assert _body(cn, mid) is None


def test_admin_can_replace_and_delete(cn) -> None:
    mid = _letter(cn, "one")
    _make_admin(cn, "ms_admin")
    _replace(cn, mid, "ms_admin", "by admin")
    assert _body(cn, mid) == "by admin"
    mail.delete(cn, mid, "ms_admin")
    assert _body(cn, mid) is None


def test_replace_of_missing_letter_is_refused(cn) -> None:
    seed_names(cn, ("ms_proj", "roster"), ("ms_from", "desk"))
    with pytest.raises(Exception, match="body:no_such_item"):
        rec_body.replace(cn, "mail", 987654321, "ms_from", "x", "2026-01-01 00:00:00.000000")



