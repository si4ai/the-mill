"""#818 PR B on a real book: --doing on activity commands, read by `mill connected`. Row F118.

The CLI runs in this process (real parser, request body, handler and SPs);
only the /ws hop is replaced by dispatch_ws, as in the #238 matrix.

(a) --doing on send, reply, mark, create todo, claim, pass, note, hold, drop
    and score writes one doing entry linked to that command's own item;
(b) the newest entry is current; a reply under the letter or a pass without
    --doing ends it; a mark never does; a reply or pass that carries --doing
    starts the next one;
(c) `mill connected` shows doing, on, age, idle/last and who is waiting on
    the desk (unanswered letters, claimed cards others watch); --history pages;
(d) cards have no title: create todo --doing stores no doing key, and a
    legacy stored key shows as the head of the detail;
(e) there is no `mill doing` command; join and invite placeholders write no
    doing text; a missing or retired item is refused;
    a refused or over-long --doing stores nothing; a command and its doing
    row commit or roll back together (one transaction, pokes after commit);
(f) an entry ends on a real event only: clock-out or reset ends it (ended_by
    cleared, the empty row is never a doing); a pass or done by the desk ends
    its card entry, a drop by the desk its hold entry; a later note, another
    desk's done, a pass --back or taking the hold again never ends one or
    brings an ended one back; a drop --doing starts the next entry.
"""
from __future__ import annotations

import io
import json
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records.db import rows_done, scalar_done
from tests.server.records.conftest import seed_names

ME = "d818-me"
PEER = "d818-peer"
R = "r818"


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
        self.body.write_text("a letter for #818", encoding="utf-8")

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

        need = "n818-" + uuid.uuid4().hex[:6]
        self.ok(["create", "todo", R, need, "--detail", "card for #818"], desk=desk)
        return need, int(rec_todo.find(self.cn, R, need)["id"])

    def me(self, desk=ME) -> dict:
        rows = self.ok(["connected", "--desk", desk])
        assert len(rows) == 1, rows
        return rows[0]

    def entries(self, desk=ME) -> list[dict]:
        return rows_done(
            self.cn,
            "SELECT g.id, g.text, g.on_type, g.on_id FROM doing g JOIN name n ON n.id = g.desk_id"
            " WHERE n.type = 'desk' AND n.name = %s ORDER BY g.id",
            (desk,),
        )


@pytest.fixture(scope="module")
def w(cn, tmp_path_factory):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(cn, (R, "roster"), ("the-mill", "roster"), (ME, "desk"), (PEER, "desk"))
    for d in (ME, PEER):
        here.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    mp = pytest.MonkeyPatch()
    world = World(cn, tmp_path_factory.mktemp("d818"))
    mp.setenv("AGENT_COORD_MILL_HOME", str(tmp_path_factory.mktemp("d818home")))
    mp.setenv("AGENT_COORD_MILL_URL", "http://127.0.0.1:9")
    mp.setattr("agent_coord.client.http.mill_http_call", lambda body: _dispatch(world, body))
    mp.setattr("agent_coord.server.api.mill.rpc._require_live_ws", lambda owner: None)
    for mod in ("agent_coord.client.http", "agent_coord.client.outbound"):
        mp.setattr(mod + ".resolve_desk_owner", lambda cli="": world.desk, raising=False)
    yield world
    mp.undo()


# (e) placeholders and the gone command ------------------------------------------

def test_join_placeholder_writes_no_doing_text(w):
    texts = [r["text"] for r in w.entries(ME)]
    assert "present" not in texts and "invited" not in texts


def test_invite_placeholder_writes_no_doing_text(w):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(w.cn, ("d818-new", "desk"))
    here.upsert(w.cn, R, "d818-new", "builder", token_hash=token_hash("tok-new"), doing="invited")
    assert all(r["text"] in ("", None) for r in w.entries("d818-new"))


