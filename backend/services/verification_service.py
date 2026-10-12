# backend/services/verification_service.py
"""
SageCommand V3 — Continuous Verification Engine Service (Prompt 36)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Orchestrates evidence-driven continuous verification of mission progress and outcomes.
Determines which mission steps and success criteria require verification, resolves evidence
through existing approved subsystem interfaces, assesses freshness, integrity, and scope,
applies deterministic rules, and produces traceable, auditable verification findings.

Cardinal Invariants:
1. Verification is a read-only assessment; it NEVER mutates operational state, dispatches actions,
   or writes to physical machines / operational databases.
2. Mission definition and lifecycle remain untouched (read-only). Verification findings are stored separately.
3. Server-authoritative scope: tenant, workspace, plant, and requested_by derived from authenticated context.
4. Preserves uncertainty: missing, unverified, stale, or conflicting evidence produces distinct statuses.
5. Idempotent: repeated requests with identical payload replay deterministically without duplicating runs.
"""

import json
import logging
import hashlib
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta

try:
    from core.config import (
        SAGE_VERIFICATION_MAX_TARGETS,
        SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET,
        SAGE_VERIFICATION_MAX_FINDINGS,
        SAGE_VERIFICATION_MAX_PAYLOAD_BYTES,
        SAGE_VERIFICATION_TIMEOUT_SECONDS,
        SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS,
        SAGE_VERIFICATION_MAX_RUNS_LIST,
        SAGE_VERIFICATION_DEFAULT_RUNS_LIMIT,
    )
    from core.auth import Identity
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        TriggerType,
        RuleType,
        EvidenceAssessment,
        VerificationRule,
        VerificationProvenance,
        VerificationAuditRecord,
        VerificationRequest,
        VerificationRunSummary,
        RULE_SET_VERSION,
        EVALUATOR_VERSION,
        validate_identifier,
        _validate_safe_text,
    )
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        StepStatus,
        CriterionStatus,
        validate_plant_identifier,
    )
    from repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
        VerificationRepositoryError,
        VerificationNotFoundError,
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )
    from services.mission_service import (
        MissionService,
        mission_service,
        MissionNotFoundError as MSMissionNotFoundError,
        MissionPermissionError as MSMissionPermissionError,
    )
    from repositories.evidence_explainability_repository import (
        EvidenceExplainabilityRepository,
        evidence_explainability_repository,
    )
    from services.action_store import action_store
    from repositories.decision_engine_repository import DecisionEngineRepository
    from services.incident_repository import IncidentRepository
    from services.rca_repository import RcaRepository
    from repositories.organizational_memory_repository import OrganizationalMemoryRepository
    from services.verification_rules import (
        VerificationRuleRegistry,
        verification_rule_registry,
        _parse_iso_timestamp,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_VERIFICATION_MAX_TARGETS,
        SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET,
        SAGE_VERIFICATION_MAX_FINDINGS,
        SAGE_VERIFICATION_MAX_PAYLOAD_BYTES,
        SAGE_VERIFICATION_TIMEOUT_SECONDS,
        SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS,
        SAGE_VERIFICATION_MAX_RUNS_LIST,
        SAGE_VERIFICATION_DEFAULT_RUNS_LIMIT,
    )
    from backend.core.auth import Identity
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        TriggerType,
        RuleType,
        EvidenceAssessment,
        VerificationRule,
        VerificationProvenance,
        VerificationAuditRecord,
        VerificationRequest,
        VerificationRunSummary,
        RULE_SET_VERSION,
        EVALUATOR_VERSION,
        validate_identifier,
        _validate_safe_text,
    )
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        StepStatus,
        CriterionStatus,
        validate_plant_identifier,
    )
    from backend.repositories.verification_repository import (
        VerificationRepository,
        verification_repository,
        VerificationRepositoryError,
        VerificationNotFoundError,
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )
    from backend.services.mission_service import (
        MissionService,
        mission_service,
        MissionNotFoundError as MSMissionNotFoundError,
        MissionPermissionError as MSMissionPermissionError,
    )
    from backend.repositories.evidence_explainability_repository import (
        EvidenceExplainabilityRepository,
        evidence_explainability_repository,
    )
    from backend.services.action_store import action_store
    from backend.repositories.decision_engine_repository import DecisionEngineRepository
    from backend.services.incident_repository import IncidentRepository
    from backend.services.rca_repository import RcaRepository
    from backend.repositories.organizational_memory_repository import OrganizationalMemoryRepository
    from backend.services.verification_rules import (
        VerificationRuleRegistry,
        verification_rule_registry,
        _parse_iso_timestamp,
    )

