# backend/data/schemas/closed_loop_contract.py
"""
SageCommand V3 — Closed-Loop Learning Foundation Contracts (Prompt 37)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Defines deterministic eligibility outcomes, eligibility decision records,
verification feedback event contracts, and feedback audit records.

Cardinal Invariants:
1. Closed-loop learning observes operational events, deterministically filters eligibility,
   invokes continuous verification, and records structured feedback.
2. It NEVER autonomously mutates policies, rewrites business rules, executes missions,
   or approves actions.
3. Feedback events NEVER recursively self-trigger the closed-loop coordinator (bounded loop guard).
4. Tenant, workspace, and plant scopes are authoritative from canonical event boundaries,
   never forged by payload attributes.
5. Preserves diagnostic versus authoritative verification distinction.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator

try:
    from data.schemas.verification_contract import (
        VerificationStatus,
        VerificationTargetType,
        MANDATORY_VERIFICATION_NOTICE,
        validate_identifier,
        _validate_safe_text,
        _scan_for_secrets,
    )
    from data.schemas.event_contract import EventCategory, EventSeverity, EventLifecycle
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.verification_contract import (
        VerificationStatus,
        VerificationTargetType,
        MANDATORY_VERIFICATION_NOTICE,
        validate_identifier,
        _validate_safe_text,
        _scan_for_secrets,
    )
    from backend.data.schemas.event_contract import EventCategory, EventSeverity, EventLifecycle

SCHEMA_VERSION = "3.0.0"
COORDINATOR_VERSION = "1.0.0"


# =============================================================================
# 1. CENTRALIZED ENUMS
# =============================================================================

class EligibilityStatus(str, Enum):
    """
    Deterministic evaluation outcome for event-triggered continuous verification.
    """
    ELIGIBLE = "ELIGIBLE"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class EligibilityReasonCode(str, Enum):
    """
    Machine-readable deterministic reason codes for event eligibility decisions.
    """
    VERIFICATION_REQUESTED = "VERIFICATION_REQUESTED"
    FEEDBACK_LOOP_GUARD = "FEEDBACK_LOOP_GUARD"
    UNSUPPORTED_EVENT_TYPE = "UNSUPPORTED_EVENT_TYPE"
    UNTRUSTED_PROVENANCE = "UNTRUSTED_PROVENANCE"
    MISSING_SCOPE = "MISSING_SCOPE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    MISSING_TARGET_REFERENCE = "MISSING_TARGET_REFERENCE"
    STALE_EVENT = "STALE_EVENT"
    FUTURE_DATED_EVENT = "FUTURE_DATED_EVENT"
    INVALIDATED_EVENT = "INVALIDATED_EVENT"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    VERIFICATION_ALREADY_CURRENT = "VERIFICATION_ALREADY_CURRENT"
    CIRCUIT_BREAKER_TRIPPED = "CIRCUIT_BREAKER_TRIPPED"
    DISABLED = "DISABLED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


# =============================================================================
# 2. ELIGIBILITY DECISION CONTRACT
# =============================================================================

class EligibilityDecision(BaseModel):
    """
    Deterministic decision record evaluating whether an operational event
    is eligible to trigger continuous verification.
    """
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:16]}", max_length=64)
    status: EligibilityStatus = Field(..., description="Deterministic eligibility outcome")
    reason_code: str = Field(..., max_length=64, description="Safe machine-readable reason code")
    explanation: str = Field(..., max_length=1000, description="Safe diagnostic explanation")

    # Authoritative Scopes derived from canonical event (never from payload)
    tenant_id: str = Field(..., max_length=128)
    workspace_id: str = Field(..., max_length=128)
    plant_id: str = Field(..., max_length=128)

    # Event references
    trigger_event_id: str = Field(..., max_length=128)
    trigger_event_fingerprint: str = Field(..., max_length=128)
    trigger_event_type: str = Field(..., max_length=128)
    trigger_category: str = Field(..., max_length=64)

    # Target mission resolution (if eligible)
    mission_id: Optional[str] = Field(default=None, max_length=128)
    mission_revision: Optional[int] = Field(default=None, ge=0)
    target_type: Optional[VerificationTargetType] = None
    target_id: Optional[str] = Field(default=None, max_length=128)

    decided_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        description="ISO-8601 evaluation timestamp",
    )
    coordinator_version: str = Field(default=COORDINATOR_VERSION, max_length=32)

    @field_validator("explanation")
    @classmethod
    def validate_expl(cls, v: str) -> str:
        _validate_safe_text(v, "explanation")
        return v


# =============================================================================
# 3. VERIFICATION FEEDBACK RECORD
# =============================================================================

class VerificationFeedbackRecord(BaseModel):
    """
    Persisted feedback trace recording the relationship between an operational trigger,
    the deterministic eligibility policy, the verification run, and the feedback event.
    """
    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(..., max_length=64, description="Unique feedback identifier")
    tenant_id: str = Field(..., max_length=128, description="Authoritative tenant isolation boundary")
    workspace_id: str = Field(..., max_length=128)
    plant_id: str = Field(..., max_length=128)

    # Trigger Event linkage
    trigger_event_id: str = Field(..., max_length=128)
    trigger_event_fingerprint: str = Field(..., max_length=128)

    # Policy decision
    eligibility_status: EligibilityStatus = Field(...)
    eligibility_reason: str = Field(..., max_length=64)

    # Target & Verification linkage
    mission_id: Optional[str] = Field(default=None, max_length=128)
    mission_revision: Optional[int] = Field(default=None, ge=0)
    verification_id: Optional[str] = Field(default=None, max_length=128)
    verification_status: Optional[str] = Field(default=None, max_length=64)

    # Diagnostic vs Authoritative distinction
    is_diagnostic: bool = Field(default=False)
    diagnostic_status: Optional[str] = Field(default=None, max_length=64)
    diagnostic_outcome: Optional[str] = Field(default=None, max_length=64)

    # Resulting feedback event
    feedback_event_id: Optional[str] = Field(default=None, max_length=128)
    feedback_event_fingerprint: Optional[str] = Field(default=None, max_length=128)

    # Idempotency
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    # Trace metadata
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    @field_validator("feedback_id")
    @classmethod
    def validate_f_id(cls, v: str) -> str:
        return validate_identifier(v, "feedback_id")
