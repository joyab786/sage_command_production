# backend/repositories/optimization_repository.py
"""
SageCommand V3 — Optimization Intelligence Repository (Prompt 29)

SQLite WAL-backed persistence for Optimization Problems, Results, Candidates, Evidence,
and Sensitivities.

Invariants:
- WAL journal mode for high read concurrency.
- All SQL queries strictly parameterized (no string formatting/concatenation).
- Tenant isolation enforced on every query.
- Workspace and Plant isolation enforced when provided.
- Bounded query results (limit capped at 200).
- Deterministic fingerprint lookup and idempotent deduplication.
- Foreign keys enabled.
- Concurrency-safe via thread locking.

ANALYTICAL ONLY. No physical systems, controllers, PLCs, or actuators are modified.
"""

import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any

try:
    from core.config import SAGE_OPTIMIZATION_DB_PATH, SAGE_OPTIMIZATION_MAX_PROBLEMS
    from data.schemas.optimization_contract import (
        OptimizationResult,
        OptimizationResultSummary,
        OptimizationProblem,
        OptimizationCandidate,
        OptimizationEvidence,
        SensitivityResult,
        TradeoffAssessment,
        FeasibilityResult,
        OptimizationExplanation,
        OptimizationLimitation,
        RobustnessStatus,
        OptimalityStatus,
        OptimizationConfidence,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_OPTIMIZATION_DB_PATH, SAGE_OPTIMIZATION_MAX_PROBLEMS
    from backend.data.schemas.optimization_contract import (
        OptimizationResult,
        OptimizationResultSummary,
        OptimizationProblem,
        OptimizationCandidate,
        OptimizationEvidence,
        SensitivityResult,
        TradeoffAssessment,
        FeasibilityResult,
        OptimizationExplanation,
        OptimizationLimitation,
        RobustnessStatus,
        OptimalityStatus,
        OptimizationConfidence,
    )

_SCHEMA_VERSION = "1.0"
_MAX_QUERY_LIMIT = min(SAGE_OPTIMIZATION_MAX_PROBLEMS, 200)


class OptimizationRepository:
    """
    Thread-safe, tenant-isolated SQLite repository for Optimization Problems and Results.
    """

    def __init__(self, db_path: str = SAGE_OPTIMIZATION_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            # 1. optimization_problems
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_problems (
                    problem_id              TEXT PRIMARY KEY,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    name                    TEXT NOT NULL,
                    decision_scope          TEXT NOT NULL,
                    method                  TEXT NOT NULL,
                    multi_objective_method  TEXT NOT NULL,
                    assessment_timestamp    TEXT NOT NULL,
                    horizon                 TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL
                )
                """
            )

            # 2. optimization_results
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_results (
                    optimization_id         TEXT PRIMARY KEY,
                    problem_id              TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    problem_name            TEXT NOT NULL,
                    assessment_timestamp    TEXT NOT NULL,
                    optimality_status       TEXT NOT NULL,
                    confidence              TEXT NOT NULL,
                    is_feasible             INTEGER NOT NULL,
                    candidate_count         INTEGER NOT NULL DEFAULT 0,
                    variable_count          INTEGER NOT NULL DEFAULT 0,
                    objective_count         INTEGER NOT NULL DEFAULT 0,
                    constraint_count        INTEGER NOT NULL DEFAULT 0,
                    input_fingerprint       TEXT NOT NULL,
                    method                  TEXT NOT NULL,
                    method_version          TEXT NOT NULL DEFAULT '1.0.0',
                    schema_version          TEXT NOT NULL DEFAULT '1.0',
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL,
                    FOREIGN KEY(problem_id) REFERENCES optimization_problems(problem_id) ON DELETE CASCADE
                )
                """
            )

            # Ensure columns exist if table was created in an older run
            cursor = conn.execute("PRAGMA table_info(optimization_results)")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "assessment_timestamp" not in existing_cols:
                conn.execute("ALTER TABLE optimization_results ADD COLUMN assessment_timestamp TEXT NOT NULL DEFAULT ''")

            # 3. optimization_candidates
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_candidates (
                    candidate_id            TEXT NOT NULL,
                    optimization_id         TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    rank                    INTEGER NOT NULL,
                    score                   REAL NOT NULL,
                    feasibility             TEXT NOT NULL,
                    is_recommended          INTEGER NOT NULL DEFAULT 0,
                    decision_values_json    TEXT NOT NULL,
                    objective_values_json   TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    PRIMARY KEY (optimization_id, candidate_id),
                    FOREIGN KEY(optimization_id) REFERENCES optimization_results(optimization_id) ON DELETE CASCADE
                )
                """
            )

            # 4. optimization_evidence
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_evidence (
                    evidence_id             TEXT NOT NULL,
                    optimization_id         TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    source_type             TEXT NOT NULL,
                    source_id               TEXT NOT NULL,
                    confidence              TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    PRIMARY KEY (optimization_id, evidence_id),
                    FOREIGN KEY(optimization_id) REFERENCES optimization_results(optimization_id) ON DELETE CASCADE
                )
                """
            )

            # 5. optimization_sensitivities
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS optimization_sensitivities (
                    sensitivity_id          TEXT NOT NULL,
                    optimization_id         TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    parameter               TEXT NOT NULL,
                    baseline_value          REAL NOT NULL,
                    changed_value           REAL NOT NULL,
                    objective_delta         REAL NOT NULL,
                    feasibility_maintained  INTEGER NOT NULL,
                    payload_json            TEXT NOT NULL,
                    PRIMARY KEY (optimization_id, sensitivity_id),
                    FOREIGN KEY(optimization_id) REFERENCES optimization_results(optimization_id) ON DELETE CASCADE
                )
                """
            )

            # Indexes
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_results_tenant ON optimization_results (tenant_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_results_workspace ON optimization_results (tenant_id, workspace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_results_plant ON optimization_results (tenant_id, plant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_results_fingerprint ON optimization_results (tenant_id, input_fingerprint)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_candidates_rank ON optimization_candidates (optimization_id, rank ASC)"
            )
            conn.commit()

    def save(self, result: OptimizationResult) -> OptimizationResult:
        """
        Idempotently persists an optimization problem, result, candidates, evidence, and sensitivities.
        If a matching input fingerprint exists for the tenant, returns the existing record.
        """
        with self._lock:
            existing = self.get_by_fingerprint(result.input_fingerprint, result.tenant_id)
            if existing:
                return existing

            prob = result.problem
            prob_payload = json.dumps(prob.model_dump(), default=str)
            result_payload = json.dumps(result.model_dump(), default=str)

            with self._get_connection() as conn:
                # 1. Insert problem
                conn.execute(
                    """
                    INSERT OR REPLACE INTO optimization_problems (
                        problem_id, tenant_id, workspace_id, plant_id,
                        name, decision_scope, method, multi_objective_method,
                        assessment_timestamp, horizon, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prob.problem_id,
                        prob.tenant_id,
                        prob.workspace_id,
                        prob.plant_id,
                        prob.name,
                        prob.decision_scope.value,
                        prob.method.value,
                        prob.multi_objective_method.value,
                        prob.assessment_timestamp,
                        prob.horizon,
                        prob_payload,
                        prob.created_at,
                    ),
                )

                # 2. Insert result
                conn.execute(
                    """
                    INSERT OR REPLACE INTO optimization_results (
                        optimization_id, problem_id, tenant_id, workspace_id, plant_id,
                        problem_name, assessment_timestamp, optimality_status, confidence, is_feasible,
                        candidate_count, variable_count, objective_count, constraint_count,
                        input_fingerprint, method, method_version, schema_version,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.optimization_id,
                        prob.problem_id,
                        result.tenant_id,
                        result.workspace_id,
                        result.plant_id,
                        prob.name,
                        prob.assessment_timestamp,
                        result.optimality_status.value,
                        result.confidence.value,
                        1 if result.feasibility.is_feasible else 0,
                        len(result.candidates),
                        len(prob.variables),
                        len(prob.objectives),
                        len(prob.constraints),
                        result.input_fingerprint,
                        prob.method.value,
                        prob.method_version,
                        _SCHEMA_VERSION,
                        result_payload,
                        result.created_at,
                    ),
                )

                # 3. Insert candidates
                for cand in result.candidates:
                    cand_payload = json.dumps(cand.model_dump(), default=str)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO optimization_candidates (
                            candidate_id, optimization_id, tenant_id, rank, score,
                            feasibility, is_recommended, decision_values_json,
                            objective_values_json, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cand.candidate_id,
                            result.optimization_id,
                            result.tenant_id,
                            cand.rank,
                            cand.score,
                            cand.feasibility.value,
                            1 if cand.is_recommended else 0,
                            json.dumps(cand.decision_values, default=str),
                            json.dumps(cand.objective_values, default=str),
                            cand_payload,
                        ),
                    )

                # 4. Insert evidence
                for ev in result.evidence:
                    ev_payload = json.dumps(ev.model_dump(), default=str)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO optimization_evidence (
                            evidence_id, optimization_id, tenant_id,
                            source_type, source_id, confidence, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ev.evidence_id,
                            result.optimization_id,
                            result.tenant_id,
                            ev.source_type,
                            ev.source_id,
                            ev.confidence.value,
                            ev_payload,
                        ),
                    )

                # 5. Insert sensitivities
                for idx, sens in enumerate(result.sensitivity_analysis):
                    sens_id = f"{result.optimization_id}_sens_{idx}_{sens.parameter}"
                    sens_payload = json.dumps(sens.model_dump(), default=str)
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO optimization_sensitivities (
                            sensitivity_id, optimization_id, tenant_id, parameter,
                            baseline_value, changed_value, objective_delta,
                            feasibility_maintained, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sens_id,
                            result.optimization_id,
                            result.tenant_id,
                            sens.parameter,
                            sens.baseline_value,
                            sens.changed_value,
                            sens.objective_delta,
                            1 if sens.feasibility_maintained else 0,
                            sens_payload,
                        ),
                    )

                conn.commit()

            return result

    def get_by_id(self, optimization_id: str, tenant_id: str) -> Optional[OptimizationResult]:
        """Retrieves an optimization result by ID strictly partitioned by tenant."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM optimization_results
                WHERE optimization_id = ? AND tenant_id = ?
                """,
                (optimization_id, tenant_id),
            ).fetchone()

            if not row:
                return None

            try:
                data = json.loads(row["payload_json"])
                return OptimizationResult.model_validate(data)
            except Exception:
                return None

    def get_by_fingerprint(self, fingerprint: str, tenant_id: str) -> Optional[OptimizationResult]:
        """Finds existing optimization result by fingerprint and tenant."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM optimization_results
                WHERE input_fingerprint = ? AND tenant_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (fingerprint, tenant_id),
            ).fetchone()

            if not row:
                return None

            try:
                data = json.loads(row["payload_json"])
                return OptimizationResult.model_validate(data)
            except Exception:
                return None

    def list_results(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[OptimizationResultSummary]:
        """Returns bounded list of optimization summaries isolated by tenant."""
        capped_limit = min(max(1, limit), _MAX_QUERY_LIMIT)

        query = """
            SELECT optimization_id, tenant_id, workspace_id, plant_id,
                   problem_name, assessment_timestamp, optimality_status,
                   confidence, is_feasible, candidate_count, variable_count,
                   objective_count, constraint_count, input_fingerprint, created_at
            FROM optimization_results
            WHERE tenant_id = ?
        """
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)

        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(capped_limit)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

            return [
                OptimizationResultSummary(
                    optimization_id=r["optimization_id"],
                    tenant_id=r["tenant_id"],
                    workspace_id=r["workspace_id"],
                    plant_id=r["plant_id"],
                    problem_name=r["problem_name"],
                    assessment_timestamp=r["assessment_timestamp"],
                    optimality_status=r["optimality_status"],
                    confidence=r["confidence"],
                    is_feasible=bool(r["is_feasible"]),
                    candidate_count=r["candidate_count"],
                    variable_count=r["variable_count"],
                    objective_count=r["objective_count"],
                    constraint_count=r["constraint_count"],
                    input_fingerprint=r["input_fingerprint"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def count_results(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
    ) -> int:
        """Returns total count of optimization records matching tenant/workspace/plant filter."""
        query = "SELECT COUNT(*) as cnt FROM optimization_results WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)

        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)

        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["cnt"]) if row else 0

    def get_candidates(self, optimization_id: str, tenant_id: str) -> List[OptimizationCandidate]:
        """Retrieves candidate solutions for an optimization run."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM optimization_candidates
                WHERE optimization_id = ? AND tenant_id = ?
                ORDER BY rank ASC
                """,
                (optimization_id, tenant_id),
            ).fetchall()

            candidates = []
            for r in rows:
                try:
                    candidates.append(OptimizationCandidate.model_validate(json.loads(r["payload_json"])))
                except Exception:
                    continue
            return candidates

    def get_evidence(self, optimization_id: str, tenant_id: str) -> List[OptimizationEvidence]:
        """Retrieves evidence items for an optimization run."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM optimization_evidence
                WHERE optimization_id = ? AND tenant_id = ?
                """,
                (optimization_id, tenant_id),
            ).fetchall()

            evidence_list = []
            for r in rows:
                try:
                    evidence_list.append(OptimizationEvidence.model_validate(json.loads(r["payload_json"])))
                except Exception:
                    continue
            return evidence_list

    def get_sensitivity(self, optimization_id: str, tenant_id: str) -> List[SensitivityResult]:
        """Retrieves sensitivity analysis for an optimization run."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM optimization_sensitivities
                WHERE optimization_id = ? AND tenant_id = ?
                """,
                (optimization_id, tenant_id),
            ).fetchall()

            results = []
            for r in rows:
                try:
                    results.append(SensitivityResult.model_validate(json.loads(r["payload_json"])))
                except Exception:
                    continue
            return results


# Global singleton instance
optimization_repository = OptimizationRepository()
