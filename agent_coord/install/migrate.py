"""Mill schema ensure. Init and Coord both run this. No session tokens here.

Fresh office / attempt 2: apply agent_coord/server/sql/ (wipe + tables + fn_ + sp_).
sql/ is not a migrate ladder.
"""

from __future__ import annotations

import json
import functools
import hashlib
import re
from pathlib import Path
from typing import Any

_IDENT = re.compile(r"^[A-Za-z0-9_]{1,64}$")

_ALTER_TABLE = re.compile(
    r"^ALTER\s+TABLE\s+(`?[A-Za-z0-9_]+`?)\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_ADD_COLUMN = re.compile(
    r"ADD\s+COLUMN\s+(`?[A-Za-z0-9_]+`?)\s+(.+?)(?=,\s*ADD\s+|\s*$)",
    re.IGNORECASE | re.DOTALL,
)
_ADD_KEY = re.compile(
    r"ADD\s+(?:CONSTRAINT\s+`?[A-Za-z0-9_]+`?\s+)?"
    r"(?:UNIQUE\s+)?(?:KEY|INDEX)\s+(`?[A-Za-z0-9_]+`?)\s*\(([^)]+)\)",
    re.IGNORECASE,
)


def _split_sql(blob: str) -> list[str]:
    cleaned: list[str] = []
    for line in blob.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        if "--" in line:
            line = line[: line.index("--")]
        cleaned.append(line)
    out: list[str] = []
    for stmt in "\n".join(cleaned).split(";"):
        stmt = stmt.strip()
        if stmt:
            out.append(stmt)
    return out


def schema_path() -> Path:
    """0.4 book is sql/tables.sql (v1 schema.sql is gone)."""
    return sql_dir() / "tables.sql"


def sql_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "server" / "sql"


def sql_apply_order() -> list[Path]:
    """Files in sql/apply_order.txt. Missing names skipped."""
    root = sql_dir()
    order = root / "apply_order.txt"
    names: list[str] = []
    if order.is_file():
        for line in order.read_text(encoding="utf-8-sig").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    else:
        names = sorted(p.name for p in root.glob("*.sql"))
    out: list[Path] = []
    for name in names:
        p = root / name
        if p.is_file():
            out.append(p)
    return out


def split_script(blob: str) -> list[str]:
    """Split SQL; honor DELIMITER (client-only, not sent to the server)."""
    delim = ";"
    buf: list[str] = []
    stmts: list[str] = []
    for raw in blob.splitlines():
        line = raw
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER "):
            chunk = "".join(buf).strip()
            if chunk:
                stmts.append(chunk if not chunk.endswith(delim) else chunk[: -len(delim)].strip())
            buf = []
            delim = stripped.split(None, 1)[1].strip() or ";"
            continue
        if stripped.startswith("--"):
            continue
        buf.append(line)
        buf.append("\n")
        joined = "".join(buf)
        if delim and joined.rstrip().endswith(delim):
            stmt = joined.rstrip()[: -len(delim)].strip()
            if stmt:
                stmts.append(stmt)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def apply_records(cn, *, wipe: bool = False) -> dict[str, Any]:
    """Apply agent_coord/server/sql/. wipe=True runs wipe.sql first (drops v1 mill-loop tables)."""
    cur = cn.cursor()
    applied: list[str] = []
    try:
        try:
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
        except Exception:
            pass
        dropped_functions = False
        for path in sql_apply_order():
            if path.name == "wipe.sql" and not wipe:
                continue
            # MySQL stores the CREATE spelling. Drop every function, then the
            # fn_ files create them again (ALL CAPS). The clock is absent until
            # fn_now.sql runs.
            if not wipe and not dropped_functions and path.stem.startswith("fn_"):
                n = _drop_functions(cur)
                applied.append(f"functions(drop {n})")
                dropped_functions = True
            blob = path.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                _apply_stmt(cur, stmt)
            applied.append(path.name)
        cn.commit()
        return {"applied": applied}
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def _drop_functions(cur) -> int:
    cur.execute(
        "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'FUNCTION'"
    )
    names = [row[0] for row in cur.fetchall() if row and row[0]]
    for name in names:
        cur.execute(f"DROP FUNCTION IF EXISTS `{_ident(str(name))}`")
    return len(names)


def _ident(name: str) -> str:
    name = name.strip().strip("`")
    if not _IDENT.match(name):
        raise ValueError(f"bad SQL identifier: {name!r}")
    return name


def _table_exists(cur, table: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s LIMIT 1",
        (table,),
    )
    return cur.fetchone() is not None


def _column_exists(cur, table: str, col: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s "
        "LIMIT 1",
        (table, col),
    )
    return cur.fetchone() is not None


def _index_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s "
        "LIMIT 1",
        (table, name),
    )
    return cur.fetchone() is not None


def _apply_stmt(cur, stmt: str) -> None:
    """Execute one SQL statement; skip ADD COLUMN / ADD KEY that already exist.

    MySQL DDL often auto-commits, so a multi-statement apply can leave columns
    applied while agent_schema_meta.version stays behind - re-run must not 1060.
    """
    def _run(sql: str) -> None:
        cur.execute(sql)
        # PREPARE/EXECUTE of SELECT 1 and similar leave a result set; drain it.
        while True:
            if getattr(cur, "with_rows", False):
                cur.fetchall()
            if not hasattr(cur, "nextset") or not cur.nextset():
                break

    m = _ALTER_TABLE.match(stmt.strip())
    if not m:
        _run(stmt)
        return
    table = _ident(m.group(1))
    clause_blob = m.group(2).strip()
    if not re.match(r"^ADD\s+", clause_blob, re.IGNORECASE):
        cur.execute(stmt)
        return

    cols = list(_ADD_COLUMN.finditer(clause_blob))
    keys = list(_ADD_KEY.finditer(clause_blob))
    if not cols and not keys:
        _run(stmt)
        return

    new_clauses: list[str] = []
    for am in cols:
        col = _ident(am.group(1))
        if _column_exists(cur, table, col):
            continue
        spec = am.group(2).strip().rstrip(",").strip()
        new_clauses.append(f"ADD COLUMN `{col}` {spec}")
    for km in keys:
        name = _ident(km.group(1))
        if _index_exists(cur, table, name):
            continue
        col_list = km.group(2).strip()
        new_clauses.append(f"ADD KEY `{name}` ({col_list})")

    if not new_clauses:
        return
    cur.execute(f"ALTER TABLE `{table}` " + ", ".join(new_clauses))


