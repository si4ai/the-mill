"""Replay recorded protocol events against the model (card 1311).

  python tools/trace_conform.py replay wake|todo EVENTS.jsonl [--lease-cap-s S] [--strict]
  python tools/trace_conform.py collect wake|todo --since STAMP [--until STAMP] --out EVENTS.jsonl

collect runs where the office book is (SELECT only): every transition row of each
wake touched in the window, its whole history, plus the wake rows' stored state
and the window. replay needs no book: same file, same bytes out.

EVENTS.jsonl lines: {"kind": "event", ...transition row...}, {"kind": "state",
"id": N, "state": S}, {"kind": "window", "since": T, "until": T}. A line with
no kind is an event.

Exit: 0 clean, 1 a forbidden step (with --strict: any forbidden, silent or
unmodelled), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# collect runs on the office host against the installed pack, so it must not need this
# module; replay imports it.
PROTOCOLS = ("wake", "todo")


def read_log(path: str) -> tuple[list[dict], dict[int, str], dict]:
    events: list[dict] = []
    states: dict[int, str] = {}
    window: dict = {}
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    for no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"trace_conform: {path}:{no}: not JSON ({exc})")
        if not isinstance(obj, dict):
            raise SystemExit(f"trace_conform: {path}:{no}: not an object")
        kind = obj.get("kind", "event")
        if kind == "state":
            states[int(obj["id"])] = str(obj["state"])
        elif kind == "window":
            window = obj
        else:
            events.append(obj)
    return events, states, window


def _summary(rep: dict) -> str:
    c = rep["counts"]
    return (f"{rep['protocol']}: {rep['events']} events; forbidden {c['forbidden']},"
            f" silent {c['silent']}, unmodelled {c['unmodelled']}")


def cmd_replay(args: argparse.Namespace) -> int:
    from agent_coord.server import trace_conform as tc

    try:
        events, states, window = read_log(args.log)
    except OSError as exc:
        print(f"trace_conform: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    rep = tc.replay(
        args.protocol,
        events,
        stored_states=states,
        lease_cap_s=args.lease_cap_s,
        window_end=args.window_end or window.get("until"),
    )
    if window:
        rep["window"] = {"since": window.get("since"), "until": window.get("until")}
    sys.stdout.write(json.dumps(rep, sort_keys=True, indent=1) + "\n")
    print(_summary(rep), file=sys.stderr)
    c = rep["counts"]
    bad = c["forbidden"] + ((c["silent"] + c["unmodelled"]) if args.strict else 0)
    return 1 if bad else 0


def _jsonable(v):
    if hasattr(v, "isoformat"):
        return v.isoformat(sep=" ")
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v


def cmd_collect(args: argparse.Namespace) -> int:
    from agent_coord.server.records import db

    cn = db.connect()
    cur = cn.cursor(buffered=True)
    try:
        cur.execute("SELECT UTC_TIMESTAMP(6)")
        now = str(cur.fetchone()[0])
        until = args.until or now
        cur.execute(
            "SELECT DISTINCT activity_id FROM transition WHERE activity_type = %s AND at >= %s AND at < %s",
            (args.protocol, args.since, until),
        )
        ids = sorted(int(r[0]) for r in cur.fetchall())
        rows: list[dict] = []
        states: list[tuple[int, str]] = []
        cols = ("id", "at", "activity_type", "activity_id", "from_state", "to_state", "reason",
                "desk_id", "role", "join_key", "meta", "n")
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            marks = ",".join(["%s"] * len(part))
            cur.execute(
                f"SELECT {', '.join(cols)} FROM transition WHERE activity_type = %s"
                f" AND activity_id IN ({marks}) AND at < %s ORDER BY id",
                (args.protocol, *part, until),
            )
            rows.extend(dict(zip(cols, (_jsonable(v) for v in r))) for r in cur.fetchall())
            if args.protocol == "wake":
                cur.execute(f"SELECT id, state FROM wake WHERE id IN ({marks})", tuple(part))
                states.extend((int(r[0]), str(r[1])) for r in cur.fetchall())
            elif args.protocol == "todo":
                # a retired card keeps its status on the row; the stored state is "retired"
                cur.execute(
                    f"SELECT t.id, IF(a.deleted IS NULL, t.status, 'retired') FROM todo t"
                    f" JOIN activity a ON a.type = 'todo' AND a.id = t.id WHERE t.id IN ({marks})",
                    tuple(part),
                )
                states.extend((int(r[0]), str(r[1])) for r in cur.fetchall())
    finally:
        cur.close()
        try:
            cn.rollback()
            cn.close()
        except Exception:
            pass
    rows.sort(key=lambda r: r["id"])
    out = [json.dumps({"kind": "window", "since": args.since, "until": until, "protocol": args.protocol})]
    out += [json.dumps({"kind": "state", "id": i, "state": s}) for i, s in sorted(states)]
    out += [json.dumps({"kind": "event", **r}, sort_keys=True) for r in rows]
    Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"trace_conform: {len(rows)} events, {len(ids)} objects -> {args.out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trace_conform", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("replay", help="check a recorded event log against the model")
    r.add_argument("protocol", choices=PROTOCOLS)
    r.add_argument("log", help="EVENTS.jsonl, or - for stdin")
    r.add_argument("--lease-cap-s", type=float, default=3600.0)
    r.add_argument("--window-end", default="", help="UTC stamp; default the log's window line")
    r.add_argument("--strict", action="store_true", help="also exit 1 on silent or unmodelled")
    c = sub.add_parser("collect", help="read a window of events from the office book (SELECT only)")
    c.add_argument("protocol", choices=PROTOCOLS)
    c.add_argument("--since", required=True, help="UTC stamp, e.g. 2026-11-19 00:00:00")
    c.add_argument("--until", default="", help="UTC stamp; default now")
    c.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return cmd_replay(args) if args.cmd == "replay" else cmd_collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
