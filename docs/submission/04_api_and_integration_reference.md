# 04. API Contract & Integration Interface Reference

**Document:** API Specification & Integration Catalog  
**Project:** AI-Powered Smart Health Monitoring System  
**Auditor & API Lead:** Senior Software Architect & Integration Engineer  
**Date:** 14 October 2026  
**System Version:** 3.0.0 (FastAPI Core Gateway)  
**Mount Strategy:** Dual Prefix Architecture (All routes accessible via `/api/v1/...` and root `/...`)  

---

## 1. Architectural Routing & Security Foundations

The FastAPI backend exposes 59 distinct operational endpoints organized across 11 functional modules. To ensure backward and cross-client compatibility:
- **Dual Prefix Mounting:** Routers are registered both at the `/api/v1` namespace and at the root `/` path.
- **Authentication Scheme:** HTTP Bearer token conforming to the OAuth2 Password Flow. Tokens are HS256-signed JSON Web Tokens containing `sub` (user ID), `username`, and `role`.
- **Role-Based Access Control (RBAC):** Hierarchically enforced via dependency injection:
  - `ADMIN`: Unrestricted platform configuration, user provisioning, benchmark runs, backup/restore.
  - `DOCTOR`: Access to patient records, telemetry trends, alert acknowledgment, patient discharge, and messaging.
  - `NURSE`: Telemetry recording, vital sign inspection, alert acknowledgment, and communication.
  - `PATIENT`: Self-telemetry inspection, vital history, and attending physician communication.

---

## 2. API Endpoint Catalog by Module

### 2.1 Authentication & User Management (`app/routers/auth.py`)

| Method & Route | Purpose | Auth & RBAC | Request Schema | Response Schema | Status & Error Codes | Test Verification |
|---|---|---|---|---|---|---|
| `POST /api/v1/auth/register` | Register new system user | Public | `UserRegisterRequest` (`username`, `email`, `password`, `role`) | `UserResponse` (`id`, `username`, `email`, `role`, `created_at`) | `201 Created`<br>`400` User/Email exists<br>`422` Validation | `tests/test_auth.py` |
| `POST /api/v1/auth/login` | Authenticate user and issue JWT | Public | `OAuth2PasswordRequestForm` (`username`, `password`) | `TokenResponse` (`access_token`, `token_type`, `user`) | `200 OK`<br>`401` Invalid credentials | `tests/test_auth.py` |
| `POST /api/v1/auth/refresh` | Exchange valid refresh token | Public | `TokenRefreshRequest` (`refresh_token`) | `TokenResponse` (`access_token`, `token_type`) | `200 OK`<br>`401` Expired/Invalid token | `tests/test_auth.py` |
| `GET /api/v1/auth/me` | Retrieve authenticated profile | Bearer (Any) | None | `UserResponse` | `200 OK`<br>`401` Unauthorized | `tests/test_auth.py` |
| `POST /api/v1/auth/logout` | Invalidate session & log audit | Bearer (Any) | None | `{"status": "logged_out"}` | `200 OK`<br>`401` Unauthorized | `tests/test_auth.py` |
| `POST /api/v1/auth/change-password` | Change user password | Bearer (Any) | `ChangePasswordRequest` (`old_password`, `new_password`) | `{"status": "password_changed"}` | `200 OK`<br>`400` Incorrect old password | `tests/test_auth.py` |

---

### 2.2 Patient Management (`app/routers/patients.py`)

