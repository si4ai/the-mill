"""Card 1255: one helper marks a retired or trashed name on every activity row.

records.name_marks.mark_deleted gives each dict that refers to a soft-deleted
name a sorted deleted_names list, for all six activities (todo, mail, hold,
doing, wake, score). The rows stay; nothing is hidden. No MySQL: the name
lookup is passed in.
"""
from __future__ import annotations

import copy

import pytest

from agent_coord.server.records.name_marks import MARK_KEY, REF_KEYS, mark_deleted

GONE = {"old-roster", "old-desk", "old-label", "old-tree"}


def _lookup(seen: list[set[str]]):
    def look(names: set[str]) -> set[str]:
        seen.append(set(names))
        return {n.casefold() for n in names if n.casefold() in GONE}
    return look


ROWS = {
    "todo": {"type": "todo", "id": 1, "roster": "old-roster", "creator": "builder",
             "assigned": "old-desk", "tree": "old-tree", "labels": '["old-label", "builder"]'},
    "mail": {"id": 2, "from": "old-desk", "sender": {"deskId": "old-desk", "roster": "the-mill"},
             "mail_tos": [{"deskId": "wall-ui", "receipt": 0}], "to": ["wall-ui", "old-desk"]},
    "hold": {"id": 3, "roster_id": "Office", "resource": "res-x", "owner": "old-desk", "holder_dead": False},
    "doing": {"owner": "builder", "doings": [{"id": 4, "desk": "builder", "roster": "old-roster", "label": "old-label"}]},
    "wake": {"type": "wake", "desk": "old-desk", "at": "2026-11-21T01:00:00Z"},
    "score": {"id": 6, "roster_id": "old-roster", "kpi": "k", "value": "1", "target": "2", "owner": "builder"},
}
WANT = {
    "todo": [(("",), ["old-desk", "old-label", "old-roster", "old-tree"])],
    "mail": [(("",), ["old-desk"]), (("sender",), ["old-desk"])],
    "hold": [(("",), ["old-desk"])],
    "doing": [(("doings", 0), ["old-label", "old-roster"])],
    "wake": [(("",), ["old-desk"])],
    "score": [(("",), ["old-roster"])],
}


def _at(node, path):
    for p in path:
        if p != "":
            node = node[p]
    return node


@pytest.mark.parametrize("kind", sorted(ROWS))
def test_each_activity_keeps_the_row_and_marks_deleted_names(kind) -> None:
    payload = {"rows": [ROWS[kind]]}
    before = copy.deepcopy(payload)
    out = mark_deleted(None, payload, lookup=_lookup([]))
    assert payload == before  # input not changed
    row = out["rows"][0]
    for path, names in WANT[kind]:
        assert _at(row, path)[MARK_KEY] == names
    # every original field is still there, unchanged
    def strip(n):
        if isinstance(n, dict):
            return {k: strip(v) for k, v in n.items() if k != MARK_KEY}
        if isinstance(n, list):
            return [strip(x) for x in n]
        return n
    assert strip(out) == before


def test_live_names_get_no_key_and_one_lookup() -> None:
    seen: list[set[str]] = []
    payload = [{"roster": "the-mill", "volunteer": "builder", "id": 7, "node": "old-desk"}]
    out = mark_deleted(None, payload, lookup=_lookup(seen))
    assert out == payload and MARK_KEY not in out[0]
    assert seen == [{"the-mill", "builder"}]  # one read; non-reference keys are not names


def test_no_names_no_lookup() -> None:
    seen: list[set[str]] = []
    assert mark_deleted(None, {"n": 1, "rows": []}, lookup=_lookup(seen)) == {"n": 1, "rows": []}
    assert seen == []


def test_lookup_failure_leaves_rows_unmarked() -> None:
    def boom(_names):
        raise RuntimeError("book away")
    row = {"roster": "old-roster"}
    assert mark_deleted(None, row, lookup=boom) == row


def test_case_and_json_text_labels() -> None:
    out = mark_deleted(None, {"labels": '["Old-Label"]', "desk": "OLD-DESK"}, lookup=_lookup([]))
    assert out[MARK_KEY] == ["OLD-DESK", "Old-Label"]


def test_reference_keys_cover_every_activity_shape() -> None:
    for kind, row in ROWS.items():
        assert any(k in REF_KEYS for k in row) or kind == "doing"
