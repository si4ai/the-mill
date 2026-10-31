"""todo of a project that is not in the book is a refusal (#226)."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import name as rec_name


pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn) -> None:
        self._cn = cn


def test_unknown_project_is_refused(cn) -> None:
    with pytest.raises(CoordError) as ei:
        rpc._h_todo(_Book(cn), {}, "f18-no-such-project", "f18-desk")
    assert "unknown project" in str(ei.value)
    assert "f18-no-such-project" in str(ei.value)


def test_known_empty_project_stays_an_empty_list(cn) -> None:
    rec_name.get_or_insert(cn, "f18-empty-project", "roster")
    assert rpc._h_todo(_Book(cn), {}, "f18-empty-project", "f18-desk") == []
