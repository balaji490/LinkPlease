from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class DMStatus(str, Enum):
    PENDING = "pending"          # Waiting in worker queue to be dispatched
    SENT_TO_API = "sent_to_api"  # Dispatched to PseudoGram (202 accepted), waiting on reconciliation
    DELIVERED = "delivered"      # Confirmed delivered (terminal success)
    FAILED = "failed"            # Exhausted retries or 400 invalid request (terminal failure)
    CANCELLED = "cancelled"      # Comment deleted before dispatch


class RuleCreateRequest(BaseModel):
    keyword: str
    dm_message: str


class RuleResponse(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str


class WebhookUser(BaseModel):
    user_id: str
    username: Optional[str] = None


class WebhookCommentData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[str] = None
    from_user: Optional[WebhookUser] = Field(default=None, alias="from")


class WebhookPayload(BaseModel):
    event_id: str
    event_type: str
    sent_at: Optional[str] = None
    data: WebhookCommentData


class StatsResponse(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int


class DMJob(BaseModel):
    id: Optional[int] = None
    rule_id: str
    recipient_user_id: str
    comment_id: str
    message: str
    dm_id: Optional[str] = None
    status: DMStatus = DMStatus.PENDING
    attempts: int = 0
    max_attempts: int = 5
    next_attempt_at: float = 0.0
    last_error: Optional[str] = None
    created_at: float
    updated_at: float
