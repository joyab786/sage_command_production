# backend/services/mission_service.py
"""
SageCommand V3 — Governed Mission Architecture Foundation Service (Prompt 35)

A MISSION IS A GOVERNED OPERATIONAL OBJECTIVE AND WORK PLAN ONLY — NEVER CONSTITUTES
DIRECT EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Governs industrial mission domain validation, deterministic DAG evaluation, scope boundaries,
lifecycle state machine transitions, immutable revision snapshots, and audit logging.

Cardinal Invariants:
1. Operational intent only: missions organize objectives and work steps; they NEVER execute actions.
2. Tenant, workspace, and plant scope are authoritative from caller identity; missing workspace fails closed.
3. Step dependencies must form a strictly acyclic directed graph (DAG).
4. Lifecycle transitions are strictly enforced: DRAFT -> VALIDATED -> REVIEW_REQUIRED -> ACCEPTED / REJECTED / CANCELLED.
5. Validated and accepted missions are immutable; modifications require new revisions.
6. Execution endpoints (/execute, /run) are strictly forbidden and non-existent.
7. Anti-smuggling checks prevent SQL, shell commands, or executable code from entering criteria or steps.
"""

import hashlib
import json
import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone

try:
    from core.auth import Identity
    from core.config import (
        SAGE_MISSION_MAX_STEPS,
        SAGE_MISSION_MAX_DEPENDENCIES,
        SAGE_MISSION_MAX_CRITERIA,
        SAGE_MISSION_MAX_CONSTRAINTS,
        SAGE_MISSION_MAX_EVIDENCE_REQS,
        SAGE_MISSION_MAX_RELATED_RESOURCES,
        SAGE_MISSION_MAX_TITLE_LENGTH,
        SAGE_MISSION_MAX_DESC_LENGTH,
        SAGE_MISSION_MAX_OBJECTIVE_LENGTH,
        SAGE_MISSION_DEFAULT_LIST_LIMIT,
        SAGE_MISSION_MAX_LIST_RESULTS,
    )
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
        MissionRepositoryError,
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity
    from backend.core.config import (
        SAGE_MISSION_MAX_STEPS,
        SAGE_MISSION_MAX_DEPENDENCIES,
        SAGE_MISSION_MAX_CRITERIA,
        SAGE_MISSION_MAX_CONSTRAINTS,
        SAGE_MISSION_MAX_EVIDENCE_REQS,
        SAGE_MISSION_MAX_RELATED_RESOURCES,
        SAGE_MISSION_MAX_TITLE_LENGTH,
        SAGE_MISSION_MAX_DESC_LENGTH,
        SAGE_MISSION_MAX_OBJECTIVE_LENGTH,
        SAGE_MISSION_DEFAULT_LIST_LIMIT,
        SAGE_MISSION_MAX_LIST_RESULTS,
    )
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
        MissionRepositoryError,
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )

logger = logging.getLogger("mission_service")


class MissionServiceError(Exception):
    """Base exception for mission service operations."""
    pass


class MissionPermissionError(MissionServiceError):
    """Raised on scope, tenant, workspace, or plant authorization violations."""
    pass


class MissionValidationError(MissionServiceError):
    """Raised on domain or structural validation failures."""
    pass


class MissionLifecycleError(MissionServiceError):
    """Raised on invalid lifecycle state transitions."""
    pass


