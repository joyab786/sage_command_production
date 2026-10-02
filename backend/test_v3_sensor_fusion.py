"""
backend/test_v3_sensor_fusion.py

SageCommand V3 — Multimodal Sensor Fusion Intelligence Foundation Test Suite (Prompt 27)

ANALYTICAL ONLY.
Mandatory Comprehensive Test Suite covering:
1. Contracts & Schema Validation
2. Controlled Modalities & Measurement Types
3. Unit Safety & Deterministic Conversion (Temperature, Pressure, Electrical, Acoustic, Vibration)
4. Provenance Invariants & Non-Conversion of Simulated Data
5. Temporal Modeling & Strict Future-Leakage Protection
6. Deterministic Temporal Alignment (Exact, Nearest, Window, Resampled)
7. Evidence Independence & Anti-Double-Counting Protection
8. Upstream Integrations (Data Quality, Anomaly Engine, Digital Twin, Ontology, Knowledge Graph)
9. Multimodal Domain Matrix (Thermal vs Numeric Temp, Vibration, Pressure, Electrical Sanity, Visual, Acoustic)
10. Cross-Modal Correlation (Pearson r, Significance, Directional Agreement, Sample Count Bounds)
11. Agreement & Disagreement Matrix (Corroboration, Material Conflict, Partial Agreement, Insufficient Evidence)
12. Fusion Strategies (Weighted Evidence, Normalized Score, Consensus, Contextual)
13. Deterministic Weighting Rules & Versioning
14. Confidence & Uncertainty Quantification
15. Sensor Health & Reliability Indicators (Stale, Flatline, Out-of-bounds, Noise)
16. Deterministic SHA-256 Input Fingerprinting & Idempotency
17. SQLite WAL Repository Persistence, Tenant/Plant Isolation, & Deduplication
18. API Endpoints, Parameters, Bounded Limits, & Error Responses
19. RBAC & ABAC Security (Tenant Mismatch, Plant Boundaries, Role Checks)
20. Non-Negotiable Execution Boundary & Static AST Verification (Zero ExecutionGateway imports)

TEST ISOLATION RULE:
All mocks use local context managers / fixtures. NO module-level monkeypatching of authorization.
"""

import ast
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from core.auth import Identity
from data.schemas.authorization_contract import (
    AuthorizationDecision,
    AuthzDecisionEffect,
    AuthzReasonCode,
)
from data.schemas.sensor_fusion_contract import (
    Modality,
    MeasurementType,
    SensorValueProvenance,
    AgreementStatus,
    AlignmentStrategy,
    FusionStrategy,
    SensorHealthStatus,
    FusionConfidence,
    FusionUncertainty,
    SensorObservation,
    NormalizedObservation,
    FusionEvidence,
    FusedObservation,
    CrossModalCorrelation,
    CrossModalAgreement,
    SensorHealthIndicator,
    WeightingRule,
    EvaluationWindow,
    FusionAssessment,
    SensorFusionAnalyzeRequest,
    convert_unit,
    are_units_compatible,
    normalize_unit_string,
    compute_sensor_fusion_fingerprint,
    CANONICAL_BASE_UNITS,
)
from services.sensor_fusion_repository import SensorFusionRepository, sensor_fusion_repository
from services.sensor_fusion_service import SensorFusionService, sensor_fusion_service, CANONICAL_WEIGHTING_RULES
import server


# =============================================================================
# FIXTURES (Strictly Scoped — No Global Monkeypatching)
# =============================================================================

@pytest.fixture
def temp_db_path(tmp_path):
    """Provides a fresh isolated SQLite DB for each test."""
    db_file = tmp_path / "test_sensor_fusion.sqlite"
    return str(db_file)


@pytest.fixture
def isolated_repo(temp_db_path):
    """Provides an isolated SensorFusionRepository instance."""
    return SensorFusionRepository(db_path=temp_db_path)


@pytest.fixture
def isolated_service(isolated_repo):
    """Provides a SensorFusionService bound to the isolated repo."""
    return SensorFusionService(repo=isolated_repo)


@pytest.fixture
def test_client():
    """Provides FastAPI test client for API route testing."""
    return TestClient(server.app)


def _make_identity(
    user_id: str = "test_analyst",
    tenant_id: str = "tenant_test",
    workspace_id: str = "workspace_test",
    roles: Optional[List[str]] = None,
    assigned_plants: Optional[List[str]] = None,
) -> Identity:
    return Identity(
        user_id=user_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        roles=roles or ["ANALYST"],
        assigned_plants=assigned_plants or ["*"],
    )


def _allow_decision(perm: str = "sensor_fusion.read") -> AuthorizationDecision:
    return AuthorizationDecision.create(
        effect=AuthzDecisionEffect.ALLOW,
        reason_code=AuthzReasonCode.ALLOWED,
        reason="Granted for test",
        required_permission=perm,
        matched_role="ANALYST",
        resolved_permissions=[perm],
    )


def _deny_decision(perm: str = "sensor_fusion.read") -> AuthorizationDecision:
    return AuthorizationDecision.create(
        effect=AuthzDecisionEffect.DENY,
        reason_code=AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS,
        reason="Denied for test",
        required_permission=perm,
        resolved_permissions=[],
    )


# =============================================================================
# 1. CONTRACTS & SCHEMA TESTS
# =============================================================================

def test_sensor_observation_valid_creation():
    """Validates creation of a fully specified SensorObservation."""
    obs = SensorObservation(
        observation_id="obs_001",
        tenant_id="tenant_01",
        workspace_id="ws_01",
        plant_id="plant_01",
        entity_id="MCH-PUMP-01",
        sensor_id="TEMP-01",
        modality=Modality.TEMPERATURE,
        measurement_type=MeasurementType.TEMPERATURE,
        value=78.5,
        unit="CELSIUS",
        observed_at="2026-10-02T10:00:00Z",
        provenance=SensorValueProvenance.OBSERVED,
        confidence=0.95,
        quality=0.98,
    )
    assert obs.observation_id == "obs_001"
    assert obs.modality == Modality.TEMPERATURE
    assert obs.provenance == SensorValueProvenance.OBSERVED


def test_sensor_observation_empty_timestamp_rejected():
    """Validates that empty timestamp raises ValueError."""
    with pytest.raises(Exception):
        SensorObservation(
            observation_id="obs_002",
            tenant_id="tenant_01",
            entity_id="MCH-01",
            sensor_id="S-01",
            modality=Modality.PRESSURE,
            measurement_type=MeasurementType.PRESSURE,
            value=10.0,
            observed_at="",
        )


def test_controlled_modality_enum_completeness():
    """Ensures all 12 mandatory industrial modalities exist."""
    required = {
        "NUMERIC_TELEMETRY", "VIBRATION", "TEMPERATURE", "PRESSURE",
        "ELECTRICAL", "ACOUSTIC", "VISUAL", "THERMAL", "PROCESS",
        "EVENT", "ANOMALY", "DIGITAL_TWIN"
    }
    present = {m.value for m in Modality}
    assert required.issubset(present)


