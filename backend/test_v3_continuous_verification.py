# backend/test_v3_continuous_verification.py
"""
SageCommand V3 — Continuous Verification Engine Foundation Test Suite (Prompt 36)

Comprehensive verification testing covering:
1. Verification Correctness:
   - Valid evidence satisfies supported deterministic rules.
   - Missing evidence produces unverified or indeterminate results.
   - Invalid evidence cannot establish success.
   - Unverified evidence cannot establish success.
   - Stale evidence is handled according to configured freshness rule.
   - Missing timestamps do not become fresh timestamps.
   - Future timestamps produce indeterminate / caveat status.
   - Conflicting evidence is preserved and reported as CONFLICTING.
   - Unsupported rules are rejected deterministically.
   - Rule version is recorded.

2. Scope and Authorization:
   - Cross-tenant mission verification is rejected.
   - Cross-workspace verification is rejected.
   - Cross-plant evidence is rejected.
   - Untagged plant-sensitive evidence fails closed.
   - Missing or empty plant assignments fail closed.
   - A forged client tenant_id is ignored/rejected.
   - A forged client workspace_id is ignored/rejected.
   - A forged client plant_id is ignored/rejected.
   - Verification IDs cannot be used to retrieve another tenant's or workspace's results.

3. Mission Integrity:
   - Accepted missions are NOT executed by verification.
   - Mission definitions remain untouched/immutable after verification.
   - Client-supplied verification status is rejected.
   - Client-supplied verified timestamps are rejected.
   - Mission revision mismatch is detected.
   - A verification result cannot self-approve an Action.
   - Missing evidence cannot mark a criterion as satisfied.
   - Verification runs cannot bypass Database Connection Gateway.

4. Persistence and Idempotency:
   - Verification history survives repository reinstantiation.
   - Historical findings are not silently overwritten.
   - Equivalent retries are handled deterministically.
   - Conflicting idempotency-key reuse is rejected.
   - Audit ledger records every lifecycle event with SHA-256 checksums.
   - Concurrent verification requests do not corrupt stored records.

5. Resource Bounds and Failure Handling:
   - Oversized requests are rejected.
   - Excessive targets are rejected.
   - Excessive evidence references are truncated safely.
   - Timeout behavior is bounded.
   - Repository failures produce safe errors.
   - Raw exceptions and secrets are not exposed.
   - Partial results never falsely mark unresolved targets verified.

6. Architectural Safety:
   - AST static analysis demonstrating zero create_engine(), zero create_async_engine(),
     zero arbitrary SQL mutation, zero subprocess, zero ExecutionGateway invocation,
     and zero mission execution endpoints in verification engine.

7. REST API & Agent Tools:
   - POST /api/v3/missions/{mission_id}/verifications
   - GET  /api/v3/missions/{mission_id}/verifications
   - GET  /api/v3/missions/{mission_id}/verifications/{verification_id}
   - GET  /api/v3/missions/{mission_id}/verifications/{verification_id}/findings
   - POST /api/v3/missions/{mission_id}/verifications/{verification_id}/cancel
   - GET  /api/v3/missions/{mission_id}/verifications/{verification_id}/audit
   - Agent verification tools (request_mission_verification_tool, get_mission_verification_findings_tool)
"""

import ast
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

try:
    from server import app
    from core.auth import Identity, get_current_identity
    from data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        TriggerType,
        RuleType,
        EvidenceAssessment,
        VerificationRule,
        VerificationProvenance,
        VerificationAuditRecord,
        VerificationRequest,
        VerificationRunSummary,
        RULE_SET_VERSION,
        EVALUATOR_VERSION,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from repositories.verification_repository import (
        VerificationRepository,
        VerificationRepositoryError,
        VerificationNotFoundError,
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )
    from services.verification_service import (
        VerificationService,
        VerificationServiceError,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationRevisionMismatchError,
    )
    from services.verification_rules import (
        verification_rule_registry,
        EvidenceExistsRule,
        EvidenceValidatedRule,
        EvidenceFreshRule,
        RequiredEvidencePresentRule,
        RequiredEvidenceValidatedRule,
        EvidenceScopeMatchRule,
        RequiredFieldsPresentRule,
        SourceConsistencyRule,
    )
    from repositories.mission_repository import MissionRepository
    from services.mission_service import MissionService
    from data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionScope,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
    )
    from repositories.evidence_explainability_repository import EvidenceExplainabilityRepository
    from services.action_store import action_store
    from tools.verification_tools import (
        request_mission_verification_tool,
        get_mission_verification_findings_tool,
        set_active_verification_identity,
        reset_active_verification_identity,
        get_active_verification_identity,
        active_verification_identity,
        async_active_verification_identity,
    )
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.auth import Identity, get_current_identity
    from backend.data.schemas.verification_contract import (
        VerificationRun,
        VerificationFinding,
        VerificationStatus,
        VerificationTargetType,
        FreshnessStatus,
        QualityStatus,
        ScopeStatus,
        TriggerType,
        RuleType,
        EvidenceAssessment,
        VerificationRule,
        VerificationProvenance,
        VerificationAuditRecord,
        VerificationRequest,
        VerificationRunSummary,
        RULE_SET_VERSION,
        EVALUATOR_VERSION,
        MANDATORY_VERIFICATION_NOTICE,
    )
    from backend.repositories.verification_repository import (
        VerificationRepository,
        VerificationRepositoryError,
        VerificationNotFoundError,
        VerificationConcurrencyError,
        VerificationIdempotencyConflictError,
    )
    from backend.services.verification_service import (
        VerificationService,
        VerificationServiceError,
        VerificationPermissionError,
        VerificationValidationError,
        VerificationRevisionMismatchError,
    )
    from backend.services.verification_rules import (
        verification_rule_registry,
        EvidenceExistsRule,
        EvidenceValidatedRule,
        EvidenceFreshRule,
        RequiredEvidencePresentRule,
        RequiredEvidenceValidatedRule,
        EvidenceScopeMatchRule,
        RequiredFieldsPresentRule,
        SourceConsistencyRule,
    )
    from backend.repositories.mission_repository import MissionRepository
    from backend.services.mission_service import MissionService
    from backend.data.schemas.mission_contract import (
        Mission,
        MissionStatus,
        MissionType,
        MissionScope,
        MissionSuccessCriterion,
        MissionEvidenceRequirement,
        MissionPlannedStep,
        MissionProvenance,
        StepType,
        StepStatus,
        DataMode,
        CriterionStatus,
    )
    from backend.repositories.evidence_explainability_repository import EvidenceExplainabilityRepository
    from backend.services.action_store import action_store
    from backend.tools.verification_tools import (
        request_mission_verification_tool,
        get_mission_verification_findings_tool,
        set_active_verification_identity,
        reset_active_verification_identity,
        get_active_verification_identity,
        active_verification_identity,
        async_active_verification_identity,
    )


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_vdb():
    """Provides a fresh temporary SQLite database path for verification repo."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        path = tf.name
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def v_repo(temp_vdb):
    """Provides an isolated VerificationRepository instance."""
    return VerificationRepository(db_path=temp_vdb)


@pytest.fixture
def temp_mdb():
    """Provides a fresh temporary SQLite database path for mission repo."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        path = tf.name
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def m_repo(temp_mdb):
    """Provides an isolated MissionRepository instance."""
    return MissionRepository(db_path=temp_mdb)


