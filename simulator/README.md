# Smartwatch Sensor Telemetry Simulator API

> **SIMULATED TELEMETRY — NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS**  
> This service is a standalone synthetic data generator built for the **Smart Health Monitoring System** software demonstration and academic evaluation. It produces mathematically controlled, synthetic physiologic observations. It does not interface with actual physical sensors and must never be utilized for genuine healthcare delivery, diagnosis, or triage.

---

## 1. Overview & Purpose

The Smartwatch Sensor Simulator is a standalone Python FastAPI microservice that continuously generates realistic, correlated ambulatory telemetry for five demonstration patients:
- **`P101`**: Standard baseline profile (resting HR ~72 bpm, SpO2 ~98.2%, Temp ~98.4°F)
- **`P102`**: Mild sinus activity profile (resting HR ~78 bpm, SpO2 ~97.5%, Temp ~98.6°F)
- **`P103`**: Athletic resting baseline (resting HR ~66 bpm, SpO2 ~99.0%, Temp ~98.1°F)
- **`P104`**: Monitored post-procedure profile (resting HR ~84 bpm, SpO2 ~96.8%, Temp ~98.7°F)
- **`P105`**: Stable post-operative trajectory (resting HR ~74 bpm, SpO2 ~97.8%, Temp ~98.3°F)

### Key Capabilities
- **Seeded, Deterministic Physiology**: Mean-reverting random walk (Ornstein–Uhlenbeck process) avoids independent erratic jumps on successive samples while producing smooth physiologic variation.
- **Correlated Measurements**: Heart rate, SpO2, and body temperature move in correlation (e.g. simulated exertion slightly raises heart rate and core temperature while preserving oxygen saturation).
- **Dual Naming & Canonical Conversions**: Provides both `timestamp` and `measured_at`, as well as automatic `temperature_c` conversion (`(F - 32) * 5/9`).
- **Lossless Cursor-Based Polling (`/api/v1/readings/stream`)**: Downstream backend ingestion processes can continuously poll for new readings using a monotonic sequence cursor without missing records or creating duplicates.
- **Scenario Controls (`normal` vs `alert_test`)**: Enables on-demand injection of threshold breaches (e.g. tachycardia > 130 bpm, hypoxemia < 85%, or fever > 100.4°F) to verify clinical alert pipelines.
- **Bounded In-Memory Buffer**: Fixed circular buffer (`deque(maxlen=2000)`) guarantees zero unbounded memory growth.

---

## 2. Configuration & Environment Variables

All settings are configurable via environment variables or default values:

| Variable | Type | Default | Description |
|---|---|---|---|
| `SIMULATOR_HOST` | `string` | `127.0.0.1` | Network interface to bind HTTP listener |
| `SIMULATOR_PORT` | `integer` | `8001` | Service port (default `8001` avoids gateway `8000`) |
| `SIMULATOR_INTERVAL_SECONDS` | `float` | `5.0` | Cadence in seconds between generation cycles |
| `SIMULATOR_MAX_HISTORY_RECORDS`| `integer` | `2000` | In-memory circular buffer capacity |
| `SIMULATOR_RANDOM_SEED` | `integer` | `42` | PRNG seed for deterministic drift |
| `SIMULATOR_AUTO_START` | `boolean` | `true` | Automatically launch background worker on startup |
| `SIMULATOR_CONTROL_SECRET` | `string` | `None` | Optional secret for `X-Simulator-Key` header |
| `SIMULATOR_DEFAULT_SCENARIO` | `string` | `normal` | Initial simulation mode (`normal` or `alert_test`) |

---

## 3. Quickstart & Startup Commands

### Prerequisites
Python 3.10+ with project dependencies installed:
```bash
pip install fastapi uvicorn pydantic pydantic-settings
```

### Run Service
From the repository root directory:
```bash
python -m simulator.main
```
Or directly with Uvicorn:
```bash
python -m uvicorn simulator.main:app --host 127.0.0.1 --port 8001
```

