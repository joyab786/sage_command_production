# backend/data/schemas/autonomy_contract.py
"""
SageCommand V3 — Autonomy Levels & Guarded Delegation Foundation Domain Contracts
Prompt 38 — Defines canonical autonomy domain schemas, explicit autonomy levels,
capability registry, scoped grants, deterministic decision records, and fail-closed invariants.

Cardinal Invariants:
1. An agent's ability to reason DOES NOT grant it operational authority.
2. Autonomy is a governed, server-authoritative capability, NEVER a prompt instruction,
   LLM-generated decision, or client-asserted claim.
3. Level 4 (SUPERVISED_EXECUTION) and Level 5 (BOUNDED_AUTONOMY) are strictly DISABLED
   and NOT_IMPLEMENTED; operational execution endpoints remain non-existent.
4. Higher autonomy levels NEVER automatically inherit lower capabilities across unrestricted scopes,
   and NEVER bypass authentication, authorization, tenant/workspace isolation, or safety controls.
5. All autonomy evaluations produce tamper-evident, cryptographically hashed decisions.
"""

from enum import Enum, IntEnum
from typing import Dict, List, Optional, Any, Set
import hashlib
import json
import time
import uuid
import re
from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# 0. CONSTANTS & MANDATORY NOTICE
# =============================================================================

MANDATORY_AUTONOMY_NOTICE = (
    "AN AGENT'S ABILITY TO REASON DOES NOT GRANT IT OPERATIONAL AUTHORITY. "
    "AUTONOMY LEVELS GOVERN ANALYSIS AND PROPOSAL BOUNDARIES ONLY — NEVER CONSTITUTE "
    "DIRECT EXECUTION AUTHORITY, UNGOVERNED MACHINE CONTROL, OR AUTHORIZATION BYPASS."
)

SCHEMA_VERSION = "3.0.0"

_SECRET_PATTERNS = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[a-z][a-z0-9+.-]*:\/\/[^\/\s:@]+:[^\/\s:@]+@|"
    r"\b(bearer|token)\s+[A-Za-z0-9_\-\.]{16,}\b|"
    r"\b(password|passwd|secret_key|api_key|access_token|private_key|auth_token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{6,}[\"']?|"
    r"\bAKIA[0-9A-Z]{16}\b"
    r")"
)


def _scan_for_secrets(value: Optional[str], field_name: str) -> None:
    """Detects raw credentials, tokens, passwords, connection strings, and private keys."""
    if not value:
        return
    if _SECRET_PATTERNS.search(value):
        raise ValueError(
            f"Field '{field_name}' contains potential secret, credential, token, or connection string."
        )


# =============================================================================
# 1. CANONICAL AUTONOMY LEVELS & STATUSES
# =============================================================================

class AutonomyLevel(IntEnum):
    """
    Explicit, documented autonomy levels.
    Levels 0-3 represent governed observation, analysis, and proposal tiers.
    Levels 4-5 represent future execution tiers that are DISABLED and NOT_IMPLEMENTED.
    """
    LEVEL_0_OBSERVE = 0
    LEVEL_1_ANALYZE = 1
    LEVEL_2_RECOMMEND = 2
    LEVEL_3_PREPARE_FOR_APPROVAL = 3
    LEVEL_4_SUPERVISED_EXECUTION = 4
    LEVEL_5_BOUNDED_AUTONOMY = 5

    # Aliases matching Prompt 38 specification
    OBSERVE = 0
    ANALYZE = 1
    RECOMMEND = 2
    PREPARE_FOR_APPROVAL = 3
    SUPERVISED_EXECUTION = 4
    BOUNDED_AUTONOMY = 5

    @property
    def title(self) -> str:
        titles = {
            0: "Level 0 — OBSERVE",
            1: "Level 1 — ANALYZE",
            2: "Level 2 — RECOMMEND",
            3: "Level 3 — PREPARE_FOR_APPROVAL",
            4: "Level 4 — SUPERVISED_EXECUTION",
            5: "Level 5 — BOUNDED_AUTONOMY",
        }
        return titles[self.value]

    @property
    def is_operational(self) -> bool:
        """Only levels 0 through 3 are implemented in SageCommand V3."""
        return self.value <= 3


