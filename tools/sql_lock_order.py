"""Lock-order check for the mill stored procedures (card 1113).

Reads the pack SQL, no database. For every procedure it lists the row locks the
statements take, in order, with CALLs and MILL_NAME_* functions inlined:

- an INSERT, or an UPDATE that sets a foreign-key column, takes a shared (S)
  lock on the parent row's referenced index (InnoDB's FK check). The FKs and
  primary keys come from tables.sql.
- INSERT ... SELECT, a subquery in UPDATE or DELETE, and a routine's IF/ELSEIF
  condition or SET x = (SELECT ...) read with S locks (seen in
  performance_schema.data_locks); a plain SELECT ... INTO is a consistent read.
- SELECT ... FOR UPDATE, UPDATE and DELETE take an exclusive (X) lock on the
  rows they name.

A row is told apart by the expression that names it (v_desk, p_id, ...), with
CALL arguments put in for the callee's parameters. Two findings:

- upgrade: one procedure takes S on a row and later X on the same row and
  index record (same table, same key) without holding X first. Two sessions
  doing that on one row deadlock (1213): each holds S and waits for X. An S
  read under an X already held on its item (todo, mail, hold, score by id) or
  its plan (name row of tree.name_id) is covered.
- cycle: across procedures, table A then B in one and B then A in another,
  with conflicting modes at both tables (table level, so a hint).

Usage: python tools/sql_lock_order.py [--sql DIR] [--proc NAME] [--cycles]
Exit 1 when any procedure has an upgrade.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "agent_coord" / "server" / "sql"
ID = r"[A-Za-z_][A-Za-z0-9_]*"
UNKNOWN = "*"
NEW = "new:"


@dataclass(frozen=True)
class Fk:
    child: str
    cols: tuple[str, ...]
    parent: str
    pcols: tuple[str, ...]


@dataclass(frozen=True)
class Lock:
    mode: str  # "S" or "X"
    table: str
    key: str  # normalized expression naming the row, or UNKNOWN
    idx: str  # the index record: "PRIMARY" or "u:<cols>" (an FK check locks the referenced index)
    where: str  # proc:line of the statement that takes it
    why: str  # "fk child.col", "for update", "update", "delete"


@dataclass
class Proc:
    name: str
    params: list[str]
    body: str
    file: str
    line: int  # line of CREATE
    end: int
    is_fn: bool = False
    stmts: list[tuple[int, str]] = field(default_factory=list)


def strip_comments(text: str) -> str:
    out = []
    for ln in text.splitlines():
        i, q = 0, None
        while i < len(ln):
            ch = ln[i]
            if q:
                if ch == q:
                    q = None
            elif ch in "'\"":
                q = ch
            elif ln.startswith("--", i):
                ln = ln[:i]
                break
            i += 1
        out.append(ln)
    return "\n".join(out)


def split_top(s: str, sep: str = ",") -> list[str]:
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts]


def _paren(s: str, i: int) -> int:
    """Index just past the ')' matching the '(' at s[i]."""
    depth, q = 0, None
    for j in range(i, len(s)):
        ch = s[j]
        if q:
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(s)


def norm(expr: str) -> str:
    return re.sub(r"\s+", "", expr.strip()).lower()


def load_fks(sql: Path) -> list[Fk]:
    text = strip_comments((sql / "tables.sql").read_text(encoding="utf-8"))
    fks: list[Fk] = []
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(" + ID + r")`?\s*\(", text, re.I):
        body = text[m.end() - 1:_paren(text, m.end() - 1)]
        for f in re.finditer(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+`?(" + ID + r")`?\s*\(([^)]*)\)", body, re.I):
            fks.append(Fk(m.group(1).lower(), tuple(norm(c) for c in f.group(1).split(",")),
                          f.group(2).lower(), tuple(norm(c) for c in f.group(3).split(","))))
    for m in re.finditer(r"ALTER\s+TABLE\s+(" + ID + r")\s+ADD\s+CONSTRAINT\s+" + ID
                         + r"\s+FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(" + ID + r")\s*\(([^)]*)\)", text, re.I):
        fks.append(Fk(m.group(1).lower(), tuple(norm(c) for c in m.group(2).split(",")),
                      m.group(3).lower(), tuple(norm(c) for c in m.group(4).split(","))))
    return fks


def load_pks(sql: Path) -> dict[str, tuple[str, ...]]:
    text = strip_comments((sql / "tables.sql").read_text(encoding="utf-8"))
    pks: dict[str, tuple[str, ...]] = {}
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(" + ID + r")`?\s*\(", text, re.I):
        body = text[m.end() - 1:_paren(text, m.end() - 1)]
        pm = re.search(r"PRIMARY\s+KEY\s*\(([^)]*)\)", body, re.I)
        if pm:
            pks[m.group(1).lower()] = tuple(norm(c) for c in pm.group(1).split(","))
    return pks


def load_procs(sql: Path) -> dict[str, Proc]:
    procs: dict[str, Proc] = {}
    for path in sorted(sql.glob("*.sql")):
        if path.name.startswith("migrate_") or path.name in ("tables.sql", "wipe.sql"):
            continue
        raw = path.read_text(encoding="utf-8")
        text = strip_comments(raw)
        for m in re.finditer(r"CREATE\s+(PROCEDURE|FUNCTION)\s+`?(" + ID + r")`?\s*\(", text, re.I):
            p_end = _paren(text, m.end() - 1)
            params = []
            for p in split_top(text[m.end():p_end - 1]):
                toks = p.split()
                if toks and toks[0].upper() in ("IN", "OUT", "INOUT"):
                    toks = toks[1:]
                if toks:
                    params.append(toks[0].lower())
            end = text.find("END //", p_end)
            end = len(text) if end < 0 else end
            body_start = re.search(r"\bBEGIN\b", text[p_end:end], re.I)
            b0 = p_end + (body_start.end() if body_start else 0)
            name = m.group(2)
            proc = Proc(name, params, text[b0:end], path.name,
                        text.count("\n", 0, m.start()) + 1, text.count("\n", 0, end) + 1,
                        m.group(1).upper() == "FUNCTION")
            line0 = text.count("\n", 0, b0) + 1
            pos = 0
            for st in split_top(proc.body, ";"):
                idx = proc.body.find(st, pos) if st else -1
                ln = line0 + (proc.body.count("\n", 0, idx) if idx >= 0 else 0)
                if idx >= 0:
                    pos = idx + len(st)
                st = " ".join(st.split())
                # IF/ELSEIF/WHILE conditions read with shared locks inside a routine (seen in
                # performance_schema.data_locks); keep them as a READ step before the statement.
                while True:
                    cm = re.match(r"(?:IF|ELSEIF|WHILE)\b(.*?)\b(?:THEN|DO)\b\s*", st, re.I)
                    if cm:
                        proc.stmts.append((ln, "READ " + cm.group(1)))
                        st = st[cm.end():]
                        continue
                    nxt = _lead(st)
                    if nxt == st:
                        break
                    st = nxt
                if st:
                    proc.stmts.append((ln, st))
            procs[name.lower()] = proc  # a later file wins, as the apply order loads them
    return procs


_LEAD = re.compile(
    r"^(?:(?:IF|ELSEIF|WHILE)\b.*?\bTHEN\b|WHILE\b.*?\bDO\b|ELSE\b|BEGIN\b|END\s+(?:IF|WHILE|LOOP|REPEAT)\b|END\b|"
    + ID + r":\s*(?:BEGIN|LOOP|REPEAT|WHILE)?\b|LOOP\b|REPEAT\b|DECLARE\b[^;]*?\bHANDLER\s+FOR\b.*?\bBEGIN\b)\s*",
    re.I,
)


def _lead(st: str) -> str:
    """Drop control-flow words in front of a statement (IF x THEN, ELSE, BEGIN, END IF)."""
    while True:
        m = _LEAD.match(st)
        if not m or not m.group(0):
            return st
        st = st[m.end():]


def _assigned(st: str) -> list[str]:
    """Variables a statement writes: SET x = ..., SELECT ... INTO x, y."""
    out = []
    m = re.match(r"SET\s+(" + ID + r")\s*=", st, re.I)
    if m:
        out.append(m.group(1).lower())
    m = re.search(r"\bINTO\s+((?:" + ID + r"\s*,\s*)*" + ID + r")\s+FROM\b", st, re.I)
    if m and st.upper().startswith("SELECT"):
        out += [v.strip().lower() for v in m.group(1).split(",")]
    return out


def _where_key(where: str, alias: str | None, col: str) -> str:
    """The row a WHERE names: the key column's value, else the first `col = value` (as col=value)."""
    pat = r"(?:\b" + re.escape(alias) + r"\.|(?<![.\w]))" if alias else r"(?<![.\w])"
    val = r"\s*=\s*([^\s=()]+(?:\([^)]*\))?)"
    m = re.search(pat + re.escape(col) + val, where, re.I)
    if m:
        return norm(m.group(1))
    m = re.search(pat + r"(" + ID + r")" + val, where, re.I)
    if m and not re.fullmatch(r"'.*'|\d+", m.group(2)):
        return f"{m.group(1).lower()}={norm(m.group(2))}"
    return UNKNOWN


