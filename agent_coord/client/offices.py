"""Local multi-mill layout. One host directory per Wall. Aliases are local names.

.mill/active                 last alias used
.mill/alias/<name>           host key
.mill/<host>/ca.crt
.mill/<host>/url
.mill/<host>/active          last desk on that host
.mill/<host>/<DESK>/token    bearer token, mode 0600

No .mill/active file means the legacy single office (~/.mill/session, config mill_url).
The alias is not sent to the Wall.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

_ALIAS = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HOST = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")

_explicit = ""
_explicit_host = ""


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address((host or "").split("%", 1)[0])
    except ValueError:
        return False
    return True


def looks_like_host(spec: str) -> bool:
    """IP, localhost, or a DNS name. A project name such as the-mill is not a host."""
    key = host_key(spec)
    if not key:
        return False
    host = key.split(":", 1)[0]
    if host == "localhost" or _is_ip(host):
        return True
    return "." in host


def prefer_dns(spec: str, *, dest: Path | None = None) -> str:
    """Keep a DNS name. An IP is replaced when a known DNS name resolves to it."""
    key = host_key(spec)
    if not key:
        return ""
    host = key.split(":", 1)[0]
    if not _is_ip(host):
        return key
    for candidate in _known_dns_names(dest=dest):
        try:
            if socket.gethostbyname(candidate) == host:
                return candidate
        except OSError:
            continue
    return key


def bind_cli_host(spec: str, *, dest: Path | None = None) -> None:
    """Direct Wall host for this process. DNS wins over an IP when both match."""
    global _explicit_host
    _explicit_host = prefer_dns(spec, dest=dest) if (spec or "").strip() else ""


def bind_cli_office(name: str) -> None:
    """Office flag for this process. Empty leaves the legacy home in charge."""
    global _explicit
    _explicit = (name or "").strip()


def cli_office() -> str:
    """--office on this process argv. Empty when only the sticky alias is set."""
    return _explicit


def current_office(*, dest: Path | None = None) -> str:
    """Explicit --office, else .mill/active when that file exists."""
    if _explicit:
        return _explicit
    return read_global_active(dest=dest)


def pull_office_flag(argv: list[str]) -> tuple[str, list[str]]:
    """Pull --office from anywhere in argv so it works before or after the command."""
    office = ""
    out: list[str] = []
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == "--office" and i + 1 < len(argv):
            office = argv[i + 1]
            i += 2
            continue
        if item.startswith("--office="):
            office = item.split("=", 1)[1]
            i += 1
            continue
        out.append(item)
        i += 1
    return office.strip(), out


def host_key(url: str) -> str:
    """Wall URL or host -> directory key. Default port 443 is omitted."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or ".." in host:
        return ""
    port = parsed.port
    key = host if not port or port == 443 else f"{host}:{port}"
    if not _HOST.match(key):
        return ""
    return key


def origin_url(url: str) -> str:
    key = host_key(url)
    if not key:
        return ""
    return "https://" + key


def _home(dest: Path | None) -> Path:
    from agent_coord.client.tokens import mill_home

    return mill_home(dest)


def _lock(path: Path, *, is_dir: bool = False) -> None:
    from agent_coord.client.tokens import _restrict_owner_only

    _restrict_owner_only(path, is_dir=is_dir)


def _alias_path(name: str, *, dest: Path | None = None) -> Path:
    if not _ALIAS.match(name or ""):
        raise ValueError("bad office alias")
    return _home(dest) / "alias" / name


def write_alias(name: str, host: str, *, dest: Path | None = None) -> Path:
    key = host_key(host) or (host if _HOST.match(host or "") else "")
    if not key:
        raise ValueError("bad office host")
    existing = read_alias(name, dest=dest)
    if existing and existing != key:
        old = existing.split(":", 1)[0]
        new = key.split(":", 1)[0]
        if not (_is_ip(old) and not _is_ip(new)):
            raise ValueError(f"office {name} already points at {existing}")
    path = _alias_path(name, dest=dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, key + "\n")
    return path


def list_aliases(*, dest: Path | None = None) -> list[dict[str, str | bool]]:
    """Local alias files. Does not call the wall or open the book."""
    root = _home(dest) / "alias"
    active = read_global_active(dest=dest)
    rows: list[dict[str, str | bool]] = []
    if not root.is_dir():
        return rows
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or not _ALIAS.match(path.name):
            continue
        try:
            host = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        url = read_host_url(host, dest=dest) if host else ""
        rows.append(
            {
                "name": path.name,
                "host": host,
                "url": url,
                "active": path.name == active,
            }
        )
    return rows


