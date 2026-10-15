# backend/api/autonomy_routes.py
"""
SageCommand V3 — Autonomy Levels & Guarded Delegation API Routes
Prompt 38 — Implements versioned REST endpoints under /api/v3/autonomy:
- POST /api/v3/autonomy/grants (Create grant)
- GET /api/v3/autonomy/grants (List grants)
- GET /api/v3/autonomy/grants/{grant_id} (Retrieve grant)
- PUT /api/v3/autonomy/grants/{grant_id} (Update grant with optimistic locking)
- POST /api/v3/autonomy/grants/{grant_id}/suspend (Suspend grant)
- DELETE /api/v3/autonomy/grants/{grant_id} (Revoke grant)
- POST /api/v3/autonomy/evaluate (Deterministic capability evaluation)
- GET /api/v3/autonomy/capabilities (List capability registry)
- GET /api/v3/autonomy/decisions (List audit decision trail)

Invariants:
- All endpoints require authenticated server-authoritative caller Identity.
- Tenant isolation is strictly enforced: callers can only access grants within their tenant.
- Execution endpoints (/execute, /run) DO NOT EXIST.
- Safe machine-readable error responses without leaking credentials or raw stack traces.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from data.schemas.autonomy_contract import (
        AutonomyLevel,
        AutonomyGrantStatus,
        SubjectType,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        AutonomyCapabilityDefinition,
        AutonomyScope,
        AutonomyGrant,
        AutonomyDecision,
        AutonomyGrantCreateRequest,
        AutonomyGrantUpdateRequest,
        AutonomyEvaluationRequest,
        AutonomyGrantListResponse,
        default_capability_registry,
    )
    from services.autonomy_service import autonomy_service
    from repositories.autonomy_repository import (
        AutonomyNotFoundError,
        AutonomyConcurrencyError,
        AutonomyInvalidTransitionError,
        AutonomyIdempotencyConflictError,
        AutonomyRepositoryError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.data.schemas.autonomy_contract import (
        AutonomyLevel,
        AutonomyGrantStatus,
        SubjectType,
        AutonomyDecisionEffect,
        AutonomyReasonCode,
        AutonomyCapabilityDefinition,
        AutonomyScope,
        AutonomyGrant,
        AutonomyDecision,
        AutonomyGrantCreateRequest,
        AutonomyGrantUpdateRequest,
        AutonomyEvaluationRequest,
        AutonomyGrantListResponse,
        default_capability_registry,
    )
    from backend.services.autonomy_service import autonomy_service
    from backend.repositories.autonomy_repository import (
        AutonomyNotFoundError,
        AutonomyConcurrencyError,
        AutonomyInvalidTransitionError,
        AutonomyIdempotencyConflictError,
        AutonomyRepositoryError,
    )

logger = logging.getLogger("autonomy_routes")

router = APIRouter(prefix="/api/v3/autonomy", tags=["Autonomy & Guarded Delegation"])


# =============================================================================
# 1. CAPABILITY REGISTRY & LEVEL STATUS
# =============================================================================

@router.get("/capabilities", response_model=List[AutonomyCapabilityDefinition])
def list_capabilities(
    identity: Identity = Depends(get_current_identity)
):
    """
    Returns the canonical capability allowlist with minimum autonomy levels,
    implementation availability, and execution prohibition flags.
    """
    return default_capability_registry.list_all()


@router.get("/levels")
def list_autonomy_levels(
    identity: Identity = Depends(get_current_identity)
):
    """
    Returns the explicit autonomy levels 0-5 and their operational availability.
    Levels 4 and 5 are explicitly documented as DISABLED and NOT_IMPLEMENTED.
    """
    return [
        {
            "level": int(AutonomyLevel.LEVEL_0_OBSERVE),
            "name": "LEVEL_0_OBSERVE",
            "title": AutonomyLevel.LEVEL_0_OBSERVE.title,
            "status": "AVAILABLE",
            "description": "View authorized system state, read telemetry, inspect metadata, receive events.",
            "is_operational": True,
        },
        {
            "level": int(AutonomyLevel.LEVEL_1_ANALYZE),
            "name": "LEVEL_1_ANALYZE",
            "title": AutonomyLevel.LEVEL_1_ANALYZE.title,
            "status": "AVAILABLE",
            "description": "Analyze observations, correlate evidence, identify anomalies, estimate uncertainty.",
            "is_operational": True,
        },
        {
            "level": int(AutonomyLevel.LEVEL_2_RECOMMEND),
            "name": "LEVEL_2_RECOMMEND",
            "title": AutonomyLevel.LEVEL_2_RECOMMEND.title,
            "status": "AVAILABLE",
            "description": "Generate recommendations, identify risks, propose structured actions and mission drafts.",
            "is_operational": True,
        },
        {
            "level": int(AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL),
            "name": "LEVEL_3_PREPARE_FOR_APPROVAL",
            "title": AutonomyLevel.LEVEL_3_PREPARE_FOR_APPROVAL.title,
            "status": "AVAILABLE",
            "description": "Validate action proposals, prepare reviewable preview packages, submit for HITL review.",
            "is_operational": True,
        },
        {
            "level": int(AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION),
            "name": "LEVEL_4_SUPERVISED_EXECUTION",
            "title": AutonomyLevel.LEVEL_4_SUPERVISED_EXECUTION.title,
            "status": "DISABLED",
            "description": "Supervised operational execution gateway — DISABLED AND NOT IMPLEMENTED.",
            "is_operational": False,
        },
        {
            "level": int(AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY),
            "name": "LEVEL_5_BOUNDED_AUTONOMY",
            "title": AutonomyLevel.LEVEL_5_BOUNDED_AUTONOMY.title,
            "status": "NOT_IMPLEMENTED",
            "description": "Autonomous bounded closed-loop operational control — DISABLED AND NOT IMPLEMENTED.",
            "is_operational": False,
        },
    ]


# =============================================================================
# 2. DETERMINISTIC CAPABILITY EVALUATION
# =============================================================================

@router.post("/evaluate", response_model=AutonomyDecision)
def evaluate_capability(
    payload: AutonomyEvaluationRequest,
    identity: Identity = Depends(get_current_identity),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
):
    """
    Evaluates whether a subject is authorized to perform a requested capability.
    Enforces deterministic capability allowlist, scope containment, data mode isolation,
    and underlying authorization integration.
    """
    # Enforce tenant isolation: caller can only evaluate capabilities within its own tenant
    scope = payload.scope
    if scope.tenant_id != identity.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-tenant evaluation forbidden: identity tenant '{identity.tenant_id}' cannot evaluate resource for tenant '{scope.tenant_id}'."
        )

    risk_context = {
        "risk_level": payload.risk_level,
        "cost_estimate_usd": payload.cost_estimate_usd,
        "action_type": payload.action_type,
        "target_resource_id": payload.target_resource_id,
        "proposer_id": identity.user_id,
    }

    decision = autonomy_service.evaluate_autonomy(
        identity=identity,
        subject_type=payload.subject_type,
        subject_id=payload.subject_id,
        requested_capability=payload.requested_capability,
        resource_scope=scope,
        data_mode=payload.data_mode,
        risk_context=risk_context,
        request_id=payload.request_id or x_request_id,
    )
    return decision


# =============================================================================
# 3. AUTONOMY GRANT CRUD & LIFECYCLE
# =============================================================================

@router.post("/grants", response_model=AutonomyGrant, status_code=status.HTTP_201_CREATED)
def create_autonomy_grant(
    payload: AutonomyGrantCreateRequest,
    identity: Identity = Depends(get_current_identity),
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    idempotency_key_hdr: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Creates a new autonomy grant.
    Enforces caller authorization, tenant scope binding, and level restrictions.
    """
    # Prefer header idempotency key if provided
    idempotency_key = idempotency_key_hdr or x_idempotency_key or payload.idempotency_key
    if idempotency_key:
        payload.idempotency_key = idempotency_key

    try:
        grant = autonomy_service.create_grant(identity=identity, request=payload)
        return grant
    except (ValueError, AutonomyIdempotencyConflictError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating autonomy grant: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create autonomy grant.")


@router.get("/grants", response_model=AutonomyGrantListResponse)
def list_autonomy_grants(
    workspace_id: Optional[str] = Query(None),
    subject_type: Optional[SubjectType] = Query(None),
    subject_id: Optional[str] = Query(None),
    status_filter: Optional[AutonomyGrantStatus] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(get_current_identity),
):
    """Lists autonomy grants within caller's authorized tenant scope."""
    try:
        grants, total = autonomy_service.list_grants(
            identity=identity,
            workspace_id=workspace_id,
            subject_type=subject_type,
            subject_id=subject_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return AutonomyGrantListResponse(total=total, grants=grants)
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get("/grants/{grant_id}", response_model=AutonomyGrant)
def get_autonomy_grant(
    grant_id: str,
    workspace_id: Optional[str] = Query(None),
    identity: Identity = Depends(get_current_identity),
):
    """Retrieves a single autonomy grant by ID within caller's authorized tenant."""
    try:
        grant = autonomy_service.get_grant(identity=identity, grant_id=grant_id, workspace_id=workspace_id)
        if not grant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Autonomy grant '{grant_id}' not found in authorized scope."
            )
        return grant
    except HTTPException:
        raise
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/grants/{grant_id}", response_model=AutonomyGrant)
def update_autonomy_grant(
    grant_id: str,
    payload: AutonomyGrantUpdateRequest,
    identity: Identity = Depends(get_current_identity),
):
    """Updates an existing autonomy grant using optimistic locking revision checks."""
    try:
        updated = autonomy_service.update_grant(identity=identity, grant_id=grant_id, request=payload)
        return updated
    except AutonomyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AutonomyConcurrencyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except AutonomyInvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post("/grants/{grant_id}/suspend", response_model=AutonomyGrant)
def suspend_autonomy_grant(
    grant_id: str,
    expected_revision: int = Query(..., ge=1),
    reason: str = Query("Operational safety hold"),
    identity: Identity = Depends(get_current_identity),
):
    """Suspends an active autonomy grant."""
    try:
        suspended = autonomy_service.suspend_grant(
            identity=identity,
            grant_id=grant_id,
            expected_revision=expected_revision,
            reason=reason,
        )
        return suspended
    except AutonomyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AutonomyConcurrencyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except AutonomyInvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.delete("/grants/{grant_id}", response_model=AutonomyGrant)
def revoke_autonomy_grant(
    grant_id: str,
    expected_revision: int = Query(..., ge=1),
    reason: str = Query("Revoked by security policy"),
    identity: Identity = Depends(get_current_identity),
):
    """
    Permanently revokes an autonomy grant.
    Once revoked, the grant cannot be reactivated or edited.
    """
    try:
        revoked = autonomy_service.revoke_grant(
            identity=identity,
            grant_id=grant_id,
            expected_revision=expected_revision,
            reason=reason,
        )
        return revoked
    except AutonomyNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except AutonomyConcurrencyError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except AutonomyInvalidTransitionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# =============================================================================
# 4. DECISION AUDIT TRAIL
# =============================================================================

@router.get("/decisions", response_model=List[AutonomyDecision])
def list_autonomy_decisions(
    workspace_id: Optional[str] = Query(None),
    subject_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
):
    """Retrieves recent autonomy evaluation decisions within caller's authorized tenant."""
    try:
        decisions = autonomy_service.list_decisions(
            identity=identity,
            workspace_id=workspace_id,
            subject_id=subject_id,
            limit=limit,
        )
        return decisions
    except AutonomyRepositoryError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
