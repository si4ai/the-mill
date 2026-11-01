"""Observer wall. Live office state is the book. Markdown parsers are import-only."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# tests/test_coord.py uses t- + 8 hex. Those must not appear on the live wall.
_FIXTURE_PROJECT = re.compile(r"^t-[0-9a-f]{8}$")
_HUMAN_CARD = re.compile(r"^\s*HUMAN\b", re.I)


# Same pattern as string (Coord purge-fixtures REGEXP).
FIXTURE_RE = r"^t-[0-9a-f]{8}$"


def is_fixture_project(project_id: str | None) -> bool:
    return bool(project_id and _FIXTURE_PROJECT.match(project_id))


def alive_owner_count(agents: list[dict[str, Any]] | None) -> int:
    """Unique alive mill owners. Two PIDs for one desk count as one SESSION agent."""
    return len(
        {
            str(a.get("owner") or "")
            for a in (agents or [])
            if a.get("alive") and a.get("owner")
        }
    )


def is_human_card(rec: dict[str, Any] | None) -> bool:
    """HELP WANTED leftover only a person can close (U8 / U20)."""
    if not rec:
        return False
    text = str(rec.get("doing") or rec.get("detail") or "")
    return bool(_HUMAN_CARD.match(text))


def wanted_cards(needs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Unowned jobs for HELP WANTED. HUMAN leftovers first, then need_id."""
    open_rows = [r for r in (needs or []) if r.get("status") == "open"]
    return sorted(
        open_rows,
        key=lambda r: (0 if is_human_card(r) else 1, str(r.get("need_id") or "")),
    )


