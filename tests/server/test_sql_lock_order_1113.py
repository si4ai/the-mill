"""Card 1113: source-shape lock-order guard for the stored procedures (tools/sql_lock_order.py).

No database. The FK parents come from tables.sql. A procedure that takes a shared FK
lock on a parent row (an INSERT, or an UPDATE of an FK column) and later locks that
row FOR UPDATE (or updates it) is an S-to-X upgrade: two sessions on one row deadlock.
Lock-order cycles between procedures are listed; only the known ones below may stay.
A routine's IF EXISTS (SELECT ...), SET x = (SELECT ...), INSERT ... SELECT and DML subqueries
read with shared locks (performance_schema.data_locks); a plain SELECT ... INTO does not.
"""
from __future__ import annotations

import re
import shutil
import warnings
from pathlib import Path

import pytest

from tools.sql_lock_order import SQL, Analyzer, load_fks

# Open upgrades outside the card procedures (card 1113, second PR: wake, mail, join, tree,
# score). Listed so they stay visible as warnings; a new one still fails. Empty when fixed.
_WAKE = "card 1113 PR B: wake transition copy (shared) then update"
_SEAT = "card 1113 PR B: IF EXISTS on the seat (shared in a routine) then update the seat"
_TREE = "card 1113 PR B: IF EXISTS on the item's tree rows, then the plan lock and tree FOR UPDATE"
KNOWN_OPEN_UPGRADES = {
    "cmd_push_mark": _WAKE, "cmd_push_put_back": _WAKE, "cmd_push_sent": _WAKE, "mill_push_take": _WAKE,
    "mill_join_connect": _SEAT, "mill_join_delete": _SEAT, "mill_join_touch": _SEAT,
    "mill_join_wake_arm": _SEAT, "mill_join_wake_off": _SEAT,
    "mill_mail_update": "card 1113 PR B: IF EXISTS on the letter then update it",
    "mill_mail_delete": "card 1113 PR B: letter and tree reads then delete",
    "mill_score_delete": _TREE, "mill_score_retire": _TREE, "mill_tree_detach": _TREE, "mill_tree_remove": _TREE,
}

# Two-table cycles at table level (most are on different rows); card 1113 PR B reviews each.
# A new cycle fails this test.
KNOWN_CYCLES = {
    ("activity", "name"), ("activity", "score"), ("activity", "seat"), ("activity", "tree"),
    ("activity", "watcher"), ("hold", "seat"), ("mail", "name"), ("mail", "tree"),
    ("member", "name"), ("name", "seat"), ("name", "tree"), ("name", "watcher"),
    ("score", "seat"), ("seat", "tree"), ("seat", "watcher"),
    # Card writes take the acting desk's seat first (checked below); this cycle is another
    # desk's seat (volunteer or asker FK) asked for after the card.
    ("seat", "todo"),
}

# Card procedures: the acting desk's seat must come before the card row (F183).
CARD_PROCS = (
    "mill_todo_insert", "mill_todo_insert_attached", "mill_todo_write", "mill_todo_update",
    "mill_todo_rename", "mill_todo_delete", "mill_todo_retire", "mill_todo_reclaim",
    "cmd_claim", "cmd_unclaim", "cmd_pass",
)


def test_fk_parents_come_from_the_schema() -> None:
    text = (SQL / "tables.sql").read_text(encoding="utf-8")
    fks = load_fks(SQL)
    assert len(fks) == len(re.findall(r"FOREIGN\s+KEY", text, re.I))
    seat_children = {f.child for f in fks if f.parent == "seat"}
    assert {"todo", "doing", "activity", "mail", "mail_to", "watcher", "hold"} <= seat_children
    assert {f.parent for f in fks} >= {"seat", "name", "activity", "mail", "doing", "score"}


def test_no_procedure_upgrades_a_shared_lock() -> None:
    an = Analyzer()
    found = {n: an.upgrades(n) for n in an.writers()}
    bad = {n: [(s.table, s.key, s.where, x.where) for s, x in u] for n, u in found.items() if u}
    for n in sorted(set(bad) & set(KNOWN_OPEN_UPGRADES)):
        warnings.warn(f"known open lock upgrade: {n} ({KNOWN_OPEN_UPGRADES[n]})", stacklevel=1)
    new = {n: v for n, v in bad.items() if n not in KNOWN_OPEN_UPGRADES}
    assert not new, new
    assert not any(n.startswith(("mill_todo_", "cmd_claim", "cmd_unclaim", "cmd_pass")) for n in bad), bad


def test_insert_select_and_subquery_reads_are_shared_locks() -> None:
    an = Analyzer()
    take = [(lk.mode, lk.table, lk.why) for lk in an.locks("mill_push_take")]
    assert ("S", "wake", "insert-select") in take
    node = [(lk.mode, lk.table, lk.why) for lk in an.locks("mill_mail_to_node_delete")]
    assert ("S", "tree", "subquery") in node


def test_lock_order_cycles_are_only_the_known_ones() -> None:
    got = {(a, b) for a, b, _p, _q in Analyzer().cycles()}
    assert got <= KNOWN_CYCLES, got - KNOWN_CYCLES


def _seat_before_card(an: Analyzer, name: str) -> bool:
    locks = an.locks(name)
    seat = next((i for i, lk in enumerate(locks) if lk.table == "seat" and lk.mode == "X"), None)
    card = next((i for i, lk in enumerate(locks) if lk.table == "todo"), None)
    return card is None or (seat is not None and seat < card)


def test_card_procedures_lock_the_desk_seat_before_the_card() -> None:
    an = Analyzer()
    late = [n for n in CARD_PROCS if not _seat_before_card(an, n)]
    assert not late, late


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
    assert not _seat_before_card(an, "mill_todo_rename")


@pytest.mark.parametrize("proc,old", [
    ("mill_todo_delete", "  SELECT id INTO v_seat FROM seat WHERE desk_id = v_seat FOR UPDATE;\n"
                         "  SELECT id INTO v_seat FROM todo WHERE id = p_id FOR UPDATE;\n  IF EXISTS (SELECT 1 FROM todo"),
    ("mill_todo_retire", "  SELECT id INTO v_seat FROM seat WHERE desk_id = v_desk FOR UPDATE;\n  SELECT roster_id INTO v_proj"),
])
def test_check_flags_a_card_write_without_its_seat_lock(tmp_path: Path, proc: str, old: str) -> None:
    # The planted error is the procedure as it was before card 1113: the card, then the seat FK.
    an = _planted(tmp_path, "sp_todo.sql", old, old.rsplit("\n", 1)[1])
    assert not _seat_before_card(an, proc)
