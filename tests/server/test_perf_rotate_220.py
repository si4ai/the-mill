"""#220: mill-perf.log rotates, fast reads stay quiet, startup names the version."""
from __future__ import annotations

from agent_coord.server import push
from agent_coord.server.records import db


def test_mill_perf_keeps_five_files_and_other_logs_do_not(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(push, "_PERF_MAX_BYTES", 64)
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    for i in range(12):
        push.dest_log("mill-perf.log", ("x" * 40) + f" {i}")
    assert (tmp_path / "mill-perf.log").is_file()
    for n in range(1, 5):
        assert (tmp_path / f"mill-perf.log.{n}").is_file()
    assert not (tmp_path / "mill-perf.log.5").exists()
    push.dest_log("mill-api.log", "y" * 80)
    assert (tmp_path / "mill-api.log").is_file()
    assert not (tmp_path / "mill-api.log.1").exists()


def test_fast_select_lines_are_dropped(monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr(
        "agent_coord.server.push.perf_write",
        lambda op, ms, kv, rid=None: seen.append((op, ms, kv)),
    )
    db._perf("sql.mill_mail_select", 3.0, n=2, ok=1)
    db._perf("sql.mill_mail_get", 24.9, n=1, ok=1)
    db._perf("sql.mill_mail_list", 25.0, n=1, ok=1)
    db._perf("sql.mill_mail_insert", 1.0, n=1, ok=1)
    db._perf("sql.mill_mail_select", 1.0, ok=0, err="down")
    db._perf("api.v1.rooms", 1.0, status=200)
    assert ("sql.mill_mail_select", 3.0, {"n": 2, "ok": 1}) not in seen
    assert ("sql.mill_mail_get", 24.9, {"n": 1, "ok": 1}) not in seen
    assert ("sql.mill_mail_list", 25.0, {"n": 1, "ok": 1}) in seen
    assert ("sql.mill_mail_insert", 1.0, {"n": 1, "ok": 1}) in seen
    assert ("sql.mill_mail_select", 1.0, {"ok": 0, "err": "down"}) in seen
    assert ("api.v1.rooms", 1.0, {"status": 200}) in seen


def test_startup_line_names_the_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    from agent_coord.server.asgi import log_startup

    log_startup()
    text = (tmp_path / "mill-perf.log").read_text(encoding="utf-8")
    assert "op=startup" in text
    assert "version=" in text