def test_a_missing_or_retired_item_is_refused(w):
    from agent_coord.server.records import doing as rec_doing

    top = int(scalar_done(w.cn, "SELECT COALESCE(MAX(id), 0) FROM mail"))
    with pytest.raises(Exception, match="the item is gone"):
        rec_doing.put(w.cn, ME, "x", "mail", top + 1000)
    with pytest.raises(Exception, match="the item is gone"):
        rec_doing.put(w.cn, ME, "x", "room", 1)
    need, tid = w.card()
    w.ok(["retire", "todo", R, need, "--yes"], desk=PEER)
    with pytest.raises(Exception, match="the item is gone"):
        rec_doing.put(w.cn, ME, "x", "todo", tid)


def test_there_is_no_doing_command(w):
    code, out, err = w.run(["doing", "x"])
    assert code == 2 and "invalid choice" in err


# (a)+(b) reply, mark ---------------------------------------------------------

def test_reply_doing_links_the_letter_replied_to_and_a_plain_reply_ends_it(w):
    mid = w.letter()
    res = w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "answering the ask"])
    assert res["doing_entry"]["on"] == f"mail-{mid}"
    view = w.me()
    assert view["doing"] == "answering the ask" and view["on"] == f"mail-{mid}"
    assert view["age"].endswith("s")
    assert f'doing "answering the ask" on mail-{mid}' in view["line"]
    # A reply under that letter without --doing ends it.
    w.ok(["reply", str(mid), "--body-file", str(w.body)])
    view = w.me()
    assert view["doing"] == "" and "idle" in view
    # 0.8.0: last carries act (focus); a plain reply still ends it as finished.
    assert view["last"]["doing"] == "answering the ask" and view["last"]["on"] == f"mail-{mid}"
    assert view["last"]["ended_by"] == "finished" and view["last"].get("act") == "focus"


def test_mark_never_ends_a_doing(w):
    mid = w.letter()
    res = w.ok(["mark", str(mid), "--doing", "reading it"])
    assert res["doing_entry"]["on"] == f"mail-{mid}"
    w.ok(["mark", str(mid)])
    view = w.me()
    assert view["doing"] == "reading it" and view["on"] == f"mail-{mid}"


def test_send_doing_links_the_new_letter(w):
    res = w.ok(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", "asking peer"])
    assert res["doing_entry"]["on"] == f"mail-{int(res['id'])}"


def test_reply_carrying_doing_starts_the_next_one(w):
    mid = w.letter()
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "step one"])
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "step two"])
    view = w.me()
    assert view["doing"] == "step two" and view["on"] == f"mail-{mid}"


# (a)+(b)+(d) cards -------------------------------------------------------------

def test_create_todo_doing_is_a_doing_not_a_title(w):
    from agent_coord.server.records import todo as rec_todo

    need = "n818-create"
    res = w.ok(["create", "todo", R, need, "--detail", "why", "--doing", "filing the card"])
    tid = int(res["id"])
    assert "doing" not in res
    assert res["doing_entry"]["on"] == f"todo-{tid}"
    stored = json.loads(rec_todo.find(w.cn, R, need)["body"])
    assert "doing" not in stored and stored["detail"] == "why"
    card = w.ok(["todo", R, need])
    card = card[0] if isinstance(card, list) else card
    assert "doing" not in json.dumps(card).replace('"doing_', "")


def test_legacy_doing_key_is_shown_as_detail():
    from agent_coord.server.records.todo import unpack

    got = unpack(json.dumps({"slug": "old", "doing": "old title", "detail": "notes"}), 1)
    assert got["detail"] == "old title\nnotes" and "doing" not in got
    again = unpack(json.dumps({"slug": "old", "doing": "old title", "detail": "old title\nnotes"}), 1)
    assert again["detail"] == "old title\nnotes"


def test_find_ranks_on_need_roster_and_body_only():
    from agent_coord.client.http import _FIND_RANK

    assert [k for k, _, _ in _FIND_RANK] == ["need_id", "project_id", "detail"]


