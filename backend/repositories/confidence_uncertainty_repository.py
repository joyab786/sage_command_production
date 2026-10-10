# backend/repositories/confidence_uncertainty_repository.py
"""
SageCommand V3 — Confidence and Uncertainty Intelligence Foundation Repository (Prompt 32)

Thread-safe, tenant-isolated SQLite WAL persistence for confidence assessments,
uncertainty decompositions, dimension breakdowns, and append-only audit ledger.
Adheres strictly to the invariant: NEVER mutates underlying source records.
"""

import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_CONFIDENCE_UNCERTAINTY_DB_PATH,
        SAGE_CONFIDENCE_MAX_ASSESSMENTS,
    )
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyResult,
        ConfidenceUncertaintySummary,
        ConfidenceAuditRecord,
        ConfidenceStatus,
        UncertaintyType,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_CONFIDENCE_UNCERTAINTY_DB_PATH,
        SAGE_CONFIDENCE_MAX_ASSESSMENTS,
    )
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceUncertaintyResult,
        ConfidenceUncertaintySummary,
        ConfidenceAuditRecord,
        ConfidenceStatus,
        UncertaintyType,
    )


class ConfidenceUncertaintyRepository:
    """
    Thread-safe SQLite WAL repository for Confidence & Uncertainty Intelligence.
    Ensures parameterized SQL queries, strict tenant isolation, deduplication by fingerprint,
    and immutable historical assessment snapshots.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_CONFIDENCE_UNCERTAINTY_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confidence_assessments (
                        assessment_id TEXT PRIMARY KEY,
                        target_type TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        plant_id TEXT,
                        aggregate_score REAL,
                        confidence_status TEXT NOT NULL,
                        predominant_uncertainty TEXT NOT NULL,
                        assessment_timestamp TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confidence_dimensions (
                        dimension_id TEXT PRIMARY KEY,
                        assessment_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        dimension_type TEXT NOT NULL,
                        score REAL,
                        weight REAL NOT NULL,
                        status TEXT NOT NULL,
                        explanation TEXT,
                        deficiencies_json TEXT,
                        FOREIGN KEY (assessment_id) REFERENCES confidence_assessments(assessment_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS uncertainty_components (
                        component_id TEXT PRIMARY KEY,
                        assessment_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        uncertainty_type TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        is_quantified INTEGER NOT NULL,
                        lower_bound REAL,
                        upper_bound REAL,
                        unit TEXT,
                        description TEXT,
                        FOREIGN KEY (assessment_id) REFERENCES confidence_assessments(assessment_id) ON DELETE CASCADE
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS confidence_audit_ledger (
                        audit_id TEXT PRIMARY KEY,
                        assessment_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        details_json TEXT NOT NULL
                    )
                """)

                # Indexes for fast scoped queries and deduplication
                conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_tenant_assessment ON confidence_assessments(tenant_id, assessment_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_tenant_target ON confidence_assessments(tenant_id, target_type, target_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_tenant_fingerprint ON confidence_assessments(tenant_id, fingerprint)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_dim_tenant ON confidence_dimensions(tenant_id, assessment_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_uncert_comp_tenant ON uncertainty_components(tenant_id, assessment_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_conf_audit_tenant ON confidence_audit_ledger(tenant_id, assessment_id)")

    def save_assessment(
        self,
        result: ConfidenceUncertaintyResult,
        actor_id: str = "system",
    ) -> ConfidenceUncertaintyResult:
        """
        Saves a ConfidenceUncertaintyResult in a thread-safe transaction.
        Deduplicates if the identical fingerprint already exists for this tenant.
        Appends an audit ledger event.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                # Check for existing identical fingerprint within tenant
                cur = conn.execute(
                    "SELECT assessment_id, payload_json FROM confidence_assessments WHERE tenant_id = ? AND fingerprint = ?",
                    (result.tenant_id, result.fingerprint),
                )
                row = cur.fetchone()
                if row:
                    # Deduplicated: append an audit event and return existing snapshot
                    audit_id = f"aud_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{result.assessment_id[:8]}"
                    conn.execute(
                        """
                        INSERT INTO confidence_audit_ledger
                        (audit_id, assessment_id, tenant_id, actor_id, action, timestamp, fingerprint, details_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            audit_id,
                            row["assessment_id"],
                            result.tenant_id,
                            actor_id,
                            "DEDUPLICATE_RETRIEVE",
                            now_iso,
                            result.fingerprint,
                            json.dumps({"deduplicated": True, "target_id": result.target_id}),
                        ),
                    )
                    return ConfidenceUncertaintyResult.model_validate_json(row["payload_json"])

                # Insert primary assessment record
                payload_json = result.model_dump_json()
                conn.execute(
                    """
                    INSERT INTO confidence_assessments
                    (assessment_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                     aggregate_score, confidence_status, predominant_uncertainty, assessment_timestamp,
                     fingerprint, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.assessment_id,
                        result.target_type,
                        result.target_id,
                        result.tenant_id,
                        result.workspace_id,
                        result.plant_id,
                        result.confidence.aggregate_score,
                        result.confidence.status.value,
                        result.uncertainty.decomposition.predominant_type.value,
                        result.assessment_timestamp,
                        result.fingerprint,
                        payload_json,
                        result.created_at or now_iso,
                    ),
                )

                # Insert dimension records for queryable analytics
                for dim in result.confidence.dimensions:
                    dim_id = f"dim_{result.assessment_id[:12]}_{dim.dimension_type.value}"
                    conn.execute(
                        """
                        INSERT INTO confidence_dimensions
                        (dimension_id, assessment_id, tenant_id, dimension_type, score, weight, status, explanation, deficiencies_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            dim_id,
                            result.assessment_id,
                            result.tenant_id,
                            dim.dimension_type.value,
                            dim.score,
                            dim.weight,
                            dim.status,
                            dim.explanation,
                            json.dumps(dim.deficiencies),
                        ),
                    )

                # Insert uncertainty component records
                for comp in (
                    result.uncertainty.decomposition.aleatoric_components
                    + result.uncertainty.decomposition.epistemic_components
                    + result.uncertainty.decomposition.other_components
                ):
                    low = comp.range_assessment.lower_bound if comp.range_assessment else None
                    high = comp.range_assessment.upper_bound if comp.range_assessment else None
                    unit = comp.range_assessment.unit if comp.range_assessment else None
                    conn.execute(
                        """
                        INSERT INTO uncertainty_components
                        (component_id, assessment_id, tenant_id, uncertainty_type, severity, is_quantified, lower_bound, upper_bound, unit, description)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"uc_{result.assessment_id[:10]}_{comp.component_id}",
                            result.assessment_id,
                            result.tenant_id,
                            comp.uncertainty_type.value,
                            comp.severity.value,
                            1 if comp.is_quantified else 0,
                            low,
                            high,
                            unit,
                            comp.description,
                        ),
                    )

                # Append audit record
                audit_id = f"aud_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}_{result.assessment_id[:8]}"
                conn.execute(
                    """
                    INSERT INTO confidence_audit_ledger
                    (audit_id, assessment_id, tenant_id, actor_id, action, timestamp, fingerprint, details_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        result.assessment_id,
                        result.tenant_id,
                        actor_id,
                        "CREATE_ASSESSMENT",
                        now_iso,
                        result.fingerprint,
                        json.dumps({
                            "target_type": result.target_type,
                            "target_id": result.target_id,
                            "confidence_status": result.confidence.status.value,
                        }),
                    ),
                )

        return result

    def get_by_id(self, assessment_id: str, tenant_id: str) -> Optional[ConfidenceUncertaintyResult]:
        """
        Retrieves an assessment by ID with strict tenant boundary enforcement.
        Returns None for inaccessible or non-existent IDs.
        """
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT payload_json FROM confidence_assessments WHERE assessment_id = ? AND tenant_id = ?",
                    (assessment_id, tenant_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return ConfidenceUncertaintyResult.model_validate_json(row["payload_json"])

    def get_by_fingerprint(self, fingerprint: str, tenant_id: str) -> Optional[ConfidenceUncertaintyResult]:
        """
        Retrieves an assessment by its cryptographic fingerprint within tenant scope.
        """
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT payload_json FROM confidence_assessments WHERE fingerprint = ? AND tenant_id = ?",
                    (fingerprint, tenant_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return ConfidenceUncertaintyResult.model_validate_json(row["payload_json"])

    def list_history(
        self,
        target_id: str,
        tenant_id: str,
        target_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[ConfidenceUncertaintySummary]:
        """
        Retrieves historical assessment summaries for a specific target entity within tenant scope.
        """
        query = """
            SELECT assessment_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                   aggregate_score, confidence_status, predominant_uncertainty, assessment_timestamp,
                   fingerprint, created_at
            FROM confidence_assessments
            WHERE tenant_id = ? AND target_id = ?
        """
        params: List[Any] = [tenant_id, target_id]
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(limit, SAGE_CONFIDENCE_MAX_ASSESSMENTS))

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(query, tuple(params))
                rows = cur.fetchall()

        summaries = []
        for r in rows:
            summaries.append(
                ConfidenceUncertaintySummary(
                    assessment_id=r["assessment_id"],
                    target_type=r["target_type"],
                    target_id=r["target_id"],
                    tenant_id=r["tenant_id"],
                    workspace_id=r["workspace_id"],
                    plant_id=r["plant_id"],
                    aggregate_confidence=r["aggregate_score"],
                    confidence_status=ConfidenceStatus(r["confidence_status"]),
                    predominant_uncertainty=UncertaintyType(r["predominant_uncertainty"]),
                    assessment_timestamp=r["assessment_timestamp"],
                    fingerprint=r["fingerprint"],
                    created_at=r["created_at"],
                )
            )
        return summaries

    def list_assessments(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        target_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ConfidenceUncertaintySummary]:
        """
        Paginated listing of assessments in tenant scope.
        """
        query = """
            SELECT assessment_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                   aggregate_score, confidence_status, predominant_uncertainty, assessment_timestamp,
                   fingerprint, created_at
            FROM confidence_assessments
            WHERE tenant_id = ?
        """
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([min(limit, SAGE_CONFIDENCE_MAX_ASSESSMENTS), max(0, offset)])

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(query, tuple(params))
                rows = cur.fetchall()

        summaries = []
        for r in rows:
            summaries.append(
                ConfidenceUncertaintySummary(
                    assessment_id=r["assessment_id"],
                    target_type=r["target_type"],
                    target_id=r["target_id"],
                    tenant_id=r["tenant_id"],
                    workspace_id=r["workspace_id"],
                    plant_id=r["plant_id"],
                    aggregate_confidence=r["aggregate_score"],
                    confidence_status=ConfidenceStatus(r["confidence_status"]),
                    predominant_uncertainty=UncertaintyType(r["predominant_uncertainty"]),
                    assessment_timestamp=r["assessment_timestamp"],
                    fingerprint=r["fingerprint"],
                    created_at=r["created_at"],
                )
            )
        return summaries

    def count_assessments(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> int:
        """
        Count matching assessments for pagination.
        """
        query = "SELECT COUNT(*) as cnt FROM confidence_assessments WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(query, tuple(params))
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0

    def get_audit_trail(self, assessment_id: str, tenant_id: str) -> List[ConfidenceAuditRecord]:
        """
        Retrieves the append-only audit trail for an assessment.
        """
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """
                    SELECT audit_id, assessment_id, tenant_id, actor_id, action, timestamp, fingerprint, details_json
                    FROM confidence_audit_ledger
                    WHERE assessment_id = ? AND tenant_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (assessment_id, tenant_id),
                )
                rows = cur.fetchall()

        records = []
        for r in rows:
            records.append(
                ConfidenceAuditRecord(
                    audit_id=r["audit_id"],
                    assessment_id=r["assessment_id"],
                    tenant_id=r["tenant_id"],
                    actor_id=r["actor_id"],
                    action=r["action"],
                    timestamp=r["timestamp"],
                    fingerprint=r["fingerprint"],
                    details=json.loads(r["details_json"]),
                )
            )
        return records


# Singleton repository instance
confidence_uncertainty_repository = ConfidenceUncertaintyRepository()
