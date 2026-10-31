"""Every book command, every argument, every bad value, on a throwaway book (#238).

The CLI runs in this process: the real parser, request body, handler, and
SPs. Only the /ws hop is replaced by dispatch_ws with the error shape the
socket returns. Each case asserts on that one call: nonzero exit, a plain
refusal (no traceback or raw DB error), and an unchanged book.
"""
from __future__ import annotations

import io
import json
import re
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from tests.client import param_cases_238 as pc
from tests.client.param_gaps_238 import GAPS
from tests.server.records.conftest import seed_names

ME = "c238-desk"
PEER = "c238-peer"
RAW = re.compile(
    r"Traceback|\b\d{4} \([0-9A-Z]{5}\)|mysql|KeyError|TypeError|ValueError|AttributeError|"
    r"NoneType|invalid literal|object has no attribute|unexpected keyword",
    re.I,
)
# Tables a refused call may still touch: per-call logs, not book state.
LOG_TABLES = {"perf", "verb_log", "rpc_log"}


class _Book:
    def __init__(self, cn):
        self._cn = cn
        self._tokens: dict = {}


class World:
    def __init__(self, cn, tmp):
        self.cn = cn
        self.book = _Book(cn)
        self.desk = ME
        self.body = tmp / "body.txt"
        self.body.write_text("hello from the matrix", encoding="utf-8")

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

    def ok(self, argv, desk=ME) -> dict:
        code, out, err = self.run(argv, desk)
        assert code == 0, (argv, out[-300:], err[-300:])
        lines = [ln for ln in out.splitlines() if ln.strip().startswith("{")]
        return json.loads(lines[-1]) if lines else {}

    def fresh(self, prefix):
        return "%s-%s" % (prefix, uuid.uuid4().hex[:8])

    def need(self, state):
        n = self.fresh("c238n")
        args = ["create", "todo", pc.P, n] + (["--status", "parked"] if state == "parked" else [])
        self.ok(args)
        if state == "claimed":
            self.ok(["claim", pc.P, n])
        return n

    def tid(self, need):
        from agent_coord.server.records import todo as rec_todo

        return int(rec_todo.find(self.cn, pc.P, need)["id"])

    def mail(self):
        row = self.ok(["send", "--to-desk", ME, "--body-file", str(self.body)], desk=PEER)
        res = row.get("result") if isinstance(row.get("result"), dict) else row
        return int(res.get("id") or res.get("mail_id"))

    def held(self):
        r = self.fresh("c238r")
        self.ok(["hold", r])
        return r

    def tid_labeled(self):
        t = self.tid(self.need("open"))
        self.ok(["label", "todo", str(t), "c238-lbl"])
        return t


    def del_roster(self):
        """Sole-member roster this desk can trash (card 879)."""
        from agent_coord.server.records import member as rec_member
        from agent_coord.server.records import name as rec_name

        r = self.fresh("c238del")
        rec_name.get_or_insert(self.cn, r, "roster")
        rec_member.put(self.cn, r, self.desk, kind="roster")
        return r

    def trashed_roster(self):
        from agent_coord.server.records import name as rec_name

        r = self.del_roster()
        rec_name.trash(self.cn, r, "roster", by=self.desk)
        return r

    def purgeable_roster(self):
        """Trashed unreferenced roster (no cards/mail) for mill purge."""
        return self.trashed_roster()

    def fill(self, argv):
        joined = " ".join(argv)
        makers = [
            ("N_CLAIMED", lambda: self.need("claimed")),
            ("N_PARKED", lambda: self.need("parked")),
            ("NEWN", lambda: self.fresh("c238n")),
            ("N", lambda: self.need("open")),
            ("TID_LBL", self.tid_labeled),
            ("TID", lambda: self.tid(self.need("open"))),
            ("MAIL", self.mail),
            ("RES", lambda: self.fresh("c238r")),
            ("HELD", self.held),
            ("DEL", self.del_roster),
            ("TRASHED", self.trashed_roster),
            ("PURGEABLE", self.purgeable_roster),
        ]
        subs = {"P": pc.P, "ME": ME, "PEER": PEER, "LBL": "c238-lbl", "BODY": str(self.body)}
        for key, make in makers:
            if "{%s}" % key in joined:
                subs[key] = str(make())
        out = []
        for w in argv:
            for k, v in subs.items():
                w = w.replace("{%s}" % k, v)
            out.append(w)
        return out

    def checksum(self):
        cur = self.cn.cursor()
        try:
            cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
            tables = [r[0] for r in cur.fetchall() if r[0] not in LOG_TABLES]
            cur.execute("CHECKSUM TABLE " + ", ".join("`%s`" % t for t in tables))
            return {r[0]: r[1] for r in cur.fetchall()}
        finally:
            cur.close()


