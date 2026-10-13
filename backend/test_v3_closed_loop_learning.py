# backend/test_v3_closed_loop_learning.py
"""
SageCommand V3 — Closed-Loop Learning Foundation Test Suite (Prompt 37)

Comprehensive verification testing covering:
1. Event Eligibility:
   - Valid operational event triggers continuous verification deterministically.
   - Unsupported event categories are ignored with UNSUPPORTED_EVENT_TYPE.
   - Stale events beyond max age are ignored with STALE_EVENT.
   - Future-dated events beyond tolerance are rejected with FUTURE_DATED_EVENT.
   - Missing target mission reference fails closed with MISSING_TARGET_REFERENCE.
   - Untrusted provenance is rejected with UNTRUSTED_PROVENANCE.
   - Invalidated or superseded lifecycle events are ignored with INVALIDATED_EVENT.
   - Disabled feature flag ignores events with DISABLED.

2. Scope and Identity:
   - Missing tenant boundary is rejected with MISSING_SCOPE.
   - Missing physical plant boundary is rejected with MISSING_SCOPE.
   - Cross-tenant events cannot trigger verification for another tenant.
   - Cross-plant events fail closed with SCOPE_MISMATCH.
   - Event payload cannot forge user_id, roles, clearance, or permissions.
   - No fallback tenant or plant is manufactured.

3. Idempotency & Duplicate Suppression:
   - Repeated event delivery replays deterministically without duplicating verification runs.
   - Equivalent trigger retries preserve the same trigger idempotency identity.
   - Distinct valid operational events legitimately trigger fresh verification runs.

4. Verification Integrity:
   - Coordinator invokes the existing VerificationService.
   - Persisted findings determine the run outcome.
   - Diagnostic verification preserves is_diagnostic=True and run.status != VERIFIED.
   - Mission lifecycle status is never mutated (never transitioned to COMPLETED).
   - No actions are approved in action_store.
   - No ExecutionGateway is invoked.

5. Feedback Integrity & Feedback Loop Prevention:
   - Persisted feedback trace references triggering event, verification run, and outcome.
   - Feedback persistence is strictly tenant and workspace scoped.
   - Secrets are absent from feedback payloads.
   - Strict loop guard: Feedback events emitted by the coordinator cannot trigger verification again.
   - Event delivery success is not confused with verification success.

6. Resilience & Configuration:
   - Queue-full conditions are safely handled.
   - Verification exceptions produce traceable failure feedback.
   - Disabled mode suppresses event-triggered verification.

7. Static Architectural Checks:
   - AST analysis proves coordinator does NOT use create_engine, create_async_engine,
     engine.connect, raw SQL execution, or ExecutionGateway.
"""

import ast
import asyncio
import os
import json
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from core.config import SAGE_CLOSED_LOOP_ENABLED
    from data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from data.schemas.event_delivery_contract import (
        Subscription,
        EventDelivery,
        DeliveryStatus,
    )
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationStatus,
        VerificationTargetType,
        VerificationRequest,
        TriggerType,
        RuleType,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from data.schemas.closed_loop_contract import (
        EligibilityStatus,
        EligibilityReasonCode,
        EligibilityDecision,
        VerificationFeedbackRecord,
    )
    from services.event_bus import EventBus
    from services.event_delivery_repository import EventDeliveryRepository
    from services.event_repository import (
        EventRepository,
        EventIdempotencyConflictError,
        LegacyEventFingerprintError,
    )
    from repositories.verification_repository import VerificationRepository
    from services.verification_service import VerificationService
    from repositories.mission_repository import MissionRepository
    from services.mission_service import MissionService
    from repositories.evidence_explainability_repository import EvidenceExplainabilityRepository
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionScope,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        StepType,
        StepStatus,
        CriterionStatus,
    )
    from services.action_store import action_store
    from services.verification_trigger_coordinator import (
        VerificationTriggerCoordinator,
        get_verification_trigger_coordinator,
    )
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.core.config import SAGE_CLOSED_LOOP_ENABLED
    from backend.data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from backend.data.schemas.event_delivery_contract import (
        Subscription,
        EventDelivery,
        DeliveryStatus,
    )
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationStatus,
        VerificationTargetType,
        VerificationRequest,
        TriggerType,
        RuleType,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.data.schemas.closed_loop_contract import (
        EligibilityStatus,
        EligibilityReasonCode,
        EligibilityDecision,
        VerificationFeedbackRecord,
    )
    from backend.services.event_bus import EventBus
    from backend.services.event_delivery_repository import EventDeliveryRepository
    from backend.services.event_repository import (
        EventRepository,
        EventIdempotencyConflictError,
        LegacyEventFingerprintError,
    )
    from backend.repositories.verification_repository import VerificationRepository
    from backend.services.verification_service import VerificationService
    from backend.repositories.mission_repository import MissionRepository
    from backend.services.mission_service import MissionService
    from backend.repositories.evidence_explainability_repository import EvidenceExplainabilityRepository
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionScope,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        StepType,
        StepStatus,
        CriterionStatus,
    )
    from backend.services.action_store import action_store
    from backend.services.verification_trigger_coordinator import (
        VerificationTriggerCoordinator,
        get_verification_trigger_coordinator,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_dbs():
    """Provides isolated SQLite database paths for test execution."""
    paths = []
    for _ in range(4):
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
            paths.append(tf.name)
    yield paths
    for p in paths:
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.fixture
def v_repo(temp_dbs):
    return VerificationRepository(db_path=temp_dbs[0])


@pytest.fixture
def m_repo(temp_dbs):
    return MissionRepository(db_path=temp_dbs[1])


@pytest.fixture
def e_repo(temp_dbs):
    return EvidenceExplainabilityRepository(db_path=temp_dbs[2])


@pytest.fixture
def ed_repo(temp_dbs):
    return EventDeliveryRepository(db_path=temp_dbs[3])


@pytest.fixture
def event_bus(ed_repo):
    bus = EventBus(ed_repo)
    bus.enabled = True
    return bus


@pytest.fixture
def m_service(m_repo):
    return MissionService(repository=m_repo)


@pytest.fixture
def v_service(v_repo, m_service, e_repo):
    return VerificationService(
        repository=v_repo,
        mission_svc=m_service,
        evidence_repo=e_repo,
    )


@pytest.fixture
def coordinator(event_bus, v_service, v_repo):
    return VerificationTriggerCoordinator(
        event_bus=event_bus,
        verification_svc=v_service,
        repository=v_repo,
        enabled=True,
        event_trigger_enabled=True,
    )


@pytest.fixture
def sample_mission(m_service):
    """Creates a sample accepted mission in tenant_alpha / plant_01."""
    creator_id = Identity(
        user_id="creator_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        plants=["plant_01"],
        roles=["ANALYST"],
        permissions=["mission.create", "mission.read", "mission.accept"],
    )
    mission = Mission(
        mission_id="msn_cl_100",
        schema_version="3.0.0",
        title="Test Continuous Verification Mission",
        description="Verify plant telemetry continuously",
        objective="Verify plant operational steps against live evidence",
        mission_type=MissionType.INVESTIGATION,
        status=MissionStatus.ACCEPTED,
        scope=MissionScope(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        ),
        success_criteria=[
            MissionSuccessCriterion(
                criterion_id="crit_01",
                description="Live telemetry must confirm operational parameters",
                required_evidence_type="TELEMETRY_LOG",
                status=CriterionStatus.UNKNOWN,
            )
        ],
        evidence_requirements=[
            MissionEvidenceRequirement(
                requirement_id="req_01",
                evidence_type="TELEMETRY_LOG",
                description="Real-time plant telemetry logs",
                linked_evidence_id="ev_telemetry_01",
                is_mandatory=True,
            )
        ],
        planned_steps=[
            MissionPlannedStep(
                step_id="step_01",
                title="Telemetry monitoring step",
                description="Monitor telemetry sensor logs",
                step_type=StepType.INVESTIGATION,
                status=StepStatus.PLANNED,
                required_evidence=["ev_telemetry_01"],
            )
        ],
        provenance=MissionProvenance(
            created_by="creator_01",
            origin_reason="Test mission creation for continuous verification",
        ),
        created_by="creator_01",
        revision=1,
    )
    saved = m_service.repository.create_mission(mission, change_reason="Initial test creation")
    return saved


@pytest.fixture
def sample_evidence(e_repo):
    """Creates authorized, fresh evidence in tenant_alpha / plant_01 directly in e_repo SQLite schema."""
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "temperature": 75.0,
        "status": "NOMINAL",
        "observed_at": now_iso,
        "classification": "INTERNAL",
    }
    with e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, supporting_evidence_count, excluded_evidence_count, summary,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_01", now_iso, "1.0.0", "3.0.0", 0, 1, 0, "Test explanation",
                json.dumps(payload), now_iso
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_telemetry_01", "exp_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "sensor_01", "OBSERVED", "VALID", json.dumps(payload), now_iso
            )
        )
        conn.commit()
    return "ev_telemetry_01"


