"""
Secure Clinical Messaging Application Service.

Coordinates:
1. Patient-clinician conversation lifecycle and membership verification.
2. Direct message persistence and idempotent client retries.
3. Message read status tracking and unread counters.
4. Active care assignment enforcement (revoked assignments enter read-only mode).
5. Post-commit real-time WebSocket event dispatch.
6. Zero-secret compliance audit logging.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityConflictError, EntityNotFoundError
from database.mysql.models import Conversation, Message, User
from database.mysql.repositories.audit_repository import AuditRepository
from database.mysql.repositories.conversation_repository import ConversationRepository
from database.mysql.repositories.message_repository import MessageRepository
from database.mysql.repositories.patient_repository import PatientRepository
from database.mysql.session import transaction_scope
from services.auth.exceptions import PermissionDeniedError

logger = logging.getLogger(__name__)


class MessagingService:
    """Coordinates secure messaging workflows and database transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.conv_repo = ConversationRepository(session)
        self.msg_repo = MessageRepository(session)
        self.patient_repo = PatientRepository(session)
        self.audit_repo = AuditRepository(session)

    def get_or_create_conversation(
        self,
        current_user: User,
        other_id: str,
    ) -> Tuple[Conversation, bool]:
        """
        Retrieve an existing conversation or create a new one between current user and other_id.
        Enforces patient-clinician assignment verification.
        Returns (conversation, was_created).
        """
        if not current_user.is_active:
            raise PermissionDeniedError("Account is inactive or disabled.")

        patient_id: Optional[str] = None
        doctor_id: Optional[str] = None

        if current_user.role == "patient":
            patient_profile = getattr(current_user, "patient_profile", None)
            if not patient_profile:
                raise PermissionDeniedError("Patient profile is not configured.")
            patient_id = patient_profile.patient_id
            doctor_id = other_id

        elif current_user.role == "doctor":
            doc_profile = getattr(current_user, "doctor_profile", None)
            if not doc_profile:
                raise PermissionDeniedError("Doctor profile is not configured.")
            doctor_id = doc_profile.doctor_id
            patient_id = other_id

        elif current_user.role == "admin_operator":
            # For admin, other_id can be in format patient_id:doctor_id
            if ":" in other_id:
                patient_id, doctor_id = other_id.split(":", 1)
            else:
                raise ValueError("Admin must specify other_id as 'patient_id:doctor_id'.")
        else:
            raise PermissionDeniedError(f"Role '{current_user.role}' cannot initiate clinical conversations.")

        # Verify active care assignment between doctor and patient
        is_assigned = self.patient_repo.is_doctor_assigned_to_patient(
            doctor_id=doctor_id,
            patient_id=patient_id,
        )
        if not is_assigned:
            raise PermissionDeniedError(
                f"Doctor '{doctor_id}' is not actively assigned to patient '{patient_id}'."
            )

        # Look up existing conversation
        existing = self.conv_repo.get_by_patient_and_doctor(patient_id=patient_id, doctor_id=doctor_id)
        if existing:
            return existing, False

        # Create new conversation atomically
        with transaction_scope(self.session):
            conv = self.conv_repo.create_conversation(patient_id=patient_id, doctor_id=doctor_id)
            self.audit_repo.record(
                actor_id=current_user.user_id,
                action="CONVERSATION_CREATE",
                target_type="conversation",
                target_id=conv.conversation_id,
                metadata_json=json.dumps({"patient_id": patient_id, "doctor_id": doctor_id}),
            )

        logger.info(
            "Created conversation '%s' between patient '%s' and doctor '%s'",
            conv.conversation_id,
            patient_id,
            doctor_id,
        )
        return conv, True

    def get_conversation(self, current_user: User, conversation_id: str) -> Conversation:
        """
        Fetch conversation and verify that current_user is an authorized participant.
        """
        if not current_user.is_active:
            raise PermissionDeniedError("Account is inactive or disabled.")

        conv = self.conv_repo.get_by_id(conversation_id)
        if not conv:
            raise EntityNotFoundError("Conversation", conversation_id)

        # Enforce membership checks
        if current_user.role == "patient":
            patient_id = getattr(current_user.patient_profile, "patient_id", None)
            if conv.patient_id != patient_id:
                raise PermissionDeniedError("Access denied: You are not a participant in this conversation.")

        elif current_user.role == "doctor":
            doctor_id = getattr(current_user.doctor_profile, "doctor_id", None)
            if conv.doctor_id != doctor_id:
                raise PermissionDeniedError("Access denied: You are not a participant in this conversation.")

        elif current_user.role == "admin_operator":
            pass  # Allowed for system oversight
        else:
            raise PermissionDeniedError(f"Role '{current_user.role}' cannot access clinical conversations.")

        return conv

    def list_conversations(
        self,
        current_user: User,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List conversations for current_user with last message preview and unread counters.
        """
        if not current_user.is_active:
            return [], 0

        convs, total_count = self.conv_repo.list_conversations_for_user(
            user=current_user,
            page=page,
            page_size=page_size,
        )

        summaries: List[Dict[str, Any]] = []
        for c in convs:
            unread_count = self.conv_repo.count_unread_messages(c.conversation_id, current_user.user_id)
            last_msg = self.conv_repo.get_last_message(c.conversation_id)

            p_name = (
                f"{c.patient.first_name} {c.patient.last_name}"
                if c.patient
                else f"Patient {c.patient_id}"
            )
            d_name = (
                f"Dr. {c.doctor.first_name} {c.doctor.last_name}"
                if c.doctor
                else f"Dr. {c.doctor_id}"
            )

            summaries.append({
                "conversation_id": c.conversation_id,
                "patient_id": c.patient_id,
                "doctor_id": c.doctor_id,
                "patient_name": p_name,
                "doctor_name": d_name,
                "is_active": c.is_active,
                "unread_count": unread_count,
                "last_message": {
                    "message_id": last_msg.message_id,
                    "sender_id": last_msg.sender_id,
                    "preview": last_msg.content[:100],
                    "created_at": last_msg.created_at.isoformat(),
                } if last_msg else None,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            })

        return summaries, total_count

    def list_messages(
        self,
        current_user: User,
        conversation_id: str,
        page: int = 1,
        page_size: int = 20,
        order: str = "asc",
    ) -> Tuple[List[Message], int]:
        """List messages in conversation after verifying participant access."""
        self.get_conversation(current_user, conversation_id)
        return self.msg_repo.list_conversation_messages_paginated(
            conversation_id=conversation_id,
            page=page,
            page_size=page_size,
            order=order,
        )

    def send_message(
        self,
        current_user: User,
        conversation_id: str,
        content: str,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[Message, bool]:
        """
        Send a direct message within an authorized conversation.
        Supports idempotency retry keys and commits before dispatching WebSockets.
        Returns (message, was_created).
        """
        stripped_content = content.strip()
        if not stripped_content:
            raise ValueError("Message content cannot be empty or whitespace only.")
        if len(stripped_content) > 2000:
            raise ValueError("Message content cannot exceed 2000 characters.")

        conv = self.get_conversation(current_user, conversation_id)

        # Enforce care assignment revocation policy
        # If the care assignment was revoked, conversation is archived read-only
        is_assigned = self.patient_repo.is_doctor_assigned_to_patient(
            doctor_id=conv.doctor_id,
            patient_id=conv.patient_id,
        )
        if not is_assigned:
            raise PermissionDeniedError(
                "Care assignment is inactive or revoked. Conversation is archived read-only."
            )

        # Determine receiver user identity
        receiver_id: str
        if current_user.role == "patient":
            receiver_id = conv.doctor.user_id
        elif current_user.role == "doctor":
            receiver_id = conv.patient.user_id
        else:
            raise PermissionDeniedError("Administrative operators cannot post clinical messages.")

        # Idempotency check
        if idempotency_key:
            clean_key = idempotency_key.strip()
            if len(clean_key) > 64:
                raise ValueError("Idempotency key cannot exceed 64 characters.")
            existing_msg = self.msg_repo.get_by_sender_and_idempotency_key(
                sender_id=current_user.user_id,
                idempotency_key=clean_key,
            )
            if existing_msg:
                # If exact duplicate retry, return existing message idempotently
                if (
                    existing_msg.conversation_id == conversation_id
                    and existing_msg.content == stripped_content
                ):
                    logger.info("Idempotent message retry detected for key '%s'", clean_key)
                    return existing_msg, False
                raise EntityConflictError(
                    "Idempotency key already used for another message or differing content."
                )

        # Persist message within authoritative transaction
        now = datetime.now(timezone.utc)
        message_id = f"msg_{int(now.timestamp() * 1000000):016d}_{uuid.uuid4().hex[:8]}"
        with transaction_scope(self.session):
            msg = Message(
                message_id=message_id,
                conversation_id=conversation_id,
                sender_id=current_user.user_id,
                receiver_id=receiver_id,
                patient_context_id=conv.patient_id,
                content=stripped_content,
                is_read=False,
                idempotency_key=idempotency_key.strip() if idempotency_key else None,
                created_at=now,
            )
            self.msg_repo.create_message(msg)

            # Advance conversation updated_at
            conv.updated_at = func.now()

            # Record security audit event (without copying sensitive full message text)
            self.audit_repo.record(
                actor_id=current_user.user_id,
                action="MESSAGE_SEND",
                target_type="message",
                target_id=message_id,
                metadata_json=json.dumps({
                    "conversation_id": conversation_id,
                    "receiver_id": receiver_id,
                    "char_count": len(stripped_content),
                }),
            )

        # Emit real-time notification strictly AFTER transaction commits
        try:
            from services.websocket.dispatcher import notify_message_created

            notify_message_created(msg, patient_id=conv.patient_id)
        except Exception as exc:
            logger.warning("Failed to emit WebSocket message.created: %s", exc)

        return msg, True

    def mark_as_read(
        self,
        current_user: User,
        conversation_id: str,
        message_ids: Optional[List[str]] = None,
    ) -> Tuple[int, datetime]:
        """
        Mark incoming messages as read for current_user.
        Returns (count_marked, server_timestamp).
        """
        conv = self.get_conversation(current_user, conversation_id)

        with transaction_scope(self.session):
            count, read_time = self.msg_repo.mark_messages_read(
                conversation_id=conversation_id,
                receiver_id=current_user.user_id,
                message_ids=message_ids,
            )
            if count > 0:
                self.audit_repo.record(
                    actor_id=current_user.user_id,
                    action="MESSAGES_MARK_READ",
                    target_type="conversation",
                    target_id=conversation_id,
                    metadata_json=json.dumps({"messages_count": count}),
                )

        # Emit real-time read event strictly AFTER transaction commits
        if count > 0:
            try:
                from services.websocket.dispatcher import notify_message_read

                notify_message_read(
                    conversation_id=conversation_id,
                    patient_id=conv.patient_id,
                    read_by=current_user.user_id,
                    count=count,
                    read_at=read_time.isoformat(),
                )
            except Exception as exc:
                logger.warning("Failed to emit WebSocket message.read: %s", exc)

        return count, read_time
