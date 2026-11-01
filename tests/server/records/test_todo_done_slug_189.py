"""#189: a done card looked up by slug or number is the card, never a bare []."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo
from tests.server.records.conftest import seed_names
from tests.server.records.test_probe_delete import _Book, _probe

FIX = "t-0a1b2c3d"

@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("pk_real", "roster"), (FIX, "roster"), ("pk_me", "desk"))
    yield c
    c.close()

def _to_done(cn, slug_s: str) -> int:
    """Open, claim, pass to shipped, pass to done. Creator is the asker and the volunteer."""
    tid = int(todo.insert(cn, "pk_real", "pk_me", "open", todo.pack({"slug": slug_s}))[0]["id"])
    book = _Book(cn)
    rpc._h_claim(book, {"need": slug_s}, "pk_real", "pk_me")
    rpc._h_pass(book, {"need": slug_s}, "pk_real", "pk_me")
    rpc._h_pass(book, {"need": slug_s, "step": "done"}, "pk_real", "pk_me")
    return tid

def test_done_slug_and_number_return_the_card(cn) -> None:
    slug_s = "pk-done-slug"
    tid = _to_done(cn, slug_s)
    book = _Book(cn)
    by_slug = rpc._h_todo(book, {"need": slug_s}, "pk_real", "pk_me")
    assert [int(r["id"]) for r in by_slug] == [tid]
    assert by_slug[0]["status"] == "done"
    assert by_slug[0]["need_id"] == slug_s
    by_num = rpc._h_todo(book, {"need": str(tid)}, "pk_real", "pk_me")
    assert [int(r["id"]) for r in by_num] == [tid]
    assert by_num[0]["status"] == "done"
    assert by_num[0]["need_id"] == slug_s
    board = {int(r["id"]) for r in rpc._h_todo(book, {}, "pk_real", "pk_me")}
    assert tid not in board

def test_deleted_number_refuses(cn) -> None:
    tid = int(todo.insert(cn, FIX, "pk_me", "open", todo.pack({"slug": "pk-gone-189"}))[0]["id"])
    _probe(cn, "pk_me", "todo", tid)
    book = _Book(cn)
    with pytest.raises(CoordError, match=r"todo: no card %s in pk_real; it is deleted" % tid):
        rpc._h_todo(book, {"need": str(tid)}, "pk_real", "pk_me")

def test_unknown_slug_refuses(cn) -> None:
    book = _Book(cn)
    with pytest.raises(CoordError, match=r"todo: no card pk-missing in pk_real"):
        rpc._h_todo(book, {"need": "pk-missing"}, "pk_real", "pk_me")
