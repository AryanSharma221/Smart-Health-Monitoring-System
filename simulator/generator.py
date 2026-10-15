"""
Telemetry Generator and In-Memory State Manager for the Smartwatch Sensor Simulator.

Provides:
- Seeded, deterministic, patient-specific baseline behavior.
- Correlated vital sign drift (HR, SpO2, Temperature).
- Bounded circular in-memory buffer (no unbounded memory growth).
- Lossless cursor-based streaming and polling.
- Thread-safe / async-safe single background worker lifecycle.
- Normal baseline mode vs. explicit alert-test scenario modes.
"""

from __future__ import annotations

import asyncio
import collections
from datetime import datetime, timezone
import logging
import math
import random
import time
from typing import Deque, Dict, List, Optional, Tuple
import uuid

from simulator.config import SimulatorSettings, get_simulator_settings
from simulator.models import (
    PatientBaselineDetail,
    PollingStreamResponse,
    ScenarioUpdateRequest,
    TelemetryReading,
)

logger = logging.getLogger(__name__)

# Configured baseline profiles for demonstration patient cohort P101–P105
PATIENT_BASELINES: Dict[str, PatientBaselineDetail] = {
    "P101": PatientBaselineDetail(
        patient_id="P101",
        baseline_heart_rate=72.0,
        baseline_spo2=98.2,
        baseline_temperature_f=98.4,
        description="Ambulatory baseline profile; healthy resting vital dynamics.",
    ),
    "P102": PatientBaselineDetail(
        patient_id="P102",
        baseline_heart_rate=78.0,
        baseline_spo2=97.5,
        baseline_temperature_f=98.6,
        description="Mild sinus activity tendency during simulated movement.",
    ),
    "P103": PatientBaselineDetail(
        patient_id="P103",
        baseline_heart_rate=66.0,
        baseline_spo2=99.0,
        baseline_temperature_f=98.1,
        description="Athletic resting baseline; high oxygen saturation and lower resting pulse.",
    ),
    "P104": PatientBaselineDetail(
        patient_id="P104",
        baseline_heart_rate=84.0,
        baseline_spo2=96.8,
        baseline_temperature_f=98.7,
        description="Borderline ambulatory SpO2; post-procedure clinical observation profile.",
    ),
    "P105": PatientBaselineDetail(
        patient_id="P105",
        baseline_heart_rate=74.0,
        baseline_spo2=97.8,
        baseline_temperature_f=98.3,
        description="Stable post-operative monitoring trajectory.",
    ),
}

# Individualized physiological dynamics and recovery kinetics per demo patient
PATIENT_DYNAMICS: Dict[str, Dict[str, float]] = {
    "P101": {
        "active_hr_delta": 28.0,
        "active_spo2_delta": -1.0,
        "active_temp_delta": 0.40,
        "recovery_rate": 0.18,
        "phase_offset": 0.0,
    },
    "P102": {
        "active_hr_delta": 36.0,
        "active_spo2_delta": -1.2,
        "active_temp_delta": 0.50,
        "recovery_rate": 0.14,
        "phase_offset": 1.25,
    },
    "P103": {
        "active_hr_delta": 24.0,
        "active_spo2_delta": -0.7,
        "active_temp_delta": 0.35,
        "recovery_rate": 0.28,  # Rapid athletic recovery
        "phase_offset": 2.50,
    },
    "P104": {
        "active_hr_delta": 30.0,
        "active_spo2_delta": -1.5,
        "active_temp_delta": 0.45,
        "recovery_rate": 0.11,  # Slower post-procedure recovery
        "phase_offset": 3.75,
    },
    "P105": {
        "active_hr_delta": 26.0,
        "active_spo2_delta": -0.9,
        "active_temp_delta": 0.38,
        "recovery_rate": 0.20,
        "phase_offset": 5.0,
    },
}


