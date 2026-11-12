"""Report a the-mill checkout whose commit hooks are off (card 1174).

The repo hooks in .githooks run tools/precommit_hygiene.py, but only after
`git config core.hooksPath .githooks` in that checkout. mill connect prints one
line when the checkout it starts in skips that step. A visible fact, not a block.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HOOKS_OFF_LINE = (
    "mill connect: this the-mill checkout has no core.hooksPath .githooks, "
    "so commit hygiene does not run here; turn it on: git config core.hooksPath .githooks"
)


def mill_checkout_root(start: Path) -> Path | None:
    """The the-mill checkout holding start: a git root with .githooks and the hygiene tool."""
    for d in (start, *start.parents):
        if (d / ".git").exists():
            if (d / ".githooks" / "pre-commit").is_file() and (d / "tools" / "precommit_hygiene.py").is_file():
                return d
            return None
    return None


def hooks_on(root: Path) -> bool:
    """core.hooksPath resolves to root/.githooks."""
    try:
        out = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    value = out.stdout.strip()
    if out.returncode != 0 or not value:
        return False
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve() == (root / ".githooks").resolve()
    except OSError:
        return False


def hooks_off_line(start: Path | None = None) -> str:
    """The report line when start is in a the-mill checkout with hooks off; else empty."""
    try:
        here = (start or Path.cwd()).resolve()
    except OSError:
        return ""
    root = mill_checkout_root(here)
    if root is None or hooks_on(root):
        return ""
    return HOOKS_OFF_LINE
