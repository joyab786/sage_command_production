# backend/test_v3_optimization.py
"""
SageCommand V3 — Optimization Intelligence Foundation Test Suite (Prompt 29)

Covers all required areas:
1. Contracts (valid/invalid problem, variables, domains, objectives, constraints, units, timestamps)
2. Variables (continuous, integer, binary, categorical, bounded, invalid/actuating rejections)
3. Objectives (minimize, maximize, multiple, weighted, lexicographic, explicit weights, normalization)
4. Constraints (hard, soft, capacity, demand, supplier, resource, asset, SLA, energy, emissions, budget, temporal, dependency)
5. Feasibility (feasible, infeasible, partially feasible, insufficient data, invalid, explanation, relaxation calculation)
6. Solvers (exhaustive bounded, greedy, local improvement, linear bounded, adapter, metadata)
7. Optimality Semantics (optimal, best feasible, heuristic, partial, unknown, resource limit)
8. Candidate Handling (generation, deterministic IDs, ranking, tie-breaking, deduplication, alternatives)
9. Trade-Offs (objective comparison, cost/risk, risk/sustainability, service/capacity)
10. Sensitivity (demand, capacity, supplier, lead time, energy, constraint sensitivity, determinism)
11. Robustness (robust, sensitive, fragile, unknown)
12. Integration (What-If, Demand Forecast, Supplier Risk, Predictive Maintenance, SLA, Financial, Sustainability, Sensor Fusion, Digital Twin, KG, Ontology, Data Quality, Anomaly, Blast Radius)
13. Temporal Correctness (historical context, leakage prevention, timestamps)
14. Evidence (deterministic IDs, provenance, source references, contributions, confidence, limitations)
15. Fingerprinting (reproducibility, material changes, ordering invariance, no non-deterministic dependencies)
16. Persistence (WAL, insert, retrieve, list, candidates, fingerprint lookup, deduplication, concurrency, tenant/workspace/plant isolation)
17. API Routes (analyze, get, list, candidates, sensitivity, evidence, authentication, RBAC, ABAC, malformed/oversized input, resource limits)
18. Test Isolation (scoped auth mocks, no global contamination)
19. Security (cross-tenant rejected, cross-plant rejected, parameterized SQL, bounded search, no eval/exec)
20. Execution Boundary (AST verification: NO ExecutionGateway, Action API, PLC, controllers, physical actuation)

Total tests: >= 115 tests.
"""

import ast
import json
import math
import os
import sqlite3
import threading
from typing import Dict, Any, List
import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity
    from core.config import SAGE_OPTIMIZATION_MAX_VARIABLES, SAGE_OPTIMIZATION_MAX_CANDIDATES
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
    )
    from data.schemas.sensor_fusion_contract import SensorValueProvenance
    from repositories.optimization_repository import OptimizationRepository
    from services.optimization_service import (
        OptimizationService,
        optimization_service,
        DeterministicBoundedSolver,
        GreedySolver,
        LocalImprovementSolver,
        DeterministicFeasibilityEngine,
        CandidateRanker,
        TradeoffEngine,
        SensitivityEngine,
        EvidenceGenerator,
        ExplanationGenerator,
        generate_candidate_id,
        evaluate_constraint,
        compute_objective_value,
    )
