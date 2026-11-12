"""Pick the CI test jobs that verify the files a change touched (card 1127).

Reads ci/test-select.toml. Each [[rule]] has paths (globs) and jobs. A
changed file runs the union of jobs from every rule it matches, and a file
that matches no rule runs nothing. "**" is zero or more directories.
An unknown job name, a broken map or a missing GITHUB_OUTPUT exits 1.

  python3 ci/test_select.py --github
      CI mode. The suites run once per change, on the pull request head:
      that is the run Validator's Pass measures. A pull_request diffs
      base...head and runs every job if any changed file selects one, else
      none. merge_group is a fingerprint check: if the queued commit's tree
      is the PR head's tree (refs/pull/N/head, N from the queue ref), that
      code already ran, so no job; if main moved under it, every job. Any
      other event, anything it cannot read, a failed diff or an empty diff
      runs every job.
  python3 ci/test_select.py --base REV [--head REV]
      Local mode. Prints the jobs the map selects, one per line.

A pyproject.toml whose only changed lines are `version = "..."` counts as
unchanged, so a release bump (that line plus CHANGELOG.md) selects nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "ci" / "test-select.toml"

# The ci.yml jobs gated on this selector. Every other ci job runs on every change.
KNOWN_JOBS = ("pytest_no_sql_run", "pytest_sql_run")

SHA_RE = re.compile(r"[0-9a-f]{40}")
ZERO_SHA = "0" * 40
VERSION_LINE_RE = re.compile(r'version = "[^"]*"')
# The suffix sha is the queue's base commit, not the PR head.
QUEUE_REF_RE = re.compile(r"(?:refs/heads/)?gh-readonly-queue/.+/pr-([0-9]+)-[0-9a-f]{40}")


class MapError(Exception):
    """The map file is unreadable, malformed or names an unknown job."""


Rules = list[tuple[list[str], list[str]]]


def match_glob(path: str, pattern: str) -> bool:
    """Match a repo-relative path. "**" is zero or more directories."""
    return _match(path.split("/"), pattern.split("/"))


def _match(path: list[str], pattern: list[str]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        if _match(path, pattern[1:]):
            return True
        return bool(path) and _match(path[1:], pattern)
    if not path or not _segment(path[0], pattern[0]):
        return False
    return _match(path[1:], pattern[1:])


def _segment(text: str, pattern: str) -> bool:
    """fnmatch for one path segment: "*" and "?" never cross a "/"."""
    i = j = 0
    star = mark = -1
    while i < len(text):
        if j < len(pattern) and pattern[j] != "*" and pattern[j] in ("?", text[i]):
            i += 1
            j += 1
        elif j < len(pattern) and pattern[j] == "*":
            star, mark = j, i
            j += 1
        elif star >= 0:
            mark += 1
            i, j = mark, star + 1
        else:
            return False
    while j < len(pattern) and pattern[j] == "*":
        j += 1
    return j == len(pattern)


def load_map(path: Path = MAP) -> Rules:
    """Return the rules. Every job a rule names must be in KNOWN_JOBS."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MapError(f"cannot read map: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise MapError(f"map is not valid toml: {exc}") from exc
    if set(data) - {"rule"}:
        raise MapError(f"unknown top-level keys: {sorted(set(data) - {'rule'})}")
    raw = data.get("rule")
    if not isinstance(raw, list) or not raw:
        raise MapError("map needs at least one [[rule]]")
    rules: Rules = []
    for n, rule in enumerate(raw, 1):
        if not isinstance(rule, dict) or set(rule) != {"paths", "jobs"}:
            raise MapError(f"rule {n} must have exactly paths and jobs")
        paths, jobs = rule["paths"], rule["jobs"]
        for name, value in (("paths", paths), ("jobs", jobs)):
            if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
                raise MapError(f"rule {n} {name} must be a non-empty list of strings")
        for job in jobs:
            if job not in KNOWN_JOBS:
                raise MapError(f"rule {n}: unknown job name: {job}")
        rules.append((paths, jobs))
    return rules


def select_jobs(paths: list[str], rules: Rules) -> set[str]:
    """Union of jobs from every rule a changed path matches."""
    chosen: set[str] = set()
    for path in paths:
        for globs, jobs in rules:
            if any(match_glob(path, glob) for glob in globs):
                chosen.update(jobs)
    return chosen


def changed_paths(base: str, head: str, separator: str = "...") -> list[str]:
    """git diff --name-only --no-renames -z, so a rename lists both sides."""
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}{separator}{head}", "--"],
        cwd=ROOT, check=False, capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        raise OSError(proc.stderr.decode("utf-8", "replace").strip() or "git diff failed")
    return [name for name in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if name]


def version_only(base: str, head: str, separator: str = "...") -> bool:
    """True when every changed pyproject.toml line is a `version = "..."` line.
    A failed diff, or one that adds or deletes the file, is not version-only."""
    proc = subprocess.run(
        ["git", "diff", "-U0", "--no-renames", "--no-color", f"{base}{separator}{head}", "--", "pyproject.toml"],
        cwd=ROOT, check=False, capture_output=True, timeout=60,
    )
    if proc.returncode != 0:
        return False
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    first_hunk = next((i for i, line in enumerate(lines) if line.startswith("@@")), len(lines))
    if any(line.startswith(("new file", "deleted file")) for line in lines[:first_hunk]):
        return False
    changed = [line[1:] for line in lines[first_hunk:] if line[:1] in "+-"]
    return bool(changed) and all(VERSION_LINE_RE.fullmatch(line) for line in changed)


