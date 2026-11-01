#!/bin/sh
# desk-start.sh: POSIX launcher for Grok Build desks on Linux/WSL/macOS.
# Reads planner JSON from desk_start_plan.py and execs grok. No GNU-only flags.
# Credential check: Windows Credential Manager (cmdkey), macOS keychain, or a
# mode-600 file named by credential_target.
set -eu

USAGE='usage: desk-start.sh --config PATH --desk NAME [--dry-run] [--session-id UUID]'

CONFIG=""
DESK=""
DRY_RUN=0
SESSION_ID=""

while [ $# -gt 0 ]; do
  case "$1" in
    --config)
      [ $# -ge 2 ] || { echo "desk-start: --config needs a path" >&2; exit 2; }
      CONFIG=$2
      shift 2
      ;;
    --desk)
      [ $# -ge 2 ] || { echo "desk-start: --desk needs a name" >&2; exit 2; }
      DESK=$2
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --session-id)
      [ $# -ge 2 ] || { echo "desk-start: --session-id needs a value" >&2; exit 2; }
      SESSION_ID=$2
      shift 2
      ;;
    -h|--help)
      echo "$USAGE"
      exit 0
      ;;
    *)
      echo "desk-start: unknown arg: $1" >&2
      echo "$USAGE" >&2
      exit 2
      ;;
  esac
done

if [ -z "$CONFIG" ] || [ -z "$DESK" ]; then
  echo "desk-start: --config and --desk are required" >&2
  echo "$USAGE" >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PLAN_PY="$SCRIPT_DIR/desk_start_plan.py"

# Resolve credential_target for DESK from config (python; config is JSON).
target=$(python3 - "$CONFIG" "$DESK" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
want = sys.argv[2]
for d in cfg.get("desks") or []:
    if d.get("name") == want:
        t = d.get("credential_target")
        if not t:
            sys.exit("desk-start: desk missing credential_target")
        print(t)
        break
else:
    sys.exit("desk-start: desk not found in config: " + want)
PY
) || {
  echo "$target" >&2
  exit 1
}

# cred_present TARGET: prints backend name on stdout, exit 0 if present.
# covers: Credential Manager (cmdkey), macOS keychain, mode-600 file.
cred_present() {
  _t=$1
  if command -v cmdkey >/dev/null 2>&1; then
    if cmdkey /list 2>/dev/null | grep -F "$_t" >/dev/null 2>&1; then
      echo "Credential Manager"
      return 0
    fi
  fi
  if command -v security >/dev/null 2>&1; then
    if security find-generic-password -s "$_t" >/dev/null 2>&1; then
      echo "macOS keychain"
      return 0
    fi
  fi
  if [ -f "$_t" ]; then
    _mode=$(check_mode600 "$_t") || return 1
    if [ "$_mode" = ok ]; then
      echo "mode-600 file"
      return 0
    fi
  fi
  return 1
}

# check_mode600 PATH: ok only when regular file mode is exactly 0600.
check_mode600() {
  _p=$1
  # POSIX: ls -l; prefer stat when it speaks portable -c/-f carefully.
  if command -v stat >/dev/null 2>&1; then
    _m=$(stat -c '%a' "$_p" 2>/dev/null || stat -f '%OLp' "$_p" 2>/dev/null || echo "")
    if [ "$_m" = "600" ] || [ "$_m" = "0600" ]; then
      echo ok
      return 0
    fi
    return 1
  fi
  # Fallback: ls -l first char of mode group for owner rw-------
  _ls=$(ls -l -d "$_p" 2>/dev/null || ls -ld "$_p")
  case "$_ls" in
    -rw-------*) echo ok; return 0 ;;
  esac
  return 1
}

CRED_WHERE=""
if CRED_WHERE=$(cred_present "$target"); then
  :
else
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "desk-start: credential (target $target) missing" >&2
    exit 1
  fi
  echo "desk-start: credential (target $target) missing" >&2
  exit 1
fi

# Build argv carefully without word-splitting issues via "$@"
set -- --config "$CONFIG" --desk "$DESK"
if [ -n "$SESSION_ID" ]; then
  set -- "$@" --session-id "$SESSION_ID"
fi

PLAN_JSON=$(python3 "$PLAN_PY" "$@") || {
  echo "desk-start: planner failed" >&2
  exit 1
}

# Patch credential.where to the backend we actually used.
PLAN_JSON=$(CRED_WHERE="$CRED_WHERE" TARGET="$target" PLAN_JSON="$PLAN_JSON" python3 - <<'PY'
import json, os
plan = json.loads(os.environ["PLAN_JSON"])
if isinstance(plan, dict) and "plans" not in plan:
    plan.setdefault("credential", {})
    plan["credential"]["where"] = os.environ["CRED_WHERE"]
    plan["credential"]["target"] = os.environ["TARGET"]
print(json.dumps(plan, indent=2, sort_keys=True))
PY
)

if [ "$DRY_RUN" -eq 1 ]; then
  printf '%s\n' "$PLAN_JSON"
  exit 0
fi

# Live launch: refuse dashboard (UNVERIFIED) the same way as the ps1.
launch_mode=$(PLAN_JSON="$PLAN_JSON" python3 - <<'PY'
import json, os
p = json.loads(os.environ["PLAN_JSON"])
print((p.get("launch_mode") or "dashboard").lower())
PY
)
if [ "$launch_mode" = "dashboard" ]; then
  echo "desk-start: launch_mode=dashboard attach recipe is UNVERIFIED; refuse live launch. Use --dry-run or set office.launch_mode to window." >&2
  exit 1
fi

if ! command -v grok >/dev/null 2>&1; then
  echo "desk-start: grok not on PATH" >&2
  exit 1
fi

# Exec argv from the plan (list of strings).
PLAN_JSON="$PLAN_JSON" python3 - <<'PY'
import json, os, sys
p = json.loads(os.environ["PLAN_JSON"])
argv = p.get("argv") or p.get("window_argv") or []
if not argv:
    sys.stderr.write("desk-start: plan has empty argv\n")
    sys.exit(1)
os.execvp(argv[0], argv)
PY
