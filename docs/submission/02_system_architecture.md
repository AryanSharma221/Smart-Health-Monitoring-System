# 02. System Architecture & End-to-End Data Flow

**Document:** System Architecture Specification  
**Project:** AI-Powered Smart Health Monitoring System  
**Auditor & Architect:** Senior Software Architect & Lead Database Reliability Engineer  
**Date:** 14 October 2026  
**System Version:** 3.0.0  

---

## 1. Architectural Philosophy: The Polyglot Persistence Pattern

Modern healthcare telemetry platforms face two conflicting operational demands:
1. **High-Integrity Clinical Transactions:** Demographics, medical histories, device assignments, and alert lifecycle states require strict ACID transactions, declarative foreign key integrity, and non-repudiation.
2. **High-Throughput Time-Series Analytics:** Physiological telemetry streams (heart rate, SpO2, blood pressure, temperature) generate millions of data points requiring flexible indexing, high ingestion throughput, and complex multi-stage windowed aggregations across cohorts.

To resolve this impedance mismatch without sacrificing operational integrity, the Smart Health Monitoring System implements a **Polyglot Persistence Architecture** powered by the **Transactional Outbox Pattern**.

```mermaid
graph TD
    subgraph Clients ["Client Applications"]
        DoctorWeb["React Clinician Dashboard\n(apps/doctor_web)"]
        StreamlitUI["Streamlit Analytics Dashboard\n(dashboard/app.py)"]
        ExternalIngest["Telemetry Producers / Ingest Scripts\n(Kaggle Replay / Sensors)"]
        MobileApp["Patient Mobile App\n(Planned / External)"]
    end

    subgraph Gateway ["FastAPI Central Application Core (Port 8000)"]
        APIGateway["FastAPI API Gateway\n(Routes, OpenAPI, CORS, Logging)"]
        AuthMiddleware["OAuth2 & JWT Auth\n(4-Tier RBAC)"]
        MLService["ML Anomaly Engine\n(Isolation Forest v1.0.0)"]
        RuleEngine["Clinical Rule Engine\n(Thresholds & Alerts)"]
        WSManager["WebSocket Connection Manager\n(Ticket Authenticated)"]
        OutboxPoller["Background Outbox Worker\n(Async Polling & Sync)"]
    end

    subgraph RelationalDB ["Primary System of Record (Authoritative)"]
        MySQL[("MySQL 8.0 InnoDB\n15 Normalized Tables\nACID Transactions\nTriggers & Procedures")]
        OutboxTable[("analytics_outbox Table\n(Pending Event Buffer)")]
    end

    subgraph DocumentStore ["Analytical System of Engagement (Mirror)"]
        MongoDB[("MongoDB Atlas\nDocument Collections:\n- telemetry_readings\n- clinical_alerts")]
    end

    DoctorWeb -->|REST / Bearer JWT| APIGateway
    DoctorWeb -->|WSS Realtime Stream| WSManager
    StreamlitUI -->|Direct Read Access| MySQL
    StreamlitUI -->|Aggregation Pipelines| MongoDB
    ExternalIngest -->|POST /api/v1/vitals| APIGateway
    MobileApp -.->|Future Integration| APIGateway

    APIGateway --> AuthMiddleware
    AuthMiddleware --> RuleEngine
    AuthMiddleware --> MLService

    RuleEngine -->|Atomic ACID Write| MySQL
    RuleEngine -->|Atomic Event Enqueue| OutboxTable
    
    OutboxPoller -->|Poll Unprocessed Events| OutboxTable
    OutboxPoller -->|Idempotent Upsert (replace_one)| MongoDB
    OutboxPoller -->|Mark Event Processed| OutboxTable

    RuleEngine -->|Broadcast Alert Events| WSManager
    WSManager -->|Push Notifications| DoctorWeb
```

---

## 2. Component Roles & Architectural Responsibilities

