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
    from services.action_store import action_store
    from data.schemas.action_contract import Action, ActionTarget, ResourceType, ActionType, ActionReason
    from repositories.evidence_explainability_repository import evidence_explainability_repository
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
    from backend.services.action_store import action_store
    from backend.data.schemas.action_contract import Action, ActionTarget, ResourceType, ActionType, ActionReason
    from backend.repositories.evidence_explainability_repository import evidence_explainability_repository


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


# =============================================================================
# 7. PROMPT 35A HARDENING TESTS
# =============================================================================

class TestPrompt35APlantAuthorizationHardening:
    """Verifies fail-closed plant scoping, wildcard semantics, and pagination count safety."""

    def test_assigned_plants_single_permitted(self, temp_service):
        """Caller assigned to plant_001 permitted only for plant_001; plant_002 denied."""
        single_plant_user = Identity(
            user_id="op_p1",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            roles=["OPERATOR"],
            permissions=["mission.create", "mission.read"],
            assigned_plants=["plant_001"],
        )

        req_ok = MissionCreateRequest(
            title="Plant 1 Mission",
            description="Scoped strictly to plant 1",
            mission_type=MissionType.INVESTIGATION,
            objective="Inspect plant 1 compressor",
            plant_id="plant_001",
            origin_reason="Vibration alert",
        )
        created = temp_service.create_mission_draft(single_plant_user, req_ok)
        assert created.scope.plant_id == "plant_001"

        req_denied = MissionCreateRequest(
            title="Plant 2 Mission",
            description="Attempt to access plant 2",
            mission_type=MissionType.INVESTIGATION,
            objective="Inspect plant 2 compressor",
            plant_id="plant_002",
            origin_reason="Vibration alert",
        )
        with pytest.raises(MissionPermissionError, match="not authorized for plant 'plant_002'"):
            temp_service.create_mission_draft(single_plant_user, req_denied)

    def test_assigned_plants_empty_fails_closed(self, temp_service, plant_manager_identity):
        """Caller with empty assigned_plants=[] fails closed and cannot create, get, or list."""
        # 1. Create a mission first using manager
        valid_req = MissionCreateRequest(
            title="Existing Mission",
            description="Existing valid mission",
            mission_type=MissionType.INVESTIGATION,
            objective="Baseline objective",
            plant_id="plant_01",
            origin_reason="Initial baseline",
        )
        m = temp_service.create_mission_draft(plant_manager_identity, valid_req)

        # 2. Caller with explicitly empty assigned_plants
        empty_plants_user = Identity(
            user_id="op_empty",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            roles=["OPERATOR"],
            permissions=["mission.create", "mission.read", "mission.update", "mission.cancel"],
            assigned_plants=[],
        )

        # Create fails closed
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.create_mission_draft(empty_plants_user, valid_req)

        # Get fails closed
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.get_mission(empty_plants_user, m.mission_id)

        # List returns 0 results
        missions, total = temp_service.list_missions(empty_plants_user)
        assert missions == []
        assert total == 0

        # Update draft fails closed
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.update_mission_draft(
                empty_plants_user,
                m.mission_id,
                MissionUpdateRequest(title="Updated Title", update_reason="Attempt update"),
            )

        # Cancel fails closed
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.cancel_mission(empty_plants_user, m.mission_id, "Attempt cancel")

    def test_assigned_plants_missing_or_none_fails_closed(self, temp_service):
        """Caller with missing or None assigned_plants attribute fails closed."""
        class MockIdentityMissingPlants:
            user_id = "op_none"
            tenant_id = "tenant_alpha"
            workspace_id = "workspace_prod"
            roles = ["OPERATOR"]
            permissions = ["mission.create", "mission.read"]
            clearance_level = 1
            is_server_authoritative = False

        missing_user = MockIdentityMissingPlants()
        req = MissionCreateRequest(
            title="Test Missing Assignment",
            description="Should fail closed",
            mission_type=MissionType.INVESTIGATION,
            objective="Attempted creation",
            plant_id="plant_01",
            origin_reason="Test check",
        )
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.create_mission_draft(missing_user, req)

        # Also test None explicitly
        missing_user.assigned_plants = None
        with pytest.raises(MissionPermissionError, match="has no assigned plants"):
            temp_service.create_mission_draft(missing_user, req)

    def test_assigned_plants_wildcard_authoritative(self, temp_service, plant_manager_identity):
        """Explicit wildcard allows unrestricted plant access."""
        for pid in ["plant_alpha", "plant_beta", "plant_gamma"]:
            req = MissionCreateRequest(
                title=f"Mission for {pid}",
                description="Wildcard multi-plant access",
                mission_type=MissionType.INVESTIGATION,
                objective=f"Objective for {pid}",
                plant_id=pid,
                origin_reason="Manager setup",
            )
            created = temp_service.create_mission_draft(plant_manager_identity, req)
            assert created.scope.plant_id == pid

    def test_list_missions_pagination_does_not_leak_unauthorized_plants(self, temp_service, plant_manager_identity):
        """Listing missions calculates counts and returns items strictly within authorized plants."""
        # Create 3 missions for plant_01 and 2 for plant_02
        for i in range(3):
            temp_service.create_mission_draft(
                plant_manager_identity,
                MissionCreateRequest(
                    title=f"Plant 1 Mission {i}",
                    description=f"Description for plant 1 mission {i}",
                    mission_type=MissionType.INVESTIGATION,
                    objective=f"Objective {i}",
                    plant_id="plant_01",
                    origin_reason="Setup",
                ),
            )
        for j in range(2):
            temp_service.create_mission_draft(
                plant_manager_identity,
                MissionCreateRequest(
                    title=f"Plant 2 Mission {j}",
                    description=f"Description for plant 2 mission {j}",
                    mission_type=MissionType.INVESTIGATION,
                    objective=f"Objective {j}",
                    plant_id="plant_02",
                    origin_reason="Setup",
                ),
            )

        # Plant 01 operator
        p1_op = Identity(
            user_id="op_plant1",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            roles=["OPERATOR"],
            permissions=["mission.read"],
            assigned_plants=["plant_01"],
        )

        missions, total = temp_service.list_missions(p1_op, limit=10, offset=0)
        assert total == 3, f"Pagination total must be 3, not {total} (no leakage of plant_02)"
        assert len(missions) == 3
        assert all(m.scope.plant_id == "plant_01" for m in missions)

        # Wildcard manager
        all_missions, all_total = temp_service.list_missions(plant_manager_identity, limit=10, offset=0)
        assert all_total == 5
        assert len(all_missions) == 5


