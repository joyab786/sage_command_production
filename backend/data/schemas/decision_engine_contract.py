# backend/data/schemas/decision_engine_contract.py
"""
SageCommand V3 — Decision Engine Foundation Contracts (Prompt 30)

ANALYTICAL DECISION SUPPORT ONLY.
Defines typed, validated contracts for the Decision Engine lifecycle:
DecisionProblem, DecisionRequest, DecisionOption, DecisionCriterion,
DecisionConstraint, DecisionPolicy, DecisionEvidenceReference,
DecisionAlternative, DecisionEvaluation, DecisionRecommendation,
DecisionOutcome, DecisionLimitation, DecisionUncertainty,
DecisionFingerprint, and DecisionAuditRecord.

Cardinal Invariant:
The Decision Engine layer produces governed ANALYTICAL RECOMMENDATIONS.
It is NOT an operational execution system.
It NEVER executes physical commands, writes to PLCs/controllers,
dispatches work orders, issues purchase orders, mutates inventories,
or bypasses independently enforced authorization and execution boundaries.

Invariant:
DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED
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

MANDATORY_EXECUTION_NOTICE = "DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED"

FORBIDDEN_ACTUATION_KEYWORDS = {
    "PLC_COMMAND",
    "ACTUATOR_COMMAND",
    "EXECUTE_WORK_ORDER",
    "PURCHASE_ORDER",
    "CUSTOMER_MESSAGE",
    "PHYSICAL_COMMAND",
    "WORK_ORDER",
    "DISPATCH_TECHNICIAN",
    "MUTATE_INVENTORY",
    "EXECUTE_TRANSACTION",
    "WRITE_PLC",
    "DIRECT_ACTUATION",
    "TRIGGER_ACTION",
    "EXECUTE_ACTION",
}


# =============================================================================
# 1. ENUMS
# =============================================================================

class DecisionScope(str, Enum):
    """Scope of decision problem."""
    ENTITY = "ENTITY"
    LINE = "LINE"
    PLANT = "PLANT"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    ENTERPRISE = "ENTERPRISE"
    MULTI_PLANT = "MULTI_PLANT"


class DecisionType(str, Enum):
    """
    Controlled, extensible set of analytical decision categories.
    These are analytical decision categories, not executable command types.
    """
    RESOURCE_ALLOCATION = "RESOURCE_ALLOCATION"
    DEMAND_FULFILLMENT = "DEMAND_FULFILLMENT"
    SUPPLIER_SELECTION = "SUPPLIER_SELECTION"
    MAINTENANCE_PRIORITIZATION = "MAINTENANCE_PRIORITIZATION"
    SLA_RISK_MITIGATION = "SLA_RISK_MITIGATION"
    FINANCIAL_TRADEOFF = "FINANCIAL_TRADEOFF"
    SUSTAINABILITY_TRADEOFF = "SUSTAINABILITY_TRADEOFF"
    PRODUCTION_PLANNING = "PRODUCTION_PLANNING"
    INCIDENT_RESPONSE = "INCIDENT_RESPONSE"
    CROSS_DOMAIN_PLANNING = "CROSS_DOMAIN_PLANNING"


class DecisionOutcomeStatus(str, Enum):
    """Outcome and recommendation status for a decision evaluation."""
    RECOMMENDED = "RECOMMENDED"
    CONDITIONALLY_RECOMMENDED = "CONDITIONALLY_RECOMMENDED"
    NO_FEASIBLE_OPTION = "NO_FEASIBLE_OPTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    EVALUATION_FAILED = "EVALUATION_FAILED"


class CriterionDirection(str, Enum):
    """Direction for objective optimization/scoring."""
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"


class CriterionType(str, Enum):
    """Analytical categories of decision criteria."""
    COST = "COST"
    RISK = "RISK"
    TIME = "TIME"
    QUALITY = "QUALITY"
    SUSTAINABILITY = "SUSTAINABILITY"
    THROUGHPUT = "THROUGHPUT"
    RELIABILITY = "RELIABILITY"
    ENERGY = "ENERGY"
    COMPLIANCE = "COMPLIANCE"


class ConstraintType(str, Enum):
    """Analytical categories of decision constraints."""
    CAPACITY = "CAPACITY"
    DEMAND = "DEMAND"
    BUDGET = "BUDGET"
    SAFETY = "SAFETY"
    REGULATORY = "REGULATORY"
    TIME = "TIME"
    EMISSIONS = "EMISSIONS"
    ENERGY = "ENERGY"
    SUPPLIER = "SUPPLIER"
    POLICY = "POLICY"


class ConstraintOperator(str, Enum):
    """Supported constraint comparison operators."""
    LTE = "<="
    GTE = ">="
    EQ = "=="
    LT = "<"
    GT = ">"
    IN = "IN"


class HardOrSoft(str, Enum):
    """Constraint severity."""
    HARD = "HARD"
    SOFT = "SOFT"


class PolicyComplianceStatus(str, Enum):
    """Evaluation status against server-governed policy."""
    COMPLIANT = "COMPLIANT"
    VIOLATED = "VIOLATED"
    EXEMPTED = "EXEMPTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConfidenceLevel(str, Enum):
    """Confidence categorization."""
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"
    UNKNOWN = "UNKNOWN"


class EvidenceProvenanceType(str, Enum):
    """Provenance classification for evidence consumed."""
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    FORECAST = "FORECAST"
    SIMULATED = "SIMULATED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class ComparisonMethod(str, Enum):
    """Comparison semantics between candidate options."""
    WEIGHTED_SCORING = "WEIGHTED_SCORING"
    LEXICOGRAPHIC = "LEXICOGRAPHIC"
    DOMINANCE = "DOMINANCE"


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
    """Validate ISO 8601 timestamp string."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty ISO 8601 string.")
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Force timezone awareness for deterministic comparisons
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception as e:
        raise ValueError(f"Field '{field_name}' must be a valid ISO 8601 timestamp: {e}")


