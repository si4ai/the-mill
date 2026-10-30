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

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Config,

  [Parameter(Mandatory = $true)]
  [string[]]$Desk,

  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function New-SessionUuid { return [guid]::NewGuid().ToString() }

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
  $tpl = [string](Get-Default $cfg "first_message_template" "desk {desk}`ndo the open work (claimed cards, open letters) first, then start mill connect-wait")
  if ($desk.first_message_template) { $tpl = [string]$desk.first_message_template }
  $map = @{
    desk           = [string]$desk.name
    lessons_label  = [string]$(if ($desk.lessons_label) { $desk.lessons_label } else { "" })
    mill_office    = [string]$cfg.office.mill_office
    roster         = [string]$(if ($cfg.office.roster) { $cfg.office.roster } else { "" })
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

function Invoke-OneDesk($desk, $cfg, [bool]$dry) {
  $name = [string]$desk.name
  $target = [string]$desk.credential_target
  $work = [string]$desk.work_dir
  $exportDir = [string]$desk.export_dir
  $deskRoot = Split-Path -Parent $work
  $sessionPath = Join-Path $deskRoot "session.json"

  if (-not $dry) {
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
    launch           = "positional-prompt"
    launch_mode      = $(if ($cfg.office.launch_mode) { [string]$cfg.office.launch_mode } else { 'dashboard' })
    leader_socket    = $(if ($cfg.office.leader_socket) { [string]$cfg.office.leader_socket } else { '' })
    window_argv      = @($argv)
    outcome          = "ok"
    would_launch     = $true
    launched         = $false
    session_record   = $sessionPath
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
    $plan | ConvertTo-Json -Depth 8
    return 0
  }

  $grok = Get-Command grok -ErrorAction SilentlyContinue
  if (-not $grok) {
    Write-Host "desk-start: grok not on PATH"
    return 1
  }

  if ($launchMode -eq 'dashboard') {
    Write-Host "desk-start: launch_mode=dashboard attach recipe is UNVERIFIED; refuse live launch until runbook step 0 probe passes. Use -DryRun or set office.launch_mode to window."
    return 1
  }

  if ($exportArgv.Count -gt 0) {
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
  $psi.FileName = $grok.Source
  $psi.UseShellExecute = $false
  $psi.WorkingDirectory = $work
  # Rebuild ArgumentList from argv without the leading "grok"
  for ($i = 1; $i -lt $argv.Count; $i++) { [void]$psi.ArgumentList.Add([string]$argv[$i]) }
  if ($psi.Environment.ContainsKey("PYTHONPATH")) { [void]$psi.Environment.Remove("PYTHONPATH") }
  $psi.Environment["PYTHONPATH"] = ""

  $proc = [System.Diagnostics.Process]::Start($psi)
  if (-not $proc) {
    Write-Host "desk-start: launch failed for $name"
    return 1
  }

  # Write session.json only under the desk folder (parent of work_dir).
  @{
    desk        = $name
    session_id  = $sessionId
    started     = (Get-Date).ToString("o")
    pid         = $proc.Id
    launch      = "positional-prompt"
    help_source = "workstation grok --help (grok 1.0.70 stable)"
  } | ConvertTo-Json | Out-File -Encoding utf8 -LiteralPath $sessionPath

  Write-Host "desk-start: launched grok pid $($proc.Id) session $sessionId for $name (fresh; never resume)"
  return 0
}

# --- main ---
$cfg = Read-DeskConfig $Config
Assert-Config $cfg
$chosen = Resolve-Desks $cfg $Desk
$code = 0
foreach ($d in $chosen) {
  $rc = Invoke-OneDesk $d $cfg ([bool]$DryRun)
  if ($rc -ne 0) { $code = $rc }
}
exit $code
