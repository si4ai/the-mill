"""Card 1051: open-PR / release / escapes scores stay out of the shipped pack.

Dev-cycle scores (GitHub PRs, Validator Pass, consensus/GOs/tag/PyPI, escapes)
live under tools/dev_scores, not agent_coord. mill score name lists and
_cards_score_view must not wire them.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "agent_coord" / "server"
RPC = SERVER / "api" / "mill" / "rpc.py"

FORBIDDEN_MODULES = (
    "open_prs_score.py",
    "release_activity.py",
    "delivery_escapes.py",
)

# Score name tokens that belong only to our pack/ship / PR pipeline.
_DEV_SCORE_TOKENS = (
    "pr.open_n",
    "pr.red_n",
    "pr.open_age_ms",
    "pr.open_to_green_ci_ms",
    "pr.open_to_validator_pass_ms",
    "pr.open_to_merge_ms",
    "pr.ci_gate_wait_ms",
    "pr.validator_gate_wait_ms",
    "pr.merge_gate_wait_ms",
    "open-prs-",
    "release.release_n",
    "release.consensus_to_gos_ms",
    "release.gos_to_tag_ms",
    "release.tag_to_pypi_ms",
    "release.pypi_to_live_ms",
    "release.consensus_to_live_ms",
    "release-consensus-",
    "release-gos-to-tag",
    "release-tag-to-pypi",
    "release-pypi-to-live",
    "release-n",
)

_IMPORT_DEV = re.compile(
    r"from\s+agent_coord\.server\s+import\s+(open_prs_score|release_activity|delivery_escapes)\b"
    r"|import\s+agent_coord\.server\.(open_prs_score|release_activity|delivery_escapes)\b"
)


def test_shipped_server_has_no_dev_score_modules():
    missing_ok = []
    for name in FORBIDDEN_MODULES:
        path = SERVER / name
        assert not path.is_file(), f"shipped pack still has {path.relative_to(ROOT)}"
        missing_ok.append(name)
    assert missing_ok == list(FORBIDDEN_MODULES)


def test_rpc_score_paths_have_no_dev_score_wiring():
    text = RPC.read_text(encoding="utf-8")
    hits = _IMPORT_DEV.findall(text)
    assert not hits, f"rpc.py still imports dev score modules: {hits}"
    for tok in _DEV_SCORE_TOKENS:
        assert tok not in text, f"rpc.py still names dev score token {tok!r}"
    # Product cards guards must not attach escapes (Validator Fail / revert).
    assert '"escapes"' not in text and "'escapes'" not in text, (
        "rpc.py _cards_score_view still surfaces guards.escapes"
    )
