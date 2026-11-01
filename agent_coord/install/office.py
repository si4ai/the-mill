"""Stand up the office. Consultative init. Does not mint a session token."""

from __future__ import annotations

import getpass
import os
import re
import sys
from pathlib import Path
from typing import Any

import mysql.connector

from agent_coord.config import DEFAULTS, config_path, save_config, settings
from agent_coord.install.migrate import ensure

_DB = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_BRIEFINGS = (
    "bootstrap",
    "host",
    "join",
    "human",
    "usecases",
    "commands",
    "skill",
    "howto-ai",
    "spawn",
    "route",
    "connect",
    "improve",
    "tree",
)
_BRIEFING_PATH = {
    "bootstrap": ("docs", "install", "HOST.md"),
    "host": ("docs", "install", "HOST.md"),
    "human": ("README.md",),
    "join": ("docs", "JOIN.md"),
    "usecases": ("docs", "protocol", "usecases.md"),
    "commands": ("docs", "protocol", "commands.md"),
    "skill": ("docs", "protocol", "skill.md"),
    "howto-ai": ("docs", "protocol", "howto-ai.md"),
    "spawn": ("docs", "protocol", "spawn.md"),
    "route": ("docs", "protocol", "route.md"),
    "connect": ("docs", "protocol", "connect.md"),
    "improve": ("docs", "protocol", "improve.md"),
    "tree": ("docs", "protocol", "tree.md"),
}
_BRIEFING_H2 = {
    "human": "Human",
}


def _share_candidates() -> list[Path]:
    """Data-file prefixes pip may have used: env prefix, user (--user), base, package-relative."""
    import site
    import sysconfig

    roots: list[Path] = []

    def _add(p: str | Path | None) -> None:
        if p:
            path = Path(p)
            if path not in roots:
                roots.append(path)

    _add(sys.prefix)
    # pip install --user (or a user fallback when site-packages is read-only):
    # data-files land under the user base, not sys.prefix.
    try:
        scheme = sysconfig.get_preferred_scheme("user")  # 3.10+
    except Exception:
        scheme = "nt_user" if os.name == "nt" else "posix_user"
    try:
        _add(sysconfig.get_path("data", scheme))
    except Exception:
        pass
    try:
        _add(site.getuserbase())
    except Exception:
        pass
    _add(getattr(sys, "base_prefix", ""))
    # <prefix>/lib/pythonX.Y/site-packages/agent_coord or <prefix>/Lib/site-packages/agent_coord
    pkg = Path(__file__).resolve().parents[1]
    for up in (3, 2):
        try:
            _add(pkg.parents[up])
        except IndexError:
            pass
    return [r / "share" / "the-mill" for r in roots]


