# End-to-End API Contract Inventory & Interface Catalog

**Project:** AI-Powered Smart Health Monitoring System  
**Version:** 3.0.0 (FastAPI Gateway)  
**Mount Strategy:** Dual Prefix Routing (routes mounted under `/api/v1/...` and `root /...` for universal client compatibility)  
**Auditor:** Senior Software Architect & API Lead  
**Audit Date:** 2026-10-14  

---

## 1. System Health & Operational Probes

| Route & Method | Request Params | Success Response | Status | Auth Required | RBAC Rules | Database Side Effects | Frontend Consumer |
|---|---|---|---|---|---|---|---|
| `GET /health` | None | `{"status": "healthy", "service": str, "version": "3.0.0", "environment": str, "is_simulated": true, "notice": str}` | `200 OK` | Public | None | None | Docker, Kubernetes, Monitoring Agents |
| `GET /health/live` | None | `{"status": "alive", "service": str, "version": "3.0.0"}` | `200 OK` | Public | None | None | Container Orchestrator Liveness Probe |
| `GET /health/ready` | None | `{"status": "ready", "database": "connected", "mongodb_mirror": str, "message": str}` | `200 OK` / `503 Service Unavailable` | Public | None | Checks live MySQL connectivity via `SELECT 1` | Container Orchestrator Readiness Probe |
| `GET /health/db` | None | `{"status": "connected", "database": "mysql_innodb"}` | `200 OK` | Public | None | Executes `SELECT 1` on SQLAlchemy session | Internal Ops & Diagnostic Tooling |
| `GET /health/mongodb` | None | `{"status": str, "database": str, "endpoint": str, "outbox_queue": dict}` | `200 OK` | Public | None | Inspects MongoDB Atlas ping and outbox stats (credentials redacted) | Streamlit System Status, Internal Ops |

---

## 2. Authentication & Identity Router (`/auth` and `/api/v1/auth`)

| Route & Method | Request Body / Schema | Success Response | Status | Auth Required | RBAC Rules | Error Status Codes | Database Side Effects | Frontend Consumers |
|---|---|---|---|---|---|---|---|---|
| `POST /auth/register` | `UserRegisterRequest`<br>`email: EmailStr`<br>`password: str (>=8)`<br>`role: "patient"`<br>`first_name: str`<br>`last_name: str`<br>`date_of_birth: Optional[date]`<br>`gender: Optional[str]` | `UserProfileResponse`<br>`user_id: str`<br>`email: str`<br>`role: "patient"`<br>`is_active: bool`<br>`created_at: datetime` | `201 Created` | Public | Restricted strictly to `role="patient"`. Attempts to register `doctor` or `admin_operator` rejected. | `400` (Validation),<br>`403` (Privilege Escalation),<br>`409` (Email Conflict),<br>`422` (Malformed JSON) | Creates `users` record (bcrypt hash) and `patient_profiles` record in single transaction. | Flutter Patient App (Sign Up screen) |
| `POST /auth/login` | `UserLoginRequest`<br>`email: EmailStr`<br>`password: str` | `TokenResponse`<br>`access_token: str`<br>`token_type: "bearer"`<br>`expires_in: int (seconds)`<br>`user_id: str`<br>`role: str` | `200 OK` | Public | None (validates active user and password hash) | `401` (Invalid Credentials / Disabled Account),<br>`422` (Malformed) | Appends successful/failed authentication audit log entry. | React Clinician Dashboard, Flutter Patient App |
| `GET /auth/me` | None | `UserProfileResponse`<br>`user_id: str`<br>`email: str`<br>`role: str`<br>`is_active: bool`<br>`created_at: datetime` | `200 OK` | Bearer JWT | Permitted for any active authenticated user | `401` (Missing / Expired / Tampered JWT) | Reads current user from database; strictly omits password hash. | React Clinician Dashboard, Flutter Patient App |
| `POST /auth/logout` | None | `{"status": "success", "message": "User logged out successfully.", "user_id": str}` | `200 OK` | Bearer JWT | Authenticated user | `401` (Unauthorized) | Appends `AUTH_LOGOUT` audit log record. | React Clinician Dashboard, Flutter Patient App |
| `GET /auth/verify-patient-access/{patient_id}` | Path param: `patient_id: str` | `{"patient_id": str, "authorized": true, "user_id": str, "role": str}` | `200 OK` | Bearer JWT | Patient (own record only), Doctor (active assignment only), Admin | `401` (Unauthorized),<br>`403` (Forbidden / Unassigned),<br>`404` (Not Found) | None (Authorization probe) | API test harnesses, Frontend navigation guards |

---

