# -*- coding: utf-8 -*-
"""First paint loads only the core; each pane module loads on first use (card #872,
wall-contract rule-lazy-panes #875).

Pane code lives in default/<pane>/<name>-paint.js and loads through lib/lazy.js
MODULES. boot.js keeps a one-line stub per entry that core still calls:
    function NAME() { return wallLazyCall("MODULE", "NAME", NAME, arguments); }
The first call loads the module; its declaration replaces the stub.
"""
from __future__ import annotations

import re
from pathlib import Path

from ._wall_src import BOOT, ROOT, pane_paint_files

LAZY = ROOT / "lib" / "lazy.js"
BOARD = ROOT / "default" / "board.html"
STUB = re.compile(r'^    function (\w+)\(\) \{ return wallLazyCall\("(\w+)", "(\w+)", (\w+), arguments\); \}$', re.M)


def _modules() -> dict[str, str]:
    """MODULES name -> js path (no pin), from lib/lazy.js."""
    src = LAZY.read_text(encoding="utf-8")
    block = src[src.index("var MODULES = {"):src.index("function ensureModule")]
    return dict(re.findall(r'(\w+): \{\s*js: "(/[^"?]+)\?v=', block))


def _static_scripts() -> list[str]:
    """Script srcs board.html loads at first paint (inert <template> content excluded)."""
    html = re.sub(r"<template\b.*?</template>", "", BOARD.read_text(encoding="utf-8"), flags=re.S)
    return [s.split("?")[0] for s in re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)]


def test_no_pane_module_is_a_first_paint_script():
    mods = set(_modules().values())
    first = set(_static_scripts())
    assert "/boot.js" in first
    assert not mods & first, sorted(mods & first)


def test_every_pane_module_file_is_lazy():
    mods = set(_modules().values())
    for p in pane_paint_files():
        rel = "/" + p.relative_to(ROOT / "default").as_posix()
        assert rel in mods, rel + " is not in lib/lazy.js MODULES"


def test_every_stub_names_its_module_and_the_module_defines_it():
    mods = _modules()
    stubs = STUB.findall(BOOT.read_text(encoding="utf-8"))
    assert len(stubs) >= 30
    for name, mod, name2, name3 in stubs:
        assert name == name2 == name3, name
        assert mod in mods, (name, mod)
        src = (ROOT / "default" / mods[mod].lstrip("/")).read_text(encoding="utf-8")
        assert re.search(r"^\s*(async\s+)?function " + name + r"\(", src, re.M), (name, mods[mod])


def test_split_entries_are_stubs_in_boot():
    """The #872 slice: these run only when their pane or panel opens."""
    boot = BOOT.read_text(encoding="utf-8")
    for name, mod in (
        ("paintScoreShow", "scorePaint"), ("paintScoreDeskTable", "scorePaint"),
        ("hereDeskLoad", "deskPaint"), ("paintHereDesk", "deskPaint"),
        ("paintWallService", "servicePaint"), ("wallMintInvite", "adminMint"),
        ("wallFetchListNextPage", "listsPaint"), ("wallFetchTreeExpand", "listsPaint"),
        ("wallOpenMailIfTrunc", "mailPaint"), ("wallOpenTodoIfTrunc", "todoPaint"),
    ):
        assert f'function {name}() {{ return wallLazyCall("{mod}", "{name}", {name}, arguments); }}' in boot, name
