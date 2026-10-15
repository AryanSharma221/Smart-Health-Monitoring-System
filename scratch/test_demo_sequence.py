import urllib.request
import json
import time

API = "http://127.0.0.1:8000"
SIM = "http://127.0.0.1:8001"

def post(url, data=None, token=None):
    req = urllib.request.Request(url, data=json.dumps(data or {}).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())

def get(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())

def main():
    print("1. Authenticate Doctor:")
    s, d = post(f"{API}/api/v1/auth/login", {"email": "doctor@hospital.org", "password": "DoctorPassword123!"})
    token = d["access_token"]
    print(f"   Logged in: status={s}, token_len={len(token)}")

    print("2. Query Demo Cohort (P101-P105):")
    for pid in ["P101", "P102", "P103", "P104", "P105"]:
        s, p = get(f"{API}/api/v1/patients/{pid}", token)
        print(f"   {pid}: status={s}, name={p.get('first_name', '')} {p.get('last_name', '')}")

    print("3. Start Simulator:")
    s, res = post(f"{API}/api/v1/simulator/start", token=token)
    print(f"   Simulator start: status={s}, lifecycle={res.get('lifecycle_state')}")
    time.sleep(1.0)

    print("4. Ingest Telemetry & Check Provenance:")
    s, latest = get(f"{SIM}/api/v1/readings/latest")
    readings = latest.get("readings", {})
    print(f"   Readings count={len(readings)}")
    for pid, r in readings.items():
        print(f"   {pid}: HR={r['heart_rate']}, SpO2={r['spo2']}, is_simulated={r['is_simulated']}, scenario={r['scenario']}")

    print("5. Trigger Elevated HR Scenario on P102:")
    s, sc_res = post(
        f"{API}/api/v1/simulator/scenario",
        {"scenario": "elevated_hr", "target_patient_id": "P102", "alert_metric": "heart_rate"},
        token=token,
    )
    print(f"   Scenario trigger: status={s}, scenario={sc_res.get('scenario')}")
    time.sleep(1.5)

    print("6. Check Clinical Alerts:")
    s, alerts = get(f"{API}/api/v1/alerts", token=token)
    alerts_list = alerts.get("items", alerts) if isinstance(alerts, dict) else alerts
    print(f"   Alerts status={s}, count={len(alerts_list)}")
    if alerts_list:
        top_alert = alerts_list[0]
        print(f"   Latest Alert: id={top_alert.get('alert_id', top_alert.get('id'))}, severity={top_alert.get('severity')}, message={top_alert.get('message')}")

    print("7. Stop Simulator:")
    s, stop_res = post(f"{API}/api/v1/simulator/stop", token=token)
    print(f"   Simulator stop: status={s}, lifecycle={stop_res.get('lifecycle_state')}")
    time.sleep(1.0)

    print("8. Query EHR while Stopped:")
    s, p101 = get(f"{API}/api/v1/patients/P101", token)
    print(f"   P101 EHR query during stop: status={s}, name={p101.get('first_name')}")

    print("9. Resume Simulator:")
    s, resume_res = post(f"{API}/api/v1/simulator/start", token=token)
    print(f"   Simulator resume: status={s}, lifecycle={resume_res.get('lifecycle_state')}")
    time.sleep(1.0)

    print("10. Final Clean Stop:")
    s, final_stop = post(f"{API}/api/v1/simulator/stop", token=token)
    print(f"   Simulator final stop: status={s}, lifecycle={final_stop.get('lifecycle_state')}")
    print("Dry-run completed successfully!")

if __name__ == "__main__":
    main()
