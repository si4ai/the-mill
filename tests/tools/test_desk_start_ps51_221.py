"""f221: desk-start.ps1 must run on windows powershell 5.1 (netfx).

real dry-run on the workstation (ps 5.1.26100, grok 1.0.70, no pwsh) found:
1) `$rc = Invoke-OneDesk ...` swallowed dry-run json (pipeline + return 0)
   so nothing printed and exit logic saw an array.
2) `ProcessStartInfo.ArgumentList` (and `.Environment`) do not exist on
   netfx; live launch must set `.Arguments` with commandlinetoargvw
   quoting and clear PYTHONPATH via `EnvironmentVariables`.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "tools" / "desk" / "desk-start.ps1"
EXAMPLE = ROOT / "tools" / "desk" / "desks.example.json"
MATRIX = ROOT / "docs" / "security" / "REGRESSION-MATRIX.md"


def _src() -> str:
    return PS1.read_text(encoding="utf-8")


def escape_win_arg(arg: str) -> str:
    """commandlinetoargvw quoting used by `Format-WinArg` in the ps1.

    wrap when the value is empty or holds whitespace/quotes; double
    backslashes that precede a quote (or the closing quote); escape
    embedded quotes as \\".
    """
    if arg == "":
        return '""'
    if not re.search(r'[\s"]', arg):
        return arg
    out: list[str] = ['"']
    num_bs = 0
    for ch in arg:
        if ch == "\\":
            num_bs += 1
            continue
        if ch == '"':
            out.append("\\" * (num_bs * 2 + 1))
            out.append('"')
            num_bs = 0
            continue
        if num_bs:
            out.append("\\" * num_bs)
            num_bs = 0
        out.append(ch)
    out.append("\\" * (num_bs * 2))
    out.append('"')
    return "".join(out)


def format_win_argv(argv: list[str]) -> str:
    return " ".join(escape_win_arg(a) for a in argv)


def test_ps1_has_no_argumentlist_or_core_environment():
    src = _src()
    assert "$psi.ArgumentList" not in src and "ArgumentList.Add" not in src, (
        "ProcessStartInfo.ArgumentList is .NET Core / PS7 only; use .Arguments"
    )
    assert not re.search(r"\$psi\.Environment\b(?!Variables)", src), (
        "use $psi.EnvironmentVariables on .NET Framework / PS 5.1"
    )
    assert "$psi.Arguments" in src
    assert "EnvironmentVariables" in src


def test_ps1_dry_run_does_not_emit_json_on_success_pipeline():
    """bare `$plan | ConvertTo-Json` before `return 0` pollutes `$rc = Invoke-OneDesk`."""
    src = _src()
    dry = re.search(
        r"if\s*\(\s*\$dry\s*\)\s*\{(.*?)\n\s*\}",
        src,
        flags=re.S,
    )
    assert dry, "expected if ($dry) { ... } branch"
    body = dry.group(1)
    assert "ConvertTo-Json" in body
    assert (
        "Write-Host" in body
        or "[Console]::Out" in body
        or "Console.Out" in body
    ), "dry-run JSON must go to Write-Host or [Console]::Out, not the pipeline"
    assert not re.search(
        r"^\s*\$plan\s*\|\s*ConvertTo-Json",
        body,
        flags=re.M,
    ), "uncaptured $plan | ConvertTo-Json pollutes the caller's $rc"


def test_ps1_invoke_onedesk_returns_only_int_shape():
    src = _src()
    assert re.search(r"\$rc\s*=\s*\[int\]\(Invoke-OneDesk", src) or re.search(
        r"\$rc\s*=\s*Invoke-OneDesk", src
    )
    assert "exit $code" in src
    m = re.search(
        r"function Invoke-OneDesk.*?^# --- main ---",
        src,
        flags=re.S | re.M,
    )
    assert m, "Invoke-OneDesk function not found"
    returns = re.findall(r"^\s*return\s+(.+)$", m.group(0), flags=re.M)
    assert returns, "expected return statements in Invoke-OneDesk"
    for r in returns:
        token = r.strip().rstrip(";").split()[0]
        assert token in ("0", "1"), f"Invoke-OneDesk must return only 0 or 1, got: {r!r}"


def test_ps1_format_win_arg_present_and_documents_rules():
    src = _src()
    assert "function Format-WinArg" in src
    assert "function Join-WinArgv" in src
    assert "commandlinetoargvw" in src.lower()
    assert "$psi.Arguments = Join-WinArgv" in src


def test_escape_win_arg_command_line_to_argv_w_rules():
    """commandlinetoargvw: quote when empty/whitespace/quote; double bs before quotes."""
    bs = chr(92)
    dq = chr(34)
    assert escape_win_arg("plain") == "plain"
    assert escape_win_arg("has space") == dq + "has space" + dq
    assert escape_win_arg("has " + dq + "quotes" + dq) == (
        dq + "has " + bs + dq + "quotes" + bs + dq + dq
    )
    assert escape_win_arg("") == dq + dq
    assert escape_win_arg("a\tb") == dq + "a\tb" + dq
    assert escape_win_arg("line1\nline2") == dq + "line1\nline2" + dq
    one_bs = "ends with " + bs
    assert escape_win_arg(one_bs) == dq + "ends with " + bs + bs + dq
    embedded = "foo" + bs + dq + "bar"
    assert escape_win_arg(embedded) == dq + "foo" + bs + bs + bs + dq + "bar" + dq
    for c in ("has space", "", "a\tb", one_bs):
        assert escape_win_arg(c) == subprocess.list2cmdline([c]), repr(c)
    handoff = "desk x\ndo " + dq + "open" + dq + " work"
    joined = format_win_argv(["grok", "--cwd", "C:/desks/example/work", handoff])
    assert joined.startswith("grok --cwd C:/desks/example/work ")
    assert joined.endswith(escape_win_arg(handoff))


def test_f221_row_in_matrix():
    text = MATRIX.read_text(encoding="utf-8")
    assert "| F221 (" in text
    assert "desk-start-ps51" in text or "PS 5.1" in text
    assert "test_desk_start_ps51_221" in text
    assert "Format-WinArg" in text or "CommandLineToArgvW" in text


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not on PATH (CI is ubuntu)")
def test_dry_run_execution_emits_json_and_exit_zero(tmp_path):
    """when pwsh is present, dry-run must print one json object and exit 0."""
    cfg = tmp_path / "desks.json"
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["office"]["launch_mode"] = "window"
    for d in data["desks"]:
        d["work_dir"] = str(tmp_path / "work")
        d["export_dir"] = str(tmp_path / "exports")
        d["agent_file"] = str(tmp_path / "agent.md")
        d["add_dirs"] = []
    cfg.write_text(json.dumps(data), encoding="utf-8")
    proc = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(PS1),
            "-Config",
            str(cfg),
            "-Desk",
            "example-desk",
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    blob = proc.stdout.strip() or proc.stderr.strip()
    m = re.search(r"\{.*\}\s*$", blob, flags=re.S)
    assert m, f"expected JSON plan in output, got: {blob[:500]!r}"
    plan = json.loads(m.group(0))
    assert plan.get("dry_run") is True
    assert isinstance(plan.get("would_launch"), bool)
