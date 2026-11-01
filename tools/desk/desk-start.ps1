# desk-start: fresh Grok Build session from an office config file.
# No desk names, paths, models, or office names are hard-coded here.
# Real config lives outside the repo. See README.md and desks.example.json.
#
# Source: workstation `grok --help` (grok 1.0.70 stable).
# Usage: grok [OPTIONS] [PROMPT] [COMMAND] - [PROMPT] = initial interactive prompt.
# Fresh: --cwd, optional --agent/--add-dir/-m/--reasoning-effort, -s <new uuid>, PROMPT.
# Never: -r/--resume, -c/--continue, --fork-session, -p.
# bypassPermissions only when config defaults.allow_bypass_permissions is true (warns).
# office.launch_mode: dashboard (default) or window.
#   dashboard - attach desk sessions to the shared Grok leader for one Agent
#     Dashboard (grok dashboard). Exact attach recipe: UNVERIFIED until the
#     owner probe (runbook step 0) passes. Dry-run prints window_argv fallback.
#   window - one interactive grok process per desk (fallback).
# Writes only under each desk's work_dir parent (session.json) and export_dir.
# Never deletes sessions.
# Window mode waits for the child (WaitForExit) and propagates its exit code so
# the shared console is released cleanly (card 950).
# -Stub (or env MILL_DESK_START_STUB=1) launches a trivial child on the same
# ProcessStartInfo path instead of grok: prints one line, sleeps
# -StubSleepSeconds (env MILL_DESK_START_STUB_SLEEP, default 3), exits with
# -StubExitCode (env MILL_DESK_START_STUB_EXIT, default 0). No grok, no seat,
# no credential, no session.json write. For debugging open/close only.
# defaults.context_restart_tokens (default 190000): printed in the plan; the
# desk asks for a fresh desk-start near that count (never resume, never compact).
# lessons_byte_cap is enforced by desk_start_plan.select_lessons; this script
# does not assemble lessons (template or HANDOFF.md + handoff_char_cap only).

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Config,

  [Parameter(Mandatory = $true)]
  [string[]]$Desk,

  [switch]$DryRun,

  # Stub / dry child on the window-mode ProcessStartInfo path (card 950).
  # No grok, no Credential Manager, no session.json. Env MILL_DESK_START_STUB=1
  # also enables; MILL_DESK_START_STUB_SLEEP / MILL_DESK_START_STUB_EXIT override.
  [switch]$Stub,

  [int]$StubSleepSeconds = 3,

  [int]$StubExitCode = 0
)

$ErrorActionPreference = "Stop"

# Env overrides for stub (switch still wins when passed).
if (-not $Stub -and $env:MILL_DESK_START_STUB -and $env:MILL_DESK_START_STUB -notin @("0", "false", "False", "")) {
  $Stub = $true
}
if ($env:MILL_DESK_START_STUB_SLEEP -and $env:MILL_DESK_START_STUB_SLEEP -match '^[0-9]+$') {
  $StubSleepSeconds = [int]$env:MILL_DESK_START_STUB_SLEEP
}
if ($env:MILL_DESK_START_STUB_EXIT -and $env:MILL_DESK_START_STUB_EXIT -match '^-?[0-9]+$') {
  $StubExitCode = [int]$env:MILL_DESK_START_STUB_EXIT
}
if ($StubSleepSeconds -lt 0) { throw "desk-start: -StubSleepSeconds must be >= 0" }
if ($StubExitCode -lt 0 -or $StubExitCode -gt 255) {
  throw "desk-start: -StubExitCode must be 0..255"
}

function New-SessionUuid { return [guid]::NewGuid().ToString() }


function Format-WinArg([string]$Arg) {
  # commandlinetoargvw quoting: wrap when empty or the value holds whitespace
  # or a quote; double each run of backslashes that sits before a quote (or
  # the closing quote); escape an embedded quote as backslash-quote.
  if ($null -eq $Arg) { $Arg = "" }
  if ($Arg -eq "") { return '""' }
  if ($Arg -notmatch '[\s"]') { return $Arg }
  $out = '"'
  $numBs = 0
  foreach ($ch in $Arg.ToCharArray()) {
    if ($ch -eq [char]0x5C) {
      $numBs++
      continue
    }
    if ($ch -eq [char]0x22) {
      $out += ([string][char]0x5C) * ($numBs * 2 + 1)
      $out += [char]0x22
      $numBs = 0
      continue
    }
    if ($numBs -gt 0) {
      $out += ([string][char]0x5C) * $numBs
      $numBs = 0
    }
    $out += $ch
  }
  if ($numBs -gt 0) {
    $out += ([string][char]0x5C) * ($numBs * 2)
  }
  $out += [char]0x22
  return $out
}

