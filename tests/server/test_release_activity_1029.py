"""Card 1029: release pipeline score from structured samples (no schema / activity.type)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_coord.server import release_activity as ra


def _t(hours: float = 0, minutes: float = 0) -> datetime:
    return datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        hours=hours, minutes=minutes
    )


def test_score_view_from_samples_medians_and_worst_per_stage():
    """consensus->GOs->tag->PyPI->live: median+worst; empty stages omitted."""
    samples = [
        ra.ReleaseSample(
            version="0.8.4",
            consensus_at=_t(hours=-20),
            gos_at=_t(hours=-18),
            tagged_at=_t(hours=-16),
            pypi_at=_t(hours=-14),
            live_at=_t(hours=-12),
        ),
        ra.ReleaseSample(
            version="0.8.5",
            consensus_at=_t(hours=-10),
            gos_at=_t(hours=-9),
            tagged_at=_t(hours=-8),
            pypi_at=_t(hours=-7),
            live_at=_t(hours=-5),
        ),
        ra.ReleaseSample(
            version="0.8.6",
            consensus_at=_t(hours=-4),
            gos_at=_t(hours=-3),
            tagged_at=None,
            pypi_at=None,
            live_at=None,
        ),
    ]
    view = ra.score_view_from_samples(samples)
    assert view["unit"] == "release"
    assert view["release_n"]["n"] == 3
    assert "consensus_to_gos_ms" in view
    assert view["consensus_to_gos_ms"]["n"] == 3
    assert view["consensus_to_gos_ms"]["worst"] >= view["consensus_to_gos_ms"]["median"]
    assert "gos_to_tag_ms" in view
    assert view["gos_to_tag_ms"]["n"] == 2
    assert "tag_to_pypi_ms" in view
    assert "pypi_to_live_ms" in view
    assert "consensus_to_live_ms" in view
    assert view["consensus_to_live_ms"]["n"] == 2
    blob = str(view)
    assert ("gh" + "p_") not in blob
    assert "localhost" not in blob
    assert "@" not in blob


def test_score_view_omits_empty_and_aliases():
    view = ra.score_view_from_samples([])
    assert view.get("unit") == "release"
    assert "consensus_to_gos_ms" not in view
    assert "release.consensus_to_gos_ms" in ra.SCORE_NAMES
    assert "release-consensus-to-gos" in ra.SCORE_NAMES
    named = ra.score_view_for_name_from_samples([], "release.consensus_to_gos_ms")
    assert named.get("missing") is True


def test_samples_from_payload_never_keeps_token_fields():
    """Parser maps release JSON fields; drops authorization-like keys."""
    payload = [
        {
            "version": "0.8.3",
            "consensus_at": "2026-10-31T01:00:00Z",
            "gos_at": "2026-10-31T02:00:00Z",
            "tagged_at": "2026-10-31T03:00:00Z",
            "pypi_at": "2026-10-31T04:00:00Z",
            "live_at": "2026-10-31T05:00:00Z",
            "token": ("gh" + "p_" + "SHOULD_NOT_APPEAR"),
            "host": "localhost",
            "author_email": "x@example.com",
        }
    ]
    samples = ra.samples_from_payload(payload)
    assert len(samples) == 1
    assert samples[0].version == "0.8.3"
    assert samples[0].gos_at is not None
    needle = "gh" + "p_"
    assert needle not in repr(samples[0])
    assert "SHOULD_NOT" not in repr(samples[0])
    assert "localhost" not in repr(samples[0])
    assert "@" not in repr(samples[0])


def test_named_score_alias_returns_summary():
    samples = [
        ra.ReleaseSample(
            version="0.8.4",
            consensus_at=_t(hours=-5),
            gos_at=_t(hours=-4),
            tagged_at=_t(hours=-3),
            pypi_at=_t(hours=-2),
            live_at=_t(hours=-1),
        )
    ]
    named = ra.score_view_for_name_from_samples(samples, "release-consensus-to-live")
    assert named.get("score") == "release-consensus-to-live"
    assert named.get("n") == 1
    assert "median" in named
