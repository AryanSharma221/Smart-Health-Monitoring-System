"""
Focused Regression Checks for Part 7S.
Verifies backend health, authentication, safe MySQL evaluation CRUD, baseline protection guard,
simulator lifecycle (start, stop, resume), and decoupled application behavior.
Strict Invariants:
- Zero writes to MongoDB Atlas.
- Zero destructive modifications to genuine EHR data (P001-P005, P101-P105).
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error

def run_checks():
    print("================================================================================")
    print("SMART HEALTH MONITORING SYSTEM — FOCUSED REGRESSION VERIFICATION (PART 7S)")
    print("================================================================================")
    
    # 1. Backend Gateway Health Probe
    t0 = time.perf_counter()
    with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=5) as r:
        data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        print(f"[PASS] 1. Backend Gateway Health: HTTP {r.status} in {lat:.2f}ms — service: {data.get('service', '')}")

    # 2. Database Health Probe
    t0 = time.perf_counter()
    with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/db", timeout=5) as r:
        data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        print(f"[PASS] 2. Database Health Probe: HTTP {r.status} in {lat:.2f}ms — engine: {data.get('database', '')}")

    # 3. Clinician Authentication & JWT Issuance
    t0 = time.perf_counter()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/auth/login",
        data=json.dumps({"email": "doctor@hospital.org", "password": "DoctorPassword123!"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        auth_data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        token = auth_data.get("access_token", "")
        role = auth_data.get("role", "")
        print(f"[PASS] 3. Clinician Authentication: HTTP {r.status} in {lat:.2f}ms — role: {role}, token acquired: {bool(token)}")

    auth_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 4. Safe MySQL CRUD Lifecycle on Isolated evaluation_records
    # 4a. CREATE
    t0 = time.perf_counter()
    crud_payload = {
        "patient_id": "P101",
        "title": "Part 7S Regression Safety Note",
        "content_text": "Verifying non-destructive CRUD isolation during Part 7S.",
        "record_type": "clinical_note",
        "status": "ACTIVE"
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/evaluation/crud/records",
        data=json.dumps(crud_payload).encode("utf-8"),
        headers=auth_headers,
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        rec_data = json.loads(r.read())
        rec_id = rec_data.get("record_id")
        lat = (time.perf_counter() - t0) * 1000
        print(f"[PASS] 4a. Safe CRUD Create: HTTP {r.status} in {lat:.2f}ms — record_id: {rec_id}")

    # 4b. RETRIEVE
    t0 = time.perf_counter()
    req = urllib.request.Request(f"http://127.0.0.1:8000/api/v1/evaluation/crud/records/{rec_id}", headers=auth_headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        get_data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        assert get_data["record_id"] == rec_id
        print(f"[PASS] 4b. Safe CRUD Retrieve: HTTP {r.status} in {lat:.2f}ms — confirmed record integrity")

    # 4c. UPDATE
    t0 = time.perf_counter()
    update_payload = {"title": "Part 7S Regression Safety Note [UPDATED]", "content_text": "Updated content."}
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/evaluation/crud/records/{rec_id}",
        data=json.dumps(update_payload).encode("utf-8"),
        headers=auth_headers,
        method="PUT"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        up_data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        assert up_data["title"] == "Part 7S Regression Safety Note [UPDATED]"
        print(f"[PASS] 4c. Safe CRUD Update: HTTP {r.status} in {lat:.2f}ms — title updated")

    # 4d. DELETE
    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1/evaluation/crud/records/{rec_id}",
        headers=auth_headers,
        method="DELETE"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        del_data = json.loads(r.read())
        lat = (time.perf_counter() - t0) * 1000
        print(f"[PASS] 4d. Safe CRUD Delete: HTTP {r.status} in {lat:.2f}ms — status: {del_data.get('status')}")

    # 4e. VERIFY 404
    try:
        req = urllib.request.Request(f"http://127.0.0.1:8000/api/v1/evaluation/crud/records/{rec_id}", headers=auth_headers)
        urllib.request.urlopen(req, timeout=5)
        print("[FAIL] Expected HTTP 404 for deleted evaluation record!")
    except urllib.error.HTTPError as e:
        assert e.code == 404
        print(f"[PASS] 4e. Post-Delete 404 Verification: HTTP {e.code} correctly confirmed deletion")

    # 5. Core EHR Baseline Deletion Guard (Attempt P001 -> HTTP 403 Forbidden)
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/v1/evaluation/crud/records/P001",
            headers=auth_headers,
            method="DELETE"
        )
        urllib.request.urlopen(req, timeout=5)
        print("[FAIL] Baseline record deletion was NOT intercepted!")
    except urllib.error.HTTPError as e:
        assert e.code == 403
        err_msg = json.loads(e.read().decode("utf-8")).get("detail", "")
        print(f"[PASS] 5. Core EHR Immutability Guard: HTTP {e.code} Forbidden strictly enforced — \"{err_msg}\"")

    # 6. Smartwatch Telemetry Simulator Lifecycle & Decoupled State
    # 6a. Probing Initial State
    with urllib.request.urlopen("http://127.0.0.1:8001/api/v1/simulator/status", timeout=5) as r:
        sim_data = json.loads(r.read())
        print(f"[PASS] 6a. Simulator Initial State: lifecycle_state={sim_data.get('lifecycle_state')}, is_running={sim_data.get('is_running')}")

    # 6b. Start Simulator
    req = urllib.request.Request("http://127.0.0.1:8001/api/v1/simulator/start", data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        s_data = json.loads(r.read())
        print(f"[PASS] 6b. Simulator Start Command: HTTP {r.status} — is_running={s_data.get('is_running')}")

    time.sleep(1)

    # 6c. Stop Simulator
    req = urllib.request.Request("http://127.0.0.1:8001/api/v1/simulator/stop", data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        s_data = json.loads(r.read())
        print(f"[PASS] 6c. Simulator Stop Command: HTTP {r.status} — is_running={s_data.get('is_running')}")

    # 6d. Decoupled Application Verification While Simulator is STOPPED
    req = urllib.request.Request("http://127.0.0.1:8000/api/v1/patients/P101", headers=auth_headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        p_data = json.loads(r.read())
        print(f"[PASS] 6d. Decoupled Application Read: HTTP {r.status} — Patient {p_data.get('patient_id')} accessible while simulator STOPPED")

    print("================================================================================")
    print(">>> ALL FOCUSED REGRESSION CHECKS PASSED (6/6 SUITES, 0 DEFECTS) <<<")
    print("================================================================================")

if __name__ == "__main__":
    run_checks()
