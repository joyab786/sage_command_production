# backend/repositories/organizational_memory_repository.py
"""
SageCommand V3 — Governed Organizational Memory Foundation Repository (Prompt 34)

ADVISORY ORGANIZATIONAL MEMORY CONTEXT ONLY — NEVER EXECUTES ACTIONS, MUTATES EQUIPMENT,
OR BYPASSES OPERATIONAL GOVERNANCE.

Thread-safe, tenant-isolated SQLite WAL repository for governed organizational memory entries,
directed memory relationships, and an append-only audit ledger.
Ensures parameterized queries, zero SQL injection surface, strict tenant scoping,
and atomic transaction boundaries for all lifecycle mutations and audit records.

Cardinal Invariants:
1. Strict tenant partitioning on every operation (tenant_id in WHERE clauses and compound keys).
2. Atomic mutation: lifecycle transitions and mandatory audit records commit together or not at all.
3. Read-only queries never mutate memory entries or operational subsystems.
4. Superseded or archived entries are preserved; updates never silently overwrite history.
"""

import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime, timezone

try:
    from core.config import (
        SAGE_ORGANIZATIONAL_MEMORY_DB_PATH,
        SAGE_MEMORY_MAX_SEARCH_RESULTS,
        SAGE_MEMORY_DEFAULT_SEARCH_LIMIT,
    )
    from data.schemas.organizational_memory_contract import (
        OrganizationalMemoryEntry,
        MemoryType,
        EpistemicStatus,
        MemoryLifecycleStatus,
        VerificationStatus,
        RelationshipType,
        SourceReference,
        MemoryRelationship,
        MemorySearchRequest,
        MemoryAuditRecord,
    )
    from data.schemas.sop_rag_contract import ClassificationLevel
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceStatus,
        UncertaintyType,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_ORGANIZATIONAL_MEMORY_DB_PATH,
        SAGE_MEMORY_MAX_SEARCH_RESULTS,
        SAGE_MEMORY_DEFAULT_SEARCH_LIMIT,
    )
    from backend.data.schemas.organizational_memory_contract import (
        OrganizationalMemoryEntry,
        MemoryType,
        EpistemicStatus,
        MemoryLifecycleStatus,
        VerificationStatus,
        RelationshipType,
        SourceReference,
        MemoryRelationship,
        MemorySearchRequest,
        MemoryAuditRecord,
    )
    from backend.data.schemas.sop_rag_contract import ClassificationLevel
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceStatus,
        UncertaintyType,
    )


# Classification hierarchy ranking for clearance checks
CLASSIFICATION_HIERARCHY: Dict[ClassificationLevel, int] = {
    ClassificationLevel.PUBLIC: 1,
    ClassificationLevel.INTERNAL: 2,
    ClassificationLevel.CONFIDENTIAL: 3,
    ClassificationLevel.RESTRICTED: 4,
}


