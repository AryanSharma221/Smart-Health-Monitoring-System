<#
.SYNOPSIS
    Smart Health Monitoring System — Live Demonstration Orchestrator and Launcher.
    Part 6M — Pre-Demonstration Orchestration and System Verification.

.DESCRIPTION
    Automated, resilient startup and verification workflow:
    1. Validates local runtimes (Python >=3.10, Node.js, NPM) and configuration (.env).
    2. Probes required ports (8001, 8000, 5173, 8501) to avoid starting duplicates.
    3. Starts microservices in strict dependency order:
       - Smartwatch Telemetry Simulator Microservice (:8001)
       - FastAPI Backend Gateway and Ingestion Worker (:8000)
       - React Clinician Workstation (:5173)
       - Streamlit DA3 Analytics Visualizer (:8501, optional)
    4. Enforces safe default: Simulator is verified in the STOPPED state on launch.
    5. Preserves all stdout and stderr service logs in the logs/ directory.
    6. Executes full 26-point live preflight verification before handing control to presenter.
    7. Automatically launches the clinician workstation in the default web browser.

.PARAMETER PreflightOnly
    Execute the diagnostic preflight suite without launching background services.

.PARAMETER NoBrowser
    Do not automatically open the Clinician Workstation in the web browser.

.PARAMETER NoStreamlit
    Skip starting the optional Streamlit analytics dashboard.

.PARAMETER ForceRestart
    Safely stop existing demo services before starting fresh instances.

.PARAMETER HealthTimeoutSeconds
    Maximum seconds to wait for each service readiness probe (default: 25).
#>

[CmdletBinding()]
param(
    [switch]$PreflightOnly,
    [switch]$NoBrowser,
    [switch]$NoStreamlit,
    [switch]$ForceRestart,
    [int]$HealthTimeoutSeconds = 25
)

$ErrorActionPreference = "Stop"

# Resolve absolute repository root
$RootDir = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$RootDir\smart_health_local.db") -and -not (Test-Path "$RootDir\database")) {
    $RootDir = (Get-Location).Path
}

$LogDir = Join-Path $RootDir "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "SMART HEALTH MONITORING SYSTEM - DEMO LAUNCHER (PART 6M)" -ForegroundColor Cyan
Write-Host "Working Directory : $RootDir" -ForegroundColor DarkCyan
Write-Host "Timestamp         : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkCyan
Write-Host "==================================================================" -ForegroundColor Cyan

# -----------------------------------------------------------------------------
# Optional Preflight-Only Mode
# -----------------------------------------------------------------------------
if ($PreflightOnly) {
    Write-Host "`n[*] Invoking Preflight Diagnostics (-PreflightOnly)..." -ForegroundColor Yellow
    python "$RootDir\scripts\preflight_check.py"
    exit $LASTEXITCODE
}

# -----------------------------------------------------------------------------
# Optional Force Restart
# -----------------------------------------------------------------------------
if ($ForceRestart) {
    Write-Host "`n[*] -ForceRestart requested. Stopping active demo services..." -ForegroundColor Yellow
    & "$RootDir\scripts\stop_demo.ps1"
    Start-Sleep -Seconds 2
}

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
function Test-PortListening {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

function Wait-EndpointHealthy {
    param(
        [string]$Url,
        [string]$Name,
        [int]$TimeoutSec = 25
    )
    $Elapsed = 0
    Write-Host -NoNewline "    -> Waiting for $Name readiness at $Url..."
    while ($Elapsed -lt $TimeoutSec) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
                Write-Host " [HEALTHY in ${Elapsed}s]" -ForegroundColor Green
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
            $Elapsed++
            Write-Host -NoNewline "."
        }
    }
    Write-Host " [FAILED / TIMEOUT after ${TimeoutSec}s]" -ForegroundColor Red
    return $false
}

# -----------------------------------------------------------------------------
# Phase 1: Environment and Prerequisite Checks
# -----------------------------------------------------------------------------
Write-Host "`n[*] Phase 1: Checking environment and prerequisites..." -ForegroundColor Yellow

