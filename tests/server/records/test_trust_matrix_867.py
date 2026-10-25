"""docs/requirements/admin.md sections 1-3 on the paths card 867 touched, at both trust levels.

Card 867 moved the claim, unclaim and pass guards into cmd_claim, cmd_unclaim and
cmd_pass (the Admin accept of pass --done reads the Admin roster in SQL) and the
raw writers (mail, push, door, todo) into SPs. Each gated path keeps main's
trust and Admin rule:
- sec 3, any desk at either trust: claim, unclaim, pass ship (pass --done is the
  asker or Admin; done-when is the asker or Admin).
- sec 2, trust-gated: assign (high any desk, limited Admin; unassigned only, for
  Admin too), member add/remove of another desk (self is open), label first use.
- sec 1, Admin at either trust: invite door keys (mint, enable, ttl, revoke) and
  setting trust.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ASKER, VOL, PLAIN, ADMIN = "ta867", "tv867", "tp867", "tadm867"
TRUST = pytest.mark.parametrize("trust", ["high", "limited"])


class _Book:
    def __init__(self, cn):
        self._cn = cn


@pytest.fixture()
def book(cn, monkeypatch):
    seed_names(cn, ("unit", "roster"), ("crew867", "roster"),
               (ASKER, "desk"), (VOL, "desk"), (PLAIN, "desk"), (ADMIN, "desk"))
    rec_member.put_admin(cn, ADMIN)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return _Book(cn)


def _open(book, need):
    rpc._h_open(book, {"need": need}, "unit", ASKER)
    return need


def _status(cn, need):
    return rec_todo.find(cn, "unit", need)["status"]


# sec 3: any desk, either trust (the guards that moved into the SPs).


@TRUST
def test_claim_unclaim_pass_are_any_desk(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = _open(book, f"m3-{trust}")
    rpc._h_claim(book, {"need": need}, "unit", PLAIN)
    rpc._h_yield(book, {"need": need}, "unit", PLAIN)
    rpc._h_claim(book, {"need": need}, "unit", PLAIN)
    assert rpc._h_pass(book, {"need": need}, "unit", PLAIN)["status"] == "shipped"


@TRUST
def test_pass_done_is_the_asker_or_admin(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = _open(book, f"md-{trust}")
    rpc._h_claim(book, {"need": need}, "unit", VOL)
    rpc._h_pass(book, {"need": need}, "unit", VOL)
    with pytest.raises(CoordError, match="who-may: pass shipped->done is the asker"):
        rpc._h_pass(book, {"need": need, "step": "done"}, "unit", PLAIN)
    assert _status(cn, need) == "shipped"
    assert rpc._h_pass(book, {"need": need, "step": "done"}, "unit", ADMIN)["status"] == "done"


@TRUST
def test_done_when_is_the_asker_or_admin(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = _open(book, f"mw-{trust}")
    with pytest.raises(CoordError, match="who-may: done-when is the asker or Admin"):
        rpc._h_note(book, {"need": need, "done_when": "x"}, "unit", PLAIN)
    assert rpc._h_note(book, {"need": need, "done_when": "y"}, "unit", ADMIN)["done_when"] == "y"
    assert rpc._h_note(book, {"need": need, "done_when": "z"}, "unit", ASKER)["done_when"] == "z"


# sec 2: trust-gated.


@TRUST
def test_assign_is_any_desk_high_admin_limited_and_unassigned_only(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = _open(book, f"ma-{trust}")
    if trust == "limited":
        with pytest.raises(CoordError, match="mill Admin required"):
            rpc._h_assign(book, {"need": need, "desk": VOL}, "unit", PLAIN)
        assert _status(cn, need) == "open"
        rpc._h_assign(book, {"need": need, "desk": VOL}, "unit", ADMIN)
    else:
        rpc._h_assign(book, {"need": need, "desk": VOL}, "unit", PLAIN)
    assert rec_todo.find(cn, "unit", need)["assigned"] == VOL
    with pytest.raises(CoordError, match="relinquish"):
        rpc._h_assign(book, {"need": need, "desk": PLAIN}, "unit", ADMIN)


@TRUST
def test_member_add_remove_of_another_desk_is_gated_self_is_open(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)

    def member(verb, desk, who):
        return rpc._h_member(book, {"verb": verb, "group": "crew867", "desk": desk}, "unit", who)

    member("member-add", PLAIN, PLAIN)
    member("member-remove", PLAIN, PLAIN)
    if trust == "limited":
        for verb in ("member-add", "member-remove"):
            with pytest.raises(CoordError, match="mill Admin required"):
                member(verb, VOL, PLAIN)
        member("member-add", VOL, ADMIN)
        member("member-remove", VOL, ADMIN)
    else:
        member("member-add", VOL, PLAIN)
        member("member-remove", VOL, PLAIN)


@TRUST
def test_label_first_use_creates_only_at_high_trust(book, cn, monkeypatch, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    need = _open(book, f"ml-{trust}")
    tid = int(rec_todo.find(cn, "unit", need)["id"])
    tag = f"lab867{trust}"
    body = {"verb": "label-add", "type": "todo", "id": tid, "label": tag}
    if trust == "limited":
        with pytest.raises(CoordError, match=f"label: no name {tag}. mill create label {tag}"):
            rpc._h_label(book, body, "unit", PLAIN)
        assert rec_name.get(cn, tag, "label") is None
    else:
        rpc._h_label(book, body, "unit", PLAIN)
        assert rec_name.get(cn, tag, "label") is not None


# sec 1: Admin at either trust.


def _stub_door(monkeypatch):
    from agent_coord.server.admin import door as door_mod

    done = []
    for fn in ("mint_key", "enable_key", "set_key_ttl", "revoke_key", "set_door", "record_join"):
        monkeypatch.setattr(door_mod, fn, lambda *a, _fn=fn, **k: done.append(_fn) or {"ok": True})
    return done


@TRUST
@pytest.mark.parametrize("action", ["mint", "ttl", "revoke", "door", "join"])
def test_wall_invite_door_keys_are_admin(monkeypatch, trust, action):
    """POST /api/admin/invites: an Admin bearer or signed-in Admin human, never the body owner."""
    from agent_coord.server.admin import invites as inv

    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    done = _stub_door(monkeypatch)

    class C:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    data = {"action": action, "owner": "DESK_admin", "key_id": "k1", "ttl": "1h", "door": "invite",
            "party_id": "p1"}
    monkeypatch.setattr(inv, "_mutate_ok", lambda *a, **k: False)
    with pytest.raises(CoordError, match="not proof"):
        inv.post_invites(dict(data), office=C)
    assert done == []
    monkeypatch.setattr(inv, "_mutate_ok", lambda *a, **k: True)
    inv.post_invites(dict(data), office=C)
    assert len(done) == 1


@TRUST
@pytest.mark.parametrize(
    "body",
    [{"mint": 1}, {"enable": "k1"}, {"ttl": "1h", "ttl_for": "k1"}, {"revoke": "k1"}, {"door": "invite"}],
    ids=["mint", "enable", "ttl", "revoke", "door"],
)
def test_mill_invite_door_keys_are_admin(book, cn, monkeypatch, trust, body):
    """mill invite: the desk must be on the Admin roster (the real member table)."""
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    done = _stub_door(monkeypatch)
    with pytest.raises(CoordError, match="mill Admin required"):
        rpc._h_invite(book, dict(body), "unit", PLAIN)
    assert done == []
    rpc._h_invite(book, dict(body), "unit", ADMIN)
    assert len(done) == 1


@TRUST
def test_setting_trust_is_admin(book, cn, monkeypatch, tmp_path, trust):
    monkeypatch.setenv("AGENT_COORD_TRUST", trust)
    monkeypatch.setenv("AGENT_COORD_CONFIG", str(tmp_path / "config.toml"))
    flips = []
    monkeypatch.setattr("agent_coord.config.set_mill_trust", lambda level, *a: flips.append(level) or level)
    with pytest.raises(CoordError, match="mill Admin required"):
        rpc._h_trust(book, {"level": "high"}, "unit", PLAIN)
    assert flips == []
    rpc._h_trust(book, {"level": trust}, "unit", ADMIN)
    assert flips == [trust]
