"""The server calls stored procedures only (card 867, beta lane L2). Rows F150-F154.

The card guards used to run in rpc.py (_pass_one, _h_yield, _h_claim) and then
write the new status with a second call: a check-then-write race, since two
desks could pass the same check before either wrote. They now run inside one
SP call under the card's row lock, with the same refusal texts. The raw-SQL
writers in records/mail.py, records/push.py, records/todo.py and admin/door.py
are SP calls too. pass takes optional evidence; a card carries done_when.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ASKER, VOL, OTHER = "a867", "v867", "o867"


class _Book:
    def __init__(self, cn):
        self._cn = cn


class _SpOnlyCursor:
    """A cursor that refuses a raw write (anything but CALL and SELECT) and records CALLs.

    Raw SELECTs outside this card's files (name, tree, label reads) still run; the
    EXECUTE-only test below is the end state that refuses them too."""

    def __init__(self, cur, seen):
        self._cur, self._seen = cur, seen

    def execute(self, sql, *a, **k):
        text = str(sql).strip()
        head = text.split(None, 1)[0].upper() if text else ""
        if head == "CALL":
            self._seen.append(text.split("(", 1)[0].split()[-1].strip("`"))
        elif head != "SELECT":
            raise AssertionError("raw SQL write from the server: " + text[:120])
        return self._cur.execute(sql, *a, **k)

    def callproc(self, name, *a, **k):
        self._seen.append(name)
        return self._cur.callproc(name, *a, **k)

    def __getattr__(self, n):
        return getattr(self._cur, n)


@pytest.fixture()
def sp_only(cn, monkeypatch):
    """Wrap the book's cursors so a raw statement fails the test; yields the CALLed names."""
    seen: list[str] = []
    real = cn.cursor

    def cursor(*a, **k):
        return _SpOnlyCursor(real(*a, **k), seen)

    monkeypatch.setattr(cn, "cursor", cursor)
    yield seen


def _card(cn, need, *, done_when=None):
    seed_names(cn, ("unit", "roster"), (ASKER, "desk"), (VOL, "desk"), (OTHER, "desk"))
    book = _Book(cn)
    body = {"need": need}
    if done_when is not None:
        body["done_when"] = done_when
    rec = rpc._h_open(book, body, "unit", ASKER)
    return book, rec


def _read(cn, need):
    """The card as `mill todo unit NEED` shows it."""
    got = rpc._h_todo(_Book(cn), {"need": need}, "unit", OTHER)
    return got[0] if isinstance(got, list) else got


# F150: the guards run in the SP, under the row lock, same texts.


def test_pass_claim_unclaim_are_one_sp_call_each(cn, sp_only):
    book, _ = _card(cn, "g867-a")
    sp_only.clear()
    rpc._h_claim(book, {"need": "g867-a"}, "unit", VOL)
    assert "cmd_claim" in sp_only
    sp_only.clear()
    rpc._h_yield(book, {"need": "g867-a"}, "unit", VOL)
    assert "cmd_unclaim" in sp_only
    rpc._h_claim(book, {"need": "g867-a"}, "unit", VOL)
    sp_only.clear()
    assert rpc._h_pass(book, {"need": "g867-a"}, "unit", VOL)["status"] == "shipped"
    assert "cmd_pass" in sp_only
    assert "mill_todo_update" not in sp_only


def test_refusal_texts_come_from_the_sp_unchanged(cn):
    book, _ = _card(cn, "g867-b")
    form = "mill pass unit g867-b"
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "g867-b"}, "unit", VOL)
    assert str(e.value) == "claim first: mill claim <project> <need>"
    rpc._h_claim(book, {"need": "g867-b"}, "unit", VOL)
    with pytest.raises(CoordError) as e:
        rpc._h_claim(book, {"need": "g867-b"}, "unit", OTHER)
    assert str(e.value).startswith("claim: unit/g867-b is claimed by " + VOL)
    with pytest.raises(CoordError) as e:
        rpc._h_yield(book, {"need": "g867-b"}, "unit", OTHER)
    assert str(e.value) == "who-may: unclaim is the volunteer"
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "g867-b"}, "unit", OTHER)
    assert str(e.value) == "who-may: pass claimed->shipped is the volunteer"
    rpc._h_pass(book, {"need": "g867-b"}, "unit", VOL)
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "g867-b"}, "unit", VOL)
    assert str(e.value) == f"pass: g867-b is already shipped; the asker accepts it with {form} --done"
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "g867-b", "step": "done"}, "unit", OTHER)
    assert str(e.value) == f"who-may: pass shipped->done is the asker ({ASKER}) or Admin"
    with pytest.raises(CoordError) as e:
        rpc._h_claim(book, {"need": "g867-b"}, "unit", VOL)
    assert str(e.value) == (
        f"claim: unit/g867-b is shipped; the asker accepts it with {form} --done, "
        f"or steps it back with {form} --back"
    )