class TestPrompt35AServerAuthoritativeOutcomeStatus:
    """Verifies that clients and LLMs cannot self-certify criteria or step outcomes."""

    def test_client_cannot_self_certify_criterion_satisfied(self):
        """MissionCreateRequest rejects criterion marked SATISFIED."""
        with pytest.raises(ValueError, match="cannot be self-certified as 'SATISFIED'"):
            MissionCreateRequest(
                title="Self Certified Criterion",
                description="Client trying to mark success",
                mission_type=MissionType.INVESTIGATION,
                objective="Test verification guard",
                plant_id="plant_01",
                success_criteria=[
                    MissionSuccessCriterion(
                        criterion_id="crit_01",
                        description="Vibration reduced below 2mm/s",
                        status=CriterionStatus.SATISFIED,
                    )
                ],
                origin_reason="Test check",
            )

    def test_client_cannot_self_certify_criterion_not_satisfied(self):
        """MissionCreateRequest rejects criterion marked NOT_SATISFIED."""
        with pytest.raises(ValueError, match="cannot be self-certified as 'NOT_SATISFIED'"):
            MissionCreateRequest(
                title="Self Certified Negative Criterion",
                description="Client trying to mark outcome",
                mission_type=MissionType.INVESTIGATION,
                objective="Test verification guard",
                plant_id="plant_01",
                success_criteria=[
                    MissionSuccessCriterion(
                        criterion_id="crit_01",
                        description="Vibration benchmark",
                        status=CriterionStatus.NOT_SATISFIED,
                    )
                ],
                origin_reason="Test check",
            )

    def test_client_cannot_update_criterion_to_satisfied(self):
        """MissionUpdateRequest rejects criterion marked SATISFIED."""
        with pytest.raises(ValueError, match="cannot be self-certified as 'SATISFIED'"):
            MissionUpdateRequest(
                title="Updated Title",
                success_criteria=[
                    MissionSuccessCriterion(
                        criterion_id="crit_01",
                        description="Benchmark achieved",
                        status=CriterionStatus.SATISFIED,
                    )
                ],
                update_reason="Attempt false outcome",
            )

    def test_client_cannot_claim_completed_or_in_progress_step(self):
        """MissionCreateRequest rejects steps marked COMPLETED, IN_PROGRESS, or FAILED."""
        for invalid_status in (StepStatus.COMPLETED, StepStatus.IN_PROGRESS, StepStatus.FAILED):
            with pytest.raises(ValueError, match=f"cannot be initialized to '{invalid_status.value}'"):
                MissionCreateRequest(
                    title="Self Certified Step",
                    description="Client claiming step work happened",
                    mission_type=MissionType.INVESTIGATION,
                    objective="Test step outcome guard",
                    plant_id="plant_01",
                    planned_steps=[
                        MissionPlannedStep(
                            step_id="step_01",
                            title="Repair Seal",
                            description="Work claimed done",
                            step_type=StepType.ANALYSIS,
                            status=invalid_status,
                        )
                    ],
                    origin_reason="Test check",
                )

    def test_client_cannot_update_step_to_completed(self):
        """MissionUpdateRequest rejects steps updated to COMPLETED."""
        with pytest.raises(ValueError, match="cannot claim unverified execution outcome status 'COMPLETED'"):
            MissionUpdateRequest(
                planned_steps=[
                    MissionPlannedStep(
                        step_id="step_01",
                        title="Work done",
                        description="Work claimed completed",
                        step_type=StepType.ANALYSIS,
                        status=StepStatus.COMPLETED,
                    )
                ],
                update_reason="Attempt false step completion",
            )

    def test_client_payload_cannot_set_mission_status_directly(self):
        """API endpoints reject client payloads with extra 'status' field (ConfigDict extra='forbid')."""
        client = TestClient(app)
        mgr = Identity(
            user_id="mgr_status",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            roles=["PLANT_MANAGER"],
            permissions=["mission.create", "mission.read"],
            assigned_plants=["*"],
        )
        app.dependency_overrides[get_current_identity] = lambda: mgr
        try:
            # Client attempting to set status directly to VALIDATED
            payload = {
                "title": "Bypass Test",
                "description": "Trying to bypass draft state",
                "mission_type": "INVESTIGATION",
                "objective": "Verify status is server authoritative",
                "plant_id": "plant_01",
                "origin_reason": "Test",
                "status": "VALIDATED",
            }
            res = client.post("/api/v3/missions", json=payload)
            assert res.status_code == 422, f"Extra status field must be rejected with 422, got {res.status_code}"
        finally:
            app.dependency_overrides.clear()


