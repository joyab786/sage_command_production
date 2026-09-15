# backend/api/action_routes.py
"""
SageCommand V3 — Structured Action API Endpoints
Base Prefix: /api/v3/actions
Provides typed, validated, and observable lifecycle management for structured actions.
Enforces double validation, deterministic risk classification, simulation preview,
and tenant isolation without allowing direct execution of operational SQL writes.
"""

import uuid
import re
from typing import Optional, List, Dict, Any, Union
from fastapi import APIRouter, Header, Depends, Query, status
from fastapi.responses import JSONResponse

try:
    from core.auth import Identity, get_current_identity
    from governance.rate_limiter import rate_limiter
    from governance.audit import log_security_event
    from data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        ActionProvenance,
        ActionErrorCode,
        CreateActionRequest,
        CreateActionResponse,
        ActionDetailResponse,
        ActionListResponse,
        ActionValidationResponse,
        ActionSimulationResponse,
        ActionCancellationResponse,
    )
    from services.action_registry import action_registry
    from services.action_validator import action_validator
    from services.action_store import action_store
    from data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
    )
    from services.authorization_service import authorization_service
    from data.schemas.ledger_contract import LedgerActor, ActorType, EventCategory, EventType
    from services.audit_ledger import audit_ledger
    from data.schemas.execution_contract import (
        ExecutionRequest,
        ExecutionResult,
        ActionExecuteResponse,
    )
    from services.execution_gateway import execution_gateway, ExecutionGatewayException
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity
    from backend.governance.rate_limiter import rate_limiter
    from backend.governance.audit import log_security_event
    from backend.data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        ActionProvenance,
        ActionErrorCode,
        CreateActionRequest,
        CreateActionResponse,
        ActionDetailResponse,
        ActionListResponse,
        ActionValidationResponse,
        ActionSimulationResponse,
        ActionCancellationResponse,
    )
    from backend.services.action_registry import action_registry
    from backend.services.action_validator import action_validator
    from backend.services.action_store import action_store
    from backend.data.schemas.authorization_contract import (
        AuthorizationScope,
        AuthorizationContext,
        AuthzDecisionEffect,
    )
    from backend.services.authorization_service import authorization_service
    from backend.data.schemas.ledger_contract import LedgerActor, ActorType, EventCategory, EventType
    from backend.services.audit_ledger import audit_ledger
    from backend.data.schemas.execution_contract import (
        ExecutionRequest,
        ExecutionResult,
        ActionExecuteResponse,
    )
    from backend.services.execution_gateway import execution_gateway, ExecutionGatewayException

router = APIRouter(prefix="/api/v3/actions", tags=["Structured Action API"])


def extract_request_id(x_request_id: Optional[str] = None) -> str:
    """Extracts, sanitizes, or generates a correlation request identifier."""
    if x_request_id:
        sanitized = re.sub(r"[^\w\-]", "", x_request_id)[:64]
        if sanitized:
            return sanitized
    return f"req_{uuid.uuid4().hex[:12]}"


def action_error_response(
    status_code: int,
    code: Union[ActionErrorCode, str],
    message: str,
    request_id: str,
    details: Optional[List[Any]] = None
) -> JSONResponse:
    """Standard error response format matching the SageCommand V3 contract."""
    code_val = code.value if hasattr(code, "value") else str(code)
    payload = {
        "success": False,
        "request_id": request_id,
        "error": {
            "code": code_val,
            "message": message,
            "details": details or []
        }
    }
    return JSONResponse(status_code=status_code, content=payload)


# =====================================================================
# 1. CREATE ACTION PROPOSAL (POST /)
# =====================================================================