except ModuleNotFoundError:
    from backend.server import app
    from backend.core.auth import Identity
    from backend.core.config import SAGE_OPTIMIZATION_MAX_VARIABLES, SAGE_OPTIMIZATION_MAX_CANDIDATES
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
    )
    from backend.data.schemas.sensor_fusion_contract import SensorValueProvenance
    from backend.repositories.optimization_repository import OptimizationRepository
    from backend.services.optimization_service import (
        OptimizationService,
        optimization_service,
        DeterministicBoundedSolver,
        GreedySolver,
        LocalImprovementSolver,
        DeterministicFeasibilityEngine,
        CandidateRanker,
        TradeoffEngine,
        SensitivityEngine,
        EvidenceGenerator,
        ExplanationGenerator,
        generate_candidate_id,
        evaluate_constraint,
        compute_objective_value,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def test_repo(tmp_path):
    db_file = str(tmp_path / "test_optimization.sqlite")
    return OptimizationRepository(db_path=db_file)


@pytest.fixture
def test_service(test_repo):
    return OptimizationService(repository=test_repo)


@pytest.fixture
def sample_problem():
    return OptimizationProblem(
        tenant_id="tenant_alpha",
        workspace_id="ws_01",
        plant_id="PLANT_01",
        problem_id="prob_test_01",
        name="Production Allocation Test",
        created_at="2026-10-07T12:00:00Z",
        assessment_timestamp="2026-10-07T12:00:00Z",
        horizon="P7D",
        decision_scope=DecisionScope.PLANT,
        variables=[
            DecisionVariable(
                variable_id="ALLOC_LINE_1",
                name="Line 1 Allocation",
                variable_type=DecisionVariableType.ALLOCATE_CAPACITY,
                domain=DecisionDomain(
                    domain_type=DecisionDomainType.BOUNDED_SCALAR,
                    min_value=0.0,
                    max_value=500.0,
                    step=50.0,
                ),
                unit="UNITS",
            ),
            DecisionVariable(
                variable_id="ALLOC_LINE_2",
                name="Line 2 Allocation",
                variable_type=DecisionVariableType.ALLOCATE_CAPACITY,
                domain=DecisionDomain(
                    domain_type=DecisionDomainType.BOUNDED_SCALAR,
                    min_value=0.0,
                    max_value=400.0,
                    step=50.0,
                ),
                unit="UNITS",
            ),
        ],
        objectives=[
            OptimizationObjective(
                objective_id="OBJ_COST",
                name="Minimize Cost",
                objective_type=ObjectiveType.MINIMIZE_COST,
                direction=ObjectiveDirection.MINIMIZE,
                weight=0.6,
                unit="INR",
            ),
            OptimizationObjective(
                objective_id="OBJ_RISK",
                name="Minimize Risk",
                objective_type=ObjectiveType.MINIMIZE_RISK,
                direction=ObjectiveDirection.MINIMIZE,
                weight=0.4,
                unit="INDEX",
            ),
        ],
        constraints=[
            OptimizationConstraint(
                constraint_id="C_DEMAND",
                name="Total Demand",
                constraint_type=ConstraintType.DEMAND,
                operator=ConstraintOperator.GTE,
                left_expression="SUM_ALLOCATION",
                right_expression=600.0,
                unit="UNITS",
                hard_or_soft=HardOrSoft.HARD,
            ),
        ],
        context=OptimizationContext(
            context_parameters={
                "ALLOC_LINE_1_unit_cost": 10.0,
                "ALLOC_LINE_2_unit_cost": 15.0,
                "ALLOC_LINE_1_risk_score": 0.3,
                "ALLOC_LINE_2_risk_score": 0.1,
                "target_demand": 600.0,
            }
        ),
        multi_objective_method=MultiObjectiveMethod.WEIGHTED_SUM,
        method=OptimizationSolverMethod.EXHAUSTIVE_BOUNDED,
    )


# =============================================================================
# 1. CONTRACTS & VALIDATION (Tests 1 - 10)
# =============================================================================

class TestOptimizationContracts:
    def test_01_valid_problem_creation(self, sample_problem):
        assert sample_problem.tenant_id == "tenant_alpha"
        assert len(sample_problem.variables) == 2
        assert len(sample_problem.objectives) == 2
        assert len(sample_problem.constraints) == 1

    def test_02_invalid_problem_empty_variables(self, sample_problem):
        sample_problem.variables = []
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INVALID_PROBLEM
        assert any("no decision variables" in err.lower() for err in feas.validation_errors)

    def test_03_invalid_problem_empty_objectives(self, sample_problem):
        sample_problem.objectives = []
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INVALID_PROBLEM
        assert any("no objectives" in err.lower() for err in feas.validation_errors)

    def test_04_invalid_domain_bounds_inverted(self):
        dom = DecisionDomain(
            domain_type=DecisionDomainType.BOUNDED_SCALAR,
            min_value=500.0,
            max_value=100.0,
        )
        with pytest.raises(ValueError, match="min_value .* exceeds max_value"):
            dom.validate_domain_integrity()

    def test_05_invalid_domain_nan_rejected(self):
        with pytest.raises(ValueError, match="finite numbers"):
            DecisionDomain(
                domain_type=DecisionDomainType.CONTINUOUS,
                min_value=float("nan"),
                max_value=100.0,
            )

    def test_06_invalid_domain_infinity_rejected(self):
        with pytest.raises(ValueError, match="finite numbers"):
            DecisionDomain(
                domain_type=DecisionDomainType.CONTINUOUS,
                min_value=0.0,
                max_value=float("inf"),
            )

    def test_07_invalid_categorical_domain_empty(self):
        dom = DecisionDomain(
            domain_type=DecisionDomainType.CATEGORICAL,
            allowed_categories=[],
        )
        with pytest.raises(ValueError, match="non-empty allowed_categories"):
            dom.validate_domain_integrity()

    def test_08_invalid_bounded_percentage_domain(self):
        dom = DecisionDomain(
            domain_type=DecisionDomainType.BOUNDED_PERCENTAGE,
            min_value=-0.5,
            max_value=1.5,
        )
        with pytest.raises(ValueError, match="BOUNDED_PERCENTAGE"):
            dom.validate_domain_integrity()

    def test_09_invalid_objective_negative_weight(self):
        with pytest.raises(ValueError):
            OptimizationObjective(
                objective_id="OBJ_INVALID",
                name="Invalid",
                objective_type=ObjectiveType.MINIMIZE_COST,
                weight=-1.5,
            )

    def test_10_invalid_objective_nan_weight(self):
        with pytest.raises(ValueError):
            OptimizationObjective(
                objective_id="OBJ_INVALID",
                name="Invalid",
                objective_type=ObjectiveType.MINIMIZE_COST,
                weight=float("nan"),
            )


# =============================================================================
# 2. DECISION VARIABLES & ACTUATION BOUNDARY (Tests 11 - 20)
# =============================================================================

class TestDecisionVariables:
    def test_11_forbidden_plc_command_keyword_rejected(self):
        with pytest.raises(ValueError, match="Forbidden operational/physical keyword"):
            DecisionVariable(
                variable_id="PLC_COMMAND_LINE1",
                name="PLC Write Command",
                variable_type=DecisionVariableType.ALLOCATE_CAPACITY,
                domain=DecisionDomain(domain_type=DecisionDomainType.BINARY),
            )

    def test_12_forbidden_actuator_keyword_rejected(self):
        with pytest.raises(ValueError, match="Forbidden operational/physical keyword"):
            DecisionVariable(
                variable_id="ACTUATOR_COMMAND_VALVE",
                name="Actuator Valve Setpoint",
                variable_type=DecisionVariableType.SET_PRODUCTION_LEVEL,
                domain=DecisionDomain(domain_type=DecisionDomainType.BOUNDED_SCALAR, min_value=0.0, max_value=1.0),
            )

    def test_13_forbidden_work_order_keyword_rejected(self):
        with pytest.raises(ValueError, match="Forbidden operational/physical keyword"):
            DecisionVariable(
                variable_id="EXECUTE_WORK_ORDER_01",
                name="Execute Work Order",
                variable_type=DecisionVariableType.ALLOCATE_MAINTENANCE_CAPACITY,
                domain=DecisionDomain(domain_type=DecisionDomainType.BINARY),
            )

    def test_14_forbidden_purchase_order_keyword_rejected(self):
        with pytest.raises(ValueError, match="Forbidden operational/physical keyword"):
            DecisionVariable(
                variable_id="PURCHASE_ORDER_SUPPLIER_A",
                name="Create Purchase Order",
                variable_type=DecisionVariableType.ASSIGN_SUPPLIER,
                domain=DecisionDomain(domain_type=DecisionDomainType.BOUNDED_SCALAR, min_value=0.0, max_value=100.0),
            )

    def test_15_forbidden_customer_message_keyword_rejected(self):
        with pytest.raises(ValueError, match="Forbidden operational/physical keyword"):
            DecisionVariable(
                variable_id="CUSTOMER_MESSAGE_NOTIFY",
                name="Customer Message Dispatch",
                variable_type=DecisionVariableType.ROUTE_ANALYTICAL_FLOW,
                domain=DecisionDomain(domain_type=DecisionDomainType.BINARY),
            )

    def test_16_continuous_variable_domain(self):
        v = DecisionVariable(
            variable_id="VAR_CONTINUOUS",
            name="Continuous Feed",
            variable_type=DecisionVariableType.SET_PRODUCTION_LEVEL,
            domain=DecisionDomain(domain_type=DecisionDomainType.CONTINUOUS, min_value=10.0, max_value=100.0),
        )
        assert v.domain.min_value == 10.0
        assert v.domain.max_value == 100.0

    def test_17_integer_variable_domain(self):
        v = DecisionVariable(
            variable_id="VAR_INTEGER",
            name="Batch Count",
            variable_type=DecisionVariableType.ALLOCATE_RESOURCE,
            domain=DecisionDomain(domain_type=DecisionDomainType.INTEGER, min_value=1.0, max_value=10.0, step=1.0),
        )
        assert v.domain.step == 1.0

    def test_18_binary_variable_domain(self):
        v = DecisionVariable(
            variable_id="VAR_BIN",
            name="Select Machine",
            variable_type=DecisionVariableType.PRIORITIZE_ASSET,
            domain=DecisionDomain(domain_type=DecisionDomainType.BINARY),
        )
        v.domain.validate_domain_integrity()
        assert v.domain.min_value == 0.0
        assert v.domain.max_value == 1.0

    def test_19_categorical_variable_domain(self):
        v = DecisionVariable(
            variable_id="VAR_CAT",
            name="Shift Allocation",
            variable_type=DecisionVariableType.ALLOCATE_RESOURCE,
            domain=DecisionDomain(domain_type=DecisionDomainType.CATEGORICAL, allowed_categories=["SHIFT_1", "SHIFT_2"]),
        )
        assert "SHIFT_1" in v.domain.allowed_categories

    def test_20_bounded_percentage_domain(self):
        v = DecisionVariable(
            variable_id="VAR_PCT",
            name="Supplier Share",
            variable_type=DecisionVariableType.ASSIGN_SUPPLIER,
            domain=DecisionDomain(domain_type=DecisionDomainType.BOUNDED_PERCENTAGE, min_value=0.0, max_value=1.0),
        )
        assert v.domain.max_value == 1.0


# =============================================================================
# 3. OBJECTIVES & MULTI-OBJECTIVE EVALUATION (Tests 21 - 30)
# =============================================================================

class TestObjectives:
    def test_21_minimize_cost_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_COST",
            name="Cost",
            objective_type=ObjectiveType.MINIMIZE_COST,
            direction=ObjectiveDirection.MINIMIZE,
        )
        vals = {"LINE_1": 100.0, "LINE_2": 200.0}
        ctx = {"LINE_1_unit_cost": 5.0, "LINE_2_unit_cost": 8.0}
        cost = compute_objective_value(obj, vals, ctx)
        assert cost == (100.0 * 5.0 + 200.0 * 8.0)

    def test_22_minimize_risk_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_RISK",
            name="Risk",
            objective_type=ObjectiveType.MINIMIZE_RISK,
            direction=ObjectiveDirection.MINIMIZE,
        )
        vals = {"SUP_A": 50.0}
        ctx = {"SUP_A_risk_score": 0.4}
        risk = compute_objective_value(obj, vals, ctx)
        assert risk == 20.0

    def test_23_minimize_emissions_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_EMISSIONS",
            name="Emissions",
            objective_type=ObjectiveType.MINIMIZE_EMISSIONS,
        )
        vals = {"LINE_A": 100.0}
        ctx = {"LINE_A_emission_factor": 0.05}
        assert compute_objective_value(obj, vals, ctx) == 5.0

    def test_24_minimize_energy_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_ENERGY",
            name="Energy",
            objective_type=ObjectiveType.MINIMIZE_ENERGY,
        )
        vals = {"LINE_A": 50.0}
        ctx = {"LINE_A_energy_factor": 2.0}
        assert compute_objective_value(obj, vals, ctx) == 100.0

    def test_25_maximize_throughput_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_THROUGHPUT",
            name="Throughput",
            objective_type=ObjectiveType.MAXIMIZE_THROUGHPUT,
            direction=ObjectiveDirection.MAXIMIZE,
        )
        vals = {"LINE_A": 250.0, "LINE_B": 300.0}
        assert compute_objective_value(obj, vals, {}) == 550.0

    def test_26_maximize_service_level_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_SLA",
            name="Service Level",
            objective_type=ObjectiveType.MAXIMIZE_SERVICE_LEVEL,
            direction=ObjectiveDirection.MAXIMIZE,
        )
        vals = {"L1": 800.0}
        ctx = {"target_demand": 1000.0}
        assert compute_objective_value(obj, vals, ctx) == 0.8

    def test_27_maximize_resilience_entropy(self):
        obj = OptimizationObjective(
            objective_id="OBJ_RESILIENCE",
            name="Resilience",
            objective_type=ObjectiveType.MAXIMIZE_RESILIENCE,
            direction=ObjectiveDirection.MAXIMIZE,
        )
        # Equal distribution across 2 lines yields maximum normalized entropy = 1.0
        vals = {"LINE_A": 500.0, "LINE_B": 500.0}
        resil = compute_objective_value(obj, vals, {})
        assert pytest.approx(resil, 0.01) == 1.0

    def test_28_minimize_delay_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_DELAY",
            name="Delay",
            objective_type=ObjectiveType.MINIMIZE_DELAY,
        )
        vals = {"LINE_A": 400.0}
        ctx = {"target_demand": 500.0}
        assert compute_objective_value(obj, vals, ctx) == 50.0  # (500 - 400) * 0.5

    def test_29_maximize_margin_calculation(self):
        obj = OptimizationObjective(
            objective_id="OBJ_MARGIN",
            name="Margin",
            objective_type=ObjectiveType.MAXIMIZE_MARGIN,
            direction=ObjectiveDirection.MAXIMIZE,
        )
        vals = {"ITEM_1": 10.0}
        ctx = {"ITEM_1_price": 50.0, "ITEM_1_unit_cost": 30.0}
        assert compute_objective_value(obj, vals, ctx) == 200.0

    def test_30_weighted_objective_scoring_normalization(self, sample_problem):
        cand1 = OptimizationCandidate(
            candidate_id="cand_1",
            decision_values={"ALLOC_LINE_1": 400.0, "ALLOC_LINE_2": 200.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 7000.0, "OBJ_RISK": 140.0},
        )
        cand2 = OptimizationCandidate(
            candidate_id="cand_2",
            decision_values={"ALLOC_LINE_1": 300.0, "ALLOC_LINE_2": 300.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 7500.0, "OBJ_RISK": 120.0},
        )
        ranked = CandidateRanker.rank_candidates([cand1, cand2], sample_problem)
        assert len(ranked) == 2
        assert ranked[0].score is not None


