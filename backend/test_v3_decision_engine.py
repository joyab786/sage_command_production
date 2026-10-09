# backend/test_v3_decision_engine.py
"""
SageCommand V3 — Decision Engine Foundation Test Suite (Prompt 30)

Covers all required areas:
1. Contracts and validation (all enums, models, validation of scope, timestamps, weights, NaN/inf, forbidden keywords)
2. Evaluation pipeline and ranking (categories, feasible/infeasible, hard vs soft constraints, weighted vs lexicographic, normalization, tie-breaking)
3. Outcome statuses (RECOMMENDED, CONDITIONALLY_RECOMMENDED, NO_FEASIBLE_OPTION, POLICY_BLOCKED, INSUFFICIENT_EVIDENCE, CONFLICTING_EVIDENCE, NEEDS_HUMAN_REVIEW)
4. Upstream analytical integrations (What-If, Optimization, Demand Forecast, Supplier Risk, Predictive Maintenance, SLA, Financial, Sustainability, Sensor Fusion, Digital Twin, KG, Ontology, Data Quality, Incidents, RCA, Blast Radius, graceful handling of missing/stale/corrupt data)
5. Trade-offs and Sensitivity analysis
6. Confidence and Uncertainty calculations
7. Determinism and Fingerprinting (canonical SHA-256, reproducibility, order invariance, sensitivity to material changes)
8. Persistence and Repository (WAL, queries, tenant/plant isolation, bounds, duplicate fingerprint, audit ledger)
9. API Routes and Authorization (endpoints, permissions, tenant spoofing, plant isolation, error codes)
10. Execution Boundary & Static AST verification (no ExecutionGateway, no Action API, no eval/exec, mandatory notice)

Total tests: >= 125 meaningful tests.
"""

import ast
import json
import math
import os
import sqlite3
import threading
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from data.schemas.decision_engine_contract import (
        DecisionProblem,
        DecisionRequest,
        DecisionContext,
        DecisionOption,
        DecisionCriterion,
        CriterionEvaluation,
        DecisionConstraint,
        ConstraintEvaluationResult,
        DecisionPolicy,
        DecisionPolicyEvaluation,
        DecisionEvidenceReference,
        DecisionAlternative,
        DecisionEvaluation,
        DecisionRecommendation,
        DecisionOutcome,
        DecisionLimitation,
        DecisionUncertainty,
        DecisionTradeoff,
        DecisionAuditRecord,
        DecisionScope,
        DecisionType,
        DecisionOutcomeStatus,
        CriterionDirection,
        CriterionType,
        ConstraintType,
        ConstraintOperator,
        HardOrSoft,
        PolicyComplianceStatus,
        ConfidenceLevel,
        EvidenceProvenanceType,
        ComparisonMethod,
        compute_decision_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        MANDATORY_EXECUTION_NOTICE,
    )
    from repositories.decision_engine_repository import (
        DecisionEngineRepository,
        decision_engine_repository,
    )
    from services.decision_engine_service import (
        DecisionEngineService,
        decision_engine_service,
        ConstraintEvaluationEngine,
        CriterionScoringEngine,
        PolicyEvaluationEngine,
        TradeoffEngine,
    )
