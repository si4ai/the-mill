# -*- coding: utf-8 -*-
"""Wall keyboard profiles + per-desk overrides (Path A pure SoR).

localStorage shape (browser): wall-keys:<deskId> -> {profile, overrides}
Path B mill prefs / Cut 6 later - schema_migrated stays False here.

SoR: wall-contract; tests/wall (keyboard)
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

PROFILES = ("windows", "brief", "emacs", "vscode", "cursor", "bot", "build")
DEFAULT_PROFILE = "windows"

ACTION_IDS = (
    "pane.session",
    "pane.floor",
    "pane.jobs",
    "pane.score",
    "pane.mail",
    "pane.plan",
    "pane.admin",
    "pane.wire",
    "pane.guide",
    "pane.prev",
    "pane.next",
    "pane.refresh",
    "focus.filter",
    "context.new",
    "ui.help",
    "ui.cancel",
    "floor.toggleAgg",
    "floor.toggleMapTimeline",
    "mail.next",
    "mail.prev",
    "mail.open",
    "mail.markRead",
    "profile.cycle",
)

# Browser chords we never steal even if customized.
BROWSER_RESERVED = frozenset(
    {
        "Ctrl+T",
        "Ctrl+W",
        "Ctrl+N",
        "Meta+T",
        "Meta+W",
        "Meta+N",
        "Cmd+T",
        "Cmd+W",
        "Cmd+N",
    }
)

PANE_ORDER = (
    "pane.session",
    "pane.floor",
    "pane.jobs",
    "pane.score",
    "pane.mail",
    "pane.plan",
    "pane.admin",
    "pane.wire",
    "pane.guide",
)


def normalize_chord(chord: str | None) -> str:
    """Normalize chord labels to a stable comparable form."""
    raw = str(chord or "").strip()
    if not raw:
        return ""
    # allow "C-g" / "C-x b" emacs shorthand
    raw = raw.replace("C-", "Ctrl+")
    raw = raw.replace("M-", "Alt+")
    parts = [p.strip() for p in raw.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return ""
    mods: list[str] = []
    key = ""
    for p in parts:
        pl = p.lower()
        if pl in ("ctrl", "control", "ctl"):
            mods.append("Ctrl")
        elif pl in ("alt", "option", "opt"):
            mods.append("Alt")
        elif pl in ("shift",):
            mods.append("Shift")
        elif pl in ("meta", "cmd", "command", "super", "win"):
            mods.append("Meta")
        else:
            key = p
    # de-dupe mods preserving order Ctrl Alt Shift Meta
    order = ["Ctrl", "Alt", "Shift", "Meta"]
    seen = set(mods)
    mods_sorted = [m for m in order if m in seen]
    if not key:
        return "+".join(mods_sorted)
    # single letter / named keys
    if len(key) == 1:
        key_out = key.upper() if mods_sorted else key.lower()
    else:
        kl = key.lower()
        named = {
            "esc": "Escape",
            "escape": "Escape",
            "return": "Enter",
            "enter": "Enter",
            "space": "Space",
            "tab": "Tab",
            "left": "ArrowLeft",
            "right": "ArrowRight",
            "up": "ArrowUp",
            "down": "ArrowDown",
            "slash": "/",
            "question": "?",
        }
        if kl in named:
            key_out = named[kl]
        elif kl.startswith("f") and kl[1:].isdigit():
            key_out = "F" + kl[1:]
        else:
            key_out = key[0].upper() + key[1:] if key else key
    if key_out == "/" and not mods_sorted:
        # bare ? often Shift+/ - keep "?" as alias
        pass
    return "+".join(mods_sorted + [key_out]) if mods_sorted else key_out


def _windows_map() -> dict[str, str]:
    panes = PANE_ORDER[:8]  # Alt+1..8
    m = {aid: f"Alt+{i}" for i, aid in enumerate(panes, 1)}
    m["pane.guide"] = "Alt+9"
    m["pane.refresh"] = "F5"
    m["pane.prev"] = "Alt+ArrowLeft"
    m["pane.next"] = "Alt+ArrowRight"
    m["focus.filter"] = "Alt+F"
    m["context.new"] = "Alt+N"
    m["ui.help"] = "?"
    m["ui.cancel"] = "Escape"
    m["floor.toggleAgg"] = "Alt+A"
    m["floor.toggleMapTimeline"] = "Alt+M"
    m["mail.next"] = "Alt+]"
    m["mail.prev"] = "Alt+["
    m["mail.open"] = "Alt+O"
    m["mail.markRead"] = "Alt+R"
    m["profile.cycle"] = "Alt+`"
    return m


def _brief_map() -> dict[str, str]:
    # Brief: Alt+letter muscle memory
    return {
        "pane.session": "Alt+S",
        "pane.floor": "Alt+L",
        "pane.jobs": "Alt+J",
        "pane.score": "Alt+C",
        "pane.mail": "Alt+E",
        "pane.plan": "Alt+P",
        "pane.admin": "Alt+D",
        "pane.wire": "Alt+W",
        "pane.guide": "Alt+G",
        "pane.prev": "Alt+-",
        "pane.next": "Alt+=",
        "pane.refresh": "Alt+U",
        "focus.filter": "Alt+F",
        "context.new": "Alt+N",
        "ui.help": "Alt+H",
        "ui.cancel": "Escape",
        "floor.toggleAgg": "Alt+A",
        "floor.toggleMapTimeline": "Alt+T",
        "mail.next": "Alt+.",
        "mail.prev": "Alt+,",
        "mail.open": "Alt+O",
        "mail.markRead": "Alt+R",
        "profile.cycle": "Alt+`",
    }


def _emacs_map() -> dict[str, str]:
    # stubs: C-g cancel; C-x b buffer stub -> focus.filter; number chords for panes
    return {
        "pane.session": "Ctrl+X 1",
        "pane.floor": "Ctrl+X 2",
        "pane.jobs": "Ctrl+X 3",
        "pane.score": "Ctrl+X 4",
        "pane.mail": "Ctrl+X 5",
        "pane.plan": "Ctrl+X 6",
        "pane.admin": "Ctrl+X 7",
        "pane.wire": "Ctrl+X 8",
        "pane.guide": "Ctrl+X 9",
        "pane.prev": "Ctrl+X Left",
        "pane.next": "Ctrl+X Right",
        "pane.refresh": "Ctrl+X R",
        "focus.filter": "Ctrl+X B",
        "context.new": "Ctrl+X N",
        "ui.help": "Ctrl+H K",
        "ui.cancel": "Ctrl+G",
        "floor.toggleAgg": "Ctrl+X A",
        "floor.toggleMapTimeline": "Ctrl+X M",
        "mail.next": "Ctrl+X ]",
        "mail.prev": "Ctrl+X [",
        "mail.open": "Ctrl+X O",
        "mail.markRead": "Ctrl+X U",
        "profile.cycle": "Ctrl+X P",
    }


def _vscode_like(cursor: bool = False) -> dict[str, str]:
    m = {
        "pane.session": "Ctrl+1",
        "pane.floor": "Ctrl+2",
        "pane.jobs": "Ctrl+3",
        "pane.score": "Ctrl+4",
        "pane.mail": "Ctrl+5",
        "pane.plan": "Ctrl+6",
        "pane.admin": "Ctrl+7",
        "pane.wire": "Ctrl+8",
        "pane.guide": "Ctrl+9",
        "pane.prev": "Ctrl+PageUp",
        "pane.next": "Ctrl+PageDown",
        "pane.refresh": "Ctrl+R",
        "focus.filter": "Ctrl+Shift+F",
        "context.new": "Ctrl+Shift+N",  # not Ctrl+N (browser)
        "ui.help": "Ctrl+Shift+P",  # palette
        "ui.cancel": "Escape",
        "floor.toggleAgg": "Ctrl+Shift+A",
        "floor.toggleMapTimeline": "Ctrl+Shift+M",
        "mail.next": "Alt+Down",
        "mail.prev": "Alt+Up",
        "mail.open": "Enter",
        "mail.markRead": "Ctrl+Shift+U",
        "profile.cycle": "Ctrl+Shift+`",
    }
    # palette also on Ctrl+P (vscode/cursor)
    m["context.new"] = "Ctrl+Shift+N"
    # use Ctrl+P as help/palette entry (not a second action collision - map focus to Shift+P already)
    # Actually: vscode Ctrl+P = quick open; we use as ui.help palette
    m["ui.help"] = "Ctrl+P"
    if cursor:
        # cursor avoid Ctrl/Cmd+L - do not bind L chords
        # (no Ctrl+L in map already; keep it that way)
        pass
    return m


def _bot_build_map() -> dict[str, str]:
    # bare letters when not typing
    return {
        "pane.session": "s",
        "pane.floor": "f",
        "pane.jobs": "j",
        "pane.score": "c",
        "pane.mail": "m",
        "pane.plan": "p",
        "pane.admin": "a",
        "pane.wire": "w",
        "pane.guide": "g",
        "pane.prev": "[",
        "pane.next": "]",
        "pane.refresh": "r",
        "focus.filter": "/",
        "context.new": "n",
        "ui.help": "?",
        "ui.cancel": "Escape",
        "floor.toggleAgg": "v",
        "floor.toggleMapTimeline": "t",
        "mail.next": "j",  # wait - j is jobs; use . and ,
        "mail.prev": ",",
        "mail.open": "o",
        "mail.markRead": "u",
        "profile.cycle": "`",
    }


def _fix_bot_build_conflicts(m: dict[str, str]) -> dict[str, str]:
    """mail.next was colliding with pane.jobs on 'j' - use '.' for mail.next."""
    out = dict(m)
    out["mail.next"] = "."
    return out


PROFILE_MAPS: dict[str, dict[str, str]] = {
    "windows": {k: normalize_chord(v) for k, v in _windows_map().items()},
    "brief": {k: normalize_chord(v) for k, v in _brief_map().items()},
    "emacs": {k: normalize_chord(v) for k, v in _emacs_map().items()},
    "vscode": {k: normalize_chord(v) for k, v in _vscode_like(False).items()},
    "cursor": {k: normalize_chord(v) for k, v in _vscode_like(True).items()},
    "bot": {k: normalize_chord(v) for k, v in _fix_bot_build_conflicts(_bot_build_map()).items()},
    "build": {k: normalize_chord(v) for k, v in _fix_bot_build_conflicts(_bot_build_map()).items()},
}


def storage_key(desk_id: str) -> str:
    d = (desk_id or "").strip() or "anon"
    return f"wall-keys:{d}"


def profile_map(profile: str) -> dict[str, str]:
    p = (profile or DEFAULT_PROFILE).strip().lower()
    if p not in PROFILE_MAPS:
        p = DEFAULT_PROFILE
    return deepcopy(PROFILE_MAPS[p])


def load_state(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    profile = str(raw.get("profile") or DEFAULT_PROFILE).strip().lower()
    if profile not in PROFILES:
        profile = DEFAULT_PROFILE
    overrides_in = raw.get("overrides") or {}
    overrides: dict[str, str] = {}
    if isinstance(overrides_in, dict):
        for k, v in overrides_in.items():
            aid = str(k).strip()
            if aid not in ACTION_IDS:
                continue
            ch = normalize_chord(str(v))
            if ch:
                overrides[aid] = ch
    return {"profile": profile, "overrides": overrides}


def effective_map(state: dict[str, Any] | None) -> dict[str, str]:
    st = load_state(state)
    base = profile_map(st["profile"])
    for aid, ch in st["overrides"].items():
        base[aid] = ch
    return base


def invert_map(action_to_chord: dict[str, str]) -> dict[str, list[str]]:
    inv: dict[str, list[str]] = {}
    for aid, ch in action_to_chord.items():
        if not ch:
            continue
        inv.setdefault(ch, []).append(aid)
    return inv


def find_conflicts(action_to_chord: dict[str, str]) -> list[dict[str, Any]]:
    inv = invert_map(action_to_chord)
    out = []
    for ch, aids in sorted(inv.items()):
        if len(aids) > 1:
            out.append({"chord": ch, "actions": sorted(aids)})
    return out


def set_override(
    state: dict[str, Any] | None,
    action_id: str,
    chord: str,
    *,
    confirm_clobber: bool = False,
) -> dict[str, Any]:
    """Set one override. Raises ValueError on conflict unless confirm_clobber."""
    aid = str(action_id).strip()
    if aid not in ACTION_IDS:
        raise ValueError(f"unknown action: {aid}")
    ch = normalize_chord(chord)
    if not ch:
        raise ValueError("empty chord")
    if ch in BROWSER_RESERVED or ch.replace("Meta+", "Cmd+") in BROWSER_RESERVED:
        raise ValueError(f"browser-reserved chord: {ch}")
    # cursor profile default must not use Ctrl/Cmd+L - also block as override? allow customize but warn
    st = load_state(state)
    trial = dict(st["overrides"])
    trial[aid] = ch
    eff = effective_map({"profile": st["profile"], "overrides": trial})
    conflicts = [c for c in find_conflicts(eff) if aid in c["actions"]]
    if conflicts and not confirm_clobber:
        raise ValueError(
            "chord conflict: "
            + "; ".join(f"{c['chord']} -> {','.join(c['actions'])}" for c in conflicts)
        )
    st["overrides"] = trial
    return st


def reset_action(state: dict[str, Any] | None, action_id: str) -> dict[str, Any]:
    st = load_state(state)
    st["overrides"].pop(str(action_id).strip(), None)
    return st


def reset_all(state: dict[str, Any] | None) -> dict[str, Any]:
    st = load_state(state)
    st["overrides"] = {}
    return st


def set_profile(state: dict[str, Any] | None, profile: str, *, keep_overrides: bool = True) -> dict[str, Any]:
    st = load_state(state)
    p = str(profile or DEFAULT_PROFILE).strip().lower()
    if p not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    st["profile"] = p
    if not keep_overrides:
        st["overrides"] = {}
    return st


def cycle_profile(state: dict[str, Any] | None) -> dict[str, Any]:
    st = load_state(state)
    i = PROFILES.index(st["profile"]) if st["profile"] in PROFILES else 0
    st["profile"] = PROFILES[(i + 1) % len(PROFILES)]
    return st


def cursor_defaults_avoid_ctrl_l() -> bool:
    m = PROFILE_MAPS["cursor"]
    bad = {"Ctrl+L", "Meta+L", "Cmd+L"}
    return not any(v in bad for v in m.values())


def keys_contract() -> dict[str, Any]:
    return {
        "path": "A",
        "schema_migrated": False,
        "default_profile": DEFAULT_PROFILE,
        "profiles": list(PROFILES),
        "action_ids": list(ACTION_IDS),
        "storage_key_prefix": "wall-keys:",
        "browser_reserved": sorted(BROWSER_RESERVED),
        "cursor_avoids_ctrl_l": cursor_defaults_avoid_ctrl_l(),
    }
