"""
Smart Health Monitoring System — Machine Learning Integration Service.

Encapsulates:
1. Thread-safe Isolation Forest telemetry scoring via the health_analysis package.
2. Frozen baseline management initialized from the verified Kaggle historical dataset.
3. Safe degradation when model artifacts are missing or corrupt without taking down the gateway.
4. Idempotent relational persistence into MySQL model_assessments and clinical alerts.
5. Outbox queue event staging for MongoDB Atlas analytics replication.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from sqlalchemy.orm import Session

from database.mysql.models import (
    Alert,
    AlertStatusHistory,
    ModelAssessment,
)
from database.mysql.repositories.alert_repository import AlertRepository
from database.mysql.repositories.assessment_repository import AssessmentRepository
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.repositories.outbox_repository import OutboxRepository
from database.mysql.session import transaction_scope
from services.api.config import Settings, get_settings
from services.websocket.dispatcher import notify_alert_created

logger = logging.getLogger(__name__)

# Ensure health_analysis is on sys.path if not installed globally
def _ensure_health_analysis_importable(settings: Settings) -> None:
    try:
        import health_analysis  # noqa: F401
    except ImportError:
        candidate_paths = [
            Path(__file__).resolve().parent.parent.parent / "HarnoorKant-Smart-Health-Monitoring-System" / "packages",
            Path("packages").resolve(),
            Path("../HarnoorKant-Smart-Health-Monitoring-System/packages").resolve(),
        ]
        for p in candidate_paths:
            if p.exists() and (p / "health_analysis").exists():
                str_p = str(p)
                if str_p not in sys.path:
                    sys.path.insert(0, str_p)
                logger.info("Added ML package path to sys.path: %s", str_p)
                break


class MLService:
    """
    Dedicated application service for machine learning telemetry anomaly detection.
    
    Guarantees:
    1. Loads Isolation Forest model artifact once during initialization.
    2. Enforces thread-safe evaluation across concurrent requests.
    3. Never blocks event loop with in-flight retraining.
    4. Handles degraded state cleanly without raising unhandled 500s.
    5. Maps outputs strictly to database constraints ('normal', 'anomaly', 'inconclusive').
    """

    def __init__(
        self,
        artifact_dir: Optional[Union[str, Path]] = None,
        dataset_path: Optional[Union[str, Path]] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        _ensure_health_analysis_importable(self.settings)

        self._lock = threading.Lock()
        self.is_available: bool = False
        self.degraded_reason: Optional[str] = None
        self.model_version: str = self.settings.model_version
        self.artifact_path: Optional[Path] = None

        self._service: Optional[Any] = None
        self._baseline_manager: Optional[Any] = None

        # Resolve paths
        if artifact_dir:
            self.artifact_path = Path(artifact_dir).resolve()
        else:
            self.artifact_path = self.settings.resolve_model_artifact_dir()

        resolved_dataset = Path(dataset_path).resolve() if dataset_path else self.settings.get_resolved_dataset_path()

        self._initialize_service(resolved_dataset)

    def _initialize_service(self, dataset_path: Path) -> None:
        """Initialize the HealthAnalysisService with model artifacts and baseline data."""
        try:
            from health_analysis.baseline import BaselineManager
            from health_analysis.service import HealthAnalysisService

            # 1. Initialize BaselineManager from verified training split if available
            actual_dataset = dataset_path
            if not actual_dataset.exists():
                fallbacks = [
                    Path(r"E:\kaggle_health_dataset.csv"),
                    Path(r"E:\DOC-20261013-WA0056.csv"),
                    Path(__file__).resolve().parent.parent.parent / "HarnoorKant-Smart-Health-Monitoring-System" / "data" / "raw" / "kaggle_health_dataset.csv",
                ]
                for cand in fallbacks:
                    if cand.exists():
                        actual_dataset = cand
                        break

            if actual_dataset.exists():
                try:
                    logger.info("Initializing BaselineManager from dataset: %s", actual_dataset)
                    df_raw = pd.read_csv(actual_dataset)
                    # Train split matches Member 3's 70% first partition (1,048 rows)
                    train_rows = min(1048, len(df_raw))
                    self._baseline_manager = BaselineManager().fit(df_raw.iloc[:train_rows])
                    logger.info("BaselineManager fit successfully across %d patient cohorts.", len(self._baseline_manager.baselines))
                except Exception as exc:
                    logger.warning("Failed to fit BaselineManager from %s: %s. Using default baselines.", actual_dataset, exc)
                    self._baseline_manager = BaselineManager()
            else:
                logger.info("Dataset path %s not found. Proceeding with unseeded BaselineManager.", dataset_path)
                self._baseline_manager = BaselineManager()

            # 2. Check model artifact directory
            if not self.artifact_path or not self.artifact_path.exists():
                self.is_available = False
                self.degraded_reason = f"Model artifact directory not found at {self.artifact_path}"
                logger.warning("MLService degraded: %s", self.degraded_reason)
                return

            model_file = self.artifact_path / "model.joblib"
            if not model_file.exists():
                self.is_available = False
                self.degraded_reason = f"Model file 'model.joblib' missing from {self.artifact_path}"
                logger.warning("MLService degraded: %s", self.degraded_reason)
                return

            # 3. Load HealthAnalysisService
            self._service = HealthAnalysisService(
                artifact_dir=str(self.artifact_path),
                baseline_manager=self._baseline_manager,
            )

            if self._service.detector and self._service.detector.is_fitted:
                self.is_available = True
                self.model_version = self._service.detector.config.model_version
                self.degraded_reason = None
                logger.info("MLService loaded successfully. IsolationForest v%s ready for inference.", self.model_version)
            else:
                self.is_available = False
                self.degraded_reason = "IsolationForestDetector failed to instantiate in fitted state."
                logger.warning("MLService degraded: %s", self.degraded_reason)

        except Exception as exc:
            self.is_available = False
            self.degraded_reason = f"Unexpected error during MLService initialization: {exc}"
            logger.error("MLService initialization failure: %s", exc, exc_info=True)

    def get_status(self) -> Dict[str, Any]:
        """Return operational status and metadata for diagnostics and health checks."""
        return {
            "status": "ready" if self.is_available else "degraded",
            "is_available": self.is_available,
            "model_version": self.model_version,
            "artifact_path": str(self.artifact_path) if self.artifact_path else None,
            "feature_count": 38,
            "algorithm": "IsolationForest",
            "degraded_reason": self.degraded_reason,
            "has_baseline_manager": self._baseline_manager is not None and getattr(self._baseline_manager, "is_fitted", False),
        }

    def clear_buffers(self, patient_id: Optional[str] = None) -> None:
        """
        Clear in-memory streaming feature buffers for a specific patient or all patients.
        Guarantees isolation during tests or patient cohort resets.
        """
        with self._lock:
            if self._service and hasattr(self._service, "streaming_extractor"):
                buffers = getattr(self._service.streaming_extractor, "buffers", None)
                if isinstance(buffers, dict):
                    if patient_id:
                        buffers.pop(str(patient_id), None)
                    else:
                        buffers.clear()

    def assess(
        self,
        patient_id: str,
        timestamp: Union[str, pd.Timestamp, Any],
        heart_rate: Optional[float],
        spo2: Optional[float],
        temperature_f: Optional[float],
        respiratory_rate: Optional[float] = None,
        systolic_bp: Optional[float] = None,
        diastolic_bp: Optional[float] = None,
        source_event_id: Optional[str] = None,
        is_simulated: bool = True,
    ) -> Any:
        """
        Thread-safe inference evaluation for a single patient telemetry reading.
        Never raises uncaught exceptions.
        """
        if not self.is_available or self._service is None:
            # Degraded graceful fallback response
            from health_analysis.service import AssessmentResult
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            return AssessmentResult(
                model_version=self.model_version,
                score=0.0,
                result="insufficient_data",
                feature_summary={"error": "model_unavailable", "detail": self.degraded_reason},
                time_window_start=now,
                time_window_end=now,
                explanation=["ML anomaly detection service is currently unavailable or degraded."],
                patient_id=str(patient_id),
                is_simulated=is_simulated,
                assessment_id=f"asmt_{source_event_id}" if source_event_id else None,
                latency_ms=0.0,
            )

        with self._lock:
            return self._service.assess_telemetry(
                patient_id=patient_id,
                timestamp=timestamp,
                heart_rate=heart_rate,
                spo2=spo2,
                temperature_f=temperature_f,
                respiratory_rate=respiratory_rate,
                systolic_bp=systolic_bp,
                diastolic_bp=diastolic_bp,
                source_event_id=source_event_id,
                is_simulated=is_simulated,
            )

    def assess_and_persist(
        self,
        db: Session,
        patient_id: str,
        timestamp: Union[str, pd.Timestamp, Any],
        heart_rate: Optional[float],
        spo2: Optional[float],
        temperature_f: Optional[float],
        respiratory_rate: Optional[float] = None,
        systolic_bp: Optional[float] = None,
        diastolic_bp: Optional[float] = None,
        source_event_id: Optional[str] = None,
        is_simulated: bool = True,
        trigger_alert: bool = True,
    ) -> Tuple[ModelAssessment, Optional[Alert], Any]:
        """
        Execute ML assessment and atomically persist ModelAssessment record in MySQL.
        If anomalous, conditionally triggers an Alert and stages MongoDB outbox synchronization.
        
        Database Check Constraint Mapping:
            'normal_like'        -> 'normal'
            'anomalous'          -> 'anomaly'
            'insufficient_data'  -> 'inconclusive'
        """
        res = self.assess(
            patient_id=patient_id,
            timestamp=timestamp,
            heart_rate=heart_rate,
            spo2=spo2,
            temperature_f=temperature_f,
            respiratory_rate=respiratory_rate,
            systolic_bp=systolic_bp,
            diastolic_bp=diastolic_bp,
            source_event_id=source_event_id,
            is_simulated=is_simulated,
        )

        # Map to MySQL check constraint ck_assessments_result: ('normal', 'anomaly', 'inconclusive')
        db_result_map = {
            "normal_like": "normal",
            "anomalous": "anomaly",
            "insufficient_data": "inconclusive",
        }
        db_result = db_result_map.get(res.result, "inconclusive")

        # Deterministic assessment ID
        if source_event_id:
            assessment_id = f"asmt_{source_event_id}"
        else:
            ts_str = str(timestamp)
            digest = hashlib.sha256(f"{patient_id}:{ts_str}:{heart_rate}:{spo2}".encode("utf-8")).hexdigest()[:20]
            assessment_id = f"asmt_{digest}"

        assessment_repo = AssessmentRepository(db)
        alert_repo = AlertRepository(db)
        audit_repo = AuditRepository(db)
        outbox_repo = OutboxRepository(db)

        persisted_alert: Optional[Alert] = None
        newly_created_alert = False

        with transaction_scope(db):
            candidate_assessment = ModelAssessment(
                assessment_id=assessment_id,
                patient_id=str(patient_id),
                event_id=source_event_id,
                model_version=res.model_version,
                score=Decimal(f"{float(res.score):.4f}"),
                result=db_result,
                features_json=json.dumps(res.feature_summary),
                time_window_start=res.time_window_start,
                time_window_end=res.time_window_end,
            )

            persisted_assessment, _ = assessment_repo.create_or_get_assessment(candidate_assessment)

            # Stage outbox event for MongoDB Atlas synchronization
            outbox_payload = {
                "assessment_id": persisted_assessment.assessment_id,
                "patient_id": persisted_assessment.patient_id,
                "event_id": persisted_assessment.event_id,
                "model_version": persisted_assessment.model_version,
                "score": float(persisted_assessment.score),
                "result": persisted_assessment.result,
                "feature_summary": res.feature_summary,
                "time_window_start": res.time_window_start.isoformat() if res.time_window_start else None,
                "time_window_end": res.time_window_end.isoformat() if res.time_window_end else None,
                "explanation": res.explanation,
                "is_simulated": is_simulated,
            }
            outbox_repo.stage_event(
                event_type="telemetry_event",
                aggregate_id=persisted_assessment.assessment_id,
                payload_json=json.dumps(outbox_payload),
            )

            # Trigger clinical alert if anomalous
            if trigger_alert and db_result == "anomaly":
                # Deterministic alert ID linked to assessment
                alert_id = f"alt_ml_{persisted_assessment.assessment_id[-20:]}"
                score_val = float(persisted_assessment.score)
                severity = "CRITICAL" if score_val >= 0.70 else "HIGH"

                explanation_text = "; ".join(res.explanation[:2]) if res.explanation else "Multivariate anomaly pattern detected."
                reason = f"[{severity}] ML Anomaly Detected (Score: {score_val:.2f}). {explanation_text}"

                candidate_alert = Alert(
                    alert_id=alert_id,
                    patient_id=persisted_assessment.patient_id,
                    event_id=source_event_id,
                    assessment_id=persisted_assessment.assessment_id,
                    rule_id=None,
                    severity=severity,
                    category="ml_anomaly",
                    reason=reason,
                    status="NEW",
                )

                persisted_alert, newly_created_alert = alert_repo.create_or_get_alert(candidate_alert)

                if newly_created_alert:
                    history = AlertStatusHistory(
                        alert_id=persisted_alert.alert_id,
                        old_status=None,
                        new_status="NEW",
                        actor_id=None,
                        note="Triggered by Isolation Forest multivariate anomaly assessment.",
                    )
                    db.add(history)

                    audit_metadata = {
                        "patient_id": persisted_assessment.patient_id,
                        "assessment_id": persisted_assessment.assessment_id,
                        "score": score_val,
                        "severity": severity,
                        "event_id": source_event_id,
                    }
                    audit_repo.record(
                        action="ALERT_TRIGGERED",
                        target_type="alert",
                        target_id=persisted_alert.alert_id,
                        actor_id=None,
                        metadata_json=json.dumps(audit_metadata),
                    )

                    alert_outbox_payload = {
                        "alert_id": persisted_alert.alert_id,
                        "patient_id": persisted_alert.patient_id,
                        "assessment_id": persisted_assessment.assessment_id,
                        "severity": persisted_alert.severity,
                        "category": persisted_alert.category,
                        "reason": persisted_alert.reason,
                        "status": persisted_alert.status,
                        "created_at": persisted_alert.created_at.isoformat() if persisted_alert.created_at else None,
                    }
                    outbox_repo.stage_event(
                        event_type="alert_event",
                        aggregate_id=persisted_alert.alert_id,
                        payload_json=json.dumps(alert_outbox_payload),
                    )

        # Notify strictly AFTER transaction commit
        if persisted_alert and newly_created_alert:
            try:
                notify_alert_created(persisted_alert)
            except Exception as exc:
                logger.warning("Failed to emit WebSocket alert.created for ML alert %s: %s", persisted_alert.alert_id, exc)

        return persisted_assessment, persisted_alert, res


# Module-level singleton
_GLOBAL_ML_SERVICE: Optional[MLService] = None
_SERVICE_INIT_LOCK = threading.Lock()


def get_ml_service(settings: Optional[Settings] = None) -> MLService:
    """Retrieve or initialize the global MLService singleton."""
    global _GLOBAL_ML_SERVICE
    if _GLOBAL_ML_SERVICE is None:
        with _SERVICE_INIT_LOCK:
            if _GLOBAL_ML_SERVICE is None:
                _GLOBAL_ML_SERVICE = MLService(settings=settings)
    return _GLOBAL_ML_SERVICE


def reset_ml_service() -> None:
    """Reset the global MLService instance (useful for test isolation)."""
    global _GLOBAL_ML_SERVICE
    with _SERVICE_INIT_LOCK:
        _GLOBAL_ML_SERVICE = None
