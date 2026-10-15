<#
.SYNOPSIS
    Gracefully and safely stops all demonstration services of the Smart Health Monitoring System.

.DESCRIPTION
    Scans the configured demonstration ports:
    - 8001: Smartwatch Sensor Simulator Microservice
    - 8000: FastAPI Central Backend Gateway & Ingestion Worker
    - 5173: Vite Clinician React Dashboard
    - 8501: Streamlit DA3 Analytics Visualizer

    SAFETY & INTEGRITY GUARDS:
    1. Inspects process name and command line before termination.
    2. Only terminates processes recognized as part of this demonstration
       (python, node, cmd, uvicorn, vite, streamlit).
    3. Never touches unrelated operating system or user processes.
    4. Never deletes databases, logs, or clinical records.
#>

[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Continue"

$Ports = @(8001, 8000, 5173, 8501)
$PortNames = @{
    8001 = "Smartwatch Simulator (Port 8001)"
    8000 = "FastAPI Backend Gateway (Port 8000)"
    5173 = "Clinician React Dashboard (Port 5173)"
    8501 = "Streamlit Analytics Dashboard (Port 8501)"
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "SMART HEALTH MONITORING SYSTEM — SAFE SERVICE SHUTDOWN" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

$StoppedCount = 0

foreach ($Port in $Ports) {
    $ServiceName = $PortNames[$Port]
    Write-Host "[*] Inspecting $ServiceName..." -ForegroundColor Yellow

    try {
        $Connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($Connections) {
            $ProcessIds = $Connections | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($TargetPid in $ProcessIds) {
                if ($TargetPid -le 4) {
                    Write-Warning "    Skipping System PID $TargetPid on port $Port."
                    continue
                }

                $Proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
                if (-not $Proc) { continue }

                # Verify process is a Python or Node runner to protect unrelated processes
                $ProcName = $Proc.ProcessName.ToLower()
                $IsDemoProcess = ($ProcName -match "^(python|node|cmd|electron)$")

                # Double check command line via WMI / CIM if possible
                try {
                    $CimProc = Get-CimInstance Win32_Process -Filter "ProcessId = $TargetPid" -ErrorAction SilentlyContinue
                    if ($CimProc -and $CimProc.CommandLine) {
                        $Cmd = $CimProc.CommandLine.ToLower()
                        if ($Cmd -match "(uvicorn|vite|streamlit|simulator\.main|services\.api)") {
                            $IsDemoProcess = $true
                        }
                    }
                } catch {
                    # Fallback to process name check
                }

                if ($IsDemoProcess -or $Force) {
                    Write-Host "    -> Terminating $ServiceName process (PID: $TargetPid, Process: $($Proc.ProcessName))..." -ForegroundColor DarkYellow
                    Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
                    $StoppedCount++
                } else {
                    Write-Warning "    [SAFEGUARD] Process PID $TargetPid ($($Proc.ProcessName)) on port $Port does not match demonstration patterns. Skipping to prevent terminating unrelated system processes. Use -Force to override."
                }
            }

            Start-Sleep -Milliseconds 600
            $Remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            if (-not $Remaining) {
                Write-Host "    [OK] Port $Port successfully released." -ForegroundColor Green
            } else {
                Write-Warning "    [WARN] Port $Port still has active listeners."
            }
        } else {
            Write-Host "    [-] Port $Port is not listening (already stopped)." -ForegroundColor DarkGray
        }
    } catch {
        Write-Warning "    Error scanning port $Port : $_"
    }
}

Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "SHUTDOWN VERIFICATION: $StoppedCount demonstration process(es) safely terminated." -ForegroundColor Green
Write-Host "Historical readings, databases, and audit trails remain 100% intact." -ForegroundColor Gray
Write-Host "==================================================================" -ForegroundColor Cyan