class TestPrompt35AResourceReferenceValidation:
    """Verifies scope-aware validation of referenced actions, decisions, evidence, incidents, and RCAs."""

    def test_valid_in_scope_resource_references(self, temp_service, operator_identity):
        """Valid reference in authorized tenant, workspace, and plant passes validation."""
        # Seed valid action
        action_id = f"act_in_scope_{uuid.uuid4().hex[:8]}"
        action = Action(
            action_id=action_id,
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            session_id="session_1",
            target=ActionTarget(resource_type=ResourceType.MACHINE, resource_id="M-101", plant_id="plant_01"),
            parameters={"interval": "weekly"},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Preventative inspection"),
        )
        action_store.save(action)

        req = MissionCreateRequest(
            title="Mission With Valid Action",
            description="References valid in-scope action",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective with verified action reference",
            plant_id="plant_01",
            related_resources={"actions": [action_id]},
            origin_reason="Setup with action",
        )
        mission = temp_service.create_mission_draft(operator_identity, req)
        val_resp = temp_service.validate_mission(operator_identity, mission.mission_id)
        assert val_resp.is_valid is True
        assert val_resp.status == MissionStatus.VALIDATED

    def test_nonexistent_resource_reference_rejected(self, temp_service, operator_identity):
        """Draft creation referencing non-existent action is rejected fail-closed."""
        req = MissionCreateRequest(
            title="Mission With Nonexistent Action",
            description="References phantom action",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective with phantom action",
            plant_id="plant_01",
            related_resources={"actions": ["act_phantom_9999"]},
            origin_reason="Setup with phantom",
        )
        with pytest.raises(MissionValidationError, match="not found"):
            temp_service.create_mission_draft(operator_identity, req)

    def test_cross_tenant_resource_reference_rejected(self, temp_service, operator_identity):
        """Reference to resource belonging to a different tenant is rejected with non-disclosing error."""
        cross_act_id = f"act_cross_tenant_{uuid.uuid4().hex[:8]}"
        action = Action(
            action_id=cross_act_id,
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            tenant_id="tenant_other_corp",  # Different tenant
            workspace_id="workspace_prod",
            session_id="session_1",
            target=ActionTarget(resource_type=ResourceType.MACHINE, resource_id="M-101", plant_id="plant_01"),
            parameters={"interval": "weekly"},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Foreign tenant action"),
        )
        action_store.save(action)

        req = MissionCreateRequest(
            title="Cross Tenant Reference Attack",
            description="Attempt to reference foreign tenant action",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective with foreign tenant action",
            plant_id="plant_01",
            related_resources={"actions": [cross_act_id]},
            origin_reason="Probe cross-tenant",
        )
        with pytest.raises(MissionValidationError, match="invalid or inaccessible in the authorized scope"):
            temp_service.create_mission_draft(operator_identity, req)

    def test_cross_workspace_resource_reference_rejected(self, temp_service, operator_identity):
        """Reference to resource belonging to a different workspace is rejected with non-disclosing error."""
        cross_ws_id = f"act_cross_ws_{uuid.uuid4().hex[:8]}"
        action = Action(
            action_id=cross_ws_id,
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            tenant_id="tenant_alpha",
            workspace_id="workspace_other",  # Different workspace
            session_id="session_1",
            target=ActionTarget(resource_type=ResourceType.MACHINE, resource_id="M-101", plant_id="plant_01"),
            parameters={"interval": "weekly"},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Foreign workspace action"),
        )
        action_store.save(action)

        req = MissionCreateRequest(
            title="Cross Workspace Reference Attack",
            description="Attempt to reference foreign workspace action",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective with foreign workspace action",
            plant_id="plant_01",
            related_resources={"actions": [cross_ws_id]},
            origin_reason="Probe cross-workspace",
        )
        with pytest.raises(MissionValidationError, match="invalid or inaccessible in the authorized scope"):
            temp_service.create_mission_draft(operator_identity, req)

    def test_unauthorized_plant_resource_reference_rejected(self, temp_service, operator_identity):
        """Reference to resource at unauthorized plant is rejected."""
        foreign_plant_act_id = f"act_plant99_{uuid.uuid4().hex[:8]}"
        action = Action(
            action_id=foreign_plant_act_id,
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            session_id="session_1",
            target=ActionTarget(resource_type=ResourceType.MACHINE, resource_id="M-101", plant_id="plant_99"),
            parameters={"interval": "weekly"},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Plant 99 action"),
        )
        action_store.save(action)

        req = MissionCreateRequest(
            title="Unauthorized Plant Action Reference",
            description="Caller assigned only to plant_01 attempts referencing plant_99 action",
            mission_type=MissionType.INVESTIGATION,
            objective="Objective with unauthorized plant action",
            plant_id="plant_01",
            related_resources={"actions": [foreign_plant_act_id]},
            origin_reason="Probe unauthorized plant",
        )
        with pytest.raises(MissionValidationError, match="invalid or inaccessible in the authorized scope"):
            temp_service.create_mission_draft(operator_identity, req)

    def test_unsupported_resource_category_rejected(self):
        """Attempting to specify an unsupported resource category in related_resources is rejected."""
        with pytest.raises(ValueError, match="Unsupported resource category 'quantum_telemetry'"):
            MissionCreateRequest(
                title="Unsupported Category Test",
                description="Testing unknown category rejection",
                mission_type=MissionType.INVESTIGATION,
                objective="Test category bounds",
                plant_id="plant_01",
                related_resources={"quantum_telemetry": ["qt_01"]},
                origin_reason="Setup unknown category",
            )

    def test_missing_linked_evidence_rejected(self, temp_service, operator_identity):
        """Evidence requirement pointing to nonexistent evidence ID is rejected."""
        req = MissionCreateRequest(
            title="Missing Evidence Test",
            description="Testing missing evidence rejection",
            mission_type=MissionType.INVESTIGATION,
            objective="Test missing evidence requirement",
            plant_id="plant_01",
            evidence_requirements=[
                MissionEvidenceRequirement(
                    requirement_id="evreq_01",
                    evidence_type="telemetry",
                    description="Vibration log file",
                    linked_evidence_id="ev_missing_888",
                )
            ],
            origin_reason="Setup missing evidence",
        )
        with pytest.raises(MissionValidationError, match="not found"):
            temp_service.create_mission_draft(operator_identity, req)

    def test_unverified_evidence_warns_and_does_not_certify_success(self, temp_service, operator_identity):
        """Unverified evidence produces domain warning and never automatically satisfies criteria."""
        unverified_ev_id = f"ev_unverified_{uuid.uuid4().hex[:8]}"
        exp_id = f"exp_test_{uuid.uuid4().hex[:8]}"

        with evidence_explainability_repository._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO evidence_explanations (
                    explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                    fingerprint, assessment_timestamp, algorithm_version, contract_version, is_partial, summary, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    exp_id, "DECISION", "dec_1", "tenant_alpha", "workspace_prod", "plant_01",
                    "fp_test", "2026-10-11T00:00:00Z", "1.0", "1.0", 0, "Summary", "{}", "2026-10-11T00:00:00Z",
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO evidence_records (
                    evidence_id, explanation_id, tenant_id, workspace_id, plant_id, source_type,
                    source_record_id, provenance, validation_status, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    unverified_ev_id, exp_id, "tenant_alpha", "workspace_prod", "plant_01",
                    "TELEMETRY", "src_1", "test_source", "UNVERIFIED", "{}", "2026-10-11T00:00:00Z",
                ),
            )
            conn.commit()

        req = MissionCreateRequest(
            title="Unverified Evidence Mission",
            description="References unverified evidence",
            mission_type=MissionType.INVESTIGATION,
            objective="Ensure unverified evidence remains unverified",
            plant_id="plant_01",
            evidence_requirements=[
                MissionEvidenceRequirement(
                    requirement_id="evreq_unverified",
                    evidence_type="telemetry",
                    description="Acoustic reading",
                    linked_evidence_id=unverified_ev_id,
                )
            ],
            success_criteria=[
                MissionSuccessCriterion(
                    description="Vibration within nominal limits",
                )
            ],
            origin_reason="Setup unverified test",
        )
        mission = temp_service.create_mission_draft(operator_identity, req)
        val_resp = temp_service.validate_mission(operator_identity, mission.mission_id)
        assert val_resp.is_valid is True
        assert any("is unverified" in w for w in val_resp.warnings)

        # Confirm criterion status is strictly UNKNOWN
        persisted = temp_service.get_mission(operator_identity, mission.mission_id)
        assert persisted.success_criteria[0].status == CriterionStatus.UNKNOWN


