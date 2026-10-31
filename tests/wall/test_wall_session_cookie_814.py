# -*- coding: utf-8 -*-
"""The Wall human session stays in the HttpOnly door cookie (card 814).

Javascript must not name the storage key, build it by concatenation, pull a
session token from another storage key, or omit credentials on the invite
fetches that rely on the door cookie.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WALL = REPO / "agent_coord" / "web" / "wall_ui"
KEY = "factory-human-token"
TEXT = {".js", ".html"}

# Invite / seat posts that must ride the door cookie (F224).
_INVITE_FETCH = re.compile(
    r"""fetch\s*\(\s*["']/api/admin/invites["']""",
    re.MULTILINE,
)
_CREDENTIALS_OMIT = re.compile(
    r"""credentials\s*:\s*["']omit["']""",
    re.IGNORECASE,
)
# "factory-" + "human-token" / 'factory-human' + '-token' / template pieces.
_KEY_CONCAT = re.compile(
    r"""["']factory-["']\s*\+|"""
    r"""["']factory-human["']\s*\+|"""
    r"""\+\s*["']human-token["']|"""
    r"""\+\s*["']-token["']|"""
    r"""["']factory-["']\s*\+\s*["']human["']""",
    re.IGNORECASE,
)
# localStorage/sessionStorage read whose result is treated as a session token.
_OTHER_STORAGE_TOKEN = re.compile(
    r"""(?:"""
    # token = ... getItem("not-the-human-name-key")
    r"""\btoken\b\s*=\s*(?:await\s+)?(?:localStorage|sessionStorage)\.getItem\s*\(\s*["'](?!factory-human["'])[^"']+["']"""
    r"""|"""
    # getItem("...") ... Authorization / Bearer / .token
    r"""(?:localStorage|sessionStorage)\.getItem\s*\(\s*["'](?!factory-human["'])[^"']+["']\s*\)"""
    r"""[^;\n]{0,160}(?:\bAuthorization\b|\bBearer\b|\.token\b)"""
    r""")""",
    re.IGNORECASE,
)


def scan_text(text: str) -> list[str]:
    """Return issue kinds found in one source text."""
    hits: list[str] = []
    if KEY in text:
        hits.append("literal-key")
    if _KEY_CONCAT.search(text):
        hits.append("concatenated-key")
    if _OTHER_STORAGE_TOKEN.search(text):
        hits.append("other-storage-token")
    # credentials: "omit" only counts on invite fetches in the same file.
    if _INVITE_FETCH.search(text) and _CREDENTIALS_OMIT.search(text):
        hits.append("credentials-omit")
    # also flag an invite fetch that sets credentials omit inside its options
    for m in _INVITE_FETCH.finditer(text):
        window = text[m.start() : m.start() + 400]
        if _CREDENTIALS_OMIT.search(window):
            if "credentials-omit" not in hits:
                hits.append("credentials-omit")
    return hits


def _scan_tree(root: Path) -> list[str]:
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT or "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        kinds = scan_text(text)
        if kinds:
            rel = path.relative_to(root).as_posix()
            out.append(f"{rel}: {', '.join(kinds)}")
    return out


def test_wall_scripts_do_not_name_the_human_session_key():
    hits = _scan_tree(WALL)
    assert not hits, "human session leaks in javascript-readable Wall source:\n" + "\n".join(hits)


def test_detector_flags_the_storage_key(tmp_path):
    probe = tmp_path / "wall_ui" / "default"
    probe.mkdir(parents=True)
    (probe / "bad.js").write_text(
        'token = localStorage.getItem("factory-human-token") || "";\n',
        encoding="utf-8",
    )
    hits = _scan_tree(tmp_path / "wall_ui")
    assert hits, "detector must call the scanner and flag the literal key"
    assert any("literal-key" in h for h in hits), hits


def test_detector_flags_concatenated_key(tmp_path):
    probe = tmp_path / "wall_ui" / "default"
    probe.mkdir(parents=True)
    (probe / "concat.js").write_text(
        'const k = "factory-" + "human-token"; localStorage.getItem(k);\n',
        encoding="utf-8",
    )
    hits = _scan_tree(tmp_path / "wall_ui")
    assert any("concatenated-key" in h for h in hits), hits


def test_detector_flags_token_from_other_storage_key(tmp_path):
    probe = tmp_path / "wall_ui" / "default"
    probe.mkdir(parents=True)
    (probe / "other.js").write_text(
        'const token = localStorage.getItem("factory-session"); '
        'headers.Authorization = "Bearer " + token;\n',
        encoding="utf-8",
    )
    hits = _scan_tree(tmp_path / "wall_ui")
    assert any("other-storage-token" in h for h in hits), hits


def test_detector_flags_credentials_omit_on_invite_fetch(tmp_path):
    probe = tmp_path / "wall_ui" / "default"
    probe.mkdir(parents=True)
    (probe / "omit.js").write_text(
        'await fetch("/api/admin/invites", { method: "POST", credentials: "omit", '
        'body: "{}" });\n',
        encoding="utf-8",
    )
    hits = _scan_tree(tmp_path / "wall_ui")
    assert any("credentials-omit" in h for h in hits), hits
