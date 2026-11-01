# -*- coding: utf-8 -*-
"""#618 desk webhook wake. Regression row F68 (desk-webhook).

Seen: no command or procedure wrote join.endpoint_url or delivery_mode, so no desk
could be armed; the auth key was one host-wide setting, so two desks with two
receivers could not both be armed; a letter never rang a webhook; and a burst
of hints would have started one paid bot run per hint.

Now `mill join` picks the delivery: the URL (https, allowlisted host, no IP
literal, public addresses only, no redirects) and the desk's own key live on
its join row; a POST is a doorbell carrying the same frame and poke key a
sitting desk gets, one per desk until it connects; every hint stays missed, so
the woken desk's connect sync hands all of them over and its chain walks them.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import push, wake
from tests.server.webhook_fixtures import HOOK_HOST, HOOK_KEY, HOOK_URL, arm


class _Resp:
    status = 200

    def read(self, _n: int = 0) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


# --- URL and key: what a person copies, and the refusals -----------------------

DEFAULT_OK = "https://api2.cursor.sh/automations/webhook/00000000-0000-4000-8000-000000000000"


def test_default_allowlist_takes_a_routine_url(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_COORD_WAKE_HOSTS", raising=False)
    url, host = wake.check_url("  " + DEFAULT_OK + "\n")
    assert url == DEFAULT_OK and host == "api2.cursor.sh"


@pytest.mark.parametrize(
    "raw, says",
    [
        ("http://api2.cursor.sh/automations/webhook/x", "https only"),
        ("https://hooks.example.com/automations/webhook/x", "not on this wall's wake allowlist"),
        ("https://api2.cursor.sh/other/x", "not a webhook path"),
        ("crsr_" + "a" * 40, "looks like the key"),
        ("Authorization: Bearer abcdefgh12345678", "looks like the key"),
        ("https://127.0.0.1/automations/webhook/x", "not an IP address"),
        ("https://[::1]/automations/webhook/x", "not an IP address"),
        ("https://2130706433/automations/webhook/x", "not an IP address"),
        ("https://u:p" + "@" + "api2.cursor.sh/automations/webhook/x", "user or password"),
        ("https://api2.cursor.sh:8443/automations/webhook/x", "default https port"),
        ("", "URL required"),
    ],
)
def test_url_refusals_name_the_fix(monkeypatch, raw, says) -> None:
    monkeypatch.delenv("AGENT_COORD_WAKE_HOSTS", raising=False)
    with pytest.raises(wake.WakeRefused) as ei:
        wake.check_url(raw)
    assert says in str(ei.value)
    assert "/automations/webhook/x" not in str(ei.value)


@pytest.mark.parametrize(
    "raw",
    [
        HOOK_KEY,
        "Bearer " + HOOK_KEY,
        "Authorization: Bearer " + HOOK_KEY,
        "authorization:bearer " + HOOK_KEY + "\n",
        "X-Automation-Key: " + HOOK_KEY,
        '"' + HOOK_KEY + '"',
    ],
)
def test_key_in_any_copied_form(raw) -> None:
    assert wake.normalize_key(raw) == HOOK_KEY


@pytest.mark.parametrize(
    "raw, says",
    [
        ("", "key required"),
        ("Bearer ", "key required"),
        (HOOK_URL, "that is a URL"),
        ("two words here", "one plain token"),
        ("line1\nline2", "one line"),
    ],
)
def test_key_refusals(raw, says) -> None:
    with pytest.raises(wake.WakeRefused) as ei:
        wake.normalize_key(raw)
    assert says in str(ei.value)


def test_private_and_loopback_addresses_are_refused(monkeypatch) -> None:
    for addrs in (["127.0.0.1"], ["::1"], []):
        monkeypatch.setattr(wake, "_addrs", lambda host, a=addrs: a)
        assert wake.public_host(HOOK_HOST) is False


def test_a_redirect_is_never_followed() -> None:
    hits: list[str] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        def log_message(self, *_a):
            return

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        status, _err = wake._post_status(
            f"http://127.0.0.1:{srv.server_port}/hook", {"kind": "wake"},
            timeout=3, key=HOOK_KEY, desk="d", hint_id=None,
        )
    finally:
        srv.shutdown()
    assert status == 302
    assert hits == ["/hook"]


def test_test_fire_says_what_is_wrong_without_the_path_or_key(monkeypatch) -> None:
    import urllib.error

    arm(monkeypatch)

    def refuse(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "no", hdrs=None, fp=None)

    with patch("agent_coord.server.wake._open", refuse):
        got = wake.test_fire(HOOK_URL, HOOK_KEY, "d1")
    assert got["ok"] is False and got["status"] == 401
    assert "refused the key" in got["fix"]
    assert HOOK_KEY not in json.dumps(got) and "fixture-routine" not in json.dumps(got)


# --- the wall: join sets the delivery ----------------------------------------

class _Join:
    """In-memory join row for rec_join.wake_*."""

    def __init__(self):
        self.row: tuple[str, str] | None = None
        self.calls: list[str] = []

    def install(self, monkeypatch):
        from agent_coord.server.records import join as rec_join

        monkeypatch.setattr(rec_join, "wake_target", lambda cn, desk: self.row)
        monkeypatch.setattr(rec_join, "wake_arm", lambda cn, desk, url, key, wake_on="addressed": (self.calls.append("arm"), setattr(self, "row", (url, key))))
        monkeypatch.setattr(rec_join, "wake_state", lambda cn, desk: {"armed": bool(self.row), "host": "", "wake_on": "addressed"})
        monkeypatch.setattr(rec_join, "wake_off", lambda cn, desk: (self.calls.append("off"), setattr(self, "row", None)))


def _deliver(delivery):
    from agent_coord.server.api.mill.rpc import _join_delivery

    return _join_delivery(SimpleNamespace(_cn=MagicMock()), "builder", delivery)


def test_join_arms_once_and_a_repeat_is_a_no_op(monkeypatch) -> None:
    arm(monkeypatch)
    j = _Join()
    j.install(monkeypatch)
    posts: list[dict] = []

    def ok(req, timeout=0):
        posts.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", ok):
        first = _deliver({"mode": "webhook", "url": HOOK_URL, "key": "Bearer " + HOOK_KEY})
        again = _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY})
    assert first == {"webhook": "armed", "host": HOOK_HOST, "test": 200, "wake_on": "addressed"}
    assert again == {"webhook": "armed", "host": HOOK_HOST, "test": "unchanged", "wake_on": "addressed"}
    assert len(posts) == 1 and posts[0]["kind"] == "wake-test"
    assert j.calls == ["arm"] and j.row == (HOOK_URL, HOOK_KEY)


def test_a_failed_test_stores_nothing(monkeypatch) -> None:
    arm(monkeypatch)
    j = _Join()
    j.install(monkeypatch)
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: (_ for _ in ()).throw(TimeoutError())):
        with pytest.raises(CoordError) as ei:
            _deliver({"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY})
    assert "not armed" in str(ei.value) and f"could not reach {HOOK_HOST}" in str(ei.value)
    assert HOOK_KEY not in str(ei.value) and "fixture-routine" not in str(ei.value)
    assert j.calls == [] and j.row is None


def test_join_websocket_forgets_the_webhook(monkeypatch) -> None:
    j = _Join()
    j.row = (HOOK_URL, HOOK_KEY)
    j.install(monkeypatch)
    assert _deliver({"mode": "websocket"}) == {"webhook": "off", "delivery": "websocket"}
    assert j.row is None


def test_the_wall_rechecks_the_allowlist(monkeypatch) -> None:
    """A desk side that skipped its shape check still cannot point the wall elsewhere."""
    arm(monkeypatch)
    _Join().install(monkeypatch)
    with pytest.raises(CoordError) as ei:
        _deliver({"mode": "webhook", "url": "https://metadata.example.com/automations/webhook/x", "key": HOOK_KEY})
    assert "allowlist" in str(ei.value)


def test_no_host_wide_webhook_key_setting() -> None:
    from agent_coord import config

    assert "webhook_key" not in config.DEFAULTS
    assert not hasattr(wake, "webhook_key")


def test_redactor_knows_the_routine_key_family() -> None:
    from agent_coord.server.redact import redact_secrets

    raw = "crsr_" + "ab12" * 16
    assert raw not in redact_secrets("key " + raw)


# --- coalescing and the sync -------------------------------------------------

class _Queue:
    """In-memory wake: put appends, take returns and clears (mill_push_take)."""

    def __init__(self):
        self.rows: list[dict] = []

    def install(self, monkeypatch):
        from agent_coord.server.records import push as rec_push

        def put(cn, desk, cause, payload, outcome):
            self.rows.append(dict(payload, kind=cause, outcome=outcome, _desk=desk))
            return []

        def take(cn, desk):
            got = [{k: v for k, v in r.items() if k != "_desk"} for r in self.rows if r["_desk"] == desk]
            self.rows = [r for r in self.rows if r["_desk"] != desk]
            return got

        monkeypatch.setattr(rec_push, "put", put)
        monkeypatch.setattr(rec_push, "take", take)
        monkeypatch.setattr(rec_push, "pending", lambda cn, desk: len([r for r in self.rows if r["_desk"] == desk]))
        monkeypatch.setattr(rec_push, "pending_addressed", lambda cn, desk: any(
            r["_desk"] == desk and r.get("wake_reason") != "room" for r in self.rows))
        monkeypatch.setattr("agent_coord.server.records.hold.own", lambda cn, desk: [])
        monkeypatch.setattr("agent_coord.server.records.join.wake_state", lambda cn, desk: {"armed": True, "host": HOOK_HOST})


def _hint(cn, n: int, desk: str = "away") -> None:
    rows = [{"desk": desk, "hint": None, "delivery_mode": "webhook", "endpoint_url": "set"}]
    with patch("agent_coord.server.records.watcher.select", return_value=rows), patch(
        "agent_coord.server.records.activity.select", return_value=[]
    ):
        push.fanout(cn, "todo", n, "TODO")


def test_a_burst_of_ten_hints_rings_once_and_the_sync_has_all_ten(monkeypatch) -> None:
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    posts: list[dict] = []

    def ok(req, timeout=0):
        posts.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    cn = MagicMock()
    with patch("agent_coord.server.wake._open", ok):
        for n in range(6180, 6190):
            _hint(cn, n)
        assert len(posts) == 1
        body = posts[0]
        assert body["idem"] == "hint:todo:6180:away"
        assert body["wake"]["pending"] == 1 and body["wake"]["window_s"] == int(wake.WAKE_WINDOW_S)
        assert "mill connect -r away" in body["wake"]["next"]
        frame = push.connect_sync_frame(cn, "away")
        assert [r["id"] for r in frame["sync"]] == list(range(6180, 6190))
        assert {r["outcome"] for r in frame["sync"]} == {"missed"}
        assert frame["wake"] == f"webhook armed (host {HOOK_HOST})"
        # F144: the sync does not end the wake lease; the next hint waits for done.
        _hint(cn, 6190)
        assert len(posts) == 1
        assert wake.lease_done(cn, "away") == "sent"
    assert len(posts) == 2
    assert posts[1]["wake"]["pending_count"] == 1


def test_the_window_ends_without_a_connect(monkeypatch) -> None:
    arm(monkeypatch)
    _Queue().install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    posts: list = []
    clock = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    cn = MagicMock()
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: posts.append(1) or _Resp()):
        _hint(cn, 6200)
        clock["t"] += wake.WAKE_WINDOW_S - 1
        _hint(cn, 6201)
        clock["t"] += 2
        _hint(cn, 6202)
    assert len(posts) == 2


def test_a_letter_rings_without_its_text(monkeypatch) -> None:
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    posts: list[dict] = []
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: posts.append(json.loads(req.data)) or _Resp()):
        assert push.emit(MagicMock(), "away", "mail", {"id": 6210, "body": "the letter text", "sender": "s"}) == "missed"
    assert len(posts) == 1
    assert posts[0]["kind"] == "mail" and posts[0]["id"] == 6210
    assert posts[0]["idem"] == "letter:6210:away"
    assert "the letter text" not in json.dumps(posts[0])
    assert q.rows[0]["outcome"] == "missed" and q.rows[0]["body"] == "the letter text"


def test_a_sitting_desk_is_never_posted(monkeypatch) -> None:
    arm(monkeypatch)
    _Queue().install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {"away": {object()}})
    monkeypatch.setattr(push.HUB, "notify", lambda *a, **k: None)
    posts: list = []
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: posts.append(1) or _Resp()):
        _hint(MagicMock(), 6220)
        push.emit(MagicMock(), "away", "mail", {"id": 6221})
    assert posts == []


# --- the desk side: the same walk, the same key check ------------------------

def _routes(monkeypatch, tmp_path, routes, calls):
    from agent_coord.client.route_chain import save_routes

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.route_chain.run_program",
        lambda cmd, msg: calls.append((cmd, msg.get("id"))) or ("handled", 0),
    )
    pokes: list = []
    monkeypatch.setattr("agent_coord.client.connectors.poke", lambda vendor, frame: pokes.append(frame.get("id")))
    save_routes("away", routes)
    return pokes


def test_a_posted_frame_takes_the_route_not_the_vendor(tmp_path, monkeypatch) -> None:
    from agent_coord.client.wake_post import accept_wake

    calls: list = []
    pokes = _routes(monkeypatch, tmp_path, [("todo:TODO", "on_todo")], calls)
    body = wake.wake_body("away", {"type": "todo", "id": 6230, "hint": "TODO", "idem": "hint:todo:6230:away"}, pending=1)
    assert accept_wake(body) == "work"
    assert calls == [("on_todo", 6230)] and pokes == []


def test_an_unmatched_posted_frame_wakes_the_vendor(tmp_path, monkeypatch) -> None:
    from agent_coord.client.wake_post import accept_wake

    calls: list = []
    pokes = _routes(monkeypatch, tmp_path, [("todo:TODO", "on_todo")], calls)
    body = wake.wake_body("away", {"type": "hold", "id": 6231, "hint": "HOLD", "idem": "hint:hold:6231:away"}, pending=1)
    assert accept_wake(body) == "wake"
    assert calls == [] and pokes == [6231]


def test_a_forged_or_another_desks_key_is_refused(tmp_path, monkeypatch) -> None:
    from agent_coord.client.wake_post import accept_wake

    calls: list = []
    pokes = _routes(monkeypatch, tmp_path, [("*", "star")], calls)
    other = {"type": "todo", "id": 6232, "hint": "TODO", "idem": "hint:todo:6232:someone-else", "desk": "away"}
    forged = {"type": "todo", "id": 6233, "hint": "TODO", "idem": "hint:todo:9999:away", "desk": "away"}
    assert accept_wake(other) == "skip"
    assert accept_wake(forged) == "skip"
    assert calls == [] and pokes == []


def test_coalescing_never_suppresses_a_routed_hint(tmp_path, monkeypatch) -> None:
    """Ten hints ring once; the connect sync walks all ten, and each takes its route."""
    from agent_coord.client.dispatch import dispatch_hint, replay_items

    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    posts: list = []
    cn = MagicMock()
    with patch("agent_coord.server.wake._open", lambda req, timeout=0: posts.append(1) or _Resp()):
        for n in range(6240, 6250):
            _hint(cn, n)
        frame = push.connect_sync_frame(cn, "away")
    assert len(posts) == 1
    calls: list = []
    pokes = _routes(monkeypatch, tmp_path, [("todo:TODO", "on_todo")], calls)
    items = replay_items("away", frame["sync"])
    assert [i["id"] for i in items] == list(range(6240, 6250))
    assert all(i["idem"] == f"hint:todo:{i['id']}:away" for i in items)
    got = [dispatch_hint("away", i, replay=True) for i in items]
    assert got == ["work"] * 10
    assert [c[1] for c in calls] == list(range(6240, 6250))
    assert pokes == []


def test_an_unrouted_replay_is_left_for_the_reader(tmp_path, monkeypatch) -> None:
    from agent_coord.client.dispatch import dispatch_hint, replay_items

    calls: list = []
    pokes = _routes(monkeypatch, tmp_path, [("todo:TODO", "on_todo")], calls)
    items = replay_items("away", [
        {"kind": "hint", "type": "hold", "id": 6251, "hint": "HOLD", "outcome": "missed"},
        {"kind": "hint", "type": "todo", "id": 6252, "hint": "TODO", "outcome": "sent"},
        {"kind": "hint", "route": "todo:TODO", "id": 6253, "exit": 3, "outcome": "error"},
    ])
    assert [i["id"] for i in items] == [6251]
    assert dispatch_hint("away", items[0], replay=True) == "left"
    assert calls == [] and pokes == []


# --- the desk side: mill join options ----------------------------------------

def _args(**kw):
    base = dict(webhook_url="", webhook_url_file="", webhook_key_file="", webhook_key_env="", wake_on="",
                webhook_key_stdin=False, webhook_key=None, websocket=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_join_options_read_the_key_from_a_file_in_any_form(tmp_path) -> None:
    from agent_coord.client.wake_cli import delivery_body

    kf = tmp_path / "key"
    kf.write_text("Authorization: Bearer " + HOOK_KEY + "\n", encoding="utf-8")
    uf = tmp_path / "url"
    uf.write_text(HOOK_URL + "\n", encoding="utf-8")
    got = delivery_body(_args(webhook_url_file=str(uf), webhook_key_file=str(kf)))
    assert got == {"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY}
    assert delivery_body(_args()) is None
    assert delivery_body(_args(websocket=True)) == {"mode": "websocket"}


def test_join_options_refuse_common_mistakes(tmp_path, monkeypatch) -> None:
    from agent_coord.client.wake_cli import delivery_body

    monkeypatch.delenv("MILL_TEST_EMPTY", raising=False)
    cases = [
        (_args(webhook_url=HOOK_URL, webhook_key=HOOK_KEY), "--webhook-key on the command line is refused"),
        (_args(webhook_url=HOOK_URL), "webhook key required"),
        (_args(webhook_url=HOOK_KEY, webhook_key_env="MILL_TEST_K"), "looks like the key"),
        (_args(webhook_url="http://" + HOOK_HOST + "/automations/webhook/r", webhook_key_env="MILL_TEST_K"), "https only"),
        (_args(webhook_url=HOOK_URL, webhook_key_env="MILL_TEST_EMPTY"), "empty or unset"),
        (_args(websocket=True, webhook_url=HOOK_URL), "--websocket takes no webhook options"),
    ]
    monkeypatch.setenv("MILL_TEST_K", HOOK_KEY)
    for args, says in cases:
        with pytest.raises(CoordError) as ei:
            delivery_body(args)
        assert says in str(ei.value)
        assert HOOK_KEY not in str(ei.value)


def test_seated_join_prints_one_line_without_path_or_key(monkeypatch, capsys) -> None:
    from agent_coord.client import wake_cli

    sent: list[dict] = []
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda who: "seat")
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: sent.append(body) or {"owner": "builder", "wake": {"webhook": "armed", "host": HOOK_HOST, "test": 200}},
    )
    rc = wake_cli.run_seated("builder", {"mode": "webhook", "url": HOOK_URL, "key": HOOK_KEY})
    out = capsys.readouterr()
    assert rc == 0
    assert json.loads(out.out) == {"kind": "wake", "desk": "builder", "webhook": "armed", "host": HOOK_HOST, "test": 200}
    assert HOOK_KEY not in out.out + out.err and "fixture-routine" not in out.out + out.err
    assert sent[0]["verb"] == "join" and sent[0]["owner"] == "builder" and "token" not in sent[0]


def test_key_argv_never_echoes_through_argparse(capsys) -> None:
    from agent_coord.__main__ import main

    rc = main(["join", "builder", "--webhook-url", HOOK_URL, "--webhook-key", HOOK_KEY])
    err = capsys.readouterr().err
    assert rc == 2
    assert "refused" in err and HOOK_KEY not in err
