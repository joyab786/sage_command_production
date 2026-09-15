# backend/data/schemas/transaction_contract.py
"""
SageCommand V3 — Transaction & Rollback Canonical Domain Contracts
Defines typed, deterministic schemas for transactions, transaction plans,
preconditions, invariants, affected resources, rollback plans, capabilities,
concurrency metadata, state machines, and API envelopes.
"""

import uuid
import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator


# =====================================================================
# 1. CENTRALIZED TRANSACTION ENUMS
# =====================================================================

class TransactionStatus(str, Enum):
    """
    Deterministic lifecycle states for a transaction.
    Active in Prompt 09: PLANNED, VALIDATING, READY, AWAITING_EXECUTION, CANCELLED, EXPIRED, FAILED.
    Future execution states: EXECUTING, COMMITTING, COMMITTED, ROLLBACK_PENDING, ROLLING_BACK, ROLLED_BACK, ROLLBACK_FAILED.
    """
    PLANNED = "PLANNED"
    VALIDATING = "VALIDATING"
    READY = "READY"
    AWAITING_EXECUTION = "AWAITING_EXECUTION"
    EXECUTING = "EXECUTING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TransactionType(str, Enum):
    """Target operational domain classification of the transaction."""
    DATABASE = "DATABASE"
    EXTERNAL_SERVICE = "EXTERNAL_SERVICE"
    COMPENSATING_WORKFLOW = "COMPENSATING_WORKFLOW"
    MULTI_SYSTEM = "MULTI_SYSTEM"
    SIMULATED = "SIMULATED"


class RollbackStrategy(str, Enum):
    """Architectural rollback implementation mechanism."""
    DATABASE_ROLLBACK = "DATABASE_ROLLBACK"
    COMPENSATING_ACTION = "COMPENSATING_ACTION"
    MANUAL_RECOVERY = "MANUAL_RECOVERY"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"


class RollbackCapability(str, Enum):
    """Reversibility boundaries determined by deterministic system metadata."""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    UNKNOWN = "UNKNOWN"


class ConflictType(str, Enum):
    """Deterministic concurrency and state conflict classifications."""
    NO_CONFLICT = "NO_CONFLICT"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    STALE_STATE = "STALE_STATE"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    POLICY_CHANGED = "POLICY_CHANGED"
    AUTHORIZATION_CHANGED = "AUTHORIZATION_CHANGED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class PreconditionType(str, Enum):
    """Deterministic precondition domain types."""
    INVENTORY_LEVEL = "INVENTORY_LEVEL"
    MACHINE_STATUS = "MACHINE_STATUS"
    LINE_STATUS = "LINE_STATUS"
    ORDER_STATUS = "ORDER_STATUS"
    VERSION_CHECK = "VERSION_CHECK"
    CUSTOM = "CUSTOM"


class InvariantType(str, Enum):
    """Business invariants that must remain true across operational boundaries."""
    NON_NEGATIVE_QUANTITY = "NON_NEGATIVE_QUANTITY"
    VALID_DATE_RANGE = "VALID_DATE_RANGE"
    NON_NEGATIVE_COST = "NON_NEGATIVE_COST"
    STATUS_TRANSITION = "STATUS_TRANSITION"
    CUSTOM = "CUSTOM"


# =====================================================================
# 2. PRECONDITIONS, INVARIANTS, & RESOURCES
# =====================================================================

class TransactionPrecondition(BaseModel):
    """Deterministic precondition required prior to transaction execution."""
    model_config = ConfigDict(extra="ignore")

    precondition_id: str = Field(default_factory=lambda: f"prec_{uuid.uuid4().hex[:8]}")
    precondition_type: PreconditionType = Field(..., description="Classification of precondition")
    field: str = Field(..., description="Target property or sensor being evaluated")
    operator: str = Field(..., description="Comparison operator: ==, !=, >=, <=, >, <, in")
    expected_value: Any = Field(..., description="Required state value")
    actual_value: Optional[Any] = Field(default=None, description="Observed state value during validation")
    is_satisfied: bool = Field(default=False, description="Evaluation outcome")
    failure_message: Optional[str] = Field(default=None)


