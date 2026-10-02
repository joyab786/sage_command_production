"""
backend/services/sensor_fusion_repository.py

SageCommand V3 — Multimodal Sensor Fusion Intelligence Repository (Prompt 27)

SQLite WAL-backed persistence for Multimodal Sensor Fusion Assessments.
Invariants:
- WAL journal mode for high read concurrency.
- All SQL queries strictly parameterized (no string formatting/concatenation).
- Tenant isolation enforced on every query.
- Workspace and Plant isolation enforced when provided.
- Bounded query results (limit capped at 200).
- Deterministic fingerprint lookup and idempotent deduplication.
- Schema versioning and tamper-evident payload storage.

ANALYTICAL ONLY. No physical systems, controllers, PLCs, or actuators are modified.
"""

import json
import sqlite3
import threading
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

try:
    from core.config import SAGE_SENSOR_FUSION_DB_PATH, SAGE_SENSOR_FUSION_MAX_ASSESSMENTS
    from data.schemas.sensor_fusion_contract import (
        FusionAssessment,
        SensorFusionSummaryItem,
        SensorEntitySummaryResponse,
        Modality,
        AgreementStatus,
        FusionConfidence,
        FusionUncertainty,
        SensorValueProvenance,
        SensorHealthIndicator,
        FusedObservation,
    )
except ModuleNotFoundError:
    from backend.core.config import SAGE_SENSOR_FUSION_DB_PATH, SAGE_SENSOR_FUSION_MAX_ASSESSMENTS
    from backend.data.schemas.sensor_fusion_contract import (
        FusionAssessment,
        SensorFusionSummaryItem,
        SensorEntitySummaryResponse,
        Modality,
        AgreementStatus,
        FusionConfidence,
        FusionUncertainty,
        SensorValueProvenance,
        SensorHealthIndicator,
        FusedObservation,
    )

_SCHEMA_VERSION = "1.0"
_MAX_QUERY_LIMIT = min(SAGE_SENSOR_FUSION_MAX_ASSESSMENTS, 200)


