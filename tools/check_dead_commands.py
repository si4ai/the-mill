#!/usr/bin/env python3
"""Dead mill commands and flags beyond tools/check_doc_commands.

Extracts every `mill ...` example from docs/ (all markdown), mill-desk and
other repo skills, agent-facing docs, and server hint / usage strings in
agent_coord/. Each example is checked against the current CLI parser
(`agent_coord.__main__._build_parser`, the same authority as
tools/check_doc_commands and `mill VERB --help`).

Findings already reported by check_doc_commands are dropped, so this
command prints only what is new. Output is sorted and has no timestamps.

By default the command exits 0 after printing the report, even when it
finds something: it is a fact report, not a CI gate on main. Pass
--strict to exit 1 when a new dead form is present (for tests and a
deliberate check).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Iterable

EXTRA_DOC_GLOBS = (
    "docs/**/*.md",
    "verify/**/SKILL.md",
    "verify/**/README.md",
    "tools/README.md",
)
CODE_GLOBS = ("agent_coord/**/*.py",)

DEAD_KINDS = frozenset(
    {
        "unknown-command",
        "unknown-sub",
        "unknown-flag",
        "retired-word",
        "stale-placeholder",
        "bad-choice",
    }
)


def _add_root(root: Path) -> None:
    root = root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    tools = root / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))


def load_cdc(root: Path):
    _add_root(root)
    import check_doc_commands as cdc  # type: ignore

    return cdc


def iter_docs(scan: Path, not_checked: set[str] | None = None) -> list[Path]:
    skip = set(not_checked or ())
    seen: set[str] = set()
    out: list[Path] = []
    for pat in EXTRA_DOC_GLOBS:
        for p in sorted(scan.glob(pat)):
            if not p.is_file():
                continue
            rel = p.resolve().relative_to(scan.resolve()).as_posix()
            if rel in seen or rel in skip:
                continue
            seen.add(rel)
            out.append(p)
    return out


def iter_code(scan: Path) -> list[Path]:
    out: list[Path] = []
    for pat in CODE_GLOBS:
        for p in sorted(scan.glob(pat)):
            if p.is_file() and p.suffix == ".py" and "__pycache__" not in p.parts:
                out.append(p)
    return out


def py_strings(path: Path) -> list[tuple[int, str]]:
    """Line number and string literals (and f-string text) that mention mill."""
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return []
    found: list[tuple[int, str]] = []

    def add(n: int, s: str) -> None:
        if s and "mill " in s:
            found.append((n, s))

    class V(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                add(getattr(node, "lineno", 1), node.value)

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            parts: list[str] = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                else:
                    parts.append("PLACEHOLDER")
            add(getattr(node, "lineno", 1), "".join(parts))

    V().visit(tree)
    found.sort(key=lambda t: (t[0], t[1]))
    return found


def scan_files(scan: Path, cdc, commands) -> list:
    findings = []
    for path in iter_docs(scan, getattr(cdc, 'NOT_CHECKED', set())):
        rel = path.resolve().relative_to(scan.resolve()).as_posix()
        text = path.read_text(encoding="utf-8")
        findings.extend(cdc.check_text(text, commands, rel))
        findings.extend(cdc.retired(text, rel))
    for path in iter_code(scan):
        rel = path.resolve().relative_to(scan.resolve()).as_posix()
        for lineno, text in py_strings(path):
            loc = f"{rel}:{lineno}"
            for m in cdc.MILL_AT.finditer(text):
                if cdc._negated(text, m.start(), m.end() + 24):
                    continue
                findings.extend(cdc.check_command(text, m.end(), commands, "prose", loc))
            findings.extend(cdc.retired_in(text, loc))
    return findings


def finding_key(f) -> tuple[str, str, str, str]:
    return (f.kind, f.where, f.text, f.why)


def existing_keys(root: Path, cdc) -> set[tuple[str, str, str, str]]:
    try:
        old = cdc.run(root)
    except Exception as e:  # parser or missing docs in a fixture tree
        # Fixtures may not be a full mill checkout; then nothing is "existing".
        if (root / "agent_coord" / "__main__.py").is_file() and (root / "tools" / "check_doc_commands.py").is_file():
            raise
        return set()
    return {finding_key(f) for f in old}


def as_dict(f) -> dict[str, str]:
    return {"kind": f.kind, "where": f.where, "text": f.text, "why": f.why}


def render_md(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Dead-command scan (new beyond check_doc_commands)",
        "",
        f"Commit: `{report.get('commit') or 'none'}`",
        f"Docs scanned: **{c['docs']}**. Code files scanned: **{c['code']}**.",
        f"Existing-tool findings: **{c['existing']}**. New findings: **{c['new']}**.",
        "",
        "## New findings",
        "",
    ]
    rows = report.get("new") or []
    if not rows:
        lines += ["None.", ""]
    else:
        for f in rows:
            lines.append(f"- `{f['where']}`: {f['kind']}: {f['text']} ({f['why']})")
        lines.append("")
    return "\n".join(lines)


def repo_commit(root: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", required=True, help="the-mill checkout (CLI parser)")
    p.add_argument(
        "--scan",
        default="",
        help="Tree to scan (default: --root). Use a fixture tree for demos.",
    )
    p.add_argument("--out-json", default="")
    p.add_argument("--out-md", default="")
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a new dead form is found (default: exit 0 and print the report)",
    )
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    scan = Path(args.scan).resolve() if args.scan else root
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    if not scan.is_dir():
        print(f"not a directory: {scan}", file=sys.stderr)
        return 2
    cdc = load_cdc(root)
    commands = cdc.load_commands()
    ours = [f for f in scan_files(scan, cdc, commands) if f.kind in DEAD_KINDS]
    ours.sort(key=lambda f: finding_key(f))
    # Dedup exact rows
    uniq = []
    seen: set = set()
    for f in ours:
        k = finding_key(f)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    # only subtract the existing tool when scanning the same checkout it covers.
    # A fixture tree is not a full mill checkout; nothing is "already reported".
    existing = existing_keys(root, cdc) if scan == root else set()
    # When scanning a fixture, also subtract findings the existing tool would
    # report on that tree if it were a full checkout (usually empty).
    new = [f for f in uniq if finding_key(f) not in existing]
    report = {
        "commit": repo_commit(root) if scan == root else "",
        "counts": {
            "docs": len(iter_docs(scan, getattr(cdc, 'NOT_CHECKED', set()))),
            "code": len(iter_code(scan)),
            "scanned_findings": len(uniq),
            "existing": sum(1 for f in uniq if finding_key(f) in existing),
            "new": len(new),
        },
        "new": [as_dict(f) for f in new],
    }
    text_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    text_md = render_md(report)
    if args.out_json:
        Path(args.out_json).write_text(text_json, encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(text_md, encoding="utf-8")
    c = report["counts"]
    print(
        "docs={docs} code={code} existing={existing} new={new}".format(**c)
    )
    for f in report["new"]:
        print(f"{f['where']}: {f['kind']}: {f['text']} ({f['why']})")
    if args.strict and new:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
