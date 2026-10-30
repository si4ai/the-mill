"""MAIL is pushed without a watcher. The sync report is a separate log of those pushes."""

from __future__ import annotations

from pathlib import Path

from agent_coord.server import push as hub
from agent_coord.server.mail_push import BODY_CAP, compact_mail, compact_receipt, push_mail
from agent_coord.server.records import opened as rec_opened
from agent_coord.server.records import push as rec_push

ROOT = Path(__file__).resolve().parents[2]


def test_watcher_type_has_no_mail():
    text = (ROOT / "agent_coord" / "server" / "sql" / "tables.sql").read_text(encoding="utf-8")
    body = text.split("CREATE TABLE IF NOT EXISTS watcher", 1)[1].split("CREATE TABLE", 1)[0]
    assert "ENUM('todo','doing','hold','score')" in body
    assert "'name'" not in body
    assert "'mail'" not in body


def test_name_is_not_a_watcher_or_activity_target():
    sql = ROOT / "agent_coord" / "server" / "sql"
    member = (sql / "sp_member.sql").read_text(encoding="utf-8")
    assert "mill_watcher_put('name'" not in member
    assert "mill_watcher_delete('name'" not in member
    join = (sql / "sp_join.sql").read_text(encoding="utf-8")
    assert "mill_watcher_put('name'" not in join
    assert "WHEN 'name'" not in join
    assert "ra.type = 'name'" not in join
    activity = (sql / "sp_activity.sql").read_text(encoding="utf-8")
    assert "ENUM('todo','join','hold','score','name')" not in activity
    assert "SELECT 'name'" not in activity
    assert "CREATE PROCEDURE mill_name_poke" not in activity
    names = (sql / "sp_name.sql").read_text(encoding="utf-8")
    assert "mill_name_poke" not in names
    listing = (ROOT / "agent_coord" / "server" / "middleware.py").read_text(encoding="utf-8")
    assert "WHEN 'name'" not in listing
    assert "ra.type = 'name'" not in listing


