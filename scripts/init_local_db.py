"""
Local Relational Database Initializer and Seeder.
Creates and seeds smart_health_local.db for offline and local demonstration mode.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from database.mysql.models import (
    Alert,
    AlertRule,
    Base,
    Conversation,
    DoctorPatientAssignment,
    DoctorProfile,
    Message,
    PatientProfile,
    User,
)
from services.alerts.rules import DEFAULT_ALERT_RULES
from services.auth.security import hash_password
from services.ingestion.importer import KaggleDatasetImporter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_local_db")

DB_FILE = ROOT_DIR / "smart_health_local.db"
DB_URL = f"sqlite:///{DB_FILE}"
CSV_PATH = ROOT_DIR / "data" / "raw" / "kaggle_health_dataset.csv"


def init_database():
    logger.info("Initializing SQLite database at: %s", DB_FILE)

    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    # 1. Views and Triggers
    with engine.begin() as conn:
        logger.info("Creating SQLite views and triggers...")
        conn.execute(text("""
            CREATE VIEW IF NOT EXISTS v_latest_patient_vitals AS
            WITH ranked_vitals AS (
                SELECT reading_id, event_id, patient_id, metric_code, value, unit, raw_value, raw_unit, quality_status, measured_at,
                       ROW_NUMBER() OVER (PARTITION BY patient_id, metric_code ORDER BY measured_at DESC) AS rn
                FROM vitals_readings
            )
            SELECT reading_id, event_id, patient_id, metric_code, value, unit, raw_value, raw_unit, quality_status, measured_at
            FROM ranked_vitals
            WHERE rn = 1;
        """))

        conn.execute(text("""
            CREATE VIEW IF NOT EXISTS v_patient_active_alerts AS
            SELECT a.alert_id, a.patient_id, p.first_name, p.last_name,
                   a.severity, a.status, a.category, a.reason, a.created_at
            FROM alerts a
            INNER JOIN patient_profiles p ON a.patient_id = p.patient_id
            WHERE a.status IN ('NEW', 'ACTIVE');
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS trg_alert_status_history_after_update
            AFTER UPDATE OF status ON alerts
            FOR EACH ROW
            WHEN OLD.status <> NEW.status
            BEGIN
                INSERT INTO alert_status_history (alert_id, old_status, new_status, actor_id, note, changed_at)
                VALUES (OLD.alert_id, OLD.status, NEW.status, COALESCE(NEW.acknowledged_by, NEW.resolved_by), 'Trigger recorded transition', CURRENT_TIMESTAMP);
            END;
        """))

    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session: Session = SessionFactory()

    try:
        # 2. Ingest Kaggle historical dataset (seeds P101–P105 and 1,500 historical readings)
        if CSV_PATH.exists():
            logger.info("Ingesting historical Kaggle dataset from: %s", CSV_PATH)
            importer = KaggleDatasetImporter(
                session=session,
                batch_size=250,
                auto_seed_patients=True,
                source_timezone="UTC",
            )
            report = importer.run_import(csv_path=CSV_PATH, dry_run=False)
            logger.info("Dataset import completed: %d events, %d readings", report.events_inserted, report.readings_inserted)
        else:
            logger.warning("Dataset CSV not found at %s; skipping ingestion.", CSV_PATH)

        # 3. Seed Alert Rules
        logger.info("Seeding default alert rules...")
        for r in DEFAULT_ALERT_RULES:
            if not session.get(AlertRule, r.rule_id):
                session.add(AlertRule(
                    rule_id=r.rule_id,
                    metric_code=r.metric_code,
                    operator=r.operator,
                    configured_value=r.configured_value,
                    duration_seconds=getattr(r, "duration_seconds", 0),
                    severity=r.severity,
                    is_enabled=r.is_enabled,
                    is_demo_only=r.is_demo_only,
                    description=r.description,
                ))

        # 4. Seed Clinician Account (Dr. Sarah Jenkins)
        logger.info("Provisioning clinician account doctor@hospital.org...")
        doc_user = session.query(User).filter_by(email="doctor@hospital.org").first()
        if not doc_user:
            doc_user = User(
                user_id="U_DOC_SARAH",
                email="doctor@hospital.org",
                password_hash=hash_password("DoctorPassword123!"),
                role="doctor",
                is_active=True,
            )
            session.add(doc_user)
            session.flush()

        doc_profile = session.query(DoctorProfile).filter_by(user_id=doc_user.user_id).first()
        if not doc_profile:
            doc_profile = DoctorProfile(
                doctor_id="DOC_JENKINS",
                user_id=doc_user.user_id,
                first_name="Sarah",
                last_name="Jenkins",
                specialization="Cardiology & Critical Care",
                license_number="LIC-MD-98765",
                contact_phone="+1-555-0199",
            )
            session.add(doc_profile)
            session.flush()

        # 5. Seed Baseline Patients P001-P005 (for RBAC and protection demos)
        logger.info("Provisioning unassigned baseline patients P001-P005...")
        for i in range(1, 6):
            pid = f"P{i:03d}"
            existing_p = session.get(PatientProfile, pid)
            if not existing_p:
                u_id = f"usr_patient_{pid.lower()}"
                u = session.get(User, u_id)
                if not u:
                    u = User(
                        user_id=u_id,
                        email=f"{pid.lower()}@hospital.org",
                        password_hash=hash_password("PatientPassword123!"),
                        role="patient",
                        is_active=True,
                    )
                    session.add(u)
                    session.flush()

                p = PatientProfile(
                    patient_id=pid,
                    user_id=u.user_id,
                    first_name="Baseline",
                    last_name=f"Patient {pid}",
                    date_of_birth=date(1985, 3, 15),
                    gender="female" if i % 2 == 0 else "male",
                    height_cm=Decimal("170.0"),
                    weight_kg=Decimal("68.5"),
                )
                session.add(p)

        # 6. Assign P101–P105 to Dr. Jenkins
        logger.info("Assigning demonstration cohort P101-P105 to Dr. Jenkins...")
        for pid in ["P101", "P102", "P103", "P104", "P105"]:
            assignment = session.query(DoctorPatientAssignment).filter_by(
                doctor_id=doc_profile.doctor_id,
                patient_id=pid,
            ).first()
            if not assignment:
                session.add(DoctorPatientAssignment(
                    doctor_id=doc_profile.doctor_id,
                    patient_id=pid,
                    is_active=True,
                    notes=f"Primary clinical monitoring assigned to Dr. Sarah Jenkins for {pid}",
                ))

            # Create conversation channel
            conv = session.query(Conversation).filter_by(
                doctor_id=doc_profile.doctor_id,
                patient_id=pid,
            ).first()
            if not conv:
                conv_id = f"CONV_{doc_profile.doctor_id}_{pid}"
                conv = Conversation(
                    conversation_id=conv_id,
                    doctor_id=doc_profile.doctor_id,
                    patient_id=pid,
                    is_active=True,
                )
                session.add(conv)
                session.flush()

                # Sample message
                msg = Message(
                    message_id=f"MSG_INIT_{pid}",
                    conversation_id=conv_id,
                    sender_id=doc_user.user_id,
                    receiver_id=f"usr_kaggle_{pid.lower()}",
                    patient_context_id=pid,
                    content="Welcome to the Smart Health Monitoring care portal. Your vitals are being tracked in real time.",
                    is_read=True,
                )
                session.add(msg)

        # 7. Seed sample initial alert for P101
        existing_alert = session.query(Alert).filter_by(patient_id="P101").first()
        if not existing_alert:
            logger.info("Seeding initial baseline alert for P101...")
            session.add(Alert(
                alert_id="ALT_BASELINE_P101",
                patient_id="P101",
                severity="HIGH",
                status="NEW",
                category="vital_threshold",
                reason="Heart rate tachycardia observation (112 bpm > 100 bpm)",
                created_at=datetime.now(timezone.utc),
            ))

        session.commit()
        logger.info("Database initialization and seeding successfully completed!")
    finally:
        session.close()


if __name__ == "__main__":
    init_database()
