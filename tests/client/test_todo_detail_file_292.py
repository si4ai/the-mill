# -*- coding: utf-8 -*-
"""#292: create todo --detail-file PATH, same 4096 cap as a mail body.

Regression row F29 (todo-detail-file).
"""
from __future__ import annotations

import os

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client.outbound import body_from_args
from agent_coord.client.ws import write_rpc_bridge
from agent_coord.helpers.errors import CoordError
from agent_coord.protocol.mail import MAIL_BODY_MAX


@pytest.fixture
def seat(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_COORD_OWNER", raising=False)
    write_rpc_bridge("alice", port=9, secret="sitting", pid=os.getpid())
    return tmp_path


def _file(tmp_path, text: str, name: str = "detail.txt") -> str:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _body(argv):
    return body_from_args(_build_parser().parse_args(argv))


def test_detail_file_reads_the_file(seat):
    path = _file(seat, "\ufeff line one\nline two \n")
    got = _body(["create", "todo", "the-mill", "n292", "--detail-file", path])
    assert got["verb"] == "open"
    assert got["detail"] == "line one\nline two"


def test_detail_file_at_cap_kept(seat):
    text = "d" * MAIL_BODY_MAX
    got = _body(["create", "todo", "the-mill", "n292", "--detail-file", _file(seat, text)])
    assert got["detail"] == text


def test_detail_file_over_cap_refused(seat):
    path = _file(seat, "d" * (MAIL_BODY_MAX + 1))
    with pytest.raises(CoordError, match="detail must be 1..4096 chars"):
        _body(["create", "todo", "the-mill", "n292", "--detail-file", path])


def test_detail_file_empty_refused(seat):
    with pytest.raises(CoordError, match="detail must be 1..4096 chars"):
        _body(["create", "todo", "the-mill", "n292", "--detail-file", _file(seat, " \n")])


def test_detail_file_missing_refused(seat):
    with pytest.raises(CoordError, match="detail-file: not found"):
        _body(["create", "todo", "the-mill", "n292", "--detail-file", str(seat / "nope.txt")])


def test_detail_file_not_utf8_refused(seat):
    p = seat / "bin.txt"
    p.write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(CoordError, match="detail-file: not UTF-8"):
        _body(["create", "todo", "the-mill", "n292", "--detail-file", str(p)])


def test_detail_and_detail_file_are_exclusive(seat, capsys):
    path = _file(seat, "x")
    with pytest.raises(SystemExit) as e:
        _build_parser().parse_args(
            ["create", "todo", "the-mill", "n292", "--detail", "x", "--detail-file", path]
        )
    assert e.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_inline_detail_unchanged(seat):
    got = _body(["create", "todo", "the-mill", "n292", "--detail", "short"])
    assert got["detail"] == "short"


def test_help_lists_detail_file(capsys):
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["create", "todo", "-h"])
    out = capsys.readouterr().out
    assert "--detail-file PATH" in out


def test_docs_name_the_row():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    commands = (root / "docs" / "protocol" / "commands.md").read_text(encoding="utf-8")
    assert "--detail-file PATH" in commands
    assert "Regression row F29 (todo-detail-file)" in commands
