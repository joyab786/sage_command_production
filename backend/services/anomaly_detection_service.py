# backend/services/anomaly_detection_service.py
"""
SageCommand V3 — Real Anomaly Detection Engine (Prompt 15)
Provides deterministic mathematical anomaly detection for operational metrics.
Strictly isolated from ExecutionGateway. Performs ZERO operational mutations.
"""

import uuid
import time
import math
import hashlib
from typing import List, Dict, Any, Tuple
from datetime import datetime, timezone

try:
    from core.auth import Identity
    from services.anomaly_repository import AnomalyRepository
    from services.digital_twin_service import DigitalTwinService
    from services.data_quality_service import DataQualityService
    from data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentScope, AnomalyAssessmentRun,
        AnomalyType, AnomalyStatus, AnomalySeverity, DetectorMethod, AnomalyEvidence
    )
    from data.schemas.data_quality_contract import QualityStatus
except ImportError:
    from backend.core.auth import Identity
    from backend.services.anomaly_repository import AnomalyRepository
    from backend.services.digital_twin_service import DigitalTwinService
    from backend.services.data_quality_service import DataQualityService
    from backend.data.schemas.anomaly_contract import (
        AnomalyDetection, AnomalyBaseline, AnomalyAssessmentScope, AnomalyAssessmentRun,
        AnomalyType, AnomalyStatus, AnomalySeverity, DetectorMethod, AnomalyEvidence
    )
    from backend.data.schemas.data_quality_contract import QualityStatus


