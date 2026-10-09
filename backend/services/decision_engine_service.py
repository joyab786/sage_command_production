# backend/services/decision_engine_service.py
"""
SageCommand V3 — Decision Engine Foundation Service (Prompt 30)

ANALYTICAL DECISION SUPPORT ONLY.
Orchestrates deterministic evaluation of decision problems, candidate courses of action,
hard constraints, soft preferences, trusted governance policies, upstream evidence chains,
trade-offs, uncertainty quantification, and auditable recommendations.

Cardinal Invariant:
The Decision Engine layer produces governed ANALYTICAL RECOMMENDATIONS.
It is NOT an operational execution system.
It NEVER executes physical commands, writes to PLCs/controllers,
dispatches work orders, issues purchase orders, mutates inventories,
or bypasses independently enforced authorization and execution boundaries.

Boundary:
DECISION ENGINE -> RECOMMENDATION -> HUMAN / AUTHORIZED OPERATOR -> [existing governed Execution Gateway]
Never: DECISION ENGINE -> AUTOMATIC EXECUTION.
"""

import math
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_DECISION_MAX_OPTIONS,
        SAGE_DECISION_MAX_CRITERIA,
        SAGE_DECISION_MAX_CONSTRAINTS,
        SAGE_DECISION_MAX_POLICIES,
        SAGE_DECISION_MAX_EVIDENCE,
    )
    from data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionEvaluation,
        DecisionRecommendation,
        DecisionOption,
        DecisionCriterion,
        CriterionEvaluation,
        DecisionConstraint,
        ConstraintEvaluationResult,
        DecisionPolicy,
        DecisionPolicyEvaluation,
        DecisionAlternative,
        DecisionEvidenceReference,
        DecisionLimitation,
        DecisionUncertainty,
        DecisionTradeoff,
        DecisionOutcomeStatus,
        DecisionType,
        DecisionScope,
        CriterionDirection,
        ConstraintOperator,
        HardOrSoft,
        PolicyComplianceStatus,
        ConfidenceLevel,
        ComparisonMethod,
        compute_decision_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        MANDATORY_EXECUTION_NOTICE,
    )
    from repositories.decision_engine_repository import (
        DecisionEngineRepository,
        decision_engine_repository,
    )
except ModuleNotFoundError:
    from backend.core.config import (
        SAGE_DECISION_MAX_OPTIONS,
        SAGE_DECISION_MAX_CRITERIA,
        SAGE_DECISION_MAX_CONSTRAINTS,
        SAGE_DECISION_MAX_POLICIES,
        SAGE_DECISION_MAX_EVIDENCE,
    )
    from backend.data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionEvaluation,
        DecisionRecommendation,
        DecisionOption,
        DecisionCriterion,
        CriterionEvaluation,
        DecisionConstraint,
        ConstraintEvaluationResult,
        DecisionPolicy,
        DecisionPolicyEvaluation,
        DecisionAlternative,
        DecisionEvidenceReference,
        DecisionLimitation,
        DecisionUncertainty,
        DecisionTradeoff,
        DecisionOutcomeStatus,
        DecisionType,
        DecisionScope,
        CriterionDirection,
        ConstraintOperator,
        HardOrSoft,
        PolicyComplianceStatus,
        ConfidenceLevel,
        ComparisonMethod,
        compute_decision_fingerprint,
        FORBIDDEN_ACTUATION_KEYWORDS,
        MANDATORY_EXECUTION_NOTICE,
    )
    from backend.repositories.decision_engine_repository import (
        DecisionEngineRepository,
        decision_engine_repository,
    )


# =============================================================================
# 1. EVALUATION ENGINES
# =============================================================================

