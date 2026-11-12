"""Card 1125: replace-body argv, the desk-local last read, and the unchanged sentence."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import body_read
from agent_coord.client.outbound import body_from_args
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill.rpc import _todo_card
from agent_coord.server.records.mail import public_mail

ROOT = Path(__file__).resolve().parents[2]
UNCHANGED = "body:unchanged: replace did nothing: the new text is the same as the current text"


def test_mail_update_is_gone():
    sql = (ROOT / "agent_coord" / "server" / "sql" / "sp_mail.sql").read_text(encoding="utf-8")
    py = (ROOT / "agent_coord" / "server" / "records" / "mail.py").read_text(encoding="utf-8")
    assert "CREATE PROCEDURE mill_mail_update" not in sql
    assert "DROP PROCEDURE IF EXISTS mill_mail_update" in sql
    assert "def update(" not in py


def _parse(argv):
    return _build_parser().parse_args(argv)


def test_inline_text_is_the_body():
    body = body_from_args(_parse(["replace-body", "mail", "12", "new text"]))
    assert body["verb"] == "replace-body"
    assert body["type"] == "mail" and body["id"] == 12 and body["body"] == "new text"
    assert "history" not in body and "project" not in body and "expected" not in body


def test_file_keeps_spaces(tmp_path):
    path = tmp_path / "body.txt"
    path.write_text("  spaced \n", encoding="utf-8")
    body = body_from_args(_parse(["replace-body", "todo", "1125", "--body-file", str(path)]))
    assert body["type"] == "todo" and body["body"] == "  spaced \n"


def test_file_strips_only_a_bom(tmp_path):
    path = tmp_path / "body.txt"
    path.write_text("\ufeffhello", encoding="utf-8")
    body = body_from_args(_parse(["replace-body", "mail", "3", "--body-file", str(path)]))
    assert body["body"] == "hello"


def test_both_text_and_file_are_refused(tmp_path):
    path = tmp_path / "body.txt"
    path.write_text("x", encoding="utf-8")
    args = _parse(["replace-body", "mail", "3", "inline", "--body-file", str(path)])
    with pytest.raises(CoordError, match="not both"):
        body_from_args(args)


def test_neither_text_nor_file_is_refused():
    with pytest.raises(CoordError, match="pass the text or --body-file"):
        body_from_args(_parse(["replace-body", "mail", "3"]))


def test_empty_text_is_no_text():
    with pytest.raises(CoordError, match="body:no_text"):
        body_from_args(_parse(["replace-body", "mail", "3", ""]))


def test_history_sends_order_and_no_body():
    body = body_from_args(_parse(["replace-body", "todo", "9", "--history", "--order", "oldest"]))
    assert body["history"] is True and body["order"] == "oldest" and "body" not in body


def test_history_with_text_is_refused():
    with pytest.raises(CoordError, match="no new text"):
        body_from_args(_parse(["replace-body", "mail", "3", "x", "--history"]))


def test_unchanged_sentence_is_the_office_message():
    sql = (ROOT / "agent_coord" / "server" / "sql" / "sp_body.sql").read_text(encoding="utf-8")
    assert UNCHANGED in sql
    assert body_read.UNCHANGED == UNCHANGED
    assert body_read.map_refusal(UNCHANGED, "mail", 3) == UNCHANGED


def test_stale_names_the_reread_and_unchanged_does_not():
    assert body_read.map_refusal("body:stale", "mail", 3) == (
        "body:stale: read it again: mill mail-thread 3 --full"
    )
    assert body_read.map_refusal("body:stale", "todo", 9, "the-mill") == (
        "body:stale: read it again: mill todo the-mill 9"
    )


def test_last_read_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    body_read.save_stamp("grok-tui", "mail", 12, "2026-11-11T20:08:36.673094Z")
    assert body_read.load_stamp("grok-tui", "mail", 12) == "2026-11-11 20:08:36.673094"
    assert body_read.load_stamp("other", "mail", 12) == ""


def test_never_read_refuses_before_a_call(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    body = {"verb": "replace-body", "type": "todo", "id": 1125, "body": "x", "owner": "grok-tui"}
    with pytest.raises(CoordError, match=r"read it first: mill todo ROSTER 1125"):
        body_read.prepare_replace(body)


def test_expected_comes_from_the_acting_desk(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    body_read.save_stamp("grok-tui", "mail", 9, "2026-11-11 20:08:36.673094")
    body = {
        "verb": "replace-body",
        "type": "mail",
        "id": 9,
        "body": "n",
        "owner": "other",
        "sender_desk": "grok-tui",
    }
    body_read.prepare_replace(body)
    assert body["expected"] == "2026-11-11 20:08:36.673094"


def test_history_does_not_ask_for_a_stamp(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    body = {"verb": "replace-body", "type": "mail", "id": 9, "history": True, "owner": "grok-tui"}
    body_read.prepare_replace(body)
    assert "expected" not in body


def test_a_full_letter_is_remembered_and_a_cut_one_is_not(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _parse(["mail-thread", "4", "--full"])
    row = {
        "ok": True,
        "result": {
            "chain": [
                {"id": 4, "created": "2026-11-11 01:02:03.000001", "body": "whole"},
                {"id": 5, "created": "2026-11-11 01:02:04", "body": "cut", "body_trunc": True},
            ]
        },
    }
    body_read.remember("grok-tui", args, row)
    assert body_read.load_stamp("grok-tui", "mail", 4) == "2026-11-11 01:02:03.000001"
    assert body_read.load_stamp("grok-tui", "mail", 5) == ""


def test_an_edited_letter_stores_the_edit_stamp(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _parse(["mail-thread", "4", "--full"])
    row = {
        "ok": True,
        "result": {
            "chain": [
                {
                    "id": 4,
                    "created": "2026-11-11 01:02:03",
                    "body_updated": "2026-11-11 04:05:06.100000",
                    "body": "now",
                }
            ]
        },
    }
    body_read.remember("grok-tui", args, row)
    assert body_read.load_stamp("grok-tui", "mail", 4) == "2026-11-11 04:05:06.100000"


def test_a_card_peek_is_remembered_and_the_board_is_not(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    peek = _parse(["todo", "the-mill", "1125"])
    body_read.remember(
        "grok-tui",
        peek,
        {"ok": True, "result": [{"id": 1125, "body_stamp": "2026-11-11 01:00:00"}]},
    )
    board = _parse(["todo", "the-mill"])
    body_read.remember(
        "grok-tui",
        board,
        {"ok": True, "result": [{"id": 7, "body_stamp": "2026-11-11 02:00:00"}]},
    )
    assert body_read.load_stamp("grok-tui", "todo", 1125) == "2026-11-11 01:00:00"
    assert body_read.load_stamp("grok-tui", "todo", 7) == ""


def test_a_replace_stores_the_new_stamp(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _parse(["replace-body", "mail", "4", "next"])
    body_read.remember(
        "grok-tui",
        args,
        {"ok": True, "result": {"type": "mail", "id": 4, "body_updated": "2026-11-11 09:00:00.000001", "op": "replaced"}},
    )
    assert body_read.load_stamp("grok-tui", "mail", 4) == "2026-11-11 09:00:00.000001"


def test_unedited_letter_has_no_edit_line():
    out = public_mail({"id": 1, "created": "2026-11-11 01:00:00", "desk": "a", "body": "hi"}, [])
    assert "edited" not in out and "body_updated" not in out


def test_edited_letter_names_the_desk_and_time():
    out = public_mail(
        {
            "id": 1,
            "created": "2026-11-11 01:00:00",
            "desk": "a",
            "body": "hi",
            "body_updated": "2026-11-11 02:00:00.100000",
            "body_updater": "builder",
        },
        [],
    )
    assert out["edited"] == "edited by builder at 2026-11-11 02:00:00.100000"
    assert out["body_updater"] == "builder"
    assert "old_body" not in out


def test_card_stamp_is_absent_until_the_row_has_one():
    bare = _todo_card(
        {"id": 1, "assigned": "w", "creator": "a"},
        "unit",
        "open",
        {"need_id": "n", "detail": "d", "progress": ""},
    )
    assert "body_stamp" not in bare and "edited" not in bare
    stamped = _todo_card(
        {"id": 1, "created": "2026-11-11 01:00:00", "assigned": "w", "creator": "a"},
        "unit",
        "open",
        {"need_id": "n", "detail": "d", "progress": ""},
    )
    assert stamped["body_stamp"] == "2026-11-11 01:00:00" and "edited" not in stamped
    edited = _todo_card(
        {
            "id": 1,
            "created": "2026-11-11 01:00:00",
            "body_updated": "2026-11-11 03:00:00",
            "body_updater": "builder",
        },
        "unit",
        "open",
        {"need_id": "n", "detail": "d", "progress": ""},
    )
    assert edited["edited"] == "edited by builder at 2026-11-11 03:00:00"
    assert edited["body_stamp"] == "2026-11-11 03:00:00"
    assert "old_body" not in edited
