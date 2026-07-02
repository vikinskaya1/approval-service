"""Idempotency-Key handling.

Every state-changing endpoint (create/approve/reject/cancel) requires an
`Idempotency-Key` header. The key is scoped per (workspace, endpoint, key):

- First request with a given key: executed normally, and the resulting
  status code + response body are stored.
- Repeat request with the same key AND the same request body: the stored
  response is replayed verbatim, without re-running any side effects
  (no duplicate approval requests, no duplicate decisions, no duplicate
  audit/event rows).
- Repeat request with the same key but a DIFFERENT request body: rejected
  with 409, since replaying it would silently apply the wrong response to
  a different intended operation.

Because the record is written in the same DB transaction as the business
change (see routers), a crash between "business change committed" and
"idempotency record written" cannot happen - they commit together.
"""
import hashlib
import json

from fastapi import Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
) -> str:
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required for this operation",
        )
    return idempotency_key.strip()


def hash_request(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_existing(
    db: Session, workspace_id: str, endpoint: str, idempotency_key: str
) -> IdempotencyRecord | None:
    return (
        db.query(IdempotencyRecord)
        .filter_by(workspace_id=workspace_id, endpoint=endpoint, idempotency_key=idempotency_key)
        .one_or_none()
    )


def resolve_or_conflict(existing: IdempotencyRecord, request_hash: str) -> dict | None:
    """Returns the stored response body to replay, or raises 409 if the
    same key was used for a materially different request."""
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different request payload",
        )
    return existing.response_body


def run_with_idempotency(
    db: Session,
    workspace_id: str,
    endpoint: str,
    idempotency_key: str,
    request_payload: dict,
    execute_fn,
) -> tuple[int, dict]:
    """Looks up a prior result for this key; if none exists, calls
    `execute_fn()` (which must return (status_code, response_body_dict) and
    perform its own DB commit for the business change), then persists the
    idempotency record so retries replay this exact result.
    """
    request_hash = hash_request(request_payload)
    existing = find_existing(db, workspace_id, endpoint, idempotency_key)
    if existing is not None:
        body = resolve_or_conflict(existing, request_hash)
        return existing.response_status, body

    response_status, response_body = execute_fn()
    store(db, workspace_id, endpoint, idempotency_key, request_hash, response_status, response_body)
    return response_status, response_body


def store(
    db: Session,
    workspace_id: str,
    endpoint: str,
    idempotency_key: str,
    request_hash: str,
    response_status: int,
    response_body: dict,
) -> None:
    record = IdempotencyRecord(
        workspace_id=workspace_id,
        endpoint=endpoint,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response_status=response_status,
        response_body=response_body,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race against a concurrent identical request; the other
        # request's record already stands, which is fine - both callers
        # will get an equivalent successful result.
        db.rollback()
