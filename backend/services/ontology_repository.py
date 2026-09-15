# backend/services/ontology_repository.py
"""
SageCommand V3 — Industrial Ontology Persistent Repository
Provides thread-safe, multi-tenant scoped SQLite persistence for canonical entities,
external identifier mappings, semantic relationships, and version snapshots.
"""

import abc
import json
import sqlite3
import threading
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

try:
    from core.config import SAGE_ONTOLOGY_DB_PATH
    from data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityType,
        EntityLifecycleState,
        EntitySource,
        RelationshipType,
        RelationshipConfidence,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_ONTOLOGY_DB_PATH
    from backend.data.schemas.ontology_contract import (
        OntologyEntity,
        OntologyRelationship,
        ExternalIdMapping,
        EntityType,
        EntityLifecycleState,
        EntitySource,
        RelationshipType,
        RelationshipConfidence,
    )


class OntologyRepository(abc.ABC):
    """Abstract interface defining industrial ontology persistence operations."""

    @abc.abstractmethod
    def save_entity(self, entity: OntologyEntity, snapshot_prior: bool = True) -> OntologyEntity:
        """Persists or updates an ontology entity within tenant boundary."""
        pass

    @abc.abstractmethod
    def get_entity(self, entity_id: str, tenant_id: str) -> Optional[OntologyEntity]:
        """Retrieves an entity strictly bounded by tenant isolation."""
        pass

    @abc.abstractmethod
    def list_entities(
        self,
        tenant_id: str,
        entity_type: Optional[str] = None,
        plant_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[OntologyEntity], int]:
        """Queries entities matching tenant and optional filter criteria."""
        pass

    @abc.abstractmethod
    def save_relationship(self, rel: OntologyRelationship) -> OntologyRelationship:
        """Persists a semantic relationship edge."""
        pass

    @abc.abstractmethod
    def get_relationship(self, relationship_id: str, tenant_id: str) -> Optional[OntologyRelationship]:
        """Retrieves a relationship edge within tenant boundary."""
        pass

    @abc.abstractmethod
    def delete_relationship(self, relationship_id: str, tenant_id: str) -> bool:
        """Deletes a relationship edge."""
        pass

    @abc.abstractmethod
    def get_entity_relationships(
        self,
        entity_id: str,
        tenant_id: str,
        direction: str = "BOTH"
    ) -> List[OntologyRelationship]:
        """Retrieves relationship edges where entity is source, target, or both."""
        pass

    @abc.abstractmethod
    def save_external_mapping(self, mapping: ExternalIdMapping) -> ExternalIdMapping:
        """Saves or updates an external identifier mapping."""
        pass

    @abc.abstractmethod
    def lookup_external_id(
        self,
        tenant_id: str,
        external_system: str,
        external_id: str
    ) -> Optional[ExternalIdMapping]:
        """Looks up an external mapping by system and native ID."""
        pass

    @abc.abstractmethod
    def get_entity_external_mappings(self, tenant_id: str, entity_id: str) -> List[ExternalIdMapping]:
        """Retrieves all external ID mappings bound to a canonical entity."""
        pass

    @abc.abstractmethod
    def get_entity_versions(self, tenant_id: str, entity_id: str) -> List[Dict[str, Any]]:
        """Retrieves historical version snapshots of an entity."""
        pass


