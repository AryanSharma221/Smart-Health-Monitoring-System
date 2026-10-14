# 01. Project Overview & Executive Summary

**Project Title:** AI-Powered Smart Health Monitoring System  
**Academic Coursework:** Database Management Systems — Digital Assignments DA1, DA2, and DA3  
**Auditor & Architect:** Senior Software Architect & Lead Database Reliability Engineer  
**Date of Audit & Compilation:** 14 October 2026  
**System Version:** 3.0.0 (FastAPI Core Gateway + Hybrid Database Engine)  
**Git Branch:** `main`  

---

## 1. Executive Summary

The **AI-Powered Smart Health Monitoring System** is an enterprise-grade, distributed digital healthcare platform engineered to provide real-time patient physiological monitoring, automated clinical triage, longitudinal health analytics, and machine-learning-assisted physiological anomaly detection.

Designed to address the dual challenges of high-frequency telemetry ingestion and complex clinical querying, the platform leverages a **hybrid polyglot persistence architecture**:
1. **Relational Core (MySQL 8 InnoDB):** Serves as the authoritative, transactional source of truth (System of Record) for patient demographics, medical history, user credentials, role-based access control (RBAC), device assignments, clinical alerts, and auditable care-team communications. It guarantees strict ACID compliance, declarative referential integrity, and procedural safety.
2. **Document Store (MongoDB Atlas):** Serves as an optimized analytical mirror (System of Engagement) for high-volume physiological telemetry time-series and pre-aggregated clinical alert summaries. It provides horizontal scalability, schema flexibility, and low-latency aggregation pipelines for population health analytics and visual dashboards.
3. **Decoupled Synchronization (Transactional Outbox Pattern):** Rather than risking dual-write inconsistencies or imposing distributed two-phase commit (2PC) locks, all telemetry ingested into MySQL atomically writes an event to an `analytics_outbox` table. An asynchronous background worker polls this outbox and idempotently mirrors documents into MongoDB Atlas using deterministic upserts.

The platform integrates an **unsupervised machine learning anomaly detection engine** (Isolation Forest with personalized patient baselines), a **real-time clinician workstation** (React 19 + TypeScript), an **interactive analytics dashboard** (Streamlit), and an **empirical performance benchmarking harness** comparing SQL and NoSQL database query latencies across identical clinical workloads.

---

## 2. Coursework Alignment (DA1, DA2, DA3)

This implementation directly addresses and satisfies the requirements set forth across the three academic digital assignments:

| Assignment | Core Academic Focus | Implemented & Verified System Components |
|---|---|---|
| **DA1** | **Conceptual & Logical Relational Modeling** | • Comprehensive Entity-Relationship (ER) model with 15 normalized relational tables.<br>• Rigorous Third Normal Form (3NF) and Boyce-Codd Normal Form (BCNF) normalization.<br>• Primary keys, foreign key constraints with explicit referential integrity (`CASCADE`, `RESTRICT`, `SET NULL`), and domain `CHECK` constraints on vital signs and medical values.<br>• Relational indexing strategies (composite, covering, unique). |
| **DA2** | **Advanced Relational DDL, Ingestion & Procedural SQL** | • Production-ready DDL (`schema.sql`) and version-controlled Alembic migrations (`alembic/versions/`).<br>• Real Kaggle healthcare dataset bulk ingestion (1,500 telemetry rows across 5 patient cohorts).<br>• Complex multi-table `JOIN` queries, nested analytical subqueries, and grouping sets.<br>• Relational views (`v_latest_patient_vitals`, `v_patient_active_alerts`).<br>• User-defined stored functions (`fn_calculate_bmi`, `fn_calculate_fever_category`).<br>• Procedural SQL (`sp_acknowledge_alert`) and atomic ACID transactions with named savepoints (`sp_safe_patient_discharge`).<br>• Database-level audit triggers (`trg_alert_status_history_after_update`). |
| **DA3** | **NoSQL Modeling, Mirroring, Aggregations, Benchmarking & Reliability** | • Document data modeling in MongoDB Atlas (`telemetry_readings`, `clinical_alerts`) with source-event correlation IDs.<br>• Reliable synchronization via the Transactional Outbox Pattern with automatic retry and error handling.<br>• 7 production MongoDB aggregation pipelines (statistical summaries, time-window scans, hourly bucketing, alert triage).<br>• Rigorous empirical SQL vs. NoSQL benchmarking harness with mathematical equivalence verification ($\epsilon = 0.05$).<br>• Database query execution plan analysis (`EXPLAIN` in MySQL vs `explain("executionStats")` in MongoDB).<br>• Multi-page Streamlit analytics dashboard (`dashboard/app.py`).<br>• Complete database backup, point-in-time recovery (PITR), and disaster recovery runbooks with automated verification scripts. |

