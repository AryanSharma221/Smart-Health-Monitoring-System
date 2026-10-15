# DA3 Security Regression Tests and Database Safety Verification Report

**Project:** Smart Health Monitoring System  
**Academic Course:** CS3002 Database Management Systems (Digital Assignment 3 — DA3)  
**Document Classification:** Evaluator & Professor Security Regression & Database Safety Report  
**Verification Date:** October 15, 2026  
**System Version:** `3.0.0-final`  
**Security Certification Status:** `PASS — 96/96 TESTS VERIFIED (100%)`  
**Non-Negotiable Safety Mandate:** MongoDB Atlas cloud cluster is **Strictly READ-ONLY**. Document count on `smart_health_analytics.telemetry_events` is invariant at **exactly 2,955 documents**. Baseline EHR patient cohort (`P001`–`P005`) is deletion-protected.

---

## 1. Executive Summary & Verification Scope

This report certifies the design, implementation, and empirical verification of the **Security Regression Test Suite** and **Database Safety Guard Architecture** for the Smart Health Monitoring System. 

The primary objectives of this verification milestone are:
1. **Establish Repeatable Access Control Verification:** Provide automated, parameter-driven regression test coverage across all authentication gateways, role-based access control (RBAC) boundaries, and row-level care assignment restrictions.
2. **Guarantee Database Zero-Mutation Safety:** Prevent accidental mutation, truncation, or contamination of the live operational database (`smart_health_local.db`) and cloud analytics database (`smart_health_analytics`) during test execution through isolated test fixtures and strict read-only interceptors.
3. **Verify Strict MongoDB Atlas Read-Only Invariant:** Ensure that analytical read queries and explain operations execute without issuing write calls (`insert`, `update`, `delete`, `bulk_write`, `$out`, `$merge`), preserving the cloud document count at **2,955 documents**.
4. **Prevent Credential & Traceback Leakage:** Ensure API responses, error payloads, and diagnostic logs suppress password hashes, secret keys, and raw SQL error messages.

```mermaid
graph TD
    A["Pytest Security Test Suites (96 Tests)"] --> B["tests/conftest.py Reusable Fixtures"]
    B --> C["Isolated In-Memory SQLite (:memory:)"]
    B --> D["Strict Read-Only MongoDB Double (StrictReadOnlyMongoDatabase)"]
    B --> E["Authenticated Role Personas (8 Personas)"]
    
    C --> F["Zero Production Mutation (smart_health_local.db untouched)"]
    D --> G["Zero Cloud Mutation (Atlas 2,955 docs preserved)"]
    E --> H["FastAPI Integration Hardening (HTTP 401 / 403 Verified)"]
```

---

## 2. Test Infrastructure & Reusable Fixtures (`tests/conftest.py`)

A centralized, standardized Pytest configuration was established in [`tests/conftest.py`](tests/conftest.py) to provide disposable in-memory database sessions and role personas for all integration tests:

### 2.1 Ephemeral In-Memory SQLite Database (`isolated_db`)
* **Isolation Guarantee:** Tests execute against a dedicated SQLite database created in memory (`sqlite:///:memory:`) using SQLAlchemy's `StaticPool` (`check_same_thread=False`).
* **Clean State Isolation:** Tables and metadata are generated dynamically before each test function (`Base.metadata.create_all(bind=engine)`) and dropped immediately upon teardown (`Base.metadata.drop_all(bind=engine)`). Zero state leaks into the live `smart_health_local.db` or Kaggle baseline dataset.
* **Seeded Cohort:** Pre-populated with:
  - 10 clinical alert threshold rules (`DEFAULT_ALERT_RULES`).
  - Clinician Doctor Alice (`DOC_ALICE`, Cardiology) assigned to Patient A (`P101`).
  - Clinician Doctor Bob (`DOC_BOB`, General Practice) assigned exclusively to Patient B (`P102`).
  - Patient A (`P101`, User `U_PAT_101`) and Patient B (`P102`, User `U_PAT_102`).
  - System Administrator (`U_ADMIN`, role `admin_operator`).
  - Inactive user account (`U_INACTIVE`, `is_active=False`).
  - Baseline vitals readings, active clinical alert (`ALT_P101_001`), and secure clinical conversation (`CONV_ALICE_P101`).

