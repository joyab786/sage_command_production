# backend/data/schemas/what_if_simulation_contract.py
"""
SageCommand V3 — What-If Simulation Intelligence Foundation Contracts (Prompt 28)

ANALYTICAL ONLY.
Deterministic counterfactual simulation layer.
Constructs hypothetical operational scenarios, computes analytical delta states,
evaluates scenario constraints, propagates bounded downstream impacts,
and preserves complete provenance, temporal correctness, and evidence chains.

Cardinal Invariant:
The What-If Simulator is an analytical counterfactual engine.
It NEVER executes physical commands, triggers work orders, writes to PLCs/controllers,
mutates inventories, issues purchase orders, or bypasses the human decision boundary.
"""

from enum import Enum
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone
import hashlib
import json
import math
from pydantic import BaseModel, Field, ConfigDict, field_validator

try:
    from data.schemas.sensor_fusion_contract import SensorValueProvenance
except ModuleNotFoundError:
    from backend.data.schemas.sensor_fusion_contract import SensorValueProvenance


# =============================================================================
# 1. ENUMS (Sections 2, 5, 6, 7, 10, 19, 21, 22)
# =============================================================================

class SimulationClassification(str, Enum):
    """
    Architectural Classification of simulation values (Section 2).
    Never silently converted or aliased.
    """
    OBSERVED = "OBSERVED"    # What actually happened in real operations
    DERIVED = "DERIVED"      # Calculated from observed evidence
    SIMULATED = "SIMULATED"  # Hypothetical state generated from scenario
    ESTIMATED = "ESTIMATED"  # Model-based estimate where evidence is incomplete
    UNKNOWN = "UNKNOWN"      # Value cannot be responsibly determined


class SimulationTargetScope(str, Enum):
    """Scope of target industrial entities."""
    ENTITY = "ENTITY"
    LINE = "LINE"
    PLANT = "PLANT"
    SYSTEM = "SYSTEM"
    NETWORK = "NETWORK"


class ScenarioVariableType(str, Enum):
    """
    Explicit, controlled hypothetical changes (Section 6).
    No arbitrary executable code or expressions allowed.
    """
    DEMAND_CHANGE = "DEMAND_CHANGE"
    SUPPLY_CAPACITY_CHANGE = "SUPPLY_CAPACITY_CHANGE"
    LEAD_TIME_CHANGE = "LEAD_TIME_CHANGE"
    ASSET_AVAILABILITY_CHANGE = "ASSET_AVAILABILITY_CHANGE"
    ASSET_DEGRADATION_CHANGE = "ASSET_DEGRADATION_CHANGE"
    PROCESS_PARAMETER_CHANGE = "PROCESS_PARAMETER_CHANGE"
    ENERGY_CONSUMPTION_CHANGE = "ENERGY_CONSUMPTION_CHANGE"
    PRODUCTION_RATE_CHANGE = "PRODUCTION_RATE_CHANGE"
    QUALITY_RATE_CHANGE = "QUALITY_RATE_CHANGE"
    SUPPLIER_DELAY = "SUPPLIER_DELAY"
    INCIDENT_SEVERITY_CHANGE = "INCIDENT_SEVERITY_CHANGE"
    RESOURCE_AVAILABILITY_CHANGE = "RESOURCE_AVAILABILITY_CHANGE"
    CUSTOM_SCALAR_CHANGE = "CUSTOM_SCALAR_CHANGE"


class VariableChangeType(str, Enum):
    """How the variable modifies the baseline."""
    MULTIPLIER = "MULTIPLIER"          # e.g. 1.20 = 120% of baseline
    PERCENT_DELTA = "PERCENT_DELTA"    # e.g. +20.0 = +20%
    ABSOLUTE_DELTA = "ABSOLUTE_DELTA"  # e.g. +3.0 = baseline + 3.0 units
    SET_VALUE = "SET_VALUE"            # e.g. 0.85 = fixed target value


class ConstraintType(str, Enum):
    """Explicit threshold and capacity constraints (Section 19)."""
    MIN_CAPACITY = "MIN_CAPACITY"
    MAX_CAPACITY = "MAX_CAPACITY"
    MAX_UTILIZATION = "MAX_UTILIZATION"
    ASSET_AVAILABILITY = "ASSET_AVAILABILITY"
    SUPPLIER_CAPACITY = "SUPPLIER_CAPACITY"
    SLA_THRESHOLD = "SLA_THRESHOLD"
    QUALITY_THRESHOLD = "QUALITY_THRESHOLD"
    ENERGY_THRESHOLD = "ENERGY_THRESHOLD"
    RESOURCE_THRESHOLD = "RESOURCE_THRESHOLD"
    CUSTOM_THRESHOLD = "CUSTOM_THRESHOLD"