def test_python_no_longer_holds_the_guards():
    import inspect

    for fn in (rpc._pass_one, rpc._h_yield, rpc._h_claim):
        src = inspect.getsource(fn)
        assert "who-may" not in src, fn.__name__
        assert "rec_todo.update" not in src, fn.__name__


# F151: pass evidence and done_when.


def test_pass_keeps_evidence_on_ship_and_done_and_drops_it_on_back(cn):
    book, _ = _card(cn, "e867-a")
    rpc._h_claim(book, {"need": "e867-a"}, "unit", VOL)
    got = rpc._h_pass(book, {"need": "e867-a", "evidence": "PR #1 sha abc123"}, "unit", VOL)
    assert got["status"] == "shipped" and got["evidence"] == "PR #1 sha abc123"
    assert _read(cn, "e867-a")["evidence"] == "PR #1 sha abc123"
    got = rpc._h_pass(book, {"need": "e867-a", "step": "done"}, "unit", ASKER)
    assert got["status"] == "done" and got["evidence"] == "PR #1 sha abc123"
    got = rpc._h_pass(book, {"need": "e867-a", "step": "back"}, "unit", ASKER)
    got = rpc._h_pass(book, {"need": "e867-a", "step": "done", "evidence": "checked"}, "unit", ASKER)
    assert got["status"] == "done" and got["evidence"] == "checked"
    got = rpc._h_pass(book, {"need": "e867-a", "step": "back", "evidence": "x"}, "unit", ASKER)
    assert got["status"] == "shipped" and got.get("evidence") is None
    assert "evidence" not in _read(cn, "e867-a")


def test_pass_evidence_over_2000_chars_is_refused_and_changes_nothing(cn):
    book, _ = _card(cn, "e867-b")
    rpc._h_claim(book, {"need": "e867-b"}, "unit", VOL)
    with pytest.raises(CoordError, match="evidence"):
        rpc._h_pass(book, {"need": "e867-b", "evidence": "x" * 2001}, "unit", VOL)
    from agent_coord.server.records import todo as rec_todo

    assert rec_todo.find(cn, "unit", "e867-b")["status"] == "claimed"


def test_card_carries_done_when_and_only_the_asker_changes_it(cn):
    book, rec = _card(cn, "w867-a", done_when="CI green and Validator PASS")
    assert rec["done_when"] == "CI green and Validator PASS"
    card = _read(cn, "w867-a")
    assert card["done_when"] == "CI green and Validator PASS"
    with pytest.raises(CoordError, match="who-may: done-when is the asker or Admin"):
        rpc._h_note(book, {"need": "w867-a", "done_when": "other"}, "unit", OTHER)
    rpc._h_note(book, {"need": "w867-a", "done_when": "merged on main"}, "unit", ASKER)
    assert _read(cn, "w867-a")["done_when"] == "merged on main"
    rpc._h_note(book, {"need": "w867-a", "done_when": ""}, "unit", ASKER)
    assert "done_when" not in _read(cn, "w867-a")


def test_a_desk_the_book_does_not_hold_is_nobody(cn):
    """MILL_DESK_ID: an unknown name is id 0, which matches no volunteer, asker or Admin."""
    book, _ = _card(cn, "w867-b")
    rpc._h_claim(book, {"need": "w867-b"}, "unit", VOL)
    with pytest.raises(CoordError, match="who-may: unclaim is the volunteer"):
        rpc._h_yield(book, {"need": "w867-b"}, "unit", "nobody867")


# F152: the raw writers are SP calls.


def test_push_ack_deletes_only_the_calling_desks_rows(cn, sp_only):
    from agent_coord.server.records import push as rec_push

    seed_names(cn, (VOL, "desk"), (OTHER, "desk"))
    assert rec_push.ack(cn, OTHER, [1, 2, 3]) == 0
    assert "cmd_push_sent" in sp_only


