"""Card 1204: mill member --all body, text render, and --json (no SQL)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from agent_coord.__main__ import _build_parser
from agent_coord.client import member_rows
from agent_coord.client.outbound import body_from_args
from agent_coord.install.office import help_text


def test_parser_and_body_carry_all() -> None:
    args = _build_parser().parse_args(["member", "--all"])
    assert args.cmd == "member" and args.all is True and args.as_json is False
    with patch("agent_coord.client.tokens.resolve_desk_owner", return_value="builder"):
        body = body_from_args(args)
    assert body["verb"] == "member" and body["all"] is True and body["owner"] == "builder"

    js = _build_parser().parse_args(["member", "--all", "--json"])
    assert js.all is True and js.as_json is True
    bare = _build_parser().parse_args(["member"])
    assert bare.all is False and bare.as_json is False


def test_render_aligns_name_and_count() -> None:
    text = member_rows.render(
        [
            {"name": "Office", "desks": 24, "members": []},
            {"name": "the-mill", "desks": 8, "members": ["builder"]},
        ]
    )
    assert text == "Office    24\nthe-mill  8\n"
    assert text.isascii()
    assert member_rows.render([]) == ""
    assert member_rows.render([{"name": "", "desks": 1}]) == ""


def test_http_prints_text_unless_json(capsys) -> None:
    from agent_coord.client import http

    rows = [{"name": "Office", "desks": 2, "members": ["a", "b"]}]
    reply = {"ok": True, "result": rows}
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "member", "all": True}
    ):
        rc = http.mill_http_from_args(SimpleNamespace(cmd="member", all=True, as_json=False))
        out = capsys.readouterr().out
        assert rc == 0 and out == "Office  2\n"
        rc = http.mill_http_from_args(SimpleNamespace(cmd="member", all=True, as_json=True))
        out = capsys.readouterr().out
        assert rc == 0 and json.loads(out)["result"] == rows


def test_plain_member_still_prints_json(capsys) -> None:
    from agent_coord.client import http

    mine = [{"slot": "Office", "desk": "builder"}]
    reply = {"ok": True, "result": mine}
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "member"}
    ):
        rc = http.mill_http_from_args(SimpleNamespace(cmd="member", all=False, as_json=False))
        out = capsys.readouterr().out
        assert rc == 0 and json.loads(out)["result"] == mine


def test_help_member_names_all() -> None:
    text = help_text("member")
    assert "mill member --all" in text
    assert "member count" in text
