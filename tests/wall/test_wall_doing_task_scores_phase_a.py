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
  // card 1207 doings[] shape: id, created, text, state, state_at, card (a feed may still leak old keys)
  { id: 1, created: '2026-11-13T01:00:00Z', text: '', state: 'active', state_at: '2026-11-13T01:00:00Z', card: 12 },
  { id: 0, created: '2026-11-13T00:00:00Z', text: '', state: 'finished', state_at: '2026-11-13T00:30:00Z', card: null },
  { id: 2, created: '2026-11-13T02:00:00Z', text: '', state: 'waiting', state_at: '2026-11-13T02:10:00Z', card: null,
    join_key: 'task:builder:w2', cause: 'pattern', waiting_on: 'x', title: 'SECRET', argv: ['x'], pattern: '/leak/' },
  { id: 3, created: '2026-11-13T03:00:00Z', text: '', state: 'failed', state_at: '2026-11-13T03:05:00Z', card: null },
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
  liveIds: live.map(r => r.id),
  liveCards: live.map(r => r.card),
  liveHasTitle: live.some(r => r.title),
  liveHasPattern: live.some(r => r.pattern),
  liveWaiting: live.find(r => r.state === 'waiting'),
  lastNone: scoreDoingTaskLastDoneFromScores([], 'builder'),
  lastMissing: scoreDoingTaskLastDoneFromScores(kpis, 'missing-desk'),
  lastEmptyDesk: scoreDoingTaskLastDoneFromScores(kpis, ''),
  lastBuilder: scoreDoingTaskLastDoneFromScores(kpis, 'builder'),
  lastWall: scoreDoingTaskLastDoneFromScores(kpis, 'wall-ui'),
  lastIdleOnly: scoreDoingTaskLastDoneFromScores([
    { kpi: 'doing.task.dwell_idle_ms', owner: 'auditor', value: '28800003.795' }
  ], 'auditor', Date.parse('2026-11-06T21:00:00Z')),
  lastWithFinishedAt: scoreDoingTaskLastDoneFromScores([
    { kpi: 'doing.task.end_reason', owner: 'auditor', value: 'tw_finished', finished_at: '2026-11-06T10:00:00Z' }
  ], 'auditor', Date.parse('2026-11-06T12:00:00Z')),
  lastWithUpdatedAt: scoreDoingTaskLastDoneFromScores([
    { kpi: 'doing.task.end_reason', owner: 'auditor', value: 'tw_finished', updated_at: '2026-11-06T11:00:00Z' }
  ], 'auditor', Date.parse('2026-11-06T12:00:00Z')),
  lastWithLeafTs: scoreDoingTaskLastDoneFromScores([
    { kpi: 'doing.task.end_reason', owner: 'auditor', value: 'tw_finished' },
    { kpi: 'doing.task.finished_at', owner: 'auditor', value: '2026-11-06T10:00:00Z' }
  ], 'auditor', Date.parse('2026-11-06T12:00:00Z')),
  lastWithDocAt: scoreDoingTaskLastDoneFromScores([
    { kpi: 'doing.task.end_reason', owner: 'auditor', value: 'tw_finished', at: '2026-11-06T10:00:00Z' }
  ], 'auditor', Date.parse('2026-11-06T12:00:00Z')),
  agoTwoHours: scoreDoingTaskFormatAgo(Date.parse('2026-11-06T10:00:00Z'), Date.parse('2026-11-06T12:00:00Z')),
  agoEmpty: scoreDoingTaskFormatAgo(null, Date.now()),
  parseIdleMs: scoreDoingTaskParseTimestamp(28800003.795),
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
    assert got["liveIds"] == [1, 2]
    assert got["liveCards"] == [12, None]
    assert got["liveHasTitle"] is False
    assert got["liveHasPattern"] is False
    wait = got["liveWaiting"]
    assert sorted(wait) == ["card", "created", "id", "state", "state_at", "text"]
    assert wait["state_at"] == "2026-11-13T02:10:00Z"


def test_phase_a_last_done_from_scores():
    got = _run()
    assert got["lastNone"] is None
    assert got["lastMissing"] is None
    assert got["lastEmptyDesk"] is None
    last = got["lastBuilder"]
    assert last["kind"] == "last_done"
    assert last["live"] is False
    assert last["end_reason"] == "tw_finished"
    assert last["dwell_active_ms"] == "20"
    assert last["dwell_idle_ms"] == "10"
    assert "ago" not in last
    assert "title" not in last
    assert "wait_by_cause" not in last
    wall = got["lastWall"]
    assert wall["end_reason"] == "tw_failed"
    assert wall["dwell_idle_ms"] == "5"
    assert "dwell_active_ms" not in wall
    idle = got["lastIdleOnly"]
    assert idle["dwell_idle_ms"] == "28800003.795"
    assert "ago" not in idle
    assert "end_reason" not in idle
    assert got["parseIdleMs"] is None


def test_phase_a_last_done_ago_only_from_real_timestamp():
    got = _run()
    assert got["agoTwoHours"] == "2 hours ago"
    assert got["agoEmpty"] == ""
    assert got["lastWithFinishedAt"]["ago"] == "2 hours ago"
    assert got["lastWithUpdatedAt"]["ago"] == "1 hour ago"
    assert got["lastWithLeafTs"]["ago"] == "2 hours ago"
    assert got["lastWithFinishedAt"]["end_reason"] == "tw_finished"
    assert "ago" not in got["lastWithDocAt"]
    assert got["lastWithDocAt"]["end_reason"] == "tw_finished"
