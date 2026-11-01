#!/usr/bin/env bash
# Card 925 (doing slice): verify doing focus/waiting/end guards against
# the 0.8.5 code at SYNC. Token-free, on demand, out of CI. Read TLC results with
# the pstack /statechart skill (do not copy its flags here; they change).
#
#   verify/doing-code/run.sh              # anchors + model + mutants + known
#   verify/doing-code/run.sh anchors      # code anchors only
#   verify/doing-code/run.sh model        # TLC on Doing.cfg (via statechart)
#   verify/doing-code/run.sh mutants      # each mutant cfg must violate
#   verify/doing-code/run.sh mutant NAME  # one mutant (e.g. no_take_free)
#   verify/doing-code/run.sh known        # wait-cycle and stale-doing findings still reproduces;
#                                        # proposed fix cfgs still pass
#
# Needs: Python 3, java 17+, tla2tools.jar. statechart is resolved from
# the pstack skill cache or STATECHART_CMD.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
OUT=${DOING_CODE_OUT:-$HERE/out}
SYNC=ce115f8
COVERED="agent_coord/server/sql/sp_doing.sql agent_coord/server/sql/sp_join.sql"

JAVA=${JAVA:-}
TLA2TOOLS=${TLA2TOOLS:-}
for cand in \
  /workspace/statechart-pilot/tools/jdk-17.0.21+9-jre/bin/java \
  "$HERE/tools/jdk/bin/java"
do
  if [ -z "$JAVA" ] && [ -x "$cand" ]; then JAVA=$cand; fi
done
JAVA=${JAVA:-java}
for cand in \
  /workspace/statechart-pilot/tools/tla2tools.jar \
  "$HERE/tools/tla2tools.jar"
do
  if [ -z "$TLA2TOOLS" ] && [ -f "$cand" ]; then TLA2TOOLS=$cand; fi
done
export JAVA TLA2TOOLS

find_statechart() {
  if [ -n "${STATECHART_CMD:-}" ]; then
    echo "$STATECHART_CMD"
    return
  fi
  if [ -x "$HERE/tools/statechart" ]; then
    echo "$HERE/tools/statechart"
    return
  fi
  local d s
  for d in \
    /home/user/sand-data/plugins/cache/cursor-public/pstack/*/skills/statechart/scripts \
    /home/user/agent-data/plugins/cache/cursor-public/pstack/*/skills/statechart/scripts \
    "$HOME/sand-data/plugins/cache/cursor-public/pstack/*/skills/statechart/scripts" \
    "$HOME/agent-data/plugins/cache/cursor-public/pstack/*/skills/statechart/scripts" \
    /home/user/agent-data/plugins/pstack/pstack/skills/statechart/scripts
  do
    for s in $d/statechart; do
      if [ -x "$s" ]; then echo "$s"; return; fi
    done
  done
  echo ""
}

note_sync() {
  if git -C "$ROOT" cat-file -e "$SYNC^{commit}" 2>/dev/null; then
    local changed
    changed=$(cd "$ROOT" && git diff --name-only "$SYNC" -- $COVERED | tr '\n' ' ')
    if [ -n "$changed" ]; then
      echo "note: covered code changed since $SYNC: $changed- recheck Doing.tla and anchors (SKILL.md)"
    fi
  fi
}

run_anchors() {
  python3 "$HERE/check_anchors.py" --selftest || return 1
  python3 "$HERE/check_anchors.py" --root "$ROOT" || return 1
  local id rc=0
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if ! python3 "$HERE/check_anchors.py" --root "$ROOT" --mutant "$id"; then
      echo "run_anchors: mutant $id did not fail as expected" >&2
      rc=1
    fi
  done < <(python3 "$HERE/check_anchors.py" --list)
  return $rc
}

run_model() {
  local sc
  sc=$(find_statechart)
  if [ -z "$sc" ]; then
    echo "model: statechart not found (set STATECHART_CMD)" >&2
    return 1
  fi
  rm -rf "$OUT/model" "$OUT/model-target"
  mkdir -p "$OUT/model" "$OUT/model-target"
  echo "model (current MaxTasks=1): Doing.cfg"
  "$sc" "$HERE/Doing.tla" --config "$HERE/Doing.cfg" --view "$HERE/view.mjs" --out "$OUT/model" || return 1
  echo "model (0.8.6 target MaxTasks=2): Doing-target.cfg"
  "$sc" "$HERE/Doing.tla" --config "$HERE/Doing-target.cfg" --view "$HERE/view.mjs" --out "$OUT/model-target"
}