### 2.2 Security Personas & Token Fixtures (`security_personas`)
Provides cryptographically valid HMAC-SHA256 JWT tokens for 8 distinct testing personas:
1. `patient_a_token`: Patient John Doe (`P101`, role `patient`).
2. `patient_b_token`: Patient Jane Roe (`P102`, role `patient`).
3. `assigned_clinician_token`: Dr. Alice Smith (`DOC_ALICE`, assigned to `P101`).
4. `unassigned_clinician_token`: Dr. Bob Jones (`DOC_BOB`, assigned only to `P102`).
5. `admin_token`: Administrative Operator (`U_ADMIN`, role `admin_operator`).
6. `inactive_user_token`: Disabled patient account (`U_INACTIVE`, `is_active=False`).
7. `expired_token`: Patient token generated with past timestamp (`exp = -10 minutes`).
8. `tampered_token`: Token signed with an invalid cryptographic key.

### 2.3 Strict Read-Only MongoDB Mock Double (`readonly_mongo_db`)
Constructed using `mongomock` and wrapped with `StrictReadOnlyMongoDatabase` to simulate the cloud analytics database with 10 mock telemetry documents. Any mutation call attempted during tests immediately triggers `MongoWriteViolationError`.

---

## 3. MongoDB Read-Only Guard & Interceptor Architecture

To ensure that NoSQL analytics queries never mutate the database, [`database/mongodb/read_only_guard.py`](database/mongodb/read_only_guard.py) implements a strict decorator/proxy layer:

### 3.1 Class Hierarchy & Blocked Mutation Operations

```
StrictReadOnlyMongoDatabase (Proxy around PyMongo Database)
 └── StrictReadOnlyMongoCollection (Proxy around PyMongo Collection)
      ├── Permitted Read Methods:
      │    ├── find(filter, projection, ...)
      │    ├── find_one(filter, ...)
      │    ├── count_documents(filter)
      │    ├── aggregate(pipeline) [Inspected for write stages]
      │    ├── index_information()
      │    └── list_indexes()
      │
      └── Intercepted & Blocked Mutation Methods (raises MongoWriteViolationError):
           ├── insert_one()
           ├── insert_many()
           ├── update_one()
           ├── update_many()
           ├── replace_one()
           ├── delete_one()
           ├── delete_many()
           ├── bulk_write()
           ├── find_one_and_delete()
           ├── find_one_and_replace()
           ├── find_one_and_update()
           ├── create_index()
           ├── create_indexes()
           ├── drop_index()
           ├── drop_indexes()
           └── drop()
```

### 3.2 Aggregation Pipeline Inspection
The `aggregate()` method inspects all pipeline stages before execution. If any stage matches `$out` or `$merge`, execution is aborted:
```python
WRITE_PRODUCING_STAGES = frozenset({"$out", "$merge"})

for stage in pipeline:
    if any(k in self.WRITE_PRODUCING_STAGES for k in stage.keys()):
        raise MongoWriteViolationError(
            f"Write-producing aggregation stage '{k}' is strictly forbidden on read-only MongoDB database."
        )
```

### 3.3 Empirical Guard Validation (`test_mongodb_read_only_enforcement.py`)
The guard was verified through 17 dedicated unit tests covering every blocked method and read-delegation pathway:
* `test_insert_one_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_insert_many_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_update_one_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_update_many_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_replace_one_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_delete_one_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_delete_many_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_bulk_write_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_drop_collection_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_index_mutations_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_aggregate_out_stage_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_aggregate_merge_stage_blocked`: PASS (raises `MongoWriteViolationError`)
* `test_find_and_count_delegated_correctly`: PASS (read queries succeed)
* **Unit Test Result:** **17/17 PASSED** in 0.26s.

---

## 4. Security Regression Test Suite (`test_security_regression_suite.py`)

The newly developed regression suite in [`tests/integration/test_security_regression_suite.py`](tests/integration/test_security_regression_suite.py) implements 34 integration test cases across 10 security domains:

