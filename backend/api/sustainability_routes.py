"""
backend/api/sustainability_routes.py

SageCommand V3 — Sustainability Intelligence API Routes (Prompt 26)

ANALYTICAL ONLY — These endpoints provide access to sustainability impact
assessments. They do NOT execute operational actions, control physical
systems, purchase carbon offsets, submit regulatory filings, or trigger
any environmental-control systems.

Sustainability Intelligence is an analytical system. It does not directly
control physical systems, execute remediation, purchase offsets, submit
regulatory filings, or mutate operational/financial records.

Base path: /api/v3/sustainability

Permissions:
  sustainability.read    — read assessments
  sustainability.analyze — create new assessments
  sustainability.admin   — administrative access
"""

from datetime import datetime, UTC
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

try:
    from core.auth import Identity, require_permission
    from data.schemas.sustainability_contract import (
        SustainabilityAssessment,
        SustainabilityAnalyzeRequest,
        SustainabilityScenarioRequest,
        SustainabilitySummaryItem,
        SustainabilityScenario,
    )
    from services.sustainability_repository import sustainability_repository
    from services.sustainability_service import sustainability_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.sustainability_contract import (
        SustainabilityAssessment,
        SustainabilityAnalyzeRequest,
        SustainabilityScenarioRequest,
        SustainabilitySummaryItem,
        SustainabilityScenario,
    )
    from backend.services.sustainability_repository import sustainability_repository
    from backend.services.sustainability_service import sustainability_service


router = APIRouter(
    prefix="/api/v3/sustainability",
    tags=["Sustainability Intelligence"],
)

_MAX_LIST_LIMIT = 200
_DEFAULT_LIST_LIMIT = 50


# ---------------------------------------------------------------------------
# POST /api/v3/sustainability/analyze
# ---------------------------------------------------------------------------

@router.post("/analyze", response_model=SustainabilityAssessment)
async def analyze_sustainability(
    request: SustainabilityAnalyzeRequest,
    user: Identity = Depends(require_permission("sustainability.analyze")),
):
    """
    Deterministically analyze sustainability impact from provided evidence,
    assumptions, and emissions factors.

    ANALYTICAL ONLY. Does not execute any operational, physical, financial,
    regulatory-filing, offset-purchasing, or environmental-control actions.

    Returns a fully-structured SustainabilityAssessment with:
    - Impact factors per dimension (UNKNOWN if evidence/assumptions insufficient)
    - Sustainability risk classification (analytically separate from measurements)
    - Calculation transparency
    - Evidence and assumption provenance
    - Confidence rating
    - Execution boundary: NO physical/financial actions are triggered.
    """
    # Enforce tenant boundary
    if user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant boundary violation.")

    assessment_timestamp = (
        request.assessment_timestamp
        or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    assessment = sustainability_service.analyze(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        plant_id=request.plant_id,
        asset_id=request.asset_id,
        supplier_id=request.supplier_id,
        customer_id=request.customer_id,
        process_id=request.process_id,
        assessment_timestamp=assessment_timestamp,
        calculation_version=request.calculation_version,
        scenario_name=request.scenario_name,
        custom_scenario_name=request.custom_scenario_name,
        evidence_payloads=request.evidence_payloads,
        raw_assumptions=request.assumptions,
        raw_emissions_factors=request.emissions_factors,
        data_quality_assessment_id=request.data_quality_assessment_id,
        anomaly_id=request.anomaly_id,
        incident_id=request.incident_id,
        blast_radius_id=request.blast_radius_id,
        maintenance_assessment_id=request.maintenance_assessment_id,
        demand_forecast_id=request.demand_forecast_id,
        supplier_risk_assessment_id=request.supplier_risk_assessment_id,
        sla_assessment_id=request.sla_assessment_id,
        financial_impact_assessment_id=request.financial_impact_assessment_id,
    )
    return assessment


# ---------------------------------------------------------------------------
# POST /api/v3/sustainability/scenario
# ---------------------------------------------------------------------------

@router.post("/scenario", response_model=SustainabilityAssessment)
async def run_sustainability_scenario(
    request: SustainabilityScenarioRequest,
    user: Identity = Depends(require_permission("sustainability.analyze")),
):
    """
    Run a sustainability scenario analysis. Scenario-derived values are marked
    SIMULATED. Does NOT mutate operational records.

    ANALYTICAL ONLY.
    """
    # Enforce tenant boundary
    if user.tenant_id != request.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant boundary violation.")

    assessment_timestamp = (
        request.assessment_timestamp
        or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    assessment = sustainability_service.analyze_scenario(
        tenant_id=request.tenant_id,
        workspace_id=request.workspace_id,
        plant_id=request.plant_id,
        asset_id=request.asset_id,
        assessment_timestamp=assessment_timestamp,
        scenario_name=request.scenario_name,
        custom_scenario_name=request.custom_scenario_name,
        scenario_assumptions=request.scenario_assumptions,
        base_evidence_payloads=request.base_evidence_payloads,
        raw_emissions_factors=[],
        calculation_version=request.calculation_version,
    )
    return assessment


# ---------------------------------------------------------------------------
# GET /api/v3/sustainability/summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=List[SustainabilitySummaryItem])
async def list_sustainability_summary(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    plant_id: Optional[str] = Query(default=None),
    user: Identity = Depends(require_permission("sustainability.read")),
):
    """
    List lightweight sustainability summary rows for the authenticated
    tenant/workspace. Enforces tenant isolation.
    """
    if limit > _MAX_LIST_LIMIT:
        limit = _MAX_LIST_LIMIT

    return sustainability_repository.list_summary(
        tenant_id=user.tenant_id,
        workspace_id=user.workspace_id,
        plant_id=plant_id,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/sustainability
# ---------------------------------------------------------------------------

@router.get("", response_model=List[SustainabilityAssessment])
async def list_assessments(
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    asset_id: Optional[str] = Query(default=None),
    supplier_id: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    plant_id: Optional[str] = Query(default=None),
    user: Identity = Depends(require_permission("sustainability.read")),
):
    """
    List sustainability assessments for the authenticated tenant/workspace.
    Supports optional filtering by asset_id, supplier_id, customer_id, or plant_id.
    """
    if limit > _MAX_LIST_LIMIT:
        limit = _MAX_LIST_LIMIT

    return sustainability_repository.list_assessments(
        tenant_id=user.tenant_id,
        workspace_id=user.workspace_id,
        plant_id=plant_id,
        asset_id=asset_id,
        supplier_id=supplier_id,
        customer_id=customer_id,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /api/v3/sustainability/{assessment_id}
# ---------------------------------------------------------------------------

@router.get("/{assessment_id}", response_model=SustainabilityAssessment)
async def get_assessment(
    assessment_id: str,
    user: Identity = Depends(require_permission("sustainability.read")),
):
    """
    Retrieve a specific sustainability assessment by ID.
    Enforces tenant isolation.
    """
    assessment = sustainability_repository.get_assessment(
        assessment_id=assessment_id,
        tenant_id=user.tenant_id,
        # workspace_id intentionally not passed: tenant isolation is sufficient for ID lookup.
        # This matches the pattern of all other V3 intelligence routers.
    )
    if not assessment:
        raise HTTPException(
            status_code=404, detail="Sustainability assessment not found."
        )
    return assessment
