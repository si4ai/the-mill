# -*- coding: utf-8 -*-
"""DESKS tab (Wall redesign, first slice): the tab shell and the DESKS rows.

The top tabs are DESKS (default), TODO, MAIL, PRIORITIES, SCORE, COLLAB. DESKS rows come
from default/session/desks-rows.js, run here in Node on reads shaped like the live routes:
GET /api/v1/doing?all=1 views, GET /api/pov?part=desks rows (card 1191), the labels read
(top 3 per desk) and Office score rows. Old letters use card 1192's n_over_day / oldest_at;
an older office server without them, and fields not served yet (card 1193 scope, card 1194
doing time), hide their element. The degrade tests strip them and check nothing is made up.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from html.parser import HTMLParser

from ._wall_src import BOOT, ROOT, wall_fn

BOARD = ROOT / "default" / "board.html"
ROWS = ROOT / "default" / "session" / "desks-rows.js"
NOW = "2026-11-13T03:00:00Z"
TABS = [
    ("session", "DESKS"),
    ("jobs", "TODO"),
    ("mail", "MAIL"),
    ("priorities", "PRIORITIES"),
    ("score", "SCORE"),
    ("floor", "COLLAB"),
]


class _Nav(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabs: list[tuple[str, str, str]] = []
        self.panes: dict[str, str] = {}
        self._in_nav = False
        self._btn: tuple[str, str] | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "nav" and "tabs" in (d.get("class") or ""):
            self._in_nav = True
        if self._in_nav and tag == "button":
            self._btn = (d.get("data-tab") or "", d.get("class") or "")
            self._buf = []
        if tag == "div" and (d.get("id") or "").startswith("pane-"):
            self.panes[d["id"]] = d.get("class") or ""

    def handle_endtag(self, tag):
        if self._btn is not None and tag == "button":
            self.tabs.append((self._btn[0], "".join(self._buf).strip(), self._btn[1]))
            self._btn = None
        if tag == "nav":
            self._in_nav = False

    def handle_data(self, data):
        if self._btn is not None:
            self._buf.append(data)


def _nav() -> _Nav:
    p = _Nav()
    p.feed(BOARD.read_text(encoding="utf-8"))
    return p


def _node(script: str, *args: str) -> dict:
    env = dict(os.environ, TZ="America/Los_Angeles")
    out = subprocess.run(["node", "-e", script, *args], capture_output=True, text=True, check=True, env=env).stdout
    return json.loads(out)


# ---- tab shell

def test_top_tabs_are_desks_todo_mail_priorities_score_collab():
    assert [(t, label) for t, label, _ in _nav().tabs] == TABS


def test_desks_is_the_default_tab():
    nav = _nav()
    on = [t for t, _, cls in nav.tabs if "on" in cls.split()]
    assert on == ["session"]
    assert "on" in nav.panes["pane-session"].split()
    assert not any("on" in c.split() for pid, c in nav.panes.items() if pid != "pane-session")
    # A fresh browser (nothing saved) and a junk saved value both land on DESKS.
    harness = r"""
    const store = JSON.parse(process.argv[1]);
    global.localStorage = { getItem: k => (k in store ? store[k] : null), setItem() {} };
    const WALL_TAB_KEY = "factory-wall-tab";
    const WALL_TAB_OK = ["session", "jobs", "mail", "priorities", "score", "floor"];
    (0, eval)(process.argv[2] + "; global.loadWallTab = loadWallTab;");
    process.stdout.write(JSON.stringify(loadWallTab()));
    """
    fn = wall_fn("loadWallTab")
    assert _node(harness, "{}", fn) == "session"
    assert _node(harness, json.dumps({"factory-wall-tab": "nonsense"}), fn) == "session"
    assert _node(harness, json.dumps({"factory-wall-tab": "mail"}), fn) == "mail"


def test_strip_names_desks_and_desks_hash_opens_it():
    html = BOARD.read_text(encoding="utf-8")
    first = re.search(r'id="strip-here"[^>]*>([A-Z]+)<', html)
    assert first and first.group(1) == "DESKS"
    src = BOOT.read_text(encoding="utf-8")
    assert re.search(r'id="strip-here"[^`]*>DESKS\$\{', src), "strip() repaints the chip as DESKS"
    show = wall_fn("showTab")
    assert 'if (name === "desks") name = "session";' in show.split("\n", 3)[2]


def test_desks_rows_load_before_boot():
    scripts = re.findall(r'<script[^>]*\ssrc="([^"?]+)', re.sub(r"<template\b.*?</template>", "", BOARD.read_text(encoding="utf-8"), flags=re.S))
    assert scripts.index("/session/desks-rows.js") < scripts.index("/boot.js")
    assert "wallDesksHtml(d, live, mine)" in wall_fn("board")


# ---- DESKS rows

HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const ctx = JSON.parse(process.argv[2]);
ctx.now = Date.parse(ctx.now);
const m = desksModel(ctx);
const html = desksHtml(m);
const rows = (list) => list.map(r => r.desk);
process.stdout.write(JSON.stringify({
  connected: rows(m.connected), away: rows(m.away), attention: m.attention, html: html,
  model: m,
}));
"""