class OrganizationalMemoryRepository:
    """
    Thread-safe SQLite WAL repository for Organizational Memory persistence.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_ORGANIZATIONAL_MEMORY_DB_PATH
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
                    CREATE TABLE IF NOT EXISTS organizational_memory_entries (
                        memory_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        plant_id TEXT NOT NULL,
                        asset_id TEXT,
                        process_id TEXT,
                        session_id TEXT,
                        classification TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        epistemic_status TEXT NOT NULL,
                        lifecycle_status TEXT NOT NULL,
                        verification_status TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags_json TEXT NOT NULL,
                        source_references_json TEXT NOT NULL,
                        evidence_references_json TEXT NOT NULL,
                        decision_reference TEXT,
                        incident_reference TEXT,
                        rca_reference TEXT,
                        sop_reference TEXT,
                        relationships_json TEXT NOT NULL,
                        supersedes_memory_id TEXT,
                        superseded_by_memory_id TEXT,
                        revision INTEGER NOT NULL DEFAULT 1,
                        confidence_status TEXT NOT NULL,
                        uncertainty_types_json TEXT NOT NULL,
                        uncertainty_notes TEXT,
                        retention_policy TEXT NOT NULL,
                        is_hold INTEGER NOT NULL DEFAULT 0,
                        hold_reason TEXT,
                        event_timestamp TEXT,
                        valid_from TEXT,
                        valid_until TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        verified_at TEXT,
                        superseded_at TEXT,
                        archived_at TEXT,
                        created_by TEXT NOT NULL,
                        verified_by TEXT,
                        superseded_by TEXT,
                        archived_by TEXT,
                        metadata_json TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, memory_id)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS organizational_memory_audit_ledger (
                        audit_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        plant_id TEXT NOT NULL,
                        memory_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        details_json TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS organizational_memory_relationships (
                        tenant_id TEXT NOT NULL,
                        source_memory_id TEXT NOT NULL,
                        target_memory_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, source_memory_id, target_memory_id, relationship_type)
                    )
                """)

                # Performance and isolation indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_type ON organizational_memory_entries (tenant_id, memory_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_status ON organizational_memory_entries (tenant_id, lifecycle_status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_plant ON organizational_memory_entries (tenant_id, plant_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_asset ON organizational_memory_entries (tenant_id, asset_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_incident ON organizational_memory_entries (tenant_id, incident_reference)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_decision ON organizational_memory_entries (tenant_id, decision_reference)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_audit_tenant_mem ON organizational_memory_audit_ledger (tenant_id, memory_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_rel_target ON organizational_memory_relationships (tenant_id, target_memory_id)")

    # -------------------------------------------------------------------------
    # Helper: Serialize / Deserialize
    # -------------------------------------------------------------------------

    def _entry_to_row(self, entry: OrganizationalMemoryEntry) -> Tuple:
        return (
            entry.memory_id,
            entry.tenant_id,
            entry.workspace_id,
            entry.plant_id,
            entry.asset_id,
            entry.process_id,
            entry.session_id,
            entry.classification.value,
            entry.memory_type.value,
            entry.epistemic_status.value,
            entry.lifecycle_status.value,
            entry.verification_status.value,
            entry.title,
            entry.summary,
            entry.content,
            json.dumps(entry.tags),
            json.dumps([r.model_dump(mode="json") for r in entry.source_references]),
            json.dumps(entry.evidence_references),
            entry.decision_reference,
            entry.incident_reference,
            entry.rca_reference,
            entry.sop_reference,
            json.dumps([rel.model_dump(mode="json") for rel in entry.relationships]),
            entry.supersedes_memory_id,
            entry.superseded_by_memory_id,
            entry.revision,
            entry.confidence_status.value,
            json.dumps([u.value for u in entry.uncertainty_types]),
            entry.uncertainty_notes,
            entry.retention_policy,
            1 if entry.is_hold else 0,
            entry.hold_reason,
            entry.event_timestamp.isoformat() if entry.event_timestamp else None,
            entry.valid_from.isoformat() if entry.valid_from else None,
            entry.valid_until.isoformat() if entry.valid_until else None,
            entry.created_at.isoformat(),
            entry.updated_at.isoformat(),
            entry.verified_at.isoformat() if entry.verified_at else None,
            entry.superseded_at.isoformat() if entry.superseded_at else None,
            entry.archived_at.isoformat() if entry.archived_at else None,
            entry.created_by,
            entry.verified_by,
            entry.superseded_by,
            entry.archived_by,
            json.dumps(entry.metadata),
        )

    def _row_to_entry(self, row: sqlite3.Row) -> OrganizationalMemoryEntry:
        source_refs_raw = json.loads(row["source_references_json"])
        source_refs = [SourceReference(**r) for r in source_refs_raw]

        rel_raw = json.loads(row["relationships_json"])
        relationships = [MemoryRelationship(**r) for r in rel_raw]

        unc_raw = json.loads(row["uncertainty_types_json"])
        uncertainty_types = [UncertaintyType(u) for u in unc_raw]

        return OrganizationalMemoryEntry(
            memory_id=row["memory_id"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            asset_id=row["asset_id"],
            process_id=row["process_id"],
            session_id=row["session_id"],
            classification=ClassificationLevel(row["classification"]),
            memory_type=MemoryType(row["memory_type"]),
            epistemic_status=EpistemicStatus(row["epistemic_status"]),
            lifecycle_status=MemoryLifecycleStatus(row["lifecycle_status"]),
            verification_status=VerificationStatus(row["verification_status"]),
            title=row["title"],
            summary=row["summary"],
            content=row["content"],
            tags=json.loads(row["tags_json"]),
            source_references=source_refs,
            evidence_references=json.loads(row["evidence_references_json"]),
            decision_reference=row["decision_reference"],
            incident_reference=row["incident_reference"],
            rca_reference=row["rca_reference"],
            sop_reference=row["sop_reference"],
            relationships=relationships,
            supersedes_memory_id=row["supersedes_memory_id"],
            superseded_by_memory_id=row["superseded_by_memory_id"],
            revision=row["revision"],
            confidence_status=ConfidenceStatus(row["confidence_status"]),
            uncertainty_types=uncertainty_types,
            uncertainty_notes=row["uncertainty_notes"],
            retention_policy=row["retention_policy"],
            is_hold=bool(row["is_hold"]),
            hold_reason=row["hold_reason"],
            event_timestamp=datetime.fromisoformat(row["event_timestamp"]) if row["event_timestamp"] else None,
            valid_from=datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
            valid_until=datetime.fromisoformat(row["valid_until"]) if row["valid_until"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            verified_at=datetime.fromisoformat(row["verified_at"]) if row["verified_at"] else None,
            superseded_at=datetime.fromisoformat(row["superseded_at"]) if row["superseded_at"] else None,
            archived_at=datetime.fromisoformat(row["archived_at"]) if row["archived_at"] else None,
            created_by=row["created_by"],
            verified_by=row["verified_by"],
            superseded_by=row["superseded_by"],
            archived_by=row["archived_by"],
            metadata=json.loads(row["metadata_json"]),
        )

    def _insert_audit_entry_conn(self, conn: sqlite3.Connection, audit: MemoryAuditRecord) -> None:
        conn.execute("""
            INSERT INTO organizational_memory_audit_ledger (
                audit_id, tenant_id, workspace_id, plant_id, memory_id,
                event_type, actor_id, timestamp, outcome, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit.audit_id,
            audit.tenant_id,
            audit.workspace_id,
            audit.plant_id,
            audit.memory_id,
            audit.event_type,
            audit.actor_id,
            audit.timestamp.isoformat(),
            audit.outcome,
            json.dumps(audit.details),
        ))

    # -------------------------------------------------------------------------
    # Mutations: Atomic creation & update
    # -------------------------------------------------------------------------

    def save_draft(
        self,
        entry: OrganizationalMemoryEntry,
        audit: MemoryAuditRecord,
    ) -> OrganizationalMemoryEntry:
        """
        Atomically saves a new draft organizational memory entry and records the creation audit log.
        Rolls back completely if either operation fails.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    row_data = self._entry_to_row(entry)
                    conn.execute("""
                        INSERT INTO organizational_memory_entries (
                            memory_id, tenant_id, workspace_id, plant_id, asset_id, process_id, session_id,
                            classification, memory_type, epistemic_status, lifecycle_status, verification_status,
                            title, summary, content, tags_json, source_references_json, evidence_references_json,
                            decision_reference, incident_reference, rca_reference, sop_reference, relationships_json,
                            supersedes_memory_id, superseded_by_memory_id, revision, confidence_status,
                            uncertainty_types_json, uncertainty_notes, retention_policy, is_hold, hold_reason,
                            event_timestamp, valid_from, valid_until, created_at, updated_at,
                            verified_at, superseded_at, archived_at, created_by, verified_by,
                            superseded_by, archived_by, metadata_json
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                    """, row_data)

                    self._insert_audit_entry_conn(conn, audit)
                return entry
            finally:
                conn.close()

    def update_draft_atomic(
        self,
        entry: OrganizationalMemoryEntry,
        audit: MemoryAuditRecord,
    ) -> bool:
        """
        Atomically updates an existing DRAFT memory entry and records an update audit log.
        Fails if the entry is not in DRAFT status or does not exist under tenant_id.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Verify currently in DRAFT status
                    cur = conn.execute(
                        "SELECT lifecycle_status FROM organizational_memory_entries WHERE tenant_id = ? AND memory_id = ?",
                        (entry.tenant_id, entry.memory_id),
                    )
                    row = cur.fetchone()
                    if not row or row["lifecycle_status"] != MemoryLifecycleStatus.DRAFT.value:
                        return False

                    row_data = self._entry_to_row(entry)
                    conn.execute("""
                        UPDATE organizational_memory_entries SET
                            workspace_id = ?, plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                            classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                            verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                            source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                            incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                            supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                            uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                            hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                            updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                            verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                        WHERE tenant_id = ? AND memory_id = ?
                    """, row_data[2:] + (entry.tenant_id, entry.memory_id))

                    self._insert_audit_entry_conn(conn, audit)
                return True
            finally:
                conn.close()

    def commit_lifecycle_mutation_atomic(
        self,
        entry: OrganizationalMemoryEntry,
        audit: MemoryAuditRecord,
        extra_entry_to_update: Optional[OrganizationalMemoryEntry] = None,
        extra_audit: Optional[MemoryAuditRecord] = None,
    ) -> bool:
        """
        Atomically applies a lifecycle status transition, optional related entry update
        (e.g., superseding an older record), and writes mandatory audit logs in one transaction.
        If any mutation or audit write fails, all changes are rolled back.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Update primary entry
                    row_data = self._entry_to_row(entry)
                    cursor = conn.execute("""
                        UPDATE organizational_memory_entries SET
                            workspace_id = ?, plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                            classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                            verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                            source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                            incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                            supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                            uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                            hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                            updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                            verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                        WHERE tenant_id = ? AND memory_id = ?
                    """, row_data[2:] + (entry.tenant_id, entry.memory_id))

                    if cursor.rowcount == 0:
                        return False

                    # Primary audit record
                    self._insert_audit_entry_conn(conn, audit)

                    # Extra entry update (e.g. older entry marked superseded)
                    if extra_entry_to_update:
                        extra_row = self._entry_to_row(extra_entry_to_update)
                        extra_cur = conn.execute("""
                            UPDATE organizational_memory_entries SET
                                workspace_id = ?, plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                                classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                                verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                                source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                                incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                                supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                                uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                                hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                                updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                                verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                            WHERE tenant_id = ? AND memory_id = ?
                        """, extra_row[2:] + (extra_entry_to_update.tenant_id, extra_entry_to_update.memory_id))
                        if extra_cur.rowcount == 0:
                            raise RuntimeError(f"Failed to update superseded entry {extra_entry_to_update.memory_id}")

                    # Extra audit record
                    if extra_audit:
                        self._insert_audit_entry_conn(conn, extra_audit)

                return True
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # Retrieval & Search
    # -------------------------------------------------------------------------

    def get_entry(self, tenant_id: str, memory_id: str) -> Optional[OrganizationalMemoryEntry]:
        """
        Retrieves a single memory entry strictly partitioned by tenant_id.
        """
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM organizational_memory_entries WHERE tenant_id = ? AND memory_id = ?",
                    (tenant_id, memory_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_entry(row)

    def search_entries(
        self,
        tenant_id: str,
        search_req: MemorySearchRequest,
        allowed_plant_ids: Optional[Set[str]] = None,
        max_classification: Optional[ClassificationLevel] = None,
    ) -> Tuple[List[OrganizationalMemoryEntry], int]:
        """
        Deterministic, bounded search query with strict server-side scoping:
        - tenant_id filtering
        - plant_id authorization filtering
        - classification ceiling filtering
        - optional metadata and lexical filters
        Returns (entries, total_matching_count).
        """
        clauses = ["tenant_id = ?"]
        params: List[Any] = [tenant_id]

        # Scope filters
        if search_req.plant_id:
            clauses.append("plant_id = ?")
            params.append(search_req.plant_id)
        elif allowed_plant_ids is not None:
            if not allowed_plant_ids:
                return [], 0
            placeholders = ",".join("?" for _ in allowed_plant_ids)
            clauses.append(f"plant_id IN ({placeholders})")
            params.extend(list(allowed_plant_ids))

        if search_req.asset_id:
            clauses.append("asset_id = ?")
            params.append(search_req.asset_id)

        if search_req.process_id:
            clauses.append("process_id = ?")
            params.append(search_req.process_id)

        if search_req.incident_reference:
            clauses.append("incident_reference = ?")
            params.append(search_req.incident_reference)

        if search_req.decision_reference:
            clauses.append("decision_reference = ?")
            params.append(search_req.decision_reference)

        # Domain & Lifecycle filters
        if search_req.memory_type:
            clauses.append("memory_type = ?")
            params.append(search_req.memory_type.value)

        if search_req.epistemic_status:
            clauses.append("epistemic_status = ?")
            params.append(search_req.epistemic_status.value)

        if search_req.lifecycle_status:
            clauses.append("lifecycle_status = ?")
            params.append(search_req.lifecycle_status.value)
        else:
            # By default, do not return superseded or archived unless requested
            status_exclusions = []
            if not search_req.include_superseded:
                status_exclusions.append(MemoryLifecycleStatus.SUPERSEDED.value)
            if not search_req.include_archived:
                status_exclusions.append(MemoryLifecycleStatus.ARCHIVED.value)
                status_exclusions.append(MemoryLifecycleStatus.REVOKED.value)
                status_exclusions.append(MemoryLifecycleStatus.REJECTED.value)
            if status_exclusions:
                placeholders = ",".join("?" for _ in status_exclusions)
                clauses.append(f"lifecycle_status NOT IN ({placeholders})")
                params.extend(status_exclusions)

        if search_req.verification_status:
            clauses.append("verification_status = ?")
            params.append(search_req.verification_status.value)

        # Temporal validity filter: valid_from <= valid_at <= valid_until
        if search_req.valid_at:
            valid_at_iso = search_req.valid_at.isoformat()
            clauses.append("(valid_from IS NULL OR valid_from <= ?)")
            params.append(valid_at_iso)
            clauses.append("(valid_until IS NULL OR valid_until >= ?)")
            params.append(valid_at_iso)

        # Lexical search query
        if search_req.query:
            q_pat = f"%{search_req.query.strip().lower()}%"
            clauses.append("(LOWER(title) LIKE ? OR LOWER(summary) LIKE ? OR LOWER(content) LIKE ?)")
            params.extend([q_pat, q_pat, q_pat])

        # Tag filter
        if search_req.tag:
            tag_pat = f"%{search_req.tag.strip()}%"
            clauses.append("tags_json LIKE ?")
            params.append(tag_pat)

        where_clause = " AND ".join(clauses)

        with self._lock:
            with self._get_connection() as conn:
                # Count total matches
                count_query = f"SELECT COUNT(*) as cnt FROM organizational_memory_entries WHERE {where_clause}"
                cur = conn.execute(count_query, params)
                total_cnt = cur.fetchone()["cnt"]

                # Fetch bounded window
                fetch_query = f"""
                    SELECT * FROM organizational_memory_entries
                    WHERE {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """
                cur = conn.execute(fetch_query, params + [search_req.limit, search_req.offset])
                rows = cur.fetchall()

                entries: List[OrganizationalMemoryEntry] = []
                max_rank = CLASSIFICATION_HIERARCHY.get(
                    max_classification or ClassificationLevel.RESTRICTED, 4
                )

                for r in rows:
                    entry = self._row_to_entry(r)
                    entry_rank = CLASSIFICATION_HIERARCHY.get(entry.classification, 4)
                    if entry_rank <= max_rank:
                        entries.append(entry)

                return entries, total_cnt

    # -------------------------------------------------------------------------
    # Audit & Relationships
    # -------------------------------------------------------------------------

    def record_audit_strict(self, audit: MemoryAuditRecord) -> None:
        """
        Appends an audit record to the ledger under SQLite lock.
        """
        with self._lock:
            with self._get_connection() as conn:
                with conn:
                    self._insert_audit_entry_conn(conn, audit)

    def get_audit_records(
        self,
        tenant_id: str,
        memory_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryAuditRecord]:
        """
        Retrieves audit trail entries for a given tenant and optional memory_id.
        """
        with self._lock:
            with self._get_connection() as conn:
                if memory_id:
                    cur = conn.execute(
                        "SELECT * FROM organizational_memory_audit_ledger WHERE tenant_id = ? AND memory_id = ? ORDER BY timestamp DESC LIMIT ?",
                        (tenant_id, memory_id, limit),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM organizational_memory_audit_ledger WHERE tenant_id = ? ORDER BY timestamp DESC LIMIT ?",
                        (tenant_id, limit),
                    )
                rows = cur.fetchall()
                records: List[MemoryAuditRecord] = []
                for r in rows:
                    records.append(MemoryAuditRecord(
                        audit_id=r["audit_id"],
                        tenant_id=r["tenant_id"],
                        workspace_id=r["workspace_id"],
                        plant_id=r["plant_id"],
                        memory_id=r["memory_id"],
                        event_type=r["event_type"],
                        actor_id=r["actor_id"],
                        timestamp=datetime.fromisoformat(r["timestamp"]),
                        outcome=r["outcome"],
                        details=json.loads(r["details_json"]),
                    ))
                return records

    def clear_all_for_tenant(self, tenant_id: str) -> None:
        """
        Purges memory and audit records for an explicit tenant (used for test teardown).
        """
        with self._lock:
            with self._get_connection() as conn:
                with conn:
                    conn.execute("DELETE FROM organizational_memory_entries WHERE tenant_id = ?", (tenant_id,))
                    conn.execute("DELETE FROM organizational_memory_audit_ledger WHERE tenant_id = ?", (tenant_id,))
                    conn.execute("DELETE FROM organizational_memory_relationships WHERE tenant_id = ?", (tenant_id,))


# Global singleton repository instance
organizational_memory_repository = OrganizationalMemoryRepository()
