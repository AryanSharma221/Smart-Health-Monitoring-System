"""
Patient and Clinician Domain Service.

Coordinates patient profiles, doctor assignments, and access validation.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityNotFoundError
from database.mysql.models import PatientProfile
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.session import transaction_scope

logger = logging.getLogger(__name__)


class PatientService:
    """Application service for patient management and authorization lookups."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = PatientRepository(session)

    def get_patient(self, patient_id: str) -> PatientProfile:
        """Fetch patient profile or raise EntityNotFoundError."""
        patient = self.repo.get_by_id(patient_id)
        if not patient:
            raise EntityNotFoundError("PatientProfile", patient_id)
        return patient

    def list_patients(self, skip: int = 0, limit: int = 50) -> List[PatientProfile]:
        """Retrieve paginated list of patients."""
        return self.repo.list_patients(skip=skip, limit=limit)

    def get_doctor_assigned_patients(
        self,
        doctor_id: str,
        active_only: bool = True,
    ) -> List[PatientProfile]:
        """Fetch all patients assigned to a clinician."""
        doctor = self.repo.get_doctor_by_id(doctor_id)
        if not doctor:
            raise EntityNotFoundError("DoctorProfile", doctor_id)
        return self.repo.get_assigned_patients_for_doctor(doctor_id, active_only=active_only)

    def verify_clinician_access(self, doctor_id: str, patient_id: str) -> bool:
        """Check if clinician is authorized to view or manage patient data."""
        return self.repo.is_doctor_assigned_to_patient(doctor_id, patient_id)
