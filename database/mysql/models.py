"""
SQLAlchemy 2.0 ORM Models for Smart Health Monitoring System.

Defines the normalized relational schema (15 tables) under MySQL 8 InnoDB:
1.  import_batches: Ingestion batch manifests and dataset provenance.
2.  users: Core authentication identities and roles.
3.  patient_profiles: Patient demographic and baseline clinical records.
4.  doctor_profiles: Clinician profiles and medical license registrations.
5.  doctor_patient_assignments: Clinical care relationships and authorizations.
6.  ingestion_events: Event-level provenance (Kaggle historical vs. simulator).
7.  vitals_readings: Normalized metric-per-row canonical health measurements.
8.  alert_rules: Deterministic clinical threshold rules.
9.  patient_baselines: Rolling statistical baselines for anomaly evaluation.
10. model_assessments: Machine-learning inference evaluation records.
11. alerts: Authoritative alert records and lifecycle status.
12. alert_status_history: Audit log for alert lifecycle state transitions.
13. notification_deliveries: Multi-channel dispatch tracking for clinical alerts.
14. messages: Doctor-patient direct communication in assigned contexts.
15. audit_logs: System-wide security and clinical compliance audit trail.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base declarative class for all relational models."""
    pass


# =============================================================================
# 1. Dataset Import Provenance
# =============================================================================

class ImportBatch(Base):
    """Tracks batch dataset imports (e.g. historical Kaggle 1,500-row dataset)."""

    __tablename__ = "import_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    events: Mapped[List[IngestionEvent]] = relationship(
        "IngestionEvent",
        back_populates="batch",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_import_batches_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<ImportBatch batch_id='{self.batch_id}' source='{self.source_name}' status='{self.status}'>"


# =============================================================================
# 2. Identity and Access Control
# =============================================================================