def _normalize_autonomy_level(v: Any) -> Any:
    if isinstance(v, str):
        clean = v.strip().upper()
        mapping = {
            "OBSERVE": AutonomyLevel.LEVEL_0_OBSERVE,
            "LEVEL_0_OBSERVE": AutonomyLevel.LEVEL_0_OBSERVE,
            "ANALYZE": AutonomyLevel.LEVEL_1_ANALYZE,
            "LEVEL_1_ANALYZE": AutonomyLevel.LEVEL_1_ANALYZE,
            "RECOMMEND": AutonomyLevel.LEVEL_2_RECOMMEND,
            "LEVEL_2_RECOMMEND": AutonomyLevel.LEVEL_2_RECOMMEND,
            "PREPARE_FOR_APPROVAL": AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
            "LEVEL_3_PREPARE_FOR_APPROVAL": AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
            "SUPERVISED_EXECUTION": AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
            "LEVEL_4_SUPERVISED_EXECUTION": AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
            "BOUNDED_AUTONOMY": AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
            "LEVEL_5_BOUNDED_AUTONOMY": AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
        }
        if clean in mapping:
            return mapping[clean]
        if clean.isdigit():
            return int(clean)
    return v


class AutonomyLevelAvailability(str, Enum):
    """Implementation and runtime availability of an autonomy level."""
    AVAILABLE = "AVAILABLE"
    RESTRICTED = "RESTRICTED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    DISABLED = "DISABLED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class AutonomyLevelMetadata(BaseModel):
    level: AutonomyLevel
    name: str
    title: str
    status: str
    availability: AutonomyLevelAvailability
    description: str
    is_operational: bool
    is_executable: bool = False


AUTONOMY_LEVEL_METADATA: Dict[AutonomyLevel, AutonomyLevelMetadata] = {
    AutonomyLevel.LEVEL_0_OBSERVE: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_0_OBSERVE,
        name="LEVEL_0_OBSERVE",
        title="Level 0 — OBSERVE",
        status="AVAILABLE",
        availability=AutonomyLevelAvailability.AVAILABLE,
        description="View authorized system state, read telemetry, inspect metadata, receive events.",
        is_operational=True,
        is_executable=False,
    ),
    AutonomyLevel.LEVEL_1_ANALYZE: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_1_ANALYZE,
        name="LEVEL_1_ANALYZE",
        title="Level 1 — ANALYZE",
        status="AVAILABLE",
        availability=AutonomyLevelAvailability.AVAILABLE,
        description="Analyze observations, correlate evidence, identify anomalies, estimate uncertainty.",
        is_operational=True,
        is_executable=False,
    ),
    AutonomyLevel.LEVEL_2_RECOMMEND: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_2_RECOMMEND,
        name="LEVEL_2_RECOMMEND",
        title="Level 2 — RECOMMEND",
        status="AVAILABLE",
        availability=AutonomyLevelAvailability.AVAILABLE,
        description="Generate recommendations, identify risks, propose structured actions and mission drafts.",
        is_operational=True,
        is_executable=False,
    ),
    AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
        name="LEVEL_3_PREPARE_FOR_APPROVAL",
        title="Level 3 — PREPARE_FOR_APPROVAL",
        status="AVAILABLE",
        availability=AutonomyLevelAvailability.AVAILABLE,
        description="Validate action proposals, prepare reviewable preview packages, submit for HITL review.",
        is_operational=True,
        is_executable=False,
    ),
    AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
        name="LEVEL_4_SUPERVISED_EXECUTION",
        title="Level 4 — SUPERVISED_EXECUTION",
        status="DISABLED",
        availability=AutonomyLevelAvailability.NOT_IMPLEMENTED,
        description="Supervised operational execution gateway — DISABLED AND NOT IMPLEMENTED.",
        is_operational=False,
        is_executable=False,
    ),
    AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY: AutonomyLevelMetadata(
        level=AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
        name="LEVEL_5_BOUNDED_AUTONOMY",
        title="Level 5 — BOUNDED_AUTONOMY",
        status="DISABLED",
        availability=AutonomyLevelAvailability.NOT_IMPLEMENTED,
        description="Autonomous bounded closed-loop operational control — DISABLED AND NOT IMPLEMENTED.",
        is_operational=False,
        is_executable=False,
    ),
}