class PatientState:
    """Tracks continuous physiological state, activity models, and signal interruption per patient."""

    def __init__(self, patient_id: str, baseline: PatientBaselineDetail, prng: random.Random) -> None:
        self.patient_id = patient_id
        self.baseline = baseline
        self.prng = prng
        self.current_hr = baseline.baseline_heart_rate
        self.current_spo2 = baseline.baseline_spo2
        self.current_temp = baseline.baseline_temperature_f
        self.step_count = 0
        self.state_step_count = 0
        self.state: str = "resting"
        self.is_interrupted: bool = False

        dyn = PATIENT_DYNAMICS.get(
            patient_id,
            {
                "active_hr_delta": 28.0,
                "active_spo2_delta": -1.0,
                "active_temp_delta": 0.40,
                "recovery_rate": 0.18,
                "phase_offset": 0.0,
            },
        )
        self.active_hr_delta = dyn["active_hr_delta"]
        self.active_spo2_delta = dyn["active_spo2_delta"]
        self.active_temp_delta = dyn["active_temp_delta"]
        self.recovery_rate = dyn["recovery_rate"]
        self.phase_offset = dyn["phase_offset"]

        self.alert_metric: str = "all"

    def set_state(self, new_state: str, alert_metric: str = "all") -> None:
        """Update behavioral state ('resting', 'active', 'recovering', 'signal_interruption', 'alert_test', 'elevated_hr', 'low_spo2')."""
        self.alert_metric = alert_metric
        if new_state == "signal_interruption":
            self.is_interrupted = True
            self.state = "signal_interruption"
        elif new_state == "elevated_hr":
            self.is_interrupted = False
            self.state = "alert_test"
            self.alert_metric = "heart_rate"
        elif new_state == "low_spo2":
            self.is_interrupted = False
            self.state = "alert_test"
            self.alert_metric = "spo2"
        elif new_state in ("normal", "resting"):
            self.is_interrupted = False
            self.state = "resting"
            self.alert_metric = "all"
        else:
            self.is_interrupted = False
            self.state = new_state
        self.state_step_count = 0

    def set_interrupted(self, interrupted: bool) -> None:
        """Toggle simulated connectivity loss for this device."""
        self.is_interrupted = interrupted
        if interrupted:
            self.state = "signal_interruption"
        elif self.state == "signal_interruption":
            self.state = "resting"
        self.state_step_count = 0

    def step(
        self,
        scenario: Optional[str] = None,
        alert_metric: Optional[str] = None,
    ) -> Optional[Tuple[float, float, float, str, str]]:
        """
        Advance patient vitals by one continuous, smoothed physiological step.
        Returns (heart_rate, spo2, temperature_f, scenario_label, state_label),
        or None if device transmission is currently interrupted.
        """
        if self.is_interrupted or self.state == "signal_interruption":
            return None

        self.step_count += 1
        self.state_step_count += 1

        effective_metric = alert_metric if alert_metric is not None else self.alert_metric

        # Resolve active effective state:
        if scenario in ("alert_test", "elevated_hr", "low_spo2"):
            active_state = "alert_test"
            scenario_label = "alert_test"
            if scenario == "elevated_hr":
                effective_metric = "heart_rate"
            elif scenario == "low_spo2":
                effective_metric = "spo2"
        elif self.state == "alert_test":
            active_state = "alert_test"
            scenario_label = "alert_test"
        elif scenario is not None and scenario not in ("normal", "resting", "default"):
            active_state = scenario
            scenario_label = scenario
        else:
            active_state = self.state
            scenario_label = "normal" if active_state in ("resting", "normal") else active_state

        if active_state == "alert_test":
            hr, spo2, temp = self._step_alert_state(effective_metric)
        elif active_state == "active":
            hr, spo2, temp = self._step_active_state()
        elif active_state == "recovering":
            hr, spo2, temp = self._step_recovering_state()
        else:  # "resting" or "normal"
            hr, spo2, temp = self._step_resting_state()

        # Rare simulated measurement noise / transient optical artifact (~2% probability)
        if active_state != "alert_test" and self.prng.random() < 0.025:
            if self.prng.random() < 0.5:
                hr = round(max(55.0, min(100.0, hr + self.prng.uniform(-1.5, 1.5))), 1)
            else:
                spo2 = round(max(95.0, min(99.8, spo2 + self.prng.uniform(-0.3, 0.3))), 1)

        self.current_hr = hr
        self.current_spo2 = spo2
        self.current_temp = temp

        return hr, spo2, temp, scenario_label, active_state

    def _step_resting_state(self) -> Tuple[float, float, float]:
        """Stable resting baseline with respiratory sinus arrhythmia and slight OU drift."""
        target_hr = self.baseline.baseline_heart_rate
        target_spo2 = self.baseline.baseline_spo2
        target_temp = self.baseline.baseline_temperature_f

        hr_reversion = 0.12 * (target_hr - self.current_hr)
        hr_sin = 0.6 * math.sin(self.step_count * 0.52 + self.phase_offset)
        hr_noise = self.prng.gauss(0.0, 0.45)
        raw_hr = self.current_hr + hr_reversion + hr_sin + hr_noise
        bounded_hr = max(self.current_hr - 3.2, min(self.current_hr + 3.2, raw_hr))
        hr = round(max(56.0, min(100.0, bounded_hr)), 1)

        spo2_reversion = 0.15 * (target_spo2 - self.current_spo2)
        spo2_noise = self.prng.gauss(0.0, 0.08)
        raw_spo2 = self.current_spo2 + spo2_reversion + spo2_noise
        bounded_spo2 = max(self.current_spo2 - 0.4, min(self.current_spo2 + 0.4, raw_spo2))
        spo2 = round(max(95.0, min(99.8, bounded_spo2)), 1)

        temp_reversion = 0.08 * (target_temp - self.current_temp)
        temp_noise = self.prng.gauss(0.0, 0.02)
        raw_temp = self.current_temp + temp_reversion + temp_noise
        bounded_temp = max(self.current_temp - 0.08, min(self.current_temp + 0.08, raw_temp))
        temp = round(max(97.2, min(99.2, bounded_temp)), 2)

        return hr, spo2, temp

    def _step_active_state(self) -> Tuple[float, float, float]:
        """Active state: progressive exertion climb toward elevated physiological plateau."""
        target_hr = self.baseline.baseline_heart_rate + self.active_hr_delta
        target_spo2 = max(93.5, self.baseline.baseline_spo2 + self.active_spo2_delta)
        target_temp = self.baseline.baseline_temperature_f + self.active_temp_delta

        hr_drift = 0.16 * (target_hr - self.current_hr)
        hr_noise = self.prng.gauss(0.0, 0.65)
        raw_hr = self.current_hr + hr_drift + hr_noise
        bounded_hr = max(self.current_hr - 2.0, min(self.current_hr + 3.8, raw_hr))
        hr = round(max(58.0, min(148.0, bounded_hr)), 1)

        spo2_drift = 0.12 * (target_spo2 - self.current_spo2)
        spo2_noise = self.prng.gauss(0.0, 0.12)
        raw_spo2 = self.current_spo2 + spo2_drift + spo2_noise
        bounded_spo2 = max(self.current_spo2 - 0.5, min(self.current_spo2 + 0.5, raw_spo2))
        spo2 = round(max(92.5, min(99.5, bounded_spo2)), 1)

        temp_drift = 0.05 * (target_temp - self.current_temp)
        temp_noise = self.prng.gauss(0.0, 0.02)
        raw_temp = self.current_temp + temp_drift + temp_noise
        bounded_temp = max(self.current_temp - 0.08, min(self.current_temp + 0.10, raw_temp))
        temp = round(max(97.4, min(100.2, bounded_temp)), 2)

        return hr, spo2, temp

    def _step_recovering_state(self) -> Tuple[float, float, float]:
        """Recovering state: exponential decay from exertion/tachycardia back down toward resting baseline."""
        target_hr = self.baseline.baseline_heart_rate
        target_spo2 = self.baseline.baseline_spo2
        target_temp = self.baseline.baseline_temperature_f

        # Biphasic HR recovery: rapid initial parasympathetic reactivation when > 100 bpm, followed by asymptotic baseline convergence
        hr_noise = self.prng.gauss(0.0, 0.35)
        if self.current_hr > 100.0:
            hr_drop = min(15.0, max(8.0, 0.40 * (self.current_hr - target_hr)))
            raw_hr = self.current_hr - hr_drop + hr_noise
            bounded_hr = max(target_hr, min(self.current_hr, raw_hr))
        else:
            hr_decay = -self.recovery_rate * (self.current_hr - target_hr)
            raw_hr = self.current_hr + hr_decay + hr_noise
            bounded_hr = max(self.current_hr - 4.0, min(self.current_hr + 1.5, raw_hr))
        hr = round(max(56.0, min(140.0, bounded_hr)), 1)

        # SpO2 recovery: swift stabilization toward healthy saturation
        spo2_noise = self.prng.gauss(0.0, 0.08)
        if self.current_spo2 < 93.0:
            spo2_rise = min(4.5, max(2.5, 0.45 * (target_spo2 - self.current_spo2)))
            raw_spo2 = self.current_spo2 + spo2_rise + spo2_noise
            bounded_spo2 = min(target_spo2, max(self.current_spo2, raw_spo2))
        else:
            spo2_reversion = 0.20 * (target_spo2 - self.current_spo2)
            raw_spo2 = self.current_spo2 + spo2_reversion + spo2_noise
            bounded_spo2 = max(self.current_spo2 - 0.2, min(self.current_spo2 + 0.8, raw_spo2))
        spo2 = round(max(91.0, min(99.8, bounded_spo2)), 1)

        temp_decay = -0.06 * (self.current_temp - target_temp)
        temp_noise = self.prng.gauss(0.0, 0.02)
        raw_temp = self.current_temp + temp_decay + temp_noise
        bounded_temp = max(self.current_temp - 0.08, min(self.current_temp + 0.08, raw_temp))
        temp = round(max(97.2, min(99.6, bounded_temp)), 2)

        if abs(hr - target_hr) <= 2.5 and self.state_step_count >= 6:
            self.state = "resting"
            self.state_step_count = 0

        return hr, spo2, temp

    def _step_alert_state(self, metric: str) -> Tuple[float, float, float]:
        """Explicit alert-test state with controlled emergency threshold excursions."""
        rest_hr, rest_spo2, rest_temp = self._step_resting_state()

        if metric in ("heart_rate", "elevated_hr", "all"):
            target_hr = 135.5 + self.prng.uniform(0.5, 3.0)
            hr = round(min(target_hr, max(self.current_hr + 12.0, 134.0)), 1)
        else:
            hr = rest_hr

        if metric in ("spo2", "low_spo2", "all"):
            target_spo2 = 83.8 + self.prng.uniform(-0.5, 0.8)
            spo2 = round(target_spo2, 1)
        else:
            spo2 = rest_spo2

        if metric in ("temperature", "high_temp", "all"):
            target_temp = 101.8 + self.prng.uniform(0.1, 0.6)
            temp = round(target_temp, 2)
        else:
            temp = rest_temp

        return hr, spo2, temp

    def step_normal(self) -> Tuple[float, float, float]:
        """Backward-compatible helper advancing vitals in resting normal mode."""
        res = self.step(scenario="resting")
        if res is None:
            return self.current_hr, self.current_spo2, self.current_temp
        return res[0], res[1], res[2]

    def step_alert(self, metric: str = "all") -> Tuple[float, float, float]:
        """Backward-compatible helper advancing vitals in alert test mode."""
        res = self.step(scenario="alert_test", alert_metric=metric)
        if res is None:
            return self.current_hr, self.current_spo2, self.current_temp
        return res[0], res[1], res[2]


