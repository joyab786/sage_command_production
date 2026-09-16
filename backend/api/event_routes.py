# backend/api/event_routes.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request

try:
    from data.schemas.event_contract import CanonicalEvent
    from services.event_repository import event_repository
    from core.auth import Identity, require_permission
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.event_contract import CanonicalEvent
    from backend.services.event_repository import event_repository
    from backend.core.auth import Identity, require_permission

router = APIRouter(prefix="/api/v3/events", tags=["Event Model"])

@router.post("/", response_model=CanonicalEvent)
async def record_event(
    event: CanonicalEvent,
    identity: Identity = Depends(require_permission("events.record"))
):
    """
    Record an immutable event.
    Enforces tenant isolation by overriding the tenant_id with the authoritative context.
    """
    # Authoritative tenant isolation override
    event.tenant_id = identity.tenant_id
    
    # Compute deterministic fingerprint
    event.apply_fingerprint()
    
    try:
        recorded = event_repository.record_event(event)
        return recorded
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/", response_model=List[CanonicalEvent], dependencies=[Depends(require_permission("events.read"))])
async def list_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    category: Optional[str] = None,
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    workspace_id: Optional[str] = None,
    plant_id: Optional[str] = None,
    identity: Identity = Depends(require_permission("events.read"))
):
    """List events with bounded queries and strict tenant isolation."""
    filters = {}
    if category:
        filters["category"] = category
    if event_type:
        filters["event_type"] = event_type
    if severity:
        filters["severity"] = severity
    if workspace_id:
        filters["workspace_id"] = workspace_id
    if plant_id:
        filters["plant_id"] = plant_id

    events = event_repository.list_events(
        tenant_id=identity.tenant_id,
        limit=limit,
        offset=offset,
        filters=filters
    )
    return events

@router.get("/{event_id}", response_model=CanonicalEvent)
async def get_event(
    event_id: str,
    identity: Identity = Depends(require_permission("events.read"))
):
    """Retrieve a single event by ID, bounded by tenant."""
    event = event_repository.get_event(identity.tenant_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@router.get("/fingerprint/{fingerprint}", response_model=CanonicalEvent)
async def get_event_by_fingerprint(
    fingerprint: str,
    identity: Identity = Depends(require_permission("events.read"))
):
    """Retrieve a single event by deterministic fingerprint, bounded by tenant."""
    event = event_repository.get_event_by_fingerprint(identity.tenant_id, fingerprint)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
