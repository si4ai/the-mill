"""Card 866: done_when, pass --evidence, cached glance, version warning. Row F143."""
from __future__ import annotations

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client.outbound import body_from_args
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill.rpc import _todo_card
from agent_coord.server.beta_client import read_cached_glance, shape_glance


def _card(row, fields):
    return _todo_card(row, "unit", "open", fields)


def test_pass_sends_evidence():
    args = _build_parser().parse_args(["pass", "unit", "n1", "--evidence", "the log"])
    body = body_from_args(args)
    assert body["step"] == "ship"
    assert body["evidence"] == "the log"


def test_blank_evidence_is_omitted():
    args = _build_parser().parse_args(["pass", "unit", "n1", "--evidence", "  "])
    body = body_from_args(args)
    assert "evidence" not in body


def test_evidence_over_2000_is_refused():
    args = _build_parser().parse_args(["pass", "unit", "n1", "--evidence", "x" * 2001])
    with pytest.raises(CoordError, match="nothing changed"):
        body_from_args(args)


def test_back_sends_evidence_for_the_server_to_drop():
    args = _build_parser().parse_args(["pass", "unit", "n1", "--back", "--evidence", "nope"])
    body = body_from_args(args)
    assert body["step"] == "back"
    assert body["evidence"] == "nope"


def test_card_shows_done_when_from_the_row():
    card = _card(
        {"id": 1, "done_when": "tests green"},
        {"need_id": "n", "detail": "d", "progress": "", "payload": {"done_when": "from body"}},
    )
    assert card["done_when"] == "tests green"


def test_card_omits_done_when_when_the_row_has_none():
    card = _card(
        {"id": 1},
        {"need_id": "n", "detail": "d", "progress": "", "payload": {"done_when": "from body"}},
    )
    assert "done_when" not in card


def test_create_sends_done_when():
    args = _build_parser().parse_args(["create", "todo", "unit", "n1", "--done-when", "tests green"])
    body = body_from_args(args)
    assert body["verb"] == "open"
    assert body["done_when"] == "tests green"


def test_create_omits_a_blank_done_when():
    args = _build_parser().parse_args(["create", "todo", "unit", "n1", "--done-when", "  "])
    body = body_from_args(args)
    assert "done_when" not in body


def test_create_refuses_a_long_done_when():
    args = _build_parser().parse_args(["create", "todo", "unit", "n1", "--done-when", "y" * 1001])
    with pytest.raises(CoordError, match="nothing stored"):
        body_from_args(args)


def test_note_sends_done_when_and_a_blank_clears_it():
    args = _build_parser().parse_args(["note", "unit", "n1", "--done-when", "  "])
    body = body_from_args(args)
    assert body["verb"] == "note"
    assert body["done_when"] == ""


def test_note_refuses_a_long_done_when():
    args = _build_parser().parse_args(["note", "unit", "n1", "--done-when", "y" * 1001])
    with pytest.raises(CoordError, match="nothing changed"):
        body_from_args(args)


def test_glance_sends_the_command():
    args = _build_parser().parse_args(["glance"])
    body = body_from_args(args)
    assert body["verb"] == "glance"


def test_glance_keeps_two_sets_and_drops_unread():
    got = shape_glance(
        [{
            "id": 1, "at": "t", "refresh_us": 1, "present": 2, "held": 0,
            "open_n": 1, "claimed_n": 0, "parked_n": 0, "shipped_n": 0, "done_n": 0,
            "letters_1d": 3, "card_moves_1d": 0, "doings_1d": 0, "holds_1d": 0, "points_1d": 0,
            "open_votes": 4, "unread": 99,
        }],
        [{"seq": 1, "at": "t", "kind": "letter", "ref": 5, "desk": "a"}],
    )
    assert got["cache"]["present"] == 2
    assert got["cache"]["open_votes"] == 4
    assert "unread" not in got["cache"]
    assert got["activity"] == [{"seq": 1, "at": "t", "kind": "letter", "ref": 5, "desk": "a"}]


def test_glance_caps_activity_at_30():
    rows = [{"seq": i, "at": "t", "kind": "card", "ref": i, "desk": "a"} for i in range(40)]
    assert len(shape_glance([], rows)["activity"]) == 30


def test_glance_skips_an_unknown_kind():
    got = shape_glance(
        [{
            "id": 1, "at": "t", "refresh_us": 1, "present": 2, "held": 0,
            "open_n": 0, "claimed_n": 0, "parked_n": 0, "shipped_n": 0, "done_n": 0,
            "letters_1d": 0, "card_moves_1d": 0, "doings_1d": 0, "holds_1d": 0, "points_1d": 0,
        }],
        [
            {"seq": 1, "at": "t", "kind": "letter", "ref": 5, "desk": "a"},
            {"seq": 2, "at": "t", "kind": "pulse", "ref": 9, "desk": "b", "extra": 1},
            {"seq": 3, "at": "t", "kind": "hold", "ref": 4, "desk": "a"},
        ],
    )
    assert got["cache"]["id"] == 1
    assert [row["kind"] for row in got["activity"]] == ["letter", "hold"]


def test_glance_refuses_when_the_read_is_missing():
    class _Cur:
        def execute(self, _sql):
            raise RuntimeError('(1305, "PROCEDURE uc_a6_glance_cached does not exist")')

        def close(self):
            return None

    class _Cn:
        def cursor(self, dictionary=True):
            return _Cur()

    with pytest.raises(CoordError, match="not installed"):
        read_cached_glance(_Cn())

@pytest.mark.parametrize(
    "extra",
    [["9/12"], ["--note", "x"], ["--eta", "2h"], ["--started"], ["--supersedes", "old", "--note", "new"]],
)
def test_note_refuses_done_when_with_other_note_fields(extra):
    # A done-when note writes only the done-when; anything beside it would be dropped.
    args = _build_parser().parse_args(["note", "unit", "n1", *extra, "--done-when", "tests green"])
    with pytest.raises(CoordError, match="--done-when goes alone"):
        body_from_args(args)


@pytest.mark.parametrize(
    "extra",
    [{"text": "9/12"}, {"note": "x"}, {"detail": "x"}, {"eta": "2h"}, {"started": True}, {"supersedes": "old"}],
)
def test_server_note_refuses_done_when_with_other_note_fields(extra):
    from agent_coord.server.api.mill.rpc import _h_note

    body = {"verb": "note", "need": "n1", "done_when": "tests green", **extra}
    with pytest.raises(CoordError, match="--done-when goes alone"):
        _h_note(None, body, "unit", "builder")
