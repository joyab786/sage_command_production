# backend/api/event_routes.py
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request
import sqlite3
import logging

logger = logging.getLogger(__name__)

try:
    from data.schemas.event_contract import CanonicalEvent
    from services.event_repository import (
        EventRepository,
        EventIdempotencyConflictError,
        LegacyEventFingerprintError,
        EventScopeMismatchError,
    )
    from services.event_bus import get_event_bus, EventBus
    from core.auth import Identity, require_permission
    from governance.redaction import sanitize_log_message
except (ImportError, ModuleNotFoundError):
    from backend.data.schemas.event_contract import CanonicalEvent
    from backend.services.event_repository import (
        EventRepository,
        EventIdempotencyConflictError,
        LegacyEventFingerprintError,
        EventScopeMismatchError,
    )
    from backend.services.event_bus import get_event_bus, EventBus
    from backend.core.auth import Identity, require_permission
    from backend.governance.redaction import sanitize_log_message

router = APIRouter(prefix="/api/v3/events", tags=["events"])

# Dependency
def get_event_repo() -> EventRepository:
    return EventRepository()

def _get_authorized_plants(identity: Identity) -> set:
    assigned = getattr(identity, "assigned_plants", None)
    if assigned is None:
        return set()
    if isinstance(assigned, (list, set, tuple)):
        return set(str(p).strip() for p in assigned if str(p).strip())
    if isinstance(assigned, str) and assigned.strip():
        return {assigned.strip()}
    return set()