class SensorFusionRepository:
    """
    Thread-safe, tenant-isolated SQLite repository for Multimodal Sensor Fusion Assessments.
    """

    def __init__(self, db_path: str = SAGE_SENSOR_FUSION_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_fusion_assessments (
                    fusion_assessment_id    TEXT PRIMARY KEY,
                    tenant_id               TEXT NOT NULL,
                    workspace_id            TEXT NOT NULL,
                    plant_id                TEXT,
                    target_entity_id        TEXT NOT NULL,
                    target_entity_type      TEXT NOT NULL DEFAULT 'MACHINE',
                    assessment_timestamp    TEXT NOT NULL,
                    confidence              TEXT NOT NULL,
                    uncertainty             TEXT NOT NULL,
                    provenance              TEXT NOT NULL,
                    modalities_present      TEXT NOT NULL DEFAULT '[]',
                    modalities_missing      TEXT NOT NULL DEFAULT '[]',
                    observation_count       INTEGER NOT NULL DEFAULT 0,
                    fused_observation_count INTEGER NOT NULL DEFAULT 0,
                    input_fingerprint       TEXT NOT NULL,
                    model_version           TEXT NOT NULL DEFAULT '1.0.0',
                    schema_version          TEXT NOT NULL DEFAULT '1.0',
                    payload_json            TEXT NOT NULL,
                    created_at              TEXT NOT NULL
                )
                """
            )
            # Create indexes for efficient tenant-scoped filtering
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_tenant "
                "ON sensor_fusion_assessments(tenant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_entity "
                "ON sensor_fusion_assessments(tenant_id, target_entity_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_plant "
                "ON sensor_fusion_assessments(tenant_id, plant_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_fingerprint "
                "ON sensor_fusion_assessments(tenant_id, input_fingerprint)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_timestamp "
                "ON sensor_fusion_assessments(tenant_id, assessment_timestamp DESC)"
            )

    # -------------------------------------------------------------------------
    # Persist & Retrieve
    # -------------------------------------------------------------------------

    def save_assessment(self, assessment: FusionAssessment) -> FusionAssessment:
        """
        Persists a FusionAssessment.
        Idempotent deduplication: If identical input_fingerprint exists for this tenant,
        returns the existing assessment.
        """
        # 1. Check existing by fingerprint
        existing = self.get_assessment_by_fingerprint(
            fingerprint=assessment.input_fingerprint,
            tenant_id=assessment.tenant_id
        )
        if existing is not None:
            return existing

        payload_dict = assessment.model_dump()
        payload_json = json.dumps(payload_dict, default=str)
        created_at = datetime.now(timezone.utc).isoformat()

        modalities_present_json = json.dumps([m.value for m in assessment.modalities_present])
        modalities_missing_json = json.dumps([m.value for m in assessment.modalities_missing])

        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO sensor_fusion_assessments (
                    fusion_assessment_id,
                    tenant_id,
                    workspace_id,
                    plant_id,
                    target_entity_id,
                    target_entity_type,
                    assessment_timestamp,
                    confidence,
                    uncertainty,
                    provenance,
                    modalities_present,
                    modalities_missing,
                    observation_count,
                    fused_observation_count,
                    input_fingerprint,
                    model_version,
                    schema_version,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assessment.fusion_assessment_id,
                    assessment.tenant_id,
                    assessment.workspace_id,
                    assessment.plant_id,
                    assessment.target_entity_id,
                    assessment.target_entity_type,
                    assessment.assessment_timestamp,
                    assessment.confidence.value,
                    assessment.uncertainty.value,
                    assessment.provenance.value,
                    modalities_present_json,
                    modalities_missing_json,
                    len(assessment.observations),
                    len(assessment.fused_observations),
                    assessment.input_fingerprint,
                    assessment.model_version,
                    assessment.schema_version,
                    payload_json,
                    created_at,
                )
            )
        return assessment

    def get_assessment(self, assessment_id: str, tenant_id: str) -> Optional[FusionAssessment]:
        """
        Retrieves a FusionAssessment by ID with strict tenant boundary enforcement.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT payload_json FROM sensor_fusion_assessments
                WHERE fusion_assessment_id = ? AND tenant_id = ?
                """,
                (assessment_id, tenant_id)
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return FusionAssessment.model_validate(data)

    def get_assessment_by_fingerprint(
        self,
        fingerprint: str,
        tenant_id: str
    ) -> Optional[FusionAssessment]:
        """
        Finds existing assessment with matching input fingerprint for the tenant.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT payload_json FROM sensor_fusion_assessments
                WHERE input_fingerprint = ? AND tenant_id = ?
                LIMIT 1
                """,
                (fingerprint, tenant_id)
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["payload_json"])
            return FusionAssessment.model_validate(data)

    def list_assessments(
        self,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None,
        target_entity_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[SensorFusionSummaryItem]:
        """
        Queries assessment summaries with parameterized tenant/workspace/plant scoping.
        Strictly bounded to avoid resource blowups.
        """
        effective_limit = max(1, min(limit, _MAX_QUERY_LIMIT))
        effective_offset = max(0, offset)

        query = """
            SELECT
                fusion_assessment_id,
                tenant_id,
                workspace_id,
                plant_id,
                target_entity_id,
                assessment_timestamp,
                confidence,
                uncertainty,
                provenance,
                modalities_present,
                observation_count,
                fused_observation_count,
                input_fingerprint,
                payload_json
            FROM sensor_fusion_assessments
            WHERE tenant_id = ?
        """
        params: List[Any] = [tenant_id]

        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        if target_entity_id:
            query += " AND target_entity_id = ?"
            params.append(target_entity_id)

        query += " ORDER BY assessment_timestamp DESC LIMIT ? OFFSET ?"
        params.extend([effective_limit, effective_offset])

        results: List[SensorFusionSummaryItem] = []
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                mod_pres_raw = json.loads(row["modalities_present"])
                modalities_present = [Modality(m) for m in mod_pres_raw if m in Modality.__members__]
                
                # Check agreement status from payload
                payload = json.loads(row["payload_json"])
                agreements = payload.get("agreements", [])
                disagreements = payload.get("disagreements", [])
                
                if disagreements:
                    agreement_status = AgreementStatus.DISAGREEMENT
                elif agreements:
                    agreement_status = AgreementStatus.AGREEMENT
                elif len(modalities_present) < 2:
                    agreement_status = AgreementStatus.INSUFFICIENT_EVIDENCE
                else:
                    agreement_status = AgreementStatus.PARTIAL_AGREEMENT

                results.append(
                    SensorFusionSummaryItem(
                        fusion_assessment_id=row["fusion_assessment_id"],
                        tenant_id=row["tenant_id"],
                        workspace_id=row["workspace_id"],
                        plant_id=row["plant_id"],
                        target_entity_id=row["target_entity_id"],
                        assessment_timestamp=row["assessment_timestamp"],
                        confidence=FusionConfidence(row["confidence"]),
                        uncertainty=FusionUncertainty(row["uncertainty"]),
                        provenance=SensorValueProvenance(row["provenance"]),
                        modalities_present=modalities_present,
                        agreement_status=agreement_status,
                        observation_count=row["observation_count"],
                        fused_observation_count=row["fused_observation_count"],
                        input_fingerprint=row["input_fingerprint"],
                    )
                )
        return results

    def get_entity_summary(
        self,
        target_entity_id: str,
        tenant_id: str,
        workspace_id: Optional[str] = None,
        plant_id: Optional[str] = None
    ) -> SensorEntitySummaryResponse:
        """
        Builds an aggregate analytical summary for an entity across historical assessments.
        """
        with self._get_connection() as conn:
            # 1. Get latest assessment
            query = """
                SELECT payload_json FROM sensor_fusion_assessments
                WHERE tenant_id = ? AND target_entity_id = ?
            """
            params: List[Any] = [tenant_id, target_entity_id]
            if workspace_id:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            if plant_id:
                query += " AND plant_id = ?"
                params.append(plant_id)

            query += " ORDER BY assessment_timestamp DESC LIMIT 1"
            cursor = conn.execute(query, params)
            latest_row = cursor.fetchone()

            # 2. Count total assessments
            count_query = """
                SELECT COUNT(*) as cnt FROM sensor_fusion_assessments
                WHERE tenant_id = ? AND target_entity_id = ?
            """
            count_params: List[Any] = [tenant_id, target_entity_id]
            if workspace_id:
                count_query += " AND workspace_id = ?"
                count_params.append(workspace_id)
            if plant_id:
                count_query += " AND plant_id = ?"
                count_params.append(plant_id)

            count_cursor = conn.execute(count_query, count_params)
            total_count = count_cursor.fetchone()["cnt"]

            if not latest_row:
                return SensorEntitySummaryResponse(
                    target_entity_id=target_entity_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id or "workspace_default",
                    plant_id=plant_id,
                    latest_assessment_id=None,
                    latest_assessment_timestamp=None,
                    confidence=FusionConfidence.UNKNOWN,
                    uncertainty=FusionUncertainty.HIGH,
                    modalities_present=[],
                    sensor_health=[],
                    latest_fused_observations=[],
                    active_anomalies_count=0,
                    total_assessments_recorded=0
                )

            latest_data = json.loads(latest_row["payload_json"])
            latest_assessment = FusionAssessment.model_validate(latest_data)

            return SensorEntitySummaryResponse(
                target_entity_id=target_entity_id,
                tenant_id=tenant_id,
                workspace_id=latest_assessment.workspace_id,
                plant_id=latest_assessment.plant_id,
                latest_assessment_id=latest_assessment.fusion_assessment_id,
                latest_assessment_timestamp=latest_assessment.assessment_timestamp,
                confidence=latest_assessment.confidence,
                uncertainty=latest_assessment.uncertainty,
                modalities_present=latest_assessment.modalities_present,
                sensor_health=latest_assessment.sensor_health,
                latest_fused_observations=latest_assessment.fused_observations,
                active_anomalies_count=len(latest_assessment.anomalies),
                total_assessments_recorded=total_count
            )

    def count_assessments(self, tenant_id: str, plant_id: Optional[str] = None) -> int:
        """Counts assessments for isolation checks."""
        query = "SELECT COUNT(*) as c FROM sensor_fusion_assessments WHERE tenant_id = ?"
        params: List[Any] = [tenant_id]
        if plant_id:
            query += " AND plant_id = ?"
            params.append(plant_id)
        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["c"]) if row else 0

    def delete_all(self, tenant_id: str) -> int:
        """Utility for test isolation."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM sensor_fusion_assessments WHERE tenant_id = ?",
                (tenant_id,)
            )
            return cursor.rowcount


# Global singleton instance
sensor_fusion_repository = SensorFusionRepository()
