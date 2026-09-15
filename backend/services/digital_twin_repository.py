# backend/services/digital_twin_repository.py
"""
SageCommand V3 — Digital Twin Repository (Prompt 13)
SQLite-backed persistence for Digital Twin state, versioning, snapshots, and scenarios.
All queries are partitioned by tenant_id for strict tenant isolation.

Cardinal Invariant:
The repository is a pure data-access layer. It never performs physical actuation,
operational mutations, or bypasses the Execution Gateway.
"""

import os
import json
import sqlite3
import threading
import uuid
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

try:
    from core.config import SAGE_DIGITAL_TWIN_DB_PATH
except ModuleNotFoundError:
    from backend.core.config import SAGE_DIGITAL_TWIN_DB_PATH


class DigitalTwinRepository:
    """
    Thread-safe SQLite repository for Digital Twin persistence.
    Tables: twin_states, twin_state_properties, twin_state_versions,
            twin_snapshots, twin_snapshot_entries, twin_scenarios, twin_scenario_overrides
    """

    def __init__(self, db_path: str = SAGE_DIGITAL_TWIN_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS twin_states (
                        twin_id TEXT PRIMARY KEY,
                        entity_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT DEFAULT 'workspace_default',
                        plant_id TEXT,
                        entity_type TEXT NOT NULL,
                        state_version INTEGER DEFAULT 1,
                        observed_at TEXT NOT NULL,
                        effective_at TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        freshness TEXT DEFAULT 'UNKNOWN',
                        conflict_state TEXT DEFAULT 'NONE',
                        metadata TEXT DEFAULT '{}'
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_states_tenant
                        ON twin_states(tenant_id);
                    CREATE INDEX IF NOT EXISTS idx_twin_states_entity
                        ON twin_states(tenant_id, entity_id);
                    CREATE INDEX IF NOT EXISTS idx_twin_states_type
                        ON twin_states(tenant_id, entity_type);

                    CREATE TABLE IF NOT EXISTS twin_state_properties (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        twin_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        property_name TEXT NOT NULL,
                        value_type TEXT DEFAULT 'STRING',
                        value TEXT,
                        unit TEXT,
                        classification TEXT DEFAULT 'OBSERVED',
                        confidence TEXT DEFAULT 'UNKNOWN',
                        source_type TEXT DEFAULT 'SYSTEM',
                        source_id TEXT DEFAULT 'system',
                        observed_at TEXT NOT NULL,
                        effective_at TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        metadata TEXT DEFAULT '{}',
                        FOREIGN KEY (twin_id) REFERENCES twin_states(twin_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_props_twin
                        ON twin_state_properties(twin_id);
                    CREATE INDEX IF NOT EXISTS idx_twin_props_tenant
                        ON twin_state_properties(tenant_id);

                    CREATE TABLE IF NOT EXISTS twin_state_versions (
                        version_id TEXT PRIMARY KEY,
                        twin_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        state_version INTEGER NOT NULL,
                        properties_json TEXT DEFAULT '[]',
                        effective_at TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        classification TEXT DEFAULT 'OBSERVED',
                        conflict_state TEXT DEFAULT 'NONE',
                        FOREIGN KEY (twin_id) REFERENCES twin_states(twin_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_versions_entity
                        ON twin_state_versions(tenant_id, entity_id);
                    CREATE INDEX IF NOT EXISTS idx_twin_versions_effective
                        ON twin_state_versions(tenant_id, entity_id, effective_at);
                    CREATE INDEX IF NOT EXISTS idx_twin_versions_version
                        ON twin_state_versions(tenant_id, twin_id, state_version);

                    CREATE TABLE IF NOT EXISTS twin_snapshots (
                        snapshot_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT DEFAULT 'workspace_default',
                        plant_id TEXT,
                        snapshot_timestamp TEXT NOT NULL,
                        entity_count INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        created_by TEXT DEFAULT 'system',
                        description TEXT,
                        metadata TEXT DEFAULT '{}',
                        is_immutable INTEGER DEFAULT 1
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_snapshots_tenant
                        ON twin_snapshots(tenant_id);

                    CREATE TABLE IF NOT EXISTS twin_snapshot_entries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        snapshot_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        entity_type TEXT NOT NULL,
                        state_version INTEGER,
                        properties_json TEXT DEFAULT '[]',
                        observed_at TEXT,
                        effective_at TEXT,
                        freshness TEXT DEFAULT 'UNKNOWN',
                        conflict_state TEXT DEFAULT 'NONE',
                        FOREIGN KEY (snapshot_id) REFERENCES twin_snapshots(snapshot_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_snap_entries_snapshot
                        ON twin_snapshot_entries(snapshot_id);

                    CREATE TABLE IF NOT EXISTS twin_scenarios (
                        scenario_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT DEFAULT 'workspace_default',
                        base_snapshot_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        created_at TEXT NOT NULL,
                        created_by TEXT DEFAULT 'system',
                        metadata TEXT DEFAULT '{}',
                        FOREIGN KEY (base_snapshot_id) REFERENCES twin_snapshots(snapshot_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_scenarios_tenant
                        ON twin_scenarios(tenant_id);

                    CREATE TABLE IF NOT EXISTS twin_scenario_overrides (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        scenario_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        property_name TEXT NOT NULL,
                        value_type TEXT DEFAULT 'STRING',
                        value TEXT,
                        unit TEXT,
                        FOREIGN KEY (scenario_id) REFERENCES twin_scenarios(scenario_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_twin_overrides_scenario
                        ON twin_scenario_overrides(scenario_id);
                """)
                conn.commit()
            finally:
                conn.close()

    # =========================================================================
    # TWIN STATE CRUD
    # =========================================================================

    def upsert_twin_state(
        self,
        twin_id: str,
        entity_id: str,
        tenant_id: str,
        workspace_id: str,
        plant_id: Optional[str],
        entity_type: str,
        state_version: int,
        observed_at: str,
        effective_at: str,
        recorded_at: str,
        freshness: str,
        conflict_state: str,
        metadata: Dict[str, Any],
        properties: List[Dict[str, Any]],
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO twin_states
                        (twin_id, entity_id, tenant_id, workspace_id, plant_id,
                         entity_type, state_version, observed_at, effective_at,
                         recorded_at, freshness, conflict_state, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(twin_id) DO UPDATE SET
                        state_version = excluded.state_version,
                        observed_at = excluded.observed_at,
                        effective_at = excluded.effective_at,
                        recorded_at = excluded.recorded_at,
                        freshness = excluded.freshness,
                        conflict_state = excluded.conflict_state,
                        metadata = excluded.metadata
                """, (
                    twin_id, entity_id, tenant_id, workspace_id, plant_id,
                    entity_type, state_version, observed_at, effective_at,
                    recorded_at, freshness, conflict_state, json.dumps(metadata)
                ))

                # Replace current properties
                conn.execute("DELETE FROM twin_state_properties WHERE twin_id = ? AND tenant_id = ?",
                             (twin_id, tenant_id))
                for prop in properties:
                    conn.execute("""
                        INSERT INTO twin_state_properties
                            (twin_id, tenant_id, property_name, value_type, value, unit,
                             classification, confidence, source_type, source_id,
                             observed_at, effective_at, recorded_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        twin_id, tenant_id,
                        prop.get("property_name", ""),
                        prop.get("value_type", "STRING"),
                        json.dumps(prop.get("value")) if not isinstance(prop.get("value"), str) else prop.get("value"),
                        prop.get("unit"),
                        prop.get("classification", "OBSERVED"),
                        prop.get("confidence", "UNKNOWN"),
                        prop.get("source_type", "SYSTEM"),
                        prop.get("source_id", "system"),
                        prop.get("observed_at", observed_at),
                        prop.get("effective_at", effective_at),
                        prop.get("recorded_at", recorded_at),
                        json.dumps(prop.get("metadata", {})),
                    ))
                conn.commit()
            finally:
                conn.close()

    def get_twin_state(self, tenant_id: str, entity_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM twin_states WHERE tenant_id = ? AND entity_id = ?",
                    (tenant_id, entity_id)
                ).fetchone()
                if not row:
                    return None
                twin = dict(row)
                twin["metadata"] = json.loads(twin.get("metadata", "{}"))

                props = conn.execute(
                    "SELECT * FROM twin_state_properties WHERE twin_id = ? AND tenant_id = ?",
                    (twin["twin_id"], tenant_id)
                ).fetchall()
                twin["properties"] = [self._parse_property(dict(p)) for p in props]
                return twin
            finally:
                conn.close()

    def list_twin_states(self, tenant_id: str, entity_type: Optional[str] = None,
                         limit: int = 100, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        with self._lock:
            conn = self._get_connection()
            try:
                base_where = "WHERE tenant_id = ?"
                params: list = [tenant_id]
                if entity_type:
                    base_where += " AND entity_type = ?"
                    params.append(entity_type)

                count = conn.execute(
                    f"SELECT COUNT(*) FROM twin_states {base_where}", params
                ).fetchone()[0]

                rows = conn.execute(
                    f"SELECT * FROM twin_states {base_where} ORDER BY entity_id LIMIT ? OFFSET ?",
                    params + [limit, offset]
                ).fetchall()

                results = []
                for row in rows:
                    twin = dict(row)
                    twin["metadata"] = json.loads(twin.get("metadata", "{}"))
                    props = conn.execute(
                        "SELECT * FROM twin_state_properties WHERE twin_id = ? AND tenant_id = ?",
                        (twin["twin_id"], tenant_id)
                    ).fetchall()
                    twin["properties"] = [self._parse_property(dict(p)) for p in props]
                    results.append(twin)
                return results, count
            finally:
                conn.close()

    # =========================================================================
    # STATE VERSIONS
    # =========================================================================

    def insert_state_version(
        self, version_id: str, twin_id: str, entity_id: str, tenant_id: str,
        state_version: int, properties_json: str, effective_at: str,
        recorded_at: str, classification: str, conflict_state: str
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO twin_state_versions
                        (version_id, twin_id, entity_id, tenant_id, state_version,
                         properties_json, effective_at, recorded_at, classification, conflict_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (version_id, twin_id, entity_id, tenant_id, state_version,
                      properties_json, effective_at, recorded_at, classification, conflict_state))
                conn.commit()
            finally:
                conn.close()

    def get_state_history(self, tenant_id: str, entity_id: str,
                          limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute("""
                    SELECT * FROM twin_state_versions
                    WHERE tenant_id = ? AND entity_id = ?
                    ORDER BY state_version DESC
                    LIMIT ?
                """, (tenant_id, entity_id, limit)).fetchall()
                return [self._parse_version(dict(r)) for r in rows]
            finally:
                conn.close()

    def get_state_at_time(self, tenant_id: str, entity_id: str,
                          timestamp: str) -> Optional[Dict[str, Any]]:
        """Get the latest state version where effective_at <= timestamp."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute("""
                    SELECT * FROM twin_state_versions
                    WHERE tenant_id = ? AND entity_id = ? AND effective_at <= ?
                    ORDER BY state_version DESC
                    LIMIT 1
                """, (tenant_id, entity_id, timestamp)).fetchone()
                if not row:
                    return None
                return self._parse_version(dict(row))
            finally:
                conn.close()

    def get_current_version(self, tenant_id: str, entity_id: str) -> int:
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT MAX(state_version) FROM twin_state_versions WHERE tenant_id = ? AND entity_id = ?",
                    (tenant_id, entity_id)
                ).fetchone()
                return row[0] if row and row[0] else 0
            finally:
                conn.close()

    # =========================================================================
    # SNAPSHOTS
    # =========================================================================

    def create_snapshot(
        self, snapshot_id: str, tenant_id: str, workspace_id: str,
        plant_id: Optional[str], snapshot_timestamp: str, entity_count: int,
        created_at: str, created_by: str, description: Optional[str],
        metadata: Dict[str, Any], entries: List[Dict[str, Any]]
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO twin_snapshots
                        (snapshot_id, tenant_id, workspace_id, plant_id, snapshot_timestamp,
                         entity_count, created_at, created_by, description, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (snapshot_id, tenant_id, workspace_id, plant_id, snapshot_timestamp,
                      entity_count, created_at, created_by, description, json.dumps(metadata)))

                for entry in entries:
                    conn.execute("""
                        INSERT INTO twin_snapshot_entries
                            (snapshot_id, tenant_id, entity_id, entity_type, state_version,
                             properties_json, observed_at, effective_at, freshness, conflict_state)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        snapshot_id, tenant_id,
                        entry["entity_id"], entry["entity_type"], entry.get("state_version"),
                        json.dumps(entry.get("properties", [])),
                        entry.get("observed_at"), entry.get("effective_at"),
                        entry.get("freshness", "UNKNOWN"), entry.get("conflict_state", "NONE"),
                    ))
                conn.commit()
            finally:
                conn.close()

    def get_snapshot(self, tenant_id: str, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM twin_snapshots WHERE tenant_id = ? AND snapshot_id = ?",
                    (tenant_id, snapshot_id)
                ).fetchone()
                if not row:
                    return None
                snap = dict(row)
                snap["metadata"] = json.loads(snap.get("metadata", "{}"))

                entries = conn.execute(
                    "SELECT * FROM twin_snapshot_entries WHERE snapshot_id = ? AND tenant_id = ?",
                    (snapshot_id, tenant_id)
                ).fetchall()
                snap["entries"] = [self._parse_snapshot_entry(dict(e)) for e in entries]
                return snap
            finally:
                conn.close()

    # =========================================================================
    # SCENARIOS
    # =========================================================================

    def create_scenario(
        self, scenario_id: str, tenant_id: str, workspace_id: str,
        base_snapshot_id: str, name: str, description: Optional[str],
        created_at: str, created_by: str, metadata: Dict[str, Any],
        overrides: List[Dict[str, Any]]
    ) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO twin_scenarios
                        (scenario_id, tenant_id, workspace_id, base_snapshot_id,
                         name, description, created_at, created_by, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (scenario_id, tenant_id, workspace_id, base_snapshot_id,
                      name, description, created_at, created_by, json.dumps(metadata)))

                for ovr in overrides:
                    conn.execute("""
                        INSERT INTO twin_scenario_overrides
                            (scenario_id, tenant_id, entity_id, property_name, value_type, value, unit)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        scenario_id, tenant_id,
                        ovr["entity_id"], ovr["property_name"],
                        ovr.get("value_type", "STRING"),
                        json.dumps(ovr["value"]) if not isinstance(ovr.get("value"), str) else ovr["value"],
                        ovr.get("unit"),
                    ))
                conn.commit()
            finally:
                conn.close()

    def get_scenario(self, tenant_id: str, scenario_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM twin_scenarios WHERE tenant_id = ? AND scenario_id = ?",
                    (tenant_id, scenario_id)
                ).fetchone()
                if not row:
                    return None
                scenario = dict(row)
                scenario["metadata"] = json.loads(scenario.get("metadata", "{}"))

                overrides = conn.execute(
                    "SELECT * FROM twin_scenario_overrides WHERE scenario_id = ? AND tenant_id = ?",
                    (scenario_id, tenant_id)
                ).fetchall()
                scenario["overrides"] = [dict(o) for o in overrides]
                return scenario
            finally:
                conn.close()

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _parse_property(self, row: Dict[str, Any]) -> Dict[str, Any]:
        row["metadata"] = json.loads(row.get("metadata", "{}"))
        # Try to parse JSON-encoded values
        val = row.get("value", "")
        if row.get("value_type") in ("INTEGER", "FLOAT", "BOOLEAN", "JSON"):
            try:
                row["value"] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
        return row

    def _parse_version(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row["properties"] = json.loads(row.get("properties_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            row["properties"] = []
        return row

    def _parse_snapshot_entry(self, row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row["properties"] = json.loads(row.get("properties_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            row["properties"] = []
        return row

    def get_all_entity_ids(self, tenant_id: str) -> List[str]:
        """Get all entity IDs with twin state for a tenant."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT entity_id FROM twin_states WHERE tenant_id = ?",
                    (tenant_id,)
                ).fetchall()
                return [r["entity_id"] for r in rows]
            finally:
                conn.close()


# Module-level singleton
digital_twin_repository = DigitalTwinRepository()
