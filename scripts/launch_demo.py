"""
Smart Health Monitoring System — Cross-Platform Demonstration Launcher (Python).
Part 6M — Pre-Demonstration Orchestration and System Verification.

Launches and verifies all demonstration services across Windows, Linux, and macOS:
1. Smartwatch Telemetry Simulator Microservice (:8001)
2. FastAPI Backend Gateway & Ingestion Worker (:8000)
3. React Clinician Workstation (:5173)
4. Streamlit DA3 Analytics Dashboard (:8501, optional)
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import webbrowser

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
LOG_DIR = os.path.join(ROOT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

POPEN_KWARGS = {}
if sys.platform == "win32":
    POPEN_KWARGS["creationflags"] = 0x00000008 | 0x00000200
else:
    POPEN_KWARGS["start_new_session"] = True


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def wait_healthy(url: str, name: str, timeout_sec: int = 25) -> bool:
    print(f"    -> Waiting for {name} readiness at {url}...", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DemoLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if 200 <= resp.status < 400:
                    elapsed = round(time.time() - t0, 1)
                    print(f" [HEALTHY in {elapsed}s]")
                    return True
        except Exception:
            time.sleep(1.0)
            print(".", end="", flush=True)
    print(f" [FAILED / TIMEOUT after {timeout_sec}s]")
    return False


def main():
    parser = argparse.ArgumentParser(description="Smart Health Monitoring System Demo Launcher")
    parser.add_argument("--preflight-only", action="store_true", help="Run preflight check only without starting services")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the browser")
    parser.add_argument("--no-streamlit", action="store_true", help="Skip starting Streamlit analytics dashboard")
    parser.add_argument("--timeout", type=int, default=25, help="Readiness probe timeout in seconds")
    args = parser.parse_args()

    print("==================================================================")
    print("SMART HEALTH MONITORING SYSTEM — DEMO LAUNCHER (PYTHON RUNNER)")
    print(f"Working Directory : {ROOT_DIR}")
    print("==================================================================")

    if args.preflight_only:
        print("\n[*] Invoking Preflight Diagnostics (--preflight-only)...")
        from scripts.preflight_check import run_preflight
        success = run_preflight(live_checks=True)
        sys.exit(0 if success else 1)

    # 1. Simulator Microservice (:8001)
    print("\n[*] Phase 1: Orchestrating Smartwatch Simulator (Port 8001)...")
    sim_healthy = False
    if is_port_in_use(8001):
        print("    [INFO] Port 8001 listening. Testing health...")
        sim_healthy = wait_healthy("http://127.0.0.1:8001/health", "Simulator", timeout_sec=5)
        if sim_healthy:
            print("    [OK] Reusing existing healthy simulator microservice.")

    if not sim_healthy:
        out_f = open(os.path.join(LOG_DIR, "simulator.log"), "a", encoding="utf-8")
        err_f = open(os.path.join(LOG_DIR, "simulator_err.log"), "a", encoding="utf-8")
        cmd = [sys.executable, "-m", "uvicorn", "simulator.main:app", "--host", "127.0.0.1", "--port", "8001"]
        subprocess.Popen(cmd, cwd=ROOT_DIR, stdout=out_f, stderr=err_f, **POPEN_KWARGS)
        sim_healthy = wait_healthy("http://127.0.0.1:8001/health", "Simulator", timeout_sec=args.timeout)
        if not sim_healthy:
            print("    [ERROR] Simulator failed to respond on port 8001.")
            sys.exit(1)

    # Enforce default stopped state
    try:
        req = urllib.request.Request("http://127.0.0.1:8001/api/v1/simulator/stop", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            pass
        print("    [OK] Verified Simulator is in clean STOPPED state.")
    except Exception as exc:
        print(f"    [WARN] Could not verify simulator stop: {exc}")

    # 2. FastAPI Backend Gateway (:8000)
    print("\n[*] Phase 2: Orchestrating FastAPI Backend Gateway (Port 8000)...")
    api_healthy = False
    if is_port_in_use(8000):
        print("    [INFO] Port 8000 listening. Testing health...")
        api_healthy = wait_healthy("http://127.0.0.1:8000/api/v1/health", "FastAPI Backend", timeout_sec=5)
        if api_healthy:
            print("    [OK] Reusing existing healthy FastAPI backend service.")

    if not api_healthy:
        out_f = open(os.path.join(LOG_DIR, "backend.log"), "a", encoding="utf-8")
        err_f = open(os.path.join(LOG_DIR, "backend_err.log"), "a", encoding="utf-8")
        cmd = [sys.executable, "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8000"]
        subprocess.Popen(cmd, cwd=ROOT_DIR, stdout=out_f, stderr=err_f, **POPEN_KWARGS)
        api_healthy = wait_healthy("http://127.0.0.1:8000/api/v1/health", "FastAPI Backend", timeout_sec=args.timeout)
        if not api_healthy:
            print("    [ERROR] FastAPI Backend Gateway failed to respond on port 8000.")
            sys.exit(1)

    # 3. React Clinician Workstation (:5173)
    print("\n[*] Phase 3: Orchestrating React Clinician Workstation (Port 5173)...")
    web_healthy = False
    if is_port_in_use(5173):
        print("    [INFO] Port 5173 listening. Testing reachability...")
        web_healthy = wait_healthy("http://127.0.0.1:5173", "React Dashboard", timeout_sec=5)
        if web_healthy:
            print("    [OK] Reusing existing Clinician Workstation instance.")

    if not web_healthy:
        doctor_web_dir = os.path.join(ROOT_DIR, "frontend", "apps", "doctor_web")
        out_f = open(os.path.join(LOG_DIR, "doctor_web.log"), "a", encoding="utf-8")
        err_f = open(os.path.join(LOG_DIR, "doctor_web_err.log"), "a", encoding="utf-8")
        npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"
        subprocess.Popen([npx_cmd, "vite", "--host", "127.0.0.1", "--port", "5173"], cwd=doctor_web_dir, stdout=out_f, stderr=err_f, shell=True, **POPEN_KWARGS)
        web_healthy = wait_healthy("http://127.0.0.1:5173", "React Dashboard", timeout_sec=args.timeout)

    # 4. Streamlit Analytics (:8501, optional)
    if not args.no_streamlit:
        print("\n[*] Phase 4: Orchestrating Streamlit Analytics Visualizer (Port 8501)...")
        st_healthy = False
        if is_port_in_use(8501):
            print("    [INFO] Port 8501 listening. Testing health...")
            st_healthy = wait_healthy("http://localhost:8501/_stcore/health", "Streamlit Dashboard", timeout_sec=5)
            if st_healthy:
                print("    [OK] Reusing existing Streamlit Analytics dashboard.")

        if not st_healthy:
            out_f = open(os.path.join(LOG_DIR, "streamlit.log"), "a", encoding="utf-8")
            err_f = open(os.path.join(LOG_DIR, "streamlit_err.log"), "a", encoding="utf-8")
            cmd = [sys.executable, "-m", "streamlit", "run", "dashboard/app.py", "--server.port", "8501", "--server.headless", "true"]
            subprocess.Popen(cmd, cwd=ROOT_DIR, stdout=out_f, stderr=err_f, **POPEN_KWARGS)
            wait_healthy("http://localhost:8501/_stcore/health", "Streamlit Dashboard", timeout_sec=args.timeout)

    # 5. Run full preflight verification
    print("\n[*] Phase 5: Executing Preflight Verification Suite...")
    from scripts.preflight_check import run_preflight
    success = run_preflight(live_checks=True)

    # 6. Browser launch
    if not args.no_browser:
        print("\n[*] Phase 6: Opening Clinician Workstation in browser...")
        webbrowser.open("http://127.0.0.1:5173")

    # 7. Summary
    print("\n==================================================================")
    print("LIVE DEMONSTRATION ENVIRONMENT READY & VERIFIED")
    print("==================================================================")
    print("  Clinician Portal : http://127.0.0.1:5173 (doctor@hospital.org / DoctorPassword123!)")
    print("  FastAPI Docs     : http://127.0.0.1:8000/docs")
    print("  Simulator Status : http://127.0.0.1:8001/api/v1/simulator/status")
    if not args.no_streamlit:
        print("  Streamlit Visual : http://localhost:8501")
    print("\nShutdown Command (PowerShell): powershell -ExecutionPolicy Bypass -File scripts\\stop_demo.ps1")
    print("==================================================================")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
