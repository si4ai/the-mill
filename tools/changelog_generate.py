"""Build CHANGELOG.md at version bump from merged PR Changelog sections (card 1120).

Usage:
  python tools/changelog_generate.py --version X.Y.Z --date YYYY-MM-DD
  python tools/changelog_generate.py --version X.Y.Z --date YYYY-MM-DD --dry-run

Ordinary PRs do not edit CHANGELOG.md. Each PR body keeps its usual sections
and adds a one-line ## Changelog section. At bump time this tool reads PRs
merged since the last release tag, uses that line (or the squash title if the
section is missing), writes them under a new current version heading in
New changes, and rolls the previous current block into Last changes (dropping
the prior Last). TBD is left as is.

It works for both landing flows, and a mix in one window. In the single-PR
flow, card PRs squash-merge to main and the tool reads each of those PRs. In
the release-fold flow, card PRs merge into release/X.Y.Z and one release PR
merges that branch to main: the tool collects the folded card PRs, not just
the release PR (the release PR itself is not an entry). Dedupe is by PR
number. The revert rule applies across both flows.

Reverts: a revert entry is "Reverts #N". GitHub's default Revert "..." title
or a "This reverts commit" body is a fallback. If #N merged in the same
window, both entries are dropped. If #N shipped in an earlier release, the
revert is listed.

The run is deterministic for a given from/to range and PR texts, and
idempotent: a second run with the same --version only refreshes that
version's bullets and does not roll Last again.

Exit 0 on success. Exit 2 on a bad argument. Exit 1 if CHANGELOG.md is
missing or does not have the three required sections, with a hint naming
this command.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"

SECTIONS = (
    "## TBD (upcoming)",
    "## New changes",
    "## Last changes",
)
DISCLAIMER = (
    "Upcoming changes are our current plan, not a promise; "
    "they can change or move at release time."
)

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHIPPED_HEAD = re.compile(r"^(\d+\.\d+\.\d+)(?:\s+\(([^)]+)\))?\s*$")
PR_IN_SUBJECT = re.compile(r"\(#(\d+)\)\s*$")
PR_HASH = re.compile(r"#(\d+)\b")
SECTION_HEAD = re.compile(r"^## (.+)$")
CHANGELOG_HEAD = re.compile(r"^##[ \t]+Changelog[ \t]*$", re.I)
NEXT_HEAD = re.compile(r"^##[ \t]+")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
REVERTS_LINE = re.compile(r"(?i)^reverts?\s+#(\d+)\s*$")
REVERT_TITLE = re.compile(r"""(?i)^Revert\s+["'](.+?)["']\s*$""")
REVERT_COMMIT = re.compile(r"(?i)This reverts commit ([0-9a-f]{7,40})\.")
BUMP_SUBJECT = re.compile(r"(?i)^the mill \d+\.\d+\.\d+:")
MERGE_PR = re.compile(r"(?i)^Merge pull request #(\d+) from \S+")
RELEASE_MERGE = re.compile(r"(?i)^Merge pull request #(\d+) from \S+/release/")
BULLET_PREFIX = re.compile(r"^[-*]\s+")

API_DEFAULT = os.environ.get("GITHUB_API_URL", "https://api.github.com")


@dataclass(frozen=True)
class MergedPR:
    """One landed change in the window, oldest first."""

    number: int | None
    title: str
    body: str
    sha: str = ""


def parse_changelog_section(body: str) -> str | None:
    """Return the one-line Changelog text, or None if the section is missing or empty."""
    if not body:
        return None
    text = HTML_COMMENT.sub("", body)
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if CHANGELOG_HEAD.match(ln):
            start = i + 1
            break
    if start is None:
        return None
    got: list[str] = []
    for ln in lines[start:]:
        if NEXT_HEAD.match(ln):
            break
        stripped = ln.strip()
        if stripped:
            got.append(BULLET_PREFIX.sub("", stripped))
    if not got:
        return None
    return got[0]


def pr_from_subject(subject: str) -> int | None:
    """PR number from a squash-merge subject '(#N)' at the end of the line."""
    m = PR_IN_SUBJECT.search(subject or "")
    return int(m.group(1)) if m else None


def pr_from_merge(subject: str) -> int | None:
    """PR number from a GitHub merge-commit subject."""
    m = MERGE_PR.match((subject or "").strip())
    return int(m.group(1)) if m else None


def is_release_merge_subject(subject: str) -> bool:
    """True for a merge of a release/* branch (the fold PR to main)."""
    return bool(RELEASE_MERGE.match((subject or "").strip()))


def is_release_pr(data: dict | None, subject: str = "") -> bool:
    """True when the PR is the release-fold PR, not a card PR."""
    if is_release_merge_subject(subject):
        return True
    if not data:
        return False
    head = str((data.get("head") or {}).get("ref") or "")
    if head.startswith("release/"):
        return True
    title = str(data.get("title") or "").strip()
    if BUMP_SUBJECT.match(title):
        return True
    return False


def pr_number_from_subject(subject: str) -> int | None:
    """PR number from a squash subject or a merge-commit subject."""
    return pr_from_merge(subject) or pr_from_subject(subject)


def revert_target(
    *,
    title: str,
    body: str,
    section: str | None,
    commit_subjects: dict[str, str] | None = None,
) -> int | None:
    """PR number this change reverts, or None if it is not a revert."""
    if section:
        m = REVERTS_LINE.match(section.strip())
        if m:
            return int(m.group(1))
        m = PR_HASH.search(section)
        if m and re.search(r"(?i)\breverts?\b", section):
            return int(m.group(1))
    m = REVERT_TITLE.match((title or "").strip())
    if m:
        quoted = m.group(1)
        n = pr_from_subject(quoted) or (int(p.group(1)) if (p := PR_HASH.search(quoted)) else None)
        if n is not None:
            return n
    m = REVERT_COMMIT.search(body or "")
    if m:
        sha = m.group(1)
        subjects = commit_subjects or {}
        for key, subj in subjects.items():
            if key.startswith(sha) or sha.startswith(key):
                n = pr_from_subject(subj)
                if n is not None:
                    return n
    return None


def is_revert_title(title: str) -> bool:
    return bool(REVERT_TITLE.match((title or "").strip()))


def entry_text(
    pr: MergedPR,
    *,
    commit_subjects: dict[str, str] | None = None,
) -> tuple[str, int | None]:
    """(bullet text without leading '- ', revert target or None)."""
    section = parse_changelog_section(pr.body)
    target = revert_target(
        title=pr.title, body=pr.body, section=section, commit_subjects=commit_subjects
    )
    if target is not None:
        return f"Reverts #{target}", target
    if section:
        return section, None
    title = (pr.title or "").strip()
    return title, None


def collect_bullets(
    prs: Sequence[MergedPR],
    *,
    commit_subjects: dict[str, str] | None = None,
) -> list[str]:
    """Build unique bullets, dropping a same-window pair of #N and its revert."""
    window = {p.number for p in prs if p.number is not None}
    prepared: list[tuple[int | None, str, int | None]] = []
    drop: set[int] = set()
    for pr in prs:
        text, target = entry_text(pr, commit_subjects=commit_subjects)
        prepared.append((pr.number, text, target))
        if target is not None and target in window:
            drop.add(target)
            if pr.number is not None:
                drop.add(pr.number)
    out: list[str] = []
    seen: set[str] = set()
    for number, text, _target in prepared:
        if number is not None and number in drop:
            continue
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def split_changelog(text: str) -> tuple[str, str, str]:
    """Return (tbd, new, last) bodies without their ## headings."""
    if not text.startswith("# Changelog\n"):
        raise ValueError("CHANGELOG.md must start with '# Changelog'")
    positions = [text.find(h) for h in SECTIONS]
    if any(p < 0 for p in positions) or positions != sorted(positions):
        raise ValueError(
            "CHANGELOG.md must have exactly three sections, newest first: "
            "TBD (upcoming), New changes, Last changes"
        )
    heads = [ln for ln in text.splitlines() if ln.startswith("## ")]
    if heads != list(SECTIONS):
        raise ValueError(f"unexpected ## headings in CHANGELOG.md: {heads}")
    tbd = text[positions[0] + len(SECTIONS[0]) : positions[1]].strip("\n")
    new = text[positions[1] + len(SECTIONS[1]) : positions[2]].strip("\n")
    last = text[positions[2] + len(SECTIONS[2]) :].strip("\n")
    if DISCLAIMER not in tbd:
        raise ValueError("TBD section is missing the upcoming-plan disclaimer")
    return tbd, new, last


def split_current(new: str) -> tuple[str, str]:
    """Split New changes into (unreleased lines, current shipped block)."""
    lines = new.splitlines()
    for i, ln in enumerate(lines):
        if SHIPPED_HEAD.match(ln.strip()):
            unreleased = "\n".join(lines[:i]).strip("\n")
            current = "\n".join(lines[i:]).strip("\n")
            return unreleased, current
    return new.strip("\n"), ""


def already_has_version(new: str, version: str) -> bool:
    body = new.lstrip("\n")
    first = body.splitlines()[0] if body else ""
    m = SHIPPED_HEAD.match(first.strip())
    return bool(m and m.group(1) == version)


def render_changelog(tbd: str, new: str, last: str) -> str:
    parts = ["# Changelog", "", SECTIONS[0], tbd.strip("\n"), "", SECTIONS[1], ""]
    new = new.strip("\n")
    if new:
        parts.append(new)
        parts.append("")
    parts.append(SECTIONS[2])
    last = last.strip("\n")
    if last:
        parts.append("")
        parts.append(last)
    text = "\n".join(parts).rstrip() + "\n"
    return text


def apply_rotation(
    text: str,
    *,
    version: str,
    date: str,
    bullets: Sequence[str],
) -> str:
    tbd, new, last = split_changelog(text)
    heading = f"{version} ({date})"
    bullet_block = "\n".join(f"- {b}" for b in bullets)
    new_section = heading + ("\n\n" + bullet_block if bullet_block else "")
    if already_has_version(new, version):
        _unreleased, rest = split_current(new)
        # rest starts with this version; drop it and keep nothing else under New
        return render_changelog(tbd, new_section, last)
    _unreleased, current = split_current(new)
    return render_changelog(tbd, new_section, current)


def last_release_tag(tip: str = "HEAD", *, cwd: Path | None = None) -> str:
    r = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", tip],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    r = subprocess.run(
        ["git", "tag", "-l", "v*", "--sort=-v:refname"],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        for tag in r.stdout.splitlines():
            tag = tag.strip()
            if not tag:
                continue
            chk = subprocess.run(
                ["git", "merge-base", "--is-ancestor", tag, tip],
                cwd=cwd or ROOT,
                capture_output=True,
            )
            if chk.returncode == 0:
                return tag
    raise RuntimeError(
        "no last release tag found; pass --from explicitly"
    )


def _git(args: Sequence[str], *, cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
    )
    return r.returncode, (r.stdout or "").strip()


def log_subjects(
    old: str,
    new: str,
    *,
    cwd: Path | None = None,
) -> list[tuple[str, str]]:
    """(sha, subject) from old..new, oldest first, all commits (not first-parent).

    Full history is required so a release-fold merge to main still exposes
    the card PRs that landed on the release branch.
    """
    code, out = _git(
        ["log", "--reverse", "--format=%H %s", f"{old}..{new}"], cwd=cwd
    )
    if code != 0:
        raise RuntimeError(f"git log {old}..{new} failed")
    rows: list[tuple[str, str]] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        sha, _, subject = ln.partition(" ")
        rows.append((sha, subject))
    return rows


def subjects_by_sha(old: str, new: str, *, cwd: Path | None = None) -> dict[str, str]:
    code, out = _git(["log", "--format=%H %s", f"{old}..{new}"], cwd=cwd)
    if code != 0:
        # include the parent window so a revert can name a commit in-range
        code, out = _git(["log", "--format=%H %s", new], cwd=cwd)
        if code != 0:
            return {}
    out_map: dict[str, str] = {}
    for ln in out.splitlines():
        if not ln.strip():
            continue
        sha, _, subject = ln.partition(" ")
        out_map[sha] = subject
    return out_map


Fetcher = Callable[[int], dict]


def fetch_pr_http(number: int, *, repo: str, token: str, api: str = API_DEFAULT) -> dict:
    """GET one pull request. Never logs the token."""
    url = f"{api.rstrip('/')}/repos/{repo}/pulls/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed API base)
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"failed to fetch PR #{number}: {type(exc).__name__}") from exc


