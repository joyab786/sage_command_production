# backend/repositories/decision_engine_repository.py
"""
SageCommand V3 — Decision Engine Repository (Prompt 30)

SQLite WAL-backed persistence for Decision Evaluations, Alternatives, Evidence References,
and Append-Only Audit Records.

Invariants:
- WAL journal mode for high read concurrency.
- All SQL queries strictly parameterized (no string formatting/concatenation).
- Strict tenant isolation enforced on every query.
- Workspace and Plant isolation enforced when specified.
- Bounded query results (limit capped at 200).
- Concurrency-safe via thread locking.
- Foreign keys enabled.
- Deterministic fingerprint indexing for idempotent lookup.

ANALYTICAL DECISION SUPPORT ONLY.
Never executes operational actions or bypasses the human decision boundary.
"""

import json
import sqlite3
import threading
import hashlib
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

try:
    from core.config import SAGE_DECISION_ENGINE_DB_PATH, SAGE_DECISION_MAX_EVALUATIONS
    from data.schemas.decision_engine_contract import (
        DecisionEvaluation,
        DecisionAlternative,
        DecisionEvidenceReference,
        DecisionAuditRecord,
        DecisionRecommendation,
        DecisionOutcomeStatus,
        DecisionType,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_DECISION_ENGINE_DB_PATH, SAGE_DECISION_MAX_EVALUATIONS
    from backend.data.schemas.decision_engine_contract import (
        DecisionEvaluation,
        DecisionAlternative,
        DecisionEvidenceReference,
        DecisionAuditRecord,
        DecisionRecommendation,
        DecisionOutcomeStatus,
        DecisionType,
    )

_SCHEMA_VERSION = "1.0"
_MAX_QUERY_LIMIT = min(SAGE_DECISION_MAX_EVALUATIONS, 200)


class DecisionEngineRepository:
    """
    Thread-safe, tenant-isolated SQLite repository for Decision Engine Foundation.
    """

    def __init__(self, db_path: str = SAGE_DECISION_ENGINE_DB_PATH) -> None:
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

            # 1. decision_evaluations
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_evaluations (
                    decision_id             TEXT PRIMARY KEY,
                    problem_id              TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    decision_type           TEXT NOT NULL,
                    fingerprint             TEXT NOT NULL,
                    status                  TEXT NOT NULL,
                    recommended_option_id   TEXT,
                    assessment_timestamp    TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_tenant_created ON decision_evaluations (tenant_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_fingerprint ON decision_evaluations (fingerprint, tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_type ON decision_evaluations (decision_type, tenant_id)")

            # 2. decision_alternatives
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_alternatives (
                    alternative_id          TEXT PRIMARY KEY,
                    decision_id             TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    option_id               TEXT NOT NULL,
                    option_name             TEXT NOT NULL,
                    rank                    INTEGER NOT NULL,
                    composite_score         REAL NOT NULL,
                    is_feasible             INTEGER NOT NULL,
                    is_policy_compliant     INTEGER NOT NULL,
                    is_recommended          INTEGER NOT NULL,
                    payload_json            TEXT NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decision_evaluations(decision_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_alt_lookup ON decision_alternatives (decision_id, rank)")

            # 3. decision_evidence
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_evidence (
                    evidence_ref_id         TEXT PRIMARY KEY,
                    decision_id             TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    source_subsystem        TEXT NOT NULL,
                    source_record_id        TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    FOREIGN KEY (decision_id) REFERENCES decision_evaluations(decision_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_ev_lookup ON decision_evidence (decision_id, source_subsystem)")

            # 4. decision_audit_ledger
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_audit_ledger (
                    audit_id                TEXT PRIMARY KEY,
                    decision_id             TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    event_type              TEXT NOT NULL,
                    actor_id                TEXT NOT NULL,
                    timestamp               TEXT NOT NULL,
                    fingerprint             TEXT NOT NULL,
                    checksum                TEXT NOT NULL,
                    payload_json            TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dec_audit_lookup ON decision_audit_ledger (decision_id, timestamp DESC)")

            conn.commit()

    # -------------------------------------------------------------------------
    # WRITE OPERATIONS
    # -------------------------------------------------------------------------

    def save_evaluation(
        self,
        evaluation: DecisionEvaluation,
        actor_id: str = "system",
        event_type: str = "DECISION_EVALUATED",
    ) -> DecisionEvaluation:
        """
        Persists a complete DecisionEvaluation, its alternatives, evidence snapshots,
        and creates an immutable audit record in a single transaction.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        eval_payload = evaluation.model_dump(mode="json")
        payload_str = json.dumps(eval_payload, sort_keys=True)
        checksum = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
        import time
        import uuid
        audit_id = f"aud_{evaluation.decision_id}_{time.time_ns()}_{uuid.uuid4().hex[:8]}"

        audit_record = DecisionAuditRecord(
            audit_id=audit_id,
            decision_id=evaluation.decision_id,
            tenant_id=evaluation.tenant_id,
            workspace_id=evaluation.workspace_id,
            plant_id=evaluation.plant_id,
            event_type=event_type,
            actor_id=actor_id,
            timestamp=now_iso,
            fingerprint=evaluation.fingerprint,
            checksum=checksum,
            details={"status": evaluation.status.value, "recommended_option_id": evaluation.recommendation.recommended_option_id},
        )

        with self._lock, self._get_connection() as conn:
            # 1. Insert or replace decision evaluation
            conn.execute(
                """
                INSERT OR REPLACE INTO decision_evaluations (
                    decision_id, problem_id, tenant_id, workspace_id, plant_id,
                    decision_type, fingerprint, status, recommended_option_id,
                    assessment_timestamp, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.decision_id,
                    evaluation.problem_id,
                    evaluation.tenant_id,
                    evaluation.workspace_id,
                    evaluation.plant_id,
                    evaluation.decision_type.value if hasattr(evaluation.decision_type, "value") else str(evaluation.decision_type),
                    evaluation.fingerprint,
                    evaluation.status.value if hasattr(evaluation.status, "value") else str(evaluation.status),
                    evaluation.recommendation.recommended_option_id,
                    evaluation.assessment_timestamp,
                    payload_str,
                    now_iso,
                ),
            )

            # 2. Insert alternatives
            conn.execute("DELETE FROM decision_alternatives WHERE decision_id = ?", (evaluation.decision_id,))
            for alt in evaluation.recommendation.alternatives:
                alt_id = f"alt_{evaluation.decision_id}_{alt.option_id}"
                alt_json = json.dumps(alt.model_dump(mode="json"), sort_keys=True)
                conn.execute(
                    """
                    INSERT INTO decision_alternatives (
                        alternative_id, decision_id, tenant_id, option_id, option_name,
                        rank, composite_score, is_feasible, is_policy_compliant,
                        is_recommended, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alt_id,
                        evaluation.decision_id,
                        evaluation.tenant_id,
                        alt.option_id,
                        alt.option_name,
                        alt.rank,
                        alt.composite_score,
                        1 if alt.is_feasible else 0,
                        1 if alt.is_policy_compliant else 0,
                        1 if alt.is_recommended else 0,
                        alt_json,
                    ),
                )

            # 3. Insert evidence references
            conn.execute("DELETE FROM decision_evidence WHERE decision_id = ?", (evaluation.decision_id,))
            for ev in evaluation.evidence_snapshot:
                ev_id = f"ev_{evaluation.decision_id}_{ev.evidence_id}"
                ev_json = json.dumps(ev.model_dump(mode="json"), sort_keys=True)
                conn.execute(
                    """
                    INSERT INTO decision_evidence (
                        evidence_ref_id, decision_id, tenant_id, source_subsystem,
                        source_record_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        evaluation.decision_id,
                        evaluation.tenant_id,
                        ev.source_subsystem,
                        ev.source_record_id,
                        ev_json,
                    ),
                )

            # 4. Insert audit ledger entry
            conn.execute(
                """
                INSERT INTO decision_audit_ledger (
                    audit_id, decision_id, tenant_id, workspace_id, plant_id,
                    event_type, actor_id, timestamp, fingerprint, checksum, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_record.audit_id,
                    audit_record.decision_id,
                    audit_record.tenant_id,
                    audit_record.workspace_id,
                    audit_record.plant_id,
                    audit_record.event_type,
                    audit_record.actor_id,
                    audit_record.timestamp,
                    audit_record.fingerprint,
                    audit_record.checksum,
                    json.dumps(audit_record.model_dump(mode="json"), sort_keys=True),
                ),
            )

            conn.commit()

        return evaluation

    # -------------------------------------------------------------------------
    # READ OPERATIONS
    # -------------------------------------------------------------------------

    def get_by_id(
        self,
        decision_id: str,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
    ) -> Optional[DecisionEvaluation]:
        """Retrieves a single DecisionEvaluation enforcing tenant, workspace, and plant isolation."""
        query = "SELECT payload_json FROM decision_evaluations WHERE decision_id = ? AND tenant_id = ?"
        params: List[Any] = [decision_id, tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)

        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return DecisionEvaluation.model_validate(data)

    def get_by_fingerprint(self, fingerprint: str, tenant_id: str) -> Optional[DecisionEvaluation]:
        """Finds existing evaluation by canonical fingerprint for idempotent caching/deduplication."""
        query = "SELECT payload_json FROM decision_evaluations WHERE fingerprint = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT 1"
        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, (fingerprint, tenant_id)).fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return DecisionEvaluation.model_validate(data)

    def list_evaluations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        decision_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[DecisionEvaluation]:
        """Lists evaluations with tenant isolation, optional filtering, and bound capping."""
        bounded_limit = max(1, min(limit, _MAX_QUERY_LIMIT))
        bounded_offset = max(0, offset)

        query = "SELECT payload_json FROM decision_evaluations WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)
        if decision_type:
            query += " AND decision_type = ?"
            params.append(decision_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([bounded_limit, bounded_offset])

        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [DecisionEvaluation.model_validate(json.loads(r["payload_json"])) for r in rows]

    def count_evaluations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
    ) -> int:
        """Counts evaluations for a tenant scope."""
        query = "SELECT COUNT(*) as cnt FROM decision_evaluations WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)

        with self._lock, self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["cnt"]) if row else 0

    def get_alternatives(self, decision_id: str, tenant_id: str) -> List[DecisionAlternative]:
        """Retrieves alternatives for a decision evaluation ordered by rank."""
        query = """
            SELECT payload_json FROM decision_alternatives
            WHERE decision_id = ? AND tenant_id = ?
            ORDER BY rank ASC
        """
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, (decision_id, tenant_id)).fetchall()
            return [DecisionAlternative.model_validate(json.loads(r["payload_json"])) for r in rows]

    def get_evidence(self, decision_id: str, tenant_id: str) -> List[DecisionEvidenceReference]:
        """Retrieves evidence references associated with a decision evaluation."""
        query = """
            SELECT payload_json FROM decision_evidence
            WHERE decision_id = ? AND tenant_id = ?
        """
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, (decision_id, tenant_id)).fetchall()
            return [DecisionEvidenceReference.model_validate(json.loads(r["payload_json"])) for r in rows]

    def get_audit_history(self, decision_id: str, tenant_id: str) -> List[DecisionAuditRecord]:
        """Retrieves immutable audit history records for a decision evaluation."""
        query = """
            SELECT payload_json FROM decision_audit_ledger
            WHERE decision_id = ? AND tenant_id = ?
            ORDER BY timestamp DESC
        """
        with self._lock, self._get_connection() as conn:
            rows = conn.execute(query, (decision_id, tenant_id)).fetchall()
            return [DecisionAuditRecord.model_validate(json.loads(r["payload_json"])) for r in rows]


decision_engine_repository = DecisionEngineRepository()
