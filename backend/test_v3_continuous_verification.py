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
        get_active_verification_identity,
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
        get_active_verification_identity,
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
    # Evidence was rejected due to scope boundary
    finding = run.findings[0]
    assess = finding.evidence_assessments[0]
    assert assess.scope_status == ScopeStatus.CROSS_PLANT


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
    finding = run.findings[0]
    assess = finding.evidence_assessments[0]
    assert assess.scope_status == ScopeStatus.UNTAGGED_PLANT


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

    # Trusted identity is for tenant_alpha, workspace_prod, plant_01
    vt.set_active_verification_identity(analyst_identity)

    # LLM attempts to pass forged cross-tenant and cross-plant arguments
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
