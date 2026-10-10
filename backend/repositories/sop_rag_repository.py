# backend/repositories/sop_rag_repository.py
"""
SageCommand V3 — SOP / RAG Intelligence Foundation Repository (Prompt 33)

Thread-safe, tenant-isolated SQLite WAL persistence for authoritative SOP documents,
deterministic document chunks, and an append-only audit ledger.
Ensures parameterized queries, zero SQL injection surface, foreign key cascades,
and atomic transaction boundaries.

Invariants:
- Strict tenant partitioning on every operation (tenant_id in WHERE clauses).
- Incomplete or failed ingestion documents are never published as active guidance.
- Chunk-to-document version integrity strictly preserved via foreign keys.
- Read-only queries never mutate documents or operational subsystems.
"""

import json
import sqlite3
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

try:
    from core.config import SAGE_SOP_RAG_DB_PATH
    from data.schemas.sop_rag_contract import (
        SOPDocument,
        DocumentChunk,
        DocumentLifecycleStatus,
        DocumentType,
        OperationalDomain,
        ClassificationLevel,
        DocumentApprovalMetadata,
        DocumentProvenanceInfo,
        SOPAuditRecord,
    )
except (ImportError, ModuleNotFoundError):
    from backend.core.config import SAGE_SOP_RAG_DB_PATH
    from backend.data.schemas.sop_rag_contract import (
        SOPDocument,
        DocumentChunk,
        DocumentLifecycleStatus,
        DocumentType,
        OperationalDomain,
        ClassificationLevel,
        DocumentApprovalMetadata,
        DocumentProvenanceInfo,
        SOPAuditRecord,
    )


