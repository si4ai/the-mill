"""Card 925 (score slice): caller-observed fixture check.

Text anchors pin guard lines; they can't see a later overwrite of the value a
caller gets. This check runs the real code path on fixture logs with no DB:
measure() -> tick()/publish() (admin_upsert stubbed) -> wall kpi_miss(), plus
score_series.shape() for a series with no points.

Asserts: ws_miss measured 1 and published ('1', '0') with the Wall red;
hold_blocked_ms 100; an empty series has gap None (missing, not zero).

  python3 behave.py --root ROOT            # fixture on the tree at ROOT
  python3 behave.py --root ROOT --mutants  # each built-in mutant must go red
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

TICK = "agent_coord/server/score_tick.py"
WALL = "agent_coord/web/wall_logic/score.py"
SERIES = "agent_coord/server/score_series.py"

# (name, path, old, new): old must occur exactly once in path.
MUTANTS = [
    ("host_item_reset", TICK, "    host = _measure_host(dest, since)\n",
     "    host = _measure_host(dest, since)\n    host[KPI_WS_MISS] = 0\n"),
    ("host_rebind", TICK, "    host = _measure_host(dest, since)\n",
     "    host = _measure_host(dest, since)\n    host = {}\n"),
    ("dupkey_wsmiss_after_spread", TICK, "        **host,\n",
     "        **host,\n        KPI_WS_MISS: 0,\n"),
    ("dupkey_hold_after_field", TICK, "        KPI_HOLD_BLOCKED_MS: hold_blocked_ms,\n",
     "        KPI_HOLD_BLOCKED_MS: hold_blocked_ms,\n        KPI_HOLD_BLOCKED_MS: 0,\n"),
    ("hold_rescaled", TICK, "hold_blocked_ms = measure_hold_blocked(perf_text, since)\n",
     "hold_blocked_ms = measure_hold_blocked(perf_text, since) // 1000\n"),
    ("tick_counts_zeroed", TICK, "    pub = publish(counts)\n",
     "    counts[KPI_WS_MISS] = 0\n    pub = publish(counts)\n"),
    ("wall_tn_forced", WALL, "    if tn == 0:\n        return ln != 0\n",
     "    tn = tn or 1\n    if tn == 0:\n        return ln != 0\n"),
    ("wall_none_guard_widened", WALL, "    if ln is None or tn is None:\n",
     "    if ln is None or tn is None or tn == 0:\n"),
    ("wall_numish_target_forced", WALL, "    ln, tn = numish(last), numish(target)\n",
     "    ln, tn = numish(last), 1.0\n"),
    ("series_gap_or_zero", SERIES, "        shaped.append(one)\n",
     "        one[\"gap\"] = one[\"gap\"] or 0\n        shaped.append(one)\n"),
]


def _load(root: pathlib.Path, name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fixture(root: pathlib.Path) -> list[str]:
    sys.path.insert(0, str(root))
    import agent_coord.server.records as R
    import agent_coord.server.records.db as db
    import agent_coord.server.records.score as sc

    calls: list[tuple] = []
    R.connect = lambda: mock.MagicMock()
    sc.admin_upsert = lambda cn, kpi, val, tgt, note: calls.append((kpi, val, tgt)) or 1
    sc.upsert = lambda *a, **k: 1
    db.call = lambda *a, **k: None
    st = _load(root, "score_tick_fx", TICK)
    st.office_name = lambda cn: "o"
    wl = _load(root, "wall_score_fx", WALL)
    ss = _load(root, "score_series_fx", SERIES)

    now = dt.datetime.now(dt.timezone.utc)
    ts = (now - dt.timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    d = pathlib.Path(tempfile.mkdtemp(prefix="score-behave-"))
    try:
        (d / "mill-backchannel.log").write_text(
            f"{ts} hub send miss=2 desk=x\n{ts} hub send miss=0 desk=y\n")
        (d / "mill-perf.log").write_text(
            f"{ts} op=hold.blocked ms=40\n{ts} op=hold.blocked ms=60\n")
        r = st.tick(dest=d, window_s=300)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    bad = []
    if r.get(st.KPI_WS_MISS) != 1:
        bad.append(f"measure ws_miss {r.get(st.KPI_WS_MISS)!r}, want 1")
    if r.get(st.KPI_HOLD_BLOCKED_MS) != 100:
        bad.append(f"measure hold_blocked_ms {r.get(st.KPI_HOLD_BLOCKED_MS)!r}, want 100")
    pub = [c for c in calls if c[0] == st.KPI_WS_MISS]
    if not pub:
        bad.append("ws_miss not published")
    else:
        _, val, tgt = pub[-1]
        if (val, tgt) != ("1", "0"):
            bad.append(f"ws_miss published {(val, tgt)!r}, want ('1', '0')")
        if wl.kpi_miss(val, tgt) is not True:
            bad.append("wall not red for published ws_miss")
    if wl.kpi_miss("2", "0") is not True:
        bad.append("wall not red for ('2', '0')")
    rows = [{"id": 7, "kpi": "k", "better": "down", "target": "0", "latest": "", "point_id": None}]
    shaped = ss.shape(rows, 5)
    if not shaped or shaped[0].get("gap") is not None:
        bad.append(f"empty series gap {shaped[0].get('gap') if shaped else 'missing'!r}, want None")
    return bad


def run_mutants(root: pathlib.Path) -> int:
    rc = 0
    for name, rel, old, new in MUTANTS:
        src = (root / rel).read_text(encoding="utf-8")
        if src.count(old) != 1:
            print(f"behave mutant {name}: FAIL (site not found once in {rel}; recheck)")
            rc = 1
            continue
        t = pathlib.Path(tempfile.mkdtemp(prefix="score-bm-"))
        try:
            shutil.copytree(root / "agent_coord", t / "agent_coord")
            (t / rel).write_text(src.replace(old, new, 1), encoding="utf-8")
            p = subprocess.run([sys.executable, __file__, "--root", str(t)],
                               capture_output=True, text=True, cwd=tempfile.gettempdir())
        finally:
            shutil.rmtree(t, ignore_errors=True)
        if p.returncode == 0:
            print(f"behave mutant {name}: FAIL (fixture stayed green)")
            rc = 1
        else:
            print(f"behave mutant {name}: red as expected")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--mutants", action="store_true")
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    if a.mutants:
        return run_mutants(root)
    bad = fixture(root)
    for b in bad:
        print(f"behave: FAIL {b}")
    if not bad:
        print("behave: ok (ws_miss 1 published ('1','0') wall red; hold_ms 100; empty gap None)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
