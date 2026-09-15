# backend/api/policy_routes.py
"""
SageCommand V3 — Policy Enforcement Engine API Endpoints
Base Prefix: /api/v3/policies
Provides deterministic evaluation of structured actions against active system policies,
policy simulation, and versioned policy registry administration.

Strictly preserves the Prompt 05 execution boundary: zero operational mutations occur here.
"""

import uuid
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, Depends, Query, HTTPException, status
from fastapi.responses import JSONResponse

try:
    from core.auth import Identity, get_current_identity, require_role
    from governance.rate_limiter import rate_limiter
    from governance.audit import log_security_event
    from data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyEvaluationContext,
        PolicyDecision,
        EvaluatePolicyRequest,
        SimulatePolicyRequest,
        PolicyResponse,
        PolicyListResponse,
        PolicyDecisionResponse,
        PolicySimulationResponse,
    )
    from services.action_store import action_store
    from services.policy_service import policy_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_role
    from backend.governance.rate_limiter import rate_limiter
    from backend.governance.audit import log_security_event
    from backend.data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from backend.data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyEvaluationContext,
        PolicyDecision,
        EvaluatePolicyRequest,
        SimulatePolicyRequest,
        PolicyResponse,
        PolicyListResponse,
        PolicyDecisionResponse,
        PolicySimulationResponse,
    )
    from backend.services.action_store import action_store
    from backend.services.policy_service import policy_service

router = APIRouter(prefix="/api/v3/policies", tags=["Policy Engine V3"])


def policy_error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    details: Optional[Any] = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "request_id": request_id,
            "error": {
                "code": code,
                "message": message,
                "details": details or []
            }
        }
    )


# =====================================================================
# 1. EVALUATION & SIMULATION ENDPOINTS
# =====================================================================

