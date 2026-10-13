"""
User Authentication and Identity Repository.

Provides explicit, encapsulated data access methods for users, credentials,
and linked patient/clinician profiles under MySQL 8 InnoDB.
"""

from __future__ import annotations

from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.mysql.models import DoctorProfile, PatientProfile, User


class UserRepository:
    """Encapsulates relational persistence queries for user identities and authentication."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Fetch user by user_id with eager loaded profiles."""
        stmt = (
            select(User)
            .options(
                joinedload(User.patient_profile),
                joinedload(User.doctor_profile),
            )
            .where(User.user_id == user_id)
        )
        return self.session.scalar(stmt)

    def get_by_email(self, email: str) -> Optional[User]:
        """Fetch user by normalized email with eager loaded profiles."""
        stmt = (
            select(User)
            .options(
                joinedload(User.patient_profile),
                joinedload(User.doctor_profile),
            )
            .where(User.email == email.strip().lower())
        )
        return self.session.scalar(stmt)

    def create_user(self, user: User) -> User:
        """Stage a new user record."""
        self.session.add(user)
        self.session.flush()
        return user

    def create_patient_user(
        self,
        user: User,
        profile: PatientProfile,
    ) -> tuple[User, PatientProfile]:
        """Atomically stage a User and associated PatientProfile."""
        self.session.add(user)
        self.session.flush()
        profile.user_id = user.user_id
        self.session.add(profile)
        self.session.flush()
        return user, profile

    def create_doctor_user(
        self,
        user: User,
        profile: DoctorProfile,
    ) -> tuple[User, DoctorProfile]:
        """Atomically stage a User and associated DoctorProfile."""
        self.session.add(user)
        self.session.flush()
        profile.user_id = user.user_id
        self.session.add(profile)
        self.session.flush()
        return user, profile

    def update_active_status(self, user_id: str, is_active: bool) -> Optional[User]:
        """Update active status of a user."""
        user = self.get_by_id(user_id)
        if user:
            user.is_active = is_active
            self.session.flush()
        return user
