"""
Pydantic Schemas for Authentication, Registration, and User Profiles.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserRegisterRequest(BaseModel):
    """Payload for public user self-registration."""

    email: str = Field(..., description="Unique email address for user account")
    password: str = Field(..., min_length=8, max_length=72, description="Plaintext password")
    first_name: str = Field(..., min_length=1, max_length=64, description="User's first name")
    last_name: str = Field(..., min_length=1, max_length=64, description="User's last name")
    role: str = Field(default="patient", description="Requested role (public registration allows only 'patient')")

    # Optional patient demographic fields
    date_of_birth: Optional[date] = Field(default=None, description="Patient birth date")
    gender: Optional[str] = Field(default=None, description="Gender (male, female, other, unknown)")
    height_cm: Optional[float] = Field(default=None, ge=1.0, le=300.0, description="Height in centimeters")
    weight_kg: Optional[float] = Field(default=None, ge=1.0, le=500.0, description="Weight in kilograms")
    contact_phone: Optional[str] = Field(default=None, max_length=32, description="Contact telephone")
    emergency_contact: Optional[str] = Field(default=None, max_length=64, description="Emergency contact info")

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean):
            raise ValueError("Invalid email address format.")
        return clean

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip().lower()
        if clean not in ("male", "female", "other", "unknown"):
            raise ValueError("Gender must be one of: 'male', 'female', 'other', 'unknown'")
        return clean


class UserLoginRequest(BaseModel):
    """Payload for authentication and token request."""

    email: str = Field(..., description="Registered user email")
    password: str = Field(..., description="User account password")

    @field_validator("email")
    @classmethod
    def clean_email(cls, v: str) -> str:
        return v.strip().lower()


class TokenResponse(BaseModel):
    """Authentication token response schema."""

    access_token: str = Field(..., description="Signed JWT Bearer access token")
    token_type: str = Field(default="bearer", description="Token type identifier")
    expires_in: int = Field(..., description="Token validity duration in seconds")
    user_id: str = Field(..., description="Stable user identity identifier")
    role: str = Field(..., description="Effective server-resolved user role")


class PatientProfileResponse(BaseModel):
    """Public safe patient demographic profile representation."""

    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    first_name: str
    last_name: str
    name: Optional[str] = None
    source_patient_id: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    contact_phone: Optional[str] = None
    emergency_contact: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def populate_patient_display_fields(cls, data: Any) -> Any:
        if hasattr(data, "first_name") and hasattr(data, "last_name"):
            fn = getattr(data, "first_name", "") or ""
            ln = getattr(data, "last_name", "") or ""
            full = f"{fn} {ln}".strip() or getattr(data, "patient_id", "")
            data_dict = {
                "patient_id": data.patient_id,
                "first_name": fn,
                "last_name": ln,
                "name": full,
                "source_patient_id": data.patient_id,
                "date_of_birth": getattr(data, "date_of_birth", None),
                "gender": getattr(data, "gender", None),
                "height_cm": getattr(data, "height_cm", None),
                "weight_kg": getattr(data, "weight_kg", None),
                "contact_phone": getattr(data, "contact_phone", None),
                "emergency_contact": getattr(data, "emergency_contact", None),
            }
            return data_dict
        return data


class DoctorProfileResponse(BaseModel):
    """Public safe clinician profile representation."""

    model_config = ConfigDict(from_attributes=True)

    doctor_id: str
    first_name: str
    last_name: str
    specialization: str
    license_number: str
    contact_phone: Optional[str] = None


class UserProfileResponse(BaseModel):
    """Safe authenticated user identity response omitting hashes and secrets."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    patient_profile: Optional[PatientProfileResponse] = None
    doctor_profile: Optional[DoctorProfileResponse] = None
    name: Optional[str] = None
    license_number: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def populate_display_fields(cls, data: Any) -> Any:
        if hasattr(data, "doctor_profile") and getattr(data, "doctor_profile", None):
            doc = data.doctor_profile
            data_dict = {
                "user_id": data.user_id,
                "email": data.email,
                "role": data.role,
                "is_active": data.is_active,
                "created_at": data.created_at,
                "patient_profile": getattr(data, "patient_profile", None),
                "doctor_profile": doc,
                "name": f"Dr. {doc.first_name} {doc.last_name}",
                "license_number": doc.license_number,
            }
            return data_dict
        elif hasattr(data, "patient_profile") and getattr(data, "patient_profile", None):
            pat = data.patient_profile
            data_dict = {
                "user_id": data.user_id,
                "email": data.email,
                "role": data.role,
                "is_active": data.is_active,
                "created_at": data.created_at,
                "patient_profile": pat,
                "doctor_profile": getattr(data, "doctor_profile", None),
                "name": f"{pat.first_name} {pat.last_name}",
                "license_number": None,
            }
            return data_dict
        return data
