#!/usr/bin/env python3
"""Report flakes over GitHub workflow runs (card 1148 / 1079).

A flake is a head_sha + workflow that has a failed attempt followed by
a success on a later attempt or a later run of the same workflow
(a rerun that goes green). Pass-then-fail is a regression, not a flake.

This command keys on workflow name (the card 1148 definition), not only
on check-run name.

Deterministic given the same run list: output is sorted by sha then
workflow, and the result has no scan timestamps. Standard library only.

By default the command exits 0 after printing the report, even when it
finds something: it is a fact report, not a CI gate on main. Pass
--strict to exit 1 when a flake is present (for tests and a deliberate
check).

Live mode uses the GitHub workflow API when a token is in the
environment. Never print the token. Prefer --fixtures for tests.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any
from pathlib import Path

FAIL = {"failure", "timed_out", "startup_failure"}
SUCCESS = {"success"}


def is_fail(conclusion: str | None) -> bool:
    return (conclusion or "").lower() in FAIL


def is_success(conclusion: str | None) -> bool:
    return (conclusion or "").lower() in SUCCESS


def flake_pairs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by (head_sha, workflow_name); fail then later success."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        sha = str(r.get("head_sha") or r.get("sha") or "")
        wf = str(r.get("workflow_name") or r.get("name") or r.get("check_name") or "")
        event = str(r.get("event") or "")
        if not sha or not wf:
            continue
        if (r.get("status") or "completed").lower() not in {"completed", ""}:
            continue
        groups[(sha, wf, event)].append(r)

    flakes: list[dict[str, Any]] = []
    for (sha, wf, event), items in groups.items():
        def sort_key(r: dict[str, Any]) -> tuple:
            # numeric run id first, then attempt of that run. attempt-first
            # or string-id order reports pass-then-fail as a flake and
            # misses fail-then-pass.
            raw_id = r.get("id") or r.get("run_id") or 0
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                rid = 0
            attempt = int(r.get("run_attempt") or r.get("attempt") or 1)
            return (rid, attempt)

        items = sorted(items, key=sort_key)
        first_fail_i = None
        later_success = None
        for i, r in enumerate(items):
            concl = r.get("conclusion")
            if first_fail_i is None and is_fail(concl):
                first_fail_i = i
                continue
            if first_fail_i is not None and is_success(concl):
                later_success = r
                break
        if first_fail_i is not None and later_success is not None:
            fail = items[first_fail_i]
            fail_id = str(fail.get("id") or fail.get("run_id") or "")
            ok_id = str(later_success.get("id") or later_success.get("run_id") or "")
            kind = "rerun_attempt" if fail_id and fail_id == ok_id else "later_run"
            flakes.append(
                {
                    "head_sha": sha,
                    "workflow": wf,
                    "event": event,
                    "kind": kind,
                    "fail_attempt": int(fail.get("run_attempt") or fail.get("attempt") or 1),
                    "success_attempt": int(
                        later_success.get("run_attempt") or later_success.get("attempt") or 1
                    ),
                    "fail_id": fail_id,
                    "success_id": ok_id,
                }
            )
    flakes.sort(key=lambda f: (f["head_sha"], f["workflow"], f.get("event") or "", f["fail_id"]))
    return flakes


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return data["runs"]
    # 1079 check-run shape: {sha: [check_runs...]}
    runs: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for sha, items in data.items():
            if sha == "runs" or not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                rec = dict(it)
                rec.setdefault("head_sha", sha)
                rec.setdefault("workflow_name", it.get("name") or "")
                rec.setdefault("run_attempt", 1)
                # If both failure and success exist for the same name, assign
                # attempts in listed order so this fixture shape still works.
                runs.append(rec)
        # Give distinct attempts to same sha+workflow in list order
        seen: dict[tuple[str, str], int] = defaultdict(int)
        for r in runs:
            key = (str(r.get("head_sha")), str(r.get("workflow_name")))
            seen[key] += 1
            r["run_attempt"] = seen[key]
            r.setdefault("id", f"{key[0][:8]}-{key[1]}-{r['run_attempt']}")
    return runs


def fetch_runs(repo: str, since: str, token: str, page_limit: int = 20) -> list[dict[str, Any]]:
    """List workflow runs created since YYYY-MM-DD. Token is never printed."""
    runs: list[dict[str, Any]] = []
    q = f"/repos/{repo}/actions/runs?per_page=100"
    if since:
        q += f"&created=>{since}"
    url = "https://api.github.com" + q
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mill-auditor-flake-check",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    pages = 0
    while url and pages < page_limit:
        pages += 1
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                link = resp.headers.get("Link") or ""
        except urllib.error.HTTPError as e:
            raise SystemExit(f"github api error: HTTP {e.code}") from None
        for r in payload.get("workflow_runs") or []:
            runs.append(
                {
                    "id": r.get("id"),
                    "head_sha": r.get("head_sha"),
                    "workflow_name": (r.get("name") or (r.get("workflow_id") and str(r["workflow_id"]))),
                    "run_attempt": r.get("run_attempt") or 1,
                    "conclusion": r.get("conclusion"),
                    "status": r.get("status"),
                    "event": r.get("event"),
                }
            )
        url = ""
        if 'rel="next"' in link:
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<>")
                    break
    return runs


def render_md(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        "# CI flake reruns",
        "",
        f"Repo: `{report.get('repo') or ''}`",
        f"Window: `{report.get('since') or 'fixtures'}`",
        f"Runs checked: **{c['runs']}**. Flakes: **{c['flakes']}**.",
        "",
        "A flake is the same `head_sha` and workflow with a failed attempt "
        "followed by a later success (a rerun that goes green).",
        "",
        "## Flakes",
        "",
    ]
    flakes = report.get("flakes") or []
    if not flakes:
        lines += ["None.", ""]
        return "\n".join(lines)
    for f in flakes:
        lines.append(
            f"- `{f['head_sha'][:12]}` / `{f['workflow']}` "
            f"({f.get('kind') or 'later_run'}"
            f"{(' ' + f['event']) if f.get('event') else ''}: "
            f"fail attempt {f['fail_attempt']} then success attempt {f['success_attempt']})"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default="si4ai/the-mill")
    p.add_argument("--since", default="", help="YYYY-MM-DD for live workflow runs")
    p.add_argument("--fixtures", default="", help="Offline JSON of workflow runs")
    p.add_argument("--out-json", default="")
    p.add_argument("--out-md", default="")
    p.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a flake is found (default: exit 0 and print the report)",
    )
    args = p.parse_args(argv)

    if args.fixtures:
        runs = load_fixtures(Path(args.fixtures))
        source = "fixtures"
    else:
        token = (
            os.environ.get("GH_TOKEN")
            or os.environ.get("AUDITOR_GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or ""
        )
        if not args.since:
            print("provide --since YYYY-MM-DD or --fixtures", file=sys.stderr)
            return 2
        if not token:
            print("no github token in the environment; use --fixtures", file=sys.stderr)
            return 2
        runs = fetch_runs(args.repo, args.since, token)
        source = f"since:{args.since}"

    flakes = flake_pairs(runs)
    report = {
        "repo": args.repo,
        "since": args.since or None,
        "source": source,
        "counts": {"runs": len(runs), "flakes": len(flakes)},
        "flakes": flakes,
    }
    text_json = json.dumps(report, indent=2, sort_keys=True) + "\n"
    text_md = render_md(report)
    if args.out_json:
        Path(args.out_json).write_text(text_json, encoding="utf-8")
    if args.out_md:
        Path(args.out_md).write_text(text_md, encoding="utf-8")
    print(f"runs={len(runs)} flakes={len(flakes)}")
    if args.strict and flakes:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
