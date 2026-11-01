"""Shared SQL arrange helpers for throwaway SQL suites (#34 get/put gate).

mill_name_get is SELECT-only. Tests that need project/desk/role/label rows
must mint them via mill_name_put (get_or_insert / host_put / join upsert),
not rely on read/list side effects.

Card 986: module ``cn`` reuses one tip schema per xdist worker and only
clears table data between modules. Schema/migration/parity suites use
``fresh_schema`` instead (see tests/sql_book.py).
"""
from __future__ import annotations

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


def open_book(test_db: str, *, fresh: bool = False, request=None):
    """Open a tip book.

    Default (fresh=False): worker shared schema; apply once; reset data.
    ``test_db`` is ignored on the shared path (kept for call-site compatibility).
    fresh=True: unique DB + full apply + DROP finalizer (needs request).
    """
    from tests import sql_book

    if fresh:
        if request is None:
            raise TypeError("open_book(fresh=True) needs request for finalizer")
        return sql_book.open_fresh_book(
            test_db or "mill_fresh",
            nodeid=getattr(request.node, "nodeid", test_db),
            finalizer_register=request.addfinalizer,
        )
    # Shared path: ignore per-module names so every module shares one apply.
    try:
        return sql_book.connect_shared(reset=True)
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")


ADMIN_DESK = "test-admin"


def admin_desk(cn, name: str = ADMIN_DESK) -> str:
    """A seated Admin desk to act as (0.8.0: sp_name_* check the acting desk). Idempotent."""
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as rec_join

    rec_join.upsert(cn, "Office", name, "", token_hash("seat-" + name), None)
    return make_admin(cn, name)


def make_admin(cn, name: str) -> str:
    """Put a seated desk on Admin (sp_admin_set as the host). Idempotent."""
    from agent_coord.server.records.db import call

    call(cn, "sp_admin_set", [None, name, 1])
    cn.commit()
    return name
