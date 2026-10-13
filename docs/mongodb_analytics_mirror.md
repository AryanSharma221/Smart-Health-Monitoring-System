# MongoDB Atlas Analytics Mirror, Outbox Pattern, and Failure Recovery

> [!NOTE]
> **ANALYTICS MIRROR ARCHITECTURE — SOURCE OF TRUTH NOTICE**  
> MySQL 8 (InnoDB) is the sole authoritative database for users, roles, clinician assignments, canonical health readings, clinical alerts, messages, acknowledgements, and compliance audit logs. MongoDB Atlas serves strictly as an asynchronous analytics-oriented mirror for telemetry time-series and alert aggregations (fulfilling NoSQL coursework and future Streamlit dashboard requirements). MongoDB NEVER acts as the primary source of truth for core healthcare records.

---

## 1. System Architecture and Source-of-Truth Boundaries

The Smart Health Monitoring System implements a hybrid relational/document architecture designed to balance transactional rigor (ACID guarantees, foreign key cascades, role security) with NoSQL analytical flexibility:

```mermaid
flowchart TD
    Client[FastAPI API Gateway] -->|Transactional Commit| MySQL[(MySQL 8 InnoDB\nAuthoritative Source of Truth)]
    MySQL -->|Outbox Event Staged| OutboxTable[analytics_outbox Table]
    
    subgraph Reliability & Failure Recovery
        OutboxTable -->|Process Batch / Immediate| SyncWorker[OutboxSyncService]
        SyncWorker -->|Idempotent Upsert _id| MongoAtlas[(MongoDB Atlas\nAnalytics Mirror)]
        SyncWorker -.->|On Failure: Mark Pending / Retry| OutboxTable
    end

    subgraph Analytics Consumers (Future DA3)
        MongoAtlas -->|Read-Only Aggregations| StreamlitApp[Streamlit Dashboard / Benchmarks]
    end
```

### Architectural Principles:
1. **Unilateral Authority**: MySQL commits define the authoritative state of the system. A transaction in MySQL succeeds regardless of whether MongoDB Atlas is online, unreachable, or degraded.
2. **Never Atomic Across Databases**: MySQL and MongoDB are never treated as a single distributed atomic transaction. Instead, the **Transactional Outbox Pattern** guarantees eventual consistency.
3. **No Direct Client Access**: Flutter, React, and external users never query MongoDB Atlas directly; all client interactions go exclusively through FastAPI with server-side authorization.

---

## 2. Document Models and Collection Schemas

Two collections are maintained in the MongoDB analytics database (`smart_health_analytics`):

### 1. `telemetry_events` Collection
Stores time-series telemetry observations with physiological vitals in original units (bpm, %, °F, °C).

```json
{
  "_id": "evt_0192e21b2123...",
  "event_id": "evt_0192e21b2123...",
  "patient_id": "P101",
  "measured_at": "2026-10-13T10:00:00Z",
  "received_at": "2026-10-13T10:00:05Z",
  "source": "simulator",
  "source_event_id": "sim_1001",
  "is_simulated": true,
  "metrics": {
    "heart_rate": 84.5,
    "spo2": 98.0,
    "temperature_f": 98.6,
    "temperature_c": 37.0
  },
  "readings_summary": [
    {
      "metric_code": "heart_rate",
      "value": 84.5,
      "unit": "bpm",
      "raw_value": 84.5,
      "raw_unit": "bpm",
      "quality_status": "valid"
    },
    {
      "metric_code": "temperature",
      "value": 37.0,
      "unit": "degC",
      "raw_value": 98.6,
      "raw_unit": "degF",
      "quality_status": "valid"
    }
  ],
  "mirrored_at": "2026-10-13T10:00:06Z",
  "schema_version": 1
}
```

### 2. `alert_events` Collection
Stores clinical alert lifecycle events, threshold breaches, and acknowledgement statuses.

```json
{
  "_id": "alt_0192e21b2123...",
  "alert_id": "alt_0192e21b2123...",
  "patient_id": "P101",
  "event_id": "evt_0192e21b2123...",
  "rule_id": "RULE_HR_HIGH",
  "severity": "HIGH",
  "category": "vital_threshold",
  "reason": "[HIGH] Heart rate exceeds 100 bpm Observed: 110.0 bpm.",
  "status": "ACKNOWLEDGED",
  "state_rank": 2,
  "acknowledged_by": "usr_doc1",
  "acknowledged_at": "2026-10-13T10:15:00Z",
  "resolved_by": null,
  "resolved_at": null,
  "created_at": "2026-10-13T10:00:06Z",
  "mirrored_at": "2026-10-13T10:15:02Z",
  "schema_version": 1
}
```

---

## 3. Stable Document Identity & Idempotency Strategy