def test_measurement_types_exist():
    """Ensures essential physical measurement categories are defined."""
    assert MeasurementType.TEMPERATURE.value == "TEMPERATURE"
    assert MeasurementType.PRESSURE.value == "PRESSURE"
    assert MeasurementType.VIBRATION_RMS.value == "VIBRATION_RMS"
    assert MeasurementType.CURRENT.value == "CURRENT"
    assert MeasurementType.ACOUSTIC_LEVEL.value == "ACOUSTIC_LEVEL"


# =============================================================================
# 2. UNIT SAFETY & DETERMINISTIC CONVERSION TESTS (Section 7)
# =============================================================================

def test_unit_normalization_casing_and_synonyms():
    """Checks uppercase normalization and synonym mapping."""
    assert normalize_unit_string("c") == "CELSIUS"
    assert normalize_unit_string("°c") == "CELSIUS"
    assert normalize_unit_string("F") == "FAHRENHEIT"
    assert normalize_unit_string("bar") == "BAR"
    assert normalize_unit_string("psi") == "PSI"
    assert normalize_unit_string("mA") == "MILLIAMPERE"
    assert normalize_unit_string(None) is None


def test_unit_compatibility_same_family():
    """Compatible units in the same family evaluate to True."""
    assert are_units_compatible("CELSIUS", "FAHRENHEIT") is True
    assert are_units_compatible("C", "K") is True
    assert are_units_compatible("BAR", "PSI") is True
    assert are_units_compatible("PA", "KPA") is True
    assert are_units_compatible("A", "MA") is True
    assert are_units_compatible("V", "KV") is True
    assert are_units_compatible("W", "KW") is True


def test_unit_incompatibility_across_families():
    """Incompatible units from different physical dimensions evaluate to False."""
    assert are_units_compatible("CELSIUS", "BAR") is False
    assert are_units_compatible("PSI", "VOLT") is False
    assert are_units_compatible("AMPERE", "WATT") is False
    assert are_units_compatible("MM/S", "RPM") is False
    assert are_units_compatible("CELSIUS", None) is False


def test_convert_temperature_celsius_to_fahrenheit():
    """Exact conversion: 100°C -> 212°F."""
    val, success, _ = convert_unit(100.0, "CELSIUS", "FAHRENHEIT")
    assert success is True
    assert val == 212.0


def test_convert_temperature_fahrenheit_to_celsius():
    """Exact conversion: 32°F -> 0°C."""
    val, success, _ = convert_unit(32.0, "FAHRENHEIT", "CELSIUS")
    assert success is True
    assert val == 0.0


def test_convert_temperature_celsius_to_kelvin():
    """Exact conversion: 0°C -> 273.15 K."""
    val, success, _ = convert_unit(0.0, "CELSIUS", "KELVIN")
    assert success is True
    assert val == 273.15


def test_convert_pressure_bar_to_psi():
    """Exact conversion: 10 bar -> ~145.038 psi."""
    val, success, _ = convert_unit(10.0, "BAR", "PSI")
    assert success is True
    assert abs(val - 145.037738) < 0.001


def test_convert_pressure_psi_to_bar():
    """Exact conversion: 14.50377 psi -> ~1 bar."""
    val, success, _ = convert_unit(14.5037738, "PSI", "BAR")
    assert success is True
    assert abs(val - 1.0) < 0.001


def test_convert_pressure_kpa_to_bar():
    """100 kPa -> 1 bar."""
    val, success, _ = convert_unit(100.0, "KPA", "BAR")
    assert success is True
    assert val == 1.0


def test_convert_current_ampere_to_milliampere():
    """2.5 A -> 2500 mA."""
    val, success, _ = convert_unit(2.5, "AMPERE", "MILLIAMPERE")
    assert success is True
    assert val == 2500.0


def test_convert_voltage_kilovolt_to_volt():
    """0.48 kV -> 480 V."""
    val, success, _ = convert_unit(0.48, "KILOVOLT", "VOLT")
    assert success is True
    assert val == 480.0


def test_convert_power_kilowatt_to_watt():
    """15 kW -> 15000 W."""
    val, success, _ = convert_unit(15.0, "KILOWATT", "WATT")
    assert success is True
    assert val == 15000.0


def test_convert_incompatible_units_fails_safely():
    """Attempting conversion between incompatible units fails gracefully."""
    val, success, msg = convert_unit(100.0, "CELSIUS", "BAR")
    assert success is False
    assert val is None
    assert "Incompatible units" in msg


# =============================================================================
# 3. PROVENANCE PRESERVATION TESTS (Section 8)
# =============================================================================

def test_provenance_enums_defined():
    """Ensures OBSERVED, DERIVED, SIMULATED, ESTIMATED, MIXED, UNKNOWN are present."""
    expected = {"OBSERVED", "DERIVED", "SIMULATED", "ESTIMATED", "MIXED", "UNKNOWN"}
    present = {p.value for p in SensorValueProvenance}
    assert expected.issubset(present)


def test_fused_provenance_all_observed_yields_observed(isolated_service):
    """When all contributing observations are OBSERVED, fused observation is OBSERVED."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="o2", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S2", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=72.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert len(result.fused_observations) == 1
    assert result.fused_observations[0].provenance == SensorValueProvenance.OBSERVED


def test_fused_provenance_mixed_sources_yields_mixed(isolated_service):
    """When combining OBSERVED and DERIVED, fused observation provenance is MIXED."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="o2", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S2", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=74.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.DERIVED
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert result.fused_observations[0].provenance == SensorValueProvenance.MIXED


