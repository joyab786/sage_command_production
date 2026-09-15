# backend/services/knowledge_graph_repository.py
"""
SageCommand V3 — Operational Knowledge Graph Repository
Provides persistent, multi-tenant relational storage for operational facts,
dynamic operational edges, and historical fact versions.

Guarantees:
1. Strict tenant isolation (all tables partitioned by tenant_id).
2. Concurrency-safe transactions via threading.RLock().
3. Normalized composite indexes for rapid temporal and traversal queries.
4. Preserves immutable audit history when facts are superseded or revoked.
"""

import os
import json
import sqlite3
import threading
import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
import logging

try:
    from core.config import SAGE_KNOWLEDGE_GRAPH_DB_PATH
    from data.schemas.knowledge_graph_contract import (
        OperationalFact,
        OperationalEdge,
        FactValueType,
        FactSourceType,
        FactLifecycleState,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_KNOWLEDGE_GRAPH_DB_PATH
    from backend.data.schemas.knowledge_graph_contract import (
        OperationalFact,
        OperationalEdge,
        FactValueType,
        FactSourceType,
        FactLifecycleState,
    )

logger = logging.getLogger("sagecommand.knowledge_graph.repo")


class KnowledgeGraphRepository(ABC):
    """Abstract contract for Operational Knowledge Graph persistence."""

    @abstractmethod
    def save_fact(self, fact: OperationalFact) -> OperationalFact:
        pass

    @abstractmethod
    def get_fact(self, fact_id: str, tenant_id: str) -> Optional[OperationalFact]:
        pass

    @abstractmethod
    def get_active_facts_for_entity(
        self,
        entity_id: str,
        tenant_id: str,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        pass

    @abstractmethod
    def get_facts_at_time(
        self,
        entity_id: str,
        tenant_id: str,
        at_time: str,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        pass

    @abstractmethod
    def get_fact_history(
        self,
        entity_id: str,
        tenant_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        pass

    @abstractmethod
    def supersede_prior_facts(
        self,
        tenant_id: str,
        subject_entity_id: str,
        predicate: str,
        new_valid_from: str,
        archive_reason: str = "SUPERSEDED_BY_NEW_OBSERVATION"
    ) -> int:
        pass

    @abstractmethod
    def save_edge(self, edge: OperationalEdge) -> OperationalEdge:
        pass

    @abstractmethod
    def get_edges_for_entity(
        self,
        entity_id: str,
        tenant_id: str,
        direction: str = "BOTH",
        predicate: Optional[str] = None,
        at_time: Optional[str] = None
    ) -> List[OperationalEdge]:
        pass

    @abstractmethod
    def get_all_tenant_facts(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[OperationalFact], int]:
        pass

    @abstractmethod
    def get_all_tenant_edges(self, tenant_id: str) -> List[OperationalEdge]:
        pass


class SQLiteKnowledgeGraphRepository(KnowledgeGraphRepository):
    """
    SQLite implementation of Operational Knowledge Graph repository.
    Enforces multi-tenant indexing and ACID concurrency locking.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or SAGE_KNOWLEDGE_GRAPH_DB_PATH
        self._lock = threading.RLock()
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_tables(self):
        with self._lock, self._get_connection() as conn:
            # 1. Operational Facts Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_graph_facts (
                    fact_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    plant_id TEXT,
                    subject_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object_entity_id TEXT,
                    value_type TEXT NOT NULL,
                    value_raw TEXT NOT NULL,
                    unit TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    recorded_at TEXT NOT NULL,
                    confidence REAL,
                    status TEXT NOT NULL,
                    metadata_json TEXT
                )
            """)

            # 2. Dynamic Operational Edges Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
                    edge_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    plant_id TEXT,
                    source_entity_id TEXT NOT NULL,
                    target_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    attributes_json TEXT,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # 3. Fact Versions / Audit History Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_graph_fact_versions (
                    version_id TEXT PRIMARY KEY,
                    fact_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    subject_entity_id TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    value_raw TEXT NOT NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    status TEXT NOT NULL,
                    archived_at TEXT NOT NULL,
                    reason TEXT
                )
            """)

            # Composite Normalized Indexes for Multi-Tenant Query Acceleration
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_tenant_subj ON knowledge_graph_facts (tenant_id, subject_entity_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_tenant_obj ON knowledge_graph_facts (tenant_id, object_entity_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_tenant_pred ON knowledge_graph_facts (tenant_id, predicate, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_tenant_validity ON knowledge_graph_facts (tenant_id, valid_from, valid_to)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_facts_tenant_observed ON knowledge_graph_facts (tenant_id, observed_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_tenant_src ON knowledge_graph_edges (tenant_id, source_entity_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_tenant_tgt ON knowledge_graph_edges (tenant_id, target_entity_id, status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_versions_tenant_fact ON knowledge_graph_fact_versions (tenant_id, fact_id)")
            conn.commit()

    def _row_to_fact(self, row: sqlite3.Row) -> OperationalFact:
        raw_val = row["value_raw"]
        vtype = row["value_type"]
        val: Any = raw_val
        if vtype == FactValueType.FLOAT.value:
            try:
                val = float(raw_val)
            except ValueError:
                pass
        elif vtype == FactValueType.INTEGER.value:
            try:
                val = int(raw_val)
            except ValueError:
                pass
        elif vtype == FactValueType.BOOLEAN.value:
            val = (raw_val.lower() in ("true", "1"))
        elif vtype == FactValueType.JSON.value:
            try:
                val = json.loads(raw_val)
            except Exception:
                pass

        meta = {}
        if row["metadata_json"]:
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                meta = {}

        return OperationalFact(
            fact_id=row["fact_id"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            subject_entity_id=row["subject_entity_id"],
            predicate=row["predicate"],
            object_entity_id=row["object_entity_id"],
            value_type=FactValueType(vtype),
            value=val,
            unit=row["unit"],
            source_type=FactSourceType(row["source_type"]),
            source_id=row["source_id"],
            observed_at=row["observed_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            recorded_at=row["recorded_at"],
            confidence=row["confidence"],
            status=FactLifecycleState(row["status"]),
            metadata=meta
        )

    def _row_to_edge(self, row: sqlite3.Row) -> OperationalEdge:
        attrs = {}
        if row["attributes_json"]:
            try:
                attrs = json.loads(row["attributes_json"])
            except Exception:
                attrs = {}

        return OperationalEdge(
            edge_id=row["edge_id"],
            tenant_id=row["tenant_id"],
            workspace_id=row["workspace_id"],
            plant_id=row["plant_id"],
            source_entity_id=row["source_entity_id"],
            target_entity_id=row["target_entity_id"],
            predicate=row["predicate"],
            attributes=attrs,
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            source_type=FactSourceType(row["source_type"]),
            source_id=row["source_id"],
            status=FactLifecycleState(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )

    def save_fact(self, fact: OperationalFact) -> OperationalFact:
        val_str = json.dumps(fact.value) if isinstance(fact.value, (dict, list)) else str(fact.value)
        meta_str = json.dumps(fact.metadata or {})

        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO knowledge_graph_facts (
                    fact_id, tenant_id, workspace_id, plant_id,
                    subject_entity_id, predicate, object_entity_id,
                    value_type, value_raw, unit, source_type, source_id,
                    observed_at, valid_from, valid_to, recorded_at,
                    confidence, status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fact.fact_id, fact.tenant_id, fact.workspace_id, fact.plant_id,
                fact.subject_entity_id, fact.predicate, fact.object_entity_id,
                fact.value_type.value, val_str, fact.unit,
                fact.source_type.value, fact.source_id,
                fact.observed_at, fact.valid_from, fact.valid_to,
                fact.recorded_at, fact.confidence, fact.status.value, meta_str
            ))
            conn.commit()
        return fact

    def get_fact(self, fact_id: str, tenant_id: str) -> Optional[OperationalFact]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM knowledge_graph_facts WHERE fact_id = ? AND tenant_id = ?",
                (fact_id.strip(), tenant_id.strip())
            )
            row = cursor.fetchone()
            return self._row_to_fact(row) if row else None

    def get_active_facts_for_entity(
        self,
        entity_id: str,
        tenant_id: str,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        with self._lock, self._get_connection() as conn:
            query = """
                SELECT * FROM knowledge_graph_facts
                WHERE tenant_id = ? AND subject_entity_id = ? AND status = ?
            """
            params: List[Any] = [tenant_id.strip(), entity_id.strip(), FactLifecycleState.ACTIVE.value]
            if predicate:
                query += " AND predicate = ?"
                params.append(predicate.strip().upper())
            query += " ORDER BY observed_at DESC"

            cursor = conn.execute(query, params)
            return [self._row_to_fact(r) for r in cursor.fetchall()]

    def get_facts_at_time(
        self,
        entity_id: str,
        tenant_id: str,
        at_time: str,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        """Returns facts that were valid at point-in-time at_time."""
        with self._lock, self._get_connection() as conn:
            query = """
                SELECT * FROM knowledge_graph_facts
                WHERE tenant_id = ? AND subject_entity_id = ?
                  AND valid_from <= ?
                  AND (valid_to IS NULL OR valid_to > ?)
            """
            params: List[Any] = [tenant_id.strip(), entity_id.strip(), at_time, at_time]
            if predicate:
                query += " AND predicate = ?"
                params.append(predicate.strip().upper())
            query += " ORDER BY observed_at DESC"

            cursor = conn.execute(query, params)
            return [self._row_to_fact(r) for r in cursor.fetchall()]

    def get_fact_history(
        self,
        entity_id: str,
        tenant_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        predicate: Optional[str] = None
    ) -> List[OperationalFact]:
        with self._lock, self._get_connection() as conn:
            query = "SELECT * FROM knowledge_graph_facts WHERE tenant_id = ? AND subject_entity_id = ?"
            params: List[Any] = [tenant_id.strip(), entity_id.strip()]

            if start_time:
                query += " AND observed_at >= ?"
                params.append(start_time)
            if end_time:
                query += " AND observed_at <= ?"
                params.append(end_time)
            if predicate:
                query += " AND predicate = ?"
                params.append(predicate.strip().upper())

            query += " ORDER BY observed_at DESC LIMIT 200"
            cursor = conn.execute(query, params)
            return [self._row_to_fact(r) for r in cursor.fetchall()]

    def supersede_prior_facts(
        self,
        tenant_id: str,
        subject_entity_id: str,
        predicate: str,
        new_valid_from: str,
        archive_reason: str = "SUPERSEDED_BY_NEW_OBSERVATION"
    ) -> int:
        """
        Transitions prior ACTIVE facts with matching (tenant, subject, predicate)
        to SUPERSEDED, sets valid_to = new_valid_from, and writes a version record.
        """
        with self._lock, self._get_connection() as conn:
            # Find current active facts
            cursor = conn.execute("""
                SELECT * FROM knowledge_graph_facts
                WHERE tenant_id = ? AND subject_entity_id = ? AND predicate = ? AND status = ?
            """, (tenant_id.strip(), subject_entity_id.strip(), predicate.strip().upper(), FactLifecycleState.ACTIVE.value))
            active_rows = cursor.fetchall()

            count = 0
            now_str = datetime.now(timezone.utc).isoformat()
            for row in active_rows:
                # 1. Snapshot into versions table
                conn.execute("""
                    INSERT INTO knowledge_graph_fact_versions (
                        version_id, fact_id, tenant_id, subject_entity_id,
                        predicate, value_raw, valid_from, valid_to,
                        status, archived_at, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"v_{uuid.uuid4().hex[:12]}", row["fact_id"], tenant_id.strip(),
                    row["subject_entity_id"], row["predicate"], row["value_raw"],
                    row["valid_from"], new_valid_from, FactLifecycleState.SUPERSEDED.value,
                    now_str, archive_reason
                ))

                # 2. Update existing fact status
                conn.execute("""
                    UPDATE knowledge_graph_facts
                    SET status = ?, valid_to = ?
                    WHERE fact_id = ?
                """, (FactLifecycleState.SUPERSEDED.value, new_valid_from, row["fact_id"]))
                count += 1

            conn.commit()
            return count

    def save_edge(self, edge: OperationalEdge) -> OperationalEdge:
        attrs_str = json.dumps(edge.attributes or {})
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO knowledge_graph_edges (
                    edge_id, tenant_id, workspace_id, plant_id,
                    source_entity_id, target_entity_id, predicate,
                    attributes_json, valid_from, valid_to,
                    source_type, source_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                edge.edge_id, edge.tenant_id, edge.workspace_id, edge.plant_id,
                edge.source_entity_id, edge.target_entity_id, edge.predicate,
                attrs_str, edge.valid_from, edge.valid_to,
                edge.source_type.value, edge.source_id, edge.status.value,
                edge.created_at, edge.updated_at
            ))
            conn.commit()
        return edge

    def get_edges_for_entity(
        self,
        entity_id: str,
        tenant_id: str,
        direction: str = "BOTH",
        predicate: Optional[str] = None,
        at_time: Optional[str] = None
    ) -> List[OperationalEdge]:
        with self._lock, self._get_connection() as conn:
            direction = direction.upper().strip()
            query_conds = ["tenant_id = ?"]
            params: List[Any] = [tenant_id.strip()]

            if direction == "OUTGOING":
                query_conds.append("source_entity_id = ?")
                params.append(entity_id.strip())
            elif direction == "INCOMING":
                query_conds.append("target_entity_id = ?")
                params.append(entity_id.strip())
            else:  # BOTH
                query_conds.append("(source_entity_id = ? OR target_entity_id = ?)")
                params.extend([entity_id.strip(), entity_id.strip()])

            if predicate:
                query_conds.append("predicate = ?")
                params.append(predicate.strip().upper())

            if at_time:
                query_conds.append("valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)")
                params.extend([at_time, at_time])
            else:
                query_conds.append("status = ?")
                params.append(FactLifecycleState.ACTIVE.value)

            sql = f"SELECT * FROM knowledge_graph_edges WHERE {' AND '.join(query_conds)} LIMIT 500"
            cursor = conn.execute(sql, params)
            return [self._row_to_edge(r) for r in cursor.fetchall()]

    def get_all_tenant_facts(
        self,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[OperationalFact], int]:
        with self._lock, self._get_connection() as conn:
            c_cursor = conn.execute(
                "SELECT COUNT(*) FROM knowledge_graph_facts WHERE tenant_id = ?",
                (tenant_id.strip(),)
            )
            total = c_cursor.fetchone()[0]

            cursor = conn.execute("""
                SELECT * FROM knowledge_graph_facts
                WHERE tenant_id = ?
                ORDER BY observed_at DESC LIMIT ? OFFSET ?
            """, (tenant_id.strip(), limit, offset))
            return [self._row_to_fact(r) for r in cursor.fetchall()], total

    def get_all_tenant_edges(self, tenant_id: str) -> List[OperationalEdge]:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM knowledge_graph_edges WHERE tenant_id = ? AND status = ? LIMIT 500",
                (tenant_id.strip(), FactLifecycleState.ACTIVE.value)
            )
            return [self._row_to_edge(r) for r in cursor.fetchall()]


# Module-level default repository singleton
knowledge_graph_repository = SQLiteKnowledgeGraphRepository()