@router.post("", response_model=CanonicalEvent, status_code=status.HTTP_201_CREATED)
async def record_event(
    event: CanonicalEvent,
    request: Request = None,
    identity: Identity = Depends(require_permission("events.record")),
    repo: EventRepository = Depends(get_event_repo),
    bus: EventBus = Depends(get_event_bus)
):
    """
    Records an immutable canonical event.
    The authenticated producer's identity is authoritative. The event body is untrusted input.
    Validates tenant, workspace, and physical plant scope against authenticated identity.
    Enforces deterministic fingerprint integrity before persistence and EventBus publication.
    Enforces strict exact-replay deduplication and rejects conflicting duplicates (HTTP 409).
    Never returns or publishes an event belonging to another workspace or plant.
    """
    # 1. Authoritative Identity Scope Validation
    if not identity.tenant_id or not identity.tenant_id.strip() or identity.tenant_id.lower() in ("global", "unknown", "default"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authoritative tenant identity is required."
        )
    if not identity.workspace_id or not identity.workspace_id.strip() or identity.workspace_id.lower() in ("global", "unknown", "default"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authoritative workspace identity is required."
        )

    auth_plants = _get_authorized_plants(identity)
    if not auth_plants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Caller has no authorized plants."
        )

    # 2. Untrusted Event Body Scope Validation (Fail-closed on missing, blank, or 'global'/'unknown'/'default')
    if not event.tenant_id or not event.tenant_id.strip() or event.tenant_id.lower() in ("global", "unknown", "default"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event tenant scope is missing or invalid."
        )
    if event.tenant_id != identity.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot record event for a different tenant."
        )

    if not event.workspace_id or not event.workspace_id.strip() or event.workspace_id.lower() in ("global", "unknown", "default"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event workspace scope is missing or invalid."
        )
    if event.workspace_id != identity.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot record event for a different workspace."
        )

    if not event.plant_id or not event.plant_id.strip() or event.plant_id.lower() in ("global", "unknown", "default"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event physical plant scope is missing or invalid."
        )
    if "*" not in auth_plants and event.plant_id not in auth_plants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Caller is not authorized for plant '{event.plant_id}'."
        )

    # 3. Deterministic Scope-Bound Fingerprint Verification
    computed_fp = event.compute_fingerprint()
    if event.event_fingerprint:
        if event.event_fingerprint != computed_fp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid event fingerprint: supplied event_fingerprint does not match deterministically computed canonical fingerprint."
            )
    else:
        event.event_fingerprint = computed_fp

    # 4. Persistence and Exact-Replay Resolution
    try:
        saved_event, is_replay = repo.record_event_ex(event)
    except EventIdempotencyConflictError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflicting duplicate event: {str(err)}"
        )
    except LegacyEventFingerprintError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ambiguous legacy event record: {str(err)}"
        )
    except EventScopeMismatchError as err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Event scope mismatch: {str(err)}"
        )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate event fingerprint collision."
        )

    # 5. Scope & Canonical Content Verification on Repository-Returned Event (Fail-closed on tampering or corruption)
    if saved_event.tenant_id != identity.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Persisted event tenant mismatch."
        )
    if saved_event.workspace_id != identity.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Persisted event workspace mismatch: cross-workspace boundary violation."
        )
    if saved_event.plant_id != event.plant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Persisted event plant '{saved_event.plant_id}' does not match requested plant '{event.plant_id}'."
        )
    if "*" not in auth_plants and saved_event.plant_id not in auth_plants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Persisted event plant '{saved_event.plant_id}' is unauthorized for caller."
        )
    if saved_event.event_fingerprint != computed_fp:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Persisted event fingerprint string mismatch."
        )
    if saved_event.compute_fingerprint() != computed_fp:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Persisted event computed fingerprint mismatch: canonical content tampering detected."
        )

    # Verify that the returned event's canonical fields match the validated request's canonical fields
    saved_cat = saved_event.category.value if hasattr(saved_event.category, "value") else str(saved_event.category)
    req_cat = event.category.value if hasattr(event.category, "value") else str(event.category)
    if (
        saved_event.schema_version != event.schema_version
        or saved_cat != req_cat
        or saved_event.event_type != event.event_type
        or saved_event.occurred_at != event.occurred_at
        or saved_event.provenance != event.provenance
        or saved_event.payload != event.payload
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Persisted event canonical fields do not match validated request."
        )

    # 6. EventBus Dispatch & Publication Failure Recovery:
    # - If newly persisted (not is_replay): publish to bus. Fail closed with HTTP 500 on transient publish failure.
    # - If exact replay (is_replay): check if unfulfilled deliveries exist (due to prior transient failure).
    #   If unfulfilled deliveries exist, retry publication idempotently (only delivering to unfulfilled subscriptions).
    #   If all deliveries previously succeeded, return saved_event immediately without republishing.
    correlation_id = (
        (request.headers.get("x-correlation-id") or request.headers.get("x-request-id"))
        if request and hasattr(request, "headers")
        else None
    ) or getattr(saved_event, "correlation_id", None) or saved_event.event_id

    error_headers = {"X-Correlation-ID": correlation_id} if correlation_id else None

    if not is_replay:
        try:
            await bus.publish(saved_event)
        except Exception as pub_err:
            sanitized_err = sanitize_log_message(str(pub_err))
            logger.error(
                f"[EventRoutes] Transient publication error for event {saved_event.event_id} "
                f"[correlation_id={correlation_id}, tenant={saved_event.tenant_id}]: {sanitized_err}",
                exc_info=False
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Event persisted but publication encountered transient error.",
                headers=error_headers
            )
    else:
        # Exact replay: check if recovery/retry is needed for unfulfilled deliveries
        if bus.has_unfulfilled_deliveries(saved_event):
            try:
                await bus.publish(saved_event)
            except Exception as pub_err:
                sanitized_err = sanitize_log_message(str(pub_err))
                logger.error(
                    f"[EventRoutes] Transient publication retry error for replayed event {saved_event.event_id} "
                    f"[correlation_id={correlation_id}, tenant={saved_event.tenant_id}]: {sanitized_err}",
                    exc_info=False
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Event persisted but publication retry encountered transient error.",
                    headers=error_headers
                )

    return saved_event

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

    # Workspace boundary enforcement
    if workspace_id:
        if workspace_id != identity.workspace_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access events from a different workspace.")
        filters["workspace_id"] = workspace_id
    elif identity.workspace_id:
        filters["workspace_id"] = identity.workspace_id

    # Plant boundary enforcement
    auth_plants = _get_authorized_plants(identity)
    if plant_id:
        if "*" not in auth_plants and plant_id not in auth_plants:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Caller is not authorized for plant '{plant_id}'.")
        filters["plant_id"] = plant_id

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
    if event.workspace_id and identity.workspace_id and event.workspace_id != identity.workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access event from a different workspace.")
    auth_plants = _get_authorized_plants(identity)
    if event.plant_id and "*" not in auth_plants and event.plant_id not in auth_plants:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Caller is not authorized for plant '{event.plant_id}'.")
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
    if event.workspace_id and identity.workspace_id and event.workspace_id != identity.workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access event from a different workspace.")
    auth_plants = _get_authorized_plants(identity)
    if event.plant_id and "*" not in auth_plants and event.plant_id not in auth_plants:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Caller is not authorized for plant '{event.plant_id}'.")
    return event
