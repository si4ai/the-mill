---
name: score-code
description: >
  Code-against-spec check for mill score liveness-truth KPIs (card 925).
  Use when changing score_tick.py, score_series.py, wall_logic/score.py,
  sp_score.sql, or verify/score-code. Token-free; out of CI.
---

# score-code

Run `verify/score-code/run.sh` from the repo root. Needs `statechart` on PATH
or `STATECHART_CMD`, or `verify/score-code/tools/statechart`.

Card 1014: every anchor marker is the guard plus its first effect line; every
anchor self-mutant must go red. Also anchor caller-observed fields (letter 4267).
Nothing counts as proved until its mutant fails.

Orthogonality: do not re-prove SPIN S1-S6 or wall paint unit tests; keep markers
those assume. Known findings: empty-as-zero publish and silent truncation.
