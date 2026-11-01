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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "fresh_schema: owns a unique DB and full tip/beta apply (migration/parity/wipe only)",
    )
    config.addinivalue_line(
        "markers",
        "sql_readonly: shared tip book; skip data reset (test does not write)",
    )
    config.addinivalue_line(
        "markers",
        "sql_mutate: shared tip book; truncate data before the test (default for sql)",
    )


def pytest_collection_modifyitems(config, items):
    """Group sql tests from markers: shared vs fresh_schema (xdist loadgroup).

    Shared modules hash across N worker groups so each worker keeps one session
    schema. Each fresh_schema module is its own group and can run in parallel.
    """
    n = getattr(config.option, "numprocesses", None)
    try:
        n_workers = int(n) if n and str(n).isdigit() else 2
    except Exception:
        n_workers = 2
    if n_workers < 1:
        n_workers = 1

    for item in items:
        if item.get_closest_marker("sql") is None:
            continue
        mod = item.module.__name__
        if item.get_closest_marker("fresh_schema") is not None:
            group = f"fresh:{mod}"
        else:
            # Sticky per module so module-scoped fixtures stay on one worker.
            h = sum(ord(c) for c in mod) % n_workers
            group = f"sql_shared:{h}"
        item.add_marker(pytest.mark.xdist_group(group))
        # Default mutating unless marked readonly.
        if (
            item.get_closest_marker("fresh_schema") is None
            and item.get_closest_marker("sql_readonly") is None
            and item.get_closest_marker("sql_mutate") is None
        ):
            item.add_marker(pytest.mark.sql_mutate)


# Data isolation: module-scoped ``cn`` truncates once when the module opens
# (tests/sql_book.connect_shared). Per-test truncate was removed: it ran after
# module arrange fixtures and wiped their seeds (card 986 CI).


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Report shared vs fresh_schema counts and sql_book timings."""
    from tests import sql_book

    tr = terminalreporter
    items = getattr(tr.config, "_sql_group_counts", None)
    # Recount from the reporter's stats when available.
    passed = tr.stats.get("passed", []) + tr.stats.get("xfailed", [])
    shared = fresh = 0
    for rep in tr.stats.get("passed", []) + tr.stats.get("failed", []) + tr.stats.get(
        "xfailed", []
    ):
        # nodeid only; markers not on reports - use stored counts if set.
        pass
    counts = getattr(config, "_mill_sql_group_counts", None)
    tw = tr.write_line
    tw("")
    tw("sql_book (card 986):")
    if counts:
        tw(
            f"  groups: shared={counts.get('shared', 0)} "
            f"fresh_schema={counts.get('fresh', 0)} "
            f"readonly={counts.get('readonly', 0)}"
        )
    for k, v in sorted(sql_book.timings().items()):
        tw(f"  timing {k}={v:.3f}s")


def pytest_sessionfinish(session, exitstatus):
    # Stash collection counts for the terminal summary.
    shared = fresh = readonly = 0
    for item in getattr(session, "items", []) or []:
        if item.get_closest_marker("sql") is None:
            continue
        if item.get_closest_marker("fresh_schema") is not None:
            fresh += 1
        else:
            shared += 1
        if item.get_closest_marker("sql_readonly") is not None:
            readonly += 1
    session.config._mill_sql_group_counts = {
        "shared": shared,
        "fresh": fresh,
        "readonly": readonly,
    }


@pytest.fixture(scope="module")
def cn(request):
    """Worker-shared tip book for @pytest.mark.sql modules (card 986).

    fresh_schema modules get a unique DB applied once and dropped on teardown.
    """
    import os
    from tests import sql_book

    if request.node.get_closest_marker("fresh_schema") is not None:
        mod = request.module.__name__.rsplit(".", 1)[-1]
        c = sql_book.open_fresh_book(
            mod,
            nodeid=request.node.nodeid,
            finalizer_register=request.addfinalizer,
        )
        yield c
        return

    saved = os.environ.pop("AGENT_COORD_DATABASE", None)
    try:
        try:
            c = sql_book.connect_shared(reset=True)
        except Exception as e:
            pytest.skip(f"mysql mill records: {e}")
    except BaseException:
        if saved is not None:
            os.environ["AGENT_COORD_DATABASE"] = saved
        raise
    try:
        yield c
    finally:
        try:
            c.close()
        except Exception:
            pass
        if saved is None:
            os.environ.pop("AGENT_COORD_DATABASE", None)
        else:
            os.environ["AGENT_COORD_DATABASE"] = saved
