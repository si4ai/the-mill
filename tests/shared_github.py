"""Card 1336: the shared si4ai/.github checker scripts the-mill calls.

The-mill keeps no copy of tools/check_pr_text.py or tools/check_validator_pass.py.
Its workflows call si4ai/.github at SHARED_PIN, and its tests for those scripts
load them from si4ai/.github at that same sha. As in the shared workflows, its
tools/ folder sits at .si4ai-tools/ in this checkout, so check_pack.mill_root()
is this repo and the ordinary-word list is this tree's. The CI pytest jobs check
si4ai/.github out and move tools/ there. Locally:

    git clone https://github.com/si4ai/.github .si4ai-github
    git -C .si4ai-github checkout <SHARED_PIN>
    mv .si4ai-github/tools .si4ai-tools

Without it, the tests skip outside CI and fail in CI (fail closed).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Must equal every `uses: si4ai/.github/...@<sha>` pin and the CI checkout ref
# (tests/install/test_github_workflows.py checks this).
SHARED_PIN = "23c056780f193d140e042491ac81a59cafb71a14"


def shared_tools() -> Path:
    """The tools/ folder of si4ai/.github at SHARED_PIN."""
    tools = ROOT / ".si4ai-tools"
    if not (tools / "check_pr_text.py").is_file():
        if os.environ.get("CI"):
            raise RuntimeError("shared si4ai/.github tools missing at .si4ai-tools/ (failing closed in CI)")
        pytest.skip("shared si4ai/.github tools not checked out; see tests/shared_github.py", allow_module_level=True)
    return tools