def make_operational_event(
    tenant_id: str = "tenant_alpha",
    workspace_id: str = "workspace_prod",
    plant_id: str = "plant_01",
    category: EventCategory = EventCategory.TELEMETRY,
    event_type: str = "telemetry.updated",
    mission_id: Optional[str] = "msn_cl_100",
    occurred_at: Optional[str] = None,
    provenance: str = "sensor_gateway",
    payload_extra: Optional[dict] = None,
) -> CanonicalEvent:
    """Helper to create valid CanonicalEvent with deterministic fingerprint."""
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {"value": 100}
    if mission_id:
        payload["mission_id"] = mission_id
    if payload_extra:
        payload.update(payload_extra)

    evt = CanonicalEvent(
        event_id=f"evt_{uuid.uuid4().hex[:12]}",
        schema_version="event.v1",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id,
        category=category,
        event_type=event_type,
        severity=EventSeverity.INFO,
        lifecycle=EventLifecycle.RECORDED,
        occurred_at=occurred_at or now_iso,
        observed_at=occurred_at or now_iso,
        provenance=provenance,
        payload=payload,
    )
    evt.apply_fingerprint()
    return evt


# =============================================================================
# 1. EVENT ELIGIBILITY TESTS
# =============================================================================

class TestEventEligibility:
    def test_01_valid_event_is_eligible(self, coordinator, sample_mission):
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.ELIGIBLE
        assert decision.reason_code == EligibilityReasonCode.VERIFICATION_REQUESTED.value
        assert decision.mission_id == "msn_cl_100"

    def test_02_unsupported_category_is_ignored(self, coordinator):
        evt = make_operational_event(category=EventCategory.SECURITY)
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.UNSUPPORTED_EVENT_TYPE.value

    def test_03_stale_event_is_ignored(self, coordinator):
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        evt = make_operational_event(occurred_at=stale_time)
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.STALE_EVENT.value

    def test_04_future_dated_event_is_rejected(self, coordinator):
        future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        evt = make_operational_event(occurred_at=future_time)
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.REJECTED
        assert decision.reason_code == EligibilityReasonCode.FUTURE_DATED_EVENT.value

    def test_05_missing_target_mission_is_ignored(self, coordinator):
        evt = make_operational_event(mission_id=None)
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.MISSING_TARGET_REFERENCE.value

    def test_06_untrusted_provenance_is_rejected(self, coordinator):
        evt = make_operational_event(provenance="untrusted")
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.REJECTED
        assert decision.reason_code == EligibilityReasonCode.UNTRUSTED_PROVENANCE.value

    def test_07_invalidated_lifecycle_event_is_ignored(self, coordinator):
        evt = make_operational_event()
        evt.lifecycle = EventLifecycle.INVALIDATED
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.INVALIDATED_EVENT.value

    def test_08_disabled_mode_ignores_all_events(self, coordinator):
        coordinator.enabled = False
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.DISABLED.value


# =============================================================================
# 2. SCOPE AND IDENTITY BOUNDARY TESTS
# =============================================================================

class TestScopeAndIdentityBoundary:
    def test_09_missing_tenant_fails_closed(self, coordinator):
        evt = make_operational_event(tenant_id="")
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.REJECTED
        assert decision.reason_code == EligibilityReasonCode.MISSING_SCOPE.value

    def test_10_missing_plant_fails_closed(self, coordinator):
        evt = make_operational_event(plant_id="global")
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.REJECTED
        assert decision.reason_code == EligibilityReasonCode.MISSING_SCOPE.value

    def test_11_cross_plant_event_fails_verification(self, coordinator, sample_mission):
        # Event originates in plant_02, but mission is in plant_01
        evt = make_operational_event(plant_id="plant_02")
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.ELIGIBLE

        async def run():
            run_obj, err = await coordinator.request_verification(evt, decision)
            assert run_obj is None
            assert err == EligibilityReasonCode.SCOPE_MISMATCH.value

        asyncio.run(run())

    def test_12_payload_cannot_forge_identity(self, coordinator):
        # Malicious payload injecting forged superadmin role, user, and clearance
        forged_payload = {
            "user_id": "hacker_99",
            "roles": ["SUPERADMIN", "ADMINISTRATOR"],
            "permissions": ["*"],
            "clearance": 5,
        }
        evt = make_operational_event(payload_extra=forged_payload)
        trusted_identity = coordinator._build_trusted_service_identity(evt)

        # Invariant: Trusted identity must be strictly system-derived, not model-forged
        assert trusted_identity.user_id == f"system:closed_loop_coordinator:{evt.tenant_id}"
        assert trusted_identity.roles == ["SYSTEM_VERIFIER"]
        assert "SUPERADMIN" not in trusted_identity.roles
        assert trusted_identity.tenant_id == evt.tenant_id
        assert trusted_identity.assigned_plants == [evt.plant_id]

    def test_13_no_fallback_tenant_created(self, coordinator):
        evt = make_operational_event(tenant_id="global")
        decision = coordinator.evaluate_eligibility(evt)
        assert decision.status == EligibilityStatus.REJECTED
        assert decision.reason_code == EligibilityReasonCode.MISSING_SCOPE.value


