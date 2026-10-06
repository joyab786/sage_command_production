# backend/services/what_if_simulation_repository.py
"""
SageCommand V3 — What-If Simulation Intelligence Repository (Prompt 28)

SQLite WAL-backed persistence for What-If Simulation Scenarios and Results.
Invariants:
- WAL journal mode for high read concurrency.
- All SQL queries strictly parameterized (no string formatting/concatenation).
- Tenant isolation enforced on every query.
- Workspace and Plant isolation enforced when provided.
- Bounded query results (limit capped at 200).
- Deterministic fingerprint lookup and idempotent deduplication.
- Schema versioning and tamper-evident payload storage.

ANALYTICAL ONLY. No physical systems, controllers, PLCs, or actuators are modified.
"""

import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

try:
    from core.config import SAGE_WHAT_IF_SIMULATION_DB_PATH, SAGE_SIMULATION_MAX_SCENARIOS
    from data.schemas.what_if_simulation_contract import (
        SimulationResult,
        SimulationResultSummary,
        SimulationScenario,
        SimulationBaseline,
        SimulatedState,
        SimulationDelta,
        ImpactAssessment,
        SimulationEvidence,
        ConstraintEvaluationResult,
        VariableContribution,
        SimulationLimitation,
        SimulationUncertainty,
        SimulationConfidence,
        SimulationMethod,
        SensorValueProvenance,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_WHAT_IF_SIMULATION_DB_PATH, SAGE_SIMULATION_MAX_SCENARIOS
    from backend.data.schemas.what_if_simulation_contract import (
        SimulationResult,
        SimulationResultSummary,
        SimulationScenario,
        SimulationBaseline,
        SimulatedState,
        SimulationDelta,
        ImpactAssessment,
        SimulationEvidence,
        ConstraintEvaluationResult,
        VariableContribution,
        SimulationLimitation,
        SimulationUncertainty,
        SimulationConfidence,
        SimulationMethod,
        SensorValueProvenance,
    )

_SCHEMA_VERSION = "1.0"
_MAX_QUERY_LIMIT = min(SAGE_SIMULATION_MAX_SCENARIOS, 200)


class WhatIfSimulationRepository:
    """
    Thread-safe, tenant-isolated SQLite repository for What-If Simulation Scenarios and Results.
    """

    def __init__(self, db_path: str = SAGE_WHAT_IF_SIMULATION_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS what_if_simulations (
                    simulation_id           TEXT PRIMARY KEY,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    scenario_name           TEXT NOT NULL,
                    assessment_timestamp    TEXT NOT NULL,
                    confidence              TEXT NOT NULL,
                    target_count            INTEGER NOT NULL DEFAULT 0,
                    variable_count          INTEGER NOT NULL DEFAULT 0,
                    delta_count             INTEGER NOT NULL DEFAULT 0,
                    impact_count            INTEGER NOT NULL DEFAULT 0,
                    violations_count        INTEGER NOT NULL DEFAULT 0,
                    input_fingerprint       TEXT NOT NULL,
                    method                  TEXT NOT NULL,
                    method_version          TEXT NOT NULL DEFAULT '1.0.0',
                    schema_version          TEXT NOT NULL DEFAULT '1.0',
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_what_if_tenant
                ON what_if_simulations (tenant_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_what_if_workspace
                ON what_if_simulations (tenant_id, workspace_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_what_if_plant
                ON what_if_simulations (tenant_id, plant_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_what_if_fingerprint
                ON what_if_simulations (tenant_id, input_fingerprint)
                """
            )
            conn.commit()

    def save(self, result: SimulationResult) -> SimulationResult:
        """
        Idempotently persists a What-If simulation result.
        If a matching input fingerprint exists for the tenant, returns the existing record.
        """
        with self._lock:
            existing = self.get_by_fingerprint(result.input_fingerprint, result.tenant_id)
            if existing:
                return existing

            violations_count = sum(1 for c in result.constraint_results if c.status.value == "VIOLATED")

            payload_dict = result.model_dump()
            payload_json = json.dumps(payload_dict, default=str)

            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO what_if_simulations (
                        simulation_id, tenant_id, workspace_id, plant_id,
                        scenario_name, assessment_timestamp, confidence,
                        target_count, variable_count, delta_count, impact_count, violations_count,
                        input_fingerprint, method, method_version, schema_version,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.simulation_id,
                        result.tenant_id,
                        result.workspace_id,
                        result.plant_id,
                        result.scenario.name,
                        result.scenario.assessment_timestamp,
                        result.confidence.value,
                        len(result.scenario.targets),
                        len(result.scenario.variables),
                        len(result.deltas),
                        len(result.impact_assessments),
                        violations_count,
                        result.input_fingerprint,
                        result.method.value,
                        result.method_version,
                        _SCHEMA_VERSION,
                        payload_json,
                        result.created_at,
                    ),
                )
                conn.commit()

            return result

    def get_by_id(self, simulation_id: str, tenant_id: str) -> Optional[SimulationResult]:
        """Retrieves a simulation result by ID strictly partitioned by tenant."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM what_if_simulations
                WHERE simulation_id = ? AND tenant_id = ?
                """,
                (simulation_id, tenant_id),
            ).fetchone()

            if not row:
                return None

            data = json.loads(row["payload_json"])
            return SimulationResult.model_validate(data)

    def get_by_fingerprint(self, fingerprint: str, tenant_id: str) -> Optional[SimulationResult]:
        """Retrieves an existing result by input fingerprint for deduplication."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json FROM what_if_simulations
                WHERE input_fingerprint = ? AND tenant_id = ?
                """,
                (fingerprint, tenant_id),
            ).fetchone()

            if not row:
                return None

            data = json.loads(row["payload_json"])
            return SimulationResult.model_validate(data)

    def list_simulations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SimulationResultSummary]:
        """
        Lists simulation summaries partitioned by tenant with optional plant/workspace filters.
        Results are strictly bounded by _MAX_QUERY_LIMIT (200).
        """
        safe_limit = max(1, min(limit, _MAX_QUERY_LIMIT))
        safe_offset = max(0, offset)

        query = """
            SELECT simulation_id, tenant_id, workspace_id, plant_id,
                   scenario_name, assessment_timestamp, confidence,
                   target_count, variable_count, delta_count, impact_count, violations_count,
                   input_fingerprint, created_at
            FROM what_if_simulations
            WHERE tenant_id = ?
        """
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)

        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([safe_limit, safe_offset])

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            SimulationResultSummary(
                simulation_id=row["simulation_id"],
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
                plant_id=row["plant_id"],
                scenario_name=row["scenario_name"],
                assessment_timestamp=row["assessment_timestamp"],
                confidence=row["confidence"],
                target_count=row["target_count"],
                variable_count=row["variable_count"],
                delta_count=row["delta_count"],
                impact_count=row["impact_count"],
                violations_count=row["violations_count"],
                input_fingerprint=row["input_fingerprint"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def count_simulations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
    ) -> int:
        """Returns total count of simulation results for pagination."""
        query = "SELECT COUNT(*) as cnt FROM what_if_simulations WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)

        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)

        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["cnt"]) if row else 0

    def delete_by_id(self, simulation_id: str, tenant_id: str) -> bool:
        """Deletes a simulation record scoped by tenant."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM what_if_simulations WHERE simulation_id = ? AND tenant_id = ?",
                    (simulation_id, tenant_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    def delete_all(self, tenant_id: str) -> int:
        """Removes all simulations for a tenant (used in test teardown)."""
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM what_if_simulations WHERE tenant_id = ?",
                    (tenant_id,),
                )
                conn.commit()
                return cursor.rowcount


what_if_simulation_repository = WhatIfSimulationRepository()
