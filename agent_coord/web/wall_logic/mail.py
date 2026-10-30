"""Mail LIST/GRAPH pure rules - SoR for acceptance-locked behavior (pack-callable).

SoR: `agent_coord.web.wall_logic.mail` (this module) is the **single source of truth** for
mail pure decision rules used by the default Wall pack:

- desk-only / bare-human mailbox strip (ACCEPTANCE-MAIL-DESK-ONLY)
- LIST dst filter (ACCEPTANCE-MAIL-LIST-DST-FILTER)
- LIST Needs-attention autoselect / attention snap (MAIL_LIST_AUTOSELECT_DST)
- agent-unread + open human_required = Needs attention (ACCEPTANCE-MAIL-ATTENTION-DEFAULT,
  ACCEPTANCE-MAIL-HUMAN-REQUIRED, ACCEPTANCE-MAIL-DUAL-READ)
- GRAPH dst+src scoping (ACCEPTANCE-MAIL-DST-SRC-BROWSER) - no auto-pick src
- lean MAIL adapters (sender + mail_tos + receipt; no opened on cast) - Loop-3 Wall rooms

Default pack paint still lives in `agent_coord/wall_ui/default/board.html` (and
`static/board.html` sync). **board.html must call-equivalent** these helpers
(same semantics; names often camelCase mirrors). Do not fork filter/autoselect/
desk-only rules in chrome without updating this module + `tests/wall`.

See wall-contract; tests/wall mail suites.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from agent_coord.const import (
    CONST_ALIAS_FILE,
    CONST_ALIAS_PROJ,
    CONST_ALIAS_RESOURCE,
    CONST_MAIL,
    CONST_ROSTER,
    CONST_RES,
)

# Not a desk id - human badge / dead-letter must not appear as mailbox chrome.
BARE_HUMAN_MAILBOXES = frozenset({"setter-upper", "human", "dead-letter"})

# Marker for board.html / pack authors (searchable).
BOARD_EQUIVALENT_MARKER = "WALL_LOGIC_MAIL_SOR"


def _name_type(value: Any) -> str:
    """name.type from a name object. Call aliases fold to the stored word."""
    if not isinstance(value, Mapping):
        return ""
    kind = str(value.get("type") or "").strip().lower()
    if kind == CONST_ALIAS_PROJ:
        kind = CONST_ROSTER
    elif kind in (CONST_ALIAS_FILE, CONST_ALIAS_RESOURCE):
        kind = CONST_RES
    if kind:
        return kind
    inner = value.get("deskId")
    if inner in (None, ""):
        inner = value.get("desk")
    if isinstance(inner, Mapping):
        return _name_type(inner)
    return ""


def _name_text(value: Any) -> str:
    """Stored name. A name object is {type, name}. The type is not a prefix."""
    if isinstance(value, Mapping):
        if value.get("name") not in (None, ""):
            return str(value.get("name")).strip()
        if value.get("str") not in (None, ""):
            return str(value.get("str")).strip()
        inner = value.get("deskId")
        if inner in (None, ""):
            inner = value.get("desk")
        if inner not in (None, ""):
            return _name_text(inner)
        return ""
    return str(value or "").strip()


def _same_name(a: Any, b: Any) -> bool:
    """Same stored name. When both sides carry a type, the types agree."""
    left = _name_text(a)
    right = _name_text(b)
    if not left or left != right:
        return False
    left_type = _name_type(a)
    right_type = _name_type(b)
    if left_type and right_type and left_type != right_type:
        return False
    return True


def mail_is_lean(m: Mapping[str, Any] | None) -> bool:
    """True when row carries lean public MAIL (sender / mail_tos)."""
    if not m:
        return False
    return ("mail_tos" in m) or isinstance(m.get("sender"), dict)


def mail_sender_desk(m: Mapping[str, Any] | None) -> str:
    """Sender deskId from lean sender{} or legacy src."""
    if not m:
        return ""
    sender = m.get("sender")
    if isinstance(sender, dict):
        if sender.get("deskId") not in (None, ""):
            return _name_text(sender.get("deskId"))
        if sender.get("desk") not in (None, ""):
            return _name_text(sender.get("desk"))
        return _name_text(sender)
    if sender not in (None, ""):
        return _name_text(sender)
    return _name_text(m.get("src") or m.get("desk") or "")


def mail_tos(m: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Lean mail_tos[{deskId, roster, receipt}] or synthesize from legacy dst."""
    if not m:
        return []
    raw = m.get("mail_tos")
    if isinstance(raw, list) and raw:
        out: list[dict[str, Any]] = []
        for t in raw:
            if not isinstance(t, Mapping):
                continue
            desk = _name_text(t.get("deskId") if t.get("deskId") not in (None, "") else t.get("desk"))
            if not desk:
                continue
            out.append(
                {
                    "deskId": desk,
                    "roster": t.get("roster") if t.get("roster") not in ("", None) else None,
                    "receipt": int(t.get("receipt") or 0),
                }
            )
        return out
    raw_dst = m.get("dst")
    if isinstance(raw_dst, str) and "," in raw_dst:
        out = []
        for part in raw_dst.split(","):
            d = part.strip()
            if d:
                out.append({"deskId": d, "roster": None, "receipt": 0})
        return out
    dst = _name_text(raw_dst)
    if not dst or dst == "*":
        return []
    return [{"deskId": dst, "roster": None, "receipt": 0}]