class SQLiteOntologyRepository(OntologyRepository):
    """
    Production-grade SQLite implementation of OntologyRepository.
    Enforces multi-tenant isolation, thread safety via RLock, and indexed queries.
    """

    def __init__(self, db_path: str = SAGE_ONTOLOGY_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self):
        """Initializes tables and high-performance indexes."""
        with self._lock:
            with self._get_connection() as conn:
                # 1. Canonical Entities Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ontology_entities (
                        tenant_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL DEFAULT 'workspace_default',
                        plant_id TEXT,
                        entity_type TEXT NOT NULL,
                        canonical_name TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE',
                        source TEXT NOT NULL DEFAULT 'MANUAL',
                        version INTEGER NOT NULL DEFAULT 1,
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, entity_id)
                    )
                """)

                # 2. External System Identifiers Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ontology_external_ids (
                        tenant_id TEXT NOT NULL,
                        external_system TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        confidence TEXT NOT NULL DEFAULT 'CONFIRMED',
                        metadata_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, external_system, external_id)
                    )
                """)

                # 3. Semantic Relationships Table
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ontology_relationships (
                        tenant_id TEXT NOT NULL,
                        relationship_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL DEFAULT 'workspace_default',
                        plant_id TEXT,
                        relationship_type TEXT NOT NULL,
                        source_entity_id TEXT NOT NULL,
                        target_entity_id TEXT NOT NULL,
                        attributes_json TEXT NOT NULL DEFAULT '{}',
                        valid_from TEXT,
                        valid_to TEXT,
                        source TEXT NOT NULL DEFAULT 'MANUAL',
                        confidence TEXT NOT NULL DEFAULT 'CONFIRMED',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (tenant_id, relationship_id)
                    )
                """)

                # 4. Entity Historical Version Snapshots
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ontology_entity_versions (
                        version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        version INTEGER NOT NULL,
                        snapshot_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                # Indexes for low-latency queries
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_ent_type ON ontology_entities (tenant_id, entity_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_ent_plant ON ontology_entities (tenant_id, plant_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_ext_lookup ON ontology_external_ids (tenant_id, external_system, external_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_ext_ent ON ontology_external_ids (tenant_id, entity_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_rel_src ON ontology_relationships (tenant_id, source_entity_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_rel_tgt ON ontology_relationships (tenant_id, target_entity_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_ont_rel_type ON ontology_relationships (tenant_id, relationship_type)")
                conn.commit()

    def save_entity(self, entity: OntologyEntity, snapshot_prior: bool = True) -> OntologyEntity:
        with self._lock:
            with self._get_connection() as conn:
                # Check existing entity for version snapshot
                cursor = conn.execute(
                    "SELECT * FROM ontology_entities WHERE tenant_id = ? AND entity_id = ?",
                    (entity.tenant_id, entity.entity_id)
                )
                row = cursor.fetchone()
                if row and snapshot_prior:
                    existing = self._row_to_entity(row, conn)
                    conn.execute("""
                        INSERT INTO ontology_entity_versions (tenant_id, entity_id, version, snapshot_json, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        existing.tenant_id,
                        existing.entity_id,
                        existing.version,
                        json.dumps(existing.model_dump(), default=str),
                        datetime.now(timezone.utc).isoformat()
                    ))

                # Upsert entity
                conn.execute("""
                    INSERT INTO ontology_entities (
                        tenant_id, entity_id, workspace_id, plant_id, entity_type,
                        canonical_name, display_name, status, source, version,
                        attributes_json, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, entity_id) DO UPDATE SET
                        workspace_id=excluded.workspace_id,
                        plant_id=excluded.plant_id,
                        entity_type=excluded.entity_type,
                        canonical_name=excluded.canonical_name,
                        display_name=excluded.display_name,
                        status=excluded.status,
                        source=excluded.source,
                        version=excluded.version,
                        attributes_json=excluded.attributes_json,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                """, (
                    entity.tenant_id,
                    entity.entity_id,
                    entity.workspace_id,
                    entity.plant_id,
                    entity.entity_type.value,
                    entity.canonical_name,
                    entity.display_name,
                    entity.status.value,
                    entity.source.value,
                    entity.version,
                    json.dumps(entity.attributes, default=str),
                    json.dumps(entity.metadata, default=str),
                    entity.created_at,
                    entity.updated_at
                ))

                # Synchronize external IDs
                if entity.external_ids:
                    for sys_name, ext_id in entity.external_ids.items():
                        conn.execute("""
                            INSERT INTO ontology_external_ids (
                                tenant_id, external_system, external_id, entity_id,
                                confidence, metadata_json, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(tenant_id, external_system, external_id) DO UPDATE SET
                                entity_id=excluded.entity_id,
                                updated_at=excluded.updated_at
                        """, (
                            entity.tenant_id,
                            sys_name.upper().strip(),
                            ext_id.strip(),
                            entity.entity_id,
                            RelationshipConfidence.CONFIRMED.value,
                            "{}",
                            entity.created_at,
                            entity.updated_at
                        ))
                conn.commit()
                return self.get_entity(entity.entity_id, entity.tenant_id)

    def get_entity(self, entity_id: str, tenant_id: str) -> Optional[OntologyEntity]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ontology_entities WHERE tenant_id = ? AND entity_id = ?",
                    (tenant_id, entity_id)
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_entity(row, conn)

    def list_entities(
        self,
        tenant_id: str,
        entity_type: Optional[str] = None,
        plant_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[OntologyEntity], int]:
        with self._lock:
            with self._get_connection() as conn:
                query = "SELECT * FROM ontology_entities WHERE tenant_id = ?"
                count_query = "SELECT COUNT(*) FROM ontology_entities WHERE tenant_id = ?"
                params = [tenant_id]

                if entity_type:
                    query += " AND entity_type = ?"
                    count_query += " AND entity_type = ?"
                    params.append(entity_type.upper().strip())
                if plant_id:
                    query += " AND plant_id = ?"
                    count_query += " AND plant_id = ?"
                    params.append(plant_id.strip())
                if status:
                    query += " AND status = ?"
                    count_query += " AND status = ?"
                    params.append(status.upper().strip())

                total_count = conn.execute(count_query, params).fetchone()[0]

                query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                exec_params = list(params)
                exec_params.extend([max(1, min(limit, 500)), max(0, offset)])

                cursor = conn.execute(query, exec_params)
                rows = cursor.fetchall()
                entities = [self._row_to_entity(r, conn) for r in rows]
                return entities, total_count

    def save_relationship(self, rel: OntologyRelationship) -> OntologyRelationship:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO ontology_relationships (
                        tenant_id, relationship_id, workspace_id, plant_id,
                        relationship_type, source_entity_id, target_entity_id,
                        attributes_json, valid_from, valid_to, source, confidence,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, relationship_id) DO UPDATE SET
                        relationship_type=excluded.relationship_type,
                        attributes_json=excluded.attributes_json,
                        valid_from=excluded.valid_from,
                        valid_to=excluded.valid_to,
                        source=excluded.source,
                        confidence=excluded.confidence,
                        updated_at=excluded.updated_at
                """, (
                    rel.tenant_id,
                    rel.relationship_id,
                    rel.workspace_id,
                    rel.plant_id,
                    rel.relationship_type.value,
                    rel.source_entity_id,
                    rel.target_entity_id,
                    json.dumps(rel.attributes, default=str),
                    rel.valid_from,
                    rel.valid_to,
                    rel.source.value,
                    rel.confidence.value,
                    rel.created_at,
                    rel.updated_at
                ))
                conn.commit()
                return self.get_relationship(rel.relationship_id, rel.tenant_id)

    def get_relationship(self, relationship_id: str, tenant_id: str) -> Optional[OntologyRelationship]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ontology_relationships WHERE tenant_id = ? AND relationship_id = ?",
                    (tenant_id, relationship_id)
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return self._row_to_relationship(row)

    def delete_relationship(self, relationship_id: str, tenant_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM ontology_relationships WHERE tenant_id = ? AND relationship_id = ?",
                    (tenant_id, relationship_id)
                )
                conn.commit()
                return cursor.rowcount > 0

    def get_entity_relationships(
        self,
        entity_id: str,
        tenant_id: str,
        direction: str = "BOTH"
    ) -> List[OntologyRelationship]:
        with self._lock:
            with self._get_connection() as conn:
                if direction.upper() == "OUTGOING":
                    query = "SELECT * FROM ontology_relationships WHERE tenant_id = ? AND source_entity_id = ?"
                    params = [tenant_id, entity_id]
                elif direction.upper() == "INCOMING":
                    query = "SELECT * FROM ontology_relationships WHERE tenant_id = ? AND target_entity_id = ?"
                    params = [tenant_id, entity_id]
                else:
                    query = "SELECT * FROM ontology_relationships WHERE tenant_id = ? AND (source_entity_id = ? OR target_entity_id = ?)"
                    params = [tenant_id, entity_id, entity_id]

                cursor = conn.execute(query, params)
                return [self._row_to_relationship(r) for r in cursor.fetchall()]

    def save_external_mapping(self, mapping: ExternalIdMapping) -> ExternalIdMapping:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO ontology_external_ids (
                        tenant_id, external_system, external_id, entity_id,
                        confidence, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, external_system, external_id) DO UPDATE SET
                        entity_id=excluded.entity_id,
                        confidence=excluded.confidence,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                """, (
                    mapping.tenant_id,
                    mapping.external_system.upper().strip(),
                    mapping.external_id.strip(),
                    mapping.entity_id,
                    mapping.confidence.value,
                    json.dumps(mapping.metadata, default=str),
                    mapping.created_at,
                    mapping.updated_at
                ))
                conn.commit()
                return mapping

    def lookup_external_id(
        self,
        tenant_id: str,
        external_system: str,
        external_id: str
    ) -> Optional[ExternalIdMapping]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ontology_external_ids WHERE tenant_id = ? AND external_system = ? AND external_id = ?",
                    (tenant_id, external_system.upper().strip(), external_id.strip())
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return ExternalIdMapping(
                    tenant_id=row["tenant_id"],
                    external_system=row["external_system"],
                    external_id=row["external_id"],
                    entity_id=row["entity_id"],
                    confidence=RelationshipConfidence(row["confidence"]),
                    metadata=json.loads(row["metadata_json"] or "{}"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )

    def delete_external_mapping(self, tenant_id: str, external_system: str, external_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM ontology_external_ids WHERE tenant_id = ? AND external_system = ? AND external_id = ?",
                    (tenant_id, external_system.upper().strip(), external_id.strip())
                )
                conn.commit()
                return cursor.rowcount > 0

    def get_entity_external_mappings(self, tenant_id: str, entity_id: str) -> List[ExternalIdMapping]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ontology_external_ids WHERE tenant_id = ? AND entity_id = ?",
                    (tenant_id, entity_id)
                )
                return [
                    ExternalIdMapping(
                        tenant_id=r["tenant_id"],
                        external_system=r["external_system"],
                        external_id=r["external_id"],
                        entity_id=r["entity_id"],
                        confidence=RelationshipConfidence(r["confidence"]),
                        metadata=json.loads(r["metadata_json"] or "{}"),
                        created_at=r["created_at"],
                        updated_at=r["updated_at"]
                    )
                    for r in cursor.fetchall()
                ]

    def get_entity_versions(self, tenant_id: str, entity_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ontology_entity_versions WHERE tenant_id = ? AND entity_id = ? ORDER BY version DESC",
                    (tenant_id, entity_id)
                )
                snapshots = []
                for r in cursor.fetchall():
                    snapshots.append({
                        "version": r["version"],
                        "created_at": r["created_at"],
                        "snapshot": json.loads(r["snapshot_json"] or "{}")
                    })
                return snapshots

    def _row_to_entity(self, row: sqlite3.Row, conn: sqlite3.Connection) -> OntologyEntity:
        tenant_id = row["tenant_id"]
        entity_id = row["entity_id"]

        # Fetch bound external IDs
        cursor = conn.execute(
            "SELECT external_system, external_id FROM ontology_external_ids WHERE tenant_id = ? AND entity_id = ?",
            (tenant_id, entity_id)
        )
        ext_ids = {r["external_system"]: r["external_id"] for r in cursor.fetchall()}

        return OntologyEntity(
            tenant_id=row["tenant_id"],
            entity_id=row["entity_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            entity_type=EntityType(row["entity_type"]),
            canonical_name=row["canonical_name"],
            display_name=row["display_name"],
            status=EntityLifecycleState(row["status"]),
            source=EntitySource(row["source"]),
            version=row["version"],
            external_ids=ext_ids,
            attributes=json.loads(row["attributes_json"] or "{}"),
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def _row_to_relationship(self, row: sqlite3.Row) -> OntologyRelationship:
        return OntologyRelationship(
            tenant_id=row["tenant_id"],
            relationship_id=row["relationship_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            relationship_type=RelationshipType(row["relationship_type"]),
            source_entity_id=row["source_entity_id"],
            target_entity_id=row["target_entity_id"],
            attributes=json.loads(row["attributes_json"] or "{}"),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source=EntitySource(row["source"]),
            confidence=RelationshipConfidence(row["confidence"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )


# Global singleton repository
ontology_repository = SQLiteOntologyRepository()
