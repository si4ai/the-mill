#!/usr/bin/env bash
# Card 925 (wake): verify wake.py / push.py control-flow guards against the
# 0.8.5 code at SYNC. Token-free, on demand, out of CI. Read TLC results with
# the pstack /statechart skill (do not copy its flags here; they change).
#
#   verify/wake-code/run.sh              # anchors + model + mutants + known
#   verify/wake-code/run.sh anchors      # code anchors only
#   verify/wake-code/run.sh model        # TLC on Wake.cfg (via statechart)
#   verify/wake-code/run.sh mutants      # each mutant cfg must violate
#   verify/wake-code/run.sh mutant NAME  # one mutant (e.g. no_stale_token)
#   verify/wake-code/run.sh known        # card 1005 finding still reproduces;
#                                        # proposed fix cfg still passes
#
# Needs: Python 3, java 17+, tla2tools.jar. statechart is resolved from
# the pstack skill cache or STATECHART_CMD.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
OUT=${WAKE_CODE_OUT:-$HERE/out}
SYNC=ce115f8eb70e7e360b80974ec62e177e7771199f
COVERED="agent_coord/server/wake.py agent_coord/server/push.py"

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
      echo "note: covered code changed since $SYNC: $changed- recheck Wake.tla and anchors (SKILL.md)"
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
  echo "model: $sc $HERE/Wake.tla --config Wake.cfg --view view.mjs --out $OUT/model"
  "$sc" "$HERE/Wake.tla" \
    --config "$HERE/Wake.cfg" \
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
  "$sc" "$HERE/Wake.tla" \
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

# Card 1005: current code must still violate UnreadAloneFailedWakeIsRetried;
# the proposed GuardRetryOnUnread=TRUE cfg must pass it.
run_known() {
  local sc mout inv
  sc=$(find_statechart)
  if [ -z "$sc" ]; then
    echo "run.sh: statechart not found; set STATECHART_CMD" >&2
    return 1
  fi
  mout=$OUT/known/card_1005
  rm -rf "$mout"
  mkdir -p "$mout"
  inv=$(cat "$HERE/known/card_1005.expect")
  echo "known card_1005: expect $inv violated (current code)"
  "$sc" "$HERE/Wake.tla" \
    --config "$HERE/known/card_1005.cfg" \
    --view "$HERE/view.mjs" \
    --out "$mout" || true
  if ! grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1 \
     && ! grep -A40 'Rules that break' "$mout/report.md" 2>/dev/null | grep -q "$inv"; then
    echo "known card_1005: FAIL (expected $inv still broken; see $mout)" >&2
    return 1
  fi
  echo "known card_1005: still violated as filed"

  mout=$OUT/known/card_1005_fixed
  rm -rf "$mout"
  mkdir -p "$mout"
  echo "known card_1005_fixed: expect $inv to hold with GuardRetryOnUnread"
  "$sc" "$HERE/Wake.tla" \
    --config "$HERE/known/card_1005_fixed.cfg" \
    --view "$HERE/view.mjs" \
    --out "$mout"
  if grep -E "Invariant $inv is violated|Error: Invariant $inv" "$mout/tlc.out" >/dev/null 2>&1; then
    echo "known card_1005_fixed: FAIL ($inv still broken; see $mout)" >&2
    return 1
  fi
  if ! grep -E 'Model checking completed|No error has been found' "$mout/tlc.out" >/dev/null 2>&1; then
    if ! grep -q 'Rules that hold' "$mout/report.md" 2>/dev/null; then
      echo "known card_1005_fixed: FAIL (no clean TLC completion; see $mout)" >&2
      return 1
    fi
  fi
  echo "known card_1005_fixed: pass (proposed fix)"
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
      echo "verify/wake-code/run.sh: all checks matched"
    else
      echo "verify/wake-code/run.sh: FAIL" >&2
    fi
    exit "$rc"
    ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
esac
