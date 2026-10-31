# -*- coding: utf-8 -*-
"""Service glance reads. Counts and presence. Secrets stay out of the JSON."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.glance import _pack_routines, build, seal, slowest_command_text
from agent_coord.server.score_tick import BOOK_PERF
import agent_coord.server.middleware as mw

CANARY = "gln-canary-9f3a"


class _Cn:
    def __init__(self, script: list[tuple[str, list]]):
        self.script = script

    def cursor(self):
        return _Cur(self.script)


class _Cur:
    def __init__(self, script: list[tuple[str, list]]):
        self.script = script
        self.rows: list = []

    def execute(self, sql, *_a, **_k):
        self.rows = []
        for needle, rows in self.script:
            if needle in sql:
                self.rows = rows
                return

    def fetchall(self):
        return list(self.rows)

    def close(self):
        return None


def _cfg(*, api_only: bool = False) -> dict:
    return {
        "door": "path",
        "trust": "high",
        "https": True,
        "bind": "127.0.0.1",
        "lan_only": False,
        "cert_present": True,
        "one_process": True,
        "api_only": api_only,
        "serves_glass": not api_only,
        "static_cache": "pinned ?v=: public, max-age=31536000, immutable; else public, max-age=60 + ETag",
        "api_cache": "no-store",
        "mysql_host": "db.example",
        "mysql_database": "agent_coord",
        "issuer_set": False,
        "client_id_present": True,
        "logout_url_present": False,
        "sign_out_link": False,
        "allow": ["192.0.2.0/24"],
        "default_ttl": "24h",
    }


def test_seal_strips_secret_keys_and_text():
    packet = seal(
        {
            "password": CANARY,
            "client_secret": CANARY,
            "token": CANARY,
            "invite_url": "https://wall/?invite=" + CANARY,
            "note": "err=" + CANARY,
            "body": "todo " + CANARY,
            "ok": True,
            "line": f"Bearer {CANARY} Cookie: factory-door={CANARY} password={CANARY}",
            "pem": "-----BEGIN " + "PRIVATE KEY-----\n" + CANARY + "\n-----END " + "PRIVATE KEY-----",
            "nested": {"token_hash": CANARY, "n": 2},
        }
    )
    raw = json.dumps(packet)
    assert CANARY not in raw
    assert packet["ok"] is True
    assert packet["nested"]["n"] == 2
    assert "password" not in packet
    assert "token_hash" not in packet["nested"]


def test_build_reads_counts_and_hides_the_canary(monkeypatch):
    monkeypatch.setattr("agent_coord.server.glance.office_config", _cfg)
    episode = next(iter(BOOK_PERF))
    pack = _pack_routines()
    assert pack
    hour = {
        "n": 4,
        "/api/v1/agents": {"n": 3, "ms": 12},
        "/api/activity": {"n": 1, "ms": 4},
        "/api/floor": {"n": 9, "ms": 1},
        f"password={CANARY}": {"n": 8, "ms": 1},
    }
    later = datetime(2099, 1, 1, 0, 0, 0)
    past = datetime(2000, 1, 1, 0, 0, 0)
    on = datetime(2020, 1, 1, 0, 0, 0)
    script = [
        (
            "glance:office-scores",
            [
                ("mill-wall.err_n", "2", "0", on),
                ("mill-wall.ws_miss", "1", "0", on),
                ("mill-desk.hint_drop", "0", "0", on),
                ("mill-wall.ticks", "5", "0", on),
                ("mill-wall.api_n", "7", "", on),
                ("mill-wall.floor_n", "99", "", on),
                ("mill-desk.idle_verbs", "4", "0", on),
                (episode, "3", "", on),
                ("mill-office.activities", "11", "", on),
                ("mill-wall.api_ms", f"password={CANARY}", "100", on),
            ],
        ),
        (
            "glance:system-scores",
            [("grok-tui", "4"), ("ok-two", f"password={CANARY}")],
        ),
        ("glance:join-desks", [("grok-tui",), ("idle-one",)]),
        ("glance:wall-hour", [(json.dumps(hour),)]),
        (
            "glance:activity-types",
            [("mail", 2), ("todo", 3), ("join", 2), ("hold", 1), ("score", 4), ("name", 6)],
        ),
        ("glance:live-mail", [(2,)]),
        ("glance:live-todo", [(3,)]),
        ("glance:live-join", [(2,)]),
        ("glance:live-hold", [(1,)]),
        ("glance:live-score", [(4,)]),
        ("glance:names", [(18, 2)]),
        ("glance:seeds", [("roster", "Office", 1), ("roster", "Admin", 1)]),
        ("glance:admin", [("grok-tui",)]),
        ("glance:routines", [(name,) for name in sorted(pack | {"mill_now"})]),
        (
            "glance:invites",
            [
                (f"door password={CANARY}", 86400, later, None, on),
                ("waiting", 3600, later, None, None),
                ("old", 3600, past, None, on),
                ("gone", 3600, later, on, on),
            ],
        ),
        ("glance:welcome-invites", [(4,)]),
        ("glance:welcome-joined", [(1,)]),
        (
            "glance:drain",
            [(f"MAINTENANCE_DRAIN eta_at=2099-01-01T00:00:00Z reason=password={CANARY}",)],
        ),
    ]
    packet = build(_Cn(script), api_only=False)
    raw = json.dumps(packet)
    assert CANARY not in raw
    assert packet["secrets"] == "redacted"
    assert packet["alerts"]["err_n"] == {"value": 2, "stored": True, "target": "0"}
    assert packet["alerts"]["ws_miss"]["value"] == 1
    assert packet["alerts"]["hint_drop"]["stored"] is True
    assert packet["alerts"]["drain"]["phase"] == "draining"
    assert packet["alerts"]["drain"]["eta_at"].startswith("2099-01-01")
    assert packet["alerts"]["routines_missing"] == 0
    assert packet["alerts"]["standing"][0]["id"] == "station_todos"
    assert packet["office"]["mysql"] == {"host": "db.example", "database": "agent_coord"}
    assert packet["office"]["station"] == ""
    assert packet["office"]["signed_in"] is False
    seeds = {(row["type"], row["name"]): row for row in packet["office"]["seeds"]}
    assert seeds[("roster", "Office")]["present"] is True
    assert seeds[("roster", "Admin")]["retired"] is False
    assert "password" not in packet["office"]["mysql"]
    assert packet["platform"]["desks_with_score"] == 2
    assert packet["platform"]["verbs_today"] == 4
    assert packet["platform"]["desks_here_without_names"] == ["idle-one"]
    routes = [row["route"] for row in packet["platform"]["routes"]]
    assert routes == ["/api/v1/agents", "/api/activity"]
    assert "/api/floor" not in routes
    assert "mill-wall.floor_n" in packet["platform"]["kept_off"]
    assert "mill-desk.idle_verbs" in packet["platform"]["kept_off"]
    assert packet["platform"]["episodes"][0]["kpi"] == episode
    assert packet["platform"]["episodes"][0]["value"] == 3
    assert all(row["kpi"] != "mill-wall.floor_n" for row in packet["logs"]["lines"])
    assert packet["logs"]["lines"][0]["kpi"] == "mill-wall.api_n"
    assert packet["logs"]["lines"][0]["value"] == 7
    ms = next(row for row in packet["logs"]["lines"] if row["kpi"] == "mill-wall.api_ms")
    assert ms["stored"] is False
    assert "op=score.history count" in packet["logs"]["unstored"]
    assert packet["book"]["open"] is True
    assert packet["book"]["types"]["mail"] == {"activity": 2, "live": 2}
    assert packet["book"]["types"]["name"]["retired"] == 2
    assert packet["book"]["seats_here"] == 2
    assert packet["book"]["promises_held"] == 1
    assert packet["book"]["admin"] == ["grok-tui"]
    assert packet["book"]["routines"]["watch"]["mill_span"] is True
    assert packet["book"]["routines"]["watch"]["mill_between"] is True
    assert packet["book"]["routines"]["watch"]["mill_wall_event"] is True
    assert "MILL_NOW" not in packet["book"]["routines"]["extra"]
    assert "mill_now" in packet["book"]["routines"]["extra"]
    assert packet["book"]["activity_touched_last_hour"]["value"] == 11
    assert packet["door"]["counts"] == {"pending": 1, "enabled": 1, "revoked": 1, "expired": 1}
    assert packet["door"]["default_ttl"] == "24h"
    assert packet["door"]["welcome"] == {"invites": 4, "joined": 1, "stored": True}
    assert packet["door"]["allow"] == ["192.0.2.0/24"]
    assert packet["door"]["allow_enforced"] is False
    assert packet["door"]["directory"]["client_id_present"] is True
    assert "client_id" not in packet["door"]["directory"]
    labels = " ".join(row["label"] for row in packet["door"]["keys"])
    assert CANARY not in labels


def test_office_config_omits_password_user_and_client_secret(monkeypatch, tmp_path):
    secret_id = "cid-" + CANARY

    def settings(*_a, **_k):
        return {
            "host": "db.example",
            "database": "agent_coord",
            "user": "root",
            "password": CANARY,
            "dashboard_bind": "127.0.0.1",
            "directory_client_secret": CANARY,
            "directory_issuer": "",
            "directory_client_id": secret_id,
            "directory_logout_url": "",
            "trust": "high",
            "door": "path",
            "lan_only": "0",
        }

    monkeypatch.setattr("agent_coord.config.settings", settings)
    monkeypatch.setattr("agent_coord.server.netbind.office_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "agent_coord.server.allow.load_allow",
        lambda: ["198.51.100.0/24", "nope " + CANARY],
    )
    from agent_coord.server.glance import office_config

    cfg = office_config(api_only=True)
    raw = json.dumps(cfg)
    assert CANARY not in raw
    assert secret_id not in raw
    assert cfg["mysql_host"] == "db.example"
    assert cfg["mysql_database"] == "agent_coord"
    assert cfg["client_id_present"] is True
    assert cfg["issuer_set"] is False
    assert cfg["api_only"] is True
    assert cfg["serves_glass"] is False
    assert cfg["cert_present"] is False
    assert cfg["allow"] == ["198.51.100.0/24"]
    assert "password" not in cfg
    assert "user" not in cfg


def test_glance_routes_share_one_cache_and_strip_secrets(monkeypatch):
    mw._floor_cache.clear()
    mw._floor_flight.clear()
    calls = {"n": 0}

    def load(*, api_only: bool = False):
        calls["n"] += 1
        return {
            "secrets": "redacted",
            "password": CANARY,
            "alerts": {"secrets": "redacted", "err_n": {"value": 1, "stored": True, "target": "0"}},
            "office": {
                "secrets": "redacted",
                "door": "path",
                "station": "",
                "signed_in": False,
                "token": CANARY,
            },
            "platform": {"secrets": "redacted"},
            "logs": {"secrets": "redacted"},
            "book": {"secrets": "redacted"},
            "door": {"secrets": "redacted", "invite_url": "/?invite=" + CANARY},
        }

    monkeypatch.setattr("agent_coord.server.glance.load_packet", load)
    monkeypatch.setattr(
        "agent_coord.server.glance.client_bits",
        lambda **_k: {"station": "192.0.2.10", "signed_in": True},
    )
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    from agent_coord.server.glance import _misses, _sessions, digest_for

    _sessions.clear()
    _misses.clear()
    taps = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc", "dddddddddd"]
    monkeypatch.setenv("AGENT_COORD_GLANCE_TAP", digest_for(taps, "word"))
    root = Path(__file__).resolve().parents[2]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    closed = client.get("/api/v1/glance/alerts")
    assert closed.status_code == 404
    assert calls["n"] == 0
    opened = client.post("/api/v1/glance/tap", json={"taps": taps, "passphrase": "word"})
    assert opened.status_code == 200

    alerts = client.get("/api/v1/glance/alerts")
    assert alerts.status_code == 200
    assert CANARY not in alerts.text
    assert alerts.json()["err_n"]["value"] == 1
    assert alerts.json()["secrets"] == "redacted"
    assert alerts.headers["cache-control"] == "no-store"
    office = client.get("/api/glance/office")
    assert office.status_code == 200
    assert office.json()["station"] == "192.0.2.10"
    assert office.json()["signed_in"] is True
    assert "token" not in office.json()
    assert calls["n"] == 1
    full = client.get("/api/v1/glance")
    assert full.status_code == 200
    body = full.json()
    for name in ("alerts", "office", "platform", "logs", "book", "door"):
        assert name in body
    assert CANARY not in full.text
    assert "password" not in body
    assert calls["n"] == 1
    live = client.get("/api/v1/glance/logs?timings=1")
    assert live.status_code == 200
    assert "sql_ms" in live.json()["timings"]
    assert calls["n"] == 2
    missing = client.get("/api/v1/glance/nope")
    assert missing.status_code == 404
    assert calls["n"] == 2


def test_key_name_matches_the_keypad():
    from agent_coord.install.glance_tap import MARKS, key_name

    assert len(MARKS) == 100
    assert MARKS[0] == ("🌞", "sun with a face")
    assert MARKS[99] == ("🎵", "musical note")
    assert len({description for _symbol, description in MARKS}) == 100
    assert key_name(0) == "iavfcwvlie"
    assert key_name(99) == "rlaydbomxp"


def test_generate_keys_are_distinct_keypad_names():
    from agent_coord.install.glance_tap import MARKS, generate_keys, key_name
    from agent_coord.server.glance import TAP_RE

    keys = generate_keys(4)
    assert len(keys) == 4
    assert len({key["name"] for key in keys}) == 4
    by_description = {description: (index, symbol) for index, (symbol, description) in enumerate(MARKS)}
    for key in keys:
        assert TAP_RE.fullmatch(key["name"])
        index, symbol = by_description[key["description"]]
        assert key["symbol"] == symbol
        assert key["name"] == key_name(index)


def _passphrase(monkeypatch, word="word"):
    asked = {}

    def fake(prompt=""):
        asked["prompt"] = prompt
        return word

    monkeypatch.setattr("getpass.getpass", fake)
    return asked


def test_generate_prints_symbols_and_stores_the_digest_only(tmp_path, capsys, monkeypatch):
    from agent_coord.install.glance_tap import configure_cli
    from agent_coord.server.glance import digest_for

    fixed = [
        {"symbol": "🌞", "description": "sun with a face", "name": "aaaaaaaaaa"},
        {"symbol": "🌙", "description": "crescent moon", "name": "bbbbbbbbbb"},
        {"symbol": "⭐", "description": "star", "name": "cccccccccc"},
        {"symbol": "⚡", "description": "lightning", "name": "dddddddddd"},
    ]
    monkeypatch.setattr("agent_coord.install.glance_tap.generate_keys", lambda count: fixed)
    asked = _passphrase(monkeypatch)
    result = configure_cli(taps=[], dest=str(tmp_path), generate=4)
    err = capsys.readouterr().err
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    names = [key["name"] for key in fixed]
    assert result["stored"] is True
    assert "sun with a face" in err
    assert "1." in err and "4." in err
    assert asked["prompt"] == "Passphrase (Enter leaves it empty): "
    for name in names:
        assert name not in err
        assert name not in text
    assert "word" not in text
    assert "word" not in err
    assert digest_for(names, "word") in text


def test_generate_display_hides_the_token(tmp_path, capsys, monkeypatch):
    from agent_coord.install import glance_tap
    from agent_coord.server.glance import digest_for

    monkeypatch.setattr(
        glance_tap.secrets.SystemRandom,
        "sample",
        lambda self, population, k: [0, 17, 64, 99],
    )
    _passphrase(monkeypatch)
    result = glance_tap.configure_cli(taps=[], dest=str(tmp_path), generate=4)
    err = capsys.readouterr().err
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    names = [glance_tap.key_name(i) for i in (0, 17, 64, 99)]
    assert result["stored"] is True
    assert "sun with a face" in err
    assert "palm" in err
    assert "ambulance" in err
    assert "musical note" in err
    for name in names:
        assert name not in err
        assert name not in text
    assert digest_for(names, "word") in text


def test_generate_flag_asks_when_the_number_is_omitted():
    import argparse

    from agent_coord.__main__ import _GenerateCount

    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", nargs="?", action=_GenerateCount, default=None)
    assert parser.parse_args(["--generate"]).generate == "ask"
    assert parser.parse_args(["--generate", "6"]).generate == 6
    assert parser.parse_args([]).generate is None


def test_generate_asks_how_many_digits(tmp_path, capsys, monkeypatch):
    from agent_coord.install.glance_tap import configure_cli

    monkeypatch.setattr("agent_coord.install.glance_tap.sys.stdin.isatty", lambda: True)
    typed = iter(["6"])
    monkeypatch.setattr("builtins.input", lambda: next(typed))
    seen = {}

    def fake(count=4):
        seen["n"] = count
        return [{"symbol": "🌞", "description": "sun with a face", "name": "aaaaaaaaaa"}]

    monkeypatch.setattr("agent_coord.install.glance_tap.generate_keys", fake)
    _passphrase(monkeypatch)
    result = configure_cli(taps=[], dest=str(tmp_path), generate="ask")
    err = capsys.readouterr().err
    assert result["stored"] is True
    assert seen["n"] == 6
    assert "Number of digits [4]:" in err


def test_generate_blank_digit_count_stays_four(tmp_path, monkeypatch):
    from agent_coord.install.glance_tap import configure_cli

    monkeypatch.setattr("agent_coord.install.glance_tap.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "")
    seen = {}

    def fake(count=4):
        seen["n"] = count
        return [{"symbol": "🌞", "description": "sun with a face", "name": "aaaaaaaaaa"}]

    monkeypatch.setattr("agent_coord.install.glance_tap.generate_keys", fake)
    _passphrase(monkeypatch, word="")
    result = configure_cli(taps=[], dest=str(tmp_path), generate="ask")
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert result["stored"] is True
    assert seen["n"] == 4
    from agent_coord.server.glance import digest_for

    assert digest_for(["aaaaaaaaaa"], "") in text


def test_generate_rejects_typed_taps(tmp_path):
    from agent_coord.install.glance_tap import configure_cli

    result = configure_cli(
        taps=["aaaaaaaaaa"],
        dest=str(tmp_path),
        generate=4,
    )
    assert result == {"ok": False, "error": "tap required"}
    assert not (tmp_path / "config.toml").exists()


def test_digest_follows_tap_order():
    from agent_coord.server.glance import digest_for

    one = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc"]
    assert digest_for(one, "") != digest_for(list(reversed(one)), "")
    assert digest_for(one, "") != digest_for(one, "word")


def test_install_stores_the_digest_only(tmp_path):
    from agent_coord.install.glance_tap import store
    from agent_coord.server.glance import digest_for

    taps = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc", "dddddddddd"]
    result = store(taps, "word", dest=str(tmp_path))
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert result["stored"] is True
    assert "aaaaaaaaaa" not in text
    assert "word" not in text
    assert digest_for(taps, "word") in text


def test_glance_read_stays_closed_without_a_session(monkeypatch):
    from agent_coord.server.glance import _misses, _sessions

    _sessions.clear()
    _misses.clear()
    mw._floor_cache.clear()
    mw._floor_flight.clear()
    calls = {"n": 0}

    def load(*, api_only: bool = False):
        calls["n"] += 1
        return {"secrets": "redacted", "alerts": {"secrets": "redacted"}}

    monkeypatch.setattr("agent_coord.server.glance.load_packet", load)
    monkeypatch.setattr("agent_coord.server.glance.stored_digest", lambda: "")
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    root = Path(__file__).resolve().parents[2]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    closed = client.get("/api/v1/glance")
    assert closed.status_code == 404
    assert closed.text == "not found\n"
    miss = client.post("/api/v1/glance/tap", json={"taps": ["aaaaaaaaaa"], "passphrase": "word"})
    assert miss.status_code == 404
    again = client.get("/api/v1/glance/alerts")
    assert again.status_code == 404
    assert calls["n"] == 0
    _sessions.clear()
    _misses.clear()


def test_tap_post_opens_glance_and_a_miss_is_empty(monkeypatch):
    from agent_coord.server.glance import _misses, _sessions, digest_for

    _sessions.clear()
    _misses.clear()
    mw._floor_cache.clear()
    mw._floor_flight.clear()
    taps = ["aaaaaaaaaa", "bbbbbbbbbb", "cccccccccc", "dddddddddd"]
    monkeypatch.setenv("AGENT_COORD_GLANCE_TAP", digest_for(taps, "word"))
    calls = {"n": 0}

    def load(*, api_only: bool = False):
        calls["n"] += 1
        return {
            "secrets": "redacted",
            "alerts": {"secrets": "redacted"},
            "office": {"secrets": "redacted", "station": "", "signed_in": False},
            "platform": {"secrets": "redacted"},
            "logs": {"secrets": "redacted"},
            "book": {"secrets": "redacted"},
            "door": {"secrets": "redacted"},
        }

    monkeypatch.setattr("agent_coord.server.glance.load_packet", load)
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    root = Path(__file__).resolve().parents[2]
    client = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    closed = client.get("/api/v1/glance/alerts")
    assert closed.status_code == 404
    assert calls["n"] == 0
    miss = client.post("/api/v1/glance/tap", json={"taps": list(reversed(taps)), "passphrase": "word"})
    assert miss.status_code == 404
    assert "aaaaaaaaaa" not in miss.text
    assert "word" not in miss.text
    opened = client.post("/api/v1/glance/tap", json={"taps": taps, "passphrase": "word"})
    assert opened.status_code == 200
    assert opened.json()["open"] is True
    assert "aaaaaaaaaa" not in opened.text
    page = client.get("/api/v1/glance/alerts")
    assert page.status_code == 200
    assert calls["n"] == 1
    _sessions.clear()
    _misses.clear()


def test_slowest_command_is_max_ms_in_the_hour():
    from datetime import timezone

    from agent_coord.server.glance import _UNSTORED

    since = datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)
    text = "\n".join(
        [
            "2026-10-06T20:00:00Z op=verb ms=9000.0 desk=old verb=claim ok=1",
            "2026-10-06T21:10:00Z op=api.mill.reply ms=50.0",
            "2026-10-06T21:12:00Z op=verb ms=40.0 desk=cold-ab-a verb=reply ok=1",
            "2026-10-06T21:20:00Z op=verb ms=180.5 desk=cold-ab-b verb=todo ok=0 err=no such need",
            "2026-10-06T21:30:00Z op=verb.extra ms=9999.0 desk=nope verb=skip ok=1",
        ]
    )
    assert slowest_command_text(text, since) == {
        "verb": "todo",
        "ms": 180.5,
        "desk": "cold-ab-b",
        "ok": 0,
        "err": "no such need",
    }
    assert "slowest command name" not in _UNSTORED


def test_slowest_command_reads_http_and_ws_transports():
    from datetime import timezone

    since = datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)
    http_slow = "\n".join(
        [
            "2026-10-06T21:12:00Z op=verb ms=40.0 desk=cold-ab-a verb=reply ok=1",
            "2026-10-06T21:15:00Z op=api.mill.hold ms=900.0 status=400 owner=cold-ab-c err=hold busy",
            "2026-10-06T21:16:00Z op=api.floor ms=5000.0 status=200",
            "2026-10-06T21:17:00Z op=api.mill ms=7000.0 status=200",
        ]
    )
    assert slowest_command_text(http_slow, since) == {
        "verb": "hold",
        "ms": 900.0,
        "desk": "cold-ab-c",
        "ok": 0,
        "err": "hold busy",
    }
    ws_slow = "\n".join(
        [
            "2026-10-06T21:15:00Z op=api.mill.send ms=90.0 status=200 owner=cold-ab-c",
            "2026-10-06T21:18:00Z op=verb ms=300.0 desk=cold-ab-d verb=hold ok=1",
        ]
    )
    assert slowest_command_text(ws_slow, since) == {"verb": "hold", "ms": 300.0, "desk": "cold-ab-d", "ok": 1}


def test_slowest_command_err_is_trimmed_and_kept_only_there():
    from datetime import timezone

    since = datetime(2026, 10, 6, 21, 0, tzinfo=timezone.utc)
    long_err = "x" * 400
    text = "2026-10-06T21:15:00Z op=api.mill.todo ms=12.0 status=500 owner=cold-ab-e err=" + long_err
    got = slowest_command_text(text, since)
    assert got == {"verb": "todo", "ms": 12.0, "desk": "cold-ab-e", "ok": 0, "err": "x" * 160}
    ok_line = "2026-10-06T21:15:00Z op=verb ms=12.0 desk=cold-ab-e verb=send ok=1"
    assert "err" not in slowest_command_text(ok_line, since)
    sealed = seal({"logs": {"slowest_verb": got}, "book": {"err": CANARY}})
    assert sealed["logs"]["slowest_verb"]["err"] == "x" * 160
    assert CANARY not in json.dumps(sealed)
