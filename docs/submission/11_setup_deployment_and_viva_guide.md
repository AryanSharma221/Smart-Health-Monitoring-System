# 11. Reproducible Setup, Deployment & Academic Viva Guide

**Document:** Environment Setup, Runbook & Examination Defense Guide  
**Project:** AI-Powered Smart Health Monitoring System  
**Auditor & Lead Architect:** Senior Software Architect & Lead Database Reliability Engineer  
**Date:** 14 October 2026  
**System Version:** 3.0.0  

---

## 1. Environment Prerequisites & Runtime Versions

The system has been verified on the following verified runtime baselines:
- **Operating System:** Windows 10/11 64-bit / Ubuntu Linux 22.04 LTS
- **Python Runtime:** Python `3.12.4` or `3.12.9`
- **Node.js Runtime:** Node.js `v24.14.0` (npm `11.9.0`)
- **Relational Engine:** MySQL `8.0` with InnoDB Storage Engine
- **Document Store:** MongoDB Atlas `7.0` / `8.0` (or local MongoDB Community / `mongomock`)

---

## 2. Step-by-Step Installation & Configuration

### 2.1 Backend Core Setup (`smart-health-monitoring`)

1. **Clone and Navigate:**
   ```bash
   cd smart-health-monitoring
   ```
2. **Create and Activate Python Virtual Environment:**
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   # Linux / macOS:
   source .venv/bin/activate
   ```
3. **Install Dependencies:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e .
   ```
4. **Environment Variables Configuration:**
   Copy `.env.example` to `.env` and configure your local credentials:
   ```ini
   # Database Configuration (MySQL)
   MYSQL_HOST=localhost
   MYSQL_PORT=3306
   MYSQL_USER=app_user
   MYSQL_PASSWORD=your_secure_password
   MYSQL_DATABASE=smart_health

   # Document Database (MongoDB Atlas)
   MONGODB_URI=mongodb+srv://<username>:<password>@cluster0.mongodb.net/smart_health_analytics?retryWrites=true&w=majority
   MONGODB_DATABASE=smart_health_analytics

   # Security & JWT Tokens
   JWT_SECRET_KEY=replace_with_openssl_rand_hex_32
   JWT_ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=60

   # Operational Flags
   ENVIRONMENT=development
   ENABLE_OUTBOX_WORKER=true
   ```

5. **Apply Database Migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Seed Initial Dataset (Kaggle Healthcare Telemetry):**
   ```bash
   python -m scripts.import_kaggle_dataset --file="data/kaggle_health_dataset.csv"
   ```

---

### 2.2 Clinician Web Dashboard Setup (`apps/doctor_web`)

1. **Navigate to Frontend Workspace:**
   ```bash
   cd ../AdityaDhakad1404-frontend-dbms/apps/doctor_web
   ```
2. **Install Node Dependencies:**
   ```bash
   npm install
   ```
3. **Configure Environment:**
   Create `.env.local` in `apps/doctor_web/`:
   ```ini
   # Set to false to connect to live FastAPI backend; true for offline mock presentation
   VITE_USE_MOCK_DATA=false
   VITE_API_URL=http://localhost:8000
   VITE_WS_URL=ws://localhost:8000
   ```

---

## 3. System Startup & Verification Commands

### Start All Services (3 Terminals):

```bash
# Terminal 1: Start FastAPI Gateway (Port 8000)
cd smart-health-monitoring
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start React Clinician Dashboard (Port 5173)
cd AdityaDhakad1404-frontend-dbms/apps/doctor_web
npm run dev

# Terminal 3: Start Streamlit Analytics Dashboard (Port 8501)
cd smart-health-monitoring
streamlit run dashboard/app.py --server.port 8501
```

### Verification Endpoints:
- **FastAPI OpenAPI Interactive Docs:** `http://localhost:8000/docs`
- **FastAPI Health Readiness Probe:** `http://localhost:8000/health/ready`
- **React Clinician Dashboard:** `http://localhost:5173`
- **Streamlit Analytics Dashboard:** `http://localhost:8501`

---

## 4. Academic Viva Examination Preparation & Architectural Defense

The following questions represent likely focal points during academic evaluation, defense, and viva examinations:

---

### Q1: Why did you choose a dual-database architecture (MySQL + MongoDB) instead of using a single database?
**Defense Answer:**
Healthcare applications have divergent operational characteristics.
- Patient profiles, role permissions, and clinical alerts represent **transactional core data** requiring strict ACID compliance, declarative referential integrity, and relational normalization to prevent anomalies. MySQL 8 InnoDB provides this authoritative foundation.
- High-volume physiological telemetry represents **time-series append-heavy analytical data**. Storing millions of sensor events in a relational table degrades query performance and complicates schema evolution when new sensors are introduced.
- By mirroring telemetry into MongoDB Atlas, we execute complex aggregation pipelines across millions of readings without placing lock contention or analytical compute load on our primary transactional database.

