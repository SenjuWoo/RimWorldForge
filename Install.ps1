[CmdletBinding()]
param(
  [switch]$SkipTests,
  [switch]$DryRun,
  [switch]$NoAgentIntegration
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Write-Host '== RimWorldForge install =='
Write-Host "root: $root"
if ($DryRun) {
  Write-Host 'Dry run: no files, packages or agent configuration will be changed.'
  Write-Host "  venv: $root\.venv"
  Write-Host "  launcher: $env:LOCALAPPDATA\RimWorldForge\bin\rwforge.cmd"
  Write-Host "  owner doctor: <installed-venv-python> -m rwforge.cli doctor"
  if ($NoAgentIntegration) { Write-Host '  agent integration: disabled by -NoAgentIntegration' }
  else { Write-Host '  agent integration: add only the rimworldforge MCP and rimworld-forge skill when absent; never delete another profile directory or rewrite its YAML' }
  return
}
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw 'Python 3.10+ was not found on PATH.' }
& $py.Source --version
$venv = Join-Path $root '.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
  & $py.Source -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw "venv creation failed with exit code $LASTEXITCODE" }
}
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --disable-pip-version-check -e $root
if ($LASTEXITCODE -ne 0) { throw "pip install failed with exit code $LASTEXITCODE" }
if (-not $SkipTests) {
  & $vpy (Join-Path $root 'tests\run_tests.py')
  if ($LASTEXITCODE -ne 0) { throw "tests failed with exit code $LASTEXITCODE" }
}

# Small launcher so `rwforge` works outside the venv; Uninstall.ps1 reverses this.
$binDir = Join-Path $env:LOCALAPPDATA 'RimWorldForge\bin'
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$launcher = Join-Path $binDir 'rwforge.cmd'
# The launcher names this checkout's interpreter by full path. If the folder is
# moved or deleted that path is gone, so the launcher says what happened and how
# to repair it instead of printing "the system cannot find the path specified".
$launcherLines = @(
  '@echo off',
  'setlocal EnableExtensions DisableDelayedExpansion',
  ('if not exist "{0}" (' -f $vpy),
  '  echo RimWorldForge is no longer at the folder this launcher was created for. 1>&2',
  '  echo Run Install.ps1 from its current folder to repair the launcher. 1>&2',
  '  exit /b 3',
  ')',
  ('"{0}" -m rwforge.cli %*' -f $vpy),
  'exit /b %ERRORLEVEL%'
)
[IO.File]::WriteAllText($launcher, (($launcherLines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding($false)))
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if ($userPath -notlike "*$binDir*") {
  [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $binDir), 'User')
  Write-Host "added $binDir to the user PATH; open a new shell to use 'rwforge'"
}
Write-Host "rwforge launcher: $launcher"

$serverPy = Join-Path $root 'mcp_server\server.py'
$skillSrc = Join-Path $root 'skills\rimworld-forge'
function Backup-IntegrationFile([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
  $backup = "$Path.bak-$(Get-Date -Format yyyyMMddHHmmss)"
  Copy-Item -LiteralPath $Path -Destination $backup -Force
  return $backup
}
function Restore-IntegrationFile([string]$Path, [string]$Backup) {
  if ($Backup -and (Test-Path -LiteralPath $Backup -PathType Leaf)) { Copy-Item -LiteralPath $Backup -Destination $Path -Force }
}

# --- Hermes: dedicated rimworld profile, optional and additive ---
$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if ($NoAgentIntegration) {
  Write-Host 'agent integration disabled by -NoAgentIntegration'
} elseif ($hermes) {
  Write-Host ''
  Write-Host '== Hermes profile =='
  $existing = & hermes profile list 2>$null | Out-String
  if ($existing -notmatch '(?m)^\s*rimworld\s') {
    & hermes profile create rimworld --description 'RimWorld 1.6/1.7 modding with RimWorldForge: Def indexing across the game plus installed Workshop mods, mod generation/validation/builds, and Player.log diagnosis. MCP is rimworldforge-only so token cost stays minimal.'
    if ($LASTEXITCODE -ne 0) { Write-Warning 'hermes profile create failed; skipping Hermes wiring' }
  }
  $cfg = Join-Path $env:LOCALAPPDATA 'hermes\profiles\rimworld\config.yaml'
  if (Test-Path -LiteralPath $cfg -PathType Leaf) {
    $mcpList = ''
    try { $mcpList = & hermes -p rimworld mcp list 2>$null | Out-String } catch {}
    if ($mcpList -notmatch 'rimworldforge') {
      $backup = Backup-IntegrationFile $cfg
      & hermes -p rimworld mcp add rimworldforge --command $vpy --connect-timeout 30 --args $serverPy 2>$null
      if ($LASTEXITCODE -ne 0) {
        Restore-IntegrationFile $cfg $backup
        Write-Warning 'hermes mcp add failed; profile config restored'
      } else {
        Write-Host "registered rimworldforge MCP -> $cfg"
      }
    } else {
      Write-Host 'rimworldforge MCP already registered; left unchanged'
    }
    $profSkills = Join-Path $env:LOCALAPPDATA 'hermes\profiles\rimworld\skills\rimworld-forge'
    if (-not (Test-Path -LiteralPath $profSkills)) {
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $profSkills) | Out-Null
      Copy-Item $skillSrc $profSkills -Recurse
      Write-Host 'skill installed into rimworld profile'
    } else {
      Write-Host 'rimworld-forge profile skill already present; left unchanged'
    }
  }
  Write-Host 'use it with:  rimworld  (wrapper) or  hermes -p rimworld'
} else {
  Write-Host 'hermes CLI not found - skipped Hermes profile'
}

