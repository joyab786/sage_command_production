# backend/data/schemas/verification_contract.py
"""
SageCommand V3 — Continuous Verification Engine Foundation Contracts (Prompt 36)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Defines canonical domain models, verification statuses, evidence assessment structures,
deterministic rule specifications, verification findings, and audit contracts.

Cardinal Invariants:
1. Verification is a read-only assessment of operational evidence; it NEVER mutates operational state,
   dispatches actions, or issues machine writes.
2. Tenant, workspace, and plant scope are strictly authoritative from caller identity and mission scope.
3. Verification findings are immutable historical assessments stored separately from mission definitions.
4. Missing, unverified, or conflicting evidence preserves uncertainty; it NEVER self-certifies success.
5. Client or LLM payloads cannot forge verification status, results, or evaluation timestamps.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =============================================================================
# 0. CONSTANTS & MANDATORY NOTICE
# =============================================================================

MANDATORY_VERIFICATION_NOTICE = (
    "A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES "
    "OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL."
)

SCHEMA_VERSION = "3.0.0"
RULE_SET_VERSION = "1.0.0"
EVALUATOR_VERSION = "1.0.0"

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

CANONICAL_ID_REGEX = re.compile(r"^[A-Za-z0-9_\-\.]{1,128}$")


def _scan_for_secrets(value: Optional[str], field_name: str) -> None:
    """Detects raw credentials, tokens, passwords, connection strings, and private keys."""
    if not value:
        return
    if _SECRET_PATTERNS.search(value):
        raise ValueError(
            f"Field '{field_name}' contains potential secret, credential, token, or connection string."
        )


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


def validate_identifier(v: str, field_name: str = "identifier") -> str:
    """Validates identifier format and scans for secrets."""
    if not v or not isinstance(v, str):
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    v = v.strip()
    _scan_for_secrets(v, field_name)
    if not CANONICAL_ID_REGEX.match(v):
        raise ValueError(
            f"Invalid identifier format for '{field_name}': '{v}'. Must be 1-128 alphanumeric characters, underscores, dashes, or dots."
        )
    return v


# =============================================================================
# 1. CENTRALIZED ENUMS
# =============================================================================

class VerificationStatus(str, Enum):
    """
    Explicit, distinct verification statuses for continuous verification.
    Preserves exact verification states without collapsing to simple booleans.
    """
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    INDETERMINATE = "INDETERMINATE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationTargetType(str, Enum):
    """Classification of verification evaluation target."""
    CRITERION = "CRITERION"
    STEP = "STEP"
    OVERALL_MISSION = "OVERALL_MISSION"


class FreshnessStatus(str, Enum):
    """Deterministic evidence freshness status."""
    CURRENT = "CURRENT"
    STALE = "STALE"
    TIMESTAMP_MISSING = "TIMESTAMP_MISSING"
    FRESHNESS_NOT_CONFIGURED = "FRESHNESS_NOT_CONFIGURED"
    FUTURE_DATED = "FUTURE_DATED"
    UNKNOWN = "UNKNOWN"


class QualityStatus(str, Enum):
    """Evidence data quality classification."""
    VALID = "VALID"
    UNVERIFIED = "UNVERIFIED"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class ScopeStatus(str, Enum):
    """Scope authorization matching status for evidence references."""
    AUTHORIZED = "AUTHORIZED"
    CROSS_TENANT = "CROSS_TENANT"
    CROSS_WORKSPACE = "CROSS_WORKSPACE"
    CROSS_PLANT = "CROSS_PLANT"
    UNTAGGED_PLANT = "UNTAGGED_PLANT"
    UNAUTHORIZED = "UNAUTHORIZED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class TriggerType(str, Enum):
    """Reason / channel initiating the verification run."""
    MANUAL = "MANUAL"
    AUTOMATED_CHECK = "AUTOMATED_CHECK"
    EVIDENCE_EVENT = "EVIDENCE_EVENT"
    GOVERNANCE_REVIEW = "GOVERNANCE_REVIEW"


class RuleType(str, Enum):
    """Deterministic, versioned rule types supported by the verification engine."""
    EVIDENCE_EXISTS = "EVIDENCE_EXISTS"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    EVIDENCE_FRESH = "EVIDENCE_FRESH"
    REQUIRED_EVIDENCE_PRESENT = "REQUIRED_EVIDENCE_PRESENT"
    REQUIRED_EVIDENCE_VALIDATED = "REQUIRED_EVIDENCE_VALIDATED"
    EVIDENCE_SCOPE_MATCH = "EVIDENCE_SCOPE_MATCH"
    REQUIRED_FIELDS_PRESENT = "REQUIRED_FIELDS_PRESENT"
    SOURCE_CONSISTENCY = "SOURCE_CONSISTENCY"


# =============================================================================
# 2. EVIDENCE ASSESSMENT CONTRACT
# =============================================================================

class EvidenceAssessment(BaseModel):
    """
    Evaluated quality, freshness, scope, and applicability of a single evidence record
    supporting a specific verification target.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., max_length=128, description="Identifier of the evaluated evidence item")
    source_type: str = Field(..., max_length=64, description="Originating subsystem type")
    source_reference: Optional[str] = Field(default=None, max_length=128, description="Reference in upstream system")
    observed_at: Optional[str] = Field(default=None, description="ISO-8601 observation timestamp")
    received_at: Optional[str] = Field(default=None, description="ISO-8601 reception timestamp")
    freshness_status: FreshnessStatus = Field(default=FreshnessStatus.UNKNOWN, description="Freshness evaluation outcome")
    freshness_seconds: Optional[float] = Field(default=None, ge=0.0, description="Computed age in seconds")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Applicable threshold in seconds")
    integrity_status: str = Field(default="UNKNOWN", max_length=64, description="Integrity check outcome (e.g. VALID, INVALID, UNVERIFIED)")
    scope_status: ScopeStatus = Field(default=ScopeStatus.UNKNOWN, description="Scope boundary matching status")
    classification_status: str = Field(default="UNKNOWN", max_length=64, description="Data classification clearance status")
    applicability_status: str = Field(default="UNKNOWN", max_length=64, description="Target applicability status")
    quality_status: QualityStatus = Field(default=QualityStatus.UNKNOWN, description="Overall quality classification")
    limitations: List[str] = Field(default_factory=list, max_length=20, description="Known caveats or limitations of this evidence")

    @field_validator("evidence_id")
    @classmethod
    def validate_ev_id(cls, v: str) -> str:
        return validate_identifier(v, "evidence_id")

    @field_validator("source_type", "source_reference", "integrity_status", "classification_status", "applicability_status")
    @classmethod
    def validate_text(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            return _validate_safe_text(v, info.field_name)
        return v


# =============================================================================
# 3. VERIFICATION RULE CONTRACT
# =============================================================================

class VerificationRule(BaseModel):
    """
    Deterministic, versioned rule specification for evaluating verification targets.
    """
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(..., max_length=64, description="Unique rule identifier")
    rule_version: str = Field(default="1.0.0", max_length=32, description="Semantic rule version")
    rule_type: RuleType = Field(..., description="Classification of deterministic verification rule")
    description: str = Field(..., min_length=1, max_length=1000, description="Human-readable rule objective")
    supported_target_types: List[VerificationTargetType] = Field(
        default_factory=lambda: [VerificationTargetType.CRITERION, VerificationTargetType.STEP],
        description="Target types this rule can evaluate"
    )
    required_evidence_types: List[str] = Field(default_factory=list, max_length=20, description="Expected evidence source types")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Max permitted evidence age in seconds")
    scope_requirements: Dict[str, Any] = Field(default_factory=dict, description="Scope validation requirements")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Deterministic rule parameters")

    @field_validator("rule_id")
    @classmethod
    def validate_rule_id(cls, v: str) -> str:
        return validate_identifier(v, "rule_id")

    @field_validator("description")
    @classmethod
    def validate_desc(cls, v: str) -> str:
        return _validate_safe_text(v, "description") or v


# =============================================================================
# 4. VERIFICATION FINDING CONTRACT
# =============================================================================

class VerificationFinding(BaseModel):
    """
    Traceable assessment outcome for a single criterion, step, or overall mission.
    """
    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(
        default_factory=lambda: f"vf_{uuid.uuid4().hex[:12]}",
        min_length=1,
        max_length=64,
        description="Unique finding identifier"
    )
    target_type: VerificationTargetType = Field(..., description="Target type evaluated")
    target_id: str = Field(..., min_length=1, max_length=128, description="Target identifier (e.g. crit_*, step_*, or mission_id)")
    status: VerificationStatus = Field(..., description="Deterministic verification status")
    evidence_references: List[str] = Field(default_factory=list, max_length=20, description="IDs of evidence records assessed")
    evidence_assessments: List[EvidenceAssessment] = Field(default_factory=list, max_length=20, description="Detailed evidence evaluations")
    rule_id: str = Field(..., max_length=64, description="ID of rule applied")
    rule_version: str = Field(default="1.0.0", max_length=32, description="Version of rule applied")
    explanation: str = Field(..., min_length=1, max_length=2000, description="Bounded, human-readable verification rationale")
    limitations: List[str] = Field(default_factory=list, max_length=20, description="Identified limitations, caveats, or missing metadata")
    evaluated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 evaluation timestamp"
    )

    @field_validator("finding_id", "target_id", "rule_id")
    @classmethod
    def validate_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("explanation")
    @classmethod
    def validate_expl(cls, v: str) -> str:
        return _validate_safe_text(v, "explanation") or v


