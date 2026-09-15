# backend/api/knowledge_graph_routes.py
"""
SageCommand V3 — Operational Knowledge Graph REST API
Exposes endpoints for querying contextual nodes, bounded neighbor and path traversals,
bitemporal histories, operational fact ingestion, graph consistency audits,
and read-only datacore projections.

Cardinal Invariant:
The Operational Knowledge Graph is purely an informational context and query layer.
It never performs operational mutations or bypasses the Execution Gateway.
"""

from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

try:
    from core.auth import Identity, get_current_identity, require_permission
    from governance.rate_limiter import rate_limiter
    from data.schemas.knowledge_graph_contract import (
        OperationalFact,
        KnowledgeGraphNode,
        GraphNeighbor,
        GraphPath,
        FactCreateRequest,
        FactRevokeRequest,
        FactResponse,
        EntityNodeResponse,
        NeighborsResponse,
        ContextResponse,
        PathResponse,
        ValidationResponse,
        ProjectionSyncResponse,
    )
    from services.knowledge_graph_service import knowledge_graph_service
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.governance.rate_limiter import rate_limiter
    from backend.data.schemas.knowledge_graph_contract import (
        OperationalFact,
        KnowledgeGraphNode,
        GraphNeighbor,
        GraphPath,
        FactCreateRequest,
        FactRevokeRequest,
        FactResponse,
        EntityNodeResponse,
        NeighborsResponse,
        ContextResponse,
        PathResponse,
        ValidationResponse,
        ProjectionSyncResponse,
    )
    from backend.services.knowledge_graph_service import knowledge_graph_service

router = APIRouter(prefix="/api/v3/knowledge-graph", tags=["Operational Knowledge Graph"])


def enforce_rate_limit(user_id: str):
    """Enforces sliding-window rate limiting for protected graph queries."""
    allowed, _ = rate_limiter.is_allowed(user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down graph queries."
        )


# =============================================================================
# 1. NODE CONTEXT & TRAVERSAL ENDPOINTS
# =============================================================================

@router.get(
    "/entities/{entity_id}",
    response_model=EntityNodeResponse,
    summary="Get Operational Knowledge Node",
    description="Retrieves an entity with its active or historical operational facts, status, and freshness."
)
async def get_entity_node(
    entity_id: str,
    at_time: Optional[str] = Query(None, description="Point-in-time ISO 8601 timestamp"),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    node = knowledge_graph_service.get_entity_node(entity_id=entity_id, identity=identity, at_time=at_time)
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found in tenant '{identity.tenant_id}'."
        )
    return EntityNodeResponse(success=True, data=node)


@router.get(
    "/entities/{entity_id}/neighbors",
    response_model=NeighborsResponse,
    summary="Get 1-Hop Graph Neighbors",
    description="Retrieves direct neighbors across structural ontology relations and dynamic operational edges."
)
async def get_neighbors(
    entity_id: str,
    direction: str = Query("BOTH", description="UPSTREAM, DOWNSTREAM, or BOTH"),
    predicate: Optional[str] = Query(None, description="Filter by relationship/predicate"),
    at_time: Optional[str] = Query(None, description="Point-in-time timestamp"),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    neighbors = knowledge_graph_service.get_neighbors(
        entity_id=entity_id,
        identity=identity,
        direction=direction,
        predicate=predicate,
        at_time=at_time
    )
    return NeighborsResponse(
        success=True,
        entity_id=entity_id,
        neighbors=neighbors,
        total_count=len(neighbors)
    )


@router.get(
    "/entities/{entity_id}/context",
    response_model=ContextResponse,
    summary="Get Subgraph Neighborhood Context",
    description="Performs bounded BFS expansion around entity enforcing maximum depth and node limits."
)
async def get_context(
    entity_id: str,
    depth: int = Query(2, ge=1, le=10),
    max_nodes: int = Query(50, ge=1, le=200),
    at_time: Optional[str] = Query(None),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    try:
        return knowledge_graph_service.get_context(
            entity_id=entity_id,
            identity=identity,
            depth=depth,
            max_nodes=max_nodes,
            at_time=at_time
        )
    except KeyError as key_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(key_err))


@router.get(
    "/entities/{entity_id}/upstream",
    response_model=ContextResponse,
    summary="Get Upstream Dependencies",
    description="Traverses incoming dependency and container edges with bounded depth."
)
async def get_upstream(
    entity_id: str,
    max_depth: int = Query(3, ge=1, le=10),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    try:
        return knowledge_graph_service.get_upstream(entity_id=entity_id, identity=identity, max_depth=max_depth)
    except KeyError as key_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(key_err))


@router.get(
    "/entities/{entity_id}/downstream",
    response_model=ContextResponse,
    summary="Get Downstream Dependencies",
    description="Traverses outgoing dependency and containee edges with bounded depth."
)
async def get_downstream(
    entity_id: str,
    max_depth: int = Query(3, ge=1, le=10),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    try:
        return knowledge_graph_service.get_downstream(entity_id=entity_id, identity=identity, max_depth=max_depth)
    except KeyError as key_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(key_err))


@router.get(
    "/path",
    response_model=PathResponse,
    summary="Find Shortest Deterministic Path",
    description="Computes shortest path between two entities using BFS with cycle termination."
)
async def find_path(
    source: str = Query(..., description="Source entity URN"),
    target: str = Query(..., description="Target entity URN"),
    max_depth: int = Query(5, ge=1, le=10),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    try:
        graph_path = knowledge_graph_service.find_path(
            source_entity_id=source,
            target_entity_id=target,
            identity=identity,
            max_depth=max_depth
        )
        if not graph_path:
            return PathResponse(success=True, found=False, data=None, message="No path found within depth limit.")
        return PathResponse(success=True, found=True, data=graph_path)
    except KeyError as key_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(key_err))


@router.get(
    "/history/{entity_id}",
    response_model=List[OperationalFact],
    summary="Get Entity Fact Timeline",
    description="Returns chronological operational facts for an entity within tenant boundary."
)
async def get_history(
    entity_id: str,
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    predicate: Optional[str] = Query(None),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    return knowledge_graph_service.get_history(
        entity_id=entity_id,
        identity=identity,
        start_time=start_time,
        end_time=end_time,
        predicate=predicate
    )


# =============================================================================
# 2. FACT INGESTION & MANAGEMENT ENDPOINTS
# =============================================================================

@router.post(
    "/facts",
    response_model=FactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Operational Fact",
    description="Validates and persists an operational fact, superseding prior active observations."
)
async def ingest_fact(
    req: FactCreateRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.manage"))
):
    enforce_rate_limit(identity.user_id)
    try:
        fact = knowledge_graph_service.ingest_fact(
            identity=identity,
            subject_entity_id=req.subject_entity_id,
            predicate=req.predicate,
            value=req.value,
            value_type=req.value_type,
            object_entity_id=req.object_entity_id,
            unit=req.unit,
            source_type=req.source_type,
            source_id=req.source_id,
            observed_at=req.observed_at,
            valid_from=req.valid_from,
            valid_to=req.valid_to,
            confidence=req.confidence,
            metadata=req.metadata
        )
        return FactResponse(success=True, data=fact, message="Operational fact successfully ingested.")
    except KeyError as key_err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(key_err))
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))