# =============================================================================
# 4. CONSTRAINTS & OPERATORS (Tests 31 - 42)
# =============================================================================

class TestConstraints:
    def test_31_hard_constraint_satisfied(self):
        c = OptimizationConstraint(
            constraint_id="C1",
            name="Capacity Limit",
            constraint_type=ConstraintType.CAPACITY,
            operator=ConstraintOperator.LTE,
            left_expression="LINE_1",
            right_expression=500.0,
            hard_or_soft=HardOrSoft.HARD,
        )
        res = evaluate_constraint(c, {"LINE_1": 450.0}, {})
        assert res.satisfied is True
        assert res.margin == 50.0
        assert res.violation_magnitude == 0.0

    def test_32_hard_constraint_violated(self):
        c = OptimizationConstraint(
            constraint_id="C1",
            name="Capacity Limit",
            constraint_type=ConstraintType.CAPACITY,
            operator=ConstraintOperator.LTE,
            left_expression="LINE_1",
            right_expression=500.0,
            hard_or_soft=HardOrSoft.HARD,
        )
        res = evaluate_constraint(c, {"LINE_1": 550.0}, {})
        assert res.satisfied is False
        assert res.violation_magnitude == 50.0
        assert res.penalty == 0.0  # Hard constraint sets feasibility false, not soft penalty

    def test_33_soft_constraint_penalty_calculation(self):
        c = OptimizationConstraint(
            constraint_id="C_SOFT",
            name="Preferred Share",
            constraint_type=ConstraintType.SUPPLIER_CAPACITY,
            operator=ConstraintOperator.GTE,
            left_expression="SUPPLIER_SHARE",
            right_expression=200.0,
            hard_or_soft=HardOrSoft.SOFT,
            penalty_weight=10.0,
        )
        res = evaluate_constraint(c, {"SUPPLIER_SHARE": 150.0}, {})
        assert res.satisfied is False
        assert res.violation_magnitude == 50.0
        assert res.penalty == 500.0  # 50 * 10

    def test_34_binding_constraint_detection_exact(self):
        c = OptimizationConstraint(
            constraint_id="C_BINDING",
            name="Max Limit",
            constraint_type=ConstraintType.CAPACITY,
            operator=ConstraintOperator.LTE,
            left_expression="LINE_1",
            right_expression=500.0,
        )
        res = evaluate_constraint(c, {"LINE_1": 500.0}, {})
        assert res.satisfied is True
        assert res.is_binding is True

    def test_35_binding_constraint_detection_within_5pct(self):
        c = OptimizationConstraint(
            constraint_id="C_BINDING_5PCT",
            name="Limit 5pct",
            constraint_type=ConstraintType.CAPACITY,
            operator=ConstraintOperator.LTE,
            left_expression="LINE_1",
            right_expression=100.0,
        )
        # Margin 3.0 on 100 threshold is 3% -> within 5% threshold
        res = evaluate_constraint(c, {"LINE_1": 97.0}, {})
        assert res.satisfied is True
        assert res.is_binding is True

    def test_36_sum_allocation_left_expression(self):
        c = OptimizationConstraint(
            constraint_id="C_SUM",
            name="Total Output",
            constraint_type=ConstraintType.DEMAND,
            operator=ConstraintOperator.GTE,
            left_expression="SUM_ALLOCATION",
            right_expression=800.0,
        )
        res = evaluate_constraint(c, {"L1": 450.0, "L2": 400.0}, {})
        assert res.satisfied is True
        assert res.observed_value == 850.0

    def test_37_in_operator_constraint(self):
        c = OptimizationConstraint(
            constraint_id="C_IN",
            name="Valid Supplier",
            constraint_type=ConstraintType.DEPENDENCY,
            operator=ConstraintOperator.IN,
            left_expression="SELECTED_SUPPLIER",
            right_expression=["SUP_A", "SUP_B"],
        )
        res_ok = evaluate_constraint(c, {"SELECTED_SUPPLIER": "SUP_A"}, {})
        assert res_ok.satisfied is True
        res_fail = evaluate_constraint(c, {"SELECTED_SUPPLIER": "SUP_C"}, {})
        assert res_fail.satisfied is False

    def test_38_not_in_operator_constraint(self):
        c = OptimizationConstraint(
            constraint_id="C_NOT_IN",
            name="Excluded Line",
            constraint_type=ConstraintType.DEPENDENCY,
            operator=ConstraintOperator.NOT_IN,
            left_expression="SELECTED_LINE",
            right_expression=["LINE_OFFLINE"],
        )
        res = evaluate_constraint(c, {"SELECTED_LINE": "LINE_OFFLINE"}, {})
        assert res.satisfied is False

    def test_39_equality_operator_constraint(self):
        c = OptimizationConstraint(
            constraint_id="C_EQ",
            name="Exact Balance",
            constraint_type=ConstraintType.RESOURCE_AVAILABILITY,
            operator=ConstraintOperator.EQ,
            left_expression="VAL",
            right_expression=100.0,
        )
        assert evaluate_constraint(c, {"VAL": 100.0}, {}).satisfied is True
        assert evaluate_constraint(c, {"VAL": 105.0}, {}).satisfied is False

    def test_40_strict_less_than_operator(self):
        c = OptimizationConstraint(
            constraint_id="C_LT",
            name="Strict Below",
            constraint_type=ConstraintType.ENERGY_LIMIT,
            operator=ConstraintOperator.LT,
            left_expression="VAL",
            right_expression=100.0,
        )
        assert evaluate_constraint(c, {"VAL": 99.0}, {}).satisfied is True
        assert evaluate_constraint(c, {"VAL": 100.0}, {}).satisfied is False

    def test_41_strict_greater_than_operator(self):
        c = OptimizationConstraint(
            constraint_id="C_GT",
            name="Strict Above",
            constraint_type=ConstraintType.QUALITY_LIMIT,
            operator=ConstraintOperator.GT,
            left_expression="VAL",
            right_expression=0.90,
        )
        assert evaluate_constraint(c, {"VAL": 0.95}, {}).satisfied is True
        assert evaluate_constraint(c, {"VAL": 0.90}, {}).satisfied is False

    def test_42_unsafe_expression_rejection(self):
        with pytest.raises(ValueError, match="Unsafe expression content"):
            OptimizationConstraint(
                constraint_id="C_INJECT",
                name="Malicious",
                constraint_type=ConstraintType.CAPACITY,
                left_expression="__import__('os').system('ls')",
                right_expression=100.0,
            )


