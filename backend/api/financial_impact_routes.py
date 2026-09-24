"""
backend/api/financial_impact_routes.py

SageCommand V3 — Financial Impact Intelligence API Routes (Prompt 25)

ANALYTICAL ONLY — These endpoints provide read access to financial impact
assessments. They do NOT execute financial transactions, mutate data, or
trigger any operational systems.

Base path: /api/v3/financial-impact

Permissions:
  financial_impact.read    — read assessments
  financial_impact.analyze — create new assessments
  financial_impact.admin   — administrative access
"""

from datetime import datetime, UTC
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

try:
    from core.auth import Identity, require_permission
    from data.schemas.financial_impact_contract import (
        FinancialImpactAssessment,
        FinancialImpactAnalyzeRequest,
        FinancialImpactSummaryItem,
        FinancialImpactScenario,
    )
    from services.financial_impact_repository import financial_impact_repository
    from services.financial_impact_service import financial_impact_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.financial_impact_contract import (
        FinancialImpactAssessment,
        FinancialImpactAnalyzeRequest,
        FinancialImpactSummaryItem,
        FinancialImpactScenario,
    )
    from backend.services.financial_impact_repository import financial_impact_repository
    from backend.services.financial_impact_service import financial_impact_service


router = APIRouter(
    prefix="/api/v3/financial-impact",
    tags=["Financial Impact Intelligence"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/financial-impact/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=FinancialImpactAssessment)
async def analyze_financial_impact(
    request: FinancialImpactAnalyzeRequest,
    user: Identity = Depends(require_permission("financial_impact.analyze")),
):
    """
    Deterministically analyze financial impact from provided evidence and assumptions.

    ANALYTICAL ONLY. Does not execute any financial transactions.

    Returns a fully-structured FinancialImpactAssessment with:
    - Impact factors per category (UNKNOWN if evidence/assumptions insufficient)
    - Aggregated total exposure (currency-safe)
    - Calculation transparency
    - Evidence and assumption provenance
    - Confidence rating
    """
    # Enforce tenant boundary
    if user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant boundary violation.")

    assessment_timestamp = request.assessment_timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")

    assessment = financial_impact_service.analyze(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        plant_id=request.plant_id,
        customer_id=request.customer_id,
        supplier_id=request.supplier_id,
        asset_id=request.asset_id,
        service_id=request.service_id,
        assessment_timestamp=assessment_timestamp,
        calculation_version=request.calculation_version,
        scenario_name=request.scenario_name,
        custom_scenario_name=request.custom_scenario_name,
        evidence_payloads=request.evidence_payloads,
        raw_assumptions=request.assumptions,
        raw_currency_conversions=request.currency_conversions,
        sla_assessment_id=request.sla_assessment_id,
        supplier_risk_assessment_id=request.supplier_risk_assessment_id,
        maintenance_assessment_id=request.maintenance_assessment_id,
        demand_forecast_id=request.demand_forecast_id,
        blast_radius_id=request.blast_radius_id,
    )
    return assessment


# ---------------------------------------------------------------------------
# GET /api/v3/financial-impact/summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=List[FinancialImpactSummaryItem])
async def list_financial_impact_summary(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    plant_id: Optional[str] = Query(default=None),
    user: Identity = Depends(require_permission("financial_impact.read")),
):
    """
    List lightweight financial impact summary rows for the authenticated
    tenant/workspace. Enforces tenant isolation.
    """
    if limit > _MAX_LIST_LIMIT:
        limit = _MAX_LIST_LIMIT

    return financial_impact_repository.list_summary(
        tenant_id=user.tenant_id,
        workspace_id=user.workspace_id,
        plant_id=plant_id,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/financial-impact
# ---------------------------------------------------------------------------

@router.get("", response_model=List[FinancialImpactAssessment])
async def list_assessments(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    customer_id: Optional[str] = Query(default=None),
    supplier_id: Optional[str] = Query(default=None),
    asset_id: Optional[str] = Query(default=None),
    plant_id: Optional[str] = Query(default=None),
    user: Identity = Depends(require_permission("financial_impact.read")),
):
    """
    List financial impact assessments for the authenticated tenant/workspace.
    Supports optional filtering by customer_id, supplier_id, asset_id, or plant_id.
    """
    if limit > _MAX_LIST_LIMIT:
        limit = _MAX_LIST_LIMIT

    return financial_impact_repository.list_assessments(
        tenant_id=user.tenant_id,
        workspace_id=user.workspace_id,
        plant_id=plant_id,
        customer_id=customer_id,
        supplier_id=supplier_id,
        asset_id=asset_id,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/financial-impact/{assessment_id}
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}", response_model=FinancialImpactAssessment)
async def get_assessment(
    assessment_id: str,
    user: Identity = Depends(require_permission("financial_impact.read")),
):
    """
    Retrieve a specific financial impact assessment by ID.
    Enforces tenant isolation only — workspace is not enforced on direct ID lookup
    because workspace context is embedded in the persisted record and was validated
    at write time.
    """
    assessment = financial_impact_repository.get_assessment(
        assessment_id=assessment_id,
        tenant_id=user.tenant_id,
        # workspace_id intentionally not passed: tenant isolation is sufficient for ID lookup.
        # This matches the pattern of all other V3 intelligence routers.
    )
    if not assessment:
        raise HTTPException(status_code=404, detail="Financial impact assessment not found.")
    return assessment
