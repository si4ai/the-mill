"""#274 client side: todo by ROSTER/NEED, todo --find, send words, join next once, connect is #281."""
from __future__ import annotations

import argparse
import base64
from urllib.parse import urlencode

import pytest

from agent_coord.__main__ import _build_parser, main
from agent_coord.client.http import _todo_find, todo_find_text
from agent_coord.client.language import card_ref, translate
from agent_coord.client.outbound import body_from_args
from agent_coord.helpers.errors import CoordError


@pytest.fixture(autouse=True)
def _clear_cli_office():
    from agent_coord.client.offices import bind_cli_office

    bind_cli_office("")
    yield
    bind_cli_office("")


def _body(argv):
    a = translate(_build_parser().parse_args(argv))
    return a.cmd, body_from_args(a)


@pytest.mark.parametrize(
    "raw,typ,want",
    [
        ("12", "todo", 12),
        ("cold-test/fix-login", "todo", "cold-test/fix-login"),
        (" 7 ", "hold", 7),
        # #327: any non-number is a hold name, slashes included; the server resolves it.
        ("cold-test/fix-login", "hold", "cold-test/fix-login"),
    ],
)
def test_card_ref_ok(raw, typ, want):
    assert card_ref(raw, typ, "watch") == want


@pytest.mark.parametrize(
    "raw,typ,msg",
    [
        ("0", "todo", "watch todo: give the todo id (a number above 0) or ROSTER/NEED"),
        ("-3", "todo", "watch todo: give the todo id"),
        ("fix-login", "todo", "watch todo: give the todo id"),
        ("cold-test/", "todo", "watch todo: give the todo id"),
        ("/fix-login", "todo", "watch todo: give the todo id"),
        ("cold test/fix", "todo", "watch todo: give the todo id"),
        ("a" * 65 + "/x", "todo", "watch todo: give the todo id"),
        ("0", "hold", "watch hold: give the hold id (a number above 0)"),
        ("x" * 1000, "hold", "resource must be 1.."),
        ("", "score", "watch score: give the score id"),
    ],
)
def test_card_ref_refused(raw, typ, msg):
    with pytest.raises(CoordError) as ei:
        card_ref(raw, typ, "watch")
    assert str(ei.value).startswith(msg)


def test_watch_by_name_sends_ref_not_id():
    cmd, body = _body(["watch", "todo", "cold-test/fix-login"])
    assert cmd == "add" and body["type"] == "todo" and body["ref"] == "cold-test/fix-login" and "id" not in body


def test_unwatch_by_name_and_by_number():
    cmd, body = _body(["unwatch", "todo", "cold-test/fix-login"])
    assert cmd == "remove" and body["ref"] == "cold-test/fix-login" and "id" not in body
    cmd, body = _body(["unwatch", "todo", "12"])
    assert cmd == "remove" and body["id"] == 12 and "ref" not in body


def test_label_by_name_sends_ref():
    cmd, body = _body(["label", "todo", "cold-test/fix-login", "urgent"])
    assert cmd == "label-add" and body["ref"] == "cold-test/fix-login" and body["label"] == "urgent"
    assert not body.get("id")


def test_label_mail_by_name_refused():
    with pytest.raises(CoordError, match="label mail: give the mail id"):
        _body(["label", "mail", "cold-test/fix-login", "urgent"])


