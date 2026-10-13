# backend/services/verification_trigger_coordinator.py
"""
SageCommand V3 — Closed-Loop Learning Foundation Coordinator (Prompt 37)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Orchestrates deterministic closed-loop learning:
1. Observes trusted operational events received through the canonical EventBus.
2. Evaluates events against an explicit, deterministic eligibility policy.
3. Validates server-authoritative tenant, workspace, and plant scope boundaries.
4. Enforces a strict feedback loop guard preventing recursive self-triggering cycles.
5. Invokes continuous verification through the existing VerificationService.
6. Records durable feedback relationships in the VerificationRepository.
7. Emits structured, bounded feedback events back to the EventBus.

Cardinal Invariants:
- Read-only assessment: NEVER executes missions, approves actions, or mutates operational state.
- Authoritative scope: NEVER trusts caller-supplied or payload-injected identity, roles, or clearance.
- Loop guard: Verification feedback events are deterministically dropped from re-triggering.
- Idempotent: Repeated event deliveries or replayed events do not duplicate verification runs.
- Diagnostic distinction: Diagnostic checks preserve is_diagnostic=True and never yield run-level VERIFIED.
- Zero raw SQL execution or ExecutionGateway interaction in coordinator.
"""

import logging
import hashlib
import json
import uuid
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_CLOSED_LOOP_ENABLED,
        SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED,
        SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS,
        SAGE_VERIFICATION_EVENT_DEDUP_WINDOW_SECONDS,
        SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS,
    )
    from core.auth import Identity
    from data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from data.schemas.event_delivery_contract import (
        EventDelivery,
        Subscription,
        DeliveryStatus,
    )
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationStatus,
        VerificationTargetType,
        VerificationRequest,
        TriggerType,
        RuleType,
        RULE_SET_VERSION,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from data.schemas.closed_loop_contract import (
        EligibilityStatus,
        EligibilityReasonCode,
        EligibilityDecision,
        VerificationFeedbackRecord,
        COORDINATOR_VERSION,
    )
    from services.event_bus import EventBus, get_event_bus
    from services.verification_service import (
        VerificationService,
        verification_service,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationNotFoundError,
        VerificationRevisionMismatchError,
    )
    from repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
    )
    from services.verification_rules import _parse_iso_timestamp
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_CLOSED_LOOP_ENABLED,
        SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED,
        SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS,
        SAGE_VERIFICATION_EVENT_DEDUP_WINDOW_SECONDS,
        SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS,
    )
    from backend.core.auth import Identity
    from backend.data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from backend.data.schemas.event_delivery_contract import (
        EventDelivery,
        Subscription,
        DeliveryStatus,
    )
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationStatus,
        VerificationTargetType,
        VerificationRequest,
        TriggerType,
        RuleType,
        RULE_SET_VERSION,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.data.schemas.closed_loop_contract import (
        EligibilityStatus,
        EligibilityReasonCode,
        EligibilityDecision,
        VerificationFeedbackRecord,
        COORDINATOR_VERSION,
    )
    from backend.services.event_bus import EventBus, get_event_bus
    from backend.services.verification_service import (
        VerificationService,
        verification_service,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationNotFoundError,
        VerificationRevisionMismatchError,
    )
    from backend.repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
    )
    from backend.services.verification_rules import _parse_iso_timestamp

logger = logging.getLogger("verification_trigger_coordinator")

# Explicit set of operational categories eligible to trigger continuous verification
ELIGIBLE_EVENT_CATEGORIES = {
    EventCategory.TELEMETRY,
    EventCategory.STATE_CHANGE,
    EventCategory.ANOMALY,
    EventCategory.QUALITY,
    EventCategory.MAINTENANCE,
    EventCategory.PRODUCTION,
    EventCategory.INVENTORY,
    EventCategory.KNOWLEDGE,
    EventCategory.TWIN,
}