| Method & Route | Purpose | Auth & RBAC | Request Schema / Parameters | Response Schema | Status & Error Codes | Test Verification |
|---|---|---|---|---|---|---|
| `GET /api/v1/patients/` | List patients with pagination | Bearer (`DOCTOR`, `NURSE`, `ADMIN`) | Query: `skip` (int, default 0), `limit` (int, default 50) | `List[PatientResponse]` | `200 OK`<br>`401` Unauthorized<br>`403` Forbidden | `tests/test_patients.py` |
| `GET /api/v1/patients/{id}` | Get detailed patient profile | Bearer (`DOCTOR`, `NURSE`, `ADMIN`, `PATIENT` self) | Path: `id` (int) | `PatientDetailResponse` (Demographics, vitals, active alerts) | `200 OK`<br>`404` Patient Not Found | `tests/test_patients.py` |
| `POST /api/v1/patients/` | Create new patient record | Bearer (`DOCTOR`, `ADMIN`) | `PatientCreateRequest` | `PatientResponse` | `201 Created`<br>`422` Validation Error | `tests/test_patients.py` |
| `GET /api/v1/patients/{id}/vitals/latest` | Get current vital signs via View | Bearer (`DOCTOR`, `NURSE`, `PATIENT` self) | Path: `id` (int) | `VitalsReadingResponse` | `200 OK`<br>`404` No vitals recorded | `tests/test_patients.py` |
| `POST /api/v1/patients/{id}/discharge` | Execute safe discharge procedure | Bearer (`DOCTOR`, `ADMIN`) | Path: `id` (int) | `DischargeResponse` (`success`, `message`) | `200 OK`<br>`400` Active alerts blocking discharge | `tests/test_patients.py` |

---

### 2.3 Vital Signs & Telemetry (`app/routers/vitals.py`)

| Method & Route | Purpose | Auth & RBAC | Request Schema / Parameters | Response Schema | Status & Error Codes | Test Verification |
|---|---|---|---|---|---|---|
| `POST /api/v1/vitals/` | Record new physiological telemetry | Bearer (`NURSE`, `DOCTOR`, `ADMIN`) | `VitalsCreateRequest` (`patient_id`, `heart_rate`, `spo2`, `systolic_bp`, `diastolic_bp`, `temperature`) | `VitalsReadingResponse` (`id`, `patient_id`, `recorded_at`, `is_abnormal`) | `201 Created`<br>`400` Domain constraint violated | `tests/test_vitals.py` |
| `GET /api/v1/vitals/patient/{id}` | Query longitudinal telemetry | Bearer (`DOCTOR`, `NURSE`, `PATIENT` self) | Path: `id` (int), Query: `start_date`, `end_date`, `limit` | `List[VitalsReadingResponse]` | `200 OK`<br>`404` Patient not found | `tests/test_vitals.py` |
| `POST /api/v1/vitals/batch` | Bulk insert vital readings | Bearer (`ADMIN`, `NURSE`) | `List[VitalsCreateRequest]` | `BatchIngestResponse` (`inserted_count`, `batch_id`) | `201 Created`<br>`422` Validation | `tests/test_vitals.py` |
| `GET /api/v1/vitals/summary` | Population-wide vitals rollup | Bearer (`DOCTOR`, `ADMIN`) | None | `VitalsSummaryResponse` (Averages, abnormal counts) | `200 OK` | `tests/test_vitals.py` |

---

### 2.4 Clinical Alert Management (`app/routers/alerts.py`)

| Method & Route | Purpose | Auth & RBAC | Request Schema / Parameters | Response Schema | Status & Error Codes | Test Verification |
|---|---|---|---|---|---|---|
| `GET /api/v1/alerts/` | List alerts with severity filters | Bearer (`DOCTOR`, `NURSE`, `ADMIN`) | Query: `status`, `severity`, `skip`, `limit` | `List[AlertResponse]` | `200 OK`<br>`401` Unauthorized | `tests/test_alerts.py` |
| `GET /api/v1/alerts/{id}` | Get single alert details | Bearer (`DOCTOR`, `NURSE`, `ADMIN`) | Path: `id` (int) | `AlertDetailResponse` (with status audit trail) | `200 OK`<br>`404` Alert not found | `tests/test_alerts.py` |
| `POST /api/v1/alerts/{id}/acknowledge` | Acknowledge active alert | Bearer (`DOCTOR`, `NURSE`) | Path: `id` (int), Body: `AcknowledgeAlertRequest` (`notes`) | `AlertResponse` | `200 OK`<br>`400` Alert already acknowledged | `tests/test_alerts.py` |
| `POST /api/v1/alerts/{id}/resolve` | Mark clinical alert resolved | Bearer (`DOCTOR`) | Path: `id` (int), Body: `ResolveAlertRequest` (`resolution_notes`) | `AlertResponse` | `200 OK`<br>`400` Cannot resolve inactive alert | `tests/test_alerts.py` |
| `POST /api/v1/alerts/{id}/dismiss` | Dismiss false positive alert | Bearer (`DOCTOR`, `ADMIN`) | Path: `id` (int), Body: `DismissAlertRequest` (`reason`) | `AlertResponse` | `200 OK` | `tests/test_alerts.py` |
| `GET /api/v1/alerts/summary` | Aggregated triage statistics | Bearer (`DOCTOR`, `NURSE`, `ADMIN`) | None | `AlertSummaryResponse` (Active by severity) | `200 OK` | `tests/test_alerts.py` |