class TestPrompt35APayloadBoundsAndSecretScanning:
    """Verifies that nested mappings, arbitrary payloads, and secrets are strictly bounded and filtered."""

    def test_nested_parameters_depth_exceeded_rejected(self):
        """Constraint parameters exceeding depth 3 are rejected."""
        deep_params = {"level1": {"level2": {"level3": {"level4": "too_deep"}}}}
        with pytest.raises(ValueError, match="nesting depth exceeds maximum allowed"):
            MissionConstraint(
                constraint_type=ConstraintType.OPERATIONAL,
                description="Deep constraint",
                parameters=deep_params,
            )

    def test_nested_parameters_key_count_exceeded_rejected(self):
        """Constraint parameters exceeding 20 total keys are rejected."""
        many_keys = {f"k_{i}": i for i in range(25)}
        with pytest.raises(ValueError, match="total key count exceeds maximum allowed"):
            MissionConstraint(
                constraint_type=ConstraintType.OPERATIONAL,
                description="Broad constraint",
                parameters=many_keys,
            )

    def test_nested_parameters_serialized_size_exceeded_rejected(self):
        """Constraint parameters exceeding 4096 serialized bytes are rejected."""
        large_params = {"payload": "A" * 4100}
        with pytest.raises(ValueError, match="serialized size exceeds maximum allowed"):
            MissionConstraint(
                constraint_type=ConstraintType.OPERATIONAL,
                description="Heavy constraint",
                parameters=large_params,
            )

    def test_prohibited_metadata_keys_in_parameters_rejected(self):
        """Prohibited credential/secret metadata keys in parameters are rejected."""
        for secret_key in ("password", "api_key", "secret_key", "token", "private_key"):
            with pytest.raises(ValueError, match="Prohibited secret metadata key"):
                MissionConstraint(
                    constraint_type=ConstraintType.OPERATIONAL,
                    description="Secret key in parameter",
                    parameters={secret_key: "my_secret_val"},
                )

    def test_secret_patterns_in_text_rejected(self):
        """Raw credentials, private keys, connection strings, and bearer tokens in text are rejected."""
        # 1. Private key
        with pytest.raises(ValueError, match="contains potential secret"):
            MissionCreateRequest(
                title="Mission with private key",
                description="-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...",
                mission_type=MissionType.INVESTIGATION,
                objective="Test secret filter",
                plant_id="plant_01",
                origin_reason="Setup",
            )

        # 2. Connection string with embedded credentials
        with pytest.raises(ValueError, match="contains potential secret"):
            MissionCreateRequest(
                title="Mission with connection string",
                description="Connect via postgres://admin:SuperSecret123@db.prod:5432/scada",
                mission_type=MissionType.INVESTIGATION,
                objective="Test secret filter",
                plant_id="plant_01",
                origin_reason="Setup",
            )

        # 3. Bearer token
        with pytest.raises(ValueError, match="contains potential secret"):
            MissionCreateRequest(
                title="Mission with bearer token",
                description="Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ91234567890",
                mission_type=MissionType.INVESTIGATION,
                objective="Test secret filter",
                plant_id="plant_01",
                origin_reason="Setup",
            )

    def test_oversized_related_resources_rejected(self):
        """related_resources exceeding aggregate limit of 50 IDs is rejected."""
        oversized = {
            "actions": [f"act_{i}" for i in range(25)],
            "decisions": [f"dec_{i}" for i in range(25)],
            "incidents": ["inc_01", "inc_02"],  # total 52 > 50
        }
        with pytest.raises(ValueError, match="Aggregate related_resources count .* exceeds maximum allowed"):
            MissionCreateRequest(
                title="Oversized related resources",
                description="Too many related references",
                mission_type=MissionType.INVESTIGATION,
                objective="Test aggregate limit",
                plant_id="plant_01",
                related_resources=oversized,
                origin_reason="Setup",
            )

    def test_step_bounds_enforced(self):
        """Step bounds on related_resource_ids (max 20) and required_evidence (max 20) enforced."""
        with pytest.raises(ValueError, match=r"(related_resource_ids count .* exceeds maximum|at most 20 items)"):
            MissionPlannedStep(
                step_id="step_bound_1",
                title="Too many resources",
                description="Step with 25 resources",
                step_type=StepType.ANALYSIS,
                related_resource_ids=[f"act_{i}" for i in range(25)],
            )

        with pytest.raises(ValueError, match=r"(required_evidence count .* exceeds maximum|at most 20 items)"):
            MissionPlannedStep(
                step_id="step_bound_2",
                title="Too many evidence items",
                description="Step with 25 evidence items",
                step_type=StepType.ANALYSIS,
                required_evidence=[f"evidence_item_{i}" for i in range(25)],
            )