class AnomalyDetectionService:
    def __init__(
        self, 
        repository: AnomalyRepository, 
        digital_twin_service: DigitalTwinService,
        data_quality_service: DataQualityService
    ):
        self._repo = repository
        self._dt_svc = digital_twin_service
        self._dq_svc = data_quality_service

    def get_detections(self, identity: Identity, limit: int = 100) -> List[AnomalyDetection]:
        return self._repo.get_detections(identity.tenant_id, limit)

    def run_assessment(self, identity: Identity, scope: AnomalyAssessmentScope) -> AnomalyAssessmentRun:
        start_ts = time.time()
        start_iso = datetime.now(timezone.utc).isoformat()
        
        # Enforce scope boundaries
        if scope.tenant_id != identity.tenant_id:
            raise ValueError("Cross-tenant assessment strictly forbidden")
            
        anomalies_detected = 0
        baselines_evaluated = 0
        observations_evaluated = 0
        
        # 1. Fetch baselines for the tenant (filtered by scope)
        baselines = self._repo.list_baselines(identity.tenant_id)
        if scope.entity_ids:
            baselines = [b for b in baselines if b.entity_id in scope.entity_ids]
        if scope.metrics:
            baselines = [b for b in baselines if b.metric in scope.metrics]
            
        # 2. Iterate baselines and detect
        for baseline in baselines:
            baselines_evaluated += 1
            
            # Fetch observations from Digital Twin (mocked extraction for demo purposes)
            twin = self._dt_svc.get_twin_entity(identity.tenant_id, baseline.entity_id)
            if not twin or not twin.current_state:
                continue
                
            # Filter properties matching metric
            props = [p for p in twin.current_state.properties.values() if p.property_name == baseline.metric]
            
            # In a real system we would fetch a time-series slice. Here we evaluate current point against baseline.
            # We mock a small history array based on the current property if time_series is not stored in twin natively.
            
            for prop in props:
                observations_evaluated += 1
                
                # Exclude explicitly invalid data
                if prop.confidence.value == "LOW": # Proxy for DQ invalid in this simple check
                    continue
                    
                val = prop.value
                if not isinstance(val, (int, float)):
                    continue # Mathematical anomaly detection requires numeric values
                
                anomaly = self._evaluate_observation(identity, baseline, prop)
                if anomaly:
                    self._repo.save_detection(anomaly)
                    anomalies_detected += 1
                    
        run = AnomalyAssessmentRun(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            tenant_id=identity.tenant_id,
            scope=scope.model_dump() if hasattr(scope, "model_dump") else scope,
            start_time=start_iso,
            completion_time=datetime.now(timezone.utc).isoformat(),
            baselines_evaluated=baselines_evaluated,
            observations_evaluated=observations_evaluated,
            anomalies_detected=anomalies_detected,
            execution_duration_ms=int((time.time() - start_ts) * 1000)
        )
        self._repo.save_run(run)
        return run

    def _evaluate_observation(self, identity: Identity, baseline: AnomalyBaseline, prop: Any) -> AnomalyDetection | None:
        """Evaluates a single observation against a deterministic baseline."""
        
        val = float(prop.value)
        evidence = AnomalyEvidence(
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            metric=baseline.metric,
            value=val,
            baseline_reference_id=baseline.baseline_id
        )
        
        # Method: Z-SCORE
        if baseline.detector_method == DetectorMethod.Z_SCORE:
            mean = baseline.calculated_statistics.get("mean")
            std_dev = baseline.calculated_statistics.get("std_dev")
            threshold = baseline.parameters.get("threshold", 3.0)
            
            if mean is None or std_dev is None or baseline.sample_count < 30:
                return None # INSUFFICIENT_DATA handled silently for return count
                
            if std_dev == 0:
                z_score = 0.0 if val == mean else float('inf')
            else:
                z_score = abs(val - mean) / std_dev
                
            if z_score > threshold:
                return self._create_anomaly(identity, baseline, val, z_score, evidence, AnomalyType.POINT)
                
        # Method: MAD
        elif baseline.detector_method == DetectorMethod.MAD:
            median = baseline.calculated_statistics.get("median")
            mad = baseline.calculated_statistics.get("mad")
            threshold = baseline.parameters.get("threshold", 3.5)
            
            if median is None or mad is None or baseline.sample_count < 15:
                return None
                
            # robust Z = 0.6745 * (x - median) / MAD
            if mad == 0:
                robust_z = 0.0 if val == median else float('inf')
            else:
                robust_z = 0.6745 * abs(val - median) / mad
                
            if robust_z > threshold:
                return self._create_anomaly(identity, baseline, val, robust_z, evidence, AnomalyType.POINT)
                
        # Method: IQR
        elif baseline.detector_method == DetectorMethod.IQR:
            q1 = baseline.calculated_statistics.get("q1")
            q3 = baseline.calculated_statistics.get("q3")
            iqr = baseline.calculated_statistics.get("iqr")
            k = baseline.parameters.get("k", 1.5)
            
            if q1 is None or q3 is None or iqr is None or baseline.sample_count < 10:
                return None
                
            lower_bound = q1 - (k * iqr)
            upper_bound = q3 + (k * iqr)
            
            if val < lower_bound or val > upper_bound:
                score = min(abs(val - lower_bound), abs(val - upper_bound))
                return self._create_anomaly(identity, baseline, val, score, evidence, AnomalyType.POINT)
                
        # Method: RATE_OF_CHANGE
        elif baseline.detector_method == DetectorMethod.RATE_OF_CHANGE:
            last_val = baseline.calculated_statistics.get("last_value")
            max_delta = baseline.parameters.get("max_delta")
            max_pct = baseline.parameters.get("max_percentage")
            
            if last_val is None or baseline.sample_count < 2:
                return None
                
            delta = abs(val - last_val)
            is_anomaly = False
            
            if max_delta is not None and delta > max_delta:
                is_anomaly = True
            
            if max_pct is not None and last_val != 0:
                pct = delta / abs(last_val)
                if pct > max_pct:
                    is_anomaly = True
                    
            if is_anomaly:
                return self._create_anomaly(identity, baseline, val, delta, evidence, AnomalyType.TREND)
                
        # Method: MOVING_WINDOW
        elif baseline.detector_method == DetectorMethod.MOVING_WINDOW:
            # Usually evaluates an array of recent points against the baseline average.
            # Simplified for scalar demonstration:
            avg = baseline.calculated_statistics.get("moving_average")
            margin = baseline.parameters.get("margin")
            if avg is not None and margin is not None:
                if abs(val - avg) > margin:
                    return self._create_anomaly(identity, baseline, val, abs(val - avg), evidence, AnomalyType.TREND)

        return None
        
    def _create_anomaly(self, identity: Identity, baseline: AnomalyBaseline, val: float, score: float, evidence: AnomalyEvidence, a_type: AnomalyType) -> AnomalyDetection:
        
        # Calculate severity based on score magnitude if possible
        severity = AnomalySeverity.LOW
        if score > 10:
            severity = AnomalySeverity.CRITICAL
        elif score > 7:
            severity = AnomalySeverity.HIGH
        elif score > 5:
            severity = AnomalySeverity.MEDIUM
            
        fingerprint_raw = f"{baseline.tenant_id}:{baseline.entity_id}:{baseline.metric}:{baseline.detector_method.value}:{baseline.context}:{baseline.version}"
        fingerprint = hashlib.sha256(fingerprint_raw.encode()).hexdigest()
        
        return AnomalyDetection(
            anomaly_id=f"anom_{uuid.uuid4().hex[:12]}",
            tenant_id=identity.tenant_id,
            workspace_id=identity.workspace_id,
            plant_id=getattr(identity, 'plant_id', None),
            entity_id=baseline.entity_id,
            metric=baseline.metric,
            type=a_type,
            status=AnomalyStatus.DETECTED,
            severity=severity,
            detector_method=baseline.detector_method,
            anomaly_score=round(score, 4),
            evidence=[evidence],
            fingerprint=fingerprint
        )
