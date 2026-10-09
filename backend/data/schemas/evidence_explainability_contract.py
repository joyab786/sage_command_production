# backend/data/schemas/evidence_explainability_contract.py
"""
SageCommand V3 — Evidence and Explainability Intelligence Foundation Contracts (Prompt 31)

ANALYTICAL EXPLAINABILITY AND EVIDENCE TRACING ONLY.
Defines typed, validated contracts for the Evidence & Explainability lifecycle:
EvidenceRecord, EvidenceReference, EvidenceSourceType, EvidenceLineageEdge,
EvidenceLineageGraph, EvidenceTransformation, EvidenceProvenance,
EvidenceValidationResult, EvidenceFreshnessAssessment, EvidenceRejection,
EvidenceConflict, EvidenceGap, EvidenceContribution, ExplanationNode,
ExplanationEdge, ExplanationGraph, ExplanationRequest, ExplanationResult,
ExplanationLimitation, and EvidenceAuditRecord.

Cardinal Invariant:
An explanation describes the evidence and reasoning behind an outcome.
It does NOT authorize an action, change a decision policy, or execute a recommendation.
The Evidence and Explainability layer is a READ-ONLY analytical integration layer.
It NEVER mutates underlying operational or source subsystem records.

Notice:
EXPLAINABILITY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone
import hashlib
import json
import math
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =============================================================================
# 0. CONSTANTS & BOUNDARY NOTICE
# =============================================================================

MANDATORY_EXPLAINABILITY_NOTICE = "EXPLAINABILITY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED"
ALGORITHM_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

FORBIDDEN_TRANSFORMATION_KEYWORDS = {
    "EXECUTE",
    "DISPATCH",
    "ACTUATE",
    "WRITE_PLC",
    "MUTATE",
    "SUBMIT_ORDER",
    "EXECUTE_WORK_ORDER",
    "TRIGGER_ACTION",
    "EVAL",
    "EXEC",
    "__IMPORT__",
    "OS.SYSTEM",
    "SUBPROCESS",
}


# =============================================================================
# 1. ENUMS
# =============================================================================

class EvidenceProvenance(str, Enum):
    """
    Controlled, rigorous provenance classifications for evidence consumed and explained.
    Preserves true source nature across wrapped analytical layers.
    """
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    FORECAST = "FORECAST"
    SIMULATED = "SIMULATED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class EvidenceSourceType(str, Enum):
    """
    Controlled registry of supported evidence source types across SageCommand V3 subsystems.
    """
    DECISION_ENGINE = "DECISION_ENGINE"
    OPTIMIZATION = "OPTIMIZATION"
    WHAT_IF_SIMULATION = "WHAT_IF_SIMULATION"
    SENSOR_FUSION = "SENSOR_FUSION"
    SUSTAINABILITY = "SUSTAINABILITY"
    FINANCIAL_IMPACT = "FINANCIAL_IMPACT"
    SLA_CUSTOMER_RISK = "SLA_CUSTOMER_RISK"
    SUPPLIER_RISK = "SUPPLIER_RISK"
    DEMAND_FORECASTING = "DEMAND_FORECASTING"
    PREDICTIVE_MAINTENANCE = "PREDICTIVE_MAINTENANCE"
    BLAST_RADIUS = "BLAST_RADIUS"
    ROOT_CAUSE_ANALYSIS = "ROOT_CAUSE_ANALYSIS"
    INCIDENT_MANAGEMENT = "INCIDENT_MANAGEMENT"
    EVENT_BUS = "EVENT_BUS"
    ANOMALY_DETECTION = "ANOMALY_DETECTION"
    DATA_QUALITY = "DATA_QUALITY"
    DIGITAL_TWIN = "DIGITAL_TWIN"
    OPERATIONAL_KNOWLEDGE_GRAPH = "OPERATIONAL_KNOWLEDGE_GRAPH"
    INDUSTRIAL_ONTOLOGY = "INDUSTRIAL_ONTOLOGY"
    MANUAL_OPERATOR = "MANUAL_OPERATOR"
    EXTERNAL_SYSTEM = "EXTERNAL_SYSTEM"


class EvidenceValidationStatus(str, Enum):
    """Structured evidence validation outcomes."""
    VALID = "VALID"
    STALE = "STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    CONFLICTING = "CONFLICTING"
    INACCESSIBLE = "INACCESSIBLE"
    INSUFFICIENT_METADATA = "INSUFFICIENT_METADATA"
    UNKNOWN = "UNKNOWN"


class LineageEdgeType(str, Enum):
    """Relationship categories between evidence records."""
    DERIVED_FROM = "DERIVED_FROM"
    SIMULATED_FROM = "SIMULATED_FROM"
    AGGREGATED_FROM = "AGGREGATED_FROM"
    CORRELATED_WITH = "CORRELATED_WITH"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"
    INPUT_TO = "INPUT_TO"
    CONSTRAINED_BY = "CONSTRAINED_BY"


class ExplanationNodeType(str, Enum):
    """Node types in an explanation graph."""
    TARGET = "TARGET"
    EVIDENCE = "EVIDENCE"
    ASSESSMENT = "ASSESSMENT"
    CRITERION = "CRITERION"
    OPTION = "OPTION"
    CONSTRAINT = "CONSTRAINT"
    POLICY = "POLICY"
    ASSUMPTION = "ASSUMPTION"
    TRANSFORMATION = "TRANSFORMATION"


class ExplanationEdgeRelation(str, Enum):
    """Directed edge relationships in an explanation graph."""
    SUPPORTS = "SUPPORTS"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    EVALUATES = "EVALUATES"
    VIOLATES = "VIOLATES"
    SATISFIES = "SATISFIES"
    EXCLUDES = "EXCLUDES"
    DERIVED_FROM = "DERIVED_FROM"
    CONTRADICTS = "CONTRADICTS"


class SeverityLevel(str, Enum):
    """Severity classification for limitations, conflicts, and rejections."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"


