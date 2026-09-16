from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
import hashlib
from datetime import datetime, UTC

class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

class Subscription(BaseModel):
    """
    Defines matching criteria for a subscriber.
    If a field is None, it acts as a wildcard for that property.
    """
    subscription_id: str = Field(..., description="Unique ID for this subscription")
    subscriber_id: str = Field(..., description="The ID of the subscribing service/component")
    tenant_id: str = Field(..., description="The authoritative tenant boundary")
    workspace_id: Optional[str] = Field(None, description="Optional workspace scope boundary")
    plant_id: Optional[str] = Field(None, description="Optional plant scope boundary")
    category: Optional[str] = Field(None, description="Match specific EventCategory")
    event_type: Optional[str] = Field(None, description="Match specific event type")
    source: Optional[str] = Field(None, description="Match specific event source")

class EventDelivery(BaseModel):
    """
    Tracks the delivery state of a single event to a single subscription.
    """
    delivery_id: str = Field(..., description="Deterministic cryptographic delivery ID")
    event_id: str = Field(..., description="Canonical event ID")
    event_fingerprint: str = Field(..., description="Canonical event fingerprint")
    subscription_id: str = Field(..., description="Target subscription ID")
    tenant_id: str = Field(..., description="Tenant scope boundary")
    status: DeliveryStatus = Field(default=DeliveryStatus.PENDING)
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)
    last_error: Optional[str] = Field(None, description="Message from last failure")
    next_retry_at: Optional[str] = Field(None, description="ISO-8601 timestamp for next allowed attempt")
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

class DeadLetter(BaseModel):
    """
    Represents an event that failed delivery after exhaustion of retries.
    """
    dead_letter_id: str = Field(..., description="Unique dead letter record ID")
    delivery_id: str = Field(..., description="The delivery ID that failed")
    event_id: str = Field(..., description="Canonical event ID")
    subscription_id: str = Field(..., description="Target subscription ID")
    tenant_id: str = Field(..., description="Tenant scope boundary")
    failure_reason: str = Field(..., description="Final failure message/exception")
    attempt_count: int = Field(..., description="Total attempts made")
    recorded_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))

def compute_delivery_id(event_fingerprint: str, subscription_id: str) -> str:
    """
    Compute a deterministic delivery ID based on the exact event instance (fingerprint)
    and the exact subscription.
    """
    payload = f"{event_fingerprint}:{subscription_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
