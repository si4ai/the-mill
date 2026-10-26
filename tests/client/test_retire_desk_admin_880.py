"""Card 880: an Admin desk retires or renames another desk; your own desk keeps the self path.

The client body goes straight into the wall handler, so each case checks what
the desk types against what the wall does with it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import outbound
from agent_coord.client.language import translate
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book

ADMIN_REQUIRED = "mill Admin required (roster Admin member)"


@pytest.fixture()
def body(monkeypatch):
    import agent_coord.client.tokens as tokens

    monkeypatch.setattr(tokens, "resolve_desk_owner", lambda x="": "me")
    p = _build_parser()

    def run(cmd: str, ask=None) -> dict:
        return outbound.body_from_args(translate(p.parse_args(cmd.split()), ask=ask))

    return run


def _wall(handler, b: dict, *, admin: bool):
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=admin), patch(
        "agent_coord.server.records.name.retire", return_value=[{"ok": 1}]
    ) as ret, patch("agent_coord.server.records.name.rename", return_value=[{"ok": 1}]) as ren:
        out = handler(c, b, "the-mill", b["owner"])
    return out, ret, ren


def test_admin_retires_another_desk(body):
    b = body("retire desk ux8-smoke --yes")
    assert (b.get("yes"), b.get("confirm"), b.get("name_type")) == (True, "ux8-smoke", "desk")
    out, ret, _ = _wall(rpc._h_retire, b, admin=True)
    ret.assert_called_once()
    assert ret.call_args.args[1:] == ("ux8-smoke", "desk")


def test_admin_retires_another_desk_after_retype(body):
    b = body("retire desk ux8-smoke", ask=lambda q: "ux8-smoke")
    assert (b.get("yes"), b.get("confirm")) == (True, "ux8-smoke")


def test_non_admin_retire_of_another_desk_gets_admin_required(body):
    b = body("retire desk ux8-smoke --yes")
    with pytest.raises(CoordError) as ei:
        _wall(rpc._h_retire, b, admin=False)
    assert str(ei.value) == ADMIN_REQUIRED


def test_self_retire_keeps_the_self_path(body):
    b = body("retire desk me --yes")
    assert "yes" not in b and not b.get("confirm")
    out, ret, _ = _wall(rpc._h_retire, b, admin=False)
    ret.assert_called_once()
    assert ret.call_args.args[1:] == ("me", "desk")


def test_admin_renames_another_desk(body):
    b = body("rename desk ux8-smoke ux8-old --yes")
    assert (b.get("yes"), b.get("confirm"), b.get("old"), b.get("new")) == (True, "ux8-old", "ux8-smoke", "ux8-old")
    out, _, ren = _wall(rpc._h_rename, b, admin=True)
    ren.assert_called_once()
    assert ren.call_args.args[1:] == ("ux8-smoke", "ux8-old", "desk")


def test_non_admin_rename_of_another_desk_gets_admin_required(body):
    b = body("rename desk ux8-smoke ux8-old --yes")
    with pytest.raises(CoordError) as ei:
        _wall(rpc._h_rename, b, admin=False)
    assert str(ei.value) == ADMIN_REQUIRED


def test_self_rename_keeps_the_self_path(body):
    b = body("rename desk me me2")
    assert "yes" not in b and not b.get("confirm")
    out, _, ren = _wall(rpc._h_rename, b, admin=False)
    ren.assert_called_once()
    assert ren.call_args.args[1:] == ("me", "me2", "desk")
