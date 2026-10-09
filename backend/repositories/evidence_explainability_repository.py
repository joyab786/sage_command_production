# backend/repositories/evidence_explainability_repository.py
"""
SageCommand V3 — Evidence and Explainability Repository (Prompt 31)

SQLite WAL-backed persistence for Evidence Explanations, Lineage Graphs,
Evidence Records, and Append-Only Audit Records.

Invariants:
- WAL journal mode for high read concurrency.
- All SQL queries strictly parameterized (no string formatting/concatenation).
- Strict tenant isolation enforced on every query.
- Workspace and Plant isolation enforced when specified.
- Bounded query results (limit capped at 200).
- Concurrency-safe via thread locking.
- Foreign keys enabled.
- Deterministic fingerprint indexing for idempotent lookup and deduplication.
- Never mutates underlying operational or source subsystem records.

ANALYTICAL EXPLAINABILITY AND EVIDENCE TRACING ONLY.
Notice: EXPLAINABILITY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED
"""

import json
import sqlite3
import threading
import hashlib
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

try:
    from core.config import SAGE_EVIDENCE_EXPLAINABILITY_DB_PATH, SAGE_EXPLAINABILITY_MAX_EXPLANATIONS
    from data.schemas.evidence_explainability_contract import (
        ExplanationResult,
        ExplanationSummary,
        EvidenceRecord,
        EvidenceLineageGraph,
        EvidenceLineageEdge,
        EvidenceAuditRecord,
        EvidenceValidationResult,
        EvidenceSourceType,
        EvidenceProvenance,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_EVIDENCE_EXPLAINABILITY_DB_PATH, SAGE_EXPLAINABILITY_MAX_EXPLANATIONS
    from backend.data.schemas.evidence_explainability_contract import (
        ExplanationResult,
        ExplanationSummary,
        EvidenceRecord,
        EvidenceLineageGraph,
        EvidenceLineageEdge,
        EvidenceAuditRecord,
        EvidenceValidationResult,
        EvidenceSourceType,
        EvidenceProvenance,
    )

_SCHEMA_VERSION = "1.0"
_MAX_QUERY_LIMIT = min(SAGE_EXPLAINABILITY_MAX_EXPLANATIONS, 200)


class EvidenceExplainabilityRepository:
    """
    Thread-safe, tenant-isolated SQLite repository for Evidence and Explainability Foundation.
    """

    def __init__(self, db_path: str = SAGE_EVIDENCE_EXPLAINABILITY_DB_PATH) -> None:
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

            # 1. evidence_explanations
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_explanations (
                    explanation_id              TEXT PRIMARY KEY,
                    target_type                 TEXT NOT NULL,
                    target_id                   TEXT NOT NULL,
                    tenant_id                   TEXT NOT NULL,
                    workspace_id                TEXT NOT NULL,
                    plant_id                    TEXT,
                    fingerprint                 TEXT NOT NULL,
                    assessment_timestamp        TEXT NOT NULL,
                    algorithm_version           TEXT NOT NULL,
                    contract_version            TEXT NOT NULL,
                    is_partial                  INTEGER NOT NULL DEFAULT 0,
                    summary                     TEXT NOT NULL,
                    supporting_evidence_count   INTEGER NOT NULL DEFAULT 0,
                    excluded_evidence_count     INTEGER NOT NULL DEFAULT 0,
                    payload_json                TEXT NOT NULL,
                    created_at                  TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ee_tenant_created ON evidence_explanations (tenant_id, created_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ee_fingerprint ON evidence_explanations (fingerprint, tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ee_target ON evidence_explanations (target_type, target_id, tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ee_plant ON evidence_explanations (plant_id, tenant_id)")

            # 2. evidence_records
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_records (
                    evidence_id             TEXT NOT NULL,
                    explanation_id          TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    source_type             TEXT NOT NULL,
                    source_record_id        TEXT NOT NULL,
                    provenance              TEXT NOT NULL,
                    validation_status       TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL,
                    PRIMARY KEY (evidence_id, explanation_id),
                    FOREIGN KEY (explanation_id) REFERENCES evidence_explanations (explanation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_er_explanation ON evidence_records (explanation_id, tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_er_source ON evidence_records (source_type, source_record_id, tenant_id)")

            # 3. evidence_lineage_edges
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_lineage_edges (
                    edge_id                 TEXT NOT NULL,
                    explanation_id          TEXT NOT NULL,
                    tenant_id               TEXT NOT NULL,
                    source_evidence_id      TEXT NOT NULL,
                    target_evidence_id      TEXT NOT NULL,
                    edge_type               TEXT NOT NULL,
                    payload_json            TEXT NOT NULL,
                    PRIMARY KEY (edge_id, explanation_id),
                    FOREIGN KEY (explanation_id) REFERENCES evidence_explanations (explanation_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ele_explanation ON evidence_lineage_edges (explanation_id, tenant_id)")

            # 4. evidence_audit_ledger
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_audit_ledger (
                    audit_id                TEXT PRIMARY KEY,
                    explanation_id          TEXT NOT NULL,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eal_explanation ON evidence_audit_ledger (explanation_id, tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_eal_tenant_ts ON evidence_audit_ledger (tenant_id, timestamp DESC)")

    def save_explanation(self, result: ExplanationResult, actor_id: str = "system") -> None:
        """
        Saves explanation, supporting evidence records, lineage edges, and append-only audit record in a single transaction.
        Thread-safe and concurrency-guarded.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now_iso = datetime.now(timezone.utc).isoformat()

                # 1. Check if explanation with identical fingerprint already exists for this tenant
                cursor.execute(
                    "SELECT explanation_id FROM evidence_explanations WHERE fingerprint = ? AND tenant_id = ?",
                    (result.fingerprint, result.tenant_id),
                )
                existing = cursor.fetchone()
                if existing:
                    # Idempotent write: update payload if needed or keep existing
                    return

                # 2. Insert into evidence_explanations
                target_type_str = result.target_type.value if hasattr(result.target_type, "value") else str(result.target_type)
                cursor.execute(
                    """
                    INSERT INTO evidence_explanations (
                        explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                        fingerprint, assessment_timestamp, algorithm_version, contract_version,
                        is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                        payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.explanation_id,
                        target_type_str,
                        result.target_id,
                        result.tenant_id,
                        result.workspace_id,
                        result.plant_id,
                        result.fingerprint,
                        result.assessment_timestamp,
                        result.algorithm_version,
                        result.contract_version,
                        1 if result.is_partial else 0,
                        result.summary,
                        len(result.supporting_evidence),
                        len(result.excluded_evidence),
                        json.dumps(result.model_dump(), separators=(",", ":")),
                        now_iso,
                    ),
                )

                # 3. Insert evidence records
                all_evidence = result.supporting_evidence + result.excluded_evidence
                # Build validation status map
                val_map = {v.evidence_id: v.status.value if hasattr(v.status, "value") else str(v.status) for v in result.validations}

                for ev in all_evidence:
                    ev_source_type = ev.source_type.value if hasattr(ev.source_type, "value") else str(ev.source_type)
                    ev_provenance = ev.provenance.value if hasattr(ev.provenance, "value") else str(ev.provenance)
                    status_str = val_map.get(ev.evidence_id, "VALID")
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO evidence_records (
                            evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                            source_type, source_record_id, provenance, validation_status,
                            payload_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ev.evidence_id,
                            result.explanation_id,
                            result.tenant_id,
                            result.workspace_id,
                            ev.plant_id or result.plant_id,
                            ev_source_type,
                            ev.source_record_id,
                            ev_provenance,
                            status_str,
                            json.dumps(ev.model_dump(), separators=(",", ":")),
                            now_iso,
                        ),
                    )

                # 4. Insert lineage edges if graph is present
                if result.lineage_graph and result.lineage_graph.edges:
                    for edge in result.lineage_graph.edges:
                        edge_type_str = edge.edge_type.value if hasattr(edge.edge_type, "value") else str(edge.edge_type)
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO evidence_lineage_edges (
                                edge_id, explanation_id, tenant_id, source_evidence_id, target_evidence_id,
                                edge_type, payload_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                edge.edge_id,
                                result.explanation_id,
                                result.tenant_id,
                                edge.source_evidence_id,
                                edge.target_evidence_id,
                                edge_type_str,
                                json.dumps(edge.model_dump(), separators=(",", ":")),
                            ),
                        )

                # 5. Insert audit ledger entry
                audit_raw = f"{result.explanation_id}:{result.fingerprint}:{actor_id}:{now_iso}"
                checksum = hashlib.sha256(audit_raw.encode("utf-8")).hexdigest()
                audit_id = f"aud_exp_{result.explanation_id[:16]}_{hashlib.sha256(now_iso.encode()).hexdigest()[:8]}"

                cursor.execute(
                    """
                    INSERT INTO evidence_audit_ledger (
                        audit_id, explanation_id, tenant_id, workspace_id, plant_id,
                        event_type, actor_id, timestamp, fingerprint, checksum, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        result.explanation_id,
                        result.tenant_id,
                        result.workspace_id,
                        result.plant_id,
                        "EXPLANATION_GENERATED",
                        actor_id,
                        now_iso,
                        result.fingerprint,
                        checksum,
                        json.dumps({
                            "target_type": target_type_str,
                            "target_id": result.target_id,
                            "supporting_count": len(result.supporting_evidence),
                            "excluded_count": len(result.excluded_evidence),
                            "is_partial": result.is_partial,
                        }, separators=(",", ":")),
                    ),
                )
                conn.commit()

    def get_by_id(self, explanation_id: str, tenant_id: str) -> Optional[ExplanationResult]:
        """
        Retrieves explanation by ID with strict tenant isolation.
        Returns None if not found or if tenant doesn't match.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json FROM evidence_explanations WHERE explanation_id = ? AND tenant_id = ?",
                (explanation_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return ExplanationResult.model_validate(data)

    def get_by_fingerprint(self, fingerprint: str, tenant_id: str) -> Optional[ExplanationResult]:
        """
        Retrieves explanation by input fingerprint with tenant isolation.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json FROM evidence_explanations WHERE fingerprint = ? AND tenant_id = ?",
                (fingerprint, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return ExplanationResult.model_validate(data)

    def list_explanations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        target_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ExplanationSummary]:
        """
        Lists explanation summaries with tenant isolation and optional filters.
        Bounded to max 200 items.
        """
        safe_limit = min(max(1, limit), _MAX_QUERY_LIMIT)
        query = "SELECT explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id, fingerprint, assessment_timestamp, is_partial, supporting_evidence_count, excluded_evidence_count, summary FROM evidence_explanations WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([safe_limit, max(0, offset)])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            summaries: List[ExplanationSummary] = []
            for r in rows:
                summaries.append(
                    ExplanationSummary(
                        explanation_id=r["explanation_id"],
                        target_type=EvidenceSourceType(r["target_type"]),
                        target_id=r["target_id"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        fingerprint=r["fingerprint"],
                        assessment_timestamp=r["assessment_timestamp"],
                        is_partial=bool(r["is_partial"]),
                        supporting_evidence_count=r["supporting_evidence_count"],
                        excluded_evidence_count=r["excluded_evidence_count"],
                        summary=r["summary"],
                    )
                )
            return summaries

    def count_explanations(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        target_type: Optional[str] = None,
    ) -> int:
        """Returns total count of explanations matching filters for caller's tenant."""
        query = "SELECT COUNT(*) as total FROM evidence_explanations WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return row["total"] if row else 0

    def get_lineage(self, explanation_id: str, tenant_id: str) -> Optional[EvidenceLineageGraph]:
        """Retrieves lineage graph for explanation with tenant isolation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json FROM evidence_explanations WHERE explanation_id = ? AND tenant_id = ?",
                (explanation_id, tenant_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            graph_data = data.get("lineage_graph")
            if not graph_data:
                return None
            return EvidenceLineageGraph.model_validate(graph_data)

    def get_evidence(self, explanation_id: str, tenant_id: str) -> List[EvidenceRecord]:
        """Retrieves all evidence records for an explanation with tenant isolation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json FROM evidence_records WHERE explanation_id = ? AND tenant_id = ? ORDER BY evidence_id ASC",
                (explanation_id, tenant_id),
            )
            rows = cursor.fetchall()
            return [EvidenceRecord.model_validate(json.loads(r["payload_json"])) for r in rows]

    def get_audit_history(self, explanation_id: str, tenant_id: str) -> List[EvidenceAuditRecord]:
        """Retrieves audit trail for an explanation with tenant isolation."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT payload_json, audit_id, explanation_id, tenant_id, workspace_id, plant_id, event_type, actor_id, timestamp, fingerprint, checksum FROM evidence_audit_ledger WHERE explanation_id = ? AND tenant_id = ? ORDER BY timestamp ASC",
                (explanation_id, tenant_id),
            )
            rows = cursor.fetchall()
            records: List[EvidenceAuditRecord] = []
            for r in rows:
                details = json.loads(r["payload_json"]) if r["payload_json"] else {}
                records.append(
                    EvidenceAuditRecord(
                        audit_id=r["audit_id"],
                        explanation_id=r["explanation_id"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        event_type=r["event_type"],
                        actor_id=r["actor_id"],
                        timestamp=r["timestamp"],
                        fingerprint=r["fingerprint"],
                        checksum=r["checksum"],
                        details=details,
                    )
                )
            return records

    def log_audit_event(
        self,
        explanation_id: str,
        event_type: str,
        actor_id: str,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str],
        fingerprint: str,
        details: Dict[str, Any],
    ) -> None:
        """Appends an individual audit ledger record."""
        now_iso = datetime.now(timezone.utc).isoformat()
        audit_raw = f"{explanation_id}:{fingerprint}:{actor_id}:{now_iso}:{event_type}"
        checksum = hashlib.sha256(audit_raw.encode("utf-8")).hexdigest()
        audit_id = f"aud_{event_type.lower()}_{explanation_id[:12]}_{checksum[:8]}"

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO evidence_audit_ledger (
                        audit_id, explanation_id, tenant_id, workspace_id, plant_id,
                        event_type, actor_id, timestamp, fingerprint, checksum, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        explanation_id,
                        tenant_id,
                        workspace_id,
                        plant_id,
                        event_type,
                        actor_id,
                        now_iso,
                        fingerprint,
                        checksum,
                        json.dumps(details, separators=(",", ":")),
                    ),
                )
                conn.commit()


# Singleton repository instance
evidence_explainability_repository = EvidenceExplainabilityRepository()
