"""Round7 cold A/B: drop reply reads as a release; send echo carries the letter roster."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book
from agent_coord.server.records import hold as rec_hold


def _rows():
    return [
        {"id": 7, "resource": "build", "desk": "alice"},
        {"id": 8, "resource": "other", "desk": "bob"},
    ]


def test_drop_own_hold_reads_as_release():
    with patch.object(rec_hold, "find", return_value=_rows()), patch.object(
        rec_hold, "delete", return_value=[{"ok": 1}]
    ):
        out = rec_hold.drop(MagicMock(), "the-mill", "alice", "build")
    assert out["ok"] is True
    assert out["released"] is True
    assert out["owner"] is None
    assert out["was_owner"] == "alice"
    assert out["id"] == 7


def test_drop_someone_elses_hold_names_holder():
    with patch.object(rec_hold, "find", return_value=_rows()), patch.object(
        rec_hold, "may_drop_other", return_value=(False, "held by bob, not you")
    ), patch.object(rec_hold, "delete") as d, patch.object(
        rec_hold, "delete_other"
    ) as d2:
        out = rec_hold.drop(MagicMock(), "the-mill", "alice", "other")
    d.assert_not_called()
    d2.assert_not_called()
    assert out["ok"] is False and out["released"] is False
    assert out["owner"] == "bob"
    assert "bob" in out["reason"]


def test_drop_free_resource_owner_null_not_caller():
    with patch.object(rec_hold, "find", return_value=_rows()), patch.object(
        rec_hold, "delete"
    ):
        out = rec_hold.drop(MagicMock(), "the-mill", "alice", "nothing-here")
    assert out["released"] is False
    assert out["owner"] is None
    assert out["reason"] == "not held by you"


def test_drop_refused_by_sp():
    with patch.object(rec_hold, "find", return_value=_rows()), patch.object(
        rec_hold, "delete", return_value=[{"ok": 0}]
    ):
        out = rec_hold.drop(MagicMock(), "the-mill", "alice", "build")
    assert out["released"] is False
    assert out["owner"] == "alice"


def _book():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    return c


def test_h_drop_pokes_only_on_release():
    pokes: list = []
    with patch.object(rpc, "_poke", side_effect=lambda *a, **k: pokes.append(a)), patch.object(
        rec_hold, "drop", return_value={"ok": False, "released": False, "owner": None}
    ):
        rpc._h_drop(_book(), {"resource": "x"}, "the-mill", "alice")
    assert pokes == []
    with patch.object(rpc, "_poke", side_effect=lambda *a, **k: pokes.append(a)), patch.object(
        rec_hold, "drop", return_value={"ok": True, "released": True, "id": 7, "owner": None}
    ):
        out = rpc._h_drop(_book(), {"resource": "x"}, "the-mill", "alice")
    assert out["released"] is True
    assert len(pokes) == 1


def test_h_hold_reply_says_held():
    with patch.object(rpc, "_poke"), patch.object(
        rec_hold, "upsert", return_value=[{"ok": 1, "id": 7, "desk_id": 1, "desk": "alice"}]
    ):
        out = rpc._h_hold(_book(), {"resource": "x"}, "the-mill", "alice")
    assert out["held"] is True
    assert out["owner"] == "alice"


@pytest.mark.parametrize(
    "seats,want",
    [
        ([{"slot": "grok-tui", "slot_type": "roster"}], "grok-tui"),
        ([{"slot": "a", "slot_type": "roster"}, {"slot": "b", "slot_type": "roster"}], "Office"),
        ([], "Office"),
    ],
)
def test_send_without_roster_uses_seat_roster(seats, want):
    """#241: no --roster and no project means the seat's project, never the-mill."""
    dest_rows = [{"desk": "bob", "receipt": 0, "opened": None}]
    with patch(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        return_value=[{"kind": "desk", "dst": "bob"}],
    ), patch("agent_coord.server.records.name.get", return_value=2), patch(
        "agent_coord.server.records.name.ensure_roster"
    ), patch(
        "agent_coord.server.records.mail.insert", return_value=[{"id": 3, "created": "t"}]
    ) as ins, patch(
        "agent_coord.server.records.mail.dest_count", return_value=1
    ), patch(
        "agent_coord.server.records.mail.to_list", return_value=dest_rows
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs", return_value={}
    ), patch(
        "agent_coord.server.push.fanout", lambda *a, **k: None
    ), patch(
        "agent_coord.server.mail_push.push_mail", lambda *a, **k: None
    ), patch(
        "agent_coord.server.records.member.select", return_value=seats
    ):
        out = rpc._h_send(
            _book(), {"src": "alice", "dst": "bob", "body": "plain"}, "the-mill", "alice"
        )
    assert ins.call_args.args[1] == want  # no --roster: the letter carries the seat roster
    assert out["sender"] == {"deskId": "alice", "roster": want}