class ConstraintEvaluationEngine:
    """Evaluates hard constraints and soft preferences against option parameters/outcomes."""

    @staticmethod
    def evaluate(
        constraint: DecisionConstraint,
        option: DecisionOption,
    ) -> ConstraintEvaluationResult:
        field_name = constraint.target_field
        # Look in expected_outcomes first, then parameters
        observed = option.expected_outcomes.get(field_name)
        if observed is None:
            observed = option.parameters.get(field_name)

        if observed is None:
            return ConstraintEvaluationResult(
                constraint_id=constraint.constraint_id,
                option_id=option.option_id,
                hard_or_soft=constraint.hard_or_soft,
                satisfied=False,
                observed_value="MISSING",
                threshold_value=constraint.threshold_value,
                margin=None,
                explanation=f"Target field '{field_name}' is missing in option '{option.option_id}'.",
            )

        # Numerical comparison
        if isinstance(observed, (int, float)) and isinstance(constraint.threshold_value, (int, float)):
            obs_num = float(observed)
            thresh_num = float(constraint.threshold_value)
            satisfied = False
            margin = None

            if constraint.operator in (ConstraintOperator.LTE, "<="):
                satisfied = obs_num <= thresh_num
                margin = thresh_num - obs_num
            elif constraint.operator in (ConstraintOperator.GTE, ">="):
                satisfied = obs_num >= thresh_num
                margin = obs_num - thresh_num
            elif constraint.operator in (ConstraintOperator.LT, "<"):
                satisfied = obs_num < thresh_num
                margin = thresh_num - obs_num
            elif constraint.operator in (ConstraintOperator.GT, ">"):
                satisfied = obs_num > thresh_num
                margin = obs_num - thresh_num
            elif constraint.operator in (ConstraintOperator.EQ, "=="):
                satisfied = math.isclose(obs_num, thresh_num, abs_tol=1e-5)
                margin = -abs(obs_num - thresh_num)
            elif constraint.operator in (ConstraintOperator.IN, "IN"):
                satisfied = obs_num == thresh_num
                margin = 0.0 if satisfied else -1.0

            margin_val = round(margin, 4) if margin is not None else None
            status_desc = "Satisfied" if satisfied else "Violated"
            explanation = f"{constraint.name} ({constraint.hard_or_soft.value}): observed {obs_num} vs limit {thresh_num} ({status_desc}, margin: {margin_val})."

            return ConstraintEvaluationResult(
                constraint_id=constraint.constraint_id,
                option_id=option.option_id,
                hard_or_soft=constraint.hard_or_soft,
                satisfied=satisfied,
                observed_value=obs_num,
                threshold_value=thresh_num,
                margin=margin_val,
                explanation=explanation,
            )

        # Categorical / list / string comparison
        satisfied = False
        if constraint.operator in (ConstraintOperator.EQ, "=="):
            satisfied = str(observed).strip().lower() == str(constraint.threshold_value).strip().lower()
        elif constraint.operator in (ConstraintOperator.IN, "IN"):
            if isinstance(constraint.threshold_value, list):
                satisfied = observed in constraint.threshold_value or str(observed) in [str(x) for x in constraint.threshold_value]
            else:
                satisfied = str(observed) == str(constraint.threshold_value)

        status_desc = "Satisfied" if satisfied else "Violated"
        explanation = f"{constraint.name} ({constraint.hard_or_soft.value}): observed '{observed}' vs limit '{constraint.threshold_value}' ({status_desc})."

        return ConstraintEvaluationResult(
            constraint_id=constraint.constraint_id,
            option_id=option.option_id,
            hard_or_soft=constraint.hard_or_soft,
            satisfied=satisfied,
            observed_value=observed,
            threshold_value=constraint.threshold_value,
            margin=0.0 if satisfied else -1.0,
            explanation=explanation,
        )