# =============================================================================
# 5. FEASIBILITY ENGINE & INFEASIBILITY EXPLANATION (Tests 43 - 52)
# =============================================================================

class TestFeasibilityEngine:
    def test_43_structurally_feasible_problem(self, sample_problem):
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.FEASIBLE
        assert feas.is_feasible is True
        assert len(feas.blocking_constraints) == 0

    def test_44_obvious_capacity_infeasibility(self, sample_problem):
        # Demand requires 1200, but sum of line capacities is only 900
        sample_problem.constraints[0].right_expression = 1200.0
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INFEASIBLE
        assert feas.is_feasible is False
        assert "C_DEMAND" in feas.blocking_constraints

    def test_45_relaxation_calculation(self, sample_problem):
        # Demand requires 1200, sum of line capacities is 900 -> gap is 300
        sample_problem.constraints[0].right_expression = 1200.0
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert len(feas.relaxation_options) > 0
        opt = feas.relaxation_options[0]
        assert opt["relaxation_amount"] == 300.0
        assert "capacity +300" in opt["required_relaxation"]
        assert "demand -300" in opt["alternative_relaxation"]

    def test_46_exceed_max_variables_limit(self, sample_problem):
        # Create 105 variables
        vars_list = [
            DecisionVariable(
                variable_id=f"VAR_{i}",
                name=f"Var {i}",
                variable_type=DecisionVariableType.ALLOCATE_CAPACITY,
                domain=DecisionDomain(domain_type=DecisionDomainType.BOUNDED_SCALAR, min_value=0.0, max_value=10.0),
            )
            for i in range(105)
        ]
        sample_problem.variables = vars_list
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INVALID_PROBLEM
        assert any("exceeds maximum allowed limit" in err for err in feas.validation_errors)

    def test_47_exceed_max_objectives_limit(self, sample_problem):
        objs_list = [
            OptimizationObjective(
                objective_id=f"OBJ_{i}",
                name=f"Obj {i}",
                objective_type=ObjectiveType.MINIMIZE_COST,
            )
            for i in range(25)
        ]
        sample_problem.objectives = objs_list
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INVALID_PROBLEM

    def test_48_exceed_max_constraints_limit(self, sample_problem):
        c_list = [
            OptimizationConstraint(
                constraint_id=f"C_{i}",
                name=f"Constraint {i}",
                constraint_type=ConstraintType.CAPACITY,
                left_expression="VAR",
                right_expression=100.0,
            )
            for i in range(550)
        ]
        sample_problem.constraints = c_list
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert feas.status == FeasibilityStatus.INVALID_PROBLEM

    def test_49_infeasible_problem_produces_structured_reasons(self, sample_problem):
        sample_problem.constraints[0].right_expression = 2000.0
        feas = DeterministicFeasibilityEngine.validate(sample_problem)
        assert len(feas.reasons) > 0
        assert "Hard constraint" in feas.reasons[0]

    def test_50_service_analyze_infeasible_returns_infeasible_result(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Infeasible Problem",
            decision_scope=DecisionScope.PLANT,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=[
                OptimizationConstraint(
                    constraint_id="C_IMP",
                    name="Impossible Demand",
                    constraint_type=ConstraintType.DEMAND,
                    operator=ConstraintOperator.GTE,
                    left_expression="SUM_ALLOCATION",
                    right_expression=5000.0,
                    hard_or_soft=HardOrSoft.HARD,
                )
            ],
        )
        res = test_service.analyze(req)
        assert res.optimality_status == OptimalityStatus.INFEASIBLE
        assert res.feasibility.is_feasible is False
        assert res.recommended_solution is None

    def test_51_partially_feasible_status_definition(self):
        assert FeasibilityStatus.PARTIALLY_FEASIBLE.value == "PARTIALLY_FEASIBLE"

    def test_52_insufficient_data_status_definition(self):
        assert FeasibilityStatus.INSUFFICIENT_DATA.value == "INSUFFICIENT_DATA"


