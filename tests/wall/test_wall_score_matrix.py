"""Score tab matrix: age from the anchor, median tint, a null reason, sort, and area groups."""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RD = REPO / "agent_coord" / "web" / "wall_ui" / "default" / "rd"
PART1_PY = REPO / "agent_coord" / "server" / "records" / "score_part1.py"
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
  groups: m && m.areas.map(a => ({ key: a.key, open: a.open, n: a.cols.length })),
  shown: m && m.shown.map(s => s.summary ? '@' + s.area : s.col.name),
  openDefault: m && m.openDefault,
  byArea: m && m.rows.reduce((a, r) => {
    a[r.desk] = {};
    Object.keys(r.byArea).forEach(k => { const x = r.byArea[k]; a[r.desk][k] = [x.worse, x.far, x.filled, x.text, x.tint]; });
    return a;
  }, {}),
  openMax: R.SCORE_OPEN_MAX,
  areaOfName: (JSON.parse(process.argv[6] || '[]')).reduce((a, n) => { a[n] = R.scoreArea(n); return a; }, {}),
  utcMs: R.utc('2026-11-11 19:59:00'),
  html,
  head,
  styleAttr: (html.match(/style=/g) || []).length
}));
"""


def score(payload: dict, opts: dict | None = None, scope: dict | None = None, names: list | None = None) -> dict:
    out = subprocess.run(
        [NODE, "-e", SCRIPT, "--", str(RD), json.dumps(payload), NOW, json.dumps(opts or {}),
         json.dumps(scope or {"rosters": ["Office"], "range": "7d", "label": "Office"}), json.dumps(names or [])],
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
    assert area_keys == ["mail", "cards", "holds", "wakes"]
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


# score part 1 (card 1212): the names GET /api/pov?part=scores serves, and the area each paints under.
PART1 = {
    "oldest_unread_ask_age_ms": "mail",
    "unanswered_required_n": "mail",
    "unanswered_fyi_n": "mail",
    "ask_to_answer_ms": "mail",
    "outgoing_unanswered_n": "mail",
    "claimed_no_pass_age_ms": "cards",
    "claimed_age_ms": "cards",
    "claimed_claimant_inactive_n": "cards",
    "claimed_past_eta_n": "cards",
    "shipped_unaccepted_age_ms": "cards",
    "hold_open_age_ms": "holds",
    "force_taken_n": "holds",
    "stale_share": "wakes",
    "ended_no_pass_or_mail_n": "wakes",
    "to_done_ms": "cards",
    "stale_done_share": "wakes",
    "hint_no_turn_n": "wakes",
}


def served_names() -> list[str]:
    """SCORE_NAMES from the server when this tree has it, else the part 1 list above."""
    if PART1_PY.exists():
        for node in ast.walk(ast.parse(PART1_PY.read_text())):
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "SCORE_NAMES" for t in node.targets):
                return [ast.literal_eval(e) for e in node.value.elts]
    return list(PART1)


def big(names: list[str], desks: int = 6) -> dict:
    out = []
    for i in range(desks):
        rows = []
        for j, n in enumerate(names):
            if n.endswith("_ms"):
                rows.append(entry(n, anchor_at=f"2026-11-1{1 + (i + j) % 3} 0{i}:00:00"))
            elif n.endswith("_share"):
                rows.append(entry(n, value=(i + 1) / 10, num=i + 1, den=10))
            else:
                rows.append(entry(n, value=(i * (j + 1)) % 7))
        out.append({"desk": f"desk-{i}", "roster": "the-mill" if i < 3 else "garden", "scores": rows})
    return {"window": "7d", "desks": out}


def test_every_part1_name_has_a_real_area():
    names = served_names()
    assert len(names) >= 17
    got = score(office(), names=names + ["brand_new_metric_n", "wake_lag_ms", "mail_bounce_n"])
    for n in names:
        assert got["areaOfName"][n] != "other", n
        if n in PART1:
            assert got["areaOfName"][n] == PART1[n], n
    # an unseen name joins its prefix family, or other when it has none
    assert got["areaOfName"]["brand_new_metric_n"] == "other"
    assert got["areaOfName"]["wake_lag_ms"] == "wakes"
    assert got["areaOfName"]["mail_bounce_n"] == "mail"


def test_many_scores_open_collapsed_with_worse_counts():
    names = served_names() + ["brand_new_metric_n"]
    got = score(big(names))
    assert len(got["cols"]) == len(names) > got["openMax"]
    assert got["openDefault"] is False
    keys = [g["key"] for g in got["groups"]]
    assert keys == ["mail", "cards", "holds", "wakes", "other"]
    assert all(g["open"] is False for g in got["groups"])
    # shut: one summary column per area, nothing per score
    assert got["shown"] == ["@mail", "@cards", "@holds", "@wakes", "@other"]
    # the summary counts the cells tinted worse or far in that area
    for desk, areas in got["byArea"].items():
        for area, (worse, far, filled, text, tint) in areas.items():
            mine = [c for k, c in got["cells"].items() if k.startswith(desk + "|") and k.split("|", 1)[1] in
                    [n for n in names if (PART1.get(n) or ("other" if n == "brand_new_metric_n" else "wakes")) == area]]
            assert worse == sum(1 for c in mine if c["tint"]), (desk, area)
            assert far == sum(1 for c in mine if c["tint"] == "far")
            assert text == (str(worse) if filled else "\u2014")
            assert tint == ("far" if far else ("worse" if worse else ""))
    html = got["html"]
    assert html.count('data-rd-score-area="mail"') >= 1 + 6  # header + one summary cell per desk
    assert 'aria-expanded="false"' in html and 'aria-expanded="true"' not in html
    assert 'data-rd-score-sort="@cards"' in html
    assert "data-rd-score-sort=\"oldest_unread_ask_age_ms\"" not in html
    assert got["styleAttr"] == 0


def test_one_group_expanded_from_saved_pick():
    names = served_names()
    got = score(big(names), opts={"open": {"cards": True}})
    opened = {g["key"]: g["open"] for g in got["groups"]}
    assert opened == {"mail": False, "cards": True, "holds": False, "wakes": False}
    cards = [n for n in names if PART1[n] == "cards"]
    assert got["shown"] == ["@mail"] + cards + ["@holds", "@wakes"]
    html = got["html"]
    assert 'colspan="%d" scope="colgroup"' % len(cards) in html
    assert 'data-rd-score-area="cards" tabindex="0" role="button" aria-expanded="true"' in html
    assert 'data-rd-score-sort="claimed_age_ms"' in html
    # narrow cards group the same way: an open section lists its scores, shut ones only a count
    assert 'class="rd-sc-card-area open' in html
    assert "rd-sc-card-sec" in html


def test_small_matrix_opens_and_saved_shut_wins():
    got = score(office())
    assert got["openDefault"] is True
    assert all(g["open"] for g in got["groups"])
    assert "@mail" not in got["shown"]
    shut = score(office(), opts={"open": {"mail": False}})
    assert shut["shown"][0] == "@mail"
    assert "oldest_unread_ask_age_ms" not in shut["shown"]


def test_unknown_name_falls_into_other_with_a_label():
    payload = office()
    for d in payload["desks"]:
        d["scores"].append(entry("brand_new_metric_n", value=1))
    got = score(payload)
    other = [g for g in got["groups"] if g["key"] == "other"]
    assert other and other[0]["n"] == 1
    assert {c["name"]: c["label"] for c in got["cols"]}["brand_new_metric_n"] == "Brand new metric"


def test_sort_by_area_summary():
    names = served_names()
    got = score(big(names), opts={"sortCol": "@mail", "sortDir": "desc"})
    worse = [got["byArea"][d]["mail"][0] for _, d, _ in got["desks"]]
    # rows sort inside each roster by the mail worse count
    mill = [got["byArea"][d]["mail"][0] for r, d, _ in got["desks"] if r == "the-mill"]
    assert mill == sorted(mill, reverse=True)
    assert len(worse) == 6
