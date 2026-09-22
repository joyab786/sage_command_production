import json
import logging
import sqlite3
import threading
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from data.schemas.predictive_maintenance_contract import MaintenanceRiskAssessment

logger = logging.getLogger(__name__)


class PredictiveMaintenanceRepository:
    """
    Dedicated repository for persisting Predictive Maintenance intelligence.
    Uses a SQLite database with WAL mode for concurrent analytical reads/writes.
    Enforces tenant/workspace/plant isolation.
    """

    def __init__(self, db_path: str = "predictive_maintenance.sqlite"):
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            # Enforce WAL mode for better concurrency
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        """Initializes the schema for predictive maintenance assessments."""
        with self._lock:
            conn = self._get_connection()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS pm_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    asset_id TEXT NOT NULL,
                    assessment_timestamp TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    risk_level TEXT NOT NULL,
                    health_score REAL NOT NULL,
                    confidence TEXT NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                
                CREATE INDEX IF NOT EXISTS idx_pm_tenant_asset 
                ON pm_assessments (tenant_id, asset_id);
                
                CREATE INDEX IF NOT EXISTS idx_pm_fingerprint 
                ON pm_assessments (input_fingerprint);
            """)
            conn.commit()

    def save_assessment(self, assessment: MaintenanceRiskAssessment) -> None:
        """
        Persists a Predictive Maintenance assessment.
        Overwrites existing assessment if the ID matches.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO pm_assessments (
                        assessment_id, tenant_id, workspace_id, plant_id, asset_id, 
                        assessment_timestamp, risk_score, risk_level, health_score, 
                        confidence, input_fingerprint, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assessment.assessment_id,
                        assessment.tenant_id,
                        assessment.workspace_id,
                        assessment.plant_id,
                        assessment.asset_id,
                        assessment.assessment_timestamp,
                        assessment.risk_score,
                        assessment.risk_level.value,
                        assessment.health_score,
                        assessment.confidence.value,
                        assessment.input_fingerprint,
                        assessment.model_dump_json()
                    )
                )
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to save PM assessment {assessment.assessment_id}: {e}")
                raise

    def get_assessment(self, assessment_id: str, tenant_id: str) -> Optional[MaintenanceRiskAssessment]:
        """
        Retrieves an assessment by ID, strictly enforcing tenant isolation.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT payload FROM pm_assessments WHERE assessment_id = ? AND tenant_id = ?",
                    (assessment_id, tenant_id)
                ).fetchone()
                if row:
                    return MaintenanceRiskAssessment.model_validate_json(row["payload"])
                return None
            except Exception as e:
                logger.error(f"Failed to retrieve PM assessment {assessment_id}: {e}")
                return None

    def get_assessment_by_fingerprint(self, fingerprint: str) -> Optional[MaintenanceRiskAssessment]:
        """
        Checks for identical previous runs to deduplicate computation.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT payload FROM pm_assessments WHERE input_fingerprint = ?",
                    (fingerprint,)
                ).fetchone()
                if row:
                    return MaintenanceRiskAssessment.model_validate_json(row["payload"])
                return None
            except Exception as e:
                logger.error(f"Failed to retrieve PM assessment by fingerprint {fingerprint}: {e}")
                return None

    def query_assessments(
        self, 
        tenant_id: str, 
        asset_id: Optional[str] = None, 
        limit: int = 50
    ) -> List[MaintenanceRiskAssessment]:
        """
        Queries assessments for a tenant, optionally filtered by asset_id.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                query = "SELECT payload FROM pm_assessments WHERE tenant_id = ?"
                params = [tenant_id]
                
                if asset_id:
                    query += " AND asset_id = ?"
                    params.append(asset_id)
                    
                query += " ORDER BY assessment_timestamp DESC LIMIT ?"
                params.append(limit)
                
                rows = conn.execute(query, params).fetchall()
                return [MaintenanceRiskAssessment.model_validate_json(row["payload"]) for row in rows]
            except Exception as e:
                logger.error(f"Failed to query PM assessments for tenant {tenant_id}: {e}")
                return []


predictive_maintenance_repository = PredictiveMaintenanceRepository()