# =============================================================================
# 5. VERIFICATION PROVENANCE CONTRACT
# =============================================================================

class VerificationProvenance(BaseModel):
    """
    Metadata recording exact versions, inputs, and limitations to ensure reproducibility.
    """
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(..., max_length=64, description="Associated verification run identifier")
    mission_id: str = Field(..., max_length=64, description="Target mission identifier")
    mission_revision: int = Field(..., ge=1, description="Exact mission revision evaluated")
    rule_set_version: str = Field(default=RULE_SET_VERSION, max_length=32, description="Rule-set version used")
    evaluator_version: str = Field(default=EVALUATOR_VERSION, max_length=32, description="Verification engine code version")
    evidence_ids: List[str] = Field(default_factory=list, max_length=100, description="All evidence identifiers consumed")
    evidence_timestamps: Dict[str, Optional[str]] = Field(default_factory=dict, description="Observed timestamps per evidence ID")
    evaluation_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 evaluation timestamp"
    )
    limitations: List[str] = Field(default_factory=list, max_length=30, description="Overall run limitations and gaps")

    @field_validator("verification_id", "mission_id")
    @classmethod
    def validate_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


# =============================================================================
# 6. CANONICAL VERIFICATION RUN CONTRACT
# =============================================================================

class VerificationRun(BaseModel):
    """
    Authoritative snapshot of a bounded verification run evaluating a mission revision.
    """
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(
        default_factory=lambda: f"vrun_{uuid.uuid4().hex[:16]}",
        min_length=1,
        max_length=64,
        description="Unique verification run identifier"
    )
    schema_version: str = Field(default=SCHEMA_VERSION, description="Contract schema version")
    mission_id: str = Field(..., min_length=1, max_length=64, description="Target mission identifier")
    mission_revision: int = Field(..., ge=1, description="Exact mission revision evaluated")
    verification_scope: str = Field(default="FULL_MISSION", max_length=64, description="Scope of evaluation (FULL_MISSION, CRITERIA_ONLY, STEPS_ONLY, or target_id)")
    status: VerificationStatus = Field(default=VerificationStatus.PENDING, description="Overall verification outcome status")
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 execution start timestamp"
    )
    completed_at: Optional[str] = Field(default=None, description="ISO-8601 completion timestamp")
    requested_by: str = Field(..., min_length=1, max_length=128, description="Authoritative identity of requesting actor")
    tenant_id: str = Field(..., min_length=1, max_length=128, description="Authoritative tenant isolation scope")
    workspace_id: str = Field(..., min_length=1, max_length=128, description="Authoritative workspace isolation scope")
    plant_id: str = Field(..., min_length=1, max_length=128, description="Authoritative plant isolation scope")
    session_id: Optional[str] = Field(default=None, max_length=128, description="Optional caller session identifier")
    trigger_type: TriggerType = Field(default=TriggerType.MANUAL, description="Trigger mechanism for this run")
    rule_set_version: str = Field(default=RULE_SET_VERSION, max_length=32, description="Version of rules applied")
    summary: str = Field(default="", max_length=2000, description="Executive summary of findings")
    target_count: int = Field(default=0, ge=0, description="Total targets evaluated")
    verified_count: int = Field(default=0, ge=0, description="Targets reaching VERIFIED status")
    unverified_count: int = Field(default=0, ge=0, description="Targets reaching NOT_VERIFIED status")
    indeterminate_count: int = Field(default=0, ge=0, description="Targets reaching INDETERMINATE status")
    blocked_count: int = Field(default=0, ge=0, description="Targets reaching BLOCKED status")
    failed_count: int = Field(default=0, ge=0, description="Targets reaching FAILED status")
    findings: List[VerificationFinding] = Field(default_factory=list, max_length=100, description="Detailed findings per target")
    provenance: VerificationProvenance = Field(..., description="Reproducibility provenance record")
    idempotency_key: Optional[str] = Field(default=None, max_length=128, description="Idempotency key if supplied")
    is_diagnostic: bool = Field(
        default=False,
        description="Indicates whether this run was a diagnostic check (e.g. EVIDENCE_EXISTS) rather than authoritative mission verification."
    )
    diagnostic_status: Optional[VerificationStatus] = Field(
        default=None,
        description="Machine-readable diagnostic status outcome when is_diagnostic is True."
    )
    diagnostic_outcome: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Machine-readable diagnostic outcome classification (e.g. 'CONFIRMED', 'NOT_FOUND', 'BLOCKED')."
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 creation timestamp"
    )

    @field_validator("verification_id", "mission_id", "tenant_id", "workspace_id", "plant_id")
    @classmethod
    def validate_run_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("summary")
    @classmethod
    def validate_sum(cls, v: str) -> str:
        return _validate_safe_text(v, "summary") or v


