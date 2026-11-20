"""Card 1254: a type collision names the type that already holds the name."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import call
from tests.server.records.conftest import admin_desk, seed_names

_TYPES = ("desk", "roster", "label", "tree", "res")


@pytest.mark.parametrize("have", _TYPES)
def test_put_names_the_existing_type(cn, have: str) -> None:
    name = "n1254" + have
    other = "roster" if have == "label" else "label"
    seed_names(cn, (name, have))
    with pytest.raises(Exception, match="name in use: %s is a %s; pick another name" % (name, have)):
        seed_names(cn, (name, other))


def test_mint_names_the_existing_type(cn) -> None:
    admin = admin_desk(cn, "n1254mintby")
    seed_names(cn, ("n1254taken", "tree"))
    with pytest.raises(Exception, match="name in use: n1254taken is a tree; pick another name"):
        rec_name.mint(cn, "n1254taken", "res", by=admin)


def test_mint_desk_names_the_existing_type(cn) -> None:
    seed_names(cn, ("n1254label", "label"))
    with pytest.raises(Exception, match="name in use: n1254label is a label; pick another name"):
        call(cn, "sp_name_mint_desk", ["n1254label", "ab" * 32])


def test_rename_names_the_existing_type(cn) -> None:
    admin = admin_desk(cn, "n1254renby")
    seed_names(cn, ("n1254keep", "desk"), ("n1254move", "roster"))
    with pytest.raises(Exception, match="name in use: n1254keep is a desk; pick another name"):
        rec_name.rename(cn, "n1254move", "n1254keep", "roster", by=admin)
