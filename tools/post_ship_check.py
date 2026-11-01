"""One post-ship check: tag, pack bytes, and office health (card 962)."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

Fetch = Callable[[str, bool], tuple[int, dict[str, str], bytes]]
Git = Callable[[list[str]], tuple[int, str]]

_PACK_SUFFIXES = (".whl", ".tar.gz")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def live_fetch(url: str, redirects: bool) -> tuple[int, dict[str, str], bytes]:
    opener = urllib.request.build_opener() if redirects else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, method="GET")
    try:
        with opener.open(req, timeout=30) as resp:
            headers = {k: v for k, v in resp.headers.items()}
            return int(resp.status), headers, resp.read()
    except urllib.error.HTTPError as exc:
        headers = {k: v for k, v in exc.headers.items()} if exc.headers else {}
        body = exc.read() if exc.fp is not None else b""
        return int(exc.code), headers, body


def live_git(args: list[str]) -> tuple[int, str]:
    git = shutil.which("git")
    if not git:
        return 127, ""
    proc = subprocess.run(
        [git, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, (proc.stdout or "").strip()


def check_tag(tag: str, sha: str, git: Git) -> str | None:
    want = sha.strip().lower()
    name = tag.strip()
    if not name or not want:
        return "tag and sha are required"
    code, out = git(["rev-parse", "--verify", f"{name}^{{commit}}"])
    got = out.splitlines()[-1].strip().lower() if out else ""
    if code != 0 or not got:
        return f"tag {name} does not resolve"
    if got != want:
        return f"tag {name} points at {got}, not {want}"
    return None


def _pack_files(gate: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    if not gate.is_dir():
        return found
    for path in sorted(gate.iterdir()):
        if path.is_file() and path.name.endswith(_PACK_SUFFIXES):
            found[path.name] = path.read_bytes()
    return found


def check_packs(version: str, gate: Path, fetch: Fetch) -> list[str]:
    local = _pack_files(gate)
    if not local:
        return ["gate build has no pack files"]
    listing = f"https://pypi.org/pypi/the-mill/{version.strip()}/json"
    try:
        status, _headers, body = fetch(listing, True)
    except OSError as exc:
        return [f"pypi fetch failed: {type(exc).__name__}"]
    if status != 200:
        return [f"pypi status {status}"]
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return ["pypi listing is not json"]
    remote: dict[str, str] = {}
    for item in data.get("urls") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or "")
        file_url = str(item.get("url") or "")
        if name.endswith(_PACK_SUFFIXES) and file_url:
            remote[name] = file_url
    misses: list[str] = []
    for name in sorted(set(local) | set(remote)):
        if name not in remote:
            misses.append(f"pypi has no {name}")
            continue
        if name not in local:
            misses.append(f"pypi has extra {name}")
            continue
        try:
            status, _headers, body = fetch(remote[name], True)
        except OSError as exc:
            misses.append(f"pypi {name} fetch failed: {type(exc).__name__}")
            continue
        if status != 200:
            misses.append(f"pypi {name} status {status}")
            continue
        if body != local[name]:
            misses.append(f"pypi {name} differs from the gate build")
    return misses


def health_target(office: str) -> tuple[str, str | None]:
    raw = office.strip()
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return raw, None
    url = urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))
    return parts.netloc, url


def _version_header(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if str(key).lower() == "x-mill-version":
            return str(value).strip()
    return ""


def check_health(offices: list[str], version: str, fetch: Fetch) -> list[str]:
    if not offices:
        return ["no office given"]
    want = version.strip()
    misses: list[str] = []
    for office in offices:
        label, url = health_target(office)
        if url is None:
            misses.append(f"health {label} is not a url")
            continue
        try:
            status, headers, body = fetch(url, False)
        except OSError as exc:
            misses.append(f"health {label} fetch failed: {type(exc).__name__}")
            continue
        if status != 200:
            misses.append(f"health {label} status {status}")
            continue
        got = _version_header(headers)
        if got != want:
            misses.append(f"health {label} version {got or 'none'} != {want}")
            continue
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            misses.append(f"health {label} body is not json")
            continue
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            misses.append(f"health {label} is not ok")
    return misses


def run_checks(
    *,
    tag: str,
    sha: str,
    version: str,
    gate: Path,
    offices: list[str],
    fetch: Fetch,
    git: Git,
) -> list[str]:
    misses: list[str] = []
    tag_miss = check_tag(tag, sha, git)
    if tag_miss:
        misses.append(tag_miss)
    misses.extend(check_packs(version, gate, fetch))
    misses.extend(check_health(offices, version, fetch))
    return misses


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="check a ship after the tag is cut")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--office", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    misses = run_checks(
        tag=args.tag,
        sha=args.sha,
        version=args.version,
        gate=args.gate,
        offices=list(args.office),
        fetch=live_fetch,
        git=live_git,
    )
    if args.json:
        print(json.dumps({"ok": not misses, "misses": misses}))
    elif misses:
        print("\n".join(misses))
    else:
        print("ok")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