class SOPRAGRepository:
    """
    Thread-safe SQLite WAL repository for SOP Document and Chunk persistence.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_SOP_RAG_DB_PATH
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
                    CREATE TABLE IF NOT EXISTS sop_documents (
                        document_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        plant_id TEXT,
                        title TEXT NOT NULL,
                        description TEXT,
                        document_type TEXT NOT NULL,
                        operational_domain TEXT NOT NULL,
                        lifecycle_status TEXT NOT NULL,
                        effective_from TEXT,
                        effective_until TEXT,
                        approval_metadata_json TEXT,
                        classification TEXT NOT NULL,
                        access_control_roles_json TEXT NOT NULL,
                        content_digest TEXT NOT NULL,
                        provenance_json TEXT NOT NULL,
                        raw_text TEXT,
                        total_chunks INTEGER NOT NULL DEFAULT 0,
                        is_valid INTEGER NOT NULL DEFAULT 1,
                        validation_errors_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (document_id, tenant_id, version)
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sop_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        document_version TEXT NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        section_heading TEXT,
                        page_number INTEGER,
                        content_digest TEXT NOT NULL,
                        plant_id TEXT,
                        classification TEXT NOT NULL,
                        access_control_roles_json TEXT NOT NULL,
                        lifecycle_status TEXT NOT NULL,
                        char_count INTEGER NOT NULL,
                        token_count_estimate INTEGER NOT NULL,
                        metadata_json TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (document_id, tenant_id, document_version)
                            REFERENCES sop_documents(document_id, tenant_id, version)
                            ON DELETE CASCADE
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sop_rag_audit_ledger (
                        audit_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        document_id TEXT,
                        query_hash TEXT,
                        passage_count INTEGER NOT NULL DEFAULT 0,
                        outcome TEXT NOT NULL,
                        detail TEXT
                    )
                """)

                # Indices for high-performance scoped retrieval & auditing
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sop_docs_tenant_status ON sop_documents (tenant_id, lifecycle_status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sop_docs_digest ON sop_documents (tenant_id, content_digest)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sop_chunks_tenant_doc ON sop_chunks (tenant_id, document_id, document_version)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sop_chunks_tenant_status ON sop_chunks (tenant_id, lifecycle_status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sop_audit_tenant_time ON sop_rag_audit_ledger (tenant_id, timestamp)")
                conn.commit()

    # -------------------------------------------------------------------------
    # DOCUMENT PERSISTENCE & RETRIEVAL
    # -------------------------------------------------------------------------

    def save_document(self, doc: SOPDocument) -> None:
        """
        Atomically saves or updates an authoritative SOP document and all of its chunks.
        """
        approval_json = json.dumps(doc.approval_metadata.model_dump()) if doc.approval_metadata else None
        roles_json = json.dumps(doc.access_control_roles)
        provenance_json = json.dumps(doc.provenance_info.model_dump())
        errors_json = json.dumps(doc.validation_errors)

        with self._lock:
            with self._get_connection() as conn:
                # Upsert parent document
                conn.execute("""
                    INSERT INTO sop_documents (
                        document_id, tenant_id, version, plant_id, title, description,
                        document_type, operational_domain, lifecycle_status, effective_from,
                        effective_until, approval_metadata_json, classification,
                        access_control_roles_json, content_digest, provenance_json,
                        raw_text, total_chunks, is_valid, validation_errors_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id, tenant_id, version) DO UPDATE SET
                        plant_id = excluded.plant_id,
                        title = excluded.title,
                        description = excluded.description,
                        document_type = excluded.document_type,
                        operational_domain = excluded.operational_domain,
                        lifecycle_status = excluded.lifecycle_status,
                        effective_from = excluded.effective_from,
                        effective_until = excluded.effective_until,
                        approval_metadata_json = excluded.approval_metadata_json,
                        classification = excluded.classification,
                        access_control_roles_json = excluded.access_control_roles_json,
                        content_digest = excluded.content_digest,
                        provenance_json = excluded.provenance_json,
                        raw_text = excluded.raw_text,
                        total_chunks = excluded.total_chunks,
                        is_valid = excluded.is_valid,
                        validation_errors_json = excluded.validation_errors_json,
                        updated_at = excluded.updated_at
                """, (
                    doc.document_id,
                    doc.tenant_id,
                    doc.version,
                    doc.plant_id,
                    doc.title,
                    doc.description,
                    doc.document_type.value,
                    doc.operational_domain.value,
                    doc.lifecycle_status.value,
                    doc.effective_from,
                    doc.effective_until,
                    approval_json,
                    doc.classification.value,
                    roles_json,
                    doc.content_digest,
                    provenance_json,
                    doc.raw_text,
                    doc.total_chunks,
                    1 if doc.is_valid else 0,
                    errors_json,
                    doc.created_at,
                    doc.updated_at,
                ))

                # Delete existing chunks for this document version before inserting new chunks
                conn.execute("""
                    DELETE FROM sop_chunks
                    WHERE tenant_id = ? AND document_id = ? AND document_version = ?
                """, (doc.tenant_id, doc.document_id, doc.version))

                now_ts = datetime.now(timezone.utc).isoformat()
                for chunk in doc.chunks:
                    chunk_roles_json = json.dumps(chunk.access_control_roles)
                    chunk_meta_json = json.dumps(chunk.metadata)
                    conn.execute("""
                        INSERT INTO sop_chunks (
                            chunk_id, document_id, tenant_id, document_version, chunk_index,
                            content, section_heading, page_number, content_digest, plant_id,
                            classification, access_control_roles_json, lifecycle_status,
                            char_count, token_count_estimate, metadata_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.tenant_id,
                        chunk.document_version,
                        chunk.chunk_index,
                        chunk.content,
                        chunk.section_heading,
                        chunk.page_number,
                        chunk.content_digest,
                        chunk.plant_id,
                        chunk.classification.value,
                        chunk_roles_json,
                        chunk.lifecycle_status.value,
                        chunk.char_count,
                        chunk.token_count_estimate,
                        chunk_meta_json,
                        now_ts,
                    ))

                conn.commit()

    def get_document(
        self,
        tenant_id: str,
        document_id: str,
        version: Optional[str] = None
    ) -> Optional[SOPDocument]:
        """
        Retrieves an authoritative document by document_id and tenant_id.
        If version is omitted, returns the latest updated version.
        """
        with self._lock:
            with self._get_connection() as conn:
                if version:
                    cursor = conn.execute("""
                        SELECT * FROM sop_documents
                        WHERE tenant_id = ? AND document_id = ? AND version = ?
                    """, (tenant_id, document_id, version))
                else:
                    cursor = conn.execute("""
                        SELECT * FROM sop_documents
                        WHERE tenant_id = ? AND document_id = ?
                        ORDER BY updated_at DESC LIMIT 1
                    """, (tenant_id, document_id))
                row = cursor.fetchone()
                if not row:
                    return None

                doc_dict = self._row_to_doc_dict(row)
                # Load chunks
                chunk_cursor = conn.execute("""
                    SELECT * FROM sop_chunks
                    WHERE tenant_id = ? AND document_id = ? AND document_version = ?
                    ORDER BY chunk_index ASC
                """, (tenant_id, doc_dict["document_id"], doc_dict["version"]))
                chunks = [self._row_to_chunk(c_row) for c_row in chunk_cursor.fetchall()]
                doc_dict["chunks"] = chunks
                return SOPDocument(**doc_dict)

    def find_document_by_digest(
        self,
        tenant_id: str,
        content_digest: str
    ) -> Optional[SOPDocument]:
        """
        Finds an existing document with the identical content digest in the tenant.
        Used for deterministic duplicate detection.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM sop_documents
                    WHERE tenant_id = ? AND content_digest = ?
                    LIMIT 1
                """, (tenant_id, content_digest))
                row = cursor.fetchone()
                if not row:
                    return None
                doc_dict = self._row_to_doc_dict(row)
                return SOPDocument(**doc_dict)

    def list_documents(
        self,
        tenant_id: str,
        plant_id: Optional[str] = None,
        lifecycle_statuses: Optional[List[str]] = None,
        allowed_classifications: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[SOPDocument]:
        """
        Lists documents within tenant scope with optional plant, status, and classification filtering.
        """
        query = "SELECT * FROM sop_documents WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]

        if plant_id:
            query += " AND (plant_id = ? OR plant_id IS NULL)"
            params.append(plant_id)

        if lifecycle_statuses:
            placeholders = ",".join("?" for _ in lifecycle_statuses)
            query += f" AND lifecycle_status IN ({placeholders})"
            params.extend(lifecycle_statuses)

        if allowed_classifications is not None:
            cls_placeholders = ",".join("?" for _ in allowed_classifications)
            query += f" AND classification IN ({cls_placeholders})"
            params.extend(allowed_classifications)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(query, tuple(params))
                results = []
                for row in cursor.fetchall():
                    doc_dict = self._row_to_doc_dict(row)
                    results.append(SOPDocument(**doc_dict))
                return results

    def update_lifecycle_status(
        self,
        tenant_id: str,
        document_id: str,
        version: str,
        new_status: DocumentLifecycleStatus,
        approval_metadata: Optional[DocumentApprovalMetadata] = None,
    ) -> bool:
        """
        Updates the lifecycle status of a document, optionally records authoritative approval metadata,
        and synchronizes all child chunks.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                if approval_metadata is not None:
                    approval_json = json.dumps(approval_metadata.model_dump())
                    cursor = conn.execute("""
                        UPDATE sop_documents
                        SET lifecycle_status = ?, updated_at = ?, approval_metadata_json = ?
                        WHERE tenant_id = ? AND document_id = ? AND version = ?
                    """, (new_status.value, now_ts, approval_json, tenant_id, document_id, version))
                else:
                    cursor = conn.execute("""
                        UPDATE sop_documents
                        SET lifecycle_status = ?, updated_at = ?
                        WHERE tenant_id = ? AND document_id = ? AND version = ?
                    """, (new_status.value, now_ts, tenant_id, document_id, version))

                if cursor.rowcount == 0:
                    return False

                # Synchronize chunks
                conn.execute("""
                    UPDATE sop_chunks
                    SET lifecycle_status = ?
                    WHERE tenant_id = ? AND document_id = ? AND document_version = ?
                """, (new_status.value, tenant_id, document_id, version))

                conn.commit()
                return True

    def commit_lifecycle_transition_atomic(
        self,
        tenant_id: str,
        document_id: str,
        version: str,
        new_status: DocumentLifecycleStatus,
        audit: SOPAuditRecord,
        approval_metadata: Optional[DocumentApprovalMetadata] = None,
    ) -> bool:
        """
        Atomically updates the document lifecycle status, synchronizes child chunks,
        persists authoritative approval metadata if provided, and records the mandatory
        audit log entry in the audit ledger within a single SQLite transaction.

        Invariants:
        - Either both the document/chunk lifecycle change and its required audit record commit, or neither commits.
        - If the document or chunk updates fail, no audit record is committed.
        - If the audit insert fails, all document and chunk updates are rolled back.
        - Returns True only after the entire combined transaction commits.
        """
        now_ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    if approval_metadata is not None:
                        approval_json = json.dumps(approval_metadata.model_dump())
                        cursor = conn.execute("""
                            UPDATE sop_documents
                            SET lifecycle_status = ?, updated_at = ?, approval_metadata_json = ?
                            WHERE tenant_id = ? AND document_id = ? AND version = ?
                        """, (new_status.value, now_ts, approval_json, tenant_id, document_id, version))
                    else:
                        cursor = conn.execute("""
                            UPDATE sop_documents
                            SET lifecycle_status = ?, updated_at = ?
                            WHERE tenant_id = ? AND document_id = ? AND version = ?
                        """, (new_status.value, now_ts, tenant_id, document_id, version))

                    if cursor.rowcount == 0:
                        return False

                    # Synchronize chunks
                    conn.execute("""
                        UPDATE sop_chunks
                        SET lifecycle_status = ?
                        WHERE tenant_id = ? AND document_id = ? AND document_version = ?
                    """, (new_status.value, tenant_id, document_id, version))

                    # Mandatory audit entry within the same transaction
                    self._insert_audit_entry_conn(conn, audit)

                return True
            finally:
                conn.close()

    # -------------------------------------------------------------------------
    # CHUNK RETRIEVAL
    # -------------------------------------------------------------------------

    def get_chunks_for_document(
        self,
        tenant_id: str,
        document_id: str,
        version: str
    ) -> List[DocumentChunk]:
        """
        Retrieves all chunks belonging to a specific document version.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM sop_chunks
                    WHERE tenant_id = ? AND document_id = ? AND document_version = ?
                    ORDER BY chunk_index ASC
                """, (tenant_id, document_id, version))
                return [self._row_to_chunk(row) for row in cursor.fetchall()]

    def query_eligible_chunks(
        self,
        tenant_id: str,
        plant_id: Optional[str] = None,
        operational_domains: Optional[List[str]] = None,
        document_types: Optional[List[str]] = None,
        document_ids: Optional[List[str]] = None,
        lifecycle_statuses: Optional[List[str]] = None,
        require_effective_at: Optional[str] = None,
        allowed_roles: Optional[List[str]] = None,
        allowed_classifications: Optional[List[str]] = None,
    ) -> List[DocumentChunk]:
        """
        Selects all chunks from eligible documents adhering strictly to tenant isolation,
        plant scope, lifecycle status, temporal validity, classification clearance, and access roles.
        """
        # Join with sop_documents to filter on document-level metadata (domain, doc_type, effective dates)
        query = """
            SELECT c.*, d.effective_from, d.effective_until, d.operational_domain, d.document_type
            FROM sop_chunks c
            JOIN sop_documents d
                ON c.tenant_id = d.tenant_id
                AND c.document_id = d.document_id
                AND c.document_version = d.version
            WHERE c.tenant_id = ?
        """
        params: List[Any] = [tenant_id]

        # Lifecycle status filtering: default to PUBLISHED only if not specified
        statuses = lifecycle_statuses or [DocumentLifecycleStatus.PUBLISHED.value]
        placeholders = ",".join("?" for _ in statuses)
        query += f" AND c.lifecycle_status IN ({placeholders})"
        params.extend(statuses)

        # Classification / Security Clearance filtering (Enforce in repository query path)
        if allowed_classifications is not None:
            cls_placeholders = ",".join("?" for _ in allowed_classifications)
            query += f" AND c.classification IN ({cls_placeholders})"
            params.extend(allowed_classifications)
        else:
            # Strict fail-closed: if allowed classifications not supplied, only PUBLIC chunks are accessible
            query += " AND c.classification = ?"
            params.append(ClassificationLevel.PUBLIC.value)

        # Plant partition check
        if plant_id:
            query += " AND (c.plant_id = ? OR c.plant_id IS NULL)"
            params.append(plant_id)

        # Operational domain filtering
        if operational_domains:
            dom_placeholders = ",".join("?" for _ in operational_domains)
            query += f" AND d.operational_domain IN ({dom_placeholders})"
            params.extend(operational_domains)

        # Document type filtering
        if document_types:
            type_placeholders = ",".join("?" for _ in document_types)
            query += f" AND d.document_type IN ({type_placeholders})"
            params.extend(document_types)

        # Document ID restriction
        if document_ids:
            id_placeholders = ",".join("?" for _ in document_ids)
            query += f" AND c.document_id IN ({id_placeholders})"
            params.extend(document_ids)

        # Temporal validity filtering
        if require_effective_at:
            query += " AND (d.effective_from IS NULL OR d.effective_from <= ?)"
            params.append(require_effective_at)
            query += " AND (d.effective_until IS NULL OR d.effective_until >= ?)"
            params.append(require_effective_at)

        query += " ORDER BY c.document_id ASC, c.document_version DESC, c.chunk_index ASC"

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(query, tuple(params))
                chunks: List[DocumentChunk] = []
                for row in cursor.fetchall():
                    chunk = self._row_to_chunk(row)
                    # Filter by access control roles if role restriction is active
                    if allowed_roles is not None and chunk.access_control_roles:
                        # Chunk has role restrictions; verify if caller has at least one matching role
                        chunk_roles = set(r.lower() for r in chunk.access_control_roles)
                        user_roles = set(r.lower() for r in allowed_roles)
                        if not chunk_roles.intersection(user_roles) and "*" not in user_roles:
                            continue  # Excluded due to insufficient role
                    chunks.append(chunk)
                return chunks

    # -------------------------------------------------------------------------
    # AUDIT PERSISTENCE
    # -------------------------------------------------------------------------

    def record_audit(self, audit: SOPAuditRecord) -> None:
        """
        Persists an immutable audit log entry into the ledger (best-effort logging).
        """
        try:
            self.record_audit_strict(audit)
        except Exception as e:
            # Best-effort logging avoids failing read/query operations
            pass

    def _insert_audit_entry_conn(self, conn: sqlite3.Connection, audit: SOPAuditRecord) -> None:
        """
        Executes audit ledger row insertion on an existing SQLite connection.
        Must be called within an active transaction boundary.
        """
        conn.execute("""
            INSERT INTO sop_rag_audit_ledger (
                audit_id, timestamp, event_type, tenant_id, actor_id,
                document_id, query_hash, passage_count, outcome, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit.audit_id,
            audit.timestamp,
            audit.event_type,
            audit.tenant_id,
            audit.actor_id,
            audit.document_id,
            audit.query_hash,
            audit.passage_count,
            audit.outcome,
            audit.detail,
        ))

    def record_audit_strict(self, audit: SOPAuditRecord) -> None:
        """
        Strictly persists an immutable audit log entry into the ledger.
        Raises an exception if persistence fails, guaranteeing that privileged operations
        (such as lifecycle transitions and approvals) fail closed if auditing cannot be committed.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    self._insert_audit_entry_conn(conn, audit)
            finally:
                conn.close()

    def get_audit_records(self, tenant_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves recent audit entries for the specified tenant.
        """
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM sop_rag_audit_ledger
                    WHERE tenant_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (tenant_id, limit))
                return [dict(row) for row in cursor.fetchall()]

    def clear_all_for_tenant(self, tenant_id: str) -> None:
        """
        Clears all documents, chunks, and audit logs for a tenant. Strictly for testing isolation.
        """
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM sop_documents WHERE tenant_id = ?", (tenant_id,))
                conn.execute("DELETE FROM sop_rag_audit_ledger WHERE tenant_id = ?", (tenant_id,))
                conn.commit()

    # -------------------------------------------------------------------------
    # INTERNAL DESERIALIZATION HELPERS
    # -------------------------------------------------------------------------

    def _row_to_doc_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        approval_meta = None
        if row["approval_metadata_json"]:
            try:
                approval_meta = DocumentApprovalMetadata(**json.loads(row["approval_metadata_json"]))
            except Exception:
                approval_meta = None

        roles = []
        if row["access_control_roles_json"]:
            try:
                roles = json.loads(row["access_control_roles_json"])
            except Exception:
                roles = []

        provenance = None
        if row["provenance_json"]:
            try:
                provenance = DocumentProvenanceInfo(**json.loads(row["provenance_json"]))
            except Exception:
                provenance = DocumentProvenanceInfo(
                    source_identifier=row["document_id"],
                    ingested_by="unknown",
                    ingestion_timestamp=row["created_at"],
                    content_fingerprint=row["content_digest"],
                )

        val_errors = []
        if row["validation_errors_json"]:
            try:
                val_errors = json.loads(row["validation_errors_json"])
            except Exception:
                val_errors = []

        return {
            "document_id": row["document_id"],
            "tenant_id": row["tenant_id"],
            "version": row["version"],
            "plant_id": row["plant_id"],
            "title": row["title"],
            "description": row["description"],
            "document_type": DocumentType(row["document_type"]),
            "operational_domain": OperationalDomain(row["operational_domain"]),
            "lifecycle_status": DocumentLifecycleStatus(row["lifecycle_status"]),
            "effective_from": row["effective_from"],
            "effective_until": row["effective_until"],
            "approval_metadata": approval_meta,
            "classification": ClassificationLevel(row["classification"]),
            "access_control_roles": roles,
            "content_digest": row["content_digest"],
            "raw_text": row["raw_text"],
            "provenance_info": provenance,
            "total_chunks": row["total_chunks"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_valid": bool(row["is_valid"]),
            "validation_errors": val_errors,
            "chunks": [],
        }

    def _row_to_chunk(self, row: sqlite3.Row) -> DocumentChunk:
        roles = []
        if row["access_control_roles_json"]:
            try:
                roles = json.loads(row["access_control_roles_json"])
            except Exception:
                roles = []

        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return DocumentChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            document_version=row["document_version"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            section_heading=row["section_heading"],
            page_number=row["page_number"],
            content_digest=row["content_digest"],
            plant_id=row["plant_id"],
            classification=ClassificationLevel(row["classification"]),
            access_control_roles=roles,
            lifecycle_status=DocumentLifecycleStatus(row["lifecycle_status"]),
            char_count=row["char_count"],
            token_count_estimate=row["token_count_estimate"],
            metadata=meta,
        )


# Global singleton instance
sop_rag_repository = SOPRAGRepository()
