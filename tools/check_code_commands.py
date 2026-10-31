"""Fail when agent_coord Python strings/docstrings teach a mill command the parser refuses.

Complements F90 (docs). Walks agent_coord/**/*.py and extracts:

  - every backticked `mill ...` in a string or docstring
  - every string (or line of a multi-line string) that starts with `mill` and
    names a real or retired command with at least one `--flag` (a taught argv),
    or the short `mill <cmd>:` stderr shape agents copy

Each form is checked with the same parser rules as tools/check_doc_commands.py.
A line can opt out with the marker `code-commands: skip` on that line or the
line above (same idea as doc-commands: skip).

Usage:
  python tools/check_code_commands.py          # exit 0 clean, 1 on any mismatch
  python tools/check_code_commands.py --list   # print every taught form found
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_doc_commands as cdc

CODE_ROOT = ROOT / "agent_coord"
SKIP_MARK = "code-commands: skip"
BACKTICK = re.compile(r"`([^`]+)`")
# Line starts with mill <cmd>; we keep it when it teaches argv (a --flag) or
# the `mill <cmd>:` stderr shape.
LINE_MILL = re.compile(r"(?m)^(mill [a-z][a-z0-9-]*\b.*)$")
HAS_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*\b")
STDERR_SHAPE = re.compile(r"^mill [a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*:")


def _string_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield getattr(node, "lineno", 0) or 0, node.value
        elif isinstance(node, ast.JoinedStr):
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    yield getattr(node, "lineno", 0) or 0, v.value


def _skip_line(lines: list[str], idx: int) -> bool:
    if SKIP_MARK in lines[idx]:
        return True
    if idx > 0 and SKIP_MARK in lines[idx - 1]:
        return True
    return False


def _command_name(form: str) -> str | None:
    m = re.match(r"mill ([a-z][a-z0-9-]*)\b", form)
    return m.group(1) if m else None


def _is_taught_line(form: str, commands: dict) -> bool:
    """True when the line is a command an agent would copy, not English prose."""
    cmd = _command_name(form)
    if cmd is None:
        return False
    known = cmd in commands or cmd in cdc.GONE_COMMANDS
    if not known:
        return False
    if HAS_FLAG.search(form) or STDERR_SHAPE.match(form):
        return True
    # Bare `mill leftover` / short retired title still teach a gone name.
    if cmd in cdc.GONE_COMMANDS and len(form.split()) <= 4:
        return True
    return False


def _trim_form(form: str) -> str:
    """Keep the argv an agent would copy; drop a trailing comment or prose tail."""
    cut = form
    hash_at = cut.find(" #")
    if hash_at < 0:
        hash_at = cut.find("\t#")
    if hash_at >= 0:
        cut = cut[:hash_at]
    # "mill invite --door invite, then re-run mill install ..." -> first command only
    for joiner in (", then ", ", and ", " then re-run ", " then "):
        if joiner in cut:
            cut = cut.split(joiner, 1)[0]
            break
    # `mill connect: ready; ...` -> through the colon head, unless flags follow the colon
    # (`mill join failed: --ca ...` must keep --ca so the checker sees the drift).
    if STDERR_SHAPE.match(cut):
        head, _, tail = cut.partition(":")
        if HAS_FLAG.search(tail):
            cut = f"{head}:{tail}"
        else:
            cut = head
    # stop at `;` so a second sentence is not parsed as flags
    if ";" in cut:
        cut = cut.split(";", 1)[0]
    return cut.strip()


def taught_forms(text: str, commands: dict) -> list[tuple[int, str]]:
    """(1-based line-in-string, form) for every backticked or taught mill command."""
    out: list[tuple[int, str]] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if _skip_line(lines, i):
            continue
        for m in BACKTICK.finditer(line):
            span = m.group(1).strip()
            if re.search(r"(?<![\w./-])mill ", span):
                out.append((i + 1, _trim_form(span)))
        m = LINE_MILL.match(line.strip())
        if m and _is_taught_line(m.group(1).strip(), commands):
            out.append((i + 1, _trim_form(m.group(1).strip())))
    return out


def check_file(path: Path, commands: dict) -> list:
    rel = path.relative_to(ROOT).as_posix()
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [cdc.Finding("syntax", rel, str(path), f"cannot parse: {e}")]
    found = []
    seen: set[tuple] = set()
    for lineno, text in _string_nodes(tree):
        for line_in, form in taught_forms(text, commands):
            where = f"{rel}:{lineno}" if line_in <= 1 else f"{rel}:{lineno}+{line_in - 1}"
            wrapped = f"`{form}`"
            hits = list(cdc.check_text(wrapped, commands, where)) + list(cdc.retired(wrapped, where))
            for f in hits:
                key = (f.kind, f.where, f.text, f.why)
                if key not in seen:
                    seen.add(key)
                    found.append(f)
    return found


def iter_py() -> list[Path]:
    return sorted(p for p in CODE_ROOT.rglob("*.py") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print every taught mill form")
    args = ap.parse_args(argv)
    commands = cdc.load_commands()
    if args.list:
        for path in iter_py():
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            rel = path.relative_to(ROOT).as_posix()
            for lineno, text in _string_nodes(tree):
                for line_in, form in taught_forms(text, commands):
                    where = f"{rel}:{lineno}" if line_in <= 1 else f"{rel}:{lineno}+{line_in - 1}"
                    print(f"{where}\t{form}")
        return 0
    all_findings = []
    for path in iter_py():
        all_findings.extend(check_file(path, commands))
    for f in all_findings:
        print(f"{f.kind}\t{f.where}\t{f.text}\t{f.why}")
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
