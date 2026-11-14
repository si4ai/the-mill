"""Score tab on a trimmed real part=scores read, and the Older subtab on real stored rows."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RD = REPO / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
FIXTURE = Path(__file__).with_name("score_part1_real_fixture.json")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# 14 Nov 2026 05:00 UTC, about when the read was taken.
NOW = "2026-11-14T05:00:00Z"

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const fx = JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8'));
const now = Date.parse(process.argv[3]);
const opts = JSON.parse(process.argv[4] || '{}');
const R = WallRd, V = WallRdView;
const b = { now, scope: { rosters: ['Office'], range: '7d', label: 'Office' }, data: { povScores: fx },
  kpis: fx.older_kpis, inScope: function () { return true; }, offDesk: function () { return false; } };
const m = R.score(b, Object.assign({ now }, opts));
const html = V.score(m);
const cells = {};
m.rows.forEach(r => r.cells.forEach(c => { cells[r.desk + '|' + c.name] = { text: c.text, empty: c.empty, reason: c.reason, tint: c.tint, cmp: c.cmp }; }));
console.log(JSON.stringify({
  desks: m.rows.map(r => r.desk), quietN: m.quietN, sub: m.sub, flags: m.flags,
  cols: m.cols.map(c => ({ name: c.name, label: c.label, desc: c.desc, pending: c.pending, n: c.n_active, median: c.median })),
  emptyCols: m.emptyCols.map(c => c.name), cells, detail: m.detail,
  older: m.older, html, styleAttr: (html.match(/style=/g) || []).length
}));
"""


def run(opts: dict | None = None) -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(RD), str(FIXTURE), NOW, json.dumps(opts or {})],
                         capture_output=True, text=True, check=False, timeout=30)
    if out.returncode:
        raise AssertionError(out.stderr or out.stdout)
    return json.loads(out.stdout)


def test_real_read_shape_is_what_the_tab_reads():
    fx = json.loads(FIXTURE.read_text())
    assert set(fx) >= {"window", "desks", "unviewed"}
    row = fx["desks"][0]["scores"][0]
    assert set(row) == {"name", "kind", "owner", "value", "reason", "anchor_at", "num", "den", "items", "target", "window", "rollup"}
    assert all(len(d["scores"]) == 17 for d in fx["desks"])


def test_every_part1_score_has_a_plain_label_and_meaning():
    got = run()
    assert len(got["cols"]) == 17  # empty columns show by default
    for c in got["cols"]:
        assert c["label"] and c["label"] != c["name"]
        assert c["desc"].endswith(".")
    pending = {c["name"] for c in got["cols"] if c["pending"]}
    assert "hint_no_turn_n" in pending and "oldest_unread_ask_age_ms" not in pending
    assert "What these mean" in got["html"]
    assert got["styleAttr"] == 0


def test_quiet_desks_and_empty_columns_fold_behind_toggles():
    got = run()
    assert got["quietN"] == 2 and "cold-p0-a" not in got["desks"] and "scout" not in got["desks"]
    shown = run({"open": {"_quiet": True, "_empty": False}})
    assert "cold-p0-a" in shown["desks"] and len(shown["desks"]) == 9
    assert len(shown["cols"]) + len(shown["emptyCols"]) == 17
    assert "ask_to_answer_ms" in shown["emptyCols"] and "ask_to_answer_ms" not in [c["name"] for c in shown["cols"]]


def test_real_cells_age_share_and_median():
    got = run({"open": {"_quiet": True}})
    c = got["cells"]
    # anchor 2026-11-06 22:27:23 naive utc, read at 2026-11-14 05:00 utc: 7d 6h
    assert c["build-ui|oldest_unread_ask_age_ms"]["text"] == "7d 6h"
    # a share with no finished wakes is a dash with a reason, not 0/0
    assert c["build-ui|stale_share"]["empty"] and c["build-ui|stale_share"]["reason"] == "no finished wakes in this window"
    assert c["builder|stale_share"]["text"] == "0%"
    assert c["build-ui|hint_no_turn_n"]["reason"] == "not built yet"
    cols = {x["name"]: x for x in got["cols"]}
    # the median counts only desks with a value
    assert cols["oldest_unread_ask_age_ms"]["n"] == 4
    assert cols["unanswered_required_n"]["n"] == 4
    assert c["wall-ui|force_taken_n"]["tint"] == "worse"  # 1 over a median of 0


def test_detail_leads_with_the_meaning():
    got = run({"selected": "build-ui|oldest_unread_ask_age_ms"})
    d = got["detail"]
    assert d["desc"].startswith("How long the oldest letter")
    assert len(d["items"]) == 5 and d["items"][0]["sel"].startswith("mail-")
    assert "Lower is better." in got["html"] and "rd-sc-items" in got["html"]


def test_older_subtab_lists_every_stored_score_once():
    got = run({"sub": "older"})
    assert got["sub"] == "older"
    o = got["older"]
    names = [r["kpi"] for f in o["families"] for r in f["rows"]]
    assert len(names) == len(set(names)) == o["names"]
    sit = next(f for f in o["families"] if f["key"] == "sitting")
    drop = next(r for r in sit["rows"] if r["kpi"] == "mill-desk.hint_drop")
    assert drop["n"] >= 5 and drop["label"] == "Dropped hints" and drop["note"]
    doing = next(f for f in o["families"] if f["key"] == "doing")
    assert doing["rows"][0]["note"]  # a plain meaning when the server leaves no note
    assert 'data-rd-score-sub="older"' in got["html"] and 'aria-selected="true"' in got["html"]
    assert "rd-sc-table" not in got["html"]
    assert got["styleAttr"] == 0
