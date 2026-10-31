"""tools/probe_deleted_rows.py (#160) with a fake sitting connect. No SQL."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from agent_coord.client.outbound import PROBE, COMMANDS, WALL
from agent_coord.server.api.mill.rpc import HANDLERS

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("probe_deleted_rows", ROOT / "tools" / "probe_deleted_rows.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_probe_is_wall_rpc_not_a_skill_command() -> None:
    assert "probe-delete" in PROBE
    assert "probe-delete" in WALL and "probe-delete" in HANDLERS
    assert "probe-delete" not in COMMANDS


def test_probe_is_not_a_mill_subcommand() -> None:
    src = (ROOT / "agent_coord" / "__main__.py").read_text(encoding="utf-8")
    assert "probe-delete" not in src


class _Fake:
    def __init__(self):
        self.sent = []

    def __call__(self, body):
        self.sent.append(dict(body))
        v = body["verb"]
        if v == "open":
            return {"ok": True, "result": {"id": 41, "project_id": body["project"]}}
        if v == "score":
            return {"ok": True, "result": [{"id": 42}]}
        if v == "probe-delete":
            return {"ok": True, "result": {"type": body["type"], "id": body["id"], "state": "deleted", "deleted": "x"}}
        if v == "trail":
            return {"ok": True, "result": {"nodes": [{"kind": "todo", "id": 41, "state": "deleted"}]}}
        if v in ("roster", "retire"):
            return {"ok": True, "result": [{"name": body["slug"]}]}
        raise AssertionError(v)


def test_run_makes_and_deletes_fixture_rows(capsys) -> None:
    mod = _tool()
    fake = _Fake()
    assert mod.main(["run", "--project", "t-0a1b2c3d"], call=fake) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["project"] == "t-0a1b2c3d"
    assert out["todo"]["id"] == 41 and out["score"]["id"] == 42
    commands = [b["verb"] for b in fake.sent]
    assert commands == ["open", "score", "probe-delete", "probe-delete", "trail"]
    assert all(b.get("project") == "t-0a1b2c3d" for b in fake.sent if b["verb"] in ("open", "score"))


def test_run_default_project_is_fresh_fixture(capsys) -> None:
    mod = _tool()
    fake = _Fake()
    assert mod.main(["run"], call=fake) == 0
    proj = json.loads(capsys.readouterr().out)["project"]
    assert mod.FIXTURE.match(proj)


def test_run_refuses_real_project_without_sending(capsys) -> None:
    mod = _tool()
    fake = _Fake()
    assert mod.main(["run", "--project", "the-mill"], call=fake) == 2
    assert fake.sent == []
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_office_refusal_is_exit_1(capsys) -> None:
    mod = _tool()

    def refuse(body):
        raise RuntimeError("probe-delete: todo 7 was not made by this desk; refused")

    assert mod.main(["delete", "--type", "todo", "--id", "7"], call=refuse) == 1
    assert "not made by this desk" in json.loads(capsys.readouterr().out)["error"]


def test_run_flags_a_row_that_did_not_go_deleted(capsys) -> None:
    mod = _tool()
    fake = _Fake()

    def half(body):
        out = fake(body)
        if body["verb"] == "trail":
            return {"ok": True, "result": {"nodes": [{"kind": "todo", "id": 41, "state": "open"}]}}
        return out

    assert mod.main(["run", "--project", "t-0a1b2c3d"], call=half) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_default_run_makes_its_roster_and_retires_it(capsys) -> None:
    """#644: 0.7 rosters must exist; the tool makes its own and retires it (F82)."""
    mod = _tool()
    fake = _Fake()
    assert mod.main(["run"], call=fake) == 0
    out = json.loads(capsys.readouterr().out)
    proj = out["project"]
    commands = [b["verb"] for b in fake.sent]
    assert commands == ["roster", "open", "score", "probe-delete", "probe-delete", "trail", "retire"]
    made, gone = fake.sent[0], fake.sent[-1]
    assert made == {"verb": "roster", "slug": proj, "confirm": proj, "yes": True}
    assert gone == {"verb": "retire", "slug": proj, "confirm": proj, "yes": True, "name_type": "roster"}
    assert out["roster"] == {"made": True, "retired": True, "slug": proj}


def test_default_run_retires_its_roster_after_a_refusal(capsys) -> None:
    mod = _tool()
    fake = _Fake()

    def call(body):
        if body["verb"] == "open":
            raise RuntimeError("todo: refused")
        return fake(body)

    assert mod.main(["run"], call=call) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and "refused" in out["error"]
    assert [b["verb"] for b in fake.sent] == ["roster", "retire"]


def test_named_project_is_the_callers_roster(capsys) -> None:
    mod = _tool()
    fake = _Fake()
    assert mod.main(["run", "--project", "t-0a1b2c3d"], call=fake) == 0
    assert "roster" not in [b["verb"] for b in fake.sent]
    assert "retire" not in [b["verb"] for b in fake.sent]


def test_doc_names_no_anonymous_events_read() -> None:
    doc = (ROOT / "docs" / "dev" / "PROBE-DELETED-ROWS.md").read_text(encoding="utf-8")
    assert "/api/v1/events?project=" not in doc
    src = (ROOT / "tools" / "probe_deleted_rows.py").read_text(encoding="utf-8")
    assert "/api/v1/events:" not in src


def test_default_run_keeps_probe_when_retire_needs_admin(capsys) -> None:
    """#721: a non-Admin retire refusal must not drop the probe result."""
    mod = _tool()
    fake = _Fake()

    def admin_only_retire(body):
        if body["verb"] == "retire":
            raise RuntimeError("mill Admin required")
        return fake(body)

    assert mod.main(["run"], call=admin_only_retire) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["trail_state"] == "deleted"
    assert out["roster"]["made"] is True and out["roster"]["retired"] is False
    assert out["roster"]["slug"] == out["project"]
    assert "Admin" in out["roster"]["reason"]
