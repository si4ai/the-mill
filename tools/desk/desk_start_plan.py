"""Plan a desk-start launch from an office config. No hardcoded desks/paths.

Source for Grok argv: workstation ``grok --help`` (grok 1.0.70 stable).
Usage: ``grok [OPTIONS] [PROMPT] [COMMAND]`` - [PROMPT] is the initial
interactive prompt. Fresh start uses ``-s`` (new UUID), never ``-r``/``-c``/
``--fork-session``/``-p``. Permission mode defaults to ``default``;
``bypassPermissions`` only when config sets ``allow_bypass_permissions``.
``office.launch_mode`` is ``dashboard`` (default; sessions attach to the
shared Grok leader so they appear in ``grok dashboard``) or ``window``
(one interactive process per desk). The exact dashboard attach recipe is
UNVERIFIED until the owner probe in the runbook passes.
``defaults.context_restart_tokens`` (default 190000) is printed in the plan;
the desk asks for a fresh desk-start near that count (operator/desk enforced;
never resume, never compact). ``lessons_byte_cap`` / ``lessons_count_cap`` are
enforced by ``select_lessons`` when the planner assembles lessons; the PS1
launcher does not assemble lessons (template or HANDOFF.md + handoff_char_cap).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

DESK_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,62}$")
FORBIDDEN_GROK_FLAGS = frozenset(
    {"-r", "--resume", "-c", "--continue", "-p", "--single", "--fork-session"}
)
HELP_SOURCE = "workstation grok --help (grok 1.0.70 stable)"
SAFE_PERMISSION_MODES = frozenset(
    {"default", "acceptEdits", "auto", "dontAsk", "plan"}
)
# bypassPermissions only when allow_bypass_permissions is true in config.


class ConfigError(ValueError):
    """Invalid or incomplete desk-start config."""


def new_session_id() -> str:
    return str(uuid.uuid4())


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ConfigError(f"desk-start: config file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"desk-start: config is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError("desk-start: config root must be an object")
    return validate_config(data)


def validate_config(data: dict[str, Any]) -> dict[str, Any]:
    office = data.get("office")
    if not isinstance(office, dict):
        raise ConfigError("desk-start: missing office object")
    for key in ("mill_office", "mill_connect_template"):
        if not str(office.get(key) or "").strip():
            raise ConfigError(f"desk-start: office.{key} is required")
    if "export_before_restart" not in office:
        office["export_before_restart"] = True
    elif not isinstance(office["export_before_restart"], bool):
        raise ConfigError("desk-start: office.export_before_restart must be a boolean")
    mode = str(office.get("launch_mode") or "dashboard").strip().lower()
    if mode not in {"dashboard", "window"}:
        raise ConfigError(
            "desk-start: office.launch_mode must be 'dashboard' or 'window'"
        )
    office["launch_mode"] = mode
    office.setdefault("leader_socket", "")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("desk-start: defaults must be an object when present")
    defaults.setdefault("permission_mode", "default")
    defaults.setdefault("allow_bypass_permissions", False)
    defaults.setdefault("lessons_byte_cap", 12_000)
    defaults.setdefault("lessons_count_cap", 25)
    defaults.setdefault("handoff_char_cap", 1_500)
    defaults.setdefault("context_restart_tokens", 190_000)
    defaults.setdefault(
        "first_message_template",
        (
            "desk {desk} on office {mill_office}. learn-label {lessons_label}. "
            "load only the mill-desk skill (not mill-build-assist). "
            "run `mill --office {mill_office} todo --mine` and do open work; "
            "do not read the mail backlog or scan the board. "
            "then sit: `mill --office {mill_office} connect-wait {desk}` in the FOREGROUND "
            "(never background, never &, never a separate mill connect). "
            "on a hint: read that letter first; work letter -> do it, reply, sit again; "
            "status note -> mark, sit again; stop letter -> stay down; dropped socket -> sit again. "
            "never two sits. human chat wins over mail. after crash/resume, read inbox before sitting. "
            "near {context_restart_tokens} tokens: write learn-{desk}, open work, and a handoff, "
            "then ask for a fresh desk-start (never resume, never compact)."
        ),
    )
    if not isinstance(defaults["allow_bypass_permissions"], bool):
        raise ConfigError("desk-start: defaults.allow_bypass_permissions must be a boolean")

    desks = data.get("desks")
    if not isinstance(desks, list) or not desks:
        raise ConfigError("desk-start: desks must be a non-empty array")
    names: set[str] = set()
    for i, d in enumerate(desks):
        if not isinstance(d, dict):
            raise ConfigError(f"desk-start: desks[{i}] must be an object")
        name = str(d.get("name") or "").strip()
        if not name or not DESK_NAME_RE.match(name):
            raise ConfigError(f"desk-start: desks[{i}].name is missing or invalid")
        if name in names:
            raise ConfigError(f"desk-start: duplicate desk name {name!r}")
        names.add(name)
        for req in ("work_dir", "export_dir", "credential_target"):
            if not str(d.get(req) or "").strip():
                raise ConfigError(f"desk-start: desks[{i}] ({name}): {req} is required")
        # Writes only under work_dir parent / export_dir - refuse empty.
        add_dirs = d.get("add_dirs") or []
        if add_dirs is not None and not isinstance(add_dirs, list):
            raise ConfigError(f"desk-start: desks[{i}] ({name}): add_dirs must be an array")
        d.setdefault("lessons_label", "")
        d.setdefault("lessons_byte_cap", defaults["lessons_byte_cap"])
        d.setdefault("lessons_count_cap", defaults["lessons_count_cap"])
        d.setdefault("permission_mode", defaults["permission_mode"])
        d.setdefault(
            "context_restart_tokens",
            defaults["context_restart_tokens"],
        )
        d.setdefault(
            "first_message_template",
            defaults["first_message_template"],
        )
        d.setdefault("model", "")
        d.setdefault("reasoning_effort", "")
        d.setdefault("agent_file", "")
        d.setdefault("handoff_letter_id", None)
        d.setdefault("handoff_query", "")
        d.setdefault("add_dirs", [])
    data["office"] = office
    data["defaults"] = defaults
    data["desks"] = desks
    return data


def resolve_desks(config: dict[str, Any], desk_args: list[str]) -> list[dict[str, Any]]:
    by_name = {d["name"]: d for d in config["desks"]}
    if not desk_args:
        raise ConfigError("desk-start: pass -Desk <name> at least once (or -Desk all)")
    if any(a.lower() == "all" for a in desk_args):
        if len(desk_args) > 1:
            raise ConfigError("desk-start: -Desk all cannot be combined with other names")
        return list(config["desks"])
    out: list[dict[str, Any]] = []
    for name in desk_args:
        if name not in by_name:
            known = ", ".join(sorted(by_name))
            raise ConfigError(f"desk-start: unknown desk {name!r}; known: {known}")
        out.append(by_name[name])
    return out


def render_template(template: str, **fields: Any) -> str:
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return str(template).format_map(_Safe(**{k: ("" if v is None else v) for k, v in fields.items()}))


def select_lessons(
    lessons: list[dict[str, Any]],
    *,
    count_cap: int,
    byte_cap: int,
) -> list[dict[str, Any]]:
    def _key(row: dict[str, Any]) -> tuple:
        return (int(row.get("id") or 0), str(row.get("created") or ""))

    ordered = sorted(lessons, key=_key, reverse=True)
    out: list[dict[str, Any]] = []
    used = 0
    for row in ordered:
        body = str(row.get("body") or "")
        n = len(body.encode("utf-8"))
        if len(out) >= count_cap:
            break
        if used + n > byte_cap and out:
            break
        out.append(row)
        used += n
    return out


def build_handoff_text(
    *,
    template: str,
    desk: str,
    fields: dict[str, Any],
    cards: list[dict[str, Any]],
    letters: list[dict[str, Any]],
    holds: list[str],
    dont: list[str],
    char_cap: int,
    stale: bool = False,
    mirror_time: str = "",
) -> str:
    """Build handoff. Drop oldest flexible lines first. Never drop a card id
    or do-not-touch line; if protected lines alone exceed the cap, keep them
    all and append ``more: todo --mine`` only when something flexible was cut.
    """
    prefix: list[str] = []
    if stale:
        prefix.append(
            f"STALE mirror {mirror_time}; mill unreachable; "
            "read-only: no claim, pass or reply until the mill answers"
        )
    body = render_template(template, desk=desk, **fields).strip()
    body_lines = body.splitlines() if body else []
    card_lines: list[str] = []
    for c in cards:
        cid = c.get("id")
        need = c.get("need_id") or c.get("need") or ""
        pr = c.get("pr") or ""
        status = c.get("status") or ""
        bit = f"card {cid} {need} {status}".strip()
        if pr:
            bit += f" pr {pr}"
        card_lines.append(bit)
    flexible: list[str] = []
    for letter in letters:
        lid = letter.get("id")
        gist = (letter.get("gist") or letter.get("body") or "").replace("\n", " ")[:80]
        flexible.append(f"letter {lid} {gist}".rstrip())
    for h in holds:
        flexible.append(f"hold {h}")
    # Non-desk/STALE template lines that are not protected join flexible,
    # except the leading desk line which stays with prefix.
    for ln in body_lines:
        if ln.startswith("desk ") or ln.startswith("STALE "):
            if ln not in prefix:
                prefix.append(ln)
        else:
            flexible.append(ln)
    dont_lines = [f"do-not-touch {d}" for d in dont]

    def _join(parts: list[str]) -> str:
        return "\n".join(p for p in parts if p is not None)

    protected = prefix + card_lines + dont_lines
    # Drop oldest flexible first.
    while flexible and len(_join(protected + flexible)) > char_cap:
        flexible.pop(0)
    text = _join(protected + flexible)
    if len(text) <= char_cap:
        return text
    # Protected alone is over the soft cap: keep every card id and dont line.
    text = _join(protected)
    if flexible:
        text = text + "\nmore: todo --mine"
    return text



def resolve_permission_mode(
    desk: dict[str, Any], defaults: dict[str, Any]
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    mode = str(desk.get("permission_mode") or defaults.get("permission_mode") or "default")
    allow_bypass = bool(defaults.get("allow_bypass_permissions"))
    if mode == "bypassPermissions":
        if not allow_bypass:
            raise ConfigError(
                "desk-start: permission_mode bypassPermissions refused "
                "(set defaults.allow_bypass_permissions true to allow; not recommended)"
            )
        warnings.append(
            "warning: allow_bypass_permissions is set; launching with bypassPermissions"
        )
        return mode, warnings
    if mode not in SAFE_PERMISSION_MODES:
        raise ConfigError(
            f"desk-start: permission_mode {mode!r} is not allowed; "
            f"use one of {sorted(SAFE_PERMISSION_MODES)} or bypassPermissions with allow flag"
        )
    return mode, warnings


def build_argv(
    handoff: str,
    *,
    work_dir: str,
    session_id: str,
    agent_file: str = "",
    model: str = "",
    reasoning_effort: str = "",
    permission_mode: str = "default",
    add_dirs: list[str] | None = None,
) -> list[str]:
    argv: list[str] = ["grok", "--cwd", work_dir]
    if agent_file:
        argv.extend(["--agent", agent_file])
    for d in add_dirs or []:
        if d:
            argv.extend(["--add-dir", d])
    if model:
        argv.extend(["-m", model])
    if reasoning_effort:
        argv.extend(["--reasoning-effort", reasoning_effort])
    if permission_mode and permission_mode != "default":
        argv.extend(["--permission-mode", permission_mode])
    argv.extend(["-s", session_id])
    argv.append(handoff)
    for flag in FORBIDDEN_GROK_FLAGS:
        if flag in argv:
            raise AssertionError(f"forbidden grok flag leaked into argv: {flag}")
    return argv


def export_argv(session_id: str, out_path: str) -> list[str]:
    return ["grok", "export", session_id, out_path]


def plan_desk(
    config: dict[str, Any],
    desk: dict[str, Any],
    *,
    dry_run: bool = True,
    seat_busy: bool = False,
    mill_ok: bool = True,
    mirror_exists: bool = True,
    cred_present: bool = True,
    lessons: list[dict[str, Any]] | None = None,
    cards: list[dict[str, Any]] | None = None,
    letters: list[dict[str, Any]] | None = None,
    holds: list[str] | None = None,
    dont: list[str] | None = None,
    mirror_time: str = "",
    prior_session_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    office = config["office"]
    defaults = config["defaults"]
    name = desk["name"]
    sid = session_id or new_session_id()
    mode, warnings = resolve_permission_mode(desk, defaults)
    target = str(desk["credential_target"])
    work_dir = str(desk["work_dir"])
    export_dir = str(desk["export_dir"])
    char_cap = int(defaults.get("handoff_char_cap") or 1500)

    connect_cmd = render_template(
        office["mill_connect_template"],
        mill_office=office.get("mill_office", ""),
        roster=office.get("roster", ""),
        desk=name,
    )

    out: dict[str, Any] = {
        "desk": name,
        "dry_run": bool(dry_run),
        "help_source": HELP_SOURCE,
        "office": {
            "mill_office": office.get("mill_office"),
            "roster": office.get("roster"),
            "export_before_restart": office.get("export_before_restart", True),
        },
        "mill_connect": connect_cmd,
        "credential": {"where": "Credential Manager", "target": target},
        "forbidden_flags": sorted(FORBIDDEN_GROK_FLAGS),
        "launch": "positional-prompt",
        "launch_mode": str(office.get("launch_mode") or "dashboard"),
        "launch_note": (
            f"grok [OPTIONS] [PROMPT] per {HELP_SOURCE}; -s new UUID; "
            "never -r/-c/--fork-session/-p"
        ),
        "permission_mode": mode,
        "warnings": warnings,
        "session_id": sid,
        "outcome": "ok",
        "argv": [],
        "export_argv": [],
        "handoff": "",
        "work_dir": work_dir,
        "export_dir": export_dir,
        "writes_allowed": [work_dir, export_dir],
        "env_clear": ["PYTHONPATH"],
        "lessons_label": desk.get("lessons_label") or "",
        "lessons_kept": 0,
        "lessons_byte_cap": int(desk.get("lessons_byte_cap") or defaults["lessons_byte_cap"]),
        "lessons_count_cap": int(desk.get("lessons_count_cap") or defaults["lessons_count_cap"]),
        "context_restart_tokens": int(
            desk.get("context_restart_tokens")
            if desk.get("context_restart_tokens") is not None
            else defaults.get("context_restart_tokens") or 190_000
        ),
        "handoff_letter_id": desk.get("handoff_letter_id"),
        "handoff_query": desk.get("handoff_query") or "",
    }
    if not cred_present:
        out["outcome"] = "refuse"
        out["reason"] = (
            f"credential (Credential Manager target {target}) missing"
        )
        return out
    if seat_busy:
        out["outcome"] = "refuse"
        out["reason"] = "seat busy; refuse (never --take)"
        return out
    if not mill_ok and not mirror_exists:
        out["outcome"] = "refuse"
        out["reason"] = "mill unreachable and no mirror; fail closed"
        return out

    stale = not mill_ok and mirror_exists
    kept = select_lessons(
        lessons or [],
        count_cap=out["lessons_count_cap"],
        byte_cap=out["lessons_byte_cap"],
    )
    out["lessons_kept"] = len(kept)
    fields = {
        "lessons_label": out["lessons_label"],
        "mill_office": office.get("mill_office", ""),
        "roster": office.get("roster", ""),
        "context_restart_tokens": out["context_restart_tokens"],
    }
    handoff = build_handoff_text(
        template=str(desk.get("first_message_template") or defaults["first_message_template"]),
        desk=name,
        fields=fields,
        cards=cards or [],
        letters=letters or [],
        holds=holds or [],
        dont=dont or [],
        char_cap=char_cap,
        stale=stale,
        mirror_time=mirror_time,
    )
    out["handoff"] = handoff
    out["handoff_chars"] = len(handoff)

    if prior_session_id and office.get("export_before_restart", True):
        export_path = str(Path(export_dir) / f"{prior_session_id}.md")
        out["export_argv"] = export_argv(prior_session_id, export_path)
        out["export_path"] = export_path
        out["export_note"] = "export prior session to Markdown; keep the old session (never delete)"

    launch_mode = str(office.get("launch_mode") or "dashboard")
    leader_socket = str(office.get("leader_socket") or "")
    out["launch_mode"] = launch_mode
    out["leader_socket"] = leader_socket or None
    window_argv = build_argv(
        handoff,
        work_dir=work_dir,
        session_id=sid,
        agent_file=str(desk.get("agent_file") or ""),
        model=str(desk.get("model") or ""),
        reasoning_effort=str(desk.get("reasoning_effort") or ""),
        permission_mode=mode,
        add_dirs=list(desk.get("add_dirs") or []),
    )
    out["window_argv"] = window_argv
    if launch_mode == "window":
        out["argv"] = window_argv
        out["attach_status"] = "verified-window"
        out["attach_note"] = (
            "window mode: one interactive grok process per desk "
            "(grok --cwd ... -s <uuid> <PROMPT>)"
        )
    else:
        # dashboard: attach to shared leader. Exact recipe UNVERIFIED on this
        # host until runbook step 0 probe passes (grok 1.0.70: grok dashboard,
        # grok leader list/info, grok agent --leader / --no-leader,
        # [cli] use_leader, GROK_AGENT_DASHBOARD, --leader-socket).
        out["argv"] = []
        out["attach_status"] = "UNVERIFIED"
        out["attach_note"] = (
            "dashboard mode: attach each desk session to the shared Grok leader "
            "so it appears in `grok dashboard`. Exact attach argv is UNVERIFIED; "
            "run the owner-approved probe (runbook step 0) before a real restart. "
            "window_argv holds the fallback one-window launch."
        )
        out["probe_hint"] = {
            "leader_list": ["grok", "leader", "list"],
            "dashboard": ["grok", "dashboard"],
            "notes": [
                "default leader socket ~/.grok/leader.sock; named ~/.grok/leader-*.sock",
                "custom via --leader-socket; grok agent --leader connects to shared leader",
                "[cli] use_leader in config.toml; --no-leader overrides; GROK_AGENT_DASHBOARD=0 disables UI",
            ],
        }
    # session.json sits beside work_dir (desk folder), not outside.
    out["session_record"] = str(Path(work_dir).parent / "session.json")
    if dry_run:
        out["would_launch"] = True
        out["launched"] = False
    return out


def plan(
    *,
    config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
    desks: list[str] | None = None,
    dry_run: bool = True,
    **per_desk_kwargs: Any,
) -> dict[str, Any]:
    """Plan one or more desks. Returns {plans: [...]} or a single plan when one desk."""
    if config is None:
        if not config_path:
            raise ConfigError("desk-start: config_path or config is required")
        config = load_config(config_path)
    else:
        config = validate_config(dict(config))
    chosen = resolve_desks(config, desks or [])
    plans = [plan_desk(config, d, dry_run=dry_run, **per_desk_kwargs) for d in chosen]
    if len(plans) == 1:
        return plans[0]
    return {"plans": plans, "count": len(plans), "dry_run": dry_run}


def plan_to_json(plan_dict: dict[str, Any]) -> str:
    return json.dumps(plan_dict, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="desk-start plan (dry-run JSON; no launch)")
    p.add_argument("--config", required=True, help="path to desks.json (outside the repo)")
    p.add_argument("--desk", action="append", default=[], help="desk name; repeat or pass all")
    p.add_argument("--seat-busy", action="store_true")
    p.add_argument("--no-cred", action="store_true")
    p.add_argument("--mill-down", action="store_true")
    p.add_argument("--no-mirror", action="store_true")
    p.add_argument("--prior-session", default="")
    p.add_argument("--session-id", default="")
    args = p.parse_args()
    try:
        result = plan(
            config_path=args.config,
            desks=args.desk or ["all"],
            dry_run=True,
            seat_busy=args.seat_busy,
            mill_ok=not args.mill_down,
            mirror_exists=not args.no_mirror,
            cred_present=not args.no_cred,
            prior_session_id=args.prior_session or None,
            session_id=args.session_id or None,
        )
    except ConfigError as e:
        raise SystemExit(str(e)) from e
    print(plan_to_json(result), end="")
