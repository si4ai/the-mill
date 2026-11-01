# -*- coding: utf-8 -*-
"""mill HTTP access tokens copy GitLab PAT / PyPI token: Bearer + session file."""
from __future__ import annotations

import base64
import json

import pytest

from agent_coord.client.http import mill_api_key, mill_http_call
from agent_coord.server.api.mill.rpc import OPEN_COMMANDS, dispatch
from agent_coord.helpers.errors import CoordError

# Valid CA PEM stub (base64 DER body) so fetch_mill_ca's parse_mill_ca_pem accepts it.
_CA_DER = base64.b64encode(b"\x30\x82\x01\x00" + b"\x00" * 252).decode("ascii")
_CA_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    + "\n".join(_CA_DER[i : i + 64] for i in range(0, len(_CA_DER), 64))
    + "\n-----END CERTIFICATE-----\n"
).encode("ascii")

@pytest.fixture(autouse=True)
def _ws_gate_noop_for_non_ws_tests(monkeypatch):
    """These modules test Bearer/handlers, not Hub /ws. Sit is enforced in test_ws_gate_commands."""
    monkeypatch.setattr(
        "agent_coord.server.api.mill.rpc._require_live_ws",
        lambda owner: None,
    )


def test_mill_api_key_ignores_env(monkeypatch, tmp_path):
    import os

    from agent_coord.client.tokens import write_session_token
    from agent_coord.client.ws import write_rpc_bridge

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    write_session_token("desk", "file-pat", dest=tmp_path)
    write_rpc_bridge("desk", port=9, secret="sitting", pid=os.getpid())
    monkeypatch.setenv("AGENT_COORD_TOKEN", "env-pat")
    assert mill_api_key("desk") == "file-pat"
    assert mill_api_key("other") == ""
    none = tmp_path / "none"
    none.mkdir(exist_ok=True)
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(none))
    assert mill_api_key("other") == ""


def test_mill_api_key_session_file(monkeypatch, tmp_path):
    import os

    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    from agent_coord.client.tokens import write_session_token
    from agent_coord.client.ws import write_rpc_bridge

    write_session_token("desk", "file-pat", dest=tmp_path)
    write_rpc_bridge("desk", port=9, secret="sitting", pid=os.getpid())
    assert mill_api_key("desk") == "file-pat"


def test_mill_http_call_join_sends_bearer_not_body_token(monkeypatch, tmp_path):
    """join stays HTTP; desk commands use /ws RPC (see test_ws_rpc / mill_ws_call)."""
    from agent_coord.client.tokens import write_session_token

    monkeypatch.setenv("AGENT_COORD_MILL_URL", "https://office.example")
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    write_session_token("desk", "gl-style-pat", dest=tmp_path)
    captured = {}

    class Resp:
        def read(self):
            return b'{"ok":true,"token":"x","owner":"desk"}'

        headers = {"X-Mill-Version": "0"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, context=None, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization") or req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return Resp()

    monkeypatch.setattr("agent_coord.client.http._open", fake_urlopen)
    row = mill_http_call({"verb": "join", "project": "the-mill", "owner": "desk"})
    assert row["ok"] is True
    assert captured["url"].endswith("/mill/v1/join")
    assert captured["auth"] == "Bearer gl-style-pat"
    assert captured["body"].get("token") == "gl-style-pat"


def test_mill_http_call_desk_command_uses_ws_rpc(monkeypatch, tmp_path):
    import os

    from agent_coord.client.tokens import write_session_token
    from agent_coord.client.ws import write_rpc_bridge

    monkeypatch.setenv("AGENT_COORD_MILL_URL", "https://office.example")
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    write_session_token("desk", "gl-style-pat", dest=tmp_path)
    write_rpc_bridge("desk", port=9, secret="sitting", pid=os.getpid())
    seen = {}

    def fake_ws(body, *, token="", desk=""):
        seen["body"] = body
        seen["token"] = token
        seen["desk"] = desk
        return {"ok": True, "via": "ws"}

    monkeypatch.setattr("agent_coord.client.ws.mill_ws_call", fake_ws)
    row = mill_http_call({"verb": "session", "project": "the-mill", "owner": "desk"})
    assert row == {"ok": True, "via": "ws"}
    assert seen["token"] == "gl-style-pat"
    assert seen["desk"] == "desk"
    assert "token" not in seen["body"]


def test_dispatch_session_requires_access_token():
    class Fake:
        _tokens = {}

        def resolve_bearer(self, token):
            return ""

        def _guard_owner(self, *a, **k):
            return {}

    with pytest.raises(CoordError, match="access token"):
        dispatch(Fake(), {"verb": "session", "project": "the-mill", "owner": "desk"}, token="")


def test_dispatch_here_is_open():
    assert "join" in OPEN_COMMANDS
    assert "here" not in OPEN_COMMANDS
    assert "session" not in OPEN_COMMANDS


def test_dispatch_registry_covers_outbound_wall():
    from agent_coord.client.outbound import COMMANDS, WALL
    from agent_coord.server.api.mill.rpc import HANDLERS

    assert COMMANDS <= WALL
    # WALL is the client command set. The old thread command is gone (#241).
    assert WALL <= set(HANDLERS)
    assert "thread" not in HANDLERS
    with pytest.raises(CoordError, match="unknown command"):
        dispatch(
            type("F", (), {"_tokens": {}, "resolve_bearer": lambda self, token: "DESK_d"})(),
            {"verb": "leftover", "project": "p", "owner": "d"},
            token="t",
        )


def test_dispatch_open_passes_status(monkeypatch):
    captured = {}

    class Fake:
        _tokens = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda *a, **k: 1)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find_retired", lambda *a, **k: None)
    monkeypatch.setattr(
        "agent_coord.server.records.todo.insert",
        lambda cn, project, desk, status, body: captured.update(status=status) or [{"id": 1}],
    )
    rec = dispatch(
        Fake(),
        {
            "verb": "open",
            "project": "the-mill",
            "owner": "desk",
            "need": "mill-park",
            "status": "parked",
        },
        token="t",
    )
    assert captured.get("status") == "parked"
    assert rec["status"] == "parked"


