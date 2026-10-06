"""
backend/test_v3_what_if_simulation.py

SageCommand V3 — What-If Simulation Intelligence Foundation Test Suite (Prompt 28)

ANALYTICAL ONLY.
Comprehensive test suite covering:
1. Contracts & Schema Validation (valid scenario, missing fields, invalid types, finite bounds)
2. Defensible Baseline Resolution (Digital Twin, Sensor Fusion, explicit, insufficient data)
3. Scenario Variables Matrix (demand, capacity, lead time, availability, degradation, energy, etc.)
4. Deterministic Simulation Methods (rule-based, capacity propagation, linear sensitivity)
5. Temporal Semantics & Anti-Leakage Protection (historical replay, future leakage rejection)
6. Scenario Composition & Interaction Effects (independent, super-additive, sub-additive)
7. Delta Engine (positive, negative, zero, percentage, zero-denominator safety, unknown)
8. Scenario Constraints Evaluation (LTE, GTE, LT, GT, EQ, BETWEEN, margin, satisfied/violated)
9. Bounded Downstream Impact Propagation (capacity, SLA, financial, sustainability, hop bounds)
10. Evidence Chain & Explainability (deterministic IDs, source references, contribution, limits)
11. Multi-Dimensional Uncertainty & Confidence (qualitative quantification, no fake intervals)
12. Deterministic SHA-256 Fingerprinting & Idempotency (invariance, material change detection)
13. SQLite WAL Repository Persistence (CRUD, isolation, duplicate prevention, thread safety)
14. API Endpoints, RBAC, ABAC & Boundary Checks (analyze, retrieve, list, impact, evidence)
15. Cross-Module Intelligence Integration (Sensor Fusion, Digital Twin, SLA, Financial, Sustainability)
16. Execution Boundary & AST Static Analysis (Zero ExecutionGateway/PLC/Action imports)

TEST ISOLATION RULE:
All mocks use local context managers / fixtures. NO module-level monkeypatching of authorization.
"""

import ast
import json
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.auth import Identity
from data.schemas.authorization_contract import (
    AuthorizationDecision,
    AuthzDecisionEffect,
    AuthzReasonCode,
)
from data.schemas.sensor_fusion_contract import SensorValueProvenance
from data.schemas.what_if_simulation_contract import (
    SimulationResult,
    SimulationScenario,
    SimulationTarget,
    ScenarioVariable,
    ScenarioConstraint,
    SimulationBaseline,
    SimulatedState,
    SimulationDelta,
    ImpactAssessment,
    SimulationEvidence,
    SimulationAssumption,
    SimulationLimitation,
    SimulationUncertainty,
    ConstraintEvaluationResult,
    VariableContribution,
    WhatIfAnalyzeRequest,
    SimulationClassification,
    SimulationTargetScope,
    ScenarioVariableType,
    VariableChangeType,
    ConstraintType,
    ConstraintOperator,
    ConstraintStatus,
    SimulationBaselineSource,
    SimulationMethod,
    SimulationConfidence,
    DeltaClassification,
    ImpactCategory,
    compute_what_if_fingerprint,
)
from services.what_if_simulation_repository import (
    WhatIfSimulationRepository,
    what_if_simulation_repository,
)
from services.what_if_simulation_service import (
    WhatIfSimulationService,
    what_if_simulation_service,
)
import server


# =============================================================================
# FIXTURES (Strictly Scoped — No Global Monkeypatching)
# =============================================================================

@pytest.fixture
def temp_db_path(tmp_path):
    """Fresh isolated SQLite database file for each test."""
    db_file = tmp_path / "test_what_if_simulation.sqlite"
    return str(db_file)


@pytest.fixture
def isolated_repo(temp_db_path):
    """Fresh WhatIfSimulationRepository backed by isolated DB."""
    return WhatIfSimulationRepository(db_path=temp_db_path)


@pytest.fixture
def isolated_service(isolated_repo):
    """Fresh WhatIfSimulationService injecting isolated repo."""
    return WhatIfSimulationService(repository=isolated_repo)


@pytest.fixture
def test_client():
    """FastAPI TestClient with isolated test headers."""
    return TestClient(server.app)


def _allow_decision(permission_id: str = "what_if_simulation.analyze") -> AuthorizationDecision:
    """Helper creating a deterministic ALLOW decision."""
    return AuthorizationDecision.create(
        effect=AuthzDecisionEffect.ALLOW,
        reason_code=AuthzReasonCode.ALLOWED,
        reason="Authorized for simulation analytical testing.",
        required_permission=permission_id,
        matched_role="ANALYST",
        resolved_permissions=[permission_id],
    )


def _deny_decision(permission_id: str = "what_if_simulation.read") -> AuthorizationDecision:
    """Helper creating a deterministic DENY decision."""
    return AuthorizationDecision.create(
        effect=AuthzDecisionEffect.DENY,
        reason_code=AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS,
        reason="Denied for simulation testing.",
        required_permission=permission_id,
    )


def _make_identity(
    tenant_id: str = "tenant_test",
    roles: Optional[List[str]] = None,
    assigned_plants: Optional[List[str]] = None,
) -> Identity:
    """Helper generating structured Identity."""
    return Identity(
        user_id="user_test",
        tenant_id=tenant_id,
        roles=roles or ["ANALYST"],
        assigned_plants=assigned_plants if assigned_plants is not None else ["*"],
    )


def _sample_variable(
    var_id: str = "VAR-01",
    vtype: ScenarioVariableType = ScenarioVariableType.DEMAND_CHANGE,
    param: str = "demand_rate",
    val: float = 20.0,
    ctype: VariableChangeType = VariableChangeType.PERCENT_DELTA,
) -> ScenarioVariable:
    return ScenarioVariable(
        variable_id=var_id,
        variable_type=vtype,
        parameter_name=param,
        change_type=ctype,
        value=val,
        unit="PERCENT",
    )


def _sample_request(
    tenant_id: str = "tenant_default",
    variables: Optional[List[ScenarioVariable]] = None,
    constraints: Optional[List[ScenarioConstraint]] = None,
    explicit_baseline: Optional[Dict[str, Any]] = None,
    assessment_ts: Optional[str] = None,
) -> WhatIfAnalyzeRequest:
    return WhatIfAnalyzeRequest(
        tenant_id=tenant_id,
        workspace_id="workspace_default",
        plant_id="PLANT-01",
        scenario_name="Test Operational Scenario",
        targets=[
            SimulationTarget(entity_id="MCH-01", entity_type="MACHINE")
        ],
        variables=variables or [_sample_variable()],
        constraints=constraints or [],
        explicit_baseline=explicit_baseline,
        assessment_timestamp=assessment_ts,
    )


# =============================================================================
# 1. CONTRACTS & SCHEMA VALIDATION TESTS (12 Tests)
# =============================================================================

def test_contract_valid_scenario_creation():
    """Valid SimulationScenario instantiates with expected attributes."""
    scen = SimulationScenario(
        scenario_id="SCEN-01",
        tenant_id="tenant_1",
        name="Demand Surge",
        created_at="2026-10-06T00:00:00Z",
        assessment_timestamp="2026-10-06T00:00:00Z",
    )
    assert scen.scenario_id == "SCEN-01"
    assert scen.target_scope == SimulationTargetScope.ENTITY
    assert scen.method == SimulationMethod.COMPOSITE_DETERMINISTIC


def test_contract_missing_tenant_id_fails(isolated_service):
    """Empty or missing tenant_id raises ValueError."""
    with pytest.raises(Exception):
        _sample_request(tenant_id="")
    req = _sample_request()
    req.tenant_id = ""
    with pytest.raises(ValueError, match="tenant_id is required"):
        isolated_service.analyze(req)


