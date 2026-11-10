"""Card 1113: source-shape lock-order guard for the stored procedures (tools/sql_lock_order.py).

No database. The FK parents come from tables.sql. A procedure that takes a shared FK
lock on a parent row (an INSERT, or an UPDATE of an FK column) and later locks that
row FOR UPDATE (or updates it) is an S-to-X upgrade: two sessions on one row deadlock.
Lock-order cycles between procedures are listed; only the known ones below may stay.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from tools.sql_lock_order import SQL, Analyzer, load_fks

# Table-order cycles the check reports today; each is on different rows or a follow-up.
# A new cycle fails this test: lock seat (or the row both sides share) first instead.
KNOWN_CYCLES = {
    # Attach a card under a parent (activity row, then the plan's name row) vs delete or
    # retire of a mail or score (plan name row, then the item's activity row). Same rows
    # only when the parent is deleted while a card is filed under it. Card 1113 follow-up.
    ("activity", "name"),
    ("activity", "tree"),
    # join_upsert locks the desk's name, then the seat, then roster and role names (other
    # name rows); insert_attached and retire lock seat, then a plan or the same desk's name.
    ("name", "seat"),
}


def test_fk_parents_come_from_the_schema() -> None:
    text = (SQL / "tables.sql").read_text(encoding="utf-8")
    fks = load_fks(SQL)
    assert len(fks) == len(re.findall(r"FOREIGN\s+KEY", text, re.I))
    seat_children = {f.child for f in fks if f.parent == "seat"}
    assert {"todo", "doing", "activity", "mail", "mail_to", "watcher", "hold"} <= seat_children
    assert {f.parent for f in fks} >= {"seat", "name", "activity", "mail", "doing", "score"}


def test_no_procedure_upgrades_a_shared_fk_lock() -> None:
    an = Analyzer()
    found = {n: an.upgrades(n) for n in an.writers()}
    bad = {n: [(s.table, s.key, s.where, x.where) for s, x in u] for n, u in found.items() if u}
    assert not bad, bad


def test_lock_order_cycles_are_only_the_known_ones() -> None:
    got = {(a, b) for a, b, _p, _q in Analyzer().cycles()}
    assert got <= KNOWN_CYCLES, got - KNOWN_CYCLES
    assert ("seat", "todo") not in got  # every card write: seat, then card


def _planted(tmp_path: Path, file: str, old: str, new: str) -> Analyzer:
    sql = tmp_path / "sql"
    shutil.copytree(SQL, sql)
    path = sql / file
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")
    return Analyzer(sql)


SEAT_LOCK = "  SELECT id INTO v_move FROM seat WHERE desk_id = v_desk FOR UPDATE;\n  SET v_move = NULL;\n"


def test_check_flags_the_todo_insert_before_its_seat_lock(tmp_path: Path) -> None:
    # The planted error is mill_todo_insert as it was before card 1113: no seat lock first.
    an = _planted(tmp_path, "sp_todo.sql", SEAT_LOCK, "")
    for name in ("mill_todo_insert", "mill_todo_insert_attached"):
        ups = an.upgrades(name)
        assert ups, name
        s, x = ups[0]
        assert s.table == "seat" and s.why.startswith("fk todo."), (name, s)
        assert "mill_doing_move" in x.where, (name, x)


def test_check_flags_rename_without_its_seat_lock(tmp_path: Path) -> None:
    # The planted error is mill_todo_rename as it was before card 1113: card first, then seat.
    card = "  SELECT roster_id INTO v_proj FROM todo WHERE id = p_id FOR UPDATE;\n  IF v_proj IS NULL THEN\n" \
           "    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rename todo: no such card';"
    an = _planted(tmp_path, "sp_todo.sql", SEAT_LOCK + card, card)
    ups = an.upgrades("mill_todo_rename")
    assert ups and ups[0][0].table == "seat" and "todo.updated_id" in ups[0][0].why, ups
    assert ("seat", "todo") in {(a, b) for a, b, _p, _q in an.cycles()}
