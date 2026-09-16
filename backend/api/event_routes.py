# backend/api/event_routes.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
import sqlite3

try:
    from data.schemas.event_contract import CanonicalEvent
    from services.event_repository import EventRepository
    from services.event_bus import get_event_bus, EventBus
    from core.auth import Identity, require_permission
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.event_contract import CanonicalEvent
    from backend.services.event_repository import EventRepository
    from backend.services.event_bus import get_event_bus, EventBus
    from backend.core.auth import Identity, require_permission

router = APIRouter(prefix="/api/v3/events", tags=["events"])

# Dependency
def get_event_repo() -> EventRepository:
    return EventRepository()

@router.post("", response_model=CanonicalEvent, status_code=status.HTTP_201_CREATED)
async def record_event(
    event: CanonicalEvent,
    identity: Identity = Depends(require_permission("events.record")),
    repo: EventRepository = Depends(get_event_repo),
    bus: EventBus = Depends(get_event_bus)
):
    """
    Records an immutable canonical event.
    Automatically enforces tenant isolation based on the authenticated identity.
    After persisting the canonical record, the event is safely dispatched to the internal Event Bus.
    """
    if event.tenant_id != identity.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot record event for a different tenant."
        )

    # Compute deterministic fingerprint if missing
    if not event.event_fingerprint:
        event.apply_fingerprint()

    try:
        saved_event = repo.record_event(event)
        # Dispatch asynchronously to the event bus
        await bus.publish(saved_event)
        return saved_event
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate event fingerprint.")

@router.get("", response_model=List[CanonicalEvent], dependencies=[Depends(require_permission("events.read"))])
async def list_events(
    limit: int = 50,
    offset: int = 0,
    category: str = None,
    event_type: str = None,
    severity: str = None,
    workspace_id: str = None,
    plant_id: str = None,
    identity: Identity = Depends(require_permission("events.read")),
    repo: EventRepository = Depends(get_event_repo)
):
    filters = {}
    if category: filters["category"] = category
    if event_type: filters["event_type"] = event_type
    if severity: filters["severity"] = severity
    if workspace_id: filters["workspace_id"] = workspace_id
    if plant_id: filters["plant_id"] = plant_id

    return repo.list_events(tenant_id=identity.tenant_id, limit=limit, offset=offset, filters=filters)

@router.get("/fingerprint/{fingerprint}", response_model=CanonicalEvent, dependencies=[Depends(require_permission("events.read"))])
async def get_event_by_fingerprint(
    fingerprint: str,
    identity: Identity = Depends(require_permission("events.read")),
    repo: EventRepository = Depends(get_event_repo)
):
    event = repo.get_event_by_fingerprint(tenant_id=identity.tenant_id, fingerprint=fingerprint)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event

@router.get("/{event_id}", response_model=CanonicalEvent, dependencies=[Depends(require_permission("events.read"))])
async def get_event(
    event_id: str,
    identity: Identity = Depends(require_permission("events.read")),
    repo: EventRepository = Depends(get_event_repo)
):
    event = repo.get_event(tenant_id=identity.tenant_id, event_id=event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    return event