def mill_root() -> Path:
    """Git checkout, else pip share/the-mill (wheel data-files; env or user install)."""
    here = Path(__file__).resolve()
    git = here.parents[2]
    if (git / "docs" / "protocol" / "commands.md").is_file():
        return git
    for share in _share_candidates():
        if (share / "docs" / "protocol" / "commands.md").is_file():
            return share
    raise FileNotFoundError("docs not found: git docs/protocol or share/the-mill (prefix or user base)")


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def markdown_tty(text: str) -> str:
    """Terminal mill briefing: headings, tables, skip mermaid fences."""
    out: list[str] = []
    in_fence = False
    mermaid = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            mermaid = in_fence and "mermaid" in line[3:].lower()
            if mermaid:
                out.append("  (mermaid - mill briefing KIND in GitLab)")
            continue
        if in_fence:
            if not mermaid:
                out.append("    " + line)
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            out.extend(["", title, "=" * min(72, max(3, len(title))), ""])
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            out.extend(["", title, "-" * min(72, max(3, len(title)))])
            continue
        if line.startswith("### "):
            out.append(line[4:].strip())
            continue
        if line.startswith("|"):
            if set(line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                continue
            cells = [c.strip().replace("**", "") for c in line.strip().strip("|").split("|")]
            out.append("  " + " | ".join(cells))
            continue
        line = _MD_LINK.sub(r"\1", line).replace("**", "")
        out.append(line)
    body = "\n".join(out)
    while "\n\n\n" in body:
        body = body.replace("\n\n\n", "\n\n")
    return body.strip() + "\n"


def mill_briefing_index() -> str:
    lines = ["mill briefing KIND", ""]
    for name in _BRIEFINGS:
        path = "/".join(_BRIEFING_PATH[name])
        lines.append(f"  {name:<12} {path}")
    lines.append("")
    lines.append("mill briefing is local printout. Not mill-wall. Not mill connect.")
    return "\n".join(lines) + "\n"


def mill_markdown(*parts: str) -> Path:
    p = mill_root().joinpath(*parts)
    if not p.is_file():
        raise FileNotFoundError("/".join(parts))
    return p


def markdown_h2_section(text: str, heading: str) -> str:
    """Slice `## heading` through the next `## `."""
    want = (heading or "").strip().lower()
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("## ") and ln[3:].strip().lower() == want),
        None,
    )
    if start is None:
        return text
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).rstrip() + "\n"


def help_text(command: str = "") -> str:
    """mill help: docs/protocol/cli-desk.md; mill help COMMAND: that command's rows in cli-*.md."""
    files = ("cli-desk.md", "cli-admin.md", "cli-install.md")
    want = (command or "").strip().lower()
    if not want:
        return markdown_tty(mill_markdown("docs", "protocol", "cli-desk.md").read_text(encoding="utf-8"))
    hits: list[str] = []
    for name in files:
        try:
            text = mill_markdown("docs", "protocol", name).read_text(encoding="utf-8")
        except OSError:
            continue
        for ln in text.splitlines():
            if ln.startswith("|") and ("`mill " + want + " " in ln or "`mill " + want + "`" in ln):
                hits.append(ln)
    if not hits:
        text = commands_text(want)
        return help_unknown(want) if "# unknown command" in text else text
    return "\n".join(["# mill " + want, "", "| command | CLI | what |", "|---|---|---|", *hits, ""]) + "\n"


_HELP_SYNONYMS = {"tag": "label", "tags": "label", "team": "roster", "project": "roster", "message": "send", "mail": "send", "task": "todo"}


def help_unknown(want: str) -> str:
    """One line for mill help <unknown>: the closest command, not the full doc."""
    import difflib

    words: set[str] = set()
    for name in ("cli-desk.md", "cli-admin.md", "cli-install.md"):
        try:
            words |= set(re.findall(r"`mill ([a-z][a-z-]*)", mill_markdown("docs", "protocol", name).read_text(encoding="utf-8")))
        except OSError:
            continue
    near = _HELP_SYNONYMS.get(want) or next(iter(difflib.get_close_matches(want, sorted(words), n=1)), "")
    tail = f"; closest: mill help {near}" if near else "; mill help lists every command"
    return f"mill help: no such topic {want!r}{tail}\n"


def commands_text(command: str = "") -> str:
    """docs/protocol/commands.md - mill help / mill briefing commands."""
    path = mill_markdown("docs", "protocol", "commands.md")
    text = path.read_text(encoding="utf-8")
    want = (command or "").strip().lower()
    if not want:
        return markdown_tty(text)
    aliases = {"needs": "todo", "ask": "open", "volunteer": "claim"}
    want = aliases.get(want, want)
    lines = text.splitlines()
    hit = [ln for ln in lines if ln.startswith("| **`") and f"**`{want}`**" in ln]
    if not hit:
        return text + f"\n\n# unknown command {want!r} - full list above\n"
    hdr = next((ln for ln in lines if ln.startswith("| command ")), "| command | intent | CALL |")
    sep = "|---|---|---|"
    return "\n".join(["# mill " + want, "", hdr, sep, *hit, ""]) + "\n"


