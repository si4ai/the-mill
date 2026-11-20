"""Repeatable --label on the six activity writes and reads (#1233).

One path validates, sets, and warns. --label never mints a label. A live label,
or a desk that already has a focus list, is set. Anything else is skipped with
a warning and the write still happens.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Callable

SIX = ("mail", "todo", "doing", "hold", "score", "wake")
_CREATE = "mill create label"
_HIST_CAP = 5000


@dataclass(frozen=True)
class NameRow:
    """One catalog name the helper may see. Tests build these without SQL."""

    name: str
    kind: str
    focus: bool = False
    may_set: bool = True
    focus_name: str = ""


@dataclass(frozen=True)
class Accepted:
    put: str
    show: str
    aliases: tuple[str, ...]


@dataclass
class Classified:
    accepted: list[Accepted] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def set_names(self) -> list[str]:
        return [a.put for a in self.accepted]

    @property
    def show(self) -> list[str]:
        return [a.show for a in self.accepted]


def clean(raw: Any) -> list[str]:
    """Strip blanks and drop duplicates. Order stays."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = [raw]
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def asked(body: dict[str, Any] | None) -> list[str]:
    """Repeatable labels on the wire. A single string is the invite flag, not this."""
    body = body or {}
    raw = body.get("labels")
    if raw is None and isinstance(body.get("label"), (list, tuple)):
        raw = body.get("label")
    return clean(raw)


def closest(name: str, label_names: list[str]) -> str:
    folded = {n.casefold(): n for n in label_names if n and n.casefold() != name.casefold()}
    hits = difflib.get_close_matches(name.casefold(), list(folded), n=3, cutoff=0.6)
    if not hits:
        return "none"
    return ", ".join(folded[h] for h in hits)


def warn_unknown(name: str, label_names: list[str]) -> str:
    return "label '%s' does not exist. closest: %s. %s %s." % (name, closest(name, label_names), _CREATE, name)


def warn_other(name: str, kind: str, label_names: list[str]) -> str:
    return "label '%s' does not exist. %s is a %s, not a label. closest: %s. %s %s." % (
        name, name, kind, closest(name, label_names), _CREATE, name,
    )


def warn_denied(name: str, label_names: list[str]) -> str:
    return "label '%s' may not be set. closest: %s. %s %s." % (name, closest(name, label_names), _CREATE, name)


def classify(raw: Any, catalog: list[NameRow], label_names: list[str] | None = None) -> Classified:
    """Split requested names into ones to set and ones to skip. Never mints."""
    names = clean(raw)
    by: dict[str, NameRow] = {}
    for row in catalog:
        by.setdefault(row.name.casefold(), row)
    if label_names is None:
        label_names = [r.name for r in catalog if r.kind == "label" and r.may_set]
    accepted: list[Accepted] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for name in names:
        row = by.get(name.casefold())
        if row is None or not row.kind:
            warnings.append(warn_unknown(name, label_names))
            continue
        if row.kind == "label":
            if not row.may_set:
                warnings.append(warn_denied(name, label_names))
                continue
            key = row.name.casefold()
            if key in seen:
                continue
            seen.add(key)
            accepted.append(Accepted(row.name, row.name, (row.name,)))
            continue
        if row.kind == "desk" and row.focus:
            key = row.name.casefold()
            if key in seen:
                continue
            seen.add(key)
            aliases = [row.name]
            show = row.focus_name or row.name
            if row.focus_name and row.focus_name.casefold() != row.name.casefold():
                aliases.append(row.focus_name)
            accepted.append(Accepted(row.name, show, tuple(aliases)))
            continue
        warnings.append(warn_other(name, row.kind, label_names))
    return Classified(accepted, warnings)