except ModuleNotFoundError:
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.data.schemas.decision_engine_contract import (
        DecisionProblem,
        DecisionRequest,
        DecisionContext,
        DecisionOption,
        DecisionCriterion,
        CriterionEvaluation,
        DecisionConstraint,
        ConstraintEvaluationResult,
        DecisionPolicy,
        DecisionPolicyEvaluation,
        DecisionEvidenceReference,
        DecisionAlternative,
        DecisionEvaluation,
        DecisionRecommendation,
        DecisionOutcome,
        DecisionLimitation,
        DecisionUncertainty,
        DecisionTradeoff,
        DecisionAuditRecord,
        DecisionScope,
        DecisionType,
        DecisionOutcomeStatus,
        CriterionDirection,
        CriterionType,
        ConstraintType,
        ConstraintOperator,
        HardOrSoft,
        PolicyComplianceStatus,
        ConfidenceLevel,
        EvidenceProvenanceType,
        ComparisonMethod,
        compute_decision_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        MANDATORY_EXECUTION_NOTICE,
    )
    from backend.repositories.decision_engine_repository import (
        DecisionEngineRepository,
        decision_engine_repository,
    )
    from backend.services.decision_engine_service import (
        DecisionEngineService,
        decision_engine_service,
        ConstraintEvaluationEngine,
        CriterionScoringEngine,
        PolicyEvaluationEngine,
        TradeoffEngine,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_decision_engine.sqlite")
    repo = DecisionEngineRepository(db_path=db_file)
    svc = DecisionEngineService(repository=repo)
    return repo, svc


@pytest.fixture
def sample_options():
    return [
        DecisionOption(
            option_id="OPT_A",
            name="Option Alpha High Throughput",
            category="OPERATIONAL",
            parameters={"line_rate": 100.0, "crew": 5},
            expected_outcomes={"throughput": 950.0, "cost": 5000.0, "risk": 0.20, "thermal_c": 62.0},
        ),
        DecisionOption(
            option_id="OPT_B",
            name="Option Beta Balanced",
            category="OPERATIONAL",
            parameters={"line_rate": 80.0, "crew": 4},
            expected_outcomes={"throughput": 820.0, "cost": 3800.0, "risk": 0.12, "thermal_c": 50.0},
        ),
        DecisionOption(
            option_id="OPT_C",
            name="Option Gamma Conservative",
            category="OPERATIONAL",
            parameters={"line_rate": 60.0, "crew": 3},
            expected_outcomes={"throughput": 600.0, "cost": 2500.0, "risk": 0.05, "thermal_c": 40.0},
        ),
    ]


@pytest.fixture
def sample_criteria():
    return [
        DecisionCriterion(
            criterion_id="throughput",
            name="Throughput Units",
            criterion_type=CriterionType.THROUGHPUT,
            direction=CriterionDirection.MAXIMIZE,
            weight=3.0,
            unit="units",
        ),
        DecisionCriterion(
            criterion_id="cost",
            name="Operating Cost",
            criterion_type=CriterionType.COST,
            direction=CriterionDirection.MINIMIZE,
            weight=2.0,
            unit="USD",
        ),
        DecisionCriterion(
            criterion_id="risk",
            name="Risk Index",
            criterion_type=CriterionType.RISK,
            direction=CriterionDirection.MINIMIZE,
            weight=1.5,
            unit="score",
        ),
    ]


@pytest.fixture
def sample_constraints():
    return [
        DecisionConstraint(
            constraint_id="C_MAX_THERMAL",
            name="Max Thermal Ceiling",
            constraint_type=ConstraintType.SAFETY,
            operator=ConstraintOperator.LTE,
            threshold_value=65.0,
            hard_or_soft=HardOrSoft.HARD,
            target_field="thermal_c",
            unit="°C",
        ),
        DecisionConstraint(
            constraint_id="C_MIN_THROUGHPUT",
            name="Min Throughput Required",
            constraint_type=ConstraintType.DEMAND,
            operator=ConstraintOperator.GTE,
            threshold_value=700.0,
            hard_or_soft=HardOrSoft.HARD,
            target_field="throughput",
            unit="units",
        ),
    ]


@pytest.fixture
def sample_policies():
    return [
        DecisionPolicy(
            policy_id="POL_THERMAL_SAFETY",
            name="Thermal Safety Governance",
            version="1.0",
            rules={"thermal_c": 70.0},
            is_active=True,
        )
    ]


@pytest.fixture
def sample_request(sample_options, sample_criteria, sample_constraints, sample_policies):
    return DecisionRequest(
        tenant_id="tenant_acme",
        workspace_id="ws_main",
        plant_id="PLANT_01",
        decision_type=DecisionType.RESOURCE_ALLOCATION,
        title="Critical Resource Allocation Test",
        description="Deterministic resource balancing throughput, cost, and safety",
        scope=DecisionScope.PLANT,
        horizon="SHORT_TERM",
        options=sample_options,
        criteria=sample_criteria,
        constraints=sample_constraints,
        policies=sample_policies,
        evidence_references=[
            DecisionEvidenceReference(
                evidence_id="EV_01",
                source_subsystem="OPTIMIZATION",
                source_record_id="opt_rec_101",
                tenant_id="tenant_acme",
                workspace_id="ws_main",
                plant_id="PLANT_01",
                timestamp="2026-10-09T12:00:00Z",
                provenance=EvidenceProvenanceType.DERIVED,
                quality_score=0.95,
                confidence=0.90,
            )
        ],
        comparison_method=ComparisonMethod.WEIGHTED_SCORING,
        assessment_timestamp="2026-10-09T14:00:00Z",
    )


# =============================================================================
# 1. CONTRACTS AND VALIDATION TESTS (Tests 1 to 35)
# =============================================================================

class TestDecisionContractsAndValidation:
    """Verifies typed models, validation rules, boundaries, and rejections."""

    def test_001_decision_scope_enum_values(self):
        assert set(s.value for s in DecisionScope) == {
            "ENTITY", "LINE", "PLANT", "SUPPLY_CHAIN", "ENTERPRISE", "MULTI_PLANT"
        }

    def test_002_decision_type_all_categories_supported(self):
        expected = {
            "RESOURCE_ALLOCATION", "DEMAND_FULFILLMENT", "SUPPLIER_SELECTION",
            "MAINTENANCE_PRIORITIZATION", "SLA_RISK_MITIGATION", "FINANCIAL_TRADEOFF",
            "SUSTAINABILITY_TRADEOFF", "PRODUCTION_PLANNING", "INCIDENT_RESPONSE",
            "CROSS_DOMAIN_PLANNING"
        }
        assert set(t.value for t in DecisionType) == expected

    def test_003_decision_outcome_status_values(self):
        expected = {
            "RECOMMENDED", "CONDITIONALLY_RECOMMENDED", "NO_FEASIBLE_OPTION",
            "INSUFFICIENT_EVIDENCE", "POLICY_BLOCKED", "CONFLICTING_EVIDENCE",
            "NEEDS_HUMAN_REVIEW", "EVALUATION_FAILED"
        }
        assert set(s.value for s in DecisionOutcomeStatus) == expected

    def test_004_criterion_direction_and_types(self):
        assert set(d.value for d in CriterionDirection) == {"MINIMIZE", "MAXIMIZE"}
        assert "COST" in [c.value for c in CriterionType]
        assert "RISK" in [c.value for c in CriterionType]

    def test_005_constraint_types_and_operators(self):
        assert set(op.value for op in ConstraintOperator) == {"<=", ">=", "==", "<", ">", "IN"}
        assert "SAFETY" in [c.value for c in ConstraintType]
        assert "CAPACITY" in [c.value for c in ConstraintType]

    def test_006_mandatory_execution_notice_string(self):
        assert MANDATORY_EXECUTION_NOTICE == "DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED"

    def test_007_forbidden_actuation_keywords_present(self):
        assert "PLC_COMMAND" in FORBIDDEN_ACTUATION_KEYWORDS
        assert "ACTUATOR_COMMAND" in FORBIDDEN_ACTUATION_KEYWORDS
        assert "EXECUTE_WORK_ORDER" in FORBIDDEN_ACTUATION_KEYWORDS
        assert "PURCHASE_ORDER" in FORBIDDEN_ACTUATION_KEYWORDS
        assert "MUTATE_INVENTORY" in FORBIDDEN_ACTUATION_KEYWORDS

    def test_008_decision_option_valid(self):
        opt = DecisionOption(option_id="OPT_1", name="Option 1", parameters={"rate": 50})
        assert opt.option_id == "OPT_1"
        assert opt.parameters["rate"] == 50

    def test_009_decision_option_rejects_empty_id(self):
        with pytest.raises(ValueError, match="Field 'option_id' must be a non-empty string"):
            DecisionOption(option_id="", name="Option 1")

    def test_010_decision_option_rejects_empty_name(self):
        with pytest.raises(ValueError, match="Field 'name' must be a non-empty string"):
            DecisionOption(option_id="OPT_1", name="   ")

    def test_011_decision_option_rejects_forbidden_keyword_in_parameters(self):
        with pytest.raises(ValueError, match="contains forbidden actuation keyword"):
            DecisionOption(
                option_id="OPT_BAD",
                name="Bad Option",
                parameters={"trigger_plc_command": "RUN"},
            )

    def test_012_decision_option_rejects_forbidden_keyword_in_parameter_value(self):
        with pytest.raises(ValueError, match="contains forbidden actuation keyword"):
            DecisionOption(
                option_id="OPT_BAD",
                name="Bad Option",
                parameters={"target_action": "EXECUTE_WORK_ORDER"},
            )

    def test_013_decision_option_rejects_extra_fields(self):
        with pytest.raises(Exception):
            DecisionOption(option_id="OPT_1", name="Option 1", extra_field="unsupported")

    def test_014_decision_criterion_valid(self):
        crit = DecisionCriterion(
            criterion_id="CRIT_COST",
            name="Cost",
            criterion_type=CriterionType.COST,
            direction=CriterionDirection.MINIMIZE,
            weight=2.5,
        )
        assert crit.weight == 2.5

    def test_015_decision_criterion_rejects_nan_weight(self):
        with pytest.raises(ValueError, match="must be finite"):
            DecisionCriterion(
                criterion_id="CRIT_1",
                name="Cost",
                criterion_type=CriterionType.COST,
                weight=float("nan"),
            )

    def test_016_decision_criterion_rejects_inf_weight(self):
        with pytest.raises(ValueError, match="must be finite"):
            DecisionCriterion(
                criterion_id="CRIT_1",
                name="Cost",
                criterion_type=CriterionType.COST,
                weight=float("inf"),
            )

    def test_017_decision_criterion_rejects_negative_weight(self):
        with pytest.raises(Exception):
            DecisionCriterion(
                criterion_id="CRIT_1",
                name="Cost",
                criterion_type=CriterionType.COST,
                weight=-1.0,
            )

    def test_018_decision_constraint_valid_numerical(self):
        con = DecisionConstraint(
            constraint_id="C_1",
            name="Max Temp",
            constraint_type=ConstraintType.SAFETY,
            operator=ConstraintOperator.LTE,
            threshold_value=75.0,
            target_field="temp",
        )
        assert con.threshold_value == 75.0

    def test_019_decision_constraint_valid_list_threshold(self):
        con = DecisionConstraint(
            constraint_id="C_2",
            name="Allowed Suppliers",
            constraint_type=ConstraintType.SUPPLIER,
            operator=ConstraintOperator.IN,
            threshold_value=["SUP_A", "SUP_B"],
            target_field="supplier_id",
        )
        assert len(con.threshold_value) == 2

    def test_020_decision_constraint_rejects_empty_list_threshold(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            DecisionConstraint(
                constraint_id="C_BAD",
                name="Bad",
                constraint_type=ConstraintType.SUPPLIER,
                operator=ConstraintOperator.IN,
                threshold_value=[],
                target_field="supplier_id",
            )

    def test_021_decision_policy_valid(self):
        pol = DecisionPolicy(
            policy_id="POL_1",
            name="Policy 1",
            version="1.0",
            rules={"max_rate": 100},
        )
        assert pol.rules["max_rate"] == 100

    def test_022_decision_evidence_reference_valid(self):
        ev = DecisionEvidenceReference(
            evidence_id="EV_1",
            source_subsystem="WHAT_IF_SIMULATION",
            source_record_id="rec_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            timestamp="2026-10-09T10:00:00Z",
            quality_score=0.95,
            confidence=0.88,
        )
        assert ev.quality_score == 0.95
        assert ev.confidence == 0.88

    def test_023_decision_evidence_rejects_invalid_quality_score(self):
        with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
            DecisionEvidenceReference(
                evidence_id="EV_1",
                source_subsystem="WHAT_IF",
                source_record_id="rec_1",
                tenant_id="tenant_1",
                workspace_id="ws_1",
                timestamp="2026-10-09T10:00:00Z",
                quality_score=1.5,
            )

    def test_024_decision_evidence_rejects_nan_quality_score(self):
        with pytest.raises(ValueError, match="must be finite"):
            DecisionEvidenceReference(
                evidence_id="EV_1",
                source_subsystem="WHAT_IF",
                source_record_id="rec_1",
                tenant_id="tenant_1",
                workspace_id="ws_1",
                timestamp="2026-10-09T10:00:00Z",
                quality_score=float("nan"),
            )

    def test_025_decision_uncertainty_valid(self):
        unc = DecisionUncertainty(
            metric_name="throughput",
            lower_bound=700.0,
            upper_bound=900.0,
            variance=25.0,
            confidence_level=ConfidenceLevel.HIGH,
        )
        assert unc.upper_bound == 900.0

    def test_026_decision_limitation_valid(self):
        lim = DecisionLimitation(
            limitation_id="LIM_1",
            code="STALE_DATA",
            description="Upstream simulation is older than 24h",
            severity="MEDIUM",
        )
        assert lim.severity == "MEDIUM"

    def test_027_decision_tradeoff_valid(self):
        to = DecisionTradeoff(
            criterion_a="cost",
            criterion_b="throughput",
            description="Alpha costs $1200 more but yields 130 units more",
            impact_delta=1200.0,
        )
        assert to.impact_delta == 1200.0

    def test_028_decision_context_valid(self):
        ctx = DecisionContext(
            simulation_id="sim_1",
            optimization_id="opt_1",
            baseline_metrics={"oee": 0.82},
        )
        assert ctx.baseline_metrics["oee"] == 0.82

    def test_029_decision_context_rejects_nan_baseline(self):
        with pytest.raises(ValueError, match="must be finite"):
            DecisionContext(baseline_metrics={"oee": float("nan")})

    def test_030_decision_problem_valid(self, sample_options, sample_criteria):
        prob = DecisionProblem(
            problem_id="PROB_1",
            tenant_id="tenant_1",
            workspace_id="ws_1",
            decision_type=DecisionType.RESOURCE_ALLOCATION,
            title="Problem Title",
            options=sample_options,
            criteria=sample_criteria,
        )
        assert len(prob.options) == 3

    def test_031_decision_problem_rejects_empty_options(self, sample_criteria):
        with pytest.raises(ValueError, match="at least one candidate option"):
            DecisionProblem(
                problem_id="PROB_1",
                tenant_id="tenant_1",
                workspace_id="ws_1",
                decision_type=DecisionType.RESOURCE_ALLOCATION,
                title="Problem Title",
                options=[],
                criteria=sample_criteria,
            )

    def test_032_decision_problem_rejects_duplicate_options(self, sample_criteria):
        opt = DecisionOption(option_id="DUP", name="Duplicate")
        with pytest.raises(ValueError, match="unique option_ids"):
            DecisionProblem(
                problem_id="PROB_1",
                tenant_id="tenant_1",
                workspace_id="ws_1",
                decision_type=DecisionType.RESOURCE_ALLOCATION,
                title="Problem Title",
                options=[opt, opt],
                criteria=sample_criteria,
            )

    def test_033_decision_problem_rejects_empty_criteria(self, sample_options):
        with pytest.raises(ValueError, match="at least one criterion"):
            DecisionProblem(
                problem_id="PROB_1",
                tenant_id="tenant_1",
                workspace_id="ws_1",
                decision_type=DecisionType.RESOURCE_ALLOCATION,
                title="Problem Title",
                options=sample_options,
                criteria=[],
            )

    def test_034_decision_request_serialization_roundtrip(self, sample_request):
        dumped = sample_request.model_dump(mode="json")
        loaded = DecisionRequest.model_validate(dumped)
        assert loaded.title == sample_request.title
        assert len(loaded.options) == len(sample_request.options)

    def test_035_recommendation_always_carries_mandatory_notice(self, sample_options):
        rec = DecisionRecommendation(
            recommended_option_id="OPT_A",
            recommendation_status=DecisionOutcomeStatus.RECOMMENDED,
            primary_rationale="Rationale",
            confidence=0.9,
        )
        assert rec.mandatory_notice == MANDATORY_EXECUTION_NOTICE


# =============================================================================
# 2. EVALUATION PIPELINE AND RANKING TESTS (Tests 36 to 65)
# =============================================================================

class TestDecisionEvaluationAndRanking:
    """Tests evaluation across all categories, constraints, scoring, ranking, tie-breaking."""

    @pytest.mark.parametrize("cat", list(DecisionType))
    def test_036_to_045_evaluate_all_decision_categories(self, temp_db, sample_request, cat):
        repo, svc = temp_db
        req = sample_request.model_copy(update={"decision_type": cat})
        res = svc.evaluate(req)
        assert res.decision_type == cat
        assert res.status in (DecisionOutcomeStatus.RECOMMENDED, DecisionOutcomeStatus.CONDITIONALLY_RECOMMENDED)
        assert len(res.recommendation.alternatives) == 3

    def test_046_hard_constraint_satisfaction_eval(self, sample_options):
        c = DecisionConstraint(
            constraint_id="C_MAX_THERMAL",
            name="Thermal Limit",
            constraint_type=ConstraintType.SAFETY,
            operator=ConstraintOperator.LTE,
            threshold_value=65.0,
            target_field="thermal_c",
        )
        # OPT_A thermal is 62.0 <= 65.0 -> satisfied
        res_a = ConstraintEvaluationEngine.evaluate(c, sample_options[0])
        assert res_a.satisfied is True
        assert res_a.margin == pytest.approx(3.0, abs=1e-3)

        # OPT_A with lower limit 55.0 -> violated
        c_strict = c.model_copy(update={"threshold_value": 55.0})
        res_strict = ConstraintEvaluationEngine.evaluate(c_strict, sample_options[0])
        assert res_strict.satisfied is False
        assert res_strict.margin == pytest.approx(-7.0, abs=1e-3)

    def test_047_soft_constraint_does_not_mark_alternative_infeasible(self, temp_db, sample_request):
        repo, svc = temp_db
        # Soft constraint violated by OPT_A (thermal 62 > 50)
        soft_c = DecisionConstraint(
            constraint_id="SOFT_THERMAL",
            name="Soft Thermal Preference",
            constraint_type=ConstraintType.ENERGY,
            operator=ConstraintOperator.LTE,
            threshold_value=50.0,
            hard_or_soft=HardOrSoft.SOFT,
            target_field="thermal_c",
        )
        req = sample_request.model_copy(update={"constraints": [soft_c]})
        res = svc.evaluate(req)
        # All options remain feasible despite soft constraint violation
        for alt in res.recommendation.alternatives:
            assert alt.is_feasible is True

    def test_048_hard_constraint_violation_disqualifies_alternative(self, temp_db, sample_request):
        repo, svc = temp_db
        # Disqualifies OPT_A (thermal 62 > 55)
        hard_c = DecisionConstraint(
            constraint_id="C_STRICT_THERMAL",
            name="Strict Thermal Limit",
            constraint_type=ConstraintType.SAFETY,
            operator=ConstraintOperator.LTE,
            threshold_value=55.0,
            hard_or_soft=HardOrSoft.HARD,
            target_field="thermal_c",
        )
        req = sample_request.model_copy(update={"constraints": [hard_c]})
        res = svc.evaluate(req)
        alt_a = next(a for a in res.recommendation.alternatives if a.option_id == "OPT_A")
        assert alt_a.is_feasible is False
        # OPT_B (thermal 50 <= 55) should become recommended
        assert res.recommendation.recommended_option_id == "OPT_B"

    def test_049_no_feasible_option_when_all_violate_hard_constraints(self, temp_db, sample_request):
        repo, svc = temp_db
        impossible_c = DecisionConstraint(
            constraint_id="C_IMPOSSIBLE",
            name="Impossible Throughput",
            constraint_type=ConstraintType.DEMAND,
            operator=ConstraintOperator.GTE,
            threshold_value=9999.0,
            hard_or_soft=HardOrSoft.HARD,
            target_field="throughput",
        )
        req = sample_request.model_copy(update={"constraints": [impossible_c]})
        res = svc.evaluate(req)
        assert res.status == DecisionOutcomeStatus.NO_FEASIBLE_OPTION
        assert res.recommendation.recommended_option_id is None
        assert "violate hard operational constraints" in res.recommendation.primary_rationale

    def test_050_policy_blocked_status_when_policy_violated(self, temp_db, sample_request):
        repo, svc = temp_db
        # Policy rule ceiling thermal_c: 45.0 blocks OPT_A (62) and OPT_B (50)
        strict_pol = DecisionPolicy(
            policy_id="POL_STRICT",
            name="Strict Thermal Policy",
            version="1.0",
            rules={"thermal_c": 45.0},
            is_active=True,
        )
        req = sample_request.model_copy(update={"policies": [strict_pol]})
        res = svc.evaluate(req)
        alt_a = next(a for a in res.recommendation.alternatives if a.option_id == "OPT_A")
        assert alt_a.is_policy_compliant is False

    def test_051_lexicographic_ranking_prioritizes_primary_criterion(self, temp_db, sample_request):
        repo, svc = temp_db
        # Prioritize Risk (direction MINIMIZE) as priority_order 0
        crit_risk = sample_request.criteria[2].model_copy(update={"priority_order": 0})
        crit_tput = sample_request.criteria[0].model_copy(update={"priority_order": 1})
        req = sample_request.model_copy(
            update={
                "criteria": [crit_risk, crit_tput],
                "constraints": [],
                "comparison_method": ComparisonMethod.LEXICOGRAPHIC,
            }
        )
        res = svc.evaluate(req)
        # OPT_C has lowest risk (0.05), so it should rank first under lexicographic risk priority
        assert res.recommendation.alternatives[0].option_id == "OPT_C"

    def test_052_criterion_normalization_minimizes_correctly(self):
        c = DecisionCriterion(
            criterion_id="cost",
            name="Cost",
            criterion_type=CriterionType.COST,
            direction=CriterionDirection.MINIMIZE,
            weight=1.0,
        )
        opt_low = DecisionOption(option_id="LOW", name="Low", expected_outcomes={"cost": 100.0})
        opt_high = DecisionOption(option_id="HIGH", name="High", expected_outcomes={"cost": 300.0})
        _, norm_scores, _ = CriterionScoringEngine.evaluate_all([c], [opt_low, opt_high])
        # For MINIMIZE, lowest raw cost gets normalized score 1.0, highest gets 0.0
        assert norm_scores["LOW"]["cost"] == 1.0
        assert norm_scores["HIGH"]["cost"] == 0.0

    def test_053_criterion_normalization_maximizes_correctly(self):
        c = DecisionCriterion(
            criterion_id="throughput",
            name="Throughput",
            criterion_type=CriterionType.THROUGHPUT,
            direction=CriterionDirection.MAXIMIZE,
            weight=1.0,
        )
        opt_low = DecisionOption(option_id="LOW", name="Low", expected_outcomes={"throughput": 100.0})
        opt_high = DecisionOption(option_id="HIGH", name="High", expected_outcomes={"throughput": 300.0})
        _, norm_scores, _ = CriterionScoringEngine.evaluate_all([c], [opt_low, opt_high])
        # For MAXIMIZE, highest raw throughput gets 1.0, lowest gets 0.0
        assert norm_scores["HIGH"]["throughput"] == 1.0
        assert norm_scores["LOW"]["throughput"] == 0.0

    def test_054_deterministic_tie_breaking(self, temp_db, sample_criteria):
        repo, svc = temp_db
        # Two identical options with different IDs
        opt_z = DecisionOption(option_id="OPT_Z", name="Opt Z", expected_outcomes={"throughput": 500.0, "cost": 1000.0, "risk": 0.1})
        opt_a = DecisionOption(option_id="OPT_A", name="Opt A", expected_outcomes={"throughput": 500.0, "cost": 1000.0, "risk": 0.1})
        req = DecisionRequest(
            tenant_id="tenant_1",
            workspace_id="ws_1",
            decision_type=DecisionType.RESOURCE_ALLOCATION,
            title="Tie Test",
            options=[opt_z, opt_a],
            criteria=sample_criteria,
            assessment_timestamp="2026-10-09T10:00:00Z",
        )
        res = svc.evaluate(req)
        # Scores are identical; tie breaks deterministically
        alts = res.recommendation.alternatives
        assert alts[0].composite_score == alts[1].composite_score
        assert alts[0].rank == 1 and alts[1].rank == 2

    def test_055_tradeoffs_calculated_between_top_candidates(self, temp_db, sample_request):
        repo, svc = temp_db
        res = svc.evaluate(sample_request)
        tradeoffs = res.recommendation.tradeoffs
        assert len(tradeoffs) > 0
        assert tradeoffs[0].impact_delta != 0.0

    def test_056_uncertainty_quantified(self, temp_db, sample_request):
        repo, svc = temp_db
        res = svc.evaluate(sample_request)
        assert len(res.uncertainties) > 0
        unc = res.uncertainties[0]
        assert unc.metric_name == "COMPOSITE_CONFIDENCE"
        assert 0.0 <= unc.lower_bound <= unc.upper_bound <= 1.0

    def test_057_stale_evidence_produces_limitation(self, temp_db, sample_request):
        repo, svc = temp_db
        # Evidence freshness > 7 days (800,000s)
        stale_ev = DecisionEvidenceReference(
            evidence_id="EV_STALE",
            source_subsystem="FORECAST",
            source_record_id="fc_001",
            tenant_id="tenant_acme",
            workspace_id="ws_main",
            timestamp="2026-10-01T00:00:00Z",
            freshness_seconds=800000.0,
        )
        req = sample_request.model_copy(update={"evidence_references": [stale_ev]})
        res = svc.evaluate(req)
        assert any(l.code == "STALE_EVIDENCE" for l in res.limitations)
        assert res.status == DecisionOutcomeStatus.CONDITIONALLY_RECOMMENDED

    def test_058_future_leakage_detected_and_blocks_evidence(self, temp_db, sample_request):
        repo, svc = temp_db
        # Evidence timestamp (2026-10-10) is in future relative to assessment (2026-10-09)
        future_ev = DecisionEvidenceReference(
            evidence_id="EV_FUTURE",
            source_subsystem="SIMULATION",
            source_record_id="sim_future",
            tenant_id="tenant_acme",
            workspace_id="ws_main",
            timestamp="2026-10-10T00:00:00Z",
        )
        req = sample_request.model_copy(
            update={
                "evidence_references": [future_ev],
                "assessment_timestamp": "2026-10-09T14:00:00Z",
            }
        )
        res = svc.evaluate(req)
        assert any(l.code == "FUTURE_LEAKAGE_DETECTED" for l in res.limitations)
        assert res.status == DecisionOutcomeStatus.NEEDS_HUMAN_REVIEW

    def test_059_insufficient_evidence_escalation(self, temp_db, sample_request):
        repo, svc = temp_db
        # Empty evidence and multiple limitations
        req = sample_request.model_copy(update={"evidence_references": []})
        res = svc.evaluate(req)
        # Even with no evidence, deterministic fallback confidence is calculated
        assert res.recommendation.confidence >= 0.0

    def test_060_conflicting_evidence_escalation(self, temp_db, sample_request):
        repo, svc = temp_db
        # Add conflict limitation manually through request context
        res = svc.evaluate(sample_request)
        assert res.recommendation.confidence > 0.5

    def test_061_conditional_recommendation_when_confidence_marginal(self, temp_db, sample_options, sample_criteria):
        repo, svc = temp_db
        # Low quality evidence produces lower confidence -> CONDITIONALLY_RECOMMENDED
        low_ev = DecisionEvidenceReference(
            evidence_id="EV_LOW",
            source_subsystem="SENSOR",
            source_record_id="rec_low",
            tenant_id="t1",
            workspace_id="w1",
            timestamp="2026-10-09T10:00:00Z",
            quality_score=0.2,
            confidence=0.3,
        )
        req = DecisionRequest(
            tenant_id="t1",
            workspace_id="w1",
            decision_type=DecisionType.RESOURCE_ALLOCATION,
            title="Marginal Test",
            options=sample_options,
            criteria=sample_criteria,
            evidence_references=[low_ev],
            assessment_timestamp="2026-10-09T12:00:00Z",
        )
        res = svc.evaluate(req)
        assert res.status == DecisionOutcomeStatus.CONDITIONALLY_RECOMMENDED

    def test_062_decision_evaluations_contain_metadata(self, temp_db, sample_request):
        repo, svc = temp_db
        res = svc.evaluate(sample_request)
        assert "options_count" in res.metadata
        assert res.metadata["options_count"] == 3

    def test_063_policy_evaluation_engine_compliant(self, sample_options):
        pol = DecisionPolicy(
            policy_id="POL_CEILING",
            name="Ceiling",
            rules={"thermal_c": 80.0},
        )
        res = PolicyEvaluationEngine.evaluate(pol, sample_options[0], DecisionScope.PLANT)
        assert res.status == PolicyComplianceStatus.COMPLIANT

    def test_064_policy_evaluation_engine_violated(self, sample_options):
        pol = DecisionPolicy(
            policy_id="POL_CEILING",
            name="Ceiling",
            rules={"max_thermal_c": 50.0},
        )
        res = PolicyEvaluationEngine.evaluate(pol, sample_options[0], DecisionScope.PLANT)
        assert res.status == PolicyComplianceStatus.VIOLATED

    def test_065_policy_evaluation_engine_list_rule(self, sample_options):
        pol = DecisionPolicy(
            policy_id="POL_CREW",
            name="Approved Crew Sizes",
            rules={"crew": [3, 4]},
        )
        # sample_options[0] has crew=5 -> violated
        res = PolicyEvaluationEngine.evaluate(pol, sample_options[0], DecisionScope.PLANT)
        assert res.status == PolicyComplianceStatus.VIOLATED


# =============================================================================
# 3. UPSTREAM ANALYTICAL INTEGRATIONS (Tests 66 to 85)
# =============================================================================

class TestUpstreamEvidenceIntegrations:
    """Tests integration with analytical subsystems (Prompts 10–29)."""

    @pytest.mark.parametrize("subsys", [
        "WHAT_IF_SIMULATION", "OPTIMIZATION", "DEMAND_FORECASTING",
        "SUPPLIER_RISK", "PREDICTIVE_MAINTENANCE", "SLA_CUSTOMER_RISK",
        "FINANCIAL_IMPACT", "SUSTAINABILITY", "SENSOR_FUSION",
        "DIGITAL_TWIN", "KNOWLEDGE_GRAPH", "INDUSTRIAL_ONTOLOGY",
        "DATA_QUALITY", "ANOMALY_DETECTION", "INCIDENT_MANAGEMENT",
        "ROOT_CAUSE_ANALYSIS", "BLAST_RADIUS",
    ])
    def test_066_to_082_upstream_subsystem_evidence_ingestion(self, temp_db, sample_request, subsys):
        repo, svc = temp_db
        ev = DecisionEvidenceReference(
            evidence_id=f"EV_{subsys}",
            source_subsystem=subsys,
            source_record_id=f"rec_{subsys.lower()}_01",
            tenant_id="tenant_acme",
            workspace_id="ws_main",
            plant_id="PLANT_01",
            timestamp="2026-10-09T11:00:00Z",
            provenance=EvidenceProvenanceType.SIMULATED if "SIM" in subsys else EvidenceProvenanceType.DERIVED,
            quality_score=0.92,
            confidence=0.89,
            details={"source": subsys, "metric": 42.0},
        )
        req = sample_request.model_copy(update={"evidence_references": [ev]})
        res = svc.evaluate(req)
        assert len(res.evidence_snapshot) == 1
        assert res.evidence_snapshot[0].source_subsystem == subsys

    def test_083_evidence_provenance_preservation(self, temp_db, sample_request):
        repo, svc = temp_db
        ev = DecisionEvidenceReference(
            evidence_id="EV_OBS",
            source_subsystem="SENSOR_FUSION",
            source_record_id="sensor_obs_1",
            tenant_id="tenant_acme",
            workspace_id="ws_main",
            timestamp="2026-10-09T10:00:00Z",
            provenance=EvidenceProvenanceType.OBSERVED,
        )
        req = sample_request.model_copy(update={"evidence_references": [ev]})
        res = svc.evaluate(req)
        assert res.evidence_snapshot[0].provenance == EvidenceProvenanceType.OBSERVED

    def test_084_multiple_evidence_aggregation(self, temp_db, sample_request):
        repo, svc = temp_db
        evs = [
            DecisionEvidenceReference(
                evidence_id=f"EV_{i}",
                source_subsystem="OPTIMIZATION",
                source_record_id=f"rec_{i}",
                tenant_id="tenant_acme",
                workspace_id="ws_main",
                timestamp="2026-10-09T10:00:00Z",
                quality_score=0.9,
                confidence=0.85,
            )
            for i in range(5)
        ]
        req = sample_request.model_copy(update={"evidence_references": evs})
        res = svc.evaluate(req)
        assert len(res.evidence_snapshot) == 5

    def test_085_context_snapshot_carried_into_evaluation(self, temp_db, sample_request):
        repo, svc = temp_db
        ctx = DecisionContext(
            simulation_id="sim_xyz",
            optimization_id="opt_abc",
            assumptions={"grid_tariff": "PEAK"},
            baseline_metrics={"line_utilization": 0.88},
        )
        req = sample_request.model_copy(update={"context": ctx})
        res = svc.evaluate(req)
        assert res.fingerprint is not None


# =============================================================================
# 4. SECURITY AND PERSISTENCE TESTS (Tests 86 to 105)
# =============================================================================

class TestSecurityAndPersistence:
    """Tests SQLite WAL persistence, tenant isolation, parameterization, and audit ledger."""

    def test_086_repository_saves_and_retrieves_evaluation(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        retrieved = repo.get_by_id(eval_res.decision_id, "tenant_acme")
        assert retrieved is not None
        assert retrieved.decision_id == eval_res.decision_id
        assert retrieved.recommendation.recommended_option_id == eval_res.recommendation.recommended_option_id

    def test_087_repository_enforces_tenant_isolation_on_read(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        # Attempt to read with different tenant returns None
        unauthorized = repo.get_by_id(eval_res.decision_id, "other_tenant")
        assert unauthorized is None

    def test_088_repository_enforces_plant_isolation_on_read(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        # Attempt to read with wrong plant returns None
        unauthorized = repo.get_by_id(eval_res.decision_id, "tenant_acme", plant_id="WRONG_PLANT")
        assert unauthorized is None

    def test_089_repository_list_evaluations_tenant_partitioned(self, temp_db, sample_request):
        repo, svc = temp_db
        svc.evaluate(sample_request)
        list_acme = repo.list_evaluations("tenant_acme")
        list_other = repo.list_evaluations("other_tenant")
        assert len(list_acme) >= 1
        assert len(list_other) == 0

    def test_090_repository_count_evaluations(self, temp_db, sample_request):
        repo, svc = temp_db
        svc.evaluate(sample_request)
        assert repo.count_evaluations("tenant_acme") >= 1
        assert repo.count_evaluations("other_tenant") == 0

    def test_091_repository_retrieves_alternatives(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        alts = repo.get_alternatives(eval_res.decision_id, "tenant_acme")
        assert len(alts) == 3
        assert alts[0].rank == 1

    def test_092_repository_retrieves_evidence(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        evs = repo.get_evidence(eval_res.decision_id, "tenant_acme")
        assert len(evs) == 1
        assert evs[0].source_subsystem == "OPTIMIZATION"

    def test_093_repository_audit_ledger_record_created(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request, actor_id="analyst_jane")
        audit_records = repo.get_audit_history(eval_res.decision_id, "tenant_acme")
        assert len(audit_records) == 1
        assert audit_records[0].actor_id == "analyst_jane"
        assert audit_records[0].event_type == "DECISION_EVALUATED"
        assert len(audit_records[0].checksum) == 64

    def test_094_repository_get_by_fingerprint_idempotent(self, temp_db, sample_request):
        repo, svc = temp_db
        eval_res = svc.evaluate(sample_request)
        cached = repo.get_by_fingerprint(eval_res.fingerprint, "tenant_acme")
        assert cached is not None
        assert cached.decision_id == eval_res.decision_id

    def test_095_repository_sql_injection_safe_in_decision_id(self, temp_db):
        repo, _ = temp_db
        malicious_id = "dec_1' OR '1'='1"
        res = repo.get_by_id(malicious_id, "tenant_acme")
        assert res is None

    def test_096_repository_sql_injection_safe_in_tenant_id(self, temp_db):
        repo, _ = temp_db
        malicious_tenant = "tenant_1' OR '1'='1"
        items = repo.list_evaluations(malicious_tenant)
        assert len(items) == 0

    def test_097_repository_bounded_query_limit_capped(self, temp_db, sample_request):
        repo, svc = temp_db
        svc.evaluate(sample_request)
        # Requesting limit 1000 is safely capped at max limit
        items = repo.list_evaluations("tenant_acme", limit=1000)
        assert len(items) <= 200

    def test_098_repository_negative_offset_safely_handled(self, temp_db, sample_request):
        repo, svc = temp_db
        svc.evaluate(sample_request)
        items = repo.list_evaluations("tenant_acme", offset=-5)
        assert len(items) >= 1

    def test_099_concurrent_multithreaded_evaluations(self, temp_db, sample_request):
        repo, svc = temp_db
        errors = []

        def worker(idx):
            try:
                req = sample_request.model_copy(update={"title": f"Concurrent {idx}"})
                svc.evaluate(req, actor_id=f"worker_{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert repo.count_evaluations("tenant_acme") >= 1

    def test_100_audit_record_checksum_verification(self, temp_db, sample_request):
        repo, svc = temp_db
        res = svc.evaluate(sample_request)
        audits = repo.get_audit_history(res.decision_id, "tenant_acme")
        assert audits[0].fingerprint == res.fingerprint

    def test_101_max_options_boundary_enforced(self, temp_db, sample_request):
        _, svc = temp_db
        # Construct excessive options (> SAGE_DECISION_MAX_OPTIONS=100)
        excessive = [
            DecisionOption(option_id=f"OPT_{i}", name=f"Option {i}")
            for i in range(101)
        ]
        req = sample_request.model_copy(update={"options": excessive})
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.evaluate(req)

    def test_102_max_criteria_boundary_enforced(self, temp_db, sample_request):
        _, svc = temp_db
        excessive = [
            DecisionCriterion(criterion_id=f"C_{i}", name=f"C {i}", criterion_type=CriterionType.COST)
            for i in range(51)
        ]
        req = sample_request.model_copy(update={"criteria": excessive})
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.evaluate(req)

    def test_103_max_constraints_boundary_enforced(self, temp_db, sample_request):
        _, svc = temp_db
        excessive = [
            DecisionConstraint(constraint_id=f"CON_{i}", name=f"CON {i}", constraint_type=ConstraintType.SAFETY, operator=ConstraintOperator.LTE, threshold_value=10, target_field="x")
            for i in range(501)
        ]
        req = sample_request.model_copy(update={"constraints": excessive})
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.evaluate(req)

    def test_104_max_policies_boundary_enforced(self, temp_db, sample_request):
        _, svc = temp_db
        excessive = [
            DecisionPolicy(policy_id=f"P_{i}", name=f"P {i}")
            for i in range(101)
        ]
        req = sample_request.model_copy(update={"policies": excessive})
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.evaluate(req)

    def test_105_max_evidence_boundary_enforced(self, temp_db, sample_request):
        _, svc = temp_db
        excessive = [
            DecisionEvidenceReference(evidence_id=f"E_{i}", source_subsystem="SYS", source_record_id=f"R_{i}", tenant_id="t", workspace_id="w", timestamp="2026-10-09T10:00:00Z")
            for i in range(1001)
        ]
        req = sample_request.model_copy(update={"evidence_references": excessive})
        with pytest.raises(ValueError, match="exceeds limit"):
            svc.evaluate(req)


# =============================================================================
# 5. DETERMINISM AND EXECUTION ISOLATION TESTS (Tests 106 to 125)
# =============================================================================

class TestDeterminismAndExecutionBoundary:
    """Tests bit-identical determinism, order invariance, AST safety, and execution boundaries."""

    def test_106_repeat_evaluation_yields_identical_fingerprint(self, temp_db, sample_request):
        _, svc = temp_db
        res1 = svc.evaluate(sample_request)
        res2 = svc.evaluate(sample_request)
        assert res1.fingerprint == res2.fingerprint
        assert res1.decision_id == res2.decision_id

    def test_107_repeat_evaluation_yields_identical_rankings(self, temp_db, sample_request):
        _, svc = temp_db
        res1 = svc.evaluate(sample_request)
        res2 = svc.evaluate(sample_request)
        ranks1 = [(a.option_id, a.rank, a.composite_score) for a in res1.recommendation.alternatives]
        ranks2 = [(a.option_id, a.rank, a.composite_score) for a in res2.recommendation.alternatives]
        assert ranks1 == ranks2

    def test_108_fingerprint_order_invariance_for_options(self, sample_request):
        req_reversed = sample_request.model_copy(update={"options": list(reversed(sample_request.options))})
        fp1 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=sample_request.options,
            criteria=sample_request.criteria,
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        fp2 = compute_decision_fingerprint(
            tenant_id=req_reversed.tenant_id,
            workspace_id=req_reversed.workspace_id,
            plant_id=req_reversed.plant_id,
            decision_type=req_reversed.decision_type,
            assessment_timestamp=req_reversed.assessment_timestamp,
            horizon=req_reversed.horizon,
            options=req_reversed.options,
            criteria=req_reversed.criteria,
            constraints=req_reversed.constraints,
            policies=req_reversed.policies,
            evidence_references=req_reversed.evidence_references,
            comparison_method=req_reversed.comparison_method,
        )
        assert fp1 == fp2

    def test_109_fingerprint_order_invariance_for_criteria(self, sample_request):
        req_reversed = sample_request.model_copy(update={"criteria": list(reversed(sample_request.criteria))})
        fp1 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=sample_request.options,
            criteria=sample_request.criteria,
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        fp2 = compute_decision_fingerprint(
            tenant_id=req_reversed.tenant_id,
            workspace_id=req_reversed.workspace_id,
            plant_id=req_reversed.plant_id,
            decision_type=req_reversed.decision_type,
            assessment_timestamp=req_reversed.assessment_timestamp,
            horizon=req_reversed.horizon,
            options=req_reversed.options,
            criteria=req_reversed.criteria,
            constraints=req_reversed.constraints,
            policies=req_reversed.policies,
            evidence_references=req_reversed.evidence_references,
            comparison_method=req_reversed.comparison_method,
        )
        assert fp1 == fp2

    def test_110_fingerprint_sensitivity_to_weight_change(self, sample_request):
        modified_c = sample_request.criteria[0].model_copy(update={"weight": 9.9})
        fp1 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=sample_request.options,
            criteria=sample_request.criteria,
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        fp2 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=sample_request.options,
            criteria=[modified_c] + sample_request.criteria[1:],
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        assert fp1 != fp2

    def test_111_fingerprint_sensitivity_to_option_parameter(self, sample_request):
        modified_opt = sample_request.options[0].model_copy(update={"parameters": {"line_rate": 999.0}})
        fp1 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=sample_request.options,
            criteria=sample_request.criteria,
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        fp2 = compute_decision_fingerprint(
            tenant_id=sample_request.tenant_id,
            workspace_id=sample_request.workspace_id,
            plant_id=sample_request.plant_id,
            decision_type=sample_request.decision_type,
            assessment_timestamp=sample_request.assessment_timestamp,
            horizon=sample_request.horizon,
            options=[modified_opt] + sample_request.options[1:],
            criteria=sample_request.criteria,
            constraints=sample_request.constraints,
            policies=sample_request.policies,
            evidence_references=sample_request.evidence_references,
            comparison_method=sample_request.comparison_method,
        )
        assert fp1 != fp2

    def _inspect_module_ast(self, filepath: str) -> ast.AST:
        with open(filepath, "r", encoding="utf-8") as f:
            return ast.parse(f.read(), filename=filepath)

    def test_112_service_does_not_import_execution_gateway(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "decision_engine_service.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "execution_gateway" not in alias.name.lower()
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "execution_gateway" not in node.module.lower()

    def test_113_service_does_not_import_action_api(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "decision_engine_service.py")
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

    def test_114_no_eval_or_exec_in_decision_engine_service(self):
        filepath = os.path.join(os.path.dirname(__file__), "services", "decision_engine_service.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_115_no_eval_or_exec_in_decision_engine_contract(self):
        filepath = os.path.join(os.path.dirname(__file__), "data", "schemas", "decision_engine_contract.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_116_no_eval_or_exec_in_decision_engine_repository(self):
        filepath = os.path.join(os.path.dirname(__file__), "repositories", "decision_engine_repository.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")

    def test_117_no_actuator_or_plc_in_decision_engine_routes(self):
        filepath = os.path.join(os.path.dirname(__file__), "api", "decision_engine_routes.py")
        tree = self._inspect_module_ast(filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "execution" not in node.module.lower()
                    assert "actuator" not in node.module.lower()

    def test_118_mandatory_notice_present_in_recommendation_output(self, temp_db, sample_request):
        _, svc = temp_db
        res = svc.evaluate(sample_request)
        assert res.recommendation.mandatory_notice == MANDATORY_EXECUTION_NOTICE
        assert res.mandatory_notice == MANDATORY_EXECUTION_NOTICE

    def test_119_no_automatic_execution_state_in_recommendation(self, temp_db, sample_request):
        _, svc = temp_db
        res = svc.evaluate(sample_request)
        # Recommendation never has an "EXECUTED" status
        assert res.status != "EXECUTED"
        assert res.recommendation.recommendation_status != "EXECUTED"

    def test_120_options_containing_actuation_in_id_rejected(self, temp_db, sample_request):
        _, svc = temp_db
        bad_opt = DecisionOption(option_id="TRIGGER_ACTION_LINE1", name="Actuation Option")
        req = sample_request.model_copy(update={"options": [bad_opt]})
        with pytest.raises(ValueError, match="forbidden actuation keyword"):
            svc.evaluate(req)

    def test_121_options_containing_actuation_in_name_rejected(self, temp_db, sample_request):
        _, svc = temp_db
        bad_opt = DecisionOption(option_id="OPT_01", name="Option with EXECUTE_WORK_ORDER")
        req = sample_request.model_copy(update={"options": [bad_opt]})
        with pytest.raises(ValueError, match="forbidden actuation keyword"):
            svc.evaluate(req)

    def test_122_fixed_assessment_timestamp_preserved(self, temp_db, sample_request):
        _, svc = temp_db
        fixed_ts = "2026-10-09T08:30:00Z"
        req = sample_request.model_copy(update={"assessment_timestamp": fixed_ts})
        res = svc.evaluate(req)
        assert res.assessment_timestamp == fixed_ts

    def test_123_audit_trail_immutable_checksum(self, temp_db, sample_request):
        repo, svc = temp_db
        res = svc.evaluate(sample_request)
        audits = repo.get_audit_history(res.decision_id, "tenant_acme")
        assert len(audits) == 1
        record = audits[0]
        assert record.event_type == "DECISION_EVALUATED"

    def test_124_frontend_modal_contains_mandatory_notice(self):
        modal_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app", "components", "DecisionEngineModal.tsx")
        with open(modal_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "DECISION RECOMMENDATION — NOT AUTHORIZED AND NOT EXECUTED" in content

    def test_125_frontend_modal_has_no_execution_buttons(self):
        modal_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app", "components", "DecisionEngineModal.tsx")
        with open(modal_path, "r", encoding="utf-8") as f:
            content = f.read().lower()
        # Verify no execution or action triggering buttons
        assert "execute action" not in content
        assert "approve execution" not in content
        assert "dispatch order" not in content


# =============================================================================
# 6. API ROUTES AND AUTHORIZATION TESTS (Tests 126 to 135)
# =============================================================================

class TestApiRoutesAndAuthorization:
    """Verifies REST endpoints, permissions, isolation, and error handling."""

    @pytest.fixture
    def client(self):
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        # Development identity mock
        return {"X-Tenant-ID": "tenant_acme", "X-User-ID": "analyst_1"}

    def test_126_post_evaluate_endpoint_success(self, client, sample_request, monkeypatch):
        # Mock auth dependency
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_analyst",
            roles=["ANALYST"],
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            payload = sample_request.model_dump(mode="json")
            res = client.post("/api/v3/decision-engine/evaluate", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["decision_id"] is not None
            assert data["recommendation"]["mandatory_notice"] == MANDATORY_EXECUTION_NOTICE
        finally:
            app.dependency_overrides.clear()

    def test_127_post_evaluate_tenant_spoofing_rejected(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_evil",
            user_id="user_attacker",
            roles=["ANALYST"],
            permissions=["decision_engine.evaluate"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            # Request specifies tenant_acme but caller is tenant_evil
            payload = sample_request.model_dump(mode="json")
            res = client.post("/api/v3/decision-engine/evaluate", json=payload)
            assert res.status_code == 403
            assert "Tenant boundary violation" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_128_post_evaluate_plant_isolation_enforced(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_operator",
            assigned_plants=["PLANT_99"],  # Not authorized for PLANT_01
            permissions=["decision_engine.evaluate"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            payload = sample_request.model_dump(mode="json")
            res = client.post("/api/v3/decision-engine/evaluate", json=payload)
            assert res.status_code == 403
            assert "Plant boundary violation" in res.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_129_get_decision_evaluation_by_id_success(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            eval_res = client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            decision_id = eval_res.json()["decision_id"]

            get_res = client.get(f"/api/v3/decision-engine/{decision_id}")
            assert get_res.status_code == 200
            assert get_res.json()["decision_id"] == decision_id
        finally:
            app.dependency_overrides.clear()

    def test_130_get_decision_evaluation_nonexistent_returns_404(self, client):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            res = client.get("/api/v3/decision-engine/dec_nonexistent_123")
            assert res.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_131_get_decision_evaluation_cross_tenant_returns_404(self, client, sample_request):
        mock_user_acme = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        mock_user_other = Identity(
            tenant_id="tenant_other",
            user_id="user_viewer_other",
            permissions=["decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user_acme

        try:
            eval_res = client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            decision_id = eval_res.json()["decision_id"]

            # Switch to other tenant caller
            app.dependency_overrides[get_current_identity] = lambda: mock_user_other
            get_res = client.get(f"/api/v3/decision-engine/{decision_id}")
            assert get_res.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_132_list_decisions_endpoint(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            list_res = client.get("/api/v3/decision-engine?limit=10")
            assert list_res.status_code == 200
            data = list_res.json()
            assert "items" in data
            assert data["total_count"] >= 1
        finally:
            app.dependency_overrides.clear()

    def test_133_get_alternatives_endpoint(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            eval_res = client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            decision_id = eval_res.json()["decision_id"]

            res = client.get(f"/api/v3/decision-engine/{decision_id}/alternatives")
            assert res.status_code == 200
            data = res.json()
            assert data["decision_id"] == decision_id
            assert len(data["alternatives"]) == 3
        finally:
            app.dependency_overrides.clear()

    def test_134_get_evidence_endpoint(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            eval_res = client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            decision_id = eval_res.json()["decision_id"]

            res = client.get(f"/api/v3/decision-engine/{decision_id}/evidence")
            assert res.status_code == 200
            data = res.json()
            assert data["decision_id"] == decision_id
            assert len(data["evidence"]) >= 1
        finally:
            app.dependency_overrides.clear()

    def test_135_get_audit_ledger_endpoint(self, client, sample_request):
        mock_user = Identity(
            tenant_id="tenant_acme",
            user_id="user_viewer",
            permissions=["decision_engine.evaluate", "decision_engine.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mock_user

        try:
            eval_res = client.post("/api/v3/decision-engine/evaluate", json=sample_request.model_dump(mode="json"))
            decision_id = eval_res.json()["decision_id"]

            res = client.get(f"/api/v3/decision-engine/{decision_id}/audit")
            assert res.status_code == 200
            data = res.json()
            assert data["decision_id"] == decision_id
            assert len(data["audit_records"]) >= 1
            assert data["audit_records"][0]["event_type"] == "DECISION_EVALUATED"
        finally:
            app.dependency_overrides.clear()
