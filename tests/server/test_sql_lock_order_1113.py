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

# Open upgrades, listed with their card so they stay visible as warnings; a new one still fails.
# Empty: card 1113 fixed the wake, mail, join, plan and score procedures.
KNOWN_OPEN_UPGRADES: dict[str, str] = {}

# Two-table cycles at table level (most are on different rows: another desk's seat, another
# item). A new cycle fails this test.
KNOWN_CYCLES = {
    ("activity", "name"), ("activity", "score"), ("activity", "seat"), ("activity", "tree"),
    ("activity", "watcher"), ("hold", "seat"), ("member", "name"), ("name", "seat"),
    ("name", "watcher"), ("score", "seat"), ("seat", "tree"), ("seat", "watcher"),
    # Card writes take the acting desk's seat first (checked below); this cycle is another
    # desk's seat (volunteer or asker FK) asked for after the card.
    ("seat", "todo"),
    # A recipient's seat (FK check) after the letter, against delete's own seat then letter:
    # only when the deleting desk is added as a recipient of that letter at that moment.
    ("mail", "seat"),
    # sp_name_purge takes the purging desk's seat, then deletes the roster's members; a letter
    # to that roster reads its members, then the sender's seat FK: only when the purger sends.
    ("member", "seat"),
    # Card 1163: a pointer to name is name(id), so the parent check locks the primary key
    # and meets an exclusive lock on a name. These orders are a different row on each side
    # (a hold's resource versus a roster, a score's roster versus a plan, a plan versus a
    # roster written after the tree row).
    ("hold", "name"), ("name", "score"), ("name", "tree"),
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
    reclaim = [(lk.mode, lk.table, lk.why) for lk in an.locks("mill_todo_reclaim")]
    assert ("S", "todo", "subquery") in reclaim


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


# Card 1207: the planted check for mill_todo_insert without its seat lock is gone. The upgrade it caught was the
# seat FK read under the insert, then mill_doing_move's write; with the move as a transition row there is no
# later seat X, so the insert's seat lock only keeps the card writes' common order.


def test_check_flags_rename_without_its_seat_lock(tmp_path: Path) -> None:
    # The planted error is mill_todo_rename as it was before card 1113: card first, then seat.
    card = "  SELECT roster_id INTO v_proj FROM todo WHERE id = p_id FOR UPDATE;\n  IF v_proj IS NULL THEN\n" \
           "    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rename todo: no such card';"
    an = _planted(tmp_path, "sp_todo.sql", SEAT_LOCK + card, card)
    assert not _seat_before_card(an, "mill_todo_rename")
    assert _seat_before_card(Analyzer(), "mill_todo_rename")


@pytest.mark.parametrize("proc,old", [
    ("mill_todo_delete", "  SELECT id INTO v_seat FROM seat WHERE desk_id = v_seat FOR UPDATE;\n"
                         "  SELECT id INTO v_seat FROM todo WHERE id = p_id FOR UPDATE;\n  IF EXISTS (SELECT 1 FROM todo"),
    ("mill_todo_retire", "  SELECT id INTO v_seat FROM seat WHERE desk_id = v_desk FOR UPDATE;\n  SELECT roster_id INTO v_proj"),
])
def test_check_flags_a_card_write_without_its_seat_lock(tmp_path: Path, proc: str, old: str) -> None:
    # The planted error is the procedure as it was before card 1113: the card, then the seat FK.
    an = _planted(tmp_path, "sp_todo.sql", old, old.rsplit("\n", 1)[1])
    assert not _seat_before_card(an, proc)


@pytest.mark.parametrize("file,proc,old,new", [
    # The wake procedures as they were before card 1113: the transition copy first.
    ("sp_cmd.sql", "cmd_push_mark",
     "  SELECT COUNT(*) INTO v_lock FROM wake WHERE type = 'wake' AND id = p_push FOR UPDATE;\n"
     "  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role)\n"
     "  SELECT 'wake', id, state, p_outcome,", None),
    ("sp_push.sql", "mill_push_take", "FOR UPDATE;\n    SELECT p.id, p.cause", ";\n    SELECT p.id, p.cause"),
    # The joined-seat check before the seat lock.
    ("sp_join.sql", "mill_join_touch", None, None),
    # The plan lookup as a SET subquery.
    ("sp_tree.sql", "mill_tree_detach",
     "  SET v_name = NULL;\n  SELECT MIN(name_id) INTO v_name FROM tree WHERE type = p_type AND id = p_id;\n  WHILE",
     "  SET v_name = (SELECT MIN(name_id) FROM tree WHERE type = p_type AND id = p_id);\n  WHILE"),
])
def test_check_flags_each_fixed_shape_when_planted_back(tmp_path: Path, file: str, proc: str, old, new) -> None:
    if proc == "mill_join_touch":
        old = "  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;\n  IF v_desk IS NOT NULL AND EXISTS"
        new = "  IF v_desk IS NOT NULL AND EXISTS"
        text = (SQL / file).read_text(encoding="utf-8")
        i = text.index("CREATE PROCEDURE mill_join_touch(")
        sql = tmp_path / "sql"
        shutil.copytree(SQL, sql)
        body = text[i:text.index("END //", i)]
        assert old in body
        (sql / file).write_text(text[:i] + body.replace(old, new) + text[i + len(body):], encoding="utf-8")
        an = Analyzer(sql)
    else:
        if new is None:
            new = old.split("\n", 1)[1]
        an = _planted(tmp_path, file, old, new)
    assert an.upgrades(proc), proc