# =============================================================================
# 7. VERIFICATION AUDIT LEDGER CONTRACT
# =============================================================================

class VerificationAuditRecord(BaseModel):
    """
    Append-only audit ledger entry for verification lifecycle events.
    """
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(
        default_factory=lambda: f"vfaud_{uuid.uuid4().hex[:16]}",
        min_length=1,
        max_length=64,
        description="Unique audit record identifier"
    )
    verification_id: str = Field(..., min_length=1, max_length=64)
    mission_id: str = Field(..., min_length=1, max_length=64)
    mission_revision: int = Field(..., ge=1)
    tenant_id: str = Field(..., min_length=1, max_length=128)
    workspace_id: str = Field(..., min_length=1, max_length=128)
    plant_id: str = Field(..., min_length=1, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    result: str = Field(..., min_length=1, max_length=32)
    actor_id: str = Field(..., min_length=1, max_length=128)
    actor_role: Optional[str] = Field(default=None, max_length=64)
    request_id: Optional[str] = Field(default=None, max_length=128)
    trace_id: Optional[str] = Field(default=None, max_length=128)
    details: Dict[str, Any] = Field(default_factory=dict)
    checksum: str = Field(default="", max_length=64, description="SHA-256 integrity checksum")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 timestamp"
    )

    @field_validator("audit_id", "verification_id", "mission_id", "tenant_id", "workspace_id", "plant_id")
    @classmethod
    def validate_audit_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @model_validator(mode="after")
    def compute_checksum(self) -> "VerificationAuditRecord":
        if not self.checksum:
            raw = f"{self.verification_id}:{self.mission_id}:{self.mission_revision}:{self.event_type}:{self.actor_id}:{self.timestamp}"
            self.checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self


