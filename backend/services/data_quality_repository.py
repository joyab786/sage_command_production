# backend/services/data_quality_repository.py
import sqlite3
import threading
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

try:
    from core.config import SAGE_DATA_QUALITY_DB_PATH
    from data.schemas.data_quality_contract import (
        QualityRule, QualityDimension, QualitySeverity, QualityStatus,
        QualityIssue, IssueLifecycle, AssessmentRun, AssessmentScope
    )
except ImportError:
    from backend.core.config import SAGE_DATA_QUALITY_DB_PATH
    from backend.data.schemas.data_quality_contract import (
        QualityRule, QualityDimension, QualitySeverity, QualityStatus,
        QualityIssue, IssueLifecycle, AssessmentRun, AssessmentScope
    )

class DataQualityRepository:
    """
    Thread-safe SQLite repository for Data Quality rules, issues, and assessment runs.
    Enforces strict tenant isolation on every query.
    """
    
    def __init__(self, db_path: str = SAGE_DATA_QUALITY_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS dq_rules (
                        rule_id TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL,
                        dimension TEXT NOT NULL,
                        entity_type TEXT,
                        field TEXT,
                        relationship_type TEXT,
                        severity TEXT NOT NULL,
                        threshold TEXT,
                        enabled INTEGER NOT NULL,
                        version INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS dq_issues (
                        issue_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT,
                        plant_id TEXT,
                        entity_id TEXT,
                        relationship_id TEXT,
                        dimension TEXT NOT NULL,
                        rule_id TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        status TEXT NOT NULL,
                        evidence TEXT NOT NULL,
                        first_detected_at TEXT NOT NULL,
                        last_detected_at TEXT NOT NULL,
                        occurrence_count INTEGER NOT NULL,
                        source TEXT NOT NULL,
                        resolution_metadata TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS dq_assessment_runs (
                        assessment_id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT,
                        plant_id TEXT,
                        scope TEXT NOT NULL,
                        start_time TEXT NOT NULL,
                        completion_time TEXT,
                        rules_evaluated INTEGER NOT NULL,
                        entities_evaluated INTEGER NOT NULL,
                        counts_by_dimension TEXT NOT NULL,
                        counts_by_status TEXT NOT NULL,
                        overall_score REAL NOT NULL,
                        execution_duration_ms INTEGER NOT NULL,
                        engine_version TEXT NOT NULL
                    )
                """)
                # Indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dq_rules_tenant ON dq_rules (tenant_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dq_issues_tenant ON dq_issues (tenant_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dq_assessments_tenant ON dq_assessment_runs (tenant_id)")

    def save_rule(self, rule: QualityRule):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO dq_rules 
                    (rule_id, tenant_id, name, description, dimension, entity_type, field, relationship_type, severity, threshold, enabled, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule.rule_id, rule.tenant_id, rule.name, rule.description, rule.dimension.value, 
                    rule.entity_type, rule.field, rule.relationship_type, rule.severity.value,
                    json.dumps(rule.threshold) if rule.threshold is not None else None,
                    1 if rule.enabled else 0, rule.version, rule.created_at
                ))

    def get_rules(self, tenant_id: str, include_system: bool = True) -> List[QualityRule]:
        with self._lock:
            with self._get_conn() as conn:
                if include_system:
                    cursor = conn.execute("SELECT * FROM dq_rules WHERE tenant_id = ? OR tenant_id IS NULL", (tenant_id,))
                else:
                    cursor = conn.execute("SELECT * FROM dq_rules WHERE tenant_id = ?", (tenant_id,))
                
                return [self._map_rule(row) for row in cursor.fetchall()]

    def save_issue(self, issue: QualityIssue):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO dq_issues 
                    (issue_id, tenant_id, workspace_id, plant_id, entity_id, relationship_id, dimension, rule_id, severity, status, evidence, first_detected_at, last_detected_at, occurrence_count, source, resolution_metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    issue.issue_id, issue.tenant_id, issue.workspace_id, issue.plant_id, issue.entity_id, 
                    issue.relationship_id, issue.dimension.value, issue.rule_id, issue.severity.value, 
                    issue.status.value, issue.evidence, issue.first_detected_at, issue.last_detected_at,
                    issue.occurrence_count, issue.source,
                    json.dumps(issue.resolution_metadata) if issue.resolution_metadata else None
                ))

    def get_issues(self, tenant_id: str, limit: int = 100) -> List[QualityIssue]:
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT * FROM dq_issues WHERE tenant_id = ? ORDER BY last_detected_at DESC LIMIT ?", (tenant_id, limit))
                return [self._map_issue(row) for row in cursor.fetchall()]

    def get_issue(self, tenant_id: str, issue_id: str) -> Optional[QualityIssue]:
        with self._lock:
            with self._get_conn() as conn:
                row = conn.execute("SELECT * FROM dq_issues WHERE tenant_id = ? AND issue_id = ?", (tenant_id, issue_id)).fetchone()
                return self._map_issue(row) if row else None

    def save_assessment_run(self, run: AssessmentRun):
        with self._lock:
            with self._get_conn() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO dq_assessment_runs 
                    (assessment_id, tenant_id, workspace_id, plant_id, scope, start_time, completion_time, rules_evaluated, entities_evaluated, counts_by_dimension, counts_by_status, overall_score, execution_duration_ms, engine_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run.assessment_id, run.tenant_id, run.workspace_id, run.plant_id,
                    run.scope.model_dump_json(), run.start_time, run.completion_time,
                    run.rules_evaluated, run.entities_evaluated,
                    json.dumps(run.counts_by_dimension), json.dumps(run.counts_by_status),
                    run.overall_score, run.execution_duration_ms, run.engine_version
                ))

    def get_assessment_runs(self, tenant_id: str, limit: int = 100) -> List[AssessmentRun]:
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.execute("SELECT * FROM dq_assessment_runs WHERE tenant_id = ? ORDER BY start_time DESC LIMIT ?", (tenant_id, limit))
                return [self._map_run(row) for row in cursor.fetchall()]
                
    def get_assessment_run(self, tenant_id: str, assessment_id: str) -> Optional[AssessmentRun]:
        with self._lock:
            with self._get_conn() as conn:
                row = conn.execute("SELECT * FROM dq_assessment_runs WHERE tenant_id = ? AND assessment_id = ?", (tenant_id, assessment_id)).fetchone()
                return self._map_run(row) if row else None

    def _map_rule(self, row: sqlite3.Row) -> QualityRule:
        return QualityRule(
            rule_id=row['rule_id'],
            tenant_id=row['tenant_id'],
            name=row['name'],
            description=row['description'],
            dimension=QualityDimension(row['dimension']),
            entity_type=row['entity_type'],
            field=row['field'],
            relationship_type=row['relationship_type'],
            severity=QualitySeverity(row['severity']),
            threshold=json.loads(row['threshold']) if row['threshold'] else None,
            enabled=bool(row['enabled']),
            version=row['version'],
            created_at=row['created_at']
        )

    def _map_issue(self, row: sqlite3.Row) -> QualityIssue:
        return QualityIssue(
            issue_id=row['issue_id'],
            tenant_id=row['tenant_id'],
            workspace_id=row['workspace_id'],
            plant_id=row['plant_id'],
            entity_id=row['entity_id'],
            relationship_id=row['relationship_id'],
            dimension=QualityDimension(row['dimension']),
            rule_id=row['rule_id'],
            severity=QualitySeverity(row['severity']),
            status=IssueLifecycle(row['status']),
            evidence=row['evidence'],
            first_detected_at=row['first_detected_at'],
            last_detected_at=row['last_detected_at'],
            occurrence_count=row['occurrence_count'],
            source=row['source'],
            resolution_metadata=json.loads(row['resolution_metadata']) if row['resolution_metadata'] else None
        )

    def _map_run(self, row: sqlite3.Row) -> AssessmentRun:
        return AssessmentRun(
            assessment_id=row['assessment_id'],
            tenant_id=row['tenant_id'],
            workspace_id=row['workspace_id'],
            plant_id=row['plant_id'],
            scope=AssessmentScope.model_validate_json(row['scope']),
            start_time=row['start_time'],
            completion_time=row['completion_time'],
            rules_evaluated=row['rules_evaluated'],
            entities_evaluated=row['entities_evaluated'],
            counts_by_dimension=json.loads(row['counts_by_dimension']),
            counts_by_status=json.loads(row['counts_by_status']),
            overall_score=row['overall_score'],
            execution_duration_ms=row['execution_duration_ms'],
            engine_version=row['engine_version']
        )
