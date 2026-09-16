from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.auth import Identity, require_permission
from data.schemas.incident_contract import (
    IncidentContract, IncidentCategory, IncidentSeverity, IncidentPriority, IncidentLifecycle,
    EventRelationshipType, EvidenceType, IncidentTimelineEntry
)
from services.incident_repository import IncidentRepository
from services.incident_service import IncidentService

router = APIRouter(prefix="/api/v3/incidents", tags=["V3 Incidents"])

# Use a singleton pattern similar to other domains, or initialize directly for the router
repo = IncidentRepository()
service = IncidentService(repo)

class CreateIncidentRequest(BaseModel):
    category: IncidentCategory
    title: str
    description: str = ""
    severity: IncidentSeverity = IncidentSeverity.LOW
    priority: IncidentPriority = IncidentPriority.NORMAL
    deduplication_key: Optional[str] = None
    workspace_id: Optional[str] = None
    plant_id: Optional[str] = None

class TransitionRequest(BaseModel):
    new_state: IncidentLifecycle
    reason: str = ""

class UpdateMetadataRequest(BaseModel):
    severity: Optional[IncidentSeverity] = None
    priority: Optional[IncidentPriority] = None

class AssignRequest(BaseModel):
    assigned_user: Optional[str] = None
    assigned_team: Optional[str] = None

class AssociateEventRequest(BaseModel):
    event_id: str
    relationship: EventRelationshipType = EventRelationshipType.RELATED

class AddEvidenceRequest(BaseModel):
    evidence_type: EvidenceType
    source_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AddNoteRequest(BaseModel):
    text: str


@router.post("", response_model=IncidentContract, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("incidents.create"))])
def create_incident(request: CreateIncidentRequest, identity: Identity = Depends(require_permission("incidents.create"))):
    try:
        return service.create_incident(
            tenant_id=identity.tenant_id,
            category=request.category,
            title=request.title,
            actor=identity.user_id,
            description=request.description,
            severity=request.severity,
            priority=request.priority,
            deduplication_key=request.deduplication_key,
            workspace_id=request.workspace_id,
            plant_id=request.plant_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=List[IncidentContract], dependencies=[Depends(require_permission("incidents.read"))])
def list_incidents(identity: Identity = Depends(require_permission("incidents.read")), limit: int = 100):
    if limit > 500:
        limit = 500
    return service.list_incidents(identity.tenant_id, limit)

@router.get("/{incident_id}", response_model=Dict[str, Any], dependencies=[Depends(require_permission("incidents.read"))])
def get_incident_details(incident_id: str, identity: Identity = Depends(require_permission("incidents.read"))):
    try:
        return service.get_incident_details(incident_id, identity.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{incident_id}/lifecycle", response_model=IncidentContract, dependencies=[Depends(require_permission("incidents.transition"))])
def transition_lifecycle(incident_id: str, request: TransitionRequest, identity: Identity = Depends(require_permission("incidents.transition"))):
    try:
        return service.transition_lifecycle(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            new_state=request.new_state,
            actor=identity.user_id,
            reason=request.reason
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/{incident_id}/metadata", response_model=IncidentContract, dependencies=[Depends(require_permission("incidents.update"))])
def update_metadata(incident_id: str, request: UpdateMetadataRequest, identity: Identity = Depends(require_permission("incidents.update"))):
    try:
        return service.update_metadata(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            actor=identity.user_id,
            severity=request.severity,
            priority=request.priority
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/{incident_id}/assignment", response_model=IncidentContract, dependencies=[Depends(require_permission("incidents.assign"))])
def assign_incident(incident_id: str, request: AssignRequest, identity: Identity = Depends(require_permission("incidents.assign"))):
    try:
        return service.assign_incident(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            actor=identity.user_id,
            assigned_user=request.assigned_user,
            assigned_team=request.assigned_team
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{incident_id}/events", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("incidents.update"))])
def associate_event(incident_id: str, request: AssociateEventRequest, identity: Identity = Depends(require_permission("incidents.update"))):
    try:
        service.associate_event(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            event_id=request.event_id,
            actor=identity.user_id,
            relationship=request.relationship
        )
        return {"status": "associated"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{incident_id}/evidence", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("incidents.evidence.write"))])
def add_evidence(incident_id: str, request: AddEvidenceRequest, identity: Identity = Depends(require_permission("incidents.evidence.write"))):
    try:
        service.add_evidence(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            evidence_type=request.evidence_type,
            source_id=request.source_id,
            actor=identity.user_id,
            metadata=request.metadata
        )
        return {"status": "added"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{incident_id}/notes", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("incidents.notes.write"))])
def add_note(incident_id: str, request: AddNoteRequest, identity: Identity = Depends(require_permission("incidents.notes.write"))):
    try:
        service.add_note(
            incident_id=incident_id,
            tenant_id=identity.tenant_id,
            text=request.text,
            actor=identity.user_id
        )
        return {"status": "added"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/{incident_id}/timeline", response_model=List[IncidentTimelineEntry], dependencies=[Depends(require_permission("incidents.read"))])
def get_timeline(incident_id: str, identity: Identity = Depends(require_permission("incidents.read"))):
    try:
        details = service.get_incident_details(incident_id, identity.tenant_id)
        return details["timeline"]
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
