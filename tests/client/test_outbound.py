# -*- coding: utf-8 -*-
from types import SimpleNamespace

import pytest

from agent_coord.client.outbound import (
    PATH,
    COMMANDS,
    body_from_args,
    canonical_command,
    is_mill_command_path,
    parse_path,
    command_path,
)
from agent_coord.helpers.errors import CoordError


def _active(monkeypatch, tmp_path, desk: str) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_COORD_OWNER", raising=False)
    import os

    from agent_coord.client.ws import write_rpc_bridge

    write_rpc_bridge(desk, port=9, secret="sitting", pid=os.getpid())


def test_skill_md_commands():
    for v in (
        "open",
        "unpark",
        "claim",
        "assign",
        "unclaim",
        "note",
        "pass",
        "todo",
        "send",
        "inbox",
        "hold",
        "drop",
        "attach",
        "label-add",
        "member-add",
        "score",
    ):
        assert v in COMMANDS


def test_old_command_names_are_not_rewritten():
    for old in ("ask", "volunteer", "yield", "yield-need", "kpi", "here", "presence", "file", "acquire", "release", "progress"):
        assert canonical_command(old) == old


def test_command_path():
    assert command_path("open") == "/mill/v1/open"
    assert command_path("ask") == "/mill/v1/ask"
    assert command_path("unclaim") == "/mill/v1/unclaim"
    assert PATH == "/mill/v1"


def test_parse_path_v1_and_alias():
    assert parse_path("/mill/v1/open") == "open"
    assert parse_path("/mill/v1/ask") == "ask"
    assert parse_path("/api/mill/send") == "send"
    assert parse_path("/api/v1/mill/claim") == "claim"
    assert parse_path("/api/floor") is None
    assert is_mill_command_path("/mill/v1/open")
    assert is_mill_command_path("/api/mill/inbox")
    assert not is_mill_command_path("/api/floor")


def test_body_create_todo(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "build-ui")
    args = SimpleNamespace(
        cmd="create",
        object="todo",
        project="the-mill",
        need="mill-foo",
        detail="later",
        status="parked",
        parent_type="todo",
        parent_id=11,
    )
    body = body_from_args(args)
    assert body["verb"] == "open"
    assert body["need"] == "mill-foo"
    assert body["status"] == "parked"
    assert body["detail"] == "later"
    assert body["parent_type"] == "todo"
    assert body["parent_id"] == 11
    assert body["owner"] == "build-ui"


def test_body_create_requires_todo_token(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "d")
    try:
        body_from_args(SimpleNamespace(cmd="create", project="p", need="n"))
    except ValueError as e:
        assert "todo" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_body_unpark_unclaim(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "d")
    unp = body_from_args(SimpleNamespace(cmd="unpark", project="p", need="n"))
    assert unp["verb"] == "unpark" and unp["need"] == "n"
    u = body_from_args(SimpleNamespace(cmd="unclaim", project="p", need="n"))
    assert u["verb"] == "unclaim"


def test_body_label_add(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "build-ui")
    args = SimpleNamespace(
        cmd="label-add",
        project="the-mill",
        type="todo",
        id=27,
        label="bug",
    )
    body = body_from_args(args)
    assert body["verb"] == "label-add"
    assert body["type"] == "todo"
    assert body["id"] == 27
    assert body["label"] == "bug"
    assert body["owner"] == "build-ui"
    assert "ord" not in body


def test_body_label_add_ord(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "build-ui")
    args = SimpleNamespace(
        cmd="label-add",
        project="the-mill",
        type="todo",
        id=27,
        label="bug",
        ord=0,
    )
    body = body_from_args(args)
    assert body["ord"] == 0


def test_body_label_add_ord_refused(monkeypatch, tmp_path):
    from agent_coord.helpers.errors import CoordError

    _active(monkeypatch, tmp_path, "build-ui")
    args = SimpleNamespace(
        cmd="label-add",
        project="the-mill",
        type="todo",
        id=27,
        label="bug",
        ord="nope",
    )
    try:
        body_from_args(args)
    except CoordError as e:
        assert "65535" in str(e)
    else:
        raise AssertionError("expected CoordError")


def test_inbox_owner_is_connect_not_dst(monkeypatch, tmp_path):
    """dst names the mailbox; actor desk is mill connect session only."""
    _active(monkeypatch, tmp_path, "mill-prompt-gardener")
    args = SimpleNamespace(
        cmd="inbox",
        project="the-mill",
        dst="mill-prompt-gardener",
        mark=False,
        all=False,
        star=True,
        limit=3,
        after=0,
        role="",
    )
    got = body_from_args(args)
    assert got["verb"] == "inbox"
    assert got["dst"] == "mill-prompt-gardener"
    assert got["owner"] == "mill-prompt-gardener"


