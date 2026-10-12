# backend/api/verification_routes.py
"""
SageCommand V3 — Continuous Verification Engine API Routes (Prompt 36)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Versioned REST endpoints mounted at /api/v3/missions/{mission_id}/verifications.
Enforces authentication, RBAC/ABAC permissions (mission.verification.*),
fail-closed tenant, workspace, and plant isolation, deterministic rule evaluation,
idempotency handling, and safe non-disclosing error responses.

Strict Architectural Rule:
No execution endpoints (/execute, /run, /apply) exist. Verification assesses evidence;
it never mutates operational state or executes operational actions.
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Header

logger = logging.getLogger("verification_routes")

try:
    from core.auth import Identity, require_permission
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationRequest,
        VerificationRunSummary,
        VerificationFindingsResponse,
        VerificationCancelRequest,
        VerificationAuditRecord,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from services.verification_service import (
        VerificationService,
        verification_service,
        VerificationServiceError,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationNotFoundError,
        VerificationRevisionMismatchError,
    )
    from repositories.verification_repository import (
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationRequest,
        VerificationRunSummary,
        VerificationFindingsResponse,
        VerificationCancelRequest,
        VerificationAuditRecord,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.services.verification_service import (
        VerificationService,
        verification_service,
        VerificationServiceError,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationNotFoundError,
        VerificationRevisionMismatchError,
    )
    from backend.repositories.verification_repository import (
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )

router = APIRouter(
    prefix="/api/v3/missions/{mission_id}/verifications",
    tags=["Continuous Verification Engine"],
)


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/verifications - Request Verification
# ---------------------------------------------------------------------------

@router.post("", response_model=VerificationRun, status_code=status.HTTP_201_CREATED)
async def request_mission_verification(
    mission_id: str,
    request: VerificationRequest,
    user: Identity = Depends(require_permission("mission.verification.request")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Requests a bounded, evidence-driven continuous verification run for a mission.
    Requires 'mission.verification.request' permission.
    Server derives tenant, workspace, plant, requested_by, and initial status authoritatively.
    Client identity and outcome forging are strictly rejected.
    """
    try:
        run = verification_service.request_verification(
            identity=user,
            mission_id=mission_id,
            request=request,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
        return run
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except VerificationIdempotencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except (VerificationValidationError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except (VerificationConcurrencyError, VerificationRevisionMismatchError) as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error requesting verification for mission %s: %s", mission_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while processing the verification request.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/verifications - List Verification Runs
# ---------------------------------------------------------------------------

@router.get("", response_model=List[VerificationRunSummary], status_code=status.HTTP_200_OK)
async def list_mission_verifications(
    mission_id: str,
    limit: int = Query(20, ge=1, le=100, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Offset index"),
    plant_id: Optional[str] = Query(None, description="Optional plant scope filter"),
    user: Identity = Depends(require_permission("mission.verification.read")),
):
    """
    Lists historical verification runs for a mission.
    Requires 'mission.verification.read' permission.
    Enforces strict tenant, workspace, and plant boundary isolation.
    """
    try:
        summaries, _ = verification_service.list_verification_runs(
            identity=user,
            mission_id=mission_id,
            limit=limit,
            offset=offset,
            plant_id=plant_id,
        )
        return summaries
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error listing verification runs for mission %s: %s", mission_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while listing verification runs.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/verifications/{verification_id} - Get Verification Run
# ---------------------------------------------------------------------------

@router.get("/{verification_id}", response_model=VerificationRun, status_code=status.HTTP_200_OK)
async def get_mission_verification(
    mission_id: str,
    verification_id: str,
    user: Identity = Depends(require_permission("mission.verification.read")),
):
    """
    Retrieves complete details and findings of a specific verification run.
    Requires 'mission.verification.read' permission.
    """
    try:
        run = verification_service.get_verification_run(
            identity=user,
            mission_id=mission_id,
            verification_id=verification_id,
        )
        return run
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error retrieving verification run %s: %s", verification_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving verification run.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/verifications/{verification_id}/findings - Get Findings
# ---------------------------------------------------------------------------

@router.get("/{verification_id}/findings", response_model=VerificationFindingsResponse, status_code=status.HTTP_200_OK)
async def get_mission_verification_findings(
    mission_id: str,
    verification_id: str,
    user: Identity = Depends(require_permission("mission.verification.read")),
):
    """
    Retrieves detailed findings for a specific verification run.
    Requires 'mission.verification.read' permission.
    """
    try:
        run = verification_service.get_verification_run(
            identity=user,
            mission_id=mission_id,
            verification_id=verification_id,
        )
        return VerificationFindingsResponse(
            verification_id=run.verification_id,
            mission_id=run.mission_id,
            mission_revision=run.mission_revision,
            overall_status=run.status,
            total_findings=len(run.findings),
            findings=run.findings,
        )
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error retrieving findings for verification %s: %s", verification_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving verification findings.",
        )


# ---------------------------------------------------------------------------
# POST /api/v3/missions/{mission_id}/verifications/{verification_id}/cancel - Cancel Run
# ---------------------------------------------------------------------------

@router.post("/{verification_id}/cancel", response_model=VerificationRun, status_code=status.HTTP_200_OK)
async def cancel_mission_verification(
    mission_id: str,
    verification_id: str,
    request: VerificationCancelRequest,
    user: Identity = Depends(require_permission("mission.verification.cancel")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Cancels an in-progress or pending verification run.
    Requires 'mission.verification.cancel' permission.
    """
    try:
        cancelled = verification_service.cancel_verification(
            identity=user,
            mission_id=mission_id,
            verification_id=verification_id,
            reason=request.cancel_reason,
            request_id=x_request_id,
            trace_id=x_trace_id,
        )
        return cancelled
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except (VerificationValidationError, VerificationRepositoryError) as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error cancelling verification %s: %s", verification_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while cancelling verification run.",
        )


# ---------------------------------------------------------------------------
# GET /api/v3/missions/{mission_id}/verifications/{verification_id}/audit - Get Audit Records
# ---------------------------------------------------------------------------

@router.get("/{verification_id}/audit", response_model=List[VerificationAuditRecord], status_code=status.HTTP_200_OK)
async def get_mission_verification_audit(
    mission_id: str,
    verification_id: str,
    user: Identity = Depends(require_permission("mission.verification.read")),
):
    """
    Retrieves append-only audit trail records for a specific verification run.
    Requires 'mission.verification.read' permission.
    """
    try:
        run = verification_service.get_verification_run(
            identity=user,
            mission_id=mission_id,
            verification_id=verification_id,
        )
        records = verification_service.repository.get_audit_records(
            tenant_id=user.tenant_id,
            workspace_id=user.workspace_id,
            mission_id=mission_id,
            verification_id=verification_id,
        )
        return records
    except VerificationNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except VerificationPermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except Exception as e:
        logger.error("Unexpected error retrieving audit records for verification %s: %s", verification_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving verification audit trail.",
        )
