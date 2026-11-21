"""Refresh a dev host book from a logical dump of another office book (card 1266).

Dev pipeline tooling, not a product feature. See docs/dev/CHECKS-AND-TOOLS.md
("Dev host book import (card 1200)").

  python tools/dev_host_import.py --dump PATH --new-database NAME
  python tools/dev_host_import.py --dump PATH --new-database NAME --dry-run

Steps, in order, stopping on the first failure:

1. Back up the current book to a dump file. Leave that database in place
   as the rollback.
2. Create a new empty database (letters, digits, underscore only) and load
   the dump into it.
3. Pre-check: strings that are a desk on one book and another type on the
   other; desks only on the current book (their bearers will not carry over).
4. Connected to the current book, CALL mill_import_bearer_salts. Refuse if
   the session database is the upload.
5. Check the account has EXECUTE on the new database.
6. Point the host config database key at the new database (keep a copy of
   the old config).
7. From the release checkout, run mill install sql --apply against the new
   database.
8. Print the restart step and the rollback step. Do not restart the wall.

--dry-run prints the plan and pre-check only. The script never prints
passwords, bearer tokens, or hashes.
"""
from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

IDENT = re.compile(r"^[A-Za-z0-9_]+$")
# token_hash is CHAR(64) hex; never print it. git shas are 40 chars.
_HASH64 = re.compile(r"(?i)(?<![0-9A-F])[0-9A-F]{64}(?![0-9A-F])")
_DROP_DB = re.compile(r"(?i)\bDROP\s+DATABASE\b")
_CREATE_DB = re.compile(r"(?i)^\s*(?:/\*[^*]*\*/\s*)*CREATE\s+DATABASE\b")
_USE_DB = re.compile(r"(?i)^\s*(?:/\*[^*]*\*/\s*)*USE\b")


class DevHostImportError(Exception):
    """Stop the import. The message is safe to print (no secrets)."""


def require_ident(name: str, *, what: str = "database name") -> str:
    raw = (name or "").strip()
    if not raw or not IDENT.fullmatch(raw):
        raise DevHostImportError(f"{what} is not a plain identifier")
    return raw


def refuse_if_session_is_upload(session_db: str | None, upload_db: str) -> None:
    """The salt procedure must run on the current book, not the upload."""
    upload = require_ident(upload_db, what="upload database name")
    session = (session_db or "").strip()
    if not session:
        raise DevHostImportError("session has no database; connect to the current book")
    if session.lower() == upload.lower():
        raise DevHostImportError(
            "session database is the upload; call mill_import_bearer_salts "
            "from the current book"
        )


def redact_output(text: str) -> str:
    """Strip hashes and known secret shapes before printing tool output."""
    if not text:
        return text
    from agent_coord.server.redact import redact_secrets

    out = redact_secrets(text)
    return _HASH64.sub("[hash]", out)


def _print(text: str, file: TextIO | None = None) -> None:
    dest = file or sys.stdout
    print(redact_output(text), file=dest)


def sql_ident(name: str) -> str:
    return "`" + require_ident(name, what="identifier").replace("`", "``") + "`"


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S.%f") + "'"
    if isinstance(value, date) and not isinstance(value, datetime):
        return "'" + value.isoformat() + "'"
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        sign = "-" if total < 0 else ""
        total = abs(total)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"'{sign}{hours}:{minutes:02d}:{seconds:02d}'"
    if isinstance(value, (bytes, bytearray, memoryview)):
        blob = bytes(value)
        return "0x" + blob.hex() if blob else "X''"
    text = value if isinstance(value, str) else str(value)
    escaped = (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\x00", "\\0")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x1a", "\\Z")
    )
    return "'" + escaped + "'"


def rewrite_dump(text: str, new_db: str) -> str:
    """Point CREATE DATABASE / USE at new_db. Drop DROP DATABASE (never run it)."""
    require_ident(new_db, what="upload database name")
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            out.append(line)
            continue
        if _DROP_DB.search(stripped):
            continue
        if _CREATE_DB.match(stripped):
            out.append(
                f"CREATE DATABASE IF NOT EXISTS `{new_db}` "
                "DEFAULT CHARACTER SET utf8mb4 "
                "DEFAULT COLLATE utf8mb4_0900_ai_ci;\n"
            )
            continue
        if _USE_DB.match(stripped):
            out.append(f"USE `{new_db}`;\n")
            continue
        out.append(line)
    return "".join(out)


