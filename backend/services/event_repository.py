# backend/services/event_repository.py
import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import closing

from data.schemas.event_contract import CanonicalEvent

logger = logging.getLogger(__name__)

class EventRepository:
    def __init__(self, db_path: str = "sage_events.sqlite"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with closing(self._get_conn()) as conn:
            with conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    schema_version TEXT,
                    category TEXT,
                    event_type TEXT,
                    severity TEXT,
                    lifecycle TEXT,
                    occurred_at TEXT,
                    observed_at TEXT,
                    recorded_at TEXT,
                    correlation_id TEXT,
                    causation_id TEXT,
                    provenance TEXT,
                    references_json TEXT,
                    payload_json TEXT,
                    UNIQUE(fingerprint, tenant_id)
                )
            """)
            
            # Indexes for efficient bounded querying
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_occurred ON events (tenant_id, occurred_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_fingerprint ON events (tenant_id, fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_category_type ON events (tenant_id, category, event_type)")

    def record_event(self, event: CanonicalEvent) -> CanonicalEvent:
        """
        Record a canonical event immutably.
        Deterministic deduplication: if the fingerprint + tenant_id already exists,
        returns the existing event without modifying it.
        """
        if not event.event_fingerprint:
            event.apply_fingerprint()

        try:
            with closing(self._get_conn()) as conn:
                with conn:
                    conn.execute("""
                    INSERT INTO events (
                        event_id, fingerprint, tenant_id, workspace_id, plant_id,
                        schema_version, category, event_type, severity, lifecycle,
                        occurred_at, observed_at, recorded_at,
                        correlation_id, causation_id, provenance,
                        references_json, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id, event.event_fingerprint, event.tenant_id, event.workspace_id, event.plant_id,
                    event.schema_version, event.category.value, event.event_type, event.severity.value, event.lifecycle.value,
                    event.occurred_at, event.observed_at, event.recorded_at,
                    event.correlation_id, event.causation_id, event.provenance,
                    event.references.model_dump_json(), json.dumps(event.payload)
                ))
            return event
        except sqlite3.IntegrityError:
            # Deduplication: fingerprint + tenant_id clash
            logger.info(f"Duplicate event fingerprint {event.event_fingerprint} for tenant {event.tenant_id}. Returning existing.")
            existing = self.get_event_by_fingerprint(event.tenant_id, event.event_fingerprint)
            if existing:
                return existing
            raise

    def get_event(self, tenant_id: str, event_id: str) -> Optional[CanonicalEvent]:
        with closing(self._get_conn()) as conn:
            row = conn.execute("SELECT * FROM events WHERE event_id = ? AND tenant_id = ?", (event_id, tenant_id)).fetchone()
            if row:
                return self._row_to_event(row)
        return None

    def get_event_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Optional[CanonicalEvent]:
        with closing(self._get_conn()) as conn:
            row = conn.execute("SELECT * FROM events WHERE fingerprint = ? AND tenant_id = ?", (fingerprint, tenant_id)).fetchone()
            if row:
                return self._row_to_event(row)
        return None

    def list_events(self, tenant_id: str, limit: int = 50, offset: int = 0, filters: Dict[str, Any] = None) -> List[CanonicalEvent]:
        """Bounded and tenant-isolated event query."""
        # Enforce max limit to prevent pathological queries
        limit = min(limit, 500)
        
        query = "SELECT * FROM events WHERE tenant_id = ?"
        params = [tenant_id]

        if filters:
            if "category" in filters:
                query += " AND category = ?"
                params.append(filters["category"])
            if "event_type" in filters:
                query += " AND event_type = ?"
                params.append(filters["event_type"])
            if "severity" in filters:
                query += " AND severity = ?"
                params.append(filters["severity"])
            if "workspace_id" in filters:
                query += " AND workspace_id = ?"
                params.append(filters["workspace_id"])
            if "plant_id" in filters:
                query += " AND plant_id = ?"
                params.append(filters["plant_id"])

        query += " ORDER BY occurred_at DESC, event_id ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with closing(self._get_conn()) as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(row) for row in rows]

    def _row_to_event(self, row: sqlite3.Row) -> CanonicalEvent:
        references_dict = json.loads(row["references_json"]) if row["references_json"] else {}
        payload_dict = json.loads(row["payload_json"]) if row["payload_json"] else {}
        
        event = CanonicalEvent(
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            event_fingerprint=row["fingerprint"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            category=row["category"],
            event_type=row["event_type"],
            severity=row["severity"],
            lifecycle=row["lifecycle"],
            occurred_at=row["occurred_at"],
            observed_at=row["observed_at"],
            recorded_at=row["recorded_at"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            provenance=row["provenance"],
            references=references_dict,
            payload=payload_dict
        )
        return event

# Global singleton
event_repository = EventRepository()
