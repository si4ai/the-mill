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
#   verify/doing-code/run.sh known        # wait-cycle and stale-doing findings still reproduce,
#                                        # at MaxTasks=1 and 2; proposed fix cfgs still pass
#   verify/doing-code/run.sh witness      # 0.8.6 target: two active tasks on one desk reachable,
#                                        # plus target mutants (supersede on, MaxTasks=1, no slot 2)
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


# broke FILE_DIR NAME: TLC (or statechart's report) shows NAME violated,
# as an invariant or as an action property.
broke() {
  local mout=$1 inv=$2
  grep -E "Invariant $inv is violated|Error: Invariant $inv|Action property $inv is violated|property $inv is violated" \
    "$mout/tlc.out" >/dev/null 2>&1 && return 0
  grep -A40 'Rules that break' "$mout/report.md" 2>/dev/null | grep -q "$inv"
}

clean() {
  local mout=$1
  grep -E 'Model checking completed|No error has been found' "$mout/tlc.out" >/dev/null 2>&1 \
    || grep -q 'Rules that hold' "$mout/report.md" 2>/dev/null
}

# Constants of Doing-target.cfg (through SPECIFICATION), optionally sed-mutated,
# followed by the given check lines. Mutants derive from the shipped target cfg,
# so editing the target cfg moves them too.
target_cfg() {
  local sedx=$1; shift
  sed -n '1,/^SPECIFICATION/p' "$HERE/Doing-target.cfg" | sed -E "${sedx:-s/^//}"
  printf '%s\n' "$@" "CHECK_DEADLOCK FALSE"
}

# run_tlc NAME CFG [TLA]: one statechart run under $OUT/NAME.
run_tlc() {
  local name=$1 cfg=$2 tla=${3:-$HERE/Doing.tla} sc
  sc=$(find_statechart)
  local mout=$OUT/$name
  rm -rf "$mout" "$mout.log"; mkdir -p "$(dirname "$mout")"
  "$sc" "$tla" --config "$cfg" --view "$HERE/view.mjs" --out "$mout" >"$mout.log" 2>&1 || true
  echo "$mout"
}

# 0.8.6 target: concurrency must be reachable, supersede must be gone.
# Each target mutant must turn this red.
run_witness() {
  local sc mout rc=0 cfgd=$OUT/witness-cfg
  sc=$(find_statechart)
  if [ -z "$sc" ]; then echo "witness: statechart not found (set STATECHART_CMD)" >&2; return 1; fi
  rm -rf "$cfgd"; mkdir -p "$cfgd"

  target_cfg "" "INVARIANT TypeOK" "INVARIANT NoTwoActive" >"$cfgd/two_active.cfg"
  mout=$(run_tlc witness/two_active "$cfgd/two_active.cfg")
  if broke "$mout" NoTwoActive; then echo "witness two_active: second concurrent task reachable on target"
  else echo "witness two_active: FAIL (target never reaches two active tasks; see $mout)" >&2; rc=1; fi

  # mutant: supersede back on -> NoSupersede must break
  target_cfg 's/^(  GuardSupersede = )FALSE/\1TRUE/' "INVARIANT TypeOK" "PROPERTY NoSupersede" >"$cfgd/target_supersede.cfg"
  grep -q 'GuardSupersede = TRUE' "$cfgd/target_supersede.cfg" || { echo "witness target_supersede: sed no-op" >&2; rc=1; }
  mout=$(run_tlc witness/target_supersede "$cfgd/target_supersede.cfg")
  if broke "$mout" NoSupersede; then echo "witness target_supersede: NoSupersede broke as expected"
  else echo "witness target_supersede: FAIL (supersede on target not caught; see $mout)" >&2; rc=1; fi

  # mutant: MaxTasks=1 on target -> the two_active witness must vanish
  target_cfg 's/^(  MaxTasks = )2/\11/' "INVARIANT TypeOK" "INVARIANT NoTwoActive" >"$cfgd/target_max1.cfg"
  grep -q 'MaxTasks = 1' "$cfgd/target_max1.cfg" || { echo "witness target_max1: sed no-op" >&2; rc=1; }
  mout=$(run_tlc witness/target_max1 "$cfgd/target_max1.cfg")
  if clean "$mout" && ! broke "$mout" NoTwoActive; then echo "witness target_max1: witness lost as expected (check catches MaxTasks=1)"
  else echo "witness target_max1: FAIL (two active still reachable at MaxTasks=1; see $mout)" >&2; rc=1; fi

  # mutant: Doing.tla never hands out slot 2 -> the two_active witness must vanish
  sed -E 's/ELSE IF MaxTasks = 2 \/\\ st(1|2)2 = 0 THEN 2/ELSE IF FALSE THEN 2/' "$HERE/Doing.tla" >"$cfgd/Doing.tla"
  if cmp -s "$HERE/Doing.tla" "$cfgd/Doing.tla"; then echo "witness target_no_slot2: sed no-op" >&2; rc=1; fi
  mout=$(run_tlc witness/target_no_slot2 "$cfgd/two_active.cfg" "$cfgd/Doing.tla")
  if clean "$mout" && ! broke "$mout" NoTwoActive; then echo "witness target_no_slot2: witness lost as expected"
  else echo "witness target_no_slot2: FAIL (see $mout)" >&2; rc=1; fi
  return $rc
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
  for pair in wait_cycle:GuardDetectWaitCycle stale_doing:GuardAutoClearStale \
              wait_cycle_target:GuardDetectWaitCycle stale_doing_target:GuardAutoClearStale; do
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
  sed -n '2,18p' "$0"
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
  witness) run_witness ;;
  all)
    rc=0
    run_anchors || rc=1
    run_model || rc=1
    run_mutants || rc=1
    run_known || rc=1
    run_witness || rc=1
    if [ "$rc" -eq 0 ]; then
      echo "verify/doing-code/run.sh: all checks matched"
    else
      echo "verify/doing-code/run.sh: FAIL" >&2
    fi
    exit "$rc"
    ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
esac
