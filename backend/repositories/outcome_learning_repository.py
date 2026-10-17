# backend/repositories/outcome_learning_repository.py
"""
SageCommand V3 — Closed-Loop Outcome Learning Repository (Prompt 39)

A VERIFICATION RUN ASSESSES EVIDENCE AND VERIFICATION FINDINGS ONLY — NEVER CONSTITUTES
OPERATIONAL EXECUTION AUTHORITY, AUTONOMOUS EXECUTION, OR PHYSICAL MACHINE CONTROL.

Durable, scope-isolated SQLite persistence for:
1. Immutable prediction snapshots (record expectations before outcomes are observed).
2. Observed outcomes with explicit verification status and evidence provenance.
3. Append-only, idempotent prediction-outcome evaluations.
4. Bounded, deterministic metrics aggregation and governed learning-context snapshots.

Invariants:
- Uses SQLite WAL mode with immediate transactions and parameterization.
- Multi-tenant and workspace scope-enforced queries (never wildcard across tenants).
- Strict immutability: Predictions and evaluations cannot be rewritten or mutated.
- Re-evaluations create new records linking to previous evaluation IDs.
- Deterministic idempotency protects against redelivery and concurrent workers.
- Zero raw string formatting for SQL identifiers/queries.
"""

import json
import logging
import math
import os
import sqlite3
import threading
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta

try:
    from core.config import SAGE_VERIFICATION_DB_PATH
    from data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_VERIFICATION_DB_PATH
    from backend.data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )

logger = logging.getLogger("outcome_learning_repository")


# =============================================================================
# REPOSITORY EXCEPTIONS
# =============================================================================

class OutcomeLearningError(Exception):
    """Base exception for outcome learning operations."""
    pass


class PredictionNotFoundError(OutcomeLearningError):
    """Raised when a requested prediction snapshot does not exist within scope."""
    pass


class OutcomeNotFoundError(OutcomeLearningError):
    """Raised when an observed outcome does not exist within scope."""
    pass


class EvaluationNotFoundError(OutcomeLearningError):
    """Raised when an evaluation record does not exist within scope."""
    pass


class PredictionImmutabilityViolationError(OutcomeLearningError):
    """Raised when attempting to overwrite or alter an immutable prediction snapshot."""
    pass


class OutcomeImmutabilityViolationError(OutcomeLearningError):
    """Raised when attempting to overwrite an observed outcome with conflicting content."""
    pass


class OutcomeEvaluationIdempotencyConflictError(OutcomeLearningError):
    """Raised when an idempotency key is reused with conflicting parameters."""
    pass


class OutcomeEvaluationScopeMismatchError(OutcomeLearningError):
    """Raised when scope boundary check fails during outcome learning."""
    pass


# =============================================================================
# REPOSITORY IMPLEMENTATION
# =============================================================================