def test_simulated_never_converted_to_observed(isolated_service):
    """Simulated observation stays simulated and never becomes observed."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_sim", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="TWIN-SIM", modality=Modality.DIGITAL_TWIN, measurement_type=MeasurementType.TEMPERATURE,
                value=65.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.SIMULATED
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert result.fused_observations[0].provenance == SensorValueProvenance.SIMULATED
    assert result.provenance == SensorValueProvenance.SIMULATED


# =============================================================================
# 4. TEMPORAL INTEGRITY & FUTURE LEAKAGE TESTS (Section 9, 33, 49)
# =============================================================================

def test_future_observation_strictly_excluded(isolated_service):
    """Observations with observed_at > assessment_timestamp must be rejected/excluded."""
    t_now = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    t_future = datetime(2026, 10, 2, 12, 5, 0, tzinfo=timezone.utc)
    t_past = datetime(2026, 10, 2, 11, 55, 0, tzinfo=timezone.utc)

    ts_now = t_now.isoformat().replace("+00:00", "Z")
    ts_future = t_future.isoformat().replace("+00:00", "Z")
    ts_past = t_past.isoformat().replace("+00:00", "Z")

    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=ts_now,
        evaluation_window_seconds=3600,
        observations=[
            SensorObservation(
                observation_id="obs_valid_past", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=75.0, unit="CELSIUS", observed_at=ts_past, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="obs_leak_future", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S2", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=99.0, unit="CELSIUS", observed_at=ts_future, provenance=SensorValueProvenance.OBSERVED
            )
        ]
    )

    assessment = isolated_service.analyze(req)
    # The future observation must be completely absent from eligible observations
    obs_ids = [o.observation_id for o in assessment.observations]
    assert "obs_valid_past" in obs_ids
    assert "obs_leak_future" not in obs_ids
    assert any("future timestamp" in lim for lim in assessment.limitations)


def test_outside_evaluation_window_excluded(isolated_service):
    """Observations older than assessment_timestamp - window must be excluded."""
    t_now = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
    t_stale = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)  # 2 hours old
    ts_now = t_now.isoformat().replace("+00:00", "Z")
    ts_stale = t_stale.isoformat().replace("+00:00", "Z")

    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=ts_now,
        evaluation_window_seconds=1800,  # 30 minute window
        observations=[
            SensorObservation(
                observation_id="obs_too_old", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=5.0, unit="BAR", observed_at=ts_stale, provenance=SensorValueProvenance.OBSERVED
            )
        ]
    )

    assessment = isolated_service.analyze(req)
    assert len(assessment.observations) == 0
    assert any("prior to evaluation window" in lim for lim in assessment.limitations)


def test_historical_reproducibility(isolated_service):
    """Running identical assessment on historical timestamp produces identical output."""
    t_hist = "2026-09-15T08:00:00Z"
    t_obs = "2026-09-15T07:55:00Z"

    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
            sensor_id="TEMP-01", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=t_obs, provenance=SensorValueProvenance.OBSERVED
        )
    ]

    req1 = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01",
        assessment_timestamp=t_hist, observations=obs
    )
    req2 = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01",
        assessment_timestamp=t_hist, observations=obs
    )

    res1 = isolated_service.analyze(req1)
    res2 = isolated_service.analyze(req2)
    assert res1.input_fingerprint == res2.input_fingerprint
    assert res1.fused_observations[0].fused_value == res2.fused_observations[0].fused_value


# =============================================================================
# 5. EVIDENCE INDEPENDENCE & ANTI-DOUBLE-COUNTING (Section 26, 45)
# =============================================================================

def test_derived_feature_flagged_as_non_independent(isolated_service):
    """A derived observation from the same sensor must be marked non-independent."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="obs_raw_vib", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="VIB-01", modality=Modality.VIBRATION, measurement_type=MeasurementType.VIBRATION_ACCELERATION,
                value=2.4, unit="M/S^2", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="obs_derived_rms", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="VIB-01", modality=Modality.VIBRATION, measurement_type=MeasurementType.VIBRATION_RMS,
                value=4.1, unit="MM/S", observed_at=now, provenance=SensorValueProvenance.DERIVED,
                parent_observation_id="obs_raw_vib", source_lineage=["VIB-01"]
            )
        ]
    )

    result = isolated_service.analyze(req)
    evd_map = {e.observation_id: e for e in result.evidence}
    assert evd_map["obs_raw_vib"].is_independent is True
    assert evd_map["obs_derived_rms"].is_independent is False


def test_duplicate_evidence_does_not_inflate_confidence(isolated_service):
    """Adding a derived copy of the same sensor does not elevate confidence to HIGH."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # Only 1 physical sensor reporting raw and derived features
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=85.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="o2", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=85.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.DERIVED,
                parent_observation_id="o1"
            )
        ]
    )

    result = isolated_service.analyze(req)
    # Confidence must NOT be HIGH because there is only 1 independent modality/sensor
    assert result.confidence != FusionConfidence.HIGH


# =============================================================================
# 6. DATA QUALITY INTEGRATION TESTS (Section 11, 48)
# =============================================================================

def test_data_quality_degraded_score_penalizes_confidence(isolated_service):
    """Low quality observations reduce overall fusion confidence."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_dq_low", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_POOR", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=88.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED,
                quality=0.2  # severely degraded quality
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert result.confidence == FusionConfidence.LOW
    assert result.uncertainty == FusionUncertainty.HIGH
    assert len(result.data_quality_summary["issues"]) > 0


def test_data_quality_summary_structure(isolated_service):
    """Ensures DQ summary contains completeness, validity, and evaluated count."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=20.0, unit="BAR", observed_at=now, quality=0.9
            )
        ]
    )
    result = isolated_service.analyze(req)
    dq = result.data_quality_summary
    assert dq["observations_evaluated"] == 1
    assert dq["completeness_score"] == 1.0
    assert dq["validity_score"] == 1.0


# =============================================================================
# 7. ANOMALY DETECTION INTEGRATION TESTS (Section 12, 44)
# =============================================================================

def test_anomaly_integration_preserves_score_and_provenance(isolated_service):
    """Anomaly observation is ingested without mutating anomaly records."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="anom_01", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="ANOM_DETECTOR", modality=Modality.ANOMALY, measurement_type=MeasurementType.ANOMALY_SCORE,
                value=3.85, observed_at=now, provenance=SensorValueProvenance.DERIVED, confidence=0.90
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert len(result.anomalies) == 1
    assert result.anomalies[0]["score"] == 3.85
    assert result.anomalies[0]["provenance"] == "DERIVED"