class CriterionScoringEngine:
    """Calculates normalized and weighted scores for criteria."""

    @staticmethod
    def extract_raw_value(criterion: DecisionCriterion, option: DecisionOption) -> Optional[float]:
        cid = criterion.criterion_id
        val = option.expected_outcomes.get(cid)
        if val is None:
            val = option.parameters.get(cid)
        if val is None:
            # Check by criterion type name (e.g. "COST", "RISK")
            val = option.expected_outcomes.get(criterion.criterion_type.value)
            if val is None:
                val = option.parameters.get(criterion.criterion_type.value)
        if val is not None:
            try:
                f_val = float(val)
                if not (math.isnan(f_val) or math.isinf(f_val)):
                    return f_val
            except (ValueError, TypeError):
                pass
        return None

    @classmethod
    def evaluate_all(
        cls,
        criteria: List[DecisionCriterion],
        options: List[DecisionOption],
    ) -> Tuple[List[CriterionEvaluation], Dict[str, Dict[str, float]], Dict[str, Dict[str, float]]]:
        """
        Computes min-max bounds per criterion, normalizes each option score to [0.0, 1.0],
        and returns criterion evaluations, normalized score map, and raw value map.
        """
        raw_values: Dict[str, Dict[str, float]] = {c.criterion_id: {} for c in criteria}
        total_weight = sum(c.weight for c in criteria)
        normalized_weights = {c.criterion_id: (c.weight / total_weight if total_weight > 0 else 1.0 / len(criteria)) for c in criteria}

        for c in criteria:
            for opt in options:
                v = cls.extract_raw_value(c, opt)
                if v is not None:
                    raw_values[c.criterion_id][opt.option_id] = v

        criterion_evaluations: List[CriterionEvaluation] = []
        option_norm_scores: Dict[str, Dict[str, float]] = {opt.option_id: {} for opt in options}
        option_raw_map: Dict[str, Dict[str, float]] = {opt.option_id: {} for opt in options}

        for c in criteria:
            c_raws = raw_values[c.criterion_id]
            vals = list(c_raws.values())
            min_val = min(vals) if vals else 0.0
            max_val = max(vals) if vals else 1.0
            span = max_val - min_val

            for opt in options:
                raw_val = c_raws.get(opt.option_id, 0.0)
                option_raw_map[opt.option_id][c.criterion_id] = raw_val

                # Normalize to [0.0, 1.0] where 1.0 is always best
                if span > 1e-9:
                    norm = (raw_val - min_val) / span
                else:
                    norm = 1.0

                if c.direction == CriterionDirection.MINIMIZE:
                    # Lower raw value is better
                    norm_score = 1.0 - norm
                else:
                    norm_score = norm

                norm_score = max(0.0, min(1.0, norm_score))
                weighted_score = norm_score * normalized_weights[c.criterion_id]

                option_norm_scores[opt.option_id][c.criterion_id] = norm_score

                eval_item = CriterionEvaluation(
                    criterion_id=c.criterion_id,
                    option_id=opt.option_id,
                    raw_value=round(raw_val, 4),
                    normalized_score=round(norm_score, 4),
                    weighted_score=round(weighted_score, 4),
                    direction=c.direction,
                    unit=c.unit,
                    notes=f"Direction: {c.direction.value}, weight: {round(normalized_weights[c.criterion_id], 4)}",
                )
                criterion_evaluations.append(eval_item)

        return criterion_evaluations, option_norm_scores, option_raw_map


class PolicyEvaluationEngine:
    """Evaluates trusted governance policies against candidate options."""

    @staticmethod
    def evaluate(policy: DecisionPolicy, option: DecisionOption, scope: DecisionScope) -> DecisionPolicyEvaluation:
        rules = policy.rules
        option_params = {**option.parameters, **option.expected_outcomes}
        now_iso = datetime.now(timezone.utc).isoformat()

        # Check rules
        for r_key, r_val in rules.items():
            target_key = None
            if r_key in option_params:
                target_key = r_key
            else:
                clean_key = r_key.lower().replace("max_", "").replace("min_", "").replace("ceiling_", "").replace("limit_", "")
                if clean_key in option_params:
                    target_key = clean_key

            if target_key:
                opt_v = option_params[target_key]
                if isinstance(r_val, (int, float)) and isinstance(opt_v, (int, float)):
                    if r_key.lower().startswith("min_"):
                        if opt_v < r_val:
                            return DecisionPolicyEvaluation(
                                policy_id=policy.policy_id,
                                policy_version=policy.version,
                                option_id=option.option_id,
                                status=PolicyComplianceStatus.VIOLATED,
                                reason=f"Policy rule '{r_key}' breached: {opt_v} < floor {r_val}.",
                                evaluated_at=now_iso,
                            )
                    else:
                        if opt_v > r_val:
                            return DecisionPolicyEvaluation(
                                policy_id=policy.policy_id,
                                policy_version=policy.version,
                                option_id=option.option_id,
                                status=PolicyComplianceStatus.VIOLATED,
                                reason=f"Policy rule '{r_key}' exceeded: {opt_v} > ceiling {r_val}.",
                                evaluated_at=now_iso,
                            )
                elif isinstance(r_val, list):
                    if opt_v not in r_val and str(opt_v) not in [str(x) for x in r_val]:
                        return DecisionPolicyEvaluation(
                            policy_id=policy.policy_id,
                            policy_version=policy.version,
                            option_id=option.option_id,
                            status=PolicyComplianceStatus.VIOLATED,
                            reason=f"Policy rule '{r_key}' mismatch: '{opt_v}' not in approved list {r_val}.",
                            evaluated_at=now_iso,
                        )

        return DecisionPolicyEvaluation(
            policy_id=policy.policy_id,
            policy_version=policy.version,
            option_id=option.option_id,
            status=PolicyComplianceStatus.COMPLIANT,
            reason=f"Option satisfies governance policy {policy.policy_id} v{policy.version}.",
            evaluated_at=now_iso,
        )