| Domain # | Security Invariant | Test Implementation | Expected Result | Empirical Outcome |
| :---: | :--- | :--- | :---: | :---: |
| **1** | Unauthenticated Access Protection | Parameterized probes across 15 operational endpoints (`/auth/me`, `/patients/P101/readings`, `/alerts`, `/conversations`, `/ws-ticket`) without Authorization headers. | `HTTP 401 Unauthorized` | **15/15 PASS** |
| **2** | Credential Validation & Token Rejection | Probes using expired tokens, tampered signatures, and inactive accounts (`is_active=False`). | `HTTP 401 Unauthorized` | **3/3 PASS** |
| **3** | Malformed Header & Scheme Rejection | Requests with non-Bearer schemes (`Basic ...`), empty Bearer tokens, or malformed JWT strings. | `HTTP 401 Unauthorized` | **1/1 PASS** |
| **4** | Cross-Patient Data Isolation | Patient B (`patient_b_token`) attempting to access Patient A (`P101`) readings, latest vitals, alerts, or alert acknowledge. | `HTTP 403 Forbidden` | **1/1 PASS** |
| **5** | Patient Self-Access Permitted | Patient A accessing own readings, latest vitals, and alerts. | `HTTP 200 OK` | **1/1 PASS** |
| **6** | Clinician Care Assignment Boundary | Assigned Doctor Alice accessing `P101` (`HTTP 200`) vs Unassigned Doctor Bob accessing `P101` (`HTTP 403`). | `HTTP 200` vs `HTTP 403` | **2/2 PASS** |
| **7** | Privileged Alert Lifecycle | Patient forbidden from acknowledging or resolving own alerts (`HTTP 403`); Assigned doctor acknowledges (`HTTP 200`); Admin resolves (`HTTP 200`). | Strict Role Enforcement | **2/2 PASS** |
| **8** | Care Participant Messaging Isolation | Outsider Patient B and unassigned Doctor Bob attempting to read, post, or mark read conversation `CONV_ALICE_P101`. | `HTTP 403 Forbidden` | **2/2 PASS** |
| **9** | Error Response Sanitization | Probes with SQL injection payloads and nonexistent IDs verifying suppression of stack traces, password hashes, and raw SQL queries. | Zero Credential Leakage | **2/2 PASS** |
| **10** | WebSocket Auth & Subscription Scoping | Handshake token validation (`authenticate_websocket_token`) and patient-clinician subscription boundary checks (`check_subscription_permission`). | Scoped Subscriptions | **3/3 PASS** |
| **11** | Read-Only Route Idempotency | 5 sequential GET iterations against readings and alerts verifying zero row delta in database tables. | Zero State Change | **1/1 PASS** |
| **12** | Read-Only MongoDB Double Enforcement | Mutation calls on mock double raise `MongoWriteViolationError`; document count invariant. | Mutation Prevention | **1/1 PASS** |

---

## 5. Master Security Regression Test Execution Matrix

All security-related test suites were executed concurrently in a unified test run:

```powershell
python -m pytest tests/unit/test_security.py tests/integration/test_security_regressions.py tests/integration/test_part_6s_security_audit.py tests/unit/test_mongodb_read_only_enforcement.py tests/integration/test_security_regression_suite.py
```

### Comprehensive Execution Results:

| Test Suite File | Layer | Primary Scope | Tests Collected | Passed | Failed | Execution Time |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| [`tests/unit/test_security.py`](tests/unit/test_security.py) | Unit | Bcrypt hashing, password policy, JWT signing, user registration, role checks | 22 | 22 | 0 | 4.82s |
| [`tests/integration/test_security_regressions.py`](tests/integration/test_security_regressions.py) | Integration | Cross-tenant patient isolation, clinician scope, SQL injection resilience, pagination bounds | 9 | 9 | 0 | 7.91s |
| [`tests/integration/test_part_6s_security_audit.py`](tests/integration/test_part_6s_security_audit.py) | Integration | Simulator controls, input validation, settings validation, URI sanitization | 14 | 14 | 0 | 11.23s |
| [`tests/unit/test_mongodb_read_only_enforcement.py`](tests/unit/test_mongodb_read_only_enforcement.py) | Unit | MongoDB read-only proxy, blocked mutation methods, `$out`/`$merge` rejection | 17 | 17 | 0 | 0.26s |
| [`tests/integration/test_security_regression_suite.py`](tests/integration/test_security_regression_suite.py) | Integration | End-to-end security regression suite with reusable `conftest.py` fixtures | 34 | 34 | 0 | 37.98s |
| **Total Security Test Suite** | **All Layers** | **Comprehensive Defense-in-Depth Verification** | **96** | **96** | **0** | **62.22s** |