def _ensure_watcher_hint(cn) -> list[str]:
    """Alpha additive: watcher.hint + mill_watcher_* refresh (no full wipe)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        _apply_stmt(
            cur,
            "ALTER TABLE watcher ADD COLUMN hint "
            "VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL",
        )
        if _column_exists(cur, "watcher", "hint"):
            applied.append("watcher.hint")
        # Refresh watcher procedures from sp_activity.sql (set_hint + select hint)
        sp = sql_dir() / "sp_activity.sql"
        if sp.is_file():
            blob = sp.read_text(encoding="utf-8-sig")
            keep = (
                "mill_watcher_put",
                "mill_watcher_roster",
                "mill_watcher_delete",
                "mill_watcher_select",
                "mill_watcher_set_hint",
            )
            for stmt in split_script(blob):
                s = stmt.strip()
                low = s.lower()
                if any(k in low for k in ("drop procedure if exists mill_watcher", "create procedure mill_watcher")):
                    if any(k in low for k in keep) or "mill_watcher" in low:
                        _apply_stmt(cur, stmt)
            applied.append("sp_watcher_hint")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied



# Whole-file procedure refresh. Every DROP/CREATE PROCEDURE in these files is
# re-applied on each ensure. mill_join_upsert and mill_member_put/delete once
# called mill_watcher_put/delete('name', ...). Tip mill_watcher_* take
# ENUM('todo','doing','hold','score') (#818; 'join' before), so a stale caller fails the seat mint.
# sp_name.sql rides along (name_type shape: mill_name_host/delete/rename/reclaim).
# Order: after _ensure_watcher_hint so the callees are tip first.
# sp_hold.sql: an existing book must pick up the #194 re-hold refresh in mill_hold_upsert.
# sp_label.sql: mill_label_delete must refuse an unknown name (#202).
# sp_mail.sql: mill_mail_select takes the desk only (#201). A 3-arg leftover must be replaced.
# sp_mail/sp_todo/sp_score (#216): payload-first inserts and no FOREIGN_KEY_CHECKS toggles
# in any writer, so every procedure in those files must reach an existing book.
_SP_FULL_REFRESH: tuple[str, ...] = (
    "sp_name.sql",
    "sp_member.sql",
    "sp_mail.sql",
    "sp_todo.sql",
    "sp_join.sql",
    "sp_doing.sql",  # #818 PR B: mill doing write, now and history reads
    "sp_hold.sql",
    "sp_score.sql",
    "sp_label.sql",
    "sp_tree.sql",
    "sp_cmd.sql",  # card 1022 R3: cmd_push_sent/put_back/mark write transitions
)

# #216: activity is the timeline, not a parent. A payload row is written first and its
# table assigns the id, so these FKs from payload to activity are dropped on an existing
# book. fk_label_activity and fk_tree_activity stay (they point at a row that exists).
_PAYLOAD_ACTIVITY_FKS: tuple[tuple[str, str], ...] = (
    ("mail", "fk_mail_activity"),
    ("todo", "fk_todo_activity"),
    ("join", "fk_join_activity"),  # pre-#818 books; the 818 migration renames join to doing
    ("hold", "fk_hold_activity"),
    ("score", "fk_score_activity"),
)


def _fk_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s "
        "AND CONSTRAINT_TYPE = 'FOREIGN KEY'",
        (table, name),
    )
    row = cur.fetchone()
    return bool(row and int(row[0]) > 0)


def _ensure_payload_fk_drop(cn) -> list[str]:
    """#216: drop payload -> activity FKs when present. Idempotent (no-op once gone)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        for table, name in _PAYLOAD_ACTIVITY_FKS:
            if not _table_exists(cur, table):
                continue
            if _fk_exists(cur, table, name):
                cur.execute(f"ALTER TABLE `{_ident(table)}` DROP FOREIGN KEY `{_ident(name)}`")
                applied.append(f"drop:{name}")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_sp_full(cn) -> list[str]:
    """Alpha: refresh every procedure in _SP_FULL_REFRESH from tip (no tables, no wipe)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        for path_name in _SP_FULL_REFRESH:
            sp = sql_dir() / path_name
            if not sp.is_file():
                continue
            blob = sp.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                low = stmt.strip().lower()
                if low.startswith("drop procedure") or low.startswith("create procedure"):
                    _apply_stmt(cur, stmt)
            applied.append(path_name)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


# #722: functions an existing book refreshes from tip (Office alias of roster id 1).
_FN_REFRESH: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fn_name.sql", ("mill_name_get", "mill_name_put")),
    # #818 PR B: when a doing entry ended (its own event, or cleared).
    ("sp_doing.sql", ("mill_doing_end", "mill_doing_cleared")),
)


def _ensure_fn_refresh(cn) -> list[str]:
    """Refresh the named stored functions from tip (no tables, no wipe)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        for path_name, keep in _FN_REFRESH:
            sp = sql_dir() / path_name
            if not sp.is_file():
                continue
            blob = sp.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                low = stmt.strip().lower()
                m = re.match(r"(?:drop|create)\s+function\s+(?:if\s+exists\s+)?`?(\w+)", low)
                if m and m.group(1) in keep:
                    _apply_stmt(cur, stmt)
            applied.append(path_name + ":functions")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_activity_soft_delete(cn) -> list[str]:
    """Alpha additive: activity.deleted + soft-delete *_delete + mill_activity_select/mill_between state."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        _apply_stmt(
            cur,
            "ALTER TABLE activity ADD COLUMN deleted "
            "DATETIME(6) NULL AFTER updated",
        )
        if _column_exists(cur, "activity", "deleted"):
            applied.append("activity.deleted")
        # BEFORE DELETE tree guards (human addendum / soft-delete #89).
        tables = sql_dir() / "tables.sql"
        if tables.is_file():
            blob = tables.read_text(encoding="utf-8-sig")
            keep = (
                "todo_no_delete_in_tree",
                "mail_no_delete_in_tree",
                "hold_no_delete_in_tree",
                "hold_no_delete",
                "join_no_delete_in_tree",  # DROP only: pre-#818 books (#818 renames join to doing)
                "doing_no_delete_in_tree",
                "score_no_delete_in_tree",
                "name_no_delete",
            )
            for stmt in split_script(blob):
                low = stmt.strip().lower()
                if not (
                    low.startswith("drop trigger") or low.startswith("create trigger")
                ):
                    continue
                if any(k in low for k in keep):
                    _apply_stmt(cur, stmt)
            applied.append("no_delete_in_tree_triggers")
        # Refresh delete + select procedures (bucket/span untouched).
        for path_name, keep in (
            # 0.6.13 writer gaps: mail insert (payload first, LAST_INSERT_ID, then activity #216; project|role),
            # to_put (no project mint), hold release + reclaim gate, score delete (p_id, p_desk).
            ("sp_mail.sql", ("mill_mail_delete", "mill_mail_insert", "mill_mail_to_put")),
            # Delete SPs take the card off every tree plan (mill_tree_detach, children move up).
            ("sp_tree.sql", ("mill_tree_remove", "mill_tree_detach")),
            ("sp_todo.sql", ("mill_todo_delete", "mill_todo_select", "mill_todo_insert", "mill_todo_insert_attached")),
            ("sp_score.sql", (
                "mill_score_delete",
                "mill_score_upsert",
                "mill_score_admin_upsert",
                "mill_score_select",
                "mill_score_event",
                "mill_wall_event",
                "mill_score_evidence_purge",
            )),  # F2 revive in upsert; #204 purge is not part of the write
            ("sp_join.sql", ("mill_join_reset",)),
            ("sp_hold.sql", ("mill_hold_delete", "mill_hold_release_other")),
            ("sp_name.sql", ("mill_name_reclaim",)),
            ("sp_floor_scope.sql", ("mill_floor_part",)),  # perf: JOIN mill_floor_desk, mail dests
            # state any type (#91); mill_span reads Office by id 1 (#722).
            ("sp_activity.sql", ("mill_activity_select", "mill_activity_get", "mill_between", "mill_span")),
        ):
            sp = sql_dir() / path_name
            if not sp.is_file():
                continue
            blob = sp.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                s = stmt.strip()
                low = s.lower()
                if not (
                    low.startswith("drop procedure") or low.startswith("create procedure")
                ):
                    continue
                if any(k in low for k in keep):
                    _apply_stmt(cur, stmt)
            applied.append(path_name + ":soft_delete_state")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied



# FK delete rules flipped on an existing book (tables.sql covers a new book).
# (table, constraint, columns, ref_table, ref_columns, rule)
# Every mill FK to name is RESTRICT. Payloads have no FK to activity (#216, see
# _PAYLOAD_ACTIVITY_FKS); do not list one here or ensure would add it back.
# Kept as they are: fk_label_activity (CASCADE), fk_mail_to_mail (CASCADE), human_* FKs.
_FK_RULES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("seat", "fk_seat_desk", "desk_id", "name", "id", "RESTRICT"),  # #96 (#818: was join)
    ("doing", "fk_doing_desk", "desk_id", "name", "id", "RESTRICT"),  # #818
    ("doing", "fk_doing_roster", "roster_id", "name", "id", "RESTRICT"),  # #818
    ("score_evidence", "fk_score_evidence_score", "score_id", "score", "id", "RESTRICT"),  # #95
    ("score_point", "fk_score_point_score", "score_id", "score", "id", "RESTRICT"),  # #288
    ("score_point", "fk_score_point_desk", "desk_id", "name", "id", "RESTRICT"),  # #288
    ("activity", "fk_activity_desk", "desk_id", "name", "id", "RESTRICT"),  # F1
    ("activity", "fk_activity_roster", "roster_id", "name", "id", "RESTRICT"),
    ("member", "fk_member_name", "name_id", "name", "id", "RESTRICT"),
    ("member", "fk_member_desk", "desk_id", "name", "id", "RESTRICT"),
    ("label", "fk_label_name", "name_id", "name", "id", "RESTRICT"),
    ("tree", "fk_tree_name", "name_id", "name", "id", "RESTRICT"),
    ("tree", "fk_tree_activity", "type,id", "activity", "type,id", "RESTRICT"),
    ("watcher", "fk_watcher_desk", "desk_id", "name", "id", "RESTRICT"),
    ("mail", "fk_mail_desk", "desk_id", "name", "id", "RESTRICT"),
    ("mail", "fk_mail_roster", "roster_id", "name", "id", "RESTRICT"),
    ("mail_to", "fk_mail_to_desk", "desk_id", "name", "id", "RESTRICT"),
    ("todo", "fk_todo_roster", "roster_id", "name", "id", "RESTRICT"),
    ("todo", "fk_todo_updated", "updated_id", "name", "id", "RESTRICT"),
    ("todo", "fk_todo_creator", "creator_id", "name", "id", "RESTRICT"),
    ("todo", "fk_todo_assigned", "assigned_id", "name", "id", "RESTRICT"),
    ("hold", "fk_hold_desk", "desk_id", "name", "id", "RESTRICT"),
    ("hold", "fk_hold_res", "resource_id", "name", "id", "RESTRICT"),
    ("score", "fk_score_roster", "roster_id", "name", "id", "RESTRICT"),
    ("score", "fk_score_desk", "desk_id", "seat", "desk_id", "RESTRICT"),
    ("wake", "fk_wake_desk", "desk_id", "seat", "desk_id", "RESTRICT"),
)


def _cols(spec: str) -> str:
    return ", ".join(f"`{_ident(c)}`" for c in spec.split(","))


def _fk_delete_rule(cur, table: str, name: str) -> str | None:
    cur.execute(
        "SELECT DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
        "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s "
        "LIMIT 1",
        (table, name),
    )
    row = cur.fetchone()
    return None if row is None else str(row[0]).upper()


def _ensure_fk_rules(cn) -> list[str]:
    """Alpha: drop + re-add FKs whose ON DELETE rule changed (#95 / #96 / F1 / name RESTRICT). Idempotent."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        for table, name, col, ref, ref_col, rule in _FK_RULES:
            if not _table_exists(cur, table):
                continue
            # Card 1214 drops score.roster_id. Do not add fk_score_roster back.
            if any(not _column_exists(cur, table, c.strip()) for c in col.split(",")):
                continue
            have = _fk_delete_rule(cur, table, name)
            if have == rule or (rule == "RESTRICT" and have == "NO ACTION"):
                continue
            if have is not None:
                cur.execute(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{name}`")
            cur.execute(
                f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` FOREIGN KEY ({_cols(col)}) "
                f"REFERENCES `{ref}` ({_cols(ref_col)}) ON DELETE {rule}"
            )
            applied.append(f"{name}:{rule}")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_mail_sp(cn) -> list[str]:
    """Alpha: refresh mill_mail_* (fail-closed empty mail_to)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        sp = sql_dir() / "sp_mail.sql"
        if sp.is_file():
            blob = sp.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                low = stmt.strip().lower()
                if "mill_mail" in low and (
                    low.startswith("drop procedure") or low.startswith("create procedure")
                ):
                    _apply_stmt(cur, stmt)
            applied.append("sp_mail")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied



def _ensure_push_expired(cn) -> list[str]:
    """Refresh mill_push_* after kind/cause shape; no-op when push_queue already folded into wake."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "push_queue"):
            _apply_stmt(
                cur,
                "ALTER TABLE push_queue MODIFY kind "
                "ENUM('hint','mail','receipt','expired') NOT NULL",
            )
            applied.append("push_queue.kind.expired")
        sp = sql_dir() / "sp_push.sql"
        if sp.is_file():
            blob = sp.read_text(encoding="utf-8-sig")
            for stmt in split_script(blob):
                low = stmt.strip().lower()
                if low.startswith("drop procedure") or low.startswith("create procedure"):
                    _apply_stmt(cur, stmt)
            applied.append("sp_push")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_join_token_hash(cn) -> list[str]:
    """Index join.token_hash so bearer lookup is not a full seat scan (pre-#818 books)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "join") and _column_exists(cur, "join", "token_hash"):
            if not _index_exists(cur, "join", "idx_token_hash"):
                _apply_stmt(
                    cur,
                    "ALTER TABLE `join` ADD KEY idx_token_hash (token_hash)",
                )
                applied.append("join.idx_token_hash")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_join_endpoint_key(cn) -> list[str]:
    """#618: join.endpoint_key, the desk's own webhook key (per desk, not a host setting)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        # #818: only a seat-shaped join (a run cut after the reshape has no endpoint_url).
        if _table_exists(cur, "join") and _column_exists(cur, "join", "endpoint_url") and not _column_exists(cur, "join", "endpoint_key"):
            cur.execute(
                "ALTER TABLE `join` ADD COLUMN endpoint_key "
                "VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER endpoint_url"
            )
            applied.append("join.endpoint_key")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_seat_wake_on_default(cn, *, moved_818: bool = False) -> list[str]:
    """Card 836: seat.wake_on defaults to addressed, so a room copy wakes no one.

    Once per book: while the column default is still 'all', move it to 'addressed'
    and move every seat on 'all' with it. The new default is the marker, so a
    second run changes nothing and a desk that picks --wake-on all later keeps it.
    moved_818: this ensure just copied join rows into seat (a resumed run may have
    created seat with the new default already), so move the copied 'all' rows too.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "seat") and _column_exists(cur, "seat", "wake_on"):
            cur.execute(
                "SELECT COLUMN_DEFAULT FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'seat' AND COLUMN_NAME = 'wake_on'"
            )
            row = cur.fetchone()
            if (row and str(row[0] or "").strip("'") == "all") or moved_818:
                cur.execute("ALTER TABLE seat ALTER COLUMN wake_on SET DEFAULT 'addressed'")
                cur.execute("UPDATE seat SET wake_on = 'addressed', updated = updated WHERE wake_on = 'all'")
                applied.append("seat.wake_on.default.addressed")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_join_wake_on(cn) -> list[str]:
    """#628: join.wake_on, the desk's choice of which items POST (all or addressed)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        # #818: only a seat-shaped join (a run cut after the reshape has no endpoint_key).
        if _table_exists(cur, "join") and _column_exists(cur, "join", "endpoint_key") and not _column_exists(cur, "join", "wake_on"):
            cur.execute(
                "ALTER TABLE `join` ADD COLUMN wake_on "
                "ENUM('all','addressed') NOT NULL DEFAULT 'all' AFTER endpoint_key"
            )
            applied.append("join.wake_on")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


_WAITING_TYPE = "enum('mail','todo','hold','desk')"


def _ensure_doing_waiting(cn) -> list[str]:
    """#822: blocked-on is fields on the doing row: widen waiting_type to a desk
    or hold and add waiting_why (the reason). Each ALTER is guarded, so a run
    killed between them resumes at the one left. No edge or link table."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "doing") and _column_exists(cur, "doing", "waiting_type"):
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                " AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'waiting_type'"
            )
            if str(cur.fetchone()[0]).lower() != _WAITING_TYPE:
                cur.execute(
                    "ALTER TABLE doing MODIFY COLUMN waiting_type "
                    "ENUM('mail','todo','hold','desk') NULL"
                )
                applied.append("doing.waiting_type")
            if not _column_exists(cur, "doing", "waiting_why"):
                cur.execute(
                    "ALTER TABLE doing ADD COLUMN waiting_why VARCHAR(200) CHARACTER SET utf8mb4"
                    " COLLATE utf8mb4_0900_ai_ci NULL AFTER waiting_id"
                )
                applied.append("doing.waiting_why")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


_TREE_READ_SQL = (
    "CREATE TABLE IF NOT EXISTS tree_read ("
    " desk_id BIGINT UNSIGNED NOT NULL,"
    " tree_id BIGINT UNSIGNED NOT NULL,"
    " last_id BIGINT UNSIGNED NOT NULL,"
    " updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)"
    " ON UPDATE CURRENT_TIMESTAMP(6),"
    " PRIMARY KEY (desk_id, tree_id),"
    " KEY idx_tree (tree_id),"
    " CONSTRAINT fk_tree_read_desk FOREIGN KEY (desk_id)"
    " REFERENCES name (id) ON DELETE RESTRICT,"
    " CONSTRAINT fk_tree_read_tree FOREIGN KEY (tree_id)"
    " REFERENCES name (id) ON DELETE RESTRICT"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)


def _ensure_mail_to_unread(cn) -> list[str]:
    """Inbox unread page index: mail_to (desk_id, opened, id). Additive; no wipe."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "mail_to") and not _index_exists(cur, "mail_to", "idx_desk_unread"):
            cur.execute("ALTER TABLE mail_to ADD KEY idx_desk_unread (desk_id, opened, id)")
            applied.append("mail_to.idx_desk_unread")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_activity_roster(cn) -> list[str]:
    """Card 841: a mail or todo activity row carries its payload's roster.

    Older write paths left the activity row on another roster: a send that
    re-tagged only the letter, and the parent touch when a tree is rooted
    (Office, id 1). The payload is the truth. `updated` is kept. A book with
    no drift changes nothing, so a second run is a no-op."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        n = 0
        for typ in ("mail", "todo"):
            if not _table_exists(cur, typ):
                continue
            cur.execute(
                f"UPDATE activity a JOIN {typ} p ON a.type = '{typ}' AND a.id = p.id"
                " SET a.roster_id = p.roster_id, a.updated = a.updated"
                " WHERE a.roster_id <> p.roster_id"
            )
            n += int(cur.rowcount or 0)
        cn.commit()
        if n:
            applied.append("activity.roster_from_payload")
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


_SCORE_POINT_SQL = (
    "CREATE TABLE IF NOT EXISTS score_point ("
    " score_id BIGINT UNSIGNED NOT NULL,"
    " id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
    " created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
    " desk_id BIGINT UNSIGNED NOT NULL,"
    " value DOUBLE NOT NULL,"
    " note VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',"
    " PRIMARY KEY (score_id, id),"
    " UNIQUE KEY idx_id (id),"
    " KEY idx_desk (desk_id),"
    " KEY idx_score_at (score_id, created, id),"
    " CONSTRAINT fk_score_point_score FOREIGN KEY (score_id)"
    " REFERENCES score (id) ON DELETE RESTRICT,"
    " CONSTRAINT fk_score_point_desk FOREIGN KEY (desk_id)"
    " REFERENCES name (id) ON DELETE RESTRICT"
    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
)


def _ensure_mail_to_asked(cn) -> list[str]:
    """#818 D1: mail_to.asked (1 asked, 0 copied). Each step checks the book, so
    a run killed between them converges on the next ensure.

    1. Add the column NULL. 2. Backfill the NULL rows: a row whose stored wake
    for that letter and desk (push_queue kind mail, wake_reason room, #627) says
    the desk got it only as a room member is copied (0); every other row is
    asked (1), the default. The room wake is the same split the reply made, so
    the rule is exact where the row is kept; rows already handed back by a sync
    or expired are not, and stay asked. 3. NOT NULL DEFAULT 1.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "mail_to"):
            return applied
        if not _column_exists(cur, "mail_to", "asked"):
            cur.execute("ALTER TABLE mail_to ADD COLUMN asked TINYINT(1) NULL AFTER receipt")
            applied.append("mail_to.asked")
        cur.execute(
            "SELECT IS_NULLABLE FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail_to' AND COLUMN_NAME = 'asked'"
        )
        if str((cur.fetchone() or ("NO",))[0]) == "YES":
            if _table_exists(cur, "wake"):
                cur.execute(
                    "UPDATE mail_to mt JOIN ("
                    " SELECT DISTINCT p.desk_id,"
                    " CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.id')) AS UNSIGNED) AS mail_id"
                    " FROM wake p"
                    " WHERE p.cause = 'mail'"
                    " AND JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.wake_reason')) = 'room'"
                    ") r ON r.desk_id = mt.desk_id AND r.mail_id = mt.id"
                    " SET mt.asked = 0 WHERE mt.type = 'mail' AND mt.asked IS NULL"
                )
            elif _table_exists(cur, "push_queue"):
                cur.execute(
                    "UPDATE mail_to mt JOIN ("
                    " SELECT DISTINCT p.desk_id,"
                    " CAST(JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.id')) AS UNSIGNED) AS mail_id"
                    " FROM push_queue p"
                    " WHERE p.kind = 'mail'"
                    " AND JSON_UNQUOTE(JSON_EXTRACT(p.payload, '$.wake_reason')) = 'room'"
                    ") r ON r.desk_id = mt.desk_id AND r.mail_id = mt.id"
                    " SET mt.asked = 0 WHERE mt.type = 'mail' AND mt.asked IS NULL"
                )
            cur.execute("UPDATE mail_to SET asked = 1 WHERE asked IS NULL")
            cn.commit()
            cur.execute("ALTER TABLE mail_to MODIFY COLUMN asked TINYINT(1) NOT NULL DEFAULT 1")
            applied.append("mail_to.asked_backfill")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_todo_done_when(cn) -> list[str]:
    """#867: todo.done_when. 0.8.0: no todo.evidence shim (evidence lives on doing move rows;
    migrate_080 carries cloud-office evidence; the owner 2026-10-29: no old-field aliases)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "todo"):
            return applied
        if not _column_exists(cur, "todo", "done_when"):
            cur.execute(
                "ALTER TABLE todo ADD COLUMN done_when VARCHAR(1000) CHARACTER SET utf8mb4"
                " COLLATE utf8mb4_0900_ai_ci NULL AFTER body"
            )
            applied.append("todo.done_when")
        if applied:
            cn.commit()
    finally:
        cur.close()
    return applied


def _ensure_todo_claimed_at(cn) -> list[str]:
    """#818 D2: todo.claimed_at. Add the column, then backfill every claimed
    card that has none, so a run killed after the ALTER converges (after this
    PR a claimed card always has one, so the backfill finds nothing to do).

    Best row the book keeps: the volunteer's watcher row on the card. The
    volunteer's first write on a card puts it on the card's watchers
    (mill_watcher_roster, INSERT IGNORE), so for a card it did not file that
    is the claim, or a note just before it; for a card it filed it is the
    create, the earliest time it can have claimed it. Capped at todo.updated.
    No watcher row: todo.updated (what the age read before). A card that left
    and came back to the same volunteer keeps its first time.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "todo"):
            return applied
        if not _column_exists(cur, "todo", "claimed_at"):
            cur.execute("ALTER TABLE todo ADD COLUMN claimed_at DATETIME(6) NULL AFTER assigned_id")
            applied.append("todo.claimed_at")
        cur.execute("SELECT COUNT(*) FROM todo WHERE status = 'claimed' AND claimed_at IS NULL")
        if int((cur.fetchone() or (0,))[0] or 0) > 0:
            # updated has ON UPDATE CURRENT_TIMESTAMP: keep it as it is.
            cur.execute(
                "UPDATE todo t"
                " LEFT JOIN watcher w ON w.type = 'todo' AND w.id = t.id AND w.desk_id = t.assigned_id"
                " SET t.claimed_at = IF(w.updated IS NULL, t.updated, LEAST(w.updated, t.updated)),"
                " t.updated = t.updated"
                " WHERE t.status = 'claimed' AND t.claimed_at IS NULL"
            )
            applied.append("todo.claimed_at_backfill")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_score_series(cn) -> list[str]:
    """#288 step 1: score.better, score.unit and the score_point table. Additive; no wipe."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "score"):
            if _column_exists(cur, "score", "note") and not _column_exists(cur, "score", "better"):
                cur.execute(
                    "ALTER TABLE score ADD COLUMN better ENUM('up','down') NOT NULL DEFAULT 'up'"
                    " AFTER note"
                )
                applied.append("score.better")
            if _column_exists(cur, "score", "better") and not _column_exists(cur, "score", "unit"):
                cur.execute(
                    "ALTER TABLE score ADD COLUMN unit VARCHAR(16) CHARACTER SET utf8mb4"
                    " COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '' AFTER better"
                )
                applied.append("score.unit")
            if not _table_exists(cur, "score_point"):
                _apply_stmt(cur, _SCORE_POINT_SQL)
                applied.append("score_point")
            elif not _index_exists(cur, "score_point", "idx_score_at"):
                # 0.7.6 (#308): points read newest by time (--at), not by insert order.
                cur.execute("ALTER TABLE score_point ADD KEY idx_score_at (score_id, created, id)")
                applied.append("score_point.idx_score_at")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_score_one_name(cn) -> list[str]:
    """0.7.6 (#305): one live score per name on a roster after the 0.7.5 series.

    A 0.7.4 write left desk-owned rows (desk_id = a desk) beside the 0.7.5
    roster-owned definition. Off the Office roster (host and system KPIs stay
    per desk there), for each live desk-owned row of a name: retire it when the
    roster already owns that name or the row is empty (no value, no points);
    else the newest one becomes the roster's definition and any others retire.
    Retire is mill_score_delete (soft; the row and its evidence stay). A second
    run finds nothing.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not (_table_exists(cur, "score") and _table_exists(cur, "score_point")):
            return applied
        # Card 1214: a score has no roster column. This step is the old desk-versus-roster merge.
        if not _column_exists(cur, "score", "roster_id"):
            return applied
        # 0.8.0: a roster-owned score is desk NULL (migrate_080 step desk_null), never desk = roster.
        if _column_exists(cur, "score", "desk_key"):
            return applied
        cur.execute(
            "SELECT s.id, s.roster_id, s.kpi, s.value,"
            " EXISTS (SELECT 1 FROM score_point sp WHERE sp.score_id = s.id) AS has_pt,"
            " EXISTS (SELECT 1 FROM score r WHERE r.roster_id = s.roster_id AND r.desk_id = s.roster_id"
            "         AND r.kpi = s.kpi) AS has_def"
            " FROM score s"
            " JOIN name dn ON dn.id = s.desk_id AND dn.type = 'desk'"
            " JOIN name rn ON rn.id = s.roster_id AND rn.id <> 1"  # #722: Office by id
            " JOIN activity a ON a.type = 'score' AND a.id = s.id AND a.deleted IS NULL"
            " ORDER BY s.roster_id, s.kpi, s.updated DESC, s.id DESC"
        )
        rows = list(cur.fetchall())
        retire: list[int] = []
        adopt: list[int] = []
        taken: set[tuple[int, str]] = set()
        for sid, rid, kpi, value, has_pt, has_def in rows:
            key = (int(rid), str(kpi))
            if has_def or key in taken or (str(value or "") == "" and not has_pt):
                retire.append(int(sid))
            else:
                adopt.append(int(sid))
                taken.add(key)
        for sid in adopt:
            cur.execute("UPDATE score SET desk_id = roster_id WHERE id = %s", (sid,))
        cn.commit()
        from agent_coord.server.records.db import call

        for sid in retire:
            call(cn, "mill_score_delete", [sid, ""])
        if adopt:
            applied.append(f"score.one_name(adopt {len(adopt)})")
        if retire:
            applied.append(f"score.one_name(retire {len(retire)})")
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_tree_read(cn) -> list[str]:
    """Per-desk tree read cursor (#155). Additive on a live book. No wipe."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "tree_read"):
            _apply_stmt(cur, _TREE_READ_SQL)
            applied.append("tree_read")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_label_ord(cn) -> list[str]:
    """#196: label.ord and idx_label_ord. Add the new index before dropping idx_name.

    fk_label_name needs a name_id-leading index. Dropping idx_name first makes
    MySQL refuse the drop. Each step is skipped when it is already done.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "label"):
            return applied
        if not _column_exists(cur, "label", "ord"):
            cur.execute(
                "ALTER TABLE label ADD COLUMN ord "
                "SMALLINT UNSIGNED NOT NULL DEFAULT 65535 AFTER name_id"
            )
            applied.append("label.ord")
        if not _index_exists(cur, "label", "idx_label_ord"):
            cur.execute(
                "ALTER TABLE label ADD KEY idx_label_ord (name_id, ord, created)"
            )
            applied.append("label.idx_label_ord")
        if _index_exists(cur, "label", "idx_name"):
            cur.execute("ALTER TABLE label DROP INDEX idx_name")
            applied.append("label.drop_idx_name")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


