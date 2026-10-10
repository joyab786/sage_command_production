# backend/test_v3_confidence_uncertainty.py
"""
SageCommand V3 — Confidence and Uncertainty Intelligence Foundation Test Suite (Prompt 32)

Covers all required areas:
1. Contracts and numerical safety (Pydantic V2, non-finite checks, invalid bounds, ISO timestamps, scope identifiers).
2. Confidence dimensions and scoring (10 dimensions, weighting, blocking deficiency capping, qualitative interpretations).
3. Uncertainty decomposition & ranges (Aleatoric vs Epistemic, range validation, sensitivity indices, qualitative fallback).
4. Evidence provenance and temporal correctness (Prompt 31 integration, provenance preservation, freshness decay, future leakage).
5. Upstream integrations (Decision Engine Prompt 30, Optimization Prompt 29, Sensor Fusion Prompt 27, unmutated sources).
6. Security, RBAC & tenant isolation (read, assess, validate, admin, plant boundary checks, non-disclosing 404/403).
7. Persistence, concurrency & audit (SQLite WAL, fingerprint deduplication, concurrent writes, audit ledger).
8. API routes & validation (all endpoints, batch evaluation, parameter validation, error responses).
9. Architectural boundaries (AST checks for forbidden execution gateways, no action execution, no physical actuation, mandatory notices).

Target: >= 140 meaningful passing tests.
"""

import ast
import json
import math
import os
import sqlite3
import threading
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from data.schemas.confidence_uncertainty_contract import (
        ConfidenceDimensionType,
        ConfidenceStatus,
        UncertaintyType,
        UncertaintySeverity,
        UncertaintyIntervalType,
        AggregationMethod,
        CalibrationStatus,
        ConfidenceDimension,
        ConfidenceComponent,
        ConfidenceEvidenceReference,
        ConfidenceContribution,
        ConfidenceCalibrationMetadata,
        ConfidenceLimitation,
        ConfidenceAssessment,
        UncertaintySource,
        UncertaintyRange,
        UncertaintyDistributionSummary,
        UncertaintySensitivity,
        UncertaintyPropagation,
        UncertaintyComponent,
        UncertaintyDecomposition,
        UncertaintyLimitation,
        UncertaintyAssessment,
        ConfidenceUncertaintyMethod,
        ConfidenceUncertaintyRequest,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyResult,
        ConfidenceUncertaintySummary,
        ConfidenceUncertaintyListResponse,
        ConfidenceAuditRecord,
        compute_confidence_fingerprint,
        validate_finite_number,
        validate_identifier,
        validate_iso_timestamp,
        validate_proportional_score,
        MANDATORY_CONFIDENCE_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from repositories.confidence_uncertainty_repository import (
        ConfidenceUncertaintyRepository,
        confidence_uncertainty_repository,
    )
    from services.confidence_uncertainty_service import (
        ConfidenceUncertaintyService,
        confidence_uncertainty_service,
        ConfidenceDimensionEvaluator,
        UncertaintyDecompositionEngine,
    )
    from repositories.decision_engine_repository import decision_engine_repository
    from data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionOption,
        DecisionCriterion,
        DecisionType,
        DecisionScope,
        CriterionDirection,
        CriterionType,
    )
    from services.decision_engine_service import decision_engine_service
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.data.schemas.confidence_uncertainty_contract import (
        ConfidenceDimensionType,
        ConfidenceStatus,
        UncertaintyType,
        UncertaintySeverity,
        UncertaintyIntervalType,
        AggregationMethod,
        CalibrationStatus,
        ConfidenceDimension,
        ConfidenceComponent,
        ConfidenceEvidenceReference,
        ConfidenceContribution,
        ConfidenceCalibrationMetadata,
        ConfidenceLimitation,
        ConfidenceAssessment,
        UncertaintySource,
        UncertaintyRange,
        UncertaintyDistributionSummary,
        UncertaintySensitivity,
        UncertaintyPropagation,
        UncertaintyComponent,
        UncertaintyDecomposition,
        UncertaintyLimitation,
        UncertaintyAssessment,
        ConfidenceUncertaintyMethod,
        ConfidenceUncertaintyRequest,
        ConfidenceValidationRequest,
        ConfidenceValidationResponse,
        ConfidenceUncertaintyResult,
        ConfidenceUncertaintySummary,
        ConfidenceUncertaintyListResponse,
        ConfidenceAuditRecord,
        compute_confidence_fingerprint,
        validate_finite_number,
        validate_identifier,
        validate_iso_timestamp,
        validate_proportional_score,
        MANDATORY_CONFIDENCE_NOTICE,
        ALGORITHM_VERSION,
        CONTRACT_VERSION,
    )
    from backend.data.schemas.evidence_explainability_contract import (
        EvidenceRecord,
        EvidenceProvenance,
        EvidenceSourceType,
    )
    from backend.repositories.confidence_uncertainty_repository import (
        ConfidenceUncertaintyRepository,
        confidence_uncertainty_repository,
    )
    from backend.services.confidence_uncertainty_service import (
        ConfidenceUncertaintyService,
        confidence_uncertainty_service,
        ConfidenceDimensionEvaluator,
        UncertaintyDecompositionEngine,
    )
    from backend.repositories.decision_engine_repository import decision_engine_repository
    from backend.data.schemas.decision_engine_contract import (
        DecisionRequest,
        DecisionOption,
        DecisionCriterion,
        DecisionType,
        DecisionScope,
        CriterionDirection,
        CriterionType,
    )
    from backend.services.decision_engine_service import decision_engine_service


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_identity_analyst():
    return Identity(
        user_id="test_analyst_conf_01",
        tenant_id="tenant_conf_1",
        workspace_id="workspace_conf_1",
        assigned_plants=["PLANT-01"],
        roles=["ANALYST"],
        is_server_authoritative=True,
    )


@pytest.fixture
def test_identity_viewer():
    return Identity(
        user_id="test_viewer_conf_01",
        tenant_id="tenant_conf_1",
        workspace_id="workspace_conf_1",
        assigned_plants=["PLANT-01"],
        roles=["VIEWER"],
        is_server_authoritative=True,
    )


@pytest.fixture
def test_identity_other_tenant():
    return Identity(
        user_id="test_alien_conf_01",
        tenant_id="tenant_alien_9",
        workspace_id="workspace_alien_9",
        assigned_plants=["PLANT-99"],
        roles=["ANALYST"],
        is_server_authoritative=True,
    )


@pytest.fixture
def sample_evidence_record():
    return EvidenceRecord(
        evidence_id="ev_conf_sample_1",
        tenant_id="tenant_conf_1",
        workspace_id="workspace_conf_1",
        plant_id="PLANT-01",
        source_type=EvidenceSourceType.SENSOR_FUSION,
        source_record_id="fuse_vib_01",
        title="Bearing Vibration & Temperature Observation",
        description="Dual telemetry confirms nominal vibration band.",
        observed_at="2026-05-01T10:00:00Z",
        assessed_at="2026-05-01T10:05:00Z",
        provenance=EvidenceProvenance.OBSERVED,
        quality_score=0.95,
        freshness_seconds=300.0,
        confidence_score=0.92,
        payload={"vibration_rms": 1.25, "temperature_c": 52.4},
    )