@router.post(
    "/evaluate",
    response_model=PolicyDecisionResponse,
    summary="Evaluate an existing structured action against system policies"
)
async def evaluate_action_policy(
    request: EvaluatePolicyRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    """
    Evaluates an existing, validated Structured Action against authoritative system policy.
    The client cannot dictate tenant_id, risk, or policy decisions.
    """
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"

    # Rate limiting
    is_allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not is_allowed:
        return policy_error_response(
            status_code=429,
            code="RATE_LIMIT_EXCEEDED",
            message="Rate limit exceeded. Please throttle your evaluation requests.",
            request_id=req_id
        )

    # 1. Fetch action from persistent repository
    action = action_store.get(request.action_id)
    if not action:
        return policy_error_response(
            status_code=404,
            code="ACTION_NOT_FOUND",
            message=f"Action '{request.action_id}' not found.",
            request_id=req_id
        )

    # 2. Strict Tenant Isolation Boundary
    if action.tenant_id != identity.tenant_id:
        log_security_event(
            event_name="CROSS_TENANT_ACCESS_BLOCKED",
            user_id=identity.user_id,
            details={
                "action_tenant": action.tenant_id,
                "caller_tenant": identity.tenant_id,
                "action_id": request.action_id
            },
            severity="WARNING"
        )
        return policy_error_response(
            status_code=404,
            code="ACTION_NOT_FOUND",
            message=f"Action '{request.action_id}' not found in tenant partition.",
            request_id=req_id
        )

    # 3. Construct Authoritative Server-Side Evaluation Context
    context = PolicyEvaluationContext(
        tenant_id=identity.tenant_id,
        workspace_id=getattr(identity, "workspace_id", "workspace_default") or "workspace_default",
        session_id=identity.session_id or "session_default",
        user_id=identity.user_id,
        plant_id=action.target.plant_id,
        roles=identity.roles,
        permissions=identity.permissions,
        data_mode=action.data_mode
    )

    # 4. Perform Deterministic Policy Evaluation
    decision = policy_service.evaluate(
        action=action,
        context=context,
        policy_ids=request.policy_ids,
        persist_decision=True
    )
    decision.request_id = req_id

    return PolicyDecisionResponse(
        success=True,
        request_id=req_id,
        decision=decision
    )


@router.post(
    "/simulate",
    response_model=PolicySimulationResponse,
    summary="Simulate policy evaluation on an action without persisting side-effects"
)
async def simulate_action_policy(
    request: SimulatePolicyRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    """
    Dry-run simulation of policy evaluation against an Action and optional hypothetical policies.
    Guaranteed zero operational mutation and zero action status modification.
    """
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"

    try:
        # Rehydrate or parse action payload
        action_data = request.action.copy()
        # Enforce server identity boundary
        action_data["tenant_id"] = identity.tenant_id
        action_data["workspace_id"] = getattr(identity, "workspace_id", "workspace_default") or "workspace_default"
        action = Action(**action_data)
    except Exception as e:
        return policy_error_response(
            status_code=400,
            code="INVALID_ACTION_PAYLOAD",
            message=f"Failed to parse action payload for policy simulation: {str(e)}",
            request_id=req_id
        )

    context = PolicyEvaluationContext(
        tenant_id=identity.tenant_id,
        workspace_id=action.workspace_id,
        session_id=identity.session_id or "session_default",
        user_id=identity.user_id,
        plant_id=action.target.plant_id,
        roles=identity.roles,
        permissions=identity.permissions,
        data_mode=action.data_mode
    )

    decision = policy_service.simulate(
        action=action,
        context=context,
        hypothetical_policies=request.hypothetical_policies
    )
    decision.request_id = req_id

    return PolicySimulationResponse(
        success=True,
        request_id=req_id,
        decision=decision,
        simulation=True
    )


# =====================================================================
# 2. POLICY DEFINITION CRUD & LIFECYCLE ENDPOINTS
# =====================================================================

@router.get(
    "",
    response_model=PolicyListResponse,
    summary="List active system policies for the authenticated tenant"
)
async def list_policies(
    active_only: bool = Query(True, description="Filter for active policies only"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    """Lists registered governance policies scoped to caller's tenant."""
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"
    policies = policy_service.store.list_policies(tenant_id=identity.tenant_id, active_only=active_only)

    return PolicyListResponse(
        success=True,
        request_id=req_id,
        policies=policies,
        total=len(policies)
    )


@router.get(
    "/{policy_id}",
    response_model=PolicyResponse,
    summary="Retrieve active policy definition by ID"
)
async def get_policy(
    policy_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    """Retrieves policy definition by policy_id."""
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"
    policy = policy_service.store.get_policy(policy_id)

    if not policy:
        return policy_error_response(
            status_code=404,
            code="POLICY_NOT_FOUND",
            message=f"Policy '{policy_id}' not found.",
            request_id=req_id
        )

    # Check tenant scope
    p_tenant = policy.scope.get("tenant_id")
    if p_tenant and p_tenant != identity.tenant_id:
        return policy_error_response(
            status_code=404,
            code="POLICY_NOT_FOUND",
            message=f"Policy '{policy_id}' not found in tenant scope.",
            request_id=req_id
        )

    return PolicyResponse(
        success=True,
        request_id=req_id,
        policy=policy
    )


@router.get(
    "/{policy_id}/versions/{version}",
    response_model=PolicyResponse,
    summary="Retrieve specific immutable historical policy version"
)
async def get_policy_version(
    policy_id: str,
    version: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    """Retrieves a specific immutable historical version of a policy."""
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"
    policy = policy_service.store.get_policy(policy_id, version=version)

    if not policy:
        return policy_error_response(
            status_code=404,
            code="POLICY_VERSION_NOT_FOUND",
            message=f"Policy '{policy_id}' version '{version}' not found.",
            request_id=req_id
        )

    return PolicyResponse(
        success=True,
        request_id=req_id,
        policy=policy
    )


@router.post(
    "",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new versioned policy (Manager clearance required)"
)
async def create_policy(
    policy: Policy,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    """
    Registers or updates a versioned policy. Requires Manager role clearance.
    Enforces separation-of-duties: ordinary operators cannot create or edit policies.
    """
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"

    # Enforce tenant isolation in scope if not set
    if not policy.scope.get("tenant_id") and identity.tenant_id != "tenant_default":
        policy.scope["tenant_id"] = identity.tenant_id

    policy.created_by = identity.user_id
    saved = policy_service.store.save_policy(policy)

    log_security_event(
        event_name="POLICY_VERSION_CREATED",
        user_id=identity.user_id,
        details={
            "policy_id": saved.policy_id,
            "policy_version": saved.policy_version,
            "status": saved.status.value,
            "priority": saved.priority
        }
    )

    return PolicyResponse(
        success=True,
        request_id=req_id,
        policy=saved
    )


@router.post(
    "/{policy_id}/activate",
    response_model=PolicyResponse,
    summary="Activate a policy (Manager clearance required)"
)
async def activate_policy(
    policy_id: str,
    version: Optional[str] = Query(None, description="Specific version to activate"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    """Activates a policy. Requires Manager authorization."""
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"
    policy = policy_service.store.get_policy(policy_id, version=version)

    if not policy:
        return policy_error_response(
            status_code=404,
            code="POLICY_NOT_FOUND",
            message=f"Policy '{policy_id}' not found.",
            request_id=req_id
        )

    policy.status = PolicyLifecycle.ACTIVE
    saved = policy_service.store.save_policy(policy)

    log_security_event(
        event_name="POLICY_VERSION_ACTIVATED",
        user_id=identity.user_id,
        details={
            "policy_id": saved.policy_id,
            "policy_version": saved.policy_version,
            "status": saved.status.value
        }
    )

    return PolicyResponse(
        success=True,
        request_id=req_id,
        policy=saved
    )


@router.post(
    "/{policy_id}/disable",
    response_model=PolicyResponse,
    summary="Disable a policy (Manager clearance required)"
)
async def disable_policy(
    policy_id: str,
    version: Optional[str] = Query(None, description="Specific version to disable"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_role("manager"))
):
    """Disables a policy. Requires Manager authorization."""
    req_id = x_request_id or f"req_{uuid.uuid4().hex[:8]}"
    policy = policy_service.store.get_policy(policy_id, version=version)

    if not policy:
        return policy_error_response(
            status_code=404,
            code="POLICY_NOT_FOUND",
            message=f"Policy '{policy_id}' not found.",
            request_id=req_id
        )

    policy.status = PolicyLifecycle.DISABLED
    saved = policy_service.store.save_policy(policy)

    log_security_event(
        event_name="POLICY_VERSION_DISABLED",
        user_id=identity.user_id,
        details={
            "policy_id": saved.policy_id,
            "policy_version": saved.policy_version,
            "status": saved.status.value
        }
    )

    return PolicyResponse(
        success=True,
        request_id=req_id,
        policy=saved
    )
