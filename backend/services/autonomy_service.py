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

logger = logging.getLogger("autonomy_service")


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
            self._audit_and_persist_decision(dec, identity)
            return dec

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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 3: Workspace Scope Check
        if resource_scope.workspace_id and resource_scope.workspace_id != "*":
            if identity.workspace_id != "*" and identity.workspace_id != resource_scope.workspace_id:
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
                self._audit_and_persist_decision(dec, identity)
                return dec

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
                self._audit_and_persist_decision(dec, identity)
                return dec

        # Step 5: Session Scope Check
        if resource_scope.session_id:
            if identity.session_id and identity.session_id != resource_scope.session_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Session mismatch: request session '{resource_scope.session_id}' does not match caller session '{identity.session_id}'.",
                    subject_type=subject_type,
                    subject_id=clean_subject_id,
                    requested_capability=req_cap,
                    effective_autonomy_level=AutonomyLevel.LEVEL_0_OBSERVE,
                    scope=resource_scope,
                    data_mode=norm_data_mode,
                    risk_status="UNKNOWN",
                    request_id=request_id,
                )
                self._audit_and_persist_decision(dec, identity)
                return dec

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
            self._audit_and_persist_decision(dec, identity)
            return dec

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
            self._audit_and_persist_decision(dec, identity)
            return dec

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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 9: Active Autonomy Grant Lookup
        active_grant = self.repository.get_active_grant_for_subject(
            subject_type=subject_type,
            subject_id=clean_subject_id,
            tenant_id=resource_scope.tenant_id,
            workspace_id=resource_scope.workspace_id,
            plant_id=resource_scope.plant_id,
            data_mode=norm_data_mode,
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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 9: Grant Level Sufficiency Check
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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 10: Capability Restrictions and Permitted Allowlist in Grant
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
            self._audit_and_persist_decision(dec, identity)
            return dec

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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 11: Data Mode Isolation Check
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
            self._audit_and_persist_decision(dec, identity)
            return dec

        # Step 12: Scope Intersection Validation (Grant Scope vs Requested Resource Scope)
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
                self._audit_and_persist_decision(dec, identity)
                return dec

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
                self._audit_and_persist_decision(dec, identity)
                return dec

        if active_grant.session_id:
            if resource_scope.session_id and resource_scope.session_id != active_grant.session_id:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.SESSION_MISMATCH,
                    reason=f"Scope violation: grant is bound to session '{active_grant.session_id}', but resource targets session '{resource_scope.session_id}'.",
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
                self._audit_and_persist_decision(dec, identity)
                return dec

        # Step 13: Underlying Authorization Integration
        if cap_def.canonical_permission:
            authz_scope = AuthorizationScope(
                tenant_id=resource_scope.tenant_id,
                workspace_id=resource_scope.workspace_id,
                session_id=resource_scope.session_id,
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
            authz_dec = authorization_service.evaluate(authz_ctx)
            if authz_dec.effect == AuthzDecisionEffect.DENY:
                dec = AutonomyDecision.create(
                    decision=AutonomyDecisionEffect.DENY,
                    reason_code=AutonomyReasonCode.AUTHORIZATION_DENIED,
                    reason=f"Underlying authorization denied permission '{cap_def.canonical_permission}': {authz_dec.reason}",
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
                self._audit_and_persist_decision(dec, identity)
                return dec

        # Step 14: Risk and Human Approval Constraints
        risk_level = str(risk_ctx.get("risk_level", "UNKNOWN")).strip().upper()
        if risk_level not in ("LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"):
            risk_level = "UNKNOWN"

        # Action Type Restriction Check
        action_type = risk_ctx.get("action_type")
        if action_type and active_grant.constraints.restricted_action_types:
            clean_act_type = str(action_type).strip().upper()
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
                    risk_status=risk_level,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                self._audit_and_persist_decision(dec, identity)
                return dec

        # Cost Limit Constraint Check
        cost_usd = risk_ctx.get("cost_estimate_usd")
        if cost_usd is not None and active_grant.constraints.max_cost_limit_usd is not None:
            try:
                c_val = float(cost_usd)
                if c_val > active_grant.constraints.max_cost_limit_usd:
                    dec = AutonomyDecision.create(
                        decision=AutonomyDecisionEffect.REQUIRES_REVIEW,
                        reason_code=AutonomyReasonCode.POLICY_REVIEW_REQUIRED,
                        reason=(
                            f"Estimated cost (${c_val:,.2f}) exceeds grant maximum cost threshold "
                            f"(${active_grant.constraints.max_cost_limit_usd:,.2f}). Human review required."
                        ),
                        subject_type=subject_type,
                        subject_id=clean_subject_id,
                        requested_capability=req_cap,
                        effective_autonomy_level=active_grant.autonomy_level,
                        scope=resource_scope,
                        data_mode=norm_data_mode,
                        risk_status=risk_level,
                        approval_requirement=True,
                        request_id=request_id,
                        grant_id=active_grant.grant_id,
                    )
                    self._audit_and_persist_decision(dec, identity)
                    return dec
            except (ValueError, TypeError):
                pass

        # Risk Classification & Approval Evaluation
        requires_approval = cap_def.requires_human_approval
        if risk_level in active_grant.constraints.approval_required_for_risk_levels:
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
                    risk_status=risk_level,
                    approval_requirement=True,
                    request_id=request_id,
                    grant_id=active_grant.grant_id,
                )
                self._audit_and_persist_decision(dec, identity)
                return dec

        # Step 15: ALLOW Capability
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
            risk_status=risk_level,
            approval_requirement=requires_approval,
            matched_constraints=matched_constraints,
            failed_constraints=[],
            autonomy_profile_revision=active_grant.revision,
            request_id=request_id,
            grant_id=active_grant.grant_id,
        )
        self._audit_and_persist_decision(dec, identity)
        return dec

    def _audit_and_persist_decision(self, decision: AutonomyDecision, identity: Identity) -> None:
        """Persists decision and logs a safe security audit event."""
        try:
            self.repository.record_decision(decision)
        except Exception as e:
            logger.error(f"Failed to persist autonomy decision: {e}")

        # Map to audit event name
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

    # =========================================================================
    # 2. GRANT LIFECYCLE MANAGEMENT
    # =========================================================================

    def _require_grant_permission(self, identity: Identity, action: str = "grant") -> None:
        """Verifies caller is authorized to administer or grant autonomy."""
        required_perm = f"autonomy.{action}"
        user_roles = [r.upper() for r in identity.roles]
        
        # Security officers, plant managers, and administrators have grant authority
        authorized_roles = {"ADMINISTRATOR", "SECURITY_ADMIN", "PLANT_MANAGER"}
        has_role = bool(set(user_roles) & authorized_roles)

        if not has_role:
            # Check RBAC permission registry
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
            authz_dec = authorization_service.evaluate(authz_ctx)
            if authz_dec.effect == AuthzDecisionEffect.DENY:
                log_security_event(
                    "AUTHORIZATION_FAILURE",
                    {
                        "user_id": identity.user_id,
                        "required_permission": required_perm,
                        "reason": authz_dec.reason,
                    },
                    severity="WARNING",
                    user_id=identity.user_id,
                    tenant_id=identity.tenant_id,
                )
                raise AutonomyRepositoryError(
                    f"Identity '{identity.user_id}' lacks permission '{required_perm}' to manage autonomy grants."
                )

    def create_grant(
        self,
        identity: Identity,
        request: AutonomyGrantCreateRequest
    ) -> AutonomyGrant:
        """
        Creates and persists a new autonomy grant under caller's authoritative identity and scope.
        Client-supplied created_by or tenant_id are ignored.
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

        # Build authoritative scope
        target_ws = request.workspace_id or identity.workspace_id or "workspace_default"
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
        """Updates an existing grant under revision control."""
        self._require_grant_permission(identity, "grant")

        if request.autonomy_level is not None and request.autonomy_level >= AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION:
            raise ValueError(
                f"Autonomy {request.autonomy_level.name} is DISABLED and NOT_IMPLEMENTED in SageCommand V3."
            )

        def _apply_update(g: AutonomyGrant) -> AutonomyGrant:
            if request.autonomy_level is not None:
                g.autonomy_level = request.autonomy_level
            if request.permitted_capabilities is not None:
                g.permitted_capabilities = [c.strip().upper() for c in request.permitted_capabilities]
            if request.restricted_capabilities is not None:
                g.restricted_capabilities = [c.strip().upper() for c in request.restricted_capabilities]
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
        """Suspends an active grant."""
        self._require_grant_permission(identity, "grant")
        suspended = self.repository.suspend_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            expected_revision=expected_revision,
            changed_by=identity.user_id,
            reason=reason,
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
        """Permanently revokes an autonomy grant."""
        self._require_grant_permission(identity, "grant")
        revoked = self.repository.revoke_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            expected_revision=expected_revision,
            changed_by=identity.user_id,
            reason=reason,
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
        """Retrieves an authorized autonomy grant within caller's tenant."""
        self._require_grant_permission(identity, "read")
        return self.repository.get_grant(
            grant_id=grant_id,
            tenant_id=identity.tenant_id,
            workspace_id=workspace_id,
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
        """Lists grants within caller's authorized tenant."""
        self._require_grant_permission(identity, "read")
        return self.repository.list_grants(
            tenant_id=identity.tenant_id,
            workspace_id=workspace_id,
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
        """Lists recent autonomy decisions within caller's authorized tenant."""
        self._require_grant_permission(identity, "read")
        return self.repository.list_decisions(
            tenant_id=identity.tenant_id,
            workspace_id=workspace_id,
            subject_id=subject_id,
            limit=limit,
        )


# Global default service instance
autonomy_service = AutonomyService()
