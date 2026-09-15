# backend/data/schemas/policy_contract.py
"""
SageCommand V3 — Canonical Policy Domain Models
Defines typed, versioned Policy schemas, rule conditions, deterministic operators,
lifecycle states, approval requirements, and immutable PolicyDecision contracts with SHA-256 fingerprinting.
"""

import re
import uuid
import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =====================================================================
# 1. CENTRALIZED POLICY ENUMS
# =====================================================================

class PolicyEffect(str, Enum):
    """Deterministic policy evaluation outcome."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    HOLD = "HOLD"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class PolicyLifecycle(str, Enum):
    """Lifecycle status of a policy definition."""
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"
    INVALID = "INVALID"


class PolicyConditionCategory(str, Enum):
    """Supported deterministic condition field categories."""
    ACTION_TYPE = "ACTION_TYPE"
    ACTION_VERSION = "ACTION_VERSION"
    RISK_LEVEL = "RISK_LEVEL"
    RESOURCE_TYPE = "RESOURCE_TYPE"
    RESOURCE_ID = "RESOURCE_ID"
    PLANT = "PLANT"
    WORKSPACE = "WORKSPACE"
    TENANT = "TENANT"
    DATA_MODE = "DATA_MODE"
    ACCESS_MODE = "ACCESS_MODE"
    USER_SCOPE = "USER_SCOPE"
    MISSION = "MISSION"
    INCIDENT = "INCIDENT"
    ESTIMATED_COST = "ESTIMATED_COST"
    ESTIMATED_DURATION = "ESTIMATED_DURATION"
    TIME_WINDOW = "TIME_WINDOW"
    DAY_OF_WEEK = "DAY_OF_WEEK"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ROLLBACK_SUPPORT = "ROLLBACK_SUPPORT"
    CAPABILITY = "CAPABILITY"


class PolicyOperator(str, Enum):
    """Supported deterministic comparison operators. Zero eval() or arbitrary execution."""
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    IN = "IN"
    NOT_IN = "NOT_IN"
    GREATER_THAN = "GREATER_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN = "LESS_THAN"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    CONTAINS = "CONTAINS"
    NOT_CONTAINS = "NOT_CONTAINS"
    MATCHES_SCOPE = "MATCHES_SCOPE"
    WITHIN_TIME_WINDOW = "WITHIN_TIME_WINDOW"
    EXISTS = "EXISTS"
    NOT_EXISTS = "NOT_EXISTS"


class PolicyReasonCode(str, Enum):
    """Machine-readable policy evaluation and conflict reason codes."""
    POLICY_ALLOWED = "POLICY_ALLOWED"
    POLICY_DENIED = "POLICY_DENIED"
    POLICY_APPROVAL_REQUIRED = "POLICY_APPROVAL_REQUIRED"
    POLICY_HOLD = "POLICY_HOLD"
    POLICY_CONFLICT = "POLICY_CONFLICT"
    POLICY_UNKNOWN_RISK = "POLICY_UNKNOWN_RISK"
    POLICY_UNKNOWN_SCOPE = "POLICY_UNKNOWN_SCOPE"
    POLICY_UNKNOWN_CAPABILITY = "POLICY_UNKNOWN_CAPABILITY"
    POLICY_DATA_MODE_RESTRICTED = "POLICY_DATA_MODE_RESTRICTED"
    POLICY_COST_LIMIT_EXCEEDED = "POLICY_COST_LIMIT_EXCEEDED"
    POLICY_TIME_WINDOW_RESTRICTED = "POLICY_TIME_WINDOW_RESTRICTED"
    POLICY_ACTION_NOT_PERMITTED = "POLICY_ACTION_NOT_PERMITTED"
    POLICY_RESOURCE_RESTRICTED = "POLICY_RESOURCE_RESTRICTED"
    POLICY_EVALUATION_ERROR = "POLICY_EVALUATION_ERROR"
    NO_MATCHING_POLICY_FOUND = "NO_MATCHING_POLICY_FOUND"


# Anti-executable code / injection patterns in policy definitions
PROHIBITED_CODE_PATTERNS = re.compile(
    r"(?i)\b(eval|exec|import|__import__|compile|system|popen|subprocess|globals|locals|getattr|setattr|delattr)\b"
)


# =====================================================================
# 2. APPROVAL REQUIREMENT MODEL
# =====================================================================

class ApprovalRequirement(BaseModel):
    """Structured human-in-the-loop governance requirement."""
    model_config = ConfigDict(extra="ignore")

    required: bool = Field(default=True, description="Whether approval is required")
    approval_type: str = Field(default="SUPERVISOR", description="SUPERVISOR | MANAGER | EXECUTIVE | SAFETY_OFFICER")
    required_role: str = Field(default="manager", description="RBAC role required for authorization")
    minimum_approvers: int = Field(default=1, ge=1, description="Minimum number of approving identities")
    reason_code: str = Field(default="POLICY_APPROVAL_REQUIRED", description="Machine-readable approval code")
    reason: str = Field(..., description="Deterministic human-readable approval justification")
    risk_level: Optional[str] = Field(default=None, description="System risk level driving approval")
    policy_id: Optional[str] = Field(default=None, description="Policy triggering approval requirement")
    policy_version: Optional[str] = Field(default=None, description="Version of triggering policy")


# =====================================================================
# 3. POLICY CONDITION & RULE MODELS
# =====================================================================

class PolicyCondition(BaseModel):
    """
    Deterministic rule condition.
    Strictly evaluates a server-extracted attribute against an expected value using a typed operator.
    """
    model_config = ConfigDict(extra="ignore")

    field: PolicyConditionCategory = Field(..., description="Target attribute category")
    operator: PolicyOperator = Field(..., description="Comparison operator")
    value: Any = Field(..., description="Expected value or set of values")

    @field_validator("value")
    @classmethod
    def assert_no_executable_code(cls, v: Any) -> Any:
        if isinstance(v, str) and PROHIBITED_CODE_PATTERNS.search(v):
            raise ValueError(f"Security Policy Violation: Prohibited code pattern detected in condition value '{v}'.")
        return v


class PolicyRule(BaseModel):
    """
    Individual evaluation rule within a policy.
    Contains a set of conditions that must ALL match (AND) to trigger the rule effect.
    """
    model_config = ConfigDict(extra="ignore")

    rule_id: str = Field(default_factory=lambda: f"rule_{uuid.uuid4().hex[:8]}")
    name: str = Field(..., min_length=2, max_length=128)
    description: Optional[str] = Field(default=None, max_length=256)
    conditions: List[PolicyCondition] = Field(default_factory=list, description="All conditions must match (AND)")
    effect: PolicyEffect = Field(..., description="ALLOW | DENY | HOLD | REQUIRE_APPROVAL")
    approval_requirement: Optional[ApprovalRequirement] = Field(default=None, description="Populated when effect is REQUIRE_APPROVAL")
    reason_code: str = Field(default="POLICY_RULE_MATCHED")
    explanation: str = Field(..., description="Deterministic human explanation for why rule fired")


# =====================================================================
# 4. CANONICAL POLICY MODEL
# =====================================================================

class Policy(BaseModel):
    """
    Canonical Versioned Policy Model.
    Governs operational actions under specific scopes, priorities, and conditions.
    """
    model_config = ConfigDict(extra="ignore")

    policy_id: str = Field(..., min_length=3, max_length=64, description="Unique policy identifier")
    policy_version: str = Field(default="1.0", description="Semantic version string")
    name: str = Field(..., min_length=3, max_length=128)
    description: str = Field(..., max_length=512)
    status: PolicyLifecycle = Field(default=PolicyLifecycle.ACTIVE)
    priority: int = Field(default=50, ge=1, le=100, description="Evaluation priority (1-100, higher evaluated first)")
    scope: Dict[str, Any] = Field(default_factory=dict, description="Scope filters e.g. tenant_id, plant_id")
    rules: List[PolicyRule] = Field(default_factory=list, description="Ordered rules within this policy")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = Field(default="system")
    policy_hash: Optional[str] = Field(default=None, description="SHA-256 fingerprint over rules and configuration")

    @model_validator(mode="after")
    def ensure_hash(self):
        if not self.policy_hash:
            self.policy_hash = self.compute_hash()
        return self

    def compute_hash(self) -> str:
        """Calculates canonical SHA-256 fingerprint over core policy fields."""
        canonical_dict = {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "name": self.name,
            "status": self.status.value,
            "priority": self.priority,
            "scope": self.scope,
            "rules": [r.model_dump() for r in self.rules]
        }
        encoded = json.dumps(canonical_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


# =====================================================================
# 5. EVALUATION CONTEXT & TRACE MODELS
# =====================================================================

class PolicyEvaluationContext(BaseModel):
    """
    Authoritative server-side context for policy evaluation.
    Derived securely from the request and authenticated identity, NEVER trusted from raw client.
    """
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., description="Authenticated tenant identifier")
    workspace_id: str = Field(default="workspace_default")
    session_id: str = Field(default="session_default")
    user_id: str = Field(default="user_dev_01")
    plant_id: Optional[str] = Field(default=None)
    roles: List[str] = Field(default_factory=lambda: ["operator"])
    permissions: List[str] = Field(default_factory=lambda: ["read"])
    current_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    timezone: str = Field(default="UTC")
    day_of_week: Optional[str] = Field(default=None)
    resource_metadata: Dict[str, Any] = Field(default_factory=dict)
    data_mode: str = Field(default="REAL", description="REAL | SIMULATION | HYBRID")
    mission_context: Optional[Dict[str, Any]] = None
    incident_context: Optional[Dict[str, Any]] = None


class PolicyEvaluationTrace(BaseModel):
    """Detailed explainable trace of the policy evaluation process."""
    model_config = ConfigDict(extra="ignore")

    policies_evaluated: int = 0
    policies_matched: int = 0
    policies_unmatched: int = 0
    blocking_rules: int = 0
    approval_rules: int = 0
    evaluated_policy_ids: List[str] = Field(default_factory=list)
    matched_rule_ids: List[str] = Field(default_factory=list)
    conflicts_detected: List[str] = Field(default_factory=list)
    final_decision: PolicyEffect = PolicyEffect.HOLD


# =====================================================================
# 6. CANONICAL POLICY DECISION MODEL
# =====================================================================

class PolicyDecision(BaseModel):
    """
    Canonical Deterministic Policy Decision.
    Represents an immutable, auditable governance result for a structured action proposal.
    """
    model_config = ConfigDict(extra="ignore")

    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:10]}")
    action_id: str = Field(..., description="Target structured action ID")
    decision: PolicyEffect = Field(..., description="ALLOW | DENY | HOLD | REQUIRE_APPROVAL")
    policy_id: Optional[str] = Field(default=None, description="Primary decisive policy ID")
    policy_version: Optional[str] = Field(default=None, description="Decisive policy version")
    tenant_id: str = Field(..., description="Authoritative tenant isolation scope")
    workspace_id: str = Field(default="workspace_default")
    session_id: str = Field(default="session_default")
    plant_id: Optional[str] = Field(default=None)
    reason_codes: List[str] = Field(default_factory=list, description="Machine-readable decision codes")
    explanation: str = Field(..., description="Deterministic human-readable explanation")
    matched_rules: List[Dict[str, Any]] = Field(default_factory=list)
    unmatched_required_rules: List[str] = Field(default_factory=list)
    risk_level: str = Field(default="UNKNOWN", description="Authoritative system risk classification")
    requires_approval: bool = Field(default=False)
    approval_requirement: Optional[ApprovalRequirement] = Field(default=None)
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    request_id: Optional[str] = Field(default=None)
    trace_id: Optional[str] = Field(default=None)
    data_mode: str = Field(default="REAL")
    provenance: Optional[Dict[str, Any]] = None
    evaluation_trace: Optional[Dict[str, Any]] = None
    decision_hash: Optional[str] = Field(default=None, description="SHA-256 fingerprint for tamper detection")

    @model_validator(mode="after")
    def ensure_decision_hash(self):
        if not self.decision_hash:
            self.decision_hash = self.compute_hash()
        return self

    def compute_hash(self) -> str:
        """Calculates canonical SHA-256 fingerprint over core decision fields."""
        canonical_dict = {
            "decision_id": self.decision_id,
            "action_id": self.action_id,
            "decision": self.decision.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "tenant_id": self.tenant_id,
            "reason_codes": self.reason_codes,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "data_mode": self.data_mode
        }
        encoded = json.dumps(canonical_dict, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


# =====================================================================
# 7. REST API REQUEST & RESPONSE ENVELOPES
# =====================================================================

class EvaluatePolicyRequest(BaseModel):
    """Payload to evaluate an existing action against system policy."""
    action_id: str = Field(..., description="ID of previously validated structured action")
    policy_ids: Optional[List[str]] = Field(default=None, description="Optional specific policy IDs to evaluate")


class SimulatePolicyRequest(BaseModel):
    """Dry-run simulation request. Evaluates an action without state mutation."""
    action: Dict[str, Any] = Field(..., description="Action payload or canonical action dict")
    hypothetical_policies: Optional[List[Policy]] = Field(default=None, description="Hypothetical policies to test against")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional simulation context overrides")


class PolicyResponse(BaseModel):
    success: bool = True
    request_id: str
    policy: Policy


class PolicyListResponse(BaseModel):
    success: bool = True
    request_id: str
    policies: List[Policy]
    total: int


class PolicyDecisionResponse(BaseModel):
    success: bool = True
    request_id: str
    decision: PolicyDecision


class PolicySimulationResponse(BaseModel):
    success: bool = True
    request_id: str
    decision: PolicyDecision
    simulation: bool = True