class TransactionInvariant(BaseModel):
    """Typed business invariant rule that must be preserved."""
    model_config = ConfigDict(extra="ignore")

    invariant_id: str = Field(default_factory=lambda: f"inv_{uuid.uuid4().hex[:8]}")
    invariant_type: InvariantType = Field(..., description="Classification of invariant")
    description: str = Field(..., description="Human-readable description of invariant")
    rule_expression: str = Field(..., description="Deterministic declarative expression")
    is_enforced: bool = Field(default=True)


class AffectedResource(BaseModel):
    """Explicit declaration of an industrial resource affected by the transaction."""
    model_config = ConfigDict(extra="ignore")

    resource_type: str = Field(..., description="MACHINE, INVENTORY_ITEM, PRODUCTION_LINE, WAREHOUSE, etc.")
    resource_id: str = Field(..., description="Canonical resource identifier")
    plant_id: Optional[str] = Field(default=None, description="Physical plant boundary")
    current_version: Optional[int] = Field(default=None, description="Observed state version")
    expected_version: Optional[int] = Field(default=None, description="Expected state version for optimistic concurrency")
    action_type: Optional[str] = Field(default=None, description="Intended operation on resource")


class TransactionSnapshot(BaseModel):
    """Bounded snapshot of relevant pre-action state for recovery analysis."""
    model_config = ConfigDict(extra="ignore")

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}")
    resource_id: str = Field(..., description="Target resource")
    observed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = Field(..., description="DATABASE, SENSOR_TELEMETRY, MES, ERP")
    connection_id: Optional[str] = Field(default=None)
    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")
    state_version: Optional[int] = Field(default=1)
    state_data: Dict[str, Any] = Field(default_factory=dict, description="Bounded state properties")


class TransactionStep(BaseModel):
    """Typed step in a structured operational sequence."""
    model_config = ConfigDict(extra="ignore")

    step_id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    sequence: int = Field(..., ge=1)
    action_reference: str = Field(..., description="Action ID or typed sub-action")
    preconditions: List[TransactionPrecondition] = Field(default_factory=list)
    expected_result: Dict[str, Any] = Field(default_factory=dict)
    rollback_reference: Optional[str] = Field(default=None)
    status: str = Field(default="PENDING")


# =====================================================================
# 3. ROLLBACK PLAN
# =====================================================================

class RollbackPlan(BaseModel):
    """
    Deterministic Rollback Specification.
    Defines the strategy, capability, preconditions, and risk for reverting a transaction.
    """
    model_config = ConfigDict(extra="ignore")

    rollback_plan_id: str = Field(default_factory=lambda: f"rbp_{uuid.uuid4().hex[:10]}")
    transaction_id: Optional[str] = Field(default=None)
    strategy: RollbackStrategy = Field(..., description="DATABASE_ROLLBACK, COMPENSATING_ACTION, MANUAL_RECOVERY, NOT_SUPPORTED")
    capability: RollbackCapability = Field(default=RollbackCapability.UNKNOWN)
    steps: List[Dict[str, Any]] = Field(default_factory=list, description="Ordered compensation or rollback steps")
    preconditions: List[TransactionPrecondition] = Field(default_factory=list, description="Preconditions required before rollback")
    limitations: List[str] = Field(default_factory=list, description="Known operational or temporal limitations")
    estimated_duration_seconds: Optional[int] = Field(default=None)
    risk_level: str = Field(default="MEDIUM", description="LOW | MEDIUM | HIGH | CRITICAL")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provenance: Optional[Dict[str, Any]] = None


# =====================================================================
# 4. TRANSACTION PLAN & TRANSACTION DOMAIN MODELS
# =====================================================================