---

### 2.5 Machine Learning Inference & Assessments (`app/routers/predictions.py`)

| Method & Route | Purpose | Auth & RBAC | Request Schema / Parameters | Response Schema | Status & Error Codes | Test Verification |
|---|---|---|---|---|---|---|
| `GET /api/v1/predictions/status` | Verify ML engine health & model version | Public / Bearer (Any) | None | `{"status": "available", "model": "iforest_v1", "version": "1.0.0", "features_expected": 38}` | `200 OK` | `tests/test_predictions.py` |
| `GET /api/v1/predictions/model-info` | Model metadata & baseline counts | Bearer (`DOCTOR`, `ADMIN`) | None | `ModelInfoResponse` (Model hyperparameters, baseline count) | `200 OK` | `tests/test_predictions.py` |
| `POST /api/v1/predictions/patients/{id}/assess` | Assess patient anomaly risk | Bearer (`DOCTOR`, `NURSE`) | Path: `id` (int), Optional Body: `AssessmentOverride` | `AssessmentResponse` (`is_anomaly`, `anomaly_score`, `contributing_features`) | `200 OK`<br>`404` Insufficient telemetry | `tests/test_predictions.py` |
| `POST /api/v1/predictions/batch-assess` | Batch anomaly scan across cohort | Bearer (`DOCTOR`, `ADMIN`) | Body: `List[int]` (Patient IDs) | `List[AssessmentResponse]` | `200 OK` | `tests/test_predictions.py` |

---

### 2.6 Real-Time WebSockets & Ticket Authentication (`app/routers/websockets.py`)

| Method & Route | Protocol | Auth & RBAC | Request Schema / Query Params | Event Payload Format | Status Codes | Test Verification |
|---|---|---|---|---|---|---|
| `POST /api/v1/ws-ticket` | HTTP REST | Bearer (`DOCTOR`, `NURSE`) | None | `{"ticket": str, "expires_in": 300}` | `200 OK`<br>`401` Unauthorized | `tests/test_websockets.py` |
| `GET /api/v1/ws/clinician` | WebSocket | Query: `ticket` | Connection Upgrade | JSON Frames: `{"event": "ALERT_NEW" \| "VITALS_UPDATE", "data": {...}}` | `101 Switching Protocols`<br>`4003` Invalid ticket | `tests/test_websockets.py` |
| `GET /api/v1/ws/patient` | WebSocket | Query: `ticket` | Connection Upgrade | JSON Frames: `{"event": "VITALS_ACK", "data": {...}}` | `101 Switching Protocols`<br>`4003` Invalid ticket | `tests/test_websockets.py` |

---

### 2.7 Analytical Pipelines (`app/routers/analytics.py`)

| Method & Route | Purpose | Auth & RBAC | Parameters | Response Schema | Backend Execution | Test Verification |
|---|---|---|---|---|---|---|
| `GET /api/v1/analytics/dataset-overview` | Dataset metrics & abnormal ratios | Bearer (`DOCTOR`, `ADMIN`) | None | `DatasetOverviewResponse` | MongoDB Pipeline A | `tests/test_mongodb_analytics.py` |
| `GET /api/v1/analytics/patients/{id}/summary` | Per-patient statistical rollup | Bearer (`DOCTOR`, `NURSE`) | Path: `id` (int) | `PatientAnalyticsSummary` | MongoDB Pipeline B | `tests/test_mongodb_analytics.py` |
| `GET /api/v1/analytics/time-series` | Hourly bucketed vital trends | Bearer (`DOCTOR`, `ADMIN`) | Query: `patient_id`, `bucket_hours` | `List[TimeBucketResponse]` | MongoDB Pipeline D | `tests/test_mongodb_analytics.py` |
| `GET /api/v1/analytics/provenance` | Telemetry source data audit | Bearer (`ADMIN`) | None | `ProvenanceResponse` | MongoDB Pipeline F | `tests/test_mongodb_analytics.py` |
| `GET /api/v1/analytics/data-quality` | Missing data & gap analysis | Bearer (`ADMIN`) | None | `DataQualityResponse` | MongoDB Pipeline G | `tests/test_mongodb_analytics.py` |