def hits(have: set[str] | list[str], classified: Classified, *, any_mode: bool) -> bool:
    """Every accepted label is on the item, unless --any (at least one).

    A skipped name (unknown or not allowed) fails an every-match: the item
    cannot carry a label that was not set. --any still matches the valid ones.
    """
    if not classified.accepted and not classified.warnings:
        return True
    if classified.warnings and not any_mode:
        return False
    if not classified.accepted:
        return False
    folded = {str(h).casefold() for h in have if str(h).strip()}

    def one(acc: Accepted) -> bool:
        return any(a.casefold() in folded for a in acc.aliases)

    if any_mode:
        return any(one(a) for a in classified.accepted)
    return all(one(a) for a in classified.accepted)


def keep(
    items: list[Any],
    classified: Classified,
    *,
    any_mode: bool,
    labels_of: Callable[[Any], set[str] | list[str]],
    pred: Callable[[Any], bool] | None = None,
) -> list[Any]:
    """Label match, then an optional extra predicate (status, mine, find)."""
    out: list[Any] = []
    for item in items:
        if pred is not None and not pred(item):
            continue
        if hits(labels_of(item), classified, any_mode=any_mode):
            out.append(item)
    return out


def emit_warnings(row: Any, *, file: Any = None) -> None:
    """Loud stderr line for each label_warnings entry. Wording stays here."""
    import sys

    dest = file if file is not None else sys.stderr
    seen: list[str] = []

    def take(obj: Any) -> None:
        if not isinstance(obj, dict):
            return
        for warning in obj.get("label_warnings") or []:
            text = str(warning)
            if text and text not in seen:
                seen.append(text)

    if isinstance(row, dict):
        take(row)
        take(row.get("result"))
    for text in seen:
        print("warning: %s" % text, file=dest)


def absorb_rows(row: Any) -> Any:
    """Lift a labeled list read back to a list so paging still sees the matches.

    label_warnings and labels move onto the envelope. Unlabeled results stay put.
    """
    if not isinstance(row, dict):
        return row
    res = row.get("result")
    if not (isinstance(res, dict) and res.get("_rows") is True and isinstance(res.get("rows"), list)):
        return row
    out = dict(row)
    out["result"] = list(res["rows"])
    warns = [str(w) for w in (res.get("label_warnings") or [])]
    labels = [str(w) for w in (res.get("labels") or [])]
    if warns:
        out["label_warnings"] = warns
    if labels or warns:
        out["labels"] = labels
    return out