@router.post(
    "",
    response_model=CreateActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Propose Structured Action",
    description="Validates schema and domain rules, enforces anti-SQL smuggling, deterministically calculates risk, and registers the proposal."
)
async def create_action(
    request: CreateActionRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)

    # 1. Rate Limiting
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        return action_error_response(429, ActionErrorCode.RATE_LIMITED, "Rate limit exceeded.", req_id)

    # 2. Idempotency Check
    effective_idempotency_key = idempotency_key or request.idempotency_key
    if effective_idempotency_key:
        cached_action = action_store.check_idempotency(identity.tenant_id, effective_idempotency_key)
        if cached_action:
            return CreateActionResponse(
                success=True,
                request_id=req_id,
                action=cached_action
            )

    # 2b. RBAC + ABAC Capability Authorization
    target_plant = getattr(request.target, "plant_id", None)
    authz_scope = AuthorizationScope(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
        session_id=identity.session_id,
        plant_id=target_plant
    )
    authz_ctx = AuthorizationContext(
        identity=identity.to_user_identity(),
        required_permission="action.create",
        scope=authz_scope,
        data_mode=request.data_mode.upper()
    )
    authz_decision = authorization_service.evaluate(authz_ctx)
    if authz_decision.effect == AuthzDecisionEffect.DENY:
        log_security_event(
            "AUTHORIZATION_FAILURE",
            {
                "user_id": identity.user_id,
                "permission": "action.create",
                "reason_code": authz_decision.reason_code.value,
                "reason": authz_decision.reason,
                "decision_hash": authz_decision.decision_hash
            },
            severity="WARNING"
        )
        return action_error_response(403, "AUTHORIZATION_DENIED", authz_decision.reason, req_id)

    # 3. Deterministic System Risk Level Calculation (Independent of LLM)
    system_risk = action_registry.classify_risk(
        action_type=request.action_type,
        target=request.target,
        parameters=request.parameters,
        cost_estimate=request.estimated_cost
    )

    # Simulator actions are always LOW risk
    if request.data_mode.upper() == "SIMULATION":
        system_risk = RiskLevel.LOW

    # Human-in-the-loop requirement
    requires_approval = system_risk in [RiskLevel.HIGH, RiskLevel.CRITICAL]

    # 4. Construct Action Provenance & Canonical Object
    provenance = ActionProvenance(
        requested_by_user_id=identity.user_id,
        source="AGENT" if identity.user_id.startswith("agent_") else "USER",
        model_name="agent-evaluator-v3" if identity.user_id.startswith("agent_") else None,
        reasoning_trace=request.reason.summary
    )

    action = Action(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
        session_id=identity.session_id or "session_default",
        action_type=request.action_type,
        version=request.version,
        target=request.target,
        parameters=request.parameters,
        reason=request.reason,
        evidence=request.evidence,
        data_mode=request.data_mode.upper(),
        system_risk_level=system_risk,
        model_estimated_risk=request.model_estimated_risk,
        requires_approval=requires_approval,
        estimated_cost=request.estimated_cost,
        estimated_duration_minutes=request.estimated_duration_minutes,
        provenance=provenance,
        mission_id=request.mission_id,
        incident_id=request.incident_id,
        idempotency_key=effective_idempotency_key,
        status=ActionStatus.PROPOSED
    )

    # 5. Two-Layer Validation
    is_valid, checks = action_validator.validate_all(action, identity)
    failed_checks = [c for c in checks if c.status == "FAIL"]

    if not is_valid:
        action.status = ActionStatus.REJECTED
        # Determine specific error code based on failed checks
        err_code = ActionErrorCode.INVALID_ACTION_SCHEMA
        for fc in failed_checks:
            if "SQL_SMUGGLING" in fc.name:
                err_code = ActionErrorCode.SQL_SMUGGLING_DETECTED
                break
            elif "TENANT" in fc.name:
                err_code = ActionErrorCode.CROSS_TENANT_VIOLATION
                break
            elif "TARGET" in fc.name:
                err_code = ActionErrorCode.INVALID_TARGET_RESOURCE
                break
            elif "INVARIANT" in fc.name:
                err_code = ActionErrorCode.DOMAIN_VALIDATION_FAILED
                break

        # Log security event for validation rejection
        log_security_event(
            event_name="ACTION_VALIDATION_FAILED",
            user_id=identity.user_id,
            details={
                "tenant_id": identity.tenant_id,
                "action_type": action.action_type.value,
                "target_id": action.target.resource_id,
                "error_code": err_code.value,
                "failed_checks": [c.model_dump() for c in failed_checks]
            }
        )

        return action_error_response(
            status_code=400,
            code=err_code,
            message=f"Action validation failed: {'; '.join([c.message or c.name for c in failed_checks])}",
            request_id=req_id,
            details=[c.model_dump() for c in failed_checks]
        )

    # 6. Save Validated Action to Repository
    action_store.save(action, idempotency_key=effective_idempotency_key)

    # 7. Audit log event & Persistent Ledger
    log_security_event(
        event_name="ACTION_PROPOSED",
        user_id=identity.user_id,
        details={
            "tenant_id": identity.tenant_id,
            "action_id": action.action_id,
            "action_type": action.action_type.value,
            "target": action.target.resource_id,
            "system_risk": action.system_risk_level.value,
            "requires_approval": action.requires_approval
        }
    )

    try:
        actor = LedgerActor(
            actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
            actor_id=identity.user_id,
            acting_user_id=identity.user_id,
            roles=getattr(identity, "roles", [])
        )
        audit_ledger.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            session_id=action.session_id,
            plant_id=getattr(action.target, "plant_id", None),
            category=EventCategory.ACTION,
            action_id=action.action_id,
            correlation_id=action.incident_id or action.mission_id or action.action_id,
            request_id=req_id,
            resource_type="action",
            resource_id=action.target.resource_id,
            data_mode=action.data_mode,
            payload={
                "action_id": action.action_id,
                "action_type": action.action_type.value,
                "target": action.target.dict(),
                "system_risk_level": action.system_risk_level.value,
                "reason": action.reason.dict(),
                "evidence": [e.dict() for e in action.evidence],
                "requires_approval": action.requires_approval
            },
            metadata={"status": action.status.value}
        )
    except Exception:
        pass

    return CreateActionResponse(
        success=True,
        request_id=req_id,
        action=action
    )


