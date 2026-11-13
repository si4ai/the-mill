# -*- coding: utf-8 -*-
"""Wall instant shell: tiny shell.css + deferred board.css; keep slim parts= poll."""
from __future__ import annotations

import re
from pathlib import Path

from agent_coord.web.wall_logic.packs import wall_ui_root

ROOT = wall_ui_root()
BOARD_HTML = ROOT / "default" / "board.html"
SHELL_CSS = ROOT / "default" / "shell.css"
BOOT = ROOT / "default" / "boot.js"


def _html() -> str:
    return BOARD_HTML.read_text(encoding="utf-8")


def _shell() -> str:
    return SHELL_CSS.read_text(encoding="utf-8")


def test_shell_css_exists_and_marked():
    assert SHELL_CSS.is_file(), "default/shell.css missing"
    src = _shell()
    assert "WALL_UI_DEFAULT_SHELL_CSS" in src
    assert len(src.encode("utf-8")) < 16_000, "shell.css grew too fat for Wave 1"


def test_board_html_instant_shell_load_order():
    html = _html()
    theme_i = html.find('href="/lib/theme.css')
    if theme_i < 0:
        theme_i = html.find('href="lib/theme.css')
    shell_i = html.find('href="/shell.css')
    if shell_i < 0:
        shell_i = html.find('href="shell.css')
    board_i = html.find('href="/board.css')
    if board_i < 0:
        board_i = html.find('href="board.css')
    assert 0 <= theme_i < shell_i < board_i
    assert re.search(r'<link[^>]+href="/?shell\.css[^>]*>', html)
    assert re.search(
        r'<link[^>]+id="board-css"[^>]+href="/?board\.css[^>]*media="print"',
        html,
    )
    assert re.search(r'<script[^>]+src="/?lib/board-css\.js', html)
    assert "onload=" not in html
    ns = html.find("<noscript>")
    assert ns >= 0 and "board.css" in html[ns : ns + 200]
    assert re.search(r'<script\s+defer\s+src="/?boot\.js', html)


def test_slim_parts_poll_not_regressed():
    src = BOOT.read_text(encoding="utf-8")
    assert "function wallParts()" in src
    assert "stripNeed" not in src
    assert 'mailView === "rooms") ? "mail,trees" : "mail"' in src
    assert "return core;" in src
    assert "function wallV1Routes" in src
    assert 'parts === "agents"' in src


def test_shell_critical_first_paint_chrome():
    src = _shell()
    assert "WALL_UI_SHELL_CRITICAL" in src
    assert ".pane.on" in src
    assert ".pane-body" in src
    assert ".mail-browser" in src or ".jobs-kanban" in src


def test_shell_structure_layout_rules():
    src = _shell()
    assert "WALL_UI_SHELL_CRITICAL" in src
    for needle in (
        "#shell",
        "#rail",
        "grid-template-columns",
        "#rail-book > div:first-child",
        ".pane.on",
        "#pane-session.on",
        ".pane-body",
        ".mail-browser",
        ".jobs-kanban",
        ".floor-split",
        "#filter-panel",
        "#howto-card",
    ):
        assert needle in src, needle
    assert len(src.encode("utf-8")) < 16_000


BOARD_CSS = ROOT / "default" / "board.css"
_PANE_ON_SEL = re.compile(r"^(?:\.pane|#pane-[a-z0-9-]+)\.on$")


def _rule_blocks(src: str):
    """Yield (selector, body) for each rule, walking into @media bodies."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    i = 0
    n = len(src)
    while i < n:
        j = src.find("{", i)
        if j < 0:
            break
        sel = src[i:j].strip()
        depth = 1
        k = j + 1
        while k < n and depth:
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
            k += 1
        body = src[j + 1 : k - 1]
        if sel.startswith("@") and "{" in body:
            yield from _rule_blocks(body)
        else:
            yield sel, body
        i = k


_CAP_PROP = re.compile(r"(?:^|;)\s*(max-width|max-inline-size)\s*:\s*([^;]+)", re.I)
_MARGIN_AUTO = re.compile(
    r"(?:^|;)\s*(margin(?:-left|-right|-inline(?:-start|-end)?)?)\s*:\s*([^;]*\bauto\b[^;]*)",
    re.I,
)


def _subject(part: str) -> str:
    """Last compound of a selector: the element the rule styles."""
    return re.split(r"\s*[>+~]\s*|\s+", part.strip())[-1]


def _is_pane_box(part: str) -> bool:
    """True when the rule styles a pane or its .pane-body, at any nesting."""
    subj = _subject(part)
    toks = set(re.findall(r"[.#][A-Za-z0-9_-]+", subj))
    if ".pane-body" in toks:
        return True
    return ".pane" in toks or any(t.startswith("#pane-") for t in toks)


def _pane_caps(src: str) -> list[str]:
    hits = []
    for sel, body in _rule_blocks(src):
        parts = [p for p in sel.split(",") if _is_pane_box(p)]
        if not parts:
            continue
        for prop, val in _CAP_PROP.findall(body):
            if val.strip().lower() not in ("none", "100%"):
                hits.append(f"{sel.strip()} {{{prop}: {val.strip()}}}")
        for prop, val in _MARGIN_AUTO.findall(body):
            hits.append(f"{sel.strip()} {{{prop}: {val.strip()}}}")
    return hits


def test_pane_cap_detector_catches_each_cap_shape():
    """The no-cap check must see every way a pane width cap comes back."""
    caps = [
        ".pane.on { max-width: 800px; }",
        "main .pane.on { max-width: 800px; }",
        "#pane-score.on { max-inline-size: 60rem; }",
        "#pane-list.on > .pane-body { max-width: 50rem; }",
        ".pane.on { margin-left: auto; margin-right: auto; }",
        ".pane.on { margin: 0 auto; }",
        "#pane-x.on { margin-inline: auto; }",
        "@media (min-width: 900px) { .pane.on { max-width: 900px; } }",
    ]
    for css in caps:
        assert _pane_caps(css), css
    fine = [
        ".pane.on { width: 100%; max-width: none; }",
        "#pane-score .score-pulse { max-width: 100%; margin: 0 auto; }",
        "#guide { max-width: 48rem; }",
    ]
    for css in fine:
        assert not _pane_caps(css), css


def test_panes_have_no_width_cap():
    """Panes stay fluid: no pane or .pane-body rule caps width or centres it."""
    hits = []
    for path in sorted((ROOT / "default").rglob("*.css")):
        for hit in _pane_caps(path.read_text(encoding="utf-8")):
            hits.append(f"{path.relative_to(ROOT)}: {hit}")
    assert not hits, "pane width cap still present: " + "; ".join(hits)


def test_prose_keeps_48rem_measure():
    """Only prose keeps a readable width: #guide and .idle stay at 48rem."""
    src = BOARD_CSS.read_text(encoding="utf-8")
    widths = {}
    for sel, body in _rule_blocks(src):
        for part in (p.strip() for p in sel.split(",")):
            if part in ("#guide", ".idle"):
                m = re.search(r"max-width\s*:\s*([^;]+)", body)
                if m:
                    widths[part] = m.group(1).strip()
    assert widths == {"#guide": "48rem", ".idle": "48rem"}, widths


def test_pane_on_rule_is_not_duplicated_in_board_css():
    src = BOARD_CSS.read_text(encoding="utf-8")
    for sel, _body in _rule_blocks(src):
        parts = [p.strip() for p in sel.split(",")]
        assert ".pane.on" not in parts, f"duplicate .pane.on rule in board.css: {sel}"
