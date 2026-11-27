"""List code that writes protected mill state without the protocol's entry point (card 1312).

  python tools/bypass_scan.py                 # scan agent_coord/, exit 1 on a finding
  python tools/bypass_scan.py --report        # same JSON, always exit 0 (fact report)
  python tools/bypass_scan.py --self-test     # planted bypasses must be flagged

Static and deterministic: the same tree gives the same bytes. No LLM, no book.
For each protocol it finds every statement that writes the protected state:
direct SQL (INSERT, REPLACE, UPDATE, DELETE on the protected tables, in .sql
files and in Python string literals) and transition writes for that activity
(SQL that inserts a transition row naming it, a mill_transition_put call naming
it, a Python call with activity_type=ActivityType.<protocol>). A write inside
one of the protocol's entry points is by the protocol. Any other write is a
finding unless tools/bypass_allow.txt names it with a reason; an allow line
that matches no write is reported as stale.

Slices so far: wake (rows and leases) and card status (todo.status, assigned_id and claimed_at,
and the todo transition rows). Holds and send identity follow.

SQL shapes read (card 1329): INSERT, REPLACE and UPDATE with or without LOW_PRIORITY,
DELAYED, HIGH_PRIORITY or IGNORE, and INSERT without INTO; an UPDATE whose JOIN list names
the table after the first table (written when its SET assigns to the table's alias, or to
an unqualified column); a multi-table DELETE (DELETE w FROM x JOIN wake w, DELETE FROM w
USING ...); a transition INSERT or REPLACE with or without a column list; a put call that
passes ActivityType.<protocol> by position or by keyword. A string that is only a
docstring (a statement that is just a string) is documentation, not a write. Not read:
SQL assembled at run time from variables.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = Path(__file__).resolve().with_name("bypass_allow.txt")

# protocol -> protected tables, transition activity type, entry points. "columns" (optional)
# narrows an UPDATE to the ones that assign a protected column: card text and the acceptance
# line live on the todo row but are not card status. INSERT, REPLACE and DELETE always count.
# An entry point is "path::function" (function "*" = the whole file). A .sql
# function is the CREATE PROCEDURE / FUNCTION / TRIGGER name around it.
PROTOCOLS: dict[str, dict] = {
    "wake": {
        "tables": ("wake",),
        "activity": "wake",
        "entry": (
            "agent_coord/server/sql/sp_push.sql::*",
            "agent_coord/server/sql/sp_cmd.sql::cmd_push_put_back",
            "agent_coord/server/sql/sp_cmd.sql::cmd_push_mark",
            "agent_coord/server/sql/sp_cmd.sql::cmd_push_sent",
            "agent_coord/server/wake.py::*",
            "agent_coord/server/wake_lease.py::*",
            "agent_coord/server/records/push.py::*",
        ),
    },
    # Card status and claim: todo.status, todo.assigned_id and todo.claimed_at move only in the
    # todo write procedures (every claim, unclaim, assign and pass goes through mill_todo_write),
    # and each todo transition row is written by todo_activity.py (or by the retire, reclaim and
    # rename procedures themselves).
    "todo": {
        "tables": ("todo",),
        "columns": ("status", "assigned_id", "claimed_at"),
        "activity": "todo",
        "entry": (
            "agent_coord/server/sql/sp_todo.sql::*",
            "agent_coord/server/todo_activity.py::*",
        ),
    },
}

_ROUTINE = re.compile(r"\bCREATE\s+(?:DEFINER\s*=\s*\S+\s+)?(?:PROCEDURE|FUNCTION|TRIGGER)\s+`?(\w+)`?", re.I)


_MODS = r"(?:(?:LOW_PRIORITY|DELAYED|HIGH_PRIORITY|QUICK|IGNORE)\s+)*"
_KW = re.compile(r"\b(INSERT|REPLACE|UPDATE|DELETE)\b", re.I)
_INS_REST = re.compile(rf"\s*{_MODS}(?:INTO\s+)?`?(?:\w+`?\.`?)?(\w+)`?", re.I)
_NOT_ALIAS = frozenset(
    "JOIN INNER LEFT RIGHT CROSS NATURAL STRAIGHT_JOIN OUTER ON USING SET WHERE ORDER LIMIT AS FORCE USE IGNORE".split()
)


def _trans_put_re(activity: str) -> re.Pattern[str]:
    return re.compile(rf"\bmill_transition_put\s*\(\s*'{re.escape(activity)}'", re.I)


def _blank_parens(text: str) -> str:
    """Text inside parentheses becomes spaces, so a comma or = in a call is not a clause edge."""
    out, depth = [], 0
    for ch in text:
        if ch == "(":
            depth += 1
            out.append(" " if depth > 1 else ch)
        elif ch == ")":
            out.append(" " if depth > 1 else ch)
            depth = max(0, depth - 1)
        else:
            out.append(ch if depth == 0 or ch == "\n" else " ")
    return "".join(out)


def _names_for(refs: str, table: str) -> set[str]:
    """The table's own name and any alias it has in a table-reference list; empty if absent."""
    names: set[str] = set()
    for m in re.finditer(rf"(?<![\w.`])`?{re.escape(table)}`?(?![\w.`(])(?:\s+(?:AS\s+)?`?(\w+)`?)?", refs, re.I):
        names.add(table.lower())
        alias = m.group(1)
        if alias and alias.upper() not in _NOT_ALIAS:
            names.add(alias.lower())
    return names