# --- Claude Code: user-scope MCP + skill copy, additive only ---
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude -and -not $NoAgentIntegration) {
  Write-Host ''
  Write-Host '== Claude Code =='
  $claudeErrorPreference = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $list = (claude mcp list 2>$null | Out-String)
  if ($list -notmatch 'rimworldforge') {
    $claudeCfg = Join-Path $env:USERPROFILE '.claude.json'
    $backup = Backup-IntegrationFile $claudeCfg
    & claude mcp add --scope user rimworldforge -- $vpy $serverPy 2>$null
    if ($LASTEXITCODE -ne 0) {
      Restore-IntegrationFile $claudeCfg $backup
      Write-Warning 'claude mcp add failed; Claude config restored'
    }
  } else {
    Write-Host 'rimworldforge MCP already registered; left unchanged'
  }
  $ErrorActionPreference = $claudeErrorPreference
  $list = (claude mcp list 2>$null | Out-String)
  if ($list -match 'rimworldforge') { Write-Host 'rimworldforge MCP registered (user scope)' } else { Write-Warning 'claude mcp registration missing' }
  $ccSkills = Join-Path $env:USERPROFILE '.claude\skills\rimworld-forge'
  if (-not (Test-Path -LiteralPath $ccSkills)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $ccSkills) | Out-Null
    Copy-Item $skillSrc $ccSkills -Recurse
    Write-Host 'skill installed into ~/.claude/skills'
  } else {
    Write-Host 'rimworld-forge Claude skill already present; left unchanged'
  }
} elseif ($NoAgentIntegration) {
  Write-Host 'Claude integration disabled by -NoAgentIntegration'
} else {
  Write-Host 'claude CLI not found - skipped Claude Code wiring'
}

# --- Codex CLI: optional skill copy, additive only ---
$codexDir = Join-Path $env:USERPROFILE '.codex'
if ((Test-Path $codexDir) -and -not $NoAgentIntegration) {
  $cxSkills = Join-Path $codexDir 'skills\rimworld-forge'
  if (-not (Test-Path -LiteralPath $cxSkills)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $cxSkills) | Out-Null
    Copy-Item $skillSrc $cxSkills -Recurse
    Write-Host ''
    Write-Host '== Codex == skill copied to ~/.codex/skills (Codex has no native MCP project scope; point it at the server command manually if wanted)'
  } else {
    Write-Host 'rimworld-forge Codex skill already present; left unchanged'
  }
}

Write-Host ''
Write-Host 'Installed. Quick start:'
Write-Host "  $vpy -m rwforge.cli doctor"
Write-Host "  $vpy -m rwforge.cli index      # auto-discovers game + all Steam libraries"
Write-Host "  $vpy -m rwforge.cli capabilities"
Write-Host ''
Write-Host 'Standalone MCP command (register only where you need it):'
Write-Host "  $vpy $serverPy"