def _letters(n, over=None, oldest=None):
    L = {"n": n, "newest": []}
    if over is not None:
        L["n_over_day"] = over
    if oldest is not None:
        L["oldest_at"] = oldest
    return {"letters": L, "cards": {"n": 0, "newest": []}}


def _ctx(**over) -> dict:
    ctx = {
        "now": NOW,
        "live": [
            {"owner": "scout", "state": "idle", "seat": ""},
            {"owner": "builder", "state": "working", "seat": ""},
            {"owner": "validator", "state": "working", "seat": ""},
            {"owner": "gardener", "state": "working", "seat": ""},
            {"owner": "wall-ui", "state": "working", "seat": ""},
        ],
        "doing": {
            "builder": {"owner": "builder", "doing": "filing the stations route", "on": "mail-6035", "age": "47m",
                        "waiting_on_it": _letters(83, 2, "2026-11-10 14:10:00")},
            "gardener": {"owner": "gardener", "doing": "rewriting the label playbook", "on": "todo-1190", "age": "1h 08m",
                         "waiting_on_it": _letters(2, 1, "2026-11-11 19:00:00")},
            "validator": {"owner": "validator", "doing": "reviewing PR 424", "on": "todo-1188", "age": "22m",
                          "waiting_on_it": _letters(4, 0, "2026-11-12 18:10:00")},
            "wall-ui": {"owner": "wall-ui", "doing": "building DESKS", "on": "todo-1192", "age": "1h 12m",
                        "waiting_on_it": _letters(3, 0, "2026-11-12 12:00:00")},
            "scout": {"owner": "scout", "doing": "", "idle": "3h 12m", "last": {"doing": "swept the tree", "on": ""},
                      "waiting_on_it": _letters(0, 0, "")},
        },
        "stations": [
            {"name": "builder", "connected": True, "last_connected": "2026-11-13T00:58:12Z",
             "recent_activity": {"type": "mail", "at": "2026-11-13T02:50:00Z", "thing": "Items 1 and 3"}},
            {"name": "wall-ui", "connected": True, "last_connected": "2026-11-13T00:10:00Z",
             "recent_activity": {"type": "doing", "at": "2026-11-13T02:58:00Z", "thing": "building DESKS"}},
            {"name": "validator", "connected": True, "last_connected": "2026-11-13T01:00:00Z",
             "recent_activity": {"type": "mail", "at": "2026-11-13T02:40:00Z", "thing": "review"}},
            {"name": "gardener", "connected": True, "last_connected": "2026-11-13T01:00:00Z",
             "recent_activity": {"type": "todo", "at": "2026-11-13T02:20:00Z", "thing": "ranked 1190"}},
            {"name": "scout", "connected": True, "last_connected": "2026-11-12T20:00:00Z",
             "recent_activity": {"type": "doing", "at": "2026-11-12T23:48:00Z", "thing": "went idle"}},
            {"name": "scribe", "connected": False, "last_connected": "2026-11-12T09:00:00Z",
             "recent_activity": {"type": "doing", "at": "2026-11-12T08:59:00Z", "thing": "filed the glossary pass"}},
            {"name": "indexer", "connected": False, "last_connected": "2026-11-12T21:00:00Z", "recent_activity": None},
            {"name": "auditor", "connected": False, "last_connected": "2026-11-10T03:00:00Z",
             "recent_activity": {"type": "mail", "at": "2026-11-10T02:00:00Z", "thing": "labels review notes"}},
            {"name": "old-desk", "connected": False, "last_connected": "2026-10-01T00:00:00Z", "recent_activity": None},
            {"name": "never-desk", "connected": False, "last_connected": None, "recent_activity": None},
        ],
        "prios": {
            "builder": [
                {"pos": 1, "id": 1191, "ord": 0, "title": "Desks last-connection"},
                {"pos": 2, "id": 1160, "ord": 1, "title": "Wire the Score tab"},
                {"pos": 3, "id": 1153, "ord": 2, "title": "Priorities follow-ups"},
                {"pos": 4, "id": 1100, "ord": 3, "title": "fourth is not shown"},
            ],
            "gardener": [{"pos": 1, "id": 1088, "ord": 0, "title": "Seed scrub", "overdue": "2d"}],
            "scribe": [{"pos": 1, "id": 1140, "ord": 0, "title": "Glossary pass"}],
        },
        "kpis": [
            {"kpi": "doing.task.last_run", "owner": "validator", "value": "failed"},
            {"kpi": "doing.task.last_run", "owner": "builder", "value": "active"},
        ],
        "awayScope": True,
        "sort": "urgency",
        "mine": "",
    }
    ctx.update(over)
    return ctx


