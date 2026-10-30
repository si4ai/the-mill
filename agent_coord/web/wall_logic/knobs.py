"""Proposed DB-driven Wall knobs (easy path) - SoR stubs, not a shipped schema.

SoR: `agent_coord.web.wall_logic.knobs` (this module) is the **single source of truth** for
knob *names*, defaults, resolve helpers, and the fungibility ladder lock:

  1) db_knobs - token/config columns tweak layout without writing CSS/JS
  2) pack_css_js_override - full pack CSS/JS still allowed when knobs aren't enough
  3) office_share - desk/office share packs (P1 parked)

**Knobs do not replace pack replaceability.** Ladder step 2 stays valid forever;
db knobs are the easy path, not the only path.

Cut 6 LOCK: wall-contract; wall_logic/knobs.py - mill prefs JSON office_default + per-desk (desk wins). schema_migrated True only after migrate_wall_prefs.
These helpers are pure stubs packs can call once knobs land.

See wall-contract; tests/wall tabs/knobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .tabs import DEFAULT_MAIN_TABS, normalize_tab

# Marker for pack authors / Claims (searchable). Path A: Python SoR stubs.
BOARD_EQUIVALENT_MARKER = "WALL_LOGIC_KNOBS_SOR"

FUNGIBILITY_LADDER = ("db_knobs", "pack_css_js_override", "office_share")

# Explicit locked: knobs are step 1; they never delete step 2/3.
KNOBS_DO_NOT_REPLACE_PACK = True

DENSITY_VALUES = frozenset({"comfortable", "compact"})
MAIL_VIEW_VALUES = frozenset({"list", "graph"})
SCORE_FILTER_VALUES = frozenset({"needs", "all"})

# Proposed columns / JSON fields (review only - not migrated).
PROPOSED_DB_KNOBS: list[dict[str, Any]] = [
    {
        "name": "pane_order",
        "type": "json_array",
        "scope": "desk|office_default",
        "example": list(DEFAULT_MAIN_TABS),
        "effect": "Main tab order; unknown ids ignored; Admin stays chrome-only",
    },
    {
        "name": "land_tab",
        "type": "string",
        "scope": "desk|office_default",
        "example": "session",
        "effect": "Initial hash/pane on cold load",
    },
    {
        "name": "density",
        "type": "enum",
        "scope": "desk|office_default",
        "example": "comfortable|compact",
        "effect": "Maps to CSS variables (--row-pad, --font-sm); not full stylesheet",
    },
    {
        "name": "css_vars",
        "type": "json_object",
        "scope": "desk|office_default|pack",
        "example": {
            "--accent": "#2a6",
            "--pane-gap": "0.5rem",
            "--font-family": "ui-monospace, monospace",
            "--font-size": "13px",
            "--h1-size": "14px",
        },
        "effect": "Whitelist of CSS custom properties injected on :root",
    },
    {
        "name": "chrome_flags",
        "type": "json_object",
        "scope": "desk|office_default",
        "example": {"show_wire": False, "show_guide": True, "show_admin_chrome": True},
        "effect": "Show/hide chrome controls; does not rewrite JS behavior contracts",
    },
    {
        "name": "mail_default_view",
        "type": "enum",
        "scope": "desk",
        "example": "list|graph",
        "effect": "Mail LIST vs GRAPH default (rules stay in wall_logic)",
    },
    {
        "name": "score_default_filter",
        "type": "enum",
        "scope": "desk",
        "example": "needs|all",
        "effect": "Scorecards Needs vs All default",
    },
    {
        "name": "pack_id",
        "type": "string",
        "scope": "desk|office_default",
        "example": "default",
        "effect": "Which pack assets to load; full CSS/JS override when not default",
    },
    {
        "name": "keyboard_profile",
        "type": "enum",
        "scope": "desk|office_default",
        "example": "windows|brief|emacs|vscode|cursor|bot|build",
        "effect": "Per-desk keybinding profile (Path B; Path A localStorage wall-keys:<deskId>)",
    },
    {
        "name": "keyboard_overrides",
        "type": "json_object",
        "scope": "desk",
        "example": {"pane.mail": "Alt+0"},
        "effect": "Per-action chord overrides; desk wins over office_default / profile defaults",
    },
]

_CHROME_DEFAULTS = {
    "show_wire": False,
    "show_guide": True,
    "show_admin_chrome": True,
    "show_debug": False,
    "land_tab": "session",
}

_DENSITY_CSS = {
    "comfortable": {"--row-pad": "0.5rem", "--font-sm": "0.875rem"},
    "compact": {"--row-pad": "0.25rem", "--font-sm": "0.8125rem"},
}

_DEFAULTS = {
    "pane_order": list(DEFAULT_MAIN_TABS),
    "land_tab": "session",
    "density": "comfortable",
    "css_vars": {},
    "chrome_flags": dict(_CHROME_DEFAULTS),
    "mail_default_view": "list",
    "score_default_filter": "needs",
    "pack_id": "default",
    "keyboard_profile": "windows",
    "keyboard_overrides": {},
}


def resolve_pane_order(order: Sequence[str] | None) -> list[str]:
    """Apply pane_order knob; fall back to default pack order."""
    if not order:
        return list(DEFAULT_MAIN_TABS)
    known = set(DEFAULT_MAIN_TABS)
    out: list[str] = []
    for x in order:
        s = str(x or "").strip().lower()
        if s in known and s not in out:
            out.append(s)
    # append any missing defaults so nav never loses a locked pane
    for x in DEFAULT_MAIN_TABS:
        if x not in out:
            out.append(x)
    return out


def resolve_land_tab(name: str | None) -> dict[str, Any]:
    """Cold-load land_tab knob -> normalize_tab outcome (session default)."""
    raw = str(name or "").strip().lower() or "session"
    info = normalize_tab(raw)
    # unknown / empty hashes fall back to session
    if not info["raw"] or (info["pane"] not in set(DEFAULT_MAIN_TABS) | {"backlog", "guide", "admin", "wire"}
                           and info["raw"] not in {"stations", "scorecards"}):
        if info["raw"] not in {"stations", "scorecards", "guide", "admin", "wire"} and info["pane"] not in set(DEFAULT_MAIN_TABS) | {"backlog"}:
            return normalize_tab("session")
    return info


def resolve_density(value: str | None) -> dict[str, Any]:
    """density enum -> css var map (not a full stylesheet)."""
    d = str(value or "").strip().lower() or "comfortable"
    if d not in DENSITY_VALUES:
        d = "comfortable"
    return {
        "density": d,
        "css_vars": dict(_DENSITY_CSS[d]),
        "full_stylesheet": False,
    }


def resolve_mail_default_view(value: str | None) -> str:
    v = str(value or "").strip().lower() or "list"
    return v if v in MAIL_VIEW_VALUES else "list"


def resolve_score_default_filter(value: str | None) -> str:
    v = str(value or "").strip().lower() or "needs"
    return v if v in SCORE_FILTER_VALUES else "needs"


def resolve_pack_id(value: str | None) -> str:
    """pack_id selects assets; empty -> default. Does not block pack CSS/JS override."""
    s = str(value or "").strip() or "default"
    return s


def apply_chrome_flags(flags: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge chrome_flags knob onto defaults (pure)."""
    out = dict(_CHROME_DEFAULTS)
    if flags:
        for k, v in flags.items():
            if k in out or k == "land_tab":
                out[k] = v
    return out


