from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import crud
from app.auth import AuthContext, get_auth_context
from app.database import get_db
from app.idempotency import require_idempotency_key, run_with_idempotency
from app.models import ApprovalStatus
from app.schemas import (
    ApprovalRequestCreate,
    ApprovalRequestListOut,
    ApprovalRequestOut,
    ApproveDecision,
    CancelDecision,
    RejectDecision,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/approval-requests", tags=["approval-requests"])


def _out(req) -> dict:
    return ApprovalRequestOut(
        id=req.id,
        workspaceId=req.workspace_id,
        sourceType=req.source_type,
        sourceId=req.source_id,
        title=req.title,
        description=req.description,
        reviewerUserIds=req.reviewer_user_ids,
        status=req.status,
        createdBy=req.created_by,
        createdAt=req.created_at,
        updatedAt=req.updated_at,
        decidedBy=req.decided_by,
        decidedAt=req.decided_at,
        decisionComment=req.decision_comment,
        decisionReason=req.decision_reason,
    ).model_dump(mode="json")


@router.post("", response_model=None, status_code=201)
def create_approval_request(
    workspace_id: str,
    payload: ApprovalRequestCreate,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    ctx.require("approval:create")

    def execute():
        req = crud.create_approval_request(db, ctx, payload)
        return 201, _out(req)

    status_code, body = run_with_idempotency(
        db, workspace_id, "create_approval_request", idempotency_key, payload.model_dump(mode="json"), execute
    )
    return JSONResponse(status_code=status_code, content=body)


@router.get("", response_model=ApprovalRequestListOut)
def list_approval_requests(
    workspace_id: str,
    status_filter: ApprovalStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    ctx.require("approval:read")
    items, total = crud.list_approval_requests(db, workspace_id, status_filter, limit, offset)
    return ApprovalRequestListOut(
        items=[ApprovalRequestOut.model_validate(_to_view(i)) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _to_view(req):
    # Adapter object exposing the camelCase field names ApprovalRequestOut expects,
    # backed by the ORM row's snake_case attributes.
    return {
        "id": req.id,
        "workspaceId": req.workspace_id,
        "sourceType": req.source_type,
        "sourceId": req.source_id,
        "title": req.title,
        "description": req.description,
        "reviewerUserIds": req.reviewer_user_ids,
        "status": req.status,
        "createdBy": req.created_by,
        "createdAt": req.created_at,
        "updatedAt": req.updated_at,
        "decidedBy": req.decided_by,
        "decidedAt": req.decided_at,
        "decisionComment": req.decision_comment,
        "decisionReason": req.decision_reason,
    }


@router.get("/{request_id}", response_model=ApprovalRequestOut)
def get_approval_request(
    workspace_id: str,
    request_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
):
    ctx.require("approval:read")
    req = crud.get_approval_request_or_404(db, workspace_id, request_id)
    return ApprovalRequestOut.model_validate(_to_view(req))


@router.post("/{request_id}/approve", response_model=None, status_code=200)
def approve(
    workspace_id: str,
    request_id: str,
    payload: ApproveDecision,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    ctx.require("approval:decide")

    def execute():
        req = crud.approve_approval_request(db, ctx, request_id, payload.comment)
        return 200, _out(req)

    endpoint = f"approve:{request_id}"
    status_code, body = run_with_idempotency(
        db, workspace_id, endpoint, idempotency_key, payload.model_dump(mode="json"), execute
    )
    return JSONResponse(status_code=status_code, content=body)


@router.post("/{request_id}/reject", response_model=None, status_code=200)
def reject(
    workspace_id: str,
    request_id: str,
    payload: RejectDecision,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    ctx.require("approval:decide")

    def execute():
        req = crud.reject_approval_request(db, ctx, request_id, payload.reason)
        return 200, _out(req)

    endpoint = f"reject:{request_id}"
    status_code, body = run_with_idempotency(
        db, workspace_id, endpoint, idempotency_key, payload.model_dump(mode="json"), execute
    )
    return JSONResponse(status_code=status_code, content=body)


@router.post("/{request_id}/cancel", response_model=None, status_code=200)
def cancel(
    workspace_id: str,
    request_id: str,
    payload: CancelDecision,
    ctx: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
    idempotency_key: str = Depends(require_idempotency_key),
):
    ctx.require("approval:cancel")

    def execute():
        req = crud.cancel_approval_request(db, ctx, request_id, payload.reason)
        return 200, _out(req)

    endpoint = f"cancel:{request_id}"
    status_code, body = run_with_idempotency(
        db, workspace_id, endpoint, idempotency_key, payload.model_dump(mode="json"), execute
    )
    return JSONResponse(status_code=status_code, content=body)
