# backend/data/schemas/confidence_uncertainty_contract.py
"""
SageCommand V3 — Confidence and Uncertainty Intelligence Foundation Contracts (Prompt 32)

ANALYTICAL CONFIDENCE & UNCERTAINTY ASSESSMENT ONLY.
Defines typed, validated contracts for evaluating reliability, evidential support,
and decomposed uncertainty across all analytical outputs in SageCommand V3:
ConfidenceAssessment, UncertaintyAssessment, ConfidenceDimension, UncertaintyComponent,
UncertaintyRange, UncertaintyDistributionSummary, UncertaintySensitivity,
ConfidenceUncertaintyResult, ConfidenceUncertaintyRequest, and ConfidenceAuditRecord.

Cardinal Principles:
1. Confidence is a measure of support for a specific analytical claim under a specific context.
   It is NOT the probability that the claim is true unless a validated statistical interpretation
   explicitly justifies that meaning.
2. Uncertainty is information that must be exposed, not hidden behind a single score.
3. The system must not artificially inflate confidence, manufacture precision,
   or treat missing evidence as proof of safety.
4. The Confidence and Uncertainty layer is a READ-ONLY analytical integration layer.
   It NEVER executes actions, triggers PLCs, modifies decisions, or mutates operational records.

Notice:
CONFIDENCE AND UNCERTAINTY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone
import hashlib
import json
import math
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

# Re-use canonical evidence types from Prompt 31
try:
    from data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )


# =============================================================================
# 0. CONSTANTS & MANDATORY NOTICE
# =============================================================================

MANDATORY_CONFIDENCE_NOTICE = "CONFIDENCE AND UNCERTAINTY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED"
ALGORITHM_VERSION = "1.0.0"
CONTRACT_VERSION = "1.0.0"

FORBIDDEN_EXECUTION_KEYWORDS = {
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

class ConfidenceDimensionType(str, Enum):
    """
    Independent dimensions of analytical confidence.
    Distinguishes independent quality indicators rather than collapsing everything into an opaque number.
    """
    EVIDENCE_COMPLETENESS = "EVIDENCE_COMPLETENESS"
    EVIDENCE_QUALITY = "EVIDENCE_QUALITY"
    FRESHNESS = "FRESHNESS"
    TEMPORAL_CONSISTENCY = "TEMPORAL_CONSISTENCY"
    SOURCE_RELIABILITY = "SOURCE_RELIABILITY"
    CROSS_SOURCE_AGREEMENT = "CROSS_SOURCE_AGREEMENT"
    METHOD_VALIDITY = "METHOD_VALIDITY"
    CONTEXT_COVERAGE = "CONTEXT_COVERAGE"
    MODEL_CALIBRATION = "MODEL_CALIBRATION"
    LINEAGE_INTEGRITY = "LINEAGE_INTEGRITY"


class ConfidenceStatus(str, Enum):
    """
    Qualitative confidence tier reflecting supported analytical strength.
    """
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    VERY_LOW_CONFIDENCE = "VERY_LOW_CONFIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_ASSESSABLE = "NOT_ASSESSABLE"


class UncertaintyType(str, Enum):
    """
    Classification of uncertainty source and nature.
    Distinguishes inherent variability from missing knowledge and sensor limitations.
    """
    ALEATORIC = "ALEATORIC"                    # Variability inherent in observations or physical process
    EPISTEMIC = "EPISTEMIC"                    # Uncertainty caused by incomplete knowledge or missing evidence
    MEASUREMENT = "MEASUREMENT"                # Sensor accuracy, precision, resolution, calibration limits
    TEMPORAL = "TEMPORAL"                      # Stale, delayed, misaligned, or sparsely sampled evidence
    MODEL = "MODEL"                            # Limitations in model structure, physics, or algorithmic assumptions
    PARAMETER = "PARAMETER"                    # Uncertain input parameters, coefficients, or conversion factors
    SCENARIO = "SCENARIO"                      # Sensitivity to scenario assumptions or external boundary conditions
    SOURCE_DISAGREEMENT = "SOURCE_DISAGREEMENT" # Conflicting observations or contradictory analytical conclusions
    COVERAGE = "COVERAGE"                      # Missing source systems, missing modalities, or incomplete context
    UNKNOWN = "UNKNOWN"                        # Uncertainty that cannot be classified reliably


class UncertaintySeverity(str, Enum):
    """Severity or impact level of an identified uncertainty component."""
    NEGLIGIBLE = "NEGLIGIBLE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNASSESSED = "UNASSESSED"


class UncertaintyIntervalType(str, Enum):
    """Statistical or empirical nature of a quantified uncertainty range."""
    OBSERVED_RANGE = "OBSERVED_RANGE"
    PREDICTION_INTERVAL = "PREDICTION_INTERVAL"
    SCENARIO_BOUNDS = "SCENARIO_BOUNDS"
    HEURISTIC_BAND = "HEURISTIC_BAND"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AggregationMethod(str, Enum):
    """Deterministic formula used to aggregate dimension scores."""
    WEIGHTED_DEFICIENCY_CAPPED = "WEIGHTED_DEFICIENCY_CAPPED"
    MIN_DIMENSION_BOUND = "MIN_DIMENSION_BOUND"
    GEOMETRIC_MEAN = "GEOMETRIC_MEAN"


class CalibrationStatus(str, Enum):
    """Empirical calibration status of the evaluating model or method."""
    CALIBRATED = "CALIBRATED"
    UNASSESSED = "UNASSESSED"
    HEURISTIC_UNAVAILABLE = "HEURISTIC_UNAVAILABLE"


# =============================================================================
# 2. VALIDATION HELPERS
# =============================================================================

def validate_finite_number(v: Any, field_name: str) -> float:
    """Validate that numeric inputs are finite (rejecting NaN, +inf, -inf)."""
    if v is None:
        raise ValueError(f"Field '{field_name}' cannot be None.")
    try:
        val = float(v)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Field '{field_name}' must be a valid number, got {v}: {e}")
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"Field '{field_name}' must be finite, got non-finite value: {val}.")
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
# 3. CONFIDENCE MODELS
# =============================================================================

class ConfidenceDimension(BaseModel):
    """
    Evaluated status of an individual confidence dimension.
    Preserves raw measurement, normalized score, weights, and explicit deficiency reasons.
    """
    model_config = ConfigDict(extra="forbid")

    dimension_type: ConfidenceDimensionType = Field(description="Confidence dimension category.")
    score: Optional[float] = Field(default=None, description="Normalized score (0.0 to 1.0), or None if NOT_ASSESSABLE.")
    weight: float = Field(default=1.0, ge=0.0, description="Relative importance weight in aggregate calculation.")
    is_assessed: bool = Field(default=True, description="True if evidence supported evaluation of this dimension.")
    status: str = Field(default="ASSESSED", description="Dimension status: ASSESSED, DEFICIENT, NOT_ASSESSABLE, SKIPPED.")
    explanation: str = Field(default="", description="Narrative rationale explaining dimension score or deficiency.")
    deficiencies: List[str] = Field(default_factory=list, description="Specific defect codes identified.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Component-level metrics and inputs.")

    @field_validator("score", mode="before")
    @classmethod
    def check_score(cls, v: Any) -> Optional[float]:
        return validate_proportional_score(v, "score") if v is not None else None

    @field_validator("weight", mode="before")
    @classmethod
    def check_weight(cls, v: Any) -> float:
        val = validate_finite_number(v, "weight")
        if val < 0.0:
            raise ValueError("weight must be non-negative.")
        return val


class ConfidenceComponent(BaseModel):
    """
    A specific granular contributor to a confidence dimension.
    """
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(description="Unique component identifier.")
    name: str = Field(description="Human-readable component name.")
    dimension_type: ConfidenceDimensionType = Field(description="Parent confidence dimension.")
    score: Optional[float] = Field(default=None, description="Component score if quantified.")
    weight: float = Field(default=1.0, ge=0.0, description="Component weight.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Diagnostic details.")

    @field_validator("component_id", "name")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("score", mode="before")
    @classmethod
    def check_score(cls, v: Any) -> Optional[float]:
        return validate_proportional_score(v, "score") if v is not None else None


class ConfidenceEvidenceReference(BaseModel):
    """
    Reference to supporting or conflicting evidence with its specific evidential role.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(description="Unique evidence identifier.")
    source_type: EvidenceSourceType = Field(description="Originating analytical subsystem.")
    source_record_id: str = Field(description="Record ID in source subsystem.")
    provenance: EvidenceProvenance = Field(description="Provenance classification.")
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Data quality score.")
    age_seconds: Optional[float] = Field(default=None, ge=0.0, description="Age in seconds relative to assessment.")
    role: str = Field(default="SUPPORTING", description="Role: SUPPORTING, CONFLICTING, CORRELATED, EXCLUDED.")
    contributes_to_dimensions: List[ConfidenceDimensionType] = Field(default_factory=list, description="Dimensions affected.")
    notes: Optional[str] = Field(default=None, description="Diagnostic notes.")

    @field_validator("evidence_id", "source_record_id")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)

    @field_validator("quality_score", mode="before")
    @classmethod
    def check_quality(cls, v: Any) -> float:
        return validate_proportional_score(v, "quality_score")


