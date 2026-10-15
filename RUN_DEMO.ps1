param([ValidateRange(0,65535)][int]$Port = 8877)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$runtimePath = Join-Path $PSScriptRoot 'runtime\server.py'
$pythonCommand = $null
$pythonArguments = @()
foreach ($candidate in @('py', 'python', 'python3')) {
    $found = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $found) { continue }
    $candidateArguments = @()
    if ($candidate -eq 'py') { $candidateArguments = @('-3') }
    try {
        & $found.Source @candidateArguments -I -B -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $pythonCommand = $found.Source
            $pythonArguments = $candidateArguments
            break
        }
    } catch { continue }
}
if (-not $pythonCommand) {
    Write-Host 'Python 3.10 or newer is required. Install Python with its launcher, reopen PowerShell, and try again.' -ForegroundColor Yellow
    Write-Host 'The demo uses only the standard library; no packages, accounts or internet connection are needed.'
    exit 1
}
# Isolated mode ignores Python environment variables and user site-packages.
# No virtual environment or package installation is necessary.
& $pythonCommand @pythonArguments -I -B $runtimePath --port $Port
exit $LASTEXITCODE
