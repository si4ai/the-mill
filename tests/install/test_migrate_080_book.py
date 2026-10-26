"""0.8.0 schema migration (lane A): a main book (0.7.18 shape) to the 0.8.0 schema, on throwaway MySQL.

Each test builds a main book, seeds normal data plus the problem cases the migration fixes, runs
agent_coord.install.migrate, and checks the result against a fresh install of tables.sql through
information_schema. No server, no SPIN. A MySQL that answers but fails to apply the SQL fails the test.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.sql

PROBLEM_ROSTER_WATCHERS = 5


def _mysql_up() -> None:
    """Skip only when no MySQL answers. Everything after the connect must pass or fail."""
    try:
        from tests.beta_book import admin_conn

        cn, _ = admin_conn()
        cn.close()
    except Exception as exc:  # no MySQL here
        pytest.skip(f"no MySQL for the 0.8.0 migration tests: {exc}")


@pytest.fixture()
def main_book():
    _mysql_up()
    from tests.beta_book import drop_db, make_main_book

    cn, db = make_main_book("mill_m080")
    yield cn
    drop_db(cn, db)


@pytest.fixture(scope="module")
def fresh_snapshot():
    _mysql_up()
    from tests.beta_book import drop_db, make_fresh_book, schema_snapshot

    cn, db = make_fresh_book("mill_m080_fresh")
    try:
        snap = schema_snapshot(cn)
    finally:
        drop_db(cn, db)
    return snap


def _q(cn, sql, args=()):
    from tests.beta_book import _q as q

    return q(cn, sql, args)


def _one(cn, sql, args=()):
    rows = _q(cn, sql, args)
    return rows[0][0] if rows else None


# ---------------------------------------------------------------------------------------------------------------
# Seed: a main book with normal data and every problem case.


def seed(cn, scale: int = 1, *, collapse: bool = False, bad_kind: bool = False) -> dict:
    rng = random.Random(80 + scale)
    cur = cn.cursor()
    t0 = datetime(2026, 9, 1, 8, 0, 0)

    def ts(i: int) -> datetime:
        return t0 + timedelta(seconds=37 * i)

    nd = 13 * scale + 7
    names = [("desk", f"desk-{i}") for i in range(nd)]
    names += [("roster", f"team-{c}") for c in "abcdefgh"]
    names += [("label", f"lab-{i}") for i in range(20)]
    names += [("tree", f"plan-{i}") for i in range(10)]
    n_hold = 20 * scale
    names += [("res", f"res-{i}") for i in range(n_hold)]
    cur.executemany("INSERT INTO name (type, name) VALUES (%s, %s)", names)
    cur.execute("SELECT id, type, name FROM name")
    ids = {(t, n): int(i) for i, t, n in cur.fetchall()}
    desks = [ids[("desk", f"desk-{i}")] for i in range(nd)]
    rosters = [ids[("roster", f"team-{c}")] for c in "abcdefgh"]
    labels = [ids[("label", f"lab-{i}")] for i in range(20)]
    plans = [ids[("tree", f"plan-{i}")] for i in range(10)]
    res = [ids[("res", f"res-{i}")] for i in range(n_hold)]
    unseated = desks[-3:]  # problem: desks that wrote rows but have no seat row
    seated = desks[:-3]

    cur.executemany(
        "INSERT INTO seat (desk_id, token_hash, delivery_mode, wake_on, time_connect, created, updated)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [(d, hashlib.sha256(str(d).encode()).hexdigest(), rng.choice(["websocket", "webhook", "polling"]),
          rng.choice(["all", "addressed"]), ts(d), ts(d), ts(d)) for d in seated],
    )
    member = [(1, d) for d in desks] + [(2, desks[0])]
    for i, d in enumerate(desks):
        member.append((rosters[i % 8], d))
        if i % 3 == 0:
            member.append((rosters[(i + 3) % 8], d))
    member = sorted(set(member))
    cur.executemany("INSERT INTO member (name_id, desk_id) VALUES (%s, %s)", member)
    for r in rosters + [1, 2]:
        cur.execute("UPDATE name SET n = (SELECT COUNT(*) FROM member WHERE name_id = %s) WHERE id = %s", (r, r))

    cur.execute("INSERT INTO human (bearer_hash) VALUES (%s), (%s)", ("a" * 64, "b" * 64))
    cur.execute("SELECT id FROM human ORDER BY id")
    humans = [int(r[0]) for r in cur.fetchall()]
    cur.execute("INSERT INTO human_desk (human_id, desk_id) VALUES (%s, %s), (%s, %s)",
                (humans[0], desks[0], humans[1], desks[1]))
    cur.execute("INSERT INTO human_member (human_id, name_id) VALUES (%s, %s)", (humans[0], rosters[0]))

    activity = []
    # mail
    n_mail = 320 * scale
    mail, mail_to = [], []
    for i in range(1, n_mail + 1):
        author = unseated[0] if i % 97 == 0 else rng.choice(desks)
        roster = rng.choice([1] + rosters)
        mail.append((i, ts(i), author, roster, f"letter {i}"))
        to = rng.sample([d for d in desks if d != author], 2)
        if i % 101 == 0 and unseated[1] not in to and author != unseated[1]:
            to[0] = unseated[1]
        for k, d in enumerate(to):
            mail_to.append((i, d, ts(i + 3) if rng.random() < 0.6 else None, k == 0, ts(i)))
        activity.append(("mail", i, ts(i), ts(i), author, roster, 1, 1, 40))
    cur.executemany("INSERT INTO mail (id, created, desk_id, roster_id, body) VALUES (%s,%s,%s,%s,%s)", mail)
    cur.executemany("INSERT INTO mail_to (id, desk_id, opened, asked, created) VALUES (%s,%s,%s,%s,%s)", mail_to)

    # todo
    n_todo = 90 * scale
    todo, watcher = [], []
    statuses = ["open", "parked", "claimed", "shipped", "done"]
    for i in range(1, n_todo + 1):
        st = statuses[i % 5]
        creator = unseated[2] if i % 89 == 0 else rng.choice(desks)
        upd = rng.choice(desks)
        asg = rng.choice(desks) if st in ("claimed", "shipped", "done") else None
        ev = f"evidence {i}" if st in ("shipped", "done") and i % 2 == 0 else None
        dw = f"done when {i}" if i % 3 == 0 else None
        roster = rng.choice([1] + rosters)
        todo.append((i, ts(i), ts(i + 50), upd, roster, creator, st, asg, ts(i + 10) if st == "claimed" else None,
                     f"card {i}", dw, ev))
        activity.append(("todo", i, ts(i), ts(i + 50), creator, roster, 1, 1, 30))
        watcher.append(("todo", i, creator, None, ts(i)))
        if asg and asg != creator:
            watcher.append(("todo", i, asg, f"hint {i}", ts(i)))
    cur.executemany(
        "INSERT INTO todo (id, created, updated, updated_id, roster_id, creator_id, status, assigned_id, claimed_at,"
        " body, done_when, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", todo)
    # problem: roster watchers (#265 rows), one with a hint and one whose member already watches.
    roster_watch = []
    for i in range(1, PROBLEM_ROSTER_WATCHERS + 1):
        roster_watch.append(("todo", i, rosters[i % 8], f"roster hint {i}" if i == 2 else None, ts(i)))
    mem_a = [d for r, d in member if r == rosters[1]]
    watcher.append(("todo", 1, mem_a[0], "already", ts(1)))
    roster_watch.append(("hold", 1, 1, None, ts(1)))  # Office roster watches a hold
    watcher = list({(w[0], w[1], w[2]): w for w in watcher + roster_watch}.values())
    cur.executemany("INSERT INTO watcher (type, id, desk_id, hint, updated) VALUES (%s,%s,%s,%s,%s)", watcher)

    # doing (append-only; ties on created broken by id; some cleared rows)
    n_doing = 500 * scale
    doing = []
    for i in range(1, n_doing + 1):
        d = rng.choice(desks)
        created = ts(i // 2)  # pairs share a timestamp
        cleared = i % 17 == 0
        on = None if cleared else rng.choice([None, ("todo", rng.randint(1, n_todo)), ("mail", rng.randint(1, n_mail))])
        doing.append((i, created, d, rng.choice([1] + rosters), "" if cleared else f"doing {i}",
                      on[0] if on else None, on[1] if on else None))
        activity.append(("doing", i, created, created, d, 1, 1, 1, None))
    cur.executemany("INSERT INTO doing (id, created, desk_id, roster_id, text, on_type, on_id)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s)", doing)

    # hold
    hold = []
    for i in range(1, n_hold + 1):
        d = rng.choice(desks) if i % 4 else None
        hold.append((i, ts(i), ts(i), d, res[i - 1]))
        activity.append(("hold", i, ts(i), ts(i), d if d else desks[0], 1, 1, 1, None))
    cur.executemany("INSERT INTO hold (id, created, updated, desk_id, resource_id) VALUES (%s,%s,%s,%s,%s)", hold)

    # score: the 3 system rows (desk 2, Admin) came with tables.sql. Problem: roster-owned rows (desk = roster).
    score = []
    for r in rosters:
        for k in range(3):
            score.append((ts(r + k), r, r, f"kpi-{k}", str(k), "", "", "up", ""))
    for d in seated[: 10 * scale]:
        score.append((ts(d), d, 1, "system", "1", "", "", "up", ""))
    if collapse:  # problem the migration refuses: two rows of one roster and kpi both become the office's
        score.append((ts(1), 2, rosters[0], "kpi-0", "9", "", "", "up", ""))
    cur.executemany("INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note, better, unit)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", score)
    cur.execute("INSERT INTO activity (type, id, created, updated, desk_id, roster_id)"
                " SELECT 'score', s.id, s.created, s.updated, s.desk_id, s.roster_id FROM score s"
                " WHERE NOT EXISTS (SELECT 1 FROM activity a WHERE a.type = 'score' AND a.id = s.id)")
    cur.execute("SELECT id FROM score WHERE roster_id <> 1 ORDER BY id")
    defs = [int(r[0]) for r in cur.fetchall()]
    cur.executemany("INSERT INTO score_point (score_id, created, desk_id, value) VALUES (%s,%s,%s,%s)",
                    [(rng.choice(defs), ts(i), rng.choice(desks), float(i)) for i in range(50 * scale)])
    cur.execute("SELECT id FROM score WHERE desk_id = 2 ORDER BY id")
    for (sid,) in cur.fetchall():
        cur.execute("INSERT INTO score_evidence (score_id, timestamp, value, taken) VALUES (%s, %s, %s, %s)",
                    (sid, datetime(1970, 1, 1, 3), json.dumps({"verbs": 3}), datetime(2026, 9, 2).date()))

    cur.executemany(
        "INSERT INTO activity (type, id, created, updated, desk_id, roster_id, weight, n, bytes)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", activity)

    # label, tree, tree_read
    acts = [(t, i) for t, i, *_ in activity]
    lab = set()
    while len(lab) < min(200 * scale, len(acts)):
        t, i = rng.choice(acts)
        lab.add((t, i, rng.choice(labels)))
    if bad_kind:  # problem the migration refuses: a label row whose name is a roster
        lab.add(("todo", 1, rosters[0]))
    cur.executemany("INSERT INTO label (type, id, name_id, ord, created) VALUES (%s,%s,%s,%s,%s)",
                    [(t, i, n, rng.randint(0, 65535), ts(i)) for t, i, n in sorted(lab)])
    tree = []
    per = max(1, (50 * scale) // len(plans))
    for p_i, p in enumerate(plans):
        for k in range(per):
            tid = (p_i * per + k) % n_todo + 1
            tree.append((p, "todo", tid, 2 * k + 1, 2 * k + 2))
    tree = list({(r[0], r[1], r[2]): r for r in tree}.values())
    cur.executemany("INSERT INTO tree (name_id, type, id, lft, rgt) VALUES (%s,%s,%s,%s,%s)", tree)
    reads = {(rng.choice(desks), rng.choice(plans)): rng.randint(1, n_mail) for _ in range(20)}
    cur.executemany("INSERT INTO tree_read (desk_id, tree_id, last_id) VALUES (%s,%s,%s)",
                    sorted((d, p, n) for (d, p), n in reads.items()))
    cur.executemany("INSERT INTO push_queue (desk_id, kind, payload, outcome, created) VALUES (%s,%s,%s,%s,%s)",
                    [(rng.choice(desks), "mail", json.dumps({"id": i}), "sent", ts(i)) for i in range(100 * scale)])
    cur.execute("INSERT INTO mill_invite (key_id, token_hash) VALUES ('k1', %s)", ("c" * 64,))
    cur.execute("INSERT INTO mill_invite_join (key_id, party, party_id) VALUES ('k1', 'desk', 'desk-0')")
    cn.commit()
    cur.close()
    return {"desks": desks, "rosters": rosters, "unseated": unseated, "member": member,
            "roster_watch": roster_watch, "n_mail": n_mail, "n_todo": n_todo, "n_doing": n_doing}


MAIN_TABLES = ("name", "seat", "member", "activity", "label", "tree", "watcher", "mail", "mail_to", "tree_read", "todo",
               "doing", "hold", "score", "score_point", "score_evidence", "human", "human_desk", "human_member",
               "mill_invite", "mill_invite_join", "push_queue")
NEW_TABLES = ("todo_event", "doing_now", "vote", "vote_option", "vote_cast", "glance_cache", "sp_deploy")
# Columns the migration adds (kind pins, desk_key) or drops (todo.evidence); left out of the row compare.
ADDED = {"name_kind", "roster_kind", "tree_kind", "resource_kind", "desk_key"}


def _pk(cn, table):
    rows = _q(cn, "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = DATABASE()"
                  " AND TABLE_NAME = %s AND CONSTRAINT_NAME = 'PRIMARY' ORDER BY ORDINAL_POSITION", (table,))
    return [r[0] for r in rows]


def _cols(cn, table):
    return [r[0] for r in _q(cn, "SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()"
                                 " AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION", (table,))]


def dump(cn, tables=MAIN_TABLES) -> dict[str, list[tuple]]:
    out = {}
    for t in tables:
        cols = [c for c in _cols(cn, t) if c not in ADDED]
        sel = ", ".join(f"`{c}`" for c in cols)
        out[t] = (cols, _q(cn, f"SELECT {sel} FROM `{t}` ORDER BY {', '.join(f'`{c}`' for c in _pk(cn, t))}"))
    return out


def _rows_as_dicts(d, table):
    cols, rows = d[table]
    return [dict(zip(cols, r)) for r in rows]


def _migrate(cn):
    from agent_coord.install import migrate

    return migrate.ensure(cn)


# ---------------------------------------------------------------------------------------------------------------


def test_fresh_tables_sql_is_the_080_schema(fresh_snapshot):
    """tables.sql is the 29-table 0.8.0 schema, the same as docs/requirements/beta/beta_ddl.sql."""
    from tests.beta_book import drop_db, make_book, schema_snapshot

    tables = {r[0] for r in fresh_snapshot["tables"]}
    assert len(tables) == 29, sorted(tables)
    assert set(NEW_TABLES) <= tables
    cn, db = make_book("mill_m080_doc", sp=False)
    try:
        doc = schema_snapshot(cn)
    finally:
        drop_db(cn, db)
    for key in fresh_snapshot:
        assert fresh_snapshot[key] == doc[key], key
    kind_fks = [r for r in fresh_snapshot["fk_cols"] if r[3].endswith("_kind")]
    assert len(kind_fks) == 12, kind_fks


def test_migrated_main_book_equals_fresh_install(main_book, fresh_snapshot):
    from tests.beta_book import schema_snapshot

    seed(main_book)
    res = _migrate(main_book)
    assert any(str(a).startswith("migrate_080") for a in res["applied"]), res["applied"]
    snap = schema_snapshot(main_book)
    for key in fresh_snapshot:
        assert snap[key] == fresh_snapshot[key], key


def test_ids_rows_and_transforms(main_book):
    s = seed(main_book)
    before = dump(main_book)
    _migrate(main_book)
    after = dump(main_book)
    cn = main_book

    untouched = set(MAIN_TABLES) - {"seat", "watcher", "activity", "score", "todo"}
    for t in sorted(untouched):
        assert after[t] == before[t], t

    # seat: every desk has a seat; old rows unchanged; the unseated desks got a token-NULL row.
    old_seats = {r["desk_id"]: r for r in _rows_as_dicts(before, "seat")}
    new_seats = {r["desk_id"]: r for r in _rows_as_dicts(after, "seat")}
    for d, row in old_seats.items():
        assert new_seats[d] == row
    assert set(new_seats) - set(old_seats) == set(s["unseated"])
    for d in s["unseated"]:
        assert new_seats[d]["token_hash"] is None
    assert _one(cn, "SELECT COUNT(*) FROM name n WHERE n.type = 'desk'"
                    " AND NOT EXISTS (SELECT 1 FROM seat s WHERE s.desk_id = n.id)") == 0

    # watcher: roster rows replaced by one row per member desk; desk rows unchanged.
    rosters = {r for r, _ in s["member"]}
    old_w = _rows_as_dicts(before, "watcher")
    new_w = {(r["type"], r["id"], r["desk_id"]): r for r in _rows_as_dicts(after, "watcher")}
    assert not [k for k in new_w if k[2] in rosters]
    desk_rows = [r for r in old_w if r["desk_id"] not in rosters]
    for r in desk_rows:
        assert new_w[(r["type"], r["id"], r["desk_id"])] == r
    want = {(r["type"], r["id"], r["desk_id"]) for r in desk_rows}
    for t, i, rid, hint, _ in s["roster_watch"]:
        for mr, d in s["member"]:
            if mr == rid:
                want.add((t, i, d))
                if not any(x["type"] == t and x["id"] == i and x["desk_id"] == d for x in desk_rows):
                    assert new_w[(t, i, d)]["hint"] == hint
    assert set(new_w) == want

    # activity and score: a desk_id that is not a desk becomes NULL (the office); every other field kept.
    desk_ids = {r["id"] for r in _rows_as_dicts(after, "name") if r["type"] == "desk"}
    for t in ("activity", "score"):
        b, a = _rows_as_dicts(before, t), _rows_as_dicts(after, t)
        assert len(a) == len(b), t
        for rb, ra in zip(b, a):
            want_desk = rb["desk_id"] if rb["desk_id"] in desk_ids else None
            assert ra["desk_id"] == want_desk, (t, rb)
            assert {k: v for k, v in ra.items() if k != "desk_id"} == {k: v for k, v in rb.items() if k != "desk_id"}
    assert _one(cn, "SELECT COUNT(*) FROM score WHERE desk_key <> IFNULL(desk_id, 0)") == 0
    assert _one(cn, "SELECT COUNT(*) FROM score WHERE desk_id IS NULL") == 3 + 8 * 3

    # todo: evidence moved to todo_event (one row each), the column is gone, every other field kept.
    b = _rows_as_dicts(before, "todo")
    a = {r["id"]: r for r in _rows_as_dicts(after, "todo")}
    assert "evidence" not in after["todo"][0]
    for rb in b:
        assert {k: v for k, v in rb.items() if k != "evidence"} == a[rb["id"]]
    ev = {r[0]: r for r in _q(cn, "SELECT todo_id, desk_id, from_status, to_status, assigned_id, evidence, created"
                                  " FROM todo_event")}
    with_ev = [r for r in b if r["evidence"] is not None]
    assert len(ev) == len(with_ev) == _one(cn, "SELECT COUNT(*) FROM todo_event")
    for rb in with_ev:
        assert ev[rb["id"]] == (rb["id"], rb["updated_id"], None, rb["status"], rb["assigned_id"], rb["evidence"],
                                rb["updated"])

    # doing_now: the newest doing row per desk, by (created, id), as mill_doing_now reads it.
    newest = {}
    for r in _rows_as_dicts(before, "doing"):
        k = (r["created"], r["id"])
        if r["desk_id"] not in newest or k > newest[r["desk_id"]][0]:
            newest[r["desk_id"]] = (k, r["id"])
    now = dict(_q(cn, "SELECT desk_id, doing_id FROM doing_now"))
    assert now == {d: v[1] for d, v in newest.items()}

    for t in ("vote", "vote_option", "vote_cast", "glance_cache"):
        assert _one(cn, f"SELECT COUNT(*) FROM {t}") == 0, t
    assert _one(cn, "SELECT COUNT(*) FROM sp_deploy") == 1
    # no migration routine is left behind
    assert _one(cn, "SELECT COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE()"
                    " AND ROUTINE_NAME LIKE 'mill\\_migrate\\_080%'") == 0


def _checksums(cn):
    from tests.beta_book import schema_snapshot

    tables = [r[0] for r in schema_snapshot(cn)["tables"]]
    cur = cn.cursor()
    try:
        cur.execute("CHECKSUM TABLE " + ", ".join(f"`{t}`" for t in tables))
        sums = {r[0].split(".")[-1]: r[1] for r in cur.fetchall()}
    finally:
        cur.close()
    return sums


def _routines(cn):
    return _q(cn, "SELECT ROUTINE_TYPE, ROUTINE_NAME, SHA2(IFNULL(ROUTINE_DEFINITION, ''), 256)"
                  " FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = DATABASE() ORDER BY 1, 2")


def test_second_run_is_a_no_op(main_book):
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    seed(main_book)
    _migrate(main_book)
    snap, sums, routines = schema_snapshot(main_book), _checksums(main_book), _routines(main_book)
    assert migrate.apply_080(main_book) == []
    _migrate(main_book)
    assert schema_snapshot(main_book) == snap
    assert _checksums(main_book) == sums
    assert _routines(main_book) == routines


@pytest.mark.parametrize("kill_after", [
    "seat", "watcher", "desk_null", "score_key", "keys_kinds", "tables", "todo_event", "doing_now", "fks",
])
def test_resumes_after_a_kill_at_each_step(main_book, fresh_snapshot, kill_after):
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    assert kill_after in migrate.STEPS_080
    seed(main_book)
    before = dump(main_book)
    migrate.apply_080(main_book, stop_after=kill_after)
    done = migrate.apply_080(main_book)
    assert done, "the resumed run had work left"
    snap = schema_snapshot(main_book)
    for key in fresh_snapshot:
        assert snap[key] == fresh_snapshot[key], (kill_after, key)
    after = dump(main_book)
    for t in MAIN_TABLES:
        assert len(after[t][1]) == len(before[t][1]) or t in ("seat", "watcher"), t
    assert _one(main_book, "SELECT COUNT(*) FROM todo_event") == sum(
        1 for r in _rows_as_dicts(before, "todo") if r["evidence"] is not None)


def test_preflight_reports_and_changes_nothing(main_book):
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    s = seed(main_book)
    snap, sums, routines = schema_snapshot(main_book), _checksums(main_book), _routines(main_book)
    rep = migrate.preflight_080(main_book)
    assert rep["pending"] is True
    assert rep["refuse"] == {}
    fix = rep["fix"]
    assert fix["seat_backfill"] == len(s["unseated"])
    assert fix["watcher_roster"] == len(s["roster_watch"])
    assert fix["activity_desk_null"] > 0 and fix["score_desk_null"] == 3 + 8 * 3
    assert fix["todo_evidence"] > 0 and fix["doing_now"] > 0
    assert schema_snapshot(main_book) == snap
    assert _checksums(main_book) == sums
    assert _routines(main_book) == routines


@pytest.mark.parametrize("case,check", [("collapse", "score_collapse"), ("bad_kind", "kind_label")])
def test_preflight_refuses_bad_data_and_changes_nothing(main_book, case, check):
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    seed(main_book, **{case: True})
    snap, sums, routines = schema_snapshot(main_book), _checksums(main_book), _routines(main_book)
    rep = migrate.preflight_080(main_book)
    assert rep["refuse"].get(check) == 1, rep
    with pytest.raises(migrate.Migrate080Refused) as e:
        migrate.apply_080(main_book)
    msg = str(e.value)
    assert check in msg and "nothing was changed" in msg, msg
    assert schema_snapshot(main_book) == snap
    assert _checksums(main_book) == sums
    assert _routines(main_book) == routines


def test_perf_lines_on_and_off(main_book, monkeypatch, tmp_path):
    from agent_coord.config import mill_home
    from agent_coord.install import migrate

    seed(main_book)
    monkeypatch.setenv("MILL_PERF", "0")
    log = mill_home() / "mill-perf.log"
    migrate.apply_080(main_book, stop_after="seat")
    assert not log.exists() or "migrate.080" not in log.read_text()
    monkeypatch.delenv("MILL_PERF")
    migrate.apply_080(main_book)
    lines = [ln for ln in log.read_text().splitlines() if "op=migrate.080." in ln]
    steps = {ln.split("op=migrate.080.")[1].split()[0] for ln in lines}
    assert {"watcher", "fks", "triggers"} <= steps, lines
    for ln in lines:
        for field in ("ms=", "rows=", "lock_waits=", "lock_ms=", "ok=1"):
            assert field in ln, ln


def test_migration_timing(main_book, capsys):
    """Time the whole migration on a seeded book.

    MILL_080_SCALE=10 is about the cloud office's volumes (mail 3.2k, cards 900, holds 200); 100 is 10x.
    """
    from agent_coord.install import migrate

    scale = int(os.environ.get("MILL_080_SCALE") or 1)
    t0 = time.perf_counter()
    seed(main_book, scale)
    seeded = time.perf_counter() - t0
    counts = {t: _one(main_book, f"SELECT COUNT(*) FROM `{t}`") for t in ("mail", "mail_to", "todo", "doing", "hold",
                                                                          "activity", "label", "watcher", "push_queue")}
    t1 = time.perf_counter()
    done = migrate.apply_080(main_book, timings=(timings := {}))
    total = time.perf_counter() - t1
    assert done
    with capsys.disabled():
        print(f"\nmigrate_080 scale={scale} seed_s={seeded:.1f} total_s={total:.2f} counts={counts}")
        print("steps_ms=" + json.dumps({k: round(v, 1) for k, v in timings.items()}))


def test_wipe_then_apply_on_a_migrated_book_is_a_fresh_install(main_book, fresh_snapshot):
    """MILL_RECORDS_WIPE: wipe.sql drops the 0.8.0 tables and triggers too, so tables.sql applies clean."""
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    seed(main_book)
    _migrate(main_book)
    migrate.apply_records(main_book, wipe=True)
    snap = schema_snapshot(main_book)
    for key in fresh_snapshot:
        assert snap[key] == fresh_snapshot[key], key
    assert _one(main_book, "SELECT COUNT(*) FROM todo_event") == 0


@pytest.mark.parametrize("cut", ["fks_dropped_not_added", "todo_event_copied_not_dropped"])
def test_resumes_after_a_kill_inside_a_step(main_book, fresh_snapshot, cut):
    """A kill between the two ALTERs of the FK step, or between the todo_event copy and the column drop."""
    from agent_coord.install import migrate
    from tests.beta_book import schema_snapshot

    seed(main_book)
    n_ev = _one(main_book, "SELECT COUNT(*) FROM todo WHERE evidence IS NOT NULL")
    cur = main_book.cursor()
    if cut == "fks_dropped_not_added":
        migrate.apply_080(main_book, stop_after="doing_now")
        cur.execute("ALTER TABLE mail DROP FOREIGN KEY fk_mail_desk, DROP FOREIGN KEY fk_mail_roster")
    else:
        migrate.apply_080(main_book, stop_after="tables")
        cur.execute("INSERT INTO todo_event (todo_id, created, desk_id, to_status, assigned_id, evidence)"
                    " SELECT id, updated, updated_id, status, assigned_id, evidence FROM todo WHERE evidence IS NOT NULL")
    main_book.commit()
    cur.close()
    assert migrate.apply_080(main_book)
    snap = schema_snapshot(main_book)
    for key in fresh_snapshot:
        assert snap[key] == fresh_snapshot[key], (cut, key)
    assert _one(main_book, "SELECT COUNT(*) FROM todo_event") == n_ev


def _declared_keys_080() -> set[tuple[str, str]]:
    """(table, index) for every key tables.sql declares. PRIMARY is always declared."""
    import re
    from pathlib import Path

    ddl = (Path(__file__).resolve().parents[2] / "agent_coord" / "server" / "sql" / "tables.sql").read_text(encoding="utf-8")
    out = set()
    for t, body in re.findall(r"^CREATE TABLE IF NOT EXISTS (\w+) \((.*?)^\)", ddl, re.M | re.S):
        out |= {(t, name) for name in re.findall(r"^\s*(?:UNIQUE )?KEY (\w+) \(", body, re.M)}
    return out


@pytest.mark.parametrize("kill_after", [None, "keys_kinds", "doing_now"])
def test_migrated_book_has_no_implicit_indexes(main_book, kill_after):
    """The owner rule (F169): PRIMARY and UNIQUE keys are indexed by definition; every other index is declared in
    tables.sql and named idx_*. A migrated main book (whole, or resumed after a kill) has no index MySQL made for an
    FK, and no index main declared that 0.8.0 folded or dropped (F170)."""
    from agent_coord.install import migrate

    seed(main_book)
    if kill_after:
        migrate.apply_080(main_book, stop_after=kill_after)
    _migrate(main_book)
    declared = _declared_keys_080()
    got = {(t, i) for t, i in _q(main_book, "SELECT DISTINCT TABLE_NAME, INDEX_NAME FROM information_schema.STATISTICS"
                                             " WHERE TABLE_SCHEMA = DATABASE()")}
    fks = {(t, c) for t, c in _q(main_book, "SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS"
                                             " WHERE CONSTRAINT_SCHEMA = DATABASE()")}
    implicit = sorted(k for k in got if k[1] != "PRIMARY" and k not in declared)
    assert not implicit, f"indexes not declared in tables.sql: {implicit}"
    assert not sorted(got & fks), "an index named after an FK constraint"
    assert sorted(declared - got) == [], "a declared key the migrated book does not have"