---

## 3. Distributed Repository Topology & Team Scope

The codebase is organized into modular repositories and workspaces reflecting specialized team responsibilities:

```
Smart-Health-Monitoring-System/
├── smart-health-monitoring/           # Central FastAPI Backend & Database Core
│   ├── app/                           # FastAPI Gateway, Routers, Services, Schemas
│   ├── database/                      # MySQL Models, Alembic Migrations, MongoDB Mirror & Aggregations
│   ├── dashboard/                     # Streamlit Multi-Page Analytics Dashboard
│   ├── benchmarks/                    # SQL vs. NoSQL Benchmarking Engine & Raw Artifacts
│   ├── scripts/                       # Backup, Recovery, Dataset Ingestion & Verification Scripts
│   ├── tests/                         # 280 Automated Unit, Integration & Contract Tests
│   └── docs/                          # Architecture, Schemas, Benchmarks & Submission Pack
│
├── AdityaDhakad1404-frontend-dbms/    # Clinician Web Workstation
│   └── apps/doctor_web/               # React 19, TypeScript 6.0, Vite 8.3, TailwindCSS
│       ├── src/api/                   # Axios HTTP Client & Live API Adapters
│       ├── src/auth/                  # JWT Session & Refresh Token Lifecycle
│       ├── src/context/               # Real-time WebSocket Ticket Stream Context
│       ├── src/pages/                 # Patients, Vitals, Alerts, Diagnostics Workstations
│       └── tests/                     # 20 Automated Unit & Contract Tests
│
└── HarnoorKant-Smart-Health-Monitoring-System/  # Machine Learning Anomaly Engine
    ├── packages/health_analysis/      # Feature Engineering (38 features) & Inference Pipelines
    ├── models/iforest_v1/             # Serialized Isolation Forest & Preprocessor Artifacts
    ├── scripts/                       # Training, Evaluation & Kaggle Dataset Pipelines
    └── tests/                         # Anomaly Engine Unit & Synthetic Validation Tests
```

### Component Status & Boundary Verification:
- **Central FastAPI Backend:** **100% Implemented & Verified.** 59 active endpoints, JWT Bearer authentication, 4-tier Role-Based Access Control (`ADMIN`, `DOCTOR`, `NURSE`, `PATIENT`), full database integration.
- **Clinician Web Dashboard:** **100% Implemented & Verified.** Successfully connected to FastAPI via REST and WebSocket streaming. Features dual-mode operation (Live backend mode vs. Standalone demo mode).
- **Machine Learning Engine:** **100% Implemented & Verified.** Integrated directly into FastAPI process space. Provides personal baseline evaluation and unsupervised anomaly scoring.
- **Streamlit Analytics Dashboard:** **100% Implemented & Verified.** 8 interactive analytical views connected to both live databases and empirical benchmark artifacts.
- **Patient Mobile Application (Flutter):** **Planned / External.** As verified during the system audit, the Flutter mobile application is not present within the local repository workspace. To maintain academic and technical integrity, patient telemetry ingestion is demonstrated and fully verified through bulk Kaggle dataset CSV ingestion and authenticated RESTful telemetry ingestion endpoints.

---

## 4. Key Verification Metrics & Evidence Summary

All claims within this submission are grounded in verifiable, reproducible execution logs and disk artifacts:

- **Automated Backend Test Suite:** **280 / 280 Passed (100%)** via `pytest tests/` in 73.64 seconds.
- **Automated Frontend Test Suite:** **20 / 20 Passed (100%)** via `node --test` in 365 milliseconds.
- **Frontend Quality Assurance:** TypeScript compilation (`tsc -b`) and Vite production bundle (`vite build`) pass with zero errors and zero warnings.
- **Live System End-to-End Verification:** **31 / 31 Checks Passed (100%)** across live FastAPI server, authenticated REST endpoints, WebSocket ticket handshakes, real-time message streaming, and ML inference.
- **SQL vs. NoSQL Semantic Equivalence:** **7 / 7 Workloads Passed (100%)** with strict numerical tolerance ($\epsilon \le 0.05$) across SQL and MongoDB aggregation queries.
- **Benchmarking Artifacts on Disk:** Multiple real benchmark runs archived under `benchmarks/results/` with raw JSON runs, per-sample CSV measurements, and executive Markdown summaries.
- **Database Backup & Recovery:** Automated verification scripts (`scripts/backup_and_recovery.py`) verified against live MySQL and MongoDB configurations with explicit checksum validation.
