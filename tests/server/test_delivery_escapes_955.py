"""Card 955: escapes guard (Validator Fails + post-release reverts) from samples; no DDL."""
from __future__ import annotations

from agent_coord.server import delivery_escapes as de


def test_escapes_summary_from_samples_median_rate():
    samples = [
        de.EscapeSample(kind="validator_fail", card_id=1),
        de.EscapeSample(kind="validator_fail", card_id=2),
        de.EscapeSample(kind="revert", card_id=3),
    ]
    got = de.escapes_view(samples, shipped=10)
    assert got["n"] == 3
    assert got["validator_fail_n"] == 2
    assert got["revert_n"] == 1
    assert got["per_shipped"] == 0.3
    assert got["unit"] == "count"
    blob = str(got)
    assert ("gh" + "p_") not in blob
    assert "localhost" not in blob
    assert "@" not in blob


def test_escapes_omitted_when_empty():
    assert de.escapes_view([], shipped=5) is None
    assert de.escapes_view(None, shipped=0) is None


def test_samples_from_payload_drops_secrets():
    rows = [
        {
            "kind": "validator_fail",
            "card_id": 9,
            "token": ("gh" + "p_" + "NOPE"),
            "host": "localhost",
            "email": "x@example.com",
        },
        {"kind": "revert", "card_id": 10},
        {"kind": "other", "card_id": 11},  # dropped
    ]
    samples = de.samples_from_payload(rows)
    assert len(samples) == 2
    assert samples[0].kind == "validator_fail"
    assert "NOPE" not in repr(samples[0])
    assert "localhost" not in repr(samples[0])
    assert "@" not in repr(samples[0])


def test_cards_score_view_surfaces_live_escapes(monkeypatch):
    """_cards_score_view fills guards.escapes from live fetch when samples exist."""
    from agent_coord.server.api.mill import rpc

    class _Book:
        _cn = object()

    samples = [
        de.EscapeSample(kind="validator_fail", card_id=1),
        de.EscapeSample(kind="revert", card_id=2),
    ]
    de.set_live_fetch(lambda: samples)
    try:
        monkeypatch.setattr(
            "agent_coord.server.records.score.cards_day_evidence",
            lambda cn, project: {"shipped": 4, "lead_n": 0, "lead_sum": 0, "eta_n": 0, "eta_sum": 0, "actual_sum": 0, "doing_sum": 0, "claimed": 1, "started": 1, "passed": 1},
        )
        monkeypatch.setattr(
            "agent_coord.server.records.score.system_commands_today",
            lambda cn, desk: None,
        )
        out = rpc._cards_score_view(_Book(), {"score": "cards"}, "unit", "v955")
        assert out["cards_per_day"] == 4
        assert out["guards"]["escapes"]["n"] == 2
        assert out["guards"]["escapes"]["per_shipped"] == 0.5
    finally:
        de.set_live_fetch(None)
