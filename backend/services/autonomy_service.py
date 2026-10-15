# backend/services/autonomy_service.py
"""
SageCommand V3 — Autonomy Levels & Guarded Delegation Foundation Service
Prompt 38 — Authoritative deterministic autonomy evaluation, capability registry,
grant lifecycle management, scope intersection enforcement, and tamper-evident decision ledger.

Cardinal Invariants:
1. An agent's ability to reason DOES NOT grant it operational authority.
2. Autonomy is a governed, server-authoritative boundary, NEVER a prompt instruction,
   LLM-generated decision, or client-asserted claim.
3. Level 4 (SUPERVISED_EXECUTION) and Level 5 (BOUNDED_AUTONOMY) are strictly DISABLED
   and NOT_IMPLEMENTED; operational execution endpoints remain non-existent.
4. Fail-closed: missing context, mismatched scopes, expired grants, or unknown capabilities
   immediately yield safe DENY or NOT_IMPLEMENTED decisions.
5. All autonomy evaluations produce tamper-evident, cryptographically hashed decisions.
"""

import logging
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple, Set, Union

try:
    from core.auth import Identity
    from governance.audit import log_security_event
    from services.authorization_service import authorization_service
    from data.schemas.authorization_contract import (
        AuthorizationContext,
        AuthorizationScope,
        AuthzDecisionEffect,
    )
    from data.schemas.autonomy_contract import (
        AutonomyLevel,
        AutonomyGrantStatus,
        SubjectType,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        AutonomyCapabilityDefinition,
        CapabilityRegistry,
        default_capability_registry,
        AutonomyScope,
        AutonomyConstraints,
        AutonomyProvenance,
        AutonomyGrant,
        AutonomyDecision,
        AutonomyGrantCreateRequest,
        AutonomyGrantUpdateRequest,
        AutonomyEvaluationRequest,
        MANDATORY_AUTONOMY_NOTICE,
    )
    from repositories.autonomy_repository import (
        AutonomyRepository,
        autonomy_repository,
        AutonomyRepositoryError,
        AutonomyNotFoundError,
        AutonomyConcurrencyError,
        AutonomyInvalidTransitionError,
        AutonomyIdempotencyConflictError,
    )
    from services.action_registry import action_registry
    from services.action_store import action_store
    from data.schemas.action_contract import ActionType, RiskLevel, ACTION_PARAMETER_SCHEMAS
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity
    from backend.governance.audit import log_security_event
    from backend.services.authorization_service import authorization_service
    from backend.data.schemas.authorization_contract import (
        AuthorizationContext,
        AuthorizationScope,
        AuthzDecisionEffect,
    )
    from backend.data.schemas.autonomy_contract import (
        AutonomyLevel,
        AutonomyGrantStatus,
        SubjectType,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        AutonomyCapabilityDefinition,
        CapabilityRegistry,
        default_capability_registry,
        AutonomyScope,
        AutonomyConstraints,
        AutonomyProvenance,
        AutonomyGrant,
        AutonomyDecision,
        AutonomyGrantCreateRequest,
        AutonomyGrantUpdateRequest,
        AutonomyEvaluationRequest,
        MANDATORY_AUTONOMY_NOTICE,
    )
    from backend.repositories.autonomy_repository import (
        AutonomyRepository,
        autonomy_repository,
        AutonomyRepositoryError,
        AutonomyNotFoundError,
        AutonomyConcurrencyError,
        AutonomyInvalidTransitionError,
        AutonomyIdempotencyConflictError,
    )
    from backend.services.action_registry import action_registry
    from backend.services.action_store import action_store
    from backend.data.schemas.action_contract import ActionType, RiskLevel, ACTION_PARAMETER_SCHEMAS

logger = logging.getLogger("autonomy_service")

# Server-authoritative capability categorization
ACTION_CAPABILITIES: Set[str] = {
    "PROPOSE_ACTION",
    "VALIDATE_ACTION",
    "PREPARE_APPROVAL_PACKAGE",
    "REQUEST_HUMAN_REVIEW",
    "VALIDATE_MISSION_DAG",
}

NON_ACTION_CAPABILITIES: Set[str] = {
    "OBSERVE_TELEMETRY",
    "READ_SENSOR_DATA",
    "READ_MISSION",
    "READ_ACTION",
    "ANALYZE_EVIDENCE",
    "CORRELATE_ANOMALIES",
    "ANALYZE_ROOT_CAUSE",
    "ESTIMATE_UNCERTAINTY",
    "GENERATE_RECOMMENDATION",
}


