# -*- coding: utf-8 -*-
"""#896 rule-no-activity-weight: the Wall never reads activity.n or activity.weight."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score-paint.js"
IMPACT = ROOT / "default" / "score" / "score-impact.js"
BOOT = ROOT / "default" / "boot.js"
WALL_JS = sorted((ROOT / "default").rglob("*.js")) + sorted((ROOT / "lib").glob("*.js"))


def test_no_presence_spend_fallback_and_unavailable():
    # Score tab redesign: Spend is tw doing time (score-impact.js); token spend is gone.
    score = SCORE.read_text(encoding="utf-8")
    impact = IMPACT.read_text(encoding="utf-8")
    assert "presenceSpendLines" not in score + impact
    assert "Number(e.n || 0) * Number(e.weight" not in score + impact
    assert "function millSpend(" not in score
    assert re.search(r"function scoreSpendHtml\(", impact)
    assert "unavailable" in impact


def test_wall_js_never_reads_event_weight_field():
    for path in WALL_JS:
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for m in re.finditer(r"(?<![a-zA-Z])e\.weight\b|(?<![a-zA-Z])r\.weight\b|event\.weight\b", src):
            full = src[max(0, m.start() - 60) : m.start() + 40]
            raise AssertionError(f"{rel}: activity weight read: {full!r}")


def test_boot_comment_does_not_teach_n_weight_spend():
    boot = BOOT.read_text(encoding="utf-8")
    assert "presence.n*weight" not in boot


_SPEND_HARNESS = r"""
const fs = require('fs');
global.window = global;
(0, eval)(fs.readFileSync(process.argv[1], 'utf8'));
const kpis = JSON.parse(process.argv[2]);
// Activity n and weight sit on the payload; Spend time must not read them.
const ctx = { presence: [{ kind: 'mail', n: 9, weight: 3 }] };
process.stdout.write(scoreSpendHtml(scoreSpendModel(kpis, ctx), 0));
"""


def _spend(kpis):
    import json
    import subprocess

    return subprocess.run(
        ["node", "-e", _SPEND_HARNESS, str(IMPACT), json.dumps(kpis)],
        capture_output=True, text=True, check=True,
    ).stdout


def test_spend_paints_unavailable_without_tw_history():
    empty = _spend([])
    assert "unavailable" in empty
    assert "No doing.task.* scores yet." in empty
    out = _spend([{"kpi": "doing.task.dwell_active_ms", "owner": "builder", "value": "1086"}])
    assert "1.1s" in out and "1086 ms" in out
    assert "unavailable" in out  # one last run is not a total
    assert ">27" not in out  # 9 * 3 from activity never shows as time