def css_vars_style_attr(vars_map: Mapping[str, str] | None) -> str:
    """Render whitelisted CSS variables as an inline style fragment (no full CSS)."""
    if not vars_map:
        return ""
    parts = []
    for k, v in vars_map.items():
        key = str(k).strip()
        if not key.startswith("--"):
            continue
        # reject braces/semicolons smuggling full rules
        val = str(v).replace(";", "").replace("{", "").replace("}", "").strip()
        if val:
            parts.append(f"{key}:{val}")
    return ";".join(parts)


def merge_knob_layer(
    db_knobs: Mapping[str, Any] | None = None,
    pack_override: Mapping[str, Any] | None = None,
    share: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve ladder: defaults <- db_knobs <- pack_override <- share (later wins).

    Pack override may supply full asset hints (`pack_css`, `pack_js`) that knobs
    never invent - proving knobs do not replace pack replaceability.
    """
    out: dict[str, Any] = {
        "pane_order": list(_DEFAULTS["pane_order"]),
        "land_tab": _DEFAULTS["land_tab"],
        "density": _DEFAULTS["density"],
        "css_vars": dict(_DEFAULTS["css_vars"]),
        "chrome_flags": dict(_DEFAULTS["chrome_flags"]),
        "mail_default_view": _DEFAULTS["mail_default_view"],
        "score_default_filter": _DEFAULTS["score_default_filter"],
        "pack_id": _DEFAULTS["pack_id"],
        "keyboard_profile": _DEFAULTS["keyboard_profile"],
        "keyboard_overrides": dict(_DEFAULTS["keyboard_overrides"]),
        "pack_css": None,
        "pack_js": None,
        "ladder": list(FUNGIBILITY_LADDER),
        "knobs_do_not_replace_pack": KNOBS_DO_NOT_REPLACE_PACK,
        "marker": BOARD_EQUIVALENT_MARKER,
        "pure": True,
        "path": "A",
        "applied_layers": ["defaults"],
    }

    def _apply(layer: Mapping[str, Any] | None, label: str) -> None:
        if not layer:
            return
        out["applied_layers"].append(label)
        if "pane_order" in layer:
            out["pane_order"] = resolve_pane_order(layer.get("pane_order"))  # type: ignore[arg-type]
        if "land_tab" in layer:
            out["land_tab"] = resolve_land_tab(layer.get("land_tab")).get("hash") or "session"
        if "density" in layer:
            dens = resolve_density(layer.get("density"))  # type: ignore[arg-type]
            out["density"] = dens["density"]
            # density css merges under css_vars; explicit css_vars still win later
            merged = dict(dens["css_vars"])
            merged.update(out["css_vars"])
            out["css_vars"] = merged
        if "css_vars" in layer and isinstance(layer["css_vars"], Mapping):
            merged = dict(out["css_vars"])
            merged.update(sanitize_css_vars(layer["css_vars"]))
            out["css_vars"] = merged
        if "chrome_flags" in layer and isinstance(layer["chrome_flags"], Mapping):
            out["chrome_flags"] = apply_chrome_flags({**out["chrome_flags"], **dict(layer["chrome_flags"])})
        if "mail_default_view" in layer:
            out["mail_default_view"] = resolve_mail_default_view(layer.get("mail_default_view"))  # type: ignore[arg-type]
        if "score_default_filter" in layer:
            out["score_default_filter"] = resolve_score_default_filter(layer.get("score_default_filter"))  # type: ignore[arg-type]
        if "pack_id" in layer:
            out["pack_id"] = resolve_pack_id(layer.get("pack_id"))  # type: ignore[arg-type]
        if "keyboard_profile" in layer:
            out["keyboard_profile"] = resolve_keyboard_profile(layer.get("keyboard_profile"))
        if "keyboard_overrides" in layer and isinstance(layer["keyboard_overrides"], Mapping):
            merged_ov = dict(out["keyboard_overrides"])
            merged_ov.update(sanitize_keyboard_overrides(layer["keyboard_overrides"]))
            out["keyboard_overrides"] = merged_ov
        # Pack-only asset hooks (ladder step 2) - knobs never invent these keys as DB columns
        if "pack_css" in layer:
            out["pack_css"] = layer.get("pack_css")
        if "pack_js" in layer:
            out["pack_js"] = layer.get("pack_js")

    _apply(db_knobs, "db_knobs")
    _apply(pack_override, "pack_css_js_override")
    _apply(share, "office_share")
    # final normalize
    out["pane_order"] = resolve_pane_order(out["pane_order"])
    out["css_vars_style"] = css_vars_style_attr(out["css_vars"])
    return out


def knobs_contract() -> dict[str, Any]:
    """Acceptance-facing contract flags for Cut 6 knobs SoR."""
    names = [k["name"] for k in PROPOSED_DB_KNOBS]
    return {
        "marker": BOARD_EQUIVALENT_MARKER,
        "ladder": list(FUNGIBILITY_LADDER),
        "knobs_do_not_replace_pack": KNOBS_DO_NOT_REPLACE_PACK,
        "proposed_names": names,
        "defaults": {
            "land_tab": _DEFAULTS["land_tab"],
            "density": _DEFAULTS["density"],
            "mail_default_view": _DEFAULTS["mail_default_view"],
            "score_default_filter": _DEFAULTS["score_default_filter"],
            "pack_id": _DEFAULTS["pack_id"],
            "pane_order": list(DEFAULT_MAIN_TABS),
            "keyboard_profile": _DEFAULTS["keyboard_profile"],
            "keyboard_overrides": dict(_DEFAULTS["keyboard_overrides"]),
        },
        "schema_migrated": schema_migrated(),
        "prefs_file_cut6": prefs_file_cut6(),
        "cut6_prefs_version": CUT6_PREFS_VERSION,
        "desk_overrides_win": True,
        "storage": "mill_prefs_json",
        "pure": True,
        "path": "A",
        "sor": "wall-contract; wall_logic/knobs.py",
    }


# --- Cut 6: mill prefs JSON (office_default + per-desk); desk wins ---
CUT6_PREFS_VERSION = 6
KEYBOARD_PROFILES = (
    "windows",
    "brief",
    "emacs",
    "vscode",
    "cursor",
    "bot",
    "build",
)

# Flipped True only by migrate_wall_prefs / mark_schema_migrated after successful migrate.
_SCHEMA_MIGRATED = False


def schema_migrated() -> bool:
    return bool(_SCHEMA_MIGRATED)


def prefs_file_cut6(prefs_path: str | Path | None = None) -> bool:
    """Durable Cut 6 signal: mill prefs JSON version >= CUT6_PREFS_VERSION."""
    import json
    path = Path(prefs_path) if prefs_path else (Path.home() / ".mill" / "wall_prefs.json")
    try:
        if not path.is_file():
            return False
        doc = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(doc, dict) and int(doc.get("version") or 0) >= CUT6_PREFS_VERSION
    except Exception:
        return False



def mark_schema_migrated(value: bool = True) -> bool:
    global _SCHEMA_MIGRATED
    _SCHEMA_MIGRATED = bool(value)
    return _SCHEMA_MIGRATED


def sanitize_css_vars(vars_map: Mapping[str, Any] | None) -> dict[str, str]:
    """--* keys only; strip ;{} (Cut 6 + theme sanitize)."""
    out: dict[str, str] = {}
    if not vars_map:
        return out
    for k, v in vars_map.items():
        key = str(k).strip()
        if not key.startswith("--"):
            continue
        val = str(v if v is not None else "").replace(";", "").replace("{", "").replace("}", "").strip()
        if val:
            out[key] = val
    return out


def resolve_keyboard_profile(value: str | None) -> str:
    p = str(value or "").strip().lower() or "windows"
    return p if p in KEYBOARD_PROFILES else "windows"


def sanitize_keyboard_overrides(overrides: Mapping[str, Any] | None) -> dict[str, str]:
    """Keep actionId -> chord strings; drop empties. Chord normalize deferred to wall_logic.keys when present."""
    out: dict[str, str] = {}
    if not overrides:
        return out
    try:
        from .keys import ACTION_IDS, normalize_chord
        known = set(ACTION_IDS)
        use_norm = True
    except Exception:
        known = None
        use_norm = False
    for k, v in overrides.items():
        aid = str(k).strip()
        if known is not None and aid not in known:
            continue
        ch = str(v or "").strip()
        if use_norm:
            ch = normalize_chord(ch)
        if ch:
            out[aid] = ch
    return out


def resolve_office_desk_prefs(
    office_default: Mapping[str, Any] | None = None,
    desk: Mapping[str, Any] | None = None,
    *,
    pack_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Cut 6 resolve: defaults <- office_default <- desk (desk wins) <- optional pack_override.

    Pack CSS/JS override remains valid (ladder step 2). Does not touch paint/mail/score pure rules.
    """
    # merge_knob_layer: defaults <- db_knobs(office) <- pack_override <- share(desk)
    # share applies last => desk wins over office_default.
    out = merge_knob_layer(
        db_knobs=office_default,
        pack_override=pack_override,
        share=desk,
    )
    out["desk_wins"] = True
    out["cut6"] = True
    out["schema_migrated"] = schema_migrated()
    return out


def migrate_wall_keys_into_desk(
    desk_prefs: Mapping[str, Any] | None,
    wall_keys_local: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Path B bridge: fold localStorage wall-keys:<deskId> {profile, overrides} into desk prefs."""
    out = dict(desk_prefs or {})
    if not wall_keys_local:
        return out
    profile = wall_keys_local.get("profile")
    overrides = wall_keys_local.get("overrides")
    if profile and "keyboard_profile" not in out:
        out["keyboard_profile"] = resolve_keyboard_profile(str(profile))
    if isinstance(overrides, Mapping):
        merged = dict(out.get("keyboard_overrides") or {})
        merged.update(sanitize_keyboard_overrides(overrides))
        out["keyboard_overrides"] = merged
    return out


def migrate_wall_prefs(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """Pure migrate mill prefs JSON -> Cut 6 shape.

    Shape:
      {
        "version": 6,
        "office_default": { ... knobs ... },
        "desks": { "<deskId>": { ... knobs ... } },
        "prefs": { ... legacy flat prefs folded into office_default if needed ... }
      }
    """
    raw = dict(doc or {})
    office = raw.get("office_default")
    if office is None or not isinstance(office, Mapping):
        office = {}
    else:
        office = dict(office)
    # legacy flat prefs
    legacy = raw.get("prefs")
    if isinstance(legacy, Mapping):
        for k, v in legacy.items():
            if k not in office:
                office[k] = v
        # density "normal" -> comfortable
        if str(office.get("density") or "").lower() == "normal":
            office["density"] = "comfortable"
    desks_in = raw.get("desks")
    desks: dict[str, Any] = {}
    if isinstance(desks_in, Mapping):
        for did, pref in desks_in.items():
            if isinstance(pref, Mapping):
                desks[str(did)] = dict(pref)
    # ensure keyboard defaults present on office
    office.setdefault("keyboard_profile", "windows")
    office.setdefault("keyboard_overrides", {})
    # sanitize office css_vars
    if "css_vars" in office:
        office["css_vars"] = sanitize_css_vars(office.get("css_vars"))  # type: ignore[arg-type]
    for did, pref in list(desks.items()):
        if "css_vars" in pref:
            pref["css_vars"] = sanitize_css_vars(pref.get("css_vars"))  # type: ignore[arg-type]
        if "keyboard_overrides" in pref:
            pref["keyboard_overrides"] = sanitize_keyboard_overrides(pref.get("keyboard_overrides"))  # type: ignore[arg-type]
        desks[did] = pref
    return {
        "version": CUT6_PREFS_VERSION,
        "office_default": office,
        "desks": desks,
        "prefs": None,  # legacy cleared after fold
        "cut6": True,
    }


def migrate_wall_prefs_file(path: str | Path, *, mark: bool = True) -> dict[str, Any]:
    """Load prefs JSON, migrate, write back; optionally mark schema_migrated."""
    import json

    p = Path(path)
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            doc = {}
    else:
        doc = {}
    migrated = migrate_wall_prefs(doc if isinstance(doc, Mapping) else {})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(migrated, indent=2) + "\n", encoding="utf-8")
    if mark:
        mark_schema_migrated(True)
    return migrated


def wall_inject_payload(resolved: Mapping[str, Any] | None) -> dict[str, Any]:
    """Shape resolved Cut 6 knobs for Wall boot inject (pure; no I/O).

    Fail-closed callers pass resolve_office_desk_prefs(None, None) when prefs/API missing.
    """
    r = dict(resolved or {})
    dens = resolve_density(r.get("density"))
    css = dict(dens.get("css_vars") or {})
    css.update(sanitize_css_vars(r.get("css_vars") if isinstance(r.get("css_vars"), Mapping) else None))
    land = resolve_land_tab(r.get("land_tab"))
    flags = apply_chrome_flags(r.get("chrome_flags") if isinstance(r.get("chrome_flags"), Mapping) else None)
    return {
        "land_tab": land.get("hash") or "session",
        "pane_order": resolve_pane_order(r.get("pane_order") if isinstance(r.get("pane_order"), (list, tuple)) else None),
        "density": dens["density"],
        "css_vars": css,
        "css_vars_style": css_vars_style_attr(css),
        "chrome_flags": flags,
        "mail_default_view": resolve_mail_default_view(r.get("mail_default_view")),
        "score_default_filter": resolve_score_default_filter(r.get("score_default_filter")),
        "pack_id": resolve_pack_id(r.get("pack_id")),
        "keyboard_profile": resolve_keyboard_profile(r.get("keyboard_profile")),
        "keyboard_overrides": sanitize_keyboard_overrides(
            r.get("keyboard_overrides") if isinstance(r.get("keyboard_overrides"), Mapping) else None
        ),
        "knobs_do_not_replace_pack": KNOBS_DO_NOT_REPLACE_PACK,
        "cut6": True,
        "pure": True,
    }


def resolve_prefs_doc(
    doc: Mapping[str, Any] | None,
    *,
    desk: str | None = None,
    pack_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load-shaped mill prefs JSON -> resolve_office_desk_prefs (desk wins). Pure."""
    migrated = migrate_wall_prefs(doc if isinstance(doc, Mapping) else {})
    office = migrated.get("office_default") if isinstance(migrated.get("office_default"), Mapping) else {}
    desks = migrated.get("desks") if isinstance(migrated.get("desks"), Mapping) else {}
    desk_row = None
    if desk:
        row = desks.get(str(desk))
        if isinstance(row, Mapping):
            desk_row = dict(row)
    resolved = resolve_office_desk_prefs(office, desk_row, pack_override=pack_override)
    inject = wall_inject_payload(resolved)
    return {
        "version": int(migrated.get("version") or CUT6_PREFS_VERSION),
        "cut6": True,
        "desk": desk or None,
        "office_default": dict(office or {}),
        "desk_prefs": dict(desk_row or {}) if desk_row else {},
        "resolved": resolved,
        "inject": inject,
        "prefs": {
            "land_tab": inject["land_tab"],
            "tabs": inject["pane_order"],
            "density": inject["density"],
            "css_vars": inject["css_vars"],
            "chrome_flags": inject["chrome_flags"],
            "mail_default_view": inject["mail_default_view"],
            "score_default_filter": inject["score_default_filter"],
            "pack_id": inject["pack_id"],
            "keyboard_profile": inject["keyboard_profile"],
            "keyboard_overrides": inject["keyboard_overrides"],
            "pane_order": inject["pane_order"],
        },
        "pack": inject["pack_id"] if inject["pack_id"] != "default" else None,
        "schema_migrated": bool(schema_migrated() or prefs_file_cut6()),
        "knobs_do_not_replace_pack": KNOBS_DO_NOT_REPLACE_PACK,
        "desk_wins": True,
        "source": "mill_prefs_json",
        "ok": True,
    }