### 2.1 FastAPI Core Application Gateway (`smart-health-monitoring`)
- **Technology:** FastAPI 0.115, Python 3.12, Uvicorn, Pydantic v2, SQLAlchemy 2.0.
- **Responsibilities:**
  - Exposes 59 REST endpoints organized under dual prefixes (`/api/v1/...` and root `/...`) for universal client compatibility.
  - Enforces OAuth2 Password Bearer authentication with HMAC-SHA256 signed JSON Web Tokens (JWT).
  - Enforces strict Role-Based Access Control (RBAC) across four security tiers: `ADMIN`, `DOCTOR`, `NURSE`, and `PATIENT`.
  - Performs declarative request validation and serialization via Pydantic schemas.
  - Manages database session lifecycles using dependency injection (`get_db`).

### 2.2 Relational Database: MySQL 8 InnoDB (`database/mysql/`)
- **Technology:** MySQL 8.0, InnoDB Storage Engine, Alembic version-controlled migrations.
- **Responsibilities:**
  - Serves as the authoritative, transactional source of truth for all critical system entities.
  - Enforces declarative referential integrity via Foreign Keys with explicit `ON DELETE CASCADE` / `ON DELETE RESTRICT` semantics.
  - Validates medical domain values at the database level using `CHECK` constraints.
  - Executes database-level business logic through 2 Views, 2 Stored Functions, 2 Stored Procedures (with atomic transaction savepoints), and 1 Audit Trigger.
  - Houses the `analytics_outbox` table to guarantee that telemetry ingestion and event publishing occur within a single atomic database transaction.

### 2.3 Document Database: MongoDB Atlas (`database/mongodb/`)
- **Technology:** MongoDB Atlas 7.0 / 8.0, PyMongo & Motor asynchronous drivers.
- **Responsibilities:**
  - Serves as the high-throughput analytical query store.
  - Stores denormalized document structures (`telemetry_readings` and `clinical_alerts`) optimized for analytical reads.
  - Maintains compound indexes supporting efficient range scans and cohort filtering.
  - Executes 7 production aggregation pipelines delivering cohort rollups, time-bucketed trends, and clinical alert triage without placing analytical query load on the primary relational database.

### 2.4 Machine Learning Anomaly Detection Package (`health_analysis`)
- **Technology:** scikit-learn 1.8.0, joblib, NumPy, Pandas, Isolation Forest algorithm.
- **Responsibilities:**
  - Implements unsupervised anomaly detection on multi-parameter vital signs.
  - Transforms raw vitals into a 38-feature vector including rolling statistical moments, delta rates, and z-score standardizations.
  - Incorporates personal historical baselines via the `BaselineManager` to prevent false alarms for patients with chronic atypical physiology (e.g. baseline tachycardia).
  - Returns continuous anomaly scores, binary anomaly flags, and top feature contribution rationales.

### 2.5 Clinician Web Workstation (`AdityaDhakad1404-frontend-dbms`)
- **Technology:** React 19, TypeScript 6.0, Vite 8.3, TailwindCSS, Axios, Node native test runner.
- **Responsibilities:**
  - Provides an interactive clinical user interface for attending physicians and triage nurses.
  - Connects to FastAPI via Bearer token authenticated REST calls.
  - Consumes live physiological alerts and vital telemetry updates via real-time WebSocket streams authenticated through short-lived single-use tickets.
  - Supports dual operational modes: Live Backend Mode (`VITE_USE_MOCK_DATA=false`) and Standalone Demo Mode.

### 2.6 Streamlit Analytics Dashboard (`dashboard/app.py`)
- **Technology:** Streamlit 1.40, Plotly, Pandas.
- **Responsibilities:**
  - Provides healthcare administrators and researchers with deep population-level analytics.
  - Renders 8 dedicated analytical modules: Patient Telemetry, Longitudinal Trends, Cohort Aggregation, Data Quality & Coverage, Clinical Alert Analytics, SQL vs. NoSQL Benchmark Explorer, Live Synchronization Health, and System Topology.
  - Offers interactive engine toggles between Live Database mode and Cached Benchmark artifacts.

