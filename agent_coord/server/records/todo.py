"""TODO = JOB+PLAN one card."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from agent_coord.const import CONST_DESK, CONST_ROSTER
from .db import call

_ETA_SPAN = re.compile(r"^(\d+)\s*([smhd])$", re.I)
_DONE_PCT = re.compile(r"(^|[\s])100%([\s.,;:]|$)")
_DONE_FRAC = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")
_DONE_WORD = re.compile(r"(^|[\s])done([\s.,;:]|$)")
_GIT_SHA = re.compile(r"\bgit\s+([0-9a-f]{7,40})\b", re.I)


def unpack(body: str, fallback_id: Any) -> dict[str, Any]:
    slug_s = str(fallback_id)
    detail = body or ""
    progress = ""
    payload = None
    aliases: list[str] = []
    raw = (body or "").strip()
    if raw.startswith("{"):
        try:
            got = json.loads(raw)
        except Exception:
            got = None
        if isinstance(got, dict):
            payload = got
            slug_s = str(got.get("slug") or slug_s)
            # #818: cards have no title. A legacy stored "doing" key is shown
            # as the head of the detail; nothing is migrated.
            legacy = str(got.get("doing") or "").strip()
            detail = str(got.get("detail") or "")
            if legacy and not detail.startswith(legacy):
                detail = legacy + ("\n" + detail if detail else "")
            progress = str(got.get("progress") or "")
            # #926: former need slugs reserved on this card (resolve + create refuse).
            raw_aliases = got.get("aliases") or []
            if isinstance(raw_aliases, list):
                aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
    return {
        "need_id": slug_s,
        "detail": detail,
        "progress": progress,
        "payload": payload,
        "aliases": aliases,
        "was": aliases[0] if aliases else "",
    }


# The card's whole budget is its column: todo.body VARCHAR(4096) utf8mb4 in
# tables.sql and IN p_body VARCHAR(4096) in sp_todo.sql. The stored body is
# json.dumps (ASCII), so characters and bytes agree. One limit, no per-note cap (#360).
BODY_MAX = 4096


def _bounded_body(body: str | None) -> str | None:
    if body is None:
        return None
    s = str(body)
    if len(s) <= BODY_MAX:
        return s
    from agent_coord.helpers.errors import CoordError

    raise CoordError(f"todo body must be 0..{BODY_MAX} chars")


def budget_left(payload: dict[str, Any]) -> int:
    """Characters a card has left before its stored body reaches BODY_MAX (#360)."""
    return BODY_MAX - len(json.dumps(dict(payload)))


def over_budget(before: dict[str, Any], after: dict[str, Any], command: str = "note") -> str:
    """The refusal when a note would take the card past BODY_MAX, else "" (#360).

    Every note on a card shares one budget, so the refusal says how much this
    note needs, how much is left, and where long text goes instead.
    """
    if len(json.dumps(dict(after))) <= BODY_MAX:
        return ""
    left = max(0, budget_left(before))
    need = len(json.dumps(dict(after))) - len(json.dumps(dict(before)))
    return (
        "%s: refused, nothing written: this note needs %d characters and the card has %d left "
        "of its %d (every note on a card shares one budget). Put the long text in a room letter "
        "(mill reply <mail_id> --body-file PATH) and note just its mail id here."
        % (command, need, left, BODY_MAX)
    )


def stored_body(payload: dict[str, Any]) -> str:
    """JSON body for a note. Over 4096 is a refusal, not a trim (#173)."""
    raw = json.dumps(dict(payload))
    if len(raw) > BODY_MAX:
        from agent_coord.helpers.errors import CoordError

        raise CoordError(
            "note: stored body is %s chars, over %s. Refused, nothing trimmed."
            % (len(raw), BODY_MAX)
        )
    return raw


def pack(payload: dict[str, Any]) -> str:
    """JSON body that fits p_body. Newest detail tail is kept when the diary is long."""
    data = dict(payload)
    raw = json.dumps(data)
    if len(raw) <= BODY_MAX:
        return raw
    detail = str(data.get("detail") or "")
    best = ""
    lo, hi = 0, len(detail)
    while lo <= hi:
        mid = (lo + hi) // 2
        data["detail"] = detail[len(detail) - mid :]
        trial = json.dumps(data)
        if len(trial) <= BODY_MAX:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    if best:
        return best
    data["detail"] = ""
    doing = str(data.get("doing") or "")
    lo, hi = 0, len(doing)
    while lo <= hi:
        mid = (lo + hi) // 2
        data["doing"] = doing[:mid]
        trial = json.dumps(data)
        if len(trial) <= BODY_MAX:
            best = trial
            lo = mid + 1
        else:
            hi = mid - 1
    if best:
        return best
    slug_s = str(data.get("slug") or "")[:64]
    trial = json.dumps({"slug": slug_s})
    return trial if len(trial) <= BODY_MAX else trial[:BODY_MAX]


def insert(cn, project: str, desk: str, status: str = "open", body: str = "") -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_todo_insert",
        [bare(project, CONST_ROSTER), bare(desk, CONST_DESK), status, _bounded_body(body)],
    )


