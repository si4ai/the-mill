"""Shared mill session / Bearer error copy (cp1252-safe ASCII)."""
from __future__ import annotations

import os

# When join.token_hash was cleared or the local token no longer matches.
SESSION_INVALID_REJOIN = (
    "invalid or expired Bearer; mill connect DESK to rejoin"
)

# Join refused: the office door (invite / directory / iam) needs a credential.
# A cold agent uses the seat welcome link; an invite office needs its invite key.
SESSION_JOIN_DENIED = (
    "join refused: this office door needs a valid invite or seat; "
    "mill join --link-file PATH (the welcome link file; ask an Admin to mint a seat)"
)

# Missing Bearer on a gated command.
SESSION_TOKEN_REQUIRED = (
    "mill access token required; mill connect DESK "
    "(writes ~/.mill/session/<desk>.token)"
)

# Bearer ok but desk has no live Hub /ws (kicked, dropped, never connected).
# Kept for WS-side checks when a socket is not seated.
SESSION_WS_REQUIRED = (
    "disconnected: no active Hub /ws for this desk; mill connect DESK to reconnect"
)

# HTTP desk-acting commands are cut: commands run as JSON RPC on the sitting /ws only.
SESSION_WS_RPC_ONLY = (
    "desk-acting commands use live /ws JSON RPC; mill connect, then command on that socket"
)

# mill_ws_call needs the sitting mill connect localhost bridge (no second /ws).
# Match is the command process parent pid, not the host active file.
# A fresh shell, a subshell, or the next tool call has a different parent, so
# "connect again, then retry" misses the same way (#179). Name the same-parent
# rule and a one-shot recipe for this OS. A second connect supersedes the first.
# The #121 retry compares str(e) to SESSION_WS_BRIDGE_REQUIRED, so the raised
# text and this constant stay the same string.
_BRIDGE_PREFIX = (
    "no sitting mill connect for this process; "
    "this command must be a child of the shell that started mill connect (same parent process). "
)
_BRIDGE_SUFFIX = "The connect is the desk's identity; a command outside one has none."
# What breaks the parent match, per OS (#361). One tool call is one shell.
_BASH_DIRECT = (
    "Connect and the commands go in ONE tool call (the next tool call is a new shell), and each command "
    "is a direct child of that shell: no timeout, nohup or other wrapper command and no ( ) subshell "
    "or second bash -c in front of it (redirecting its output to a file is fine). "
)
_PS_DIRECT = (
    "Connect and the commands go in ONE tool call: a Start-Process connect stops when the PowerShell "
    "call that started it ends, so the next tool call finds none. Run each command directly in that "
    "PowerShell, not through cmd /c, Start-Process or a new powershell. "
)
# Every mill command runs this way: connect and the command share one parent (0.7.x).
ONE_LINER = "bash -c 'mill connect DESK >/dev/null 2>&1 & trap \"kill $!\" EXIT; mill COMMAND ARGS'"
_BASH_RECIPE = "Run it as: " + ONE_LINER + " (connect alone in the foreground just blocks). "
_PS_RECIPE = (
    "Run it as: $c = Start-Process mill -ArgumentList 'connect','DESK' -PassThru -NoNewWindow; "
    "mill COMMAND ARGS; Stop-Process $c.Id (connect alone in the foreground just blocks). "
)


PS_ONE_LINER = (
    "$c = Start-Process mill -ArgumentList 'connect','DESK' -PassThru -NoNewWindow; "
    "mill COMMAND ARGS; Stop-Process $c.Id"
)


def bridge_hint(os_name: str | None = None) -> str:
    name = os.name if os_name is None else str(os_name)
    if name == "nt":
        return _BRIDGE_PREFIX + _PS_RECIPE + _PS_DIRECT + _BRIDGE_SUFFIX
    return _BRIDGE_PREFIX + _BASH_RECIPE + _BASH_DIRECT + _BRIDGE_SUFFIX


def parent_exited_notice(desk: str, os_name: str | None = None, **extra: object) -> dict:
    """The line a connect prints when the shell that started it is gone (#192, #361).

    A connect never outlives its parent; the hint says what to run instead.
    """
    name = os.name if os_name is None else str(os_name)
    recipe = PS_ONE_LINER if name == "nt" else ONE_LINER
    out: dict = {"ok": True, "mode": "ws", "reason": "parent exited", "desk": desk}
    out.update(extra)
    out["hint"] = (
        "the shell that started this connect ended, so the connect stopped (a connect never "
        "outlives the shell that started it; a new tool call is a new shell). Start connect and "
        "run the commands in one tool call: " + recipe
    )
    return out


SESSION_WS_BRIDGE_REQUIRED = bridge_hint()


def desk_flag_unnecessary(desk: str) -> str:
    """--desk was passed while this shell already has a connect."""
    who = str(desk or "").strip() or "this desk"
    return f"--desk is not necessary; {who} is already connected"


# The command as typed (after the mill word), so a refusal can name the exact
# next command in the CLI's words, not the RPC it rides (card 1130).
_typed: list[str] = []


def remember_typed(argv: list[str]) -> None:
    global _typed
    _typed = [str(a) for a in argv]


def desk_flag_required(command: str) -> str:
    """no sit and no --desk: say why, then the exact command to run next (card 1130)."""
    import shlex

    words = list(_typed) or [str(command or "").strip() or "COMMAND"]
    head = shlex.join(["mill", *words])
    again = head + " --desk DESK"
    return (
        f"{head}: no desk to act as (this shell has no sitting mill connect "
        f"and the command has no --desk). Run: {again} (DESK = a desk joined on this machine), "
        "or run it in the same shell as mill connect DESK."
    )


def desk_office_ambiguous(desk: str, aliases: list[str]) -> str:
    """Same desk name has a seat on more than one wall, and --office was omitted."""
    who = str(desk or "").strip() or "DESK"
    names = ", ".join(str(name) for name in aliases if str(name).strip())
    return f"multiple offices have desk {who} ({names}); pass --office ALIAS"

# The bridge or starting file is still here, but that connect process is gone (#228).
# Shell-neutral, and different from the sitting-miss hint (#236).
SESSION_CONNECT_DIED = (
    "disconnected: the mill connect for this process died. "
    "A connect stops when the shell that started it ends: a new tool call is a new shell, and a "
    "Start-Process connect stops with the PowerShell call that ran it. "
    "Start mill connect again in this same shell, then retry the command, all in one tool call."
)

