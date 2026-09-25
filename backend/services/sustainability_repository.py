"""
backend/services/sustainability_repository.py

SageCommand V3 — Sustainability Intelligence Repository (Prompt 26)

SQLite WAL-backed persistence for Sustainability Assessments.
Follows established V3 repository patterns: tenant isolation, workspace
isolation, plant isolation, parameterized SQL, bounded queries, deterministic
fingerprint lookup, WAL mode, and schema versioning.

ANALYTICAL ONLY. No operational, financial, environmental-control, procurement,
regulatory-filing, or physical systems are mutated here.

Sustainability Intelligence is an analytical system. It does not directly
control physical systems, execute remediation, purchase offsets, submit
regulatory filings, or mutate operational/financial records.
"""

import json
import sqlite3
from typing import List, Optional

try:
    from core.config import SAGE_SUSTAINABILITY_DB_PATH
    from data.schemas.sustainability_contract import (
        SustainabilityAssessment,
        SustainabilityConfidence,
        SustainabilityRiskLevel,
        SustainabilitySummaryItem,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_SUSTAINABILITY_DB_PATH
    from backend.data.schemas.sustainability_contract import (
        SustainabilityAssessment,
        SustainabilityConfidence,
        SustainabilityRiskLevel,
        SustainabilitySummaryItem,
    )


_SCHEMA_VERSION = "1.0"


class SustainabilityRepository:
    """
    SQLite-backed repository for Sustainability Assessments.

    Design invariants:
    - WAL journal mode for read concurrency.
    - All queries parameterized (no string concatenation).
    - Tenant isolation enforced at every query.
    - Workspace isolation enforced when workspace_id provided.
    - Plant isolation enforced when plant_id provided.
    - Bounded query results (limit cap at 200).
    - Deterministic fingerprint deduplication.
    """

    def __init__(self, db_path: str = SAGE_SUSTAINABILITY_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sustainability_assessments (
                    assessment_id           TEXT PRIMARY KEY,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT,
                    plant_id                TEXT,
                    asset_id                TEXT,
                    supplier_id             TEXT,
                    customer_id             TEXT,
                    process_id              TEXT,
                    assessment_timestamp    TEXT NOT NULL,
                    scenario_name           TEXT NOT NULL,
                    confidence              TEXT NOT NULL,
                    overall_risk_level      TEXT NOT NULL DEFAULT 'UNKNOWN',
                    dimensions_present      TEXT NOT NULL DEFAULT '[]',
                    input_fingerprint       TEXT NOT NULL,
                    schema_version          TEXT NOT NULL DEFAULT '1.0',
                    payload_json            TEXT NOT NULL
                )
                """
            )
            # Indexes for efficient tenant-scoped queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_tenant "
                "ON sustainability_assessments(tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_tenant_workspace "
                "ON sustainability_assessments(tenant_id, workspace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_tenant_plant "
                "ON sustainability_assessments(tenant_id, plant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_tenant_asset "
                "ON sustainability_assessments(tenant_id, asset_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_tenant_supplier "
                "ON sustainability_assessments(tenant_id, supplier_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_fingerprint "
                "ON sustainability_assessments(input_fingerprint, tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sus_timestamp "
                "ON sustainability_assessments(assessment_timestamp DESC)"
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_assessment(
        self, assessment: SustainabilityAssessment
    ) -> SustainabilityAssessment:
        """
        Persist an assessment. If an identical fingerprint already exists for
        the same tenant, return the cached record (idempotent / deterministic).
        """
        with self._get_connection() as conn:
            # Fingerprint deduplication
            cursor = conn.execute(
                "SELECT payload_json FROM sustainability_assessments "
                "WHERE input_fingerprint = ? AND tenant_id = ?",
                (assessment.input_fingerprint, assessment.tenant_id),
            )
            existing = cursor.fetchone()
            if existing:
                return SustainabilityAssessment.model_validate_json(
                    existing["payload_json"]
                )

            # Derive overall risk level from risk_factors
            overall_risk_level = "UNKNOWN"
            if assessment.risk_factors:
                risk_order = [
                    "UNKNOWN", "MINIMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"
                ]
                max_risk = max(
                    assessment.risk_factors,
                    key=lambda r: risk_order.index(r.risk_level.value)
                    if r.risk_level.value in risk_order
                    else 0,
                )
                overall_risk_level = max_risk.risk_level.value

            # Derive dimensions present
            dimensions_present = json.dumps(
                sorted({f.dimension.value for f in assessment.factors if f.value.is_known})
            )

            conn.execute(
                """
                INSERT INTO sustainability_assessments
                (assessment_id, tenant_id, workspace_id, plant_id,
                 asset_id, supplier_id, customer_id, process_id,
                 assessment_timestamp, scenario_name, confidence,
                 overall_risk_level, dimensions_present,
                 input_fingerprint, schema_version, payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    assessment.assessment_id,
                    assessment.tenant_id,
                    assessment.workspace_id,
                    assessment.plant_id,
                    assessment.asset_id,
                    assessment.supplier_id,
                    assessment.customer_id,
                    assessment.process_id,
                    assessment.assessment_timestamp,
                    assessment.scenario.scenario_name.value,
                    assessment.confidence.value,
                    overall_risk_level,
                    dimensions_present,
                    assessment.input_fingerprint,
                    _SCHEMA_VERSION,
                    assessment.model_dump_json(),
                ),
            )
        return assessment

    # ------------------------------------------------------------------
    # Read — by ID
    # ------------------------------------------------------------------

    def get_assessment(
        self,
        assessment_id: str,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
    ) -> Optional[SustainabilityAssessment]:
        """Retrieve a single assessment by ID, enforcing tenant/workspace/plant isolation."""
        with self._get_connection() as conn:
            query = (
                "SELECT payload_json FROM sustainability_assessments "
                "WHERE assessment_id = ? AND tenant_id = ?"
            )
            params: list = [assessment_id, tenant_id]
            if workspace_id is not None:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id is not None:
                query += " AND plant_id = ?"
                params.append(plant_id)

            cursor = conn.execute(query, tuple(params))
            row = cursor.fetchone()
            if row:
                return SustainabilityAssessment.model_validate_json(
                    row["payload_json"]
                )
        return None

    # ------------------------------------------------------------------
    # Read — list (bounded)
    # ------------------------------------------------------------------

    def list_assessments(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[SustainabilityAssessment]:
        """
        List assessments with full tenant/workspace/plant isolation.
        Limit is capped at 200 to prevent unbounded queries.
        """
        limit = min(limit, 200)
        with self._get_connection() as conn:
            query = (
                "SELECT payload_json FROM sustainability_assessments "
                "WHERE tenant_id = ?"
            )
            params: list = [tenant_id]
            if workspace_id is not None:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id is not None:
                query += " AND plant_id = ?"
                params.append(plant_id)
            if asset_id is not None:
                query += " AND asset_id = ?"
                params.append(asset_id)
            if supplier_id is not None:
                query += " AND supplier_id = ?"
                params.append(supplier_id)
            if customer_id is not None:
                query += " AND customer_id = ?"
                params.append(customer_id)

            query += " ORDER BY assessment_timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [
            SustainabilityAssessment.model_validate_json(r["payload_json"])
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Read — summary list (lightweight)
    # ------------------------------------------------------------------

    def list_summary(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[SustainabilitySummaryItem]:
        """
        Return lightweight summary rows without full JSON payloads.
        """
        limit = min(limit, 200)
        with self._get_connection() as conn:
            query = (
                "SELECT assessment_id, tenant_id, workspace_id, plant_id, "
                "asset_id, assessment_timestamp, scenario_name, confidence, "
                "overall_risk_level, dimensions_present, input_fingerprint "
                "FROM sustainability_assessments WHERE tenant_id = ?"
            )
            params: list = [tenant_id]
            if workspace_id is not None:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id is not None:
                query += " AND plant_id = ?"
                params.append(plant_id)

            query += " ORDER BY assessment_timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()

        result = []
        for r in rows:
            try:
                dims = json.loads(r["dimensions_present"] or "[]")
            except (json.JSONDecodeError, TypeError):
                dims = []
            result.append(
                SustainabilitySummaryItem(
                    assessment_id=r["assessment_id"],
                    tenant_id=r["tenant_id"],
                    workspace_id=r["workspace_id"],
                    plant_id=r["plant_id"],
                    asset_id=r["asset_id"],
                    assessment_timestamp=r["assessment_timestamp"],
                    scenario_name=r["scenario_name"],
                    confidence=SustainabilityConfidence(r["confidence"]),
                    dimensions_present=dims,
                    risk_level=SustainabilityRiskLevel(r["overall_risk_level"]),
                    input_fingerprint=r["input_fingerprint"],
                )
            )
        return result

    # ------------------------------------------------------------------
    # Fingerprint lookup
    # ------------------------------------------------------------------

    def find_by_fingerprint(
        self, fingerprint: str, tenant_id: str
    ) -> Optional[SustainabilityAssessment]:
        """Look up a prior assessment by deterministic fingerprint."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT payload_json FROM sustainability_assessments "
                "WHERE input_fingerprint = ? AND tenant_id = ?",
                (fingerprint, tenant_id),
            )
            row = cursor.fetchone()
            if row:
                return SustainabilityAssessment.model_validate_json(
                    row["payload_json"]
                )
        return None


# Module-level singleton (follows pattern of all other V3 repositories)
sustainability_repository = SustainabilityRepository()
