"""#288 step 1: score is a number series. Trend, gap and the read shape (no SQL).

The handler records a numeric point, reads one score, or lists the roster. A
reply carries its own size as bytes. Regression row F31 (score-series).
"""
from __future__ import annotations

import json

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import score_series as ss
from agent_coord.server.mill_json import with_bytes


@pytest.mark.parametrize(
    "vals,better,want",
    [
        ([], "up", "new"),
        ([5], "up", "new"),
        ([6, 5], "up", "improving"),
        ([5, 6], "up", "worse"),
        ([5, 6], "down", "improving"),
        ([10, 10, 10, 10, 10, 10], "up", "flat"),
        ([0, 0, 0, 0], "down", "flat"),
        ([102, 101, 100, 100, 100, 100], "up", "flat"),
        # 0.7.6 (#307): the newest step decides; an unchanged step is flat.
        ([110, 110, 110, 100, 100, 100], "up", "flat"),
        ([110, 110, 110, 100, 100, 100], "down", "flat"),
        ([1, 1, 1, 9, 9, 9, 500, 500], "up", "flat"),
        ([-5, -5, -5, -10, -10, -10], "up", "flat"),
        ([-5, -10], "up", "improving"),
        ([3, 3, 2], "up", "flat"),
        ([3, 2, 2], "up", "improving"),
    ],
)
def test_trend(vals, better, want) -> None:
    assert ss.trend(vals, better) == want


@pytest.mark.parametrize(
    "latest,target,better,want",
    [
        (585, "500", "down", -85),
        (500, "500", "down", "met"),
        (480, "500", "down", "met"),
        (40, "50", "up", 10),
        (50.5, "50", "up", "met"),
        (0.1, "0.3", "up", 0.2),
        (None, "50", "up", None),
        (5, "", "up", None),
        (5, "soon", "up", None),
    ],
)
def test_gap(latest, target, better, want) -> None:
    assert ss.gap(latest, target, better) == want


@pytest.mark.parametrize("raw", ["", " ", "abc", "nan", "inf", "-inf", None, "1,5"])
def test_number_refuses(raw) -> None:
    assert ss.number(raw) is None


@pytest.mark.parametrize("raw,want", [("12", 12.0), (" -3.5 ", -3.5), ("1e3", 1000.0), (7, 7.0)])
def test_number_takes(raw, want) -> None:
    assert ss.number(raw) == want


def _rows(n: int, *, desk=lambda i: "d1", note=lambda i: f"try {i}") -> list[dict]:
    head = {"id": 7, "kpi": "tokens.loop", "latest": str(n), "target": "500", "better": "down",
            "unit": "tokens", "owner": "unit"}
    if n == 0:
        return [dict(head, point_id=None, v=None, at=None, note=None, desk=None)]
    return [
        dict(head, point_id=100 + i, v=float(900 - 10 * i), at=f"2026-10-18 23:{i:02d}:01.123456",
             note=note(i), desk=desk(i))
        for i in reversed(range(n))
    ]


def test_shape_one_score_under_1kb_with_trend_and_gap() -> None:
    got = ss.shape(_rows(12, desk=lambda i: "unit-builder-long-desk-name"), 10)
    assert len(got) == 1
    one = got[0]
    assert one["latest"] == 790 and one["gap"] == -290 and one["trend"] == "improving"
    assert [p["v"] for p in one["points"]][:3] == [790, 800, 810]
    assert len(one["points"]) == 10
    assert one["points"][0]["at"] == "10-18 23:11"
    # one desk for the run: named once, on the newest point
    assert [("desk" in p) for p in one["points"]] == [True] + [False] * 9
    env, n = with_bytes({"id": "0" * 36, "ok": True, "result": one, "sync": [], "mill": "0.7.5"})
    assert n < 1024, n


def test_shape_desk_named_where_it_changes() -> None:
    got = ss.shape(_rows(4, desk=lambda i: "a" if i < 2 else "b", note=lambda i: ""), 10)[0]
    assert [p.get("desk") for p in got["points"]] == ["b", None, "a", None]
    assert all("note" not in p for p in got["points"])


def test_shape_no_points_uses_stored_latest() -> None:
    rows = _rows(0)
    rows[0]["latest"] = "42"
    one = ss.shape(rows, 10)[0]
    assert one["latest"] == 42 and one["trend"] == "new" and one["points"] == []


def test_shape_limit_zero_omits_points_but_keeps_trend() -> None:
    one = ss.shape(_rows(6), 0)[0]
    assert "points" not in one and one["trend"] == "improving"


def test_shape_groups_many_scores_in_order() -> None:
    a = _rows(3)
    b = [dict(r, id=8, kpi="ms.command", better="up") for r in _rows(2)]
    got = ss.shape(a + b, 0)
    assert [g["score"] for g in got] == ["tokens.loop", "ms.command"]


