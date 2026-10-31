"""PR-head cold measure starter (card 813 / F212).

Builds a kit from a PR head tree so a tester desk can run the gardener cold
measure (letter 3623) before merge, without installing over the live office
mill.

  python tools/cold_measure_head.py --out ~/cold-kit --stage-only
  python tools/cold_measure_head.py --out ~/cold-kit --install
  python tools/cold_measure_head.py --verdict-file BODY.txt --pr N --head SHA \\
      --join-sha J --skill-sha S --task ROW --join-row ROW --leave-row ROW

`--install` builds the wheel from the head and pip-installs it into
`<out>/venv` only. It never targets the live mill on PATH, and it refuses
when that mill already lives under `<out>` (so it cannot rmtree a live
venv). The tester is an agent desk; CI cannot seat it, so this is not a
required GitHub check.

Verdict sink: the tester replies on the PR's mill thread to the opener, the
merge partner and validator, then leaves a one-line PR comment naming that
letter id. Use `--verdict-file` to write the letter body.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

LIVE_MARKER = ".live-mill-marker"
TASK_TEXT = (
    "What is desk grok-tui doing right now, on which letter or card, "
    "and is anyone waiting on it? Answer in three lines and list the "
    "commands you ran."
)
RECIPE = """# PR-head cold measure (card 813)

Same recipe as the post-ship cold measure (letters 3390 on 3385, 3198 on 3194).
Not the ct1022 battery. Not a REMEASURE TOY pass.

## Kit
This directory holds `JOIN.md` and `mill-desk/SKILL.md` from the PR head,
plus `manifest.json` (content shas). With `--install`, `<out>/venv` has the
head wheel; put that venv's `bin` first on PATH for the tester. Do not
install over the live office mill.

## Desk
One fresh `cold-*` desk woken through room barker (`--wake-on addressed`).
Give the tester only this kit's JOIN.md + mill-desk SKILL. No other skills.

## Task (letter 2531, unchanged)
{task}

## Score
Record against the last live run (3390: task 1/0/0/1s/1.4KB, join 9/0/0/31s,
leave 1/0/0):
- task / join / leave rows: commands / wrong guesses / retries / seconds / bytes
- JOIN.md sha and mill-desk SKILL sha (see manifest.json)

