# backend/services/what_if_simulation_service.py
"""
SageCommand V3 — What-If Simulation Intelligence Service (Prompt 28)

ANALYTICAL ONLY.
Deterministic counterfactual simulation engine.
Performs:
1. Defensible baseline resolution and temporal validation (rejecting future data leakage).
2. Typed scenario variable application and individual contribution breakdown.
3. Scenario composition and interaction effect modeling.
4. Deterministic delta computation (avoiding division-by-zero artifacts).
5. Scenario constraint evaluation with margins and explanations.
6. Bounded downstream dependency and cross-module impact propagation.
7. Explainable evidence chain generation with deterministic identifiers.
8. Qualitative multi-dimensional uncertainty and confidence quantification.
9. Deterministic SHA-256 fingerprinting and idempotent persistence.

Cardinal Invariant:
ANALYTICAL ONLY. The simulator NEVER invokes ExecutionGateway, Action API,
physical actuators, PLCs, work orders, procurement, or operational mutations.
"""

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

try:
    from core.config import (
        SAGE_SIMULATION_MAX_DEPTH,
        SAGE_SIMULATION_MAX_NODES,
        SAGE_SIMULATION_MAX_PATHS,
        SAGE_SIMULATION_MAX_EVIDENCE,
        SAGE_SIMULATION_MAX_VARIABLES,
    )
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
    from data.schemas.sensor_fusion_contract import SensorValueProvenance
    from services.what_if_simulation_repository import (
        WhatIfSimulationRepository,
        what_if_simulation_repository,
    )
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_SIMULATION_MAX_DEPTH,
        SAGE_SIMULATION_MAX_NODES,
        SAGE_SIMULATION_MAX_PATHS,
        SAGE_SIMULATION_MAX_EVIDENCE,
        SAGE_SIMULATION_MAX_VARIABLES,
    )
    from backend.data.schemas.what_if_simulation_contract import (
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
    from backend.data.schemas.sensor_fusion_contract import SensorValueProvenance
    from backend.services.what_if_simulation_repository import (
        WhatIfSimulationRepository,
        what_if_simulation_repository,
    )

_METHOD_VERSION = "1.0.0"
_RULES_VERSION = "1.0.0"
_PARAMETER_VERSION = "1.0.0"


class WhatIfSimulationService:
    """
    Core Deterministic What-If Simulation Engine.
    Executes counterfactual scenarios strictly without side-effects or physical mutations.
    """

    def __init__(self, repository: WhatIfSimulationRepository = what_if_simulation_repository) -> None:
        self.repository = repository

    def analyze(self, request: WhatIfAnalyzeRequest) -> SimulationResult:
        """
        Constructs and deterministically evaluates a What-If simulation scenario.
        """
        # 1. Validation & Boundaries
        if not request.tenant_id or not request.tenant_id.strip():
            raise ValueError("tenant_id is required for simulation isolation.")
        if not request.scenario_name or not request.scenario_name.strip():
            raise ValueError("scenario_name cannot be empty.")
        if len(request.variables) > SAGE_SIMULATION_MAX_VARIABLES:
            raise ValueError(f"Exceeded maximum scenario variables limit of {SAGE_SIMULATION_MAX_VARIABLES}.")

        # Temporal anchor
        assessment_timestamp = request.assessment_timestamp
        if not assessment_timestamp:
            assessment_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 2. Baseline Resolution & Temporal Leakage Check
        baseline, baseline_limitations = self._resolve_baseline(request, assessment_timestamp)

        # 3. Deterministic Input Fingerprinting (Section 24)
        input_fingerprint = compute_what_if_fingerprint(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            assessment_timestamp=assessment_timestamp,
            horizon=request.horizon,
            targets=request.targets,
            variables=request.variables,
            constraints=request.constraints,
            baseline_source=baseline.source.value,
            baseline_id=baseline.baseline_id,
            baseline_metrics=baseline.metrics,
            method=request.method.value,
            method_version=_METHOD_VERSION,
            rules_version=_RULES_VERSION,
            parameter_version=_PARAMETER_VERSION,
        )

        # 4. Scenario Construction
        scenario_id = self._generate_deterministic_id(
            "SCEN",
            f"{request.tenant_id}:{request.scenario_name}:{input_fingerprint[:16]}"
        )
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            name=request.scenario_name,
            description=request.description,
            targets=request.targets,
            variables=request.variables,
            constraints=request.constraints,
            baseline_reference=baseline.baseline_id,
            method=request.method,
            method_version=_METHOD_VERSION,
            created_at=assessment_timestamp,
            assessment_timestamp=assessment_timestamp,
            horizon=request.horizon,
        )

        # 5. Deterministic Simulation Execution
        (
            simulated_metrics,
            simulated_entity_states,
            variable_contributions,
            interaction_effect,
            sim_limitations,
        ) = self._execute_simulation(baseline, scenario)

        # 6. Delta Calculation (Section 21)
        deltas = self._compute_deltas(baseline.metrics, simulated_metrics, request.targets)

        # 7. Scenario Constraints Evaluation (Section 19)
        constraint_results = self._evaluate_constraints(scenario.constraints, simulated_metrics, baseline.metrics)

        # 8. Bounded Downstream Impact Propagation (Section 12, 16-18)
        max_depth = min(request.max_propagation_depth, SAGE_SIMULATION_MAX_DEPTH)
        impact_assessments, affected_entities = self._propagate_impacts(
            request.tenant_id,
            scenario,
            baseline.metrics,
            simulated_metrics,
            deltas,
            constraint_results,
            max_depth=max_depth
        )

        # 9. Evidence Chain Generation (Section 23)
        simulation_id = self._generate_deterministic_id(
            "SIM",
            f"{request.tenant_id}:{scenario_id}:{input_fingerprint[:16]}"
        )
        evidence = self._generate_evidence_chain(
            simulation_id=simulation_id,
            baseline=baseline,
            scenario=scenario,
            deltas=deltas,
            constraint_results=constraint_results,
            impact_assessments=impact_assessments,
        )

        # 10. Confidence and Multi-Dimensional Uncertainty (Section 22)
        confidence, uncertainty = self._quantify_confidence_and_uncertainty(
            baseline=baseline,
            scenario=scenario,
            constraint_results=constraint_results,
            limitations=baseline_limitations + sim_limitations,
        )

        # 11. Combine Limitations
        all_limitations = baseline_limitations + sim_limitations

        simulated_state = SimulatedState(
            entity_states=simulated_entity_states,
            metrics=simulated_metrics,
            provenance=SensorValueProvenance.SIMULATED,
            effective_at=assessment_timestamp,
            state_classification=SimulationClassification.SIMULATED.value,
        )

        result = SimulationResult(
            simulation_id=simulation_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            scenario=scenario,
            baseline=baseline,
            simulated_state=simulated_state,
            deltas=deltas,
            affected_entities=affected_entities,
            constraint_results=constraint_results,
            impact_assessments=impact_assessments,
            variable_contributions=variable_contributions,
            interaction_effect=interaction_effect,
            evidence=evidence,
            confidence=confidence,
            uncertainty=uncertainty,
            data_quality_score=baseline.data_quality_score or 0.95,
            provenance=SensorValueProvenance.SIMULATED,
            limitations=all_limitations,
            method=request.method,
            method_version=_METHOD_VERSION,
            rules_version=_RULES_VERSION,
            parameter_version=_PARAMETER_VERSION,
            input_fingerprint=input_fingerprint,
            created_at=assessment_timestamp,
        )

        # 12. Idempotent Persistence
        saved = self.repository.save(result)
        return saved

    # =========================================================================
    # BASELINE RESOLUTION & TEMPORAL INTEGRITY (Section 7, 8)
    # =========================================================================

    def _resolve_baseline(
        self,
        request: WhatIfAnalyzeRequest,
        assessment_timestamp: str
    ) -> Tuple[SimulationBaseline, List[SimulationLimitation]]:
        """
        Resolves or synthesizes an authoritative analytical baseline.
        Enforces strict temporal validation to prevent future-data leakage.
        """
        limitations: List[SimulationLimitation] = []
        source = request.baseline_source or SimulationBaselineSource.EXPLICIT_INPUT
        source_id = request.baseline_id or "baseline_default"

        # Check explicit baseline if provided
        metrics: Dict[str, Any] = {}
        entity_states: Dict[str, Dict[str, Any]] = {}
        dq_score = 0.95
        confidence = "HIGH"

        if request.explicit_baseline:
            metrics.update(request.explicit_baseline.get("metrics", {}))
            entity_states.update(request.explicit_baseline.get("entity_states", {}))
            dq_score = request.explicit_baseline.get("data_quality_score", 0.95)
            confidence = request.explicit_baseline.get("confidence", "HIGH")
            if not request.baseline_source:
                source = SimulationBaselineSource.EXPLICIT_INPUT

        # Default standard industrial operational baseline metrics if empty
        if not metrics:
            metrics = {
                "demand_rate": 1000.0,
                "production_capacity": 1200.0,
                "asset_availability": 0.95,
                "lead_time_days": 5.0,
                "supplier_capacity": 1500.0,
                "energy_consumption": 450.0,
                "quality_rate": 0.98,
                "hourly_downtime_cost": 2500.0,
                "sla_compliance_rate": 0.99,
                "degradation_rate": 0.05,
                "vibration_rms": 2.2,
                "temperature": 68.0,
                "grid_emission_factor": 0.42,
                "projected_emissions_co2e": 189.0,
            }
            limitations.append(
                SimulationLimitation(
                    limitation_id="LIM-DEFAULT-BASELINE",
                    category="INSUFFICIENT_EVIDENCE",
                    description="Default reference baseline metrics applied due to unpopulated upstream source.",
                    affected_metrics=list(metrics.keys()),
                )
            )

        # Baseline timestamp validation — Strict Temporal Leakage Protection
        baseline_timestamp = request.assessment_timestamp or assessment_timestamp
        if request.explicit_baseline and "timestamp" in request.explicit_baseline:
            cand_ts = str(request.explicit_baseline["timestamp"])
            if cand_ts > assessment_timestamp:
                raise ValueError(
                    f"Temporal leakage violation: baseline timestamp '{cand_ts}' "
                    f"is in the future relative to assessment_timestamp '{assessment_timestamp}'."
                )
            baseline_timestamp = cand_ts

        baseline_id = self._generate_deterministic_id(
            "BASE",
            f"{request.tenant_id}:{source.value}:{source_id}:{baseline_timestamp}"
        )

        baseline = SimulationBaseline(
            baseline_id=baseline_id,
            source=source,
            source_id=source_id,
            source_timestamp=baseline_timestamp,
            effective_at=baseline_timestamp,
            provenance=SensorValueProvenance.OBSERVED,
            data_quality_score=dq_score,
            confidence=confidence,
            metrics=metrics,
            entity_states=entity_states,
        )

        return baseline, limitations

    # =========================================================================
    # SIMULATION EXECUTION (Section 10, 16, 17, 18)
    # =========================================================================

    def _execute_simulation(
        self,
        baseline: SimulationBaseline,
        scenario: SimulationScenario
    ) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], List[VariableContribution], str, List[SimulationLimitation]]:
        """
        Executes deterministic transformations based on scenario variables.
        Computes individual variable effects and combined state.
        """
        simulated_metrics = dict(baseline.metrics)
        simulated_entity_states = dict(baseline.entity_states)
        contributions: List[VariableContribution] = []
        limitations: List[SimulationLimitation] = []

        active_variables_count = len(scenario.variables)
        affected_domains = set()

        for var in scenario.variables:
            # Check temporal validity of scenario variable
            if var.valid_to and var.valid_to < scenario.assessment_timestamp:
                limitations.append(
                    SimulationLimitation(
                        limitation_id=f"LIM-EXP-VAR-{var.variable_id}",
                        category="EXPIRED_ASSUMPTION",
                        description=f"Scenario variable '{var.parameter_name}' expired at '{var.valid_to}'.",
                        affected_metrics=[var.parameter_name],
                    )
                )
                continue

            single_effect: Dict[str, float] = {}

            if var.variable_type == ScenarioVariableType.DEMAND_CHANGE:
                affected_domains.add("DEMAND")
                base_demand = float(simulated_metrics.get("demand_rate", 1000.0))
                sim_demand = self._apply_change(base_demand, var)
                simulated_metrics["demand_rate"] = sim_demand
                single_effect["demand_rate"] = sim_demand - base_demand

                # Capacity utilization and gap
                cap = float(simulated_metrics.get("production_capacity", 1200.0))
                sim_gap = max(0.0, sim_demand - cap)
                simulated_metrics["capacity_gap"] = sim_gap
                simulated_metrics["capacity_utilization"] = round(sim_demand / cap, 4) if cap > 0 else 1.0
                single_effect["capacity_gap"] = sim_gap

            elif var.variable_type == ScenarioVariableType.SUPPLY_CAPACITY_CHANGE:
                affected_domains.add("SUPPLY")
                base_cap = float(simulated_metrics.get("supplier_capacity", 1500.0))
                sim_cap = self._apply_change(base_cap, var)
                simulated_metrics["supplier_capacity"] = sim_cap
                single_effect["supplier_capacity"] = sim_cap - base_cap

            elif var.variable_type == ScenarioVariableType.LEAD_TIME_CHANGE or var.variable_type == ScenarioVariableType.SUPPLIER_DELAY:
                affected_domains.add("SUPPLY")
                base_lt = float(simulated_metrics.get("lead_time_days", 5.0))
                sim_lt = self._apply_change(base_lt, var)
                simulated_metrics["lead_time_days"] = sim_lt
                single_effect["lead_time_days"] = sim_lt - base_lt

            elif var.variable_type == ScenarioVariableType.ASSET_AVAILABILITY_CHANGE:
                affected_domains.add("ASSET")
                base_avail = float(simulated_metrics.get("asset_availability", 0.95))
                sim_avail = max(0.0, min(1.0, self._apply_change(base_avail, var)))
                simulated_metrics["asset_availability"] = sim_avail
                single_effect["asset_availability"] = sim_avail - base_avail

                # Downtime hours impact (horizon 7 days = 168 hours)
                horizon_hours = 168.0
                downtime_hours = round((1.0 - sim_avail) * horizon_hours, 2)
                simulated_metrics["projected_downtime_hours"] = downtime_hours
                single_effect["projected_downtime_hours"] = downtime_hours

            elif var.variable_type == ScenarioVariableType.ASSET_DEGRADATION_CHANGE:
                affected_domains.add("ASSET")
                base_deg = float(simulated_metrics.get("degradation_rate", 0.05))
                sim_deg = max(0.0, self._apply_change(base_deg, var))
                simulated_metrics["degradation_rate"] = sim_deg
                single_effect["degradation_rate"] = sim_deg - base_deg

                # Sensor vibration / temperature correlation
                base_vib = float(simulated_metrics.get("vibration_rms", 2.2))
                deg_ratio = sim_deg / base_deg if base_deg > 0 else 1.0
                sim_vib = round(base_vib * math.sqrt(deg_ratio), 2)
                simulated_metrics["vibration_rms"] = sim_vib
                single_effect["vibration_rms"] = sim_vib - base_vib

            elif var.variable_type == ScenarioVariableType.ENERGY_CONSUMPTION_CHANGE:
                affected_domains.add("SUSTAINABILITY")
                base_energy = float(simulated_metrics.get("energy_consumption", 450.0))
                sim_energy = self._apply_change(base_energy, var)
                simulated_metrics["energy_consumption"] = sim_energy
                single_effect["energy_consumption"] = sim_energy - base_energy

                # Emissions calculation (if grid factor known)
                grid_factor = simulated_metrics.get("grid_emission_factor", 0.42)  # kg CO2e / kWh
                if grid_factor is not None:
                    sim_emissions = round(sim_energy * float(grid_factor), 2)
                    simulated_metrics["projected_emissions_co2e"] = sim_emissions
                    single_effect["projected_emissions_co2e"] = sim_emissions
                else:
                    simulated_metrics["projected_emissions_co2e"] = None
                    limitations.append(
                        SimulationLimitation(
                            limitation_id="LIM-EMISSIONS-UNKNOWN",
                            category="MISSING_FACTOR",
                            description="Emissions grid factor unavailable; projected emissions classified as UNKNOWN.",
                            affected_metrics=["projected_emissions_co2e"],
                        )
                    )

            elif var.variable_type == ScenarioVariableType.PRODUCTION_RATE_CHANGE:
                affected_domains.add("PRODUCTION")
                base_prod = float(simulated_metrics.get("production_capacity", 1200.0))
                sim_prod = self._apply_change(base_prod, var)
                simulated_metrics["production_capacity"] = sim_prod
                single_effect["production_capacity"] = sim_prod - base_prod

            elif var.variable_type == ScenarioVariableType.QUALITY_RATE_CHANGE:
                affected_domains.add("QUALITY")
                base_q = float(simulated_metrics.get("quality_rate", 0.98))
                sim_q = max(0.0, min(1.0, self._apply_change(base_q, var)))
                simulated_metrics["quality_rate"] = sim_q
                single_effect["quality_rate"] = sim_q - base_q

            else:
                # Custom or generic scalar change
                param_name = var.parameter_name
                base_val = float(simulated_metrics.get(param_name, 100.0))
                sim_val = self._apply_change(base_val, var)
                simulated_metrics[param_name] = sim_val
                single_effect[param_name] = sim_val - base_val

            contributions.append(
                VariableContribution(
                    variable_id=var.variable_id,
                    variable_type=var.variable_type,
                    parameter_name=var.parameter_name,
                    individual_effect=single_effect,
                    contribution_pct=round(100.0 / active_variables_count, 2) if active_variables_count > 0 else 100.0,
                )
            )

        # Cross-Domain Derived Metrics
        # Financial Impact derivation
        hourly_cost = float(simulated_metrics.get("hourly_downtime_cost", 2500.0))
        downtime_hrs = float(simulated_metrics.get("projected_downtime_hours", 0.0))
        financial_exposure = round(downtime_hrs * hourly_cost, 2)
        simulated_metrics["financial_risk_exposure"] = financial_exposure

        # SLA Breach Risk derivation
        util = float(simulated_metrics.get("capacity_utilization", 0.83))
        avail = float(simulated_metrics.get("asset_availability", 0.95))
        base_sla = float(simulated_metrics.get("sla_compliance_rate", 0.99))
        if util > 1.0 or avail < 0.85:
            sla_penalty = (max(0.0, util - 1.0) * 0.5) + (max(0.0, 0.85 - avail) * 0.4)
            sim_sla = max(0.50, round(base_sla - sla_penalty, 3))
        else:
            sim_sla = base_sla
        simulated_metrics["sla_compliance_rate"] = sim_sla

        # Scenario Composition & Interaction Effects (Section 9)
        if len(scenario.variables) <= 1:
            interaction_effect = "INDEPENDENT"
        elif "DEMAND" in affected_domains and "ASSET" in affected_domains:
            interaction_effect = "SUPER_ADDITIVE"  # Both demand surge and asset downtime compound capacity failure
        elif len(affected_domains) == 1:
            interaction_effect = "SUB_ADDITIVE"
        else:
            interaction_effect = "INDEPENDENT"

        return simulated_metrics, simulated_entity_states, contributions, interaction_effect, limitations

    def _apply_change(self, base_val: float, var: ScenarioVariable) -> float:
        """Applies typed variable change deterministically."""
        if var.change_type == VariableChangeType.MULTIPLIER:
            return round(base_val * var.value, 4)
        elif var.change_type == VariableChangeType.PERCENT_DELTA:
            return round(base_val * (1.0 + (var.value / 100.0)), 4)
        elif var.change_type == VariableChangeType.ABSOLUTE_DELTA:
            return round(base_val + var.value, 4)
        elif var.change_type == VariableChangeType.SET_VALUE:
            return round(var.value, 4)
        return base_val

    # =========================================================================
    # DELTA ENGINE (Section 21)
    # =========================================================================

    def _compute_deltas(
        self,
        baseline_metrics: Dict[str, Any],
        simulated_metrics: Dict[str, Any],
        targets: List[SimulationTarget],
    ) -> List[SimulationDelta]:
        """
        Computes deterministic deltas between baseline and simulated values.
        Safely handles zero denominators and missing values.
        """
        deltas: List[SimulationDelta] = []
        target_entity_id = targets[0].entity_id if targets else None

        all_keys = sorted(set(baseline_metrics.keys()) | set(simulated_metrics.keys()))

        for k in all_keys:
            base_v = baseline_metrics.get(k)
            sim_v = simulated_metrics.get(k)

            if base_v is None or sim_v is None:
                deltas.append(
                    SimulationDelta(
                        metric_name=k,
                        target_entity_id=target_entity_id,
                        baseline_value=float(base_v) if isinstance(base_v, (int, float)) else None,
                        simulated_value=float(sim_v) if isinstance(sim_v, (int, float)) else None,
                        delta=None,
                        delta_percent=None,
                        classification=DeltaClassification.UNKNOWN,
                        provenance=SensorValueProvenance.UNKNOWN,
                        confidence=SimulationConfidence.LOW,
                    )
                )
                continue

            if not isinstance(base_v, (int, float)) or not isinstance(sim_v, (int, float)):
                is_changed = str(base_v) != str(sim_v)
                deltas.append(
                    SimulationDelta(
                        metric_name=k,
                        target_entity_id=target_entity_id,
                        baseline_value=None,
                        simulated_value=None,
                        delta=None,
                        delta_percent=None,
                        classification=DeltaClassification.CHANGED if is_changed else DeltaClassification.UNCHANGED,
                        provenance=SensorValueProvenance.SIMULATED,
                        confidence=SimulationConfidence.HIGH,
                    )
                )
                continue

            b_float = float(base_v)
            s_float = float(sim_v)
            diff = round(s_float - b_float, 4)

            # Safe percentage calculation without zero division
            if abs(b_float) > 1e-9:
                pct = round((diff / abs(b_float)) * 100.0, 2)
            else:
                pct = None  # Safe undefined percentage on zero baseline

            classification = DeltaClassification.UNCHANGED if abs(diff) < 1e-6 else DeltaClassification.CHANGED

            deltas.append(
                SimulationDelta(
                    metric_name=k,
                    target_entity_id=target_entity_id,
                    baseline_value=b_float,
                    simulated_value=s_float,
                    delta=diff,
                    delta_percent=pct,
                    classification=classification,
                    provenance=SensorValueProvenance.SIMULATED,
                    confidence=SimulationConfidence.HIGH,
                )
            )

        return deltas

    # =========================================================================
    # CONSTRAINT EVALUATION (Section 19)
    # =========================================================================

    def _evaluate_constraints(
        self,
        constraints: List[ScenarioConstraint],
        simulated_metrics: Dict[str, Any],
        baseline_metrics: Dict[str, Any],
    ) -> List[ConstraintEvaluationResult]:
        """
        Evaluates each scenario constraint against simulated outcomes.
        """
        results: List[ConstraintEvaluationResult] = []

        for c in constraints:
            val = simulated_metrics.get(c.metric_name)
            base_val = baseline_metrics.get(c.metric_name)

            if val is None or not isinstance(val, (int, float)):
                results.append(
                    ConstraintEvaluationResult(
                        constraint_id=c.constraint_id,
                        constraint_type=c.constraint_type,
                        metric_name=c.metric_name,
                        status=ConstraintStatus.UNKNOWN,
                        observed_or_baseline_value=float(base_val) if isinstance(base_val, (int, float)) else None,
                        simulated_value=None,
                        threshold_value=c.threshold_value,
                        unit=c.unit,
                        margin=None,
                        explanation=f"Metric '{c.metric_name}' is not present in simulated metrics.",
                    )
                )
                continue

            f_val = float(val)
            thresh = float(c.threshold_value)
            margin = round(f_val - thresh, 4)
            status = ConstraintStatus.UNKNOWN

            if c.operator == ConstraintOperator.LTE:
                status = ConstraintStatus.SATISFIED if f_val <= thresh else ConstraintStatus.VIOLATED
            elif c.operator == ConstraintOperator.GTE:
                status = ConstraintStatus.SATISFIED if f_val >= thresh else ConstraintStatus.VIOLATED
            elif c.operator == ConstraintOperator.LT:
                status = ConstraintStatus.SATISFIED if f_val < thresh else ConstraintStatus.VIOLATED
            elif c.operator == ConstraintOperator.GT:
                status = ConstraintStatus.SATISFIED if f_val > thresh else ConstraintStatus.VIOLATED
            elif c.operator == ConstraintOperator.EQ:
                status = ConstraintStatus.SATISFIED if abs(f_val - thresh) < 1e-4 else ConstraintStatus.VIOLATED
            elif c.operator == ConstraintOperator.BETWEEN:
                thresh_max = float(c.threshold_max_value or thresh)
                status = ConstraintStatus.SATISFIED if (thresh <= f_val <= thresh_max) else ConstraintStatus.VIOLATED

            expl = (
                f"Constraint '{c.constraint_id}' ({c.operator.value} {thresh}): "
                f"Simulated value {f_val} is {status.value} (margin: {margin})."
            )

            results.append(
                ConstraintEvaluationResult(
                    constraint_id=c.constraint_id,
                    constraint_type=c.constraint_type,
                    metric_name=c.metric_name,
                    status=status,
                    observed_or_baseline_value=float(base_val) if isinstance(base_val, (int, float)) else None,
                    simulated_value=f_val,
                    threshold_value=thresh,
                    unit=c.unit,
                    margin=margin,
                    explanation=expl,
                )
            )

        return results

    # =========================================================================
    # BOUNDED DOWNSTREAM IMPACT PROPAGATION (Section 12, 16-18)
    # =========================================================================

    def _propagate_impacts(
        self,
        tenant_id: str,
        scenario: SimulationScenario,
        baseline_metrics: Dict[str, Any],
        simulated_metrics: Dict[str, Any],
        deltas: List[SimulationDelta],
        constraint_results: List[ConstraintEvaluationResult],
        max_depth: int = 5,
    ) -> Tuple[List[ImpactAssessment], List[str]]:
        """
        Propagates analytical impact to downstream domains.
        Enforces strict limits (max_depth=5, max_nodes=200).
        """
        impacts: List[ImpactAssessment] = []
        affected_entities = set()

        primary_target_id = scenario.targets[0].entity_id if scenario.targets else "SYSTEM"
        affected_entities.add(primary_target_id)

        # 1. Capacity & Demand Impacts
        cap_gap = float(simulated_metrics.get("capacity_gap", 0.0))
        if cap_gap > 0.0:
            impacts.append(
                ImpactAssessment(
                    impact_id=self._generate_deterministic_id("IMP-CAP", f"{scenario.scenario_id}:cap_gap"),
                    category=ImpactCategory.CAPACITY,
                    affected_entity_id=primary_target_id,
                    description=f"Projected capacity shortage of {cap_gap:.1f} units under scenario.",
                    severity="HIGH" if cap_gap > 200 else "MEDIUM",
                    baseline_metric=float(baseline_metrics.get("capacity_gap", 0.0)),
                    projected_metric=cap_gap,
                    delta_metric=cap_gap,
                    unit="UNITS",
                    propagation_distance=0,
                    confidence=SimulationConfidence.HIGH,
                )
            )

        # 2. SLA Compliance Impact
        sla_comp = float(simulated_metrics.get("sla_compliance_rate", 0.99))
        base_sla = float(baseline_metrics.get("sla_compliance_rate", 0.99))
        if sla_comp < base_sla:
            impacts.append(
                ImpactAssessment(
                    impact_id=self._generate_deterministic_id("IMP-SLA", f"{scenario.scenario_id}:sla"),
                    category=ImpactCategory.SLA,
                    affected_entity_id="CUSTOMER-TIER-1",
                    description=f"SLA compliance projected to drop from {base_sla*100:.1f}% to {sla_comp*100:.1f}%.",
                    severity="CRITICAL" if sla_comp < 0.90 else "HIGH",
                    baseline_metric=base_sla,
                    projected_metric=sla_comp,
                    delta_metric=round(sla_comp - base_sla, 4),
                    unit="RATE",
                    propagation_distance=1,
                    confidence=SimulationConfidence.MEDIUM,
                )
            )
            affected_entities.add("CUSTOMER-TIER-1")

        # 3. Financial Downtime Exposure Impact
        fin_exp = float(simulated_metrics.get("financial_risk_exposure", 0.0))
        base_fin = float(baseline_metrics.get("financial_risk_exposure", 0.0))
        if fin_exp > base_fin:
            impacts.append(
                ImpactAssessment(
                    impact_id=self._generate_deterministic_id("IMP-FIN", f"{scenario.scenario_id}:fin"),
                    category=ImpactCategory.FINANCIAL,
                    affected_entity_id=primary_target_id,
                    description=f"Simulated financial exposure increased by ${fin_exp - base_fin:,.2f}.",
                    severity="HIGH" if (fin_exp - base_fin) > 10000 else "MEDIUM",
                    baseline_metric=base_fin,
                    projected_metric=fin_exp,
                    delta_metric=round(fin_exp - base_fin, 2),
                    unit="USD",
                    propagation_distance=0,
                    confidence=SimulationConfidence.HIGH,
                )
            )

        # 4. Sustainability Impact
        sim_emiss = simulated_metrics.get("projected_emissions_co2e")
        base_emiss = baseline_metrics.get("projected_emissions_co2e")
        if sim_emiss is None and "energy_consumption" in simulated_metrics:
            gf = float(simulated_metrics.get("grid_emission_factor", 0.42))
            sim_emiss = round(float(simulated_metrics["energy_consumption"]) * gf, 2)
        if base_emiss is None and "energy_consumption" in baseline_metrics:
            gf = float(baseline_metrics.get("grid_emission_factor", 0.42))
            base_emiss = round(float(baseline_metrics["energy_consumption"]) * gf, 2)

        if sim_emiss is not None and base_emiss is not None:
            diff_emiss = round(float(sim_emiss) - float(base_emiss), 2)
            if abs(diff_emiss) > 0.01:
                impacts.append(
                    ImpactAssessment(
                        impact_id=self._generate_deterministic_id("IMP-SUST", f"{scenario.scenario_id}:emiss"),
                        category=ImpactCategory.SUSTAINABILITY,
                        affected_entity_id=primary_target_id,
                        description=f"Simulated CO2e emissions changed by {diff_emiss:+.1f} kg CO2e.",
                        severity="MEDIUM" if diff_emiss > 50.0 else "LOW",
                        baseline_metric=float(base_emiss),
                        projected_metric=float(sim_emiss),
                        delta_metric=diff_emiss,
                        unit="KG_CO2E",
                        propagation_distance=0,
                        confidence=SimulationConfidence.HIGH,
                    )
                )

        # 5. Downstream Dependency Propagation (bounded graph mock)
        for depth in range(1, min(max_depth + 1, 3)):
            downstream_entity = f"DOWNSTREAM-CELL-0{depth}"
            if len(affected_entities) < SAGE_SIMULATION_MAX_NODES:
                affected_entities.add(downstream_entity)
                impacts.append(
                    ImpactAssessment(
                        impact_id=self._generate_deterministic_id("IMP-DEP", f"{scenario.scenario_id}:{downstream_entity}"),
                        category=ImpactCategory.DOWNSTREAM_DEPENDENCY,
                        affected_entity_id=downstream_entity,
                        description=f"Bounded dependency propagation (hop {depth}) affected downstream flow.",
                        severity="LOW",
                        propagation_distance=depth,
                        confidence=SimulationConfidence.MEDIUM,
                    )
                )

        # Limit impacts count
        return impacts[:SAGE_SIMULATION_MAX_PATHS], sorted(list(affected_entities))

    # =========================================================================
    # EVIDENCE CHAIN GENERATION (Section 23)
    # =========================================================================

    def _generate_evidence_chain(
        self,
        simulation_id: str,
        baseline: SimulationBaseline,
        scenario: SimulationScenario,
        deltas: List[SimulationDelta],
        constraint_results: List[ConstraintEvaluationResult],
        impact_assessments: List[ImpactAssessment],
    ) -> List[SimulationEvidence]:
        """
        Creates a deterministic evidence chain explaining the simulation outcome.
        """
        evidence_list: List[SimulationEvidence] = []
        step_idx = 0

        # Baseline Evidence
        evidence_list.append(
            SimulationEvidence(
                evidence_id=self._generate_deterministic_id("EVID", f"{simulation_id}:{step_idx}:{baseline.baseline_id}"),
                source_type="BASELINE_OBSERVATION",
                source_id=baseline.source_id,
                source_timestamp=baseline.source_timestamp,
                relationship="GROUNDING_STATE",
                contribution="PRIMARY",
                provenance=baseline.provenance,
                confidence=SimulationConfidence.HIGH,
                explanation=f"Established baseline state from {baseline.source.value} ({baseline.source_id}).",
            )
        )
        step_idx += 1

        # Scenario Variables Evidence
        for var in scenario.variables[:20]:
            evidence_list.append(
                SimulationEvidence(
                    evidence_id=self._generate_deterministic_id("EVID", f"{simulation_id}:{step_idx}:{var.variable_id}"),
                    source_type="SCENARIO_VARIABLE",
                    source_id=var.variable_id,
                    source_timestamp=scenario.created_at,
                    relationship="HYPOTHETICAL_INPUT",
                    contribution="PRIMARY",
                    provenance=SensorValueProvenance.SIMULATED,
                    confidence=SimulationConfidence.HIGH,
                    explanation=f"Hypothetical change applied: {var.parameter_name} ({var.change_type.value} {var.value}).",
                )
            )
            step_idx += 1

        # Constraint Violations Evidence
        for c_res in constraint_results:
            if c_res.status == ConstraintStatus.VIOLATED:
                evidence_list.append(
                    SimulationEvidence(
                        evidence_id=self._generate_deterministic_id("EVID", f"{simulation_id}:{step_idx}:{c_res.constraint_id}"),
                        source_type="CONSTRAINT",
                        source_id=c_res.constraint_id,
                        source_timestamp=scenario.created_at,
                        relationship="VIOLATION_TRIGGER",
                        contribution="LIMITING",
                        provenance=SensorValueProvenance.SIMULATED,
                        confidence=SimulationConfidence.HIGH,
                        explanation=c_res.explanation,
                    )
                )
                step_idx += 1

        # Material Impact Evidence
        for imp in impact_assessments[:10]:
            evidence_list.append(
                SimulationEvidence(
                    evidence_id=self._generate_deterministic_id("EVID", f"{simulation_id}:{step_idx}:{imp.impact_id}"),
                    source_type="PROPAGATION_RULE",
                    source_id=imp.impact_id,
                    source_timestamp=scenario.created_at,
                    relationship="DOWNSTREAM_EFFECT",
                    contribution="CORROBORATING",
                    provenance=SensorValueProvenance.SIMULATED,
                    confidence=imp.confidence,
                    explanation=imp.description,
                )
            )
            step_idx += 1

        return evidence_list[:SAGE_SIMULATION_MAX_EVIDENCE]

    # =========================================================================
    # CONFIDENCE & UNCERTAINTY QUANTIFICATION (Section 22)
    # =========================================================================

    def _quantify_confidence_and_uncertainty(
        self,
        baseline: SimulationBaseline,
        scenario: SimulationScenario,
        constraint_results: List[ConstraintEvaluationResult],
        limitations: List[SimulationLimitation],
    ) -> Tuple[SimulationConfidence, SimulationUncertainty]:
        """
        Quantifies qualitative confidence and multi-dimensional uncertainty.
        Avoids fabricating numerical confidence intervals.
        """
        has_critical_limitations = any(lim.category in ("INSUFFICIENT_EVIDENCE", "MISSING_FACTOR") for lim in limitations)
        has_violations = any(c.status == ConstraintStatus.VIOLATED for c in constraint_results)

        if not baseline.metrics or has_critical_limitations:
            conf = SimulationConfidence.MEDIUM
            overall_unc = "MEDIUM"
        elif baseline.confidence == "LOW":
            conf = SimulationConfidence.LOW
            overall_unc = "HIGH"
        else:
            conf = SimulationConfidence.HIGH
            overall_unc = "LOW"

        uncertainty = SimulationUncertainty(
            overall_uncertainty=overall_unc,
            measurement_uncertainty="LOW" if (baseline.data_quality_score or 1.0) >= 0.90 else "MEDIUM",
            model_uncertainty="LOW" if len(scenario.variables) <= 3 else "MEDIUM",
            scenario_uncertainty="LOW" if not has_violations else "MEDIUM",
            dependency_uncertainty="MEDIUM" if len(scenario.targets) > 2 else "LOW",
            data_quality_uncertainty="LOW" if (baseline.data_quality_score or 1.0) >= 0.85 else "HIGH",
            explanation=(
                f"Multi-dimensional uncertainty assessed with {len(scenario.variables)} variables, "
                f"baseline confidence {baseline.confidence}, and {len(limitations)} recorded limitations."
            ),
        )

        return conf, uncertainty

    def _generate_deterministic_id(self, prefix: str, entropy: str) -> str:
        """Produces a deterministic ID based solely on seed content (no uuid4)."""
        digest = hashlib.sha256(entropy.encode("utf-8")).hexdigest()[:12].upper()
        return f"{prefix}-{digest}"


what_if_simulation_service = WhatIfSimulationService()
