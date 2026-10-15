param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Push-Location $PSScriptRoot
try {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($launcher) { & $launcher.Source -3 -m venv .venv }
        else { & python -m venv .venv }
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed. Install Python 3.10+ and retry.' }
    }
    & $venvPython -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ required.' }
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $node) { throw 'Install Node.js 22+ and rerun INSTALL.ps1. No npm packages are needed.' }
    & $node.Source -e 'process.exit(parseFloat(process.versions.node) >= 22 ? 0 : 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 22+ required.' }
    & $venvPython -B scripts/check_presentation_app.py --app app --runtime demo --output .local/frontend_build.json
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build verification failed.' }
    Write-Host 'Installation and frontend build verification passed. See INSTALL.md for credentials and live execution.'
} finally { Pop-Location }