def test_cross_modal_corroboration_with_anomalies(isolated_service):
    """Elevated vibration + elevated temperature + anomaly produce corroboration agreement."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_vib", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="VIB-01", modality=Modality.VIBRATION, measurement_type=MeasurementType.VIBRATION_RMS,
                value=8.5, unit="MM/S", observed_at=now, quality=0.95
            ),
            SensorObservation(
                observation_id="o_temp", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="TEMP-01", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=85.0, unit="CELSIUS", observed_at=now, quality=0.95
            ),
            SensorObservation(
                observation_id="o_anom", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="ANOM-01", modality=Modality.ANOMALY, measurement_type=MeasurementType.ANOMALY_SCORE,
                value=0.85, observed_at=now, quality=0.95
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert len(result.agreements) >= 1
    assert result.agreements[0].status == AgreementStatus.AGREEMENT


# =============================================================================
# 8. DIGITAL TWIN INTEGRATION TESTS (Section 13, 44)
# =============================================================================

def test_digital_twin_deviation_calculation(isolated_service):
    """Digital Twin expected state generates a derived deviation signal without mutating twin."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_real_temp", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="TEMP-PHYSICAL", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=85.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.OBSERVED
            ),
            SensorObservation(
                observation_id="o_twin_temp", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="TWIN-MODEL", modality=Modality.DIGITAL_TWIN, measurement_type=MeasurementType.TEMPERATURE,
                value=65.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.SIMULATED
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert result.digital_twin_context is not None
    devs = result.digital_twin_context["deviations"]
    assert len(devs) == 1
    assert devs[0]["deviation"] == 20.0
    assert devs[0]["classification"] == "DERIVED_DEVIATION"


# =============================================================================
# 9. MULTIMODAL DOMAIN MATRIX TESTS (Section 14-18, 44)
# =============================================================================

def test_thermal_and_numeric_temperature_agreement(isolated_service):
    """When contact RTD and thermal imaging agree (<= 5°C diff), agreement is recorded."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_temp", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="RTD-01", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=82.0, unit="CELSIUS", observed_at=now
            ),
            SensorObservation(
                observation_id="o_therm", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="IR-CAM", modality=Modality.THERMAL, measurement_type=MeasurementType.TEMPERATURE,
                value=84.5, unit="CELSIUS", observed_at=now
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert any("Numeric temperature" in a.details for a in result.agreements)


def test_thermal_and_numeric_temperature_disagreement(isolated_service):
    """When contact RTD and thermal imaging differ by > 15°C, disagreement is flagged."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_temp", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="RTD-01", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=50.0, unit="CELSIUS", observed_at=now
            ),
            SensorObservation(
                observation_id="o_therm", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="IR-CAM", modality=Modality.THERMAL, measurement_type=MeasurementType.TEMPERATURE,
                value=88.0, unit="CELSIUS", observed_at=now
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert any("Discrepancy between thermography" in d.details for d in result.disagreements)


def test_electrical_signals_physical_sanity_check(isolated_service):
    """P ≈ V × I consistency check detects unrealistic power factor."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    # V=400V, I=10A -> Apparent S=4000VA. But reported P=50W (PF = 0.0125 -> abnormal)
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_volt", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="V1", modality=Modality.ELECTRICAL, measurement_type=MeasurementType.VOLTAGE,
                value=400.0, unit="VOLT", observed_at=now
            ),
            SensorObservation(
                observation_id="o_curr", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="I1", modality=Modality.ELECTRICAL, measurement_type=MeasurementType.CURRENT,
                value=10.0, unit="AMPERE", observed_at=now
            ),
            SensorObservation(
                observation_id="o_pwr", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="P1", modality=Modality.ELECTRICAL, measurement_type=MeasurementType.POWER,
                value=50.0, unit="WATT", observed_at=now  # Inconsistent
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert any("Electrical discrepancy detected" in lim for lim in result.limitations)


def test_visual_observation_integration(isolated_service):
    """Visual inspection finding is ingested with confidence and explanation."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_vis", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="VIS-CAM-01", modality=Modality.VISUAL, measurement_type=MeasurementType.VISUAL_DEFECT,
                value="Surface Corrosion Level 2", observed_at=now, confidence=0.88
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert Modality.VISUAL in result.modalities_present
    evd = next(e for e in result.evidence if e.modality == Modality.VISUAL)
    assert evd.value == "Surface Corrosion Level 2"
    assert evd.confidence == 0.88


def test_acoustic_observation_integration(isolated_service):
    """Acoustic level measurement is parsed and unit-normalized."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01",
        target_entity_id="MCH-01",
        assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_mic", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="MIC-01", modality=Modality.ACOUSTIC, measurement_type=MeasurementType.ACOUSTIC_LEVEL,
                value=85.0, unit="DB", observed_at=now
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert Modality.ACOUSTIC in result.modalities_present
    assert result.fused_observations[0].fused_value == 85.0


# =============================================================================
# 10. CROSS-MODAL CORRELATION TESTS (Section 19, 46)
# =============================================================================

def test_pearson_correlation_sufficient_samples(isolated_service):
    """Computes exact Pearson r when N >= 3 aligned samples exist."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    obs_list: List[SensorObservation] = []

    # Positively correlated series: X = [10, 20, 30, 40], Y = [100, 200, 300, 400]
    for idx, (x, y) in enumerate([(10, 100), (20, 200), (30, 300), (40, 400)]):
        ts = (t_base + timedelta(minutes=idx * 5)).isoformat().replace("+00:00", "Z")
        obs_list.append(
            SensorObservation(
                observation_id=f"ox_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_TEMP", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=float(x), unit="CELSIUS", observed_at=ts
            )
        )
        obs_list.append(
            SensorObservation(
                observation_id=f"oy_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_PRES", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=float(y), unit="BAR", observed_at=ts
            )
        )

    t_end = (t_base + timedelta(minutes=25)).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=t_end,
        evaluation_window_seconds=3600, observations=obs_list
    )

    result = isolated_service.analyze(req)
    assert len(result.correlations) == 1
    corr = result.correlations[0]
    assert corr.sample_count == 4
    assert corr.correlation_coefficient is not None
    assert abs(corr.correlation_coefficient - 1.0) < 0.001
    assert corr.is_significant is True
    assert corr.directional_agreement is True


def test_pearson_correlation_insufficient_samples_flagged(isolated_service):
    """When sample count < 3, correlation is not computed and limitation is stated."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=80.0, unit="CELSIUS", observed_at=now
            ),
            SensorObservation(
                observation_id="o2", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S2", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=40.0, unit="BAR", observed_at=now
            )
        ]
    )

    result = isolated_service.analyze(req)
    assert len(result.correlations) == 1
    corr = result.correlations[0]
    assert corr.sample_count == 1
    assert corr.correlation_coefficient is None
    assert "Insufficient aligned sample count" in corr.explanation


# =============================================================================
# 11. SENSOR HEALTH & RELIABILITY TESTS (Section 27, 47)
# =============================================================================

def test_sensor_health_constant_flatline_detected(isolated_service):
    """Zero variance across >= 3 samples flags CONSTANT_VALUE status."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    obs = [
        SensorObservation(
            observation_id=f"o_{i}", tenant_id="tenant_01", entity_id="MCH-01",
            sensor_id="S_FLATLINE", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
            value=45.0, unit="BAR", observed_at=(t_base + timedelta(minutes=i * 2)).isoformat().replace("+00:00", "Z")
        )
        for i in range(4)
    ]
    t_end = (t_base + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=t_end,
        observations=obs
    )
    result = isolated_service.analyze(req)
    sh = next(h for h in result.sensor_health if h.sensor_id == "S_FLATLINE")
    assert sh.status == SensorHealthStatus.CONSTANT_VALUE
    assert any("Constant unchanging reading" in f for f in sh.findings)