def _duplicate_key(exc: BaseException) -> bool:
    """MySQL 1062. A fresh call gets a new autoincrement id; the rolled-back one stays spent."""
    if getattr(exc, "errno", None) == 1062:
        return True
    text = str(exc)
    return "1062" in text or "Duplicate entry" in text


def insert_attached(
    cn,
    project: str,
    desk: str,
    status: str,
    body: str,
    parent_type: str,
    parent_id: int,
) -> list[dict]:
    """Insert the card and attach it under the parent in one procedure call (#146).

    Up to three tries on 1062. Each try is the whole procedure, so a clash
    rolls the card back instead of leaving it half on the plan.
    """
    from agent_coord.server.records.name import bare

    args = [
        bare(project, CONST_ROSTER),
        bare(desk, CONST_DESK),
        status,
        _bounded_body(body),
        parent_type,
        int(parent_id),
    ]
    last: BaseException | None = None
    for _attempt in range(3):
        try:
            return call(cn, "mill_todo_insert_attached", args)
        except Exception as exc:
            last = exc
            if not _duplicate_key(exc):
                raise
    if last is not None:
        raise last
    raise RuntimeError("insert_attached produced no result")


def update(
    cn,
    todo_id: int,
    desk: str,
    status: str = "",
    volunteer: str = "",
    body: str | None = None,
) -> list[dict]:
    from agent_coord.server.records.name import bare

    return call(
        cn,
        "mill_todo_update",
        [
            todo_id,
            bare(desk, CONST_DESK),
            status,
            bare(volunteer, CONST_DESK) if volunteer else "",
            _bounded_body(body),
        ],
    )


def delete(cn, todo_id: int, desk: str) -> list[dict]:
    from agent_coord.server.records.name import bare
    from agent_coord.helpers.errors import CoordError

    desk_b = bare(desk, CONST_DESK) if desk else ""
    if not desk_b:
        raise CoordError("todo delete: desk required")
    return call(cn, "mill_todo_delete", [todo_id, desk_b])


def get(cn, todo_id: int) -> list[dict]:
    return call(cn, "mill_todo_get", [todo_id])


def select(cn, project: str, status: str = "") -> list[dict]:
    from agent_coord.server.records.name import roster_name

    return call(cn, "mill_todo_select", [roster_name(project) if project else "", status])


def page(
    cn, project: str, status: str = "", *, hide_done: bool = False, card_id: int = 0
) -> list[dict]:
    """mill_todo_select rows, filtered in SQL: hide_done drops done, card_id reads one card."""
    from agent_coord.server.records.name import roster_name

    return call(
        cn,
        "mill_todo_page",
        [roster_name(project) if project else "", status, 1 if hide_done else 0, int(card_id or 0)],
    )


def select_rosters(cn, names: list[str], status: str = "") -> list[tuple[str, dict]]:
    """mill_todo_select for many projects/roles in one read: [(requested name, card row)].

    Ids resolved once (name.roster_ids), then one read SP with the
    mill_todo_select row shape. Input name order, then updated DESC. None resolved -> [].
    """
    from agent_coord.server.records.name import roster_ids

    pairs = roster_ids(cn, names)
    if not pairs:
        return []
    ids = [aid for _n, aid in pairs]
    # #867: one read SP, same row shape as mill_todo_select (no raw SELECT).
    rows = call(cn, "mill_todo_select_rosters", [json.dumps(ids), (status or "").strip()])
    by_aff: dict[int, list[dict]] = {}
    for r in rows:
        by_aff.setdefault(int(r.get("roster_id") or 0), []).append(r)
    return [(name, r) for name, aid in pairs for r in by_aff.get(aid, [])]