def _run(ctx: dict) -> dict:
    return _node(HARNESS, str(ROWS), json.dumps(ctx))


def _line(html: str, desk: str) -> str:
    start = html.rindex('<div class="here-line', 0, html.index('data-here-owner="' + desk + '"'))
    nxt = html.find('<div class="here-line', start + 1)
    sec = html.find('<div class="here-section', start + 1)
    ends = [e for e in (nxt, sec) if e > 0]
    return html[start:min(ends)] if ends else html[start:]


def test_urgency_puts_old_letters_then_failed_runs_then_waiting_then_working_first():
    got = _run(_ctx())
    # builder 2 over a day, gardener 1 over a day, validator last run failed, wall-ui 3 waiting, scout idle.
    assert got["connected"] == ["builder", "gardener", "validator", "wall-ui", "scout"]


def test_working_desks_lead_an_idle_desk_that_needs_attention():
    # scout is idle but has 5 letters over a day and a failed last run: it still sits below every working desk.
    doing = _ctx()["doing"]
    doing["scout"] = dict(doing["scout"], waiting_on_it=_letters(9, 5, "2026-11-09 10:00:00"))
    kpis = _ctx()["kpis"] + [{"kpi": "doing.task.last_run", "owner": "scout", "value": "failed"}]
    got = _run(_ctx(doing=doing, kpis=kpis))
    assert got["connected"] == ["builder", "gardener", "validator", "wall-ui", "scout"]
    # Its old letters and failed run still show in the Needs attention block.
    assert {a["kind"] for a in got["attention"] if a["desk"] == "scout"} == {"letter", "score"}


def test_my_desk_leads_urgency():
    assert _run(_ctx(mine="scout"))["connected"][0] == "scout"


def test_other_sorts():
    assert _run(_ctx(sort="az"))["connected"] == ["builder", "gardener", "scout", "validator", "wall-ui"]
    assert _run(_ctx(sort="za"))["connected"] == ["wall-ui", "validator", "scout", "gardener", "builder"]
    # Recent follows recent_activity.at from pov?part=desks.
    assert _run(_ctx(sort="recent"))["connected"] == ["wall-ui", "builder", "validator", "gardener", "scout"]
    assert _run(_ctx(sort="bogus"))["model"]["sort"] == "urgency"


def test_disconnected_desks_sit_below_dimmed_with_last_seen():
    got = _run(_ctx())
    # Seen in the last 7 days, newest first; a 6-week-old desk and a never-connected desk are left out.
    assert got["away"] == ["indexer", "scribe", "auditor"]
    html = got["html"]
    assert html.index("Disconnected") > max(html.index('data-here-owner="' + d + '"') for d in got["connected"])
    scribe = _line(html, "scribe")
    assert 'class="here-line desk-line away"' in scribe
    assert "last seen 18h ago" in scribe
    assert "last: filed the glossary pass" in scribe
    assert "<button" not in scribe
    assert "last seen 3d ago" in _line(html, "auditor")


