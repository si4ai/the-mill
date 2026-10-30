"""GET /api/floor - CALL mill_* only. DATETIME(6) on the wire."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from agent_coord.const import (
    CONST_HOLD,
    CONST_DOING,
    CONST_MAIL,
    CONST_OFFICE,
    CONST_SCORE,
    CONST_TODO,
    CONST_TREE,
)
from . import join as rec_join
from . import mail as rec_mail
from . import name as rec_name
from . import activity as rec_activity
from . import score as rec_score
from . import hold as rec_hold
from . import todo as rec_todo
from . import tree as rec_tree
from . import watcher as rec_watcher
from agent_coord.helpers.names import MillName
from agent_coord.helpers.ident import iso6



_FP_PARTS = frozenset({"mail", "trees", "todos", "agents", "scores", "holds", "events"})


def parse_floor_fps(qs: dict[str, list[str]] | None) -> dict[str, str]:
    """Parse ?fp=mail:hex,trees:hex and/or fp_<part>=hex into a part->fp map."""
    out: dict[str, str] = {}
    if not qs:
        return out
    def _ok(hexv: str) -> bool:
        h = (hexv or "").strip().lower()
        return len(h) == 16 and all(c in "0123456789abcdef" for c in h)
    raw = ""
    for v in qs.get("fp") or []:
        if v:
            raw = str(v)
            break
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece or ":" not in piece:
            continue
        part, hexv = piece.split(":", 1)
        part = part.strip().lower()
        hexv = hexv.strip().lower()
        if part in _FP_PARTS and _ok(hexv):
            out[part] = hexv
    for key, vals in qs.items():
        if not key.startswith("fp_") or key == "fp_":
            continue
        part = key[3:].strip().lower()
        hexv = ((vals or [""])[0] or "").strip().lower()
        if part in _FP_PARTS and _ok(hexv):
            out[part] = hexv
    return out


def _part_fp(cn, kind: str, ident: str, part: str) -> str:
    from .db import call
    rows = call(cn, "mill_floor_fp", [kind, ident, part])
    if not rows:
        return ""
    return str(rows[0].get("fp") or "")


def _projects_part_fp(cn, projects: list[str], part: str) -> str:
    """Fingerprint one part across one or more project names (MySQL mill_fp owns hash)."""
    from .db import scalar
    slugs = [p for p in projects if p]
    if not slugs:
        return _part_fp(cn, "project", "", part)
    fps = [_part_fp(cn, "project", s, part) for s in slugs]
    if len(fps) == 1:
        return fps[0]
    return str(scalar(cn, "SELECT mill_fp(%s)", (":".join(fps),)) or "")


def _nm(value: Any) -> str:
    return str(value or "").strip()


def _gid(r: dict[str, Any]):
    """SQL group_id (tables.sql) or leftover project_id alias."""
    return r.get("roster_id") or r.get("group_id") or r.get("project_id")


def window_bucket(window: str) -> tuple[datetime, str]:
    """15m->min, 1h->5min, 24h->hour, 7d->day."""
    w = (window or "24h").strip().lower()
    now = datetime.now()
    if w in ("15m", "15min"):
        return now - timedelta(minutes=15), "min"
    if w in ("1h", "hour"):
        return now - timedelta(hours=1), "5min"
    if w in ("7d", "week"):
        return now - timedelta(days=7), "day"
    return now - timedelta(hours=24), "hour"


def _name_catalog(rows_in: list[dict]) -> list[dict]:
    """Every name, grouped for the glossary. Deleted stays in its group.

    name is the bare name and name_type is the kind. Both come from SQL.
    """
    import re
    rows: list[dict] = []
    unnamed = 0
    ordered = sorted(rows_in, key=lambda r: str(r.get("name") or "").lower())
    for rec in ordered:
        shown = str(rec.get("name") or "")
        if not shown:
            continue
        item = MillName(str(rec.get("name_type") or ""), shown)
        gone = rec.get("deleted") is not None
        if item.type == CONST_TREE and re.fullmatch(r"[0-9a-f]{10}", item.str, re.I):
            unnamed += 1
            continue
        rows.append({"kind": item.type, "name": item.str, "deleted": gone})
    if unnamed:
        rows.append({"kind": "tree", "name": "", "n": unnamed, "hidden": True})
    return rows


LIST_TEXT_MAX = 256
LIST_PAGE_DEFAULT = 50
LIST_PAGE_MAX = 500  # mill_mail_list SP LIMIT


def parse_list_page(
    qs: dict[str, list[str]] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[int, str | None]:
    """Resolve ?limit= (default 50, max 500) and ?cursor= for lean list pages."""
    lim = limit
    cur = cursor
    if qs is not None:
        raw_lim = (qs.get("limit") or [""])[0]
        if lim is None:
            try:
                lim = int(str(raw_lim).strip()) if str(raw_lim).strip() else LIST_PAGE_DEFAULT
            except (TypeError, ValueError):
                lim = LIST_PAGE_DEFAULT
        raw_cur = (qs.get("cursor") or [""])[0]
        if cur is None:
            cur = str(raw_cur).strip() or None
    if lim is None:
        lim = LIST_PAGE_DEFAULT
    try:
        lim = int(lim)
    except (TypeError, ValueError):
        lim = LIST_PAGE_DEFAULT
    if lim < 1:
        lim = 1
    if lim > LIST_PAGE_MAX:
        lim = LIST_PAGE_MAX
    if cur is not None:
        cur = str(cur).strip() or None
    return lim, cur


def page_by_cursor(
    rows: list[dict],
    limit: int,
    cursor: str | None,
    *,
    key: str = "id",
    get_key=None,
) -> tuple[list[dict], str | None]:
    """Slice rows in display order after cursor; return (page, next|None).
    Cursor is the opaque string of the last row key from the prior page
    (default key=id). Unknown cursor => empty page, next null (client resets).
    Optional get_key(row)->str overrides key lookup (e.g. type:id for events).
    """
    lim = int(limit) if limit else LIST_PAGE_DEFAULT
    if lim < 1:
        lim = 1
    def _k(row: dict | None) -> str:
        if get_key is not None:
            return str(get_key(row) or "")
        return str((row or {}).get(key) or "")
    start = 0
    if cursor:
        cur = str(cursor).strip()
        found = False
        for i, row in enumerate(rows or []):
            if _k(row) == cur:
                start = i + 1
                found = True
                break
        if not found:
            return [], None
    seq = list(rows or [])
    page = seq[start : start + lim]
    nxt: str | None = None
    if page and (start + lim) < len(seq):
        nxt = _k(page[-1]) or None
    return page, nxt



TREE_DEPTH_DEFAULT = 1


def parse_tree_depth(
    qs: dict[str, list[str]] | None = None,
    *,
    depth: int | None = None,
) -> int:
    """Resolve ?depth= for progressive trees (default 1). Invalid -> 1. Min 0."""
    val = depth
    if qs is not None and val is None:
        raw = (qs.get("depth") or [""])[0]
        if str(raw).strip():
            try:
                val = int(str(raw).strip())
            except (TypeError, ValueError):
                val = TREE_DEPTH_DEFAULT
        else:
            val = TREE_DEPTH_DEFAULT
    if val is None:
        val = TREE_DEPTH_DEFAULT
    try:
        val = int(val)
    except (TypeError, ValueError):
        val = TREE_DEPTH_DEFAULT
    if val < 0:
        val = 0
    return val


def parse_tree_parent_id(
    qs: dict[str, list[str]] | None = None,
    *,
    parent_id: str | None = None,
) -> str | None:
    """Resolve ?parent_id= as opaque type:id (e.g. mail:101). Empty -> None."""
    val = parent_id
    if qs is not None and val is None:
        raw = (qs.get("parent_id") or [""])[0]
        val = str(raw).strip() or None
    if val is None:
        return None
    s = str(val).strip()
    return s or None


TREE_WINDOW_DURATIONS = {
    "1d": timedelta(days=1),
    "1w": timedelta(days=7),
    "30d": timedelta(days=30),
}


def parse_tree_window(
    qs: dict[str, list[str]] | None = None,
    *,
    window: str | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """Resolve ?window=1d|1w|30d for tree-mail/todo. Omit/empty = All (None).

    Invalid non-empty value raises ValueError (middleware maps to HTTP 400).
    Returns cutoff datetime (keep forests with last_activity >= cutoff).
    """
    val = window
    if qs is not None and val is None:
        raw = (qs.get("window") or [""])[0]
        val = str(raw).strip() if raw is not None else ""
    if val is None:
        return None
    key = str(val).strip().lower()
    if not key:
        return None
    if key not in TREE_WINDOW_DURATIONS:
        raise ValueError(
            "invalid window; use window=1d|1w|30d or omit for All"
        )
    n = now if now is not None else datetime.now()
    return n - TREE_WINDOW_DURATIONS[key]


def filter_trees_by_window(
    trees: list[dict],
    since: datetime | None,
    last_by_name: dict[str, object] | None,
) -> list[dict]:
    """Keep forests whose last TREE activity is >= since. since=None => All."""
    if since is None:
        return list(trees or [])
    last = last_by_name or {}
    out: list[dict] = []
    for tree in trees or []:
        name = str(tree.get("name") or "")
        act = last.get(name)
        if act is None:
            continue
        if act >= since:
            out.append(tree)
    return out



def _parse_parent_type_id(parent_id: str | None) -> tuple[str, int] | None:
    if not parent_id:
        return None
    s = str(parent_id).strip()
    if ":" not in s:
        return None
    typ, _, rest = s.partition(":")
    typ = typ.strip().lower()
    rest = rest.strip()
    if not typ or not rest:
        return None
    try:
        return typ, int(rest)
    except (TypeError, ValueError):
        return None


def _tree_stream_cursor_key(row: dict | None) -> str:
    """Opaque forest|type:id|lft for progressive tree paging."""
    r = row or {}
    forest = str(r.get("_forest") or "")
    typ = str(r.get("type") or "")
    return f"{forest}|{typ}:{r.get('id')}|{r.get('lft')}"


def _ensure_node_has_children(node: dict) -> dict:
    n = dict(node)
    if "has_children" not in n:
        lft = int(n.get("lft") or 0)
        rgt = int(n.get("rgt") or 0)
        n["has_children"] = rgt > lft + 1
    return n


def _flatten_trees_stream(
    trees: list[dict],
    *,
    depth: int,
    parent_id: str | None,
) -> list[dict]:
    """Forest-order nest-set stream: depth-capped roots, or direct children of parent_id."""
    stream: list[dict] = []
    if parent_id is not None:
        parsed = _parse_parent_type_id(parent_id)
        if parsed is None:
            return []
        ptyp, pid = parsed
        for tree in trees or []:
            fname = str(tree.get("name") or "")
            hidden = bool(tree.get("hidden"))
            nodes = list(tree.get("nodes") or [])
            parent = None
            for n in nodes:
                if str(n.get("type") or "") == ptyp and int(n.get("id") or 0) == pid:
                    parent = n
                    break
            if parent is None:
                continue
            plft = int(parent.get("lft") or 0)
            prgt = int(parent.get("rgt") or 0)
            pdepth = int(parent.get("depth") or 0)
            for n in nodes:
                nlft = int(n.get("lft") or 0)
                nrgt = int(n.get("rgt") or 0)
                ndepth = int(n.get("depth") or 0)
                if not (plft < nlft and nrgt < prgt):
                    continue
                if ndepth != pdepth + 1:
                    continue
                item = _ensure_node_has_children(n)
                item["_forest"] = fname
                item["_hidden"] = hidden
                stream.append(item)
        return stream

    cap = int(depth) if depth is not None else TREE_DEPTH_DEFAULT
    for tree in trees or []:
        fname = str(tree.get("name") or "")
        hidden = bool(tree.get("hidden"))
        for n in tree.get("nodes") or []:
            if int(n.get("depth") or 0) <= cap:
                item = _ensure_node_has_children(n)
                item["_forest"] = fname
                item["_hidden"] = hidden
                stream.append(item)
    return stream


def _repack_trees_page(page: list[dict]) -> list[dict]:
    """Rebuild trees[] forest shape from flat progressive page rows."""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    hidden: dict[str, bool] = {}
    for row in page or []:
        fname = str(row.get("_forest") or "")
        if fname not in groups:
            groups[fname] = []
            order.append(fname)
            hidden[fname] = bool(row.get("_hidden"))
        node = {k: v for k, v in row.items() if not str(k).startswith("_")}
        groups[fname].append(node)
    return [
        {"name": name, "hidden": hidden.get(name, False), "nodes": groups[name]}
        for name in order
    ]


def page_trees_progressive(
    trees: list[dict],
    limit: int,
    cursor: str | None,
    *,
    depth: int | None = None,
    parent_id: str | None = None,
) -> tuple[list[dict], str | None]:
    """Page nest-set stream; return (trees subset, next|None)."""
    cap = TREE_DEPTH_DEFAULT if depth is None else int(depth)
    stream = _flatten_trees_stream(trees or [], depth=cap, parent_id=parent_id)
    page, nxt = page_by_cursor(
        stream, limit, cursor, get_key=_tree_stream_cursor_key
    )
    return _repack_trees_page(page), nxt


_FLOOR_PAGE_ORDER = (
    "mail",
    "todos",
    "agents",
    "scores",
    "holds",
    "watchers",
    "events",
)


def _floor_primary_page_part(partset: set[str] | None) -> str | None:
    """Which dense part owns ?cursor= / response next. Trees PARK."""
    if partset is None:
        return "mail"
    for name in _FLOOR_PAGE_ORDER:
        if name in partset:
            return name
    return None


def _events_cursor_key(row: dict | None) -> str:
    r = row or {}
    typ = str(r.get("type") or r.get("kind") or "")
    return f"{typ}:{r.get('id')}"


def _names_cursor_key(row: dict | None) -> str:
    r = row or {}
    return f"{r.get('kind') or ''}:{r.get('name') or ''}"


def _activity_row_id(row: dict) -> str:
    if row.get("id") not in (None, ""):
        return str(row.get("id"))
    return "|".join(
        str(row.get(k) or "")
        for k in ("updated", "type", "desk_id", "owner", "roster_id")
    )


def apply_floor_list_page(
    out: dict[str, Any],
    *,
    limit: int | None = None,
    cursor: str | None = None,
    partset: set[str] | None = None,
) -> dict[str, Any]:
    """Page dense floor lists (N=50 default). Trees untouched. Sets out['next'].
    desk_unread / office_glance / fp must already reflect the full pre-page sets.
    ?cursor= applies to the primary pageable part only; other dense parts get
    the first page (limit). Prefer parts=<one> for infinite scroll.

    Call AFTER board_view/snapshot (TTL + fixture drops). Paging pre-filter
    can leave next set while events/lists are empty - infinite-scroll footgun.
    """
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    primary = _floor_primary_page_part(partset)
    def wanted(name: str) -> bool:
        return partset is None or name in partset
    def cur_for(name: str) -> str | None:
        return page_cur if name == primary else None
    next_by: dict[str, str | None] = {}
    if wanted("mail"):
        page, nxt = page_by_cursor(list(out.get("mailbox") or []), page_lim, cur_for("mail"))
        out["mailbox"] = page
        next_by["mail"] = nxt
    if wanted("todos"):
        needs = list(out.get("needs") or [])
        issues = list(out.get("issues") or [])
        need_ids = {int(c.get("id") or 0) for c in needs}
        stream = needs + issues
        page, nxt = page_by_cursor(stream, page_lim, cur_for("todos"))
        out["needs"] = [c for c in page if int(c.get("id") or 0) in need_ids]
        out["issues"] = [c for c in page if int(c.get("id") or 0) not in need_ids]
        next_by["todos"] = nxt
    if wanted("agents"):
        agents = list(out.get("agents") or [])
        for a in agents:
            if a.get("id") in (None, ""):
                a["id"] = a.get("owner") or a.get("pid") or ""
        page, nxt = page_by_cursor(agents, page_lim, cur_for("agents"))
        out["agents"] = page
        next_by["agents"] = nxt
    if wanted("scores"):
        kpis = list(out.get("kpis") or [])
        for row in kpis:
            if row.get("id") in (None, ""):
                row["id"] = "|".join(
                    str(row.get(k) or "") for k in ("owner", "kpi", "roster_id")
                )
        page, nxt = page_by_cursor(kpis, page_lim, cur_for("scores"))
        out["kpis"] = page
        next_by["scores"] = nxt
    if wanted("holds"):
        locks = list(out.get("locks") or [])
        for row in locks:
            if row.get("id") in (None, ""):
                row["id"] = "|".join(
                    str(row.get(k) or "") for k in ("resource", "owner", "roster_id")
                )
        page, nxt = page_by_cursor(locks, page_lim, cur_for("holds"))
        out["locks"] = page
        next_by["holds"] = nxt
    if wanted("watchers"):
        page, nxt = page_by_cursor(
            list(out.get("watchers") or []),
            page_lim,
            cur_for("watchers"),
            get_key=_events_cursor_key,
        )
        out["watchers"] = page
        next_by["watchers"] = nxt
    if wanted("events"):
        page, nxt = page_by_cursor(
            list(out.get("events") or []),
            page_lim,
            cur_for("events"),
            get_key=_events_cursor_key,
        )
        out["events"] = page
        next_by["events"] = nxt
    nxt_out: str | None = None
    if primary and primary in next_by:
        nxt_out = next_by[primary]
    else:
        for name in _FLOOR_PAGE_ORDER:
            if name in next_by:
                nxt_out = next_by[name]
                if nxt_out is not None:
                    break
    out["next"] = nxt_out
    return out


def lean_text(text: str | None, n: int = LIST_TEXT_MAX) -> tuple[str, bool]:
    """Truncate public text for list/poll. Returns (text, truncated)."""
    s = text if isinstance(text, str) else ("" if text is None else str(text))
    limit = int(n) if n and int(n) > 0 else LIST_TEXT_MAX
    if len(s) <= limit:
        return s, False
    return s[:limit], True


def _clip(text: str, n: int = 80) -> str:
    s = " ".join(str(text or "").split())
    if len(s) <= n:
        return s
    return s[: n - 1] + "..."


def _meta_for(typ: str, iid: int, todos: dict, mails: dict, names: dict) -> dict[str, str]:
    if typ == CONST_TODO:
        row = todos.get(iid) or {}
        if not row:
            return {}
        return {
            "title": _clip(row.get("detail") or row.get("need_id")),
            "status": str(row.get("status") or ""),
            "who": str(row.get("volunteer") or row.get("asker") or ""),
        }
    if typ == CONST_MAIL:
        row = mails.get(iid) or {}
        if not row:
            return {}
        sender = row.get("sender") or row.get("src") or ""
        if isinstance(sender, dict):
            who = str(sender.get("deskId") or sender.get("desk") or "")
        else:
            who = str(sender)
        return {
            "title": _clip(row.get("body")),
            "status": "mail",
            "who": who,
        }
    return {}


def _filter_tree_nodes(nodes: list[dict], want: set[str] | None) -> list[dict]:
    if not want:
        return nodes
    hit = [i for i, node in enumerate(nodes) if _keep(node, want)]
    if not hit:
        return []
    keep: set[int] = set(hit)
    for i in hit:
        lft = int(nodes[i].get("lft") or 0)
        rgt = int(nodes[i].get("rgt") or 0)
        for j, anc in enumerate(nodes):
            if int(anc.get("lft") or 0) < lft and int(anc.get("rgt") or 0) > rgt:
                keep.add(j)
    kept = [nodes[i] for i in range(len(nodes)) if i in keep]
    for node in kept:
        lft = int(node.get("lft") or 0)
        rgt = int(node.get("rgt") or 0)
        node["depth"] = sum(
            1 for other in kept if int(other.get("lft") or 0) < lft and int(other.get("rgt") or 0) > rgt
        )
    return kept


def _tree_face(typ: str, raw: dict, meta: dict) -> tuple[str, str, str]:
    """Label a tree node. tree.type is an activity: mail todo doing hold score."""
    title = str(meta.get("title") or "")
    status = str(meta.get("status") or "")
    who = str(meta.get("who") or "")
    iid = raw.get("id")
    if typ == CONST_DOING:
        desk = _nm(str(raw.get("join_desk") or ""))
        doing = _clip(str(raw.get("join_doing") or ""))
        label = desk or title or f"doing {iid}"
        if doing:
            label = f"{label} | {doing}" if desk else doing
        return label, "doing", ""
    if typ == CONST_HOLD:
        res = _nm(str(raw.get("hold_resource") or ""))
        desk = _nm(str(raw.get("hold_desk") or ""))
        return res or title or f"hold {iid}", "hold", desk
    if typ == CONST_SCORE:
        kpi = _nm(str(raw.get("score_kpi") or ""))
        desk = _nm(str(raw.get("score_desk") or ""))
        return kpi or title or f"score {iid}", "score", desk
    if typ == CONST_TODO and raw.get("todo_body") is not None:
        fields = rec_todo.unpack(str(raw.get("todo_body") or ""), iid)
        label = _clip(fields.get("detail") or fields.get("need_id")) or title
        return label, str(raw.get("todo_status") or status or "todo"), who
    if typ == CONST_MAIL and raw.get("mail_body") is not None:
        src = _nm(str(raw.get("mail_src") or "")) or who
        return _clip(str(raw.get("mail_body") or "")) or title, "mail", src
    return title, status, who


def _floor_trees(
    cn,
    want: set[str] | None,
    todos: dict,
    mails: dict,
    names: dict,
    roster_ids: list[int] | None = None,
    *,
    rows: list[dict] | None = None,
    mail: bool = False,
    keep_all_nodes: bool = False,
) -> list[dict]:
    enriched = []
    if rows is not None:
        raw_rows = rows
    elif mail:
        raw_rows = rec_tree.mail_forest_rows(cn, roster_ids)
    else:
        raw_rows = rec_tree.glance_rows(cn, roster_ids)
    for raw in raw_rows:
        typ = str(raw.get("type") or "")
        iid = int(raw.get("id") or 0)
        aff = _nm(str(names.get(int(raw.get("roster_id") or 0)) or ""))
        meta = _meta_for(typ, iid, todos, mails, names)
        title, status, who = _tree_face(typ, raw, meta)
        enriched.append(
            {
                "tree": str(raw.get("tree") or ""),
                "type": typ,
                "id": iid,
                "lft": int(raw.get("lft") or 0),
                "rgt": int(raw.get("rgt") or 0),
                "roster_id": aff,
                "title": title,
                "status": status,
                "who": who,
            }
        )
    trees = []
    for tree in rec_tree.pack_trees(enriched):
        nodes = list(tree.get("nodes") or [])
        if not keep_all_nodes:
            nodes = _filter_tree_nodes(nodes, want)
        if want and not nodes:
            continue
        trees.append({**tree, "nodes": nodes})
    return trees


def build_watchers(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
    *,
    todos: dict | None = None,
    mails: dict | None = None,
    names: dict | None = None,
    roster_ids: list[int] | None = None,
) -> list[dict]:
    """Watchers isolate: glance_rows + pack/group; title/status from todos/mails/names."""
    del mail_ps  # scope via roster_ids / want (holds-like call shape)
    todos = todos if todos is not None else {}
    mails = mails if mails is not None else {}
    if names is None:
        names = {int(r["id"]): str(r.get("name") or "") for r in rec_name.select(cn)}
    if roster_ids is None and want:
        roster_ids = [
            i for i, nm in names.items() if nm in want or _nm(nm) in want
        ]
    enriched = []
    for raw in rec_watcher.glance_rows(cn, roster_ids):
        typ = str(raw.get("type") or "")
        iid = int(raw.get("id") or 0)
        aff = _nm(str(names.get(int(raw.get("roster_id") or 0)) or ""))
        meta = _meta_for(typ, iid, todos, mails, names)
        title = str(meta.get("title") or "")
        status = str(meta.get("status") or "")
        if typ == CONST_SCORE:
            title = _nm(str(raw.get("kpi") or "")) or title
            status = "score"
        enriched.append(
            {
                "type": typ,
                "id": iid,
                "desk": _nm(str(raw.get("desk") or "")),
                "custom": raw.get("custom"),
                "roster_id": aff,
                "title": title,
                "status": status,
            }
        )
    rows = rec_watcher.group_watchers(rec_watcher.pack_watchers(enriched))
    if not want:
        return rows
    return [row for row in rows if _keep(row, want)]


def _keep(row: dict[str, Any], want: set[str] | None) -> bool:
    if not want:
        return True
    pid = str(
        row.get("roster_id")
        or row.get("roster")
        or row.get("group_id")
        or row.get("project_id")
        or ""
    )
    if pid in want:
        return True
    sender = row.get("sender")
    if isinstance(sender, dict):
        saff = str(sender.get("roster") or "")
        if saff and saff in want:
            return True
    for t in row.get("mail_tos") or []:
        aff = str((t or {}).get("roster") or "")
        if aff and aff in want:
            return True
    return False


def _glance(agents: list[dict], mailbox: list[dict], needs: list[dict], window: str = "24h") -> dict[str, Any]:
    desks = []
    seen: set[str] = set()
    for a in agents:
        owner = str(a.get("owner") or "")
        if not owner or owner in seen:
            continue
        seen.add(owner)
        alive = bool(a.get("alive"))
        stale = bool(a.get("stale")) if "stale" in a else (not alive)
        desks.append(
            {
                "owner": owner,
                "group_id": a.get("group_id") or a.get("project_id") or "",
                "role": a.get("role") or "",
                "doing": a.get("doing") or "",
                "alive": alive,
                "stale": stale,
                "unread": 0,
                "human_required": 0,
                "needs_attention": False,
                "tokens": 0,
                "usd": 0,
                "jobs_done": 0,
                "owner_host": "",
            }
        )
    counts: dict[tuple[str, str], int] = {}
    for m in mailbox:
        sender = m.get("sender") or m.get("src") or ""
        if isinstance(sender, dict):
            src = str(sender.get("deskId") or sender.get("desk") or "")
        else:
            src = str(sender)
        if not src:
            continue
        dests = m.get("mail_tos") or []
        if dests:
            for t in dests:
                dst = str((t or {}).get("deskId") or (t or {}).get("desk") or "")
                if not dst or dst == "*":
                    continue
                key = (src, dst)
                counts[key] = counts.get(key, 0) + 1
        else:
            dst = str(m.get("dst") or "")
            if not dst or dst == "*":
                continue
            key = (src, dst)
            counts[key] = counts.get(key, 0) + 1
    edges = [
        {"src": a, "dst": b, "n": n}
        for (a, b), n in sorted(counts.items(), key=lambda kv: -kv[1])[:200]
    ]
    stale = sum(1 for n in needs if n.get("status") == "claimed" and n.get("stale"))
    return {"window": window, "desks": desks, "edges": edges, "stale_claims": stale}


def _timeline(cn, project: str, window: str = "24h") -> list[dict[str, Any]]:
    since, buck = window_bucket(window)
    out = []
    for r in rec_activity.bucket(cn, project, 0, "", since, buck):
        row = {
            "updated": iso6(r.get("updated") or r.get("lastUpdate") or r.get("lastUpdated")),
            "type": r.get("type"),
            "desk_id": r.get("desk_id"),
            "owner": _nm(r.get("desk")),
            "roster_id": _nm(r.get("roster")),
            "n": int(r.get("n") or 0),
        }
        row["id"] = _activity_row_id(row)
        out.append(row)
    return out


def page_activity_rows(
    rows: list[dict],
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> tuple[list[dict], str | None]:
    """Page /api/activity rows; stamp opaque id when missing."""
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    stamped: list[dict] = []
    for r in rows or []:
        row = dict(r)
        row["id"] = _activity_row_id(row)
        stamped.append(row)
    return page_by_cursor(stamped, page_lim, page_cur)


def floor(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    parts: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    from agent_coord.helpers.ident import this_host
    from agent_coord.install.packver import package_version
    partset = {str(x).strip() for x in (parts or []) if str(x).strip()} or None
    def use(name: str) -> bool:
        return partset is None or name in partset
    want: set[str] | None = None
    if projects:
        want = {_nm(str(x).strip()) for x in projects if str(x).strip()}
    elif project:
        want = {_nm(str(project).strip())}
    if projects:
        p = _nm(str(projects[0]).strip())
    elif project:
        p = _nm(str(project).strip())
    else:
        p = ""
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    fps_out: dict[str, str] = {}
    # Bare project names. mill_floor_fp looks up type project and that string.
    if projects:
        mail_ps = []
        for raw in projects:
            slug = _nm(str(raw).strip())
            if slug not in mail_ps:
                mail_ps.append(slug)
    elif p:
        mail_ps = [p]
    else:
        mail_ps = []
    def _fp_for(part: str) -> str:
        if mail_ps:
            return _projects_part_fp(cn, mail_ps, part)
        return _part_fp(cn, "project", "", part)
    mail_skip = False
    if use("mail"):
        cur = _fp_for("mail")
        fps_out["mail"] = cur
        mail_skip = client_fps.get("mail") == cur and bool(cur)
    trees_skip = False
    if use("trees"):
        cur = _fp_for("trees")
        fps_out["trees"] = cur
        trees_skip = client_fps.get("trees") == cur and bool(cur)
    todos_skip = False
    if use("todos"):
        cur = _fp_for("todos")
        fps_out["todos"] = cur
        todos_skip = client_fps.get("todos") == cur and bool(cur)
    agents_skip = False
    if use("agents"):
        cur = _fp_for("agents")
        fps_out["agents"] = cur
        agents_skip = client_fps.get("agents") == cur and bool(cur)
    scores_skip = False
    if use("scores"):
        cur = _fp_for("scores")
        fps_out["scores"] = cur
        scores_skip = client_fps.get("scores") == cur and bool(cur)
    holds_skip = False
    if use("holds"):
        cur = _fp_for("holds")
        fps_out["holds"] = cur
        holds_skip = client_fps.get("holds") == cur and bool(cur)
    events_skip = False
    if use("events"):
        cur = _fp_for("events")
        fps_out["events"] = cur
        events_skip = client_fps.get("events") == cur and bool(cur)
    agents = []
    if (use("agents") and not agents_skip) or (use("mail") and not mail_skip):
        agents = build_agents(cn, [p] if p else [""], want)
    if agents_skip:
        agents = []
    if not mail_ps:
        mail_ps = list({_nm(str(a.get("group_id") or "the-mill")) for a in agents} or ["the-mill"])
        # Recompute fps that depended on empty mail_ps once desks known (cold no-project rare).
        if use("mail") and "mail" in fps_out and not mail_skip:
            fps_out["mail"] = _fp_for("mail")
            mail_skip = client_fps.get("mail") == fps_out["mail"] and bool(fps_out["mail"])
        if use("trees") and "trees" in fps_out and not trees_skip:
            fps_out["trees"] = _fp_for("trees")
            trees_skip = client_fps.get("trees") == fps_out["trees"] and bool(fps_out["trees"])
    mailbox = []
    if use("mail") and not mail_skip:
        seen_mail: set[int] = set()
        pending: list[tuple[str, dict, list[dict]]] = []
        for mp, mp_rows in _mail_by_aff(cn, mail_ps):
            grouped = rec_mail.group_list_rows(mp_rows)
            for letter, dest_rows in grouped:
                mid = int(letter["id"])
                if mid in seen_mail:
                    continue
                seen_mail.add(mid)
                pending.append((mp, letter, dest_rows))
        crumbs_by = rec_mail.tree_crumbs_batch(cn, [int(letter["id"]) for _mp, letter, _d in pending])
        for mp, letter, dest_rows in pending:
            mid = int(letter["id"])
            created = iso6(letter.get("created"))
            row = rec_mail.public_mail(
                {
                    "id": mid,
                    "created": created,
                    "desk": letter.get("desk"),
                    "sender_roster": letter.get("sender_roster"),
                    "body": letter.get("body") or "",
                },
                dest_rows,
                crumbs=crumbs_by.get(mid) or None,
                lean=True,
            )
            # list_project scoped by mp; letter sender.roster is the project or role name
            if want and _nm(mp) not in want and not _keep(row, want):
                continue
            mailbox.append(row)
    needs = []
    issues = []
    if use("todos") and not todos_skip:
        for mp, mp_rows in _todo_by_aff(cn, mail_ps):
            for r in mp_rows:
                st = r.get("status") or "open"
                fields = rec_todo.unpack(r.get("body") or "", r.get("id"))
                detail, detail_trunc = lean_text(fields["detail"])
                card = {
                    "roster_id": _nm(r.get("roster")),
                    "need_id": str(r.get("id") or ""),  # need_id = card id (todo.id)
                    "id": r.get("id"),
                    "status": st,
                    "detail": detail,
                    "progress": fields["progress"],
                    "assigned": _nm(r.get("assigned")),
                    "creator": _nm(r.get("creator")),
                    "volunteer": _nm(r.get("assigned")),
                    "asker": _nm(r.get("creator")),
                }
                if detail_trunc:
                    card["detail_trunc"] = True
                if not _keep(card, want):
                    continue
                if st == "parked":
                    issues.append({**card, "title": "", "kind": "next"})
                else:
                    needs.append(card)
    events = []
    if use("events") and not events_skip:
        events = build_events(cn, mail_ps or [], want)
    locks = []
    if use("holds") and not holds_skip:
        locks = build_holds(cn, mail_ps or [], want)
    kpis = []
    if use("scores") and not scores_skip:
        kpis = build_scores(cn, mail_ps or [], want)
    desk_unread: dict[str, int] = {}
    for m in mailbox:
        tos = m.get("mail_tos") or []
        if tos:
            for t in tos:
                dst = str((t or {}).get("deskId") or (t or {}).get("desk") or "")
                if not dst or dst == "*":
                    continue
                desk_unread[dst] = desk_unread.get(dst, 0) + 1
        else:
            dst = str(m.get("dst") or "")
            if not dst or dst == "*":
                continue
            desk_unread[dst] = desk_unread.get(dst, 0) + 1
    g = _glance(agents, mailbox, needs)
    for d in g.get("desks") or []:
        d["unread"] = int(desk_unread.get(str(d.get("owner") or ""), 0) or 0)
    names = {}
    name_rows: list[dict] = []
    need_names = use("names") or ((use("trees") and not trees_skip) or use("watchers"))
    if use("names"):
        name_rows = rec_name.select(cn, include_deleted=True)
        names = {
            int(r["id"]): str(r.get("name") or "")
            for r in name_rows
            if r.get("deleted") is None
        }
    elif need_names:
        names = {int(r["id"]): str(r.get("name") or "") for r in rec_name.select(cn)}
    aff_ids = None
    if want:
        aff_ids = [i for i, nm in names.items() if nm in want or _nm(nm) in want]
    office_slug = _nm(names.get(1) or CONST_OFFICE)
    groups = sorted({a.get("group_id") or "" for a in agents if a.get("group_id")})
    todos: dict[int, dict] = {}
    for row in list(needs) + list(issues):
        try:
            todos[int(row.get("id") or 0)] = row
        except (TypeError, ValueError):
            continue
    mails: dict[int, dict] = {}
    for row in mailbox:
        try:
            mails[int(row.get("id") or 0)] = row
        except (TypeError, ValueError):
            continue
    trees = _floor_trees(cn, want, todos, mails, names, aff_ids) if (use("trees") and not trees_skip) else []
    watchers = (
        build_watchers(
            cn,
            mail_ps or [],
            want,
            todos=todos,
            mails=mails,
            names=names,
            roster_ids=aff_ids,
        )
        if use("watchers")
        else []
    )
    from agent_coord.config import mill_trust

    out = {
        "at": iso6(datetime.now()),
        "node": this_host(),
        "version": package_version(),
        # Mill trust matrix; Stations floor envelope carries the INVITE gate stamp.
        "trust": mill_trust(),
        "office": office_slug,
        "office_id": 1,
        "groups": groups,
        "locks": locks,
        "agents": agents,
        "events": events,
        "timeline": _timeline(cn, p or (mail_ps[0] if mail_ps else _nm("the-mill")), "24h") if use("timeline") else [],
        "parts": sorted(partset) if partset else [],
        "mailbox": mailbox,
        "kpis": kpis,
        "needs": needs,
        "issues": issues,
        "trees": trees,
        "watchers": watchers,
        "catalog": build_names(cn, mail_ps or [], want, name_rows=name_rows) if use("names") else [],
        "spend": [],
        "spend_lines": [],
        "desk_unread": desk_unread,
        "desk_human_required": {},
        "desk_attention": {},
        "office_glance": g,
        "live_agents": len({a.get("owner") for a in agents if a.get("owner")}),
        "live_locks": len(locks),
        "dead_holders": 0,
        "remote_holders": 0,
    }
    if fps_out:
        out["fp"] = fps_out
    # limit/cursor accepted for API signature; /api/floor pages AFTER board_view
    # (see middleware) so next matches post-TTL/fixture lists.
    del limit, cursor
    return out



def floor_scope(
    cn,
    kind: str,
    ident: str,
    parts: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """One stored call per displayed part. kind is role or lan. No row discard pass."""
    from agent_coord.server.records.db import call
    from agent_coord.helpers.ident import this_host
    from agent_coord.install.packver import package_version
    kind_s = (kind or "").strip().lower()
    ident_s = _nm((ident or "").strip())
    partset = [p.strip() for p in (parts or []) if p and str(p).strip()]
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    fps_out: dict[str, str] = {}
    agents: list[dict] = []
    mailbox: list[dict] = []
    needs: list[dict] = []
    issues: list[dict] = []
    locks: list[dict] = []
    kpis: list[dict] = []
    events: list[dict] = []
    def _skip(part: str) -> bool:
        if part not in partset:
            return False
        cur = _part_fp(cn, kind_s, ident_s, part)
        fps_out[part] = cur
        return bool(cur) and client_fps.get(part) == cur
    mail_skip = _skip("mail") if "mail" in partset else False
    trees_skip = _skip("trees") if "trees" in partset else False
    agents_skip = _skip("agents") if "agents" in partset else False
    todos_skip = _skip("todos") if "todos" in partset else False
    holds_skip = _skip("holds") if "holds" in partset else False
    scores_skip = _skip("scores") if "scores" in partset else False
    events_skip = _skip("events") if "events" in partset else False
    if "agents" in partset and not agents_skip:
        agents = call(cn, "mill_floor_part", [kind_s, ident_s, "agents"])
    if "mail" in partset and not mail_skip:
        raw_mail = call(cn, "mill_floor_part", [kind_s, ident_s, "mail"])
        seen_m: set[int] = set()
        ordered: list[dict] = []
        for r in raw_mail:
            mid = int(r.get("id") or 0)
            if not mid or mid in seen_m:
                continue
            seen_m.add(mid)
            ordered.append(r)
        # mill_floor_part mail carries every dest per letter (JSON_ARRAYAGG). Old shape
        # (one row per dest, no dests column) falls back to one batch tos_by_id.
        if all("dests" in r for r in ordered):
            dests = {int(r.get("id") or 0): rec_mail.dest_rows_json(r.get("dests")) for r in ordered}
        else:
            dests = rec_mail.tos_by_id(cn, list(seen_m))
        crumbs_by = rec_mail.tree_crumbs_batch(cn, list(seen_m))
        mailbox = []
        for r in ordered:
            mid = int(r.get("id") or 0)
            created = iso6(r.get("created") or r.get("updated") or r.get("at"))
            mailbox.append(
                rec_mail.public_mail(
                    {
                        "id": mid,
                        "created": created or r.get("created"),
                        "desk": r.get("desk") or r.get("src"),
                        "sender": r.get("sender"),
                        "sender_roster": r.get("sender_roster"),
                        "body": r.get("body") or "",
                    },
                    dests.get(mid, []),
                    crumbs=crumbs_by.get(mid) or None,
                    lean=True,
                )
            )
    if "todos" in partset and not todos_skip:
        for row in call(cn, "mill_floor_part", [kind_s, ident_s, "todos"]):
            # #818: cards have no title; a legacy stored doing heads the detail (as rec_todo.unpack).
            legacy = str(row.get("doing") or "").strip()
            raw_detail = str(row.get("detail") or "")
            if legacy and not raw_detail.startswith(legacy):
                raw_detail = legacy + ("\n" + raw_detail if raw_detail else "")
            detail, detail_trunc = lean_text(raw_detail)
            card = {
                "roster_id": row.get("roster_id") or "",
                "need_id": row.get("need_id") or "",
                "id": row.get("id"),
                "status": row.get("status") or "open",
                "detail": detail,
                "progress": row.get("progress") or "",
                "assigned": row.get("assigned") or "",
                "creator": row.get("creator") or "",
                "volunteer": row.get("assigned") or "",
                "asker": row.get("creator") or "",
            }
            if detail_trunc:
                card["detail_trunc"] = True
            if card["status"] == "parked":
                issues.append({**card, "title": "", "kind": "next"})
            else:
                needs.append(card)
    if "holds" in partset and not holds_skip:
        locks = call(cn, "mill_floor_part", [kind_s, ident_s, "holds"])
    if "scores" in partset and not scores_skip:
        kpis = call(cn, "mill_floor_part", [kind_s, ident_s, "scores"])
    if "events" in partset and not events_skip:
        events = stamp_event_state(cn, call(cn, "mill_floor_part", [kind_s, ident_s, "events"]))
    trees: list = []  # lan/role trees empty; fp still echoed when requested
    desk_unread: dict[str, int] = {}
    for m in mailbox:
        dst = str(m.get("dst") or "")
        if dst and dst != "*":
            desk_unread[dst] = desk_unread.get(dst, 0) + 1
    g = _glance(agents, mailbox, needs) if (agents or mailbox or needs) else {}
    from agent_coord.config import mill_trust

    out = {
        "at": iso6(datetime.now()),
        "node": this_host(),
        "version": package_version(),
        # Mill trust matrix; Stations floor envelope carries the INVITE gate stamp.
        "trust": mill_trust(),
        "office": "",
        "office_id": 1,
        "groups": [],
        "locks": locks,
        "agents": agents,
        "events": events,
        "timeline": [],
        "parts": sorted(set(partset)),
        "mailbox": mailbox,
        "kpis": kpis,
        "needs": needs,
        "issues": issues,
        "trees": trees,
        "watchers": [],
        "catalog": [],
        "spend": [],
        "spend_lines": [],
        "desk_unread": desk_unread,
        "desk_human_required": {},
        "desk_attention": {},
        "office_glance": g,
        "live_agents": len({a.get("owner") for a in agents if a.get("owner")}),
        "live_locks": len(locks),
        "dead_holders": 0,
        "remote_holders": 0,
    }
    if fps_out:
        out["fp"] = fps_out
    # limit/cursor accepted for API signature; /api/floor pages AFTER board_view.
    del limit, cursor
    return out


def v1_by_scope(
    cn,
    route: str,
    kind: str,
    ident: str,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """One /api/v1 part for a role or a station. Same keys as the project route.

    Agents, mail, todos, holds, scores, and events come from mill_floor_part.
    Names stay the office catalog. Rooms, trees, and watchers are empty here,
    matching the role and station floor envelope. A timeline part is empty;
    events are the activity rows for those desks.
    """
    route_s = (route or "").strip().lower()
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    if route_s == "names":
        return v1_names(cn, client_fps=client_fps, limit=limit, cursor=cursor)
    if route_s in ("rooms", "tree-mail", "tree-todo"):
        out = _v1_envelope(["rooms"] if route_s == "rooms" else ["trees"])
        out["trees"] = []
        out["next"] = None
        return out
    if route_s == "watchers":
        out = _v1_envelope(["watchers"])
        out["watchers"] = []
        out["next"] = None
        return out

    use_timeline = False
    if route_s == "map":
        part_list = ["agents", "mail"]
        envelope = ["agents", "mail"]
    elif route_s == "timeline":
        raw_parts: list[str] = []
        for raw in parts or []:
            for bit in str(raw).split(","):
                bit = bit.strip().lower()
                if bit and bit not in raw_parts:
                    raw_parts.append(bit)
        use_timeline = "timeline" in raw_parts and "events" not in raw_parts
        if use_timeline:
            part_list = ["agents"]
            envelope = ["agents", "timeline"]
        else:
            part_list = ["agents", "events"]
            envelope = ["agents", "events"]
    else:
        part_list = {
            "mailbox": ["mail"],
            "todos": ["todos"],
            "agents": ["agents"],
            "scores": ["scores"],
            "holds": ["holds"],
            "events": ["events"],
        }.get(route_s)
        if not part_list:
            raise ValueError(f"unknown v1 route {route_s}")
        envelope = list(part_list)
        if route_s == "mailbox":
            envelope = ["mail"]
        elif route_s == "scores":
            envelope = ["scores"]
        elif route_s == "holds":
            envelope = ["holds"]

    view = floor_scope(cn, kind, ident, part_list, client_fps=client_fps)
    out = _v1_envelope(envelope)
    if view.get("fp"):
        out["fp"] = view["fp"]

    def stamp_agents(rows: list[dict] | None) -> list[dict]:
        agents: list[dict] = []
        for raw in rows or []:
            row = dict(raw)
            if row.get("id") in (None, ""):
                row["id"] = row.get("owner") or row.get("pid") or ""
            agents.append(row)
        return agents

    if route_s == "agents":
        page, nxt = page_by_cursor(stamp_agents(view.get("agents")), page_lim, page_cur)
        out["agents"] = page
        out["next"] = nxt
        return out
    if route_s == "mailbox":
        page, nxt = page_by_cursor(list(view.get("mailbox") or []), page_lim, page_cur)
        out["mailbox"] = page
        out["desk_unread"] = view.get("desk_unread") or {}
        out["next"] = nxt
        return out
    if route_s == "todos":
        needs = list(view.get("needs") or [])
        issues = list(view.get("issues") or [])
        need_ids = {int(c.get("id") or 0) for c in needs}
        page, nxt = page_by_cursor(needs + issues, page_lim, page_cur)
        out["needs"] = [c for c in page if int(c.get("id") or 0) in need_ids]
        out["issues"] = [c for c in page if int(c.get("id") or 0) not in need_ids]
        out["next"] = nxt
        return out
    if route_s == "scores":
        rows = []
        for raw in view.get("kpis") or []:
            item = dict(raw)
            if item.get("id") in (None, ""):
                item["id"] = "|".join(
                    str(item.get(k) or "") for k in ("owner", "kpi", "roster_id")
                )
            rows.append(item)
        page, nxt = page_by_cursor(rows, page_lim, page_cur)
        out["kpis"] = page
        out["next"] = nxt
        return out
    if route_s == "holds":
        rows = []
        for raw in view.get("locks") or []:
            item = dict(raw)
            if item.get("id") in (None, ""):
                item["id"] = "|".join(
                    str(item.get(k) or "") for k in ("resource", "owner", "roster_id")
                )
            rows.append(item)
        page, nxt = page_by_cursor(rows, page_lim, page_cur)
        out["locks"] = page
        out["next"] = nxt
        return out
    if route_s == "events":
        page, nxt = page_by_cursor(
            list(view.get("events") or []), page_lim, page_cur, get_key=_events_cursor_key
        )
        out["events"] = page
        out["next"] = nxt
        return out
    if route_s == "map":
        out["agents"] = stamp_agents(view.get("agents"))
        out["mailbox"] = list(view.get("mailbox") or [])
        out["desk_unread"] = view.get("desk_unread") or {}
        apply_floor_list_page(
            out, limit=page_lim, cursor=page_cur, partset={"agents", "mail"}
        )
        return out
    out["agents"] = stamp_agents(view.get("agents"))
    if use_timeline:
        out["timeline"] = []
        apply_floor_list_page(out, limit=page_lim, cursor=page_cur, partset={"agents"})
        return out
    out["events"] = list(view.get("events") or [])
    apply_floor_list_page(
        out, limit=page_lim, cursor=page_cur, partset={"agents", "events"}
    )
    return out





def _by_aff(pairs: list[tuple[str, dict]]) -> list[tuple[str, list[dict]]]:
    """[(name, row), ...] -> [(name, [rows])] keeping first-seen name order."""
    out: list[tuple[str, list[dict]]] = []
    idx: dict[str, int] = {}
    for name, row in pairs:
        if name not in idx:
            idx[name] = len(out)
            out.append((name, []))
        out[idx[name]][1].append(row)
    return out


def _aff_names(names: list[str] | None) -> list[str]:
    """Drop blank names (no per-name fallback read); input order kept."""
    return [n for n in (names or []) if str(n or "").strip()]


def _mail_by_aff(cn, names: list[str]) -> list[tuple[str, list[dict]]]:
    """Mail letters per roster: blanks dropped, ids resolved once, one IN (...) read."""
    names = _aff_names(names)
    if not names:
        return []
    return _by_aff(rec_mail.list_rosters(cn, names))


def _todo_by_aff(cn, names: list[str]) -> list[tuple[str, list[dict]]]:
    """Todo cards per roster: blanks dropped, one IN (...) read."""
    names = _aff_names(names)
    if not names:
        return []
    return _by_aff(rec_todo.select_rosters(cn, names))


def _score_by_aff(cn, names: list[str]) -> list[tuple[str, list[dict]]]:
    """Score rows per roster: blanks dropped, one IN (...) read."""
    names = _aff_names(names)
    if not names:
        return []
    return _by_aff(rec_score.select_rosters(cn, names))

def _v1_project_scope(
    project: str | None = None,
    projects: list[str] | None = None,
) -> tuple[list[str], set[str] | None]:
    """Resolve project= / projects= into stored project names and a want set."""
    want: set[str] | None = None
    raws: list[str] = []
    if projects:
        raws = [str(x).strip() for x in projects if str(x).strip()]
    elif project:
        raws = [x.strip() for x in str(project).split(",") if x.strip()]
    if raws:
        want = set()
        for r in raws:
            want.add(_nm(_nm(r)))
            want.add(str(r).strip())
    mail_ps: list[str] = []
    for r in raws:
        slug = _nm(r)
        if slug not in mail_ps:
            mail_ps.append(slug)
    return mail_ps, want


def _v1_envelope(parts: list[str]) -> dict[str, Any]:
    from agent_coord.helpers.ident import this_host
    from agent_coord.install.packver import package_version
    from agent_coord.config import mill_trust

    return {
        "at": iso6(datetime.now()),
        "node": this_host(),
        "version": package_version(),
        "parts": list(parts),
        # Wall browse vs agent commands trust matrix (Host GO). Roles only.
        "trust": mill_trust(),
    }


def _v1_aff_ids(cn, want: set[str] | None) -> list[int] | None:
    if not want:
        return None
    names = {int(r["id"]): str(r.get("name") or "") for r in rec_name.select(cn)}
    return [i for i, nm in names.items() if nm in want or _nm(nm) in want]


def build_mailbox(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Mailbox isolate: mill_mail_list JOIN dests grouped + one batch tree_crumbs."""
    mailbox: list[dict] = []
    seen_mail: set[int] = set()
    pending: list[tuple[str, dict, list[dict]]] = []
    for mp, mp_rows in _mail_by_aff(cn, mail_ps):
        grouped = rec_mail.group_list_rows(mp_rows)
        for letter, dest_rows in grouped:
            mid = int(letter["id"])
            if mid in seen_mail:
                continue
            seen_mail.add(mid)
            pending.append((mp, letter, dest_rows))
    crumbs_by = rec_mail.tree_crumbs_batch(cn, [int(letter["id"]) for _mp, letter, _d in pending])
    for mp, letter, dest_rows in pending:
        mid = int(letter["id"])
        created = iso6(letter.get("created"))
        row = rec_mail.public_mail(
            {
                "id": mid,
                "created": created,
                "desk": letter.get("desk"),
                "sender_roster": letter.get("sender_roster"),
                "body": letter.get("body") or "",
            },
            dest_rows,
            crumbs=crumbs_by.get(mid) or None,
            lean=True,
        )
        if want and _nm(mp) not in want and not _keep(row, want):
            continue
        mailbox.append(row)
    desk_unread: dict[str, int] = {}
    for m in mailbox:
        tos = m.get("mail_tos") or []
        if tos:
            for t in tos:
                dst = str((t or {}).get("deskId") or (t or {}).get("desk") or "")
                if not dst or dst == "*":
                    continue
                desk_unread[dst] = desk_unread.get(dst, 0) + 1
        else:
            dst = str(m.get("dst") or "")
            if not dst or dst == "*":
                continue
            desk_unread[dst] = desk_unread.get(dst, 0) + 1
    return mailbox, desk_unread