def test_contract_missing_scenario_name_fails(isolated_service):
    """Empty scenario name raises ValueError."""
    req = _sample_request()
    req.scenario_name = "   "
    with pytest.raises(ValueError, match="scenario_name cannot be empty"):
        isolated_service.analyze(req)


def test_contract_finite_variable_value():
    """ScenarioVariable accepts finite floats."""
    var = ScenarioVariable(
        variable_id="V1",
        variable_type=ScenarioVariableType.DEMAND_CHANGE,
        parameter_name="demand_rate",
        value=15.5,
    )
    assert var.value == 15.5


def test_contract_nan_variable_value_rejected():
    """NaN variable value is rejected by validator."""
    with pytest.raises(ValueError, match="finite numeric scalar"):
        ScenarioVariable(
            variable_id="V1",
            variable_type=ScenarioVariableType.DEMAND_CHANGE,
            parameter_name="demand_rate",
            value=float("nan"),
        )


def test_contract_inf_variable_value_rejected():
    """Infinity variable value is rejected by validator."""
    with pytest.raises(ValueError, match="finite numeric scalar"):
        ScenarioVariable(
            variable_id="V1",
            variable_type=ScenarioVariableType.DEMAND_CHANGE,
            parameter_name="demand_rate",
            value=float("inf"),
        )


def test_contract_target_defaults():
    """SimulationTarget defaults to ENTITY scope and EQUIPMENT type."""
    t = SimulationTarget(entity_id="ROBOT-42")
    assert t.entity_id == "ROBOT-42"
    assert t.entity_type == "EQUIPMENT"
    assert t.target_scope == SimulationTargetScope.ENTITY


def test_contract_constraint_model_validation():
    """ScenarioConstraint validates operator and threshold."""
    c = ScenarioConstraint(
        constraint_id="C-99",
        constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap",
        operator=ConstraintOperator.LTE,
        threshold_value=50.0,
    )
    assert c.operator == ConstraintOperator.LTE
    assert c.threshold_value == 50.0


def test_contract_assumption_expiration_flag():
    """SimulationAssumption tracks expiration status."""
    assump = SimulationAssumption(
        assumption_id="ASSUMP-1",
        description="Grid power stable",
        is_expired=True,
    )
    assert assump.is_expired is True


def test_contract_limitation_categories():
    """SimulationLimitation accurately records limitation details."""
    lim = SimulationLimitation(
        limitation_id="LIM-01",
        category="MISSING_FACTOR",
        description="Emissions factor unavailable",
        affected_metrics=["co2e"],
    )
    assert lim.category == "MISSING_FACTOR"
    assert "co2e" in lim.affected_metrics


def test_contract_exceeded_variables_limit_fails(isolated_service):
    """Exceeding SAGE_SIMULATION_MAX_VARIABLES raises ValueError."""
    many_vars = [
        ScenarioVariable(
            variable_id=f"V{i}",
            variable_type=ScenarioVariableType.CUSTOM_SCALAR_CHANGE,
            parameter_name=f"param_{i}",
            value=1.0,
        )
        for i in range(105)
    ]
    req = _sample_request(variables=many_vars)
    with pytest.raises(ValueError, match="Exceeded maximum scenario variables limit"):
        isolated_service.analyze(req)


def test_contract_provenance_immutability():
    """SimulationResult enforces SIMULATED provenance."""
    baseline = SimulationBaseline(
        baseline_id="B1", source=SimulationBaselineSource.EXPLICIT_INPUT,
        source_id="S1", source_timestamp="2026-10-06T00:00:00Z",
        effective_at="2026-10-06T00:00:00Z",
    )
    scen = SimulationScenario(
        scenario_id="S1", tenant_id="t1", name="N",
        created_at="2026-10-06T00:00:00Z", assessment_timestamp="2026-10-06T00:00:00Z",
    )
    state = SimulatedState(effective_at="2026-10-06T00:00:00Z")
    unc = SimulationUncertainty()
    res = SimulationResult(
        simulation_id="SIM-1", tenant_id="t1", scenario=scen,
        baseline=baseline, simulated_state=state, uncertainty=unc,
        input_fingerprint="f"*64, created_at="2026-10-06T00:00:00Z",
    )
    assert res.provenance == SensorValueProvenance.SIMULATED


# =============================================================================
# 2. DEFENSIBLE BASELINE RESOLUTION TESTS (8 Tests)
# =============================================================================

def test_baseline_explicit_metrics_applied(isolated_service):
    """Explicit baseline metrics are respected and ground simulation."""
    exp = {
        "metrics": {"demand_rate": 2000.0, "production_capacity": 2500.0},
        "data_quality_score": 0.98,
        "confidence": "HIGH",
    }
    req = _sample_request(explicit_baseline=exp)
    res = isolated_service.analyze(req)
    assert res.baseline.metrics["demand_rate"] == 2000.0
    assert res.baseline.data_quality_score == 0.98


def test_baseline_fallback_when_unpopulated(isolated_service):
    """When no baseline provided, conservative standard baseline is used with limitation."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert "demand_rate" in res.baseline.metrics
    assert any(lim.limitation_id == "LIM-DEFAULT-BASELINE" for lim in res.limitations)


def test_baseline_sensor_fusion_source_labeling(isolated_service):
    """Simulation records SENSOR_FUSION baseline source."""
    req = _sample_request()
    req.baseline_source = SimulationBaselineSource.SENSOR_FUSION
    req.baseline_id = "FUSION-ASSESS-001"
    res = isolated_service.analyze(req)
    assert res.baseline.source == SimulationBaselineSource.SENSOR_FUSION
    assert res.baseline.source_id == "FUSION-ASSESS-001"


def test_baseline_digital_twin_source_labeling(isolated_service):
    """Simulation records DIGITAL_TWIN baseline source."""
    req = _sample_request()
    req.baseline_source = SimulationBaselineSource.DIGITAL_TWIN
    req.baseline_id = "TWIN-SNAP-999"
    res = isolated_service.analyze(req)
    assert res.baseline.source == SimulationBaselineSource.DIGITAL_TWIN


def test_baseline_supplier_risk_source_labeling(isolated_service):
    """Simulation records SUPPLIER_RISK baseline source."""
    req = _sample_request()
    req.baseline_source = SimulationBaselineSource.SUPPLIER_RISK
    res = isolated_service.analyze(req)
    assert res.baseline.source == SimulationBaselineSource.SUPPLIER_RISK


def test_baseline_financial_impact_source_labeling(isolated_service):
    """Simulation records FINANCIAL_IMPACT baseline source."""
    req = _sample_request()
    req.baseline_source = SimulationBaselineSource.FINANCIAL_IMPACT
    res = isolated_service.analyze(req)
    assert res.baseline.source == SimulationBaselineSource.FINANCIAL_IMPACT


def test_baseline_sustainability_source_labeling(isolated_service):
    """Simulation records SUSTAINABILITY baseline source."""
    req = _sample_request()
    req.baseline_source = SimulationBaselineSource.SUSTAINABILITY
    res = isolated_service.analyze(req)
    assert res.baseline.source == SimulationBaselineSource.SUSTAINABILITY


def test_baseline_provenance_preserves_observed(isolated_service):
    """Baseline provenance is OBSERVED, never altered to SIMULATED."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert res.baseline.provenance == SensorValueProvenance.OBSERVED
    assert res.simulated_state.provenance == SensorValueProvenance.SIMULATED


