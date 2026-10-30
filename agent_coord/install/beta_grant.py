"""Beta (card 868, F160): the EXECUTE-only app database user for the proposed 0.8 book.

Its own module so migrate.py, whose bytes are part of MILL_SQL_STAMP (sql_digest, #614), does not change
with the beta proposal. Not called by `mill install sql`; the beta book is a proposal under
docs/requirements/beta/.
"""
from __future__ import annotations

from agent_coord.install.migrate import _ident

# Beta (card 868): the app database user holds EXECUTE on the public routines and nothing else.
_BETA_PUBLIC = r"^(cmd_|uc_|sp_name_|sp_label_|mill_)"


def grant_app_user(cn, db: str, user: str, password: str, host: str = "%") -> list[str]:
    """Create or reset `user`@`host` with EXECUTE on the beta public routines of `db` only.

    No table privilege at all: every write and read goes through a procedure, so the guards in the
    procedures (trust, Admin, membership) cannot be skipped. `sp_admin_set` is host-only and `b_*`
    helpers are internal; neither is granted. Returns the routines granted.
    """
    cur = cn.cursor()
    try:
        cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, host, password))
        cur.execute("ALTER USER %s@%s IDENTIFIED BY %s", (user, host, password))
        cur.execute("REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@%s", (user, host))
        cur.execute(
            "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES "
            "WHERE ROUTINE_SCHEMA = %s AND ROUTINE_NAME REGEXP %s ORDER BY ROUTINE_NAME",
            (db, _BETA_PUBLIC),
        )
        rows = list(cur.fetchall())
        done = []
        for name, kind in rows:
            if str(name) == "sp_admin_set":
                continue
            cur.execute(f"GRANT EXECUTE ON {kind} {_ident(db)}.{_ident(str(name))} TO %s@%s", (user, host))
            done.append(str(name))
        cn.commit()
        return done
    finally:
        cur.close()
