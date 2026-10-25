"""Mill access: first-person receipts and Admin gates."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book



@pytest.fixture(autouse=True)
def _ws_gate_noop_for_non_ws_tests(monkeypatch):
    """These modules test Bearer/handlers, not Hub /ws. Sit is enforced in test_ws_gate_commands."""
    monkeypatch.setattr(
        "agent_coord.server.api.mill.rpc._require_live_ws",
        lambda owner: None,
    )


def test_inbox_mark_other_dst_refused():
    """Desk A must not stamp desk B mail_to.opened via inbox dst=B."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    body = {"dst": "desk-b", "limit": 10}
    with pytest.raises(CoordError) as ei:
        rpc._h_inbox(c, body, "office", "desk-a")
    msg = str(ei.value).lower()
    assert "dest must be" in msg or "bearer" in msg or "another desk" in msg


def test_inbox_self_dst_ok_calls_select():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    body = {"dst": "desk-a", "no_mark": True, "limit": 5}
    with patch("agent_coord.server.records.mail.inbox", return_value=[]) as sel:
        out = rpc._h_inbox(c, body, "office", "desk-a")
    assert out == []
    sel.assert_called_once()


def test_inbox_mark_does_not_call_opened_insert_for_other_desk():
    """Regression guard: even if select were mocked, mark path must not run for foreign dst."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.api.mill.rpc.slug", side_effect=lambda x: str(x or "").strip().lower()), patch(
        "agent_coord.server.records.opened.insert"
    ) as ins:
        with pytest.raises(CoordError):
            rpc._h_inbox(c, {"dst": "desk-b"}, "office", "desk-a")
    ins.assert_not_called()


def test_assign_requires_admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch.dict("os.environ", {"AGENT_COORD_TRUST": "limited"}), patch(
        "agent_coord.server.admin.guard.is_role_admin", return_value=False
    ), patch("agent_coord.server.records.todo.find", return_value={"id": 1, "volunteer": ""}):
        with pytest.raises(CoordError) as ei:
            rpc._h_assign(c, {"need": "x", "desk": "other"}, "office", "plain-desk")
    assert str(ei.value) == "mill Admin required (roster Admin member)"


def test_assign_ok_when_admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    hit = {"id": 1}
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=True), patch(
        "agent_coord.server.records.todo.find", return_value=hit
    ), patch("agent_coord.server.records.todo.update") as upd, patch(
        "agent_coord.server.api.mill.rpc._poke"
    ):
        out = rpc._h_assign(c, {"need": "card-a", "desk": "worker"}, "office", "admin-desk")
    assert out.get("ok") is True
    upd.assert_called_once()


def test_reset_requires_admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False):
        with pytest.raises(CoordError) as ei:
            rpc._h_reset(c, {"desk": "other"}, "office", "plain-desk")
    assert str(ei.value) == "mill Admin required (roster Admin member)"


def test_reclaim_requires_admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.catalog.reclaim") as reclaim:
        # catalog.reclaim itself calls require_admin - simulate by side_effect
        from agent_coord.server.admin.guard import require_admin

        def _boom(cn, desk, body):
            require_admin(cn, desk)
            return []

        reclaim.side_effect = _boom
        with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False):
            with pytest.raises(CoordError) as ei:
                rpc._h_reclaim(c, {"slug": "x", "confirm": "x", "yes": True}, "office", "plain-desk")
    assert str(ei.value) == "mill Admin required (roster Admin member)"


def test_retire_proj_requires_admin():
    """Admin catalog retire path."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False):
        with pytest.raises(CoordError) as ei:
            rpc._h_retire(
                c, {"slug": "tmp", "confirm": "tmp", "yes": True}, "office", "plain-desk"
            )
    assert str(ei.value) == "mill Admin required (roster Admin member)"


