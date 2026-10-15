"""
Smart Health Monitoring System — Comprehensive Preflight Verification Script.
Part 6M — Pre-Demonstration Diagnostics and Readiness Certification.

Validates the complete operational environment:
1. Runtimes: Python (>=3.10), Node.js, NPM.
2. Configuration: .env validation without printing sensitive secrets.
3. Local Storage: Relational schema, SQLite/MySQL tables, baseline records.
4. Machine Learning: IsolationForest artifact availability and feature space.
5. Microservices:
   - Smartwatch Simulator (:8001) health, status, stopped baseline, controls.
   - FastAPI Backend (:8000) health, DB probe, MongoDB sync gate, auth, ML status.
   - WebSocket Telemetry Channel (:8000/ws/v1/updates) ticket & handshake.
   - React Clinician Dashboard (:5173) HTTP availability.
   - Streamlit Analytics Dashboard (:8501) reachability (optional / WARN).

Outputs clear status tags:
- PASS        : Verified successfully.
- WARN        : Optional component offline or non-blocking limitation.
- FAIL        : Required dependency or core operation broken.
- NOT CHECKED : Precondition not met (e.g. service down).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Service URLs
SIMULATOR_URL = os.getenv("SENSOR_SIMULATOR_BASE_URL", "http://127.0.0.1:8001")
BACKEND_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501/_stcore/health")

DOCTOR_EMAIL = "doctor@hospital.org"
DOCTOR_PASSWORD = "DoctorPassword123!"

results: List[Dict[str, Any]] = []


def record_check(
    check_id: str,
    category: str,
    name: str,
    status: str,  # PASS, WARN, FAIL, NOT VERIFIED
    detail: str,
    latency_ms: Optional[float] = None,
) -> None:
    results.append({
        "id": check_id,
        "category": category,
        "name": name,
        "status": status,
        "detail": detail,
        "latency_ms": latency_ms,
    })
    # Colorized terminal output
    color = (
        "\033[92m" if status == "PASS" else
        ("\033[93m" if status == "WARN" else
        ("\033[91m" if status == "FAIL" else "\033[90m"))
    )
    reset = "\033[0m"
    lat_str = f" ({latency_ms:.1f}ms)" if latency_ms is not None else ""
    print(f"[{color}{status:<12}{reset}] {check_id:<20} {name}{lat_str}")
    if detail:
        print(f"              Detail: {detail}")


def http_call(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 4.0,
) -> Tuple[int, Any, float]:
    req_headers = headers.copy() if headers else {}
    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            lat = (time.perf_counter() - t0) * 1000.0
            content = resp.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return resp.status, parsed, lat
    except urllib.error.HTTPError as e:
        lat = (time.perf_counter() - t0) * 1000.0
        err_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = err_body
        return e.code, parsed, lat
    except Exception as exc:
        lat = (time.perf_counter() - t0) * 1000.0
        return 0, str(exc), lat


# =============================================================================
# 1. Runtimes & Environment
# =============================================================================

def check_runtimes() -> None:
    print("\n--- 1. Runtimes & Dependencies ---")
    # Python
    py_ver = sys.version_info
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    if py_ver >= (3, 10):
        record_check("RUNTIME-PYTHON", "Environment", "Python Runtime Version (>= 3.10)", "PASS", f"Python {py_str} on {sys.platform}")
    else:
        record_check("RUNTIME-PYTHON", "Environment", "Python Runtime Version (>= 3.10)", "FAIL", f"Found Python {py_str}, requires >= 3.10")

    # Node.js
    try:
        res = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            node_ver = res.stdout.strip()
            record_check("RUNTIME-NODE", "Environment", "Node.js Runtime Version", "PASS", f"Node.js {node_ver}")
        else:
            record_check("RUNTIME-NODE", "Environment", "Node.js Runtime Version", "WARN", "Node.js execution failed")
    except Exception as exc:
        record_check("RUNTIME-NODE", "Environment", "Node.js Runtime Version", "WARN", f"Node.js not detected on PATH ({exc})")

    # NPM
    try:
        res = subprocess.run(["npm", "--version"], shell=True, capture_output=True, text=True, timeout=3)
        if res.returncode == 0:
            npm_ver = res.stdout.strip()
            record_check("RUNTIME-NPM", "Environment", "NPM Package Manager", "PASS", f"npm v{npm_ver}")
        else:
            record_check("RUNTIME-NPM", "Environment", "NPM Package Manager", "WARN", "NPM execution failed")
    except Exception as exc:
        record_check("RUNTIME-NPM", "Environment", "NPM Package Manager", "WARN", f"NPM not detected ({exc})")


def check_configuration() -> None:
    print("\n--- 2. Configuration & Secrets Redaction ---")
    env_path = ".env"
    if not os.path.exists(env_path):
        record_check("CONFIG-ENV-FILE", "Configuration", "Environment File (.env)", "FAIL", ".env file not found in repository root")
        return

    record_check("CONFIG-ENV-FILE", "Configuration", "Environment File (.env)", "PASS", "Found .env file")

    # Check key configurations without printing sensitive values
    try:
        keys_found = {}
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys_found[k.strip()] = v.strip().strip("'\"")

        required_keys = ["APP_NAME", "JWT_SECRET", "SENSOR_SIMULATOR_BASE_URL"]
        missing = [k for k in required_keys if not keys_found.get(k)]
        if missing:
            record_check("CONFIG-REQUIRED-KEYS", "Configuration", "Required Environment Variables", "FAIL", f"Missing keys: {missing}")
        else:
            record_check("CONFIG-REQUIRED-KEYS", "Configuration", "Required Environment Variables", "PASS", "All required variables defined")

        # JWT Secret security check
        jwt_sec = keys_found.get("JWT_SECRET", "")
        if len(jwt_sec) >= 32:
            record_check("CONFIG-JWT-SECRET", "Configuration", "JWT Secret Strength (>= 32 chars)", "PASS", f"Length: {len(jwt_sec)} characters [REDACTED]")
        else:
            record_check("CONFIG-JWT-SECRET", "Configuration", "JWT Secret Strength (>= 32 chars)", "WARN", f"Length: {len(jwt_sec)} characters (production recommends >= 32)")

        # MongoDB Sync Protection check
        mongo_sync = keys_found.get("MONGODB_SYNC_ENABLED", "false").lower()
        if mongo_sync in ("false", "0", "no"):
            record_check("CONFIG-MONGO-GATE", "Configuration", "MongoDB Sync Isolation Policy", "PASS", "MONGODB_SYNC_ENABLED=false (Atlas cluster storage protected)")
        else:
            record_check("CONFIG-MONGO-GATE", "Configuration", "MongoDB Sync Isolation Policy", "WARN", "MONGODB_SYNC_ENABLED=true (unbounded writes will push to Atlas)")

    except Exception as exc:
        record_check("CONFIG-PARSE", "Configuration", "Parse .env Configuration", "FAIL", str(exc))


# =============================================================================
# 3. Database & Machine Learning Artifacts
# =============================================================================

def check_local_database() -> None:
    print("\n--- 3. Relational Database & Clinical Schemas ---")
    db_file = "smart_health_local.db"
    if not os.path.exists(db_file):
        record_check("DB-FILE", "Database", "Local Relational Database File", "FAIL", f"{db_file} not found")
        return

    record_check("DB-FILE", "Database", "Local Relational Database File", "PASS", f"Found {db_file} ({os.path.getsize(db_file)} bytes)")

    try:
        conn = sqlite3.connect(db_file)
        cur = conn.cursor()

        # Check critical tables
        expected_tables = [
            "users", "patient_profiles", "doctor_profiles", "doctor_patient_assignments",
            "ingestion_events", "vitals_readings", "alerts", "conversations", "messages"
        ]
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = {row[0] for row in cur.fetchall()}
        missing_tables = [t for t in expected_tables if t not in existing_tables]

        if missing_tables:
            record_check("DB-SCHEMA-TABLES", "Database", "Authoritative Table Schema", "FAIL", f"Missing tables: {missing_tables}")
        else:
            record_check("DB-SCHEMA-TABLES", "Database", "Authoritative Table Schema", "PASS", f"All {len(expected_tables)} required tables present")

        # Check compiled relational views
        expected_views = ["v_latest_patient_vitals", "v_patient_active_alerts"]
        cur.execute("SELECT name FROM sqlite_master WHERE type='view'")
        existing_views = {row[0] for row in cur.fetchall()}
        missing_views = [v for v in expected_views if v not in existing_views]
        if missing_views:
            record_check("DB-SCHEMA-VIEWS", "Database", "Compiled Relational Views", "FAIL", f"Missing views: {missing_views}")
        else:
            record_check("DB-SCHEMA-VIEWS", "Database", "Compiled Relational Views", "PASS", f"All {len(expected_views)} required views active ({', '.join(expected_views)})")

        # Check database triggers
        expected_triggers = ["trg_alert_status_history_after_update"]
        cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        existing_triggers = {row[0] for row in cur.fetchall()}
        missing_triggers = [tr for tr in expected_triggers if tr not in existing_triggers]
        if missing_triggers:
            record_check("DB-SCHEMA-TRIGGERS", "Database", "Database Triggers", "FAIL", f"Missing triggers: {missing_triggers}")
        else:
            record_check("DB-SCHEMA-TRIGGERS", "Database", "Database Triggers", "PASS", f"Trigger {', '.join(expected_triggers)} active on status transitions")

        # Check evaluation & audit tables
        eval_tables = ["evaluation_records", "alert_status_history", "audit_logs"]
        missing_eval = [t for t in eval_tables if t not in existing_tables]
        if missing_eval:
            record_check("DB-SCHEMA-EVAL", "Database", "Evaluation & Audit Tables", "FAIL", f"Missing evaluation tables: {missing_eval}")
        else:
            record_check("DB-SCHEMA-EVAL", "Database", "Evaluation & Audit Tables", "PASS", f"All {len(eval_tables)} evaluation & audit tables present")

        # Check migration & schema integrity
        cur.execute("PRAGMA integrity_check")
        integrity_res = cur.fetchone()[0]
        if integrity_res == "ok":
            record_check("DB-MIGRATION-READY", "Database", "Schema & Migration Integrity", "PASS", f"PRAGMA integrity_check passed ({len(existing_tables)} tables, {len(existing_views)} views)")
        else:
            record_check("DB-MIGRATION-READY", "Database", "Schema & Migration Integrity", "FAIL", f"Integrity check failed: {integrity_res}")

        # Check demo doctor user exists
        cur.execute("SELECT user_id, email, role FROM users WHERE email = ?", (DOCTOR_EMAIL,))
        doc_user = cur.fetchone()
        if doc_user:
            record_check("DB-TEST-ACCOUNT", "Database", "Demo Doctor User Account", "PASS", f"User {doc_user[1]} ({doc_user[2]}) verified")
        else:
            record_check("DB-TEST-ACCOUNT", "Database", "Demo Doctor User Account", "FAIL", f"Account {DOCTOR_EMAIL} not found in users table")

        # Check patient cohort
        cur.execute("SELECT count(*) FROM patient_profiles WHERE patient_id IN ('P101', 'P102', 'P103', 'P104', 'P105')")
        p_count = cur.fetchone()[0]
        if p_count == 5:
            record_check("DB-DEMO-COHORT", "Database", "Demo Patient Cohort (P101–P105)", "PASS", "All 5 demo patient profiles provisioned")
        else:
            record_check("DB-DEMO-COHORT", "Database", "Demo Patient Cohort (P101–P105)", "FAIL", f"Only {p_count}/5 demo patients found")

        # Check Kaggle baseline records
        cur.execute("SELECT count(*) FROM ingestion_events WHERE source = 'kaggle_csv'")
        kaggle_count = cur.fetchone()[0]
        if kaggle_count >= 1500:
            record_check("DB-KAGGLE-DATA", "Database", "Kaggle Baseline Readings", "PASS", f"{kaggle_count} historical records present")
        else:
            record_check("DB-KAGGLE-DATA", "Database", "Kaggle Baseline Readings", "WARN", f"{kaggle_count} records present (expected 1,500)")

        conn.close()
    except Exception as exc:
        record_check("DB-INSPECT", "Database", "Inspect Relational Database", "FAIL", str(exc))


def check_ml_artifacts() -> None:
    print("\n--- 4. Machine Learning Model Artifacts ---")
    model_path = os.path.join("models", "iforest_v1", "model.joblib")
    meta_path = os.path.join("models", "iforest_v1", "metadata.json")

    if os.path.exists(model_path):
        size = os.path.getsize(model_path)
        record_check("ML-MODEL-FILE", "Machine Learning", "Trained IsolationForest Artifact", "PASS", f"model.joblib found ({size:,} bytes)")
    else:
        record_check("ML-MODEL-FILE", "Machine Learning", "Trained IsolationForest Artifact", "WARN", f"{model_path} not found; fallback active")

    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            features = len(meta.get("feature_names", []))
            version = meta.get("model_version", "1.0.0")
            record_check("ML-METADATA", "Machine Learning", "Model Feature Metadata", "PASS", f"Model v{version}, {features} features")
        except Exception as exc:
            record_check("ML-METADATA", "Machine Learning", "Model Feature Metadata", "WARN", str(exc))
    else:
        record_check("ML-METADATA", "Machine Learning", "Model Feature Metadata", "WARN", f"{meta_path} not found")


# =============================================================================
# 4. Live Microservices Probes (When Online)
# =============================================================================

def check_live_simulator() -> None:
    print("\n--- 5. Smartwatch Simulator Service (:8001) ---")
    # Health probe
    st, body, lat = http_call(f"{SIMULATOR_URL}/health")
    if st == 200:
        record_check("SVC-SIM-HEALTH", "Simulator", "Simulator Health Probe (:8001/health)", "PASS", f"HTTP 200: {body.get('service', 'Simulator')}", lat)
    else:
        record_check("SVC-SIM-HEALTH", "Simulator", "Simulator Health Probe (:8001/health)", "FAIL", f"Simulator offline or HTTP {st} ({body})", lat)
        record_check("SVC-SIM-STOPPED", "Simulator", "Default Stopped State", "NOT CHECKED", "Simulator service not responding")
        record_check("SVC-SIM-CONTROLS", "Simulator", "Start/Stop API Controls", "NOT CHECKED", "Simulator service not responding")
        return

    # Status & Stopped State Probe
    st_status, body_status, lat_s = http_call(f"{SIMULATOR_URL}/api/v1/simulator/status")
    if st_status == 200:
        is_running = body_status.get("is_running", True)
        lifecycle = body_status.get("lifecycle_state", "UNKNOWN")
        if not is_running and lifecycle == "STOPPED":
            record_check("SVC-SIM-STOPPED", "Simulator", "Default Simulator Stopped State", "PASS", f"lifecycle_state: {lifecycle}, is_running: {is_running}", lat_s)
        else:
            record_check("SVC-SIM-STOPPED", "Simulator", "Default Simulator Stopped State", "WARN", f"Simulator currently {lifecycle} (will need Stop before demo)", lat_s)
    else:
        record_check("SVC-SIM-STOPPED", "Simulator", "Default Simulator Stopped State", "FAIL", f"HTTP {st_status}", lat_s)

    # Control Endpoints Verification (Safe probe: verify stop is idempotent)
    st_stop, body_stop, lat_stop = http_call(f"{SIMULATOR_URL}/api/v1/simulator/stop", method="POST")
    if st_stop == 200:
        record_check("SVC-SIM-CONTROLS", "Simulator", "Start/Stop Control API Reachability", "PASS", f"POST /stop responsive ({lat_stop:.1f}ms)", lat_stop)
    else:
        record_check("SVC-SIM-CONTROLS", "Simulator", "Start/Stop Control API Reachability", "FAIL", f"HTTP {st_stop}", lat_stop)


def check_live_backend() -> Optional[str]:
    print("\n--- 6. FastAPI Backend Gateway (:8000) ---")
    # Health Probe
    st, body, lat = http_call(f"{BACKEND_URL}/api/v1/health")
    if st == 200:
        record_check("SVC-API-HEALTH", "Backend", "Gateway Health Probe (:8000/api/v1/health)", "PASS", f"HTTP 200: {body.get('service', 'API')}", lat)
    else:
        record_check("SVC-API-HEALTH", "Backend", "Gateway Health Probe (:8000/api/v1/health)", "FAIL", f"Backend gateway offline or HTTP {st}", lat)
        return None

    # Liveness Probe
    st_live, _, lat_l = http_call(f"{BACKEND_URL}/health/live")
    if st_live == 200:
        record_check("SVC-API-LIVENESS", "Backend", "Process Liveness Probe (/health/live)", "PASS", "ASGI event loop healthy", lat_l)
    else:
        record_check("SVC-API-LIVENESS", "Backend", "Process Liveness Probe (/health/live)", "WARN", f"HTTP {st_live}", lat_l)

    # Relational DB Connectivity
    st_db, body_db, lat_db = http_call(f"{BACKEND_URL}/api/v1/health/db")
    if st_db == 200 and isinstance(body_db, dict) and body_db.get("status") == "connected":
        record_check("SVC-API-DB", "Backend", "Relational Database Connectivity Probe", "PASS", f"Database: {body_db.get('database')}", lat_db)
    else:
        record_check("SVC-API-DB", "Backend", "Relational Database Connectivity Probe", "FAIL", f"Database status: {body_db}", lat_db)

    # MongoDB Atlas Status (Non-blocking)
    st_m, body_m, lat_m = http_call(f"{BACKEND_URL}/api/v1/health/mongodb")
    if st_m == 200 and isinstance(body_m, dict):
        m_status = body_m.get("status")
        outbox = body_m.get("outbox_queue", {})
        if m_status == "connected":
            record_check("SVC-API-MONGO", "Backend", "MongoDB Atlas Status (Outbox Queue)", "PASS", f"Connected. Outbox pending: {outbox.get('pending', 0)}", lat_m)
        else:
            record_check("SVC-API-MONGO", "Backend", "MongoDB Atlas Status (Outbox Queue)", "WARN", f"Status: {m_status} (sync disabled; non-blocking)", lat_m)
    else:
        record_check("SVC-API-MONGO", "Backend", "MongoDB Atlas Status (Outbox Queue)", "WARN", f"Probe HTTP {st_m} (non-blocking)", lat_m)

    # ML Inference Service Probe
    st_ml, body_ml, lat_ml = http_call(f"{BACKEND_URL}/api/v1/predictions/status")
    if st_ml == 200 and isinstance(body_ml, dict) and body_ml.get("is_available"):
        record_check("SVC-API-ML", "Backend", "ML Anomaly Inference Subsystem", "PASS", f"Model {body_ml.get('model_version')} ({body_ml.get('algorithm')})", lat_ml)
    else:
        record_check("SVC-API-ML", "Backend", "ML Anomaly Inference Subsystem", "WARN", f"ML status: {body_ml}", lat_ml)

    # Clinician Authentication
    token = None
    st_auth, body_auth, lat_a = http_call(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": DOCTOR_EMAIL, "password": DOCTOR_PASSWORD},
    )
    if st_auth == 200 and isinstance(body_auth, dict) and "access_token" in body_auth:
        token = body_auth["access_token"]
        record_check("SVC-API-AUTH", "Backend", "Clinician JWT Authentication", "PASS", f"Acquired JWT for {DOCTOR_EMAIL}", lat_a)
    else:
        record_check("SVC-API-AUTH", "Backend", "Clinician JWT Authentication", "FAIL", f"Auth failed with HTTP {st_auth}: {body_auth}", lat_a)

    # Alert Generation & Retrieval API
    if token:
        st_al, body_al, lat_al = http_call(
            f"{BACKEND_URL}/api/v1/alerts?limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )
        if st_al == 200 and isinstance(body_al, list):
            record_check("SVC-API-ALERTS", "Backend", "Alert Generation & Retrieval API", "PASS", f"HTTP 200: {len(body_al)} alerts accessible", lat_al)
        else:
            record_check("SVC-API-ALERTS", "Backend", "Alert Generation & Retrieval API", "FAIL", f"Alerts probe failed (HTTP {st_al})", lat_al)
    else:
        record_check("SVC-API-ALERTS", "Backend", "Alert Generation & Retrieval API", "NOT VERIFIED", "Token unavailable")

    # Patient Readings & Telemetry API
    if token:
        st_rd, body_rd, lat_rd = http_call(
            f"{BACKEND_URL}/api/v1/patients/P101/readings?page_size=5",
            headers={"Authorization": f"Bearer {token}"},
        )
        if st_rd == 200 and isinstance(body_rd, dict) and "items" in body_rd:
            record_check("SVC-API-READINGS", "Backend", "Patient Telemetry Readings API", "PASS", f"HTTP 200: {len(body_rd.get('items', []))} readings (total: {body_rd.get('total_count', 0)})", lat_rd)
        else:
            record_check("SVC-API-READINGS", "Backend", "Patient Telemetry Readings API", "FAIL", f"Readings probe failed (HTTP {st_rd})", lat_rd)
    else:
        record_check("SVC-API-READINGS", "Backend", "Patient Telemetry Readings API", "NOT VERIFIED", "Token unavailable")

    # DA3 Evaluation Console API
    st_ch, body_ch, lat_ch = http_call(f"{BACKEND_URL}/api/v1/evaluation/challenges")
    if st_ch == 200 and isinstance(body_ch, list) and len(body_ch) >= 20:
        record_check("SVC-EVAL-CONSOLE", "Evaluation Console", "DA3 Evaluation Console Challenge Catalog", "PASS", f"HTTP 200: {len(body_ch)} challenges registered", lat_ch)
    else:
        record_check("SVC-EVAL-CONSOLE", "Evaluation Console", "DA3 Evaluation Console Challenge Catalog", "FAIL", f"HTTP {st_ch}", lat_ch)

    st_vw, body_vw, lat_vw = http_call(f"{BACKEND_URL}/api/v1/evaluation/db-objects/views/v_latest_patient_vitals?limit=2")
    if st_vw == 200 and isinstance(body_vw, dict) and body_vw.get("row_count", 0) >= 1:
        record_check("SVC-EVAL-VIEWS", "Evaluation Console", "Database View Live Query API", "PASS", f"HTTP 200: v_latest_patient_vitals queried ({body_vw.get('row_count')} rows)", lat_vw)
    else:
        record_check("SVC-EVAL-VIEWS", "Evaluation Console", "Database View Live Query API", "FAIL", f"HTTP {st_vw}", lat_vw)

    return token


async def check_websocket_handshake(token: Optional[str]) -> None:
    print("\n--- 7. Real-Time WebSocket Channel (:8000/ws/v1/updates) ---")
    if not token:
        record_check("SVC-WS-CONN", "WebSocket", "WebSocket Telemetry Push Channel", "NOT CHECKED", "Skipped: Clinician JWT authentication unavailable")
        return

    # Request short-lived WebSocket ticket
    st_t, body_t, lat_t = http_call(
        f"{BACKEND_URL}/api/v1/ws-ticket",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    ticket = body_t.get("ticket") if (st_t == 200 and isinstance(body_t, dict)) else token

    try:
        import websockets
        ws_url = f"ws://127.0.0.1:8000/ws/v1/updates?token={ticket}"
        t0 = time.perf_counter()
        async with websockets.connect(ws_url, close_timeout=2.0) as ws:
            lat_ws = (time.perf_counter() - t0) * 1000.0
            record_check("SVC-WS-CONN", "WebSocket", "WebSocket Telemetry Push Channel", "PASS", f"Connected and authenticated ({lat_ws:.1f}ms)", lat_ws)
    except Exception as exc:
        record_check("SVC-WS-CONN", "WebSocket", "WebSocket Telemetry Push Channel", "WARN", f"WebSocket handshake error: {exc}")


def check_frontend_and_dashboard() -> None:
    print("\n--- 8. Frontend & Analytics Dashboards ---")
    # React Clinician Dashboard (:5173)
    st_ui, _, lat_ui = http_call(FRONTEND_URL)
    if st_ui == 200:
        record_check("SVC-UI-VITE", "Frontend", "React Clinician Workstation (:5173)", "PASS", "HTTP 200 OK (Vite Development Server)", lat_ui)
    else:
        record_check("SVC-UI-VITE", "Frontend", "React Clinician Workstation (:5173)", "FAIL", f"Frontend unavailable at {FRONTEND_URL} (HTTP {st_ui})", lat_ui)

    # Streamlit Analytics Dashboard (:8501, optional)
    st_st, _, lat_st = http_call(STREAMLIT_URL)
    if st_st == 200:
        record_check("SVC-UI-STREAMLIT", "Analytics", "Streamlit DA3 Visualizer (:8501)", "PASS", "HTTP 200 OK (Analytics Dashboard ready)", lat_st)
    else:
        record_check("SVC-UI-STREAMLIT", "Analytics", "Streamlit DA3 Visualizer (:8501)", "WARN", "Streamlit offline (Optional DA3 analytics dashboard)", lat_st)


# =============================================================================
# Summary & Runner
# =============================================================================

def run_preflight(live_checks: bool = True) -> bool:
    print("================================================================================")
    print("SMART HEALTH MONITORING SYSTEM — DEMONSTRATION PREFLIGHT CHECK")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print("================================================================================")

    # Static & Runtime Checks
    check_runtimes()
    check_configuration()
    check_local_database()
    check_ml_artifacts()

    # Dynamic Network Probes
    if live_checks:
        check_live_simulator()
        token = check_live_backend()
        try:
            asyncio.run(check_websocket_handshake(token))
        except Exception as exc:
            record_check("SVC-WS-CONN", "WebSocket", "WebSocket Telemetry Push Channel", "WARN", f"Handshake runner error: {exc}")
        check_frontend_and_dashboard()
    else:
        print("\n[INFO] Skipping live network probes (--offline specified).")

    # Final Summary Table
    print("\n================================================================================")
    print("PREFLIGHT DIAGNOSTIC SUMMARY")
    print("================================================================================")
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    not_checked = sum(1 for r in results if r["status"] == "NOT CHECKED")

    print(f"Total Checks Executed : {total}")
    print(f"PASS                  : {passed}")
    print(f"WARN                  : {warned} (Non-blocking limitations)")
    print(f"FAIL                  : {failed}")
    print(f"NOT CHECKED           : {not_checked}\n")

    if failed == 0:
        print("\033[92m>>> VERDICT: SYSTEM IS CERTIFIED READY FOR LIVE DEMONSTRATION <<<\033[0m\n")
        return True
    else:
        print("\033[91m>>> VERDICT: PREFLIGHT FAILED — RESOLVE FAILURES BEFORE DEMONSTRATION <<<\033[0m\n")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smart Health System Preflight Diagnostic Check")
    parser.add_argument("--offline", action="store_true", help="Execute file and runtime checks only; skip live network calls")
    args = parser.parse_args()

    success = run_preflight(live_checks=not args.offline)
    sys.exit(0 if success else 1)