@router.get(
    "/facts/{fact_id}",
    response_model=FactResponse,
    summary="Get Fact by ID",
    description="Retrieves a specific operational fact within caller's tenant boundary."
)
async def get_fact(
    fact_id: str,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    fact = knowledge_graph_service.get_fact(fact_id=fact_id, identity=identity)
    if not fact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact '{fact_id}' not found in tenant '{identity.tenant_id}'."
        )
    return FactResponse(success=True, data=fact)


@router.post(
    "/facts/{fact_id}/revoke",
    summary="Revoke Operational Fact",
    description="Transitions an active operational fact to REVOKED status with reason and audit metadata."
)
async def revoke_fact(
    fact_id: str,
    req: FactRevokeRequest,
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.manage"))
):
    enforce_rate_limit(identity.user_id)
    revoked = knowledge_graph_service.revoke_fact(fact_id=fact_id, identity=identity, reason=req.reason)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fact '{fact_id}' not found in tenant '{identity.tenant_id}'."
        )
    return {"success": True, "fact_id": fact_id, "revoked": True, "reason": req.reason}


# =============================================================================
# 3. CONSISTENCY, SNAPSHOT & PROJECTION ENDPOINTS
# =============================================================================

@router.post(
    "/validate",
    response_model=ValidationResponse,
    summary="Validate Knowledge Graph Consistency",
    description="Runs consistency audits across dangling entities, incompatible edges, and timestamp sanity."
)
async def validate_graph(
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.manage"))
):
    enforce_rate_limit(identity.user_id)
    report = knowledge_graph_service.validate_graph(identity=identity)
    return ValidationResponse(success=True, report=report)


@router.get(
    "/snapshot",
    summary="Get Point-in-Time Graph Snapshot",
    description="Reconstructs tenant graph state at specified timestamp without mutating underlying history."
)
async def get_snapshot(
    at_time: Optional[str] = Query(None, description="Target point-in-time timestamp"),
    plant_id: Optional[str] = Query(None, description="Optional plant filter"),
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.read"))
):
    enforce_rate_limit(identity.user_id)
    return knowledge_graph_service.get_snapshot(identity=identity, at_time=at_time, plant_id=plant_id)


@router.post(
    "/projection/sync-inventory",
    response_model=ProjectionSyncResponse,
    summary="Sync Operational Inventory Projection",
    description="Reads datacore inventory strictly in read-only mode and projects INVENTORY_LEVEL operational facts."
)
async def sync_inventory_projection(
    identity: Identity = Depends(get_current_identity),
    _perm = Depends(require_permission("knowledge_graph.manage"))
):
    enforce_rate_limit(identity.user_id)
    res = knowledge_graph_service.sync_inventory_projection(identity=identity)
    return res
