"""Cheap deterministic checks before a Validator Pass ask (card 959 / F-precheck).

  python tools/precheck.py [<head>]
  tools/precheck.sh [<head>]
  make precheck

Exit 0 prints one line: precheck OK <sha>
Exit 1 prints one line per finding: file:line rule message
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# id-like columns that may stay non-BIGINT (same reasons as test_schema_invariants_868).
ID_TYPE_OK = {
    ("mill_invite", "key_id"),
    ("mill_invite_join", "key_id"),
    ("mill_invite_join", "party_id"),
}

DDL_PATHS = (
    "agent_coord/server/sql/tables.sql",
    "docs/requirements/beta/beta_ddl.sql",
)

GONE = frozenset(
    {
        "mail",
        "mcp",
        "mcp-config",
        "leftover",
        "leftover-done",
        "heartbeat",
        "sync",
        "done",
        "spend",
        "issues",
        "here",
        "presence",
        "acquire",
        "yield",
        "open",
        "roster",  # not a CLI command; mill connected ROSTER / send roster
    }
)

MILL_VERB = re.compile(
    r"(?:^|[\"'\s]|Next:\s*|run:\s*)mill\s+([a-z][a-z0-9-]*)\b",
    re.M,
)
PR_CITE = re.compile(r"(?<!\w)#(\d+)\b")
CARD_CITE = re.compile(r"\bcard\s+(\d+)\b", re.I)
F_NUM_FILE = re.compile(r"^F(\d+)\w*\.md$")
F_ID_LINE = re.compile(r"^\| ((?:S-\d+|F\d+\w*|F-[a-z0-9]+(?:-[a-z0-9]+)*)) ")
COL_ID = re.compile(
    r"(?P<table>CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(?P<tname>\w+)`?)"
    r"|(?P<col>^\s*`?(?P<cname>\w+)`?\s+(?P<ctype>[A-Za-z]+(?:\s+UNSIGNED)?))",
    re.M | re.I,
)
SHIPPED_HEAD = re.compile(r"^(\d+\.\d+\.\d+)(?:\s+\(([^)]+)\))?\s*$")
SECTION = re.compile(r"^## (.+)$")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str


def format_finding(f: Finding) -> str:
    return f"{f.path}:{f.line} {f.rule} {f.message}"


def ok_line(sha: str) -> str:
    return f"precheck OK {sha}"


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _rev_parse(head: str, cwd: Path = ROOT) -> str:
    return _git("rev-parse", head, cwd=cwd)


def check_changelog(path: Path, base_text: str = "") -> list[Finding]:
    """New bullets cite a card (not only a PR); shipped version heads have dates."""
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    section = ""
    under_shipped = False
    shipped_dated = True
    shipped_line = 0
    shipped_name = ""
    for i, ln in enumerate(text.splitlines(), 1):
        m = SECTION.match(ln)
        if m:
            section = m.group(1)
            under_shipped = False
            continue
        if section == "Last changes":
            sm = SHIPPED_HEAD.match(ln.strip())
            if sm:
                under_shipped = True
                shipped_name = sm.group(1)
                shipped_line = i
                shipped_dated = bool(sm.group(2))
                if not shipped_dated:
                    findings.append(
                        Finding(
                            path.as_posix() if path.is_absolute() else str(path),
                            i,
                            "changelog-date",
                            f"shipped heading {shipped_name} needs a date",
                        )
                    )
                continue
        if not ln.strip().startswith("- "):
            continue
        # flag PR-only cites on any bullet under New changes / TBD (unreleased)
        if section in ("New changes", "TBD (upcoming)") or (
            section == "Last changes" and under_shipped
        ):
            has_pr = bool(PR_CITE.search(ln))
            has_card = bool(CARD_CITE.search(ln))
            if has_pr and not has_card:
                findings.append(
                    Finding(
                        path.as_posix() if path.is_absolute() else str(path),
                        i,
                        "changelog-card",
                        "cite card N, not only a PR number",
                    )
                )
            # new lines under a dated shipped heading in Last are fine; under New
            # without a card is also wrong when the bullet is brand new vs base
            if section in ("New changes", "TBD (upcoming)") and not has_card and ln.strip().startswith("- "):
                # only when the line is new vs base (or base empty = all new)
                if not base_text or ln not in base_text:
                    if not has_pr:  # already flagged PR-only above; still need a card
                        findings.append(
                            Finding(
                                path.as_posix() if path.is_absolute() else str(path),
                                i,
                                "changelog-card",
                                "unreleased bullet must cite card N",
                            )
                        )
    return findings


def check_frows(root: Path, new_paths: list[str] | None = None) -> list[Finding]:
    """Flag new numbered F*.md files and duplicate F/S ids across row files."""
    findings: list[Finding] = []
    reg = root / "docs" / "security" / "regression"
    if not reg.is_dir():
        return findings
    if new_paths is None:
        new_paths = []
    for rel in new_paths:
        name = Path(rel).name
        if F_NUM_FILE.match(name):
            findings.append(
                Finding(
                    rel,
                    1,
                    "frow-numbered",
                    f"new row must be F-<slug>.md, not {name}",
                )
            )
    seen: dict[str, str] = {}
    for path in sorted(reg.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            m = F_ID_LINE.match(ln)
            if not m:
                continue
            fid = m.group(1)
            rel = path.relative_to(root).as_posix() if root in path.parents or path.is_relative_to(root) else path.as_posix()
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.as_posix()
            if fid in seen:
                findings.append(
                    Finding(
                        rel,
                        i,
                        "frow-dup",
                        f"duplicate id {fid} also in {seen[fid]}",
                    )
                )
            else:
                seen[fid] = rel
            break
    return findings


def _cli_commands(root: Path) -> set[str]:
    """Command names from the mill parser; falls back to a static set on import fail."""
    try:
        sys.path.insert(0, str(root))
        from agent_coord.__main__ import _build_parser  # type: ignore

        p = _build_parser()
        for act in p._actions:
            if getattr(act, "choices", None) and isinstance(act.choices, dict):
                return set(act.choices) | {"help"}
    except Exception:
        pass
    # minimal fallback used only when the pack is not importable (unit tests)
    return {
        "connect",
        "join",
        "inbox",
        "send",
        "reply",
        "todo",
        "claim",
        "note",
        "pass",
        "hold",
        "drop",
        "label",
        "create",
        "add",
        "remove",
        "mark",
        "mail-thread",
        "connected",
        "install",
        "update",
        "route",
        "watch",
        "trail",
        "score",
        "invite",
        "help",
        "briefing",
    }


def check_mill_verbs(root: Path, paths: list[str] | None = None) -> list[Finding]:
    """Every command-shaped mill <verb> in hints/docs is a real CLI command.

    Matches backtick `mill verb`, line-start, and Next:/run: forms. Prose like
    "a mill roster" is ignored. When paths is None, returns no findings (caller
    passes the diff); unit tests pass an explicit list.
    """
    findings: list[Finding] = []
    commands = _cli_commands(root)
    if paths is None:
        return findings
    patterns = (
        re.compile(r"`mill\s+([a-z][a-z0-9-]*)"),
        re.compile(r"(?:^|\bNext:\s*|\brun:\s*)mill\s+([a-z][a-z0-9-]*)"),
        re.compile(r"['\"](?:Next:\s*)?mill\s+([a-z][a-z0-9-]*)"),
    )
    for rel in paths:
        path = root / rel
        if not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, ln in enumerate(body.splitlines(), 1):
            seen: set[str] = set()
            for pat in patterns:
                for m in pat.finditer(ln):
                    verb = m.group(1)
                    if verb in seen or verb in commands:
                        continue
                    seen.add(verb)
                    findings.append(
                        Finding(rel, i, "mill-verb", f"mill {verb} is not a CLI command")
                    )
    return findings


def check_schema_ids(root: Path) -> list[Finding]:
    """DDL id columns must be BIGINT UNSIGNED (allowlisted exceptions)."""
    findings: list[Finding] = []
    for rel in DDL_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        table = ""
        for i, ln in enumerate(text.splitlines(), 1):
            tm = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(\w+)`?", ln, re.I)
            if tm:
                table = tm.group(1)
                continue
            cm = re.match(
                r"^\s*`?(\w+)`?\s+([A-Za-z]+(?:\s+UNSIGNED)?)\b",
                ln,
                re.I,
            )
            if not cm or not table:
                continue
            col, ctype = cm.group(1), re.sub(r"\s+", " ", cm.group(2)).upper()
            if col != "id" and not col.endswith("_id") and col != "opt":
                continue
            if (table, col) in ID_TYPE_OK:
                continue
            if ctype != "BIGINT UNSIGNED":
                findings.append(
                    Finding(
                        rel,
                        i,
                        "schema-id",
                        f"{table}.{col} is {ctype}, want BIGINT UNSIGNED",
                    )
                )
    return findings


def check_pack_fresh(root: Path, sha: str, base: str = "origin/main") -> list[Finding]:
    """check_pack dist + --commits + --head-message on a fresh single-branch clone.

    ``base`` is resolved to a sha in ``root`` first: the clone only maps the
    checked-out branch, so a ref such as origin/main does not exist there.
    """
    findings: list[Finding] = []
    try:
        base_sha = _rev_parse(f"{base}^{{commit}}", cwd=root)
    except subprocess.CalledProcessError as e:
        findings.append(
            Finding(
                "tools/check_pack.py",
                1,
                "check-pack",
                f"base {base} does not resolve: {e.stderr[-200:] if e.stderr else e}",
            )
        )
        return findings
    with tempfile.TemporaryDirectory(prefix="precheck-pack-") as tmp:
        tmp_p = Path(tmp)
        clone = tmp_p / "src"
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "-q",
                    "--single-branch",
                    "--no-tags",
                    str(root),
                    str(clone),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "checkout", "-q", "--detach", sha],
                cwd=clone,
                check=True,
                capture_output=True,
                text=True,
            )
            # --commits needs the base commit in the clone; fetch it by sha
            # when the single-branch clone did not bring it along.
            has_base = subprocess.run(
                ["git", "cat-file", "-e", f"{base_sha}^{{commit}}"],
                cwd=clone,
                capture_output=True,
            )
            if has_base.returncode:
                subprocess.run(
                    ["git", "fetch", "-q", "--no-tags", "origin", base_sha],
                    cwd=clone,
                    check=True,
                    capture_output=True,
                    text=True,
                )
        except subprocess.CalledProcessError as e:
            findings.append(
                Finding(
                    "tools/check_pack.py",
                    1,
                    "check-pack",
                    f"fresh clone failed: {e.stderr[-200:] if e.stderr else e}",
                )
            )
            return findings
        # build
        dist = clone / "dist"
        env = {**os.environ, "SOURCE_DATE_EPOCH": _git("log", "-1", "--format=%ct", sha, cwd=root)}
        built = subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist)],
            cwd=clone,
            env=env,
            capture_output=True,
            text=True,
        )
        if built.returncode:
            findings.append(
                Finding(
                    "dist",
                    1,
                    "check-pack",
                    f"build failed (exit {built.returncode})",
                )
            )
            return findings
        for args in (
            ["dist"],
            ["--head-message"],
            ["--commits", f"{base_sha}..{sha}"],
        ):
            run = subprocess.run(
                [sys.executable, "tools/check_pack.py", *args],
                cwd=clone,
                capture_output=True,
                text=True,
                env={**os.environ, "CI": "true", "MILL_PRIVATE_NAMES_REQUIRED": "0"},
            )
            if run.returncode:
                msg = (run.stdout or run.stderr or "check_pack failed").strip().splitlines()
                findings.append(
                    Finding(
                        "tools/check_pack.py",
                        1,
                        "check-pack",
                        f"{' '.join(args)}: {msg[-1][:200] if msg else 'failed'}",
                    )
                )
    return findings


def check_targeted_pytest(root: Path, base: str = "origin/main") -> list[Finding]:
    """Run pytest on test files the diff touches."""
    findings: list[Finding] = []
    try:
        merge_base = _git("merge-base", "HEAD", base, cwd=root)
        diff = _git("diff", "--name-only", merge_base, "HEAD", cwd=root)
    except subprocess.CalledProcessError:
        return findings
    tests = sorted(
        {
            p
            for p in diff.splitlines()
            if p.startswith("tests/") and p.endswith(".py") and Path(root, p).is_file()
        }
    )
    # Wall surface validators need tools/wall-validators (npm ci). Precheck stays
    # cheap: pytest_no_sql already covers them with Node installed.
    wall_npm = root / "tools" / "wall-validators" / "node_modules"
    if not wall_npm.is_dir():
        tests = [p for p in tests if not p.startswith("tests/wall/")]
    if not tests:
        return findings
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", *tests],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if run.returncode:
        tail = (run.stdout or run.stderr or "pytest failed").strip().splitlines()
        findings.append(
            Finding(
                tests[0],
                1,
                "pytest",
                f"targeted pytest failed ({len(tests)} files): {tail[-1][:160] if tail else 'fail'}",
            )
        )
    return findings


def _new_paths(root: Path, base: str = "origin/main") -> list[str]:
    try:
        merge_base = _git("merge-base", "HEAD", base, cwd=root)
        out = _git("diff", "--name-only", "--diff-filter=A", merge_base, "HEAD", cwd=root)
        return [ln for ln in out.splitlines() if ln]
    except subprocess.CalledProcessError:
        return []


def run(
    root: Path = ROOT,
    head: str = "HEAD",
    base: str = "origin/main",
    skip_pack: bool = False,
    skip_pytest: bool = False,
) -> tuple[int, list[str]]:
    sha = _rev_parse(head, cwd=root)
    findings: list[Finding] = []
    cl = root / "CHANGELOG.md"
    if cl.is_file():
        base_text = ""
        try:
            base_text = _git("show", f"{base}:CHANGELOG.md", cwd=root)
        except subprocess.CalledProcessError:
            pass
        findings.extend(check_changelog(cl, base_text=base_text))
    findings.extend(check_frows(root, new_paths=_new_paths(root, base)))
    changed: list[str] = []
    try:
        mb = _git("merge-base", "HEAD", base, cwd=root)
        changed = [ln for ln in _git("diff", "--name-only", mb, "HEAD", cwd=root).splitlines() if ln]
    except subprocess.CalledProcessError:
        changed = []
    # Prefer the release-train check_code_commands when present (card 734);
    # otherwise scan the diff with the lightweight mill-verb checker.
    code_cmd = root / "tools" / "check_code_commands.py"
    if code_cmd.is_file():
        run_cc = subprocess.run(
            [sys.executable, str(code_cmd)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if run_cc.returncode:
            for ln in (run_cc.stdout or run_cc.stderr or "failed").splitlines():
                if not ln.strip():
                    continue
                parts = ln.split(chr(9))
                where = parts[1] if len(parts) > 1 else "tools/check_code_commands.py:1"
                why = parts[-1] if parts else "failed"
                if ":" in where:
                    fpath, _, rest = where.partition(":")
                    line_s, _, _ = rest.partition(":")
                    try:
                        line_n = int(line_s)
                    except ValueError:
                        line_n = 1
                        fpath = where
                else:
                    fpath, line_n = where, 1
                findings.append(Finding(fpath, line_n, "mill-verb", why[:200]))
    else:
        findings.extend(check_mill_verbs(root, paths=changed))
    findings.extend(check_schema_ids(root))
    if not skip_pack:
        findings.extend(check_pack_fresh(root, sha, base=base))
    if not skip_pytest:
        findings.extend(check_targeted_pytest(root, base=base))
    # also run existing doc/skill checks when present (cheap, no network)
    for script, rule in (
        ("tools/check_doc_commands.py", "doc-commands"),
        ("tools/check_skill_copy.py", "skill-copy"),
    ):
        if not (root / script).is_file():
            continue
        run = subprocess.run(
            [sys.executable, script],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if run.returncode:
            msg = (run.stdout or run.stderr or "failed").strip().splitlines()
            findings.append(
                Finding(
                    script,
                    1,
                    rule,
                    msg[-1][:200] if msg else "failed",
                )
            )
    lines = [format_finding(f) for f in findings]
    if findings:
        return 1, lines
    return 0, [ok_line(sha)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cheap pre-Pass checks (card 959)")
    ap.add_argument("head", nargs="?", default="HEAD")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--skip-pack", action="store_true")
    ap.add_argument("--skip-pytest", action="store_true")
    args = ap.parse_args(argv)
    code, lines = run(
        ROOT,
        head=args.head,
        base=args.base,
        skip_pack=args.skip_pack,
        skip_pytest=args.skip_pytest,
    )
    for ln in lines:
        print(ln)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