@pytest.mark.parametrize("reply", [{}, {"a": 1}, {"x": "y" * 85}, {"x": "y" * 984}, {"x": "\u00e9" * 50}])
def test_with_bytes_is_its_own_size(reply) -> None:
    out, n = with_bytes(reply)
    assert out["bytes"] == n == len(json.dumps(out, default=str).encode("utf-8"))
    assert "bytes" not in reply


# The handler, with the record layer swapped out.


class _Book:
    _cn = None


@pytest.fixture
def rec(monkeypatch):
    from agent_coord.server.api.mill import rpc
    from agent_coord.server.records import score as rec_score

    calls: list[tuple] = []

    def add(cn, project, desk, kpi, value, **kw):
        calls.append(("add", project, desk, kpi, value, kw))
        return [{"id": 7, "point_id": 1}]

    def points(cn, project, kpi="", limit=10):
        calls.append(("points", project, kpi, limit))
        return _rows(3) if kpi in ("tokens.loop", "") else []

    monkeypatch.setattr(rec_score, "point_add", add)
    monkeypatch.setattr(rec_score, "points", points)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    return rpc, calls


def test_handler_desk_value_write_is_refused(rec) -> None:
    """Card 1021: desk VALUE / define writes never reach records."""
    rpc, calls = rec
    with pytest.raises(CoordError, match=r"desks only read scores; use mill score unit tokens\.loop"):
        rpc._h_score(
            _Book(),
            {
                "name": "tokens.loop",
                "value": "880",
                "target": "500",
                "better": "down",
                "unit": "tokens",
                "note": "shorter prompt",
            },
            "unit",
            "d1",
        )
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "value": "fast"},
        {"name": "x", "value": "3", "target": "soon"},
        {"name": "x", "value": "3", "better": "sideways"},
        {"name": "x", "value": "3", "unit": "u" * 17},
        {"name": "x", "retire": True},
        {"name": "x", "target": "1"},
    ],
)
def test_handler_refuses_and_stores_nothing(rec, body) -> None:
    rpc, calls = rec
    with pytest.raises(CoordError, match=r"desks only read scores; use mill score unit"):
        rpc._h_score(_Book(), body, "unit", "d1")
    assert calls == []


def test_handler_reads_one_score(rec) -> None:
    rpc, calls = rec
    out = rpc._h_score(_Book(), {"name": "tokens.loop", "limit": 2}, "unit", "d1")
    assert calls == [("points", "unit", "tokens.loop", ss.TREND_POINTS)]
    assert len(out["points"]) == 2 and out["gap"] == -380


def test_handler_unknown_score_says_how_to_record(rec) -> None:
    rpc, _ = rec
    with pytest.raises(CoordError, match=r"no score nope on unit; use mill score unit nope"):
        rpc._h_score(_Book(), {"name": "nope"}, "unit", "d1")


def test_handler_lists_the_roster(rec) -> None:
    rpc, calls = rec
    out = rpc._h_score(_Book(), {}, "unit", "d1")
    assert calls == [("points", "unit", "", ss.TREND_POINTS)]
    assert out["roster"] == "unit" and out["scores"][0]["score"] == "tokens.loop"
    assert "points" not in out["scores"][0]


def test_cli_parses_read_write_and_list() -> None:
    from agent_coord.__main__ import _build_parser as build_parser

    p = build_parser()
    a = p.parse_args(["score", "the-mill", "tokens.loop", "880", "--better", "down", "--unit", "tokens"])
    assert (a.project, a.name, a.value, a.better, a.unit) == ("the-mill", "tokens.loop", "880", "down", "tokens")
    a = p.parse_args(["score", "the-mill", "tokens.loop", "--limit", "3"])
    assert (a.name, a.value, a.limit) == ("tokens.loop", "", 3)
    a = p.parse_args(["score", "the-mill"])
    assert (a.name, a.value) == ("", "")
    with pytest.raises(SystemExit):
        p.parse_args(["score", "the-mill", "x", "1", "--better", "sideways"])


def test_shape_labels_truncated_window() -> None:
    """Card 1020: a capped point window is labelled; a short history is not."""
    long = ss.shape(_rows(12), 10)[0]
    assert long.get("truncated") is True
    assert long.get("truncated_n") == 2
    assert len(long["points"]) == 10
    short = ss.shape(_rows(4), 10)[0]
    assert "truncated" not in short
    assert "truncated_n" not in short
    assert len(short["points"]) == 4


def test_shape_limit_zero_is_not_a_truncated_window() -> None:
    """limit 0 omits points for trend-only reads; not a truncation label."""
    one = ss.shape(_rows(6), 0)[0]
    assert "points" not in one
    assert "truncated" not in one
