<#
.SYNOPSIS
    Smart Health Monitoring System — Live Demonstration Launcher (Alias).
.DESCRIPTION
    Delegates directly to scripts/launch_demo.ps1 for comprehensive orchestration.
#>

[CmdletBinding()]
param(
    [switch]$PreflightOnly,
    [switch]$NoBrowser,
    [switch]$NoStreamlit,
    [switch]$ForceRestart,
    [int]$HealthTimeoutSeconds = 25
)

$RootDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$RootDir\smart_health_local.db") -and -not (Test-Path "$RootDir\database")) {
    $RootDir = (Get-Location).Path
}

$LauncherPath = Join-Path $RootDir "scripts\launch_demo.ps1"
& $LauncherPath @PSBoundParameters
exit $LASTEXITCODE
