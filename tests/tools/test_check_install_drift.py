"""Card 1145: check_install_drift reports install drift by object hash.

Normalize and diff tests need no MySQL: they fail on doctored input and
pass on clean input. The compare command exit codes are pinned here the
same way. The live install-then-doctor test is marked sql; it uses the
job MySQL when AGENT_COORD_HOST is set, otherwise a throwaway mysqld
when a mysqld binary is found (including a distro path such as
/usr/sbin/mysqld), and skips cleanly when neither is present (CI
pytest_sql_run is the proof). The compare command exits 0 by default
even when it finds drift (it is not a CI gate).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools import check_install_drift as cid
from tools.check_install_drift import (
    default_mysqld_binary,
    diff_dumps,
    job_mysql_kwargs,
    mysqld_basedir_if_present,
    mysqld_basedir_of,
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


def test_mysqld_basedir_requires_bin_mysqld(tmp_path: Path) -> None:
    # ubuntu: which(mysqld) -> /usr/sbin/mysqld, parent.parent is /usr
    usr = tmp_path / "usr"
    sbin = usr / "sbin" / "mysqld"
    sbin.parent.mkdir(parents=True)
    sbin.write_text("", encoding="utf-8")
    sbin.chmod(0o755)
    assert mysqld_basedir_if_present(usr) is None
    bindir = tmp_path / "mysql84"
    mysqld = bindir / "bin" / "mysqld"
    mysqld.parent.mkdir(parents=True)
    mysqld.write_text("", encoding="utf-8")
    mysqld.chmod(0o755)
    assert mysqld_basedir_if_present(bindir) == bindir


def test_which_sbin_mysqld_is_spawned_not_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """which() -> .../sbin/mysqld is spawned; basedir/bin/mysqld is not."""
    usr = tmp_path / "usr"
    sbin = usr / "sbin" / "mysqld"
    sbin.parent.mkdir(parents=True)
    sbin.write_text("", encoding="utf-8")
    sbin.chmod(0o755)
    monkeypatch.delenv("MILL_MYSQLD_BASEDIR", raising=False)
    monkeypatch.setattr(cid, "WELL_KNOWN_MYSQLD_BASEDIRS", ())
    monkeypatch.setattr(cid.shutil, "which", lambda name: str(sbin) if name == "mysqld" else None)
    found = default_mysqld_binary()
    assert found == sbin.resolve()
    assert mysqld_basedir_of(found) == usr.resolve()
    server = cid.LocalMysqld(tmp_path / "work", found)
    cmd = server.mysqld_cmd(f"--datadir={server.datadir}")
    assert cmd[0] == str(sbin.resolve())
    assert f"--basedir={usr.resolve()}" in cmd
    assert str(usr / "bin" / "mysqld") not in "".join(cmd)


class _CN:
    def close(self) -> None:
        pass


def test_compare_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cid, "connect", lambda kw: _CN())

    def report(drift: int) -> dict:
        return {
            "counts": {
                "gold": 1,
                "subject": 1,
                "drift": drift,
                "routines": 0,
                "tables": 0,
                "columns": 0,
            },
            "drift": [{"object": "x", "kind": "hash_mismatch"}] if drift else [],
        }

    monkeypatch.setattr(cid, "write_reports", lambda *a, **k: None)
    monkeypatch.setattr(cid, "run_compare", lambda g, s: report(1))
    assert cid.main(["--gold-database", "g", "--subject-database", "s"]) == 0
    assert cid.main(["--gold-database", "g", "--subject-database", "s", "--strict"]) == 1
    monkeypatch.setattr(cid, "run_compare", lambda g, s: report(0))
    assert cid.main(["--gold-database", "g", "--subject-database", "s", "--strict"]) == 0


def test_run_demo_deletes_datadir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeServer:
        def __init__(self, workdir: Path, mysqld: Path, port: int | None = None):
            self.workdir = workdir
            self.datadir = workdir / "data"
            self.datadir.mkdir(parents=True)
            (self.datadir / "ibdata1").write_bytes(b"x")

        def start(self) -> None:
            raise RuntimeError("do not start mysqld in this unit test")

        def stop(self) -> None:
            pass

        def connect_kwargs(self, database: str | None = None) -> dict:
            return {}

    monkeypatch.setattr(cid, "default_mysqld_binary", lambda: tmp_path / "sbin" / "mysqld")
    monkeypatch.setattr(cid, "LocalMysqld", FakeServer)
    work = tmp_path / "work"
    with pytest.raises(RuntimeError, match="do not start"):
        cid.run_demo(ROOT, work, tmp_path)
    assert not (work / "data").exists()


def test_demo_default_out_dir_is_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Path] = {}

    def fake_demo(root: Path, workdir: Path, out_dir: Path) -> int:
        seen["out"] = out_dir
        seen["work"] = workdir
        return 0

    monkeypatch.setattr(cid, "run_demo", fake_demo)
    monkeypatch.chdir(tmp_path)
    assert cid.main(["--demo", "--root", str(ROOT)]) == 0
    assert seen["out"] == tmp_path
    assert seen["out"] != (ROOT / "tools")


@pytest.mark.sql
def test_install_then_doctor_on_throwaway_mysqld(tmp_path: Path) -> None:
    if not (ROOT / "agent_coord" / "install" / "migrate.py").is_file():
        pytest.skip("the-mill checkout is missing migrate.py")
    try:
        import mysql.connector  # noqa: F401
    except ImportError:
        pytest.skip("mysql.connector is not installed")

    job = job_mysql_kwargs()
    if job is not None:
        from tests.sql_isolate import throwaway_db

        gold = throwaway_db("mill_drift_gold")
        subject = throwaway_db("mill_drift_subj")
        try:
            assert cid.compare_fresh_then_doctor(ROOT, job, gold, subject, tmp_path) == 0
        finally:
            for name in (gold, subject):
                try:
                    cid.drop_database(job, name)
                except Exception:
                    pass
        return

    if default_mysqld_binary() is None:
        pytest.skip("no job MySQL and no local mysqld (CI pytest_sql_run is the proof)")
    assert cid.run_demo(ROOT, tmp_path / "mysqld", tmp_path) == 0
    assert not (tmp_path / "mysqld" / "data").exists()