ROSTER_070 = "migrate_070_roster.sql"
DOING_818 = "migrate_818_doing.sql"
TRANSITION_1022 = "migrate_1022_transition.sql"
TASK_970 = "migrate_970_task.sql"
HISTORY_1133 = "migrate_1133_history.sql"


def roster_070_needed(cn) -> bool:
    """True when the book still has project/role name types or an old tag column."""
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'name' AND COLUMN_NAME = 'type'"
        )
        row = cur.fetchone()
        ctype = row[0] if row else ""
        if isinstance(ctype, (bytes, bytearray)):
            ctype = ctype.decode("utf-8")
        if "'project'" in str(ctype or ""):
            return True
        old_col = "affil" + "iation_id"  # the pre-0.7.0 column name, spelled apart for the grep gate
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = %s",
            (old_col,),
        )
        return int(cur.fetchone()[0] or 0) > 0
    finally:
        cur.close()


def reload_routines(cn) -> list[str]:
    """Drop every function, then apply each fn_/sp_ file in apply order (no tables, no wipe)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        try:
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
        except Exception:
            pass
        n = _drop_functions(cur)
        applied.append(f"functions(drop {n})")
        for path in sql_apply_order():
            if not (path.stem.startswith("fn_") or path.stem.startswith("sp_")):
                continue
            for stmt in split_script(path.read_text(encoding="utf-8-sig")):
                _apply_stmt(cur, stmt)
            applied.append(path.name)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def apply_roster_070(cn) -> list[str]:
    """0.7.0: one roster name type and roster_id columns, then reload every routine.

    Runs migrate_070_roster.sql through split_script (same statements the mysql
    client runs whole-file). A same-name project/role refuses before any change.
    """
    if not roster_070_needed(cn):
        return []
    cur = cn.cursor()
    try:
        for stmt in split_script((sql_dir() / ROSTER_070).read_text(encoding="utf-8-sig")):
            cur.execute(stmt)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return [ROSTER_070] + reload_routines(cn)


def doing_818_needed(cn) -> bool:
    """#818: True while the book has a `join` table or a type column that lists 'join'."""
    cur = cn.cursor()
    try:
        if _table_exists(cur, "join"):
            return True
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'on_type'"
            " AND COLUMN_TYPE <> %s",
            ("enum('mail','todo','hold','score')",),
        )
        if int(cur.fetchone()[0] or 0) > 0:
            return True
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND COLUMN_NAME = 'type'"
            " AND TABLE_NAME IN ('activity','label','tree','mail','mail_to','todo','doing','hold','score','watcher')"
            " AND COLUMN_TYPE LIKE %s",
            ("%'join'%",),
        )
        return int(cur.fetchone()[0] or 0) > 0
    finally:
        cur.close()


def apply_doing_818(cn) -> list[str]:
    """#818: seat split off, activity type join renamed to doing, the `join`
    table becomes the append-only doing table (same ids). Then reload every
    routine. Each step in the file checks the book first, so a second run (or
    a run after a partial one) does only what is left."""
    if not doing_818_needed(cn):
        return []
    cur = cn.cursor()
    try:
        for stmt in split_script((sql_dir() / DOING_818).read_text(encoding="utf-8-sig")):
            cur.execute(stmt)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    # The routine reload is not here: _ensure_steps reloads after this step
    # whenever the routines are not this pack's, so a run killed after the
    # RENAME (when this check is already false) still gets its reload.
    return [DOING_818]


MIGRATE_080 = "migrate_080.sql"
# Steps in order. Each checks the book first, so a run after a kill at any point does only what is left.
STEPS_080: tuple[str, ...] = (
    "seat", "watcher", "desk_null", "score_key", "keys_kinds", "columns", "acts", "moves", "doing_id", "drop_cols", "fks",
    "triggers",
)
# Preflight checks that refuse the run, with what they mean. Nothing in the book changes before the refusal.
_REFUSE_080: dict[str, str] = {
    "desk_seat": "seat.desk_id holds a name that is not a desk",
    "desk_member": "member.desk_id holds a name that is not a desk",
    "desk_mail": "mail.desk_id holds a name that is not a desk",
    "desk_mail_to": "mail_to.desk_id holds a name that is not a desk",
    "desk_tree_read": "tree_read.desk_id holds a name that is not a desk",
    "desk_todo": "todo.updated_id, creator_id or assigned_id holds a name that is not a desk",
    "desk_doing": "doing.desk_id holds a name that is not a desk",
    "desk_hold": "hold.desk_id holds a name that is not a desk",
    "desk_score_point": "score_point.desk_id holds a name that is not a desk",
    "desk_human_desk": "human_desk.desk_id holds a name that is not a desk",
    "desk_wake": "wake.desk_id holds a name that is not a desk",
    "desk_watcher": "watcher.desk_id holds a label, tree or res name",
    "kind_member": "member.name_id holds a name that is not a roster",
    "kind_activity": "activity.roster_id holds a name that is not a roster",
    "kind_label": "label.name_id holds a name that is not a label",
    "kind_tree": "tree.name_id holds a name that is not a tree",
    "kind_mail": "mail.roster_id holds a name that is not a roster",
    "kind_tree_read": "tree_read.tree_id holds a name that is not a tree",
    "kind_todo": "todo.roster_id holds a name that is not a roster",
    "kind_doing": "doing.roster_id holds a name that is not a roster",
    "kind_hold": "hold.resource_id holds a name that is not a res",
    "kind_score": "score.roster_id holds a name that is not a roster",
    "kind_human_member": "human_member.name_id holds a name that is not a roster",
    "score_collapse": "two scores of one roster and kpi would both become the office's (desk NULL); retire or rename one",
    "todo_evidence_long": (
        "a card's evidence is longer than 2000 characters (doing.evidence / EVIDENCE_MAX); nothing is cut"
    ),
}


class Migrate080Refused(RuntimeError):
    """The preflight found data no step can fix. The book is unchanged."""

    def __init__(self, refuse: dict[str, int]):
        self.refuse = dict(refuse)
        lines = "; ".join(f"{k}={n} ({_REFUSE_080.get(k, k)})" for k, n in sorted(self.refuse.items()))
        super().__init__(
            f"migrate to the 0.8.0 schema refused, nothing was changed: {lines}. "
            f"Fix those rows, then run {SQL_FIX} again."
        )


def _perf_on() -> bool:
    """mill-perf lines for this migration. MILL_PERF=0 (or off/false/no) turns them off."""
    import os

    return (os.environ.get("MILL_PERF") or "").strip().lower() not in ("0", "off", "false", "no")


def _lock_status(cur) -> tuple[int, int]:
    cur.execute("SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_row_lock_waits', 'Innodb_row_lock_time')")
    got = {str(k): int(v or 0) for k, v in cur.fetchall()}
    return got.get("Innodb_row_lock_waits", 0), got.get("Innodb_row_lock_time", 0)


def _timed_080(cn, op: str, fn, timings: dict | None):
    """Run fn(cur) -> rows. With perf on: one mill-perf line (ms, rows, lock waits, outcome); off: no reads, no line."""
    import time

    on = _perf_on()
    cur = cn.cursor()
    try:
        w0 = _lock_status(cur) if on else (0, 0)
        t0 = time.perf_counter()
        try:
            rows = fn(cur)
        except Exception as e:
            if on:
                from agent_coord.server.push import perf_log

                perf_log(f"migrate.080.{op}", (time.perf_counter() - t0) * 1000.0, ok=0, err=str(e)[:160])
            raise
        ms = (time.perf_counter() - t0) * 1000.0
        if timings is not None:
            timings[op] = ms
        if on:
            from agent_coord.server.push import perf_log

            w1 = _lock_status(cur)
            perf_log(f"migrate.080.{op}", ms, rows=rows, lock_waits=w1[0] - w0[0], lock_ms=w1[1] - w0[1], ok=1)
        return rows
    finally:
        cur.close()


def _helpers_080(cn, *, create: bool) -> None:
    """Create (or drop) the mill_migrate_080_* routines. They never stay in a finished book."""
    stmts = split_script((sql_dir() / MIGRATE_080).read_text(encoding="utf-8-sig"))
    cur = cn.cursor()
    try:
        for stmt in stmts:
            if create or stmt.lstrip().upper().startswith("DROP "):
                cur.execute(stmt)
        cn.commit()
    finally:
        cur.close()


def _preflight_rows(cur) -> list[tuple[str, str, int]]:
    cur.execute("CALL mill_migrate_080_preflight()")
    rows = [(str(c), str(a), int(n)) for c, a, n in cur.fetchall()]
    while cur.nextset():
        if cur.with_rows:
            cur.fetchall()
    return rows


def _report_080(rows: list[tuple[str, str, int]]) -> dict[str, Any]:
    refuse = {c: n for c, a, n in rows if a == "refuse" and n}
    fix = {c: n for c, a, n in rows if a == "fix"}
    schema = {c: n for c, a, n in rows if a == "schema" and n}
    pending = bool(schema) or any(fix.values())
    return {"pending": pending, "refuse": refuse, "fix": fix, "schema": schema}


