# backend/api/decision_engine_routes.py
"""
SageCommand V3 — Decision Engine API Routes (Prompt 30)

ANALYTICAL DECISION SUPPORT ONLY.
Provides REST endpoints for deterministic decision evaluation, alternative ranking,
evidence inspection, and immutable decision audit ledgers.

Does NOT execute physical actuation, PLC writes, maintenance work orders,
procurement actions, inventory adjustments, or bypass the human decision boundary.

Base path: /api/v3/decision-engine
Permissions:
  decision_engine.read     — view decision problems, candidate options, evaluations, trade-offs, and audit ledger
  decision_engine.evaluate — evaluate decision problems deterministically against policies and constraints
  decision_engine.admin    — administrative authority over decision engine policies and bounds
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, require_permission
    from data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionEvaluation,
        DecisionListResponse,
        DecisionAlternativesResponse,
        DecisionEvidenceResponse,
        DecisionAuditResponse,
    )
    from repositories.decision_engine_repository import decision_engine_repository
    from services.decision_engine_service import decision_engine_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionEvaluation,
        DecisionListResponse,
        DecisionAlternativesResponse,
        DecisionEvidenceResponse,
        DecisionAuditResponse,
    )
    from backend.repositories.decision_engine_repository import decision_engine_repository
    from backend.services.decision_engine_service import decision_engine_service

router = APIRouter(
    prefix="/api/v3/decision-engine",
    tags=["Decision Engine Foundation"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/decision-engine/evaluate
# ---------------------------------------------------------------------------

@router.post("/evaluate", response_model=DecisionEvaluation)
async def evaluate_decision(
    request: DecisionRequest,
    user: Identity = Depends(require_permission("decision_engine.evaluate")),
):
    """
    Evaluates a candidate decision problem deterministically against policies and constraints.
    ANALYTICAL DECISION SUPPORT ONLY. Returns recommendations; never executes operational commands.
    """
    # Strict tenant isolation
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot evaluate decision across tenant partition.",
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
        evaluation = decision_engine_service.evaluate(request, actor_id=actor_id)
        return evaluation
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# GET /api/v3/decision-engine/{decision_id}
# ---------------------------------------------------------------------------

@router.get("/{decision_id}", response_model=DecisionEvaluation)
async def get_decision_evaluation(
    decision_id: str,
    user: Identity = Depends(require_permission("decision_engine.read")),
):
    """Retrieves an evaluated decision problem by ID enforcing tenant isolation."""
    result = decision_engine_repository.get_by_id(decision_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision evaluation '{decision_id}' not found.",
        )

    # Enforce plant isolation on read
    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'.",
            )

    return result


# ---------------------------------------------------------------------------
# GET /api/v3/decision-engine
# ---------------------------------------------------------------------------

@router.get("", response_model=DecisionListResponse)
async def list_decision_evaluations(
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    decision_type: Optional[str] = Query(None),
    workspace_id: Optional[str] = Query(None),
    plant_id: Optional[str] = Query(None),
    user: Identity = Depends(require_permission("decision_engine.read")),
):
    """Lists historical decision evaluations for the caller's tenant with pagination."""
    # Enforce plant isolation
    effective_plant_id = plant_id
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'.",
            )
        if not plant_id and len(user.assigned_plants) == 1:
            effective_plant_id = user.assigned_plants[0]

    items = decision_engine_repository.list_evaluations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
        decision_type=decision_type,
        limit=limit,
        offset=offset,
    )
    total_count = decision_engine_repository.count_evaluations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
    )

    return DecisionListResponse(items=items, total_count=total_count)


# ---------------------------------------------------------------------------
# GET /api/v3/decision-engine/{decision_id}/alternatives
# ---------------------------------------------------------------------------

@router.get("/{decision_id}/alternatives", response_model=DecisionAlternativesResponse)
async def get_decision_alternatives(
    decision_id: str,
    user: Identity = Depends(require_permission("decision_engine.read")),
):
    """Retrieves ranked candidate alternatives for a decision evaluation."""
    result = decision_engine_repository.get_by_id(decision_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision evaluation '{decision_id}' not found.",
        )

    alternatives = decision_engine_repository.get_alternatives(decision_id, user.tenant_id)
    return DecisionAlternativesResponse(decision_id=decision_id, alternatives=alternatives)


# ---------------------------------------------------------------------------
# GET /api/v3/decision-engine/{decision_id}/evidence
# ---------------------------------------------------------------------------

@router.get("/{decision_id}/evidence", response_model=DecisionEvidenceResponse)
async def get_decision_evidence(
    decision_id: str,
    user: Identity = Depends(require_permission("decision_engine.read")),
):
    """Retrieves evidence references snapshot supporting a decision recommendation."""
    result = decision_engine_repository.get_by_id(decision_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision evaluation '{decision_id}' not found.",
        )

    evidence_list = decision_engine_repository.get_evidence(decision_id, user.tenant_id)
    return DecisionEvidenceResponse(decision_id=decision_id, evidence=evidence_list)


# ---------------------------------------------------------------------------
# GET /api/v3/decision-engine/{decision_id}/audit
# ---------------------------------------------------------------------------

@router.get("/{decision_id}/audit", response_model=DecisionAuditResponse)
async def get_decision_audit(
    decision_id: str,
    user: Identity = Depends(require_permission("decision_engine.read")),
):
    """Retrieves immutable audit history ledger for a decision evaluation."""
    result = decision_engine_repository.get_by_id(decision_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision evaluation '{decision_id}' not found.",
        )

    audit_records = decision_engine_repository.get_audit_history(decision_id, user.tenant_id)
    return DecisionAuditResponse(decision_id=decision_id, audit_records=audit_records)
