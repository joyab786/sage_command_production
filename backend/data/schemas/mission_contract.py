# backend/data/schemas/mission_contract.py
"""
SageCommand V3 — Governed Mission Architecture Foundation Contracts (Prompt 35)

A MISSION IS A GOVERNED OPERATIONAL OBJECTIVE AND WORK PLAN ONLY — NEVER CONSTITUTES
DIRECT EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Defines typed, validated domain models, lifecycle enums, DAG dependency validation,
scope constraints, structured step definitions, success criteria, and audit contracts.

Cardinal Invariants:
1. A mission is an auditable, bounded operational objective, NOT a chat conversation or free-form LLM plan.
2. A mission NEVER directly executes SQL mutations, shell commands, PLC/SCADA writes, or invokes the Execution Gateway.
3. Structured action references organize intent; they do NOT bypass action validation or policy approval.
4. Tenant, workspace, and plant scope are authoritative from authenticated server context and fail closed.
5. Client or LLM-supplied fields cannot override data_mode, tenant_id, workspace_id, or authorization.
6. Step dependencies must form a strictly acyclic directed graph (DAG).
7. Validated and accepted missions are protected from silent mutation through explicit revision history.
8. Unresolved completion status remains UNKNOWN; LLMs cannot claim mission completion without verified evidence.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =============================================================================
# 0. CONSTANTS & MANDATORY NOTICE
# =============================================================================

MANDATORY_MISSION_NOTICE = (
    "A MISSION IS A GOVERNED OPERATIONAL OBJECTIVE AND WORK PLAN ONLY — NEVER CONSTITUTES "
    "DIRECT EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL."
)

SCHEMA_VERSION = "3.0.0"

# Anti-executable / Anti-smuggling pattern checks
_DISALLOWED_PATTERNS = re.compile(
    r"(?i)\b(exec\s*\(|eval\s*\(|os\.system|subprocess\.|__import__|import\s+sys|"
    r"select\s+.*\s+from|insert\s+into|update\s+.*\s+set|delete\s+from|drop\s+table|"
    r"alter\s+table|truncate\s+table|union\s+select|;\s*drop|;\s*shutdown|"
    r"rm\s+-rf|format\s+[a-z]:|powershell\s+-enc|cmd\.exe\s+/c|sh\s+-c|curl\s+.*\|\s*sh)"
)

# Raw credentials, connection strings, bearer tokens, and private key detection
_SECRET_PATTERNS = re.compile(
    r"(?i)("
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"[a-z][a-z0-9+.-]*:\/\/[^\/\s:@]+:[^\/\s:@]+@|"  # URI with embedded user:password@
    r"\b(bearer|token)\s+[A-Za-z0-9_\-\.]{16,}\b|"
    r"\b(password|passwd|secret_key|api_key|access_token|private_key|auth_token)\s*[:=]\s*[\"']?[A-Za-z0-9_\-\.]{6,}[\"']?|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b|"
    r"\beyJ[A-Za-z0-9_\-\.]{20,}\b|"
    r"\b(sk_live|sk_test|ghp_|glpat-|xoxb-|xoxp-)[A-Za-z0-9_\-]{10,}\b"
    r")"
)

PROHIBITED_METADATA_KEYS = {
    "password", "passwd", "secret", "secret_key", "api_key", "apikey",
    "token", "access_token", "private_key", "credentials", "conn_str",
    "connection_string", "auth_token"
}

# Allowlisted resource categories for canonical reference validation
SUPPORTED_RESOURCE_CATEGORIES = {
    "actions",
    "action_proposals",
    "decisions",
    "evidence",
    "incidents",
    "rcas",
    "memories",
}

CANONICAL_PLANT_ID_REGEX = re.compile(r"^[A-Za-z0-9_\-\.]{2,64}$")


def _scan_for_secrets(value: Optional[str], field_name: str) -> None:
    """Detects raw credentials, tokens, passwords, connection strings, and private keys."""
    if not value:
        return
    if _SECRET_PATTERNS.search(value):
        raise ValueError(
            f"Field '{field_name}' contains potential secret, credential, token, or connection string."
        )


def validate_plant_identifier(v: str) -> str:
    """Validates plant identifier format and scans for secrets."""
    if not v or not isinstance(v, str):
        raise ValueError("Plant identifier must be a non-empty string.")
    v = v.strip()
    _scan_for_secrets(v, "plant_id")
    if not CANONICAL_PLANT_ID_REGEX.match(v):
        raise ValueError(
            f"Invalid plant identifier format '{v}'. Must be 2-64 alphanumeric characters, underscores, dashes, or dots."
        )
    return v


def _validate_safe_text(value: Optional[str], field_name: str) -> Optional[str]:
    """Ensures string does not contain executable code, SQL smuggling, shell scripts, or raw secrets."""
    if not value:
        return value
    _scan_for_secrets(value, field_name)
    if _DISALLOWED_PATTERNS.search(value):
        raise ValueError(
            f"Field '{field_name}' contains disallowed executable pattern, script, or SQL command."
        )
    return value


def _validate_related_resources(v: Optional[Dict[str, List[str]]]) -> Optional[Dict[str, List[str]]]:
    """Bounds and validates related_resources categories and ID formats."""
    if v is None:
        return v
    if len(v) > 10:
        raise ValueError(f"related_resources category count ({len(v)}) exceeds maximum allowed (10).")
    total_ids = 0
    for cat, id_list in v.items():
        if cat.lower() not in SUPPORTED_RESOURCE_CATEGORIES:
            raise ValueError(
                f"Unsupported resource category '{cat}'. Supported categories are: {sorted(list(SUPPORTED_RESOURCE_CATEGORIES))}."
            )
        if len(id_list) > 25:
            raise ValueError(f"Resource category '{cat}' ID count ({len(id_list)}) exceeds maximum allowed (25).")
        total_ids += len(id_list)
        for res_id in id_list:
            _scan_for_secrets(res_id, "resource_id")
            if not re.match(r"^[A-Za-z0-9_\-\.]{1,64}$", res_id):
                raise ValueError(f"Invalid resource ID format '{res_id}' in category '{cat}'.")
    if total_ids > 50:
        raise ValueError(f"Aggregate related_resources count ({total_ids}) exceeds maximum allowed (50).")
    return v


# =============================================================================
# 1. CENTRALIZED ENUMS
# =============================================================================

class MissionStatus(str, Enum):
    """Deterministic lifecycle state machine for an industrial mission."""
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MissionType(str, Enum):
    """Officially supported mission types mapped to current SageCommand capabilities."""
    INVESTIGATION = "INVESTIGATION"
    PREDICTIVE_MAINTENANCE = "PREDICTIVE_MAINTENANCE"
    SUPPLY_CHAIN_RISK = "SUPPLY_CHAIN_RISK"
    INVENTORY_REPLENISHMENT = "INVENTORY_REPLENISHMENT"
    INCIDENT_RESPONSE = "INCIDENT_RESPONSE"
    ROOT_CAUSE_ANALYSIS = "ROOT_CAUSE_ANALYSIS"
    OPERATIONAL_REVIEW = "OPERATIONAL_REVIEW"


class StepType(str, Enum):
    """Permitted step types for planned work within a mission."""
    ANALYSIS = "ANALYSIS"
    INVESTIGATION = "INVESTIGATION"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    ACTION_PROPOSAL = "ACTION_PROPOSAL"
    DECISION_REQUEST = "DECISION_REQUEST"
    POLICY_CHECK = "POLICY_CHECK"
    REVIEW = "REVIEW"


class StepStatus(str, Enum):
    """Status of an individual planned step."""
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class DataMode(str, Enum):
    """Authoritative execution boundary mode."""
    SIMULATION = "SIMULATION"
    REAL = "REAL"


class CriterionStatus(str, Enum):
    """Deterministic status of an individual success criterion."""
    UNKNOWN = "UNKNOWN"
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConstraintType(str, Enum):
    """Classification of operational constraint."""
    TIME = "TIME"
    BUDGET = "BUDGET"
    RESOURCE = "RESOURCE"
    POLICY = "POLICY"
    SAFETY = "SAFETY"
    OPERATIONAL = "OPERATIONAL"


# =============================================================================
# 2. LIFECYCLE TRANSITION MAP
# =============================================================================

VALID_LIFECYCLE_TRANSITIONS: Dict[MissionStatus, Set[MissionStatus]] = {
    MissionStatus.DRAFT: {
        MissionStatus.PROPOSED,
        MissionStatus.VALIDATING,
        MissionStatus.VALIDATED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.PROPOSED: {
        MissionStatus.VALIDATING,
        MissionStatus.VALIDATED,
        MissionStatus.DRAFT,
        MissionStatus.CANCELLED,
    },
    MissionStatus.VALIDATING: {
        MissionStatus.VALIDATED,
        MissionStatus.DRAFT,
        MissionStatus.REJECTED,
        MissionStatus.CANCELLED,
    },
    MissionStatus.VALIDATED: {
        MissionStatus.REVIEW_REQUIRED,
        MissionStatus.DRAFT,
        MissionStatus.CANCELLED,
    },
    MissionStatus.REVIEW_REQUIRED: {
        MissionStatus.ACCEPTED,
        MissionStatus.REJECTED,
        MissionStatus.DRAFT,
        MissionStatus.CANCELLED,
    },
    MissionStatus.ACCEPTED: {
        MissionStatus.CANCELLED,
    },
    MissionStatus.REJECTED: {
        MissionStatus.DRAFT,
        MissionStatus.CANCELLED,
    },
    MissionStatus.CANCELLED: set(),
}


def is_valid_lifecycle_transition(current: MissionStatus, target: MissionStatus) -> bool:
    """Check if lifecycle transition is permitted."""
    allowed = VALID_LIFECYCLE_TRANSITIONS.get(current, set())
    return target in allowed


# =============================================================================
# 3. DOMAIN SUB-MODELS
# =============================================================================

class MissionScope(BaseModel):
    """Authoritative security and organizational boundary for a mission."""
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(..., min_length=1, max_length=128, description="Authoritative tenant ID")
    workspace_id: str = Field(..., min_length=1, max_length=128, description="Authoritative workspace ID")
    plant_id: str = Field(..., min_length=1, max_length=128, description="Authoritative plant ID")
    session_id: Optional[str] = Field(default=None, max_length=128, description="Optional caller session ID")

    @field_validator("plant_id")
    @classmethod
    def validate_scope_plant_id(cls, v: str) -> str:
        return validate_plant_identifier(v)

    @field_validator("tenant_id", "workspace_id", "session_id")
    @classmethod
    def validate_scope_identifiers(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            _scan_for_secrets(v, info.field_name)
        return v


class MissionConstraint(BaseModel):
    """Bounded, reviewable operational constraint."""
    model_config = ConfigDict(extra="forbid")

    constraint_id: str = Field(
        default_factory=lambda: f"con_{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
        description="Unique constraint identifier"
    )
    constraint_type: ConstraintType = Field(..., description="Type of constraint")
    description: str = Field(..., min_length=1, max_length=1000, description="Human-readable constraint description")
    is_hard: bool = Field(default=True, description="Whether constraint is hard (violating halts) or soft")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Typed constraint parameters")

    @field_validator("constraint_id")
    @classmethod
    def validate_constraint_id(cls, v: str) -> str:
        _scan_for_secrets(v, "constraint_id")
        if not re.match(r"^[A-Za-z0-9_\-\.]{1,64}$", v):
            raise ValueError(f"Invalid constraint ID format '{v}'.")
        return v

    @field_validator("description")
    @classmethod
    def validate_description_safe(cls, v: str) -> str:
        return _validate_safe_text(v, "description") or v

    @field_validator("parameters")
    @classmethod
    def validate_parameters_bounds_and_safety(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            return v

        # 1. Nesting depth check (max depth 3)
        def _check_depth(obj: Any, current: int = 1) -> None:
            if current > 3:
                raise ValueError("Constraint parameters nesting depth exceeds maximum allowed (depth 3).")
            if isinstance(obj, dict):
                for val in obj.values():
                    _check_depth(val, current + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _check_depth(item, current + 1)

        _check_depth(v)

        # 2. Total key count check (max 20 keys)
        def _count_keys(obj: Any) -> int:
            cnt = 0
            if isinstance(obj, dict):
                cnt += len(obj)
                for val in obj.values():
                    cnt += _count_keys(val)
            elif isinstance(obj, list):
                for item in obj:
                    cnt += _count_keys(item)
            return cnt

        if _count_keys(v) > 20:
            raise ValueError(f"Constraint parameters total key count exceeds maximum allowed (20 keys).")

        # 3. Serialized size check (max 4096 bytes)
        dumped = json.dumps(v, default=str)
        if len(dumped.encode("utf-8")) > 4096:
            raise ValueError("Constraint parameters serialized size exceeds maximum allowed (4096 bytes).")

        # 4. Secret scanning and prohibited keys
        def _scan_obj(obj: Any, path: str = "parameters") -> None:
            if isinstance(obj, dict):
                for k, val in obj.items():
                    k_str = str(k).lower()
                    if k_str in PROHIBITED_METADATA_KEYS:
                        raise ValueError(f"Prohibited secret metadata key '{k}' detected in parameters.")
                    _validate_safe_text(str(k), f"{path}.key")
                    _scan_obj(val, f"{path}.{k}")
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    _scan_obj(item, f"{path}[{idx}]")
            elif isinstance(obj, str):
                _validate_safe_text(obj, path)

        _scan_obj(v)
        return v


class MissionSuccessCriterion(BaseModel):
    """Structured, reviewable success criterion — NOT an executable expression."""
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(
        default_factory=lambda: f"crit_{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
        description="Unique criterion identifier"
    )
    description: str = Field(..., min_length=1, max_length=1000, description="Reviewable condition required for success")
    status: CriterionStatus = Field(default=CriterionStatus.UNKNOWN, description="Deterministic status of criterion")
    target_metric: Optional[str] = Field(default=None, max_length=256, description="Optional target metric name or key")
    required_evidence_type: Optional[str] = Field(default=None, max_length=128, description="Expected evidence record type")
    evaluation_notes: Optional[str] = Field(default=None, max_length=2000, description="Auditable reviewer evaluation notes")

    @field_validator("criterion_id")
    @classmethod
    def validate_criterion_id(cls, v: str) -> str:
        _scan_for_secrets(v, "criterion_id")
        if not re.match(r"^[A-Za-z0-9_\-\.]{1,64}$", v):
            raise ValueError(f"Invalid criterion ID format '{v}'.")
        return v

    @field_validator("description", "target_metric", "required_evidence_type", "evaluation_notes")
    @classmethod
    def validate_safe_text(cls, v: Optional[str], info) -> Optional[str]:
        return _validate_safe_text(v, info.field_name)


class MissionEvidenceRequirement(BaseModel):
    """Explicit evidence requirement needed to evaluate mission outcomes."""
    model_config = ConfigDict(extra="forbid")

    requirement_id: str = Field(
        default_factory=lambda: f"evreq_{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
        description="Unique requirement ID"
    )
    evidence_type: str = Field(..., min_length=1, max_length=128, description="Type of evidence record required")
    description: str = Field(..., min_length=1, max_length=1000, description="Description of evidence required")
    is_mandatory: bool = Field(default=True, description="Whether this evidence is strictly mandatory")
    linked_evidence_id: Optional[str] = Field(default=None, max_length=128, description="ID of linked evidence record if attached")

    @field_validator("requirement_id")
    @classmethod
    def validate_requirement_id(cls, v: str) -> str:
        _scan_for_secrets(v, "requirement_id")
        if not re.match(r"^[A-Za-z0-9_\-\.]{1,64}$", v):
            raise ValueError(f"Invalid requirement ID format '{v}'.")
        return v

    @field_validator("linked_evidence_id")
    @classmethod
    def validate_linked_evidence_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            _scan_for_secrets(v, "linked_evidence_id")
            if not re.match(r"^[A-Za-z0-9_\-\.]{1,128}$", v):
                raise ValueError(f"Invalid linked evidence ID format '{v}'.")
        return v

    @field_validator("description", "evidence_type")
    @classmethod
    def validate_description_safe(cls, v: str, info) -> str:
        return _validate_safe_text(v, info.field_name) or v


class MissionPlannedStep(BaseModel):
    """A typed step representing planned work within a mission DAG."""
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(..., min_length=1, max_length=64, description="Unique step identifier within mission")
    title: str = Field(..., min_length=1, max_length=256, description="Short step title")
    description: str = Field(..., min_length=1, max_length=2000, description="Detailed step description")
    step_type: StepType = Field(..., description="Classification of work for this step")
    status: StepStatus = Field(default=StepStatus.PLANNED, description="Current execution or planning status")
    depends_on: List[str] = Field(default_factory=list, max_length=20, description="List of step_ids that must complete before this step")
    related_resource_ids: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="References to Action proposals, Decisions, Incidents, RCAs, or Memories"
    )
    required_evidence: List[str] = Field(default_factory=list, max_length=20, description="Evidence requirements for this step")

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, v: str) -> str:
        v = v.strip()
        _scan_for_secrets(v, "step_id")
        if not re.match(r"^[A-Za-z0-9_-]+$", v):
            raise ValueError(f"Step ID '{v}' must be alphanumeric with dashes or underscores only.")
        return v

    @field_validator("related_resource_ids")
    @classmethod
    def validate_related_resource_ids(cls, v: List[str]) -> List[str]:
        if len(v) > 20:
            raise ValueError(f"Step related_resource_ids count ({len(v)}) exceeds maximum allowed (20).")
        for res_id in v:
            _scan_for_secrets(res_id, "related_resource_id")
            if not re.match(r"^[A-Za-z0-9_\-\.]{1,64}$", res_id):
                raise ValueError(f"Invalid resource ID format '{res_id}'.")
        return v

    @field_validator("required_evidence")
    @classmethod
    def validate_required_evidence(cls, v: List[str]) -> List[str]:
        if len(v) > 20:
            raise ValueError(f"Step required_evidence count ({len(v)}) exceeds maximum allowed (20).")
        for ev in v:
            if len(ev) > 128:
                raise ValueError(f"Required evidence name '{ev[:20]}...' exceeds maximum length (128 characters).")
            _validate_safe_text(ev, "required_evidence")
        return v

    @field_validator("title", "description")
    @classmethod
    def validate_step_text(cls, v: str, info) -> str:
        return _validate_safe_text(v, info.field_name) or v


class MissionProvenance(BaseModel):
    """Audit and origin metadata for mission creation and evolution."""
    model_config = ConfigDict(extra="forbid")

    created_by: str = Field(..., min_length=1, max_length=128, description="Identity of creator")
    created_by_role: Optional[str] = Field(default=None, max_length=64, description="Role of creator at creation time")
    origin_reason: str = Field(..., min_length=1, max_length=1000, description="Operational justification for mission")
    parent_incident_id: Optional[str] = Field(default=None, max_length=128, description="Associated Incident ID if applicable")
    parent_rca_id: Optional[str] = Field(default=None, max_length=128, description="Associated RCA ID if applicable")
    source_system: str = Field(default="sagecommand_v3", max_length=64, description="Originating subsystem")
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Analytical confidence if known")

    @field_validator("parent_incident_id", "parent_rca_id")
    @classmethod
    def validate_parent_ids(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            _scan_for_secrets(v, info.field_name)
            if not re.match(r"^[A-Za-z0-9_\-\.]{1,128}$", v):
                raise ValueError(f"Invalid identifier format for '{info.field_name}': '{v}'.")
        return v

    @field_validator("origin_reason")
    @classmethod
    def validate_origin_reason(cls, v: str) -> str:
        return _validate_safe_text(v, "origin_reason") or v

    @field_validator("created_by", "created_by_role", "source_system")
    @classmethod
    def validate_provenance_text(cls, v: Optional[str], info) -> Optional[str]:
        return _validate_safe_text(v, info.field_name)


# =============================================================================
# 4. CANONICAL MISSION DOMAIN MODEL
# =============================================================================

class Mission(BaseModel):
    """
    Canonical SageCommand V3 Industrial Mission.

    Represents a governed, auditable, bounded operational objective with
    structured work steps, dependency constraints, and evidence requirements.
    """
    model_config = ConfigDict(extra="forbid")

    mission_id: str = Field(
        default_factory=lambda: f"msn_{uuid.uuid4().hex[:16]}",
        min_length=1,
        max_length=64,
        description="Unique mission identifier"
    )
    schema_version: str = Field(default=SCHEMA_VERSION, description="Contract schema version")
    revision: int = Field(default=1, ge=1, description="Monotonically increasing revision number")
    title: str = Field(..., min_length=1, max_length=256, description="Short, descriptive mission title")
    description: str = Field(..., min_length=1, max_length=4000, description="Comprehensive mission narrative")
    mission_type: MissionType = Field(..., description="Allowlisted mission classification")
    objective: str = Field(..., min_length=1, max_length=4000, description="Primary bounded operational objective")
    scope: MissionScope = Field(..., description="Authoritative organizational and security boundary")
    constraints: List[MissionConstraint] = Field(default_factory=list, max_length=20, description="Bounded operational constraints")
    success_criteria: List[MissionSuccessCriterion] = Field(default_factory=list, max_length=20, description="Structured success conditions")
    planned_steps: List[MissionPlannedStep] = Field(default_factory=list, max_length=50, description="Planned DAG steps")
    evidence_requirements: List[MissionEvidenceRequirement] = Field(default_factory=list, max_length=30, description="Required evidence items")
    related_resources: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="Referenced Action proposals, Decisions, Incidents, RCAs, and Memories"
    )
    data_mode: DataMode = Field(default=DataMode.SIMULATION, description="Authoritative execution mode boundary")
    status: MissionStatus = Field(default=MissionStatus.DRAFT, description="Current governance lifecycle status")
    provenance: MissionProvenance = Field(..., description="Origin and creator provenance")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 creation timestamp"
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 last update timestamp"
    )
    created_by: str = Field(..., min_length=1, max_length=128, description="Authoritative identity of creator")
    validation_errors: List[str] = Field(default_factory=list, max_length=50, description="Structural and domain validation error traces")
    validation_warnings: List[str] = Field(default_factory=list, max_length=50, description="Domain validation warnings")
    review_notes: Optional[str] = Field(default=None, max_length=4000, description="Governance reviewer notes")
    reviewed_by: Optional[str] = Field(default=None, max_length=128, description="Governance reviewer identity")
    reviewed_at: Optional[str] = Field(default=None, description="ISO-8601 review timestamp")

    @field_validator("title", "description", "objective")
    @classmethod
    def validate_mission_text(cls, v: str, info) -> str:
        return _validate_safe_text(v, info.field_name) or v

    @field_validator("related_resources")
    @classmethod
    def validate_mission_related_resources(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        return _validate_related_resources(v) or {}

    @model_validator(mode="after")
    def validate_created_by_matches_provenance(self) -> "Mission":
        if self.created_by != self.provenance.created_by:
            # Reconcile authoritative creator
            self.provenance.created_by = self.created_by
        return self


# =============================================================================
# 5. DETERMINISTIC DAG DEPENDENCY VALIDATION
# =============================================================================

def validate_mission_dependencies(
    planned_steps: List[MissionPlannedStep],
    max_steps: int = 50,
    max_dependencies: int = 100,
) -> Tuple[bool, List[str]]:
    """
    Deterministically validates step identifiers and acyclic dependency graph (DAG).

    Returns:
        Tuple[is_valid, error_messages]
    """
    errors: List[str] = []

    if len(planned_steps) > max_steps:
        errors.append(f"Step count ({len(planned_steps)}) exceeds maximum allowed ({max_steps}).")

    step_ids: Set[str] = set()
    total_deps = 0

    for step in planned_steps:
        if step.step_id in step_ids:
            errors.append(f"Duplicate step ID '{step.step_id}' found in planned steps.")
        step_ids.add(step.step_id)
        total_deps += len(step.depends_on)

    if total_deps > max_dependencies:
        errors.append(f"Total dependency count ({total_deps}) exceeds maximum allowed ({max_dependencies}).")

    # Validate individual dependencies
    for step in planned_steps:
        for dep_id in step.depends_on:
            if dep_id == step.step_id:
                errors.append(f"Self-dependency detected: Step '{step.step_id}' cannot depend on itself.")
            elif dep_id not in step_ids:
                errors.append(f"Unknown dependency: Step '{step.step_id}' depends on non-existent step '{dep_id}'.")

    if errors:
        return False, errors

    # Check for cycles using Kahn's algorithm (Topological sort)
    in_degree: Dict[str, int] = {s_id: 0 for s_id in step_ids}
    adj: Dict[str, List[str]] = {s_id: [] for s_id in step_ids}

    for step in planned_steps:
        for dep in step.depends_on:
            adj[dep].append(step.step_id)
            in_degree[step.step_id] += 1

    queue = [s_id for s_id, deg in in_degree.items() if deg == 0]
    visited_count = 0

    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(step_ids):
        errors.append("Dependency cycle detected: Planned steps do not form a strictly acyclic directed graph (DAG).")
        return False, errors

    return True, []


# =============================================================================
# 6. API REQUEST / RESPONSE / AUDIT CONTRACTS
# =============================================================================

class MissionCreateRequest(BaseModel):
    """Payload to propose or draft a new industrial mission."""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1, max_length=4000)
    mission_type: MissionType
    objective: str = Field(..., min_length=1, max_length=4000)
    plant_id: str = Field(..., min_length=1, max_length=128)
    constraints: List[MissionConstraint] = Field(default_factory=list, max_length=20)
    success_criteria: List[MissionSuccessCriterion] = Field(default_factory=list, max_length=20)
    planned_steps: List[MissionPlannedStep] = Field(default_factory=list, max_length=50)
    evidence_requirements: List[MissionEvidenceRequirement] = Field(default_factory=list, max_length=30)
    related_resources: Dict[str, List[str]] = Field(default_factory=dict)
    origin_reason: str = Field(..., min_length=1, max_length=1000)
    parent_incident_id: Optional[str] = Field(default=None, max_length=128)
    parent_rca_id: Optional[str] = Field(default=None, max_length=128)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @field_validator("plant_id")
    @classmethod
    def validate_request_plant_id(cls, v: str) -> str:
        return validate_plant_identifier(v)

    @field_validator("title", "description", "objective", "origin_reason")
    @classmethod
    def validate_request_text(cls, v: str, info) -> str:
        return _validate_safe_text(v, info.field_name) or v

    @field_validator("parent_incident_id", "parent_rca_id", "idempotency_key")
    @classmethod
    def validate_request_ids(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            _scan_for_secrets(v, info.field_name)
            if not re.match(r"^[A-Za-z0-9_\-\.]{1,128}$", v):
                raise ValueError(f"Invalid identifier format for '{info.field_name}': '{v}'.")
        return v

    @field_validator("related_resources")
    @classmethod
    def validate_request_related_resources(cls, v: Dict[str, List[str]]) -> Dict[str, List[str]]:
        return _validate_related_resources(v) or {}

    @field_validator("success_criteria")
    @classmethod
    def validate_criteria_initial_status(cls, v: List[MissionSuccessCriterion]) -> List[MissionSuccessCriterion]:
        if len(v) > 20:
            raise ValueError(f"Success criteria count ({len(v)}) exceeds maximum allowed (20).")
        for crit in v:
            if crit.status != CriterionStatus.UNKNOWN:
                raise ValueError(
                    f"Success criterion '{crit.criterion_id}' status cannot be self-certified as '{crit.status.value}'. "
                    "Only 'UNKNOWN' status is permitted for ordinary create and draft updates."
                )
            if crit.evaluation_notes and crit.evaluation_notes.strip():
                raise ValueError(
                    f"Client-supplied evaluation notes are not permitted on criterion '{crit.criterion_id}'. "
                    "Evaluation notes are server-authoritative."
                )
        return v

    @field_validator("planned_steps")
    @classmethod
    def validate_steps_initial_status(cls, v: List[MissionPlannedStep]) -> List[MissionPlannedStep]:
        if len(v) > 50:
            raise ValueError(f"Planned steps count ({len(v)}) exceeds maximum allowed (50).")
        for step in v:
            if step.status not in (StepStatus.PLANNED, StepStatus.PENDING):
                raise ValueError(
                    f"Planned step '{step.step_id}' status cannot be initialized to '{step.status.value}'. "
                    "Planned steps must begin in 'PLANNED' or 'PENDING' status."
                )
        return v


class MissionUpdateRequest(BaseModel):
    """Payload to update an editable mission draft."""
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    objective: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    constraints: Optional[List[MissionConstraint]] = Field(default=None, max_length=20)
    success_criteria: Optional[List[MissionSuccessCriterion]] = Field(default=None, max_length=20)
    planned_steps: Optional[List[MissionPlannedStep]] = Field(default=None, max_length=50)
    evidence_requirements: Optional[List[MissionEvidenceRequirement]] = Field(default=None, max_length=30)
    related_resources: Optional[Dict[str, List[str]]] = None
    update_reason: str = Field(..., min_length=1, max_length=1000)

    @field_validator("title", "description", "objective", "update_reason")
    @classmethod
    def validate_update_text(cls, v: Optional[str], info) -> Optional[str]:
        return _validate_safe_text(v, info.field_name)

    @field_validator("related_resources")
    @classmethod
    def validate_update_related_resources(cls, v: Optional[Dict[str, List[str]]]) -> Optional[Dict[str, List[str]]]:
        return _validate_related_resources(v)

    @field_validator("success_criteria")
    @classmethod
    def validate_update_criteria_status(cls, v: Optional[List[MissionSuccessCriterion]]) -> Optional[List[MissionSuccessCriterion]]:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError(f"Success criteria count ({len(v)}) exceeds maximum allowed (20).")
        for crit in v:
            if crit.status != CriterionStatus.UNKNOWN:
                raise ValueError(
                    f"Success criterion '{crit.criterion_id}' status cannot be self-certified as '{crit.status.value}'. "
                    "Only 'UNKNOWN' status is permitted for ordinary create and draft updates."
                )
            if crit.evaluation_notes and crit.evaluation_notes.strip():
                raise ValueError(
                    f"Client-supplied evaluation notes are not permitted on criterion '{crit.criterion_id}'. "
                    "Evaluation notes are server-authoritative."
                )
        return v

    @field_validator("planned_steps")
    @classmethod
    def validate_update_steps_status(cls, v: Optional[List[MissionPlannedStep]]) -> Optional[List[MissionPlannedStep]]:
        if v is None:
            return v
        if len(v) > 50:
            raise ValueError(f"Planned steps count ({len(v)}) exceeds maximum allowed (50).")
        for step in v:
            if step.status not in (StepStatus.PLANNED, StepStatus.PENDING):
                raise ValueError(
                    f"Planned step '{step.step_id}' status cannot claim unverified execution outcome status '{step.status.value}'. "
                    "Only 'PLANNED' or 'PENDING' status is permitted for ordinary draft updates."
                )
        return v


class MissionReviewRequest(BaseModel):
    """Payload to accept or reject a mission in REVIEW_REQUIRED state."""
    model_config = ConfigDict(extra="forbid")

    action: str = Field(..., pattern=r"^(ACCEPT|REJECT)$", description="'ACCEPT' or 'REJECT'")
    review_notes: str = Field(..., min_length=1, max_length=4000, description="Authoritative governance rationale")

    @field_validator("review_notes")
    @classmethod
    def validate_notes(cls, v: str) -> str:
        return _validate_safe_text(v, "review_notes") or v


class MissionValidationResponse(BaseModel):
    """Deterministic validation evaluation response."""
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    is_valid: bool
    status: MissionStatus
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    step_count: int
    dependency_count: int
    validated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MissionRevisionRecord(BaseModel):
    """Historical snapshot of a mission revision."""
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    revision: int
    tenant_id: str
    workspace_id: str
    plant_id: str
    snapshot_json: str
    change_reason: str
    changed_by: str
    created_at: str


class MissionAuditRecord(BaseModel):
    """Auditable mission lifecycle event ledger entry."""
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(default_factory=lambda: f"msnaud_{uuid.uuid4().hex[:16]}")
    mission_id: str
    revision: int
    tenant_id: str
    workspace_id: str
    plant_id: str
    event_type: str
    result: str
    actor_id: str
    actor_role: Optional[str] = None
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
