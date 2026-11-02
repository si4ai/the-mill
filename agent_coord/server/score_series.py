"""Score series read shape: latest, target, gap and a trend word (#288, #307).

Pure functions over the mill_score_points rows; no SQL here. Points arrive
newest first by their time (--at, else when recorded).

Trend weighs the newest point (#307). better says which way is good.
- under 2 points: new
- the newest step against the point before it: past FLAT_PCT of that point
  it is improving or worse; a step back inside FLAT_PCT is flat
- an unchanged newest point is flat (equal values never read improving,
  whatever came before them)
- a small forward step: the newest point against the one 3 back says
  improving (a slow steady gain), or flat inside FLAT_PCT
- met replaces flat or improving when the latest is at or past the target;
  a step back past FLAT_PCT still reads worse, and gap still says met

A point lists desk only where it changes from the newer point above it, and its
time as MM-DD HH:MM, so a 10-point read stays well under 1 KB.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

FLAT_PCT = 0.02
WINDOW = 3
TREND_POINTS = 2 * WINDOW
NOTE_MAX = 200  # sp_score p_note VARCHAR(200) (#707)


_AGO = re.compile(r"[0-9]{1,6}[mhd]")
_WHEN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[ T][0-9]{2}:[0-9]{2}(?::[0-9]{2})?)?")


def at_ok(raw: str) -> bool:
    """--at shape (#308): Nm, Nh or Nd ago, or a real calendar time. Future is the SQL's call."""
    s = str(raw or "").strip()
    if _AGO.fullmatch(s):
        return True
    if not _WHEN.fullmatch(s):
        return False
    try:
        datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return False
    return True


def number(raw: Any) -> float | None:
    """A finite float from raw, else None (blank, words, nan and inf refused)."""
    try:
        v = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _flat(delta: float, base: float) -> bool:
    return abs(delta) <= FLAT_PCT * abs(base) or delta == 0


def trend(values_newest_first: list[float], better: str = "up", target: Any = None) -> str:
    vals = [float(v) for v in list(values_newest_first)[:TREND_POINTS]]
    if len(vals) < 2:
        return "new"
    sign = -1.0 if better == "down" else 1.0
    step = sign * (vals[0] - vals[1])
    if not _flat(step, vals[1]):
        word = "improving" if step > 0 else "worse"
    elif step <= 0:
        word = "flat"
    else:
        back = vals[min(WINDOW, len(vals) - 1)]
        drift = sign * (vals[0] - back)
        word = "flat" if _flat(drift, back) or drift < 0 else "improving"
    if word != "worse" and gap(vals[0], target, better) == "met":
        return "met"
    return word


def gap(latest: float | None, target: Any, better: str = "up") -> float | str | None:
    """target - latest, or met when latest is at or past target; None without both."""
    t = number(target)
    if latest is None or t is None:
        return None
    if (better == "down" and latest <= t) or (better != "down" and latest >= t):
        return "met"
    return _num(t - latest)


def _num(v: float) -> float | int:
    r = round(v, 6)
    return int(r) if r == int(r) else r


def _at(v: Any) -> str:
    """MM-DD HH:MM of the stored time (the book clock); the year and seconds add bytes, not use."""
    s = str(v or "").replace("T", " ")
    return s[5:16] if len(s) >= 16 else s


def shape(rows: list[dict], limit: int) -> list[dict]:
    """Group point rows by score id: one dict per score, newest points first."""
    out: list[dict] = []
    by_id: dict[int, dict] = {}
    for r in rows:
        sid = int(r.get("id") or 0)
        cur = by_id.get(sid)
        if cur is None:
            cur = {
                "score": str(r.get("kpi") or ""),
                "id": sid,
                "better": str(r.get("better") or "up"),
                "unit": str(r.get("unit") or ""),
                "target": str(r.get("target") or ""),
                "owner": str(r.get("owner") or ""),
                "_latest": str(r.get("latest") or ""),
                "points": [],
            }
            by_id[sid] = cur
            out.append(cur)
        if r.get("point_id") is not None:
            cur["points"].append(
                {
                    "v": _num(float(r.get("v") or 0.0)),
                    "desk": str(r.get("desk") or ""),
                    "at": _at(r.get("at")),
                    "note": str(r.get("note") or ""),
                }
            )
    shaped: list[dict] = []
    for cur in out:
        pts = cur["points"]
        vals = [float(p["v"]) for p in pts]
        latest = vals[0] if vals else number(cur["_latest"])
        prev = None
        for p in pts:
            if not p["note"]:
                del p["note"]
            # A run of points from one desk names it once, on the newest point of the run.
            if p["desk"] == prev:
                del p["desk"]
            else:
                prev = p["desk"]
        one = {
            "score": cur["score"],
            "id": cur["id"],
            "latest": _num(latest) if latest is not None else cur["_latest"],
            "target": cur["target"],
            "gap": gap(latest, cur["target"], cur["better"]),
            "trend": trend(vals, cur["better"], cur["target"]),
            "better": cur["better"],
            "unit": cur["unit"],
            "owner": cur["owner"],
        }
        if limit > 0:
            lim = int(limit)
            if len(pts) > lim:
                one["truncated"] = True
                one["truncated_n"] = len(pts) - lim
            one["points"] = pts[:lim]
        shaped.append(one)
    return shaped