def test_dispatch_unpark_and_unclaim(monkeypatch):
    calls = []

    class Fake:
        _tokens = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    card = {"id": 9, "status": "parked"}
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: dict(card))
    monkeypatch.setattr(
        "agent_coord.server.records.tree.has_parent", lambda *a, **k: True
    )

    def update(cn, tid, desk, status="", volunteer="", body=None):
        calls.append((status, volunteer))
        if status:
            card["status"] = status  # unclaim after unpark sees an open card (card 778)
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.update", update)

    def card_sp(book, proc, args, roster, need):  # #867: unclaim is one cmd_unclaim call
        calls.append((proc, args[1]))
        return {"card": args[1], "status": "open"}

    monkeypatch.setattr("agent_coord.server.api.mill.rpc._card_sp", card_sp)
    c = Fake()
    rec = dispatch(
        c,
        {"verb": "unpark", "project": "the-mill", "owner": "desk", "need": "mill-park"},
        token="t",
    )
    assert rec["ok"] is True and rec["status"] == "open"
    rec = dispatch(
        c,
        {"verb": "unclaim", "project": "the-mill", "owner": "desk", "need": "mill-park"},
        token="t",
    )
    assert rec["ok"] is True
    for old in ("yield", "yield-need"):
        with pytest.raises(CoordError, match="unknown command"):
            dispatch(
                c,
                {"verb": old, "project": "the-mill", "owner": "desk", "need": "mill-park"},
                token="t",
            )
    assert calls == [("open", ""), ("cmd_unclaim", 9)]


def test_unpark_refuses_orphan(monkeypatch):
    class Fake:
        _tokens = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    monkeypatch.setattr(
        "agent_coord.server.records.todo.find", lambda *a, **k: {"id": 9, "status": "parked"}
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.has_parent", lambda *a, **k: False
    )
    with pytest.raises(CoordError, match="TREE parent"):
        dispatch(
            Fake(),
            {"verb": "unpark", "project": "the-mill", "owner": "desk", "need": "mill-park"},
            token="t",
        )


