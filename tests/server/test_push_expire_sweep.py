"""F17: the 30-day push sweep runs from the wall on a timer, not inside each take."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_coord.server import push


def test_sweep_cadence_is_twice_a_day() -> None:
    assert push.PUSH_EXPIRE_EVERY_S == 12 * 60 * 60


def test_expire_sweep_logs_and_closes() -> None:
    cn = MagicMock()
    lines = []
    with patch("agent_coord.server.records.db.connect", return_value=cn), patch(
        "agent_coord.server.records.push.expire", return_value={"deleted": 7, "cut": "2026-09-17"}
    ), patch.object(push, "perf_log", side_effect=lambda op, ms, **kv: lines.append((op, kv))):
        out = push.expire_sweep()
    assert out == {"ok": True, "deleted": 7, "cut": "2026-09-17"}
    assert lines == [("push.expire", {"deleted": 7, "ok": 1})]
    cn.close.assert_called_once()


def test_expire_sweep_failure_is_logged_not_raised() -> None:
    cn = MagicMock()
    lines = []
    with patch("agent_coord.server.records.db.connect", return_value=cn), patch(
        "agent_coord.server.records.push.expire", side_effect=RuntimeError("book down")
    ), patch.object(push, "perf_log", side_effect=lambda op, ms, **kv: lines.append((op, kv))):
        out = push.expire_sweep()
    assert out["ok"] is False
    assert "book down" in out["error"]
    assert lines[0][0] == "push.expire" and lines[0][1]["ok"] == 0
    cn.close.assert_called_once()


def test_expire_sweep_without_a_book_does_not_raise() -> None:
    with patch("agent_coord.server.records.db.connect", side_effect=RuntimeError("no book")), patch.object(
        push, "perf_log"
    ):
        assert push.expire_sweep()["ok"] is False


def test_wall_start_runs_the_sweep_once(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from agent_coord.server.asgi import make_asgi_app
    from agent_coord.lib.observe import parse_roots

    calls = []
    with patch("agent_coord.server.push.expire_sweep", side_effect=lambda: calls.append(1) or {"ok": True}), patch(
        "agent_coord.server.score_tick.tick", return_value={}
    ), patch("agent_coord.server.records.db.warm_pool"), patch(
        "agent_coord.server.records.db.warm_read_paths"
    ):
        app = make_asgi_app(parse_roots(cwd=tmp_path), api_only=True)
        with TestClient(app):
            deadline = time.monotonic() + 5
            while not calls and time.monotonic() < deadline:
                time.sleep(0.05)
    assert calls == [1]


def test_take_no_longer_sweeps() -> None:
    sql = (Path(push.__file__).resolve().parent / "sql" / "sp_push.sql").read_text(encoding="utf-8")
    take = sql.split("CREATE PROCEDURE mill_push_take(", 1)[1].split("END //", 1)[0]
    assert "GROUP BY" not in take
    assert "INSERT INTO wake" not in take
    assert "created < v_cut" not in take
    sweep = sql.split("CREATE PROCEDURE mill_push_expire()", 1)[1].split("END //", 1)[0]
    assert "INSERT INTO wake" in sweep and "DELETE FROM wake" in sweep


def test_f17_names_the_push_expire_row() -> None:
    path = Path(__file__).resolve().parents[2] / "docs" / "protocol" / "sync.md"
    row = next(line for line in path.read_text(encoding="utf-8").splitlines() if "F17" in line)
    assert "push-expire-off-take" in row
