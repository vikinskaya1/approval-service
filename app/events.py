"""Event payload construction for the transactional outbox.

Payloads only ever contain the same opaque ids and fields already present
in API responses. No secrets, tokens, emails, storage keys, signed URLs or
provider payloads are ever placed on an event - there simply are none of
those in this service's data model.
"""
from app.models import ApprovalRequest


def approval_request_event_payload(req: ApprovalRequest) -> dict:
    return {
        "approvalRequestId": req.id,
        "workspaceId": req.workspace_id,
        "sourceType": req.source_type.value,
        "sourceId": req.source_id,
        "status": req.status.value,
        "decidedBy": req.decided_by,
        "decidedAt": req.decided_at.isoformat() if req.decided_at else None,
    }


EVENT_CREATED = "approval_request.created"
EVENT_APPROVED = "approval_request.approved"
EVENT_REJECTED = "approval_request.rejected"
EVENT_CANCELLED = "approval_request.cancelled"
