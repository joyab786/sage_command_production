# backend/api/transaction_routes.py
"""
SageCommand V3 — Transaction & Rollback Architecture REST API
Exposes deterministic transaction planning, validation, revalidation, and cancellation endpoints.
Strictly guards the execution boundary: POST /execute and POST /rollback return 405 Method Not Allowed.
"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query

try:
    from core.auth import Identity, get_current_identity, require_permission
    from data.schemas.transaction_contract import (
        TransactionPlanRequest,
        TransactionPlanResponse,
        TransactionDetailResponse,
        TransactionListResponse,
        TransactionValidateResponse,
        TransactionRevalidateResponse,
        TransactionCancelResponse
    )
    from services.transaction_service import transaction_service, TransactionService
except ModuleNotFoundError:
    from backend.core.auth import Identity, get_current_identity, require_permission
    from backend.data.schemas.transaction_contract import (
        TransactionPlanRequest,
        TransactionPlanResponse,
        TransactionDetailResponse,
        TransactionListResponse,
        TransactionValidateResponse,
        TransactionRevalidateResponse,
        TransactionCancelResponse
    )
    from backend.services.transaction_service import transaction_service, TransactionService

router = APIRouter(prefix="/api/v3/transactions", tags=["V3 Transactions"])


@router.post(
    "/plan",
    response_model=TransactionPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a deterministic Transaction Plan from a structured Action",
    dependencies=[Depends(require_permission("transaction.plan"))]
)
def create_transaction_plan(
    payload: TransactionPlanRequest,
    identity: Identity = Depends(get_current_identity)
):
    """
    Synthesizes a deterministic Transaction Plan for an approved or proposed Action.
    Enforces idempotency, tenant isolation, and strict passive boundaries:
    side_effects = False, execution_permitted = False.
    """
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    try:
        tx, val_res = transaction_service.plan_transaction(
            action_id=payload.action_id,
            identity=identity,
            idempotency_key=payload.idempotency_key,
            ttl_seconds=payload.ttl_seconds,
            data_mode_override=payload.data_mode
        )
        return TransactionPlanResponse(
            success=True,
            request_id=req_id,
            transaction=tx,
            validation=val_res
        )
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        if "IDEMPOTENCY_CONFLICT" in str(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Transaction planning failed: {e}")


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetailResponse,
    summary="Retrieve a Transaction by ID",
    dependencies=[Depends(require_permission("transaction.read"))]
)
def get_transaction(
    transaction_id: str,
    identity: Identity = Depends(get_current_identity)
):
    """Retrieves a single transaction record strictly scoped to caller's tenant."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    tx = transaction_service.get_transaction(transaction_id, identity)
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transaction '{transaction_id}' not found.")
    return TransactionDetailResponse(
        success=True,
        request_id=req_id,
        transaction=tx
    )


@router.get(
    "",
    response_model=TransactionListResponse,
    summary="List Transactions with tenant and workspace scoping",
    dependencies=[Depends(require_permission("transaction.read"))]
)
def list_transactions(
    workspace_id: Optional[str] = Query(None, description="Optional workspace filter"),
    status_filter: Optional[str] = Query(None, alias="status", description="Optional status filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    identity: Identity = Depends(get_current_identity)
):
    """Queries transactions belonging to caller's tenant."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    txs = transaction_service.list_transactions(
        identity=identity,
        workspace_id=workspace_id,
        status=status_filter,
        limit=limit,
        offset=offset
    )
    return TransactionListResponse(
        success=True,
        request_id=req_id,
        transactions=txs,
        total_count=len(txs)
    )


@router.post(
    "/{transaction_id}/validate",
    response_model=TransactionValidateResponse,
    summary="Validate an existing Transaction Plan",
    dependencies=[Depends(require_permission("transaction.validate"))]
)
def validate_transaction(
    transaction_id: str,
    identity: Identity = Depends(get_current_identity)
):
    """Executes deterministic validation gates on a planned transaction."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    try:
        tx, val_res = transaction_service.validate_transaction(transaction_id, identity)
        return TransactionValidateResponse(
            success=True,
            request_id=req_id,
            validation=val_res,
            transaction=tx
        )
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{transaction_id}/revalidate",
    response_model=TransactionRevalidateResponse,
    summary="Revalidate a Transaction Plan against current system state",
    dependencies=[Depends(require_permission("transaction.validate"))]
)
def revalidate_transaction(
    transaction_id: str,
    identity: Identity = Depends(get_current_identity)
):
    """Detects policy, authorization, or resource drift prior to future execution."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    try:
        tx, val_res = transaction_service.revalidate_transaction(transaction_id, identity)
        return TransactionRevalidateResponse(
            success=True,
            request_id=req_id,
            revalidation_status="VALID" if val_res.valid else "CONFLICT_DETECTED",
            validation=val_res,
            transaction=tx
        )
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/{transaction_id}/cancel",
    response_model=TransactionCancelResponse,
    summary="Cancel a planned transaction prior to execution",
    dependencies=[Depends(require_permission("transaction.cancel"))]
)
def cancel_transaction(
    transaction_id: str,
    reason: str = Query("Cancelled by operator", description="Reason for cancellation"),
    identity: Identity = Depends(get_current_identity)
):
    """Cancels a pending transaction plan."""
    req_id = f"req_{uuid.uuid4().hex[:8]}"
    try:
        tx = transaction_service.cancel_transaction(transaction_id, identity, reason=reason)
        return TransactionCancelResponse(
            success=True,
            request_id=req_id,
            message=f"Transaction '{transaction_id}' cancelled successfully.",
            transaction=tx
        )
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# =====================================================================
# MANDATORY SAFETY EXECUTION & ROLLBACK BOUNDARY (STRICTLY 405)
# =====================================================================

@router.post("/{transaction_id}/execute", include_in_schema=True)
def execute_transaction_boundary(transaction_id: str):
    """
    CRITICAL ARCHITECTURAL SAFETY BOUNDARY:
    Operational transaction execution is strictly prohibited under Prompt 09.
    Real-world side effects are deferred to the future Execution Gateway.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="EXECUTION_GATEWAY_NOT_IMPLEMENTED: Transaction execution is disabled in Prompt 09. Operational execution is deferred to the Execution Gateway."
    )


@router.post("/{transaction_id}/rollback", include_in_schema=True)
def rollback_transaction_boundary(transaction_id: str):
    """
    CRITICAL ARCHITECTURAL SAFETY BOUNDARY:
    Autonomous rollback execution is strictly prohibited under Prompt 09.
    Rollback capability analysis is supported; autonomous rollback execution is deferred.
    """
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail="ROLLBACK_GATEWAY_NOT_IMPLEMENTED: Autonomous rollback execution is disabled in Prompt 09. Direct execution of rollback is deferred to the Execution Gateway."
    )