def _dispatch(w: World, body: dict):
    """The /ws hop: dispatch_ws, then the reply shape asgi and mill_ws_call give."""
    from agent_coord.client.outbound import canonical_command
    from agent_coord.server.api.mill import rpc
    from agent_coord.server.asgi import hold_envelope_ok

    command = canonical_command(str(body.get("verb") or body.get("cmd") or ""))
    args = {k: v for k, v in dict(body).items() if k not in ("verb", "cmd", "owner", "token")}
    try:
        result = rpc.dispatch_ws(w.book, w.desk, command, args)
    except CoordError as e:
        raise CoordError(str(e)) from None
    except Exception as e:
        raise CoordError(str(e)[:240]) from None
    return {"ok": hold_envelope_ok(command, result), "result": result, "sync": []}


@pytest.fixture(scope="module")
def world(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    # the-mill is the default project for commands that still default it (#243, #244).
    seed_names(
        cn, (pc.P, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"),
        ("c238-lbl", "label"),
    )
    for d in (ME, PEER):
        here.upsert(cn, pc.P, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    mp = pytest.MonkeyPatch()
    w = World(cn, tmp_path_factory.mktemp("m238"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("m238home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(w, body))
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": w.desk, raising=False)
    yield w
    mp.undo()


def _parser():
    from agent_coord.__main__ import _build_parser

    return _build_parser()


CASES = pc.build_cases(_parser())


# Commands whose cases cannot run yet. unpark takes its parent since #246.
BLOCKED: dict[str, str] = {}


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(v, marks=[pytest.mark.xfail(strict=True, reason=BLOCKED[v])]) if v in BLOCKED else v
        for v in pc.BOOK
    ],
)
def test_base_argv_is_valid(world, command) -> None:
    """The base command succeeds, so a refusal below belongs to the bad value."""
    argv = command.split() + world.fill(pc.BOOK[command])
    code, out, err = world.run(argv)
    assert code == 0, (argv[:6], out[-300:], err[-300:])


def _params():
    out = []
    for command, dest, case, argv in CASES:
        cid = pc.case_id(command, dest, case)
        marks = [pytest.mark.xfail(strict=True, reason=GAPS[cid])] if cid in GAPS else []
        if command in BLOCKED:
            marks = [pytest.mark.skip(reason=BLOCKED[command])]
        out.append(pytest.param(command, argv, id=cid, marks=marks))
    return out


@pytest.mark.parametrize("command,argv", _params())
def test_bad_value_refused_on_the_call(world, command, argv) -> None:
    filled = command.split() + world.fill(argv)
    before = world.checksum()
    code, out, err = world.run(filled)
    after = world.checksum()
    text = (err + out)[-2000:]
    changed = sorted(t for t in after if after.get(t) != before.get(t))
    assert code != 0, "accepted: exit 0: " + text[-300:]
    assert text.strip(), "refused with no message"
    assert not RAW.search(text), "raw error: " + text[-300:]
    assert changed == [], "stored on a refused call: %s" % changed