def _is_main_book(cn) -> bool:
    cur = cn.cursor()
    try:
        return _table_exists(cur, "activity") and _table_exists(cur, "name")
    finally:
        cur.close()


def preflight_080(cn) -> dict[str, Any]:
    """Read only: what the 0.8.0 migration would change (fix), still has to build (schema) and refuses on
    (refuse). The helper routines are dropped again, so the book is as it was."""
    if not _is_main_book(cn):
        return {"pending": False, "refuse": {}, "fix": {}, "schema": {}}
    _helpers_080(cn, create=True)
    try:
        holder: dict[str, list] = {}

        def run(cur) -> int:
            holder["rows"] = _preflight_rows(cur)
            return len(holder["rows"])

        _timed_080(cn, "preflight", run, None)
        return _report_080(holder["rows"])
    finally:
        _helpers_080(cn, create=False)


def _triggers_080(cur) -> int:
    """The triggers of tables.sql (drop, then create), as a fresh book has them."""
    n = 0
    for stmt in split_script(schema_path().read_text(encoding="utf-8-sig")):
        low = stmt.lstrip().lower()
        if low.startswith("drop trigger") or low.startswith("create trigger"):
            cur.execute(stmt)
            n += low.startswith("create trigger")
    return n


def _book_is_1163(cn) -> bool:
    """Card 1163 shape: one unique name string, and the kind columns are gone."""
    cur = cn.cursor()
    try:
        return _index_exists(cur, "name", "idx_name") and not _column_exists(cur, "member", "name_kind")
    finally:
        cur.close()


def apply_080(cn, *, stop_after: str | None = None, timings: dict | None = None) -> list[str]:
    """0.8.0 schema on a main book (migrate_080.sql). Preflight first: refuse (Migrate080Refused) before any
    change; nothing pending is a no-op ([]). stop_after ends the run after that step, as a kill would (tests).
    A book already on the card 1163 shape is left alone: migrate_080.sql is not rewritten, and its preflight
    would otherwise treat the dropped kind columns as work still to do.
    Card 1214 removes score.roster_id. migrate_080.sql would rebuild idx_score_who on that column, so a book
    that already took 1214 is left alone too."""
    if _book_is_1163(cn):
        return []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "score") and not _column_exists(cur, "score", "roster_id"):
            return []
    finally:
        cur.close()
    if stop_after is not None and stop_after not in STEPS_080:
        raise ValueError(f"unknown 0.8.0 step: {stop_after}")
    if not _is_main_book(cn):
        return []
    _helpers_080(cn, create=True)
    holder: dict[str, list] = {}

    def pre(cur) -> int:
        holder["rows"] = _preflight_rows(cur)
        return len(holder["rows"])

    try:
        _timed_080(cn, "preflight", pre, timings)
        rep = _report_080(holder["rows"])
    except Exception:
        _helpers_080(cn, create=False)
        raise
    if rep["refuse"]:
        _helpers_080(cn, create=False)
        raise Migrate080Refused(rep["refuse"])
    if not rep["pending"]:
        _helpers_080(cn, create=False)
        return []
    applied: list[str] = []
    for step in STEPS_080:
        if step == "triggers":
            _helpers_080(cn, create=False)

            def _triggers_1163(cur) -> int:
                # The focus trigger reads seat.focus_label_id. The column is not in migrate_080.sql.
                _ensure_focus_label_column(cur)
                return _triggers_080(cur)

            n = _timed_080(cn, step, _triggers_1163, timings)
            cn.commit()
        else:
            def run(cur, step=step) -> int:
                cur.execute("CALL mill_migrate_080_step(%s)", (step,))
                while cur.nextset():
                    if cur.with_rows:
                        cur.fetchall()
                cur.execute("SELECT @m080_rows")
                return int((cur.fetchone() or (0,))[0] or 0)

            n = _timed_080(cn, step, run, timings)
            cn.commit()
        applied.append(f"migrate_080:{step}({n})")
        if step == stop_after:
            break
    return applied


SQL_FIX = "mill install sql --apply"
_STAMP_FN = "MILL_SQL_STAMP"


@functools.lru_cache(maxsize=1)
def sql_digest() -> str:
    """sha256 of this pack's SQL: every apply_order file but wipe.sql, then this
    module (its ensure steps). Line endings do not count (#614)."""
    h = hashlib.sha256()
    parts = [p for p in sql_apply_order() if p.name != "wipe.sql"] + [Path(__file__)]
    for path in parts:
        h.update(path.name.encode("utf-8") + b"\0")
        h.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def _stamp_sql(cn, digest: str) -> None:
    """Record in the book which pack's SQL it holds: a function, no table (#614)."""
    if not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
        raise ValueError("sql stamp is 64 hex")
    cur = cn.cursor()
    try:
        cur.execute(f"DROP FUNCTION IF EXISTS {_STAMP_FN}")
        cur.execute(
            f"CREATE FUNCTION {_STAMP_FN}() RETURNS CHAR(64) CHARSET ascii"
            f" DETERMINISTIC NO SQL RETURN '{digest}'"
        )
        cn.commit()
    finally:
        cur.close()


_ROUTINES_FN = "MILL_ROUTINES_STAMP"
_ROUTINE_RE = re.compile(r"^\s*CREATE\s+(?:DEFINER\s*=\s*\S+\s+)?(PROCEDURE|FUNCTION)\s+`?([A-Za-z0-9_]+)`?", re.I)


@functools.lru_cache(maxsize=1)
def shipped_routines() -> frozenset[tuple[str, str]]:
    """(PROCEDURE|FUNCTION, lower name) for every routine the fn_/sp_ files create."""
    out: set[tuple[str, str]] = set()
    for path in sql_apply_order():
        if not (path.stem.startswith("fn_") or path.stem.startswith("sp_")):
            continue
        for stmt in split_script(path.read_text(encoding="utf-8-sig")):
            m = _ROUTINE_RE.match(stmt)
            if m:
                out.add((m.group(1).upper(), m.group(2).lower()))
    return frozenset(out)


def _routine_rows(cur) -> list[tuple[str, str, str]]:
    cur.execute(
        "SELECT ROUTINE_TYPE, ROUTINE_NAME, SHA2(IFNULL(ROUTINE_DEFINITION, ''), 256)"
        " FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()"
        " AND ROUTINE_NAME NOT IN (%s, %s) AND ROUTINE_NAME NOT LIKE 'mill\\_migrate\\_%%'",
        (_STAMP_FN, _ROUTINES_FN),
    )
    rows = []
    for r in cur.fetchall():
        rows.append(tuple(x.decode("utf-8") if isinstance(x, (bytes, bytearray)) else str(x) for x in r))
    return sorted(rows, key=lambda r: (r[0], r[1].lower()))


def routines_fingerprint(cn) -> str:
    """sha256 over (type, name, body hash) of every routine in the book but the stamps (#818)."""
    cur = cn.cursor()
    try:
        rows = _routine_rows(cur)
    finally:
        cur.close()
    h = hashlib.sha256()
    for t, n, d in rows:
        h.update(f"{t}:{n.lower()}:{d}\n".encode("ascii"))
    return h.hexdigest()


def _stamp_routines(cn) -> None:
    """Record the routines' fingerprint after a run that finished (#818)."""
    digest = routines_fingerprint(cn)
    cur = cn.cursor()
    try:
        cur.execute(f"DROP FUNCTION IF EXISTS {_ROUTINES_FN}")
        cur.execute(
            f"CREATE FUNCTION {_ROUTINES_FN}() RETURNS CHAR(64) CHARSET ascii"
            f" DETERMINISTIC NO SQL RETURN '{digest}'"
        )
        cn.commit()
    finally:
        cur.close()


def _read_stamp(cur, fn: str) -> str:
    try:
        cur.execute(f"SELECT {fn}()")
        row = cur.fetchone()
        return str((row or [""])[0] or "")
    except Exception as e:
        # 1305: no such function, a book from before the stamp. 1449: its definer
        # is not a user here (a dump restored on another server). Either way the
        # routines are not known to be this pack's: unstamped, so ensure reloads them.
        if getattr(e, "errno", None) not in (1305, 1449):
            raise
        return ""


def sql_state(cn) -> dict[str, Any]:
    """Does the book hold this pack's SQL? Read only. ok, pack and book (12 hex each), fix.

    #818: also the routines. Every routine the pack ships must be there, and
    the routines must be the ones the last finished ensure left (their
    fingerprint equals the stamp it wrote). A run killed mid-reload, or a
    routine changed or dropped by hand, is not ok."""
    pack = sql_digest()
    cur = cn.cursor()
    try:
        book = _read_stamp(cur, _STAMP_FN)
        stamped = _read_stamp(cur, _ROUTINES_FN)
        rows = _routine_rows(cur)
    finally:
        cur.close()
    have = {(t.upper(), n.lower()) for t, n, _ in rows}
    missing = sorted(n for _, n in shipped_routines() - have)
    h = hashlib.sha256()
    for t, n, d in rows:
        h.update(f"{t}:{n.lower()}:{d}\n".encode("ascii"))
    routines_ok = not missing and bool(stamped) and stamped == h.hexdigest()
    out = {"ok": book == pack and routines_ok, "pack": pack[:12], "book": book[:12], "fix": SQL_FIX}
    if not routines_ok:
        out["routines"] = "missing " + ",".join(missing[:5]) if missing else "changed since the last ensure"
    return out


def install_sql(cn, *, apply: bool) -> dict[str, Any]:
    """mill install sql: without apply, report; with apply, ensure then verify (#614).
    mill update only reports (#616); applying stays this deliberate step."""
    before = sql_state(cn)
    if not apply:
        return {**before, "applied": False}
    res = ensure(cn)
    after = sql_state(cn)
    return {**after, "applied": True, "was": before["book"], "steps": len(res.get("applied") or [])}



def _ensure_name_trashed(cn) -> list[str]:
    """#879: name.trashed for mill delete soft-trash (restorable; purge hard-deletes)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "name"):
            return applied
        if not _column_exists(cur, "name", "trashed"):
            cur.execute(
                "ALTER TABLE name ADD COLUMN trashed "
                "DATETIME(6) NULL AFTER deleted"
            )
            applied.append("name.trashed")
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_act_rename(cn) -> list[str]:
    """#926/#879: activity.act and doing.act gain delete/restore/purge/rename."""
    applied: list[str] = []
    want = (
        "ENUM('create','send','reply','note','park','claim','unclaim','assign','unpark',"
        "'ship','done','back','hold','drop','focus','clear','finish','score','retire',"
        "'reclaim','remove','delete','restore','purge','rename')"
    )
    cur = cn.cursor()
    try:
        for table, default in (("activity", "create"), ("doing", "focus")):
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='act'",
                (table,),
            )
            row = cur.fetchone()
            ctype = (row[0] if row else "") or ""
            # pre-0.8.0 books have no act yet; migrate_080 adds the full ENUM
            low = ctype.lower()
            if (not ctype) or all(a in low for a in ("delete", "restore", "purge", "rename")):
                continue
            _apply_stmt(
                cur,
                f"ALTER TABLE `{table}` MODIFY COLUMN act {want} NOT NULL DEFAULT '{default}'",
            )
            applied.append(f"{table}.act+rename")
    finally:
        cur.close()
    return applied



def transition_1022_needed(cn) -> bool:
    """True when wake/transition/System from card 1022 are not yet on the book,
    or push_queue still exists (fold into wake), or wake lacks payload,
    or watcher.type still drifts from the tip ENUM (card 1059 name rows)."""
    cur = cn.cursor()
    try:
        if _table_exists(cur, "push_queue"):
            return True
        if not _table_exists(cur, "transition") or not _table_exists(cur, "wake"):
            return True
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wake' AND COLUMN_NAME = 'payload'"
        )
        if int(cur.fetchone()[0] or 0) == 0:
            return True
        cur.execute(
            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'type'"
        )
        row = cur.fetchone()
        ctype = row[0] if row else ""
        if isinstance(ctype, (bytes, bytearray)):
            ctype = ctype.decode("utf-8")
        if "'wake'" not in str(ctype or ""):
            return True
        cur.execute(
            "SELECT COUNT(*) FROM name WHERE id = 0 AND type = 'desk' AND name = 'System'"
        )
        if int(cur.fetchone()[0] or 0) == 0:
            return True
        cur.execute(
            "SELECT COUNT(*) FROM seat WHERE desk_id = 0"
        )
        if int(cur.fetchone()[0] or 0) == 0:
            return True
        # desk_id on transition must be NOT NULL DEFAULT 0 (owner 2026-11-01)
        cur.execute(
            "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transition' AND COLUMN_NAME = 'desk_id'"
        )
        row = cur.fetchone()
        if row and (str(row[0]).upper() == "YES" or str(row[1] or "") not in ("0", "0.0")):
            return True
        # card 1059: watcher.type must match tip (no 'name'; Oct 3 name-is-not-activity)
        if _table_exists(cur, "watcher"):
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'watcher'"
                " AND COLUMN_NAME = 'type'"
            )
            row = cur.fetchone()
            wtype = row[0] if row else ""
            if isinstance(wtype, (bytes, bytearray)):
                wtype = wtype.decode("utf-8")
            tip = "enum('todo','doing','hold','score','wake')"
            if str(wtype or "") != tip:
                return True
        return False
    finally:
        cur.close()



def _ensure_transition_n(cn) -> list[str]:
    """card 1098: transition.n cycle count (default 1). Idempotent ADD COLUMN."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "transition"):
            return applied
        if not _column_exists(cur, "transition", "n"):
            cur.execute(
                "ALTER TABLE transition ADD COLUMN n INT UNSIGNED NOT NULL DEFAULT 1"
                " AFTER meta"
            )
            applied.append("transition.n")
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_label_updated(cn) -> list[str]:
    """card 1153: label.updated, when ord was last set. Idempotent ADD COLUMN; an
    existing row starts at its created stamp (the only ord time the book has)."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "label"):
            return applied
        if not _column_exists(cur, "label", "updated"):
            cur.execute(
                "ALTER TABLE label ADD COLUMN updated DATETIME(6) NOT NULL"
                " DEFAULT CURRENT_TIMESTAMP(6) AFTER created"
            )
            cur.execute("UPDATE label SET updated = created")
            applied.append("label.updated")
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied



