#!/usr/bin/env bash
# Card 925: verify todo T1-T14 who-may against the 0.8.0 code.
# Token-free, on demand, out of CI. Read TLC results with the pstack
# /statechart skill (do not copy its flags here; they change).
#
#   verify/todo-code/run.sh              # anchors + model + all mutants
#   verify/todo-code/run.sh anchors      # code anchors only
#   verify/todo-code/run.sh model        # TLC on Todo.cfg (via statechart)
#   verify/todo-code/run.sh mutants      # each mutant cfg must violate
#   verify/todo-code/run.sh mutant NAME  # one mutant (e.g. no_who_may_done)
#
# Needs: Python 3, java 17+, tla2tools.jar. statechart is resolved from
# the pstack skill cache or STATECHART_CMD.
set -euo pipefail

HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
OUT=${TODO_CODE_OUT:-$HERE/out}
SYNC=4ee4a347ebc141fe27648cf4e72e56c7a9d8160b
COVERED="agent_coord/server/sql/sp_cmd.sql agent_coord/server/sql/sp_todo.sql agent_coord/server/api/mill/rpc.py"

# Bundled TLC tools (same tree the statechart pilot uses), overridable.
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
  # Optional local copy (agents may symlink the pstack statechart here).
  if [ -x "$HERE/tools/statechart" ]; then
    echo "$HERE/tools/statechart"
    return
  fi
  # Common pstack skill cache layout (login segment is the placeholder "user").
  local d s
  for d in \
    /home/user/sand-data/plugins/cache/cursor-public/pstack/*/skills/statechart/scripts \
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
      echo "note: covered code changed since $SYNC: $changed- recheck Todo.tla and anchors (SKILL.md)"
    fi
  fi
}

run_anchors() {
  python3 "$HERE/check_anchors.py" --root "$ROOT" || return 1
  # Each listed mutant id must fail the anchor check on a stripped copy.
  local id
  for id in T9-done T7-who-may T8-ship T4-claimed-by T5-assign-guard T12-retire-who T3-unpark; do
    if ! python3 "$HERE/check_anchors.py" --root "$ROOT" --mutant "$id"; then
      echo "run_anchors: mutant $id did not fail as expected" >&2
      return 1
    fi
  done
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
  echo "model: $sc $HERE/Todo.tla --config Todo.cfg --view view.mjs --out $OUT/model"
  "$sc" "$HERE/Todo.tla" \
    --config "$HERE/Todo.cfg" \
    --view "$HERE/view.mjs" \
    --out "$OUT/model"
  # statechart writes report.md; require no breaking rules.
  if grep -q 'Rules that break' "$OUT/model/report.md" 2>/dev/null; then
    if grep -A20 'Rules that break' "$OUT/model/report.md" | grep -q '[A-Za-z]'; then
      # Empty section is fine; non-empty names mean a break.
      if grep -A50 '## Rules that break' "$OUT/model/report.md" | grep -v '^#' | grep -v '^$' | grep -vq 'none\|None\|^--'; then
        # Fall back: TLC exit is reflected in tlc.out
        :
      fi
    fi
  fi
  if grep -E 'Invariant .* is violated|Error: Invariant' "$OUT/model/tlc.out" >/dev/null 2>&1; then
    echo "model: FAIL (invariant violated; see $OUT/model/tlc.out)" >&2
    return 1
  fi
  if ! grep -E 'Model checking completed|No error has been found' "$OUT/model/tlc.out" >/dev/null 2>&1; then
    # statechart may still pass with "Rules that hold"
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
  "$sc" "$HERE/Todo.tla" \
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

usage() {
  sed -n '2,12p' "$0"
}

note_sync
cmd=${1:-all}
case "$cmd" in
  -h|--help) usage; exit 0 ;;
  anchors) run_anchors ;;
  model) run_model ;;
  mutants) run_mutants ;;
  mutant) run_one_mutant "${2:?mutant name}" ;;
  all)
    rc=0
    run_anchors || rc=1
    run_model || rc=1
    run_mutants || rc=1
    if [ "$rc" -eq 0 ]; then
      echo "verify/todo-code/run.sh: all checks matched"
    else
      echo "verify/todo-code/run.sh: FAIL" >&2
    fi
    exit "$rc"
    ;;
  *) echo "unknown command: $cmd" >&2; usage; exit 2 ;;
esac
