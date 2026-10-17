# backend/services/outcome_evaluation_service.py
"""
SageCommand V3 — Closed-Loop Outcome Evaluation Service (Prompt 39)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Orchestrates deterministic outcome evaluation:
1. Preserves original expectations via immutable prediction snapshots.
2. Ingests observed physical/operational outcomes with verified provenance.
3. Deterministically validates 13-point outcome eligibility policy.
4. Compares predictions and outcomes using type-safe mathematical evaluation.
5. Persists append-only, idempotent evaluation records.
6. Computes bounded, deterministic aggregate metrics without LLM fabrication.
7. Exposes governed, scope-isolated read-only historical learning context.
8. Emits canonical audit and EventBus events without recursive self-triggering loops.

Invariants:
- Read-only evaluation: NEVER mutates policies, model weights, or machine setpoints.
- Authoritative scope: Strictly enforces tenant, workspace, and assigned plant boundaries.
- Timing integrity: Rejects outcomes observed before predictions were recorded.
- Honest uncertainty: Zero denominator yields None (never zero or fabricated values).
- Data-mode boundary: Simulation data cannot contaminate real-world learning context.
- Zero operational execution gateway or action tool pathways.
"""

import asyncio
import hashlib
import json
import logging
import math
import uuid
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta

try:
    from core.config import (
        SAGE_OUTCOME_EVALUATION_ENABLED,
        SAGE_OUTCOME_EVALUATION_MIN_SAMPLE_COUNT,
        SAGE_OUTCOME_EVALUATION_MAX_WINDOW_DAYS,
        SAGE_OUTCOME_EVALUATION_MAX_PAYLOAD_BYTES,
        SAGE_OUTCOME_EVALUATION_CLOCK_SKEW_TOLERANCE_SECONDS,
    )
    from core.auth import Identity
    from governance.audit import log_security_event
    from data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from services.event_bus import EventBus, get_event_bus
    from data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        OutcomeEligibilityStatus,
        OutcomeEligibilityReason,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        SCHEMA_VERSION,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )
    from repositories.outcome_learning_repository import (
        OutcomeLearningRepository,
        outcome_learning_repository,
        OutcomeLearningError,
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_OUTCOME_EVALUATION_ENABLED,
        SAGE_OUTCOME_EVALUATION_MIN_SAMPLE_COUNT,
        SAGE_OUTCOME_EVALUATION_MAX_WINDOW_DAYS,
        SAGE_OUTCOME_EVALUATION_MAX_PAYLOAD_BYTES,
        SAGE_OUTCOME_EVALUATION_CLOCK_SKEW_TOLERANCE_SECONDS,
    )
    from backend.core.auth import Identity
    from backend.governance.audit import log_security_event
    from backend.data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from backend.services.event_bus import EventBus, get_event_bus
    from backend.data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        OutcomeEligibilityStatus,
        OutcomeEligibilityReason,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        SCHEMA_VERSION,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )
    from backend.repositories.outcome_learning_repository import (
        OutcomeLearningRepository,
        outcome_learning_repository,
        OutcomeLearningError,
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )

logger = logging.getLogger("outcome_evaluation_service")

# Provenance identifier for the outcome evaluator (used for loop guard)
EVALUATOR_PROVENANCE = "closed_loop_evaluator"


