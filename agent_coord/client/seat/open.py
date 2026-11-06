# -*- coding: utf-8 -*-
"""Open the mill websocket. mill connect and a one-call command both use this."""
from __future__ import annotations

from typing import Any


def connect_websocket(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ssl_context: Any = None,
) -> Any:
    """Return a websockets connect context manager for this url.

    Older websockets builds take extra_headers. Newer ones take
    additional_headers. One attempt covers both.
    """
    import websockets

    kw: dict[str, Any] = {"open_timeout": 10}
    hdrs = {str(k): str(v) for k, v in (headers or {}).items() if v}
    if ssl_context is not None:
        kw["ssl"] = ssl_context
    if hdrs:
        kw["additional_headers"] = hdrs
    try:
        return websockets.connect(url, **kw)
    except TypeError:
        kw.pop("additional_headers", None)
        if hdrs:
            kw["extra_headers"] = hdrs
        return websockets.connect(url, **kw)
