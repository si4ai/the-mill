"""Shared SQL arrange helpers for throwaway SQL suites (#34 get/put gate).

mill_name_get is SELECT-only. Tests that need project/desk/role/label rows
must mint them via mill_name_put (get_or_insert / host_put / join upsert),
not rely on read/list side effects.
"""
from __future__ import annotations

import os

import pytest

from agent_coord.server.records import name as rec_name


def seed_names(cn, *specs: tuple[str, str]) -> list[int]:
    """Intentional create via mill_name_put. Idempotent. Skips blanks.

    Each spec is (stored name, kind). The name is stored as given.
    """
    out: list[int] = []
    for spec in specs:
        name, kind = spec
        s = (name or "").strip()
        if not s:
            continue
        out.append(rec_name.get_or_insert(cn, s, kind))
    return out


def open_book(test_db: str):
    """Create test_db and apply the pack's SQL to it. Returns the connection.

    Skips only when MySQL does not answer. When it answers and the schema or a
    routine fails to apply, the suite fails (0.8.0, F168): a skip hid a broken
    apply behind a green run.
    """
    import mysql.connector

    from agent_coord.server import records
    from agent_coord.server.records.db import conn_kwargs

    try:
        kw = conn_kwargs()
        kw.pop("database", None)
        kw["autocommit"] = True
        admin = mysql.connector.connect(**kw)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{test_db}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    c = records.connect(test_db)
    try:
        records.apply(c, wipe=True)
    except Exception as e:
        pytest.fail(f"mill records: MySQL answered but the SQL did not apply: {e}", pytrace=False)
    return c


@pytest.fixture(scope="module")
def cn(request):
    """One wiped book per test module.

    Two modules in one process must not share a book. A read cursor left by
    test_room_reply would hide the branch on the next file.
    """
    from tests.sql_isolate import throwaway_db

    mod = request.module.__name__.rsplit(".", 1)[-1]
    test_db = throwaway_db("mill_" + mod)
    # connect() returns the process pool when the name matches the env book.
    # That pool stays on the first schema, and wipe.sql does not drop tree_read,
    # so the next module's mail ids restart on top of a stale read cursor.
    saved = os.environ.pop("AGENT_COORD_DATABASE", None)
    try:
        c = open_book(test_db)
    except BaseException:
        if saved is not None:
            os.environ["AGENT_COORD_DATABASE"] = saved
        raise
    try:
        yield c
    finally:
        c.close()
        if saved is None:
            os.environ.pop("AGENT_COORD_DATABASE", None)
        else:
            os.environ["AGENT_COORD_DATABASE"] = saved


ADMIN_DESK = "test-admin"


def admin_desk(cn, name: str = ADMIN_DESK) -> str:
    """A seated Admin desk to act as (0.8.0: sp_name_* check the acting desk). Idempotent."""
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as rec_join
    from agent_coord.server.records.db import call

    rec_join.upsert(cn, "Office", name, "", token_hash("seat-" + name), None)
    return make_admin(cn, name)


def make_admin(cn, name: str) -> str:
    """Put a seated desk on Admin (sp_admin_set as the host). Idempotent."""
    from agent_coord.server.records.db import call

    call(cn, "sp_admin_set", [None, name, 1])
    cn.commit()
    return name
