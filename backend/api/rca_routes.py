# backend/api/rca_routes.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

try:
    from core.auth import Identity, require_permission
    from data.schemas.rca_contract import RcaAnalysis
    from services.rca_service import RcaService
    from services.rca_repository import RcaRepository
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.rca_contract import RcaAnalysis
    from backend.services.rca_service import RcaService
    from backend.services.rca_repository import RcaRepository

router = APIRouter(prefix="/api/v3/rca", tags=["RCA"])

# Default singleton repository and service
repo = RcaRepository()
service = RcaService(repository=repo)


class AnalyzeRequest(BaseModel):
    evidence_ids: List[str] = []
    kg_version: str = "latest"
    twin_snapshot_id: str = "current"


@router.post("/analyze/{incident_id}", response_model=RcaAnalysis, status_code=status.HTTP_200_OK, dependencies=[Depends(require_permission("rca.analyze"))])
def analyze_incident(
    incident_id: str,
    request: AnalyzeRequest,
    identity: Identity = Depends(require_permission("rca.analyze"))
):
    """
    Trigger deterministic Root-Cause Analysis for an incident.
    """
    try:
        analysis = service.analyze_incident(
            tenant_id=identity.tenant_id,
            incident_id=incident_id,
            evidence_ids=request.evidence_ids,
            kg_version=request.kg_version,
            twin_snapshot_id=request.twin_snapshot_id,
            workspace_id=identity.workspace_id,
            plant_id=identity.assigned_plants[0] if identity.assigned_plants else None
        )
        return analysis
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error during analysis")


@router.get("/analyses/{incident_id}", response_model=List[RcaAnalysis], dependencies=[Depends(require_permission("rca.read"))])
def list_analyses(
    incident_id: str,
    identity: Identity = Depends(require_permission("rca.read"))
):
    """
    Retrieve previous analyses for an incident.
    """
    try:
        return service.list_analyses(incident_id=incident_id, tenant_id=identity.tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to list analyses")


@router.get("/analysis/{analysis_id}", response_model=RcaAnalysis, dependencies=[Depends(require_permission("rca.read"))])
def get_analysis(
    analysis_id: str,
    identity: Identity = Depends(require_permission("rca.read"))
):
    """
    Get specific analysis by ID.
    """
    analysis = service.get_analysis(analysis_id, identity.tenant_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis
