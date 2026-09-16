import sqlite3
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, UTC
from core.config import SAGE_INCIDENT_DB_PATH
from data.schemas.incident_contract import (
    IncidentContract, IncidentCategory, IncidentSeverity, IncidentPriority, IncidentLifecycle,
    IncidentHistory, IncidentEventAssociation, IncidentEvidence, IncidentNote, IncidentTimelineEntry,
    EvidenceType, IncidentTimelineEntryType, EventRelationshipType
)

logger = logging.getLogger(__name__)

class IncidentRepository:
    """
    SQLite-backed repository for Incident Management (Prompt 18).
    Enforces Write-Ahead Logging (WAL) and foreign keys for stability.
    """
    def __init__(self, db_path: str = SAGE_INCIDENT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            # Incidents table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    schema_version TEXT NOT NULL,
                    incident_fingerprint TEXT UNIQUE,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    detected_at TEXT,
                    opened_at TEXT NOT NULL,
                    acknowledged_at TEXT,
                    resolved_at TEXT,
                    closed_at TEXT,
                    updated_at TEXT NOT NULL,
                    assigned_user TEXT,
                    assigned_team TEXT,
                    acknowledged_by TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inc_tenant ON incidents(tenant_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inc_status ON incidents(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inc_priority ON incidents(priority)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_inc_category ON incidents(category)")

            # History table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_history (
                    history_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    previous_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    correlation_id TEXT,
                    metadata TEXT,
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_inc ON incident_history(incident_id)")

            # Event Association table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_events (
                    incident_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    relationship_type TEXT NOT NULL,
                    added_by TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (incident_id, event_id),
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id) ON DELETE CASCADE
                )
            """)

            # Evidence table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    actor TEXT,
                    metadata TEXT,
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evid_inc ON incident_evidence(incident_id)")

            # Notes table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_notes (
                    note_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    text TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_note_inc ON incident_notes(incident_id)")

            # Timeline table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS incident_timeline (
                    entry_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    metadata TEXT,
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tln_inc ON incident_timeline(incident_id)")
            
            conn.commit()

    def _row_to_incident(self, row: sqlite3.Row) -> IncidentContract:
        return IncidentContract(
            incident_id=row["incident_id"],
            schema_version=row["schema_version"],
            incident_fingerprint=row["incident_fingerprint"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            category=IncidentCategory(row["category"]),
            severity=IncidentSeverity(row["severity"]),
            priority=IncidentPriority(row["priority"]),
            status=IncidentLifecycle(row["status"]),
            title=row["title"],
            description=row["description"],
            detected_at=row["detected_at"],
            opened_at=row["opened_at"],
            acknowledged_at=row["acknowledged_at"],
            resolved_at=row["resolved_at"],
            closed_at=row["closed_at"],
            updated_at=row["updated_at"],
            assigned_user=row["assigned_user"],
            assigned_team=row["assigned_team"],
            acknowledged_by=row["acknowledged_by"],
            version=row["version"]
        )

    def save_incident(self, incident: IncidentContract) -> IncidentContract:
        """Upserts an incident. Enforces optimistic concurrency if record exists."""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version FROM incidents WHERE incident_id = ?", (incident.incident_id,))
            row = cur.fetchone()
            
            if row:
                current_version = row["version"]
                if incident.version <= current_version:
                    raise ValueError(f"Concurrency conflict: Incident {incident.incident_id} version {incident.version} is stale (current: {current_version})")
                
                # Update
                cur.execute("""
                    UPDATE incidents SET
                        schema_version=?, incident_fingerprint=?, tenant_id=?, workspace_id=?, plant_id=?,
                        category=?, severity=?, priority=?, status=?, title=?, description=?,
                        detected_at=?, opened_at=?, acknowledged_at=?, resolved_at=?, closed_at=?, updated_at=?,
                        assigned_user=?, assigned_team=?, acknowledged_by=?, version=?
                    WHERE incident_id=? AND version=?
                """, (
                    incident.schema_version, incident.incident_fingerprint, incident.tenant_id, incident.workspace_id, incident.plant_id,
                    incident.category.value, incident.severity.value, incident.priority.value, incident.status.value, incident.title, incident.description,
                    incident.detected_at, incident.opened_at, incident.acknowledged_at, incident.resolved_at, incident.closed_at, incident.updated_at,
                    incident.assigned_user, incident.assigned_team, incident.acknowledged_by, incident.version,
                    incident.incident_id, current_version
                ))
                if cur.rowcount == 0:
                    raise ValueError("Concurrency conflict on update")
            else:
                # Insert
                try:
                    cur.execute("""
                        INSERT INTO incidents (
                            incident_id, schema_version, incident_fingerprint, tenant_id, workspace_id, plant_id,
                            category, severity, priority, status, title, description,
                            detected_at, opened_at, acknowledged_at, resolved_at, closed_at, updated_at,
                            assigned_user, assigned_team, acknowledged_by, version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        incident.incident_id, incident.schema_version, incident.incident_fingerprint, incident.tenant_id, incident.workspace_id, incident.plant_id,
                        incident.category.value, incident.severity.value, incident.priority.value, incident.status.value, incident.title, incident.description,
                        incident.detected_at, incident.opened_at, incident.acknowledged_at, incident.resolved_at, incident.closed_at, incident.updated_at,
                        incident.assigned_user, incident.assigned_team, incident.acknowledged_by, incident.version
                    ))
                except sqlite3.IntegrityError as e:
                    if "UNIQUE constraint failed: incidents.incident_fingerprint" in str(e):
                        raise ValueError(f"Incident with fingerprint {incident.incident_fingerprint} already exists.")
                    raise
            conn.commit()
            return incident

    def get_incident(self, incident_id: str, tenant_id: str) -> Optional[IncidentContract]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incidents WHERE incident_id = ? AND tenant_id = ?", (incident_id, tenant_id))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_incident(row)

    def list_incidents(self, tenant_id: str, limit: int = 100) -> List[IncidentContract]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incidents WHERE tenant_id = ? ORDER BY updated_at DESC LIMIT ?", (tenant_id, limit))
            return [self._row_to_incident(row) for row in cur.fetchall()]

    def append_history(self, history: IncidentHistory):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO incident_history (
                    history_id, incident_id, previous_state, new_state, actor, timestamp, reason, correlation_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                history.history_id, history.incident_id, history.previous_state, history.new_state, history.actor,
                history.timestamp, history.reason, history.correlation_id, json.dumps(history.metadata)
            ))
            conn.commit()

    def add_event_association(self, assoc: IncidentEventAssociation):
        with self._get_conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO incident_events (
                        incident_id, event_id, relationship_type, added_by, added_at
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    assoc.incident_id, assoc.event_id, assoc.relationship_type.value, assoc.added_by, assoc.added_at
                ))
                conn.commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE constraint failed" in str(e):
                    pass # Already associated
                else:
                    raise

    def get_event_associations(self, incident_id: str) -> List[IncidentEventAssociation]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incident_events WHERE incident_id = ?", (incident_id,))
            return [IncidentEventAssociation(
                incident_id=r["incident_id"],
                event_id=r["event_id"],
                relationship_type=EventRelationshipType(r["relationship_type"]),
                added_by=r["added_by"],
                added_at=r["added_at"]
            ) for r in cur.fetchall()]

    def add_evidence(self, evidence: IncidentEvidence):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO incident_evidence (
                    evidence_id, incident_id, evidence_type, source_id, timestamp, provenance, actor, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                evidence.evidence_id, evidence.incident_id, evidence.evidence_type.value, evidence.source_id,
                evidence.timestamp, evidence.provenance, evidence.actor, json.dumps(evidence.metadata)
            ))
            conn.commit()

    def get_evidence(self, incident_id: str) -> List[IncidentEvidence]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incident_evidence WHERE incident_id = ? ORDER BY timestamp DESC", (incident_id,))
            return [IncidentEvidence(
                evidence_id=r["evidence_id"],
                incident_id=r["incident_id"],
                evidence_type=EvidenceType(r["evidence_type"]),
                source_id=r["source_id"],
                timestamp=r["timestamp"],
                provenance=r["provenance"],
                actor=r["actor"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else {}
            ) for r in cur.fetchall()]

    def add_note(self, note: IncidentNote):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO incident_notes (
                    note_id, incident_id, author, timestamp, text, provenance
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                note.note_id, note.incident_id, note.author, note.timestamp, note.text, note.provenance
            ))
            conn.commit()

    def get_notes(self, incident_id: str) -> List[IncidentNote]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incident_notes WHERE incident_id = ? ORDER BY timestamp ASC", (incident_id,))
            return [IncidentNote(
                note_id=r["note_id"],
                incident_id=r["incident_id"],
                author=r["author"],
                timestamp=r["timestamp"],
                text=r["text"],
                provenance=r["provenance"]
            ) for r in cur.fetchall()]

    def append_timeline(self, entry: IncidentTimelineEntry):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO incident_timeline (
                    entry_id, incident_id, entry_type, actor, timestamp, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                entry.entry_id, entry.incident_id, entry.entry_type.value, entry.actor, entry.timestamp, json.dumps(entry.metadata)
            ))
            conn.commit()

    def get_timeline(self, incident_id: str) -> List[IncidentTimelineEntry]:
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM incident_timeline WHERE incident_id = ? ORDER BY timestamp ASC", (incident_id,))
            return [IncidentTimelineEntry(
                entry_id=r["entry_id"],
                incident_id=r["incident_id"],
                entry_type=IncidentTimelineEntryType(r["entry_type"]),
                actor=r["actor"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else {}
            ) for r in cur.fetchall()]