def test_sensor_health_stale_sensor_detected(isolated_service):
    """Timestamp gap > 3600s flags STALE status."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    t_assess = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)  # 2 hours later
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01",
        assessment_timestamp=t_assess.isoformat().replace("+00:00", "Z"),
        evaluation_window_seconds=10000,
        observations=[
            SensorObservation(
                observation_id="o_stale", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_STALE", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=t_base.isoformat().replace("+00:00", "Z")
            )
        ]
    )
    result = isolated_service.analyze(req)
    sh = next(h for h in result.sensor_health if h.sensor_id == "S_STALE")
    assert sh.status == SensorHealthStatus.STALE


def test_sensor_health_impossible_negative_kelvin(isolated_service):
    """Negative Kelvin flags OUT_OF_BOUNDS status."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_bad", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_IMPOSSIBLE", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=-10.0, unit="KELVIN", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    sh = next(h for h in result.sensor_health if h.sensor_id == "S_IMPOSSIBLE")
    assert sh.status == SensorHealthStatus.OUT_OF_BOUNDS


# =============================================================================
# 12. DETERMINISTIC SHA-256 FINGERPRINT TESTS (Section 34, 50)
# =============================================================================

def test_fingerprint_identical_inputs_identical_hash():
    """Same material inputs produce exact identical SHA-256 hash."""
    now = "2026-10-02T12:00:00Z"
    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=now
        )
    ]
    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs)
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs)
    assert fp1 == fp2
    assert len(fp1) == 64  # valid SHA-256 hex string


def test_fingerprint_reordered_observations_identical_hash():
    """Reordering observation array produces exact identical hash."""
    now = "2026-10-02T12:00:00Z"
    obsA = SensorObservation(
        observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s_alpha",
        modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
        value=80.0, unit="CELSIUS", observed_at=now
    )
    obsB = SensorObservation(
        observation_id="o2", tenant_id="t1", entity_id="e1", sensor_id="s_beta",
        modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
        value=40.0, unit="BAR", observed_at=now
    )

    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, [obsA, obsB])
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, [obsB, obsA])
    assert fp1 == fp2


def test_fingerprint_material_change_changes_hash():
    """Changing value, timestamp, or tenant produces a different hash."""
    now = "2026-10-02T12:00:00Z"
    obs1 = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=now
        )
    ]
    obs2 = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=81.0, unit="CELSIUS", observed_at=now  # changed value
        )
    ]
    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs1)
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs2)
    assert fp1 != fp2


# =============================================================================
# 13. PERSISTENCE REPOSITORY TESTS (Section 35, 51)
# =============================================================================

def test_repo_save_and_retrieve(isolated_repo, isolated_service):
    """Saves a FusionAssessment and retrieves it by assessment_id."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_save", target_entity_id="MCH-SAVE-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_save", entity_id="MCH-SAVE-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=75.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    saved = isolated_service.analyze(req)
    retrieved = isolated_repo.get_assessment(saved.fusion_assessment_id, tenant_id="tenant_save")
    assert retrieved is not None
    assert retrieved.fusion_assessment_id == saved.fusion_assessment_id
    assert retrieved.target_entity_id == "MCH-SAVE-01"


def test_repo_tenant_isolation(isolated_repo, isolated_service):
    """Cross-tenant retrieval returns None."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_A", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_A", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=10.0, unit="BAR", observed_at=now
            )
        ]
    )
    saved = isolated_service.analyze(req)
    # Attempting to read under tenant_B
    cross_read = isolated_repo.get_assessment(saved.fusion_assessment_id, tenant_id="tenant_B")
    assert cross_read is None


def test_repo_idempotent_deduplication(isolated_repo, isolated_service):
    """Saving assessment with duplicate fingerprint returns existing record."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_dedup", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_dedup", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=80.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    first_save = isolated_service.analyze(req)
    second_save = isolated_service.analyze(req)
    # Must return identical assessment ID
    assert first_save.fusion_assessment_id == second_save.fusion_assessment_id
    assert isolated_repo.count_assessments("tenant_dedup") == 1


def test_repo_list_assessments_bounded(isolated_repo, isolated_service):
    """Query results are bounded and respect limit parameter."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for i in range(5):
        req = SensorFusionAnalyzeRequest(
            tenant_id="tenant_list", target_entity_id=f"MCH-0{i}",
            assessment_timestamp=(datetime.now(timezone.utc) + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"),
            observations=[
                SensorObservation(
                    observation_id=f"o_{i}", tenant_id="tenant_list", entity_id=f"MCH-0{i}",
                    sensor_id=f"S_{i}", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                    value=70.0 + i, unit="CELSIUS", observed_at=now
                )
            ]
        )
        isolated_service.analyze(req)

    items = isolated_repo.list_assessments("tenant_list", limit=3)
    assert len(items) == 3


def test_repo_entity_summary_aggregation(isolated_repo, isolated_service):
    """Entity summary returns latest assessment and health indicators."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_summary", target_entity_id="MCH-TARGET", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_summary", entity_id="MCH-TARGET",
                sensor_id="TEMP-01", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=85.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    isolated_service.analyze(req)

    summary = isolated_repo.get_entity_summary("MCH-TARGET", "tenant_summary")
    assert summary.target_entity_id == "MCH-TARGET"
    assert summary.total_assessments_recorded == 1
    assert Modality.TEMPERATURE in summary.modalities_present


# =============================================================================
# 14. API ROUTE & AUTHORIZATION TESTS (Section 37, 38, 52)
# =============================================================================

def test_api_analyze_success(test_client):
    """POST /api/v3/sensor-fusion/analyze returns 200 with valid payload."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "tenant_id": "tenant_default",
        "workspace_id": "workspace_default",
        "plant_id": "PLANT-01",
        "target_entity_id": "MCH-PUMP-01",
        "assessment_timestamp": now,
        "evaluation_window_seconds": 3600,
        "observations": [
            {
                "observation_id": f"obs_{datetime.now().timestamp()}",
                "tenant_id": "tenant_default",
                "entity_id": "MCH-PUMP-01",
                "sensor_id": "TEMP-01",
                "modality": "TEMPERATURE",
                "measurement_type": "TEMPERATURE",
                "value": 78.5,
                "unit": "CELSIUS",
                "observed_at": now
            }
        ]
    }

    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.analyze")):
        resp = test_client.post(
            "/api/v3/sensor-fusion/analyze",
            json=payload,
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_entity_id"] == "MCH-PUMP-01"
    assert data["execution_boundary_verified"] is True


def test_api_analyze_tenant_boundary_violation(test_client):
    """POST /api/v3/sensor-fusion/analyze rejects cross-tenant requests with 403."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "tenant_id": "tenant_attacker",
        "target_entity_id": "MCH-01",
        "assessment_timestamp": now,
        "observations": []
    }

    # User identity is tenant_default
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.analyze")):
        resp = test_client.post(
            "/api/v3/sensor-fusion/analyze",
            json=payload,
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 403
    assert "Tenant boundary violation" in resp.json()["detail"]


def test_api_get_assessment_not_found(test_client):
    """GET /api/v3/sensor-fusion/assessment/{id} returns 404 for unknown record."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.read")):
        resp = test_client.get(
            "/api/v3/sensor-fusion/assessment/sf_unknown_12345",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 404


def test_api_list_assessments(test_client):
    """GET /api/v3/sensor-fusion/assessments returns 200 list envelope."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.read")):
        resp = test_client.get(
            "/api/v3/sensor-fusion/assessments?limit=10",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "assessments" in data
    assert "total_count" in data


def test_api_entity_summary(test_client):
    """GET /api/v3/sensor-fusion/entities/{id}/summary returns entity summary."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.read")):
        resp = test_client.get(
            "/api/v3/sensor-fusion/entities/MCH-PUMP-01/summary",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_entity_id"] == "MCH-PUMP-01"


def test_api_unauthorized_when_missing_permission(test_client):
    """Requests without required permission return 403 Forbidden."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_deny_decision("sensor_fusion.read")):
        resp = test_client.get(
            "/api/v3/sensor-fusion/assessments",
            headers={"Authorization": "Bearer dev_token", "X-Tenant-ID": "tenant_default"}
        )
    assert resp.status_code == 403


# =============================================================================
# 15. RESOURCE LIMITS & SECURITY TESTS (Section 39, 42)
# =============================================================================

def test_oversized_observations_rejected(isolated_service):
    """Requests exceeding SAGE_SENSOR_FUSION_MAX_OBSERVATIONS are rejected safely."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    excessive_obs = [
        SensorObservation(
            observation_id=f"o_{i}", tenant_id="tenant_01", entity_id="MCH-01",
            sensor_id=f"S_{i}", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=70.0, observed_at=now
        )
        for i in range(1005)  # > 1000 limit
    ]

    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=excessive_obs
    )
    with pytest.raises(ValueError) as exc:
        isolated_service.analyze(req)
    assert "exceeds maximum allowed limit" in str(exc.value)


