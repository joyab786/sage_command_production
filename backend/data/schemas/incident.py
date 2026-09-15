# backend/data/schemas/incident.py
from enum import Enum
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class IncidentState(str, Enum):
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    ANALYZING = "ANALYZING"
    RECOMMENDATION_READY = "RECOMMENDATION_READY"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class ActionState(str, Enum):
    PROPOSED = "PROPOSED"
    POLICY_REVIEW = "POLICY_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class IncidentObject(BaseModel):
    incident_id: str = Field(description="Unique incident identifier")
    title: str = Field(description="Short operational summary of incident")
    severity: str = Field(default="HIGH", description="Severity level")
    state: IncidentState = Field(default=IncidentState.DETECTED, description="Incident operational state")
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat(), description="ISO-8601 detection timestamp")
    affected_entities: List[str] = Field(default_factory=list, description="List of entity IDs affected")
    telemetry_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Telemetry snapshot at detection time")
