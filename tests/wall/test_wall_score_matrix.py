"""Score tab matrix: age from the anchor, median tint, a null reason, and sort."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RD = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# 13 Nov 2026 23:59 UTC. an unread ask from 11 Nov 19:59 UTC is then 2d 4h old.
NOW = "2026-11-13T23:59:00Z"

SCRIPT = r"""
require(process.argv[1] + '/rd-model.js');
require(process.argv[1] + '/rd-view.js');
const payload = JSON.parse(process.argv[2]);
const now = Date.parse(process.argv[3]);
const opts = JSON.parse(process.argv[4] || '{}');
const scope = JSON.parse(process.argv[5] || '{"rosters":["Office"],"range":"7d","label":"Office"}');
const R = WallRd, V = WallRdView;
const b = { now, scope, data: { povScores: payload }, offDesk: function () { return false; } };
const m = R.score(b, Object.assign({ now }, opts));
const html = m ? V.score(m) : '';
const head = m ? V.paneHead('score', { scope }) : '';
function row(desk) { return (m && m.rows || []).find(r => r.desk === desk) || null; }
function cell(desk, name) {
  const r = row(desk);
  return r ? r.cells.find(c => c.name === name) : null;
}
console.log(JSON.stringify({
  known: !!m,
  window: m && m.window,
  windows: m && m.windows,
  off: m && m.off,
  n_active: m && m.n_active,
  areas: m && m.areas.map(a => [a.key, a.cols.map(c => c.name)]),
  cols: m && m.cols.map(c => ({ name: c.name, label: c.label, kind: c.kind, median: c.median, medianText: c.medianText, n_active: c.n_active })),
  desks: m && m.groups.reduce((a, g) => a.concat(g.rows.map(r => [g.label, r.desk, r.worse])), []),
  cells: m && m.rows.reduce((a, r) => {
    r.cells.forEach(c => { a[r.desk + '|' + c.name] = { text: c.text, tint: c.tint, empty: c.empty, zero: c.zero, title: c.title, cmp: c.cmp, reason: c.reason }; });
    return a;
  }, {}),
  detail: m && m.detail,
  labels: {
    idle: R.scoreLabel('claimed_idle_age_ms'),
    noPass: R.scoreLabel('claimed_no_pass_age_ms'),
    unknown: R.scoreLabel('brand_new_metric_n')
  },
  areasOf: {
    unread: R.scoreArea('oldest_unread_ask_age_ms'),
    claimed: R.scoreArea('claimed_idle_age_ms'),
    hold: R.scoreArea('hold_open_age_ms'),
    other: R.scoreArea('brand_new_metric_n')
  },
  utcMs: R.utc('2026-11-11 19:59:00'),
  html,
  head,
  styleAttr: (html.match(/style=/g) || []).length
}));
"""


def score(payload: dict, opts: dict | None = None, scope: dict | None = None) -> dict:
    out = subprocess.run(
        [NODE, "-e", SCRIPT, "--", str(RD), json.dumps(payload), NOW, json.dumps(opts or {}), json.dumps(scope or {"rosters": ["Office"], "range": "7d", "label": "Office"})],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if out.returncode:
        raise AssertionError(out.stderr or out.stdout)
    return json.loads(out.stdout)


def entry(name, *, kind=None, value=None, reason=None, anchor_at=None, num=None, den=None, items=None, target=None, window="7d"):
    if kind is None:
        kind = "share" if den is not None else ("age" if name.endswith("_ms") else "count")
    return {
        "name": name, "kind": kind, "owner": "desk", "value": value, "reason": reason,
        "anchor_at": anchor_at, "num": num, "den": den, "items": items or [],
        "target": target, "window": window, "rollup": {"median": None, "n_active": 4, "window": window},
    }


def office():
    names = [
        "oldest_unread_ask_age_ms",
        "unanswered_required_n",
        "claimed_no_pass_age_ms",
        "hold_open_age_ms",
        "force_taken_n",
        "stale_share",
    ]
    def scores(vals):
        out = []
        for n in names:
            raw = dict(vals.get(n) or {})
            raw.setdefault("name", n)
            out.append(entry(n, **{k: v for k, v in raw.items() if k != "name"}))
        return out

    return {
        "window": "7d",
        "desks": [
            {"desk": "wall-ui", "roster": "the-mill", "scores": scores({
                # 2d 4h before NOW; a leftover value must be ignored when the anchor is present
                "oldest_unread_ask_age_ms": {"anchor_at": "2026-11-11 19:59:00", "value": 999, "items": [11, 11, 12]},
                "unanswered_required_n": {"value": 8},
                "claimed_no_pass_age_ms": {"anchor_at": "2026-11-13 22:59:00", "items": [91]},
                "hold_open_age_ms": {"reason": "none"},
                "force_taken_n": {"value": 0},
                "stale_share": {"value": 0.8, "num": 8, "den": 10},
            })},
            {"desk": "builder", "roster": "the-mill", "scores": scores({
                "oldest_unread_ask_age_ms": {"anchor_at": "2026-11-12 23:59:00", "items": [21]},
                "unanswered_required_n": {"value": 2},
                "claimed_no_pass_age_ms": {"anchor_at": "2026-11-13 11:59:00", "items": [92]},
                "hold_open_age_ms": {"anchor_at": "2026-11-12 23:59:00", "items": [3, 3]},
                "force_taken_n": {"value": 1},
                "stale_share": {"value": 0.2, "num": 2, "den": 10},
            })},
            {"desk": "gardener", "roster": "garden", "scores": scores({
                "oldest_unread_ask_age_ms": {"anchor_at": "2026-11-08 23:59:00"},
                "unanswered_required_n": {"value": 3},
                "claimed_no_pass_age_ms": {"reason": "inactive"},
                "hold_open_age_ms": {"anchor_at": "2026-11-13 20:59:00", "items": [4]},
                "force_taken_n": {"value": 2},
                "stale_share": {"value": 0.1, "num": 1, "den": 10},
            })},
            {"desk": "scout", "roster": "garden", "scores": scores({
                "oldest_unread_ask_age_ms": {"reason": "none"},
                "unanswered_required_n": {"value": 2},
                "claimed_no_pass_age_ms": {"anchor_at": "2026-11-13 21:59:00"},
                "hold_open_age_ms": {"anchor_at": "2026-11-13 11:59:00", "items": [5]},
                "force_taken_n": {"value": 1},
                "stale_share": {"value": 0.5, "num": 5, "den": 10},
            })},
        ],
    }


def test_unserved_payload_stays_hidden():
    got = score(None)  # type: ignore[arg-type]
    # JSON null becomes payload null; the model should still hide
    # (we pass the string 'null' as payload via json.dumps(None))
    assert got["known"] is False


def test_age_uses_anchor_and_ignores_value():
    got = score(office())
    # utc string without Z is treated as UTC
    assert got["utcMs"] == 1794427140000
    cell = got["cells"]["wall-ui|oldest_unread_ask_age_ms"]
    assert cell["text"] == "2d 4h"
    # 2d 4h in ms
    assert cell["cmp"] == 52 * 3600 * 1000
    assert cell["empty"] is False


def test_null_reason_is_a_quiet_dash():
    got = score(office())
    cell = got["cells"]["wall-ui|hold_open_age_ms"]
    assert cell["text"] == "\u2014"
    assert cell["empty"] is True
    assert cell["title"] == "none"
    assert cell["reason"] == "none"
    assert cell["tint"] == ""
    assert "\u2014" in got["html"]
    # gardener's claimed idle is also empty with a reason
    idle = got["cells"]["gardener|claimed_no_pass_age_ms"]
    assert idle["text"] == "\u2014" and idle["title"] == "inactive"


def test_zero_is_faint_and_not_tinted():
    got = score(office())
    cell = got["cells"]["wall-ui|force_taken_n"]
    assert cell["text"] == "0"
    assert cell["zero"] is True
    assert cell["tint"] == ""
    assert "zero" in got["html"]


def test_median_tint_worse_and_far():
    got = score(office())
    cols = {c["name"]: c for c in got["cols"]}
    # ages: wall-ui 52h, builder 24h, gardener 5d=120h, scout null
    # series [52h, 24h, 120h], sorted 24, 52, 120, mid=52h. text 2d 4h
    assert cols["oldest_unread_ask_age_ms"]["medianText"] == "2d 4h"
    assert got["cells"]["builder|oldest_unread_ask_age_ms"]["tint"] == ""  # below
    assert got["cells"]["wall-ui|oldest_unread_ask_age_ms"]["tint"] == ""  # at
    assert got["cells"]["gardener|oldest_unread_ask_age_ms"]["tint"] == "far"  # 120h > 2*52
    # counts: 8, 2, 3, 2 -> sorted 2,2,3,8 mid=3. 8 is far ( > 6 )
    assert cols["unanswered_required_n"]["median"] == 3
    assert got["cells"]["wall-ui|unanswered_required_n"]["tint"] == "far"
    assert got["cells"]["gardener|unanswered_required_n"]["tint"] == ""  # at
    assert got["cells"]["builder|unanswered_required_n"]["tint"] == ""
    # shares: 0.8, 0.2, 0.1, 0.5 -> sorted 0.1,0.2,0.5,0.8 mid=0.5. 0.8 is worse, not far (2x is 1.0)
    assert got["cells"]["wall-ui|stale_share"]["text"] == "8/10"
    assert got["cells"]["wall-ui|stale_share"]["tint"] == "worse"
    assert got["cells"]["scout|stale_share"]["tint"] == ""
    # no colour when the median is missing: a lone desk
    one = {"window": "7d", "desks": [office()["desks"][0]]}
    lone = score(one)
    assert lone["cols"][0]["median"] is None
    assert all(c["tint"] == "" for c in lone["cells"].values())


def test_desks_sort_by_worse_count_then_column():
    got = score(office())
    # default: worse desc, grouped by roster (rosters by total worse, then desks)
    order = [d for _, d, _ in got["desks"]]
    worse = {d: w for _, d, w in got["desks"]}
    rosters = [r for r, _, _ in got["desks"]]
    # the-mill has more worse cells in total, so it leads; garden follows
    assert rosters[0] == "the-mill" and rosters[-1] == "garden"
    # wall-ui and builder are tied on worse cells, so the row sort is by name
    assert worse["wall-ui"] == worse["builder"] == 2
    assert worse["scout"] == 0
    assert order[:2] == ["builder", "wall-ui"]
    assert order[-1] == "scout"
    # column sort: unanswered_required_n desc -> wall-ui (8), gardener (3), then 2s
    by_col = score(office(), opts={"sortCol": "unanswered_required_n", "sortDir": "desc"})
    desks = [d for _, d, _ in by_col["desks"]]
    assert desks[0] == "wall-ui"
    assert "gardener" in desks[1:3]


def test_labels_and_areas_cover_renames_and_unknowns():
    got = score(office())
    assert got["labels"]["idle"] == got["labels"]["noPass"] == "Claimed idle"
    assert got["labels"]["unknown"] == "Brand new metric"
    assert got["areasOf"] == {"unread": "mail", "claimed": "cards", "hold": "holds", "other": "other"}
    area_keys = [a[0] for a in got["areas"]]
    assert area_keys == ["mail", "cards", "holds"]
    assert "oldest_unread_ask_age_ms" in got["areas"][0][1]


def test_detail_dedupes_items_and_view_is_csp_safe():
    got = score(office(), opts={"selected": "wall-ui|oldest_unread_ask_age_ms"})
    d = got["detail"]
    assert d["label"] == "Oldest unread ask"
    assert d["desk"] == "wall-ui"
    assert d["text"] == "2d 4h"
    assert d["ageText"] == "2d 4h"
    assert d["anchorMs"] == 1794427140000
    assert [it["id"] for it in d["items"]] == ["11", "12"]
    assert d["items"][0]["tab"] == "mail" and d["items"][0]["sel"] == "mail-11"
    card = score(office(), opts={"selected": "builder|hold_open_age_ms"})["detail"]
    assert card["items"][0]["tab"] == "collab" and card["items"][0]["sel"] == "hold-3"
    assert got["styleAttr"] == 0
    assert 'data-rd-score-sort="oldest_unread_ask_age_ms"' in got["html"]
    assert "24h" in got["head"] and "7d" in got["head"] and "30d" in got["head"]
    assert "Today" not in got["head"]
    # hold items from builder are hold ids, mail items are letter ids
    assert "mail-11" in got["html"] and 'data-rd-go="mail"' in got["html"]
