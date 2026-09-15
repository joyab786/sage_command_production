# backend/api/audit_routes.py
"""
SageCommand V3 — Audit & Decision Ledger API Endpoints
Base Prefix: /api/v3/audit
Provides authorized multi-tenant query access to immutable audit events,
chronological timeline reconstructions, and high-level decision records.

Invariants:
- All queries enforce server-authoritative tenant isolation.
- Reading audit data requires 'audit.read' permission clearance.
- No public raw event ingestion endpoint exists (audit records are emitted exclusively by trusted internal services).
"""

import re
import uuid
from typing import Optional
from fastapi import APIRouter, Header, Depends, Query, HTTPException, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from governance.rate_limiter import rate_limiter
    from data.schemas.ledger_contract import (
        LedgerEventResponse,
        LedgerEventListResponse,
        TimelineResponse,
        DecisionRecordResponse,
    )
    from services.audit_ledger import audit_ledger
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.governance.rate_limiter import rate_limiter
    from backend.data.schemas.ledger_contract import (
        LedgerEventResponse,
        LedgerEventListResponse,
        TimelineResponse,
        DecisionRecordResponse,
    )
    from backend.services.audit_ledger import audit_ledger

router = APIRouter(prefix="/api/v3/audit", tags=["Audit & Decision Ledger"])


def extract_request_id(x_request_id: Optional[str] = None) -> str:
    if x_request_id:
        sanitized = re.sub(r"[^\w\-]", "", x_request_id)[:64]
        if sanitized:
            return sanitized
    return f"req_{uuid.uuid4().hex[:12]}"


# =====================================================================
# 1. QUERY AUDIT EVENTS (GET /api/v3/audit/events)
# =====================================================================

@router.get(
    "/events",
    response_model=LedgerEventListResponse,
    summary="Query Audit Events",
    description="Returns a paginated list of immutable audit events strictly scoped to caller's tenant."
)
async def query_events(
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    event_type: Optional[str] = Query(None, description="Filter by EventType"),
    category: Optional[str] = Query(None, description="Filter by EventCategory"),
    action_id: Optional[str] = Query(None, description="Filter by Action ID"),
    correlation_id: Optional[str] = Query(None, description="Filter by Correlation ID"),
    trace_id: Optional[str] = Query(None, description="Filter by Trace ID"),
    actor_id: Optional[str] = Query(None, description="Filter by actor ID or user ID"),
    plant_id: Optional[str] = Query(None, description="Filter by plant ID"),
    data_mode: Optional[str] = Query(None, description="Filter by data mode: REAL or SIMULATION"),
    start_time: Optional[str] = Query(None, description="Filter occurred_at >= start_time (ISO format)"),
    end_time: Optional[str] = Query(None, description="Filter occurred_at <= end_time (ISO format)"),
    limit: int = Query(20, ge=1, le=100, description="Page size (max 100)"),
    offset: int = Query(0, ge=0, description="Offset"),
    identity: Identity = Depends(require_permission("audit.read"))
):
    req_id = extract_request_id(x_request_id)

    # Rate limiting
    allowed, _ = rate_limiter.is_allowed(identity.user_id)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded.")

    filters = {
        "event_type": event_type,
        "category": category,
        "action_id": action_id,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "actor_id": actor_id,
        "plant_id": plant_id,
        "data_mode": data_mode,
        "start_time": start_time,
        "end_time": end_time,
        "workspace_id": getattr(identity, "workspace_id", None)
    }

    events, total_count = audit_ledger.repository.query(
        tenant_id=identity.tenant_id,
        filters=filters,
        limit=limit,
        offset=offset
    )

    return LedgerEventListResponse(
        success=True,
        request_id=req_id,
        total_count=total_count,
        limit=limit,
        offset=offset,
        events=events
    )


# =====================================================================
# 2. GET EVENT BY ID (GET /api/v3/audit/events/{event_id})
# =====================================================================

@router.get(
    "/events/{event_id}",
    response_model=LedgerEventResponse,
    summary="Get Audit Event",
    description="Retrieves an immutable audit event by ID within caller's tenant boundary."
)
async def get_event_by_id(
    event_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_permission("audit.read"))
):
    req_id = extract_request_id(x_request_id)

    event = audit_ledger.repository.get_by_id(event_id, identity.tenant_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audit event '{event_id}' not found in tenant partition."
        )

    return LedgerEventResponse(
        success=True,
        request_id=req_id,
        event=event
    )


# =====================================================================
# 3. RECONSTRUCT TIMELINE (GET /api/v3/audit/timeline)
# =====================================================================

@router.get(
    "/timeline",
    response_model=TimelineResponse,
    summary="Get Incident & Decision Timeline",
    description="Reconstructs an ordered sequence of events for a correlation, action, or incident ID."
)
async def get_timeline_endpoint(
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    correlation_id: Optional[str] = Query(None, description="Correlation ID connecting related workflow events"),
    action_id: Optional[str] = Query(None, description="Action ID for lifecycle timeline"),
    incident_id: Optional[str] = Query(None, description="Incident ID for incident replay"),
    limit: int = Query(50, ge=1, le=100, description="Max timeline events (max 100)"),
    identity: Identity = Depends(require_permission("audit.read"))
):
    req_id = extract_request_id(x_request_id)

    if not correlation_id and not action_id and not incident_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must provide at least one of: correlation_id, action_id, or incident_id."
        )

    timeline_events = audit_ledger.get_timeline(
        tenant_id=identity.tenant_id,
        correlation_id=correlation_id,
        action_id=action_id,
        incident_id=incident_id,
        workspace_id=getattr(identity, "workspace_id", None),
        limit=limit
    )

    return TimelineResponse(
        success=True,
        request_id=req_id,
        correlation_id=correlation_id,
        action_id=action_id,
        total_events=len(timeline_events),
        timeline=timeline_events
    )


# =====================================================================
# 4. GET DECISION RECORD (GET /api/v3/audit/decisions/{action_id})
# =====================================================================

@router.get(
    "/decisions/{action_id}",
    response_model=DecisionRecordResponse,
    summary="Get Decision Record Graph",
    description="Assembles the complete decision lineage: Evidence -> Action Proposal -> Authorization -> Policy."
)
async def get_decision_record_endpoint(
    action_id: str,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    identity: Identity = Depends(require_permission("audit.read"))
):
    req_id = extract_request_id(x_request_id)

    record = audit_ledger.get_decision_record(action_id, identity.tenant_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Decision record for action '{action_id}' not found."
        )

    return DecisionRecordResponse(
        success=True,
        request_id=req_id,
        decision_record=record
    )
