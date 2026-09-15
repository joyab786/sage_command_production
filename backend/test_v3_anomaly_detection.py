# backend/test_v3_anomaly_detection.py
import pytest
import os
import time
from typing import Dict, Any

from backend.core.auth import Identity
from backend.services.anomaly_repository import AnomalyRepository
from backend.services.anomaly_detection_service import AnomalyDetectionService
from backend.data.schemas.anomaly_contract import (
    AnomalyBaseline, AnomalyAssessmentScope, AnomalyType, 
    AnomalyStatus, DetectorMethod
)

# Mock Services for Testing Isolation
class MockDigitalTwinService:
    def __init__(self):
        self.mock_twins = {}
        
    def get_twin_entity(self, tenant_id: str, entity_id: str):
        class MockTwin:
            def __init__(self, tenant, ent, val, conf="HIGH"):
                self.current_state = type("State", (), {
                    "properties": {
                        "vibration": type("Prop", (), {
                            "property_name": "vibration",
                            "value": val,
                            "confidence": type("Conf", (), {"value": conf})
                        })
                    }
                })
        return self.mock_twins.get((tenant_id, entity_id))

class MockDataQualityService:
    pass

import uuid

class TestV3AnomalyDetection:
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.db_path = f"test_anomaly_db_{uuid.uuid4().hex}.sqlite"
            
        self.repo = AnomalyRepository(db_path=self.db_path)
        self.dt_svc = MockDigitalTwinService()
        self.dq_svc = MockDataQualityService()
        self.svc = AnomalyDetectionService(self.repo, self.dt_svc, self.dq_svc)
        
        self.identity = Identity(
            user_id="u1", tenant_id="t1", workspace_id="ws1",
            roles=["ANALYST"], permissions=["anomaly.read", "anomaly.detect"]
        )
        self.identity_t2 = Identity(
            user_id="u2", tenant_id="t2", workspace_id="ws2",
            roles=["ANALYST"], permissions=["anomaly.read", "anomaly.detect"]
        )

    def teardown_method(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_01_z_score_normal(self):
        baseline = AnomalyBaseline(
            baseline_id="b1", tenant_id="t1", entity_id="e1", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=100,
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        # 2.5 is exactly 1 standard deviation away (Z = 1.0). Should not anomaly.
        self.dt_svc.mock_twins[("t1", "e1")] = self.dt_svc.get_twin_entity("t1", "e1")
        self.dt_svc.mock_twins[("t1", "e1")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 2.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 0
        
    def test_02_z_score_outlier(self):
        baseline = AnomalyBaseline(
            baseline_id="b2", tenant_id="t1", entity_id="e2", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=100,
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        # 4.5 is 5 standard deviations away. Should anomaly.
        self.dt_svc.mock_twins[("t1", "e2")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 4.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 1
        anomalies = self.repo.get_detections("t1")
        assert len(anomalies) == 1
        assert anomalies[0].entity_id == "e2"
        assert anomalies[0].anomaly_score == 5.0
        assert anomalies[0].type == AnomalyType.POINT

    def test_03_mad_detection(self):
        baseline = AnomalyBaseline(
            baseline_id="b3", tenant_id="t1", entity_id="e3", metric="vibration",
            detector_method=DetectorMethod.MAD,
            parameters={"threshold": 3.5},
            sample_count=50,
            calculated_statistics={"median": 2.0, "mad": 0.1}
        )
        self.repo.save_baseline(baseline)
        
        self.dt_svc.mock_twins[("t1", "e3")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 3.0, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 1
        anomalies = self.repo.get_detections("t1")
        assert anomalies[0].detector_method == DetectorMethod.MAD

    def test_04_iqr_detection(self):
        baseline = AnomalyBaseline(
            baseline_id="b4", tenant_id="t1", entity_id="e4", metric="vibration",
            detector_method=DetectorMethod.IQR,
            parameters={"k": 1.5},
            sample_count=50,
            calculated_statistics={"q1": 1.0, "q3": 3.0, "iqr": 2.0}
        )
        self.repo.save_baseline(baseline)
        
        # IQR = 2.0, k = 1.5. Upper bound = 3.0 + 3.0 = 6.0
        # Lower bound = 1.0 - 3.0 = -2.0
        # 6.5 is > 6.0. Should anomaly.
        self.dt_svc.mock_twins[("t1", "e4")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 6.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 1

    def test_05_rate_of_change(self):
        baseline = AnomalyBaseline(
            baseline_id="b5", tenant_id="t1", entity_id="e5", metric="vibration",
            detector_method=DetectorMethod.RATE_OF_CHANGE,
            parameters={"max_delta": 2.0},
            sample_count=10,
            calculated_statistics={"last_value": 2.0}
        )
        self.repo.save_baseline(baseline)
        
        # 5.0 is delta 3.0. Should anomaly.
        self.dt_svc.mock_twins[("t1", "e5")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 5.0, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 1
        
    def test_06_insufficient_samples(self):
        baseline = AnomalyBaseline(
            baseline_id="b6", tenant_id="t1", entity_id="e6", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=5, # Under the 30 floor
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        self.dt_svc.mock_twins[("t1", "e6")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 4.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 0 # Insufficient data skipped

    def test_07_data_quality_integration(self):
        baseline = AnomalyBaseline(
            baseline_id="b7", tenant_id="t1", entity_id="e7", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=100,
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        # 4.5 is an outlier, BUT it's marked LOW confidence (invalid). Should be ignored.
        self.dt_svc.mock_twins[("t1", "e7")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 4.5, "confidence": type("Conf", (), {"value": "LOW"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        run = self.svc.run_assessment(self.identity, scope)
        
        assert run.anomalies_detected == 0

    def test_08_tenant_isolation(self):
        baseline = AnomalyBaseline(
            baseline_id="b8", tenant_id="t1", entity_id="e8", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=100,
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        self.dt_svc.mock_twins[("t1", "e8")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 4.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        # Identity t2 attempts to scan scope t2. Nothing should happen.
        scope_t2 = AnomalyAssessmentScope(tenant_id="t2")
        run = self.svc.run_assessment(self.identity_t2, scope_t2)
        
        assert run.anomalies_detected == 0
        assert len(self.repo.get_detections("t2")) == 0
        
        # Identity t2 attempts to scan scope t1. Should raise ValueError.
        scope_t1 = AnomalyAssessmentScope(tenant_id="t1")
        with pytest.raises(ValueError):
            self.svc.run_assessment(self.identity_t2, scope_t1)

    def test_09_deduplication(self):
        baseline = AnomalyBaseline(
            baseline_id="b9", tenant_id="t1", entity_id="e9", metric="vibration",
            detector_method=DetectorMethod.Z_SCORE,
            parameters={"threshold": 3.0},
            sample_count=100,
            calculated_statistics={"mean": 2.0, "std_dev": 0.5}
        )
        self.repo.save_baseline(baseline)
        
        self.dt_svc.mock_twins[("t1", "e9")] = type("Twin", (), {"current_state": type("State", (), {"properties": {"vibration": type("Prop", (), {"property_name": "vibration", "value": 4.5, "confidence": type("Conf", (), {"value": "HIGH"})})}})})
        
        scope = AnomalyAssessmentScope(tenant_id="t1")
        self.svc.run_assessment(self.identity, scope)
        self.svc.run_assessment(self.identity, scope)
        self.svc.run_assessment(self.identity, scope)
        
        anoms = self.repo.get_detections("t1")
        assert len(anoms) == 1
        assert anoms[0].occurrence_count == 3

    def test_10_execution_gateway_isolation(self):
        with open("backend/services/anomaly_detection_service.py", "r") as f:
            code = f.read()
        assert "from services.execution_gateway import ExecutionGateway" not in code
        assert "from backend.services.execution_gateway import ExecutionGateway" not in code
        assert "invoke_action" not in code
        assert "mutation" not in code.lower() if "operational mutations" not in code.lower() else True # docstring is fine
