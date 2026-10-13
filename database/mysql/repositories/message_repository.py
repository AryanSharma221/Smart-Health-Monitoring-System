"""
Message Data Access Repository.

Encapsulates relational persistence, idempotency lookup, pagination, and read status transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, select, update
from sqlalchemy.orm import Session

from database.mysql.models import Message

logger = logging.getLogger(__name__)


class MessageRepository:
    """Repository for managing Message persistence and queries."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, message_id: str) -> Optional[Message]:
        """Fetch message by primary key."""
        return self.session.get(Message, message_id)

    def get_by_sender_and_idempotency_key(
        self,
        sender_id: str,
        idempotency_key: str,
    ) -> Optional[Message]:
        """Look up existing message by sender and idempotency key."""
        stmt = select(Message).where(
            Message.sender_id == sender_id,
            Message.idempotency_key == idempotency_key,
        )
        return self.session.scalar(stmt)

    def create_message(self, message: Message) -> Message:
        """Stage and add a Message entity to the session."""
        self.session.add(message)
        return message

    def list_conversation_messages_paginated(
        self,
        conversation_id: str,
        page: int = 1,
        page_size: int = 20,
        order: str = "asc",
    ) -> Tuple[List[Message], int]:
        """
        Query paginated messages for a conversation with deterministic ordering.
        Returns (messages_slice, total_count).
        """
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        offset = (page - 1) * page_size

        count_stmt = (
            select(func.count(Message.message_id))
            .where(Message.conversation_id == conversation_id)
        )
        total_count = self.session.scalar(count_stmt) or 0

        sort_col = asc(Message.created_at) if order.lower() == "asc" else desc(Message.created_at)
        tie_breaker = asc(Message.message_id) if order.lower() == "asc" else desc(Message.message_id)

        query_stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(sort_col, tie_breaker)
            .offset(offset)
            .limit(page_size)
        )
        messages = list(self.session.scalars(query_stmt).all())
        return messages, total_count

    def mark_messages_read(
        self,
        conversation_id: str,
        receiver_id: str,
        message_ids: Optional[List[str]] = None,
    ) -> Tuple[int, datetime]:
        """
        Mark eligible unread incoming messages as read for receiver_id.
        Never updates outgoing messages (where receiver_id != user).
        Returns (count_marked, server_timestamp).
        """
        now = datetime.now(timezone.utc)

        # First identify the message IDs to be updated
        stmt = (
            select(Message.message_id)
            .where(
                Message.conversation_id == conversation_id,
                Message.receiver_id == receiver_id,
                Message.is_read == False,  # noqa: E712
            )
        )
        if message_ids:
            stmt = stmt.where(Message.message_id.in_(message_ids))

        target_ids = list(self.session.scalars(stmt).all())
        if not target_ids:
            return 0, now

        update_stmt = (
            update(Message)
            .where(Message.message_id.in_(target_ids))
            .values(is_read=True, read_at=now)
        )
        self.session.execute(update_stmt)
        return len(target_ids), now