def build_todos(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
    *,
    lean: bool = True,
) -> tuple[list[dict], list[dict]]:
    """Todos isolate: mill_todo_select -> needs + issues.
    lean=True (list/poll): truncate detail to LIST_TEXT_MAX; set detail_trunc when
    clipped (omit the flag when full). #818: cards carry no doing key.
    """
    needs: list[dict] = []
    issues: list[dict] = []
    for mp, mp_rows in _todo_by_aff(cn, mail_ps):
        for r in mp_rows:
            st = r.get("status") or "open"
            fields = rec_todo.unpack(r.get("body") or "", r.get("id"))
            detail = fields["detail"]
            detail_trunc = False
            if lean:
                detail, detail_trunc = lean_text(detail)
            card = {
                "roster_id": _nm(r.get("roster")),
                "need_id": str(r.get("id") or ""),  # need_id = card id (todo.id)
                "id": r.get("id"),
                "status": st,
                "detail": detail,
                "progress": fields["progress"],
                "assigned": _nm(r.get("assigned")),
                "creator": _nm(r.get("creator")),
                "volunteer": _nm(r.get("assigned")),
                "asker": _nm(r.get("creator")),
            }
            if detail_trunc:
                card["detail_trunc"] = True
            if not _keep(card, want):
                continue
            if st == "parked":
                issues.append({**card, "title": "", "kind": "next"})
            else:
                needs.append(card)
    return needs, issues