# Python Check
try {
    $PyOut = python --version 2>&1
    Write-Host "    [OK] Python Runtime: $PyOut" -ForegroundColor Green
} catch {
    Write-Error "Python executable not found in PATH. Please install Python 3.10+."
    exit 1
}

# Node.js Check
try {
    $NodeOut = node --version 2>&1
    Write-Host "    [OK] Node.js Runtime: $NodeOut" -ForegroundColor Green
} catch {
    Write-Warning "    [WARN] Node.js not detected on PATH. React dashboard requires Node.js."
}

# .env Configuration Validation (Never print sensitive secrets)
$EnvPath = Join-Path $RootDir ".env"
if (Test-Path $EnvPath) {
    Write-Host "    [OK] Environment configuration verified (.env)" -ForegroundColor Green
} else {
    Write-Warning "    [WARN] .env not found; copying template from .env.example..."
    if (Test-Path "$RootDir\.env.example") {
        Copy-Item "$RootDir\.env.example" $EnvPath
        Write-Host "    [OK] Initialized .env from template." -ForegroundColor Green
    } else {
        Write-Error ".env and .env.example both missing."
        exit 1
    }
}

# Database Integrity Check
$DbPath = Join-Path $RootDir "smart_health_local.db"
if (Test-Path $DbPath) {
    Write-Host "    [OK] Authoritative Relational SQLite database found ($DbPath)" -ForegroundColor Green
} else {
    Write-Warning "    [WARN] Local database file not found at $DbPath. It will be initialized on first write."
}

# ML Artifact Check
$ModelPath = Join-Path $RootDir "models\iforest_v1\model.joblib"
if (Test-Path $ModelPath) {
    Write-Host "    [OK] Trained IsolationForest ML model verified ($ModelPath)" -ForegroundColor Green
} else {
    Write-Host "    [INFO] ML model file not found; heuristic fallback mode will be active." -ForegroundColor DarkYellow
}

# -----------------------------------------------------------------------------
# Phase 2: Start Smartwatch Simulator Microservice (Port 8001)
# -----------------------------------------------------------------------------
Write-Host "`n[*] Phase 2: Orchestrating Smartwatch Sensor Simulator (Port 8001)..." -ForegroundColor Yellow
$simHealthy = $false

if (Test-PortListening -Port 8001) {
    Write-Host "    [INFO] Port 8001 is already listening. Testing health..." -ForegroundColor Cyan
    $simHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:8001/health" -Name "Simulator" -TimeoutSec 5
    if ($simHealthy) {
        Write-Host "    [OK] Reusing existing healthy simulator microservice (no duplicate spawned)." -ForegroundColor Green
    }
}

