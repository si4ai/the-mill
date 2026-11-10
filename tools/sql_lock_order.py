"""Lock-order check for the mill stored procedures (card 1113).

Reads the pack SQL, no database. For every procedure it lists the row locks the
statements take, in order, with CALLs and MILL_NAME_* functions inlined:

- an INSERT, or an UPDATE that sets a foreign-key column, takes a shared (S)
  lock on the parent row (InnoDB's FK check). The FKs come from tables.sql.
- SELECT ... FOR UPDATE, UPDATE and DELETE take an exclusive (X) lock on the
  rows they name.

A row is told apart by the expression that names it (v_desk, p_id, ...), with
CALL arguments put in for the callee's parameters. Two findings:

- upgrade: one procedure takes S on a parent row and later X on the same row
  (same table, same key) without holding X first. Two sessions doing that on
  one row deadlock (1213): each holds S and waits for X.
- cycle: across procedures, the table order of exclusive-held locks forms a
  cycle (table A then B in one procedure, B then A in another).

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
                st = _lead(" ".join(st.split()))
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
    pat = r"(?:\b" + re.escape(alias) + r"\.|(?<![.\w]))" if alias else r"(?<![.\w])"
    m = re.search(pat + re.escape(col) + r"\s*=\s*([^\s=]+(?:\([^)]*\))?)", where, re.I)
    return norm(m.group(1)) if m else UNKNOWN


class Analyzer:
    def __init__(self, sql: Path = SQL):
        self.fks = load_fks(sql)
        self.procs = load_procs(sql)
        self.parents = {f.parent for f in self.fks}
        self.keycol: dict[str, str] = {}
        for f in self.fks:
            self.keycol.setdefault(f.parent, f.pcols[0] if f.pcols[0] != "type" or len(f.pcols) == 1 else f.pcols[1])
        self._memo: dict[str, list[Lock]] = {}
        self._outs: dict[str, dict[str, str]] = {}

    def key_col(self, table: str) -> str:
        return self.keycol.get(table, "id")

    def _fk_locks(self, table: str, colvals: dict[str, str], where: str, why: str) -> list[Lock]:
        out = []
        for f in self.fks:
            if f.child != table or not all(c in colvals for c in f.cols):
                continue
            # The row key is the value of the FK column that maps to the parent's key column.
            kc = self.key_col(f.parent)
            val = colvals[f.cols[f.pcols.index(kc)]] if kc in f.pcols else colvals[f.cols[0]]
            if val in ("null",):
                continue
            out.append(Lock("S", f.parent, val, where, f"{why} {table}.{','.join(f.cols)}"))
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
            locks += self._fk_locks(table, colvals, where, "fk")
            if re.search(r"ON\s+DUPLICATE\s+KEY\s+UPDATE", st, re.I):
                locks.append(Lock("X", table, UNKNOWN, where, "upsert"))
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
            key = UNKNOWN if m.group(3) else _where_key(wh, alias, self.key_col(table))
            # Lock the row first (the update reads it), then the FK check on a changed FK column.
            locks.append(Lock("X", table, key, where, "update"))
            changed = {c: v for c, v in sets.items() if v != c}
            for f in self.fks:
                if f.child != table or not any(c in changed for c in f.cols):
                    continue
                kc = self.key_col(f.parent)
                val = changed.get(f.cols[f.pcols.index(kc)] if kc in f.pcols else f.cols[0], UNKNOWN)
                if val != "null":
                    locks.append(Lock("S", f.parent, val, where, f"fk(update) {table}.{','.join(f.cols)}"))
            return locks
        m = re.match(r"DELETE\s+FROM\s+`?(" + ID + r")`?(?:\s+(" + ID + r"))?\s*(?:WHERE\s+(.*))?$", st, re.I)
        if m:
            table = m.group(1).lower()
            locks.append(Lock("X", table, _where_key(m.group(3) or "", None, self.key_col(table)), where, "delete"))
            return locks
        if re.search(r"\bFOR\s+UPDATE\s*$", st, re.I) and re.match(r"SELECT\b", st, re.I):
            fm = re.search(r"\bFROM\s+(.*?)(?:\bWHERE\b(.*?))?(?:\bORDER\s+BY\b.*|\bLIMIT\b.*|\bFOR\s+UPDATE\s*)$", st, re.I)
            if fm:
                src, wh = fm.group(1), fm.group(2) or ""
                for tm in re.finditer(r"(?:^|\bJOIN\s+)`?(" + ID + r")`?(?:\s+(?:AS\s+)?(?!JOIN\b|ON\b|LEFT\b|WHERE\b)(" + ID + r"))?", src.strip(), re.I):
                    table = tm.group(1).lower()
                    if table.upper() in ("LEFT", "INNER", "RIGHT"):
                        continue
                    alias = tm.group(2)
                    locks.append(Lock("X", table, _where_key(wh, alias, self.key_col(table)), where, "for update"))
            return locks
        return locks

    def _fk_cols(self, child: str, parent: str) -> set[str]:
        return {c for f in self.fks if f.child == child and f.parent == parent for c in f.cols}

    def _inline(self, callee: Proc, args: list[str], depth: int) -> list[Lock]:
        if depth > 8:
            return []
        sub = {p: norm(a) for p, a in zip(callee.params, args)}
        out = []
        for lk in self.locks(callee.name, depth + 1):
            key = sub.get(lk.key, lk.key if lk.key == UNKNOWN or not re.fullmatch(r"[pv]_\w+", lk.key) else f"{callee.name.lower()}.{lk.key}")
            out.append(Lock(lk.mode, lk.table, key, f"{lk.where} via {callee.name}", lk.why))
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
                    out.append(Lock(lk.mode, lk.table, key, lk.where, lk.why))
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
        """(S, later X) pairs on the same parent row with no X held before the S."""
        found = []
        held_x: set[tuple[str, str]] = set()
        s_held: dict[tuple[str, str], Lock] = {}
        for lk in self.locks(name):
            rk = (lk.table, lk.key)
            if lk.mode == "X":
                if lk.key != UNKNOWN and rk in s_held and rk not in held_x:
                    found.append((s_held[rk], lk))
                held_x.add(rk)
            elif lk.key != UNKNOWN and rk not in held_x:
                s_held.setdefault(rk, lk)
        return found

    def writers(self) -> list[str]:
        return [p.name for p in self.procs.values() if not p.is_fn and self.locks(p.name)]

    def order_edges(self) -> dict[tuple[str, str], list[str]]:
        """Table A -> B when a procedure holds X on A and then asks for X on B."""
        edges: dict[tuple[str, str], list[str]] = {}
        for name in self.writers():
            seen: list[str] = []
            held: set[tuple[str, str]] = set()
            for lk in self.locks(name):
                if lk.mode != "X" or lk.key == UNKNOWN or (lk.table, lk.key) in held:
                    continue
                held.add((lk.table, lk.key))
                for a in seen:
                    if a != lk.table:
                        edges.setdefault((a, lk.table), []).append(name)
                if lk.table not in seen:
                    seen.append(lk.table)
        return edges

    def cycles(self) -> list[tuple[str, str, list[str], list[str]]]:
        e = self.order_edges()
        return sorted((a, b, sorted(set(e[(a, b)])), sorted(set(e[(b, a)])))
                      for (a, b) in e if a < b and (b, a) in e)


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
                print(f"  {lk.mode} {lk.table}[{lk.key}] {lk.why} @ {lk.where}")
        for s, x in an.upgrades(n):
            bad += 1
            print(f"UPGRADE {n}: S {s.table}[{s.key}] ({s.why} @ {s.where}) then X ({x.why} @ {x.where})")
    if a.cycles:
        for t1, t2, p, q in an.cycles():
            print(f"CYCLE {t1} -> {t2}: {', '.join(p)}; {t2} -> {t1}: {', '.join(q)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