def mail_tree_root(nodes: Sequence[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """MAIL room root for one floor.trees[] entry (one forest / name_id).

    Builder Rooms root query lock (exact SQL, no GROUP BY)::

        SELECT name_id, type, id, lft, rgt
        FROM tree
        WHERE type = 'mail' AND lft = 1
        ORDER BY name_id;

    Root per forest is lft=1 (mill_tree_create). type='mail' for MAIL rooms only.
    Optional: JOIN name n ON n.id = tree.name_id for the plan name.
    Index: KEY idx_type_lft (type, lft) - added specifically to drop GROUP BY.

    Client-side (floor.trees): keep trees whose root node is type=mail and lft=1.
    Nest / crumbs via lft/rgt under that root on the same name_id
    (depth-0 helper is crumbs-only inside one name_id).

    Room identity is name_id (the plan name). Root ``(type, id)`` is mail payload.
    Returns None when this forest is not a MAIL room (e.g. name/todo @ lft=1).
    """
    rows = [n for n in (nodes or []) if isinstance(n, Mapping)]
    for n in rows:
        try:
            lft = int(n.get("lft") or 0)
        except (TypeError, ValueError):
            continue
        if lft != 1:
            continue
        if str(n.get("type") or "").strip().lower() != CONST_MAIL:
            continue
        return dict(n)
    return None


def mail_rooms_from_trees(
    trees: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Room list = floor.trees whose root is type=mail AND lft=1.

    Client-side equivalent of the Rooms root SELECT (no GROUP BY): keep forests
    whose root node matches WHERE type = 'mail' AND lft = 1. ``floor.trees``
    from pack_trees is one entry per name_id / forest.
    """
    out: list[dict[str, Any]] = []
    for t in trees or []:
        if not isinstance(t, Mapping):
            continue
        nodes = t.get("nodes")
        if not isinstance(nodes, Sequence):
            continue
        if mail_tree_root(nodes) is None:
            continue
        out.append(dict(t))
    return out



def mail_room_latest_at(
    tree: Mapping[str, Any] | None,
    mailbox: Sequence[Mapping[str, Any]] | None,
) -> str:
    """Latest activity time in one name_id forest (newest mail at/under the tree).

    Timestamp field (lean MAIL cast / crumbs): lean public MAIL uses ``created``;
    legacy mailbox rows use ``at``. Resolved by ``mail_at`` (``at`` or ``created``).
    TREE crumbs carry tree/parent ids only - not the activity clock. Rooms left
    pane sorts forests by this string descending (most recent first).
    """
    if not isinstance(tree, Mapping):
        return ""
    nodes = tree.get("nodes")
    if not isinstance(nodes, Sequence):
        return ""
    by_id: dict[str, Mapping[str, Any]] = {}
    for m in mailbox or []:
        if not isinstance(m, Mapping):
            continue
        mid = m.get("id")
        if mid is None or mid == "":
            continue
        by_id[str(mid)] = m
    latest = ""
    for n in nodes:
        if not isinstance(n, Mapping):
            continue
        if str(n.get("type") or "").strip().lower() != CONST_MAIL:
            continue
        mid = n.get("id")
        if mid is None or mid == "":
            continue
        m = by_id.get(str(mid))
        if m is None:
            continue
        ts = mail_at(m)
        if ts and ts > latest:
            latest = ts
    return latest


def mail_rooms_sorted_by_latest(
    trees: Sequence[Mapping[str, Any]] | None,
    mailbox: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """MAIL rooms (type=mail AND lft=1) sorted most-recent-first by mail_room_latest_at.

    Activity clock = lean ``created`` / legacy ``at`` via mail_at (see mail_room_latest_at).
    """
    rooms = mail_rooms_from_trees(trees)
    return sorted(
        rooms,
        key=lambda t: mail_room_latest_at(t, mailbox) or "",
        reverse=True,
    )


def mail_tree_depth0(nodes: Sequence[Mapping[str, Any]] | None) -> dict[str, Any] | None:
    """Crumbs-only: depth-0 / no strict ancestor inside one name_id.

    Not used to build the Rooms list (that is WHERE type='mail' AND lft=1).
    Prefer packed ``depth === 0``; else compute no strict ancestor.
    """
    rows = [n for n in (nodes or []) if isinstance(n, Mapping)]
    if not rows:
        return None

    def _lr(n: Mapping[str, Any]) -> tuple[int, int]:
        try:
            return int(n.get("lft") or 0), int(n.get("rgt") or 0)
        except (TypeError, ValueError):
            return 0, 0

    def _lft(n: Mapping[str, Any]) -> int:
        return _lr(n)[0]

    depth0: list[Mapping[str, Any]] = []
    for n in rows:
        d = n.get("depth")
        if d is None or d == "":
            continue
        try:
            if int(d) == 0:
                depth0.append(n)
        except (TypeError, ValueError):
            continue
    if depth0:
        return dict(min(depth0, key=_lft))

    roots: list[Mapping[str, Any]] = []
    for n in rows:
        lft, rgt = _lr(n)
        if not any(
            (_lr(o)[0] < lft and _lr(o)[1] > rgt)
            for o in rows
            if o is not n
        ):
            roots.append(n)
    if not roots:
        roots = list(rows)
    return dict(min(roots, key=_lft))


def mail_room_cast(m: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Room cast = sender union mail_tos (deskId + roster; no receipt on sender)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    src = mail_sender_desk(m)
    if src:
        aff = None
        sender = (m or {}).get("sender")
        if isinstance(sender, dict):
            aff = sender.get("roster") or None
        seen.add(src)
        out.append({"deskId": src, "roster": aff})
    for t in mail_tos(m):
        d = str(t.get("deskId") or "").strip()
        if not d or d in seen:
            continue
        seen.add(d)
        out.append({"deskId": d, "roster": t.get("roster") or None})
    return out


def mail_lean_tos_len(m: Mapping[str, Any] | None) -> int:
    """Lean mail_tos length only; do not invent from legacy dst."""
    if not m:
        return 0
    raw = m.get("mail_tos")
    if not isinstance(raw, list):
        return 0
    return len(raw)


def mail_cast_count(m: Mapping[str, Any] | None) -> int:
    """Cast size = 1 (sender) + len(mail_tos). Lean only."""
    if not mail_is_lean(m):
        return 0
    return 1 + mail_lean_tos_len(m)


def mail_cast_tip(m: Mapping[str, Any] | None) -> str:
    """Hover text: sender + each mail_to desk/roster."""
    if not m:
        return ""
    parts: list[str] = []
    desk = mail_sender_desk(m)
    aff = None
    sender = m.get("sender")
    if isinstance(sender, dict):
        aff_raw = sender.get("roster")
        aff = None if aff_raw is None or aff_raw == "" else aff_raw
    if desk:
        parts.append(f"from {desk} ({aff})" if aff else f"from {desk}")
    raw = m.get("mail_tos") if isinstance(m.get("mail_tos"), list) else []
    for t in raw:
        if not isinstance(t, dict):
            continue
        d = _name_text(t.get("deskId") if t.get("deskId") not in (None, "") else t.get("desk"))
        if not d:
            continue
        a_raw = t.get("roster")
        a = None if a_raw is None or a_raw == "" else a_raw
        parts.append(f"to {d} ({a})" if a else f"to {d}")
    return "; ".join(parts)


def mail_dst_desks(m: Mapping[str, Any] | None) -> list[str]:
    """All destination deskIds (mail_tos), or legacy single dst."""
    tos = mail_tos(m)
    if tos:
        return [str(t["deskId"]) for t in tos if t.get("deskId")]
    dst = _name_text((m or {}).get("dst"))
    if not dst or dst == "*":
        return [dst] if dst == "*" else []
    return [dst]


def mail_at(m: Mapping[str, Any] | None) -> str:
    """Timestamp for paint: created (lean) or at (legacy)."""
    if not m:
        return ""
    return str(m.get("at") or m.get("created") or "").strip()


def mail_dst(m: Mapping[str, Any] | None) -> str:
    """Primary dst for LIST chrome: legacy dst, else first mail_to deskId."""
    if not m:
        return ""
    raw = _name_text(m.get("dst"))
    if raw:
        return raw
    tos = mail_tos(m)
    if not tos:
        return ""
    return str(tos[0].get("deskId") or "").strip()


def mail_is_floor(m: Mapping[str, Any] | None) -> bool:
    dst = mail_dst(m)
    if mail_is_lean(m) and not mail_tos(m) and not _name_text(m.get("dst")):
        return True
    return (not dst) or dst == "*"


def mail_dst_key(dst: Any) -> str:
    return _name_text(dst)


def mail_bare_dst(dst: Any) -> str:
    return _name_text(dst).lower()


def mail_is_bare_human_mailbox(dst: str | None) -> bool:
    d = mail_bare_dst(dst)
    return (not d) or d in BARE_HUMAN_MAILBOXES


def mail_active_rows(rows: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    """Strip bare-human / dead-letter rows from active mailbox chrome."""
    return [m for m in (rows or []) if not mail_is_bare_human_mailbox(m.get("dst"))]


def mail_read_matches_dst(r: Mapping[str, Any] | None, dst: str | None) -> bool:
    if not r:
        return False
    desk = _name_text(r.get("desk") if r.get("desk") not in (None, "") else r.get("reader"))
    if not desk:
        return False
    return desk == _name_text(dst)


def mail_dst_agent_read(m: Mapping[str, Any] | None) -> bool:
    """Primary Wall unread clear = party=agent read for dst desk."""
    if not m or mail_is_floor(m):
        return False
    if m.get("read_agent") is True:
        return True
    dst = mail_dst(m)
    reads = m.get("reads") or []
    if reads:
        return any(
            mail_read_matches_dst(r, dst)
            and str((r or {}).get("party") or "").lower() == "agent"
            for r in reads
        )
    key = mail_dst_key(dst)
    for r in m.get("readers") or []:
        s = str(r or "").strip()
        if (
            s == key + ":agent"
            or s.startswith(key + ":agent:")
            or s == dst + ":agent"
            or s.startswith(str(dst) + ":agent:")
        ):
            return True
    return False


def mail_dst_human_opened(m: Mapping[str, Any] | None) -> bool:
    """Soft cue: human opened on Wall (party=human). Not on lean public cast."""
    if not m or mail_is_floor(m):
        return False
    dst = mail_dst(m)
    reads = m.get("reads") or []
    if reads:
        return any(
            mail_read_matches_dst(r, dst)
            and str((r or {}).get("party") or "").lower() == "human"
            for r in reads
        )
    key = mail_dst_key(dst)
    for r in m.get("readers") or []:
        s = str(r or "").strip()
        if s == key + ":human" or s == dst + ":human":
            return True
    return False


def mail_dst_read(m: Mapping[str, Any] | None) -> bool:
    """Deprecated name kept: primary read = agent read (board mirror)."""
    return mail_dst_agent_read(m)


def mail_star_any_agent_read(m: Mapping[str, Any] | None) -> bool:
    """Wall * glance: True if ANY agent desk marked this * row (or batch flag)."""
    if not m or mail_dst(m) != "*":
        return False
    if m.get("read_star_any_agent") is True:
        return True
    reads = m.get("reads") or []
    if reads:
        return any(str((r or {}).get("party") or "").lower() == "agent" for r in reads)
    for r in m.get("readers") or []:
        s = str(r or "").strip()
        if ":agent" in s:
            return True
    return False


def mail_star_wall_unread(m: Mapping[str, Any] | None) -> bool:
    """Human Wall: * looks unread until any agent marked it."""
    return bool(m) and mail_dst(m) == "*" and (not mail_star_any_agent_read(m))


def mail_wall_unread(m: Mapping[str, Any] | None) -> bool:
    """Wall paint unread: desk agent-unread, or * glance unread. Not peek."""
    if not m:
        return False
    if mail_dst(m) == "*":
        return mail_star_wall_unread(m)
    return mail_msg_agent_unread(m)


def mail_msg_human_required_open(m: Mapping[str, Any] | None) -> bool:
    """HR open: legacy flags, or lean mail_tos.receipt==1 (public cast; no opened)."""
    if not m:
        return False
    if m.get("human_required_cleared") or m.get("human_acked") or m.get("human_required_done"):
        return False
    st = str(m.get("human_required_status") or "").lower()
    if st in {"cleared", "acked", "done"}:
        return False
    if bool(m.get("human_required") or m.get("needs_human")):
        return True
    # Lean: receipt on dest = human_required (set outside mill send; send has no flag for it).
    return any(int(t.get("receipt") or 0) == 1 for t in mail_tos(m))


def mail_msg_agent_unread(m: Mapping[str, Any] | None) -> bool:
    """Agent-unread for Wall paint.

    Lean public MAIL has no opened: do **not** invent unread from its absence.
    Attention for lean rows comes from receipt (HR) + floor.desk_unread rails /
    TREE crumbs at the paint layer. Legacy rows with reads/readers/read_agent
    keep the dual-read contract.
    """
    if not m or mail_is_floor(m):
        return False
    if mail_dst(m) == "*":
        return mail_star_wall_unread(m)
    if mail_is_lean(m) and m.get("read_agent") is not True and not (m.get("reads") or m.get("readers")):
        return False
    return not mail_dst_agent_read(m)


def mail_msg_needs_attention(m: Mapping[str, Any] | None) -> bool:
    return mail_msg_agent_unread(m) or mail_msg_human_required_open(m)


def mail_desk_matches(m: Mapping[str, Any] | None, desk: Any) -> bool:
    """True when the selected name is a destination.

    The name is the stored string. Type, when present, is the name object
    field (desk, project, role, label, tree, res), not a prefix on the string.
    """
    want = _name_text(desk)
    if not want:
        return False
    desks = mail_dst_desks(m)
    if want == "*":
        return "*" in desks or mail_dst(m) == "*"
    saw_type = False
    raw_tos = m.get("mail_tos") if m and isinstance(m.get("mail_tos"), list) else []
    for t in raw_tos:
        if not isinstance(t, Mapping):
            continue
        ident = t.get("deskId") if t.get("deskId") not in (None, "") else t.get("desk")
        if _name_type(ident):
            saw_type = True
        if _same_name(ident, desk):
            return True
    raw_dst = m.get("dst") if m else None
    if raw_dst not in (None, ""):
        if _name_type(raw_dst):
            saw_type = True
        if _same_name(raw_dst, desk):
            return True
    if saw_type:
        return False
    for d in desks:
        if _same_name(d, desk):
            return True
    return False


def mail_rows_all_recent(
    rows: Sequence[Mapping[str, Any]] | None,
    mode: str = "attention",
) -> list[Mapping[str, Any]]:
    out = list(rows or [])
    if mode == "attention":
        out = [m for m in out if mail_msg_needs_attention(m)]
    out.sort(key=lambda m: mail_at(m), reverse=True)
    if mode == "recent":
        out = out[:80]
    return out


def mail_rows_for_list_dst(
    rows: Sequence[Mapping[str, Any]] | None,
    dst: str | None,
    mode: str = "attention",
) -> list[Mapping[str, Any]]:
    """LIST col2 = selected dst only (ACCEPTANCE-MAIL-LIST-DST-FILTER). Empty dst -> []."""
    want = str(dst or "").strip()
    if not want:
        return []
    scoped = [m for m in (rows or []) if mail_desk_matches(m, want)]
    return mail_rows_all_recent(scoped, mode)


def mail_rows_for_dst_src(
    rows: Sequence[Mapping[str, Any]] | None,
    dst: str | None,
    src: str | None = "",
    mode: str = "attention",
) -> list[Mapping[str, Any]]:
    """GRAPH col3 / legacy desk list: dst (+ optional src) with unread-first sort.

    mode=recent -> recent-first cap 80. Else agent-unread, then HR open, then at desc.
    Empty src = dst-only (legacy LIST desk path / GRAPH before src pick uses empty col3
    at the paint layer - this helper still returns dst-scoped rows when src empty).
    """
    want = str(dst or "").strip()
    if not want:
        return []
    out = [m for m in (rows or []) if mail_desk_matches(m, want)]
    want_src = str(src or "").strip()
    if want_src:
        out = [m for m in out if mail_sender_desk(m) == want_src]
    if mode == "recent":
        out = sorted(out, key=lambda m: mail_at(m), reverse=True)[:80]
        return out
    # attention / all: unread desc, HR desc, at desc (board mailRowsForDstSrc)
    out = sorted(
        out,
        key=lambda m: (
            1 if mail_msg_agent_unread(m) else 0,
            1 if mail_msg_human_required_open(m) else 0,
            mail_at(m),
        ),
        reverse=True,
    )
    return out

def mail_rows_for_desk(
    rows: Sequence[Mapping[str, Any]] | None,
    desk: str | None,
    mode: str = "attention",
) -> list[Mapping[str, Any]]:
    return mail_rows_for_dst_src(rows, desk, "", mode)


def mail_srcs_for_dst(
    rows: Sequence[Mapping[str, Any]] | None,
    dst: str | None,
) -> list[dict[str, Any]]:
    """GRAPH src rail aggregates for selected dst (non-empty src).

    Floor (no dest) never has senders for a dst. Star dst=* is a real dest on cast
    but mail_is_floor treats legacy dst="*" as floor - still allow srcs when want is *.
    """
    want = str(dst or "").strip()
    if not want:
        return []
    by: dict[str, dict[str, Any]] = {}
    for m in rows or []:
        if not mail_desk_matches(m, want):
            continue
        if mail_is_floor(m) and want != "*":
            continue
        src = mail_sender_desk(m)
        if not src:
            continue
        prev = by.get(src) or {"id": src, "agentUnread": 0, "humanRequired": 0, "n": 0}
        prev["n"] += 1
        if mail_msg_agent_unread(m):
            prev["agentUnread"] += 1
        if mail_msg_human_required_open(m):
            prev["humanRequired"] += 1
        by[src] = prev
    return sorted(
        by.values(),
        key=lambda x: (-int(x["agentUnread"]), -int(x["humanRequired"]), str(x["id"])),
    )


def mail_attention_dsts(
    dsts: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    return [x for x in (dsts or []) if x.get("needsAttention")]


def mail_list_autoselect_dst(
    dsts: Sequence[Mapping[str, Any]] | None,
    *,
    mode: str = "attention",
    selected: str | None = "",
    view: str = "list",
) -> str:
    """LIST enter: prefer Needs-attention dst; else first rail dst. GRAPH: no auto src.

    Mirrors board `mail()` LIST path + attention snap:
    - view != list -> return selected unchanged (GRAPH must not auto-pick src;
      dst snap for GRAPH attention is paint-layer; callers may pass view=list only
      for the LIST contract tested here, or use mail_resolve_list_dst).
    - selected kept if non-empty **unless** mode=attention and a Needs rail exists
      and selected is not on that Needs rail -> snap to first Needs (board lines
      ~3899-3908).
    - empty selected -> first Needs (attention mode with Needs present) else first rail.
    """
    return mail_resolve_list_dst(dsts, mode=mode, selected=selected, view=view)


def mail_resolve_list_dst(
    dsts: Sequence[Mapping[str, Any]] | None,
    *,
    mode: str = "attention",
    selected: str | None = "",
    view: str = "list",
) -> str:
    """Canonical LIST dst resolution (autoselect + attention snap). See mail_list_autoselect_dst."""
    sel = str(selected or "").strip()
    if view != "list":
        return sel  # GRAPH: no LIST autoselect contract
    rail = list(dsts or [])
    attention = mail_attention_dsts(rail)
    if mode == "attention" and attention:
        if sel and any(str(x.get("id") or "").strip() == sel for x in attention):
            return sel
        # empty OR selected not in Needs -> snap to first Needs
        return str(attention[0].get("id") or "").strip()
    if sel:
        return sel
    if not rail:
        return ""
    return str(rail[0].get("id") or "").strip()