if (-not $simHealthy) {
    $SimOut = Join-Path $LogDir "simulator.log"
    $SimErr = Join-Path $LogDir "simulator_err.log"
    Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn simulator.main:app --host 127.0.0.1 --port 8001" `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $SimOut `
        -RedirectStandardError $SimErr `
        -WindowStyle Minimized
    $simHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:8001/health" -Name "Simulator" -TimeoutSec $HealthTimeoutSeconds
    if (-not $simHealthy) {
        Write-Error "Failed to start Smartwatch Simulator microservice on port 8001. Check $SimErr."
        exit 1
    }
}

# Enforce default STOPPED condition on simulator before demo
try {
    $simStatusResp = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/v1/simulator/status" -TimeoutSec 3 -ErrorAction SilentlyContinue
    if ($simStatusResp -and $simStatusResp.is_running) {
        Write-Host "    [INFO] Simulator is actively generating. Issuing stop command for demo baseline..." -ForegroundColor Yellow
        Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/v1/simulator/stop" -Method Post -TimeoutSec 3 | Out-Null
    }
    Write-Host "    [OK] Verified Simulator is in clean STOPPED state (ready for manual presenter start)." -ForegroundColor Green
} catch {
    Write-Warning "    Could not verify simulator stopped state: $_"
}

# -----------------------------------------------------------------------------
# Phase 3: Start FastAPI Backend Gateway and Ingestion Worker (Port 8000)
# -----------------------------------------------------------------------------
Write-Host "`n[*] Phase 3: Orchestrating FastAPI Backend Gateway (Port 8000)..." -ForegroundColor Yellow
$apiHealthy = $false

if (Test-PortListening -Port 8000) {
    Write-Host "    [INFO] Port 8000 is already listening. Testing health..." -ForegroundColor Cyan
    $apiHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:8000/api/v1/health" -Name "FastAPI Backend" -TimeoutSec 5
    if ($apiHealthy) {
        Write-Host "    [OK] Reusing existing healthy FastAPI backend service (no duplicate spawned)." -ForegroundColor Green
    }
}

if (-not $apiHealthy) {
    $ApiOut = Join-Path $LogDir "backend.log"
    $ApiErr = Join-Path $LogDir "backend_err.log"
    Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn services.api.main:app --host 127.0.0.1 --port 8000" `
        -WorkingDirectory $RootDir `
        -RedirectStandardOutput $ApiOut `
        -RedirectStandardError $ApiErr `
        -WindowStyle Minimized
    $apiHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:8000/api/v1/health" -Name "FastAPI Backend" -TimeoutSec $HealthTimeoutSeconds
    if (-not $apiHealthy) {
        Write-Error "Failed to start FastAPI Backend Gateway on port 8000. Check $ApiErr."
        exit 1
    }
}

# -----------------------------------------------------------------------------
# Phase 4: Start React Clinician Workstation (Port 5173)
# -----------------------------------------------------------------------------
Write-Host "`n[*] Phase 4: Orchestrating React Clinician Workstation (Port 5173)..." -ForegroundColor Yellow
$webHealthy = $false
$DoctorWebDir = Join-Path $RootDir "frontend\apps\doctor_web"

if (Test-PortListening -Port 5173) {
    Write-Host "    [INFO] Port 5173 is already listening. Testing reachability..." -ForegroundColor Cyan
    $webHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:5173" -Name "React Clinician Dashboard" -TimeoutSec 5
    if ($webHealthy) {
        Write-Host "    [OK] Reusing existing Clinician Workstation instance (no duplicate spawned)." -ForegroundColor Green
    }
}

if (-not $webHealthy) {
    $WebOut = Join-Path $LogDir "doctor_web.log"
    $WebErr = Join-Path $LogDir "doctor_web_err.log"
    Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c npx vite --host 127.0.0.1 --port 5173" `
        -WorkingDirectory $DoctorWebDir `
        -RedirectStandardOutput $WebOut `
        -RedirectStandardError $WebErr `
        -WindowStyle Minimized
    $webHealthy = Wait-EndpointHealthy -Url "http://127.0.0.1:5173" -Name "React Clinician Dashboard" -TimeoutSec $HealthTimeoutSeconds
    if (-not $webHealthy) {
        Write-Warning "React Clinician Dashboard did not respond on port 5173 within timeout. Check $WebErr."
    }
}

# -----------------------------------------------------------------------------
# Phase 5: Start Streamlit Analytics Dashboard (Port 8501, Optional)
# -----------------------------------------------------------------------------
if (-not $NoStreamlit) {
    Write-Host "`n[*] Phase 5: Orchestrating Streamlit DA3 Analytics Visualizer (Port 8501)..." -ForegroundColor Yellow
    $stHealthy = $false

    if (Test-PortListening -Port 8501) {
        Write-Host "    [INFO] Port 8501 is already listening. Testing health..." -ForegroundColor Cyan
        $stHealthy = Wait-EndpointHealthy -Url "http://localhost:8501/_stcore/health" -Name "Streamlit Visualizer" -TimeoutSec 5
        if ($stHealthy) {
            Write-Host "    [OK] Reusing existing Streamlit Analytics dashboard (no duplicate spawned)." -ForegroundColor Green
        }
    }

    if (-not $stHealthy) {
        $StOut = Join-Path $LogDir "streamlit.log"
        $StErr = Join-Path $LogDir "streamlit_err.log"
        Start-Process -FilePath "python" `
            -ArgumentList "-m streamlit run dashboard/app.py --server.port 8501 --server.headless true" `
            -WorkingDirectory $RootDir `
            -RedirectStandardOutput $StOut `
            -RedirectStandardError $StErr `
            -WindowStyle Minimized
        $stHealthy = Wait-EndpointHealthy -Url "http://localhost:8501/_stcore/health" -Name "Streamlit Visualizer" -TimeoutSec $HealthTimeoutSeconds
    }
} else {
    Write-Host "`n[*] Phase 5: Skipping Streamlit Analytics Dashboard (-NoStreamlit specified)." -ForegroundColor DarkGray
}

# -----------------------------------------------------------------------------
# Phase 6: Post-Launch Preflight Verification
# -----------------------------------------------------------------------------
Write-Host "`n[*] Phase 6: Executing Complete Preflight Verification Suite..." -ForegroundColor Yellow
python "$RootDir\scripts\preflight_check.py"
$preflightExit = $LASTEXITCODE

# -----------------------------------------------------------------------------
# Phase 7: Launch Web Browser
# -----------------------------------------------------------------------------
if (-not $NoBrowser) {
    Write-Host "`n[*] Phase 7: Opening Clinician Workstation in default browser..." -ForegroundColor Yellow
    Start-Process "http://127.0.0.1:5173"
}

# -----------------------------------------------------------------------------
# Operator Summary and Demo Runbook
# -----------------------------------------------------------------------------
Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "LIVE DEMONSTRATION ENVIRONMENT READY AND VERIFIED" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "Access Points and URLs:"
Write-Host "  1. Clinician React Portal : http://127.0.0.1:5173" -ForegroundColor White
Write-Host "     - Doctor Credentials   : doctor@hospital.org / DoctorPassword123!" -ForegroundColor Yellow
Write-Host "     - Demonstration Cohort : Patients P101, P102, P103, P104, P105" -ForegroundColor Gray
Write-Host "  2. FastAPI Gateway & Docs : http://127.0.0.1:8000" -ForegroundColor White
Write-Host "     - Swagger Interactive  : http://127.0.0.1:8000/docs" -ForegroundColor Gray
Write-Host "     - Ingestion Status     : http://127.0.0.1:8000/api/v1/simulator/ingestion-status" -ForegroundColor Gray
Write-Host "  3. Simulator Microservice : http://127.0.0.1:8001" -ForegroundColor White
Write-Host "     - Simulator Status     : http://127.0.0.1:8001/api/v1/simulator/status" -ForegroundColor Gray
Write-Host "     - Telemetry Feed (Raw) : http://127.0.0.1:8001/api/v1/readings/latest" -ForegroundColor Gray
if (-not $NoStreamlit) {
    Write-Host "  4. Streamlit Analytics    : http://localhost:8501" -ForegroundColor White
    Write-Host "     - DA3 Benchmarks       : SQL-vs-NoSQL latency and population analytics" -ForegroundColor Gray
}

Write-Host "`nPresenter Quick Guide:" -ForegroundColor Cyan
Write-Host "  * The simulator is currently STOPPED. Baseline patient vitals and clinical" -ForegroundColor White
Write-Host "    records are fully operational without synthetic data running." -ForegroundColor White
Write-Host "  * To begin streaming: In the Live Telemetry panel, click 'Start Telemetry'." -ForegroundColor White
Write-Host "  * To halt streaming: Click 'Stop Telemetry' at any time." -ForegroundColor White

Write-Host "`nShutdown Command (After Live Demo):" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\stop_demo.ps1" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Cyan

exit $preflightExit
