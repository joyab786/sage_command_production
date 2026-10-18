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
        SAGE_VERIFICATION_DB_PATH,
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
    from data.schemas.verification_contract import (
        VerificationStatus,
        ScopeStatus,
        QualityStatus,
    )
    from repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
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
    from data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
    )
    from services.authorization_service import authorization_service
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_OUTCOME_EVALUATION_ENABLED,
        SAGE_OUTCOME_EVALUATION_MIN_SAMPLE_COUNT,
        SAGE_OUTCOME_EVALUATION_MAX_WINDOW_DAYS,
        SAGE_OUTCOME_EVALUATION_MAX_PAYLOAD_BYTES,
        SAGE_OUTCOME_EVALUATION_CLOCK_SKEW_TOLERANCE_SECONDS,
        SAGE_VERIFICATION_DB_PATH,
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
    from backend.data.schemas.verification_contract import (
        VerificationStatus,
        ScopeStatus,
        QualityStatus,
    )
    from backend.repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
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
    from backend.data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
    )
    from backend.services.authorization_service import authorization_service

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
        verification_repository: Optional[VerificationRepository] = None,
    ):
        self.repository = repository or outcome_learning_repository
        self._event_bus = event_bus
        self.enabled = SAGE_OUTCOME_EVALUATION_ENABLED if enabled is None else enabled
        if verification_repository is not None:
            self.verification_repository = verification_repository
        else:
            db_path = getattr(self.repository, "_db_path", SAGE_VERIFICATION_DB_PATH)
            self.verification_repository = VerificationRepository(db_path=db_path)

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
    # 2. OBSERVED OUTCOME OPERATIONS & AUTHORITATIVE VERIFICATION
    # -------------------------------------------------------------------------

    def _validate_authoritative_verification(
        self,
        identity: Identity,
        outcome: ObservedOutcome,
        prediction: Optional[PredictionSnapshot] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Validates whether an outcome's verification_reference identifies a genuine,
        persisted, authoritative, and in-scope verification record in the canonical Verification Engine.

        Enforces:
        1. Reference existence and non-empty format.
        2. Resolution to persisted VerificationRun or VerificationFinding.
        3. Strict tenant, workspace, and plant matching.
        4. Authoritative VERIFIED status (never PENDING, FAILED, BLOCKED, etc.).
        5. Exclusion of diagnostic-only verification.
        6. Exclusion of invalidated or rejected evidence.
        7. Target relevance between outcome/prediction and verification record.
        8. Caller authorization to access the verification record.
        """
        ref = outcome.verification_reference
        if not ref or not isinstance(ref, str) or not ref.strip():
            return False, "MISSING_VERIFICATION_REFERENCE", None
        ref = ref.strip()

        # Query canonical verification repository scoped strictly to tenant and workspace
        auth_record = self.verification_repository.get_authoritative_verification_record(
            tenant_id=outcome.tenant_id,
            workspace_id=outcome.workspace_id,
            reference_id=ref,
        )
        if not auth_record:
            # Note: Cross-tenant references also fail here without disclosing
            # whether the ID exists in another tenant.
            return False, "VERIFICATION_RECORD_NOT_FOUND", None

        # Scope verification: plant must match
        if auth_record["plant_id"] != outcome.plant_id:
            return False, "CROSS_PLANT_VERIFICATION", auth_record

        # Prediction scope matching if evaluating against prediction
        if prediction is not None:
            if (
                prediction.tenant_id != auth_record["tenant_id"]
                or prediction.workspace_id != auth_record["workspace_id"]
                or prediction.plant_id != auth_record["plant_id"]
            ):
                return False, "PREDICTION_SCOPE_MISMATCH", auth_record

        # Caller authorization
        assigned_plants = getattr(identity, "assigned_plants", ["*"]) or ["*"]
        if "*" not in assigned_plants and auth_record["plant_id"] not in assigned_plants:
            return False, "CALLER_PLANT_UNAUTHORIZED", auth_record

        # Diagnostic check: Diagnostic verification cannot verify an outcome or establish learning eligibility
        if auth_record.get("is_diagnostic"):
            return False, "DIAGNOSTIC_ONLY_VERIFICATION", auth_record
        if auth_record.get("rule_id") == "RULE_EVIDENCE_EXISTS_V1":
            return False, "DIAGNOSTIC_ONLY_VERIFICATION", auth_record

        # Authoritative status check: Must be VERIFIED
        if auth_record["status"] != VerificationStatus.VERIFIED:
            return False, f"NON_AUTHORITATIVE_STATUS_{auth_record['status'].value}", auth_record

        # Invalidation check on outcome itself
        if outcome.is_invalidated:
            return False, "OUTCOME_EVIDENCE_INVALIDATED", auth_record

        # Rejection & invalidation checks on underlying evidence
        if auth_record["type"] == "FINDING":
            finding = auth_record["record"]
            for ea in getattr(finding, "evidence_assessments", []):
                if ea.scope_status in (
                    ScopeStatus.REJECTED,
                    ScopeStatus.CROSS_TENANT,
                    ScopeStatus.CROSS_WORKSPACE,
                    ScopeStatus.CROSS_PLANT,
                    ScopeStatus.UNAUTHORIZED,
                ):
                    return False, "REJECTED_EVIDENCE_SCOPE", auth_record
                if ea.quality_status in (QualityStatus.INVALID, QualityStatus.CONFLICTING):
                    return False, "INVALID_EVIDENCE_QUALITY", auth_record
                if str(ea.integrity_status).upper() == "INVALID":
                    return False, "INVALID_EVIDENCE_INTEGRITY", auth_record
        elif auth_record["type"] == "RUN":
            run = auth_record["record"]
            for f in run.findings:
                if f.status in (VerificationStatus.FAILED, VerificationStatus.CONFLICTING):
                    return False, f"RUN_FINDING_STATUS_{f.status.value}", auth_record
                for ea in f.evidence_assessments:
                    if ea.scope_status in (
                        ScopeStatus.REJECTED,
                        ScopeStatus.CROSS_TENANT,
                        ScopeStatus.CROSS_WORKSPACE,
                        ScopeStatus.CROSS_PLANT,
                        ScopeStatus.UNAUTHORIZED,
                    ):
                        return False, "REJECTED_EVIDENCE_SCOPE", auth_record
                    if ea.quality_status in (QualityStatus.INVALID, QualityStatus.CONFLICTING):
                        return False, "INVALID_EVIDENCE_QUALITY", auth_record
                    if str(ea.integrity_status).upper() == "INVALID":
                        return False, "INVALID_EVIDENCE_INTEGRITY", auth_record

        # Target relevance check:
        # The verification record must be relevant to the outcome being evaluated
        candidate_targets = {
            outcome.target_reference.strip().lower(),
        }
        if outcome.prediction_id:
            candidate_targets.add(outcome.prediction_id.strip().lower())
        if prediction is not None:
            candidate_targets.add(prediction.target_reference.strip().lower())
            candidate_targets.add(prediction.prediction_id.strip().lower())

        record_targets = {
            str(t).strip().lower() for t in auth_record.get("targets", []) if t
        }
        if auth_record.get("mission_id"):
            record_targets.add(str(auth_record["mission_id"]).strip().lower())

        if not candidate_targets.intersection(record_targets):
            return False, "UNRELATED_VERIFICATION_RECORD", auth_record

        return True, "VERIFIED", auth_record

    def record_observed_outcome(
        self, identity: Identity, outcome: ObservedOutcome
    ) -> ObservedOutcome:
        """
        Records an observed outcome.
        Prevents client-side forgery of authoritative verification status.
        Requires genuine, persisted, authoritative verification record in the Verification Engine.
        Privileged roles (ADMINISTRATOR, SYSTEM_VERIFIER) CANNOT bypass this check.
        """
        self._validate_identity_scope(identity, outcome.tenant_id, outcome.workspace_id, outcome.plant_id)

        # Authoritative verification check:
        # A caller declaring VERIFIED must be backed by genuine persisted verification evidence.
        if outcome.verification_status == OutcomeVerificationStatus.VERIFIED:
            is_valid, reason, auth_record = self._validate_authoritative_verification(
                identity, outcome, prediction=None
            )
            if not is_valid:
                logger.warning(
                    "Caller '%s' attempted to record VERIFIED outcome '%s' with non-authoritative reference '%s' (reason: %s). Downgrading to OBSERVED.",
                    identity.user_id,
                    outcome.outcome_id,
                    outcome.verification_reference,
                    reason,
                )
                outcome.verification_status = OutcomeVerificationStatus.OBSERVED
                outcome.verification_reference = None
                if reason == "DIAGNOSTIC_ONLY_VERIFICATION" or (auth_record and auth_record.get("is_diagnostic")):
                    outcome.is_diagnostic = True
                elif "INVALID" in reason or "REJECTED" in reason or (auth_record and auth_record.get("is_invalidated")):
                    outcome.is_invalidated = True
            else:
                # Synchronize server-authoritative flags from canonical verification record
                outcome.is_diagnostic = False
                outcome.is_invalidated = False

        persisted = self.repository.record_observed_outcome(outcome)

        self._log_audit_event(
            "OUTCOME_OBSERVED",
            identity,
            {
                "outcome_id": persisted.outcome_id,
                "target_reference": persisted.target_reference,
                "verification_status": persisted.verification_status.value,
                "verification_reference": persisted.verification_reference,
                "is_diagnostic": persisted.is_diagnostic,
                "is_invalidated": persisted.is_invalidated,
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
            if outcome.is_diagnostic:
                learning_eligible = False
                learning_inelig_reason = "DIAGNOSTIC_VERIFICATION_ONLY"
            elif outcome.is_invalidated:
                learning_eligible = False
                learning_inelig_reason = "INVALIDATED_EVIDENCE"
            elif outcome.data_mode != DataMode.REAL:
                learning_eligible = False
                learning_inelig_reason = "SIMULATION_DATA_MODE"
            elif outcome.verification_status != OutcomeVerificationStatus.VERIFIED:
                learning_eligible = False
                learning_inelig_reason = "OUTCOME_NOT_VERIFIED"
            else:
                # Authoritative re-validation at evaluation boundary against canonical Verification Engine
                is_valid, reason, auth_record = self._validate_authoritative_verification(
                    identity, outcome, prediction=prediction
                )
                if not is_valid:
                    learning_eligible = False
                    learning_inelig_reason = f"VERIFICATION_{reason}"
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

    def revalidate_historical_evaluations(
        self,
        identity: Identity,
        plant_id: Optional[str] = None,
        limit: int = 500,
    ) -> Dict[str, Any]:
        """
        Explicit historical evaluation revalidation procedure (Prompt 39 correction).
        Audits existing evaluations marked eligible_for_learning=1 against canonical
        persisted verification records. Fails closed and corrects any evaluations backed
        by unverified or missing verification evidence, emitting structured security audit logs.
        """
        # 1. Enforce dedicated administrative permission
        scope = AuthorizationScope(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            session_id=identity.session_id,
            plant_id=plant_id,
        )
        authz_ctx = AuthorizationContext(
            identity=identity.to_user_identity(),
            required_permission="learning.evaluation.revalidate",
            scope=scope,
        )
        authz_dec = authorization_service.evaluate(authz_ctx)
        if not authz_dec or authz_dec.effect != AuthzDecisionEffect.ALLOW:
            reason_msg = authz_dec.reason if authz_dec else "Authorization returned no ALLOW decision"
            self._log_audit_event(
                "HISTORICAL_REVALIDATION_AUTHORIZATION_DENIED",
                identity,
                {
                    "required_permission": "learning.evaluation.revalidate",
                    "reason_code": authz_dec.reason_code.value if authz_dec else "DENY",
                    "reason": reason_msg,
                },
            )
            raise OutcomeEvaluationScopeMismatchError(
                f"Authorization denied for historical revalidation: {reason_msg}"
            )

        # 2. Scope checks
        if plant_id:
            self._validate_plant_access(identity, plant_id)

        evals = self.repository.list_evaluations(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=plant_id,
            eligible_only=True,
            limit=limit,
        )

        assigned_plants = getattr(identity, "assigned_plants", ["*"]) or ["*"]
        if "*" not in assigned_plants:
            evals = [ev for ev in evals if ev.plant_id in assigned_plants]

        total_checked = len(evals)
        corrected_count = 0
        corrected_eval_ids = []

        for ev in evals:
            try:
                outcome = self.repository.get_observed_outcome(
                    tenant_id=ev.tenant_id,
                    workspace_id=ev.workspace_id,
                    outcome_id=ev.outcome_id,
                )
                if not outcome or outcome.verification_status != OutcomeVerificationStatus.VERIFIED:
                    should_correct = True
                    reason = "HISTORICAL_OUTCOME_NOT_VERIFIED"
                else:
                    prediction = self.repository.get_prediction_snapshot(
                        tenant_id=ev.tenant_id,
                        workspace_id=ev.workspace_id,
                        prediction_id=ev.prediction_id,
                    )
                    is_valid, v_reason, _ = self._validate_authoritative_verification(
                        identity, outcome, prediction=prediction
                    )
                    should_correct = not is_valid
                    reason = f"HISTORICAL_REVALIDATION_{v_reason}"

                if should_correct:
                    self.repository.update_evaluation_learning_eligibility(
                        tenant_id=ev.tenant_id,
                        workspace_id=ev.workspace_id,
                        evaluation_id=ev.evaluation_id,
                        eligible_for_learning=False,
                        learning_ineligibility_reason=reason,
                    )
                    corrected_count += 1
                    corrected_eval_ids.append(ev.evaluation_id)

                    self._log_audit_event(
                        "HISTORICAL_EVALUATION_REVALIDATION_CORRECTION",
                        identity,
                        {
                            "evaluation_id": ev.evaluation_id,
                            "prediction_id": ev.prediction_id,
                            "outcome_id": ev.outcome_id,
                            "previous_eligible_for_learning": True,
                            "new_eligible_for_learning": False,
                            "reason": reason,
                        },
                    )
            except Exception as e:
                logger.error("Error during historical revalidation of evaluation '%s': %s", ev.evaluation_id, e)

        return {
            "tenant_id": identity.tenant_id,
            "workspace_id": identity.workspace_id,
            "plant_id": plant_id,
            "total_checked": total_checked,
            "corrected_count": corrected_count,
            "corrected_evaluation_ids": corrected_eval_ids,
            "revalidation_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

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
