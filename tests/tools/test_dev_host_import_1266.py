"""Card 1266: dev host book import script (dry-run, guards, and a real run)."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.dev_host_import import (
    DevHostImportError,
    classify_precheck,
    import_bearer_salts,
    main,
    point_database_key,
    redact_output,
    refuse_if_session_is_upload,
    require_ident,
    rewrite_dump,
)

ROOT = Path(__file__).resolve().parents[2]
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_L = "c" * 64
SECRET = "s3cret-value"


def test_require_ident_rejects_bad_names() -> None:
    with pytest.raises(DevHostImportError, match="plain identifier"):
        require_ident("bad-name", what="upload database name")
    with pytest.raises(DevHostImportError, match="plain identifier"):
        require_ident("has space")
    with pytest.raises(DevHostImportError, match="plain identifier"):
        require_ident("foo;bar")
    with pytest.raises(DevHostImportError, match="plain identifier"):
        require_ident("")
    assert require_ident("mill_20261120") == "mill_20261120"


def test_main_rejects_bad_new_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dump = tmp_path / "book.sql"
    dump.write_text("SELECT 1;\n", encoding="utf-8")
    assert main(["--dump", str(dump), "--new-database", "bad-name"]) == 1
    err = capsys.readouterr().err
    assert "plain identifier" in err
    assert "bad-name" not in err or "identifier" in err


def test_refuse_if_session_is_the_upload() -> None:
    with pytest.raises(DevHostImportError, match="session database is the upload"):
        refuse_if_session_is_upload("mill_up", "mill_up")
    with pytest.raises(DevHostImportError, match="session database is the upload"):
        refuse_if_session_is_upload("Mill_Up", "mill_up")
    refuse_if_session_is_upload("mill_cur", "mill_up")


def test_rewrite_dump_rewrites_use_and_drops_drop_database() -> None:
    raw = (
        "CREATE DATABASE /*!32312 IF NOT EXISTS*/ `cloud_book` "
        "/*!40100 DEFAULT CHARACTER SET utf8mb4 */;\n"
        "/*!40000 DROP DATABASE IF EXISTS `cloud_book`*/;\n"
        "DROP DATABASE IF EXISTS `cloud_book`;\n"
        "USE `cloud_book`;\n"
        "INSERT INTO name (type, name) VALUES ('desk', 'd1');\n"
    )
    out = rewrite_dump(raw, "dev_in")
    assert "DROP DATABASE" not in out
    assert "USE `dev_in`;" in out
    assert "CREATE DATABASE IF NOT EXISTS `dev_in`" in out
    assert "cloud_book" not in out
    assert "INSERT INTO name" in out
    with pytest.raises(DevHostImportError, match="plain identifier"):
        rewrite_dump(raw, "dev-in")


def test_classify_precheck_reports_cross_type_and_current_only_desks() -> None:
    current = [
        ("shared", "desk"),
        ("only_here", "desk"),
        ("cross", "desk"),
        ("Office", "roster"),
    ]
    upload = [
        ("shared", "desk"),
        ("cross", "roster"),
        ("only_up", "desk"),
        ("Office", "roster"),
    ]
    report = classify_precheck(current, upload)
    # cross is a desk only on the current book, and also a type conflict.
    assert report["current_only_desks"] == ["cross", "only_here"]
    assert report["type_conflicts"] == [
        {"name": "cross", "current": "desk", "upload": "roster"}
    ]
    flipped = classify_precheck([("n", "roster")], [("n", "desk")])
    assert flipped["type_conflicts"] == [
        {"name": "n", "current": "roster", "upload": "desk"}
    ]
    clean = classify_precheck([("d", "desk")], [("d", "desk")])
    assert clean == {"type_conflicts": [], "current_only_desks": []}


def test_point_database_key_keeps_other_lines_and_copies_the_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    bak = tmp_path / "config.toml.bak"
    cfg.write_text(
        'host = "127.0.0.1"\n'
        f'password = "{SECRET}"\n'
        'database = "old_book"\n'
        'trust = "high"\n',
        encoding="utf-8",
    )
    point_database_key(cfg, "new_book", bak)
    text = cfg.read_text(encoding="utf-8")
    assert 'database = "new_book"' in text
    assert 'password = "' + SECRET + '"' in text
    assert 'trust = "high"' in text
    assert bak.read_text(encoding="utf-8").count('database = "old_book"') == 1


def test_redact_output_strips_a_sixty_four_char_hash() -> None:
    line = "token_hash=" + HASH_A + " leftover"
    out = redact_output(line)
    assert HASH_A not in out
    assert "[hash]" in out or "[redacted]" in out


def _mysql_up():
    """Job MySQL, or a throwaway mysqld, or skip (CI pytest_sql_run is the proof)."""
    try:
        import mysql.connector  # noqa: F401
    except ImportError:
        pytest.skip("mysql.connector is not installed")
    from tools.check_install_drift import (
        LocalMysqld,
        default_mysqld_binary,
        job_mysql_kwargs,
    )

    job = job_mysql_kwargs()
    if job is not None:
        return job, None
    binary = default_mysqld_binary()
    if binary is None:
        pytest.skip("no job MySQL and no local mysqld (CI pytest_sql_run is the proof)")
    return None, binary


def _write_config(path: Path, kw: dict, database: str) -> None:
    password = kw.get("password") or ""
    lines = [
        f'host = "{kw.get("host", "127.0.0.1")}"\n',
        f'port = "{kw.get("port", 3306)}"\n',
        f'user = "{kw.get("user", "root")}"\n',
        f'password = "{password}"\n',
        f'database = "{database}"\n',
    ]
    path.write_text("".join(lines), encoding="utf-8")
    path.chmod(0o600)


def _seed_book(cn, *, shared_hash: str, extra_desk: str | None, extra_hash: str | None,
               cross_as: str) -> None:
    cur = cn.cursor()
    try:
        cur.execute("INSERT INTO name (type, name) VALUES ('desk', 'shared')")
        cur.execute(
            "INSERT INTO seat (desk_id, token_hash) "
            "SELECT id, %s FROM name WHERE type = 'desk' AND name = 'shared'",
            (shared_hash,),
        )
        if extra_desk:
            cur.execute("INSERT INTO name (type, name) VALUES ('desk', %s)", (extra_desk,))
            cur.execute(
                "INSERT INTO seat (desk_id, token_hash) "
                "SELECT id, %s FROM name WHERE type = 'desk' AND name = %s",
                (extra_hash, extra_desk),
            )
        cur.execute("INSERT INTO name (type, name) VALUES (%s, 'cross')", (cross_as,))
        cn.commit()
    finally:
        cur.close()


def _bind_env(monkeypatch: pytest.MonkeyPatch, kw: dict, config: Path) -> None:
    monkeypatch.setenv("AGENT_COORD_HOST", str(kw.get("host") or "127.0.0.1"))
    monkeypatch.setenv("AGENT_COORD_PORT", str(kw.get("port") or 3306))
    monkeypatch.setenv("AGENT_COORD_USER", str(kw.get("user") or "root"))
    monkeypatch.setenv("AGENT_COORD_PASSWORD", str(kw.get("password") or ""))
    monkeypatch.setenv("AGENT_COORD_CONFIG", str(config))
    monkeypatch.delenv("AGENT_COORD_DATABASE", raising=False)


def _hash_for(cn, database: str, desk: str) -> str:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT s.token_hash FROM `" + database + "`.seat s "
            "JOIN `" + database + "`.name n ON n.id = s.desk_id "
            "WHERE n.type = 'desk' AND n.name = %s",
            (desk,),
        )
        row = cur.fetchone()
        return "" if not row or row[0] is None else str(row[0])
    finally:
        cur.close()


@pytest.mark.sql
def test_dry_run_wrong_side_and_real_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    job, binary = _mysql_up()
    server = None
    if job is None:
        from tools.check_install_drift import LocalMysqld

        server = LocalMysqld(tmp_path / "mysqld", binary)
        server.start()
        boot = server.connect()
        try:
            cur = boot.cursor()
            cur.execute("SET GLOBAL log_bin_trust_function_creators = 1")
            cur.close()
        finally:
            boot.close()
        kw = server.connect_kwargs()
    else:
        kw = dict(job)
        kw.pop("database", None)

    from tests.beta_book import drop_db, make_main_book
    from tests.sql_isolate import throwaway_db
    from tools import dev_host_import as dhi

    cfg = tmp_path / "config.toml"
    # Bind env before make_main_book so admin_conn sees this MySQL.
    _bind_env(monkeypatch, kw, cfg)
    current_cn = upload_cn = None
    current_db = upload_src = new_db = None
    try:
        current_cn, current_db = make_main_book("mill_1266c", routines=True)
        upload_cn, upload_src = make_main_book("mill_1266u", routines=True)
        _seed_book(
            current_cn,
            shared_hash=HASH_A,
            extra_desk="only_here",
            extra_hash=HASH_L,
            cross_as="desk",
        )
        _seed_book(
            upload_cn,
            shared_hash=HASH_B,
            extra_desk=None,
            extra_hash=None,
            cross_as="roster",
        )
        _write_config(cfg, kw, current_db)
        dump = tmp_path / "cloud.sql"
        dhi.dump_database(upload_cn, dump, upload_src)
        new_db = throwaway_db("mill_1266n")
        backup = tmp_path / "current.sql"
        cfg_bak = tmp_path / "config.toml.bak"

        # Wrong-side: a connection whose session is the upload must refuse.
        with pytest.raises(DevHostImportError, match="session database is the upload"):
            import_bearer_salts(upload_cn, upload_src)

        rc = main(
            [
                "--dump",
                str(dump),
                "--new-database",
                new_db,
                "--config",
                str(cfg),
                "--backup",
                str(backup),
                "--config-backup",
                str(cfg_bak),
                "--checkout",
                str(ROOT),
                "--dry-run",
            ]
        )
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 0, out
        assert "dry-run: true" in out
        assert "type_conflicts:" in out
        assert "cross: current desk, upload roster" in out
        assert "only_here" in out
        assert "execute: yes" in out
        assert HASH_A not in out and HASH_B not in out and HASH_L not in out
        assert SECRET not in out
        assert not backup.exists()
        assert cfg.read_text(encoding="utf-8").count(f'database = "{current_db}"') == 1
        assert _hash_for(upload_cn, upload_src, "shared") == HASH_B
        # dry-run dropped the temporary upload database
        admin = dhi.connect(dhi.connect_kwargs(cfg), autocommit=True)
        try:
            assert not dhi.database_exists(admin, new_db)
        finally:
            admin.close()

        rc = main(
            [
                "--dump",
                str(dump),
                "--new-database",
                new_db,
                "--config",
                str(cfg),
                "--backup",
                str(backup),
                "--config-backup",
                str(cfg_bak),
                "--checkout",
                str(ROOT),
            ]
        )
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 0, out
        assert "imported_salts:" in out
        assert "apply: ok" in out
        assert "restart:" in out and "does not restart" in out
        assert "rollback:" in out and current_db in out
        assert HASH_A not in out and HASH_B not in out and HASH_L not in out
        assert SECRET not in out
        text = cfg.read_text(encoding="utf-8")
        assert f'database = "{new_db}"' in text
        assert cfg_bak.is_file()
        assert backup.is_file()
        admin = dhi.connect(dhi.connect_kwargs(cfg), autocommit=True)
        try:
            assert dhi.database_exists(admin, current_db)
            assert dhi.database_exists(admin, new_db)
            assert _hash_for(admin, new_db, "shared") == HASH_A
            # ids are not remapped: the upload row for shared keeps its id
            cur = admin.cursor()
            cur.execute(
                "SELECT n.id FROM `" + upload_src + "`.name n WHERE n.type='desk' AND n.name='shared'"
            )
            src_id = cur.fetchone()[0]
            cur.execute(
                "SELECT n.id FROM `" + new_db + "`.name n WHERE n.type='desk' AND n.name='shared'"
            )
            new_id = cur.fetchone()[0]
            cur.close()
            assert int(new_id) == int(src_id)
        finally:
            admin.close()
        # original current book unchanged
        assert _hash_for(current_cn, current_db, "shared") == HASH_A
    finally:
        capsys.readouterr()  # do not leak hashes if a later close fails
        if new_db:
            try:
                admin = dhi.connect(dhi.connect_kwargs(cfg), autocommit=True)
                try:
                    dhi.drop_database(admin, new_db)
                finally:
                    admin.close()
            except Exception:
                pass
        if current_cn is not None and current_db:
            drop_db(current_cn, current_db)
        if upload_cn is not None and upload_src:
            drop_db(upload_cn, upload_src)
        if server is not None:
            server.stop()
