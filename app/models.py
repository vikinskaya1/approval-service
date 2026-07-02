import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceType(str, enum.Enum):
    publication = "publication"
    scenario = "scenario"
    edit = "edit"
    external = "external"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


FINAL_STATUSES = {ApprovalStatus.approved, ApprovalStatus.rejected, ApprovalStatus.cancelled}


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    # External user ids, stored as a plain JSON list of strings (no PII beyond opaque ids)
    reviewer_user_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), nullable=False, default=ApprovalStatus.pending, index=True
    )

    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Approve -> comment, Reject/Cancel -> reason. Kept as separate nullable columns
    # so the API contract per-decision-type stays explicit.
    decision_comment: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Optimistic concurrency guard, incremented on every state change.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    audit_logs: Mapped[list["AuditLog"]] = relationship(
        back_populates="approval_request", cascade="all, delete-orphan"
    )
    events: Mapped[list["OutboxEvent"]] = relationship(
        back_populates="approval_request", cascade="all, delete-orphan"
    )


class AuditLog(Base):
    """Immutable trail of who did what to an approval request."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    approval_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_requests.id"), index=True, nullable=False
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False)  # created|approved|rejected|cancelled
    actor_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    approval_request: Mapped["ApprovalRequest"] = relationship(back_populates="audit_logs")


class OutboxEvent(Base):
    """Transactional outbox row, written in the same DB transaction as the
    state change it describes. A separate publisher process/worker (not part
    of this service) can poll `published = false` rows and forward them to a
    message broker for downstream integration.
    """

    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    approval_request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("approval_requests.id"), index=True, nullable=False
    )

    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    published: Mapped[bool] = mapped_column(default=False, nullable=False)

    approval_request: Mapped["ApprovalRequest"] = relationship(back_populates="events")


class IdempotencyRecord(Base):
    """Stores the outcome of a previously-processed request so retries with
    the same Idempotency-Key are answered without re-executing side effects.
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "endpoint", "idempotency_key", name="uq_idempotency_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)

    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
