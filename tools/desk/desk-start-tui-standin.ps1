# desk-start TUI stand-in (Windows). No grok. Used by desk-start.ps1 -StubTui.
# Checks console redirect state, enables VT, draws an alternate-screen frame,
# reads one key, restores the screen, exits with -ExitCode.
# Contract mirrored by desk_start_tui_standin.py for Linux CI.

[CmdletBinding()]
param(
  [int]$ExitCode = 0,
  [switch]$AutoExit
)

$ErrorActionPreference = "Stop"

function Test-ConsoleInteractive {
  # Match what a real TUI cares about: stdin/stdout are console, not pipes.
  $inRedir = $false
  $outRedir = $false
  try { $inRedir = [Console]::IsInputRedirected } catch { $inRedir = $true }
  try { $outRedir = [Console]::IsOutputRedirected } catch { $outRedir = $true }
  return (-not $inRedir -and -not $outRedir)
}

$interactive = Test-ConsoleInteractive
Write-Host ("desk-start-tui-standin: interactive={0} in_redir={1} out_redir={2}" -f `
  $interactive, [Console]::IsInputRedirected, [Console]::IsOutputRedirected)

if (-not $interactive) {
  Write-Host "desk-start-tui-standin: FAIL not a console (input or output redirected)"
  exit 2
}

# Enable VT processing when the host supports it (PS 5.1 / Windows 10+).
try {
  $method = [Console].GetMethod("set_OutputEncoding")
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$esc = [char]27
# Enter alternate screen, clear, home, draw a box, ask for a key.
$frame = @(
  ($esc + "[?1049h"),
  ($esc + "[2J"),
  ($esc + "[H"),
  ($esc + "[1;1Hdesk-start-tui-standin"),
  ($esc + "[2;1H---------------------"),
  ($esc + "[3;1Hconsole attached; press any key to exit " + $ExitCode),
  ($esc + "[4;1H(or wait if -AutoExit)")
) -join ""
[Console]::Write($frame)

if ($AutoExit) {
  Start-Sleep -Milliseconds 200
} else {
  $null = [Console]::ReadKey($true)
}

# Leave alternate screen.
[Console]::Write($esc + "[?1049l")
Write-Host "desk-start-tui-standin: exit $ExitCode"
exit $ExitCode
