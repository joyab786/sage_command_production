import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel

try:
    from core.auth import get_current_identity, Identity
    from core.config import SAGE_BLAST_RADIUS_MAX_DEPTH, SAGE_BLAST_RADIUS_MAX_NODES
    from data.schemas.blast_radius_contract import BlastRadiusAnalysis
    from data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope
    from services.authorization_service import authorization_service
    from services.blast_radius_service import blast_radius_service
    from services.blast_radius_repository import blast_radius_repository
except ModuleNotFoundError:
    from backend.core.auth import get_current_identity, Identity
    from backend.core.config import SAGE_BLAST_RADIUS_MAX_DEPTH, SAGE_BLAST_RADIUS_MAX_NODES
    from backend.data.schemas.blast_radius_contract import BlastRadiusAnalysis
    from backend.data.schemas.authorization_contract import AuthorizationContext, AuthorizationScope
    from backend.services.authorization_service import authorization_service
    from backend.services.blast_radius_service import blast_radius_service
    from backend.services.blast_radius_repository import blast_radius_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v3/blast-radius", tags=["Blast-Radius Intelligence"])

class AnalyzeBlastRadiusRequest(BaseModel):
    source_entity_id: str
    source_incident_id: Optional[str] = None
    source_anomaly_id: Optional[str] = None
    max_depth: int = SAGE_BLAST_RADIUS_MAX_DEPTH
    max_nodes: int = SAGE_BLAST_RADIUS_MAX_NODES

@router.post("/analyze", response_model=BlastRadiusAnalysis)
def analyze_blast_radius(
    request: AnalyzeBlastRadiusRequest,
    identity: Identity = Depends(get_current_identity)
):
    """
    Triggers deterministic Blast-Radius impact analysis.
    """
    # Authorization
    scope = AuthorizationScope(tenant_id=identity.tenant_id, workspace_id=identity.workspace_id)
    ctx = AuthorizationContext(
        identity=identity,
        required_permission="blast_radius.analyze",
        scope=scope
    )
    decision = authorization_service.evaluate(ctx)
    if not decision.is_allowed():
        raise HTTPException(status_code=403, detail=decision.reason)
        
    analysis = blast_radius_service.analyze_impact(
        identity=identity,
        source_entity_id=request.source_entity_id,
        source_incident_id=request.source_incident_id,
        source_anomaly_id=request.source_anomaly_id,
        max_depth=request.max_depth,
        max_nodes=request.max_nodes
    )
    
    return analysis

@router.get("/{analysis_id}", response_model=BlastRadiusAnalysis)
def get_analysis(
    analysis_id: str = Path(...),
    identity: Identity = Depends(get_current_identity)
):
    """
    Retrieves a completed Blast-Radius analysis by ID.
    """
    # Authorization
    scope = AuthorizationScope(tenant_id=identity.tenant_id, workspace_id=identity.workspace_id)
    ctx = AuthorizationContext(
        identity=identity,
        required_permission="blast_radius.read",
        scope=scope
    )
    decision = authorization_service.evaluate(ctx)
    if not decision.is_allowed():
        raise HTTPException(status_code=403, detail=decision.reason)
        
    analysis = blast_radius_repository.get_analysis(analysis_id, identity.tenant_id)
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Blast radius analysis '{analysis_id}' not found.")
        
    return analysis
