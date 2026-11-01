#!/usr/bin/env python3
"""Check that each recovery-guard anchor still appears, as live code, in the cited source file.

  python check_anchors.py
  python check_anchors.py --mutant ID
  python check_anchors.py --list

With --mutant ID, the check breaks that anchor on a temp copy of the file in
every way listed below and expects each broken copy to fail (this proves the
property can fail):
  - remove: the marker is deleted
  - comment: every line of the marker is commented out in place
             (Python "# "; SQL "-- " per line, and a "/* ... */" block)
  - absent anchors: a forbidden line is inserted into the region

Rules (cards 1014 and the Validator's D4/D5/comment findings):
  - the marker's first line is the real guard (or definition) line; it must be
    code, not a comment, import, log call, message text, SIGNAL, raise, bare
    `try:` or block keyword
  - the marker as a whole must hold at least one code line besides imports,
    logs and messages, so log-only and try+import markers are refused
  - matches are counted on the file with comments blanked out, so a guard
    that has been commented out (line or block comment) no longer counts
  - the marker must match expected_count times (default 1)
  - kind "absent" anchors name a region (start and end markers) and regexes
    that must not appear in it with comments blanked out (for "this path
    writes nothing" properties)
  - every anchor is self-mutated by run.sh (not a hand-picked subset)

Standard library only. Not wired into CI.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ANCHORS = HERE / "anchors.json"

LOG_RE = re.compile(r"^(?:await\s+)?(?:[\w.]+\.)?(?:\w*log\w*|print|warn\w*)\s*\(", re.I)
MESSAGE_RE = re.compile(r"MESSAGE_TEXT|^SIGNAL\b|^RESIGNAL\b|^raise\b", re.I)
BLOCK_RE = re.compile(
    r"^(?:try:|finally:|else:|except\b.*:|pass|BEGIN|END\b.*|DO|THEN|\)|\}|\]|;)$",
    re.I,
)


def load() -> list[dict]:
    data = json.loads(ANCHORS.read_text(encoding="utf-8"))
    return list(data["anchors"])


def lang_of(path: str) -> str:
    return "sql" if path.endswith(".sql") else "py"


def mask_comments(text: str, lang: str) -> str:
    """Blank out comment characters (keep length and newlines); strings are kept."""
    out = list(text)
    i, n = 0, len(text)
    quotes = ("'", '"', "`") if lang == "sql" else ("'", '"')
    while i < n:
        c = text[i]
        if lang == "py" and text.startswith(('"""', "'''"), i):
            q = text[i : i + 3]
            j = text.find(q, i + 3)
            i = n if j < 0 else j + 3
            continue
        if c in quotes:
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        line_comment = c == "#" or (
            lang == "sql"
            and text.startswith("--", i)
            and (i + 2 >= n or text[i + 2] in " \t\r\n")
        )
        if line_comment:
            j = text.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if lang == "sql" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def classify(line: str) -> str:
    s = line.strip()
    if not s:
        return "blank"
    if s.startswith(("#", "--", "/*", "*", "//")):
        return "comment"
    if s.startswith("import ") or (s.startswith("from ") and " import " in s):
        return "import"
    if LOG_RE.match(s):
        return "log"
    if MESSAGE_RE.search(s):
        return "message"
    if BLOCK_RE.match(s):
        return "block"
    return "code"


def validate_marker(a: dict) -> tuple[bool, str]:
    """Refuse markers that sit on the wrong kind of line."""
    if a.get("kind") == "absent":
        for k in ("start", "end", "forbid"):
            if not a.get(k):
                return False, f"absent anchor needs {k}"
        return True, "ok"
    m = a["marker"]
    if not m or not m.strip():
        return False, "empty marker"
    lines = [ln for ln in m.strip("\n").split("\n")]
    first = classify(lines[0])
    if first != "code":
        return False, f"marker's first line is a {first} line, not a guard: {lines[0].strip()!r}"
    if not any(classify(ln) == "code" for ln in lines):
        return False, "marker holds no code line"
    return True, "ok"


def count_live(text: str, marker: str, lang: str) -> int:
    return mask_comments(text, lang).count(mask_comments(marker, lang))


def region(text: str, a: dict) -> str | None:
    lang = lang_of(a["path"])
    masked = mask_comments(text, lang)
    start = mask_comments(a["start"], lang)
    if masked.count(start) != 1:
        return None
    s = masked.index(start)
    e = masked.find(mask_comments(a["end"], lang), s + len(start))
    if e < 0:
        return None
    return masked[s:e]


def check_one(root: Path, a: dict) -> tuple[bool, str]:
    ok, msg = validate_marker(a)
    if not ok:
        return False, msg
    path = root / a["path"]
    if not path.is_file():
        return False, f"missing file {a['path']}"
    text = path.read_text(encoding="utf-8", errors="replace")
    if a.get("kind") == "absent":
        body = region(text, a)
        if body is None:
            return False, f"region not found once in {a['path']}"
        for pat in a["forbid"]:
            if re.search(pat, body, re.I | re.M):
                return False, f"forbidden {pat!r} found in region of {a['path']}"
        return True, "ok"
    count = count_live(text, a["marker"], lang_of(a["path"]))
    expected = int(a.get("expected_count", 1))
    if count != expected:
        return False, f"live marker count {count} != expected {expected} in {a['path']}: {a['marker']!r}"
    return True, "ok"


