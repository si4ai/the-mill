# -*- coding: utf-8 -*-
"""The Wall CSP does not allow inline script or style (card 815).

The board onload handler and the paint-module style attributes move into
files and classes. A strict policy then loads the page with no violations.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WALL = REPO / "agent_coord" / "web" / "wall_ui"
TEXT = {".js", ".html", ".css"}

_STYLE_ATTR = re.compile(
    r"""style\s*=\s*(['"]|\\['"]|\$\{)"""
)
_STYLE_ELEM = re.compile(
    r"""<style\b|createElement\(\s*['"]style['"]\s*\)|setAttribute\(\s*['"]style['"]""",
    re.I,
)
_HANDLER = re.compile(
    r"""\son[a-z]+\s*=\s*['"]""",
    re.I,
)


def _hits() -> list[str]:
    out = []
    for path in sorted(WALL.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or "node_modules" in path.parts:
            continue
        if path.suffix == ".css":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _STYLE_ATTR.search(line) or _STYLE_ELEM.search(line) or _HANDLER.search(line):
                out.append(f"{path.relative_to(WALL).as_posix()}:{n}")
    return out


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    monkeypatch.delenv("AGENT_COORD_WALL_ALLOW", raising=False)
    return TestClient(make_asgi_app(parse_roots(cwd=REPO), api_only=False))


def test_served_csp_has_no_unsafe_inline(client):
    page = client.get("/")
    csp = page.headers["content-security-policy"]
    assert "unsafe-inline" not in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp


def test_wall_sources_have_no_inline_style_or_handler():
    hits = _hits()
    assert not hits, "inline style or handler in Wall source:\n" + "\n".join(hits)


def test_headless_chromium_loads_with_no_csp_violations():
    """Load the board in headless Chromium and count securitypolicyviolation."""
    pytest.importorskip("playwright.sync_api")
    import socket
    import threading

    import uvicorn

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = make_asgi_app(parse_roots(cwd=REPO), api_only=False)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        thread.join(0.1)
    assert server.started

    from playwright.sync_api import sync_playwright

    hits: list[str] = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(
            "window.__csp=[];document.addEventListener('securitypolicyviolation',"
            "function(e){window.__csp.push(e.violatedDirective+' '+(e.sample||''));});"
        )
        page.goto(f"http://127.0.0.1:{port}/", wait_until="commit")
        page.wait_for_selector("h1", timeout=10000)
        page.wait_for_timeout(400)
        dismiss = page.locator("#wall-welcome .dismiss")
        if dismiss.count() and dismiss.first.is_visible():
            dismiss.first.click()
            page.wait_for_timeout(200)
        for sel in ("#strip-here", "#strip-todo", "#strip-mail", "#strip-score"):
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2000)
                page.wait_for_timeout(200)
        hits = page.evaluate("window.__csp")
        browser.close()
    server.should_exit = True
    assert hits == [], hits