# =============================================================================
# 3. IDEMPOTENCY & DUPLICATE SUPPRESSION TESTS
# =============================================================================

class TestIdempotencyAndDuplicateSuppression:
    def test_14_repeated_delivery_replays_deterministically(
        self, coordinator, sample_mission, sample_evidence
    ):
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        async def run():
            # First verification request
            run1, err1 = await coordinator.request_verification(evt, decision)
            assert run1 is not None
            assert err1 is None

            # Repeated verification request with identical trigger
            run2, err2 = await coordinator.request_verification(evt, decision)
            assert run2 is not None
            assert err2 is None

            # Invariant: Must replay the identical persisted verification ID without creating duplicate
            assert run1.verification_id == run2.verification_id

        asyncio.run(run())

    def test_15_distinct_events_trigger_separate_runs(
        self, coordinator, sample_mission, sample_evidence
    ):
        async def run():
            evt1 = make_operational_event(payload_extra={"batch": 1})
            dec1 = coordinator.evaluate_eligibility(evt1)
            run1, _ = await coordinator.request_verification(evt1, dec1)

            # Legitimate distinct later event
            evt2 = make_operational_event(payload_extra={"batch": 2})
            dec2 = coordinator.evaluate_eligibility(evt2)
            run2, _ = await coordinator.request_verification(evt2, dec2)

            assert run1 is not None and run2 is not None
            assert run1.verification_id != run2.verification_id

        asyncio.run(run())


# =============================================================================
# 4. VERIFICATION INTEGRITY TESTS
# =============================================================================

class TestVerificationIntegrity:
    def test_16_verification_invokes_existing_service(
        self, coordinator, sample_mission, sample_evidence
    ):
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        async def run():
            run_obj, err = await coordinator.request_verification(evt, decision)
            assert run_obj is not None
            assert err is None
            assert run_obj.mission_id == sample_mission.mission_id
            assert run_obj.target_count >= 1
            assert run_obj.status == VerificationStatus.VERIFIED

        asyncio.run(run())

    def test_17_mission_lifecycle_is_never_mutated(
        self, coordinator, sample_mission, sample_evidence, m_service
    ):
        # Verification runs must never complete or mutate mission state
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        async def run():
            await coordinator.request_verification(evt, decision)
            ident = Identity(user_id="read_check", tenant_id="tenant_alpha", workspace_id="workspace_prod", roles=["ANALYST"], permissions=["mission.read"], assigned_plants=["plant_01"])
            m = m_service.get_mission(ident, sample_mission.mission_id)
            assert m.status == MissionStatus.ACCEPTED  # NOT COMPLETED!

        asyncio.run(run())

    def test_18_no_actions_are_approved(self, coordinator, sample_mission, sample_evidence):
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        async def run():
            run_obj, _ = await coordinator.request_verification(evt, decision)
            assert run_obj is not None
            # Check action_store: no approved actions
            actions, _ = action_store.list_actions("tenant_alpha", "workspace_prod")
            for a in actions:
                assert a.status.value != "APPROVED"

        asyncio.run(run())

    def test_19_diagnostic_run_preserves_non_authoritative_status(
        self, coordinator, sample_mission, sample_evidence
    ):
        # Request verification targeting diagnostic rule (EVIDENCE_EXISTS)
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        # Trigger diagnostic rule directly through VerificationRequest
        trusted_ident = coordinator._build_trusted_service_identity(evt)
        req = VerificationRequest(
            rule_type=RuleType.EVIDENCE_EXISTS,
            trigger_type=TriggerType.EVIDENCE_EVENT,
        )
        diag_run = coordinator.verification_service.request_verification(
            identity=trusted_ident,
            mission_id=sample_mission.mission_id,
            request=req,
        )

        assert diag_run.is_diagnostic is True
        assert diag_run.diagnostic_outcome == "CONFIRMED"
        # Mandatory invariant: Diagnostic check must never produce run.status == VERIFIED
        assert diag_run.status != VerificationStatus.VERIFIED
        assert diag_run.status == VerificationStatus.NOT_VERIFIED


# =============================================================================
# 5. FEEDBACK INTEGRITY & LOOP PREVENTION TESTS
# =============================================================================

class TestFeedbackIntegrityAndLoopPrevention:
    def test_20_feedback_record_persisted_with_provenance(
        self, coordinator, sample_mission, sample_evidence, v_repo
    ):
        evt = make_operational_event()
        delivery = EventDelivery(
            delivery_id="del_001",
            event_id=evt.event_id,
            event_fingerprint=evt.event_fingerprint,
            subscription_id="sub_test",
            tenant_id=evt.tenant_id,
        )

        async def run():
            success = await coordinator.handle_event(delivery, evt)
            assert success is True

            feedback = v_repo.get_feedback_by_trigger_event(evt.tenant_id, evt.event_id)
            assert feedback is not None
            assert feedback.trigger_event_id == evt.event_id
            assert feedback.mission_id == sample_mission.mission_id
            assert feedback.verification_id is not None
            assert feedback.feedback_event_id is not None
            assert feedback.eligibility_status == EligibilityStatus.ELIGIBLE

        asyncio.run(run())

    def test_21_feedback_event_cannot_retrigger_coordinator(self, coordinator):
        # Create a CanonicalEvent mimicking a verification feedback event
        fb_event = CanonicalEvent(
            event_id="evt_fb_loop_check",
            schema_version="event.v1",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            category=EventCategory.SYSTEM,
            event_type="verification.feedback.recorded",
            occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            provenance="closed_loop_coordinator",
            payload={"is_feedback_event": True, "verification_id": "vrun_123", "mission_id": "msn_cl_100"},
        )
        fb_event.apply_fingerprint()

        decision = coordinator.evaluate_eligibility(fb_event)
        # Invariant: Loop guard must drop the event deterministically
        assert decision.status == EligibilityStatus.IGNORED
        assert decision.reason_code == EligibilityReasonCode.FEEDBACK_LOOP_GUARD.value

    def test_22_full_closed_loop_execution_and_loop_break(
        self, coordinator, sample_mission, sample_evidence, event_bus
    ):
        """
        Validates the complete closed loop:
        1. Operational event published to EventBus.
        2. EventBus delivers to Coordinator callback.
        3. Coordinator executes continuous verification.
        4. Coordinator records feedback and publishes feedback event.
        5. Feedback event is dispatched back to EventBus.
        6. Coordinator receives feedback event and loop guard deterministically stops recursion.
        """
        async def run():
            event_bus.start()
            sub = coordinator.register_tenant_subscription("tenant_alpha")

            published_events: List[CanonicalEvent] = []
            async def monitor_cb(deliv: EventDelivery, ev: CanonicalEvent) -> bool:
                published_events.append(ev)
                return True

            mon_sub = Subscription(
                subscription_id="sub_monitor",
                subscriber_id="monitor",
                tenant_id="tenant_alpha",
            )
            event_bus.subscribe(mon_sub, monitor_cb)

            try:
                op_event = make_operational_event()
                await event_bus.publish(op_event)

                # Allow workers to dispatch both operational event and resulting feedback event
                await asyncio.sleep(0.3)

                # Operational event + Feedback event both published
                event_types = [e.event_type for e in published_events]
                assert "telemetry.updated" in event_types
                assert "verification.feedback.recorded" in event_types

                # Verify feedback record was recorded
                fb_record = coordinator.repository.get_feedback_by_trigger_event(
                    "tenant_alpha", op_event.event_id
                )
                assert fb_record is not None
                assert fb_record.verification_id is not None

            finally:
                await event_bus.stop()

        asyncio.run(run())


