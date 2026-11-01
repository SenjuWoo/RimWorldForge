[CmdletBinding()]
param(
  [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw 'Python 3.10+ was not found on PATH.' }
Write-Host '== RimWorldForge install =='
Write-Host "root: $root"
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
Set-Content -Path $launcher -Encoding ASCII -Value "@echo off`r`n`"$vpy`" -m rwforge.cli %*`r`n"
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) { $userPath = '' }
if ($userPath -notlike "*$binDir*") {
  [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $binDir), 'User')
  Write-Host "added $binDir to the user PATH; open a new shell to use 'rwforge'"
}
Write-Host "rwforge launcher: $launcher"

$serverPy = Join-Path $root 'mcp_server\server.py'
$skillSrc = Join-Path $root 'skills\rimworld-forge'
$mcpBlock = @"
mcp_servers:
  rimworldforge:
    command: $($root.Replace('\','/'))/.venv/Scripts/python.exe
    args:
      - $($serverPy.Replace('\','/'))
    enabled: true
    connect_timeout: 30
"@

# --- Hermes: dedicated rimworld profile (MCP lives there, not globally) ---
$hermes = Get-Command hermes -ErrorAction SilentlyContinue
if ($hermes) {
  Write-Host ''
  Write-Host '== Hermes profile =='
  $existing = & hermes profile list 2>$null | Out-String
  if ($existing -match '(?m)^\s*rimworld\s') {
    Write-Host 'profile rimworld already exists - refreshing MCP entry if needed'
  } else {
    & hermes profile create rimworld --description 'RimWorld 1.6/1.7 modding with RimWorldForge: Def indexing across the game plus installed Workshop mods, mod generation/validation/builds, and Player.log diagnosis. MCP is rimworldforge-only so token cost stays minimal.'
    if ($LASTEXITCODE -ne 0) { Write-Warning 'hermes profile create failed; skipping Hermes wiring' }
  }
  $cfg = Join-Path $env:LOCALAPPDATA 'hermes\profiles\rimworld\config.yaml'
  if (Test-Path $cfg) {
    $cfgText = Get-Content $cfg -Raw
    if ($cfgText -notmatch 'rimworldforge:') {
      # Base the profile on the defaults the user already has: mirror the MCP servers
      # enabled in their default profile (minus any rimworldforge entry), then add
      # rimworldforge. Falls back to forge-only if the default config has none.
      $defaultCfg = Join-Path $env:LOCALAPPDATA 'hermes\config.yaml'
      $extraServers = ''
      if (Test-Path $defaultCfg) {
        try {
          $defText = Get-Content $defaultCfg -Raw
          $blockLines = @()
          $inBlock = $false
          foreach ($line in ($defText -split "`r?`n")) {
            if ($line -match '^mcp_servers:\s*$') { $inBlock = $true; continue }
            if ($inBlock) {
              if ($line -match '^\s') { $blockLines += $line } else { break }
            }
          }
          $current = $null
          $entries = [ordered]@{}
          foreach ($line in $blockLines) {
            if ($line -match '^  ([A-Za-z0-9_.-]+):\s*$') {
              $current = $Matches[1]
              if (-not $entries.Contains($current)) { $entries[$current] = New-Object System.Collections.Generic.List[string] }
              if ($current -ne 'rimworldforge') { $entries[$current].Add($line) }
            } elseif ($null -ne $current) {
              if ($current -ne 'rimworldforge') { $entries[$current].Add($line) }
            }
          }
          foreach ($name in $entries.Keys) {
            if ($name -eq 'rimworldforge') { continue }
            if ($cfgText -match ('^\s*' + [regex]::Escape($name) + ':')) { continue }
            $extraServers += "`n" + ($entries[$name] -join "`n")
          }
        } catch { Write-Host 'could not mirror default-profile MCPs; continuing with forge-only' }
      }
      Add-Content -Path $cfg -Value "`n$mcpBlock$extraServers" -Encoding utf8
      $mirrored = @($entries.Keys | Where-Object { $_ -ne 'rimworldforge' }).Count
      Write-Host "wrote rimworldforge MCP (+$mirrored mirrored servers) -> $cfg"
    } else {
      Write-Host 'rimworldforge MCP already in profile config'
    }
  }
  # --- Repair profile plumbing so it matches roblox/skyrim (junction + full bundled skills + full config) ---
  $profRoot = Join-Path $env:LOCALAPPDATA 'hermes\profiles\rimworld'
  $defaultPlugins = Join-Path $env:LOCALAPPDATA 'hermes\plugins'
  $profPlugins = Join-Path $profRoot 'plugins'
  try {
    $linkType = $null; try { $linkType = (Get-Item $profPlugins -ErrorAction Stop).LinkType } catch {}
    if (-not $linkType) {
      if (Test-Path $profPlugins) { Remove-Item $profPlugins -Recurse -Force }
      New-Item -ItemType Junction -Path $profPlugins -Target $defaultPlugins | Out-Null
      Write-Host "fixed plugins junction -> $defaultPlugins"
    }
  } catch { Write-Warning "could not fix plugins junction: $_" }

  # Seed missing bundled skills from a healthy profile (skyrim/roblox) or the default store
  try {
    $profSkillsDir = Join-Path $profRoot 'skills'
    $seedSrc = $null
    foreach ($cand in @((Join-Path $env:LOCALAPPDATA 'hermes\profiles\skyrim\skills'), (Join-Path $env:LOCALAPPDATA 'hermes\profiles\roblox\skills'), (Join-Path $env:LOCALAPPDATA 'hermes\skills'))) {
      if (Test-Path $cand) { $seedSrc = $cand; break }
    }
    if ($seedSrc) {
      $missing = Compare-Object (Get-ChildItem $seedSrc -Name) (Get-ChildItem $profSkillsDir -Name) | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject }
      foreach ($m in $missing) {
        Copy-Item (Join-Path $seedSrc $m) (Join-Path $profSkillsDir $m) -Recurse -Force
      }
      if ($missing) { Write-Host "seeded $($missing.Count) missing skills from $seedSrc" }
    }
  } catch { Write-Warning "skill seeding failed: $_" }

  # If config is still the old truncated shape (missing terminal/browser/compression etc.), repair from skyrim template keeping rimworldforge MCP
  try {
    $skyrimCfg = Join-Path $env:LOCALAPPDATA 'hermes\profiles\skyrim\config.yaml'
    if ((Test-Path $skyrimCfg) -and (Test-Path $cfg)) {
      $cur = Get-Content $cfg -Raw
      if ($cur -notmatch '(?m)^terminal:' -or $cur -notmatch '(?m)^compression:') {
        $sky = Get-Content $skyrimCfg -Raw
        $mcpBlockCurrent = $null
        if ($cur -match '(?ms)^mcp_servers:\r?\n.*?(?=^platform_toolsets:)') { $mcpBlockCurrent = $Matches[0] -replace 'platform_toolsets:$','' }
        if (-not $mcpBlockCurrent) { $mcpBlockCurrent = "mcp_servers:`n  rimworldforge:`n    command: $($root.Replace('\','/'))/.venv/Scripts/python.exe`n    args:`n      - $($serverPy.Replace('\','/'))`n    enabled: true`n    connect_timeout: 30`n" }
        $skyPatched = $sky -replace '(?ms)^mcp_servers:\r?\n.*?(?=^platform_toolsets:)', $mcpBlockCurrent
        if ($skyPatched -notmatch 'rimworldforge:') { $skyPatched = $sky -replace '(?ms)^mcp_servers:\r?\n.*?(?=^platform_toolsets:)', $mcpBlockCurrent }
        Set-Content -Path $cfg -Value $skyPatched -Encoding utf8
        Write-Host "repaired truncated config.yaml from skyrim template (kept rimworldforge MCP)"
      }
    }
  } catch { Write-Warning "config repair skipped: $_" }

  $profSkills = Join-Path $env:LOCALAPPDATA "hermes\profiles\rimworld\skills\rimworld-forge"
  if ((Test-Path (Join-Path $env:LOCALAPPDATA 'hermes\profiles\rimworld')) -and -not (Test-Path $profSkills)) {
    Copy-Item $skillSrc $profSkills -Recurse
    Write-Host 'skill installed into rimworld profile'
  } else {
    # refresh from repo so profile stays current even if it already exists
    if (Test-Path $profSkills) { Remove-Item $profSkills -Recurse -Force }
    Copy-Item $skillSrc $profSkills -Recurse
    Write-Host 'skill refreshed into rimworld profile'
  }
  Write-Host 'use it with:  rimworld  (wrapper) or  hermes -p rimworld'
} else {
  Write-Host 'hermes CLI not found - skipped Hermes profile'
}

