#!/usr/bin/env bash
# Card 925 (doing slice): verify score liveness-truth KPIs guards against
# the 0.8.5 code at SYNC. Token-free, on demand, out of CI. Read TLC results with
# the pstack /statechart skill (do not copy its flags here; they change).
#
#   verify/score-code/run.sh              # anchors + model + mutants + known
#   verify/score-code/run.sh anchors      # code anchors only
#   verify/score-code/run.sh model        # TLC on Score.cfg (via statechart)
#   verify/score-code/run.sh mutants      # each mutant cfg must violate
#   verify/score-code/run.sh mutant NAME  # one mutant (e.g. no_take_free)
#   verify/score-code/run.sh known        # empty-as-zero and silent-truncation findings still reproduce;
#                                        # proposed fix cfgs still pass
#
# Needs: Python 3, java 17+, tla2tools.jar. statechart is resolved from
# the pstack skill cache or STATECHART_CMD.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
OUT=${SCORE_CODE_OUT:-$HERE/out}
SYNC=ce115f8
COVERED="agent_coord/server/score_tick.py agent_coord/server/score_series.py agent_coord/web/wall_logic/score.py agent_coord/server/sql/sp_score.sql"

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
      echo "note: covered code changed since $SYNC: $changed- recheck Score.tla and anchors (SKILL.md)"
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
  rm -rf "$OUT/model"
  mkdir -p "$OUT/model"
  if [ -z "$sc" ]; then
    echo "run.sh: statechart not found; set STATECHART_CMD" >&2
    return 1
  fi
  echo "model: $sc $HERE/Score.tla --config Score.cfg --view view.mjs --out $OUT/model"
  "$sc" "$HERE/Score.tla" \
    --config "$HERE/Score.cfg" \
    --view "$HERE/view.mjs" \
    --out "$OUT/model"
  if grep -E 'Invariant .* is violated|Error: Invariant' "$OUT/model/tlc.out" >/dev/null 2>&1; then
    echo "model: FAIL (invariant violated; see $OUT/model/tlc.out)" >&2
    return 1
  fi
  if ! grep -E 'Model checking completed|No error has been found' "$OUT/model/tlc.out" >/dev/null 2>&1; then
    if grep -q 'Rules that hold' "$OUT/model/report.md" 2>/dev/null; then
      echo "model: pass (report lists rules that hold)"
      return 0
    fi
    echo "model: FAIL (no clean TLC completion; see $OUT/model)" >&2
    return 1
  fi
  echo "model: pass"
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
  "$sc" "$HERE/Score.tla" \
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

# Known findings: empty publish as zero; silent point truncation.
run_known() {
  local sc mout inv
  sc=$(find_statechart)
  if [ -z "$sc" ]; then
    echo "run.sh: statechart not found; set STATECHART_CMD" >&2
    return 1
  fi
  for pair in empty_as_zero:GuardEmptyAsMissing truncation_silent:GuardTruncationLabelled; do
    name=${pair%%:*}; guard=${pair#*:}
    mout=$OUT/known/$name
    rm -rf "$mout"; mkdir -p "$mout"
    inv=$(cat "$HERE/known/${name}.expect")
    echo "known $name: expect $inv violated (current code)"
    "$sc" "$HERE/Score.tla" --config "$HERE/known/${name}.cfg" --view "$HERE/view.mjs" --out "$mout" || true
    if ! grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1 \
       && ! grep -A40 'Rules that break' "$mout/report.md" 2>/dev/null | grep -q "$inv"; then
      echo "known $name: FAIL (expected $inv still broken; see $mout)" >&2
      return 1
    fi
    echo "known $name: still violated as filed"
    mout=$OUT/known/${name}_fixed
    rm -rf "$mout"; mkdir -p "$mout"
    echo "known ${name}_fixed: expect $inv to hold with $guard"
    "$sc" "$HERE/Score.tla" --config "$HERE/known/${name}_fixed.cfg" --view "$HERE/view.mjs" --out "$mout"
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
      echo "verify/score-code/run.sh: all checks matched"
    else
      echo "verify/score-code/run.sh: FAIL" >&2
    fi
    exit "$rc"
    ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
esac