- **Telemetry Identifier**: `_id` is set to the MySQL `event_id` string (e.g., `evt_...`).
- **Alert Identifier**: `_id` is set to the deterministic MySQL `alert_id` string (e.g., `alt_...`).
- **Idempotent Upsert**:
  - All writes use `replace_one({"_id": doc["_id"]}, doc, upsert=True)`.
  - Re-delivering or replaying an event updates the existing document in place without creating duplicates.
  - Different legitimate events with identical vitals measurements have distinct `event_id` keys and therefore remain distinct documents.
- **Monotonic State Conflict Resolution**:
  - Alert states have assigned ranks: `NEW` (1) $\to$ `ACKNOWLEDGED` (2) $\to$ `RESOLVED` (3).
  - If a delayed out-of-order event arrives with a lower `state_rank` than the document already stored in MongoDB, the existing `status`, `acknowledged_at`, and `acknowledged_by` attributes are preserved.

---

## 4. Transactional Outbox Pattern & Failure Recovery

### MySQL Table: `analytics_outbox`
Migrated via Alembic (`002_analytics_outbox`):
- `outbox_id`: BigInteger auto-increment primary key.
- `event_type`: `telemetry_event` or `alert_event`.
- `aggregate_id`: Foreign key reference (`event_id` or `alert_id`).
- `payload_json`: Pre-serialized document payload.
- `status`: `pending`, `processing`, `completed`, `failed`.
- `attempt_count`: Bounded retry counter (default max: 5).
- `last_error`: Sanitized error message (capped at 1,000 characters).
- `created_at`, `last_attempt_at`, `completed_at`.

### Recovery Workflow:
1. When an `IngestionEvent` or `Alert` is saved in MySQL, an outbox record is inserted in the **same transaction**.
2. If MongoDB Atlas is online, immediate opportunistic sync is attempted.
3. If MongoDB Atlas is unavailable or times out:
   - MySQL transaction commits successfully.
   - The outbox record remains in `pending` status.
   - The source `IngestionEvent.mirror_status` remains `pending`.
4. The background or periodic sync worker (`OutboxSyncService.process_outbox_batch`) queries pending entries ordered by `created_at ASC`.
5. Interrupted workers (where an uncompleted crash left records in `processing` status) are automatically recovered on subsequent runs.
6. When `attempt_count >= max_attempts`, the record transitions to `failed`, triggering diagnostic alerts on `/health/mongodb`.

---

## 5. Indexes and Query Plan Optimization

| Collection | Index Keys | Type | Intended Query Pattern |
| :--- | :--- | :--- | :--- |
| `telemetry_events` | `(patient_id: 1, measured_at: -1)` | Compound | Patient historical telemetry charts and time series. |
| `telemetry_events` | `(measured_at: -1)` | Single | Population-level time-window aggregations. |
| `telemetry_events` | `(source: 1)` | Single | Provenance filtering (e.g. simulator vs kaggle). |
| `telemetry_events` | `(is_simulated: 1)` | Single | Live telemetry vs synthetic evaluation. |
| `alert_events` | `(patient_id: 1, created_at: -1)` | Compound | Patient alert history feeds. |
| `alert_events` | `(status: 1, severity: 1)` | Compound | Active emergency triage queues. |
| `alert_events` | `(rule_id: 1)` | Single | Clinical rule breach frequency metrics. |
| `alert_events` | `(event_id: 1)` | Single | Association link to triggering telemetry packet. |

---

## 6. Centralized Configuration and Client Lifecycle

Environment configuration variables:
```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=smart_health_analytics
MONGODB_SERVER_SELECTION_TIMEOUT_MS=5000
MONGODB_CONNECT_TIMEOUT_MS=5000
```

### Security & Sanitization Rules:
- The centralized provider [`database/mongodb/client.py`](file:///C:/Users/Aryan/.gemini/antigravity/scratch/smart-health-monitoring/database/mongodb/client.py) strictly redacts credentials via `sanitize_mongo_uri`:
  - `mongodb+srv://admin_user:Pass123@cluster0.mongodb.net/analytics` $\to$ `mongodb+srv://***:***@cluster0.mongodb.net/analytics`.
- The API diagnostic endpoint `GET /health/mongodb` reports connection state and outbox queue lengths without leaking connection secrets.
- Resources are released via `close_mongo_client()` in the FastAPI lifespan handler.

---

## 7. Testing and Offline Verification

Unit tests use `mongomock` to simulate PyMongo collections, document upserts, index creation, and queries in memory without requiring live Atlas credentials.

Run test suite:
```powershell
& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/test_mongodb_mirror.py -v
```

All 19 tests pass in < 1.0 second, verifying client lifecycle, document serialization, monotonic state protection, outbox retry loops, and failure isolation.