# --- Claude Code: user-scope MCP + skill copy ---
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  Write-Host ''
  Write-Host '== Claude Code =='
$claudeErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& claude mcp remove --scope user rimworldforge 2>$null | Out-Null
& claude mcp add --scope user rimworldforge -- $vpy $serverPy 2>$null
$ErrorActionPreference = $claudeErrorPreference
$list = (claude mcp list 2>$null | Out-String)
if ($list -match 'rimworldforge') { Write-Host 'rimworldforge MCP registered (user scope)' } else { Write-Warning 'claude mcp add failed' }
  $ccSkills = Join-Path $env:USERPROFILE '.claude\skills\rimworld-forge'
  if (-not (Test-Path $ccSkills)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $ccSkills) | Out-Null
    Copy-Item $skillSrc $ccSkills -Recurse
    Write-Host 'skill installed into ~/.claude/skills'
  }
} else {
  Write-Host 'claude CLI not found - skipped Claude Code wiring'
}

# --- Codex CLI: no project-scoped MCP config exists; skill file for reference ---
$codexDir = Join-Path $env:USERPROFILE '.codex'
if (Test-Path $codexDir) {
  $cxSkills = Join-Path $codexDir 'skills\rimworld-forge'
  if (-not (Test-Path $cxSkills)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $cxSkills) | Out-Null
    Copy-Item $skillSrc $cxSkills -Recurse
    Write-Host ''
    Write-Host '== Codex == skill copied to ~/.codex/skills (Codex has no native MCP project scope; point it at the server command manually if wanted)'
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
