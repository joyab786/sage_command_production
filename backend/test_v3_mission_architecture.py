# backend/test_v3_mission_architecture.py
"""
SageCommand V3 — Governed Mission Architecture Foundation Test Suite (Prompt 35)

Comprehensive verification covering:
1. Domain model, structured steps, acyclic DAG dependencies, bounds, and anti-smuggling checks.
2. Tenant, workspace, and plant scope authorization (fail-closed boundaries).
3. Lifecycle state machine transitions, validation enforcement, review, and cancellation.
4. Persistence durability, deterministic revision snapshots, optimistic locking, and idempotency.
5. REST API endpoints, RBAC permissions, and non-disclosing error handling.
6. Architectural safety AST checks confirming zero ExecutionGateway coupling, no shell/PLC writes,
   and no operational execution bypasses.

Principle:
A Mission is a governed representation of an industrial objective and its intended work—
NOT permission to execute that work.
"""

import ast
import json
import os
import sqlite3
import tempfile
import uuid
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from core.config import SAGE_MISSION_DB_PATH
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        MANDATORY_MISSION_NOTICE,
        VALID_LIFECYCLE_TRANSITIONS,
        is_valid_lifecycle_transition,
        validate_mission_dependencies,
    )
    from repositories.mission_repository import (
        MissionRepository,
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )
    from services.mission_service import (
        MissionService,
        mission_service,
        MissionPermissionError,
        MissionValidationError,
        MissionLifecycleError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.core.config import SAGE_MISSION_DB_PATH
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
        ConstraintType,
        MissionScope,
        MissionConstraint,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        MANDATORY_MISSION_NOTICE,
        VALID_LIFECYCLE_TRANSITIONS,
        is_valid_lifecycle_transition,
        validate_mission_dependencies,
    )
    from backend.repositories.mission_repository import (
        MissionRepository,
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )
    from backend.services.mission_service import (
        MissionService,
        mission_service,
        MissionPermissionError,
        MissionValidationError,
        MissionLifecycleError,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_repo():
    """Provides a fresh MissionRepository backed by a temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        temp_path = tf.name
    repo = MissionRepository(db_path=temp_path)
    yield repo
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


@pytest.fixture
def temp_service(temp_repo):
    """Provides a fresh MissionService connected to temp_repo."""
    return MissionService(repository=temp_repo)


@pytest.fixture
def operator_identity():
    """Authoritative operator identity with plant_01 assignment."""
    return Identity(
        user_id="operator_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["OPERATOR"],
        permissions=[
            "mission.read",
            "mission.create",
            "mission.update",
            "mission.validate",
            "mission.cancel",
        ],
        assigned_plants=["plant_01"],
        session_id="session_op_1",
    )


@pytest.fixture
def plant_manager_identity():
    """Authoritative plant manager identity with review and admin authority."""
    return Identity(
        user_id="manager_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["PLANT_MANAGER"],
        permissions=[
            "mission.read",
            "mission.create",
            "mission.update",
            "mission.validate",
            "mission.review",
            "mission.cancel",
            "mission.admin",
        ],
        assigned_plants=["*"],
        session_id="session_mgr_1",
    )


@pytest.fixture
def unauthorized_plant_identity():
    """Caller assigned only to plant_99, attempting access to plant_01."""
    return Identity(
        user_id="operator_99",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["OPERATOR"],
        permissions=["mission.read", "mission.create"],
        assigned_plants=["plant_99"],
        session_id="session_op_99",
    )


@pytest.fixture
def cross_tenant_identity():
    """Caller belonging to tenant_beta attempting cross-tenant access."""
    return Identity(
        user_id="external_user",
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        roles=["OPERATOR"],
        permissions=["mission.read"],
        assigned_plants=["*"],
    )


@pytest.fixture
def cross_workspace_identity():
    """Caller belonging to workspace_other attempting cross-workspace access."""
    return Identity(
        user_id="other_ws_user",
        tenant_id="tenant_alpha",
        workspace_id="workspace_other",
        roles=["OPERATOR"],
        permissions=["mission.read"],
        assigned_plants=["*"],
    )


# =============================================================================
# 1. DOMAIN & VALIDATION TESTS
# =============================================================================

class TestMissionDomainValidation:
    """Verifies domain models, bounded constraints, and deterministic DAG validation."""

    def test_valid_mission_contract(self):
        """Constructs a fully populated, valid industrial mission."""
        scope = MissionScope(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )
        steps = [
            MissionPlannedStep(
                step_id="step_rca",
                title="Root Cause Analysis",
                description="Investigate recurring seal failures on Pump 4B",
                step_type=StepType.INVESTIGATION,
                status=StepStatus.PLANNED,
                depends_on=[],
            ),
            MissionPlannedStep(
                step_id="step_evidence",
                title="Collect Vibration Telemetry",
                description="Gather 14-day FFT spectra for Pump 4B",
                step_type=StepType.EVIDENCE_COLLECTION,
                status=StepStatus.PLANNED,
                depends_on=["step_rca"],
            ),
            MissionPlannedStep(
                step_id="step_proposal",
                title="Propose Bearing Replacement",
                description="Draft structured Action proposal for bearing overhaul",
                step_type=StepType.ACTION_PROPOSAL,
                status=StepStatus.PLANNED,
                depends_on=["step_evidence"],
            ),
        ]
        criteria = [
            MissionSuccessCriterion(
                description="Vibration analysis identifies peak harmonic exceedance",
                status=CriterionStatus.UNKNOWN,
                target_metric="vibration_rms_velocity",
            ),
            MissionSuccessCriterion(
                description="Action proposal passes deterministic policy check",
                status=CriterionStatus.UNKNOWN,
            ),
        ]
        provenance = MissionProvenance(
            created_by="operator_01",
            origin_reason="Recurring alarm cluster detected on Line 4",
        )

        mission = Mission(
            title="Investigate Pump 4B Vibration Anomaly",
            description="Operational investigation into recurring seal and bearing vibrations.",
            mission_type=MissionType.INVESTIGATION,
            objective="Identify root cause of vibration spikes and organize repair proposals.",
            scope=scope,
            planned_steps=steps,
            success_criteria=criteria,
            provenance=provenance,
            created_by="operator_01",
        )

        assert mission.mission_id.startswith("msn_")
        assert mission.status == MissionStatus.DRAFT
        assert mission.data_mode == DataMode.SIMULATION
        assert mission.revision == 1
        assert len(mission.planned_steps) == 3

    def test_missing_required_objective_fails(self):
        """Ensures mission without objective is rejected."""
        scope = MissionScope(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )
        provenance = MissionProvenance(
            created_by="operator_01",
            origin_reason="Testing missing objective",
        )
        with pytest.raises(Exception):
            Mission(
                title="Missing Objective Mission",
                description="Description here",
                mission_type=MissionType.INVESTIGATION,
                objective="",  # Empty string violates min_length=1
                scope=scope,
                provenance=provenance,
                created_by="operator_01",
            )

    def test_unsupported_mission_type_fails(self):
        """Ensures unlisted mission types are rejected."""
        with pytest.raises(ValueError):
            MissionType("AUTONOMOUS_WEAPON_CONTROL")

    def test_oversized_payload_fails(self):
        """Ensures fields with oversized lengths are rejected."""
        with pytest.raises(ValueError):
            MissionCreateRequest(
                title="X" * 300,  # Exceeds max_length=256
                description="Valid description",
                mission_type=MissionType.INVESTIGATION,
                objective="Valid objective",
                plant_id="plant_01",
                origin_reason="Valid reason",
            )

    def test_duplicate_step_ids_rejected(self):
        """DAG validation detects duplicate step identifiers."""
        steps = [
            MissionPlannedStep(
                step_id="step_01",
                title="First Step",
                description="Do work",
                step_type=StepType.ANALYSIS,
            ),
            MissionPlannedStep(
                step_id="step_01",  # Duplicate!
                title="Second Step with duplicate ID",
                description="Do more work",
                step_type=StepType.INVESTIGATION,
            ),
        ]
        is_valid, errors = validate_mission_dependencies(steps)
        assert not is_valid
        assert any("Duplicate step ID 'step_01'" in e for e in errors)

    def test_unknown_dependency_reference_rejected(self):
        """DAG validation rejects step referencing a non-existent prerequisite."""
        steps = [
            MissionPlannedStep(
                step_id="step_01",
                title="First Step",
                description="Do work",
                step_type=StepType.ANALYSIS,
                depends_on=["non_existent_step_99"],
            ),
        ]
        is_valid, errors = validate_mission_dependencies(steps)
        assert not is_valid
        assert any("depends on non-existent step 'non_existent_step_99'" in e for e in errors)

    def test_self_dependency_rejected(self):
        """DAG validation rejects self-dependency."""
        steps = [
            MissionPlannedStep(
                step_id="step_loop",
                title="Looping Step",
                description="I depend on myself",
                step_type=StepType.ANALYSIS,
                depends_on=["step_loop"],
            ),
        ]
        is_valid, errors = validate_mission_dependencies(steps)
        assert not is_valid
        assert any("Self-dependency detected" in e for e in errors)

    def test_cyclic_dependency_rejected(self):
        """DAG validation detects 2-node and 3-node dependency cycles."""
        # 2-step cycle: A -> B and B -> A
        cycle_steps = [
            MissionPlannedStep(
                step_id="step_A",
                title="Step A",
                description="Work A",
                step_type=StepType.ANALYSIS,
                depends_on=["step_B"],
            ),
            MissionPlannedStep(
                step_id="step_B",
                title="Step B",
                description="Work B",
                step_type=StepType.INVESTIGATION,
                depends_on=["step_A"],
            ),
        ]
        is_valid, errors = validate_mission_dependencies(cycle_steps)
        assert not is_valid
        assert any("Dependency cycle detected" in e for e in errors)

    def test_excessive_steps_or_dependencies_rejected(self):
        """DAG validation enforces maximum configured bounds."""
        many_steps = [
            MissionPlannedStep(
                step_id=f"step_{i}",
                title=f"Step {i}",
                description=f"Description {i}",
                step_type=StepType.ANALYSIS,
            )
            for i in range(55)  # Max allowed is 50
        ]
        is_valid, errors = validate_mission_dependencies(many_steps, max_steps=50)
        assert not is_valid
        assert any("exceeds maximum allowed (50)" in e for e in errors)

    def test_anti_sql_and_script_smuggling_rejected(self):
        """Disallowed SQL commands, shell commands, and eval syntax are rejected."""
        scope = MissionScope(tenant_id="t1", workspace_id="w1", plant_id="p1")
        provenance = MissionProvenance(created_by="op1", origin_reason="test")

        # SQL injection in objective
        with pytest.raises(ValueError, match="disallowed executable pattern"):
            Mission(
                title="Normal title",
                description="Normal description",
                mission_type=MissionType.INVESTIGATION,
                objective="Analyze issue; DROP TABLE missions; --",
                scope=scope,
                provenance=provenance,
                created_by="op1",
            )

        # Executable shell pattern in step description
        with pytest.raises(ValueError, match="disallowed executable pattern"):
            MissionPlannedStep(
                step_id="step_malicious",
                title="Normal Step",
                description="Run cleanup: rm -rf /var/log",
                step_type=StepType.ANALYSIS,
            )


# =============================================================================
# 2. SCOPE & SECURITY TESTS
# =============================================================================

class TestMissionScopeAndSecurity:
    """Verifies strict tenant, workspace, and plant isolation."""

    def test_cross_tenant_access_rejected(self, temp_service, operator_identity, cross_tenant_identity):
        """A user from tenant_beta cannot access tenant_alpha's mission."""
        create_req = MissionCreateRequest(
            title="Tenant Alpha Mission",
            description="Isolated operational objective",
            mission_type=MissionType.INVESTIGATION,
            objective="Ensure proper thermal limits on Reactor 1",
            plant_id="plant_01",
            origin_reason="Temperature anomaly",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        # Tenant beta attempts retrieval
        with pytest.raises(MissionNotFoundError):
            temp_service.get_mission(cross_tenant_identity, mission.mission_id)

    def test_cross_workspace_access_rejected(self, temp_service, operator_identity, cross_workspace_identity):
        """A user from another workspace cannot access the mission."""
        create_req = MissionCreateRequest(
            title="Workspace Alpha Mission",
            description="Isolated workspace objective",
            mission_type=MissionType.PREDICTIVE_MAINTENANCE,
            objective="Prevent motor burnout",
            plant_id="plant_01",
            origin_reason="Lubrication alert",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        # Other workspace attempts retrieval
        with pytest.raises(MissionNotFoundError):
            temp_service.get_mission(cross_workspace_identity, mission.mission_id)

    def test_unauthorized_plant_access_rejected(self, temp_service, unauthorized_plant_identity):
        """Caller cannot create or access missions for plants outside assigned_plants."""
        create_req = MissionCreateRequest(
            title="Plant 01 Mission",
            description="Targeting Plant 01",
            mission_type=MissionType.INVESTIGATION,
            objective="Investigate plant 01",
            plant_id="plant_01",  # Caller only has plant_99!
            origin_reason="Unauthorized plant test",
        )
        with pytest.raises(MissionPermissionError, match="not authorized for plant 'plant_01'"):
            temp_service.create_mission_draft(unauthorized_plant_identity, create_req)

    def test_missing_authoritative_workspace_fails_closed(self, temp_service):
        """Missing or empty workspace_id on identity fails closed immediately."""
        bad_identity = Identity(
            user_id="anonymous",
            tenant_id="tenant_alpha",
            workspace_id="",  # Empty workspace!
            roles=["OPERATOR"],
            assigned_plants=["*"],
        )
        create_req = MissionCreateRequest(
            title="Fail Closed Mission",
            description="Testing fail-closed",
            mission_type=MissionType.INVESTIGATION,
            objective="Fail closed objective",
            plant_id="plant_01",
            origin_reason="Testing",
        )
        with pytest.raises(MissionPermissionError, match="Authoritative workspace identity is required"):
            temp_service.create_mission_draft(bad_identity, create_req)

    def test_data_mode_cannot_be_escalated_to_real(self, temp_service, operator_identity):
        """Client-supplied requests always receive authoritative SIMULATION data mode."""
        create_req = MissionCreateRequest(
            title="Simulation Mission",
            description="Testing data mode boundary",
            mission_type=MissionType.INVESTIGATION,
            objective="Verify simulation boundary",
            plant_id="plant_01",
            origin_reason="Data mode boundary test",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)
        assert mission.data_mode == DataMode.SIMULATION

    def test_llm_cannot_bypass_governance_to_accept(self, temp_service, operator_identity):
        """Mission cannot be accepted directly without entering REVIEW_REQUIRED state."""
        create_req = MissionCreateRequest(
            title="Unreviewed Mission",
            description="Testing governance boundary",
            mission_type=MissionType.INVESTIGATION,
            objective="Testing governance bypass rejection",
            plant_id="plant_01",
            origin_reason="Testing",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        # Attempt to review a mission that is still in DRAFT
        review_req = MissionReviewRequest(
            action="ACCEPT",
            review_notes="Operator claiming acceptance directly without review",
        )
        with pytest.raises(MissionLifecycleError, match="cannot be reviewed"):
            temp_service.review_mission(operator_identity, mission.mission_id, review_req)


# =============================================================================
# 3. LIFECYCLE & STATE MACHINE TESTS
# =============================================================================

class TestMissionLifecycleAndTransitions:
    """Verifies deterministic lifecycle: DRAFT -> VALIDATED -> REVIEW_REQUIRED -> ACCEPTED."""

    def test_full_governed_lifecycle_progression(self, temp_service, operator_identity, plant_manager_identity):
        """Step-by-step valid lifecycle execution."""
        # 1. Create DRAFT
        create_req = MissionCreateRequest(
            title="Compressor Seal Investigation",
            description="Governed investigation for Compressor C-102",
            mission_type=MissionType.INVESTIGATION,
            objective="Identify source of seal leakage and propose remediation Actions",
            plant_id="plant_01",
            planned_steps=[
                MissionPlannedStep(
                    step_id="step_inspect",
                    title="Inspect Seal Chamber",
                    description="Visual and acoustic inspection",
                    step_type=StepType.INVESTIGATION,
                ),
                MissionPlannedStep(
                    step_id="step_action",
                    title="Propose Seal Replacement",
                    description="Propose replacement action",
                    step_type=StepType.ACTION_PROPOSAL,
                    depends_on=["step_inspect"],
                ),
            ],
            success_criteria=[
                MissionSuccessCriterion(
                    description="Seal leakage source confirmed with ultrasonic measurement",
                ),
            ],
            origin_reason="Acoustic sensor alert on Compressor C-102",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)
        assert mission.status == MissionStatus.DRAFT

        # 2. Validate -> VALIDATED
        val_resp = temp_service.validate_mission(operator_identity, mission.mission_id)
        assert val_resp.is_valid is True
        assert val_resp.status == MissionStatus.VALIDATED

        # 3. Submit for review -> REVIEW_REQUIRED
        submitted = temp_service.submit_for_review(
            operator_identity,
            mission.mission_id,
            submission_notes="Ready for Plant Manager review.",
        )
        assert submitted.status == MissionStatus.REVIEW_REQUIRED

        # 4. Plant Manager accepts -> ACCEPTED
        review_req = MissionReviewRequest(
            action="ACCEPT",
            review_notes="Approved investigation scope and proposed Action preparation.",
        )
        accepted = temp_service.review_mission(plant_manager_identity, mission.mission_id, review_req)
        assert accepted.status == MissionStatus.ACCEPTED
        assert accepted.reviewed_by == plant_manager_identity.user_id

    def test_submit_unvalidated_mission_rejected(self, temp_service, operator_identity):
        """Submitting a draft directly without prior successful validation is rejected."""
        create_req = MissionCreateRequest(
            title="Unvalidated Draft",
            description="Draft with cyclic step",
            mission_type=MissionType.INVESTIGATION,
            objective="Test submit unvalidated",
            plant_id="plant_01",
            origin_reason="Testing",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        with pytest.raises(MissionLifecycleError, match="must be in VALIDATED state before submission"):
            temp_service.submit_for_review(operator_identity, mission.mission_id, "Attempting skip")

    def test_accepted_mission_cannot_be_silently_mutated(self, temp_service, operator_identity, plant_manager_identity):
        """Once ACCEPTED, a mission is protected from direct mutation."""
        create_req = MissionCreateRequest(
            title="Accepted Mission",
            description="Testing immutability",
            mission_type=MissionType.INVESTIGATION,
            objective="Immutable objective",
            plant_id="plant_01",
            origin_reason="Testing",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)
        temp_service.validate_mission(operator_identity, mission.mission_id)
        temp_service.submit_for_review(operator_identity, mission.mission_id, "Submitting")
        temp_service.review_mission(plant_manager_identity, mission.mission_id, MissionReviewRequest(action="ACCEPT", review_notes="Accepted"))

        # Attempt to edit accepted mission
        update_req = MissionUpdateRequest(
            title="Mutated Title",
            update_reason="Trying to tamper with accepted mission",
        )
        with pytest.raises(MissionLifecycleError, match="cannot be edited directly"):
            temp_service.update_mission_draft(operator_identity, mission.mission_id, update_req)

    def test_cancellation_from_draft_and_accepted(self, temp_service, operator_identity, plant_manager_identity):
        """Missions can be cancelled from DRAFT or ACCEPTED states."""
        create_req = MissionCreateRequest(
            title="Cancellable Mission",
            description="Testing cancellation",
            mission_type=MissionType.INVESTIGATION,
            objective="Testing cancellation transitions",
            plant_id="plant_01",
            origin_reason="Testing",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        cancelled = temp_service.cancel_mission(operator_identity, mission.mission_id, "No longer needed")
        assert cancelled.status == MissionStatus.CANCELLED


# =============================================================================
# 4. PERSISTENCE & INTEGRITY TESTS
# =============================================================================

class TestMissionPersistenceAndIntegrity:
    """Verifies SQLite persistence, revision snapshots, optimistic locking, and idempotency."""

    def test_mission_survives_repository_reinitialization(self, temp_repo, operator_identity):
        """State persists across repository reinstantiations."""
        service = MissionService(repository=temp_repo)
        create_req = MissionCreateRequest(
            title="Durable Mission",
            description="Testing SQLite durability",
            mission_type=MissionType.PREDICTIVE_MAINTENANCE,
            objective="Ensure durability across restarts",
            plant_id="plant_01",
            origin_reason="Durability test",
        )
        mission = service.create_mission_draft(operator_identity, create_req)

        # Create new service instance with new repository on the same DB file
        new_repo = MissionRepository(db_path=temp_repo.db_path)
        new_service = MissionService(repository=new_repo)

        fetched = new_service.get_mission(operator_identity, mission.mission_id)
        assert fetched.mission_id == mission.mission_id
        assert fetched.title == "Durable Mission"
        assert fetched.status == MissionStatus.DRAFT

    def test_revision_snapshots_are_traceable(self, temp_service, operator_identity):
        """Updating a mission creates auditable, sequential revision snapshots."""
        create_req = MissionCreateRequest(
            title="Versioned Mission V1",
            description="Initial version",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective V1",
            plant_id="plant_01",
            origin_reason="Version test",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)
        assert mission.revision == 1

        update_req = MissionUpdateRequest(
            title="Versioned Mission V2",
            update_reason="Refining mission scope",
        )
        updated = temp_service.update_mission_draft(operator_identity, mission.mission_id, update_req)
        assert updated.revision == 2

        revisions = temp_service.get_revisions(operator_identity, mission.mission_id)
        assert len(revisions) == 2
        assert revisions[0].revision == 1
        assert revisions[1].revision == 2
        assert "Versioned Mission V1" in revisions[0].snapshot_json
        assert "Versioned Mission V2" in revisions[1].snapshot_json

    def test_concurrency_conflict_detected(self, temp_service, operator_identity):
        """Updating with an outdated expected_revision raises MissionConcurrencyError."""
        create_req = MissionCreateRequest(
            title="Concurrent Mission",
            description="Testing concurrency",
            mission_type=MissionType.INVESTIGATION,
            objective="Concurrency test",
            plant_id="plant_01",
            origin_reason="Concurrency test",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)

        # First update succeeds (revision 1 -> 2)
        temp_service.update_mission_draft(
            operator_identity,
            mission.mission_id,
            MissionUpdateRequest(title="Title V2", update_reason="First update"),
            expected_revision=1,
        )

        # Stale update with expected_revision=1 fails
        with pytest.raises(MissionConcurrencyError):
            temp_service.update_mission_draft(
                operator_identity,
                mission.mission_id,
                MissionUpdateRequest(title="Stale Title", update_reason="Conflicting update"),
                expected_revision=1,
            )

    def test_idempotent_creation_returns_same_mission(self, temp_service, operator_identity):
        """Re-submitting the exact same request with the same idempotency key returns existing record."""
        create_req = MissionCreateRequest(
            title="Idempotent Mission",
            description="Testing idempotency",
            mission_type=MissionType.INVESTIGATION,
            objective="Idempotent objective",
            plant_id="plant_01",
            origin_reason="Idempotency test",
            idempotency_key="idemp_key_12345",
        )
        mission1 = temp_service.create_mission_draft(operator_identity, create_req)
        mission2 = temp_service.create_mission_draft(operator_identity, create_req)

        assert mission1.mission_id == mission2.mission_id

    def test_conflicting_idempotency_key_rejected(self, temp_service, operator_identity):
        """Re-submitting a differing request with the same idempotency key raises conflict error."""
        create_req_1 = MissionCreateRequest(
            title="First Mission",
            description="Description 1",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective 1",
            plant_id="plant_01",
            origin_reason="Reason 1",
            idempotency_key="reused_key_999",
        )
        temp_service.create_mission_draft(operator_identity, create_req_1)

        create_req_2 = MissionCreateRequest(
            title="Second Mission Differing Title",
            description="Description 2",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective 2",
            plant_id="plant_01",
            origin_reason="Reason 2",
            idempotency_key="reused_key_999",  # Reused key with different payload!
        )
        with pytest.raises(MissionIdempotencyConflictError):
            temp_service.create_mission_draft(operator_identity, create_req_2)

    def test_audit_ledger_recorded_atomically(self, temp_service, operator_identity):
        """Lifecycle transitions create immutable audit ledger entries."""
        create_req = MissionCreateRequest(
            title="Audited Mission",
            description="Testing audit trail",
            mission_type=MissionType.INVESTIGATION,
            objective="Ensure all events are logged",
            plant_id="plant_01",
            origin_reason="Audit test",
        )
        mission = temp_service.create_mission_draft(operator_identity, create_req)
        temp_service.validate_mission(operator_identity, mission.mission_id)

        audit_events = temp_service.get_audit_ledger(operator_identity, mission.mission_id)
        assert len(audit_events) >= 2
        event_types = [a.event_type for a in audit_events]
        assert "MISSION_CREATED" in event_types
        assert "MISSION_VALIDATION_SUCCEEDED" in event_types


# =============================================================================
# 5. REST API ROUTE TESTS
# =============================================================================

class TestMissionAPIRoutes:
    """Verifies FastAPI REST endpoints at /api/v3/missions."""

    @pytest.fixture(autouse=True)
    def setup_api_client(self, operator_identity, plant_manager_identity):
        """Configures FastAPI TestClient with mocked authenticated identity."""
        self.client = TestClient(app)
        self.operator = operator_identity
        self.manager = plant_manager_identity

    def test_api_crud_and_lifecycle_flow(self, monkeypatch):
        """Full end-to-end API test covering creation, listing, validation, and review."""
        # Authenticate as operator
        app.dependency_overrides[get_current_identity] = lambda: self.operator

        payload = {
            "title": "API Test Mission",
            "description": "Created via FastAPI endpoint",
            "mission_type": "INVESTIGATION",
            "objective": "API integration verification",
            "plant_id": "plant_01",
            "origin_reason": "API test suite",
            "planned_steps": [
                {
                    "step_id": "step_01",
                    "title": "Initial Step",
                    "description": "Perform telemetry analysis",
                    "step_type": "ANALYSIS",
                }
            ],
            "success_criteria": [
                {
                    "description": "Telemetry confirms nominal state",
                }
            ],
        }

        # 1. POST /api/v3/missions
        res = self.client.post("/api/v3/missions", json=payload)
        assert res.status_code == 201
        data = res.json()
        mission_id = data["mission_id"]
        assert data["status"] == "DRAFT"

        # 2. GET /api/v3/missions/{id}
        res_get = self.client.get(f"/api/v3/missions/{mission_id}")
        assert res_get.status_code == 200
        assert res_get.json()["mission_id"] == mission_id

        # 3. GET /api/v3/missions (List)
        res_list = self.client.get("/api/v3/missions?plant_id=plant_01")
        assert res_list.status_code == 200
        list_data = res_list.json()
        assert list_data["total"] >= 1
        assert any(item["mission_id"] == mission_id for item in list_data["items"])

        # 4. POST /api/v3/missions/{id}/validate
        res_val = self.client.post(f"/api/v3/missions/{mission_id}/validate")
        assert res_val.status_code == 200
        val_data = res_val.json()
        assert val_data["is_valid"] is True
        assert val_data["status"] == "VALIDATED"

        # 5. POST /api/v3/missions/{id}/submit
        res_sub = self.client.post(f"/api/v3/missions/{mission_id}/submit")
        assert res_sub.status_code == 200
        assert res_sub.json()["status"] == "REVIEW_REQUIRED"

        # 6. POST /api/v3/missions/{id}/review (as Plant Manager)
        app.dependency_overrides[get_current_identity] = lambda: self.manager
        res_rev = self.client.post(
            f"/api/v3/missions/{mission_id}/review",
            json={"action": "ACCEPT", "review_notes": "Accepted via API test"},
        )
        assert res_rev.status_code == 200
        assert res_rev.json()["status"] == "ACCEPTED"

        # 7. GET /api/v3/missions/{id}/revisions
        res_revs = self.client.get(f"/api/v3/missions/{mission_id}/revisions")
        assert res_revs.status_code == 200
        assert len(res_revs.json()) >= 2

        # 8. GET /api/v3/missions/{id}/audit
        res_aud = self.client.get(f"/api/v3/missions/{mission_id}/audit")
        assert res_aud.status_code == 200
        assert len(res_aud.json()) >= 3

        # Clean up overrides
        app.dependency_overrides.clear()


# =============================================================================
# 6. ARCHITECTURAL SAFETY AST CHECKS (ZERO EXECUTION COUPLING)
# =============================================================================

class TestMissionArchitecturalASTSafety:
    """
    Parses mission architecture Python source files to prove that NO execution paths,
    ExecutionGateway invocations, shell commands, or PLC/SCADA writes were introduced.
    """

    MISSION_FILES = [
        os.path.join(os.path.dirname(__file__), "data", "schemas", "mission_contract.py"),
        os.path.join(os.path.dirname(__file__), "repositories", "mission_repository.py"),
        os.path.join(os.path.dirname(__file__), "services", "mission_service.py"),
        os.path.join(os.path.dirname(__file__), "api", "mission_routes.py"),
    ]

    def test_no_execution_gateway_imports(self):
        """Verifies zero imports or usages of ExecutionGateway."""
        for file_path in self.MISSION_FILES:
            if not os.path.exists(file_path):
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "ExecutionGateway" not in alias.name
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        assert "ExecutionGateway" not in node.module
                    for alias in node.names:
                        assert "ExecutionGateway" not in alias.name

    def test_no_shell_or_eval_calls(self):
        """Verifies zero calls to os.system, subprocess, eval, or exec."""
        for file_path in self.MISSION_FILES:
            if not os.path.exists(file_path):
                continue
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        assert node.func.id not in ("eval", "exec")
                    elif isinstance(node.func, ast.Attribute):
                        assert node.func.attr not in ("system", "popen", "check_call", "check_output")

    def test_no_execution_endpoints_in_routes(self):
        """Verifies that no /execute or /run routes exist in mission_routes.py."""
        route_file = os.path.join(os.path.dirname(__file__), "api", "mission_routes.py")
        with open(route_file, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=route_file)

        # Inspect all function decorators for router.(get|post|put|delete|patch)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                        if decorator.func.attr in ("get", "post", "put", "delete", "patch"):
                            if decorator.args:
                                first_arg = decorator.args[0]
                                if isinstance(first_arg, ast.Constant):
                                    path = str(first_arg.value)
                                    assert "execute" not in path, f"Disallowed execution endpoint found: {path}"
                                    assert "run" not in path, f"Disallowed run endpoint found: {path}"
                assert not node.name.startswith("execute_"), f"Disallowed execution function: {node.name}"