function Join-WinArgv([string[]]$Argv) {
  return (($Argv | ForEach-Object { Format-WinArg ([string]$_) }) -join " ")
}


function Read-DeskConfig([string]$path) {
  if (-not (Test-Path -LiteralPath $path)) {
    throw "desk-start: config file not found: $path"
  }
  try {
    $raw = Get-Content -LiteralPath $path -Raw -Encoding utf8
    return $raw | ConvertFrom-Json
  } catch {
    throw "desk-start: config is not valid JSON: $_"
  }
}

function Assert-Config($cfg) {
  if (-not $cfg.office) { throw "desk-start: missing office object" }
  if (-not $cfg.office.mill_office) { throw "desk-start: office.mill_office is required" }
  if (-not $cfg.office.mill_connect_template) { throw "desk-start: office.mill_connect_template is required" }
  if (-not $cfg.desks -or $cfg.desks.Count -lt 1) { throw "desk-start: desks must be a non-empty array" }
  $names = @{}
  foreach ($d in $cfg.desks) {
    if (-not $d.name) { throw "desk-start: a desk entry is missing name" }
    if ($names.ContainsKey([string]$d.name)) { throw "desk-start: duplicate desk name '$($d.name)'" }
    $names[[string]$d.name] = $true
    if (-not $d.work_dir) { throw "desk-start: desk '$($d.name)': work_dir is required" }
    if (-not $d.export_dir) { throw "desk-start: desk '$($d.name)': export_dir is required" }
    if (-not $d.credential_target) { throw "desk-start: desk '$($d.name)': credential_target is required" }
  }
  $lm = 'dashboard'
  if ($cfg.office.launch_mode) { $lm = [string]$cfg.office.launch_mode }
  $lm = $lm.ToLowerInvariant()
  if (@('dashboard', 'window') -notcontains $lm) {
    throw "desk-start: office.launch_mode must be 'dashboard' or 'window'"
  }
}

function Resolve-Desks($cfg, [string[]]$want) {
  if (-not $want -or $want.Count -lt 1) { throw "desk-start: pass -Desk <name> at least once (or -Desk all)" }
  $all = $want | ForEach-Object { $_.ToLowerInvariant() }
  if ($all -contains "all") {
    if ($want.Count -gt 1) { throw "desk-start: -Desk all cannot be combined with other names" }
    return @($cfg.desks)
  }
  $by = @{}
  foreach ($d in $cfg.desks) { $by[[string]$d.name] = $d }
  $out = @()
  foreach ($n in $want) {
    if (-not $by.ContainsKey($n)) {
      $known = ($by.Keys | Sort-Object) -join ", "
      throw "desk-start: unknown desk '$n'; known: $known"
    }
    $out += $by[$n]
  }
  return $out
}

function Get-Default($cfg, [string]$key, $fallback) {
  if ($cfg.defaults -and ($null -ne $cfg.defaults.$key) -and ($cfg.defaults.$key -ne "")) {
    return $cfg.defaults.$key
  }
  return $fallback
}

function Format-Template([string]$template, $map) {
  $s = $template
  foreach ($k in $map.Keys) {
    $s = $s.Replace("{$k}", [string]$map[$k])
  }
  return $s
}

function Test-CredPresent([string]$target) {
  $raw = & cmdkey.exe /list 2>$null | Out-String
  if (-not $raw) { return $false }
  return ($raw -match [regex]::Escape($target))
}

function Resolve-PermissionMode($desk, $cfg) {
  $mode = [string](Get-Default $cfg "permission_mode" "default")
  if ($desk.permission_mode) { $mode = [string]$desk.permission_mode }
  $allowBypass = $false
  if ($cfg.defaults -and $cfg.defaults.allow_bypass_permissions -eq $true) { $allowBypass = $true }
  $safe = @("default", "acceptEdits", "auto", "dontAsk", "plan")
  if ($mode -eq "bypassPermissions") {
    if (-not $allowBypass) {
      throw "desk-start: permission_mode bypassPermissions refused (set defaults.allow_bypass_permissions true to allow; not recommended)"
    }
    Write-Warning "desk-start: allow_bypass_permissions is set; launching with bypassPermissions"
    return $mode
  }
  if ($safe -notcontains $mode) {
    throw "desk-start: permission_mode '$mode' is not allowed"
  }
  return $mode
}

