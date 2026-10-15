param([switch]$NoKeys, [switch]$KeepBuild)
# Builds dist\GTMTracker.exe. The exe embeds the access keys found at build time
# (project .env if present, else environment variables). Never share it; use -NoKeys for a shareable build.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run .\INSTALL.ps1 first.' }
& $python -c 'import PyInstaller' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
}
$buildArguments = @('-B', (Join-Path $PSScriptRoot 'build_exe.py'))
if ($NoKeys) { $buildArguments += '--no-keys' }
if ($KeepBuild) { $buildArguments += '--keep-build' }
Push-Location $root
try {
    & $python @buildArguments
    $result = $LASTEXITCODE
} finally { Pop-Location }
exit $result
