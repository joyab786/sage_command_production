# backend/services/ledger_repository.py
"""
SageCommand V3 — Persistent Audit Ledger Repository
Provides append-only, thread-safe, multi-tenant scoped persistence for LedgerEvent records.
Enforces strict immutability: historical records can never be updated or deleted.
"""

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Any

try:
    from core.config import SAGE_AUDIT_LEDGER_DB_PATH
    from data.schemas.ledger_contract import (
        LedgerEvent,
        LedgerActor,
        ModelProvenance,
        EventCategory,
        EventStatus,
        ActorType,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_AUDIT_LEDGER_DB_PATH
    from backend.data.schemas.ledger_contract import (
        LedgerEvent,
        LedgerActor,
        ModelProvenance,
        EventCategory,
        EventStatus,
        ActorType,
    )


class AuditLedgerRepository(ABC):
    """Abstract interface for append-only audit ledger storage."""

    @abstractmethod
    def append(self, event: LedgerEvent) -> LedgerEvent:
        """Appends a new event to the ledger."""
        pass

    @abstractmethod
    def get_by_id(self, event_id: str, tenant_id: str) -> Optional[LedgerEvent]:
        """Retrieves an event by its unique ID within tenant partition."""
        pass

    @abstractmethod
    def query(
        self,
        tenant_id: str,
        filters: Dict[str, Any],
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[LedgerEvent], int]:
        """Queries events within tenant boundary matching criteria, returning (events, total_count)."""
        pass

    @abstractmethod
    def get_timeline(
        self,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        action_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50
    ) -> List[LedgerEvent]:
        """Reconstructs ordered chronological timeline of correlated events."""
        pass

    @abstractmethod
    def get_decision_events(self, action_id: str, tenant_id: str) -> List[LedgerEvent]:
        """Retrieves all events directly associated with an action decision lifecycle."""
        pass


class SQLiteAuditLedgerRepository(AuditLedgerRepository):
    """
    Dedicated SQLite Implementation for Audit & Decision Ledger.
    Guarantees persistence in an isolated database file (sage_audit_ledger.sqlite).
    """

    def __init__(self, db_path: str = SAGE_AUDIT_LEDGER_DB_PATH):
        self._lock = threading.RLock()
        self._db_path = db_path
        self._is_memory = (db_path == ":memory:" or "mode=memory" in db_path)
        self._shared_conn = None
        if self._is_memory:
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False, timeout=15.0)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._is_memory and self._shared_conn:
            return self._shared_conn
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_connection(self, conn: sqlite3.Connection):
        if not self._is_memory:
            try:
                conn.close()
            except Exception:
                pass

    def _init_db(self):
        """Initializes the audit_ledger_v3 schema and optimized indexes."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS audit_ledger_v3 (
                            event_id TEXT PRIMARY KEY,
                            event_type TEXT NOT NULL,
                            event_version TEXT NOT NULL,
                            category TEXT NOT NULL,
                            event_status TEXT NOT NULL,
                            occurred_at TEXT NOT NULL,
                            recorded_at TEXT NOT NULL,
                            tenant_id TEXT NOT NULL,
                            workspace_id TEXT NOT NULL,
                            session_id TEXT,
                            plant_id TEXT,
                            user_id TEXT,
                            actor_type TEXT NOT NULL,
                            actor_id TEXT NOT NULL,
                            acting_user_id TEXT,
                            roles_json TEXT,
                            request_id TEXT,
                            trace_id TEXT,
                            correlation_id TEXT,
                            resource_type TEXT,
                            resource_id TEXT,
                            action_id TEXT,
                            mission_id TEXT,
                            incident_id TEXT,
                            data_mode TEXT NOT NULL,
                            payload_json TEXT NOT NULL,
                            metadata_json TEXT NOT NULL,
                            model_provenance_json TEXT,
                            policy_version TEXT,
                            authorization_version TEXT,
                            previous_event_id TEXT,
                            sequence_number INTEGER,
                            event_hash TEXT NOT NULL
                        )
                    """)
                    # Query performance indexes
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_time ON audit_ledger_v3 (tenant_id, occurred_at DESC)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_action ON audit_ledger_v3 (tenant_id, action_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_corr ON audit_ledger_v3 (tenant_id, correlation_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_trace ON audit_ledger_v3 (tenant_id, trace_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant_type ON audit_ledger_v3 (tenant_id, event_type)")
            finally:
                self._close_connection(conn)

    def _row_to_event(self, row: sqlite3.Row) -> LedgerEvent:
        """Hydrates a LedgerEvent domain model from a SQLite row."""
        roles = json.loads(row["roles_json"]) if row["roles_json"] else []
        actor = LedgerActor(
            actor_type=ActorType(row["actor_type"]),
            actor_id=row["actor_id"],
            acting_user_id=row["acting_user_id"],
            roles=roles
        )
        model_prov = None
        if row["model_provenance_json"]:
            try:
                model_prov = ModelProvenance(**json.loads(row["model_provenance_json"]))
            except Exception:
                model_prov = None

        return LedgerEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            event_version=row["event_version"],
            category=EventCategory(row["category"]),
            event_status=EventStatus(row["event_status"]),
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            plant_id=row["plant_id"],
            actor=actor,
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            correlation_id=row["correlation_id"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            action_id=row["action_id"],
            mission_id=row["mission_id"],
            incident_id=row["incident_id"],
            data_mode=row["data_mode"],
            payload=json.loads(row["payload_json"]) if row["payload_json"] else {},
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            model_provenance=model_prov,
            policy_version=row["policy_version"],
            authorization_version=row["authorization_version"],
            previous_event_id=row["previous_event_id"],
            sequence_number=row["sequence_number"],
            event_hash=row["event_hash"]
        )

    def append(self, event: LedgerEvent) -> LedgerEvent:
        """
        Appends event to ledger.
        Enforces idempotency: if event_id exists, returns existing record.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                # 1. Idempotency Check
                existing_row = conn.execute(
                    "SELECT * FROM audit_ledger_v3 WHERE event_id = ? AND tenant_id = ?",
                    (event.event_id, event.tenant_id)
                ).fetchone()
                if existing_row:
                    return self._row_to_event(existing_row)

                # 2. Sequence Calculation within tenant
                if event.sequence_number is None:
                    max_seq_row = conn.execute(
                        "SELECT MAX(sequence_number) as max_seq FROM audit_ledger_v3 WHERE tenant_id = ?",
                        (event.tenant_id,)
                    ).fetchone()
                    current_max = max_seq_row["max_seq"] if max_seq_row and max_seq_row["max_seq"] is not None else 0
                    event.sequence_number = current_max + 1

                # 3. Finalize Hash
                if not event.event_hash:
                    event.finalize_hash()

                # 4. Insert Immutable Row
                with conn:
                    conn.execute("""
                        INSERT INTO audit_ledger_v3 (
                            event_id, event_type, event_version, category, event_status,
                            occurred_at, recorded_at, tenant_id, workspace_id, session_id, plant_id,
                            user_id, actor_type, actor_id, acting_user_id, roles_json,
                            request_id, trace_id, correlation_id, resource_type, resource_id,
                            action_id, mission_id, incident_id, data_mode, payload_json, metadata_json,
                            model_provenance_json, policy_version, authorization_version,
                            previous_event_id, sequence_number, event_hash
                        ) VALUES (
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?,
                            ?, ?, ?,
                            ?, ?, ?
                        )
                    """, (
                        event.event_id,
                        event.event_type,
                        event.event_version,
                        event.category.value,
                        event.event_status.value,
                        event.occurred_at,
                        event.recorded_at,
                        event.tenant_id,
                        event.workspace_id,
                        event.session_id,
                        event.plant_id,
                        event.actor.acting_user_id or event.actor.actor_id,
                        event.actor.actor_type.value,
                        event.actor.actor_id,
                        event.actor.acting_user_id,
                        json.dumps(event.actor.roles),
                        event.request_id,
                        event.trace_id,
                        event.correlation_id,
                        event.resource_type,
                        event.resource_id,
                        event.action_id,
                        event.mission_id,
                        event.incident_id,
                        event.data_mode,
                        json.dumps(event.payload),
                        json.dumps(event.metadata),
                        json.dumps(event.model_provenance.model_dump() if hasattr(event.model_provenance, "model_dump") else event.model_provenance.dict()) if event.model_provenance else None,
                        event.policy_version,
                        event.authorization_version,
                        event.previous_event_id,
                        event.sequence_number,
                        event.event_hash
                    ))
                return event
            finally:
                self._close_connection(conn)

    def get_by_id(self, event_id: str, tenant_id: str) -> Optional[LedgerEvent]:
        """Retrieves a single event strictly scoped to the caller's tenant."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM audit_ledger_v3 WHERE event_id = ? AND tenant_id = ?",
                    (event_id, tenant_id)
                ).fetchone()
                return self._row_to_event(row) if row else None
            finally:
                self._close_connection(conn)

    def query(
        self,
        tenant_id: str,
        filters: Dict[str, Any],
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[LedgerEvent], int]:
        """
        Executes parameterized multi-attribute search within tenant boundaries.
        Enforces safe bounds (max limit 100).
        """
        safe_limit = max(1, min(limit, 100))
        safe_offset = max(0, offset)

        query_clauses = ["tenant_id = ?"]
        params: List[Any] = [tenant_id]

        if filters.get("workspace_id") and filters["workspace_id"] != "*":
            query_clauses.append("workspace_id = ?")
            params.append(filters["workspace_id"])

        if filters.get("session_id"):
            query_clauses.append("session_id = ?")
            params.append(filters["session_id"])

        if filters.get("plant_id"):
            query_clauses.append("plant_id = ?")
            params.append(filters["plant_id"])

        if filters.get("event_type"):
            query_clauses.append("event_type = ?")
            params.append(filters["event_type"])

        if filters.get("category"):
            query_clauses.append("category = ?")
            params.append(filters["category"])

        if filters.get("action_id"):
            query_clauses.append("action_id = ?")
            params.append(filters["action_id"])

        if filters.get("correlation_id"):
            query_clauses.append("correlation_id = ?")
            params.append(filters["correlation_id"])

        if filters.get("trace_id"):
            query_clauses.append("trace_id = ?")
            params.append(filters["trace_id"])

        if filters.get("actor_id"):
            query_clauses.append("(actor_id = ? OR acting_user_id = ?)")
            params.extend([filters["actor_id"], filters["actor_id"]])

        if filters.get("data_mode"):
            query_clauses.append("data_mode = ?")
            params.append(filters["data_mode"])

        if filters.get("start_time"):
            query_clauses.append("occurred_at >= ?")
            params.append(filters["start_time"])

        if filters.get("end_time"):
            query_clauses.append("occurred_at <= ?")
            params.append(filters["end_time"])

        where_sql = " AND ".join(query_clauses)

        with self._lock:
            conn = self._get_connection()
            try:
                # Total count query
                count_sql = f"SELECT COUNT(*) as cnt FROM audit_ledger_v3 WHERE {where_sql}"
                total_count = conn.execute(count_sql, params).fetchone()["cnt"]

                # Data query
                data_sql = f"""
                    SELECT * FROM audit_ledger_v3
                    WHERE {where_sql}
                    ORDER BY sequence_number DESC, occurred_at DESC
                    LIMIT ? OFFSET ?
                """
                rows = conn.execute(data_sql, params + [safe_limit, safe_offset]).fetchall()
                events = [self._row_to_event(r) for r in rows]
                return events, total_count
            finally:
                self._close_connection(conn)

    def get_timeline(
        self,
        tenant_id: str,
        correlation_id: Optional[str] = None,
        action_id: Optional[str] = None,
        incident_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 50
    ) -> List[LedgerEvent]:
        """Reconstructs ordered chronological timeline of correlated events."""
        safe_limit = max(1, min(limit, 100))
        query_clauses = ["tenant_id = ?"]
        params: List[Any] = [tenant_id]

        target_clauses = []
        if correlation_id:
            target_clauses.append("correlation_id = ?")
            params.append(correlation_id)
        if action_id:
            target_clauses.append("action_id = ?")
            params.append(action_id)
        if incident_id:
            target_clauses.append("incident_id = ?")
            params.append(incident_id)

        if target_clauses:
            query_clauses.append(f"({' OR '.join(target_clauses)})")

        if workspace_id and workspace_id != "*":
            query_clauses.append("workspace_id = ?")
            params.append(workspace_id)

        if session_id:
            query_clauses.append("session_id = ?")
            params.append(session_id)

        where_sql = " AND ".join(query_clauses)
        with self._lock:
            conn = self._get_connection()
            try:
                data_sql = f"""
                    SELECT * FROM audit_ledger_v3
                    WHERE {where_sql}
                    ORDER BY sequence_number ASC, occurred_at ASC
                    LIMIT ?
                """
                rows = conn.execute(data_sql, params + [safe_limit]).fetchall()
                return [self._row_to_event(r) for r in rows]
            finally:
                self._close_connection(conn)

    def get_decision_events(self, action_id: str, tenant_id: str) -> List[LedgerEvent]:
        """Retrieves all events directly associated with an action decision lifecycle."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("""
                    SELECT * FROM audit_ledger_v3
                    WHERE tenant_id = ? AND (action_id = ? OR resource_id = ?)
                    ORDER BY sequence_number ASC, occurred_at ASC
                """, (tenant_id, action_id, action_id)).fetchall()
                return [self._row_to_event(r) for r in rows]
            finally:
                self._close_connection(conn)


# Default singleton instance
default_ledger_repository = SQLiteAuditLedgerRepository()
