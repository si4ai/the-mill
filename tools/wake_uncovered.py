"""List addressed letter-desk pairs with no delivered wake (card 826).

Read-only. Two modes:

  python tools/wake_uncovered.py classify   # unit helper (events in, sets out)
  python tools/wake_uncovered.py report --since STAMP [--log PATH]

report reads mill-backchannel.log* wake lines and the office book (mail_to
asked rows since STAMP), then prints covered / uncovered letter-desk pairs.
A pair is covered when any wake line for that desk names the letter id with
wake=sent, wake=coalesced (held for a later trailing/sent), or the desk was
sitting (over its socket). Uncovered: addressed, webhook-armed, and no such
line. Soft-fails to stderr when the book or log is missing.

Desk or Validator use: run against the cloud office after a cut to re-measure
826. Does not POST or change the book.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import os
import re
import sys
from pathlib import Path
from typing import Iterable

_WAKE = re.compile(
    r"^(\S+)\s+webhook desk=(\S+) (?:kind=mail|type=\S+) id=(\d+) wake=(\S+)"
)
_SIT = re.compile(r"^(\S+)\s+ws (sit|leave) desk=(\S+) n=(\d+)")


def classify(events: Iterable[tuple[str, int, str | None]]) -> dict[str, set[tuple[str, int]]]:
    """events: (desk, mail_id, outcome|None). coalesced or sent => covered."""
    covered: set[tuple[str, int]] = set()
    seen: set[tuple[str, int]] = set()
    for desk, mid, outcome in events:
        key = (str(desk), int(mid))
        seen.add(key)
        if outcome in ("sent", "coalesced"):
            covered.add(key)
    return {"covered": covered, "uncovered": seen - covered}


def parse_log(paths: list[Path], since: str) -> tuple[dict[str, list], dict[tuple[str, int], list]]:
    """Return sit events per desk and wake outcomes per (desk, id)."""
    ev: dict[str, list] = collections.defaultdict(list)
    wl: dict[tuple[str, int], list] = {}
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", errors="replace") as fh:
            for line in fh:
                if line[:16] < since:
                    continue
                m = _SIT.search(line)
                if m:
                    ev[m.group(3)].append((m.group(1)[:19], m.group(2), int(m.group(4))))
                    continue
                m = _WAKE.search(line)
                if m:
                    wl.setdefault((m.group(2), int(m.group(3))), []).append(
                        (m.group(4), m.group(1)[:19])
                    )
    for d in ev:
        ev[d].sort()
    return ev, wl


def sitting_at(ev: dict[str, list], desk: str, when: str) -> bool:
    n = 0
    for te, what, k in ev.get(desk, []):
        if te > when:
            break
        if what in ("sit", "leave"):
            n = k
    return n > 0


def default_log_paths() -> list[Path]:
    home = Path(os.environ.get("AGENT_COORD_MILL_HOME") or Path.home() / ".mill")
    paths = sorted(home.glob("mill-backchannel.log*"))
    return paths


def report(since: str, log_paths: list[Path] | None = None) -> int:
    """Print covered / uncovered counts. Exit 0 always when it can read; 1 on hard fail."""
    paths = log_paths or default_log_paths()
    if not paths:
        print("wake_uncovered: no mill-backchannel.log under mill home", file=sys.stderr)
        return 1
    ev, wl = parse_log(paths, since)
    try:
        import mysql.connector
        from agent_coord.config import mysql_kwargs
    except Exception as e:
        print(f"wake_uncovered: book import failed: {type(e).__name__}", file=sys.stderr)
        return 1
    try:
        cn = mysql.connector.connect(**mysql_kwargs())
        cur = cn.cursor()
        cur.execute(
            "SELECT n.name FROM seat s JOIN name n ON n.id=s.desk_id "
            "WHERE s.endpoint_key IS NOT NULL AND s.endpoint_key<>''"
        )
        armed = {r[0] for r in cur.fetchall()}
        cut = since.replace("T", " ")
        cur.execute(
            "SELECT m.id, m.created, n.name FROM mail m "
            "JOIN mail_to mt ON mt.type='mail' AND mt.id=m.id "
            "JOIN name n ON n.id=mt.desk_id "
            "WHERE m.created >= %s AND mt.desk_id<>m.desk_id AND mt.asked=1",
            (cut,),
        )
        rows = cur.fetchall()
        cur.close()
        cn.close()
    except Exception as e:
        print(f"wake_uncovered: book read failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    counts: collections.Counter = collections.Counter()
    uncovered: list[tuple] = []
    for mid, created, desk in rows:
        when = created.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(created, "strftime") else str(created)[:19]
        if desk not in armed:
            counts["not-armed"] += 1
            continue
        lines = wl.get((desk, int(mid)), [])
        outs = {o for o, _ in lines}
        if "sent" in outs or "coalesced" in outs:
            counts["covered-wake"] += 1
            continue
        if sitting_at(ev, desk, when) and not lines:
            counts["covered-socket"] += 1
            continue
        if "skipped" in outs:
            counts["room-only-skip"] += 1
            continue
        counts["uncovered"] += 1
        uncovered.append((int(mid), desk, when))

    print(f"since={since} pairs={len(rows)} armed_desks={len(armed)}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    if uncovered:
        print("uncovered (mail_id desk when):")
        for mid, desk, when in uncovered[:50]:
            print(f"  {mid} {desk} {when}")
        if len(uncovered) > 50:
            print(f"  ... and {len(uncovered) - 50} more")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("classify", help="no-op self-check for the unit helper")
    r = sub.add_parser("report", help="scan log + book for uncovered pairs")
    r.add_argument("--since", required=True, help="UTC stamp YYYY-MM-DDTHH:MM:SS")
    r.add_argument("--log", action="append", type=Path, help="log path (repeatable)")
    args = p.parse_args(argv)
    if args.cmd == "classify":
        sample = classify([("d", 1, "sent"), ("d", 2, None)])
        print(sample)
        return 0 if sample["uncovered"] == {("d", 2)} else 1
    return report(args.since, args.log)


if __name__ == "__main__":
    raise SystemExit(main())