def local_servers(*, dest: Path | None = None) -> list[dict[str, str | bool | list[str]]]:
    """One row per server. Aliases are local names for that DNS name or IP."""
    grouped: dict[str, dict[str, str | bool | list[str]]] = {}
    for row in list_aliases(dest=dest):
        host = str(row["host"] or "")
        if not host:
            continue
        bucket = grouped.get(host)
        if bucket is None:
            bucket = {"host": host, "url": str(row["url"] or ""), "aliases": [], "active": False}
            grouped[host] = bucket
        aliases = bucket["aliases"]
        assert isinstance(aliases, list)
        aliases.append(str(row["name"]))
        if row["url"]:
            bucket["url"] = str(row["url"])
        if row["active"]:
            bucket["active"] = True
    return sorted(grouped.values(), key=lambda item: str(item["host"]).casefold())


def read_alias(name: str, *, dest: Path | None = None) -> str:
    if not name or not _ALIAS.match(name):
        return ""
    try:
        return _alias_path(name, dest=dest).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_global_active(*, dest: Path | None = None) -> str:
    try:
        return (_home(dest) / "active").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_global_active(name: str, *, dest: Path | None = None) -> Path:
    if not _ALIAS.match(name or ""):
        raise ValueError("bad office alias")
    if not read_alias(name, dest=dest):
        raise ValueError(f"unknown office {name}")
    path = _home(dest) / "active"
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, name + "\n")
    return path


def current_host_key(*, dest: Path | None = None) -> str:
    """Host key for the selected office. Empty when this process is on the legacy home."""
    if _explicit_host:
        return prefer_dns(_explicit_host, dest=dest)
    name = current_office(dest=dest)
    if not name:
        return ""
    if looks_like_host(name):
        return prefer_dns(name, dest=dest)
    host = read_alias(name, dest=dest)
    if not host:
        raise ValueError(f"unknown office {name}")
    return prefer_dns(host, dest=dest)


def _known_dns_names(*, dest: Path | None = None) -> list[str]:
    names: list[str] = []
    root = _home(dest) / "alias"
    if root.is_dir():
        for path in root.iterdir():
            if not path.is_file():
                continue
            try:
                target = path.read_text(encoding="utf-8").strip().split(":", 1)[0]
            except OSError:
                continue
            if target and not _is_ip(target):
                names.append(target)
    home = _home(dest)
    if home.is_dir():
        for path in home.iterdir():
            if path.is_dir() and "." in path.name and not _is_ip(path.name.split(":", 1)[0]):
                names.append(path.name.split(":", 1)[0])
    return names


def desk_local_file(desk: str, leaf: str, *, dest: Path | None = None) -> Path | None:
    """File under the selected host and desk. None means use the legacy session folder."""
    host = current_host_key(dest=dest)
    if not host:
        return None
    from agent_coord.helpers.ident import desk as slug_desk

    who = slug_desk(desk)
    path = host_dir(host, dest=dest) / who / leaf
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def host_dir(host: str, *, dest: Path | None = None) -> Path:
    key = host if _HOST.match(host or "") else host_key(host)
    if not key:
        raise ValueError("bad office host")
    return _home(dest) / key


def write_host_url(host: str, url: str, *, dest: Path | None = None) -> Path:
    path = host_dir(host, dest=dest) / "url"
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, origin_url(url) + "\n")
    return path


def read_host_url(host: str, *, dest: Path | None = None) -> str:
    try:
        text = (host_dir(host, dest=dest) / "url").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        text = ""
    return text or ("https://" + host if _HOST.match(host or "") else "")


def ca_path(host: str, *, dest: Path | None = None) -> Path:
    return host_dir(host, dest=dest) / "ca.crt"