def build_trees_typed(
    cn,
    want: set[str] | None,
    type_filter: str,
    roster_ids: list[int] | None = None,
) -> list[dict]:
    """Full slice of glance trees for one activity type (mail|todo). Not progressive."""
    typ = (type_filter or "").strip().lower()
    names = {int(r["id"]): str(r.get("name") or "") for r in rec_name.select(cn)}
    whole = typ in ("mail", "todo")
    if typ == "mail":
        raw_rows = rec_tree.mail_forest_rows(cn, roster_ids)
    elif typ == "todo":
        raw_rows = rec_tree.todo_forest_rows(cn, roster_ids)
    else:
        raw_rows = None
    trees = _floor_trees(
        cn,
        want,
        {},
        {},
        names,
        roster_ids,
        rows=raw_rows,
        keep_all_nodes=whole,
    )
    out: list[dict] = []
    for tree in trees:
        nodes = [n for n in (tree.get("nodes") or []) if str(n.get("type") or "") == typ]
        if not nodes:
            continue
        for node in nodes:
            lft = int(node.get("lft") or 0)
            rgt = int(node.get("rgt") or 0)
            node["depth"] = sum(
                1
                for other in nodes
                if int(other.get("lft") or 0) < lft and int(other.get("rgt") or 0) > rgt
            )
            node["has_children"] = any(
                other is not node
                and int(other.get("lft") or 0) > lft
                and int(other.get("rgt") or 0) < rgt
                for other in nodes
            )
        out.append({**tree, "nodes": nodes})
    return out







