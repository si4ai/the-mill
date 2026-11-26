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

Slice 1 is wake (rows and leases). Holds, card status and send identity follow.
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

# protocol -> protected tables, transition activity type, entry points.
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
}

_ROUTINE = re.compile(r"\bCREATE\s+(?:DEFINER\s*=\s*\S+\s+)?(?:PROCEDURE|FUNCTION|TRIGGER)\s+`?(\w+)`?", re.I)


def _write_re(table: str) -> re.Pattern[str]:
    t = rf"`?{re.escape(table)}`?(?![\w.])"
    return re.compile(
        rf"\b(?:INSERT(?:\s+IGNORE)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+IGNORE)?|DELETE\s+FROM|DELETE\s+\w+\s+FROM)\s+{t}",
        re.I,
    )


_TRANS_INSERT = re.compile(r"\bINSERT(?:\s+IGNORE)?\s+INTO\s+`?transition`?\s*\(", re.I)


def _trans_put_re(activity: str) -> re.Pattern[str]:
    return re.compile(rf"\bmill_transition_put\s*\(\s*'{re.escape(activity)}'", re.I)


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


def _sql_hits(protocol: str, spec: dict, text: str) -> list[tuple[int, str, str]]:
    """(offset, kind, snippet) of every protected write in one SQL text."""
    hits: list[tuple[int, str, str]] = []
    for table in spec["tables"]:
        for m in _write_re(table).finditer(text):
            hits.append((m.start(), "sql-write", _snip(text[m.start():m.start() + 120])))
    for m in _TRANS_INSERT.finditer(text):
        end = text.find(";", m.end())
        stmt = text[m.start(): end if end >= 0 else len(text)]
        if f"'{spec['activity']}'" in stmt:
            hits.append((m.start(), "transition-write", _snip(stmt)))
    for m in _trans_put_re(spec["activity"]).finditer(text):
        hits.append((m.start(), "transition-write", _snip(text[m.start():m.start() + 120])))
    return hits


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

    def _fn(self) -> str:
        return ".".join(self.stack) or "<module>"

    def _def(self, node) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _def

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and len(node.value) > 8:
            for protocol, spec in PROTOCOLS.items():
                for off, kind, snip in _sql_hits(protocol, spec, node.value):
                    line = node.lineno + node.value.count("\n", 0, off)
                    self.out.append(Write(protocol, self.path, line, self._fn(), kind, snip))

    def visit_Call(self, node: ast.Call) -> None:
        for kw in node.keywords:
            v = kw.value
            if (kw.arg == "activity_type" and isinstance(v, ast.Attribute)
                    and isinstance(v.value, ast.Name) and v.value.id == "ActivityType"):
                for protocol, spec in PROTOCOLS.items():
                    if v.attr == spec["activity"]:
                        self.out.append(Write(protocol, self.path, node.lineno, self._fn(),
                                              "transition-write", f"put(activity_type=ActivityType.{v.attr})"))
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
    ),
    "agent_coord/server/planted.py": (
        "def lease_end_elsewhere(cn, wid):\n"
        "    put(cn, activity_type=ActivityType.wake, activity_id=wid)\n"
        "    cn.cursor().execute(\"DELETE FROM wake WHERE id = %s\", (wid,))\n"
    ),
}
PLANTED_WANT = {
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_wake_skip", "sql-write"),
    ("wake", "agent_coord/server/sql/sp_planted.sql", "planted_wake_skip", "transition-write"),
    ("wake", "agent_coord/server/planted.py", "lease_end_elsewhere", "transition-write"),
    ("wake", "agent_coord/server/planted.py", "lease_end_elsewhere", "sql-write"),
}


def self_test() -> list[str]:
    writes: list[Write] = []
    for path, text in PLANTED.items():
        writes += scan_sql(path, text) if path.endswith(".sql") else scan_py(path, text)
    got = {(f["protocol"], f["path"], f["function"], f["kind"]) for f in report(writes, [])["findings"]}
    problems = [f"planted bypass not flagged: {w}" for w in sorted(PLANTED_WANT - got)]
    if any(w.line == 3 and w.path.endswith(".sql") for w in writes):
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
