"""F-desk-start-exit-wait / card 950: call-operator launch + stub (+ stub-tui).

Process.Start(UseShellExecute=false)+WaitForExit keeps the parent attached to
the same console; a TUI (grok) then draws nothing. The call operator (&) yields
the console, waits, and propagates $LASTEXITCODE (one window). Stub / StubTui
exercise that path without grok.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
STANDIN_PS1 = ROOT / "tools" / "desk" / "desk-start-tui-standin.ps1"
STANDIN_PY = ROOT / "tools" / "desk" / "desk_start_tui_standin.py"
README = ROOT / "tools" / "desk" / "README.md"
ROW = ROOT / "docs" / "security" / "regression" / "F-desk-start-exit-wait.md"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _src() -> str:
    return PS1.read_text(encoding="utf-8")


def test_ps1_uses_call_operator_not_process_start_wait():
    src = _src()
    assert "& $grok.Source @argTail" in src
    assert "$LASTEXITCODE" in src
    assert "[System.Diagnostics.Process]::Start" not in src
    assert "$proc.WaitForExit()" not in src
    assert "UseShellExecute = $false" not in src
    assert "return $childExit" in src
    assert "call-operator" in src or "call operator" in src.lower()


def test_ps1_stub_and_stub_tui_on_call_operator_path():
    src = _src()
    assert "[switch]$Stub" in src
    assert "[switch]$StubTui" in src
    assert "StubSleepSeconds" in src
    assert "StubExitCode" in src
    assert "MILL_DESK_START_STUB" in src
    assert "MILL_DESK_START_STUB_TUI" in src
    assert "MILL_DESK_START_STUB_SLEEP" in src
    assert "MILL_DESK_START_STUB_EXIT" in src
    assert "desk-start-tui-standin.ps1" in src
    assert "desk-start stub:" in src
    assert "Start-Sleep" in src
    assert "-not $stub" in src
    assert "stub mode (no grok)" in src or "stub-tui mode" in src
    assert "sessionPath" in src
    assert "if ($stub)" in src


def test_ps1_stub_passed_into_invoke_onedesk():
    src = _src()
    assert re.search(
        r"function Invoke-OneDesk\(\$desk, \$cfg, \[bool\]\$dry, \[bool\]\$stub, \[bool\]\$stubTui",
        src,
    )
    assert re.search(
        r"Invoke-OneDesk \$d \$cfg \(\[bool\]\$DryRun\) \(\[bool\]\$Stub\) \(\[bool\]\$StubTui\)",
        src,
    )


def test_standin_files_exist_and_document_tty_check():
    assert STANDIN_PS1.is_file()
    assert STANDIN_PY.is_file()
    ps = STANDIN_PS1.read_text(encoding="utf-8")
    assert "IsInputRedirected" in ps
    assert "1049h" in ps
    assert "ReadKey" in ps or "AutoExit" in ps
    py = STANDIN_PY.read_text(encoding="utf-8")
    assert "isatty" in py
    assert "1049h" in py
    assert "--auto-exit" in py
    assert "--exit-code" in py


def test_python_standin_auto_exit_on_tty_or_fail_redirect():
    """With pipes (typical under pytest), stand-in must refuse (exit 2)."""
    proc = subprocess.run(
        [sys.executable, str(STANDIN_PY), "--exit-code", "7", "--auto-exit"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "FAIL" in proc.stdout or "FAIL" in proc.stderr
        assert "interactive=False" in proc.stdout
    else:
        assert proc.returncode == 7, proc.stdout + proc.stderr
        assert "interactive=True" in proc.stdout


def test_python_standin_helper_is_interactive_false_when_piped():
    spec = importlib.util.spec_from_file_location("desk_start_tui_standin", STANDIN_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    class _Pipe:
        def isatty(self):
            return False

    old_in, old_out = sys.stdin, sys.stdout
    try:
        sys.stdin, sys.stdout = _Pipe(), _Pipe()  # type: ignore[assignment]
        assert mod.is_interactive() is False
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def test_readme_documents_call_operator_stub_and_stub_tui():
    text = README.read_text(encoding="utf-8")
    assert "-Stub" in text
    assert "StubTui" in text or "-StubTui" in text
    assert "call operator" in text.lower() or "call-operator" in text
    assert "MILL_DESK_START_STUB" in text
    assert "Process.Start" in text or "ProcessStartInfo" in text


def test_desk_start_exit_wait_row_and_matrix():
    assert ROW.is_file()
    line = ROW.read_text(encoding="utf-8")
    assert "| F-desk-start-exit-wait" in line
    assert ("call operator" in line.lower()) or ("call-operator" in line) or ("& $" in line)
    assert "Stub" in line or "stub" in line
    assert "test_desk_start_exit_hang_950" in line
    assert "950" in line
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "| F-desk-start-exit-wait" in matrix