### 2.7 Patient Mobile Application (Flutter)
- **Status:** **Planned / External (Not present in repository workspace).**
- **Documentation Integrity:** As verified during the system audit, mobile client code is not included in the repository. Telemetry generation is modeled through Kaggle dataset replay scripts and authenticated RESTful ingestion endpoints.

---

## 3. Detailed End-to-End Data Flows

### 3.1 Telemetry Ingestion & Transactional Outbox Flow

The primary data ingestion pipeline guarantees that vital readings are permanently recorded in the relational database before being mirrored to the document store.

```mermaid
sequenceDiagram
    autonumber
    actor Sensor as Telemetry Source (Script / Sensor)
    participant API as FastAPI Ingestion Route (/api/v1/vitals)
    participant Auth as RBAC / Auth Dependency
    participant Rule as Clinical Rule Engine
    participant MySQL as MySQL 8 InnoDB (Operational Store)
    participant Outbox as analytics_outbox Table
    participant Worker as Background Outbox Worker
    participant Mongo as MongoDB Atlas (Analytics Mirror)
    participant WS as WebSocket Manager
    participant Clinician as Clinician Dashboard (React)

    Sensor->>API: POST /api/v1/vitals (Patient ID, Vitals Payload)
    API->>Auth: Validate JWT Bearer Token (NURSE / DOCTOR / ADMIN)
    Auth-->>API: Authorized
    API->>Rule: Evaluate Clinical Thresholds (HR, SpO2, Temp, BP)
    Rule-->>API: Clinical State & Alert Evaluation
    
    rect rgb(240, 248, 255)
        Note over API,Outbox: Single Atomic ACID Transaction
        API->>MySQL: INSERT INTO vitals_readings (...)
        alt Vital Signs Trigger Clinical Alert
            API->>MySQL: INSERT INTO clinical_alerts (...)
        end
        API->>Outbox: INSERT INTO analytics_outbox (event_type, payload, status='PENDING')
        API->>MySQL: COMMIT Transaction
    end

    API-->>Sensor: 201 Created (Reading ID, Recorded Timestamp)

    par Asynchronous Alert Notification
        opt Alert Generated
            API->>WS: Broadcast Alert Event (JSON)
            WS->>Clinician: Push Real-Time Alert to Connected Doctors
        end
    and Asynchronous Outbox Synchronization
        Worker->>Outbox: SELECT * FROM analytics_outbox WHERE status='PENDING' LIMIT 100 FOR UPDATE
        loop For each pending event
            Worker->>Mongo: db.telemetry_readings.replace_one({source_event_id: id}, doc, upsert=True)
            Worker->>Outbox: UPDATE analytics_outbox SET status='PROCESSED', processed_at=NOW() WHERE id=event_id
        end
    end
```

### 3.2 Real-Time WebSocket Ticket Authentication Flow

To protect WebSocket streaming endpoints from credential leakage in URL query parameters, the system uses a **Short-Lived Ticket Exchange Protocol**:

```mermaid
sequenceDiagram
    autonumber
    actor Doctor as Doctor / Clinician
    participant UI as React Clinician Web Dashboard
    participant API as FastAPI Gateway (/api/v1/ws-ticket)
    participant WS as WebSocket Endpoint (/api/v1/ws/clinician)
    participant WSMgr as WebSocket Connection Manager

    Doctor->>UI: Logs in with username & password
    UI->>API: POST /api/v1/auth/login (OAuth2 Password Form)
    API-->>UI: 200 OK (access_token, token_type: Bearer)

    Note over UI,API: Establishing Secure Real-Time Stream
    UI->>API: POST /api/v1/ws-ticket (Header: Authorization: Bearer <JWT>)
    API->>API: Validate JWT & User Roles (DOCTOR / NURSE)
    API->>API: Generate Single-Use Ticket (TTL: 300 seconds)
    API-->>UI: 200 OK {"ticket": "ws_ticket_abc123...", "expires_in": 300}

    UI->>WS: Connect: wss://host/api/v1/ws/clinician?ticket=ws_ticket_abc123...
    WS->>WSMgr: Validate & Consume Ticket
    alt Ticket Valid & Not Expired
        WSMgr-->>WS: Ticket Accepted (Register Connection)
        WS-->>UI: WebSocket Connection Upgraded (101 Switching Protocols)
        WS-->>UI: Send Initial Handshake Frame: {"event": "CONNECTED", "role": "DOCTOR"}
    else Ticket Expired or Invalid
        WSMgr-->>WS: Reject Ticket
        WS-->>UI: Close Connection (Code 4003: Forbidden / Invalid Ticket)
    end
```

