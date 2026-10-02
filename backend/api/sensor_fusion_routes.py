"""
backend/api/sensor_fusion_routes.py

SageCommand V3 — Multimodal Sensor Fusion Intelligence API Routes (Prompt 27)

ANALYTICAL ONLY.
Provides access to multimodal sensor fusion assessments, cross-modal agreement,
correlations, and sensor reliability.
Does NOT execute physical actuation, PLC writes, maintenance work orders, or
procurement actions.

Base path: /api/v3/sensor-fusion
Permissions:
  sensor_fusion.read    — view assessments and summaries
  sensor_fusion.analyze — trigger deterministic multimodal fusion analysis
  sensor_fusion.admin   — administrative access
"""

from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, require_permission
    from data.schemas.sensor_fusion_contract import (
        FusionAssessment,
        SensorFusionAnalyzeRequest,
        SensorFusionListResponse,
        SensorEntitySummaryResponse,
    )
    from services.sensor_fusion_repository import sensor_fusion_repository
    from services.sensor_fusion_service import sensor_fusion_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.sensor_fusion_contract import (
        FusionAssessment,
        SensorFusionAnalyzeRequest,
        SensorFusionListResponse,
        SensorEntitySummaryResponse,
    )
    from backend.services.sensor_fusion_repository import sensor_fusion_repository
    from backend.services.sensor_fusion_service import sensor_fusion_service


router = APIRouter(
    prefix="/api/v3/sensor-fusion",
    tags=["Multimodal Sensor Fusion Intelligence"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/sensor-fusion/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=FusionAssessment)
async def analyze_sensor_fusion(
    request: SensorFusionAnalyzeRequest,
    user: Identity = Depends(require_permission("sensor_fusion.analyze")),
):
    """
    Deterministically fuses multimodal industrial observations.
    ANALYTICAL ONLY. No PLC writes or equipment controls.
    """
    # Strict tenant isolation
    if user.tenant_id != request.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant boundary violation: cannot analyze across tenant partition."
        )

    # Enforce plant isolation if user has plant restrictions
    if user.assigned_plants and "*" not in user.assigned_plants:
        if request.plant_id and request.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: user not authorized for plant '{request.plant_id}'."
            )

    try:
        assessment = sensor_fusion_service.analyze(request)
        return assessment
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )


# ---------------------------------------------------------------------------
# GET /api/v3/sensor-fusion/assessment/{assessment_id}
# ---------------------------------------------------------------------------

@router.get("/assessment/{assessment_id}", response_model=FusionAssessment)
async def get_sensor_fusion_assessment(
    assessment_id: str,
    user: Identity = Depends(require_permission("sensor_fusion.read")),
):
    """
    Retrieves a specific multimodal sensor fusion assessment by ID.
    """
    assessment = sensor_fusion_repository.get_assessment(
        assessment_id=assessment_id,
        tenant_id=user.tenant_id
    )
    if not assessment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sensor fusion assessment '{assessment_id}' not found."
        )

    # Plant-level access check
    if user.assigned_plants and "*" not in user.assigned_plants:
        if assessment.plant_id and assessment.plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: not authorized for plant '{assessment.plant_id}'."
            )

    return assessment


# ---------------------------------------------------------------------------
# GET /api/v3/sensor-fusion/assessments
# ---------------------------------------------------------------------------

@router.get("/assessments", response_model=SensorFusionListResponse)
async def list_sensor_fusion_assessments(
    workspace_id: Optional[str] = None,
    plant_id: Optional[str] = None,
    target_entity_id: Optional[str] = None,
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    user: Identity = Depends(require_permission("sensor_fusion.read")),
):
    """
    Queries historical multimodal sensor fusion assessments with tenant scoping.
    """
    # Enforce plant restriction
    effective_plant = plant_id
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: not authorized for plant '{plant_id}'."
            )
        elif not plant_id and len(user.assigned_plants) == 1:
            effective_plant = user.assigned_plants[0]

    assessments = sensor_fusion_repository.list_assessments(
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=effective_plant,
        target_entity_id=target_entity_id,
        limit=limit,
        offset=offset
    )
    total_count = len(assessments)
    return SensorFusionListResponse(
        assessments=assessments,
        total_count=total_count
    )


# ---------------------------------------------------------------------------
# GET /api/v3/sensor-fusion/entities/{entity_id}/summary
# ---------------------------------------------------------------------------

@router.get("/entities/{entity_id}/summary", response_model=SensorEntitySummaryResponse)
async def get_sensor_entity_summary(
    entity_id: str,
    workspace_id: Optional[str] = None,
    plant_id: Optional[str] = None,
    user: Identity = Depends(require_permission("sensor_fusion.read")),
):
    """
    Returns an analytical summary of sensor reliability and multimodal state for an entity.
    """
    if user.assigned_plants and "*" not in user.assigned_plants:
        if plant_id and plant_id not in user.assigned_plants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plant boundary violation: not authorized for plant '{plant_id}'."
            )

    summary = sensor_fusion_repository.get_entity_summary(
        target_entity_id=entity_id,
        tenant_id=user.tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id
    )
    return summary