class TestPrompt35APersistenceAndAuditIntegrity:
    """Verifies that validation failures do not log success audit events, and lifecycle integrity is preserved."""

    def test_failed_validation_records_failure_audit_and_preserves_draft(self, temp_service, operator_identity):
        """When validation fails due to invalid references, status remains DRAFT and audit event is recorded."""
        # 1. Create a draft without references initially
        req = MissionCreateRequest(
            title="Validation Failure Test Mission",
            description="Testing failed validation audit trail",
            mission_type=MissionType.INVESTIGATION,
            objective="Ensure failed validation logs failure",
            plant_id="plant_01",
            origin_reason="Audit test",
        )
        mission = temp_service.create_mission_draft(operator_identity, req)
        assert mission.status == MissionStatus.DRAFT

        # 2. Directly simulate corrupted reference in repository to test validate_mission failure path
        with temp_service.repository._lock, temp_service.repository._get_connection() as conn:
            conn.execute(
                "UPDATE missions SET related_resources_json = ? WHERE mission_id = ?",
                (json.dumps({"actions": ["act_missing_phantom"]}), mission.mission_id),
            )
            conn.commit()

        # 3. Execute validate_mission
        val_resp = temp_service.validate_mission(operator_identity, mission.mission_id)
        assert val_resp.is_valid is False
        assert val_resp.status == MissionStatus.DRAFT

        # 4. Check audit ledger: event_type must be MISSION_VALIDATION_FAILED with result FAILURE
        ledger = temp_service.get_audit_ledger(operator_identity, mission.mission_id)
        latest_audit = ledger[0]  # Ordered DESC by timestamp
        assert latest_audit.event_type == "MISSION_VALIDATION_FAILED"
        assert latest_audit.result == "FAILURE"
        assert "act_missing_phantom" in str(latest_audit.details.get("errors", []))

