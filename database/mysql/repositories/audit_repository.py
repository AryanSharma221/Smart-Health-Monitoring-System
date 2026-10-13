"""
System Audit and Compliance Repository.

Provides structured persistence for security events and sensitive clinical data access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from database.mysql.models import AuditLog


class AuditRepository:
    """Encapsulates relational persistence queries for immutable audit logs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        action: str,
        target_type: str,
        target_id: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        metadata_json: Optional[str] = None,
    ) -> AuditLog:
        """Stage an audit trail record."""
        log = AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            metadata_json=metadata_json,
            timestamp=datetime.now(timezone.utc),
        )
        self.session.add(log)
        self.session.flush()
        return log

    def list_logs(
        self,
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Query audit log entries ordered by timestamp descending."""
        stmt = select(AuditLog)
        if actor_id:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if target_type:
            stmt = stmt.where(AuditLog.target_type == target_type)

        stmt = stmt.order_by(desc(AuditLog.timestamp)).limit(limit)
        return list(self.session.scalars(stmt).all())