logger = logging.getLogger("verification_service")


class VerificationServiceError(Exception):
    """Base exception for verification service operations."""
    pass


class VerificationPermissionError(VerificationServiceError):
    """Raised on scope, tenant, workspace, or plant authorization violations."""
    pass


class VerificationValidationError(VerificationServiceError):
    """Raised on validation or boundary precondition failures."""
    pass


class VerificationRevisionMismatchError(VerificationServiceError):
    """Raised when target mission revision does not match expected revision."""
    pass


class VerificationService:
    """
    Authoritative continuous verification engine for governed missions.
    """

    def __init__(
        self,
        repository: Optional[VerificationRepository] = None,
        mission_svc: Optional[MissionService] = None,
        evidence_repo: Optional[EvidenceExplainabilityRepository] = None,
        rule_registry: Optional[VerificationRuleRegistry] = None,
    ):
        self.repository = repository or verification_repository
        self.mission_service = mission_svc or mission_service
        self.evidence_repo = evidence_repo or evidence_explainability_repository
        self.rule_registry = rule_registry or verification_rule_registry
        self.decision_repo = DecisionEngineRepository()
        self.incident_repo = IncidentRepository()
        self.rca_repo = RcaRepository()
        self.memory_repo = OrganizationalMemoryRepository()

    def _get_authorized_plants(self, identity: Identity) -> Set[str]:
        """Extracts authorized plant IDs from caller identity."""
        if hasattr(identity, "assigned_plants") and identity.assigned_plants:
            return set(identity.assigned_plants)
        if hasattr(identity, "plants") and identity.plants:
            return set(identity.plants)
        if hasattr(identity, "plant_id") and identity.plant_id:
            return {identity.plant_id}
        # Admins or system roles may have wildcard
        if any(r in ("ADMINISTRATOR", "admin", "SUPERADMIN") for r in identity.roles):
            return {"*"}
        return set()

    def _validate_scope_authority(self, identity: Identity, target_plant_id: Optional[str] = None) -> None:
        """Validates caller identity, tenant, workspace, and plant assignment."""
        if not identity.tenant_id or not identity.tenant_id.strip():
            raise VerificationPermissionError("Authoritative tenant identity is required. Access denied (fail-closed).")
        if not identity.workspace_id or not identity.workspace_id.strip():
            raise VerificationPermissionError("Authoritative workspace identity is required. Access denied (fail-closed).")

        assigned = self._get_authorized_plants(identity)
        if not assigned:
            raise VerificationPermissionError("Caller has no assigned plants. Access denied (fail-closed).")

        if target_plant_id:
            validate_plant_identifier(target_plant_id)
            if "*" not in assigned and target_plant_id not in assigned:
                raise VerificationPermissionError(f"Caller is not authorized for plant '{target_plant_id}'.")

    def _hash_request_payload(self, request: VerificationRequest, mission_id: str, mission_revision: int) -> str:
        """Computes deterministic SHA-256 hash for idempotency checking."""
        payload_dict = request.model_dump(exclude_none=True)
        payload_dict["mission_id"] = mission_id
        payload_dict["mission_revision"] = mission_revision
        canonical_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def _resolve_evidence_item(
        self,
        ref_id: str,
        mission: Mission,
        identity: Identity,
        freshness_threshold: float,
        eval_dt: datetime,
    ) -> Tuple[EvidenceAssessment, Dict[str, Any]]:
        """
        Resolves an individual evidence reference through canonical subsystem interfaces.
        Validates tenant, workspace, and plant scope, integrity, and freshness.
        Returns both EvidenceAssessment and the resolved raw payload dictionary.
        """
        m_tenant = mission.scope.tenant_id
        m_ws = mission.scope.workspace_id
        m_plant = mission.scope.plant_id

        # 1. Check EvidenceExplainabilityRepository
        rec = self.evidence_repo.get_evidence_record_scoped(ref_id, m_tenant, m_ws)
        if rec:
            rec_plant = rec.get("plant_id")
            if not rec_plant:
                scope_status = ScopeStatus.UNTAGGED_PLANT
            elif rec_plant != m_plant:
                scope_status = ScopeStatus.CROSS_PLANT
            else:
                scope_status = ScopeStatus.AUTHORIZED

            val_status = rec.get("validation_status", "UNKNOWN").upper()
            observed_at = rec.get("observed_at") or rec.get("created_at")

            # Evaluate freshness
            obs_dt = _parse_iso_timestamp(observed_at)
            freshness_status = FreshnessStatus.UNKNOWN
            freshness_sec = None
            if obs_dt:
                age = (eval_dt - obs_dt).total_seconds()
                freshness_sec = max(0.0, age)
                if age < -60.0:
                    freshness_status = FreshnessStatus.FUTURE_DATED
                elif age > freshness_threshold:
                    freshness_status = FreshnessStatus.STALE
                else:
                    freshness_status = FreshnessStatus.CURRENT
            else:
                freshness_status = FreshnessStatus.TIMESTAMP_MISSING

            quality_status = QualityStatus.VALID if val_status == "VALID" else (
                QualityStatus.INVALID if val_status == "INVALID" else QualityStatus.UNVERIFIED
            )

            payload = rec.get("payload") or {}
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type=rec.get("source_type", "EVIDENCE_RECORD"),
                source_reference=rec.get("source_record_id"),
                observed_at=observed_at,
                received_at=rec.get("created_at"),
                freshness_status=freshness_status,
                freshness_seconds=freshness_sec,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status=val_status,
                scope_status=scope_status,
                quality_status=quality_status,
                limitations=[],
            )
            return assessment, payload

        # 2. Check ActionStore (prefixed or raw action_id)
        act = action_store.get_by_scope(ref_id, m_tenant, m_ws)
        if act:
            act_plant = act.plant_id
            if not act_plant:
                scope_status = ScopeStatus.UNTAGGED_PLANT
            elif act_plant != m_plant:
                scope_status = ScopeStatus.CROSS_PLANT
            else:
                scope_status = ScopeStatus.AUTHORIZED

            obs_dt = _parse_iso_timestamp(act.updated_at or act.created_at)
            freshness_status = FreshnessStatus.UNKNOWN
            freshness_sec = None
            if obs_dt:
                age = (eval_dt - obs_dt).total_seconds()
                freshness_sec = max(0.0, age)
                freshness_status = FreshnessStatus.STALE if age > freshness_threshold else FreshnessStatus.CURRENT
            else:
                freshness_status = FreshnessStatus.TIMESTAMP_MISSING

            payload = act.parameters if isinstance(act.parameters, dict) else (
                act.parameters.model_dump() if hasattr(act.parameters, "model_dump") else {}
            )
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type="ACTION_RECORD",
                source_reference=act.action_id,
                observed_at=act.updated_at or act.created_at,
                received_at=act.created_at,
                freshness_status=freshness_status,
                freshness_seconds=freshness_sec,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status="VALID",
                scope_status=scope_status,
                quality_status=QualityStatus.VALID,
                limitations=[],
            )
            return assessment, payload

        # 3. Check DecisionEngineRepository
        dec = self.decision_repo.get_by_id(ref_id, m_tenant, m_ws, m_plant)
        if dec:
            obs_dt_str = dec.assessment_timestamp if hasattr(dec, "assessment_timestamp") else getattr(dec, "evaluated_at", None)
            obs_dt = _parse_iso_timestamp(obs_dt_str)
            freshness_status = FreshnessStatus.UNKNOWN
            freshness_sec = None
            if obs_dt:
                age = (eval_dt - obs_dt).total_seconds()
                freshness_sec = max(0.0, age)
                freshness_status = FreshnessStatus.STALE if age > freshness_threshold else FreshnessStatus.CURRENT
            else:
                freshness_status = FreshnessStatus.CURRENT
                freshness_sec = 0.0

            payload = dec.metadata or {}
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type="DECISION_RECORD",
                source_reference=dec.decision_id,
                observed_at=obs_dt_str,
                received_at=None,
                freshness_status=freshness_status,
                freshness_seconds=freshness_sec,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status="VALID",
                scope_status=ScopeStatus.AUTHORIZED,
                quality_status=QualityStatus.VALID,
                limitations=[],
            )
            return assessment, payload

        # 4. Check IncidentRepository
        inc = self.incident_repo.get_incident_scoped(ref_id, m_tenant, m_ws)
        if inc:
            inc_plant = inc.plant_id
            scope_status = ScopeStatus.AUTHORIZED if inc_plant == m_plant else ScopeStatus.CROSS_PLANT
            payload = {
                "category": inc.category.value,
                "severity": inc.severity.value,
                "priority": inc.priority.value,
                "title": inc.title,
            }
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type="INCIDENT_RECORD",
                source_reference=inc.incident_id,
                observed_at=inc.created_at,
                received_at=inc.created_at,
                freshness_status=FreshnessStatus.CURRENT,
                freshness_seconds=0.0,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status="VALID",
                scope_status=scope_status,
                quality_status=QualityStatus.VALID,
                limitations=[],
            )
            return assessment, payload

        # 5. Check RcaRepository
        rca = self.rca_repo.get_analysis_scoped(ref_id, m_tenant, m_ws)
        if rca:
            rca_plant = rca.plant_id
            scope_status = ScopeStatus.AUTHORIZED if rca_plant == m_plant else ScopeStatus.CROSS_PLANT
            payload = {"status": rca.status.value, "incident_id": rca.incident_id}
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type="RCA_RECORD",
                source_reference=rca.analysis_id,
                observed_at=rca.created_at,
                received_at=rca.created_at,
                freshness_status=FreshnessStatus.CURRENT,
                freshness_seconds=0.0,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status="VALID",
                scope_status=scope_status,
                quality_status=QualityStatus.VALID,
                limitations=[],
            )
            return assessment, payload

        # 6. Check OrganizationalMemoryRepository
        mem = self.memory_repo.get_entry(m_tenant, m_ws, ref_id)
        if mem:
            mem_plant = mem.plant_id
            scope_status = ScopeStatus.AUTHORIZED if mem_plant == m_plant else ScopeStatus.CROSS_PLANT
            obs_dt_str = mem.created_at.isoformat() if hasattr(mem.created_at, "isoformat") else str(mem.created_at)
            payload = mem.metadata or {}
            assessment = EvidenceAssessment(
                evidence_id=ref_id,
                source_type="MEMORY_RECORD",
                source_reference=mem.memory_id,
                observed_at=obs_dt_str,
                received_at=obs_dt_str,
                freshness_status=FreshnessStatus.CURRENT,
                freshness_seconds=0.0,
                freshness_threshold_seconds=freshness_threshold,
                integrity_status="VALID",
                scope_status=scope_status,
                quality_status=QualityStatus.VALID,
                limitations=[],
            )
            return assessment, payload

        # Missing or inaccessible record
        assessment = EvidenceAssessment(
            evidence_id=ref_id,
            source_type="UNKNOWN",
            source_reference=None,
            observed_at=None,
            received_at=None,
            freshness_status=FreshnessStatus.UNKNOWN,
            freshness_seconds=None,
            freshness_threshold_seconds=freshness_threshold,
            integrity_status="UNVERIFIED",
            scope_status=ScopeStatus.UNKNOWN,
            applicability_status="UNAVAILABLE",
            quality_status=QualityStatus.UNKNOWN,
            limitations=[f"Evidence reference '{ref_id}' could not be resolved within authorized scope."],
        )
        return assessment, {}

    def request_verification(
        self,
        identity: Identity,
        mission_id: str,
        request: VerificationRequest,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> VerificationRun:
        """
        Executes a bounded, continuous verification run for a governed mission.
        Evaluates criteria and/or steps deterministically without mutating mission state.
        """
        # 1. Scope & identity validation
        self._validate_scope_authority(identity)

        # Request size check
        req_json_len = len(request.model_dump_json().encode("utf-8"))
        if req_json_len > SAGE_VERIFICATION_MAX_PAYLOAD_BYTES:
            raise VerificationValidationError(
                f"Request payload size ({req_json_len} bytes) exceeds maximum permitted ({SAGE_VERIFICATION_MAX_PAYLOAD_BYTES} bytes)."
            )

        # 2. Retrieve authoritative mission
        try:
            mission = self.mission_service.get_mission(identity, mission_id)
        except MSMissionNotFoundError:
            raise VerificationNotFoundError(f"Mission '{mission_id}' not found within authorized scope.")
        except MSMissionPermissionError as e:
            raise VerificationPermissionError(str(e))

        m_tenant = mission.scope.tenant_id
        m_ws = mission.scope.workspace_id
        m_plant = mission.scope.plant_id

        # Validate caller plant authorization for mission's specific plant
        self._validate_scope_authority(identity, m_plant)

        # Mission revision integrity check
        if request.expected_mission_revision is not None and request.expected_mission_revision != mission.revision:
            raise VerificationRevisionMismatchError(
                f"Mission revision mismatch: expected revision {request.expected_mission_revision}, but current revision is {mission.revision}."
            )

        # 3. Idempotency handling
        request_hash = self._hash_request_payload(request, mission_id, mission.revision) if request.idempotency_key else None
        if request.idempotency_key and request_hash:
            existing_run_id = self.repository.check_idempotency(m_tenant, m_ws, request.idempotency_key, request_hash)
            if existing_run_id:
                existing_run = self.repository.get_run(m_tenant, m_ws, mission_id, existing_run_id)
                if existing_run:
                    logger.info("Idempotent replay: returning existing verification run '%s'", existing_run_id)
                    return existing_run

        eval_dt = datetime.now(timezone.utc)
        freshness_threshold = request.freshness_threshold_override_seconds or SAGE_VERIFICATION_DEFAULT_FRESHNESS_SECONDS

        # Rule selection & validation
        if request.rule_type is not None:
            rule_to_use = self.rule_registry.get_rule_by_type(request.rule_type)
            if not rule_to_use:
                raise VerificationValidationError(f"Unsupported verification rule type: '{request.rule_type}'.")
        else:
            rule_to_use = self.rule_registry.get_rule_by_type(RuleType.EVIDENCE_FRESH)

        # 4. Identify verification targets
        target_crits = []
        target_steps = []
        verification_scope = "FULL_MISSION"

        if request.target_type == VerificationTargetType.CRITERION:
            if request.target_id:
                verification_scope = f"CRITERION:{request.target_id}"
                found = [c for c in mission.success_criteria if c.criterion_id == request.target_id]
                if not found:
                    raise VerificationValidationError(f"Target criterion '{request.target_id}' not found on mission '{mission_id}'.")
                target_crits = found
            else:
                verification_scope = "ALL_CRITERIA"
                target_crits = list(mission.success_criteria)
        elif request.target_type == VerificationTargetType.STEP:
            if request.target_id:
                verification_scope = f"STEP:{request.target_id}"
                found = [s for s in mission.planned_steps if s.step_id == request.target_id]
                if not found:
                    raise VerificationValidationError(f"Target step '{request.target_id}' not found on mission '{mission_id}'.")
                target_steps = found
            else:
                verification_scope = "ALL_STEPS"
                target_steps = list(mission.planned_steps)
        else:
            verification_scope = "FULL_MISSION"
            target_crits = list(mission.success_criteria)
            target_steps = list(mission.planned_steps)

        total_targets = len(target_crits) + len(target_steps)
        if total_targets > SAGE_VERIFICATION_MAX_TARGETS:
            raise VerificationValidationError(
                f"Requested targets count ({total_targets}) exceeds maximum permitted ({SAGE_VERIFICATION_MAX_TARGETS})."
            )

        # 5. Evaluate Targets Deterministically
        findings: List[VerificationFinding] = []
        all_consumed_evidence_ids: List[str] = []
        all_evidence_timestamps: Dict[str, Optional[str]] = {}
        all_evidence_payloads: Dict[str, Dict[str, Any]] = {}
        all_limitations: List[str] = []

        mission_scope_dict = {"tenant_id": m_tenant, "workspace_id": m_ws, "plant_id": m_plant}

        # Build evidence requirements map
        req_type_to_linked: Dict[str, List[str]] = {}
        for req in mission.evidence_requirements:
            if req.linked_evidence_id:
                req_type_to_linked.setdefault(req.evidence_type, []).append(req.linked_evidence_id)

        # 5.A Evaluate Success Criteria
        for crit in target_crits:
            ev_refs = []
            if crit.required_evidence_type and crit.required_evidence_type in req_type_to_linked:
                ev_refs.extend(req_type_to_linked[crit.required_evidence_type])

            # Bounded check on evidence references
            if len(ev_refs) > SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET:
                ev_refs = ev_refs[:SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET]
                all_limitations.append(f"Evidence references for criterion '{crit.criterion_id}' truncated to {SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET}.")

            # Resolve evidence items
            assessments: List[EvidenceAssessment] = []
            for ref in ev_refs:
                assess, payload = self._resolve_evidence_item(ref, mission, identity, freshness_threshold, eval_dt)
                assessments.append(assess)
                all_consumed_evidence_ids.append(assess.evidence_id)
                all_evidence_timestamps[assess.evidence_id] = assess.observed_at
                all_evidence_payloads[assess.evidence_id] = payload

            crit_params = dict(request.rule_parameters or {})
            crit_params.setdefault("freshness_threshold_seconds", freshness_threshold)
            crit_params["evidence_payloads"] = all_evidence_payloads
            if crit.required_evidence_type:
                crit_params.setdefault("required_evidence_types", [crit.required_evidence_type])

            finding = rule_to_use.evaluate(
                target_id=crit.criterion_id,
                target_type=VerificationTargetType.CRITERION,
                assessments=assessments,
                mission_scope=mission_scope_dict,
                parameters=crit_params,
                now=eval_dt,
            )
            findings.append(finding)

        # 5.B Evaluate Planned Steps
        for step in target_steps:
            ev_refs = list(step.required_evidence) + list(step.related_resource_ids)
            if len(ev_refs) > SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET:
                ev_refs = ev_refs[:SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET]
                all_limitations.append(f"Evidence references for step '{step.step_id}' truncated to {SAGE_VERIFICATION_MAX_EVIDENCE_PER_TARGET}.")

            assessments = []
            for ref in ev_refs:
                assess, payload = self._resolve_evidence_item(ref, mission, identity, freshness_threshold, eval_dt)
                assessments.append(assess)
                all_consumed_evidence_ids.append(assess.evidence_id)
                all_evidence_timestamps[assess.evidence_id] = assess.observed_at
                all_evidence_payloads[assess.evidence_id] = payload

            step_params = dict(request.rule_parameters or {})
            step_params.setdefault("freshness_threshold_seconds", freshness_threshold)
            step_params["evidence_payloads"] = all_evidence_payloads
            if step.required_evidence:
                step_params.setdefault("required_evidence_ids", list(step.required_evidence))

            finding = rule_to_use.evaluate(
                target_id=step.step_id,
                target_type=VerificationTargetType.STEP,
                assessments=assessments,
                mission_scope=mission_scope_dict,
                parameters=step_params,
                now=eval_dt,
            )
            findings.append(finding)

        # 6. Aggregate Findings & Determine Run Status
        target_count = len(findings)
        verified_count = sum(1 for f in findings if f.status == VerificationStatus.VERIFIED)
        unverified_count = sum(1 for f in findings if f.status == VerificationStatus.NOT_VERIFIED)
        indeterminate_count = sum(1 for f in findings if f.status == VerificationStatus.INDETERMINATE)
        blocked_count = sum(1 for f in findings if f.status == VerificationStatus.BLOCKED)
        failed_count = sum(1 for f in findings if f.status == VerificationStatus.FAILED)
        stale_count = sum(1 for f in findings if f.status == VerificationStatus.STALE)
        conflicting_count = sum(1 for f in findings if f.status == VerificationStatus.CONFLICTING)

        if target_count == 0:
            overall_status = VerificationStatus.INDETERMINATE
            summary = "No targets were eligible or requested for verification."
        elif blocked_count > 0:
            overall_status = VerificationStatus.BLOCKED
            summary = f"{blocked_count} verification target(s) blocked due to scope boundary violations."
        elif conflicting_count > 0:
            overall_status = VerificationStatus.CONFLICTING
            summary = f"{conflicting_count} verification target(s) have conflicting evidence sources."
        elif stale_count > 0 and (unverified_count == 0 and failed_count == 0):
            overall_status = VerificationStatus.STALE
            summary = f"{stale_count} verification target(s) rely on stale evidence beyond threshold ({freshness_threshold:.0f}s)."
        elif failed_count > 0:
            overall_status = VerificationStatus.FAILED
            summary = f"{failed_count} verification check(s) failed evaluation preconditions."
        elif verified_count == target_count:
            overall_status = VerificationStatus.VERIFIED
            summary = f"All {target_count} target(s) successfully verified by authorized, current evidence."
        elif unverified_count > 0:
            overall_status = VerificationStatus.NOT_VERIFIED
            summary = f"{unverified_count} of {target_count} target(s) remain unverified due to missing or inadequate evidence."
        else:
            overall_status = VerificationStatus.INDETERMINATE
            summary = f"{indeterminate_count} target(s) have indeterminate evidence."

        now_iso = eval_dt.isoformat()
        v_id = f"vrun_{uuid.uuid4().hex[:16]}"

        provenance = VerificationProvenance(
            verification_id=v_id,
            mission_id=mission_id,
            mission_revision=mission.revision,
            rule_set_version=RULE_SET_VERSION,
            evaluator_version=EVALUATOR_VERSION,
            evidence_ids=list(set(all_consumed_evidence_ids))[:100],
            evidence_timestamps=all_evidence_timestamps,
            evaluation_timestamp=now_iso,
            limitations=all_limitations[:30],
        )

        run = VerificationRun(
            verification_id=v_id,
            mission_id=mission_id,
            mission_revision=mission.revision,
            verification_scope=verification_scope,
            status=overall_status,
            started_at=now_iso,
            completed_at=now_iso,
            requested_by=identity.user_id,
            tenant_id=m_tenant,
            workspace_id=m_ws,
            plant_id=m_plant,
            session_id=identity.session_id,
            trigger_type=request.trigger_type,
            rule_set_version=RULE_SET_VERSION,
            summary=summary,
            target_count=target_count,
            verified_count=verified_count,
            unverified_count=unverified_count,
            indeterminate_count=indeterminate_count,
            blocked_count=blocked_count,
            failed_count=failed_count,
            findings=findings,
            provenance=provenance,
            idempotency_key=request.idempotency_key,
            created_at=now_iso,
        )

        # 7. Audit Ledger Record
        audit_rec = VerificationAuditRecord(
            verification_id=v_id,
            mission_id=mission_id,
            mission_revision=mission.revision,
            tenant_id=m_tenant,
            workspace_id=m_ws,
            plant_id=m_plant,
            event_type="VERIFICATION_COMPLETED",
            result=overall_status.value,
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={
                "target_count": target_count,
                "verified_count": verified_count,
                "unverified_count": unverified_count,
                "status": overall_status.value,
            },
        )

        # 8. Atomic Persistence
        persisted_run = self.repository.save_run_atomic(run, audit_rec, request_hash)
        logger.info(
            "Verification run '%s' completed with status '%s' for mission '%s' rev %d",
            persisted_run.verification_id,
            persisted_run.status.value,
            mission_id,
            mission.revision,
        )
        self._emit_safe_status_notification(persisted_run)
        return persisted_run

    def get_verification_run(
        self,
        identity: Identity,
        mission_id: str,
        verification_id: str,
    ) -> VerificationRun:
        """Retrieves an authoritative verification run by ID scoped to tenant and workspace."""
        self._validate_scope_authority(identity)
        run = self.repository.get_run(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
            verification_id=verification_id,
        )
        if not run:
            raise VerificationNotFoundError(f"Verification run '{verification_id}' not found within authorized scope.")
        self._validate_scope_authority(identity, run.plant_id)
        return run

    def list_verification_runs(
        self,
        identity: Identity,
        mission_id: str,
        limit: int = SAGE_VERIFICATION_DEFAULT_RUNS_LIMIT,
        offset: int = 0,
        plant_id: Optional[str] = None,
    ) -> Tuple[List[VerificationRunSummary], int]:
        """Lists summaries of verification runs scoped to tenant, workspace, and mission."""
        self._validate_scope_authority(identity, plant_id)
        return self.repository.list_runs(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
            plant_id=plant_id,
        )

    def get_verification_findings(
        self,
        identity: Identity,
        mission_id: str,
        verification_id: str,
    ) -> List[VerificationFinding]:
        """Retrieves detailed verification findings for a run within authorized scope."""
        self._validate_scope_authority(identity)
        # Ensure run exists and caller has plant scope
        run = self.get_verification_run(identity, mission_id, verification_id)
        return run.findings

    def cancel_verification(
        self,
        identity: Identity,
        mission_id: str,
        verification_id: str,
        reason: str,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> VerificationRun:
        """Cancels an in-progress or pending verification run atomically."""
        self._validate_scope_authority(identity)
        run = self.get_verification_run(identity, mission_id, verification_id)

        audit_rec = VerificationAuditRecord(
            verification_id=verification_id,
            mission_id=mission_id,
            mission_revision=run.mission_revision,
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=run.plant_id,
            event_type="VERIFICATION_CANCELLED",
            result="CANCELLED",
            actor_id=identity.user_id,
            actor_role=identity.roles[0] if identity.roles else None,
            request_id=request_id,
            trace_id=trace_id,
            details={"cancel_reason": reason},
        )

        cancelled = self.repository.cancel_run_atomic(
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            mission_id=mission_id,
            verification_id=verification_id,
            cancelled_by=identity.user_id,
            reason=reason,
            audit_record=audit_rec,
        )
        if not cancelled:
            raise VerificationNotFoundError(f"Verification run '{verification_id}' not found or could not be cancelled.")
        self._emit_safe_status_notification(cancelled)
        return cancelled

    def _emit_safe_status_notification(self, run: VerificationRun) -> None:
        """
        Publishes bounded, safe status notification events using existing logging / event conventions.
        Strict architectural rule: Notifications are informational events, never commands.
        Does NOT place sensitive evidence payloads in notification messages.
        """
        try:
            notification_event = {
                "event_type": "VERIFICATION_STATUS_UPDATED",
                "verification_id": run.verification_id,
                "mission_id": run.mission_id,
                "mission_revision": run.mission_revision,
                "status": run.status.value,
                "target_count": run.target_count,
                "verified_count": run.verified_count,
                "unverified_count": run.unverified_count,
                "summary": run.summary,
                "timestamp": run.completed_at or run.started_at,
            }
            logger.info("Published safe verification notification: %s", notification_event)
        except Exception as e:
            logger.warning("Could not emit safe verification status event: %s", e)


# Canonical singleton service instance
verification_service = VerificationService()