def build_names(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
    *,
    name_rows: list[dict] | None = None,
) -> list[dict]:
    """Names (glossary) isolate: catalog from name table (include deleted)."""
    del mail_ps, want  # office-global catalog; floor does not filter by project
    rows = name_rows if name_rows is not None else rec_name.select(cn, include_deleted=True)
    return _name_catalog(rows)


SCOPE_EVENTS_LIMIT = 120  # mill_floor_part events LIMIT (sp_floor_scope.sql)


def stamp_event_state(cn, events: list[dict] | None) -> list[dict]:
    """Role and station events come from mill_floor_part, which has no state column.

    Stamp each row with the state mill_activity_select gives (#91/#92): deleted
    (any type), sent (live letter), or None. One office-wide read covers the
    usual case. A row older than that read is looked up per desk, and a desk's
    own newest SCOPE_EVENTS_LIMIT rows always hold every row of that desk the
    scope read could return.
    """
    rows = [dict(r) for r in events or []]
    if not rows:
        return rows

    def key(typ: Any, ident: Any) -> tuple[str, str]:
        return (str(typ or ""), str(ident if ident is not None else ""))

    def row_key(r: dict) -> tuple[str, str]:
        return key(r.get("type") or r.get("kind"), r.get("id"))

    state: dict[tuple[str, str], Any] = {}
    for a in rec_activity.select(cn, 0, LIST_PAGE_MAX):
        state[key(a.get("type"), a.get("id"))] = a.get("state")
    missing = {
        (_nm(r.get("owner")), str(r.get("owner_type") or ""))
        for r in rows
        if row_key(r) not in state and _nm(r.get("owner"))
    }
    if missing:
        names = {_nm(o) for o, _t in missing}
        desk_ids: set[int] = set()
        for n in rec_name.select(cn, include_deleted=True):
            nm = _nm(n.get("name"))
            if nm not in names:
                continue
            typ = str(n.get("type") or "")
            if (nm, typ) in missing or (nm, "") in missing:
                desk_ids.add(int(n["id"]))
        for did in sorted(desk_ids):
            for a in rec_activity.select(cn, did, SCOPE_EVENTS_LIMIT):
                state.setdefault(key(a.get("type"), a.get("id")), a.get("state"))
    for r in rows:
        r["state"] = state.get(row_key(r))
    return rows


