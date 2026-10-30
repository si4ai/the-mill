"""Time a Wall page cold: first-paint bytes and open-to-painted time per pane.

Run it against a Wall you can reach (a local test office is fine), once before a
change and once after, then compare the two JSON reports. It is a lab tool, not
a test: no CI job runs it, and it needs `playwright` with a `chromium` build.

    pip install playwright
    python -m playwright install chromium-headless-shell
    python tools/glance.py URL TAG [--out DIR] [--roster ID] [--runs N]

Each run opens a fresh browser context with the HTTP cache off, so every run is
a cold load. It dismisses the welcome card, picks the roster row named by
--roster (if any), and records the JS, CSS and HTML bytes loaded by then. Then
it opens the desk panel and each strip pane in turn (floor, todo, mail, score,
session), and times the click until the pane shows text and no loading marker.
Last it pages one list and paints the service glance, so every lazy module
loads at least once. Each step also lists the scripts it loaded.

The first run saves each pane's text (clock times and durations replaced by #)
and a screenshot, so two reports can be diffed for visible change. Output:
DIR/TAG.json and DIR/shots/TAG-PANE.png. The tool only reads: it never logs in,
posts, or changes the office.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PANES = [
    ("floor", "strip-floor", "pane-floor"),
    ("todo", "strip-todo", "pane-todo"),
    ("mail", "strip-mail", "pane-mail"),
    ("score", "strip-score", "pane-score"),
    ("session", "strip-here", "pane-session"),
]

RESOURCES = """() => performance.getEntriesByType('resource').map(r => ({
  n: r.name.replace(location.origin, '').split('?')[0], xfer: r.transferSize,
  dec: r.decodedBodySize}))"""

NAVIGATION = """() => { const n = performance.getEntriesByType('navigation')[0];
  return {dec: n.decodedBodySize, xfer: n.transferSize}; }"""

PAINTED = """(id) => { const p = document.getElementById(id);
  if (!p || !p.classList.contains('on')) return false;
  const busy = p.querySelector('.wall-loading, .kpi-loading, [data-wall-loading="1"], .pane-overlay:not([hidden])');
  return !busy && p.innerText.trim().length > 40; }"""

DESK_PAINTED = """() => { const e = document.getElementById('here-desk');
  return e && e.innerText.trim().length > 20; }"""

LIST_PAGE = "() => { try { wallFetchListNextPage('events'); } catch (e) {} }"

SERVICE = """() => { try { const r = document.getElementById('wall-service');
  r.hidden = false; paintWallService(); } catch (e) { console.error('service ' + e); } }"""

CLOCKS = re.compile(r"\d\d:\d\d(:\d\d)?|\b\d+(\.\d+)?\s*(ms|s|m|h|d|min)\b( ago)?|\d{4}-\d\d-\d\d")


def norm(text: str) -> str:
    """Replace clock times, dates and durations so two runs diff cleanly."""
    return CLOCKS.sub("#", text)


def scripts(entries: list[dict], ends: tuple[str, ...] = (".js",)) -> set[str]:
    return {e["n"] for e in entries if e["n"].endswith(ends)}


def text_of(page, selector: str, errors: list[str]) -> str:
    try:
        return norm(page.inner_text(selector, timeout=3000))
    except Exception as e:
        errors.append(f"text {selector}: {str(e)[:80]}")
        return ""


def one_run(browser, args, keep: bool, shots: Path) -> dict:
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text[:200]}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {str(e)[:200]}"))

    page.goto(args.url, wait_until="load")
    page.wait_for_timeout(args.settle_ms)
    try:
        page.click("#wall-welcome .dismiss", timeout=1500)
    except Exception:
        pass
    if args.roster:
        try:
            page.click(f"#rail-roster .rail-row[data-id='{args.roster}']", timeout=5000)
            page.wait_for_timeout(args.settle_ms)
        except Exception as e:
            errors.append(f"roster row: {str(e)[:80]}")

    first = page.evaluate(RESOURCES)
    nav = page.evaluate(NAVIGATION)
    js = [e for e in first if e["n"].endswith(".js")]
    css = [e for e in first if e["n"].endswith(".css")]
    run = {
        "first_js_dec": sum(e["dec"] for e in js),
        "first_js_xfer": sum(e["xfer"] for e in js),
        "first_css_dec": sum(e["dec"] for e in css),
        "first_html_dec": nav["dec"],
        "first_js_files": sorted(e["n"] for e in js),
        "panes": {},
        "text": {},
    }
    run["first_static_dec"] = run["first_js_dec"] + run["first_css_dec"] + run["first_html_dec"]
    seen = {e["n"] for e in first}

    t0 = time.time()
    try:
        page.click("#here .here-row", timeout=5000)
        page.wait_for_function(DESK_PAINTED, timeout=10000, polling=10)
        run["desk_open_to_painted_ms"] = round((time.time() - t0) * 1000)
        page.wait_for_timeout(1500)
    except Exception as e:
        errors.append(f"desk panel: {str(e)[:100]}")
    now = page.evaluate(RESOURCES)
    run["panes"]["desk"] = {"loaded": sorted(scripts(now) - seen)}
    seen |= {e["n"] for e in now}
    if keep:
        run["text"]["desk"] = text_of(page, "#pane-session", errors)
        page.screenshot(path=str(shots / f"{args.tag}-desk.png"))

    for name, strip, pane in PANES:
        t0 = time.time()
        try:
            page.click("#" + strip, timeout=5000)
            page.wait_for_function(PAINTED, arg=pane, timeout=15000, polling=10)
            ms = round((time.time() - t0) * 1000)
        except Exception as e:
            errors.append(f"pane {name}: {str(e)[:80]}")
            ms = None
        page.wait_for_timeout(1500)
        now = page.evaluate(RESOURCES)
        run["panes"][name] = {"open_to_painted_ms": ms, "loaded": sorted(scripts(now, (".js", ".css")) - seen)}
        seen |= {e["n"] for e in now}
        if keep:
            run["text"][name] = text_of(page, "#" + pane, errors)
            page.screenshot(path=str(shots / f"{args.tag}-{name}.png"))

    page.evaluate(LIST_PAGE)
    page.wait_for_timeout(1200)
    page.evaluate(SERVICE)
    page.wait_for_timeout(1200)
    now = page.evaluate(RESOURCES)
    run["panes"]["lists+service"] = {"loaded": sorted(scripts(now) - seen)}
    if keep:
        run["text"]["service"] = text_of(page, "#wall-service", errors)
        page.screenshot(path=str(shots / f"{args.tag}-service.png"))

    run["errors"] = errors[:30]
    ctx.close()
    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cold-load bytes and pane open times for one Wall page.")
    ap.add_argument("url", help="Wall page URL")
    ap.add_argument("tag", help="report name, such as before or after")
    ap.add_argument("--out", default="glance-report", help="report folder (default: glance-report)")
    ap.add_argument("--roster", default="", help="roster id to pick in the rail before measuring")
    ap.add_argument("--runs", type=int, default=3, help="cold runs (default: 3)")
    ap.add_argument("--settle-ms", type=int, default=3000, help="wait after load and after the roster pick")
    args = ap.parse_args(argv)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("glance needs Playwright: pip install playwright", file=sys.stderr)
        return 2

    out = Path(args.out)
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    report = {"tag": args.tag, "runs": []}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i in range(args.runs):
            report["runs"].append(one_run(browser, args, i == 0, shots))
        browser.close()
    (out / f"{args.tag}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")

    runs = report["runs"]
    print(args.tag, "first static B", [r["first_static_dec"] for r in runs], "js", [r["first_js_dec"] for r in runs])
    for k in runs[0]["panes"]:
        print(" ", k, [r["panes"][k].get("open_to_painted_ms") for r in runs], runs[0]["panes"][k]["loaded"])
    print("desk ms", [r.get("desk_open_to_painted_ms") for r in runs])
    print("errors", [r["errors"] for r in runs])
    return 0


if __name__ == "__main__":
    sys.exit(main())