def test_row_leads_with_doing_time_then_top_three_priorities_one_based():
    got = _run(_ctx())
    row = _line(got["html"], "builder")
    assert row.index('class="desk-time"') < row.index('class="desk-text"') < row.index('class="desk-prios"')
    assert ">47m<" in row
    ranks = re.findall(r'<span class="rank" title="ord (\d+)">#(\d+)</span>', row)
    assert ranks == [("0", "1"), ("1", "2"), ("2", "3")]
    assert "fourth is not shown" not in row
    assert 'data-doing-go="mail-6035"' in row
    assert "83 letters waiting \u00b7 2 over a day" in row
    assert "oldest since 11-10 14:10" in row
    assert "Last run <b>active</b>" in row
    assert "no priorities set" in _line(got["html"], "validator")


def test_sections_are_open_with_no_dropdowns():
    html = _run(_ctx())["html"]
    assert "<details" not in html and "<summary" not in html and "<select" not in html


def test_needs_attention_lists_real_facts_only():
    att = _run(_ctx())["attention"]
    assert {"desk": "builder", "kind": "letter", "text": "2 letters waiting over a day, oldest since 11-10 14:10"} in att
    assert {"desk": "validator", "kind": "score", "text": "Last run failed"} in att
    assert {"desk": "gardener", "kind": "prio", "text": "#1 todo-1088 overdue 2d"} in att
    assert not any(a["desk"] in ("wall-ui", "scout") for a in att)


def _strip_1192(ctx: dict) -> dict:
    for v in ctx["doing"].values():
        L = v["waiting_on_it"]["letters"]
        L.pop("n_over_day", None)
        L.pop("oldest_at", None)
    return ctx


def test_degrade_without_card_1192_fields():
    got = _run(_strip_1192(_ctx()))
    html = got["html"]
    assert "over a day" not in html
    assert "oldest since" not in html
    assert not [a for a in got["attention"] if a["kind"] == "letter"]
    assert got["connected"][:2] == ["validator", "builder"]
    assert "83 letters waiting</span>" in _line(html, "builder")


def test_degrade_without_labels_scores_stations_or_doing_view():
    got = _run(_ctx(prios=None, kpis=[], stations=None))
    html = got["html"]
    assert 'class="desk-prios' not in html
    assert 'class="desk-scores' not in html
    assert "Disconnected" not in html and got["away"] == []
    bare = _run(_ctx(doing=None, live=[{"owner": "builder", "state": "working", "seat": "seat text"}]))
    row = _line(bare["html"], "builder")
    assert "seat text" in row
    assert 'class="desk-time"' not in row
    assert "waiting" not in row


def test_away_desks_hide_when_the_scope_cannot_name_them():
    assert _run(_ctx(awayScope=False))["away"] == []


def test_empty_office_still_lists_away_desks():
    got = _run(_ctx(live=[]))
    assert "No desks are here." in got["html"]
    assert got["away"] == ["indexer", "scribe", "auditor"]


def test_served_pane_order_keeps_the_redesign_order():
    # The server injects pane_order and boot.js re-appends nav buttons in that order. A tab
    # the order leaves out stays in front, so the default order must name all six (the live
    # Wall showed PRIORITIES first before this).
    from agent_coord.web.wall_logic.knobs import resolve_pane_order

    harness = r"""
    const tabs = JSON.parse(process.argv[1]);
    const order = JSON.parse(process.argv[2]);
    const kids = tabs.map(t => ({ getAttribute: () => t, tab: t }));
    const nav = {
      querySelectorAll: () => kids.slice(),
      appendChild(b) { kids.splice(kids.indexOf(b), 1); kids.push(b); },
    };
    global.document = { querySelector: () => nav };
    (0, eval)(process.argv[3] + "; global.applyPaneOrderCut6 = applyPaneOrderCut6;");
    applyPaneOrderCut6(order);
    process.stdout.write(JSON.stringify(kids.map(k => k.tab)));
    """
    html_order = [t for t, _, _ in _nav().tabs]
    fn = wall_fn("applyPaneOrderCut6")
    want = [t for t, _ in TABS]
    assert _node(harness, json.dumps(html_order), json.dumps(resolve_pane_order(None)), fn) == want
    boot_default = re.search(r'pane_order: (\[[^\]]*\])', BOOT.read_text(encoding="utf-8")).group(1)
    assert _node(harness, json.dumps(html_order), boot_default, fn) == want
