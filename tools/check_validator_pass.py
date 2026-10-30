#!/usr/bin/env python3
"""The Validator gate as a check (#810, F110). Standard library only.

  python3 tools/check_validator_pass.py      (in GitHub Actions)

Reads the event JSON at GITHUB_EVENT_PATH, the repo from GITHUB_REPOSITORY
and a read-only GITHUB_TOKEN (statuses and pull requests read).

merge_group: finds every PR in the queue entry (the pr-N in the queue
branch name and the "(#N)" squash subjects between the base and the queued
head) and requires the latest `validator` commit status on each PR's head
sha to be success. Anything else, or no PR found, fails.

Only statuses the Validator GitHub App posted count (#811, F111): creator
login exactly VALIDATOR_LOGIN and creator type exactly VALIDATOR_TYPE
("Bot", #663). Anyone with write access can post a
`validator` status, so a status from any other creator is ignored, neither
pass nor fail. Statuses are read from the full list for the exact head sha
(the combined status keeps one per context, from any creator).

pull_request: reports the `validator` state on the PR head and passes. The
queue is the gate: a PR may wait for its PASS without a red check. The line
starts WAITING (no verdict, or not success) or REPORT, never OK, and goes to
a ::notice annotation and the job summary too, so green is not read as PASS.

The report names PR numbers, shas and states, never PR text.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from typing import Callable

CONTEXT = "validator"
# The one creator the gate trusts: the si4ai-validator GitHub App (App ID 5431726).
VALIDATOR_LOGIN = "si4ai-validator[bot]"
# and its user object type: an app's bot user is "Bot", a person or token seat "User" (#663).
VALIDATOR_TYPE = "Bot"
PER_PAGE = 100
MAX_PAGES = 10  # GitHub keeps at most 1000 statuses per sha and context
QUEUE_REF_RE = re.compile(r"^(?:refs/heads/)?gh-readonly-queue/[^/]+(?:/[^/]+)*/pr-(\d+)-[0-9a-f]{40}$")
SUBJECT_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
API = "https://api.github.com"

Fetch = Callable[[str], object]


def http_fetch(path: str) -> object:
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + os.environ.get("GITHUB_TOKEN", ""),
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https host)
        return json.load(r)


def queue_prs(event: dict, repo: str, fetch: Fetch) -> list[int]:
    """PR numbers in a merge_group entry, ascending."""
    mg = event.get("merge_group") or {}
    nums: set[int] = set()
    m = QUEUE_REF_RE.match(str(mg.get("head_ref", "")))
    if m:
        nums.add(int(m.group(1)))
    base, head = str(mg.get("base_sha", "")), str(mg.get("head_sha", ""))
    if re.fullmatch(r"[0-9a-f]{40}", base) and re.fullmatch(r"[0-9a-f]{40}", head):
        cmp = fetch(f"/repos/{repo}/compare/{base}...{head}")
        for c in (cmp or {}).get("commits", []) if isinstance(cmp, dict) else []:
            subject = str((c.get("commit") or {}).get("message", "")).split("\n", 1)[0]
            s = SUBJECT_PR_RE.search(subject)
            if s:
                nums.add(int(s.group(1)))
    return sorted(nums)


def validator_state(repo: str, sha: str, fetch: Fetch) -> str:
    """Latest `validator` status on sha posted by VALIDATOR_LOGIN (type Bot):
    success, failure, error, pending or missing. Other creators are ignored."""
    counted: list[tuple[int, int, str]] = []
    pos = 0
    for page in range(1, MAX_PAGES + 1):
        batch = fetch(f"/repos/{repo}/commits/{sha}/statuses?per_page={PER_PAGE}&page={page}")
        if not isinstance(batch, list):
            break
        for st in batch:
            pos += 1
            if not isinstance(st, dict) or st.get("context") != CONTEXT:
                continue
            creator = st.get("creator") or {}
            if not isinstance(creator, dict):
                continue
            if str(creator.get("login", "")) != VALIDATOR_LOGIN or creator.get("type") != VALIDATOR_TYPE:
                continue
            url = st.get("url")
            if url is not None and not str(url).endswith(f"/statuses/{sha}"):
                continue
            sid = st.get("id")
            # newest first: the highest id, else the first listed
            counted.append((sid if isinstance(sid, int) else -1, -pos, str(st.get("state", "missing"))))
        if len(batch) < PER_PAGE:
            break
    return max(counted)[2] if counted else "missing"


def pr_stage_line(sha: str, state: str) -> tuple[str, str]:
    """The pull_request line: never reads as a pass, the queue enforces (#811)."""
    tail = "(report only; merge queue enforces)"
    if state == "success":
        return f"REPORT: {VALIDATOR_LOGIN} success on {sha} {tail}", "report"
    if state == "missing":
        return f"WAITING: no {VALIDATOR_LOGIN} verdict on {sha} yet {tail}", "waiting"
    return f"WAITING: {VALIDATOR_LOGIN} verdict on {sha} is {state} {tail}", "waiting"


def append_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)


def run(event_name: str, event: dict, repo: str, fetch: Fetch, out=print,
        summary: Callable[[str], None] | None = None) -> int:
    if event_name == "merge_group":
        prs = queue_prs(event, repo, fetch)
        if not prs:
            out("FAIL: no PR found in this merge queue entry (failing closed)")
            return 1
        bad = 0
        for n in prs:
            pr = fetch(f"/repos/{repo}/pulls/{n}")
            sha = str(((pr or {}).get("head") or {}).get("sha", "")) if isinstance(pr, dict) else ""
            if not re.fullmatch(r"[0-9a-f]{40}", sha):
                out(f"FAIL: PR #{n}: head sha not readable")
                bad += 1
                continue
            state = validator_state(repo, sha, fetch)
            ok = state == "success"
            out(f"{'OK' if ok else 'FAIL'}: PR #{n} head {sha[:12]}: {CONTEXT} {state}")
            bad += 0 if ok else 1
        if bad:
            out(f"Validator has not passed {bad} PR head(s) in this entry; it leaves the queue.")
            return 1
        return 0
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        sha = str((pr.get("head") or {}).get("sha", ""))
        state = validator_state(repo, sha, fetch) if re.fullmatch(r"[0-9a-f]{40}", sha) else "missing"
        line, title = pr_stage_line(sha, state)
        out(line)
        # an annotation, so the green check is not read as a pass
        out(f"::notice title=validator_pass {title}::{line}")
        if summary is not None:
            summary(f"### validator_pass (PR #{pr.get('number')})\n\n{line}\n")
        return 0
    out(f"nothing to check on {event_name}")
    return 0


def main() -> int:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not path or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        print("FAIL: GITHUB_EVENT_PATH and GITHUB_REPOSITORY are required")
        return 2
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    return run(os.environ.get("GITHUB_EVENT_NAME", ""), event, repo, http_fetch, summary=append_step_summary)


if __name__ == "__main__":
    raise SystemExit(main())
