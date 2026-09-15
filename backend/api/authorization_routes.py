# backend/api/authorization_routes.py
"""
SageCommand V3 — Authorization API Endpoints
Base Prefix: /api/v3/authorization
Provides inspection of permissions, roles, and programmatic permission checks.
Supports tamper-evident decision auditing and acyclic role inspection.
"""

import re
import uuid
from typing import Optional
from fastapi import APIRouter, Header, Depends, status, HTTPException

try:
    from core.auth import Identity, get_current_identity, require_permission
    from governance.rate_limiter import rate_limiter
    from governance.audit import log_security_event
    from data.schemas.authorization_contract import (
        Role,
        Permission,
        AuthorizationContext,
        AuthorizationCheckRequest,
        AuthorizationCheckResponse,
        RoleListResponse,
        RoleDetailResponse,
        PermissionListResponse,
        AuthzDecisionEffect,
        AuthzReasonCode,
    )
    from services.authorization_service import authorization_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.governance.rate_limiter import rate_limiter
    from backend.governance.audit import log_security_event
    from backend.data.schemas.authorization_contract import (
        Role,
        Permission,
        AuthorizationContext,
        AuthorizationCheckRequest,
        AuthorizationCheckResponse,
        RoleListResponse,
        RoleDetailResponse,
        PermissionListResponse,
        AuthzDecisionEffect,
        AuthzReasonCode,
    )
    from backend.services.authorization_service import authorization_service

router = APIRouter(prefix="/api/v3/authorization", tags=["Authorization Layer"])


def extract_request_id(x_request_id: Optional[str] = None) -> str:
    if x_request_id:
        sanitized = re.sub(r"[^\w\-]", "", x_request_id)[:64]
        if sanitized:
            return sanitized
    return f"req_{uuid.uuid4().hex[:12]}"


# =====================================================================
# 1. PROGRAMMATIC CAPABILITY EVALUATION
# =====================================================================

@router.post(
    "/check",
    response_model=AuthorizationCheckResponse,
    summary="Evaluate Authorization Context",
    description="Deterministically evaluates RBAC capabilities and ABAC attributes against a target scope."
)
async def check_authorization(
    request: AuthorizationCheckRequest,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)

    # 1. Rate Limiting
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

    # 2. Build canonical authorization context
    user_identity = identity.to_user_identity()
    context = AuthorizationContext(
        identity=user_identity,
        required_permission=request.required_permission,
        scope=request.target_scope,
        action_id=request.action_id,
        target_resource=request.target_resource,
        data_mode=request.data_mode,
        proposer_id=request.proposer_id,
        required_clearance=request.required_clearance,
        environment_attributes=request.context_attributes
    )

    # 3. Deterministic Evaluation
    decision = authorization_service.evaluate(context)

    return AuthorizationCheckResponse(
        success=True,
        request_id=req_id,
        decision=decision
    )


# =====================================================================
# 2. PERMISSION CATALOG
# =====================================================================

@router.get(
    "/permissions",
    response_model=PermissionListResponse,
    summary="List Canonical Permissions",
    description="Returns the authoritative catalog of system permissions with descriptions and sensitivity flags."
)
async def list_permissions(
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    permissions = authorization_service.permission_registry.list_permissions()
    return PermissionListResponse(
        success=True,
        request_id=req_id,
        permissions=permissions
    )


# =====================================================================
# 3. ROLE INSPECTION
# =====================================================================

@router.get(
    "/roles",
    response_model=RoleListResponse,
    summary="List Roles",
    description="Returns all registered system and custom roles."
)
async def list_roles(
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    roles = authorization_service.role_registry.list_roles()
    return RoleListResponse(
        success=True,
        request_id=req_id,
        roles=roles
    )


@router.get(
    "/roles/{role_id}",
    response_model=RoleDetailResponse,
    summary="Get Role Details & Effective Permissions",
    description="Retrieves a specific role definition and its transitively resolved permissions."
)
async def get_role(
    role_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(get_current_identity)
):
    req_id = extract_request_id(x_request_id)
    role = authorization_service.role_registry.get_role(role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Role '{role_id.upper()}' not found in role registry."
        )

    try:
        effective_perms, _ = authorization_service.role_registry.resolve_effective_permissions([role.role_id])
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role inheritance cycle detected: {str(e)}"
        )

    return RoleDetailResponse(
        success=True,
        request_id=req_id,
        role=role,
        effective_permissions=effective_perms
    )