def test_invalid_negative_window_rejected(isolated_service):
    """Negative evaluation window is rejected with ValueError."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        evaluation_window_seconds=-3600, observations=[]
    )
    with pytest.raises(ValueError) as exc:
        isolated_service.analyze(req)
    assert "Evaluation window" in str(exc.value)


# =============================================================================
# 16. STATIC AST & EXECUTION BOUNDARY TESTS (Section 2, 53)
# =============================================================================

def test_ast_no_execution_gateway_in_sensor_fusion_service():
    """Verifies that sensor_fusion_service.py has ZERO imports of ExecutionGateway."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "sensor_fusion_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "execution_gateway" not in alias.name.lower(), f"Forbidden import: {alias.name}"
                assert "ExecutionGateway" not in alias.name, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "execution_gateway" not in node.module.lower(), f"Forbidden from-import module: {node.module}"
            for alias in node.names:
                assert "ExecutionGateway" not in alias.name, f"Forbidden from-import: {alias.name}"


def test_ast_no_execution_gateway_in_sensor_fusion_routes():
    """Verifies that sensor_fusion_routes.py has ZERO imports of ExecutionGateway."""
    file_path = os.path.join(os.path.dirname(__file__), "api", "sensor_fusion_routes.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "execution_gateway" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "execution_gateway" not in node.module.lower()


def test_ast_no_execution_gateway_in_sensor_fusion_repository():
    """Verifies that sensor_fusion_repository.py has ZERO imports of ExecutionGateway."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "sensor_fusion_repository.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "execution_gateway" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "execution_gateway" not in node.module.lower()


def test_no_action_api_invocations(isolated_service):
    """Verifies that SensorFusionService does not invoke Action API or create work orders."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=99.0, unit="CELSIUS", observed_at=now  # Critical temperature
            )
        ]
    )

    assessment = isolated_service.analyze(req)
    assert assessment.execution_boundary_verified is True
    # Asserts output is strictly analytical
    assert hasattr(assessment, "fused_observations")
    assert not hasattr(assessment, "action_id")
    assert not hasattr(assessment, "work_order_id")


def test_no_mutation_to_upstream_data(isolated_service):
    """Verifies that analyzing sensor fusion does not modify input observation arrays."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    original_val = 75.5
    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
            sensor_id="S1", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
            value=original_val, unit="BAR", observed_at=now
        )
    ]
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=obs
    )
    isolated_service.analyze(req)
    # The original observation must remain untouched
    assert obs[0].value == original_val


# =============================================================================
# 17. ADDITIONAL UNIT CONVERSION & SAFETY TESTS
# =============================================================================

def test_convert_kelvin_to_fahrenheit():
    """373.15 K -> 212.0°F."""
    val, success, _ = convert_unit(373.15, "KELVIN", "FAHRENHEIT")
    assert success is True
    assert abs(val - 212.0) < 0.01


def test_convert_fahrenheit_to_kelvin():
    """212.0°F -> 373.15 K."""
    val, success, _ = convert_unit(212.0, "FAHRENHEIT", "KELVIN")
    assert success is True
    assert abs(val - 373.15) < 0.01


def test_convert_mpa_to_bar():
    """2.5 MPa -> 25.0 bar."""
    val, success, _ = convert_unit(2.5, "MPA", "BAR")
    assert success is True
    assert val == 25.0


def test_convert_bar_to_mpa():
    """50.0 bar -> 5.0 MPa."""
    val, success, _ = convert_unit(50.0, "BAR", "MPA")
    assert success is True
    assert val == 5.0


def test_convert_millivolt_to_volt():
    """500.0 mV -> 0.5 V."""
    val, success, _ = convert_unit(500.0, "MILLIVOLT", "VOLT")
    assert success is True
    assert val == 0.5


def test_convert_megawatt_to_kilowatt():
    """1.2 MW -> 1200.0 kW."""
    val, success, _ = convert_unit(1.2, "MEGAWATT", "KILOWATT")
    assert success is True
    assert val == 1200.0


def test_convert_acceleration_g_to_ms2():
    """1.0 g -> ~9.80665 m/s^2."""
    val, success, _ = convert_unit(1.0, "G_ACCEL", "M/S^2")
    assert success is True
    assert abs(val - 9.80665) < 0.001


def test_convert_frequency_khz_to_hz():
    """2.5 kHz -> 2500.0 Hz."""
    val, success, _ = convert_unit(2.5, "KHZ", "HZ")
    assert success is True
    assert val == 2500.0


def test_convert_incompatible_torque_and_voltage():
    """Torque (Nm) cannot be converted to Voltage (V)."""
    val, success, msg = convert_unit(50.0, "NM", "VOLT")
    assert success is False
    assert val is None
    assert "Incompatible units" in msg


def test_convert_incompatible_flow_and_pressure():
    """Flow (L/min) cannot be converted to Pressure (bar)."""
    val, success, msg = convert_unit(10.0, "L/MIN", "BAR")
    assert success is False
    assert val is None


def test_convert_incompatible_acoustic_and_temperature():
    """Acoustic (dB) cannot be converted to Temperature (C)."""
    val, success, msg = convert_unit(85.0, "DB", "CELSIUS")
    assert success is False
    assert val is None


# =============================================================================
# 18. FUSION STRATEGIES & WEIGHTING TESTS
# =============================================================================

def test_consensus_fusion_strategy_execution(isolated_service):
    """Consensus fusion strategy executes deterministically."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_strat", target_entity_id="MCH-01", assessment_timestamp=now,
        fusion_strategy=FusionStrategy.CONSENSUS_FUSION,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_strat", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=75.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert result.fused_observations[0].fusion_method == FusionStrategy.CONSENSUS_FUSION


