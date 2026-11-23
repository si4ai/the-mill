"""Card 1280: a label-add on a trashed name is the office sentence, with no 1644 prefix."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.label_ord import TRASHED_LABEL
from agent_coord.server.api.mill import rpc


class _SqlRefusal(Exception):
    def __init__(self, msg: str) -> None:
        super().__init__("1644 (45000): %s" % msg)
        self.msg = msg
        self.sqlstate = "45000"
        self.errno = 1644


def _go(monkeypatch) -> None:
    monkeypatch.setattr(rpc, "_require_live_project", lambda cn, project, command: "Office")
    monkeypatch.setattr(rpc, "_occupant_type", lambda cn, name: "label")
    rpc._h_label(
        SimpleNamespace(_cn=object()),
        {"verb": "label-add", "type": "mail", "id": 1, "label": "old"},
        "Office",
        "grok-tui",
    )


def test_trashed_label_add_is_the_office_sentence(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.label.trashed_name", lambda cn, name: True)
    with pytest.raises(CoordError) as ei:
        _go(monkeypatch)
    assert str(ei.value) == TRASHED_LABEL
    assert "1644" not in str(ei.value) and "45000" not in str(ei.value)
    assert "mill create label" not in str(ei.value)


def test_raw_signal_loses_the_code_prefix(monkeypatch):
    monkeypatch.setattr("agent_coord.server.records.label.trashed_name", lambda cn, name: False)
    monkeypatch.setattr("agent_coord.config.mill_catalog_open", lambda kind: True)
    monkeypatch.setattr("agent_coord.server.records.name.get", lambda cn, name, kind="": None)

    def boom(*a, **k):
        raise _SqlRefusal(TRASHED_LABEL)

    monkeypatch.setattr("agent_coord.server.records.name.host_put", boom)
    with pytest.raises(CoordError) as ei:
        _go(monkeypatch)
    assert str(ei.value) == TRASHED_LABEL
    assert "1644" not in str(ei.value) and "45000" not in str(ei.value)
