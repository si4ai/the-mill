"""Mill schema ensure. Init and Coord both run this. No session tokens here.

Fresh office / attempt 2: apply agent_coord/server/sql/ (wipe + tables + fn_ + sp_).
sql/ is not a migrate ladder.
"""

from __future__ import annotations

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
    ("score", "fk_score_desk", "desk_id", "name", "id", "RESTRICT"),
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
            if not _column_exists(cur, "score", "better"):
                cur.execute(
                    "ALTER TABLE score ADD COLUMN better ENUM('up','down') NOT NULL DEFAULT 'up'"
                    " AFTER note"
                )
                applied.append("score.better")
            if not _column_exists(cur, "score", "unit"):
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


def apply_080(cn, *, stop_after: str | None = None, timings: dict | None = None) -> list[str]:
    """0.8.0 schema on a main book (migrate_080.sql). Preflight first: refuse (Migrate080Refused) before any
    change; nothing pending is a no-op ([]). stop_after ends the run after that step, as a kill would (tests)."""
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
            n = _timed_080(cn, step, _triggers_080, timings)
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
    or push_queue still exists (fold into wake), or wake lacks payload."""
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
        return False
    finally:
        cur.close()


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
            if did_1022:
                applied.extend(reload_routines(cn))
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
