"""Floor part fingerprints: miss -> full + fp; hit -> empty + same fp."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import call, conn_kwargs as _conn_kwargs, scalar
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records.floor import floor, floor_scope, parse_floor_fps
from tests.server.records.conftest import seed_names

def test_parse_floor_fps_wire_and_aliases() -> None:
    got = parse_floor_fps(
        {
            "fp": ["mail:a1b2c3d4e5f60718,trees:9f8e7d6c5b4a3210"],
            "fp_todos": ["0123456789abcdef"],
            "fp_junk": ["not-hex"],
        }
    )
    assert got == {
        "mail": "a1b2c3d4e5f60718",
        "trees": "9f8e7d6c5b4a3210",
        "todos": "0123456789abcdef",
    }

def test_mill_fp_function(cn) -> None:
    a = scalar(cn, "SELECT mill_fp(%s)", ("hello",))
    b = scalar(cn, "SELECT mill_fp(%s)", ("hello",))
    c = scalar(cn, "SELECT mill_fp(%s)", ("world",))
    assert a == b
    assert len(a) == 16
    assert a != c
    assert scalar(cn, "SELECT mill_fp(%s)", (None,)) == scalar(cn, "SELECT mill_fp(%s)", ("",))

def test_floor_project_mail_trees_fp_hit_miss(cn, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_trust", lambda: "limited")
    seed_names(cn, ("fpdemo", "roster"), ("a", "desk"), ("b", "desk"))
    rec_mail.insert(cn, "fpdemo", "a", "b", "letter one")
    # Cold: no client fp -> full parts + fp echo
    cold = floor(cn, project="fpdemo", parts=["mail", "trees"])
    assert cold["trust"] == "limited"
    assert "fp" in cold
    assert set(cold["fp"]) == {"mail", "trees"}
    assert len(cold["fp"]["mail"]) == 16
    assert len(cold["fp"]["trees"]) == 16
    assert len(cold["mailbox"]) >= 1
    mail_fp = cold["fp"]["mail"]
    trees_fp = cold["fp"]["trees"]

    # Hit: echoed fps -> empty bodies, same fps
    hit = floor(
        cn,
        project="fpdemo",
        parts=["mail", "trees"],
        client_fps={"mail": mail_fp, "trees": trees_fp},
    )
    assert hit["mailbox"] == []
    assert hit["trees"] == []
    assert hit["desk_unread"] == {}
    assert hit["fp"]["mail"] == mail_fp
    assert hit["fp"]["trees"] == trees_fp

    # Miss after write: new mail busts mail fp; trees may stay
    rec_mail.insert(cn, "fpdemo", "a", "b", "letter two")
    miss = floor(
        cn,
        project="fpdemo",
        parts=["mail", "trees"],
        client_fps={"mail": mail_fp, "trees": trees_fp},
    )
    assert len(miss["mailbox"]) >= 2
    assert miss["fp"]["mail"] != mail_fp
    assert miss["fp"]["trees"] == trees_fp  # letter body does not bump trees
    assert miss["trees"] == []  # trees still hit

    # Second call with new mail fp hits mail
    hit2 = floor(
        cn,
        project="fpdemo",
        parts=["mail", "trees"],
        client_fps={"mail": miss["fp"]["mail"], "trees": trees_fp},
    )
    assert hit2["mailbox"] == []
    assert hit2["fp"]["mail"] == miss["fp"]["mail"]

def test_floor_scope_lan_mail_fp(cn, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_trust", lambda: "limited")
    seed_names(cn, ("fpdemo", "roster"), ("lanfp", "desk"))
    from agent_coord.server.records import join as rec_join

    rec_join.upsert(cn, "fpdemo", "lanfp", "", "a" * 64, "present")
    rec_join.set_lan_ip(cn, "lanfp", "203.0.113.50")
    rec_mail.insert(cn, "fpdemo", "lanfp", "lanfp", "lan letter")

    cold = floor_scope(cn, "lan", "203.0.113.50", parts=["mail", "trees"])
    assert cold["trust"] == "limited"
    assert "fp" in cold
    assert cold["fp"]["trees"]  # constant trees:0 material
    assert len(cold["mailbox"]) >= 1
    mail_fp = cold["fp"]["mail"]
    trees_fp = cold["fp"]["trees"]

    hit = floor_scope(
        cn,
        "lan",
        "203.0.113.50",
        parts=["mail", "trees"],
        client_fps={"mail": mail_fp, "trees": trees_fp},
    )
    assert hit["mailbox"] == []
    assert hit["trees"] == []
    assert hit["fp"]["mail"] == mail_fp
    assert hit["fp"]["trees"] == trees_fp

def test_floor_scope_role_mail_and_agents(cn, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_trust", lambda: "limited")
    seed_names(cn, ("fprole", "roster"), ("rolefp", "desk"), ("fprole", "roster"))
    from agent_coord.server.records import join as rec_join
    from agent_coord.server.records import member as rec_member

    rec_member.put(cn, "fprole", "rolefp", kind="roster")
    rec_join.upsert(cn, "fprole", "rolefp", "", "c" * 64, "present")
    rec_mail.insert(cn, "fprole", "rolefp", "rolefp", "role letter")
    cold = floor_scope(cn, "role", "fprole", parts=["mail", "agents"])
    assert any("role letter" in str(m.get("body") or "") for m in cold["mailbox"])
    assert any(str(a.get("owner") or "") == "rolefp" for a in cold["agents"])

def test_mill_floor_fp_direct(cn) -> None:
    seed_names(cn, ("fpdirect", "roster"), ("x", "desk"), ("y", "desk"))
    rec_mail.insert(cn, "fpdirect", "x", "y", "direct")
    rows = call(cn, "mill_floor_fp", ["project", "fpdirect", "mail"])
    assert len(rows) == 1
    assert rows[0]["part"] == "mail"
    assert len(rows[0]["fp"]) == 16
    trees = call(cn, "mill_floor_fp", ["lan", "203.0.113.9", "trees"])
    assert trees[0]["fp"] == scalar(cn, "SELECT mill_fp(%s)", ("trees:0",))