def db_ident(name: str) -> str:
    s = (name or "").strip()
    if not _DB.match(s):
        raise ValueError(f"bad database name: {name!r}")
    return s


def briefing_text(kind: str = "") -> str:
    name = (kind or "").strip().lower()
    if not name:
        return mill_briefing_index()
    if name not in _BRIEFING_PATH:
        raise ValueError(f"briefing must be one of {', '.join(_BRIEFINGS)}")
    if name == "commands":
        return commands_text()
    text = mill_markdown(*_BRIEFING_PATH[name]).read_text(encoding="utf-8")
    h2 = _BRIEFING_H2.get(name)
    if h2:
        text = markdown_h2_section(text, h2)
    return markdown_tty(text)


def _ask(label: str, default: str, *, secret: bool = False) -> str:
    hint = f" [{default}]" if default else ""
    prompt = f"{label}{hint}: "
    if secret:
        raw = getpass.getpass(prompt)
    else:
        raw = input(prompt)
    return (raw or "").strip() or default


def gather(
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    database: str | None = None,
    node: str | None = None,
    dashboard_bind: str | None = None,
    dashboard_port: int | None = None,
    lan: bool = False,
    prompt: bool = False,
) -> dict[str, Any]:
    s = settings()
    from agent_coord.server.netbind import preferred_office_host

    host_default = host or s["host"] or DEFAULTS["host"]
    if not host and str(host_default) in ("127.0.0.1", "localhost", ""):
        host_default = preferred_office_host()
    data = {
        "host": host_default,
        "port": int(port if port is not None else s["port"]),
        "user": user or s["user"] or DEFAULTS["user"],
        "password": password if password is not None else s["password"],
        "database": database or s["database"] or DEFAULTS["database"],
        "node": node if node is not None else (s.get("node") or ""),
        "dashboard_bind": dashboard_bind
        or ("0.0.0.0" if lan else s["dashboard_bind"] or DEFAULTS["dashboard_bind"]),
        "dashboard_port": int(
            dashboard_port if dashboard_port is not None else s["dashboard_port"]
        ),
    }
    if prompt and sys.stdin.isatty():
        print("Standing up the factory office. Enter accepts the default.")
        print("Session tokens are NOT created here. Clock in later with presence.")
        data["host"] = _ask("MySQL host", str(data["host"]))
        data["port"] = int(_ask("MySQL port", str(data["port"])))
        data["user"] = _ask("MySQL user", str(data["user"]))
        data["password"] = _ask("MySQL password", str(data["password"]), secret=True)
        data["database"] = _ask("Database name", str(data["database"]))
        data["node"] = _ask("Node name (blank = hostname)", str(data["node"] or ""))
        bind_default = "0.0.0.0" if lan else str(data["dashboard_bind"])
        data["dashboard_bind"] = _ask(
            "Wall bind (127.0.0.1 this machine, 0.0.0.0 office LAN)",
            bind_default,
        )
        data["dashboard_port"] = int(_ask("Wall port (nginx TLS or mill-wall)", str(data["dashboard_port"])))
    db_ident(str(data["database"]))
    return data