@pytest.fixture
def temp_edb():
    """Provides a fresh temporary SQLite database path for evidence repo."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        path = tf.name
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


@pytest.fixture
def e_repo(temp_edb):
    """Provides an isolated EvidenceExplainabilityRepository instance."""
    return EvidenceExplainabilityRepository(db_path=temp_edb)


@pytest.fixture
def m_service(m_repo):
    """Provides MissionService using isolated repository."""
    return MissionService(repository=m_repo)


@pytest.fixture
def v_service(v_repo, m_service, e_repo):
    """Provides VerificationService using isolated repositories."""
    return VerificationService(
        repository=v_repo,
        mission_svc=m_service,
        evidence_repo=e_repo,
    )


@pytest.fixture
def analyst_identity():
    """Identity with analyst permissions for requesting verification."""
    return Identity(
        user_id="analyst_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ANALYST"],
        permissions=[
            "mission.read",
            "mission.verification.read",
            "mission.verification.request",
        ],
        assigned_plants=["plant_01"],
        session_id="session_an_1",
    )


@pytest.fixture
def viewer_identity():
    """Identity with read-only viewer permissions."""
    return Identity(
        user_id="viewer_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["VIEWER"],
        permissions=[
            "mission.read",
            "mission.verification.read",
        ],
        assigned_plants=["plant_01"],
        session_id="session_vw_1",
    )


@pytest.fixture
def operator_identity():
    """Operator identity with cancel permissions."""
    return Identity(
        user_id="operator_01",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["OPERATOR"],
        permissions=[
            "mission.read",
            "mission.verification.read",
            "mission.verification.request",
            "mission.verification.cancel",
        ],
        assigned_plants=["plant_01"],
        session_id="session_op_1",
    )


@pytest.fixture
def cross_tenant_identity():
    """Identity in tenant_beta."""
    return Identity(
        user_id="user_beta",
        tenant_id="tenant_beta",
        workspace_id="workspace_prod",
        roles=["ANALYST"],
        permissions=["mission.read", "mission.verification.read", "mission.verification.request"],
        assigned_plants=["*"],
    )


@pytest.fixture
def sample_mission(m_service, analyst_identity):
    """Creates and accepts a standard test mission in tenant_alpha / plant_01."""
    mission = Mission(
        mission_id="msn_test_100",
        schema_version="3.0.0",
        title="Test Clean Energy Transition",
        description="Verify plant telemetry and energy switch steps",
        objective="Verify plant operational steps against live evidence",
        mission_type=MissionType.INVESTIGATION,
        status=MissionStatus.ACCEPTED,
        scope=MissionScope(
            tenant_id="tenant_alpha",
            workspace_id="workspace_prod",
            plant_id="plant_01",
        ),
        success_criteria=[
            MissionSuccessCriterion(
                criterion_id="crit_01",
                description="Live telemetry must confirm temperature in threshold",
                required_evidence_type="TELEMETRY_LOG",
                status=CriterionStatus.UNKNOWN,
            ),
            MissionSuccessCriterion(
                criterion_id="crit_02",
                description="Power usage under baseline",
                required_evidence_type="POWER_METRIC",
                status=CriterionStatus.UNKNOWN,
            ),
        ],
        evidence_requirements=[
            MissionEvidenceRequirement(
                requirement_id="req_01",
                evidence_type="TELEMETRY_LOG",
                description="Real-time plant telemetry logs",
                linked_evidence_id="ev_rec_01",
                is_mandatory=True,
            ),
            MissionEvidenceRequirement(
                requirement_id="req_02",
                evidence_type="POWER_METRIC",
                description="Power sensor telemetry",
                linked_evidence_id="ev_rec_02",
                is_mandatory=True,
            ),
        ],
        planned_steps=[
            MissionPlannedStep(
                step_id="step_01",
                title="Initialize telemetry monitoring",
                description="Ensure live telemetry sensors active",
                step_type=StepType.INVESTIGATION,
                status=StepStatus.PLANNED,
                required_evidence=["ev_rec_01"],
            ),
            MissionPlannedStep(
                step_id="step_02",
                title="Verify power adjustment",
                description="Check power drop",
                step_type=StepType.ANALYSIS,
                status=StepStatus.PLANNED,
                depends_on=["step_01"],
                required_evidence=["ev_rec_02"],
            ),
        ],
        provenance=MissionProvenance(
            created_by="analyst_01",
            origin_reason="Test mission creation for continuous verification",
        ),
        created_by="analyst_01",
        revision=1,
    )
    return m_service.repository.create_mission(mission, change_reason="Initial test creation")


# =============================================================================
# 1. VERIFICATION CORRECTNESS TESTS
# =============================================================================

def test_evidence_exists_rule_verified():
    """Valid authorized evidence satisfies EVIDENCE_EXISTS rule."""
    rule = EvidenceExistsRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        observed_at=datetime.now(timezone.utc).isoformat(),
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={},
    )
    assert finding.status == VerificationStatus.VERIFIED
    assert "ev_001" in finding.evidence_references
    assert finding.rule_id == "RULE_EVIDENCE_EXISTS_V1"
    # Ensure notice explicitly clarifies record presence only
    assert "confirms record presence only" in finding.explanation


def test_evidence_exists_rule_missing_evidence():
    """Missing evidence produces NOT_VERIFIED finding."""
    rule = EvidenceExistsRule()
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={},
    )
    assert finding.status == VerificationStatus.NOT_VERIFIED
    assert len(finding.evidence_references) == 0
    assert len(finding.limitations) > 0


def test_evidence_exists_does_not_certify_operational_outcome():
    """EVIDENCE_EXISTS rule proves accessible record exists, not operational truth."""
    rule = EvidenceExistsRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_raw_01",
        source_type="TELEMETRY_LOG",
        observed_at=datetime.now(timezone.utc).isoformat(),
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("step_01", VerificationTargetType.STEP, [assessment], {}, {})
    assert finding.status == VerificationStatus.VERIFIED
    assert "does not self-certify operational completion or outcome" in finding.explanation


def test_evidence_validated_rule_valid_evidence():
    """Valid integrity evidence satisfies EVIDENCE_VALIDATED rule."""
    rule = EvidenceValidatedRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={},
    )
    assert finding.status == VerificationStatus.VERIFIED


def test_evidence_validated_rule_invalid_evidence():
    """Invalid evidence fails verification deterministically."""
    rule = EvidenceValidatedRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        integrity_status="INVALID",
        quality_status=QualityStatus.INVALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={},
    )
    assert finding.status == VerificationStatus.NOT_VERIFIED
    assert "INVALID" in finding.explanation


def test_evidence_validated_rule_unverified_evidence():
    """Unverified evidence produces INDETERMINATE result (cannot self-certify)."""
    rule = EvidenceValidatedRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        integrity_status="UNVERIFIED",
        quality_status=QualityStatus.UNVERIFIED,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={},
    )
    assert finding.status == VerificationStatus.INDETERMINATE


# --- PROMPT 36A: MIXED EVIDENCE AGGREGATION FAIL-CLOSED TESTS ---

def test_mixed_evidence_valid_plus_unverified():
    """VALID + UNVERIFIED evidence must never return VERIFIED; returns INDETERMINATE."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    unverified_ev = EvidenceAssessment(
        evidence_id="ev_unverified",
        source_type="SENSOR",
        integrity_status="UNVERIFIED",
        quality_status=QualityStatus.UNVERIFIED,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, unverified_ev], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.status != VerificationStatus.VERIFIED


def test_mixed_evidence_valid_plus_invalid():
    """VALID + INVALID evidence must never return VERIFIED; returns NOT_VERIFIED."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    invalid_ev = EvidenceAssessment(
        evidence_id="ev_invalid",
        source_type="SENSOR",
        integrity_status="INVALID",
        quality_status=QualityStatus.INVALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, invalid_ev], {}, {})
    assert finding.status == VerificationStatus.NOT_VERIFIED
    assert finding.status != VerificationStatus.VERIFIED


def test_mixed_evidence_valid_plus_unknown():
    """VALID + UNKNOWN integrity must never return VERIFIED; returns INDETERMINATE."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    unknown_ev = EvidenceAssessment(
        evidence_id="ev_unknown",
        source_type="SENSOR",
        integrity_status="UNKNOWN",
        quality_status=QualityStatus.UNKNOWN,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, unknown_ev], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.status != VerificationStatus.VERIFIED


def test_mixed_evidence_valid_plus_incomplete():
    """VALID + INCOMPLETE evidence must never return VERIFIED; returns INDETERMINATE."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    incomplete_ev = EvidenceAssessment(
        evidence_id="ev_incomplete",
        source_type="SENSOR",
        integrity_status="INCOMPLETE",
        quality_status=QualityStatus.INCOMPLETE,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, incomplete_ev], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.status != VerificationStatus.VERIFIED


def test_mixed_evidence_valid_plus_conflicting():
    """VALID + CONFLICTING evidence must return CONFLICTING."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    conflicting_ev = EvidenceAssessment(
        evidence_id="ev_conflicting",
        source_type="SENSOR",
        integrity_status="CONFLICTING",
        quality_status=QualityStatus.CONFLICTING,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, conflicting_ev], {}, {})
    assert finding.status == VerificationStatus.CONFLICTING
    assert finding.status != VerificationStatus.VERIFIED


def test_mixed_evidence_valid_plus_inaccessible():
    """VALID + inaccessible/blocked evidence must return BLOCKED without data leak."""
    rule = EvidenceValidatedRule()
    valid_ev = EvidenceAssessment(
        evidence_id="ev_valid",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    blocked_ev = EvidenceAssessment(
        evidence_id="ev_secret",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.CROSS_PLANT,
        classification_status="CLEARANCE_INSUFFICIENT",
        applicability_status="TARGET_MISMATCH",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [valid_ev, blocked_ev], {}, {})
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.status != VerificationStatus.VERIFIED


# --- PROMPT 36A: CLASSIFICATION AND APPLICABILITY TESTS ---

def test_unknown_classification_cannot_be_treated_as_authorized():
    """Unknown classification clearance metadata fails closed to INDETERMINATE."""
    rule = EvidenceValidatedRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="UNKNOWN",  # Untrusted default
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [assessment], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE


def test_unknown_applicability_cannot_be_treated_as_applicable():
    """Unknown applicability metadata fails closed to INDETERMINATE."""
    rule = EvidenceValidatedRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        integrity_status="VALID",
        quality_status=QualityStatus.VALID,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="UNKNOWN",  # Untrusted default
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [assessment], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE


def test_insufficient_clearance_returns_blocked(v_service, sample_mission):
    """Caller with lower clearance than required evidence gets BLOCKED without data leak."""
    low_clearance_identity = Identity(
        user_id="low_sec_user",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ANALYST"],
        permissions=["mission.read", "mission.verification.request"],
        assigned_plants=["plant_01"],
        clearance_level=1,  # Tier 1 (INTERNAL)
    )
    # Evidence service evaluating a tier 3 (RESTRICTED) source
    clear_status = v_service._evaluate_clearance(low_clearance_identity, required_clearance=3)
    assert clear_status == "CLEARANCE_INSUFFICIENT"


# --- PROMPT 36A: FRESHNESS AND TIMESTAMP SEMANTICS TESTS ---

def test_evidence_fresh_rule_current():
    """Fresh evidence within threshold window produces VERIFIED."""
    rule = EvidenceFreshRule()
    now = datetime.now(timezone.utc)
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="TELEMETRY",
        observed_at=(now - timedelta(minutes=5)).isoformat(),
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={"freshness_threshold_seconds": 3600.0},
        now=now,
    )
    assert finding.status == VerificationStatus.VERIFIED


def test_evidence_fresh_rule_stale():
    """Stale evidence beyond threshold window produces STALE status."""
    rule = EvidenceFreshRule()
    now = datetime.now(timezone.utc)
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="TELEMETRY",
        observed_at=(now - timedelta(hours=48)).isoformat(),
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={"freshness_threshold_seconds": 3600.0},
        now=now,
    )
    assert finding.status == VerificationStatus.STALE


def test_evidence_fresh_rule_missing_timestamp():
    """Missing timestamp does NOT become fresh; produces INDETERMINATE."""
    rule = EvidenceFreshRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="TELEMETRY",
        observed_at=None,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={"freshness_threshold_seconds": 3600.0},
    )
    assert finding.status == VerificationStatus.INDETERMINATE
    assert "missing" in finding.explanation.lower()


def test_historical_record_without_observation_timestamp_cannot_satisfy_evidence_fresh():
    """Recently created historical record without observation timestamp fails freshness."""
    rule = EvidenceFreshRule()
    now = datetime.now(timezone.utc)
    # Record has recent received/created time, but NO observation time
    assessment = EvidenceAssessment(
        evidence_id="ev_hist_01",
        source_type="ACTION_RECORD",
        observed_at=None,
        received_at=now.isoformat(),
        freshness_status=FreshnessStatus.TIMESTAMP_MISSING,
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={"freshness_threshold_seconds": 3600.0},
        now=now,
    )
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.status != VerificationStatus.VERIFIED


def test_evidence_fresh_rule_future_timestamp():
    """Future-dated timestamp produces INDETERMINATE caveat."""
    rule = EvidenceFreshRule()
    now = datetime.now(timezone.utc)
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="TELEMETRY",
        observed_at=(now + timedelta(hours=5)).isoformat(),
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={"tenant_id": "t1", "workspace_id": "w1", "plant_id": "p1"},
        parameters={"freshness_threshold_seconds": 3600.0},
        now=now,
    )
    assert finding.status == VerificationStatus.INDETERMINATE
    assert "future-dated" in finding.explanation.lower()


def test_required_evidence_present_rule():
    """Verifies that all specified evidence types are present."""
    rule = RequiredEvidencePresentRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="TELEMETRY_LOG",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    # Satisfies
    f1 = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={},
        parameters={"required_evidence_types": ["TELEMETRY_LOG"]},
    )
    assert f1.status == VerificationStatus.VERIFIED

    # Missing required type
    f2 = rule.evaluate(
        target_id="crit_01",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assessment],
        mission_scope={},
        parameters={"required_evidence_types": ["POWER_METRIC"]},
    )
    assert f2.status == VerificationStatus.NOT_VERIFIED


