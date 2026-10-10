# backend/api/confidence_uncertainty_routes.py
"""
SageCommand V3 — Confidence and Uncertainty Intelligence Foundation API Routes (Prompt 32)

Versioned REST endpoints rooted at /api/v3/confidence-uncertainty.
Enforces authentication, RBAC/ABAC permissions, tenant isolation,
plant boundary restrictions, payload bounds, and non-disclosing error responses.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from core.config import SAGE_CONFIDENCE_MAX_BATCH_SIZE
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyRequest,
        ConfidenceUncertaintyResult,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyListResponse,
        ConfidenceEvidenceReference,
        ConfidenceUncertaintySummary,
        ConfidenceAuditRecord,
    )
    from services.confidence_uncertainty_service import (
        ConfidenceUncertaintyService,
        confidence_uncertainty_service,
    )
    from repositories.confidence_uncertainty_repository import (
        confidence_uncertainty_repository,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.core.config import SAGE_CONFIDENCE_MAX_BATCH_SIZE
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyRequest,
        ConfidenceUncertaintyResult,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyListResponse,
        ConfidenceEvidenceReference,
        ConfidenceUncertaintySummary,
        ConfidenceAuditRecord,
    )
    from backend.services.confidence_uncertainty_service import (
        ConfidenceUncertaintyService,
        confidence_uncertainty_service,
    )
    from backend.repositories.confidence_uncertainty_repository import (
        confidence_uncertainty_repository,
    )

router = APIRouter(
    prefix="/api/v3/confidence-uncertainty",
    tags=["Confidence and Uncertainty Intelligence"],
)


# ---------------------------------------------------------------------------
# POST /api/v3/confidence-uncertainty/assess
# ---------------------------------------------------------------------------

@router.post("/assess", response_model=ConfidenceUncertaintyResult)
async def assess_confidence_uncertainty(
    request: ConfidenceUncertaintyRequest,
    user: Identity = Depends(require_permission("confidence_uncertainty.assess")),
):
    """
    Evaluates multi-dimensional confidence and decomposed uncertainty for an analytical claim or target.
    Enforces tenant partition isolation and authorized plant scope.
    """
    # Tenant boundary enforcement: prevent caller-supplied spoofing
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot assess entities in a different tenant partition.",
        )

    # Plant scope enforcement
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        result = confidence_uncertainty_service.assess(request, actor_id=actor_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# POST /api/v3/confidence-uncertainty/assess/batch
# ---------------------------------------------------------------------------

@router.post("/assess/batch", response_model=List[ConfidenceUncertaintyResult])
async def assess_confidence_uncertainty_batch(
    requests: List[ConfidenceUncertaintyRequest],
    user: Identity = Depends(require_permission("confidence_uncertainty.assess")),
):
    """
    Bounded batch evaluation of confidence and uncertainty across multiple targets.
    """
    if len(requests) > SAGE_CONFIDENCE_MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Batch size exceeds maximum limit of {SAGE_CONFIDENCE_MAX_BATCH_SIZE} items.",
        )

    results = []
    actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")

    for req in requests:
        if user.tenant_id != req.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant boundary violation in batch payload.",
            )
        if user.assigned_plants and "*" not in user.assigned_plants:
            if req.plant_id and req.plant_id not in user.assigned_plants:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Plant boundary violation in batch item for plant '{req.plant_id}'.",
                )
        results.append(confidence_uncertainty_service.assess(req, actor_id=actor_id))

    return results


# ---------------------------------------------------------------------------
# POST /api/v3/confidence-uncertainty/validate
# ---------------------------------------------------------------------------

@router.post("/validate", response_model=ConfidenceValidationResponse)
async def validate_confidence_eligibility(
    request: ConfidenceValidationRequest,
    user: Identity = Depends(require_permission("confidence_uncertainty.validate")),
):
    """
    Validates evidence readiness and eligibility for confidence assessment.
    """
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot validate evidence across tenant partitions.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        return confidence_uncertainty_service.validate_eligibility(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# GET /api/v3/confidence-uncertainty/entity/{entity_id}/summary
# ---------------------------------------------------------------------------

@router.get("/entity/{entity_id}/summary", response_model=List[ConfidenceUncertaintySummary])
async def get_entity_confidence_summary(
    entity_id: str,
    target_type: Optional[str] = Query(None, description="Optional filter by target analytical subsystem"),
    limit: int = Query(20, ge=1, le=100, description="Max history items"),
    user: Identity = Depends(require_permission("confidence_uncertainty.read")),
):
    """
    Retrieves authorized confidence and uncertainty summaries for a target entity.
    """
    summaries = confidence_uncertainty_repository.list_history(
        target_id=entity_id,
        tenant_id=user.tenant_id,
        target_type=target_type,
        limit=limit,
    )
    return summaries


# ---------------------------------------------------------------------------
# GET /api/v3/confidence-uncertainty/{assessment_id}/evidence
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}/evidence", response_model=List[ConfidenceEvidenceReference])
async def get_assessment_evidence(
    assessment_id: str,
    user: Identity = Depends(require_permission("confidence_uncertainty.read")),
):
    """
    Retrieves the supporting and conflicting evidence references for an assessment.
    """
    result = confidence_uncertainty_repository.get_by_id(assessment_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment '{assessment_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    return result.supporting_evidence + result.conflicting_evidence


# ---------------------------------------------------------------------------
# GET /api/v3/confidence-uncertainty/{assessment_id}/history
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}/history", response_model=List[ConfidenceUncertaintySummary])
async def get_assessment_history(
    assessment_id: str,
    limit: int = Query(20, ge=1, le=100),
    user: Identity = Depends(require_permission("confidence_uncertainty.read")),
):
    """
    Retrieves historical assessments for the entity referenced by assessment_id.
    """
    curr = confidence_uncertainty_repository.get_by_id(assessment_id, user.tenant_id)
    if not curr:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment '{assessment_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if curr.plant_id and curr.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{curr.plant_id}'.",
            )

    return confidence_uncertainty_repository.list_history(
        target_id=curr.target_id,
        tenant_id=user.tenant_id,
        target_type=curr.target_type,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/confidence-uncertainty/{assessment_id}
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}", response_model=ConfidenceUncertaintyResult)
async def get_assessment(
    assessment_id: str,
    user: Identity = Depends(require_permission("confidence_uncertainty.read")),
):
    """
    Retrieves an assessment by ID enforcing tenant and plant isolation.
    """
    result = confidence_uncertainty_repository.get_by_id(assessment_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Assessment '{assessment_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    return result


# ---------------------------------------------------------------------------
# GET /api/v3/confidence-uncertainty
# ---------------------------------------------------------------------------

@router.get("", response_model=ConfidenceUncertaintyListResponse)
async def list_assessments(
    limit: int = Query(50, ge=1, le=200, description="Max items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    workspace_id: Optional[str] = Query(None, description="Optional workspace filter"),
    plant_id: Optional[str] = Query(None, description="Optional plant filter"),
    target_type: Optional[str] = Query(None, description="Optional target subsystem filter"),
    user: Identity = Depends(require_permission("confidence_uncertainty.read")),
):
    """
    Paginated listing of confidence assessments within authorized scope.
    """
    # Restrict plant if user is plant-scoped
    effective_plant = plant_id
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id:
            if plant_id not in user.assigned_plants:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'.",
                )
        else:
            effective_plant = user.assigned_plants[0] if user.assigned_plants else None

    items = confidence_uncertainty_repository.list_assessments(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant,
        target_type=target_type,
        limit=limit,
        offset=offset,
    )
    total_count = confidence_uncertainty_repository.count_assessments(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant,
        target_type=target_type,
    )

    return ConfidenceUncertaintyListResponse(
        items=items,
        total_count=total_count,
        limit=limit,
        offset=offset,
    )
