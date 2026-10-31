"""One notice when this pack is older than the office mill field (card 923)."""
from __future__ import annotations

import re
from typing import Any

_RELEASE = re.compile(r"^\d+(?:\.\d+)*$")
_LINE = "this mill client is older than the office ({client} < {office}): pip install -U the-mill"

_said = False


def reset_older_once() -> None:
    """Test hook. A process says the notice at most once."""
    global _said
    _said = False


def release_key(text: str) -> tuple[int, ...] | None:
    """Dotted integers only. Anything else is not comparable."""
    raw = (text or "").strip()
    if not _RELEASE.fullmatch(raw):
        return None
    return tuple(int(part) for part in raw.split("."))


def _older(client: tuple[int, ...], office: tuple[int, ...]) -> bool:
    width = max(len(client), len(office))
    left = client + (0,) * (width - len(client))
    right = office + (0,) * (width - len(office))
    return left < right


def older_client_line(client: str, office: str) -> str:
    """Warning text, or empty when the client is not an older dotted release."""
    client_key = release_key(client)
    office_key = release_key(office)
    if client_key is None or office_key is None or not _older(client_key, office_key):
        return ""
    return _LINE.format(client=client.strip(), office=office.strip())


def _office_mill(row: dict[str, Any]) -> str:
    mill = row.get("mill")
    if isinstance(mill, str) and mill.strip():
        return mill
    hint = row.get("hint")
    if isinstance(hint, dict):
        nested = hint.get("mill")
        if isinstance(nested, str) and nested.strip():
            return nested
    return ""


def attach_older_once(row: dict[str, Any], *, client: str | None = None) -> dict[str, Any]:
    """Copy row with ``older`` the first time this process should say so.

    Later calls return the same row. A match, a newer client, a missing
    office field, or a version that is not dotted numbers stays quiet.
    """
    global _said
    if _said or not isinstance(row, dict) or row.get("older"):
        return row
    office = _office_mill(row)
    if not office:
        return row
    if client is None:
        from agent_coord.install.packver import package_version

        client = package_version()
    text = older_client_line(client, office)
    if not text:
        return row
    _said = True
    out = dict(row)
    out["older"] = text
    return out
