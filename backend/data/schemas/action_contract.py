# backend/data/schemas/action_contract.py
"""
SageCommand V3 — Structured Action API Canonical Domain Models
Defines typed, versioned Action schemas, lifecycle statuses, target models,
action-specific parameters, anti-SQL smuggling validation, evidence, provenance,
and simulation preview structures.
"""

import re
import uuid
import hashlib
import json
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =====================================================================
# 1. CENTRALIZED ENUMS
# =====================================================================

class ActionStatus(str, Enum):
    """Lifecycle state machine for a structured action."""
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    POLICY_REVIEW = "POLICY_REVIEW"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    READY = "READY"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    STALE = "STALE"


class ActionType(str, Enum):
    """Officially supported industrial action types."""
    ADJUST_REORDER_POINT = "ADJUST_REORDER_POINT"
    REORDER_INVENTORY = "REORDER_INVENTORY"
    MOVE_INVENTORY = "MOVE_INVENTORY"
    SCHEDULE_MAINTENANCE = "SCHEDULE_MAINTENANCE"
    CREATE_MAINTENANCE_WORK_ORDER = "CREATE_MAINTENANCE_WORK_ORDER"
    RESCHEDULE_PRODUCTION = "RESCHEDULE_PRODUCTION"
    CHANGE_PRODUCTION_PLAN = "CHANGE_PRODUCTION_PLAN"
    UPDATE_SUPPLIER_ORDER = "UPDATE_SUPPLIER_ORDER"
    ESCALATE_INCIDENT = "ESCALATE_INCIDENT"
    NOTIFY_STAKEHOLDER = "NOTIFY_STAKEHOLDER"
    UPDATE_SLA_PRIORITY = "UPDATE_SLA_PRIORITY"


class ResourceType(str, Enum):
    """Permitted industrial target resource classes."""
    PLANT = "PLANT"
    PRODUCTION_LINE = "PRODUCTION_LINE"
    MACHINE = "MACHINE"
    SENSOR = "SENSOR"
    PRODUCT = "PRODUCT"
    SKU = "SKU"
    INVENTORY_ITEM = "INVENTORY_ITEM"
    WAREHOUSE = "WAREHOUSE"
    SUPPLIER = "SUPPLIER"
    CUSTOMER = "CUSTOMER"
    ORDER = "ORDER"
    MAINTENANCE_RECORD = "MAINTENANCE_RECORD"
    INCIDENT = "INCIDENT"
    SLA = "SLA"
    PRODUCTION_PLAN = "PRODUCTION_PLAN"