def test_read_cursor_is_an_sp_not_a_tree_read_upsert(cn):
    import inspect

    from agent_coord.server.records import mail as rec_mail

    src = inspect.getsource(rec_mail)
    assert "INSERT INTO tree_read" not in src
    assert "UPDATE mail m" not in src
    assert not hasattr(rec_mail, "set_sender_roster")


def test_invite_writers_are_sp_calls():
    import inspect

    from agent_coord.server.admin import door

    src = inspect.getsource(door)
    for raw in ("INSERT INTO mill_invite", "UPDATE mill_invite", "INSERT IGNORE INTO mill_invite_join"):
        assert raw not in src, raw


def test_select_rosters_is_an_sp_read(cn, sp_only):
    from agent_coord.server.records import todo as rec_todo

    _card(cn, "r867-a")
    sp_only.clear()
    got = rec_todo.select_rosters(cn, ["unit"])
    assert any(r.get("id") for _n, r in got)
    assert sp_only


# F153: connect checks the SP version stamp.


def test_connect_frame_carries_the_sp_version_check(cn, sp_only):
    from agent_coord.server.push import connect_sync_frame

    seed_names(cn, (VOL, "desk"))
    frame = connect_sync_frame(cn, VOL)
    assert "mill_hello" in sp_only
    assert "hello" in frame


def test_mill_hello_is_ok_on_the_office_stamp_and_warns_or_refuses_otherwise(cn):
    from agent_coord.install import migrate
    from agent_coord.server.push import hello_line, sp_stamp
    from agent_coord.server.records.db import call

    migrate._stamp_sql(cn, migrate.sql_digest())
    assert sp_stamp().startswith("sp-") and len(sp_stamp()) == 15
    assert hello_line(cn) == "ok"
    got = call(cn, "mill_hello", ["sp-000000000000", "warn"])[-1]
    assert got["status"] == "warn" and got["office"] == sp_stamp() and "sp-000000000000" in got["message"]
    with pytest.raises(Exception, match="sp stamp: office"):
        call(cn, "mill_hello", ["sp-000000000000", "refuse"])


# F154: the app DB user can run the SPs and nothing else.


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="F154 is the 0.8.0 end state: in 0.7.18 the app user still runs raw SQL on today's tables",
)
def test_app_user_cannot_run_raw_sql(cn):
    """The app DB user runs the SPs and nothing else. 0.8.0 creates it with
    migrate.grant_app_user; until then the app user is the configured one
    (conn_kwargs), which may run raw SQL, so the assert below is the failure."""
    import mysql.connector

    from agent_coord.install import migrate
    from agent_coord.server.records.db import conn_kwargs

    cur = cn.cursor()
    cur.execute("SELECT DATABASE()")
    db = cur.fetchone()[0]
    cur.close()
    kw = conn_kwargs()
    kw.update(database=db)
    grant = getattr(migrate, "grant_app_user", None)
    if grant is not None:
        user, pw = "mill_app_t867", "t867-only-for-this-test"
        grant(cn, db, user, pw, host="%")
        kw.update(user=user, password=pw)
    app = mysql.connector.connect(**kw)
    ran = []
    try:
        c = app.cursor()
        for sql in ("SELECT 1 FROM todo LIMIT 1", "DELETE FROM push_queue WHERE id = 0", "CREATE TEMPORARY TABLE t867 (i INT)"):
            try:
                c.execute(sql)
                if c.with_rows:
                    c.fetchall()
                ran.append(sql)
            except mysql.connector.Error as e:
                assert e.errno in (1142, 1044, 1146), (sql, e.errno)
        c.close()
        app.rollback()
    finally:
        app.close()
    assert not ran, "raw SQL ran as the app user: %s" % ran


# 0.8.0: done_when stays on todo; evidence is doing.evidence (no todo.evidence shim).


def test_ensure_adds_done_when_once(cn):
    from agent_coord.install import migrate

    cur = cn.cursor()
    try:
        cur.execute("ALTER TABLE todo DROP COLUMN done_when")
    finally:
        cur.close()
    assert migrate._ensure_todo_done_when(cn) == ["todo.done_when"]
    assert migrate._ensure_todo_done_when(cn) == []