## Verdict sink
Reply on the PR's mill thread to the PR opener, the merge partner and
validator with those rows. Leave a one-line PR comment that names the letter
id. Mill stays the record.
""".format(task=TASK_TEXT)


def repo_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__).resolve().parent.parent).resolve()
    if not (here / "pyproject.toml").is_file():
        raise SystemExit("cold_measure_head: need a the-mill checkout (missing pyproject.toml)")
    return here


def content_sha(path: Path) -> str:
    data = path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:12]


def git_sha(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return (out.stdout or "").strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def git_dirty(root: Path) -> bool:
    try:
        out = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "-C", str(root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        return bool((out.stdout or "").strip())
    except (OSError, subprocess.SubprocessError):
        return False


def mill_on_path() -> Path | None:
    mill = shutil.which("mill")
    return Path(mill).resolve() if mill else None



def mill_under(path: Path) -> bool:
    """True when the PATH mill binary lives under path (symlinks resolved)."""
    mill = mill_on_path()
    if mill is None:
        return False
    try:
        target = path.resolve()
    except OSError:
        return False
    try:
        mill.relative_to(target)
        return True
    except ValueError:
        return False


def is_live_mill(path: Path) -> bool:
    """True when out would clobber a live mill install tree."""
    p = path.resolve()
    if (p / LIVE_MARKER).is_file():
        return True
    mill = mill_on_path()
    if mill is None:
        return False
    mill_bin = mill.parent
    # Refuse out inside the mill bin dir, or equal to its parent (~/.local).
    try:
        p.relative_to(mill_bin)
        return True
    except ValueError:
        pass
    if p == mill_bin.parent:
        return True
    # Refuse when the live mill binary already lives under out
    # (e.g. out/venv/bin/mill and --out out -> would rmtree the live venv).
    try:
        mill.relative_to(p)
        return True
    except ValueError:
        pass
    return False


def stage_kit(root: Path, out: Path, *, refuse_live: bool = True, allow_dirty: bool = False) -> dict:
    root = root.resolve()
    out = out.resolve()
    if refuse_live and is_live_mill(out):
        raise SystemExit(2)
    dirty = git_dirty(root)
    if dirty and not allow_dirty:
        raise SystemExit("cold_measure_head: refuse dirty checkout (pass --allow-dirty to override)")
    join = root / "docs" / "JOIN.md"
    skill = root / "docs" / "protocol" / "skill.md"
    for p in (join, skill):
        if not p.is_file():
            raise SystemExit(f"cold_measure_head: missing {p}")
    out.mkdir(parents=True, exist_ok=True)
    if (out / LIVE_MARKER).is_file() and refuse_live:
        raise SystemExit(2)
    shutil.copy2(join, out / "JOIN.md")
    desk = out / "mill-desk"
    desk.mkdir(exist_ok=True)
    shutil.copy2(skill, desk / "SKILL.md")
    # Lock 3623: JOIN.md + mill-desk SKILL only (no other skills in the kit).
    manifest = {
        "head_sha": git_sha(root),
        "join_sha": content_sha(join),
        "skill_sha": content_sha(skill),
        "dirty": dirty,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "recipe.md").write_text(RECIPE, encoding="utf-8")
    return manifest


def newest(dist: Path, pattern: str) -> Path:
    hits = sorted(dist.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not hits:
        raise SystemExit(f"cold_measure_head: no {pattern} in dist/")
    return hits[-1]


def build_and_install(root: Path, out: Path, *, recreate: bool = False) -> Path:
    """Build the head wheel and pip-install into out/venv. Never the live mill."""
    if is_live_mill(out):
        raise SystemExit(2)
    out.mkdir(parents=True, exist_ok=True)
    venv_dir = out / "venv"
    # is_symlink first: a link to a live tree must refuse with rc 2, not OSError.
    if venv_dir.is_symlink() or venv_dir.exists():
        if mill_under(venv_dir) or is_live_mill(out):
            raise SystemExit(2)
        if not recreate:
            raise SystemExit(
                "cold_measure_head: refuse to replace existing <out>/venv "
                "(pass --recreate to rebuild it)"
            )
        if venv_dir.is_symlink():
            venv_dir.unlink()
        else:
            shutil.rmtree(venv_dir)
    venv.EnvBuilder(with_pip=True).create(str(venv_dir))
    py = venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run([str(py), "-m", "pip", "install", "-q", "build"], check=True, cwd=str(root), env=env)
    subprocess.run([str(py), "-m", "build"], check=True, cwd=str(root), env=env)
    whl = newest(root / "dist", "*.whl")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--force-reinstall", str(whl.resolve())],
        check=True,
        cwd=str(out),
        env=env,
    )
    return whl


def verdict_body(
    *,
    pr: int,
    head_sha: str,
    join_sha: str,
    skill_sha: str,
    task_row: str,
    join_row: str,
    leave_row: str,
    verd: str,
    opener: str,
    partner: str,
) -> str:
    if verd not in ("GREEN", "RED"):
        raise SystemExit("cold_measure_head: --verd must be GREEN or RED")
    body = (
        f"PR-head cold measure on PR #{pr} ({head_sha}): {verd}.\n"
        f"JOIN.md sha {join_sha}; mill-desk SKILL sha {skill_sha}.\n"
        f"- task (2531 doing): {task_row}\n"
        f"- join: {join_row}\n"
        f"- leave: {leave_row}\n"
        f"To: {opener} (opener), {partner} (merge partner), validator.\n"
        f"Mill stays the record; name this letter id in a one-line PR comment."
    )
    if len(body) > 2000:
        body = body[:1997] + "..."
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path, default=None, help="PR head checkout (default: this repo)")
    p.add_argument("--out", type=Path, default=None, help="kit directory (JOIN + skill + recipe)")
    p.add_argument("--stage-only", action="store_true", help="copy JOIN/skill/recipe; do not build or pip install")
    p.add_argument("--install", action="store_true", help="build head wheel into <out>/venv (never live mill)")
    p.add_argument("--recreate", action="store_true", help="with --install, replace an existing <out>/venv")
    p.add_argument("--allow-dirty", action="store_true", help="allow staging from a dirty checkout")
    p.add_argument("--verdict-file", type=Path, default=None, help="write a mill letter body for the verdict sink")
    p.add_argument("--pr", type=int, default=0)
    p.add_argument("--head", default="")
    p.add_argument("--join-sha", default="")
    p.add_argument("--skill-sha", default="")
    p.add_argument("--task", default="", help="task score row commands/wrong/retries/seconds/bytes")
    p.add_argument("--join-row", default="")
    p.add_argument("--leave-row", default="")
    p.add_argument("--verd", default="GREEN", choices=("GREEN", "RED"), help="GREEN or RED")
    p.add_argument("--opener", default="builder")
    p.add_argument("--partner", default="grok-tui")
    args = p.parse_args(argv)

    if args.verdict_file is not None:
        if not (args.pr and args.head and args.join_sha and args.skill_sha and args.task and args.join_row and args.leave_row):
            print(
                "cold_measure_head: --verdict-file needs --pr --head --join-sha "
                "--skill-sha --task --join-row --leave-row",
                file=sys.stderr,
            )
            return 2
        body = verdict_body(
            pr=args.pr,
            head_sha=args.head,
            join_sha=args.join_sha,
            skill_sha=args.skill_sha,
            task_row=args.task,
            join_row=args.join_row,
            leave_row=args.leave_row,
            verd=args.verd,
            opener=args.opener,
            partner=args.partner,
        )
        args.verdict_file.write_text(body, encoding="utf-8")
        print(f"wrote {args.verdict_file} ({len(body)} bytes)")
        return 0

    if args.out is None:
        print("cold_measure_head: --out DIR is required (kit directory)", file=sys.stderr)
        return 2
    root = repo_root(args.root)
    if is_live_mill(args.out.resolve()):
        print("cold_measure_head: refuse --out that is the live mill (marker, PATH mill under out, or mill parent)", file=sys.stderr)
        return 2
    manifest = stage_kit(root, args.out, refuse_live=True, allow_dirty=args.allow_dirty)
    print(json.dumps(manifest, indent=2))
    if args.install:
        if args.stage_only:
            print("cold_measure_head: --install ignored with --stage-only", file=sys.stderr)
        else:
            whl = build_and_install(root, args.out, recreate=args.recreate)
            print(f"installed {whl.name} into {args.out / 'venv'} (not live mill)")
    elif not args.stage_only:
        print("staged kit only; pass --install to build the head into <out>/venv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
