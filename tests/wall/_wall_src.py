"""Source of the Wall boot code for text checks (#710).

boot.js keeps the shared core; a split pane's paint code lives in its own
lazy file (``default/<pane>/<pane>-paint.js``, lib/lazy.js MODULES). Text
checks that are about the boot code as a whole read both.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
BOOT = ROOT / "default" / "boot.js"


def pane_paint_files() -> list[Path]:
    """The split pane paint files, in a stable order."""
    return sorted(p for p in (ROOT / "default").glob("*/*-paint.js") if p.parent.name != "floor" or p.name != "map-paint.js")


def boot_source() -> str:
    """boot.js followed by every split pane paint file."""
    parts = [BOOT.read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in pane_paint_files()]
    return "\n".join(parts)


def wall_fn(name: str) -> str:
    """Source of one top-level Wall function, from whichever file holds it (#872).

    A function split out of boot.js lives in its pane module, and boot.js keeps a
    one-line wallLazyCall stub under the same name; the stub is skipped.
    """
    for path in [BOOT] + pane_paint_files():
        src = path.read_text(encoding="utf-8")
        for decl in ("    async function " + name + "(", "    function " + name + "("):
            head = src.find(decl)
            while head >= 0:
                line_end = src.find("\n", head)
                if "wallLazyCall(" not in src[head:line_end]:
                    end = src.index("\n    }\n", head) + len("\n    }\n")
                    return src[head:end]
                head = src.find(decl, line_end)
    raise ValueError("no Wall function " + name)