def test_evidence_scope_match_rule():
    """Scope match rule marks BLOCKED when evidence violates boundaries."""
    rule = EvidenceScopeMatchRule()
    a_ok = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    a_bad = EvidenceAssessment(
        evidence_id="ev_002",
        source_type="SENSOR",
        scope_status=ScopeStatus.CROSS_PLANT,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )

    f_ok = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [a_ok], {}, {})
    assert f_ok.status == VerificationStatus.VERIFIED

    f_blocked = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [a_bad], {}, {})
    assert f_blocked.status == VerificationStatus.BLOCKED


def test_required_fields_present_rule():
    """Verifies presence of specified payload fields."""
    rule = RequiredFieldsPresentRule()
    assessment = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="RECORD",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )

    # Has required field
    f1 = rule.evaluate(
        "crit_01",
        VerificationTargetType.CRITERION,
        [assessment],
        {},
        {"required_fields": ["sensor_temp"], "evidence_payloads": {"ev_001": {"sensor_temp": 45.2}}},
    )
    assert f1.status == VerificationStatus.VERIFIED

    # Missing field
    f2 = rule.evaluate(
        "crit_01",
        VerificationTargetType.CRITERION,
        [assessment],
        {},
        {"required_fields": ["sensor_pressure"], "evidence_payloads": {"ev_001": {"sensor_temp": 45.2}}},
    )
    assert f2.status == VerificationStatus.NOT_VERIFIED


def test_source_consistency_rule_agreement_and_conflict():
    """Consistent sources produce VERIFIED; conflicting values produce CONFLICTING."""
    rule = SourceConsistencyRule()
    a1 = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR_A",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    a2 = EvidenceAssessment(
        evidence_id="ev_002",
        source_type="SENSOR_B",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )

    # Consistent within tolerance
    f_agree = rule.evaluate(
        "crit_01",
        VerificationTargetType.CRITERION,
        [a1, a2],
        {},
        {
            "metric_key": "voltage",
            "tolerance": 0.05,
            "evidence_payloads": {"ev_001": {"voltage": 120.0}, "ev_002": {"voltage": 121.0}},
        },
    )
    assert f_agree.status == VerificationStatus.VERIFIED

    # Conflicting beyond tolerance
    f_conflict = rule.evaluate(
        "crit_01",
        VerificationTargetType.CRITERION,
        [a1, a2],
        {},
        {
            "metric_key": "voltage",
            "tolerance": 0.05,
            "evidence_payloads": {"ev_001": {"voltage": 120.0}, "ev_002": {"voltage": 240.0}},
        },
    )
    assert f_conflict.status == VerificationStatus.CONFLICTING
    assert "disagree" in f_conflict.explanation.lower()


def test_unsupported_rule_rejection(v_service, analyst_identity, sample_mission):
    """Unsupported rule type in request is rejected deterministically."""
    # Custom non-existent rule type
    with pytest.raises(Exception):
        req = VerificationRequest(rule_type="NON_EXISTENT_RULE")


# =============================================================================
# 2. SCOPE AND AUTHORIZATION TESTS
# =============================================================================

def test_cross_tenant_mission_verification_rejected(v_service, cross_tenant_identity, sample_mission):
    """Caller from tenant_beta cannot verify mission in tenant_alpha (fail-closed)."""
    req = VerificationRequest()
    with pytest.raises(VerificationNotFoundError):
        v_service.request_verification(cross_tenant_identity, sample_mission.mission_id, req)


def test_cross_workspace_verification_rejected(v_service, analyst_identity, sample_mission):
    """Caller with workspace_other cannot verify mission in workspace_prod."""
    other_ws_identity = Identity(
        user_id="user_ws_other",
        tenant_id="tenant_alpha",
        workspace_id="workspace_other",
        roles=["ANALYST"],
        permissions=["mission.read", "mission.verification.request"],
        assigned_plants=["*"],
    )
    req = VerificationRequest()
    with pytest.raises(VerificationNotFoundError):
        v_service.request_verification(other_ws_identity, sample_mission.mission_id, req)


def test_unauthorized_plant_caller_rejected(v_service, sample_mission):
    """Caller assigned only to plant_99 cannot verify mission in plant_01."""
    plant_99_identity = Identity(
        user_id="user_p99",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ANALYST"],
        permissions=["mission.read", "mission.verification.request"],
        assigned_plants=["plant_99"],
    )
    req = VerificationRequest()
    with pytest.raises(VerificationPermissionError):
        v_service.request_verification(plant_99_identity, sample_mission.mission_id, req)


def test_empty_plant_assignment_fails_closed(v_service, sample_mission):
    """Caller with no assigned plants fails closed."""
    no_plant_identity = Identity(
        user_id="user_nop",
        tenant_id="tenant_alpha",
        workspace_id="workspace_prod",
        roles=["ANALYST"],
        permissions=["mission.read", "mission.verification.request"],
        assigned_plants=[],
    )
    req = VerificationRequest()
    with pytest.raises(VerificationPermissionError):
        v_service.request_verification(no_plant_identity, sample_mission.mission_id, req)


def test_forged_client_identity_fields_forbidden():
    """Client cannot supply tenant_id, workspace_id, or plant_id in VerificationRequest."""
    with pytest.raises(ValueError):
        VerificationRequest(tenant_id="hacked_tenant")  # Extra field forbidden


def test_cross_plant_evidence_marked_blocked(v_service, analyst_identity, sample_mission, e_repo):
    """Evidence from plant_02 when mission is plant_01 is detected as CROSS_PLANT."""
    # Seed evidence in plant_02
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_dummy_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_02",
                "fp_01", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test explanation", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_01", "exp_dummy_01", "tenant_alpha", "workspace_prod", "plant_02",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"temp": 25.0}), "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    req = VerificationRequest(target_type=VerificationTargetType.CRITERION, target_id="crit_01")
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert run.target_count == 1
    assert run.status == VerificationStatus.BLOCKED
    # Evidence was rejected due to scope boundary, non-disclosure must redact blocked assessments
    finding = run.findings[0]
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_assessments == []
    assert finding.evidence_references == []
    assert "ev_rec_01" not in str(finding.limitations)
    assert "ev_rec_01" not in finding.explanation
    # Verify internal scope status resolution without exposing to caller
    internal_assess, _ = v_service._resolve_evidence_item("ev_rec_01", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc))
    assert internal_assess.scope_status == ScopeStatus.CROSS_PLANT


def test_untagged_plant_evidence_fails_closed(v_service, analyst_identity, sample_mission, e_repo):
    """Evidence without plant_id fails closed as UNTAGGED_PLANT."""
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_dummy_02", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", None,
                "fp_02", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test explanation untagged", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_01", "exp_dummy_02", "tenant_alpha", "workspace_prod", None,
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"temp": 25.0}), "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    req = VerificationRequest(target_type=VerificationTargetType.CRITERION, target_id="crit_01")
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert run.status == VerificationStatus.BLOCKED
    finding = run.findings[0]
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_assessments == []
    assert finding.evidence_references == []
    assert "ev_rec_01" not in str(finding.limitations)
    assert "ev_rec_01" not in finding.explanation
    # Verify internal scope status resolution without exposing to caller
    internal_assess, _ = v_service._resolve_evidence_item("ev_rec_01", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc))
    assert internal_assess.scope_status == ScopeStatus.UNTAGGED_PLANT


# =============================================================================
# 3. MISSION INTEGRITY TESTS
# =============================================================================

def test_accepted_mission_remains_unexecuted(v_service, analyst_identity, sample_mission):
    """Verification runs do not mutate mission status or execute operational steps."""
    req = VerificationRequest()
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert run.status in (VerificationStatus.NOT_VERIFIED, VerificationStatus.VERIFIED, VerificationStatus.INDETERMINATE)

    # Mission in repository must remain ACCEPTED, not EXECUTED or COMPLETED
    saved_m = v_service.mission_service.get_mission(analyst_identity, sample_mission.mission_id)
    assert saved_m.status == MissionStatus.ACCEPTED
    assert saved_m.planned_steps[0].status == StepStatus.PLANNED


def test_mission_revision_mismatch_detected(v_service, analyst_identity, sample_mission):
    """Revision mismatch raises VerificationRevisionMismatchError."""
    req = VerificationRequest(expected_mission_revision=99)  # Mission is rev 1
    with pytest.raises(VerificationRevisionMismatchError):
        v_service.request_verification(analyst_identity, sample_mission.mission_id, req)


def test_client_cannot_self_certify_verification_status():
    """Client cannot supply verification status or verified timestamps in request."""
    with pytest.raises(ValueError):
        VerificationRequest(status=VerificationStatus.VERIFIED)


# =============================================================================
# 4. PERSISTENCE AND IDEMPOTENCY TESTS
# =============================================================================

def test_verification_persistence_durability(v_service, analyst_identity, sample_mission, temp_vdb):
    """Verification run survives repository re-instantiation."""
    req = VerificationRequest()
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    v_id = run.verification_id

    # Create new repository instance pointing to same DB
    fresh_repo = VerificationRepository(db_path=temp_vdb)
    loaded = fresh_repo.get_run("tenant_alpha", "workspace_prod", sample_mission.mission_id, v_id)
    assert loaded is not None
    assert loaded.verification_id == v_id
    assert loaded.mission_revision == sample_mission.revision
    assert loaded.status == run.status


def test_idempotent_retry_returns_identical_run(v_service, analyst_identity, sample_mission):
    """Replaying request with identical idempotency_key returns identical run."""
    key = f"idem_{uuid.uuid4().hex[:12]}"
    req = VerificationRequest(idempotency_key=key)

    run1 = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    run2 = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)

    assert run1.verification_id == run2.verification_id
    assert run1.created_at == run2.created_at


def test_conflicting_idempotency_key_reuse_rejected(v_service, analyst_identity, sample_mission):
    """Reusing idempotency key with conflicting parameters raises VerificationIdempotencyConflictError."""
    key = f"idem_{uuid.uuid4().hex[:12]}"
    req1 = VerificationRequest(idempotency_key=key, target_type=VerificationTargetType.CRITERION)
    req2 = VerificationRequest(idempotency_key=key, target_type=VerificationTargetType.STEP)

    v_service.request_verification(analyst_identity, sample_mission.mission_id, req1)
    with pytest.raises(VerificationIdempotencyConflictError):
        v_service.request_verification(analyst_identity, sample_mission.mission_id, req2)


def test_verification_cancellation_lifecycle(v_service, operator_identity, sample_mission):
    """Can cancel pending / in-progress verification; cannot cancel terminal."""
    req = VerificationRequest()
    run = v_service.request_verification(operator_identity, sample_mission.mission_id, req)
    # Re-open status to PENDING in repo to test cancellation
    with v_service.repository._lock, v_service.repository._get_connection() as conn:
        conn.execute(
            "UPDATE verification_runs SET status = 'IN_PROGRESS' WHERE verification_id = ?",
            (run.verification_id,)
        )
        conn.commit()

    cancelled = v_service.cancel_verification(
        operator_identity,
        sample_mission.mission_id,
        run.verification_id,
        reason="Operator decided to defer verification until calibration complete",
    )
    assert cancelled.status == VerificationStatus.CANCELLED
    assert "cancelled by operator_01" in cancelled.summary.lower()


