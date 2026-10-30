"""Perf punch (0.6.13): mail list dests JSON_ARRAYAGG, floor parts JOIN mill_floor_desk,
floor reads resolve roster ids once then IN (...)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import apply, connect, mail, score, todo
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import call, conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_perf_punch_test")
SQL = Path(__file__).resolve().parents[3] / "agent_coord" / "server" / "sql"


def _cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


@pytest.fixture(scope="module")
def seeded(cn):
    seed_names(
        cn,
        ("pp_a", "roster"),
        ("pp_b", "roster"),
        ("pp_role", "roster"),
        ("pp_s", "desk"),
        ("pp_r1", "desk"),
        ("pp_r2", "desk"),
    )
    m1 = int(mail.insert(cn, "pp_a", "pp_s", "pp_r1", "one")[0]["id"])
    mail.to_put(cn, m1, "pp_a", "pp_r2", dst_kind="desk")
    m2 = int(mail.insert(cn, "pp_b", "pp_s", "pp_r2", "two")[0]["id"])
    m3 = int(mail.insert(cn, "pp_role", "pp_s", "pp_r1", "three")[0]["id"])
    todo.insert(cn, "pp_a", "pp_s", "open", "ta")
    todo.insert(cn, "pp_b", "pp_s", "open", "tb")
    score.upsert(cn, "pp_a", "pp_s", "k1", "1", "", "")
    score.upsert(cn, "pp_b", "pp_s", "k2", "2", "", "")
    return m1, m2, m3


def test_mail_list_one_row_per_letter_with_dests(cn, seeded) -> None:
    m1, _m2, _m3 = seeded
    rows = mail.list_project(cn, "pp_a")
    ids = [int(r["id"]) for r in rows]
    assert ids.count(m1) == 1
    row = next(r for r in rows if int(r["id"]) == m1)
    dests = mail.dest_rows_json(row["dests"])
    assert [d["desk"] for d in dests] == ["pp_r1", "pp_r2"]
    grouped = mail.group_list_rows(rows)
    assert [d["desk"] for d in dict((int(l["id"]), d) for l, d in grouped)[m1]] == ["pp_r1", "pp_r2"]


def test_list_rosters_matches_per_name_reads(cn, seeded) -> None:
    names = ["pp_b", "pp_a", "pp_role", "pp_nope"]
    batch = mail.list_rosters(cn, names)
    per = [(n, r) for n in names[:3] for r in mail.list_project(cn, n)]
    assert [(n, int(r["id"])) for n, r in batch] == [(n, int(r["id"])) for n, r in per]
    assert mail.list_rosters(cn, ["pp_nope"]) == []
    assert mail.list_rosters(cn, []) == []
    assert scalar(cn, "SELECT id FROM name WHERE name='pp_nope'") is None


def test_todo_score_select_rosters_match(cn, seeded) -> None:
    names = ["pp_b", "pp_a"]
    t_batch = [(n, int(r["id"])) for n, r in todo.select_rosters(cn, names)]
    t_per = [(n, int(r["id"])) for n in names for r in todo.select(cn, n, "")]
    assert t_batch == t_per and t_batch
    s_batch = [(n, int(r["id"])) for n, r in score.select_rosters(cn, names)]
    s_per = [(n, int(r["id"])) for n in names for r in score.select(cn, n)]
    assert s_batch == s_per and s_batch
    assert todo.select_rosters(cn, ["pp_nope"]) == []
    assert score.select_rosters(cn, []) == []


def test_roster_ids_project_before_role(cn) -> None:
    seed_names(cn, ("pp_both", "roster"), ("pp_both", "roster"))
    pid = int(scalar(cn, "SELECT id FROM name WHERE type = 'roster' AND name='pp_both'"))
    assert rec_name.roster_ids(cn, ["pp_both", "pp_both "]) == [("pp_both", pid)]


def test_floor_part_mail_one_row_per_letter(cn, seeded) -> None:
    m1, _m2, _m3 = seeded
    seed_names(cn, ("pp_lan_p", "roster"))
    rec_join.upsert(cn, "pp_lan_p", "pp_r2", "", "1" * 64, "")
    cur = cn.cursor()
    cur.execute("UPDATE seat SET lan_ip='192.0.2.77' WHERE desk_id=(SELECT id FROM name WHERE type='desk' AND name='pp_r2')")
    cn.commit()
    cur.close()
    rows = call(cn, "mill_floor_part", ["lan", "192.0.2.77", "mail"])
    ids = [int(r["id"]) for r in rows]
    assert len(ids) == len(set(ids))
    assert m1 in ids
    row = next(r for r in rows if int(r["id"]) == m1)
    assert [d["desk"] for d in mail.dest_rows_json(row["dests"])] == ["pp_r1", "pp_r2"]
    # every other part still answers on the same scope
    for part in ("agents", "todos", "holds", "scores", "events"):
        call(cn, "mill_floor_part", ["lan", "192.0.2.77", part])


def test_floor_part_sql_joins_scope_table() -> None:
    text = (SQL / "sp_floor_scope.sql").read_text(encoding="utf-8")
    body = text.split("CREATE PROCEDURE mill_floor_part", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "IN (SELECT desk_id FROM mill_floor_desk)" not in body
    assert "EXISTS (" not in body
    assert "JSON_ARRAYAGG" in body
    mail_sql = (SQL / "sp_mail.sql").read_text(encoding="utf-8")
    lst = mail_sql.split("CREATE PROCEDURE mill_mail_list", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "JSON_ARRAYAGG" in lst and "GROUP BY" in lst
    sel = mail_sql.split("CREATE PROCEDURE mill_mail_select", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "IFNULL" not in sel
    assert "JOIN activity" not in sel
    get = mail_sql.split("CREATE PROCEDURE mill_mail_get", 1)[1].split("CREATE PROCEDURE", 1)[0]
    assert "IFNULL" not in get
    assert "JOIN activity" not in get