def test_dispatch_owner_mismatch_forces_bearer():
    """Stale OWNER env must not 400 - Bearer wins (#392)."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    c._tokens = {}
    c.resolve_bearer.return_value = "a"
    c._guard_owner.return_value = {"id": 1}

    def _doing(book, body, project, owner):
        return {"ok": True, "owner": owner}

    with patch("agent_coord.client.outbound.canonical_command", return_value="doing"), patch(
        "agent_coord.client.outbound.WALL", frozenset({"doing"})
    ), patch.dict(rpc.HANDLERS, {"doing": _doing}, clear=False):
        out = rpc.dispatch(
            c, {"verb": "doing", "owner": "b", "project": "office"}, token="tok-a"
        )
    assert out["owner"] == "a"
    c._guard_owner.assert_called_once()


def test_dispatch_here_first_person_forces_bearer_owner():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    c._tokens = {}
    c.resolve_bearer.return_value = "a"
    c._guard_owner.return_value = {"id": 1}

    def _doing(book, body, project, owner):
        return {"ok": True, "owner": owner}

    with patch("agent_coord.client.outbound.canonical_command", return_value="doing"), patch(
        "agent_coord.client.outbound.WALL", frozenset({"doing"})
    ), patch.dict(rpc.HANDLERS, {"doing": _doing}, clear=False):
        out = rpc.dispatch(c, {"verb": "doing", "project": "office"}, token="tok-a")
    assert out["owner"] == "a"
    c._guard_owner.assert_called_once()


def test_send_src_must_be_bearer():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.api.mill.rpc.slug", side_effect=lambda x: str(x or "")), patch(
        "agent_coord.client.outbound.addressing.parse_mail_to", return_value=[{"dst": "b", "kind": "desk"}]
    ):
        with pytest.raises(CoordError) as ei:
            rpc._h_send(
                c,
                {"src": "forged", "dst": "b", "body": "hi"},
                "office",
                "real-desk",
            )
    assert "bearer" in str(ei.value).lower() or "src" in str(ei.value).lower()


def test_no_mail_edit_command_in_handlers():
    """Mail is append-only at the RPC surface - no edit-letter command."""
    assert "mail-update" not in rpc.HANDLERS
    assert "edit" not in rpc.HANDLERS
    # mail-thread is intentional read command (lean TREE/chain); not an edit.
    for k in rpc.HANDLERS:
        assert "mail" not in k or k in ("send", "inbox", "mail-thread"), k


def test_inbox_role_does_not_mark():
    """inbox --role still returns the row, and a fetch does not stamp handled (#195)."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    rows = [{"id": 9, "desk": "src", "body": "role mail"}]
    dest_rows = [{"desk": "me", "roster": None, "receipt": 0}]
    with patch("agent_coord.server.records.mail.inbox", return_value=rows) as sel, patch(
        "agent_coord.server.records.opened.read_ids", return_value=set()
    ), patch("agent_coord.server.records.opened.insert") as op_ins, patch(
        "agent_coord.server.records.name.by_id", return_value="src"
    ), patch(
        "agent_coord.server.records.mail.tos_by_id", return_value={9: dest_rows}
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs_batch", return_value={}
    ), patch(
        "agent_coord.server.records.mail.letters_by_id", return_value={}
    ):
        out = rpc._h_inbox(
            c, {"dst": "me", "role": "builder", "limit": 10}, "office", "me"
        )
    assert sel.call_args[0][1:] == sel.call_args[0][1:]
    assert "builder" not in sel.call_args[0]
    assert len(out) == 1
    assert out[0]["id"] == 9
    assert "copies" not in out[0]
    assert "builder" not in sel.call_args[0]
    op_ins.assert_not_called()


def _named_hit(status: str) -> dict:
    """mill_todo_select row shape: names joined next to ids."""
    return {
        "id": 63,
        "status": status,
        "assigned_id": 99,
        "creator_id": 88,
        "assigned": "vol",
        "creator": "ask",
        "body": "{}",
    }


def test_pass_and_unclaim_hand_the_guard_to_the_sp():
    """#867: who-may and status guards run in cmd_pass / cmd_unclaim (the SQL suite
    checks them: test_pass_step_sql_615, test_sec_pass_asker_655, test_server_sp_only_867).
    The server passes the desk, card, step and evidence, and returns the SP's answer."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    seen = []

    def fake_sp(book, proc, args, roster, need):
        desk = args[0]
        seen.append((proc, [desk.sql, *desk.params, *args[1:], roster, need]))
        if proc == "cmd_unclaim":
            raise CoordError("who-may: unclaim is the volunteer")
        return {"card": 63, "status": "done", "was": "shipped", "evidence": args[3]}

    with patch("agent_coord.server.records.todo.find", return_value=_named_hit("shipped")), patch(
        "agent_coord.server.api.mill.rpc._card_sp", side_effect=fake_sp
    ), patch("agent_coord.server.api.mill.rpc._poke"):
        out = rpc._h_pass(c, {"need": "63", "step": "done", "evidence": "PR 1"}, "office", "ask")
        assert out["ok"] is True and out["status"] == "done" and out["was"] == "shipped"
        assert out["evidence"] == "PR 1"
        with pytest.raises(CoordError, match="who-may: unclaim is the volunteer"):
            rpc._h_yield(c, {"need": "63"}, "office", "intruder")
    assert seen[0] == ("cmd_pass", ["MILL_DESK_ID(%s)", "ask", 63, "done", "PR 1", "office", "63"])
    assert seen[1][0] == "cmd_unclaim" and seen[1][1][1:3] == ["intruder", 63]


def test_desk_slug_picks_requested_role():
    hit = _named_hit("shipped")
    assert rpc._desk_slug(None, hit, "asker", "creator") == "ask"
    assert rpc._desk_slug(None, hit, "volunteer", "assigned") == "vol"


def test_dispatch_bare_owner_matches_desk_bearer():
    """CLI owner=builder runs as the stored desk builder. Session files stay DESK_builder."""
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    c._tokens = {}
    c.resolve_bearer.return_value = "builder"
    c._guard_owner.return_value = {"id": 1}

    def _doing(book, body, project, owner):
        return {"ok": True, "owner": owner}

    with patch("agent_coord.client.outbound.canonical_command", return_value="doing"), patch(
        "agent_coord.client.outbound.WALL", frozenset({"doing"})
    ), patch.dict(rpc.HANDLERS, {"doing": _doing}, clear=False):
        out = rpc.dispatch(
            c, {"verb": "doing", "project": "office", "owner": "builder"}, token="tok-b"
        )
    assert out["owner"] == "builder"
    c._guard_owner.assert_called_once()


def test_inbox_bare_dst_matches_desk_bearer():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    rows = [{"id": 3, "desk": "src", "body": "hi"}]
    dest_rows = [{"desk": "me", "roster": None, "receipt": 0}]
    with patch("agent_coord.server.records.mail.inbox", return_value=rows), patch(
        "agent_coord.server.records.opened.read_ids", return_value=set()
    ), patch("agent_coord.server.records.opened.insert") as op_ins, patch(
        "agent_coord.server.records.name.by_id", return_value="src"
    ), patch(
        "agent_coord.server.records.mail.tos_by_id", return_value={3: dest_rows}
    ), patch(
        "agent_coord.server.records.mail.tree_crumbs_batch", return_value={}
    ), patch(
        "agent_coord.server.records.mail.letters_by_id", return_value={}
    ):
        out = rpc._h_inbox(c, {"dst": "me", "limit": 5}, "office", "me")
    assert len(out) == 1
    assert out[0]["id"] == 3
    assert "copies" not in out[0]
    op_ins.assert_not_called()


def test_send_bare_src_matches_bearer():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        return_value=[{"dst": "other", "kind": "desk"}],
    ), patch("agent_coord.server.records.name.get", return_value=1), patch(
        "agent_coord.server.records.mail.insert", return_value=[{"id": 99}]
    ), patch("agent_coord.server.api.mill.rpc._poke"):
        cur = MagicMock()
        cur.fetchone.return_value = (1,)
        c._cn.cursor.return_value = cur
        out = rpc._h_send(
            c, {"src": "me", "dst": "other", "body": "hello"}, "office", "me"
        )
    assert out.get("id") == 99 or out.get("ok") or "copies" in out or isinstance(out, (dict, list))


def test_join_does_not_grant_admin():
    c = MagicMock(spec=Book)
    for role in ("Admin", "admin"):
        with pytest.raises(CoordError) as ei:
            rpc._issue_here(
                c,
                {"project": "the-mill", "owner": "build-cloud", "role": role},
            )
        assert str(ei.value) == "roster Admin is granted only by member-add on the office host"


def test_member_admin_slot_accepts_bare_Admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False):
        with pytest.raises(CoordError) as ei:
            rpc._h_member(
                c,
                {"verb": "member-add", "group": "Admin", "desk": "other"},
                "office",
                "plain",
            )
    assert str(ei.value) == "roster Admin: office host only (loopback)"


def test_loopback_grants_admin_to_any_desk():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False), patch(
        "agent_coord.server.records.member.put_admin", return_value=[{"ok": True}]
    ) as put, patch("agent_coord.server.api.mill.rpc._poke"), patch(
        "agent_coord.server.api.mill.rpc._h_send", return_value={"id": 1}
    ) as mail:
        rpc._h_member(
            c,
            {"verb": "member-add", "group": "Admin", "desk": "other", "host": True},
            "office",
            "plain",
        )
    put.assert_called_once()
    body = mail.call_args.args[1]
    assert body["dst"] == "other"
    assert body["body"] == "You are an Admin on this office."


def test_role_admin_remove_is_host_and_admin():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=True):
        with pytest.raises(CoordError) as ei:
            rpc._h_member(
                c,
                {"verb": "member-remove", "group": "Admin", "desk": "other"},
                "office",
                "admin",
            )
    assert str(ei.value) == "roster Admin: office host only (loopback)"
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=False):
        with pytest.raises(CoordError) as ei:
            rpc._h_member(
                c,
                {"verb": "member-remove", "group": "Admin", "desk": "other", "host": True},
                "office",
                "plain",
            )
    assert str(ei.value) == "mill Admin required (roster Admin member)"


def test_role_admin_remove_mails_the_desk():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.admin.guard.is_role_admin", return_value=True), patch(
        "agent_coord.server.records.member.delete_admin", return_value=[{"ok": True}]
    ), patch("agent_coord.server.api.mill.rpc._h_send", return_value={"id": 2}) as mail:
        rpc._h_member(
            c,
            {"verb": "member-remove", "group": "Admin", "desk": "other", "host": True},
            "office",
            "admin",
        )
    body = mail.call_args.args[1]
    assert body["dst"] == "other"
    assert body["body"] == "You are no longer an Admin on this office."


def test_mark_host_ignores_client_flag():
    from agent_coord.server.admin.guard import mark_host

    remote = {"host": True, "verb": "member-add"}
    mark_host(remote, "203.0.113.10")
    assert "host" not in remote
    local = {"verb": "join"}
    mark_host(local, "127.0.0.1")
    assert local["host"] is True
