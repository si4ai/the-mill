"""Card 1267: a hold is an explicit mutex with a one-use release key.

A take returns release_key once; only its sha256 is stored, as meta.kh on the take
transition. A second take is refused for every caller, same desk included. A drop
with the key frees the hold once, for any desk that has the key. A wrong or spent
key is refused and the hold stays. A drop without a key is the admin.md override
(hold_force). A hand-off (`mill hold X --key K`) spends K and mints a new key (K25).
Every refusal writes a hold_refuse transition in the same transaction (K04).

The tests call the mill handlers the CLI reaches (rpc._h_hold / rpc._h_drop), from
separate OS processes for the race, and assert the rows written.
"""
from __future__ import annotations

import json
import multiprocessing as mp

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.helpers.hold_key import key_hash, new_key
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.db import rows_done
from tests.server.records.conftest import admin_desk, seed_names

pytestmark = pytest.mark.sql

R = "r1267"
A = "d1267-a"
B = "d1267-b"
ADMIN = "d1267-admin"
RACERS = tuple(f"d1267-r{i}" for i in range(6))


class _B:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture()
def book(cn, monkeypatch):
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    seed_names(cn, (R, "roster"), (A, "desk"), (B, "desk"), *((d, "desk") for d in RACERS))
    for d in (A, B) + RACERS:
        rec_join.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d))
    admin_desk(cn, ADMIN)
    cn.commit()
    return cn


def _take(cn, desk: str, res: str, *, key: str | None = None) -> tuple[dict, str]:
    k, kh = new_key()
    body = {"resource": res, "kh": kh}
    if key is not None:
        body["key"] = key
    out = rpc._h_hold(_B(cn), body, R, desk)
    return out, k


def _drop(cn, desk: str, res: str, key: str | None = None) -> dict:
    body = {"resource": res}
    if key is not None:
        body["key"] = key
    return rpc._h_drop(_B(cn), body, R, desk)


def _rows(cn, res: str) -> list[dict]:
    return rows_done(
        cn,
        "SELECT t.id, t.from_state, t.to_state, t.reason, t.desk_id, t.meta FROM transition t"
        " JOIN hold h ON h.id = t.activity_id JOIN name n ON n.id = h.resource_id"
        " WHERE t.activity_type = 'hold' AND n.type = 'res' AND n.name = %s ORDER BY t.id",
        (res,),
    )


def _meta(row: dict) -> dict:
    m = row.get("meta")
    if m is None:
        return {}
    return m if isinstance(m, dict) else json.loads(m)


def _holder(cn, res: str) -> str | None:
    got = rows_done(
        cn,
        "SELECT dn.name AS desk FROM hold h JOIN name rn ON rn.id = h.resource_id"
        " LEFT JOIN name dn ON dn.id = h.desk_id WHERE rn.type = 'res' AND rn.name = %s",
        (res,),
    )
    return got[0]["desk"] if got else None


def _did(cn, desk: str) -> int:
    return int(rows_done(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0]["id"])


def test_take_returns_key_and_stores_only_its_hash(book) -> None:
    cn = book
    res = "h1267/hash"
    out, k = _take(cn, A, res)
    assert out["ok"] is True and out["held"] is True, out
    assert "refreshed" not in out, out
    takes = [r for r in _rows(cn, res) if r["reason"] == "hold_grant"]
    assert len(takes) == 1
    assert _meta(takes[0]) == {"kh": key_hash(k)}
    # The plain key is in no row of the book.
    for t in ("transition", "activity", "hold"):
        dump = json.dumps(rows_done(cn, f"SELECT * FROM {t}"), default=str)
        assert k not in dump, t