def drop_version_bump(paths: list[str], base: str, head: str, separator: str = "...") -> list[str]:
    """paths, less a pyproject.toml whose only change is its version."""
    if "pyproject.toml" in paths and version_only(base, head, separator):
        return [p for p in paths if p != "pyproject.toml"]
    return paths


def pr_range(event: dict) -> tuple[str, str] | None:
    """(base, head) of a pull_request event, or None to run every job."""
    try:
        base, head = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"]
    except (KeyError, TypeError):
        return None
    if not all(isinstance(s, str) and SHA_RE.fullmatch(s) for s in (base, head)) or base == ZERO_SHA:
        return None
    return base, head


def _git(*args: str) -> str | None:
    """stdout of a git command run in ROOT, or None if it failed."""
    try:
        proc = subprocess.run(["git", *args], cwd=ROOT, check=False, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def tree_of(rev: str) -> str | None:
    return _git("rev-parse", "--verify", "--quiet", f"{rev}^{{tree}}")


def merge_group_selection(event: dict) -> tuple[set[str], str]:
    """No job when the queued commit's tree is the tested PR head's tree."""
    try:
        head_sha, head_ref = event["merge_group"]["head_sha"], event["merge_group"]["head_ref"]
    except (KeyError, TypeError):
        return set(KNOWN_JOBS), "merge_group: no head_sha or head_ref: every job"
    match = QUEUE_REF_RE.fullmatch(head_ref) if isinstance(head_ref, str) else None
    if match is None or not (isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha)):
        return set(KNOWN_JOBS), "merge_group: unreadable queue ref or sha: every job"
    number = match.group(1)
    if _git("fetch", "--no-tags", "--quiet", "origin", f"+refs/pull/{number}/head") is None:
        return set(KNOWN_JOBS), f"merge_group: cannot fetch PR #{number} head: every job"
    pr_head = _git("rev-parse", "--verify", "--quiet", "FETCH_HEAD^{commit}")
    queued, tested = tree_of(head_sha), tree_of(pr_head) if pr_head else None
    if queued is None or tested is None:
        return set(KNOWN_JOBS), f"merge_group: cannot read the trees for PR #{number}: every job"
    if queued != tested:
        return set(KNOWN_JOBS), f"merge_group: tree differs from PR #{number} head {pr_head[:12]}: every job"
    return set(), f"merge_group: tree matches PR #{number} head {pr_head[:12]}, already tested: no job"


def github_selection(rules: Rules, event_name: str, event: dict) -> tuple[set[str], str]:
    """The jobs to run for this event and a one-line reason."""
    if event_name == "merge_group":
        return merge_group_selection(event)
    span = pr_range(event) if event_name == "pull_request" else None
    if span is None:
        return set(KNOWN_JOBS), f"{event_name or 'no event'}: every job"
    base, head = span
    try:
        paths = changed_paths(base, head)
        if not paths:
            return set(KNOWN_JOBS), "empty diff: every job"
        paths = drop_version_bump(paths, base, head)
    except (OSError, subprocess.SubprocessError) as exc:
        return set(KNOWN_JOBS), f"diff failed ({exc}): every job"
    where = f"{len(paths)} changed file(s) in {base[:12]}...{head[:12]}"
    if not select_jobs(paths, rules):
        return set(), f"{where}: none selects a job"
    return set(KNOWN_JOBS), f"{where}: every job"


def write_output(chosen: set[str], dest: str) -> None:
    """Append one job=true|false line per known job."""
    with open(dest, "a", encoding="utf-8", newline="\n") as handle:
        for job in KNOWN_JOBS:
            handle.write(f"{job}={'true' if job in chosen else 'false'}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="select CI test jobs from changed paths")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--github", action="store_true", help="read the GitHub event; write GITHUB_OUTPUT")
    mode.add_argument("--base", help="diff base (local mode)")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--map", type=Path, default=MAP)
    args = parser.parse_args(argv)
    try:
        rules = load_map(args.map)
        if args.github:
            dest = os.environ.get("GITHUB_OUTPUT", "")
            if not dest:
                raise MapError("GITHUB_OUTPUT is not set")
            name = os.environ.get("GITHUB_EVENT_NAME", "")
            try:
                event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
            except (KeyError, OSError, ValueError):
                event = {}
            chosen, reason = github_selection(rules, name, event)
            write_output(chosen, dest)
            print(f"test_select: {reason}")
        else:
            paths = changed_paths(args.base, args.head)
            chosen = select_jobs(drop_version_bump(paths, args.base, args.head), rules)
    except (MapError, OSError) as exc:
        print(f"test_select: {exc}", file=sys.stderr)
        return 1
    for job in KNOWN_JOBS:
        print(f"{job}={'true' if job in chosen else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
