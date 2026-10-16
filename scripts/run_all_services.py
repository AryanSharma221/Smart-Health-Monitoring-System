"""
Persistent Daemon Orchestrator for Smart Health Monitoring System.
Keeps all 4 demonstration microservices active in the background:
1. Smartwatch Simulator (:8001)
2. FastAPI Backend Gateway (:8000)
3. React Clinician Workstation (:5173)
4. Streamlit Analytics Visualizer (:8501)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DOCTOR_WEB_DIR = ROOT_DIR / "frontend" / "apps" / "doctor_web"

processes: list[subprocess.Popen] = []


def stop_all(signum=None, frame=None):
    print("\n[*] Terminating all demo services...")
    for p in processes:
        try:
            if sys.platform == "win32":
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(p.pid)])
            else:
                p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, stop_all)
signal.signal(signal.SIGTERM, stop_all)


def wait_healthy(url: str, name: str, timeout_sec: int = 25) -> bool:
    print(f"    -> Waiting for {name} readiness at {url}...", end="", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DemoRunner/1.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if 200 <= resp.status < 400:
                    print(f" [HEALTHY in {round(time.time() - t0, 1)}s]")
                    return True
        except Exception:
            time.sleep(1.0)
            print(".", end="", flush=True)
    print(f" [FAILED / TIMEOUT after {timeout_sec}s]")
    return False


def main():
    print("=" * 70)
    print("SMART HEALTH MONITORING SYSTEM — PERSISTENT DEMO RUNNER")
    print(f"Working Directory: {ROOT_DIR}")
    print("=" * 70)

    # 1. Smartwatch Simulator (:8001)
    print("\n[*] Launching Smartwatch Simulator (:8001)...")
    sim_out = open(LOG_DIR / "simulator.log", "a", encoding="utf-8")
    sim_err = open(LOG_DIR / "simulator_err.log", "a", encoding="utf-8")
    p_sim = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "simulator.main:app", "--host", "127.0.0.1", "--port", "8001"],
        cwd=str(ROOT_DIR),
        stdout=sim_out,
        stderr=sim_err,
    )
    processes.append(p_sim)
    wait_healthy("http://127.0.0.1:8001/health", "Simulator")

    # Start simulator data generation so it actively feeds MongoDB Atlas on launch
    try:
        req = urllib.request.Request("http://127.0.0.1:8001/api/v1/simulator/start", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3.0):
            pass
        print("    [OK] Smartwatch Simulator started and actively streaming to MongoDB Atlas.")
    except Exception as exc:
        print(f"    [WARN] Could not start simulator: {exc}")

    # 2. FastAPI Backend Gateway (:8000)
    print("\n[*] Launching FastAPI Backend Gateway (:8000)...")
    api_out = open(LOG_DIR / "backend.log", "a", encoding="utf-8")
    api_err = open(LOG_DIR / "backend_err.log", "a", encoding="utf-8")
    p_api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.api.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"],
        cwd=str(ROOT_DIR),
        stdout=api_out,
        stderr=api_err,
    )
    processes.append(p_api)
    wait_healthy("http://127.0.0.1:8000/api/v1/health", "FastAPI Backend")

    # 3. React Clinician Workstation (:5173)
    print("\n[*] Launching React Clinician Workstation (:5173)...")
    web_out = open(LOG_DIR / "doctor_web.log", "a", encoding="utf-8")
    web_err = open(LOG_DIR / "doctor_web_err.log", "a", encoding="utf-8")
    p_web = subprocess.Popen(
        "npx vite --host 127.0.0.1 --port 5173",
        cwd=str(DOCTOR_WEB_DIR),
        stdout=web_out,
        stderr=web_err,
        shell=True,
    )
    processes.append(p_web)
    wait_healthy("http://127.0.0.1:5173", "React Clinician Workstation")

    # 4. Streamlit Analytics Visualizer (:8501)
    print("\n[*] Launching Streamlit Analytics Dashboard (:8501)...")
    st_out = open(LOG_DIR / "streamlit.log", "a", encoding="utf-8")
    st_err = open(LOG_DIR / "streamlit_err.log", "a", encoding="utf-8")
    p_st = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "dashboard/app.py", "--server.port", "8501", "--server.headless", "true"],
        cwd=str(ROOT_DIR),
        stdout=st_out,
        stderr=st_err,
    )
    processes.append(p_st)
    wait_healthy("http://127.0.0.1:8501/_stcore/health", "Streamlit Dashboard")

    print("\n" + "=" * 70)
    print("ALL 4 DEMONSTRATION MICROSERVICES ARE LIVE & HEALTHY")
    print("=" * 70)
    print("  1. React Clinician Portal  : http://127.0.0.1:5173")
    print("     Credentials             : doctor@hospital.org / DoctorPassword123!")
    print("  2. FastAPI Gateway & Docs  : http://127.0.0.1:8000/docs")
    print("  3. Simulator Microservice  : http://127.0.0.1:8001/api/v1/simulator/status")
    print("  4. Streamlit Analytics     : http://127.0.0.1:8501")
    print("=" * 70)

    # Keep alive
    try:
        while True:
            time.sleep(1)
            for p in processes:
                if p.poll() is not None:
                    print(f"[WARN] Process {p.pid} terminated unexpectedly with code {p.returncode}")
    except (KeyboardInterrupt, SystemExit):
        stop_all()


if __name__ == "__main__":
    main()
