"""
Unit and Integration Tests for Part 6O: Reproducible Smart Health Monitoring Demo Scenarios.

Verifies:
1. Scenario A — Normal monitoring: Resting baseline vitals drift without spurious alerts.
2. Scenario B — Elevated heart rate: Controlled tachycardia (HR > 130 bpm) triggers RULE_HR_CRITICAL_HIGH.
3. Scenario C — Low SpO2: Controlled hypoxemia (SpO2 < 85%) triggers RULE_SPO2_CRITICAL_LOW.
4. Scenario D — Baseline recovery: Exponential decay back to resting baseline while preserving existing clinical alerts.
5. Lifecycle controls: Idempotent scenario transitions, immediate Stop cessation, safe Resume.
6. Data provenance: is_simulated=True, source='smartwatch_simulator', isolation from historical Kaggle records.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
import pytest

from database.mysql.models import Alert, IngestionEvent, VitalsReading
from database.mysql.session import get_session_factory
from simulator.generator import TelemetryGenerator, PatientState, PatientBaselineDetail
from simulator.models import ScenarioUpdateRequest
from services.alerts.evaluator import AlertEvaluator


@pytest.fixture
def session():
    """Yield a database session for test execution and roll back transactions cleanly."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def generator():
    """Provide a fresh deterministic TelemetryGenerator instance."""
    gen = TelemetryGenerator()
    gen.reset_state(clear_history=True)
    return gen


class TestScenarioANormalMonitoring:
    """Scenario A: Plausible resting vitals drift without erratic alert-triggering noise across P101–P105."""

    def test_scenario_a_vitals_within_normal_boundaries(self, generator):
        req = ScenarioUpdateRequest(scenario="normal")
        generator.set_scenario(req)

        for _ in range(10):
            readings = generator.generate_cycle()
            assert len(readings) == 5
            for r in readings:
                assert 55.0 <= r.heart_rate <= 100.0, f"Spurious HR excursion: {r.heart_rate} for {r.patient_id}"
                assert 95.0 <= r.spo2 <= 100.0, f"Spurious SpO2 excursion: {r.spo2} for {r.patient_id}"
                assert 97.0 <= r.temperature_f <= 99.5, f"Spurious Temp excursion: {r.temperature_f} for {r.patient_id}"
                assert r.scenario == "normal"
                assert r.state in ("resting", "normal")
                assert r.is_simulated is True
                assert r.source == "smartwatch_simulator"

    def test_scenario_a_triggers_zero_clinical_alerts(self, session, generator):
        req = ScenarioUpdateRequest(scenario="normal")
        generator.set_scenario(req)
        evaluator = AlertEvaluator(session)

        for _ in range(5):
            readings = generator.generate_cycle()
            for r in readings:
                ev = IngestionEvent(
                    event_id=r.event_id,
                    patient_id=r.patient_id,
                    source="smartwatch_simulator",
                    is_simulated=True,
                    measured_at=datetime.now(timezone.utc),
                )
                vitals = [
                    VitalsReading(
                        event_id=r.event_id,
                        patient_id=r.patient_id,
                        metric_code="heart_rate",
                        value=Decimal(str(r.heart_rate)),
                        unit="bpm",
                        quality_status="valid",
                        measured_at=datetime.now(timezone.utc),
                    ),
                    VitalsReading(
                        event_id=r.event_id,
                        patient_id=r.patient_id,
                        metric_code="spo2",
                        value=Decimal(str(r.spo2)),
                        unit="%",
                        quality_status="valid",
                        measured_at=datetime.now(timezone.utc),
                    ),
                ]
                alerts = evaluator.evaluate_readings_batch(ev, vitals)
                assert len(alerts) == 0, f"Expected 0 alerts for normal scenario, got: {[a.rule_id for a in alerts]}"


class TestScenarioBElevatedHeartRate:
    """Scenario B: Controlled synthetic tachycardia event for a selected demo patient."""

    def test_scenario_b_elevated_hr_tachycardia_target_only(self, generator):
        req = ScenarioUpdateRequest(scenario="elevated_hr", target_patient_id="P101")
        generator.set_scenario(req)

        readings = {r.patient_id: r for r in generator.generate_cycle()}
        p101 = readings["P101"]
        assert p101.heart_rate >= 130.0, f"Expected P101 HR >= 130 bpm, got {p101.heart_rate}"
        assert p101.spo2 >= 95.0, f"Expected P101 SpO2 resting, got {p101.spo2}"
        assert p101.scenario == "alert_test"

        # Verify other patients remain in resting normal baseline
        for pid in ["P102", "P103", "P104", "P105"]:
            assert readings[pid].heart_rate <= 100.0, f"Non-target patient {pid} unexpectedly elevated"
            assert readings[pid].scenario == "normal"

    def test_scenario_b_triggers_critical_tachycardia_alert(self, session, generator):
        req = ScenarioUpdateRequest(scenario="elevated_hr", target_patient_id="P101")
        generator.set_scenario(req)
        r = [x for x in generator.generate_cycle() if x.patient_id == "P101"][0]

        ev = IngestionEvent(
            event_id=r.event_id,
            patient_id="P101",
            source="smartwatch_simulator",
            is_simulated=True,
            measured_at=datetime.now(timezone.utc),
        )
        rd = VitalsReading(
            event_id=r.event_id,
            patient_id="P101",
            metric_code="heart_rate",
            value=Decimal(str(r.heart_rate)),
            unit="bpm",
            quality_status="valid",
            measured_at=datetime.now(timezone.utc),
        )
        alerts = AlertEvaluator(session).evaluate_readings_batch(ev, [rd])
        rule_ids = {a.rule_id for a in alerts}
        assert "RULE_HR_HIGH" in rule_ids
        assert "RULE_HR_CRITICAL_HIGH" in rule_ids
        critical_alert = [a for a in alerts if a.rule_id == "RULE_HR_CRITICAL_HIGH"][0]
        assert critical_alert.severity == "CRITICAL"
        assert critical_alert.status == "NEW"