def test_normalized_score_fusion_strategy_execution(isolated_service):
    """Normalized score fusion strategy executes deterministically."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_strat", target_entity_id="MCH-01", assessment_timestamp=now,
        fusion_strategy=FusionStrategy.NORMALIZED_SCORE_FUSION,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_strat", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=25.0, unit="BAR", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert result.fused_observations[0].fusion_method == FusionStrategy.NORMALIZED_SCORE_FUSION


def test_contextual_fusion_strategy_with_ontology_and_twin(isolated_service):
    """Contextual fusion combines physical readings with Digital Twin and Ontology."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_strat", target_entity_id="MCH-01", assessment_timestamp=now,
        fusion_strategy=FusionStrategy.CONTEXTUAL_FUSION,
        include_ontology=True, include_digital_twin=True,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_strat", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=80.0, unit="CELSIUS", observed_at=now
            ),
            SensorObservation(
                observation_id="o_dt", tenant_id="tenant_strat", entity_id="MCH-01",
                sensor_id="TWIN-01", modality=Modality.DIGITAL_TWIN, measurement_type=MeasurementType.TEMPERATURE,
                value=60.0, unit="CELSIUS", observed_at=now, provenance=SensorValueProvenance.SIMULATED
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert result.ontology_context is not None
    assert result.digital_twin_context is not None


def test_canonical_weights_defined_for_all_modalities():
    """All 12 modalities have defined canonical weights between 0.0 and 1.0."""
    weight_modalities = {w.modality for w in CANONICAL_WEIGHTING_RULES}
    assert weight_modalities == set(Modality)
    for w in CANONICAL_WEIGHTING_RULES:
        assert 0.0 < w.weight <= 1.0
        assert len(w.rationale) > 5


# =============================================================================
# 19. ADVANCED CORRELATION & AGREEMENT TESTS
# =============================================================================

def test_negative_cross_modal_correlation(isolated_service):
    """Inverse signals compute a negative Pearson r (-1.0)."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    obs_list: List[SensorObservation] = []

    # Inverse series: X = [10, 20, 30, 40], Y = [400, 300, 200, 100]
    for idx, (x, y) in enumerate([(10, 400), (20, 300), (30, 200), (40, 100)]):
        ts = (t_base + timedelta(minutes=idx * 5)).isoformat().replace("+00:00", "Z")
        obs_list.append(
            SensorObservation(
                observation_id=f"ox_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_TEMP", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=float(x), unit="CELSIUS", observed_at=ts
            )
        )
        obs_list.append(
            SensorObservation(
                observation_id=f"oy_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_PRES", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=float(y), unit="BAR", observed_at=ts
            )
        )

    t_end = (t_base + timedelta(minutes=25)).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=t_end,
        evaluation_window_seconds=3600, observations=obs_list
    )

    result = isolated_service.analyze(req)
    corr = result.correlations[0]
    assert corr.correlation_coefficient is not None
    assert corr.correlation_coefficient < -0.9
    assert corr.directional_agreement is False


def test_zero_variance_correlation_handled_gracefully(isolated_service):
    """When one series is flat, Pearson r does not divide by zero."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    obs_list: List[SensorObservation] = []

    for idx, x in enumerate([10, 20, 30, 40]):
        ts = (t_base + timedelta(minutes=idx * 5)).isoformat().replace("+00:00", "Z")
        obs_list.append(
            SensorObservation(
                observation_id=f"ox_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_VAR", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=float(x), unit="CELSIUS", observed_at=ts
            )
        )
        obs_list.append(
            SensorObservation(
                observation_id=f"oy_{idx}", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_FLAT", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=50.0, unit="BAR", observed_at=ts  # Zero variance
            )
        )

    t_end = (t_base + timedelta(minutes=25)).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=t_end,
        evaluation_window_seconds=3600, observations=obs_list
    )

    result = isolated_service.analyze(req)
    # Correlation calculation should complete without throwing ZeroDivisionError
    assert len(result.correlations) == 1


def test_insufficient_evidence_when_single_modality(isolated_service):
    """Only 1 modality present adds single-modality limitation note."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert any("Only single modality present" in lim for lim in result.limitations)
    assert result.confidence == FusionConfidence.LOW


def test_unknown_confidence_when_no_observations(isolated_service):
    """Empty eligible observations list returns UNKNOWN confidence and HIGH uncertainty."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[]
    )
    result = isolated_service.analyze(req)
    assert result.confidence == FusionConfidence.UNKNOWN
    assert result.uncertainty == FusionUncertainty.HIGH
    assert len(result.fused_observations) == 0


def test_missing_modalities_list_accuracy(isolated_service):
    """When 2 modalities are present, exactly 10 are reported in modalities_missing."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=now
            ),
            SensorObservation(
                observation_id="o2", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S2", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=40.0, unit="BAR", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    assert len(result.modalities_present) == 2
    assert len(result.modalities_missing) == 10
    assert Modality.TEMPERATURE not in result.modalities_missing
    assert Modality.VIBRATION in result.modalities_missing


# =============================================================================
# 20. ADVANCED SENSOR HEALTH TESTS
# =============================================================================

def test_sensor_health_negative_pressure_out_of_bounds(isolated_service):
    """Negative gauge pressure < -1.0 bar flags OUT_OF_BOUNDS."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o_neg_p", tenant_id="tenant_01", entity_id="MCH-01",
                sensor_id="S_VACUUM_ERR", modality=Modality.PRESSURE, measurement_type=MeasurementType.PRESSURE,
                value=-5.0, unit="BAR", observed_at=now
            )
        ]
    )
    result = isolated_service.analyze(req)
    sh = next(h for h in result.sensor_health if h.sensor_id == "S_VACUUM_ERR")
    assert sh.status == SensorHealthStatus.OUT_OF_BOUNDS
    assert any("negative pressure" in f for f in sh.findings)


