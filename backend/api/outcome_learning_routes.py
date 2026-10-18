# backend/api/outcome_learning_routes.py
"""
SageCommand V3 — Closed-Loop Outcome Learning API Routes (Prompt 39)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Versioned REST endpoints mounted at /api/v3/learning.
Enforces authentication, RBAC permissions (learning.*), fail-closed tenant,
workspace, and plant isolation, deterministic evaluation, and non-disclosing safe error responses.

Strict Architectural Rule:
No execution endpoints (/execute, /run, /apply) exist. Outcome learning evaluates
evidence and provides read-only historical learning context; it never mutates operational state.
"""

import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Header
from pydantic import BaseModel, Field

try:
    from core.auth import Identity, require_permission
    from data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        EvaluationStatus,
        DataMode,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
    )
    from repositories.outcome_learning_repository import (
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.auth import Identity, require_permission
    from backend.data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        EvaluationStatus,
        DataMode,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
    )
    from backend.repositories.outcome_learning_repository import (
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )

logger = logging.getLogger("outcome_learning_routes")

router = APIRouter(
    prefix="/api/v3/learning",
    tags=["Closed-Loop Outcome Learning"],
)


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class EvaluationRequest(BaseModel):
    """Request payload to evaluate a prediction against an observed outcome."""
    prediction_id: str = Field(..., max_length=128)
    outcome_id: str = Field(..., max_length=128)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)
    reevaluation_reason: Optional[str] = Field(default=None, max_length=256)


# =============================================================================
# 1. PREDICTION SNAPSHOT ENDPOINTS
# =============================================================================

@router.post(
    "/predictions",
    response_model=PredictionSnapshot,
    status_code=status.HTTP_201_CREATED,
)
async def record_prediction_snapshot(
    snapshot: PredictionSnapshot,
    user: Identity = Depends(require_permission("learning.prediction.record")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Records an immutable prediction snapshot preserving expectation before outcome is observed.
    Enforces authoritative tenant and workspace boundaries from caller identity.
    """
    # Enforce authoritative tenant and workspace from token
    if snapshot.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot record prediction for tenant '{snapshot.tenant_id}'; caller belongs to '{user.tenant_id}'.",
        )
    if snapshot.workspace_id != user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot record prediction for workspace '{snapshot.workspace_id}'; caller belongs to '{user.workspace_id}'.",
        )

    try:
        persisted = outcome_evaluation_service.record_prediction_snapshot(user, snapshot)
        return persisted
    except PredictionImmutabilityViolationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error recording prediction snapshot: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while recording the prediction snapshot.",
        )


@router.get(
    "/predictions/{prediction_id}",
    response_model=PredictionSnapshot,
    status_code=status.HTTP_200_OK,
)
async def get_prediction_snapshot(
    prediction_id: str,
    user: Identity = Depends(require_permission("learning.prediction.read")),
):
    """Retrieves a single prediction snapshot scoped to caller's tenant and workspace."""
    try:
        return outcome_evaluation_service.get_prediction_snapshot(user, prediction_id)
    except PredictionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error retrieving prediction snapshot '%s': %s", prediction_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving the prediction snapshot.",
        )


@router.get(
    "/predictions",
    response_model=List[PredictionSnapshot],
    status_code=status.HTTP_200_OK,
)
async def list_prediction_snapshots(
    plant_id: Optional[str] = Query(None),
    prediction_type: Optional[PredictionType] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(require_permission("learning.prediction.read")),
):
    """Lists prediction snapshots within caller's authorized scope."""
    try:
        return outcome_evaluation_service.list_prediction_snapshots(
            identity=user,
            plant_id=plant_id,
            prediction_type=prediction_type,
            limit=limit,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error listing prediction snapshots: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while listing prediction snapshots.",
        )


# =============================================================================
# 2. OBSERVED OUTCOME ENDPOINTS
# =============================================================================

@router.post(
    "/outcomes",
    response_model=ObservedOutcome,
    status_code=status.HTTP_201_CREATED,
)
async def record_observed_outcome(
    outcome: ObservedOutcome,
    user: Identity = Depends(require_permission("learning.outcome.record")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Records an observed physical or operational outcome.
    Prevents client-side forgery of verification status.
    """
    if outcome.tenant_id != user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot record outcome for tenant '{outcome.tenant_id}'; caller belongs to '{user.tenant_id}'.",
        )
    if outcome.workspace_id != user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot record outcome for workspace '{outcome.workspace_id}'; caller belongs to '{user.workspace_id}'.",
        )

    try:
        persisted = outcome_evaluation_service.record_observed_outcome(user, outcome)
        return persisted
    except OutcomeImmutabilityViolationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error recording observed outcome: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while recording the observed outcome.",
        )


@router.get(
    "/outcomes/{outcome_id}",
    response_model=ObservedOutcome,
    status_code=status.HTTP_200_OK,
)
async def get_observed_outcome(
    outcome_id: str,
    user: Identity = Depends(require_permission("learning.outcome.read")),
):
    """Retrieves an observed outcome within caller's scope."""
    try:
        return outcome_evaluation_service.get_observed_outcome(user, outcome_id)
    except OutcomeNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error retrieving outcome '%s': %s", outcome_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving the observed outcome.",
        )


@router.get(
    "/outcomes",
    response_model=List[ObservedOutcome],
    status_code=status.HTTP_200_OK,
)
async def list_observed_outcomes(
    target_reference: Optional[str] = Query(None),
    prediction_id: Optional[str] = Query(None),
    plant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(require_permission("learning.outcome.read")),
):
    """Lists observed outcomes within caller's authorized scope."""
    try:
        return outcome_evaluation_service.list_observed_outcomes(
            identity=user,
            target_reference=target_reference,
            prediction_id=prediction_id,
            plant_id=plant_id,
            limit=limit,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error listing observed outcomes: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while listing observed outcomes.",
        )


# =============================================================================
# 3. PREDICTION-OUTCOME EVALUATION ENDPOINTS
# =============================================================================

@router.post(
    "/evaluations",
    response_model=PredictionOutcomeEvaluation,
    status_code=status.HTTP_201_CREATED,
)
async def evaluate_prediction_outcome(
    req: EvaluationRequest,
    user: Identity = Depends(require_permission("learning.evaluation.evaluate")),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    x_trace_id: Optional[str] = Header(None, alias="X-Trace-ID"),
):
    """
    Evaluates a prediction against an observed outcome using deterministic comparison rules.
    Computes absolute error, signed error, relative error, directional bias, and learning eligibility.
    """
    try:
        evaluation = outcome_evaluation_service.evaluate_prediction_outcome(
            identity=user,
            prediction_id=req.prediction_id,
            outcome_id=req.outcome_id,
            idempotency_key=req.idempotency_key,
            reevaluation_reason=req.reevaluation_reason,
            correlation_id=x_trace_id or x_request_id,
        )
        return evaluation
    except PredictionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutcomeNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutcomeEvaluationIdempotencyConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error evaluating prediction '%s' and outcome '%s': %s", req.prediction_id, req.outcome_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while evaluating the prediction and outcome.",
        )


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=PredictionOutcomeEvaluation,
    status_code=status.HTTP_200_OK,
)
async def get_evaluation(
    evaluation_id: str,
    user: Identity = Depends(require_permission("learning.evaluation.read")),
):
    """Retrieves a single evaluation record within caller's scope."""
    try:
        return outcome_evaluation_service.get_evaluation(user, evaluation_id)
    except EvaluationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error retrieving evaluation '%s': %s", evaluation_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving the evaluation record.",
        )


