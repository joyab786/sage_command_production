import sqlite3
import json
from typing import List, Optional
from datetime import datetime, UTC

from core.config import SAGE_SUPPLIER_RISK_DB_PATH
from data.schemas.supplier_risk_contract import SupplierRiskAssessment

class SupplierRiskRepository:
    """
    SQLite-backed repository for Supplier Risk Assessments.
    Uses WAL mode for concurrency and strict deterministic writes.
    """
    def __init__(self, db_path: str = SAGE_SUPPLIER_RISK_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS supplier_risk_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    supplier_id TEXT NOT NULL,
                    assessment_timestamp TEXT NOT NULL,
                    as_of_timestamp TEXT NOT NULL,
                    risk_status TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_supplier_tenant ON supplier_risk_assessments(tenant_id, supplier_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_supplier_fingerprint ON supplier_risk_assessments(input_fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_supplier_timestamp ON supplier_risk_assessments(as_of_timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_supplier_workspace ON supplier_risk_assessments(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_supplier_plant ON supplier_risk_assessments(plant_id)")

    def save_assessment(self, assessment: SupplierRiskAssessment) -> SupplierRiskAssessment:
        with self._get_connection() as conn:
            # Check if fingerprint already exists to avoid duplicate deterministic work
            cursor = conn.execute(
                "SELECT payload_json FROM supplier_risk_assessments WHERE input_fingerprint = ? AND tenant_id = ?",
                (assessment.input_fingerprint, assessment.tenant_id)
            )
            existing = cursor.fetchone()
            if existing:
                return SupplierRiskAssessment.model_validate_json(existing["payload_json"])
            
            conn.execute("""
                INSERT INTO supplier_risk_assessments 
                (assessment_id, tenant_id, workspace_id, plant_id, supplier_id, assessment_timestamp, as_of_timestamp, risk_status, risk_score, input_fingerprint, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                assessment.assessment_id,
                assessment.tenant_id,
                assessment.workspace_id,
                assessment.plant_id,
                assessment.supplier_id,
                assessment.assessment_timestamp,
                assessment.as_of_timestamp,
                assessment.risk_status.value,
                assessment.risk_score,
                assessment.input_fingerprint,
                assessment.model_dump_json()
            ))
        return assessment

    def get_assessment(self, assessment_id: str, tenant_id: str, workspace_id: Optional[str] = None, plant_id: Optional[str] = None) -> Optional[SupplierRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM supplier_risk_assessments WHERE assessment_id = ? AND tenant_id = ?"
            params = [assessment_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id:
                query += " AND plant_id = ?"
                params.append(plant_id)
                
            cursor = conn.execute(query, tuple(params))
            row = cursor.fetchone()
            if row:
                return SupplierRiskAssessment.model_validate_json(row["payload_json"])
        return None

    def get_latest_assessment(self, supplier_id: str, tenant_id: str, workspace_id: Optional[str] = None, plant_id: Optional[str] = None) -> Optional[SupplierRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM supplier_risk_assessments WHERE supplier_id = ? AND tenant_id = ?"
            params = [supplier_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id:
                query += " AND plant_id = ?"
                params.append(plant_id)
            
            query += " ORDER BY as_of_timestamp DESC LIMIT 1"
            cursor = conn.execute(query, tuple(params))
            row = cursor.fetchone()
            if row:
                return SupplierRiskAssessment.model_validate_json(row["payload_json"])
        return None

    def get_history(self, supplier_id: str, tenant_id: str, limit: int = 100, workspace_id: Optional[str] = None, plant_id: Optional[str] = None) -> List[SupplierRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM supplier_risk_assessments WHERE supplier_id = ? AND tenant_id = ?"
            params = [supplier_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id:
                query += " AND plant_id = ?"
                params.append(plant_id)
            
            query += " ORDER BY as_of_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [SupplierRiskAssessment.model_validate_json(row["payload_json"]) for row in rows]

supplier_risk_repository = SupplierRiskRepository()