def test_sensor_health_healthy_sensor_properties(isolated_service):
    """Normal fresh sensor has status HEALTHY and high reliability score."""
    t_base = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    t_assess = datetime(2026, 10, 2, 10, 5, 0, tzinfo=timezone.utc)
    obs = [
        SensorObservation(
            observation_id=f"o_{i}", tenant_id="tenant_01", entity_id="MCH-01",
            sensor_id="S_HEALTHY", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=70.0 + i, unit="CELSIUS", observed_at=(t_base + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        )
        for i in range(3)
    ]
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_01", target_entity_id="MCH-01",
        assessment_timestamp=t_assess.isoformat().replace("+00:00", "Z"),
        observations=obs
    )
    result = isolated_service.analyze(req)
    sh = next(h for h in result.sensor_health if h.sensor_id == "S_HEALTHY")
    assert sh.status == SensorHealthStatus.HEALTHY
    assert sh.reliability_score == 1.0


# =============================================================================
# 21. ADVANCED FINGERPRINT & REPOSITORY ISOLATION TESTS
# =============================================================================

def test_fingerprint_changes_on_window_duration_change():
    """Changing window duration modifies the input fingerprint."""
    now = "2026-10-02T12:00:00Z"
    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=now
        )
    ]
    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs)
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 7200, obs)
    assert fp1 != fp2


def test_fingerprint_changes_on_fusion_strategy_change():
    """Changing fusion strategy modifies the input fingerprint."""
    now = "2026-10-02T12:00:00Z"
    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=now
        )
    ]
    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs, fusion_strategy="WEIGHTED_EVIDENCE_FUSION")
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "e1", now, 3600, obs, fusion_strategy="CONSENSUS_FUSION")
    assert fp1 != fp2


def test_fingerprint_changes_on_target_entity_change():
    """Changing target entity modifies the input fingerprint."""
    now = "2026-10-02T12:00:00Z"
    obs = [
        SensorObservation(
            observation_id="o1", tenant_id="t1", entity_id="e1", sensor_id="s1",
            modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
            value=80.0, unit="CELSIUS", observed_at=now
        )
    ]
    fp1 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "ENTITY_A", now, 3600, obs)
    fp2 = compute_sensor_fusion_fingerprint("t1", "w1", "p1", "ENTITY_B", now, 3600, obs)
    assert fp1 != fp2


def test_repo_wal_mode_enabled(isolated_repo):
    """Verifies that SQLite repository is operating under WAL journal mode."""
    with isolated_repo._get_connection() as conn:
        cursor = conn.execute("PRAGMA journal_mode")
        row = cursor.fetchone()
        assert row[0].upper() == "WAL"


def test_repo_sql_injection_resistant(isolated_repo, isolated_service):
    """Malicious SQL injection payload in entity_id is safely parameterized."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    malicious_entity_id = "MCH-01' OR '1'='1"
    req = SensorFusionAnalyzeRequest(
        tenant_id="tenant_sec", target_entity_id=malicious_entity_id, assessment_timestamp=now,
        observations=[
            SensorObservation(
                observation_id="o1", tenant_id="tenant_sec", entity_id=malicious_entity_id,
                sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE,
                value=70.0, unit="CELSIUS", observed_at=now
            )
        ]
    )
    saved = isolated_service.analyze(req)
    assert saved.target_entity_id == malicious_entity_id

    # Query with exact entity_id
    summary = isolated_repo.get_entity_summary(malicious_entity_id, "tenant_sec")
    assert summary.total_assessments_recorded == 1

    # Query with non-existent entity should return 0, not leak rows
    other_summary = isolated_repo.get_entity_summary("MCH-BENIGN", "tenant_sec")
    assert other_summary.total_assessments_recorded == 0


def test_repo_delete_all_tenant_scoped(isolated_repo, isolated_service):
    """delete_all removes only target tenant's records."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    req1 = SensorFusionAnalyzeRequest(
        tenant_id="tenant_X", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[SensorObservation(observation_id="o1", tenant_id="tenant_X", entity_id="MCH-01", sensor_id="S1", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE, value=70.0, observed_at=now)]
    )
    req2 = SensorFusionAnalyzeRequest(
        tenant_id="tenant_Y", target_entity_id="MCH-01", assessment_timestamp=now,
        observations=[SensorObservation(observation_id="o2", tenant_id="tenant_Y", entity_id="MCH-01", sensor_id="S2", modality=Modality.TEMPERATURE, measurement_type=MeasurementType.TEMPERATURE, value=70.0, observed_at=now)]
    )
    isolated_service.analyze(req1)
    isolated_service.analyze(req2)

    isolated_repo.delete_all("tenant_X")
    assert isolated_repo.count_assessments("tenant_X") == 0
    assert isolated_repo.count_assessments("tenant_Y") == 1


# =============================================================================
# 22. ADVANCED API & AST SECURITY TESTS
# =============================================================================

def test_api_plant_boundary_forbidden_for_restricted_user(test_client):
    """User restricted to PLANT-A is forbidden from accessing PLANT-B assessment (403)."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.read")):
        from core.auth import get_current_identity
        server.app.dependency_overrides[get_current_identity] = lambda: _make_identity(assigned_plants=["PLANT-A"])
        try:
            resp = test_client.get(
                "/api/v3/sensor-fusion/assessments?plant_id=PLANT-B",
                headers={"Authorization": "Bearer token", "X-Tenant-ID": "tenant_test"}
            )
            assert resp.status_code == 403
            assert "Plant boundary violation" in resp.json()["detail"]
        finally:
            server.app.dependency_overrides.pop(get_current_identity, None)


def test_api_analyze_missing_entity_id_422(test_client):
    """Missing target_entity_id fails schema validation with 422."""
    with patch("services.authorization_service.authorization_service.evaluate", return_value=_allow_decision("sensor_fusion.analyze")):
        resp = test_client.post(
            "/api/v3/sensor-fusion/analyze",
            json={"tenant_id": "tenant_default"},
            headers={"Authorization": "Bearer dev_token"}
        )
        assert resp.status_code == 422


def test_ast_no_action_api_routes_in_sensor_fusion():
    """sensor_fusion_routes.py has zero imports of action_routes."""
    file_path = os.path.join(os.path.dirname(__file__), "api", "sensor_fusion_routes.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "action_routes" not in alias.name.lower()
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert "action_routes" not in node.module.lower()


def test_ast_no_controller_or_plc_imports():
    """sensor_fusion_service.py has zero imports of PLC or physical controller libraries."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "sensor_fusion_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=file_path)

    forbidden = {"pymodbus", "snap7", "opcua", "pycomm3", "can", "serial", "controller"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.lower() not in forbidden
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.lower() not in forbidden


def test_ast_no_prompt_28_what_if_simulation():
    """sensor_fusion_service.py contains no Prompt 28 What-If simulation engine."""
    file_path = os.path.join(os.path.dirname(__file__), "services", "sensor_fusion_service.py")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "what_if" not in content.lower()
    assert "whatif" not in content.lower()

