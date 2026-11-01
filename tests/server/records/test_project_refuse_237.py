"""hold refuses an unknown project before writing (#237)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _count(cn) -> int:
    cur = cn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM hold")
        return int(cur.fetchone()[0])
    finally:
        cur.close()


def test_unknown_retired_empty_and_valid(cn) -> None:
    seed_names(cn, ("c237", "roster"), ("c237-gone", "roster"), ("c237-desk", "desk"))
    rec_name.retire(cn, "c237-gone", "roster", by=admin_desk(cn))
    book = _Book(cn)
    before = _count(cn)

    for command, fn in (("hold", rpc._h_hold),):
        # 0.7.x: an empty roster on hold means Office (holds take no roster).
        for project in ("c237-missing", "c237-gone"):
            with pytest.raises(CoordError) as ei:
                fn(book, {"resource": "c237-lock"}, project, "c237-desk")
            text = str(ei.value)
            assert text.startswith(command + ": no such roster")
            assert "rosters:" in text
            assert "mill member" in text
            listed = text.split("rosters: ", 1)[1].split(". list them:", 1)[0]
            parts = [p.strip() for p in listed.split(",")]
            assert "c237" in parts
            assert "c237-gone" not in parts
            assert "c237-missing" not in parts
            text.encode("ascii")
    assert _count(cn) == before

    taken = rpc._h_hold(
        book, {"resource": "c237-lock"}, "c237", "c237-desk"
    )
    assert taken["ok"] is True
    assert _count(cn) == before + 1


def test_project_command_for_connect(cn) -> None:
    seed_names(cn, ("c237b", "roster"), ("c237b-gone", "roster"))
    rec_name.retire(cn, "c237b-gone", "roster", by=admin_desk(cn))
    book = _Book(cn)
    for project in ("c237b-missing", "c237b-gone", "", "   "):
        with pytest.raises(CoordError) as ei:
            rpc._h_project(book, {"project": project}, "the-mill", "d")
        text = str(ei.value)
        assert text.startswith("connect: no such roster")
        assert "mill member" in text
        parts = [p.strip() for p in text.split("rosters: ", 1)[1].split(". list them:", 1)[0].split(",")]
        assert "c237b" in parts and "c237b-gone" not in parts
    ok = rpc._h_project(book, {"project": "c237b"}, "c237b", "d")
    assert ok["ok"] is True and ok["project"] == "c237b"
    assert "c237b" in ok["projects"]
