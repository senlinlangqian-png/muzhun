param([string]$Destination = '', [switch]$Update,
      [ValidateSet('codex', 'deepseek', 'claude', 'cursor', 'gemini', 'opencode', 'kimi', 'agents')][string]$Agent = 'codex')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) { throw 'Run run.ps1 -InstallOnly first.' }
$installArguments = @((Join-Path $projectRoot 'scripts\install_skill.py'), '--agent', $Agent)
if ($Destination) { $installArguments += @('--destination', $Destination) }
if ($Update) { $installArguments += '--update' }
& $venvPython @installArguments
exit $LASTEXITCODE