class OutcomeLearningRepository:
    """
    Durable SQLite repository for prediction snapshots, observed outcomes,
    and append-only prediction-outcome evaluations.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or SAGE_VERIFICATION_DB_PATH
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Returns SQLite connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(self._db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self):
        """Creates tables, indices, and constraints for Prompt 39."""
        with self._lock, self._get_connection() as conn:
            # 1. Prediction Snapshots Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prediction_snapshots (
                    prediction_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT '3.0.0',
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    plant_id TEXT NOT NULL,
                    prediction_type TEXT NOT NULL,
                    target_reference TEXT NOT NULL,
                    predicted_at TEXT NOT NULL,
                    expected_value_json TEXT NOT NULL,
                    expected_unit TEXT,
                    forecast_horizon TEXT,
                    evaluation_window_start TEXT,
                    evaluation_window_end TEXT,
                    prediction_method TEXT,
                    model_version TEXT,
                    prediction_provenance TEXT NOT NULL,
                    data_mode TEXT NOT NULL,
                    source_references_json TEXT NOT NULL DEFAULT '{}',
                    is_superseded INTEGER NOT NULL DEFAULT 0,
                    superseded_by TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, workspace_id, prediction_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_psnap_target
                ON prediction_snapshots (tenant_id, workspace_id, target_reference, predicted_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_psnap_type
                ON prediction_snapshots (tenant_id, workspace_id, prediction_type, created_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_psnap_plant
                ON prediction_snapshots (tenant_id, plant_id, created_at DESC)
            """)

            # 2. Observed Outcomes Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS observed_outcomes (
                    outcome_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT '3.0.0',
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    plant_id TEXT NOT NULL,
                    prediction_id TEXT,
                    target_reference TEXT NOT NULL,
                    outcome_type TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    observed_value_json TEXT NOT NULL,
                    unit TEXT,
                    source_references_json TEXT NOT NULL DEFAULT '{}',
                    verification_reference TEXT,
                    verification_status TEXT NOT NULL,
                    is_diagnostic INTEGER NOT NULL DEFAULT 0,
                    is_invalidated INTEGER NOT NULL DEFAULT 0,
                    provenance TEXT NOT NULL,
                    data_mode TEXT NOT NULL,
                    correlation_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, workspace_id, outcome_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ooutc_pred
                ON observed_outcomes (tenant_id, workspace_id, prediction_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ooutc_target
                ON observed_outcomes (tenant_id, workspace_id, target_reference, observed_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ooutc_status
                ON observed_outcomes (tenant_id, workspace_id, verification_status)
            """)

            # 3. Prediction-Outcome Evaluations Table (Append-Only)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prediction_outcome_evaluations (
                    evaluation_id TEXT NOT NULL,
                    schema_version TEXT NOT NULL DEFAULT '3.0.0',
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    plant_id TEXT NOT NULL,
                    prediction_id TEXT NOT NULL,
                    outcome_id TEXT NOT NULL,
                    evaluation_status TEXT NOT NULL,
                    eligibility_reason TEXT NOT NULL,
                    evaluation_policy_version TEXT NOT NULL,
                    metric_implementation_version TEXT NOT NULL,
                    prediction_type TEXT NOT NULL,
                    target_reference TEXT NOT NULL,
                    predicted_value_json TEXT NOT NULL,
                    observed_value_json TEXT NOT NULL,
                    unit TEXT,
                    comparison_semantics TEXT NOT NULL,
                    absolute_error REAL,
                    signed_error REAL,
                    relative_error REAL,
                    directional_bias TEXT,
                    exact_match INTEGER,
                    verification_reference TEXT,
                    is_diagnostic INTEGER NOT NULL DEFAULT 0,
                    eligible_for_learning INTEGER NOT NULL DEFAULT 0,
                    learning_ineligibility_reason TEXT,
                    provenance TEXT NOT NULL,
                    data_mode TEXT NOT NULL,
                    prior_evaluation_id TEXT,
                    reevaluation_reason TEXT,
                    idempotency_key TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    correlation_id TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (tenant_id, workspace_id, evaluation_id),
                    UNIQUE (tenant_id, workspace_id, idempotency_key)
                )
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_canonical_pair
                ON prediction_outcome_evaluations (tenant_id, workspace_id, prediction_id, outcome_id, evaluation_policy_version)
                WHERE prior_evaluation_id IS NULL AND reevaluation_reason IS NULL
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_pred
                ON prediction_outcome_evaluations (tenant_id, workspace_id, prediction_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_outc
                ON prediction_outcome_evaluations (tenant_id, workspace_id, outcome_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_type
                ON prediction_outcome_evaluations (tenant_id, workspace_id, prediction_type, evaluated_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_learning
                ON prediction_outcome_evaluations (tenant_id, workspace_id, eligible_for_learning, data_mode)
            """)

            # Safe migration if tables pre-existed without schema_version
            for tbl in ("prediction_snapshots", "observed_outcomes", "prediction_outcome_evaluations"):
                try:
                    cols_info = conn.execute("PRAGMA table_info(" + tbl + ")").fetchall()
                    col_names = [c["name"] for c in cols_info]
                    if col_names and "schema_version" not in col_names:
                        conn.execute("ALTER TABLE " + tbl + " ADD COLUMN schema_version TEXT NOT NULL DEFAULT '3.0.0'")
                except Exception:
                    pass
            conn.commit()

    # -------------------------------------------------------------------------
    # 1. PREDICTION SNAPSHOT PERSISTENCE
    # -------------------------------------------------------------------------

    def record_prediction_snapshot(self, snapshot: PredictionSnapshot) -> PredictionSnapshot:
        """
        Immutably records a prediction snapshot.
        If a snapshot with the same ID already exists:
        - If fingerprint matches: returns existing snapshot (idempotent replay).
        - If fingerprint differs: raises PredictionImmutabilityViolationError.
        """
        self._validate_scope(snapshot.tenant_id, snapshot.workspace_id, snapshot.plant_id)

        query_existing = """
            SELECT * FROM prediction_snapshots
            WHERE tenant_id = ? AND workspace_id = ? AND prediction_id = ?
        """
        insert_sql = """
            INSERT INTO prediction_snapshots (
                prediction_id, schema_version, tenant_id, workspace_id, plant_id,
                prediction_type, target_reference, predicted_at,
                expected_value_json, expected_unit, forecast_horizon,
                evaluation_window_start, evaluation_window_end,
                prediction_method, model_version, prediction_provenance,
                data_mode, source_references_json, is_superseded,
                superseded_by, details_json, created_at, fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        new_fp = snapshot.compute_fingerprint()
        params = (
            snapshot.prediction_id,
            snapshot.schema_version,
            snapshot.tenant_id,
            snapshot.workspace_id,
            snapshot.plant_id,
            snapshot.prediction_type.value,
            snapshot.target_reference,
            snapshot.predicted_at,
            json.dumps(snapshot.expected_value),
            snapshot.expected_unit,
            snapshot.forecast_horizon,
            snapshot.evaluation_window_start,
            snapshot.evaluation_window_end,
            snapshot.prediction_method,
            snapshot.model_version,
            snapshot.prediction_provenance,
            snapshot.data_mode.value,
            json.dumps(snapshot.source_references),
            1 if snapshot.is_superseded else 0,
            snapshot.superseded_by,
            json.dumps(snapshot.details),
            snapshot.created_at,
            new_fp,
        )

        with self._lock, self._get_connection() as conn:
            existing = conn.execute(query_existing, (snapshot.tenant_id, snapshot.workspace_id, snapshot.prediction_id)).fetchone()
            if existing:
                if existing["fingerprint"] == new_fp:
                    return self._row_to_prediction(existing)
                raise PredictionImmutabilityViolationError(
                    f"Prediction '{snapshot.prediction_id}' already exists and is immutable with differing content."
                )
            conn.execute(insert_sql, params)
            conn.commit()
        return snapshot

    def get_prediction_snapshot(
        self, tenant_id: str, workspace_id: str, prediction_id: str
    ) -> Optional[PredictionSnapshot]:
        """Retrieves a single prediction snapshot strictly scoped to tenant and workspace."""
        query = """
            SELECT * FROM prediction_snapshots
            WHERE tenant_id = ? AND workspace_id = ? AND prediction_id = ?
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, workspace_id, prediction_id)).fetchone()
            if not row:
                return None
            return self._row_to_prediction(row)

    def supersede_prediction_snapshot(
        self, tenant_id: str, workspace_id: str, prediction_id: str, superseded_by_id: str
    ) -> bool:
        """
        Marks a prediction snapshot as superseded by another prediction without altering
        its original expectation fields.
        """
        update_sql = """
            UPDATE prediction_snapshots
            SET is_superseded = 1, superseded_by = ?
            WHERE tenant_id = ? AND workspace_id = ? AND prediction_id = ?
        """
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(update_sql, (superseded_by_id, tenant_id, workspace_id, prediction_id))
            conn.commit()
            return cursor.rowcount > 0

    def list_prediction_snapshots(
        self,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str] = None,
        prediction_type: Optional[PredictionType] = None,
        limit: int = 50,
    ) -> List[PredictionSnapshot]:
        """Lists prediction snapshots scoped to tenant and workspace."""
        query = """
            SELECT * FROM prediction_snapshots
            WHERE tenant_id = ? AND workspace_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id]
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if prediction_type:
            val = prediction_type.value if hasattr(prediction_type, "value") else str(prediction_type)
            query += " AND prediction_type = ?"
            params.append(val)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(max(1, limit), 200))

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_prediction(r) for r in rows]

    # -------------------------------------------------------------------------
    # 2. OBSERVED OUTCOME PERSISTENCE
    # -------------------------------------------------------------------------

    def record_observed_outcome(self, outcome: ObservedOutcome) -> ObservedOutcome:
        """
        Records an observed outcome.
        If outcome exists:
        - If fingerprint matches: returns existing (idempotent).
        - If fingerprint differs: raises OutcomeImmutabilityViolationError.
        """
        self._validate_scope(outcome.tenant_id, outcome.workspace_id, outcome.plant_id)

        query_existing = """
            SELECT * FROM observed_outcomes
            WHERE tenant_id = ? AND workspace_id = ? AND outcome_id = ?
        """
        insert_sql = """
            INSERT INTO observed_outcomes (
                outcome_id, schema_version, tenant_id, workspace_id, plant_id,
                prediction_id, target_reference, outcome_type,
                observed_at, recorded_at, observed_value_json,
                unit, source_references_json, verification_reference,
                verification_status, is_diagnostic, is_invalidated,
                provenance, data_mode, correlation_id, details_json,
                created_at, fingerprint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        new_fp = outcome.compute_fingerprint()
        params = (
            outcome.outcome_id,
            outcome.schema_version,
            outcome.tenant_id,
            outcome.workspace_id,
            outcome.plant_id,
            outcome.prediction_id,
            outcome.target_reference,
            outcome.outcome_type,
            outcome.observed_at,
            outcome.recorded_at,
            json.dumps(outcome.observed_value),
            outcome.unit,
            json.dumps(outcome.source_references),
            outcome.verification_reference,
            outcome.verification_status.value,
            1 if outcome.is_diagnostic else 0,
            1 if outcome.is_invalidated else 0,
            outcome.provenance,
            outcome.data_mode.value,
            outcome.correlation_id,
            json.dumps(outcome.details),
            outcome.created_at,
            new_fp,
        )

        with self._lock, self._get_connection() as conn:
            existing = conn.execute(query_existing, (outcome.tenant_id, outcome.workspace_id, outcome.outcome_id)).fetchone()
            if existing:
                if existing["fingerprint"] == new_fp:
                    return self._row_to_outcome(existing)
                raise OutcomeImmutabilityViolationError(
                    f"Observed outcome '{outcome.outcome_id}' already exists with differing canonical data."
                )
            conn.execute(insert_sql, params)
            conn.commit()
        return outcome

    def get_observed_outcome(
        self, tenant_id: str, workspace_id: str, outcome_id: str
    ) -> Optional[ObservedOutcome]:
        """Retrieves a single observed outcome scoped strictly to tenant and workspace."""
        query = """
            SELECT * FROM observed_outcomes
            WHERE tenant_id = ? AND workspace_id = ? AND outcome_id = ?
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, workspace_id, outcome_id)).fetchone()
            if not row:
                return None
            return self._row_to_outcome(row)

    def list_observed_outcomes(
        self,
        tenant_id: str,
        workspace_id: str,
        target_reference: Optional[str] = None,
        prediction_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[ObservedOutcome]:
        """Lists observed outcomes within tenant and workspace scope."""
        query = """
            SELECT * FROM observed_outcomes
            WHERE tenant_id = ? AND workspace_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id]
        if target_reference:
            query += " AND target_reference = ?"
            params.append(target_reference)
        if prediction_id:
            query += " AND prediction_id = ?"
            params.append(prediction_id)
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(min(max(1, limit), 200))

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_outcome(r) for r in rows]

    # -------------------------------------------------------------------------
    # 3. PREDICTION-OUTCOME EVALUATION PERSISTENCE (APPEND-ONLY)
    # -------------------------------------------------------------------------

    def record_evaluation(
        self, evaluation: PredictionOutcomeEvaluation
    ) -> PredictionOutcomeEvaluation:
        """
        Atomically records an append-only evaluation record.
        Enforces idempotency by idempotency_key and canonical prediction/outcome/policy unique constraint.
        """
        self._validate_scope(evaluation.tenant_id, evaluation.workspace_id, evaluation.plant_id)

        query_idem = """
            SELECT * FROM prediction_outcome_evaluations
            WHERE tenant_id = ? AND workspace_id = ? AND idempotency_key = ?
        """
        query_pair = """
            SELECT * FROM prediction_outcome_evaluations
            WHERE tenant_id = ? AND workspace_id = ?
              AND prediction_id = ? AND outcome_id = ? AND evaluation_policy_version = ?
        """
        insert_sql = """
            INSERT INTO prediction_outcome_evaluations (
                evaluation_id, schema_version, tenant_id, workspace_id, plant_id,
                prediction_id, outcome_id, evaluation_status,
                eligibility_reason, evaluation_policy_version,
                metric_implementation_version, prediction_type,
                target_reference, predicted_value_json, observed_value_json,
                unit, comparison_semantics, absolute_error, signed_error,
                relative_error, directional_bias, exact_match,
                verification_reference, is_diagnostic, eligible_for_learning,
                learning_ineligibility_reason, provenance, data_mode,
                prior_evaluation_id, reevaluation_reason, idempotency_key,
                evaluated_at, correlation_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            evaluation.evaluation_id,
            evaluation.schema_version,
            evaluation.tenant_id,
            evaluation.workspace_id,
            evaluation.plant_id,
            evaluation.prediction_id,
            evaluation.outcome_id,
            evaluation.evaluation_status.value,
            evaluation.eligibility_reason,
            evaluation.evaluation_policy_version,
            evaluation.metric_implementation_version,
            evaluation.prediction_type.value,
            evaluation.target_reference,
            json.dumps(evaluation.predicted_value),
            json.dumps(evaluation.observed_value),
            evaluation.unit,
            evaluation.comparison_semantics,
            evaluation.absolute_error,
            evaluation.signed_error,
            evaluation.relative_error,
            evaluation.directional_bias.value if evaluation.directional_bias else None,
            1 if evaluation.exact_match else (0 if evaluation.exact_match is False else None),
            evaluation.verification_reference,
            1 if evaluation.is_diagnostic else 0,
            1 if evaluation.eligible_for_learning else 0,
            evaluation.learning_ineligibility_reason,
            evaluation.provenance,
            evaluation.data_mode.value,
            evaluation.prior_evaluation_id,
            evaluation.reevaluation_reason,
            evaluation.idempotency_key,
            evaluation.evaluated_at,
            evaluation.correlation_id,
            json.dumps(evaluation.details),
        )

        with self._lock, self._get_connection() as conn:
            # Check idempotency key first
            existing_by_idem = conn.execute(
                query_idem, (evaluation.tenant_id, evaluation.workspace_id, evaluation.idempotency_key)
            ).fetchone()
            if existing_by_idem:
                if (
                    existing_by_idem["prediction_id"] == evaluation.prediction_id
                    and existing_by_idem["outcome_id"] == evaluation.outcome_id
                ):
                    return self._row_to_evaluation(existing_by_idem)
                raise OutcomeEvaluationIdempotencyConflictError(
                    f"Idempotency key '{evaluation.idempotency_key}' reused with conflicting prediction/outcome IDs."
                )

            # Check canonical prediction-outcome-policy unique pair
            # (unless explicit prior_evaluation_id or reevaluation_reason indicates intentional re-evaluation)
            if not evaluation.prior_evaluation_id and not evaluation.reevaluation_reason:
                existing_by_pair = conn.execute(
                    query_pair,
                    (
                        evaluation.tenant_id,
                        evaluation.workspace_id,
                        evaluation.prediction_id,
                        evaluation.outcome_id,
                        evaluation.evaluation_policy_version,
                    ),
                ).fetchone()
                if existing_by_pair:
                    return self._row_to_evaluation(existing_by_pair)

            try:
                conn.execute(insert_sql, params)
                conn.commit()
            except sqlite3.IntegrityError as e:
                # Concurrency safety: check if another worker just committed this exact evaluation
                existing_concurrent = conn.execute(
                    query_idem, (evaluation.tenant_id, evaluation.workspace_id, evaluation.idempotency_key)
                ).fetchone()
                if existing_concurrent:
                    return self._row_to_evaluation(existing_concurrent)
                if not evaluation.prior_evaluation_id and not evaluation.reevaluation_reason:
                    existing_pair = conn.execute(
                        query_pair,
                        (
                            evaluation.tenant_id,
                            evaluation.workspace_id,
                            evaluation.prediction_id,
                            evaluation.outcome_id,
                            evaluation.evaluation_policy_version,
                        ),
                    ).fetchone()
                    if existing_pair:
                        return self._row_to_evaluation(existing_pair)
                raise OutcomeEvaluationIdempotencyConflictError(f"Database integrity conflict during evaluation creation: {e}")
        return evaluation

    def get_evaluation(
        self, tenant_id: str, workspace_id: str, evaluation_id: str
    ) -> Optional[PredictionOutcomeEvaluation]:
        """Retrieves a single evaluation record within tenant and workspace scope."""
        query = """
            SELECT * FROM prediction_outcome_evaluations
            WHERE tenant_id = ? AND workspace_id = ? AND evaluation_id = ?
        """
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (tenant_id, workspace_id, evaluation_id)).fetchone()
            if not row:
                return None
            return self._row_to_evaluation(row)

    def list_evaluations(
        self,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str] = None,
        prediction_type: Optional[PredictionType] = None,
        data_mode: Optional[DataMode] = None,
        eligible_only: bool = False,
        limit: int = 50,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
    ) -> List[PredictionOutcomeEvaluation]:
        """Lists evaluations within authorized scope with bounded pagination."""
        query = """
            SELECT * FROM prediction_outcome_evaluations
            WHERE tenant_id = ? AND workspace_id = ?
        """
        params: List[Any] = [tenant_id, workspace_id]
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if prediction_type:
            val = prediction_type.value if hasattr(prediction_type, "value") else str(prediction_type)
            query += " AND prediction_type = ?"
            params.append(val)
        if data_mode:
            val = data_mode.value if hasattr(data_mode, "value") else str(data_mode)
            query += " AND data_mode = ?"
            params.append(val)
        if eligible_only:
            query += " AND eligible_for_learning = 1"
        if window_start:
            query += " AND evaluated_at >= ?"
            params.append(window_start)
        if window_end:
            query += " AND evaluated_at <= ?"
            params.append(window_end)
        query += " ORDER BY evaluated_at DESC LIMIT ?"
        params.append(min(max(1, limit), 200))

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_evaluation(r) for r in rows]

    # -------------------------------------------------------------------------
    # 4. METRICS AGGREGATION & GOVERNED LEARNING CONTEXT
    # -------------------------------------------------------------------------

    def calculate_aggregate_metrics(
        self,
        tenant_id: str,
        workspace_id: str,
        prediction_type: PredictionType,
        plant_id: Optional[str] = None,
        data_mode: Optional[DataMode] = None,
        model_version: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        min_sample_threshold: int = 5,
    ) -> AggregateMetricsSummary:
        """
        Calculates deterministic aggregate performance metrics across eligible evaluations.
        Enforces sample thresholding, time-window bounding, and zero-denominator safety.
        """
        self._validate_scope(tenant_id, workspace_id, plant_id if plant_id else "plant_scope_check")

        pred_type_str = prediction_type.value if hasattr(prediction_type, "value") else str(prediction_type)
        mode_str = data_mode.value if data_mode and hasattr(data_mode, "value") else (str(data_mode) if data_mode else DataMode.REAL.value)

        # Base query to fetch relevant evaluations
        query = """
            SELECT
                evaluation_id, evaluation_status, absolute_error, signed_error,
                relative_error, directional_bias, exact_match, unit,
                eligible_for_learning, learning_ineligibility_reason
            FROM prediction_outcome_evaluations
            WHERE tenant_id = ? AND workspace_id = ? AND prediction_type = ? AND data_mode = ?
        """
        params: List[Any] = [tenant_id, workspace_id, pred_type_str, mode_str]
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if window_start:
            query += " AND evaluated_at >= ?"
            params.append(window_start)
        if window_end:
            query += " AND evaluated_at <= ?"
            params.append(window_end)

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        total_count = len(rows)
        eligible_rows = [r for r in rows if r["eligible_for_learning"] == 1 and r["evaluation_status"] == EvaluationStatus.EVALUATED.value]
        eligible_count = len(eligible_rows)
        excluded_count = total_count - eligible_count

        unverified_count = 0
        deferred_count = 0
        rejected_count = 0
        for r in rows:
            if r["evaluation_status"] == EvaluationStatus.DEFERRED.value:
                deferred_count += 1
            elif r["evaluation_status"] == EvaluationStatus.REJECTED.value:
                rejected_count += 1
            elif r["eligible_for_learning"] == 0 and r["learning_ineligibility_reason"] == "OUTCOME_NOT_VERIFIED":
                unverified_count += 1

        unit: Optional[str] = eligible_rows[0]["unit"] if eligible_rows and eligible_rows[0]["unit"] else None

        # Sample threshold evaluation
        sample_status = "SUFFICIENT_DATA" if eligible_count >= min_sample_threshold else "INSUFFICIENT_DATA"

        # Metric calculations over eligible rows
        mae: Optional[float] = None
        signed_mean: Optional[float] = None
        rmse: Optional[float] = None
        mape: Optional[float] = None
        exact_match_rate: Optional[float] = None

        over_count = 0
        under_count = 0
        exact_matched = 0

        if eligible_count > 0:
            abs_errors = [r["absolute_error"] for r in eligible_rows if r["absolute_error"] is not None]
            signed_errors = [r["signed_error"] for r in eligible_rows if r["signed_error"] is not None]
            rel_errors = [r["relative_error"] for r in eligible_rows if r["relative_error"] is not None]
            match_flags = [r["exact_match"] for r in eligible_rows if r["exact_match"] is not None]

            if abs_errors:
                mae = round(sum(abs_errors) / len(abs_errors), 4)
                rmse = round(math.sqrt(sum(e ** 2 for e in abs_errors) / len(abs_errors)), 4)
            if signed_errors:
                signed_mean = round(sum(signed_errors) / len(signed_errors), 4)
            if rel_errors:
                mape = round((sum(rel_errors) / len(rel_errors)) * 100.0, 4)

            for r in eligible_rows:
                bias = r["directional_bias"]
                if bias == DirectionalBias.OVER_PREDICTED.value:
                    over_count += 1
                elif bias == DirectionalBias.UNDER_PREDICTED.value:
                    under_count += 1
                elif bias == DirectionalBias.MATCHED.value:
                    exact_matched += 1

            if match_flags:
                true_matches = sum(1 for m in match_flags if m == 1)
                exact_match_rate = round(true_matches / len(match_flags), 4)

        return AggregateMetricsSummary(
            prediction_type=prediction_type,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            data_mode=data_mode or DataMode.REAL,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
            total_evaluations=total_count,
            eligible_sample_count=eligible_count,
            excluded_evaluations=excluded_count,
            sample_status=sample_status,
            min_sample_threshold=min_sample_threshold,
            mean_absolute_error=mae,
            mean_absolute_percentage_error=mape,
            root_mean_squared_error=rmse,
            signed_mean_error=signed_mean,
            over_predicted_count=over_count,
            under_predicted_count=under_count,
            exact_matched_count=exact_matched,
            exact_match_rate=exact_match_rate,
            unverified_count=unverified_count,
            deferred_count=deferred_count,
            rejected_count=rejected_count,
            unit=unit,
            metric_implementation_version=METRIC_IMPLEMENTATION_VERSION,
        )

    def get_governed_learning_context(
        self,
        tenant_id: str,
        workspace_id: str,
        prediction_type: PredictionType,
        plant_id: Optional[str] = None,
        data_mode: Optional[DataMode] = None,
        model_version: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        min_sample_threshold: int = 5,
    ) -> GovernedLearningContext:
        """
        Retrieves scoped historical evaluation context formatted for future decision support.
        Strictly read-only; never grants operational execution authority.
        """
        metrics = self.calculate_aggregate_metrics(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            prediction_type=prediction_type,
            plant_id=plant_id,
            data_mode=data_mode,
            model_version=model_version,
            window_start=window_start,
            window_end=window_end,
            min_sample_threshold=min_sample_threshold,
        )

        directional_tendency: Optional[str] = None
        if metrics.sample_status == "SUFFICIENT_DATA":
            if metrics.over_predicted_count > metrics.under_predicted_count * 1.5:
                directional_tendency = "SYSTEMATIC_OVER_PREDICTION"
            elif metrics.under_predicted_count > metrics.over_predicted_count * 1.5:
                directional_tendency = "SYSTEMATIC_UNDER_PREDICTION"
            else:
                directional_tendency = "BALANCED_PREDICTION_DISTRIBUTION"
        else:
            directional_tendency = "INSUFFICIENT_DATA"

        limitations: List[str] = []
        if metrics.sample_status == "INSUFFICIENT_DATA":
            limitations.append(
                f"Sample size ({metrics.eligible_sample_count}) is below minimum threshold ({min_sample_threshold}). Metric is not statistically reliable."
            )
        if metrics.excluded_evaluations > 0:
            limitations.append(
                f"{metrics.excluded_evaluations} evaluations were excluded due to unverified outcomes, diagnostic checks, or simulation data."
            )
        limitations.append(
            "Governed learning context is evidence for decision support only — NEVER constitutes operational execution authority."
        )

        return GovernedLearningContext(
            prediction_type=prediction_type,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            model_version=model_version,
            data_mode=data_mode or DataMode.REAL,
            sample_count=metrics.eligible_sample_count,
            evaluation_status=metrics.sample_status,
            mean_absolute_error=metrics.mean_absolute_error,
            mean_absolute_percentage_error=metrics.mean_absolute_percentage_error,
            signed_mean_error=metrics.signed_mean_error,
            directional_tendency=directional_tendency,
            unit=metrics.unit,
            window_start=window_start,
            window_end=window_end,
            provenance="verified_outcome_evaluations",
            limitations=limitations,
        )

    # -------------------------------------------------------------------------
    # 5. INTERNAL HELPERS & ROW DESERIALIZATION
    # -------------------------------------------------------------------------

    def _validate_scope(self, tenant_id: str, workspace_id: str, plant_id: str):
        """Rejects empty, whitespace, or manufactured scope identifiers."""
        for name, val in [("tenant_id", tenant_id), ("workspace_id", workspace_id), ("plant_id", plant_id)]:
            if not val or not val.strip():
                raise OutcomeEvaluationScopeMismatchError(f"Scope parameter '{name}' cannot be empty.")
            norm = val.strip().lower()
            if norm in ("global", "unknown", "default"):
                raise OutcomeEvaluationScopeMismatchError(
                    f"Manufactured or wildcard scope '{val}' is prohibited for '{name}'."
                )

    def _row_to_prediction(self, row: sqlite3.Row) -> PredictionSnapshot:
        return PredictionSnapshot(
            prediction_id=row["prediction_id"],
            schema_version=row["schema_version"],
            prediction_type=PredictionType(row["prediction_type"]),
            target_reference=row["target_reference"],
            predicted_at=row["predicted_at"],
            expected_value=json.loads(row["expected_value_json"]),
            expected_unit=row["expected_unit"],
            forecast_horizon=row["forecast_horizon"],
            evaluation_window_start=row["evaluation_window_start"],
            evaluation_window_end=row["evaluation_window_end"],
            prediction_method=row["prediction_method"],
            model_version=row["model_version"],
            prediction_provenance=row["prediction_provenance"],
            data_mode=DataMode(row["data_mode"]),
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            source_references=json.loads(row["source_references_json"]),
            is_superseded=bool(row["is_superseded"]),
            superseded_by=row["superseded_by"],
            details=json.loads(row["details_json"]),
            created_at=row["created_at"],
        )

    def _row_to_outcome(self, row: sqlite3.Row) -> ObservedOutcome:
        return ObservedOutcome(
            outcome_id=row["outcome_id"],
            schema_version=row["schema_version"],
            prediction_id=row["prediction_id"],
            target_reference=row["target_reference"],
            outcome_type=row["outcome_type"],
            observed_at=row["observed_at"],
            recorded_at=row["recorded_at"],
            observed_value=json.loads(row["observed_value_json"]),
            unit=row["unit"],
            source_references=json.loads(row["source_references_json"]),
            verification_reference=row["verification_reference"],
            verification_status=OutcomeVerificationStatus(row["verification_status"]),
            is_diagnostic=bool(row["is_diagnostic"]),
            is_invalidated=bool(row["is_invalidated"]),
            provenance=row["provenance"],
            data_mode=DataMode(row["data_mode"]),
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            correlation_id=row["correlation_id"],
            details=json.loads(row["details_json"]),
            created_at=row["created_at"],
        )

    def _row_to_evaluation(self, row: sqlite3.Row) -> PredictionOutcomeEvaluation:
        return PredictionOutcomeEvaluation(
            evaluation_id=row["evaluation_id"],
            schema_version=row["schema_version"],
            prediction_id=row["prediction_id"],
            outcome_id=row["outcome_id"],
            evaluation_status=EvaluationStatus(row["evaluation_status"]),
            eligibility_reason=row["eligibility_reason"],
            evaluation_policy_version=row["evaluation_policy_version"],
            metric_implementation_version=row["metric_implementation_version"],
            prediction_type=PredictionType(row["prediction_type"]),
            target_reference=row["target_reference"],
            predicted_value=json.loads(row["predicted_value_json"]),
            observed_value=json.loads(row["observed_value_json"]),
            unit=row["unit"],
            comparison_semantics=row["comparison_semantics"],
            absolute_error=row["absolute_error"],
            signed_error=row["signed_error"],
            relative_error=row["relative_error"],
            directional_bias=DirectionalBias(row["directional_bias"]) if row["directional_bias"] else None,
            exact_match=bool(row["exact_match"]) if row["exact_match"] is not None else None,
            verification_reference=row["verification_reference"],
            is_diagnostic=bool(row["is_diagnostic"]),
            eligible_for_learning=bool(row["eligible_for_learning"]),
            learning_ineligibility_reason=row["learning_ineligibility_reason"],
            provenance=row["provenance"],
            data_mode=DataMode(row["data_mode"]),
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            prior_evaluation_id=row["prior_evaluation_id"],
            reevaluation_reason=row["reevaluation_reason"],
            idempotency_key=row["idempotency_key"],
            evaluated_at=row["evaluated_at"],
            correlation_id=row["correlation_id"],
            details=json.loads(row["details_json"]),
        )


# Canonical singleton repository instance
outcome_learning_repository = OutcomeLearningRepository()
