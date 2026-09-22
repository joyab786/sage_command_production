from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from pydantic import BaseModel, Field

try:
    from core.auth import get_current_identity
    from data.schemas.authorization_contract import (
        UserIdentity, AuthorizationScope, AuthorizationContext, AuthzDecisionEffect
    )
    from services.authorization_service import authorization_service
    from data.schemas.demand_forecasting_contract import (
        DemandForecast, ForecastEvaluation, Granularity, ForecastHorizon, DemandObservation
    )
    from services.demand_forecasting_service import demand_forecasting_service
except ModuleNotFoundError:
    from backend.core.auth import get_current_identity
    from backend.data.schemas.authorization_contract import (
        UserIdentity, AuthorizationScope, AuthorizationContext, AuthzDecisionEffect
    )
    from backend.services.authorization_service import authorization_service
    from backend.data.schemas.demand_forecasting_contract import (
        DemandForecast, ForecastEvaluation, Granularity, ForecastHorizon, DemandObservation
    )
    from backend.services.demand_forecasting_service import demand_forecasting_service

router = APIRouter(prefix="/api/v3/demand-forecasting", tags=["Demand Forecasting"])

class ForecastRequest(BaseModel):
    target_scope: AuthorizationScope
    demand_entity_id: str = Field(..., description="Entity ID to forecast")
    horizon: ForecastHorizon
    granularity: Granularity
    observations: List[DemandObservation]
    evaluation_timestamp: Optional[str] = None

class ForecastResponse(BaseModel):
    success: bool
    forecast: DemandForecast

class EvaluateRequest(BaseModel):
    target_scope: AuthorizationScope
    forecast_id: str
    actual_observations: List[DemandObservation]

class EvaluateResponse(BaseModel):
    success: bool
    evaluation: ForecastEvaluation

def _authorize(identity: UserIdentity, permission: str, scope: AuthorizationScope):
    ctx = AuthorizationContext(
        identity=identity,
        required_permission=permission,
        scope=scope,
        data_mode="LIVE"
    )
    decision = authorization_service.evaluate(ctx)
    if decision.effect != AuthzDecisionEffect.ALLOW:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Authorization denied: {decision.reason}"
        )

@router.post("/forecast", response_model=ForecastResponse)
def generate_forecast(
    req: ForecastRequest,
    identity: UserIdentity = Depends(get_current_identity)
):
    _authorize(identity, "demand_forecasting.analyze", req.target_scope)
    
    # Strictly enforce boundaries
    if req.target_scope.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
        
    try:
        forecast = demand_forecasting_service.generate_forecast(
            tenant_id=req.target_scope.tenant_id,
            workspace_id=req.target_scope.workspace_id,
            plant_id=req.target_scope.plant_id,
            demand_entity_id=req.target_entity_id if hasattr(req, "target_entity_id") else req.demand_entity_id,
            horizon=req.horizon,
            granularity=req.granularity,
            observations=req.observations,
            evaluation_timestamp=req.evaluation_timestamp
        )
        return ForecastResponse(success=True, forecast=forecast)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/forecast/{forecast_id}", response_model=ForecastResponse)
def get_forecast(
    forecast_id: str,
    target_tenant: str,
    identity: UserIdentity = Depends(get_current_identity)
):
    scope = AuthorizationScope(tenant_id=target_tenant)
    _authorize(identity, "demand_forecasting.read", scope)
    
    forecast = demand_forecasting_service.get_forecast(forecast_id, target_tenant)
    if not forecast:
        raise HTTPException(status_code=404, detail="Forecast not found")
        
    return ForecastResponse(success=True, forecast=forecast)

class ForecastsListResponse(BaseModel):
    success: bool
    forecasts: List[DemandForecast]

@router.get("/forecasts", response_model=ForecastsListResponse)
def query_forecasts(
    target_tenant: str,
    entity_id: Optional[str] = None,
    identity: UserIdentity = Depends(get_current_identity)
):
    scope = AuthorizationScope(tenant_id=target_tenant)
    _authorize(identity, "demand_forecasting.read", scope)
    
    forecasts = demand_forecasting_service.query_forecasts(target_tenant, entity_id)
    return ForecastsListResponse(success=True, forecasts=forecasts)

@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate_forecast(
    req: EvaluateRequest,
    identity: UserIdentity = Depends(get_current_identity)
):
    _authorize(identity, "demand_forecasting.evaluate", req.target_scope)
    
    try:
        evaluation = demand_forecasting_service.evaluate_forecast(
            forecast_id=req.forecast_id,
            tenant_id=req.target_scope.tenant_id,
            actual_observations=req.actual_observations
        )
        return EvaluateResponse(success=True, evaluation=evaluation)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
