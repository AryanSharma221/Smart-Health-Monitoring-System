# AI-Powered Smart Health Monitoring System

Version 3.0 — Kaggle Dataset-Aligned DA3 Edition  
*Simulated Health Telemetry Prototype — NOT FOR MEDICAL USE*

## 1. Overview
The Smart Health Monitoring System is an end-to-end telemetry and clinical decision-support prototype featuring:
- **FastAPI Backend Gateway:** REST APIs, JWT authentication, and WebSocket live updates.
- **MySQL 8 (InnoDB):** Authoritative transactional store for patients, doctors, assignments, canonical readings, alerts, and audit logs.
- **MongoDB Atlas:** DA3 document mirror for telemetry events (`health_events`) and model assessments (`model_assessments`).
- **Kaggle Historical Dataset:** 1,500 historical rows across 5 patients (`P101`–`P105`) with 3 vitals (`heart_rate`, `spo2`, `temperature_f`).
- **ML Anomaly Detection:** Rolling-window feature extraction and unsupervised `Isolation Forest` analysis.
- **Streamlit Analytics Dashboard:** DA3 SQL-vs-NoSQL performance benchmarking and aggregation visualizer.

## 2. Quickstart & Configuration Setup

### Step 1: Clone & Navigate
```bash
cd smart-health-monitoring
```

### Step 2: Configure Environment Variables
Copy the template and configure your local settings:
```bash
copy .env.example .env
```
*Note: Never commit `.env` or any files containing credentials to version control.*

### Step 3: Run Configuration Unit Tests
```bash
python -m pytest tests/unit/test_config.py -v
```

### Step 4: Run FastAPI Gateway Locally
```bash
uvicorn services.api.main:app --host 127.0.0.1 --port 8000 --reload
```
Visit http://127.0.0.1:8000/docs for the interactive OpenAPI documentation.
