# -*- coding: utf-8 -*-
"""Pick the local transport. Linux, macOS, and WSL share the unix file."""
from __future__ import annotations

import os


def kind(name: str | None = None) -> str:
    """pipe on Windows. unix on Linux, macOS, and WSL."""
    which = os.name if name is None else name
    return "pipe" if which == "nt" else "unix"