def test_claim_doing_then_pass_ends_it_and_pass_with_doing_starts_next(w):
    need, tid = w.card()
    res = w.ok(["claim", R, need, "--doing", "fixing it"])
    assert res["doing_entry"]["on"] == f"todo-{tid}"
    assert w.me()["doing"] == "fixing it"
    w.ok(["note", R, need, "--note", "half way", "--doing", "testing it"])
    assert w.me()["doing"] == "testing it"
    w.ok(["pass", R, need])
    view = w.me()
    assert view["doing"] == "" and view["last"]["on"] == f"todo-{tid}"
    need2, tid2 = w.card()
    w.ok(["claim", R, need2])
    w.ok(["pass", R, need2, "--doing", "waiting on review"])
    view = w.me()
    assert view["doing"] == "waiting on review" and view["on"] == f"todo-{tid2}"


# (a)+(b) hold and score ----------------------------------------------------------

def test_hold_doing_links_the_hold_and_drop_ends_it(w):
    res_name = "r818-" + uuid.uuid4().hex[:6]
    res = w.ok(["hold", res_name, "--doing", "editing the file"])
    assert res["doing_entry"]["on"].startswith("hold-")
    assert w.me()["doing"] == "editing the file"
    w.ok(["drop", res_name])
    assert w.me()["doing"] == ""


def test_refused_hold_records_no_doing(w):
    res_name = "r818-" + uuid.uuid4().hex[:6]
    w.ok(["hold", res_name], desk=PEER)
    before = len(w.entries(ME))
    code, out, err = w.run(["hold", res_name, "--doing", "want it"])
    assert code != 0
    assert len(w.entries(ME)) == before


def test_score_doing_links_the_score(w):
    res = w.ok(["score", R, "k818", "3", "--doing", "measuring"])
    assert res["doing_entry"]["on"] == f"score-{int(res['id'])}"


# (e) refusals and the command standing --------------------------------------------

def test_over_long_doing_is_refused_and_nothing_stored(w):
    before = len(w.entries(ME))
    mid = w.letter()
    n = scalar_done(w.cn, "SELECT COUNT(*) FROM mail")
    code, out, err = w.run(["reply", str(mid), "--body-file", str(w.body), "--doing", "x" * 600])
    assert code != 0 and "--doing" in (err + out)
    assert scalar_done(w.cn, "SELECT COUNT(*) FROM mail") == n
    assert len(w.entries(ME)) == before


def _counts(w) -> dict:
    return {t: scalar_done(w.cn, f"SELECT COUNT(*) FROM {t}")
            for t in ("mail", "mail_to", "tree", "activity", "push_queue", "doing", "todo", "watcher")}


def _spy_fanout(monkeypatch) -> list:
    seen: list = []
    import agent_coord.server.push as push

    real = push.fanout

    def spy(cn, type, id, hint, **k):
        seen.append((type, int(id)))
        return real(cn, type, id, hint, **k)

    monkeypatch.setattr(push, "fanout", spy)
    return seen


def test_an_item_gone_at_the_doing_write_rolls_the_whole_command_back(w, monkeypatch):
    """The item is retired between the command and the doing write: the doing
    is refused in SQL, and the reply (five writes) is rolled back with it."""
    from agent_coord.server.api.mill import rpc

    mid = w.letter()
    top = int(scalar_done(w.cn, "SELECT COALESCE(MAX(id), 0) FROM mail"))
    monkeypatch.setattr(rpc, "_doing_item", lambda *a, **k: ("mail", top + 1000))
    seen = _spy_fanout(monkeypatch)
    before = _counts(w)
    code, out, err = w.run(["reply", str(mid), "--body-file", str(w.body), "--doing", "x"])
    assert code != 0 and "item is gone" in (err + out) and "nothing was changed" in (err + out)
    assert _counts(w) == before
    assert seen == []


