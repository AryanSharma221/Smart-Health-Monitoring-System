"""
Patient and Clinician Profile Repository.

Provides explicit, encapsulated data access methods for users, patient profiles,
doctor profiles, and care assignments.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.mysql.models import (
    DoctorPatientAssignment,
    DoctorProfile,
    PatientProfile,
    User,
)


class PatientRepository:
    """Encapsulates relational persistence queries for patient and clinician domains."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, patient_id: str) -> Optional[PatientProfile]:
        """Fetch patient profile by domain patient_id."""
        return self.session.get(PatientProfile, patient_id)

    def get_by_user_id(self, user_id: str) -> Optional[PatientProfile]:
        """Fetch patient profile associated with a specific user identity."""
        stmt = select(PatientProfile).where(PatientProfile.user_id == user_id)
        return self.session.scalar(stmt)

    def list_patients(self, skip: int = 0, limit: int = 50) -> List[PatientProfile]:
        """List patient profiles with pagination."""
        stmt = select(PatientProfile).offset(skip).limit(limit)
        return list(self.session.scalars(stmt).all())

    def get_doctor_by_id(self, doctor_id: str) -> Optional[DoctorProfile]:
        """Fetch clinician profile by doctor_id."""
        return self.session.get(DoctorProfile, doctor_id)

    def get_doctor_by_user_id(self, user_id: str) -> Optional[DoctorProfile]:
        """Fetch clinician profile associated with a specific user identity."""
        stmt = select(DoctorProfile).where(DoctorProfile.user_id == user_id)
        return self.session.scalar(stmt)

    def get_assigned_patients_for_doctor(
        self,
        doctor_id: str,
        active_only: bool = True,
    ) -> List[PatientProfile]:
        """Retrieve all patients assigned to a specific clinician."""
        stmt = (
            select(PatientProfile)
            .join(DoctorPatientAssignment, PatientProfile.patient_id == DoctorPatientAssignment.patient_id)
            .where(DoctorPatientAssignment.doctor_id == doctor_id)
        )
        if active_only:
            stmt = stmt.where(DoctorPatientAssignment.is_active == True)
        return list(self.session.scalars(stmt).all())

    def is_doctor_assigned_to_patient(self, doctor_id: str, patient_id: str) -> bool:
        """Check whether an active care assignment exists between doctor and patient."""
        stmt = select(DoctorPatientAssignment.patient_id).where(
            DoctorPatientAssignment.doctor_id == doctor_id,
            DoctorPatientAssignment.patient_id == patient_id,
            DoctorPatientAssignment.is_active == True,
        )
        return self.session.scalar(stmt) is not None

    def get_existing_patient_ids(self, patient_ids: Sequence[str]) -> Set[str]:
        """Filter input patient IDs and return those present in the database."""
        stmt = select(PatientProfile.patient_id).where(PatientProfile.patient_id.in_(list(patient_ids)))
        return set(self.session.scalars(stmt).all())

    def create_patient_with_user(
        self,
        user: User,
        profile: PatientProfile,
    ) -> PatientProfile:
        """Atomically stage a User and associated PatientProfile."""
        self.session.add(user)
        self.session.flush()
        profile.user_id = user.user_id
        self.session.add(profile)
        self.session.flush()
        return profile