def classify_precheck(
    current: Iterable[tuple[str, str]],
    upload: Iterable[tuple[str, str]],
) -> dict[str, list]:
    """Compare name strings across two books. Values are display names only."""

    def bucket(rows: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for name, typ in rows:
            n, t = str(name), str(typ)
            out.setdefault(n, set()).add(t)
        return out

    cur = bucket(current)
    up = bucket(upload)
    conflicts: list[dict[str, str]] = []
    for name in sorted(set(cur) & set(up)):
        c_types, u_types = cur[name], up[name]
        if "desk" in c_types and u_types - {"desk"}:
            for typ in sorted(u_types - {"desk"}):
                conflicts.append({"name": name, "current": "desk", "upload": typ})
        if "desk" in u_types and c_types - {"desk"}:
            for typ in sorted(c_types - {"desk"}):
                conflicts.append({"name": name, "current": typ, "upload": "desk"})
    current_only = sorted(
        name
        for name, types in cur.items()
        if "desk" in types and "desk" not in up.get(name, set())
    )
    return {"type_conflicts": conflicts, "current_only_desks": current_only}


def connect_kwargs(config_path: Path | None) -> dict[str, Any]:
    from agent_coord.config import mysql_kwargs

    kw = dict(mysql_kwargs(config_path))
    kw.pop("database", None)
    kw["connection_timeout"] = 10
    return kw


def connect(kw: dict[str, Any], database: str | None = None, *, autocommit: bool = False):
    import mysql.connector

    args = dict(kw)
    args["autocommit"] = autocommit
    if database is not None:
        args["database"] = require_ident(database)
    return mysql.connector.connect(**args)


def current_database(config_path: Path, override: str | None = None) -> str:
    if override:
        return require_ident(override, what="current database name")
    from agent_coord.config import load_file, settings

    data = load_file(config_path)
    name = str(data.get("database") or "").strip()
    if not name:
        name = str(settings(config_path).get("database") or "").strip()
    if not name:
        raise DevHostImportError("host config has no database key")
    return require_ident(name, what="current database name")


def session_database(cn) -> str:
    cur = cn.cursor()
    try:
        cur.execute("SELECT DATABASE()")
        row = cur.fetchone()
        return "" if not row or row[0] is None else str(row[0])
    finally:
        cur.close()


def _table_names(cn) -> list[str]:
    cur = cn.cursor()
    try:
        cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
        return [str(r[0]) for r in cur.fetchall()]
    finally:
        cur.close()


def _strip_definer(sql: str) -> str:
    return re.sub(r"\s*DEFINER=`[^`]+`@`[^`]+`", "", sql)


def _col_ident(name: str) -> str:
    raw = str(name)
    if IDENT.fullmatch(raw):
        return "`" + raw + "`"
    return "`" + raw.replace("`", "``") + "`"


def dump_database(cn, path: Path, database: str) -> None:
    """Write a logical dump. Values stay in the file; nothing is printed."""
    require_ident(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    cur = cn.cursor()
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("-- mill dev_host_import backup\n")
            fh.write("SET NAMES utf8mb4;\n")
            fh.write("SET FOREIGN_KEY_CHECKS=0;\n")
            fh.write("SET UNIQUE_CHECKS=0;\n")
            fh.write("SET sql_mode='NO_AUTO_VALUE_ON_ZERO';\n")
            fh.write(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "DEFAULT CHARACTER SET utf8mb4 "
                "DEFAULT COLLATE utf8mb4_0900_ai_ci;\n"
            )
            fh.write(f"USE `{database}`;\n")
            for table in _table_names(cn):
                cur.execute("SHOW CREATE TABLE " + _col_ident(table))
                row = cur.fetchone()
                if not row:
                    continue
                create = _strip_definer(str(row[1]))
                fh.write("DROP TABLE IF EXISTS " + _col_ident(table) + ";\n")
                fh.write(create.rstrip(";") + ";\n")
                cur.execute("SELECT * FROM " + _col_ident(table))
                cols = [d[0] for d in cur.description]
                col_sql = ", ".join(_col_ident(c) for c in cols)
                batch: list[str] = []

                def flush() -> None:
                    if not batch:
                        return
                    fh.write(
                        "INSERT INTO "
                        + _col_ident(table)
                        + " ("
                        + col_sql
                        + ") VALUES "
                        + ", ".join(batch)
                        + ";\n"
                    )
                    batch.clear()

                for rec in cur:
                    batch.append("(" + ", ".join(sql_literal(v) for v in rec) + ")")
                    if len(batch) >= 100:
                        flush()
                flush()
            cur.execute(
                "SELECT ROUTINE_TYPE, ROUTINE_NAME FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = DATABASE() ORDER BY ROUTINE_TYPE, ROUTINE_NAME"
            )
            routines = list(cur.fetchall())
            for typ, name in routines:
                kind = str(typ).upper()
                ident = _col_ident(str(name))
                if kind == "FUNCTION":
                    cur.execute("SHOW CREATE FUNCTION " + ident)
                    key = "Create Function"
                else:
                    cur.execute("SHOW CREATE PROCEDURE " + ident)
                    key = "Create Procedure"
                row = cur.fetchone()
                if not row:
                    continue
                desc = [d[0] for d in cur.description]
                body = row[desc.index(key)] if key in desc else row[2]
                fh.write("DELIMITER //\n")
                fh.write("DROP " + kind + " IF EXISTS " + ident + "//\n")
                fh.write(_strip_definer(str(body)).rstrip(";") + "//\n")
                fh.write("DELIMITER ;\n")
            cur.execute("SHOW TRIGGERS")
            triggers = list(cur.fetchall())
            if triggers:
                tdesc = [d[0] for d in cur.description]
                name_i = tdesc.index("Trigger") if "Trigger" in tdesc else 0
                for rec in triggers:
                    tname = rec[name_i]
                    cur.execute("SHOW CREATE TRIGGER " + _col_ident(str(tname)))
                    crow = cur.fetchone()
                    if not crow:
                        continue
                    cdesc = [d[0] for d in cur.description]
                    key = "SQL Original Statement"
                    body = crow[cdesc.index(key)] if key in cdesc else crow[-1]
                    fh.write("DELIMITER //\n")
                    fh.write(_strip_definer(str(body)).rstrip(";") + "//\n")
                    fh.write("DELIMITER ;\n")
        tmp.replace(path)
        os.chmod(path, 0o600)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    finally:
        cur.close()


def load_dump(cn, path: Path, new_db: str) -> None:
    """Create new_db if needed and load path into it. Never runs DROP DATABASE."""
    from agent_coord.install.migrate import split_script

    require_ident(new_db, what="upload database name")
    raw = path.read_text(encoding="utf-8")
    text = rewrite_dump(raw, new_db)
    cur = cn.cursor()
    try:
        cur.execute(
            "CREATE DATABASE IF NOT EXISTS "
            + sql_ident(new_db)
            + " DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
        )
        cur.execute("USE " + sql_ident(new_db))
        cur.execute("SET NAMES utf8mb4")
        cur.execute("SET FOREIGN_KEY_CHECKS=0")
        cur.execute("SET UNIQUE_CHECKS=0")
        cur.execute("SET sql_mode='NO_AUTO_VALUE_ON_ZERO'")
        for stmt in split_script(text):
            s = stmt.strip()
            if not s or _DROP_DB.search(s):
                continue
            cur.execute(s)
            if cur.with_rows:
                cur.fetchall()
        cur.execute("SET FOREIGN_KEY_CHECKS=1")
        cur.execute("SET UNIQUE_CHECKS=1")
    finally:
        cur.close()


def name_rows(cn, database: str) -> list[tuple[str, str]]:
    cur = cn.cursor()
    try:
        cur.execute("SELECT name, type FROM " + sql_ident(database) + ".name")
        return [(str(n), str(t)) for n, t in cur.fetchall()]
    finally:
        cur.close()


def _grantee_sql() -> str:
    # GRANTEE is 'user'@'host'; CURRENT_USER() is user@host.
    return "REPLACE(GRANTEE, CHAR(39), '') = CURRENT_USER()"


def account_has_execute(cn, schema: str) -> bool:
    require_ident(schema, what="upload database name")
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.USER_PRIVILEGES "
            "WHERE " + _grantee_sql() + " "
            "AND PRIVILEGE_TYPE IN ('EXECUTE', 'ALL', 'ALL PRIVILEGES') "
            "LIMIT 1"
        )
        if cur.fetchone():
            return True
        cur.execute(
            "SELECT 1 FROM information_schema.SCHEMA_PRIVILEGES "
            "WHERE " + _grantee_sql() + " "
            "AND TABLE_SCHEMA = %s "
            "AND PRIVILEGE_TYPE IN ('EXECUTE', 'ALL', 'ALL PRIVILEGES') "
            "LIMIT 1",
            (schema,),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


def import_bearer_salts(cn, upload_db: str) -> int:
    """CALL mill_import_bearer_salts from the current book. Returns matching desks."""
    upload = require_ident(upload_db, what="upload database name")
    refuse_if_session_is_upload(session_database(cn), upload)
    cur = cn.cursor()
    try:
        cur.execute("CALL mill_import_bearer_salts(%s)", (upload,))
        if cur.with_rows:
            cur.fetchall()
        while True:
            try:
                if not cur.nextset():
                    break
            except Exception:
                break
        cur.execute(
            "SELECT COUNT(*) FROM "
            + sql_ident(upload)
            + ".seat s JOIN "
            + sql_ident(upload)
            + ".name n ON n.id = s.desk_id AND n.type = 'desk' "
            "JOIN name ln ON ln.type = 'desk' AND ln.name = n.name "
            "JOIN seat ls ON ls.desk_id = ln.id "
            "WHERE ls.token_hash IS NOT NULL AND s.token_hash = ls.token_hash"
        )
        row = cur.fetchone()
        cn.commit()
        return int(row[0] if row else 0)
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def point_database_key(config_path: Path, new_db: str, backup_path: Path) -> None:
    """Copy the config, then set only the database key. Never prints the file."""
    require_ident(new_db, what="upload database name")
    if not config_path.is_file():
        raise DevHostImportError("host config file is missing")
    text = config_path.read_text(encoding="utf-8")
    mode = stat.S_IMODE(config_path.stat().st_mode)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(text, encoding="utf-8")
    os.chmod(backup_path, mode or 0o600)
    lines = text.splitlines(True)
    if not lines:
        lines = ["\n"]
    ended_nl = lines[-1].endswith("\n")
    found = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _raw = stripped.split("=", 1)
            if key.strip() == "database":
                nl = "\n" if line.endswith("\n") else ""
                out.append(f'database = "{new_db}"{nl}')
                found = True
                continue
        out.append(line)
    if not found:
        prefix = "" if ended_nl or not out else "\n"
        out.append(f'{prefix}database = "{new_db}"\n')
    config_path.write_text("".join(out), encoding="utf-8")
    os.chmod(config_path, mode or 0o600)


def run_apply(checkout: Path, config_path: Path) -> str:
    """Run mill install sql --apply from the release checkout with this config."""
    if not checkout.is_dir():
        raise DevHostImportError("release checkout is missing")
    env = os.environ.copy()
    env.pop("AGENT_COORD_DATABASE", None)
    env["AGENT_COORD_CONFIG"] = str(config_path.resolve())
    py_path = str(checkout.resolve())
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = py_path + os.pathsep + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = py_path
    cmd = [sys.executable, "-m", "agent_coord", "install", "sql", "--apply"]
    proc = subprocess.run(
        cmd,
        cwd=str(checkout.resolve()),
        env=env,
        capture_output=True,
        text=True,
    )
    stdout = redact_output(proc.stdout or "")
    stderr = redact_output(proc.stderr or "")
    if proc.returncode != 0:
        detail = (stdout + "\n" + stderr).strip() or f"exit {proc.returncode}"
        raise DevHostImportError(
            "mill install sql --apply failed: " + detail.splitlines()[-1][:200]
        )
    return stdout.strip()


def _format_precheck(report: dict[str, list]) -> str:
    lines = ["pre-check:"]
    conflicts = report.get("type_conflicts") or []
    if conflicts:
        lines.append("  type_conflicts:")
        for row in conflicts:
            lines.append(
                f"    - {row['name']}: current {row['current']}, upload {row['upload']}"
            )
    else:
        lines.append("  type_conflicts: none")
    only = report.get("current_only_desks") or []
    if only:
        lines.append("  current_only_desks:")
        for name in only:
            lines.append(f"    - {name}")
    else:
        lines.append("  current_only_desks: none")
    return "\n".join(lines)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def database_exists(cn, name: str) -> bool:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
            (name,),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


def drop_database(cn, name: str) -> None:
    cur = cn.cursor()
    try:
        cur.execute("DROP DATABASE IF EXISTS " + sql_ident(name))
    finally:
        cur.close()


def run(args: argparse.Namespace) -> int:
    dump_path = Path(args.dump)
    if not dump_path.is_file():
        raise DevHostImportError("dump file is missing")
    new_db = require_ident(args.new_database, what="upload database name")
    if args.config:
        config_path = Path(args.config)
    else:
        from agent_coord.config import config_path as default_config

        config_path = default_config()
    config_path = config_path.resolve()
    current_db = current_database(config_path, args.current_database or None)
    if current_db.lower() == new_db.lower():
        raise DevHostImportError(
            "new database must differ from the current book; "
            "the current book is the rollback"
        )
    checkout = Path(args.checkout) if args.checkout else ROOT
    checkout = checkout.resolve()
    stamp = _stamp()
    backup_path = Path(args.backup) if args.backup else Path(f"{current_db}_{stamp}.sql")
    backup_path = backup_path.resolve()
    if args.config_backup:
        config_backup = Path(args.config_backup)
    else:
        config_backup = Path(str(config_path) + ".bak-" + stamp)
    config_backup = config_backup.resolve()

    plan = [
        "plan:",
        f"  current_database: {current_db}",
        f"  new_database: {new_db}",
        f"  dump: {dump_path}",
        f"  backup: {backup_path}",
        f"  config: {config_path}",
        f"  config_backup: {config_backup}",
        f"  checkout: {checkout}",
        "  apply: mill install sql --apply (from the checkout, after the config "
        "points at the new database)",
        f"  dry-run: {'true' if args.dry_run else 'false'}",
    ]
    _print("\n".join(plan))

    kw = connect_kwargs(config_path)
    admin = connect(kw, autocommit=True)
    created_upload = False
    try:
        if not database_exists(admin, current_db):
            raise DevHostImportError("current database is missing")
        if database_exists(admin, new_db):
            raise DevHostImportError("new database already exists")
        current = connect(kw, current_db)
        try:
            if not args.dry_run:
                dump_database(current, backup_path, current_db)
                _print(f"backup: wrote {backup_path}")
            load_dump(admin, dump_path, new_db)
            created_upload = True
            report = classify_precheck(
                name_rows(admin, current_db), name_rows(admin, new_db)
            )
            _print(_format_precheck(report))
            has_exec = account_has_execute(admin, new_db)
            _print("  execute: yes" if has_exec else "  execute: no")
            if not has_exec:
                raise DevHostImportError(
                    "account needs EXECUTE on the upload database"
                )
            if args.dry_run:
                drop_database(admin, new_db)
                created_upload = False
                _print(
                    "dry-run: no backup, no salt copy, no config change, no apply; "
                    "temporary upload database dropped."
                )
                _print(
                    "restart (when you run for real): Restart the wall so it opens "
                    f"the new database ({new_db}). This script does not restart it."
                )
                _print(
                    "rollback (when you run for real): Point database in the host "
                    f"config back to {current_db} and restart the wall. {current_db} "
                    "stays in place as the rollback."
                )
                return 0
            # Fresh session: the backup and the upload load may have left
            # this connection holding metadata from before the new database
            # existed (MySQL 1412 on the prepared CALL).
            current.close()
            current = connect(kw, current_db)
            matched = import_bearer_salts(current, new_db)
            _print(f"imported_salts: {matched} matching desks")
            point_database_key(config_path, new_db, config_backup)
            _print(f"config: pointed at {new_db} (copy at {config_backup})")
            run_apply(checkout, config_path)
            _print("apply: ok")
            _print(
                f"restart: Restart the wall so it opens the new database ({new_db}). "
                "This script does not restart it."
            )
            _print(
                f"rollback: Point database in the host config back to {current_db} "
                f"(copy at {config_backup}) and restart the wall. {current_db} was "
                f"left in place. Leave {new_db} until the rollback is confirmed."
            )
            return 0
        finally:
            current.close()
    except Exception:
        if args.dry_run and created_upload:
            try:
                drop_database(admin, new_db)
            except Exception:
                pass
        raise
    finally:
        admin.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Refresh a dev host book from a logical dump of another office book."
        )
    )
    p.add_argument("--dump", required=True, help="logical dump of the cloud book")
    p.add_argument(
        "--new-database",
        required=True,
        help="new empty database to load into (letters, digits, underscore only)",
    )
    p.add_argument(
        "--config", default="", help="host config.toml (default: mill config path)"
    )
    p.add_argument(
        "--current-database", default="", help="override the current book name"
    )
    p.add_argument("--backup", default="", help="path to write the current-book backup")
    p.add_argument(
        "--config-backup", default="", help="path for the copy of the old config"
    )
    p.add_argument(
        "--checkout",
        default="",
        help="release checkout that runs mill install sql --apply (default: this repo)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and pre-check only; mutate nothing lasting",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except DevHostImportError as exc:
        _print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