def _clause_end(text: str) -> str:
    return re.split(r"\b(?:WHERE|ORDER\s+BY|LIMIT)\b", text, maxsplit=1, flags=re.I)[0]


def _update_writes(tail: str, table: str, columns: tuple[str, ...] | None = None) -> bool:
    m = re.match(rf"UPDATE\s+{_MODS}(.*?)\bSET\b(.*)", tail, re.I | re.S)
    if not m:
        return False
    names = _names_for(m.group(1), table)
    if not names:
        return False
    for part in _blank_parens(_clause_end(m.group(2))).split(","):
        lhs = part.split("=", 1)[0].strip().replace("`", "")
        if "=" not in part or not lhs:
            continue
        owner = lhs.rsplit(".", 1)[0].lower() if "." in lhs else ""
        if columns is not None and lhs.rsplit(".", 1)[-1].lower() not in columns:
            continue
        if owner == "" or owner in names:
            return True
    return False


def _delete_writes(tail: str, table: str) -> bool:
    m = re.match(rf"DELETE\s+{_MODS}(.*)", tail, re.I | re.S)
    if not m:
        return False
    rest = _clause_end(m.group(1))
    if re.match(r"FROM\b", rest, re.I):
        after = rest[4:]
        using = re.split(r"\bUSING\b", after, maxsplit=1, flags=re.I)
        if len(using) == 1:
            return bool(_names_for(after, table))
        targets, refs = using
    else:
        parts = re.split(r"\bFROM\b", rest, maxsplit=1, flags=re.I)
        if len(parts) == 1:
            return False
        targets, refs = parts
    names = _names_for(refs, table)
    wanted = {t.strip().replace("`", "").split(".")[0].lower() for t in targets.split(",") if t.strip()}
    return bool(names & wanted)


def _sql_hits(protocol: str, spec: dict, text: str) -> list[tuple[int, str, str]]:
    """(offset, kind, snippet) of every protected write in one SQL text."""
    hits: list[tuple[int, str, str]] = []
    tables = tuple(t.lower() for t in spec["tables"])
    for m in _KW.finditer(text):
        kw = m.group(1).upper()
        end = text.find(";", m.end())
        tail = text[m.start(): end if end >= 0 else len(text)]
        snip = _snip(tail[:120])
        if kw in ("INSERT", "REPLACE"):
            rest = tail[m.end() - m.start():]
            t = _INS_REST.match(rest)
            if t and t.group(1).lower() in tables:
                hits.append((m.start(), "sql-write", snip))
            elif t and t.group(1).lower() == "transition" and f"'{spec['activity']}'" in tail:
                hits.append((m.start(), "transition-write", _snip(tail)))
        elif kw == "UPDATE":
            cols = tuple(c.lower() for c in spec["columns"]) if spec.get("columns") else None
            if any(_update_writes(tail, t, cols) for t in tables):
                hits.append((m.start(), "sql-write", snip))
        elif any(_delete_writes(tail, t) for t in tables):
            hits.append((m.start(), "sql-write", snip))
    for m in _trans_put_re(spec["activity"]).finditer(text):
        hits.append((m.start(), "transition-write", _snip(text[m.start():m.start() + 120])))
    return sorted(set(hits))