# =============================================================================
# 3. CORE DECISION CONTRACT MODELS
# =============================================================================

class DecisionOption(BaseModel):
    """
    A candidate course of action or abstract planning alternative.
    Represents an analytical option; must not directly invoke operational commands.
    """
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(description="Unique identifier for the candidate option.")
    name: str = Field(description="Human-readable name of the option.")
    description: str = Field(default="", description="Detailed description of the option.")
    category: str = Field(default="GENERAL", description="Domain category of the option.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Analytical parameters for this option.")
    expected_outcomes: Dict[str, Any] = Field(default_factory=dict, description="Projected outcome values for evaluation.")
    tags: List[str] = Field(default_factory=list, description="Categorical or filtering tags.")

    @field_validator("option_id", "name")
    @classmethod
    def check_id_and_name(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("parameters")
    @classmethod
    def check_parameters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        for key, val in v.items():
            if any(forbidden in key.upper() for forbidden in FORBIDDEN_ACTUATION_KEYWORDS):
                raise ValueError(f"Option parameter '{key}' contains forbidden actuation keyword.")
            if isinstance(val, str) and any(forbidden in val.upper() for forbidden in FORBIDDEN_ACTUATION_KEYWORDS):
                raise ValueError(f"Option parameter value for '{key}' contains forbidden actuation keyword.")
        return v


class DecisionCriterion(BaseModel):
    """
    An explicit objective or criterion against which candidate options are scored.
    """
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(description="Unique identifier for the criterion.")
    name: str = Field(description="Human-readable name.")
    criterion_type: CriterionType = Field(description="Criterion analytical category.")
    direction: CriterionDirection = Field(default=CriterionDirection.MINIMIZE, description="MINIMIZE or MAXIMIZE.")
    weight: float = Field(default=1.0, description="Criterion importance weight.")
    unit: Optional[str] = Field(default=None, description="Physical or financial unit of measure.")
    min_acceptable: Optional[float] = Field(default=None, description="Lower acceptable bound.")
    max_acceptable: Optional[float] = Field(default=None, description="Upper acceptable bound.")
    target_value: Optional[float] = Field(default=None, description="Ideal target value if specified.")
    normalization: Optional[str] = Field(default="MIN_MAX", description="Normalization method: MIN_MAX, Z_SCORE, DIRECT.")
    priority_order: int = Field(default=0, ge=0, description="Lexicographic priority order (0 = primary).")

    @field_validator("criterion_id", "name")
    @classmethod
    def check_id_and_name(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("weight", mode="before")
    @classmethod
    def check_weight(cls, v: Any) -> float:
        val = validate_finite_number(v, "weight")
        if val < 0.0:
            raise ValueError("Criterion weight must be non-negative.")
        if val > 100.0:
            raise ValueError("Criterion weight must be <= 100.0.")
        return val

    @field_validator("min_acceptable", "max_acceptable", "target_value")
    @classmethod
    def check_bounds(cls, v: Optional[float], info) -> Optional[float]:
        if v is not None:
            return validate_finite_number(v, info.field_name)
        return None


class CriterionEvaluation(BaseModel):
    """Evaluation result of a single criterion for a candidate option."""
    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(description="Associated criterion ID.")
    option_id: str = Field(description="Associated option ID.")
    raw_value: float = Field(description="Raw metric value observed/projected.")
    normalized_score: float = Field(description="Normalized score between 0.0 and 1.0 (1.0 = best).")
    weighted_score: float = Field(description="Score multiplied by normalized weight.")
    direction: CriterionDirection = Field(description="Direction evaluated.")
    unit: Optional[str] = Field(default=None, description="Unit evaluated.")
    notes: Optional[str] = Field(default=None, description="Evaluation commentary.")

    @field_validator("raw_value", "normalized_score", "weighted_score")
    @classmethod
    def check_scores(cls, v: float, info) -> float:
        return validate_finite_number(v, info.field_name)


class DecisionConstraint(BaseModel):
    """
    Mandatory hard constraint or trade-off soft preference.
    """
    model_config = ConfigDict(extra="forbid")

    constraint_id: str = Field(description="Unique constraint identifier.")
    name: str = Field(description="Human-readable constraint name.")
    constraint_type: ConstraintType = Field(description="Domain category.")
    operator: ConstraintOperator = Field(description="Comparison operator (<=, >=, ==, <, >, IN).")
    threshold_value: Union[float, str, List[Union[float, str]]] = Field(description="Threshold value.")
    hard_or_soft: HardOrSoft = Field(default=HardOrSoft.HARD, description="HARD (mandatory) or SOFT (preference).")
    unit: Optional[str] = Field(default=None, description="Measurement unit.")
    target_field: str = Field(description="Target field in option parameters or expected_outcomes.")
    description: Optional[str] = Field(default=None, description="Constraint explanation.")

    @field_validator("constraint_id", "name", "target_field")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("threshold_value")
    @classmethod
    def check_threshold(cls, v: Any) -> Any:
        if isinstance(v, (int, float)):
            return validate_finite_number(v, "threshold_value")
        if isinstance(v, str):
            return validate_identifier(v, "threshold_value")
        if isinstance(v, list):
            if not v:
                raise ValueError("List threshold cannot be empty.")
            return v
        raise ValueError(f"Unsupported threshold type: {type(v).__name__}")


class ConstraintEvaluationResult(BaseModel):
    """Evaluation result of a single constraint against an option."""
    model_config = ConfigDict(extra="forbid")

    constraint_id: str = Field(description="Constraint identifier.")
    option_id: str = Field(description="Option identifier.")
    hard_or_soft: HardOrSoft = Field(description="HARD or SOFT.")
    satisfied: bool = Field(description="Whether the constraint is met.")
    observed_value: Any = Field(description="Actual observed or projected value.")
    threshold_value: Any = Field(description="Evaluated threshold.")
    margin: Optional[float] = Field(default=None, description="Distance from threshold (>= 0 means satisfied).")
    explanation: str = Field(description="Human-readable explanation of satisfaction/violation.")


class DecisionPolicy(BaseModel):
    """
    Server-controlled governance policy rule. Caller cannot weaken or bypass this.
    """
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(description="Canonical policy identifier.")
    name: str = Field(description="Policy name.")
    version: str = Field(default="1.0", description="Policy version string.")
    description: str = Field(default="", description="Governance description.")
    required_permission: Optional[str] = Field(default=None, description="Required caller permission.")
    rules: Dict[str, Any] = Field(default_factory=dict, description="Structured policy rules.")
    is_active: bool = Field(default=True, description="Whether policy is active.")

    @field_validator("policy_id", "name", "version")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class DecisionPolicyEvaluation(BaseModel):
    """Evaluation result of a trusted policy against a candidate option."""
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(description="Policy identifier.")
    policy_version: str = Field(description="Policy version evaluated.")
    option_id: str = Field(description="Option identifier.")
    status: PolicyComplianceStatus = Field(description="COMPLIANT, VIOLATED, EXEMPTED, NOT_APPLICABLE.")
    reason: str = Field(description="Detailed reason for compliance or violation.")
    evaluated_at: str = Field(description="ISO 8601 timestamp of policy evaluation.")


class DecisionEvidenceReference(BaseModel):
    """
    Reference to governed evidence from upstream analytical subsystems (Prompts 10–29).
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Deterministic evidence identifier.")
    source_subsystem: str = Field(description="Upstream system: OPTIMIZATION, SIMULATION, FORECAST, etc.")
    source_record_id: str = Field(description="Upstream record primary key.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope if applicable.")
    timestamp: str = Field(description="ISO 8601 observation/assessment timestamp.")
    horizon: str = Field(default="SHORT_TERM", description="Applicable time horizon.")
    provenance: EvidenceProvenanceType = Field(default=EvidenceProvenanceType.OBSERVED, description="Provenance type.")
    quality_score: float = Field(default=1.0, description="Data quality score.")
    freshness_seconds: Optional[float] = Field(default=None, ge=0.0, description="Age of evidence in seconds.")
    confidence: float = Field(default=1.0, description="Confidence in this evidence item.")
    is_valid: bool = Field(default=True, description="Whether evidence is valid and not expired/stale.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Extracted payload context.")

    @field_validator("evidence_id", "source_subsystem", "source_record_id", "tenant_id", "workspace_id")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("quality_score", "confidence", mode="before")
    @classmethod
    def check_proportions(cls, v: Any, info) -> float:
        val = validate_finite_number(v, info.field_name)
        if not (0.0 <= val <= 1.0):
            raise ValueError(f"Field '{info.field_name}' must be between 0.0 and 1.0.")
        return val


class DecisionUncertainty(BaseModel):
    """Uncertainty quantification for an analytical metric or evaluation."""
    model_config = ConfigDict(extra="forbid")

    metric_name: str = Field(description="Metric name.")
    lower_bound: float = Field(description="Lower estimated bound.")
    upper_bound: float = Field(description="Upper estimated bound.")
    variance: Optional[float] = Field(default=None, ge=0.0, description="Estimated variance.")
    confidence_level: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM, description="Confidence level.")
    notes: Optional[str] = Field(default=None, description="Uncertainty explanation.")

    @field_validator("lower_bound", "upper_bound")
    @classmethod
    def check_bounds(cls, v: float, info) -> float:
        return validate_finite_number(v, info.field_name)

    @field_validator("variance")
    @classmethod
    def check_variance(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            return validate_finite_number(v, "variance")
        return None


class DecisionLimitation(BaseModel):
    """Explicit limitation, assumption, or unresolved risk."""
    model_config = ConfigDict(extra="forbid")

    limitation_id: str = Field(description="Unique limitation identifier.")
    code: str = Field(description="Structured limitation code.")
    description: str = Field(description="Explanation of limitation.")
    severity: str = Field(default="MEDIUM", description="LOW, MEDIUM, HIGH, BLOCKING.")
    affected_option_ids: List[str] = Field(default_factory=list, description="Affected option identifiers.")
    mitigation: Optional[str] = Field(default=None, description="Recommended mitigation or human action.")

    @field_validator("limitation_id", "code", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class DecisionTradeoff(BaseModel):
    """Explicit trade-off assessment between criteria or alternatives."""
    model_config = ConfigDict(extra="forbid")

    criterion_a: str = Field(description="First criterion ID.")
    criterion_b: str = Field(description="Second criterion ID.")
    description: str = Field(description="Description of trade-off.")
    impact_delta: float = Field(description="Magnitude of trade-off difference.")
    sensitivity_ratio: Optional[float] = Field(default=None, description="Relative sensitivity ratio.")

    @field_validator("impact_delta")
    @classmethod
    def check_delta(cls, v: float) -> float:
        return validate_finite_number(v, "impact_delta")


class DecisionAlternative(BaseModel):
    """
    Ranked candidate alternative with complete scoring and constraint compliance.
    """
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(description="Option identifier.")
    option_name: str = Field(description="Option human-readable name.")
    rank: int = Field(ge=1, description="Deterministic rank (1 = top option).")
    composite_score: float = Field(description="Deterministic composite score (0.0 to 1.0).")
    is_feasible: bool = Field(description="True if all hard constraints are satisfied.")
    is_policy_compliant: bool = Field(description="True if all applicable policies are satisfied.")
    is_recommended: bool = Field(default=False, description="Whether this alternative is the primary recommendation.")
    criteria_scores: Dict[str, float] = Field(default_factory=dict, description="Criterion ID to normalized score map.")
    criteria_raw_values: Dict[str, float] = Field(default_factory=dict, description="Criterion ID to raw value map.")
    binding_constraints: List[str] = Field(default_factory=list, description="IDs of hard constraints that are active/violated.")
    violations: List[str] = Field(default_factory=list, description="Constraint or policy violation descriptions.")
    unresolved_limitations: List[str] = Field(default_factory=list, description="Limitation IDs relevant to this alternative.")

    @field_validator("composite_score")
    @classmethod
    def check_score(cls, v: float) -> float:
        return validate_finite_number(v, "composite_score")


class DecisionOutcome(BaseModel):
    """Summary of final decision evaluation outcome."""
    model_config = ConfigDict(extra="forbid")

    option_id: Optional[str] = Field(default=None, description="Recommended option ID if any.")
    outcome_status: DecisionOutcomeStatus = Field(description="Structured outcome status.")
    summary: str = Field(description="Concise outcome summary.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured outcome details.")


class DecisionRecommendation(BaseModel):
    """
    Governed decision recommendation payload.
    Mandatory notice: "DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED".
    """
    model_config = ConfigDict(extra="forbid")

    recommended_option_id: Optional[str] = Field(default=None, description="Top-ranked feasible and policy-compliant option.")
    recommendation_status: DecisionOutcomeStatus = Field(description="Status of recommendation.")
    primary_rationale: str = Field(description="Clear deterministic explanation for recommendation.")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Overall recommendation confidence.")
    uncertainty_summary: str = Field(default="Deterministic evaluation", description="Uncertainty summary.")
    alternatives: List[DecisionAlternative] = Field(default_factory=list, description="Ranked list of all evaluated alternatives.")
    limitations: List[DecisionLimitation] = Field(default_factory=list, description="Unresolved limitations and risks.")
    tradeoffs: List[DecisionTradeoff] = Field(default_factory=list, description="Material trade-offs evaluated.")
    mandatory_notice: str = Field(
        default=MANDATORY_EXECUTION_NOTICE,
        description="Non-negotiable architectural execution boundary notice."
    )

    @field_validator("confidence")
    @classmethod
    def check_conf(cls, v: float) -> float:
        val = validate_finite_number(v, "confidence")
        if not (0.0 <= val <= 1.0):
            raise ValueError("Confidence must be between 0.0 and 1.0.")
        return val


class DecisionContext(BaseModel):
    """
    Governed analytical context connecting to upstream intelligence models.
    """
    model_config = ConfigDict(extra="forbid")

    simulation_id: Optional[str] = Field(default=None, description="What-If Simulation ID reference.")
    optimization_id: Optional[str] = Field(default=None, description="Optimization Result ID reference.")
    forecast_id: Optional[str] = Field(default=None, description="Demand Forecast reference.")
    incident_id: Optional[str] = Field(default=None, description="Active Incident reference.")
    digital_twin_snapshot_id: Optional[str] = Field(default=None, description="Digital Twin snapshot ID.")
    assumptions: Dict[str, Any] = Field(default_factory=dict, description="Explicit modeling assumptions.")
    environmental_factors: Dict[str, Any] = Field(default_factory=dict, description="Ambient or environmental factors.")
    baseline_metrics: Dict[str, float] = Field(default_factory=dict, description="Current baseline operational metrics.")

    @field_validator("baseline_metrics")
    @classmethod
    def check_baseline(cls, v: Dict[str, float]) -> Dict[str, float]:
        for k, val in v.items():
            validate_finite_number(val, f"baseline_metrics[{k}]")
        return v


class DecisionProblem(BaseModel):
    """
    Canonical formulation of a decision problem.
    """
    model_config = ConfigDict(extra="forbid")

    problem_id: str = Field(description="Unique decision problem identifier.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope if applicable.")
    decision_type: DecisionType = Field(description="Analytical decision category.")
    title: str = Field(description="Decision title.")
    description: str = Field(default="", description="Detailed problem statement.")
    scope: DecisionScope = Field(default=DecisionScope.PLANT, description="Decision scope.")
    horizon: str = Field(default="SHORT_TERM", description="Planning horizon.")
    options: List[DecisionOption] = Field(description="Candidate courses of action.")
    criteria: List[DecisionCriterion] = Field(description="Objectives and scoring criteria.")
    constraints: List[DecisionConstraint] = Field(default_factory=list, description="Hard and soft constraints.")
    policies: List[DecisionPolicy] = Field(default_factory=list, description="Applicable governance policies.")
    context: Optional[DecisionContext] = Field(default=None, description="Analytical context snapshot.")
    evidence_references: List[DecisionEvidenceReference] = Field(default_factory=list, description="Evidence items.")
    comparison_method: ComparisonMethod = Field(default=ComparisonMethod.WEIGHTED_SCORING, description="Scoring method.")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Creation timestamp.")

    @field_validator("problem_id", "tenant_id", "workspace_id", "title")
    @classmethod
    def check_required_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("options")
    @classmethod
    def check_options_not_empty(cls, v: List[DecisionOption]) -> List[DecisionOption]:
        if not v:
            raise ValueError("Decision problem must have at least one candidate option.")
        ids = [opt.option_id for opt in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Candidate options must have unique option_ids.")
        return v

    @field_validator("criteria")
    @classmethod
    def check_criteria_not_empty(cls, v: List[DecisionCriterion]) -> List[DecisionCriterion]:
        if not v:
            raise ValueError("Decision problem must have at least one criterion.")
        ids = [c.criterion_id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Criteria must have unique criterion_ids.")
        return v


class DecisionRequest(BaseModel):
    """
    Request payload to evaluate a decision problem.
    """
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope if applicable.")
    decision_type: DecisionType = Field(description="Analytical decision category.")
    title: str = Field(description="Decision title.")
    description: str = Field(default="", description="Detailed problem statement.")
    scope: DecisionScope = Field(default=DecisionScope.PLANT, description="Decision scope.")
    horizon: str = Field(default="SHORT_TERM", description="Planning horizon.")
    options: List[DecisionOption] = Field(description="Candidate options to evaluate.")
    criteria: List[DecisionCriterion] = Field(description="Criteria for scoring.")
    constraints: List[DecisionConstraint] = Field(default_factory=list, description="Constraints.")
    policies: List[DecisionPolicy] = Field(default_factory=list, description="Governance policies.")
    context: Optional[DecisionContext] = Field(default=None, description="Analytical context snapshot.")
    evidence_references: List[DecisionEvidenceReference] = Field(default_factory=list, description="Evidence references.")
    comparison_method: ComparisonMethod = Field(default=ComparisonMethod.WEIGHTED_SCORING, description="Scoring method.")
    assessment_timestamp: Optional[str] = Field(default=None, description="Fixed evaluation timestamp.")

    @field_validator("tenant_id", "workspace_id", "title")
    @classmethod
    def check_required_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("options")
    @classmethod
    def check_options(cls, v: List[DecisionOption]) -> List[DecisionOption]:
        if not v:
            raise ValueError("Decision request must have at least one candidate option.")
        ids = [opt.option_id for opt in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Candidate options must have unique option_ids.")
        return v

    @field_validator("criteria")
    @classmethod
    def check_criteria(cls, v: List[DecisionCriterion]) -> List[DecisionCriterion]:
        if not v:
            raise ValueError("Decision request must have at least one criterion.")
        ids = [c.criterion_id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Criteria must have unique criterion_ids.")
        return v


class DecisionEvaluation(BaseModel):
    """
    Complete structured decision evaluation output.
    Contains recommendation, policy checks, constraint evaluations,
    criterion evaluations, limitations, evidence snapshot, and deterministic fingerprint.
    """
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(description="Unique decision evaluation identifier.")
    problem_id: str = Field(description="Associated problem identifier.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    decision_type: DecisionType = Field(description="Analytical decision category.")
    fingerprint: str = Field(description="Deterministic canonical SHA-256 fingerprint.")
    assessment_timestamp: str = Field(description="Fixed ISO 8601 evaluation timestamp.")
    status: DecisionOutcomeStatus = Field(description="Overall evaluation status.")
    recommendation: DecisionRecommendation = Field(description="Governed recommendation.")
    policy_evaluations: List[DecisionPolicyEvaluation] = Field(default_factory=list, description="Policy check results.")
    constraint_evaluations: List[ConstraintEvaluationResult] = Field(default_factory=list, description="Constraint check results.")
    criterion_evaluations: List[CriterionEvaluation] = Field(default_factory=list, description="Criterion score breakdown.")
    limitations: List[DecisionLimitation] = Field(default_factory=list, description="Identified limitations.")
    evidence_snapshot: List[DecisionEvidenceReference] = Field(default_factory=list, description="Evidence items utilized.")
    uncertainties: List[DecisionUncertainty] = Field(default_factory=list, description="Quantified uncertainties.")
    mandatory_notice: str = Field(
        default=MANDATORY_EXECUTION_NOTICE,
        description="Non-negotiable architectural execution boundary notice."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Evaluation metadata.")


class DecisionAuditRecord(BaseModel):
    """
    Append-only audit record for decision evaluations.
    """
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(description="Unique audit event ID.")
    decision_id: str = Field(description="Evaluated decision ID.")
    tenant_id: str = Field(description="Tenant scope.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    event_type: str = Field(default="DECISION_EVALUATED", description="Audit event type.")
    actor_id: str = Field(description="Authenticated user or agent ID.")
    timestamp: str = Field(description="ISO 8601 event timestamp.")
    fingerprint: str = Field(description="Decision input SHA-256 fingerprint.")
    checksum: str = Field(description="Cryptographic checksum of audit payload.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Audit event details.")


class DecisionEvaluationSummary(BaseModel):
    """Summary representation of a decision evaluation for list endpoints."""
    model_config = ConfigDict(extra="ignore")

    decision_id: str
    problem_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    decision_type: DecisionType
    status: DecisionOutcomeStatus
    recommended_option_id: Optional[str] = None
    composite_confidence: float
    fingerprint: str
    assessment_timestamp: str


class DecisionListResponse(BaseModel):
    """Paginated list response of decision evaluations."""
    model_config = ConfigDict(extra="ignore")

    items: List[DecisionEvaluation]
    total_count: int


class DecisionAlternativesResponse(BaseModel):
    """Alternatives evaluated for a decision run."""
    model_config = ConfigDict(extra="ignore")

    decision_id: str
    alternatives: List[DecisionAlternative]


class DecisionEvidenceResponse(BaseModel):
    """Evidence references associated with a decision evaluation."""
    model_config = ConfigDict(extra="ignore")

    decision_id: str
    evidence: List[DecisionEvidenceReference]


class DecisionAuditResponse(BaseModel):
    """Audit ledger records for a decision evaluation."""
    model_config = ConfigDict(extra="ignore")

    decision_id: str
    audit_records: List[DecisionAuditRecord]


# =============================================================================
# 4. DETERMINISTIC FINGERPRINTING
# =============================================================================

def compute_decision_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    decision_type: Union[DecisionType, str],
    assessment_timestamp: str,
    horizon: str,
    options: List[DecisionOption],
    criteria: List[DecisionCriterion],
    constraints: List[DecisionConstraint],
    policies: List[DecisionPolicy],
    evidence_references: List[DecisionEvidenceReference],
    comparison_method: Union[ComparisonMethod, str],
    context: Optional[DecisionContext] = None,
) -> str:
    """
    Computes a canonical, deterministic SHA-256 fingerprint over all material decision inputs.

    Properties:
    - Sorted by canonical identifiers to ensure order invariance.
    - Floating point values are rounded to 6 decimal places.
    - Excludes non-material identifiers, random UUIDs, or volatile timestamps.
    """
    decision_type_str = decision_type.value if isinstance(decision_type, DecisionType) else str(decision_type)
    comparison_method_str = comparison_method.value if isinstance(comparison_method, ComparisonMethod) else str(comparison_method)

    canonical_options = sorted(
        [
            {
                "opt_id": opt.option_id.strip(),
                "name": opt.name.strip(),
                "cat": opt.category.strip(),
                "params": {
                    k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
                    for k, v in sorted(opt.parameters.items())
                },
                "outcomes": {
                    k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
                    for k, v in sorted(opt.expected_outcomes.items())
                },
            }
            for opt in options
        ],
        key=lambda x: x["opt_id"]
    )

    canonical_criteria = sorted(
        [
            {
                "crit_id": c.criterion_id.strip(),
                "type": c.criterion_type.value if hasattr(c.criterion_type, "value") else str(c.criterion_type),
                "dir": c.direction.value if hasattr(c.direction, "value") else str(c.direction),
                "weight": round(float(c.weight), 6),
                "unit": (c.unit or "").strip(),
                "order": c.priority_order,
                "norm": (c.normalization or "").strip(),
                "min": round(float(c.min_acceptable), 6) if c.min_acceptable is not None else None,
                "max": round(float(c.max_acceptable), 6) if c.max_acceptable is not None else None,
            }
            for c in criteria
        ],
        key=lambda x: x["crit_id"]
    )

    canonical_constraints = sorted(
        [
            {
                "c_id": c.constraint_id.strip(),
                "type": c.constraint_type.value if hasattr(c.constraint_type, "value") else str(c.constraint_type),
                "op": c.operator.value if hasattr(c.operator, "value") else str(c.operator),
                "threshold": (round(float(c.threshold_value), 6) if isinstance(c.threshold_value, (int, float)) and not isinstance(c.threshold_value, bool) else str(c.threshold_value)),
                "hard_or_soft": c.hard_or_soft.value if hasattr(c.hard_or_soft, "value") else str(c.hard_or_soft),
                "target_field": c.target_field.strip(),
            }
            for c in constraints
        ],
        key=lambda x: x["c_id"]
    )

    canonical_policies = sorted(
        [
            {
                "p_id": p.policy_id.strip(),
                "version": p.version.strip(),
                "rules": {
                    k: str(v) for k, v in sorted(p.rules.items())
                },
            }
            for p in policies
        ],
        key=lambda x: (x["p_id"], x["version"])
    )

    canonical_evidence = sorted(
        [
            {
                "e_id": e.evidence_id.strip(),
                "source": e.source_subsystem.strip(),
                "rec_id": e.source_record_id.strip(),
                "prov": e.provenance.value if hasattr(e.provenance, "value") else str(e.provenance),
                "quality": round(float(e.quality_score), 6),
                "confidence": round(float(e.confidence), 6),
            }
            for e in evidence_references
        ],
        key=lambda x: (x["e_id"], x["source"])
    )

    canonical_context: Dict[str, Any] = {}
    if context:
        canonical_context = {
            "simulation_id": (context.simulation_id or "").strip(),
            "optimization_id": (context.optimization_id or "").strip(),
            "forecast_id": (context.forecast_id or "").strip(),
            "incident_id": (context.incident_id or "").strip(),
            "twin_id": (context.digital_twin_snapshot_id or "").strip(),
            "assumptions": {
                k: str(v) for k, v in sorted(context.assumptions.items())
            },
            "baseline": {
                k: round(float(v), 6) for k, v in sorted(context.baseline_metrics.items())
            },
        }

    fingerprint_payload = {
        "tenant_id": tenant_id.strip(),
        "workspace_id": workspace_id.strip(),
        "plant_id": (plant_id or "").strip(),
        "decision_type": decision_type_str.strip(),
        "assessment_timestamp": assessment_timestamp.strip(),
        "horizon": horizon.strip(),
        "options": canonical_options,
        "criteria": canonical_criteria,
        "constraints": canonical_constraints,
        "policies": canonical_policies,
        "evidence": canonical_evidence,
        "context": canonical_context,
        "comparison_method": comparison_method_str.strip(),
        "contract_version": "3.0",
    }

    serialized = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