@router.get(
    "/evaluations",
    response_model=List[PredictionOutcomeEvaluation],
    status_code=status.HTTP_200_OK,
)
async def list_evaluations(
    prediction_type: Optional[PredictionType] = Query(None),
    plant_id: Optional[str] = Query(None),
    data_mode: Optional[DataMode] = Query(None),
    eligible_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    window_start: Optional[str] = Query(None),
    window_end: Optional[str] = Query(None),
    user: Identity = Depends(require_permission("learning.evaluation.read")),
):
    """Lists evaluations within caller's authorized scope."""
    try:
        return outcome_evaluation_service.list_evaluations(
            identity=user,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            eligible_only=eligible_only,
            limit=limit,
            window_start=window_start,
            window_end=window_end,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error listing evaluations: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while listing evaluation records.",
        )


@router.post(
    "/evaluations/revalidate",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
)
async def revalidate_historical_evaluations(
    plant_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    user: Identity = Depends(require_permission("learning.evaluation.evaluate")),
):
    """
    Explicit remediation and revalidation endpoint for historical evaluations.
    Verifies that all evaluations marked eligible_for_learning are supported by
    canonical persisted verification records, updating and auditing any anomalies.
    """
    try:
        return outcome_evaluation_service.revalidate_historical_evaluations(
            identity=user,
            plant_id=plant_id,
            limit=limit,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error during historical evaluation revalidation: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during evaluation revalidation.",
        )


# =============================================================================
# 4. METRICS & LEARNING CONTEXT ENDPOINTS
# =============================================================================

@router.get(
    "/metrics",
    response_model=AggregateMetricsSummary,
    status_code=status.HTTP_200_OK,
)
async def get_aggregate_metrics(
    prediction_type: PredictionType = Query(...),
    plant_id: Optional[str] = Query(None),
    data_mode: Optional[DataMode] = Query(None),
    model_version: Optional[str] = Query(None),
    window_start: Optional[str] = Query(None),
    window_end: Optional[str] = Query(None),
    user: Identity = Depends(require_permission("learning.evaluation.read")),
):
    """Retrieves deterministic aggregate metrics across eligible evaluations."""
    try:
        return outcome_evaluation_service.get_aggregate_metrics(
            identity=user,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error calculating aggregate metrics: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while calculating aggregate metrics.",
        )


@router.get(
    "/context",
    response_model=GovernedLearningContext,
    status_code=status.HTTP_200_OK,
)
async def get_governed_learning_context(
    prediction_type: PredictionType = Query(...),
    plant_id: Optional[str] = Query(None),
    data_mode: Optional[DataMode] = Query(None),
    model_version: Optional[str] = Query(None),
    window_start: Optional[str] = Query(None),
    window_end: Optional[str] = Query(None),
    user: Identity = Depends(require_permission("learning.evaluation.read")),
):
    """
    Exposes eligible historical evaluation evidence to future decision-support processes.
    Read-only evidence; never constitutes operational execution authority.
    """
    try:
        return outcome_evaluation_service.get_governed_learning_context(
            identity=user,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
        )
    except OutcomeEvaluationScopeMismatchError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        logger.error("Error retrieving governed learning context: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while retrieving learning context.",
        )
