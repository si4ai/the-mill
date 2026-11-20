"""mill -h lists only wall commands the server handles (#234)."""
from __future__ import annotations

import io
import re
import sys

from agent_coord.__main__ import main
from agent_coord.client.outbound import WALL, canonical_command
from agent_coord.server.api.mill.rpc import HANDLERS

# Host commands. They are printed in help and are not mill-wall commands.
_LOCAL = frozenset(
    {
        "briefing",
        "help",
        "init",
        "score-add",
        "score-tick",
        "wall",
        "update",
        "install",
        "uninstall",
        "connect",
        "route",
        "watch",
        "wall-check",
        "wall-src",
        "local",
        "status",
    }
)
_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


def _help_commands() -> list[str]:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        try:
            main(["-h"])
        except SystemExit as exc:
            assert exc.code in (0, None)
    finally:
        sys.stdout = old
    names: list[str] = []
    for line in buf.getvalue().splitlines():
        if not line.startswith("    ") or line.startswith("     "):
            continue
        word = line.strip().split()[0]
        if _NAME.match(word):
            names.append(word)
    return names


def test_help_wall_commands_are_handlers() -> None:
    names = _help_commands()
    # #254 folded the old wall status verb into hold --peek.
    # Card 1223's status is a local run self-check, not a wall handler.
    assert "status" in names
    assert "hold" in names
    missing = []
    for name in names:
        if name in _LOCAL:
            continue
        # 0.7.x CLI words that translate onto a wall command (agent_coord/client/language.py).
        cli = {"unlabel": "label-remove", "watch": "add", "unwatch": "remove", "connect-wait": "connect", "connected": "session"}
        if name == "connect-wait":
            continue
        canon = "open" if name == "create" else canonical_command(cli.get(name, name))
        if canon not in HANDLERS or canon not in WALL:
            missing.append("%s -> %s" % (name, canon))
    assert missing == []


def test_help_has_no_mcp_commands_666() -> None:
    """#666: the mill is a shell CLI; `mill mcp` and `mill mcp-config` are gone."""
    names = _help_commands()
    assert "hold" in names
    assert "mcp" not in names
    assert "mcp-config" not in names
    for command in ("mcp", "mcp-config"):
        try:
            main([command])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("mill %s still parses" % command)


def test_no_mill_mcp_console_script_666() -> None:
    """#666: the wheel installs no `mill-mcp` launcher and ships no mcp_mill module."""
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    assert "mill-mcp" not in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert importlib.util.find_spec("agent_coord.server.mcp_mill") is None