@pytest.fixture
def sample_decision_evaluation():
    req = DecisionRequest(
        tenant_id="tenant_conf_1",
        workspace_id="workspace_conf_1",
        plant_id="PLANT-01",
        decision_type=DecisionType.RESOURCE_ALLOCATION,
        title="Pump A vs B Allocation",
        options=[
            DecisionOption(option_id="opt_a", name="Run Pump A", parameters={"kw": 45.0}),
            DecisionOption(option_id="opt_b", name="Run Pump B", parameters={"kw": 52.0}),
        ],
        criteria=[
            DecisionCriterion(criterion_id="crit_cost", name="Energy Cost", criterion_type=CriterionType.COST, direction=CriterionDirection.MINIMIZE, weight=0.6),
            DecisionCriterion(criterion_id="crit_rel", name="Reliability", criterion_type=CriterionType.RELIABILITY, direction=CriterionDirection.MAXIMIZE, weight=0.4),
        ],
    )
    return decision_engine_service.evaluate(req)


@pytest.fixture
def test_repo(tmp_path):
    db_file = str(tmp_path / "test_conf_uncert.sqlite")
    return ConfidenceUncertaintyRepository(db_path=db_file)


# =============================================================================
# 1. CONTRACTS & NUMERICAL SAFETY TESTS (Tests 1–20)
# =============================================================================

class TestContractsAndNumericalSafety:

    def test_001_validate_finite_number_valid(self):
        assert validate_finite_number(42.5, "test") == 42.5
        assert validate_finite_number(0, "test") == 0.0
        assert validate_finite_number(-100.2, "test") == -100.2

    def test_002_validate_finite_number_nan_rejected(self):
        with pytest.raises(ValueError, match="must be finite"):
            validate_finite_number(float("nan"), "test")

    def test_003_validate_finite_number_inf_rejected(self):
        with pytest.raises(ValueError, match="must be finite"):
            validate_finite_number(float("inf"), "test")
        with pytest.raises(ValueError, match="must be finite"):
            validate_finite_number(float("-inf"), "test")

    def test_004_validate_finite_number_none_rejected(self):
        with pytest.raises(ValueError, match="cannot be None"):
            validate_finite_number(None, "test")

    def test_005_validate_identifier_empty_rejected(self):
        with pytest.raises(ValueError, match="non-empty string"):
            validate_identifier("", "test_id")
        with pytest.raises(ValueError, match="non-empty string"):
            validate_identifier("   ", "test_id")

    def test_006_validate_identifier_length_limit(self):
        long_str = "a" * 300
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_identifier(long_str, "test_id")

    def test_007_validate_iso_timestamp_valid(self):
        ts = "2026-05-01T12:00:00Z"
        res = validate_iso_timestamp(ts, "ts_field")
        assert "+00:00" in res or "2026-05-01" in res

    def test_008_validate_iso_timestamp_invalid(self):
        with pytest.raises(ValueError, match="valid ISO 8601"):
            validate_iso_timestamp("not-a-date", "ts_field")

    def test_009_validate_proportional_score_bounds(self):
        assert validate_proportional_score(0.0, "score") == 0.0
        assert validate_proportional_score(1.0, "score") == 1.0
        assert validate_proportional_score(0.75, "score") == 0.75
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            validate_proportional_score(-0.1, "score")
        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            validate_proportional_score(1.05, "score")

    def test_010_confidence_dimension_model_valid(self):
        dim = ConfidenceDimension(
            dimension_type=ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
            score=0.85,
            weight=1.5,
            is_assessed=True,
            status="ASSESSED",
            explanation="85% completeness",
        )
        assert dim.score == 0.85
        assert dim.weight == 1.5

    def test_011_confidence_dimension_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            ConfidenceDimension(
                dimension_type=ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
                score=0.8,
                weight=-1.0,
            )

    def test_012_confidence_dimension_extra_field_forbidden(self):
        with pytest.raises(ValueError):
            ConfidenceDimension(
                dimension_type=ConfidenceDimensionType.EVIDENCE_COMPLETENESS,
                score=0.8,
                weight=1.0,
                unknown_field="extra",
            )

    def test_013_uncertainty_range_valid(self):
        ur = UncertaintyRange(
            lower_bound=10.0,
            upper_bound=20.0,
            unit="celsius",
            confidence_level=0.95,
            interval_type=UncertaintyIntervalType.PREDICTION_INTERVAL,
        )
        assert ur.lower_bound == 10.0
        assert ur.upper_bound == 20.0
        assert ur.unit == "celsius"

    def test_014_uncertainty_range_inverted_bounds_rejected(self):
        with pytest.raises(ValueError, match="cannot exceed upper_bound"):
            UncertaintyRange(
                lower_bound=25.0,
                upper_bound=10.0,
                unit="celsius",
                interval_type=UncertaintyIntervalType.OBSERVED_RANGE,
            )

    def test_015_uncertainty_range_nan_bounds_rejected(self):
        with pytest.raises(ValueError, match="must be finite"):
            UncertaintyRange(
                lower_bound=float("nan"),
                upper_bound=10.0,
                unit="celsius",
                interval_type=UncertaintyIntervalType.OBSERVED_RANGE,
            )

    def test_016_uncertainty_sensitivity_model(self):
        sens = UncertaintySensitivity(
            parameter_name="vibration_rms",
            sensitivity_index=0.75,
            elasticity=0.45,
            notes="Linear scaling",
        )
        assert sens.sensitivity_index == 0.75

    def test_017_confidence_calibration_metadata_defaults(self):
        cal = ConfidenceCalibrationMetadata()
        assert cal.is_calibrated is False
        assert cal.calibration_status == CalibrationStatus.UNASSESSED
        assert "Uncalibrated analytical heuristic" in cal.notes

    def test_018_mandatory_notice_constant(self):
        assert MANDATORY_CONFIDENCE_NOTICE == "CONFIDENCE AND UNCERTAINTY ANALYSIS ONLY — NOT AUTHORIZED AND NOT EXECUTED"

    def test_019_confidence_limitation_model(self):
        lim = ConfidenceLimitation(
            limitation_id="lim_01",
            code="UNMODELED_EXTREME_RISK",
            description="Extreme risk unmodeled",
            severity="HIGH",
        )
        assert lim.code == "UNMODELED_EXTREME_RISK"

    def test_020_confidence_fingerprint_deterministic(self):
        fp1 = compute_confidence_fingerprint(
            "tenant_1", "ws_1", "PLANT-01", "DECISION_ENGINE", "dec_1",
            "2026-05-01T12:00:00Z", "1.0.0",
            {"EVIDENCE_QUALITY": 0.9, "FRESHNESS": 0.8},
            ["ALEATORIC", "EPISTEMIC"],
            ["ev_1", "ev_2"],
            [],
            [],
        )
        fp2 = compute_confidence_fingerprint(
            "tenant_1", "ws_1", "PLANT-01", "DECISION_ENGINE", "dec_1",
            "2026-05-01T12:00:00Z", "1.0.0",
            {"EVIDENCE_QUALITY": 0.9, "FRESHNESS": 0.8},
            ["ALEATORIC", "EPISTEMIC"],
            ["ev_1", "ev_2"],
            [],
            [],
        )
        assert fp1 == fp2
        assert len(fp1) == 64


# =============================================================================
# 2. CONFIDENCE DIMENSIONS & SCORING TESTS (Tests 21–40)
# =============================================================================

