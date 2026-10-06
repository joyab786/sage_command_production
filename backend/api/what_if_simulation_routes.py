"""
backend/api/what_if_simulation_routes.py

SageCommand V3 — What-If Simulation Intelligence API Routes (Prompt 28)

ANALYTICAL ONLY.
Provides access to deterministic counterfactual what-if simulation scenarios,
delta states, impact assessments, constraint evaluations, and evidence chains.
Does NOT execute physical actuation, PLC writes, maintenance work orders,
or procurement actions.

Base path: /api/v3/what-if-simulation
Permissions:
  what_if_simulation.read     — view simulation results, deltas, impacts, and evidence
  what_if_simulation.analyze  — construct and run deterministic counterfactual simulations
  what_if_simulation.evaluate — evaluate constraint violations and multi-dimensional uncertainty
  what_if_simulation.admin    — administrative access to simulation configurations
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, require_permission
    from data.schemas.what_if_simulation_contract import (
        SimulationResult,
        WhatIfAnalyzeRequest,
        WhatIfListResponse,
        WhatIfImpactResponse,
        WhatIfEvidenceResponse,
    )
    from services.what_if_simulation_repository import what_if_simulation_repository
    from services.what_if_simulation_service import what_if_simulation_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.what_if_simulation_contract import (
        SimulationResult,
        WhatIfAnalyzeRequest,
        WhatIfListResponse,
        WhatIfImpactResponse,
        WhatIfEvidenceResponse,
    )
    from backend.services.what_if_simulation_repository import what_if_simulation_repository
    from backend.services.what_if_simulation_service import what_if_simulation_service


router = APIRouter(
    prefix="/api/v3/what-if-simulation",
    tags=["What-If Simulation Intelligence"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/what-if-simulation/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=SimulationResult)
async def analyze_what_if_simulation(
    request: WhatIfAnalyzeRequest,
    user: Identity = Depends(require_permission("what_if_simulation.analyze")),
):
    """
    Constructs and deterministically evaluates a What-If simulation scenario.
    ANALYTICAL ONLY. No physical actuation or operational mutations.
    """
    # Strict tenant boundary enforcement
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot analyze simulation across tenant partition."
        )

    # Enforce plant isolation if user has plant restrictions
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'."
            )

    try:
        result = what_if_simulation_service.analyze(request)
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )


# ---------------------------------------------------------------------------
# GET /api/v3/what-if-simulation/{simulation_id}
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}", response_model=SimulationResult)
async def get_what_if_simulation(
    simulation_id: str,
    user: Identity = Depends(require_permission("what_if_simulation.read")),
):
    """
    Retrieves a complete What-If simulation result by ID strictly partitioned by tenant.
    """
    result = what_if_simulation_repository.get_by_id(simulation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation result '{simulation_id}' not found in tenant '{user.tenant_id}'."
        )

    # Check plant permission if user has plant restrictions
    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'."
            )

    return result


# ---------------------------------------------------------------------------
# GET /api/v3/what-if-simulation
# ---------------------------------------------------------------------------

@router.get("", response_model=WhatIfListResponse)
async def list_what_if_simulations(
    workspace_id: Optional[str] = Query(None, description="Filter by workspace"),
    plant_id: Optional[str] = Query(None, description="Filter by plant"),
    limit: int = Query(_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(0, ge=0),
    user: Identity = Depends(require_permission("what_if_simulation.read")),
):
    """
    Lists paginated simulation summaries partitioned by tenant with optional plant/workspace filters.
    """
    # Enforce plant filter if user is restricted to specific plants
    effective_plant_id = plant_id
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{plant_id}'."
            )
        if not effective_plant_id and len(user.assigned_plants) == 1:
            effective_plant_id = user.assigned_plants[0]

    items = what_if_simulation_repository.list_simulations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
        limit=limit,
        offset=offset,
    )
    total_count = what_if_simulation_repository.count_simulations(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant_id,
    )

    return WhatIfListResponse(items=items, total_count=total_count)


# ---------------------------------------------------------------------------
# GET /api/v3/what-if-simulation/{simulation_id}/impact
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/impact", response_model=WhatIfImpactResponse)
async def get_simulation_impact(
    simulation_id: str,
    user: Identity = Depends(require_permission("what_if_simulation.read")),
):
    """
    Retrieves downstream impact assessments for a specific simulation.
    """
    result = what_if_simulation_repository.get_by_id(simulation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation result '{simulation_id}' not found."
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'."
            )

    return WhatIfImpactResponse(simulation_id=simulation_id, impacts=result.impact_assessments)


# ---------------------------------------------------------------------------
# GET /api/v3/what-if-simulation/{simulation_id}/evidence
# ---------------------------------------------------------------------------

@router.get("/{simulation_id}/evidence", response_model=WhatIfEvidenceResponse)
async def get_simulation_evidence(
    simulation_id: str,
    user: Identity = Depends(require_permission("what_if_simulation.read")),
):
    """
    Retrieves the complete evidence chain supporting a simulation.
    """
    result = what_if_simulation_repository.get_by_id(simulation_id, user.tenant_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Simulation result '{simulation_id}' not found."
        )

    if user.assigned_plants and "*" not in user.assigned_plants:
        if result.plant_id and result.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{result.plant_id}'."
            )

    return WhatIfEvidenceResponse(simulation_id=simulation_id, evidence=result.evidence)