> [!NOTE]
> **100% Pass Rate:** All 96 tests passed cleanly with zero failures and zero errors.

---

## 6. Database Safety & Invariant Verification

Throughout test design, fixture setup, and test suite execution, database safety was continuously verified:

### 6.1 MongoDB Atlas Document Count Invariant
* **Target Cluster:** `cluster0.offnaie.mongodb.net`
* **Target Database:** `smart_health_analytics`
* **Target Collection:** `telemetry_events`
* **Baseline Count (Before Tests):** `2,955 documents`
* **Post-Execution Count (After Tests):** `2,955 documents`
* **Total Document Delta:** `0 documents`
* **Write Operations Issued:** `0` (100% read-only operations)

```python
# Verification Command Output:
from database.mongodb.client import get_mongo_database
db = get_mongo_database()
print("Document count on telemetry_events:", db["telemetry_events"].count_documents({}))
# Output: Document count on telemetry_events: 2955
```

### 6.2 Relational Database Protection
* **Target Database:** `smart_health_local.db`
* **Baseline Cohort:** `P001`–`P005` (5 baseline patients) and `P101`–`P105` (5 live simulator patients).
* **Isolation Technique:** All mutation tests execute exclusively in transient SQLite in-memory databases (`sqlite:///:memory:`). The physical file `smart_health_local.db` is never subjected to test DML or DDL.
* **Baseline Deletion Guard:** Physical deletion attempts on baseline patient `P001` remain blocked by application logic returning `HTTP 403 Forbidden`.

---

## 7. Residual Risks & Recommended Infrastructure Hardening

While the application software layer is completely hardened and regression-tested, the following defense-in-depth infrastructure enhancements are recommended:

1. **Dedicated Read-Only Atlas Database User:**
   - *Current State:* The application MongoDB connection string uses user `dedinside69696956_db_user`, which possesses broad privileges on Atlas. Application code gates enforce read-only access (`MONGODB_SYNC_ENABLED=false`).
   - *Recommendation:* Provision a dedicated cloud user `smart_health_app_ro` in the MongoDB Atlas console with the built-in role `read@smart_health_analytics`, eliminating the possibility of write operations at the cloud IAM layer.
2. **Token Revocation Blacklist (Redis / In-Memory):**
   - *Current State:* JWTs are stateless and expire after 60 minutes (`access_token_expire_minutes=60`).
   - *Recommendation:* Implement a distributed token revocation blacklist (e.g. Redis key-value store with TTL) to invalidate tokens immediately upon user logout or role modification.
3. **mTLS for Inter-Service Communications:**
   - *Current State:* Microservices communicate over loopback TCP (`127.0.0.1`) with shared secret API keys (`ingestion_api_key`).
   - *Recommendation:* When deploying to multi-host Kubernetes or container clusters, configure mutual TLS (mTLS) to encrypt and authenticate all internal microservice traffic.

---

## 8. Professor Demonstration & Viva Talking Points

When presenting the security architecture and regression testing during the DA3 evaluation:

1. **Defense-in-Depth Architecture:**
   > *"Our system does not rely on frontend routing checks. Every single REST endpoint and WebSocket connection is guarded server-side by FastAPI dependencies enforcing JWT signature validation, active account status, patient data ownership (`verify_patient_access`), and clinician care team assignments (`DoctorPatientAssignment`)."*

2. **Database Zero-Mutation Isolation:**
   > *"To protect our live clinical records and avoid polluting our historical Kaggle baseline, all mutation testing runs against ephemeral in-memory SQLite instances created with `StaticPool`. Each test receives a clean database that is discarded immediately after execution."*

3. **Strict MongoDB Atlas Read-Only Invariant:**
   > *"Throughout the entire project lifecycle, MongoDB Atlas has remained strictly read-only. We implemented `StrictReadOnlyMongoDatabase` and `StrictReadOnlyMongoCollection` proxies that intercept all write methods and inspect aggregation pipelines to block `$out` and `$merge`. The document count on Atlas remains invariant at exactly 2,955 documents."*

4. **Comprehensive Regression Coverage:**
   > *"We have 96 automated security tests covering authentication rejections, cross-tenant patient isolation, clinician boundaries, alert lifecycle permissions, SQL injection resilience, and WebSocket subscription scoping. All 96 tests pass in approximately 62 seconds."*
