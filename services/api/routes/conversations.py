"""
Secure Clinical Conversations and Messaging API Router.

Endpoints:
- GET  /conversations: List permitted conversations with unread counts and message previews.
- POST /conversations: Initiate or retrieve canonical patient-doctor conversation.
- GET  /conversations/{conversation_id}: Retrieve individual conversation details.
- GET  /conversations/{conversation_id}/messages: List conversation messages with pagination.
- POST /conversations/{conversation_id}/messages: Send message with idempotency support.
- POST /conversations/{conversation_id}/read: Mark incoming unread messages as read.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from database.mysql.exceptions import EntityConflictError, EntityNotFoundError
from database.mysql.models import User
from database.mysql.session import get_db
from services.api.schemas.messaging import (
    ConversationResponse,
    CreateConversationRequest,
    LastMessagePreview,
    MarkReadRequest,
    MarkReadResponse,
    MessageResponse,
    PaginatedConversationsResponse,
    PaginatedMessagesResponse,
    SendMessageRequest,
)
from services.auth.dependencies import get_current_user
from services.auth.exceptions import PermissionDeniedError
from services.messaging_service import MessagingService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clinical Messaging"])


@router.get(
    "/conversations",
    response_model=PaginatedConversationsResponse,
    status_code=status.HTTP_200_OK,
    summary="List permitted conversations for authenticated user",
)
def list_conversations(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedConversationsResponse:
    """Retrieve all conversations the authenticated user is authorized to access."""
    service = MessagingService(db)
    items_data, total_count = service.list_conversations(
        current_user=current_user,
        page=page,
        page_size=page_size,
    )

    items = [
        ConversationResponse(
            conversation_id=item["conversation_id"],
            patient_id=item["patient_id"],
            doctor_id=item["doctor_id"],
            patient_name=item["patient_name"],
            doctor_name=item["doctor_name"],
            is_active=item["is_active"],
            unread_count=item["unread_count"],
            last_message=LastMessagePreview(**item["last_message"]) if item["last_message"] else None,
            created_at=item["created_at"],
            updated_at=item["updated_at"],
        )
        for item in items_data
    ]

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0
    return PaginatedConversationsResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total_pages > 0,
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or retrieve canonical patient-doctor conversation",
)
def create_or_get_conversation(
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    """
    Establish or retrieve a secure conversation between an authorized patient and clinician.
    Enforces active care assignment validation.
    """
    service = MessagingService(db)

    # Determine other_id based on authenticated role
    if current_user.role == "patient":
        if not payload.doctor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'doctor_id' is required when initiated by a patient.",
            )
        other_id = payload.doctor_id
    elif current_user.role == "doctor":
        if not payload.patient_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'patient_id' is required when initiated by a clinician.",
            )
        other_id = payload.patient_id
    elif current_user.role == "admin_operator":
        if not payload.patient_id or not payload.doctor_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Admin must specify both 'patient_id' and 'doctor_id'.",
            )
        other_id = f"{payload.patient_id}:{payload.doctor_id}"
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' cannot initiate clinical conversations.",
        )

    try:
        conv, was_created = service.get_or_create_conversation(current_user=current_user, other_id=other_id)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    p_name = f"{conv.patient.first_name} {conv.patient.last_name}" if conv.patient else f"Patient {conv.patient_id}"
    d_name = f"Dr. {conv.doctor.first_name} {conv.doctor.last_name}" if conv.doctor else f"Dr. {conv.doctor_id}"

    return ConversationResponse(
        conversation_id=conv.conversation_id,
        patient_id=conv.patient_id,
        doctor_id=conv.doctor_id,
        patient_name=p_name,
        doctor_name=d_name,
        is_active=conv.is_active,
        unread_count=0,
        last_message=None,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get conversation metadata by ID",
)
def get_conversation_by_id(
    conversation_id: str = Path(..., min_length=1, max_length=64, description="Conversation ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    """Retrieve details for a specific conversation."""
    service = MessagingService(db)
    try:
        conv = service.get_conversation(current_user=current_user, conversation_id=conversation_id)
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    p_name = f"{conv.patient.first_name} {conv.patient.last_name}" if conv.patient else f"Patient {conv.patient_id}"
    d_name = f"Dr. {conv.doctor.first_name} {conv.doctor.last_name}" if conv.doctor else f"Dr. {conv.doctor_id}"
    unread = service.conv_repo.count_unread_messages(conv.conversation_id, current_user.user_id)
    last_msg = service.conv_repo.get_last_message(conv.conversation_id)

    return ConversationResponse(
        conversation_id=conv.conversation_id,
        patient_id=conv.patient_id,
        doctor_id=conv.doctor_id,
        patient_name=p_name,
        doctor_name=d_name,
        is_active=conv.is_active,
        unread_count=unread,
        last_message=LastMessagePreview(
            message_id=last_msg.message_id,
            sender_id=last_msg.sender_id,
            preview=last_msg.content[:100],
            created_at=last_msg.created_at,
        ) if last_msg else None,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=PaginatedMessagesResponse,
    status_code=status.HTTP_200_OK,
    summary="List messages in conversation",
)
def list_messages(
    conversation_id: str = Path(..., min_length=1, max_length=64, description="Conversation ID"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size limit"),
    order: str = Query("asc", pattern="^(asc|desc)$", description="Chronological ordering"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedMessagesResponse:
    """Retrieve paginated messages for an authorized conversation."""
    service = MessagingService(db)
    try:
        messages, total_count = service.list_messages(
            current_user=current_user,
            conversation_id=conversation_id,
            page=page,
            page_size=page_size,
            order=order,
        )
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    items = [
        MessageResponse(
            message_id=m.message_id,
            conversation_id=m.conversation_id,
            sender_id=m.sender_id,
            receiver_id=m.receiver_id,
            patient_context_id=m.patient_context_id,
            content=m.content,
            is_read=m.is_read,
            idempotency_key=m.idempotency_key,
            created_at=m.created_at,
            read_at=m.read_at,
        )
        for m in messages
    ]

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0
    return PaginatedMessagesResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_previous=page > 1 and total_pages > 0,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a direct message in a conversation",
)
def send_message(
    conversation_id: str = Path(..., min_length=1, max_length=64, description="Conversation ID"),
    payload: SendMessageRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Send a message within an authorized conversation."""
    service = MessagingService(db)
    try:
        msg, was_created = service.send_message(
            current_user=current_user,
            conversation_id=conversation_id,
            content=payload.content,
            idempotency_key=payload.idempotency_key,
        )
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except EntityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    return MessageResponse(
        message_id=msg.message_id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        receiver_id=msg.receiver_id,
        patient_context_id=msg.patient_context_id,
        content=msg.content,
        is_read=msg.is_read,
        idempotency_key=msg.idempotency_key,
        created_at=msg.created_at,
        read_at=msg.read_at,
    )


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=MarkReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark incoming conversation messages as read",
)
def mark_messages_read(
    conversation_id: str = Path(..., min_length=1, max_length=64, description="Conversation ID"),
    payload: Optional[MarkReadRequest] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MarkReadResponse:
    """Mark incoming unread messages in conversation as read."""
    service = MessagingService(db)
    message_ids = payload.message_ids if payload else None

    try:
        count, read_time = service.mark_as_read(
            current_user=current_user,
            conversation_id=conversation_id,
            message_ids=message_ids,
        )
    except EntityNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' was not found.",
        )
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    return MarkReadResponse(
        status="success",
        conversation_id=conversation_id,
        messages_marked_read=count,
        read_at=read_time,
    )
