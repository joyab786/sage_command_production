"""
backend/api/optimization_routes.py

SageCommand V3 — Optimization Intelligence API Routes (Prompt 29)

ANALYTICAL DECISION SUPPORT ONLY.
Provides REST access to deterministic optimization problems, candidate solutions,
feasibility assessments, trade-off assessments, parameter sensitivity analysis,
and evidence chains.

Does NOT execute physical actuation, PLC writes, maintenance work orders,
procurement actions, or inventory adjustments.

Base path: /api/v3/optimization
Permissions:
  optimization.read     — view optimization problems, candidates, trade-offs, and evidence
  optimization.analyze  — formulate and solve deterministic optimization problems
  optimization.evaluate — evaluate candidate solutions, constraint violations, and sensitivity
  optimization.admin    — administrative access to optimization settings and bounds
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, require_permission
    from data.schemas.optimization_contract import (
        OptimizationResult,
        OptimizationAnalyzeRequest,
        OptimizationListResponse,
        OptimizationCandidatesResponse,
        OptimizationSensitivityResponse,
        OptimizationEvidenceResponse,
    )
    from repositories.optimization_repository import optimization_repository
    from services.optimization_service import optimization_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.optimization_contract import (
        OptimizationResult,
        OptimizationAnalyzeRequest,
        OptimizationListResponse,
        OptimizationCandidatesResponse,
        OptimizationSensitivityResponse,
        OptimizationEvidenceResponse,
    )
    from backend.repositories.optimization_repository import optimization_repository
    from backend.services.optimization_service import optimization_service


router = APIRouter(
    prefix="/api/v3/optimization",
    tags=["Optimization Intelligence"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/optimization/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=OptimizationResult)
async def analyze_optimization(
    request: OptimizationAnalyzeRequest,
    user: Identity = Depends(require_permission("optimization.analyze")),
):
    """
    Formulates and deterministically solves an industrial optimization problem.
    ANALYTICAL DECISION SUPPORT ONLY. Returns recommendations; never executes commands.
    """
    # Strict tenant isolation
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot run optimization across tenant partition.",
        )

    # Enforce plant isolation
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'.",
            )

    try:
        result = optimization_service.analyze(request)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# GET /api/v3/optimization/{optimization_id}
# ---------------------------------------------------------------------------

@router.get("/{optimization_id}", response_model=OptimizationResult)
async def get_optimization(
    optimization_id: str,
    user: Identity = Depends(require_permission("optimization.read")),
):
    """Retrieves a specific optimization result by ID strictly partitioned by tenant."""
    result = optimization_repository.get_by_id(optimization_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization result '{optimization_id}' not found for tenant '{user.tenant_id}'.",
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: access to plant '{result.plant_id}' denied.",
            )

    return result


# ---------------------------------------------------------------------------
# GET /api/v3/optimization
# ---------------------------------------------------------------------------

@router.get("", response_model=OptimizationListResponse)
async def list_optimizations(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    plant_id: Optional[str] = Query(None, description="Filter by plant ID"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    user: Identity = Depends(require_permission("optimization.read")),
):
    """Returns bounded, paginated list of optimization summaries isolated by tenant."""
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: access to plant '{plant_id}' denied.",
            )
        if not plant_id:
            items = []
            for p in user.assigned_plants:
                items.extend(
                    optimization_repository.list_results(
                        tenant_id=user.tenant_id,
                        workspace_id=workspace_id,
                        plant_id=p,
                        limit=limit,
                    )
                )
            items = items[:limit]
            return OptimizationListResponse(items=items, total_count=len(items))

    items = optimization_repository.list_results(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id,
        limit=limit,
    )
    total_count = optimization_repository.count_results(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id,
    )

    return OptimizationListResponse(items=items, total_count=total_count)


# ---------------------------------------------------------------------------
# GET /api/v3/optimization/{optimization_id}/candidates
# ---------------------------------------------------------------------------

@router.get("/{optimization_id}/candidates", response_model=OptimizationCandidatesResponse)
async def get_optimization_candidates(
    optimization_id: str,
    user: Identity = Depends(require_permission("optimization.read")),
):
    """Retrieves ranked candidate solutions for an optimization run."""
    result = optimization_repository.get_by_id(optimization_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization '{optimization_id}' not found.",
        )

    candidates = optimization_repository.get_candidates(optimization_id, user.tenant_id)
    return OptimizationCandidatesResponse(
        optimization_id=optimization_id,
        candidates=candidates or result.candidates,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/optimization/{optimization_id}/sensitivity
# ---------------------------------------------------------------------------

@router.get("/{optimization_id}/sensitivity", response_model=OptimizationSensitivityResponse)
async def get_optimization_sensitivity(
    optimization_id: str,
    user: Identity = Depends(require_permission("optimization.read")),
):
    """Retrieves parameter sensitivity analysis and robustness assessment."""
    result = optimization_repository.get_by_id(optimization_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization '{optimization_id}' not found.",
        )

    sensitivities = optimization_repository.get_sensitivity(optimization_id, user.tenant_id)
    return OptimizationSensitivityResponse(
        optimization_id=optimization_id,
        sensitivity_results=sensitivities or result.sensitivity_analysis,
        robustness=result.robustness,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/optimization/{optimization_id}/evidence
# ---------------------------------------------------------------------------

@router.get("/{optimization_id}/evidence", response_model=OptimizationEvidenceResponse)
async def get_optimization_evidence(
    optimization_id: str,
    user: Identity = Depends(require_permission("optimization.read")),
):
    """Retrieves complete evidence chain supporting an optimization recommendation."""
    result = optimization_repository.get_by_id(optimization_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Optimization '{optimization_id}' not found.",
        )

    evidence_list = optimization_repository.get_evidence(optimization_id, user.tenant_id)
    return OptimizationEvidenceResponse(
        optimization_id=optimization_id,
        evidence=evidence_list or result.evidence,
    )