class TradeoffEngine:
    """Computes explicit trade-offs and sensitivity between top candidates."""

    @staticmethod
    def compute_tradeoffs(
        top_alt: DecisionAlternative,
        runner_up_alt: Optional[DecisionAlternative],
        criteria: List[DecisionCriterion],
    ) -> List[DecisionTradeoff]:
        tradeoffs: List[DecisionTradeoff] = []
        if not runner_up_alt:
            return tradeoffs

        for c in criteria:
            cid = c.criterion_id
            score_a = top_alt.criteria_scores.get(cid, 0.0)
            score_b = runner_up_alt.criteria_scores.get(cid, 0.0)
            delta = round(score_a - score_b, 4)

            raw_a = top_alt.criteria_raw_values.get(cid, 0.0)
            raw_b = runner_up_alt.criteria_raw_values.get(cid, 0.0)
            raw_delta = round(raw_a - raw_b, 4)

            # Look for trade-offs where top candidate gains in one criterion but loses or ties in another
            if abs(delta) > 0.01:
                desc = f"For criterion '{c.name}', top option '{top_alt.option_id}' score delta is {delta:+.4f} (raw delta: {raw_delta:+.2f} {c.unit or ''}) vs runner-up '{runner_up_alt.option_id}'."
                tradeoffs.append(
                    DecisionTradeoff(
                        criterion_a=cid,
                        criterion_b=cid,
                        description=desc,
                        impact_delta=delta,
                        sensitivity_ratio=round(abs(delta) / (runner_up_alt.composite_score or 1.0), 4),
                    )
                )

        return sorted(tradeoffs, key=lambda t: abs(t.impact_delta), reverse=True)[:5]


# =============================================================================
# 2. DECISION ENGINE SERVICE ORCHESTRATOR
# =============================================================================

