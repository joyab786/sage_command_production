# backend/services/anomaly_repository.py
"""
SageCommand V3 — Real Anomaly Detection Repository (Prompt 15)
Provides local SQLite persistence for anomalies, baselines, and assessment runs.
Enforces tenant isolation by design.
"""

import sqlite3
import json
from typing import List, Optional
from datetime import datetime, timezone
import os

try:
    from data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentRun, 
        AnomalyType, AnomalyStatus, AnomalySeverity, DetectorMethod, AnomalyEvidence, AnomalyAssessmentScope
    )
except ImportError:
    from backend.data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentRun, 
        AnomalyType, AnomalyStatus, AnomalySeverity, DetectorMethod, AnomalyEvidence, AnomalyAssessmentScope
    )

SAGE_ANOMALY_DB = os.getenv("SAGE_ANOMALY_DB_PATH", "v3_anomaly_db.sqlite")

class AnomalyRepository:
    def __init__(self, db_path: str = SAGE_ANOMALY_DB):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Baselines
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anomaly_baselines (
                    baseline_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    entity_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    detector_method TEXT NOT NULL,
                    parameters TEXT,
                    sample_count INTEGER,
                    calculated_statistics TEXT,
                    context TEXT,
                    created_at TEXT,
                    version INTEGER,
                    UNIQUE(tenant_id, entity_id, metric, context, version)
                )
            ''')
            
            # Anomalies
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anomaly_detections (
                    anomaly_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    workspace_id TEXT,
                    plant_id TEXT,
                    entity_id TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    detector_method TEXT NOT NULL,
                    anomaly_score REAL,
                    evidence TEXT,
                    first_detected_at TEXT,
                    last_detected_at TEXT,
                    occurrence_count INTEGER,
                    fingerprint TEXT NOT NULL,
                    UNIQUE(tenant_id, fingerprint)
                )
            ''')
            
            # Assessment Runs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anomaly_assessment_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    scope TEXT,
                    start_time TEXT,
                    completion_time TEXT,
                    baselines_evaluated INTEGER,
                    observations_evaluated INTEGER,
                    anomalies_detected INTEGER,
                    execution_duration_ms INTEGER
                )
            ''')
            conn.commit()

    def save_baseline(self, baseline: AnomalyBaseline):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO anomaly_baselines (
                    baseline_id, tenant_id, workspace_id, plant_id, entity_id, 
                    metric, detector_method, parameters, sample_count, 
                    calculated_statistics, context, created_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                baseline.baseline_id,
                baseline.tenant_id,
                baseline.workspace_id,
                baseline.plant_id,
                baseline.entity_id,
                baseline.metric,
                baseline.detector_method.value,
                json.dumps(baseline.parameters),
                baseline.sample_count,
                json.dumps(baseline.calculated_statistics),
                baseline.context,
                baseline.created_at,
                baseline.version
            ))
            conn.commit()

    def get_baseline(self, tenant_id: str, baseline_id: str) -> Optional[AnomalyBaseline]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT baseline_id, tenant_id, workspace_id, plant_id, entity_id, 
                       metric, detector_method, parameters, sample_count, 
                       calculated_statistics, context, created_at, version
                FROM anomaly_baselines 
                WHERE tenant_id = ? AND baseline_id = ?
            ''', (tenant_id, baseline_id))
            row = cursor.fetchone()
            if row:
                return AnomalyBaseline(
                    baseline_id=row[0],
                    tenant_id=row[1],
                    workspace_id=row[2],
                    plant_id=row[3],
                    entity_id=row[4],
                    metric=row[5],
                    detector_method=DetectorMethod(row[6]),
                    parameters=json.loads(row[7]) if row[7] else {},
                    sample_count=row[8],
                    calculated_statistics=json.loads(row[9]) if row[9] else {},
                    context=row[10],
                    created_at=row[11],
                    version=row[12]
                )
            return None

    def list_baselines(self, tenant_id: str, entity_id: Optional[str] = None) -> List[AnomalyBaseline]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if entity_id:
                cursor.execute('''
                    SELECT * FROM anomaly_baselines WHERE tenant_id = ? AND entity_id = ?
                ''', (tenant_id, entity_id))
            else:
                cursor.execute('''
                    SELECT * FROM anomaly_baselines WHERE tenant_id = ?
                ''', (tenant_id,))
            rows = cursor.fetchall()
            return [AnomalyBaseline(
                baseline_id=r[0], tenant_id=r[1], workspace_id=r[2], plant_id=r[3],
                entity_id=r[4], metric=r[5], detector_method=DetectorMethod(r[6]),
                parameters=json.loads(r[7]) if r[7] else {}, sample_count=r[8],
                calculated_statistics=json.loads(r[9]) if r[9] else {}, context=r[10],
                created_at=r[11], version=r[12]
            ) for r in rows]

    def save_detection(self, anomaly: AnomalyDetection) -> AnomalyDetection:
        """Saves a detection. Deduplicates by fingerprint."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Check for existing
            cursor.execute('''
                SELECT anomaly_id, first_detected_at, occurrence_count 
                FROM anomaly_detections 
                WHERE tenant_id = ? AND fingerprint = ?
            ''', (anomaly.tenant_id, anomaly.fingerprint))
            
            existing = cursor.fetchone()
            if existing:
                existing_id, first_detected_at, occ_count = existing
                # Update occurrence count and last_detected
                cursor.execute('''
                    UPDATE anomaly_detections
                    SET last_detected_at = ?, occurrence_count = occurrence_count + 1, evidence = ?
                    WHERE anomaly_id = ?
                ''', (
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps([e.model_dump() for e in anomaly.evidence]),
                    existing_id
                ))
                conn.commit()
                # Return mutated copy
                anomaly.anomaly_id = existing_id
                anomaly.first_detected_at = first_detected_at
                anomaly.occurrence_count = occ_count + 1
                return anomaly
            else:
                cursor.execute('''
                    INSERT INTO anomaly_detections (
                        anomaly_id, tenant_id, workspace_id, plant_id, entity_id, 
                        metric, type, status, severity, detector_method, anomaly_score,
                        evidence, first_detected_at, last_detected_at, occurrence_count, fingerprint
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    anomaly.anomaly_id,
                    anomaly.tenant_id,
                    anomaly.workspace_id,
                    anomaly.plant_id,
                    anomaly.entity_id,
                    anomaly.metric,
                    anomaly.type.value,
                    anomaly.status.value,
                    anomaly.severity.value,
                    anomaly.detector_method.value,
                    anomaly.anomaly_score,
                    json.dumps([e.model_dump() for e in anomaly.evidence]),
                    anomaly.first_detected_at,
                    anomaly.last_detected_at,
                    anomaly.occurrence_count,
                    anomaly.fingerprint
                ))
                conn.commit()
                return anomaly

    def get_detections(self, tenant_id: str, limit: int = 100) -> List[AnomalyDetection]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT anomaly_id, tenant_id, workspace_id, plant_id, entity_id, 
                       metric, type, status, severity, detector_method, anomaly_score,
                       evidence, first_detected_at, last_detected_at, occurrence_count, fingerprint
                FROM anomaly_detections 
                WHERE tenant_id = ? 
                ORDER BY last_detected_at DESC
                LIMIT ?
            ''', (tenant_id, limit))
            rows = cursor.fetchall()
            
            anomalies = []
            for r in rows:
                ev_data = json.loads(r[11]) if r[11] else []
                evidence = [AnomalyEvidence(**e) for e in ev_data]
                
                anomalies.append(AnomalyDetection(
                    anomaly_id=r[0], tenant_id=r[1], workspace_id=r[2], plant_id=r[3],
                    entity_id=r[4], metric=r[5], type=AnomalyType(r[6]), status=AnomalyStatus(r[7]),
                    severity=AnomalySeverity(r[8]), detector_method=DetectorMethod(r[9]),
                    anomaly_score=r[10], evidence=evidence, first_detected_at=r[12],
                    last_detected_at=r[13], occurrence_count=r[14], fingerprint=r[15]
                ))
            return anomalies

    def save_run(self, run: AnomalyAssessmentRun):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO anomaly_assessment_runs (
                    run_id, tenant_id, scope, start_time, completion_time, 
                    baselines_evaluated, observations_evaluated, anomalies_detected, execution_duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                run.run_id,
                run.tenant_id,
                json.dumps(run.scope.model_dump()),
                run.start_time,
                run.completion_time,
                run.baselines_evaluated,
                run.observations_evaluated,
                run.anomalies_detected,
                run.execution_duration_ms
            ))
            conn.commit()
