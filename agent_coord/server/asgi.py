# -*- coding: utf-8 -*-
"""FastAPI/uvicorn mill-wall. Same Handler as middleware.

Wall /api and mill-command HTTP contracts stay. Request log (status + duration_ms)
plus nginx combined access/error logs at the TLS edge.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from http.client import HTTPMessage
from io import BytesIO
from pathlib import Path
from typing import Any

from agent_coord.server.redact import err_text

from agent_coord.server.middleware import BODY_MAX_BYTES, make_handler  # cap shared with the stdlib Handler (#747, #783)
from agent_coord.lib.observe import parse_roots

_log = logging.getLogger("mill.wall")
_server: Any = None
_samples: list[float] = []
_SAMPLE_CAP = 200
_n = 0
_ms_max = 0.0


def hold_envelope_ok(command: str, result: Any) -> bool:
    """Top-level ok matches a refused hold or a refused drop (#207, #227)."""
    if command in ("hold", "drop") and isinstance(result, dict) and result.get("ok") is False:
        return False
    return True


def ws_auth_close(exc: BaseException) -> tuple[int, str]:
    """A down book during /ws auth is try-again. Other failures stay 1011 (#144)."""
    from agent_coord.server.records.db import book_down

    if book_down(exc):
        return 1013, "book unavailable"
    return 1011, ""


def _note_connect(c: Any, want: str) -> None:
    """Record the /ws connect (DOING fanout). Only a connect that sits is recorded (#332)."""
    from agent_coord.server.records import join as rec_join

    try:
        rec_join.note_connect(c._cn, want)
    except Exception as e:
        err = type(e).__name__  # the class only; no exception text reaches the log
        _log.warning("ws connect activity err=%s", err)


def touch_sitting_desks(desks: list[str]) -> None:
    """Bump seat.updated for each desk that still holds /ws (card 985).

    Hub PING alone does not write the book, so a plain connect with no RPC
    looked stale after HEARTBEAT_STALE_S even while the socket was up.
    """
    from agent_coord.server.book import Book
    from agent_coord.server.records import join as rec_join

    for desk in desks or []:
        who = str(desk or "").strip()
        if not who:
            continue
        try:
            with Book() as c:
                rec_join.touch(c._cn, "", who)
        except Exception as e:
            err = type(e).__name__
            _log.warning("ws sit touch err desk=%s err=%s", who[:64], err)


def latency_snapshot() -> dict[str, float | int]:
    """Cheap mill-wall timing for unit/benchmark. Not a Wall API."""
    xs = sorted(_samples)
    n = len(xs)
    if not n:
        return {"n": _n, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": _ms_max}
    p50 = xs[n // 2]
    p95 = xs[min(n - 1, int(n * 0.95))]
    return {"n": _n, "p50_ms": p50, "p95_ms": p95, "max_ms": _ms_max}


def _note_ms(ms: float) -> None:
    global _n, _ms_max
    _n += 1
    _ms_max = max(_ms_max, ms)
    _samples.append(ms)
    if len(_samples) > _SAMPLE_CAP:
        del _samples[0 : len(_samples) - _SAMPLE_CAP]
    if _n % 50 == 0:
        snap = latency_snapshot()
        _log.info(
            "mill-wall latency n=%s p50=%.1fms p95=%.1fms max=%.1fms",
            snap["n"],
            snap["p50_ms"],
            snap["p95_ms"],
            snap["max_ms"],
        )


class _FakeServer:
    def __init__(self, host: str, port: int) -> None:
        self.server_address = (host, port)


def _access_log_path() -> Path:
    home = Path(os.environ.get("AGENT_COORD_MILL_HOME") or "").expanduser()
    if not str(home):
        home = Path.home() / ".mill"
    logs = home / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "mill-wall-access.log"


def _line(method: str, path: str, status: int, ms: float, nbytes: int, req_b: int = 0) -> str:
    return f"{method} {path} {status} req_b={req_b} resp_b={nbytes} {ms:.1f}ms"


def record_access(
    log_path: Path,
    method: str,
    path: str,
    status: int,
    ms: float,
    nbytes: int,
    req_b: int = 0,
) -> str:
    """Redact door secrets, then store one mill-wall access line."""
    from agent_coord.server.redact import redact_secrets

    line = redact_secrets(_line(method, path, status, ms, nbytes, req_b=req_b))
    _log.info(line)
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    return line



def _ack_rows(desk: str, ids: list) -> None:
    """#831: delete the queue rows a sent frame carried. An error leaves them queued."""
    try:
        from agent_coord.helpers.ident import desk_name
        from agent_coord.server.book import Book
        from agent_coord.server.push import ack_sync

        with Book() as c:
            ack_sync(c._cn, desk_name(desk), ids)
    except Exception as e:
        err = type(e).__name__  # the class only; no desk path or exception text reaches the log
        _log.warning("ws ack fail err=%s", err)


async def _ws_handle_client_text(
    desk: str, websocket: Any, raw: str, acks: list | None = None
) -> dict[str, Any] | None:
    """Parse client text. Valid RPC -> reply dict. Non-RPC -> None (ignore). Bad RPC shape -> error reply."""
    import asyncio

    from agent_coord.helpers.errors import CoordError
    from agent_coord.helpers.ident import desk_name
    from agent_coord.server.api.mill.rpc import dispatch_ws
    from agent_coord.server.book import Book
    from agent_coord.server.mill_json import stamp_mill
    from agent_coord.server.push import socket_seated
    from agent_coord.client.session_errors import SESSION_WS_REQUIRED

    text = raw if isinstance(raw, str) else str(raw or "")

    def _held(items: list) -> list:
        # #831: with acks, the reply's queue rows are deleted only after it is sent.
        if acks is not None:
            from agent_coord.server.push import sync_ids

            acks.extend(sync_ids(items))
        return items

    def _sync_now(who: str) -> list:
        from agent_coord.server.push import take_sync

        try:
            with Book() as c:
                return _held(take_sync(c._cn, who, hold=acks is not None))
        except Exception:
            return []

    async def _fail(fail_id: Any, error: str) -> dict[str, Any]:
        sync = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _sync_now(desk_name(desk))
        )
        return stamp_mill({"id": fail_id, "ok": False, "error": error, "sync": sync})

    try:
        msg = json.loads(text) if text else None
    except json.JSONDecodeError:
        return None
    if not isinstance(msg, dict):
        return None
    if (
        msg.get("drop") == 1
        and isinstance(msg.get("frame"), dict)
        and not (msg.get("verb") or msg.get("cmd"))
    ):
        frame = dict(msg["frame"])

        def _note() -> None:
            from agent_coord.server.book import Book
            from agent_coord.server.records.push import note_drop

            with Book() as c:
                note_drop(c._cn, desk_name(desk), frame)

        try:
            await asyncio.get_running_loop().run_in_executor(None, _note)
        except Exception:
            pass
        return None
    if (
        msg.get("exit") == 1
        and isinstance(msg.get("frame"), dict)
        and not (msg.get("verb") or msg.get("cmd"))
    ):
        frame = dict(msg["frame"])

        def _exit_line() -> None:
            from agent_coord.server.book import Book
            from agent_coord.server.records.push import note_route_exit

            with Book() as c:
                note_route_exit(c._cn, desk_name(desk), frame)

        try:
            await asyncio.get_running_loop().run_in_executor(None, _exit_line)
        except Exception:
            pass
        return None

    has_id = "id" in msg
    has_command = "verb" in msg or "cmd" in msg
    # Existing server pushes use type/hint; never treat as client RPC.
    if str(msg.get("hint") or "") and not has_command:
        return None
    if str(msg.get("type") or "") in ("heartbeat", "session") and not has_command:
        return None
    # Non-RPC client text: ignore.
    if not has_id and not has_command:
        return None
    # Looks like RPC but bad shape.
    req_id = msg.get("id")
    command = str(msg.get("verb") or msg.get("cmd") or "").strip()
    args = msg.get("args", {})
    if not has_id or req_id is None or req_id == "":
        return await _fail(req_id if has_id else None, "ws rpc: id required")
    if not command:
        return await _fail(req_id, "ws rpc: command required")
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return await _fail(req_id, "ws rpc: args must be an object")
    client_mill = " ".join(str(msg.get("mill") or "").split())[:64]

    who = desk_name(desk)
    if not socket_seated(who, websocket) and not socket_seated(desk, websocket):
        return await _fail(req_id, SESSION_WS_REQUIRED)

    t0 = time.perf_counter()
    from agent_coord.server import perf

    cmd = perf.begin(command, who or desk)  # None when perf is off (F171)

    # The transport peer decides the office-host (loopback) Admin marker, never
    # the client args. A forwarded request (reverse proxy) is not treated as
    # loopback so a proxy hop cannot masquerade as the office host.
    ws_peer = ""
    ws_forwarded = False
    try:
        client = getattr(websocket, "client", None)
        ws_peer = str(getattr(client, "host", "") or "")
        hdrs = getattr(websocket, "headers", None)
        if hdrs is not None:
            ws_forwarded = bool((hdrs.get("x-forwarded-for") or "").strip())
    except Exception:
        ws_peer = ""
        ws_forwarded = False

    def _dispatch(c: Any) -> Any:
        return dispatch_ws(
            c, who, command, args, req_id=str(req_id),
            peer=ws_peer, forwarded=ws_forwarded, client_mill=client_mill,
        )

    def _run() -> Any:
        if cmd is None:
            with Book() as c:
                return _dispatch(c)
        perf.phase(cmd, "q", (time.perf_counter() - t_q) * 1000.0)  # waiting for a worker thread
        return perf.in_book(cmd, Book, _dispatch)

    def _sync() -> list:
        from agent_coord.server.push import take_sync

        with Book() as c:
            return _held(take_sync(c._cn, who, hold=acks is not None))

    t_q = time.perf_counter()
    try:
        result = await asyncio.get_running_loop().run_in_executor(None, _run)
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000.0
        # A refusal keeps its short text; any other error only its class (no stack, no detail).
        err = " ".join(str(e).split())[:160] if isinstance(e, CoordError) else type(e).__name__

        def _command_err() -> None:
            perf.finish(cmd, ms, ok=0, err=err, req_b=len(text.encode("utf-8")))

        if cmd is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(None, _command_err)
            except Exception:
                pass
        sync = await asyncio.get_running_loop().run_in_executor(None, _sync)
        if isinstance(e, CoordError):
            return stamp_mill({"id": req_id, "ok": False, "error": str(e), "sync": sync})
        return stamp_mill({"id": req_id, "ok": False, "error": err_text(e), "sync": sync})

    # Kick/supersede during handler: do not complete RPC on a dead seat.
    if not socket_seated(who, websocket) and not socket_seated(desk, websocket):
        sync = await asyncio.get_running_loop().run_in_executor(None, _sync)
        return stamp_mill({"id": req_id, "ok": False, "error": SESSION_WS_REQUIRED, "sync": sync})
    t_s = time.perf_counter()
    sync = await asyncio.get_running_loop().run_in_executor(None, _sync)
    t_e = time.perf_counter()
    perf.phase(cmd, "sync", (t_e - t_s) * 1000.0)
    # A refused hold or drop keeps result.ok false. The envelope ok must match (#207, #227).
    env_ok = hold_envelope_ok(command, result)
    reply = stamp_mill({"id": req_id, "ok": env_ok, "result": result, "sync": sync})
    resp_b = 0
    try:
        from agent_coord.server.mill_json import with_bytes

        reply, resp_b = with_bytes(reply)
    except Exception:
        pass
    # ms ends after the reply is encoded (F171), so the phases add up to it.
    t_end = time.perf_counter()
    ms = (t_end - t0) * 1000.0
    perf.phase(cmd, "enc", (t_end - t_e) * 1000.0)
    try:
        req_b = len(text.encode("utf-8"))

        def _note() -> None:
            perf.finish(cmd, ms, ok=1 if env_ok else 0, req_b=req_b, resp_b=resp_b)

        # The score write goes to the flusher and the log line to a worker; the
        # reply does not wait for either (F24). It used to await mill_score_event.
        from agent_coord.server.score_system import enqueue_command

        enqueue_command(who or desk, command, req_b=req_b, resp_b=resp_b, ms=ms)
        asyncio.get_running_loop().run_in_executor(None, _note)
    except Exception:
        pass
    return reply



def make_asgi_app(
    roots: dict[str, Path] | None = None,
    *,
    api_only: bool = False,
    host: str = "127.0.0.1",
    port: int = 8765,
):
    """ASGI app: FastAPI catch-all that drives middleware.make_handler."""
    import asyncio

    from starlette.requests import Request
    from starlette.responses import Response

    from .push import HUB, WS_IN_USE

    Handler = make_handler(roots or parse_roots(), api_only=api_only)

    log_path = _access_log_path()

    async def _dispatch(request: Request) -> Response:
        t0 = time.perf_counter()
        path = request.url.path
        try:
            return await _dispatch_inner(request, t0)
        except Exception as e:
            from agent_coord.server.middleware import SECURITY_HEADERS, error_id

            eid = error_id(e, f"{request.method} {path} dispatch")
            try:
                from agent_coord.server.push import mill_admin_alert
                from agent_coord.server.middleware import _office

                with _office() as c:
                    mill_admin_alert(c._cn, f"asgi {request.method} {path} error_id={eid}: {e}", command="asgi")
            except Exception:
                pass
            from agent_coord.server.mill_json import dumps_mill_bytes

            return Response(
                content=dumps_mill_bytes({"error": "mill API error", "error_id": eid}),
                status_code=500,
                media_type="application/json; charset=utf-8",
                headers={"Cache-Control": "no-store", **dict(SECURITY_HEADERS)},
            )

    def _body_refusal(code: int, text: str) -> Response:
        from agent_coord.server.mill_json import dumps_mill_bytes

        return Response(
            content=dumps_mill_bytes({"error": text}),
            status_code=code,
            media_type="application/json; charset=utf-8",
            headers={"Connection": "close"},
        )

    async def _read_body_capped(request: Request) -> bytes | Response:
        """The request body, or a 413/400 refusal; never more than BODY_MAX_BYTES (#747).

        A declared Content-Length over the cap is refused before one byte is
        read. Any body, declared or chunked, is read through the stream with a
        running count, so a wrong header cannot get more than the cap past it.
        """
        cap = BODY_MAX_BYTES
        too_big = "request body too large: the most is %d bytes (413)" % cap
        declared = request.headers.get("content-length")
        if declared is not None:
            d = declared.strip()
            # ASCII digits only; cap length so int() cannot raise (#783).
            if not d or len(d) > 10 or not d.isascii() or not d.isdigit():
                return _body_refusal(400, "bad Content-Length")
            if int(d) > cap:
                return _body_refusal(413, too_big)
        parts: list[bytes] = []
        got = 0
        async for chunk in request.stream():
            if not chunk:
                continue
            got += len(chunk)
            if got > cap:
                return _body_refusal(413, too_big)
            parts.append(chunk)
        body = b"".join(parts)
        request._body = body  # later readers see the same bytes
        return body

    async def _dispatch_inner(request: Request, t0: float) -> Response:
        path = request.url.path
        from .allow import allowed, door_client, is_mill_command

        peer = request.client.host if request.client else "127.0.0.1"
        fwd = request.headers.get("x-forwarded-for") or ""
        from agent_coord.server.admin.door import mode as door_mode

        if door_mode() == "ip":
            # Forwarded only from a trusted proxy; a forwarded loopback is not
            # this machine (#651).
            ip, via_proxy = door_client(peer, fwd)
            if not allowed(ip, empty_open=False, forwarded=via_proxy):
                return Response(
                    content=b"mill-wall: door=ip; add this address to wall-allow.txt\n",
                    status_code=403,
                    media_type="text/plain; charset=utf-8",
                )
        elif not is_mill_command(path):
            # Same trusted-proxy read as door=ip (#731).
            ip, via_proxy = door_client(peer, fwd)
            if not allowed(ip, forwarded=via_proxy):
                return Response(
                    content=b"mill-wall: IP not on wall-allow (human Wall ACL)\n",
                    status_code=403,
                    media_type="text/plain; charset=utf-8",
                )
        body = await _read_body_capped(request)
        if isinstance(body, Response):
            return body
        if request.url.query:
            path = path + "?" + request.url.query
        handler = Handler.__new__(Handler)
        handler.command = request.method
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.requestline = f"{request.method} {path} HTTP/1.1"
        handler.close_connection = True
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        msg = HTTPMessage()
        for key, val in request.headers.items():
            msg[key] = val
        if "Content-Length" not in msg:
            msg["Content-Length"] = str(len(body))
        handler.headers = msg
        client = request.client
        handler.client_address = (
            client.host if client else "127.0.0.1",
            client.port if client else 0,
        )
        handler.server = _FakeServer(host, port)
        handler.request = None
        handler.connection = None
        handler.raw_requestline = handler.requestline.encode("latin-1", "replace")
        status = [200]
        resp_headers: list[tuple[str, str]] = []

        def send_response(code: int, message: str | None = None) -> None:
            status[0] = int(code)

        def send_header(key: str, val: str) -> None:
            resp_headers.append((str(key), str(val)))

        def end_headers() -> None:
            return None

        handler.send_response = send_response  # type: ignore[method-assign]
        handler.send_header = send_header  # type: ignore[method-assign]
        handler.end_headers = end_headers  # type: ignore[method-assign]
        handler.log_request = lambda *a, **k: None  # type: ignore[method-assign]
        method = (request.method or "GET").upper()

        def _run_handler() -> None:
            if method == "POST":
                handler.do_POST()
            else:
                handler.do_GET()

        await asyncio.get_running_loop().run_in_executor(None, _run_handler)
        raw = handler.wfile.getvalue()
        cookies: list[tuple[str, str]] = []
        hdrs: dict[str, str] = {}
        for key, val in resp_headers:
            if key.lower() == "content-length":
                continue
            if key.lower() == "set-cookie":
                cookies.append((key, val))
                continue
            hdrs[key] = val
        media = hdrs.pop("Content-Type", None) or hdrs.pop("content-type", None)
        ms = (time.perf_counter() - t0) * 1000.0
        _note_ms(ms)
        record_access(
            log_path,
            request.method,
            path,
            status[0],
            ms,
            len(raw),
            req_b=len(body),
        )
        hdrs["X-Mill-Duration-Ms"] = f"{ms:.1f}"
        response = Response(
            content=raw,
            status_code=status[0],
            media_type=media,
            headers=hdrs,
        )
        for key, val in cookies:
            response.headers.append(key, val)
        return response

    from starlette.applications import Starlette
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket as StarWS


    async def ws_endpoint(websocket: StarWS) -> None:
        from agent_coord.server.redact import redact_format

        desk = str(websocket.path_params.get("desk") or "")
        # mill connect -r: do not take a seat another live socket holds (#332).
        refuse = str(websocket.query_params.get("refuse") or "") == "1"
        try:
            await websocket.accept()
        except Exception as e:
            _log.warning("%s", redact_format("ws accept fail desk=%s err=%s", desk, e))
            return
        auth = (websocket.headers.get("authorization") or "").strip()
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            _log.warning("ws auth missing desk=%s", desk)
            try:
                await websocket.close(code=4401)
            except Exception:
                pass
            return
        try:
            from agent_coord.client.tokens import token_hash
            from agent_coord.helpers.ident import desk_name
            from agent_coord.server.book import Book
            from agent_coord.server.records import join as rec_join

            digest = token_hash(token)
            want = desk_name(desk)
            ok = False
            with Book() as c:
                if rec_join.token_matches(c._cn, want, digest):
                    ok = True
                    if not refuse:
                        _note_connect(c, want)
            if not ok:
                _log.warning("ws auth bad token desk=%s", desk)
                try:
                    await websocket.close(code=4401)
                except Exception:
                    pass
                return
        except Exception as e:
            _log.warning("%s", redact_format("ws auth fail desk=%s err=%s", desk, e))
            code, reason = ws_auth_close(e)
            try:
                if reason:
                    await websocket.close(code=code, reason=reason)
                else:
                    await websocket.close(code=code)
            except Exception:
                pass
            return
        held = None
        try:
            held = await HUB.add(desk, websocket, refuse=refuse)
        except Exception as e:
            _log.warning("%s", redact_format("ws add fail desk=%s err=%s", desk, e))
        if held:
            since = f" since {held['since']}" if held.get("since") else ""
            # A close reason is at most 123 UTF-8 bytes.
            reason = f"seat in use: {held['desk']}{since}".encode("utf-8")[:123].decode("utf-8", "ignore")
            try:
                await websocket.close(code=WS_IN_USE, reason=reason)
            except Exception:
                pass
            return
        if refuse:
            try:
                from agent_coord.helpers.ident import desk_name
                from agent_coord.server.book import Book

                with Book() as c:
                    _note_connect(c, desk_name(desk))
            except Exception as e:
                err = type(e).__name__  # the class only; no exception text reaches the log
                _log.warning("ws connect activity err=%s", err)
        # Card 985: every successful sit bumps seat.updated so the hub shows alive
        # immediately (PING refresh continues while the socket stays up).
        try:
            from agent_coord.helpers.ident import desk_name as _desk_name_touch

            touch_sitting_desks([_desk_name_touch(desk)])
        except Exception:
            pass
        try:
            from agent_coord.helpers.ident import desk_name
            from agent_coord.server.book import Book
            from agent_coord.server.mill_json import stamp_mill
            from agent_coord.server.push import connect_sync_frame, sync_ids

            def _connect_sync() -> dict:
                with Book() as c:
                    return connect_sync_frame(c._cn, desk_name(desk), hold=True)

            frame = await asyncio.get_running_loop().run_in_executor(None, _connect_sync)
            # #831: the rows are deleted only after send_text returns. A socket kicked
            # or closed before then leaves them queued for the next sync.
            sent_ids = sync_ids(frame.get("sync"))
            await websocket.send_text(json.dumps(stamp_mill(frame), default=str))
            if sent_ids:
                await asyncio.get_running_loop().run_in_executor(None, _ack_rows, desk, sent_ids)
        except Exception as e:
            _log.warning("%s", redact_format("ws sync fail desk=%s err=%s", desk, e))
        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                except Exception:
                    break
                acks: list = []
                try:
                    reply = await _ws_handle_client_text(desk, websocket, raw, acks)
                except Exception as e:
                    _log.warning("%s", redact_format("ws rpc fail desk=%s err=%s", desk, e))
                    reply = None
                if reply is None:
                    continue
                try:
                    await websocket.send_text(json.dumps(reply, default=str))
                except Exception:
                    break  # #831: not sent, so its sync rows stay queued
                if acks:
                    await asyncio.get_running_loop().run_in_executor(None, _ack_rows, desk, acks)
        finally:
            try:
                HUB.discard(desk, websocket)
            except Exception:
                pass

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        HUB.bind_loop(asyncio.get_running_loop())
        try:
            from agent_coord.server.records.db import warm_pool

            await asyncio.get_running_loop().run_in_executor(None, warm_pool)
        except Exception:
            pass

        async def _warm_paths() -> None:
            # After listen: open read paths (rooms + lean mailbox) so first Wall paint is warm.
            try:
                await asyncio.sleep(0)
                from agent_coord.server.records.db import warm_read_paths

                await asyncio.get_running_loop().run_in_executor(None, warm_read_paths)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        async def _ping() -> None:
            while True:
                try:
                    await asyncio.sleep(20)
                    rooms = list(HUB.rooms)
                    for desk in rooms:
                        try:
                            HUB.notify(desk, {"type": "heartbeat", "id": 0, "hint": "PING"})
                        except Exception:
                            pass
                    # Card 985: keep seat.updated fresh while /ws is up so connected
                    # shows alive without requiring an RPC heartbeat from the desk.
                    if rooms:
                        try:
                            await asyncio.get_running_loop().run_in_executor(
                                None, touch_sitting_desks, rooms
                            )
                        except Exception:
                            pass
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(20)

        async def _score() -> None:
            from agent_coord.server.score_tick import tick

            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, tick)
            except Exception:
                pass
            while True:
                try:
                    await asyncio.sleep(900)
                    await loop.run_in_executor(None, tick)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(900)

        async def _push_expire() -> None:
            # 30-day queue sweep: once at start, then every PUSH_EXPIRE_EVERY_S.
            from agent_coord.server.push import PUSH_EXPIRE_EVERY_S, expire_sweep

            loop = asyncio.get_running_loop()
            while True:
                try:
                    await loop.run_in_executor(None, expire_sweep)
                    await asyncio.sleep(PUSH_EXPIRE_EVERY_S)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(PUSH_EXPIRE_EVERY_S)

        ping_task = asyncio.create_task(_ping())
        score_task = asyncio.create_task(_score())
        expire_task = asyncio.create_task(_push_expire())
        warm_task = asyncio.create_task(_warm_paths())
        yield
        warm_task.cancel()
        ping_task.cancel()
        score_task.cancel()
        expire_task.cancel()

    _http = ["GET", "POST", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"]

    async def http_endpoint(request: Request) -> Response:
        return await _dispatch(request)

    app = Starlette(
        routes=[
            WebSocketRoute("/ws/{desk}", ws_endpoint),
            Route("/", http_endpoint, methods=_http),
            Route("/{path:path}", http_endpoint, methods=_http),
        ],
        lifespan=lifespan,
    )
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    return app


def log_startup() -> None:
    """One mill-perf line when the wall process comes up (#220), with the driver (F34)."""
    try:
        from agent_coord.install.packver import package_version
        from agent_coord.server.push import perf_log
        from agent_coord.server.records.driver import cached, warn_once

        info = warn_once(cached())
        from agent_coord.server.records.db import book_sql_state

        sql = book_sql_state()
        perf_log(
            "startup",
            0.0,
            version=package_version(),
            db_driver=info.get("path"),
            connector=info.get("version") or None,
            sql="ok" if sql.get("ok") else "stale",
        )
        if not sql.get("ok"):
            # #614: say it where the operator looks; /health is 503 until it is fixed.
            _log.error(
                "book SQL is not this pack's (book %s, pack %s); run: %s",
                sql.get("book") or "none",
                sql.get("pack") or "unknown",
                sql.get("fix"),
            )
    except Exception:
        pass


def uvicorn_config(app, host: str, port: int, *, certs: dict | None = None):
    """The mill-wall uvicorn.Config.

    proxy_headers is hard-set off (#791): uvicorn keeps the raw TCP peer in
    scope["client"] and never reads X-Forwarded-For, so FORWARDED_ALLOW_IPS or
    --forwarded-allow-ips cannot widen proxy trust. The header is read only by
    allow.door_client, from the proxies in AGENT_COORD_TRUSTED_PROXIES
    (default this host's loopback, the installed nginx edge).
    """
    import uvicorn

    kw = dict(
        app=app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        use_colors=False,
        log_config=None,
        proxy_headers=False,
        forwarded_allow_ips="",
    )
    if certs:
        kw["ssl_certfile"] = certs["cert"]
        kw["ssl_keyfile"] = certs["key"]
    return uvicorn.Config(**kw)


def run_uvicorn(
    host: str,
    port: int,
    roots: dict[str, Path] | None = None,
    *,
    api_only: bool = False,
    dogfood: bool = False,
) -> None:
    """Block as mill-wall (replaces ThreadingHTTPServer.serve_forever)."""
    global _server
    import uvicorn

    from agent_coord.helpers.ident import this_host
    from .netbind import assert_mill_api_bind

    roots = roots or parse_roots()
    from .netbind import cert_paths

    certs = cert_paths()
    tls = bool(certs.get("cert_exists"))
    assert_mill_api_bind(host, api_only=api_only)
    if not api_only and not tls:
        h = (host or "").strip()
        if h in ("0.0.0.0", "::", "*") or (
            h and h not in ("127.0.0.1", "localhost", "::1") and not h.startswith("127.")
        ):
            raise SystemExit(
                "HTTPS-only: refusing cleartext wall on non-loopback. "
                "Need ~/.mill/ssl/wall.crt + wall.key (mill --http service) or nginx TLS."
            )
    if dogfood:
        print(
            "dogfood foreground wall - office wall is `mill install wall --apply`. "
            "This process is not a mill session.",
            flush=True,
        )
    scheme = "https" if tls else "http"
    print(
        f"factory board on {scheme}://{host}:{port}/  node={this_host()}  roots={list(roots)}  asgi=uvicorn",
        flush=True,
    )
    print(f"mill-wall access log {_access_log_path()}", flush=True)
    from agent_coord.server.win_wall_svc import _no_console_stdio

    _no_console_stdio()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    app = make_asgi_app(roots, api_only=api_only, host=host, port=port)
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = uvicorn_config(app, host, port, certs=certs if tls else None)
    server = uvicorn.Server(config)
    # Windows SERVICE: signals only work on the process main thread
    # https://github.com/encode/uvicorn/issues/526
    server.install_signal_handlers = lambda: None
    _server = server
    log_startup()
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nboard stopped")
    finally:
        _server = None


def shutdown_uvicorn() -> None:
    if _server is not None:
        _server.should_exit = True
