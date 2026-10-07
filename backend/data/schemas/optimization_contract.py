# backend/data/schemas/optimization_contract.py
"""
SageCommand V3 — Optimization Intelligence Foundation Contracts (Prompt 29)

ANALYTICAL DECISION SUPPORT ONLY.
Defines typed contracts for optimization problems, decision variables, domains,
objectives, constraints, candidates, solutions, feasibility, trade-offs,
sensitivity analysis, robustness, evidence, and deterministic SHA-256 fingerprinting.

Cardinal Invariant:
The Optimization Intelligence layer produces governed ANALYTICAL RECOMMENDATIONS.
It is NOT an operational execution command.
It NEVER executes physical commands, triggers work orders, writes to PLCs/controllers,
mutates inventories, issues purchase orders, sends customer messages,
or bypasses the human decision boundary.

Boundary:
OPTIMIZATION -> RECOMMENDATION -> HUMAN / AUTHORIZED DECISION -> [future execution path]
Never: OPTIMIZATION -> AUTOMATIC EXECUTION.
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
# 1. ENUMS (Sections 7, 8, 9, 10, 11, 13, 14, 15, 16, 21, 36, 39, 40)
# =============================================================================

class DecisionScope(str, Enum):
    """Scope of optimization problem."""
    ENTITY = "ENTITY"
    LINE = "LINE"
    PLANT = "PLANT"
    SUPPLY_CHAIN = "SUPPLY_CHAIN"
    ENTERPRISE = "ENTERPRISE"
    MULTI_PLANT = "MULTI_PLANT"


class DecisionVariableType(str, Enum):
    """
    Explicitly typed analytical decision variables (Section 8).
    These represent analytical allocations and planning decisions only.
    Physical or operational actuation commands are strictly forbidden.
    """
    ALLOCATE_CAPACITY = "ALLOCATE_CAPACITY"
    ALLOCATE_DEMAND = "ALLOCATE_DEMAND"
    ASSIGN_SUPPLIER = "ASSIGN_SUPPLIER"
    ALLOCATE_RESOURCE = "ALLOCATE_RESOURCE"
    PRIORITIZE_ASSET = "PRIORITIZE_ASSET"
    ALLOCATE_MAINTENANCE_CAPACITY = "ALLOCATE_MAINTENANCE_CAPACITY"
    SET_PRODUCTION_LEVEL = "SET_PRODUCTION_LEVEL"
    SET_RESOURCE_LEVEL = "SET_RESOURCE_LEVEL"
    SELECT_SCENARIO = "SELECT_SCENARIO"
    ROUTE_ANALYTICAL_FLOW = "ROUTE_ANALYTICAL_FLOW"


# Explicit list of forbidden physical/actuation command keywords (Section 8)
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
}


class DecisionDomainType(str, Enum):
    """Supported domains for decision variables (Section 9)."""
    CONTINUOUS = "CONTINUOUS"
    INTEGER = "INTEGER"
    BINARY = "BINARY"
    CATEGORICAL = "CATEGORICAL"
    BOUNDED_SCALAR = "BOUNDED_SCALAR"
    BOUNDED_PERCENTAGE = "BOUNDED_PERCENTAGE"


class ObjectiveDirection(str, Enum):
    """Direction for objective optimization."""
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"


class ObjectiveType(str, Enum):
    """Explicitly supported industrial optimization objectives (Section 10)."""
    MINIMIZE_COST = "MINIMIZE_COST"
    MINIMIZE_DOWNTIME = "MINIMIZE_DOWNTIME"
    MINIMIZE_DELAY = "MINIMIZE_DELAY"
    MINIMIZE_RISK = "MINIMIZE_RISK"
    MINIMIZE_SERVICE_PENALTY = "MINIMIZE_SERVICE_PENALTY"
    MINIMIZE_RESOURCE_USAGE = "MINIMIZE_RESOURCE_USAGE"
    MINIMIZE_ENERGY = "MINIMIZE_ENERGY"
    MINIMIZE_EMISSIONS = "MINIMIZE_EMISSIONS"
    MAXIMIZE_THROUGHPUT = "MAXIMIZE_THROUGHPUT"
    MAXIMIZE_SERVICE_LEVEL = "MAXIMIZE_SERVICE_LEVEL"
    MAXIMIZE_UTILIZATION = "MAXIMIZE_UTILIZATION"
    MAXIMIZE_MARGIN = "MAXIMIZE_MARGIN"
    MAXIMIZE_RESILIENCE = "MAXIMIZE_RESILIENCE"


class MultiObjectiveMethod(str, Enum):
    """Deterministic multi-objective methods (Section 11)."""
    WEIGHTED_SUM = "WEIGHTED_SUM"
    LEXICOGRAPHIC = "LEXICOGRAPHIC"
    CONSTRAINT_FIRST = "CONSTRAINT_FIRST"
    PARETO_BOUNDED = "PARETO_BOUNDED"


class ConstraintType(str, Enum):
    """Typed optimization constraints (Section 13)."""
    CAPACITY = "CAPACITY"
    DEMAND = "DEMAND"
    INVENTORY_AVAILABILITY = "INVENTORY_AVAILABILITY"
    SUPPLIER_CAPACITY = "SUPPLIER_CAPACITY"
    ASSET_AVAILABILITY = "ASSET_AVAILABILITY"
    RESOURCE_AVAILABILITY = "RESOURCE_AVAILABILITY"
    PRODUCTION_LIMIT = "PRODUCTION_LIMIT"
    QUALITY_LIMIT = "QUALITY_LIMIT"
    SLA_LIMIT = "SLA_LIMIT"
    ENERGY_LIMIT = "ENERGY_LIMIT"
    EMISSION_LIMIT = "EMISSION_LIMIT"
    BUDGET_LIMIT = "BUDGET_LIMIT"
    DEPENDENCY = "DEPENDENCY"
    TEMPORAL = "TEMPORAL"
    SCENARIO = "SCENARIO"


class ConstraintOperator(str, Enum):
    """Deterministic operators for constraints (Section 14)."""
    LTE = "<="
    GTE = ">="
    EQ = "=="
    LT = "<"
    GT = ">"
    IN = "IN"
    NOT_IN = "NOT_IN"


class HardOrSoft(str, Enum):
    """Mandatory distinction between hard and soft constraints (Section 15)."""
    HARD = "HARD"
    SOFT = "SOFT"


class FeasibilityStatus(str, Enum):
    """Feasibility classification returned by feasibility engine (Section 16)."""
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    PARTIALLY_FEASIBLE = "PARTIALLY_FEASIBLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_PROBLEM = "INVALID_PROBLEM"


class OptimalityStatus(str, Enum):
    """Optimality semantics of the solver outcome (Section 21)."""
    OPTIMAL = "OPTIMAL"                        # Proven optimal via exhaustive/bounded search
    FEASIBLE_BEST_FOUND = "FEASIBLE_BEST_FOUND"  # Best feasible found under heuristic or truncation
    HEURISTIC = "HEURISTIC"                    # Solved via greedy/local improvement heuristic
    PARTIAL = "PARTIAL"                        # Partial solution only
    INFEASIBLE = "INFEASIBLE"                  # No feasible solution exists
    RESOURCE_LIMIT = "RESOURCE_LIMIT"          # Truncated by search bounds
    UNKNOWN = "UNKNOWN"                        # Status cannot be determined


class RobustnessStatus(str, Enum):
    """Deterministic robustness classification (Section 36)."""
    ROBUST = "ROBUST"
    SENSITIVE = "SENSITIVE"
    FRAGILE = "FRAGILE"
    UNKNOWN = "UNKNOWN"


class OptimizationConfidence(str, Enum):
    """Confidence classification reflecting input and assumption quality (Section 39)."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class OptimizationProvenance(str, Enum):
    """
    Standard provenance semantics (Section 40).
    Never transform provenance silently.
    """
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    FORECAST = "FORECAST"
    SIMULATED = "SIMULATED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class OptimizationSolverMethod(str, Enum):
    """Deterministic optimization solver methods (Section 18, 19)."""
    EXHAUSTIVE_BOUNDED = "EXHAUSTIVE_BOUNDED"
    GREEDY = "GREEDY"
    LOCAL_IMPROVEMENT = "LOCAL_IMPROVEMENT"
    LEXICOGRAPHIC = "LEXICOGRAPHIC"
    LINEAR_BOUNDED = "LINEAR_BOUNDED"
    PARETO_BOUNDED = "PARETO_BOUNDED"


