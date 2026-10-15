<#
.SYNOPSIS
    DA3 Demonstration Test Runner Wrapper.
.DESCRIPTION
    Runs the comprehensive DA3 test suite across Backend Unit, Integration,
    Frontend Node assertions, and Live Microservice Probes while enforcing
    strict MongoDB Read-Only and MySQL Baseline EHR invariants.
.PARAMETER Suite
    The test suite to execute: 'quick', 'all', 'unit', 'integration', 'frontend', 'live'. Default: 'quick'.
#>
[CmdletBinding()]
param(
    [ValidateSet("quick", "all", "unit", "integration", "frontend", "live")]
    [string]$Suite = "quick",
    [string]$JsonOutput = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "DA3 LIVE DEMONSTRATION TEST RUNNER" -ForegroundColor Cyan
Write-Host "Target Suite: $Suite" -ForegroundColor Gray
Write-Host "================================================================================" -ForegroundColor Cyan

$CmdArgs = @("$ScriptDir\run_da3_tests.py", "--suite", $Suite)
if ($JsonOutput -ne "") {
    $CmdArgs += @("--json-output", $JsonOutput)
}

python @CmdArgs
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "`n>>> ALL DA3 VERIFICATION TESTS PASSED SUCCESSFULLY <<<`n" -ForegroundColor Green
} else {
    Write-Host "`n>>> TEST RUNNER DETECTED FAILURES (Exit code: $ExitCode) <<<`n" -ForegroundColor Red
}

exit $ExitCode
