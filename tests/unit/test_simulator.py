"""
Automated Unit and Integration Tests for the Standalone Smartwatch Sensor Simulator.

Verifies:
1. Health endpoint and root discovery.
2. Demo patient cohort list and baselines.
3. Reading schema, units (bpm, %, °F, °C), and data contracts.
4. Unique event IDs and monotonic sequence numbering.
5. Simulated provenance flags (is_simulated=True, source='smartwatch_simulator').
6. Latest readings retrieval per patient.
7. Patient-specific filtering.
8. Bounded in-memory circular buffer limits.
9. Lossless cursor-based stream polling.
10. Background worker start, stop, and duplicate start idempotence.
11. Input validation and HTTP error handling.
12. Normal baseline vs. alert-test scenario transitions.
13. Control endpoint authentication guard.
14. Graceful application lifespan shutdown.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from fastapi import status
from fastapi.testclient import TestClient

from simulator.config import SimulatorSettings
from simulator.generator import TelemetryGenerator
from simulator.routes import set_generator_instance
from simulator.main import create_simulator_app
from simulator.models import ScenarioUpdateRequest


@pytest.fixture
def test_settings() -> SimulatorSettings:
    """Fixture providing isolated simulator settings with background auto_start disabled."""
    return SimulatorSettings(
        auto_start=False,
        interval_seconds=0.1,
        max_history_records=50,
        random_seed=12345,
        control_secret=None,
    )


@pytest.fixture
def simulator_client(test_settings: SimulatorSettings) -> TestClient:
    """Fixture providing a fresh TestClient and isolated generator instance."""
    generator = TelemetryGenerator(test_settings)
    set_generator_instance(generator)
    app = create_simulator_app(test_settings)
    with TestClient(app) as client:
        yield client


# =============================================================================
# 1. Health and Discovery Endpoints
# =============================================================================

def test_health_endpoint(simulator_client: TestClient) -> None:
    """Verify /health returns 200 OK with expected service metadata and safety notice."""
    resp = simulator_client.get("/health")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["status"] == "healthy"
    assert "Smartwatch Sensor" in data["service"]
    assert data["version"] == "1.0.0"
    assert data["uptime_seconds"] >= 0.0
    assert "SIMULATED TELEMETRY" in data["disclaimer"]
    assert "NOT FOR MEDICAL USE" in data["disclaimer"]


def test_root_discovery_endpoint(simulator_client: TestClient) -> None:
    """Verify GET / returns navigation links and service index."""
    resp = simulator_client.get("/")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["status"] == "online"
    assert data["documentation"] == "/docs"
    assert "health" in data["endpoints"]
    assert "patients" in data["endpoints"]
    assert "latest_readings" in data["endpoints"]
    assert "streaming_poll" in data["endpoints"]


# =============================================================================
# 2. Patient Roster & Baselines
# =============================================================================

def test_patients_list_endpoint(simulator_client: TestClient) -> None:
    """Verify GET /api/v1/patients returns configured demo patient identifiers."""
    resp = simulator_client.get("/api/v1/patients")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["patients"] == ["P101", "P102", "P103", "P104", "P105"]
    assert data["count"] == 5
    assert len(data["details"]) == 5

    p101_detail = next(d for d in data["details"] if d["patient_id"] == "P101")
    assert p101_detail["baseline_heart_rate"] == 72.0
    assert p101_detail["baseline_spo2"] == 98.2
    assert p101_detail["baseline_temperature_f"] == 98.4


# =============================================================================
# 3. Telemetry Reading Schema, Units, and Provenance
# =============================================================================

def test_telemetry_reading_schema_and_units(simulator_client: TestClient) -> None:
    """Verify reading field names, valid ranges, and temperature conversion accuracy."""
    resp = simulator_client.get("/api/v1/readings/latest")
    assert resp.status_code == status.HTTP_200_OK
    readings = resp.json()["readings"]

    for pid in ["P101", "P102", "P103", "P104", "P105"]:
        assert pid in readings
        r = readings[pid]

        assert r["patient_id"] == pid
        assert r["source"] == "smartwatch_simulator"
        assert r["is_simulated"] is True
        assert r["scenario"] == "normal"
        assert "timestamp" in r
        assert "measured_at" in r
        assert r["timestamp"] == r["measured_at"]

        # Physiologic ranges in normal mode
        assert 50.0 <= r["heart_rate"] <= 100.0, f"Heart rate out of normal bounds: {r['heart_rate']}"
        assert 95.0 <= r["spo2"] <= 100.0, f"SpO2 out of normal bounds: {r['spo2']}"
        assert 97.0 <= r["temperature_f"] <= 100.0, f"Temperature F out of normal bounds: {r['temperature_f']}"

        # Verify Celsius conversion: (F - 32) * 5/9
        expected_c = round((r["temperature_f"] - 32.0) * (5.0 / 9.0), 2)
        assert abs(r["temperature_c"] - expected_c) < 0.05


def test_unique_event_ids_and_monotonic_sequence(test_settings: SimulatorSettings) -> None:
    """Verify unique event IDs and strictly increasing monotonic sequence numbers."""
    generator = TelemetryGenerator(test_settings)
    all_readings = []

    for _ in range(5):
        cycle = generator.generate_cycle()
        all_readings.extend(cycle)

    assert len(all_readings) == 25
    event_ids = [r.event_id for r in all_readings]
    sequences = [r.sequence_number for r in all_readings]

    # Every event ID must be unique
    assert len(set(event_ids)) == 25
    for eid in event_ids:
        assert eid.startswith("evt_sim_")

    # Sequences must be strictly increasing: 1, 2, 3... 25
    assert sequences == list(range(1, 26))


# =============================================================================
# 4. Read Endpoints: Latest, Filtered, and Bounded History
# =============================================================================

def test_latest_readings_endpoint(simulator_client: TestClient) -> None:
    """Verify GET /api/v1/readings/latest returns latest observations for all 5 patients."""
    resp = simulator_client.get("/api/v1/readings/latest")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["count"] == 5
    assert set(data["readings"].keys()) == {"P101", "P102", "P103", "P104", "P105"}


def test_patient_filtering_in_readings(simulator_client: TestClient) -> None:
    """Verify GET /api/v1/readings with patient_id filter returns only matching records."""
    # Ensure readings exist
    simulator_client.get("/api/v1/readings/latest")

    resp = simulator_client.get("/api/v1/readings?patient_id=P103&limit=20")
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]

    assert len(items) > 0
    for item in items:
        assert item["patient_id"] == "P103"


def test_bounded_history_capacity(test_settings: SimulatorSettings) -> None:
    """Verify buffer caps memory growth at configured max_history_records."""
    # Buffer capacity configured to 50 in test_settings
    generator = TelemetryGenerator(test_settings)

    # Generate 15 cycles (15 * 5 = 75 readings) -> exceeds 50 capacity
    for _ in range(15):
        generator.generate_cycle()

    assert generator.total_readings_generated == 75
    assert generator.buffer_count == 50  # Must be bounded strictly at max_history_records
    assert len(generator.get_bounded_readings(limit=100)) == 50


# =============================================================================
# 5. Polling Stream & Cursor Deduplication
# =============================================================================

def test_polling_stream_cursor_behavior(test_settings: SimulatorSettings) -> None:
    """Verify reliable cursor-based polling without duplicated or skipped readings."""
    generator = TelemetryGenerator(test_settings)

    # 1. Initial cycle: 5 readings (sequences 1..5)
    generator.generate_cycle()

    # Initial poll without cursor
    stream1 = generator.poll_stream(cursor=None, limit=10)
    assert stream1.count == 5
    assert stream1.items[0].sequence_number == 1
    assert stream1.items[-1].sequence_number == 5
    assert stream1.next_cursor == "5"
    assert stream1.has_more is False

    # Immediate second poll using next_cursor before new generation -> 0 items
    stream2 = generator.poll_stream(cursor=stream1.next_cursor, limit=10)
    assert stream2.count == 0
    assert stream2.items == []
    assert stream2.next_cursor == "5"

    # 2. Generate second cycle: 5 more readings (sequences 6..10)
    generator.generate_cycle()

    # Poll with cursor="5" -> receives exactly the 5 new readings (6..10)
    stream3 = generator.poll_stream(cursor="5", limit=10)
    assert stream3.count == 5
    assert [r.sequence_number for r in stream3.items] == [6, 7, 8, 9, 10]
    assert stream3.next_cursor == "10"

    # 3. Test cursor parsing using event_id format (e.g. evt_sim_7_...)
    target_event_id = stream3.items[1].event_id  # sequence 7
    stream_by_eid = generator.poll_stream(cursor=target_event_id, limit=10)
    assert stream_by_eid.count == 3
    assert [r.sequence_number for r in stream_by_eid.items] == [8, 9, 10]


# =============================================================================
# 6. Lifecycle Management & Duplicate Start Idempotence
# =============================================================================

def test_simulator_start_and_stop_lifecycle(simulator_client: TestClient) -> None:
    """Verify simulator start, stop, and duplicate start idempotence."""
    # 1. Initial status: not running
    status1 = simulator_client.get("/api/v1/simulator/status").json()
    assert status1["is_running"] is False

    # 2. Start generator
    start_resp = simulator_client.post("/api/v1/simulator/start")
    assert start_resp.status_code == status.HTTP_200_OK
    assert start_resp.json()["is_running"] is True
    assert "started successfully" in start_resp.json()["message"]

    # 3. Duplicate start request must be handled safely without error or extra tasks
    dup_resp = simulator_client.post("/api/v1/simulator/start")
    assert dup_resp.status_code == status.HTTP_200_OK
    assert dup_resp.json()["is_running"] is True
    assert "already actively running" in dup_resp.json()["message"]

    # 4. Verify running in status
    status2 = simulator_client.get("/api/v1/simulator/status").json()
    assert status2["is_running"] is True

    # 5. Stop generator
    stop_resp = simulator_client.post("/api/v1/simulator/stop")
    assert stop_resp.status_code == status.HTTP_200_OK
    assert stop_resp.json()["is_running"] is False
    assert "stopped gracefully" in stop_resp.json()["message"]

    # 6. Verify stopped in status
    status3 = simulator_client.get("/api/v1/simulator/status").json()
    assert status3["is_running"] is False


# =============================================================================
# 7. Scenario Controls: Normal vs Alert Test
# =============================================================================

def test_scenario_transition_to_alert_test(simulator_client: TestClient) -> None:
    """Verify switching scenario to alert_test generates threshold breaches for target patient."""
    # 1. Normal mode generation
    simulator_client.get("/api/v1/readings/latest")

    # 2. Switch P101 to alert_test for tachycardia (heart_rate)
    scenario_resp = simulator_client.post(
        "/api/v1/simulator/scenario",
        json={
            "scenario": "alert_test",
            "target_patient_id": "P101",
            "alert_metric": "heart_rate",
        },
    )
    assert scenario_resp.status_code == status.HTTP_200_OK

    # 3. Query readings to observe alert value
    latest_resp = simulator_client.get("/api/v1/readings/latest")
    readings = latest_resp.json()["readings"]

    # P101 must exhibit critical tachycardia (> 130 bpm)
    assert readings["P101"]["scenario"] == "alert_test"
    assert readings["P101"]["heart_rate"] > 130.0

    # Non-target patients (P102–P105) must remain in normal range
    assert readings["P102"]["scenario"] == "normal"
    assert readings["P102"]["heart_rate"] < 100.0

    # 4. Switch back to normal
    restore_resp = simulator_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "normal"},
    )
    assert restore_resp.status_code == status.HTTP_200_OK


# =============================================================================
# 8. Error Handling and Input Validation
# =============================================================================

def test_invalid_patient_id_handling(simulator_client: TestClient) -> None:
    """Verify querying non-existent patient returns 404 Not Found."""
    resp = simulator_client.get("/api/v1/readings?patient_id=P999_NONEXISTENT")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "not in configured simulator cohort" in resp.json()["detail"]


def test_invalid_limit_parameter(simulator_client: TestClient) -> None:
    """Verify limit validation catches invalid integer parameters."""
    resp = simulator_client.get("/api/v1/readings?limit=0")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    resp2 = simulator_client.get("/api/v1/readings?limit=9999")
    assert resp2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# =============================================================================
# 9. Control Endpoint Security Guard
# =============================================================================

def test_control_secret_protection() -> None:
    """Verify control endpoints require X-Simulator-Key when control_secret is configured."""
    secure_settings = SimulatorSettings(
        auto_start=False,
        control_secret="super_secret_demo_token_123",
    )
    generator = TelemetryGenerator(secure_settings)
    set_generator_instance(generator)
    app = create_simulator_app(secure_settings)

    with TestClient(app) as client:
        # Request without header -> 401 Unauthorized
        unauth_resp = client.post("/api/v1/simulator/start")
        assert unauth_resp.status_code == status.HTTP_401_UNAUTHORIZED

        # Request with wrong key -> 401 Unauthorized
        bad_key_resp = client.post(
            "/api/v1/simulator/start",
            headers={"X-Simulator-Key": "wrong_key"},
        )
        assert bad_key_resp.status_code == status.HTTP_401_UNAUTHORIZED

        # Request with correct key -> 200 OK
        valid_resp = client.post(
            "/api/v1/simulator/start",
            headers={"X-Simulator-Key": "super_secret_demo_token_123"},
        )
        assert valid_resp.status_code == status.HTTP_200_OK
        assert valid_resp.json()["is_running"] is True

        # Stop with key -> 200 OK
        stop_resp = client.post(
            "/api/v1/simulator/stop",
            headers={"X-Simulator-Key": "super_secret_demo_token_123"},
        )
        assert stop_resp.status_code == status.HTTP_200_OK


# =============================================================================
# 10. Lifespan and Graceful Shutdown
# =============================================================================

def test_lifespan_graceful_shutdown() -> None:
    """Verify application lifespan initializes auto-started task and cleanly cancels on exit."""
    auto_start_settings = SimulatorSettings(
        auto_start=True,
        interval_seconds=0.1,
    )
    generator = TelemetryGenerator(auto_start_settings)
    set_generator_instance(generator)
    app = create_simulator_app(auto_start_settings)

    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["generator_running"] is True

    # After exiting lifespan context, generator must be stopped
    assert generator.is_running is False


# =============================================================================
# 11. Part 6G — Realistic Continuous Simulation & State Tests
# =============================================================================

def test_patient_specific_independent_baselines_and_dynamics() -> None:
    """Verify that each demo patient has a distinct profile, baseline, and recovery kinetics."""
    from simulator.generator import PATIENT_BASELINES, PATIENT_DYNAMICS

    patients = ["P101", "P102", "P103", "P104", "P105"]
    hrs = [PATIENT_BASELINES[p].baseline_heart_rate for p in patients]
    spo2s = [PATIENT_BASELINES[p].baseline_spo2 for p in patients]
    temps = [PATIENT_BASELINES[p].baseline_temperature_f for p in patients]

    # Verify baseline diversity
    assert len(set(hrs)) >= 4, "Heart rate baselines must be distinct across demo patients"
    assert len(set(spo2s)) >= 4, "SpO2 baselines must be distinct across demo patients"
    assert len(set(temps)) >= 3, "Temperature baselines must be distinct across demo patients"

    # Verify distinct dynamic parameters
    rec_rates = [PATIENT_DYNAMICS[p]["recovery_rate"] for p in patients]
    assert len(set(rec_rates)) == 5, "Recovery rates must be individualized per patient"


def test_gradual_value_evolution_no_erratic_jumps() -> None:
    """Verify that vitals evolve continuously with bounded delta between consecutive cycles."""
    settings = SimulatorSettings(auto_start=False, random_seed=42)
    generator = TelemetryGenerator(settings)

    prev_readings: dict = {}
    max_hr_delta = 0.0
    max_spo2_delta = 0.0
    max_temp_delta = 0.0

    # Execute 40 consecutive cycles in resting mode
    for _ in range(40):
        cycle = generator.generate_cycle()
        for r in cycle:
            pid = r.patient_id
            if pid in prev_readings:
                prev = prev_readings[pid]
                hr_delta = abs(r.heart_rate - prev.heart_rate)
                spo2_delta = abs(r.spo2 - prev.spo2)
                temp_delta = abs(r.temperature_f - prev.temperature_f)

                max_hr_delta = max(max_hr_delta, hr_delta)
                max_spo2_delta = max(max_spo2_delta, spo2_delta)
                max_temp_delta = max(max_temp_delta, temp_delta)

                # Slew rate constraints (accounting for possible rare transient noise)
                assert hr_delta <= 4.5, f"Heart rate jumped erratically: {hr_delta} bpm for {pid}"
                assert spo2_delta <= 1.0, f"SpO2 jumped erratically: {spo2_delta}% for {pid}"
                assert temp_delta <= 0.25, f"Temperature jumped erratically: {temp_delta}°F for {pid}"

            prev_readings[pid] = r

    assert max_hr_delta > 0.0, "Telemetry must exhibit realistic dynamic variation"


def test_deterministic_seeded_output() -> None:
    """Verify that identical random seeds produce 100% reproducible numerical telemetry."""
    settings_a = SimulatorSettings(auto_start=False, random_seed=999)
    settings_b = SimulatorSettings(auto_start=False, random_seed=999)

    gen_a = TelemetryGenerator(settings_a)
    gen_b = TelemetryGenerator(settings_b)

    for cycle_idx in range(15):
        cycle_a = gen_a.generate_cycle()
        cycle_b = gen_b.generate_cycle()

        assert len(cycle_a) == len(cycle_b)
        for ra, rb in zip(cycle_a, cycle_b):
            assert ra.patient_id == rb.patient_id
            assert ra.heart_rate == rb.heart_rate, f"Cycle {cycle_idx} HR mismatch: {ra.heart_rate} != {rb.heart_rate}"
            assert ra.spo2 == rb.spo2, f"Cycle {cycle_idx} SpO2 mismatch: {ra.spo2} != {rb.spo2}"
            assert ra.temperature_f == rb.temperature_f, f"Cycle {cycle_idx} Temp mismatch: {ra.temperature_f} != {rb.temperature_f}"


def test_sensor_behavior_states_transitions(simulator_client: TestClient) -> None:
    """Verify state transitions: resting -> active -> recovering -> resting."""
    # 1. Baseline resting readings
    resp_init = simulator_client.get("/api/v1/readings/latest").json()
    base_hr_p101 = resp_init["readings"]["P101"]["heart_rate"]

    # 2. Transition P101 to 'active' state
    act_resp = simulator_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "active", "target_patient_id": "P101"},
    )
    assert act_resp.status_code == status.HTTP_200_OK

    # Simulate 10 active cycles to let HR climb gradually
    gen = simulator_client.app.routes  # Generator is shared via dependency
    from simulator.routes import get_generator
    generator = get_generator()
    for _ in range(10):
        generator.generate_cycle()

    resp_active = simulator_client.get("/api/v1/readings/latest").json()
    active_hr_p101 = resp_active["readings"]["P101"]["heart_rate"]
    assert active_hr_p101 > base_hr_p101 + 10.0, "Heart rate must climb significantly in active state"
    assert resp_active["readings"]["P101"]["state"] == "active"

    # 3. Transition to 'recovering'
    rec_resp = simulator_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "recovering", "target_patient_id": "P101"},
    )
    assert rec_resp.status_code == status.HTTP_200_OK

    # Simulate 15 recovery cycles to decay back to resting baseline
    for _ in range(15):
        generator.generate_cycle()

    resp_recovered = simulator_client.get("/api/v1/readings/latest").json()
    recovered_hr_p101 = resp_recovered["readings"]["P101"]["heart_rate"]
    assert recovered_hr_p101 < active_hr_p101 - 8.0, "Heart rate must decay back down toward baseline during recovery"


def test_signal_interruption_and_recovery(simulator_client: TestClient) -> None:
    """Verify that signal interruption suppresses readings for target patient while other patients continue."""
    from simulator.routes import get_generator
    generator = get_generator()

    # 1. Interrupt P104
    int_resp = simulator_client.post(
        "/api/v1/simulator/interruption",
        json={"patient_id": "P104", "interrupted": True, "reason": "smartwatch_off_wrist"},
    )
    assert int_resp.status_code == status.HTTP_200_OK
    assert "P104" in int_resp.json()["interrupted_patients"]

    # 2. Generate a cycle
    cycle = generator.generate_cycle()
    cycle_patients = [r.patient_id for r in cycle]
    assert "P104" not in cycle_patients, "Interrupted patient P104 must not produce new readings"
    assert "P101" in cycle_patients
    assert "P102" in cycle_patients
    assert "P103" in cycle_patients
    assert "P105" in cycle_patients

    # 3. Check status endpoint
    status_data = simulator_client.get("/api/v1/simulator/status").json()
    assert "P104" in status_data["interrupted_patients"]
    assert "P104" not in status_data["active_patients"]
    assert status_data["patient_states"]["P104"] == "signal_interruption"

    # 4. Resume P104
    resume_resp = simulator_client.post(
        "/api/v1/simulator/interruption",
        json={"patient_id": "P104", "interrupted": False},
    )
    assert resume_resp.status_code == status.HTTP_200_OK
    assert "P104" not in resume_resp.json()["interrupted_patients"]

    # 5. Generate next cycle
    next_cycle = generator.generate_cycle()
    next_cycle_patients = [r.patient_id for r in next_cycle]
    assert "P104" in next_cycle_patients, "Resumed patient P104 must produce readings again"

    # Event IDs must be strictly unique and sequence numbers strictly monotonic
    p104_reading = next(r for r in next_cycle if r.patient_id == "P104")
    assert p104_reading.sequence_number > 0
    assert p104_reading.event_id.startswith("evt_sim_")


def test_scenario_signal_interruption_via_scenario_endpoint(simulator_client: TestClient) -> None:
    """Verify that setting scenario='signal_interruption' halts device transmission."""
    from simulator.routes import get_generator
    generator = get_generator()

    resp = simulator_client.post(
        "/api/v1/simulator/scenario",
        json={"scenario": "signal_interruption", "target_patient_id": "P102"},
    )
    assert resp.status_code == status.HTTP_200_OK

    cycle = generator.generate_cycle()
    pids = [r.patient_id for r in cycle]
    assert "P102" not in pids


def test_controlled_5_minute_continuous_generation_simulation() -> None:
    """
    Controlled 5-minute simulation test:
    Executes 60 continuous generation cycles (60 cycles * 5s = 300s = 5 minutes).
    Verifies that 300 total observations (60 * 5 patients) are produced with:
    - 0 dropped events
    - 100% unique event IDs
    - Strictly monotonic sequence numbering
    - Strictly ordered UTC timestamps
    - All values within physiological safety boundaries
    """
    settings = SimulatorSettings(auto_start=False, random_seed=777)
    generator = TelemetryGenerator(settings)

    total_cycles = 60  # 5 minutes worth of 5s cycles
    expected_readings = total_cycles * len(settings.demo_patients)  # 60 * 5 = 300 readings

    start_time = datetime.now(timezone.utc)
    all_readings = []
    seen_event_ids = set()

    for i in range(total_cycles):
        # Advance virtual clock by 5.0 seconds each cycle
        from datetime import timedelta
        virtual_ts = start_time + timedelta(seconds=i * 5)
        readings = generator.generate_cycle(custom_timestamp=virtual_ts)
        all_readings.extend(readings)

    # 1. Total event count assertion
    assert len(all_readings) == expected_readings
    assert generator.total_readings_generated == expected_readings

    # 2. Event identity and uniqueness
    for r in all_readings:
        assert r.event_id not in seen_event_ids, f"Duplicate event ID detected: {r.event_id}"
        seen_event_ids.add(r.event_id)

        # 3. Bounds check
        assert 50.0 <= r.heart_rate <= 160.0
        assert 90.0 <= r.spo2 <= 100.0
        assert 96.0 <= r.temperature_f <= 102.0
        assert r.is_simulated is True
        assert r.source == "smartwatch_simulator"

    # 4. Sequence number monotonicity
    seqs = [r.sequence_number for r in all_readings]
    assert seqs == list(range(1, expected_readings + 1))

    # 5. Timestamp ordering
    timestamps = [r.timestamp for r in all_readings]
    for k in range(1, len(timestamps)):
        assert timestamps[k] >= timestamps[k - 1]