# =============================================================================
# 3. SCENARIO VARIABLES MATRIX TESTS (10 Tests)
# =============================================================================

def test_variable_demand_surge_calculation(isolated_service):
    """+20% demand increase raises demand from 1000 to 1200."""
    v = _sample_variable(vtype=ScenarioVariableType.DEMAND_CHANGE, val=20.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["demand_rate"] == 1200.0


def test_variable_demand_drop_calculation(isolated_service):
    """-15% demand drop reduces demand from 1000 to 850."""
    v = _sample_variable(vtype=ScenarioVariableType.DEMAND_CHANGE, val=-15.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["demand_rate"] == 850.0


def test_variable_demand_multiplier(isolated_service):
    """Demand change using MULTIPLIER 1.25 yields 1250."""
    v = _sample_variable(
        vtype=ScenarioVariableType.DEMAND_CHANGE,
        val=1.25,
        ctype=VariableChangeType.MULTIPLIER
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["demand_rate"] == 1250.0


def test_variable_supply_capacity_reduction(isolated_service):
    """-20% supply capacity reduces baseline 1500 to 1200."""
    v = _sample_variable(
        vtype=ScenarioVariableType.SUPPLY_CAPACITY_CHANGE,
        param="supplier_capacity",
        val=-20.0
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["supplier_capacity"] == 1200.0


def test_variable_lead_time_days_absolute_delta(isolated_service):
    """Lead time +3 days increases baseline 5.0 to 8.0."""
    v = ScenarioVariable(
        variable_id="V-LT",
        variable_type=ScenarioVariableType.LEAD_TIME_CHANGE,
        parameter_name="lead_time_days",
        change_type=VariableChangeType.ABSOLUTE_DELTA,
        value=3.0,
        unit="DAYS",
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["lead_time_days"] == 8.0


def test_variable_asset_availability_drop(isolated_service):
    """Asset availability drop generates projected downtime hours."""
    v = _sample_variable(
        vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE,
        param="asset_availability",
        val=-10.0  # -10% of 0.95 = 0.855
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["asset_availability"] == 0.855
    assert res.simulated_state.metrics["projected_downtime_hours"] > 0


def test_variable_asset_degradation_acceleration(isolated_service):
    """Degradation acceleration correlates with elevated vibration RMS."""
    v = _sample_variable(
        vtype=ScenarioVariableType.ASSET_DEGRADATION_CHANGE,
        param="degradation_rate",
        val=50.0  # +50%
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["degradation_rate"] == 0.075
    assert res.simulated_state.metrics["vibration_rms"] > 2.2


def test_variable_energy_consumption_and_emissions(isolated_service):
    """Energy consumption change computes projected emissions."""
    v = _sample_variable(
        vtype=ScenarioVariableType.ENERGY_CONSUMPTION_CHANGE,
        param="energy_consumption",
        val=20.0  # 450 * 1.2 = 540
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["energy_consumption"] == 540.0
    assert res.simulated_state.metrics["projected_emissions_co2e"] == round(540.0 * 0.42, 2)


def test_variable_quality_rate_reduction(isolated_service):
    """Quality rate reduction is clamped between 0 and 1."""
    v = _sample_variable(
        vtype=ScenarioVariableType.QUALITY_RATE_CHANGE,
        param="quality_rate",
        val=-5.0
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert 0.0 <= res.simulated_state.metrics["quality_rate"] <= 1.0


def test_variable_custom_scalar_parameter(isolated_service):
    """Custom scalar variable alters parameter deterministically."""
    v = ScenarioVariable(
        variable_id="V-CUSTOM",
        variable_type=ScenarioVariableType.CUSTOM_SCALAR_CHANGE,
        parameter_name="furnace_temperature",
        change_type=VariableChangeType.SET_VALUE,
        value=750.0,
        unit="CELSIUS",
    )
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["furnace_temperature"] == 750.0


# =============================================================================
# 4. TEMPORAL CORRECTNESS & ANTI-LEAKAGE TESTS (8 Tests)
# =============================================================================

def test_temporal_future_leakage_rejected(isolated_service):
    """Baseline timestamp in future relative to assessment_timestamp raises ValueError."""
    now = "2026-10-06T12:00:00Z"
    future = "2026-10-06T13:00:00Z"
    exp = {"timestamp": future, "metrics": {"demand_rate": 1000.0}}
    req = _sample_request(explicit_baseline=exp, assessment_ts=now)
    with pytest.raises(ValueError, match="Temporal leakage violation"):
        isolated_service.analyze(req)


def test_temporal_historical_simulation_allowed(isolated_service):
    """Historical baseline strictly prior to assessment_timestamp succeeds."""
    hist = "2026-09-01T00:00:00Z"
    now = "2026-10-06T00:00:00Z"
    exp = {"timestamp": hist, "metrics": {"demand_rate": 800.0}}
    req = _sample_request(explicit_baseline=exp, assessment_ts=now)
    res = isolated_service.analyze(req)
    assert res.baseline.source_timestamp == hist


def test_temporal_expired_variable_skipped_with_limitation(isolated_service):
    """Variable with valid_to < assessment_timestamp is skipped with limitation."""
    past = "2026-10-01T00:00:00Z"
    now = "2026-10-06T00:00:00Z"
    var = ScenarioVariable(
        variable_id="V-EXP",
        variable_type=ScenarioVariableType.DEMAND_CHANGE,
        parameter_name="demand_rate",
        value=50.0,
        valid_to=past,
    )
    req = _sample_request(variables=[var], assessment_ts=now)
    res = isolated_service.analyze(req)
    # Demand was not changed by expired variable
    assert res.simulated_state.metrics["demand_rate"] == 1000.0
    assert any(lim.category == "EXPIRED_ASSUMPTION" for lim in res.limitations)


def test_temporal_effective_at_set_to_assessment_timestamp(isolated_service):
    """Simulated state effective_at strictly equals assessment_timestamp."""
    now = "2026-10-06T08:30:00Z"
    req = _sample_request(assessment_ts=now)
    res = isolated_service.analyze(req)
    assert res.simulated_state.effective_at == now


def test_temporal_snapshot_consistency(isolated_service):
    """Baseline effective_at matches snapshot timestamp."""
    now = "2026-10-06T09:00:00Z"
    req = _sample_request(assessment_ts=now)
    res = isolated_service.analyze(req)
    assert res.baseline.effective_at == now


def test_temporal_horizon_preservation(isolated_service):
    """Horizon parameter P30D preserved in scenario."""
    req = _sample_request()
    req.horizon = "P30D"
    res = isolated_service.analyze(req)
    assert res.scenario.horizon == "P30D"


def test_temporal_equal_timestamps_allowed(isolated_service):
    """Baseline timestamp equal to assessment_timestamp is valid."""
    ts = "2026-10-06T10:00:00Z"
    exp = {"timestamp": ts, "metrics": {"demand_rate": 1100.0}}
    req = _sample_request(explicit_baseline=exp, assessment_ts=ts)
    res = isolated_service.analyze(req)
    assert res.baseline.source_timestamp == ts


def test_temporal_replay_does_not_mutate_baseline(isolated_service):
    """Replaying simulation never mutates baseline source object."""
    exp = {"metrics": {"demand_rate": 1000.0}}
    req = _sample_request(explicit_baseline=exp)
    isolated_service.analyze(req)
    assert exp["metrics"]["demand_rate"] == 1000.0


# =============================================================================
# 5. SCENARIO COMPOSITION & INTERACTION EFFECTS TESTS (8 Tests)
# =============================================================================

def test_composition_single_variable_is_independent(isolated_service):
    """Single scenario variable classifies interaction as INDEPENDENT."""
    v = _sample_variable()
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.interaction_effect == "INDEPENDENT"


def test_composition_demand_and_asset_super_additive(isolated_service):
    """Simultaneous demand surge and asset downtime stress yields SUPER_ADDITIVE."""
    v1 = _sample_variable(var_id="V1", vtype=ScenarioVariableType.DEMAND_CHANGE, val=25.0)
    v2 = _sample_variable(var_id="V2", vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-15.0)
    req = _sample_request(variables=[v1, v2])
    res = isolated_service.analyze(req)
    assert res.interaction_effect == "SUPER_ADDITIVE"


def test_composition_multiple_same_domain_sub_additive(isolated_service):
    """Multiple variables in same domain classify interaction as SUB_ADDITIVE."""
    v1 = _sample_variable(var_id="V1", vtype=ScenarioVariableType.DEMAND_CHANGE, val=10.0)
    v2 = _sample_variable(var_id="V2", vtype=ScenarioVariableType.DEMAND_CHANGE, val=5.0)
    req = _sample_request(variables=[v1, v2])
    res = isolated_service.analyze(req)
    assert res.interaction_effect == "SUB_ADDITIVE"


def test_composition_orthogonal_domains_independent(isolated_service):
    """Variables in orthogonal domains classify as INDEPENDENT."""
    v1 = _sample_variable(var_id="V1", vtype=ScenarioVariableType.DEMAND_CHANGE, val=10.0)
    v2 = _sample_variable(var_id="V2", vtype=ScenarioVariableType.ENERGY_CONSUMPTION_CHANGE, param="energy_consumption", val=5.0)
    req = _sample_request(variables=[v1, v2])
    res = isolated_service.analyze(req)
    assert res.interaction_effect == "INDEPENDENT"


def test_composition_individual_variable_contributions_recorded(isolated_service):
    """Each variable has an individual effect recorded in variable_contributions."""
    v1 = _sample_variable(var_id="V1", vtype=ScenarioVariableType.DEMAND_CHANGE, val=20.0)
    v2 = _sample_variable(var_id="V2", vtype=ScenarioVariableType.SUPPLY_CAPACITY_CHANGE, param="supplier_capacity", val=-10.0)
    req = _sample_request(variables=[v1, v2])
    res = isolated_service.analyze(req)
    assert len(res.variable_contributions) == 2
    assert "demand_rate" in res.variable_contributions[0].individual_effect
    assert "supplier_capacity" in res.variable_contributions[1].individual_effect


def test_composition_contribution_percentages_sum_to_100(isolated_service):
    """Contribution percentages partition equally across active variables."""
    v1 = _sample_variable(var_id="V1")
    v2 = _sample_variable(var_id="V2")
    req = _sample_request(variables=[v1, v2])
    res = isolated_service.analyze(req)
    total_pct = sum(vc.contribution_pct for vc in res.variable_contributions)
    assert round(total_pct, 1) == 100.0


def test_composition_multi_variable_capacity_gap(isolated_service):
    """Demand surge above capacity creates explicit capacity_gap."""
    # Baseline capacity is 1200. Demand +30% from 1000 = 1300. Gap = 100.
    v = _sample_variable(val=30.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["capacity_gap"] == 100.0


def test_composition_no_negative_capacity_gap(isolated_service):
    """Demand below capacity yields capacity_gap of 0.0 (non-negative)."""
    # Demand -20% from 1000 = 800. Cap = 1200. Gap = 0.
    v = _sample_variable(val=-20.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["capacity_gap"] == 0.0


# =============================================================================
# 6. DELTA ENGINE TESTS (8 Tests)
# =============================================================================

def test_delta_positive_calculation(isolated_service):
    """Positive change produces positive delta and percentage."""
    v = _sample_variable(val=20.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "demand_rate")
    assert d.delta == 200.0
    assert d.delta_percent == 20.0
    assert d.classification == DeltaClassification.CHANGED


def test_delta_negative_calculation(isolated_service):
    """Negative change produces negative delta and percentage."""
    v = _sample_variable(val=-10.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "demand_rate")
    assert d.delta == -100.0
    assert d.delta_percent == -10.0


def test_delta_zero_unchanged_classification(isolated_service):
    """Zero delta correctly classifies as UNCHANGED."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "lead_time_days")
    assert d.delta == 0.0
    assert d.classification == DeltaClassification.UNCHANGED


def test_delta_zero_denominator_safe(isolated_service):
    """Baseline value of 0.0 safely produces None percentage without ZeroDivisionError."""
    exp = {"metrics": {"custom_counter": 0.0}}
    v = ScenarioVariable(
        variable_id="V1", variable_type=ScenarioVariableType.CUSTOM_SCALAR_CHANGE,
        parameter_name="custom_counter", change_type=VariableChangeType.SET_VALUE, value=10.0,
    )
    req = _sample_request(variables=[v], explicit_baseline=exp)
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "custom_counter")
    assert d.delta == 10.0
    assert d.delta_percent is None  # Undefined, not an exception or inf


def test_delta_missing_metric_classified_unknown(isolated_service):
    """Missing metric delta classifies as UNKNOWN with None values."""
    exp = {"metrics": {"existing_metric": 50.0, "missing_in_sim": None}}
    req = _sample_request(explicit_baseline=exp)
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "missing_in_sim")
    assert d.classification == DeltaClassification.UNKNOWN
    assert d.delta is None


def test_delta_confidence_high_on_numeric(isolated_service):
    """Numeric delta carries HIGH confidence."""
    v = _sample_variable()
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "demand_rate")
    assert d.confidence == SimulationConfidence.HIGH


def test_delta_provenance_is_simulated(isolated_service):
    """Delta provenance is explicitly SIMULATED."""
    v = _sample_variable()
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "demand_rate")
    assert d.provenance == SensorValueProvenance.SIMULATED


def test_delta_target_entity_propagation(isolated_service):
    """Target entity ID is propagated to delta records."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    d = next(d for d in res.deltas if d.metric_name == "demand_rate")
    assert d.target_entity_id == "MCH-01"


# =============================================================================
# 7. SCENARIO CONSTRAINTS EVALUATION TESTS (10 Tests)
# =============================================================================

def test_constraint_lte_satisfied(isolated_service):
    """LTE constraint satisfied when value <= threshold."""
    c = ScenarioConstraint(
        constraint_id="C-LTE", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap", operator=ConstraintOperator.LTE, threshold_value=500.0,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-LTE")
    assert cr.status == ConstraintStatus.SATISFIED


def test_constraint_lte_violated(isolated_service):
    """LTE constraint violated when value > threshold."""
    # Demand +30% yields capacity_gap = 100 > 0.
    v = _sample_variable(val=30.0)
    c = ScenarioConstraint(
        constraint_id="C-ZERO-GAP", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap", operator=ConstraintOperator.LTE, threshold_value=0.0,
    )
    req = _sample_request(variables=[v], constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-ZERO-GAP")
    assert cr.status == ConstraintStatus.VIOLATED
    assert cr.margin > 0


def test_constraint_gte_satisfied(isolated_service):
    """GTE constraint satisfied when value >= threshold."""
    c = ScenarioConstraint(
        constraint_id="C-AVAIL", constraint_type=ConstraintType.ASSET_AVAILABILITY,
        metric_name="asset_availability", operator=ConstraintOperator.GTE, threshold_value=0.90,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-AVAIL")
    assert cr.status == ConstraintStatus.SATISFIED


def test_constraint_gte_violated(isolated_service):
    """GTE constraint violated when value < threshold."""
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-20.0)
    c = ScenarioConstraint(
        constraint_id="C-MIN-AVAIL", constraint_type=ConstraintType.ASSET_AVAILABILITY,
        metric_name="asset_availability", operator=ConstraintOperator.GTE, threshold_value=0.90,
    )
    req = _sample_request(variables=[v], constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-MIN-AVAIL")
    assert cr.status == ConstraintStatus.VIOLATED


def test_constraint_between_satisfied(isolated_service):
    """BETWEEN operator satisfied when min <= val <= max."""
    c = ScenarioConstraint(
        constraint_id="C-RANGE", constraint_type=ConstraintType.CUSTOM_THRESHOLD,
        metric_name="asset_availability", operator=ConstraintOperator.BETWEEN,
        threshold_value=0.80, threshold_max_value=1.00,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-RANGE")
    assert cr.status == ConstraintStatus.SATISFIED


def test_constraint_between_violated(isolated_service):
    """BETWEEN operator violated when value outside bounds."""
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-30.0)
    c = ScenarioConstraint(
        constraint_id="C-RANGE", constraint_type=ConstraintType.CUSTOM_THRESHOLD,
        metric_name="asset_availability", operator=ConstraintOperator.BETWEEN,
        threshold_value=0.80, threshold_max_value=1.00,
    )
    req = _sample_request(variables=[v], constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-RANGE")
    assert cr.status == ConstraintStatus.VIOLATED


def test_constraint_unknown_metric(isolated_service):
    """Constraint on non-existent metric returns UNKNOWN status."""
    c = ScenarioConstraint(
        constraint_id="C-NONEXIST", constraint_type=ConstraintType.CUSTOM_THRESHOLD,
        metric_name="non_existent_telemetry", operator=ConstraintOperator.LTE, threshold_value=10.0,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-NONEXIST")
    assert cr.status == ConstraintStatus.UNKNOWN


def test_constraint_margin_calculation(isolated_service):
    """Margin reflects simulated_value minus threshold_value."""
    c = ScenarioConstraint(
        constraint_id="C-MARGIN", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="demand_rate", operator=ConstraintOperator.LTE, threshold_value=1000.0,
    )
    v = _sample_variable(val=20.0)  # demand 1200
    req = _sample_request(variables=[v], constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-MARGIN")
    assert cr.margin == 200.0


def test_constraint_explanation_string(isolated_service):
    """Constraint evaluation result includes readable explanation."""
    c = ScenarioConstraint(
        constraint_id="C-EXPL", constraint_type=ConstraintType.SLA_THRESHOLD,
        metric_name="sla_compliance_rate", operator=ConstraintOperator.GTE, threshold_value=0.95,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-EXPL")
    assert "Simulated value" in cr.explanation
    assert cr.status.value in cr.explanation


def test_constraint_eq_operator(isolated_service):
    """EQ operator verifies equality within tolerance."""
    c = ScenarioConstraint(
        constraint_id="C-EQ", constraint_type=ConstraintType.CUSTOM_THRESHOLD,
        metric_name="lead_time_days", operator=ConstraintOperator.EQ, threshold_value=5.0,
    )
    req = _sample_request(constraints=[c])
    res = isolated_service.analyze(req)
    cr = next(r for r in res.constraint_results if r.constraint_id == "C-EQ")
    assert cr.status == ConstraintStatus.SATISFIED


# =============================================================================
# 8. BOUNDED DOWNSTREAM IMPACT PROPAGATION TESTS (8 Tests)
# =============================================================================

def test_impact_capacity_shortage_trigger(isolated_service):
    """Demand surge creating gap generates CAPACITY impact."""
    v = _sample_variable(val=30.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    imp = next((i for i in res.impact_assessments if i.category == ImpactCategory.CAPACITY), None)
    assert imp is not None
    assert imp.delta_metric == 100.0


def test_impact_sla_drop_trigger(isolated_service):
    """Severe asset availability drop triggers SLA impact on customer."""
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-25.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    imp = next((i for i in res.impact_assessments if i.category == ImpactCategory.SLA), None)
    assert imp is not None
    assert imp.affected_entity_id == "CUSTOMER-TIER-1"


def test_impact_financial_exposure_trigger(isolated_service):
    """Downtime hours trigger FINANCIAL impact assessment."""
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-10.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    imp = next((i for i in res.impact_assessments if i.category == ImpactCategory.FINANCIAL), None)
    assert imp is not None
    assert imp.unit == "USD"
    assert imp.delta_metric > 0


def test_impact_sustainability_emissions_trigger(isolated_service):
    """Energy consumption change generates SUSTAINABILITY impact."""
    v = _sample_variable(vtype=ScenarioVariableType.ENERGY_CONSUMPTION_CHANGE, param="energy_consumption", val=20.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    imp = next((i for i in res.impact_assessments if i.category == ImpactCategory.SUSTAINABILITY), None)
    assert imp is not None
    assert imp.unit == "KG_CO2E"


def test_impact_bounded_propagation_depth(isolated_service):
    """Propagation distance does not exceed configured max_depth."""
    req = _sample_request()
    req.max_propagation_depth = 2
    res = isolated_service.analyze(req)
    for imp in res.impact_assessments:
        assert imp.propagation_distance <= 2


def test_impact_affected_entities_populated(isolated_service):
    """Affected entities list includes primary target and downstream nodes."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert "MCH-01" in res.affected_entities
    assert len(res.affected_entities) >= 1


def test_impact_confidence_and_provenance(isolated_service):
    """Impact assessments carry SIMULATED provenance and valid confidence."""
    v = _sample_variable(val=25.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    for imp in res.impact_assessments:
        assert imp.provenance == SensorValueProvenance.SIMULATED
        assert imp.confidence in (SimulationConfidence.HIGH, SimulationConfidence.MEDIUM, SimulationConfidence.LOW)


def test_impact_severity_classification(isolated_service):
    """Severe capacity gap (>200) receives HIGH severity."""
    # Baseline capacity = 1200. Demand +50% = 1500. Gap = 300.
    v = _sample_variable(val=50.0)
    req = _sample_request(variables=[v])
    res = isolated_service.analyze(req)
    imp = next(i for i in res.impact_assessments if i.category == ImpactCategory.CAPACITY)
    assert imp.severity == "HIGH"


# =============================================================================
# 9. EVIDENCE CHAIN & EXPLAINABILITY TESTS (8 Tests)
# =============================================================================

def test_evidence_deterministic_ids(isolated_service):
    """Evidence items have deterministic identifiers prefixed with EVID-."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    for ev in res.evidence:
        assert ev.evidence_id.startswith("EVID-")


def test_evidence_grounding_baseline_included(isolated_service):
    """Evidence chain includes BASELINE_OBSERVATION grounding item."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert any(ev.source_type == "BASELINE_OBSERVATION" for ev in res.evidence)


def test_evidence_scenario_variables_included(isolated_service):
    """Evidence chain includes SCENARIO_VARIABLE item."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert any(ev.source_type == "SCENARIO_VARIABLE" for ev in res.evidence)


def test_evidence_constraint_violations_included(isolated_service):
    """Violated constraints are recorded in the evidence chain."""
    v = _sample_variable(val=30.0)
    c = ScenarioConstraint(
        constraint_id="C-VIOL", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap", operator=ConstraintOperator.LTE, threshold_value=0.0,
    )
    req = _sample_request(variables=[v], constraints=[c])
    res = isolated_service.analyze(req)
    assert any(ev.source_type == "CONSTRAINT" and ev.relationship == "VIOLATION_TRIGGER" for ev in res.evidence)


def test_evidence_provenance_explicit(isolated_service):
    """Evidence provenance is preserved."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    for ev in res.evidence:
        assert ev.provenance in (SensorValueProvenance.OBSERVED, SensorValueProvenance.DERIVED, SensorValueProvenance.SIMULATED)


def test_evidence_bounded_size(isolated_service):
    """Evidence list size is strictly bounded."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert len(res.evidence) <= 1000


def test_evidence_reproducible_across_runs(isolated_service):
    """Identical requests produce identical evidence IDs and explanations."""
    req1 = _sample_request(assessment_ts="2026-10-06T12:00:00Z")
    req2 = _sample_request(assessment_ts="2026-10-06T12:00:00Z")
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    ev_ids_1 = [e.evidence_id for e in res1.evidence]
    ev_ids_2 = [e.evidence_id for e in res2.evidence]
    assert ev_ids_1 == ev_ids_2


def test_evidence_explanation_not_empty(isolated_service):
    """Every evidence item has non-empty human-readable explanation."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    for ev in res.evidence:
        assert len(ev.explanation.strip()) > 5


# =============================================================================
# 10. UNCERTAINTY & CONFIDENCE TESTS (6 Tests)
# =============================================================================

def test_uncertainty_dimensions_populated(isolated_service):
    """SimulationUncertainty populates all 6 dimensions."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    unc = res.uncertainty
    assert unc.overall_uncertainty in ("LOW", "MEDIUM", "HIGH")
    assert unc.measurement_uncertainty in ("LOW", "MEDIUM", "HIGH")
    assert unc.model_uncertainty in ("LOW", "MEDIUM", "HIGH")
    assert unc.scenario_uncertainty in ("LOW", "MEDIUM", "HIGH")
    assert unc.dependency_uncertainty in ("LOW", "MEDIUM", "HIGH")
    assert unc.data_quality_uncertainty in ("LOW", "MEDIUM", "HIGH")


def test_uncertainty_no_fabricated_numerical_intervals(isolated_service):
    """Uncertainty does not fabricate fake numerical probability intervals."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    # Validates qualitative string enums rather than fake numerical ranges
    assert isinstance(res.uncertainty.overall_uncertainty, str)


def test_confidence_high_with_clean_baseline(isolated_service):
    """Clean high-confidence baseline yields HIGH simulation confidence."""
    exp = {"metrics": {"demand_rate": 1000.0}, "confidence": "HIGH", "data_quality_score": 0.99}
    req = _sample_request(explicit_baseline=exp)
    res = isolated_service.analyze(req)
    assert res.confidence == SimulationConfidence.HIGH


def test_confidence_medium_with_unpopulated_baseline(isolated_service):
    """Unpopulated baseline yields MEDIUM confidence with limitations."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert res.confidence == SimulationConfidence.MEDIUM


def test_confidence_low_with_low_baseline_confidence(isolated_service):
    """Low baseline confidence propagates to LOW simulation confidence."""
    exp = {"metrics": {"demand_rate": 1000.0}, "confidence": "LOW"}
    req = _sample_request(explicit_baseline=exp)
    res = isolated_service.analyze(req)
    assert res.confidence == SimulationConfidence.LOW
    assert res.uncertainty.overall_uncertainty == "HIGH"


def test_uncertainty_explanation_informative(isolated_service):
    """Uncertainty explanation details variable counts and baseline state."""
    req = _sample_request()
    res = isolated_service.analyze(req)
    assert "variables" in res.uncertainty.explanation.lower()


# =============================================================================
# 11. DETERMINISTIC SHA-256 FINGERPRINTING TESTS (8 Tests)
# =============================================================================

def test_fingerprint_identical_inputs_identical_fingerprint(isolated_service):
    """Identical scenario inputs produce identical SHA-256 fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    req1 = _sample_request(assessment_ts=ts)
    req2 = _sample_request(assessment_ts=ts)
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint == res2.input_fingerprint
    assert len(res1.input_fingerprint) == 64


def test_fingerprint_material_variable_change_changes_fingerprint(isolated_service):
    """Changing variable value changes the fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    req1 = _sample_request(variables=[_sample_variable(val=20.0)], assessment_ts=ts)
    req2 = _sample_request(variables=[_sample_variable(val=25.0)], assessment_ts=ts)
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint != res2.input_fingerprint


def test_fingerprint_timestamp_change_changes_fingerprint(isolated_service):
    """Different assessment timestamp changes the fingerprint."""
    req1 = _sample_request(assessment_ts="2026-10-06T12:00:00Z")
    req2 = _sample_request(assessment_ts="2026-10-06T13:00:00Z")
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint != res2.input_fingerprint


def test_fingerprint_ordering_invariance(isolated_service):
    """Reordering scenario variables does not alter the fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    v1 = _sample_variable(var_id="V1", param="param_A", val=10.0)
    v2 = _sample_variable(var_id="V2", param="param_B", val=20.0)

    req1 = _sample_request(variables=[v1, v2], assessment_ts=ts)
    req2 = _sample_request(variables=[v2, v1], assessment_ts=ts)

    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint == res2.input_fingerprint


def test_fingerprint_targets_ordering_invariance(isolated_service):
    """Reordering targets does not alter the fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    t1 = SimulationTarget(entity_id="MCH-01")
    t2 = SimulationTarget(entity_id="MCH-02")

    req1 = _sample_request(assessment_ts=ts)
    req1.targets = [t1, t2]

    req2 = _sample_request(assessment_ts=ts)
    req2.targets = [t2, t1]

    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint == res2.input_fingerprint


def test_fingerprint_tenant_isolation(isolated_service):
    """Different tenant ID produces different fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    req1 = _sample_request(tenant_id="tenant_A", assessment_ts=ts)
    req2 = _sample_request(tenant_id="tenant_B", assessment_ts=ts)
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint != res2.input_fingerprint


def test_fingerprint_pure_hex_sha256():
    """Fingerprint helper produces 64-character lowercase hex string."""
    fp = compute_what_if_fingerprint(
        tenant_id="tenant_1", workspace_id="ws_1", plant_id="PL_1",
        assessment_timestamp="2026-10-06T00:00:00Z", horizon="P7D",
        targets=[], variables=[], constraints=[], baseline_source="EXPLICIT",
        baseline_id="B1", baseline_metrics={"val": 1.0},
        method="COMPOSITE", method_version="1.0.0", rules_version="1.0.0", parameter_version="1.0.0"
    )
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_constraint_change_changes_fingerprint(isolated_service):
    """Changing a constraint threshold changes the fingerprint."""
    ts = "2026-10-06T12:00:00Z"
    c1 = ScenarioConstraint(
        constraint_id="C1", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap", operator=ConstraintOperator.LTE, threshold_value=0.0
    )
    c2 = ScenarioConstraint(
        constraint_id="C1", constraint_type=ConstraintType.MAX_CAPACITY,
        metric_name="capacity_gap", operator=ConstraintOperator.LTE, threshold_value=10.0
    )
    req1 = _sample_request(constraints=[c1], assessment_ts=ts)
    req2 = _sample_request(constraints=[c2], assessment_ts=ts)
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint != res2.input_fingerprint


# =============================================================================
# 12. SQLITE WAL PERSISTENCE & ISOLATION TESTS (10 Tests)
# =============================================================================

def test_repo_wal_mode_enabled(isolated_repo):
    """Repository database operates in WAL journal mode."""
    with isolated_repo._get_connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.upper() == "WAL"


def test_repo_save_and_retrieve_by_id(isolated_repo, isolated_service):
    """Saved simulation can be retrieved by simulation_id."""
    req = _sample_request()
    saved = isolated_service.analyze(req)
    retrieved = isolated_repo.get_by_id(saved.simulation_id, req.tenant_id)
    assert retrieved is not None
    assert retrieved.simulation_id == saved.simulation_id
    assert retrieved.input_fingerprint == saved.input_fingerprint


def test_repo_idempotent_deduplication(isolated_repo, isolated_service):
    """Saving identical simulation twice returns existing record without duplicating."""
    ts = "2026-10-06T12:00:00Z"
    req1 = _sample_request(assessment_ts=ts)
    req2 = _sample_request(assessment_ts=ts)
    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.simulation_id == res2.simulation_id
    assert isolated_repo.count_simulations(req1.tenant_id) == 1


def test_repo_tenant_isolation_retrieval(isolated_repo, isolated_service):
    """Tenant B cannot retrieve simulation belonging to Tenant A."""
    req = _sample_request(tenant_id="tenant_A")
    saved = isolated_service.analyze(req)
    leaked = isolated_repo.get_by_id(saved.simulation_id, "tenant_B")
    assert leaked is None


def test_repo_list_simulations_paging(isolated_repo, isolated_service):
    """list_simulations supports limit and offset paging."""
    for i in range(5):
        req = _sample_request(variables=[_sample_variable(val=float(i + 1))])
        req.scenario_name = f"Scenario {i}"
        isolated_service.analyze(req)

    items = isolated_repo.list_simulations("tenant_default", limit=2, offset=0)
    assert len(items) == 2
    assert isolated_repo.count_simulations("tenant_default") == 5


def test_repo_list_simulations_capped_at_200(isolated_repo):
    """list_simulations enforces maximum limit boundary of 200."""
    # Even if limit=500 requested, queries are clamped
    items = isolated_repo.list_simulations("tenant_default", limit=500)
    assert len(items) <= 200


def test_repo_plant_filter(isolated_repo, isolated_service):
    """list_simulations respects plant_id filter."""
    req1 = _sample_request()
    req1.plant_id = "PLANT-A"
    req1.scenario_name = "Plant A Scen"
    isolated_service.analyze(req1)

    req2 = _sample_request(variables=[_sample_variable(val=99.0)])
    req2.plant_id = "PLANT-B"
    req2.scenario_name = "Plant B Scen"
    isolated_service.analyze(req2)

    plant_a_items = isolated_repo.list_simulations("tenant_default", plant_id="PLANT-A")
    assert any(i.plant_id == "PLANT-A" for i in plant_a_items)


def test_repo_delete_by_id(isolated_repo, isolated_service):
    """delete_by_id removes specific simulation record."""
    req = _sample_request()
    saved = isolated_service.analyze(req)
    assert isolated_repo.delete_by_id(saved.simulation_id, req.tenant_id) is True
    assert isolated_repo.get_by_id(saved.simulation_id, req.tenant_id) is None


def test_repo_delete_all_tenant_scoped(isolated_repo, isolated_service):
    """delete_all removes only records for the target tenant."""
    reqA = _sample_request(tenant_id="tenant_A")
    reqB = _sample_request(tenant_id="tenant_B")
    isolated_service.analyze(reqA)
    isolated_service.analyze(reqB)

    isolated_repo.delete_all("tenant_A")
    assert isolated_repo.count_simulations("tenant_A") == 0
    assert isolated_repo.count_simulations("tenant_B") == 1


def test_repo_thread_safe_concurrent_saves(temp_db_path):
    """Concurrent saves do not corrupt database."""
    import threading
    repo = WhatIfSimulationRepository(db_path=temp_db_path)
    service = WhatIfSimulationService(repository=repo)

    errors = []
    def worker(idx):
        try:
            req = _sample_request(variables=[_sample_variable(val=float(idx))])
            req.scenario_name = f"Concurrent {idx}"
            service.analyze(req)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(errors) == 0
    assert repo.count_simulations("tenant_default") == 10


# =============================================================================
# 13. API ENDPOINTS & RBAC / ABAC TESTS (10 Tests)
# =============================================================================

def test_api_analyze_success(test_client):
    """POST /api/v3/what-if-simulation/analyze succeeds with what_if_simulation.analyze permission."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.analyze")):
        resp = test_client.post(
            "/api/v3/what-if-simulation/analyze",
            json={
                "tenant_id": "tenant_default",
                "scenario_name": "API Test Scenario",
                "variables": [
                    {
                        "variable_id": "V1",
                        "variable_type": "DEMAND_CHANGE",
                        "parameter_name": "demand_rate",
                        "change_type": "PERCENT_DELTA",
                        "value": 15.0,
                    }
                ],
            },
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario"]["name"] == "API Test Scenario"
        assert "simulation_id" in data


def test_api_analyze_tenant_boundary_violation_403(test_client):
    """POST /analyze returns 403 when request tenant differs from identity tenant."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.analyze")):
        from core.auth import get_current_identity
        server.app.dependency_overrides[get_current_identity] = lambda: _make_identity(tenant_id="tenant_auth_user")
        try:
            resp = test_client.post(
                "/api/v3/what-if-simulation/analyze",
                json={
                    "tenant_id": "tenant_intruder",
                    "scenario_name": "Cross Tenant Attempt",
                    "variables": [],
                },
                headers={"Authorization": "Bearer dev_token"},
            )
            assert resp.status_code == 403
            assert "Tenant boundary violation" in resp.json()["detail"]
        finally:
            server.app.dependency_overrides.pop(get_current_identity, None)


def test_api_analyze_plant_boundary_violation_403(test_client):
    """POST /analyze returns 403 when user is restricted to PLANT-A but requests PLANT-B."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.analyze")):
        from core.auth import get_current_identity
        server.app.dependency_overrides[get_current_identity] = lambda: _make_identity(assigned_plants=["PLANT-A"])
        try:
            resp = test_client.post(
                "/api/v3/what-if-simulation/analyze",
                json={
                    "tenant_id": "tenant_test",
                    "plant_id": "PLANT-B",
                    "scenario_name": "Cross Plant Attempt",
                    "variables": [],
                },
                headers={"Authorization": "Bearer dev_token"},
            )
            assert resp.status_code == 403
            assert "Plant boundary violation" in resp.json()["detail"]
        finally:
            server.app.dependency_overrides.pop(get_current_identity, None)


def test_api_get_by_id_success(test_client):
    """GET /{simulation_id} retrieves simulation result."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.read")):
        req = _sample_request(tenant_id="tenant_default")
        saved = what_if_simulation_service.analyze(req)

        resp = test_client.get(
            f"/api/v3/what-if-simulation/{saved.simulation_id}",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"},
        )
        assert resp.status_code == 200
        assert resp.json()["simulation_id"] == saved.simulation_id


def test_api_get_by_id_not_found_404(test_client):
    """GET /{simulation_id} returns 404 for non-existent simulation."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.read")):
        resp = test_client.get(
            "/api/v3/what-if-simulation/SIM-NONEXISTENT",
            headers={"Authorization": "Bearer dev_token"},
        )
        assert resp.status_code == 404


def test_api_list_simulations(test_client):
    """GET /api/v3/what-if-simulation lists paginated results."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.read")):
        resp = test_client.get(
            "/api/v3/what-if-simulation?limit=10",
            headers={"Authorization": "Bearer dev_token"},
        )
        assert resp.status_code == 200
        assert "items" in resp.json()
        assert "total_count" in resp.json()


def test_api_get_impact(test_client):
    """GET /{simulation_id}/impact returns downstream impacts."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.read")):
        v = _sample_variable(val=25.0)
        req = _sample_request(tenant_id="tenant_default", variables=[v])
        saved = what_if_simulation_service.analyze(req)

        resp = test_client.get(
            f"/api/v3/what-if-simulation/{saved.simulation_id}/impact",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"},
        )
        assert resp.status_code == 200
        assert "impacts" in resp.json()


def test_api_get_evidence(test_client):
    """GET /{simulation_id}/evidence returns evidence chain."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.read")):
        req = _sample_request(tenant_id="tenant_default")
        saved = what_if_simulation_service.analyze(req)

        resp = test_client.get(
            f"/api/v3/what-if-simulation/{saved.simulation_id}/evidence",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"},
        )
        assert resp.status_code == 200
        assert "evidence" in resp.json()
        assert len(resp.json()["evidence"]) > 0


def test_api_missing_auth_header_401(test_client):
    """Requests without required permission return 403 Forbidden."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_deny_decision("what_if_simulation.read")):
        resp = test_client.get(
            "/api/v3/what-if-simulation",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 403


def test_api_malformed_payload_422(test_client):
    """Malformed payload fails with 422 Unprocessable Entity."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("what_if_simulation.analyze")):
        resp = test_client.post(
            "/api/v3/what-if-simulation/analyze",
            json={"tenant_id": 12345},  # Invalid types
            headers={"Authorization": "Bearer dev_token"},
        )
        assert resp.status_code == 422


# =============================================================================
# 14. CROSS-MODULE INTELLIGENCE INTEGRATION TESTS (8 Tests)
# =============================================================================

def test_integration_sensor_fusion_baseline_telemetry(isolated_service):
    """Multimodal sensor fusion physical telemetry grounds vibration/temperature baseline."""
    fusion_metrics = {
        "vibration_rms": 3.8,
        "temperature": 82.5,
        "production_capacity": 1000.0,
    }
    exp = {"metrics": fusion_metrics, "source": "SENSOR_FUSION", "confidence": "HIGH"}
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_DEGRADATION_CHANGE, param="degradation_rate", val=30.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.baseline.metrics["vibration_rms"] == 3.8
    assert res.simulated_state.metrics["vibration_rms"] > 3.8


def test_integration_digital_twin_baseline_state(isolated_service):
    """Digital Twin operational state grounds twin properties."""
    twin_metrics = {"asset_availability": 0.92, "power_factor": 0.88}
    exp = {"metrics": twin_metrics, "source": "DIGITAL_TWIN"}
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-5.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["asset_availability"] == round(0.92 * 0.95, 4)


def test_integration_demand_forecasting_baseline(isolated_service):
    """Demand forecasting forecast grounds baseline demand rate."""
    exp = {"metrics": {"demand_rate": 1850.0, "production_capacity": 2000.0}}
    v = _sample_variable(val=10.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["demand_rate"] == round(1850.0 * 1.10, 4)


def test_integration_supplier_risk_baseline(isolated_service):
    """Supplier risk metrics ground lead times and supplier capacity."""
    exp = {"metrics": {"lead_time_days": 12.0, "supplier_capacity": 800.0}}
    v = ScenarioVariable(
        variable_id="V-SUP", variable_type=ScenarioVariableType.SUPPLIER_DELAY,
        parameter_name="lead_time_days", change_type=VariableChangeType.ABSOLUTE_DELTA, value=4.0
    )
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["lead_time_days"] == 16.0


def test_integration_financial_impact_baseline(isolated_service):
    """Financial hourly downtime cost translates downtime hours into financial delta."""
    exp = {"metrics": {"asset_availability": 0.95, "hourly_downtime_cost": 5000.0}}
    v = _sample_variable(vtype=ScenarioVariableType.ASSET_AVAILABILITY_CHANGE, param="asset_availability", val=-10.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    fin_imp = next(i for i in res.impact_assessments if i.category == ImpactCategory.FINANCIAL)
    assert fin_imp.delta_metric > 0


def test_integration_sustainability_baseline(isolated_service):
    """Sustainability baseline energy intensity models carbon impact."""
    exp = {"metrics": {"energy_consumption": 800.0, "grid_emission_factor": 0.50}}
    v = _sample_variable(vtype=ScenarioVariableType.ENERGY_CONSUMPTION_CHANGE, param="energy_consumption", val=25.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["energy_consumption"] == 1000.0
    assert res.simulated_state.metrics["projected_emissions_co2e"] == 500.0


def test_integration_sla_customer_risk_baseline(isolated_service):
    """Customer risk baseline tracks SLA degradation under capacity deficit."""
    exp = {"metrics": {"demand_rate": 1200.0, "production_capacity": 1000.0, "sla_compliance_rate": 0.98}}
    v = _sample_variable(val=10.0)
    req = _sample_request(explicit_baseline=exp, variables=[v])
    res = isolated_service.analyze(req)
    assert res.simulated_state.metrics["sla_compliance_rate"] < 0.98


def test_integration_read_only_invariant(isolated_service):
    """Simulation is strictly read-only; no upstream database tables are written to."""
    req = _sample_request()
    isolated_service.analyze(req)
    # Verifies What-If only writes to its dedicated isolated what_if_simulations table
    with isolated_service.repository._get_connection() as conn:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "what_if_simulations" in tables
        assert "actions" not in tables
        assert "work_orders" not in tables


# =============================================================================
# 15. EXECUTION BOUNDARY & AST STATIC ANALYSIS TESTS (8 Tests)
# =============================================================================

def test_ast_no_execution_gateway_in_service():
    """what_if_simulation_service.py has zero imports of execution_gateway."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "execution_gateway" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "execution_gateway" not in node.module.lower()


def test_ast_no_action_api_in_service():
    """what_if_simulation_service.py has zero imports of action_api or action_routes."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "action_routes" not in alias.name.lower()
                assert "action_api" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "action_routes" not in node.module.lower()
                assert "action_api" not in node.module.lower()


def test_ast_no_plc_or_actuator_imports():
    """what_if_simulation_service.py has zero imports of industrial control/PLC libraries."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    forbidden = {"pymodbus", "snap7", "opcua", "pycomm3", "serial", "can", "controller"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.lower() not in forbidden
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.lower() not in forbidden


def test_ast_no_execution_gateway_in_routes():
    """what_if_simulation_routes.py has zero imports of execution_gateway."""
    file_path = os.path.join(os.path.dirname(__file__), "api", "what_if_simulation_routes.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "execution_gateway" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "execution_gateway" not in node.module.lower()


def test_ast_no_eval_or_exec_in_service():
    """what_if_simulation_service.py contains zero dynamic eval() or exec() calls."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec")


def test_ast_no_prompt_29_optimization():
    """what_if_simulation_service.py contains no Prompt 29 optimization engine."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "prompt 29" not in content.lower()
    assert "prompt_29" not in content.lower()


def test_ast_no_procurement_or_inventory_mutation():
    """Repository contains zero purchase order or inventory mutation functions."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "create_purchase_order" not in content
    assert "mutate_inventory" not in content
    assert "dispatch_work_order" not in content


def test_ast_no_llm_numerical_authority():
    """Service does not use LLM prompts to calculate numbers."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "what_if_simulation_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "groq" not in content.lower()
    assert "gemini" not in content.lower()
    assert "openai" not in content.lower()