## 3. Patient Health Telemetry Router (`/patients` and `/api/v1/patients`)

| Route & Method | Request Params | Success Response | Status | Auth Required | RBAC Rules | Error Codes | Database Side Effects | Frontend Consumers |
|---|---|---|---|---|---|---|---|---|
| `GET /patients/{patient_id}/readings` | Path: `patient_id`<br>Query: `start_time`, `end_time`, `page (>=1)`, `page_size (1-100)`, `source`, `is_simulated` | `PaginatedReadingsResponse`<br>`items: List[PatientReadingResponse]`<br>`total_count: int`<br>`page: int`<br>`page_size: int`<br>`total_pages: int`<br>`has_next: bool`<br>`has_previous: bool` | `200 OK` | Bearer JWT | Patient (own only), Doctor (assigned only), Admin | `400` (Invalid time range `start > end`),<br>`401` (Unauthorized),<br>`403` (Forbidden) | Reads `ingestion_events` and joined `vitals_readings`. | React Clinician Dashboard (Vitals Chart), Flutter Patient App (History) |
| `GET /patients/{patient_id}/readings/latest` | Path: `patient_id` | `PatientReadingResponse`<br>`event_id: str`<br>`patient_id: str`<br>`measured_at: datetime`<br>`source: str`<br>`is_simulated: bool`<br>`metrics: dict` (`heart_rate`, `spo2`, `temperature_f`, `temperature_c`) | `200 OK` | Bearer JWT | Patient (own only), Doctor (assigned only), Admin | `401` (Unauthorized),<br>`403` (Forbidden),<br>`404` (No readings recorded) | Reads single most recent observation event for patient. | React Clinician Dashboard (Patient Card), Flutter Patient App (Home Screen) |

---

## 4. Clinical Alerts Router (`/alerts`, `/patients/{id}/alerts` and `/api/v1/...`)