def test_a_failed_doing_write_rolls_the_command_back(w, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("lost the book")

    monkeypatch.setattr("agent_coord.server.records.doing.put", boom)
    seen = _spy_fanout(monkeypatch)
    before = _counts(w)
    code, out, err = w.run(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", "x"])
    assert code != 0 and "nothing was changed" in (err + out)
    assert _counts(w) == before and seen == []


def test_a_command_with_doing_commits_both_then_pokes(w, monkeypatch):
    """Pokes go out after the commit: another connection already sees the row."""
    import agent_coord.server.push as push
    from agent_coord.server.records.db import connect

    other = connect(w.cn.database)
    seen: list = []
    real = push.fanout

    def spy(cn, type, id, hint, **k):
        if type == "doing":
            seen.append(scalar_done(other, "SELECT COUNT(*) FROM doing WHERE id = %s", (int(id),)))
        return real(cn, type, id, hint, **k)

    monkeypatch.setattr(push, "fanout", spy)
    before = _counts(w)
    res = w.ok(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", "asking again"])
    other.close()
    assert "doing_error" not in res and res["doing_entry"]["on"] == f"mail-{int(res['id'])}"
    after = _counts(w)
    assert after["mail"] == before["mail"] + 1 and after["doing"] == before["doing"] + 1
    assert seen == [1]


def test_a_list_command_with_doing_is_all_or_nothing(w):
    """pass a,b --doing: one card refused rolls back the other card too."""
    from agent_coord.server.records import todo as rec_todo

    need, tid = w.card()
    w.ok(["claim", R, need])
    before = _counts(w)
    code, out, err = w.run(["pass", R, f"{need},n818-nosuch", "--doing", "both"])
    assert code != 0 and "nothing was changed" in (err + out)
    assert rec_todo.find(w.cn, R, need)["status"] == "claimed"
    assert _counts(w) == before



def _transient(errno: int):
    """The class the connector really raises: InternalError for 1213, DatabaseError for 1205."""
    from mysql.connector import errors

    state = "40001" if errno == 1213 else "HY000"
    return errors.get_mysql_exception(errno, f"injected {errno}", state)


def _fail_sp(monkeypatch, prefix: str, errno: int, times: int) -> dict:
    """The first `times` calls of a procedure named prefix* inside a --doing request raise errno."""
    import agent_coord.server.records.db as db

    real = db._run_proc
    n = {"k": 0}

    def flaky(cur, name, args):
        if name.startswith(prefix) and db._REQ_TX and n["k"] < times:
            n["k"] += 1
            raise _transient(errno)
        return real(cur, name, args)

    monkeypatch.setattr(db, "_run_proc", flaky)
    return n


@pytest.mark.parametrize("errno", [1213, 1205, 2013])
def test_a_transient_error_in_the_doing_write_retries_the_whole_request(w, monkeypatch, errno):
    """Validator probes c6 and c6b: the doing write hits a deadlock, lock wait or
    lost connection once; the whole request runs again and lands once."""
    from agent_coord.server.records import doing as rec_doing

    real = rec_doing.put
    n = {"k": 0}

    def flaky(cn, *a, **k):
        n["k"] += 1
        if n["k"] == 1:
            raise _transient(errno)
        return real(cn, *a, **k)

    monkeypatch.setattr(rec_doing, "put", flaky)
    seen = _spy_fanout(monkeypatch)
    before = _counts(w)
    res = w.ok(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", f"retry {errno}"])
    after = _counts(w)
    assert n["k"] == 2
    assert after["mail"] == before["mail"] + 1 and after["doing"] == before["doing"] + 1
    assert [s for s in seen if s[0] == "doing"] == [("doing", int(res["doing_entry"]["id"]))]


@pytest.mark.parametrize("errno", [1213, 1205])
def test_a_transient_error_in_the_command_retries_the_whole_request(w, monkeypatch, errno):
    """Validator probe c8: the command's own procedure hits a deadlock or lock wait once."""
    n = _fail_sp(monkeypatch, "mill_mail", errno, 1)
    before = _counts(w)
    w.ok(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", f"again {errno}"])
    after = _counts(w)
    assert n["k"] == 1
    assert after["mail"] == before["mail"] + 1 and after["doing"] == before["doing"] + 1


@pytest.mark.parametrize("errno", [1213, 1205])
def test_a_transient_error_that_outlasts_the_retry_is_refused_and_changes_nothing(w, monkeypatch, errno):
    """Validator probe c9, with the retry in place: it fails both times, so the
    reply says the --doing command was refused and nothing was changed."""
    n = _fail_sp(monkeypatch, "mill_mail", errno, 99)
    seen = _spy_fanout(monkeypatch)
    before = _counts(w)
    code, out, err = w.run(["send", "--to-desk", PEER, "--body-file", str(w.body), "--doing", f"busy {errno}"])
    txt = err + out
    assert code != 0 and "send --doing refused" in txt and "nothing was changed" in txt, txt
    assert str(errno) in txt
    assert n["k"] == 2
    assert _counts(w) == before and seen == []


# (c) the read ------------------------------------------------------------------

def test_connected_shows_who_is_waiting_on_the_desk(w):
    mid = w.letter()
    need, tid = w.card()
    w.ok(["claim", R, need])
    w.ok(["watch", "todo", str(tid)], desk=PEER)
    view = w.me()
    letters = view["waiting_on_it"]["letters"]
    assert letters["n"] >= 1 and letters["newest"][0] == {"id": f"mail-{mid}", "from": PEER, "age": letters["newest"][0]["age"], "asked": True}
    assert len(letters["newest"]) <= 3
    cards = view["waiting_on_it"]["cards"]
    assert cards["n"] >= 1 and any(c["id"] == f"todo-{tid}" and PEER in c["watchers"] for c in cards["newest"])
    assert "Waiting on it:" in view["line"] and f"mail-{mid}" in view["line"]
    # Replying under the letter takes it off the list.
    w.ok(["reply", str(mid), "--body-file", str(w.body)])
    assert all(x["id"] != f"mail-{mid}" for x in w.me()["waiting_on_it"]["letters"]["newest"])


def test_connected_roster_is_optional_and_lists_active_desks(w):
    rows = w.ok(["connected"])
    assert {ME, PEER} <= {r["owner"] for r in rows}
    rows = w.ok(["connected", R])
    assert {ME, PEER} <= {r["owner"] for r in rows}
    code, out, err = w.run(["connected", "--desk", "d818-nobody"])
    assert code != 0 and "no desk" in (err + out)


def test_rows_from_before_818_are_not_a_doing(w):
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(w.cn, ("d818-old", "desk"))
    here.upsert(w.cn, R, "d818-old", "builder", token_hash=token_hash("tok-old"), doing="todo | member | old text")
    assert any(r["text"] for r in w.entries("d818-old"))
    view = w.me("d818-old")
    assert view["doing"] == "" and "last" not in view and view["line"].startswith("d818-old: idle.")
    hist = w.ok(["connected", "--history", "--desk", "d818-old"])
    assert hist["history"] == [] and hist["page"]["entries"] == 0


def test_history_says_how_an_entry_ended(w):
    need, tid = w.card()
    w.ok(["claim", R, need, "--doing", "first"])
    w.ok(["note", R, need, "--note", "x", "--doing", "second"])
    w.ok(["pass", R, need])
    rows = w.ok(["connected", "--history", "--desk", ME])["history"]
    by = {r["doing"]: r for r in rows[:2]}
    assert by["second"]["ended_by"] == "finished" and by["first"]["ended_by"] == "newer"


def test_history_lists_entries_with_ended_and_pages(w):
    need, _ = w.card()
    w.ok(["claim", R, need, "--doing", "still on it"])
    got = w.ok(["connected", "--history", "--desk", ME])
    hist = got["history"]
    assert hist and all(e["desk"] == ME and e["doing"] for e in hist)
    assert any(e["ended"] for e in hist) and any(not e["ended"] for e in hist)
    assert got["page"]["n"] == 1 and got["page"]["entries"] >= len(hist)
    assert w.ok(["connected", "--history", "--since", "2999-01-01"])["history"] == []
    code, out, err = w.run(["connected", "--history", "--since", "soonish"])
    assert code != 0 and "not a date" in (err + out)
    code, out, err = w.run(["connected", "--page", "2"])
    assert code != 0 and "--history" in (err + out)


# (f) a doing ends on a real event only -------------------------------------------

def _joined(w, desk: str) -> str:
    from agent_coord.client.tokens import token_hash
    from agent_coord.server.records import join as here

    seed_names(w.cn, (desk, "desk"))
    here.upsert(w.cn, R, desk, "builder", token_hash=token_hash("tok-" + desk), doing="present")
    return desk


def _hist(w, desk: str) -> list[dict]:
    return w.ok(["connected", "--history", "--desk", desk])["history"]


@pytest.mark.parametrize("how", ["clock-out", "reset"])
def test_clock_out_or_reset_ends_the_doing(w, how):
    from agent_coord.server.records import join as here

    desk = _joined(w, f"d818-{how}-" + uuid.uuid4().hex[:4])
    mid = w.letter(to=desk)
    w.ok(["reply", str(mid), "--body-file", str(w.body), "--doing", "mid task"], desk=desk)
    assert w.me(desk)["doing"] == "mid task"
    (here.delete if how == "clock-out" else here.reset)(w.cn, R, desk)
    view = w.me(desk)
    assert view["doing"] == "" and "idle" in view
    assert view["last"]["doing"] == "mid task" and f'{desk}: idle' in view["line"]
    rows = _hist(w, desk)
    assert [r["doing"] for r in rows] == ["mid task"]  # the empty row is never a doing
    assert rows[0]["ended"] is True and rows[0]["ended_by"] == "cleared"


def test_a_later_note_or_someone_elses_done_never_ends_a_card_doing(w):
    need, tid = w.card()
    w.ok(["claim", R, need])
    w.ok(["pass", R, need, "--doing", "waiting on review"])
    assert w.me()["doing"] == "waiting on review"
    w.ok(["note", R, need, "--note", "one more thing"])
    assert w.me()["doing"] == "waiting on review"
    w.ok(["pass", R, need, "--done"], desk=PEER)
    view = w.me()
    assert view["doing"] == "waiting on review" and view["on"] == f"todo-{tid}"
    assert _hist(w, ME)[0]["ended"] is False


def test_pass_back_never_brings_back_an_ended_card_doing(w):
    need, tid = w.card()
    w.ok(["claim", R, need, "--doing", "fixing it"])
    w.ok(["pass", R, need])
    assert w.me()["doing"] == ""
    w.ok(["pass", R, need, "--back"])
    view = w.me()
    assert view["doing"] == "" and view["last"]["on"] == f"todo-{tid}"
    row = _hist(w, ME)[0]
    assert row["doing"] == "fixing it" and row["ended_by"] == "finished"


def test_done_by_the_desk_itself_ends_its_card_doing(w):
    need, tid = w.card(desk=ME)
    w.ok(["claim", R, need], desk=PEER)
    w.ok(["pass", R, need], desk=PEER)
    w.ok(["note", R, need, "--note", "reviewing", "--doing", "reviewing the ship"])
    assert w.me()["doing"] == "reviewing the ship"
    w.ok(["pass", R, need, "--done"])
    assert w.me()["doing"] == ""
    assert _hist(w, ME)[0]["ended_by"] == "finished"


def test_retaking_a_dropped_hold_never_brings_back_its_doing(w):
    res_name = "r818-" + uuid.uuid4().hex[:6]
    res = w.ok(["hold", res_name, "--doing", "editing the file"])
    hid = res["doing_entry"]["on"]
    w.ok(["drop", res_name])
    assert w.me()["doing"] == ""
    w.ok(["hold", res_name])
    view = w.me()
    assert view["doing"] == "" and view["last"]["on"] == hid
    row = _hist(w, ME)[0]
    assert row["doing"] == "editing the file" and row["ended_by"] == "finished"


def test_drop_doing_replaces_the_hold_doing_and_stays_current(w):
    res_name = "r818-" + uuid.uuid4().hex[:6]
    res = w.ok(["hold", res_name, "--doing", "editing the file"])
    hid = res["doing_entry"]["on"]
    got = w.ok(["drop", res_name, "--doing", "handing the file over"])
    assert got["doing_entry"]["on"] == hid
    view = w.me()
    assert view["doing"] == "handing the file over" and view["on"] == hid
    rows = _hist(w, ME)
    assert rows[0]["doing"] == "handing the file over" and rows[0]["ended"] is False
    # 0.8.0: the desk's own drop move ends the prior focus as finished (F174/F186), not newer.
    assert rows[1]["doing"] == "editing the file" and rows[1]["ended_by"] == "finished"
