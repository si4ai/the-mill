"""Beta book (roster = room) install, migration and rollback (L1).

Kept apart from migrate.py on purpose: migrate.sql_digest() hashes migrate.py, so touching it would restamp every
0.7 office. Nothing here runs from `mill install sql` yet; the beta files are not in apply_order.txt. The server
switch (L2) wires this in at ship.

  install(cn)                     beta tables, the SP version stamp, the routines, one sp_deploy row (current database)
  migrate(cn, src, dst)           copy a 0.7 book into a new beta database; the 0.7 book is only read
  rollback(cn, src, dst)          copy a beta book back into a new 0.7 database (0.7 tables + routines, then the data)
  grant_execute(cn, db, user, host)  the app user may EXECUTE the public routines and nothing else
  set_read_committed(cn)          READ COMMITTED for the server (PERSIST, else GLOBAL); the app also sets it per session
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from agent_coord.install import migrate as m07

_IDENT = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_HOST = re.compile(r"^[A-Za-z0-9_.%:-]{1,255}$")
_PUBLIC = re.compile(r"^(cmd_|uc_)|^(mill_span|mill_hello|mill_sp_version)$")
_TRIGGER = re.compile(r"^\s*CREATE\s+TRIGGER\s+([A-Za-z0-9_]+)", re.I)
# triggers that guard live writes but would refuse 0.7 history (a former member's letters, a deep plan copied in order)
_HISTORY_TRIGGERS = ("letter_sender_current", "card_no_cycle")


def beta_dir() -> Path:
    """The L1 fold's SQL files: a draft under docs/requirements/beta/fold/, beside the #199 proposal and
    not in the pack (F160, F165)."""
    return Path(__file__).resolve().parents[2] / "docs" / "requirements" / "beta" / "fold"


def _sql(name: str) -> str:
    return (beta_dir() / name).read_text(encoding="utf-8-sig")


def _ident(name: str) -> str:
    if not _IDENT.fullmatch(name or ""):
        raise ValueError(f"bad identifier: {name!r}")
    return name


def sp_version() -> str:
    """'sp-' + sha256(beta_sp.sql)[:12], line endings ignored. Clients send it in mill_hello."""
    blob = (beta_dir() / "beta_sp.sql").read_bytes().replace(b"\r\n", b"\n")
    return "sp-" + hashlib.sha256(blob).hexdigest()[:12]


def _run(cur, blob: str) -> int:
    n = 0
    for stmt in m07.split_script(blob):
        try:
            cur.execute(stmt)
        except Exception as exc:
            raise RuntimeError(f"{exc} in: {stmt[:160]}") from exc
        if cur.with_rows:
            cur.fetchall()
        n += 1
    return n


def _triggers(names: tuple[str, ...]) -> str:
    out = []
    for stmt in m07.split_script(_sql("beta_ddl.sql")):
        hit = _TRIGGER.match(stmt)
        if hit and hit.group(1) in names:
            out.append(stmt)
    if len(out) != len(names):
        raise RuntimeError("beta_ddl.sql is missing a history trigger")
    return "DELIMITER //\n" + "\n//\n".join(out) + "\n//\nDELIMITER ;\n"


def _stamp(cur) -> str:
    version = sp_version()
    if not re.fullmatch(r"sp-[0-9a-f]{12}", version):
        raise ValueError("sp version is sp- + 12 hex")
    cur.execute("DROP FUNCTION IF EXISTS mill_sp_version")
    # the value is checked hex above; a routine body cannot take a bound parameter
    cur.execute("CREATE FUNCTION mill_sp_version() RETURNS CHAR(15) CHARSET ascii DETERMINISTIC NO SQL RETURN '" + version + "'")
    return version


def _routines(cur, *, by: str = "install") -> str:
    try:
        cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
    except Exception:
        pass
    version = _stamp(cur)
    _run(cur, _sql("beta_sp.sql"))
    cur.execute("INSERT INTO sp_deploy (version, by_user) VALUES (%s, %s)", (version, by[:64]))
    return version


def install(cn) -> dict[str, Any]:
    """Fresh beta book in the current (empty) database."""
    cur = cn.cursor(buffered=True)
    try:
        t0 = time.monotonic()
        _run(cur, _sql("beta_ddl.sql"))
        version = _routines(cur)
        cn.commit()
        return {"sp_version": version, "seconds": round(time.monotonic() - t0, 3)}
    finally:
        cur.close()


def _fresh_db(cur, db: str) -> None:
    cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s", (db,))
    if cur.fetchone()[0]:
        raise RuntimeError(f"target database {db} exists; migrate copies into a new one")
    cur.execute("CREATE DATABASE " + _ident(db) + " CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    cur.execute("USE " + _ident(db))


def _has_column(cur, db: str, table: str, col: str) -> bool:
    cur.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = %s AND table_name = %s AND column_name = %s", (db, table, col))
    return bool(cur.fetchone()[0])


# facts a 0.7 book cannot hold; rollback reports how many it leaves behind
_ROLLBACK_LOSS = {
    "card status events beyond the current one": "SELECT (SELECT COUNT(*) FROM {s}.card_event) - (SELECT COUNT(*) FROM {s}.card)",
    "cards with done_when": "SELECT COUNT(*) FROM {s}.card WHERE done_when IS NOT NULL",
    "pass evidence": "SELECT COUNT(*) FROM {s}.card_event WHERE evidence IS NOT NULL",
    "votes (their letters stay)": "SELECT COUNT(*) FROM {s}.vote",
    "ballots": "SELECT COUNT(*) FROM {s}.ballot",
    "former members": "SELECT COUNT(*) FROM {s}.room_member WHERE left_at IS NOT NULL",
    "hold events beyond the current holder": "SELECT (SELECT COUNT(*) FROM {s}.hold_event) - (SELECT COUNT(*) FROM {s}.hold)",
    "card wakes": "SELECT COUNT(*) FROM {s}.push WHERE card_event_id IS NOT NULL",
}


def migrate(cn, src: str, dst: str) -> dict[str, Any]:
    """0.7 book `src` -> new beta book `dst`. Returns timing, repair counts and row counts."""
    src, dst = _ident(src), _ident(dst)
    cur = cn.cursor(buffered=True)
    try:
        t0 = time.monotonic()
        _fresh_db(cur, dst)
        _run(cur, _sql("beta_ddl.sql"))
        for name in _HISTORY_TRIGGERS:
            cur.execute("DROP TRIGGER " + name)
        sub = "x.directory_sub" if _has_column(cur, src, "doing", "directory_sub") else "NULL"
        _run(cur, _sql("beta_migrate.sql").replace("@SRC@", src).replace("@DOING_SUB@", sub))
        _run(cur, _triggers(_HISTORY_TRIGGERS))
        # new desks, rooms, tags and resources take ids above every 0.7 name id, so a rollback can keep the old ids
        cur.execute("SELECT IFNULL(MAX(id), 0) FROM " + src + ".name")
        cut = int(cur.fetchone()[0])
        for t in ("desk", "room", "tag", "resource"):
            cur.execute("ALTER TABLE " + t + " AUTO_INCREMENT = " + str(cut + 1))
        cur.execute("INSERT INTO mig_repair (what, n) VALUES ('cut: highest 0.7 name id', %s)", (cut,))
        version = _routines(cur, by="migrate")
        cn.commit()
        seconds = round(time.monotonic() - t0, 2)
        cur.execute("SELECT what, n FROM mig_repair WHERE n > 0 ORDER BY what")
        repairs = {w: int(n) for w, n in cur.fetchall()}
        rows = {}
        for t in ("desk", "room", "room_member", "letter", "letter_to", "card", "card_event", "focus", "hold", "doing", "score", "push", "activity"):
            cur.execute("SELECT COUNT(*) FROM " + t)
            rows[t] = int(cur.fetchone()[0])
        return {"src": src, "dst": dst, "seconds": seconds, "sp_version": version, "repairs": repairs, "rows": rows}
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def rollback(cn, src: str, dst: str) -> dict[str, Any]:
    """Beta book `src` -> new 0.7 book `dst` (0.7 tables and routines from this pack, then the data, then the stamps)."""
    src, dst = _ident(src), _ident(dst)
    cur = cn.cursor(buffered=True)
    try:
        t0 = time.monotonic()
        _fresh_db(cur, dst)
        cn.commit()
    finally:
        cur.close()
    m07.ensure(cn)
    cur = cn.cursor(buffered=True)
    try:
        cur.execute("USE " + dst)
        has_sub = _has_column(cur, dst, "doing", "directory_sub")
        lost = {}
        for what, q in _ROLLBACK_LOSS.items():
            cur.execute(q.format(s=src))
            lost[what] = int(cur.fetchone()[0])
        if not has_sub:
            cur.execute("SELECT COUNT(*) FROM " + src + ".doing WHERE directory_sub IS NOT NULL")
            lost["doing directory_sub (this pack's 0.7 tables lack it)"] = int(cur.fetchone()[0])
        blob = (_sql("beta_rollback.sql").replace("@SRC@", src)
                .replace("@DOING_SUB_COL@", ", directory_sub" if has_sub else "")
                .replace("@DOING_SUB_VAL@", ", d.directory_sub" if has_sub else ""))
        _run(cur, blob)
        cn.commit()
        return {"src": src, "dst": dst, "seconds": round(time.monotonic() - t0, 2), "lost": {k: v for k, v in lost.items() if v}}
    except Exception:
        cn.rollback()
        raise
    finally:
        cur.close()


def public_routines(cn, db: str) -> list[tuple[str, str]]:
    cur = cn.cursor()
    try:
        cur.execute("SELECT routine_type, routine_name FROM information_schema.routines WHERE routine_schema = %s ORDER BY 2", (_ident(db),))
        return [(t, n) for t, n in cur.fetchall() if _PUBLIC.search(n)]
    finally:
        cur.close()


def grant_execute(cn, db: str, user: str, host: str = "%") -> int:
    """EXECUTE on each public routine, nothing else (no table privilege). The account must exist; its password is
    never handled here. Returns the number of routines granted."""
    db, user = _ident(db), _ident(user)
    if not _HOST.fullmatch(host or ""):
        raise ValueError("bad host")
    cur = cn.cursor()
    n = 0
    try:
        for kind, name in public_routines(cn, db):
            cur.execute("GRANT EXECUTE ON " + kind + " " + db + "." + _ident(name) + " TO %s@%s", (user, host))
            n += 1
        return n
    finally:
        cur.close()


def set_read_committed(cn) -> str:
    """Server default isolation READ COMMITTED. 'persist' survives restarts; 'global' lasts until restart; 'session'
    means the account may not change the server and the app must SET it per connection (L2 does, always)."""
    cur = cn.cursor()
    try:
        for scope, stmt in (("persist", "SET PERSIST transaction_isolation = 'READ-COMMITTED'"),
                            ("global", "SET GLOBAL transaction_isolation = 'READ-COMMITTED'")):
            try:
                cur.execute(stmt)
                return scope
            except Exception:
                continue
        cur.execute("SET SESSION transaction_isolation = 'READ-COMMITTED'")
        return "session"
    finally:
        cur.close()
