"""Compare the schema of two books: a fresh install and an upgraded one (card 840).

  book_shape.py FRESH_DB BOOK_DB

FRESH_DB is a database that `migrate.ensure` built from empty; BOOK_DB is the
book to check, such as a throwaway copy of an office dump after ensure. The
connection is the usual AGENT_COORD_* settings. Prints one JSON object: every
differing part (`drift`), and the parts not in KNOWN_LIVE_DRIFT
(`unexpected`). Exit 0 when nothing is unexpected, 1 otherwise. Reads the
information schema only: no rows, no writes.

The shape: tables (engine, collation), columns (type with enum values,
null, default, extra, collation; not their order), indexes, foreign keys
with their rules, triggers (timing, event, table, body hash) and routines
(body hash; the two stamp functions are left out).

`review(old, new)` lists what an upgrade dropped or narrowed (card 1068): the
columns gone and the column types made smaller. It is for a person's schema
review and decides nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

# The repo root, so the command runs from a checkout without the pack installed.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Drift seen on the cloud office book after ensure at 0.7.16. Reported, not
# dropped, in 0.7.17: removing it changes the data format (normalization batch).
KNOWN_LIVE_DRIFT = (
    "column doing.directory_sub",
    "column watcher.type",
    "fk tree.fk_tree_name",
    "trigger hold_ad_activity",
    "trigger mail_ad_activity",
    "trigger score_ad_activity",
    "trigger todo_ad_activity",
)
_STAMPS = ("MILL_SQL_STAMP", "MILL_ROUTINES_STAMP")


def _s(x: Any) -> str:
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8")
    return "" if x is None else str(x)


def _h(text: Any) -> str:
    return hashlib.sha256(_s(text).encode("utf-8")).hexdigest()[:12]


_QUERIES = (
    (
        "SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'",
        lambda r: (f"table {_s(r[0])}", f"{_s(r[1])} {_s(r[2])}"),
    ),
    (
        "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA,"
        " COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()",
        lambda r: (
            f"column {_s(r[0])}.{_s(r[1])}",
            f"{_s(r[2])} null={_s(r[3])} default={_s(r[4])} extra={_s(r[5])} coll={_s(r[6])}",
        ),
    ),
    (
        "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE,"
        " GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX)"
        " FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() GROUP BY 1, 2, 3",
        lambda r: (f"index {_s(r[0])}.{_s(r[1])}", f"unique={1 - int(r[2])} ({_s(r[3])})"),
    ),
    (
        "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME,"
        " GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION), k.REFERENCED_TABLE_NAME,"
        " GROUP_CONCAT(k.REFERENCED_COLUMN_NAME ORDER BY k.ORDINAL_POSITION),"
        " r.UPDATE_RULE, r.DELETE_RULE"
        " FROM information_schema.KEY_COLUMN_USAGE k"
        " JOIN information_schema.REFERENTIAL_CONSTRAINTS r"
        " ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME"
        " AND r.TABLE_NAME = k.TABLE_NAME"
        " WHERE k.TABLE_SCHEMA = DATABASE() GROUP BY 1, 2, 4, 6, 7",
        lambda r: (
            f"fk {_s(r[0])}.{_s(r[1])}",
            f"({_s(r[2])}) -> {_s(r[3])}({_s(r[4])}) update={_s(r[5])} delete={_s(r[6])}",
        ),
    ),
    (
        "SELECT TRIGGER_NAME, EVENT_OBJECT_TABLE, ACTION_TIMING, EVENT_MANIPULATION,"
        " ACTION_STATEMENT FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()",
        lambda r: (f"trigger {_s(r[0])}", f"{_s(r[2])} {_s(r[3])} ON {_s(r[1])} body={_h(r[4])}"),
    ),
    (
        "SELECT ROUTINE_TYPE, ROUTINE_NAME, ROUTINE_DEFINITION FROM information_schema.ROUTINES"
        f" WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_NAME NOT IN {_STAMPS!r}",
        lambda r: (f"routine {_s(r[1]).lower()}", f"{_s(r[0])} body={_h(r[2])}"),
    ),
)


def shape(cn) -> dict[str, str]:
    """One line per schema part, keyed `KIND NAME`."""
    out: dict[str, str] = {}
    cur = cn.cursor()
    try:
        for sql, row in _QUERIES:
            cur.execute(sql)
            for r in cur.fetchall():
                k, v = row(r)
                out[k] = v
    finally:
        cur.close()
    return out


def diff(fresh: dict[str, str], book: dict[str, str]) -> list[str]:
    """`KEY: fresh=... book=...` for every part that differs, sorted by key."""
    return [
        f"{k}: fresh={fresh.get(k)!r} book={book.get(k)!r}"
        for k in sorted(set(fresh) | set(book))
        if fresh.get(k) != book.get(k)
    ]


_INT = ("tinyint", "smallint", "mediumint", "int", "bigint")
_TEXT = ("tinytext", "text", "mediumtext", "longtext")
_BLOB = ("tinyblob", "blob", "mediumblob", "longblob")
_TYPE = re.compile(r"^(\w+)(?:\((.*)\))?(.*)$")


def _values(args: str | None) -> set[str]:
    return set(re.findall(r"'((?:[^']|'')*)'", args or ""))


def _col_type(value: str) -> str:
    return value.split(" null=", 1)[0]


def _narrower(old: str, new: str) -> bool | None:
    """True when NEW holds less than OLD, False when not, None when the two
    types are not on one scale (a person reads the pair)."""
    mo, mn = _TYPE.match(old), _TYPE.match(new)
    if not (mo and mn):
        return None
    (bo, ao, to), (bn, an, tn) = mo.groups(), mn.groups()
    if bo in ("enum", "set") and bo == bn:
        return not _values(ao) <= _values(an)
    for scale in (_INT, _TEXT, _BLOB):
        if bo in scale and bn in scale:
            return scale.index(bn) < scale.index(bo) or ("unsigned" in to) != ("unsigned" in tn)
    if bo in _TEXT and bn in ("char", "varchar"):
        return True
    if bo == bn and ao and an:
        try:
            po, pn = [int(x) for x in ao.split(",")], [int(x) for x in an.split(",")]
        except ValueError:
            return None
        return any(n < o for o, n in zip(po, pn))
    return None if bo != bn else False


def review(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """What going from OLD to NEW dropped or narrowed, for a person's review:
    `dropped` columns, `narrowed` types (`KEY: old -> new`), and `changed`
    types this cannot rank."""
    out: dict[str, list[str]] = {"dropped": [], "narrowed": [], "changed": []}
    for k in sorted(old):
        if not k.startswith("column "):
            continue
        if k not in new:
            out["dropped"].append(k)
            continue
        a, b = _col_type(old[k]), _col_type(new[k])
        if a == b:
            continue
        verdict = _narrower(a, b)
        if verdict is not False:
            out["narrowed" if verdict else "changed"].append(f"{k}: {a} -> {b}")
    return out


def drift_keys(lines: list[str]) -> list[str]:
    return [line.split(": ", 1)[0] for line in lines]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    from agent_coord.server.records import connect

    shapes = []
    for name in argv:
        cn = connect(name)
        try:
            shapes.append(shape(cn))
        finally:
            cn.close()
    keys = drift_keys(diff(*shapes))
    unexpected = [k for k in keys if k not in KNOWN_LIVE_DRIFT]
    print(json.dumps({"ok": not unexpected, "drift": keys, "unexpected": unexpected}))
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
