"""F-desk-start-exit-wait / card 950: desk-start window mode WaitForExit + stub child.

Without WaitForExit, grok shares the console with the calling PowerShell and
a clean grok exit hangs the terminal. Stub mode exercises the same
ProcessStartInfo path without grok, seat, credential, or model tokens.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
README = ROOT / "tools" / "desk" / "README.md"
ROW = ROOT / "docs" / "security" / "regression" / "F-desk-start-exit-wait.md"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _src() -> str:
    return PS1.read_text(encoding="utf-8")


def test_ps1_wait_for_exit_and_propagates_child_code():
    src = _src()
    assert "$proc.WaitForExit()" in src or "WaitForExit()" in src
    assert "return $childExit" in src or "return [int]$proc.ExitCode" in src
    # slice from process start to end of invoke-onedesk must wait then return exit.
    start = src.index("[System.Diagnostics.Process]::Start($psi)")
    end = src.index("# --- main ---", start)
    body = src[start:end]
    assert "WaitForExit" in body
    before_wait, after_wait = body.split("WaitForExit", 1)
    assert not re.search(r"^\s*return\s+0\b", before_wait, flags=re.M), (
        "must not return 0 before WaitForExit"
    )
    assert "ExitCode" in after_wait or "$childExit" in after_wait


def test_ps1_stub_switch_and_env_override():
    src = _src()
    assert "[switch]$Stub" in src
    assert "StubSleepSeconds" in src
    assert "StubExitCode" in src
    assert "MILL_DESK_START_STUB" in src
    assert "MILL_DESK_START_STUB_SLEEP" in src
    assert "MILL_DESK_START_STUB_EXIT" in src
    # Stub child is powershell -NoProfile on the same PSI path.
    assert "UseShellExecute = $false" in src
    assert "-NoProfile" in src
    assert "desk-start stub:" in src
    assert "Start-Sleep" in src
    # Stub skips credential, grok, session.json.
    assert "-not $stub" in src
    assert "stub mode (no grok)" in src
    assert "session.json" in src.lower() or "sessionPath" in src
    # session write gated
    assert re.search(r"if\s*\(\s*-not\s+\$stub\s*\)\s*\{[\s\S]*sessionPath", src)


def test_ps1_stub_passed_into_invoke_onedesk():
    src = _src()
    assert re.search(
        r"function Invoke-OneDesk\(\$desk, \$cfg, \[bool\]\$dry, \[bool\]\$stub",
        src,
    )
    assert re.search(
        r"Invoke-OneDesk \$d \$cfg \(\[bool\]\$DryRun\) \(\[bool\]\$Stub\)",
        src,
    )


def test_readme_documents_stub_and_wait():
    text = README.read_text(encoding="utf-8")
    assert "-Stub" in text or "Stub" in text
    assert "WaitForExit" in text or "waits for" in text.lower()
    assert "MILL_DESK_START_STUB" in text


def test_desk_start_exit_wait_row_and_matrix():
    assert ROW.is_file(), "docs/security/regression/F-desk-start-exit-wait.md missing"
    line = ROW.read_text(encoding="utf-8")
    assert "| F-desk-start-exit-wait" in line
    assert "WaitForExit" in line
    assert "Stub" in line or "stub" in line
    assert "test_desk_start_exit_hang_950" in line
    assert "950" in line
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "| F-desk-start-exit-wait" in matrix