---

### Q2: How do you guarantee consistency between MySQL and MongoDB without distributed two-phase commit (2PC)?
**Defense Answer:**
We implement the **Transactional Outbox Pattern**:
1. When a vital reading is ingested, the reading record and an outbox event are inserted into MySQL inside the **exact same atomic ACID transaction**.
2. If the transaction succeeds, the event is guaranteed to be in the `analytics_outbox` table.
3. An asynchronous background worker polls this outbox and replicates documents to MongoDB using **idempotent upserts** (`replace_one` keyed on `source_event_id`).
4. This delivers **Guaranteed Eventual Consistency**. Distributed 2PC (XA) was deliberately avoided because it creates tight coupling across network boundaries; if MongoDB Atlas suffered a temporary network hiccup, 2PC would block all incoming patient vitals in MySQL, causing critical telemetry data loss.

---

### Q3: How does your relational schema demonstrate 3NF / BCNF normalization?
**Defense Answer:**
Our MySQL schema comprises 17 tables where every table satisfies:
1. **1NF:** All columns store atomic values (e.g. vital metrics are individual floating-point columns, not JSON strings).
2. **2NF:** Non-key attributes are fully functionally dependent on candidate keys with zero partial dependencies on composite keys.
3. **3NF & BCNF:** Transitive functional dependencies are eliminated. For instance, user credentials (`users`), clinical patient profiles (`patient_profiles`), doctor assignments (`doctor_profiles`), and sensor events (`ingestion_events`) are isolated in separate tables. Every non-trivial functional dependency $X \rightarrow Y$ has a determinant $X$ that is a superkey.

---

### Q4: Why is Isolation Forest used for physiological anomaly detection instead of a supervised classifier?
**Defense Answer:**
Supervised classification requires large, accurately labeled clinical datasets containing confirmed instances of thousands of rare medical conditions. In clinical telemetry:
1. Normal physiology is plentiful, but acute emergency events are sparse (severe class imbalance).
2. Clinical anomalies take unpredictable, novel forms that supervised models fail to generalize.
3. Isolation Forest operates **unsupervised**, isolating anomalies by measuring how shallowly observations are split across randomized decision trees. It requires zero ground-truth labels and natively assigns continuous anomaly scores based on multi-parameter distance from normal physiological equilibrium.

---

### Q5: Why was MySQL faster than MongoDB in Workloads A–F, but MongoDB was 14.5x faster in Workload G?
**Defense Answer:**
- In Workloads A–F, MySQL queries benefited from **in-engine composite B-tree covering indexes** (e.g. `(patient_id, recorded_at DESC)`) where the entire query was satisfied directly from memory pages without touching table data blocks.
- In Workload G (Clinical Alert Triage), MongoDB's denormalized document structure stored pre-aggregated alerts with embedded patient identifiers. MongoDB computed the aggregation in **0.06 ms** versus MySQL's **0.84 ms** because MongoDB scanned a small, dedicated in-memory index without executing multi-table relational joins or checking foreign key constraints.

---

### Q6: How does the system prevent accidental discharge of unstable patients?
**Defense Answer:**
We implemented the stored procedure **`sp_safe_patient_discharge`** using **ACID transactions with named savepoints**:
```sql
START TRANSACTION;
SAVEPOINT before_discharge;
SELECT COUNT(*) INTO active_critical_count FROM alerts 
WHERE patient_id = p_id AND severity IN ('HIGH', 'CRITICAL') AND status = 'ACTIVE';

IF active_critical_count > 0 THEN
    ROLLBACK TO SAVEPOINT before_discharge;
    SET p_success = FALSE;
    SET p_message = 'Cannot discharge patient with active CRITICAL or HIGH alerts.';
    COMMIT;
...
```
The transaction atomically validates clinical safety before committing patient deactivation.

---

### Q7: Where is the Flutter mobile patient application?
**Defense Answer:**
To maintain strict academic and professional integrity, we explicitly report that the Flutter mobile application is a **planned external integration component** and is not packaged within the current repository workspace. 
All patient telemetry ingestion and historical viewing functionalities are fully modeled, implemented, and verified through our RESTful ingestion endpoints (`POST /api/v1/vitals/`) and real Kaggle healthcare dataset bulk replay scripts.