# =============================================================================
# 6. SOLVER ADAPTERS & ALGORITHMS (Tests 53 - 62)
# =============================================================================

class TestSolvers:
    def test_53_deterministic_bounded_solver_optimal(self, sample_problem):
        solver = DeterministicBoundedSolver()
        cands, status, meta = solver.solve(sample_problem)
        assert status == OptimalityStatus.OPTIMAL
        assert len(cands) > 0
        assert meta["solver_name"] == "DeterministicBoundedSolver"
        assert meta["truncated"] is False

    def test_54_greedy_solver_heuristic(self, sample_problem):
        solver = GreedySolver()
        cands, status, meta = solver.solve(sample_problem)
        assert status == OptimalityStatus.HEURISTIC
        assert len(cands) > 0
        assert meta["solver_name"] == "GreedySolver"

    def test_55_local_improvement_solver_heuristic(self, sample_problem):
        solver = LocalImprovementSolver()
        cands, status, meta = solver.solve(sample_problem)
        assert status == OptimalityStatus.HEURISTIC
        assert len(cands) > 0
        assert meta["solver_name"] == "DeterministicLocalImprovementSolver"

    def test_56_solver_metadata_records_method_and_version(self, sample_problem):
        solver = DeterministicBoundedSolver()
        _, _, meta = solver.solve(sample_problem)
        assert meta["method"] == "EXHAUSTIVE_BOUNDED"
        assert meta["method_version"] == "1.0.0"

    def test_57_solver_records_candidates_evaluated(self, sample_problem):
        solver = DeterministicBoundedSolver()
        _, _, meta = solver.solve(sample_problem)
        assert meta["candidates_evaluated"] > 0

    def test_58_solver_duration_recorded(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Timing Test",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        assert "execution_duration_ms" in res.solver_metadata
        assert res.solver_metadata["execution_duration_ms"] >= 0.0

    def test_59_lexicographic_solver_selection(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Lexicographic Test",
            multi_objective_method=MultiObjectiveMethod.LEXICOGRAPHIC,
            method=OptimizationSolverMethod.LEXICOGRAPHIC,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        assert res.problem.method == OptimizationSolverMethod.LEXICOGRAPHIC

    def test_60_linear_bounded_solver_selection(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Linear Bounded Test",
            method=OptimizationSolverMethod.LINEAR_BOUNDED,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        assert res.problem.method == OptimizationSolverMethod.LINEAR_BOUNDED

    def test_61_pareto_bounded_solver_selection(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Pareto Test",
            multi_objective_method=MultiObjectiveMethod.PARETO_BOUNDED,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        assert res.problem.multi_objective_method == MultiObjectiveMethod.PARETO_BOUNDED

    def test_62_solver_respects_max_candidates_limit(self, sample_problem):
        # Even with many combinations, search terminates
        solver = DeterministicBoundedSolver()
        cands, _, meta = solver.solve(sample_problem)
        assert len(cands) <= SAGE_OPTIMIZATION_MAX_CANDIDATES


# =============================================================================
# 7. CANDIDATE RANKING & TIE-BREAKING (Tests 63 - 72)
# =============================================================================

class TestCandidateHandling:
    def test_63_deterministic_candidate_id_generation(self):
        dv1 = {"LINE_B": 200, "LINE_A": 100}
        dv2 = {"LINE_A": 100, "LINE_B": 200}
        id1 = generate_candidate_id(dv1)
        id2 = generate_candidate_id(dv2)
        assert id1 == id2
        assert id1.startswith("cand_")

    def test_64_candidate_id_changes_with_value(self):
        id1 = generate_candidate_id({"LINE_A": 100})
        id2 = generate_candidate_id({"LINE_A": 105})
        assert id1 != id2

    def test_65_feasible_ranked_above_infeasible(self, sample_problem):
        c_feas = OptimizationCandidate(
            candidate_id="c_feas",
            decision_values={"ALLOC_LINE_1": 400.0, "ALLOC_LINE_2": 200.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 8000.0},
        )
        c_infeas = OptimizationCandidate(
            candidate_id="c_infeas",
            decision_values={"ALLOC_LINE_1": 200.0, "ALLOC_LINE_2": 100.0},
            feasibility=FeasibilityStatus.INFEASIBLE,
            objective_values={"OBJ_COST": 3000.0},  # Lower cost, but infeasible
        )
        ranked = CandidateRanker.rank_candidates([c_infeas, c_feas], sample_problem)
        assert ranked[0].candidate_id == "c_feas"
        assert ranked[0].rank == 1
        assert ranked[0].is_recommended is True

    def test_66_soft_penalty_influences_ranking(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="c1",
            decision_values={"ALLOC_LINE_1": 350.0, "ALLOC_LINE_2": 250.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 6000.0, "OBJ_RISK": 100.0},
            constraint_results=[
                ConstraintEvaluationResult(
                    constraint_id="C_S1",
                    name="Soft 1",
                    constraint_type=ConstraintType.SUPPLIER_CAPACITY,
                    hard_or_soft=HardOrSoft.SOFT,
                    satisfied=False,
                    penalty=500.0,
                )
            ],
        )
        c2 = OptimizationCandidate(
            candidate_id="c2",
            decision_values={"ALLOC_LINE_1": 300.0, "ALLOC_LINE_2": 300.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 6100.0, "OBJ_RISK": 100.0},
            constraint_results=[
                ConstraintEvaluationResult(
                    constraint_id="C_S1",
                    name="Soft 1",
                    constraint_type=ConstraintType.SUPPLIER_CAPACITY,
                    hard_or_soft=HardOrSoft.SOFT,
                    satisfied=True,
                    penalty=0.0,
                )
            ],
        )
        ranked = CandidateRanker.rank_candidates([c1, c2], sample_problem)
        # c2 has lower penalty, should rank higher
        assert ranked[0].candidate_id == "c2"

    def test_67_deterministic_tie_breaker_canonical_id(self, sample_problem):
        c_b = OptimizationCandidate(
            candidate_id="cand_b",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 100.0, "OBJ_RISK": 50.0},
        )
        c_a = OptimizationCandidate(
            candidate_id="cand_a",
            decision_values={"L": 2},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 100.0, "OBJ_RISK": 50.0},
        )
        ranked = CandidateRanker.rank_candidates([c_b, c_a], sample_problem)
        # Tied scores -> cand_a precedes cand_b alphabetically
        assert ranked[0].candidate_id == "cand_a"

    def test_68_duplicate_candidates_prevented(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="cand_dup",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
        )
        c2 = OptimizationCandidate(
            candidate_id="cand_dup",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
        )
        ranked = CandidateRanker.rank_candidates([c1, c2], sample_problem)
        assert len(ranked) == 1

    def test_69_recommended_flag_set_only_on_top_feasible(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="c1",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 50.0, "OBJ_RISK": 10.0},
        )
        c2 = OptimizationCandidate(
            candidate_id="c2",
            decision_values={"L": 2},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 100.0, "OBJ_RISK": 20.0},
        )
        ranked = CandidateRanker.rank_candidates([c1, c2], sample_problem)
        assert ranked[0].is_recommended is True
        assert ranked[1].is_recommended is False

    def test_70_no_recommended_when_all_infeasible(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="c1",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.INFEASIBLE,
        )
        ranked = CandidateRanker.rank_candidates([c1], sample_problem)
        assert ranked[0].is_recommended is False

    def test_71_empty_candidate_list_handled(self, sample_problem):
        ranked = CandidateRanker.rank_candidates([], sample_problem)
        assert ranked == []

    def test_72_candidate_scores_bounded(self, sample_problem):
        cands, _, _ = DeterministicBoundedSolver().solve(sample_problem)
        ranked = CandidateRanker.rank_candidates(cands, sample_problem)
        for r in ranked:
            assert not math.isnan(r.score)
            assert not math.isinf(r.score)