class TransactionPlan(BaseModel):
    """
    Authoritative Deterministic Transaction Plan.
    Describes 'what would need to happen' without executing.
    Maintains: side_effects = False, execution_permitted = False in Prompt 09.
    """
    model_config = ConfigDict(extra="ignore")

    transaction_plan_id: str = Field(default_factory=lambda: f"txp_{uuid.uuid4().hex[:10]}")
    transaction_plan_version: int = Field(default=1, ge=1)

    action_id: str = Field(..., description="Governed structured action identifier")
    action_type: str = Field(..., description="ActionType enum string")
    action_version: str = Field(default="1.0")

    tenant_id: str = Field(..., description="Scoped tenant")
    workspace_id: str = Field(default="workspace_default")
    session_id: str = Field(default="session_default")
    plant_id: Optional[str] = Field(default=None)

    target: Dict[str, Any] = Field(..., description="ActionTarget dictionary")
    parameters: Dict[str, Any] = Field(..., description="Validated action parameters")

    preconditions: List[TransactionPrecondition] = Field(default_factory=list)
    invariants: List[TransactionInvariant] = Field(default_factory=list)
    affected_resources: List[AffectedResource] = Field(default_factory=list)
    expected_changes: Dict[str, Any] = Field(default_factory=dict)

    rollback_plan: RollbackPlan = Field(..., description="Deterministic rollback specification")

    risk_level: str = Field(default="MEDIUM", description="System authoritative risk level")
    system_risk_level: str = Field(default="MEDIUM")

    estimated_cost: Optional[Dict[str, Any]] = None
    estimated_duration_seconds: Optional[int] = Field(default=None)

    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")
    access_mode: str = Field(default="READ_WRITE")

    idempotency_key: Optional[str] = Field(default=None)

    requires_approval: bool = Field(default=True)
    approval_reference: Optional[str] = Field(default="NOT_AVAILABLE")

    policy_reference: Optional[Union[Dict[str, Any], str]] = Field(default=None)
    authorization_reference: Optional[Union[Dict[str, Any], str]] = Field(default=None)

    state_version: Optional[int] = Field(default=1)
    observed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = Field(..., description="ISO 8601 expiration timestamp")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    provenance: Optional[Dict[str, Any]] = None
    transaction_plan_hash: Optional[str] = Field(default=None, description="SHA-256 integrity fingerprint")

    # Invariants strictly enforced
    side_effects: bool = Field(default=False, description="Passive plan; MUST remain False in Prompt 09")
    execution_permitted: bool = Field(default=False, description="Execution boundary; MUST remain False in Prompt 09")

    @model_validator(mode="after")
    def ensure_plan_hash(self):
        if not self.transaction_plan_hash:
            self.transaction_plan_hash = self.compute_hash()
        return self

    def compute_hash(self) -> str:
        """Calculates canonical SHA-256 fingerprint over core immutable plan fields."""
        canonical_dict = {
            "transaction_plan_id": self.transaction_plan_id,
            "transaction_plan_version": self.transaction_plan_version,
            "action_id": self.action_id,
            "action_type": self.action_type,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "target": self.target,
            "parameters": self.parameters,
            "affected_resources": [r.model_dump() for r in self.affected_resources],
            "data_mode": self.data_mode,
            "expires_at": self.expires_at
        }
        encoded = json.dumps(canonical_dict, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class Transaction(BaseModel):
    """
    Canonical Transaction Domain Record.
    Maintains mutable transactional state across planning, validation, and lifecycle transitions.
    """
    model_config = ConfigDict(extra="ignore")

    transaction_id: str = Field(default_factory=lambda: f"tx_{uuid.uuid4().hex[:12]}")
    transaction_version: int = Field(default=1, ge=1)

    tenant_id: str = Field(..., description="Authoritative tenant isolation scope")
    workspace_id: str = Field(default="workspace_default")
    session_id: str = Field(default="session_default")
    plant_id: Optional[str] = Field(default=None)

    action_id: str = Field(..., description="Bound structured action ID")
    action_version: str = Field(default="1.0")
    mission_id: Optional[str] = Field(default=None)
    incident_id: Optional[str] = Field(default=None)

    status: TransactionStatus = Field(default=TransactionStatus.PLANNED)
    transaction_type: TransactionType = Field(default=TransactionType.DATABASE)

    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")
    access_mode: str = Field(default="READ_WRITE")

    plan: TransactionPlan = Field(..., description="Authoritative transaction plan")

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    expires_at: str = Field(...)

    requested_by: str = Field(default="user_dev_01")
    approved_by: Optional[str] = Field(default=None)

    idempotency_key: Optional[str] = Field(default=None)

    rollback_supported: RollbackCapability = Field(default=RollbackCapability.UNKNOWN)
    rollback_status: str = Field(default="NOT_INITIATED")

    failure_reason: Optional[str] = Field(default=None)
    failure_code: Optional[str] = Field(default=None)

    request_id: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None)

    revalidation_count: int = Field(default=0)
    last_revalidated_at: Optional[str] = Field(default=None)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =====================================================================