class RiskLevel(str, Enum):
    """Operational risk classifications."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RollbackCapability(str, Enum):
    """Reversibility boundaries of an action."""
    REVERSIBLE = "REVERSIBLE"
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    """Class of supporting telemetry or observation."""
    DATABASE_QUERY = "DATABASE_QUERY"
    SENSOR_EVENT = "SENSOR_EVENT"
    TELEMETRY_ANOMALY = "TELEMETRY_ANOMALY"
    MARKET_REPORT = "MARKET_REPORT"
    EXTERNAL_API = "EXTERNAL_API"
    USER_OBSERVATION = "USER_OBSERVATION"


class EvidenceVerification(str, Enum):
    """Verification provenance of evidence."""
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    GENERATED = "GENERATED"
    USER_PROVIDED = "USER_PROVIDED"
    SIMULATED = "SIMULATED"


class ActionErrorCode(str, Enum):
    """Canonical error codes for Structured Action API."""
    ACTION_NOT_FOUND = "ACTION_NOT_FOUND"
    ACTION_TYPE_UNSUPPORTED = "ACTION_TYPE_UNSUPPORTED"
    ACTION_VERSION_UNSUPPORTED = "ACTION_VERSION_UNSUPPORTED"
    ACTION_SCHEMA_INVALID = "ACTION_SCHEMA_INVALID"
    INVALID_ACTION_SCHEMA = "INVALID_ACTION_SCHEMA"
    ACTION_TARGET_INVALID = "ACTION_TARGET_INVALID"
    INVALID_TARGET_RESOURCE = "INVALID_TARGET_RESOURCE"
    ACTION_TARGET_NOT_FOUND = "ACTION_TARGET_NOT_FOUND"
    ACTION_SCOPE_DENIED = "ACTION_SCOPE_DENIED"
    CROSS_TENANT_VIOLATION = "CROSS_TENANT_VIOLATION"
    ACTION_PARAMETER_INVALID = "ACTION_PARAMETER_INVALID"
    DOMAIN_VALIDATION_FAILED = "DOMAIN_VALIDATION_FAILED"
    ACTION_CAPABILITY_DENIED = "ACTION_CAPABILITY_DENIED"
    ACTION_DATA_MODE_INVALID = "ACTION_DATA_MODE_INVALID"
    ACTION_RISK_REQUIRES_REVIEW = "ACTION_RISK_REQUIRES_REVIEW"
    ACTION_NOT_CANCELLABLE = "ACTION_NOT_CANCELLABLE"
    ACTION_IMMUTABLE = "ACTION_IMMUTABLE"
    ACTION_ALREADY_EXISTS = "ACTION_ALREADY_EXISTS"
    ACTION_IDEMPOTENCY_CONFLICT = "ACTION_IDEMPOTENCY_CONFLICT"
    ACTION_SIMULATION_FAILED = "ACTION_SIMULATION_FAILED"
    ACTION_POLICY_REJECTED = "ACTION_POLICY_REJECTED"
    SQL_SMUGGLING_DETECTED = "SQL_SMUGGLING_DETECTED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# =====================================================================
# 2. ANTI-SQL SMUGGLING CHECKER
# =====================================================================

SQL_SMUGGLING_PATTERNS = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+DATABASE|DELETE\s+FROM|TRUNCATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|"
    r"UPDATE\s+\w+\s+SET|UNION\s+SELECT|SELECT\s+.*\s+FROM|EXEC\s+|EXECUTE\s+|xp_cmdshell|--|;|\/\*)\b",
    re.IGNORECASE
)

PROHIBITED_PARAMETER_KEYS = {
    "sql", "raw_sql", "query", "command", "shell", "script", "javascript",
    "python", "expression", "arbitrary_payload", "payload", "cmd", "exec"
}

def assert_no_sql_smuggling(data: Any, path: str = "parameters") -> None:
    """Recursively validates that no dictionary keys or values smuggle raw SQL or script execution."""
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in PROHIBITED_PARAMETER_KEYS:
                raise ValueError(f"SQL_SMUGGLING_DETECTED: Prohibited execution parameter key '{k}' detected at '{path}'.")
            if SQL_SMUGGLING_PATTERNS.search(str(k)):
                raise ValueError(f"SQL_SMUGGLING_DETECTED: Malicious SQL pattern detected in parameter key '{k}' at '{path}'.")
            assert_no_sql_smuggling(v, f"{path}.{k}")
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            assert_no_sql_smuggling(item, f"{path}[{idx}]")
    elif isinstance(data, str):
        if SQL_SMUGGLING_PATTERNS.search(data):
            raise ValueError(f"SQL_SMUGGLING_DETECTED: Malicious executable SQL syntax detected in parameter value at '{path}'.")


# =====================================================================
# 3. ACTION TARGET MODEL
# =====================================================================

class ActionTarget(BaseModel):
    """Identifies the explicit industrial target an action intends to affect."""
    model_config = ConfigDict(extra="ignore")

    resource_type: ResourceType = Field(..., description="Class of target industrial resource")
    resource_id: str = Field(..., min_length=1, max_length=128, description="Target resource unique identifier")
    plant_id: Optional[str] = Field(default="plant_001", max_length=64, description="Target operational plant")
    tenant_id: Optional[str] = Field(default=None)
    workspace_id: Optional[str] = Field(default=None)

    @field_validator("resource_id", "plant_id")
    @classmethod
    def validate_safe_identifier(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^[\w\.\-\:]+$", v):
                raise ValueError(f"Invalid identifier '{v}': must contain only alphanumeric characters, dots, dashes, or colons.")
            if SQL_SMUGGLING_PATTERNS.search(v):
                raise ValueError(f"SQL_SMUGGLING_DETECTED in identifier '{v}'.")
        return v


# =====================================================================
# 4. ACTION-SPECIFIC PARAMETER SCHEMAS
# =====================================================================

class BaseActionParameters(BaseModel):
    """Base parameter model enforcing anti-SQL smuggling."""
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def check_anti_smuggling(self):
        assert_no_sql_smuggling(self.model_dump())
        return self


class AdjustReorderPointParameters(BaseActionParameters):
    new_reorder_point: int = Field(..., ge=0, le=10000000, description="New inventory reorder threshold (units)")
    sku_id: Optional[str] = Field(default=None, max_length=128)
    reason_code: Optional[str] = Field(default="PREDICTED_STOCKOUT", max_length=64)
    effective_date: Optional[str] = Field(default=None)


class ReorderInventoryParameters(BaseActionParameters):
    quantity: int = Field(..., ge=1, le=5000000, description="Purchase/restock order quantity")
    sku_id: Optional[str] = Field(default=None, max_length=128)
    supplier_id: Optional[str] = Field(default="SUPPLIER_DEFAULT", max_length=64)
    priority: Optional[str] = Field(default="STANDARD", max_length=32)
    required_by: Optional[str] = Field(default=None, description="ISO 8601 target delivery deadline")


class MoveInventoryParameters(BaseActionParameters):
    quantity: int = Field(..., ge=1, le=1000000, description="Units to transfer")
    from_warehouse: str = Field(..., min_length=1, max_length=64)
    to_warehouse: str = Field(..., min_length=1, max_length=64)
    sku_id: Optional[str] = Field(default=None, max_length=128)


class ScheduleMaintenanceParameters(BaseActionParameters):
    machine_id: str = Field(..., min_length=1, max_length=64)
    scheduled_start: str = Field(..., description="ISO 8601 maintenance window start")
    estimated_duration_minutes: int = Field(..., ge=1, le=43200, description="Planned duration in minutes (max 30 days)")
    maintenance_type: str = Field(default="PREVENTIVE", max_length=64)


class CreateMaintenanceWorkOrderParameters(BaseActionParameters):
    machine_id: str = Field(..., min_length=1, max_length=64)
    issue_description: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, max_length=256)
    severity: Optional[str] = Field(default="HIGH", max_length=32)
    priority: str = Field(default="HIGH", max_length=32)


class RescheduleProductionParameters(BaseActionParameters):
    production_line: str = Field(..., min_length=1, max_length=64)
    shift_hours: int = Field(..., ge=1, le=24, description="Shift extension or reduction in hours")
    reason: str = Field(..., min_length=3, max_length=256)


class ChangeProductionPlanParameters(BaseActionParameters):
    production_plan_id: str = Field(..., min_length=1, max_length=64)
    target_units: int = Field(..., ge=0, le=10000000)


class UpdateSupplierOrderParameters(BaseActionParameters):
    order_id: str = Field(..., min_length=1, max_length=64)
    new_delivery_date: str = Field(..., description="ISO 8601 adjusted delivery date")


class EscalateIncidentParameters(BaseActionParameters):
    incident_id: str = Field(..., min_length=1, max_length=64)
    escalation_level: str = Field(default="LEVEL_2", max_length=32)


class NotifyStakeholderParameters(BaseActionParameters):
    recipient_role: str = Field(..., min_length=2, max_length=64)
    message: str = Field(..., min_length=5, max_length=500)


class UpdateSLAPriorityParameters(BaseActionParameters):
    sla_id: str = Field(..., min_length=1, max_length=64)
    new_priority: str = Field(default="P1", max_length=16)


# Parameter mapping table
ACTION_PARAMETER_SCHEMAS: Dict[ActionType, type[BaseActionParameters]] = {
    ActionType.ADJUST_REORDER_POINT: AdjustReorderPointParameters,
    ActionType.REORDER_INVENTORY: ReorderInventoryParameters,
    ActionType.MOVE_INVENTORY: MoveInventoryParameters,
    ActionType.SCHEDULE_MAINTENANCE: ScheduleMaintenanceParameters,
    ActionType.CREATE_MAINTENANCE_WORK_ORDER: CreateMaintenanceWorkOrderParameters,
    ActionType.RESCHEDULE_PRODUCTION: RescheduleProductionParameters,
    ActionType.CHANGE_PRODUCTION_PLAN: ChangeProductionPlanParameters,
    ActionType.UPDATE_SUPPLIER_ORDER: UpdateSupplierOrderParameters,
    ActionType.ESCALATE_INCIDENT: EscalateIncidentParameters,
    ActionType.NOTIFY_STAKEHOLDER: NotifyStakeholderParameters,
    ActionType.UPDATE_SLA_PRIORITY: UpdateSLAPriorityParameters,
}


# =====================================================================
# 5. REASON, EVIDENCE, PROVENANCE & COST MODELS
# =====================================================================

class ActionReason(BaseModel):
    """Structured rationale for proposing an operational action."""
    model_config = ConfigDict(extra="ignore")

    reason_code: str = Field(..., min_length=2, max_length=64, description="Standardized operational reason code")
    summary: str = Field(..., min_length=5, max_length=500, description="Human-readable justification summary")
    justification: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("reason_code", "summary")
    @classmethod
    def check_sql(cls, v: str) -> str:
        if SQL_SMUGGLING_PATTERNS.search(v):
            raise ValueError(f"SQL_SMUGGLING_DETECTED in action reason: '{v}'.")
        return v


class ActionEvidence(BaseModel):
    """Reference to verified or inferred operational telemetry."""
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:8]}")
    type: EvidenceType = Field(..., description="Telemetry source class")
    source: Optional[str] = Field(default=None, max_length=128)
    reference: str = Field(..., max_length=128, description="Identifier of anomaly, event, or query reference")
    verification: EvidenceVerification = Field(default=EvidenceVerification.VERIFIED)


class CostEstimate(BaseModel):
    """Financial impact representation with confidence weighting."""
    model_config = ConfigDict(extra="forbid")

    value: Optional[float] = Field(default=None, ge=0.0, description="Estimated financial expenditure")
    currency: str = Field(default="USD", max_length=3)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ActionProvenance(BaseModel):
    """Audit origin tracing which agent, model, and request generated the action."""
    model_config = ConfigDict(extra="ignore")

    source: str = Field(default="AI_AGENT", description="Origin: AI_AGENT, HUMAN_OPERATOR, SIMULATOR, API")
    agent: Optional[str] = Field(default="evaluator")
    model: Optional[str] = Field(default="llama-3.3-70b-versatile")
    model_version: Optional[str] = Field(default="v3")
    prompt_version: Optional[str] = Field(default="v3")
    request_id: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=lambda: "2026-09-14T12:00:00Z")
    data_mode: str = Field(default="REAL")


# =====================================================================
# 6. CANONICAL ACTION DOMAIN MODEL
# =====================================================================

class Action(BaseModel):
    """
    Canonical Structured Action Resource.
    Represents an immutable, auditable operational proposal.
    """
    model_config = ConfigDict(extra="ignore")

    action_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:10]}")
    action_type: ActionType = Field(..., description="Class of operational action")
    version: str = Field(default="1.0", description="Action schema semantic version")

    tenant_id: str = Field(..., description="Scoped tenant organization")
    workspace_id: str = Field(..., description="Scoped workspace partition")
    session_id: str = Field(..., description="Scoped active session")

    mission_id: Optional[str] = Field(default=None)
    incident_id: Optional[str] = Field(default=None)

    target: ActionTarget = Field(..., description="Target industrial resource")
    parameters: Dict[str, Any] = Field(..., description="Validated action parameters")
    reason: ActionReason = Field(..., description="Operational rationale")
    evidence: List[ActionEvidence] = Field(default_factory=list, description="Referenced telemetry evidence")

    model_estimated_risk: Optional[RiskLevel] = Field(default=None, description="LLM subjective risk estimation")
    system_risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM, description="Authoritative deterministic risk classification")

    estimated_cost: Optional[CostEstimate] = Field(default=None)
    estimated_duration_minutes: Optional[int] = Field(default=None, ge=1)

    requires_approval: bool = Field(default=True, description="Enforced human approval requirement")
    rollback_supported: RollbackCapability = Field(default=RollbackCapability.UNKNOWN)
    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")

    requested_by: str = Field(default="user_dev_01")
    created_at: str = Field(default_factory=lambda: "2026-09-14T12:00:00Z")
    status: ActionStatus = Field(default=ActionStatus.PROPOSED)
    provenance: Optional[ActionProvenance] = Field(default=None)
    idempotency_key: Optional[str] = Field(default=None)
    action_hash: Optional[str] = Field(default=None, description="Cryptographic integrity SHA-256 fingerprint")

    @model_validator(mode="after")
    def ensure_hash(self):
        if not self.action_hash:
            self.action_hash = self.compute_hash()
        return self

    def compute_hash(self) -> str:
        """Calculates canonical SHA-256 fingerprint over core immutable action fields."""
        canonical_dict = {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "version": self.version,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "target": self.target.model_dump(),
            "parameters": self.parameters,
            "reason": self.reason.model_dump(),
            "data_mode": self.data_mode
        }
        encoded = json.dumps(canonical_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def generate_human_preview(self) -> str:
        """Generates standard deterministic human-readable preview."""
        cost_str = f"${self.estimated_cost.value:,.2f} {self.estimated_cost.currency}" if (self.estimated_cost and self.estimated_cost.value is not None) else "None / Undetermined"
        duration_str = f"{self.estimated_duration_minutes} minutes" if self.estimated_duration_minutes else "Immediate / N/A"
        params_str = ", ".join([f"{k}={v}" for k, v in self.parameters.items()])

        return (
            f"Action: {self.action_type.value} (v{self.version})\n"
            f"Target: {self.target.resource_type.value} [{self.target.resource_id}] @ {self.target.plant_id}\n"
            f"Parameters: {params_str}\n"
            f"Reason: {self.reason.summary} [{self.reason.reason_code}]\n"
            f"Risk Level: {self.system_risk_level.value} (Deterministic)\n"
            f"Estimated Cost: {cost_str}\n"
            f"Estimated Duration: {duration_str}\n"
            f"Approval Required: {'YES' if self.requires_approval else 'NO'}\n"
            f"Data Mode: {self.data_mode}\n"
            f"Status: {self.status.value}"
        )


# =====================================================================
# 7. SIMULATION & VALIDATION MODELS
# =====================================================================

class ActionSimulationEffect(BaseModel):
    resource: str
    field: str
    before: Any
    after: Any


class ActionSimulationResult(BaseModel):
    simulation_id: str = Field(default_factory=lambda: f"sim_{uuid.uuid4().hex[:8]}")
    action_id: str
    data_mode: str = "SIMULATION"
    expected_effects: List[ActionSimulationEffect]
    estimated_impact: Dict[str, Any]


class ActionValidationCheck(BaseModel):
    name: str
    status: str = Field(..., description="PASS | FAIL")
    message: Optional[str] = None


# =====================================================================
# 8. REST API REQUEST & RESPONSE ENVELOPES
# =====================================================================

class CreateActionRequest(BaseModel):
    """Payload to propose a new structured action."""
    action_type: ActionType
    version: str = Field(default="1.0")
    target: ActionTarget
    parameters: Dict[str, Any]
    reason: ActionReason
    evidence: List[ActionEvidence] = Field(default_factory=list)
    data_mode: str = Field(default="REAL")
    mission_id: Optional[str] = None
    incident_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    model_estimated_risk: Optional[RiskLevel] = None
    estimated_cost: Optional[CostEstimate] = None
    estimated_duration_minutes: Optional[int] = None


class CreateActionResponse(BaseModel):
    success: bool = True
    request_id: str
    action: Action


class ActionDetailResponse(BaseModel):
    success: bool = True
    request_id: str
    action: Action
    preview: str


class ActionListResponse(BaseModel):
    success: bool = True
    request_id: str
    actions: List[Action]
    total: int


class ActionValidationResponse(BaseModel):
    success: bool = True
    request_id: str
    valid: bool
    checks: List[ActionValidationCheck]


class ActionSimulationResponse(BaseModel):
    success: bool = True
    request_id: str
    simulation: ActionSimulationResult
    preview: str


class ActionCancellationResponse(BaseModel):
    success: bool = True
    request_id: str
    action_id: str
    status: ActionStatus
