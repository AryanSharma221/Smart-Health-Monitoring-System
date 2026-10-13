"""
Pydantic Schemas for Secure Clinical Conversations, Messages, and Read Status.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateConversationRequest(BaseModel):
    """Payload to initiate or retrieve a conversation."""

    doctor_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=32,
        description="Target clinician ID (required when initiated by a patient)",
    )
    patient_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=32,
        description="Target patient ID (required when initiated by a clinician)",
    )


class LastMessagePreview(BaseModel):
    """Summary of the most recent message in a conversation."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str
    sender_id: str
    preview: str
    created_at: datetime


class ConversationResponse(BaseModel):
    """Conversation metadata summary."""

    model_config = ConfigDict(from_attributes=True)

    conversation_id: str
    patient_id: str
    doctor_id: str
    patient_name: str
    doctor_name: str
    is_active: bool
    unread_count: int
    last_message: Optional[LastMessagePreview] = None
    created_at: datetime
    updated_at: datetime


class PaginatedConversationsResponse(BaseModel):
    """Paginated collection of conversations."""

    model_config = ConfigDict(from_attributes=True)

    items: List[ConversationResponse]
    total_count: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_previous: bool


class SendMessageRequest(BaseModel):
    """Inbound message dispatch payload."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Message body text (1-2000 characters, non-empty)",
    )
    idempotency_key: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        description="Optional client idempotency key for safe transmission retries",
    )


class MessageResponse(BaseModel):
    """Individual clinical message record."""

    model_config = ConfigDict(from_attributes=True)

    message_id: str
    conversation_id: Optional[str] = None
    sender_id: str
    receiver_id: str
    patient_context_id: Optional[str] = None
    content: str
    is_read: bool
    idempotency_key: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class PaginatedMessagesResponse(BaseModel):
    """Paginated collection of conversation messages."""

    model_config = ConfigDict(from_attributes=True)

    items: List[MessageResponse]
    total_count: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total_pages: int = Field(..., ge=0)
    has_next: bool
    has_previous: bool


class MarkReadRequest(BaseModel):
    """Optional message read request specifying subset of IDs."""

    message_ids: Optional[List[str]] = Field(
        None,
        description="Optional specific message IDs to mark as read. If omitted, marks all eligible incoming unread messages.",
    )


class MarkReadResponse(BaseModel):
    """Confirmation of read status transition."""

    status: str = "success"
    conversation_id: str
    messages_marked_read: int
    read_at: datetime