Once running:
- **Interactive Swagger UI**: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- **ReDoc Documentation**: [http://127.0.0.1:8001/redoc](http://127.0.0.1:8001/redoc)
- **OpenAPI JSON**: [http://127.0.0.1:8001/openapi.json](http://127.0.0.1:8001/openapi.json)

---

## 4. API Endpoints & Request/Response Contracts

### `GET /health`
Returns simulator operational status, version, uptime, and safety disclaimer.
```json
{
  "status": "healthy",
  "service": "Smartwatch Sensor Telemetry Simulator",
  "version": "1.0.0",
  "uptime_seconds": 12.4,
  "generator_running": true,
  "disclaimer": "SIMULATED TELEMETRY — NOT FOR MEDICAL USE OR CLINICAL DIAGNOSIS"
}
```

### `GET /api/v1/patients`
Returns the 5 demonstration patient identifiers and their baseline physiological characteristics.
```json
{
  "patients": ["P101", "P102", "P103", "P104", "P105"],
  "details": [
    {
      "patient_id": "P101",
      "baseline_heart_rate": 72.0,
      "baseline_spo2": 98.2,
      "baseline_temperature_f": 98.4,
      "description": "Ambulatory baseline profile; healthy resting vital dynamics."
    }
  ],
  "count": 5
}
```

### `GET /api/v1/readings/latest`
Returns the latest generated reading for each configured patient in the cohort.
```json
{
  "readings": {
    "P101": {
      "event_id": "evt_sim_51_3fa85f64",
      "patient_id": "P101",
      "timestamp": "2026-10-15T01:30:00.000000Z",
      "measured_at": "2026-10-15T01:30:00.000000Z",
      "source": "smartwatch_simulator",
      "is_simulated": true,
      "heart_rate": 72.8,
      "spo2": 98.1,
      "temperature_f": 98.42,
      "temperature_c": 36.9,
      "scenario": "normal",
      "sequence_number": 51
    }
  },
  "count": 5,
  "timestamp_utc": "2026-10-15T01:30:00.123456Z"
}
```

### `GET /api/v1/readings`
Returns recent observations sorted newest-first, with optional patient filtering.
- **Parameters**:
  - `patient_id` (optional, string): e.g. `P101`
  - `limit` (optional, int, default: 50, max: 500)

### `GET /api/v1/readings/stream` (Cursor-Based Polling)
Lossless polling endpoint designed for backend ingestion pipelines.
- **Parameters**:
  - `cursor` (optional, string): Pass `next_cursor` from the previous response.
  - `limit` (optional, int, default: 50, max: 200)

**Polling Pattern**:
```python
import time, requests

cursor = None
while True:
    params = {"cursor": cursor, "limit": 100} if cursor else {"limit": 100}
    resp = requests.get("http://127.0.0.1:8001/api/v1/readings/stream", params=params).json()
    
    for reading in resp["items"]:
        # Ingest reading into central backend or message queue
        print(f"Ingesting: {reading['event_id']} ({reading['patient_id']}): HR={reading['heart_rate']}")
    
    cursor = resp["next_cursor"]
    time.sleep(2.0)
```

### `POST /api/v1/simulator/start`
Starts the background telemetry generation loop. Calling this endpoint when the generator is already running is completely idempotent and safe.

### `POST /api/v1/simulator/stop`
Stops background telemetry generation safely.

### `GET /api/v1/simulator/status`
Returns generator operational state, interval, scenario, buffer usage, and generation timestamp.

### `POST /api/v1/simulator/scenario`
Switches simulation scenario:
- **Body**:
  ```json
  {
    "scenario": "alert_test",
    "target_patient_id": "P101",
    "alert_metric": "heart_rate"
  }
  ```
  *(Supported `alert_metric` options: `"heart_rate"`, `"spo2"`, `"temperature"`, `"all"`)*

---

## 5. Security & Protection

In production or non-local demonstration deployments, set the `SIMULATOR_CONTROL_SECRET` environment variable:
```bash
export SIMULATOR_CONTROL_SECRET="your-demo-control-secret"
```
When set, all mutating control endpoints (`/start`, `/stop`, `/scenario`) require:
```http
X-Simulator-Key: your-demo-control-secret
```
Requests lacking this header receive HTTP `401 Unauthorized`. Read endpoints (`/health`, `/patients`, `/readings`, `/readings/stream`, `/status`) remain accessible without credentials.

---

## 6. Running Tests

Execute the comprehensive automated test suite:
```bash
python -m pytest tests/unit/test_simulator.py -v
```
All 15 test cases validate health checks, patient baselines, schema invariance, units, event uniqueness, monotonic cursors, start/stop lifecycle, scenario transitions, and graceful shutdown.