### 3.3 Machine Learning Anomaly Assessment Flow

```mermaid
sequenceDiagram
    autonumber
    actor Clinician as Attending Physician
    participant UI as Clinician Dashboard / Streamlit
    participant API as FastAPI Route (/api/v1/patients/{id}/assess)
    participant DB as MySQL Repository
    participant FE as ML Feature Engineer (38 Features)
    participant BM as BaselineManager
    participant Model as Isolation Forest Model (iforest_v1)

    Clinician->>UI: Clicks "Assess Anomaly Risk" for Patient
    UI->>API: POST /api/v1/patients/{id}/assess
    API->>DB: Fetch Recent Vitals History (Last N Readings)
    DB-->>API: Longitudinal Telemetry Series

    API->>FE: Transform Series into Feature Vector
    Note over FE: Compute rolling means, variances, min/max,<br/>delta rates & standardized z-scores (38 features)
    FE-->>API: Extracted Feature Vector (1x38)

    API->>BM: Retrieve Patient Baseline Profile
    alt Patient has Established Baseline
        BM-->>API: Baseline Mean & Standard Deviations
        API->>FE: Apply Personalized Patient Centering
    else New Patient
        BM-->>API: Fallback to Population Cohort Baseline
    end

    API->>Model: model.score_samples(feature_vector)
    Model-->>API: Raw Anomaly Score & Prediction Flag (-1: Anomaly, 1: Normal)

    API->>API: Map to Clinical Risk Probability [0.0, 1.0] & Feature Attributions
    API-->>UI: 200 OK {"patient_id": id, "is_anomaly": true, "anomaly_score": 0.78, "top_contributing_features": ["hr_rolling_std_5", "spo2_delta_rate"]}
    UI-->>Clinician: Render Anomaly Badge, Radar Chart & Feature Breakdown
```

---

## 4. Consistency Guarantees & Distributed Architecture Trade-Offs

### 4.1 Why Distributed Two-Phase Commit (2PC) Was Deliberately Avoided
In a distributed cloud environment where MySQL runs locally or on a managed cloud VM and MongoDB is hosted on MongoDB Atlas, traditional distributed transactions (XA / 2PC) introduce severe operational risks:
- **Blocking Coordinator Problem:** If either network boundary experiences latency or a temporary partition, transactions block, holding locks on primary relational tables and starving incoming patient telemetry writes.
- **Latency Amplification:** Incurring two sequential network round-trips to MongoDB Atlas for every single sensor reading would degrade ingestion throughput by orders of magnitude.

### 4.2 The Implemented Guarantee: Dual-Layered Eventual Consistency
To ensure maximum availability, resilience, and operational safety:
1. **Intra-Relational Consistency (Strict ACID):** All clinical patient writes, vital sign insertions, and outbox event enqueue operations occur within a single atomic MySQL InnoDB transaction. If any constraint fails, the entire transaction rolls back cleanly.
2. **Inter-Database Consistency (Eventual Consistency with Idempotent Upserts):** The background outbox poller asynchronously reads pending events from `analytics_outbox` and mirrors them into MongoDB Atlas using `replace_one(filter={"source_event_id": event_id}, replacement=doc, upsert=True)`.
   - **Idempotency Guarantee:** If a network failure occurs during MongoDB synchronization and the worker retries the event, the upsert operation replaces the identical document without creating duplicates.
   - **Fault Tolerance:** If MongoDB Atlas becomes temporarily unreachable, incoming patient care and relational data storage proceed uninterrupted. Events accumulate safely in `analytics_outbox` and resume syncing immediately upon connection restoration.