class OutcomeEvaluationService:
    """
    Core service coordinating closed-loop outcome evaluation, deterministic
    prediction-versus-outcome comparison, and governed decision-support learning context.
    """

    def __init__(
        self,
        repository: Optional[OutcomeLearningRepository] = None,
        event_bus: Optional[EventBus] = None,
        enabled: Optional[bool] = None,
    ):
        self.repository = repository or outcome_learning_repository
        self._event_bus = event_bus
        self.enabled = SAGE_OUTCOME_EVALUATION_ENABLED if enabled is None else enabled

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = get_event_bus()
        return self._event_bus

    # -------------------------------------------------------------------------
    # 1. PREDICTION SNAPSHOT OPERATIONS
    # -------------------------------------------------------------------------

    def record_prediction_snapshot(
        self, identity: Identity, snapshot: PredictionSnapshot
    ) -> PredictionSnapshot:
        """
        Records an immutable prediction snapshot.
        Enforces tenant and plant scope authorization.
        """
        self._validate_identity_scope(identity, snapshot.tenant_id, snapshot.workspace_id, snapshot.plant_id)

        persisted = self.repository.record_prediction_snapshot(snapshot)

        self._log_audit_event(
            "PREDICTION_SNAPSHOT_RECORDED",
            identity,
            {
                "prediction_id": persisted.prediction_id,
                "prediction_type": persisted.prediction_type.value,
                "target_reference": persisted.target_reference,
                "predicted_at": persisted.predicted_at,
                "plant_id": persisted.plant_id,
            },
        )
        return persisted

    def get_prediction_snapshot(
        self, identity: Identity, prediction_id: str
    ) -> PredictionSnapshot:
        """Retrieves prediction snapshot within caller's authorized scope."""
        snapshot = self.repository.get_prediction_snapshot(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            prediction_id=prediction_id,
        )
        if not snapshot:
            raise PredictionNotFoundError(
                f"Prediction snapshot '{prediction_id}' not found in workspace '{identity.workspace_id}'."
            )
        self._validate_plant_access(identity, snapshot.plant_id)
        return snapshot

    def list_prediction_snapshots(
        self,
        identity: Identity,
        plant_id: Optional[str] = None,
        prediction_type: Optional[PredictionType] = None,
        limit: int = 50,
    ) -> List[PredictionSnapshot]:
        """Lists prediction snapshots scoped to caller."""
        if plant_id:
            self._validate_plant_access(identity, plant_id)
        return self.repository.list_prediction_snapshots(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=plant_id,
            prediction_type=prediction_type,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # 2. OBSERVED OUTCOME OPERATIONS
    # -------------------------------------------------------------------------

    def record_observed_outcome(
        self, identity: Identity, outcome: ObservedOutcome
    ) -> ObservedOutcome:
        """
        Records an observed outcome.
        Prevents client-side forgery of authoritative verification status.
        """
        self._validate_identity_scope(identity, outcome.tenant_id, outcome.workspace_id, outcome.plant_id)

        # Security Invariant: An untrusted client cannot assert outcome is VERIFIED
        # without authoritative verification reference.
        user_roles = [r.upper() for r in identity.roles]
        is_verifier = "SYSTEM_VERIFIER" in user_roles or "SYSTEM_ADMIN" in user_roles or "ADMINISTRATOR" in user_roles
        if outcome.verification_status == OutcomeVerificationStatus.VERIFIED:
            if not outcome.verification_reference and not is_verifier:
                logger.warning(
                    "Caller '%s' attempted to record VERIFIED outcome '%s' without verification reference. Downgrading to OBSERVED.",
                    identity.user_id,
                    outcome.outcome_id,
                )
                outcome.verification_status = OutcomeVerificationStatus.OBSERVED

        persisted = self.repository.record_observed_outcome(outcome)

        self._log_audit_event(
            "OUTCOME_OBSERVED",
            identity,
            {
                "outcome_id": persisted.outcome_id,
                "target_reference": persisted.target_reference,
                "verification_status": persisted.verification_status.value,
                "observed_at": persisted.observed_at,
                "plant_id": persisted.plant_id,
            },
        )
        return persisted

    def get_observed_outcome(
        self, identity: Identity, outcome_id: str
    ) -> ObservedOutcome:
        """Retrieves observed outcome within caller's authorized scope."""
        outcome = self.repository.get_observed_outcome(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            outcome_id=outcome_id,
        )
        if not outcome:
            raise OutcomeNotFoundError(
                f"Observed outcome '{outcome_id}' not found in workspace '{identity.workspace_id}'."
            )
        self._validate_plant_access(identity, outcome.plant_id)
        return outcome

    def list_observed_outcomes(
        self,
        identity: Identity,
        target_reference: Optional[str] = None,
        prediction_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservedOutcome]:
        """Lists observed outcomes within caller's scope."""
        if plant_id:
            self._validate_plant_access(identity, plant_id)
        return self.repository.list_observed_outcomes(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            target_reference=target_reference,
            prediction_id=prediction_id,
            plant_id=plant_id,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # 3. DETERMINISTIC OUTCOME ELIGIBILITY POLICY
    # -------------------------------------------------------------------------

    def validate_outcome_eligibility(
        self,
        prediction: PredictionSnapshot,
        outcome: ObservedOutcome,
        identity: Identity,
    ) -> Tuple[OutcomeEligibilityStatus, OutcomeEligibilityReason, str]:
        """
        Evaluates deterministic 13-point eligibility policy before comparison.
        Returns (status, reason_code, diagnostic_explanation).
        """
        # 1. Prediction existence verified by caller.

        # 2. Scope validation against identity
        if (
            prediction.tenant_id != identity.tenant_id
            or prediction.workspace_id != identity.workspace_id
        ):
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.SCOPE_MISMATCH,
                "Prediction is outside caller's authorized tenant or workspace scope.",
            )

        # 3. Check prediction type validity
        if not isinstance(prediction.prediction_type, PredictionType):
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.UNSUPPORTED_PREDICTION_TYPE,
                f"Unsupported prediction type: '{prediction.prediction_type}'.",
            )

        # 4. Scope matching between prediction and outcome
        if (
            prediction.tenant_id != outcome.tenant_id
            or prediction.workspace_id != outcome.workspace_id
            or prediction.plant_id != outcome.plant_id
        ):
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.SCOPE_MISMATCH,
                f"Cross-scope association rejected: prediction scope ({prediction.tenant_id}:{prediction.workspace_id}:{prediction.plant_id}) does not match outcome scope ({outcome.tenant_id}:{outcome.workspace_id}:{outcome.plant_id}).",
            )

        # 5. Timing validation: prediction must be recorded before outcome's observation time
        #    (subject to clock skew tolerance)
        try:
            pred_dt = _parse_utc_iso(prediction.predicted_at)
            outc_dt = _parse_utc_iso(outcome.observed_at)
            tolerance = timedelta(seconds=SAGE_OUTCOME_EVALUATION_CLOCK_SKEW_TOLERANCE_SECONDS)
            if pred_dt > outc_dt + tolerance:
                return (
                    OutcomeEligibilityStatus.REJECTED,
                    OutcomeEligibilityReason.TIMING_VIOLATION,
                    f"Prediction time ({prediction.predicted_at}) is later than outcome observation time ({outcome.observed_at}) beyond clock skew tolerance ({SAGE_OUTCOME_EVALUATION_CLOCK_SKEW_TOLERANCE_SECONDS}s).",
                )
        except Exception as e:
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.TIMING_VIOLATION,
                f"Failed to parse timestamp during timing validation: {e}",
            )

        # 6. Target reference linkage
        if outcome.prediction_id:
            if outcome.prediction_id != prediction.prediction_id:
                return (
                    OutcomeEligibilityStatus.REJECTED,
                    OutcomeEligibilityReason.SCOPE_MISMATCH,
                    f"Outcome explicitly references prediction '{outcome.prediction_id}', not '{prediction.prediction_id}'.",
                )
        elif outcome.target_reference != prediction.target_reference:
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.SCOPE_MISMATCH,
                f"Target reference mismatch: prediction targets '{prediction.target_reference}' while outcome targets '{outcome.target_reference}'.",
            )

        # 7. Data mode compatibility
        if prediction.data_mode != outcome.data_mode:
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.DATA_MODE_MISMATCH,
                f"Data mode mismatch: prediction is '{prediction.data_mode.value}' while outcome is '{outcome.data_mode.value}'.",
            )

        # 8. Evidence invalidation check
        if outcome.is_invalidated:
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.INVALIDATED_SOURCE,
                "Outcome evidence has been invalidated or superseded.",
            )

        # 9. Unit compatibility check
        if prediction.expected_unit and outcome.unit:
            if prediction.expected_unit.strip().lower() != outcome.unit.strip().lower():
                return (
                    OutcomeEligibilityStatus.REJECTED,
                    OutcomeEligibilityReason.UNIT_MISMATCH,
                    f"Incompatible units: prediction expected '{prediction.expected_unit}' but outcome reported '{outcome.unit}'.",
                )

        # 10. Evaluation window check
        if prediction.evaluation_window_start:
            try:
                win_start = _parse_utc_iso(prediction.evaluation_window_start)
                if outc_dt < win_start - tolerance:
                    return (
                        OutcomeEligibilityStatus.DEFERRED,
                        OutcomeEligibilityReason.INVALID_EVALUATION_WINDOW,
                        f"Outcome observed ({outcome.observed_at}) before evaluation window start ({prediction.evaluation_window_start}).",
                    )
            except Exception:
                pass

        if prediction.evaluation_window_end:
            try:
                win_end = _parse_utc_iso(prediction.evaluation_window_end)
                if outc_dt > win_end + tolerance:
                    return (
                        OutcomeEligibilityStatus.DEFERRED,
                        OutcomeEligibilityReason.INVALID_EVALUATION_WINDOW,
                        f"Outcome observed ({outcome.observed_at}) after evaluation window end ({prediction.evaluation_window_end}).",
                    )
            except Exception:
                pass

        # 11. Verification status assessment
        if outcome.verification_status == OutcomeVerificationStatus.REJECTED:
            return (
                OutcomeEligibilityStatus.REJECTED,
                OutcomeEligibilityReason.OUTCOME_NOT_VERIFIED,
                "Outcome was rejected by continuous verification engine.",
            )

        # All deterministic checks passed
        return (
            OutcomeEligibilityStatus.ELIGIBLE,
            OutcomeEligibilityReason.ELIGIBLE,
            "Outcome satisfies all deterministic eligibility criteria for evaluation.",
        )

    # -------------------------------------------------------------------------
    # 4. PREDICTION-OUTCOME EVALUATION
    # -------------------------------------------------------------------------

    def evaluate_prediction_outcome(
        self,
        identity: Identity,
        prediction_id: str,
        outcome_id: str,
        idempotency_key: Optional[str] = None,
        reevaluation_reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> PredictionOutcomeEvaluation:
        """
        Deterministically evaluates prediction against eligible observed outcome.
        Performs typed error and accuracy calculations, persists append-only record,
        and safely emits canonical evaluation event to EventBus.
        """
        prediction = self.get_prediction_snapshot(identity, prediction_id)
        outcome = self.get_observed_outcome(identity, outcome_id)

        # Deterministic Idempotency Key binding pair and policy version
        canonical_idem = (
            idempotency_key
            or f"idem_eval_{hashlib.sha256(f'{prediction.tenant_id}:{prediction.workspace_id}:{prediction_id}:{outcome_id}:{EVALUATION_POLICY_VERSION}'.encode()).hexdigest()[:32]}"
        )

        # If not explicit re-evaluation, check if already evaluated
        if not reevaluation_reason:
            existing = self.repository.get_evaluation(
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                evaluation_id=canonical_idem,
            )
            if existing:
                return existing

        # Evaluate eligibility policy
        elig_status, elig_reason, elig_expl = self.validate_outcome_eligibility(prediction, outcome, identity)

        evaluation_id = f"eval_{uuid.uuid4().hex[:16]}"
        unit = outcome.unit or prediction.expected_unit

        # Prepare comparison metrics
        abs_err: Optional[float] = None
        signed_err: Optional[float] = None
        rel_err: Optional[float] = None
        dir_bias: Optional[DirectionalBias] = None
        exact_match: Optional[bool] = None
        comparison_semantics = "UNKNOWN"

        eval_status = EvaluationStatus.EVALUATED
        is_diag = outcome.is_diagnostic
        learning_eligible = False
        learning_inelig_reason: Optional[str] = None

        if elig_status != OutcomeEligibilityStatus.ELIGIBLE:
            eval_status = (
                EvaluationStatus.DEFERRED
                if elig_status == OutcomeEligibilityStatus.DEFERRED
                else EvaluationStatus.REJECTED
            )
            learning_eligible = False
            learning_inelig_reason = elig_reason.value
            comparison_semantics = "INELIGIBLE_EVALUATION"
        else:
            # Perform Typed Comparison
            pred_val = prediction.expected_value
            obs_val = outcome.observed_value

            # Check if numeric comparison is applicable
            is_pred_num = isinstance(pred_val, (int, float)) and not isinstance(pred_val, bool)
            is_obs_num = isinstance(obs_val, (int, float)) and not isinstance(obs_val, bool)

            if is_pred_num and is_obs_num:
                comparison_semantics = "NUMERIC_ERROR"
                y_hat = float(pred_val)
                y = float(obs_val)

                abs_err = round(abs(y - y_hat), 6)
                signed_err = round(y - y_hat, 6)

                # Relative Error: ONLY when denominator y is nonzero!
                if y != 0.0:
                    rel_err = round(abs(y - y_hat) / abs(y), 6)
                else:
                    rel_err = None  # Explicitly unavailable, never divide by zero

                if y_hat > y:
                    dir_bias = DirectionalBias.OVER_PREDICTED
                elif y_hat < y:
                    dir_bias = DirectionalBias.UNDER_PREDICTED
                else:
                    dir_bias = DirectionalBias.MATCHED

                exact_match = (y == y_hat)
            elif isinstance(pred_val, bool) and isinstance(obs_val, bool):
                comparison_semantics = "BOOLEAN_MATCH"
                exact_match = (pred_val == obs_val)
                dir_bias = DirectionalBias.MATCHED if exact_match else DirectionalBias.NOT_DETERMINABLE
            else:
                # Categorical / string comparison
                comparison_semantics = "CATEGORICAL_EXACT_MATCH"
                str_pred = str(pred_val).strip().lower()
                str_obs = str(obs_val).strip().lower()
                exact_match = (str_pred == str_obs)
                dir_bias = DirectionalBias.MATCHED if exact_match else DirectionalBias.NOT_DETERMINABLE

            # Determine eligibility for future learning
            if outcome.verification_status != OutcomeVerificationStatus.VERIFIED:
                learning_eligible = False
                learning_inelig_reason = "OUTCOME_NOT_VERIFIED"
            elif outcome.is_diagnostic:
                learning_eligible = False
                learning_inelig_reason = "DIAGNOSTIC_VERIFICATION_ONLY"
            elif outcome.data_mode != DataMode.REAL:
                learning_eligible = False
                learning_inelig_reason = "SIMULATION_DATA_MODE"
            elif outcome.is_invalidated:
                learning_eligible = False
                learning_inelig_reason = "INVALIDATED_EVIDENCE"
            else:
                learning_eligible = True
                learning_inelig_reason = None

        prior_eval_id: Optional[str] = None
        if reevaluation_reason:
            existing_prior = self.repository.list_evaluations(
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                limit=1,
            )
            if existing_prior:
                prior_eval_id = existing_prior[0].evaluation_id

        eval_record = PredictionOutcomeEvaluation(
            evaluation_id=evaluation_id,
            schema_version=SCHEMA_VERSION,
            prediction_id=prediction.prediction_id,
            outcome_id=outcome.outcome_id,
            evaluation_status=eval_status,
            eligibility_reason=elig_reason.value,
            evaluation_policy_version=EVALUATION_POLICY_VERSION,
            metric_implementation_version=METRIC_IMPLEMENTATION_VERSION,
            prediction_type=prediction.prediction_type,
            target_reference=prediction.target_reference,
            predicted_value=prediction.expected_value,
            observed_value=outcome.observed_value,
            unit=unit,
            comparison_semantics=comparison_semantics,
            absolute_error=abs_err,
            signed_error=signed_err,
            relative_error=rel_err,
            directional_bias=dir_bias,
            exact_match=exact_match,
            verification_reference=outcome.verification_reference,
            is_diagnostic=is_diag,
            eligible_for_learning=learning_eligible,
            learning_ineligibility_reason=learning_inelig_reason,
            provenance=EVALUATOR_PROVENANCE,
            data_mode=prediction.data_mode,
            prior_evaluation_id=prior_eval_id,
            reevaluation_reason=reevaluation_reason,
            idempotency_key=canonical_idem,
            correlation_id=correlation_id or outcome.correlation_id,
            tenant_id=prediction.tenant_id,
            workspace_id=prediction.workspace_id,
            plant_id=prediction.plant_id,
            details={
                "eligibility_explanation": elig_expl,
                "predicted_at": prediction.predicted_at,
                "observed_at": outcome.observed_at,
            },
        )

        persisted = self.repository.record_evaluation(eval_record)

        self._log_audit_event(
            "OUTCOME_EVALUATION_COMPLETED",
            identity,
            {
                "evaluation_id": persisted.evaluation_id,
                "prediction_id": persisted.prediction_id,
                "outcome_id": persisted.outcome_id,
                "status": persisted.evaluation_status.value,
                "absolute_error": persisted.absolute_error,
                "eligible_for_learning": persisted.eligible_for_learning,
            },
        )

        # Publish canonical event prediction.evaluated AFTER durable commit
        self._publish_evaluation_event(persisted)

        return persisted

    def get_evaluation(
        self, identity: Identity, evaluation_id: str
    ) -> PredictionOutcomeEvaluation:
        """Retrieves evaluation record within caller's scope."""
        evaluation = self.repository.get_evaluation(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            evaluation_id=evaluation_id,
        )
        if not evaluation:
            raise EvaluationNotFoundError(
                f"Evaluation '{evaluation_id}' not found in workspace '{identity.workspace_id}'."
            )
        self._validate_plant_access(identity, evaluation.plant_id)
        return evaluation

    def list_evaluations(
        self,
        identity: Identity,
        prediction_type: Optional[PredictionType] = None,
        plant_id: Optional[str] = None,
        data_mode: Optional[DataMode] = None,
        eligible_only: bool = False,
        limit: int = 50,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
    ) -> List[PredictionOutcomeEvaluation]:
        """Lists evaluations within authorized scope."""
        if plant_id:
            self._validate_plant_access(identity, plant_id)
        return self.repository.list_evaluations(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=plant_id,
            prediction_type=prediction_type,
            data_mode=data_mode,
            eligible_only=eligible_only,
            limit=limit,
            window_start=window_start,
            window_end=window_end,
        )

    # -------------------------------------------------------------------------
    # 5. AGGREGATE METRICS & GOVERNED LEARNING CONTEXT
    # -------------------------------------------------------------------------

    def get_aggregate_metrics(
        self,
        identity: Identity,
        prediction_type: PredictionType,
        plant_id: Optional[str] = None,
        data_mode: Optional[DataMode] = None,
        model_version: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        min_sample_threshold: Optional[int] = None,
    ) -> AggregateMetricsSummary:
        """Retrieves bounded aggregate performance metrics for authorized scope."""
        if plant_id:
            self._validate_plant_access(identity, plant_id)
        threshold = min_sample_threshold or SAGE_OUTCOME_EVALUATION_MIN_SAMPLE_COUNT
        return self.repository.calculate_aggregate_metrics(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
            min_sample_threshold=threshold,
        )

    def get_governed_learning_context(
        self,
        identity: Identity,
        prediction_type: PredictionType,
        plant_id: Optional[str] = None,
        data_mode: Optional[DataMode] = None,
        model_version: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
    ) -> GovernedLearningContext:
        """Retrieves read-only historical evaluation evidence for future decision-support."""
        if plant_id:
            self._validate_plant_access(identity, plant_id)
        context = self.repository.get_governed_learning_context(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
            min_sample_threshold=SAGE_OUTCOME_EVALUATION_MIN_SAMPLE_COUNT,
        )
        self._log_audit_event(
            "LEARNING_CONTEXT_RETRIEVED",
            identity,
            {
                "prediction_type": prediction_type.value,
                "sample_count": context.sample_count,
                "status": context.evaluation_status,
                "plant_id": plant_id,
            },
        )
        return context

    # -------------------------------------------------------------------------
    # 6. EVENTBUS INTEGRATION & LOOP GUARD
    # -------------------------------------------------------------------------

    def _publish_evaluation_event(self, evaluation: PredictionOutcomeEvaluation) -> None:
        """
        Publishes canonical event prediction.evaluated to EventBus.
        Safely isolates failures so persistence is never corrupted.
        """
        try:
            event = CanonicalEvent(
                tenant_id=evaluation.tenant_id,
                workspace_id=evaluation.workspace_id,
                plant_id=evaluation.plant_id,
                category=EventCategory.QUALITY,
                event_type="prediction.evaluated",
                severity=EventSeverity.INFO,
                lifecycle=EventLifecycle.RECORDED,
                occurred_at=evaluation.evaluated_at,
                observed_at=evaluation.evaluated_at,
                provenance=EVALUATOR_PROVENANCE,
                correlation_id=evaluation.correlation_id,
                references=EventReferences(
                    source_system="outcome_evaluation_service",
                    source_record_id=evaluation.evaluation_id,
                ),
                payload={
                    "evaluation_id": evaluation.evaluation_id,
                    "prediction_id": evaluation.prediction_id,
                    "outcome_id": evaluation.outcome_id,
                    "prediction_type": evaluation.prediction_type.value,
                    "target_reference": evaluation.target_reference,
                    "evaluation_status": evaluation.evaluation_status.value,
                    "absolute_error": evaluation.absolute_error,
                    "signed_error": evaluation.signed_error,
                    "relative_error": evaluation.relative_error,
                    "directional_bias": evaluation.directional_bias.value if evaluation.directional_bias else None,
                    "eligible_for_learning": evaluation.eligible_for_learning,
                    "data_mode": evaluation.data_mode.value,
                },
            )
            event.event_fingerprint = event.compute_fingerprint()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.event_bus.publish(event))
            except RuntimeError:
                asyncio.run(self.event_bus.publish(event))
            logger.info("Published canonical evaluation event '%s' to EventBus.", event.event_id)
        except Exception as e:
            # Safe recovery: event publication failure does NOT roll back committed evaluation
            logger.error("Failed to publish canonical evaluation event: %s", e)

    # -------------------------------------------------------------------------
    # 7. INTERNAL VALIDATION & AUDIT
    # -------------------------------------------------------------------------

    def _validate_identity_scope(
        self, identity: Identity, tenant_id: str, workspace_id: str, plant_id: str
    ):
        """Ensures caller cannot operate outside assigned tenant, workspace, or plant boundaries."""
        if identity.tenant_id != tenant_id:
            raise OutcomeEvaluationScopeMismatchError(
                f"Tenant mismatch: caller tenant '{identity.tenant_id}' cannot access '{tenant_id}'."
            )
        if identity.workspace_id != workspace_id:
            raise OutcomeEvaluationScopeMismatchError(
                f"Workspace mismatch: caller workspace '{identity.workspace_id}' cannot access '{workspace_id}'."
            )
        self._validate_plant_access(identity, plant_id)

    def _validate_plant_access(self, identity: Identity, plant_id: str):
        """Validates plant against caller's assigned plants."""
        assigned = getattr(identity, "assigned_plants", ["*"]) or ["*"]
        if "*" in assigned:
            return
        if plant_id not in assigned:
            raise OutcomeEvaluationScopeMismatchError(
                f"Plant access denied: plant '{plant_id}' is not in assigned plants {assigned}."
            )

    def _log_audit_event(self, operation: str, identity: Identity, details: Dict[str, Any]):
        """Logs structured security audit event."""
        log_security_event(
            operation,
            {
                "user_id": identity.user_id,
                "tenant_id": identity.tenant_id,
                "workspace_id": identity.workspace_id,
                **details,
            },
            severity="INFO",
        )


# Canonical singleton service instance
outcome_evaluation_service = OutcomeEvaluationService()