def token_from_env() -> str:
    for key in (
        "GITHUB_TOKEN",
        "MILL_GITHUB_TOKEN_SI4AI",
        "MILL_GITHUB_TOKEN",
        "SI4AI_GITHUB_TOKEN",
    ):
        val = os.environ.get(key) or ""
        if val:
            return val
    return ""


def merged_prs_from_log(
    rows: Sequence[tuple[str, str]],
    *,
    fetch: Fetcher | None,
) -> list[MergedPR]:
    """Build a unique MergedPR list, oldest first, from git log rows.

    Walks every commit in the window (not first-parent) so card PRs that
    merged into a release branch are still found after that branch merges
    to main. Dedupes by PR number. Skips the release PR itself, version
    bump subjects, and commits with no PR number (feature-branch commits
    already covered by their merge or squash).
    """
    seen: set[int] = set()
    out: list[MergedPR] = []
    for sha, subject in rows:
        if BUMP_SUBJECT.match(subject or ""):
            continue
        if is_release_merge_subject(subject):
            n = pr_from_merge(subject)
            if n is not None:
                seen.add(n)
            continue
        number = pr_number_from_subject(subject)
        if number is None or number in seen:
            continue
        seen.add(number)
        title, body = subject, ""
        data: dict | None = None
        if fetch is not None:
            try:
                data = fetch(number)
                title = (data.get("title") or subject).strip()
                body = data.get("body") or ""
            except RuntimeError as exc:
                print(f"hint: {exc}; using the commit subject for #{number}", file=sys.stderr)
        if is_release_pr(data, subject):
            continue
        out.append(MergedPR(number=number, title=title, body=body, sha=sha))
    return out