# =====================================================================
# 2. LIST ACTIONS (GET /)
# =====================================================================

@router.get(
    "",
    response_model=ActionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Actions",
    description="Queries actions scoped to current tenant with optional filters and pagination."
)
async def list_actions(
    action_type: Optional[ActionType] = Query(None, description="Filter by action type"),
    status_filter: Optional[ActionStatus] = Query(None, alias="status", description="Filter by status"),
    risk_level: Optional[RiskLevel] = Query(None, description="Filter by system risk level"),
    data_mode: Optional[str] = Query(None, description="REAL or SIMULATION"),
    mission_id: Optional[str] = Query(None, description="Filter by mission ID"),
    incident_id: Optional[str] = Query(None, description="Filter by incident ID"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    actions, total = action_store.list_actions(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default"),
        action_type=action_type,
        status=status_filter,
        risk_level=risk_level,
        data_mode=data_mode,
        mission_id=mission_id,
        incident_id=incident_id,
        limit=limit,
        offset=offset
    )

    return ActionListResponse(
        success=True,
        request_id=req_id,
        actions=actions,
        total=total
    )


# =====================================================================
# 3. GET ACTION DETAILS (GET /{action_id})
# =====================================================================

@router.get(
    "/{action_id}",
    response_model=ActionDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Action Detail",
    description="Retrieves action details by ID with tenant isolation and human-readable preview."
)
async def get_action(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    action = action_store.get_by_id(action_id, identity.tenant_id)

    if not action:
        return action_error_response(
            status_code=404,
            code=ActionErrorCode.ACTION_NOT_FOUND,
            message=f"Action '{action_id}' not found.",
            request_id=req_id
        )

    return ActionDetailResponse(
        success=True,
        request_id=req_id,
        action=action,
        preview=action.generate_human_preview()
    )


# =====================================================================
# 4. VALIDATE ACTION (POST /{action_id}/validate)
# =====================================================================

@router.post(
    "/{action_id}/validate",
    response_model=ActionValidationResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate Action",
    description="Explicitly re-runs Layer 1 and Layer 2 validation checks for an action."
)
async def validate_action_endpoint(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    action = action_store.get_by_id(action_id, identity.tenant_id)

    if not action:
        return action_error_response(
            status_code=404,
            code=ActionErrorCode.ACTION_NOT_FOUND,
            message=f"Action '{action_id}' not found.",
            request_id=req_id
        )

    is_valid, checks = action_validator.validate_all(action, identity)
    return ActionValidationResponse(
        success=True,
        request_id=req_id,
        valid=is_valid,
        checks=checks
    )


# =====================================================================
# 5. SIMULATE ACTION (POST /{action_id}/simulate)
# =====================================================================

@router.post(
    "/{action_id}/simulate",
    response_model=ActionSimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="Simulate Action Impact",
    description="Generates a deterministic before/after preview without altering live databases."
)
async def simulate_action_endpoint(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    action = action_store.get_by_id(action_id, identity.tenant_id)

    if not action:
        return action_error_response(
            status_code=404,
            code=ActionErrorCode.ACTION_NOT_FOUND,
            message=f"Action '{action_id}' not found.",
            request_id=req_id
        )

    # RBAC Authorization Check
    authz_scope = AuthorizationScope(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
        session_id=identity.session_id,
        plant_id=getattr(action.target, "plant_id", None)
    )
    authz_ctx = AuthorizationContext(
        identity=identity.to_user_identity(),
        required_permission="action.simulate",
        scope=authz_scope
    )
    authz_decision = authorization_service.evaluate(authz_ctx)
    if authz_decision.effect == AuthzDecisionEffect.DENY:
        return action_error_response(403, "AUTHORIZATION_DENIED", authz_decision.reason, req_id)

    simulation = action_validator.generate_simulation(action)

    try:
        actor = LedgerActor(
            actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
            actor_id=identity.user_id,
            acting_user_id=identity.user_id,
            roles=getattr(identity, "roles", [])
        )
        audit_ledger.record_event(
            event_type=EventType.ACTION_SIMULATION_COMPLETED.value,
            actor=actor,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            session_id=action.session_id,
            plant_id=getattr(action.target, "plant_id", None),
            category=EventCategory.SIMULATION,
            action_id=action.action_id,
            correlation_id=action.incident_id or action.mission_id or action.action_id,
            request_id=req_id,
            resource_type="action",
            resource_id=action.action_id,
            data_mode="SIMULATION",
            payload={"action_id": action.action_id, "simulation": simulation.dict()}
        )
    except Exception:
        pass

    return ActionSimulationResponse(
        success=True,
        request_id=req_id,
        simulation=simulation,
        preview=action.generate_human_preview()
    )


# =====================================================================
# 6. CANCEL ACTION (POST /{action_id}/cancel)
# =====================================================================

@router.post(
    "/{action_id}/cancel",
    response_model=ActionCancellationResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel Action Proposal",
    description="Cancels an action in PROPOSED, VALIDATING, or AWAITING_APPROVAL status."
)
async def cancel_action_endpoint(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    action = action_store.get_by_id(action_id, identity.tenant_id)

    if not action:
        return action_error_response(
            status_code=404,
            code=ActionErrorCode.ACTION_NOT_FOUND,
            message=f"Action '{action_id}' not found.",
            request_id=req_id
        )

    # RBAC Authorization Check
    authz_scope = AuthorizationScope(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
        session_id=identity.session_id,
        plant_id=getattr(action.target, "plant_id", None)
    )
    authz_ctx = AuthorizationContext(
        identity=identity.to_user_identity(),
        required_permission="action.cancel",
        scope=authz_scope,
        action_id=action_id
    )
    authz_decision = authorization_service.evaluate(authz_ctx)
    if authz_decision.effect == AuthzDecisionEffect.DENY:
        return action_error_response(403, "AUTHORIZATION_DENIED", authz_decision.reason, req_id)

    # Check cancellable status
    cancellable_statuses = [
        ActionStatus.PROPOSED,
        ActionStatus.VALIDATING,
        ActionStatus.POLICY_REVIEW,
        ActionStatus.AWAITING_APPROVAL
    ]
    if action.status not in cancellable_statuses:
        return action_error_response(
            status_code=400,
            code=ActionErrorCode.ACTION_IMMUTABLE,
            message=f"Action '{action_id}' cannot be cancelled in status '{action.status.value}'.",
            request_id=req_id
        )

    action_store.update_status(action_id, identity.tenant_id, ActionStatus.CANCELLED)

    log_security_event(
        event_name="ACTION_CANCELLED",
        user_id=identity.user_id,
        details={"tenant_id": identity.tenant_id, "action_id": action_id, "previous_status": action.status.value}
    )

    try:
        actor = LedgerActor(
            actor_type=ActorType.AGENT if identity.user_id.startswith("agent_") else ActorType.USER,
            actor_id=identity.user_id,
            acting_user_id=identity.user_id,
            roles=getattr(identity, "roles", [])
        )
        audit_ledger.record_event(
            event_type=EventType.ACTION_CANCELLED.value,
            actor=actor,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            session_id=action.session_id,
            plant_id=getattr(action.target, "plant_id", None),
            category=EventCategory.ACTION,
            action_id=action.action_id,
            correlation_id=action.incident_id or action.mission_id or action.action_id,
            request_id=req_id,
            resource_type="action",
            resource_id=action.action_id,
            data_mode=action.data_mode,
            payload={"action_id": action.action_id, "previous_status": action.status.value}
        )
    except Exception:
        pass

    return ActionCancellationResponse(
        success=True,
        request_id=req_id,
        action_id=action_id,
        status=ActionStatus.CANCELLED
    )


# =====================================================================
# 7. APPROVE ACTION (POST /{action_id}/approve)
# =====================================================================

@router.post(
    "/{action_id}/approve",
    response_model=ActionDetailResponse,
    summary="Approve Structured Action",
    description="Grants explicit human approval to an action awaiting review, enforcing separation of duties."
)
async def approve_action(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    action = action_store.get_by_id(action_id, identity.tenant_id)
    if not action:
        return action_error_response(404, ActionErrorCode.ACTION_NOT_FOUND, f"Action '{action_id}' not found.", req_id)

    # ABAC Authorization Check: action.approve with Separation of Duties
    authz_scope = AuthorizationScope(
        tenant_id=identity.tenant_id,
        workspace_id=action.workspace_id,
        session_id=identity.session_id,
        plant_id=getattr(action.target, "plant_id", None)
    )
    authz_ctx = AuthorizationContext(
        identity=identity.to_user_identity(),
        required_permission="action.approve",
        scope=authz_scope,
        action_id=action.action_id,
        action_proposer_id=action.requested_by
    )
    decision = authorization_service.evaluate(authz_ctx)
    if decision.effect == AuthzDecisionEffect.DENY:
        return action_error_response(403, "AUTHORIZATION_DENIED", decision.reason, req_id)

    if action.status not in (ActionStatus.AWAITING_APPROVAL, ActionStatus.POLICY_REVIEW, ActionStatus.PROPOSED, ActionStatus.READY):
        return action_error_response(
            400,
            ActionErrorCode.ACTION_IMMUTABLE,
            f"Action '{action_id}' cannot be approved in status '{action.status.value}'.",
            req_id
        )

    updated = action_store.update_status(action_id, identity.tenant_id, ActionStatus.APPROVED)
    log_security_event(
        "ACTION_APPROVED",
        {"user_id": identity.user_id, "action_id": action_id, "tenant_id": identity.tenant_id},
        severity="INFO"
    )

    target_action = updated or action
    return ActionDetailResponse(
        success=True,
        request_id=req_id,
        action=target_action,
        preview=target_action.generate_human_preview()
    )


# =====================================================================
# 8. EXECUTION GATEWAY BOUNDARY (POST /{action_id}/execute)
# =====================================================================

@router.post(
    "/{action_id}/execute",
    response_model=ActionExecuteResponse,
    summary="Execute Structured Action",
    description="Multi-gate deterministic execution of a structured action through the V3 Execution Gateway."
)
async def execute_action(
    action_id: str,
    request: Optional[ExecutionRequest] = None,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    exec_req = request or ExecutionRequest(action_id=action_id)
    if idempotency_key and not exec_req.idempotency_key:
        exec_req.idempotency_key = idempotency_key

    try:
        result = execution_gateway.execute_action(
            action_id=action_id,
            identity=identity,
            request=exec_req
        )
        return ActionExecuteResponse(
            success=True,
            request_id=req_id,
            result=result
        )
    except ExecutionGatewayException as ex:
        return action_error_response(
            status_code=ex.status_code,
            code=ex.code,
            message=ex.message,
            request_id=req_id,
            details=[ex.details] if ex.details else []
        )
    except Exception as ex:
        return action_error_response(
            status_code=500,
            code="INTERNAL_EXECUTION_ERROR",
            message=str(ex),
            request_id=req_id
        )