class User(Base):
    """Central identity model for authentication and role-based access control."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    patient_profile: Mapped[Optional[PatientProfile]] = relationship(
        "PatientProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    doctor_profile: Mapped[Optional[DoctorProfile]] = relationship(
        "DoctorProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('patient', 'doctor', 'admin_operator')",
            name="ck_users_role",
        ),
    )

    def __repr__(self) -> str:
        return f"<User user_id='{self.user_id}' email='{self.email}' role='{self.role}' active={self.is_active}>"


class PatientProfile(Base):
    """Patient demographic and baseline clinical profile."""

    __tablename__ = "patient_profiles"

    patient_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    gender: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    height_cm: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    emergency_contact: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="patient_profile")
    doctor_assignments: Mapped[List[DoctorPatientAssignment]] = relationship(
        "DoctorPatientAssignment",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    ingestion_events: Mapped[List[IngestionEvent]] = relationship(
        "IngestionEvent",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    vitals_readings: Mapped[List[VitalsReading]] = relationship(
        "VitalsReading",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    alerts: Mapped[List[Alert]] = relationship(
        "Alert",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    baselines: Mapped[List[PatientBaseline]] = relationship(
        "PatientBaseline",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "gender IS NULL OR gender IN ('male', 'female', 'other', 'unknown')",
            name="ck_patient_gender",
        ),
        CheckConstraint(
            "height_cm IS NULL OR height_cm > 0",
            name="ck_patient_height_positive",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg > 0",
            name="ck_patient_weight_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<PatientProfile patient_id='{self.patient_id}' user_id='{self.user_id}'>"


class DoctorProfile(Base):
    """Clinical professional profile and medical license registry."""

    __tablename__ = "doctor_profiles"

    doctor_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(64), nullable=False)
    last_name: Mapped[str] = mapped_column(String(64), nullable=False)
    specialization: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="General Practice",
    )
    license_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="doctor_profile")
    patient_assignments: Mapped[List[DoctorPatientAssignment]] = relationship(
        "DoctorPatientAssignment",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<DoctorProfile doctor_id='{self.doctor_id}' license='{self.license_number}'>"


class DoctorPatientAssignment(Base):
    """Many-to-many relationship defining patient assignment to clinical staff."""

    __tablename__ = "doctor_patient_assignments"

    doctor_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("doctor_profiles.doctor_id", ondelete="CASCADE"),
        primary_key=True,
    )
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    doctor: Mapped[DoctorProfile] = relationship(
        "DoctorProfile",
        back_populates="patient_assignments",
    )
    patient: Mapped[PatientProfile] = relationship(
        "PatientProfile",
        back_populates="doctor_assignments",
    )

    __table_args__ = (
        Index("idx_assignments_patient", "patient_id"),
        Index("idx_assignments_doctor_active", "doctor_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<DoctorPatientAssignment doctor='{self.doctor_id}' patient='{self.patient_id}' active={self.is_active}>"


# =============================================================================
# 3. Canonical Health Readings & Ingestion Events
# =============================================================================

class IngestionEvent(Base):
    """
    Discrete provenance record for each incoming telemetry packet.
    Differentiates Kaggle historical records (is_simulated=False) from simulator events (is_simulated=True).
    Guarantees idempotency via unique constraint on (source, source_event_id).
    """

    __tablename__ = "ingestion_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("import_batches.batch_id", ondelete="SET NULL"),
        nullable=True,
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mirror_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    patient: Mapped[PatientProfile] = relationship(
        "PatientProfile",
        back_populates="ingestion_events",
    )
    batch: Mapped[Optional[ImportBatch]] = relationship(
        "ImportBatch",
        back_populates="events",
    )
    readings: Mapped[List[VitalsReading]] = relationship(
        "VitalsReading",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_event_id",
            name="uq_events_source_source_event_id",
        ),
        Index("idx_events_patient_measured", "patient_id", "measured_at"),
        Index("idx_events_mirror_status", "mirror_status"),
        CheckConstraint(
            "mirror_status IN ('pending', 'mirrored', 'failed')",
            name="ck_events_mirror_status",
        ),
    )

    def __repr__(self) -> str:
        return f"<IngestionEvent event_id='{self.event_id}' patient='{self.patient_id}' source='{self.source}'>"


class VitalsReading(Base):
    """
    Normalized metric-per-row measurement entity.
    Stores canonical decimal value & unit as well as raw source value & unit
    (e.g., Fahrenheit stored raw, Celsius stored canonical).
    """

    __tablename__ = "vitals_readings"

    reading_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("ingestion_events.event_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_code: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    raw_unit: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="valid",
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    event: Mapped[IngestionEvent] = relationship(
        "IngestionEvent",
        back_populates="readings",
    )
    patient: Mapped[PatientProfile] = relationship(
        "PatientProfile",
        back_populates="vitals_readings",
    )

    __table_args__ = (
        UniqueConstraint("event_id", "metric_code", name="uq_vitals_event_metric"),
        Index("idx_vitals_patient_metric_time", "patient_id", "metric_code", "measured_at"),
        Index("idx_vitals_measured_at", "measured_at"),
        CheckConstraint(
            "metric_code IN ('heart_rate', 'spo2', 'temperature', 'respiratory_rate', 'bp_systolic', 'bp_diastolic')",
            name="ck_vitals_metric_code",
        ),
        CheckConstraint(
            "quality_status IN ('valid', 'out_of_range', 'stale', 'suspect')",
            name="ck_vitals_quality_status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<VitalsReading id={self.reading_id} patient='{self.patient_id}' "
            f"metric='{self.metric_code}' value={self.value} {self.unit}>"
        )


# =============================================================================
# 4. Clinical Threshold Rules & Baselines
# =============================================================================

class AlertRule(Base):
    """Deterministic clinical rule configuration for threshold-based anomaly detection."""

    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(32), nullable=False)
    operator: Mapped[str] = mapped_column(String(8), nullable=False)
    configured_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_demo_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "operator IN ('<', '>', '<=', '>=', '==', '!=')",
            name="ck_alert_rules_operator",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_alert_rules_severity",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertRule rule_id='{self.rule_id}' metric='{self.metric_code}' "
            f"op='{self.operator}' val={self.configured_value} sev='{self.severity}'>"
        )


class PatientBaseline(Base):
    """Rolling statistical baseline (median, MAD) per patient and vital metric."""

    __tablename__ = "patient_baselines"

    baseline_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_code: Mapped[str] = mapped_column(String(32), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    median_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    mad_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    patient: Mapped[PatientProfile] = relationship(
        "PatientProfile",
        back_populates="baselines",
    )

    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "metric_code",
            "window_hours",
            name="uq_patient_metric_window",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PatientBaseline patient='{self.patient_id}' metric='{self.metric_code}' "
            f"med={self.median_value} mad={self.mad_value}>"
        )


# =============================================================================
# 5. Machine Learning Assessments & Alerts
# =============================================================================

class ModelAssessment(Base):
    """Machine learning anomaly evaluation records (e.g. Isolation Forest)."""

    __tablename__ = "model_assessments"

    assessment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("ingestion_events.event_id", ondelete="SET NULL"),
        nullable=True,
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    features_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time_window_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    time_window_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    alerts: Mapped[List[Alert]] = relationship(
        "Alert",
        back_populates="assessment",
    )

    __table_args__ = (
        CheckConstraint(
            "result IN ('normal', 'anomaly', 'inconclusive')",
            name="ck_assessments_result",
        ),
        Index("idx_assessments_patient_time", "patient_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ModelAssessment id='{self.assessment_id}' patient='{self.patient_id}' "
            f"model='{self.model_version}' res='{self.result}' score={self.score}>"
        )


class Alert(Base):
    """Authoritative clinical alert records and lifecycle status."""

    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("ingestion_events.event_id", ondelete="SET NULL"),
        nullable=True,
    )
    assessment_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("model_assessments.assessment_id", ondelete="SET NULL"),
        nullable=True,
    )
    rule_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("alert_rules.rule_id", ondelete="SET NULL"),
        nullable=True,
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="NEW",
    )
    acknowledged_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolved_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    patient: Mapped[PatientProfile] = relationship("PatientProfile", back_populates="alerts")
    assessment: Mapped[Optional[ModelAssessment]] = relationship("ModelAssessment", back_populates="alerts")
    acknowledged_by_user: Mapped[Optional[User]] = relationship("User", foreign_keys=[acknowledged_by])
    resolved_by_user: Mapped[Optional[User]] = relationship("User", foreign_keys=[resolved_by])
    status_history: Mapped[List[AlertStatusHistory]] = relationship(
        "AlertStatusHistory",
        back_populates="alert",
        cascade="all, delete-orphan",
    )
    deliveries: Mapped[List[NotificationDelivery]] = relationship(
        "NotificationDelivery",
        back_populates="alert",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="ck_alerts_severity",
        ),
        CheckConstraint(
            "category IN ('vital_threshold', 'ml_anomaly', 'composite', 'stale_data')",
            name="ck_alerts_category",
        ),
        CheckConstraint(
            "status IN ('NEW', 'ACKNOWLEDGED', 'RESOLVED')",
            name="ck_alerts_status",
        ),
        UniqueConstraint("event_id", "rule_id", name="uq_alerts_event_rule"),
        Index("idx_alerts_patient_status_time", "patient_id", "status", "created_at"),
        Index("idx_alerts_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert alert_id='{self.alert_id}' patient='{self.patient_id}' "
            f"sev='{self.severity}' status='{self.status}'>"
        )


class AlertStatusHistory(Base):
    """Immutable audit trail for alert lifecycle state transitions."""

    __tablename__ = "alert_status_history"

    history_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    alert_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("alerts.alert_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    alert: Mapped[Alert] = relationship("Alert", back_populates="status_history")
    actor: Mapped[Optional[User]] = relationship("User")

    __table_args__ = (
        Index("idx_alert_history_alert_time", "alert_id", "changed_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertStatusHistory alert='{self.alert_id}' transition="
            f"'{self.old_status}->{self.new_status}' at={self.changed_at}>"
        )


class NotificationDelivery(Base):
    """Notification dispatch tracking for alerts sent to patients or clinicians."""

    __tablename__ = "notification_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alert_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("alerts.alert_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    alert: Mapped[Alert] = relationship("Alert", back_populates="deliveries")
    recipient: Mapped[User] = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "channel IN ('in_app', 'websocket', 'email', 'sms')",
            name="ck_deliveries_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed')",
            name="ck_deliveries_status",
        ),
        Index("idx_deliveries_recipient_status", "recipient_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<NotificationDelivery id='{self.delivery_id}' alert='{self.alert_id}' status='{self.status}'>"


# =============================================================================
# 6. Direct Messaging & System Audit Trail
# =============================================================================

class Conversation(Base):
    """Secure direct messaging channel between an authorized patient and clinician."""

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("doctor_profiles.doctor_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    patient: Mapped[PatientProfile] = relationship("PatientProfile")
    doctor: Mapped[DoctorProfile] = relationship("DoctorProfile")
    messages: Mapped[List[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )

    __table_args__ = (
        UniqueConstraint("patient_id", "doctor_id", name="uq_conversations_patient_doctor"),
        Index("idx_conversations_updated", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Conversation id='{self.conversation_id}' patient='{self.patient_id}' doctor='{self.doctor_id}'>"


class Message(Base):
    """Direct communication between clinicians and patients within assigned care contexts."""

    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sender_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receiver_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    patient_context_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("patient_profiles.patient_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    conversation: Mapped[Optional[Conversation]] = relationship("Conversation", back_populates="messages")
    sender: Mapped[User] = relationship("User", foreign_keys=[sender_id])
    receiver: Mapped[User] = relationship("User", foreign_keys=[receiver_id])
    patient_context: Mapped[Optional[PatientProfile]] = relationship("PatientProfile")

    __table_args__ = (
        Index("idx_messages_receiver_read_time", "receiver_id", "is_read", "created_at"),
        Index("idx_messages_sender_time", "sender_id", "created_at"),
        Index("idx_messages_conversation_time", "conversation_id", "created_at"),
        Index("idx_messages_conversation_unread", "conversation_id", "is_read", "receiver_id"),
        Index("uq_messages_sender_idempotency", "sender_id", "idempotency_key", unique=True),
    )

    def __repr__(self) -> str:
        return f"<Message id='{self.message_id}' conv='{self.conversation_id}' sender='{self.sender_id}' receiver='{self.receiver_id}' read={self.is_read}>"


class AuditLog(Base):
    """Immutable audit trail for security events and sensitive clinical data access."""

    __tablename__ = "audit_logs"

    audit_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    actor: Mapped[Optional[User]] = relationship("User")

    __table_args__ = (
        Index("idx_audit_actor_time", "actor_id", "timestamp"),
        Index("idx_audit_target", "target_type", "target_id"),
        Index("idx_audit_timestamp", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.audit_id} actor='{self.actor_id}' action='{self.action}' target='{self.target_type}/{self.target_id}'>"


# =============================================================================
# 7. Asynchronous Analytics Mirror & Transactional Outbox
# =============================================================================

class AnalyticsOutbox(Base):
    """
    Transactional outbox table for reliable, asynchronous mirroring to MongoDB Atlas.
    Committed in the same MySQL transaction as the business event.
    """

    __tablename__ = "analytics_outbox"

    outbox_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
        Index("idx_outbox_aggregate", "event_type", "aggregate_id"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_outbox_status",
        ),
        CheckConstraint(
            "event_type IN ('telemetry_event', 'alert_event')",
            name="ck_outbox_event_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<AnalyticsOutbox id={self.outbox_id} type='{self.event_type}' agg='{self.aggregate_id}' status='{self.status}'>"

