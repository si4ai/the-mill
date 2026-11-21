"""Card 1255: the Wall paints a name a row's deleted_names lists as deleted.

The server (PR #482) gives any row that names a retired desk or a trashed roster, label or
tree a sorted deleted_names list, those names as the row spells them; nested objects (a
letter's sender, each mail_to, a PRIORITIES row's card, a doing view's doings[]) are marked
on their own. The Wall strikes exactly those names, adds a small "deleted" tag, and keeps the
row where it is. A row with no list paints exactly as before. Runs lib/data.js, rd-model.js,
rd-view.js and priorities-paint.js in Node over a fake feed.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

NOW = "2026-11-20T20:00:00Z"
LIVE = "2026-11-20 19:59:00"
GONE = ["oldie"]


def seat(owner: str, **extra) -> dict:
    return dict({"owner": owner, "alive": True, "stale": False, "heartbeat": LIVE}, **extra)


FEED = {
    "agents": {"Office": [seat("builder"), seat("oldie", deleted_names=GONE), seat("napper")]},
    "doing": {
        "builder": {"owner": "builder", "n": 0, "doings": [], "alive": True, "stale": False},
        "oldie": {"owner": "oldie", "n": 0, "doings": [], "alive": True, "stale": False, "deleted_names": GONE},
        # Marked only on a nested doings[] row: still names the desk deleted.
        "napper": {"owner": "napper", "n": 1, "alive": True, "stale": False,
                   "doings": [{"id": 4, "created": LIVE, "text": "nap", "state": "running", "deleted_names": ["napper"]}]},
    },
    "mail": {"Office": [
        # The sender object is marked on its own; the letter itself carries no list.
        {"id": 1, "created": LIVE, "body": "hello from oldie",
         "sender": {"deskId": "oldie", "roster": "Office", "deleted_names": GONE},
         "mail_tos": [{"deskId": "builder", "receipt": 0}]},
        # A mail_to marked on its own, and the letter's to list.
        {"id": 2, "created": LIVE, "body": "to oldie", "to": ["oldie"], "deleted_names": GONE,
         "sender": {"deskId": "builder", "roster": "Office"},
         "mail_tos": [{"deskId": "oldie", "receipt": 1, "deleted_names": GONE}]},
    ]},
}
SCORES = {"desks": [
    {"desk": "oldie", "roster": "Office", "deleted_names": GONE, "scores": [{"name": "open_holds_n", "value": 2}]},
    {"desk": "builder", "roster": "Office", "scores": [{"name": "open_holds_n", "value": 1}]},
]}
PRIO = [
    {"label": "human-priorities", "type": "todo", "id": 7, "ord": 0,
     "card": {"need": "old card", "status": "claimed", "volunteer": "oldie", "deleted_names": GONE}},
    {"label": "human-priorities", "type": "todo", "id": 8, "ord": 1,
     "card": {"need": "live card", "status": "claimed", "volunteer": "builder"}},
]

SCRIPT = r"""
const fs = require('fs');
const [ui, feedS, scoresS, prioS, nowS, withLib] = process.argv.slice(1);
global.window = global;
if (withLib === '1') require(ui + '/lib/data.js');
require(ui + '/default/rd/rd-model.js');
require(ui + '/default/rd/rd-view.js');
(0, eval)(fs.readFileSync(ui + '/default/priorities/priorities-paint.js', 'utf8'));
const R = WallRd, V = WallRdView, now = Date.parse(nowS);
const b = R.base(JSON.parse(feedS), {rosters: ['Office'], range: '7d'}, now);
const m = R.desks(b, {sort: 'urgency'});
const rows = {};
V.desksList(m, now).split('<div class="rd-here-line').slice(1).forEach(x => { rows[/data-rd-pickdesk="([^"]+)"/.exec(x)[1]] = x; });
const detail = {};
Object.keys(rows).forEach(n => { detail[n] = V.deskDetail(R.deskDetail(b, n), now); });
const sb = { now, scope: {rosters: ['Office'], range: '7d', label: 'Office'}, data: { povScores: JSON.parse(scoresS) }, offDesk: () => false };
const sm = R.score(sb, { now, selected: 'oldie|open_holds_n' });
const prio = prioHtml(prioModel({ rows: JSON.parse(prioS), desks: ['builder'], now }));
const lib = withLib === '1' ? {
  bare: wallDelName({}, 'oldie', 'oldie'), none: wallDelName(null, 'oldie', 'x'),
  hit: wallDelName({deleted_names: ['oldie']}, 'oldie', 'oldie'), miss: wallDelName({deleted_names: ['oldie']}, 'builder', 'builder'),
  any: wallDelIs([null, {deleted_names: ['b']}], 'b'), empty: wallDelIs({deleted_names: ['']}, ''),
} : null;
console.log(JSON.stringify({ rows, detail, score: V.score(sm), prio, lib }));
"""


def run(feed: dict = FEED, scores: dict = SCORES, prio: list = PRIO, lib: bool = True) -> dict:
    out = subprocess.run([NODE, "-e", SCRIPT, "--", str(UI), json.dumps(feed), json.dumps(scores), json.dumps(prio),
                          NOW, "1" if lib else "0"], capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def strip(x):
    """The same feed from a server with no marks: every deleted_names key gone, at any depth."""
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k != "deleted_names"}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def struck(html: str) -> list[str]:
    return re.findall(r'<s class="nm-del" title="deleted">([^<]*)</s> <span class="nm-del-tag">deleted</span>', html)


def test_helper_strikes_only_listed_names():
    lib = run()["lib"]
    assert lib["bare"] == "oldie" and lib["none"] == "x" and lib["miss"] == "builder"
    assert lib["hit"] == '<s class="nm-del" title="deleted">oldie</s> <span class="nm-del-tag">deleted</span>'
    assert lib["any"] is True and lib["empty"] is False


def test_desk_row_and_detail_strike_a_retired_desk_in_place():
    got = run()
    assert set(got["rows"]) == {"builder", "oldie", "napper"}
    assert struck(got["rows"]["oldie"]) == ["oldie"]
    assert struck(got["rows"]["builder"]) == []
    assert struck(got["detail"]["oldie"].split("</div>")[0]) == ["oldie"]


def test_nested_doings_row_marks_its_desk():
    got = run()
    assert struck(got["rows"]["napper"]) == ["napper"]


def test_letters_mark_the_sender_object_and_each_mail_to_on_their_own():
    det = run()["detail"]["builder"]
    # Letter 1: only the sender object is marked; builder (to) stays plain.
    # Letter 2: the letter's to list and its mail_to mark oldie; the sender builder stays plain.
    assert struck(det) == ["oldie", "oldie"]
    assert "<b>builder</b>" in det
    assert "to " + '<s class="nm-del" title="deleted">oldie</s> <span class="nm-del-tag">deleted</span>' in det


def test_score_rows_and_detail_strike_the_deleted_desk_only():
    html = run()["score"]
    # Matrix row, phone card head, detail title and detail desk chip.
    assert struck(html) == ["oldie"] * 4
    assert '<th class="rd-sc-desk" scope="row">builder' in html


def test_priorities_card_object_marks_its_holder_and_column():
    html = run()["prio"]
    # The human list's holder (card object marked on its own) and the column that card opens.
    assert struck(html) == ["oldie", "oldie"]
    assert '<span class="prio-who">builder</span>' in html and "<h3>builder</h3>" in html


def test_rows_without_the_key_paint_exactly_as_before():
    bare = run(strip(FEED), strip(SCORES), strip(PRIO))
    assert "nm-del" not in json.dumps({k: bare[k] for k in ("rows", "detail", "score", "prio")})
    # With no marks the helper changes nothing: the same HTML as with no helper loaded at all,
    # which is the Wall before card 1255 for these views.
    nolib = run(strip(FEED), strip(SCORES), strip(PRIO), lib=False)
    assert {k: bare[k] for k in ("rows", "detail", "score", "prio")} == {k: nolib[k] for k in ("rows", "detail", "score", "prio")}
    # And a marked feed on a Wall without the helper also paints as before.
    marked_nolib = run(lib=False)
    assert {k: marked_nolib[k] for k in ("rows", "detail", "score", "prio")} == {k: nolib[k] for k in ("rows", "detail", "score", "prio")}


def test_a_name_not_in_the_list_is_not_struck():
    feed = copy.deepcopy(FEED)
    # The row lists a name it does not spell: nothing on it is struck.
    feed["agents"]["Office"][0]["deleted_names"] = ["somebody-else"]
    got = run(feed)
    assert struck(got["rows"]["builder"]) == []


PLAN = r"""
const fs = require('fs');
const ui = process.argv[1];
global.window = global;
require(ui + '/lib/data.js');
const boot = fs.readFileSync(ui + '/default/boot.js', 'utf8');
global.esc = (0, eval)('(' + /const esc = (s => [^\n]+);/.exec(boot)[1] + ')');
global.nmDel = (0, eval)('(' + /const nmDel = ([^\n]+);/.exec(boot)[1] + ')');
global.planNormStatus = s => String(s || ''); global.dt = s => String(s || '');
const src = /    function issueCard\(r\) \{[\s\S]*?\n    \}\n/.exec(fs.readFileSync(ui + '/default/todo/todo-paint.js', 'utf8'))[0];
const issueCard = (0, eval)('(' + src.trim() + ')');
const rows = JSON.parse(process.argv[2]);
console.log(JSON.stringify(rows.map(issueCard)));
"""


def test_plan_card_strikes_a_trashed_label_and_keeps_the_rest():
    rows = [{"id": 31, "title": "t", "label": "old-label", "status": "parked", "who": "builder", "deleted_names": ["old-label"]},
            {"id": 32, "title": "t", "label": "wall", "status": "parked", "who": "builder"}]
    out = subprocess.run([NODE, "-e", PLAN, "--", str(UI), json.dumps(rows)], capture_output=True, text=True, check=True, timeout=30)
    gone, live = json.loads(out.stdout)
    assert struck(gone) == ["old-label"] and "by <b>builder</b>" in gone
    assert "nm-del" not in live and "label <b>wall</b>" in live