---

### 2.8 Benchmarks, Backup & System Probes (`app/routers/`)

| Method & Route | Module | Purpose | Auth & RBAC | Key Parameters | Success Output | Test Verification |
|---|---|---|---|---|---|---|
| `POST /api/v1/benchmarks/run` | `benchmarks.py` | Trigger SQL vs. NoSQL benchmark suite | Bearer (`ADMIN`) | Query: `iterations`, `warmup` | `BenchmarkRunSummary` (Raw latencies, equivalence status) | `tests/test_benchmarks.py` |
| `GET /api/v1/benchmarks/results/latest` | `benchmarks.py` | Fetch most recent benchmark run | Bearer (`ADMIN`, `DOCTOR`) | None | `BenchmarkRunDetail` | `tests/test_benchmarks.py` |
| `POST /api/v1/backup/create` | `backup.py` | Create physical/logical DB backup | Bearer (`ADMIN`) | Body: `BackupRequest` (`target`) | `BackupResult` (Artifact path, checksum, size) | `tests/test_backup_and_recovery.py` |
| `POST /api/v1/backup/restore-test` | `backup.py` | Execute non-destructive restore drill | Bearer (`ADMIN`) | Body: `RestoreTestRequest` | `RestoreTestResult` (Verification status, row count) | `tests/test_backup_and_recovery.py` |
| `GET /health` | `system.py` | Service health & environment probe | Public | None | `{"status": "healthy", "version": "3.0.0"}` | `tests/test_system.py` |
| `GET /health/ready` | `system.py` | Database connectivity readiness probe | Public | None | `{"status": "ready", "database": "connected"}` | `tests/test_system.py` |

---

## 3. Frontend-to-Backend Integration Mapping (`doctor_web`)

The React clinician workstation communicates with FastAPI via standardized service modules located in `apps/doctor_web/src/api/`:

| Frontend Service Module | Frontend Method | Backend Endpoint Called | Authentication | Response Handling & State Updates |
|---|---|---|---|---|
| `authService.ts` | `login(credentials)` | `POST /api/v1/auth/login` | None | Stores `access_token` in memory/localStorage; sets default Axios Bearer header |
| `authService.ts` | `refreshToken(token)` | `POST /api/v1/auth/refresh` | None | Updates active token; re-dispatches queued HTTP requests |
| `authService.ts` | `getCurrentUser()` | `GET /api/v1/auth/me` | Bearer | Populates `UserContext` with doctor name, license, and roles |
| `patientService.ts` | `getPatients(params)` | `GET /api/v1/patients/` | Bearer | Maps backend `PatientResponse` to `Patient[]` table state |
| `patientService.ts` | `getPatientDetails(id)` | `GET /api/v1/patients/{id}` | Bearer | Populates patient overview, past diagnoses, and medications |
| `patientService.ts` | `getPatientVitals(id)` | `GET /api/v1/vitals/patient/{id}` | Bearer | Renders multi-parameter interactive Plotly telemetry charts |
| `patientService.ts` | `getPatientAlerts(id)` | `GET /api/v1/alerts/patient/{id}` | Bearer | Renders alert triage cards with severity color-coding |
| `patientService.ts` | `acknowledgeAlert(id)` | `POST /api/v1/alerts/{id}/acknowledge` | Bearer | Optimistically updates alert status to `ACKNOWLEDGED` |
| `wsService.ts` | `requestTicket()` | `POST /api/v1/ws-ticket` | Bearer | Receives 5-minute single-use ticket string |
| `wsService.ts` | `connectStream(ticket)` | `GET /api/v1/ws/clinician?ticket=...` | Ticket Query | Establishes WebSocket; dispatches live telemetry events to Redux/Context |
| `predictionService.ts`| `assessPatientRisk(id)` | `POST /api/v1/predictions/patients/{id}/assess` | Bearer | Updates ML Anomaly Badge and radar feature contribution chart |