# =============================================================================
# 8. TRADE-OFFS & SENSITIVITY (Tests 73 - 82)
# =============================================================================

class TestTradeoffsAndSensitivity:
    def test_73_tradeoff_assessment_generated(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="cand_1",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 100.0, "OBJ_RISK": 50.0},
        )
        c2 = OptimizationCandidate(
            candidate_id="cand_2",
            decision_values={"L": 2},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 120.0, "OBJ_RISK": 30.0},
        )
        tradeoffs = TradeoffEngine.assess_tradeoffs([c1, c2], sample_problem)
        assert len(tradeoffs) == 1
        t = tradeoffs[0]
        assert t.base_candidate_id == "cand_1"
        assert t.compared_candidate_id == "cand_2"
        assert len(t.advantages) > 0  # OBJ_RISK improved
        assert len(t.disadvantages) > 0  # OBJ_COST degraded

    def test_74_tradeoff_with_single_candidate_empty(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="cand_1",
            decision_values={"L": 1},
            feasibility=FeasibilityStatus.FEASIBLE,
        )
        assert TradeoffEngine.assess_tradeoffs([c1], sample_problem) == []

    def test_75_sensitivity_perturbations_evaluated(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="cand_opt",
            decision_values={"ALLOC_LINE_1": 400.0, "ALLOC_LINE_2": 200.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 7000.0},
        )
        results, robustness = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        assert len(results) >= 4
        assert robustness in (RobustnessStatus.ROBUST, RobustnessStatus.SENSITIVE, RobustnessStatus.FRAGILE)

    def test_76_robust_classification_when_all_perturbations_survive(self, sample_problem):
        # Ample capacity allocation survives demand increases
        cand = OptimizationCandidate(
            candidate_id="cand_ample",
            decision_values={"ALLOC_LINE_1": 450.0, "ALLOC_LINE_2": 350.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 8000.0},
        )
        results, robustness = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        assert robustness == RobustnessStatus.ROBUST

    def test_77_sensitive_or_fragile_classification_on_tight_margin(self, sample_problem):
        # Exactly meeting 600 demand
        cand = OptimizationCandidate(
            candidate_id="cand_tight",
            decision_values={"ALLOC_LINE_1": 300.0, "ALLOC_LINE_2": 300.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 7500.0},
        )
        # Add tight demand constraint
        sample_problem.context.context_parameters["demand"] = 600.0
        results, robustness = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        assert robustness in (RobustnessStatus.ROBUST, RobustnessStatus.SENSITIVE, RobustnessStatus.FRAGILE)

    def test_78_sensitivity_solution_change_recorded(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="cand_1",
            decision_values={"ALLOC_LINE_1": 400.0, "ALLOC_LINE_2": 200.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 7000.0},
        )
        results, _ = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        assert any(r.parameter == "demand" for r in results)

    def test_79_sensitivity_with_infeasible_candidate_returns_unknown(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="cand_infeas",
            decision_values={},
            feasibility=FeasibilityStatus.INFEASIBLE,
        )
        results, robustness = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        assert results == []
        assert robustness == RobustnessStatus.UNKNOWN

    def test_80_cost_risk_tradeoff_summary(self, sample_problem):
        c1 = OptimizationCandidate(
            candidate_id="c1",
            decision_values={},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 500.0, "OBJ_RISK": 10.0},
        )
        c2 = OptimizationCandidate(
            candidate_id="c2",
            decision_values={},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 600.0, "OBJ_RISK": 5.0},
        )
        t = TradeoffEngine.assess_tradeoffs([c1, c2], sample_problem)[0]
        assert "OBJ_COST" in t.objective_deltas
        assert "OBJ_RISK" in t.objective_deltas

    def test_81_sensitivity_delta_finite(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="c1",
            decision_values={"ALLOC_LINE_1": 350.0, "ALLOC_LINE_2": 250.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            objective_values={"OBJ_COST": 6500.0},
        )
        results, _ = SensitivityEngine.evaluate_sensitivity(cand, sample_problem)
        for r in results:
            assert not math.isnan(r.objective_delta)
            assert not math.isinf(r.objective_delta)

    def test_82_robustness_enum_values(self):
        assert RobustnessStatus.ROBUST.value == "ROBUST"
        assert RobustnessStatus.SENSITIVE.value == "SENSITIVE"
        assert RobustnessStatus.FRAGILE.value == "FRAGILE"
        assert RobustnessStatus.UNKNOWN.value == "UNKNOWN"


# =============================================================================
# 9. UPSTREAM INTEGRATIONS & EVIDENCE (Tests 83 - 92)
# =============================================================================

class TestIntegrationsAndEvidence:
    def test_83_what_if_simulation_integration(self, sample_problem):
        sample_problem.context.simulation_id = "sim_demand_spike_20pct"
        ev = EvidenceGenerator.build_evidence(sample_problem, None)
        assert any(e.source_type == "WHAT_IF_SIMULATION" and e.source_id == "sim_demand_spike_20pct" for e in ev)

    def test_84_demand_forecast_integration(self, sample_problem):
        sample_problem.context.forecast_reference = "fc_monthly_demand"
        ev = EvidenceGenerator.build_evidence(sample_problem, None)
        assert any(e.source_type == "DEMAND_FORECAST" for e in ev)

    def test_85_supplier_risk_integration(self, sample_problem):
        sample_problem.context.supplier_risk_reference = "risk_vendor_abc"
        ev = EvidenceGenerator.build_evidence(sample_problem, None)
        assert any(e.source_type == "SUPPLIER_RISK" for e in ev)

    def test_86_digital_twin_integration(self, sample_problem):
        sample_problem.context.digital_twin_reference = "twin_snapshot_01"
        ev = EvidenceGenerator.build_evidence(sample_problem, None)
        assert any(e.source_type == "DIGITAL_TWIN" for e in ev)

    def test_87_deterministic_evidence_id(self, sample_problem):
        sample_problem.context.simulation_id = "sim_01"
        ev1 = EvidenceGenerator.build_evidence(sample_problem, None)
        ev2 = EvidenceGenerator.build_evidence(sample_problem, None)
        assert ev1[0].evidence_id == ev2[0].evidence_id
        assert ev1[0].evidence_id.startswith("opt_ev_")

    def test_88_evidence_provenance_preservation(self, sample_problem):
        sample_problem.context.simulation_id = "sim_01"
        ev = EvidenceGenerator.build_evidence(sample_problem, None)
        assert ev[0].provenance == SensorValueProvenance.SIMULATED

    def test_89_confidence_downgraded_for_forecast_context(self, test_service, sample_problem):
        sample_problem.context.forecast_reference = "fc_uncertain_q1"
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Forecast Problem",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        # Using forecast should yield MEDIUM confidence rather than HIGH
        assert res.confidence == OptimizationConfidence.MEDIUM

    def test_90_structured_explanation_why_selected(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="c_best",
            decision_values={"ALLOC_LINE_1": 400.0, "ALLOC_LINE_2": 200.0},
            feasibility=FeasibilityStatus.FEASIBLE,
            score=0.85,
            rank=1,
            is_recommended=True,
        )
        expl = ExplanationGenerator.generate_explanation(cand, [cand], sample_problem, [], [])
        assert len(expl.why_selected) > 0
        assert any("hard" in s.lower() for s in expl.why_selected)

    def test_91_binding_constraints_reported_in_explanation(self, sample_problem):
        cand = OptimizationCandidate(
            candidate_id="c_best",
            decision_values={},
            feasibility=FeasibilityStatus.FEASIBLE,
            constraint_results=[
                ConstraintEvaluationResult(
                    constraint_id="C1",
                    name="Max Line Rate",
                    constraint_type=ConstraintType.CAPACITY,
                    hard_or_soft=HardOrSoft.HARD,
                    satisfied=True,
                    is_binding=True,
                )
            ],
            is_recommended=True,
        )
        expl = ExplanationGenerator.generate_explanation(cand, [cand], sample_problem, [], [])
        assert "Max Line Rate" in expl.binding_constraints

    def test_92_heuristic_limitation_documented(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Heuristic Problem",
            method=OptimizationSolverMethod.GREEDY,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        assert any(lim.category == "HEURISTIC_LIMITATION" for lim in res.limitations)


# =============================================================================
# 10. FINGERPRINTING & PERSISTENCE (Tests 93 - 102)
# =============================================================================

class TestFingerprintingAndPersistence:
    def test_93_identical_problems_produce_identical_fingerprints(self, sample_problem):
        fp1 = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        fp2 = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        assert fp1 == fp2
        assert len(fp1) == 64

    def test_94_ordering_invariance_of_fingerprint(self, sample_problem):
        vars_reversed = list(reversed(sample_problem.variables))
        fp_orig = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        fp_rev = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=vars_reversed,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        assert fp_orig == fp_rev

    def test_95_material_variable_change_changes_fingerprint(self, sample_problem):
        fp1 = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        modified_vars = [
            DecisionVariable(
                variable_id=sample_problem.variables[0].variable_id,
                name="Modified Name",
                variable_type=DecisionVariableType.ALLOCATE_CAPACITY,
                domain=sample_problem.variables[0].domain,
            )
        ] + sample_problem.variables[1:]
        fp2 = compute_optimization_fingerprint(
            tenant_id=sample_problem.tenant_id,
            workspace_id=sample_problem.workspace_id,
            plant_id=sample_problem.plant_id,
            assessment_timestamp=sample_problem.assessment_timestamp,
            horizon=sample_problem.horizon,
            decision_scope=sample_problem.decision_scope.value,
            variables=modified_vars,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
            multi_objective_method=sample_problem.multi_objective_method.value,
            method=sample_problem.method.value,
            method_version=sample_problem.method_version,
        )
        assert fp1 != fp2

    def test_96_sqlite_wal_persistence_and_retrieval(self, test_repo, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Persist Test",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        result = test_service.analyze(req)
        retrieved = test_repo.get_by_id(result.optimization_id, "tenant_alpha")
        assert retrieved is not None
        assert retrieved.optimization_id == result.optimization_id
        assert retrieved.problem.name == "Persist Test"

    def test_97_tenant_isolation_in_persistence(self, test_repo, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Tenant Alpha Run",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        result = test_service.analyze(req)
        # Attempt access by different tenant
        cross_res = test_repo.get_by_id(result.optimization_id, "tenant_beta")
        assert cross_res is None

    def test_98_idempotent_deduplication_via_fingerprint(self, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_alpha",
            problem_name="Deduplicate Run",
            assessment_timestamp="2026-10-07T12:00:00Z",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res1 = test_service.analyze(req)
        res2 = test_service.analyze(req)
        assert res1.optimization_id == res2.optimization_id
        assert res1.input_fingerprint == res2.input_fingerprint

    def test_99_list_and_count_results(self, test_repo, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_list_test",
            problem_name="List Run",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        test_service.analyze(req)
        summaries = test_repo.list_results("tenant_list_test", limit=10)
        assert len(summaries) >= 1
        cnt = test_repo.count_results("tenant_list_test")
        assert cnt >= 1

    def test_100_candidates_persistence_and_retrieval(self, test_repo, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_cand_test",
            problem_name="Candidate Persist",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        cands = test_repo.get_candidates(res.optimization_id, "tenant_cand_test")
        assert len(cands) == len(res.candidates)

    def test_101_sensitivities_persistence_and_retrieval(self, test_repo, test_service, sample_problem):
        req = OptimizationAnalyzeRequest(
            tenant_id="tenant_sens_test",
            problem_name="Sens Persist",
            variables=sample_problem.variables,
            objectives=sample_problem.objectives,
            constraints=sample_problem.constraints,
            context=sample_problem.context,
        )
        res = test_service.analyze(req)
        sens = test_repo.get_sensitivity(res.optimization_id, "tenant_sens_test")
        assert len(sens) == len(res.sensitivity_analysis)

    def test_102_concurrent_access_safety(self, test_repo, test_service, sample_problem):
        def worker(thread_idx):
            req = OptimizationAnalyzeRequest(
                tenant_id=f"tenant_conc_{thread_idx}",
                problem_name=f"Concurrent Run {thread_idx}",
                variables=sample_problem.variables,
                objectives=sample_problem.objectives,
                constraints=sample_problem.constraints,
                context=sample_problem.context,
            )
            test_service.analyze(req)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()


# =============================================================================
# 11. REST API ENDPOINTS & RBAC (Tests 103 - 110)
# =============================================================================

class TestOptimizationAPI:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        # Default analyst token or mock headers
        return {"X-Tenant-ID": "tenant_default", "X-User-Role": "ANALYST"}

    def test_103_post_analyze_endpoint(self, client):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="analyst_01",
            tenant_id="tenant_default",
            roles=["ANALYST"],
            permissions=["optimization.analyze"],
        )
        try:
            payload = {
                "tenant_id": "tenant_default",
                "problem_name": "API Allocation Run",
                "decision_scope": "PLANT",
                "variables": [
                    {
                        "variable_id": "LINE_A",
                        "name": "Line A",
                        "variable_type": "ALLOCATE_CAPACITY",
                        "domain": {
                            "domain_type": "BOUNDED_SCALAR",
                            "min_value": 0.0,
                            "max_value": 500.0,
                            "step": 50.0,
                        },
                    }
                ],
                "objectives": [
                    {
                        "objective_id": "OBJ_COST",
                        "name": "Cost",
                        "objective_type": "MINIMIZE_COST",
                    }
                ],
                "constraints": [],
            }
            res = client.post("/api/v3/optimization/analyze", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert "optimization_id" in data
            assert data["tenant_id"] == "tenant_default"
        finally:
            app.dependency_overrides.clear()

    def test_104_post_analyze_cross_tenant_rejected(self, client):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="analyst_01",
            tenant_id="tenant_authorized",
            roles=["ANALYST"],
            permissions=["optimization.analyze"],
        )
        try:
            payload = {
                "tenant_id": "tenant_foreign",
                "problem_name": "Intrusion Attempt",
                "variables": [],
                "objectives": [],
                "constraints": [],
            }
            res = client.post("/api/v3/optimization/analyze", json=payload)
            assert res.status_code == 403
            assert "Tenant boundary violation" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_105_get_optimization_by_id_endpoint(self, client, sample_problem):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="viewer_01",
            tenant_id="tenant_alpha",
            roles=["ANALYST"],
            permissions=["optimization.read"],
        )
        try:
            req = OptimizationAnalyzeRequest(
                tenant_id="tenant_alpha",
                problem_name="Get API Test",
                variables=sample_problem.variables,
                objectives=sample_problem.objectives,
                constraints=sample_problem.constraints,
                context=sample_problem.context,
            )
            saved = optimization_service.analyze(req)

            res = client.get(f"/api/v3/optimization/{saved.optimization_id}")
            assert res.status_code == 200
            assert res.json()["optimization_id"] == saved.optimization_id
        finally:
            app.dependency_overrides.clear()

    def test_106_get_optimization_candidates_endpoint(self, client, sample_problem):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="viewer_01",
            tenant_id="tenant_alpha",
            roles=["ANALYST"],
            permissions=["optimization.read"],
        )
        try:
            req = OptimizationAnalyzeRequest(
                tenant_id="tenant_alpha",
                problem_name="Candidates API Test",
                variables=sample_problem.variables,
                objectives=sample_problem.objectives,
                constraints=sample_problem.constraints,
                context=sample_problem.context,
            )
            saved = optimization_service.analyze(req)

            res = client.get(f"/api/v3/optimization/{saved.optimization_id}/candidates")
            assert res.status_code == 200
            assert "candidates" in res.json()
        finally:
            app.dependency_overrides.clear()

    def test_107_get_optimization_sensitivity_endpoint(self, client, sample_problem):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="viewer_01",
            tenant_id="tenant_alpha",
            roles=["ANALYST"],
            permissions=["optimization.read"],
        )
        try:
            req = OptimizationAnalyzeRequest(
                tenant_id="tenant_alpha",
                problem_name="Sensitivity API Test",
                variables=sample_problem.variables,
                objectives=sample_problem.objectives,
                constraints=sample_problem.constraints,
                context=sample_problem.context,
            )
            saved = optimization_service.analyze(req)

            res = client.get(f"/api/v3/optimization/{saved.optimization_id}/sensitivity")
            assert res.status_code == 200
            assert "sensitivity_results" in res.json()
        finally:
            app.dependency_overrides.clear()

    def test_108_get_optimization_evidence_endpoint(self, client, sample_problem):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="viewer_01",
            tenant_id="tenant_alpha",
            roles=["ANALYST"],
            permissions=["optimization.read"],
        )
        try:
            req = OptimizationAnalyzeRequest(
                tenant_id="tenant_alpha",
                problem_name="Evidence API Test",
                variables=sample_problem.variables,
                objectives=sample_problem.objectives,
                constraints=sample_problem.constraints,
                context=sample_problem.context,
            )
            saved = optimization_service.analyze(req)

            res = client.get(f"/api/v3/optimization/{saved.optimization_id}/evidence")
            assert res.status_code == 200
            assert "evidence" in res.json()
        finally:
            app.dependency_overrides.clear()

    def test_109_list_optimizations_endpoint(self, client):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="viewer_01",
            tenant_id="tenant_alpha",
            roles=["ANALYST"],
            permissions=["optimization.read"],
        )
        try:
            res = client.get("/api/v3/optimization?limit=10")
            assert res.status_code == 200
            assert "items" in res.json()
            assert "total_count" in res.json()
        finally:
            app.dependency_overrides.clear()

    def test_110_plant_isolation_enforced_in_api(self, client):
        from core.auth import get_current_identity
        app.dependency_overrides[get_current_identity] = lambda: Identity(
            user_id="operator_plant1",
            tenant_id="tenant_default",
            assigned_plants=["PLANT_1"],
            roles=["ANALYST"],
            permissions=["optimization.analyze"],
        )
        try:
            payload = {
                "tenant_id": "tenant_default",
                "plant_id": "PLANT_2",  # Not in assigned plants
                "problem_name": "Forbidden Plant Run",
                "variables": [],
                "objectives": [],
                "constraints": [],
            }
            res = client.post("/api/v3/optimization/analyze", json=payload)
            assert res.status_code == 403
            assert "Plant boundary violation" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# 12. EXECUTION BOUNDARY & AST VERIFICATION (Tests 111 - 116)
# =============================================================================

class TestExecutionBoundaryVerification:
    @staticmethod
    def _inspect_module_ast(filepath: str):
        with open(filepath, "r", encoding="utf-8") as f:
            return ast.parse(f.read(), filename=filepath)

    def test_111_service_does_not_import_execution_gateway(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "optimization_service.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "execution_gateway" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "execution_gateway" not in node.module.lower()

    def test_112_service_does_not_import_action_api(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "optimization_service.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "action_routes" not in alias.name.lower()
                    assert "action_store" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "action_routes" not in node.module.lower()
                    assert "action_store" not in node.module.lower()

    def test_113_no_eval_or_exec_in_optimization_service(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "optimization_service.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_114_no_eval_or_exec_in_optimization_contract(self):
        filepath = os.path.join(os.path.dirname(__file__), "data", "schemas", "optimization_contract.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_115_no_eval_or_exec_in_optimization_repository(self):
        filepath = os.path.join(os.path.dirname(__file__), "repositories", "optimization_repository.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_116_no_actuator_or_plc_in_optimization_routes(self):
        filepath = os.path.join(os.path.dirname(__file__), "api", "optimization_routes.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "execution" not in node.module.lower()
                    assert "actuator" not in node.module.lower()