def test_unpark_attaches_parent_then_opens(monkeypatch):
    calls = []
    adds = []
    monkeypatch.setattr("agent_coord.server.records.label._activity_live", lambda *a, **k: True)

    class Fake:
        _tokens = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    monkeypatch.setattr(
        "agent_coord.server.records.todo.find", lambda *a, **k: {"id": 9, "status": "parked"}
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.add",
        lambda cn, pt, pid, ct, cid, tree="": adds.append((pt, pid, ct, cid)) or [],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.has_parent", lambda *a, **k: True
    )

    def update(cn, tid, desk, status="", volunteer="", body=None):
        calls.append(status)
        return [{"id": tid}]

    monkeypatch.setattr("agent_coord.server.records.todo.update", update)
    rec = dispatch(
        Fake(),
        {
            "verb": "unpark",
            "project": "the-mill",
            "owner": "desk",
            "need": "mill-park",
            "parent_type": "todo",
            "parent_id": 3,
        },
        token="t",
    )
    assert rec["ok"] is True and rec["status"] == "open"
    assert adds == [("todo", 3, "todo", 9)]
    assert calls == ["open"]


def test_open_attaches_parent(monkeypatch):
    attached = []

    class Fake:
        _tokens = {}
        _cn = object()

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda *a, **k: 1)
    monkeypatch.setattr("agent_coord.server.records.todo.find", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.todo.find_retired", lambda *a, **k: None)

    def insert_attached(cn, project, desk, status, body, parent_type, parent_id):
        attached.append((parent_type, int(parent_id), status))
        return [{"id": 42, "status": status}]

    monkeypatch.setattr("agent_coord.server.records.todo.insert_attached", insert_attached)

    def _no_insert(*_a, **_k):
        raise AssertionError("insert")

    def _no_tree_add(*_a, **_k):
        raise AssertionError("tree.add")

    monkeypatch.setattr("agent_coord.server.records.todo.insert", _no_insert)
    monkeypatch.setattr("agent_coord.server.records.tree.add", _no_tree_add)
    rec = dispatch(
        Fake(),
        {
            "verb": "open",
            "project": "the-mill",
            "owner": "desk",
            "need": "mill-child",
            "status": "parked",
            "parent_type": "todo",
            "parent_id": 7,
        },
        token="t",
    )
    assert rec["id"] == 42 and rec["status"] == "parked"
    assert attached == [("todo", 7, "parked")]


def test_send_attaches_parent(monkeypatch):
    adds = []

    class Fake:
        _tokens = {}
        _cn = None

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    from unittest.mock import MagicMock

    fake_cn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    fake_cn.cursor.return_value = cur
    book = Fake()
    book._cn = fake_cn

    dest_rows = [
        {"desk": "validator", "roster": None, "receipt": 0},
    ]
    monkeypatch.setattr(
        "agent_coord.server.records.mail.insert",
        lambda *a, **k: [{"id": 55, "created": "t"}],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.name.get", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "agent_coord.server.records.name.ensure_roster", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        lambda dst, project_id="": [{"dst": "validator", "kind": "desk"}],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.dest_count", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list", lambda *a, **k: dest_rows
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.tree_crumbs",
        lambda *a, **k: {
            "tree": "TREE_x",
            "root_id": 21,
            "root_type": "todo",
            "parent_id": 21,
            "parent_type": "todo",
        },
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.add",
        lambda cn, pt, pid, ct, cid, tree="": adds.append((pt, pid, ct, cid))
        or [{"type": ct, "id": cid}],
    )
    monkeypatch.setattr(
        "agent_coord.server.push.fanout", lambda *a, **k: None, raising=False
    )
    rec = dispatch(
        book,
        {
            "verb": "send",
            "project": "the-mill",
            "owner": "desk",
            "src": "desk",
            "dst": "validator",
            "body": "thread reply",
            "parent_type": "todo",
            "parent_id": 21,
        },
        token="t",
    )
    assert rec["id"] == 55
    assert rec["parent_type"] == "todo" and rec["parent_id"] == 21
    assert adds == [("todo", 21, "mail", 55)]
    assert "copies" not in rec
    assert rec["mail_tos"][0]["deskId"] == "validator"


def test_send_without_parent_skips_tree(monkeypatch):
    adds = []

    class Fake:
        _tokens = {}
        _cn = None

        def resolve_bearer(self, token):
            return "desk"

        def _guard_owner(self, *a, **k):
            return {}

    from unittest.mock import MagicMock

    fake_cn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (1,)
    fake_cn.cursor.return_value = cur
    book = Fake()
    book._cn = fake_cn

    dest_rows = [
        {"desk": "validator", "roster": None, "receipt": 0},
    ]
    monkeypatch.setattr(
        "agent_coord.server.records.mail.insert",
        lambda *a, **k: [{"id": 56, "created": "t"}],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.name.get", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "agent_coord.server.records.name.ensure_roster", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        lambda dst, project_id="": [{"dst": "validator", "kind": "desk"}],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.dest_count", lambda *a, **k: 1
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list", lambda *a, **k: dest_rows
    )
    monkeypatch.setattr(
        "agent_coord.server.records.mail.tree_crumbs", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "agent_coord.server.records.tree.add",
        lambda cn, pt, pid, ct, cid, tree="": adds.append((pt, pid, ct, cid)) or [],
    )
    monkeypatch.setattr(
        "agent_coord.server.push.fanout", lambda *a, **k: None, raising=False
    )
    rec = dispatch(
        book,
        {
            "verb": "send",
            "project": "the-mill",
            "owner": "desk",
            "src": "desk",
            "dst": "validator",
            "body": "plain note",
        },
        token="t",
    )
    assert rec["id"] == 56
    assert "parent_type" not in rec
    assert "copies" not in rec
    assert adds == []
    assert "tree" not in rec
    assert rec["mail_tos"][0]["deskId"] == "validator"


def test_mill_http_client_never_opens_mysql():
    import inspect

    from agent_coord.client import http as mill_client

    src = inspect.getsource(mill_client)
    assert "mysql" not in src
    assert "Coord(" not in src


def test_fetch_mill_ca_prefers_api_path(monkeypatch, tmp_path):
    from agent_coord.client import http as mill_client

    urls = []
    got_headers: list[str] = []

    class Resp:
        def read(self):
            return b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, context=None, timeout=None):
        urls.append(getattr(url, "full_url", str(url)))
        got_headers.append(url.get_header("X-mill-invite") if hasattr(url, "get_header") else "")
        return Resp()

    monkeypatch.setattr(mill_client, "mill_ca_file", lambda: tmp_path / "ca.crt")
    monkeypatch.setattr(mill_client, "_open", fake_urlopen)
    got = mill_client.fetch_mill_ca("https://198.51.100.10/")
    assert got is not None
    assert urls[0].endswith("/api/ca.crt")
    assert got_headers[0] in ("", None)