def generate(
    text: str,
    *,
    version: str,
    date: str,
    prs: Sequence[MergedPR],
    commit_subjects: dict[str, str] | None = None,
) -> str:
    bullets = collect_bullets(prs, commit_subjects=commit_subjects)
    return apply_rotation(text, version=version, date=date, bullets=bullets)


def _fail_hint(message: str, version: str, date: str) -> int:
    cmd = f"python tools/changelog_generate.py --version {version} --date {date}"
    print(f"changelog-generate: {message}", file=sys.stderr)
    print(f"hint: fix the input, then run: {cmd}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="changelog_generate")
    p.add_argument("--version", required=True, help="new version, e.g. 0.8.11")
    p.add_argument("--date", required=True, help="release date YYYY-MM-DD")
    p.add_argument("--from", dest="changes_from", default="", help="old tag (default: last v* tag)")
    p.add_argument("--to", dest="changes_to", default="HEAD", help="new rev (default: HEAD)")
    p.add_argument("--changelog", default=str(CHANGELOG), help="path to CHANGELOG.md")
    p.add_argument("--repo", default=os.environ.get("MILL_GH_REPO", "si4ai/the-mill"))
    p.add_argument("--dry-run", action="store_true", help="print the new New-changes section; do not write")
    p.add_argument("--no-fetch", action="store_true", help="do not call the GitHub API; use squash titles only")
    args = p.parse_args(argv)

    if not VERSION_RE.match(args.version):
        print("changelog-generate: --version must be X.Y.Z", file=sys.stderr)
        return 2
    if not DATE_RE.match(args.date):
        print("changelog-generate: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2

    path = Path(args.changelog)
    if not path.is_file():
        return _fail_hint(f"{path} is missing", args.version, args.date)
    try:
        original = path.read_text(encoding="utf-8")
        split_changelog(original)
    except (OSError, ValueError) as exc:
        return _fail_hint(str(exc), args.version, args.date)

    cwd = path.resolve().parent if (path.resolve().parent / ".git").exists() else ROOT
    # worktree: .git may be a file
    if not (cwd / ".git").exists() and (ROOT / ".git").exists():
        cwd = ROOT
    try:
        old = args.changes_from or last_release_tag(args.changes_to, cwd=cwd)
        rows = log_subjects(old, args.changes_to, cwd=cwd)
        commit_subjects = subjects_by_sha(old, args.changes_to, cwd=cwd)
        # extend with enough history to resolve "This reverts commit" SHAs
        more = subjects_by_sha(f"{old}^", old, cwd=cwd) if old else {}
        commit_subjects = {**more, **commit_subjects}
    except RuntimeError as exc:
        return _fail_hint(str(exc), args.version, args.date)

    fetch: Fetcher | None = None
    if not args.no_fetch:
        token = token_from_env()
        repo = args.repo

        def fetch(number: int, _repo: str = repo, _token: str = token) -> dict:
            return fetch_pr_http(number, repo=_repo, token=_token)

    prs = merged_prs_from_log(rows, fetch=fetch)
    try:
        updated = generate(
            original,
            version=args.version,
            date=args.date,
            prs=prs,
            commit_subjects=commit_subjects,
        )
        split_changelog(updated)
    except ValueError as exc:
        return _fail_hint(str(exc), args.version, args.date)

    if args.dry_run:
        _tbd, new, _last = split_changelog(updated)
        sys.stdout.write(new if new.endswith("\n") else new + "\n")
        return 0

    if updated != original:
        path.write_text(updated, encoding="utf-8")
        print(f"changelog-generate: wrote {path} for {args.version} ({args.date})")
    else:
        print(f"changelog-generate: {path} already matches {args.version} ({args.date})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