def init_office(
    data: dict[str, Any],
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create DB, migrate, write config. Return status with no token field."""
    database = db_ident(str(data["database"]))
    bind = str(data.get("dashboard_bind") or "127.0.0.1")
    port = int(data.get("dashboard_port") or 8765)
    warnings: list[str] = []
    if str(data.get("password") or "") in ("", "root"):
        warnings.append(
            "DB password is the local-dev default; change it if other machines can reach MySQL"
        )
    if bind in ("0.0.0.0", "::"):
        warnings.append("wall will listen on all interfaces; only do this on a private LAN")
    else:
        warnings.append("wall is localhost-only; other desks need --lan (or bind 0.0.0.0)")
    warnings.append("records and wall are OS services; do not serve them from a coding-agent chat")

    server = dict(
        host=data["host"],
        port=int(data["port"]),
        user=data["user"],
        password=data["password"],
        connection_timeout=10,
        autocommit=True,
    )
    try:
        cn = mysql.connector.connect(**server)
    except mysql.connector.Error as e:
        raise RuntimeError(
            f"cannot reach MySQL at {data['host']}:{data['port']} as {data['user']}: {e}"
        ) from e
    try:
        cur = cn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
        )
        cur.close()
    finally:
        cn.close()

    office = dict(server)
    office["database"] = database
    office["autocommit"] = False
    cn = mysql.connector.connect(**office)
    try:
        mig = ensure(cn)
    finally:
        cn.close()

    cfg = {
        "host": data["host"],
        "port": int(data["port"]),
        "user": data["user"],
        "password": data["password"],
        "database": database,
        "node": data.get("node") or "",
        "dashboard_bind": bind,
        "dashboard_port": port,
        "door": str(data.get("door") or "path"),
    }
    written = save_config(cfg, path or config_path())
    dash = (
        "https://127.0.0.1/"
        if bind in ("127.0.0.1", "localhost")
        else f"https://{bind}/"
    )
    next_steps = [
        "Records must already be an OS database service (mysqld). init only creates the schema.",
        "Install the wall as an OS web service: mill install wall --apply",
        "Do not keep `mill wall` running in this chat.",
        f"Humans open the wall: {dash}",
        "Sibling mill reads ~/.mill/session/<owner>.token (do not paste the token)",
        "Other agents: mill briefing join",
        "Do not treat the config file as a login token",
    ]

    invite_info = {}
    who = str(data.get("admin") or data.get("owner") or "installer")
    try:
        from agent_coord.server.admin.door import ensure_ootb_invite

        invite_info = ensure_ootb_invite(created_by=who)
        link = invite_info.get("invite_path") or "/?invite=<token>"
        if invite_info.get("token"):
            full = dash.rstrip("/") + link if link.startswith("/") else link
            next_steps.insert(
                3,
                f"Human Wall door (browser invite-key, admin={who}): {full}",
            )
            next_steps.insert(4, "Door stays path until you run: mill invite --door invite")
        else:
            next_steps.insert(3, f"Invite key board ready (active keys present); admin={who}")
    except Exception as e:
        warnings.append(f"ootb invite skipped: {e}")

    # Host desk welcome link for agent join (#253).
    seat_info: dict = {}
    try:
        from agent_coord.server.admin.door import _db
        from agent_coord.server.admin.seats import mint_seat

        cn = _db()
        if cn is not None:
            try:
                seat_info = mint_seat(
                    cn,
                    desk=who,
                    project=str(data.get("project") or "the-mill"),
                    created_by=who,
                    mill_url=dash.rstrip("/"),
                )
                wel = str(seat_info.get("invite_url") or "")
                if wel:
                    next_steps.insert(
                        3,
                        f"Host desk welcome link (holds the seat secret; save it to a file, then mill join --office <alias> --link-file PATH): {wel}",
                    )
            finally:
                try:
                    cn.close()
                except Exception:
                    pass
    except Exception as e:
        warnings.append(f"host seat welcome skipped: {e}")

    return {
        "ok": True,
        "config_path": str(written),
        "database": database,
        "host": data["host"],
        "schema_version": mig.get("version"),
        "migrations_applied": mig.get("applied") or [],
        "dashboard": dash,
        "dashboard_bind": bind,
        "warnings": warnings,
        "next": next_steps,
        "invite": invite_info,
        "seat_welcome": seat_info,
        "invite_link": (
            (dash.rstrip("/") + invite_info["invite_path"])
            if invite_info.get("token") and invite_info.get("invite_path")
            else None
        ),
        "admin": invite_info.get("admin") or "installer",
    }