class GapType(str, Enum):
    """Categorization of evidence gaps."""
    MISSING_PARENT = "MISSING_PARENT"
    UNAVAILABLE_RECORD = "UNAVAILABLE_RECORD"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    UNRESOLVED_INPUT = "UNRESOLVED_INPUT"


class ConflictType(str, Enum):
    """Categorization of evidence conflicts."""
    CONTRADICTORY_VALUES = "CONTRADICTORY_VALUES"
    TEMPORAL_INCONSISTENCY = "TEMPORAL_INCONSISTENCY"
    SEMANTIC_MISMATCH = "SEMANTIC_MISMATCH"
    UNRESOLVED_DISAGREEMENT = "UNRESOLVED_DISAGREEMENT"


# =============================================================================
# 2. HELPER VALIDATORS
# =============================================================================

def validate_finite_number(v: Any, field_name: str) -> float:
    """Ensure numerical values are valid, non-null, and finite (no NaN or Inf)."""
    if v is None:
        raise ValueError(f"Field '{field_name}' cannot be null.")
    try:
        val = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"Field '{field_name}' must be a numerical value, got {type(v).__name__}.")
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Field '{field_name}' must be finite, got {val}.")
    return val


def validate_identifier(v: str, field_name: str) -> str:
    """Ensure identifier strings are non-empty and well-formed."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    cleaned = v.strip()
    if len(cleaned) > 256:
        raise ValueError(f"Field '{field_name}' exceeds maximum length of 256 characters.")
    return cleaned


def validate_iso_timestamp(v: str, field_name: str) -> str:
    """Validate ISO 8601 timestamp string and force timezone awareness."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty ISO 8601 string.")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception as e:
        raise ValueError(f"Field '{field_name}' must be a valid ISO 8601 timestamp: {e}")


def validate_proportional_score(v: Any, field_name: str) -> float:
    """Validate a score between 0.0 and 1.0 inclusive."""
    val = validate_finite_number(v, field_name)
    if not (0.0 <= val <= 1.0):
        raise ValueError(f"Field '{field_name}' must be between 0.0 and 1.0, got {val}.")
    return val


# =============================================================================
# 3. CORE CONTRACT MODELS
# =============================================================================