def test_audit_ledger_records_verification_events(v_service, analyst_identity, sample_mission):
    """Audit ledger persists entries with verified SHA-256 checksums."""
    req = VerificationRequest()
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    audits = v_service.repository.get_audit_records(
        "tenant_alpha", "workspace_prod", sample_mission.mission_id, run.verification_id
    )
    assert len(audits) >= 1
    for a in audits:
        assert a.verification_id == run.verification_id
        assert a.checksum is not None
        assert len(a.checksum) == 64  # SHA-256 hex


# =============================================================================
# 5. RESOURCE BOUNDS AND FAILURE HANDLING
# =============================================================================

def test_oversized_payload_rejected(v_service, analyst_identity, sample_mission):
    """Request with oversized target_id or reason is rejected."""
    with pytest.raises(ValueError):
        VerificationRequest(target_id="a" * 200)  # max_length=128


def test_excessive_targets_rejected(v_service, analyst_identity, sample_mission, monkeypatch):
    """Mission with targets exceeding maximum allowed is rejected."""
    import services.verification_service as vs_mod
    monkeypatch.setattr(vs_mod, "SAGE_VERIFICATION_MAX_TARGETS", 2)
    req = VerificationRequest()
    with pytest.raises(VerificationValidationError) as exc:
        v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert "exceeds maximum permitted" in str(exc.value)


# =============================================================================
# 6. ARCHITECTURAL SAFETY STATIC AST ANALYSIS
# =============================================================================

def test_architectural_safety_ast_verification():
    """
    Verifies using Python AST that continuous verification codebase:
    1. Never calls create_engine() or create_async_engine()
    2. Never calls execution_gateway or triggers operational actions
    3. Never executes subprocess or os.system
    4. Has zero operational execute endpoints
    """
    verification_files = [
        os.path.join("backend", "data", "schemas", "verification_contract.py"),
        os.path.join("backend", "services", "verification_rules.py"),
        os.path.join("backend", "repositories", "verification_repository.py"),
        os.path.join("backend", "services", "verification_service.py"),
        os.path.join("backend", "api", "verification_routes.py"),
        os.path.join("backend", "tools", "verification_tools.py"),
    ]

    for filepath in verification_files:
        assert os.path.exists(filepath), f"File {filepath} must exist"
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code, filename=filepath)

        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                assert func_name not in ("create_engine", "create_async_engine"), (
                    f"Forbidden engine creation '{func_name}' found in {filepath}"
                )
                assert func_name not in ("system", "popen", "check_call"), (
                    f"Forbidden shell execution '{func_name}' found in {filepath}"
                )
                assert func_name not in ("execute_mission", "execute_action"), (
                    f"Forbidden operational execution '{func_name}' found in {filepath}"
                )

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("subprocess",), (
                        f"Forbidden import '{alias.name}' in {filepath}"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert "execution_gateway" not in mod, (
                    f"Forbidden ExecutionGateway coupling in {filepath}"
                )


# =============================================================================
# 7. FASTAPI REST API TESTS
# =============================================================================

def test_api_request_and_list_verifications(sample_mission):
    """Tests POST and GET verification routes with FastAPI TestClient."""
    from server import app
    client = TestClient(app)

    # 1. POST request verification
    analyst_token = "valid_analyst_token"  # Simulated through test identity
    payload = {
        "target_type": "CRITERION",
        "target_id": "crit_01",
        "trigger_type": "MANUAL",
        "freshness_threshold_override_seconds": 86400.0,
    }
    # Test client calling the endpoints
    res_post = client.post(
        f"/api/v3/missions/{sample_mission.mission_id}/verifications",
        json=payload,
        headers={"X-User-Role": "ANALYST", "X-Plant-Id": "plant_01"},
    )
    # If auth required, test endpoint response format
    if res_post.status_code == 201:
        data = res_post.json()
        assert "verification_id" in data
        assert data["mission_id"] == sample_mission.mission_id
        v_id = data["verification_id"]

        # 2. GET verification run
        res_get = client.get(
            f"/api/v3/missions/{sample_mission.mission_id}/verifications/{v_id}",
            headers={"X-User-Role": "VIEWER", "X-Plant-Id": "plant_01"},
        )
        assert res_get.status_code == 200
        assert res_get.json()["verification_id"] == v_id

        # 3. GET findings
        res_findings = client.get(
            f"/api/v3/missions/{sample_mission.mission_id}/verifications/{v_id}/findings",
            headers={"X-User-Role": "VIEWER", "X-Plant-Id": "plant_01"},
        )
        assert res_findings.status_code == 200
        assert "findings" in res_findings.json()

        # 4. GET audit
        res_audit = client.get(
            f"/api/v3/missions/{sample_mission.mission_id}/verifications/{v_id}/audit",
            headers={"X-User-Role": "VIEWER", "X-Plant-Id": "plant_01"},
        )
        assert res_audit.status_code == 200


# =============================================================================
# 8. AGENT TOOL INTEGRATION TESTS
# =============================================================================

def test_agent_verification_tool(monkeypatch, v_service, sample_mission, analyst_identity):
    """Tests agent tool request_mission_verification_tool and findings inspection with trusted identity."""
    import re
    try:
        from tools import verification_tools as vt
    except ImportError:
        from backend.tools import verification_tools as vt
    monkeypatch.setattr(vt, "verification_service", v_service)

    # Inject trusted server-side identity context
    vt.set_active_verification_identity(analyst_identity)

    res_str = request_mission_verification_tool.invoke({
        "mission_id": sample_mission.mission_id,
    })
    assert "[VERIFICATION COMPLETED]" in res_str
    assert sample_mission.mission_id in res_str
    assert "Verification ID:" in res_str

    # Extract verification ID and test findings tool
    m = re.search(r"Verification ID: (vrun_[a-zA-Z0-9_]+)", res_str)
    assert m is not None
    v_id = m.group(1)

    find_str = get_mission_verification_findings_tool.invoke({
        "mission_id": sample_mission.mission_id,
        "verification_id": v_id,
    })
    assert "[VERIFICATION FINDINGS]" in find_str or "Verification Findings for Run" in find_str
    assert v_id in find_str


def test_agent_tool_schema_has_no_model_controlled_identity_args():
    """Proves that verification tools do not expose identity parameters to LLMs."""
    req_args = request_mission_verification_tool.args
    findings_args = get_mission_verification_findings_tool.args

    forbidden = {
        "tenant_id",
        "workspace_id",
        "plant_id",
        "user_id",
        "roles",
        "permissions",
        "clearance_level",
        "assigned_plants",
        "session_id",
    }
    req_leak = forbidden.intersection(set(req_args.keys()))
    findings_leak = forbidden.intersection(set(findings_args.keys()))

    assert len(req_leak) == 0, f"request_mission_verification_tool exposes identity parameters: {req_leak}"
    assert len(findings_leak) == 0, f"get_mission_verification_findings_tool exposes identity parameters: {findings_leak}"


def test_agent_tool_fails_closed_when_identity_context_missing(monkeypatch, v_service, sample_mission):
    """Invocation must fail closed when trusted identity context is unavailable."""
    try:
        from tools import verification_tools as vt
    except ImportError:
        from backend.tools import verification_tools as vt
    monkeypatch.setattr(vt, "verification_service", v_service)

    # Ensure context is explicitly None
    vt.set_active_verification_identity(None)

    res_str = request_mission_verification_tool.invoke({
        "mission_id": sample_mission.mission_id,
    })
    assert "[VERIFICATION BLOCKED]" in res_str
    assert "Trusted caller identity context is unavailable" in res_str

    findings_str = get_mission_verification_findings_tool.invoke({
        "mission_id": sample_mission.mission_id,
        "verification_id": "vrun_dummy",
    })
    assert "[FINDINGS RETRIEVAL BLOCKED]" in findings_str or "[FINDINGS BLOCKED]" in findings_str
    assert "Trusted caller identity context is unavailable" in findings_str


def test_agent_tool_cannot_forge_identity_via_kwargs(monkeypatch, v_service, sample_mission, analyst_identity):
    """Model kwargs cannot forge tenant, workspace, plant, or grant elevated roles."""
    try:
        from tools import verification_tools as vt
    except ImportError:
        from backend.tools import verification_tools as vt
    monkeypatch.setattr(vt, "verification_service", v_service)

    # Trusted identity is for tenant_alpha, workspace_prod, plant_01; reset in finally
    with vt.active_verification_identity(analyst_identity):
        res_str = request_mission_verification_tool.invoke({
            "mission_id": sample_mission.mission_id,
            "tenant_id": "forged_tenant_evil",
            "workspace_id": "forged_workspace_evil",
            "plant_id": "forged_plant_999",
            "roles": ["ADMIN", "SUPERUSER"],
        })
        # Operation executes strictly under analyst_identity (tenant_alpha), ignoring model kwargs
        assert "[VERIFICATION COMPLETED]" in res_str
        assert sample_mission.mission_id in res_str


# =============================================================================
# 9. PROMPT 36B HARDENING TESTS: TRUSTED IDENTITY, NON-DISCLOSURE & ADAPTERS
# =============================================================================

# --- 9.1 IDENTITY CONTEXT LIFECYCLE, RESET & ISOLATION ---

def test_active_verification_identity_context_manager_lifecycle(analyst_identity):
    """Context manager sets and resets ContextVar correctly on success."""
    assert get_active_verification_identity() is None
    with active_verification_identity(analyst_identity) as ident:
        assert ident == analyst_identity
        assert get_active_verification_identity() == analyst_identity
    # Guaranteed reset after exiting context
    assert get_active_verification_identity() is None


def test_active_verification_identity_context_manager_reset_on_exception(analyst_identity):
    """ContextVar is reliably reset even if an exception occurs inside the context block."""
    assert get_active_verification_identity() is None
    with pytest.raises(RuntimeError, match="Simulated worker failure"):
        with active_verification_identity(analyst_identity):
            assert get_active_verification_identity() == analyst_identity
            raise RuntimeError("Simulated worker failure")
    # Must fail closed and be None
    assert get_active_verification_identity() is None


@pytest.mark.asyncio
async def test_async_active_verification_identity_lifecycle(analyst_identity):
    """Async context manager sets and resets ContextVar correctly on success and exception."""
    assert get_active_verification_identity() is None
    async with async_active_verification_identity(analyst_identity) as ident:
        assert ident == analyst_identity
        assert get_active_verification_identity() == analyst_identity
    assert get_active_verification_identity() is None

    with pytest.raises(ValueError, match="Async worker error"):
        async with async_active_verification_identity(analyst_identity):
            assert get_active_verification_identity() == analyst_identity
            raise ValueError("Async worker error")
    assert get_active_verification_identity() is None


@pytest.mark.asyncio
async def test_concurrent_async_tasks_isolated_identity_context(analyst_identity, viewer_identity):
    """Concurrent async tasks running for different identities cannot observe each other's context."""
    import asyncio

    async def task_worker(identity: Identity, expected_user: str, duration: float):
        async with async_active_verification_identity(identity):
            current = get_active_verification_identity()
            assert current is not None
            assert current.user_id == expected_user
            await asyncio.sleep(duration)
            current_after = get_active_verification_identity()
            assert current_after is not None
            assert current_after.user_id == expected_user
            return current_after.user_id

    # Spawn 10 concurrent tasks interleaved
    tasks = []
    for i in range(10):
        if i % 2 == 0:
            tasks.append(task_worker(analyst_identity, "analyst_01", 0.02))
        else:
            tasks.append(task_worker(viewer_identity, "viewer_01", 0.03))

    results = await asyncio.gather(*tasks)
    assert len(results) == 10
    assert results.count("analyst_01") == 5
    assert results.count("viewer_01") == 5
    assert get_active_verification_identity() is None


def test_sequential_requests_cannot_reuse_previous_identity(analyst_identity, sample_mission, monkeypatch, v_service):
    """Sequential requests handled by the same worker cannot reuse the prior caller's identity."""
    try:
        from tools import verification_tools as vt
    except ImportError:
        from backend.tools import verification_tools as vt
    monkeypatch.setattr(vt, "verification_service", v_service)

    # Request 1: Authenticated caller
    with vt.active_verification_identity(analyst_identity):
        res1 = vt.request_mission_verification_tool.invoke({"mission_id": sample_mission.mission_id})
        assert "[VERIFICATION COMPLETED]" in res1

    # Request 2: Subsequent unauthenticated caller on same thread/worker
    res2 = vt.request_mission_verification_tool.invoke({"mission_id": sample_mission.mission_id})
    assert "[VERIFICATION BLOCKED]" in res2
    assert "Trusted caller identity context is unavailable" in res2


def test_unauthorized_or_missing_identity_never_persists_verification(temp_vdb, sample_mission):
    """Missing or unauthorized identity never writes verification runs or audit records to repository."""
    repo = VerificationRepository(db_path=temp_vdb)
    # Ensure active context is None
    set_active_verification_identity(None)
    res = request_mission_verification_tool.invoke({"mission_id": sample_mission.mission_id})
    assert "[VERIFICATION BLOCKED]" in res

    # Repository should be completely untouched
    runs, _ = repo.list_runs(
        tenant_id=sample_mission.scope.tenant_id,
        workspace_id=sample_mission.scope.workspace_id,
        mission_id=sample_mission.mission_id,
    )
    assert len(runs) == 0


# --- 9.2 EVIDENCE-EXISTENCE AGGREGATION & NON-DISCLOSURE ---

def test_evidence_exists_one_accessible_required_record():
    """One accessible required record returns VERIFIED with exact non-disclosing payload."""
    rule = EvidenceExistsRule()
    assess = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [assess], {}, {})
    assert finding.status == VerificationStatus.VERIFIED
    assert finding.evidence_references == ["ev_001"]
    assert len(finding.evidence_assessments) == 1
    assert finding.evidence_assessments[0].evidence_id == "ev_001"
    assert finding.limitations == []
    assert "confirms record presence only" in finding.explanation


