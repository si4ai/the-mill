"""Card 1233: --label on activity writes and reads. No MySQL."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_coord.helpers import activity_label as al
from agent_coord.helpers.activity_label import NameRow, classify, keep
from agent_coord.helpers.errors import CoordError

CATALOG = [
    NameRow("rco", "label"),
    NameRow("windows", "label"),
    NameRow("old", "label", may_set=False),
    NameRow("bob", "desk", focus=False),
    NameRow("ada", "desk", focus=True, focus_name="ada-1"),
    NameRow("crew", "roster"),
]


def _labels():
    return ["rco", "windows", "old"]


def test_unknown_warning_names_closest_and_create():
    got = classify(["windos"], CATALOG, _labels())
    assert got.set_names == []
    assert got.warnings == [
        "label 'windos' does not exist. closest: windows. mill create label windos."
    ]


def test_no_closest_says_none():
    got = classify(["zzzz"], CATALOG, _labels())
    assert "closest: none." in got.warnings[0]
    assert "mill create label zzzz." in got.warnings[0]


def test_other_kind_is_named():
    got = classify(["bob", "crew"], CATALOG, _labels())
    assert got.set_names == []
    assert "bob is a desk, not a label" in got.warnings[0]
    assert "crew is a roster, not a label" in got.warnings[1]


def test_disallowed_label_is_skipped():
    got = classify(["old"], CATALOG, _labels())
    assert got.set_names == []
    assert got.warnings == [
        "label 'old' may not be set. closest: none. mill create label old."
    ]


def test_focus_desk_read_names_the_list_and_a_write_skips_it():
    read = classify(["ada", "bob"], CATALOG, _labels())
    assert read.set_names == ["ada"]
    assert read.show == ["ada-1"]
    assert read.accepted[0].aliases == ("ada", "ada-1")
    assert any("desk" in w for w in read.warnings)
    write = classify(["ada", "bob"], CATALOG, _labels(), writing=True)
    assert write.set_names == []
    assert "ada is a desk, not a label" in write.warnings[0]
    assert "bob is a desk, not a label" in write.warnings[1]


def test_blanks_and_dupes_drop():
    got = classify([" rco ", "", "rco", "windows"], CATALOG, _labels())
    assert got.set_names == ["rco", "windows"]
    assert got.warnings == []


def test_one_label_every_and_any_agree():
    item = {"id": 1}
    labels = {1: {"rco"}}
    got = classify(["rco"], CATALOG, _labels())
    assert keep([item], got, any_mode=False, labels_of=lambda it: labels[it["id"]]) == [item]
    assert keep([item], got, any_mode=True, labels_of=lambda it: labels[it["id"]]) == [item]


def test_two_labels_every_and_any():
    items = [{"id": 1}, {"id": 2}, {"id": 3}]
    labels = {1: {"rco"}, 2: {"rco", "windows"}, 3: {"windows"}}
    got = classify(["rco", "windows"], CATALOG, _labels())

    def of(it):
        return labels[it["id"]]

    assert [it["id"] for it in keep(items, got, any_mode=False, labels_of=of)] == [2]
    assert [it["id"] for it in keep(items, got, any_mode=True, labels_of=of)] == [1, 2, 3]


def test_unknown_read_is_not_a_silent_filter():
    items = [{"id": 1}]
    got = classify(["nope"], CATALOG, _labels())
    assert got.warnings
    assert keep(items, got, any_mode=False, labels_of=lambda it: {"rco"}) == []
    assert keep(items, got, any_mode=True, labels_of=lambda it: {"rco"}) == []


def test_label_plus_status_filter():
    items = [
        {"id": 1, "status": "open"},
        {"id": 2, "status": "done"},
        {"id": 3, "status": "open"},
    ]
    labels = {1: {"rco"}, 2: {"rco", "windows"}, 3: {"windows"}}
    got = classify(["rco", "windows"], CATALOG, _labels())

    def of(it):
        return labels[it["id"]]

    every_open = keep(
        items, got, any_mode=False, labels_of=of, pred=lambda it: it["status"] == "open"
    )
    any_open = keep(
        items, got, any_mode=True, labels_of=of, pred=lambda it: it["status"] == "open"
    )
    assert every_open == []
    assert [it["id"] for it in any_open] == [1, 3]


def _book():
    return SimpleNamespace(_cn=object())


@pytest.fixture
def quiet_tx(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.db.request_tx", lambda cn, run: run())
    monkeypatch.setattr("agent_coord.server.records.db.in_request_tx", lambda cn: False)


def _patch_catalog(monkeypatch, puts):
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))

    def _apply(cn, typ, nid, names):
        puts.append((typ, nid, list(names)))

    monkeypatch.setattr(al, "apply_names", _apply)


def test_write_desk_name_is_skipped(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(_book(), "open", {"labels": ["ada"]}, "desk", lambda: {"id": 3})
    assert puts == []
    assert out["labels"] == []
    assert any("ada is a desk, not a label" in w for w in out["label_warnings"])


def test_write_zero_labels_leaves_the_result(quiet_tx):
    out = al.run_labeled(_book(), "open", {}, "desk", lambda: {"id": 1, "need": "n"})
    assert out == {"id": 1, "need": "n"}


@pytest.mark.parametrize(
    "command,body,result,typ,nid",
    [
        ("open", {}, {"id": 3}, "todo", 3),
        ("claim", {}, {"id": 4, "ok": True}, "todo", 4),
        ("assign", {}, {"id": 5}, "todo", 5),
        ("pass", {}, {"id": 6, "ok": True}, "todo", 6),
        ("send", {}, {"id": 7}, "mail", 7),
        ("reply", {}, {"id": 8}, "mail", 8),
        ("hold", {"resource": "gate"}, {"ok": True, "held": True, "id": 9}, "hold", 9),
        ("drop", {"resource": "gate"}, {"released": True, "id": 10}, "hold", 10),
        ("replace-body", {"type": "todo", "id": 11}, {"id": 11}, "todo", 11),
        ("todo", {"eta": "2h", "need": "n"}, {"id": 12}, "todo", 12),
        ("rename", {"name_type": "todo"}, {"id": 13, "ok": True}, "todo", 13),
    ],
)
def test_write_one_label(quiet_tx, monkeypatch, command, body, result, typ, nid):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(_book(), command, dict(body, labels=["rco"]), "desk", lambda: result)
    assert puts == [(typ, nid, ["rco"])]
    assert out["labels"] == ["rco"]
    assert out["label_warnings"] == []


def test_write_two_labels(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(_book(), "open", {"labels": ["rco", "windows"]}, "desk", lambda: {"id": 2})
    assert puts == [("todo", 2, ["rco", "windows"])]
    assert out["labels"] == ["rco", "windows"]


def test_write_unknown_still_sets_the_valid_label(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(
        _book(), "send", {"labels": ["rco", "nope"]}, "desk", lambda: {"id": 4}
    )
    assert puts == [("mail", 4, ["rco"])]
    assert out["labels"] == ["rco"]
    assert "does not exist" in out["label_warnings"][0]
    assert "mill create label nope" in out["label_warnings"][0]


def test_write_disallowed_is_skipped(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(_book(), "reply", {"labels": ["old"]}, "desk", lambda: {"id": 5})
    assert puts == []
    assert out["labels"] == []
    assert "may not be set" in out["label_warnings"][0]


def test_hold_not_taken_sets_nothing(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(
        _book(), "hold", {"resource": "gate", "labels": ["rco"]}, "desk",
        lambda: {"ok": False, "held": False, "id": 9},
    )
    assert puts == []
    assert out["labels"] == []
    assert "hold was not taken" in out["label_warnings"][0]


def test_wake_done_stale_sets_nothing(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(
        _book(), "wake-done", {"labels": ["rco"]}, "desk",
        lambda: {"ok": True, "wake": "stale", "lease": "stale"},
    )
    assert puts == []
    assert "ended nothing" in out["label_warnings"][0]


def test_unclaim_uses_the_card_id(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    monkeypatch.setattr(al, "_todo_id", lambda cn, body: 21)
    out = al.run_labeled(
        _book(), "unclaim", {"labels": ["rco"], "project": "p", "need": "n"}, "desk",
        lambda: {"ok": True, "need": "n", "status": "open"},
    )
    assert puts == [("todo", 21, ["rco"])]
    assert out["labels"] == ["rco"]


def test_pass_list_labels_only_the_cards_that_moved(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    result = {
        "ok": True,
        "results": [
            {"ok": True, "id": 1, "need": "a"},
            {"ok": False, "need": "b", "error": "no"},
        ],
    }
    out = al.run_labeled(_book(), "pass", {"labels": ["rco", "windows"]}, "desk", lambda: result)
    assert puts == [("todo", 1, ["rco", "windows"])]
    assert out["results"][0]["labels"] == ["rco", "windows"]
    assert "labels" not in out["results"][1]


def test_attach_labels_the_child(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    out = al.run_labeled(
        _book(), "attach",
        {"labels": ["rco"], "type_b": "todo", "id_b": 30},
        "desk", lambda: [{"ok": 1}],
    )
    assert puts == [("todo", 30, ["rco"])]
    assert out["rows"] == [{"ok": 1}]
    assert out["labels"] == ["rco"]


def test_score_point_is_still_refused(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)

    def boom():
        raise CoordError("score: desks only read scores")

    with pytest.raises(CoordError):
        al.run_labeled(_book(), "score", {"labels": ["rco"], "name": "k", "value": "1"}, "desk", boom)
    assert puts == []


def test_read_one_two_any_and_unknown(monkeypatch):
    items = [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    monkeypatch.setattr(
        al, "names_on",
        lambda cn, typ, ids: {1: {"rco"}, 2: {"rco", "windows"}},
    )
    one = al.run_labeled(_book(), "inbox", {"labels": ["rco"]}, "desk", lambda: list(items))
    assert [r["id"] for r in one["rows"]] == [1, 2]
    both = al.run_labeled(
        _book(), "todo", {"labels": ["rco", "windows"]}, "desk", lambda: list(items)
    )
    assert [r["id"] for r in both["rows"]] == [2]
    either = al.run_labeled(
        _book(), "todo", {"labels": ["rco", "windows"], "label_any": True}, "desk",
        lambda: list(items),
    )
    assert [r["id"] for r in either["rows"]] == [1, 2]
    missing = al.run_labeled(_book(), "inbox", {"labels": ["nope"]}, "desk", lambda: list(items))
    assert missing["rows"] == []
    assert "does not exist" in missing["label_warnings"][0]
    mixed = al.run_labeled(
        _book(), "inbox", {"labels": ["rco", "nope"], "label_any": True}, "desk", lambda: list(items)
    )
    assert [r["id"] for r in mixed["rows"]] == [1, 2]
    every_mixed = al.run_labeled(
        _book(), "inbox", {"labels": ["rco", "nope"]}, "desk", lambda: list(items)
    )
    assert every_mixed["rows"] == []
    assert every_mixed["label_warnings"]


def test_read_label_with_status_sees_only_matches(monkeypatch):
    items = [
        {"id": 1, "status": "open"},
        {"id": 2, "status": "open"},
        {"id": 3, "status": "done"},
    ]
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    monkeypatch.setattr(al, "names_on", lambda cn, typ, ids: {1: {"rco"}, 2: {"windows"}, 3: {"rco"}})
    wrapped = al.run_labeled(_book(), "todo", {"labels": ["rco"]}, "desk", lambda: items)
    opened = [r for r in wrapped["rows"] if r["status"] == "open"]
    assert [r["id"] for r in opened] == [1]


def test_hold_list_and_peek(monkeypatch):
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    monkeypatch.setattr(al, "names_on", lambda cn, typ, ids: {1: {"rco"}, 2: set()})
    listed = al.run_labeled(
        _book(), "hold", {"peek": True, "labels": ["rco"]}, "desk",
        lambda: {"ok": True, "holds": [{"id": 1, "resource": "a"}, {"id": 2, "resource": "b"}]},
    )
    assert [h["id"] for h in listed["holds"]] == [1]
    peeked = al.run_labeled(
        _book(), "hold", {"peek": True, "resource": "b", "labels": ["rco"]}, "desk",
        lambda: {"ok": True, "peek": True, "resource": "b", "id": 2, "held": True},
    )
    assert peeked["matched"] is False
    assert peeked["label_warnings"] == []


def test_connected_and_score_reads(monkeypatch):
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    monkeypatch.setattr(al, "names_on", lambda cn, typ, ids: {1: {"rco"}, 2: {"windows"}, 8: {"rco"}})
    live = al.run_labeled(
        _book(), "session", {"labels": ["windows"]}, "desk",
        lambda: [{"owner": "ada", "n": 2, "doings": [{"id": 1}, {"id": 2}]}],
    )
    assert live["rows"][0]["doings"] == [{"id": 2}]
    assert live["rows"][0]["n"] == 1
    score = al.run_labeled(
        _book(), "score", {"labels": ["windows"], "project": "p"}, "desk",
        lambda: {"score": "k", "id": 8},
    )
    assert score["scores"] == []
    assert score["label_warnings"] == []


def test_mail_thread_and_history_any(monkeypatch):
    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    monkeypatch.setattr(al, "names_on", lambda cn, typ, ids: {1: {"rco"}, 2: {"windows"}})
    thread = al.run_labeled(
        _book(), "mail-thread", {"labels": ["rco", "windows"], "label_any": True}, "desk",
        lambda: {"chain": [{"id": 1}, {"id": 2}, {"id": 3}]},
    )
    assert [c["id"] for c in thread["chain"]] == [1, 2]
    hist = al.run_labeled(
        _book(), "session",
        {"history": True, "labels": ["rco"], "page": 1},
        "desk",
        lambda: {"history": [
            {"id": 1, "src": "doing"},
            {"id": 2, "src": "doing"},
            {"id": 9, "src": "transition"},
        ], "page": {"n": 1, "of": 1, "size": 50, "entries": 3}},
    )
    assert [e["id"] for e in hist["history"]] == [1]
    assert hist["page"]["entries"] == 1


def test_parser_label_is_repeatable_and_invite_stays_a_string(monkeypatch):
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda cli="": "desk")
    from agent_coord.__main__ import _build_parser
    from agent_coord.client.outbound import body_from_args

    parser = _build_parser()
    args = parser.parse_args(["create", "todo", "r", "n", "--label", "rco", "--label", "windows"])
    assert args.label == ["rco", "windows"]
    body = body_from_args(args)
    assert body["verb"] == "open"
    assert body["labels"] == ["rco", "windows"]
    assert "label" not in body
    invite = parser.parse_args(["invite", "--label", "door"])
    ibody = body_from_args(invite)
    assert ibody["label"] == "door"
    assert "labels" not in ibody
    with pytest.raises(CoordError):
        body_from_args(parser.parse_args(["trail", "todo:1", "--label", "rco"]))


def test_emit_warnings_and_absorb_rows():
    import io

    buf = io.StringIO()
    row = {"ok": True, "result": {"_rows": True, "rows": [{"id": 1}], "labels": ["rco"], "label_warnings": ["label 'nope' does not exist. closest: none. mill create label nope."]}}
    lifted = al.absorb_rows(row)
    assert lifted["result"] == [{"id": 1}]
    assert lifted["labels"] == ["rco"]
    al.emit_warnings(lifted, file=buf)
    assert buf.getvalue().startswith("warning: label 'nope' does not exist.")


def test_replace_body_history_and_a_desk_rename_set_nothing(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    hist = al.run_labeled(
        _book(), "replace-body",
        {"type": "todo", "id": 11, "history": True, "labels": ["rco"]},
        "desk", lambda: {"history": []},
    )
    desk = al.run_labeled(
        _book(), "rename", {"name_type": "desk", "labels": ["rco"]}, "desk",
        lambda: {"ok": True},
    )
    assert puts == []
    assert "does not apply" in hist["label_warnings"][0]
    assert "does not apply" in desk["label_warnings"][0]


def test_wake_done_sets_the_wake_it_ended(quiet_tx, monkeypatch):
    puts = []
    _patch_catalog(monkeypatch, puts)
    monkeypatch.setattr(al, "wake_target", lambda cn, owner, body, result: 44)
    out = al.run_labeled(
        _book(), "wake-done", {"labels": ["rco"]}, "desk",
        lambda: {"ok": True, "wake": "sent", "lease": "sent"},
    )
    assert puts == [("wake", 44, ["rco"])]
    assert out["labels"] == ["rco"]


def test_trail_two_labels_every_and_any(monkeypatch):
    rows = {
        "rco": [{"type": "todo", "id": 1}, {"type": "todo", "id": 2}],
        "windows": [{"type": "todo", "id": 2}],
    }

    def one(tag):
        return {"label": tag, "hint": "", "rows": rows[tag], "truncated": False}

    monkeypatch.setattr(al, "resolve", lambda cn, raw, writing=False: classify(raw, CATALOG, _labels(), writing=writing))
    book = SimpleNamespace(_cn=object())
    one_label = al.trail_read(book, ["rco"], False, one)
    assert [r["id"] for r in one_label["rows"]] == [1, 2]
    every = al.trail_read(book, ["rco", "windows"], False, one)
    assert [r["id"] for r in every["rows"]] == [2]
    assert every["label_warnings"] == []
    either = al.trail_read(book, ["rco", "windows"], True, one)
    assert [r["id"] for r in either["rows"]] == [1, 2]
    missing = al.trail_read(book, ["nope"], False, one)
    assert missing["rows"] == []
    assert "does not exist" in missing["label_warnings"][0]
    assert "mill create label nope" in missing["label_warnings"][0]
