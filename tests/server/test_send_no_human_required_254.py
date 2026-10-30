"""#254 follow-up: send and reply have no --human-required; receipt is never set by send."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent_coord.client.outbound import body_from_args


def _body_file():
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".txt")
    with open(fd, "w", encoding="utf-8") as f:
        f.write("needs a human")
    return path


def test_body_from_args_drops_human_required():
    args = SimpleNamespace(
        cmd="send",
        project="the-mill",
        src="builder",
        to_desk=["validator"],
        body_file=_body_file(),
        owner="builder",
        human_required=True,
    )
    body = body_from_args(args)
    assert "human_required" not in body


def test_body_from_args_default_no_human_required():
    args = SimpleNamespace(
        cmd="send",
        project="the-mill",
        src="builder",
        to_desk=["validator"],
        body_file=_body_file(),
        owner="builder",
    )
    body = body_from_args(args)
    assert "human_required" not in body or body.get("human_required") is not True


def test_h_send_ignores_human_required(monkeypatch):
    from agent_coord.server.api.mill import rpc

    inserted = {}

    def fake_insert(cn, project, desk, dst, body, receipt=0, dst_kind="desk"):
        inserted["receipt"] = receipt
        inserted["body"] = body
        inserted["dst"] = dst
        inserted["dst_kind"] = dst_kind
        return [{"id": 42, "created": "t"}]

    class FakeBook:
        _cn = MagicMock()

    book = FakeBook()
    monkeypatch.setattr("agent_coord.server.records.mail.insert", fake_insert)
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda cn, name, kind="": 1)
    monkeypatch.setattr("agent_coord.server.records.name.ensure_roster", lambda *a, **k: 1)
    monkeypatch.setattr(
        "agent_coord.client.outbound.addressing.parse_mail_to",
        lambda dst, project_id="": [{"dst": "validator", "kind": "desk"}],
    )
    monkeypatch.setattr("agent_coord.server.records.mail.dest_count", lambda *a, **k: 1)
    monkeypatch.setattr(
        "agent_coord.server.records.mail.to_list",
        lambda *a, **k: [
            {"desk": "validator", "roster": None, "receipt": 0, "opened": None}
        ],
    )
    monkeypatch.setattr("agent_coord.server.records.mail.tree_crumbs", lambda *a, **k: {})
    monkeypatch.setattr(
        "agent_coord.server.push.fanout", lambda *a, **k: None, raising=False
    )

    out = rpc._h_send(
        book,
        {
            "src": "builder",
            "dst": "validator",
            "body": "please help",
            "human_required": True,
        },
        "the-mill",
        "builder",
    )
    assert inserted["receipt"] == 0
    assert "copies" not in out
    assert "human_required" not in out
    assert out["mail_tos"][0]["receipt"] == 0
    assert set(out["mail_tos"][0].keys()) == {"deskId", "receipt"}
