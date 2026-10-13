"""
Conversation Data Access Repository.

Encapsulates relational persistence and querying for secure patient-clinician conversations.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from database.mysql.models import Conversation, Message, User

logger = logging.getLogger(__name__)


class ConversationRepository:
    """Repository for managing Conversation persistence and queries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """Fetch conversation by unique identifier with eager loaded participant profiles."""
        stmt = (
            select(Conversation)
            .options(
                joinedload(Conversation.patient),
                joinedload(Conversation.doctor),
            )
            .where(Conversation.conversation_id == conversation_id)
        )
        return self.session.scalar(stmt)

    def get_by_patient_and_doctor(self, patient_id: str, doctor_id: str) -> Optional[Conversation]:
        """Fetch conversation by canonical participant pair."""
        stmt = (
            select(Conversation)
            .options(
                joinedload(Conversation.patient),
                joinedload(Conversation.doctor),
            )
            .where(
                Conversation.patient_id == patient_id,
                Conversation.doctor_id == doctor_id,
            )
        )
        return self.session.scalar(stmt)

    def create_conversation(
        self,
        patient_id: str,
        doctor_id: str,
        conversation_id: Optional[str] = None,
    ) -> Conversation:
        """Create and stage a new Conversation entity."""
        cid = conversation_id or f"conv_{patient_id}_{doctor_id}"
        conversation = Conversation(
            conversation_id=cid,
            patient_id=patient_id,
            doctor_id=doctor_id,
            is_active=True,
        )
        self.session.add(conversation)
        return conversation

    def list_conversations_for_user(
        self,
        user: User,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[Conversation], int]:
        """
        List conversations the authenticated user is authorized to participate in.
        Returns (conversations_slice, total_count).
        """
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        filters = []
        if user.role == "patient":
            patient_id = getattr(user.patient_profile, "patient_id", None)
            if not patient_id:
                return [], 0
            filters.append(Conversation.patient_id == patient_id)
        elif user.role == "doctor":
            doctor_id = getattr(user.doctor_profile, "doctor_id", None)
            if not doctor_id:
                return [], 0
            filters.append(Conversation.doctor_id == doctor_id)
        elif user.role == "admin_operator":
            pass  # Admins have global operational visibility
        else:
            return [], 0

        count_stmt = select(func.count(Conversation.conversation_id))
        if filters:
            count_stmt = count_stmt.where(*filters)
        total_count = self.session.scalar(count_stmt) or 0

        query_stmt = (
            select(Conversation)
            .options(
                joinedload(Conversation.patient),
                joinedload(Conversation.doctor),
            )
            .order_by(desc(Conversation.updated_at), desc(Conversation.conversation_id))
            .offset(offset)
            .limit(page_size)
        )
        if filters:
            query_stmt = query_stmt.where(*filters)

        conversations = list(self.session.scalars(query_stmt).all())
        return conversations, total_count

    def count_unread_messages(self, conversation_id: str, receiver_id: str) -> int:
        """Count unread messages addressed to receiver_id in a specific conversation."""
        stmt = select(func.count(Message.message_id)).where(
            Message.conversation_id == conversation_id,
            Message.receiver_id == receiver_id,
            Message.is_read == False,  # noqa: E712
        )
        return self.session.scalar(stmt) or 0

    def get_last_message(self, conversation_id: str) -> Optional[Message]:
        """Fetch the most recent message in a conversation for summary preview."""
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at), desc(Message.message_id))
            .limit(1)
        )
        return self.session.scalar(stmt)
