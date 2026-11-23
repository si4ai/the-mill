#!/usr/bin/env python3
"""Fail a PR that adds a silencer without a written reason (card 1273).

A silencer is a new # noqa, # type: ignore, # nosec, pragma: no cover,
CodeQL query-filter exclude, or Dependabot ignore. Existing silencers on
the base are left alone (even when they only name a rule). A move that
deletes and re-adds the same comment text is not a new silencer.

  python3 tools/check_silencers.py --base REV [--head REV]

Exit 0 when every new silencer has a reason on the same line or entry.
Exit 1 when one does not. A git failure exits 2.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# After the silencer token is stripped, a reason is leftover text that
# contains a letter (a parenthetical or a second comment), not only codes.
_HAS_LETTER = re.compile(r"[A-Za-z]")

_NOQA = re.compile(
    r"#\s*noqa\b(?::\s*[A-Za-z][A-Za-z0-9]+(?:\s*,\s*[A-Za-z][A-Za-z0-9]+)*)?",
    re.I,
)
_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore\b(?:\[[^\]]*\])?", re.I)
_NOSEC = re.compile(r"#\s*nosec\b(?::?\s*[A-Za-z][A-Za-z0-9]+(?:\s*,\s*[A-Za-z][A-Za-z0-9]+)*)?", re.I)
_NO_COVER = re.compile(r"#\s*pragma:\s*no cover\b", re.I)

_CODE_SILENCERS = (
    ("noqa", _NOQA),
    ("type-ignore", _TYPE_IGNORE),
    ("nosec", _NOSEC),
    ("no-cover", _NO_COVER),
)

_QUERY_ID_LINE = re.compile(
    r"^\s*id:\s*['\"]?(?:py|js|js\/|ts|go|java|rb|actions|cs|cpp|swift|rust|mill)/",
    re.I,
)
_DEP_NAME_LINE = re.compile(r"^\s*-\s*dependency-name\s*:")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def format(self) -> str:
        return (
            f"{self.path}:{self.line}: new {self.kind} without a written reason "
            f"on the same line or entry: {self.text.strip()}"
        )


def _git(*args: str, cwd: Path = ROOT) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git failed").strip()
        raise RuntimeError(err)
    return proc.stdout


def _comment_reason(text: str) -> bool:
    """True when a # comment on this line has a letter after the first #."""
    i = text.find("#")
    if i < 0:
        return False
    return bool(_HAS_LETTER.search(text[i + 1 :]))


def _reason_after(match: re.Match[str], line: str) -> bool:
    rest = line[match.end() :]
    # A first leftover "#" starts a second comment; letters anywhere count.
    return bool(_HAS_LETTER.search(rest))


def _is_codeql_config(path: str) -> bool:
    norm = path.replace("\\", "/")
    name = Path(norm).name
    return (
        norm.startswith(".github/codeql/")
        or name == "codeql-config.yml"
        or name == "codeql-config.yaml"
    )


def _is_dependabot(path: str) -> bool:
    norm = path.replace("\\", "/")
    return Path(norm).name in {"dependabot.yml", "dependabot.yaml"}


def _code_findings(path: str, line_no: int, text: str) -> list[Finding]:
    found: list[Finding] = []
    for kind, rx in _CODE_SILENCERS:
        for m in rx.finditer(text):
            if not _reason_after(m, text):
                found.append(Finding(path, line_no, kind, text))
    return found


def _config_findings(path: str, line_no: int, text: str) -> list[Finding]:
    # Flag the entry line (the query id or the dependency name), not the
    # wrapper key. The reason may sit on that same line; that is the entry.
    found: list[Finding] = []
    if _is_codeql_config(path) and _QUERY_ID_LINE.search(text):
        if not _comment_reason(text):
            found.append(Finding(path, line_no, "codeql-exclude", text))
    if _is_dependabot(path) and _DEP_NAME_LINE.search(text):
        if not _comment_reason(text):
            found.append(Finding(path, line_no, "dependabot-ignore", text))
    return found


def _silencer_key(kind: str, text: str) -> str:
    return f"{kind}\0{text.strip()}"


def parse_diff(diff: str) -> list[Finding]:
    """Return new silencers in added lines that have no reason.

    A comment text deleted in the same file (a move or rewrite) does not
    count as new.
    """
    findings: list[Finding] = []
    deleted: dict[str, set[str]] = {}
    pending: list[Finding] = []
    path = ""
    new_line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ ") or raw.startswith("--- "):
            # +++ b/path or --- a/path
            tag, _, rest = raw.partition(" ")
            if rest.startswith("b/") or rest.startswith("a/"):
                cand = rest[2:]
                if cand != "/dev/null":
                    path = cand
            continue
        if raw.startswith("diff --git "):
            path = ""
            new_line = 0
            continue
        if raw.startswith("@@"):
            # @@ -old,cnt +new,cnt @@
            m = re.search(r"\+(\d+)", raw)
            new_line = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:]
            for f in _code_findings(path, new_line, text) + _config_findings(
                path, new_line, text
            ):
                pending.append(f)
            new_line += 1
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            text = raw[1:]
            # Record every silencer-shaped deleted line, even those with a
            # reason, so a moved line is not treated as new.
            for kind, rx in _CODE_SILENCERS:
                if rx.search(text):
                    deleted.setdefault(path, set()).add(_silencer_key(kind, text))
            if _is_codeql_config(path) and _QUERY_ID_LINE.search(text):
                deleted.setdefault(path, set()).add(
                    _silencer_key("codeql-exclude", text)
                )
            if _is_dependabot(path) and _DEP_NAME_LINE.search(text):
                deleted.setdefault(path, set()).add(
                    _silencer_key("dependabot-ignore", text)
                )
            continue
        if raw.startswith("\\"):
            continue
        # context line in -U0 diffs should not appear; ignore others
    for f in pending:
        keys = deleted.get(f.path, set())
        if _silencer_key(f.kind, f.text) in keys:
            continue
        findings.append(f)
    return findings


def scan(base: str, head: str, cwd: Path = ROOT) -> list[Finding]:
    diff = _git("diff", "-U0", "--no-ext-diff", "-M", f"{base}...{head}", cwd=cwd)
    return parse_diff(diff)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="git revision to compare against")
    ap.add_argument("--head", default="HEAD", help="git revision to scan (default HEAD)")
    ap.add_argument("--cwd", default=str(ROOT), help="repository root")
    args = ap.parse_args(argv)
    cwd = Path(args.cwd)
    try:
        findings = scan(args.base, args.head, cwd=cwd)
    except RuntimeError as e:
        print(f"check_silencers: git failed: {e}", file=sys.stderr)
        return 2
    if not findings:
        print("check_silencers: no new silencer without a reason")
        return 0
    print("check_silencers: a new silencer needs a written reason on the same line or entry:")
    for f in findings:
        print(f.format())
    return 1


if __name__ == "__main__":
    sys.exit(main())