def _as_int(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _card_fields(body: dict[str, Any]) -> bool:
    return "done_when" in body or any(body.get(k) for k in ("eta", "started", "progress"))


def _score_read(body: dict[str, Any]) -> bool:
    raw = body.get("value")
    has_value = raw is not None and str(raw).strip() != ""
    target = body.get("target")
    better = str(body.get("better") or "").strip() or None
    unit = str(body.get("unit") or "").strip() or None
    name = str(body.get("name") or body.get("kpi") or "").strip()
    defining = bool(name and ((target is not None and str(target).strip() != "") or better or unit))
    note = str(body.get("note") or "").strip()
    at = str(body.get("at") or "").strip()
    if has_value or body.get("retire") or defining or at or note:
        return False
    return True


def write_type(command: str, body: dict[str, Any]) -> str | None:
    """Activity type this call writes, or None when --label does not stamp it."""
    if command == "open":
        return "todo"
    if command in ("claim", "unclaim", "unpark", "assign", "pass"):
        return "todo"
    if command == "todo":
        return "todo" if _card_fields(body) else None
    if command in ("send", "reply"):
        return "mail"
    if command == "hold":
        if body.get("peek") or not str(body.get("resource") or "").strip():
            return None
        return "hold"
    if command == "drop":
        return "hold"
    if command == "wake-done":
        return "wake"
    if command == "replace-body":
        if body.get("history"):
            return None
        kind = str(body.get("type") or "").strip().lower()
        return kind if kind in ("mail", "todo") else None
    if command in ("attach", "move", "prune", "detach"):
        kind = _tree_kind(command, body)
        return kind if kind in SIX else None
    if command in ("rename", "retire", "reclaim"):
        if str(body.get("name_type") or "").strip().lower() == "todo":
            return "todo"
        return None
    return None


def is_read(command: str, body: dict[str, Any]) -> bool:
    if command in ("inbox", "mail-thread", "session"):
        return True
    if command == "todo":
        return not _card_fields(body)
    if command == "hold":
        return bool(body.get("peek") or not str(body.get("resource") or "").strip())
    if command == "score":
        return _score_read(body)
    return False


def _tree_kind(command: str, body: dict[str, Any]) -> str:
    if command == "attach":
        return str(body.get("type_b") or body.get("type") or "").strip().lower()
    return str(body.get("type") or body.get("type_b") or "").strip().lower()


def _tree_id_ref(command: str, body: dict[str, Any]) -> tuple[int, str]:
    if command == "attach":
        raw = body.get("id_b") if body.get("id_b") not in (None, "") else body.get("id")
        ref = str(body.get("ref_b") or "")
    else:
        raw = body.get("id") if body.get("id") not in (None, "") else body.get("id_b")
        ref = str(body.get("ref") or "")
    return _as_int(raw), ref


def _todo_id(cn: Any, body: dict[str, Any]) -> int:
    if cn is None:
        return 0
    from agent_coord.server.records import todo as rec_todo

    hit = rec_todo.find(cn, str(body.get("project") or ""), str(body.get("need") or ""))
    return int(hit["id"]) if hit else 0


def _resolve_ref(cn: Any, ref: str) -> int:
    if cn is None or "/" not in ref:
        return 0
    roster, _, need = ref.partition("/")
    from agent_coord.server.records import todo as rec_todo

    hit = rec_todo.find(cn, roster.strip(), need.strip())
    return int(hit["id"]) if hit else 0


def wake_target(cn: Any, owner: str | None, body: dict[str, Any], result: Any) -> int:
    """Wake id wake-done actually ended, else 0. A stale or already-done lease sets nothing."""
    if not isinstance(result, dict):
        return 0
    raw = str(result.get("wake") or "")
    state = str(result.get("lease") or "")
    if raw in ("already_done", "stale", "none", "error") or state in ("already_done", "stale"):
        return 0
    if cn is None:
        return 0
    token = str(body.get("lease") or "").strip()
    if token:
        from agent_coord.server.wake_lease import ring_row

        try:
            row = ring_row(cn, token)
        except Exception:
            row = None
        return int((row or {}).get("wake_id") or 0)
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT t.activity_id FROM transition t"
            " JOIN name d ON d.id = t.desk_id AND d.type = 'desk' AND d.name = %s"
            " WHERE t.activity_type = 'wake' AND t.reason = 'wake_done'"
            " ORDER BY t.id DESC LIMIT 1",
            (str(owner or ""),),
        )
        rec = cur.fetchone()
    finally:
        cur.close()
    return int(rec[0]) if rec and rec[0] else 0


def target_ids(command: str, body: dict[str, Any], result: Any, cn: Any, owner: str | None) -> list[tuple[str, int]]:
    typ = write_type(command, body)
    if not typ:
        return []
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        out: list[tuple[str, int]] = []
        for row in result["results"]:
            if not isinstance(row, dict) or row.get("ok") is False:
                continue
            nid = _as_int(row.get("id"))
            if nid:
                out.append((typ, nid))
        return out
    if command == "wake-done":
        nid = wake_target(cn, owner, body, result)
        return [(typ, nid)] if nid else []
    if command == "hold":
        if not isinstance(result, dict) or result.get("ok") is False or result.get("held") is False:
            return []
        nid = _as_int(result.get("id"))
        return [(typ, nid)] if nid else []
    if command == "drop":
        if not isinstance(result, dict) or not result.get("released"):
            return []
        nid = _as_int(result.get("id"))
        return [(typ, nid)] if nid else []
    if command in ("attach", "move", "prune", "detach"):
        nid, ref = _tree_id_ref(command, body)
        if not nid:
            nid = _resolve_ref(cn, ref)
        return [(typ, nid)] if nid else []
    if command in ("unclaim", "unpark") or (command in ("rename", "retire", "reclaim") and typ == "todo"):
        nid = _as_int(result.get("id")) if isinstance(result, dict) else 0
        if not nid:
            nid = _todo_id(cn, body)
        return [(typ, nid)] if nid else []
    if isinstance(result, dict):
        nid = _as_int(result.get("id"))
        return [(typ, nid)] if nid else []
    return []