def comment_out(marker: str, lang: str) -> list[tuple[str, str]]:
    lines = marker.split("\n")
    if lang == "py":
        return [("comment-line", "\n".join("# " + ln for ln in lines))]
    return [
        ("comment-line", "\n".join("-- " + ln for ln in lines)),
        ("comment-block", "/* " + marker + " */"),
    ]


def mutants_for(text: str, a: dict) -> list[tuple[str, str]]:
    lang = lang_of(a["path"])
    if a.get("kind") == "absent":
        masked = mask_comments(text, lang)
        s = masked.find(mask_comments(a["start"], lang))
        if s < 0:
            return []
        cut = text.find("\n", s) + 1
        return [("inject", text[:cut] + a["inject"] + "\n" + text[cut:])]
    marker = a["marker"]
    if marker not in text:
        return []
    out = [("remove", text.replace(marker, "/* MUTANT REMOVED */", 1))]
    for name, rep in comment_out(marker, lang):
        out.append((name, text.replace(marker, rep, 1)))
    return out


def run_mutant(root: Path, anchors: list[dict], target: dict) -> int:
    src = root / target["path"]
    text = src.read_text(encoding="utf-8")
    variants = mutants_for(text, target)
    if not variants:
        print(f"check_anchors: mutant {target['id']}: marker absent, cannot mutate", file=sys.stderr)
        return 1
    rc = 0
    for name, mutated in variants:
        with tempfile.TemporaryDirectory(prefix="code-mut-") as td:
            td_path = Path(td)
            dst = td_path / target["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(mutated, encoding="utf-8")
            for a in anchors:
                d = td_path / a["path"]
                if not d.exists():
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(root / a["path"], d)
            ok, msg = check_one(td_path, target)
        if ok:
            print(f"check_anchors: mutant {target['id']}/{name} unexpectedly passed")
            rc = 1
        else:
            print(f"check_anchors: mutant {target['id']}/{name} failed as expected ({msg[:120]})")
    return rc


SELFTEST = [
    # (marker, path, why it must be refused) - the Validator's D4/D5 shapes
    ('_bc_log_safe(f"webhook desk={d} wake=done")', "x.py", "log line only"),
    ("try:\n        from agent_coord.server import push", "x.py", "try + import"),
    ("from agent_coord.server import push", "x.py", "import only"),
    ("SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: x';", "x.sql", "SIGNAL/message only"),
    ("SET MESSAGE_TEXT = 'x';", "x.sql", "message only"),
    ("# if stale:\n        return 1", "x.py", "comment"),
    ("-- IF x THEN\n  SET y = 1;", "x.sql", "comment"),
]


def selftest() -> int:
    rc = 0
    for marker, path, why in SELFTEST:
        ok, _ = validate_marker({"marker": marker, "path": path})
        if ok:
            print(f"check_anchors selftest: {why} marker was accepted", file=sys.stderr)
            rc = 1
    live = "if x:\n    return 1\n"
    for text, lang, why in (
        ("# if x:\n#     return 1\n", "py", "py line comment"),
        ("/* IF x THEN\n  SET y = 1; */", "sql", "sql block comment"),
        ("-- IF x THEN\n--   SET y = 1;", "sql", "sql line comment"),
    ):
        m = "if x:\n    return 1" if lang == "py" else "IF x THEN\n  SET y = 1;"
        if count_live(text, m, lang) != 0:
            print(f"check_anchors selftest: {why} still counted as live", file=sys.stderr)
            rc = 1
    if count_live(live, "if x:\n    return 1", "py") != 1:
        print("check_anchors selftest: live code not counted", file=sys.stderr)
        rc = 1
    print("check_anchors selftest: " + ("ok" if rc == 0 else "FAILED"))
    return rc


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT, help="repo root")
    ap.add_argument("--mutant", metavar="ID", help="break this anchor on a temp tree and expect failure")
    ap.add_argument("--list", action="store_true", help="print anchor ids (one per line) and exit")
    ap.add_argument("--selftest", action="store_true", help="prove the marker rules refuse D4/D5/comment shapes")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    anchors = load()
    by_id = {a["id"]: a for a in anchors}

    if args.list:
        for a in anchors:
            print(a["id"])
        return 0

    if args.mutant:
        if args.mutant not in by_id:
            print(f"check_anchors: unknown mutant id {args.mutant}", file=sys.stderr)
            return 2
        return run_mutant(args.root, anchors, by_id[args.mutant])

    failed = 0
    for a in anchors:
        ok, msg = check_one(args.root, a)
        status = "ok" if ok else "FAIL"
        print(f"{status:4}  {a['id']:<28} {a['path']}  ({a.get('property', '')})")
        if not ok:
            print(f"       {msg}", file=sys.stderr)
            failed += 1
    total = len(anchors)
    print(f"check_anchors: {total - failed}/{total} anchors present")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
