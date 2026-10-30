#!/usr/bin/env python3
"""Pre-www Wall CSS/JS gate (cheap). Fail before deploy_www / install wall.

SoR: wall-contract rule-asset-bytes (card 874); tests/wall/test_wall_asset_bytes.py
Catches:
  - JS syntax via node --check / quickjs when available; else ast-ish heuristics
    plus stray )(); / broken IIFE closers
  - CSS brace balance (+ obvious empty deleted blocks)
  - required markers (help-box, pane-score, WALL_UI_LIB_*, theme.css vars)

Exit non-zero on failure so bad assets never land in ~/.mill/www.
Usage:
  python -m agent_coord.web.wall_ui.validate_assets
  python -m pytest tests/wall/test_wall_js_lib.py -q
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
# agent_coord/web/wall_ui/lib/check.py -> parents[4] holds agent_coord/ (the repo or site-packages)
ROOT = _HERE.parents[4]
WALL_UI = ROOT / "agent_coord" / "web" / "wall_ui"
LIB = WALL_UI / "lib"
DEFAULT = WALL_UI / "default"
BOARD = DEFAULT / "board.html"

REQUIRED_MARKERS = (
    "help-box",
    'id="pane-score"',
    "WALL_UI_LIB_POPUP",
    "WALL_UI_LIB_DATA",
    "WALL_UI_LIB_TABS",
    "WALL_UI_LIB_TABLE",
    "WALL_UI_LIB_GRAPH",
    "WALL_UI_LIB_THEME",
    "WALL_UI_LIB_KEYS",
    "WALL_UI_DEFAULT_BOARD_CSS",
    "WALL_UI_DEFAULT_BOOT",
    "--font-family",
    "--h1-size",
)

LIB_JS = ("popup.js", "data.js", "tabs.js", "table.js", "graph.js", "theme.js", "keys.js", "lazy.js")
LIB_CSS = ("theme.css",)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def check_css_braces(text: str, label: str) -> list[str]:
    errs: list[str] = []
    # strip comments lightly
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    opens = stripped.count("{")
    closes = stripped.count("}")
    if opens != closes:
        errs.append(f"{label}: CSS brace imbalance open={opens} close={closes}")
    # empty rule bodies that often mean deleted content left braces
    if re.search(r"\{\s*\}", stripped):
        # allow a few intentional empties? flag as warning-level fail for gate
        empties = len(re.findall(r"\{\s*\}", stripped))
        if empties > 2:
            errs.append(f"{label}: too many empty CSS blocks ({empties})")
    # duplicated consecutive selectors (crude)
    sels = re.findall(r"(^|\n)([^{}/\n][^{]*)\{", stripped)
    seen: dict[str, int] = {}
    for _, s in sels:
        key = re.sub(r"\s+", " ", s.strip())
        if not key or key.startswith("@"):
            continue
        seen[key] = seen.get(key, 0) + 1
    dups = [k for k, n in seen.items() if n >= 3 and len(k) < 80]
    if dups:
        errs.append(f"{label}: repeated CSS selectors x3+: {dups[:5]}")
    return errs


def check_js_footguns(text: str, label: str) -> list[str]:
    errs: list[str] = []
    # stray )(); not part of normal (function(){...})();  - orphan closer lines
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s in {")();", "););", "})(););", "(););"}:
            errs.append(f"{label}:{i}: stray closer {s!r}")
        if s == "}););" or s == ")};":
            errs.append(f"{label}:{i}: broken IIFE/closer {s!r}")
    # crude paren balance on full file (strings will skew; still catches disasters)
    # skip if looks like huge board with template strings - still useful signal
    opens = text.count("(") - text.count(")")
    if abs(opens) > 20:
        errs.append(f"{label}: extreme paren skew delta={opens}")
    braces = text.count("{") - text.count("}")
    if abs(braces) > 20:
        errs.append(f"{label}: extreme brace skew delta={braces}")
    return errs


def extract_board_inline_js(html: str) -> str:
    parts = re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.I | re.S)
    out = []
    for p in parts:
        if "src=" in p[:40].lower():
            continue
        out.append(p)
    return "\n".join(out)


def run_external_js_check(path: Path) -> list[str]:
    errs: list[str] = []
    node = shutil.which("node")
    qjs = shutil.which("qjs") or shutil.which("quickjs")
    if node:
        r = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            errs.append(f"{path.name}: node --check failed: {(r.stderr or r.stdout)[:400]}")
        return errs
    if qjs:
        r = subprocess.run([qjs, "-c", str(path)], capture_output=True, text=True)
        if r.returncode != 0:
            # some qjs builds differ; treat non-zero as fail when -c exists
            errs.append(f"{path.name}: qjs check failed: {(r.stderr or r.stdout)[:400]}")
        return errs
    # no runtime: rely on footgun heuristics only (still a gate)
    return errs


def check_required_markers(board: str, theme: str) -> list[str]:
    errs: list[str] = []
    blob = board + "\n" + theme
    for m in REQUIRED_MARKERS:
        if m not in blob and m not in board:
            # theme-only markers may live only in theme.css
            if m.startswith("--") and m in theme:
                continue
            if m == "WALL_UI_LIB_THEME" and ("WALL_UI_LIB_THEME" in theme or "WALL_UI_LIB_THEME" in board):
                continue
            if m not in board and m not in theme:
                errs.append(f"missing required marker: {m}")
    if "lib/theme.css" not in board and 'href="lib/theme.css"' not in board and "theme.css" not in board:
        errs.append("board.html must link theme.css (lib/theme.css)")
    for name in LIB_JS:
        if f"lib/{name}" not in board and f'src="lib/{name}"' not in board:
            # allow basename if mirrored; prefer lib/ path
            if f'src="{name}"' not in board:
                errs.append(f"board.html must load lib/{name}")
    return errs


def run_gate(root: Path | None = None) -> dict:
    root = root or ROOT
    # Prefer package-local WALL_UI (pip OOTB) when already bound by validate_assets
    wall = WALL_UI if (WALL_UI / "default" / "board.html").is_file() else (root / "agent_coord" / "web" / "wall_ui")
    if not (wall / "default" / "board.html").is_file():
        wall = Path(__file__).resolve().parents[1]  # agent_coord/wall_ui
    lib = wall / "lib"
    board_path = wall / "default" / "board.html"
    errs: list[str] = []
    files_checked: list[str] = []

    if not board_path.is_file():
        return {"ok": False, "errors": [f"missing board: {board_path}"], "files": []}

    board = _read(board_path)
    files_checked.append(str(board_path))

    theme_path = lib / "theme.css"
    if not theme_path.is_file():
        errs.append("missing lib/theme.css")
        theme = ""
    else:
        theme = _read(theme_path)
        files_checked.append(str(theme_path))
        errs.extend(check_css_braces(theme, "lib/theme.css"))
        for var in ("--font-family", "--font-size", "--h1-size", "--h2-size", "--row-pad"):
            if var not in theme:
                errs.append(f"theme.css missing {var}")

    # board inline <style>
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", board, flags=re.I | re.S)
    for i, st in enumerate(styles):
        errs.extend(check_css_braces(st, f"board.html<style[{i}]>"))

    # lib JS
    for name in LIB_JS:
        p = lib / name
        if not p.is_file():
            errs.append(f"missing lib/{name}")
            continue
        files_checked.append(str(p))
        txt = _read(p)
        errs.extend(check_js_footguns(txt, f"lib/{name}"))
        errs.extend(run_external_js_check(p))
        marker = "WALL_UI_LIB_" + name.replace(".js", "").upper()
        if name == "theme.js":
            marker = "WALL_UI_LIB_THEME_JS"
        if marker not in txt and name != "theme.js":
            # popup -> WALL_UI_LIB_POPUP etc.
            pass
        if name == "theme.js" and "WALL_UI_LIB_THEME_JS" not in txt:
            errs.append("theme.js missing WALL_UI_LIB_THEME_JS")
        elif name != "theme.js":
            expect = {
                "popup.js": "WALL_UI_LIB_POPUP",
                "data.js": "WALL_UI_LIB_DATA",
                "tabs.js": "WALL_UI_LIB_TABS",
                "table.js": "WALL_UI_LIB_TABLE",
                "graph.js": "WALL_UI_LIB_GRAPH",
                "keys.js": "WALL_UI_LIB_KEYS",
                "lazy.js": "WALL_UI_LIB_LAZY",
            }[name]
            if expect not in txt:
                errs.append(f"{name} missing {expect}")

    # board inline JS
    inline = extract_board_inline_js(board)
    tmp = root / "tmp"
    tmp.mkdir(exist_ok=True)
    inline_path = tmp / "_board_inline_wall_check.js"
    inline_path.write_text(inline, encoding="utf-8")
    files_checked.append("tmp/_board_inline_wall_check.js")
    errs.extend(check_js_footguns(inline, "board.html<script>"))
    # only run node --check on lib files by default; board inline is huge and
    # may use browser-only globals - footguns + marker checks cover board.


    # Wave 1 instant shell (optional file; required when board.html links it)
    shell_css = wall / "default" / "shell.css"
    if shell_css.is_file():
        files_checked.append(str(shell_css))
        scss = _read(shell_css)
        errs.extend(check_css_braces(scss, "default/shell.css"))
        if "WALL_UI_DEFAULT_SHELL_CSS" not in scss:
            errs.append("shell.css missing WALL_UI_DEFAULT_SHELL_CSS")
        if "shell.css" not in board:
            errs.append("shell.css present but board.html does not link it")
    elif "shell.css" in board:
        errs.append("board.html links shell.css but default/shell.css missing")


    # Wave 2: lazy.js + tab CSS markers (MAIL/TODO/SCORE)
    lazy_js = lib / "lazy.js"
    if lazy_js.is_file():
        files_checked.append(str(lazy_js))
        lj = _read(lazy_js)
        if "WALL_UI_LIB_LAZY" not in lj:
            errs.append("lazy.js missing WALL_UI_LIB_LAZY")
        if "wallEnsureDomain" not in lj:
            errs.append("lazy.js missing wallEnsureDomain")
        if "lib/lazy.js" not in board:
            errs.append("lazy.js present but board.html does not load lib/lazy.js")
    for dom, marker in (("mail", "WALL_UI_DEFAULT_MAIL_CSS"), ("todo", "WALL_UI_DEFAULT_TODO_CSS"), ("score", "WALL_UI_DEFAULT_SCORE_CSS")):
        cpath = wall / "default" / dom / f"{dom}.css"
        if cpath.is_file():
            files_checked.append(str(cpath))
            ctxt = _read(cpath)
            errs.extend(check_css_braces(ctxt, f"default/{dom}/{dom}.css"))
            if marker not in ctxt:
                errs.append(f"{dom}.css missing {marker}")

    # default pack board.css / boot.js (Path A breakup)
    board_css = wall / "default" / "board.css"
    if board_css.is_file():
        files_checked.append(str(board_css))
        bcss = _read(board_css)
        errs.extend(check_css_braces(bcss, "default/board.css"))
        if "WALL_UI_DEFAULT_BOARD_CSS" not in bcss:
            errs.append("board.css missing WALL_UI_DEFAULT_BOARD_CSS")
    elif "board.css" in board:
        errs.append("board.html links board.css but default/board.css missing")
    boot_js = wall / "default" / "boot.js"
    if boot_js.is_file():
        files_checked.append(str(boot_js))
        bjs = _read(boot_js)
        errs.extend(check_js_footguns(bjs, "default/boot.js"))
        errs.extend(run_external_js_check(boot_js))
        if "WALL_UI_DEFAULT_BOOT" not in bjs:
            errs.append("boot.js missing WALL_UI_DEFAULT_BOOT")
        for needle in ("document.hidden", "wallClaimPollLeader", "visibilitychange", "wallEnsureDomain"):
            if needle not in bjs:
                errs.append(f"boot.js missing poll/lazy hygiene: {needle}")
    if "board.css" in board and 'href="board.css"' not in board and "href='board.css'" not in board:
        # linked somehow
        pass
    if "boot.js" in board and 'src="boot.js"' not in board and "src='boot.js'" not in board:
        pass

    errs.extend(check_required_markers(board, theme))

    # components gutter still required (prior cut)
    gutter = wall / "components" / "gutter.js"
    if gutter.is_file():
        files_checked.append(str(gutter))
        errs.extend(check_js_footguns(_read(gutter), "components/gutter.js"))
        errs.extend(run_external_js_check(gutter))

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except Exception:
            try:
                return str(p.relative_to(wall))
            except Exception:
                return str(p)

    files_checked = [_rel(Path(f)) if not isinstance(f, str) else f for f in files_checked]
    # re-normalize any absolute we stored as str earlier
    norm = []
    for f in files_checked:
        fp = Path(f)
        norm.append(_rel(fp) if fp.is_absolute() else f)
    return {
        "ok": not errs,
        "errors": errs,
        "files": norm,
        "marker": "WALL_CSS_JS_CHECK",
        "theme_css": _rel(theme_path) if theme_path.is_file() else None,
        "product_package_data": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pre-www Wall CSS/JS gate")
    ap.add_argument("--json", action="store_true", help="print JSON report")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args(argv)
    report = run_gate(args.root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("WALL_CSS_JS_CHECK", "PASS" if report["ok"] else "FAIL")
        print("files", len(report["files"]))
        if report.get("theme_css"):
            print("theme.css", report["theme_css"])
        for e in report["errors"]:
            print("ERR", e)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