def _miss_line(command: str) -> str:
    if command == "hold":
        return "hold was not taken; no label set"
    if command == "drop":
        return "drop released nothing; no label set"
    if command == "wake-done":
        return "wake-done ended nothing; no label set"
    return "no label set"


def _stamp_dict(result: dict[str, Any], classified: Classified, extra: list[str], *, placed: bool) -> dict[str, Any]:
    out = dict(result)
    out["labels"] = classified.show if placed else []
    warns = list(classified.warnings) + [w for w in extra if w not in classified.warnings]
    out["label_warnings"] = warns
    return out


def stamp_write(command: str, result: Any, classified: Classified, targets: list[tuple[str, int]]) -> Any:
    extra: list[str] = []
    placed = bool(targets)
    if classified.set_names and not placed:
        extra.append(_miss_line(command))
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        out = _stamp_dict(result, classified, extra, placed=placed)
        rows = []
        stamped = {i for _t, i in targets}
        for row in result["results"]:
            if not isinstance(row, dict):
                rows.append(row)
                continue
            item = dict(row)
            if row.get("ok") is not False and _as_int(row.get("id")) in stamped:
                item["labels"] = classified.show
            item["label_warnings"] = list(classified.warnings) + extra
            rows.append(item)
        out["results"] = rows
        return out
    if isinstance(result, dict):
        return _stamp_dict(result, classified, extra, placed=placed)
    if isinstance(result, list):
        return {
            "rows": result,
            "labels": classified.show if placed else [],
            "label_warnings": list(classified.warnings) + extra,
        }
    return result


def load_catalog(cn: Any, names: list[str]) -> tuple[list[NameRow], list[str]]:
    """Live names for the request, plus every live label (closest). No insert."""
    from agent_coord.server.records import label as rec_label
    from agent_coord.server.records.name import by_id

    want = clean(names)
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT name FROM name WHERE type = 'label' AND deleted IS NULL AND trashed IS NULL"
        )
        label_names = [str(r[0]) for r in cur.fetchall() if r and r[0]]
        found: dict[str, tuple[str, str, bool, bool]] = {}
        if want:
            marks = ",".join(["%s"] * len(want))
            cur.execute(
                "SELECT type, name, deleted IS NULL, trashed IS NULL FROM name WHERE name IN (" + marks + ")",
                tuple(want),
            )
            for typ, name, live, not_trash in cur.fetchall():
                found[str(name).casefold()] = (str(typ), str(name), bool(live), bool(not_trash))
    finally:
        cur.close()
    rows: list[NameRow] = []
    for raw in want:
        hit = found.get(raw.casefold())
        if not hit:
            continue
        typ, stored, live, not_trash = hit
        focus = False
        focus_name = ""
        if typ == "desk":
            fid = rec_label.focus_label_id(cn, stored)
            if fid:
                focus = True
                focus_name = str(by_id(cn, fid) or "")
        may = typ == "label" and live and not_trash
        rows.append(NameRow(stored, typ, focus=focus, may_set=may, focus_name=focus_name))
    return rows, label_names


def resolve(cn: Any, raw: Any) -> Classified:
    names = clean(raw)
    if cn is None:
        return classify(names, [])
    rows, label_names = load_catalog(cn, names)
    return classify(names, rows, label_names)


