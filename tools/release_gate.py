"""Post-merge release gate with tree-equal fast path (card 960 / F-gate-fastpath).

  python tools/release_gate.py --passed <sha> [--head <sha>] [--dist DIR]

When HEAD's tree equals the passed release-branch tree: build once, check the
version, byte-compare dist/ against that build (fast path).
When the trees differ: run the full gate (check_pack + check_repro + twine).

Exit 0 prints: gate OK fast|full <sha>
Exit non-zero prints one finding line each.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r'(?m)^version\s*=\s*["\']([^"\']+)["\']')


def ok_line(sha: str, path: str) -> str:
    return f"gate OK {path} {sha}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def trees_equal(repo: Path, a: str, b: str) -> bool:
    ta = _git(repo, "rev-parse", f"{a}^{{tree}}")
    tb = _git(repo, "rev-parse", f"{b}^{{tree}}")
    return ta == tb


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sums(dist: Path) -> dict[str, str]:
    return {
        p.name: _sha256(p)
        for p in sorted(dist.iterdir())
        if p.name.endswith((".whl", ".tar.gz"))
    }


def _version(repo: Path, sha: str) -> str:
    text = _git(repo, "show", f"{sha}:pyproject.toml")
    m = VERSION_RE.search(text)
    if not m:
        raise SystemExit("pyproject.toml: no version")
    return m.group(1)


def default_build_once(repo: Path, sha: str, out: Path) -> str:
    """Build sha into out/; return the version string."""
    ver = _version(repo, sha)
    epoch = _git(repo, "log", "-1", "--format=%ct", sha)
    src = out.parent / "src"
    if src.exists():
        shutil.rmtree(src)
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", "--no-checkout", str(repo), str(src)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-q", "--detach", sha],
        cwd=src,
        check=True,
        capture_output=True,
    )
    env = {**os.environ, "SOURCE_DATE_EPOCH": epoch}
    done = subprocess.run(
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out)],
        cwd=src,
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode:
        sys.stderr.write((done.stdout or "")[-2000:] + (done.stderr or "")[-2000:])
        raise SystemExit(f"build failed (exit {done.returncode})")
    return ver


def run_fast_gate(
    repo: Path,
    sha: str,
    dist: Path | None,
    build_once=None,
) -> tuple[int, list[str]]:
    """Build once, check version naming, byte-compare against dist/ when given."""
    build_once = build_once or default_build_once
    lines: list[str] = []
    with tempfile.TemporaryDirectory(prefix="gate-fast-") as tmp:
        out = Path(tmp) / "dist"
        out.mkdir()
        ver = build_once(repo, sha, out)
        want = {
            f"the_mill-{ver}-py3-none-any.whl",
            f"the_mill-{ver}.tar.gz",
        }
        got = set(_sums(out))
        if got != want:
            lines.append(f"dist:1 version-files want {sorted(want)} got {sorted(got)}")
            return 1, lines
        if dist is not None:
            if not dist.is_dir():
                lines.append(f"{dist}:1 dist missing dist directory")
                return 1, lines
            dsums = _sums(dist)
            bsums = _sums(out)
            if set(dsums) != set(bsums):
                lines.append(
                    f"dist:1 byte-compare file set differs: dist={sorted(dsums)} build={sorted(bsums)}"
                )
                return 1, lines
            for name, digest in bsums.items():
                if dsums.get(name) != digest:
                    lines.append(f"dist/{name}:1 byte-compare mismatch vs gate build")
            if lines:
                return 1, lines
        lines.append(f"gate fast: tree match, version {ver}, build ok")
    return 0, lines


def run_full_gate(repo: Path, sha: str, dist: Path | None = None) -> tuple[int, list[str]]:
    """Full post-merge gate: check_pack + check_repro (+ twine when dist present)."""
    lines: list[str] = []
    # ensure HEAD is sha for the tools that read HEAD
    try:
        subprocess.run(
            ["git", "checkout", "-q", "--detach", sha],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        return 1, [f"git:1 checkout {sha[:12]} failed"]

    if dist is None:
        # build first
        dist = repo / "dist"
        if dist.exists():
            shutil.rmtree(dist)
        dist.mkdir()
        env = {**os.environ, "SOURCE_DATE_EPOCH": _git(repo, "log", "-1", "--format=%ct", sha)}
        built = subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )
        if built.returncode:
            return 1, [f"dist:1 full-build failed (exit {built.returncode})"]

    for cmd, label in (
        ([sys.executable, "tools/check_pack.py", "dist"], "check_pack"),
        ([sys.executable, "tools/check_repro.py", "dist"], "check_repro"),
    ):
        if not (repo / cmd[-2].replace("dist", "tools/check_pack.py") if False else True):
            pass
        tool = cmd[1] if cmd[1].startswith("tools/") else None
        # resolve tool path from argv
        tool_path = None
        for part in cmd:
            if part.startswith("tools/") and part.endswith(".py"):
                tool_path = repo / part
        if tool_path is not None and not tool_path.is_file():
            lines.append(f"{tool_path.name}:1 {label} missing")
            continue
        run = subprocess.run(
            cmd,
            cwd=repo,
            capture_output=True,
            text=True,
            env={**os.environ, "CI": "true", "MILL_PRIVATE_NAMES_REQUIRED": "0"},
        )
        if run.returncode:
            msg = (run.stdout or run.stderr or "failed").strip().splitlines()
            lines.append(f"{label}:1 full-gate {msg[-1][:160] if msg else 'failed'}")
    if shutil.which("twine") and dist is not None:
        run = subprocess.run(
            [sys.executable, "-m", "twine", "check", "--strict", *map(str, dist.glob("*"))],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if run.returncode:
            lines.append("twine:1 full-gate twine check failed")
    if lines:
        return 1, lines
    return 0, [f"gate full: ran check_pack+check_repro at {sha[:12]}"]


def gate(
    repo: Path,
    passed_sha: str,
    head_sha: str,
    dist: Path | None = None,
) -> int:
    if trees_equal(repo, passed_sha, head_sha):
        code, lines = run_fast_gate(repo, head_sha, dist)
        path = "fast"
    else:
        code, lines = run_full_gate(repo, head_sha, dist)
        path = "full"
    if code == 0:
        print(ok_line(head_sha, path))
        for ln in lines:
            if not ln.startswith("gate OK"):
                # keep diagnostic on stderr for humans; stdout stays one OK line
                print(ln, file=sys.stderr)
        return 0
    for ln in lines:
        print(ln)
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Release gate with tree-equal fast path (card 960)")
    ap.add_argument("--passed", required=True, help="release-branch sha the Validator passed")
    ap.add_argument("--head", default="HEAD", help="merge commit / tag sha to gate")
    ap.add_argument("--dist", type=Path, default=None, help="existing dist/ to byte-compare (fast) or scan (full)")
    ap.add_argument("--repo", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    head = _git(args.repo, "rev-parse", args.head)
    passed = _git(args.repo, "rev-parse", args.passed)
    return gate(args.repo, passed_sha=passed, head_sha=head, dist=args.dist)


if __name__ == "__main__":
    raise SystemExit(main())
