# -*- coding: utf-8 -*-
"""Plan nest index (#33): depth, parent, kids, roots, and spine match the old scans; depth is linear-ish."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent_coord.web.wall_logic.packs import wall_ui_root

BOOT = wall_ui_root() / "default" / "boot.js"
TODO_PAINT = wall_ui_root() / "default" / "todo" / "todo-paint.js"

SCRIPT = r"""
const fs = require('fs');
const body = fs.readFileSync(process.argv[2], 'utf8');
const stubs = "const esc = s => String(s == null ? '' : s);" +
  "const millNameBare = (k, s) => String(s || ''); const millName = millNameBare;" +
  "const millTodoCards = d => (d && d.needs) || [];";
const api = new Function(stubs + body + "\nreturn { millTreeDepth, millOutlineKidsOf, millTodoParentOf, millTodoKidsOf, millTodoRootsOf, todoTreeOnSpine };")();
const num = v => Number(v);
function refDepth(nodes, node) {
  if (node && node.depth != null && node.depth !== '') { const d = Number(node.depth); if (Number.isFinite(d) && d >= 0) return d; }
  const l = num(node && node.lft), r = num(node && node.rgt);
  if (!Number.isFinite(l) || !Number.isFinite(r)) return 0;
  let n = 0;
  nodes.forEach(o => { if (!o || o === node) return; const a = num(o.lft), b = num(o.rgt); if (Number.isFinite(a) && Number.isFinite(b) && a < l && b > r) n += 1; });
  return n;
}
function refParent(todos, n) {
  const l = num(n && n.lft), r = num(n && n.rgt);
  if (!Number.isFinite(l) || !Number.isFinite(r)) return null;
  let best = null;
  todos.forEach(o => { if (!o || o === n) return; const a = num(o.lft), b = num(o.rgt);
    if (!Number.isFinite(a) || !Number.isFinite(b) || !(a < l && b > r)) return; if (!best || a > num(best.lft)) best = o; });
  return best;
}
const byLft = (a, b) => (num(a.lft) || 0) - (num(b.lft) || 0);
function refKids(todos, n) {
  const l = num(n && n.lft), r = num(n && n.rgt);
  if (!Number.isFinite(l) || !Number.isFinite(r)) return [];
  return todos.filter(o => o && o !== n && num(o.lft) > l && num(o.rgt) < r && refParent(todos, o) === n).sort(byLft);
}
function refOutlineKids(nodes, n) {
  const l = num(n && n.lft), r = num(n && n.rgt), d = refDepth(nodes, n);
  return nodes.filter(o => o && o !== n && refDepth(nodes, o) === d + 1 && num(o.lft) > l && num(o.rgt) < r);
}
function rng(seed) { return () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648; }
function tree(n, maxKids, seed, base) {
  const r = rng(seed); const kids = [[]];
  for (let i = 1; i < n; i++) { let p; do { p = Math.floor(r() * i); } while (kids[p].length >= maxKids); kids.push([]); kids[p].push(i); }
  const nodes = new Array(n); let c = 1;
  (function walk(i) { const o = { type: 'todo', id: base + i, lft: c++ }; for (const k of kids[i]) walk(k); o.rgt = c++; nodes[i] = o; })(0);
  return nodes;
}
function chain(n, base) { const out = []; for (let i = 0; i < n; i++) out.push({ type: 'todo', id: base + i, lft: i + 1, rgt: 2 * n - i }); return out; }
const ids = a => a.map(x => x && x.id);
const cases = {};
cases.chain = chain(300, 1);
cases.branches = tree(600, 5, 7, 1000);
cases.wide = tree(400, 400, 3, 3000);
cases.forest = tree(50, 3, 1, 5000).concat(tree(40, 2, 2, 6000).map(o => ({ type: 'todo', id: o.id, lft: o.lft + 1000, rgt: o.rgt + 1000 })));
cases.shuffled = tree(200, 3, 11, 7000).reverse();
cases.overlap = tree(60, 3, 5, 8000).concat([{ type: 'todo', id: 8999, lft: 2, rgt: 500 }]);
cases.tie = tree(60, 3, 6, 9000).concat([{ type: 'todo', id: 9999, lft: 1, rgt: 3 }]);
cases.inverted = tree(40, 3, 8, 10000).concat([{ type: 'todo', id: 10999, lft: 9, rgt: 4 }]);
cases.nonfinite = tree(40, 3, 9, 11000).concat([{ type: 'todo', id: 11999 }, { type: 'todo', id: 11998, lft: 'x', rgt: 3 }, null]);
const twice = tree(30, 3, 4, 12000); cases.repeated = twice.concat([twice[3]]);
cases.explicit = tree(40, 3, 12, 13000).map((o, i) => (i % 7 ? o : Object.assign({}, o, { depth: 9 })));
const bad = [];
Object.keys(cases).forEach(name => {
  const nodes = cases[name];
  const d = { needs: nodes.filter(Boolean).map((n, i) => ({ id: n.id, need_id: 'need-' + n.id, status: 'open', detail: (i % 9 ? 'card ' : 'hit ') + n.id })) };
  nodes.forEach((n, i) => {
    if (api.millTreeDepth(nodes, n) !== refDepth(nodes, n)) bad.push([name, 'depth', i]);
    if (n && JSON.stringify(ids(api.millOutlineKidsOf(nodes, n))) !== JSON.stringify(ids(refOutlineKids(nodes, n)))) bad.push([name, 'outline-kids', i]);
    if (!n) return;
    if (api.millTodoParentOf(nodes, n) !== refParent(nodes, n)) bad.push([name, 'parent', i]);
    if (JSON.stringify(ids(api.millTodoKidsOf(nodes, n))) !== JSON.stringify(ids(refKids(nodes, n)))) bad.push([name, 'kids', i]);
    const refSpine = n.id && (d.needs.find(r => r.id === n.id) || {}).detail.indexOf('hit') === 0 ||
      nodes.some(o => o && o !== n && num(o.lft) > num(n.lft) && num(o.rgt) < num(n.rgt) && (d.needs.find(r => r.id === o.id) || { detail: '' }).detail.indexOf('hit') === 0);
    if (api.todoTreeOnSpine(nodes, n, d, 'hit') !== !!refSpine) bad.push([name, 'spine', i]);
  });
  const todos = nodes.filter(Boolean);
  const roots = todos.filter(n => !refParent(todos, n)).sort(byLft);
  if (JSON.stringify(ids(api.millTodoRootsOf(todos))) !== JSON.stringify(ids(roots))) bad.push([name, 'roots']);
});
// rows edited in place by a later refresh (next task) are read fresh
const live = chain(20, 20000);
live.forEach(n => api.millTreeDepth(live, n));
Promise.resolve().then(() => {
live[5].lft = 100; live[5].rgt = 101; live[19].lft = 0; live[19].rgt = 1000;
live.forEach((n, i) => { if (api.millTreeDepth(live, n) !== refDepth(live, n)) bad.push(['edited', 'depth', i]); });
// linear-ish: every depth on a 30000 chain (the old scan is 9e8 steps)
const big = chain(30000, 100000);
const t0 = Date.now();
let sum = 0;
big.forEach(n => { sum += api.millTreeDepth(big, n); });
const ms = Date.now() - t0;
process.stdout.write(JSON.stringify({ bad: bad.slice(0, 20), nbad: bad.length, ms: ms, sum: sum }));
});
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is not on PATH, so the plan nest index cannot run.")
    src = BOOT.read_text(encoding="utf-8")
    start = src.index("function millTreeHexName(")
    end = src.index("    function hereKpiName(")
    # #710: the plan tree helpers boot.js keeps, then the split TODO paint file
    src = src[:end] + "\n" + TODO_PAINT.read_text(encoding="utf-8")
    end = len(src)
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        js = tmp / "nest.js"
        body = tmp / "body.js"
        js.write_text(SCRIPT, encoding="utf-8", newline="\n")
        body.write_text(src[start:end], encoding="utf-8", newline="\n")
        proc = subprocess.run([node, str(js), str(body)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "node failed")[-2000:])
    return json.loads(proc.stdout)


def test_nest_index_matches_old_scans_and_is_linear():
    got = _run()
    assert got["nbad"] == 0, got["bad"]
    assert got["sum"] == 30000 * 29999 // 2
    assert got["ms"] < 2000, got["ms"]


def test_plan_chart_reuses_rows():
    src = BOOT.read_text(encoding="utf-8") + TODO_PAINT.read_text(encoding="utf-8")
    assert "function millNestBuild(" in src
    assert "function todoPertSync(" in src
    assert "wallKeyedSync(forestBox, forestRows);" in src
    assert "_millPaintScope = { d: d, cards: null };" in src