def apply_names(cn: Any, typ: str, nid: int, names: list[str]) -> None:
    """put() only for names classify already accepted. put mints a focus list; we do not."""
    from agent_coord.server.records import label as rec_label

    for name in names:
        rec_label.put(cn, typ, int(nid), name)


def names_on(cn: Any, typ: str, ids: list[int]) -> dict[int, set[str]]:
    """Stored label name and, when it is a focus list, the desk name."""
    if cn is None or not ids:
        return {}
    clean_ids = list(dict.fromkeys(_as_int(i) for i in ids))
    clean_ids = [i for i in clean_ids if i]
    if not clean_ids:
        return {}
    marks = ",".join(["%s"] * len(clean_ids))
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT l.id, n.name, dn.name"
            " FROM label l"
            " JOIN name n ON n.id = l.name_id AND n.type = 'label'"
            "  AND n.deleted IS NULL AND n.trashed IS NULL"
            " LEFT JOIN seat s ON s.focus_label_id = n.id"
            " LEFT JOIN name dn ON dn.id = s.desk_id AND dn.type = 'desk'"
            "  AND dn.deleted IS NULL AND dn.trashed IS NULL"
            " WHERE l.type = %s AND l.id IN (" + marks + ")",
            (typ, *clean_ids),
        )
        fetched = cur.fetchall()
    finally:
        cur.close()
    out: dict[int, set[str]] = {i: set() for i in clean_ids}
    for rid, name, desk in fetched:
        bag = out.setdefault(int(rid), set())
        if name:
            bag.add(str(name))
        if desk:
            bag.add(str(desk))
    return out


def _id_of(item: Any) -> int:
    if isinstance(item, dict):
        return _as_int(item.get("id"))
    return 0


def _filter_ids(items: list[Any], typ: str, cn: Any, classified: Classified, any_mode: bool) -> list[Any]:
    have = names_on(cn, typ, [_id_of(it) for it in items])
    return keep(items, classified, any_mode=any_mode, labels_of=lambda it: have.get(_id_of(it), set()))


def _wrap_rows(rows: list[Any], classified: Classified) -> dict[str, Any]:
    return {"_rows": True, "rows": rows, "labels": classified.show, "label_warnings": list(classified.warnings)}


def _stamp_read(result: dict[str, Any], classified: Classified) -> dict[str, Any]:
    out = dict(result)
    out["labels"] = classified.show
    out["label_warnings"] = list(classified.warnings)
    return out


def _any_mode(body: dict[str, Any]) -> bool:
    return bool(body.get("label_any"))


def _prepare_history(command: str, body: dict[str, Any]) -> None:
    if command == "session" and body.get("history"):
        body["_label_page"] = body.get("page") or 1
        body["_label_hist_size"] = _HIST_CAP
        body["page"] = 1


