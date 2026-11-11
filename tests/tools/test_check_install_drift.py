"""Card 1145: check_install_drift reports install drift by object hash.

Normalize and diff tests need no MySQL: they fail on doctored input and
pass on clean input. The live install-then-doctor test is marked sql and
skips when no throwaway mysqld is available (CI pytest_sql_run is the
proof). The compare command exits 0 by default even when it finds drift
(it is not a CI gate).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_install_drift import (
    default_mysqld_basedir,
    diff_dumps,
    normalize,
    sha256,
)

ROOT = Path(__file__).resolve().parents[2]


def test_normalize_strips_definer_whitespace_and_auto_increment() -> None:
    raw = "CREATE DEFINER=`office`@`%` PROCEDURE p()  BEGIN  SELECT  1; END"
    assert "DEFINER" not in normalize(raw)
    assert "  " not in normalize(raw)
    table = "ENGINE=InnoDB AUTO_INCREMENT=99 DEFAULT CHARSET=utf8mb4"
    assert "AUTO_INCREMENT" not in normalize(table)
    assert sha256("A  B") == sha256("A B")


def test_diff_dumps_reports_mismatch_and_extra() -> None:
    gold = {"routine PROCEDURE.a": {"sha256": "aaa"}, "table t": {"sha256": "ttt"}}
    subject = {"routine PROCEDURE.a": {"sha256": "bbb"}, "routine PROCEDURE.probe": {"sha256": "p"}}
    findings = diff_dumps(gold, subject)
    kinds = {(f["object"], f["kind"]) for f in findings}
    assert ("routine PROCEDURE.a", "hash_mismatch") in kinds
    assert ("table t", "missing_from_subject") in kinds
    assert ("routine PROCEDURE.probe", "extra_in_subject") in kinds


def test_clean_dumps_have_no_drift() -> None:
    gold = {"routine PROCEDURE.a": {"sha256": "aaa"}, "table t": {"sha256": "ttt"}}
    assert diff_dumps(gold, gold) == []


@pytest.mark.sql
def test_install_then_doctor_on_throwaway_mysqld(tmp_path: Path) -> None:
    if not (ROOT / "agent_coord" / "install" / "migrate.py").is_file():
        pytest.skip("the-mill checkout is missing migrate.py")
    if default_mysqld_basedir() is None:
        pytest.skip("no local mysqld (CI pytest_sql_run is the proof)")
    try:
        import mysql.connector  # noqa: F401
    except ImportError:
        pytest.skip("mysql.connector is not installed")
    from tools.check_install_drift import run_demo

    assert run_demo(ROOT, tmp_path / "mysqld", tmp_path) == 0
