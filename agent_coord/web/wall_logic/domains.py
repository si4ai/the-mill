"""Default-pack domain folders (mail/score/floor) - fungible cut 5.

SoR inventory for Path A thin JS modules under `wall_ui/default/{mail,score,floor}/`.
Board loads them as a thin shell; packs override domain files without whole-board forks.

See wall-contract; wall_logic/domains.py
wall-contract; wall_logic/domains.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BOARD_EQUIVALENT_MARKER = "WALL_UI_DEFAULT_DOMAINS"
DOMAIN_IDS = ("mail", "score", "floor", "todo")


def wall_ui_root() -> Path:
    return Path(__file__).resolve().parent.parent / "wall_ui"


def default_pack_dir() -> Path:
    return wall_ui_root() / "default"


def domain_dir(domain: str) -> Path:
    return default_pack_dir() / domain


def domain_js_name(domain: str) -> str:
    return f"{domain}.js"


def domain_script_src(domain: str) -> str:
    """Site-root URL board.html / lazy loader use (nested under default pack).

    Leading slash so Nest paths (/project|/station|/role) do not
    resolve domain scripts as /project/mail/mail.js (404).
    """
    return f"/{domain}/{domain}.js"


def domain_paths() -> dict[str, dict[str, Path]]:
    out: dict[str, dict[str, Path]] = {}
    for d in DOMAIN_IDS:
        base = domain_dir(d)
        out[d] = {
            "dir": base,
            "js": base / domain_js_name(d),
        }
    return out


def domain_markers() -> dict[str, str]:
    return {
        "mail": "WALL_UI_DEFAULT_MAIL",
        "score": "WALL_UI_DEFAULT_SCORE",
        "floor": "WALL_UI_DEFAULT_FLOOR",
        "todo": "WALL_UI_DEFAULT_TODO",
        "pack": BOARD_EQUIVALENT_MARKER,
    }


def domains_contract() -> dict[str, Any]:
    paths = domain_paths()
    markers = domain_markers()
    return {
        "marker": BOARD_EQUIVALENT_MARKER,
        "path": "A",
        "domains": list(DOMAIN_IDS),
        "script_srcs": [domain_script_src(d) for d in DOMAIN_IDS],
        "markers": markers,
        "paths_exist": {
            d: {k: v.is_file() if k != "dir" else v.is_dir() for k, v in paths[d].items()}
            for d in DOMAIN_IDS
        },
        "pure": True,
        "wired_board": True,
        "enables_pack_override_without_whole_board_fork": True,
    }