class ConstraintOperator(str, Enum):
    """Comparison operator for scenario constraint evaluation."""
    LTE = "LTE"          # value <= threshold
    GTE = "GTE"          # value >= threshold
    LT = "LT"            # value < threshold
    GT = "GT"            # value > threshold
    EQ = "EQ"            # value == threshold
    BETWEEN = "BETWEEN"  # threshold_value <= value <= threshold_max_value


class ConstraintStatus(str, Enum):
    """Outcome of constraint evaluation (Section 19)."""
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"
    UNKNOWN = "UNKNOWN"


class SimulationBaselineSource(str, Enum):
    """Legitimate analytical baseline sources (Section 7)."""
    DIGITAL_TWIN = "DIGITAL_TWIN"
    SENSOR_FUSION = "SENSOR_FUSION"
    DEMAND_FORECAST = "DEMAND_FORECAST"
    SUPPLIER_RISK = "SUPPLIER_RISK"
    SLA_CUSTOMER_RISK = "SLA_CUSTOMER_RISK"
    FINANCIAL_IMPACT = "FINANCIAL_IMPACT"
    SUSTAINABILITY = "SUSTAINABILITY"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    EXPLICIT_INPUT = "EXPLICIT_INPUT"


class SimulationMethod(str, Enum):
    """Deterministic simulation methods (Section 10)."""
    RULE_BASED_PROPAGATION = "RULE_BASED_PROPAGATION"
    LINEAR_SENSITIVITY = "LINEAR_SENSITIVITY"
    CAPACITY_PROPAGATION = "CAPACITY_PROPAGATION"
    DEPENDENCY_PROPAGATION = "DEPENDENCY_PROPAGATION"
    STATE_TRANSITION_SIMULATION = "STATE_TRANSITION_SIMULATION"
    THRESHOLD_SIMULATION = "THRESHOLD_SIMULATION"
    BOUNDED_IMPACT_PROPAGATION = "BOUNDED_IMPACT_PROPAGATION"
    COMPOSITE_DETERMINISTIC = "COMPOSITE_DETERMINISTIC"


