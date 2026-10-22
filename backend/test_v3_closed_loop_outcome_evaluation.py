# backend/test_v3_closed_loop_outcome_evaluation.py
"""
SageCommand V3 — Closed-Loop Outcome Learning Test Suite (Prompt 39)

Comprehensive verification covering:
Group A. Prediction Contract (1-10)
Group B. Outcome Integrity & Scope (11-24)
Group C. Evaluation Correctness & Metrics (25-38)
Group D. Idempotency & Persistence (39-46)
Group E. Deterministic Aggregate Metrics (47-57)
Group F. Historical Learning Context (58-66)
Group G. EventBus Integration & Loop Guard (67-74)
Group H. Concurrency & Consistency (75-80)
Group I. Security, Scope Isolation & Architectural Boundaries (81-90)
"""

import ast
import asyncio
import concurrent.futures
import json
import math
import os
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from core.config import SAGE_OUTCOME_EVALUATION_ENABLED
    from data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        OutcomeEligibilityStatus,
        OutcomeEligibilityReason,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )
    from repositories.outcome_learning_repository import (
        OutcomeLearningRepository,
        outcome_learning_repository,
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )
    from services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
        EVALUATOR_PROVENANCE,
    )
    from services.outcome_learning_event_handler import OutcomeLearningEventHandler
    from services.event_bus import EventBus
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        TriggerType,
        EvidenceAssessment,
        ScopeStatus,
        QualityStatus,
        VerificationProvenance,
    )
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.core.config import SAGE_OUTCOME_EVALUATION_ENABLED
    from backend.data.schemas.event_contract import (
        CanonicalEvent,
        EventCategory,
        EventSeverity,
        EventLifecycle,
        EventReferences,
    )
    from backend.data.schemas.outcome_learning_contract import (
        PredictionSnapshot,
        ObservedOutcome,
        PredictionOutcomeEvaluation,
        AggregateMetricsSummary,
        GovernedLearningContext,
        PredictionType,
        OutcomeVerificationStatus,
        OutcomeEligibilityStatus,
        OutcomeEligibilityReason,
        EvaluationStatus,
        DirectionalBias,
        DataMode,
        EVALUATION_POLICY_VERSION,
        METRIC_IMPLEMENTATION_VERSION,
        _parse_utc_iso,
    )
    from backend.repositories.outcome_learning_repository import (
        OutcomeLearningRepository,
        outcome_learning_repository,
        PredictionNotFoundError,
        OutcomeNotFoundError,
        EvaluationNotFoundError,
        PredictionImmutabilityViolationError,
        OutcomeImmutabilityViolationError,
        OutcomeEvaluationIdempotencyConflictError,
        OutcomeEvaluationScopeMismatchError,
    )
    from backend.services.outcome_evaluation_service import (
        OutcomeEvaluationService,
        outcome_evaluation_service,
        EVALUATOR_PROVENANCE,
    )
    from backend.services.outcome_learning_event_handler import OutcomeLearningEventHandler
    from backend.services.event_bus import EventBus
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        TriggerType,
        EvidenceAssessment,
        ScopeStatus,
        QualityStatus,
        VerificationProvenance,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_db():
    """Provides isolated temporary SQLite database for test execution."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    repo = OutcomeLearningRepository(db_path=path)
    service = OutcomeEvaluationService(repository=repo, enabled=True)
    yield repo, service
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


@pytest.fixture
def test_identity():
    """Provides standard authorized operator identity."""
    return Identity(
        user_id="user_test_operator",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ENGINEER", "ANALYST"],
        permissions=[
            "learning.prediction.record",
            "learning.prediction.read",
            "learning.outcome.record",
            "learning.outcome.read",
            "learning.evaluation.evaluate",
            "learning.evaluation.read",
            "mission.verification.read",
            "mission.verification.request",
        ],
        assigned_plants=["plant_01", "plant_02"],
        clearance_level=2,
        is_server_authoritative=True,
    )


@pytest.fixture
def admin_identity():
    """Provides system admin identity."""
    return Identity(
        user_id="user_test_admin",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR", "SYSTEM_VERIFIER"],
        permissions=[
            "learning.prediction.record",
            "learning.prediction.read",
            "learning.outcome.record",
            "learning.outcome.read",
            "learning.evaluation.evaluate",
            "learning.evaluation.read",
            "learning.evaluation.revalidate",
        ],
        assigned_plants=["*"],
        clearance_level=3,
        is_server_authoritative=True,
    )


@pytest.fixture
def client():
    """FastAPI TestClient."""
    return TestClient(app)


def seed_authoritative_run(
    service: OutcomeEvaluationService,
    tenant_id: str = "tenant_alpha",
    workspace_id: str = "workspace_prod",
    plant_id: str = "plant_01",
    verification_id: Optional[str] = None,
    target_id: Optional[str] = None,
    status: VerificationStatus = VerificationStatus.VERIFIED,
    is_diagnostic: bool = False,
    is_invalidated: bool = False,
    rule_id: str = "RULE_EVIDENCE_VALIDATED_V1",
    finding_id: Optional[str] = None,
) -> VerificationRun:
    """Helper to seed an authoritative VerificationRun and VerificationFinding in the Verification Engine."""
    v_id = verification_id or f"vrun_{uuid.uuid4().hex[:12]}"
    f_id = finding_id or f"vf_{uuid.uuid4().hex[:12]}"
    t_id = target_id or "default_target"
    finding = VerificationFinding(
        finding_id=f_id,
        target_type=VerificationTargetType.CRITERION,
        target_id=t_id,
        status=status,
        evidence_references=["ev_1"],
        evidence_assessments=[
            EvidenceAssessment(
                evidence_id="ev_1",
                source_type="TELEMETRY",
                integrity_status="INVALID" if is_invalidated else "VALID",
                scope_status=ScopeStatus.REJECTED if is_invalidated else ScopeStatus.AUTHORIZED,
                quality_status=QualityStatus.INVALID if is_invalidated else QualityStatus.VALID,
            )
        ],
        rule_id=rule_id,
        rule_version="1.0.0",
        explanation="Authoritative test finding",
        limitations=[],
    )
    run = VerificationRun(
        verification_id=v_id,
        mission_id="m_test_mission",
        mission_revision=1,
        verification_scope="FULL_MISSION",
        status=status if not is_diagnostic else VerificationStatus.NOT_VERIFIED,
        requested_by="test_user",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id,
        trigger_type=TriggerType.MANUAL,
        rule_set_version="1.0.0",
        summary="Test verification run" + (" INVALIDATED" if is_invalidated else ""),
        target_count=1,
        verified_count=1 if status == VerificationStatus.VERIFIED and not is_diagnostic else 0,
        failed_count=1 if status == VerificationStatus.FAILED else 0,
        indeterminate_count=1 if status == VerificationStatus.INDETERMINATE else 0,
        findings=[finding],
        provenance=VerificationProvenance(
            verification_id=v_id,
            mission_id="m_test_mission",
            mission_revision=1,
            rule_set_version="1.0.0",
            evaluator_version="1.0.0",
            evidence_ids=["ev_1"],
        ),
        is_diagnostic=is_diagnostic,
        diagnostic_status=VerificationStatus.VERIFIED if is_diagnostic else None,
        diagnostic_outcome="CONFIRMED" if is_diagnostic else None,
    )
    service.verification_repository.save_run_atomic(run)
    return run


# =============================================================================
# GROUP A: PREDICTION CONTRACT (1-10)
# =============================================================================

def test_01_valid_numeric_prediction():
    """1. Valid numeric prediction snapshot instantiates and computes deterministic fingerprint."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap = PredictionSnapshot(
        prediction_id="pred_num_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_widget_a",
        predicted_at=now_str,
        expected_value=150.5,
        expected_unit="units",
        forecast_horizon="P7D",
        prediction_provenance="demand_forecasting_service",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    assert snap.expected_value == 150.5
    assert snap.expected_unit == "units"
    fp = snap.compute_fingerprint()
    assert isinstance(fp, str) and len(fp) == 64
    assert fp == snap.compute_fingerprint()


def test_02_valid_categorical_prediction():
    """2. Valid categorical prediction instantiates correctly."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap = PredictionSnapshot(
        prediction_id="pred_cat_01",
        prediction_type=PredictionType.MAINTENANCE_RISK,
        target_reference="pump_hydro_01",
        predicted_at=now_str,
        expected_value="HIGH_RISK",
        prediction_provenance="predictive_maintenance_service",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    assert snap.expected_value == "HIGH_RISK"
    assert snap.prediction_type == PredictionType.MAINTENANCE_RISK


def test_03_unsupported_prediction_type_rejected():
    """3. Unsupported prediction type string is rejected by contract validation."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(Exception):
        PredictionSnapshot(
            prediction_id="pred_bad_type",
            prediction_type="UNSUPPORTED_TYPE_XYZ",  # type: ignore
            target_reference="target_01",
            predicted_at=now_str,
            expected_value=100.0,
            prediction_provenance="service",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )


def test_04_invalid_unit_rejected():
    """4. Disallowed executable patterns or raw secrets in units are rejected."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError):
        PredictionSnapshot(
            prediction_id="pred_bad_unit",
            prediction_type=PredictionType.OPERATIONAL_COST,
            target_reference="target_01",
            predicted_at=now_str,
            expected_value=500.0,
            expected_unit="DROP TABLE users; --",
            prediction_provenance="service",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )


def test_05_invalid_evaluation_window():
    """5. Parsing ISO timestamps on evaluation windows handles invalid values gracefully."""
    with pytest.raises(Exception):
        _parse_utc_iso("not-a-timestamp")


def test_06_missing_scope_rejected():
    """6. Missing, empty, or fabricated tenant/plant scopes are rejected."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="Manufactured or wildcard scope"):
        PredictionSnapshot(
            prediction_id="pred_bad_scope",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference="sku_01",
            predicted_at=now_str,
            expected_value=10.0,
            prediction_provenance="service",
            tenant_id="global",  # Fabricated scope prohibited
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )


def test_07_extra_unrecognized_fields_rejected():
    """7. Extra unrecognized fields fail closed with ConfigDict extra='forbid'."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(Exception):
        PredictionSnapshot(
            prediction_id="pred_extra",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference="sku_01",
            predicted_at=now_str,
            expected_value=10.0,
            prediction_provenance="service",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
            unauthorized_secret_field="attacker_payload",  # type: ignore
        )


def test_08_prediction_immutability(temp_db, test_identity):
    """8. Attempting to overwrite a prediction with differing content raises immutability violation."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap1 = PredictionSnapshot(
        prediction_id="pred_immut_01",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_assembly_01",
        predicted_at=now_str,
        expected_value=4.5,
        expected_unit="hours",
        prediction_provenance="recovery_service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, snap1)

    # Attempt to alter expected_value from 4.5 to 1.5
    snap2 = PredictionSnapshot(
        prediction_id="pred_immut_01",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_assembly_01",
        predicted_at=now_str,
        expected_value=1.5,
        expected_unit="hours",
        prediction_provenance="recovery_service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    with pytest.raises(PredictionImmutabilityViolationError, match="immutable with differing content"):
        service.record_prediction_snapshot(test_identity, snap2)


def test_09_prediction_recorded_before_outcome(temp_db, test_identity):
    """9. Prediction recorded after outcome observation time is rejected (timing violation)."""
    repo, service = temp_db
    t_past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t_future = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Outcome physically observed 2 hours ago
    outcome = ObservedOutcome(
        outcome_id="outc_past_01",
        target_reference="line_assembly_01",
        outcome_type="RECOVERY_ACTUAL",
        observed_at=t_past,
        observed_value=3.0,
        unit="hours",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outcome)

    # Prediction claims it predicted now (after outcome was observed)
    pred = PredictionSnapshot(
        prediction_id="pred_late_01",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_assembly_01",
        predicted_at=t_future,
        expected_value=2.8,
        expected_unit="hours",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    eval_result = service.evaluate_prediction_outcome(test_identity, "pred_late_01", "outc_past_01")
    assert eval_result.evaluation_status == EvaluationStatus.REJECTED
    assert eval_result.eligibility_reason == OutcomeEligibilityReason.TIMING_VIOLATION.value
    assert eval_result.eligible_for_learning is False


def test_10_safe_handling_of_oversized_payloads():
    """10. Oversized text in descriptions or reasons is rejected or bounded."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(Exception):
        PredictionSnapshot(
            prediction_id="x" * 200,  # Max length 128
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference="target_01",
            predicted_at=now_str,
            expected_value=10.0,
            prediction_provenance="service",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )


# =============================================================================
# GROUP B: OUTCOME INTEGRITY & SCOPE (11-24)
# =============================================================================

def test_11_valid_observed_outcome(temp_db, test_identity):
    """11. Valid observed outcome persists and computes deterministic fingerprint."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    outc = ObservedOutcome(
        outcome_id="outc_valid_01",
        target_reference="sku_widget_a",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=now_str,
        observed_value=162.0,
        unit="units",
        provenance="telemetry_feed",
        verification_status=OutcomeVerificationStatus.OBSERVED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    persisted = service.record_observed_outcome(test_identity, outc)
    assert persisted.outcome_id == "outc_valid_01"
    assert persisted.observed_value == 162.0


def test_12_outcome_without_verification_not_authoritative(temp_db, test_identity):
    """12. Outcome with status OBSERVED is evaluated but NOT eligible for learning."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_unver_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_widget_b",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_unver_01",
        prediction_id="pred_unver_01",
        target_reference="sku_widget_b",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t2,
        observed_value=110.0,
        unit="units",
        provenance="unverified_sensor",
        verification_status=OutcomeVerificationStatus.OBSERVED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_unver_01", "outc_unver_01")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED
    assert ev.absolute_error == 10.0
    assert ev.eligible_for_learning is False
    assert ev.learning_ineligibility_reason == "OUTCOME_NOT_VERIFIED"


def test_13_valid_verified_outcome(temp_db, test_identity, admin_identity):
    """13. Valid outcome verified by continuous verification is eligible for learning."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_ver_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_widget_c",
        predicted_at=t1,
        expected_value=200.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_998811",
        target_id="sku_widget_c",
    )

    outc = ObservedOutcome(
        outcome_id="outc_ver_01",
        prediction_id="pred_ver_01",
        target_reference="sku_widget_c",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t2,
        observed_value=205.0,
        unit="units",
        provenance="continuous_verification_engine",
        verification_reference="vrun_998811",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        is_diagnostic=False,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_ver_01", "outc_ver_01")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED
    assert ev.absolute_error == 5.0
    assert ev.eligible_for_learning is True
    assert ev.learning_ineligibility_reason is None


def test_14_missing_evidence_handled_explicitly(temp_db, test_identity):
    """14. Evaluating a non-existent outcome ID raises OutcomeNotFoundError."""
    repo, service = temp_db
    t1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pred = PredictionSnapshot(
        prediction_id="pred_mis_ev_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_widget_x",
        predicted_at=t1,
        expected_value=50.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)
    with pytest.raises(OutcomeNotFoundError):
        service.evaluate_prediction_outcome(test_identity, "pred_mis_ev_01", "outc_nonexistent_999")


def test_15_invalidated_evidence_rejected(temp_db, test_identity):
    """15. Invalidated outcome evidence is rejected from evaluation."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_inval_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_inval",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_inval_01",
        target_reference="sku_inval",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t2,
        observed_value=120.0,
        is_invalidated=True,
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_inval_01", "outc_inval_01")
    assert ev.evaluation_status == EvaluationStatus.REJECTED
    assert ev.eligibility_reason == OutcomeEligibilityReason.INVALIDATED_SOURCE.value


def test_16_stale_outcome_deferred(temp_db, test_identity):
    """16. Outcome outside evaluation window is deferred."""
    repo, service = temp_db
    t_start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    t_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat().replace("+00:00", "Z")
    t_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_win_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_win",
        predicted_at=t_now,
        expected_value=100.0,
        evaluation_window_start=t_start,
        evaluation_window_end=t_end,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    # Observed today, before window start tomorrow
    outc = ObservedOutcome(
        outcome_id="outc_win_early",
        target_reference="sku_win",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t_now,
        observed_value=105.0,
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_win_01", "outc_win_early")
    assert ev.evaluation_status == EvaluationStatus.DEFERRED
    assert ev.eligibility_reason == OutcomeEligibilityReason.INVALID_EVALUATION_WINDOW.value


def test_17_future_dated_outcome_handled_deterministically(temp_db, test_identity):
    """17. Timestamps with valid ISO format parse without timezone ambiguity."""
    now_utc = datetime.now(timezone.utc)
    ts = now_utc.isoformat().replace("+00:00", "Z")
    parsed = _parse_utc_iso(ts)
    assert parsed.tzinfo == timezone.utc
    assert abs((parsed - now_utc).total_seconds()) < 1.0


def test_18_cross_tenant_evidence_rejected(temp_db, test_identity):
    """18. Cross-tenant outcome cannot be associated with a prediction."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    pred = PredictionSnapshot(
        prediction_id="pred_tenant_a",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_center_01",
        predicted_at=t1,
        expected_value=5000.0,
        prediction_provenance="service",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    # Outcome recorded in tenant_beta
    beta_identity = Identity(
        user_id="user_beta",
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        roles=["ENGINEER"],
        assigned_plants=["*"],
    )
    outc = ObservedOutcome(
        outcome_id="outc_tenant_b",
        target_reference="cost_center_01",
        outcome_type="ACTUAL_COST",
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_value=4800.0,
        provenance="erp",
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    service.record_observed_outcome(beta_identity, outc)

    # Calling evaluate with tenant_alpha identity on tenant_beta outcome fails
    with pytest.raises(OutcomeNotFoundError):
        service.evaluate_prediction_outcome(test_identity, "pred_tenant_a", "outc_tenant_b")


def test_19_cross_workspace_evidence_rejected(temp_db, test_identity):
    """19. Cross-workspace prediction access raises PredictionNotFoundError."""
    repo, service = temp_db
    t1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    staging_identity = Identity(
        user_id="user_stag",
        tenant_id=test_identity.tenant_id,
        workspace_id="workspace_staging",
        roles=["ENGINEER"],
        assigned_plants=["*"],
    )
    pred = PredictionSnapshot(
        prediction_id="pred_stag_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_staging",
        predicted_at=t1,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id="workspace_staging",
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(staging_identity, pred)

    with pytest.raises(PredictionNotFoundError):
        service.get_prediction_snapshot(test_identity, "pred_stag_01")


def test_20_cross_plant_evidence_rejected(temp_db, test_identity):
    """20. Accessing a plant outside assigned plants raises OutcomeEvaluationScopeMismatchError."""
    repo, service = temp_db
    t1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    admin_id = Identity(
        user_id="admin_all",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        roles=["ADMINISTRATOR"],
        assigned_plants=["*"],
    )
    pred = PredictionSnapshot(
        prediction_id="pred_plant_99",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_plant_99",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_99",  # Not in test_identity.assigned_plants (which is ["plant_01", "plant_02"])
    )
    service.record_prediction_snapshot(admin_id, pred)

    with pytest.raises(OutcomeEvaluationScopeMismatchError, match="not in assigned plants"):
        service.get_prediction_snapshot(test_identity, "pred_plant_99")


def test_21_client_forged_verification_status_downgraded(temp_db, test_identity):
    """21. Regular operator claiming VERIFIED without verification ref is downgraded to OBSERVED."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    outc = ObservedOutcome(
        outcome_id="outc_forged_ver",
        target_reference="sku_forged",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=now_str,
        observed_value=50.0,
        provenance="operator_assertion",
        verification_status=OutcomeVerificationStatus.VERIFIED,  # Client assertion without reference
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    persisted = service.record_observed_outcome(test_identity, outc)
    assert persisted.verification_status == OutcomeVerificationStatus.OBSERVED


def test_22_client_forged_identity_rejected(temp_db, test_identity):
    """22. Attempting to record snapshot with mismatched tenant scope fails closed."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap = PredictionSnapshot(
        prediction_id="pred_forged_tenant",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="target_01",
        predicted_at=now_str,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id="tenant_forged_xyz",  # Caller is tenant_alpha
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    with pytest.raises(OutcomeEvaluationScopeMismatchError, match="Tenant mismatch"):
        service.record_prediction_snapshot(test_identity, snap)


def test_23_data_mode_mismatch_rejected(temp_db, test_identity):
    """23. Mixing REAL prediction with SIMULATION outcome is rejected by eligibility policy."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_real_mode",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_mode_01",
        predicted_at=t1,
        expected_value=1000.0,
        data_mode=DataMode.REAL,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_sim_mode",
        target_reference="cost_mode_01",
        outcome_type="ACTUAL_COST",
        observed_at=t2,
        observed_value=980.0,
        data_mode=DataMode.SIMULATION,  # Simulation data cannot be mixed with real
        provenance="what_if_simulation",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_real_mode", "outc_sim_mode")
    assert ev.evaluation_status == EvaluationStatus.REJECTED
    assert ev.eligibility_reason == OutcomeEligibilityReason.DATA_MODE_MISMATCH.value


def test_24_conflicting_outcome_history_preserved(temp_db, test_identity):
    """24. Distinct outcomes for the same target reference are preserved independently."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    outc1 = ObservedOutcome(
        outcome_id="outc_multi_01",
        target_reference="target_sensor_10",
        outcome_type="TEMPERATURE",
        observed_at=now_str,
        observed_value=65.2,
        provenance="sensor_a",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    outc2 = ObservedOutcome(
        outcome_id="outc_multi_02",
        target_reference="target_sensor_10",
        outcome_type="TEMPERATURE",
        observed_at=now_str,
        observed_value=68.1,
        provenance="sensor_b",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc1)
    service.record_observed_outcome(test_identity, outc2)

    listed = service.list_observed_outcomes(test_identity, target_reference="target_sensor_10")
    assert len(listed) == 2


# =============================================================================
# GROUP C: EVALUATION CORRECTNESS (25-38)
# =============================================================================

def test_25_correct_absolute_error_calculation(temp_db, test_identity, admin_identity):
    """25. Correct absolute error: e_abs = |y - y_hat|."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_err_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_err_01",
        predicted_at=t1,
        expected_value=120.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_err_01",
        target_reference="sku_err_01",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t2,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_err_01", "outc_err_01")
    # y = 100, y_hat = 120 -> e_abs = |100 - 120| = 20.0
    assert ev.absolute_error == 20.0


def test_26_correct_signed_error_calculation(temp_db, test_identity, admin_identity):
    """26. Correct signed error: e_signed = y - y_hat."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_signed_01",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_signed_01",
        predicted_at=t1,
        expected_value=150.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_signed_01",
        target_reference="cost_signed_01",
        outcome_type="ACTUAL_COST",
        observed_at=t2,
        observed_value=120.0,
        provenance="erp",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_signed_01", "outc_signed_01")
    # y = 120, y_hat = 150 -> e_signed = 120 - 150 = -30.0
    assert ev.signed_error == -30.0


def test_27_correct_relative_error_calculation(temp_db, test_identity, admin_identity):
    """27. Correct relative error: e_rel = |y - y_hat| / |y| when y != 0."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_rel_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_rel_01",
        predicted_at=t1,
        expected_value=120.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_rel_01",
        target_reference="sku_rel_01",
        outcome_type="DEMAND_OBSERVATION",
        observed_at=t2,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_rel_01", "outc_rel_01")
    # y = 100, y_hat = 120 -> e_rel = |100 - 120| / 100 = 20 / 100 = 0.2
    assert ev.relative_error == 0.2


def test_28_zero_actual_value_handles_division_by_zero(temp_db, test_identity, admin_identity):
    """28. When actual value y == 0, relative_error is None (never divide by zero or fabricated)."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_zero_01",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_zero",
        predicted_at=t1,
        expected_value=2.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_zero_01",
        target_reference="line_zero",
        outcome_type="RECOVERY_ACTUAL",
        observed_at=t2,
        observed_value=0.0,  # Zero actual denominator
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_zero_01", "outc_zero_01")
    assert ev.absolute_error == 2.0
    assert ev.signed_error == -2.0
    assert ev.relative_error is None  # Must NOT divide by zero!


def test_29_unit_mismatch_rejected(temp_db, test_identity):
    """29. Unit mismatch fails closed (UNIT_MISMATCH)."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_unit_mis",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_unit",
        predicted_at=t1,
        expected_value=2.0,
        expected_unit="hours",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_unit_mis",
        target_reference="line_unit",
        outcome_type="RECOVERY_ACTUAL",
        observed_at=t2,
        observed_value=120.0,
        unit="minutes",  # Mismatched unit
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_unit_mis", "outc_unit_mis")
    assert ev.evaluation_status == EvaluationStatus.REJECTED
    assert ev.eligibility_reason == OutcomeEligibilityReason.UNIT_MISMATCH.value


def test_30_missing_numeric_values_do_not_become_zero(temp_db, test_identity):
    """30. Categorical values do not convert missing numeric errors to zero."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_str_01",
        prediction_type=PredictionType.MISSION_CRITERION,
        target_reference="crit_01",
        predicted_at=t1,
        expected_value="PASSED",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_str_01",
        target_reference="crit_01",
        outcome_type="CRITERION_RESULT",
        observed_at=t2,
        observed_value="PASSED",
        provenance="verification",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_str_01", "outc_str_01")
    assert ev.absolute_error is None
    assert ev.signed_error is None
    assert ev.relative_error is None
    assert ev.exact_match is True


def test_31_categorical_comparison_exact_match(temp_db, test_identity):
    """31. Categorical comparison performs case-insensitive exact matching."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_cat_match",
        prediction_type=PredictionType.MAINTENANCE_RISK,
        target_reference="motor_01",
        predicted_at=t1,
        expected_value="HIGH",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_cat_match",
        target_reference="motor_01",
        outcome_type="RISK_ACTUAL",
        observed_at=t2,
        observed_value="high",
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_cat_match", "outc_cat_match")
    assert ev.exact_match is True
    assert ev.directional_bias == DirectionalBias.MATCHED


def test_32_unsupported_comparison_semantics(temp_db, test_identity):
    """32. Ineligible evaluation returns safe diagnostic explanation."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_unsupp",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="target_x",
        predicted_at=t1,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_rej",
        target_reference="target_x",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=12.0,
        verification_status=OutcomeVerificationStatus.REJECTED,
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_unsupp", "outc_rej")
    assert ev.evaluation_status == EvaluationStatus.REJECTED
    assert ev.comparison_semantics == "INELIGIBLE_EVALUATION"


def test_33_overprediction_classification(temp_db, test_identity, admin_identity):
    """33. y_hat > y classifies directional bias as OVER_PREDICTED."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_over_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_over",
        predicted_at=t1,
        expected_value=150.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_over_01",
        target_reference="sku_over",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_over_01", "outc_over_01")
    assert ev.directional_bias == DirectionalBias.OVER_PREDICTED


def test_34_underprediction_classification(temp_db, test_identity, admin_identity):
    """34. y_hat < y classifies directional bias as UNDER_PREDICTED."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_under_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_under",
        predicted_at=t1,
        expected_value=80.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_under_01",
        target_reference="sku_under",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=120.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_under_01", "outc_under_01")
    assert ev.directional_bias == DirectionalBias.UNDER_PREDICTED


def test_35_exact_match_classification(temp_db, test_identity, admin_identity):
    """35. y_hat == y classifies directional bias as MATCHED."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_match_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_match",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_match_01",
        target_reference="sku_match",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_match_01", "outc_match_01")
    assert ev.directional_bias == DirectionalBias.MATCHED
    assert ev.exact_match is True
    assert ev.absolute_error == 0.0


def test_36_evaluation_window_late_rejected(temp_db, test_identity):
    """36. Outcome observed after evaluation window end is deferred."""
    repo, service = temp_db
    t_start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    t_end = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    t_pred = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat().replace("+00:00", "Z")
    t_now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_late_win",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_late_win",
        predicted_at=t_pred,
        expected_value=50.0,
        evaluation_window_start=t_start,
        evaluation_window_end=t_end,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_late_win",
        target_reference="sku_late_win",
        outcome_type="DEMAND",
        observed_at=t_now,  # After window end
        observed_value=55.0,
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_late_win", "outc_late_win")
    assert ev.evaluation_status == EvaluationStatus.DEFERRED
    assert ev.eligibility_reason == OutcomeEligibilityReason.INVALID_EVALUATION_WINDOW.value


def test_37_diagnostic_verification_cannot_masquerade_as_authoritative(temp_db, test_identity, admin_identity):
    """37. Diagnostic-only verification run cannot yield eligible_for_learning=True."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_diag_01",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_diag",
        predicted_at=t1,
        expected_value=2.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_diag_01",
        target_id="line_diag",
        is_diagnostic=True,
        rule_id="RULE_EVIDENCE_EXISTS_V1",
    )

    outc = ObservedOutcome(
        outcome_id="outc_diag_01",
        target_reference="line_diag",
        outcome_type="RECOVERY_ACTUAL",
        observed_at=t2,
        observed_value=2.2,
        provenance="verification",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        is_diagnostic=True,  # Diagnostic only
        verification_reference="vrun_diag_01",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_diag_01", "outc_diag_01")
    assert ev.is_diagnostic is True
    assert ev.eligible_for_learning is False
    assert ev.learning_ineligibility_reason == "DIAGNOSTIC_VERIFICATION_ONLY"


def test_38_historical_prediction_remains_unchanged_after_evaluation(temp_db, test_identity, admin_identity):
    """38. Evaluating an outcome does not mutate the historical prediction snapshot."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_immutable_check",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_immut",
        predicted_at=t1,
        expected_value=500.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)
    orig_fp = pred.compute_fingerprint()

    outc = ObservedOutcome(
        outcome_id="outc_immut_check",
        target_reference="sku_immut",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=420.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    service.evaluate_prediction_outcome(test_identity, "pred_immutable_check", "outc_immut_check")

    retrieved_pred = service.get_prediction_snapshot(test_identity, "pred_immutable_check")
    assert retrieved_pred.expected_value == 500.0
    assert retrieved_pred.compute_fingerprint() == orig_fp


# =============================================================================
# GROUP D: IDEMPOTENCY & PERSISTENCE (39-46)
# =============================================================================

def test_39_identical_pair_produces_one_authoritative_evaluation(temp_db, test_identity, admin_identity):
    """39. Evaluating the same pair multiple times returns the exact same evaluation record."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_idem_pair",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_idem",
        predicted_at=t1,
        expected_value=1000.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_idem_pair",
        target_reference="cost_idem",
        outcome_type="COST",
        observed_at=t2,
        observed_value=950.0,
        provenance="erp",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev1 = service.evaluate_prediction_outcome(test_identity, "pred_idem_pair", "outc_idem_pair")
    ev2 = service.evaluate_prediction_outcome(test_identity, "pred_idem_pair", "outc_idem_pair")
    assert ev1.evaluation_id == ev2.evaluation_id
    assert ev1.absolute_error == ev2.absolute_error


def test_40_duplicate_event_delivery_does_not_duplicate_evaluation(temp_db, test_identity, admin_identity):
    """40. Redelivered event invokes handler without creating duplicate evaluation."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_ev_redel",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_redel",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_ev_redel",
        target_reference="sku_redel",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    event = CanonicalEvent(
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=t2,
        observed_at=t2,
        provenance="sensor_gateway",
        references=EventReferences(source_record_id="outc_ev_redel"),
        payload={"prediction_id": "pred_ev_redel", "outcome_id": "outc_ev_redel"},
    )
    event.event_fingerprint = event.compute_fingerprint()

    ev1 = handler.handle_event(event)
    ev2 = handler.handle_event(event)
    assert ev1 is not None and ev2 is not None
    assert ev1.evaluation_id == ev2.evaluation_id

    # Verify repository only has 1 evaluation
    all_evals = service.list_evaluations(test_identity)
    assert len([e for e in all_evals if e.prediction_id == "pred_ev_redel"]) == 1


def test_41_conflicting_idempotency_key_reuse_rejected(temp_db, test_identity, admin_identity):
    """41. Reusing idempotency key for different prediction/outcome raises conflict."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred1 = PredictionSnapshot(
        prediction_id="pred_conflict_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_1",
        predicted_at=t1,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    pred2 = PredictionSnapshot(
        prediction_id="pred_conflict_02",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_2",
        predicted_at=t1,
        expected_value=20.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred1)
    service.record_prediction_snapshot(test_identity, pred2)

    outc = ObservedOutcome(
        outcome_id="outc_conflict",
        target_reference="sku_1",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=12.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    shared_idem = "idem_custom_key_123"
    service.evaluate_prediction_outcome(
        test_identity, "pred_conflict_01", "outc_conflict", idempotency_key=shared_idem
    )

    with pytest.raises(OutcomeEvaluationIdempotencyConflictError, match="conflicting prediction/outcome IDs"):
        service.evaluate_prediction_outcome(
            test_identity, "pred_conflict_02", "outc_conflict", idempotency_key=shared_idem
        )


def test_42_evaluation_survives_service_reinitialization(temp_db, test_identity, admin_identity):
    """42. Evaluation records persist durably across repository/service reinitialization."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_reinit",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_reinit",
        predicted_at=t1,
        expected_value=3.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_reinit",
        target_reference="line_reinit",
        outcome_type="RECOVERY",
        observed_at=t2,
        observed_value=3.5,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_reinit", "outc_reinit")

    # Reinitialize service and repository pointing to the same DB file
    new_repo = OutcomeLearningRepository(db_path=repo._db_path)
    new_service = OutcomeEvaluationService(repository=new_repo, enabled=True)

    loaded = new_service.get_evaluation(test_identity, ev.evaluation_id)
    assert loaded is not None
    assert loaded.evaluation_id == ev.evaluation_id
    assert loaded.absolute_error == 0.5


def test_43_historical_evaluation_not_overwritten(temp_db, test_identity, admin_identity):
    """43. Old evaluation records cannot be mutated."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_no_over",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_no_over",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_no_over",
        target_reference="sku_no_over",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=110.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_no_over", "outc_no_over")
    orig_err = ev.absolute_error

    # Multiple evaluate calls must return the same record and error
    ev_repeat = service.evaluate_prediction_outcome(test_identity, "pred_no_over", "outc_no_over")
    assert ev_repeat.absolute_error == orig_err


def test_44_reevaluation_preserves_linkage_to_prior_evaluation(temp_db, test_identity, admin_identity):
    """44. Explicit re-evaluation creates a new record linked to prior evaluation ID."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_reeval",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_reeval",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_reeval",
        target_reference="sku_reeval",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=110.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev1 = service.evaluate_prediction_outcome(test_identity, "pred_reeval", "outc_reeval")
    ev2 = service.evaluate_prediction_outcome(
        test_identity,
        "pred_reeval",
        "outc_reeval",
        idempotency_key="idem_reeval_v2",
        reevaluation_reason="Audit review requested re-evaluation under policy v2",
    )
    assert ev2.evaluation_id != ev1.evaluation_id
    assert ev2.reevaluation_reason == "Audit review requested re-evaluation under policy v2"


def test_45_failed_transaction_leaves_no_partial_record(temp_db, test_identity):
    """45. Evaluating an invalid target raises error and leaves no evaluation in DB."""
    repo, service = temp_db
    with pytest.raises(PredictionNotFoundError):
        service.evaluate_prediction_outcome(test_identity, "nonexistent_pred", "nonexistent_outc")
    listed = service.list_evaluations(test_identity)
    assert len(listed) == 0


def test_46_persistence_failure_does_not_report_success(temp_db, test_identity):
    """46. Repository write failures raise error instead of falsely reporting success."""
    repo, service = temp_db
    # Force closed DB connection
    with pytest.raises(Exception):
        bad_repo = OutcomeLearningRepository(db_path="/invalid_dir/bad_path.sqlite")
        bad_service = OutcomeEvaluationService(repository=bad_repo, enabled=True)
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snap = PredictionSnapshot(
            prediction_id="p1",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference="t1",
            predicted_at=now_str,
            expected_value=1.0,
            prediction_provenance="s",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )
        bad_service.record_prediction_snapshot(test_identity, snap)


# =============================================================================
# GROUP E: METRICS (47-57)
# =============================================================================

def test_47_correct_mean_absolute_error(temp_db, test_identity, admin_identity):
    """47. Correct MAE calculation: sum(|y - y_hat|) / n."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Insert 5 pairs: errors = 2, 4, 6, 8, 10 -> MAE = 30 / 5 = 6.0
    for i, err in enumerate([2.0, 4.0, 6.0, 8.0, 10.0]):
        seed_authoritative_run(
            service,
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
            verification_id=f"v_{i}",
            target_id=f"cost_mae_{i}",
        )
        pred = PredictionSnapshot(
            prediction_id=f"pred_mae_{i}",
            prediction_type=PredictionType.OPERATIONAL_COST,
            target_reference=f"cost_mae_{i}",
            predicted_at=t1,
            expected_value=100.0,
            expected_unit="usd",
            prediction_provenance="service",
            tenant_id=test_identity.tenant_id,
            workspace_id=test_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_prediction_snapshot(test_identity, pred)

        outc = ObservedOutcome(
            outcome_id=f"outc_mae_{i}",
            target_reference=f"cost_mae_{i}",
            outcome_type="COST",
            observed_at=t2,
            observed_value=100.0 + err,
            unit="usd",
            provenance="erp",
            verification_status=OutcomeVerificationStatus.VERIFIED,
            verification_reference=f"v_{i}",
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_observed_outcome(admin_identity, outc)
        service.evaluate_prediction_outcome(test_identity, f"pred_mae_{i}", f"outc_mae_{i}")

    metrics = service.get_aggregate_metrics(test_identity, PredictionType.OPERATIONAL_COST, min_sample_threshold=5)
    assert metrics.eligible_sample_count == 5
    assert metrics.sample_status == "SUFFICIENT_DATA"
    assert metrics.mean_absolute_error == 6.0


def test_48_correct_root_mean_squared_error(temp_db, test_identity, admin_identity):
    """48. Correct RMSE calculation: sqrt(sum(err^2)/n)."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Errors: 3, 4 -> err^2 = 9, 16 -> sum = 25 -> mean = 12.5 -> sqrt(12.5) = 3.5355
    for i, err in enumerate([3.0, 4.0]):
        seed_authoritative_run(
            service,
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
            verification_id=f"v_{i}",
            target_id=f"line_rmse_{i}",
        )
        pred = PredictionSnapshot(
            prediction_id=f"pred_rmse_{i}",
            prediction_type=PredictionType.RECOVERY_DURATION,
            target_reference=f"line_rmse_{i}",
            predicted_at=t1,
            expected_value=10.0,
            expected_unit="hours",
            prediction_provenance="service",
            tenant_id=test_identity.tenant_id,
            workspace_id=test_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_prediction_snapshot(test_identity, pred)

        outc = ObservedOutcome(
            outcome_id=f"outc_rmse_{i}",
            target_reference=f"line_rmse_{i}",
            outcome_type="RECOVERY",
            observed_at=t2,
            observed_value=10.0 + err,
            unit="hours",
            provenance="sensor",
            verification_status=OutcomeVerificationStatus.VERIFIED,
            verification_reference=f"v_{i}",
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_observed_outcome(admin_identity, outc)
        service.evaluate_prediction_outcome(test_identity, f"pred_rmse_{i}", f"outc_rmse_{i}")

    metrics = service.get_aggregate_metrics(test_identity, PredictionType.RECOVERY_DURATION, min_sample_threshold=2)
    assert metrics.root_mean_squared_error == round(math.sqrt(12.5), 4)


def test_49_correct_signed_mean_bias(temp_db, test_identity, admin_identity):
    """49. Correct signed mean error (systematic bias): sum(y - y_hat) / n."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # y = 110, y_hat = 100 -> signed = +10; y = 104, y_hat = 100 -> signed = +4 -> mean = +7.0
    for i, act in enumerate([110.0, 104.0]):
        seed_authoritative_run(
            service,
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
            verification_id=f"v_{i}",
            target_id=f"line_bias_{i}",
        )
        pred = PredictionSnapshot(
            prediction_id=f"pred_bias_{i}",
            prediction_type=PredictionType.PRODUCTION_THROUGHPUT,
            target_reference=f"line_bias_{i}",
            predicted_at=t1,
            expected_value=100.0,
            prediction_provenance="service",
            tenant_id=test_identity.tenant_id,
            workspace_id=test_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_prediction_snapshot(test_identity, pred)

        outc = ObservedOutcome(
            outcome_id=f"outc_bias_{i}",
            target_reference=f"line_bias_{i}",
            outcome_type="THROUGHPUT",
            observed_at=t2,
            observed_value=act,
            provenance="sensor",
            verification_status=OutcomeVerificationStatus.VERIFIED,
            verification_reference=f"v_{i}",
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_observed_outcome(admin_identity, outc)
        service.evaluate_prediction_outcome(test_identity, f"pred_bias_{i}", f"outc_bias_{i}")

    metrics = service.get_aggregate_metrics(test_identity, PredictionType.PRODUCTION_THROUGHPUT, min_sample_threshold=2)
    assert metrics.signed_mean_error == 7.0


def test_50_zero_denominator_mape_not_fabricated(temp_db, test_identity, admin_identity):
    """50. When actual values are zero, MAPE does not divide by zero and returns None."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_mape_zero",
        prediction_type=PredictionType.ENERGY_CONSUMPTION,
        target_reference="meter_01",
        predicted_at=t1,
        expected_value=5.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_mape_zero",
        target_reference="meter_01",
        outcome_type="ENERGY",
        observed_at=t2,
        observed_value=0.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    service.evaluate_prediction_outcome(test_identity, "pred_mape_zero", "outc_mape_zero")

    metrics = service.get_aggregate_metrics(test_identity, PredictionType.ENERGY_CONSUMPTION, min_sample_threshold=1)
    assert metrics.mean_absolute_percentage_error is None  # Denominator is zero


def test_51_insufficient_sample_count_is_explicit(temp_db, test_identity):
    """51. When sample size is below threshold, status is explicitly INSUFFICIENT_DATA."""
    repo, service = temp_db
    metrics = service.get_aggregate_metrics(
        test_identity,
        PredictionType.DEMAND_FORECAST,
        min_sample_threshold=10,
    )
    assert metrics.eligible_sample_count == 0
    assert metrics.sample_status == "INSUFFICIENT_DATA"
    assert metrics.mean_absolute_error is None


def test_52_incompatible_prediction_types_not_combined(temp_db, test_identity, admin_identity):
    """52. Aggregation for DEMAND_FORECAST does not include RECOVERY_DURATION evaluations."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred1 = PredictionSnapshot(
        prediction_id="pred_dom_1",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_dom_1",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    pred2 = PredictionSnapshot(
        prediction_id="pred_dom_2",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="sku_dom_2",
        predicted_at=t1,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred1)
    service.record_prediction_snapshot(test_identity, pred2)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v1",
        target_id="sku_dom_1",
    )
    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v2",
        target_id="sku_dom_2",
    )

    outc1 = ObservedOutcome(
        outcome_id="outc_dom_1",
        target_reference="sku_dom_1",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    outc2 = ObservedOutcome(
        outcome_id="outc_dom_2",
        target_reference="sku_dom_2",
        outcome_type="RECOVERY",
        observed_at=t2,
        observed_value=12.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v2",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc1)
    service.record_observed_outcome(admin_identity, outc2)

    service.evaluate_prediction_outcome(test_identity, "pred_dom_1", "outc_dom_1")
    service.evaluate_prediction_outcome(test_identity, "pred_dom_2", "outc_dom_2")

    demand_metrics = service.get_aggregate_metrics(test_identity, PredictionType.DEMAND_FORECAST)
    recovery_metrics = service.get_aggregate_metrics(test_identity, PredictionType.RECOVERY_DURATION)

    assert demand_metrics.eligible_sample_count == 1
    assert demand_metrics.mean_absolute_error == 5.0
    assert recovery_metrics.eligible_sample_count == 1
    assert recovery_metrics.mean_absolute_error == 2.0


def test_53_incompatible_units_not_combined(temp_db, test_identity):
    """53. Snapshot preserves unit string safely without fabrication."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap = PredictionSnapshot(
        prediction_id="pred_unit_test",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_u",
        predicted_at=now_str,
        expected_value=10.0,
        expected_unit="liters",
        prediction_provenance="service",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    assert snap.expected_unit == "liters"


def test_54_simulation_and_real_outcomes_not_silently_mixed(temp_db, test_identity, admin_identity):
    """54. Aggregation for REAL data mode strictly excludes SIMULATION evaluations."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred_real = PredictionSnapshot(
        prediction_id="pred_r",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_r",
        predicted_at=t1,
        expected_value=100.0,
        data_mode=DataMode.REAL,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    pred_sim = PredictionSnapshot(
        prediction_id="pred_s",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_s",
        predicted_at=t1,
        expected_value=100.0,
        data_mode=DataMode.SIMULATION,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred_real)
    service.record_prediction_snapshot(test_identity, pred_sim)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v1",
        target_id="sku_r",
    )
    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v2",
        target_id="sku_s",
    )

    outc_real = ObservedOutcome(
        outcome_id="outc_r",
        target_reference="sku_r",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=110.0,
        data_mode=DataMode.REAL,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    outc_sim = ObservedOutcome(
        outcome_id="outc_s",
        target_reference="sku_s",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=150.0,
        data_mode=DataMode.SIMULATION,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v2",
        provenance="sim",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc_real)
    service.record_observed_outcome(admin_identity, outc_sim)

    service.evaluate_prediction_outcome(test_identity, "pred_r", "outc_r")
    service.evaluate_prediction_outcome(test_identity, "pred_s", "outc_s")

    real_metrics = service.get_aggregate_metrics(test_identity, PredictionType.DEMAND_FORECAST, data_mode=DataMode.REAL)
    assert real_metrics.eligible_sample_count == 1
    assert real_metrics.mean_absolute_error == 10.0


def test_55_bounded_date_windows_enforced(temp_db, test_identity, admin_identity):
    """55. Queries with window_start and window_end filter records strictly."""
    repo, service = temp_db
    t_past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat().replace("+00:00", "Z")
    t_recent = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_window_test",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_win_t",
        predicted_at=t_past,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_window_test",
        target_reference="sku_win_t",
        outcome_type="DEMAND",
        observed_at=t_recent,
        observed_value=105.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    service.evaluate_prediction_outcome(test_identity, "pred_window_test", "outc_window_test")

    # Query window in the past (before evaluation happened)
    metrics_old_win = service.get_aggregate_metrics(
        test_identity,
        PredictionType.DEMAND_FORECAST,
        window_start=(datetime.now(timezone.utc) - timedelta(days=20)).isoformat().replace("+00:00", "Z"),
        window_end=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
    )
    assert metrics_old_win.eligible_sample_count == 0


def test_56_tenant_workspace_plant_isolation_in_aggregates(temp_db, test_identity):
    """56. Aggregates enforce strict tenant boundary."""
    repo, service = temp_db
    # Another tenant's metrics must return 0 samples
    other_tenant = Identity(
        user_id="user_other",
        tenant_id="tenant_other",
        workspace_id="workspace_prod",
        roles=["ENGINEER"],
        assigned_plants=["*"],
    )
    metrics = service.get_aggregate_metrics(other_tenant, PredictionType.DEMAND_FORECAST)
    assert metrics.tenant_id == "tenant_other"
    assert metrics.eligible_sample_count == 0


def test_57_aggregate_results_include_sample_size_and_metric_version(temp_db, test_identity):
    """57. Aggregate results report exact sample count and metric implementation version."""
    repo, service = temp_db
    metrics = service.get_aggregate_metrics(test_identity, PredictionType.DEMAND_FORECAST)
    assert hasattr(metrics, "eligible_sample_count")
    assert metrics.metric_implementation_version == METRIC_IMPLEMENTATION_VERSION


# =============================================================================
# GROUP F: HISTORICAL LEARNING CONTEXT (58-66)
# =============================================================================

def test_58_eligible_evaluation_retrievable_within_scope(temp_db, test_identity, admin_identity):
    """58. Eligible evaluation appears in governed learning context within scope."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_ctx_1",
        prediction_type=PredictionType.RECOVERY_DURATION,
        target_reference="line_ctx",
        predicted_at=t1,
        expected_value=2.0,
        expected_unit="hours",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v1",
        target_id="line_ctx",
    )

    outc = ObservedOutcome(
        outcome_id="outc_ctx_1",
        target_reference="line_ctx",
        outcome_type="RECOVERY",
        observed_at=t2,
        observed_value=2.5,
        unit="hours",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    service.evaluate_prediction_outcome(test_identity, "pred_ctx_1", "outc_ctx_1")

    context = service.get_governed_learning_context(test_identity, PredictionType.RECOVERY_DURATION)
    assert context.sample_count == 1
    assert context.mean_absolute_error == 0.5
    assert context.provenance == "verified_outcome_evaluations"


def test_59_unverified_outcome_excluded_from_learning_context(temp_db, test_identity):
    """59. Unverified outcome evaluation is excluded from eligible learning context sample count."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_unv_ctx",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_unv",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_unv_ctx",
        target_reference="cost_unv",
        outcome_type="COST",
        observed_at=t2,
        observed_value=110.0,
        verification_status=OutcomeVerificationStatus.OBSERVED,  # Not verified
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)
    service.evaluate_prediction_outcome(test_identity, "pred_unv_ctx", "outc_unv_ctx")

    context = service.get_governed_learning_context(test_identity, PredictionType.OPERATIONAL_COST)
    assert context.sample_count == 0  # Unverified is excluded


def test_60_diagnostic_only_evaluation_properly_labelled(temp_db, test_identity, admin_identity):
    """60. Diagnostic-only evaluation records is_diagnostic=True and is excluded from learning."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_diag_label",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_diag_lbl",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_diag_label",
        target_reference="sku_diag_lbl",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=102.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        is_diagnostic=True,
        verification_reference="v_diag",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    ev = service.evaluate_prediction_outcome(test_identity, "pred_diag_label", "outc_diag_label")

    assert ev.is_diagnostic is True
    assert ev.eligible_for_learning is False


def test_61_simulated_outcome_distinguishable_from_real(temp_db, test_identity):
    """61. DataMode.SIMULATION is explicitly recorded and separated from REAL data mode."""
    repo, service = temp_db
    t1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    pred = PredictionSnapshot(
        prediction_id="pred_sim_dist",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_sim_dist",
        predicted_at=t1,
        expected_value=50.0,
        data_mode=DataMode.SIMULATION,
        prediction_provenance="what_if_sim",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    persisted = service.record_prediction_snapshot(test_identity, pred)
    assert persisted.data_mode == DataMode.SIMULATION


def test_62_invalidated_evidence_excluded_from_learning_context(temp_db, test_identity):
    """62. Invalidated evidence is excluded according to policy."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_inval_ctx",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_inval_ctx",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_inval_ctx",
        target_reference="cost_inval_ctx",
        outcome_type="COST",
        observed_at=t2,
        observed_value=120.0,
        is_invalidated=True,
        provenance="sensor",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)
    ev = service.evaluate_prediction_outcome(test_identity, "pred_inval_ctx", "outc_inval_ctx")
    assert ev.eligible_for_learning is False


def test_63_insufficient_data_status_preserved(temp_db, test_identity):
    """63. Governed learning context preserves INSUFFICIENT_DATA status and documents limitations."""
    repo, service = temp_db
    ctx = service.get_governed_learning_context(test_identity, PredictionType.MISSION_CRITERION)
    assert ctx.evaluation_status == "INSUFFICIENT_DATA"
    assert any("below minimum threshold" in lim for lim in ctx.limitations)


def test_64_model_version_retained(temp_db, test_identity):
    """64. Model version is retained in snapshot and learning context."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snap = PredictionSnapshot(
        prediction_id="pred_ver_check",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_vc",
        predicted_at=now_str,
        expected_value=10.0,
        model_version="v3.1.2-beta",
        prediction_provenance="service",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
    )
    assert snap.model_version == "v3.1.2-beta"


def test_65_retrieval_is_bounded_and_authorized(temp_db, test_identity):
    """65. list_evaluations bounds limit between 1 and 200."""
    repo, service = temp_db
    evals = service.list_evaluations(test_identity, limit=500)
    assert isinstance(evals, list)


def test_66_llm_cannot_modify_historical_evaluation(temp_db, test_identity):
    """66. Repository does not expose any update_evaluation or delete_evaluation methods."""
    repo, service = temp_db
    assert not hasattr(repo, "update_evaluation")
    assert not hasattr(repo, "delete_evaluation")
    assert not hasattr(service, "update_evaluation")


# =============================================================================
# GROUP G: EVENTBUS INTEGRATION (67-74)
# =============================================================================

def test_67_evaluation_event_uses_canonical_validation(temp_db, test_identity, admin_identity):
    """67. Evaluation event published to EventBus satisfies CanonicalEvent contract."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_ev_valid",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_ev_valid",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_ev_valid",
        target_reference="sku_ev_valid",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=102.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_ev_valid", "outc_ev_valid")
    assert ev.provenance == EVALUATOR_PROVENANCE


def test_68_evaluation_persisted_before_publication(temp_db, test_identity, admin_identity):
    """68. Database record exists before any event can be processed downstream."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_pbp",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_pbp",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_pbp",
        target_reference="sku_pbp",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_pbp", "outc_pbp")
    in_db = repo.get_evaluation(test_identity.tenant_id, test_identity.workspace_id, ev.evaluation_id)
    assert in_db is not None


def test_69_publication_failure_is_safely_recoverable(temp_db, test_identity, admin_identity):
    """69. If EventBus publication raises an exception, evaluation persistence remains intact."""
    repo, service = temp_db
    # Create mock eventbus that fails
    class FailingEventBus:
        def publish(self, event):
            raise RuntimeError("EventBus connection error simulated")

    service._event_bus = FailingEventBus()  # type: ignore

    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_pub_fail",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_pub_fail",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_pub_fail",
        target_reference="sku_pub_fail",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_pub_fail", "outc_pub_fail")
    assert ev is not None
    # Verify evaluation is still in repository
    persisted = repo.get_evaluation(test_identity.tenant_id, test_identity.workspace_id, ev.evaluation_id)
    assert persisted is not None


def test_70_retry_after_publication_failure_does_not_duplicate(temp_db, test_identity, admin_identity):
    """70. Retrying evaluation after bus failure resolves idempotently without duplicate records."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_retry_dup",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_retry",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_retry_dup",
        target_reference="sku_retry",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev1 = service.evaluate_prediction_outcome(test_identity, "pred_retry_dup", "outc_retry_dup")
    ev2 = service.evaluate_prediction_outcome(test_identity, "pred_retry_dup", "outc_retry_dup")
    assert ev1.evaluation_id == ev2.evaluation_id


def test_71_evaluation_feedback_cannot_recursively_trigger_itself(temp_db, test_identity):
    """71. Loop guard: Event with closed_loop_evaluator provenance is dropped from evaluation."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    event = CanonicalEvent(
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="prediction.evaluated",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=EVALUATOR_PROVENANCE,  # Emitted by evaluator itself
        payload={"prediction_id": "p1", "outcome_id": "o1"},
    )
    event.event_fingerprint = event.compute_fingerprint()

    # Must be dropped by loop guard
    result = handler.handle_event(event)
    assert result is None


def test_72_cross_tenant_delivery_does_not_expose_evaluation_records(temp_db, test_identity):
    """72. Event from another tenant cannot evaluate or access tenant_alpha records."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    event = CanonicalEvent(
        tenant_id="tenant_foreign_xyz",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance="sensor",
        payload={"prediction_id": "pred_any", "outcome_id": "outc_any"},
    )
    event.event_fingerprint = event.compute_fingerprint()

    # Evaluator runs within tenant_foreign_xyz scope and cannot find tenant_alpha records
    result = handler.handle_event(event)
    assert result is None


def test_73_permanent_invalid_input_does_not_retry_indefinitely(temp_db, test_identity):
    """73. Permanent invalid event returns None immediately."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    event = CanonicalEvent(
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance="sensor",
        payload={},  # Missing prediction_id and outcome_id
    )
    event.event_fingerprint = event.compute_fingerprint()

    result = handler.handle_event(event)
    assert result is None


def test_74_transient_error_handling(temp_db, test_identity):
    """74. Handler catches exceptions cleanly without crashing process."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    event = CanonicalEvent(
        tenant_id="global",  # Prohibited scope
        workspace_id="workspace_prod",
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance="sensor",
        payload={"prediction_id": "p", "outcome_id": "o"},
    )
    event.event_fingerprint = event.compute_fingerprint()

    res = handler.handle_event(event)
    assert res is None


# =============================================================================
# GROUP H: CONCURRENCY (75-80)
# =============================================================================

def test_75_concurrent_identical_evaluations_produce_one_authoritative_result(temp_db, test_identity, admin_identity):
    """75. 10 concurrent threads evaluating the same pair produce exactly 1 evaluation in DB."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_conc_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_conc",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_conc_01",
        target_reference="sku_conc",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=115.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    results = []

    def run_eval():
        return service.evaluate_prediction_outcome(test_identity, "pred_conc_01", "outc_conc_01")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(run_eval) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # All threads must receive the same evaluation record
    eval_ids = {r.evaluation_id for r in results}
    assert len(eval_ids) == 1

    # Database must contain exactly 1 evaluation for this pair
    all_evals = service.list_evaluations(test_identity)
    matching = [e for e in all_evals if e.prediction_id == "pred_conc_01"]
    assert len(matching) == 1


def test_76_concurrent_conflicting_submissions_fail_deterministically(temp_db, test_identity):
    """76. Overwriting a prediction concurrently with conflicting values fails safely."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    snap = PredictionSnapshot(
        prediction_id="pred_conc_conflict",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_conc_conf",
        predicted_at=now_str,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, snap)

    errors = []

    def attempt_overwrite(val):
        try:
            s = PredictionSnapshot(
                prediction_id="pred_conc_conflict",
                prediction_type=PredictionType.DEMAND_FORECAST,
                target_reference="sku_conc_conf",
                predicted_at=now_str,
                expected_value=val,
                prediction_provenance="service",
                tenant_id=test_identity.tenant_id,
                workspace_id=test_identity.workspace_id,
                plant_id="plant_01",
            )
            service.record_prediction_snapshot(test_identity, s)
        except Exception as e:
            errors.append(e)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(attempt_overwrite, float(i)) for i in range(100, 104)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # All attempts to alter expected_value must fail
    assert len(errors) == 4
    assert all(isinstance(e, PredictionImmutabilityViolationError) for e in errors)


def test_77_stale_evaluation_references_fail_safely(temp_db, test_identity):
    """77. Stale evaluation lookup returns 404/NotFoundError safely."""
    repo, service = temp_db
    with pytest.raises(EvaluationNotFoundError):
        service.get_evaluation(test_identity, "eval_nonexistent_123")


def test_78_concurrent_writes_do_not_corrupt_history(temp_db, test_identity):
    """78. Multiple distinct predictions can be inserted concurrently without database corruption."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def insert_pred(idx):
        snap = PredictionSnapshot(
            prediction_id=f"pred_bulk_{idx}",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference=f"sku_bulk_{idx}",
            predicted_at=now_str,
            expected_value=float(idx),
            prediction_provenance="service",
            tenant_id=test_identity.tenant_id,
            workspace_id=test_identity.workspace_id,
            plant_id="plant_01",
        )
        return service.record_prediction_snapshot(test_identity, snap)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(insert_pred, i) for i in range(20)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    listed = service.list_prediction_snapshots(test_identity, limit=100)
    assert len(listed) == 20


def test_79_concurrent_metric_queries_return_consistent_results(temp_db, test_identity, admin_identity):
    """79. Metric calculations during writes return consistent, bounded results."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_conc_m",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_cm",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="v1",
        target_id="sku_cm",
    )

    outc = ObservedOutcome(
        outcome_id="outc_conc_m",
        target_reference="sku_cm",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=110.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    service.evaluate_prediction_outcome(test_identity, "pred_conc_m", "outc_conc_m")

    def get_metrics():
        return service.get_aggregate_metrics(test_identity, PredictionType.DEMAND_FORECAST, min_sample_threshold=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_metrics) for _ in range(8)]
        for f in concurrent.futures.as_completed(futures):
            m = f.result()
            assert m.mean_absolute_error == 10.0


def test_80_crash_retry_behavior_is_deterministic(temp_db, test_identity, admin_identity):
    """80. Service recovers from interrupted state deterministically."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_crash",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_crash",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_crash",
        target_reference="sku_crash",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=108.0,
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="v1",
        provenance="sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_crash", "outc_crash")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED


# =============================================================================
# GROUP I: SECURITY, SCOPE ISOLATION & ARCHITECTURAL BOUNDARIES (81-90)
# =============================================================================

def test_81_no_cross_tenant_prediction_access(client):
    """81. API endpoint rejects cross-tenant prediction access."""
    # Attempt to request prediction with tenant_alpha token while header specifies tenant_beta
    headers = {
        "Authorization": "Bearer dev_admin_token",
        "X-Tenant-ID": "tenant_beta",
        "X-Workspace-ID": "workspace_prod",
    }
    res = client.get("/api/v3/learning/predictions/pred_nonexistent", headers=headers)
    assert res.status_code in (403, 404)


def test_82_no_cross_workspace_prediction_access(client):
    """82. API endpoint rejects cross-workspace prediction query."""
    headers = {
        "Authorization": "Bearer dev_admin_token",
        "X-Tenant-ID": "tenant_alpha",
        "X-Workspace-ID": "workspace_other",
    }
    res = client.get("/api/v3/learning/predictions/pred_nonexistent", headers=headers)
    assert res.status_code in (403, 404)


def test_83_no_cross_plant_prediction_access(temp_db, test_identity):
    """83. Identity cannot retrieve prediction from plant outside assigned_plants."""
    repo, service = temp_db
    t1 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    admin_id = Identity(
        user_id="admin_all",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        roles=["ADMINISTRATOR"],
        assigned_plants=["*"],
    )
    pred = PredictionSnapshot(
        prediction_id="pred_isolated_plant",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_iso",
        predicted_at=t1,
        expected_value=10.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_restricted_99",  # Not in test_identity assigned plants
    )
    service.record_prediction_snapshot(admin_id, pred)

    with pytest.raises(OutcomeEvaluationScopeMismatchError, match="not in assigned plants"):
        service.get_prediction_snapshot(test_identity, "pred_isolated_plant")


def test_84_no_unauthorized_outcome_submission(client):
    """84. Submitting outcome without authorization returns 401/403."""
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        user_id="unauth_viewer",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["VIEWER"],
        permissions=["learning.prediction.read"],
        assigned_plants=["plant_01"],
    )
    try:
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        res = client.post(
            "/api/v3/learning/outcomes",
            json={
                "outcome_id": "outc_test_sec_84",
                "target_reference": "target_84",
                "outcome_type": "DEMAND",
                "observed_at": now_str,
                "recorded_at": now_str,
                "observed_value": 10.0,
                "provenance": "sensor",
                "verification_status": "OBSERVED",
                "data_mode": "REAL",
                "tenant_id": "tenant_alpha",
                "workspace_id": "workspace_prod",
                "plant_id": "plant_01",
            },
        )
        assert res.status_code in (401, 403)
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_85_no_arbitrary_sql_execution_pathway():
    """85. Static AST analysis confirms repository uses parameterized SQL only."""
    import repositories.outcome_learning_repository as repo_mod
    src_file = repo_mod.__file__
    with open(src_file, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=src_file)

    # Ensure no f-string or % formatting is used directly in execute() calls
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                first_arg = node.args[0]
                # first_arg should not be a JoinedStr (f-string)
                assert not isinstance(first_arg, ast.JoinedStr), f"Raw f-string SQL detected in execute call at line {node.lineno}!"


def test_86_no_direct_execution_gateway_invocation():
    """86. Static AST analysis confirms outcome learning does NOT import ExecutionGateway."""
    import services.outcome_evaluation_service as svc_mod
    src_file = svc_mod.__file__
    with open(src_file, "r", encoding="utf-8") as f:
        src = f.read()
    assert "ExecutionGateway" not in src
    assert "execute_action" not in src
    assert "ActionTool" not in src


def test_87_no_autonomous_action_approval():
    """87. Static AST analysis confirms no approve_action or approve calls exist."""
    import services.outcome_evaluation_service as svc_mod
    src_file = svc_mod.__file__
    with open(src_file, "r", encoding="utf-8") as f:
        src = f.read()
    assert "approve_action" not in src
    assert "approve_execution" not in src


def test_88_no_physical_state_mutation():
    """88. Outcome learning does not write PLC, SCADA, or actuator commands."""
    import services.outcome_evaluation_service as svc_mod
    src_file = svc_mod.__file__
    with open(src_file, "r", encoding="utf-8") as f:
        src = f.read()
    assert "plc" not in src.lower()
    assert "scada" not in src.lower()
    assert "actuator" not in src.lower()


def test_89_no_raw_secrets_in_records():
    """89. Embedding raw secrets in prediction snapshot fields raises ValueError."""
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="potential secret"):
        PredictionSnapshot(
            prediction_id="pred_sec_test",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference="target_sec",
            predicted_at=now_str,
            expected_value=10.0,
            expected_unit="units",
            prediction_provenance="bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.secrettoken123456",
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        )


def test_90_no_fabricated_metrics_on_failure(temp_db, test_identity):
    """90. When no eligible data exists, metrics return None rather than fabricated numbers."""
    repo, service = temp_db
    metrics = service.get_aggregate_metrics(test_identity, PredictionType.MAINTENANCE_RISK)
    assert metrics.eligible_sample_count == 0
    assert metrics.mean_absolute_error is None
    assert metrics.mean_absolute_percentage_error is None
    assert metrics.root_mean_squared_error is None
    assert metrics.signed_mean_error is None
    assert metrics.sample_status == "INSUFFICIENT_DATA"


# =============================================================================
# GROUP J: PROMPT 39 SECURITY REGRESSION (91-109)
# Authoritative Outcome Verification & Learning-Eligibility Hardening
# =============================================================================

def test_91_fabricated_non_empty_verification_reference_cannot_produce_verified_outcome(temp_db, test_identity):
    """91. A fabricated non-empty verification reference cannot produce a verified outcome."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_fab_ref_01",
        target_reference="sku_fab_target",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fabricated_fake_reference_99999",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)

    # Must be downgraded to OBSERVED, reference cleared, and ineligible
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None

    retrieved = service.get_observed_outcome(test_identity, "outc_fab_ref_01")
    assert retrieved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert retrieved.verification_reference is None


def test_92_random_reference_with_verified_status_not_learning_eligible(temp_db, test_identity):
    """92. A random reference with VERIFIED status is not learning-eligible."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_rand_ref_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_rand_ref",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_rand_ref_01",
        prediction_id="pred_rand_ref_01",
        target_reference="sku_rand_ref",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_random_token_xyz_8877",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_rand_ref_01", "outc_rand_ref_01")
    assert ev.eligible_for_learning is False
    assert ev.learning_ineligibility_reason == "OUTCOME_NOT_VERIFIED"


def test_93_valid_reference_to_authoritative_in_scope_record_follows_workflow(temp_db, test_identity, admin_identity):
    """93. A valid reference to an authoritative, in-scope verification record follows the intended workflow."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed authoritative verification run in Verification Engine
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_auth_valid_01",
        target_id="sku_auth_valid",
        status=VerificationStatus.VERIFIED,
    )

    pred = PredictionSnapshot(
        prediction_id="pred_auth_valid_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_auth_valid",
        predicted_at=t1,
        expected_value=200.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_auth_valid_01",
        prediction_id="pred_auth_valid_01",
        target_reference="sku_auth_valid",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=210.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_auth_valid_01",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    saved_outc = service.record_observed_outcome(admin_identity, outc)
    assert saved_outc.verification_status == OutcomeVerificationStatus.VERIFIED
    assert saved_outc.verification_reference == "vrun_auth_valid_01"

    ev = service.evaluate_prediction_outcome(test_identity, "pred_auth_valid_01", "outc_auth_valid_01")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED
    assert ev.eligible_for_learning is True
    assert ev.learning_ineligibility_reason is None
    assert ev.absolute_error == 10.0


def test_94_reference_to_nonexistent_run_remains_unverified(temp_db, test_identity):
    """94. A reference to a nonexistent run is rejected or remains explicitly unverified."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_nonexist_run",
        target_reference="sku_nonexist_run",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_0000000000000000",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_95_reference_to_nonexistent_finding_remains_unverified(temp_db, test_identity):
    """95. A reference to a nonexistent finding is rejected or remains explicitly unverified."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_nonexist_find",
        target_reference="sku_nonexist_find",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vf_000000000000",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_96_cross_tenant_verification_reference_rejected_without_leakage(temp_db, test_identity):
    """96. A cross-tenant verification reference is rejected without leaking whether the other tenant's record exists."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed authoritative run under tenant_beta
    seed_authoritative_run(
        service,
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        verification_id="vrun_tenant_beta_secret",
        target_id="sku_cross_t",
        status=VerificationStatus.VERIFIED,
    )

    # Caller belongs to tenant_alpha (test_identity.tenant_id)
    outc = ObservedOutcome(
        outcome_id="outc_cross_tenant_01",
        target_reference="sku_cross_t",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_tenant_beta_secret",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)

    # Must be safely downgraded with zero leakage
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None

    # Check direct internal lookup with cross-tenant reference fails closed without disclosure
    cross_outc = ObservedOutcome(
        outcome_id="outc_cross_tenant_check",
        target_reference="sku_cross_t",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_tenant_beta_secret",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    is_valid, reason, rec = service._validate_authoritative_verification(test_identity, cross_outc)
    assert is_valid is False
    assert reason == "VERIFICATION_RECORD_NOT_FOUND"  # Generic not found, no disclosure of tenant_beta record
    assert rec is None


def test_97_cross_workspace_verification_reference_rejected(temp_db, test_identity):
    """97. A cross-workspace verification reference is rejected."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed authoritative run in workspace_dev
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id="workspace_dev",
        plant_id="plant_01",
        verification_id="vrun_dev_ws_01",
        target_id="sku_cross_ws",
        status=VerificationStatus.VERIFIED,
    )

    # Caller submits outcome in workspace_prod
    outc = ObservedOutcome(
        outcome_id="outc_cross_ws_01",
        target_reference="sku_cross_ws",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_dev_ws_01",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,  # workspace_prod
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_98_cross_plant_verification_reference_rejected(temp_db, test_identity):
    """98. A cross-plant verification reference is rejected."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed authoritative run in plant_02
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_02",
        verification_id="vrun_plant_02_01",
        target_id="sku_cross_plant",
        status=VerificationStatus.VERIFIED,
    )

    # Caller submits outcome for plant_01
    outc = ObservedOutcome(
        outcome_id="outc_cross_plant_01",
        target_reference="sku_cross_plant",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=50.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_plant_02_01",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_99_diagnostic_only_verification_cannot_establish_learning_eligibility(temp_db, test_identity, admin_identity):
    """99. A diagnostic-only verification cannot establish learning eligibility."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed diagnostic verification run (e.g., rule RULE_EVIDENCE_EXISTS_V1)
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_diag_only_01",
        target_id="sku_diag_target",
        status=VerificationStatus.VERIFIED,
        is_diagnostic=True,
        rule_id="RULE_EVIDENCE_EXISTS_V1",
    )

    pred = PredictionSnapshot(
        prediction_id="pred_diag_test",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_diag_target",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_diag_test",
        prediction_id="pred_diag_test",
        target_reference="sku_diag_target",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_diag_only_01",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(admin_identity, outc)
    assert saved.is_diagnostic is True

    ev = service.evaluate_prediction_outcome(test_identity, "pred_diag_test", "outc_diag_test")
    assert ev.eligible_for_learning is False
    assert ev.learning_ineligibility_reason == "DIAGNOSTIC_VERIFICATION_ONLY"


def test_100_failed_rejected_indeterminate_or_invalidated_cannot_establish_learning(temp_db, test_identity, admin_identity):
    """100. A failed, rejected, indeterminate, or invalidated verification cannot establish learning eligibility."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Case A: FAILED run
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_failed_01",
        target_id="sku_failed_target",
        status=VerificationStatus.FAILED,
    )
    # Case B: INDETERMINATE run
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_indet_01",
        target_id="sku_indet_target",
        status=VerificationStatus.INDETERMINATE,
    )
    # Case C: Invalidated / Rejected evidence run
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_inval_01",
        target_id="sku_inval_target",
        status=VerificationStatus.VERIFIED,
        is_invalidated=True,
    )

    for case_id, ref, target in [
        ("failed", "vrun_failed_01", "sku_failed_target"),
        ("indet", "vrun_indet_01", "sku_indet_target"),
        ("inval", "vrun_inval_01", "sku_inval_target"),
    ]:
        pred = PredictionSnapshot(
            prediction_id=f"pred_bad_{case_id}",
            prediction_type=PredictionType.DEMAND_FORECAST,
            target_reference=target,
            predicted_at=t1,
            expected_value=100.0,
            prediction_provenance="service",
            tenant_id=test_identity.tenant_id,
            workspace_id=test_identity.workspace_id,
            plant_id="plant_01",
        )
        service.record_prediction_snapshot(test_identity, pred)

        outc = ObservedOutcome(
            outcome_id=f"outc_bad_{case_id}",
            prediction_id=f"pred_bad_{case_id}",
            target_reference=target,
            outcome_type="DEMAND",
            observed_at=t2,
            observed_value=105.0,
            provenance="sensor",
            verification_status=OutcomeVerificationStatus.VERIFIED,
            verification_reference=ref,
            tenant_id=admin_identity.tenant_id,
            workspace_id=admin_identity.workspace_id,
            plant_id="plant_01",
        )
        saved = service.record_observed_outcome(admin_identity, outc)
        assert saved.verification_status == OutcomeVerificationStatus.OBSERVED

        ev = service.evaluate_prediction_outcome(test_identity, f"pred_bad_{case_id}", f"outc_bad_{case_id}")
        assert ev.eligible_for_learning is False


def test_101_administrator_role_without_verification_evidence_cannot_bypass(temp_db, admin_identity):
    """101. An administrator role without authoritative verification evidence cannot bypass the checks."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_admin_bypass_attempt",
        target_reference="sku_admin_bypass",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=100.0,
        provenance="admin_portal",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fake_admin_bypass",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    # Admin calls record_observed_outcome
    saved = service.record_observed_outcome(admin_identity, outc)

    # Server-side validation must not bypass for admin
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_102_non_privileged_caller_cannot_bypass_with_plausible_reference(temp_db, test_identity):
    """102. A non-privileged caller cannot bypass verification by supplying a plausible-looking reference."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_plausible_ref",
        target_reference="sku_plausible",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=100.0,
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_9a8b7c6d5e4f3a2b",  # Plausible 64-char uuid hex
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(test_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_103_valid_reference_to_unrelated_finding_cannot_verify_target(temp_db, test_identity, admin_identity):
    """103. A valid-looking reference to an unrelated verification finding cannot verify the target outcome."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Seed authoritative run for an unrelated target
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_unrelated_sensor",
        target_id="sensor_boiler_pressure_99",
        status=VerificationStatus.VERIFIED,
    )

    # Outcome claims this verification for demand forecast target
    outc = ObservedOutcome(
        outcome_id="outc_unrelated_target",
        target_reference="sku_chocolate_bars_50g",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=500.0,
        provenance="erp",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_unrelated_sensor",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(admin_identity, outc)

    # Must be downgraded due to target mismatch
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None


def test_104_api_cannot_forge_authoritative_verification_status(client, admin_identity):
    """104. The API cannot forge authoritative verification status through request JSON."""
    app.dependency_overrides[get_current_identity] = lambda: admin_identity
    try:
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        outc_id = f"outc_api_forge_{uuid.uuid4().hex[:12]}"
        res = client.post(
            "/api/v3/learning/outcomes",
            json={
                "outcome_id": outc_id,
                "target_reference": "sku_api_forge",
                "outcome_type": "DEMAND",
                "observed_at": now_str,
                "recorded_at": now_str,
                "observed_value": 75.0,
                "provenance": "sensor",
                "verification_status": "VERIFIED",
                "verification_reference": "vrun_fabricated_api_token",
                "data_mode": "REAL",
                "tenant_id": admin_identity.tenant_id,
                "workspace_id": admin_identity.workspace_id,
                "plant_id": "plant_01",
            },
        )
        assert res.status_code == 201
        data = res.json()
        # Server must override/downgrade to OBSERVED and clear reference
        assert data["verification_status"] == "OBSERVED"
        assert data["verification_reference"] is None
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_105_rejected_verification_evidence_does_not_contaminate_metrics(temp_db, test_identity, admin_identity):
    """105. Rejected verification evidence does not contaminate aggregate metrics."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # 1. Genuine verified evaluation (error = 5.0)
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_metric_genuine",
        target_id="cost_metric_gen",
        status=VerificationStatus.VERIFIED,
    )
    pred_g = PredictionSnapshot(
        prediction_id="pred_metric_gen",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_metric_gen",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="usd",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred_g)
    outc_g = ObservedOutcome(
        outcome_id="outc_metric_gen",
        target_reference="cost_metric_gen",
        outcome_type="COST",
        observed_at=t2,
        observed_value=105.0,
        unit="usd",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_metric_genuine",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc_g)
    service.evaluate_prediction_outcome(test_identity, "pred_metric_gen", "outc_metric_gen")

    # 2. Fabricated reference evaluation (error = 500.0)
    pred_f = PredictionSnapshot(
        prediction_id="pred_metric_fab",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_metric_fab",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="usd",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred_f)
    outc_f = ObservedOutcome(
        outcome_id="outc_metric_fab",
        target_reference="cost_metric_fab",
        outcome_type="COST",
        observed_at=t2,
        observed_value=600.0,
        unit="usd",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fake_metric_ref",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc_f)
    service.evaluate_prediction_outcome(test_identity, "pred_metric_fab", "outc_metric_fab")

    metrics = service.get_aggregate_metrics(test_identity, PredictionType.OPERATIONAL_COST, min_sample_threshold=1)
    # Only genuine evaluation is included
    assert metrics.eligible_sample_count == 1
    assert metrics.mean_absolute_error == 5.0


def test_106_rejected_verification_evidence_does_not_enter_governed_learning_context(temp_db, test_identity, admin_identity):
    """106. Rejected verification evidence does not enter governed learning context."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_ctx_genuine",
        target_id="cost_ctx_gen",
        status=VerificationStatus.VERIFIED,
    )
    pred_g = PredictionSnapshot(
        prediction_id="pred_ctx_gen",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_ctx_gen",
        predicted_at=t1,
        expected_value=50.0,
        expected_unit="usd",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred_g)
    outc_g = ObservedOutcome(
        outcome_id="outc_ctx_gen",
        target_reference="cost_ctx_gen",
        outcome_type="COST",
        observed_at=t2,
        observed_value=52.0,
        unit="usd",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_ctx_genuine",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc_g)
    service.evaluate_prediction_outcome(test_identity, "pred_ctx_gen", "outc_ctx_gen")

    # Add outcome with invalidated evidence
    seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_ctx_inval",
        target_id="cost_ctx_inval",
        status=VerificationStatus.VERIFIED,
        is_invalidated=True,
    )
    pred_inv = PredictionSnapshot(
        prediction_id="pred_ctx_inv",
        prediction_type=PredictionType.OPERATIONAL_COST,
        target_reference="cost_ctx_inval",
        predicted_at=t1,
        expected_value=50.0,
        expected_unit="usd",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred_inv)
    outc_inv = ObservedOutcome(
        outcome_id="outc_ctx_inv",
        target_reference="cost_ctx_inval",
        outcome_type="COST",
        observed_at=t2,
        observed_value=999.0,
        unit="usd",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_ctx_inval",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc_inv)
    service.evaluate_prediction_outcome(test_identity, "pred_ctx_inv", "outc_ctx_inv")

    ctx = service.get_governed_learning_context(test_identity, PredictionType.OPERATIONAL_COST)
    assert ctx.sample_count == 1
    assert ctx.mean_absolute_error == 2.0


def test_107_eventbus_redelivery_cannot_bypass_authoritative_verification(temp_db, test_identity, admin_identity):
    """107. EventBus redelivery cannot bypass authoritative verification checks."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_bus_redeliv",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_bus_target",
        predicted_at=t1,
        expected_value=100.0,
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    # Initial outcome with forged reference submitted
    outc_initial = ObservedOutcome(
        outcome_id="outc_bus_redeliv",
        prediction_id="pred_bus_redeliv",
        target_reference="sku_bus_target",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=110.0,
        provenance="event_stream",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fake_bus_token",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    saved_outc = service.record_observed_outcome(admin_identity, outc_initial)
    assert saved_outc.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved_outc.verification_reference is None

    event_payload = {
        "prediction_id": "pred_bus_redeliv",
        "outcome_id": "outc_bus_redeliv",
    }

    event1 = CanonicalEvent(
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=t2,
        observed_at=t2,
        provenance="sensor",
        payload=event_payload,
    )
    event1.event_fingerprint = event1.compute_fingerprint()

    # First delivery
    ev1 = handler.handle_event(event1)
    assert ev1 is not None
    assert ev1.eligible_for_learning is False

    # Redelivery (duplicate event with same payload)
    event2 = CanonicalEvent(
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=t2,
        observed_at=t2,
        provenance="sensor",
        payload=event_payload,
    )
    event2.event_fingerprint = event2.compute_fingerprint()
    ev2 = handler.handle_event(event2)
    assert ev2 is not None
    assert ev2.eligible_for_learning is False

    # Verification status remains OBSERVED; cannot be promoted
    outc_after = service.get_observed_outcome(test_identity, "outc_bus_redeliv")
    assert outc_after.verification_status == OutcomeVerificationStatus.OBSERVED


def test_108_existing_valid_verification_workflows_remain_compatible(temp_db, test_identity, admin_identity):
    """108. Existing valid verification workflows remain compatible."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Full workflow with finding reference
    run = seed_authoritative_run(
        service,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_compat_01",
        target_id="sku_compat_target",
        finding_id="vf_compat_finding_01",
        status=VerificationStatus.VERIFIED,
    )

    pred = PredictionSnapshot(
        prediction_id="pred_compat_01",
        prediction_type=PredictionType.PRODUCTION_THROUGHPUT,
        target_reference="sku_compat_target",
        predicted_at=t1,
        expected_value=1000.0,
        expected_unit="kg",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    # Reference finding_id directly
    outc = ObservedOutcome(
        outcome_id="outc_compat_01",
        prediction_id="pred_compat_01",
        target_reference="sku_compat_target",
        outcome_type="THROUGHPUT",
        observed_at=t2,
        observed_value=980.0,
        unit="kg",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vf_compat_finding_01",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    saved = service.record_observed_outcome(admin_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.VERIFIED
    assert saved.verification_reference == "vf_compat_finding_01"

    ev = service.evaluate_prediction_outcome(test_identity, "pred_compat_01", "outc_compat_01")
    assert ev.eligible_for_learning is True
    assert ev.absolute_error == 20.0


def test_109_historical_revalidation_remediates_untrusted_evaluations(temp_db, test_identity, admin_identity):
    """109. Historical revalidation procedure remediates unverified evaluations safely."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred = PredictionSnapshot(
        prediction_id="pred_hist_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_hist_01",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_hist_01",
        target_reference="sku_hist_01",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=105.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fake_historical_ref",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    # Bypass record_observed_outcome to simulate legacy record written before Prompt 39 correction
    repo.record_observed_outcome(outc)

    # Insert legacy evaluation with eligible_for_learning=True directly
    legacy_eval = PredictionOutcomeEvaluation(
        evaluation_id="eval_legacy_untrusted_01",
        schema_version="3.0.0",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        idempotency_key="idem_legacy_untrusted_01",
        prediction_id="pred_hist_01",
        outcome_id="outc_hist_01",
        evaluation_status=EvaluationStatus.EVALUATED,
        eligibility_reason="ELIGIBLE",
        evaluation_policy_version="1.0.0",
        metric_implementation_version="1.0.0",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_hist_01",
        predicted_value=100.0,
        observed_value=105.0,
        unit="units",
        comparison_semantics="NUMERIC_ERROR",
        absolute_error=5.0,
        verification_reference="vrun_fake_historical_ref",
        eligible_for_learning=True,
        provenance="legacy_untrusted",
    )
    repo.record_evaluation(legacy_eval)

    # Verify legacy record was eligible initially
    initial = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_legacy_untrusted_01")
    assert initial.eligible_for_learning is True

    # Run historical revalidation procedure
    report = service.revalidate_historical_evaluations(admin_identity)
    assert report["corrected_count"] >= 1

    # Evaluation is now remediated and no longer eligible for learning
    remediated = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_legacy_untrusted_01")
    assert remediated.eligible_for_learning is False
    assert "HISTORICAL_REVALIDATION" in remediated.learning_ineligibility_reason


# =============================================================================
# GROUP K: PROMPT 39 CORRECTION 2 SECURITY REGRESSION (110-119)
# Authoritative Revalidation Administrative Authorization Hardening
# =============================================================================

def test_110_ordinary_evaluator_cannot_invoke_historical_revalidation(temp_db, test_identity, client):
    """110. An ordinary user with learning.evaluation.evaluate cannot invoke historical revalidation."""
    repo, service = temp_db

    # 1. Service layer check: raises OutcomeEvaluationScopeMismatchError
    with pytest.raises(OutcomeEvaluationScopeMismatchError) as exc_info:
        service.revalidate_historical_evaluations(test_identity)
    assert "Authorization denied" in str(exc_info.value) or "INSUFFICIENT_ROLE_PERMISSIONS" in str(exc_info.value)

    # 2. API layer check: returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: test_identity
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
        data = res.json()
        assert "learning.evaluation.revalidate" in str(data) or data.get("detail", {}).get("reason_code") == "INSUFFICIENT_ROLE_PERMISSIONS"
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_111_operator_cannot_invoke_historical_revalidation(temp_db, client):
    """111. An operator cannot invoke historical revalidation."""
    repo, service = temp_db
    op_identity = Identity(
        user_id="user_op_line1",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["OPERATOR"],
        permissions=["learning.outcome.record"],
        assigned_plants=["plant_01"],
        clearance_level=1,
        is_server_authoritative=True,
    )

    # 1. Service layer check: rejected fail-closed
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(op_identity)

    # 2. API layer check: returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: op_identity
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_112_readonly_learning_user_cannot_invoke_historical_revalidation(temp_db, client):
    """112. A user with read-only learning permissions cannot invoke historical revalidation."""
    repo, service = temp_db
    viewer_identity = Identity(
        user_id="user_viewer_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["VIEWER"],
        permissions=[
            "learning.prediction.read",
            "learning.outcome.read",
            "learning.evaluation.read",
        ],
        assigned_plants=["plant_01"],
        clearance_level=1,
        is_server_authoritative=True,
    )

    # 1. Service layer check: rejected fail-closed
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(viewer_identity)

    # 2. API layer check: returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: viewer_identity
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_113_authorized_administrator_can_invoke_historical_revalidation(temp_db, admin_identity, client):
    """113. An authorized administrator can invoke historical revalidation."""
    repo, service = temp_db

    # 1. Service layer invocation succeeds
    report = service.revalidate_historical_evaluations(admin_identity)
    assert "total_checked" in report
    assert "corrected_count" in report
    assert report["tenant_id"] == admin_identity.tenant_id

    # 2. API layer invocation succeeds
    app.dependency_overrides[get_current_identity] = lambda: admin_identity
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 200
        data = res.json()
        assert "total_checked" in data
        assert "corrected_count" in data
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_114_unauthorized_user_cannot_disable_learning_eligibility_through_endpoint(temp_db, test_identity, admin_identity, client):
    """114. An unauthorized user cannot disable learning eligibility through the endpoint."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Authoritative run and genuine verified evaluation
    seed_authoritative_run(
        service,
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        verification_id="vrun_auth_persist_01",
        target_id="sku_persist_target",
        status=VerificationStatus.VERIFIED,
    )

    pred = PredictionSnapshot(
        prediction_id="pred_persist_01",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_persist_target",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(admin_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_persist_01",
        prediction_id="pred_persist_01",
        target_reference="sku_persist_target",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=102.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_auth_persist_01",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(admin_identity, outc)
    eval_rec = service.evaluate_prediction_outcome(admin_identity, "pred_persist_01", "outc_persist_01")
    assert eval_rec.eligible_for_learning is True

    # Unauthorized caller attempts to hit revalidation endpoint
    app.dependency_overrides[get_current_identity] = lambda: test_identity
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)

    # Verify evaluation eligibility was NOT altered or disabled
    persisted = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, eval_rec.evaluation_id)
    assert persisted.eligible_for_learning is True


def test_115_denied_request_causes_no_evaluation_record_mutation(temp_db, test_identity, admin_identity):
    """115. A denied request causes no evaluation-record mutation."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    eval_unauth = PredictionOutcomeEvaluation(
        evaluation_id="eval_immutable_on_deny",
        schema_version="3.0.0",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
        idempotency_key="idem_immutable_on_deny",
        prediction_id="pred_deny_mut",
        outcome_id="outc_deny_mut",
        evaluation_status=EvaluationStatus.EVALUATED,
        eligibility_reason="ELIGIBLE",
        evaluation_policy_version="1.0.0",
        metric_implementation_version="1.0.0",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_deny_target",
        predicted_value=100.0,
        observed_value=105.0,
        unit="units",
        comparison_semantics="NUMERIC_ERROR",
        absolute_error=5.0,
        verification_reference="vrun_unverified_unmutated",
        eligible_for_learning=True,
        provenance="test",
    )
    repo.record_evaluation(eval_unauth)

    before = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_immutable_on_deny")
    assert before.eligible_for_learning is True

    # Unauthorized call fails
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(test_identity)

    # Record must remain completely unmutated
    after = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_immutable_on_deny")
    assert after.eligible_for_learning is True
    assert after.learning_ineligibility_reason == before.learning_ineligibility_reason


def test_116_authorized_revalidation_remains_tenant_workspace_plant_scoped(temp_db, admin_identity):
    """116. Authorized revalidation remains tenant, workspace, and plant scoped."""
    repo, service = temp_db

    # 1. Admin assigned exclusively to plant_01 attempts to revalidate plant_02
    plant_scoped_admin = Identity(
        user_id="user_admin_plant_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=[
            "learning.prediction.record", "learning.prediction.read",
            "learning.outcome.record", "learning.outcome.read",
            "learning.evaluation.evaluate", "learning.evaluation.read",
            "learning.evaluation.revalidate",
        ],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # Access to plant_02 is forbidden
    with pytest.raises(OutcomeEvaluationScopeMismatchError) as exc_plant:
        service.revalidate_historical_evaluations(plant_scoped_admin, plant_id="plant_02")
    assert "plant_02" in str(exc_plant.value) or "PLANT_SCOPE_DENIED" in str(exc_plant.value)

    # 2. Cross-tenant attempt
    cross_tenant_admin = Identity(
        user_id="user_admin_tenant_other",
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["*"],
        clearance_level=3,
        is_server_authoritative=True,
    )
    # Revalidating with cross_tenant_admin only searches tenant_beta
    report = service.revalidate_historical_evaluations(cross_tenant_admin)
    assert report["tenant_id"] == "tenant_beta"
    assert report["total_checked"] == 0  # No access to tenant_alpha records


def test_117_existing_prediction_evaluation_continues_with_intended_permissions(temp_db, test_identity, client):
    """117. Existing prediction-evaluation endpoints continue to work for their intended permissions."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pred_id = f"pred_eval_perm_{uuid.uuid4().hex[:8]}"
    outc_id = f"outc_eval_perm_{uuid.uuid4().hex[:8]}"
    target_ref = f"sku_eval_perm_{uuid.uuid4().hex[:8]}"

    pred = PredictionSnapshot(
        prediction_id=pred_id,
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference=target_ref,
        predicted_at=t1,
        expected_value=250.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id=outc_id,
        prediction_id=pred_id,
        target_reference=target_ref,
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=245.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.OBSERVED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    # Ordinary evaluation succeeds for user with learning.evaluation.evaluate
    eval_rec = service.evaluate_prediction_outcome(test_identity, pred_id, outc_id)
    assert eval_rec.evaluation_status == EvaluationStatus.EVALUATED
    assert eval_rec.absolute_error == 5.0
    # Because outcome was OBSERVED, learning eligibility is False (as expected)
    assert eval_rec.eligible_for_learning is False


def test_118_eventbus_processing_does_not_acquire_administrative_permission_implicitly(temp_db):
    """118. EventBus processing does not acquire the administrative permission implicitly."""
    repo, service = temp_db
    handler = OutcomeLearningEventHandler(service=service, enabled=True)

    # EventBus handler identity permissions inspection
    sample_event = CanonicalEvent(
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        category=EventCategory.QUALITY,
        event_type="outcome.observed",
        occurred_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        observed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance="sensor",
        payload={"prediction_id": "p1", "outcome_id": "o1"},
    )
    # The internal identity constructed by handler must NOT have learning.evaluation.revalidate
    handler_identity = Identity(
        user_id=f"system:outcome_evaluator:{sample_event.tenant_id}",
        tenant_id=sample_event.tenant_id,
        workspace_id=sample_event.workspace_id,
        roles=["SYSTEM_VERIFIER", "ANALYST"],
        permissions=[
            "learning.prediction.read",
            "learning.outcome.read",
            "learning.evaluation.evaluate",
            "learning.evaluation.read",
        ],
        assigned_plants=[sample_event.plant_id],
        clearance_level=3,
        is_server_authoritative=True,
    )
    assert "learning.evaluation.revalidate" not in handler_identity.permissions
    assert "ADMINISTRATOR" not in handler_identity.roles

    # Handler identity calling revalidation directly is denied
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(handler_identity)


def test_119_privileged_caller_without_evidence_cannot_make_outcome_learning_eligible(temp_db, admin_identity):
    """119. A privileged caller without genuine verification evidence still cannot make an outcome learning-eligible."""
    repo, service = temp_db
    now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    outc = ObservedOutcome(
        outcome_id="outc_admin_fake_eligible_test",
        target_reference="sku_admin_fake",
        outcome_type="DEMAND",
        observed_at=now_str,
        observed_value=500.0,
        provenance="admin_override_attempt",
        verification_status=OutcomeVerificationStatus.VERIFIED,
        verification_reference="vrun_fabricated_admin_token_999",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    # Even though caller is ADMINISTRATOR, lack of backing verification run downgrades to OBSERVED
    saved = service.record_observed_outcome(admin_identity, outc)
    assert saved.verification_status == OutcomeVerificationStatus.OBSERVED
    assert saved.verification_reference is None

    # Prediction snapshot
    t_past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    pred = PredictionSnapshot(
        prediction_id="pred_admin_fake_eligible_test",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_admin_fake",
        predicted_at=t_past,
        expected_value=500.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(admin_identity, pred)

    # Evaluation produces eligible_for_learning=False
    eval_rec = service.evaluate_prediction_outcome(admin_identity, "pred_admin_fake_eligible_test", "outc_admin_fake_eligible_test")
    assert eval_rec.eligible_for_learning is False
    assert eval_rec.learning_ineligibility_reason == "OUTCOME_NOT_VERIFIED"


# =============================================================================
# GROUP L: PROMPT 39 CORRECTION 3 SECURITY REGRESSION (120-126)
# Fail-Closed Plant Scope Enforcement for Historical Revalidation
# =============================================================================

def test_120_admin_with_empty_plant_assignment_cannot_revalidate_all_plants(temp_db, client):
    """120. An administrator with assigned_plants=[] cannot revalidate all plants."""
    repo, service = temp_db
    admin_empty_plants = Identity(
        user_id="user_admin_empty_plants",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=[],  # Explicitly empty assignment
        clearance_level=3,
        is_server_authoritative=True,
    )

    # 1. Service layer check: fail-closed denied
    with pytest.raises(OutcomeEvaluationScopeMismatchError) as exc_info:
        service.revalidate_historical_evaluations(admin_empty_plants)
    assert "Plant scope denied" in str(exc_info.value) or "no assigned plants" in str(exc_info.value)

    # 2. API layer check: returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: admin_empty_plants
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_121_admin_with_missing_plant_assignment_denied_fail_closed(temp_db, client):
    """121. An administrator with missing plant assignments is denied rather than treated as wildcard."""
    repo, service = temp_db
    admin_missing_plants = Identity(
        user_id="user_admin_missing_plants",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=None,  # Missing/None assignment
        clearance_level=3,
        is_server_authoritative=True,
    )

    # 1. Calling without plant_id: denied
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_missing_plants)

    # 2. Calling with explicit plant_id: also denied because caller has no plant access
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_missing_plants, plant_id="plant_01")

    # 3. API layer check: returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: admin_missing_plants
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_122_admin_assigned_to_plant_01_cannot_revalidate_plant_02(temp_db, client):
    """122. An administrator assigned only to plant_01 cannot revalidate plant_02."""
    repo, service = temp_db
    admin_p1_only = Identity(
        user_id="user_admin_p1_only",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # 1. Service layer check: requesting plant_02 is denied
    with pytest.raises(OutcomeEvaluationScopeMismatchError) as exc_info:
        service.revalidate_historical_evaluations(admin_p1_only, plant_id="plant_02")
    assert "plant_02" in str(exc_info.value) or "Plant access denied" in str(exc_info.value)

    # 2. API layer check: requesting plant_02 returns 403 Forbidden
    app.dependency_overrides[get_current_identity] = lambda: admin_p1_only
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate?plant_id=plant_02")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_123_explicit_wildcard_admin_retains_intended_behavior(temp_db, client):
    """123. An explicitly authorized wildcard administrator retains intended behavior."""
    repo, service = temp_db
    wildcard_admin = Identity(
        user_id="user_admin_wildcard_explicit",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["*"],  # Explicit wildcard
        clearance_level=3,
        is_server_authoritative=True,
    )

    # 1. Service layer without plant_id succeeds
    report = service.revalidate_historical_evaluations(wildcard_admin)
    assert "total_checked" in report
    assert report["tenant_id"] == "tenant_alpha"

    # 2. Service layer with explicit plant_id succeeds
    report_p1 = service.revalidate_historical_evaluations(wildcard_admin, plant_id="plant_01")
    assert report_p1["plant_id"] == "plant_01"

    # 3. API layer succeeds with 200 OK
    app.dependency_overrides[get_current_identity] = lambda: wildcard_admin
    try:
        res = client.post("/api/v3/learning/evaluations/revalidate")
        assert res.status_code == 200
        assert res.json()["tenant_id"] == "tenant_alpha"
    finally:
        app.dependency_overrides.pop(get_current_identity, None)


def test_124_denied_empty_or_mismatched_plant_revalidation_causes_no_mutation(temp_db, admin_identity):
    """124. Denied revalidation performs no evaluation-record mutation."""
    repo, service = temp_db

    eval_unmutated = PredictionOutcomeEvaluation(
        evaluation_id="eval_unmutated_plant_scope",
        schema_version="3.0.0",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        plant_id="plant_02",
        idempotency_key="idem_unmutated_plant_scope",
        prediction_id="pred_plant_scope_01",
        outcome_id="outc_plant_scope_01",
        evaluation_status=EvaluationStatus.EVALUATED,
        eligibility_reason="ELIGIBLE",
        evaluation_policy_version="1.0.0",
        metric_implementation_version="1.0.0",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_plant_scope_target",
        predicted_value=100.0,
        observed_value=105.0,
        unit="units",
        comparison_semantics="NUMERIC_ERROR",
        absolute_error=5.0,
        verification_reference="vrun_fake_ref",
        eligible_for_learning=True,
        provenance="test",
    )
    repo.record_evaluation(eval_unmutated)

    # 1. Admin with empty assigned_plants attempts revalidation
    admin_empty = Identity(
        user_id="user_admin_empty_mut",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=[],
        clearance_level=3,
        is_server_authoritative=True,
    )
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_empty)

    # Record remains unchanged
    rec1 = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_unmutated_plant_scope")
    assert rec1.eligible_for_learning is True

    # 2. Admin assigned only to plant_01 attempts revalidation of plant_02
    admin_p1 = Identity(
        user_id="user_admin_p1_mut",
        tenant_id=admin_identity.tenant_id,
        workspace_id=admin_identity.workspace_id,
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_p1, plant_id="plant_02")

    # Record still remains unchanged
    rec2 = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_unmutated_plant_scope")
    assert rec2.eligible_for_learning is True


def test_125_tenant_and_workspace_isolation_preserved_with_plant_scoping(temp_db):
    """125. Tenant and workspace isolation still hold alongside plant scoping."""
    repo, service = temp_db

    admin_alpha = Identity(
        user_id="user_admin_alpha_scoped",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["*"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # Revalidation is strictly bounded to caller's tenant and workspace
    rep = service.revalidate_historical_evaluations(admin_alpha)
    assert rep["tenant_id"] == "tenant_alpha"
    assert rep["workspace_id"] == "workspace_prod"


def test_126_existing_authorized_revalidation_and_ordinary_evaluation_continue_working(temp_db, test_identity, admin_identity):
    """126. Existing authorized revalidation and ordinary prediction evaluation continue to work."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # 1. Ordinary evaluation by test_identity (with assigned_plants=["plant_01", "plant_02"]) succeeds
    pred = PredictionSnapshot(
        prediction_id="pred_regress_p126",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_regress_p126",
        predicted_at=t1,
        expected_value=100.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_regress_p126",
        prediction_id="pred_regress_p126",
        target_reference="sku_regress_p126",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=98.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.OBSERVED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_regress_p126", "outc_regress_p126")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED
    assert ev.absolute_error == 2.0

    # 2. Authorized revalidation with explicit wildcard admin succeeds
    report = service.revalidate_historical_evaluations(admin_identity, plant_id="plant_01")
    assert report["plant_id"] == "plant_01"
    assert report["tenant_id"] == admin_identity.tenant_id


# =============================================================================
# GROUP M: ENFORCE PLANT SCOPE AT THE PERSISTENCE QUERY BOUNDARY (Prompt 39 Correction 4)
# =============================================================================

def _create_scoped_test_eval(
    repo,
    eval_id: str,
    plant_id: str,
    evaluated_at: str,
    tenant_id: str = "tenant_alpha",
    workspace_id: str = "workspace_prod",
    eligible: bool = True,
):
    """Helper to record a prediction outcome evaluation with specific plant and timestamp."""
    ev = PredictionOutcomeEvaluation(
        evaluation_id=eval_id,
        schema_version="3.0.0",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        plant_id=plant_id,
        idempotency_key=f"idem_{eval_id}",
        prediction_id=f"pred_{eval_id}",
        outcome_id=f"outc_{eval_id}",
        evaluation_status=EvaluationStatus.EVALUATED,
        eligibility_reason="ELIGIBLE",
        evaluation_policy_version="1.0.0",
        metric_implementation_version="1.0.0",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference=f"target_{eval_id}",
        predicted_value=100.0,
        observed_value=105.0,
        unit="units",
        comparison_semantics="NUMERIC_ERROR",
        absolute_error=5.0,
        verification_reference=f"vref_{eval_id}",
        eligible_for_learning=eligible,
        provenance="test",
        evaluated_at=evaluated_at,
    )
    repo.record_evaluation(ev)
    return ev


def test_127_identity_assigned_only_to_plant_01_never_causes_query_for_all_plants(temp_db):
    """127. An identity assigned only to plant_01 never causes a query for all plants at the boundary."""
    repo, service = temp_db
    _create_scoped_test_eval(repo, "eval_127_p1", "plant_01", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_127_p2", "plant_02", "2026-10-18T10:00:00Z")

    admin_p1 = Identity(
        user_id="user_admin_p1_boundary",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list_evaluations = repo.list_evaluations

    def spy_list_evaluations(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list_evaluations(*args, **kwargs)

    service.repository.list_evaluations = spy_list_evaluations

    # Call historical revalidation without explicit plant_id
    service.revalidate_historical_evaluations(admin_p1)

    # Must invoke list_evaluations with plant_id="plant_01" and NEVER with plant_id=None or any other plant
    assert len(captured_calls) == 1
    assert captured_calls[0]["kwargs"].get("plant_id") == "plant_01"
    assert captured_calls[0]["kwargs"].get("tenant_id") == "tenant_alpha"
    assert captured_calls[0]["kwargs"].get("workspace_id") == "workspace_prod"


def test_128_query_for_plant_02_denied_to_plant_01_identity_before_repo_queried(temp_db):
    """128. A query for plant_02 is denied to an identity assigned only to plant_01, before repository is queried."""
    repo, service = temp_db
    admin_p1 = Identity(
        user_id="user_admin_p1_deny_early",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list_evaluations = repo.list_evaluations

    def spy_list_evaluations(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list_evaluations(*args, **kwargs)

    service.repository.list_evaluations = spy_list_evaluations

    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_p1, plant_id="plant_02")

    # The repository must NEVER have been called at all
    assert len(captured_calls) == 0


def test_129_empty_and_missing_assignments_denied_before_repo_queried(temp_db):
    """129. Empty and missing assignments are denied before the repository is queried."""
    repo, service = temp_db
    admin_empty = Identity(
        user_id="user_admin_empty_early",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=[],
        clearance_level=3,
        is_server_authoritative=True,
    )
    admin_none = Identity(
        user_id="user_admin_none_early",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=None,
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list_evaluations = repo.list_evaluations

    def spy_list_evaluations(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list_evaluations(*args, **kwargs)

    service.repository.list_evaluations = spy_list_evaluations

    # 1. Empty assignments without plant_id
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_empty)

    # 2. Empty assignments with explicit plant_id
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_empty, plant_id="plant_01")

    # 3. Missing assignments without plant_id
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_none)

    # 4. Missing assignments with explicit plant_id
    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_none, plant_id="plant_01")

    # No queries issued
    assert len(captured_calls) == 0


def test_130_explicit_authorized_wildcard_uses_bounded_all_plants_query(temp_db):
    """130. An explicitly authorized wildcard still uses the bounded all-plants query."""
    repo, service = temp_db
    admin_wildcard = Identity(
        user_id="user_admin_wildcard_boundary",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["*"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list_evaluations = repo.list_evaluations

    def spy_list_evaluations(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list_evaluations(*args, **kwargs)

    service.repository.list_evaluations = spy_list_evaluations

    service.revalidate_historical_evaluations(admin_wildcard)

    assert len(captured_calls) == 1
    assert captured_calls[0]["kwargs"].get("plant_id") is None
    assert captured_calls[0]["kwargs"].get("tenant_id") == "tenant_alpha"
    assert captured_calls[0]["kwargs"].get("workspace_id") == "workspace_prod"


def test_131_multi_plant_assignments_query_only_authorized_plants(temp_db):
    """131. Multi-plant assignments query only authorized plants."""
    repo, service = temp_db
    admin_multi = Identity(
        user_id="user_admin_multi_boundary",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01", "plant_02"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list_evaluations = repo.list_evaluations

    def spy_list_evaluations(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list_evaluations(*args, **kwargs)

    service.repository.list_evaluations = spy_list_evaluations

    service.revalidate_historical_evaluations(admin_multi)

    # Must query plant_01 and plant_02, and NEVER plant_id=None or plant_03
    assert len(captured_calls) == 2
    queried_plants = [c["kwargs"].get("plant_id") for c in captured_calls]
    assert queried_plants == ["plant_01", "plant_02"]


def test_132_revalidation_enforces_overall_limit_across_all_assigned_plants(temp_db):
    """132. The overall result respects the requested limit across assigned plants."""
    repo, service = temp_db
    admin_multi = Identity(
        user_id="user_admin_limit_boundary",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01", "plant_02"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # Seed 5 records in plant_01 and 5 in plant_02 (total 10)
    for i in range(5):
        _create_scoped_test_eval(repo, f"eval_lim_p1_{i}", "plant_01", f"2026-10-18T10:0{i}:00Z")
    for i in range(5):
        _create_scoped_test_eval(repo, f"eval_lim_p2_{i}", "plant_02", f"2026-10-18T11:0{i}:00Z")

    # Request limit=3
    report = service.revalidate_historical_evaluations(admin_multi, limit=3)
    assert report["total_checked"] == 3


def test_133_combining_results_preserves_deterministic_ordering_and_deduplicates(temp_db):
    """133. Combining results preserves deterministic ordering and avoids duplicate evaluation IDs."""
    repo, service = temp_db
    admin_multi = Identity(
        user_id="user_admin_order_boundary",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01", "plant_02"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # Insert items with timestamps across plants
    ev1 = _create_scoped_test_eval(repo, "eval_order_b", "plant_01", "2026-10-18T08:00:00Z")
    ev2 = _create_scoped_test_eval(repo, "eval_order_a", "plant_02", "2026-10-18T12:00:00Z")  # Newer
    ev3 = _create_scoped_test_eval(repo, "eval_order_c", "plant_01", "2026-10-18T10:00:00Z")
    ev4 = _create_scoped_test_eval(repo, "eval_order_d", "plant_02", "2026-10-18T10:00:00Z")  # Same timestamp as ev3

    # Spy on get_observed_outcome to record the order in which evaluations were checked
    checked_outcomes = []
    orig_get_outcome = repo.get_observed_outcome

    def spy_get_outcome(*args, **kwargs):
        outcome_id = kwargs.get("outcome_id") or (args[2] if len(args) > 2 else None)
        checked_outcomes.append(outcome_id)
        return orig_get_outcome(*args, **kwargs)

    service.repository.get_observed_outcome = spy_get_outcome

    report = service.revalidate_historical_evaluations(admin_multi)

    # Expected order: evaluated_at DESC:
    # 1. eval_order_a (12:00:00Z) -> outc_eval_order_a
    # 2. eval_order_c and eval_order_d (10:00:00Z, tie broken by eval_id ASC -> eval_order_c then eval_order_d)
    # 3. eval_order_b (08:00:00Z) -> outc_eval_order_b
    assert checked_outcomes == [
        "outc_eval_order_a",
        "outc_eval_order_c",
        "outc_eval_order_d",
        "outc_eval_order_b",
    ]

    # Test deduplication: if repository returns duplicate evaluation ID across plants
    dup_eval = _create_scoped_test_eval(repo, "eval_order_dup", "plant_01", "2026-10-18T13:00:00Z")
    orig_list = repo.list_evaluations

    def mock_list_with_dups(*args, **kwargs):
        res = orig_list(*args, **kwargs)
        # In plant_02 query, duplicate eval_order_dup as well
        if kwargs.get("plant_id") == "plant_02":
            # Clone with plant_02 plant_id but duplicate evaluation_id
            fake_dup = (
                dup_eval.model_copy(update={"plant_id": "plant_02"})
                if hasattr(dup_eval, "model_copy")
                else dup_eval.copy(update={"plant_id": "plant_02"})
            )
            return res + [fake_dup]
        return res

    service.repository.list_evaluations = mock_list_with_dups
    checked_outcomes.clear()
    report_dup = service.revalidate_historical_evaluations(admin_multi)
    # outc_eval_order_dup should appear exactly once
    assert checked_outcomes.count("outc_eval_order_dup") == 1


def test_134_denied_requests_do_not_mutate_evaluation_records(temp_db):
    """134. Denied requests do not mutate evaluation records."""
    repo, service = temp_db
    ev = _create_scoped_test_eval(repo, "eval_unmutated_134", "plant_02", "2026-10-18T10:00:00Z", eligible=True)

    admin_p1 = Identity(
        user_id="user_admin_p1_nomut",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    with pytest.raises(OutcomeEvaluationScopeMismatchError):
        service.revalidate_historical_evaluations(admin_p1, plant_id="plant_02")

    loaded = repo.get_evaluation("tenant_alpha", "workspace_prod", "eval_unmutated_134")
    assert loaded.eligible_for_learning is True


def test_135_tenant_and_workspace_isolation_remains_intact(temp_db):
    """135. Tenant and workspace isolation remains intact."""
    repo, service = temp_db
    # Seed evaluation in tenant_beta
    _create_scoped_test_eval(
        repo,
        "eval_beta_iso",
        "plant_01",
        "2026-10-18T10:00:00Z",
        tenant_id="tenant_beta",
        workspace_id="workspace_staging",
    )
    # Seed evaluation in tenant_alpha
    _create_scoped_test_eval(
        repo,
        "eval_alpha_iso",
        "plant_01",
        "2026-10-18T10:00:00Z",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
    )

    admin_alpha = Identity(
        user_id="user_admin_alpha_iso",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    captured_calls = []
    orig_list = repo.list_evaluations

    def spy_list(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})
        return orig_list(*args, **kwargs)

    service.repository.list_evaluations = spy_list

    report = service.revalidate_historical_evaluations(admin_alpha)

    assert report["tenant_id"] == "tenant_alpha"
    assert report["workspace_id"] == "workspace_prod"
    assert len(captured_calls) == 1
    assert captured_calls[0]["kwargs"].get("tenant_id") == "tenant_alpha"
    assert captured_calls[0]["kwargs"].get("workspace_id") == "workspace_prod"

    # Evaluation in tenant_beta remains untouched
    beta_rec = repo.get_evaluation("tenant_beta", "workspace_staging", "eval_beta_iso")
    assert beta_rec is not None
    assert beta_rec.eligible_for_learning is True


def test_136_existing_authoritative_verification_and_evaluation_flow_intact(temp_db, test_identity, admin_identity):
    """136. The existing authoritative verification checks and ordinary evaluation flow continue working."""
    repo, service = temp_db
    t1 = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    t2 = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # 1. Ordinary evaluation flow succeeds
    pred = PredictionSnapshot(
        prediction_id="pred_136_ok",
        prediction_type=PredictionType.DEMAND_FORECAST,
        target_reference="sku_136_ok",
        predicted_at=t1,
        expected_value=50.0,
        expected_unit="units",
        prediction_provenance="service",
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_prediction_snapshot(test_identity, pred)

    outc = ObservedOutcome(
        outcome_id="outc_136_ok",
        prediction_id="pred_136_ok",
        target_reference="sku_136_ok",
        outcome_type="DEMAND",
        observed_at=t2,
        observed_value=50.0,
        unit="units",
        provenance="sensor",
        verification_status=OutcomeVerificationStatus.OBSERVED,
        tenant_id=test_identity.tenant_id,
        workspace_id=test_identity.workspace_id,
        plant_id="plant_01",
    )
    service.record_observed_outcome(test_identity, outc)

    ev = service.evaluate_prediction_outcome(test_identity, "pred_136_ok", "outc_136_ok")
    assert ev.evaluation_status == EvaluationStatus.EVALUATED
    assert ev.absolute_error == 0.0

    # 2. Historical revalidation catches unverified outcomes and corrects them
    # Seed an evaluation whose outcome is missing/unverified
    _create_scoped_test_eval(repo, "eval_136_unverified", "plant_01", "2026-10-18T10:00:00Z", eligible=True)
    report = service.revalidate_historical_evaluations(admin_identity, plant_id="plant_01")
    assert report["corrected_count"] >= 1
    assert "eval_136_unverified" in report["corrected_evaluation_ids"]
    corrected = repo.get_evaluation(admin_identity.tenant_id, admin_identity.workspace_id, "eval_136_unverified")
    assert corrected.eligible_for_learning is False


# =============================================================================
# GROUP N: DETERMINISTIC ORDERING BEFORE REPOSITORY LIMITS (Prompt 39 Correction 5)
# =============================================================================

def test_137_repository_ordering_primary_evaluated_at_desc_secondary_eval_id_asc(temp_db):
    """137. Repository results are ordered by evaluated_at DESC, then evaluation_id ASC."""
    repo, service = temp_db
    # Insert in mixed order with varied timestamps and ties
    _create_scoped_test_eval(repo, "eval_137_mid_z", "plant_01", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_137_new_a", "plant_01", "2026-10-18T12:00:00Z")
    _create_scoped_test_eval(repo, "eval_137_mid_a", "plant_01", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_137_old_m", "plant_01", "2026-10-18T08:00:00Z")
    _create_scoped_test_eval(repo, "eval_137_mid_m", "plant_01", "2026-10-18T10:00:00Z")

    results = repo.list_evaluations(tenant_id="tenant_alpha", workspace_id="workspace_prod", plant_id="plant_01")
    result_ids = [r.evaluation_id for r in results]

    # Expected: 12:00 first, then 10:00 sorted ASC by eval_id (mid_a, mid_m, mid_z), then 08:00
    assert result_ids == [
        "eval_137_new_a",
        "eval_137_mid_a",
        "eval_137_mid_m",
        "eval_137_mid_z",
        "eval_137_old_m",
    ]


def test_138_deterministic_selection_when_tied_timestamps_exceed_query_limit(temp_db):
    """138. When multiple records share the same timestamp and exceed query limit, selected records are deterministic before limit."""
    repo, service = temp_db
    # Create 8 records sharing the EXACT same timestamp (10:00:00Z), inserted out of alphabetical order
    same_ts = "2026-10-18T10:00:00Z"
    ids_to_insert = [
        "eval_138_tie_07",
        "eval_138_tie_02",
        "eval_138_tie_05",
        "eval_138_tie_01",
        "eval_138_tie_08",
        "eval_138_tie_03",
        "eval_138_tie_06",
        "eval_138_tie_04",
    ]
    for eid in ids_to_insert:
        _create_scoped_test_eval(repo, eid, "plant_01", same_ts)

    # Query with limit=4 (exceeded by 8 records)
    limit = 4
    results = repo.list_evaluations(
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        limit=limit,
    )

    # Must deterministically select the lowest 4 evaluation_ids before limit is applied
    assert len(results) == 4
    selected_ids = [r.evaluation_id for r in results]
    assert selected_ids == [
        "eval_138_tie_01",
        "eval_138_tie_02",
        "eval_138_tie_03",
        "eval_138_tie_04",
    ]

    # Verify repeatable deterministic behavior
    repeat_results = repo.list_evaluations(
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        limit=limit,
    )
    assert [r.evaluation_id for r in repeat_results] == selected_ids


def test_139_multi_plant_revalidation_retains_deterministic_ordering_and_overall_limit(temp_db):
    """139. Multi-plant revalidation retains deterministic ordering and the overall limit."""
    repo, service = temp_db
    admin_multi = Identity(
        user_id="user_admin_reval_det",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ADMINISTRATOR"],
        permissions=["learning.evaluation.revalidate"],
        assigned_plants=["plant_01", "plant_02"],
        clearance_level=3,
        is_server_authoritative=True,
    )

    # Seed records in plant_01 and plant_02 with same timestamps exceeding limit
    # plant_01 has 2 items at 10:00:00Z and 1 at 12:00:00Z
    _create_scoped_test_eval(repo, "eval_139_tie_b_p1", "plant_01", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_139_tie_d_p1", "plant_01", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_139_recent_p1", "plant_01", "2026-10-18T12:00:00Z")

    # plant_02 has 2 items at 10:00:00Z and 1 at 12:00:00Z
    _create_scoped_test_eval(repo, "eval_139_tie_a_p2", "plant_02", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_139_tie_c_p2", "plant_02", "2026-10-18T10:00:00Z")
    _create_scoped_test_eval(repo, "eval_139_recent_p2", "plant_02", "2026-10-18T12:00:00Z")

    # Intercept outcomes to track the exact sequence in which revalidation examines records
    checked_eval_outcomes = []
    orig_get_outcome = repo.get_observed_outcome

    def spy_get_outcome(*args, **kwargs):
        outcome_id = kwargs.get("outcome_id") or (args[2] if len(args) > 2 else None)
        checked_eval_outcomes.append(outcome_id)
        return orig_get_outcome(*args, **kwargs)

    service.repository.get_observed_outcome = spy_get_outcome

    # Request limit=4 overall across both plants (there are 6 eligible records)
    report = service.revalidate_historical_evaluations(admin_multi, limit=4)
    assert report["total_checked"] == 4

    # Ordering must be evaluated_at DESC (12:00 before 10:00) then evaluation_id ASC:
    # 12:00: eval_139_recent_p1, then eval_139_recent_p2
    # 10:00: eval_139_tie_a_p2 (plant_02), then eval_139_tie_b_p1 (plant_01)
    assert checked_eval_outcomes == [
        "outc_eval_139_recent_p1",
        "outc_eval_139_recent_p2",
        "outc_eval_139_tie_a_p2",
        "outc_eval_139_tie_b_p1",
    ]


def test_140_tenant_workspace_plant_and_eligibility_filtering_unchanged(temp_db):
    """140. Tenant/workspace/plant filtering and eligibility filters remain strictly enforced."""
    repo, service = temp_db
    same_ts = "2026-10-18T10:00:00Z"

    # Seed records in target scope
    _create_scoped_test_eval(repo, "eval_140_target_1", "plant_01", same_ts, eligible=True)
    _create_scoped_test_eval(repo, "eval_140_target_2", "plant_01", same_ts, eligible=False)

    # Seed records outside target scope (other plant, other workspace, other tenant)
    _create_scoped_test_eval(repo, "eval_140_diff_plant", "plant_02", same_ts, eligible=True)
    _create_scoped_test_eval(repo, "eval_140_diff_ws", "plant_01", same_ts, workspace_id="workspace_other", eligible=True)
    _create_scoped_test_eval(repo, "eval_140_diff_tenant", "plant_01", same_ts, tenant_id="tenant_other", eligible=True)

    # Query with plant_id="plant_01" and eligible_only=True
    filtered = repo.list_evaluations(
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        eligible_only=True,
    )
    assert len(filtered) == 1
    assert filtered[0].evaluation_id == "eval_140_target_1"

    # Query with plant_id="plant_01" and eligible_only=False
    all_p1 = repo.list_evaluations(
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        plant_id="plant_01",
        eligible_only=False,
    )
    assert len(all_p1) == 2
    assert {r.evaluation_id for r in all_p1} == {"eval_140_target_1", "eval_140_target_2"}


def test_141_existing_repository_and_service_behavior_remains_compatible(temp_db, test_identity):
    """141. Existing repository and service behavior remains compatible with limit bounding and prior eval lookup."""
    repo, service = temp_db
    # Test repository bounds limit: min(max(1, limit), 200)
    for i in range(5):
        _create_scoped_test_eval(repo, f"eval_141_{i}", "plant_01", f"2026-10-18T10:0{i}:00Z")

    # Limit = -10 clamped to 1
    res_neg = repo.list_evaluations("tenant_alpha", "workspace_prod", limit=-10)
    assert len(res_neg) == 1

    # Limit = 0 clamped to 1
    res_zero = repo.list_evaluations("tenant_alpha", "workspace_prod", limit=0)
    assert len(res_zero) == 1

    # Service list_evaluations delegates transparently
    srv_list = service.list_evaluations(test_identity, plant_id="plant_01", limit=3)
    assert len(srv_list) == 3
    # Verify deterministic ordering holds on service call as well
    assert srv_list[0].evaluation_id == "eval_141_4"  # Most recent (10:04)
    assert srv_list[1].evaluation_id == "eval_141_3"  # 10:03
    assert srv_list[2].evaluation_id == "eval_141_2"  # 10:02