function Build-Argv($desk, $cfg, [string]$handoff, [string]$sessionId, [string]$mode) {
  $work = [string]$desk.work_dir
  $list = New-Object System.Collections.Generic.List[string]
  [void]$list.Add("grok")
  [void]$list.Add("--cwd"); [void]$list.Add($work)
  if ($desk.agent_file) { [void]$list.Add("--agent"); [void]$list.Add([string]$desk.agent_file) }
  if ($desk.add_dirs) {
    foreach ($ad in @($desk.add_dirs)) {
      if ($ad) { [void]$list.Add("--add-dir"); [void]$list.Add([string]$ad) }
    }
  }
  if ($desk.model) { [void]$list.Add("-m"); [void]$list.Add([string]$desk.model) }
  if ($desk.reasoning_effort) { [void]$list.Add("--reasoning-effort"); [void]$list.Add([string]$desk.reasoning_effort) }
  if ($mode -and $mode -ne "default") {
    [void]$list.Add("--permission-mode"); [void]$list.Add($mode)
  }
  [void]$list.Add("-s"); [void]$list.Add($sessionId)
  [void]$list.Add($handoff)
  $forbidden = @("-r", "--resume", "-c", "--continue", "-p", "--single", "--fork-session")
  foreach ($f in $forbidden) {
    if ($list -contains $f) { throw "desk-start: forbidden flag $f in argv" }
  }
  return ,@($list.ToArray())
}

function Get-FirstMessage($desk, $cfg) {
  # lean foreground sit: connect-wait blocking; restart near context_restart_tokens.
  $defaultTpl = "desk {desk} on office {mill_office}. learn-label {lessons_label}. load only the mill-desk skill (not mill-build-assist). run ``mill --office {mill_office} todo --mine`` and do open work; do not read the mail backlog or scan the board. then sit: ``mill --office {mill_office} connect-wait {desk}`` in the FOREGROUND (never background, never &, never a separate mill connect). on a hint: read that letter first; work letter -> do it, reply, sit again; status note -> mark, sit again; stop letter -> stay down; dropped socket -> sit again. never two sits. human chat wins over mail. after crash/resume, read inbox before sitting. near {context_restart_tokens} tokens: write learn-{desk}, open work, and a handoff, then ask for a fresh desk-start (never resume, never compact)."
  $tpl = [string](Get-Default $cfg "first_message_template" $defaultTpl)
  if ($desk.first_message_template) { $tpl = [string]$desk.first_message_template }
  $restartTok = 190000
  $restartDef = Get-Default $cfg "context_restart_tokens" 190000
  if ($null -ne $restartDef -and "$restartDef" -ne "") { $restartTok = [int]$restartDef }
  if ($null -ne $desk.context_restart_tokens -and "$($desk.context_restart_tokens)" -ne "") {
    $restartTok = [int]$desk.context_restart_tokens
  }
  $map = @{
    desk                    = [string]$desk.name
    lessons_label           = [string]$(if ($desk.lessons_label) { $desk.lessons_label } else { "" })
    mill_office             = [string]$cfg.office.mill_office
    roster                  = [string]$(if ($cfg.office.roster) { $cfg.office.roster } else { "" })
    context_restart_tokens  = [string]$restartTok
  }
  $text = (Format-Template $tpl $map).Trim()
  # Prefer HANDOFF.md beside work_dir when present (bot-written).
  $handoffFile = Join-Path (Split-Path -Parent ([string]$desk.work_dir)) "HANDOFF.md"
  if (Test-Path -LiteralPath $handoffFile) {
    $fromFile = (Get-Content -LiteralPath $handoffFile -Raw -Encoding utf8).Trim()
    if ($fromFile) { $text = $fromFile }
  }
  $cap = 1500
  $capDef = Get-Default $cfg "handoff_char_cap" 1500
  if ($capDef) { $cap = [int]$capDef }
  if ($text.Length -gt $cap) {
    $text = $text.Substring(0, [Math]::Max(0, $cap - 20)).TrimEnd() + "`nmore: todo --mine"
  }
  return $text
}

