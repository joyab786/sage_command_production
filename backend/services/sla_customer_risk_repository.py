import sqlite3
import json
from typing import List, Optional
from datetime import datetime, UTC

from core.config import SAGE_SLA_CUSTOMER_RISK_DB_PATH
from data.schemas.sla_customer_risk_contract import SLACustomerRiskAssessment

class SLACustomerRiskRepository:
    """
    SQLite-backed repository for SLA / Customer Risk Assessments.
    Uses WAL mode for concurrency and strict deterministic writes.
    """
    def __init__(self, db_path: str = SAGE_SLA_CUSTOMER_RISK_DB_PATH):
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
                CREATE TABLE IF NOT EXISTS sla_customer_risk_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    customer_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    assessment_timestamp TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    sla_status TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    input_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sla_tenant_customer ON sla_customer_risk_assessments(tenant_id, customer_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sla_fingerprint ON sla_customer_risk_assessments(input_fingerprint)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sla_timestamp ON sla_customer_risk_assessments(assessment_timestamp DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sla_workspace ON sla_customer_risk_assessments(workspace_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sla_service ON sla_customer_risk_assessments(tenant_id, service_id)")

    def save_assessment(self, assessment: SLACustomerRiskAssessment) -> SLACustomerRiskAssessment:
        with self._get_connection() as conn:
            # Check if fingerprint already exists to avoid duplicate deterministic work
            cursor = conn.execute(
                "SELECT payload_json FROM sla_customer_risk_assessments WHERE input_fingerprint = ? AND tenant_id = ?",
                (assessment.input_fingerprint, assessment.tenant_id)
            )
            existing = cursor.fetchone()
            if existing:
                return SLACustomerRiskAssessment.model_validate_json(existing["payload_json"])
            
            conn.execute("""
                INSERT INTO sla_customer_risk_assessments 
                (assessment_id, tenant_id, workspace_id, customer_id, service_id, assessment_timestamp, risk_level, sla_status, risk_score, input_fingerprint, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                assessment.assessment_id,
                assessment.tenant_id,
                assessment.workspace_id,
                assessment.customer_id,
                assessment.service_id,
                assessment.assessment_timestamp,
                assessment.risk_level.value,
                assessment.sla_status.value,
                assessment.risk_score,
                assessment.input_fingerprint,
                assessment.model_dump_json()
            ))
        return assessment

    def get_assessment(self, assessment_id: str, tenant_id: str, workspace_id: Optional[str] = None) -> Optional[SLACustomerRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM sla_customer_risk_assessments WHERE assessment_id = ? AND tenant_id = ?"
            params = [assessment_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
                
            cursor = conn.execute(query, tuple(params))
            row = cursor.fetchone()
            if row:
                return SLACustomerRiskAssessment.model_validate_json(row["payload_json"])
        return None

    def get_latest_assessment(self, customer_id: str, service_id: str, tenant_id: str, workspace_id: Optional[str] = None) -> Optional[SLACustomerRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM sla_customer_risk_assessments WHERE customer_id = ? AND service_id = ? AND tenant_id = ?"
            params = [customer_id, service_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            
            query += " ORDER BY assessment_timestamp DESC LIMIT 1"
            cursor = conn.execute(query, tuple(params))
            row = cursor.fetchone()
            if row:
                return SLACustomerRiskAssessment.model_validate_json(row["payload_json"])
        return None

    def get_customer_summary(self, customer_id: str, tenant_id: str, workspace_id: Optional[str] = None, limit: int = 50) -> List[SLACustomerRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM sla_customer_risk_assessments WHERE customer_id = ? AND tenant_id = ?"
            params = [customer_id, tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            
            query += " ORDER BY assessment_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [SLACustomerRiskAssessment.model_validate_json(row["payload_json"]) for row in rows]
            
    def get_history(self, tenant_id: str, limit: int = 100, workspace_id: Optional[str] = None) -> List[SLACustomerRiskAssessment]:
        with self._get_connection() as conn:
            query = "SELECT payload_json FROM sla_customer_risk_assessments WHERE tenant_id = ?"
            params = [tenant_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            
            query += " ORDER BY assessment_timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [SLACustomerRiskAssessment.model_validate_json(row["payload_json"]) for row in rows]

sla_customer_risk_repository = SLACustomerRiskRepository()
