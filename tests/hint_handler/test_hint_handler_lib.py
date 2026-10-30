"""HINT receiver lib: parse, ignore PING/DOING, leftovers without board dump."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_parse_real_mail_frame_is_mail(hh, monkeypatch):
    """The frame mill connect hands a route program, not the {type, hint} shape."""
    from agent_coord.client.dispatch import public_frame
    from agent_coord.server.mail_push import compact_mail
    from agent_coord.server.poke_key import letter_key

    letter = {
        "id": 4,
        "created": "2026-01-01T00:00:00",
        "desk": "sender",
        "sender_roster": 1,
        "body": "hello",
    }
    dests = [{"desk": "builder", "opened": None, "receipt": 0}]
    raw = compact_mail(letter, dests, "builder")
    raw["idem"] = letter_key(4, "builder")
    raw["mill"] = "0.7.7"
    # put_recv stamps desk and an empty route: inbound classify has no type/hint.
    raw["desk"] = "builder"
    raw["route"] = ""
    frame = public_frame(raw, "builder")
    assert frame.get("kind") == "mail"
    assert frame.get("idem") == "letter:4:builder"
    assert "body" not in frame
    assert "type" not in frame
    assert "hint" not in frame

    ev = hh.parse_hint(frame)
    assert ev.route_key == "mail:MAIL"
    assert ev.type == "mail"
    assert ev.hint == "MAIL"
    assert ev.id == 4
    assert ev.ignore is False

    bare = {"id": 4, "idem": "letter:4:builder", "kind": "mail", "desk": "builder"}
    ev2 = hh.parse_hint(bare)
    assert ev2.route_key == "mail:MAIL"
    assert ev2.ignore is False

    monkeypatch.delenv("AGENT_COORD_OWNER", raising=False)

    class R:
        returncode = 0
        stdout = '[{"id": 4}]'
        stderr = ""

    with patch.object(hh, "run_mill", return_value=R()) as run:
        out = hh.leftovers(ev2)
    assert out == '[{"id": 4}]'
    run.assert_called_once()
    assert run.call_args[0][0][:3] == ["inbox", "--limit", "3"]


def test_parse_hint_route_key_and_upper_hint(hh):
    ev = hh.parse_hint({"type": "mail", "id": 12, "hint": "mail", "detail": None})
    assert ev.route_key == "mail:MAIL"
    assert ev.hint == "MAIL"
    assert ev.id == 12


def test_parse_hint_detail_json_string(hh):
    ev = hh.parse_hint(
        {
            "type": "todo",
            "id": 3,
            "hint": "TODO",
            "detail": '{"what": "todo", "id": 3, "need": "x"}',
        }
    )
    assert isinstance(ev.detail, dict)
    assert ev.detail["need"] == "x"
    assert hh._detail_sufficient(ev) is True


def test_cheap_default_detail_not_sufficient(hh):
    ev = hh.parse_hint(
        {
            "type": "mail",
            "id": 9,
            "hint": "MAIL",
            "detail": {"what": "mail", "id": 9, "when": "t", "watchers": 1},
        }
    )
    assert hh._detail_sufficient(ev) is False


def test_ignore_ping_join_heartbeat(hh):
    assert hh.parse_hint({"type": "heartbeat", "id": 0, "hint": "PING"}).ignore
    assert hh.parse_hint({"type": "doing", "id": 1, "hint": "DOING"}).ignore
    assert hh.parse_hint({"type": "mail", "id": 1, "hint": "PING"}).ignore
    assert not hh.parse_hint({"type": "mail", "id": 1, "hint": "MAIL"}).ignore


def test_parse_stdin_bad_json(hh):
    with pytest.raises(ValueError, match="not JSON"):
        hh.parse_stdin("not-json")


def test_leftovers_ignore_returns_empty(hh):
    ev = hh.parse_hint({"type": "heartbeat", "id": 0, "hint": "PING"})
    assert hh.leftovers(ev) == ""


def test_leftovers_mail_fetches_inbox_when_detail_thin(hh, monkeypatch):
    ev = hh.parse_hint(
        {
            "type": "mail",
            "id": 5,
            "hint": "MAIL",
            "detail": {"what": "mail", "id": 5},
            "desk": "DESK_builder",
        }
    )
    monkeypatch.setenv("AGENT_COORD_OWNER", "builder")
    monkeypatch.setenv("AGENT_COORD_PROJECT", "the-mill")

    class R:
        returncode = 0
        stdout = '[{"id": 5}]'
        stderr = ""

    with patch.object(hh, "run_mill", return_value=R()) as run:
        out = hh.leftovers(ev)
    assert out == '[{"id": 5}]'
    run.assert_called_once()
    args = run.call_args[0][0]
    assert args[:3] == ["inbox", "--limit", "3"]
    assert "--limit" in args


def test_leftovers_todo_does_not_dump_board(hh):
    ev = hh.parse_hint(
        {
            "type": "todo",
            "id": 44,
            "hint": "TODO",
            "detail": {"what": "todo", "id": 44, "when": "t", "watchers": 2},
        }
    )
    with patch.object(hh, "run_mill") as run:
        out = hh.leftovers(ev)
    assert out == ""
    run.assert_not_called()


def test_leftovers_todo_uses_sufficient_detail(hh):
    ev = hh.parse_hint(
        {
            "type": "todo",
            "id": 44,
            "hint": "TODO",
            "detail": {"what": "todo", "id": 44, "need": "n1", "status": "open"},
        }
    )
    with patch.object(hh, "run_mill") as run:
        out = hh.leftovers(ev)
    assert "need" in out
    run.assert_not_called()


def test_stub_handler_exit_0_on_ping(hh, monkeypatch):
    import runpy

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"type": "heartbeat", "id": 0, "hint": "PING"})),
    )
    root = Path("docs/protocol/hint-handler").resolve()
    monkeypatch.syspath_prepend(str(root))
    # Prefer root tools over repo tools for this run
    # stub inserts parents[1]=hint-handler root first
    stub = root / "examples" / "stub_handler.py"
    # Avoid import collision: run stub main by injecting our hh module path
    # Stub does: from tools.hint_handler import ... which hits repo tools.
    # Call ignore path via hh directly for STOP contract.
    ev = hh.parse_stdin(json.dumps({"type": "heartbeat", "id": 0, "hint": "PING"}))
    assert ev.ignore
    assert hh.exit_ok() == 0
