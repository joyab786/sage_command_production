import sqlite3
import json
import threading
from typing import Optional, List
from datetime import datetime, UTC

try:
    from data.schemas.blast_radius_contract import (
        BlastRadiusAnalysis,
        ImpactNode,
        ImpactPath,
        ImpactScope,
        ImpactEvidence,
        BlastRadiusAnalysisStatus,
        ImpactClassification,
        ConfidenceLevel
    )
    from core.config import SAGE_BLAST_RADIUS_DB_PATH
except ModuleNotFoundError:
    from backend.data.schemas.blast_radius_contract import (
        BlastRadiusAnalysis,
        ImpactNode,
        ImpactPath,
        ImpactScope,
        ImpactEvidence,
        BlastRadiusAnalysisStatus,
        ImpactClassification,
        ConfidenceLevel
    )
    from backend.core.config import SAGE_BLAST_RADIUS_DB_PATH


class BlastRadiusRepository:
    """
    Dedicated SQLite persistence repository for Blast-Radius Intelligence.
    Uses WAL mode and enforces tenant isolation.
    """

    def __init__(self, db_path: str = SAGE_BLAST_RADIUS_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                # Enable WAL mode for concurrency
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                
                with conn:
                    # Analyses Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS blast_radius_analyses (
                            analysis_id TEXT PRIMARY KEY,
                            tenant_id TEXT NOT NULL,
                            workspace_id TEXT,
                            plant_id TEXT,
                            source_entity_id TEXT,
                            source_entity_type TEXT,
                            source_incident_id TEXT,
                            source_anomaly_id TEXT,
                            source_event_id TEXT,
                            analysis_status TEXT NOT NULL,
                            analysis_timestamp TEXT NOT NULL,
                            snapshot_timestamp TEXT NOT NULL,
                            ontology_version TEXT,
                            knowledge_graph_version TEXT,
                            digital_twin_snapshot_id TEXT,
                            method_version TEXT,
                            input_fingerprint TEXT,
                            confidence TEXT,
                            uncertainty TEXT,
                            schema_version TEXT
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_br_analysis_tenant ON blast_radius_analyses(tenant_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_br_analysis_fingerprint ON blast_radius_analyses(input_fingerprint)")
                    
                    # Scopes Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS blast_radius_scopes (
                            analysis_id TEXT PRIMARY KEY,
                            total_assets INTEGER,
                            total_processes INTEGER,
                            total_production_areas INTEGER,
                            total_workspaces INTEGER,
                            total_plants INTEGER,
                            total_upstream_dependencies INTEGER,
                            total_downstream_dependencies INTEGER,
                            related_incidents INTEGER,
                            related_anomalies INTEGER,
                            FOREIGN KEY(analysis_id) REFERENCES blast_radius_analyses(analysis_id) ON DELETE CASCADE
                        )
                    """)
                    
                    # Nodes Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS blast_radius_nodes (
                            entity_id TEXT NOT NULL,
                            analysis_id TEXT NOT NULL,
                            tenant_id TEXT NOT NULL,
                            entity_type TEXT NOT NULL,
                            impact_classification TEXT NOT NULL,
                            impact_score REAL,
                            confidence TEXT,
                            distance INTEGER,
                            temporal_validity_start TEXT,
                            temporal_validity_end TEXT,
                            evidence_refs_json TEXT,
                            PRIMARY KEY (analysis_id, entity_id),
                            FOREIGN KEY(analysis_id) REFERENCES blast_radius_analyses(analysis_id) ON DELETE CASCADE
                        )
                    """)
                    
                    # Paths Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS blast_radius_paths (
                            path_id TEXT PRIMARY KEY,
                            analysis_id TEXT NOT NULL,
                            source_node_id TEXT NOT NULL,
                            target_node_id TEXT NOT NULL,
                            ordered_path_json TEXT NOT NULL,
                            relationship_types_json TEXT NOT NULL,
                            traversal_depth INTEGER,
                            confidence TEXT,
                            evidence_refs_json TEXT,
                            FOREIGN KEY(analysis_id) REFERENCES blast_radius_analyses(analysis_id) ON DELETE CASCADE
                        )
                    """)
            finally:
                conn.close()

    def get_analysis_by_fingerprint(self, fingerprint: str) -> Optional[BlastRadiusAnalysis]:
        """Check for identical previous runs to deduplicate computation."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM blast_radius_analyses WHERE input_fingerprint = ? AND analysis_status = 'COMPLETED'",
                    (fingerprint,)
                ).fetchone()
                if row:
                    return self.get_analysis(row["analysis_id"], row["tenant_id"])
                return None
            finally:
                conn.close()

    def save_analysis(self, analysis: BlastRadiusAnalysis):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # 1. Save or Update Analysis Record
                    conn.execute("""
                        INSERT INTO blast_radius_analyses (
                            analysis_id, tenant_id, workspace_id, plant_id, 
                            source_entity_id, source_entity_type, source_incident_id, 
                            source_anomaly_id, source_event_id, analysis_status, 
                            analysis_timestamp, snapshot_timestamp, ontology_version, 
                            knowledge_graph_version, digital_twin_snapshot_id, method_version, 
                            input_fingerprint, confidence, uncertainty, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(analysis_id) DO UPDATE SET
                            analysis_status=excluded.analysis_status,
                            confidence=excluded.confidence,
                            uncertainty=excluded.uncertainty
                    """, (
                        analysis.analysis_id, analysis.tenant_id, analysis.workspace_id, analysis.plant_id,
                        analysis.source_entity_id, analysis.source_entity_type, analysis.source_incident_id,
                        analysis.source_anomaly_id, analysis.source_event_id, analysis.analysis_status.value,
                        analysis.analysis_timestamp, analysis.snapshot_timestamp, analysis.ontology_version,
                        analysis.knowledge_graph_version, analysis.digital_twin_snapshot_id, analysis.method_version,
                        analysis.input_fingerprint, analysis.confidence.value, analysis.uncertainty, analysis.schema_version
                    ))
                    
                    # 2. Save Scope
                    if analysis.scope:
                        conn.execute("""
                            INSERT INTO blast_radius_scopes (
                                analysis_id, total_assets, total_processes, total_production_areas,
                                total_workspaces, total_plants, total_upstream_dependencies,
                                total_downstream_dependencies, related_incidents, related_anomalies
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(analysis_id) DO UPDATE SET
                                total_assets=excluded.total_assets, total_processes=excluded.total_processes,
                                total_production_areas=excluded.total_production_areas, total_workspaces=excluded.total_workspaces,
                                total_plants=excluded.total_plants, total_upstream_dependencies=excluded.total_upstream_dependencies,
                                total_downstream_dependencies=excluded.total_downstream_dependencies,
                                related_incidents=excluded.related_incidents, related_anomalies=excluded.related_anomalies
                        """, (
                            analysis.analysis_id, analysis.scope.total_assets, analysis.scope.total_processes,
                            analysis.scope.total_production_areas, analysis.scope.total_workspaces,
                            analysis.scope.total_plants, analysis.scope.total_upstream_dependencies,
                            analysis.scope.total_downstream_dependencies, analysis.scope.related_incidents,
                            analysis.scope.related_anomalies
                        ))

                    # 3. Save Nodes
                    # Clear existing nodes for update
                    conn.execute("DELETE FROM blast_radius_nodes WHERE analysis_id = ?", (analysis.analysis_id,))
                    for node in analysis.nodes:
                        conn.execute("""
                            INSERT INTO blast_radius_nodes (
                                entity_id, analysis_id, tenant_id, entity_type, impact_classification,
                                impact_score, confidence, distance, temporal_validity_start, 
                                temporal_validity_end, evidence_refs_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            node.entity_id, analysis.analysis_id, node.tenant_id, node.entity_type,
                            node.impact_classification.value, node.impact_score, node.confidence.value,
                            node.distance, node.temporal_validity_start, node.temporal_validity_end,
                            json.dumps([e.model_dump() for e in node.evidence_refs])
                        ))

                    # 4. Save Paths
                    # Clear existing paths for update
                    conn.execute("DELETE FROM blast_radius_paths WHERE analysis_id = ?", (analysis.analysis_id,))
                    for path in analysis.paths:
                        conn.execute("""
                            INSERT INTO blast_radius_paths (
                                path_id, analysis_id, source_node_id, target_node_id, 
                                ordered_path_json, relationship_types_json, traversal_depth, 
                                confidence, evidence_refs_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            path.path_id, analysis.analysis_id, path.source_node_id, path.target_node_id,
                            json.dumps(path.ordered_path), json.dumps(path.relationship_types),
                            path.traversal_depth, path.confidence.value,
                            json.dumps([e.model_dump() for e in path.evidence_refs])
                        ))
            finally:
                conn.close()

    def get_analysis(self, analysis_id: str, tenant_id: str) -> Optional[BlastRadiusAnalysis]:
        with self._lock:
            conn = self._get_connection()
            try:
                # 1. Fetch Analysis Base
                row = conn.execute(
                    "SELECT * FROM blast_radius_analyses WHERE analysis_id = ? AND tenant_id = ?",
                    (analysis_id, tenant_id)
                ).fetchone()
                
                if not row:
                    return None
                    
                analysis = BlastRadiusAnalysis(
                    analysis_id=row["analysis_id"],
                    tenant_id=row["tenant_id"],
                    workspace_id=row["workspace_id"],
                    plant_id=row["plant_id"],
                    source_entity_id=row["source_entity_id"],
                    source_entity_type=row["source_entity_type"],
                    source_incident_id=row["source_incident_id"],
                    source_anomaly_id=row["source_anomaly_id"],
                    source_event_id=row["source_event_id"],
                    analysis_status=BlastRadiusAnalysisStatus(row["analysis_status"]),
                    analysis_timestamp=row["analysis_timestamp"],
                    snapshot_timestamp=row["snapshot_timestamp"],
                    ontology_version=row["ontology_version"],
                    knowledge_graph_version=row["knowledge_graph_version"],
                    digital_twin_snapshot_id=row["digital_twin_snapshot_id"],
                    method_version=row["method_version"],
                    input_fingerprint=row["input_fingerprint"] or "",
                    confidence=ConfidenceLevel(row["confidence"]),
                    uncertainty=row["uncertainty"] or "",
                    schema_version=row["schema_version"]
                )

                # 2. Fetch Scope
                scope_row = conn.execute(
                    "SELECT * FROM blast_radius_scopes WHERE analysis_id = ?", (analysis_id,)
                ).fetchone()
                if scope_row:
                    analysis.scope = ImpactScope(
                        total_assets=scope_row["total_assets"],
                        total_processes=scope_row["total_processes"],
                        total_production_areas=scope_row["total_production_areas"],
                        total_workspaces=scope_row["total_workspaces"],
                        total_plants=scope_row["total_plants"],
                        total_upstream_dependencies=scope_row["total_upstream_dependencies"],
                        total_downstream_dependencies=scope_row["total_downstream_dependencies"],
                        related_incidents=scope_row["related_incidents"],
                        related_anomalies=scope_row["related_anomalies"]
                    )

                # 3. Fetch Nodes
                node_rows = conn.execute(
                    "SELECT * FROM blast_radius_nodes WHERE analysis_id = ?", (analysis_id,)
                ).fetchall()
                for nr in node_rows:
                    evidence_refs_data = json.loads(nr["evidence_refs_json"]) if nr["evidence_refs_json"] else []
                    evidence_refs = [ImpactEvidence(**e) for e in evidence_refs_data]
                    
                    analysis.nodes.append(ImpactNode(
                        entity_id=nr["entity_id"],
                        tenant_id=nr["tenant_id"],
                        entity_type=nr["entity_type"],
                        impact_classification=ImpactClassification(nr["impact_classification"]),
                        impact_score=nr["impact_score"],
                        confidence=ConfidenceLevel(nr["confidence"]),
                        distance=nr["distance"],
                        temporal_validity_start=nr["temporal_validity_start"],
                        temporal_validity_end=nr["temporal_validity_end"],
                        evidence_refs=evidence_refs
                    ))

                # 4. Fetch Paths
                path_rows = conn.execute(
                    "SELECT * FROM blast_radius_paths WHERE analysis_id = ?", (analysis_id,)
                ).fetchall()
                for pr in path_rows:
                    evidence_refs_data = json.loads(pr["evidence_refs_json"]) if pr["evidence_refs_json"] else []
                    evidence_refs = [ImpactEvidence(**e) for e in evidence_refs_data]
                    
                    analysis.paths.append(ImpactPath(
                        path_id=pr["path_id"],
                        source_node_id=pr["source_node_id"],
                        target_node_id=pr["target_node_id"],
                        ordered_path=json.loads(pr["ordered_path_json"]),
                        relationship_types=json.loads(pr["relationship_types_json"]),
                        traversal_depth=pr["traversal_depth"],
                        confidence=ConfidenceLevel(pr["confidence"]),
                        evidence_refs=evidence_refs
                    ))

                return analysis
            finally:
                conn.close()

# Global Singleton
blast_radius_repository = BlastRadiusRepository()
