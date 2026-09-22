import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel

try:
    from core.auth import get_current_identity, Identity
    from data.schemas.predictive_maintenance_contract import MaintenanceRiskAssessment
    from data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope
    from services.authorization_service import authorization_service
    from services.predictive_maintenance_service import predictive_maintenance_service
    from services.predictive_maintenance_repository import predictive_maintenance_repository
except ModuleNotFoundError:
    from backend.core.auth import get_current_identity, Identity
    from backend.data.schemas.predictive_maintenance_contract import MaintenanceRiskAssessment
    from backend.data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope
    from backend.services.authorization_service import authorization_service
    from backend.services.predictive_maintenance_service import predictive_maintenance_service
    from backend.services.predictive_maintenance_repository import predictive_maintenance_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v3/predictive-maintenance", tags=["Predictive Maintenance Intelligence"])


class AnalyzeAssetRequest(BaseModel):
    asset_id: str
    prediction_horizon: str = "P7D"


@router.post("/analyze", response_model=MaintenanceRiskAssessment)
def analyze_asset(
    request: AnalyzeAssetRequest,
    identity: Identity = Depends(get_current_identity)
):
    """
    Triggers deterministic Predictive Maintenance risk assessment.
    """
    # Authorization
    scope = AuthorizationScope(tenant_id=identity.tenant_id, workspace_id=identity.workspace_id)
    ctx = AuthorizationContext(
        identity=identity,
        required_permission="predictive_maintenance.analyze",
        scope=scope
    )
    decision = authorization_service.evaluate(ctx)
    if not decision.is_allowed():
        raise HTTPException(status_code=403, detail=decision.reason)
        
    analysis = predictive_maintenance_service.analyze_asset(
        identity=identity,
        asset_id=request.asset_id,
        prediction_horizon=request.prediction_horizon
    )
    
    return analysis


@router.get("/assessment/{assessment_id}", response_model=MaintenanceRiskAssessment)
def get_assessment(
    assessment_id: str = Path(...),
    identity: Identity = Depends(get_current_identity)
):
    """
    Retrieves a completed Predictive Maintenance assessment by ID.
    """
    # Authorization
    scope = AuthorizationScope(tenant_id=identity.tenant_id, workspace_id=identity.workspace_id)
    ctx = AuthorizationContext(
        identity=identity,
        required_permission="predictive_maintenance.read",
        scope=scope
    )
    decision = authorization_service.evaluate(ctx)
    if not decision.is_allowed():
        raise HTTPException(status_code=403, detail=decision.reason)
        
    assessment = predictive_maintenance_repository.get_assessment(assessment_id, identity.tenant_id)
    if not assessment:
        raise HTTPException(status_code=404, detail=f"Predictive Maintenance assessment '{assessment_id}' not found.")
        
    return assessment


@router.get("/assessments", response_model=List[MaintenanceRiskAssessment])
def list_assessments(
    asset_id: Optional[str] = Query(None),
    limit: int = Query(50, le=100),
    identity: Identity = Depends(get_current_identity)
):
    """
    Lists Predictive Maintenance assessments for the tenant.
    """
    # Authorization
    scope = AuthorizationScope(tenant_id=identity.tenant_id, workspace_id=identity.workspace_id)
    ctx = AuthorizationContext(
        identity=identity,
        required_permission="predictive_maintenance.read",
        scope=scope
    )
    decision = authorization_service.evaluate(ctx)
    if not decision.is_allowed():
        raise HTTPException(status_code=403, detail=decision.reason)
        
    assessments = predictive_maintenance_repository.query_assessments(
        tenant_id=identity.tenant_id,
        asset_id=asset_id,
        limit=limit
    )
        
    return assessments
