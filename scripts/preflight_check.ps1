<#
.SYNOPSIS
    Smart Health Monitoring System — Preflight Diagnostic Verification Wrapper.
.DESCRIPTION
    Executes comprehensive pre-demonstration verification across runtimes,
    configuration, database integrity, ML artifacts, and live microservice health.
.PARAMETER Offline
    Execute only file and runtime checks; skip live network calls to microservices.
#>

[CmdletBinding()]
param(
    [switch]$Offline
)

$RootDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$RootDir\smart_health_local.db") -and -not (Test-Path "$RootDir\database")) {
    $RootDir = (Get-Location).Path
}

$ScriptPath = Join-Path $RootDir "scripts\preflight_check.py"
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Preflight script not found at $ScriptPath"
    exit 1
}

$ArgsList = @($ScriptPath)
if ($Offline) {
    $ArgsList += "--offline"
}

python @ArgsList
exit $LASTEXITCODE