# =============================================================================
# 8. API REQUEST / RESPONSE CONTRACTS
# =============================================================================

PROHIBITED_CALLER_RULE_PARAMETERS: Set[str] = {
    # Evidence requirements & optionality overrides
    "optional_evidence_ids",
    "required_evidence_ids",
    "required_evidence_types",
    "evidence_payloads",
    "evidence_ids",
    "evidence_records",
    # Scope and plant isolation overrides
    "mission_scope",
    "scope",
    "tenant_id",
    "workspace_id",
    "plant_id",
    "session_id",
    # Classification and clearance decisions
    "classification",
    "classification_status",
    "clearance",
    "clearance_level",
    # Authorization & assessment status overrides
    "authorization_status",
    "scope_status",
    "integrity_status",
    "quality_status",
    "freshness_status",
    "status",
    "verification_status",
    "risk_score",
    "risk_level",
}


class VerificationRequest(BaseModel):
    """
    Payload to request continuous verification of a mission.
    Server derives tenant, workspace, plant, requested_by, and initial status authoritatively.
    Client values for identity or outcome statuses are strictly forbidden.
    """
    model_config = ConfigDict(extra="forbid")

    target_type: Optional[VerificationTargetType] = Field(
        default=None,
        description="Optional filter: CRITERION, STEP, or None for full mission"
    )
    target_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional target identifier to evaluate a single criterion or step"
    )
    trigger_type: TriggerType = Field(
        default=TriggerType.MANUAL,
        description="Trigger classification"
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional client idempotency key for safe retries"
    )
    rule_type: Optional[RuleType] = Field(
        default=None,
        description="Optional explicit rule type override for evaluation (e.g. EVIDENCE_FRESH, EVIDENCE_VALIDATED, SOURCE_CONSISTENCY)"
    )
    rule_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional deterministic parameters for rule evaluation"
    )
    expected_mission_revision: Optional[int] = Field(
        default=None,
        ge=1,
        description="Optional expected mission revision to detect concurrent modification"
    )
    freshness_threshold_override_seconds: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=86400.0 * 365,  # max 1 year
        description="Optional custom freshness threshold in seconds (bounds: 1.0 to 31,536,000)"
    )

    @field_validator("target_id", "idempotency_key")
    @classmethod
    def validate_request_ids(cls, v: Optional[str], info) -> Optional[str]:
        if v is not None:
            return validate_identifier(v, info.field_name)
        return v

    @field_validator("rule_parameters")
    @classmethod
    def validate_rule_parameters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            return {}
        if len(v) > 20:
            raise ValueError(f"Rule parameters count ({len(v)}) exceeds maximum permitted (20).")
        for k in v:
            if not isinstance(k, str):
                raise ValueError("Rule parameter keys must be strings.")
            if k.lower() in {p.lower() for p in PROHIBITED_CALLER_RULE_PARAMETERS}:
                raise ValueError(
                    f"Prohibited rule parameter '{k}'. "
                    f"Callers cannot override authoritative verification requirements, payloads, or scope boundaries."
                )
        return v