def test_same_desk_second_take_is_refused(book) -> None:
    cn = book
    res = "h1267/same"
    first, _ = _take(cn, A, res)
    assert first["held"] is True
    second, _ = _take(cn, A, res)
    assert second["ok"] is False and second["held"] is False, second
    assert second["refused"] == "held" and second["holder"] == A, second
    assert second.get("since") and second.get("next"), second
    ref = [r for r in _rows(cn, res) if r["reason"] == "hold_refuse"]
    assert len(ref) == 1
    aid = _did(cn, A)
    assert _meta(ref[0]) == {"op": "take", "asker": aid, "holder": aid}


def test_cross_desk_take_refused_and_recorded(book) -> None:
    cn = book
    res = "h1267/cross"
    _take(cn, A, res)
    out, _ = _take(cn, B, res)
    assert out["refused"] == "held" and out["holder"] == A, out
    ref = [r for r in _rows(cn, res) if r["reason"] == "hold_refuse"]
    assert _meta(ref[-1]) == {"op": "take", "asker": _did(cn, B), "holder": _did(cn, A)}


def test_right_key_frees_once_and_reuse_is_refused(book) -> None:
    cn = book
    res = "h1267/once"
    _, k = _take(cn, A, res)
    out = _drop(cn, A, res, k)
    assert out["released"] is True, out
    assert _holder(cn, res) is None
    drops = [r for r in _rows(cn, res) if r["reason"] == "hold_drop"]
    assert len(drops) == 1 and int(drops[0]["desk_id"]) == _did(cn, A)
    again = _drop(cn, A, res, k)
    assert again["released"] is False and again.get("next"), again
    # Spent key on a retaken hold: refused, the new holder keeps it.
    _take(cn, B, res)
    third = _drop(cn, A, res, k)
    assert third["released"] is False, third
    assert _holder(cn, res) == B
    refused = [r for r in _rows(cn, res) if r["reason"] == "hold_refuse" and _meta(r).get("op") == "drop"]
    assert len(refused) == 2


def test_wrong_key_is_refused_and_hold_stays(book) -> None:
    cn = book
    res = "h1267/wrong"
    _take(cn, A, res)
    out = _drop(cn, A, res, new_key()[0])
    assert out["released"] is False, out
    assert "key" in str(out.get("reason") or "") and out.get("next"), out
    assert _holder(cn, res) == A


def test_other_desk_frees_with_the_key(book) -> None:
    cn = book
    res = "h1267/handed"
    _, k = _take(cn, A, res)
    out = _drop(cn, B, res, k)
    assert out["released"] is True, out
    assert _holder(cn, res) is None
    drop = [r for r in _rows(cn, res) if r["reason"] == "hold_drop"][-1]
    assert int(drop["desk_id"]) == _did(cn, A)
    assert _meta(drop) == {"by": _did(cn, B)}


def test_keyless_own_drop_is_the_override(book, monkeypatch) -> None:
    """K24: the holder's own desk without the key is not a normal drop."""
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    res = "h1267/keyless"
    _take(cn, A, res)
    rec_join.mark_socket(cn, A, up=True)
    out = _drop(cn, A, res)
    assert out["released"] is False, out
    assert _holder(cn, res) == A


def test_forced_drop_by_admin_still_works(book, monkeypatch) -> None:
    cn = book
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    res = "h1267/force"
    _take(cn, A, res)
    rec_join.mark_socket(cn, A, up=True)
    out = _drop(cn, ADMIN, res)
    assert out["released"] is True, out
    assert _holder(cn, res) is None
    force = [r for r in _rows(cn, res) if r["reason"] == "hold_force"]
    assert len(force) == 1 and _meta(force[0]) == {"by": _did(cn, ADMIN)}


def test_handoff_spends_the_key_and_mints_a_new_one(book) -> None:
    """K25: the receiver re-keys; the sender's copy is spent and cannot free it."""
    cn = book
    res = "h1267/handoff"
    _, k = _take(cn, A, res)
    out, k2 = _take(cn, B, res, key=k)
    assert out["ok"] is True and out["held"] is True and out.get("handoff") is True, out
    assert _holder(cn, res) == B
    hand = [r for r in _rows(cn, res) if r["reason"] == "hold_refresh"]
    assert len(hand) == 1 and _meta(hand[0]) == {"kh": key_hash(k2), "from": _did(cn, A)}
    stale = _drop(cn, A, res, k)
    assert stale["released"] is False, stale
    assert _holder(cn, res) == B
    assert _drop(cn, B, res, k2)["released"] is True


