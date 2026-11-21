"""mill todo --done / --status over /ws (agent-ux 1215)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.book import Book


def _row(i: int, status: str) -> dict:
    return {"id": i, "status": status, "body": '{"slug": "c%d"}' % i, "assigned": "vol", "creator": "ask"}


ROWS = [_row(1, "open"), _row(2, "claimed"), _row(3, "shipped"), _row(4, "done")]


def _as_page(select_fn):
    """mill_todo_page over a fake select: the SQL filters done and id (F22)."""

    def page(cn, project, status="", *, hide_done=False, card_id=0):
        rows = select_fn(cn, project, status)
        return [
            r for r in rows
            if not (hide_done and r.get("status") == "done")
            and not (card_id and int(r.get("id") or 0) != int(card_id))
        ]

    return page


def _run(body: dict) -> tuple[list, MagicMock]:
    c = MagicMock(spec=Book)
    c._cn = MagicMock()

    def fake_select(cn, project, status=""):
        return [r for r in ROWS if not status or r["status"] == status]

    with patch("agent_coord.server.records.todo.page", side_effect=_as_page(fake_select)) as sel:
        out = rpc._h_todo(c, body, "the-mill", "me")
    return out, sel


def test_default_hides_done():
    out, _ = _run({})
    assert [r["id"] for r in out] == [1, 2, 3]


def test_done_flag_includes_done():
    out, _ = _run({"done": True})
    assert [r["id"] for r in out] == [1, 2, 3, 4]


def test_done_flag_string_from_ws_args():
    out, _ = _run({"done": "true"})
    assert 4 in [r["id"] for r in out]


@pytest.mark.parametrize("st,ids", [("done", [4]), ("shipped", [3]), ("open", [1]), ("claimed", [2])])
def test_status_filters(st, ids):
    out, sel = _run({"status": st})
    assert [r["id"] for r in out] == ids
    assert sel.call_args[0][2] == st


def test_status_alias_normalized():
    out, _ = _run({"status": "doing"})
    assert [r["id"] for r in out] == [1]


def test_peek_done_slug_is_shown():
    out, _ = _run({"need": "c4"})
    assert [r["id"] for r in out] == [4]


def test_peek_numeric_id_includes_done():
    out, _ = _run({"need": "4"})
    assert [r["id"] for r in out] == [4]
    assert out[0]["need_id"] == "c4"


def test_peek_numeric_open_id():
    out, _ = _run({"need": "1"})
    assert [r["id"] for r in out] == [1]


def test_peek_unknown_number_refuses():
    with pytest.raises(CoordError, match="todo: no card 999999 in the-mill"):
        _run({"need": "999999"})


@pytest.mark.parametrize(
    "need,snippet",
    [
        ("0", "todo: no card 0 in the-mill"),
        ("-3", "todo: no card -3 in the-mill"),
        ("nope", "todo: no card nope in the-mill"),
        ("9" * 30, "todo: no card " + ("9" * 30) + " in the-mill"),
    ],
)
def test_peek_edge_refuses(need, snippet):
    with pytest.raises(CoordError, match=snippet):
        _run({"need": need})


def test_peek_overlong_number_refuses():
    with pytest.raises(CoordError):
        _run({"need": "9" * 65})


def test_peek_done_id_without_done_returns_the_card():
    out, _ = _run({"need": "4"})
    assert out[0]["id"] == 4
    assert out[0]["status"] == "done"


def test_peek_id_in_another_project_refuses():
    with pytest.raises(CoordError, match="todo: no card 4 in other-proj"):
        c = MagicMock(spec=Book)
        c._cn = MagicMock()

        def fake_select(cn, project, status=""):
            if project == "other-proj":
                return []
            return list(ROWS)

        with patch("agent_coord.server.records.todo.page", side_effect=_as_page(fake_select)):
            rpc._h_todo(c, {"need": "4"}, "other-proj", "me")


def test_cli_peek_miss_prints_stderr_and_exits_1(capsys, monkeypatch):
    import agent_coord.__main__ as cli

    def run(args):
        with pytest.raises(CoordError) as ei:
            _run({"need": args.need})
        raise ei.value

    monkeypatch.setattr("agent_coord.client.http.mill_url", lambda: "http://127.0.0.1:9/")
    monkeypatch.setattr("agent_coord.client.http.mill_http_from_args", run)
    rc = cli.main(["todo", "the-mill", "-3"])
    cap = capsys.readouterr()
    assert rc == 1
    obj = json.loads(cap.out)
    assert obj["code"] == "refused"
    assert "todo: no card" in obj.get("refusal", "")
    assert "todo: no card" not in cap.err
    assert cap.err.strip() == "refused %s" % obj["id"]


def test_peek_done_under_other_status_hints_done():
    with pytest.raises(CoordError, match="pass --done"):
        _run({"need": "4", "status": "open"})


def test_peek_fixture_number_hints_fixtures():
    rows = list(ROWS) + [
        {
            "id": 9,
            "status": "open",
            "body": '{"slug": "fix"}',
            "assigned": "vol",
            "creator": "ask",
            "roster": "t-0a1b2c3d",
        }
    ]

    def fake_select(cn, project, status=""):
        return [r for r in rows if not status or r["status"] == status]

    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.records.todo.page", side_effect=_as_page(fake_select)):
        with pytest.raises(CoordError, match="pass --fixtures"):
            rpc._h_todo(c, {"need": "9"}, "the-mill", "me")
        out = rpc._h_todo(c, {"need": "9", "fixtures": True}, "the-mill", "me")
    assert [r["id"] for r in out] == [9]


def test_bad_status_errors():
    with pytest.raises(CoordError):
        _run({"status": "bogus"})


def test_dispatch_ws_passes_done_through():
    c = MagicMock(spec=Book)
    c._cn = MagicMock()
    with patch("agent_coord.server.records.todo.page", side_effect=_as_page(lambda *a, **k: list(ROWS))):
        out = rpc.dispatch_ws(c, "me", "todo", {"done": True})
    assert 4 in [r["id"] for r in out]


def test_cli_body_carries_done_and_status():
    from agent_coord.client.outbound import body_from_args

    args = SimpleNamespace(cmd="todo", project="the-mill", need="", done=True, status="shipped", fixtures=False)
    with patch("agent_coord.client.tokens.resolve_desk_owner", return_value="me"):
        body = body_from_args(args)
    assert body["done"] is True
    assert body["status"] == "shipped"
    assert "fixtures" not in body
    args.fixtures = True
    with patch("agent_coord.client.tokens.resolve_desk_owner", return_value="me"):
        body = body_from_args(args)
    assert body["fixtures"] is True
