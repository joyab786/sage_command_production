# backend/api/digital_twin_routes.py
"""
SageCommand V3 — Digital Twin REST API Routes (Prompt 13)
Exposes read/write endpoints for Digital Twin state, snapshots, scenarios,
state comparison, and consistency validation.

Cardinal Invariant:
These endpoints are a state representation and simulation-context API.
They NEVER execute physical actions, write to PLCs, or bypass the Execution Gateway.
"""

import logging
from fastapi import APIRouter, HTTPException, Request

try:
    from core.auth import Identity
    from services.digital_twin_service import DigitalTwinService, digital_twin_service
    from data.schemas.digital_twin_contract import (
        StateIngestRequest,
        SnapshotCreateRequest,
        ScenarioCreateRequest,
        StateCompareRequest,
        TwinEntityResponse,
        TwinHistoryResponse,
        SnapshotResponse,
        ScenarioResponse,
        CompareResponse,
        ValidationResponse,
    )
except ModuleNotFoundError:
    from backend.core.auth import Identity
    from backend.services.digital_twin_service import DigitalTwinService, digital_twin_service
    from backend.data.schemas.digital_twin_contract import (
        StateIngestRequest,
        SnapshotCreateRequest,
        ScenarioCreateRequest,
        StateCompareRequest,
        TwinEntityResponse,
        TwinHistoryResponse,
        SnapshotResponse,
        ScenarioResponse,
        CompareResponse,
        ValidationResponse,
    )

logger = logging.getLogger("sagecommand.digital_twin.api")

router = APIRouter(prefix="/api/v3/digital-twin", tags=["Digital Twin"])


def _get_identity(request: Request) -> Identity:
    """Extract server-authoritative identity. Never trust client-supplied tenant."""
    identity = getattr(request.state, "identity", None)
    if identity:
        return identity
    # Fallback for development
    return Identity(
        user_id="dev_user",
        tenant_id="default_tenant",
        roles=["ADMINISTRATOR"],
    )


# =========================================================================
# TWIN ENTITY ENDPOINTS
# =========================================================================

@router.get("/entities/{entity_id}")
async def get_twin_entity(entity_id: str, request: Request):
    """Get current Digital Twin state for an entity."""
    identity = _get_identity(request)
    twin = digital_twin_service.get_twin_entity(
        tenant_id=identity.tenant_id,
        entity_id=entity_id,
    )
    if not twin:
        raise HTTPException(status_code=404, detail=f"No twin state found for entity '{entity_id}'.")
    return TwinEntityResponse(data=twin)


@router.get("/entities/{entity_id}/history")
async def get_twin_history(entity_id: str, request: Request, limit: int = 50):
    """Get historical state versions for an entity."""
    identity = _get_identity(request)
    history = digital_twin_service.get_state_history(
        tenant_id=identity.tenant_id,
        entity_id=entity_id,
        limit=min(limit, 200),
    )
    return TwinHistoryResponse(data=history, total_count=len(history))


@router.get("/entities/{entity_id}/context")
async def get_twin_context(entity_id: str, request: Request):
    """Get Knowledge Graph relationship context for a twin entity."""
    identity = _get_identity(request)
    context = digital_twin_service.get_entity_context(
        tenant_id=identity.tenant_id,
        entity_id=entity_id,
    )
    return {"success": True, "data": context}


# =========================================================================
# STATE INGESTION
# =========================================================================

@router.post("/state/ingest")
async def ingest_state(body: StateIngestRequest, request: Request):
    """Ingest observed/derived/simulated state into the Digital Twin."""
    identity = _get_identity(request)
    success, message, twin = digital_twin_service.ingest_state(
        tenant_id=identity.tenant_id,
        entity_id=body.entity_id,
        properties=body.properties,
        classification=body.classification.value,
        source_type=body.source_type.value,
        source_id=body.source_id,
        observed_at=body.observed_at,
        effective_at=body.effective_at,
        confidence=body.confidence.value,
        metadata=body.metadata,
        actor_id=identity.user_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return TwinEntityResponse(data=twin, message=message)


# =========================================================================
# SNAPSHOTS
# =========================================================================

@router.post("/snapshot")
async def create_snapshot(body: SnapshotCreateRequest, request: Request):
    """Create an immutable point-in-time snapshot."""
    identity = _get_identity(request)
    snapshot = digital_twin_service.create_snapshot(
        tenant_id=identity.tenant_id,
        snapshot_timestamp=body.snapshot_timestamp,
        entity_ids=body.entity_ids,
        description=body.description,
        metadata=body.metadata,
        created_by=identity.user_id,
    )
    return SnapshotResponse(data=snapshot, message="Snapshot created.")


@router.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: str, request: Request):
    """Retrieve an existing snapshot."""
    identity = _get_identity(request)
    snapshot = digital_twin_service.get_snapshot(
        tenant_id=identity.tenant_id,
        snapshot_id=snapshot_id,
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_id}' not found.")
    return SnapshotResponse(data=snapshot)


# =========================================================================
# SCENARIOS
# =========================================================================

@router.post("/scenarios")
async def create_scenario(body: ScenarioCreateRequest, request: Request):
    """Create a simulation scenario isolated from observed state."""
    identity = _get_identity(request)
    success, message, scenario = digital_twin_service.create_scenario(
        tenant_id=identity.tenant_id,
        base_snapshot_id=body.base_snapshot_id,
        name=body.name,
        description=body.description,
        overrides=body.overrides,
        metadata=body.metadata,
        created_by=identity.user_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return ScenarioResponse(data=scenario, message=message)


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: str, request: Request):
    """Retrieve a scenario with its overrides."""
    identity = _get_identity(request)
    scenario = digital_twin_service.get_scenario(
        tenant_id=identity.tenant_id,
        scenario_id=scenario_id,
    )
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found.")
    return ScenarioResponse(data=scenario)


# =========================================================================
# STATE COMPARISON
# =========================================================================

@router.post("/state/compare")
async def compare_states(body: StateCompareRequest, request: Request):
    """Compare two twin states deterministically."""
    identity = _get_identity(request)
    success, message, diffs = digital_twin_service.compare_states(
        tenant_id=identity.tenant_id,
        source_type=body.source_type,
        source_id=body.source_id,
        target_type=body.target_type,
        target_id=body.target_id,
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return CompareResponse(diffs=diffs, total_changes=len(diffs))


# =========================================================================
# VALIDATION
# =========================================================================

@router.post("/validate")
async def validate_consistency(request: Request):
    """Run consistency validation on all twin entities."""
    identity = _get_identity(request)
    report = digital_twin_service.validate_consistency(
        tenant_id=identity.tenant_id,
    )
    return ValidationResponse(report=report)