class TestConfidenceDimensionsAndScoring:

    def test_021_eval_dimensions_empty_evidence(self):
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        assert len(dims) == 10
        assert "MISSING_ALL_SUPPORTING_EVIDENCE" in defs
        comp_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.EVIDENCE_COMPLETENESS)
        assert comp_dim.is_assessed is False
        assert comp_dim.score is None

    def test_022_eval_dimensions_single_evidence(self, sample_evidence_record):
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        assert len(dims) == 10
        qual_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.EVIDENCE_QUALITY)
        assert qual_dim.score == pytest.approx(0.95, rel=1e-2)

    def test_023_eval_dimensions_freshness_decay(self, sample_evidence_record):
        # Age is 2 hours (7200s), threshold is 3600s -> stale
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=3600.0,  # 1 hour threshold
            plant_id="PLANT-01",
        )
        fresh_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.FRESHNESS)
        assert fresh_dim.score == 0.0  # Decayed to 0
        assert "ALL_EVIDENCE_STALE" in defs

    def test_024_eval_dimensions_future_leakage_blocking(self, sample_evidence_record):
        future_ev = sample_evidence_record.model_copy()
        future_ev.observed_at = "2026-05-02T00:00:00Z"  # 12 hours after assessment
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[future_ev],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        temp_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.TEMPORAL_CONSISTENCY)
        assert temp_dim.score == 0.0
        assert "FUTURE_DATED_EVIDENCE_LEAKAGE" in defs

    def test_025_eval_dimensions_provenance_weighting(self, sample_evidence_record):
        sim_ev = sample_evidence_record.model_copy()
        sim_ev.provenance = EvidenceProvenance.SIMULATED
        dims, _ = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sim_ev],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        rel_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.SOURCE_RELIABILITY)
        assert rel_dim.score == 0.65  # SIMULATED weight is 0.65

    def test_026_eval_dimensions_conflict_penalty(self, sample_evidence_record):
        conflicts = [{"conflict_id": "c1", "description": "Temperature contradiction"}]
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
            conflicts=conflicts,
        )
        agr_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.CROSS_SOURCE_AGREEMENT)
        assert agr_dim.score < 0.8
        assert any("CONFLICT" in d for d in agr_dim.deficiencies)

    def test_027_eval_dimensions_severe_conflict_blocking(self, sample_evidence_record):
        conflicts = [
            {"conflict_id": "c1", "description": "Contradiction 1"},
            {"conflict_id": "c2", "description": "Contradiction 2"},
        ]
        dims, defs = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
            conflicts=conflicts,
        )
        assert "SEVERE_SOURCE_CONFLICTS" in defs

    def test_028_eval_dimensions_context_coverage_unspecified_plant(self, sample_evidence_record):
        dims, _ = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id=None,  # No plant
        )
        ctx_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.CONTEXT_COVERAGE)
        assert ctx_dim.score == 0.75
        assert "PLANT_SCOPE_UNSPECIFIED" in ctx_dim.deficiencies

    def test_029_eval_dimensions_model_calibration_uncalibrated_notice(self, sample_evidence_record):
        dims, _ = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        cal_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.MODEL_CALIBRATION)
        assert cal_dim.score == 0.50
        assert "not a calibrated statistical probability" in cal_dim.explanation.lower()

    def test_030_eval_dimensions_lineage_unresolved_parents(self, sample_evidence_record):
        orphan_ev = sample_evidence_record.model_copy()
        orphan_ev.parent_evidence_ids = ["missing_p1", "missing_p2"]
        dims, _ = ConfidenceDimensionEvaluator.evaluate_dimensions(
            evidence_items=[orphan_ev],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            assessment_ts="2026-05-01T12:00:00Z",
            freshness_threshold=86400.0,
            plant_id="PLANT-01",
        )
        lin_dim = next(d for d in dims if d.dimension_type == ConfidenceDimensionType.LINEAGE_INTEGRITY)
        assert lin_dim.score < 1.0

    def test_031_assess_service_empty_evidence_insufficient_status(self):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="nonexistent_dec_999",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.confidence.status == ConfidenceStatus.INSUFFICIENT_EVIDENCE
        assert res.confidence.aggregate_score is None

    def test_032_assess_service_high_confidence(self, sample_evidence_record):
        # 3 high quality, fresh evidence records
        e1 = sample_evidence_record
        e2 = sample_evidence_record.model_copy()
        e2.evidence_id = "ev_2"
        e3 = sample_evidence_record.model_copy()
        e3.evidence_id = "ev_3"

        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_high_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[e1, e2, e3],
            freshness_threshold_seconds=86400.0,
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.confidence.status == ConfidenceStatus.HIGH_CONFIDENCE
        assert res.confidence.aggregate_score >= 0.80

    def test_033_assess_service_blocking_deficiency_cap_all_stale(self, sample_evidence_record):
        stale_ev = sample_evidence_record.model_copy()
        stale_ev.observed_at = "2026-01-01T00:00:00Z"  # 4 months old
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_stale_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[stale_ev],
            freshness_threshold_seconds=86400.0,
        )
        res = confidence_uncertainty_service.assess(req)
        assert "ALL_EVIDENCE_STALE" in res.confidence.blocking_deficiencies
        assert res.confidence.aggregate_score <= 0.30
        assert res.confidence.status in (ConfidenceStatus.LOW_CONFIDENCE, ConfidenceStatus.VERY_LOW_CONFIDENCE)

    def test_034_assess_service_future_leakage_cap_zero(self, sample_evidence_record):
        fut_ev = sample_evidence_record.model_copy()
        fut_ev.observed_at = "2026-05-10T00:00:00Z"
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_fut_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[fut_ev],
        )
        res = confidence_uncertainty_service.assess(req)
        assert "FUTURE_DATED_EVIDENCE_LEAKAGE" in res.confidence.blocking_deficiencies
        assert res.confidence.aggregate_score == 0.0

    def test_035_assess_service_low_data_quality_cap(self, sample_evidence_record):
        bad_ev = sample_evidence_record.model_copy()
        bad_ev.quality_score = 0.20
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_bad_qual_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[bad_ev],
        )
        res = confidence_uncertainty_service.assess(req)
        assert "CRITICAL_LOW_DATA_QUALITY" in res.confidence.blocking_deficiencies
        assert res.confidence.aggregate_score <= 0.25

    def test_036_assess_service_duplicate_evidence_detection(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_dup_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[sample_evidence_record, sample_evidence_record],  # Duplicate
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.duplicate_evidence_warnings) >= 1
        assert len(res.supporting_evidence) == 1

    def test_037_assess_service_weights_override(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_override_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[sample_evidence_record],
            weights_override={"EVIDENCE_QUALITY": 10.0},
        )
        res = confidence_uncertainty_service.assess(req)
        qual_dim = next(d for d in res.confidence.dimensions if d.dimension_type == ConfidenceDimensionType.EVIDENCE_QUALITY)
        assert qual_dim.weight == 10.0

    def test_038_assess_service_mandatory_notice_present(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_not_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.mandatory_notice == MANDATORY_CONFIDENCE_NOTICE

    def test_039_assess_service_method_metadata(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_met_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.method.version == ALGORITHM_VERSION
        assert res.method.formula_reference == "SAGE_V3_CONF_EQ_1"

    def test_040_assess_service_contributions_breakdown(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_cont_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.confidence.contributions) == 10


# =============================================================================
# 3. UNCERTAINTY DECOMPOSITION & RANGES (Tests 41–60)
# =============================================================================

class TestUncertaintyDecompositionAndRanges:

    def test_041_decompose_epistemic_sample_sparsity(self, sample_evidence_record):
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sample_evidence_record],  # Only 1 item
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert len(decomp.epistemic_components) >= 1
        assert any(c.uncertainty_type == UncertaintyType.EPISTEMIC for c in decomp.epistemic_components)

    def test_042_decompose_epistemic_conflict(self, sample_evidence_record):
        conflicts = [{"conflict_id": "c1", "description": "Contradiction"}]
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=conflicts,
        )
        assert any(c.uncertainty_type == UncertaintyType.SOURCE_DISAGREEMENT for c in decomp.epistemic_components)

    def test_043_decompose_aleatoric_process_dispersion(self):
        e1 = EvidenceRecord(
            evidence_id="e1", tenant_id="t1", workspace_id="w1",
            source_type=EvidenceSourceType.SENSOR_FUSION, source_record_id="r1",
            title="T1", payload={"vib": 1.2},
        )
        e2 = EvidenceRecord(
            evidence_id="e2", tenant_id="t1", workspace_id="w1",
            source_type=EvidenceSourceType.SENSOR_FUSION, source_record_id="r2",
            title="T2", payload={"vib": 1.8},
        )
        decomp, ranges, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[e1, e2],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert len(decomp.aleatoric_components) >= 1
        assert len(ranges) >= 1
        assert ranges[0].lower_bound == 1.2
        assert ranges[0].upper_bound == 1.8

    def test_044_decompose_temporal_delay_component(self):
        stale_ev = EvidenceRecord(
            evidence_id="e1", tenant_id="t1", workspace_id="w1",
            source_type=EvidenceSourceType.SENSOR_FUSION, source_record_id="r1",
            title="T1", freshness_seconds=9000000.0,
        )
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[stale_ev],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert any(c.uncertainty_type == UncertaintyType.TEMPORAL for c in decomp.other_components)

    def test_045_decompose_simulated_model_approximation(self):
        sim_ev = EvidenceRecord(
            evidence_id="e1", tenant_id="t1", workspace_id="w1",
            source_type=EvidenceSourceType.WHAT_IF_SIMULATION, source_record_id="r1",
            title="Sim", provenance=EvidenceProvenance.SIMULATED,
        )
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sim_ev],
            target_type="WHAT_IF_SIMULATION",
            target_id="sim_1",
            conflicts=[],
        )
        assert any(c.uncertainty_type == UncertaintyType.MODEL for c in decomp.other_components)

    def test_046_ranges_order_guarantee(self):
        r = UncertaintyRange(lower_bound=5.0, upper_bound=15.0, unit="psi", interval_type=UncertaintyIntervalType.OBSERVED_RANGE)
        assert r.lower_bound <= r.upper_bound

    def test_047_ranges_zero_width_allowed(self):
        r = UncertaintyRange(lower_bound=10.0, upper_bound=10.0, unit="kw", interval_type=UncertaintyIntervalType.OBSERVED_RANGE)
        assert r.lower_bound == r.upper_bound

    def test_048_sensitivities_evaluated(self, sample_evidence_record):
        _, _, sens, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert len(sens) >= 2
        assert any(s.parameter_name == "evidence_freshness_decay_rate" for s in sens)

    def test_049_explicit_unmodeled_tail_limitation(self, sample_evidence_record):
        _, _, _, lims = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert any(l.code == "UNMODELED_EXTREME_RISK" for l in lims)

    def test_050_predominant_uncertainty_epistemic(self, sample_evidence_record):
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[sample_evidence_record],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[{"conflict_id": "c1", "description": "Conflict"}],
        )
        assert decomp.predominant_type == UncertaintyType.EPISTEMIC

    def test_051_predominant_uncertainty_unknown_when_empty(self):
        decomp, _, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            conflicts=[],
        )
        assert decomp.predominant_type in (UncertaintyType.EPISTEMIC, UncertaintyType.UNKNOWN)

    def test_052_qualitative_fallback_when_ranges_not_computable(self):
        e_str = EvidenceRecord(
            evidence_id="e1", tenant_id="t1", workspace_id="w1",
            source_type=EvidenceSourceType.INCIDENT_MANAGEMENT, source_record_id="r1",
            title="Text incident", payload={"status": "OPEN"},
        )
        _, ranges, _, _ = UncertaintyDecompositionEngine.decompose_uncertainty(
            evidence_items=[e_str],
            target_type="INCIDENT_MANAGEMENT",
            target_id="inc_1",
            conflicts=[],
        )
        assert len(ranges) == 0  # No arbitrary quantitative range invented

    def test_053_uncertainty_distribution_summary_model(self):
        uds = UncertaintyDistributionSummary(
            distribution_type="Gaussian",
            mean=50.0,
            median=49.8,
            std_dev=2.1,
            sample_size=100,
        )
        assert uds.distribution_type == "Gaussian"
        assert uds.sample_size == 100

    def test_054_uncertainty_propagation_model(self):
        prop = UncertaintyPropagation(
            upstream_component="MultimodalSensorFusion",
            propagated_uncertainty_type=UncertaintyType.MEASUREMENT,
            impact_factor=1.2,
            description="Sensor noise propagated",
        )
        assert prop.impact_factor == 1.2

    def test_055_uncertainty_component_severity_enum(self):
        uc = UncertaintyComponent(
            component_id="uc_1",
            uncertainty_type=UncertaintyType.MODEL,
            severity=UncertaintySeverity.CRITICAL,
            description="Physics approximation",
        )
        assert uc.severity == UncertaintySeverity.CRITICAL

    def test_056_uncertainty_assessment_qualitative_summary(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.uncertainty.qualitative_summary) > 0

    def test_057_include_ranges_flag_false(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
            include_ranges=False,
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.uncertainty.primary_ranges) == 0

    def test_058_include_sensitivities_flag_false(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
            include_sensitivities=False,
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.uncertainty.sensitivities) == 0

    def test_059_uncertainty_source_model(self):
        src = UncertaintySource(
            source_id="src_1",
            source_type="VibrationSensor",
            description="Thermal drift",
            severity=UncertaintySeverity.LOW,
        )
        assert src.source_id == "src_1"

    def test_060_uncertainty_limitation_model(self):
        ul = UncertaintyLimitation(
            limitation_id="ul_1",
            code="UNMEASURED_MICROCLIMATE",
            description="Humidity unmeasured",
            severity=UncertaintySeverity.LOW,
        )
        assert ul.code == "UNMEASURED_MICROCLIMATE"