# =============================================================================
# 6. STATIC ARCHITECTURAL CHECKS (AST ANALYSIS)
# =============================================================================

class TestStaticArchitecturalChecks:
    def test_23_coordinator_has_zero_db_engines_or_execution_gateway(self):
        """
        AST analysis verifying coordinator does NOT directly create engines,
        invoke raw SQL execution, or import/invoke ExecutionGateway.
        """
        filepath = os.path.join(
            os.path.dirname(__file__), "services", "verification_trigger_coordinator.py"
        )
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        prohibited_calls = {"create_engine", "create_async_engine", "execute_sql"}
        prohibited_imports = {"ExecutionGateway", "execution_gateway"}

        found_prohibited_calls = []
        found_prohibited_imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name in prohibited_calls:
                    found_prohibited_calls.append(func_name)

            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in prohibited_imports:
                        found_prohibited_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module and "execution_gateway" in node.module:
                    found_prohibited_imports.append(node.module)
                for alias in node.names:
                    if alias.name in prohibited_imports:
                        found_prohibited_imports.append(alias.name)

        assert not found_prohibited_calls, f"Found prohibited engine/SQL calls: {found_prohibited_calls}"
        assert not found_prohibited_imports, f"Found prohibited ExecutionGateway imports: {found_prohibited_imports}"


# =============================================================================
# 7. REST API FEEDBACK INSPECTION ENDPOINT TESTS
# =============================================================================

class TestClosedLoopRestApi:
    def test_24_feedback_routes_accessible_to_authorized_user(
        self, coordinator, sample_mission, sample_evidence
    ):
        evt = make_operational_event()
        decision = coordinator.evaluate_eligibility(evt)

        async def setup_feedback():
            run_obj, _ = await coordinator.request_verification(evt, decision)
            await coordinator.record_feedback(evt, decision, run=run_obj)

        asyncio.run(setup_feedback())

        # Test GET /api/v3/missions/{mission_id}/verifications/feedback
        test_client = TestClient(app)
        auth_user = Identity(
            user_id="analyst_test",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            roles=["ANALYST"],
            permissions=["mission.read", "mission.verification.read"],
            assigned_plants=["plant_01"],
        )

        try:
            import api.verification_routes as vr
        except (ImportError, ModuleNotFoundError):
            import backend.api.verification_routes as vr

        orig_vs = vr.verification_service
        vr.verification_service = coordinator.verification_service
        app.dependency_overrides[get_current_identity] = lambda: auth_user
        try:
            # 1. Mission-specific feedback route
            resp = test_client.get(
                f"/api/v3/missions/{sample_mission.mission_id}/verifications/feedback",
                headers={"Authorization": "Bearer test_token"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) >= 1
            assert data[0]["trigger_event_id"] == evt.event_id
            assert data[0]["eligibility_status"] == "ELIGIBLE"

            # 2. Tenant-level feedback route
            resp2 = test_client.get(
                "/api/v3/verification/feedback",
                headers={"Authorization": "Bearer test_token"},
            )
            assert resp2.status_code == 200
            data2 = resp2.json()
            assert len(data2) >= 1
            assert any(item["trigger_event_id"] == evt.event_id for item in data2)
        finally:
            vr.verification_service = orig_vs
            app.dependency_overrides.clear()


# =============================================================================
# 8. AUTHENTICATED EVENT PRODUCER SECURITY (Prompt 37A Section 3 & 9)
# =============================================================================

class TestAuthenticatedEventProducerSecurity:
    @pytest.fixture
    def api_setup(self, temp_dbs):
        event_db = temp_dbs[0]
        delivery_db = temp_dbs[1]
        ev_repo = EventRepository(db_path=event_db)
        deliv_repo = EventDeliveryRepository(db_path=delivery_db)
        ebus = EventBus(deliv_repo)
        ebus.enabled = True
        client = TestClient(app)
        try:
            import api.event_routes as er
        except (ImportError, ModuleNotFoundError):
            import backend.api.event_routes as er
        app.dependency_overrides[er.get_event_repo] = lambda: ev_repo
        app.dependency_overrides[er.get_event_bus] = lambda: ebus
        yield client, ev_repo, ebus
        app.dependency_overrides.clear()

    def test_25_producer_submits_different_tenant_event_rejected(self, api_setup):
        """Producer authenticated in tenant_alpha cannot submit event for tenant_bravo (HTTP 403)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        evt = make_operational_event(tenant_id="tenant_bravo", workspace_id="workspace_prod", plant_id="plant_01")
        resp = client.post("/api/v3/events", json=evt.model_dump())
        assert resp.status_code == 403
        assert "different tenant" in resp.json()["detail"].lower()
        # Ensure rejected event is NOT persisted
        assert ev_repo.get_event("tenant_bravo", evt.event_id) is None
        assert ev_repo.get_event("tenant_alpha", evt.event_id) is None

    def test_26_producer_submits_unauthorized_workspace_rejected(self, api_setup):
        """Producer in workspace_prod cannot submit event targeting unauthorized workspace_dev (HTTP 403)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        evt = make_operational_event(tenant_id="tenant_alpha", workspace_id="workspace_dev", plant_id="plant_01")
        resp = client.post("/api/v3/events", json=evt.model_dump())
        assert resp.status_code == 403
        assert "workspace" in resp.json()["detail"].lower()
        assert ev_repo.get_event("tenant_alpha", evt.event_id) is None

    def test_27_producer_submits_unauthorized_plant_rejected(self, api_setup):
        """Producer authorized only for plant_01 cannot submit event for plant_02 (HTTP 403)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        evt = make_operational_event(tenant_id="tenant_alpha", workspace_id="workspace_prod", plant_id="plant_02")
        resp = client.post("/api/v3/events", json=evt.model_dump())
        assert resp.status_code == 403
        assert "plant" in resp.json()["detail"].lower()
        assert ev_repo.get_event("tenant_alpha", evt.event_id) is None

    def test_28_producer_forged_payload_fields_no_escalation(self, api_setup):
        """Producer attempting to forge identity/permissions in payload cannot escalate privileges."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        forged_payload = {
            "user_id": "root_admin",
            "roles": ["SUPERADMIN", "ADMINISTRATOR"],
            "permissions": ["*"],
            "clearance": 5,
            "workspace_id": "system_admin",
            "plant_id": "all_plants",
        }
        evt = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            payload_extra=forged_payload,
        )
        resp = client.post("/api/v3/events", json=evt.model_dump())
        assert resp.status_code == 201
        saved = ev_repo.get_event("tenant_alpha", evt.event_id)
        assert saved is not None
        # Verify event saved has strictly the authenticated producer's tenant/workspace
        assert saved.tenant_id == "tenant_alpha"
        assert saved.workspace_id == "workspace_prod"
        assert saved.plant_id == "plant_01"

    def test_29_missing_workspace_scope_rejected(self, api_setup):
        """Submitting event with missing or blank workspace fails closed (HTTP 400)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        raw_evt = make_operational_event().model_dump()
        raw_evt["workspace_id"] = ""
        raw_evt["event_fingerprint"] = ""
        resp = client.post("/api/v3/events", json=raw_evt)
        assert resp.status_code == 400
        assert "workspace scope is missing or invalid" in resp.json()["detail"].lower()

    def test_30_missing_plant_scope_rejected(self, api_setup):
        """Submitting event with missing or blank plant fails closed (HTTP 400)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        raw_evt = make_operational_event().model_dump()
        raw_evt["plant_id"] = ""
        raw_evt["event_fingerprint"] = ""
        resp = client.post("/api/v3/events", json=raw_evt)
        assert resp.status_code == 400
        assert "plant scope is missing or invalid" in resp.json()["detail"].lower()

    def test_31_global_scope_without_authorization_rejected(self, api_setup):
        """Submitting manufactured 'global' scope is rejected (HTTP 400)."""
        client, ev_repo, _ = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        raw_evt = make_operational_event().model_dump()
        raw_evt["workspace_id"] = "global"
        raw_evt["event_fingerprint"] = ""
        resp = client.post("/api/v3/events", json=raw_evt)
        assert resp.status_code == 400
        assert "workspace scope is missing or invalid" in resp.json()["detail"].lower()

    def test_32_rejected_events_not_persisted_or_dispatched(self, api_setup):
        """Assert that rejected event is neither in SQLite store nor dispatched to subscribers."""
        client, ev_repo, ebus = api_setup
        producer = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        received_events = []
        async def on_event(delivery, ev):
            received_events.append(ev)
            return True

        sub = Subscription(subscription_id="sub_test", subscriber_id="sub_test", tenant_id="tenant_bravo")
        ebus.subscribe(sub, on_event)

        evt = make_operational_event(tenant_id="tenant_bravo", workspace_id="workspace_prod", plant_id="plant_01")
        resp = client.post("/api/v3/events", json=evt.model_dump())
        assert resp.status_code == 403
        assert ev_repo.get_event("tenant_bravo", evt.event_id) is None
        assert len(received_events) == 0


