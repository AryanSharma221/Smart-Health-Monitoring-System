"""
Machine Learning Model Assessment Repository.

Encapsulates relational persistence queries for Isolation Forest anomaly detection evaluations,
ensuring idempotent inserts and paginated historical queries.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.mysql.models import ModelAssessment

logger = logging.getLogger(__name__)


class AssessmentRepository:
    """Encapsulates persistence operations for model_assessments records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, assessment: ModelAssessment) -> ModelAssessment:
        """Stage a new model assessment."""
        self.session.add(assessment)
        self.session.flush()
        return assessment

    def get_by_id(self, assessment_id: str) -> Optional[ModelAssessment]:
        """Fetch model assessment by assessment_id."""
        return self.session.get(ModelAssessment, assessment_id)

    def get_by_event_id(self, event_id: str) -> Optional[ModelAssessment]:
        """Fetch model assessment by triggering event_id."""
        stmt = select(ModelAssessment).where(ModelAssessment.event_id == event_id)
        return self.session.scalars(stmt).first()

    def create_or_get_assessment(self, assessment: ModelAssessment) -> tuple[ModelAssessment, bool]:
        """
        Atomically persist an assessment or return existing if duplicate.
        Returns (assessment, was_created).
        Guarantees idempotency via database unique constraint / primary key.
        """
        if assessment.event_id:
            existing_event = self.get_by_event_id(assessment.event_id)
            if existing_event:
                return existing_event, False

        existing = self.get_by_id(assessment.assessment_id)
        if existing:
            return existing, False

        try:
            with self.session.begin_nested():
                self.session.add(assessment)
                self.session.flush()
            return assessment, True
        except IntegrityError:
            if assessment.event_id:
                existing_event = self.get_by_event_id(assessment.event_id)
                if existing_event:
                    return existing_event, False
            existing = self.get_by_id(assessment.assessment_id)
            if existing:
                return existing, False
            raise

    def list_by_patient_paginated(
        self,
        patient_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[ModelAssessment], int]:
        """
        Query paginated assessments for a patient.
        Ordered by created_at descending with tie-breaker assessment_id.
        """
        filters = [ModelAssessment.patient_id == patient_id]

        count_stmt = select(func.count(ModelAssessment.assessment_id)).where(*filters)
        total_count = self.session.scalar(count_stmt) or 0

        offset = (page - 1) * page_size
        stmt = (
            select(ModelAssessment)
            .where(*filters)
            .order_by(desc(ModelAssessment.created_at), desc(ModelAssessment.assessment_id))
            .offset(offset)
            .limit(page_size)
        )
        items = list(self.session.scalars(stmt).all())
        return items, total_count

    def list_latest_by_patient(
        self,
        patient_id: str,
        limit: int = 10,
    ) -> List[ModelAssessment]:
        """Fetch newest assessments for a patient."""
        stmt = (
            select(ModelAssessment)
            .where(ModelAssessment.patient_id == patient_id)
            .order_by(desc(ModelAssessment.created_at), desc(ModelAssessment.assessment_id))
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())