@dataclass(frozen=True)
class Write:
    protocol: str
    path: str
    line: int
    function: str
    kind: str
    text: str

    def key(self) -> tuple:
        return (self.protocol, self.path, self.line, self.function, self.kind)


def _blank_sql_comments(text: str) -> str:
    """-- and /* */ comments become spaces, so line numbers stay true."""
    out = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"--[^\n]*", lambda m: " " * len(m.group(0)), out)


def _snip(text: str) -> str:
    return " ".join(text.split())[:100]


def scan_sql(path: str, text: str) -> list[Write]:
    clean = _blank_sql_comments(text)
    routines = [(m.start(), m.group(1)) for m in _ROUTINE.finditer(clean)]
    out: list[Write] = []
    for protocol, spec in PROTOCOLS.items():
        for off, kind, snip in _sql_hits(protocol, spec, clean):
            fn = "<top>"
            for start, name in routines:
                if start <= off:
                    fn = name
            out.append(Write(protocol, path, clean.count("\n", 0, off) + 1, fn, kind, snip))
    return out


class _PyScan(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.out: list[Write] = []
        self.docs: set[int] = set()

    def _fn(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _def(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    def visit_Expr(self, node: ast.Expr) -> None:
        # A statement that is only a string (a docstring, a block comment) runs nothing.
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            self.docs.add(id(node.value))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self.docs:
            return
        if isinstance(node.value, str) and len(node.value) > 8:
            for protocol, spec in PROTOCOLS.items():
                for off, kind, snip in _sql_hits(protocol, spec, node.value):
                    line = node.lineno + node.value.count("\n", 0, off)
                    self.out.append(Write(protocol, self.path, line, self._fn(), kind, snip))

    @staticmethod
    def _activity(v: ast.AST) -> str:
        """X for ActivityType.X or mod.ActivityType.X, else ''."""
        if isinstance(v, ast.Attribute):
            base = v.value
            if (isinstance(base, ast.Name) and base.id == "ActivityType") or (
                    isinstance(base, ast.Attribute) and base.attr == "ActivityType"):
                return v.attr
        return ""

    def visit_Call(self, node: ast.Call) -> None:
        args = [*node.args, *(kw.value for kw in node.keywords)]
        for v in args:
            act = self._activity(v)
            for protocol, spec in PROTOCOLS.items():
                if act and act == spec["activity"]:
                    self.out.append(Write(protocol, self.path, node.lineno, self._fn(),
                                          "transition-write", f"put(ActivityType.{act})"))
        self.generic_visit(node)


def scan_py(path: str, text: str) -> list[Write]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return []
    s = _PyScan(path)
    s.visit(tree)
    return s.out


def scan_tree(root: Path) -> list[Write]:
    out: list[Write] = []
    base = root / "agent_coord"
    for p in sorted(base.rglob("*")):
        if "__pycache__" in p.parts or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if p.suffix == ".sql":
            out += scan_sql(rel, p.read_text(encoding="utf-8"))
        elif p.suffix == ".py":
            out += scan_py(rel, p.read_text(encoding="utf-8"))
    return sorted(set(out), key=lambda w: w.key())


def _in_entry(w: Write) -> bool:
    for e in PROTOCOLS[w.protocol]["entry"]:
        path, _, fn = e.partition("::")
        if w.path == path and (fn == "*" or w.function == fn or w.function.startswith(fn + ".")):
            return True
    return False


def read_allow(path: Path) -> list[dict]:
    """Lines: PROTOCOL PATH::FUNCTION REASON... (# comments, blank lines skipped)."""
    out = []
    if not path.is_file():
        return out
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 2)
        if len(parts) < 3 or "::" not in parts[1]:
            raise SystemExit(f"bypass_scan: {path.name}:{no}: want PROTOCOL PATH::FUNCTION REASON")
        where, _, fn = parts[1].partition("::")
        out.append({"line": no, "protocol": parts[0], "path": where, "function": fn, "reason": parts[2]})
    return out


def _allowed(w: Write, allow: list[dict]) -> dict | None:
    for a in allow:
        if a["protocol"] == w.protocol and a["path"] == w.path and a["function"] in ("*", w.function):
            return a
    return None


def report(writes: list[Write], allow: list[dict]) -> dict:
    used: set[int] = set()
    findings, by_protocol, allowed = [], [], 0
    for w in writes:
        if _in_entry(w):
            continue
        a = _allowed(w, allow)
        if a is not None:
            used.add(a["line"])
            allowed += 1
            continue
        findings.append({"protocol": w.protocol, "path": w.path, "line": w.line,
                         "function": w.function, "kind": w.kind, "text": w.text})
    stale = [{"allow_line": a["line"], "protocol": a["protocol"], "where": f"{a['path']}::{a['function']}"}
             for a in allow if a["line"] not in used]
    for protocol in sorted(PROTOCOLS):
        mine = [w for w in writes if w.protocol == protocol]
        by_protocol.append({
            "protocol": protocol,
            "writes": len(mine),
            "via_entry": sum(1 for w in mine if _in_entry(w)),
            "findings": sum(1 for f in findings if f["protocol"] == protocol),
        })
    return {"protocols": by_protocol, "allowed": allowed, "findings": findings, "stale_allow": stale}


# Planted bypasses: each must come back as a finding, or the scan is broken.
PLANTED = {
    "agent_coord/server/sql/sp_planted.sql": (
        "CREATE PROCEDURE planted_wake_skip(IN p BIGINT)\nBEGIN\n"
        "  -- a comment: UPDATE wake SET state = 'x' must not count\n"
        "  UPDATE wake SET state = 'taken' WHERE id = p;\n"
        "  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason)\n"
        "  VALUES ('wake', p, 'sent', 'taken', 'wake_deliver');\nEND //\n"
        "CREATE PROCEDURE planted_join_first(IN p BIGINT)\nBEGIN\n"
        "  UPDATE activity a JOIN wake w ON w.id = a.id SET w.state = 'taken' WHERE a.id = p;\nEND //\n"
        "CREATE PROCEDURE planted_delete_join(IN p BIGINT)\nBEGIN\n"
        "  DELETE w FROM mail m JOIN wake w ON w.cause_id = m.id WHERE m.id = p;\nEND //\n"
        "CREATE PROCEDURE planted_low_priority(IN p BIGINT)\nBEGIN\n"
        "  UPDATE LOW_PRIORITY wake SET state = 'taken' WHERE id = p;\nEND //\n"
        "CREATE PROCEDURE planted_columnless(IN p BIGINT)\nBEGIN\n"
        "  INSERT INTO transition SELECT 0, NOW(6), 'wake', id, state, 'taken', 'wake_deliver', desk_id,\n"
        "    'office', NULL, NULL, 1 FROM wake WHERE id = p;\nEND //\n"
    ),
    "agent_coord/server/planted.py": (
        "def lease_end_elsewhere(cn, wid):\n"
        "    put(cn, activity_type=ActivityType.wake, activity_id=wid)\n"
        "    cn.cursor().execute(\"DELETE FROM wake WHERE id = %s\", (wid,))\n"
        "\n\n"
        "def positional(cn, wid):\n"
        "    put(cn, ActivityType.wake, wid, State.idle)\n"
        "\n\n"
        "def only_documents():\n"
        "    \"\"\"Runs UPDATE wake SET state = 'x' and DELETE FROM wake, in prose.\"\"\"\n"
    ),
}
PLANTED["agent_coord/server/sql/sp_planted_todo.sql"] = (
    "CREATE PROCEDURE planted_status_skip(IN p BIGINT)\nBEGIN\n"
    "  -- a comment: UPDATE todo SET status = 'done' must not count\n"
    "  UPDATE todo SET status = 'done' WHERE id = p;\nEND //\n"
    "CREATE PROCEDURE planted_claim_skip(IN p BIGINT, IN d BIGINT)\nBEGIN\n"
    "  UPDATE todo SET assigned_id = d, claimed_at = NOW(6) WHERE id = p;\nEND //\n"
    "CREATE PROCEDURE planted_join_status(IN p BIGINT)\nBEGIN\n"
    "  UPDATE todo t JOIN name r ON r.id = t.roster_id SET t.status = 'open' WHERE t.id = p;\nEND //\n"
    "CREATE PROCEDURE planted_card_row(IN p BIGINT)\nBEGIN\n"
    "  INSERT INTO todo (updated_id, roster_id, creator_id, status) VALUES (p, 1, 1, 'open');\nEND //\n"
    "CREATE PROCEDURE planted_card_gone(IN p BIGINT)\nBEGIN\n"
    "  DELETE FROM todo WHERE id = p;\nEND //\n"
    "CREATE PROCEDURE planted_todo_transition(IN p BIGINT)\nBEGIN\n"
    "  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason)\n"
    "  VALUES ('todo', p, 'open', 'claimed', 'claim');\nEND //\n"
    "CREATE PROCEDURE planted_note_only(IN p BIGINT)\nBEGIN\n"
    "  UPDATE todo SET body = 'x', done_when = 'y', meta = NULL WHERE id = p;\nEND //\n"
)
PLANTED["agent_coord/server/planted_todo.py"] = (
    "def card_done_elsewhere(cn, tid):\n"
    "    put(cn, activity_type=ActivityType.todo, activity_id=tid)\n"
    "    cn.cursor().execute(\"UPDATE todo SET status = 'shipped' WHERE id = %s\", (tid,))\n"
    "\n\n"
    "def note_only_py(cn, tid):\n"
    "    cn.cursor().execute(\"UPDATE todo SET done_when = %s WHERE id = %s\", ('y', tid))\n"
)
PLANTED_WANT = {
    *(("todo", "agent_coord/server/sql/sp_planted_todo.sql", fn, kind) for fn, kind in (
        ("planted_status_skip", "sql-write"),
        ("planted_claim_skip", "sql-write"),
        ("planted_join_status", "sql-write"),
        ("planted_card_row", "sql-write"),
        ("planted_card_gone", "sql-write"),
        ("planted_todo_transition", "transition-write"),
    )),
    ("todo", "agent_coord/server/planted_todo.py", "card_done_elsewhere", "transition-write"),
    ("todo", "agent_coord/server/planted_todo.py", "card_done_elsewhere", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_wake_skip", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_wake_skip", "transition-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_join_first", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_delete_join", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_low_priority", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_columnless", "transition-write"),
    ("wake", "agent_coord/server/planted.py", "lease_end_elsewhere", "transition-write"),
    ("wake", "agent_coord/server/planted.py", "lease_end_elsewhere", "sql-write"),
    ("wake", "agent_coord/server/planted.py", "positional", "transition-write"),
}
# Functions in the plants that only talk about a write: any finding there is a bug.
PLANTED_QUIET = {"only_documents", "planted_note_only", "note_only_py"}


def self_test() -> list[str]:
    writes: list[Write] = []
    for path, text in PLANTED.items():
        writes += scan_sql(path, text) if path.endswith(".sql") else scan_py(path, text)
    found = report(writes, [])["findings"]
    got = {(f["protocol"], f["path"], f["function"], f["kind"]) for f in found}
    problems = [f"planted bypass not flagged: {w}" for w in sorted(PLANTED_WANT - got)]
    problems += [f"counted a write that is not one: {f['function']}" for f in found
                 if f["function"] in PLANTED_QUIET]
    if any(f["line"] == 3 and f["path"].endswith(".sql") for f in found):
        problems.append("a commented-out write was counted")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bypass_scan", description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--allow", default=str(ALLOW))
    ap.add_argument("--report", action="store_true", help="always exit 0")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    problems = self_test()
    if problems:
        for p in problems:
            print(f"bypass_scan: self-test: {p}", file=sys.stderr)
        return 1
    if args.self_test:
        print("bypass_scan: self-test ok", file=sys.stderr)
        return 0
    try:
        allow = read_allow(Path(args.allow))
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    rep = report(scan_tree(Path(args.root)), allow)
    sys.stdout.write(json.dumps(rep, sort_keys=True, indent=1) + "\n")
    n, s = len(rep["findings"]), len(rep["stale_allow"])
    print(f"bypass_scan: {n} finding(s), {s} stale allow line(s), {rep['allowed']} allowed", file=sys.stderr)
    return 0 if args.report or not (n or s) else 1


if __name__ == "__main__":
    raise SystemExit(main())
