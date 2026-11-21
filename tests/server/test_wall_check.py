# -*- coding: utf-8 -*-
"""#36+#37: floor.version + mill wall-check vs stale projects filter."""
from __future__ import annotations

import json

from agent_coord.lib.observe import board_view
from agent_coord.install.packver import package_version
from agent_coord.server.wall_check import filter_hides_live, wall_check


class _Resp:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "application/json"):
        self._body = body
        self.status = status
        self.headers = {"content-type": content_type}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_filter_hides_live():
    assert filter_hides_live(live_agents=6, filtered_agents=0) is True
    assert filter_hides_live(live_agents=6, filtered_agents=6) is False
    assert filter_hides_live(live_agents=0, filtered_agents=0) is False


def test_board_view_keeps_floor_version():
    floor = {
        "version": "0.2.5",
        "node": "box",
        "projects": ["the-mill"],
        "events": [],
        "mailbox": [],
        "locks": [],
        "agents": [],
        "kpis": [],
        "needs": [],
        "issues": [],
        "spend": {},
        "spend_lines": [],
    }
    out = board_view(floor)
    assert out["version"] == "0.2.5"


def test_wall_check_expect_empty_exit_2():
    mill_ver = package_version()
    html = b'<html id="x"><div id="pane-session"></div><div id="here"></div><div id="pane-mail"></div></html>'
    floor = {
        "version": mill_ver,
        "live_agents": 2,
        "agents": [
            {"project_id": "the-mill", "alive": True, "owner": "a"},
            {"project_id": "the-mill", "alive": True, "owner": "b"},
        ],
        "mailbox": [{"project_id": "the-mill"}],
    }

    def opener(req, timeout=20, context=None):
        url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
        if "/api/v1/agents" in url:
            return _Resp(json.dumps(floor).encode("utf-8"))
        return _Resp(html, content_type="text/html")

    row, code = wall_check(
        base="https://192.0.2.10",
        project_filter="agent-coord",
        expect_empty=True,
        urlopen=opener,
        ssl_context=object(),
    )
    assert row["ok"] is True
    assert row["version_match"] is True
    assert row["api"]["version"] == mill_ver
    assert code == 2
    assert "hides" in (row.get("bug") or "")


def test_wall_check_office_uses_alias_host(monkeypatch):
    from agent_coord.__main__ import main

    seen = {}

    def fake(**kwargs):
        seen["base"] = kwargs.get("base")
        return {"ok": True}, 0

    monkeypatch.setattr("agent_coord.server.wall_check.wall_check", fake)
    monkeypatch.setattr("agent_coord.client.offices.read_alias", lambda name, dest=None: "203.0.113.9")
    rc = main(["wall-check", "--office", "office-alias"])
    assert rc == 0
    assert seen["base"] == "https://203.0.113.9"


def test_wall_check_base_wins_over_office(monkeypatch):
    from agent_coord.__main__ import main

    seen = {}

    def fake(**kwargs):
        seen["base"] = kwargs.get("base")
        return {"ok": True}, 0

    monkeypatch.setattr("agent_coord.server.wall_check.wall_check", fake)
    monkeypatch.setattr("agent_coord.client.offices.read_alias", lambda name, dest=None: "203.0.113.9")
    rc = main(["--office", "office-alias", "wall-check", "--base", "https://192.0.2.10"])
    assert rc == 0
    assert seen["base"] == "https://192.0.2.10"


def test_wall_check_office_without_alias_refuses(monkeypatch, capsys):
    from agent_coord.__main__ import main

    monkeypatch.setattr("agent_coord.client.offices.read_alias", lambda name, dest=None: "")
    rc = main(["wall-check", "--office", "missing-office"])
    cap = capsys.readouterr()
    assert rc == 1
    obj = json.loads(cap.out)
    assert obj["code"] == "refused"
    assert obj["refusal"] == "wall-check: --office missing-office has no local alias; pass --base"
    assert "no local alias" not in cap.err and "missing-office" not in cap.err
    assert cap.err.strip() == "refused %s" % obj["id"]


def test_wall_check_missing_version_fails():
    html = b'<html><div id="pane-session"></div></html>'
    floor = {"live_agents": 1, "agents": [{"project_id": "the-mill", "alive": True}], "mailbox": []}

    def opener(req, timeout=20, context=None):
        url = req.get_full_url() if hasattr(req, "get_full_url") else str(req)
        if "/api/v1/agents" in url:
            return _Resp(json.dumps(floor).encode("utf-8"))
        return _Resp(html, content_type="text/html")

    row, code = wall_check(
        base="https://192.0.2.10",
        urlopen=opener,
        ssl_context=object(),
    )
    assert code == 1
    assert row["ok"] is False
    assert "version" in (row.get("bug") or "")