class MissionService:
    """
    Canonical service for managing governed industrial missions.
    """

    def __init__(self, repository: Optional[MissionRepository] = None):
        self.repository = repository or MissionRepository()

    # -------------------------------------------------------------------------
    # SCOPE & SECURITY VALIDATION
    # -------------------------------------------------------------------------

    def _validate_scope_authority(self, identity: Identity, requested_plant_id: Optional[str] = None) -> None:
        """
        Validates authoritative caller scope:
        - Workspace ID must not be empty or null (fail closed).
        - Tenant ID must not be empty or null.
        - Plant ID (if requested) must be in caller's assigned plants.
        """
        if not identity.workspace_id or not identity.workspace_id.strip():
            logger.warning(f"Rejecting mission access: caller '{identity.user_id}' has empty workspace_id.")
            raise MissionPermissionError("Authoritative workspace identity is required. Access denied (fail-closed).")

        if not identity.tenant_id or not identity.tenant_id.strip():
            logger.warning(f"Rejecting mission access: caller '{identity.user_id}' has empty tenant_id.")
            raise MissionPermissionError("Authoritative tenant identity is required. Access denied (fail-closed).")

        if requested_plant_id:
            assigned = getattr(identity, "assigned_plants", ["*"]) or ["*"]
            if "*" not in assigned and requested_plant_id not in assigned:
                logger.warning(
                    f"Scope denial: caller '{identity.user_id}' assigned to {assigned} attempted access to plant '{requested_plant_id}'."
                )
                raise MissionPermissionError(
                    f"Caller is not authorized for plant '{requested_plant_id}'."
                )

    def _hash_request_payload(self, request: MissionCreateRequest) -> str:
        """Generates deterministic SHA-256 hash of creation request payload."""
        data = request.model_dump(exclude={"idempotency_key"})
        dumped = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(dumped.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------------------
    # DOMAIN VALIDATION ENGINE
    # -------------------------------------------------------------------------

    def validate_mission_structure(self, mission: Mission) -> Tuple[bool, List[str], List[str]]:
        """
        Deterministically evaluates structural integrity, DAG acyclicity, bounds,
        and anti-smuggling constraints.

        Returns:
            Tuple[is_valid, error_list, warning_list]
        """
        errors: List[str] = []
        warnings: List[str] = []

        # 1. Bounds checks
        if len(mission.title) > SAGE_MISSION_MAX_TITLE_LENGTH:
            errors.append(f"Title length ({len(mission.title)}) exceeds maximum ({SAGE_MISSION_MAX_TITLE_LENGTH}).")

        if len(mission.description) > SAGE_MISSION_MAX_DESC_LENGTH:
            errors.append(f"Description length ({len(mission.description)}) exceeds maximum ({SAGE_MISSION_MAX_DESC_LENGTH}).")

        if len(mission.objective) > SAGE_MISSION_MAX_OBJECTIVE_LENGTH:
            errors.append(f"Objective length ({len(mission.objective)}) exceeds maximum ({SAGE_MISSION_MAX_OBJECTIVE_LENGTH}).")

        if len(mission.constraints) > SAGE_MISSION_MAX_CONSTRAINTS:
            errors.append(f"Constraint count ({len(mission.constraints)}) exceeds maximum ({SAGE_MISSION_MAX_CONSTRAINTS}).")

        if len(mission.success_criteria) > SAGE_MISSION_MAX_CRITERIA:
            errors.append(f"Success criteria count ({len(mission.success_criteria)}) exceeds maximum ({SAGE_MISSION_MAX_CRITERIA}).")

        if len(mission.evidence_requirements) > SAGE_MISSION_MAX_EVIDENCE_REQS:
            errors.append(f"Evidence requirements count ({len(mission.evidence_requirements)}) exceeds maximum ({SAGE_MISSION_MAX_EVIDENCE_REQS}).")

        # 2. DAG validation
        dag_valid, dag_errors = validate_mission_dependencies(
            mission.planned_steps,
            max_steps=SAGE_MISSION_MAX_STEPS,
            max_dependencies=SAGE_MISSION_MAX_DEPENDENCIES,
        )
        if not dag_valid:
            errors.extend(dag_errors)

        # 3. Success criteria content validation
        if not mission.success_criteria:
            warnings.append("Mission has no defined success criteria; review will require explicit operational benchmarks.")

        # 4. Related resources validation
        total_related = sum(len(v) for v in mission.related_resources.values())
        if total_related > SAGE_MISSION_MAX_RELATED_RESOURCES:
            errors.append(f"Total related resources ({total_related}) exceeds maximum ({SAGE_MISSION_MAX_RELATED_RESOURCES}).")

        return (len(errors) == 0, errors, warnings)

    # -------------------------------------------------------------------------
    # MISSION LIFECYCLE OPERATIONS
    # -------------------------------------------------------------------------

    def create_mission_draft(
        self,
        identity: Identity,
        request: MissionCreateRequest,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Mission:
        """
        Creates a new industrial mission draft.
        Enforces authoritative scope, initial DRAFT state, and deterministic validation.
        """
        # Validate caller scope
        self._validate_scope_authority(identity, request.plant_id)

        scope = MissionScope(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=request.plant_id,
            session_id=identity.session_id,
        )

        provenance = MissionProvenance(
            created_by=identity.user_id,
            created_by_role=identity.roles[0] if identity.roles else "OPERATOR",
            origin_reason=request.origin_reason,
            parent_incident_id=request.parent_incident_id,
            parent_rca_id=request.parent_rca_id,
            source_system="sagecommand_v3",
        )

        mission = Mission(
            title=request.title,
            description=request.description,
            mission_type=request.mission_type,
            objective=request.objective,
            scope=scope,
            constraints=request.constraints,
            success_criteria=request.success_criteria,
            planned_steps=request.planned_steps,
            evidence_requirements=request.evidence_requirements,
            related_resources=request.related_resources,
            data_mode=DataMode.SIMULATION,  # Authoritative default: SIMULATION
            status=MissionStatus.DRAFT,
            provenance=provenance,
            created_by=identity.user_id,
        )

        # Structural check
        is_valid, errors, warnings = self.validate_mission_structure(mission)
        mission.validation_errors = errors
        mission.validation_warnings = warnings

        # Audit event
        audit_event = MissionAuditRecord(
            mission_id=mission.mission_id,
            revision=mission.revision,
            tenant_id=mission.scope.tenant_id,
            workspace_id=mission.scope.workspace_id,
            plant_id=mission.scope.plant_id,
            event_type="MISSION_CREATED",
            result="SUCCESS",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={
                "mission_type": mission.mission_type.value,
                "step_count": len(mission.planned_steps),
                "has_errors": len(errors) > 0,
            },
        )

        request_hash = self._hash_request_payload(request) if request.idempotency_key else None

        persisted = self.repository.create_mission(
            mission=mission,
            change_reason="Initial mission proposal draft created.",
            audit_event=audit_event,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )

        return persisted

    def get_mission(
        self,
        identity: Identity,
        mission_id: str,
    ) -> Mission:
        """Retrieves a mission within caller's authoritative scope."""
        self._validate_scope_authority(identity)

        mission = self.repository.get_mission(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
        )

        if not mission:
            raise MissionNotFoundError(f"Mission '{mission_id}' not found within authorized scope.")

        self._validate_scope_authority(identity, mission.scope.plant_id)
        return mission

    def list_missions(
        self,
        identity: Identity,
        plant_id: Optional[str] = None,
        status: Optional[MissionStatus] = None,
        mission_type: Optional[MissionType] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Mission], int]:
        """Lists missions for caller's tenant and workspace."""
        self._validate_scope_authority(identity, plant_id)

        missions, total = self.repository.list_missions(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=plant_id,
            status=status,
            mission_type=mission_type,
            limit=limit,
            offset=offset,
        )

        # Filter by plant assignment if caller is restricted
        assigned = getattr(identity, "assigned_plants", ["*"]) or ["*"]
        if "*" not in assigned:
            missions = [m for m in missions if m.scope.plant_id in assigned]
            total = len(missions)

        return missions, total

    def update_mission_draft(
        self,
        identity: Identity,
        mission_id: str,
        request: MissionUpdateRequest,
        expected_revision: Optional[int] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Mission:
        """
        Updates an editable mission draft.
        Fails if mission has already progressed to VALIDATED, REVIEW_REQUIRED, or ACCEPTED.
        """
        current = self.get_mission(identity, mission_id)

        if current.status not in (MissionStatus.DRAFT, MissionStatus.PROPOSED, MissionStatus.REJECTED):
            raise MissionLifecycleError(
                f"Mission '{mission_id}' in status '{current.status.value}' cannot be edited directly. "
                "Only DRAFT, PROPOSED, or REJECTED missions may be updated."
            )

        # Apply updates
        if request.title is not None:
            current.title = request.title
        if request.description is not None:
            current.description = request.description
        if request.objective is not None:
            current.objective = request.objective
        if request.constraints is not None:
            current.constraints = request.constraints
        if request.success_criteria is not None:
            current.success_criteria = request.success_criteria
        if request.planned_steps is not None:
            current.planned_steps = request.planned_steps
        if request.evidence_requirements is not None:
            current.evidence_requirements = request.evidence_requirements
        if request.related_resources is not None:
            current.related_resources = request.related_resources

        # Re-validate
        is_valid, errors, warnings = self.validate_mission_structure(current)
        current.validation_errors = errors
        current.validation_warnings = warnings

        # Audit record
        audit_event = MissionAuditRecord(
            mission_id=current.mission_id,
            revision=current.revision + 1,
            tenant_id=current.scope.tenant_id,
            workspace_id=current.scope.workspace_id,
            plant_id=current.scope.plant_id,
            event_type="MISSION_REVISION_CREATED",
            result="SUCCESS",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={"change_reason": request.update_reason},
        )

        rev_to_check = expected_revision if expected_revision is not None else current.revision
        updated = self.repository.update_mission(
            mission=current,
            expected_revision=rev_to_check,
            change_reason=request.update_reason,
            changed_by=identity.user_id,
            audit_event=audit_event,
        )

        return updated

    def validate_mission(
        self,
        identity: Identity,
        mission_id: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> MissionValidationResponse:
        """
        Executes deterministic domain and DAG validation.
        Transitions mission status to VALIDATED if passes; records errors and returns response.
        """
        current = self.get_mission(identity, mission_id)

        is_valid, errors, warnings = self.validate_mission_structure(current)
        current.validation_errors = errors
        current.validation_warnings = warnings

        old_status = current.status
        if is_valid:
            if is_valid_lifecycle_transition(current.status, MissionStatus.VALIDATED):
                current.status = MissionStatus.VALIDATED
            event_type = "MISSION_VALIDATION_SUCCEEDED"
            result = "SUCCESS"
        else:
            # Remain in draft / proposed if validation failed
            event_type = "MISSION_VALIDATION_FAILED"
            result = "FAILURE"

        audit_event = MissionAuditRecord(
            mission_id=current.mission_id,
            revision=current.revision + 1,
            tenant_id=current.scope.tenant_id,
            workspace_id=current.scope.workspace_id,
            plant_id=current.scope.plant_id,
            event_type=event_type,
            result=result,
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={
                "errors": errors,
                "warnings": warnings,
                "old_status": old_status.value,
                "new_status": current.status.value,
            },
        )

        self.repository.update_mission(
            mission=current,
            expected_revision=current.revision,
            change_reason=f"Validation run: {'Passed' if is_valid else 'Failed with errors'}",
            changed_by=identity.user_id,
            audit_event=audit_event,
        )

        total_deps = sum(len(s.depends_on) for s in current.planned_steps)

        return MissionValidationResponse(
            mission_id=current.mission_id,
            is_valid=is_valid,
            status=current.status,
            errors=errors,
            warnings=warnings,
            step_count=len(current.planned_steps),
            dependency_count=total_deps,
        )

    def submit_for_review(
        self,
        identity: Identity,
        mission_id: str,
        submission_notes: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Mission:
        """
        Submits a validated mission for governance review.
        Fails if mission has not successfully passed domain validation.
        """
        current = self.get_mission(identity, mission_id)

        if current.status != MissionStatus.VALIDATED:
            raise MissionLifecycleError(
                f"Mission '{mission_id}' in status '{current.status.value}' cannot be submitted for review. "
                "Missions must be in VALIDATED state before submission."
            )

        if not is_valid_lifecycle_transition(current.status, MissionStatus.REVIEW_REQUIRED):
            raise MissionLifecycleError(
                f"Invalid transition from '{current.status.value}' to 'REVIEW_REQUIRED'."
            )

        current.status = MissionStatus.REVIEW_REQUIRED
        current.review_notes = submission_notes

        audit_event = MissionAuditRecord(
            mission_id=current.mission_id,
            revision=current.revision + 1,
            tenant_id=current.scope.tenant_id,
            workspace_id=current.scope.workspace_id,
            plant_id=current.scope.plant_id,
            event_type="MISSION_SUBMITTED_FOR_REVIEW",
            result="SUCCESS",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={"submission_notes": submission_notes},
        )

        updated = self.repository.update_mission(
            mission=current,
            expected_revision=current.revision,
            change_reason="Submitted for governance review.",
            changed_by=identity.user_id,
            audit_event=audit_event,
        )

        return updated

    def review_mission(
        self,
        identity: Identity,
        mission_id: str,
        request: MissionReviewRequest,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Mission:
        """
        Accepts or rejects a mission in REVIEW_REQUIRED status.
        Does NOT authorize direct execution.
        """
        current = self.get_mission(identity, mission_id)

        if current.status != MissionStatus.REVIEW_REQUIRED:
            raise MissionLifecycleError(
                f"Mission '{mission_id}' in status '{current.status.value}' cannot be reviewed. "
                "Only missions in REVIEW_REQUIRED status may be accepted or rejected."
            )

        target_status = MissionStatus.ACCEPTED if request.action == "ACCEPT" else MissionStatus.REJECTED

        if not is_valid_lifecycle_transition(current.status, target_status):
            raise MissionLifecycleError(
                f"Invalid transition from '{current.status.value}' to '{target_status.value}'."
            )

        now = datetime.now(timezone.utc).isoformat()
        current.status = target_status
        current.review_notes = request.review_notes
        current.reviewed_by = identity.user_id
        current.reviewed_at = now

        event_type = "MISSION_ACCEPTED" if request.action == "ACCEPT" else "MISSION_REJECTED"

        audit_event = MissionAuditRecord(
            mission_id=current.mission_id,
            revision=current.revision + 1,
            tenant_id=current.scope.tenant_id,
            workspace_id=current.scope.workspace_id,
            plant_id=current.scope.plant_id,
            event_type=event_type,
            result="SUCCESS",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={
                "action": request.action,
                "review_notes": request.review_notes,
            },
        )

        updated = self.repository.update_mission(
            mission=current,
            expected_revision=current.revision,
            change_reason=f"Governance review decided: {request.action}.",
            changed_by=identity.user_id,
            audit_event=audit_event,
        )

        return updated

    def cancel_mission(
        self,
        identity: Identity,
        mission_id: str,
        cancel_reason: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Mission:
        """
        Cancels an industrial mission from any non-terminal state.
        """
        current = self.get_mission(identity, mission_id)

        if current.status == MissionStatus.CANCELLED:
            return current

        if not is_valid_lifecycle_transition(current.status, MissionStatus.CANCELLED):
            raise MissionLifecycleError(
                f"Mission '{mission_id}' in status '{current.status.value}' cannot be cancelled."
            )

        current.status = MissionStatus.CANCELLED
        current.review_notes = f"Cancelled: {cancel_reason}"

        audit_event = MissionAuditRecord(
            mission_id=current.mission_id,
            revision=current.revision + 1,
            tenant_id=current.scope.tenant_id,
            workspace_id=current.scope.workspace_id,
            plant_id=current.scope.plant_id,
            event_type="MISSION_CANCELLED",
            result="SUCCESS",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={"cancel_reason": cancel_reason},
        )

        updated = self.repository.update_mission(
            mission=current,
            expected_revision=current.revision,
            change_reason=f"Mission cancelled: {cancel_reason}",
            changed_by=identity.user_id,
            audit_event=audit_event,
        )

        return updated

    def get_revisions(
        self,
        identity: Identity,
        mission_id: str,
    ) -> List[MissionRevisionRecord]:
        """Retrieves revision snapshots within caller's scope."""
        self.get_mission(identity, mission_id)  # Validate access
        return self.repository.get_revisions(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
        )

    def get_audit_ledger(
        self,
        identity: Identity,
        mission_id: str,
        limit: int = 50,
    ) -> List[MissionAuditRecord]:
        """Retrieves audit trail within caller's scope."""
        self.get_mission(identity, mission_id)  # Validate access
        return self.repository.get_audit_ledger(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
            limit=limit,
        )


# Global singleton instance
mission_service = MissionService()