def test_fetch_mill_ca_warns_on_version_mismatch(monkeypatch, tmp_path, capsys) -> None:
    from agent_coord.client import http as mill_client

    class Resp:
        headers = {"X-Mill-Version": "0.5.1"}

        def read(self):
            return _CA_PEM

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mill_client, "_open", lambda *a, **k: Resp())
    monkeypatch.setattr("agent_coord.install.packver.package_version", lambda: "0.5.2")
    got = mill_client.fetch_mill_ca("https://203.0.113.10/", dest=tmp_path / "ca.crt")
    assert got is not None
    assert "warning: mill client 0.5.2 != wall 0.5.1" in capsys.readouterr().err


def test_warn_wall_version_mismatch(capsys, monkeypatch) -> None:
    from agent_coord.client.http import warn_wall_version

    monkeypatch.setattr("agent_coord.install.packver.package_version", lambda: "0.5.2")
    warn_wall_version("0.5.1")
    err = capsys.readouterr().err
    assert "warning: mill client 0.5.2 != wall 0.5.1" in err
    warn_wall_version("0.5.2")
    assert capsys.readouterr().err == ""


def test_fetch_mill_ca_sends_invite(monkeypatch, tmp_path):
    from agent_coord.client import http as mill_client

    seen: dict[str, str] = {}

    class Resp:
        def read(self):
            return _CA_PEM

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, context=None, timeout=None):
        seen["url"] = getattr(url, "full_url", str(url))
        seen["invite"] = url.get_header("X-mill-invite") or ""
        return Resp()

    monkeypatch.setattr(mill_client, "_open", fake_urlopen)
    got = mill_client.fetch_mill_ca("https://203.0.113.10/?invite=cloud-key", dest=tmp_path / "ca.crt")
    assert got is not None
    assert seen["url"].endswith("/api/ca.crt")
    assert "invite=" not in seen["url"]
    assert seen["invite"] == "cloud-key"


def test_token_required_default_on():
    from agent_coord.config import DEFAULTS

    assert str(DEFAULTS.get("token_required") or "") == "1"