def _ensure_wake_retry_edge(cn) -> list[str]:
    """card 1111: wake error -> retry_armed / wake_retry. Idempotent INSERT IGNORE."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "transition_edge"):
            return applied
        cur.execute(
            "INSERT IGNORE INTO transition_edge"
            " (activity_type, from_state, to_state, reason)"
            " VALUES ('wake', 'error', 'retry_armed', 'wake_retry')"
        )
        if cur.rowcount:
            applied.append("transition_edge.wake_retry_from_error")
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_wake_lease_edges(cn) -> list[str]:
    """card 1140: wake lease edges (ring, done, expired, cleared). Idempotent INSERT IGNORE."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "transition_edge"):
            return applied
        cur.execute(
            "INSERT IGNORE INTO transition_edge"
            " (activity_type, from_state, to_state, reason) VALUES"
            " ('wake', 'ring', 'lease_live', 'wake_sent'),"
            " ('wake', 'lease_live', 'done', 'wake_done'),"
            " ('wake', 'lease_live', 'expired', 'wake_expire'),"
            " ('wake', 'lease_live', 'cleared', 'clear')"
        )
        if cur.rowcount:
            applied.append("transition_edge.wake_lease_1140")
            cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def _ensure_wake_auto_id(cn) -> list[str]:
    """card 1113: wake is payload first, as mail and todo. wake.id is AUTO_INCREMENT, past every wake id in
    activity (rollup deletes wake rows and keeps their activity rows), and fk_wake_activity is gone (the
    wake row is written before its activity row). Idempotent.
    """
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "wake"):
            return applied
        cur.execute(
            "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'wake' AND CONSTRAINT_NAME = 'fk_wake_activity'"
        )
        if cur.fetchone():
            _apply_stmt(cur, "ALTER TABLE wake DROP FOREIGN KEY fk_wake_activity")
            applied.append("wake_drop_fk_activity")
        cur.execute(
            "SELECT EXTRA FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
            " AND TABLE_NAME = 'wake' AND COLUMN_NAME = 'id'"
        )
        row = cur.fetchone()
        if row and "auto_increment" not in str(row[0]).lower():
            _apply_stmt(cur, "ALTER TABLE wake MODIFY id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT")
            applied.append("wake_auto_id")
        cur.execute("SELECT IFNULL(MAX(id), 0) FROM activity WHERE type = 'wake'")
        top = int(cur.fetchone()[0])
        if top:
            # Only raises the counter: InnoDB keeps it at or past MAX(wake.id) + 1.
            cur.execute(f"ALTER TABLE wake AUTO_INCREMENT = {top + 1}")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied



def _ensure_wake_cause_id_idx(cn) -> list[str]:
    """card 1171: wake (cause, cause_id, state) for mill_mail_delete's find. Additive; no wipe."""
    applied: list[str] = []
    cur = cn.cursor()
    try:
        if _table_exists(cur, "wake") and not _index_exists(cur, "wake", "idx_cause_id"):
            cur.execute("ALTER TABLE wake ADD KEY idx_cause_id (cause, cause_id, state)")
            applied.append("wake.idx_cause_id")
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def apply_transition_1022(cn) -> list[str]:
    """card 1022: fold push_queue into wake, transition table, System desk id 0. Idempotent."""
    if not transition_1022_needed(cn):
        return []
    applied: list[str] = []
    cur = cn.cursor()
    try:
        # If transition exists with nullable desk_id, widen in place before / with migrate.
        if _table_exists(cur, "transition"):
            cur.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transition'"
                " AND COLUMN_NAME = 'desk_id'"
            )
            row = cur.fetchone()
            if row and str(row[0]).upper() == "YES":
                cur.execute(
                    "UPDATE transition SET desk_id = 0 WHERE desk_id IS NULL"
                )
                cur.execute(
                    "ALTER TABLE transition MODIFY desk_id BIGINT UNSIGNED NOT NULL DEFAULT 0"
                )
                applied.append("transition.desk_id_not_null")
        for stmt in split_script((sql_dir() / TRANSITION_1022).read_text(encoding="utf-8-sig")):
            _apply_stmt(cur, stmt)
            if cur.with_rows:
                cur.fetchall()
        # Fold push_queue rows into activity+wake, then drop push_queue.
        if _table_exists(cur, "push_queue"):
            cur.execute(
                "INSERT IGNORE INTO activity (type, id, created, updated, desk_id, roster_id, act) "
                "SELECT 'wake', pq.id, pq.created, pq.created, 0, 1, 'ring' FROM push_queue pq"
            )
            cur.execute(
                "INSERT IGNORE INTO wake (id, type, desk_id, cause, state, payload, created) "
                "SELECT pq.id, 'wake', pq.desk_id, pq.kind, pq.outcome, pq.payload, pq.created "
                "FROM push_queue pq"
            )
            cur.execute("DROP TABLE push_queue")
            applied.append("fold_push_queue_into_wake")
        applied.append(TRANSITION_1022)
        cn.commit()
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
    return applied


def task_970_needed(cn) -> bool:
    """Both act enums share the task value (card 970); a missing act column (doing, card 1207) is skipped."""
    cur = cn.cursor()
    try:
        for table in ("activity", "doing"):
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = 'act'",
                (table,),
            )
            row = cur.fetchone()
            if row is None:  # card 1207: doing.act is gone; nothing to widen
                continue
            ctype = row[0]
            if isinstance(ctype, (bytes, bytearray)):
                ctype = ctype.decode("utf-8")
            if "'task'" not in str(ctype):
                return True
        return False
    finally:
        cur.close()


def apply_task_970(cn) -> list[str]:
    """Append task without rewriting or narrowing an existing enum. Idempotent."""
    if not task_970_needed(cn):
        return []
    cur = cn.cursor()
    try:
        for stmt in split_script((sql_dir() / TASK_970).read_text(encoding="utf-8-sig")):
            _apply_stmt(cur, stmt)
            if cur.with_rows:
                cur.fetchall()
        cn.commit()
        return [TASK_970]
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def history_1133_needed(cn) -> bool:
    """Card 1133: True while the book lacks activity_history, a body stamp column, todo.meta, the replace act,
    or still has a card document that is not split into body and meta (meta NULL)."""
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "activity_history"):
            return True
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
            " AND ((TABLE_NAME = 'mail' AND COLUMN_NAME IN ('body_updated', 'body_updater_id'))"
            " OR (TABLE_NAME = 'todo' AND COLUMN_NAME IN ('meta', 'body_updated', 'body_updater_id')))"
        )
        if int(cur.fetchone()[0] or 0) < 5:
            return True
        for table in ("activity", "doing"):
            cur.execute(
                "SELECT COLUMN_TYPE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = 'act'",
                (table,),
            )
            row = cur.fetchone()
            if row is None:  # card 1207: doing.act is gone; nothing to widen
                continue
            ctype = row[0]
            if isinstance(ctype, (bytes, bytearray)):
                ctype = ctype.decode("utf-8")
            if "'replace'" not in str(ctype):
                return True
        cur.execute("SELECT EXISTS (SELECT 1 FROM todo WHERE meta IS NULL)")
        return bool(int(cur.fetchone()[0] or 0))
    finally:
        cur.close()


def apply_history_1133(cn) -> list[str]:
    """Card 1133: body stamps, todo meta, activity_history and the replace act; splits each card document into
    body (the text) and meta (the rest). Each step checks the book first. Idempotent."""
    if not history_1133_needed(cn):
        return []
    cur = cn.cursor()
    try:
        for stmt in split_script((sql_dir() / HISTORY_1133).read_text(encoding="utf-8-sig")):
            _apply_stmt(cur, stmt)
            if cur.with_rows:
                cur.fetchall()
        cn.commit()
        return [HISTORY_1133]
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


class Migrate1163Refused(RuntimeError):
    """Card 1163 stopped before changing the book. A name type is wrong, or a suffix will not fit."""


# Letter 5758. The highest rank keeps the bare name. Each lower rank takes the next free name-N.
NAME_RANK_1163 = ("res", "desk", "roster", "tree", "label")

# Pointers that must name one type. seat.desk_id was already a plain id; the others lose their kind column.
_NAME_POINTERS_1163 = (
    ("seat", "desk_id", "desk"),
    ("member", "name_id", "roster"),
    ("human_member", "name_id", "roster"),
    ("activity", "roster_id", "roster"),
    ("mail", "roster_id", "roster"),
    ("todo", "roster_id", "roster"),
    ("doing", "roster_id", "roster"),
    ("score", "roster_id", "roster"),
    ("label", "name_id", "label"),
    ("tree", "name_id", "tree"),
    ("tree_read", "tree_id", "tree"),
    ("hold", "resource_id", "res"),
)

# (table, kind column, index that held it, columns of that index after the drop, ADD statement, fk, fk statement)
_RESHAPE_1163 = (
    ("member", "name_kind", "PRIMARY", ("name_id", "desk_id"),
     "ALTER TABLE member ADD PRIMARY KEY (name_id, desk_id)",
     "fk_member_name",
     "ALTER TABLE member ADD CONSTRAINT fk_member_name FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("human_member", "name_kind", "idx_role", ("name_id", "human_id"),
     "ALTER TABLE human_member ADD KEY idx_role (name_id, human_id)",
     "fk_human_member_name",
     "ALTER TABLE human_member ADD CONSTRAINT fk_human_member_name FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE CASCADE"),
    ("activity", "roster_kind", "idx_roster", ("roster_id", "type", "updated"),
     "ALTER TABLE activity ADD KEY idx_roster (roster_id, type, updated)",
     "fk_activity_roster",
     "ALTER TABLE activity ADD CONSTRAINT fk_activity_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("mail", "roster_kind", "idx_mail_roster", ("roster_id",),
     "ALTER TABLE mail ADD KEY idx_mail_roster (roster_id)",
     "fk_mail_roster",
     "ALTER TABLE mail ADD CONSTRAINT fk_mail_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("todo", "roster_kind", "idx_roster", ("roster_id", "status", "updated"),
     "ALTER TABLE todo ADD KEY idx_roster (roster_id, status, updated)",
     "fk_todo_roster",
     "ALTER TABLE todo ADD CONSTRAINT fk_todo_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("doing", "roster_kind", "idx_roster", ("roster_id",),
     "ALTER TABLE doing ADD KEY idx_roster (roster_id)",
     "fk_doing_roster",
     "ALTER TABLE doing ADD CONSTRAINT fk_doing_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("score", "roster_kind", "idx_score_who", ("roster_id", "desk_key", "kpi"),
     "ALTER TABLE score ADD UNIQUE KEY idx_score_who (roster_id, desk_key, kpi)",
     "fk_score_roster",
     "ALTER TABLE score ADD CONSTRAINT fk_score_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("label", "name_kind", "idx_label_ord", ("name_id", "ord", "created"),
     "ALTER TABLE label ADD KEY idx_label_ord (name_id, ord, created)",
     "fk_label_name",
     "ALTER TABLE label ADD CONSTRAINT fk_label_name FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("tree", "name_kind", "PRIMARY", ("name_id", "type", "id"),
     "ALTER TABLE tree ADD PRIMARY KEY (name_id, type, id)",
     "fk_tree_name",
     "ALTER TABLE tree ADD CONSTRAINT fk_tree_name FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("tree_read", "tree_kind", "idx_tree", ("tree_id",),
     "ALTER TABLE tree_read ADD KEY idx_tree (tree_id)",
     "fk_tree_read_tree",
     "ALTER TABLE tree_read ADD CONSTRAINT fk_tree_read_tree FOREIGN KEY (tree_id) REFERENCES name (id) ON DELETE RESTRICT"),
    ("hold", "resource_kind", "idx_hold", ("resource_id",),
     "ALTER TABLE hold ADD UNIQUE KEY idx_hold (resource_id)",
     "fk_hold_res",
     "ALTER TABLE hold ADD CONSTRAINT fk_hold_res FOREIGN KEY (resource_id) REFERENCES name (id) ON DELETE RESTRICT"),
)


def free_name_suffix(base: str, taken) -> str:
    """Next shell-safe base-N that taken(candidate) says is free. taken is a callable."""
    n = 1
    while True:
        candidate = f"{base}-{n}"
        if len(candidate) > 64:
            raise Migrate1163Refused(f"name suffix exceeds 64 characters: {base}")
        if not taken(candidate):
            return candidate
        n += 1


def _index_cols(cur, table: str, name: str) -> list[str]:
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s "
        "ORDER BY SEQ_IN_INDEX",
        (table, name),
    )
    return [r[0] for r in cur.fetchall()]


def _fk_exists(cur, table: str, name: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s "
        "AND CONSTRAINT_TYPE = 'FOREIGN KEY' LIMIT 1",
        (table, name),
    )
    return cur.fetchone() is not None