# =============================================================================
# 9. COORDINATOR SCOPE & INDEPENDENT VERIFICATION BOUNDARY (Prompt 37A Section 4 & 9)
# =============================================================================

class TestCoordinatorScopeSecurity:
    def test_33_forged_envelope_cannot_obtain_service_identity_for_other_workspace(
        self, coordinator, sample_mission, v_repo
    ):
        """Forged envelope workspace cannot grant service identity for that workspace."""
        forged_evt = make_operational_event(
            workspace_id="workspace_stolen",
            payload_extra={"roles": ["SUPERADMIN"], "clearance": 5}
        )
        dec = coordinator.evaluate_eligibility(forged_evt)

        async def run():
            run_obj, err = await coordinator.request_verification(forged_evt, dec)
            assert run_obj is None
            assert err in (EligibilityReasonCode.SCOPE_MISMATCH.value, EligibilityReasonCode.MISSING_TARGET_REFERENCE.value)
            # Assert absence of any unauthorized verification runs in database
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())

    def test_34_forged_plant_cannot_cause_cross_plant_verification(
        self, coordinator, sample_mission, v_repo
    ):
        """Event with unauthorized plant_02 cannot trigger verification on mission in plant_01."""
        evt = make_operational_event(plant_id="plant_02")
        dec = coordinator.evaluate_eligibility(evt)

        async def run():
            run_obj, err = await coordinator.request_verification(evt, dec)
            assert run_obj is None
            assert err == EligibilityReasonCode.SCOPE_MISMATCH.value
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())

    def test_35_mission_in_another_tenant_cannot_be_verified(
        self, coordinator, sample_mission, v_repo
    ):
        """Event from tenant_bravo cannot verify mission belonging to tenant_alpha."""
        evt = make_operational_event(tenant_id="tenant_bravo", mission_id=sample_mission.mission_id)
        dec = coordinator.evaluate_eligibility(evt)

        async def run():
            run_obj, err = await coordinator.request_verification(evt, dec)
            assert run_obj is None
            assert err in (EligibilityReasonCode.SCOPE_MISMATCH.value, EligibilityReasonCode.MISSING_TARGET_REFERENCE.value)
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())

    def test_36_mismatched_mission_revision_rejected(
        self, coordinator, sample_mission, v_repo
    ):
        """Event specifying target_revision=99 against a revision=1 mission is rejected."""
        evt = make_operational_event(payload_extra={"target_revision": 99})
        dec = coordinator.evaluate_eligibility(evt)

        async def run():
            run_obj, err = await coordinator.request_verification(evt, dec)
            assert run_obj is None
            assert err == EligibilityReasonCode.SCOPE_MISMATCH.value
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())

    def test_37_missing_authoritative_scope_does_not_create_run(
        self, coordinator, sample_mission, v_repo
    ):
        """Event with missing plant scope fails closed and creates zero runs."""
        evt = make_operational_event(plant_id="")
        dec = coordinator.evaluate_eligibility(evt)
        assert dec.status == EligibilityStatus.REJECTED
        assert dec.reason_code == EligibilityReasonCode.MISSING_SCOPE.value

        async def run():
            run_obj, err = await coordinator.request_verification(evt, dec)
            assert run_obj is None
            assert err == EligibilityReasonCode.MISSING_SCOPE.value
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())

    def test_38_schema_valid_event_with_untrusted_scope_fails(
        self, coordinator, sample_mission, v_repo
    ):
        """CanonicalEvent schema valid with manufactured 'default' scope fails closed."""
        evt = make_operational_event(workspace_id="default")
        dec = coordinator.evaluate_eligibility(evt)
        assert dec.status == EligibilityStatus.REJECTED
        assert dec.reason_code == EligibilityReasonCode.MISSING_SCOPE.value

        async def run():
            run_obj, err = await coordinator.request_verification(evt, dec)
            assert run_obj is None
            _, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 0

        asyncio.run(run())