function Invoke-OneDesk($desk, $cfg, [bool]$dry, [bool]$stub, [int]$stubSleep, [int]$stubExit) {
  $name = [string]$desk.name
  $target = [string]$desk.credential_target
  $work = [string]$desk.work_dir
  $exportDir = [string]$desk.export_dir
  $deskRoot = Split-Path -Parent $work
  $sessionPath = Join-Path $deskRoot "session.json"

  if (-not $dry -and -not $stub) {
    if (-not (Test-CredPresent $target)) {
      Write-Host "desk-start: credential (Credential Manager target $target) missing"
      return 1
    }
  }

  $mode = Resolve-PermissionMode $desk $cfg
  $sessionId = New-SessionUuid
  $priorId = ""
  if (Test-Path -LiteralPath $sessionPath) {
    try {
      $prev = Get-Content -LiteralPath $sessionPath -Raw -Encoding utf8 | ConvertFrom-Json
      if ($prev.session_id) { $priorId = [string]$prev.session_id }
    } catch { }
  }

  $handoff = Get-FirstMessage $desk $cfg
  $argv = Build-Argv $desk $cfg $handoff $sessionId $mode

  $exportArgv = @()
  $exportPath = ""
  $doExport = $true
  if ($null -ne $cfg.office.export_before_restart) { $doExport = [bool]$cfg.office.export_before_restart }
  if ($priorId -and $doExport) {
    if (-not (Test-Path -LiteralPath $exportDir)) {
      if (-not $dry) { New-Item -ItemType Directory -Path $exportDir -Force | Out-Null }
    }
    $exportPath = Join-Path $exportDir "$priorId.md"
    $exportArgv = @("grok", "export", $priorId, $exportPath)
  }

  $connect = Format-Template ([string]$cfg.office.mill_connect_template) @{
    mill_office = [string]$cfg.office.mill_office
    roster      = [string]$(if ($cfg.office.roster) { $cfg.office.roster } else { "" })
    desk        = $name
  }

  $plan = [ordered]@{
    desk             = $name
    dry_run          = $dry
    help_source      = "workstation grok --help (grok 1.0.70 stable)"
    mill_connect     = $connect
    credential       = @{ where = "Credential Manager"; target = $target }
    work_dir         = $work
    export_dir       = $exportDir
    writes_allowed   = @($work, $exportDir, $deskRoot)
    permission_mode  = $mode
    session_id       = $sessionId
    prior_session_id = $priorId
    argv             = @($argv)
    export_argv      = $exportArgv
    export_path      = $exportPath
    handoff          = $handoff
    handoff_chars    = $handoff.Length
    context_restart_tokens = $(
      if ($null -ne $desk.context_restart_tokens -and "$($desk.context_restart_tokens)" -ne "") {
        [int]$desk.context_restart_tokens
      } elseif ($cfg.defaults -and $null -ne $cfg.defaults.context_restart_tokens -and "$($cfg.defaults.context_restart_tokens)" -ne "") {
        [int]$cfg.defaults.context_restart_tokens
      } else { 190000 }
    )
    launch           = "positional-prompt"
    launch_mode      = $(if ($cfg.office.launch_mode) { [string]$cfg.office.launch_mode } else { 'dashboard' })
    leader_socket    = $(if ($cfg.office.leader_socket) { [string]$cfg.office.leader_socket } else { '' })
    window_argv      = @($argv)
    outcome          = "ok"
    would_launch     = $true
    launched         = $false
    session_record   = $sessionPath
    stub             = [bool]$stub
    stub_sleep_seconds = [int]$stubSleep
    stub_exit_code   = [int]$stubExit
  }
  $launchMode = ([string]$plan.launch_mode).ToLowerInvariant()
  if (-not $launchMode) { $launchMode = 'dashboard' }
  if ($launchMode -eq 'dashboard') {
    $plan.attach_status = 'UNVERIFIED'
    $plan.attach_note = 'dashboard mode: attach to shared Grok leader for grok dashboard. Exact attach argv UNVERIFIED until owner probe (runbook step 0). window_argv is the fallback.'
    $plan.argv = @()
  } else {
    $plan.attach_status = 'verified-window'
    $plan.attach_note = 'window mode: one interactive grok process per desk'
  }

  if ($dry) {
    # write json off the success pipeline so `$rc = Invoke-OneDesk` stays an int.
    [Console]::Out.WriteLine(($plan | ConvertTo-Json -Depth 8))
    return 0
  }

  if ($launchMode -eq 'dashboard' -and -not $stub) {
    Write-Host "desk-start: launch_mode=dashboard attach recipe is UNVERIFIED; refuse live launch until runbook step 0 probe passes. Use -DryRun, -Stub, or set office.launch_mode to window."
    return 1
  }

  if (-not $stub) {
    $grok = Get-Command grok -ErrorAction SilentlyContinue
    if (-not $grok) {
      Write-Host "desk-start: grok not on PATH"
      return 1
    }
  }

  if (-not $stub -and $exportArgv.Count -gt 0) {
    try {
      & $grok.Source export $priorId $exportPath
    } catch {
      Write-Host "desk-start: export of prior session failed (continuing; session kept): $_"
    }
  }

  if (-not (Test-Path -LiteralPath $work)) {
    Write-Host "desk-start: work_dir does not exist: $work"
    return 1
  }

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.UseShellExecute = $false
  $psi.WorkingDirectory = $work
  # netfx: environmentvariables (stringdictionary), not the core environment map.
  # Clear PYTHONPATH for both grok and stub so a parent venv cannot leak in.
  if ($psi.EnvironmentVariables.ContainsKey("PYTHONPATH")) {
    $psi.EnvironmentVariables.Remove("PYTHONPATH")
  }
  $psi.EnvironmentVariables["PYTHONPATH"] = ""

  if ($stub) {
    # Same ProcessStartInfo window-mode path as grok, but a trivial child.
    # powershell.exe -NoProfile so no profile / no model tokens.
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $psExe)) {
      $cmd = Get-Command powershell.exe -ErrorAction SilentlyContinue
      if (-not $cmd) {
        Write-Host "desk-start: stub needs powershell.exe on PATH"
        return 1
      }
      $psExe = $cmd.Source
    }
    $stubMsg = "desk-start stub: sleeping $stubSleep then exit $stubExit"
    # Single -Command string; Join-WinArgv quotes it for CommandLineToArgvW.
    $stubCmd = "Write-Host '$stubMsg'; Start-Sleep -Seconds $stubSleep; exit $stubExit"
    $psi.FileName = $psExe
    $psi.Arguments = Join-WinArgv @("-NoProfile", "-NonInteractive", "-Command", $stubCmd)
    Write-Host "desk-start: stub mode (no grok); sleeping ${stubSleep}s then exit $stubExit"
  } else {
    $psi.FileName = $grok.Source
    # netfx / ps 5.1: set arguments (one string) with join-winargv.
    # skip leading grok (filename); quote the rest (commandlinetoargvw via format-winarg).
    $argTail = @()
    for ($i = 1; $i -lt $argv.Count; $i++) { $argTail += [string]$argv[$i] }
    $psi.Arguments = Join-WinArgv $argTail
  }

  $proc = [System.Diagnostics.Process]::Start($psi)
  if (-not $proc) {
    Write-Host "desk-start: launch failed for $name"
    return 1
  }

  if (-not $stub) {
    # Write session.json only under the desk folder (parent of work_dir).
    @{
      desk        = $name
      session_id  = $sessionId
      started     = (Get-Date).ToString("o")
      pid         = $proc.Id
      launch      = "positional-prompt"
      help_source = "workstation grok --help (grok 1.0.70 stable)"
    } | ConvertTo-Json | Out-File -Encoding utf8 -LiteralPath $sessionPath
    Write-Host "desk-start: launched grok pid $($proc.Id) session $sessionId for $name (fresh; never resume); waiting for exit"
  } else {
    Write-Host "desk-start: launched stub pid $($proc.Id) for $name; waiting for exit"
  }

  # Window mode: wait so the child owns the console until it exits, then
  # propagate the exit code and release the console (card 950).
  $proc.WaitForExit()
  $childExit = 0
  try { $childExit = [int]$proc.ExitCode } catch { $childExit = 1 }
  Write-Host "desk-start: child exited $childExit for $name"
  return $childExit
}

# --- main ---
$cfg = Read-DeskConfig $Config
Assert-Config $cfg
$chosen = Resolve-Desks $cfg $Desk
$code = 0
foreach ($d in $chosen) {
  $rc = [int](Invoke-OneDesk $d $cfg ([bool]$DryRun) ([bool]$Stub) ([int]$StubSleepSeconds) ([int]$StubExitCode))
  if ($rc -ne 0) { $code = $rc }
}
exit $code
