from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import uuid
from datetime import datetime, UTC

from core.auth import Identity, require_permission
from services.sla_customer_risk_repository import sla_customer_risk_repository
from services.sla_customer_risk_service import sla_customer_risk_service
from data.schemas.sla_customer_risk_contract import SLACustomerRiskAssessment

router = APIRouter(prefix="/api/v3/sla-customer-risk", tags=["SLA Customer Risk Intelligence"])

class SLAAnalyzeRequest(BaseModel):
    tenant_id: str
    workspace_id: Optional[str] = None
    customer_id: str
    service_id: str
    observation_start: str
    observation_end: str
    assessment_timestamp: Optional[str] = None
    commitment_due_at: Optional[str] = None
    expected_completion_at: Optional[str] = None
    evidence_payloads: List[Dict[str, Any]] = Field(default_factory=list)
    historical_data: Dict[str, Any] = Field(default_factory=dict)
    capacity_data: Dict[str, Any] = Field(default_factory=dict)
    demand_data: Dict[str, Any] = Field(default_factory=dict)

@router.post("/analyze", response_model=SLACustomerRiskAssessment)
async def analyze_sla_risk(
    request: SLAAnalyzeRequest,
    user: Identity = Depends(require_permission("sla_customer_risk.analyze"))
):
    """
    Deterministically analyze SLA and Customer risk based on provided evidence.
    """
    # Enforce tenant boundaries
    if user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant boundary violation")

    assessment_timestamp = request.assessment_timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")

    assessment = sla_customer_risk_service.analyze(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        customer_id=request.customer_id,
        service_id=request.service_id,
        observation_start=request.observation_start,
        observation_end=request.observation_end,
        assessment_timestamp=assessment_timestamp,
        commitment_due_at=request.commitment_due_at,
        expected_completion_at=request.expected_completion_at,
        evidence_payloads=request.evidence_payloads,
        historical_data=request.historical_data,
        capacity_data=request.capacity_data,
        demand_data=request.demand_data
    )
    return assessment

@router.get("/{assessment_id}", response_model=SLACustomerRiskAssessment)
async def get_assessment(
    assessment_id: str,
    user: Identity = Depends(require_permission("sla_customer_risk.read"))
):
    """
    Retrieve a specific assessment by ID.
    """
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id
    
    assessment = sla_customer_risk_repository.get_assessment(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id
    )
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return assessment

@router.get("/customer/{customer_id}/summary", response_model=List[SLACustomerRiskAssessment])
async def get_customer_summary(
    customer_id: str,
    limit: int = 50,
    user: Identity = Depends(require_permission("sla_customer_risk.read"))
):
    """
    Retrieve recent assessments for a customer.
    """
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id
    
    # Cap limit to bounded config
    if limit > 100:
        limit = 100
        
    assessments = sla_customer_risk_repository.get_customer_summary(
        customer_id=customer_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit
    )
    return assessments

@router.get("", response_model=List[SLACustomerRiskAssessment])
async def list_assessments(
    limit: int = 50,
    user: Identity = Depends(require_permission("sla_customer_risk.read"))
):
    """
    List recent SLA Risk assessments in the tenant/workspace.
    """
    tenant_id = user.tenant_id
    workspace_id = user.workspace_id
    
    if limit > 100:
        limit = 100
        
    assessments = sla_customer_risk_repository.get_history(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        limit=limit
    )
    return assessments