class TelemetryGenerator:
    """
    Central controller managing synthetic smartwatch data generation, in-memory buffers,
    and background worker lifecycle.
    """

    def __init__(self, settings: Optional[SimulatorSettings] = None) -> None:
        self.settings = settings or get_simulator_settings()
        self.prng = random.Random(self.settings.random_seed)
        self.start_time = time.time()

        # In-memory bounded buffer
        self._history: Deque[TelemetryReading] = collections.deque(
            maxlen=self.settings.max_history_records
        )
        self._latest_by_patient: Dict[str, TelemetryReading] = {}
        self._sequence_counter: int = 0
        self._total_generated: int = 0
        self._latest_generation_at: Optional[datetime] = None

        # Scenario controls
        self.current_scenario: str = self.settings.default_scenario
        self.scenario_target_patient: Optional[str] = None
        self.scenario_alert_metric: str = "all"

        # Concurrency & Worker management
        self._lifecycle_state: str = "STOPPED"
        self._is_running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._stop_event.set()
        self._last_error: Optional[str] = None
        self._lock = asyncio.Lock()

        # Initialize patient states with deterministic patient-specific sub-seeds
        self._patient_states: Dict[str, PatientState] = {}
        for pid in self.settings.demo_patients:
            baseline = PATIENT_BASELINES.get(
                pid,
                PatientBaselineDetail(
                    patient_id=pid,
                    baseline_heart_rate=72.0,
                    baseline_spo2=98.0,
                    baseline_temperature_f=98.6,
                    description="Standard baseline profile",
                ),
            )
            patient_seed = (self.settings.random_seed * 31 + sum(ord(c) for c in pid)) & 0xFFFFFFFF
            self._patient_states[pid] = PatientState(pid, baseline, random.Random(patient_seed))

    @property
    def is_running(self) -> bool:
        """Returns True if the background generation worker is actively scheduled."""
        return (
            self._lifecycle_state == "RUNNING"
            and self._is_running
            and self._worker_task is not None
            and not self._worker_task.done()
        )

    @property
    def lifecycle_state(self) -> str:
        """Explicit lifecycle state: 'RUNNING', 'STOPPING', 'STOPPED', 'ERROR'."""
        if self._lifecycle_state == "RUNNING":
            if self._worker_task is None or self._worker_task.done():
                return "STOPPED"
        return self._lifecycle_state

    @property
    def total_readings_generated(self) -> int:
        return self._total_generated

    @property
    def buffer_count(self) -> int:
        return len(self._history)

    @property
    def latest_generation_timestamp(self) -> Optional[datetime]:
        return self._latest_generation_at

    def generate_cycle(self, custom_timestamp: Optional[datetime] = None) -> List[TelemetryReading]:
        """
        Generate exactly one reading for each active demo patient.
        Interrupted devices are safely skipped without reusing or skipping sequence IDs.
        Thread-safe; can be invoked synchronously for deterministic test execution.
        """
        now_utc = custom_timestamp or datetime.now(timezone.utc)
        cycle_readings: List[TelemetryReading] = []

        for pid in self.settings.demo_patients:
            state = self._patient_states.get(pid)
            if not state:
                continue

            res = state.step()

            # If patient wearable is in signal interruption, step() returns None
            if res is None:
                continue

            hr, spo2, temp_f, scenario_label, state_label = res

            self._sequence_counter += 1
            self._total_generated += 1
            seq = self._sequence_counter

            # Construct globally unique event ID
            uid_short = uuid.uuid4().hex[:8]
            event_id = f"evt_sim_{seq}_{uid_short}"

            # Exact Celsius conversion: (°F - 32) * 5/9
            temp_c = round((temp_f - 32.0) * (5.0 / 9.0), 2)

            reading = TelemetryReading(
                event_id=event_id,
                patient_id=pid,
                timestamp=now_utc,
                measured_at=now_utc,
                source=self.settings.source_identifier,
                is_simulated=True,
                heart_rate=hr,
                spo2=spo2,
                temperature_f=temp_f,
                temperature_c=temp_c,
                scenario=scenario_label,
                state=state_label,
                sequence_number=seq,
            )

            self._history.append(reading)
            self._latest_by_patient[pid] = reading
            cycle_readings.append(reading)

        self._latest_generation_at = now_utc
        return cycle_readings

    async def start(self) -> bool:
        """
        Starts the continuous background generation task if not already running.
        Guarantees single task execution; duplicate calls return False safely.
        """
        async with self._lock:
            if self.is_running:
                logger.info("Simulator generation already active; ignoring duplicate start request.")
                return False

            if self._lifecycle_state == "STOPPING" and self._worker_task and not self._worker_task.done():
                try:
                    await asyncio.wait_for(self._worker_task, timeout=1.0)
                except Exception:
                    pass

            self._stop_event.clear()
            self._is_running = True
            self._lifecycle_state = "RUNNING"
            self._last_error = None
            self._worker_task = asyncio.create_task(self._background_loop(), name="smartwatch_simulator_worker")
            logger.info(
                "Started smartwatch simulator background task (interval: %.1fs, patients: %s)",
                self.settings.interval_seconds,
                self.settings.demo_patients,
            )
            return True

    async def stop(self) -> bool:
        """
        Safely stops the continuous background generation worker immediately and awaits task termination.
        Idempotent: safe to call repeatedly when stopped.
        """
        async with self._lock:
            if not self._is_running and (self._worker_task is None or self._worker_task.done()):
                self._lifecycle_state = "STOPPED"
                return False

            self._lifecycle_state = "STOPPING"
            self._is_running = False
            self._stop_event.set()

            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None

            self._lifecycle_state = "STOPPED"
            logger.info("Smartwatch simulator background task stopped gracefully.")
            return True

    async def _background_loop(self) -> None:
        """Continuous background execution loop running at configured interval with immediate stop responsiveness."""
        try:
            while not self._stop_event.is_set() and self._is_running:
                self.generate_cycle()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.settings.interval_seconds,
                    )
                    # If stop_event was signaled, break out immediately
                    break
                except asyncio.TimeoutError:
                    # Timeout elapsed normally; proceed to next cycle
                    pass
        except asyncio.CancelledError:
            logger.debug("Background generator loop task received cancellation.")
        except Exception as exc:
            logger.error("Unexpected error in smartwatch generator loop: %s", exc, exc_info=True)
            self._lifecycle_state = "ERROR"
            self._last_error = str(exc)
            self._is_running = False
        finally:
            if self._lifecycle_state != "ERROR":
                self._lifecycle_state = "STOPPED"
            self._is_running = False

    def get_latest_readings(self) -> Dict[str, TelemetryReading]:
        """Retrieve most recent generated reading for each patient."""
        return dict(self._latest_by_patient)

    def get_bounded_readings(
        self,
        patient_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[TelemetryReading]:
        """
        Retrieve recent readings sorted newest-first, with optional patient filtering.
        """
        bounded_limit = max(1, min(limit, 500))
        results: List[TelemetryReading] = []

        # Iterate in reverse (newest first)
        for r in reversed(self._history):
            if patient_id is not None and r.patient_id != patient_id:
                continue
            results.append(r)
            if len(results) >= bounded_limit:
                break

        return results

    def poll_stream(
        self,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> PollingStreamResponse:
        """
        Reliable cursor-based polling for downstream consumers (e.g. backend ingestors).
        Returns readings strictly newer than cursor in chronological order.
        """
        bounded_limit = max(1, min(limit, 200))
        target_seq = 0

        if cursor:
            # Support parsing cursor as integer sequence or event_id (evt_sim_<seq>_...)
            if cursor.isdigit():
                target_seq = int(cursor)
            elif cursor.startswith("evt_sim_"):
                parts = cursor.split("_")
                if len(parts) >= 3 and parts[2].isdigit():
                    target_seq = int(parts[2])

            # If downstream consumer's cursor is ahead of simulator's sequence counter
            # (e.g. simulator was restarted fresh while consumer has persistent DB cursor),
            # align sequence numbers so newly generated readings flow past consumer cursor.
            if target_seq > self._sequence_counter:
                logger.info(
                    "Consumer cursor sequence %d is ahead of generator sequence %d; aligning generator counter",
                    target_seq,
                    self._sequence_counter,
                )
                if self._history:
                    min_seq = self._history[0].sequence_number
                    shift = (target_seq - min_seq) + 1
                    for item in self._history:
                        item.sequence_number += shift
                        uid = uuid.uuid4().hex[:8]
                        item.event_id = f"evt_sim_{item.sequence_number}_{uid}"
                    self._sequence_counter = self._history[-1].sequence_number
                else:
                    self._sequence_counter = target_seq

        new_items: List[TelemetryReading] = []
        has_more = False

        for r in self._history:
            if r.sequence_number > target_seq:
                if len(new_items) < bounded_limit:
                    new_items.append(r)
                else:
                    has_more = True
                    break

        # Compute next cursor
        if new_items:
            next_cursor = str(new_items[-1].sequence_number)
            newest_seq = new_items[-1].sequence_number
        else:
            # If no new items, maintain the highest seen sequence or existing cursor
            next_cursor = cursor or str(self._sequence_counter)
            newest_seq = None

        return PollingStreamResponse(
            items=new_items,
            count=len(new_items),
            cursor=cursor,
            next_cursor=next_cursor,
            has_more=has_more,
            newest_sequence_number=newest_seq,
        )

    def set_interruption(self, patient_id: Optional[str] = None, interrupted: bool = True) -> List[str]:
        """Toggle signal interruption for target patient or whole cohort."""
        targets = [patient_id] if patient_id else list(self.settings.demo_patients)
        for pid in targets:
            if pid in self._patient_states:
                self._patient_states[pid].set_interrupted(interrupted)
        logger.info(
            "Signal interruption toggled: targets=%s, interrupted=%s (active interrupted: %s)",
            targets,
            interrupted,
            self.get_interrupted_patients(),
        )
        return self.get_interrupted_patients()

    def get_interrupted_patients(self) -> List[str]:
        """List patient IDs currently under simulated signal interruption."""
        return [pid for pid, state in self._patient_states.items() if state.is_interrupted]

    def get_active_patients(self) -> List[str]:
        """List patient IDs currently active and transmitting telemetry."""
        return [pid for pid, state in self._patient_states.items() if not state.is_interrupted]

    def get_patient_states(self) -> Dict[str, str]:
        """Return current behavioral state per patient."""
        return {pid: state.state for pid, state in self._patient_states.items()}

    def set_scenario(self, request: ScenarioUpdateRequest) -> None:
        """Update simulation scenario or specific sensor behavior state."""
        self.current_scenario = request.scenario
        self.scenario_target_patient = request.target_patient_id

        # Normalize scenario aliases
        resolved_metric = request.alert_metric
        resolved_scenario = request.scenario
        if request.scenario == "elevated_hr":
            resolved_scenario = "alert_test"
            resolved_metric = "heart_rate"
        elif request.scenario == "low_spo2":
            resolved_scenario = "alert_test"
            resolved_metric = "spo2"

        self.scenario_alert_metric = resolved_metric

        targets = [request.target_patient_id] if request.target_patient_id else list(self.settings.demo_patients)
        for pid in targets:
            if pid in self._patient_states:
                if resolved_scenario == "signal_interruption":
                    self._patient_states[pid].set_interrupted(True)
                else:
                    self._patient_states[pid].set_state(resolved_scenario, alert_metric=resolved_metric)

        logger.info(
            "Simulator scenario updated: scenario=%s (resolved=%s), target_patient=%s, metric=%s",
            request.scenario,
            resolved_scenario,
            request.target_patient_id,
            resolved_metric,
        )

    def reset_state(self, clear_history: bool = False) -> None:
        """Reset internal generator PRNG and patient states for deterministic test isolation."""
        self.prng = random.Random(self.settings.random_seed)
        self.current_scenario = self.settings.default_scenario
        self.scenario_target_patient = None
        self.scenario_alert_metric = "all"
        if clear_history:
            self._history.clear()
            self._latest_by_patient.clear()
            self._sequence_counter = 0
            self._total_generated = 0
            self._latest_generation_at = None

        for pid in self.settings.demo_patients:
            baseline = PATIENT_BASELINES.get(
                pid,
                PatientBaselineDetail(
                    patient_id=pid,
                    baseline_heart_rate=72.0,
                    baseline_spo2=98.0,
                    baseline_temperature_f=98.6,
                    description="Standard baseline profile",
                ),
            )
            patient_seed = (self.settings.random_seed * 31 + sum(ord(c) for c in pid)) & 0xFFFFFFFF
            self._patient_states[pid] = PatientState(pid, baseline, random.Random(patient_seed))
