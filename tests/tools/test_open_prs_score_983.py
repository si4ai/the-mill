"""Card 983: open-PRs queue score from gh samples + optional Pass stamps (no schema)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tools.dev_scores import open_prs_score as ops


def _t(hours: float = 0, minutes: float = 0) -> datetime:
    return datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        hours=hours, minutes=minutes
    )


def test_score_view_from_samples_medians_and_counts():
    """Injected PR samples: open age, time to green CI / merge, gate waits; no tokens/names in view keys beyond kpi."""
    samples = [
        ops.PrSample(
            number=101,
            opened_at=_t(hours=-10),
            first_green_ci_at=_t(hours=-8),
            validator_pass_at=_t(hours=-6),
            merged_at=_t(hours=-4),
            closed_at=None,
            red=False,
            open=False,
        ),
        ops.PrSample(
            number=102,
            opened_at=_t(hours=-5),
            first_green_ci_at=_t(hours=-4),
            validator_pass_at=_t(hours=-3),
            merged_at=None,
            closed_at=None,
            red=False,
            open=True,
        ),
        ops.PrSample(
            number=103,
            opened_at=_t(hours=-2),
            first_green_ci_at=None,
            validator_pass_at=None,
            merged_at=None,
            closed_at=None,
            red=True,
            open=True,
        ),
    ]
    view = ops.score_view_from_samples(samples, now=_t())
    assert view["open_n"]["n"] == 2
    assert view["red_n"]["n"] == 1
    assert "open_age_ms" in view
    assert view["open_age_ms"]["n"] == 2
    assert view["open_age_ms"]["worst"] >= view["open_age_ms"]["median"]
    assert "open_to_green_ci_ms" in view
    assert view["open_to_green_ci_ms"]["n"] == 2  # 101 and 102
    assert view["open_to_green_ci_ms"]["median"] >= 3_500_000  # ~1h for 102
    assert "open_to_validator_pass_ms" in view
    assert "open_to_merge_ms" in view
    assert view["open_to_merge_ms"]["n"] == 1
    assert "ci_gate_wait_ms" in view
    assert "validator_gate_wait_ms" in view
    assert "merge_gate_wait_ms" in view
    # no host/token leakage in serialized view
    blob = str(view)
    assert ("gh" + "p_") not in blob
    assert ("github" + "_pat_") not in blob
    assert "localhost" not in blob
    assert "@" not in blob


def test_score_view_omits_empty_and_aliases():
    view = ops.score_view_from_samples([], now=_t())
    assert view.get("unit") == "pr"
    assert "open_n" not in view or view["open_n"]["n"] == 0
    # empty samples: ages/times omitted (1019)
    assert "open_to_green_ci_ms" not in view
    assert "open-prs-open-to-green" in ops.SCORE_NAMES
    assert "pr.open_to_green_ci_ms" in ops.SCORE_NAMES
    named = ops.score_view_for_name_from_samples(
        [], "pr.open_to_green_ci_ms", now=_t()
    )
    assert named.get("missing") is True


def test_samples_from_gh_payload_never_keeps_token_fields():
    """Parser maps gh JSON fields; drops authorization-like keys."""
    payload = [
        {
            "number": 7,
            "created_at": "2026-11-01T02:00:00Z",
            "merged_at": None,
            "closed_at": None,
            "token": ("gh" + "p_" + "SHOULD_NOT_APPEAR"),
            "head": {"sha": "abc", "repo": {"private": True}},
            "user": {"login": "builder"},
        }
    ]
    checks = {
        7: {
            "first_green_at": "2026-11-01T03:00:00Z",
            "red": False,
            "validator_pass_at": "2026-11-01T04:00:00Z",
        }
    }
    samples = ops.samples_from_gh(payload, checks=checks)
    assert len(samples) == 1
    assert samples[0].number == 7
    assert samples[0].first_green_ci_at is not None
    assert samples[0].validator_pass_at is not None
    # dataclass / repr must not include token
    needle = "gh" + "p_"
    assert needle not in repr(samples[0])
    assert "SHOULD_NOT" not in repr(samples[0])


def test_pass_stamps_overlay_from_961_hook():
    """961 supplies Pass stamps keyed by head sha / pr number; overlay fills validator_pass_at."""
    samples = [
        ops.PrSample(
            number=9,
            opened_at=_t(hours=-3),
            first_green_ci_at=_t(hours=-2),
            validator_pass_at=None,
            merged_at=None,
            closed_at=None,
            red=False,
            open=True,
            head_sha="deadbeef",
        )
    ]
    stamps = [ops.PassStamp(pr_number=9, head_sha="deadbeef", passed_at=_t(hours=-1))]
    out = ops.apply_pass_stamps(samples, stamps)
    assert out[0].validator_pass_at == _t(hours=-1)
