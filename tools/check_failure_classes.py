#!/usr/bin/env python3
"""Check docs/dev/FAILURE-CLASSES.md coverage.

Report when a class (that is not N/A) has no owner, when a named check
path does not exist in the repo, or when dated evidence is older than
N days (default 14).

Deterministic given --as-of and the same file + repo. No scan
timestamps in the result. Standard library only.

By default the command exits 0 after printing the report, even when it
finds something: it is a fact report, not a CI gate on main. Pass
--strict to exit 1 when a finding is present (for tests and a
deliberate check).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PATH_PREFIXES = (
    "tests/",
    "tools/",
    "verify/",
    "docs/",
    ".github/",
    "ci/",
    "scripts/",
    "agent_coord/",
    "build_backend/",
)
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
BT_RE = re.compile(r"`([^`]+)`")


def parse_table(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_table = False
    headers: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            headers = []
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cols:
            continue
        if cols[0].lower() == "class" or set(cols[0]) <= set(":-"):
            if cols[0].lower() == "class":
                headers = [h.lower() for h in cols]
                in_table = True
            continue
        if not in_table or not headers:
            continue
        rec = {headers[i]: cols[i] if i < len(cols) else "" for i in range(len(headers))}
        rows.append(rec)
    return rows


def is_na(status: str) -> bool:
    return status.strip().lower().startswith("n/a")


def has_owner(owner: str) -> bool:
    o = owner.strip()
    if not o or o in {"-", "-", "none", "n/a"}:
        return False
    return True


def evidence_dates(cell: str) -> list[date]:
    out: list[date] = []
    for m in DATE_RE.findall(cell or ""):
        try:
            out.append(date.fromisoformat(m))
        except ValueError:
            continue
    return out


def named_paths(check_cell: str) -> list[str]:
    """Repo-rooted paths named in backticks (or bare known prefixes)."""
    found: list[str] = []

    def consider(raw: str) -> None:
        s = raw.strip().strip("`")
        s = s.split()[0] if s else s
        s = s.split("::", 1)[0]  # drop pytest node
        s = s.split("#", 1)[0]
        s = s.strip().strip(",")
        if not s:
            return
        if s.startswith(PATH_PREFIXES) or (
            "/" not in s and s.endswith((".py", ".sh", ".yml", ".yaml"))
        ):
            if s not in found:
                found.append(s)

    for m in BT_RE.findall(check_cell or ""):
        consider(m)
    for pref in PATH_PREFIXES:
        for m in re.finditer(re.escape(pref) + r"[A-Za-z0-9_./-]+", check_cell or ""):
            consider(m.group(0))
    return found


def resolve_path(repo: Path, rel: str) -> bool:
    p = repo / rel
    if p.exists():
        return True
    # tools/foo.py vs foo.py at tools/
    name = Path(rel).name
    if name and (repo / "tools" / name).exists():
        return True
    return False


def check_rows(
    rows: list[dict[str, str]],
    repo: Path,
    *,
    as_of: date,
    stale_days: int,
) -> dict[str, Any]:
    cutoff = as_of - timedelta(days=stale_days)
    findings: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for row in rows:
        cls = row.get("class") or row.get("Class") or ""
        status = row.get("status") or ""
        owner = row.get("owner") or ""
        check = row.get("covering check") or ""
        evid = row.get("last result (sha, date)") or row.get("last result") or ""
        rec: dict[str, Any] = {
            "class": cls,
            "status": status,
            "owner": owner,
        }
        if not is_na(status) and not has_owner(owner):
            findings.append({**rec, "kind": "no_owner"})
        paths = named_paths(check)
        missing = [p for p in paths if not resolve_path(repo, p)]
        if missing:
            findings.append({**rec, "kind": "missing_path", "paths": missing})
        dates = evidence_dates(evid)
        if dates:
            newest = max(dates)
            rec_dates = {
                "newest_evidence": newest.isoformat(),
                "cutoff": cutoff.isoformat(),
            }
            if newest < cutoff:
                findings.append({**rec, "kind": "stale_evidence", **rec_dates})
        else:
            if (not is_na(status)) and "covered" in status.lower():
                warnings.append({**rec, "kind": "no_evidence_date"})
        if "stale" in evid.lower() or "stale" in status.lower():
            warnings.append({**rec, "kind": "marked_stale_in_cell"})
    findings.sort(key=lambda f: (f["kind"], f["class"]))
    warnings.sort(key=lambda f: (f["kind"], f["class"]))
    return {
        "as_of": as_of.isoformat(),
        "stale_days": stale_days,
        "cutoff": cutoff.isoformat(),
        "classes": len(rows),
        "findings": findings,
        "warnings": warnings,
        "counts": {
            "classes": len(rows),
            "findings": len(findings),
            "no_owner": sum(1 for f in findings if f["kind"] == "no_owner"),
            "missing_path": sum(1 for f in findings if f["kind"] == "missing_path"),
            "stale_evidence": sum(1 for f in findings if f["kind"] == "stale_evidence"),
            "warnings": len(warnings),
        },
    }


def render_md(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# Failure-class coverage",
        "",
        f"As of: `{report['as_of']}` (stale after {report['stale_days']} days, cutoff `{report['cutoff']}`)",
        f"Classes: **{c['classes']}**. Findings: **{c['findings']}** "
        f"(no owner {c['no_owner']}, missing path {c['missing_path']}, stale {c['stale_evidence']}).",
        "",
        "## Findings",
        "",
    ]
    if not report["findings"]:
        lines += ["None.", ""]
    else:
        for f in report["findings"]:
            extra = ""
            if f["kind"] == "missing_path":
                extra = " " + ", ".join(f"`{p}`" for p in f.get("paths") or [])
            if f["kind"] == "stale_evidence":
                extra = f" newest={f.get('newest_evidence')} cutoff={f.get('cutoff')}"
            lines.append(f"- `{f['kind']}`  -  {f['class']}:{extra}")
        lines.append("")
    lines += ["## Warnings", ""]
    if not report["warnings"]:
        lines += ["None.", ""]
    else:
        for w in report["warnings"]:
            lines.append(f"- `{w['kind']}`  -  {w['class']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--file", default="", help="FAILURE-CLASSES.md path (default: docs/dev/FAILURE-CLASSES.md under --repo)")
    p.add_argument("--repo", required=True, help="Repository root for path existence")
    p.add_argument("--as-of", default="", help="YYYY-MM-DD (default: today)")
    p.add_argument("--stale-days", type=int, default=14)
    p.add_argument("--out-json", default="")
    p.add_argument("--out-md", default="")
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a finding is present (default: exit 0 and print the report)",
    )
    args = p.parse_args(argv)
    repo = Path(args.repo)
    path = Path(args.file) if args.file else repo / "docs/dev/FAILURE-CLASSES.md"
    if not path.is_file():
        print(f"missing file: {path}", file=sys.stderr)
        return 2
    if not repo.is_dir():
        print(f"missing repo: {repo}", file=sys.stderr)
        return 2
    if args.as_of:
        as_of = date.fromisoformat(args.as_of)
    else:
        as_of = date.today()
    text = path.read_text(encoding="utf-8")
    rows = parse_table(text)
    if not rows:
        print("no class table rows parsed", file=sys.stderr)
        return 2
    report = check_rows(rows, repo, as_of=as_of, stale_days=args.stale_days)
    report["file"] = path.name
    text_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    text_md = render_md(report)
    if args.out_json:
        Path(args.out_json).write_text(text_json, encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(text_md, encoding="utf-8")
    c = report["counts"]
    print(
        "classes={classes} findings={findings} no_owner={no_owner} "
        "missing_path={missing_path} stale={stale_evidence} warnings={warnings}".format(**c)
    )
    if args.strict and report["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