class AutonomyGrantStatus(str, Enum):
    """Deterministic lifecycle state machine for an autonomy grant."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SubjectType(str, Enum):
    """Permitted entity types capable of receiving an autonomy grant."""
    AGENT = "AGENT"
    MISSION = "MISSION"
    USER = "USER"
    WORKFLOW = "WORKFLOW"


class AutonomyDecisionEffect(str, Enum):
    """Deterministic decision effect of an autonomy capability evaluation."""
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class AutonomyReasonCode(str, Enum):
    """Machine-readable, safe reason codes for autonomy evaluations."""
    ALLOWED = "ALLOWED"
    AUTONOMY_GRANT_NOT_FOUND = "AUTONOMY_GRANT_NOT_FOUND"
    AUTONOMY_GRANT_EXPIRED = "AUTONOMY_GRANT_EXPIRED"
    AUTONOMY_GRANT_REVOKED = "AUTONOMY_GRANT_REVOKED"
    AUTONOMY_GRANT_SUSPENDED = "AUTONOMY_GRANT_SUSPENDED"
    AUTONOMY_LEVEL_INSUFFICIENT = "AUTONOMY_LEVEL_INSUFFICIENT"
    CAPABILITY_NOT_GRANTED = "CAPABILITY_NOT_GRANTED"
    CAPABILITY_RESTRICTED = "CAPABILITY_RESTRICTED"
    CAPABILITY_NOT_IMPLEMENTED = "CAPABILITY_NOT_IMPLEMENTED"
    CAPABILITY_UNKNOWN = "CAPABILITY_UNKNOWN"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    WORKSPACE_MISMATCH = "WORKSPACE_MISMATCH"
    PLANT_SCOPE_DENIED = "PLANT_SCOPE_DENIED"
    SESSION_MISMATCH = "SESSION_MISMATCH"
    DATA_MODE_MISMATCH = "DATA_MODE_MISMATCH"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    POLICY_REVIEW_REQUIRED = "POLICY_REVIEW_REQUIRED"
    RISK_UNKNOWN = "RISK_UNKNOWN"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    SEPARATION_OF_DUTIES_VIOLATION = "SEPARATION_OF_DUTIES_VIOLATION"
    CLEARANCE_LEVEL_INSUFFICIENT = "CLEARANCE_LEVEL_INSUFFICIENT"
    IDENTITY_NOT_ACTIVE = "IDENTITY_NOT_ACTIVE"
    STALE_REVISION = "STALE_REVISION"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    EVALUATION_ERROR = "EVALUATION_ERROR"


# =============================================================================
# 2. CAPABILITY REGISTRY SCHEMA & CANONICAL CAPABILITIES
# =============================================================================

class AutonomyCapabilityDefinition(BaseModel):
    """
    Discrete capability registered in the server-authoritative capability allowlist.
    Only registered, implemented capabilities can be granted or evaluated.
    """
    capability_id: str = Field(..., description="Canonical unique capability identifier, e.g. OBSERVE_TELEMETRY")
    name: str = Field(..., description="Human-readable name")
    minimum_level: AutonomyLevel = Field(..., description="Minimum autonomy level required")
    description: str = Field(..., description="Scope and purpose of capability")
    is_implemented: bool = Field(default=True, description="Whether capability has a real implementation")
    is_execution: bool = Field(default=False, description="True if capability executes operational mutations (must be False in V3)")
    requires_human_approval: bool = Field(default=False, description="Whether capability inherently requires HITL approval")
    allowed_data_modes: List[str] = Field(default_factory=lambda: ["SIMULATION", "REAL"], description="Allowed data modes")
    canonical_permission: Optional[str] = Field(default=None, description="Mapped underlying RBAC permission, if any")

    @field_validator("capability_id")
    def validate_capability_id(cls, v: str) -> str:
        clean = v.strip().upper()
        if not re.match(r"^[A-Z0-9_]{3,64}$", clean):
            raise ValueError(f"Invalid capability_id format: '{v}'. Must be 3-64 uppercase alphanumeric and underscores.")
        return clean

    @property
    def is_executable(self) -> bool:
        return self.is_execution


CANONICAL_CAPABILITIES: List[AutonomyCapabilityDefinition] = [
    # Level 0 — OBSERVE
    AutonomyCapabilityDefinition(
        capability_id="OBSERVE_TELEMETRY",
        name="Observe Telemetry",
        minimum_level=AutonomyLevel.LEVEL_0_OBSERVE,
        description="View authorized telemetry, machine states, and sensor streams",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="telemetry.read"
    ),
    AutonomyCapabilityDefinition(
        capability_id="READ_AUTHORIZED_SCHEMA",
        name="Read Authorized Schema",
        minimum_level=AutonomyLevel.LEVEL_0_OBSERVE,
        description="Inspect authorized database metadata, ontology models, and data catalogs",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="database.read"
    ),
    AutonomyCapabilityDefinition(
        capability_id="VIEW_AUDIT_HISTORY",
        name="View Audit History",
        minimum_level=AutonomyLevel.LEVEL_0_OBSERVE,
        description="Inspect security audit ledger records and event streams within authorized scope",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="audit.read"
    ),
    AutonomyCapabilityDefinition(
        capability_id="READ_MISSION",
        name="Read Mission",
        minimum_level=AutonomyLevel.LEVEL_0_OBSERVE,
        description="Inspect mission drafts, steps, criteria, and verification findings",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="mission.read"
    ),
    AutonomyCapabilityDefinition(
        capability_id="READ_ACTION",
        name="Read Action",
        minimum_level=AutonomyLevel.LEVEL_0_OBSERVE,
        description="Inspect structured action proposals, simulation previews, and status",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="action.read"
    ),

    # Level 1 — ANALYZE
    AutonomyCapabilityDefinition(
        capability_id="ANALYZE_EVIDENCE",
        name="Analyze Evidence",
        minimum_level=AutonomyLevel.LEVEL_1_ANALYZE,
        description="Correlate observations, run deterministic query analysis, and evaluate confidence",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="evidence_explainability.explain"
    ),
    AutonomyCapabilityDefinition(
        capability_id="CORRELATE_ANOMALIES",
        name="Correlate Anomalies",
        minimum_level=AutonomyLevel.LEVEL_1_ANALYZE,
        description="Correlate cross-sensor telemetry anomalies and evaluate multimodal sensor agreement",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="sensor_fusion.analyze"
    ),
    AutonomyCapabilityDefinition(
        capability_id="ANALYZE_ROOT_CAUSE",
        name="Analyze Root Cause",
        minimum_level=AutonomyLevel.LEVEL_1_ANALYZE,
        description="Run deterministic Root-Cause Analysis and blast radius estimation",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="rca.analyze"
    ),
    AutonomyCapabilityDefinition(
        capability_id="ESTIMATE_UNCERTAINTY",
        name="Estimate Uncertainty",
        minimum_level=AutonomyLevel.LEVEL_1_ANALYZE,
        description="Compute calibration curves, uncertainty intervals, and data quality scores",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="confidence_uncertainty.assess"
    ),
    AutonomyCapabilityDefinition(
        capability_id="DEFERRED_ADVANCED_SYNTHESIS",
        name="Deferred Advanced Synthesis",
        minimum_level=AutonomyLevel.LEVEL_1_ANALYZE,
        description="Autonomous multi-plant cross-correlator — UNIMPLEMENTED",
        is_implemented=False,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission=None
    ),

    # Level 2 — RECOMMEND
    AutonomyCapabilityDefinition(
        capability_id="GENERATE_RECOMMENDATION",
        name="Generate Recommendation",
        minimum_level=AutonomyLevel.LEVEL_2_RECOMMEND,
        description="Synthesize analytical findings into non-executable advisory recommendations",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="decision_engine.evaluate"
    ),
    AutonomyCapabilityDefinition(
        capability_id="PROPOSE_ACTION",
        name="Propose Action",
        minimum_level=AutonomyLevel.LEVEL_2_RECOMMEND,
        description="Draft a structured, typed operational action proposal for validation and review",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="action.create"
    ),
    AutonomyCapabilityDefinition(
        capability_id="CREATE_MISSION_DRAFT",
        name="Create Mission Draft",
        minimum_level=AutonomyLevel.LEVEL_2_RECOMMEND,
        description="Draft a structured, governed operational mission proposal and DAG work plan",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="mission.create"
    ),

    # Level 3 — PREPARE_FOR_APPROVAL
    AutonomyCapabilityDefinition(
        capability_id="VALIDATE_ACTION",
        name="Validate Action",
        minimum_level=AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
        description="Run deterministic parameter, schema, and simulation validation on action proposal",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="action.simulate"
    ),
    AutonomyCapabilityDefinition(
        capability_id="PREPARE_APPROVAL_PACKAGE",
        name="Prepare Approval Package",
        minimum_level=AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
        description="Collate evidence, lineage trace, blast radius, and simulation into reviewable package",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="action.read"
    ),
    AutonomyCapabilityDefinition(
        capability_id="REQUEST_HUMAN_REVIEW",
        name="Request Human Review",
        minimum_level=AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
        description="Submit validated proposal into human-in-the-loop (HITL) approval queue",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=True,
        canonical_permission="mission.review"
    ),
    AutonomyCapabilityDefinition(
        capability_id="VALIDATE_MISSION_DAG",
        name="Validate Mission DAG",
        minimum_level=AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL,
        description="Trigger deterministic acyclic DAG, scope containment, and criterion validation",
        is_implemented=True,
        is_execution=False,
        requires_human_approval=False,
        canonical_permission="mission.validate"
    ),

    # Level 4 — SUPERVISED_EXECUTION (DISABLED / NOT_IMPLEMENTED in V3)
    AutonomyCapabilityDefinition(
        capability_id="SUPERVISED_EXECUTION",
        name="Supervised Execution",
        minimum_level=AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
        description="Future supervised execution gateway execution — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission="action.execute"
    ),
    AutonomyCapabilityDefinition(
        capability_id="EXECUTE_SQL_MUTATION",
        name="Execute SQL Mutation",
        minimum_level=AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
        description="Direct write/update SQL statement execution — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),
    AutonomyCapabilityDefinition(
        capability_id="EXECUTE_SQL",
        name="Execute SQL Mutation",
        minimum_level=AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
        description="Direct write/update SQL statement execution — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),
    AutonomyCapabilityDefinition(
        capability_id="EXECUTE_COMMAND",
        name="Execute Shell Command",
        minimum_level=AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION,
        description="Operating system command execution — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),

    # Level 5 — BOUNDED_AUTONOMY (DISABLED / NOT_IMPLEMENTED in V3)
    AutonomyCapabilityDefinition(
        capability_id="CONTROL_PLC",
        name="Control PLC Command",
        minimum_level=AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
        description="Direct industrial PLC write/command — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),
    AutonomyCapabilityDefinition(
        capability_id="CONTROL_SCADA",
        name="Control SCADA Setpoint",
        minimum_level=AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
        description="Direct SCADA setpoint adjustment — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),
    AutonomyCapabilityDefinition(
        capability_id="BOUNDED_AUTONOMOUS_EXECUTION",
        name="Bounded Autonomous Execution",
        minimum_level=AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY,
        description="Autonomous industrial closed-loop execution — DISABLED AND NOT IMPLEMENTED",
        is_implemented=False,
        is_execution=True,
        requires_human_approval=True,
        canonical_permission=None
    ),
]


class CapabilityRegistry:
    """Server-authoritative registry maintaining valid capabilities."""

    def __init__(self, capabilities: Optional[List[AutonomyCapabilityDefinition]] = None):
        cap_list = capabilities if capabilities is not None else CANONICAL_CAPABILITIES
        self._capabilities: Dict[str, AutonomyCapabilityDefinition] = {
            c.capability_id: c for c in cap_list
        }

    def get(self, capability_id: str) -> Optional[AutonomyCapabilityDefinition]:
        return self._capabilities.get(capability_id.strip().upper())

    def list_all(self) -> List[AutonomyCapabilityDefinition]:
        return list(self._capabilities.values())

    def is_known(self, capability_id: str) -> bool:
        return capability_id.strip().upper() in self._capabilities

    def is_implemented(self, capability_id: str) -> bool:
        cap = self.get(capability_id)
        return bool(cap and cap.is_implemented)


# Global default registry
default_capability_registry = CapabilityRegistry()


# =============================================================================
# 3. SCOPE, CONSTRAINTS & PROVENANCE
# =============================================================================

class AutonomyScope(BaseModel):
    """Hierarchical resource scope boundary for an autonomy grant or capability request."""
    tenant_id: str = Field(..., description="Target tenant ID")
    workspace_id: Optional[str] = Field(default=None, description="Target workspace ID or '*' if unrestricted")
    session_id: Optional[str] = Field(default=None, description="Optional session correlation ID")
    plant_id: Optional[str] = Field(default=None, description="Target plant ID or '*' if unrestricted")
    line_id: Optional[str] = Field(default=None, description="Target production line ID")
    equipment_id: Optional[str] = Field(default=None, description="Target machine or equipment ID")

    @field_validator("tenant_id")
    def validate_tenant(cls, v: str) -> str:
        clean = v.strip()
        if not clean or clean == "*":
            raise ValueError("tenant_id must be a specific non-empty identifier; wildcard tenant is forbidden.")
        _scan_for_secrets(clean, "tenant_id")
        return clean

    @field_validator("workspace_id", "plant_id", "session_id", "line_id", "equipment_id")
    def validate_scope_fields(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean = v.strip()
        _scan_for_secrets(clean, "scope_field")
        return clean


class AutonomyConstraints(BaseModel):
    """Safety and risk constraints bound to an autonomy grant."""
    approval_required_for_risk_levels: List[str] = Field(
        default_factory=lambda: ["HIGH", "CRITICAL"],
        description="Risk levels that unconditionally demand human approval"
    )
    max_cost_limit_usd: Optional[float] = Field(
        default=None,
        description="Maximum estimated financial cost threshold before human escalation"
    )
    max_estimated_duration_minutes: Optional[int] = Field(
        default=None,
        description="Maximum estimated operational duration before human escalation"
    )
    restricted_action_types: List[str] = Field(
        default_factory=list,
        description="Specific action types explicitly denied to this grant"
    )
    custom_rules: Dict[str, Any] = Field(
        default_factory=dict,
        description="Non-sensitive structured constraint rules"
    )

    @field_validator("restricted_action_types")
    def clean_action_types(cls, v: List[str]) -> List[str]:
        return [item.strip().upper() for item in v]



class AutonomyProvenance(BaseModel):
    """Audit provenance tracking how and by whom the grant was issued."""
    created_by_user_id: str = Field(..., description="Authoritative user ID who created the grant")
    granted_by_user_id: str = Field(..., description="Authoritative supervisor or security officer who authorized the grant")
    grant_reason: str = Field(..., description="Operational justification for autonomy grant")
    approval_ticket_id: Optional[str] = Field(default=None, description="Associated change-control ticket ID")
    delegated_from_grant_id: Optional[str] = Field(default=None, description="Parent grant ID if delegated")

    @field_validator("created_by_user_id", "granted_by_user_id", "grant_reason")
    def validate_provenance_text(cls, v: str) -> str:
        clean = v.strip()
        _scan_for_secrets(clean, "provenance")
        return clean


# =============================================================================
# 4. CANONICAL AUTONOMY GRANT MODEL
# =============================================================================

class AutonomyGrant(BaseModel):
    """
    Authoritative, versioned autonomy grant record.
    Binds a subject (agent, mission, user, workflow) to a specific autonomy level,
    permitted capabilities, authoritative scope, constraints, and lifecycle status.
    """
    grant_id: str = Field(default_factory=lambda: f"grant_{uuid.uuid4().hex[:12]}")
    schema_version: str = Field(default=SCHEMA_VERSION)
    subject_type: SubjectType = Field(..., description="Entity type being governed")
    subject_id: str = Field(..., description="Unique subject ID (e.g. agent_copilot, mission_123)")
    autonomy_level: AutonomyLevel = Field(..., description="Granted autonomy level (0-3 in V3)")
    tenant_id: str = Field(..., description="Authoritative tenant ID")
    workspace_id: str = Field(..., description="Authoritative workspace ID")
    session_id: Optional[str] = Field(default=None, description="Session ID if session-bound")
    plant_id: Optional[str] = Field(default=None, description="Plant ID if plant-scoped")
    data_mode: str = Field(default="SIMULATION", description="Operating data mode: SIMULATION or REAL")
    permitted_capabilities: List[str] = Field(default_factory=list, description="Explicitly allowlisted capability IDs")
    restricted_capabilities: List[str] = Field(default_factory=list, description="Explicitly restricted capability IDs")
    constraints: AutonomyConstraints = Field(default_factory=AutonomyConstraints)
    effective_from: float = Field(default_factory=time.time, description="Unix timestamp when grant becomes active")
    expires_at: Optional[float] = Field(default=None, description="Unix timestamp when grant expires (None = no expiry)")
    status: AutonomyGrantStatus = Field(default=AutonomyGrantStatus.ACTIVE)
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision number")
    created_by: str = Field(..., description="Authoritative creator user ID")
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    provenance: AutonomyProvenance = Field(
        default_factory=lambda: AutonomyProvenance(
            created_by_user_id="system",
            granted_by_user_id="system",
            grant_reason="System default grant"
        )
    )

    @property
    def scope(self) -> AutonomyScope:
        return AutonomyScope(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            plant_id=self.plant_id,
        )

    @field_validator("autonomy_level", mode="before")
    def parse_autonomy_level(cls, v: Any) -> Any:
        return _normalize_autonomy_level(v)

    @field_validator("autonomy_level")
    def validate_level(cls, v: AutonomyLevel) -> AutonomyLevel:
        if v >= AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION:
            raise ValueError(
                f"Autonomy {v.name} is DISABLED and NOT_IMPLEMENTED in SageCommand V3. "
                "Execution capabilities cannot be granted."
            )
        return v

    @field_validator("data_mode")
    def validate_data_mode(cls, v: str) -> str:
        clean = v.strip().upper()
        if clean not in ("SIMULATION", "REAL"):
            raise ValueError(f"Invalid data_mode '{v}'. Must be 'SIMULATION' or 'REAL'.")
        return clean

    @field_validator("permitted_capabilities", "restricted_capabilities")
    def clean_caps(cls, v: List[str]) -> List[str]:
        return [item.strip().upper() for item in v]


    def is_expired(self, current_time: Optional[float] = None) -> bool:
        """Determines if the grant is past its expiration timestamp."""
        now = current_time if current_time is not None else time.time()
        if self.expires_at is not None and now > self.expires_at:
            return True
        return False

    def is_active(self, current_time: Optional[float] = None) -> bool:
        """Grant is active only if status is ACTIVE and not expired."""
        if self.status != AutonomyGrantStatus.ACTIVE:
            return False
        return not self.is_expired(current_time)


# =============================================================================
# 5. DETERMINISTIC DECISION CONTRACT
# =============================================================================

class AutonomyDecision(BaseModel):
    """
    Deterministic, auditable decision record produced for every capability evaluation.
    Protected by cryptographic SHA-256 decision hash.
    """
    decision_id: str = Field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:12]}")
    decision: AutonomyDecisionEffect = Field(..., description="ALLOW, DENY, REQUIRES_REVIEW, or NOT_IMPLEMENTED")
    reason_code: AutonomyReasonCode = Field(..., description="Standard machine-readable reason code")
    reason: str = Field(..., description="Human-readable decision explanation")
    subject_type: SubjectType = Field(..., description="Governed subject type")
    subject_id: str = Field(..., description="Governed subject ID")
    requested_capability: str = Field(..., description="Requested capability ID")
    effective_autonomy_level: AutonomyLevel = Field(..., description="Effective autonomy level evaluated")
    scope: AutonomyScope = Field(..., description="Target resource scope evaluated")
    data_mode: str = Field(..., description="Operating data mode evaluated")
    risk_status: str = Field(default="UNKNOWN", description="Assessed risk status: LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN")
    approval_requirement: bool = Field(default=False, description="Whether operation requires human approval")
    matched_constraints: List[str] = Field(default_factory=list, description="Constraints that passed")
    failed_constraints: List[str] = Field(default_factory=list, description="Constraints that failed")
    evaluated_at: float = Field(default_factory=time.time)
    policy_version: str = Field(default="3.0.0")
    autonomy_profile_revision: int = Field(default=1)
    request_id: Optional[str] = Field(default=None)
    grant_id: Optional[str] = Field(default=None)
    decision_hash: str = Field(default="")

    @classmethod
    def create(
        cls,
        decision: AutonomyDecisionEffect,
        reason_code: AutonomyReasonCode,
        reason: str,
        subject_type: SubjectType,
        subject_id: str,
        requested_capability: str,
        effective_autonomy_level: AutonomyLevel,
        scope: AutonomyScope,
        data_mode: str,
        risk_status: str = "UNKNOWN",
        approval_requirement: bool = False,
        matched_constraints: Optional[List[str]] = None,
        failed_constraints: Optional[List[str]] = None,
        policy_version: str = "3.0.0",
        autonomy_profile_revision: int = 1,
        request_id: Optional[str] = None,
        grant_id: Optional[str] = None,
    ) -> "AutonomyDecision":
        """Constructs an AutonomyDecision with a deterministic SHA-256 decision hash."""
        now = time.time()
        dec_id = f"dec_{uuid.uuid4().hex[:12]}"

        hash_payload = {
            "decision_id": dec_id,
            "decision": decision.value,
            "reason_code": reason_code.value,
            "subject_id": subject_id,
            "requested_capability": requested_capability,
            "level": int(effective_autonomy_level),
            "tenant_id": scope.tenant_id,
            "workspace_id": scope.workspace_id,
            "plant_id": scope.plant_id,
            "data_mode": data_mode,
            "risk_status": risk_status,
            "approval_requirement": approval_requirement,
            "grant_id": grant_id,
            "evaluated_at": now,
        }
        raw_bytes = json.dumps(hash_payload, sort_keys=True).encode("utf-8")
        dec_hash = hashlib.sha256(raw_bytes).hexdigest()

        return cls(
            decision_id=dec_id,
            decision=decision,
            reason_code=reason_code,
            reason=reason,
            subject_type=subject_type,
            subject_id=subject_id,
            requested_capability=requested_capability,
            effective_autonomy_level=effective_autonomy_level,
            scope=scope,
            data_mode=data_mode,
            risk_status=risk_status,
            approval_requirement=approval_requirement,
            matched_constraints=matched_constraints or [],
            failed_constraints=failed_constraints or [],
            evaluated_at=now,
            policy_version=policy_version,
            autonomy_profile_revision=autonomy_profile_revision,
            request_id=request_id,
            grant_id=grant_id,
            decision_hash=dec_hash,
        )


# =============================================================================
# 6. API REQUEST / RESPONSE SCHEMAS
# =============================================================================

class AutonomyGrantCreateRequest(BaseModel):
    """Payload to create a new autonomy grant."""
    subject_type: SubjectType
    subject_id: str
    autonomy_level: AutonomyLevel
    tenant_id: Optional[str] = None  # Ignored and overridden by server-authoritative identity
    workspace_id: Optional[str] = None
    session_id: Optional[str] = None
    plant_id: Optional[str] = None
    data_mode: str = "SIMULATION"
    permitted_capabilities: Optional[List[str]] = None
    restricted_capabilities: Optional[List[str]] = None
    constraints: Optional[AutonomyConstraints] = None
    expires_at: Optional[float] = None
    grant_reason: str = Field(default="Standard operational delegation grant")
    approval_ticket_id: Optional[str] = None
    idempotency_key: Optional[str] = None

    @field_validator("autonomy_level", mode="before")
    def parse_autonomy_level(cls, v: Any) -> Any:
        return _normalize_autonomy_level(v)

    @field_validator("subject_id", "grant_reason")
    def validate_text(cls, v: str) -> str:
        clean = v.strip()
        _scan_for_secrets(clean, "grant_create")
        return clean


class AutonomyGrantUpdateRequest(BaseModel):
    """Payload to update an existing autonomy grant."""
    expected_revision: int = Field(..., ge=0, description="Expected current revision for optimistic locking")
    autonomy_level: Optional[AutonomyLevel] = None
    status: Optional[AutonomyGrantStatus] = None
    permitted_capabilities: Optional[List[str]] = None
    restricted_capabilities: Optional[List[str]] = None
    constraints: Optional[AutonomyConstraints] = None
    expires_at: Optional[float] = None
    update_reason: str = Field(default="Standard grant update")

    @field_validator("autonomy_level", mode="before")
    def parse_autonomy_level(cls, v: Any) -> Any:
        return _normalize_autonomy_level(v)

    @field_validator("update_reason")
    def validate_update_reason(cls, v: str) -> str:
        clean = v.strip()
        _scan_for_secrets(clean, "update_reason")
        return clean


class AutonomyEvaluationRequest(BaseModel):
    """Payload to evaluate a capability request against autonomy governance."""
    subject_type: SubjectType = Field(default=SubjectType.AGENT)
    subject_id: str
    requested_capability: str
    scope: Optional[AutonomyScope] = None
    resource_scope: Optional[AutonomyScope] = None
    data_mode: str = "SIMULATION"
    risk_level: Optional[str] = None
    cost_estimate_usd: Optional[float] = None
    action_type: Optional[str] = None
    target_resource_id: Optional[str] = None
    request_id: Optional[str] = None

    @model_validator(mode="after")
    def resolve_scope(self) -> "AutonomyEvaluationRequest":
        if self.scope is None and self.resource_scope is not None:
            self.scope = self.resource_scope
        elif self.scope is None:
            raise ValueError("Either 'scope' or 'resource_scope' must be provided.")
        return self


class AutonomyGrantListResponse(BaseModel):
    """Paginated response for autonomy grant queries."""
    total: int
    grants: List[AutonomyGrant]
