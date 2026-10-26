"""Beta book files without a server (row F143): each splits into statements, every public routine is re-creatable,
the SP version stamp is deterministic, and the 0.7 install is untouched (the beta files are not in apply_order and
migrate.py's digest does not cover them)."""
from __future__ import annotations

import re

from agent_coord.install import beta_migrate as bm
from agent_coord.install import migrate as m07

FILES = ("beta_ddl.sql", "beta_sp.sql", "beta_migrate.sql", "beta_rollback.sql")


def _read(name: str) -> str:
    return (bm.beta_dir() / name).read_text(encoding="utf-8-sig")


def test_files_split():
    for name in FILES:
        stmts = m07.split_script(_read(name))
        assert len(stmts) > 5, name
        # a comment after ';' on the same line glues two statements together in split_script
        for st in stmts:
            assert not re.search(r";\s*--", st.split("BEGIN")[0]), (name, st[:80])


def test_every_routine_drops_before_create():
    blob = _read("beta_sp.sql")
    made = re.findall(r"^CREATE (PROCEDURE|FUNCTION|EVENT) ([A-Za-z0-9_]+)", blob, re.M)
    dropped = set(re.findall(r"^DROP (?:PROCEDURE|FUNCTION|EVENT) IF EXISTS ([A-Za-z0-9_]+)", blob, re.M))
    assert made and {n for _, n in made} <= dropped


def test_public_routines_have_the_frozen_prefixes():
    names = re.findall(r"^CREATE (?:PROCEDURE|FUNCTION) ([A-Za-z0-9_]+)", _read("beta_sp.sql"), re.M)
    for n in names:
        assert re.match(r"^(cmd_|uc_|mill_span$|mill_hello$|mill_i_|sp_)", n), n


def test_sp_version_is_deterministic():
    v = bm.sp_version()
    assert re.fullmatch(r"sp-[0-9a-f]{12}", v) and v == bm.sp_version()


def test_beta_is_not_in_the_07_install():
    order = [p.name for p in m07.sql_apply_order()]
    assert not any(n.startswith("beta_") for n in order)


def test_no_caller_variables_in_routines():
    # a routine must not read a session @variable the caller could set (lab finding: SPs trusted @who)
    blob = _read("beta_sp.sql")
    assert not re.search(r"@[A-Za-z_]", blob.replace("@@", ""))


def test_identifiers_are_checked():
    import pytest

    for bad in ("x; DROP DATABASE y", "a-b", "", "a" * 65):
        with pytest.raises(ValueError):
            bm._ident(bad)
