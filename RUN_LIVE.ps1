param([switch]$CheckOnly, [switch]$NoServe, [ValidateRange(0,65535)][int]$Port = 8878)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run .\INSTALL.ps1 first.' }
$liveArguments = @('-B', 'scripts/run_live.py', '--port', "$Port")
if ($CheckOnly) { $liveArguments += '--check-only' }
if ($NoServe) { $liveArguments += '--no-serve' }
Push-Location $PSScriptRoot
try {
    & $python @liveArguments
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
