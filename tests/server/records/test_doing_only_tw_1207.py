"""Card 1207 (the owner, 2026-11-13): doing is written only by tw.exe. A check, not a rule.

(a) No SQL routine or runtime Python inserts a doing row except mill_doing_task (the tw birth).
(b) On a real book, every desk command that used to take --doing (send, reply, mark, create todo,
    claim, pass, hold, drop, score) and clock-out leave the doing table untouched; one tw start adds
    exactly one row.
(c) --doing and --waiting-on are gone from the CLI, and a body that still carries one is refused.
(d) `mill connected` serves n and doings (wall-ui shape) and nothing from the dropped columns.
The CLI runs in this process (real parser, request body, handler and SPs); only the /ws hop is
replaced by dispatch_ws, as in the #238 matrix.
"""
from __future__ import annotations

import io
import json
import re
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records.db import scalar_done
from tests.server.records.conftest import seed_names

ME = "d1207-me"
PEER = "d1207-peer"
R = "r1207"
ROOT = Path(__file__).resolve().parents[3]
_INSERT = re.compile(r"\b(INSERT|REPLACE)\s+(IGNORE\s+)?INTO\s+`?doing`?[\s(]", re.I)
FORMER_DOING_COMMANDS = ("send", "reply", "mark", "claim", "unclaim", "assign", "pass", "todo", "unpark",
                         "hold", "drop", "score")


def _routines(text: str):
    """(name, body) for each CREATE PROCEDURE/FUNCTION/TRIGGER in a routine file."""
    parts = re.split(r"(?im)^CREATE\s+(?:PROCEDURE|FUNCTION|TRIGGER)\s+`?(\w+)`?", text)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


# (a) static -------------------------------------------------------------------------

def test_only_mill_doing_task_inserts_a_doing_row_in_sql():
    writers = []
    for path in sorted((ROOT / "agent_coord/server/sql").glob("*.sql")):
        if path.name.startswith(("migrate_", "migrations", "wipe")):
            continue  # install-time migrations, not a runtime path
        for name, body in _routines(path.read_text(encoding="utf-8")):
            if _INSERT.search(body):
                writers.append(f"{path.name}:{name}")
    assert writers == ["sp_doing.sql:mill_doing_task"], writers


def test_no_runtime_python_inserts_a_doing_row():
    hits = []
    for path in sorted((ROOT / "agent_coord").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("agent_coord/install/"):
            continue  # install-time migrations
        if _INSERT.search(path.read_text(encoding="utf-8")):
            hits.append(rel)
    assert hits == [], hits


def test_the_cli_has_no_doing_or_waiting_on_flag():
    from agent_coord import __main__ as cli

    sub = next(a for a in cli._build_parser()._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
    bad = []
    for name, parser in sub.choices.items():
        for act in parser._actions:
            if {"--doing", "--waiting-on"} & set(act.option_strings):
                bad.append(f"{name} {act.option_strings}")
    assert bad == [], bad


pytestmark = pytest.mark.sql


class _Book:
    def __init__(self, cn):
        self._cn = cn
        self._tokens: dict = {}


def _dispatch(w, body: dict):
    from agent_coord.client.outbound import canonical_command
    from agent_coord.server.api.mill import rpc
    from agent_coord.server.asgi import hold_envelope_ok

    command = canonical_command(str(body.get("verb") or body.get("cmd") or ""))
    args = {k: v for k, v in dict(body).items() if k not in ("verb", "cmd", "owner", "token")}
    try:
        result = rpc.dispatch_ws(w.book, w.desk, command, args)
    except CoordError as e:
        raise CoordError(str(e)) from None
    return {"ok": hold_envelope_ok(command, result), "result": result, "sync": []}


class World:
    def __init__(self, cn, tmp):
        self.cn = cn
        self.book = _Book(cn)
        self.desk = ME
        self.body = tmp / "body.txt"
        self.body.write_text("a letter for card 1207", encoding="utf-8")

    def run(self, argv, desk=ME):
        from agent_coord import __main__ as cli

        self.desk = desk
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = int(cli.main(list(argv)) or 0)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 2)
            except CoordError as e:
                print(str(e), file=sys.stderr)
                code = 1
        return code, out.getvalue(), err.getvalue()

    def ok(self, argv, desk=ME):
        code, out, err = self.run(argv, desk)
        assert code == 0, (argv, out[-400:], err[-400:])
        lines = [ln for ln in out.splitlines() if ln.strip().startswith(("{", "["))]
        row = json.loads(lines[-1]) if lines else {}
        return row.get("result", row) if isinstance(row, dict) else row

    def letter(self, to=ME, desk=PEER) -> int:
        res = self.ok(["send", "--to-desk", to, "--body-file", str(self.body)], desk=desk)
        return int(res["id"])

    def card(self, desk=PEER, **kw) -> tuple[str, int]:
        from agent_coord.server.records import todo as rec_todo

        need = "n1207-" + uuid.uuid4().hex[:6]
        self.ok(["create", "todo", R, need, "--detail", "card for card 1207"], desk=desk)
        return need, int(rec_todo.find(self.cn, R, need)["id"])

    def me(self, desk=ME) -> dict:
        rows = self.ok(["connected", "--who", desk])
        assert len(rows) == 1, rows
        return rows[0]

    def doing_n(self) -> int:
        return int(scalar_done(self.cn, "SELECT COUNT(*) FROM doing"))


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for d in (ME, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d))
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d1207"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d1207home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()