def _filter_history(cn: Any, body: dict[str, Any], result: dict[str, Any], classified: Classified) -> dict[str, Any]:
    from agent_coord.helpers.errors import CoordError

    entries = [e for e in (result.get("history") or []) if isinstance(e, dict)]
    doings = [e for e in entries if str(e.get("src") or "doing") == "doing"]
    matched = _filter_ids(doings, "doing", cn, classified, _any_mode(body))
    try:
        page = int(body.get("_label_page") or body.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = page or 1
    size = 50
    try:
        from agent_coord.server.api.mill.rpc import DOING_PAGE

        size = int(DOING_PAGE)
    except Exception:
        size = 50
    total = len(matched)
    of = max(1, -(-total // size)) if total else 1
    if page > 1 and (page - 1) * size >= max(total, 1) and not matched[ (page - 1) * size : page * size]:
        raise CoordError("connected --history --page %s: past the last page" % page)
    part = matched[(page - 1) * size : page * size]
    block: dict[str, Any] = {"n": page, "of": of, "size": size, "entries": total}
    if page < of:
        block["next"] = "--page %s" % (page + 1)
    raw_total = 0
    page_block = result.get("page")
    if isinstance(page_block, dict):
        raw_total = _as_int(page_block.get("entries"))
    out = _stamp_read(result, classified)
    out["history"] = part
    out["page"] = block
    if raw_total > len(entries):
        extra = "connected --history --label stopped at %s rows" % len(entries)
        out["label_warnings"] = list(out["label_warnings"]) + [extra]
    return out


def _filter_live(cn: Any, views: list[Any], classified: Classified, any_mode: bool) -> list[Any]:
    ids: list[int] = []
    for view in views:
        if not isinstance(view, dict):
            continue
        for doing in view.get("doings") or []:
            if isinstance(doing, dict):
                ids.append(_as_int(doing.get("id")))
    have = names_on(cn, "doing", ids)
    out: list[Any] = []
    for view in views:
        if not isinstance(view, dict):
            out.append(view)
            continue
        item = dict(view)
        doings = []
        for doing in view.get("doings") or []:
            if not isinstance(doing, dict):
                continue
            if hits(have.get(_as_int(doing.get("id")), set()), classified, any_mode=any_mode):
                doings.append(doing)
        item["doings"] = doings
        item["n"] = len(doings)
        out.append(item)
    return out


def _filter_score(cn: Any, body: dict[str, Any], result: Any, classified: Classified) -> Any:
    any_mode = _any_mode(body)
    if isinstance(result, dict) and isinstance(result.get("scores"), list):
        scores = _filter_ids(result["scores"], "score", cn, classified, any_mode)
        out = _stamp_read(result, classified)
        out["scores"] = scores
        return out
    if isinstance(result, dict) and _as_int(result.get("id")) and "score" in result:
        have = names_on(cn, "score", [_as_int(result.get("id"))])
        if hits(have.get(_as_int(result.get("id")), set()), classified, any_mode=any_mode):
            return _stamp_read(result, classified)
        return {
            "roster": body.get("project") or result.get("roster") or "",
            "scores": [],
            "labels": classified.show,
            "label_warnings": list(classified.warnings),
        }
    if isinstance(result, dict):
        return _stamp_read(result, classified)
    return result


def _filter_hold(cn: Any, result: Any, classified: Classified, any_mode: bool) -> Any:
    if not isinstance(result, dict):
        return result
    if isinstance(result.get("holds"), list):
        holds = _filter_ids(result["holds"], "hold", cn, classified, any_mode)
        out = _stamp_read(result, classified)
        out["holds"] = holds
        return out
    if result.get("peek"):
        nid = _as_int(result.get("id"))
        have = names_on(cn, "hold", [nid] if nid else [])
        if nid and hits(have.get(nid, set()), classified, any_mode=any_mode):
            return _stamp_read(result, classified)
        return {
            "ok": True,
            "peek": True,
            "resource": result.get("resource"),
            "matched": False,
            "labels": classified.show,
            "label_warnings": list(classified.warnings),
        }
    return _stamp_read(result, classified)


def filter_read(cn: Any, command: str, body: dict[str, Any], result: Any, classified: Classified) -> Any:
    any_mode = _any_mode(body)
    if command == "inbox" and isinstance(result, list):
        return _wrap_rows(_filter_ids(result, "mail", cn, classified, any_mode), classified)
    if command == "todo":
        if isinstance(result, list):
            return _wrap_rows(_filter_ids(result, "todo", cn, classified, any_mode), classified)
        if isinstance(result, dict) and isinstance(result.get("cards"), list):
            cards = _filter_ids(result["cards"], "todo", cn, classified, any_mode)
            out = _stamp_read(result, classified)
            out["cards"] = cards
            return out
    if command == "mail-thread" and isinstance(result, dict):
        chain = [x for x in (result.get("chain") or []) if isinstance(x, dict)]
        out = _stamp_read(result, classified)
        out["chain"] = _filter_ids(chain, "mail", cn, classified, any_mode)
        return out
    if command == "hold":
        return _filter_hold(cn, result, classified, any_mode)
    if command == "session":
        if isinstance(result, dict) and "history" in result:
            return _filter_history(cn, body, result, classified)
        if isinstance(result, list):
            return _wrap_rows(_filter_live(cn, result, classified, any_mode), classified)
    if command == "score":
        return _filter_score(cn, body, result, classified)
    if isinstance(result, dict):
        return _stamp_read(result, classified)
    if isinstance(result, list):
        return _wrap_rows(result, classified)
    return result


def _note_unused(result: Any) -> Any:
    warning = "label: --label does not apply here; no label set"
    if isinstance(result, dict):
        out = dict(result)
        out["labels"] = []
        out["label_warnings"] = [warning]
        return out
    if isinstance(result, list):
        return {"rows": result, "labels": [], "label_warnings": [warning]}
    return result


def _together(cn: Any, run: Callable[[], Any]) -> Any:
    if cn is None:
        return run()
    from agent_coord.server.records.db import in_request_tx, request_tx

    if in_request_tx(cn):
        return run()
    return request_tx(cn, run)


def run_labeled(c: Any, command: str, body: dict[str, Any], owner: str | None, run: Callable[[], Any]) -> Any:
    """Validate, run the handler, set or filter. Trail labels itself."""
    names = asked(body)
    if not names or command == "trail":
        return run()
    cn = getattr(c, "_cn", None)
    writing = write_type(command, body)
    reading = is_read(command, body)
    if writing is None and not reading:
        return _note_unused(run())
    classified = resolve(cn, names)
    if reading:
        _prepare_history(command, body)
        return filter_read(cn, command, body, run(), classified)
    if not classified.set_names:
        return stamp_write(command, run(), classified, [])

    def go() -> Any:
        out = run()
        targets = target_ids(command, body, out, cn, owner)
        for typ, nid in targets:
            apply_names(cn, typ, nid, classified.set_names)
        return stamp_write(command, out, classified, targets)

    return _together(cn, go)


def trail_read(c: Any, labels: list[str], any_mode: bool, one: Callable[[str], Any]) -> dict[str, Any]:
    """Mail and todo wearing every label (or any). Unknown names warn and add no rows."""
    import json

    classified = resolve(getattr(c, "_cn", None), labels)
    raw = clean(labels)
    if len(classified.accepted) == 1 and not classified.warnings:
        return one(classified.accepted[0].put)
    if not classified.accepted:
        label = raw[0] if len(raw) == 1 else ", ".join(raw)
        return {
            "label": label,
            "hint": " ".join(classified.warnings),
            "rows": [],
            "truncated": False,
            "labels": [],
            "label_warnings": list(classified.warnings),
        }
    groups: list[list[dict[str, Any]]] = []
    for acc in classified.accepted:
        got = one(acc.put) or {}
        groups.append([r for r in (got.get("rows") or []) if isinstance(r, dict)])
    if any_mode:
        seen: set[tuple[Any, Any]] = set()
        rows: list[dict[str, Any]] = []
        for group in groups:
            for row in group:
                key = (row.get("type"), row.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
    else:
        rest = [{(r.get("type"), r.get("id")) for r in group} for group in groups[1:]]
        rows = [r for r in groups[0] if all((r.get("type"), r.get("id")) in bag for bag in rest)]
    kept: list[dict[str, Any]] = []
    used = 0
    truncated = False
    for row in rows:
        blob = json.dumps(row, separators=(",", ":")).encode("utf-8")
        if kept and used + len(blob) > 8192:
            truncated = True
            break
        kept.append(row)
        used += len(blob)
    label_field = classified.show[0] if len(classified.show) == 1 else ", ".join(classified.show)
    hint = " ".join(classified.warnings)
    return {
        "label": label_field,
        "hint": hint,
        "rows": kept,
        "truncated": truncated,
        "labels": classified.show,
        "label_warnings": list(classified.warnings),
    }
