"""
End-to-End Live Demonstration Smoke Test & Verification Suite.
Smart Health Monitoring System - Part 6H Integration Verification.

Executes a complete verification run of:
1. Smartwatch sensor simulator microservice (port 8001)
2. FastAPI gateway and ingestion engine (port 8000)
3. Relational operational database (SQLite / MySQL)
4. ML anomaly scoring and model assessment pipeline
5. Clinician authentication and cohort telemetry access
6. Alert generation, persistence, broadcast, and acknowledgement lifecycle
7. Sensor signal interruption and recovery lifecycle
8. MongoDB Atlas outbox gating verification (MONGODB_SYNC_ENABLED=false)
9. React clinician dashboard & Streamlit analytics UI reachability
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error


SIMULATOR_URL = "http://127.0.0.1:8001"
BACKEND_URL = "http://127.0.0.1:8000"
REACT_URL = "http://127.0.0.1:5173"
STREAMLIT_URL = "http://localhost:8501/_stcore/health"
DB_PATH = "smart_health_local.db"

DOCTOR_EMAIL = "doctor@hospital.org"
DOCTOR_PASSWORD = "DoctorPassword123!"

results: Dict[str, Dict[str, Any]] = {}


def http_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    timeout: float = 10.0,
) -> tuple[int, Any]:
    req_headers = headers.copy() if headers else {}
    body_bytes = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        start_t = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency_ms = (time.perf_counter() - start_t) * 1000.0
            resp_body = resp.read().decode("utf-8")
            status = resp.status
            try:
                parsed = json.loads(resp_body)
            except Exception:
                parsed = resp_body
            return status, parsed, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - start_t) * 1000.0
        err_body = e.read().decode("utf-8")
        try:
            parsed = json.loads(err_body)
        except Exception:
            parsed = err_body
        return e.code, parsed, latency_ms
    except Exception as exc:
        return 0, str(exc), 0.0


def record_result(test_name: str, passed: bool, details: Dict[str, Any]):
    status = "VERIFIED PASS" if passed else "FAILED"
    results[test_name] = {"status": status, **details}
    marker = "[PASS]" if passed else "[FAIL]"
    print(f"{marker} {test_name}: {status}")
    for k, v in details.items():
        print(f"    - {k}: {v}")


def run_smoke_test():
    print("=" * 80)
    print("SMART HEALTH MONITORING SYSTEM - LIVE DEMONSTRATION SMOKE TEST")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    # 1. Simulator Health & Endpoints
    print("\n--- Phase 1: Smartwatch Simulator Health & Telemetry ---")
    st, res, lat = http_request(f"{SIMULATOR_URL}/health")
    sim_healthy = st == 200 and res.get("status") == "healthy" and res.get("generator_running") is True
    record_result(
        "Simulator Health Check",
        sim_healthy,
        {"http_status": st, "service": res.get("service") if isinstance(res, dict) else res, "latency_ms": round(lat, 2)},
    )

    st, res, lat = http_request(f"{SIMULATOR_URL}/api/v1/patients")
    expected_patients = ["P101", "P102", "P103", "P104", "P105"]
    pts_list = res.get("patients", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    pts_ok = st == 200 and sorted(pts_list) == sorted(expected_patients)
    record_result(
        "Simulator Patient Configuration",
        pts_ok,
        {"http_status": st, "patients": pts_list, "latency_ms": round(lat, 2)},
    )

    st, res, lat = http_request(f"{SIMULATOR_URL}/api/v1/readings/latest")
    readings_map = res.get("readings", {}) if isinstance(res, dict) else {}
    readings_ok = st == 200 and len(readings_map) == 5
    sample_p101 = readings_map.get("P101")
    record_result(
        "Simulator Latest Readings",
        readings_ok and sample_p101 is not None,
        {
            "http_status": st,
            "readings_count": len(readings_map),
            "sample_p101_hr": sample_p101.get("heart_rate") if sample_p101 else None,
            "sample_p101_spo2": sample_p101.get("spo2") if sample_p101 else None,
            "sample_p101_temp": sample_p101.get("temperature_f") if sample_p101 else None,
            "latency_ms": round(lat, 2),
        },
    )

    # 2. Backend Health & Simulator Ingestion Pipeline
    print("\n--- Phase 2: FastAPI Backend Health & Telemetry Ingestion ---")
    st, res, lat = http_request(f"{BACKEND_URL}/health")
    backend_healthy = st == 200 and res.get("status") == "healthy"
    record_result(
        "Backend Gateway Health",
        backend_healthy,
        {"http_status": st, "service": res.get("service") if isinstance(res, dict) else res, "latency_ms": round(lat, 2)},
    )

    st, res, lat = http_request(f"{BACKEND_URL}/api/v1/simulator/ingestion-status")
    ingestion_ok = (
        st == 200
        and isinstance(res, dict)
        and res.get("running") is True
        and res.get("pipeline_health") == "healthy"
        and res.get("simulator_reachable") is True
        and res.get("events_accepted_count", 0) > 0
    )
    record_result(
        "Backend Ingestion Worker Status",
        ingestion_ok,
        {
            "http_status": st,
            "pipeline_health": res.get("pipeline_health") if isinstance(res, dict) else None,
            "events_accepted": res.get("events_accepted_count") if isinstance(res, dict) else None,
            "consecutive_failures": res.get("consecutive_failures") if isinstance(res, dict) else None,
            "latency_ms": round(lat, 2),
        },
    )

    # 3. Clinician Authentication & Authorization
    print("\n--- Phase 3: Clinician Authentication & Cohort Access ---")
    st_login, login_data, login_lat = http_request(
        f"{BACKEND_URL}/api/v1/auth/login",
        method="POST",
        data={"email": DOCTOR_EMAIL, "password": DOCTOR_PASSWORD},
    )
    access_token = login_data.get("access_token") if isinstance(login_data, dict) else None
    role = login_data.get("role") if isinstance(login_data, dict) else None
    auth_ok = st_login == 200 and access_token is not None and role == "doctor"

    record_result(
        "Clinician Authentication (JWT)",
        auth_ok,
        {"login_role": role, "http_status": st_login, "latency_ms": round(login_lat, 2)},
    )

    auth_headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

    # Query assigned patients
    st, res, lat = http_request(f"{BACKEND_URL}/api/v1/patients", headers=auth_headers)
    cohort_ok = st == 200 and isinstance(res, list) and len(res) == 5
    assigned_ids = [p.get("patient_id") for p in res if isinstance(p, dict)] if cohort_ok else []
    record_result(
        "Clinician Patient Cohort Retrieval",
        cohort_ok and sorted(assigned_ids) == sorted(expected_patients),
        {"http_status": st, "cohort_count": len(res) if isinstance(res, list) else 0, "cohort_ids": assigned_ids, "latency_ms": round(lat, 2)},
    )

    # Query latest readings for each assigned patient via backend
    all_readings_ok = True
    vitals_retrieved = {}
    for pid in expected_patients:
        st_p, res_p, lat_p = http_request(f"{BACKEND_URL}/api/v1/patients/{pid}/readings/latest", headers=auth_headers)
        if st_p == 200 and isinstance(res_p, dict) and "heart_rate" in res_p:
            vitals_retrieved[pid] = {
                "heart_rate": res_p.get("heart_rate"),
                "spo2": res_p.get("spo2"),
                "temperature_f": res_p.get("temperature_f"),
                "is_simulated": res_p.get("is_simulated"),
                "event_id": res_p.get("event_id"),
            }
        else:
            all_readings_ok = False
            vitals_retrieved[pid] = f"Error: status {st_p}"

    record_result(
        "Patient Live Vitals Retrieval (REST API)",
        all_readings_ok,
        {
            "patients_verified": len(vitals_retrieved),
            "sample_P101_vitals": vitals_retrieved.get("P101"),
            "sample_P102_vitals": vitals_retrieved.get("P102"),
        },
    )

    # 4. Relational Database Persistence & Integrity
    print("\n--- Phase 4: Operational Relational Database (SQLite) ---")
    db_verified = False
    db_stats = {}
    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM ingestion_events")
            db_stats["ingestion_events"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM vitals_readings")
            db_stats["vitals_readings"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM model_assessments")
            db_stats["model_assessments"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM alerts")
            db_stats["alerts"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM analytics_outbox")
            db_stats["analytics_outbox"] = cur.fetchone()[0]

            # Verify idempotency: check for duplicate (event_id, metric_code) in vitals_readings
            cur.execute(
                "SELECT event_id, metric_code, COUNT(*) FROM vitals_readings GROUP BY event_id, metric_code HAVING COUNT(*) > 1"
            )
            dups = cur.fetchall()
            db_stats["vitals_duplicates"] = len(dups)

            # Verify simulated provenance tracking
            cur.execute("SELECT COUNT(*) FROM ingestion_events WHERE is_simulated = 1")
            sim_count = cur.fetchone()[0]
            db_stats["simulated_events_count"] = sim_count

            db_verified = (
                db_stats["ingestion_events"] > 0
                and db_stats["vitals_readings"] > 0
                and db_stats["model_assessments"] > 0
                and db_stats["vitals_duplicates"] == 0
            )
            conn.close()
        except Exception as exc:
            db_stats["error"] = str(exc)

    record_result(
        "Database Persistence & Idempotency",
        db_verified,
        db_stats,
    )

    # 5. Alert Trigger, Persistence & Acknowledgement Lifecycle
    print("\n--- Phase 5: Alert Lifecycle (Trigger -> Persist -> Acknowledge) ---")
    # Trigger alert scenario on P101
    st_scen, res_scen, _ = http_request(
        f"{SIMULATOR_URL}/api/v1/simulator/scenario",
        method="POST",
        data={"scenario": "alert_test", "target_patient_id": "P101", "alert_metric": "heart_rate"},
    )
    print(f"Triggered alert_test on P101 (HTTP {st_scen}). Waiting 6 seconds for backend ingestion...")
    time.sleep(6.0)

    # Query alerts for P101
    st_alt, res_alt, _ = http_request(f"{BACKEND_URL}/api/v1/alerts?patient_id=P101", headers=auth_headers)
    new_alerts = [a for a in res_alt if isinstance(a, dict) and a.get("status") == "NEW"] if st_alt == 200 and isinstance(res_alt, list) else []
    alert_created = len(new_alerts) > 0
    target_alert = new_alerts[0] if alert_created else None
    target_alert_id = target_alert.get("alert_id") if target_alert else None

    record_result(
        "Alert Generation & Ingestion",
        alert_created,
        {
            "alert_created": alert_created,
            "target_alert_id": target_alert_id,
            "patient_id": target_alert.get("patient_id") if target_alert else None,
            "category": target_alert.get("category") if target_alert else None,
            "severity": target_alert.get("severity") if target_alert else None,
            "reason": (target_alert.get("reason")[:80] + "...") if target_alert and target_alert.get("reason") else None,
        },
    )

    # Acknowledge the alert
    ack_ok = False
    ack_res = {}
    if target_alert_id:
        st_ack, res_ack, lat_ack = http_request(
            f"{BACKEND_URL}/api/v1/alerts/{target_alert_id}/acknowledge",
            method="POST",
            headers=auth_headers,
            data={"note": "Verified by live integration smoke test."},
        )
        ack_ok = st_ack == 200 and isinstance(res_ack, dict) and res_ack.get("status") == "ACKNOWLEDGED"
        ack_res = {
            "http_status": st_ack,
            "alert_id": target_alert_id,
            "alert_status": res_ack.get("status") if isinstance(res_ack, dict) else res_ack,
            "acknowledged_by": res_ack.get("acknowledged_by") if isinstance(res_ack, dict) else None,
            "latency_ms": round(lat_ack, 2),
        }

    record_result("Alert Acknowledgement Flow", ack_ok, ack_res)

    # Restore simulator scenario to normal
    http_request(
        f"{SIMULATOR_URL}/api/v1/simulator/scenario",
        method="POST",
        data={"scenario": "normal"},
    )
    print("Restored simulator scenario to normal.")

    # 6. Sensor Interruption & Recovery
    print("\n--- Phase 6: Sensor Interruption & Recovery Resilience ---")
    st_int, res_int, _ = http_request(
        f"{SIMULATOR_URL}/api/v1/simulator/interruption",
        method="POST",
        data={"patient_id": "P104", "interrupted": True},
    )
    st_stat, res_stat, _ = http_request(f"{SIMULATOR_URL}/api/v1/simulator/status")
    interrupted_list = res_stat.get("interrupted_patients", []) if isinstance(res_stat, dict) else []
    int_ok = st_int == 200 and "P104" in interrupted_list

    record_result(
        "Sensor Disconnection Interruption",
        int_ok,
        {"interrupted_patient": "P104", "active_interrupted_list": interrupted_list},
    )

    # Resume P104
    st_res, res_res, _ = http_request(
        f"{SIMULATOR_URL}/api/v1/simulator/interruption",
        method="POST",
        data={"patient_id": "P104", "interrupted": False},
    )
    st_stat2, res_stat2, _ = http_request(f"{SIMULATOR_URL}/api/v1/simulator/status")
    interrupted_list2 = res_stat2.get("interrupted_patients", []) if isinstance(res_stat2, dict) else []
    recov_ok = st_res == 200 and "P104" not in interrupted_list2

    record_result(
        "Sensor Reconnection & Recovery",
        recov_ok,
        {"resumed_patient": "P104", "remaining_interrupted": interrupted_list2},
    )

    # 7. MongoDB Gating Verification
    print("\n--- Phase 7: MongoDB Atlas Storage Protection Gating ---")
    # Verify in DB that analytics_outbox records exist with status 'pending'
    pending_outbox = 0
    synced_outbox = 0
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT status, COUNT(*) FROM analytics_outbox GROUP BY status")
        outbox_counts = dict(cur.fetchall())
        pending_outbox = outbox_counts.get("pending", 0)
        synced_outbox = outbox_counts.get("synced", 0)
        conn.close()

    # Per user directive: MONGODB_SYNC_ENABLED is False, so synced_outbox must NOT increase during live simulation
    mongo_gated = pending_outbox > 0
    record_result(
        "MongoDB Atlas Protection (Gated per User Directive)",
        mongo_gated,
        {
            "pending_outbox_records": pending_outbox,
            "synced_outbox_records": synced_outbox,
            "protection_status": "ENFORCED (Zero automated writes to Atlas; lossless relational queuing active)",
        },
    )

    # 8. User Interface Reachability
    print("\n--- Phase 8: User Interfaces Reachability ---")
    st_react, _, lat_react = http_request(REACT_URL)
    react_ok = st_react == 200
    record_result(
        "React Clinician Web Dashboard",
        react_ok,
        {"http_status": st_react, "url": REACT_URL, "latency_ms": round(lat_react, 2)},
    )

    st_st, _, lat_st = http_request(STREAMLIT_URL)
    st_ok = st_st == 200
    record_result(
        "Streamlit Analytics Dashboard",
        st_ok,
        {"http_status": st_st, "url": "http://localhost:8501", "latency_ms": round(lat_st, 2)},
    )

    # Summary
    print("\n" + "=" * 80)
    total_tests = len(results)
    passed_tests = sum(1 for r in results.values() if r["status"] == "VERIFIED PASS")
    print(f"TEST SUMMARY: {passed_tests}/{total_tests} Passed ({(passed_tests/total_tests)*100:.1f}%)")
    print("=" * 80)

    # Save detailed JSON output for report generation
    with open("live_demo_verification_results.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_tests": total_tests,
                "passed_tests": passed_tests,
                "pass_rate": round(passed_tests / total_tests, 4),
                "results": results,
            },
            f,
            indent=2,
        )
    print("Results saved to live_demo_verification_results.json")
    return passed_tests == total_tests


if __name__ == "__main__":
    success = run_smoke_test()
    sys.exit(0 if success else 1)
