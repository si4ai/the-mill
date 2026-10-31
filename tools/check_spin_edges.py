#!/usr/bin/env python3
"""On-demand sync: every required SPIN product edge has a named test (card 916).

  python tools/check_spin_edges.py

Reads verify/spin/product_edges.txt (one id per line; # comments). Scans every
tests/**/*.py for the token `SPIN <id>` (word boundary). Prints mapped and
unmapped ids; exits 1 when any required id is unmapped. Not wired into CI:
SPIN stays on demand (letter 3408). Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDGES = ROOT / "verify" / "spin" / "product_edges.txt"
TESTS = ROOT / "tests"
TOKEN = re.compile(r"\bSPIN\s+([A-Za-z][A-Za-z0-9_]*)\b")


def required_ids() -> list[str]:
    out: list[str] = []
    for ln in EDGES.read_text(encoding="utf-8").splitlines():
        s = ln.split("#", 1)[0].strip()
        if s:
            out.append(s)
    return out


def found_ids() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for p in sorted(TESTS.rglob("test_*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        for m in TOKEN.finditer(text):
            hits.setdefault(m.group(1), []).append(rel)
    return hits


def main(argv: list[str]) -> int:
    need = required_ids()
    if not need:
        print("check_spin_edges: product_edges.txt names no ids", file=sys.stderr)
        return 1
    found = found_ids()
    mapped = [i for i in need if i in found]
    missing = [i for i in need if i not in found]
    for i in mapped:
        files = sorted(set(found[i]))
        print(f"mapped  {i}  ->  {', '.join(files[:3])}{' ...' if len(files) > 3 else ''}")
    for i in missing:
        print(f"unmapped  {i}")
    print(f"check_spin_edges: {len(mapped)}/{len(need)} mapped")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