| Route & Method | Request Params / Body | Success Response | Status | Auth Required | RBAC Rules | Error Codes | Database Side Effects | Frontend Consumers |
|---|---|---|---|---|---|---|---|---|
| `GET /alerts` | Query: `patient_id`, `status` (`NEW`, `ACKNOWLEDGED`, `RESOLVED`), `limit (1-100)` | `List[AlertResponse]`<br>`alert_id: str`<br>`patient_id: str`<br>`severity: str`<br>`category: str`<br>`reason: str`<br>`status: str`<br>`created_at: datetime`<br>`acknowledged_at: Optional[datetime]`<br>`acknowledged_by: Optional[str]` | `200 OK` | Bearer JWT | Patient (own alerts only), Doctor (assigned patients' alerts), Admin (global) | `400` (Invalid status),<br>`401` (Unauthorized),<br>`403` (Cross-patient access denied) | Reads from `alerts` table filtered by authorized scope. | React Clinician Dashboard (Alert Triage Panel) |
| `GET /patients/{patient_id}/alerts` | Path: `patient_id`<br>Query: `status`, `severity`, `start_time`, `end_time`, `page`, `page_size` | `PaginatedAlertsResponse`<br>`items: List[AlertResponse]`<br>`total_count: int`<br>`page: int`<br>`page_size: int`<br>`total_pages: int` | `200 OK` | Bearer JWT | Patient (own only), Doctor (assigned only), Admin | `400` (Invalid status/severity/time),<br>`401` (Unauthorized),<br>`403` (Forbidden) | Reads paginated alerts for target patient. | React Clinician Dashboard, Flutter Patient App |
| `GET /alerts/{alert_id}` | Path: `alert_id` | `AlertResponse` | `200 OK` | Bearer JWT | Patient (own alert), Doctor (assigned patient), Admin | `401` (Unauthorized),<br>`403` (Forbidden),<br>`404` (Alert not found) | Reads alert and verifies patient authorization. | React Clinician Dashboard (Alert Detail Modal) |
| `POST /alerts/{alert_id}/acknowledge` | Path: `alert_id`<br>Body (optional): `{"note": Optional[str]}` | `AlertResponse` (updated with `status="ACKNOWLEDGED"`) | `200 OK` | Bearer JWT | Attending Doctor (assigned) or Admin Operator | `400` (Cannot acknowledge resolved alert),<br>`401` (Unauthorized),<br>`403` (Forbidden),<br>`404` (Not found) | Idempotent state transition in `alerts`, appends `alert_status_history` record, appends `audit_logs` entry. | React Clinician Dashboard (One-Click Acknowledge Action) |

---

## 5. Clinical Messaging Router (`/conversations` and `/api/v1/conversations`)

| Route & Method | Request Params / Body | Success Response | Status | Auth Required | RBAC Rules | Error Codes | Database Side Effects | Frontend Consumers |
|---|---|---|---|---|---|---|---|---|
| `GET /conversations` | Query: `page (>=1)`, `page_size (1-100)` | `PaginatedConversationsResponse`<br>`items: List[ConversationResponse]`<br>`total_count: int` | `200 OK` | Bearer JWT | Returns conversations where authenticated user is participant (patient or doctor) | `401` (Unauthorized) | Reads `conversations` joined with latest message preview and unread counts. | React Clinician Dashboard, Flutter Patient App |
| `POST /conversations` | Body: `CreateConversationRequest`<br>`patient_id: str`<br>`doctor_id: str` | `ConversationResponse` | `201 Created` | Bearer JWT | Patient (can only initiate with assigned doctor), Doctor (with assigned patient) | `401` (Unauthorized),<br>`403` (Unassigned pair),<br>`404` (User not found) | Idempotent: creates canonical conversation or returns existing active channel. | React Clinician Dashboard, Flutter Patient App |
| `GET /conversations/{conversation_id}/messages` | Path: `conversation_id`<br>Query: `page`, `page_size`, `before_message_id` | `PaginatedMessagesResponse`<br>`items: List[MessageResponse]`<br>`total_count: int` | `200 OK` | Bearer JWT | Participants of conversation only | `401` (Unauthorized),<br>`403` (Non-participant access denied),<br>`404` (Not found) | Reads chronological messages with tie-breaking sort. | React Clinician Dashboard (Chat View), Flutter Patient App |
| `POST /conversations/{conversation_id}/messages` | Path: `conversation_id`<br>Body: `SendMessageRequest`<br>`content: str (1-4000)`<br>`idempotency_key: Optional[str]` | `MessageResponse`<br>`message_id: str`<br>`sender_id: str`<br>`content: str`<br>`is_read: bool`<br>`sent_at: datetime` | `201 Created` | Bearer JWT | Permitted conversation participants only | `400` (Empty message),<br>`401` (Unauthorized),<br>`403` (Forbidden),<br>`409` (Idempotency conflict) | Inserts `messages` row, updates `conversations.updated_at`. | React Clinician Dashboard, Flutter Patient App |
| `POST /conversations/{conversation_id}/read` | Path: `conversation_id`<br>Body: `MarkReadRequest`<br>`up_to_message_id: Optional[str]` | `MarkReadResponse`<br>`conversation_id: str`<br>`marked_count: int`<br>`read_at: datetime` | `200 OK` | Bearer JWT | Recipient participant of conversation | `401` (Unauthorized),<br>`403` (Forbidden),<br>`404` (Not found) | Updates `messages.is_read = TRUE` and stamps `read_at`. | React Clinician Dashboard, Flutter Patient App |

---

## 6. Real-Time WebSockets Router (`/ws` and `/api/v1/ws`)

| Protocol & Path | Authentication Mechanism | Supported Actions / Events | Security & Policy Constraints | Database Interactions | Frontend Consumers |
|---|---|---|---|---|---|
| `WebSocket /ws`<br>`WebSocket /api/v1/ws` | **Dual Authentication:**<br>1. Token in query: `?token=<JWT>` (evaluated before accept)<br>2. In-band handshake: `{"action": "authenticate", "token": "<JWT>"}` within 5.0 seconds | **Client Inbound:**<br>- `authenticate`<br>- `subscribe` (`topic: "patient:{id}"`)<br>- `unsubscribe`<br>- `ping` (`{"action": "ping"}` -> `{"type": "pong"}`)<br><br>**Server Outbound:**<br>- `reading.created`<br>- `alert.created`<br>- `alert.acknowledged` | - Message payload capped at 64 KB.<br>- Slow client timeout isolation (2.0s per send).<br>- Unauthorized subscriptions return `403` error frame.<br>- Handshake timeout closes socket with code `1008` (Policy Violation). | Validates JWT via `users` table; checks `doctor_patient_assignments` on subscription request. | React Clinician Dashboard (Live Alert Feed), Flutter Patient App (Live Telemetry Stream) |

---

## 7. Contract Verification Summary

All routes and parameters documented above are verified against automated integration test contracts in:
- [`tests/integration/test_api_contracts.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/tests/integration/test_api_contracts.py) (8 contract test cases covering OpenAPI spec generation, 422 schema validation, pagination limits, and response shapes).
- [`tests/integration/test_security_regressions.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/tests/integration/test_security_regressions.py) (9 test cases asserting role escalation rejection, unauthenticated 401s, cross-patient 403s, and SQL injection safety).