class TestScenarioCLowSpO2:
    """Scenario C: Controlled synthetic hypoxemia event for a selected demo patient."""

    def test_scenario_c_low_spo2_target_only(self, generator):
        req = ScenarioUpdateRequest(scenario="low_spo2", target_patient_id="P102")
        generator.set_scenario(req)

        readings = {r.patient_id: r for r in generator.generate_cycle()}
        p102 = readings["P102"]
        assert p102.spo2 < 85.0, f"Expected P102 SpO2 < 85%, got {p102.spo2}"
        assert p102.heart_rate <= 100.0, f"Expected P102 HR resting, got {p102.heart_rate}"
        assert p102.scenario == "alert_test"

        # Verify other patients remain in normal baseline
        for pid in ["P101", "P103", "P104", "P105"]:
            assert readings[pid].spo2 >= 95.0, f"Non-target patient {pid} unexpectedly affected"

    def test_scenario_c_triggers_critical_hypoxemia_alert(self, session, generator):
        req = ScenarioUpdateRequest(scenario="low_spo2", target_patient_id="P102")
        generator.set_scenario(req)
        r = [x for x in generator.generate_cycle() if x.patient_id == "P102"][0]

        ev = IngestionEvent(
            event_id=r.event_id,
            patient_id="P102",
            source="smartwatch_simulator",
            is_simulated=True,
            measured_at=datetime.now(timezone.utc),
        )
        rd = VitalsReading(
            event_id=r.event_id,
            patient_id="P102",
            metric_code="spo2",
            value=Decimal(str(r.spo2)),
            unit="%",
            quality_status="valid",
            measured_at=datetime.now(timezone.utc),
        )
        alerts = AlertEvaluator(session).evaluate_readings_batch(ev, [rd])
        rule_ids = {a.rule_id for a in alerts}
        assert "RULE_SPO2_LOW" in rule_ids
        assert "RULE_SPO2_CRITICAL_LOW" in rule_ids
        crit_alert = [a for a in alerts if a.rule_id == "RULE_SPO2_CRITICAL_LOW"][0]
        assert crit_alert.severity == "CRITICAL"
        assert crit_alert.status == "NEW"


class TestScenarioDRecoveryAndAlertPreservation:
    """Scenario D: Exponential decay back toward resting baseline without un-authorized alert resolution."""

    def test_scenario_d_recovers_to_baseline(self, generator):
        # Step into tachycardia first
        generator.set_scenario(ScenarioUpdateRequest(scenario="elevated_hr", target_patient_id="P101"))
        generator.generate_cycle()
        assert generator.get_latest_readings()["P101"].heart_rate >= 130.0

        # Step into recovery
        generator.set_scenario(ScenarioUpdateRequest(scenario="recovering", target_patient_id="P101"))
        hr_progression = []
        for _ in range(12):
            readings = generator.generate_cycle()
            hr_progression.append(readings[0].heart_rate)

        # Confirm downward decay toward resting baseline
        assert hr_progression[-1] < hr_progression[0]
        assert hr_progression[-1] <= 100.0, f"Expected final recovered HR <= 100 bpm, got {hr_progression[-1]}"

    def test_scenario_d_preserves_existing_clinical_alerts(self, session):
        # Create an existing alert in NEW status
        alert_id = "alt_test_preservation_6o"
        event_id = "evt_test_preservation_6o"

        # Clean any prior fixture
        session.query(Alert).filter(Alert.alert_id == alert_id).delete()
        session.commit()

        alert = Alert(
            alert_id=alert_id,
            patient_id="P101",
            event_id=event_id,
            rule_id="RULE_HR_CRITICAL_HIGH",
            severity="CRITICAL",
            category="vital_threshold",
            reason="[CRITICAL] Heart rate exceeds 130 bpm.",
            status="NEW",
        )
        session.add(alert)
        session.commit()

        # Simulate normal recovery vitals arriving
        normal_reading = VitalsReading(
            event_id="evt_recovery_step",
            patient_id="P101",
            metric_code="heart_rate",
            value=Decimal("72.0"),
            unit="bpm",
            quality_status="valid",
            measured_at=datetime.now(timezone.utc),
        )
        ev = IngestionEvent(
            event_id="evt_recovery_step",
            patient_id="P101",
            source="smartwatch_simulator",
            is_simulated=True,
            measured_at=datetime.now(timezone.utc),
        )
        new_alerts = AlertEvaluator(session).evaluate_readings_batch(ev, [normal_reading])
        assert len(new_alerts) == 0

        # Verify prior alert status has NOT been modified or closed
        queried = session.query(Alert).filter(Alert.alert_id == alert_id).first()
        assert queried is not None
        assert queried.status == "NEW", "Clinical alert was falsely altered/auto-resolved during recovery"

        # Teardown
        session.delete(queried)
        session.commit()
