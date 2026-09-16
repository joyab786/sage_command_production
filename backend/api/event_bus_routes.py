# backend/api/event_bus_routes.py
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status

try:
    from data.schemas.event_delivery_contract import Subscription, EventDelivery, DeadLetter
    from services.event_bus import get_event_bus, EventBus
    from services.event_delivery_repository import EventDeliveryRepository
    from core.auth import Identity, require_permission
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.event_delivery_contract import Subscription, EventDelivery, DeadLetter
    from backend.services.event_bus import get_event_bus, EventBus
    from backend.services.event_delivery_repository import EventDeliveryRepository
    from backend.core.auth import Identity, require_permission

router = APIRouter(prefix="/api/v3/event-bus", tags=["event_bus"])

def get_delivery_repo(bus: EventBus = Depends(get_event_bus)) -> EventDeliveryRepository:
    return bus.repository

@router.get("/status", response_model=Dict[str, Any], dependencies=[Depends(require_permission("events.dispatch.read"))])
async def get_bus_status(
    identity: Identity = Depends(require_permission("events.dispatch.read")),
    bus: EventBus = Depends(get_event_bus)
):
    """Returns the operational status of the event bus."""
    return {
        "enabled": bus.enabled,
        "running": bus._running,
        "queue_size": bus.queue.qsize(),
        "active_workers": len(bus.workers),
        "tenant_id": identity.tenant_id
    }

@router.get("/subscriptions", response_model=List[Subscription], dependencies=[Depends(require_permission("events.dispatch.read"))])
async def list_subscriptions(
    identity: Identity = Depends(require_permission("events.dispatch.read")),
    repo: EventDeliveryRepository = Depends(get_delivery_repo)
):
    """Lists all registered subscriptions for the tenant."""
    return repo.get_subscriptions_for_tenant(identity.tenant_id)

@router.get("/deliveries", response_model=List[EventDelivery], dependencies=[Depends(require_permission("events.dispatch.read"))])
async def list_deliveries(
    limit: int = 100,
    identity: Identity = Depends(require_permission("events.dispatch.read")),
    repo: EventDeliveryRepository = Depends(get_delivery_repo)
):
    """Lists recent delivery attempts for the tenant."""
    return repo.list_deliveries(identity.tenant_id, limit=limit)

@router.get("/dead-letters", response_model=List[DeadLetter], dependencies=[Depends(require_permission("events.dispatch.read"))])
async def list_dead_letters(
    limit: int = 100,
    identity: Identity = Depends(require_permission("events.dispatch.read")),
    repo: EventDeliveryRepository = Depends(get_delivery_repo)
):
    """Lists dead-lettered events for the tenant."""
    return repo.list_dead_letters(identity.tenant_id, limit=limit)