class Analyzer:
    def __init__(self, sql: Path = SQL):
        self.fks = load_fks(sql)
        self.pks = load_pks(sql)
        self.procs = load_procs(sql)
        self.parents = {f.parent for f in self.fks}
        self.keycol: dict[str, str] = {}
        for f in self.fks:
            self.keycol.setdefault(f.parent, f.pcols[0] if f.pcols[0] != "type" or len(f.pcols) == 1 else f.pcols[1])
        self._memo: dict[str, list[Lock]] = {}
        self._outs: dict[str, dict[str, str]] = {}

    def key_col(self, table: str) -> str:
        return self.keycol.get(table, "id")

    def idx_of(self, table: str, cols: tuple[str, ...]) -> str:
        return "PRIMARY" if set(cols) == set(self.pks.get(table, ("id",))) else "u:" + ",".join(sorted(cols))

    def idx_where(self, table: str, wh: str, alias: str | None, key: str = "") -> str:
        """The index a WHERE finds the row by: the primary key when it names every PK column."""
        if "=" in key:
            return self.idx_of(table, (key.split("=", 1)[0],))
        pre = r"(?:\b" + re.escape(alias) + r"\.|(?<![.\w]))" if alias else r"(?<![.\w])"
        pk = self.pks.get(table, ("id",))
        if all(re.search(pre + re.escape(c) + r"\s*=", wh, re.I) for c in pk):
            return "PRIMARY"
        return self.idx_of(table, (self.key_col(table),))

    def _fk_locks(self, table: str, colvals: dict[str, str], where: str, why: str) -> list[Lock]:
        out = []
        for f in self.fks:
            if f.child != table or not any(c in colvals for c in f.cols):
                continue
            # The row key is the value of the FK column that maps to the parent's key column
            # (a column left out, such as a generated kind, still gets checked).
            kc = self.key_col(f.parent)
            val = colvals.get(f.cols[f.pcols.index(kc)] if kc in f.pcols else f.cols[0], UNKNOWN)
            if val in ("null",):
                continue
            out.append(Lock("S", f.parent, val, self.idx_of(f.parent, f.pcols), where, f"{why} {table}.{','.join(f.cols)}"))
        return out

    def stmt_locks(self, proc: Proc, ln: int, st: str, depth: int) -> list[Lock]:
        where = f"{proc.file}:{ln}"
        u = st.upper()
        locks: list[Lock] = []
        # Functions with side effects used inside expressions (MILL_NAME_PUT inserts a name).
        for fm in re.finditer(r"\b(" + ID + r")\s*\(", st):
            fn = self.procs.get(fm.group(1).lower())
            if fn is not None and fn.is_fn and not u.startswith("CREATE"):
                args = split_top(st[fm.end():_paren(st, fm.end() - 1) - 1])
                locks += self._inline(fn, args, depth)
        if re.match(r"(?:READ|SET)\b", st, re.I):
            # A condition, or SET x = (SELECT ...): its subqueries take shared locks in a routine.
            return locks + self._sub_locks(st, where)
        m = re.match(r"CALL\s+(" + ID + r")\s*\(", st, re.I)
        if m:
            callee = self.procs.get(m.group(1).lower())
            if callee is not None:
                args = split_top(st[m.end():_paren(st, m.end() - 1) - 1])
                return locks + self._inline(callee, args, depth)
            return locks
        m = re.match(r"INSERT\s+(?:IGNORE\s+)?INTO\s+`?(" + ID + r")`?\s*\(", st, re.I)
        if m:
            table = m.group(1).lower()
            c_end = _paren(st, m.end() - 1)
            cols = [norm(c) for c in split_top(st[m.end():c_end - 1])]
            rest = st[c_end:].strip()
            vm = re.match(r"VALUES\s*\(", rest, re.I)
            if vm:
                vals = [norm(v) for v in split_top(rest[vm.end():_paren(rest, vm.end() - 1) - 1])]
                colvals = dict(zip(cols, vals))
            else:
                colvals = {c: UNKNOWN for c in cols}
                # INSERT ... SELECT reads its source rows with shared locks (REPEATABLE READ).
                sm = re.search(r"\bFROM\s+(.*?)(?:\bWHERE\b(.*?))?(?:\bORDER\s+BY\b.*|\bLIMIT\b.*)?$", rest, re.I)
                if sm:
                    locks += self._from_locks(sm.group(1), sm.group(2) or "", "S", where, "insert-select")
            locks += self._fk_locks(table, colvals, where, "fk")
            if re.search(r"ON\s+DUPLICATE\s+KEY\s+UPDATE", st, re.I):
                locks.append(Lock("X", table, UNKNOWN, "PRIMARY", where, "upsert"))
            return locks
        m = re.match(r"UPDATE\s+`?(" + ID + r")`?(?:\s+(?!SET\b)(" + ID + r"))?\s+(JOIN\b.*?\s)?SET\s+(.*)$", st, re.I)
        if m:
            table, alias = m.group(1).lower(), m.group(2)
            setw = re.split(r"\bWHERE\b", m.group(4), maxsplit=1, flags=re.I)
            sets = {}
            for a in split_top(re.split(r"\bORDER\s+BY\b|\bLIMIT\b", setw[0], flags=re.I)[0]):
                if "=" in a:
                    k, v = a.split("=", 1)
                    sets[norm(k.split(".")[-1])] = norm(v)
            wh = setw[1] if len(setw) > 1 else ""
            key = _where_key(wh, alias, self.key_col(table))
            locks += self._sub_locks(wh, where)
            # Lock the row first (the update reads it), then the FK check on a changed FK column.
            locks.append(Lock("X", table, key, self.idx_where(table, wh, alias, key), where, "update"))
            changed = {c: v for c, v in sets.items() if v != c}
            for f in self.fks:
                if f.child != table or not any(c in changed for c in f.cols):
                    continue
                kc = self.key_col(f.parent)
                val = changed.get(f.cols[f.pcols.index(kc)] if kc in f.pcols else f.cols[0], UNKNOWN)
                if val != "null":
                    locks.append(Lock("S", f.parent, val, self.idx_of(f.parent, f.pcols), where,
                                      f"fk(update) {table}.{','.join(f.cols)}"))
            return locks
        m = re.match(r"DELETE\s+(?:" + ID + r"\s+)?FROM\s+`?(" + ID + r")`?(?:\s+(?!WHERE\b)(" + ID + r"))?.*?(?:\bWHERE\s+(.*))?$", st, re.I)
        if m:
            table = m.group(1).lower()
            wh = m.group(3) or ""
            key = _where_key(wh, None, self.key_col(table))
            locks += self._sub_locks(wh, where)
            locks.append(Lock("X", table, key, self.idx_where(table, wh, None, key), where, "delete"))
            return locks
        if re.search(r"\bFOR\s+UPDATE\s*$", st, re.I) and re.match(r"SELECT\b", st, re.I):
            fm = re.search(r"\bFROM\s+(.*?)(?:\bWHERE\b(.*?))?(?:\bORDER\s+BY\b.*|\bLIMIT\b.*|\bFOR\s+UPDATE\s*)$", st, re.I)
            if fm:
                locks += self._from_locks(fm.group(1), fm.group(2) or "", "X", where, "for update")
            return locks
        return locks

    def _from_locks(self, src: str, wh: str, mode: str, where: str, why: str) -> list[Lock]:
        """One lock per table in a FROM ... JOIN list (not JSON_TABLE), keyed from the WHERE."""
        out = []
        for tm in re.finditer(r"(?:^|\bJOIN\s+)`?(" + ID + r")`?(?:\s+(?:AS\s+)?(?!JOIN\b|ON\b|LEFT\b|WHERE\b)(" + ID + r"))?",
                              src.strip(), re.I):
            table = tm.group(1).lower()
            if table.upper() in ("LEFT", "INNER", "RIGHT", "JSON_TABLE"):
                continue
            key = _where_key(wh, tm.group(2), self.key_col(table))
            out.append(Lock(mode, table, key, self.idx_where(table, wh, tm.group(2), key), where, why))
        return out

    def _sub_locks(self, wh: str, where: str) -> list[Lock]:
        """A subquery in a DML WHERE, an IF condition or a SET reads its tables with shared locks."""
        out = []
        for sm in re.finditer(r"\(\s*SELECT\b", wh, re.I):
            sub = wh[sm.start() + 1:_paren(wh, sm.start()) - 1]
            fm = re.search(r"\bFROM\s+(.*?)(?:\bWHERE\b(.*?))?(?:\bGROUP\s+BY\b.*|\bORDER\s+BY\b.*|\bLIMIT\b.*)?$", sub, re.I)
            if fm:
                out += self._from_locks(fm.group(1), fm.group(2) or "", "S", where, "subquery")
        return out

    def _fk_cols(self, child: str, parent: str) -> set[str]:
        return {c for f in self.fks if f.child == child and f.parent == parent for c in f.cols}

    def _inline(self, callee: Proc, args: list[str], depth: int) -> list[Lock]:
        if depth > 8:
            return []
        sub = {p: norm(a) for p, a in zip(callee.params, args)}
        out = []
        for lk in self.locks(callee.name, depth + 1):
            key = sub.get(lk.key, lk.key if lk.key == UNKNOWN or not re.fullmatch(r"[pv]_\w+", lk.key) else f"{callee.name.lower()}.{lk.key}")
            out.append(Lock(lk.mode, lk.table, key, lk.idx, f"{lk.where} via {callee.name}", lk.why))
        return out

    def locks(self, name: str, depth: int = 0) -> list[Lock]:
        """The row locks one procedure takes, in statement order, callees inlined, keys in its own names."""
        k = name.lower()
        if k in self._memo:
            return self._memo[k]
        proc = self.procs[k]
        self._memo[k] = []  # recursion guard
        alias: dict[str, str] = {}
        last_new = ""
        out: list[Lock] = []
        for ln, st in proc.stmts:
            for lk in self.stmt_locks(proc, ln, st, depth):
                key = alias.get(lk.key, lk.key)
                if not key.startswith(NEW):  # a row this transaction inserted is already its own
                    out.append(Lock(lk.mode, lk.table, key, lk.idx, lk.where, lk.why))
            im = re.match(r"INSERT\s+(?:IGNORE\s+)?INTO\s+`?(" + ID + r")`?", st, re.I)
            if im:
                last_new = NEW + im.group(1).lower()
            cm = re.match(r"CALL\s+(" + ID + r")\s*\(", st, re.I)
            if cm and cm.group(1).lower() in self.procs:
                callee = self.procs[cm.group(1).lower()]
                args = split_top(st[cm.end():_paren(st, cm.end() - 1) - 1])
                for p, v in self._outs.get(callee.name.lower(), {}).items():
                    if p in callee.params and callee.params.index(p) < len(args):
                        alias[norm(args[callee.params.index(p)])] = v
            for tgt in _assigned(st):
                alias.pop(tgt, None)
            nm = re.fullmatch(r"SELECT\s+name\s+INTO\s+(" + ID + r")\s+FROM\s+name\s+WHERE\s+id\s*=\s*(" + ID + r")",
                              st, re.I)
            if nm:  # the desk's name read by id names the same seat row
                alias[nm.group(1).lower()] = alias.get(nm.group(2).lower(), nm.group(2).lower())
            sm = re.match(r"SET\s+(" + ID + r")\s*=\s*(.*)$", st, re.I)
            if sm:
                lhs, rhs = sm.group(1).lower(), norm(sm.group(2))
                gm = re.fullmatch(r"mill_name_get\('desk',(" + ID + r")\)", rhs)
                if re.fullmatch(r"last_insert_id\(\)", rhs) and last_new:
                    alias[lhs] = last_new
                elif gm:
                    alias[lhs] = alias.get(gm.group(1), gm.group(1))
                elif re.fullmatch(ID, rhs) and rhs not in ("null", "true", "false"):
                    alias[lhs] = alias.get(rhs, rhs)
        self._outs[k] = {p: v for p, v in alias.items() if p in proc.params and v.startswith(NEW)}
        self._memo[k] = out
        return out

    def upgrades(self, name: str) -> list[tuple[Lock, Lock]]:
        """(S, later X) pairs on the same index record with no X held on that row before the S.

        X locks the record by the index it searches plus the primary key, so it meets an
        FK S lock when the S is on the primary key or on the index the X searched by.
        """
        found = []
        held_x: set[tuple[str, str]] = set()
        s_held: dict[tuple[str, str], list[Lock]] = {}
        for lk in self.locks(name):
            rk = (lk.table, lk.key)
            if lk.mode == "X":
                if lk.key != UNKNOWN and rk not in held_x:
                    hit = [s for s in s_held.get(rk, []) if s.idx in ("PRIMARY", lk.idx)]
                    if hit:
                        found.append((hit[0], lk))
                held_x.add(rk)
            elif lk.key != UNKNOWN and rk not in held_x and not self._covered(lk, held_x):
                s_held.setdefault(rk, []).append(lk)
        return found

    def _covered(self, lk: Lock, held_x: set[tuple[str, str]]) -> bool:
        """A shared read taken while this procedure already holds X on the item it belongs to.

        Assumption (the mill's lock order, F183): an item's rows (tree, watcher, activity) are
        written under the item's own row lock (todo, mail, hold, score by id), and a plan's tree
        rows under the plan's name row. So an X on todo[k] covers an S on tree[k], and an X on
        name[v] covers an S on tree[name_id=v] (tree.name_id references name).
        """
        val = lk.key.split("=", 1)[1] if "=" in lk.key else lk.key
        col = lk.key.split("=", 1)[0] if "=" in lk.key else self.key_col(lk.table)
        for t, k in held_x:
            if k != val or t == lk.table:
                continue
            if "=" not in lk.key and t in ("todo", "mail", "hold", "score"):
                return True
            if any(f.child == lk.table and f.parent == t and col in f.cols for f in self.fks):
                return True
        return False

    def writers(self) -> list[str]:
        return [p.name for p in self.procs.values() if not p.is_fn and self.locks(p.name)]

    @staticmethod
    def conflict(a: Lock, b: Lock) -> bool:
        """Two locks on one row conflict unless both are shared and when their index records meet
        (an X locks the record by its search index and by the primary key)."""
        if a.mode == "S" and b.mode == "S":
            return False
        if a.mode == "X" and b.mode == "X":
            return True
        s, x = (a, b) if a.mode == "S" else (b, a)
        return s.idx in ("PRIMARY", x.idx)

    def order_edges(self) -> dict[tuple[str, str], list[tuple[str, Lock, Lock]]]:
        """Table A -> B when a procedure holds a lock on A and then asks for one on B."""
        edges: dict[tuple[str, str], list[tuple[str, Lock, Lock]]] = {}
        for name in self.writers():
            held: dict[str, list[Lock]] = {}
            have: set[tuple[str, str, str]] = set()
            for lk in self.locks(name):
                if lk.key == UNKNOWN or (lk.table, lk.key, lk.mode) in have or (lk.table, lk.key, "X") in have:
                    continue
                have.add((lk.table, lk.key, lk.mode))
                for t, hs in held.items():
                    if t != lk.table:
                        edges.setdefault((t, lk.table), []).append((name, hs[0], lk))
                held.setdefault(lk.table, []).append(lk)
        return edges

    def cycles(self) -> list[tuple[str, str, list[str], list[str]]]:
        """Two-table cycles where, at each table, the asked-for lock conflicts with the held one."""
        e = self.order_edges()
        out = []
        for (a, b), fwd in e.items():
            if a >= b or (b, a) not in e:
                continue
            p, q = set(), set()
            for n1, h1, r1 in fwd:  # n1 holds a (h1), asks b (r1)
                for n2, h2, r2 in e[(b, a)]:  # n2 holds b (h2), asks a (r2)
                    if self.conflict(r1, h2) and self.conflict(r2, h1):
                        p.add(n1)
                        q.add(n2)
            if p:
                out.append((a, b, sorted(p), sorted(q)))
        return sorted(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sql", default=str(SQL))
    ap.add_argument("--proc", default="")
    ap.add_argument("--cycles", action="store_true")
    a = ap.parse_args(argv)
    an = Analyzer(Path(a.sql))
    names = [a.proc] if a.proc else an.writers()
    bad = 0
    for n in names:
        if a.proc:
            for lk in an.locks(n):
                print(f"  {lk.mode} {lk.table}[{lk.key}] {lk.idx} {lk.why} @ {lk.where}")
        for s, x in an.upgrades(n):
            bad += 1
            print(f"UPGRADE {n}: S {s.table}[{s.key}] {s.idx} ({s.why} @ {s.where}) then X {x.idx} ({x.why} @ {x.where})")
    if a.cycles:
        for t1, t2, p, q in an.cycles():
            print(f"CYCLE {t1} -> {t2}: {', '.join(p)}; {t2} -> {t1}: {', '.join(q)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
