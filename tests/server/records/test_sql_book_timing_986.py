"""Card 986: time bare DROP+CREATE vs tip schema apply (report in CI log).

fresh_schema: owns a unique DB so the apply timing is not mixed into the
shared worker book.
"""
from __future__ import annotations

import time

import pytest

from tests import sql_book

# fresh_schema: measures full tip apply on a dedicated throwaway database
pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def test_drop_create_vs_schema_apply_timing(request) -> None:
    db = sql_book.fresh_db_name("mill_timing986", nodeid=request.node.nodeid)
    drop_s = sql_book.drop_database(db)
    create_s = sql_book.create_database(db)
    from agent_coord.server import records

    cn = records.connect(db)
    try:
        apply_s = sql_book.apply_tip(cn)
    finally:
        cn.close()
        sql_book.drop_database(db)
    sql_book.record_timing("bare_drop_s", drop_s)
    sql_book.record_timing("bare_create_s", create_s)
    sql_book.record_timing("bare_drop_create_s", drop_s + create_s)
    sql_book.record_timing("schema_apply_s", apply_s)
    # Always print so CI logs carry both numbers without opening the junit file.
    print(
        f"sql_book_timing986 drop={drop_s:.3f}s create={create_s:.3f}s "
        f"drop_create={drop_s + create_s:.3f}s apply={apply_s:.3f}s"
    )
    assert apply_s > 0
    assert drop_s + create_s >= 0