def build_events(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
) -> list[dict]:
    """Events isolate: mill_activity_select (LIST_PAGE_MAX) + want filter."""
    del mail_ps  # scope via want (activity is global select then _keep)
    events: list[dict] = []
    for r in rec_activity.select(cn, 0, LIST_PAGE_MAX):
        proj_s = _nm(r.get("roster"))
        ev = {
            "id": r.get("id"),
            "kind": r.get("type"),
            "type": r.get("type"),
            "at": iso6(r.get("updated") or r.get("lastUpdate")),
            "owner": _nm(r.get("desk")),
            "roster_id": proj_s,
            "desk_id": r.get("desk_id"),
            "weight": r.get("weight"),
            "n": r.get("n"),
            "state": r.get("state"),
        }
        if _keep(ev, want):
            events.append(ev)
    return events


def build_holds(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
) -> list[dict]:
    """Currently held locks. One row per resource, not per project. Free rows stay out."""
    del mail_ps, want
    locks: list[dict] = []
    for r in rec_hold.find(cn, held=True):
        if r.get("desk_id") is None:
            continue
        locks.append(
            {
                "id": r.get("id"),
                "roster_id": _nm(r.get("roster")),
                "resource": _nm(r.get("resource")),
                "owner": _nm(r.get("desk")),
                "holder_dead": False,
            }
        )
    return locks


