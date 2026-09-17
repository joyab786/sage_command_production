import json
import sqlite3
import threading
from typing import List, Optional, Tuple

from core.config import SAGE_RCA_DB_PATH
from data.schemas.rca_contract import (
    RcaAnalysis, CauseCandidate, CausalRelationship, RcaEvidence,
    RcaAnalysisStatus, CauseType, CausalRelationshipType, ConfidenceLevel,
    EvidenceSourceType, DataQualityState, TemporalReasoning, DependencyReasoning
)


class RcaRepository:
    def __init__(self, db_path: str = SAGE_RCA_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # Analyses Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS rca_analyses (
                            analysis_id TEXT PRIMARY KEY,
                            incident_id TEXT NOT NULL,
                            tenant_id TEXT NOT NULL,
                            workspace_id TEXT,
                            plant_id TEXT,
                            schema_version TEXT,
                            analysis_version INTEGER,
                            status TEXT NOT NULL,
                            started_at TEXT NOT NULL,
                            completed_at TEXT,
                            method_version TEXT NOT NULL,
                            input_fingerprint TEXT NOT NULL
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_rca_incident ON rca_analyses(incident_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_rca_tenant ON rca_analyses(tenant_id)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_rca_fingerprint ON rca_analyses(input_fingerprint)")

                    # Causes Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS rca_causes (
                            cause_id TEXT PRIMARY KEY,
                            analysis_id TEXT NOT NULL,
                            cause_type TEXT NOT NULL,
                            label TEXT NOT NULL,
                            description TEXT NOT NULL,
                            status TEXT NOT NULL,
                            score REAL NOT NULL,
                            confidence TEXT NOT NULL,
                            uncertainty TEXT,
                            temporal_support TEXT,
                            dependency_support TEXT,
                            data_quality_state TEXT,
                            provenance TEXT,
                            entity_refs TEXT,
                            FOREIGN KEY (analysis_id) REFERENCES rca_analyses(analysis_id) ON DELETE CASCADE
                        )
                    """)

                    # Evidence Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS rca_evidence (
                            evidence_id TEXT PRIMARY KEY,
                            cause_id TEXT NOT NULL,
                            source_type TEXT NOT NULL,
                            source_id TEXT NOT NULL,
                            relationship TEXT NOT NULL,
                            recorded_timestamp TEXT NOT NULL,
                            provenance TEXT NOT NULL,
                            relevance_metadata TEXT,
                            FOREIGN KEY (cause_id) REFERENCES rca_causes(cause_id) ON DELETE CASCADE
                        )
                    """)

                    # Relationships Table
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS rca_relationships (
                            relationship_id TEXT PRIMARY KEY,
                            analysis_id TEXT NOT NULL,
                            source_cause_id TEXT NOT NULL,
                            target_cause_id TEXT NOT NULL,
                            relationship_type TEXT NOT NULL,
                            description TEXT,
                            FOREIGN KEY (analysis_id) REFERENCES rca_analyses(analysis_id) ON DELETE CASCADE,
                            FOREIGN KEY (source_cause_id) REFERENCES rca_causes(cause_id) ON DELETE CASCADE,
                            FOREIGN KEY (target_cause_id) REFERENCES rca_causes(cause_id) ON DELETE CASCADE
                        )
                    """)

            finally:
                conn.close()

    def create_analysis(self, analysis: RcaAnalysis) -> RcaAnalysis:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("""
                        INSERT INTO rca_analyses (
                            analysis_id, incident_id, tenant_id, workspace_id, plant_id, 
                            schema_version, analysis_version, status, started_at, 
                            completed_at, method_version, input_fingerprint
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        analysis.analysis_id, analysis.incident_id, analysis.tenant_id,
                        analysis.workspace_id, analysis.plant_id, analysis.schema_version,
                        analysis.analysis_version, analysis.status.value, analysis.started_at,
                        analysis.completed_at, analysis.method_version, analysis.input_fingerprint
                    ))
                    
                    self._insert_causes(conn, analysis.analysis_id, analysis.causes)
                    self._insert_relationships(conn, analysis.analysis_id, analysis.relationships)

                return analysis
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Analysis creation failed, Integrity Error: {e}")
            finally:
                conn.close()

    def update_analysis_status(self, analysis_id: str, tenant_id: str, status: RcaAnalysisStatus, completed_at: Optional[str] = None):
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    res = conn.execute("""
                        UPDATE rca_analyses SET status = ?, completed_at = ? 
                        WHERE analysis_id = ? AND tenant_id = ?
                    """, (status.value, completed_at, analysis_id, tenant_id))
                    if res.rowcount == 0:
                        raise ValueError(f"Analysis '{analysis_id}' not found for tenant '{tenant_id}'.")
            finally:
                conn.close()

    def _insert_causes(self, conn: sqlite3.Connection, analysis_id: str, causes: List[CauseCandidate]):
        for cause in causes:
            conn.execute("""
                INSERT INTO rca_causes (
                    cause_id, analysis_id, cause_type, label, description, status, 
                    score, confidence, uncertainty, temporal_support, dependency_support, 
                    data_quality_state, provenance, entity_refs
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cause.cause_id, analysis_id, cause.cause_type.value, cause.label, cause.description,
                cause.status, cause.score, cause.confidence.value, cause.uncertainty,
                cause.temporal_support.model_dump_json() if cause.temporal_support else None,
                cause.dependency_support.model_dump_json() if cause.dependency_support else None,
                cause.data_quality_state.value, cause.provenance, json.dumps(cause.entity_refs)
            ))
            
            for evd in cause.evidence_refs:
                conn.execute("""
                    INSERT INTO rca_evidence (
                        evidence_id, cause_id, source_type, source_id, relationship, 
                        recorded_timestamp, provenance, relevance_metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    evd.evidence_id, cause.cause_id, evd.source_type.value, evd.source_id,
                    evd.relationship, evd.recorded_timestamp, evd.provenance,
                    json.dumps(evd.relevance_metadata)
                ))

    def _insert_relationships(self, conn: sqlite3.Connection, analysis_id: str, relationships: List[CausalRelationship]):
        for rel in relationships:
            conn.execute("""
                INSERT INTO rca_relationships (
                    relationship_id, analysis_id, source_cause_id, target_cause_id, 
                    relationship_type, description
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                rel.relationship_id, analysis_id, rel.source_cause_id, rel.target_cause_id,
                rel.relationship_type.value, rel.description
            ))

    def get_analysis(self, analysis_id: str, tenant_id: str) -> Optional[RcaAnalysis]:
        conn = self._get_connection()
        try:
            row = conn.execute("SELECT * FROM rca_analyses WHERE analysis_id = ? AND tenant_id = ?", (analysis_id, tenant_id)).fetchone()
            if not row:
                return None
            
            analysis = RcaAnalysis(
                analysis_id=row["analysis_id"],
                incident_id=row["incident_id"],
                tenant_id=row["tenant_id"],
                workspace_id=row["workspace_id"],
                plant_id=row["plant_id"],
                schema_version=row["schema_version"],
                analysis_version=row["analysis_version"],
                status=RcaAnalysisStatus(row["status"]),
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                method_version=row["method_version"],
                input_fingerprint=row["input_fingerprint"]
            )
            
            # Fetch Causes
            cause_rows = conn.execute("SELECT * FROM rca_causes WHERE analysis_id = ?", (analysis_id,)).fetchall()
            for crow in cause_rows:
                cause = CauseCandidate(
                    cause_id=crow["cause_id"],
                    analysis_id=crow["analysis_id"],
                    cause_type=CauseType(crow["cause_type"]),
                    label=crow["label"],
                    description=crow["description"],
                    status=crow["status"],
                    score=crow["score"],
                    confidence=ConfidenceLevel(crow["confidence"]),
                    uncertainty=crow["uncertainty"] or "",
                    data_quality_state=DataQualityState(crow["data_quality_state"]),
                    provenance=crow["provenance"],
                    entity_refs=json.loads(crow["entity_refs"]) if crow["entity_refs"] else [],
                    temporal_support=TemporalReasoning.model_validate_json(crow["temporal_support"]) if crow["temporal_support"] else None,
                    dependency_support=DependencyReasoning.model_validate_json(crow["dependency_support"]) if crow["dependency_support"] else None,
                )
                
                # Fetch Evidence
                evd_rows = conn.execute("SELECT * FROM rca_evidence WHERE cause_id = ?", (cause.cause_id,)).fetchall()
                for erow in evd_rows:
                    cause.evidence_refs.append(RcaEvidence(
                        evidence_id=erow["evidence_id"],
                        cause_id=erow["cause_id"],
                        source_type=EvidenceSourceType(erow["source_type"]),
                        source_id=erow["source_id"],
                        relationship=erow["relationship"],
                        recorded_timestamp=erow["recorded_timestamp"],
                        provenance=erow["provenance"],
                        relevance_metadata=json.loads(erow["relevance_metadata"]) if erow["relevance_metadata"] else {}
                    ))
                
                analysis.causes.append(cause)

            # Fetch Relationships
            rel_rows = conn.execute("SELECT * FROM rca_relationships WHERE analysis_id = ?", (analysis_id,)).fetchall()
            for rrow in rel_rows:
                analysis.relationships.append(CausalRelationship(
                    relationship_id=rrow["relationship_id"],
                    analysis_id=rrow["analysis_id"],
                    source_cause_id=rrow["source_cause_id"],
                    target_cause_id=rrow["target_cause_id"],
                    relationship_type=CausalRelationshipType(rrow["relationship_type"]),
                    description=rrow["description"] or ""
                ))

            return analysis
        finally:
            conn.close()

    def list_analyses_for_incident(self, incident_id: str, tenant_id: str) -> List[RcaAnalysis]:
        conn = self._get_connection()
        try:
            # First just fetch IDs, then get full analyses
            rows = conn.execute("SELECT analysis_id FROM rca_analyses WHERE incident_id = ? AND tenant_id = ? ORDER BY started_at DESC", (incident_id, tenant_id)).fetchall()
            analyses = []
            for row in rows:
                analysis = self.get_analysis(row["analysis_id"], tenant_id)
                if analysis:
                    analyses.append(analysis)
            return analyses
        finally:
            conn.close()

    def get_analysis_by_fingerprint(self, incident_id: str, tenant_id: str, input_fingerprint: str) -> Optional[RcaAnalysis]:
        conn = self._get_connection()
        try:
            row = conn.execute("""
                SELECT analysis_id FROM rca_analyses 
                WHERE incident_id = ? AND tenant_id = ? AND input_fingerprint = ? 
                ORDER BY started_at DESC LIMIT 1
            """, (incident_id, tenant_id, input_fingerprint)).fetchone()
            
            if row:
                return self.get_analysis(row["analysis_id"], tenant_id)
            return None
        finally:
            conn.close()