# =============================================================================
# 2. DECISION DOMAIN & VARIABLES (Sections 8, 9)
# =============================================================================

class DecisionDomain(BaseModel):
    """
    Explicit mathematical domain for a decision variable (Section 9).
    Validates bounds, rejecting NaN, Inf, and invalid categorical choices.
    """
    model_config = ConfigDict(extra="ignore")

    domain_type: DecisionDomainType = Field(...)
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = Field(None, gt=0.0)
    allowed_categories: Optional[List[str]] = None

    @field_validator("min_value", "max_value")
    @classmethod
    def validate_finite_scalars(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Domain bounds must be finite numbers")
            return float(v)
        return v

    def validate_domain_integrity(self) -> None:
        """Ensures logical domain consistency."""
        if self.domain_type in (
            DecisionDomainType.CONTINUOUS,
            DecisionDomainType.INTEGER,
            DecisionDomainType.BOUNDED_SCALAR,
            DecisionDomainType.BOUNDED_PERCENTAGE,
        ):
            if self.min_value is None or self.max_value is None:
                raise ValueError(f"Domain {self.domain_type.value} requires both min_value and max_value")
            if self.min_value > self.max_value:
                raise ValueError(f"Domain min_value ({self.min_value}) exceeds max_value ({self.max_value})")

        if self.domain_type == DecisionDomainType.BOUNDED_PERCENTAGE:
            if self.min_value < 0.0 or self.max_value > 100.0:
                # Support [0.0, 1.0] or [0.0, 100.0]
                if self.min_value < 0.0 or self.max_value > 1.0:
                    raise ValueError("BOUNDED_PERCENTAGE domain must fall within [0.0, 1.0] or [0.0, 100.0]")

        if self.domain_type == DecisionDomainType.BINARY:
            self.min_value = 0.0
            self.max_value = 1.0
            self.step = 1.0

        if self.domain_type == DecisionDomainType.CATEGORICAL:
            if not self.allowed_categories or len(self.allowed_categories) == 0:
                raise ValueError("CATEGORICAL domain requires a non-empty allowed_categories list")


class DecisionVariable(BaseModel):
    """
    Explicitly typed analytical decision variable (Section 8).
    Strictly analytical — actuation/command keywords are forbidden.
    """
    model_config = ConfigDict(extra="ignore")

    variable_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    variable_type: DecisionVariableType = Field(...)
    target_entity_id: Optional[str] = Field(None, max_length=128)
    domain: DecisionDomain = Field(...)
    unit: Optional[str] = Field(None, max_length=32)
    initial_value: Optional[Union[float, str]] = None
    description: Optional[str] = Field(None, max_length=256)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("variable_id", "name")
    @classmethod
    def validate_non_actuating(cls, v: str) -> str:
        upper = v.upper()
        for kw in FORBIDDEN_ACTUATION_KEYWORDS:
            if kw in upper:
                raise ValueError(
                    f"Forbidden operational/physical keyword '{kw}' detected in decision variable identifier '{v}'. "
                    "Optimization decision variables are analytical only."
                )
        return v


# Backward-compatible alias
OptimizationVariable = DecisionVariable


# =============================================================================
# 3. OBJECTIVES (Sections 10, 11, 12)
# =============================================================================

class OptimizationObjective(BaseModel):
    """
    Explicit industrial optimization objective with auditable weights (Sections 10, 12).
    """
    model_config = ConfigDict(extra="ignore")

    objective_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    objective_type: ObjectiveType = Field(...)
    direction: ObjectiveDirection = Field(default=ObjectiveDirection.MINIMIZE)
    weight: float = Field(default=1.0, ge=0.0)
    unit: Optional[str] = Field(None, max_length=32)
    source: str = Field(default="USER_ANALYST", max_length=64)
    provenance: Union[OptimizationProvenance, SensorValueProvenance, str] = Field(default=OptimizationProvenance.DERIVED)
    method: str = Field(default="DETERMINISTIC_EVALUATION", max_length=64)
    weight_source: str = Field(default="EXPLICIT_CONFIG", max_length=64)
    weight_version: str = Field(default="1.0.0", max_length=32)
    normalization: Optional[str] = Field("MIN_MAX", max_length=64)
    order: int = Field(default=1, ge=1, description="Order for lexicographic evaluation")
    description: Optional[str] = Field(None, max_length=256)

    @field_validator("weight")
    @classmethod
    def validate_finite_weight(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v) or v < 0:
            raise ValueError("Objective weight must be a finite non-negative number")
        return float(v)


# =============================================================================
# 4. CONSTRAINTS (Sections 13, 14, 15)
# =============================================================================

class OptimizationConstraint(BaseModel):
    """
    Typed optimization constraint with hard vs soft distinction (Sections 13, 14, 15).
    No arbitrary executable expressions allowed.
    """
    model_config = ConfigDict(extra="ignore")

    constraint_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    constraint_type: ConstraintType = Field(...)
    target_entity_id: Optional[str] = Field(None, max_length=128)
    operator: ConstraintOperator = Field(default=ConstraintOperator.LTE)
    left_expression: str = Field(..., min_length=1, max_length=128, description="Variable or metric identifier")
    right_expression: Union[float, str, List[Union[str, float]]] = Field(..., description="Threshold, bound, or membership set")
    unit: Optional[str] = Field(None, max_length=32)
    hard_or_soft: HardOrSoft = Field(default=HardOrSoft.HARD)
    penalty_weight: float = Field(default=1000.0, ge=0.0, description="Penalty for soft constraint violation")
    source: str = Field(default="ENGINEERING_LIMIT", max_length=64)
    provenance: SensorValueProvenance = Field(default=SensorValueProvenance.OBSERVED)
    description: Optional[str] = Field(None, max_length=256)

    @field_validator("left_expression")
    @classmethod
    def validate_expression_safety(cls, v: str) -> str:
        # Prevent executable expressions, eval injection, etc.
        forbidden_chars = [";", "__", "import", "exec", "eval", "os.", "sys."]
        for fc in forbidden_chars:
            if fc in v:
                raise ValueError(f"Unsafe expression content '{fc}' in constraint expression")
        return v


class ConstraintEvaluationResult(BaseModel):
    """Result of evaluating an OptimizationConstraint on a candidate solution (Section 15)."""
    model_config = ConfigDict(extra="ignore")

    constraint_id: str
    name: str
    constraint_type: ConstraintType
    hard_or_soft: HardOrSoft
    satisfied: bool
    observed_value: Optional[float] = None
    threshold_value: Optional[float] = None
    margin: Optional[float] = None
    violation_magnitude: float = 0.0
    penalty: float = 0.0
    is_binding: bool = False
    reason: Optional[str] = None


# =============================================================================
# 5. CONTEXT, EVIDENCE & LIMITATIONS (Sections 3, 22-30, 37, 38)
# =============================================================================

class OptimizationContext(BaseModel):
    """
    Upstream analytical context consumed by the optimizer (Sections 3, 22-30).
    References What-If simulation, forecast, risks, Digital Twin, and Ontology.
    """
    model_config = ConfigDict(extra="ignore")

    simulation_id: Optional[str] = None
    forecast_reference: Optional[str] = None
    supplier_risk_reference: Optional[str] = None
    maintenance_reference: Optional[str] = None
    sla_reference: Optional[str] = None
    financial_reference: Optional[str] = None
    sustainability_reference: Optional[str] = None
    digital_twin_reference: Optional[str] = None
    graph_reference: Optional[str] = None
    baseline_metrics: Dict[str, Any] = Field(default_factory=dict)
    context_parameters: Dict[str, Any] = Field(default_factory=dict)


class OptimizationEvidence(BaseModel):
    """Deterministic, auditable evidence item supporting an optimization decision (Section 37)."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    source_type: str  # WHAT_IF_SIMULATION, DEMAND_FORECAST, SUPPLIER_RISK, DIGITAL_TWIN, etc.
    source_id: str
    source_timestamp: str
    relationship: str
    contribution: str = Field(default="PRIMARY")  # PRIMARY, CONSTRAINT, OBJECTIVE, CONTEXTUAL
    provenance: Union[OptimizationProvenance, SensorValueProvenance, str] = Field(default=OptimizationProvenance.DERIVED)
    confidence: OptimizationConfidence = Field(default=OptimizationConfidence.HIGH)
    explanation: str


class OptimizationLimitation(BaseModel):
    """Explicit limitation documented for the optimization result (Sections 20, 38)."""
    model_config = ConfigDict(extra="ignore")

    limitation_id: str
    category: str  # RESOURCE_LIMIT, HEURISTIC_LIMITATION, INSUFFICIENT_DATA, UNSUPPORTED_RELATIONSHIP
    description: str
    affected_variables: List[str] = Field(default_factory=list)
    affected_objectives: List[str] = Field(default_factory=list)


# =============================================================================
# 6. FEASIBILITY & RELAXATION (Sections 16, 17)
# =============================================================================

class FeasibilityResult(BaseModel):
    """
    Detailed feasibility assessment for the optimization problem (Sections 16, 17).
    Includes deterministic relaxation suggestions when infeasible.
    """
    model_config = ConfigDict(extra="ignore")

    status: FeasibilityStatus
    is_feasible: bool
    blocking_constraints: List[str] = Field(default_factory=list)
    relaxation_options: List[Dict[str, Any]] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)


# =============================================================================
# 7. CANDIDATE SOLUTIONS & RANKING (Sections 31, 32)
# =============================================================================

class OptimizationCandidate(BaseModel):
    """
    A single evaluated candidate allocation/decision (Section 31).
    Candidate ID is deterministically derived from sorted decision variable assignments.
    """
    model_config = ConfigDict(extra="ignore")

    candidate_id: str
    decision_values: Dict[str, Any]
    feasibility: FeasibilityStatus
    objective_values: Dict[str, float] = Field(default_factory=dict)
    constraint_results: List[ConstraintEvaluationResult] = Field(default_factory=list)
    score: float = 0.0
    rank: int = 1
    method: str = "DETERMINISTIC"
    is_recommended: bool = False
    evidence_ids: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# =============================================================================
# 8. TRADE-OFFS & SENSITIVITY (Sections 33, 34, 35, 36)
# =============================================================================

class TradeoffAssessment(BaseModel):
    """
    Deterministic comparison between two candidate solutions (Section 33).
    """
    model_config = ConfigDict(extra="ignore")

    base_candidate_id: str
    compared_candidate_id: str
    objective_deltas: Dict[str, float] = Field(default_factory=dict)
    objective_percent_deltas: Dict[str, float] = Field(default_factory=dict)
    tradeoff_summary: str
    advantages: List[str] = Field(default_factory=list)
    disadvantages: List[str] = Field(default_factory=list)


class SensitivityResult(BaseModel):
    """
    Result of a bounded parameter perturbation test (Section 34).
    """
    model_config = ConfigDict(extra="ignore")

    parameter: str
    baseline_value: float
    changed_value: float
    perturbation_pct: float
    objective_delta: float
    solution_change: Dict[str, Any] = Field(default_factory=dict)
    constraint_change: List[str] = Field(default_factory=list)
    feasibility_maintained: bool = True


# =============================================================================
# 9. EXPLANATION (Section 38)
# =============================================================================

class OptimizationExplanation(BaseModel):
    """
    Optimization-native structured explanation (Section 38).
    Generated deterministically from structured outputs without LLM hallucination.
    """
    model_config = ConfigDict(extra="ignore")

    why_selected: List[str] = Field(default_factory=list)
    why_not_selected: Dict[str, List[str]] = Field(default_factory=dict)
    binding_constraints: List[str] = Field(default_factory=list)
    objective_contributions: Dict[str, float] = Field(default_factory=dict)
    tradeoffs_summary: Optional[str] = None
    sensitivity_summary: Optional[str] = None
    alternative_count: int = 0
    alternative_explanation: Optional[str] = None
    limitations_summary: List[str] = Field(default_factory=list)


# =============================================================================
# 10. OPTIMIZATION PROBLEM & RESULT (Sections 7, 20, 21, 41, 42)
# =============================================================================

class OptimizationProblem(BaseModel):
    """
    Complete specification of an industrial optimization problem (Section 7).
    """
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = Field(None, max_length=64)
    problem_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(None, max_length=512)
    created_at: str
    assessment_timestamp: str
    horizon: str = Field(default="P7D")
    decision_scope: DecisionScope = Field(default=DecisionScope.PLANT)
    variables: List[DecisionVariable] = Field(default_factory=list)
    objectives: List[OptimizationObjective] = Field(default_factory=list)
    constraints: List[OptimizationConstraint] = Field(default_factory=list)
    context: OptimizationContext = Field(default_factory=OptimizationContext)
    multi_objective_method: MultiObjectiveMethod = Field(default=MultiObjectiveMethod.WEIGHTED_SUM)
    method: OptimizationSolverMethod = Field(default=OptimizationSolverMethod.EXHAUSTIVE_BOUNDED)
    method_version: str = Field(default="1.0.0")


class OptimizationResult(BaseModel):
    """
    Governed analytical recommendation produced by the optimizer (Sections 7, 21, 41).
    Cardinal Invariant: NOT an operational command. Does NOT mutate physical systems.
    """
    model_config = ConfigDict(extra="ignore")

    optimization_id: str = Field(..., min_length=1, max_length=64)
    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = None
    problem: OptimizationProblem
    feasibility: FeasibilityResult
    optimality_status: OptimalityStatus
    confidence: OptimizationConfidence
    recommended_solution: Optional[OptimizationCandidate] = None
    candidates: List[OptimizationCandidate] = Field(default_factory=list)
    tradeoffs: List[TradeoffAssessment] = Field(default_factory=list)
    sensitivity_analysis: List[SensitivityResult] = Field(default_factory=list)
    robustness: RobustnessStatus = Field(default=RobustnessStatus.ROBUST)
    evidence: List[OptimizationEvidence] = Field(default_factory=list)
    limitations: List[OptimizationLimitation] = Field(default_factory=list)
    explanation: OptimizationExplanation
    solver_metadata: Dict[str, Any] = Field(default_factory=dict)
    input_fingerprint: str = Field(..., min_length=64, max_length=64)
    created_at: str


# Backward-compatible alias
OptimizationSolution = OptimizationResult


# =============================================================================
# 11. API REQUEST & RESPONSE MODELS (Section 43)
# =============================================================================

class OptimizationAnalyzeRequest(BaseModel):
    """Request payload to analyze and solve an optimization problem."""
    model_config = ConfigDict(extra="ignore")

    tenant_id: str = Field(..., min_length=1, max_length=64)
    workspace_id: str = Field(default="workspace_default", max_length=64)
    plant_id: Optional[str] = Field(None, max_length=64)
    problem_name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(None, max_length=512)
    decision_scope: DecisionScope = Field(default=DecisionScope.PLANT)
    variables: List[DecisionVariable] = Field(default_factory=list)
    objectives: List[OptimizationObjective] = Field(default_factory=list)
    constraints: List[OptimizationConstraint] = Field(default_factory=list)
    context: Optional[OptimizationContext] = None
    multi_objective_method: MultiObjectiveMethod = Field(default=MultiObjectiveMethod.WEIGHTED_SUM)
    method: OptimizationSolverMethod = Field(default=OptimizationSolverMethod.EXHAUSTIVE_BOUNDED)
    assessment_timestamp: Optional[str] = None
    horizon: str = Field(default="P7D")


class OptimizationResultSummary(BaseModel):
    """Concise summary for list and history views."""
    model_config = ConfigDict(extra="ignore")

    optimization_id: str
    tenant_id: str
    workspace_id: str
    plant_id: Optional[str] = None
    problem_name: str
    assessment_timestamp: str
    optimality_status: str
    confidence: str
    is_feasible: bool
    candidate_count: int
    variable_count: int
    objective_count: int
    constraint_count: int
    input_fingerprint: str
    created_at: str


class OptimizationListResponse(BaseModel):
    """Paginated list response of optimization results."""
    model_config = ConfigDict(extra="ignore")

    items: List[OptimizationResultSummary]
    total_count: int


class OptimizationCandidatesResponse(BaseModel):
    """Candidates evaluated for an optimization run."""
    model_config = ConfigDict(extra="ignore")

    optimization_id: str
    candidates: List[OptimizationCandidate]


class OptimizationSensitivityResponse(BaseModel):
    """Sensitivity analysis for an optimization run."""
    model_config = ConfigDict(extra="ignore")

    optimization_id: str
    sensitivity_results: List[SensitivityResult]
    robustness: RobustnessStatus


class OptimizationEvidenceResponse(BaseModel):
    """Evidence chain supporting an optimization recommendation."""
    model_config = ConfigDict(extra="ignore")

    optimization_id: str
    evidence: List[OptimizationEvidence]


# =============================================================================
# 12. DETERMINISTIC FINGERPRINTING FUNCTION (Section 41)
# =============================================================================

def compute_optimization_fingerprint(
    tenant_id: str,
    workspace_id: str,
    plant_id: Optional[str],
    assessment_timestamp: str,
    horizon: str,
    decision_scope: str,
    variables: List[DecisionVariable],
    objectives: List[OptimizationObjective],
    constraints: List[OptimizationConstraint],
    context: Optional[OptimizationContext],
    multi_objective_method: str,
    method: str,
    method_version: str,
) -> str:
    """
    Computes a deterministic SHA-256 fingerprint over all material optimization inputs (Section 41).
    Orders variables, objectives, and constraints canonically.
    Equivalent problems produce identical fingerprints.
    Material changes alter the fingerprint.
    No UUIDs, memory addresses, or non-deterministic values are included.
    """
    canonical_variables = sorted(
        [
            {
                "var_id": v.variable_id,
                "name": v.name,
                "type": v.variable_type.value,
                "target": v.target_entity_id or "",
                "domain_type": v.domain.domain_type.value,
                "min": round(float(v.domain.min_value), 6) if v.domain.min_value is not None else None,
                "max": round(float(v.domain.max_value), 6) if v.domain.max_value is not None else None,
                "step": round(float(v.domain.step), 6) if v.domain.step is not None else None,
                "cats": sorted(v.domain.allowed_categories) if v.domain.allowed_categories else [],
                "unit": v.unit or "",
            }
            for v in variables
        ],
        key=lambda x: (x["var_id"], x["name"])
    )

    canonical_objectives = sorted(
        [
            {
                "obj_id": o.objective_id,
                "type": o.objective_type.value,
                "dir": o.direction.value,
                "weight": round(float(o.weight), 6),
                "unit": o.unit or "",
                "order": o.order,
                "norm": o.normalization or "",
            }
            for o in objectives
        ],
        key=lambda x: (x["obj_id"], x["type"])
    )

    canonical_constraints = sorted(
        [
            {
                "c_id": c.constraint_id,
                "type": c.constraint_type.value,
                "target": c.target_entity_id or "",
                "op": c.operator.value,
                "left": c.left_expression,
                "right": str(c.right_expression),
                "hard_or_soft": c.hard_or_soft.value,
                "unit": c.unit or "",
            }
            for c in constraints
        ],
        key=lambda x: (x["c_id"], x["left"])
    )

    canonical_context: Dict[str, Any] = {}
    if context:
        canonical_context = {
            "simulation_id": context.simulation_id or "",
            "forecast_reference": context.forecast_reference or "",
            "supplier_risk_reference": context.supplier_risk_reference or "",
            "maintenance_reference": context.maintenance_reference or "",
            "sla_reference": context.sla_reference or "",
            "financial_reference": context.financial_reference or "",
            "sustainability_reference": context.sustainability_reference or "",
            "digital_twin_reference": context.digital_twin_reference or "",
            "graph_reference": context.graph_reference or "",
            "baseline_metrics": {
                k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
                for k, v in sorted(context.baseline_metrics.items())
            },
            "context_parameters": {
                k: (round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
                for k, v in sorted(context.context_parameters.items())
            },
        }

    fingerprint_payload = {
        "tenant_id": tenant_id.strip(),
        "workspace_id": workspace_id.strip(),
        "plant_id": (plant_id or "").strip(),
        "assessment_timestamp": assessment_timestamp.strip(),
        "horizon": horizon.strip(),
        "decision_scope": decision_scope.strip(),
        "variables": canonical_variables,
        "objectives": canonical_objectives,
        "constraints": canonical_constraints,
        "context": canonical_context,
        "multi_objective_method": multi_objective_method.strip(),
        "method": method.strip(),
        "method_version": method_version.strip(),
    }

    serialized = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