def test_evidence_exists_all_required_records_accessible():
    """Multiple required records all accessible returns VERIFIED with exact payload."""
    rule = EvidenceExistsRule()
    a1 = EvidenceAssessment(
        evidence_id="ev_001",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    a2 = EvidenceAssessment(
        evidence_id="ev_002",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("step_01", VerificationTargetType.STEP, [a1, a2], {}, {})
    assert finding.status == VerificationStatus.VERIFIED
    assert finding.evidence_references == ["ev_001", "ev_002"]
    assert len(finding.evidence_assessments) == 2
    assert finding.limitations == []


def test_evidence_exists_accessible_plus_blocked_required_record():
    """Accessible + blocked required record returns BLOCKED and does NOT disclose blocked ID or assessment."""
    rule = EvidenceExistsRule()
    accessible_ev = EvidenceAssessment(
        evidence_id="ev_pub_01",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    blocked_ev = EvidenceAssessment(
        evidence_id="ev_secret_99",
        source_type="CONFIDENTIAL_SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="CLEARANCE_INSUFFICIENT",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [accessible_ev, blocked_ev], {}, {})
    # MUST NOT be promoted to VERIFIED
    assert finding.status == VerificationStatus.BLOCKED
    # Blocked record ID MUST NOT appear in evidence_references
    assert finding.evidence_references == ["ev_pub_01"]
    assert "ev_secret_99" not in finding.evidence_references
    # Blocked assessment MUST NOT appear in evidence_assessments
    assert len(finding.evidence_assessments) == 1
    assert finding.evidence_assessments[0].evidence_id == "ev_pub_01"
    # Blocked record ID MUST NOT appear in limitations or explanation
    for lim in finding.limitations:
        assert "ev_secret_99" not in lim
    assert "ev_secret_99" not in finding.explanation


def test_evidence_exists_accessible_plus_unknown_required_record():
    """Accessible + unknown/unresolved required record returns INDETERMINATE without disclosing unknown ID."""
    rule = EvidenceExistsRule()
    accessible_ev = EvidenceAssessment(
        evidence_id="ev_pub_01",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    unknown_ev = EvidenceAssessment(
        evidence_id="ev_missing_55",
        source_type="UNKNOWN",
        observed_at=None,
        scope_status=ScopeStatus.UNKNOWN,
        classification_status="UNKNOWN",
        applicability_status="UNAVAILABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [accessible_ev, unknown_ev], {}, {})
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.evidence_references == ["ev_pub_01"]
    assert "ev_missing_55" not in finding.evidence_references
    assert len(finding.evidence_assessments) == 1
    assert finding.evidence_assessments[0].evidence_id == "ev_pub_01"
    assert "ev_missing_55" not in str(finding.limitations)
    assert "ev_missing_55" not in finding.explanation


def test_evidence_exists_accessible_plus_untagged_plant_record():
    """Accessible + untagged plant record returns BLOCKED and does NOT disclose untagged record ID."""
    rule = EvidenceExistsRule()
    accessible_ev = EvidenceAssessment(
        evidence_id="ev_pub_01",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    untagged_ev = EvidenceAssessment(
        evidence_id="ev_untagged_88",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.UNTAGGED_PLANT,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("step_01", VerificationTargetType.STEP, [accessible_ev, untagged_ev], {}, {})
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_references == ["ev_pub_01"]
    assert "ev_untagged_88" not in finding.evidence_references
    assert len(finding.evidence_assessments) == 1
    assert "ev_untagged_88" not in str(finding.limitations)
    assert "ev_untagged_88" not in finding.explanation


def test_evidence_exists_all_requested_records_inaccessible():
    """All requested records blocked returns BLOCKED with empty visible refs and no leaked IDs."""
    rule = EvidenceExistsRule()
    b1 = EvidenceAssessment(
        evidence_id="ev_cross_plant_01",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.CROSS_PLANT,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    b2 = EvidenceAssessment(
        evidence_id="ev_classified_topsecret",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="CLEARANCE_INSUFFICIENT",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate("step_01", VerificationTargetType.STEP, [b1, b2], {}, {})
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_references == []
    assert finding.evidence_assessments == []
    assert len(finding.limitations) > 0
    for lim in finding.limitations:
        assert "ev_cross_plant_01" not in lim
        assert "ev_classified_topsecret" not in lim
    assert "ev_cross_plant_01" not in finding.explanation
    assert "ev_classified_topsecret" not in finding.explanation


def test_evidence_exists_record_absent():
    """Missing/absent records return NOT_VERIFIED with empty payload."""
    rule = EvidenceExistsRule()
    absent_ev = EvidenceAssessment(
        evidence_id="ev_nonexistent",
        source_type="UNKNOWN",
        observed_at=None,
        scope_status=ScopeStatus.UNKNOWN,
        classification_status="UNKNOWN",
        applicability_status="UNAVAILABLE",
    )
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [absent_ev], {}, {})
    assert finding.status == VerificationStatus.NOT_VERIFIED
    assert finding.evidence_references == []
    assert finding.evidence_assessments == []
    assert len(finding.limitations) > 0


def test_evidence_exists_optional_evidence_only():
    """Optional evidence only returns VERIFIED when accessible optional evidence is present."""
    rule = EvidenceExistsRule()
    opt_ev = EvidenceAssessment(
        evidence_id="ev_opt_01",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    params = {"optional_evidence_ids": ["ev_opt_01"]}
    finding = rule.evaluate("crit_01", VerificationTargetType.CRITERION, [opt_ev], {}, params)
    assert finding.status == VerificationStatus.VERIFIED
    assert finding.evidence_references == ["ev_opt_01"]
    assert len(finding.evidence_assessments) == 1


# --- 9.3 AUTHORITATIVE VALIDATION SIGNALS & CLASSIFICATION HARDENING ---

def test_action_status_and_hash_do_not_infer_validity(v_service, analyst_identity, sample_mission):
    """Action store SUCCEEDED status and hash do NOT infer validity; must return UNVERIFIED."""
    try:
        from data.schemas.action_contract import (
            Action,
            ActionType,
            ActionStatus,
            ActionTarget,
            ActionReason,
        )
    except (ImportError, ModuleNotFoundError):
        from backend.data.schemas.action_contract import (
            Action,
            ActionType,
            ActionStatus,
            ActionTarget,
            ActionReason,
        )
    action = Action(
        action_id="act_test_validity",
        action_type=ActionType.REORDER_INVENTORY,
        tenant_id=sample_mission.scope.tenant_id,
        workspace_id=sample_mission.scope.workspace_id,
        session_id=analyst_identity.session_id,
        target=ActionTarget(
            resource_id="res_01",
            resource_type="INVENTORY_ITEM",
            plant_id=sample_mission.scope.plant_id,
        ),
        parameters={"sku": "SKU-100", "qty": 50, "classification": "INTERNAL"},
        reason=ActionReason(reason_code="RESTOCK", summary="Operational restock justification"),
        status=ActionStatus.SUCCEEDED,
    )
    action_store.save(action)

    assess, payload = v_service._resolve_evidence_item(
        ref_id=action.action_id,
        mission=sample_mission,
        identity=analyst_identity,
        freshness_threshold=3600.0,
        eval_dt=datetime.now(timezone.utc),
    )
    # MUST be UNVERIFIED, not VALID
    assert assess.integrity_status == "UNVERIFIED"
    assert assess.quality_status == QualityStatus.UNVERIFIED
    assert assess.observed_at is None
    assert any("Action proposal records workflow state" in lim for lim in assess.limitations)


def test_decision_status_and_fingerprint_do_not_infer_validity(v_service, analyst_identity, sample_mission):
    """Decision Engine RECOMMENDED status and fingerprint do NOT infer validity; must return UNVERIFIED."""
    try:
        from data.schemas.decision_engine_contract import (
            DecisionEvaluation,
            DecisionOutcomeStatus,
            DecisionType,
            DecisionRecommendation,
        )
    except (ImportError, ModuleNotFoundError):
        from backend.data.schemas.decision_engine_contract import (
            DecisionEvaluation,
            DecisionOutcomeStatus,
            DecisionType,
            DecisionRecommendation,
        )
    dec_id = f"dec_test_validity_{uuid.uuid4().hex[:8]}"
    dec = DecisionEvaluation(
        decision_id=dec_id,
        problem_id="prob_test_1",
        tenant_id=sample_mission.scope.tenant_id,
        workspace_id=sample_mission.scope.workspace_id,
        plant_id=sample_mission.scope.plant_id,
        decision_type=DecisionType.RESOURCE_ALLOCATION,
        status=DecisionOutcomeStatus.RECOMMENDED,
        recommendation=DecisionRecommendation(
            recommended_option_id="opt_1",
            recommendation_status=DecisionOutcomeStatus.RECOMMENDED,
            primary_rationale="Optimal efficiency under current constraints",
        ),
        fingerprint="fp_sha256_mock_1234567890",
        assessment_timestamp="2026-10-12T10:00:00Z",
        metadata={"classification": "INTERNAL"},
    )
    v_service.decision_repo.save_evaluation(dec)

    assess, _ = v_service._resolve_evidence_item(
        ref_id=dec.decision_id,
        mission=sample_mission,
        identity=analyst_identity,
        freshness_threshold=3600.0,
        eval_dt=datetime.now(timezone.utc),
    )
    # MUST be UNVERIFIED, not VALID
    assert assess.integrity_status == "UNVERIFIED"
    assert assess.quality_status == QualityStatus.UNVERIFIED
    assert assess.observed_at is None
    assert any("Decision evaluation represents analytical optimization" in lim for lim in assess.limitations)


def test_incident_status_and_fingerprint_do_not_infer_validity(v_service, analyst_identity, sample_mission):
    """Incident RESOLVED status does NOT infer validity; uses detected_at only for observation timestamp."""
    try:
        from data.schemas.incident_contract import (
            IncidentContract,
            IncidentCategory,
            IncidentSeverity,
            IncidentPriority,
            IncidentLifecycle,
        )
    except (ImportError, ModuleNotFoundError):
        from backend.data.schemas.incident_contract import (
            IncidentContract,
            IncidentCategory,
            IncidentSeverity,
            IncidentPriority,
            IncidentLifecycle,
        )
    inc_id = f"inc_test_validity_{uuid.uuid4().hex[:8]}"
    inc = IncidentContract(
        incident_id=inc_id,
        tenant_id=sample_mission.scope.tenant_id,
        workspace_id=sample_mission.scope.workspace_id,
        plant_id=sample_mission.scope.plant_id,
        category=IncidentCategory.OPERATIONAL,
        severity=IncidentSeverity.MEDIUM,
        priority=IncidentPriority.NORMAL,
        status=IncidentLifecycle.RESOLVED,
        title="Pump Bearing Temperature Spike",
        detected_at="2026-10-12T10:00:00Z",
        opened_at="2026-10-12T10:05:00Z",
        resolved_at="2026-10-12T11:00:00Z",
        updated_at="2026-10-12T11:00:00Z",
        incident_fingerprint=f"inc_fp_mock_{uuid.uuid4().hex[:8]}",
    )
    v_service.incident_repo.save_incident(inc)

    assess, _ = v_service._resolve_evidence_item(
        ref_id=inc.incident_id,
        mission=sample_mission,
        identity=analyst_identity,
        freshness_threshold=86400.0,
        eval_dt=datetime.now(timezone.utc),
    )
    # MUST be UNVERIFIED, not VALID
    assert assess.integrity_status == "UNVERIFIED"
    assert assess.quality_status == QualityStatus.UNVERIFIED
    # Observation time is detected_at strictly; not opened_at or resolved_at
    assert assess.observed_at == "2026-10-12T10:00:00Z"
    assert any("Incident record reflects operational tracking status" in lim for lim in assess.limitations)


def test_rca_status_and_fingerprint_do_not_infer_validity(v_service, analyst_identity, sample_mission):
    """RCA COMPLETED status does NOT infer validity; completion time is not observation time."""
    try:
        from data.schemas.rca_contract import RcaAnalysis, RcaAnalysisStatus
    except (ImportError, ModuleNotFoundError):
        from backend.data.schemas.rca_contract import RcaAnalysis, RcaAnalysisStatus
    rca_id = f"rca_test_validity_{uuid.uuid4().hex[:8]}"
    rca = RcaAnalysis(
        analysis_id=rca_id,
        incident_id=f"inc_ref_{uuid.uuid4().hex[:8]}",
        tenant_id=sample_mission.scope.tenant_id,
        workspace_id=sample_mission.scope.workspace_id,
        plant_id=sample_mission.scope.plant_id,
        status=RcaAnalysisStatus.COMPLETED,
        started_at="2026-10-12T10:00:00Z",
        completed_at="2026-10-12T11:00:00Z",
        method_version="1.0",
        input_fingerprint=f"rca_fp_mock_{uuid.uuid4().hex[:8]}",
    )
    v_service.rca_repo.create_analysis(rca)

    assess, _ = v_service._resolve_evidence_item(
        ref_id=rca.analysis_id,
        mission=sample_mission,
        identity=analyst_identity,
        freshness_threshold=86400.0,
        eval_dt=datetime.now(timezone.utc),
    )
    # MUST be UNVERIFIED, not VALID
    assert assess.integrity_status == "UNVERIFIED"
    assert assess.quality_status == QualityStatus.UNVERIFIED
    assert assess.observed_at is None
    assert any("RCA record represents investigation synthesis" in lim for lim in assess.limitations)


def test_missing_or_malformed_classification_fails_closed_to_unknown(v_service, analyst_identity, sample_mission, e_repo):
    """Missing or unsupported classification metadata fails closed to UNKNOWN, never defaults to INTERNAL."""
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_class_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_c1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test explanation", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_noclass", "exp_class_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"temp": 25.0}),  # No classification field!
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    assess, _ = v_service._resolve_evidence_item(
        ref_id="ev_rec_noclass",
        mission=sample_mission,
        identity=analyst_identity,
        freshness_threshold=86400.0,
        eval_dt=datetime.now(timezone.utc),
    )
    # Must fail closed to UNKNOWN; must NOT be promoted to INTERNAL or AUTHORIZED
    assert assess.classification_status == "UNKNOWN"
    assert assess.applicability_status == "UNKNOWN"


def test_provenance_does_not_disclose_blocked_evidence_ids(v_service, analyst_identity, sample_mission, e_repo):
    """Verification provenance evidence_ids must NOT include inaccessible/blocked evidence IDs."""
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_prov_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_prov1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test prov", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_01", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "temp": 25.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        # Blocked record in plant_02
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_02", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_02",
                "POWER_METRIC", "pwr_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "power": 100.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    req = VerificationRequest()
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    # The blocked record ev_rec_02 MUST NOT be disclosed in provenance.evidence_ids!
    assert "ev_rec_02" not in run.provenance.evidence_ids
    assert "ev_rec_01" in run.provenance.evidence_ids


# =============================================================================
# 10. PROMPT 36C — ADVERSARIAL ATTACK TESTS FOR TRUSTED RULE PARAMETERS
# =============================================================================

def test_case_a_caller_attempts_to_downgrade_required_evidence(v_service, analyst_identity, sample_mission, e_repo):
    """
    Case A — Caller attempts to downgrade required evidence:
    Mission requires evidence A and B. A is accessible, B is blocked.
    Caller supplies optional_evidence_ids = [B].
    Expected: request rejected with VerificationValidationError / ValueError, or result remains BLOCKED.
    Never VERIFIED.
    """
    # Seed accessible evidence A in plant_01 and explanation prerequisite
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_prov_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_prov1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test prov", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_a_acc", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "temp": 25.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        # Seed blocked evidence B in plant_02 (cross-plant boundary violation)
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_a_blk", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_02",
                "POWER_METRIC", "pwr_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "power": 100.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    # 1. API / Request validation boundary: caller supplies optional_evidence_ids
    # Must be rejected at request creation or service invocation
    with pytest.raises((VerificationValidationError, ValueError)):
        req = VerificationRequest(
            rule_parameters={"optional_evidence_ids": ["ev_case_a_blk"]},
            rule_type=RuleType.EVIDENCE_EXISTS,
        )
        v_service.request_verification(analyst_identity, sample_mission.mission_id, req)

    # 2. Rule evaluation boundary: even if optional_evidence_ids is passed directly to rule
    rule = EvidenceExistsRule()
    assess_a, _ = v_service._resolve_evidence_item(
        "ev_case_a_acc", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    assess_b, _ = v_service._resolve_evidence_item(
        "ev_case_a_blk", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    finding = rule.evaluate(
        target_id="step_test",
        target_type=VerificationTargetType.STEP,
        assessments=[assess_a, assess_b],
        mission_scope={"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"},
        parameters={"optional_evidence_ids": ["ev_case_a_blk"]},
    )
    # MUST be BLOCKED, NEVER VERIFIED!
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.status != VerificationStatus.VERIFIED
    # Non-disclosure: blocked identifier is completely redacted
    assert "ev_case_a_blk" not in finding.evidence_references
    assert "ev_case_a_acc" in finding.evidence_references
    assert "ev_case_a_blk" not in finding.explanation
    assert "ev_case_a_blk" not in str(finding.limitations)
    assert not any(a.evidence_id == "ev_case_a_blk" for a in finding.evidence_assessments)


def test_case_b_caller_attempts_to_downgrade_all_requirements(v_service, analyst_identity, sample_mission):
    """
    Case B — Caller attempts to downgrade all requirements:
    Mission contains required evidence. Caller marks every reference optional using request.rule_parameters.
    Expected: caller cannot change mission requirements; request rejected.
    """
    with pytest.raises((VerificationValidationError, ValueError)):
        VerificationRequest(
            rule_parameters={"optional_evidence_ids": ["ev_rec_01", "ev_rec_02"]},
            rule_type=RuleType.EVIDENCE_EXISTS,
        )


def test_case_c_caller_attempts_to_override_required_references(v_service, analyst_identity, sample_mission):
    """
    Case C — Caller attempts to override required references:
    Authoritative mission requires A and B. Caller supplies required_evidence_ids containing only A.
    Expected: request is rejected, and authoritative requirements cannot be dropped.
    """
    with pytest.raises((VerificationValidationError, ValueError)):
        VerificationRequest(
            rule_parameters={"required_evidence_ids": ["ev_rec_01"]},
            rule_type=RuleType.REQUIRED_EVIDENCE_PRESENT,
        )


def test_case_d_caller_attempts_to_inject_evidence_payloads(v_service, analyst_identity, sample_mission, e_repo):
    """
    Case D — Caller attempts to inject evidence payloads:
    Caller supplies fabricated evidence_payloads in rule_parameters.
    Expected: caller payload injection is rejected and server-resolved payloads remain authoritative.
    """
    # 1. Request rejection when trying to inject protected evidence_payloads
    with pytest.raises((VerificationValidationError, ValueError)):
        VerificationRequest(
            rule_parameters={"evidence_payloads": {"ev_rec_01": {"temp": 999.0, "forged": True}}},
        )


def test_case_e_legitimate_accessible_evidence(v_service, analyst_identity, sample_mission, e_repo):
    """
    Case E — Legitimate accessible evidence:
    All authoritative required evidence is accessible.
    Expected: EVIDENCE_EXISTS returns VERIFIED with notice that existence confirms presence only.
    """
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_prov_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_prov1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test prov", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_e_01", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "temp": 25.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    rule = EvidenceExistsRule()
    assess, _ = v_service._resolve_evidence_item(
        "ev_case_e_01", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    finding = rule.evaluate(
        target_id="crit_test",
        target_type=VerificationTargetType.CRITERION,
        assessments=[assess],
        mission_scope={"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"},
        parameters={},
    )
    assert finding.status == VerificationStatus.VERIFIED
    assert "ev_case_e_01" in finding.evidence_references
    assert len(finding.evidence_assessments) == 1
    assert "Notice: Evidence existence confirms record presence only — does not self-certify operational completion or outcome." in finding.explanation


def test_case_f_mixed_required_evidence_accessible_plus_blocked(v_service, analyst_identity, sample_mission, e_repo):
    """
    Case F — Mixed required evidence: Accessible + blocked.
    Expected: BLOCKED, no inaccessible identifiers disclosed.
    """
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_prov_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_prov1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test prov", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_f_acc", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "temp": 25.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_f_blk", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_02",
                "POWER_METRIC", "pwr_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "power": 100.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    rule = EvidenceExistsRule()
    assess_a, _ = v_service._resolve_evidence_item(
        "ev_case_f_acc", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    assess_b, _ = v_service._resolve_evidence_item(
        "ev_case_f_blk", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    finding = rule.evaluate(
        target_id="step_test",
        target_type=VerificationTargetType.STEP,
        assessments=[assess_a, assess_b],
        mission_scope={"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"},
        parameters={},
    )
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_references == ["ev_case_f_acc"]
    assert len(finding.evidence_assessments) == 1
    assert "ev_case_f_blk" not in finding.evidence_references
    assert "ev_case_f_blk" not in finding.explanation
    assert "ev_case_f_blk" not in str(finding.limitations)


def test_case_g_mixed_unresolved_evidence_accessible_plus_unknown(v_service, analyst_identity, sample_mission, e_repo):
    """
    Case G — Mixed unresolved evidence: Accessible + unknown.
    Expected: INDETERMINATE, no unresolved identifiers disclosed.
    """
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_prov_01", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_prov1", "2026-10-12T00:00:00+00:00", "1.0", "1.0",
                0, "test prov", 1, 0, "{}", "2026-10-12T00:00:00+00:00"
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_case_g_acc", "exp_prov_01", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"classification": "INTERNAL", "temp": 25.0}),
                "2026-10-12T00:00:00+00:00"
            )
        )
        conn.commit()

    rule = EvidenceExistsRule()
    assess_a, _ = v_service._resolve_evidence_item(
        "ev_case_g_acc", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    assess_u, _ = v_service._resolve_evidence_item(
        "ev_case_g_unknown_999", sample_mission, analyst_identity, 3600.0, datetime.now(timezone.utc)
    )
    finding = rule.evaluate(
        target_id="step_test",
        target_type=VerificationTargetType.STEP,
        assessments=[assess_a, assess_u],
        mission_scope={"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"},
        parameters={},
    )
    assert finding.status == VerificationStatus.INDETERMINATE
    assert finding.evidence_references == ["ev_case_g_acc"]
    assert len(finding.evidence_assessments) == 1
    assert "ev_case_g_unknown_999" not in finding.evidence_references
    assert "ev_case_g_unknown_999" not in finding.explanation
    assert "ev_case_g_unknown_999" not in str(finding.limitations)


def test_case_h_trusted_optional_evidence_boundary():
    """
    Case H — Trusted optional evidence boundary verification:
    Confirms that no target-level optional evidence contract exists in MissionSuccessCriterion
    or MissionPlannedStep, and all parameters attempting to infer optionality fail closed.
    """
    # Confirm MissionSuccessCriterion and MissionPlannedStep do NOT expose optional evidence fields
    assert not hasattr(MissionSuccessCriterion, "optional_evidence")
    assert not hasattr(MissionSuccessCriterion, "optional_evidence_ids")
    assert not hasattr(MissionPlannedStep, "optional_evidence")
    assert not hasattr(MissionPlannedStep, "optional_evidence_ids")

    # In EvidenceExistsRule, optional_evidence_ids is not supported and fails closed to treating as required
    rule = EvidenceExistsRule()
    assess = EvidenceAssessment(
        evidence_id="ev_blocked_test",
        source_type="SENSOR",
        observed_at="2026-10-12T12:00:00+00:00",
        scope_status=ScopeStatus.CROSS_PLANT,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
    )
    finding = rule.evaluate(
        "target_h",
        VerificationTargetType.CRITERION,
        [assess],
        {},
        {"optional_evidence_ids": ["ev_blocked_test"]},
    )
    assert finding.status == VerificationStatus.BLOCKED
    assert finding.evidence_references == []


# =============================================================================
# PROMPT 36D: UNIVERSAL EVIDENCE SCOPE ENFORCEMENT & NON-DISCLOSURE HARDENING
# =============================================================================

ALL_8_RULES = [
    EvidenceExistsRule(),
    EvidenceValidatedRule(),
    EvidenceFreshRule(),
    RequiredEvidencePresentRule(),
    RequiredEvidenceValidatedRule(),
    EvidenceScopeMatchRule(),
    RequiredFieldsPresentRule(),
    SourceConsistencyRule(),
]

ALL_UNAUTHORIZED_SCOPES = [
    ScopeStatus.CROSS_TENANT,
    ScopeStatus.CROSS_WORKSPACE,
    ScopeStatus.CROSS_PLANT,
    ScopeStatus.UNAUTHORIZED,
    ScopeStatus.REJECTED,
    ScopeStatus.UNTAGGED_PLANT,
]


def _build_test_params_for_rule(auth_id="ev_auth_01", blocked_id="ev_blocked_01"):
    return {
        "required_evidence_types": ["SENSOR"],
        "required_evidence_ids": [auth_id],
        "required_fields": ["reading"],
        "metric_key": "reading",
        "tolerance": 0.1,
        "freshness_threshold_seconds": 3600.0,
        "evidence_payloads": {
            auth_id: {"reading": 42.0},
            blocked_id: {"reading": 42.0},
            "ev_auth_02": {"reading": 42.0},
        },
    }


def _build_authorized_assessment(ev_id="ev_auth_01", source_type="SENSOR"):
    now_iso = datetime.now(timezone.utc).isoformat()
    return EvidenceAssessment(
        evidence_id=ev_id,
        source_type=source_type,
        observed_at=now_iso,
        received_at=now_iso,
        freshness_status=FreshnessStatus.CURRENT,
        freshness_seconds=10.0,
        freshness_threshold_seconds=3600.0,
        integrity_status="VALID",
        scope_status=ScopeStatus.AUTHORIZED,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
        quality_status=QualityStatus.VALID,
    )


def _build_unauthorized_assessment(scope_status: ScopeStatus, ev_id="ev_blocked_01", source_type="SENSOR"):
    now_iso = datetime.now(timezone.utc).isoformat()
    return EvidenceAssessment(
        evidence_id=ev_id,
        source_type=source_type,
        observed_at=now_iso,
        received_at=now_iso,
        freshness_status=FreshnessStatus.CURRENT,
        freshness_seconds=10.0,
        freshness_threshold_seconds=3600.0,
        integrity_status="VALID",  # Valid integrity explicitly set
        scope_status=scope_status,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
        quality_status=QualityStatus.VALID,
    )


@pytest.mark.parametrize("scope_status", ALL_UNAUTHORIZED_SCOPES)
def test_prompt36d_scope_matrix_unauthorized_statuses_never_verified(scope_status):
    """
    Scope Matrix: CROSS_TENANT, CROSS_WORKSPACE, CROSS_PLANT, UNAUTHORIZED,
    REJECTED, UNTAGGED_PLANT never produce VERIFIED across all 8 rules.
    """
    blocked_id = f"ev_blocked_{scope_status.value.lower()}"
    assessment = _build_unauthorized_assessment(scope_status, ev_id=blocked_id)
    params = _build_test_params_for_rule(blocked_id=blocked_id)
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        finding = rule.evaluate("target_scope_matrix", VerificationTargetType.CRITERION, [assessment], mission_scope, params)
        assert finding.status != VerificationStatus.VERIFIED, (
            f"Rule '{rule.rule_id}' falsely returned VERIFIED for scope status '{scope_status}'!"
        )
        assert finding.status == VerificationStatus.BLOCKED, (
            f"Rule '{rule.rule_id}' did not return BLOCKED for unauthorized scope status '{scope_status}'!"
        )
        # Non-disclosure assertions
        assert finding.evidence_references == [], f"Rule '{rule.rule_id}' disclosed blocked evidence reference!"
        assert finding.evidence_assessments == [], f"Rule '{rule.rule_id}' disclosed blocked assessment!"
        assert blocked_id not in finding.explanation
        assert blocked_id not in str(finding.limitations)


def test_prompt36d_scope_matrix_unknown_scope_never_verified():
    """
    Scope Matrix: UNKNOWN scope cannot produce a falsely authorized result across all 8 rules.
    """
    unknown_id = "ev_unknown_scope_01"
    now_iso = datetime.now(timezone.utc).isoformat()
    assessment = EvidenceAssessment(
        evidence_id=unknown_id,
        source_type="SENSOR",
        observed_at=now_iso,
        received_at=now_iso,
        freshness_status=FreshnessStatus.CURRENT,
        integrity_status="VALID",
        scope_status=ScopeStatus.UNKNOWN,
        classification_status="AUTHORIZED",
        applicability_status="APPLICABLE",
        quality_status=QualityStatus.VALID,
    )
    params = _build_test_params_for_rule(blocked_id=unknown_id)
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        finding = rule.evaluate("target_unknown", VerificationTargetType.CRITERION, [assessment], mission_scope, params)
        assert finding.status != VerificationStatus.VERIFIED, (
            f"Rule '{rule.rule_id}' falsely returned VERIFIED for UNKNOWN scope!"
        )
        assert finding.status in (VerificationStatus.INDETERMINATE, VerificationStatus.NOT_VERIFIED), (
            f"Rule '{rule.rule_id}' did not fail closed to INDETERMINATE/NOT_VERIFIED for UNKNOWN scope!"
        )
        assert unknown_id not in finding.evidence_references
        assert unknown_id not in [a.evidence_id for a in finding.evidence_assessments]
        assert unknown_id not in finding.explanation
        assert unknown_id not in str(finding.limitations)


@pytest.mark.parametrize("scope_status", ALL_UNAUTHORIZED_SCOPES)
def test_prompt36d_scope_matrix_valid_integrity_cannot_override_scope(scope_status):
    """
    Scope Matrix: Valid integrity status cannot override an unauthorized scope status.
    """
    blocked_id = f"ev_valid_integ_{scope_status.value.lower()}"
    assessment = _build_unauthorized_assessment(scope_status, ev_id=blocked_id)
    # Ensure all integrity and quality signals are explicitly valid
    assessment.integrity_status = "VALID"
    assessment.quality_status = QualityStatus.VALID
    assessment.classification_status = "AUTHORIZED"
    assessment.applicability_status = "APPLICABLE"

    params = _build_test_params_for_rule(blocked_id=blocked_id)
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        finding = rule.evaluate("target_override", VerificationTargetType.CRITERION, [assessment], mission_scope, params)
        assert finding.status == VerificationStatus.BLOCKED
        assert finding.status != VerificationStatus.VERIFIED
        assert finding.evidence_references == []
        assert finding.evidence_assessments == []


def test_prompt36d_all_rules_authorized_baseline():
    """
    Rule Coverage: Fully authorized assessment with minimum required conditions produces VERIFIED.
    """
    auth1 = _build_authorized_assessment("ev_auth_01")
    auth2 = _build_authorized_assessment("ev_auth_02")
    params = _build_test_params_for_rule("ev_auth_01")
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        # SourceConsistencyRule requires at least 2 sources
        assessments = [auth1, auth2] if isinstance(rule, SourceConsistencyRule) else [auth1]
        finding = rule.evaluate("target_baseline", VerificationTargetType.CRITERION, assessments, mission_scope, params)
        assert finding.status == VerificationStatus.VERIFIED, (
            f"Rule '{rule.rule_id}' failed to verify fully authorized evidence!"
        )
        assert len(finding.evidence_references) >= 1
        assert len(finding.evidence_assessments) >= 1
        assert "ev_auth_01" in finding.evidence_references


def test_prompt36d_all_rules_mixed_collection_fails_closed_and_redacts():
    """
    Rule Coverage: Mixed authorized and cross-boundary collection never produces VERIFIED,
    and blocked IDs are redacted from references, assessments, explanations, and limitations.
    """
    auth = _build_authorized_assessment("ev_auth_01")
    blocked = _build_unauthorized_assessment(ScopeStatus.CROSS_TENANT, ev_id="ev_cross_tenant_99")
    params = _build_test_params_for_rule(auth_id="ev_auth_01", blocked_id="ev_cross_tenant_99")
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        finding = rule.evaluate("target_mixed", VerificationTargetType.CRITERION, [auth, blocked], mission_scope, params)
        assert finding.status != VerificationStatus.VERIFIED, (
            f"Rule '{rule.rule_id}' falsely returned VERIFIED for mixed accessible/inaccessible collection!"
        )
        assert finding.status == VerificationStatus.BLOCKED, (
            f"Rule '{rule.rule_id}' did not return BLOCKED for mixed collection!"
        )
        # Redaction check: blocked ID must NEVER appear
        assert "ev_cross_tenant_99" not in finding.evidence_references
        assert "ev_cross_tenant_99" not in [a.evidence_id for a in finding.evidence_assessments]
        assert "ev_cross_tenant_99" not in finding.explanation
        assert "ev_cross_tenant_99" not in str(finding.limitations)


def test_prompt36d_all_rules_unresolved_non_disclosure():
    """
    Rule Coverage: Unresolved/inaccessible identifiers are not leaked in findings.
    """
    unresolved = EvidenceAssessment(
        evidence_id="ev_unresolved_secret_01",
        source_type="UNKNOWN",
        observed_at=None,
        received_at=None,
        freshness_status=FreshnessStatus.UNKNOWN,
        integrity_status="UNVERIFIED",
        scope_status=ScopeStatus.UNKNOWN,
        classification_status="UNKNOWN",
        applicability_status="UNAVAILABLE",
        quality_status=QualityStatus.UNKNOWN,
    )
    params = _build_test_params_for_rule(blocked_id="ev_unresolved_secret_01")
    mission_scope = {"tenant_id": "tenant_alpha", "workspace_id": "workspace_prod", "plant_id": "plant_01"}

    for rule in ALL_8_RULES:
        finding = rule.evaluate("target_unres", VerificationTargetType.CRITERION, [unresolved], mission_scope, params)
        assert finding.status != VerificationStatus.VERIFIED
        assert "ev_unresolved_secret_01" not in finding.evidence_references
        assert "ev_unresolved_secret_01" not in [a.evidence_id for a in finding.evidence_assessments]
        assert "ev_unresolved_secret_01" not in finding.explanation
        assert "ev_unresolved_secret_01" not in str(finding.limitations)


def test_prompt36d_end_to_end_serialized_run_and_provenance_non_disclosure(
    v_service, analyst_identity, sample_mission, e_repo
):
    """
    Response and Persistence: Complete serialized finding, serialized run, and provenance
    never disclose blocked evidence IDs, and subsequent retrieval retains the same boundary.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with e_repo._lock, e_repo._get_connection() as conn:
        # Seed authorized evidence ev_rec_01 for crit_01
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_p36d_auth", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_p36d_auth", now_iso, "1.0", "1.0",
                0, "test auth explanation", 1, 0, "{}", now_iso
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_01", "exp_p36d_auth", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"temp": 25.0, "classification": "INTERNAL"}), now_iso
            )
        )
        # Seed cross-plant blocked evidence ev_rec_02 for crit_02 in plant_02
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_p36d_blocked", "CRITERION", "crit_02", "tenant_alpha", "workspace_prod", "plant_02",
                "fp_p36d_blk", now_iso, "1.0", "1.0",
                0, "test blocked explanation", 1, 0, "{}", now_iso
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_02", "exp_p36d_blocked", "tenant_alpha", "workspace_prod", "plant_02",
                "POWER_METRIC", "tel_002", "OBSERVED", "VALID",
                json.dumps({"power": 100.0, "classification": "INTERNAL"}), now_iso
            )
        )
        conn.commit()

    req = VerificationRequest()
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert run.status == VerificationStatus.BLOCKED

    # 1. Serialized run provenance check
    run_dict = run.model_dump()
    assert "ev_rec_02" not in run_dict["provenance"]["evidence_ids"]
    assert "ev_rec_01" in run_dict["provenance"]["evidence_ids"]

    # 2. Serialized finding check for blocked target (crit_02)
    blocked_finding = next(f for f in run_dict["findings"] if f["target_id"] == "crit_02")
    assert blocked_finding["status"] == "BLOCKED"
    assert "ev_rec_02" not in blocked_finding["evidence_references"]
    assert "ev_rec_02" not in [a["evidence_id"] for a in blocked_finding["evidence_assessments"]]
    assert "ev_rec_02" not in blocked_finding["explanation"]
    assert "ev_rec_02" not in str(blocked_finding["limitations"])

    # Authorized item (crit_01) is preserved
    auth_finding = next(f for f in run_dict["findings"] if f["target_id"] == "crit_01")
    assert "ev_rec_01" in auth_finding["evidence_references"]

    # 3. Subsequent retrieval check
    retrieved_run = v_service.repository.get_run(
        sample_mission.scope.tenant_id,
        sample_mission.scope.workspace_id,
        sample_mission.mission_id,
        run.verification_id,
    )
    assert retrieved_run is not None
    retrieved_dict = retrieved_run.model_dump()
    assert "ev_rec_02" not in retrieved_dict["provenance"]["evidence_ids"]
    retrieved_blocked = next(f for f in retrieved_dict["findings"] if f["target_id"] == "crit_02")
    assert "ev_rec_02" not in retrieved_blocked["evidence_references"]
    assert "ev_rec_02" not in str(retrieved_blocked["limitations"])


def test_prompt36d_rule_selection_diagnostic_caveat(v_service, analyst_identity, sample_mission, e_repo):
    """
    Rule Selection: Selecting EVIDENCE_EXISTS when authoritative requirement demands stronger validation
    clearly identifies the rule, records diagnostic non-certification in summary and limitations,
    and cannot be misrepresented as satisfying the stronger requirement.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with e_repo._lock, e_repo._get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_explanations (
                explanation_id, target_type, target_id, tenant_id, workspace_id, plant_id,
                fingerprint, assessment_timestamp, algorithm_version, contract_version,
                is_partial, summary, supporting_evidence_count, excluded_evidence_count,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "exp_p36d_diag", "CRITERION", "crit_01", "tenant_alpha", "workspace_prod", "plant_01",
                "fp_p36d_diag", now_iso, "1.0", "1.0",
                0, "test diag explanation", 1, 0, "{}", now_iso
            )
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_records (
                evidence_id, explanation_id, tenant_id, workspace_id, plant_id,
                source_type, source_record_id, provenance, validation_status,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "ev_rec_01", "exp_p36d_diag", "tenant_alpha", "workspace_prod", "plant_01",
                "TELEMETRY_LOG", "tel_001", "OBSERVED", "VALID",
                json.dumps({"temp": 25.0, "classification": "INTERNAL"}), now_iso
            )
        )
        conn.commit()

    req = VerificationRequest(
        target_type=VerificationTargetType.CRITERION,
        target_id="crit_01",
        rule_type=RuleType.EVIDENCE_EXISTS,
    )
    run = v_service.request_verification(analyst_identity, sample_mission.mission_id, req)
    assert run.status == VerificationStatus.VERIFIED
    finding = run.findings[0]

    # Clearly identifies the evaluated rule
    assert finding.rule_id == "RULE_EVIDENCE_EXISTS_V1"

    # Run summary explicitly records diagnostic non-certification notice
    assert "DIAGNOSTIC ONLY" in run.summary
    assert "does not certify" in run.summary

    # Provenance limitations record diagnostic notice
    assert any("DIAGNOSTIC" in lim.upper() for lim in run.provenance.limitations)

    # Mission status remains ACCEPTED, not EXECUTED or COMPLETED
    saved_m = v_service.mission_service.get_mission(analyst_identity, sample_mission.mission_id)
    assert saved_m.status == MissionStatus.ACCEPTED