def build_scores(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
) -> list[dict]:
    """Scores isolate: mill_score_select per project and Office; dedupe owner|kpi|aff."""
    kpis: list[dict] = []
    from agent_coord.server.admin.guard import office_name

    score_ps = list(dict.fromkeys([*(mail_ps or []), office_name(cn)]))  # #722: id 1's name
    seen_kpi: set[tuple] = set()
    for mp, mp_rows in _score_by_aff(cn, score_ps):
        for r in mp_rows:
            aff = _nm(r.get("roster"))
            row = {
                "id": r.get("id"),
                "roster_id": aff,
                "project_id": aff,
                "kpi": _nm(r.get("kpi")),
                "value": r.get("value") or "",
                "target": r.get("target") or "",
                "note": r.get("note") or "",
                "owner": _nm(r.get("desk")),
            }
            key = (row["owner"], row["kpi"], aff)
            if key in seen_kpi:
                continue
            office = aff in (CONST_OFFICE,) or int(_gid(r) or 0) == 1
            if office or _keep(row, want):
                seen_kpi.add(key)
                kpis.append(row)
    return kpis


def build_agents(
    cn,
    mail_ps: list[str],
    want: set[str] | None = None,
) -> list[dict]:
    """Agents for each project: mill_join_select, skipping a join row with no token_hash."""
    from agent_coord.lib.observe import heartbeat_flags

    agents: list[dict] = []
    seen: set[Any] = set()
    scopes = list(mail_ps) if mail_ps else [""]
    for mp in scopes:
        for r in rec_join.select(cn, mp):
            # A join row with no token_hash is not a live seat.
            if not str(r.get("token_hash") or "").strip():
                continue
            rid = r.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            pid_s = _nm(mp) if mp else _nm(r.get("roster"))
            hb = r.get("updated") or r.get("lastUpdated")
            alive, stale = heartbeat_flags(hb)
            row = {
                "id": rid,
                "roster_id": pid_s,
                "owner": _nm(r.get("desk")),
                "pid": r.get("pid") or rid,
                "role": "",
                "alive": alive,
                "stale": stale,
                "heartbeat": iso6(hb),
                "doing": r.get("doing") or "",
                "waiting_on": "",
                "root": "",
            }
            lan = str(r.get("lan_ip") or "").strip()
            if lan:
                row["lan_ip"] = lan
            if mp or _keep(row, want):
                agents.append(row)
    return agents