class SimulationConfidence(str, Enum):
    """Confidence classification (Section 22)."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DeltaClassification(str, Enum):
    """Delta state categorization (Section 21)."""
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    UNKNOWN = "UNKNOWN"
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"


class ImpactCategory(str, Enum):
    """Downstream affected domains (Section 16-18)."""
    CAPACITY = "CAPACITY"
    DEMAND = "DEMAND"
    SUPPLY = "SUPPLY"
    SLA = "SLA"
    FINANCIAL = "FINANCIAL"
    SUSTAINABILITY = "SUSTAINABILITY"
    OPERATIONAL_MAINTENANCE = "OPERATIONAL_MAINTENANCE"
    DOWNSTREAM_DEPENDENCY = "DOWNSTREAM_DEPENDENCY"


# =============================================================================
# 2. CORE DOMAIN MODELS (Section 5)
# =============================================================================

class SimulationTarget(BaseModel):
    """Identifies target entity or group for scenario evaluation."""
    model_config = ConfigDict(extra="ignore")

    entity_id: str = Field(..., min_length=1, max_length=128, description="Target entity ID e.g. MCH-01, SUP-100")
    entity_type: str = Field(default="EQUIPMENT", max_length=64, description="Target type e.g. MACHINE, SUPPLIER")
    name: Optional[str] = Field(None, max_length=128)
    target_scope: SimulationTargetScope = Field(default=SimulationTargetScope.ENTITY)


class ScenarioVariable(BaseModel):
    """
    Hypothetical change applied to the simulation baseline (Section 6).
    Must NOT contain executable code or dynamic expressions.
    """
    model_config = ConfigDict(extra="ignore")

    variable_id: str = Field(..., min_length=1, max_length=64)
    variable_type: ScenarioVariableType = Field(...)
    target_entity_id: Optional[str] = Field(None, max_length=128)
    parameter_name: str = Field(..., min_length=1, max_length=128)
    change_type: VariableChangeType = Field(default=VariableChangeType.PERCENT_DELTA)
    value: float = Field(..., description="Finite numeric scalar only")
    unit: Optional[str] = Field(None, max_length=32)
    baseline_reference_value: Optional[float] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    description: Optional[str] = Field(None, max_length=256)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("value")
    @classmethod
    def validate_finite_value(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("ScenarioVariable value must be a finite numeric scalar")
        return float(v)


class ScenarioConstraint(BaseModel):
    """Configured constraint or boundary condition (Section 19)."""
    model_config = ConfigDict(extra="ignore")

    constraint_id: str = Field(..., min_length=1, max_length=64)
    constraint_type: ConstraintType = Field(...)
    target_entity_id: Optional[str] = Field(None, max_length=128)
    metric_name: str = Field(..., min_length=1, max_length=128)
    operator: ConstraintOperator = Field(default=ConstraintOperator.LTE)
    threshold_value: float = Field(...)
    threshold_max_value: Optional[float] = None
    unit: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = Field(None, max_length=256)


class ConstraintEvaluationResult(BaseModel):
    """Result of evaluating a ScenarioConstraint against simulated state."""
    model_config = ConfigDict(extra="ignore")

    constraint_id: str
    constraint_type: ConstraintType
    metric_name: str
    status: ConstraintStatus
    observed_or_baseline_value: Optional[float] = None
    simulated_value: Optional[float] = None
    threshold_value: float
    unit: Optional[str] = None
    margin: Optional[float] = None
    explanation: str


class SimulationAssumption(BaseModel):
    """Documented hypothesis or environmental assumption."""
    model_config = ConfigDict(extra="ignore")

    assumption_id: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=512)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    is_expired: bool = False
    source: str = Field(default="USER", max_length=64)


class SimulationLimitation(BaseModel):
    """Explicit analytical limitation (Section 30)."""
    model_config = ConfigDict(extra="ignore")

    limitation_id: str
    category: str  # UNSUPPORTED_RELATIONSHIP, INSUFFICIENT_EVIDENCE, MISSING_FACTOR, EXPIRED_ASSUMPTION
    description: str
    affected_metrics: List[str] = Field(default_factory=list)


class SimulationEvidence(BaseModel):
    """Deterministic, auditable evidence item supporting a simulation finding (Section 23)."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    source_type: str  # SCENARIO_VARIABLE, BASELINE_OBSERVATION, SENSOR_FUSION, DIGITAL_TWIN, etc.
    source_id: str
    source_timestamp: str
    relationship: str
    contribution: str = Field(default="PRIMARY")  # PRIMARY, CORROBORATING, CONTEXTUAL, LIMITING
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.DERIVED)
    confidence: SimulationConfidence = Field(default=SimulationConfidence.HIGH)
    explanation: str


class SimulationUncertainty(BaseModel):
    """Uncertainty quantification distinguishing specific uncertainty dimensions (Section 22)."""
    model_config = ConfigDict(extra="ignore")

    overall_uncertainty: str = "LOW"             # LOW, MEDIUM, HIGH, UNKNOWN
    measurement_uncertainty: str = "LOW"
    model_uncertainty: str = "LOW"
    scenario_uncertainty: str = "LOW"
    dependency_uncertainty: str = "LOW"
    data_quality_uncertainty: str = "LOW"
    explanation: str = "Deterministic linear/sensitivity model with verified baseline observations"


class SimulationDelta(BaseModel):
    """Deterministic difference between simulated and baseline values (Section 21)."""
    model_config = ConfigDict(extra="ignore")

    metric_name: str
    target_entity_id: Optional[str] = None
    baseline_value: Optional[float] = None
    simulated_value: Optional[float] = None
    delta: Optional[float] = None
    delta_percent: Optional[float] = None
    unit: Optional[str] = None
    classification: DeltaClassification = Field(default=DeltaClassification.UNCHANGED)
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.SIMULATED)
    confidence: SimulationConfidence = Field(default=SimulationConfidence.HIGH)


class ImpactAssessment(BaseModel):
    """Downstream affected domain impact assessment (Section 16-18)."""
    model_config = ConfigDict(extra="ignore")

    impact_id: str
    category: ImpactCategory
    affected_entity_id: str
    affected_entity_type: str = "EQUIPMENT"
    description: str
    severity: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL, UNKNOWN
    baseline_metric: Optional[float] = None
    projected_metric: Optional[float] = None
    delta_metric: Optional[float] = None
    unit: Optional[str] = None
    propagation_distance: int = 0
    confidence: SimulationConfidence = Field(default=SimulationConfidence.HIGH)
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.SIMULATED)
    evidence_ids: List[str] = Field(default_factory=list)