def _drop_fk(cur, table: str, name: str) -> None:
    if _fk_exists(cur, table, name):
        cur.execute(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{name}`")


def _name_taken(cur, candidate: str) -> bool:
    """True when any row holds the string, retired and trashed included."""
    cur.execute("SELECT 1 FROM name WHERE name = %s LIMIT 1", (candidate,))
    return cur.fetchone() is not None


def _trigger_statement(text: str, name: str) -> str:
    """One CREATE TRIGGER body from tables.sql, without the client delimiter."""
    key = f"CREATE TRIGGER {name}"
    start = text.index(key)
    end = text.index("END //", start)
    return text[start:end].rstrip() + "\nEND"


def _install_name_fixed(cur) -> None:
    """Replace name_fixed so the collision step can rename a retired row."""
    text = (sql_dir() / "tables.sql").read_text(encoding="utf-8-sig")
    cur.execute("DROP TRIGGER IF EXISTS name_fixed")
    cur.execute(_trigger_statement(text, "name_fixed"))


def _ensure_focus_label_column(cur) -> None:
    """seat.focus_label_id, the desk's focus list. Present on a fresh book already."""
    if not _table_exists(cur, "seat"):
        return
    if not _column_exists(cur, "seat", "focus_label_id"):
        after = " AFTER doing_id" if _column_exists(cur, "seat", "doing_id") else ""
        cur.execute("ALTER TABLE seat ADD COLUMN focus_label_id BIGINT UNSIGNED NULL" + after)
    if _index_cols(cur, "seat", "idx_focus_label") != ["focus_label_id"]:
        _drop_index_if(cur, "seat", "idx_focus_label")
        cur.execute("ALTER TABLE seat ADD UNIQUE KEY idx_focus_label (focus_label_id)")
    if not _fk_exists(cur, "seat", "fk_seat_focus_label"):
        cur.execute(
            "ALTER TABLE seat ADD CONSTRAINT fk_seat_focus_label "
            "FOREIGN KEY (focus_label_id) REFERENCES name (id) ON DELETE RESTRICT"
        )


def _link_focus_labels(cur) -> None:
    """A live label that still shares a live desk's string is that desk's focus list.

    Called before the collision rename, while the two strings still match.
    A retired or trashed label is renamed with every other loser and is not the list.
    """
    if not _column_exists(cur, "seat", "focus_label_id"):
        return
    live = "l.deleted IS NULL"
    if _column_exists(cur, "name", "trashed"):
        live += " AND l.trashed IS NULL"
    cur.execute(
        "UPDATE seat s "
        "JOIN name d ON d.id = s.desk_id AND d.type = 'desk' AND d.deleted IS NULL "
        "JOIN name l ON l.type = 'label' AND l.name = d.name AND " + live + " "
        "SET s.focus_label_id = l.id "
        "WHERE s.focus_label_id IS NULL"
    )


def _rename_name_collisions(cur) -> int:
    """Highest rank keeps the bare string. Each lower row takes the next free name-N."""
    cur.execute("SELECT name FROM name GROUP BY name HAVING COUNT(*) > 1")
    groups = [r[0] for r in cur.fetchall()]
    renamed = 0
    order = ", ".join(f"'{t}'" for t in NAME_RANK_1163)
    for bare in groups:
        cur.execute(
            f"SELECT id, type, name FROM name WHERE name = %s ORDER BY FIELD(type, {order}), id",
            (bare,),
        )
        rows = cur.fetchall()
        for nid, typ, nm in rows[1:]:
            if typ == "res":
                raise Migrate1163Refused("refusing to rename a res name")
            candidate = free_name_suffix(str(nm), lambda c: _name_taken(cur, c))
            cur.execute("UPDATE name SET name = %s WHERE id = %s", (candidate, nid))
            renamed += 1
    return renamed


def _preflight_name_types(cur) -> None:
    bad = []
    for table, column, kind in _NAME_POINTERS_1163:
        if not _table_exists(cur, table) or not _column_exists(cur, table, column):
            continue
        cur.execute(
            f"SELECT COUNT(*) FROM `{table}` t JOIN name n ON n.id = t.`{column}` WHERE n.type <> %s",
            (kind,),
        )
        n = int(cur.fetchone()[0])
        if n:
            bad.append(f"{table}.{column} has {n} {kind} mismatch")
    if bad:
        raise Migrate1163Refused("; ".join(bad))


def _drop_index_if(cur, table: str, name: str) -> None:
    cols = _index_cols(cur, table, name)
    if not cols:
        return
    if name == "PRIMARY":
        cur.execute(f"ALTER TABLE `{table}` DROP PRIMARY KEY")
    else:
        cur.execute(f"ALTER TABLE `{table}` DROP INDEX `{name}`")


def _reshape_1163(cur) -> None:
    for table, _column, index_name, _want, _ddl, fk, _fk_ddl in _RESHAPE_1163:
        _drop_fk(cur, table, fk)
    if _index_exists(cur, "name", "idx_type"):
        cur.execute("ALTER TABLE name DROP INDEX idx_type")
    if _index_exists(cur, "name", "idx_id_type"):
        cur.execute("ALTER TABLE name DROP INDEX idx_id_type")
    if _index_cols(cur, "name", "idx_name") != ["name"]:
        _drop_index_if(cur, "name", "idx_name")
        cur.execute("ALTER TABLE name ADD UNIQUE KEY idx_name (name)")
    for table, column, index_name, want, ddl, fk, fk_ddl in _RESHAPE_1163:
        if _column_exists(cur, table, column):
            _drop_kind_checks(cur, table, column)
            cols = _index_cols(cur, table, index_name)
            if column in cols:
                _drop_index_if(cur, table, index_name)
            cur.execute(f"ALTER TABLE `{table}` DROP COLUMN `{column}`")
        # Card 1214 drops score.roster_id and score.desk_key. Do not put that
        # index back once those columns are gone.
        if any(not _column_exists(cur, table, col) for col in want):
            continue
        if _index_cols(cur, table, index_name) != list(want):
            _drop_index_if(cur, table, index_name)
            cur.execute(ddl)
        if not _fk_exists(cur, table, fk):
            cur.execute(fk_ddl)


def name_type_trigger_sql(text: str) -> list[tuple[str, str]]:
    """The card 1163 triggers between the markers. Leading comments are not part of the statement."""
    start = text.index("-- card 1163 name-type triggers BEGIN")
    end = text.index("-- card 1163 name-type triggers END")
    out: list[tuple[str, str]] = []
    for part in text[start:end].split("//"):
        lines: list[str] = []
        started = False
        for line in part.splitlines():
            if not started:
                if not line.strip().upper().startswith("CREATE TRIGGER"):
                    continue
                started = True
            lines.append(line)
        stmt = "\n".join(lines).strip()
        if not stmt.upper().startswith("CREATE TRIGGER"):
            continue
        out.append((stmt.split()[2], stmt))
    return out


def _install_name_type_triggers(cur) -> int:
    found = name_type_trigger_sql((sql_dir() / "tables.sql").read_text(encoding="utf-8-sig"))
    if len(found) != 24:
        raise Migrate1163Refused(f"expected 24 name-type triggers, parsed {len(found)}")
    for name, stmt in found:
        cur.execute(f"DROP TRIGGER IF EXISTS `{name}`")
        cur.execute(stmt)
    return len(found)


def _drop_kind_checks(cur, table: str, column: str) -> None:
    """Drop a CHECK that names the kind column. DROP COLUMN does not always take it."""
    cur.execute(
        "SELECT c.CONSTRAINT_NAME, c.CHECK_CLAUSE "
        "FROM information_schema.CHECK_CONSTRAINTS c "
        "JOIN information_schema.TABLE_CONSTRAINTS t "
        "ON t.CONSTRAINT_SCHEMA = c.CONSTRAINT_SCHEMA AND t.CONSTRAINT_NAME = c.CONSTRAINT_NAME "
        "WHERE c.CONSTRAINT_SCHEMA = DATABASE() AND t.TABLE_NAME = %s AND t.CONSTRAINT_TYPE = 'CHECK'",
        (table,),
    )
    for name, clause in cur.fetchall():
        if column in (clause or "").replace("`", ""):
            cur.execute(f"ALTER TABLE `{table}` DROP CHECK `{name}`")


# Card 1207 (the owner, 2026-11-13): doing is only tw runs (act task). Card and hold moves leave doing for
# transition; ship/done evidence moves to todo.meta.evidence (a JSON key, not capped); a tw run's card moves to
# its tw_start transition meta.card; focus, clear, finish, rename and name trash/restore/purge rows go (a name is
# not an activity, so its timeline has no anchor). Then seat.doing_id and the doing columns past the six go.
# Each step checks the book first, so a rerun is a no-op.
_MOVE_ACTS_1207 = ("create", "park", "unpark", "claim", "assign", "unclaim", "ship", "done", "back",
                   "hold", "drop", "rename", "delete", "restore", "purge")
# act -> (activity_type, from_state, to_state, reason) for a move row with no transition row yet.
_MOVE_EDGE_1207 = {
    "create": ("todo", "none", "open", "create"),
    "park": ("todo", "none", "parked", "create_parked"),
    "unpark": ("todo", "parked", "open", "unpark"),
    "claim": ("todo", "open", "claimed", "claim"),
    "assign": ("todo", "open", "claimed", "assign"),
    "unclaim": ("todo", "claimed", "open", "unclaim"),
    "ship": ("todo", "claimed", "shipped", "pass_ship"),
    "done": ("todo", "shipped", "done", "pass_done"),
    "back": ("todo", "shipped", "open", "pass_back"),
    "rename": ("todo", "any", "same", "rename"),
    "hold": ("hold", "free", "held", "hold_grant"),
    "drop": ("hold", "held", "free", "hold_drop"),
}
# An old take-over (cmd_claim --take-over) is a claim row whose peer_id is another desk (the one it took the card
# from; a plain claim has none, and migrate_080 wrote the claimer itself); its transition was written as take_over
# (T6 claimed->claimed). Either reason covers a claim row.
_TAKE_OVER_1207 = ("todo", "claimed", "claimed", "take_over")
_CLAIM_REASONS_1207 = ("claim", "take_over")
_EDGES_1207 = (("todo", "any", "same", "rename"),)
_NAME_REASONS_1207 = ("name_delete", "name_purge", "name_restore")
# FK before index (an index a foreign key uses can't go first), then the columns.
SEAT_DOING_SQL_1207 = (
    "ALTER TABLE seat DROP FOREIGN KEY fk_seat_doing, DROP INDEX idx_doing, DROP COLUMN doing_id"
)
DOING_COLS_SQL_1207 = (
    "ALTER TABLE doing DROP FOREIGN KEY fk_doing_peer, DROP INDEX idx_peer, DROP INDEX idx_on,"
    " DROP INDEX idx_id_desk, DROP COLUMN on_type, DROP COLUMN on_id, DROP COLUMN waiting_type,"
    " DROP COLUMN waiting_id, DROP COLUMN waiting_why, DROP COLUMN act, DROP COLUMN peer_id"
)


def _alter_1207(cur, table: str, fks: list[str], idxs: list[str], cols: list[str]) -> str:
    """One ALTER in FK, index, column order, with only the parts the book still has (the full statements are
    SEAT_DOING_SQL_1207 and DOING_COLS_SQL_1207)."""
    cur.execute(
        "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s AND CONSTRAINT_TYPE = 'FOREIGN KEY'", (table,))
    have_fk = {r[0] for r in cur.fetchall()}
    cur.execute(
        "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE()"
        " AND TABLE_NAME = %s", (table,))
    have_ix = {r[0] for r in cur.fetchall()}
    parts = [f"DROP FOREIGN KEY {f}" for f in fks if f in have_fk]
    parts += [f"DROP INDEX {i}" for i in idxs if i in have_ix]
    parts += [f"DROP COLUMN {c}" for c in cols if _column_exists(cur, table, c)]
    return f"ALTER TABLE {table} " + ", ".join(parts)


def _drain(cur) -> None:
    while cur.nextset():
        if cur.with_rows:
            cur.fetchall()


# doing.created was written in the session zone (CURRENT_TIMESTAMP); converted per row, so a DST zone gives
# each row its own offset. SYSTEM and fixed offsets need no time zone tables.
_BOOK_TO_UTC_1207 = "CONVERT_TZ(d.created, @@session.time_zone, '+00:00')"


def _reanchor_connect_1207(cur) -> int:
    """Connect and disconnect rows (card 1028) were anchored on activity('doing', desk_id); once tw doing ids pass
    the desk ids they land on a real run's trail (Validator, 1207 q4). Move them to the connect anchor
    (connect_activity.anchor_id), then drop the old pseudo activity row when nothing else uses it. The new
    activity row takes the connecting desk's desk_id (the old activity id), not the copied row's desk_id,
    which may belong to a tw run that reused that id. A rerun finds nothing to move. Returns the transition
    rows moved."""
    from agent_coord.server.connect_activity import CONNECT_ANCHOR_BASE

    if not _table_exists(cur, "transition") or not _table_exists(cur, "activity"):
        return 0
    old = ("t.activity_type = 'doing' AND t.activity_id = t.desk_id AND t.join_key LIKE 'connect:%%'"
           " AND t.activity_id < %s")
    cur.execute(
        "INSERT IGNORE INTO activity (type, id, created, updated, desk_id, roster_id, act, bytes)"
        " SELECT a.type, a.id + %s, a.created, a.updated, a.id, a.roster_id, a.act, a.bytes"
        " FROM activity a WHERE a.type = 'doing' AND a.id IN"
        f" (SELECT DISTINCT t.activity_id FROM transition t WHERE {old})",
        (CONNECT_ANCHOR_BASE, CONNECT_ANCHOR_BASE),
    )
    cur.execute(
        f"UPDATE transition t SET t.activity_id = t.activity_id + %s WHERE {old}",
        (CONNECT_ANCHOR_BASE, CONNECT_ANCHOR_BASE),
    )
    moved = cur.rowcount
    if moved:
        cur.execute(
            "SELECT n.id - %s FROM activity n WHERE n.type = 'doing' AND n.id > %s"
            " AND NOT EXISTS (SELECT 1 FROM doing g WHERE g.id = n.id - %s)"
            " AND NOT EXISTS (SELECT 1 FROM transition t WHERE t.activity_type = 'doing' AND t.activity_id = n.id - %s)"
            " AND NOT EXISTS (SELECT 1 FROM tree r WHERE r.type = 'doing' AND r.id = n.id - %s)",
            (CONNECT_ANCHOR_BASE,) * 5,
        )
        gone = [int(r[0]) for r in cur.fetchall()]
        if gone:
            cur.execute("DELETE FROM activity WHERE type = 'doing' AND id IN (" + ",".join(["%s"] * len(gone)) + ")",
                        gone)
    return moved


def apply_1212(cn) -> list[str]:
    """Card 1212: score_view on a book that already exists. Fresh books get it from tables.sql."""
    cur = cn.cursor()
    try:
        if _table_exists(cur, "score_view"):
            return []
        cur.execute(
            "CREATE TABLE score_view ("
            " score_id BIGINT UNSIGNED NOT NULL,"
            " viewer_id BIGINT UNSIGNED NOT NULL,"
            " n INT UNSIGNED NOT NULL DEFAULT 0,"
            " last_seen DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
            " PRIMARY KEY (score_id, viewer_id),"
            " KEY idx_viewer (viewer_id, last_seen),"
            " CONSTRAINT fk_score_view_score FOREIGN KEY (score_id) REFERENCES score (id)"
            " ON DELETE RESTRICT ON UPDATE CASCADE"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
        )
        cn.commit()
        return ["migrate_1212:score_view"]
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def _drop_score_triggers(cur) -> list[str]:
    """The retired roster triggers still name score.roster_id. A fresh script drops them. An upgrade must too."""
    cur.execute(
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
        "WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME IN "
        "('score_roster_type_ins', 'score_roster_type_upd')"
    )
    names = [str(r[0]) for r in cur.fetchall()]
    for name in names:
        cur.execute(f"DROP TRIGGER IF EXISTS `{name}`")
    return [f"migrate_1214:dropped trigger {name}" for name in names]


def _delete_score_row(cur, sid: int) -> None:
    """Remove one score and the rows that hang on it. The activity row goes with the score."""
    if _table_exists(cur, "score_evidence"):
        cur.execute("DELETE FROM score_evidence WHERE score_id = %s", (sid,))
    if _table_exists(cur, "score_point"):
        cur.execute("DELETE FROM score_point WHERE score_id = %s", (sid,))
    if _table_exists(cur, "score_view") and _column_exists(cur, "score_view", "score_id"):
        cur.execute("DELETE FROM score_view WHERE score_id = %s", (sid,))
    if _table_exists(cur, "watcher"):
        cur.execute("DELETE FROM watcher WHERE type = 'score' AND id = %s", (sid,))
    if _table_exists(cur, "transition"):
        cur.execute(
            "DELETE FROM transition WHERE activity_type = 'score' AND activity_id = %s",
            (sid,),
        )
    if _table_exists(cur, "tree"):
        cur.execute("DELETE FROM tree WHERE type = 'score' AND id = %s", (sid,))
    if _table_exists(cur, "label"):
        cur.execute("DELETE FROM label WHERE type = 'score' AND id = %s", (sid,))
    if _table_exists(cur, "activity"):
        cur.execute("DELETE FROM activity WHERE type = 'score' AND id = %s", (sid,))
    cur.execute("DELETE FROM score WHERE id = %s", (sid,))


def _merge_score_row(cur, loser: int, keeper: int) -> int:
    """Move points and evidence onto the keeper. A timestamp the keeper already has is dropped."""
    dropped_slots = 0
    if _table_exists(cur, "score_evidence"):
        cur.execute(
            "SELECT COUNT(*) FROM score_evidence e "
            "JOIN score_evidence k ON k.score_id = %s AND k.`timestamp` = e.`timestamp` "
            "WHERE e.score_id = %s",
            (keeper, loser),
        )
        dropped_slots = int((cur.fetchone() or (0,))[0] or 0)
        cur.execute(
            "DELETE e FROM score_evidence e "
            "JOIN score_evidence k ON k.score_id = %s AND k.`timestamp` = e.`timestamp` "
            "WHERE e.score_id = %s",
            (keeper, loser),
        )
        cur.execute(
            "UPDATE score_evidence SET score_id = %s WHERE score_id = %s",
            (keeper, loser),
        )
    if _table_exists(cur, "score_point"):
        cur.execute(
            "UPDATE score_point SET score_id = %s WHERE score_id = %s",
            (keeper, loser),
        )
    _delete_score_row(cur, loser)
    return dropped_slots


def _activity_desk_matches(cur, sid: int, desk_id: int) -> bool:
    """True when there is no activity row, or that row already names this desk.

    An activity row with an empty desk is not filled in. The series is dropped instead.
    """
    if not _table_exists(cur, "activity"):
        return True
    cur.execute(
        "SELECT desk_id FROM activity WHERE type = 'score' AND id = %s",
        (sid,),
    )
    row = cur.fetchone()
    if row is None:
        return True
    return row[0] is not None and int(row[0]) == int(desk_id)


def _report_non_numeric_values(cur) -> list[str]:
    """score.value was text. A word cannot become a point, so it is dropped and named."""
    if not _column_exists(cur, "score", "value"):
        return []
    cur.execute(
        "SELECT id, kpi, `value` FROM score "
        "WHERE `value` IS NOT NULL AND `value` <> '' "
        "AND `value` NOT REGEXP '^-?[0-9]+([.][0-9]+)?$'"
    )
    notes = []
    for sid, kpi, val in cur.fetchall():
        text = str(val).replace("\n", " ").replace("\r", " ")[:80]
        notes.append(f"migrate_1214:dropped value id={int(sid)} kpi={kpi} text={text}")
    return notes


def _seat_holds(cur, desk_id: int) -> bool:
    if not _table_exists(cur, "seat"):
        return True
    cur.execute("SELECT 1 FROM seat WHERE desk_id = %s", (desk_id,))
    return cur.fetchone() is not None


def _cleanup_score_rows(cur) -> list[str]:
    """One desk and one kpi. Keep a series whose points name one desk. Report every series that cannot."""
    notes: list[str] = []
    cur.execute("SELECT id, kpi FROM score WHERE desk_id IS NULL")
    pending = [(int(r[0]), str(r[1] or "")) for r in cur.fetchall()]
    for sid, kpi in pending:
        desks: list[int] = []
        n_pt = 0
        if _table_exists(cur, "score_point"):
            cur.execute(
                "SELECT DISTINCT desk_id FROM score_point WHERE score_id = %s AND desk_id IS NOT NULL",
                (sid,),
            )
            desks = [int(r[0]) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) FROM score_point WHERE score_id = %s", (sid,))
            n_pt = int((cur.fetchone() or (0,))[0] or 0)
        if len(desks) == 1 and _seat_holds(cur, desks[0]) and _activity_desk_matches(cur, sid, desks[0]):
            cur.execute(
                "SELECT id FROM score WHERE desk_id = %s AND kpi = %s AND id <> %s LIMIT 1",
                (desks[0], kpi, sid),
            )
            other = cur.fetchone()
            if other:
                slots = _merge_score_row(cur, sid, int(other[0]))
                notes.append(
                    f"migrate_1214:merged id={sid} into={int(other[0])} kpi={kpi} "
                    f"desk={desks[0]} evidence_slots_dropped={slots}"
                )
            else:
                cur.execute("UPDATE score SET desk_id = %s WHERE id = %s", (desks[0], sid))
                notes.append(f"migrate_1214:attached id={sid} kpi={kpi} desk={desks[0]} points={n_pt}")
            continue
        if len(desks) == 1 and _seat_holds(cur, desks[0]):
            reason = "activity-desk"
        elif len(desks) == 1:
            reason = "no-seat"
        elif len(desks) == 0:
            reason = "no-desk"
        else:
            reason = "many-desks"
        who = ",".join(str(d) for d in desks) or "-"
        notes.append(
            f"migrate_1214:dropped id={sid} kpi={kpi} reason={reason} points={n_pt} desks={who}"
        )
        _delete_score_row(cur, sid)
    cur.execute(
        "SELECT desk_id, kpi FROM score WHERE desk_id IS NOT NULL GROUP BY desk_id, kpi HAVING COUNT(*) > 1"
    )
    groups = [(int(r[0]), str(r[1] or "")) for r in cur.fetchall()]
    for desk, kpi in groups:
        cur.execute(
            "SELECT id FROM score WHERE desk_id = %s AND kpi = %s ORDER BY updated DESC, id DESC",
            (desk, kpi),
        )
        ids = [int(r[0]) for r in cur.fetchall()]
        keeper = ids[0]
        for loser in ids[1:]:
            slots = _merge_score_row(cur, loser, keeper)
            notes.append(
                f"migrate_1214:merged id={loser} into={keeper} kpi={kpi} "
                f"desk={desk} evidence_slots_dropped={slots}"
            )
    return notes


def apply_1214(cn) -> list[str]:
    """Card 1214: a score is one desk and one kpi. meta holds the markup. Views point at score.id.

    A series with no desk is kept when its points name one desk. Anything else is removed and named
    in the returned lines, so an upgrade says what it could not keep.
    """
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "score"):
            return []
        notes = _drop_score_triggers(cur)
        changed = bool(notes)
        if _column_exists(cur, "score", "roster_id"):
            if not _column_exists(cur, "score", "meta"):
                cur.execute("ALTER TABLE score ADD COLUMN meta JSON NULL")
            sets = []
            for key, col in (("target", "target"), ("better", "better"), ("unit", "unit")):
                if _column_exists(cur, "score", col):
                    sets.append(f"'$.{key}', `{col}`")
            if sets:
                cur.execute(
                    "UPDATE score SET meta = JSON_SET(IFNULL(meta, JSON_OBJECT()), "
                    + ", ".join(sets) + ")"
                )
            notes.extend(_report_non_numeric_values(cur))
            notes.extend(_cleanup_score_rows(cur))
            _drop_fk(cur, "score", "fk_score_roster")
            # The old key has no ON UPDATE CASCADE (desk_key blocked it). Drop it before
            # the column change, then put back the same key the other kind tables use.
            _drop_fk(cur, "score", "fk_score_desk")
            if _index_exists(cur, "score", "idx_score_who"):
                cur.execute("ALTER TABLE score DROP INDEX idx_score_who")
            if _index_exists(cur, "score", "idx_desk"):
                cur.execute("ALTER TABLE score DROP INDEX idx_desk")
            for col in ("desk_key", "value", "target", "note", "better", "unit", "roster_id"):
                if _column_exists(cur, "score", col):
                    cur.execute(f"ALTER TABLE score DROP COLUMN `{col}`")
            cur.execute("ALTER TABLE score MODIFY desk_id BIGINT UNSIGNED NOT NULL")
            if not _index_exists(cur, "score", "idx_desk_kpi"):
                cur.execute("ALTER TABLE score ADD UNIQUE KEY idx_desk_kpi (desk_id, kpi)")
            cur.execute(
                "ALTER TABLE score ADD CONSTRAINT fk_score_desk FOREIGN KEY (desk_id)"
                " REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE"
            )
            changed = True
        elif _index_exists(cur, "score", "idx_desk") and _index_exists(cur, "score", "idx_desk_kpi"):
            _drop_fk(cur, "score", "fk_score_desk")
            cur.execute("ALTER TABLE score DROP INDEX idx_desk")
            cur.execute(
                "ALTER TABLE score ADD CONSTRAINT fk_score_desk FOREIGN KEY (desk_id)"
                " REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE"
            )
            changed = True
        if _table_exists(cur, "score_view") and _column_exists(cur, "score_view", "kpi"):
            cur.execute("DROP TABLE score_view")
            cur.execute(
                "CREATE TABLE score_view ("
                " score_id BIGINT UNSIGNED NOT NULL,"
                " viewer_id BIGINT UNSIGNED NOT NULL,"
                " n INT UNSIGNED NOT NULL DEFAULT 0,"
                " last_seen DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),"
                " PRIMARY KEY (score_id, viewer_id),"
                " KEY idx_viewer (viewer_id, last_seen),"
                " CONSTRAINT fk_score_view_score FOREIGN KEY (score_id) REFERENCES score (id)"
                " ON DELETE RESTRICT ON UPDATE CASCADE"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci"
            )
            changed = True
        cn.commit()
        if changed:
            notes.append("migrate_1214:score")
        return notes
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def apply_1207(cn, report: dict | None = None) -> list[str]:
    """Card 1207 data and schema. report (tests) gets the counts: evidence backfilled, move rows covered by a
    transition row, move rows backfilled to transition, move rows deleted, evidence rows with no card left,
    name rows dropped, tw cards backfilled, non-task rows deleted and kept with a trail."""
    applied: list[str] = []
    rep = report if report is not None else {}
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "doing") or not _table_exists(cur, "transition_edge"):
            return applied
        # A zone that cannot convert must stop before any write, so "Nothing was changed" is true:
        # the name-row deletes, the connect re-anchor and the rename edge would otherwise already
        # be committed (Validator W1).
        acts = ", ".join(f"'{a}'" for a in _MOVE_ACTS_1207)
        utc = _BOOK_TO_UTC_1207
        if _column_exists(cur, "doing", "act"):
            cur.execute(f"SELECT @@session.time_zone, COUNT(*) FROM doing d WHERE d.act IN ({acts}) AND {utc} IS NULL")
            tz, bad = cur.fetchone()
            if int(bad or 0):
                raise RuntimeError(
                    f"card 1207: session time_zone {tz!r} cannot convert {int(bad)} doing.created values to UTC"
                    " (CONVERT_TZ is NULL; load the MySQL time zone tables, or set time_zone to SYSTEM or an"
                    " offset like the book was written with), then start the office again. Nothing was changed."
                )
        # Part 1 of this card anchored name events on focus rows; those edges and rows go.
        names = ", ".join(f"'{r}'" for r in _NAME_REASONS_1207)
        cur.execute(f"DELETE FROM transition WHERE activity_type = 'doing' AND reason IN ({names})")
        rep["name_transitions_deleted"] = cur.rowcount
        cur.execute(f"DELETE FROM transition_edge WHERE activity_type = 'doing' AND reason IN ({names})")
        cn.commit()
        moved = _reanchor_connect_1207(cur)
        rep["connect_rows_moved"] = moved
        if moved:
            applied.append("migrate_1207:connect_anchor(%d)" % moved)
        cn.commit()
        if not _column_exists(cur, "doing", "act"):
            return applied
        cur.executemany(
            "INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES (%s,%s,%s,%s)",
            list(_EDGES_1207),
        )
        if cur.rowcount:
            applied.append("transition_edge.card_1207")
        cn.commit()
        # 0. A row that is not a tw run but that a tree node names can't go (doing_no_delete_in_tree,
        # fk_tree_activity), and a plan's node is the user's: the row stays, with its node and activity row,
        # and gets one terminal row (any -> cleared, clear, meta.cause migrate_1207) so no reader counts it live.
        cur.execute(
            "INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role, meta)"
            " SELECT 'doing', d.id, 'any', 'cleared', 'clear', d.desk_id, 'actor', JSON_OBJECT('cause', 'migrate_1207')"
            " FROM doing d JOIN activity a ON a.type = 'doing' AND a.id = d.id"
            " WHERE d.act <> 'task' AND EXISTS (SELECT 1 FROM tree r WHERE r.type = 'doing' AND r.id = d.id)"
            "   AND NOT EXISTS (SELECT 1 FROM transition e WHERE e.activity_type = 'doing' AND e.activity_id = d.id"
            "     AND e.to_state IN ('finished', 'failed', 'stale', 'cleared'))"
            " ORDER BY d.id"
        )
        rep["kept_for_tree"] = cur.rowcount
        cur.execute(f"SELECT COUNT(*) FROM doing WHERE act IN ({acts})")
        moves = int(cur.fetchone()[0])
        if moves:
            # The book clock (doing.created, CURRENT_TIMESTAMP in the session zone) to UTC (transition.at), per
            # row: on a DST zone a row from the other half of the year has the other offset (Validator, 1207).
            # The CONVERT_TZ guard ran at the start of this function, before any write.
            if _column_exists(cur, "doing", "evidence"):
                # 1. Evidence: the card's newest ship/done/back row; ship or done with evidence -> meta.evidence,
                # byte-equal. A step back leaves none. Only the newest is kept (meta holds one).
                cur.execute(
                    "UPDATE todo t JOIN ("
                    " SELECT d.on_id, d.act, d.evidence, ROW_NUMBER() OVER ("
                    "   PARTITION BY d.on_id ORDER BY d.created DESC, d.id DESC) AS rn"
                    " FROM doing d WHERE d.on_type = 'todo' AND d.act IN ('ship', 'done', 'back')) x"
                    " ON x.on_id = t.id AND x.rn = 1"
                    " SET t.meta = JSON_SET(IFNULL(t.meta, JSON_OBJECT()), '$.evidence', x.evidence),"
                    "     t.updated = t.updated"
                    " WHERE x.act IN ('ship', 'done') AND x.evidence IS NOT NULL"
                    "   AND JSON_EXTRACT(IFNULL(t.meta, JSON_OBJECT()), '$.evidence') IS NULL"
                )
                rep["evidence_backfilled"] = cur.rowcount
                cur.execute(
                    "SELECT COUNT(*) FROM doing d LEFT JOIN todo t ON t.id = d.on_id"
                    " WHERE d.on_type = 'todo' AND d.act IN ('ship', 'done') AND d.evidence IS NOT NULL"
                    "   AND t.id IS NULL"
                )
                rep["evidence_no_card"] = int(cur.fetchone()[0])
            # 2. Coverage: a card or hold move row is covered when its item has a transition row by the same
            # desk with the mapped reason within 5 seconds (the Python emitters write just after the SQL),
            # or a compressed hold row (card 1098, n > 1) for that hold and desk at or after it.
            covered = 0
            backfilled = 0
            peer = _column_exists(cur, "doing", "peer_id")
            passes = []
            for act, edge in _MOVE_EDGE_1207.items():
                if act == "claim" and peer:
                    passes.append((act, "NOT (d.peer_id IS NOT NULL AND d.peer_id <> d.desk_id)", edge))
                    passes.append((act, "(d.peer_id IS NOT NULL AND d.peer_id <> d.desk_id)", _TAKE_OVER_1207))
                else:
                    passes.append((act, "TRUE", edge))
            for act, which, (atype, frm, to, reason) in passes:
                reasons = _CLAIM_REASONS_1207 if act == "claim" else (reason,)
                rin = ", ".join(["%s"] * len(reasons))
                jk = ("CONCAT('card:', d.on_id)" if atype == "todo"
                      else "CONCAT('hold:', d.on_id, ':', d.desk_id)")
                # The fixture flag as todo_activity.roster_excluded (no routine needed here).
                meta = ("(SELECT IF(REGEXP_LIKE(r.name, '^(fx-|cold-test\\\\b|t-[0-9a-f]{8}$)', 'i'),"
                        " JSON_OBJECT('fx', 1), NULL) FROM name r WHERE r.id = d.roster_id)"
                        if atype == "todo" else "NULL")
                cover = (
                    "EXISTS (SELECT 1 FROM transition t WHERE t.activity_type = d.on_type"
                    f" AND t.activity_id = d.on_id AND t.desk_id = d.desk_id AND t.reason IN ({rin})"
                    f" AND ABS(TIMESTAMPDIFF(SECOND, {utc}, t.at)) <= 5)"
                    + (" OR EXISTS (SELECT 1 FROM transition t WHERE t.activity_type = 'hold'"
                       " AND t.activity_id = d.on_id AND t.desk_id = d.desk_id AND t.n > 1"
                       f" AND t.at >= {utc})" if atype == "hold" else "")
                )
                args = list(reasons)
                cur.execute(
                    f"SELECT COUNT(*) FROM doing d WHERE d.act = %s AND d.on_type = %s AND {which} AND ({cover})",
                    [act, atype] + args,
                )
                covered += int(cur.fetchone()[0])
                cur.execute(
                    "INSERT INTO transition (at, activity_type, activity_id, from_state, to_state, reason,"
                    " desk_id, role, join_key, meta)"
                    f" SELECT {utc}, d.on_type, d.on_id, %s, %s, %s, d.desk_id, 'actor',"
                    f" {jk}, {meta}"
                    " FROM doing d JOIN activity a ON a.type = d.on_type AND a.id = d.on_id"
                    f" WHERE d.act = %s AND d.on_type = %s AND {which} AND NOT ({cover})"
                    " ORDER BY d.created, d.id",
                    [frm, to, reason, act, atype] + args,
                )
                backfilled += cur.rowcount
                if act == "assign" and peer:
                    # 0.8.14 kept the assignee on doing.peer_id, and step 4 deletes that row: copy it to the
                    # transition's meta.to (todo_activity.emit_assign's shape), for the row just backfilled and
                    # for an old one that lacks it, matched as the cover is. Other meta keys and a set 'to' stay.
                    cur.execute(
                        "UPDATE transition t JOIN doing d ON t.activity_type = d.on_type AND t.activity_id = d.on_id"
                        " AND t.desk_id = d.desk_id AND t.reason = %s"
                        f" AND ABS(TIMESTAMPDIFF(SECOND, {utc}, t.at)) <= 5"
                        " SET t.meta = JSON_SET(IFNULL(t.meta, JSON_OBJECT()), '$.to', CAST(d.peer_id AS SIGNED))"
                        " WHERE d.act = %s AND d.on_type = %s AND d.peer_id > 0"
                        "   AND JSON_EXTRACT(IFNULL(t.meta, JSON_OBJECT()), '$.to') IS NULL",
                        [reason, act, atype],
                    )
            rep["moves_covered"] = covered
            rep["moves_backfilled"] = backfilled
            # 3. A name's trash, restore or purge (text 'kind:name'): dropped (no anchor; counted).
            cur.execute("SELECT COUNT(*) FROM doing d WHERE d.act IN ('rename', 'delete', 'restore', 'purge')")
            rep["name_rows"] = int(cur.fetchone()[0])
            # 4. Delete the move and timeline rows, their watchers and their activity rows (move rows have none;
            # the name rows do). A row a tree node names was given its own trail above, so it stays.
            # A row with its own transition trail is an activity, not a move record (a tw task row's act
            # rewritten by hand): it stays, and is counted.
            own = ("NOT EXISTS (SELECT 1 FROM transition t WHERE t.activity_type = 'doing'"
                   " AND t.activity_id = d.id)")
            cur.execute(f"SELECT COUNT(*) FROM doing d WHERE d.act IN ({acts}) AND NOT {own}")
            rep["moves_kept_with_trail"] = int(cur.fetchone()[0])
            cur.execute(
                f"DELETE w FROM watcher w JOIN doing d ON w.type = 'doing' AND w.id = d.id"
                f" WHERE d.act IN ({acts}) AND {own}"
            )
            cur.execute(
                f"DELETE a FROM activity a JOIN doing d ON a.type = 'doing' AND a.id = d.id"
                f" WHERE d.act IN ({acts}) AND {own}"
            )
            cur.execute(f"DELETE d FROM doing d WHERE d.act IN ({acts}) AND {own}")
            rep["moves_deleted"] = cur.rowcount
            cn.commit()
            applied.append("migrate_1207:moves(%d)" % rep["moves_deleted"])
        # 5. A tw run's card (on_type todo, on_id) rides in its tw_start meta.card; fill it where tw had not.
        cur.execute(
            "UPDATE transition t JOIN doing d ON d.id = t.activity_id"
            " SET t.meta = JSON_SET(IFNULL(t.meta, JSON_OBJECT()), '$.card', d.on_id)"
            " WHERE t.activity_type = 'doing' AND t.reason = 'tw_start' AND d.act = 'task'"
            "   AND d.on_type = 'todo' AND d.on_id IS NOT NULL"
            "   AND JSON_EXTRACT(IFNULL(t.meta, JSON_OBJECT()), '$.card') IS NULL"
        )
        rep["tw_cards_backfilled"] = cur.rowcount
        # 6. Every row that is not a tw run (focus, clear, finish, and any move left): its watchers, its
        # activity row when no transition names it (one a tree node names stays: fk_tree_activity is
        # RESTRICT), then the row, unless a tree node names it (step 0 ended it). Connect rows moved to their
        # own anchor above. Labels on a deleted activity row go with it (fk_label_activity CASCADE).
        if _column_exists(cur, "seat", "doing_id"):
            cur.execute("UPDATE seat SET doing_id = NULL, updated = updated WHERE doing_id IS NOT NULL")
        trail = ("EXISTS (SELECT 1 FROM transition t WHERE t.activity_type = 'doing' AND t.activity_id = d.id)")
        cur.execute(f"SELECT COUNT(*) FROM doing d WHERE d.act <> 'task' AND {trail}")
        rep["non_task_with_trail"] = int(cur.fetchone()[0])
        cur.execute("DELETE w FROM watcher w JOIN doing d ON w.type = 'doing' AND w.id = d.id WHERE d.act <> 'task'")
        free = (f"d.act <> 'task' AND NOT {trail}"
                " AND NOT EXISTS (SELECT 1 FROM tree r WHERE r.type = 'doing' AND r.id = d.id)")
        cur.execute(f"SELECT COUNT(*) FROM label l JOIN doing d ON l.type = 'doing' AND l.id = d.id WHERE {free}")
        rep["non_task_labels_dropped"] = int(cur.fetchone()[0])
        cur.execute(f"DELETE a FROM activity a JOIN doing d ON a.type = 'doing' AND a.id = d.id WHERE {free}")
        cur.execute("DELETE d FROM doing d WHERE d.act <> 'task'"
                    " AND NOT EXISTS (SELECT 1 FROM tree r WHERE r.type = 'doing' AND r.id = d.id)")
        rep["non_task_deleted"] = cur.rowcount
        cn.commit()
        applied.append("migrate_1207:non_task(%d)" % rep["non_task_deleted"])
        # 7. Schema. doing.evidence and its check, then seat.doing_id, then the doing columns past the six.
        if _column_exists(cur, "doing", "evidence"):
            _drop_kind_checks(cur, "doing", "evidence")
            cur.execute("ALTER TABLE doing DROP COLUMN evidence")
            applied.append("migrate_1207:doing.evidence")
        if _column_exists(cur, "seat", "doing_id"):
            cur.execute(_alter_1207(cur, "seat", ["fk_seat_doing"], ["idx_doing"], ["doing_id"]))
            applied.append("migrate_1207:seat.doing_id")
        for col in ("on_type", "act", "waiting_type"):
            _drop_kind_checks(cur, "doing", col)
        cur.execute(_alter_1207(cur, "doing", ["fk_doing_peer"], ["idx_peer", "idx_on", "idx_id_desk"],
                                ["on_type", "on_id", "waiting_type", "waiting_id", "waiting_why", "act", "peer_id"]))
        applied.append("migrate_1207:doing.columns")
        cn.commit()
        return applied
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def apply_1200(cn) -> list[str]:
    """Card 1200: ON UPDATE CASCADE on every foreign key, and the id-change flag.

    Idempotent. A fresh book already has the keys from tables.sql. migrations.sql
    is the same shape for a book that was built before this card.
    """
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "member"):
            return []
        cur.execute(
            "SELECT UPDATE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'fk_member_desk' "
            "LIMIT 1"
        )
        row = cur.fetchone()
        cur.execute(
            "SELECT ACTION_STATEMENT FROM information_schema.TRIGGERS "
            "WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME = 'name_fixed' LIMIT 1"
        )
        trig = cur.fetchone()
        cascaded = row is not None and str(row[0]).upper() == "CASCADE"
        flagged = trig is not None and "mill_allow_name_id_change" in str(trig[0])
        if cascaded and flagged:
            return []
        blob = (sql_dir() / "migrations.sql").read_text(encoding="utf-8-sig")
        score_roster = _column_exists(cur, "score", "roster_id")
        for stmt in split_script(blob):
            low = stmt.lower()
            if not score_roster and "fk_score_roster" in low:
                continue
            if "drop index" in low and "idx_score_who" in low and not _index_exists(cur, "score", "idx_score_who"):
                continue
            if "drop column" in low and "desk_key" in low and not _column_exists(cur, "score", "desk_key"):
                continue
            if "drop foreign key" in low and "fk_score_desk" in low and not _fk_exists(cur, "score", "fk_score_desk"):
                continue
            try:
                cur.execute(stmt)
            except Exception as exc:
                raise RuntimeError(stmt[:240]) from exc
        cn.commit()
        return ["migrate_1200:cascade"]
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def apply_1163(cn) -> list[str]:
    """One name string in the office. Plain id pointers, type triggers, collision suffixes.

    Idempotent. migrate_080.sql is not changed. A wrong name.type on an existing pointer
    refuses the run; name.type is not rewritten.
    """
    cur = cn.cursor()
    try:
        if not _table_exists(cur, "name"):
            return []
        already = _book_is_1163(cn)
        _preflight_name_types(cur)
        # The trigger on an older book refuses a retired rename. Install the flag form first.
        _install_name_fixed(cur)
        _ensure_focus_label_column(cur)
        renamed = 0
        if not already:
            _link_focus_labels(cur)
            cur.execute("SET @mill_allow_retired_rename = 1")
            try:
                renamed = _rename_name_collisions(cur)
            finally:
                cur.execute("SET @mill_allow_retired_rename = NULL")
            _reshape_1163(cur)
            cur.execute("ALTER TABLE name AUTO_INCREMENT = 100")
        _install_name_type_triggers(cur)
        cn.commit()
        if already:
            return []
        return [f"migrate_1163:renamed({renamed})"]
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def ensure(cn) -> dict[str, Any]:
    """The one migration entry: tables, then routines, then the stamp of this
    pack's SQL digest (#614). mill install and mill install sql --apply call it."""
    res = _ensure_steps(cn)
    _stamp_sql(cn, sql_digest())
    _stamp_routines(cn)
    return res