def test_send_words_ride_along(tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("hi", encoding="utf-8")
    _, body = _body(["send", "desk", "builder", "roster", "the-mill", "--body-file", str(f)])
    assert body["mail_tos"] == [{"deskId": "builder", "kind": "desk"}, {"deskId": "the-mill", "kind": "roster"}]
    _, body = _body(["send", "--to-desk", "builder", "--body-file", str(f)])
    assert body["mail_tos"] == ["builder"]


def test_connected_is_the_word_and_session_is_gone():
    cmd, body = _body(["connected", "cold-test"])
    assert cmd == "session" and body["project"] == "cold-test"
    with pytest.raises(SystemExit) as ei:
        _build_parser().parse_args(["session", "cold-test"])
    assert ei.value.code == 2


def _ns(find, cmd="todo"):
    return argparse.Namespace(find=find, cmd=cmd)


@pytest.mark.parametrize("raw,want", [("ux11", "ux11"), ("  Login ", "Login"), ("", ""), (None, "")])
def test_find_text_ok(raw, want):
    assert todo_find_text(_ns(raw)) == want


@pytest.mark.parametrize("raw", ["   ", "x" * 65])
def test_find_text_refused(raw):
    with pytest.raises(CoordError, match="todo --find: TEXT is 1..64 characters"):
        todo_find_text(_ns(raw))


def test_find_ignored_off_todo():
    assert todo_find_text(_ns("x", cmd="inbox")) == ""


ROWS = [
    {"project_id": "cold-test", "need_id": "ux11-fix-login", "id": 5, "detail": "login 500"},
    {"project_id": "the-mill", "need_id": "073-card-lookup", "id": 274, "detail": "card lookup"},
    {"project_id": "agent-ux", "need_id": "r4", "id": 9, "detail": "Fix LOGIN page", "doing": ""},
]


def test_find_filters_roster_need_detail_any_case():
    out = _todo_find({"ok": True, "result": ROWS}, "login")
    assert [r["id"] for r in out["result"]] == [5, 9]
    assert out["note"].startswith("2 card(s) match")
    out = _todo_find({"ok": True, "result": ROWS}, "the-mill")
    assert [r["id"] for r in out["result"]] == [274]


def test_find_none_says_how_to_widen():
    out = _todo_find({"ok": True, "result": ROWS}, "nothing-here")
    assert out["result"] == [] and "--all" in out["note"]


def test_find_none_omits_flags_already_given():
    """#649: empty --find note names only flags not already on the command."""
    out = _todo_find({"ok": True, "result": ROWS}, "nothing-here", have_done=True, have_all=True)
    assert out["result"] == []
    assert "--done" not in out["note"] and "--all" not in out["note"]
    out = _todo_find({"ok": True, "result": ROWS}, "nothing-here", have_done=True)
    assert "--done" not in out["note"] and "--all" in out["note"]
    out = _todo_find({"ok": True, "result": ROWS}, "nothing-here", have_all=True)
    assert "--all" not in out["note"] and "--done" in out["note"]


def test_find_leaves_refusals_alone():
    row = {"ok": False, "error": "x"}
    assert _todo_find(row, "a") is row


_PEM = "-----BEGIN CERTIFICATE-----\nMIIBTESTCA\n-----END CERTIFICATE-----\n"


def _welcome(desk: str) -> str:
    fields = {"desk": desk, "seat": "sek", "project": "the-mill", "pem": base64.b64encode(_PEM.encode()).decode()}
    return "https://office.example/welcome?" + urlencode(fields)


def _lf(tmp_path, link):
    f = tmp_path / "welcome.link"
    f.write_text(link + "\n", encoding="utf-8")
    return str(f)


def _fake_join(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr("agent_coord.install.packver.checkout_dist_line", lambda: "")
    monkeypatch.setattr(
        "agent_coord.client.offices.join_office",
        lambda url, office, **kw: {"ok": True, "desk": "build-app", "project": "the-mill", "next": "next: X"},
    )


def test_join_prints_next_once(monkeypatch, tmp_path, capsys):
    _fake_join(monkeypatch, tmp_path)
    rc = main(["join", "--link-file", _lf(tmp_path.parent, _welcome("build-app"))])
    cap = capsys.readouterr()
    assert rc == 0
    both = cap.out + cap.err
    assert both.count("next: ") == 1
    assert cap.out.rstrip().splitlines()[-1].startswith("next: ")
    assert '"next"' not in cap.out


def test_join_reports_failed_office_save(monkeypatch, tmp_path, capsys):
    _fake_join(monkeypatch, tmp_path)

    def boom(_office, **kw):
        raise OSError("read-only file system")

    monkeypatch.setattr("agent_coord.client.offices.write_global_active", boom)
    rc = main(["join", "--link-file", _lf(tmp_path.parent, _welcome("build-app"))])
    cap = capsys.readouterr()
    assert rc == 0
    assert "could not save" in cap.err and "read-only file system" in cap.err and "--office" in cap.err
