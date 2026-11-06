# -*- coding: utf-8 -*-
"""wall-scores Phase A: doing.task.* leaf extract + desk/office rollups (omit missing).

Pure helpers live in default/score/score.js. This runs them in Node against a
fixture so CI checks operators without a live Wall.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "agent_coord" / "web" / "wall_ui"
SCORE = ROOT / "default" / "score" / "score.js"
DATA = ROOT / "lib" / "data.js"

HARNESS = r"""
const fs = require('fs');
const scoreSrc = fs.readFileSync(process.argv[2], 'utf8');
const dataSrc = fs.readFileSync(process.argv[3], 'utf8');
global.window = global;
(0, eval)(dataSrc);
(0, eval)(scoreSrc);

const kpis = [
  { kpi: 'doing.task.dwell_idle_ms', owner: 'builder', value: '10' },
  { kpi: 'doing.task.dwell_active_ms', owner: 'builder', value: '20' },
  { kpi: 'doing.task.wait_by_cause', owner: 'builder', value: '{"pattern":1,"quiet":2}' },
  { kpi: 'doing.task.end_reason', owner: 'builder', value: 'tw_finished' },
  { kpi: 'doing.task.dwell_idle_ms', owner: 'wall-ui', value: '5' },
  { kpi: 'doing.task.buffer_overflow_n', owner: 'wall-ui', value: '3' },
  { kpi: 'doing.task.retry_give_up_n', owner: 'wall-ui', value: '1' },
  { kpi: 'doing.task.end_reason', owner: 'wall-ui', value: 'tw_failed' },
  // missing dwell_waiting_ms on both - must not appear as 0
  { kpi: 'doing.task.stale_n', owner: 'builder', value: '9' }, // invent-ban: ignore
  { kpi: 'mill-wall.ticks', owner: 'mill-host', value: '1' },
];

const by = scoreDoingTaskLeavesByDesk(kpis);
const office = scoreDoingTaskOfficeRollup(by);
const builder = scoreDoingTaskDeskRollup(by.builder);
const live = scoreDoingTaskLiveRows([
  { act: 'task', state: 'active', join_key: 'task:builder:w1', card: 'todo-12' },
  { act: 'task', state: 'finished', join_key: 'task:builder:w0' },
  { act: 'task', state: 'waiting', join_key: 'task:builder:w2', cause: 'pattern', title: 'SECRET', argv: ['x'], pattern: '/leak/' },
  { act: 'task', state: 'failed', join_key: 'task:builder:w3' },
]);

const out = {
  tasked: wallActLabel('task'),
  builderKeys: Object.keys(builder).sort(),
  builderWait: scoreDoingTaskFormatLeaf('wait_by_cause', builder.wait_by_cause),
  noWaitingMs: !Object.prototype.hasOwnProperty.call(builder, 'dwell_waiting_ms'),
  noStale: !Object.prototype.hasOwnProperty.call(builder, 'stale_n'),
  officeSumIdle: office.sum.dwell_idle_ms,
  officeSumActive: office.sum.dwell_active_ms,
  officeOverflow: office.sum.buffer_overflow_n,
  officeRetry: office.sum.retry_give_up_n,
  officeCauses: office.wait_by_cause,
  officeEnds: office.end_reason,
  officeDesks: office.desks,
  liveN: live.length,
  liveStates: live.map(r => r.state),
  liveJoin: live.map(r => r.join_key),
  liveHasTitle: live.some(r => r.title),
  liveHasPattern: live.some(r => r.pattern),
  liveWaiting: live.find(r => r.state === 'waiting'),
};
process.stdout.write(JSON.stringify(out));
"""


def _run() -> dict:
    node = shutil.which("node")
    assert node, "node required"
    with tempfile.TemporaryDirectory() as td:
        harness = Path(td) / "h.js"
        harness.write_text(HARNESS, encoding="utf-8")
        proc = subprocess.run(
            [node, str(harness), str(SCORE), str(DATA)],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(proc.stdout)


def test_phase_a_task_label():
    assert _run()["tasked"] == "tasked"


def test_phase_a_omit_missing_and_banned():
    got = _run()
    assert got["noWaitingMs"] is True
    assert got["noStale"] is True
    assert "dwell_idle_ms" in got["builderKeys"]
    assert "wait_by_cause" in got["builderKeys"]
    assert got["builderWait"] == "pattern:1 quiet:2"


def test_phase_a_office_rollup_operators():
    got = _run()
    assert got["officeDesks"] == 2
    assert got["officeSumIdle"] == 15  # 10 + 5
    assert got["officeSumActive"] == 20  # builder only
    assert got["officeOverflow"] == 3
    assert got["officeRetry"] == 1
    assert got["officeCauses"] == {"pattern": 1, "quiet": 2}
    assert got["officeEnds"] == {"tw_finished": 1, "tw_failed": 1}


def test_phase_a_hide_terminal_and_privacy():
    got = _run()
    assert got["liveN"] == 2
    assert got["liveStates"] == ["active", "waiting"]
    assert got["liveJoin"] == ["task:builder:w1", "task:builder:w2"]
    assert got["liveHasTitle"] is False
    assert got["liveHasPattern"] is False
    wait = got["liveWaiting"]
    assert wait["waiting_on"] == "pattern"
    assert "title" not in wait
    assert "argv" not in wait
