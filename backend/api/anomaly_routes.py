# backend/api/anomaly_routes.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List

try:
    from core.auth import Identity, get_current_identity, require_permission
    from services.anomaly_detection_service import AnomalyDetectionService
    from services.anomaly_repository import AnomalyRepository
    from services.digital_twin_service import DigitalTwinService
    from services.digital_twin_repository import DigitalTwinRepository
    from services.ontology_service import OntologyService
    from services.ontology_repository import SQLiteOntologyRepository
    from services.knowledge_graph_service import KnowledgeGraphService
    from services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
    from services.data_quality_service import DataQualityService
    from services.data_quality_repository import DataQualityRepository
    from data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentRun, 
        AnomalyAssessmentScope, AnomalyListResponse
    )
except ImportError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.services.anomaly_detection_service import AnomalyDetectionService
    from backend.services.anomaly_repository import AnomalyRepository
    from backend.services.digital_twin_service import DigitalTwinService
    from backend.services.digital_twin_repository import DigitalTwinRepository
    from backend.services.ontology_service import OntologyService
    from backend.services.ontology_repository import SQLiteOntologyRepository
    from backend.services.knowledge_graph_service import KnowledgeGraphService
    from backend.services.knowledge_graph_repository import SQLiteKnowledgeGraphRepository
    from backend.services.data_quality_service import DataQualityService
    from backend.services.data_quality_repository import DataQualityRepository
    from backend.data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentRun, 
        AnomalyAssessmentScope, AnomalyListResponse
    )

router = APIRouter(prefix="/api/v3/anomalies", tags=["v3-anomalies"])

# Dependency setup
anomaly_repo = AnomalyRepository()
ont_repo = SQLiteOntologyRepository()
ont_svc = OntologyService(ont_repo)
kg_repo = SQLiteKnowledgeGraphRepository()
kg_svc = KnowledgeGraphService(kg_repo, ont_svc)
dt_repo = DigitalTwinRepository()
dt_svc = DigitalTwinService(dt_repo, ont_svc, kg_svc)
dq_repo = DataQualityRepository()
dq_svc = DataQualityService(dq_repo, ont_svc, kg_svc, dt_svc)

anomaly_svc = AnomalyDetectionService(anomaly_repo, dt_svc, dq_svc)

@router.get("", response_model=AnomalyListResponse)
async def list_anomalies(
    limit: int = 100,
    identity: Identity = Depends(require_permission("anomaly.read"))
):
    """Retrieve anomalies detected within the tenant."""
    if limit > 500:
        limit = 500 # Bounded resource limit
    anomalies = anomaly_svc.get_detections(identity, limit=limit)
    return AnomalyListResponse(anomalies=anomalies, total_count=len(anomalies))

@router.get("/baselines", response_model=List[AnomalyBaseline])
async def list_baselines(
    entity_id: str = None,
    identity: Identity = Depends(require_permission("anomaly.read"))
):
    """Retrieve anomaly detection baselines."""
    return anomaly_repo.list_baselines(identity.tenant_id, entity_id)

@router.post("/detect", response_model=AnomalyAssessmentRun)
async def detect_anomalies(
    scope: AnomalyAssessmentScope,
    identity: Identity = Depends(require_permission("anomaly.detect"))
):
    """Trigger anomaly detection explicitly."""
    # Strict bounds
    if scope.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant execution strictly forbidden")
        
    return anomaly_svc.run_assessment(identity, scope)
