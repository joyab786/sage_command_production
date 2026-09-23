from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime, UTC

try:
    from core.auth import get_current_identity
    from data.schemas.authorization_contract import UserIdentity, AuthorizationScope, AuthorizationContext
    from data.schemas.supplier_risk_contract import SupplierRiskAssessment
    from services.supplier_risk_service import supplier_risk_service
    from services.authorization_service import authorization_service
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import get_current_identity
    from backend.data.schemas.authorization_contract import UserIdentity, AuthorizationScope, AuthorizationContext
    from backend.data.schemas.supplier_risk_contract import SupplierRiskAssessment
    from backend.services.supplier_risk_service import supplier_risk_service
    from backend.services.authorization_service import authorization_service

router = APIRouter(prefix="/api/v3/supplier-risk", tags=["Supplier Risk Intelligence"])

class SupplierRiskAnalyzeRequest(BaseModel):
    supplier_id: str = Field(..., description="Canonical ID of the supplier")
    as_of_timestamp: str = Field(..., description="ISO-8601 UTC timestamp defining boundary")
    observations: List[Dict[str, Any]] = Field(default_factory=list, description="Raw observations for deterministic calculation")

@router.post("/analyze", response_model=SupplierRiskAssessment, summary="Analyze Supplier Risk")
def analyze_supplier_risk(
    req: SupplierRiskAnalyzeRequest,
    identity: UserIdentity = Depends(get_current_identity)
):
    """
    Trigger deterministic supplier risk analysis.
    Produces an intelligence assessment based on operational data, bounded by as_of_timestamp.
    """
    # Enforce RBAC
    user_id_dict = identity.model_dump() if hasattr(identity, "model_dump") else identity.dict()
    user_identity = UserIdentity(**user_id_dict) if not isinstance(identity, UserIdentity) else identity
    scope = AuthorizationScope(tenant_id=user_identity.tenant_id)
    ctx = AuthorizationContext(
        identity=user_identity,
        required_permission="supplier_risk.analyze",
        scope=scope,
        data_mode="HISTORICAL"
    )
    decision = authorization_service.evaluate(ctx)
    if decision.effect.value != "ALLOW":
        raise HTTPException(status_code=403, detail=decision.reason)
        
    try:
        assessment = supplier_risk_service.analyze_supplier_risk(
            tenant_id=identity.tenant_id,
            supplier_id=req.supplier_id,
            as_of_timestamp=req.as_of_timestamp,
            raw_observations=req.observations
        )
        return assessment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal supplier risk engine error: {str(e)}")

@router.get("/assessment/{assessment_id}", response_model=SupplierRiskAssessment, summary="Get Specific Assessment")
def get_specific_assessment(
    assessment_id: str,
    identity: UserIdentity = Depends(get_current_identity)
):
    """
    Retrieve a specific risk assessment by its ID.
    """
    user_id_dict = identity.model_dump() if hasattr(identity, "model_dump") else identity.dict()
    user_identity = UserIdentity(**user_id_dict) if not isinstance(identity, UserIdentity) else identity
    scope = AuthorizationScope(tenant_id=user_identity.tenant_id)
    ctx = AuthorizationContext(
        identity=user_identity,
        required_permission="supplier_risk.read",
        scope=scope,
        data_mode="HISTORICAL"
    )
    decision = authorization_service.evaluate(ctx)
    if decision.effect.value != "ALLOW":
        raise HTTPException(status_code=403, detail=decision.reason)
        
    assessment = supplier_risk_service.get_assessment(tenant_id=identity.tenant_id, assessment_id=assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail=f"Assessment {assessment_id} not found")
    return assessment

@router.get("/suppliers/{supplier_id}/summary", summary="Get Latest Supplier Risk Summary")
def get_supplier_risk_summary(
    supplier_id: str,
    identity: UserIdentity = Depends(get_current_identity)
):
    """
    Retrieve the most recent risk summary for a supplier.
    """
    user_id_dict = identity.model_dump() if hasattr(identity, "model_dump") else identity.dict()
    user_identity = UserIdentity(**user_id_dict) if not isinstance(identity, UserIdentity) else identity
    scope = AuthorizationScope(tenant_id=user_identity.tenant_id)
    ctx = AuthorizationContext(
        identity=user_identity,
        required_permission="supplier_risk.read",
        scope=scope,
        data_mode="LIVE"
    )
    decision = authorization_service.evaluate(ctx)
    if decision.effect.value != "ALLOW":
        raise HTTPException(status_code=403, detail=decision.reason)
        
    summary = supplier_risk_service.get_summary(tenant_id=identity.tenant_id, supplier_id=supplier_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"No risk assessment found for supplier {supplier_id}")
    return summary

@router.get("/suppliers/{supplier_id}/history", response_model=List[SupplierRiskAssessment], summary="Get Supplier Risk History")
def get_supplier_risk_history(
    supplier_id: str,
    limit: int = Query(10, ge=1, le=100),
    identity: UserIdentity = Depends(get_current_identity)
):
    """
    Retrieve historical risk assessments for a supplier.
    """
    user_id_dict = identity.model_dump() if hasattr(identity, "model_dump") else identity.dict()
    user_identity = UserIdentity(**user_id_dict) if not isinstance(identity, UserIdentity) else identity
    scope = AuthorizationScope(tenant_id=user_identity.tenant_id)
    ctx = AuthorizationContext(
        identity=user_identity,
        required_permission="supplier_risk.history",
        scope=scope,
        data_mode="HISTORICAL"
    )
    decision = authorization_service.evaluate(ctx)
    if decision.effect.value != "ALLOW":
        raise HTTPException(status_code=403, detail=decision.reason)
        
    history = supplier_risk_service.get_history(tenant_id=identity.tenant_id, supplier_id=supplier_id, limit=limit)
    return history
