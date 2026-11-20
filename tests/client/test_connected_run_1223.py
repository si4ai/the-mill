"""Card 1223 part B: `mill connected --run WATCH_ID` asks the office for one tw run and its descendants."""
from __future__ import annotations

from types import SimpleNamespace

from agent_coord.__main__ import _build_parser
from agent_coord.client.outbound import body_from_args


def test_connected_takes_run_and_sends_it_on_the_session_body() -> None:
    args = _build_parser().parse_args(["connected", "--run", "tw-0123abcd"])
    assert args.run == "tw-0123abcd"
    body = body_from_args(SimpleNamespace(cmd="session", project="", history=False, page=0, run="tw-0123abcd"))
    assert body["verb"] == "session" and body["run"] == "tw-0123abcd"
    assert "project" not in body


def test_plain_connected_sends_no_run() -> None:
    body = body_from_args(SimpleNamespace(cmd="session", project="", history=False, page=0, run=""))
    assert "run" not in body