# 5. VALIDATION & REVALIDATION RESULT MODELS
# =====================================================================

class TransactionValidationResult(BaseModel):
    """
    Comprehensive result of transaction validation or revalidation.
    Fails closed on any ambiguity or unmet precondition.
    """
    model_config = ConfigDict(extra="ignore")

    valid: bool = Field(..., description="True only if all safety gates pass")
    status: TransactionStatus = Field(..., description="Resulting transaction status")
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable outcome codes")
    blocking_reasons: List[str] = Field(default_factory=list, description="Critical blocking reasons if invalid")
    warnings: List[str] = Field(default_factory=list, description="Advisory warnings")
    checked_preconditions: List[Dict[str, Any]] = Field(default_factory=list)
    checked_invariants: List[Dict[str, Any]] = Field(default_factory=list)
    conflict_type: ConflictType = Field(default=ConflictType.NO_CONFLICT)
    policy_reference: Optional[Dict[str, Any]] = None
    authorization_reference: Optional[Dict[str, Any]] = None
    validated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =====================================================================
# 6. API REQUEST & RESPONSE ENVELOPES
# =====================================================================

class TransactionPlanRequest(BaseModel):
    """Payload for POST /api/v3/transactions/plan."""
    action_id: str = Field(..., min_length=1, max_length=128, description="Target structured action ID")
    idempotency_key: Optional[str] = Field(default=None, max_length=128, description="Client or server idempotency key")
    ttl_seconds: Optional[int] = Field(default=None, ge=60, le=86400, description="Custom expiration TTL (1 min - 24 hrs)")
    data_mode: Optional[str] = Field(default=None, description="Explicit data mode override (cannot promote SIMULATION to REAL)")


class TransactionPlanResponse(BaseModel):
    """Response envelope for POST /api/v3/transactions/plan."""
    success: bool
    request_id: str
    transaction: Transaction
    validation: TransactionValidationResult


class TransactionDetailResponse(BaseModel):
    """Response envelope for GET /api/v3/transactions/{transaction_id}."""
    success: bool
    request_id: str
    transaction: Transaction


class TransactionListResponse(BaseModel):
    """Response envelope for GET /api/v3/transactions."""
    success: bool
    request_id: str
    transactions: List[Transaction]
    total_count: int


class TransactionValidateResponse(BaseModel):
    """Response envelope for POST /api/v3/transactions/{transaction_id}/validate."""
    success: bool
    request_id: str
    validation: TransactionValidationResult
    transaction: Transaction


class TransactionRevalidateResponse(BaseModel):
    """Response envelope for POST /api/v3/transactions/{transaction_id}/revalidate."""
    success: bool
    request_id: str
    revalidation_status: str
    validation: TransactionValidationResult
    transaction: Transaction


class TransactionCancelResponse(BaseModel):
    """Response envelope for POST /api/v3/transactions/{transaction_id}/cancel."""
    success: bool
    request_id: str
    message: str
    transaction: Transaction