def _ensure_steps(cn) -> dict[str, Any]:
    """0.4 book. Skip if activity exists (do not re-apply SPs). Else apply sql/."""
    import os

    cur = cn.cursor()
    applied: list[str] = []
    try:
        wipe = (os.environ.get("MILL_RECORDS_WIPE") or "").strip() == "1"
        if _table_exists(cur, "activity") and not wipe:
            cur.close()
            # #818: read before any step. A book whose routines are not this
            # pack's (another pack, or a run killed mid-reload) gets the full reload.
            current = bool(sql_state(cn).get("ok"))
            # 0.7.0 roster first: later steps name roster_id and the roster type.
            applied.extend(apply_roster_070(cn))
            # Column before the procedure refresh, so mill_label_select can read l.ord.
            applied.extend(_ensure_label_ord(cn))
            # card 1153: label.updated before the refresh too (mill_label_put sets it on a re-rank).
            applied.extend(_ensure_label_updated(cn))
            # Column before the procedure refresh: mill_join_wake_* name it (#618).
            applied.extend(_ensure_join_endpoint_key(cn))
            applied.extend(_ensure_join_wake_on(cn))
            # #818 D1: before the routine reload (mill_mail_to_copied, mill_doing_now read it).
            applied.extend(_ensure_mail_to_asked(cn))
            # #818 D2: before the routine reload (mill_todo_update, mill_doing_now read it).
            applied.extend(_ensure_todo_claimed_at(cn))
            # #867: before the routine reload (mill_todo_select, cmd_pass read them).
            applied.extend(_ensure_todo_done_when(cn))
            # #818 after the join column steps (the seat copy reads them).
            did_818 = apply_doing_818(cn)
            applied.extend(did_818)
            applied.extend(_ensure_seat_wake_on_default(cn, moved_818=bool(did_818)))
            # #822 columns before the routine reload (mill_doing_put names waiting_why).
            applied.extend(_ensure_doing_waiting(cn))
            if did_818 or not current:
                applied.extend(reload_routines(cn))
            applied.extend(_ensure_score_series(cn))
            applied.extend(_ensure_payload_fk_drop(cn))
            applied.extend(_ensure_watcher_hint(cn))
            applied.extend(_ensure_fn_refresh(cn))
            applied.extend(_ensure_sp_full(cn))
            applied.extend(_ensure_mail_sp(cn))
            applied.extend(_ensure_push_expired(cn))
            applied.extend(_ensure_activity_soft_delete(cn))
            applied.extend(_ensure_name_trashed(cn))
            applied.extend(_ensure_act_rename(cn))
            applied.extend(_ensure_fk_rules(cn))
            applied.extend(_ensure_join_token_hash(cn))
            applied.extend(_ensure_tree_read(cn))
            applied.extend(_ensure_mail_to_unread(cn))
            applied.extend(_ensure_activity_roster(cn))
            # After the routine reload: retire goes through mill_score_delete.
            applied.extend(_ensure_score_one_name(cn))
            # 0.8.0 schema last: every step above leaves a main-shape (0.7.18) book.
            applied.extend(apply_080(cn))
            # card 1022: wake + transition + System desk 0 (after 0.8.0 shape).
            did_1022 = apply_transition_1022(cn)
            applied.extend(did_1022)
            applied.extend(apply_task_970(cn))
            # card 1133: after 970 so replace follows task in both act enums, as in tables.sql.
            applied.extend(apply_history_1133(cn))
            # card 1098: transition.n (after 1022 table exists)
            applied.extend(_ensure_transition_n(cn))
            applied.extend(_ensure_wake_retry_edge(cn))
            applied.extend(_ensure_wake_lease_edges(cn))
            # card 1113: wake.id is AUTO_INCREMENT, payload first (after the 1022 wake table).
            applied.extend(_ensure_wake_auto_id(cn))
            # card 1171: after the 1022 wake table exists.
            applied.extend(_ensure_wake_cause_id_idx(cn))
            if did_1022:
                applied.extend(reload_routines(cn))
            applied.extend(apply_1163(cn))
            applied.extend(apply_1200(cn))
            # card 1207: after the routine reload (mill_doing_anchor, MILL_FX_META) and the 1022 edges.
            applied.extend(apply_1207(cn))
            applied.extend(apply_1212(cn))
            applied.extend(apply_1214(cn))
            return {"version": 1, "applied": applied, "book": "activity"}
        rec = apply_records(cn, wipe=wipe)
        applied.extend(rec.get("applied") or [])
        cn.commit()
        return {"version": 1, "applied": applied, "book": "activity"}
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()