def write_host_invite(host: str, token: str, *, dest: Path | None = None) -> Path:
    """Door invite for later mill commands. Owner-only. Not sent as the desk bearer."""
    path = host_dir(host, dest=dest) / "invite"
    path.parent.mkdir(parents=True, exist_ok=True)
    _lock(path.parent, is_dir=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text((token or "").strip() + "\n", encoding="utf-8")
    _lock(tmp, is_dir=False)
    os.replace(tmp, path)
    _lock(path, is_dir=False)
    return path


def read_host_invite(host: str, *, dest: Path | None = None) -> str:
    try:
        return (host_dir(host, dest=dest) / "invite").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def write_legacy_invite(token: str, *, dest: Path | None = None) -> Path:
    path = _home(dest) / "invite"
    path.parent.mkdir(parents=True, exist_ok=True)
    _lock(path.parent, is_dir=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text((token or "").strip() + "\n", encoding="utf-8")
    _lock(tmp, is_dir=False)
    os.replace(tmp, path)
    _lock(path, is_dir=False)
    return path


def read_office_invite(*, dest: Path | None = None) -> str:
    """Invite saved for the selected office, or the legacy home when no office is selected."""
    host = current_host_key(dest=dest)
    if host:
        return read_host_invite(host, dest=dest)
    try:
        return (_home(dest) / "invite").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def write_host_active(host: str, desk: str, *, dest: Path | None = None) -> Path:
    """Legacy per-host desk pointer. Commands must not use this as the sender."""
    path = host_dir(host, dest=dest) / "active"
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, desk + "\n")
    return path


def read_host_active(host: str, *, dest: Path | None = None) -> str:
    """Legacy per-host desk pointer. Commands must not read this to choose a sender."""
    try:
        return (host_dir(host, dest=dest) / "active").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def desk_token_path(host: str, desk: str, *, dest: Path | None = None) -> Path:
    from agent_coord.helpers.ident import desk as slug_desk

    who = slug_desk(desk)
    if not _ALIAS.match(who):
        raise ValueError("bad desk")
    return host_dir(host, dest=dest) / who / "token"


def write_desk_token(owner: str, token: str, *, host: str, dest: Path | None = None) -> Path:
    tok = (token or "").strip()
    if not tok:
        raise ValueError("session token empty")
    path = desk_token_path(host, owner, dest=dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    _lock(path.parent, is_dir=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(tok + "\n", encoding="utf-8")
    _lock(tmp, is_dir=False)
    os.replace(tmp, path)
    _lock(path, is_dir=False)
    return path


def read_desk_token(owner: str, *, host: str, dest: Path | None = None) -> str:
    try:
        return desk_token_path(host, owner, dest=dest).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def write_seat_project(owner: str, project: str, *, host: str, dest: Path | None = None) -> Path | None:
    """Remember the project this seat joined, so connect can fill it in (#249)."""
    name = (project or "").strip()
    if not name:
        return None
    path = desk_token_path(host, owner, dest=dest).with_name("project")
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace(path, name + "\n")
    return path


def read_seat_project(owner: str, *, host: str, dest: Path | None = None) -> str:
    try:
        path = desk_token_path(host, owner, dest=dest).with_name("project")
        return path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def project_on_url(url: str) -> str:
    """project= on a welcome or join URL. Empty when the seat did not say."""
    from urllib.parse import parse_qs, urlsplit

    got = parse_qs(urlsplit(url or "").query).get("project") or []
    return (got[0] if got else "").strip()


def next_connect_line(office: str, project: str, desk: str) -> str:
    """The copyable line a cold seat runs after join (#249). Empty if desk is unknown.

    0.7.x: connect DESK joins the Office roster, so the line names only the desk.
    """
    office_s = (office or "").strip()
    desk_s = (desk or "").strip()
    if not desk_s:
        return ""
    mill = f"mill --office {office_s}" if office_s else "mill"
    # Every command runs with its own connect in one line (0.7.x).
    return f"next: bash -c '{mill} connect {desk_s} >/dev/null 2>&1 & trap \"kill $!\" EXIT; {mill} inbox'"


LINK_ON_ARGV = (
    "join: the welcome link carries the seat secret, so it never goes on the command line "
    "(process list, shell history, transcripts). Save the file mill invite writes, then "
    "run: mill join --link-file PATH. To pipe it, run: mill join --link-stdin"
)


def looks_like_link(text: str) -> bool:
    """True for anything that may be a welcome or invite link (#620): a scheme, a query or a seat."""
    t = str(text or "").strip().strip("'\"").lower()
    return bool(t) and ("://" in t or "?" in t or "seat=" in t or "/welcome" in t or "invite=" in t)


def read_link(path: str, stdin=None) -> str:
    """The one welcome link from a file or stdin (#620). ValueError never holds the link."""
    if stdin is not None:
        raw = stdin.read(16384)
        where = "stdin"
    else:
        try:
            raw = Path(path).expanduser().read_text(encoding="utf-8-sig")[:16384]
        except OSError as e:
            raise ValueError(f"join: could not read the link file ({e.strerror or type(e).__name__})") from None
        where = "the link file"
    lines = [ln.strip().strip("'\"").strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ValueError(f"join: {where} is empty; it holds the one welcome link mill invite wrote")
    if len(lines) > 1:
        raise ValueError(f"join: {where} must hold one line, the welcome link")
    return lines[0]


def alias_from_link(link: str) -> str:
    """Default office alias for mill join: the welcome link's host. Empty if none."""
    from urllib.parse import urlparse

    try:
        host = (urlparse((link or "").strip()).hostname or "").strip().lower()
    except ValueError:
        return ""
    return host if _ALIAS.match(host) else ""


def office_mill_url(*, dest: Path | None = None) -> str:
    """https origin for the selected office, or empty when legacy."""
    host = current_host_key(dest=dest)
    if not host:
        return ""
    return read_host_url(host, dest=dest)


def office_ca_file(*, dest: Path | None = None) -> Path | None:
    """CA path for the selected office, or None when legacy."""
    host = current_host_key(dest=dest)
    if not host:
        return None
    return ca_path(host, dest=dest)


def is_welcome_link(url: str) -> bool:
    """True when URL is a seat welcome link with desk and seat (#253)."""
    from urllib.parse import urlsplit

    from agent_coord.client.http import desk_on_url, seat_on_url

    text = (url or "").strip()
    if not text:
        return False
    if "://" not in text:
        text = "https://" + text
    path = (urlsplit(text).path or "").rstrip("/")
    if path != "/welcome":
        return False
    return bool(desk_on_url(text) and seat_on_url(text))


def is_invite_key_link(url: str) -> bool:
    """True when URL is the browser invite-key door /?invite=KEY (#253)."""
    from agent_coord.client.http import invite_on_url

    return bool(invite_on_url(url)) and not is_welcome_link(url)


def join_office(
    url: str,
    office: str,
    *,
    dest: Path | None = None,
) -> dict:
    """Point a local alias at a Wall from one seat welcome link (#253).

    Parses desk, seat, project, and CA pem from the URL. Does not take flag
    overrides. invite-key and bare path doors are refused here.
    """
    from agent_coord.client.http import (
        desk_on_url,
        materialize_mill_ca,
        pem_on_url,
        seat_on_url,
    )

    if is_invite_key_link(url):
        return {
            "ok": False,
            "error": (
                "join: invite-key is the Wall browser door; "
                "use a seat welcome link https://<wall>/welcome?desk=&seat=&project="
            ),
        }
    if not is_welcome_link(url):
        return {
            "ok": False,
            "error": (
                "join: need a seat welcome link "
                "https://<wall>/welcome?desk=&seat=&project="
            ),
        }
    if not _ALIAS.match(office or ""):
        return {"ok": False, "error": "join: --office <alias> required"}

    key = prefer_dns(url, dest=dest)
    if not key:
        return {"ok": False, "error": "need a wall URL and an office alias"}
    try:
        write_alias(office, key, dest=dest)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "office": office}
    origin = "https://" + key
    write_host_url(key, origin, dest=dest)

    who = desk_on_url(url)
    tok = seat_on_url(url)
    project = project_on_url(url)
    ca_pem = pem_on_url(url)
    if not ca_pem:
        return {
            "ok": False,
            "office": office,
            "host": key,
            "mill_url": origin,
            "error": "join: welcome link needs pem= (CA); remint the seat",
        }
    ca = materialize_mill_ca(ca_pem, dest=ca_path(key, dest=dest))
    if ca is None:
        return {
            "ok": False,
            "office": office,
            "host": key,
            "mill_url": origin,
            "error": "join: pem= on the welcome link is not a CA certificate",
        }
    trust = ["received mill CA"]
    note = "Received the mill CA. It was not installed in the OS trust store."
    try:
        write_desk_token(who, tok, host=key, dest=dest)
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "office": office,
            "host": key,
            "mill_url": origin,
            "ca": str(ca),
            "trust": trust,
            "error": "seat token was not stored",
            "note": str(exc),
        }
    if not project:
        try:
            from agent_coord.const import CONST_OFFICE
            from agent_coord.client.http import mill_http_call

            row = mill_http_call(
                {
                    "verb": "join",
                    "cmd": "join",
                    "project": CONST_OFFICE,
                    "placeholder": True,
                    "owner": who,
                    "token": tok,
                }
            )
        except Exception:
            row = None
        if isinstance(row, dict):
            from agent_coord.const import CONST_OFFICE

            gid = str(row.get("group_id") or row.get("project") or "").strip()
            if gid == CONST_OFFICE:
                gid = ""
            if gid:
                project = gid
    if project:
        try:
            write_seat_project(who, project, host=key, dest=dest)
        except (OSError, ValueError):
            pass
    try:
        from agent_coord.install.host import installed_skill_md

        skill = installed_skill_md()
    except Exception:
        skill = ""
    if skill:
        note = note + " skill " + skill
    line = next_connect_line(office, project, who)
    out = {
        "ok": True,
        "office": office,
        "host": key,
        "mill_url": origin,
        "ca": str(ca),
        "trust": trust,
        "skill": skill,
        "desk": who or None,
        "project": project or None,
        "note": "alias is local. mill connect --office uses this host. The default mill home was not changed. " + note,
    }
    if line:
        out["next"] = line
    return out


def _replace(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