class VerificationRunSummary(BaseModel):
    """Lightweight summary of a verification run for listing endpoints."""
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    mission_id: str
    mission_revision: int
    verification_scope: str
    status: VerificationStatus
    trigger_type: TriggerType
    started_at: str
    completed_at: Optional[str] = None
    target_count: int
    verified_count: int
    unverified_count: int
    indeterminate_count: int
    blocked_count: int
    failed_count: int
    summary: str
    is_diagnostic: bool = False
    diagnostic_status: Optional[VerificationStatus] = None
    diagnostic_outcome: Optional[str] = None


class VerificationFindingsResponse(BaseModel):
    """Paginated or complete findings list for a verification run."""
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    mission_id: str
    mission_revision: int
    overall_status: VerificationStatus
    total_findings: int
    findings: List[VerificationFinding]
    is_diagnostic: bool = False
    diagnostic_status: Optional[VerificationStatus] = None
    diagnostic_outcome: Optional[str] = None


class VerificationCancelRequest(BaseModel):
    """Payload to cancel an in-progress verification run."""
    model_config = ConfigDict(extra="forbid")

    cancel_reason: str = Field(..., min_length=1, max_length=1000, description="Operational justification for cancellation")

    @field_validator("cancel_reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        return _validate_safe_text(v, "cancel_reason") or v
