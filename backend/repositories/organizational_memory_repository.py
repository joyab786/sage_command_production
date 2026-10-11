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
import logging
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
        VALID_LIFECYCLE_TRANSITIONS,
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
        VALID_LIFECYCLE_TRANSITIONS,
    )
    from backend.data.schemas.sop_rag_contract import ClassificationLevel
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceStatus,
        UncertaintyType,
    )

logger = logging.getLogger("organizational_memory_repository")


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
                self._migrate_schema_if_needed(conn)
                self._create_tables_and_indexes(conn)

    def _create_tables_and_indexes(self, conn: sqlite3.Connection) -> None:
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
                PRIMARY KEY (tenant_id, workspace_id, memory_id)
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

        # Performance and workspace isolation indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_ws ON organizational_memory_entries (tenant_id, workspace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_ws_id ON organizational_memory_entries (tenant_id, workspace_id, memory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_type ON organizational_memory_entries (tenant_id, workspace_id, memory_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_status ON organizational_memory_entries (tenant_id, workspace_id, lifecycle_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_plant ON organizational_memory_entries (tenant_id, workspace_id, plant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_asset ON organizational_memory_entries (tenant_id, workspace_id, asset_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_incident ON organizational_memory_entries (tenant_id, workspace_id, incident_reference)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_decision ON organizational_memory_entries (tenant_id, workspace_id, decision_reference)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_audit_tenant_ws_mem ON organizational_memory_audit_ledger (tenant_id, workspace_id, memory_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_rel_target ON organizational_memory_relationships (tenant_id, target_memory_id)")

    def _migrate_schema_if_needed(self, conn: sqlite3.Connection) -> bool:
        """
        Detects actual existing table schema and safely migrates composite primary key to
        (tenant_id, workspace_id, memory_id) if existing database was created under older schema.
        Preserves all existing organizational-memory entries, audit records, relationships,
        provenance, classifications, and lifecycle states.
        Idempotent and safe to run repeatedly.
        Returns True if a migration was performed, False otherwise.
        """
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='organizational_memory_entries'"
        )
        if not cur.fetchone():
            return False

        table_info = conn.execute("PRAGMA table_info(organizational_memory_entries)").fetchall()
        pk_cols = [r[1] for r in sorted([r for r in table_info if r[5] > 0], key=lambda x: x[5])]

        target_pk = ["tenant_id", "workspace_id", "memory_id"]
        if pk_cols == target_pk:
            return False

        logger.info(
            "Migrating organizational_memory_entries schema from PK %s to %s",
            pk_cols, target_pk,
        )

        fk_cur = conn.execute("PRAGMA foreign_keys")
        fk_enabled = bool(fk_cur.fetchone()[0])
        if fk_enabled:
            conn.execute("PRAGMA foreign_keys = OFF")

        try:
            with conn:
                old_count = conn.execute("SELECT COUNT(*) FROM organizational_memory_entries").fetchone()[0]

                # 1. Create temporary migration table with target composite primary key
                conn.execute("""
                    CREATE TABLE organizational_memory_entries__v3_migration (
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
                        PRIMARY KEY (tenant_id, workspace_id, memory_id)
                    )
                """)

                # 2. Copy all data into migration table preserving all fields
                conn.execute("""
                    INSERT INTO organizational_memory_entries__v3_migration (
                        memory_id, tenant_id, workspace_id, plant_id, asset_id, process_id, session_id,
                        classification, memory_type, epistemic_status, lifecycle_status, verification_status,
                        title, summary, content, tags_json, source_references_json, evidence_references_json,
                        decision_reference, incident_reference, rca_reference, sop_reference, relationships_json,
                        supersedes_memory_id, superseded_by_memory_id, revision, confidence_status,
                        uncertainty_types_json, uncertainty_notes, retention_policy, is_hold, hold_reason,
                        event_timestamp, valid_from, valid_until, created_at, updated_at,
                        verified_at, superseded_at, archived_at, created_by, verified_by,
                        superseded_by, archived_by, metadata_json
                    )
                    SELECT
                        memory_id, tenant_id, COALESCE(NULLIF(workspace_id, ''), 'workspace_default'), plant_id, asset_id, process_id, session_id,
                        classification, memory_type, epistemic_status, lifecycle_status, verification_status,
                        title, summary, content, tags_json, source_references_json, evidence_references_json,
                        decision_reference, incident_reference, rca_reference, sop_reference, relationships_json,
                        supersedes_memory_id, superseded_by_memory_id, revision, confidence_status,
                        uncertainty_types_json, uncertainty_notes, retention_policy, is_hold, hold_reason,
                        event_timestamp, valid_from, valid_until, created_at, updated_at,
                        verified_at, superseded_at, archived_at, created_by, verified_by,
                        superseded_by, archived_by, metadata_json
                    FROM organizational_memory_entries
                """)

                # 3. Verify exact record count preservation
                new_count = conn.execute("SELECT COUNT(*) FROM organizational_memory_entries__v3_migration").fetchone()[0]
                if new_count != old_count:
                    raise RuntimeError(
                        f"Migration aborted: row count mismatch. Expected {old_count}, got {new_count}."
                    )

                # 4. Drop old table and rename migration table
                conn.execute("DROP TABLE organizational_memory_entries")
                conn.execute("ALTER TABLE organizational_memory_entries__v3_migration RENAME TO organizational_memory_entries")

                # 5. Recreate indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_ws ON organizational_memory_entries (tenant_id, workspace_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_ws_id ON organizational_memory_entries (tenant_id, workspace_id, memory_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_type ON organizational_memory_entries (tenant_id, workspace_id, memory_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_status ON organizational_memory_entries (tenant_id, workspace_id, lifecycle_status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_plant ON organizational_memory_entries (tenant_id, workspace_id, plant_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_asset ON organizational_memory_entries (tenant_id, workspace_id, asset_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_incident ON organizational_memory_entries (tenant_id, workspace_id, incident_reference)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_tenant_decision ON organizational_memory_entries (tenant_id, workspace_id, decision_reference)")

            logger.info("Successfully migrated organizational_memory_entries schema to composite PK (rows: %d)", new_count)
            return True
        except Exception as exc:
            try:
                conn.execute("DROP TABLE IF EXISTS organizational_memory_entries__v3_migration")
                conn.commit()
            except Exception:
                pass
            logger.error("Failed to migrate organizational_memory_entries schema: %s", exc)
            raise RuntimeError(f"Database schema migration failed: {exc}") from exc
        finally:
            if fk_enabled:
                conn.execute("PRAGMA foreign_keys = ON")

    def migrate_schema(self) -> bool:
        """
        Public entry point to check and perform schema migration if necessary.
        """
        with self._lock:
            with self._get_connection() as conn:
                return self._migrate_schema_if_needed(conn)

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
        Fails if the entry is not in DRAFT status or does not exist under (tenant_id, workspace_id).
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Verify currently in DRAFT status under tenant_id and workspace_id
                    cur = conn.execute(
                        "SELECT lifecycle_status FROM organizational_memory_entries WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?",
                        (entry.tenant_id, entry.workspace_id, entry.memory_id),
                    )
                    row = cur.fetchone()
                    if not row or row["lifecycle_status"] != MemoryLifecycleStatus.DRAFT.value:
                        return False

                    row_data = self._entry_to_row(entry)
                    conn.execute("""
                        UPDATE organizational_memory_entries SET
                            plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                            classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                            verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                            source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                            incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                            supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                            uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                            hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                            updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                            verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                        WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?
                    """, row_data[3:] + (entry.tenant_id, entry.workspace_id, entry.memory_id))

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
        Enforces tenant_id and workspace_id boundaries.
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
                            plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                            classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                            verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                            source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                            incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                            supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                            uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                            hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                            updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                            verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                        WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?
                    """, row_data[3:] + (entry.tenant_id, entry.workspace_id, entry.memory_id))

                    if cursor.rowcount == 0:
                        return False

                    # Primary audit record
                    self._insert_audit_entry_conn(conn, audit)

                    # Extra entry update (e.g. older entry marked superseded)
                    if extra_entry_to_update:
                        extra_row = self._entry_to_row(extra_entry_to_update)
                        extra_cur = conn.execute("""
                            UPDATE organizational_memory_entries SET
                                plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                                classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                                verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                                source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                                incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                                supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                                uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                                hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                                updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                                verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                            WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?
                        """, extra_row[3:] + (extra_entry_to_update.tenant_id, extra_entry_to_update.workspace_id, extra_entry_to_update.memory_id))
                        if extra_cur.rowcount == 0:
                            raise RuntimeError(f"Failed to update superseded entry {extra_entry_to_update.memory_id}")

                    # Extra audit record
                    if extra_audit:
                        self._insert_audit_entry_conn(conn, extra_audit)

                return True
            finally:
                conn.close()

    def supersede_entry_atomic(
        self,
        superseded_entry: OrganizationalMemoryEntry,
        superseded_audit: MemoryAuditRecord,
        replacement_entry: Optional[OrganizationalMemoryEntry] = None,
        replacement_audit: Optional[MemoryAuditRecord] = None,
    ) -> bool:
        """
        Atomically supersedes a memory entry in a single SQLite transaction:
        1. Verifies existing target belongs to authoritative (tenant_id, workspace_id).
        2. Verifies target's current lifecycle state permits supersession and is not under hold.
        3. Inserts replacement entry, if requested.
        4. Inserts replacement-created audit event, if replacement exists.
        5. Updates original entry to SUPERSEDED.
        6. Inserts original supersession audit event.
        7. Commits only after all required operations succeed; rolls back all changes on any error.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # 1. Verify target exists and belongs to authoritative (tenant_id, workspace_id)
                    cur = conn.execute(
                        "SELECT lifecycle_status, is_hold FROM organizational_memory_entries WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?",
                        (superseded_entry.tenant_id, superseded_entry.workspace_id, superseded_entry.memory_id),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise KeyError(
                            f"Memory entry '{superseded_entry.memory_id}' not found in workspace '{superseded_entry.workspace_id}'."
                        )

                    # 2. Verify lifecycle permits supersession and is not under active hold
                    current_status = MemoryLifecycleStatus(row["lifecycle_status"])
                    valid_targets = VALID_LIFECYCLE_TRANSITIONS.get(current_status, set())
                    if MemoryLifecycleStatus.SUPERSEDED not in valid_targets:
                        raise ValueError(
                            f"Memory entry '{superseded_entry.memory_id}' in status '{current_status.value}' cannot be superseded."
                        )
                    if row["is_hold"]:
                        raise ValueError(
                            f"Memory entry '{superseded_entry.memory_id}' is under active hold and cannot be superseded."
                        )

                    # Validate tenant/workspace alignment if replacement exists
                    if replacement_entry:
                        if (
                            replacement_entry.tenant_id != superseded_entry.tenant_id
                            or replacement_entry.workspace_id != superseded_entry.workspace_id
                        ):
                            raise ValueError(
                                "Replacement entry must belong to the same tenant_id and workspace_id as target entry."
                            )
                        if replacement_audit and (
                            replacement_audit.tenant_id != superseded_entry.tenant_id
                            or replacement_audit.workspace_id != superseded_entry.workspace_id
                        ):
                            raise ValueError(
                                "Replacement audit must belong to the same tenant_id and workspace_id as target entry."
                            )

                        # 3. Insert replacement entry
                        row_data_repl = self._entry_to_row(replacement_entry)
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
                        """, row_data_repl)

                        # 4. Insert replacement-created audit event
                        if replacement_audit:
                            self._insert_audit_entry_conn(conn, replacement_audit)

                    # 5. Update original entry to SUPERSEDED
                    row_data_sup = self._entry_to_row(superseded_entry)
                    upd_cur = conn.execute("""
                        UPDATE organizational_memory_entries SET
                            plant_id = ?, asset_id = ?, process_id = ?, session_id = ?,
                            classification = ?, memory_type = ?, epistemic_status = ?, lifecycle_status = ?,
                            verification_status = ?, title = ?, summary = ?, content = ?, tags_json = ?,
                            source_references_json = ?, evidence_references_json = ?, decision_reference = ?,
                            incident_reference = ?, rca_reference = ?, sop_reference = ?, relationships_json = ?,
                            supersedes_memory_id = ?, superseded_by_memory_id = ?, revision = ?, confidence_status = ?,
                            uncertainty_types_json = ?, uncertainty_notes = ?, retention_policy = ?, is_hold = ?,
                            hold_reason = ?, event_timestamp = ?, valid_from = ?, valid_until = ?, created_at = ?,
                            updated_at = ?, verified_at = ?, superseded_at = ?, archived_at = ?, created_by = ?,
                            verified_by = ?, superseded_by = ?, archived_by = ?, metadata_json = ?
                        WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?
                    """, row_data_sup[3:] + (superseded_entry.tenant_id, superseded_entry.workspace_id, superseded_entry.memory_id))

                    if upd_cur.rowcount == 0:
                        raise RuntimeError(f"Failed to update original entry '{superseded_entry.memory_id}'.")

                    # 6. Insert original supersession audit event
                    self._insert_audit_entry_conn(conn, superseded_audit)

                return True
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # Retrieval & Search
    # -------------------------------------------------------------------------

    def get_entry(
        self,
        tenant_id: str,
        workspace_id: str,
        memory_id: str,
    ) -> Optional[OrganizationalMemoryEntry]:
        """
        Retrieves a single memory entry strictly partitioned by tenant_id and workspace_id.
        """
        if not workspace_id or not workspace_id.strip():
            raise ValueError("Authoritative workspace_id is required for memory entry retrieval.")

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM organizational_memory_entries WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ?",
                    (tenant_id, workspace_id, memory_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return self._row_to_entry(row)

    def search_entries(
        self,
        tenant_id: str,
        workspace_id: str,
        search_req: MemorySearchRequest,
        allowed_plant_ids: Optional[Set[str]] = None,
        max_classification: Optional[ClassificationLevel] = None,
    ) -> Tuple[List[OrganizationalMemoryEntry], int]:
        """
        Deterministic, bounded search query with strict server-side scoping:
        - tenant_id and workspace_id mandatory filtering
        - plant_id authorization filtering (strictly intersected with allowed_plant_ids)
        - classification ceiling filtering
        - optional metadata and lexical filters
        Returns (entries, total_matching_count).
        """
        if not workspace_id or not workspace_id.strip():
            raise ValueError("Authoritative workspace_id is required for memory search.")

        clauses = ["tenant_id = ?", "workspace_id = ?"]
        params: List[Any] = [tenant_id, workspace_id]

        # Scope filters: strictly intersect requested plant with allowed_plant_ids
        if allowed_plant_ids is not None:
            if not allowed_plant_ids:
                return [], 0
            if search_req.plant_id:
                if search_req.plant_id not in allowed_plant_ids:
                    # Client-supplied plant_id is outside authorized set -> intersection is empty!
                    return [], 0
                clauses.append("plant_id = ?")
                params.append(search_req.plant_id)
            else:
                placeholders = ",".join("?" for _ in allowed_plant_ids)
                clauses.append(f"plant_id IN ({placeholders})")
                params.extend(list(allowed_plant_ids))
        elif search_req.plant_id:
            clauses.append("plant_id = ?")
            params.append(search_req.plant_id)

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

        # Classification ceiling filter applied before both counting and pagination
        target_ceiling = max_classification or ClassificationLevel.RESTRICTED
        max_rank = CLASSIFICATION_HIERARCHY.get(target_ceiling, 4)
        allowed_classifications = [
            lvl.value
            for lvl, rank in CLASSIFICATION_HIERARCHY.items()
            if rank <= max_rank
        ]
        if not allowed_classifications:
            return [], 0

        placeholders_cls = ",".join("?" for _ in allowed_classifications)
        clauses.append(f"classification IN ({placeholders_cls})")
        params.extend(allowed_classifications)

        where_clause = " AND ".join(clauses)

        with self._lock:
            with self._get_connection() as conn:
                # Count total matches within authorized classification ceiling
                count_query = f"SELECT COUNT(*) as cnt FROM organizational_memory_entries WHERE {where_clause}"
                cur = conn.execute(count_query, params)
                total_cnt = cur.fetchone()["cnt"]

                # Fetch bounded window within authorized classification ceiling
                fetch_query = f"""
                    SELECT * FROM organizational_memory_entries
                    WHERE {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ? OFFSET ?
                """
                cur = conn.execute(fetch_query, params + [search_req.limit, search_req.offset])
                rows = cur.fetchall()

                entries: List[OrganizationalMemoryEntry] = [self._row_to_entry(r) for r in rows]
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
        workspace_id: str,
        memory_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryAuditRecord]:
        """
        Retrieves audit trail entries partitioned strictly by tenant_id and workspace_id.
        """
        if not workspace_id or not workspace_id.strip():
            raise ValueError("Authoritative workspace_id is required for audit retrieval.")

        with self._lock:
            with self._get_connection() as conn:
                if memory_id:
                    cur = conn.execute(
                        "SELECT * FROM organizational_memory_audit_ledger WHERE tenant_id = ? AND workspace_id = ? AND memory_id = ? ORDER BY timestamp DESC LIMIT ?",
                        (tenant_id, workspace_id, memory_id, limit),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM organizational_memory_audit_ledger WHERE tenant_id = ? AND workspace_id = ? ORDER BY timestamp DESC LIMIT ?",
                        (tenant_id, workspace_id, limit),
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

    def clear_all_for_tenant(self, tenant_id: str, workspace_id: Optional[str] = None) -> None:
        """
        Purges memory and audit records for an explicit tenant (and optional workspace).
        """
        with self._lock:
            with self._get_connection() as conn:
                with conn:
                    if workspace_id:
                        conn.execute("DELETE FROM organizational_memory_entries WHERE tenant_id = ? AND workspace_id = ?", (tenant_id, workspace_id))
                        conn.execute("DELETE FROM organizational_memory_audit_ledger WHERE tenant_id = ? AND workspace_id = ?", (tenant_id, workspace_id))
                    else:
                        conn.execute("DELETE FROM organizational_memory_entries WHERE tenant_id = ?", (tenant_id,))
                        conn.execute("DELETE FROM organizational_memory_audit_ledger WHERE tenant_id = ?", (tenant_id,))
                    conn.execute("DELETE FROM organizational_memory_relationships WHERE tenant_id = ?", (tenant_id,))


# Global singleton repository instance
organizational_memory_repository = OrganizationalMemoryRepository()
