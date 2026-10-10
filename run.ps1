param([int]$Port = 8770, [switch]$InstallOnly, [switch]$NoBrowser, [string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bootstrapArguments = @()
if ($Python) { $bootstrapPython = $Python }
elseif (Test-Path -LiteralPath $venvPython) { $bootstrapPython = $venvPython }
else {
    $bootstrapPython = $null
    foreach ($version in @('3.12','3.13','3.11','3.10','3')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            try { & py "-$version" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null }
            catch { continue }
            if ($LASTEXITCODE -eq 0) {
                $bootstrapPython = (Get-Command py).Source
                $bootstrapArguments = @("-$version")
                break
            }
        }
    }
    if (-not $bootstrapPython) {
        foreach ($name in @('python','python3')) {
            $candidate = Get-Command $name -ErrorAction SilentlyContinue
            if ($candidate) {
                try { & $candidate.Source -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>$null }
                catch { continue }
                if ($LASTEXITCODE -eq 0) { $bootstrapPython = $candidate.Source; break }
            }
        }
    }
    if (-not $bootstrapPython) {
        Write-Host 'Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/.'
        Write-Host 'Enable Add python.exe to PATH, then run Start-Muzhun.cmd again.'
        exit 1
    }
}
$launchArguments = @((Join-Path $projectRoot 'scripts\launch.py'), '--port', "$Port")
if ($InstallOnly) { $launchArguments += '--install-only' }
if ($NoBrowser) { $launchArguments += '--no-browser' }
& $bootstrapPython @bootstrapArguments @launchArguments
exit $LASTEXITCODE
