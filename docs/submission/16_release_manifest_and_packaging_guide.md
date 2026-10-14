# 16. Reproducible Release Manifest & Source Packaging Guide

**Document:** Software Release Manifest & Source Code Packaging Guide  
**Project:** AI-Powered Smart Health Monitoring System  
**Release Version:** 3.0.0 (Production Candidate)  
**Release Date:** 14 October 2026  
**Senior Release Engineer:** Lead Architect & Release Engineering Specialist  
**Release Status:** **READY WITH DISCLOSED LIMITATIONS**  
**Machine-Readable Manifest:** [`RELEASE_MANIFEST.json`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/RELEASE_MANIFEST.json)  

---

## 1. Release Architecture & Repository Topology

The **Smart Health Monitoring System** is engineered across three modular Git repositories reflecting clear domain boundaries and academic team divisions:

```
Smart-Health-Monitoring-System/
├── smart-health-monitoring/                  # Authoritative Gateway & Database Core (Member 1)
│   ├── app/ & services/                      # FastAPI REST & WebSocket Routing, Business Logic
│   ├── database/mysql/                       # 17-Table Relational Schema, Stored Procedures, Triggers
│   ├── database/mongodb/                     # Outbox Sync Worker, 7 Aggregation Pipelines
│   ├── dashboard/                            # Streamlit 1.40 Multi-Page Population Dashboard
│   ├── benchmarks/                           # SQL vs. NoSQL Performance Harness & Raw Artifacts
│   ├── scripts/                              # Backup, PITR, Dataset Ingestion & Validation Tools
│   ├── tests/                                # 280 Automated Unit, Integration & Contract Tests
│   ├── RELEASE_MANIFEST.json                 # Machine-Readable Release Manifest
│   └── docs/submission/                      # 16 Unified Academic Submission Documents
│
├── AdityaDhakad1404-frontend-dbms/           # Clinician Web Workstation (Member 2)
│   └── apps/doctor_web/                      # React 19, TypeScript 6.0, Vite 8.3, TailwindCSS
│       ├── src/api/                          # Axios Client, Live Adapters, WebSocket Ticket Client
│       ├── src/pages/                        # Patients, Telemetry Monitor, Alert Triage Desk
│       └── tests/                            # 20 Automated Unit & Contract Tests
│
└── HarnoorKant-Smart-Health-Monitoring-System/ # Machine Learning Anomaly Engine (Member 3)
    ├── packages/health_analysis/             # 38-Feature Pipeline & BaselineManager Personalization
    ├── models/iforest_v1/                    # Serialized Isolation Forest Model & Metadata
    └── tests/                                # Synthetic Feature & Model Evaluation Tests
```

---

## 2. Commit Identifiers & Authoritative Repositories

| Subsystem Name | Authoritative Remote / Workspace | Branch | Verified Commit Hash | Verified Runtime | Automated Test Result |
|---|---|:---:|---|---|:---:|
| **Backend Core & Databases** | `smart-health-monitoring` | `main` | `af3517887ff921a7f92de21c88d4022bed449d83` | Python 3.12.4 / 3.12.9 | **280 / 280 Passed** (69.02s) |
| **Clinician Web Workstation** | `https://github.com/AdityaDhakad1404/frontend-dbms` | `main` | `2c2d6a7a88d9f5f9b3fdd482f4878b8f3f508206` | Node.js v24.14.0, npm 11.9.0 | **20 / 20 Passed** (211ms) |
| **Machine Learning Engine** | `https://github.com/HarnoorKant/Smart-Health-Monitoring-System` | `main` | `aa6410df29113c7ba618ee9506fc1113ec879e96` | Python 3.12.4, scikit-learn 1.8.0 | Verified in live inference |

---

## 3. Exact Step-by-Step Reproducible Setup

### 3.1 Environment Prerequisites
- **Python:** Python `3.10` through `3.12` (Tested on `3.12.4` and `3.12.9`).
- **Node.js:** Node.js `>= v20.0.0` (Tested on `v24.14.0` with `npm 11.9.0`).
- **Relational Storage:** MySQL `8.0` with InnoDB Storage Engine.
- **Document Storage:** MongoDB Atlas `7.0` / `8.0` (or local MongoDB Community / `mongomock`).

---

### 3.2 Backend & Database Setup (`smart-health-monitoring`)

1. **Activate Virtual Environment:**
   ```bash
   cd smart-health-monitoring
   python -m venv .venv
   # Windows:
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```
2. **Install Python Dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Configure Environment:**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   *Verify that `.env` contains your local database credentials (e.g. `MYSQL_USER`, `MYSQL_PASSWORD`, `MONGODB_URI`).*
4. **Initialize MySQL Schema & Run Migrations:**
   ```bash
   alembic upgrade head
   ```
5. **Seed Verified Dataset (Kaggle 1,500 Telemetry Records):**
   ```bash
   python -m scripts.import_kaggle_dataset --file="data/kaggle_health_dataset.csv"
   ```
6. **Execute Automated Test Suite:**
   ```bash
   python -m pytest
   ```

---

### 3.3 Clinician Workstation Setup (`apps/doctor_web`)

1. **Navigate and Install Node Modules:**
   ```bash
   cd ../AdityaDhakad1404-frontend-dbms/apps/doctor_web
   npm.cmd install
   ```
