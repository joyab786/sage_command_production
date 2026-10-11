# backend/api/mission_routes.py
"""
SageCommand V3 — Governed Mission Architecture Foundation API Routes (Prompt 35)

A MISSION IS A GOVERNED OPERATIONAL OBJECTIVE AND WORK PLAN ONLY — NEVER CONSTITUTES
DIRECT EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Versioned REST endpoints rooted at /api/v3/missions.
Enforces authentication, RBAC/ABAC permissions, fail-closed tenant and workspace isolation,
plant boundary restrictions, deterministic DAG validation, immutable revision history,
and safe non-disclosing error responses.

Strict Architectural Rule:
No execution endpoints (/execute, /run) exist. A mission organizes operational intent;
it never executes operational actions.
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Header

logger = logging.getLogger("mission_routes")

try:
    from core.auth import Identity, require_permission
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        MANDATORY_MISSION_NOTICE,
    )
    from services.mission_service import (
        MissionService,
        mission_service,
        MissionServiceError,
        MissionPermissionError,
        MissionValidationError,
        MissionLifecycleError,
    )
    from repositories.mission_repository import (
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionCreateRequest,
        MissionUpdateRequest,
        MissionReviewRequest,
        MissionValidationResponse,
        MissionRevisionRecord,
        MissionAuditRecord,
        MANDATORY_MISSION_NOTICE,
    )
    from backend.services.mission_service import (
        MissionService,
        mission_service,
        MissionServiceError,
        MissionPermissionError,
        MissionValidationError,
        MissionLifecycleError,
    )
    from backend.repositories.mission_repository import (
        MissionNotFoundError,
        MissionConcurrencyError,
        MissionIdempotencyConflictError,
    )

router = APIRouter(
    prefix="/api/v3/missions",
    tags=["Mission Architecture Foundation"],
)


# ---------------------------------------------------------------------------
# POST /api/v3/missions - Create Mission Draft
# ---------------------------------------------------------------------------

@router.post("", response_model=Mission, status_code=status.HTTP_201_CREATED)
async def create_mission_draft(
    request: MissionCreateRequest,
    user: Identity = Depends(require_permission("mission.create")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Creates a new draft industrial mission.
    Requires 'mission.create' permission.
    Server derives tenant and workspace scope; enforces DAG validity and safe text checks.
    """
    try:
        return mission_service.create_mission_draft(
            identity=user,
            request=request,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionPermissionError as pe:
        logger.warning(f"Mission draft permission denied: {pe}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except MissionIdempotencyConflictError as ice:
        logger.warning(f"Mission idempotency conflict: {ice}")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ice))
    except (ValueError, MissionValidationError) as ve:
        logger.warning(f"Mission validation failure: {ve}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error(f"Mission creation internal failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create industrial mission draft.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id} - Retrieve Mission
# ---------------------------------------------------------------------------

