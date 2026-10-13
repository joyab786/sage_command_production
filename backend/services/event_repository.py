# backend/services/event_repository.py
import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from contextlib import closing

from data.schemas.event_contract import CanonicalEvent

logger = logging.getLogger(__name__)

class EventRepositoryError(Exception):
    """Base exception for event repository operations."""
    pass


class EventNotFoundError(EventRepositoryError):
    """Raised when an event cannot be found."""
    pass


class EventIdempotencyConflictError(EventRepositoryError):
    """Raised when an event fingerprint is reused with differing event payload, scope, or canonical content."""
    pass


class EventScopeMismatchError(EventRepositoryError):
    """Raised when an event does not match expected scope or crosses workspace/plant boundaries."""
    pass


class LegacyEventFingerprintError(EventRepositoryError):
    """Raised when an existing event record has an ambiguous or legacy fingerprint preventing safe replay verification."""
    pass


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
            
            # Indexes for efficient bounded querying and scope isolation
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_occurred ON events (tenant_id, occurred_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_fingerprint ON events (tenant_id, fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_category_type ON events (tenant_id, category, event_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_ws_plant ON events (tenant_id, workspace_id, plant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant_scope_fp ON events (tenant_id, workspace_id, plant_id, fingerprint)")

    def record_event_ex(self, event: CanonicalEvent) -> tuple[CanonicalEvent, bool]:
        """
        Record a canonical event immutably.
        Distinguishes deterministically between:
        - Newly persisted event: returns (event, False)
        - Exact legitimate replay: returns (existing_event, True)
        - Conflicting duplicate (mismatched payload or scope): raises EventIdempotencyConflictError
        - Ambiguous/legacy duplicate: raises LegacyEventFingerprintError
        """
        if not event.event_fingerprint:
            event.apply_fingerprint()
        else:
            computed_fp = event.compute_fingerprint()
            if event.event_fingerprint != computed_fp:
                raise EventIdempotencyConflictError(
                    f"Supplied fingerprint '{event.event_fingerprint}' does not match computed canonical fingerprint '{computed_fp}'."
                )

        cat_val = event.category.value if hasattr(event.category, "value") else str(event.category)
        sev_val = event.severity.value if hasattr(event.severity, "value") else str(event.severity)
        life_val = event.lifecycle.value if hasattr(event.lifecycle, "value") else str(event.lifecycle)
        ref_json = event.references.model_dump_json() if hasattr(event.references, "model_dump_json") else json.dumps(event.references)

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
                        event.schema_version, cat_val, event.event_type, sev_val, life_val,
                        event.occurred_at, event.observed_at, event.recorded_at,
                        event.correlation_id, event.causation_id, event.provenance,
                        ref_json, json.dumps(event.payload)
                    ))
            return event, False
        except sqlite3.IntegrityError:
            # Duplicate fingerprint or primary key clash.
            # Perform strict verification against existing record.
            existing = self.get_event_by_fingerprint(event.tenant_id, event.event_fingerprint)
            if not existing:
                # Primary key clash (event_id clash) or unresolvable integrity error
                raise EventIdempotencyConflictError(f"Integrity conflict for event_id '{event.event_id}' in tenant '{event.tenant_id}'.")

            # Check for legacy or ambiguous fingerprint on existing record
            if not existing.workspace_id or not existing.plant_id:
                raise LegacyEventFingerprintError(
                    f"Existing event '{existing.event_id}' has ambiguous scope (workspace='{existing.workspace_id}', plant='{existing.plant_id}')."
                )

            if existing.compute_fingerprint() != existing.event_fingerprint:
                raise LegacyEventFingerprintError(
                    f"Existing event '{existing.event_id}' has legacy/unverified fingerprint '{existing.event_fingerprint}'."
                )

            # Check scope boundaries: workspace and plant must match
            if existing.workspace_id != event.workspace_id or existing.plant_id != event.plant_id:
                raise EventIdempotencyConflictError(
                    f"Fingerprint collision across scope: existing event '{existing.event_id}' has scope "
                    f"({existing.workspace_id}, {existing.plant_id}) but incoming event has scope ({event.workspace_id}, {event.plant_id})."
                )

            # Check canonical content equality
            existing_cat = existing.category.value if hasattr(existing.category, "value") else str(existing.category)
            if (
                existing_cat != cat_val or
                existing.event_type != event.event_type or
                existing.occurred_at != event.occurred_at or
                existing.provenance != event.provenance or
                existing.payload != event.payload or
                existing.schema_version != event.schema_version
            ):
                raise EventIdempotencyConflictError(
                    f"Fingerprint collision on '{event.event_fingerprint}': incoming event content differs from existing event '{existing.event_id}'."
                )

            # Exact legitimate replay verified!
            logger.info(f"Exact replay of canonical event '{existing.event_id}' (fingerprint {event.event_fingerprint}). Returning existing record.")
            return existing, True

    def record_event(self, event: CanonicalEvent) -> CanonicalEvent:
        """
        Record a canonical event immutably.
        Returns the event (or existing event on exact replay).
        Raises EventIdempotencyConflictError on conflicting duplicates.
        """
        event_obj, _ = self.record_event_ex(event)
        return event_obj

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

    def get_event_by_scope_and_fingerprint(
        self, tenant_id: str, workspace_id: str, plant_id: str, fingerprint: str
    ) -> Optional[CanonicalEvent]:
        with closing(self._get_conn()) as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE tenant_id = ? AND workspace_id = ? AND plant_id = ? AND fingerprint = ?",
                (tenant_id, workspace_id, plant_id, fingerprint)
            ).fetchone()
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
            workspace_id=row["workspace_id"] or "",
            plant_id=row["plant_id"] or "",
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