def build_rooms(
    cn,
    want: set[str] | None = None,
    roster_ids: list[int] | None = None,
) -> list[dict]:
    """Lean mail room roots only (type=mail lft=1). No letter bodies.

    Every room, at every trust level (#672, S-3): nothing is private between
    desks in an office, and the Wall shows humans every room.
    """

    aff = roster_ids
    if aff is None and want:
        aff = _v1_aff_ids(cn, want)
    names = {int(r["id"]): str(r.get("name") or "") for r in rec_name.select(cn)}
    rows = rec_tree.mail_room_root_rows(cn, aff)
    enriched: list[dict] = []
    for raw in rows:
        rid = int(raw.get("id") or 0)
        try:
            aff_id = int(raw.get("roster_id") or 0)
        except (TypeError, ValueError):
            aff_id = 0
        aff_s = _nm(str(names.get(aff_id) or ""))
        enriched.append(
            {
                "tree": str(raw.get("tree") or ""),
                "type": "mail",
                "id": rid,
                "lft": int(raw.get("lft") or 0),
                "rgt": int(raw.get("rgt") or 0),
                "roster_id": aff_s,
                "title": "",
                "status": "mail",
                "who": "",
            }
        )
    return rec_tree.pack_trees(enriched)


def v1_rooms(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    *,
    desk: str | None = None,
    scope: str | None = None,
) -> dict[str, Any]:
    """Rooms isolate. Stamp trust. Every room at every trust level (#672, S-3).

    ?desk= and ?scope=membership are still accepted (older Wall glass sends them
    under limited trust) but no longer filter: nothing is private between desks
    in an office, and the Wall shows humans every room.
    """
    _mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["rooms"])
    out["trees"] = build_rooms(cn, want)
    if desk:
        out["desk"] = desk
    return out


