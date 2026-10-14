# AI-Powered Smart Health Monitoring System

Version 3.0 — Kaggle Dataset-Aligned DA3 Edition  
*Simulated Health Telemetry Prototype — NOT FOR MEDICAL USE*

## 1. Overview
The Smart Health Monitoring System is an end-to-end telemetry and clinical decision-support prototype featuring:
- **FastAPI Backend Gateway:** REST APIs, JWT authentication, operational healthchecks, and WebSocket live updates.
- **MySQL 8 (InnoDB):** Authoritative transactional store for patients, doctors, assignments, canonical readings, alerts, messages, and audit logs.
- **MongoDB Atlas:** DA3 document mirror for telemetry events (`telemetry_events`) and clinical alerts (`alert_events`).
- **Kaggle Historical Dataset:** 1,500 historical rows across 5 patients (`P101`–`P105`) with 3 vitals (`heart_rate`, `spo2`, `temperature_f`).
- **ML Anomaly Detection:** Rolling-window feature extraction and unsupervised `Isolation Forest` analysis.
- **Streamlit Analytics Dashboard:** DA3 SQL-vs-NoSQL performance benchmarking and aggregation visualizer.

---

## 2. Quickstart & Configuration Setup

### Step 1: Clone & Navigate
```bash
cd smart-health-monitoring
```

### Step 2: Configure Environment Variables
Copy the template and configure your local settings:
```bash
# Windows
copy .env.example .env
# Linux / macOS
cp .env.example .env
```
*Note: Never commit `.env` or any files containing credentials to version control. For production, see `.env.production.template`.*

### Step 3: Run Full Automated Verification Suite
Runs all 210 unit, integration, security regression, and end-to-end test cases:
```bash
python -m pytest tests/ -v
```

### Step 4: Database Migrations (Alembic)
Generate offline MySQL 8 DDL without connecting to a live database:
```bash
python -m alembic upgrade head --sql
```
Apply migrations directly to the configured MySQL instance (when online):
```bash
python -m alembic upgrade head
```

### Step 5: Validate and Ingest Kaggle Historical Dataset
Dry-run validation (zero database mutation):
```bash
python -m services.ingestion.cli --dry-run
```
Execute actual idempotent ingestion:
```bash
python -m services.ingestion.cli --csv-path "E:\DOC-20261013-WA0056.csv" --batch-size 250
```
For detailed ingestion documentation, see [docs/dataset_ingestion.md](docs/dataset_ingestion.md).

### Step 6: Run FastAPI Gateway Locally
```bash
uvicorn services.api.main:app --host 127.0.0.1 --port 8000 --reload
```
Visit http://127.0.0.1:8000/docs for the interactive OpenAPI documentation.

---

## 3. Containerized Deployment (Docker & Compose)

### Launch Local Staging Environment (API + MySQL):
```bash
docker compose up -d --build
```
Check container status and logs:
```bash
docker compose ps
docker compose logs -f api
```

### Build Hardened Production Container:
```bash
docker build -t smart-health-api:3.0.0 -f Dockerfile .
```

---

## 4. Operational Health & Readiness Probes

| Endpoint | Type | Purpose | Healthy Status | Failure Status |
|:---|:---|:---|:---|:---|
| `GET /health` | Liveness | Application metadata & simulated notice | 200 OK | Process down |
| `GET /health/live` | Liveness | Kubernetes / Container liveness check | 200 OK | Process down |
| `GET /health/ready` | Readiness | Authoritative MySQL connectivity check | 200 OK | 503 Service Unavailable |
| `GET /health/db` | Diagnostic | Direct MySQL connectivity probe | 200 OK (`connected`) | 200 OK (`unreachable`) |
| `GET /health/mongodb`| Diagnostic | MongoDB Atlas & outbox queue telemetry | 200 OK (`connected` / status) | Safe masked status |

---

## 5. Operations & Documentation Runbooks

- [Production Deployment Guide](docs/deployment_guide.md): Server prerequisites, Nginx reverse proxy configuration, systemd units, and pre/post-deployment checklists.
- [Backup and Recovery Runbook](docs/backup_and_recovery.md): MySQL `mysqldump` procedures, point-in-time recovery, isolated restoration verification, and MongoDB outbox recovery.
- [Operational Architecture & Diagnostics](docs/operational_architecture.md): Process concurrency, WebSocket multi-node scaling boundaries, structured logging, and diagnostics.
- [Dataset Ingestion Pipeline](docs/dataset_ingestion.md): Kaggle schema mapping, unit conversions, and idempotency guarantees.
- [MongoDB Analytics Mirror](docs/mongodb_analytics_mirror.md): Transactional outbox pattern, collections, and disaster recovery.
- [Real-Time WebSockets](docs/realtime_websockets.md): WebSocket handshake, connection lifecycle, and authorization.
- [Clinical Messaging System](docs/messaging_system.md): End-to-end patient-clinician messaging and read tracking.

---

## 6. Academic Coursework Submission & Viva Defense Pack (DA1, DA2, DA3)

The complete academic evidence and defense suite is located in [docs/submission/](docs/submission/):
- **Technical Presentation Deck:** [docs/submission/presentation_slide_deck.md](docs/submission/presentation_slide_deck.md) (20 slides with speaker notes & examiner Q&A)
- **Master Viva Voce Guide:** [docs/submission/13_project_presentation_and_viva_guide.md](docs/submission/13_project_presentation_and_viva_guide.md) (Model answers for Database, ML, Backend, and Benchmarks)
- **DA1–DA3 Traceability Matrix:** [docs/submission/07_da1_da3_traceability_matrix.md](docs/submission/07_da1_da3_traceability_matrix.md) (100% compliance mapping)
- **Release Manifest & Packaging Guide:** [docs/submission/16_release_manifest_and_packaging_guide.md](docs/submission/16_release_manifest_and_packaging_guide.md)
- **Machine-Readable Manifest:** [RELEASE_MANIFEST.json](RELEASE_MANIFEST.json) (v3.0.0 release specification)