class AutonomyService:
    """
    Production Autonomy Evaluation and Guarded Delegation Service.
    Enforces deterministic capability allowlists, hierarchical scope containment,
    grant lifecycle verification, risk constraints, and underlying authorization integration.
    """

    def __init__(
        self,
        repository: Optional[AutonomyRepository] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
    ):
        self.repository = repository or autonomy_repository
        self.capability_registry = capability_registry or default_capability_registry

    def _resolve_caller_workspace(self, identity: Identity, requested_workspace: Optional[str] = None) -> Optional[str]:
        """
        Enforces workspace isolation across all autonomy operations.
        Derives caller's authoritative workspace from identity.
        Non-administrators are strictly confined to their authoritative workspace.
        """
        caller_ws = getattr(identity, "workspace_id", None) or "workspace_default"
        user_roles = [r.upper() for r in getattr(identity, "roles", [])]
        is_admin = bool({"ADMINISTRATOR", "ADMIN", "SECURITY_ADMIN"} & set(user_roles))

        if requested_workspace is not None and requested_workspace.strip() != "":
            clean_req = requested_workspace.strip()
            if clean_req == "*":
                if not is_admin:
                    raise AutonomyRepositoryError(
                        f"Cross-workspace violation: identity '{identity.user_id}' lacks administrator authority for wildcard workspace '*'. "
                        f"Confined to workspace '{caller_ws}'."
                    )
                return "*"
            if clean_req != caller_ws and not is_admin:
                raise AutonomyRepositoryError(
                    f"Cross-workspace access denied: identity '{identity.user_id}' is confined to workspace '{caller_ws}' "
                    f"and cannot access or manage workspace '{clean_req}'."
                )
            return clean_req
        if not is_admin:
            return caller_ws
        return None

    # =========================================================================
    # 1. DETERMINISTIC CAPABILITY EVALUATION ENGINE
    # =========================================================================

    def evaluate_autonomy(
        self,
        identity: Identity,
        subject_type: Union[SubjectType, str] = SubjectType.AGENT,
        subject_id: Optional[str] = None,
        requested_capability: Optional[str] = None,
        resource_scope: Optional[AutonomyScope] = None,
        data_mode: str = "SIMULATION",
        risk_context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        **kwargs: Any,
    ) -> AutonomyDecision:
        """
        Deterministically evaluates whether a subject is authorized to perform
        the requested capability within authoritative scope, data mode, and risk constraints.
        Follows strict fail-closed evaluation.
        """
        actual_subject_type = SubjectType.AGENT
        if isinstance(subject_type, SubjectType):
            actual_subject_type = subject_type
        elif isinstance(subject_type, str):
            try:
                actual_subject_type = SubjectType(subject_type.strip().upper())
            except ValueError:
                # String value was not a SubjectType enum (e.g. called as evaluate_autonomy(identity, "agent_id", "PROPOSE_ACTION", scope))
                if subject_id is not None and (requested_capability is None or isinstance(requested_capability, AutonomyScope)):
                    actual_subject_id = subject_type
                    actual_cap = subject_id
                    actual_scope = requested_capability
                    actual_data_mode = resource_scope if isinstance(resource_scope, str) else "SIMULATION"
                    actual_risk = data_mode if isinstance(data_mode, dict) else risk_context

                    actual_subject_type = SubjectType.AGENT
                    subject_id = actual_subject_id
                    requested_capability = actual_cap
                    resource_scope = actual_scope if isinstance(actual_scope, AutonomyScope) else AutonomyScope(tenant_id=identity.tenant_id)
                    data_mode = actual_data_mode
                    risk_context = actual_risk

        subject_type = actual_subject_type
        clean_subject_id = (subject_id or kwargs.get("subject") or "agent_default").strip()
        req_cap = (requested_capability or kwargs.get("capability") or "").strip().upper()
        if resource_scope is None:
            resource_scope = AutonomyScope(tenant_id=identity.tenant_id)
        norm_data_mode = data_mode.strip().upper() if isinstance(data_mode, str) else "SIMULATION"
        risk_ctx = risk_context or {}

        # The authenticated Identity.session_id is authoritative and exclusive
        caller_session = getattr(identity, "session_id", None)

        # Step 1: Caller Identity Active Status Check
        if identity.status.upper() != "ACTIVE":
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.IDENTITY_NOT_ACTIVE,
                reason=f"Identity '{identity.user_id}' account status is '{identity.status}'. Only ACTIVE identities are permitted.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 2: Tenant Isolation Check
        if identity.tenant_id != resource_scope.tenant_id:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.TENANT_MISMATCH,
                reason=f"Tenant mismatch: caller tenant '{identity.tenant_id}' cannot evaluate resource in tenant '{resource_scope.tenant_id}'.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 3: Workspace Scope Check
        if resource_scope.workspace_id and resource_scope.workspace_id != "*":
            user_roles = [r.upper() for r in getattr(identity, "roles", [])]
            is_admin = bool({"ADMINISTRATOR", "ADMIN", "SECURITY_ADMIN"} & set(user_roles))
            if identity.workspace_id != "*" and identity.workspace_id != resource_scope.workspace_id and not is_admin:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.WORKSPACE_MISMATCH,
                    reason=f"Workspace mismatch: caller workspace '{identity.workspace_id}' cannot access target workspace '{resource_scope.workspace_id}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 4: Plant Scope Check
        if resource_scope.plant_id and resource_scope.plant_id != "*":
            user_plants = identity.assigned_plants or []
            if "*" not in user_plants and resource_scope.plant_id not in user_plants:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.PLANT_SCOPE_DENIED,
                    reason=f"Plant access denied: caller '{identity.user_id}' is assigned to {user_plants}, but operation targets plant '{resource_scope.plant_id}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 5: Session Scope Check
        if resource_scope.session_id:
            if not caller_session:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Session scope '{resource_scope.session_id}' requested, but caller has no trusted session context.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                )
                return self._audit_and_persist_decision(dec, identity)
            if caller_session != resource_scope.session_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Session mismatch: request session '{resource_scope.session_id}' does not match trusted caller session '{caller_session}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 6: Capability Registry Allowlist Check
        cap_def = self.capability_registry.get(req_cap)
        if not cap_def:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.CAPABILITY_UNKNOWN,
                reason=f"Requested capability '{req_cap}' is not registered in the canonical capability registry.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 7: Execution Boundary Guard (Non-negotiable)
        if cap_def.is_execution or cap_def.minimum_level >= AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.EXECUTION_DISABLED,
                reason=f"Operational execution capability '{req_cap}' is DISABLED and NOT_IMPLEMENTED in SageCommand V3. No execution gateway is active.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=cap_def.minimum_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 8: Implementation Availability
        if not cap_def.is_implemented:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.NOT_IMPLEMENTED,
                reason_code=AutonomyReasonCode.CAPABILITY_NOT_IMPLEMENTED,
                reason=f"Capability '{req_cap}' is not implemented in SageCommand V3.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=cap_def.minimum_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 9: Active Autonomy Grant Lookup (Session-aware)
        active_grant = self.repository.get_active_grant_for_subject(
            subject_type=subject_type,
            subject_id=clean_subject_id,
            tenant_id=resource_scope.tenant_id,
            workspace_id=resource_scope.workspace_id,
            plant_id=resource_scope.plant_id,
            data_mode=norm_data_mode,
            session_id=caller_session,
        )

        if not active_grant:
            # Check if there is an inactive/suspended/expired/revoked or SIMULATION-only grant for detailed diagnostics
            grants, _ = self.repository.list_grants(
                tenant_id=resource_scope.tenant_id,
                workspace_id=resource_scope.workspace_id,
                subject_type=subject_type,
                subject_id=clean_subject_id,
                limit=1,
            )
            if grants:
                g = grants[0]
                if g.data_mode == "SIMULATION" and norm_data_mode == "REAL":
                    r_code = AutonomyReasonCode.DATA_MODE_MISMATCH
                    msg = f"Data-mode isolation violation: subject '{clean_subject_id}' has a SIMULATION autonomy grant, which cannot authorize access to REAL operational resources."
                elif g.status == AutonomyGrantStatus.REVOKED:
                    r_code = AutonomyReasonCode.AUTONOMY_GRANT_REVOKED
                    msg = f"Autonomy grant '{g.grant_id}' for subject '{clean_subject_id}' has been permanently REVOKED."
                elif g.status == AutonomyGrantStatus.SUSPENDED:
                    r_code = AutonomyReasonCode.AUTONOMY_GRANT_SUSPENDED
                    msg = f"Autonomy grant '{g.grant_id}' for subject '{clean_subject_id}' is currently SUSPENDED."
                elif g.is_expired():
                    r_code = AutonomyReasonCode.AUTONOMY_GRANT_EXPIRED
                    msg = f"Autonomy grant '{g.grant_id}' for subject '{clean_subject_id}' expired at timestamp {g.expires_at}."
                elif g.session_id and not caller_session:
                    r_code = AutonomyReasonCode.SESSION_MISMATCH
                    msg = f"Session context missing: subject '{clean_subject_id}' has a session-bound grant '{g.grant_id}' for session '{g.session_id}', but caller provided no session context."
                elif g.session_id and caller_session and g.session_id != caller_session:
                    r_code = AutonomyReasonCode.SESSION_MISMATCH
                    msg = f"Session mismatch: subject '{clean_subject_id}' grant '{g.grant_id}' is bound to session '{g.session_id}', but request session is '{caller_session}'."
                else:
                    r_code = AutonomyReasonCode.AUTONOMY_GRANT_NOT_FOUND
                    msg = f"No active autonomy grant found for subject '{clean_subject_id}' matching target scope."
            else:
                r_code = AutonomyReasonCode.AUTONOMY_GRANT_NOT_FOUND
                msg = f"No autonomy grant found for subject '{clean_subject_id}' in tenant '{resource_scope.tenant_id}'."

            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=r_code,
                reason=msg,
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 10: Grant Level Sufficiency Check
        if active_grant.autonomy_level < cap_def.minimum_level:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.AUTONOMY_LEVEL_INSUFFICIENT,
                reason=(
                    f"Autonomy level insufficient: subject '{clean_subject_id}' holds {active_grant.autonomy_level.title}, "
                    f"but capability '{req_cap}' requires at least {cap_def.minimum_level.title}."
                ),
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=active_grant.autonomy_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
                grant_id=active_grant.grant_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 11: Capability Restrictions and Permitted Allowlist in Grant
        if req_cap in active_grant.restricted_capabilities:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.CAPABILITY_RESTRICTED,
                reason=f"Capability '{req_cap}' is explicitly restricted by autonomy grant '{active_grant.grant_id}'.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=active_grant.autonomy_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
                grant_id=active_grant.grant_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        if active_grant.permitted_capabilities and req_cap not in active_grant.permitted_capabilities:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.CAPABILITY_NOT_GRANTED,
                reason=f"Capability '{req_cap}' is not among explicitly permitted capabilities on grant '{active_grant.grant_id}'.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=active_grant.autonomy_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
                grant_id=active_grant.grant_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 12: Data Mode Isolation Check
        if active_grant.data_mode == "SIMULATION" and norm_data_mode == "REAL":
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.DENY,
                reason_code=AutonomyReasonCode.DATA_MODE_MISMATCH,
                reason="Data-mode isolation violation: SIMULATION autonomy grant cannot authorize access to REAL operational resources.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=active_grant.autonomy_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                request_id=request_id,
                grant_id=active_grant.grant_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Step 13: Scope Intersection Validation (Grant Scope vs Requested Resource Scope)
        if active_grant.workspace_id and active_grant.workspace_id != "*":
            if resource_scope.workspace_id and resource_scope.workspace_id != active_grant.workspace_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.WORKSPACE_MISMATCH,
                    reason=f"Scope violation: grant is bound to workspace '{active_grant.workspace_id}', but resource targets workspace '{resource_scope.workspace_id}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        if active_grant.plant_id and active_grant.plant_id != "*":
            if resource_scope.plant_id and resource_scope.plant_id != active_grant.plant_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.PLANT_SCOPE_DENIED,
                    reason=f"Scope violation: grant is bound to plant '{active_grant.plant_id}', but resource targets plant '{resource_scope.plant_id}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Strict Session-Bound Check
        if active_grant.session_id:
            if not caller_session:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Session context missing: grant '{active_grant.grant_id}' is strictly bound to session '{active_grant.session_id}', but caller provided no session identifier.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)
            if caller_session != active_grant.session_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Scope violation: grant is bound to session '{active_grant.session_id}', but request session is '{caller_session}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 14: Underlying Authorization Integration
        if cap_def.canonical_permission:
            authz_scope = AuthorizationScope(
                tenant_id=resource_scope.tenant_id,
                workspace_id=resource_scope.workspace_id,
                session_id=caller_session,
                plant_id=resource_scope.plant_id,
                line_id=resource_scope.line_id,
                machine_id=resource_scope.equipment_id,
            )
            authz_ctx = AuthorizationContext(
                identity=identity.to_user_identity(),
                required_permission=cap_def.canonical_permission,
                scope=authz_scope,
                data_mode=norm_data_mode,
            )
            try:
                authz_dec = authorization_service.evaluate(authz_ctx)
                if not authz_dec or authz_dec.effect != AuthzDecisionEffect.ALLOW:
                    reason_msg = authz_dec.reason if authz_dec else "Authorization returned no ALLOW decision"
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.DENY,
                        reason_code=AutonomyReasonCode.AUTHORIZATION_DENIED,
                        reason=f"Underlying authorization denied permission '{cap_def.canonical_permission}': {reason_msg}",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)
            except Exception as e:
                logger.warning(f"Underlying authorization evaluation failed: {e}")
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.AUTHORIZATION_DENIED,
                    reason=f"Underlying authorization evaluation failed for permission '{cap_def.canonical_permission}': {e}",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 15: Authoritative Deterministic Risk & Action Evaluation
        client_claimed_risk = str(risk_ctx.get("risk_level", "")).strip().upper()
        action_id = risk_ctx.get("action_id")
        action_type_str = risk_ctx.get("action_type")
        target_res_id = risk_ctx.get("target_resource_id") or resource_scope.equipment_id

        system_risk = None
        system_requires_approval = False
        authoritative_cost = None

        if req_cap in NON_ACTION_CAPABILITIES:
            # Observation and analysis capabilities do not alter state or require action risk.
            # Explicit rule: read-only analytical operations default to LOW system risk.
            system_risk = "LOW"
            system_requires_approval = False
        elif req_cap in ACTION_CAPABILITIES:
            # Action capabilities require authoritative action risk evaluation.
            if action_id:
                # 1. Authoritative check via persisted action_id against action_store
                try:
                    stored_action = action_store.get_action(str(action_id).strip(), tenant_id=resource_scope.tenant_id)
                except Exception as e:
                    logger.warning(f"Error accessing stored action: {e}")
                    stored_action = None

                if not stored_action:
                    existing_anywhere = action_store.find_existing_by_id(str(action_id).strip())
                    reason_c = AutonomyReasonCode.WORKSPACE_MISMATCH if existing_anywhere else AutonomyReasonCode.AUTHORIZATION_DENIED
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.DENY,
                        reason_code=reason_c,
                        reason=f"Authoritative action record '{action_id}' not accessible or not found in tenant '{resource_scope.tenant_id}'.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                # Workspace scope check on stored action
                user_roles = [r.upper() for r in getattr(identity, "roles", [])]
                is_admin = bool({"ADMINISTRATOR", "ADMIN", "SECURITY_ADMIN", "SYSTEM_ADMIN"} & set(user_roles))
                if resource_scope.workspace_id and resource_scope.workspace_id != "*":
                    if stored_action.workspace_id and stored_action.workspace_id != resource_scope.workspace_id:
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.WORKSPACE_MISMATCH,
                            reason=f"Cross-workspace action access: action '{action_id}' belongs to workspace '{stored_action.workspace_id}', but evaluation scope is '{resource_scope.workspace_id}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                if not is_admin and identity.workspace_id != "*":
                    if stored_action.workspace_id and stored_action.workspace_id != identity.workspace_id:
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.WORKSPACE_MISMATCH,
                            reason=f"Cross-workspace action reference: action '{action_id}' belongs to workspace '{stored_action.workspace_id}', caller workspace is '{identity.workspace_id}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                # Data mode isolation check on stored action
                stored_mode = str(stored_action.data_mode).strip().upper() if hasattr(stored_action, "data_mode") else "SIMULATION"
                if stored_mode != norm_data_mode:
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.DENY,
                        reason_code=AutonomyReasonCode.DATA_MODE_MISMATCH,
                        reason=f"Data-mode mismatch: stored action is in '{stored_mode}' mode, but evaluation requested '{norm_data_mode}'.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                # Plant scope check on stored action
                if stored_action.target and resource_scope.plant_id and resource_scope.plant_id != "*":
                    act_plant = getattr(stored_action.target, "plant_id", None)
                    if act_plant and act_plant != resource_scope.plant_id:
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.PLANT_SCOPE_DENIED,
                            reason=f"Authoritative action plant '{act_plant}' does not match evaluation plant scope '{resource_scope.plant_id}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                # Session scope check on stored action
                if caller_session and getattr(stored_action, "session_id", None):
                    if stored_action.session_id and stored_action.session_id != caller_session:
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                            reason=f"Session mismatch: stored action is bound to session '{stored_action.session_id}', but caller session is '{caller_session}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                # Consistency check: action type
                if action_type_str:
                    stored_type_val = stored_action.action_type.value if hasattr(stored_action.action_type, "value") else str(stored_action.action_type)
                    if stored_type_val.strip().upper() != str(action_type_str).strip().upper():
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.ACTION_VALIDATION_FAILED,
                            reason=f"Action type mismatch: stored action is '{stored_type_val}', but evaluation request specified '{action_type_str}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                # Consistency check: target resource
                if target_res_id and stored_action.target:
                    stored_target_id = getattr(stored_action.target, "resource_id", None)
                    if stored_target_id and str(stored_target_id).strip() != str(target_res_id).strip():
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.DENY,
                            reason_code=AutonomyReasonCode.SCOPE_MISMATCH,
                            reason=f"Target mismatch: stored action targets '{stored_target_id}', but evaluation requested '{target_res_id}'.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)

                # Stored action is valid and consistent
                system_risk = stored_action.system_risk_level.value if hasattr(stored_action.system_risk_level, "value") else str(stored_action.system_risk_level)
                system_requires_approval = bool(stored_action.requires_approval)
                if stored_action.estimated_cost and hasattr(stored_action.estimated_cost, "value") and stored_action.estimated_cost.value is not None:
                    authoritative_cost = float(stored_action.estimated_cost.value)

            else:
                # No action_id provided
                if req_cap in ("VALIDATE_ACTION", "PREPARE_APPROVAL_PACKAGE", "REQUEST_HUMAN_REVIEW", "VALIDATE_MISSION_DAG"):
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                        reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                        reason=f"Authoritative persisted action record ('action_id') is required for capability '{req_cap}'. Human review required.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        approval_requirement=True,
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                # For PROPOSE_ACTION (server-side pre-persistence validation)
                if not action_type_str:
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                        reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                        reason=f"Action details ('action_type') omitted for action capability '{req_cap}'. Authoritative risk cannot be established.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        approval_requirement=True,
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                try:
                    act_type_enum = ActionType(str(action_type_str).strip().upper())
                except (ValueError, KeyError):
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                        reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                        reason=f"Invalid action type '{action_type_str}'. Authoritative risk cannot be established.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        approval_requirement=True,
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                # Validate parameters against parameter schema
                param_schema = ACTION_PARAMETER_SCHEMAS.get(act_type_enum)
                raw_params = risk_ctx.get("parameters")
                validated_params = {}
                if param_schema and raw_params is not None:
                    try:
                        validated_params = param_schema(**raw_params).model_dump()
                    except Exception as e:
                        dec = AutonomyDecision.create(
                            decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                            reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                            reason=f"Malformed parameters for action type '{act_type_enum.value}': {e}. Human review required.",
                            subject_type=subject_type,
                            subject_id=clean_subject_id,
                            requested_capability=req_cap,
                            effective_autonomy_level=active_grant.autonomy_level,
                            scope=resource_scope,
                            data_mode=norm_data_mode,
                            risk_status="UNKNOWN",
                            approval_requirement=True,
                            request_id=request_id,
                            grant_id=active_grant.grant_id,
                        )
                        return self._audit_and_persist_decision(dec, identity)
                elif raw_params:
                    validated_params = raw_params

                # Validate target context
                if not target_res_id and not resource_scope.plant_id and not resource_scope.equipment_id:
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                        reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                        reason=f"Missing target resource or plant context for action '{act_type_enum.value}'. Authoritative risk cannot be established.",
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status="UNKNOWN",
                        approval_requirement=True,
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    return self._audit_and_persist_decision(dec, identity)

                try:
                    classified_risk = action_registry.classify_risk(
                        action_type=act_type_enum,
                        target={"resource_id": target_res_id, "plant_id": resource_scope.plant_id},
                        parameters=validated_params,
                        cost_estimate=risk_ctx.get("cost_estimate_usd"),
                        data_mode=norm_data_mode,
                    )
                    system_risk = classified_risk.value if hasattr(classified_risk, "value") else str(classified_risk)
                except Exception:
                    system_risk = "UNKNOWN"

                if risk_ctx.get("cost_estimate_usd") is not None:
                    try:
                        authoritative_cost = float(risk_ctx.get("cost_estimate_usd"))
                    except (ValueError, TypeError):
                        authoritative_cost = None
        else:
            # Capability not explicitly categorized: must establish risk or fail closed
            system_risk = "UNKNOWN"

        # INVARIANT: Client-supplied risk cannot downgrade system-computed risk!
        # Client can only claim higher risk (conservative escalation), never establish that an action is safe.
        risk_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4, "UNKNOWN": 5}
        authoritative_risk = system_risk or "UNKNOWN"
        if client_claimed_risk in risk_rank and authoritative_risk in risk_rank:
            if risk_rank[client_claimed_risk] > risk_rank[authoritative_risk]:
                authoritative_risk = client_claimed_risk

        # If authoritative risk is UNKNOWN for an action capability: fail closed to review required
        if authoritative_risk == "UNKNOWN" and req_cap in ACTION_CAPABILITIES:
            dec = AutonomyDecision.create(
                decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                reason_code=AutonomyReasonCode.RISK_UNKNOWN,
                reason=f"Authoritative risk cannot be established for capability '{req_cap}'. Human review required.",
                subject_type=subject_type,
                subject_id=clean_subject_id,
                requested_capability=req_cap,
                effective_autonomy_level=active_grant.autonomy_level,
                scope=resource_scope,
                data_mode=norm_data_mode,
                risk_status="UNKNOWN",
                approval_requirement=True,
                request_id=request_id,
                grant_id=active_grant.grant_id,
            )
            return self._audit_and_persist_decision(dec, identity)

        # Action Type Restriction Check
        if action_type_str and active_grant.constraints.restricted_action_types:
            clean_act_type = str(action_type_str).strip().upper()
            if clean_act_type in active_grant.constraints.restricted_action_types:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.POLICY_REVIEW_REQUIRED,
                    reason=f"Action type '{clean_act_type}' is explicitly restricted by grant constraints.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status=authoritative_risk,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Cost Limit Constraint Check
        max_cost_limit = active_grant.constraints.max_cost_limit_usd
        if max_cost_limit is not None:
            effective_cost = None
            if authoritative_cost is not None:
                effective_cost = authoritative_cost
                # Client cost can escalate conservatism, but can never understate/override authoritative cost
                client_cost = risk_ctx.get("cost_estimate_usd")
                if client_cost is not None:
                    try:
                        c_val = float(client_cost)
                        if c_val > effective_cost:
                            effective_cost = c_val
                    except (ValueError, TypeError):
                        pass
            else:
                client_cost = risk_ctx.get("cost_estimate_usd")
                if client_cost is not None:
                    try:
                        effective_cost = float(client_cost)
                    except (ValueError, TypeError):
                        effective_cost = None

            if effective_cost is None:
                # Mandatory cost limit cannot be evaluated
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                    reason_code=AutonomyReasonCode.POLICY_REVIEW_REQUIRED,
                    reason=(
                        f"Grant specifies mandatory max cost limit of ${max_cost_limit:,.2f}, "
                        "but action cost cannot be authoritatively evaluated. Human review required."
                    ),
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status=authoritative_risk,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

            if effective_cost > max_cost_limit:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                    reason_code=AutonomyReasonCode.POLICY_REVIEW_REQUIRED,
                    reason=(
                        f"Authoritative cost (${effective_cost:,.2f}) exceeds grant maximum cost threshold "
                        f"(${max_cost_limit:,.2f}). Human review required."
                    ),
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status=authoritative_risk,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Risk Classification & Approval Evaluation
        # An autonomy grant NEVER suppresses a mandatory approval requirement!
        requires_approval = cap_def.requires_human_approval or system_requires_approval
        if authoritative_risk in active_grant.constraints.approval_required_for_risk_levels:
            requires_approval = True

        # Separation of Duties Check
        if req_cap == "REQUEST_HUMAN_REVIEW" or "APPROVE" in req_cap:
            proposer_id = risk_ctx.get("proposer_id")
            if proposer_id and proposer_id == clean_subject_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SEPARATION_OF_DUTIES_VIOLATION,
                    reason=f"Separation of duties violation: subject '{clean_subject_id}' proposed the action and cannot approve its own proposal.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=active_grant.autonomy_level,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status=authoritative_risk,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                return self._audit_and_persist_decision(dec, identity)

        # Step 16: ALLOW Capability
        matched_constraints = [
            f"Autonomy level {active_grant.autonomy_level.title} >= {cap_def.minimum_level.title}",
            "Allowlist and restricted capabilities satisfied",
            "Scope intersection validated",
            "Data mode isolation satisfied",
        ]

        dec = AutonomyDecision.create(
            decision=AutonomyDecisionEffect.ALLOW,
            reason_code=AutonomyReasonCode.ALLOWED,
            reason=f"Capability '{req_cap}' authorized under autonomy grant '{active_grant.grant_id}'.",
            subject_type=subject_type,
            subject_id=clean_subject_id,
            requested_capability=req_cap,
            effective_autonomy_level=active_grant.autonomy_level,
            scope=resource_scope,
            data_mode=norm_data_mode,
            risk_status=authoritative_risk,
            approval_requirement=requires_approval,
            matched_constraints=matched_constraints,
            failed_constraints=[],
            autonomy_profile_revision=active_grant.revision,
            request_id=request_id,
            grant_id=active_grant.grant_id,
        )
        return self._audit_and_persist_decision(dec, identity)

    def _audit_and_persist_decision(self, decision: AutonomyDecision, identity: Identity) -> AutonomyDecision:
        """
        Persists decision to SQLite ledger and logs a safe security audit event.
        FAIL-CLOSED INVARIANT: If mandatory persistence of an ALLOW decision fails,
        the decision is converted to DENY with reason EVALUATION_ERROR to prevent
        unrecorded / unaudited actions.
        """
        try:
            self.repository.record_decision(decision)
        except Exception as e:
            logger.error(
                f"Mandatory autonomy decision persistence failed for decision_id={decision.decision_id}, "
                f"request_id={decision.request_id}, subject={decision.subject_id}: {type(e).__name__}"
            )
            if decision.decision == AutonomyDecisionEffect.ALLOW:
                # Strictly fail closed: ALLOW without audit persistence is forbidden
                denial = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.EVALUATION_ERROR,
                    reason="Mandatory audit persistence failed; operation denied for safety.",
                    subject_type=decision.subject_type,
                    subject_id=decision.subject_id,
                    requested_capability=decision.requested_capability,
                    effective_autonomy_level=decision.effective_autonomy_level,
                    scope=decision.scope,
                    data_mode=decision.data_mode,
                    risk_status=decision.risk_status,
                    approval_requirement=True,
                    request_id=decision.request_id,
                    grant_id=decision.grant_id,
                )
                try:
                    log_security_event(
                        event_name="AUTONOMY_AUDIT_PERSISTENCE_FAILURE",
                        details={
                            "original_decision_id": decision.decision_id,
                            "denial_decision_id": denial.decision_id,
                            "subject_id": decision.subject_id,
                            "requested_capability": decision.requested_capability,
                        },
                        severity="CRITICAL",
                        user_id=identity.user_id,
                        tenant_id=decision.scope.tenant_id,
                        session_id=decision.scope.session_id,
                    )
                except Exception:
                    pass
                return denial

        # Best-effort operational logging to security event audit log
        try:
            evt_map = {
                AutonomyDecisionEffect.ALLOW: "AUTONOMY_CAPABILITY_ALLOWED",
                AutonomyDecisionEffect.DENY: "AUTONOMY_CAPABILITY_DENIED",
                AutonomyDecisionEffect.REQUIRES_REVIEW: "AUTONOMY_REVIEW_REQUIRED",
                AutonomyDecisionEffect.NOT_IMPLEMENTED: "AUTONOMY_UNIMPLEMENTED_CAPABILITY_REQUESTED",
            }
            event_name = evt_map.get(decision.decision, "AUTONOMY_CAPABILITY_DENIED")
            log_security_event(
                event_name=event_name,
                details={
                    "decision_id": decision.decision_id,
                    "subject_type": decision.subject_type.value,
                    "subject_id": decision.subject_id,
                    "requested_capability": decision.requested_capability,
                    "effective_level": int(decision.effective_autonomy_level),
                    "decision": decision.decision.value,
                    "reason_code": decision.reason_code.value,
                    "tenant_id": decision.scope.tenant_id,
                    "workspace_id": decision.scope.workspace_id,
                    "plant_id": decision.scope.plant_id,
                    "data_mode": decision.data_mode,
                    "risk_status": decision.risk_status,
                    "approval_requirement": decision.approval_requirement,
                    "decision_hash": decision.decision_hash,
                    "grant_id": decision.grant_id,
                },
                user_id=identity.user_id,
                severity="INFO" if decision.decision == AutonomyDecisionEffect.ALLOW else "WARNING",
                tenant_id=decision.scope.tenant_id,
                session_id=decision.scope.session_id,
            )
        except Exception as e:
            logger.warning(f"Operational audit logging error: {type(e).__name__}")

        return decision

    # =========================================================================
    # 2. GRANT LIFECYCLE MANAGEMENT
    # =========================================================================

    def _require_grant_permission(self, identity: Identity, action: str = "grant") -> None:
        """Verifies caller is authorized to administer or grant autonomy."""
        required_perm = f"autonomy.{action}"
        user_roles = [r.upper() for r in identity.roles]
        
        # Explicit trusted role-based shortcuts covering the exact requested operation
        if action == "grant":
            authorized_roles = {"ADMINISTRATOR", "SECURITY_ADMIN", "PLANT_MANAGER", "SYSTEM_ADMIN"}
        elif action == "read":
            authorized_roles = {"ADMINISTRATOR", "SECURITY_ADMIN", "PLANT_MANAGER", "SYSTEM_ADMIN", "OPERATOR", "ANALYST", "VIEWER"}
        else:
            authorized_roles = {"ADMINISTRATOR", "SECURITY_ADMIN", "SYSTEM_ADMIN"}

        has_role = bool(set(user_roles) & authorized_roles)

        if not has_role:
            # Check RBAC permission registry via authorization_service
            authz_scope = AuthorizationScope(
                tenant_id=identity.tenant_id,
                workspace_id=identity.workspace_id,
                session_id=identity.session_id,
            )
            authz_ctx = AuthorizationContext(
                identity=identity.to_user_identity(),
                required_permission=required_perm,
                scope=authz_scope,
            )
            try:
                authz_dec = authorization_service.evaluate(authz_ctx)
                if not authz_dec or authz_dec.effect != AuthzDecisionEffect.ALLOW:
                    reason = authz_dec.reason if authz_dec else "Authorization decision was empty or not ALLOW"
                    log_security_event(
                        "AUTHORIZATION_FAILURE",
                        {
                            "user_id": identity.user_id,
                            "required_permission": required_perm,
                            "reason": reason,
                        },
                        severity="WARNING",
                        user_id=identity.user_id,
                        tenant_id=identity.tenant_id,
                    )
                    raise AutonomyRepositoryError(
                        f"Identity '{identity.user_id}' lacks permission '{required_perm}' (authorization effect: {authz_dec.effect.value if authz_dec else 'None'})."
                    )
            except AutonomyRepositoryError:
                raise
            except Exception as e:
                logger.warning(f"Authorization evaluation exception for '{required_perm}': {e}")
                raise AutonomyRepositoryError(
                    f"Authorization evaluation failed for permission '{required_perm}': {e}"
                )

    def create_grant(
        self,
        identity: Identity,
        request: AutonomyGrantCreateRequest
    ) -> AutonomyGrant:
        """
        Creates and persists a new autonomy grant under caller's authoritative identity and scope.
        Client-supplied created_by or tenant_id are ignored.
        Enforces workspace isolation so callers cannot create grants for unauthorized workspaces.
        """
        self._require_grant_permission(identity, "grant")

        # Validate Level: Levels 4 & 5 are strictly prohibited
        if request.autonomy_level >= AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION:
            raise ValueError(
                f"Autonomy {request.autonomy_level.name} is DISABLED and NOT_IMPLEMENTED in SageCommand V3."
            )

        # Validate capabilities against registry
        permitted = []
        if request.permitted_capabilities:
            for cap_id in request.permitted_capabilities:
                clean_cap = cap_id.strip().upper()
                if not self.capability_registry.is_known(clean_cap):
                    raise ValueError(f"Unknown capability '{clean_cap}' in permitted_capabilities.")
                permitted.append(clean_cap)

        restricted = []
        if request.restricted_capabilities:
            for cap_id in request.restricted_capabilities:
                clean_cap = cap_id.strip().upper()
                if not self.capability_registry.is_known(clean_cap):
                    raise ValueError(f"Unknown capability '{clean_cap}' in restricted_capabilities.")
                restricted.append(clean_cap)

        # Build authoritative scope with workspace isolation enforcement
        target_ws = self._resolve_caller_workspace(identity, request.workspace_id) or getattr(identity, "workspace_id", None) or "workspace_default"
        target_plant = request.plant_id
        if target_plant and target_plant != "*":
            user_plants = identity.assigned_plants or []
            if "*" not in user_plants and target_plant not in user_plants:
                raise ValueError(f"Caller '{identity.user_id}' is not authorized to grant autonomy for plant '{target_plant}'.")

        provenance = AutonomyProvenance(
            created_by_user_id=identity.user_id,
            granted_by_user_id=identity.user_id,
            grant_reason=request.grant_reason,
            approval_ticket_id=request.approval_ticket_id,
        )

        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:12]}",
            schema_version="3.0.0",
            subject_type=request.subject_type,
            subject_id=request.subject_id.strip(),
            autonomy_level=request.autonomy_level,
            tenant_id=identity.tenant_id,  # Authoritative from caller identity
            workspace_id=target_ws,
            session_id=request.session_id,
            plant_id=target_plant,
            data_mode=request.data_mode.strip().upper(),
            permitted_capabilities=permitted,
            restricted_capabilities=restricted,
            constraints=request.constraints or AutonomyConstraints(),
            effective_from=time.time(),
            expires_at=request.expires_at,
            status=AutonomyGrantStatus.ACTIVE,
            revision=1,
            created_by=identity.user_id,
            created_at=time.time(),
            updated_at=time.time(),
            provenance=provenance,
        )

        saved = self.repository.create_grant(grant, idempotency_key=request.idempotency_key)

        log_security_event(
            event_name="AUTONOMY_GRANT_CREATED",
            details={
                "grant_id": saved.grant_id,
                "subject_type": saved.subject_type.value,
                "subject_id": saved.subject_id,
                "autonomy_level": int(saved.autonomy_level),
                "tenant_id": saved.tenant_id,
                "workspace_id": saved.workspace_id,
                "plant_id": saved.plant_id,
                "data_mode": saved.data_mode,
                "expires_at": saved.expires_at,
            },
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            session_id=identity.session_id,
        )
        return saved

    def update_grant(
        self,
        identity: Identity,
        grant_id: str,
        request: AutonomyGrantUpdateRequest
    ) -> AutonomyGrant:
        """
        Updates an existing grant under revision control and workspace isolation.
        Validates capabilities strictly and enforces lifecycle rules.
        """
        self._require_grant_permission(identity, "grant")
        effective_ws = self._resolve_caller_workspace(identity, None)

        if request.autonomy_level is not None and request.autonomy_level >= AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION:
            raise ValueError(
                f"Autonomy {request.autonomy_level.name} is DISABLED and NOT_IMPLEMENTED in SageCommand V3."
            )

        permitted = None
        if request.permitted_capabilities is not None:
            permitted = []
            for cap_id in request.permitted_capabilities:
                clean_cap = cap_id.strip().upper()
                if not self.capability_registry.is_known(clean_cap):
                    raise ValueError(f"Unknown capability '{clean_cap}' in permitted_capabilities.")
                permitted.append(clean_cap)

        restricted = None
        if request.restricted_capabilities is not None:
            restricted = []
            for cap_id in request.restricted_capabilities:
                clean_cap = cap_id.strip().upper()
                if not self.capability_registry.is_known(clean_cap):
                    raise ValueError(f"Unknown capability '{clean_cap}' in restricted_capabilities.")
                restricted.append(clean_cap)

        if request.status == AutonomyGrantStatus.REVOKED:
            raise AutonomyInvalidTransitionError(
                "Direct update to REVOKED status is prohibited. Use revoke_grant to maintain audit invariants."
            )

        def _apply_update(g: AutonomyGrant) -> AutonomyGrant:
            if request.autonomy_level is not None:
                g.autonomy_level = request.autonomy_level
            if permitted is not None:
                g.permitted_capabilities = permitted
            if restricted is not None:
                g.restricted_capabilities = restricted
            if request.constraints is not None:
                g.constraints = request.constraints
            if request.status is not None:
                g.status = request.status
            if request.expires_at is not None:
                g.expires_at = request.expires_at
            return g

        updated = self.repository.update_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            expected_revision=request.expected_revision,
            changed_by=identity.user_id,
            change_reason=request.update_reason,
            update_fn=_apply_update,
            workspace_id=effective_ws,
        )

        log_security_event(
            event_name="AUTONOMY_GRANT_UPDATED",
            details={
                "grant_id": updated.grant_id,
                "revision": updated.revision,
                "autonomy_level": int(updated.autonomy_level),
                "reason": request.update_reason,
            },
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
        )
        return updated

    def suspend_grant(
        self,
        identity: Identity,
        grant_id: str,
        expected_revision: int,
        reason: str
    ) -> AutonomyGrant:
        """Suspends an active grant with workspace isolation."""
        self._require_grant_permission(identity, "grant")
        effective_ws = self._resolve_caller_workspace(identity, None)
        suspended = self.repository.suspend_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            expected_revision=expected_revision,
            changed_by=identity.user_id,
            reason=reason,
            workspace_id=effective_ws,
        )
        log_security_event(
            event_name="AUTONOMY_GRANT_SUSPENDED",
            details={
                "grant_id": suspended.grant_id,
                "revision": suspended.revision,
                "reason": reason,
            },
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
        )
        return suspended

    def revoke_grant(
        self,
        identity: Identity,
        grant_id: str,
        expected_revision: int,
        reason: str
    ) -> AutonomyGrant:
        """Permanently revokes an autonomy grant with workspace isolation."""
        self._require_grant_permission(identity, "grant")
        effective_ws = self._resolve_caller_workspace(identity, None)
        revoked = self.repository.revoke_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            expected_revision=expected_revision,
            changed_by=identity.user_id,
            reason=reason,
            workspace_id=effective_ws,
        )
        log_security_event(
            event_name="AUTONOMY_GRANT_REVOKED",
            details={
                "grant_id": revoked.grant_id,
                "revision": revoked.revision,
                "reason": reason,
            },
            user_id=identity.user_id,
            tenant_id=identity.tenant_id,
        )
        return revoked

    def get_grant(
        self,
        identity: Identity,
        grant_id: str,
        workspace_id: Optional[str] = None
    ) -> Optional[AutonomyGrant]:
        """Retrieves an authorized autonomy grant within caller's tenant and workspace."""
        self._require_grant_permission(identity, "read")
        effective_ws = self._resolve_caller_workspace(identity, workspace_id)
        return self.repository.get_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            workspace_id=effective_ws,
        )

    def list_grants(
        self,
        identity: Identity,
        workspace_id: Optional[str] = None,
        subject_type: Optional[SubjectType] = None,
        subject_id: Optional[str] = None,
        status: Optional[AutonomyGrantStatus] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[AutonomyGrant], int]:
        """Lists grants within caller's authorized tenant and workspace."""
        self._require_grant_permission(identity, "read")
        effective_ws = self._resolve_caller_workspace(identity, workspace_id)
        return self.repository.list_grants(
            tenant_id=identity.tenant_id,
            workspace_id=effective_ws,
            subject_type=subject_type,
            subject_id=subject_id,
            status=status,
            limit=limit,
            offset=offset,
        )

    def list_decisions(
        self,
        identity: Identity,
        workspace_id: Optional[str] = None,
        subject_id: Optional[str] = None,
        limit: int = 50
    ) -> List[AutonomyDecision]:
        """Lists recent autonomy decisions within caller's authorized tenant and workspace."""
        self._require_grant_permission(identity, "read")
        effective_ws = self._resolve_caller_workspace(identity, workspace_id)
        return self.repository.list_decisions(
            tenant_id=identity.tenant_id,
            workspace_id=effective_ws,
            subject_id=subject_id,
            limit=limit,
        )


# Global default service instance
autonomy_service = AutonomyService()