run_one_mutant() {
  local name=$1
  local cfg=$HERE/mutants/${name}.cfg
  local expect=$HERE/mutants/${name}.expect
  local mout=$OUT/mutants/$name
  local sc
  sc=$(find_statechart)
  if [ ! -f "$cfg" ]; then
    echo "mutant: unknown $name" >&2
    return 1
  fi
  rm -rf "$mout"
  mkdir -p "$mout"
  echo "mutant $name: expect $(cat "$expect") violated"
  "$sc" "$HERE/Doing.tla" \
    --config "$cfg" \
    --view "$HERE/view.mjs" \
    --out "$mout" || true
  local inv
  inv=$(cat "$expect")
  if grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1; then
    echo "mutant $name: violated as expected ($inv)"
    return 0
  fi
  if grep -A40 'Rules that break' "$mout/report.md" 2>/dev/null | grep -q "$inv"; then
    echo "mutant $name: violated as expected ($inv)"
    return 0
  fi
  echo "mutant $name: FAIL (expected $inv to break; see $mout)" >&2
  return 1
}

run_mutants() {
  local f name rc=0
  for f in "$HERE"/mutants/*.cfg; do
    name=$(basename "$f" .cfg)
    if ! run_one_mutant "$name"; then rc=1; fi
  done
  return $rc
}

# Known findings: wait cycle (no GuardDetectWaitCycle) and stale doing (no auto-clear).
run_known() {
  local sc mout inv
  sc=$(find_statechart)
  if [ -z "$sc" ]; then
    echo "run.sh: statechart not found; set STATECHART_CMD" >&2
    return 1
  fi
  for pair in wait_cycle:GuardDetectWaitCycle stale_doing:GuardAutoClearStale; do
    name=${pair%%:*}; guard=${pair#*:}
    mout=$OUT/known/$name
    rm -rf "$mout"; mkdir -p "$mout"
    inv=$(cat "$HERE/known/${name}.expect")
    echo "known $name: expect $inv violated (current code)"
    "$sc" "$HERE/Doing.tla" --config "$HERE/known/${name}.cfg" --view "$HERE/view.mjs" --out "$mout" || true
    if ! grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1 \
       && ! grep -A40 'Rules that break' "$mout/report.md" 2>/dev/null | grep -q "$inv"; then
      echo "known $name: FAIL (expected $inv still broken; see $mout)" >&2
      return 1
    fi
    echo "known $name: still violated as filed"
    mout=$OUT/known/${name}_fixed
    rm -rf "$mout"; mkdir -p "$mout"
    echo "known ${name}_fixed: expect $inv to hold with $guard"
    "$sc" "$HERE/Doing.tla" --config "$HERE/known/${name}_fixed.cfg" --view "$HERE/view.mjs" --out "$mout"
    if grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1; then
      echo "known ${name}_fixed: FAIL ($inv still broken; see $mout)" >&2
      return 1
    fi
    if ! grep -E 'Model checking completed|No error has been found' "$mout/tlc.out" >/dev/null 2>&1; then
      if ! grep -q 'Rules that hold' "$mout/report.md" 2>/dev/null; then
        echo "known ${name}_fixed: FAIL (no clean TLC completion; see $mout)" >&2
        return 1
      fi
    fi
    echo "known ${name}_fixed: pass (proposed fix)"
  done
}

usage() {
  sed -n '2,16p' "$0"
}

note_sync
cmd=${1:-all}
case "$cmd" in
  -h|--help) usage; exit 0 ;;
  anchors) run_anchors ;;
  model) run_model ;;
  mutants) run_mutants ;;
  mutant) run_one_mutant "${2:?mutant name}" ;;
  known) run_known ;;
  all)
    rc=0
    run_anchors || rc=1
    run_model || rc=1
    run_mutants || rc=1
    run_known || rc=1
    if [ "$rc" -eq 0 ]; then
      echo "verify/doing-code/run.sh: all checks matched"
    else
      echo "verify/doing-code/run.sh: FAIL" >&2
    fi
    exit "$rc"
    ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
esac