def test_mail_send_does_not_plant_a_watcher():
    text = (ROOT / "agent_coord" / "server" / "sql" / "sp_mail.sql").read_text(encoding="utf-8")
    body = text.split("CREATE PROCEDURE mill_mail_to_put", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "mill_watcher_put" not in body


def test_compact_mail_is_for_one_dest_and_cuts_the_body():
    letter = {
        "id": 9,
        "created": "2026-09-27T00:00:00",
        "desk": "sender",
        "sender_roster": "the-mill",
        "body": "m" * (BODY_CAP + 40),
    }
    dests = [
        {"desk": "one", "receipt": 1, "opened": None},
        {"desk": "two", "receipt": 0, "opened": "2026-09-27T01:00:00"},
    ]
    item = compact_mail(letter, dests, "two")
    assert item["kind"] == "mail"
    assert item["id"] == 9
    assert item["sender"] == "sender"
    assert item["mail_tos"] == ["one", "two"]
    assert item["roster_id"] == "the-mill"
    assert item["opened"] == "2026-09-27T01:00:00"
    assert item["receipt"] == 0
    assert len(item["body"]) == BODY_CAP
    assert item["body_trunc"] is True and item["read"] == "mill mail-thread 9"  # #584


def test_compact_receipt_names_the_opener_and_the_open_time():
    item = compact_receipt(
        {
            "id": 9,
            "created": "2026-09-27T00:00:00",
            "body": "hello",
            "desk": "one",
            "opened": "2026-09-27T02:00:00",
        }
    )
    assert item == {
        "kind": "receipt",
        "id": 9,
        "created": "2026-09-27T00:00:00",
        "body": "hello",
        "mail_to": "one",
        "opened": "2026-09-27T02:00:00",
    }


def test_emit_records_sent_missed_and_error(monkeypatch):
    """#832: the row is put first, always as missed; a raised live send marks it error.
    A send that reaches a socket marks it sent from the broadcast (row id in notify)."""
    logged: list[tuple] = []
    marks: list[tuple] = []
    monkeypatch.setattr(hub.HUB, "rooms", {})
    monkeypatch.setattr(
        rec_push,
        "put",
        lambda cn, desk, kind, payload, outcome: logged.append((desk, kind, outcome, payload["id"]))
        or [{"id": 70 + len(logged)}],
    )
    monkeypatch.setattr(rec_push, "mark", lambda cn, rid, outcome: marks.append((rid, outcome)) or 1)
    assert hub.emit(object(), "DESK_one", "mail", {"id": 9}) == "missed"
    hub.HUB.rooms["DESK_one"] = {object()}
    rows: list = []
    monkeypatch.setattr(hub.HUB, "notify", lambda desk, frame, row=None: rows.append(row))
    assert hub.emit(object(), "DESK_one", "mail", {"id": 9}) == "sent"
    assert rows == [("DESK_one", 72)]

    def _boom(desk, frame, row=None):
        raise RuntimeError("down")

    monkeypatch.setattr(hub.HUB, "notify", _boom)
    assert hub.emit(object(), "DESK_one", "mail", {"id": 9}) == "error"
    assert [row[2] for row in logged] == ["missed", "missed", "missed"]
    assert marks == [(73, "error")]


def test_take_merges_outcome_and_time(monkeypatch):
    monkeypatch.setattr(
        rec_push,
        "call",
        lambda cn, name, args: [
            {
                "kind": "mail",
                "payload": '{"kind":"mail","id":9,"body":"hi"}',
                "outcome": "missed",
                "created": "2026-09-27T03:00:00",
            }
        ],
    )
    item = rec_push.take(object(), "DESK_one")[0]
    assert item["kind"] == "mail"
    assert item["outcome"] == "missed"
    assert item["time"] == "2026-09-27T03:00:00"
    assert item["id"] == 9
    assert item["body"] == "hi"


def test_push_mail_emits_one_item_per_dest(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(
        "agent_coord.server.records.mail.letter_row",
        lambda cn, mail_id: {"id": mail_id, "created": "t", "desk": "DESK_sender", "body": "hi"},
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list",
        lambda cn, mail_id: [
            {"desk": "DESK_one", "receipt": 0, "opened": None},
            {"desk": "DESK_two", "receipt": 1, "opened": None},
        ],
    )
    monkeypatch.setattr(
        "agent_coord.server.push.emit",
        lambda cn, desk, kind, payload, **kw: sent.append(desk) or "missed",
    )
    push_mail(object(), 9)
    assert sent == ["DESK_one", "DESK_two"]


def test_open_pushes_a_receipt_only_when_flagged(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        rec_opened,
        "call",
        lambda cn, name, args: [{"push_receipt": 0, "id": args[0]}],
    )
    monkeypatch.setattr(
        "agent_coord.server.mail_push.push_receipt",
        lambda cn, row: calls.append(row),
    )
    rec_opened.insert(object(), 9, "DESK_one")
    assert calls == []
    monkeypatch.setattr(
        rec_opened,
        "call",
        lambda cn, name, args: [{"push_receipt": 1, "id": 9, "sender": "DESK_sender"}],
    )
    rec_opened.insert(object(), 9, "DESK_one")
    assert calls[0]["sender"] == "DESK_sender"


def test_failed_command_keeps_sync_on_the_error():
    from agent_coord.__main__ import _format_error
    from agent_coord.helpers.errors import CoordError

    item = {"kind": "mail", "id": 9, "outcome": "missed"}
    err = CoordError("send: To required", sync=[item])
    text = _format_error(err)
    assert "send: To required" in text
    assert '"kind": "mail"' in text
    assert _format_error(CoordError("send: To required")) == "send: To required"


def test_open_procedure_pushes_a_receipt_only_on_the_first_open():
    text = (ROOT / "agent_coord" / "server" / "sql" / "sp_opened.sql").read_text(encoding="utf-8")
    assert "push_receipt" in text
    assert "v_prev IS NULL" in text
    assert "v_receipt <> 0" in text
