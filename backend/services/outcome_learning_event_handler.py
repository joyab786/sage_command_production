# backend/services/outcome_learning_event_handler.py
"""
SageCommand V3 — Closed-Loop Outcome Learning Event Handler (Prompt 39)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Subscribes to canonical operational events on the EventBus, validates scope and provenance,
guards against recursive feedback cycles, and invokes deterministic outcome evaluation.

Invariants:
- Deterministic Loop Guard: Events emitted by closed_loop_evaluator or closed_loop_coordinator
  are immediately dropped to prevent cyclic cascades.
- Canonical event validation: Strictly enforces tenant, workspace, and plant scope matching.
- Durable persistence BEFORE event publication: Evaluations are committed to SQLite first.
- Idempotent: Redelivered events resolve to existing evaluation records without duplication.
"""

import logging
from typing import Optional, Dict, Any

try:
    from core.auth import Identity
    from core.config import SAGE_OUTCOME_EVALUATION_ENABLED
    from data.schemas.event_contract import CanonicalEvent
    from data.schemas.outcome_learning_contract import (
        PredictionOutcomeEvaluation,
        OutcomeVerificationStatus,
    )
    from services.event_bus import EventBus, get_event_bus
    from services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
        EVALUATOR_PROVENANCE,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity
    from backend.core.config import SAGE_OUTCOME_EVALUATION_ENABLED
    from backend.data.schemas.event_contract import CanonicalEvent
    from backend.data.schemas.outcome_learning_contract import (
        PredictionOutcomeEvaluation,
        OutcomeVerificationStatus,
    )
    from backend.services.event_bus import EventBus, get_event_bus
    from backend.services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
        EVALUATOR_PROVENANCE,
    )

logger = logging.getLogger("outcome_learning_event_handler")


class OutcomeLearningEventHandler:
    """
    Subscribes to operational outcome events on the canonical EventBus and deterministically
    triggers prediction-outcome evaluation with strict loop guard protection.
    """

    def __init__(
        self,
        service: Optional[OutcomeEvaluationService] = None,
        event_bus: Optional[EventBus] = None,
        enabled: Optional[bool] = None,
    ):
        self.service = service or outcome_evaluation_service
        self._event_bus = event_bus
        self.enabled = SAGE_OUTCOME_EVALUATION_ENABLED if enabled is None else enabled
        self._subscription_id: Optional[str] = None

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            self._event_bus = get_event_bus()
        return self._event_bus

    def register_subscriptions(self) -> None:
        """Subscribes to outcome and verification completion events."""
        if not self.enabled:
            logger.info("Outcome learning event handler is disabled by configuration.")
            return

        try:
            # Subscribe to outcome.observed and verification feedback
            sub = self.event_bus.subscribe(
                subscriber_id="outcome_learning_evaluator",
                topic_filter="outcome.*",
                callback=self.handle_event,
            )
            self._subscription_id = getattr(sub, "subscription_id", "outcome_learning_evaluator")
            logger.info("Outcome learning event handler registered successfully.")
        except Exception as e:
            logger.warning("Could not register outcome learning subscription: %s", e)

    def handle_event(self, event: CanonicalEvent) -> Optional[PredictionOutcomeEvaluation]:
        """
        Processes an incoming canonical event.
        Enforces loop guard, resolves prediction and outcome, and invokes evaluation.
        """
        # 1. Deterministic Loop Guard
        origin = str(event.provenance or "").strip().lower()
        if origin in (EVALUATOR_PROVENANCE.lower(), "closed_loop_coordinator", "system:closed_loop"):
            logger.debug(
                "Loop Guard: Dropping event '%s' with provenance '%s' to prevent feedback cycles.",
                event.event_id,
                event.provenance,
            )
            return None

        # 2. Scope validation
        if not event.tenant_id or not event.workspace_id or not event.plant_id:
            logger.warning("Dropping event '%s' due to missing scope parameters.", event.event_id)
            return None

        norm_tenant = event.tenant_id.lower()
        if norm_tenant in ("global", "unknown", "default"):
            logger.warning("Dropping event '%s' with fabricated tenant scope '%s'.", event.event_id, event.tenant_id)
            return None

        # 3. Payload inspection for prediction and outcome references
        prediction_id = event.payload.get("prediction_id")
        outcome_id = event.payload.get("outcome_id") or event.references.source_record_id

        if not prediction_id or not outcome_id:
            # Event does not contain pair for evaluation
            return None

        # Construct trusted server-side system identity scoped to event boundary
        identity = Identity(
            user_id=f"system:outcome_evaluator:{event.tenant_id}",
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            roles=["SYSTEM_VERIFIER", "ANALYST"],
            permissions=[
                "learning.prediction.read",
                "learning.outcome.read",
                "learning.evaluation.evaluate",
                "learning.evaluation.read",
            ],
            assigned_plants=[event.plant_id],
            clearance_level=3,
            is_server_authoritative=True,
        )

        try:
            evaluation = self.service.evaluate_prediction_outcome(
                identity=identity,
                prediction_id=prediction_id,
                outcome_id=outcome_id,
                correlation_id=event.correlation_id or event.event_id,
            )
            logger.info(
                "Successfully evaluated prediction '%s' against outcome '%s' via event '%s': status=%s.",
                prediction_id,
                outcome_id,
                event.event_id,
                evaluation.evaluation_status.value,
            )
            return evaluation
        except Exception as e:
            logger.error("Error evaluating outcome from event '%s': %s", event.event_id, e)
            return None


# Canonical singleton instance
outcome_learning_event_handler = OutcomeLearningEventHandler()