class VerificationTriggerCoordinator:
    """
    Deterministic coordinator for event-triggered continuous verification and feedback recording.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        verification_svc: Optional[VerificationService] = None,
        repository: Optional[VerificationRepository] = None,
        enabled: Optional[bool] = None,
        event_trigger_enabled: Optional[bool] = None,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.verification_service = verification_svc or verification_service
        self.repository = repository or verification_repository
        self.enabled = SAGE_CLOSED_LOOP_ENABLED if enabled is None else enabled
        self.event_trigger_enabled = (
            SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED
            if event_trigger_enabled is None
            else event_trigger_enabled
        )
        self._subscribed_tenants: Dict[str, str] = {}  # tenant_id -> subscription_id

    # -------------------------------------------------------------------------
    # Subscription Lifecycle
    # -------------------------------------------------------------------------

    def register_tenant_subscription(
        self, tenant_id: str, workspace_id: Optional[str] = None, plant_id: Optional[str] = None
    ) -> Subscription:
        """
        Binds the coordinator to the tenant's EventBus subscription channel.
        Strict tenant boundary is preserved.
        """
        sub_id = f"sub_closed_loop_{tenant_id}"
        if workspace_id:
            sub_id += f"_{workspace_id}"
        if plant_id:
            sub_id += f"_{plant_id}"

        sub = Subscription(
            subscription_id=sub_id,
            subscriber_id="closed_loop_coordinator",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
        )
        registered = self.event_bus.subscribe(sub, self.handle_event)
        self._subscribed_tenants[tenant_id] = registered.subscription_id
        logger.info(
            "Registered closed-loop subscription '%s' for tenant '%s'",
            registered.subscription_id,
            tenant_id,
        )
        return registered

    # -------------------------------------------------------------------------
    # Feedback Loop Guard
    # -------------------------------------------------------------------------

    def _is_feedback_or_internal_event(self, event: CanonicalEvent) -> bool:
        """
        Deterministic loop guard: prevents feedback events or coordinator-emitted events
        from recursively triggering new verification runs.
        """
        # 1. Provenance check
        prov_str = getattr(event.provenance, "source", None) or str(event.provenance or "")
        if prov_str in (
            "closed_loop_coordinator",
            "verification_coordinator",
            "verification_service",
            "system_closed_loop",
        ):
            return True

        # 2. Explicit feedback payload indicator
        if isinstance(event.payload, dict) and event.payload.get("is_feedback_event") is True:
            return True

        # 3. Standardized feedback event type prefix
        if event.event_type.startswith("verification.feedback"):
            return True

        # 4. System category with feedback in name
        if event.category == EventCategory.SYSTEM and "feedback" in event.event_type.lower():
            return True

        # 5. Upstream source system reference
        if event.references and event.references.source_system in (
            "verification_service",
            "closed_loop_coordinator",
        ):
            return True

        return False

    # -------------------------------------------------------------------------
    # Deterministic Eligibility Evaluation
    # -------------------------------------------------------------------------

    def evaluate_eligibility(self, event: CanonicalEvent) -> EligibilityDecision:
        """
        Evaluates whether an incoming canonical event is eligible to trigger verification.
        Fails closed with explicit machine-readable reason code.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat().replace("+00:00", "Z")

        # 1. Check feature flag configuration
        if not self.enabled or not self.event_trigger_enabled:
            return EligibilityDecision(
                status=EligibilityStatus.IGNORED,
                reason_code=EligibilityReasonCode.DISABLED.value,
                explanation="Closed-loop verification trigger is currently disabled by configuration.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 2. Check Feedback Loop Guard (Mandatory invariant)
        if self._is_feedback_or_internal_event(event):
            return EligibilityDecision(
                status=EligibilityStatus.IGNORED,
                reason_code=EligibilityReasonCode.FEEDBACK_LOOP_GUARD.value,
                explanation="Event is a verification feedback event and was ignored by the feedback loop guard.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 3. Check Scope Boundaries (Fail-closed on missing or invalid tenant/plant)
        if not event.tenant_id or not event.tenant_id.strip() or event.tenant_id == "global":
            return EligibilityDecision(
                status=EligibilityStatus.REJECTED,
                reason_code=EligibilityReasonCode.MISSING_SCOPE.value,
                explanation="Authoritative tenant isolation boundary is missing or invalid.",
                tenant_id=event.tenant_id or "unknown",
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        if not event.plant_id or not event.plant_id.strip() or event.plant_id == "global":
            return EligibilityDecision(
                status=EligibilityStatus.REJECTED,
                reason_code=EligibilityReasonCode.MISSING_SCOPE.value,
                explanation="Authoritative plant scope boundary is missing or non-specific ('global').",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id or "unknown",
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 4. Check Event Provenance
        prov_val = str(getattr(event.provenance, "source", None) or event.provenance or "").strip()
        if not prov_val or prov_val.lower() in ("untrusted", "unknown", "fake", "spoofed"):
            return EligibilityDecision(
                status=EligibilityStatus.REJECTED,
                reason_code=EligibilityReasonCode.UNTRUSTED_PROVENANCE.value,
                explanation="Event provenance is untrusted, invalid, or missing.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 5. Check Event Lifecycle
        if event.lifecycle in (EventLifecycle.INVALIDATED, EventLifecycle.SUPERSEDED):
            return EligibilityDecision(
                status=EligibilityStatus.IGNORED,
                reason_code=EligibilityReasonCode.INVALIDATED_EVENT.value,
                explanation=f"Event lifecycle '{event.lifecycle.value}' is not active or recorded.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 6. Check Event Freshness & Future Dating
        obs_dt = _parse_iso_timestamp(event.occurred_at or event.observed_at)
        if obs_dt:
            age_sec = (now_dt - obs_dt).total_seconds()
            if age_sec < -60.0:
                return EligibilityDecision(
                    status=EligibilityStatus.REJECTED,
                    reason_code=EligibilityReasonCode.FUTURE_DATED_EVENT.value,
                    explanation=f"Event timestamp is future-dated by {-age_sec:.1f}s beyond tolerance.",
                    tenant_id=event.tenant_id,
                    workspace_id=event.workspace_id,
                    plant_id=event.plant_id,
                    trigger_event_id=event.event_id,
                    trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                    trigger_event_type=event.event_type,
                    trigger_category=event.category.value,
                    decided_at=now_iso,
                )
            if age_sec > SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS:
                return EligibilityDecision(
                    status=EligibilityStatus.IGNORED,
                    reason_code=EligibilityReasonCode.STALE_EVENT.value,
                    explanation=f"Event age ({age_sec:.1f}s) exceeds maximum trigger threshold ({SAGE_VERIFICATION_EVENT_MAX_AGE_SECONDS:.0f}s).",
                    tenant_id=event.tenant_id,
                    workspace_id=event.workspace_id,
                    plant_id=event.plant_id,
                    trigger_event_id=event.event_id,
                    trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                    trigger_event_type=event.event_type,
                    trigger_category=event.category.value,
                    decided_at=now_iso,
                )

        # 7. Check Category Eligibility
        if event.category not in ELIGIBLE_EVENT_CATEGORIES:
            return EligibilityDecision(
                status=EligibilityStatus.IGNORED,
                reason_code=EligibilityReasonCode.UNSUPPORTED_EVENT_TYPE.value,
                explanation=f"Event category '{event.category.value}' is not configured for continuous verification.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        # 8. Resolve Target Mission Reference
        payload = event.payload if isinstance(event.payload, dict) else {}
        mission_id = (
            payload.get("mission_id")
            or payload.get("target_mission_id")
            or (
                event.references.source_record_id
                if event.references and event.references.source_system in ("mission", "mission_service")
                else None
            )
        )

        if not mission_id or not str(mission_id).strip():
            return EligibilityDecision(
                status=EligibilityStatus.IGNORED,
                reason_code=EligibilityReasonCode.MISSING_TARGET_REFERENCE.value,
                explanation="Operational event does not reference a specific governed mission target.",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                trigger_event_id=event.event_id,
                trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
                trigger_event_type=event.event_type,
                trigger_category=event.category.value,
                decided_at=now_iso,
            )

        clean_mission_id = str(mission_id).strip()

        # Parse optional target specifics from payload
        mission_rev = payload.get("mission_revision") or payload.get("expected_mission_revision")
        if mission_rev is not None:
            try:
                mission_rev = int(mission_rev)
            except (ValueError, TypeError):
                mission_rev = None

        target_type_str = payload.get("target_type")
        target_type_enum: Optional[VerificationTargetType] = None
        if target_type_str and str(target_type_str).upper() in ("CRITERION", "STEP"):
            target_type_enum = VerificationTargetType(str(target_type_str).upper())

        target_id = payload.get("target_id")
        clean_target_id = str(target_id).strip() if target_id else None

        return EligibilityDecision(
            status=EligibilityStatus.ELIGIBLE,
            reason_code=EligibilityReasonCode.VERIFICATION_REQUESTED.value,
            explanation=f"Operational event '{event.event_type}' matches continuous verification criteria for mission '{clean_mission_id}'.",
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            plant_id=event.plant_id,
            trigger_event_id=event.event_id,
            trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
            trigger_event_type=event.event_type,
            trigger_category=event.category.value,
            mission_id=clean_mission_id,
            mission_revision=mission_rev,
            target_type=target_type_enum,
            target_id=clean_target_id,
            decided_at=now_iso,
        )

    # -------------------------------------------------------------------------
    # Trusted Server Identity Construction
    # -------------------------------------------------------------------------

    def _build_trusted_service_identity(self, event: CanonicalEvent) -> Identity:
        """
        Builds a strictly bound, server-authoritative service identity.
        NEVER accepts client-supplied or payload-injected user_id, roles, or clearance.
        """
        return Identity(
            user_id=f"system:closed_loop_coordinator:{event.tenant_id}",
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id or "global",
            assigned_plants=[event.plant_id] if event.plant_id and event.plant_id != "global" else [],
            roles=["SYSTEM_VERIFIER"],
            permissions=[
                "mission.verification.request",
                "mission.verification.read",
                "verifications.read",
                "verifications.write",
            ],
            clearance_level=2,
            is_server_authoritative=True,
        )

    # -------------------------------------------------------------------------
    # Deterministic Idempotency Key Computation
    # -------------------------------------------------------------------------

    def _compute_trigger_idempotency_key(
        self, event: CanonicalEvent, decision: EligibilityDecision
    ) -> str:
        """
        Computes deterministic idempotency key derived from:
        tenant, workspace, event fingerprint, mission ID, revision, and target reference.
        Prevents redelivery or worker retries from duplicating verification runs.
        """
        fingerprint = event.event_fingerprint or event.compute_fingerprint()
        components = [
            event.tenant_id,
            event.workspace_id,
            fingerprint,
            str(decision.mission_id or ""),
            str(decision.mission_revision or "latest"),
            str(decision.target_id or "all"),
            RULE_SET_VERSION,
        ]
        raw_string = "|".join(components)
        h = hashlib.sha256(raw_string.encode("utf-8")).hexdigest()[:32]
        return f"cltrig_{h}"

    # -------------------------------------------------------------------------
    # Request Verification
    # -------------------------------------------------------------------------

    async def request_verification(
        self, event: CanonicalEvent, decision: EligibilityDecision
    ) -> Tuple[Optional[VerificationRun], Optional[str]]:
        """
        Invokes continuous verification through the existing VerificationService.
        Enforces scope validation and idempotency. Returns (VerificationRun, error_reason).
        """
        if not decision.mission_id:
            return None, "MISSING_MISSION_ID"

        trusted_identity = self._build_trusted_service_identity(event)
        idempotency_key = self._compute_trigger_idempotency_key(event, decision)

        req = VerificationRequest(
            target_type=decision.target_type,
            target_id=decision.target_id,
            expected_mission_revision=decision.mission_revision,
            trigger_type=TriggerType.EVIDENCE_EVENT,
            rule_type=RuleType.EVIDENCE_FRESH,
            idempotency_key=idempotency_key,
        )

        try:
            run = self.verification_service.request_verification(
                identity=trusted_identity,
                mission_id=decision.mission_id,
                request=req,
                request_id=f"req_cl_{event.event_id[:16]}",
                trace_id=event.correlation_id or event.event_id,
            )
            return run, None

        except VerificationPermissionError as e:
            logger.warning(
                "Scope or permission violation triggering verification for mission '%s': %s",
                decision.mission_id,
                e,
            )
            return None, EligibilityReasonCode.SCOPE_MISMATCH.value

        except VerificationNotFoundError as e:
            logger.warning(
                "Mission '%s' not found within authorized scope: %s",
                decision.mission_id,
                e,
            )
            return None, EligibilityReasonCode.MISSING_TARGET_REFERENCE.value

        except VerificationRevisionMismatchError as e:
            logger.warning(
                "Mission '%s' revision mismatch: %s",
                decision.mission_id,
                e,
            )
            return None, "REVISION_MISMATCH"

        except VerificationValidationError as e:
            logger.warning(
                "Verification validation failed for mission '%s': %s",
                decision.mission_id,
                e,
            )
            return None, EligibilityReasonCode.VERIFICATION_FAILED.value

        except Exception as e:
            logger.error(
                "Unexpected exception in request_verification for mission '%s': %s",
                decision.mission_id,
                e,
                exc_info=True,
            )
            return None, "UNEXPECTED_ERROR"

    # -------------------------------------------------------------------------
    # Record Feedback & Emit Structured Feedback Event
    # -------------------------------------------------------------------------

    async def record_feedback(
        self,
        event: CanonicalEvent,
        decision: EligibilityDecision,
        run: Optional[VerificationRun],
        error_reason: Optional[str] = None,
    ) -> VerificationFeedbackRecord:
        """
        Records durable feedback in the repository and publishes a structured
        feedback event to the EventBus.
        """
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat().replace("+00:00", "Z")
        feedback_id = f"fb_{uuid.uuid4().hex[:16]}"
        idempotency_key = self._compute_trigger_idempotency_key(event, decision) if decision.mission_id else None

        # Build Feedback Canonical Event if verification ran
        feedback_event_id: Optional[str] = None
        feedback_event_fingerprint: Optional[str] = None

        if run is not None:
            fb_event = CanonicalEvent(
                event_id=f"evt_fb_{uuid.uuid4().hex[:16]}",
                schema_version="event.v1",
                tenant_id=event.tenant_id,
                workspace_id=event.workspace_id,
                plant_id=event.plant_id,
                category=EventCategory.SYSTEM,
                event_type="verification.feedback.recorded",
                severity=EventSeverity.INFO if run.status == VerificationStatus.VERIFIED else EventSeverity.MEDIUM,
                lifecycle=EventLifecycle.RECORDED,
                occurred_at=now_iso,
                observed_at=now_iso,
                correlation_id=event.correlation_id or event.event_id,
                causation_id=event.event_id,
                provenance="closed_loop_coordinator",
                references=EventReferences(
                    source_system="verification_service",
                    source_record_id=run.verification_id,
                ),
                payload={
                    "trigger_event_id": event.event_id,
                    "trigger_event_fingerprint": event.event_fingerprint or event.compute_fingerprint(),
                    "verification_id": run.verification_id,
                    "mission_id": run.mission_id,
                    "mission_revision": run.mission_revision,
                    "verification_scope": run.verification_scope,
                    "verification_status": run.status.value,
                    "is_diagnostic": run.is_diagnostic,
                    "diagnostic_status": run.diagnostic_status.value if run.diagnostic_status else None,
                    "diagnostic_outcome": run.diagnostic_outcome,
                    "target_count": run.target_count,
                    "verified_count": run.verified_count,
                    "unverified_count": run.unverified_count,
                    "summary": run.summary,
                    "is_feedback_event": True,
                    "trigger_rule_version": run.provenance.rule_set_version if run.provenance else RULE_SET_VERSION,
                    "eligibility_status": decision.status.value,
                    "eligibility_reason": decision.reason_code,
                },
            )
            fb_event.apply_fingerprint()
            feedback_event_id = fb_event.event_id
            feedback_event_fingerprint = fb_event.event_fingerprint

            # Publish feedback event asynchronously to EventBus
            try:
                await self.event_bus.publish(fb_event)
            except Exception as pub_err:
                logger.warning("Could not publish feedback event to EventBus: %s", pub_err)

        # Assemble and persist Feedback Record
        status_for_record = decision.status
        reason_for_record = error_reason or decision.reason_code

        feedback_record = VerificationFeedbackRecord(
            feedback_id=feedback_id,
            tenant_id=event.tenant_id,
            workspace_id=event.workspace_id,
            plant_id=event.plant_id,
            trigger_event_id=event.event_id,
            trigger_event_fingerprint=event.event_fingerprint or event.compute_fingerprint(),
            eligibility_status=status_for_record,
            eligibility_reason=reason_for_record,
            mission_id=decision.mission_id,
            mission_revision=run.mission_revision if run else decision.mission_revision,
            verification_id=run.verification_id if run else None,
            verification_status=run.status.value if run else None,
            is_diagnostic=run.is_diagnostic if run else False,
            diagnostic_status=run.diagnostic_status.value if run and run.diagnostic_status else None,
            diagnostic_outcome=run.diagnostic_outcome if run else None,
            feedback_event_id=feedback_event_id,
            feedback_event_fingerprint=feedback_event_fingerprint,
            idempotency_key=idempotency_key,
            details={
                "trigger_event_type": event.event_type,
                "trigger_category": event.category.value,
                "explanation": decision.explanation,
                "notice": MANDATORY_VERIFICATION_NOTICE,
            },
            created_at=now_iso,
        )

        persisted = self.repository.save_feedback_record(feedback_record)
        return persisted

    # -------------------------------------------------------------------------
    # Main Event Handler (EventBus Subscriber Callback)
    # -------------------------------------------------------------------------

    async def handle_event(self, delivery: EventDelivery, event: CanonicalEvent) -> bool:
        """
        SubscriberCallback implementation for the EventBus.
        Processes an event through the closed-loop learning foundation:
        Observe -> Decide -> Verify -> Record Feedback.
        Returns True to acknowledge successful delivery processing.
        """
        try:
            # Stage A & B: Observe & Evaluate Eligibility
            decision = self.evaluate_eligibility(event)

            if decision.status == EligibilityStatus.IGNORED:
                logger.debug(
                    "Event '%s' ignored by closed-loop policy: %s (%s)",
                    event.event_id,
                    decision.reason_code,
                    decision.explanation,
                )
                # Durably record trace of ignored decision for audit visibility
                await self.record_feedback(event, decision, run=None)
                return True

            if decision.status == EligibilityStatus.REJECTED:
                logger.info(
                    "Event '%s' rejected by closed-loop policy: %s (%s)",
                    event.event_id,
                    decision.reason_code,
                    decision.explanation,
                )
                await self.record_feedback(event, decision, run=None)
                return True

            if decision.status == EligibilityStatus.DEFERRED:
                logger.info("Event '%s' deferred by closed-loop policy", event.event_id)
                await self.record_feedback(event, decision, run=None)
                return True

            # Stage C: Verify
            run, err = await self.request_verification(event, decision)

            # Stage D & E: Record Feedback & Publish Feedback Event
            await self.record_feedback(event, decision, run=run, error_reason=err)
            return True

        except Exception as e:
            logger.error(
                "Unhandled error in Closed-Loop Coordinator processing event '%s': %s",
                event.event_id,
                e,
                exc_info=True,
            )
            # Return False so EventBus can record failure, calculate backoff retry, or dead-letter
            return False


# Canonical singleton coordinator instance
verification_trigger_coordinator = VerificationTriggerCoordinator()


def get_verification_trigger_coordinator() -> VerificationTriggerCoordinator:
    """Returns canonical singleton coordinator instance."""
    return verification_trigger_coordinator