class EvidenceTransformation(BaseModel):
    """
    Describes an analytical transformation or mathematical derivation applied to evidence.
    Strictly declarative; rejects executable expressions and forbidden actuation keywords.
    """
    model_config = ConfigDict(extra="forbid")

    transformation_id: str = Field(description="Unique transformation identifier.")
    transformation_type: str = Field(description="Transformation type: AGGREGATION, NORMALIZATION, FILTER, FUSION, SOLVER, etc.")
    description: str = Field(default="", description="Human-readable description of the transformation.")
    input_keys: List[str] = Field(default_factory=list, description="Names/keys of input features consumed.")
    output_keys: List[str] = Field(default_factory=list, description="Names/keys of output metrics produced.")
    algorithm_version: str = Field(default=ALGORITHM_VERSION, description="Version of transformation algorithm.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Declarative parameters used.")

    @field_validator("transformation_id", "transformation_type")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("parameters")
    @classmethod
    def check_parameters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        for key, val in v.items():
            for forbidden in FORBIDDEN_TRANSFORMATION_KEYWORDS:
                if forbidden in key.upper():
                    raise ValueError(f"Transformation parameter '{key}' contains forbidden keyword.")
                if isinstance(val, str) and forbidden in val.upper():
                    raise ValueError(f"Transformation parameter value for '{key}' contains forbidden keyword.")
        return v