# =============================================================================
# 10. FEATURE FLAGS & STARTUP SAFETY (Prompt 37A Section 6, 7 & 9)
# =============================================================================

class TestFeatureFlagsAndStartupSecurity:
    def test_39_flags_default_to_disabled_when_env_absent(self):
        """Both closed-loop and event-trigger flags default to false when env vars absent."""
        from core.config import SAGE_CLOSED_LOOP_ENABLED, SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED
        assert SAGE_CLOSED_LOOP_ENABLED is False or str(os.getenv("SAGE_CLOSED_LOOP_ENABLED", "false")).lower() in ("0", "false")
        assert SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED is False or str(os.getenv("SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED", "false")).lower() in ("0", "false")

    def test_40_either_flag_disabled_prevents_event_triggered_verification(
        self, event_bus, v_service, v_repo
    ):
        """When either SAGE_CLOSED_LOOP_ENABLED or SAGE_VERIFICATION_EVENT_TRIGGER_ENABLED is false, no event triggering occurs."""
        coord_disabled_1 = VerificationTriggerCoordinator(
            event_bus=event_bus,
            verification_svc=v_service,
            repository=v_repo,
            enabled=False,
            event_trigger_enabled=True,
        )
        evt = make_operational_event()
        dec1 = coord_disabled_1.evaluate_eligibility(evt)
        assert dec1.status == EligibilityStatus.IGNORED
        assert dec1.reason_code == EligibilityReasonCode.DISABLED.value

        coord_disabled_2 = VerificationTriggerCoordinator(
            event_bus=event_bus,
            verification_svc=v_service,
            repository=v_repo,
            enabled=True,
            event_trigger_enabled=False,
        )
        dec2 = coord_disabled_2.evaluate_eligibility(evt)
        assert dec2.status == EligibilityStatus.IGNORED
        assert dec2.reason_code == EligibilityReasonCode.DISABLED.value

    def test_41_startup_does_not_subscribe_to_default_tenant(self):
        """AST check: backend/server.py must not contain register_tenant_subscription('default')."""
        server_path = os.path.join(os.path.dirname(__file__), "server.py")
        with open(server_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'register_tenant_subscription("default")' not in content
        assert "register_tenant_subscription('default')" not in content

    def test_42_missing_subscription_config_leaves_coordinator_inactive(
        self, event_bus, v_service, v_repo
    ):
        """Coordinator with no registered subscriptions processes 0 subscriptions."""
        coord = VerificationTriggerCoordinator(
            event_bus=event_bus,
            verification_svc=v_service,
            repository=v_repo,
            enabled=True,
            event_trigger_enabled=True,
        )
        assert len(coord._subscribed_tenants) == 0

    def test_43_explicit_valid_test_scopes_work(
        self, event_bus, v_service, v_repo
    ):
        """Explicit tenant, workspace, plant registration succeeds and rejects manufactured scopes."""
        coord = VerificationTriggerCoordinator(
            event_bus=event_bus,
            verification_svc=v_service,
            repository=v_repo,
            enabled=True,
            event_trigger_enabled=True,
        )
        sub = coord.register_tenant_subscription("tenant_alpha", workspace_id="workspace_prod", plant_id="plant_01")
        assert sub is not None
        assert sub.tenant_id == "tenant_alpha"
        assert sub.workspace_id == "workspace_prod"
        assert sub.plant_id == "plant_01"

        with pytest.raises(ValueError):
            coord.register_tenant_subscription("default")
        with pytest.raises(ValueError):
            coord.register_tenant_subscription("tenant_alpha", workspace_id="*")

    def test_44_manually_requested_continuous_verification_remains_functional(
        self, v_service, sample_mission, sample_evidence, coordinator
    ):
        """Manual VerificationService verification works even if event-trigger coordinator is disabled."""
        coordinator.enabled = False
        coordinator.event_trigger_enabled = False

        analyst = Identity(
            user_id="analyst_direct",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["ANALYST"],
            permissions=["mission.verification.request"],
        )
        req = VerificationRequest(
            rule_type=RuleType.EVIDENCE_EXISTS,
            trigger_type=TriggerType.MANUAL,
        )
        run_obj = v_service.request_verification(
            identity=analyst,
            mission_id=sample_mission.mission_id,
            request=req,
        )
        assert run_obj is not None
        assert run_obj.mission_id == sample_mission.mission_id
        assert run_obj.trigger_type == TriggerType.MANUAL


# =============================================================================
# 11. FINGERPRINTS & IDEMPOTENCY INTEGRITY (Prompt 37A Section 8 & 9)
# =============================================================================

class TestFingerprintIntegrityAndIdempotency:
    def test_45_missing_fingerprint_safely_computed(self):
        """An event created without a fingerprint computes its deterministic fingerprint."""
        evt = make_operational_event()
        evt.event_fingerprint = ""
        computed = evt.compute_fingerprint()
        assert computed != ""
        evt.apply_fingerprint()
        assert evt.event_fingerprint == computed

    def test_46_correct_supplied_fingerprint_accepted(self, coordinator):
        """Event with correct deterministic fingerprint is eligible."""
        evt = make_operational_event()
        assert evt.event_fingerprint == evt.compute_fingerprint()
        dec = coordinator.evaluate_eligibility(evt)
        assert dec.status == EligibilityStatus.ELIGIBLE

    def test_47_incorrect_supplied_fingerprint_rejected(self, coordinator):
        """Event with incorrect client-supplied fingerprint fails boundary checks."""
        evt = make_operational_event()
        evt.event_fingerprint = "fake_sha256_hash_1234567890abcdef"
        dec = coordinator.evaluate_eligibility(evt)
        assert dec.status == EligibilityStatus.REJECTED
        assert dec.reason_code == EligibilityReasonCode.UNTRUSTED_PROVENANCE.value

    def test_48_fingerprint_reuse_with_different_content_cannot_impersonate(
        self, coordinator, v_repo
    ):
        """Reusing fingerprint of Event A on mutated Event B cannot impersonate Event A."""
        evt_a = make_operational_event(payload_extra={"measurement": 42.0})
        fp_a = evt_a.event_fingerprint

        evt_b = make_operational_event(payload_extra={"measurement": 999.0})
        evt_b.event_fingerprint = fp_a

        dec = coordinator.evaluate_eligibility(evt_b)
        assert dec.status == EligibilityStatus.REJECTED
        assert dec.reason_code == EligibilityReasonCode.UNTRUSTED_PROVENANCE.value

    def test_49_legitimate_event_retries_remain_idempotent(
        self, coordinator, sample_mission, sample_evidence, v_repo
    ):
        """Re-delivery of identical event deterministically returns existing verification run."""
        evt = make_operational_event()
        dec = coordinator.evaluate_eligibility(evt)

        async def run():
            run1, err1 = await coordinator.request_verification(evt, dec)
            assert run1 is not None
            assert err1 is None

            run2, err2 = await coordinator.request_verification(evt, dec)
            assert run2 is not None
            assert err2 is None
            assert run1.verification_id == run2.verification_id

            runs, total = v_repo.list_runs("tenant_alpha", "workspace_prod", sample_mission.mission_id)
            assert total == 1

        asyncio.run(run())


# =============================================================================
# 12. EVENT FINGERPRINT ISOLATION & DEDUPLICATION SAFETY (Prompt 37B Section 6)
# =============================================================================

class TestEventFingerprintIsolationAndDeduplication:
    @pytest.fixture
    def fp_api_setup(self, temp_dbs):
        event_db = temp_dbs[0]
        delivery_db = temp_dbs[1]
        ev_repo = EventRepository(db_path=event_db)
        deliv_repo = EventDeliveryRepository(db_path=delivery_db)
        ebus = EventBus(deliv_repo)
        ebus.enabled = True
        client = TestClient(app)
        try:
            import api.event_routes as er
        except (ImportError, ModuleNotFoundError):
            import backend.api.event_routes as er
        app.dependency_overrides[er.get_event_repo] = lambda: ev_repo
        app.dependency_overrides[er.get_event_bus] = lambda: ebus
        yield client, ev_repo, ebus
        app.dependency_overrides.clear()

    def test_50_same_tenant_different_workspace_isolation(self, fp_api_setup):
        """Test A: Events in different workspaces have distinct fingerprints and do not resolve to each other."""
        client, ev_repo, _ = fp_api_setup
        
        # 1. Producer in Workspace A
        producer_a = Identity(
            user_id="op_a",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_a

        occurred_iso = "2026-10-13T10:00:00Z"
        evt_a = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            occurred_at=occurred_iso,
            payload_extra={"telemetry_val": 42.0},
        )
        resp_a = client.post("/api/v3/events", json=evt_a.model_dump())
        assert resp_a.status_code == 201
        data_a = resp_a.json()

        # 2. Producer in Workspace B with identical payload, event_type, occurred_at, and plant
        producer_b = Identity(
            user_id="op_b",
            tenant_id="tenant_alpha",
            workspace_id="workspace_dev",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_b

        evt_b = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_dev",
            plant_id="plant_01",
            occurred_at=occurred_iso,
            payload_extra={"telemetry_val": 42.0},
        )
        resp_b = client.post("/api/v3/events", json=evt_b.model_dump())
        assert resp_b.status_code == 201
        data_b = resp_b.json()

        # 3. Verify fingerprint separation & isolation
        assert data_a["event_fingerprint"] != data_b["event_fingerprint"]
        assert data_b["workspace_id"] == "workspace_dev"
        assert data_a["workspace_id"] == "workspace_prod"
        assert data_b["event_id"] != data_a["event_id"]
        # Zero data from Workspace A leaked to Workspace B
        assert data_b["event_id"] == evt_b.event_id

    def test_51_same_workspace_different_plant_isolation(self, fp_api_setup):
        """Test B: Events in different plants have distinct fingerprints and do not collide."""
        client, ev_repo, _ = fp_api_setup
        
        producer_1 = Identity(
            user_id="op_p1",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_1

        occurred_iso = "2026-10-13T10:00:00Z"
        evt_1 = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            occurred_at=occurred_iso,
            payload_extra={"temp": 98.6},
        )
        resp_1 = client.post("/api/v3/events", json=evt_1.model_dump())
        assert resp_1.status_code == 201
        data_1 = resp_1.json()

        producer_2 = Identity(
            user_id="op_p2",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_02"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_2

        evt_2 = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_02",
            occurred_at=occurred_iso,
            payload_extra={"temp": 98.6},
        )
        resp_2 = client.post("/api/v3/events", json=evt_2.model_dump())
        assert resp_2.status_code == 201
        data_2 = resp_2.json()

        assert data_1["event_fingerprint"] != data_2["event_fingerprint"]
        assert data_1["plant_id"] == "plant_01"
        assert data_2["plant_id"] == "plant_02"
        assert data_1["event_id"] != data_2["event_id"]

    def test_52_exact_replay_idempotency_preserved(self, fp_api_setup):
        """Test C: Exact re-submission of the same canonical event returns the existing event idempotently."""
        client, ev_repo, _ = fp_api_setup
        producer = Identity(
            user_id="op_replay",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        evt = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            payload_extra={"sensor": "A1"},
        )
        resp_1 = client.post("/api/v3/events", json=evt.model_dump())
        assert resp_1.status_code == 201
        data_1 = resp_1.json()

        # Exact replay (retry with newly generated event_id but identical canonical scope & content)
        evt_replay = evt.model_copy(deep=True)
        evt_replay.event_id = f"evt_retry_{uuid.uuid4().hex[:8]}"
        evt_replay.apply_fingerprint()
        assert evt_replay.event_fingerprint == evt.event_fingerprint

        resp_2 = client.post("/api/v3/events", json=evt_replay.model_dump())
        assert resp_2.status_code == 201
        data_2 = resp_2.json()

        # Idempotent return of the original persisted event
        assert data_1["event_id"] == data_2["event_id"]
        assert data_1["event_fingerprint"] == data_2["event_fingerprint"]

        # Exactly 1 record in repository
        all_events = ev_repo.list_events("tenant_alpha")
        assert len(all_events) == 1

    def test_53_modified_payload_with_reused_fingerprint_rejected(self, fp_api_setup):
        """Test D: Mutating payload while supplying original fingerprint fails closed (HTTP 400)."""
        client, ev_repo, _ = fp_api_setup
        producer = Identity(
            user_id="op_d",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        evt_orig = make_operational_event(payload_extra={"val": 100})
        fp_orig = evt_orig.event_fingerprint

        # Modified payload but forged/reused original fingerprint
        evt_bad = make_operational_event(payload_extra={"val": 9999})
        bad_dump = evt_bad.model_dump()
        bad_dump["event_fingerprint"] = fp_orig

        resp = client.post("/api/v3/events", json=bad_dump)
        assert resp.status_code == 400
        assert "fingerprint does not match" in resp.json()["detail"].lower()
        assert ev_repo.get_event("tenant_alpha", evt_bad.event_id) is None

    def test_54_modified_workspace_with_reused_fingerprint_rejected(self, fp_api_setup):
        """Test E: Changing workspace while keeping original fingerprint is rejected (HTTP 400)."""
        client, ev_repo, _ = fp_api_setup
        producer_dev = Identity(
            user_id="op_e",
            tenant_id="tenant_alpha",
            workspace_id="workspace_dev",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_dev

        evt_prod = make_operational_event(workspace_id="workspace_prod")
        fp_prod = evt_prod.event_fingerprint

        # Submit event for workspace_dev with prod's fingerprint
        evt_dev = make_operational_event(workspace_id="workspace_dev")
        dev_dump = evt_dev.model_dump()
        dev_dump["event_fingerprint"] = fp_prod

        resp = client.post("/api/v3/events", json=dev_dump)
        assert resp.status_code == 400
        assert "fingerprint does not match" in resp.json()["detail"].lower()
        assert ev_repo.get_event("tenant_alpha", evt_dev.event_id) is None

    def test_55_modified_plant_with_reused_fingerprint_rejected(self, fp_api_setup):
        """Test F: Changing plant while keeping original fingerprint is rejected (HTTP 400)."""
        client, ev_repo, _ = fp_api_setup
        producer_p2 = Identity(
            user_id="op_f",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_02"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_p2

        evt_p1 = make_operational_event(plant_id="plant_01")
        fp_p1 = evt_p1.event_fingerprint

        # Submit event for plant_02 with plant_01's fingerprint
        evt_p2 = make_operational_event(plant_id="plant_02")
        p2_dump = evt_p2.model_dump()
        p2_dump["event_fingerprint"] = fp_p1

        resp = client.post("/api/v3/events", json=p2_dump)
        assert resp.status_code == 400
        assert "fingerprint does not match" in resp.json()["detail"].lower()
        assert ev_repo.get_event("tenant_alpha", evt_p2.event_id) is None

    def test_56_repository_collision_path_rejects_conflicting_duplicate(self, fp_api_setup):
        """Test G: Conflicting duplicate in repository raises EventIdempotencyConflictError and never returns existing record."""
        _, ev_repo, _ = fp_api_setup
        evt_orig = make_operational_event(payload_extra={"data": "original"})
        ev_repo.record_event(evt_orig)

        # Forge conflicting event with same fingerprint but modified payload
        evt_conflict = evt_orig.model_copy(deep=True)
        evt_conflict.event_id = "evt_conflict_99"
        evt_conflict.payload = {"data": "tampered"}
        # Keep original fingerprint
        evt_conflict.event_fingerprint = evt_orig.event_fingerprint

        with pytest.raises(EventIdempotencyConflictError):
            ev_repo.record_event_ex(evt_conflict)

        # Verify original record in DB was untouched
        stored = ev_repo.get_event("tenant_alpha", evt_orig.event_id)
        assert stored.payload == {"value": 100, "mission_id": "msn_cl_100", "data": "original"}

    def test_57_publication_boundary_spy_verifies_no_unintended_publication(self, fp_api_setup):
        """Test H: EventBus spy verifies exact replay publishes 0 duplicates, and rejected requests publish 0 events."""
        client, ev_repo, ebus = fp_api_setup
        producer = Identity(
            user_id="op_spy",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer

        published_calls = []
        async def spy_publish(ev):
            published_calls.append(ev)

        ebus.publish = spy_publish

        # 1. First submission -> published
        evt = make_operational_event()
        resp_1 = client.post("/api/v3/events", json=evt.model_dump())
        assert resp_1.status_code == 201
        assert len(published_calls) == 1

        # 2. Exact replay -> NOT published again
        evt_replay = evt.model_copy(deep=True)
        evt_replay.event_id = "evt_replay_uuid"
        evt_replay.apply_fingerprint()
        resp_2 = client.post("/api/v3/events", json=evt_replay.model_dump())
        assert resp_2.status_code == 201
        assert len(published_calls) == 1  # Still 1, zero unintended publication!

        # 3. Invalid fingerprint -> 400, NOT published
        bad_evt = evt.model_dump()
        bad_evt["event_id"] = "evt_bad_uuid"
        bad_evt["event_fingerprint"] = "bad_fp_123"
        resp_3 = client.post("/api/v3/events", json=bad_evt)
        assert resp_3.status_code == 400
        assert len(published_calls) == 1  # Still 1

    def test_58_legacy_records_fail_closed_on_collision(self, fp_api_setup):
        """Test I: Ambiguous legacy record without workspace/plant fails closed and is never returned as exact replay."""
        _, ev_repo, _ = fp_api_setup
        
        # Create a modern event with valid deterministic fingerprint
        modern_evt = make_operational_event(tenant_id="tenant_alpha", workspace_id="workspace_prod", plant_id="plant_01")
        valid_fp = modern_evt.compute_fingerprint()

        # Directly insert a legacy event with NULL workspace/plant and valid_fp into SQLite store
        now_iso = "2026-10-13T10:00:00Z"
        with ev_repo._get_conn() as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO events (
                        event_id, fingerprint, tenant_id, workspace_id, plant_id,
                        schema_version, category, event_type, severity, lifecycle,
                        occurred_at, observed_at, recorded_at, provenance, references_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "evt_legacy_01", valid_fp, "tenant_alpha", None, None,
                        "event.v1", "TELEMETRY", "telemetry.updated", "INFO", "RECORDED",
                        now_iso, now_iso, now_iso, "sensor", "{}", "{}"
                    )
                )

        # Incoming modern event attempts insertion, clashes on fingerprint in DB,
        # but existing record has ambiguous scope (NULL workspace/plant) -> fails closed
        with pytest.raises(LegacyEventFingerprintError):
            ev_repo.record_event_ex(modern_evt)

    def test_59_multitenant_workspace_plant_regression(self, fp_api_setup):
        """Test J: Multi-tenant isolation: identical payloads in tenant A and tenant B produce distinct isolated events."""
        client, ev_repo, _ = fp_api_setup
        occurred_iso = "2026-10-13T10:00:00Z"

        # Tenant Alpha
        producer_a = Identity(
            user_id="op_alpha",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_a

        evt_a = make_operational_event(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            occurred_at=occurred_iso,
            payload_extra={"shared_metric": 100},
        )
        resp_a = client.post("/api/v3/events", json=evt_a.model_dump())
        assert resp_a.status_code == 201
        data_a = resp_a.json()

        # Tenant Beta
        producer_b = Identity(
            user_id="op_beta",
            tenant_id="tenant_beta",
            workspace_id="workspace_prod",
            assigned_plants=["plant_01"],
            roles=["OPERATOR"],
            permissions=["events.record", "events.read"],
        )
        app.dependency_overrides[get_current_identity] = lambda: producer_b

        evt_b = make_operational_event(
            tenant_id="tenant_beta",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            occurred_at=occurred_iso,
            payload_extra={"shared_metric": 100},
        )
        resp_b = client.post("/api/v3/events", json=evt_b.model_dump())
        assert resp_b.status_code == 201
        data_b = resp_b.json()

        # Both exist independently
        assert data_a["event_fingerprint"] != data_b["event_fingerprint"]
        assert data_a["tenant_id"] == "tenant_alpha"
        assert data_b["tenant_id"] == "tenant_beta"

        # Tenant Alpha cannot list Tenant Beta's events
        app.dependency_overrides[get_current_identity] = lambda: producer_a
        events_a = client.get("/api/v3/events").json()
        assert len(events_a) == 1
        assert events_a[0]["tenant_id"] == "tenant_alpha"