@router.get("/{mission_id}", response_model=Mission)
async def get_mission(
    mission_id: str,
    user: Identity = Depends(require_permission("mission.read")),
):
    """
    Retrieves a single industrial mission by ID.
    Requires 'mission.read' permission. Enforces tenant, workspace, and plant scope.
    """
    try:
        return mission_service.get_mission(identity=user, mission_id=mission_id)
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionPermissionError as pe:
        logger.warning(f"Mission retrieval scope denied: {pe}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission retrieval internal failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve mission.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions - List Missions
# ---------------------------------------------------------------------------

@router.get("", response_model=Dict[str, Any])
async def list_missions(
    plant_id: Optional[str] = Query(None, description="Optional plant filter"),
    status: Optional[MissionStatus] = Query(None, description="Optional status filter"),
    mission_type: Optional[MissionType] = Query(None, description="Optional mission type filter"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: Identity = Depends(require_permission("mission.read")),
):
    """
    Lists missions matching caller's authoritative tenant and workspace scope.
    Requires 'mission.read' permission.
    """
    try:
        items, total = mission_service.list_missions(
            identity=user,
            plant_id=plant_id,
            status=status,
            mission_type=mission_type,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [m.model_dump() for m in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "notice": MANDATORY_MISSION_NOTICE,
        }
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission listing failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list missions.",
        )


# ---------------------------------------------------------------------------
# PUT /api/v3/missions/{mission_id} - Update Editable Draft
# ---------------------------------------------------------------------------

@router.put("/{mission_id}", response_model=Mission)
async def update_mission_draft(
    mission_id: str,
    request: MissionUpdateRequest,
    expected_revision: Optional[int] = Query(None, description="Optimistic concurrency revision check"),
    user: Identity = Depends(require_permission("mission.update")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Updates an editable mission draft.
    Requires 'mission.update' permission. Fails if mission is in non-editable state.
    """
    try:
        return mission_service.update_mission_draft(
            identity=user,
            mission_id=mission_id,
            request=request,
            expected_revision=expected_revision,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionLifecycleError as le:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(le))
    except MissionConcurrencyError as ce:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(ce))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except (ValueError, MissionValidationError) as ve:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception as e:
        logger.error(f"Mission update failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update mission draft.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/validate - Deterministic Validation
# ---------------------------------------------------------------------------

@router.post("/{mission_id}/validate", response_model=MissionValidationResponse)
async def validate_mission(
    mission_id: str,
    user: Identity = Depends(require_permission("mission.validate")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Executes deterministic domain, bounds, and DAG acyclicity validation on a mission.
    Requires 'mission.validate' permission.
    """
    try:
        return mission_service.validate_mission(
            identity=user,
            mission_id=mission_id,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission validation failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to validate mission.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/submit - Submit For Review
# ---------------------------------------------------------------------------

@router.post("/{mission_id}/submit", response_model=Mission)
async def submit_for_review(
    mission_id: str,
    submission_notes: str = Query("Submitted for governance review.", description="Submission notes"),
    user: Identity = Depends(require_permission("mission.update")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Submits a validated mission for governance review.
    Requires 'mission.update' permission and status == 'VALIDATED'.
    """
    try:
        return mission_service.submit_for_review(
            identity=user,
            mission_id=mission_id,
            submission_notes=submission_notes,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionLifecycleError as le:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(le))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission submission failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit mission for review.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/review - Accept or Reject
# ---------------------------------------------------------------------------

@router.post("/{mission_id}/review", response_model=Mission)
async def review_mission(
    mission_id: str,
    request: MissionReviewRequest,
    user: Identity = Depends(require_permission("mission.review")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Formally accepts or rejects a mission in REVIEW_REQUIRED status.
    Requires 'mission.review' permission.
    Does NOT authorize direct execution.
    """
    try:
        return mission_service.review_mission(
            identity=user,
            mission_id=mission_id,
            request=request,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionLifecycleError as le:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(le))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission review failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to review mission.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/cancel - Cancel Mission
# ---------------------------------------------------------------------------

@router.post("/{mission_id}/cancel", response_model=Mission)
async def cancel_mission(
    mission_id: str,
    cancel_reason: str = Query("Mission cancelled by operator.", description="Operational cancellation reason"),
    user: Identity = Depends(require_permission("mission.cancel")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Cancels an active or draft mission.
    Requires 'mission.cancel' permission.
    """
    try:
        return mission_service.cancel_mission(
            identity=user,
            mission_id=mission_id,
            cancel_reason=cancel_reason,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionLifecycleError as le:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(le))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission cancellation failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel mission.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/revisions - Revision History
# ---------------------------------------------------------------------------

@router.get("/{mission_id}/revisions", response_model=List[MissionRevisionRecord])
async def get_mission_revisions(
    mission_id: str,
    user: Identity = Depends(require_permission("mission.read")),
):
    """
    Retrieves full revision history snapshots for a mission.
    Requires 'mission.read' permission.
    """
    try:
        return mission_service.get_revisions(identity=user, mission_id=mission_id)
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission revisions failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve mission revisions.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/audit - Audit Ledger
# ---------------------------------------------------------------------------

@router.get("/{mission_id}/audit", response_model=List[MissionAuditRecord])
async def get_mission_audit_ledger(
    mission_id: str,
    limit: int = Query(50, ge=1, le=200, description="Audit record limit"),
    user: Identity = Depends(require_permission("mission.read")),
):
    """
    Retrieves append-only audit trail for a mission.
    Requires 'mission.read' permission.
    """
    try:
        return mission_service.get_audit_ledger(identity=user, mission_id=mission_id, limit=limit)
    except MissionNotFoundError as nfe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(nfe))
    except MissionPermissionError as pe:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(pe))
    except Exception as e:
        logger.error(f"Mission audit ledger failure: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve mission audit ledger.",
        )
