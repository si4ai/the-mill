---
name: doing-code
description: >
  Code-against-spec check for mill doing focus/waiting/end (card 925).
  Use when changing sp_doing.sql, mill_doing_put/finish/insert, or
  verify/doing-code. Token-free; out of CI.
---

# doing-code

Run `verify/doing-code/run.sh` from the repo root. Needs `statechart` on PATH
or `STATECHART_CMD`, or `verify/doing-code/tools/statechart`.

Card 1014: every anchor marker is the guard plus its first effect line; every
anchor self-mutant must go red. Nothing counts as proved until its mutant fails.

Orthogonality: do not re-prove SPIN D01-D08 or waiting_818; keep SQL markers
those assume. Known findings: wait-cycle and stale-doing (see README).