def _joined(w, desk: str) -> str:
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(w.cn, (desk, "desk"))
    here.upsert(w.cn, R, desk, "builder", token_hash=token_hash("tok-" + desk))
    return desk


def _hist(w, desk: str) -> list[dict]:
    return w.ok(["connected", "--history", "--who", desk])["history"]


def _tw(w, desk: str, watch: str, kind: str, **kw) -> None:
    """One tw.event, the only doing writer."""
    from agent_coord.server.api.mill import rpc

    rpc._h_tw_event(SimpleNamespace(_cn=w.cn), {"watch_id": watch, "kind": kind, **kw}, R, desk)
    w.cn.commit()


def test_clock_out_ends_live_doings_as_cleared(w, monkeypatch):
    from agent_coord.server.records import join as here

    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    desk = _joined(w, "d1207-out-" + uuid.uuid4().hex[:4])
    _tw(w, desk, "a", "start")
    _tw(w, desk, "b", "start")
    assert w.me(desk)["n"] == 2
    here.delete(w.cn, R, desk)
    w.cn.commit()
    hist = _hist(w, desk)
    assert [e["ended_by"] for e in hist] == ["cleared", "cleared"]


# (b) real book ----------------------------------------------------------------------

def test_desk_commands_write_no_doing_row(w):
    from agent_coord.server.records import score as rec_score

    before = w.doing_n()
    mid = w.letter()
    w.ok(["reply", str(mid), "--body-file", str(w.body)])
    w.ok(["mark", str(mid)])
    need, _tid = w.card()
    w.ok(["claim", R, need])
    w.ok(["pass", R, need])
    w.ok(["pass", R, need, "--done"], desk=PEER)
    res_name = "r1207-" + uuid.uuid4().hex[:6]
    w.ok(["hold", res_name])
    w.ok(["drop", res_name])
    rec_score.point_add(w.cn, R, ME, "k1207", 3.0)
    w.cn.commit()
    w.ok(["score", R, "k1207"])
    assert w.doing_n() == before


def test_one_tw_start_adds_exactly_one_doing_row(w, monkeypatch):
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    before = w.doing_n()
    _tw(w, ME, "w1207", "start")
    assert w.doing_n() == before + 1
    view = w.me()
    assert view["n"] >= 1 and view["doings"][0]["state"] == "active"


# (c) gone flags ---------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--doing", "--waiting-on"])
def test_gone_flags_are_refused_by_the_parser(w, flag):
    code, _out, err = w.run(["mark", "1", flag, "x"])
    assert code == 2 and flag in err


@pytest.mark.parametrize("key", ["doing", "waiting_on"])
def test_a_body_that_carries_a_gone_key_is_refused(w, key):
    from agent_coord.server.api.mill import rpc

    before = w.doing_n()
    with pytest.raises(CoordError, match="is gone"):
        rpc.dispatch_ws(w.book, ME, "hold", {"resource": "r1207-x", key: "something"})
    assert w.doing_n() == before


# (d) the read -----------------------------------------------------------------------

def test_connected_serves_n_and_doings_only(w):
    view = w.me()
    assert {"n", "doings"} <= set(view)
    for gone in ("doing", "on", "act", "last", "waiting_on", "waiting_on_it", "tasks", "line", "age", "idle"):
        assert gone not in view, gone
    for row in view["doings"]:
        assert set(row) == {"id", "created", "text", "state", "state_at", "card"}
        assert row["created"].endswith("Z") and row["state_at"].endswith("Z")
