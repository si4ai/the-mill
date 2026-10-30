"""Isolate mill_home so pytest never writes ~/.mill/session/*.token on this office."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_mill_home(tmp_path_factory, monkeypatch):
    d = tmp_path_factory.mktemp("mill-home")
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(d))
    yield d

# Sql tests that hang (FOR UPDATE / MDL / wedged connector) used to eat the whole
# pytest_sql job (~15 min). Fail the test instead (F192 hang class).
_SQL_TEST_TIMEOUT_S = 120


@pytest.fixture(autouse=True)
def _sql_test_timeout(request):
    if request.node.get_closest_marker("sql") is None:
        yield
        return
    import signal

    node = request.node.nodeid

    def _on_alarm(signum, frame):
        raise TimeoutError(f"sql test exceeded {_SQL_TEST_TIMEOUT_S}s: {node}")

    prev = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(_SQL_TEST_TIMEOUT_S)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev)