def find(cn, project: str, need: str) -> dict | None:
    """Match mill-wall need slug, a former slug (#926), or numeric id."""
    rows = select(cn, project, "")
    raw = str(need or "")
    if raw.isdigit():
        for r in rows:
            if int(r.get("id") or 0) == int(raw):
                return r
    for r in rows:
        fields = unpack(r.get("body") or "", r.get("id"))
        if str(fields["need_id"]) == raw or raw in (fields.get("aliases") or []):
            return r
    return None


def retire(cn, todo_id: int, desk: str) -> list[dict]:
    """#19: soft delete. The card row, plan, labels and watchers stay; lists skip it."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_todo_retire", [int(todo_id), bare(desk, CONST_DESK)])


def reclaim(cn, todo_id: int, desk: str) -> list[dict]:
    """#19: undo retire. The card comes back with the status it had."""
    from agent_coord.server.records.name import bare

    return call(cn, "mill_todo_reclaim", [int(todo_id), bare(desk, CONST_DESK)])


def rename(
    cn,
    todo_id: int,
    desk: str,
    old_need: str,
    new_need: str,
    *,
    why: str = "",
) -> dict:
    """#926: change the card's need slug; keep id; reserve old slug in aliases.

    Auth (asker or Admin) is the caller's job. Writes one timeline row (act rename).
    """
    from agent_coord.helpers.errors import CoordError
    from agent_coord.helpers.ident import slug
    from agent_coord.server.records.name import bare

    old_s = slug(str(old_need or ""))
    new_s = slug(str(new_need or ""))
    if not old_s or not new_s:
        raise CoordError("rename todo: old and new need required")
    if old_s == new_s:
        raise CoordError("rename todo: old and new are the same; nothing changed")
    rows = get(cn, int(todo_id))
    if not rows:
        raise CoordError("rename todo: no such card")
    hit = rows[0]
    fields = unpack(hit.get("body") or "", hit.get("id"))
    if fields["need_id"] != old_s and old_s not in (fields.get("aliases") or []):
        raise CoordError(f"rename todo: card need is {fields['need_id']!r}, not {old_s!r}")
    # Roster of this card: refuse if new (or its aliases) already names another live card.
    roster = str(hit.get("roster") or "")
    if not roster:
        # get() may not join roster name; fall back via select by id through page
        from agent_coord.server.records.db import scalar_done

        roster = str(
            scalar_done(
                cn,
                "SELECT n.name FROM todo t JOIN name n ON n.id = t.roster_id WHERE t.id=%s",
                (int(todo_id),),
            )
            or ""
        )
    clash = find(cn, roster, new_s) if roster else None
    if clash is not None and int(clash.get("id") or 0) != int(todo_id):
        raise CoordError(
            f"rename todo: {roster}/{new_s} exists (id {int(clash['id'])}); nothing changed"
        )
    payload = dict(fields["payload"] or {"slug": fields["need_id"], "detail": fields["detail"]})
    aliases = [str(a) for a in (payload.get("aliases") or []) if str(a).strip()]
    # put the current slug first as the newest was; keep prior aliases; drop the new name if present.
    cur = str(payload.get("slug") or fields["need_id"])
    aliases = [a for a in aliases if a not in (cur, new_s, old_s)]
    if cur and cur != new_s:
        aliases = [cur] + aliases
    if old_s != cur and old_s != new_s and old_s not in aliases:
        aliases = [old_s] + aliases
    payload["slug"] = new_s
    payload["aliases"] = aliases
    body_s = stored_body(payload)
    why_s = str(why or "").strip()
    if len(why_s) > 1000:
        raise CoordError("rename todo: why must be 0..1000 characters; nothing changed")
    out = call(
        cn,
        "mill_todo_rename",
        [int(todo_id), bare(desk, CONST_DESK), old_s, new_s, body_s, why_s],
    )
    row = out[0] if out else {}
    return {
        "ok": True,
        "id": int(row.get("id") or todo_id),
        "need_id": str(row.get("need_id") or new_s),
        "was": str(row.get("was") or cur or old_s),
        "op": str(row.get("op") or "renamed"),
        "why": why_s,
    }


def find_retired(cn, project: str, need: str) -> dict | None:
    """A retired card on this roster by need slug or numeric id (the reclaim lookup)."""
    from agent_coord.server.records.name import roster_ids

    pairs = roster_ids(cn, [project]) if project else []
    if not pairs:
        return None
    rows = call(cn, "mill_todo_select_retired", [int(pairs[0][1])])  # #867: a read SP
    raw = str(need or "")
    for r in rows:
        if raw.isdigit() and int(r.get("id") or 0) == int(raw):
            return r
    for r in rows:
        fields = unpack(r.get("body") or "", r.get("id"))
        if str(fields["need_id"]) == raw or raw in (fields.get("aliases") or []):
            return r
    return None