class DecisionEngineService:
    """
    Production-ready, deterministic Decision Engine service.
    Consumes governed context, evaluates policies and constraints, ranks options,
    computes trade-offs and uncertainties, and persists auditable recommendations.
    """

    def __init__(self, repository: Optional[DecisionEngineRepository] = None):
        self.repository = repository or decision_engine_repository

    def evaluate(
        self,
        request: DecisionRequest,
        actor_id: str = "system",
    ) -> DecisionEvaluation:
        """
        Executes the 18-step deterministic decision evaluation pipeline.
        Returns a structured DecisionEvaluation with MANDATORY_EXECUTION_NOTICE.
        """
        # Step 1: Validate request and scope
        self._validate_request_boundaries(request)

        # Fixed assessment timestamp
        assessment_ts = request.assessment_timestamp or datetime.now(timezone.utc).isoformat()

        # Step 2 & 3 & 4: Check evidence temporal validity, quality, and freshness
        limitations: List[DecisionLimitation] = []
        uncertainties: List[DecisionUncertainty] = []
        valid_evidence, evidence_limitations = self._evaluate_evidence(request.evidence_references, assessment_ts)
        limitations.extend(evidence_limitations)

        # Step 5: Validate candidate options against forbidden actuation keywords
        for opt in request.options:
            for forbidden in FORBIDDEN_ACTUATION_KEYWORDS:
                if forbidden in opt.option_id.upper() or forbidden in opt.name.upper():
                    raise ValueError(f"Option '{opt.option_id}' contains forbidden actuation keyword: {forbidden}")

        # Step 6: Evaluate hard and soft constraints for all options
        constraint_evaluations: List[ConstraintEvaluationResult] = []
        option_feasibility: Dict[str, bool] = {}
        option_violations: Dict[str, List[str]] = {opt.option_id: [] for opt in request.options}
        option_binding: Dict[str, List[str]] = {opt.option_id: [] for opt in request.options}

        for opt in request.options:
            is_feasible = True
            for c in request.constraints:
                c_res = ConstraintEvaluationEngine.evaluate(c, opt)
                constraint_evaluations.append(c_res)
                if not c_res.satisfied:
                    if c.hard_or_soft == HardOrSoft.HARD:
                        is_feasible = False
                        option_violations[opt.option_id].append(c_res.explanation)
                        option_binding[opt.option_id].append(c.constraint_id)
                    else:
                        option_violations[opt.option_id].append(f"Soft preference violation: {c_res.explanation}")
            option_feasibility[opt.option_id] = is_feasible

        # Step 7 & 8: Score criteria and normalize
        criterion_evaluations, norm_scores, raw_scores = CriterionScoringEngine.evaluate_all(
            request.criteria,
            request.options,
        )

        # Step 9: Evaluate policy compliance
        policy_evaluations: List[DecisionPolicyEvaluation] = []
        option_policy_compliance: Dict[str, bool] = {}

        for opt in request.options:
            compliant = True
            for policy in request.policies:
                if not policy.is_active:
                    continue
                p_res = PolicyEvaluationEngine.evaluate(policy, opt, request.scope)
                policy_evaluations.append(p_res)
                if p_res.status == PolicyComplianceStatus.VIOLATED:
                    compliant = False
                    option_violations[opt.option_id].append(f"Policy violation ({policy.policy_id}): {p_res.reason}")
            option_policy_compliance[opt.option_id] = compliant

        # Step 10 & 11: Calculate candidate scores deterministically and rank
        alternatives: List[DecisionAlternative] = []
        total_weight = sum(c.weight for c in request.criteria)
        weights_map = {c.criterion_id: (c.weight / total_weight if total_weight > 0 else 1.0 / len(request.criteria)) for c in request.criteria}

        for opt in request.options:
            composite_score = 0.0
            if request.comparison_method == ComparisonMethod.WEIGHTED_SCORING:
                for c in request.criteria:
                    s = norm_scores[opt.option_id].get(c.criterion_id, 0.0)
                    w = weights_map.get(c.criterion_id, 0.0)
                    composite_score += s * w
            elif request.comparison_method == ComparisonMethod.LEXICOGRAPHIC:
                # Primary criterion score heavily weighted
                sorted_c = sorted(request.criteria, key=lambda x: x.priority_order)
                base_factor = 1.0
                for c in sorted_c:
                    s = norm_scores[opt.option_id].get(c.criterion_id, 0.0)
                    composite_score += s * base_factor
                    base_factor *= 0.1
            else:
                # Simple average
                scores = list(norm_scores[opt.option_id].values())
                composite_score = sum(scores) / len(scores) if scores else 0.0

            composite_score = round(composite_score, 4)

            alt = DecisionAlternative(
                option_id=opt.option_id,
                option_name=opt.name,
                rank=1,  # Placeholder, assigned below
                composite_score=composite_score,
                is_feasible=option_feasibility[opt.option_id],
                is_policy_compliant=option_policy_compliance[opt.option_id],
                is_recommended=False,
                criteria_scores=norm_scores[opt.option_id],
                criteria_raw_values=raw_scores[opt.option_id],
                binding_constraints=option_binding[opt.option_id],
                violations=option_violations[opt.option_id],
                unresolved_limitations=[],
            )
            alternatives.append(alt)

        # Stable, deterministic sorting:
        # 1. Policy compliant first
        # 2. Feasible first
        # 3. Higher composite score first
        # 4. Tie-breaking by option_id ascending
        ranked_alternatives = sorted(
            alternatives,
            key=lambda a: (
                1 if a.is_policy_compliant else 0,
                1 if a.is_feasible else 0,
                a.composite_score,
                -ord(a.option_id[0]) if a.option_id else 0,
                a.option_id,
            ),
            reverse=True,
        )

        for i, alt in enumerate(ranked_alternatives):
            alt.rank = i + 1

        # Step 12: Calculate trade-offs and sensitivity between top alternatives
        top_alt = ranked_alternatives[0] if ranked_alternatives else None
        runner_up = ranked_alternatives[1] if len(ranked_alternatives) > 1 else None
        tradeoffs = TradeoffEngine.compute_tradeoffs(top_alt, runner_up, request.criteria) if top_alt else []

        # Step 13 & 14: Determine recommendation eligibility and calculate confidence
        overall_status, confidence, rationale = self._determine_recommendation_status(
            ranked_alternatives,
            valid_evidence,
            limitations,
        )

        if top_alt and overall_status in (DecisionOutcomeStatus.RECOMMENDED, DecisionOutcomeStatus.CONDITIONALLY_RECOMMENDED):
            top_alt.is_recommended = True

        # Generate uncertainty estimate
        uncertainty_val = round(1.0 - confidence, 3)
        uncertainties.append(
            DecisionUncertainty(
                metric_name="COMPOSITE_CONFIDENCE",
                lower_bound=max(0.0, confidence - 0.1),
                upper_bound=min(1.0, confidence + 0.1),
                variance=round(uncertainty_val * 0.05, 4),
                confidence_level=ConfidenceLevel.HIGH if confidence >= 0.8 else (ConfidenceLevel.MEDIUM if confidence >= 0.5 else ConfidenceLevel.LOW),
                notes=f"Aggregated confidence: {confidence:.2f}, uncertainty index: {uncertainty_val:.2f}",
            )
        )

        # Step 15: Create Recommendation Object
        recommendation = DecisionRecommendation(
            recommended_option_id=top_alt.option_id if (top_alt and top_alt.is_recommended) else None,
            recommendation_status=overall_status,
            primary_rationale=rationale,
            confidence=round(confidence, 3),
            uncertainty_summary=f"Uncertainty: {uncertainty_val:.2f}. " + ("; ".join(l.description for l in limitations[:2]) if limitations else "Inputs verified."),
            alternatives=ranked_alternatives,
            limitations=limitations,
            tradeoffs=tradeoffs,
            mandatory_notice=MANDATORY_EXECUTION_NOTICE,
        )

        # Step 16: Compute canonical decision fingerprint
        fingerprint = compute_decision_fingerprint(
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            decision_type=request.decision_type,
            assessment_timestamp=assessment_ts,
            horizon=request.horizon,
            options=request.options,
            criteria=request.criteria,
            constraints=request.constraints,
            policies=request.policies,
            evidence_references=request.evidence_references,
            comparison_method=request.comparison_method,
            context=request.context,
        )

        # Generate decision_id
        decision_id = f"dec_{fingerprint[:16]}"
        problem_id = f"prob_{fingerprint[16:32]}"

        evaluation = DecisionEvaluation(
            decision_id=decision_id,
            problem_id=problem_id,
            tenant_id=request.tenant_id,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id,
            decision_type=request.decision_type,
            fingerprint=fingerprint,
            assessment_timestamp=assessment_ts,
            status=overall_status,
            recommendation=recommendation,
            policy_evaluations=policy_evaluations,
            constraint_evaluations=constraint_evaluations,
            criterion_evaluations=criterion_evaluations,
            limitations=limitations,
            evidence_snapshot=valid_evidence,
            uncertainties=uncertainties,
            mandatory_notice=MANDATORY_EXECUTION_NOTICE,
            metadata={
                "comparison_method": request.comparison_method.value,
                "options_count": len(request.options),
                "criteria_count": len(request.criteria),
                "constraints_count": len(request.constraints),
                "policies_count": len(request.policies),
                "evidence_count": len(valid_evidence),
            },
        )

        # Step 17: Persist evaluation and audit record
        self.repository.save_evaluation(evaluation, actor_id=actor_id)

        # Step 18: Return structured evaluation
        return evaluation

    # -------------------------------------------------------------------------
    # PRIVATE HELPER PIPELINE METHODS
    # -------------------------------------------------------------------------

    def _validate_request_boundaries(self, request: DecisionRequest) -> None:
        if len(request.options) > SAGE_DECISION_MAX_OPTIONS:
            raise ValueError(f"Number of options ({len(request.options)}) exceeds limit ({SAGE_DECISION_MAX_OPTIONS}).")
        if len(request.criteria) > SAGE_DECISION_MAX_CRITERIA:
            raise ValueError(f"Number of criteria ({len(request.criteria)}) exceeds limit ({SAGE_DECISION_MAX_CRITERIA}).")
        if len(request.constraints) > SAGE_DECISION_MAX_CONSTRAINTS:
            raise ValueError(f"Number of constraints ({len(request.constraints)}) exceeds limit ({SAGE_DECISION_MAX_CONSTRAINTS}).")
        if len(request.policies) > SAGE_DECISION_MAX_POLICIES:
            raise ValueError(f"Number of policies ({len(request.policies)}) exceeds limit ({SAGE_DECISION_MAX_POLICIES}).")
        if len(request.evidence_references) > SAGE_DECISION_MAX_EVIDENCE:
            raise ValueError(f"Number of evidence items ({len(request.evidence_references)}) exceeds limit ({SAGE_DECISION_MAX_EVIDENCE}).")

    def _evaluate_evidence(
        self,
        evidence_list: List[DecisionEvidenceReference],
        assessment_ts: str,
    ) -> Tuple[List[DecisionEvidenceReference], List[DecisionLimitation]]:
        valid_evidence: List[DecisionEvidenceReference] = []
        limitations: List[DecisionLimitation] = []

        try:
            assess_dt = datetime.fromisoformat(assessment_ts.replace("Z", "+00:00"))
        except Exception:
            assess_dt = datetime.now(timezone.utc)

        for ev in evidence_list:
            # Check temporal validity (no future leakage)
            try:
                ev_dt = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
                if ev_dt > assess_dt:
                    limitations.append(
                        DecisionLimitation(
                            limitation_id=f"lim_future_{ev.evidence_id}",
                            code="FUTURE_LEAKAGE_DETECTED",
                            description=f"Evidence {ev.evidence_id} has future timestamp ({ev.timestamp}) relative to assessment ({assessment_ts}).",
                            severity="BLOCKING",
                            mitigation="Evidence excluded from active calculation.",
                        )
                    )
                    continue
            except Exception:
                pass

            # Check freshness / stale data
            if ev.freshness_seconds is not None and ev.freshness_seconds > 86400 * 7:  # Older than 7 days
                limitations.append(
                    DecisionLimitation(
                        limitation_id=f"lim_stale_{ev.evidence_id}",
                        code="STALE_EVIDENCE",
                        description=f"Evidence {ev.evidence_id} is stale (age: {ev.freshness_seconds / 3600:.1f} hours).",
                        severity="MEDIUM",
                        mitigation="Verify upstream operational state before manual execution.",
                    )
                )

            valid_evidence.append(ev)

        return valid_evidence, limitations

    def _determine_recommendation_status(
        self,
        ranked: List[DecisionAlternative],
        evidence: List[DecisionEvidenceReference],
        limitations: List[DecisionLimitation],
    ) -> Tuple[DecisionOutcomeStatus, float, str]:
        if not ranked:
            return DecisionOutcomeStatus.EVALUATION_FAILED, 0.0, "No alternatives evaluated."

        # Check for blocking limitations
        if any(l.severity == "BLOCKING" for l in limitations):
            return DecisionOutcomeStatus.NEEDS_HUMAN_REVIEW, 0.2, "Blocking limitations detected in evidence inputs."

        top = ranked[0]

        # Case 1: Infeasible (violates hard constraints)
        if not top.is_feasible:
            all_infeasible = all(not a.is_feasible for a in ranked)
            if all_infeasible:
                return (
                    DecisionOutcomeStatus.NO_FEASIBLE_OPTION,
                    0.0,
                    f"All {len(ranked)} candidate options violate hard operational constraints. Binding constraints: {', '.join(top.binding_constraints)}.",
                )

        # Case 2: Policy blocked
        if not top.is_policy_compliant:
            return (
                DecisionOutcomeStatus.POLICY_BLOCKED,
                0.0,
                f"Candidate option '{top.option_id}' violates trusted governance policy. Violations: {'; '.join(top.violations)}.",
            )

        # Base confidence calculation
        ev_conf = (sum(e.confidence * e.quality_score for e in evidence) / len(evidence)) if evidence else 0.8
        score_conf = top.composite_score
        confidence = round(0.5 * ev_conf + 0.5 * score_conf, 3)

        # Case 3: Conflicting evidence
        if any("CONFLICT" in l.code for l in limitations):
            return DecisionOutcomeStatus.CONFLICTING_EVIDENCE, confidence * 0.5, "Conflicting evidence identified across upstream subsystems."

        # Case 4: Insufficient evidence
        if not evidence and len(limitations) > 2:
            return DecisionOutcomeStatus.INSUFFICIENT_EVIDENCE, 0.4, "Insufficient upstream evidence snapshot provided for governed recommendation."

        # Case 5: Conditionally recommended vs Recommended
        if limitations or confidence < 0.65:
            return (
                DecisionOutcomeStatus.CONDITIONALLY_RECOMMENDED,
                confidence,
                f"Option '{top.option_id}' is the highest-scoring feasible alternative (score: {top.composite_score:.4f}), conditionally recommended subject to active limitations.",
            )

        return (
            DecisionOutcomeStatus.RECOMMENDED,
            confidence,
            f"Option '{top.option_id}' ({top.option_name}) is deterministically recommended with composite score {top.composite_score:.4f} and 100% policy compliance.",
        )


decision_engine_service = DecisionEngineService()