class EvidenceRecord(BaseModel):
    """
    Canonical evidence record representing an observation, assessment, or derivation.
    Immutable, deterministic snapshot with scope, timestamps, quality, and provenance.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Deterministic evidence identifier.")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope if applicable.")
    source_type: EvidenceSourceType = Field(description="Subsystem that produced the evidence.")
    source_record_id: str = Field(description="Primary identifier of source record in upstream subsystem.")
    title: str = Field(description="Human-readable title or summary.")
    description: str = Field(default="", description="Detailed narrative description.")
    observed_at: Optional[str] = Field(default=None, description="ISO 8601 observation timestamp.")
    received_at: Optional[str] = Field(default=None, description="ISO 8601 ingestion timestamp.")
    assessed_at: Optional[str] = Field(default=None, description="ISO 8601 analytical assessment timestamp.")
    valid_until: Optional[str] = Field(default=None, description="ISO 8601 temporal expiration timestamp.")
    provenance: EvidenceProvenance = Field(default=EvidenceProvenance.OBSERVED, description="Provenance classification.")
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Data quality score (0.0 to 1.0).")
    freshness_seconds: Optional[float] = Field(default=None, ge=0.0, description="Age in seconds relative to evaluation.")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence in this evidence item.")
    fingerprint: str = Field(default="", description="Cryptographic SHA-256 fingerprint of evidence content.")
    parent_evidence_ids: List[str] = Field(default_factory=list, description="IDs of direct parent evidence records.")
    transformations: List[EvidenceTransformation] = Field(default_factory=list, description="Transformations applied.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Extracted analytical payload fields.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata.")

    @field_validator("evidence_id", "tenant_id", "workspace_id", "source_record_id", "title")
    @classmethod
    def check_required_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("plant_id")
    @classmethod
    def check_plant(cls, v: Optional[str], info) -> Optional[str]:
        return validate_identifier(v, info.field_name) if v else None

    @field_validator("observed_at", "received_at", "assessed_at", "valid_until")
    @classmethod
    def check_timestamps(cls, v: Optional[str], info) -> Optional[str]:
        return validate_iso_timestamp(v, info.field_name) if v else None

    @field_validator("quality_score", "confidence_score", mode="before")
    @classmethod
    def check_proportions(cls, v: Any, info) -> float:
        return validate_proportional_score(v, info.field_name)

    @field_validator("freshness_seconds", mode="before")
    @classmethod
    def check_freshness(cls, v: Any) -> Optional[float]:
        if v is not None:
            val = validate_finite_number(v, "freshness_seconds")
            if val < 0.0:
                raise ValueError("freshness_seconds must be non-negative.")
            return val
        return None


class EvidenceReference(BaseModel):
    """
    Lightweight reference pointing to an evidence item supporting a conclusion or criterion.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Evidence identifier.")
    source_type: EvidenceSourceType = Field(description="Subsystem producing evidence.")
    source_record_id: str = Field(description="Source record primary key.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    timestamp: str = Field(description="Observation or assessment timestamp.")
    provenance: EvidenceProvenance = Field(default=EvidenceProvenance.OBSERVED, description="Provenance type.")
    weight: float = Field(default=1.0, ge=0.0, description="Relative contribution weight.")
    role: str = Field(default="SUPPORTING", description="Role: SUPPORTING, REFUTING, CONTEXTUAL, CRITERION_INPUT, CONSTRAINT_INPUT, BASELINE.")
    criterion_id: Optional[str] = Field(default=None, description="Associated criterion ID if relevant.")
    option_id: Optional[str] = Field(default=None, description="Associated option ID if relevant.")

    @field_validator("evidence_id", "source_record_id", "tenant_id", "workspace_id", "timestamp")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        if info.field_name == "timestamp":
            return validate_iso_timestamp(v, info.field_name)
        return validate_identifier(v, info.field_name)

    @field_validator("weight", mode="before")
    @classmethod
    def check_weight(cls, v: Any) -> float:
        val = validate_finite_number(v, "weight")
        if val < 0.0:
            raise ValueError("weight must be non-negative.")
        return val


class EvidenceLineageEdge(BaseModel):
    """
    Directed lineage edge from parent evidence to child evidence or assessment.
    """
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(description="Unique edge identifier.")
    source_evidence_id: str = Field(description="Parent / source evidence ID.")
    target_evidence_id: str = Field(description="Child / derived evidence ID.")
    edge_type: LineageEdgeType = Field(description="Lineage relationship category.")
    transformation: Optional[EvidenceTransformation] = Field(default=None, description="Transformation applied across this edge.")
    weight: float = Field(default=1.0, description="Lineage relationship weight.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Edge metadata.")

    @field_validator("edge_id", "source_evidence_id", "target_evidence_id")
    @classmethod
    def check_edge_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("weight", mode="before")
    @classmethod
    def check_weight(cls, v: Any) -> float:
        val = validate_finite_number(v, "weight")
        if val < 0.0:
            raise ValueError("weight must be non-negative.")
        return val


class EvidenceLineageGraph(BaseModel):
    """
    Bounded, acyclic, deterministic evidence lineage graph.
    """
    model_config = ConfigDict(extra="forbid")

    graph_id: str = Field(description="Unique graph identifier.")
    root_id: str = Field(description="Root evidence or assessment identifier.")
    tenant_id: str = Field(description="Tenant isolation boundary.")
    workspace_id: str = Field(description="Workspace boundary.")
    plant_id: Optional[str] = Field(default=None, description="Plant boundary.")
    nodes: List[EvidenceRecord] = Field(default_factory=list, description="All evidence nodes in graph.")
    edges: List[EvidenceLineageEdge] = Field(default_factory=list, description="Directed lineage edges.")
    depth: int = Field(default=0, ge=0, description="Maximum traversal depth from root.")
    fingerprint: str = Field(default="", description="Deterministic SHA-256 graph fingerprint.")
    has_cycles: bool = Field(default=False, description="Whether cycle was detected and resolved.")
    unresolved_references: List[str] = Field(default_factory=list, description="Missing or unresolvable parent IDs.")
    is_truncated: bool = Field(default=False, description="Whether graph traversal hit max depth or max node limit.")


class EvidenceFreshnessAssessment(BaseModel):
    """
    Deterministic freshness check of an evidence record relative to evaluation timestamp.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Evidence identifier.")
    observed_at: Optional[str] = Field(default=None, description="Original observation timestamp.")
    assessed_at: str = Field(description="Timestamp against which freshness was evaluated.")
    age_seconds: float = Field(ge=0.0, description="Computed age in seconds.")
    freshness_threshold_seconds: float = Field(ge=0.0, description="Configured freshness threshold in seconds.")
    is_fresh: bool = Field(description="True if age <= freshness_threshold_seconds.")
    is_future_dated: bool = Field(default=False, description="True if evidence timestamp > assessed_at.")

    @field_validator("age_seconds", "freshness_threshold_seconds", mode="before")
    @classmethod
    def check_seconds(cls, v: Any, info) -> float:
        val = validate_finite_number(v, info.field_name)
        if val < 0.0:
            raise ValueError(f"Field '{info.field_name}' must be non-negative.")
        return val


class EvidenceRejection(BaseModel):
    """
    Explicit record of why evidence was rejected or excluded from explanation.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Rejected evidence identifier.")
    reason_code: str = Field(description="Structured rejection reason code: FUTURE_DATED, STALE, LOW_QUALITY, CROSS_TENANT, etc.")
    explanation: str = Field(description="Human-readable explanation for rejection.")
    severity: SeverityLevel = Field(default=SeverityLevel.MEDIUM, description="Severity of rejection.")

    @field_validator("evidence_id", "reason_code", "explanation")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class EvidenceConflict(BaseModel):
    """
    Explicit contradiction or inconsistency detected between evidence items.
    """
    model_config = ConfigDict(extra="forbid")

    conflict_id: str = Field(description="Unique conflict identifier.")
    evidence_ids: List[str] = Field(description="Conflicting evidence identifiers.")
    conflict_type: ConflictType = Field(description="Category of conflict.")
    description: str = Field(description="Detailed explanation of contradiction.")
    severity: SeverityLevel = Field(default=SeverityLevel.MEDIUM, description="Severity of conflict.")

    @field_validator("conflict_id", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("evidence_ids")
    @classmethod
    def check_ids(cls, v: List[str]) -> List[str]:
        if len(v) < 2:
            raise ValueError("Conflict must involve at least two evidence items.")
        return v


class EvidenceGap(BaseModel):
    """
    Explicitly identified missing evidence, unavailable parent, or unresolved dependency.
    """
    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(description="Unique gap identifier.")
    target_type: str = Field(description="Target subsystem or entity.")
    target_id: str = Field(description="Target record or missing parent ID.")
    description: str = Field(description="Detailed explanation of gap.")
    gap_type: GapType = Field(description="Category of evidence gap.")
    impact: str = Field(default="PARTIAL_EXPLANATION", description="Impact on conclusion or explanation.")

    @field_validator("gap_id", "target_type", "target_id", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class EvidenceValidationResult(BaseModel):
    """
    Validation outcome for a single evidence item.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Evidence identifier.")
    status: EvidenceValidationStatus = Field(description="Structured validation outcome.")
    is_valid: bool = Field(description="True if evidence passed all eligibility criteria.")
    rejection_reasons: List[str] = Field(default_factory=list, description="Reason codes if excluded.")
    freshness_assessment: Optional[EvidenceFreshnessAssessment] = Field(default=None, description="Freshness evaluation.")
    evaluated_at: str = Field(description="ISO 8601 evaluation timestamp.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Validation diagnostic details.")

    @field_validator("evidence_id")
    @classmethod
    def check_id(cls, v: str) -> str:
        return validate_identifier(v, "evidence_id")

    @field_validator("evaluated_at")
    @classmethod
    def check_ts(cls, v: str) -> str:
        return validate_iso_timestamp(v, "evaluated_at")


class EvidenceContribution(BaseModel):
    """
    Quantified contribution of an evidence item toward an analytical criterion or outcome.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Evidence item identifier.")
    target_id: str = Field(description="Target decision, alternative, or outcome identifier.")
    target_type: str = Field(description="Target analytical category.")
    criterion_id: Optional[str] = Field(default=None, description="Associated criterion ID.")
    option_id: Optional[str] = Field(default=None, description="Associated option ID.")
    weight: float = Field(default=1.0, description="Normalized importance weight.")
    contribution_score: float = Field(default=0.0, description="Quantified score contribution.")
    explanation: str = Field(default="", description="Narrative rationale for contribution.")

    @field_validator("evidence_id", "target_id", "target_type")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("weight", "contribution_score", mode="before")
    @classmethod
    def check_numbers(cls, v: Any, info) -> float:
        return validate_finite_number(v, info.field_name)


class ExplanationNode(BaseModel):
    """
    Node in the human-facing explanation graph (criteria, options, evidence, constraints, policies).
    """
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(description="Unique node identifier.")
    node_type: ExplanationNodeType = Field(description="Node category.")
    title: str = Field(description="Display title.")
    provenance: EvidenceProvenance = Field(default=EvidenceProvenance.OBSERVED, description="Provenance type.")
    status: str = Field(default="ACTIVE", description="Node status: ACTIVE, EXCLUDED, VIOLATED, SATISFIED, RECOMMENDED.")
    score: Optional[float] = Field(default=None, description="Associated score or weight if applicable.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Node details.")

    @field_validator("node_id", "title")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("score", mode="before")
    @classmethod
    def check_score(cls, v: Optional[float]) -> Optional[float]:
        return validate_finite_number(v, "score") if v is not None else None


class ExplanationEdge(BaseModel):
    """
    Directed relationship between explanation nodes.
    """
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(description="Unique edge identifier.")
    from_node_id: str = Field(description="Source explanation node ID.")
    to_node_id: str = Field(description="Target explanation node ID.")
    relation: ExplanationEdgeRelation = Field(description="Relationship category.")
    weight: Optional[float] = Field(default=1.0, description="Relationship strength/weight.")
    notes: Optional[str] = Field(default=None, description="Explanatory text.")

    @field_validator("edge_id", "from_node_id", "to_node_id")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("weight", mode="before")
    @classmethod
    def check_weight(cls, v: Optional[float]) -> Optional[float]:
        return validate_finite_number(v, "weight") if v is not None else None


class ExplanationGraph(BaseModel):
    """
    Complete explanation graph connecting conclusions, criteria, options, and supporting evidence.
    """
    model_config = ConfigDict(extra="forbid")

    graph_id: str = Field(description="Unique explanation graph identifier.")
    nodes: List[ExplanationNode] = Field(default_factory=list, description="All explanation nodes.")
    edges: List[ExplanationEdge] = Field(default_factory=list, description="All directed explanation edges.")
    fingerprint: str = Field(default="", description="Cryptographic fingerprint of explanation graph.")


class ExplanationLimitation(BaseModel):
    """
    Explicit boundary condition, assumption, or analytical limitation.
    """
    model_config = ConfigDict(extra="forbid")

    limitation_id: str = Field(description="Unique limitation identifier.")
    code: str = Field(description="Structured limitation code: STALE_DATA, INSUFFICIENT_EVIDENCE, ASSUMPTION_UNVERIFIED, etc.")
    description: str = Field(description="Detailed limitation description.")
    severity: SeverityLevel = Field(default=SeverityLevel.MEDIUM, description="Limitation severity.")
    mitigation: Optional[str] = Field(default=None, description="Recommended operator review or mitigation action.")

    @field_validator("limitation_id", "code", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


# =============================================================================
# 4. REQUEST & RESPONSE MODELS
# =============================================================================

class ExplanationRequest(BaseModel):
    """
    Request payload to generate a deterministic evidence explanation.
    """
    model_config = ConfigDict(extra="forbid")

    target_type: EvidenceSourceType = Field(description="Analytical subsystem to explain.")
    target_id: str = Field(description="Primary key of target record to explain (decision_id, optimization_id, etc.).")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope.")
    assessment_timestamp: Optional[str] = Field(default=None, description="Fixed evaluation timestamp.")
    depth_limit: Optional[int] = Field(default=5, ge=1, le=20, description="Max traversal depth in lineage graph.")
    include_lineage: bool = Field(default=True, description="Whether to include full lineage graph.")
    include_validation: bool = Field(default=True, description="Whether to run full evidence validation pipeline.")
    include_excluded: bool = Field(default=True, description="Whether to include rejected/stale evidence.")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Custom freshness threshold in seconds.")

    @field_validator("target_id", "tenant_id", "workspace_id")
    @classmethod
    def check_required_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("plant_id")
    @classmethod
    def check_plant(cls, v: Optional[str], info) -> Optional[str]:
        return validate_identifier(v, info.field_name) if v else None

    @field_validator("assessment_timestamp")
    @classmethod
    def check_ts(cls, v: Optional[str], info) -> Optional[str]:
        return validate_iso_timestamp(v, info.field_name) if v else None


class EvidenceValidationRequest(BaseModel):
    """
    Request payload to validate a batch of evidence records deterministically.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_items: List[EvidenceRecord] = Field(description="Evidence items to validate.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    assessment_timestamp: Optional[str] = Field(default=None, description="Fixed assessment timestamp.")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Freshness threshold.")
    verify_source_existence: bool = Field(default=False, description="Whether to verify source record existence in upstream subsystem.")

    @field_validator("tenant_id", "workspace_id")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("evidence_items")
    @classmethod
    def check_items_not_empty(cls, v: List[EvidenceRecord]) -> List[EvidenceRecord]:
        if not v:
            raise ValueError("evidence_items cannot be empty.")
        return v


class EvidenceValidationBatchResponse(BaseModel):
    """
    Validation response for a batch of evidence records.
    """
    model_config = ConfigDict(extra="forbid")

    validations: List[EvidenceValidationResult] = Field(description="Itemized validation results.")
    valid_count: int = Field(ge=0, description="Count of valid items.")
    invalid_count: int = Field(ge=0, description="Count of invalid items.")
    stale_count: int = Field(ge=0, description="Count of stale items.")
    conflicting_count: int = Field(ge=0, description="Count of conflicting items.")
    rejections: List[EvidenceRejection] = Field(default_factory=list, description="Rejections recorded.")
    conflicts: List[EvidenceConflict] = Field(default_factory=list, description="Conflicts recorded.")
    evaluated_at: str = Field(description="Evaluation timestamp.")
    fingerprint: str = Field(description="Deterministic validation fingerprint.")


class ExplanationResult(BaseModel):
    """
    Complete structured explanation result for an analytical conclusion or decision recommendation.
    Contains recommendation/conclusion, lineage graph, validation results, contributions,
    trade-offs, rejections, gaps, limitations, and deterministic fingerprint.
    """
    model_config = ConfigDict(extra="forbid")

    explanation_id: str = Field(description="Unique explanation identifier.")
    target_type: EvidenceSourceType = Field(description="Target analytical subsystem.")
    target_id: str = Field(description="Target record identifier.")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope.")
    fingerprint: str = Field(description="Deterministic SHA-256 canonical explanation fingerprint.")
    assessment_timestamp: str = Field(description="Fixed ISO 8601 evaluation timestamp.")
    algorithm_version: str = Field(default=ALGORITHM_VERSION, description="Explainability algorithm version.")
    contract_version: str = Field(default=CONTRACT_VERSION, description="Explainability contract version.")
    summary: str = Field(description="Concise human-readable explanation summary.")
    recommendation_or_conclusion: Dict[str, Any] = Field(default_factory=dict, description="Preserved target recommendation or analytical conclusion.")
    lineage_graph: Optional[EvidenceLineageGraph] = Field(default=None, description="Deterministic evidence lineage graph.")
    explanation_graph: Optional[ExplanationGraph] = Field(default=None, description="Connected explanation graph.")
    supporting_evidence: List[EvidenceRecord] = Field(default_factory=list, description="Valid evidence directly supporting conclusion.")
    excluded_evidence: List[EvidenceRecord] = Field(default_factory=list, description="Excluded or rejected evidence.")
    validations: List[EvidenceValidationResult] = Field(default_factory=list, description="Validation outcomes for evidence items.")
    contributions: List[EvidenceContribution] = Field(default_factory=list, description="Criterion-level evidence contributions.")
    rejections: List[EvidenceRejection] = Field(default_factory=list, description="Excluded evidence rejections.")
    conflicts: List[EvidenceConflict] = Field(default_factory=list, description="Identified evidence conflicts.")
    gaps: List[EvidenceGap] = Field(default_factory=list, description="Identified evidence gaps.")
    limitations: List[ExplanationLimitation] = Field(default_factory=list, description="Explicit analytical limitations and assumptions.")
    is_partial: bool = Field(default=False, description="True if evidence was insufficient for complete explanation.")
    mandatory_notice: str = Field(
        default=MANDATORY_EXPLAINABILITY_NOTICE,
        description="Non-negotiable architectural boundary notice."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic and traversal metadata.")


class EvidenceAuditRecord(BaseModel):
    """
    Immutable append-only audit record for evidence explanation and validation operations.
    """
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(description="Unique audit identifier.")
    explanation_id: str = Field(description="Associated explanation identifier.")
    event_type: str = Field(default="EXPLANATION_GENERATED", description="Audit event category.")
    actor_id: str = Field(description="Caller identity.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    timestamp: str = Field(description="ISO 8601 audit timestamp.")
    fingerprint: str = Field(description="Input SHA-256 fingerprint.")
    checksum: str = Field(description="Cryptographic checksum of audit payload.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Audit event details.")


class ExplanationSummary(BaseModel):
    """
    Summary representation of an explanation for paginated list endpoints.
    """
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    target_type: EvidenceSourceType
    target_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    fingerprint: str
    assessment_timestamp: str
    is_partial: bool
    supporting_evidence_count: int
    excluded_evidence_count: int
    summary: str


class ExplanationListResponse(BaseModel):
    """Paginated list response of explanation summaries."""
    model_config = ConfigDict(extra="ignore")

    items: List[ExplanationSummary]
    total_count: int


class ExplanationLineageResponse(BaseModel):
    """Lineage graph response for a specific explanation."""
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    lineage_graph: EvidenceLineageGraph


class ExplanationEvidenceResponse(BaseModel):
    """Evidence items and validations for a specific explanation."""
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    supporting_evidence: List[EvidenceRecord]
    excluded_evidence: List[EvidenceRecord]
    validations: List[EvidenceValidationResult]


class ExplanationAuditResponse(BaseModel):
    """Audit ledger history for a specific explanation."""
    model_config = ConfigDict(extra="ignore")

    explanation_id: str
    audit_records: List[EvidenceAuditRecord]


# =============================================================================
# 5. DETERMINISTIC CANONICAL FINGERPRINTING
# =============================================================================

def compute_explanation_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    target_type: Union[EvidenceSourceType, str],
    target_id: str,
    assessment_timestamp: str,
    algorithm_version: str,
    contract_version: str,
    supporting_evidence_ids: List[str],
    excluded_evidence_ids: List[str],
    rejection_reasons: List[str],
    gaps: List[str],
    limitations: List[str],
    recommendation_summary: str = "",
) -> str:
    """
    Computes a canonical, deterministic SHA-256 fingerprint over all material explanation inputs.

    Properties:
    1. Independent of memory addresses, random IDs, and dictionary insertion order.
    2. Sorts all lists deterministically before hashing.
    3. Normalizes timestamps to UTC ISO 8601 strings.
    4. Changing any material source record, timestamp, limitation, or version alters the hash.
    """
    target_type_str = target_type.value if isinstance(target_type, EvidenceSourceType) else str(target_type)

    canonical_dict = {
        "algorithm_version": algorithm_version.strip(),
        "assessment_timestamp": assessment_timestamp.strip(),
        "contract_version": contract_version.strip(),
        "excluded_evidence_ids": sorted(list(excluded_evidence_ids)),
        "gaps": sorted(list(gaps)),
        "limitations": sorted(list(limitations)),
        "plant_id": plant_id.strip() if plant_id else None,
        "recommendation_summary": recommendation_summary.strip(),
        "rejection_reasons": sorted(list(rejection_reasons)),
        "supporting_evidence_ids": sorted(list(supporting_evidence_ids)),
        "target_id": target_id.strip(),
        "target_type": target_type_str,
        "tenant_id": tenant_id.strip(),
        "workspace_id": workspace_id.strip(),
    }

    serialized = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_evidence_record_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    source_type: Union[EvidenceSourceType, str],
    source_record_id: str,
    provenance: Union[EvidenceProvenance, str],
    observed_at: Optional[str],
    payload: Dict[str, Any],
) -> str:
    """Computes a deterministic SHA-256 fingerprint for an individual evidence record."""
    source_type_str = source_type.value if isinstance(source_type, EvidenceSourceType) else str(source_type)
    provenance_str = provenance.value if isinstance(provenance, EvidenceProvenance) else str(provenance)

    canonical_dict = {
        "observed_at": observed_at.strip() if observed_at else None,
        "payload": payload,
        "plant_id": plant_id.strip() if plant_id else None,
        "provenance": provenance_str,
        "source_record_id": source_record_id.strip(),
        "source_type": source_type_str,
        "tenant_id": tenant_id.strip(),
        "workspace_id": workspace_id.strip(),
    }

    serialized = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