# tables.sql todo.status. Old mill name was JOB/PLAN/need.
STATUSES = ("parked", "open", "claimed", "shipped", "done")
_STATUS_ALIASES = {
    "todo": "parked",
    "parked": "parked",
    "doing": "open",
    "upcoming": "open",
    "open": "open",
    "claimed": "claimed",
    "shipped": "shipped",
    "done": "done",
}


def normalize_status(raw: str, *, default: str = "open") -> str:
    st = _STATUS_ALIASES.get((raw or "").strip().lower(), "")
    if st:
        return st
    d = (default or "").strip().lower()
    if d in STATUSES:
        return d
    return "open" if default != "" else ""


def require_status(raw: str, *, allow_empty: bool = False) -> str:
    s = (raw or "").strip()
    if not s:
        if allow_empty:
            return ""
        raise ValueError("status must be parked, open, claimed, shipped, or done")
    st = normalize_status(s, default="")
    if st not in STATUSES:
        raise ValueError("status must be parked, open, claimed, shipped, or done")
    return st


def progress_is_done(progress: str) -> bool:
    p = (progress or "").strip().lower()
    if not p:
        return False
    if p in ("done", "100", "100%"):
        return True
    if _DONE_PCT.search(p) or _DONE_WORD.search(p):
        return True
    if progress_git_sha(p):
        return True
    m = _DONE_FRAC.search(p)
    if m and int(m.group(2)) > 0 and int(m.group(1)) >= int(m.group(2)):
        return True
    return False


def progress_git_sha(progress: str) -> str:
    m = _GIT_SHA.search(progress or "")
    return (m.group(1).lower() if m else "")


def is_progress_token(text: str) -> bool:
    """Short progress text (9/12, 75%, done, git <sha>), not a diary line."""
    s = (text or "").strip()
    if not s or len(s) > 64:
        return False
    if re.fullmatch(r"\d+\s*/\s*\d+", s) or re.fullmatch(r"\d{1,3}\s*%", s):
        return True
    if s.lower() == "done":
        return True
    return bool(re.fullmatch(r"git\s+[0-9a-f]{7,40}", s, re.I))


def format_progress(
    text: str = "",
    *,
    n: int | None = None,
    of: int | None = None,
    pct: int | None = None,
    note: str = "",
) -> str:
    parts: list[str] = []
    raw = (text or "").strip()
    if raw:
        parts.append(raw)
    elif n is not None and of is not None:
        parts.append(f"{int(n)}/{int(of)}")
    elif pct is not None:
        parts.append(f"{int(pct)}%")
    elif n is not None:
        parts.append(str(int(n)))
    extra = (note or "").strip()
    if extra:
        parts.append(extra)
    return " ".join(parts)[:64]


def parse_eta(raw: str | None, now: datetime | None = None) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    now = now or datetime.now()
    m = _ETA_SPAN.match(s)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        sec = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        if n < 1:
            raise ValueError("eta must be >= 1")
        return now + timedelta(seconds=n * sec)
    t = s.replace("T", " ").replace("Z", "").split("+")[0].strip()
    try:
        dt = datetime.fromisoformat(t)
    except ValueError as e:
        raise ValueError("eta must be 20m / 2h / 90s / 1d or YYYY-MM-DD HH:MM") from e
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def is_validator_pass_body(src: str, body: str) -> bool:
    s = (src or "").strip().lower()
    if s not in ("validator", "build-validator"):
        return False
    b = (body or "").lower()
    return "validation verdict" in b and "passed" in b


def pass_mail_closes(src: str, body: str, needs: list[dict]) -> list[str]:
    if not is_validator_pass_body(src, body):
        return []
    b = (body or "").lower()
    out: list[str] = []
    for rec in needs:
        st = (rec.get("status") or "").strip().lower()
        prog = rec.get("progress") or ""
        if st not in ("claimed", "shipped"):
            continue
        if st == "claimed" and not progress_is_done(prog):
            continue
        nid = str(rec.get("need_id") or "")
        sha = progress_git_sha(prog)
        if nid and nid.lower() in b:
            out.append(nid)
        elif sha and sha in b:
            out.append(nid)
    return out
