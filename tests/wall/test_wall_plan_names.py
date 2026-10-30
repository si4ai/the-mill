# -*- coding: utf-8 -*-
"""#717: a plan row is named by its plan, or else by its root card, never "unnamed plan".

Runs the real millTreePlanLabel() and millPlanRowFace() from boot.js in Node, so the
test checks behavior, not source text.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from agent_coord.web.wall_logic.packs import wall_ui_root

from ._wall_src import wall_fn

BOOT = wall_ui_root() / "default" / "boot.js"

HARNESS = r"""
const fs = require('fs');
const body = fs.readFileSync(process.argv[2], 'utf8');
const millNameBare = (kind, raw) => String(raw || '').trim();
const api = new Function('millNameBare', body + '\nreturn { millTreePlanLabel, millPlanRowFace };')(millNameBare);
const face = (tree, root) => api.millPlanRowFace(api.millTreePlanLabel(tree), root, root && { id: root.id });
const long = 'card ' + 'detail '.repeat(20);
process.stdout.write(JSON.stringify({
  hidden: face({ name: '006737d3a3', hidden: true }, { id: 135, title: '#716 docs wake guide gaps', status: 'done', who: '' }),
  claimed: face({ name: '1bb6ff441d', hidden: true }, { id: 117, title: '  #698 mail   rooms ', status: 'open', who: 'builder' }),
  named: face({ name: 'engineering' }, { id: 9, title: '#600 score tick gap', status: 'open' }),
  noTitle: face({ name: '0f6c6c5652', hidden: true }, { id: 1, title: '', status: 'done' }),
  long: face({ name: '452a9908c9', hidden: true }, { id: 54, title: long, status: 'parked' }),
  longFull: long.trim(),
}));
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is not on PATH, so the plan rows cannot run.")
    src = BOOT.read_text(encoding="utf-8")
    block = src[src.index("function millTreeHexName("):src.index("/* #33: one nested-set pass")]
    block += "\n" + wall_fn("millPlanRowFace")  # #872: lives in todo/todo-paint.js
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        js, body = tmp / "plan.js", tmp / "body.js"
        js.write_text(HARNESS, encoding="utf-8", newline="\n")
        body.write_text(block, encoding="utf-8", newline="\n")
        proc = subprocess.run([node, str(js), str(body)], capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise AssertionError((proc.stderr or proc.stdout or "node failed")[-2000:])
    return json.loads(proc.stdout)


def test_hex_plan_takes_root_card_title():
    out = _run()
    assert out["hidden"]["head"] == "#716 docs wake guide gaps"
    assert out["hidden"]["line"] == "done"
    assert out["claimed"]["head"] == "#698 mail rooms"
    assert out["claimed"]["line"] == "open | builder"


def test_named_plan_keeps_its_name():
    out = _run()
    assert out["named"]["head"] == "release"
    assert out["named"]["line"] == "#600 score tick gap"


def test_no_row_says_unnamed_plan():
    out = _run()
    assert out["noTitle"]["head"] == "card 1"
    for key in ("hidden", "claimed", "named", "noTitle", "long"):
        assert "unnamed" not in out[key]["head"]


def test_long_root_title_is_cut_on_a_word_and_kept_whole_on_hover():
    out = _run()
    head = out["long"]["head"]
    assert head.endswith("\u2026") and len(head) <= 64
    assert out["longFull"].startswith(head[:-1])
    assert out["long"]["full"] == out["longFull"]
