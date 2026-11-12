"""Card 1133: mill_body_replace, the body stamps and the todo body/meta split, on the tip book.

A replace writes the old text to activity_history, the new text and both stamps to the item, and act replace to its
activity row, in one transaction. It refuses a stale stamp, a desk with no rights at limited trust, a retired item and a no-op, and
writes nothing then; the no-op says plainly that the replace did nothing because the text is the same. History lists
the old texts newest first unless the caller asks for oldest first. A card's text is todo.body; slug and the rest are todo.meta; readers still get one document.
"""
from __future__ import annotations

import json

import pytest

from agent_coord.server.records import body as rec_body
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import call
from tests.server.records.conftest import book_trust, seed_names

pytestmark = pytest.mark.sql

ROSTER = "b1133"


@pytest.fixture(scope="module", autouse=True)
def _desks(cn):
    seed_names(cn, (ROSTER, "roster"), ("h_ask", "desk"), ("h_peer", "desk"), ("h_adm", "desk"))
    call(cn, "mill_member_admin_put", ["h_adm"])


def _q(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        cn.commit()


def _card(cn, need: str, detail: str) -> int:
    doc = json.dumps({"slug": need, "detail": detail, "progress": "1/3"})
    return int(rec_todo.insert(cn, ROSTER, "h_ask", "open", doc)[0]["id"])


def _card_row(cn, tid: int) -> dict:
    return _q(cn, "SELECT body, meta, body_updated, body_updater_id, created, updated, updated_id"
                  " FROM todo WHERE id = %s", (tid,))[0]


def _stamp(row: dict):
    return row["body_updated"] or row["created"]


def _desk(cn, name: str) -> int:
    return int(_q(cn, "SELECT id FROM name WHERE type = 'desk' AND name = %s", (name,))[0]["id"])


def _history_n(cn, kind: str, item: int) -> int:
    return int(_q(cn, "SELECT COUNT(*) AS n FROM activity_history WHERE type = %s AND activity_id = %s",
                  (kind, item))[0]["n"])


def test_card_write_stores_text_in_body_and_the_rest_in_meta(cn):
    text = 'line one\nline "two" \u00e9 \U0001f600'
    tid = _card(cn, "split-on-write", text)
    row = _card_row(cn, tid)
    assert row["body"] == text
    assert json.loads(row["meta"]) == {"slug": "split-on-write", "progress": "1/3"}
    assert row["body_updated"] is None and row["body_updater_id"] is None
    got = rec_todo.find(cn, ROSTER, "split-on-write")
    assert int(got["id"]) == tid
    fields = rec_todo.unpack(str(got.get("body") or ""), tid)
    assert fields["detail"] == text and fields["need_id"] == "split-on-write" and fields["progress"] == "1/3"


def test_note_append_stamps_text_but_meta_only_write_does_not(cn):
    tid = _card(cn, "note-stamp", "first")
    doc = json.loads(str(rec_todo.find(cn, ROSTER, "note-stamp")["body"]))
    doc["eta_at"] = "2026-11-12T10:00:00"
    rec_todo.update(cn, tid, "h_peer", "", "", json.dumps(doc))
    row = _card_row(cn, tid)
    assert row["body"] == "first" and row["body_updated"] is None  # meta only: no text stamp
    assert json.loads(row["meta"])["eta_at"] == "2026-11-12T10:00:00"
    doc["detail"] = "first\nsecond"
    rec_todo.update(cn, tid, "h_peer", "", "", json.dumps(doc))
    row = _card_row(cn, tid)
    assert row["body"] == "first\nsecond"
    assert row["body_updated"] is not None and row["body_updater_id"] == _desk(cn, "h_peer")


def test_replace_card_writes_history_text_stamps_and_act(cn):
    tid = _card(cn, "replace-card", "old text")
    before = _card_row(cn, tid)
    out = rec_body.replace(cn, "todo", tid, "h_ask", "new text", _stamp(before))
    assert out["op"] == "replaced" and int(out["id"]) == tid
    after = _card_row(cn, tid)
    asker = _desk(cn, "h_ask")
    assert after["body"] == "new text"
    assert json.loads(after["meta"]) == json.loads(before["meta"])  # meta untouched
    assert after["body_updated"] == out["body_updated"] and after["body_updater_id"] == asker
    assert after["updated"] == out["body_updated"] and after["updated_id"] == asker
    hist = rec_body.history(cn, "todo", tid)
    assert len(hist) == 1
    h = hist[0]
    assert int(h["id"]) == int(out["history_id"])
    assert h["old_body"] == "old text" and h["old_updated"] == before["created"]
    assert h["old_updater"] == "h_ask" and h["replaced_by"] == "h_ask"
    assert h["replaced_at"] == out["body_updated"]
    act = _q(cn, "SELECT act, desk_id, bytes FROM activity WHERE type = 'todo' AND id = %s", (tid,))[0]
    assert act["act"] == "replace" and int(act["desk_id"]) == asker and int(act["bytes"]) == len(b"new text")
    # The card document readers parse carries the new text.
    fields = rec_todo.unpack(str(rec_todo.find(cn, ROSTER, "replace-card")["body"]), tid)
    assert fields["detail"] == "new text" and fields["progress"] == "1/3"


def test_second_replace_chains_old_updated_to_the_first(cn):
    tid = _card(cn, "replace-chain", "v1")
    first = rec_body.replace(cn, "todo", tid, "h_ask", "v2", _stamp(_card_row(cn, tid)))
    second = rec_body.replace(cn, "todo", tid, "h_adm", "v3", first["body_updated"])
    hist = rec_body.history(cn, "todo", tid)
    assert [h["old_body"] for h in hist] == ["v2", "v1"]  # newest first by default
    assert hist[0]["old_updated"] == first["body_updated"] and hist[0]["old_updater"] == "h_ask"
    assert hist[0]["replaced_by"] == "h_adm" and second["old_updated"] == first["body_updated"]
    assert _card_row(cn, tid)["body"] == "v3"


def test_history_is_newest_first_and_oldest_on_request(cn):
    tid = _card(cn, "history-order", "v1")
    stamp = _stamp(_card_row(cn, tid))
    for text in ("v2", "v3", "v4"):
        stamp = rec_body.replace(cn, "todo", tid, "h_ask", text, stamp)["body_updated"]
    newest = ["v3", "v2", "v1"]
    assert [h["old_body"] for h in rec_body.history(cn, "todo", tid)] == newest
    assert [h["old_body"] for h in rec_body.history(cn, "todo", tid, order="newest")] == newest
    assert [h["old_body"] for h in call(cn, "mill_body_history", ["todo", tid, None])] == newest
    assert [h["old_body"] for h in rec_body.history(cn, "todo", tid, order="oldest")] == newest[::-1]
    with pytest.raises(Exception, match="body:order"):
        rec_body.history(cn, "todo", tid, order="sideways")
    with pytest.raises(Exception, match="body:order"):
        rec_body.history(cn, "todo", tid, order="newest-first")


def test_unchanged_refusal_says_the_replace_did_nothing(cn):
    tid = _card(cn, "unchanged-message", "same words")
    with pytest.raises(Exception) as err:
        rec_body.replace(cn, "todo", tid, "h_ask", "same words", _stamp(_card_row(cn, tid)))
    assert "body:unchanged: replace did nothing: the new text is the same as the current text" in str(err.value)


def test_case_only_change_replaces_because_compare_is_binary(cn):
    tid = _card(cn, "case-only", "Same Words")
    out = rec_body.replace(cn, "todo", tid, "h_ask", "same words", _stamp(_card_row(cn, tid)))
    assert out["op"] == "replaced"
    assert _card_row(cn, tid)["body"] == "same words"
    assert rec_body.history(cn, "todo", tid)[0]["old_body"] == "Same Words"


@pytest.mark.parametrize(
    "case, code",
    [("stale", "body:stale"), ("rights", "body:rights"), ("unchanged", "body:unchanged"),
     ("missing", "body:no_such_item"), ("kind", "body:type"), ("null_stamp", "body:stale")],
)
def test_card_replace_refusals_write_nothing(cn, case, code):
    tid = _card(cn, f"refuse-{case.replace('_', '-')}", "keep me")
    row = _card_row(cn, tid)
    act0 = _q(cn, "SELECT act, updated FROM activity WHERE type = 'todo' AND id = %s", (tid,))[0]
    args = {"kind": "todo", "item": tid, "desk": "h_ask", "text": "changed", "expected": _stamp(row)}
    if case == "stale":
        rec_body.replace(cn, "todo", tid, "h_ask", "first edit", _stamp(row))
        row = _card_row(cn, tid)
        act0 = _q(cn, "SELECT act, updated FROM activity WHERE type = 'todo' AND id = %s", (tid,))[0]
        args["expected"] = row["created"]  # the stamp before the first edit
    elif case == "rights":
        args["desk"] = "h_peer"
    elif case == "unchanged":
        args["text"] = "keep me"
    elif case == "missing":
        args["item"] = 987654321
    elif case == "kind":
        args["kind"] = "hold"
    elif case == "null_stamp":
        args["expected"] = None
    n0 = _history_n(cn, "todo", tid)
    # body:rights is the limited-trust rule (admin.md section 2); every other refusal holds at either level.
    with book_trust(cn, "limited" if case == "rights" else "high"), pytest.raises(Exception, match=code):
        rec_body.replace(cn, args["kind"], args["item"], args["desk"], args["text"], args["expected"])
    assert _card_row(cn, tid) == row
    assert _history_n(cn, "todo", tid) == n0
    assert _q(cn, "SELECT act, updated FROM activity WHERE type = 'todo' AND id = %s", (tid,))[0] == act0


def test_retired_card_is_refused(cn):
    tid = _card(cn, "replace-retired", "gone")
    rec_todo.retire(cn, tid, "h_ask")
    row = _card_row(cn, tid)
    with pytest.raises(Exception, match="body:deleted"):
        rec_body.replace(cn, "todo", tid, "h_ask", "back", _stamp(row))
    assert _history_n(cn, "todo", tid) == 0


def test_mail_replace_sender_or_admin_and_receipts_untouched(cn):
    mid = int(rec_mail.insert(cn, ROSTER, "h_ask", "h_peer", "letter v1", receipt=1)[0]["id"])
    to0 = _q(cn, "SELECT desk_id, opened, receipt, asked, created FROM mail_to WHERE type = 'mail' AND id = %s", (mid,))
    got = call(cn, "mill_mail_get", [mid])[0]
    assert got["body_updated"] is None
    with book_trust(cn, "limited"), pytest.raises(Exception, match="body:rights"):
        rec_body.replace(cn, "mail", mid, "h_peer", "not mine", got["created"])
    first = rec_body.replace(cn, "mail", mid, "h_ask", "letter v2", got["created"])
    second = rec_body.replace(cn, "mail", mid, "h_adm", "letter v3", first["body_updated"])
    row = _q(cn, "SELECT body, body_updated, body_updater_id FROM mail WHERE id = %s", (mid,))[0]
    assert row["body"] == "letter v3" and row["body_updated"] == second["body_updated"]
    assert row["body_updater_id"] == _desk(cn, "h_adm")
    assert call(cn, "mill_mail_get", [mid])[0]["body_updated"] == second["body_updated"]
    assert [h["old_body"] for h in rec_body.history(cn, "mail", mid, order="oldest")] == ["letter v1", "letter v2"]
    assert _q(cn, "SELECT desk_id, opened, receipt, asked, created FROM mail_to WHERE type = 'mail' AND id = %s",
              (mid,)) == to0
    assert _q(cn, "SELECT act FROM activity WHERE type = 'mail' AND id = %s", (mid,))[0]["act"] == "replace"


def test_unique_old_updated_refuses_a_second_row_for_one_version(cn):
    tid = _card(cn, "unique-version", "a")
    out = rec_body.replace(cn, "todo", tid, "h_ask", "b", _stamp(_card_row(cn, tid)))
    h = rec_body.history(cn, "todo", tid)[0]
    cur = cn.cursor()
    try:
        with pytest.raises(Exception, match="1062|Duplicate"):
            cur.execute(
                "INSERT INTO activity_history (type, activity_id, old_body, old_updated, old_updater_id, replaced_by)"
                " VALUES ('todo', %s, 'x', %s, %s, %s)",
                (tid, h["old_updated"], h["old_updater_id"], h["replaced_by_id"]),
            )
    finally:
        cn.rollback()
        cur.close()
    assert out["old_updated"] == h["old_updated"]


def test_hard_delete_of_the_activity_row_takes_its_history(cn):
    tid = _card(cn, "cascade", "a")
    rec_body.replace(cn, "todo", tid, "h_ask", "b", _stamp(_card_row(cn, tid)))
    assert _history_n(cn, "todo", tid) == 1
    cur = cn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cur.execute("DELETE FROM label WHERE type = 'todo' AND id = %s", (tid,))
        cur.execute("DELETE FROM tree WHERE type = 'todo' AND id = %s", (tid,))
        cur.execute("DELETE FROM activity WHERE type = 'todo' AND id = %s", (tid,))
        cn.commit()
    finally:
        cur.close()
    assert _history_n(cn, "todo", tid) == 0


def test_unsplit_row_reads_as_before_and_replace_splits_it(cn):
    """A row the migration has not split yet (meta NULL) reads as its document and is split by a replace."""
    tid = _card(cn, "unsplit", "x")
    doc = json.dumps({"slug": "unsplit", "detail": "legacy text", "aliases": ["old-name"]})
    cur = cn.cursor()
    try:
        cur.execute("UPDATE todo SET body = %s, meta = NULL WHERE id = %s", (doc, tid))
        cn.commit()
    finally:
        cur.close()
    fields = rec_todo.unpack(str(rec_todo.find(cn, ROSTER, "unsplit")["body"]), tid)
    assert fields["detail"] == "legacy text" and fields["aliases"] == ["old-name"]
    rec_body.replace(cn, "todo", tid, "h_ask", "fresh text", _stamp(_card_row(cn, tid)))
    row = _card_row(cn, tid)
    assert row["body"] == "fresh text"
    assert json.loads(row["meta"]) == {"slug": "unsplit", "aliases": ["old-name"]}
    assert rec_body.history(cn, "todo", tid)[0]["old_body"] == "legacy text"
