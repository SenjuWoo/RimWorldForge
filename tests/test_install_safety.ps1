# Safety regression checks for the RimWorldForge installer.
# It must never delete another profile's plugins or rewrite another Forge's config.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$source = [IO.File]::ReadAllText((Join-Path $repo 'Install.ps1'))
function Assert($ok, [string]$why) { if (-not $ok) { throw $why } }

Assert ($source -notmatch 'Remove-Item\s+\$profPlugins') 'installer still deletes an unowned plugins directory'
Assert ($source -notmatch 'Remove-Item\s+\$profSkills') 'installer still deletes the RimWorld skill directory'
Assert ($source -notmatch 'profiles\\skyrim|profiles\\roblox') 'installer still borrows another Forge profile'
Assert ($source -notmatch 'claude mcp remove') 'installer removes an MCP registration before validating a replacement'
Assert ($source -notmatch 'Set-Content\s+-Path\s+\$cfg') 'installer still rewrites Hermes YAML by text mutation'
Assert ($source -match '\[switch\]\$DryRun') 'installer has no dry-run switch'
Assert ($source -match '\[switch\]\$NoAgentIntegration') 'installer has no opt-out for agent integration'

# Dry run in a path with spaces and non-ASCII characters must not touch user state.
$temp = Join-Path ([IO.Path]::GetTempPath()) ('Rim World ü ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path (Join-Path $temp 'hermes\profiles\rimworld\plugins') | Out-Null
$sentinel = Join-Path $temp 'hermes\profiles\rimworld\plugins\user-plugin.txt'
Set-Content -LiteralPath $sentinel -Value 'keep me'
$sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
Copy-Item -LiteralPath (Join-Path $repo 'Install.ps1') -Destination (Join-Path $temp 'Install.ps1')
$oldLocal = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $temp
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $temp 'Install.ps1') -DryRun 2>&1 | Out-String
    Assert ($LASTEXITCODE -eq 0) ('dry run failed: ' + $output)
    Assert ($output -match 'Dry run') 'dry run did not report its plan'
    Assert (Test-Path -LiteralPath $sentinel) 'dry run removed an existing profile plugin file'
    Assert (([IO.File]::ReadAllText($sentinel)).Contains('keep me')) 'dry run changed a user plugin file'
    Assert ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -eq $sentinelHash) 'dry run modified a user plugin file'
    Assert (-not (Test-Path -LiteralPath (Join-Path $temp 'hermes\profiles\rimworld\config.yaml'))) 'dry run created profile configuration'
    Assert (-not (Test-Path -LiteralPath (Join-Path $temp 'RimWorldForge\bin\rwforge.cmd'))) 'dry run created a launcher'
} finally {
    $env:LOCALAPPDATA = $oldLocal
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Output 'rimworldforge installer safety checks ok'
exit 0