def test_take_without_key_hash_is_refused_at_the_boundary(book) -> None:
    with pytest.raises(Exception) as ei:
        rpc._h_hold(_B(book), {"resource": "h1267/nokh"}, R, A)
    assert "kh" in str(ei.value)


def test_contention_score_reads_refusals(book) -> None:
    from agent_coord.server import hold_activity as ha

    cn = book
    res = "h1267/score"
    _, k = _take(cn, A, res)
    _take(cn, A, res)
    _take(cn, B, res)
    _drop(cn, B, res, new_key()[0])
    view = ha.contention_view(cn)
    assert view["same_desk_n"]["n"] >= 1 and view["cross_desk_n"]["n"] >= 1, view
    assert view["refused_drop_n"]["n"] >= 1, view
    assert any(t["resource"] == res for t in view["top_resources"]), view
    for part in ("same_desk_n", "cross_desk_n", "refused_drop_n"):
        assert view[part]["name"] and view[part]["why"], view[part]


# ---- N processes, one never-held name ----


def _racer(db: str, desk: str, res: str, start, out) -> None:
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs

    kw = conn_kwargs()
    kw["database"] = db
    cn = mysql.connector.connect(**kw)
    try:
        start.wait(30)
        got, k = _take(cn, desk, res)
        out.put((desk, bool(got.get("held")), k if got.get("held") else None, got.get("refused")))
    except Exception as e:  # an error is not a refusal: the test fails on it
        out.put((desk, None, None, "error: %s" % (e,)))
    finally:
        cn.close()


@pytest.mark.parametrize("same_desk", [False, True], ids=["cross-desk", "same-desk"])
def test_n_process_take_has_one_winner(book, same_desk) -> None:
    cn = book
    rpc._poke = lambda *a, **k: None  # children are forked; the monkeypatch rides along
    res = "h1267/race-same" if same_desk else "h1267/race-cross"
    db = cn.database
    ctx = mp.get_context("fork")
    start = ctx.Barrier(len(RACERS))
    out = ctx.Queue()
    procs = [
        ctx.Process(target=_racer, args=(db, RACERS[0] if same_desk else d, res, start, out))
        for d in RACERS
    ]
    for p in procs:
        p.start()
    got = [out.get(timeout=60) for _ in procs]
    for p in procs:
        p.join(30)
    errors = [g for g in got if g[1] is None]
    assert not errors, errors
    winners = [g for g in got if g[1]]
    assert len(winners) == 1, got
    assert all(g[3] == "held" for g in got if not g[1]), got
    cn.rollback()
    rows = _rows(cn, res)
    takes = [r for r in rows if r["reason"] == "hold_grant"]
    assert len(takes) == 1 and _meta(takes[0]) == {"kh": key_hash(winners[0][2])}
    assert len([r for r in rows if r["reason"] == "hold_refuse"]) == len(RACERS) - 1
    assert _holder(cn, res) == winners[0][0]


def test_contention_scores_read_by_name(book) -> None:
    from agent_coord.server import hold_activity as ha

    cn = book
    res = "h1267/score-name"
    _take(cn, A, res)
    _take(cn, A, res)
    got = ha.score_view_for_name(cn, "hold-same-desk")
    assert got["score"] == "hold-same-desk" and got["n"] >= 1 and got["why"], got
    assert "hold-same-desk" in ha.SCORE_NAMES


def test_release_key_never_parses_as_a_flag() -> None:
    from agent_coord.helpers.hold_key import new_key

    keys = [new_key()[0] for _ in range(500)]
    assert all(k.startswith("hk_") and len(k) > 40 for k in keys)
    assert len(set(keys)) == len(keys)