class VariableContribution(BaseModel):
    """Individual contribution of each scenario variable (Section 9)."""
    model_config = ConfigDict(extra="ignore")

    variable_id: str
    variable_type: ScenarioVariableType
    parameter_name: str
    individual_effect: Dict[str, float] = Field(default_factory=dict)
    contribution_pct: Optional[float] = None


class SimulationBaseline(BaseModel):
    """Defensible baseline snapshot required for every simulation (Section 7)."""
    model_config = ConfigDict(extra="ignore")

    baseline_id: str = Field(..., min_length=1, max_length=128)
    source: SimulationBaselineSource = Field(...)
    source_id: str = Field(..., min_length=1, max_length=128)
    source_timestamp: str = Field(..., description="ISO 8601 timestamp of baseline state")
    effective_at: str = Field(..., description="ISO 8601 timestamp when baseline was effective")
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.OBSERVED)
    data_quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    confidence: str = Field(default="HIGH")
    metrics: Dict[str, Any] = Field(default_factory=dict)
    entity_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SimulatedState(BaseModel):
    """Synthesized counterfactual state resulting from scenario application (Section 15)."""
    model_config = ConfigDict(extra="ignore")

    entity_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.SIMULATED)
    effective_at: str
    state_classification: str = Field(default="SIMULATED")


class SimulationScenario(BaseModel):
    """Complete specification of a hypothetical counterfactual scenario (Section 5)."""
    model_config = ConfigDict(extra="ignore")

    scenario_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = Field(None, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(None, max_length=512)
    target_scope: SimulationTargetScope = Field(default=SimulationTargetScope.ENTITY)
    targets: List[SimulationTarget] = Field(default_factory=list)
    variables: List[ScenarioVariable] = Field(default_factory=list)
    constraints: List[ScenarioConstraint] = Field(default_factory=list)
    baseline_reference: Optional[str] = None
    assumptions: List[SimulationAssumption] = Field(default_factory=list)
    method: SimulationMethod = Field(default=SimulationMethod.COMPOSITE_DETERMINISTIC)
    method_version: str = Field(default="1.0.0")
    created_at: str
    assessment_timestamp: str
    scenario_start: Optional[str] = None
    scenario_end: Optional[str] = None
    horizon: str = Field(default="P7D")


class SimulationResult(BaseModel):
    """
    Complete, explainable, immutable What-If Simulation outcome (Section 20).
    Preserves all deltas, impact assessments, evidence, and input fingerprints.
    """
    model_config = ConfigDict(extra="ignore")

    simulation_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = None
    scenario: SimulationScenario
    baseline: SimulationBaseline
    simulated_state: SimulatedState
    deltas: List[SimulationDelta] = Field(default_factory=list)
    affected_entities: List[str] = Field(default_factory=list)
    constraint_results: List[ConstraintEvaluationResult] = Field(default_factory=list)
    impact_assessments: List[ImpactAssessment] = Field(default_factory=list)
    variable_contributions: List[VariableContribution] = Field(default_factory=list)
    interaction_effect: str = Field(default="UNKNOWN")  # INDEPENDENT, SUPER_ADDITIVE, SUB_ADDITIVE, UNKNOWN
    evidence: List[SimulationEvidence] = Field(default_factory=list)
    confidence: SimulationConfidence = Field(default=SimulationConfidence.HIGH)
    uncertainty: SimulationUncertainty
    data_quality_score: Optional[float] = None
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.SIMULATED)
    limitations: List[SimulationLimitation] = Field(default_factory=list)
    method: SimulationMethod = Field(default=SimulationMethod.COMPOSITE_DETERMINISTIC)
    method_version: str = Field(default="1.0.0")
    rules_version: str = Field(default="1.0.0")
    parameter_version: str = Field(default="1.0.0")
    input_fingerprint: str = Field(..., min_length=64, max_length=64)
    created_at: str


# =============================================================================
# 3. API REQUEST & RESPONSE MODELS (Section 26)
# =============================================================================