class ConfidenceContribution(BaseModel):
    """
    Mathematical contribution of a dimension to the aggregate score.
    """
    model_config = ConfigDict(extra="forbid")

    dimension_type: ConfidenceDimensionType = Field(description="Evaluated dimension.")
    raw_score: Optional[float] = Field(default=None, description="Raw dimension score.")
    weight: float = Field(description="Normalized weight used.")
    weighted_contribution: float = Field(default=0.0, description="Score * weight contribution.")
    blocking_deficiency: bool = Field(default=False, description="True if dimension triggered a blocking cap.")


class ConfidenceCalibrationMetadata(BaseModel):
    """
    Empirical calibration information. Distinguishes calibrated models from heuristic scoring.
    """
    model_config = ConfigDict(extra="forbid")

    is_calibrated: bool = Field(default=False, description="True only if validated statistical calibration exists.")
    calibration_status: CalibrationStatus = Field(default=CalibrationStatus.UNASSESSED, description="Calibration status.")
    calibration_method: Optional[str] = Field(default=None, description="Statistical calibration method used (e.g., Platt, Isotonic).")
    sample_size: Optional[int] = Field(default=None, ge=1, description="Number of validation samples evaluated.")
    brier_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Brier calibration score if available.")
    expected_calibration_error: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="ECE score if available.")
    last_calibrated_at: Optional[str] = Field(default=None, description="ISO timestamp of last calibration.")
    notes: str = Field(default="Uncalibrated analytical heuristic. Not a statistical probability.", description="Interpretive guidance.")


