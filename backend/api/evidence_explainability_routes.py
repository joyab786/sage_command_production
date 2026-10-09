# backend/api/evidence_explainability_routes.py
"""
SageCommand V3 — Evidence and Explainability API Routes (Prompt 31)

ANALYTICAL EXPLAINABILITY AND EVIDENCE TRACING ONLY.
Provides REST endpoints for deterministic evidence explanations, lineage graph traversal,
evidence validation batches, and immutable audit ledgers.

Does NOT execute physical actuation, PLC writes, maintenance work orders,
procurement actions, inventory adjustments, or bypass the human decision boundary.

Base path: /api/v3/evidence-explainability
Permissions:
  evidence_explainability.read     — view evidence records, lineage graphs, explanations, and audit history
  evidence_explainability.explain  — generate deterministic evidence explanations and lineage traces
  evidence_explainability.validate — validate evidence items, freshness, provenance, and temporal validity
  evidence_explainability.admin    — administrative authority over evidence explainability configuration
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, require_permission
    from data.schemas.evidence_explainability_contract import (
        ExplanationRequest,
        ExplanationResult,
        EvidenceValidationRequest,
        EvidenceValidationBatchResponse,
        ExplanationListResponse,
        ExplanationLineageResponse,
        ExplanationEvidenceResponse,
        ExplanationAuditResponse,
        EvidenceSourceType,
    )
    from repositories.evidence_explainability_repository import evidence_explainability_repository
    from services.evidence_explainability_service import evidence_explainability_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.evidence_explainability_contract import (
        ExplanationRequest,
        ExplanationResult,
        EvidenceValidationRequest,
        EvidenceValidationBatchResponse,
        ExplanationListResponse,
        ExplanationLineageResponse,
        ExplanationEvidenceResponse,
        ExplanationAuditResponse,
        EvidenceSourceType,
    )
    from backend.repositories.evidence_explainability_repository import evidence_explainability_repository
    from backend.services.evidence_explainability_service import evidence_explainability_service

router = APIRouter(
    prefix="/api/v3/evidence-explainability",
    tags=["Evidence and Explainability Intelligence Foundation"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/evidence-explainability/explain
# ---------------------------------------------------------------------------

@router.post("/explain", response_model=ExplanationResult)
async def explain_target(
    request: ExplanationRequest,
    user: Identity = Depends(require_permission("evidence_explainability.explain")),
):
    """
    Generates a deterministic explanation for an analytical conclusion or decision recommendation.
    ANALYTICAL EXPLAINABILITY ONLY.
    """
    # Strict tenant isolation
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot explain analytical targets across tenant partition.",
        )

    # Enforce plant isolation
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        explanation = evidence_explainability_service.explain(request, actor_id=actor_id)
        return explanation
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# POST /api/v3/evidence-explainability/validate
# ---------------------------------------------------------------------------

@router.post("/validate", response_model=EvidenceValidationBatchResponse)
async def validate_evidence_batch(
    request: EvidenceValidationRequest,
    user: Identity = Depends(require_permission("evidence_explainability.validate")),
):
    """
    Validates a batch of evidence records deterministically for freshness, scope, and provenance.
    """
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot validate evidence across tenant partition.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        actor_id = getattr(user, "user_id", None) or getattr(user, "sub", "system")
        result = evidence_explainability_service.validate_batch(request, actor_id=actor_id)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# GET /api/v3/evidence-explainability/{explanation_id}
# ---------------------------------------------------------------------------

@router.get("/{explanation_id}", response_model=ExplanationResult)
async def get_explanation(
    explanation_id: str,
    user: Identity = Depends(require_permission("evidence_explainability.read")),
):
    """Retrieves an explanation by ID enforcing tenant and plant isolation."""
    result = evidence_explainability_repository.get_by_id(explanation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explanation '{explanation_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    return result


# ---------------------------------------------------------------------------
# GET /api/v3/evidence-explainability/{explanation_id}/lineage
# ---------------------------------------------------------------------------

@router.get("/{explanation_id}/lineage", response_model=ExplanationLineageResponse)
async def get_explanation_lineage(
    explanation_id: str,
    user: Identity = Depends(require_permission("evidence_explainability.read")),
):
    """Retrieves the bounded evidence lineage graph for an explanation."""
    result = evidence_explainability_repository.get_by_id(explanation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explanation '{explanation_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    lineage = evidence_explainability_repository.get_lineage(explanation_id, user.tenant_id)
    if not lineage:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lineage graph for explanation '{explanation_id}' not found.",
        )

    return ExplanationLineageResponse(explanation_id=explanation_id, lineage_graph=lineage)


# ---------------------------------------------------------------------------
# GET /api/v3/evidence-explainability/{explanation_id}/evidence
# ---------------------------------------------------------------------------

@router.get("/{explanation_id}/evidence", response_model=ExplanationEvidenceResponse)
async def get_explanation_evidence(
    explanation_id: str,
    user: Identity = Depends(require_permission("evidence_explainability.read")),
):
    """Retrieves supporting and excluded evidence items for an explanation."""
    result = evidence_explainability_repository.get_by_id(explanation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explanation '{explanation_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    return ExplanationEvidenceResponse(
        explanation_id=explanation_id,
        supporting_evidence=result.supporting_evidence,
        excluded_evidence=result.excluded_evidence,
        validations=result.validations,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/evidence-explainability/{explanation_id}/audit
# ---------------------------------------------------------------------------

@router.get("/{explanation_id}/audit", response_model=ExplanationAuditResponse)
async def get_explanation_audit(
    explanation_id: str,
    user: Identity = Depends(require_permission("evidence_explainability.read")),
):
    """Retrieves immutable audit history ledger for an explanation."""
    result = evidence_explainability_repository.get_by_id(explanation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Explanation '{explanation_id}' not found.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    audit_records = evidence_explainability_repository.get_audit_history(explanation_id, user.tenant_id)
    return ExplanationAuditResponse(explanation_id=explanation_id, audit_records=audit_records)


# ---------------------------------------------------------------------------
# GET /api/v3/evidence-explainability
# ---------------------------------------------------------------------------

@router.get("", response_model=ExplanationListResponse)
async def list_explanations(
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    target_type: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    plant_id: Optional[str] = Query(None),
    user: Identity = Depends(require_permission("evidence_explainability.read")),
):
    """Lists historical explanations for caller's tenant with pagination and optional filters."""
    effective_plant_id = plant_id
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'.",
            )
        if not plant_id and len(user.assigned_plants) == 1:
            effective_plant_id = user.assigned_plants[0]

    items = evidence_explainability_repository.list_explanations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
        target_type=target_type,
        limit=limit,
        offset=offset,
    )
    total_count = evidence_explainability_repository.count_explanations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
        target_type=target_type,
    )

    return ExplanationListResponse(items=items, total_count=total_count)
