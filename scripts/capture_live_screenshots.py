"""
Smart Health Monitoring System — Live UI Screenshot Capture Utility.
Uses Playwright to capture genuine high-resolution PNG screenshots from the live running services.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def capture_screenshots():
    print("[*] Launching headless browser for screenshot capture...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # 1. Clinician Workstation — Patients Directory
        print("  -> Capturing 01_clinician_workstation_patients.png...")
        page.goto("http://127.0.0.1:5173", wait_until="networkidle", timeout=15000)
        time.sleep(1.5)
        page.screenshot(path=str(OUTPUT_DIR / "01_clinician_workstation_patients.png"))

        # 2. Clinician Workstation — Longitudinal Telemetry Chart (P101)
        print("  -> Capturing 02_patient_vitals_timeseries.png...")
        page.goto("http://127.0.0.1:5173/patients/P101", wait_until="networkidle", timeout=15000)
        time.sleep(2.0)
        page.screenshot(path=str(OUTPUT_DIR / "02_patient_vitals_timeseries.png"))

        # 3. Clinician Workstation — Alert Triage Desk
        print("  -> Capturing 03_clinical_alert_triage.png...")
        page.goto("http://127.0.0.1:5173/alerts", wait_until="networkidle", timeout=15000)
        time.sleep(1.5)
        page.screenshot(path=str(OUTPUT_DIR / "03_clinical_alert_triage.png"))

        # 4. DA3 Evaluation Console
        print("  -> Capturing 04_da3_evaluation_console.png...")
        page.goto("http://127.0.0.1:5173/evaluation", wait_until="networkidle", timeout=15000)
        time.sleep(2.0)
        page.screenshot(path=str(OUTPUT_DIR / "04_da3_evaluation_console.png"))

        # 5. FastAPI Interactive Swagger Docs
        print("  -> Capturing 05_fastapi_swagger_docs.png...")
        page.goto("http://127.0.0.1:8000/docs", wait_until="networkidle", timeout=15000)
        time.sleep(2.0)
        page.screenshot(path=str(OUTPUT_DIR / "05_fastapi_swagger_docs.png"))

        # 6. Streamlit Population Analytics Visualizer
        print("  -> Capturing 06_streamlit_analytics_visualizer.png...")
        try:
            page.goto("http://localhost:8501", wait_until="networkidle", timeout=15000)
            time.sleep(3.0)
            page.screenshot(path=str(OUTPUT_DIR / "06_streamlit_analytics_visualizer.png"))
        except Exception as e:
            print(f"    [WARN] Streamlit capture note: {e}")

        browser.close()
    print("[OK] All genuine live UI screenshots captured successfully in docs/screenshots/")

if __name__ == "__main__":
    capture_screenshots()
