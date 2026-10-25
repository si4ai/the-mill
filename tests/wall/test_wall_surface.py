# -*- coding: utf-8 -*-
"""Wall surface: HTML, CSS, JSON, one cache-pin table, human welcome.

Byte size stays in test_wall_ui_shell_css and test_wall_board_breakup.
JS syntax stays in test_wall_js_lib. Poll, scores, mail, and routes stay
in their own modules. This file is the only cache-pin lock.

stylelint, eslint, and html-validate are the tools/wall-validators package.
Install from the repo root: npm ci --prefix tools/wall-validators
A copy already on PATH is used when that directory has no node_modules.
Node.js itself is required. If it is not on PATH, the test fails and names Node.js.
The Node range is package.json engines (html-validate needs fs.globSync: ^22.22 or
>=24.8); npm ci refuses an older Node and the validators fail naming the range (#610).
The wall files are the checkout that contains this test, wherever it sits.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess

import pytest
from html.parser import HTMLParser
from pathlib import Path

# tests/wall/<this file> -> repo root. Not the installed package, not a fixed drive path.
_REPO = Path(__file__).resolve().parents[2]
_TOOLS = _REPO / "tools" / "wall-validators"
ROOT = _REPO / "agent_coord" / "web" / "wall_ui"

_check_spec = importlib.util.spec_from_file_location(
    "wall_surface_check",
    ROOT / "lib" / "check.py",
)
assert _check_spec is not None and _check_spec.loader is not None
_check_mod = importlib.util.module_from_spec(_check_spec)
_check_spec.loader.exec_module(_check_mod)
check_css_braces = _check_mod.check_css_braces
BOARD = ROOT / "default" / "board.html"
BOOT = ROOT / "default" / "boot.js"
MAIL_PAINT = ROOT / "default" / "mail" / "mail-paint.js"

# Immutable for a year once the browser has them. Change a file, change its pin here.
HTML_PINS = {
    "boot.js": "wow320",
    "board.css": "wow319",
    "lazy.js": "wow319",
    "shell.css": "wow269",
    "shell-early.js": "wow281",
    "theme.css": "wow165",
}
LAZY_PINS = (
    "/glossary/glossary.js?v=wow285",
    "/floor/map-paint.js?v=wow319",
    "/admin/invite.js?v=wow280",
    "/mail/mail-paint.js?v=wow319",
    "/score/score-paint.js?v=wow319",
    "/floor/floor-paint.js?v=wow319",
    "/todo/todo-paint.js?v=wow319",
    "/doing/doing-paint.js?v=wow319",
    "/doing/doing.css?v=wow319",
    "/mail/mail.js?v=wow285",
    "/score/score.js?v=wow320",
    "/todo/todo.js?v=wow320",
    "/mail/mail.css?v=wow316",
    "/score/score.css?v=wow319",
    "/todo/todo.css?v=wow319",
)
PERF_PIN = "/lib/perf.js?v=wow162"

VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}
STRIP = (
    ("session", "CONNECTED"),
    ("jobs", "TODO"),
    ("mail", "MAIL"),
    ("score", "SCORE"),
    ("floor", "COLLAB"),
)
REJECTED = {"SESSION", "FLOOR", "LEASES", "SCORECARDS"}
REQUIRED_IDS = (
    "pane-session",
    "pane-todo",
    "pane-mail",
    "pane-score",
    "pane-floor",
    "here-scores",
    "rail",
)


class _BoardHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.error: str | None = None
        self._strip = False
        self.strip_buttons: list[tuple[str, str]] = []
        self._btn: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if d.get("id"):
            self.ids.append(d["id"])
        if tag == "nav" and "tabs" in (d.get("class") or ""):
            self._strip = True
        if self._strip and tag == "button":
            self._btn = d.get("data-tab") or ""
            self._buf = []
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if self._btn is not None and tag == "button":
            self.strip_buttons.append((self._btn, "".join(self._buf).strip()))
            self._btn = None
        if tag == "nav" and self._strip:
            self._strip = False
        if not self.stack:
            self.error = f"extra </{tag}>"
            return
        if self.stack[-1] != tag:
            self.error = f"expected </{self.stack[-1]}> got </{tag}>"
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self._btn is not None:
            self._buf.append(data)


def test_board_html_well_formed_unique_ids():
    raw = BOARD.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    doc = _BoardHTML()
    doc.feed(raw.decode("utf-8"))
    doc.close()
    assert doc.error is None, doc.error
    assert doc.stack == []
    dup = {i for i in doc.ids if doc.ids.count(i) > 1}
    assert not dup, sorted(dup)
    for required in REQUIRED_IDS:
        assert required in doc.ids
    assert doc.strip_buttons == list(STRIP)
    assert REJECTED.isdisjoint({text for _, text in doc.strip_buttons})


def test_every_wall_css_braces():
    sheets = sorted(p for p in ROOT.rglob("*.css") if p.is_file())
    assert sheets
    for path in sheets:
        text = path.read_text(encoding="utf-8")
        label = str(path.relative_to(ROOT))
        assert check_css_braces(text, label) == []


def test_every_wall_json_parses():
    for path in ROOT.rglob("*.json"):
        if not path.is_file():
            continue
        json.loads(path.read_text(encoding="utf-8"))


def test_cache_pins_one_place():
    html = BOARD.read_text(encoding="utf-8")
    for name, ver in HTML_PINS.items():
        hits = re.findall(re.escape(name) + r"\?v=([^\"'\s>]+)", html)
        assert hits, name
        assert set(hits) == {ver}, (name, hits)
    lazy = (ROOT / "lib" / "lazy.js").read_text(encoding="utf-8")
    for pin in LAZY_PINS:
        assert pin in lazy
    early = (ROOT / "default" / "shell-early.js").read_text(encoding="utf-8")
    assert PERF_PIN in early


def test_welcome_is_the_human_page():
    src = BOOT.read_text(encoding="utf-8")
    html = BOARD.read_text(encoding="utf-8")
    assert "WALL_WELCOME_PAUSED" not in src
    card = html.split('id="wall-welcome"', 1)[1].split('id="howto-card"', 1)[0]
    assert "This is the office wall." in card
    assert "mill join" not in card
    assert "mill connect" not in card
    assert "pip install" not in card
    guide = html.split('id="wall-lazy-guide"', 1)[1].split("</template>", 1)[0]
    assert "docs/JOIN.md" in guide
    for phrase in ("pip install", "mill join", "mill connect", "mill install", "mill wall-src", "mill-wall"):
        assert phrase not in guide, phrase


def test_boot_opens_first_subtab_and_live_mail_views():
    src = BOOT.read_text(encoding="utf-8") + MAIL_PAINT.read_text(encoding="utf-8")
    assert 'localStorage.setItem("factory-todo-view"' not in src
    assert "factory-session-mode" not in src
    assert "factory-mail-view" not in src
    assert "localStorage.getItem(MAIL_MODE_KEY)" not in src
    assert "localStorage.getItem(MAIL_DESK_KEY)" not in src
    assert "localStorage.getItem(MAIL_TO_KEY)" not in src
    assert "localStorage.getItem(MAIL_SRC_KEY)" not in src
    assert "localStorage.getItem(MAIL_ROOM_KEY)" not in src
    assert "localStorage.getItem(MAIL_ROOMS_Q_KEY)" not in src
    assert "localStorage.getItem(MAIL_CLASS_KEY)" not in src
    prefs = src.split("function applyWallPrefsCut6(", 1)[1].split("async function loadWallPrefsCut6(", 1)[0]
    assert 'mv === "list"' not in prefs
    assert 'mv === "graph"' not in prefs
    assert 'mv === "rooms"' in prefs
    assert 'mv === "letters"' in prefs
    mail = MAIL_PAINT.read_text(encoding="utf-8").split("function mail(", 1)[1].split("function ", 1)[0]
    assert 'mailView !== "rooms"' in mail
    assert "paintMailLetters" in mail


NPM_CI = "npm ci --prefix tools/wall-validators"


def _not_installed(tool: str) -> str:
    return tool + " is not installed. From the repo root: " + NPM_CI


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_REPO).as_posix()
    except ValueError:
        return path.name


def _ver(text: str) -> tuple[int, int, int]:
    parts = (re.findall(r"\d+", text) + ["0", "0", "0"])[:3]
    return int(parts[0]), int(parts[1]), int(parts[2])


def _node_in_range(version: str, engines: str) -> bool:
    """True when version meets one ^X.Y.Z or >=X.Y.Z alternative of engines (#610)."""
    have = _ver(version)
    for alt in engines.split("||"):
        alt = alt.strip().replace(" ", "")
        if alt.startswith("^") and have[0] == _ver(alt)[0] and have >= _ver(alt):
            return True
        if alt.startswith(">=") and have >= _ver(alt):
            return True
    return False


def _node_engines() -> str:
    pkg = _TOOLS / "package.json"
    if not pkg.is_file():
        return ""
    return str(json.loads(pkg.read_text(encoding="utf-8")).get("engines", {}).get("node") or "")


def _validator(tool: str, script: str, config: str, files: list[Path], extra: list[str] | None = None) -> None:
    config_path = _TOOLS / config
    assert config_path.is_file(), "missing " + _rel(config_path)
    assert files, tool
    node = shutil.which("node")
    if not node:
        raise AssertionError(
            "Node.js is not on PATH, so " + tool + " cannot run."
        )
    engines = _node_engines()
    if engines:
        have = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        if not _node_in_range(have, engines):
            raise AssertionError(
                "Node.js " + engines + " is needed for the wall validators (tools/wall-validators"
                " package.json engines); this node is " + have + "."
            )
    local = _TOOLS / "node_modules" / script
    if local.is_file():
        cmd = [node, str(local)]
    else:
        found = shutil.which(tool)
        if not found:
            raise AssertionError(_not_installed(tool))
        cmd = [found]
    cmd.extend(["--config", str(config_path), *(extra or []), *[str(p) for p in files]])
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        text = (proc.stdout or "") + (proc.stderr or "")
        if "ERR_MODULE_NOT_FOUND" in text and ("'" + tool + "'") in text:
            raise AssertionError(_not_installed(tool))
        text = text.replace(str(_REPO), ".")
        home = str(Path.home())
        if home:
            text = text.replace(home, "~")
        raise AssertionError(text[-4000:])


def test_missing_node_names_node(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    try:
        _validator(
            "stylelint",
            "stylelint/bin/stylelint.mjs",
            "stylelint.config.mjs",
            [BOARD],
        )
    except AssertionError as exc:
        message = str(exc)
    else:
        raise AssertionError("missing Node.js did not fail")
    assert message == "Node.js is not on PATH, so stylelint cannot run."


def _html_validate_message() -> str:
    try:
        _validator(
            "html-validate",
            "html-validate/bin/html-validate.mjs",
            "html-validate.config.mjs",
            [BOARD],
        )
    except AssertionError as exc:
        return str(exc)
    raise AssertionError("missing html-validate did not fail")


def test_missing_html_validate_names_npm_ci(monkeypatch, tmp_path):
    # An empty validators folder: no node_modules, so the package cannot load.
    shutil.copy(_TOOLS / "html-validate.config.mjs", tmp_path / "html-validate.config.mjs")
    monkeypatch.setitem(globals(), "_TOOLS", tmp_path)
    want = "html-validate is not installed. From the repo root: " + NPM_CI
    if shutil.which("html-validate"):
        # A copy on PATH runs, but the config cannot import html-validate.
        assert _html_validate_message() == want
    node = shutil.which("node")
    monkeypatch.setattr(shutil, "which", lambda name: node if name == "node" else None)
    assert _html_validate_message() == want


def test_stylelint_parses_wall_css():
    sheets = sorted(p for p in ROOT.rglob("*.css") if p.is_file())
    _validator(
        "stylelint",
        "stylelint/bin/stylelint.mjs",
        "stylelint.config.mjs",
        sheets,
    )


def test_eslint_parses_wall_js():
    scripts = sorted(p for p in ROOT.rglob("*.js") if p.is_file())
    _validator(
        "eslint",
        "eslint/bin/eslint.js",
        "eslint.config.mjs",
        scripts,
        ["--no-config-lookup"],
    )


def test_html_validate_board():
    _validator(
        "html-validate",
        "html-validate/bin/html-validate.mjs",
        "html-validate.config.mjs",
        [BOARD],
    )


# #610: html-validate needs fs.globSync (Node 22). The package declares the Node
# range in engines, npm ci refuses an older Node, and the validators name it.
ENGINES = "^22.22.0 || >=24.8.0"


def test_validators_declare_the_node_range():
    pkg = json.loads((_TOOLS / "package.json").read_text(encoding="utf-8"))
    assert pkg.get("engines", {}).get("node") == ENGINES
    rc = (_TOOLS / ".npmrc").read_text(encoding="utf-8").split()
    assert "engine-strict=true" in rc


@pytest.mark.parametrize("ver,ok", [
    ("v20.19.2", False), ("v22.21.9", False), ("v22.22.0", True), ("v23.11.0", False),
    ("v24.7.9", False), ("v24.8.0", True), ("v24.21.0", True), ("v26.0.0", True),
])
def test_node_range(ver, ok):
    assert _node_in_range(ver, ENGINES) is ok


def test_ci_node_pin_is_in_range():
    ci = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pins = re.findall(r"NODE_VERSION:\s*(v[0-9.]+)", ci)
    assert pins
    for pin in pins:
        assert _node_in_range(pin, ENGINES), pin


def test_old_node_names_the_range(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_node_version("v20.19.2\n"))
    message = _html_validate_message()
    assert message == (
        "Node.js " + ENGINES + " is needed for the wall validators (tools/wall-validators"
        " package.json engines); this node is v20.19.2."
    )


def _fake_node_version(out: str):
    real = subprocess.run

    def run(cmd, *a, **k):
        if list(cmd)[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        return real(cmd, *a, **k)

    return run
