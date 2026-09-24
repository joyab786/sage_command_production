"""
backend/services/financial_impact_repository.py

SageCommand V3 — Financial Impact Intelligence Repository (Prompt 25)

SQLite WAL-backed persistence for Financial Impact Assessments.
Follows established V3 repository patterns: tenant isolation, workspace
isolation, plant isolation, parameterized SQL, bounded queries, deterministic
fingerprint lookup, WAL mode, and schema versioning.

ANALYTICAL ONLY. No financial transactions are executed or mutated here.
"""

import json
import sqlite3
from typing import List, Optional

try:
    from core.config import SAGE_FINANCIAL_IMPACT_DB_PATH
    from data.schemas.financial_impact_contract import (
        FinancialImpactAssessment,
        FinancialImpactSummaryItem,
        FinancialConfidence,
        CurrencyAggregationStatus,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_FINANCIAL_IMPACT_DB_PATH
    from backend.data.schemas.financial_impact_contract import (
        FinancialImpactAssessment,
        FinancialImpactSummaryItem,
        FinancialConfidence,
        CurrencyAggregationStatus,
    )


_SCHEMA_VERSION = "1.0"


class FinancialImpactRepository:
    """
    SQLite-backed repository for Financial Impact Assessments.

    Design invariants:
    - WAL journal mode for read concurrency.
    - All queries parameterized (no string concatenation).
    - Tenant isolation enforced at every query.
    - Workspace isolation enforced when workspace_id provided.
    - Plant isolation enforced when plant_id provided.
    - Bounded query results (limit cap).
    - Deterministic fingerprint deduplication.
    """

    def __init__(self, db_path: str = SAGE_FINANCIAL_IMPACT_DB_PATH) -> None:
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
                CREATE TABLE IF NOT EXISTS financial_impact_assessments (
                    assessment_id       TEXT PRIMARY KEY,
                    tenant_id           TEXT NOT NULL,
                    workspace_id        TEXT,
                    plant_id            TEXT,
                    customer_id         TEXT,
                    supplier_id         TEXT,
                    asset_id            TEXT,
                    service_id          TEXT,
                    assessment_timestamp TEXT NOT NULL,
                    scenario_name       TEXT NOT NULL,
                    confidence          TEXT NOT NULL,
                    aggregation_status  TEXT NOT NULL,
                    total_amount        REAL,
                    total_currency      TEXT,
                    input_fingerprint   TEXT NOT NULL,
                    schema_version      TEXT NOT NULL DEFAULT '1.0',
                    payload_json        TEXT NOT NULL
                )
                """
            )
            # Indexes for efficient tenant-scoped queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_tenant "
                "ON financial_impact_assessments(tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_tenant_workspace "
                "ON financial_impact_assessments(tenant_id, workspace_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_tenant_customer "
                "ON financial_impact_assessments(tenant_id, customer_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_tenant_supplier "
                "ON financial_impact_assessments(tenant_id, supplier_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_tenant_asset "
                "ON financial_impact_assessments(tenant_id, asset_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_fingerprint "
                "ON financial_impact_assessments(input_fingerprint, tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fi_timestamp "
                "ON financial_impact_assessments(assessment_timestamp DESC)"
            )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_assessment(
        self, assessment: FinancialImpactAssessment
    ) -> FinancialImpactAssessment:
        """
        Persist an assessment. If an identical fingerprint already exists for
        the same tenant, return the cached record (idempotent / deterministic).
        """
        with self._get_connection() as conn:
            # Fingerprint deduplication
            cursor = conn.execute(
                "SELECT payload_json FROM financial_impact_assessments "
                "WHERE input_fingerprint = ? AND tenant_id = ?",
                (assessment.input_fingerprint, assessment.tenant_id),
            )
            existing = cursor.fetchone()
            if existing:
                return FinancialImpactAssessment.model_validate_json(
                    existing["payload_json"]
                )

            total_amount: Optional[float] = None
            total_currency: Optional[str] = None
            if assessment.total_exposure.is_monetary:
                total_amount = assessment.total_exposure.amount
                total_currency = assessment.total_exposure.currency

            conn.execute(
                """
                INSERT INTO financial_impact_assessments
                (assessment_id, tenant_id, workspace_id, plant_id,
                 customer_id, supplier_id, asset_id, service_id,
                 assessment_timestamp, scenario_name, confidence,
                 aggregation_status, total_amount, total_currency,
                 input_fingerprint, schema_version, payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    assessment.assessment_id,
                    assessment.tenant_id,
                    assessment.workspace_id,
                    assessment.plant_id,
                    assessment.customer_id,
                    assessment.supplier_id,
                    assessment.asset_id,
                    assessment.service_id,
                    assessment.assessment_timestamp,
                    assessment.scenario.scenario_name.value,
                    assessment.confidence.value,
                    assessment.aggregation_status.value,
                    total_amount,
                    total_currency,
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
    ) -> Optional[FinancialImpactAssessment]:
        """Retrieve a single assessment by ID, enforcing tenant/workspace/plant isolation."""
        with self._get_connection() as conn:
            query = (
                "SELECT payload_json FROM financial_impact_assessments "
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
                return FinancialImpactAssessment.model_validate_json(
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
        customer_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[FinancialImpactAssessment]:
        """
        List assessments with full tenant/workspace/plant isolation.
        Limit is capped at 200 to prevent unbounded queries.
        """
        limit = min(limit, 200)
        with self._get_connection() as conn:
            query = (
                "SELECT payload_json FROM financial_impact_assessments "
                "WHERE tenant_id = ?"
            )
            params: list = [tenant_id]
            if workspace_id is not None:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id is not None:
                query += " AND plant_id = ?"
                params.append(plant_id)
            if customer_id is not None:
                query += " AND customer_id = ?"
                params.append(customer_id)
            if supplier_id is not None:
                query += " AND supplier_id = ?"
                params.append(supplier_id)
            if asset_id is not None:
                query += " AND asset_id = ?"
                params.append(asset_id)

            query += " ORDER BY assessment_timestamp DESC LIMIT ?"
            params.append(limit)

            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [
            FinancialImpactAssessment.model_validate_json(r["payload_json"])
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
    ) -> List[FinancialImpactSummaryItem]:
        """
        Return lightweight summary rows without full JSON payloads.
        """
        limit = min(limit, 200)
        with self._get_connection() as conn:
            query = (
                "SELECT assessment_id, tenant_id, workspace_id, "
                "customer_id, supplier_id, asset_id, assessment_timestamp, "
                "scenario_name, confidence, aggregation_status, "
                "total_amount, total_currency, input_fingerprint "
                "FROM financial_impact_assessments WHERE tenant_id = ?"
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
            result.append(
                FinancialImpactSummaryItem(
                    assessment_id=r["assessment_id"],
                    tenant_id=r["tenant_id"],
                    workspace_id=r["workspace_id"],
                    customer_id=r["customer_id"],
                    supplier_id=r["supplier_id"],
                    asset_id=r["asset_id"],
                    assessment_timestamp=r["assessment_timestamp"],
                    scenario_name=r["scenario_name"],
                    confidence=FinancialConfidence(r["confidence"]),
                    aggregation_status=CurrencyAggregationStatus(
                        r["aggregation_status"]
                    ),
                    total_amount=r["total_amount"],
                    total_currency=r["total_currency"],
                    input_fingerprint=r["input_fingerprint"],
                )
            )
        return result

    # ------------------------------------------------------------------
    # Fingerprint lookup
    # ------------------------------------------------------------------

    def find_by_fingerprint(
        self, fingerprint: str, tenant_id: str
    ) -> Optional[FinancialImpactAssessment]:
        """Look up a prior assessment by deterministic fingerprint."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT payload_json FROM financial_impact_assessments "
                "WHERE input_fingerprint = ? AND tenant_id = ?",
                (fingerprint, tenant_id),
            )
            row = cursor.fetchone()
            if row:
                return FinancialImpactAssessment.model_validate_json(
                    row["payload_json"]
                )
        return None


# Module-level singleton (follows pattern of all other V3 repositories)
financial_impact_repository = FinancialImpactRepository()
