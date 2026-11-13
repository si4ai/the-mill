# -*- coding: utf-8 -*-
"""#715: a strip chip whose part this scope has not read shows the loading mark, never 0.

Runs the real strip(), wallResetStripReady() and wallSyncStripTabLoading() from
boot.js in Node against stub panes, so the test checks behavior, not source text.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent_coord.web.wall_logic.packs import wall_ui_root

BOOT = wall_ui_root() / "default" / "boot.js"

HARNESS = r"""
const fs = require('fs');
const body = fs.readFileSync(process.argv[2], 'utf8');
function chipEl(id, num, cue) {
  const kids = { b: { textContent: num }, cue: cue ? { textContent: cue, remove() { kids.cue = null; } } : null, load: null };
  const cls = new Set();
  return {
    id, attrs: {}, cls,
    classList: { add(c) { cls.add(c); }, remove(c) { cls.delete(c); } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    querySelector(sel) {
      if (sel === 'b') return kids.b;
      if (sel === '.kpi-cue') return kids.cue;
      if (sel === '.kpi-load') return kids.load;
      return null;
    },
    insertBefore(node) { kids.load = { remove() { kids.load = null; } }; },
    kids,
  };
}
const els = {
  strip: { innerHTML: '' },
  // A pane still painted by the previous roster: real content, wrong scope.
  parked: { innerHTML: 'card 1', textContent: 'card 1' },
  here: { innerHTML: 'installer working', textContent: 'installer working' },
};
const document = {
  getElementById(id) { return els[id] || null; },
  createElement() { return { set innerHTML(v) {}, firstChild: {} }; },
  addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
};
const stubs = {
  document,
  _stripReady: { session: false, floor: false, todo: false, score: false, mail: false },
  _officeScoreSeen: true, apiOk: true,
  wallClockLine: () => '', wallStripLoadHtml: () => '<span class="kpi-load"></span>',
  wallHasRealContent: () => true,
  uniqueDesksByOwner: (a) => a, esc: (s) => String(s),
  millTodoCards: (d) => (d.needs || []).concat(d.issues || []),
  hereScoreRows: () => [], floorShared: (d) => ({ rows: (d.between || []).length }),
  floorProjectQuery: () => '', floorScope: () => ({ key: 'project:x', query: 'project=x' }),
  activityBetweenQuery: () => ({ key: 'k', url: '/x' }),
  wallFetchFloorParts: () => Promise.resolve({}), wallFetchFloorV1: () => new Promise(() => {}),
  wallPaintFloorPartEarly: () => {}, showTab: () => {}, window: {},
  paintStripTab: () => {}, wallApplyInviteGate: () => {}, paintHereScores: () => {},
  paintHereDesk: () => {}, wireHereFront: () => {}, _hereOwner: '',
  wallDoingView: () => null,  // card 1207: Waiting counts desks with a live tw run in state waiting
};
const names = Object.keys(stubs);
const api = new Function(...names, body + '\nreturn { strip, wallResetStripReady, wallSyncStripTabLoading };')(...names.map((n) => stubs[n]));
function chips() {
  const out = {};
  const re = /id="strip-([a-z]+)"[^>]*data-wall-strip-loading="([01])"[^>]*>[A-Z]+(?:<span class="kpi-load"><\/span>)?<b>([^<]*)<\/b>/g;
  let m;
  while ((m = re.exec(els.strip.innerHTML))) out[m[1]] = (m[2] === '1' ? 'loading:' : '') + m[3];
  return out;
}
const open = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1, status: 'open' }));
const agents = [{ owner: 'd1', alive: true }];
const steps = [];
api.wallResetStripReady();
api.strip({ parts: ['agents'], agents }); steps.push(chips());
api.strip({ parts: ['agents', 'todos'], agents, needs: open(3) }); steps.push(chips());
api.strip({ parts: ['agents'], agents }); steps.push(chips());
api.strip({ parts: ['agents'], agents, between: [{}, {}, {}, {}, {}] }); steps.push(chips());
const floorCls = (m) => ((els.strip.innerHTML.match(/class="([^"]*)" id="strip-floor"/) || [])[1] || '');
const collabLoaded = floorCls();
api.strip({ parts: ['agents'], agents }); steps.push(chips());
api.wallResetStripReady();
api.strip({ parts: ['agents'], agents }); steps.push(chips());
// A chip painted with the last scope's number goes back to unknown on sync.
api.wallResetStripReady();
els['strip-todo'] = chipEl('strip-todo', '22', '22 moving');
api.wallSyncStripTabLoading();
const t = els['strip-todo'];
steps.push({ todo_b: t.kids.b.textContent, cue: !!t.kids.cue, loading: t.attrs['data-wall-strip-loading'] });
api.wallResetStripReady();
api.strip({ parts: ['agents'], agents });
steps.push({ loaded: collabLoaded, loading: floorCls() });
process.stdout.write(JSON.stringify(steps));
"""


def _run() -> list[dict]:
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is not on PATH, so the strip cannot run.")
    src = BOOT.read_text(encoding="utf-8")
    sync = src[src.index("function wallSyncStripTabLoading()"):src.index("function wallParts()")]
    block = src[src.index("const _stripLast"):src.index("function isMillNeedId(")]
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        js, body = tmp / "strip.js", tmp / "body.js"
        js.write_text(HARNESS, encoding="utf-8", newline="\n")
        body.write_text(sync + "\n" + block, encoding="utf-8", newline="\n")
        proc = subprocess.run([node, str(js), str(body)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "node failed")[-2000:])
    return json.loads(proc.stdout)


def test_unread_part_is_loading_not_zero():
    steps = _run()
    first = steps[0]
    # CONNECTED was read; TODO and COLLAB were not, and a stale painted pane is no proof.
    assert first["here"] == "1"
    assert first["todo"] == "loading:..."
    assert first["floor"] == "loading:..."
    assert first["mail"] == "loading:\u2014"


def test_read_part_counts_and_is_kept_for_the_scope():
    steps = _run()
    assert steps[1]["todo"] == "3"
    assert steps[2]["todo"] == "3"  # a later agents-only poll keeps the scope's count
    assert steps[3]["floor"] == "5"  # Between rows give COLLAB its count
    assert steps[4]["floor"] == "5"


def test_scope_switch_forgets_counts():
    steps = _run()
    assert steps[5]["todo"] == "loading:..."
    assert steps[5]["floor"] == "loading:..."


def test_sync_drops_last_scope_number():
    last = _run()[6]
    assert last == {"todo_b": "...", "cue": False, "loading": "1"}


def test_read_collab_count_is_not_drawn_faded():
    """A read COLLAB count is a real number: only the loading chip keeps the faded look."""
    cls = _run()[7]
    assert "kpi-loading" in cls["loading"].split()
    assert "kpi-loading" not in cls["loaded"].split()
    assert "strip-later" in cls["loaded"].split()
    css = (BOOT.parent / "board.css").read_text(encoding="utf-8")
    faded = css.index(".strip .kpi.strip-nav.strip-later {")
    assert "opacity: .4" in css[faded:css.index("}", faded)]
    rule = ".strip .kpi.strip-nav.strip-later:not(.kpi-loading) {"
    assert rule in css and css.index(rule) > faded  # same specificity plus one class, later
    body = css[css.index(rule):css.index("}", css.index(rule))]
    assert "opacity: 1" in body