2. **Configure Environment:**
   Create `.env.local` with:
   ```ini
   VITE_USE_MOCK_DATA=false
   VITE_API_URL=http://localhost:8000
   VITE_WS_URL=ws://localhost:8000
   ```
3. **Execute Unit Tests & Production Build:**
   ```bash
   npm.cmd test
   npm.cmd run build
   ```

---

### 3.4 Service Startup Commands (3 Terminals)

```bash
# Terminal 1: FastAPI Core Gateway (Port 8000)
cd smart-health-monitoring
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: React Clinician Dashboard (Port 5173)
cd AdityaDhakad1404-frontend-dbms/apps/doctor_web
npm.cmd run dev

# Terminal 3: Streamlit Analytics Dashboard (Port 8501)
cd smart-health-monitoring
streamlit run dashboard/app.py --server.port 8501
```

---

## 4. Environment Variables Specification & Security Guarantees

All sensitive parameters are abstracted through `.env.example` templates. No real secrets or live connection URIs are committed to Git:

| Environment Variable | Description | Safe Example Placeholder | Required In |
|---|---|---|:---:|
| `MYSQL_HOST` | MySQL hostname | `localhost` | Backend |
| `MYSQL_PORT` | MySQL port | `3306` | Backend |
| `MYSQL_DATABASE` | Relational database name | `smart_health` | Backend |
| `MYSQL_USER` | Application database user | `smart_health_app` | Backend |
| `MYSQL_PASSWORD` | Database password | `replace_with_secure_mysql_password` | Backend |
| `MONGODB_URI` | MongoDB Atlas cluster URI | `mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority` | Backend |
| `MONGODB_DATABASE` | Analytical document database | `smart_health_analytics` | Backend |
| `JWT_SECRET` | Cryptographic secret for signing JWTs | `replace_with_min_32_char_random_secret_key` | Backend |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` | Backend |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token validity duration | `60` | Backend |
| `VITE_USE_MOCK_DATA` | Toggle between live and demo modes | `false` | Frontend |
| `VITE_API_URL` | Base URL for FastAPI REST endpoints | `http://localhost:8000` | Frontend |
| `VITE_WS_URL` | Base URL for WebSocket streams | `ws://localhost:8000` | Frontend |

---

## 5. Physical Deliverables & Disk Artifacts Inventory

The complete academic packaging comprises 16 unified specification documents located in [`docs/submission/`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/docs/submission/):

```
docs/submission/
├── 01_project_overview.md                           (Project Scope, Team Roles & Scorecard)
├── 02_system_architecture.md                        (Polyglot Model, 4 Mermaid Diagrams)
├── 03_database_design.md                            (17 MySQL Tables, 3NF/BCNF Proof, 7 Pipelines)
├── 04_api_and_integration_reference.md              (59 FastAPI Endpoints & RBAC Rules)
├── 05_ml_technical_documentation.md                 (Isolation Forest v1.0.0, 38 Features)
├── 06_frontend_integration_guide.md                 (React 19 Architecture, WebSocket Tickets)
├── 07_da1_da3_traceability_matrix.md                (Complete Coursework Compliance Matrix)
├── 08_test_and_verification_report.md               (338-Point Test Scorecard & Fix Evidence)
├── 09_sql_vs_nosql_benchmark_report.md              (Empirical Data: bench_1791921481)
├── 10_backup_and_recovery_runbook.md                (mysqldump, Binary Log PITR, Restore Drills)
├── 11_setup_deployment_and_viva_guide.md            (Setup Runbook, Env Vars & Viva Q&A)
├── 12_evidence_inventory_and_checklist.md          (Physical Code Catalog & Pre-Submission Check)
├── 13_project_presentation_and_viva_guide.md        (Master Oral Defense Guide & Model Answers)
├── 14_final_defect_remediation_and_hardening_report.md (DEF-001 to DEF-005 Fixes & Evidence)
├── 15_final_system_submission_audit.md              (Independent Auditor Report & Final Verdict)
├── 16_release_manifest_and_packaging_guide.md      (This Release Specification)
└── presentation_slide_deck.md                       (20-Slide Technical Presentation Deck)
```

---

## 6. Disclosed Operational Boundaries & Known Limitations

To maintain uncompromising academic honesty, the following scope boundaries are disclosed:
1. **Patient Mobile Application (Flutter):** As verified during the system audit, mobile client code is an **external, planned integration component** and is not packaged in the current repository workspace. Telemetry ingestion and viewing are demonstrated via bulk Kaggle CSV replay and authenticated REST APIs.
2. **Stateless JWT Revocation:** Access tokens remain cryptographically valid until expiration; client logouts log an immutable audit event (`AUTH_LOGOUT`) in MySQL and clear local tokens. An external Redis token blacklist is recommended for enterprise deployments.
3. **Cold-Start Machine Learning Windowing:** Patients with fewer than 10 historical readings fall back to cohort averages rather than full rolling-window feature extraction.

---

## 7. Release Certification & Sign-off

- **Mandatory Requirements:** **100% Satisfied across DA1, DA2, and DA3.**
- **Automated Verification:** **338 of 338 Verification Points Passed (100%).**
- **Security Audit:** **Zero Hardcoded Secrets.**
- **Release Verdict:** **CERTIFIED AND READY FOR SUBMISSION AND ACADEMIC DEFENSE.**
