"""inbox and mail-thread --room print short rows; --full keeps today's reply (#295).

Regression row F53 (mail-short-rows).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser, main
from agent_coord.client import http
from agent_coord.client.mail_rows import BODY_PREVIEW, MAIL_PAGE

GOLDEN = Path(__file__).with_name("mail_full_295.json")
LONG = "GO at 0123abc (desk).\n\n- sha: on main\n" + "- detail line about the build.\n" * 30


def _letter(i, tree="build-room", root=191, body=None):
    return {"id": i, "created": "2026-10-20 03:43:03.742328",
            "sender": {"deskId": f"desk-{i % 3}", "roster": "the-mill"},
            "body": LONG if body is None else body,
            "mail_tos": [{"deskId": "builder", "receipt": 0}],
            "tree": tree, "root_id": root, "root_type": "mail",
            "parent_id": (root if i != root else None), "parent_type": "mail"}


def letters(n, start=1000, **kw):
    return [_letter(start + i, **kw) for i in range(n)]


def room(n, body=None):
    chain = [_letter(191, body="Build Room. The crew talks here.")] + letters(n - 1, body=body)
    return {"id": 191, "chain": chain, "tree": "build-room", "root_id": 191, "root_type": "mail",
            "thread": 1, "latest_id": chain[-1]["id"], "scope": "room", "room_letters": n}


def _wall(monkeypatch, result, command):
    from agent_coord.server.mill_json import with_bytes

    def fake(args, body):
        reply, _ = with_bytes({"id": "r1", "ok": True, "result": result, "sync": [], "mill": "t"})
        return dict(reply)

    monkeypatch.setattr(http, "_todo_call", fake)
    monkeypatch.setattr("agent_coord.client.outbound.body_from_args", lambda args: {"verb": command})


def _run(capsys, cmd, **kw):
    base = dict(cmd=cmd, project="", need="", find="", group_by="", raw=False, said_command="",
                full=False, page=0, scope="", after=0)
    base.update(kw)
    rc = http.mill_http_from_args(SimpleNamespace(**base))
    out = capsys.readouterr().out.strip().splitlines()
    return rc, (out[-1] if out else ""), (json.loads(out[-1]) if out else None)


def _items(result):
    if isinstance(result, list):
        return result
    return [r for g in result["groups"] for r in g["items"]]


# --- inbox ---------------------------------------------------------------

def test_inbox_rows_are_short(monkeypatch, capsys):
    _wall(monkeypatch, letters(3) + letters(2, start=2000, tree="agent-ux", root=1182), "inbox")
    rc, line, row = _run(capsys, "inbox")
    assert rc == 0
    rows = _items(row["result"])
    assert len(rows) == 5
    for r in rows:
        assert set(r) <= {"id", "created", "from", "parent_id", "tree", "body", "body_trunc"}
        assert "mail_tos" not in r and "sender" not in r and "tree" not in r  # grouped by tree
        assert len(r["body"]) <= BODY_PREVIEW and "\n" not in r["body"]
        assert r["body_trunc"] is True and r["from"].startswith("desk-")
        assert r["created"] == "2026-10-20 03:43:03"
    assert row["bytes"] == len(line.encode("utf-8"))
    assert row["page"]["n"] == 1 and row["page"]["of"] == 1 and row["page"]["letters"] == 5
    assert "next" not in row["page"] and "--full" in row["page"]["full"]
    assert {r["tree"] for r in row["rooms"]} == {"build-room", "agent-ux"}


def test_inbox_short_body_is_whole(monkeypatch, capsys):
    _wall(monkeypatch, letters(1, body="ok, merged."), "inbox")
    _, _, row = _run(capsys, "inbox")
    r = _items(row["result"])[0]
    assert r["body"] == "ok, merged." and "body_trunc" not in r


def test_inbox_group_by_roster_keeps_tree(monkeypatch, capsys):
    _wall(monkeypatch, letters(2), "inbox")
    _, _, row = _run(capsys, "inbox", group_by="roster")
    assert all(r["tree"] == "build-room" for r in _items(row["result"]))


def test_inbox_empty(monkeypatch, capsys):
    _wall(monkeypatch, [], "inbox")
    rc, _, row = _run(capsys, "inbox")
    assert rc == 0 and _items(row["result"]) == []
    assert row["page"]["n"] == 1 and row["page"]["of"] == 1 and row["page"]["letters"] == 0


def test_inbox_pages_cover_every_letter_once_and_rooms_cover_all(monkeypatch, capsys):
    n = MAIL_PAGE * 2 + 3
    _wall(monkeypatch, letters(n), "inbox")
    seen = []
    for p in (1, 2, 3):
        _, _, row = _run(capsys, "inbox", page=p)
        seen += [r["id"] for r in _items(row["result"])]
        assert row["rooms"][0]["letters"] == n
        assert row["page"].get("next") == (f"--page {p + 1}" if p < 3 else None)
    assert seen == [1000 + i for i in range(n)]


def test_inbox_exact_page_has_no_next(monkeypatch, capsys):
    _wall(monkeypatch, letters(MAIL_PAGE), "inbox")
    _, _, row = _run(capsys, "inbox")
    assert row["page"]["of"] == 1 and "next" not in row["page"]


def test_inbox_page_past_the_last_is_refused(monkeypatch, capsys):
    _wall(monkeypatch, letters(MAIL_PAGE + 1), "inbox")
    with pytest.raises(Exception, match=r"inbox --page 3: 51 letter\(s\) make 2 page"):
        _run(capsys, "inbox", page=3)


def test_inbox_raw_unchanged_and_page_refused(monkeypatch, capsys):
    rows = letters(4)
    _wall(monkeypatch, rows, "inbox")
    _, _, row = _run(capsys, "inbox", raw=True)
    assert row == rows
    with pytest.raises(Exception, match="inbox --page"):
        _run(capsys, "inbox", raw=True, page=2)


# --- mail-thread --room ----------------------------------------------------

def test_room_page_one_is_the_newest(monkeypatch, capsys):
    _wall(monkeypatch, room(MAIL_PAGE + 10), "mail-thread")
    rc, line, row = _run(capsys, "mail-thread", scope="room")
    assert rc == 0
    chain = row["result"]["chain"]
    ids = [r["id"] for r in chain]
    assert len(ids) == MAIL_PAGE and ids == sorted(ids)
    assert ids[-1] == row["result"]["latest_id"]
    assert row["result"]["room_letters"] == MAIL_PAGE + 10 and row["result"]["tree"] == "build-room"
    assert all("tree" not in r and "mail_tos" not in r for r in chain)
    assert row["page"]["of"] == 2 and row["page"]["next"] == "--page 2" and "newest" in row["page"]["order"]
    assert row["bytes"] == len(line.encode("utf-8"))


def test_room_pages_cover_every_letter_once(monkeypatch, capsys):
    n = MAIL_PAGE * 2 + 7
    full = room(n)
    _wall(monkeypatch, full, "mail-thread")
    pages = []
    for p in (1, 2, 3):
        _, _, row = _run(capsys, "mail-thread", scope="room", page=p)
        pages.append([r["id"] for r in row["result"]["chain"]])
    assert pages[2][0] == 191 and len(pages[2]) == 7
    assert pages[2] + pages[1] + pages[0] == [r["id"] for r in full["chain"]]


def test_room_page_past_the_last_is_refused(monkeypatch, capsys):
    _wall(monkeypatch, room(3), "mail-thread")
    with pytest.raises(Exception, match=r"mail-thread --page 2: 3 letter\(s\) make 1 page"):
        _run(capsys, "mail-thread", scope="room", page=2)


@pytest.mark.parametrize("kw", [{"scope": ""}, {"scope": "subtree"}, {"scope": "full"},
                                {"scope": "room", "after": 5}, {"scope": "room", "raw": True}])
def test_room_other_reads_unchanged_and_page_refused(monkeypatch, capsys, kw):
    res = room(MAIL_PAGE + 5)
    _wall(monkeypatch, res, "mail-thread")
    _, _, row = _run(capsys, "mail-thread", **kw)
    if not kw.get("raw"):
        assert row["result"] == json.loads(json.dumps(res)) and "page" not in row
    with pytest.raises(Exception, match="mail-thread --page"):
        _run(capsys, "mail-thread", page=2, **kw)


# --- --full is today's reply byte-for-byte -------------------------------

def _full_lines(monkeypatch, capsys):
    out = []
    _wall(monkeypatch, letters(MAIL_PAGE + 20, body="GO at 0123abc.\n- ok"), "inbox")
    out.append(_run(capsys, "inbox", full=True)[1])
    _wall(monkeypatch, room(MAIL_PAGE + 20, body="GO at 0123abc.\n- ok"), "mail-thread")
    out.append(_run(capsys, "mail-thread", scope="room", full=True)[1])
    return out


def test_full_is_todays_reply_byte_for_byte(monkeypatch, capsys):
    assert _full_lines(monkeypatch, capsys) == GOLDEN.read_text(encoding="utf-8").strip().split("\n")


# --- parser --------------------------------------------------------------

def test_parser_flags():
    p = _build_parser()
    a = p.parse_args(["inbox", "--page", "2"])
    assert a.page == 2 and a.full is False
    assert p.parse_args(["inbox", "--full"]).full is True
    assert p.parse_args(["mail-thread", "9", "--full"]).scope == "full"
    a = p.parse_args(["mail-thread", "9", "--room", "--full"])
    assert a.scope == "room" and a.full is True
    a = p.parse_args(["mail-thread", "9", "--full", "--room"])
    assert a.scope == "room" and a.full is True
    assert p.parse_args(["mail-thread", "9", "--room", "--page", "3"]).page == 3


@pytest.mark.parametrize("argv", [["inbox", "--page", "0"], ["inbox", "--full", "--page", "2"],
                                  ["mail-thread", "9", "--room", "--page", "x"]])
def test_bad_flags_exit_2(argv):
    with pytest.raises(SystemExit) as e:
        _build_parser().parse_args(argv)
    assert e.value.code == 2


@pytest.mark.parametrize("argv", [["mail-thread", "9", "--subtree", "--full"],
                                  ["mail-thread", "9", "--full", "--subtree"],
                                  ["mail-thread", "9", "--room", "--full", "--page", "2"]])
def test_bad_pairs_exit_2(argv):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 2


@pytest.mark.parametrize("command,flags", [("inbox", ("--full", "--page")),
                                        ("mail-thread", ("--full", "--page"))])
def test_help_names_the_flags(capsys, command, flags):
    with pytest.raises(SystemExit):
        main([command, "--help"])
    out = capsys.readouterr().out
    assert all(f in out for f in flags)
