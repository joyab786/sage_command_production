# backend/api/data_quality_routes.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List

try:
    from core.auth import Identity, get_current_identity, require_permission
    from services.authorization_service import AuthorizationService
    from services.data_quality_service import DataQualityService
    from services.data_quality_repository import DataQualityRepository
    from services.ontology_service import OntologyService
    from services.knowledge_graph_service import KnowledgeGraphService
    from services.digital_twin_service import DigitalTwinService
    from services.ontology_repository import SQLiteOntologyRepository
    from services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
    from services.digital_twin_repository import DigitalTwinRepository
    from data.schemas.data_quality_contract import (
        QualityRule, QualityIssue, AssessmentRun, AssessmentRequest, AssessmentResponse, IssueListResponse
    )
except ImportError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.services.authorization_service import AuthorizationService
    from backend.services.data_quality_service import DataQualityService
    from backend.services.data_quality_repository import DataQualityRepository
    from backend.services.ontology_service import OntologyService
    from backend.services.knowledge_graph_service import KnowledgeGraphService
    from backend.services.digital_twin_service import DigitalTwinService
    from backend.services.ontology_repository import SQLiteOntologyRepository
    from backend.services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
    from backend.services.digital_twin_repository import DigitalTwinRepository
    from backend.data.schemas.data_quality_contract import (
        QualityRule, QualityIssue, AssessmentRun, AssessmentRequest, AssessmentResponse, IssueListResponse
    )

router = APIRouter(prefix="/api/v3/data-quality", tags=["v3-data-quality"])

# Shared service instances for the router
dq_repo = DataQualityRepository()
ont_svc = OntologyService(SQLiteOntologyRepository())
kg_svc = KnowledgeGraphService(SQLiteKnowledgeGraphRepository(), ont_svc)
dt_svc = DigitalTwinService(DigitalTwinRepository(), ont_svc, kg_svc)
dq_svc = DataQualityService(dq_repo, ont_svc, kg_svc, dt_svc)


@router.get("/rules", response_model=List[QualityRule])
async def list_rules(
    identity: Identity = Depends(require_permission("data_quality.read"))
):
    """Retrieve all active data quality rules for the tenant."""
    return dq_svc.list_rules(identity)


@router.get("/issues", response_model=IssueListResponse)
async def list_issues(
    identity: Identity = Depends(require_permission("data_quality.read"))
):
    """Retrieve all active data quality issues for the tenant."""
    issues = dq_svc.list_issues(identity)
    return IssueListResponse(issues=issues, total_count=len(issues))


@router.get("/assessments", response_model=List[AssessmentRun])
async def list_assessments(
    identity: Identity = Depends(require_permission("data_quality.read"))
):
    """Retrieve recent data quality assessment runs."""
    return dq_svc.get_assessments(identity)


@router.get("/assessments/{assessment_id}", response_model=AssessmentRun)
async def get_assessment(
    assessment_id: str,
    identity: Identity = Depends(require_permission("data_quality.read"))
):
    """Retrieve a specific data quality assessment run."""
    assessment = dq_svc.get_assessment(identity, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return assessment


@router.post("/assess", response_model=AssessmentRun)
async def run_assessment(
    request: AssessmentRequest,
    identity: Identity = Depends(require_permission("data_quality.assess"))
):
    """Trigger a deterministic data quality assessment for the specified scope."""
    # Strict boundary enforcement
    if request.scope.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant assessment strictly forbidden")
    
    return dq_svc.run_assessment(identity, request.scope)