def v1_mailbox(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Mailbox isolate. ?fp=mail:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    Pages in Python after mill_mail_list (SP LIMIT 500). desk_unread from full set.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["mail"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    mail_fp = _projects_part_fp(cn, mail_ps, "mail") if mail_ps else ""
    if mail_fp:
        out["fp"] = {"mail": mail_fp}
    if mail_fp and client_fps.get("mail") == mail_fp:
        out["mailbox"] = []
        out["desk_unread"] = {}
        out["next"] = None
        return out
    mailbox, desk_unread = build_mailbox(cn, mail_ps, want)
    page, nxt = page_by_cursor(mailbox, page_lim, page_cur)
    out["mailbox"] = page
    out["desk_unread"] = desk_unread
    out["next"] = nxt
    return out


def v1_tree_mail(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    depth: int | None = None,
    parent_id: str | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Mail trees progressive + optional ?window=1d|1w|30d (omit=All)."""
    _mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["trees"])
    aff = _v1_aff_ids(cn, want)
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    depth_cap = parse_tree_depth(depth=depth)
    pid = parse_tree_parent_id(parent_id=parent_id)
    since = parse_tree_window(window=window)
    full = build_trees_typed(cn, want, "mail", aff)
    if since is not None:
        last = rec_tree.forest_last_activity(cn, aff)
        full = filter_trees_by_window(full, since, last)
    trees, nxt = page_trees_progressive(
        full, page_lim, page_cur, depth=depth_cap, parent_id=pid
    )
    out["trees"] = trees
    out["next"] = nxt
    return out


def v1_tree_todo(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    depth: int | None = None,
    parent_id: str | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Todo trees progressive + optional ?window=1d|1w|30d (omit=All)."""
    _mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["trees"])
    aff = _v1_aff_ids(cn, want)
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    depth_cap = parse_tree_depth(depth=depth)
    pid = parse_tree_parent_id(parent_id=parent_id)
    since = parse_tree_window(window=window)
    full = build_trees_typed(cn, want, "todo", aff)
    if since is not None:
        last = rec_tree.forest_last_activity(cn, aff)
        full = filter_trees_by_window(full, since, last)
    trees, nxt = page_trees_progressive(
        full, page_lim, page_cur, depth=depth_cap, parent_id=pid
    )
    out["trees"] = trees
    out["next"] = nxt
    return out


def v1_todos(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Todos isolate. ?fp=todos:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    Stream order: needs then issues; page split back into those keys.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["todos"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    todos_fp = _projects_part_fp(cn, mail_ps, "todos") if mail_ps else ""
    if todos_fp:
        out["fp"] = {"todos": todos_fp}
    if todos_fp and client_fps.get("todos") == todos_fp:
        out["needs"] = []
        out["issues"] = []
        out["next"] = None
        return out
    needs, issues = build_todos(cn, mail_ps, want)
    need_ids = {int(c.get("id") or 0) for c in needs}
    stream = list(needs) + list(issues)
    page, nxt = page_by_cursor(stream, page_lim, page_cur)
    out["needs"] = [c for c in page if int(c.get("id") or 0) in need_ids]
    out["issues"] = [c for c in page if int(c.get("id") or 0) not in need_ids]
    out["next"] = nxt
    return out





def v1_agents(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Agents isolate. ?fp=agents:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["agents"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    agents_fp = _projects_part_fp(cn, mail_ps, "agents") if mail_ps else ""
    if agents_fp:
        out["fp"] = {"agents": agents_fp}
    if agents_fp and client_fps.get("agents") == agents_fp:
        out["agents"] = []
        out["next"] = None
        return out
    agents = build_agents(cn, mail_ps, want)
    for a in agents:
        if a.get("id") in (None, ""):
            a["id"] = a.get("owner") or a.get("pid") or ""
    page, nxt = page_by_cursor(agents, page_lim, page_cur)
    out["agents"] = page
    out["next"] = nxt
    return out



def v1_scores(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Scores isolate. ?fp=scores:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["scores"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    scores_fp = _projects_part_fp(cn, mail_ps, "scores") if mail_ps else ""
    if scores_fp:
        out["fp"] = {"scores": scores_fp}
    if scores_fp and client_fps.get("scores") == scores_fp:
        out["kpis"] = []
        out["next"] = None
        return out
    kpis = build_scores(cn, mail_ps, want)
    for row in kpis:
        if row.get("id") in (None, ""):
            row["id"] = "|".join(
                str(row.get(k) or "") for k in ("owner", "kpi", "roster_id")
            )
    page, nxt = page_by_cursor(kpis, page_lim, page_cur)
    out["kpis"] = page
    out["next"] = nxt
    return out



def v1_holds(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Holds isolate. ?fp=holds:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["holds"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    holds_fp = _projects_part_fp(cn, mail_ps, "holds") if mail_ps else ""
    if holds_fp:
        out["fp"] = {"holds": holds_fp}
    if holds_fp and client_fps.get("holds") == holds_fp:
        out["locks"] = []
        out["next"] = None
        return out
    locks = build_holds(cn, mail_ps, want)
    for row in locks:
        if row.get("id") in (None, ""):
            row["id"] = "|".join(
                str(row.get(k) or "") for k in ("resource", "owner", "roster_id")
            )
    page, nxt = page_by_cursor(locks, page_lim, page_cur)
    out["locks"] = page
    out["next"] = nxt
    return out



def v1_watchers(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Watchers isolate. ?fp=watchers:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    Cursor key is type:id (same as floor list page for watchers).
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["watchers"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    watchers_fp = _projects_part_fp(cn, mail_ps, "watchers") if mail_ps else ""
    if watchers_fp:
        out["fp"] = {"watchers": watchers_fp}
    if watchers_fp and client_fps.get("watchers") == watchers_fp:
        out["watchers"] = []
        out["next"] = None
        return out
    rows = build_watchers(cn, mail_ps, want)
    page, nxt = page_by_cursor(rows, page_lim, page_cur, get_key=_events_cursor_key)
    out["watchers"] = page
    out["next"] = nxt
    return out




def v1_events(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Events isolate. ?fp=events:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    Cursor key is type:id (same as floor list page for events).
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["events"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    events_fp = _projects_part_fp(cn, mail_ps, "events") if mail_ps else ""
    if events_fp:
        out["fp"] = {"events": events_fp}
    if events_fp and client_fps.get("events") == events_fp:
        out["events"] = []
        out["next"] = None
        return out
    rows = build_events(cn, mail_ps, want)
    page, nxt = page_by_cursor(rows, page_lim, page_cur, get_key=_events_cursor_key)
    out["events"] = page
    out["next"] = nxt
    return out



def v1_names(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Names (glossary) isolate. ?fp=names:hex empty-on-match (body skip; fp echoed).
    Lean list page: ?limit= (default 50) + ?cursor=; response next cursor or null.
    Payload key catalog (same as floor parts=names). Cursor key is kind:name.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["names"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    names_fp = _projects_part_fp(cn, mail_ps, "names") if mail_ps else ""
    if names_fp:
        out["fp"] = {"names": names_fp}
    if names_fp and client_fps.get("names") == names_fp:
        out["catalog"] = []
        out["next"] = None
        return out
    rows = build_names(cn, mail_ps, want)
    page, nxt = page_by_cursor(rows, page_lim, page_cur, get_key=_names_cursor_key)
    out["catalog"] = page
    out["next"] = nxt
    return out



def v1_map(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Joined FLOOR Map isolate: agents + mail (mailbox).

    Same keys as GET /api/floor?parts=agents,mail so wall Map paint can drop in.
    Per-part ?fp= empty-on-match; ?limit=/?cursor= via apply_floor_list_page
    (primary pageable part = mail).
    """
    del parts  # locked agents,mail
    mail_ps, want = _v1_project_scope(project, projects)
    out = _v1_envelope(["agents", "mail"])
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    fps_out: dict[str, str] = {}
    agents_skip = mail_skip = False
    if mail_ps:
        agents_fp = _projects_part_fp(cn, mail_ps, "agents")
        if agents_fp:
            fps_out["agents"] = agents_fp
            agents_skip = client_fps.get("agents") == agents_fp
        mail_fp = _projects_part_fp(cn, mail_ps, "mail")
        if mail_fp:
            fps_out["mail"] = mail_fp
            mail_skip = client_fps.get("mail") == mail_fp
    if fps_out:
        out["fp"] = fps_out
    agents: list[dict] = []
    if not agents_skip:
        agents = build_agents(cn, mail_ps, want)
        for a in agents:
            if a.get("id") in (None, ""):
                a["id"] = a.get("owner") or a.get("pid") or ""
    mailbox: list[dict] = []
    desk_unread: dict[str, int] = {}
    if not mail_skip:
        mailbox, desk_unread = build_mailbox(cn, mail_ps, want)
    out["agents"] = agents
    out["mailbox"] = mailbox
    out["desk_unread"] = desk_unread
    apply_floor_list_page(
        out, limit=page_lim, cursor=page_cur, partset={"agents", "mail"}
    )
    return out


def v1_timeline(
    cn,
    project: str | None = None,
    projects: list[str] | None = None,
    client_fps: dict[str, str] | None = None,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Joined FLOOR Timeline isolate: agents + events|timeline.

    Default parts=agents,events (LAN style). Pass parts=agents,timeline (or
    parts=timeline) for project-style activity buckets. Same keys as
    /api/floor?parts=agents,events|agents,timeline. Per-part ?fp= for agents
    and events (timeline has no mill_fp). ?limit=/?cursor= on pageable lists.
    """
    mail_ps, want = _v1_project_scope(project, projects)
    raw_parts: list[str] = []
    for raw in parts or []:
        for x in str(raw).split(","):
            x = x.strip().lower()
            if x and x not in raw_parts:
                raw_parts.append(x)
    use_timeline = "timeline" in raw_parts and "events" not in raw_parts
    if use_timeline:
        part_names = ["agents", "timeline"]
    else:
        part_names = ["agents", "events"]
    out = _v1_envelope(part_names)
    page_lim, page_cur = parse_list_page(limit=limit, cursor=cursor)
    client_fps = {str(k).lower(): str(v).lower() for k, v in (client_fps or {}).items() if k and v}
    fps_out: dict[str, str] = {}
    agents_skip = events_skip = False
    if mail_ps:
        agents_fp = _projects_part_fp(cn, mail_ps, "agents")
        if agents_fp:
            fps_out["agents"] = agents_fp
            agents_skip = client_fps.get("agents") == agents_fp
        if not use_timeline:
            events_fp = _projects_part_fp(cn, mail_ps, "events")
            if events_fp:
                fps_out["events"] = events_fp
                events_skip = client_fps.get("events") == events_fp
    if fps_out:
        out["fp"] = fps_out
    agents: list[dict] = []
    if not agents_skip:
        agents = build_agents(cn, mail_ps, want)
        for a in agents:
            if a.get("id") in (None, ""):
                a["id"] = a.get("owner") or a.get("pid") or ""
    out["agents"] = agents
    if use_timeline:
        proj_slug = mail_ps[0] if mail_ps else _nm("the-mill")
        # timeline has no mill_fp; always build (activity buckets)
        out["timeline"] = _timeline(cn, proj_slug, "24h")
        # page agents (cursor primary) + clamp timeline to first page
        apply_floor_list_page(
            out, limit=page_lim, cursor=page_cur, partset={"agents"}
        )
        tl_page, _tl_nxt = page_activity_rows(
            list(out.get("timeline") or []), limit=page_lim, cursor=None
        )
        out["timeline"] = tl_page
    else:
        events: list[dict] = []
        if not events_skip:
            events = build_events(cn, mail_ps, want)
        out["events"] = events
        apply_floor_list_page(
            out, limit=page_lim, cursor=page_cur, partset={"agents", "events"}
        )
    return out


def v1_mail(cn, mail_id: int) -> dict[str, Any]:
    """GET /api/v1/mail/{id} - one letter full body (open/detail; not list lean)."""
    mid = int(mail_id)
    out = _v1_envelope(["mail"])
    letter = rec_mail.letter_row(cn, mid)
    if not letter:
        rows = rec_mail.get(cn, mid)
        if not rows:
            out["error"] = "mail not found"
            out["mail"] = None
            return out
        letter = rows[0]
    dest_rows = rec_mail.to_list(cn, mid)
    crumbs = rec_mail.tree_crumbs(cn, mid)
    created = iso6(letter.get("created") or letter.get("updated"))
    out["mail"] = rec_mail.public_mail(
        {
            "id": mid,
            "created": created or letter.get("created"),
            "desk": letter.get("desk"),
            "sender_roster": letter.get("sender_roster"),
            "body": letter.get("body") or "",
        },
        dest_rows,
        crumbs=crumbs or None,
        lean=False,
    )
    return out


def v1_todo(cn, todo_id: int) -> dict[str, Any]:
    """GET /api/v1/todo/{id} - one card full detail (open/detail; not list lean)."""
    tid = int(todo_id)
    out = _v1_envelope(["todos"])
    rows = rec_todo.get(cn, tid)
    if not rows:
        out["error"] = "todo not found"
        out["todo"] = None
        return out
    r = rows[0]
    st = r.get("status") or "open"
    fields = rec_todo.unpack(r.get("body") or "", r.get("id"))
    out["todo"] = {
        "roster_id": _nm(r.get("roster")),
        "need_id": str(r.get("id") or ""),  # need_id = card id (todo.id)
        "id": r.get("id"),
        "status": st,
        "detail": fields["detail"],
        "progress": fields["progress"],
        "assigned": _nm(r.get("assigned")),
        "creator": _nm(r.get("creator")),
        "volunteer": _nm(r.get("assigned")),
        "asker": _nm(r.get("creator")),
    }
    return out


def office_glance(
    cn, project_id: str | None = None, *, window: str = "24h"
) -> dict[str, Any]:
    """GET /api/office-glance - slice of floor, not leftover Coord."""
    w = (window or "24h").strip().lower()
    if w not in ("1h", "24h", "7d"):
        w = "24h"
    plist = []
    if project_id:
        plist = [x.strip() for x in str(project_id).split(",") if x.strip()]
    f = floor(
        cn,
        None if len(plist) != 1 else plist[0],
        projects=plist or None,
    )
    g = f.get("office_glance") or {}
    g["window"] = w
    g["desk_unread"] = f.get("desk_unread") or {}
    g["projects"] = f.get("projects") or plist
    return g
