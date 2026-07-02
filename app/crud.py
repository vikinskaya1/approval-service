from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext
from app.events import (
    EVENT_APPROVED,
    EVENT_CANCELLED,
    EVENT_CREATED,
    EVENT_REJECTED,
    approval_request_event_payload,
)
from app.models import (
    FINAL_STATUSES,
    ApprovalRequest,
    ApprovalStatus,
    AuditLog,
    OutboxEvent,
    _now,
)
from app.schemas import ApprovalRequestCreate


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="approval request not found")


def get_approval_request_or_404(db: Session, workspace_id: str, request_id: str) -> ApprovalRequest:
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.id == request_id,
        ApprovalRequest.workspace_id == workspace_id,
    )
    req = db.execute(stmt).scalar_one_or_none()
    if req is None:
        raise _not_found()
    return req


def list_approval_requests(
    db: Session,
    workspace_id: str,
    status_filter: ApprovalStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[ApprovalRequest], int]:
    base = select(ApprovalRequest).where(ApprovalRequest.workspace_id == workspace_id)
    if status_filter is not None:
        base = base.where(ApprovalRequest.status == status_filter)

    total = len(db.execute(base).scalars().all())
    stmt = base.order_by(ApprovalRequest.created_at.desc()).limit(limit).offset(offset)
    items = list(db.execute(stmt).scalars().all())
    return items, total


def create_approval_request(
    db: Session, ctx: AuthContext, payload: ApprovalRequestCreate
) -> ApprovalRequest:
    req = ApprovalRequest(
        workspace_id=ctx.workspace_id,
        source_type=payload.sourceType,
        source_id=payload.sourceId,
        title=payload.title,
        description=payload.description,
        reviewer_user_ids=payload.reviewerUserIds,
        status=ApprovalStatus.pending,
        created_by=ctx.user_id,
    )
    db.add(req)
    db.flush()  # assign req.id

    db.add(
        AuditLog(
            workspace_id=ctx.workspace_id,
            approval_request_id=req.id,
            action="created",
            actor_user_id=ctx.user_id,
            details={"title": req.title, "sourceType": req.source_type.value},
        )
    )
    db.add(
        OutboxEvent(
            workspace_id=ctx.workspace_id,
            approval_request_id=req.id,
            event_type=EVENT_CREATED,
            payload=approval_request_event_payload(req),
        )
    )
    db.commit()
    db.refresh(req)
    return req


def _apply_decision(
    db: Session,
    ctx: AuthContext,
    request_id: str,
    *,
    target_status: ApprovalStatus,
    action_name: str,
    event_type: str,
    comment: str | None = None,
    reason: str | None = None,
) -> ApprovalRequest:
    req = get_approval_request_or_404(db, ctx.workspace_id, request_id)

    if req.status in FINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"approval request already in final state '{req.status.value}'",
        )

    req.status = target_status
    req.decided_by = ctx.user_id
    req.decided_at = _now()
    req.decision_comment = comment
    req.decision_reason = reason
    req.version += 1

    db.add(
        AuditLog(
            workspace_id=ctx.workspace_id,
            approval_request_id=req.id,
            action=action_name,
            actor_user_id=ctx.user_id,
            details={"comment": comment, "reason": reason},
        )
    )
    db.add(
        OutboxEvent(
            workspace_id=ctx.workspace_id,
            approval_request_id=req.id,
            event_type=event_type,
            payload=approval_request_event_payload(req),
        )
    )
    db.commit()
    db.refresh(req)
    return req


def approve_approval_request(db: Session, ctx: AuthContext, request_id: str, comment: str | None) -> ApprovalRequest:
    return _apply_decision(
        db,
        ctx,
        request_id,
        target_status=ApprovalStatus.approved,
        action_name="approved",
        event_type=EVENT_APPROVED,
        comment=comment,
    )


def reject_approval_request(db: Session, ctx: AuthContext, request_id: str, reason: str) -> ApprovalRequest:
    return _apply_decision(
        db,
        ctx,
        request_id,
        target_status=ApprovalStatus.rejected,
        action_name="rejected",
        event_type=EVENT_REJECTED,
        reason=reason,
    )


def cancel_approval_request(db: Session, ctx: AuthContext, request_id: str, reason: str) -> ApprovalRequest:
    return _apply_decision(
        db,
        ctx,
        request_id,
        target_status=ApprovalStatus.cancelled,
        action_name="cancelled",
        event_type=EVENT_CANCELLED,
        reason=reason,
    )