def parse_roots(spec: str | None = None, cwd: Path | None = None) -> dict[str, Path]:
    """Map project_id -> root. Env AGENT_COORD_ROOTS is `name=path;name=path`.

    Paths are ordinary filesystem paths (Windows or WSL). No host-specific defaults.
    """
    roots: dict[str, Path] = {}
    raw = spec if spec is not None else os.environ.get("AGENT_COORD_ROOTS", "")
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, path = part.split("=", 1)
        name = name.strip()
        p = Path(path.strip()).expanduser()
        if name:
            roots[name] = p
    here = (cwd or Path.cwd()).resolve()
    for cand in (here, here.parent):
        if not cand.is_dir():
            continue
        try:
            kids = list(cand.iterdir())
        except OSError:
            continue
        for child in kids:
            if not child.is_dir():
                continue
            if (child / "SCORECARD.md").is_file() or (child / "docs" / "SCORECARD.md").is_file():
                roots.setdefault(child.name, child)
    if (here / "SCORECARD.md").is_file() or (here / "docs" / "SCORECARD.md").is_file():
        roots.setdefault(here.name, here)
    return roots


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_sep(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(set(c.replace(":", "").replace(" ", "")) <= {"-"} for c in cells)


def parse_tables(text: str, *, first_only: bool = False) -> list[dict[str, str]]:
    """Markdown tables. first_only=True stops after the first table (deprecated kpi-import seed; not live Last)."""
    rows: list[dict[str, str]] = []
    headers: list[str] | None = None
    seen_table = False
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            if first_only and seen_table:
                break
            headers = None
            continue
        cells = _cells(line)
        if _is_sep(cells):
            continue
        if headers is None:
            headers = [h.lower() for h in cells]
            seen_table = True
            continue
        rec = {headers[i]: cells[i] if i < len(cells) else "" for i in range(len(headers))}
        rows.append(rec)
    return rows


def scorecard_kpis(text: str) -> list[dict[str, str]]:
    """First SCORECARD.md table only (deprecated kpi-import seed). Not Wall Last."""
    out = []
    for rec in parse_tables(text, first_only=True):
        kpi = rec.get("kpi") or rec.get("lever") or ""
        if not kpi:
            continue
        value = (
            rec.get("last")
            or rec.get("last number")
            or rec.get("this cycle")
            or rec.get("needle f1")
            or rec.get("value")
            or ""
        )
        out.append(
            {
                "kpi": kpi,
                "value": value,
                "target": rec.get("target") or rec.get("note") or "",
                "note": rec.get("meaning") or rec.get("caveat") or rec.get("split") or "",
            }
        )
    return out


def loop_cycles(text: str) -> list[dict[str, str]]:
    rows = []
    for rec in parse_tables(text):
        if "cycle" not in rec:
            continue
        rows.append(rec)
    return rows


def last_cycle_heading(text: str) -> str:
    """Newest cycle heading. Files write newest first; do not use the last ## Cycle in the file."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Cycle") or (
            stripped.startswith("## ") and "cycle" in stripped.lower()
        ):
            return stripped.lstrip("#").strip()
    return ""


def _plain(cell: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell or "").strip()


def loop_kpis(cycles: list[dict[str, str]], current_id: str) -> list[dict[str, str]]:
    """Turn the current (or latest) INDEX row into KPI cells. Not SCORECARD.md prose."""
    if not cycles:
        return []
    cur = None
    if current_id:
        for rec in cycles:
            if _plain(rec.get("cycle") or "") == str(current_id):
                cur = rec
                break
    if cur is None:
        cur = cycles[-1]
    skip = {"cycle", "lever", "note"}
    out = []
    for key, val in cur.items():
        if key in skip:
            continue
        out.append(
            {
                "kpi": key,
                "value": _plain(val),
                "target": "",
                "note": _plain(cur.get("note") or cur.get("lever") or ""),
            }
        )
    if cur.get("lever"):
        out.insert(0, {"kpi": "lever", "value": _plain(cur["lever"]), "target": "", "note": ""})
    return out


def load_line(project_id: str, root: Path) -> dict[str, Any]:
    """One product line's judged-loop board. Does not read traces or checkpoints.

    If data/loop/INDEX.md exists (demo-app), that plus current.json is the
    loop archive. SCORECARD.md is deprecated archive/seed for kpi-import only;
    Wall Last is agent_kpi.
    """
    root = Path(root)
    card = root / "SCORECARD.md"
    if not card.is_file():
        alt = root / "docs" / "SCORECARD.md"
        if alt.is_file():
            card = alt
    index = root / "data" / "loop" / "INDEX.md"
    current = root / "data" / "loop" / "current.json"
    score_text = card.read_text(encoding="utf-8") if card.is_file() else ""
    index_text = index.read_text(encoding="utf-8") if index.is_file() else ""
    cur: dict[str, Any] = {}
    if current.is_file():
        try:
            cur = json.loads(current.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cur = {}
    cycles = loop_cycles(index_text)[:12]
    for rec in cycles:
        if "cycle" in rec:
            rec["cycle"] = _plain(rec["cycle"])
    current_id = str(cur.get("id") or "")
    if cycles:
        kpis = loop_kpis(cycles, current_id)
        source = "loop"
        cycle = current_id or (cycles[-1].get("cycle") if cycles else "")
    else:
        kpis = scorecard_kpis(score_text)[:24]
        source = "scorecard"
        cycle = last_cycle_heading(score_text) or current_id
    return {
        "project_id": project_id,
        "root": str(root),
        "has_scorecard": card.is_file() or bool(cycles),
        "source": source,
        "cycle": cycle,
        "current": cur,
        "kpis": kpis,
        "loop": cycles,
    }


def decay_s() -> int:
    raw = (os.environ.get("AGENT_COORD_DECAY_S") or "").strip()
    if raw:
        return max(0, int(raw))
    return 15 * 60


# Session and the floor share this. Age equal to the threshold is still alive.
HEARTBEAT_STALE_S = 15 * 60


def heartbeat_flags(
    updated: Any,
    *,
    now: datetime | None = None,
    sitting: bool = False,
) -> tuple[bool, bool]:
    """(alive, stale) from join.updated. A missing time is stale.

    sitting=True: the desk has a live /ws right now, so it stays alive even when
    seat.updated is old (card 985; plain connect used to look stale while up).
    """
    if sitting:
        return True, False
    if now is None:
        now = datetime.now()
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    age = _age_s(updated, now)
    if age is None or age > HEARTBEAT_STALE_S:
        return False, True
    return True, False


def _as_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    s = str(value).strip().replace("T", " ").replace("Z", "")
    s = s.split("+")[0].strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _age_s(value: Any, now: datetime) -> float | None:
    at = _as_dt(value)
    if at is None:
        return None
    return max(0.0, (now - at).total_seconds())


def _on_it(
    needs: list[dict[str, Any]],
    locks: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """JOBS ON IT: claimed jobs, else live register.doing and file leases."""
    claimed = []
    covered: set[tuple[str, str]] = set()
    for rec in needs:
        if rec.get("status") != "claimed":
            continue
        row = dict(rec)
        row.setdefault("kind", "card")
        row.setdefault("source", "need")
        claimed.append(row)
        covered.add((row.get("project_id") or "", row.get("volunteer") or ""))
    leases_by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lock in locks:
        if lock.get("holder_dead"):
            continue
        key = (lock.get("project_id") or "", lock.get("owner") or "")
        leases_by.setdefault(key, []).append(lock)
    extra: list[dict[str, Any]] = []
    skip_doing = {"", "standup-wall", "present"}
    by_owner: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in agents:
        if not rec.get("alive"):
            continue
        key = (rec.get("project_id") or "", rec.get("owner") or "")
        by_owner.setdefault(key, []).append(rec)
    for key, rows in by_owner.items():
        if key in covered:
            continue
        preferred = [r for r in rows if (r.get("doing") or "").strip() not in skip_doing]
        rec = preferred[0] if preferred else rows[0]
        leases = leases_by.get(key, [])
        doing = (rec.get("doing") or "").strip()
        if not doing and not leases:
            continue
        resources = ", ".join(str(x.get("resource") or "") for x in leases if x.get("resource"))
        extra.append(
            {
                "kind": "session",
                "source": "register",
                "status": "current",
                "project_id": rec.get("project_id"),
                "need_id": "",
                "asker": "",
                "volunteer": rec.get("owner"),
                "doing": doing or (leases[0].get("doing") if leases else ""),
                "detail": f"leases: {resources}" if resources else "session",
                "progress": "",
                "holder_dead": False,
            }
        )
        covered.add(key)
    for key, leases in leases_by.items():
        if key in covered or not leases:
            continue
        lock = leases[0]
        resources = ", ".join(str(x.get("resource") or "") for x in leases if x.get("resource"))
        extra.append(
            {
                "kind": "lease",
                "source": "lease",
                "status": "current",
                "project_id": lock.get("project_id"),
                "need_id": lock.get("resource") or "",
                "asker": "",
                "volunteer": lock.get("owner"),
                "doing": lock.get("doing") or "",
                "detail": f"leases: {resources}",
                "progress": "",
                "holder_dead": False,
            }
        )
        covered.add(key)
    return claimed + extra


def board_view(
    floor: dict[str, Any],
    *,
    now: datetime | None = None,
    decay: int | None = None,
) -> dict[str, Any]:
    """Observer wall: drop fixture projects; WIRE packets age off after decay_s.

    Live stations (locks, live agents, open/claimed needs) do not decay. Done needs stay for Jobs Done window.
    Mailbox stays (fades after decay_s). Default decay 15 minutes (AGENT_COORD_DECAY_S).
    """
    # MySQL DATETIME(3) is naive session time (usually host local). UTC now
    # makes every packet look hours old and WIRE goes blank.
    now = now or datetime.now().replace(tzinfo=None)
    ttl = decay_s() if decay is None else max(0, int(decay))
    out = dict(floor)
    for key in ("events", "mailbox", "locks", "agents", "kpis", "needs", "spend", "spend_lines", "issues"):
        out[key] = [
            r for r in (floor.get(key) or []) if not is_fixture_project(r.get("project_id"))
        ]
    kept_events = []
    half = ttl / 2.0 if ttl else 0.0
    for rec in out["events"]:
        age = _age_s(rec.get("at"), now)
        rec = dict(rec)
        rec["age_s"] = age
        if ttl and age is not None and age > ttl:
            continue
        rec["fading"] = bool(half and age is not None and age > half)
        kept_events.append(rec)
    out["events"] = kept_events
    kept_mail = []
    for rec in out["mailbox"]:
        age = _age_s(rec.get("at"), now)
        rec = dict(rec)
        rec["age_s"] = age
        rec["fading"] = bool(ttl and age is not None and age > ttl)
        kept_mail.append(rec)
    out["mailbox"] = kept_mail
    kept_needs = []
    for rec in out["needs"]:
        rec = dict(rec)
        rec["progress"] = rec.get("progress") or ""
        if rec.get("status") == "done":
            # Keep done history for Jobs Done time-window (1h..30d/all).
            # WIRE still decays via events TTL; Done column filters in the wall.
            age = _age_s(rec.get("updated_at") or rec.get("asked_at"), now)
            rec["fading"] = bool(ttl and age is not None and age > ttl)
        kept_needs.append(rec)
    out["needs"] = kept_needs
    out["on_it"] = _on_it(kept_needs, out["locks"], out["agents"])
    out["wanted"] = wanted_cards(kept_needs)
    out["decay_s"] = ttl
    out["projects"] = [p for p in (floor.get("projects") or []) if not is_fixture_project(p)]
    agents = out["agents"]
    out["live_agents"] = alive_owner_count(agents)
    out["live_locks"] = len(out["locks"])
    out["dead_holders"] = sum(1 for r in out["locks"] if r.get("holder_dead"))
    out["remote_holders"] = sum(1 for r in out["locks"] if r.get("remote"))
    needs = out.get("needs") or []
    out["open_needs"] = sum(1 for n in needs if n.get("status") == "open")
    out["claimed_needs"] = sum(1 for n in needs if n.get("status") == "claimed")
    iss = out.get("issues") or []
    out["open_issues"] = sum(1 for i in iss if i.get("status") in ("todo", "doing"))
    return out


def kpi_slug(name: str) -> str:
    """SCORECARD.md cell -> agent_kpi.kpi. DEPRECATED one-shot seed only, not the wall path."""
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")[:64]
    return s.lower() if s else ""


def markdown_kpis(text: str) -> list[dict[str, str]]:
    """First SCORECARD.md table as publishable rows (DEPRECATED seed). Never used by snapshot/floor."""
    out: list[dict[str, str]] = []
    for rec in scorecard_kpis(text):
        key = kpi_slug(rec.get("kpi") or "")
        if not key:
            continue
        out.append(
            {
                "kpi": key,
                "value": (rec.get("value") or "")[:64],
                "target": (rec.get("target") or "")[:64],
                "note": (rec.get("note") or "")[:200],
            }
        )
    return out


def book_scorecards(kpis: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Group judged agent_kpi rows into the wall SCORECARDS payload. Empty records => {}."""
    boards: dict[str, dict[str, Any]] = {}
    for rec in kpis or []:
        pid = str(rec.get("project_id") or rec.get("roster_id") or "")
        if not pid or is_fixture_project(pid):
            continue
        board = boards.setdefault(
            pid,
            {
                "project_id": pid,
                "source": "records",
                "has_scorecard": True,
                "kpis": [],
                "cycle": "",
                "loop": [],
                "current": {},
                "root": "",
            },
        )
        board["kpis"].append(
            {
                "kpi": rec.get("kpi") or "",
                "value": rec.get("value") or "",
                "target": rec.get("target") or "",
                "note": rec.get("note") or "",
                "owner": rec.get("owner") or "",
                "updated_at": rec.get("updated_at") or "",
            }
        )
    return boards


def snapshot(floor: dict[str, Any], roots: dict[str, Path] | None = None) -> dict[str, Any]:
    """Live office snapshot. Scorecards/kpis from the records (agent_kpi), never disk files.

    `roots` is ignored. parse_roots/load_line must not feed the floor.
    """
    del roots
    out = board_view(floor)
    out["scorecards"] = book_scorecards(out.get("kpis"))
    out["roots"] = {}
    return out
