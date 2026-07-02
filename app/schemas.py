from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import ApprovalStatus, SourceType


class ApprovalRequestCreate(BaseModel):
    sourceType: SourceType
    sourceId: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=4096)
    reviewerUserIds: list[str] = Field(default_factory=list)

    @field_validator("reviewerUserIds")
    @classmethod
    def dedupe_reviewers(cls, v: list[str]) -> list[str]:
        seen = []
        for item in v:
            if not item:
                continue
            if item not in seen:
                seen.append(item)
        return seen


class ApproveDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=2048)


class RejectDecision(BaseModel):
    reason: str = Field(min_length=1, max_length=2048)


class CancelDecision(BaseModel):
    reason: str = Field(min_length=1, max_length=2048)


class ApprovalRequestOut(BaseModel):
    id: str
    workspaceId: str
    sourceType: SourceType
    sourceId: str
    title: str
    description: str | None
    reviewerUserIds: list[str]
    status: ApprovalStatus
    createdBy: str
    createdAt: datetime
    updatedAt: datetime
    decidedBy: str | None
    decidedAt: datetime | None
    decisionComment: str | None
    decisionReason: str | None

    model_config = {"from_attributes": True}


class ApprovalRequestListOut(BaseModel):
    items: list[ApprovalRequestOut]
    total: int
    limit: int
    offset: int


class ErrorOut(BaseModel):
    error: str
    message: str
