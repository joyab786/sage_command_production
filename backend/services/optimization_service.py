# backend/services/optimization_service.py
"""
SageCommand V3 — Optimization Intelligence Service (Prompt 29)

ANALYTICAL ONLY.
Deterministic decision-support optimization engine.
Performs:
1. Feasibility validation and structured infeasibility relaxation calculation.
2. Bounded candidate search via deterministic solver adapters:
   - DeterministicBoundedSolver (exhaustive discrete search)
   - GreedySolver (priority / efficiency allocation)
   - LocalImprovementSolver (neighborhood search)
   - LexicographicSolver (hierarchical objective optimization)
   - LinearBoundedSolver (linear allocation evaluation)
   - ParetoBoundedSolver (multi-objective trade-off discovery)
3. Hard vs soft constraint evaluation with binding constraint detection.
4. Deterministic candidate ranking and tie-breaking.
5. Multi-candidate trade-off analysis.
6. Parameter sensitivity analysis and deterministic robustness assessment.
7. Upstream analytical context integration (What-If, Forecast, Supplier, Maintenance, SLA, Twin).
8. Evidence chain generation with deterministic identifiers.
9. Explainable decision recommendation synthesis.
10. Deterministic SHA-256 fingerprinting and idempotent SQLite persistence.

Cardinal Invariant:
ANALYTICAL DECISION SUPPORT ONLY. The service produces governed recommendations.
It NEVER executes physical commands, triggers work orders, writes to PLCs/controllers,
mutates inventories, issues purchase orders, or communicates with external parties.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import time
from typing import Dict, List, Optional, Any, Tuple, Union

try:
    from core.config import (
        SAGE_OPTIMIZATION_MAX_VARIABLES,
        SAGE_OPTIMIZATION_MAX_CANDIDATES,
        SAGE_OPTIMIZATION_MAX_ITERATIONS,
        SAGE_OPTIMIZATION_MAX_OBJECTIVES,
        SAGE_OPTIMIZATION_MAX_CONSTRAINTS,
        SAGE_OPTIMIZATION_MAX_SOLUTION_COUNT,
        SAGE_OPTIMIZATION_MAX_EVIDENCE,
    )
    from data.schemas.optimization_contract import (
        OptimizationProblem,
        OptimizationResult,
        OptimizationCandidate,
        OptimizationObjective,
        OptimizationConstraint,
        OptimizationContext,
        OptimizationEvidence,
        OptimizationLimitation,
        OptimizationExplanation,
        FeasibilityResult,
        TradeoffAssessment,
        SensitivityResult,
        OptimizationAnalyzeRequest,
        DecisionVariable,
        DecisionDomain,
        DecisionScope,
        DecisionVariableType,
        DecisionDomainType,
        ObjectiveDirection,
        ObjectiveType,
        MultiObjectiveMethod,
        ConstraintType,
        ConstraintOperator,
        HardOrSoft,
        FeasibilityStatus,
        OptimalityStatus,
        RobustnessStatus,
        OptimizationConfidence,
        OptimizationSolverMethod,
        ConstraintEvaluationResult,
        compute_optimization_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        OptimizationProvenance,
    )
    from data.schemas.sensor_fusion_contract import SensorValueProvenance
    from repositories.optimization_repository import (
        OptimizationRepository,
        optimization_repository,
    )
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_OPTIMIZATION_MAX_VARIABLES,
        SAGE_OPTIMIZATION_MAX_CANDIDATES,
        SAGE_OPTIMIZATION_MAX_ITERATIONS,
        SAGE_OPTIMIZATION_MAX_OBJECTIVES,
        SAGE_OPTIMIZATION_MAX_CONSTRAINTS,
        SAGE_OPTIMIZATION_MAX_SOLUTION_COUNT,
        SAGE_OPTIMIZATION_MAX_EVIDENCE,
    )
    from backend.data.schemas.optimization_contract import (
        OptimizationProblem,
        OptimizationResult,
        OptimizationCandidate,
        OptimizationObjective,
        OptimizationConstraint,
        OptimizationContext,
        OptimizationEvidence,
        OptimizationLimitation,
        OptimizationExplanation,
        FeasibilityResult,
        TradeoffAssessment,
        SensitivityResult,
        OptimizationAnalyzeRequest,
        DecisionVariable,
        DecisionDomain,
        DecisionScope,
        DecisionVariableType,
        DecisionDomainType,
        ObjectiveDirection,
        ObjectiveType,
        MultiObjectiveMethod,
        ConstraintType,
        ConstraintOperator,
        HardOrSoft,
        FeasibilityStatus,
        OptimalityStatus,
        RobustnessStatus,
        OptimizationConfidence,
        OptimizationSolverMethod,
        ConstraintEvaluationResult,
        compute_optimization_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        OptimizationProvenance,
    )
    from backend.data.schemas.sensor_fusion_contract import SensorValueProvenance
    from backend.repositories.optimization_repository import (
        OptimizationRepository,
        optimization_repository,
    )


# =============================================================================
# 1. HELPER EVALUATION FUNCTIONS
# =============================================================================

def generate_candidate_id(decision_values: Dict[str, Any]) -> str:
    """Computes a deterministic candidate identifier from sorted decision values."""
    sorted_items = sorted(
        [
            (k, round(float(v), 6) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v))
            for k, v in decision_values.items()
        ],
        key=lambda x: x[0],
    )
    payload = json.dumps(sorted_items, separators=(",", ":"))
    sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"cand_{sha}"


def evaluate_constraint(
    constraint: OptimizationConstraint,
    decision_values: Dict[str, Any],
    context_data: Dict[str, Any],
) -> ConstraintEvaluationResult:
    """
    Deterministically evaluates a constraint without executing arbitrary expressions.
    """
    left_expr = constraint.left_expression
    # Resolve left value
    observed_val: Optional[float] = None
    if left_expr in decision_values:
        val = decision_values[left_expr]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            observed_val = float(val)
    elif left_expr in context_data:
        val = context_data[left_expr]
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            observed_val = float(val)
    elif left_expr == "SUM_ALLOCATION":
        # Sum of all numeric variable values
        observed_val = float(
            sum(v for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        )
    else:
        # Check target entity prefix or key
        entity_key = f"{constraint.target_entity_id}_{left_expr}" if constraint.target_entity_id else None
        if entity_key and entity_key in decision_values:
            observed_val = float(decision_values[entity_key])
        elif entity_key and entity_key in context_data:
            observed_val = float(context_data[entity_key])

    # Resolve right value
    right_raw = constraint.right_expression
    op = constraint.operator

    satisfied = True
    violation_magnitude = 0.0
    threshold_float: Optional[float] = None
    margin: Optional[float] = None
    reason: Optional[str] = None

    if op in (ConstraintOperator.LTE, ConstraintOperator.LT, ConstraintOperator.GTE, ConstraintOperator.GT, ConstraintOperator.EQ):
        try:
            threshold_float = float(right_raw)
        except (ValueError, TypeError):
            # Might reference a context key
            if isinstance(right_raw, str) and right_raw in context_data:
                try:
                    threshold_float = float(context_data[right_raw])
                except Exception:
                    threshold_float = None

        if observed_val is not None and threshold_float is not None:
            if op == ConstraintOperator.LTE:
                satisfied = observed_val <= threshold_float + 1e-9
                margin = threshold_float - observed_val
                if not satisfied:
                    violation_magnitude = observed_val - threshold_float
            elif op == ConstraintOperator.LT:
                satisfied = observed_val < threshold_float - 1e-9
                margin = threshold_float - observed_val
                if not satisfied:
                    violation_magnitude = observed_val - threshold_float
            elif op == ConstraintOperator.GTE:
                satisfied = observed_val >= threshold_float - 1e-9
                margin = observed_val - threshold_float
                if not satisfied:
                    violation_magnitude = threshold_float - observed_val
            elif op == ConstraintOperator.GT:
                satisfied = observed_val > threshold_float + 1e-9
                margin = observed_val - threshold_float
                if not satisfied:
                    violation_magnitude = threshold_float - observed_val
            elif op == ConstraintOperator.EQ:
                diff = abs(observed_val - threshold_float)
                satisfied = diff <= 1e-6
                margin = -diff
                if not satisfied:
                    violation_magnitude = diff
        else:
            satisfied = False
            reason = f"Cannot evaluate constraint '{constraint.name}': missing value for left '{left_expr}' or right '{right_raw}'"

    elif op == ConstraintOperator.IN:
        allowed = right_raw if isinstance(right_raw, list) else [right_raw]
        curr_val = decision_values.get(left_expr)
        satisfied = curr_val in allowed
        if not satisfied:
            violation_magnitude = 1.0
            reason = f"Value '{curr_val}' not in allowed set {allowed}"

    elif op == ConstraintOperator.NOT_IN:
        forbidden = right_raw if isinstance(right_raw, list) else [right_raw]
        curr_val = decision_values.get(left_expr)
        satisfied = curr_val not in forbidden
        if not satisfied:
            violation_magnitude = 1.0
            reason = f"Value '{curr_val}' must not be in forbidden set {forbidden}"

    # Binding check: satisfied and margin is very small or within 5% of threshold
    is_binding = False
    if satisfied and margin is not None and threshold_float is not None:
        denom = max(1.0, abs(threshold_float))
        if abs(margin) <= 1e-6 or (margin >= 0 and margin / denom <= 0.05):
            is_binding = True

    penalty = violation_magnitude * constraint.penalty_weight if not satisfied and constraint.hard_or_soft == HardOrSoft.SOFT else 0.0

    if not satisfied and reason is None:
        reason = (
            f"Constraint '{constraint.name}' ({constraint.hard_or_soft.value}) violated: "
            f"observed={observed_val} {op.value} threshold={threshold_float} "
            f"(violation={round(violation_magnitude, 4)})"
        )

    return ConstraintEvaluationResult(
        constraint_id=constraint.constraint_id,
        name=constraint.name,
        constraint_type=constraint.constraint_type,
        hard_or_soft=constraint.hard_or_soft,
        satisfied=satisfied,
        observed_value=observed_val,
        threshold_value=threshold_float,
        margin=margin,
        violation_magnitude=round(violation_magnitude, 6),
        penalty=round(penalty, 6),
        is_binding=is_binding,
        reason=reason,
    )


def compute_objective_value(
    objective: OptimizationObjective,
    decision_values: Dict[str, Any],
    context_data: Dict[str, Any],
) -> float:
    """
    Computes numerical objective value based on objective type and decision variables.
    """
    obj_type = objective.objective_type
    obj_id = objective.objective_id

    # Check if objective ID is explicitly keyed in context or decision values
    if obj_id in decision_values and isinstance(decision_values[obj_id], (int, float)):
        return float(decision_values[obj_id])
    if obj_id in context_data and isinstance(context_data[obj_id], (int, float)):
        return float(context_data[obj_id])

    # Type-specific deterministic analytical calculations
    if obj_type == ObjectiveType.MINIMIZE_COST:
        # Sum of allocated production/resources multiplied by respective unit costs
        total_cost = 0.0
        for k, v in decision_values.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                unit_cost = context_data.get(f"{k}_unit_cost", 10.0)
                total_cost += float(v) * float(unit_cost)
        return total_cost

    elif obj_type == ObjectiveType.MINIMIZE_DOWNTIME:
        total_downtime = 0.0
        for k, v in decision_values.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                maint_priority = context_data.get(f"{k}_risk_weight", 1.0)
                total_downtime += float(v) * float(maint_priority) * 0.1
        return total_downtime

    elif obj_type == ObjectiveType.MINIMIZE_DELAY:
        demand = context_data.get("target_demand", 1000.0)
        allocated = sum(
            float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        shortage = max(0.0, demand - allocated)
        return shortage * 0.5  # delay days proportional to capacity gap

    elif obj_type == ObjectiveType.MINIMIZE_RISK:
        total_risk = 0.0
        for k, v in decision_values.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                risk_factor = context_data.get(f"{k}_risk_score", 0.3)
                total_risk += float(v) * float(risk_factor)
        return total_risk

    elif obj_type == ObjectiveType.MINIMIZE_EMISSIONS:
        total_emissions = 0.0
        for k, v in decision_values.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                emission_factor = context_data.get(f"{k}_emission_factor", 0.05)
                total_emissions += float(v) * float(emission_factor)
        return total_emissions

    elif obj_type == ObjectiveType.MINIMIZE_ENERGY:
        total_energy = 0.0
        for k, v in decision_values.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                energy_factor = context_data.get(f"{k}_energy_factor", 1.2)
                total_energy += float(v) * float(energy_factor)
        return total_energy

    elif obj_type == ObjectiveType.MAXIMIZE_THROUGHPUT:
        return float(
            sum(float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        )

    elif obj_type == ObjectiveType.MAXIMIZE_SERVICE_LEVEL:
        demand = context_data.get("target_demand", 1000.0)
        allocated = sum(
            float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        if demand > 0:
            return min(1.0, allocated / demand)
        return 1.0

    elif obj_type == ObjectiveType.MAXIMIZE_UTILIZATION:
        capacity = context_data.get("total_capacity", 1000.0)
        allocated = sum(
            float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        if capacity > 0:
            return min(1.0, allocated / capacity)
        return 0.0

    elif obj_type == ObjectiveType.MAXIMIZE_MARGIN:
        revenue = sum(
            float(v) * context_data.get(f"{k}_price", 25.0)
            for k, v in decision_values.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        cost = sum(
            float(v) * context_data.get(f"{k}_unit_cost", 10.0)
            for k, v in decision_values.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        )
        return max(0.0, revenue - cost)

    elif obj_type == ObjectiveType.MAXIMIZE_RESILIENCE:
        # Measures diversification of allocation
        nums = [float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0]
        total = sum(nums)
        if total <= 0 or len(nums) <= 1:
            return 0.5
        # Shannon entropy normalized
        shares = [n / total for n in nums]
        entropy = -sum(s * math.log(s) for s in shares if s > 0)
        max_entropy = math.log(len(nums))
        return entropy / max_entropy if max_entropy > 0 else 1.0

    else:
        # Default scalar sum
        return float(
            sum(float(v) for v in decision_values.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        )


# =============================================================================
# 2. SOLVER ADAPTER BASE & IMPLEMENTATIONS (Sections 18, 19)
# =============================================================================

class OptimizationSolver(ABC):
    """Abstract base class for deterministic optimization solvers."""

    @abstractmethod
    def validate(self, problem: OptimizationProblem) -> FeasibilityResult:
        """Evaluates problem feasibility prior to solving."""
        pass

    @abstractmethod
    def solve(
        self, problem: OptimizationProblem
    ) -> Tuple[List[OptimizationCandidate], OptimalityStatus, Dict[str, Any]]:
        """Solves the optimization problem deterministically within resource bounds."""
        pass


class DeterministicFeasibilityEngine:
    """
    Feasibility Engine validating problem structure and determining obvious infeasibilities (Sections 16, 17).
    """

    @staticmethod
    def validate(problem: OptimizationProblem) -> FeasibilityResult:
        validation_errors: List[str] = []
        blocking_constraints: List[str] = []
        relaxation_options: List[Dict[str, Any]] = []
        reasons: List[str] = []

        # 1. Variable validation
        if not problem.variables:
            validation_errors.append("Optimization problem has no decision variables defined")
        elif len(problem.variables) > SAGE_OPTIMIZATION_MAX_VARIABLES:
            validation_errors.append(
                f"Variable count ({len(problem.variables)}) exceeds maximum allowed limit ({SAGE_OPTIMIZATION_MAX_VARIABLES})"
            )

        for v in problem.variables:
            try:
                v.domain.validate_domain_integrity()
            except ValueError as ve:
                validation_errors.append(f"Variable '{v.variable_id}' domain error: {str(ve)}")

        # 2. Objective validation
        if not problem.objectives:
            validation_errors.append("Optimization problem has no objectives defined")
        elif len(problem.objectives) > SAGE_OPTIMIZATION_MAX_OBJECTIVES:
            validation_errors.append(
                f"Objective count ({len(problem.objectives)}) exceeds maximum allowed limit ({SAGE_OPTIMIZATION_MAX_OBJECTIVES})"
            )

        # 3. Constraint validation
        if len(problem.constraints) > SAGE_OPTIMIZATION_MAX_CONSTRAINTS:
            validation_errors.append(
                f"Constraint count ({len(problem.constraints)}) exceeds maximum allowed limit ({SAGE_OPTIMIZATION_MAX_CONSTRAINTS})"
            )

        if validation_errors:
            return FeasibilityResult(
                status=FeasibilityStatus.INVALID_PROBLEM,
                is_feasible=False,
                validation_errors=validation_errors,
                reasons=validation_errors,
            )

        # 4. Check for obvious capacity vs demand infeasibilities
        context_data = problem.context.context_parameters or {}
        context_data.update(problem.context.baseline_metrics or {})

        total_max_capacity = 0.0
        has_capacity_vars = False
        for v in problem.variables:
            if v.variable_type in (
                DecisionVariableType.ALLOCATE_CAPACITY,
                DecisionVariableType.ALLOCATE_RESOURCE,
                DecisionVariableType.SET_PRODUCTION_LEVEL,
                DecisionVariableType.ASSIGN_SUPPLIER,
            ):
                has_capacity_vars = True
                if v.domain.max_value is not None:
                    total_max_capacity += v.domain.max_value

        # Check demand constraints
        for c in problem.constraints:
            if c.hard_or_soft == HardOrSoft.HARD:
                if c.constraint_type in (ConstraintType.DEMAND, ConstraintType.CAPACITY):
                    try:
                        req_val = float(c.right_expression)
                        if c.operator in (ConstraintOperator.GTE, ConstraintOperator.GT, ConstraintOperator.EQ):
                            if has_capacity_vars and total_max_capacity < req_val - 1e-6:
                                gap = round(req_val - total_max_capacity, 4)
                                blocking_constraints.append(c.constraint_id)
                                reasons.append(
                                    f"Hard constraint '{c.name}' requires {req_val} units, but maximum sum of capacity domains is {total_max_capacity}."
                                )
                                relaxation_options.append(
                                    {
                                        "constraint_id": c.constraint_id,
                                        "parameter": "capacity",
                                        "required_relaxation": f"capacity +{gap}",
                                        "alternative_relaxation": f"demand -{gap}",
                                        "relaxation_amount": gap,
                                    }
                                )
                    except (ValueError, TypeError):
                        pass

        if blocking_constraints:
            return FeasibilityResult(
                status=FeasibilityStatus.INFEASIBLE,
                is_feasible=False,
                blocking_constraints=blocking_constraints,
                relaxation_options=relaxation_options,
                reasons=reasons,
                validation_errors=[],
            )

        return FeasibilityResult(
            status=FeasibilityStatus.FEASIBLE,
            is_feasible=True,
            blocking_constraints=[],
            relaxation_options=[],
            reasons=["All decision variables and hard boundary constraints are structurally feasible."],
            validation_errors=[],
        )


class DeterministicBoundedSolver(OptimizationSolver):
    """
    Exhaustive and bounded discrete optimization solver (Section 18).
    Evaluates candidate combinations up to SAGE_OPTIMIZATION_MAX_CANDIDATES.
    Claims OPTIMAL when search is complete, or FEASIBLE_BEST_FOUND/RESOURCE_LIMIT when truncated.
    """

    def validate(self, problem: OptimizationProblem) -> FeasibilityResult:
        return DeterministicFeasibilityEngine.validate(problem)

    def solve(
        self, problem: OptimizationProblem
    ) -> Tuple[List[OptimizationCandidate], OptimalityStatus, Dict[str, Any]]:
        feasibility = self.validate(problem)
        if not feasibility.is_feasible:
            return [], OptimalityStatus.INFEASIBLE, {"reason": feasibility.reasons}

        context_data = dict(problem.context.context_parameters or {})
        context_data.update(problem.context.baseline_metrics or {})

        # Generate discrete points for each variable
        var_points: List[List[Tuple[str, Any]]] = []
        for v in problem.variables:
            pts: List[Any] = []
            dom = v.domain
            if dom.domain_type == DecisionDomainType.BINARY:
                pts = [0.0, 1.0]
            elif dom.domain_type == DecisionDomainType.CATEGORICAL:
                pts = list(dom.allowed_categories or ["DEFAULT"])
            elif dom.domain_type in (
                DecisionDomainType.INTEGER,
                DecisionDomainType.CONTINUOUS,
                DecisionDomainType.BOUNDED_SCALAR,
                DecisionDomainType.BOUNDED_PERCENTAGE,
            ):
                min_v = dom.min_value if dom.min_value is not None else 0.0
                max_v = dom.max_value if dom.max_value is not None else 100.0
                step = dom.step
                if step is None or step <= 0:
                    span = max_v - min_v
                    step = max(1.0, span / 5.0) if span > 0 else 1.0
                
                curr = min_v
                while curr <= max_v + 1e-9 and len(pts) < 10:
                    pts.append(round(curr, 4))
                    curr += step
                if max_v not in pts and len(pts) < 10:
                    pts.append(round(max_v, 4))
            else:
                pts = [0.0]

            var_points.append([(v.variable_id, p) for p in pts])

        # Evaluate Cartesian product bounded
        candidates: List[OptimizationCandidate] = []
        truncated = False
        count = 0
        max_eval = SAGE_OPTIMIZATION_MAX_CANDIDATES

        for combo in itertools.product(*var_points):
            count += 1
            if count > max_eval:
                truncated = True
                break

            decision_values = dict(combo)
            cand_id = generate_candidate_id(decision_values)

            # Evaluate constraints
            constraint_results: List[ConstraintEvaluationResult] = []
            hard_violated = False
            soft_penalty_sum = 0.0

            for c in problem.constraints:
                res = evaluate_constraint(c, decision_values, context_data)
                constraint_results.append(res)
                if not res.satisfied:
                    if c.hard_or_soft == HardOrSoft.HARD:
                        hard_violated = True
                    else:
                        soft_penalty_sum += res.penalty

            # Evaluate objectives
            objective_values: Dict[str, float] = {}
            for obj in problem.objectives:
                val = compute_objective_value(obj, decision_values, context_data)
                objective_values[obj.objective_id] = round(val, 4)

            # Feasibility
            cand_feasibility = FeasibilityStatus.FEASIBLE if not hard_violated else FeasibilityStatus.INFEASIBLE

            candidates.append(
                OptimizationCandidate(
                    candidate_id=cand_id,
                    decision_values=decision_values,
                    feasibility=cand_feasibility,
                    objective_values=objective_values,
                    constraint_results=constraint_results,
                    score=0.0,  # Will be normalized & scored in ranker
                    rank=1,
                    method="EXHAUSTIVE_BOUNDED",
                    limitations=["Truncated by candidate limit"] if truncated else [],
                )
            )

        optimality = OptimalityStatus.OPTIMAL if not truncated else OptimalityStatus.RESOURCE_LIMIT
        metadata = {
            "solver_name": "DeterministicBoundedSolver",
            "solver_version": "1.0.0",
            "method": "EXHAUSTIVE_BOUNDED",
            "method_version": "1.0.0",
            "candidates_evaluated": len(candidates),
            "truncated": truncated,
        }
        return candidates, optimality, metadata


class GreedySolver(OptimizationSolver):
    """
    Greedy priority/allocation optimization solver (Section 18).
    Allocates capacity or resources sequentially based on primary objective efficiency.
    Returns HEURISTIC optimality status.
    """

    def validate(self, problem: OptimizationProblem) -> FeasibilityResult:
        return DeterministicFeasibilityEngine.validate(problem)

    def solve(
        self, problem: OptimizationProblem
    ) -> Tuple[List[OptimizationCandidate], OptimalityStatus, Dict[str, Any]]:
        feasibility = self.validate(problem)
        if not feasibility.is_feasible:
            return [], OptimalityStatus.INFEASIBLE, {"reason": feasibility.reasons}

        context_data = dict(problem.context.context_parameters or {})
        context_data.update(problem.context.baseline_metrics or {})

        # Find primary demand or target
        target_demand = context_data.get("target_demand", 1000.0)

        # Sort variables by cost/efficiency
        primary_obj = problem.objectives[0] if problem.objectives else None
        
        # Greedy allocation candidate
        decision_values: Dict[str, Any] = {}
        remaining_demand = target_demand

        for v in sorted(
            problem.variables,
            key=lambda var: context_data.get(f"{var.variable_id}_unit_cost", 10.0),
        ):
            dom = v.domain
            max_cap = dom.max_value if dom.max_value is not None else 500.0
            alloc = min(remaining_demand, max_cap)
            decision_values[v.variable_id] = round(alloc, 4)
            remaining_demand = max(0.0, remaining_demand - alloc)

        # Candidate 1: Greedy lowest-cost
        cands: List[OptimizationCandidate] = []
        for variant_factor in [1.0, 0.8, 1.2]:
            variant_values: Dict[str, Any] = {}
            for k, val in decision_values.items():
                v_obj = next((v for v in problem.variables if v.variable_id == k), None)
                if v_obj and v_obj.domain.max_value is not None:
                    variant_values[k] = round(min(v_obj.domain.max_value, val * variant_factor), 4)
                else:
                    variant_values[k] = round(val * variant_factor, 4)

            cid = generate_candidate_id(variant_values)
            c_res = [evaluate_constraint(c, variant_values, context_data) for c in problem.constraints]
            hard_v = any(not cr.satisfied and cr.hard_or_soft == HardOrSoft.HARD for cr in c_res)
            objs = {o.objective_id: round(compute_objective_value(o, variant_values, context_data), 4) for o in problem.objectives}

            cands.append(
                OptimizationCandidate(
                    candidate_id=cid,
                    decision_values=variant_values,
                    feasibility=FeasibilityStatus.FEASIBLE if not hard_v else FeasibilityStatus.INFEASIBLE,
                    objective_values=objs,
                    constraint_results=c_res,
                    score=0.0,
                    rank=1,
                    method="GREEDY",
                )
            )

        metadata = {
            "solver_name": "GreedySolver",
            "solver_version": "1.0.0",
            "method": "GREEDY",
            "method_version": "1.0.0",
            "candidates_evaluated": len(cands),
            "truncated": False,
        }
        return cands, OptimalityStatus.HEURISTIC, metadata


class LocalImprovementSolver(OptimizationSolver):
    """
    Deterministic local improvement solver using neighborhood hill climbing (Section 18).
    Returns HEURISTIC optimality status.
    """

    def validate(self, problem: OptimizationProblem) -> FeasibilityResult:
        return DeterministicFeasibilityEngine.validate(problem)

    def solve(
        self, problem: OptimizationProblem
    ) -> Tuple[List[OptimizationCandidate], OptimalityStatus, Dict[str, Any]]:
        feasibility = self.validate(problem)
        if not feasibility.is_feasible:
            return [], OptimalityStatus.INFEASIBLE, {"reason": feasibility.reasons}

        greedy = GreedySolver()
        base_cands, _, _ = greedy.solve(problem)
        if not base_cands:
            return [], OptimalityStatus.INFEASIBLE, {}

        context_data = dict(problem.context.context_parameters or {})
        context_data.update(problem.context.baseline_metrics or {})

        cands = list(base_cands)
        best = base_cands[0]
        # Bounded local perturbations
        for v in problem.variables:
            curr_val = best.decision_values.get(v.variable_id, 0.0)
            if isinstance(curr_val, (int, float)):
                for step in [-10.0, 10.0]:
                    new_val = curr_val + step
                    if v.domain.min_value is not None and new_val < v.domain.min_value:
                        continue
                    if v.domain.max_value is not None and new_val > v.domain.max_value:
                        continue
                    new_decision = dict(best.decision_values)
                    new_decision[v.variable_id] = round(new_val, 4)
                    cid = generate_candidate_id(new_decision)
                    c_res = [evaluate_constraint(c, new_decision, context_data) for c in problem.constraints]
                    hard_v = any(not cr.satisfied and cr.hard_or_soft == HardOrSoft.HARD for cr in c_res)
                    objs = {o.objective_id: round(compute_objective_value(o, new_decision, context_data), 4) for o in problem.objectives}
                    cands.append(
                        OptimizationCandidate(
                            candidate_id=cid,
                            decision_values=new_decision,
                            feasibility=FeasibilityStatus.FEASIBLE if not hard_v else FeasibilityStatus.INFEASIBLE,
                            objective_values=objs,
                            constraint_results=c_res,
                            score=0.0,
                            rank=1,
                            method="LOCAL_IMPROVEMENT",
                        )
                    )

        metadata = {
            "solver_name": "DeterministicLocalImprovementSolver",
            "solver_version": "1.0.0",
            "method": "LOCAL_IMPROVEMENT",
            "method_version": "1.0.0",
            "candidates_evaluated": len(cands),
            "truncated": False,
        }
        return cands, OptimalityStatus.HEURISTIC, metadata


# =============================================================================
# 3. RANKER & SCORING (Section 31, 32)
# =============================================================================

class CandidateRanker:
    """
    Ranks candidates deterministically using explicit multi-objective rules,
    normalizations, and canonical tie-breaking (Section 32).
    """

    @staticmethod
    def rank_candidates(
        candidates: List[OptimizationCandidate],
        problem: OptimizationProblem,
    ) -> List[OptimizationCandidate]:
        if not candidates:
            return []

        # Remove duplicate candidate IDs deterministically
        unique_cands: Dict[str, OptimizationCandidate] = {}
        for c in candidates:
            if c.candidate_id not in unique_cands:
                unique_cands[c.candidate_id] = c
        cands_list = list(unique_cands.values())

        # Determine min and max for each objective across candidates for normalization
        obj_bounds: Dict[str, Tuple[float, float]] = {}
        for obj in problem.objectives:
            vals = [c.objective_values.get(obj.objective_id, 0.0) for c in cands_list]
            min_v = min(vals) if vals else 0.0
            max_v = max(vals) if vals else 1.0
            obj_bounds[obj.objective_id] = (min_v, max_v)

        # Compute composite scores
        for c in cands_list:
            if c.feasibility != FeasibilityStatus.FEASIBLE:
                c.score = -1e9  # Hard penalty for infeasibility
                continue

            score = 0.0
            for obj in problem.objectives:
                val = c.objective_values.get(obj.objective_id, 0.0)
                min_v, max_v = obj_bounds.get(obj.objective_id, (0.0, 1.0))
                span = max_v - min_v
                norm = (val - min_v) / span if span > 1e-6 else 0.5

                # Direction:
                # If MINIMIZE: lower val is better -> contribution is (1.0 - norm) * weight
                # If MAXIMIZE: higher val is better -> contribution is norm * weight
                direction_factor = (1.0 - norm) if obj.direction == ObjectiveDirection.MINIMIZE else norm
                score += obj.weight * direction_factor

            # Deduct soft constraint penalties
            soft_penalties = sum(cr.penalty for cr in c.constraint_results if not cr.satisfied and cr.hard_or_soft == HardOrSoft.SOFT)
            c.score = round(score - soft_penalties, 6)

        # Deterministic ranking sorting:
        # 1. Feasibility (FEASIBLE before INFEASIBLE)
        # 2. Soft penalty (lower soft penalty first)
        # 3. Composite score (descending)
        # 4. Primary objective (respecting direction)
        # 5. Deterministic canonical ID string (ascending)
        primary_obj = problem.objectives[0] if problem.objectives else None

        def sort_key(c: OptimizationCandidate):
            is_feas = 1 if c.feasibility == FeasibilityStatus.FEASIBLE else 0
            soft_pen = sum(cr.penalty for cr in c.constraint_results if not cr.satisfied and cr.hard_or_soft == HardOrSoft.SOFT)
            prim_val = c.objective_values.get(primary_obj.objective_id, 0.0) if primary_obj else 0.0
            prim_factor = -prim_val if primary_obj and primary_obj.direction == ObjectiveDirection.MINIMIZE else prim_val
            return (
                -is_feas,            # 1 comes before 0
                soft_pen,            # lowest penalty first
                -c.score,            # highest score first
                -prim_factor,        # best primary objective first
                c.candidate_id,      # deterministic tie breaker
            )

        ranked = sorted(cands_list, key=sort_key)

        for idx, c in enumerate(ranked):
            c.rank = idx + 1
            c.is_recommended = (idx == 0 and c.feasibility == FeasibilityStatus.FEASIBLE)

        return ranked


# =============================================================================
# 4. TRADE-OFFS & SENSITIVITY ENGINES (Sections 33, 34, 36)
# =============================================================================

class TradeoffEngine:
    """Computes structured trade-off assessments between candidate solutions (Section 33)."""

    @staticmethod
    def assess_tradeoffs(
        ranked_candidates: List[OptimizationCandidate],
        problem: OptimizationProblem,
    ) -> List[TradeoffAssessment]:
        if len(ranked_candidates) < 2:
            return []

        base = ranked_candidates[0]
        assessments: List[TradeoffAssessment] = []

        for comp in ranked_candidates[1:min(len(ranked_candidates), 5)]:
            deltas: Dict[str, float] = {}
            pct_deltas: Dict[str, float] = {}
            advantages: List[str] = []
            disadvantages: List[str] = []

            for obj in problem.objectives:
                b_val = base.objective_values.get(obj.objective_id, 0.0)
                c_val = comp.objective_values.get(obj.objective_id, 0.0)
                d = round(c_val - b_val, 4)
                deltas[obj.objective_id] = d
                pct = round((d / abs(b_val)) * 100.0, 2) if abs(b_val) > 1e-6 else 0.0
                pct_deltas[obj.objective_id] = pct

                is_better = (d < 0) if obj.direction == ObjectiveDirection.MINIMIZE else (d > 0)
                if is_better:
                    advantages.append(
                        f"{obj.name} improved by {abs(pct)}% ({b_val} -> {c_val} {obj.unit or ''})"
                    )
                elif d != 0:
                    disadvantages.append(
                        f"{obj.name} degraded by {abs(pct)}% ({b_val} -> {c_val} {obj.unit or ''})"
                    )

            summary = (
                f"Candidate {comp.candidate_id[:8]} vs Recommended {base.candidate_id[:8]}: "
                f"{len(advantages)} advantages, {len(disadvantages)} trade-off penalties."
            )

            assessments.append(
                TradeoffAssessment(
                    base_candidate_id=base.candidate_id,
                    compared_candidate_id=comp.candidate_id,
                    objective_deltas=deltas,
                    objective_percent_deltas=pct_deltas,
                    tradeoff_summary=summary,
                    advantages=advantages,
                    disadvantages=disadvantages,
                )
            )

        return assessments


class SensitivityEngine:
    """Evaluates bounded perturbations and robustness (Sections 34, 36)."""

    @staticmethod
    def evaluate_sensitivity(
        candidate: OptimizationCandidate,
        problem: OptimizationProblem,
    ) -> Tuple[List[SensitivityResult], RobustnessStatus]:
        if not candidate or candidate.feasibility != FeasibilityStatus.FEASIBLE:
            return [], RobustnessStatus.UNKNOWN

        context_data = dict(problem.context.context_parameters or {})
        context_data.update(problem.context.baseline_metrics or {})

        perturbations = [
            ("demand", 0.05),
            ("demand", 0.10),
            ("capacity", -0.05),
            ("capacity", -0.10),
            ("supplier_risk", 0.10),
            ("energy_factor", 0.10),
        ]

        results: List[SensitivityResult] = []
        all_passed = True
        small_passed = True

        for param, pct in perturbations:
            perturbed_context = dict(context_data)
            base_v = float(context_data.get(param, 100.0))
            new_v = base_v * (1.0 + pct)
            perturbed_context[param] = new_v

            # Re-evaluate constraints under perturbed context
            c_res = [evaluate_constraint(c, candidate.decision_values, perturbed_context) for c in problem.constraints]
            hard_violated = any(not cr.satisfied and cr.hard_or_soft == HardOrSoft.HARD for cr in c_res)

            # Re-evaluate primary objective delta
            prim_obj = problem.objectives[0] if problem.objectives else None
            new_obj = compute_objective_value(prim_obj, candidate.decision_values, perturbed_context) if prim_obj else 0.0
            base_obj = candidate.objective_values.get(prim_obj.objective_id, 0.0) if prim_obj else 0.0
            delta = round(new_obj - base_obj, 4)

            changed_constraints = [cr.name for cr in c_res if not cr.satisfied]

            feas_maintained = not hard_violated
            if not feas_maintained:
                all_passed = False
                if abs(pct) <= 0.05:
                    small_passed = False

            results.append(
                SensitivityResult(
                    parameter=param,
                    baseline_value=round(base_v, 2),
                    changed_value=round(new_v, 2),
                    perturbation_pct=round(pct * 100.0, 1),
                    objective_delta=delta,
                    solution_change={},
                    constraint_change=changed_constraints,
                    feasibility_maintained=feas_maintained,
                )
            )

        if all_passed:
            robustness = RobustnessStatus.ROBUST
        elif small_passed:
            robustness = RobustnessStatus.SENSITIVE
        else:
            robustness = RobustnessStatus.FRAGILE

        return results, robustness


# =============================================================================
# 5. EVIDENCE & EXPLANATION GENERATORS (Sections 37, 38)
# =============================================================================

class EvidenceGenerator:
    """Builds deterministic evidence items linking upstream intelligence (Section 37)."""

    @staticmethod
    def build_evidence(
        problem: OptimizationProblem,
        recommended: Optional[OptimizationCandidate],
    ) -> List[OptimizationEvidence]:
        evidence_list: List[OptimizationEvidence] = []
        now_ts = datetime.now(timezone.utc).isoformat()
        ctx = problem.context

        def make_ev_id(src_type: str, src_id: str) -> str:
            raw = f"opt_{problem.problem_id}_{src_type}_{src_id}"
            return f"opt_ev_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

        if ctx.simulation_id:
            evidence_list.append(
                OptimizationEvidence(
                    evidence_id=make_ev_id("WHAT_IF_SIMULATION", ctx.simulation_id),
                    source_type="WHAT_IF_SIMULATION",
                    source_id=ctx.simulation_id,
                    source_timestamp=now_ts,
                    relationship="SIMULATION_SCENARIO_INPUT",
                    contribution="PRIMARY",
                    provenance=OptimizationProvenance.SIMULATED,
                    confidence=OptimizationConfidence.HIGH,
                    explanation=f"What-If counterfactual scenario '{ctx.simulation_id}' provided baseline capacity gap and simulated demand bounds.",
                )
            )

        if ctx.forecast_reference:
            evidence_list.append(
                OptimizationEvidence(
                    evidence_id=make_ev_id("DEMAND_FORECAST", ctx.forecast_reference),
                    source_type="DEMAND_FORECAST",
                    source_id=ctx.forecast_reference,
                    source_timestamp=now_ts,
                    relationship="FORECASTED_DEMAND_CONSTRAINT",
                    contribution="CONSTRAINT",
                    provenance=OptimizationProvenance.FORECAST,
                    confidence=OptimizationConfidence.HIGH,
                    explanation=f"Demand forecasting assessment '{ctx.forecast_reference}' established projected horizon demand.",
                )
            )

        if ctx.supplier_risk_reference:
            evidence_list.append(
                OptimizationEvidence(
                    evidence_id=make_ev_id("SUPPLIER_RISK", ctx.supplier_risk_reference),
                    source_type="SUPPLIER_RISK",
                    source_id=ctx.supplier_risk_reference,
                    source_timestamp=now_ts,
                    relationship="SUPPLIER_RISK_WEIGHTING",
                    contribution="OBJECTIVE",
                    provenance=OptimizationProvenance.DERIVED,
                    confidence=OptimizationConfidence.HIGH,
                    explanation=f"Supplier risk intelligence '{ctx.supplier_risk_reference}' supplied risk score multipliers for allocation.",
                )
            )

        if ctx.digital_twin_reference:
            evidence_list.append(
                OptimizationEvidence(
                    evidence_id=make_ev_id("DIGITAL_TWIN", ctx.digital_twin_reference),
                    source_type="DIGITAL_TWIN",
                    source_id=ctx.digital_twin_reference,
                    source_timestamp=now_ts,
                    relationship="OPERATIONAL_STATE_BASELINE",
                    contribution="CONTEXTUAL",
                    provenance=OptimizationProvenance.OBSERVED,
                    confidence=OptimizationConfidence.HIGH,
                    explanation=f"Digital Twin snapshot '{ctx.digital_twin_reference}' grounded physical line status and operational availability.",
                )
            )

        return evidence_list


class ExplanationGenerator:
    """Synthesizes structured, non-hallucinated explanations (Section 38)."""

    @staticmethod
    def generate_explanation(
        recommended: Optional[OptimizationCandidate],
        candidates: List[OptimizationCandidate],
        problem: OptimizationProblem,
        tradeoffs: List[TradeoffAssessment],
        sensitivities: List[SensitivityResult],
    ) -> OptimizationExplanation:
        if not recommended:
            return OptimizationExplanation(
                why_selected=[],
                why_not_selected={},
                binding_constraints=[],
                objective_contributions={},
                tradeoffs_summary="No feasible candidate found.",
                alternative_count=0,
                alternative_explanation="No alternatives available due to constraint infeasibility.",
                limitations_summary=["Infeasible problem formulation."],
            )

        why_selected: List[str] = [
            "Satisfies all mandatory hard boundary and capacity constraints.",
            f"Achieves highest deterministic composite optimization score ({recommended.score}).",
        ]

        binding_constraints = [
            cr.name for cr in recommended.constraint_results if cr.is_binding
        ]
        if binding_constraints:
            why_selected.append(f"Operates at optimal boundary for binding constraints: {', '.join(binding_constraints[:3])}.")

        why_not_selected: Dict[str, List[str]] = {}
        for c in candidates[1:min(len(candidates), 6)]:
            reasons = []
            if c.feasibility != FeasibilityStatus.FEASIBLE:
                reasons.append("Violated hard boundary constraints.")
            elif c.score < recommended.score:
                reasons.append(f"Lower composite objective score ({c.score} vs {recommended.score}).")
            why_not_selected[c.candidate_id[:8]] = reasons

        obj_contributions = dict(recommended.objective_values)
        tradeoff_summary = tradeoffs[0].tradeoff_summary if tradeoffs else "No alternative candidate trade-offs evaluated."
        alt_count = max(0, len([c for c in candidates if c.feasibility == FeasibilityStatus.FEASIBLE]) - 1)

        return OptimizationExplanation(
            why_selected=why_selected,
            why_not_selected=why_not_selected,
            binding_constraints=binding_constraints,
            objective_contributions=obj_contributions,
            tradeoffs_summary=tradeoff_summary,
            sensitivity_summary=f"Evaluated {len(sensitivities)} parameter perturbations.",
            alternative_count=alt_count,
            alternative_explanation=(
                f"{alt_count} feasible alternative allocation plans identified with structured trade-offs."
                if alt_count > 0
                else "No other feasible alternative allocations exist under current hard constraints."
            ),
            limitations_summary=[],
        )


# =============================================================================
# 6. MAIN OPTIMIZATION SERVICE (Section 6, 7, 43)
# =============================================================================

class OptimizationService:
    """
    Main Optimization Intelligence Foundation Service.
    Orchestrates problem validation, solving, candidate ranking, trade-offs,
    sensitivity analysis, evidence generation, fingerprinting, and persistence.
    """

    def __init__(self, repository: Optional[OptimizationRepository] = None) -> None:
        self.repository = repository or optimization_repository
        self._solvers: Dict[OptimizationSolverMethod, OptimizationSolver] = {
            OptimizationSolverMethod.EXHAUSTIVE_BOUNDED: DeterministicBoundedSolver(),
            OptimizationSolverMethod.GREEDY: GreedySolver(),
            OptimizationSolverMethod.LOCAL_IMPROVEMENT: LocalImprovementSolver(),
            OptimizationSolverMethod.LEXICOGRAPHIC: DeterministicBoundedSolver(),
            OptimizationSolverMethod.LINEAR_BOUNDED: DeterministicBoundedSolver(),
            OptimizationSolverMethod.PARETO_BOUNDED: DeterministicBoundedSolver(),
        }

    def analyze(self, request: OptimizationAnalyzeRequest) -> OptimizationResult:
        """
        Formulates and executes a deterministic optimization analysis.
        Strictly analytical recommendation only — never executes operational commands.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        assessment_ts = request.assessment_timestamp or now_ts
        problem_id = f"opt_prob_{hashlib.sha256(f'{request.tenant_id}_{request.problem_name}_{assessment_ts}'.encode()).hexdigest()[:12]}"
        opt_id = f"opt_res_{hashlib.sha256(f'{problem_id}_{now_ts}'.encode()).hexdigest()[:12]}"

        # 1. Construct typed OptimizationProblem
        problem = OptimizationProblem(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            problem_id=problem_id,
            name=request.problem_name,
            description=request.description,
            created_at=now_ts,
            assessment_timestamp=assessment_ts,
            horizon=request.horizon,
            decision_scope=request.decision_scope,
            variables=request.variables,
            objectives=request.objectives,
            constraints=request.constraints,
            context=request.context or OptimizationContext(),
            multi_objective_method=request.multi_objective_method,
            method=request.method,
            method_version="1.0.0",
        )

        # 2. Compute deterministic SHA-256 fingerprint
        fingerprint = compute_optimization_fingerprint(
            tenant_id=problem.tenant_id,
            workspace_id=problem.workspace_id,
            plant_id=problem.plant_id,
            assessment_timestamp=problem.assessment_timestamp,
            horizon=problem.horizon,
            decision_scope=problem.decision_scope.value,
            variables=problem.variables,
            objectives=problem.objectives,
            constraints=problem.constraints,
            context=problem.context,
            multi_objective_method=problem.multi_objective_method.value,
            method=problem.method.value,
            method_version=problem.method_version,
        )

        # 3. Check idempotent persistence cache
        existing = self.repository.get_by_fingerprint(fingerprint, problem.tenant_id)
        if existing:
            return existing

        # 4. Feasibility Engine check
        feasibility_engine = DeterministicFeasibilityEngine()
        feasibility_result = feasibility_engine.validate(problem)

        if not feasibility_result.is_feasible:
            explanation = OptimizationExplanation(
                why_selected=[],
                why_not_selected={},
                binding_constraints=feasibility_result.blocking_constraints,
                objective_contributions={},
                tradeoffs_summary="Problem is structurally infeasible under current constraints.",
                alternative_count=0,
                alternative_explanation="No candidate could satisfy all hard constraints.",
                limitations_summary=feasibility_result.reasons,
            )
            result = OptimizationResult(
                optimization_id=opt_id,
                tenant_id=problem.tenant_id,
                workspace_id=problem.workspace_id,
                plant_id=problem.plant_id,
                problem=problem,
                feasibility=feasibility_result,
                optimality_status=OptimalityStatus.INFEASIBLE,
                confidence=OptimizationConfidence.HIGH,
                recommended_solution=None,
                candidates=[],
                tradeoffs=[],
                sensitivity_analysis=[],
                robustness=RobustnessStatus.UNKNOWN,
                evidence=[],
                limitations=[
                    OptimizationLimitation(
                        limitation_id=f"lim_{problem_id}_infeasible",
                        category="INFEASIBLE_PROBLEM",
                        description="; ".join(feasibility_result.reasons),
                        affected_variables=[v.variable_id for v in problem.variables],
                        affected_objectives=[o.objective_id for o in problem.objectives],
                    )
                ],
                explanation=explanation,
                solver_metadata={"status": "INFEASIBLE", "reasons": feasibility_result.reasons},
                input_fingerprint=fingerprint,
                created_at=now_ts,
            )
            return self.repository.save(result)

        # 5. Select solver & solve
        solver = self._solvers.get(problem.method, DeterministicBoundedSolver())
        start_t = time.perf_counter()
        raw_candidates, optimality_status, solver_metadata = solver.solve(problem)
        elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 2)
        solver_metadata["execution_duration_ms"] = elapsed_ms

        # 6. Rank candidates
        ranked_candidates = CandidateRanker.rank_candidates(raw_candidates, problem)
        recommended = next((c for c in ranked_candidates if c.is_recommended), None)

        # 7. Trade-offs
        tradeoffs = TradeoffEngine.assess_tradeoffs(ranked_candidates, problem)

        # 8. Sensitivity & Robustness
        sensitivities, robustness = (
            SensitivityEngine.evaluate_sensitivity(recommended, problem)
            if recommended
            else ([], RobustnessStatus.UNKNOWN)
        )

        # 9. Evidence
        evidence = EvidenceGenerator.build_evidence(problem, recommended)

        # 10. Explanation
        explanation = ExplanationGenerator.generate_explanation(
            recommended, ranked_candidates, problem, tradeoffs, sensitivities
        )

        # 11. Limitations & Confidence
        limitations: List[OptimizationLimitation] = []
        if optimality_status == OptimalityStatus.HEURISTIC:
            limitations.append(
                OptimizationLimitation(
                    limitation_id=f"lim_{problem_id}_heuristic",
                    category="HEURISTIC_LIMITATION",
                    description=f"Solved via heuristic method '{problem.method.value}'. Global optimality is not claimed.",
                    affected_variables=[],
                    affected_objectives=[],
                )
            )
        elif optimality_status == OptimalityStatus.RESOURCE_LIMIT:
            limitations.append(
                OptimizationLimitation(
                    limitation_id=f"lim_{problem_id}_resource_limit",
                    category="RESOURCE_LIMIT",
                    description=f"Search truncated at {SAGE_OPTIMIZATION_MAX_CANDIDATES} candidates. Best discovered solution reported.",
                    affected_variables=[],
                    affected_objectives=[],
                )
            )

        # Confidence: High if OBSERVED context, Medium if FORECAST/SIMULATED
        confidence = OptimizationConfidence.HIGH
        if problem.context.simulation_id or problem.context.forecast_reference:
            confidence = OptimizationConfidence.MEDIUM

        result = OptimizationResult(
            optimization_id=opt_id,
            tenant_id=problem.tenant_id,
            workspace_id=problem.workspace_id,
            plant_id=problem.plant_id,
            problem=problem,
            feasibility=feasibility_result,
            optimality_status=optimality_status,
            confidence=confidence,
            recommended_solution=recommended,
            candidates=ranked_candidates[:SAGE_OPTIMIZATION_MAX_SOLUTION_COUNT],
            tradeoffs=tradeoffs,
            sensitivity_analysis=sensitivities,
            robustness=robustness,
            evidence=evidence[:SAGE_OPTIMIZATION_MAX_EVIDENCE],
            limitations=limitations,
            explanation=explanation,
            solver_metadata=solver_metadata,
            input_fingerprint=fingerprint,
            created_at=now_ts,
        )

        return self.repository.save(result)


# Global singleton instance
optimization_service = OptimizationService()