def test_inbox_ignores_argv_owner_spoof(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(
            cmd="inbox",
            project="the-mill",
            dst="alice",
            owner="eve",
            mark=False,
            all=False,
            star=False,
            limit=3,
            after=0,
            role="",
        )
    )
    assert got["owner"] == "alice"


def test_reply_in_commands():
    assert "reply" in COMMANDS
    assert "mail-thread" in COMMANDS
    assert "thread" not in COMMANDS


def test_mail_thread_body_from_args(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(
            cmd="mail-thread",
            object="",
            project="the-mill",
            mail_id=99,
        )
    )
    assert got["verb"] == "mail-thread"
    assert got["mail_id"] == 99
    assert got["owner"] == "alice"


def test_mail_thread_body_after(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(
            cmd="mail-thread",
            object="",
            project="the-mill",
            mail_id=99,
            after=42,
        )
    )
    assert got["verb"] == "mail-thread"
    assert got["mail_id"] == 99
    assert got["after"] == 42


def test_mail_thread_body_tree_name(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(
            cmd="mail-thread",
            object="",
            project="the-mill",
            mail_id="8d275a0ac1",
            after=0,
        )
    )
    assert got["verb"] == "mail-thread"
    assert got.get("tree") == "8d275a0ac1"
    assert "mail_id" not in got


def test_mail_thread_body_numeric_string(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(
            cmd="mail-thread",
            object="",
            project="the-mill",
            mail_id="99",
        )
    )
    assert got["mail_id"] == 99
    assert "tree" not in got

def test_send_attr_src_spoof_rejected(monkeypatch, tmp_path):
    _active(monkeypatch, tmp_path, "alice")
    with pytest.raises(CoordError, match="connect desk"):
        body_from_args(
            SimpleNamespace(
                cmd="send",
                project="the-mill",
                src="eve",
                dst="bob",
                body="nope",
            )
        )


@pytest.mark.parametrize("scope", ["room", "subtree"])
def test_mail_thread_body_scope(monkeypatch, tmp_path, scope):
    """#148: --room and --subtree reach the host as scope. --all does not (#242)."""
    _active(monkeypatch, tmp_path, "alice")
    got = body_from_args(
        SimpleNamespace(cmd="mail-thread", object="", project="the-mill", mail_id=99, scope=scope)
    )
    assert got["scope"] == scope
    plain = body_from_args(
        SimpleNamespace(cmd="mail-thread", object="", project="the-mill", mail_id=99, scope="")
    )
    assert "scope" not in plain


def test_mail_thread_help_names_branch_and_room(capsys):
    from agent_coord.__main__ import main

    with pytest.raises(SystemExit):
        main(["mail-thread", "-h"])
    out = capsys.readouterr().out
    assert "--room" in out and "--subtree" in out and "--full" in out and "--after" in out
    assert "--all" not in out and "--no-mark" not in out
    assert "branch" in out


@pytest.mark.parametrize(
    "cmd,extra,match",
    [
        ("create", {"project": "", "need": "n"}, "project required"),
        ("create", {"project": "p" * 65, "need": "n"}, "no such roster"),
        ("create", {"project": "p", "need": "n", "doing": "d" * 513}, "--doing must be"),
        ("todo", {"project": "p" * 65}, "no such roster"),
    ],
)
def test_todo_project_and_doing_guard_243(monkeypatch, tmp_path, cmd, extra, match):
    _active(monkeypatch, tmp_path, "alice")
    args = SimpleNamespace(cmd=cmd, object="todo" if cmd == "create" else "", **extra)
    with pytest.raises(CoordError, match=match):
        body_from_args(args)


@pytest.mark.parametrize(
    "cmd,extra,match",
    [
        ("hold", {"project": "p", "resource": "", "doing": "d"}, "--doing needs a resource"),
        ("hold", {"project": "p", "resource": "", "peek": True, "doing": "d"}, "--doing needs a resource"),
        ("hold", {"project": "p", "resource": "r", "doing": "d" * 513}, "--doing must be"),
    ],
)
def test_hold_drop_status_guard_244(monkeypatch, tmp_path, cmd, extra, match):
    _active(monkeypatch, tmp_path, "alice")
    with pytest.raises(CoordError, match=match):
        body_from_args(SimpleNamespace(cmd=cmd, **extra))