class WhatIfAnalyzeRequest(BaseModel):
    """Request payload to construct and run a What-If simulation."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = Field(None, max_length=64)
    scenario_name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(None, max_length=512)
    targets: List[SimulationTarget] = Field(default_factory=list)
    variables: List[ScenarioVariable] = Field(default_factory=list)
    constraints: List[ScenarioConstraint] = Field(default_factory=list)
    baseline_source: Optional[SimulationBaselineSource] = None
    baseline_id: Optional[str] = None
    explicit_baseline: Optional[Dict[str, Any]] = None
    assessment_timestamp: Optional[str] = None
    horizon: str = Field(default="P7D")
    method: SimulationMethod = Field(default=SimulationMethod.COMPOSITE_DETERMINISTIC)
    max_propagation_depth: int = Field(default=5, ge=1, le=10)


class SimulationResultSummary(BaseModel):
    """Concise summary for list and history views."""
    model_config = ConfigDict(extra="ignore")

    simulation_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    scenario_name: str
    assessment_timestamp: str
    confidence: str
    target_count: int
    variable_count: int
    delta_count: int
    impact_count: int
    violations_count: int
    input_fingerprint: str
    created_at: str


class WhatIfListResponse(BaseModel):
    """Paginated list response of simulation results."""
    model_config = ConfigDict(extra="ignore")

    items: List[SimulationResultSummary]
    total_count: int


class WhatIfImpactResponse(BaseModel):
    """Impact assessments associated with a simulation."""
    model_config = ConfigDict(extra="ignore")

    simulation_id: str
    impacts: List[ImpactAssessment]


class WhatIfEvidenceResponse(BaseModel):
    """Evidence chain supporting a simulation."""
    model_config = ConfigDict(extra="ignore")

    simulation_id: str
    evidence: List[SimulationEvidence]


# =============================================================================
# 4. DETERMINISTIC FINGERPRINTING FUNCTION (Section 11, 24)
# =============================================================================

def compute_what_if_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    assessment_timestamp: str,
    horizon: str,
    targets: List[SimulationTarget],
    variables: List[ScenarioVariable],
    constraints: List[ScenarioConstraint],
    baseline_source: str,
    baseline_id: str,
    baseline_metrics: Dict[str, Any],
    method: str,
    method_version: str,
    rules_version: str,
    parameter_version: str,
) -> str:
    """
    Computes a deterministic SHA-256 fingerprint over all material simulation inputs.
    Strictly orders lists and dictionaries to ensure invariance to ordering.
    Contains NO non-deterministic components (UUIDs, wall-clock, memory addresses).
    """
    canonical_targets = sorted(
        [{"id": t.entity_id, "type": t.entity_type, "scope": t.target_scope.value} for t in targets],
        key=lambda x: (x["id"], x["type"])
    )

    canonical_variables = sorted(
        [
            {
                "var_id": v.variable_id,
                "type": v.variable_type.value,
                "target": v.target_entity_id or "",
                "param": v.parameter_name,
                "change_type": v.change_type.value,
                "value": round(float(v.value), 6),
                "unit": v.unit or "",
            }
            for v in variables
        ],
        key=lambda x: (x["var_id"], x["param"], x["target"])
    )

    canonical_constraints = sorted(
        [
            {
                "c_id": c.constraint_id,
                "type": c.constraint_type.value,
                "metric": c.metric_name,
                "op": c.operator.value,
                "thresh": round(float(c.threshold_value), 6),
                "thresh_max": round(float(c.threshold_max_value), 6) if c.threshold_max_value is not None else None,
            }
            for c in constraints
        ],
        key=lambda x: (x["c_id"], x["metric"])
    )

    canonical_baseline_metrics = {
        k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
        for k, v in sorted(baseline_metrics.items())
    }

    fingerprint_dict = {
        "tenant_id": tenant_id.strip(),
        "workspace_id": workspace_id.strip(),
        "plant_id": (plant_id or "").strip(),
        "assessment_timestamp": assessment_timestamp.strip(),
        "horizon": horizon.strip(),
        "targets": canonical_targets,
        "variables": canonical_variables,
        "constraints": canonical_constraints,
        "baseline_source": baseline_source.strip(),
        "baseline_id": baseline_id.strip(),
        "baseline_metrics": canonical_baseline_metrics,
        "method": method.strip(),
        "method_version": method_version.strip(),
        "rules_version": rules_version.strip(),
        "parameter_version": parameter_version.strip(),
    }

    serialized = json.dumps(fingerprint_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