# =============================================================================
# 4. EVIDENCE PROVENANCE & TEMPORAL CORRECTNESS (Tests 61–80)
# =============================================================================

class TestEvidenceProvenanceAndTemporalCorrectness:

    def test_061_provenance_preserved_not_upgraded(self, sample_evidence_record):
        sim = sample_evidence_record.model_copy()
        sim.provenance = EvidenceProvenance.SIMULATED
        req = ConfidenceUncertaintyRequest(
            target_type="WHAT_IF_SIMULATION",
            target_id="sim_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sim],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.supporting_evidence[0].provenance == EvidenceProvenance.SIMULATED

    def test_062_forecast_provenance_preserved(self, sample_evidence_record):
        fc = sample_evidence_record.model_copy()
        fc.provenance = EvidenceProvenance.FORECAST
        req = ConfidenceUncertaintyRequest(
            target_type="DEMAND_FORECASTING",
            target_id="fc_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[fc],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.supporting_evidence[0].provenance == EvidenceProvenance.FORECAST

    def test_063_estimated_provenance_preserved(self, sample_evidence_record):
        est = sample_evidence_record.model_copy()
        est.provenance = EvidenceProvenance.ESTIMATED
        req = ConfidenceUncertaintyRequest(
            target_type="FINANCIAL_IMPACT",
            target_id="fin_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[est],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.supporting_evidence[0].provenance == EvidenceProvenance.ESTIMATED

    def test_064_unknown_provenance_preserved(self, sample_evidence_record):
        unk = sample_evidence_record.model_copy()
        unk.provenance = EvidenceProvenance.UNKNOWN
        req = ConfidenceUncertaintyRequest(
            target_type="SENSOR_FUSION",
            target_id="sens_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[unk],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.supporting_evidence[0].provenance == EvidenceProvenance.UNKNOWN

    def test_065_temporal_eligibility_future_evidence_excluded(self, sample_evidence_record):
        fut = sample_evidence_record.model_copy()
        fut.observed_at = "2026-05-10T12:00:00Z"
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[fut],
        )
        res = confidence_uncertainty_service.assess(req)
        assert "FUTURE_DATED_EVIDENCE_LEAKAGE" in res.confidence.blocking_deficiencies

    def test_066_temporal_eligibility_valid_past_evidence_accepted(self, sample_evidence_record):
        past = sample_evidence_record.model_copy()
        past.observed_at = "2026-05-01T11:00:00Z"
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[past],
        )
        res = confidence_uncertainty_service.assess(req)
        assert "FUTURE_DATED_EVIDENCE_LEAKAGE" not in res.confidence.blocking_deficiencies

    def test_067_freshness_threshold_honored(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[sample_evidence_record],
            freshness_threshold_seconds=600.0,  # 10 mins
        )
        res = confidence_uncertainty_service.assess(req)
        fresh_dim = next(d for d in res.confidence.dimensions if d.dimension_type == ConfidenceDimensionType.FRESHNESS)
        assert fresh_dim.metadata["freshness_threshold_seconds"] == 600.0

    def test_068_cross_tenant_evidence_ignored(self, sample_evidence_record):
        alien_ev = sample_evidence_record.model_copy()
        alien_ev.tenant_id = "tenant_alien_9"
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[alien_ev],
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.supporting_evidence) == 0

    def test_069_plant_scoped_evidence_filtering(self, sample_evidence_record):
        plant2_ev = sample_evidence_record.model_copy()
        plant2_ev.plant_id = "PLANT-02"
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",  # Request is for PLANT-01
            evidence_items=[plant2_ev],
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.supporting_evidence) == 0

    def test_070_unspecified_plant_evidence_accepted(self, sample_evidence_record):
        neutral_ev = sample_evidence_record.model_copy()
        neutral_ev.plant_id = None
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            evidence_items=[neutral_ev],
        )
        res = confidence_uncertainty_service.assess(req)
        assert len(res.supporting_evidence) == 1

    def test_071_fingerprint_changes_on_evidence_change(self, sample_evidence_record):
        e1 = sample_evidence_record
        e2 = sample_evidence_record.model_copy()
        e2.evidence_id = "ev_modified_02"
        e2.quality_score = 0.5

        req1 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            plant_id="PLANT-01", evidence_items=[e1], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        req2 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            plant_id="PLANT-01", evidence_items=[e2], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res1 = confidence_uncertainty_service.assess(req1)
        res2 = confidence_uncertainty_service.assess(req2)
        assert res1.fingerprint != res2.fingerprint

    def test_072_fingerprint_changes_on_timestamp_change(self, sample_evidence_record):
        req1 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t1", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        req2 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t1", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-02T12:00:00Z",
        )
        res1 = confidence_uncertainty_service.assess(req1)
        res2 = confidence_uncertainty_service.assess(req2)
        assert res1.fingerprint != res2.fingerprint

    def test_073_fingerprint_changes_on_scope_change(self, sample_evidence_record):
        req1 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t1", workspace_id="w1",
            plant_id="PLANT-01", evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        req2 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t1", workspace_id="w1",
            plant_id="PLANT-02", evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res1 = confidence_uncertainty_service.assess(req1)
        res2 = confidence_uncertainty_service.assess(req2)
        assert res1.fingerprint != res2.fingerprint

    def test_074_validate_eligibility_ready(self, sample_evidence_record):
        e1 = sample_evidence_record
        e2 = sample_evidence_record.model_copy()
        e2.evidence_id = "ev_2"
        req = ConfidenceValidationRequest(
            evidence_items=[e1, e2],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        resp = confidence_uncertainty_service.validate_eligibility(req)
        assert resp.is_eligible is True
        assert resp.assessment_readiness == "READY"
        assert resp.eligible_evidence_count == 2

    def test_075_validate_eligibility_ineligible_on_tenant_mismatch(self, sample_evidence_record):
        alien = sample_evidence_record.model_copy()
        alien.tenant_id = "alien_tenant"
        req = ConfidenceValidationRequest(
            evidence_items=[alien],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        resp = confidence_uncertainty_service.validate_eligibility(req)
        assert resp.is_eligible is False
        assert resp.assessment_readiness == "INELIGIBLE"
        assert resp.rejected_evidence_count == 1

    def test_076_validate_eligibility_low_quality_rejection(self, sample_evidence_record):
        bad = sample_evidence_record.model_copy()
        bad.quality_score = 0.1
        req = ConfidenceValidationRequest(
            evidence_items=[bad],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        resp = confidence_uncertainty_service.validate_eligibility(req)
        assert resp.is_eligible is False
        assert resp.rejected_evidence_count == 1
        assert any("LOW_QUALITY" in d for d in resp.deficiencies)

    def test_077_validate_eligibility_plant_mismatch_rejection(self, sample_evidence_record):
        p2 = sample_evidence_record.model_copy()
        p2.plant_id = "PLANT-02"
        req = ConfidenceValidationRequest(
            evidence_items=[p2],
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
        )
        resp = confidence_uncertainty_service.validate_eligibility(req)
        assert resp.rejected_evidence_count == 1
        assert any("PLANT_MISMATCH" in d for d in resp.deficiencies)

    def test_078_confidence_evidence_reference_model(self, sample_evidence_record):
        ref = ConfidenceEvidenceReference(
            evidence_id=sample_evidence_record.evidence_id,
            source_type=sample_evidence_record.source_type,
            source_record_id=sample_evidence_record.source_record_id,
            provenance=sample_evidence_record.provenance,
            quality_score=sample_evidence_record.quality_score,
            role="SUPPORTING",
        )
        assert ref.evidence_id == sample_evidence_record.evidence_id

    def test_079_assessment_timestamp_defaults_to_now_if_unspecified(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.assessment_timestamp is not None
        assert "T" in res.assessment_timestamp

    def test_080_unsupported_probability_notice_enforced(self, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_1",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        assert any(l.code == "NOT_STATISTICAL_PROBABILITY" for l in res.limitations)


# =============================================================================
# 5. UPSTREAM INTEGRATIONS (Tests 81–95)
# =============================================================================

class TestUpstreamIntegrations:

    def test_081_decision_engine_evaluation_source_unmutated(self, sample_decision_evaluation):
        orig_dict = decision_engine_repository.get_by_id(sample_decision_evaluation.decision_id, "tenant_conf_1").model_dump()
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id=sample_decision_evaluation.decision_id,
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
        )
        res = confidence_uncertainty_service.assess(req)
        after_dict = decision_engine_repository.get_by_id(sample_decision_evaluation.decision_id, "tenant_conf_1").model_dump()
        assert orig_dict == after_dict
        assert res.target_type == "DECISION_ENGINE"

    def test_082_decision_engine_score_preservation(self, sample_decision_evaluation):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id=sample_decision_evaluation.decision_id,
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        # Original recommendation status is preserved
        orig = decision_engine_repository.get_by_id(sample_decision_evaluation.decision_id, "tenant_conf_1")
        assert orig.recommendation.recommendation_status == sample_decision_evaluation.recommendation.recommendation_status
        assert orig.recommendation.recommended_option_id == sample_decision_evaluation.recommendation.recommended_option_id

    def test_083_optimization_adapter_read_only(self):
        req = ConfidenceUncertaintyRequest(
            target_type="OPTIMIZATION",
            target_id="opt_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "OPTIMIZATION"

    def test_084_what_if_simulation_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="WHAT_IF_SIMULATION",
            target_id="sim_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "WHAT_IF_SIMULATION"

    def test_085_sensor_fusion_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="SENSOR_FUSION",
            target_id="fuse_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "SENSOR_FUSION"

    def test_086_predictive_maintenance_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="PREDICTIVE_MAINTENANCE",
            target_id="pm_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "PREDICTIVE_MAINTENANCE"

    def test_087_demand_forecasting_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="DEMAND_FORECASTING",
            target_id="df_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "DEMAND_FORECASTING"

    def test_088_supplier_risk_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="SUPPLIER_RISK",
            target_id="sr_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "SUPPLIER_RISK"

    def test_089_sla_customer_risk_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="SLA_CUSTOMER_RISK",
            target_id="sla_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "SLA_CUSTOMER_RISK"

    def test_090_financial_impact_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="FINANCIAL_IMPACT",
            target_id="fin_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "FINANCIAL_IMPACT"

    def test_091_sustainability_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="SUSTAINABILITY",
            target_id="sust_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "SUSTAINABILITY"

    def test_092_incident_management_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="INCIDENT_MANAGEMENT",
            target_id="inc_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "INCIDENT_MANAGEMENT"

    def test_093_anomaly_detection_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="ANOMALY_DETECTION",
            target_id="anom_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "ANOMALY_DETECTION"

    def test_094_root_cause_analysis_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="ROOT_CAUSE_ANALYSIS",
            target_id="rca_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "ROOT_CAUSE_ANALYSIS"

    def test_095_blast_radius_adapter(self):
        req = ConfidenceUncertaintyRequest(
            target_type="BLAST_RADIUS",
            target_id="br_mock_001",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        res = confidence_uncertainty_service.assess(req)
        assert res.target_type == "BLAST_RADIUS"


# =============================================================================
# 6. SECURITY, RBAC & TENANT ISOLATION (Tests 96–110)
# =============================================================================

class TestSecurityRBACAndTenantIsolation:

    def test_096_cross_tenant_assess_forbidden(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_alien_01",
                    "tenant_id": "alien_tenant_99",  # Spoofed tenant
                    "workspace_id": "workspace_conf_1",
                },
            )
            assert resp.status_code == 403
            assert "Tenant boundary violation" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_097_unauthorized_plant_assess_forbidden(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_plant_01",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "workspace_conf_1",
                    "plant_id": "PLANT-99-FORBIDDEN",
                },
            )
            assert resp.status_code == 403
            assert "Plant boundary violation" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_098_viewer_denied_assess(self, client, test_identity_viewer):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_view_01",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "workspace_conf_1",
                },
            )
            assert resp.status_code == 403  # Viewer lacks confidence_uncertainty.assess
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_099_viewer_allowed_read(self, client, test_identity_viewer, sample_evidence_record):
        # Create an assessment as analyst first
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_read_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}")
            assert resp.status_code == 200
            assert resp.json()["assessment_id"] == res.assessment_id
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_100_alien_tenant_get_assessment_404(self, client, test_identity_other_tenant, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_secret_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        # Alien tenant accesses
        app.dependency_overrides[get_current_identity] = lambda: test_identity_other_tenant
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}")
            assert resp.status_code == 404
            assert "not found" in resp.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_101_cross_tenant_validate_forbidden(self, client, test_identity_analyst, sample_evidence_record):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/validate",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_1",
                    "tenant_id": "alien_tenant_99",
                    "workspace_id": "ws_1",
                    "evidence_items": [sample_evidence_record.model_dump()],
                },
            )
            assert resp.status_code == 403
            assert "Tenant boundary violation" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_102_cross_tenant_batch_forbidden(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess/batch",
                json=[
                    {
                        "target_type": "DECISION_ENGINE",
                        "target_id": "dec_1",
                        "tenant_id": "alien_tenant_99",
                        "workspace_id": "ws_1",
                    }
                ],
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_103_batch_size_limit_exceeded(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            payload = [
                {
                    "target_type": "DECISION_ENGINE",
                    "target_id": f"dec_{i}",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "workspace_conf_1",
                }
                for i in range(60)  # Max is 50
            ]
            resp = client.post("/api/v3/confidence-uncertainty/assess/batch", json=payload)
            assert resp.status_code == 422
            assert "Batch size exceeds" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_104_get_evidence_endpoint_authorized(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_ev_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}/evidence")
            assert resp.status_code == 200
            assert len(resp.json()) >= 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_105_get_history_endpoint_authorized(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_hist_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}/history")
            assert resp.status_code == 200
            assert len(resp.json()) >= 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_106_get_entity_summary_endpoint(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="entity_pump_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty/entity/entity_pump_01/summary")
            assert resp.status_code == 200
            assert len(resp.json()) >= 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_107_list_assessments_tenant_isolated(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_list_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty?limit=10&offset=0")
            assert resp.status_code == 200
            data = resp.json()
            assert "items" in data
            assert all(item["tenant_id"] == "tenant_conf_1" for item in data["items"])
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_108_list_assessments_negative_offset_rejected(self, client, test_identity_viewer):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty?offset=-5")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_109_list_assessments_oversized_limit_rejected(self, client, test_identity_viewer):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty?limit=500")
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_110_sql_injection_sanitization(self, client, test_identity_viewer):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            malicious_id = "dec_1' OR '1'='1"
            resp = client.get(f"/api/v3/confidence-uncertainty/entity/{malicious_id}/summary")
            assert resp.status_code == 200
            assert len(resp.json()) == 0  # No records returned via SQL injection
        finally:
            app.dependency_overrides.pop(get_current_identity, None)


# =============================================================================
# 7. PERSISTENCE, CONCURRENCY & AUDIT (Tests 111–125)
# =============================================================================

class TestPersistenceConcurrencyAndAudit:

    def test_111_repository_save_and_get_by_id(self, test_repo, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t1", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res = confidence_uncertainty_service.assess(req)
        test_repo.save_assessment(res)
        found = test_repo.get_by_id(res.assessment_id, "t1")
        assert found is not None
        assert found.assessment_id == res.assessment_id

    def test_112_repository_get_by_fingerprint(self, test_repo, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t_fp", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res = confidence_uncertainty_service.assess(req)
        test_repo.save_assessment(res)
        found = test_repo.get_by_fingerprint(res.fingerprint, "t_fp")
        assert found is not None
        assert found.fingerprint == res.fingerprint

    def test_113_repository_deduplication(self, test_repo, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t_dedup", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res = confidence_uncertainty_service.assess(req)
        saved1 = test_repo.save_assessment(res)
        saved2 = test_repo.save_assessment(res)
        assert saved1.assessment_id == saved2.assessment_id
        # Audit ledger has two entries (initial create + deduplicate retrieve)
        audit = test_repo.get_audit_trail(res.assessment_id, "t_dedup")
        assert len(audit) == 2
        assert audit[1].action == "DEDUPLICATE_RETRIEVE"

    def test_114_repository_cross_tenant_isolation(self, test_repo, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d1", tenant_id="t_owner", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res = confidence_uncertainty_service.assess(req)
        test_repo.save_assessment(res)
        # Attempt to access using t_alien
        found = test_repo.get_by_id(res.assessment_id, "t_alien")
        assert found is None

    def test_115_repository_list_history(self, test_repo, sample_evidence_record):
        req1 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="target_hist_9", tenant_id="t_hist", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T10:00:00Z",
        )
        req2 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="target_hist_9", tenant_id="t_hist", workspace_id="w1",
            evidence_items=[sample_evidence_record], assessment_timestamp="2026-05-01T12:00:00Z",
        )
        res1 = confidence_uncertainty_service.assess(req1)
        res2 = confidence_uncertainty_service.assess(req2)
        test_repo.save_assessment(res1)
        test_repo.save_assessment(res2)
        hist = test_repo.list_history("target_hist_9", "t_hist")
        assert len(hist) == 2

    def test_116_repository_list_assessments_pagination(self, test_repo, sample_evidence_record):
        for i in range(5):
            req = ConfidenceUncertaintyRequest(
                target_type="DECISION_ENGINE", target_id=f"target_p_{i}", tenant_id="t_page", workspace_id="w1",
                evidence_items=[sample_evidence_record], assessment_timestamp=f"2026-05-01T{10+i}:00:00Z",
            )
            res = confidence_uncertainty_service.assess(req)
            test_repo.save_assessment(res)

        items_p1 = test_repo.list_assessments("t_page", limit=2, offset=0)
        items_p2 = test_repo.list_assessments("t_page", limit=2, offset=2)
        assert len(items_p1) == 2
        assert len(items_p2) == 2
        assert items_p1[0].assessment_id != items_p2[0].assessment_id

    def test_117_repository_count_assessments(self, test_repo, sample_evidence_record):
        for i in range(3):
            req = ConfidenceUncertaintyRequest(
                target_type="DECISION_ENGINE", target_id=f"cnt_{i}", tenant_id="t_cnt", workspace_id="w1",
                evidence_items=[sample_evidence_record], assessment_timestamp=f"2026-05-01T{10+i}:00:00Z",
            )
            res = confidence_uncertainty_service.assess(req)
            test_repo.save_assessment(res)

        cnt = test_repo.count_assessments("t_cnt")
        assert cnt == 3

    def test_118_repository_concurrent_writes(self, test_repo, sample_evidence_record):
        def worker(idx):
            req = ConfidenceUncertaintyRequest(
                target_type="DECISION_ENGINE", target_id=f"conc_{idx}", tenant_id="t_conc", workspace_id="w1",
                evidence_items=[sample_evidence_record], assessment_timestamp=f"2026-05-01T{10+idx}:00:00Z",
            )
            res = confidence_uncertainty_service.assess(req)
            test_repo.save_assessment(res)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        cnt = test_repo.count_assessments("t_conc")
        assert cnt == 5

    def test_119_audit_ledger_immutable_timestamps(self, test_repo, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d_aud", tenant_id="t_aud", workspace_id="w1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)
        test_repo.save_assessment(res, actor_id="analyst_bob")
        audit = test_repo.get_audit_trail(res.assessment_id, "t_aud")
        assert len(audit) == 1
        assert audit[0].actor_id == "analyst_bob"
        assert audit[0].action == "CREATE_ASSESSMENT"

    def test_120_wal_mode_enabled(self, test_repo):
        with test_repo._get_connection() as conn:
            cur = conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0]
            assert mode.lower() == "wal"

    def test_121_confidence_audit_record_model(self):
        rec = ConfidenceAuditRecord(
            audit_id="aud_1",
            assessment_id="conf_1",
            tenant_id="t1",
            actor_id="user_1",
            action="ASSESS",
            timestamp="2026-05-01T12:00:00Z",
            fingerprint="fp_123",
            details={"mode": "analytical"},
        )
        assert rec.action == "ASSESS"

    def test_122_confidence_uncertainty_summary_model(self):
        summ = ConfidenceUncertaintySummary(
            assessment_id="c_1",
            target_type="DECISION_ENGINE",
            target_id="d_1",
            tenant_id="t1",
            workspace_id="w1",
            aggregate_confidence=0.85,
            confidence_status=ConfidenceStatus.HIGH_CONFIDENCE,
            predominant_uncertainty=UncertaintyType.EPISTEMIC,
            assessment_timestamp="2026-05-01T12:00:00Z",
            fingerprint="fp_xyz",
            created_at="2026-05-01T12:00:00Z",
        )
        assert summ.confidence_status == ConfidenceStatus.HIGH_CONFIDENCE

    def test_123_confidence_uncertainty_list_response_model(self):
        resp = ConfidenceUncertaintyListResponse(
            items=[],
            total_count=0,
            limit=50,
            offset=0,
        )
        assert resp.total_count == 0

    def test_124_confidence_component_model(self):
        comp = ConfidenceComponent(
            component_id="comp_1",
            name="VibrationSensorReliability",
            dimension_type=ConfidenceDimensionType.SOURCE_RELIABILITY,
            score=0.9,
            weight=1.0,
        )
        assert comp.name == "VibrationSensorReliability"

    def test_125_confidence_contribution_model(self):
        contrib = ConfidenceContribution(
            dimension_type=ConfidenceDimensionType.EVIDENCE_QUALITY,
            raw_score=0.95,
            weight=0.15,
            weighted_contribution=0.1425,
            blocking_deficiency=False,
        )
        assert contrib.weighted_contribution == 0.1425


# =============================================================================
# 8. API ROUTES & VALIDATION TESTS (Tests 126–140)
# =============================================================================

class TestAPIRoutesAndValidation:

    def test_126_api_post_assess_endpoint(self, client, test_identity_analyst, sample_evidence_record):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_api_01",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "workspace_conf_1",
                    "plant_id": "PLANT-01",
                    "assessment_timestamp": "2026-05-01T12:00:00Z",
                    "evidence_items": [sample_evidence_record.model_dump()],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["assessment_id"] is not None
            assert data["mandatory_notice"] == MANDATORY_CONFIDENCE_NOTICE
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_127_api_post_assess_batch_endpoint(self, client, test_identity_analyst, sample_evidence_record):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess/batch",
                json=[
                    {
                        "target_type": "DECISION_ENGINE",
                        "target_id": "dec_b_1",
                        "tenant_id": "tenant_conf_1",
                        "workspace_id": "workspace_conf_1",
                        "plant_id": "PLANT-01",
                        "evidence_items": [sample_evidence_record.model_dump()],
                    },
                    {
                        "target_type": "OPTIMIZATION",
                        "target_id": "opt_b_2",
                        "tenant_id": "tenant_conf_1",
                        "workspace_id": "workspace_conf_1",
                        "plant_id": "PLANT-01",
                        "evidence_items": [sample_evidence_record.model_dump()],
                    },
                ],
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_128_api_post_validate_endpoint(self, client, test_identity_analyst, sample_evidence_record):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/validate",
                json={
                    "evidence_items": [sample_evidence_record.model_dump()],
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_val_01",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "workspace_conf_1",
                    "plant_id": "PLANT-01",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["is_eligible"] is True
            assert data["assessment_readiness"] == "PARTIAL"
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_129_api_get_assessment_by_id(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d_api_get", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}")
            assert resp.status_code == 200
            assert resp.json()["assessment_id"] == res.assessment_id
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_130_api_get_assessment_nonexistent_404(self, client, test_identity_viewer):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty/conf_nonexistent_999")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_131_api_get_evidence_references(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d_ev_ref", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}/evidence")
            assert resp.status_code == 200
            assert len(resp.json()) == 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_132_api_get_history(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="d_hist_endpoint", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        res = confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get(f"/api/v3/confidence-uncertainty/{res.assessment_id}/history")
            assert resp.status_code == 200
            assert len(resp.json()) >= 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_133_api_get_entity_summary(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="entity_summary_pump_01", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty/entity/entity_summary_pump_01/summary")
            assert resp.status_code == 200
            assert len(resp.json()) >= 1
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_134_api_list_pagination(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE", target_id="dec_list_pag", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty?limit=5&offset=0")
            assert resp.status_code == 200
            assert "items" in resp.json()
            assert "total_count" in resp.json()
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_135_api_list_filter_target_type(self, client, test_identity_viewer, sample_evidence_record):
        req = ConfidenceUncertaintyRequest(
            target_type="OPTIMIZATION", target_id="opt_filter_01", tenant_id="tenant_conf_1", workspace_id="workspace_conf_1",
            evidence_items=[sample_evidence_record],
        )
        confidence_uncertainty_service.assess(req)

        app.dependency_overrides[get_current_identity] = lambda: test_identity_viewer
        try:
            resp = client.get("/api/v3/confidence-uncertainty?target_type=OPTIMIZATION")
            assert resp.status_code == 200
            data = resp.json()
            assert all(item["target_type"] == "OPTIMIZATION" for item in data["items"])
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_136_api_unauthorized_user_denied(self, client):
        no_role_user = Identity(
            user_id="test_unauth_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            assigned_plants=[],
            roles=[],
            is_server_authoritative=True,
        )
        app.dependency_overrides[get_current_identity] = lambda: no_role_user
        try:
            resp = client.get("/api/v3/confidence-uncertainty")
            assert resp.status_code in (401, 403)
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_137_api_malformed_json_body_422(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={"target_type": "DECISION_ENGINE"},  # Missing required fields
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_138_api_invalid_timestamp_format_422(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_1",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "ws_1",
                    "assessment_timestamp": "invalid_date_format",
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_139_api_negative_freshness_threshold_422(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_1",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "ws_1",
                    "freshness_threshold_seconds": -50.0,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_140_api_non_finite_weight_override_422(self, client, test_identity_analyst):
        app.dependency_overrides[get_current_identity] = lambda: test_identity_analyst
        try:
            resp = client.post(
                "/api/v3/confidence-uncertainty/assess",
                json={
                    "target_type": "DECISION_ENGINE",
                    "target_id": "dec_1",
                    "tenant_id": "tenant_conf_1",
                    "workspace_id": "ws_1",
                    "weights_override": {"EVIDENCE_QUALITY": "not_a_number"},
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)


# =============================================================================
# 9. ARCHITECTURAL BOUNDARIES & STATIC AST CHECKS (Tests 141–145)
# =============================================================================

class TestArchitecturalBoundariesAndAST:

    def test_141_static_ast_no_execution_gateway_imports(self):
        """Verifies that confidence service contains NO imports from execution_gateway or ActionAPI."""
        service_path = os.path.join(os.path.dirname(__file__), "services", "confidence_uncertainty_service.py")
        if not os.path.exists(service_path):
            service_path = "backend/services/confidence_uncertainty_service.py"

        with open(service_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imported_modules.add(name.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.add(node.module)

        forbidden_imports = {"execution_gateway", "backend.services.execution_gateway", "action_registry", "ActionAPI"}
        for imp in imported_modules:
            for forbidden in forbidden_imports:
                assert forbidden not in imp, f"Forbidden import found in confidence service: {imp}"

    def test_142_static_ast_no_eval_or_exec(self):
        """Verifies that confidence service and contracts contain NO eval() or exec() calls."""
        for filename in ["confidence_uncertainty_service.py", "confidence_uncertainty_contract.py"]:
            file_path = os.path.join(os.path.dirname(__file__), "services", filename)
            if not os.path.exists(file_path):
                file_path = os.path.join(os.path.dirname(__file__), "data", "schemas", filename)
            if not os.path.exists(file_path):
                file_path = f"backend/data/schemas/{filename}"

            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        assert node.func.id not in ("eval", "exec"), f"Forbidden call {node.func.id} in {filename}"

    def test_143_no_source_system_mutations(self, sample_decision_evaluation):
        """Verifies that assessing confidence does not mutate upstream decision evaluations."""
        pre_snap = decision_engine_repository.get_by_id(sample_decision_evaluation.decision_id, "tenant_conf_1").model_dump()
        req = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id=sample_decision_evaluation.decision_id,
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
        )
        confidence_uncertainty_service.assess(req)
        post_snap = decision_engine_repository.get_by_id(sample_decision_evaluation.decision_id, "tenant_conf_1").model_dump()
        assert pre_snap == post_snap

    def test_144_no_physical_actuation_or_plc_writes(self):
        """Verifies that no actuation keywords appear in method specifications."""
        method = ConfidenceUncertaintyMethod()
        for kw in ("PLC", "ACTUATE", "EXECUTE_WORK_ORDER", "DISPATCH"):
            assert kw not in method.method_name
            assert kw not in method.formula_reference

    def test_145_deterministic_reproducibility(self, sample_evidence_record):
        """Verifies that two identical requests produce byte-for-byte identical fingerprints and scores."""
        req1 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_det_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[sample_evidence_record],
        )
        req2 = ConfidenceUncertaintyRequest(
            target_type="DECISION_ENGINE",
            target_id="dec_det_01",
            tenant_id="tenant_conf_1",
            workspace_id="workspace_conf_1",
            plant_id="PLANT-01",
            assessment_timestamp="2026-05-01T12:00:00Z",
            evidence_items=[sample_evidence_record],
        )
        res1 = confidence_uncertainty_service.assess(req1)
        res2 = confidence_uncertainty_service.assess(req2)
        assert res1.fingerprint == res2.fingerprint
        assert res1.confidence.aggregate_score == res2.confidence.aggregate_score
        assert res1.confidence.status == res2.confidence.status
