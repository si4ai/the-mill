"""Pick the CI test jobs that verify the files a change touched (card 1127).

Reads ci/test-select.toml. Each [[rule]] has paths (globs) and jobs. A
changed file runs the union of jobs from every rule it matches, and a file
that matches no rule runs nothing. "**" is zero or more directories.
An unknown job name, a broken map or a missing GITHUB_OUTPUT exits 1.

  python3 ci/test_select.py --github
      CI mode. pull_request diffs base...head, merge_group diffs
      base_sha..head_sha. Any other event, a malformed sha, a failed diff
      or an empty diff runs every job.
  python3 ci/test_select.py --base REV [--head REV]
      Local mode. Prints the selected jobs, one per line.
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


def event_range(event_name: str, event: dict) -> tuple[str, str, str] | None:
    """(base, head, separator) to diff, or None to run every job."""
    try:
        if event_name == "pull_request":
            base, head, sep = event["pull_request"]["base"]["sha"], event["pull_request"]["head"]["sha"], "..."
        elif event_name == "merge_group":
            # Two dots: everything the queued squash adds on top of its base.
            base, head, sep = event["merge_group"]["base_sha"], event["merge_group"]["head_sha"], ".."
        else:
            return None
    except (KeyError, TypeError):
        return None
    if not all(isinstance(s, str) and SHA_RE.fullmatch(s) for s in (base, head)) or base == ZERO_SHA:
        return None
    return base, head, sep


def github_selection(rules: Rules, event_name: str, event: dict) -> tuple[set[str], str]:
    """The jobs to run for this event and a one-line reason."""
    span = event_range(event_name, event)
    if span is None:
        return set(KNOWN_JOBS), f"{event_name or 'no event'}: every job"
    base, head, sep = span
    try:
        paths = changed_paths(base, head, sep)
    except (OSError, subprocess.SubprocessError) as exc:
        return set(KNOWN_JOBS), f"diff failed ({exc}): every job"
    if not paths:
        return set(KNOWN_JOBS), "empty diff: every job"
    return select_jobs(paths, rules), f"{len(paths)} changed file(s) in {base[:12]}{sep}{head[:12]}"


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
            chosen = select_jobs(changed_paths(args.base, args.head), rules)
    except (MapError, OSError) as exc:
        print(f"test_select: {exc}", file=sys.stderr)
        return 1
    for job in KNOWN_JOBS:
        print(f"{job}={'true' if job in chosen else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
