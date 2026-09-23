import pytest
import os
import ast
import uuid
import json
from datetime import datetime, UTC, timedelta
from fastapi.testclient import TestClient

from core.auth import get_current_identity
from data.schemas.authorization_contract import UserIdentity
from data.schemas.supplier_risk_contract import (
    SupplierRiskAssessment, 
    SupplierRiskStatus, 
    SupplierRiskConfidence,
    RiskFactor,
    SupplierRiskEvidence,
    AnalyticalObservation
)
from services.supplier_risk_service import supplier_risk_service
from services.supplier_risk_repository import supplier_risk_repository
from server import app

# Create a test client
client = TestClient(app)

class TestSupplierRiskFoundation:
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        # Override auth for testing
        self.tenant_id = f"tenant_{uuid.uuid4().hex[:8]}"
        self.user_identity = UserIdentity(
            user_id="test_user",
            tenant_id=self.tenant_id,
            roles=["ANALYST"]
        )
        app.dependency_overrides[get_current_identity] = lambda: self.user_identity
        
        yield
        
        app.dependency_overrides.clear()
        
    def _create_observation(self, obs_type, status, days_ago=1):
        dt = datetime.now(UTC) - timedelta(days=days_ago)
        return {
            "type": obs_type,
            "status": status,
            "timestamp": dt.isoformat().replace("+00:00", "Z")
        }

    # ---------------------------------------------------------
    # 1. Execution Boundary Tests (1-5)
    # ---------------------------------------------------------
    def test_001_no_execution_gateway_import(self):
        service_file = os.path.join(os.path.dirname(__file__), "services", "supplier_risk_service.py")
        with open(service_file, "r") as f:
            tree = ast.parse(f.read())
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "ExecutionGateway" not in alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "ExecutionGateway" not in node.module
                
    def test_002_no_action_api_import(self):
        service_file = os.path.join(os.path.dirname(__file__), "services", "supplier_risk_service.py")
        with open(service_file, "r") as f:
            content = f.read()
        assert "action" not in content.lower() or "action_api" not in content.lower()

    def test_003_observation_must_not_be_executable(self):
        obs = AnalyticalObservation(observation_type="TEST", description="test")
        assert obs.executable is False
        
    def test_004_analytical_observation_enforces_read_only(self):
        with pytest.raises(Exception):
            AnalyticalObservation(observation_type="TEST", description="test", executable=True)
            
    def test_005_service_is_side_effect_free(self):
        assert not hasattr(supplier_risk_service, "execute_action")

    # ---------------------------------------------------------
    # 2. Schema Validation Tests (6-15)
    # ---------------------------------------------------------
    def test_006_schema_requires_tenant_id(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=0.0, confidence="LOW")
            
    def test_007_schema_requires_supplier_id(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=0.0, confidence="LOW")

    def test_008_schema_requires_as_of_timestamp(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", risk_status="LOW", risk_score=0.0, confidence="LOW")

    def test_009_risk_status_enum_validation(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="INVALID", risk_score=0.0, confidence="LOW")

    def test_010_risk_score_bounds_ge_0(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=-1.0, confidence="LOW")

    def test_011_risk_score_bounds_le_100(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=101.0, confidence="LOW")

    def test_012_confidence_enum_validation(self):
        with pytest.raises(ValueError):
            SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=0.0, confidence="INVALID")

    def test_013_factor_score_bounds(self):
        with pytest.raises(ValueError):
            RiskFactor(factor_name="test", score=101.0, weight=0.5)

    def test_014_evidence_confidence_bounds(self):
        with pytest.raises(ValueError):
            SupplierRiskEvidence(factor_type="t", source="s", source_id="s", supplier_id="sup", timestamp="t", observed_value=1, confidence=1.5)

    def test_015_schema_default_methodology(self):
        a = SupplierRiskAssessment(tenant_id="t1", supplier_id="sup1", as_of_timestamp="2024-01-01T00:00:00Z", risk_status="LOW", risk_score=0.0, confidence="LOW")
        assert a.methodology == "deterministic_weighted_sum"

    # ---------------------------------------------------------
    # 3. Temporal Boundary / Leakage Tests (16-25)
    # ---------------------------------------------------------
    def test_016_as_of_timestamp_enforces_strict_cutoff(self):
        as_of = (datetime.now(UTC) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
        obs_future = self._create_observation("delivery", "late", days_ago=2) # Occurs AFTER as_of
        obs_past = self._create_observation("delivery", "late", days_ago=10) # Occurs BEFORE as_of
        
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs_future, obs_past])
        # Only the past observation should be counted. If both were counted, score would be higher.
        # Since only one observation is valid, total delivery = 1, late = 1 => 100% late.
        assert assessment.factors[0].score == 100.0

    def test_017_future_observations_are_ignored(self):
        as_of = (datetime.now(UTC) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
        obs_future = self._create_observation("delivery", "late", days_ago=2)
        
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs_future])
        assert assessment.risk_status == SupplierRiskStatus.UNKNOWN
        
    def test_018_missing_timestamp_reported_as_data_quality(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs_bad = {"type": "delivery", "status": "late"}
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs_bad])
        assert any("Missing timestamp" in dq for dq in assessment.data_quality_issues)
        
    def test_019_invalid_timestamp_reported_as_data_quality(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs_bad = {"type": "delivery", "status": "late", "timestamp": "invalid_date"}
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs_bad])
        assert any("Invalid timestamp" in dq for dq in assessment.data_quality_issues)

    def test_020_invalid_as_of_timestamp_raises_error(self):
        with pytest.raises(ValueError):
            supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", "invalid_as_of", [])

    def test_021_exact_boundary_inclusion(self):
        as_of_dt = datetime.now(UTC) - timedelta(days=5)
        as_of = as_of_dt.isoformat().replace("+00:00", "Z")
        obs = {"type": "delivery", "status": "late", "timestamp": as_of}
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs])
        assert assessment.factors[0].score == 100.0
        
    def test_022_timezone_normalization(self):
        as_of = "2024-01-01T12:00:00Z"
        obs = {"type": "delivery", "status": "late", "timestamp": "2024-01-01T12:00:00+00:00"}
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs])
        assert assessment.risk_status != SupplierRiskStatus.UNKNOWN

    def test_023_timezone_offset_handling(self):
        as_of = "2024-01-01T12:00:00Z" # UTC noon
        obs = {"type": "delivery", "status": "late", "timestamp": "2024-01-01T07:00:00-05:00"} # EST 7am = UTC noon
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs])
        assert assessment.risk_status != SupplierRiskStatus.UNKNOWN

    def test_024_temporal_ordering_independence(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs1 = self._create_observation("delivery", "late", days_ago=2)
        obs2 = self._create_observation("delivery", "on_time", days_ago=4)
        a1 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs1, obs2])
        a2 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [obs2, obs1])
        assert a1.input_fingerprint == a2.input_fingerprint

    def test_025_temporal_fingerprint_inclusion(self):
        as_of1 = "2024-01-01T00:00:00Z"
        as_of2 = "2024-01-02T00:00:00Z"
        a1 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of1, [])
        a2 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of2, [])
        assert a1.input_fingerprint != a2.input_fingerprint

    # ---------------------------------------------------------
    # 4. Delivery Risk Tests (26-30)
    # ---------------------------------------------------------
    def test_026_delivery_risk_perfect_score(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(10)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "delivery_reliability")
        assert factor.score == 0.0

    def test_027_delivery_risk_moderate_score(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(8)] + [self._create_observation("delivery", "late") for _ in range(2)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "delivery_reliability")
        assert factor.score == 40.0  # 20% late * 200 = 40

    def test_028_delivery_risk_high_score(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(5)] + [self._create_observation("delivery", "late") for _ in range(5)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "delivery_reliability")
        assert factor.score == 100.0  # 50% late * 200 = 100

    def test_029_delivery_risk_max_cap(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "late") for _ in range(10)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "delivery_reliability")
        assert factor.score == 100.0  # 100% late * 200 = 200 -> capped at 100

    def test_030_delivery_warning_observation_generated(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "late") for _ in range(5)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert any(o.observation_type == "DELIVERY_WARNING" for o in assessment.observations)

    # ---------------------------------------------------------
    # 5. Quality Risk Tests (31-35)
    # ---------------------------------------------------------
    def test_031_quality_risk_perfect(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("quality", "passed") for _ in range(10)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "quality")
        assert factor.score == 0.0

    def test_032_quality_risk_moderate(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("quality", "passed") for _ in range(9)] + [self._create_observation("quality", "defective") for _ in range(1)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "quality")
        assert factor.score == 50.0  # 10% defective * 500 = 50

    def test_033_quality_risk_high(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("quality", "passed") for _ in range(8)] + [self._create_observation("quality", "defective") for _ in range(2)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "quality")
        assert factor.score == 100.0  # 20% defective * 500 = 100

    def test_034_quality_risk_max_cap(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("quality", "defective") for _ in range(10)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "quality")
        assert factor.score == 100.0 

    def test_035_quality_warning_observation_generated(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("quality", "passed") for _ in range(8)] + [self._create_observation("quality", "defective") for _ in range(2)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert any(o.observation_type == "QUALITY_WARNING" for o in assessment.observations)

    # ---------------------------------------------------------
    # 6. Capacity / Incident Tests (36-40)
    # ---------------------------------------------------------
    def test_036_capacity_risk_none(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time")] # No disruptions
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert not any(f.factor_name == "capacity_disruption" for f in assessment.factors)

    def test_037_capacity_risk_single_incident(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("disruption", "severe")]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "capacity_disruption")
        assert factor.score == 25.0

    def test_038_capacity_risk_multiple_incidents(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("disruption", "severe") for _ in range(4)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "capacity_disruption")
        assert factor.score == 100.0

    def test_039_capacity_risk_shortfalls(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("shortfall", "minor")]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "capacity_disruption")
        assert factor.score == 25.0

    def test_040_capacity_warning_generated(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("disruption", "severe")]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert any(o.observation_type == "CAPACITY_WARNING" for o in assessment.observations)

    # ---------------------------------------------------------
    # 7. Concentration / Exposure Tests (41-45)
    # ---------------------------------------------------------
    def test_041_concentration_risk_single_source(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [{"type": "kg_context", "single_source": True, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "concentration")
        assert factor.score == 100.0
        assert assessment.exposure_summary.single_source_exposure is True

    def test_042_concentration_risk_multi_plant(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [{"type": "kg_context", "affected_plant_count": 3, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        factor = next(f for f in assessment.factors if f.factor_name == "concentration")
        assert factor.score == 60.0 # 3 plants * 20 = 60
        assert assessment.exposure_summary.affected_plant_count == 3

    def test_043_concentration_risk_none(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [{"type": "kg_context", "affected_plant_count": 1, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert not any(f.factor_name == "concentration" for f in assessment.factors)

    def test_044_exposure_metrics_aggregation(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [{"type": "exposure", "affected_sku_count": 100, "forecast_exposure_units": 5000, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.exposure_summary.affected_sku_count == 100
        assert assessment.exposure_summary.forecast_exposure_units == 5000

    def test_045_concentration_warning_generated(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [{"type": "kg_context", "single_source": True, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert any(o.observation_type == "CONCENTRATION_WARNING" for o in assessment.observations)

    # ---------------------------------------------------------
    # 8. Confidence and Uncertainty Tests (46-50)
    # ---------------------------------------------------------
    def test_046_insufficient_data(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, [])
        assert assessment.confidence == SupplierRiskConfidence.INSUFFICIENT_DATA
        assert assessment.risk_status == SupplierRiskStatus.UNKNOWN

    def test_047_low_confidence(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(5)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.confidence == SupplierRiskConfidence.LOW

    def test_048_medium_confidence(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(15)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.confidence == SupplierRiskConfidence.MEDIUM

    def test_049_high_confidence(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(55)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.confidence == SupplierRiskConfidence.HIGH

    def test_050_uncertainty_explanation_exists(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(5)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert len(assessment.uncertainty) > 0

    # ---------------------------------------------------------
    # 9. Overall Risk Status Aggregation (51-55)
    # ---------------------------------------------------------
    def test_051_overall_risk_low(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time") for _ in range(10)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.risk_status == SupplierRiskStatus.LOW

    def test_052_overall_risk_medium(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # Delivery 20% late (score 40, weight 0.3) -> Total = 40 -> MEDIUM
        obs = [self._create_observation("delivery", "late") for _ in range(2)] + [self._create_observation("delivery", "on_time") for _ in range(8)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.risk_status == SupplierRiskStatus.MEDIUM

    def test_053_overall_risk_high(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # Delivery 30% late (score 60, weight 0.3) -> Total = 60 -> HIGH
        obs = [self._create_observation("delivery", "late") for _ in range(3)] + [self._create_observation("delivery", "on_time") for _ in range(7)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.risk_status == SupplierRiskStatus.HIGH

    def test_054_overall_risk_critical(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        # Everything goes wrong
        obs = [self._create_observation("delivery", "late") for _ in range(5)] + \
              [self._create_observation("quality", "defective") for _ in range(5)] + \
              [self._create_observation("disruption", "severe") for _ in range(4)] + \
              [{"type": "kg_context", "single_source": True, "timestamp": as_of}]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert assessment.risk_status == SupplierRiskStatus.CRITICAL

    def test_055_overall_score_aggregation(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "late") for _ in range(5)]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        # delivery score 100, weight 0.3. Only one factor. Average is 100.
        assert assessment.risk_score == 100.0

    # ---------------------------------------------------------
    # 10. Persistence and Isolation Tests (56-65)
    # ---------------------------------------------------------
    def test_056_persistence_saves_to_db(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time")]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        fetched = supplier_risk_repository.get_assessment(assessment.assessment_id, self.tenant_id)
        assert fetched is not None
        assert fetched.assessment_id == assessment.assessment_id

    def test_057_multi_tenant_isolation_get(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time")]
        assessment = supplier_risk_service.analyze_supplier_risk("tenantA", "sup1", as_of, obs)
        fetched = supplier_risk_repository.get_assessment(assessment.assessment_id, "tenantB")
        assert fetched is None # Tenant B cannot see Tenant A's assessment

    def test_058_multi_tenant_isolation_history(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time")]
        supplier_risk_service.analyze_supplier_risk("tenantA", "sup_shared", as_of, obs)
        history_b = supplier_risk_repository.get_history("sup_shared", "tenantB")
        assert len(history_b) == 0

    def test_059_deterministic_fingerprint_idempotency(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "on_time")]
        a1 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        a2 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert a1.assessment_id == a2.assessment_id # Should return the same assessment from DB

    def test_060_fingerprint_changes_on_input_change(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs1 = [self._create_observation("delivery", "on_time")]
        obs2 = [self._create_observation("delivery", "late")]
        a1 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup2", as_of, obs1)
        a2 = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup2", as_of, obs2)
        assert a1.assessment_id != a2.assessment_id

    def test_061_history_ordering(self):
        obs = [self._create_observation("delivery", "on_time")]
        as_of1 = (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
        as_of2 = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup3", as_of1, obs)
        supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup3", as_of2, obs)
        
        history = supplier_risk_service.get_history(self.tenant_id, "sup3")
        assert len(history) >= 2
        assert history[0].as_of_timestamp == as_of2 # Descending order

    def test_062_latest_assessment(self):
        obs = [self._create_observation("delivery", "on_time")]
        as_of1 = (datetime.now(UTC) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
        as_of2 = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup4", as_of1, obs)
        supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup4", as_of2, obs)
        
        latest = supplier_risk_repository.get_latest_assessment("sup4", self.tenant_id)
        assert latest.as_of_timestamp == as_of2

    def test_063_get_summary(self):
        obs = [self._create_observation("delivery", "on_time")]
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        a = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup5", as_of, obs)
        
        summary = supplier_risk_service.get_summary(self.tenant_id, "sup5")
        assert summary["supplier_id"] == "sup5"
        assert summary["risk_status"] == a.risk_status.value
        assert summary["fingerprint"] == a.input_fingerprint

    def test_064_get_summary_not_found(self):
        summary = supplier_risk_service.get_summary(self.tenant_id, "sup_non_existent")
        assert summary is None

    def test_065_repository_history_limit(self):
        obs = [self._create_observation("delivery", "on_time")]
        # Create 3 assessments
        for i in range(3):
            as_of = (datetime.now(UTC) - timedelta(days=i)).isoformat().replace("+00:00", "Z")
            supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup6", as_of, obs)
            
        history = supplier_risk_service.get_history(self.tenant_id, "sup6", limit=2)
        assert len(history) == 2

    # ---------------------------------------------------------
    # 11. API / Routing Tests (66-75)
    # ---------------------------------------------------------
    def test_066_api_analyze_success(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "supplier_id": "api_sup1",
            "as_of_timestamp": as_of,
            "observations": [self._create_observation("delivery", "on_time")]
        }
        response = client.post("/api/v3/supplier-risk/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["supplier_id"] == "api_sup1"
        assert data["risk_status"] == "LOW"

    def test_067_api_analyze_rbac_denied(self):
        # Override to read-only user
        app.dependency_overrides[get_current_identity] = lambda: UserIdentity(
            user_id="read_user", tenant_id=self.tenant_id, roles=["VIEWER"]
        )
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "supplier_id": "api_sup1",
            "as_of_timestamp": as_of,
            "observations": []
        }
        response = client.post("/api/v3/supplier-risk/analyze", json=payload)
        assert response.status_code == 403
        app.dependency_overrides[get_current_identity] = lambda: self.user_identity

    def test_068_api_get_specific_assessment(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "supplier_id": "api_sup2",
            "as_of_timestamp": as_of,
            "observations": [self._create_observation("delivery", "on_time")]
        }
        res1 = client.post("/api/v3/supplier-risk/analyze", json=payload)
        assessment_id = res1.json()["assessment_id"]
        
        res2 = client.get(f"/api/v3/supplier-risk/assessment/{assessment_id}")
        assert res2.status_code == 200
        assert res2.json()["assessment_id"] == assessment_id

    def test_069_api_get_specific_assessment_not_found(self):
        res = client.get("/api/v3/supplier-risk/assessment/non_existent_id")
        assert res.status_code == 404

    def test_070_api_get_summary(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "supplier_id": "api_sup3",
            "as_of_timestamp": as_of,
            "observations": [self._create_observation("delivery", "on_time")]
        }
        client.post("/api/v3/supplier-risk/analyze", json=payload)
        
        res = client.get("/api/v3/supplier-risk/suppliers/api_sup3/summary")
        assert res.status_code == 200
        assert res.json()["supplier_id"] == "api_sup3"

    def test_071_api_get_summary_not_found(self):
        res = client.get("/api/v3/supplier-risk/suppliers/api_sup_none/summary")
        assert res.status_code == 404

    def test_072_api_get_history(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        payload = {
            "supplier_id": "api_sup4",
            "as_of_timestamp": as_of,
            "observations": [self._create_observation("delivery", "on_time")]
        }
        client.post("/api/v3/supplier-risk/analyze", json=payload)
        
        res = client.get("/api/v3/supplier-risk/suppliers/api_sup4/history?limit=5")
        assert res.status_code == 200
        assert len(res.json()) >= 1

    def test_073_api_analyze_invalid_timestamp(self):
        payload = {
            "supplier_id": "api_sup5",
            "as_of_timestamp": "invalid_date",
            "observations": []
        }
        res = client.post("/api/v3/supplier-risk/analyze", json=payload)
        assert res.status_code == 400

    def test_074_evidence_generation(self):
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [self._create_observation("delivery", "late")]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup1", as_of, obs)
        assert len(assessment.evidence) > 0
        ev = assessment.evidence[0]
        assert ev.factor_type == "delivery_reliability"
        assert ev.supplier_id == "sup1"

    def test_075_all_deterministic_factors_present(self):
        # Trigger all factors
        as_of = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        obs = [
            self._create_observation("delivery", "late"),
            self._create_observation("quality", "defective"),
            self._create_observation("disruption", "severe"),
            {"type": "kg_context", "single_source": True, "timestamp": as_of}
        ]
        assessment = supplier_risk_service.analyze_supplier_risk(self.tenant_id, "sup_all", as_of, obs)
        factors = [f.factor_name for f in assessment.factors]
        assert "delivery_reliability" in factors
        assert "quality" in factors
        assert "capacity_disruption" in factors
        assert "concentration" in factors