class ConfidenceLimitation(BaseModel):
    """
    Explicit boundary condition or limitation in the confidence assessment.
    """
    model_config = ConfigDict(extra="forbid")

    limitation_id: str = Field(description="Unique limitation identifier.")
    code: str = Field(description="Limitation code: INSUFFICIENT_EVIDENCE, CRITICAL_DEFICIENCY, UNCALIBRATED, etc.")
    description: str = Field(description="Detailed description of limitation.")
    severity: str = Field(default="MEDIUM", description="Severity: LOW, MEDIUM, HIGH, BLOCKING.")
    mitigation: Optional[str] = Field(default=None, description="Recommended operator review or additional data collection.")

    @field_validator("limitation_id", "code", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class ConfidenceAssessment(BaseModel):
    """
    Multi-dimensional confidence evaluation result.
    """
    model_config = ConfigDict(extra="forbid")

    aggregate_score: Optional[float] = Field(default=None, description="Composite score (0.0 to 1.0), or None if NOT_ASSESSABLE.")
    status: ConfidenceStatus = Field(description="Categorical confidence determination.")
    dimensions: List[ConfidenceDimension] = Field(description="Dimension-level evaluations.")
    contributions: List[ConfidenceContribution] = Field(default_factory=list, description="Mathematical contribution breakdown.")
    blocking_deficiencies: List[str] = Field(default_factory=list, description="Deficiencies that capped or blocked the score.")
    interpretations: str = Field(description="Defensible interpretation of confidence status.")
    aggregation_method: AggregationMethod = Field(default=AggregationMethod.WEIGHTED_DEFICIENCY_CAPPED, description="Aggregation formula.")

    @field_validator("aggregate_score", mode="before")
    @classmethod
    def check_agg_score(cls, v: Any) -> Optional[float]:
        return validate_proportional_score(v, "aggregate_score") if v is not None else None


# =============================================================================
# 4. UNCERTAINTY MODELS
# =============================================================================

class UncertaintySource(BaseModel):
    """
    Specific origin or driver of uncertainty.
    """
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(description="Unique source identifier.")
    source_type: str = Field(description="Originating entity or parameter.")
    description: str = Field(description="Description of uncertainty source.")
    severity: UncertaintySeverity = Field(default=UncertaintySeverity.MODERATE, description="Impact severity.")

    @field_validator("source_id", "source_type", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class UncertaintyRange(BaseModel):
    """
    Validated quantitative interval or bounds with strict mathematical guarantees.
    Enforces lower_bound <= upper_bound and finite numbers.
    """
    model_config = ConfigDict(extra="forbid")

    lower_bound: float = Field(description="Lower numerical bound.")
    upper_bound: float = Field(description="Upper numerical bound.")
    unit: str = Field(description="Physical, economic, or temporal unit (e.g. 'celsius', 'usd', 'hours').")
    confidence_level: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Statistical coverage probability if known (e.g. 0.95).")
    interval_type: UncertaintyIntervalType = Field(description="Category of interval.")
    distribution_assumptions: Optional[str] = Field(default=None, description="Explicit distribution assumptions (e.g. 'Normal', 'Student-t').")
    description: Optional[str] = Field(default=None, description="Interval description.")

    @field_validator("lower_bound", "upper_bound", mode="before")
    @classmethod
    def check_bounds_finite(cls, v: Any, info) -> float:
        return validate_finite_number(v, info.field_name)

    @field_validator("unit")
    @classmethod
    def check_unit(cls, v: str) -> str:
        return validate_identifier(v, "unit")

    @model_validator(mode="after")
    def validate_bound_order(self) -> "UncertaintyRange":
        if self.lower_bound > self.upper_bound:
            raise ValueError(f"lower_bound ({self.lower_bound}) cannot exceed upper_bound ({self.upper_bound}).")
        return self


class UncertaintyDistributionSummary(BaseModel):
    """
    Summary statistics of a modeled probability distribution.
    Only reported when mathematically justified by empirical observations or validated simulations.
    """
    model_config = ConfigDict(extra="forbid")

    distribution_type: str = Field(description="Assumed or fitted distribution (e.g. 'Gaussian', 'Weibull', 'Empirical').")
    mean: Optional[float] = Field(default=None, description="Expected value.")
    median: Optional[float] = Field(default=None, description="Median value.")
    std_dev: Optional[float] = Field(default=None, ge=0.0, description="Standard deviation.")
    p05: Optional[float] = Field(default=None, description="5th percentile.")
    p25: Optional[float] = Field(default=None, description="25th percentile.")
    p75: Optional[float] = Field(default=None, description="75th percentile.")
    p95: Optional[float] = Field(default=None, description="95th percentile.")
    sample_size: Optional[int] = Field(default=None, ge=1, description="Number of supporting observations.")

    @field_validator("mean", "median", "std_dev", "p05", "p25", "p75", "p95", mode="before")
    @classmethod
    def check_numbers_finite(cls, v: Any, info) -> Optional[float]:
        return validate_finite_number(v, info.field_name) if v is not None else None


class UncertaintySensitivity(BaseModel):
    """
    Sensitivity of the analytical conclusion to a specific uncertain parameter.
    """
    model_config = ConfigDict(extra="forbid")

    parameter_name: str = Field(description="Input parameter or variable evaluated.")
    sensitivity_index: float = Field(description="Sensitivity gradient or correlation index.")
    elasticity: Optional[float] = Field(default=None, description="Percentage change in outcome per 1% change in parameter.")
    notes: str = Field(default="", description="Qualitative findings.")

    @field_validator("parameter_name")
    @classmethod
    def check_param(cls, v: str) -> str:
        return validate_identifier(v, "parameter_name")

    @field_validator("sensitivity_index", mode="before")
    @classmethod
    def check_sens(cls, v: Any) -> float:
        return validate_finite_number(v, "sensitivity_index")


class UncertaintyPropagation(BaseModel):
    """
    Trace of how uncertainty in an upstream subsystem propagated into this analytical assessment.
    """
    model_config = ConfigDict(extra="forbid")

    upstream_component: str = Field(description="Upstream subsystem or model name.")
    propagated_uncertainty_type: UncertaintyType = Field(description="Type of propagated uncertainty.")
    impact_factor: float = Field(default=1.0, ge=0.0, description="Magnification or dampening factor.")
    description: str = Field(description="Propagation narrative.")

    @field_validator("upstream_component", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class UncertaintyComponent(BaseModel):
    """
    Granular decomposed uncertainty element.
    """
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(description="Unique component identifier.")
    uncertainty_type: UncertaintyType = Field(description="Category of uncertainty.")
    severity: UncertaintySeverity = Field(default=UncertaintySeverity.MODERATE, description="Severity assessment.")
    description: str = Field(description="Narrative explanation.")
    is_quantified: bool = Field(default=False, description="True if supported by a validated range or distribution.")
    range_assessment: Optional[UncertaintyRange] = Field(default=None, description="Quantitative range if justified.")
    sources: List[UncertaintySource] = Field(default_factory=list, description="Contributing uncertainty sources.")

    @field_validator("component_id", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class UncertaintyDecomposition(BaseModel):
    """
    Decomposition into aleatoric, epistemic, and specialized uncertainty dimensions.
    """
    model_config = ConfigDict(extra="forbid")

    aleatoric_components: List[UncertaintyComponent] = Field(default_factory=list, description="Inherent stochastic variability.")
    epistemic_components: List[UncertaintyComponent] = Field(default_factory=list, description="Reducible knowledge / data gaps.")
    other_components: List[UncertaintyComponent] = Field(default_factory=list, description="Model, scenario, or measurement components.")
    total_components_count: int = Field(default=0, ge=0, description="Total identified uncertainty components.")
    predominant_type: UncertaintyType = Field(default=UncertaintyType.UNKNOWN, description="Primary uncertainty driver.")
    summary: str = Field(description="Summary narrative of decomposed uncertainty.")


class UncertaintyLimitation(BaseModel):
    """
    Identified unquantified or unassessed uncertainty limitation.
    """
    model_config = ConfigDict(extra="forbid")

    limitation_id: str = Field(description="Unique limitation identifier.")
    code: str = Field(description="Structured limitation code.")
    description: str = Field(description="Detailed explanation.")
    severity: UncertaintySeverity = Field(default=UncertaintySeverity.MODERATE, description="Limitation severity.")
    notes: Optional[str] = Field(default=None, description="Operator guidance.")

    @field_validator("limitation_id", "code", "description")
    @classmethod
    def check_strings(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class UncertaintyAssessment(BaseModel):
    """
    Complete uncertainty assessment encompassing decomposition, bounds, sensitivities, and limitations.
    """
    model_config = ConfigDict(extra="forbid")

    decomposition: UncertaintyDecomposition = Field(description="Categorical decomposition.")
    primary_ranges: List[UncertaintyRange] = Field(default_factory=list, description="Validated quantitative intervals.")
    distribution_summary: Optional[UncertaintyDistributionSummary] = Field(default=None, description="Distribution summary if justified.")
    sensitivities: List[UncertaintySensitivity] = Field(default_factory=list, description="Parameter sensitivity findings.")
    propagations: List[UncertaintyPropagation] = Field(default_factory=list, description="Propagation traces.")
    limitations: List[UncertaintyLimitation] = Field(default_factory=list, description="Unassessed or unquantified limitations.")
    qualitative_summary: str = Field(description="Executive narrative of overall uncertainty.")


# =============================================================================
# 5. REQUEST & RESPONSE MODELS
# =============================================================================

class ConfidenceUncertaintyMethod(BaseModel):
    """
    Formal specification of the calculation algorithm and version used.
    """
    model_config = ConfigDict(extra="forbid")

    method_name: str = Field(default="SageMultiDimensionalConfidenceEngine", description="Engine algorithm name.")
    version: str = Field(default=ALGORITHM_VERSION, description="Algorithm semantic version.")
    formula_reference: str = Field(default="SAGE_V3_CONF_EQ_1", description="Documented formula identifier.")
    description: str = Field(default="Deterministic weighted deficiency-capped multi-dimensional evaluation.", description="Method summary.")


class ConfidenceUncertaintyRequest(BaseModel):
    """
    Request to assess confidence and uncertainty for a target analytical entity or recommendation.
    """
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(description="Subsystem or entity type: DECISION_ENGINE, OPTIMIZATION, WHAT_IF_SIMULATION, SENSOR_FUSION, etc.")
    target_id: str = Field(description="Primary identifier of target record to assess.")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope if applicable.")
    assessment_timestamp: Optional[str] = Field(default=None, description="Fixed evaluation timestamp (prevents temporal leakage).")
    evidence_items: List[EvidenceRecord] = Field(default_factory=list, description="Explicit in-memory evidence records to evaluate.")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Custom freshness threshold in seconds.")
    required_dimensions: Optional[List[ConfidenceDimensionType]] = Field(default=None, description="Dimensions required for this assessment.")
    weights_override: Optional[Dict[str, float]] = Field(default=None, description="Custom dimension weights.")
    include_ranges: bool = Field(default=True, description="Whether to compute quantitative uncertainty ranges.")
    include_sensitivities: bool = Field(default=True, description="Whether to evaluate parameter sensitivities.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata.")

    @field_validator("target_type", "target_id", "tenant_id", "workspace_id")
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


class ConfidenceValidationRequest(BaseModel):
    """
    Request to validate evidence items for confidence evaluation readiness.
    """
    model_config = ConfigDict(extra="forbid")

    evidence_items: List[EvidenceRecord] = Field(description="Evidence items to inspect.")
    target_type: str = Field(description="Target subsystem type.")
    target_id: str = Field(description="Target entity ID.")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope.")
    assessment_timestamp: Optional[str] = Field(default=None, description="Evaluation timestamp.")
    freshness_threshold_seconds: Optional[float] = Field(default=None, ge=0.0, description="Freshness threshold.")

    @field_validator("target_type", "target_id", "tenant_id", "workspace_id")
    @classmethod
    def check_ids(cls, v: str, info) -> str:
        return validate_identifier(v, info.field_name)


class ConfidenceValidationResponse(BaseModel):
    """
    Eligibility and readiness validation response.
    """
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="Target entity ID.")
    is_eligible: bool = Field(description="True if evidence is sufficient to compute meaningful confidence.")
    eligible_evidence_count: int = Field(ge=0, description="Valid evidence records.")
    rejected_evidence_count: int = Field(ge=0, description="Rejected or invalid evidence records.")
    deficiencies: List[str] = Field(default_factory=list, description="Identified blocking deficiencies.")
    assessment_readiness: str = Field(description="Readiness status: READY, PARTIAL, INSUFFICIENT, INELIGIBLE.")
    evaluated_at: str = Field(description="ISO timestamp of evaluation.")
    fingerprint: str = Field(description="Deterministic fingerprint of validation outcome.")


class ConfidenceUncertaintyResult(BaseModel):
    """
    Canonical output of the Confidence and Uncertainty Intelligence Foundation.
    Immutable, fully explainable, deterministic analytical result.
    """
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(description="Deterministic assessment identifier.")
    target_type: str = Field(description="Target analytical subsystem.")
    target_id: str = Field(description="Target entity identifier.")
    tenant_id: str = Field(description="Tenant isolation scope.")
    workspace_id: str = Field(description="Workspace isolation scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant isolation scope.")
    assessment_timestamp: str = Field(description="Fixed assessment timestamp.")
    confidence: ConfidenceAssessment = Field(description="Evaluated confidence.")
    uncertainty: UncertaintyAssessment = Field(description="Evaluated uncertainty.")
    supporting_evidence: List[ConfidenceEvidenceReference] = Field(default_factory=list, description="Corroborating evidence items.")
    conflicting_evidence: List[ConfidenceEvidenceReference] = Field(default_factory=list, description="Conflicting evidence items.")
    duplicate_evidence_warnings: List[str] = Field(default_factory=list, description="Duplicate evidence detected.")
    correlation_warnings: List[str] = Field(default_factory=list, description="Strong correlation / dependent source warnings.")
    method: ConfidenceUncertaintyMethod = Field(default_factory=ConfidenceUncertaintyMethod, description="Calculation method metadata.")
    calibration: ConfidenceCalibrationMetadata = Field(default_factory=ConfidenceCalibrationMetadata, description="Calibration information.")
    limitations: List[ConfidenceLimitation] = Field(default_factory=list, description="Explicit limitations and unassessed uncertainty.")
    fingerprint: str = Field(description="Cryptographic SHA-256 fingerprint for integrity and reproducibility.")
    mandatory_notice: str = Field(default=MANDATORY_CONFIDENCE_NOTICE, description="Mandatory non-execution notice.")
    created_at: str = Field(description="ISO timestamp of result creation.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context metadata.")


class ConfidenceUncertaintySummary(BaseModel):
    """
    Lightweight summary for listings, dashboards, and audit summaries.
    """
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(description="Assessment identifier.")
    target_type: str = Field(description="Target subsystem.")
    target_id: str = Field(description="Target entity ID.")
    tenant_id: str = Field(description="Tenant partition.")
    workspace_id: str = Field(description="Workspace scope.")
    plant_id: Optional[str] = Field(default=None, description="Plant scope.")
    aggregate_confidence: Optional[float] = Field(default=None, description="Overall score if assessable.")
    confidence_status: ConfidenceStatus = Field(description="Confidence status.")
    predominant_uncertainty: UncertaintyType = Field(description="Primary uncertainty driver.")
    assessment_timestamp: str = Field(description="Evaluation timestamp.")
    fingerprint: str = Field(description="SHA-256 fingerprint.")
    created_at: str = Field(description="Creation timestamp.")


class ConfidenceUncertaintyListResponse(BaseModel):
    """
    Paginated list of historical confidence/uncertainty assessments.
    """
    model_config = ConfigDict(extra="forbid")

    items: List[ConfidenceUncertaintySummary] = Field(description="Summary items.")
    total_count: int = Field(ge=0, description="Total matching items in scope.")
    limit: int = Field(ge=1, description="Page limit.")
    offset: int = Field(ge=0, description="Page offset.")


class ConfidenceAuditRecord(BaseModel):
    """
    Append-only audit record tracking assessment creation, evaluation, and access.
    """
    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(description="Unique audit record identifier.")
    assessment_id: str = Field(description="Referenced assessment identifier.")
    tenant_id: str = Field(description="Tenant isolation partition.")
    actor_id: str = Field(description="User or service identity that performed the action.")
    action: str = Field(description="Action name: ASSESS, VALIDATE, RETRIEVE, EXPORT.")
    timestamp: str = Field(description="ISO timestamp of audit event.")
    fingerprint: str = Field(description="Assessment fingerprint at audit time.")
    details: Dict[str, Any] = Field(default_factory=dict, description="Audit event details.")


# =============================================================================
# 6. DETERMINISTIC FINGERPRINT COMPUTATION
# =============================================================================

def compute_confidence_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    target_type: str,
    target_id: str,
    assessment_timestamp: str,
    algorithm_version: str,
    dimension_scores: Dict[str, Optional[float]],
    uncertainty_types: List[str],
    supporting_evidence_ids: List[str],
    conflicting_evidence_ids: List[str],
    blocking_deficiencies: List[str],
) -> str:
    """
    Generates a deterministic cryptographic SHA-256 fingerprint representing the canonical
    state and material inputs of a confidence & uncertainty assessment.
    """
    material_payload = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "plant_id": plant_id or "",
        "target_type": target_type,
        "target_id": target_id,
        "assessment_timestamp": assessment_timestamp,
        "algorithm_version": algorithm_version,
        "dimension_scores": {k: dimension_scores[k] for k in sorted(dimension_scores.keys())},
        "uncertainty_types": sorted(uncertainty_types),
        "supporting_evidence_ids": sorted(supporting_evidence_ids),
        "conflicting_evidence_ids": sorted(conflicting_evidence_ids),
        "blocking_deficiencies": sorted(blocking_deficiencies),
    }
    canonical_json = json.dumps(material_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
