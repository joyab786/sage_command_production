# backend/test_v3_autonomy.py
"""
SageCommand V3 — Autonomy Levels & Guarded Delegation Foundation Test Suite (Prompt 38)
Validates:
1. Canonical Autonomy Domain Models & Explicit Autonomy Levels (0 to 5).
2. Level 4 & 5 Disabled/Blocked Non-Negotiable Invariant.
3. Separation of Levels, Capabilities, and Permissions (Capability Allowlist).
4. Deterministic 15-Step Autonomy Evaluation Service.
5. Grant Lifecycle (ACTIVE, SUSPENDED, REVOKED, EXPIRED).
6. Scope Isolation (Tenant, Workspace, Plant, Session).
7. Data Mode Isolation (SIMULATION vs REAL).
8. Anti-Escalation & Identity Integrity (LLM claims & client tampering rejected).
9. Optimistic Concurrency, Revision History, and SQLite Persistence.
10. REST API Endpoints under /api/v3/autonomy.
11. Action Tool & Mission Guard Integration.
12. Strict Execution Boundary: No operational execution endpoint or side-effect.
"""

import unittest
from unittest.mock import patch, MagicMock
import uuid
import time
import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

from server import app
from core.auth import Identity
from data.schemas.autonomy_contract import (
    AutonomyLevel,
    AutonomyLevelAvailability,
    AutonomyGrantStatus,
    SubjectType,
    AutonomyDecisionEffect,
    AutonomyReasonCode,
    CapabilityRegistry,
    AutonomyScope,
    AutonomyConstraints,
    AutonomyProvenance,
    AutonomyGrant,
    AutonomyDecision,
    AutonomyEvaluationRequest,
    AutonomyGrantCreateRequest,
    AutonomyGrantUpdateRequest,
)
from repositories.autonomy_repository import AutonomyRepository, autonomy_repository
from services.autonomy_service import AutonomyService, autonomy_service
from tools.autonomy_context import (
    active_autonomy_context,
    get_active_autonomy_subject,
    get_active_autonomy_identity,
)
from tools.action_tools import propose_action
from data.schemas.action_contract import (
    Action,
    ActionType,
    ActionStatus,
    ResourceType,
    CostEstimate,
    ActionTarget,
    ActionReason,
    RiskLevel,
)
from services.action_store import action_store
from data.schemas.authorization_contract import AuthzDecisionEffect, AuthorizationDecision
from repositories.autonomy_repository import AutonomyRepositoryError


class TestV3AutonomyFoundation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.service = autonomy_service
        cls.repo = autonomy_repository

    def _auth_headers(
        self,
        token="manager_token",
        session_id="session_autonomy_01",
        tenant_id="tenant_default",
        idempotency_key=None,
    ):
        h = {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": session_id,
            "X-Tenant-ID": tenant_id,
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}",
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    # =========================================================================
    # A. AUTONOMY LEVELS & CAPABILITY MODEL TESTS
    # =========================================================================

    def test_canonical_levels_defined(self):
        """Levels 0 to 5 must be defined with exact specification names."""
        levels = [
            AutonomyLevel.OBSERVE,
            AutonomyLevel.ANALYZE,
            AutonomyLevel.RECOMMEND,
            AutonomyLevel.PREPARE_FOR_APPROVAL,
            AutonomyLevel.SUPERVISED_EXECUTION,
            AutonomyLevel.BOUNDED_AUTONOMY,
        ]
        self.assertEqual(len(levels), 6)
        self.assertEqual(int(AutonomyLevel.OBSERVE), 0)
        self.assertEqual(int(AutonomyLevel.PREPARE_FOR_APPROVAL), 3)
        self.assertEqual(int(AutonomyLevel.SUPERVISED_EXECUTION), 4)
        self.assertEqual(int(AutonomyLevel.BOUNDED_AUTONOMY), 5)

    def test_disabled_levels_cannot_be_active(self):
        """Levels 4 & 5 must be permanently DISABLED and NOT_IMPLEMENTED."""
        from data.schemas.autonomy_contract import AUTONOMY_LEVEL_METADATA

        l4_meta = AUTONOMY_LEVEL_METADATA[AutonomyLevel.SUPERVISED_EXECUTION]
        self.assertEqual(l4_meta.availability, AutonomyLevelAvailability.NOT_IMPLEMENTED)
        self.assertFalse(l4_meta.is_executable)

        l5_meta = AUTONOMY_LEVEL_METADATA[AutonomyLevel.BOUNDED_AUTONOMY]
        self.assertEqual(l5_meta.availability, AutonomyLevelAvailability.NOT_IMPLEMENTED)
        self.assertFalse(l5_meta.is_executable)

    def test_capability_registry_allowlist(self):
        """Capability registry must contain canonical capabilities and flag execution as unexecutable."""
        from data.schemas.autonomy_contract import default_capability_registry
        caps = default_capability_registry.list_all()
        cap_ids = [c.capability_id for c in caps]
        self.assertIn("OBSERVE_TELEMETRY", cap_ids)
        self.assertIn("READ_AUTHORIZED_SCHEMA", cap_ids)
        self.assertIn("ANALYZE_EVIDENCE", cap_ids)
        self.assertIn("GENERATE_RECOMMENDATION", cap_ids)
        self.assertIn("PROPOSE_ACTION", cap_ids)
        self.assertIn("VALIDATE_ACTION", cap_ids)
        self.assertIn("PREPARE_APPROVAL_PACKAGE", cap_ids)

        # Execution capabilities must not be implemented in this prompt
        for cap in caps:
            if cap.capability_id in ("EXECUTE_SQL", "EXECUTE_SQL_MUTATION", "EXECUTE_COMMAND", "CONTROL_PLC", "CONTROL_SCADA"):
                self.assertFalse(cap.is_implemented)

    def test_higher_level_does_not_implicitly_grant_all_capabilities(self):
        """Level 3 grant without explicit allowlist must NOT grant capabilities not listed."""
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=f"agent_test_{uuid.uuid4().hex[:6]}",
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],  # Only PROPOSE_ACTION permitted
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # PROPOSE_ACTION allowed with valid action context
        decision_allowed = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=grant.subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "ADJUST_REORDER_POINT",
                "parameters": {"new_reorder_point": 100},
                "target_resource_id": "SKU-01",
            },
        )
        self.assertEqual(decision_allowed.decision, AutonomyDecisionEffect.ALLOW)

        # GENERATE_RECOMMENDATION denied even though it is Level 2 and grant is Level 3
        decision_denied = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=grant.subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision_denied.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision_denied.reason_code, AutonomyReasonCode.CAPABILITY_NOT_GRANTED)

    # =========================================================================
    # B. AUTHORIZATION & RBAC INTEGRATION TESTS
    # =========================================================================

    def test_unauthenticated_grant_creation_rejected(self):
        """Creating an autonomy grant without authentication must return 401."""
        payload = {
            "subject_type": "AGENT",
            "subject_id": "agent_rogue",
            "autonomy_level": "RECOMMEND",
            "tenant_id": "tenant_default",
            "permitted_capabilities": ["GENERATE_RECOMMENDATION"],
        }
        resp = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers={"Authorization": "Bearer invalid_token"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_unauthorized_role_grant_creation_rejected(self):
        """Viewer role (lacking autonomy.grant) must return 403 Forbidden."""
        payload = {
            "subject_type": "AGENT",
            "subject_id": "agent_rogue",
            "autonomy_level": "RECOMMEND",
            "tenant_id": "tenant_default",
            "permitted_capabilities": ["GENERATE_RECOMMENDATION"],
        }
        resp = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers=self._auth_headers(token="viewer_token"),
        )
        self.assertEqual(resp.status_code, 403)

    def test_cross_tenant_grant_retrieval_rejected(self):
        """A caller from tenant_A cannot retrieve a grant created in tenant_B."""
        # Create grant in tenant_B
        grant_b = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=f"agent_b_{uuid.uuid4().hex[:6]}",
            autonomy_level=AutonomyLevel.ANALYZE,
            tenant_id="tenant_B",
            workspace_id="workspace_B",
            plant_id="plant_B",
            data_mode="SIMULATION",
            permitted_capabilities=["ANALYZE_EVIDENCE"],
            created_by="user_tenant_b",
        )
        self.repo.save_grant(grant_b)

        # Caller with tenant_A token tries to read tenant_B grant
        resp = self.client.get(
            f"/api/v3/autonomy/grants/{grant_b.grant_id}",
            headers=self._auth_headers(token="test_token_tenant_a", tenant_id="tenant_A"),
        )
        self.assertIn(resp.status_code, [403, 404])

    def test_cross_tenant_grant_listing_isolated(self):
        """Listing grants with tenant_A token only lists tenant_A grants, never tenant_B."""
        resp = self.client.get(
            "/api/v3/autonomy/grants",
            headers=self._auth_headers(token="test_token_tenant_a", tenant_id="tenant_A"),
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json().get("items", [])
        for item in items:
            self.assertEqual(item["tenant_id"], "tenant_A")

    # =========================================================================
    # C. GRANT LIFECYCLE TESTS (ACTIVE, SUSPENDED, REVOKED, EXPIRED)
    # =========================================================================

    def test_suspended_grant_denies_evaluation(self):
        """Suspended grant must immediately deny evaluation with AUTONOMY_GRANT_SUSPENDED."""
        subject_id = f"agent_suspend_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.OBSERVE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            status=AutonomyGrantStatus.SUSPENDED,
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="OBSERVE_TELEMETRY",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.AUTONOMY_GRANT_SUSPENDED)

    def test_revoked_grant_denies_evaluation_immediately(self):
        """Revoked grant must immediately deny evaluation with AUTONOMY_GRANT_REVOKED."""
        subject_id = f"agent_revoke_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.OBSERVE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            status=AutonomyGrantStatus.REVOKED,
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="OBSERVE_TELEMETRY",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.AUTONOMY_GRANT_REVOKED)

    def test_revoked_grant_cannot_be_reactivated(self):
        """A revoked grant cannot be reactivated via ordinary update request."""
        # Create active grant
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=f"agent_rev_react_{uuid.uuid4().hex[:6]}",
            autonomy_level=AutonomyLevel.OBSERVE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            status=AutonomyGrantStatus.ACTIVE,
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Revoke it
        self.repo.revoke_grant(grant.grant_id, "admin_01", "Security breach")

        # Try to reactivate via API update
        update_payload = {
            "expected_revision": 2,
            "status": "ACTIVE",
        }
        resp = self.client.put(
            f"/api/v3/autonomy/grants/{grant.grant_id}",
            json=update_payload,
            headers=self._auth_headers(token="admin_token"),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cannot be reactivated", resp.json().get("detail", ""))

    def test_expired_grant_denied_deterministically(self):
        """An expired grant must be deterministically rejected with AUTONOMY_GRANT_EXPIRED."""
        subject_id = f"agent_exp_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.OBSERVE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            status=AutonomyGrantStatus.ACTIVE,
            expires_at=time.time() - 3600.0,  # Expired 1 hour ago
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="OBSERVE_TELEMETRY",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.AUTONOMY_GRANT_EXPIRED)

    def test_stale_revision_update_rejected(self):
        """Updating a grant with a stale revision number returns 409 Conflict."""
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=f"agent_stale_{uuid.uuid4().hex[:6]}",
            autonomy_level=AutonomyLevel.OBSERVE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
            revision=1,
        )
        self.repo.save_grant(grant)

        # Attempt update with expected_revision=0 (stale)
        resp = self.client.put(
            f"/api/v3/autonomy/grants/{grant.grant_id}",
            json={"expected_revision": 0, "autonomy_level": "ANALYZE"},
            headers=self._auth_headers(token="admin_token"),
        )
        self.assertEqual(resp.status_code, 409)

    # =========================================================================
    # D. CAPABILITY & EXECUTION BOUNDARY TESTS
    # =========================================================================

    def test_execution_capabilities_permanently_blocked(self):
        """Execution capabilities (EXECUTE_SQL, EXECUTE_COMMAND, etc.) fail closed with EXECUTION_DISABLED."""
        subject_id = f"agent_exec_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["EXECUTE_SQL", "EXECUTE_COMMAND"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )

        for cap in ["EXECUTE_SQL", "EXECUTE_COMMAND", "CONTROL_PLC", "CONTROL_SCADA"]:
            decision = self.service.evaluate_autonomy(
                identity=identity,
                subject_id=subject_id,
                requested_capability=cap,
                resource_scope=grant.scope,
                data_mode="SIMULATION",
            )
            self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
            self.assertEqual(decision.reason_code, AutonomyReasonCode.EXECUTION_DISABLED)

    def test_unimplemented_capability_returns_not_implemented(self):
        """Requesting an unimplemented capability returns NOT_IMPLEMENTED."""
        subject_id = f"agent_unimpl_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.ANALYZE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["DEFERRED_ADVANCED_SYNTHESIS"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="DEFERRED_ADVANCED_SYNTHESIS",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.NOT_IMPLEMENTED)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.CAPABILITY_NOT_IMPLEMENTED)

    def test_unknown_capability_fails_closed(self):
        """Requesting a capability not in the allowlist fails closed with CAPABILITY_NOT_IMPLEMENTED."""
        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id="agent_action_tool",
            requested_capability="MAGIC_AUTONOMOUS_OPERATOR",
            resource_scope=AutonomyScope(tenant_id="tenant_default", plant_id="plant_01"),
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.CAPABILITY_UNKNOWN)

    # =========================================================================
    # E. IDENTITY INTEGRITY & ANTI-PRIVILEGE ESCALATION
    # =========================================================================

    def test_client_supplied_identity_overridden_by_server_auth(self):
        """API endpoints must ignore client-supplied created_by, tenant_id, and use authenticated identity."""
        # Manager from tenant_default submits a grant with fake tenant_id="tenant_super_admin"
        create_payload = {
            "subject_type": "AGENT",
            "subject_id": f"agent_anti_spoof_{uuid.uuid4().hex[:6]}",
            "autonomy_level": "RECOMMEND",
            "tenant_id": "tenant_super_admin",  # Client spoof attempt
            "workspace_id": "workspace_default",
            "plant_id": "plant_01",
            "permitted_capabilities": ["GENERATE_RECOMMENDATION"],
        }
        resp = self.client.post(
            "/api/v3/autonomy/grants",
            json=create_payload,
            headers=self._auth_headers(token="manager_token", tenant_id="tenant_default"),
        )
        self.assertEqual(resp.status_code, 201)
        created_grant = resp.json()
        # Tenant must be authoritative tenant_default, NOT spoofed tenant_super_admin
        self.assertEqual(created_grant["tenant_id"], "tenant_default")
        self.assertEqual(created_grant["created_by"], "mgr_456")

    def test_llm_cannot_elevate_autonomy_level_via_eval_request(self):
        """An evaluation request claims Level 3, but subject grant is Level 0 -> evaluation denies Level 3 capability."""
        subject_id = f"agent_obs_only_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.OBSERVE,  # Level 0
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Request capability PROPOSE_ACTION (requires Level 2+)
        eval_payload = {
            "subject_id": subject_id,
            "subject_type": "AGENT",
            "requested_capability": "PROPOSE_ACTION",
            "resource_scope": {"tenant_id": "tenant_default", "plant_id": "plant_01"},
            "data_mode": "SIMULATION",
        }
        resp = self.client.post(
            "/api/v3/autonomy/evaluate",
            json=eval_payload,
            headers=self._auth_headers(token="operator_token"),
        )
        self.assertEqual(resp.status_code, 200)
        decision = resp.json()
        self.assertEqual(decision["decision"], "DENY")
        self.assertEqual(decision["reason_code"], "AUTONOMY_LEVEL_INSUFFICIENT")

    # =========================================================================
    # F. DATA-MODE ISOLATION (SIMULATION vs REAL)
    # =========================================================================

    def test_simulation_grant_cannot_authorize_real_mode_operation(self):
        """A grant issued for SIMULATION data mode must be denied when requesting REAL mode."""
        subject_id = f"agent_sim_only_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",  # SIMULATION only
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="admin_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            assigned_plants=["plant_01"],
            clearance_level=3,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",  # Attempting REAL
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.DATA_MODE_MISMATCH)

    # =========================================================================
    # G. ACTION & MISSION INTEGRATION (GUARDED PROPOSE_ACTION)
    # =========================================================================

    def test_propose_action_guarded_by_active_autonomy_context(self):
        """ActionTool propose_action must evaluate autonomy and reject if autonomy denies."""
        # Create an agent subject with only Level 0 (OBSERVE)
        subject_id = f"agent_restricted_proposer_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.OBSERVE,  # Level 0
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["OBSERVE_TELEMETRY"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        operator_identity = Identity(
            user_id="op_123",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator"],
            assigned_plants=["plant_01"],
            clearance_level=1,
        )

        # Run propose_action within this agent's autonomy context
        with active_autonomy_context(subject_id=subject_id, identity=operator_identity):
            res = propose_action.invoke({
                "action_type": "SCHEDULE_MAINTENANCE",
                "resource_type": "MACHINE",
                "resource_id": "unit_test_99",
                "plant_id": "plant_01",
                "parameters": {"maintenance_type": "PREVENTATIVE", "duration_hours": 2},
                "reason": "Testing autonomy guardrail",
            })
            # Must be rejected because agent only has Level 0 (OBSERVE) without PROPOSE_ACTION capability
            self.assertIn("ACTION PROPOSAL BLOCKED BY AUTONOMY GOVERNANCE", res)
            self.assertIn("DENY", res)

    def test_propose_action_allowed_with_valid_autonomy_grant(self):
        """ActionTool propose_action succeeds when agent has an active Level 2/3 grant with PROPOSE_ACTION."""
        subject_id = f"agent_valid_proposer_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="mgr_456",
        )
        self.repo.save_grant(grant)

        manager_identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        with active_autonomy_context(subject_id=subject_id, identity=manager_identity):
            res = propose_action.invoke({
                "action_type": "REORDER_INVENTORY",
                "resource_type": "SKU",
                "resource_id": "SKU-100",
                "plant_id": "plant_01",
                "parameters": {"sku_id": "SKU-100", "quantity": 50, "priority": "STANDARD"},
                "estimated_duration_minutes": 30,
                "reason": "Emergency restock authorized",
            })
            self.assertIn("ACTION PROPOSED SUCCESSFULLY", res)
            self.assertIn("Action ID:", res)

    def test_action_execute_endpoint_strictly_405(self):
        """POST /api/v3/actions/{id}/execute must remain strictly 405 Method Not Allowed."""
        dummy_id = str(uuid.uuid4())
        resp = self.client.post(
            f"/api/v3/actions/{dummy_id}/execute",
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertIn(resp.status_code, [404, 405])

    def test_mission_execute_endpoint_strictly_404_or_405(self):
        """POST /api/v3/missions/{id}/execute must remain strictly non-existent or disallowed."""
        dummy_id = str(uuid.uuid4())
        resp = self.client.post(
            f"/api/v3/missions/{dummy_id}/execute",
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertIn(resp.status_code, [404, 405])

    # =========================================================================
    # H. PERSISTENCE, IDEMPOTENCY & AUDIT LEDGER
    # =========================================================================

    def test_grant_persists_across_repository_instances(self):
        """A saved grant must be reloaded accurately from SQLite WAL by a new repository instance."""
        grant_id = f"grant_{uuid.uuid4().hex[:8]}"
        subject_id = f"agent_persist_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=grant_id,
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.ANALYZE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["ANALYZE_EVIDENCE"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Create new repository instance pointing to the same DB
        new_repo = AutonomyRepository(db_path=self.repo.db_path)
        loaded = new_repo.get_grant(grant_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.grant_id, grant_id)
        self.assertEqual(loaded.subject_id, subject_id)
        self.assertEqual(loaded.autonomy_level, AutonomyLevel.ANALYZE)
        self.assertEqual(loaded.revision, 1)

    def test_idempotent_grant_creation_retry(self):
        """Retrying grant creation with the same idempotency key returns the original grant."""
        idem_key = f"idem_{uuid.uuid4().hex[:12]}"
        payload = {
            "subject_type": "AGENT",
            "subject_id": f"agent_idem_{uuid.uuid4().hex[:6]}",
            "autonomy_level": "ANALYZE",
            "tenant_id": "tenant_default",
            "workspace_id": "workspace_default",
            "plant_id": "plant_01",
            "data_mode": "SIMULATION",
            "permitted_capabilities": ["ANALYZE_EVIDENCE"],
        }
        # First request
        resp1 = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertEqual(resp1.status_code, 201)
        grant1 = resp1.json()

        # Second request with same idempotency key
        resp2 = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertIn(resp2.status_code, [200, 201])
        grant2 = resp2.json()
        self.assertEqual(grant1["grant_id"], grant2["grant_id"])

    def test_decision_ledger_records_cryptographic_hash(self):
        """Every autonomy evaluation records an auditable decision with a SHA-256 fingerprint."""
        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id="agent_action_tool",
            requested_capability="PROPOSE_ACTION",
            resource_scope=AutonomyScope(tenant_id="tenant_default", plant_id="plant_01"),
            data_mode="SIMULATION",
        )
        self.assertIsNotNone(decision.decision_id)
        self.assertIsNotNone(decision.decision_hash)
        self.assertEqual(len(decision.decision_hash), 64)  # Valid SHA-256 hex string

        # Retrieve decisions from repo
        decisions = self.repo.list_decisions(tenant_id="tenant_default", limit=5)
        decision_ids = [d.decision_id for d in decisions]
        self.assertIn(decision.decision_id, decision_ids)

    # =========================================================================
    # I. API CONTRACT ENDPOINTS
    # =========================================================================

    def test_api_get_levels_endpoint(self):
        """GET /api/v3/autonomy/levels returns 6 levels with proper availability."""
        resp = self.client.get(
            "/api/v3/autonomy/levels",
            headers=self._auth_headers(token="operator_token"),
        )
        self.assertEqual(resp.status_code, 200)
        levels = resp.json()
        self.assertIsInstance(levels, list)
        self.assertEqual(len(levels), 6)
        l_dict = {l["name"]: l for l in levels}
        self.assertEqual(l_dict["LEVEL_4_SUPERVISED_EXECUTION"]["status"], "DISABLED")
        self.assertFalse(l_dict["LEVEL_4_SUPERVISED_EXECUTION"]["is_operational"])
        self.assertEqual(l_dict["LEVEL_5_BOUNDED_AUTONOMY"]["status"], "NOT_IMPLEMENTED")
        self.assertFalse(l_dict["LEVEL_5_BOUNDED_AUTONOMY"]["is_operational"])

    def test_api_get_capabilities_endpoint(self):
        """GET /api/v3/autonomy/capabilities returns allowlisted capabilities."""
        resp = self.client.get(
            "/api/v3/autonomy/capabilities",
            headers=self._auth_headers(token="operator_token"),
        )
        self.assertEqual(resp.status_code, 200)
        caps = resp.json()
        self.assertIsInstance(caps, list)
        self.assertGreater(len(caps), 5)


class TestV3AutonomyPrompt38ACorrections(unittest.TestCase):
    """
    Prompt 38A Autonomy Governance Security Corrections Test Suite.
    Exhaustively tests all 13 security requirements:
    1. Client-supplied low risk cannot downgrade authoritative high risk.
    2. Missing authoritative risk fails closed (unknown action fails to REQUIRES_REVIEW or safe DENY).
    3. Cross-workspace grant creation is rejected.
    4. Cross-workspace grant retrieval and lifecycle changes are rejected.
    5. Cross-workspace listing cannot expose records.
    6. Missing session identity cannot use a session-bound grant.
    7. A session-bound grant cannot authorize a different session.
    8. Audit persistence failure cannot yield ALLOW (fails closed).
    9. Idempotency conflict detection includes every security-relevant field.
    10. A denied canonical permission prevents ALLOW (both autonomy and authz must pass).
    11. Capability updates reject unknown capability identifiers.
    12. Levels 4 and 5 remain disabled on create and update.
    13. No new execution endpoint or operational side effect is introduced.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.service = autonomy_service
        cls.repo = autonomy_repository

    def _auth_headers(
        self,
        token="manager_token",
        session_id="session_autonomy_corr",
        tenant_id="tenant_default",
        idempotency_key=None,
    ):
        h = {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": session_id,
            "X-Tenant-ID": tenant_id,
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}",
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    # -------------------------------------------------------------------------
    # 1. Client-supplied low risk cannot downgrade authoritative high risk
    # -------------------------------------------------------------------------
    def test_client_supplied_low_risk_cannot_downgrade_authoritative_high_risk(self):
        """Caller submits LOW for a high-risk action: system risk prevails, review required."""
        subject_id = f"agent_risk_test_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            constraints=AutonomyConstraints(approval_required_for_risk_levels=["HIGH", "CRITICAL"]),
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # Client submits risk_level="LOW" for RESCHEDULE_PRODUCTION (classified as HIGH)
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={
                "action_type": "RESCHEDULE_PRODUCTION",
                "risk_level": "LOW",  # Client downgrade attempt
            },
        )
        # Authoritative system risk must NOT be downgraded to LOW
        self.assertIn(decision.risk_status, ["HIGH", "CRITICAL"])
        self.assertNotEqual(decision.risk_status, "LOW")
        # Mandatory approval must be required
        self.assertTrue(decision.approval_requirement)

    # -------------------------------------------------------------------------
    # 2. Missing authoritative risk fails closed
    # -------------------------------------------------------------------------
    def test_missing_authoritative_risk_fails_closed(self):
        """If authoritative risk cannot be established, evaluation fails closed to review-required or denial."""
        subject_id = f"agent_unknown_risk_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # 1. Unregistered action type -> fails closed to REQUIRES_REVIEW (RISK_UNKNOWN)
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "TOTALLY_UNKNOWN_ACTION_999",
                "risk_level": "LOW",
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)

        # 2. Missing action record reference -> fails closed to DENY (AUTHORIZATION_DENIED)
        decision2 = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_id": "act_nonexistent_reference_xyz",
            },
        )
        self.assertEqual(decision2.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision2.reason_code, AutonomyReasonCode.AUTHORIZATION_DENIED)

    # -------------------------------------------------------------------------
    # 3. Cross-workspace grant creation is rejected
    # -------------------------------------------------------------------------
    def test_cross_workspace_grant_creation_rejected(self):
        """Non-admin caller cannot create an autonomy grant outside their authoritative workspace."""
        payload = {
            "subject_type": "AGENT",
            "subject_id": f"agent_cross_ws_{uuid.uuid4().hex[:6]}",
            "autonomy_level": "RECOMMEND",
            "workspace_id": "workspace_finance",  # Cross-workspace creation attempt
            "plant_id": "plant_01",
            "permitted_capabilities": ["GENERATE_RECOMMENDATION"],
        }
        resp = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers=self._auth_headers(token="manager_token"),  # manager is confined to workspace_default
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Cross-workspace access denied", resp.json()["detail"])

        # Wildcard workspace by non-admin must also be rejected
        payload["workspace_id"] = "*"
        resp_wildcard = self.client.post(
            "/api/v3/autonomy/grants",
            json=payload,
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_wildcard.status_code, 403)

    # -------------------------------------------------------------------------
    # 4. Cross-workspace grant retrieval and lifecycle changes are rejected
    # -------------------------------------------------------------------------
    def test_cross_workspace_grant_retrieval_and_lifecycle_changes_rejected(self):
        """Non-admin caller cannot read, update, suspend, or revoke grants from another workspace."""
        grant_id = f"grant_ws_eng_{uuid.uuid4().hex[:8]}"
        grant = AutonomyGrant(
            grant_id=grant_id,
            subject_type=SubjectType.AGENT,
            subject_id=f"agent_eng_{uuid.uuid4().hex[:6]}",
            autonomy_level=AutonomyLevel.ANALYZE,
            tenant_id="tenant_default",
            workspace_id="workspace_engineering",  # Distinct workspace
            plant_id="plant_01",
            data_mode="SIMULATION",
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Manager from workspace_default attempts direct access
        headers = self._auth_headers(token="manager_token")

        # GET: not found in caller's authorized scope
        resp_get = self.client.get(f"/api/v3/autonomy/grants/{grant_id}", headers=headers)
        self.assertIn(resp_get.status_code, [403, 404])

        # PUT: update rejected
        resp_put = self.client.put(
            f"/api/v3/autonomy/grants/{grant_id}",
            json={"expected_revision": 1, "update_reason": "Malicious edit"},
            headers=headers,
        )
        self.assertIn(resp_put.status_code, [403, 404])

        # POST suspend: rejected
        resp_suspend = self.client.post(
            f"/api/v3/autonomy/grants/{grant_id}/suspend?expected_revision=1",
            headers=headers,
        )
        self.assertIn(resp_suspend.status_code, [403, 404])

        # DELETE revoke: rejected
        resp_revoke = self.client.delete(
            f"/api/v3/autonomy/grants/{grant_id}?expected_revision=1",
            headers=headers,
        )
        self.assertIn(resp_revoke.status_code, [403, 404])

        # Verify grant in workspace_engineering was not modified
        g_check = self.repo.get_grant(grant_id, tenant_id="tenant_default", workspace_id="workspace_engineering")
        self.assertIsNotNone(g_check)
        self.assertEqual(g_check.status, AutonomyGrantStatus.ACTIVE)
        self.assertEqual(g_check.revision, 1)

    # -------------------------------------------------------------------------
    # 5. Cross-workspace listing cannot expose records
    # -------------------------------------------------------------------------
    def test_cross_workspace_listing_cannot_expose_records(self):
        """Listing grants with an unauthorized workspace filter is rejected; default list excludes other workspaces."""
        # Querying an unauthorized workspace returns 403
        resp = self.client.get(
            "/api/v3/autonomy/grants?workspace_id=workspace_engineering",
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp.status_code, 403)

        # Querying decisions with unauthorized workspace returns 403
        resp_dec = self.client.get(
            "/api/v3/autonomy/decisions?workspace_id=workspace_engineering",
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_dec.status_code, 403)

        # Default listing strictly isolates to caller's workspace
        resp_list = self.client.get(
            "/api/v3/autonomy/grants",
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_list.status_code, 200)
        grants = resp_list.json().get("grants", [])
        for g in grants:
            self.assertIn(g["workspace_id"], ["workspace_default", "*"])

    # -------------------------------------------------------------------------
    # 6. Missing session identity cannot use a session-bound grant
    # -------------------------------------------------------------------------
    def test_missing_session_identity_cannot_use_session_bound_grant(self):
        """A session-bound grant must strictly deny callers that provide no session context."""
        subject_id = f"agent_sess_bound_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_mission_alpha_99",  # Strictly bound to session
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Caller provides NO session context
        identity_no_session = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id=None,
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )
        scope_no_session = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            session_id=None,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity_no_session,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_no_session,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.SESSION_MISMATCH)

    # -------------------------------------------------------------------------
    # 7. A session-bound grant cannot authorize a different session
    # -------------------------------------------------------------------------
    def test_session_bound_grant_cannot_authorize_different_session(self):
        """A grant bound to session A must reject requests from session B and only allow session A."""
        subject_id = f"agent_sess_cross_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_alpha_only",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Session mismatch: caller provides session_beta
        identity_beta = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_beta_wrong",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )
        scope_beta = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            session_id="session_beta_wrong",
        )
        decision_mismatch = self.service.evaluate_autonomy(
            identity=identity_beta,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_beta,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision_mismatch.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision_mismatch.reason_code, AutonomyReasonCode.SESSION_MISMATCH)

        # Matching session: caller provides session_alpha_only -> ALLOW
        identity_alpha = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_alpha_only",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )
        scope_alpha = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            session_id="session_alpha_only",
        )
        decision_match = self.service.evaluate_autonomy(
            identity=identity_alpha,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_alpha,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision_match.decision, AutonomyDecisionEffect.ALLOW)

    # -------------------------------------------------------------------------
    # 8. Audit persistence failure cannot yield ALLOW
    # -------------------------------------------------------------------------
    def test_audit_persistence_failure_cannot_yield_allow(self):
        """When ledger database persistence fails during an ALLOW evaluation, it must fail closed to DENY."""
        subject_id = f"agent_audit_fail_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # Force database persistence to fail with an OperationalError
        with patch.object(self.repo, "record_decision", side_effect=sqlite3.OperationalError("database disk image is malformed")):
            decision = self.service.evaluate_autonomy(
                identity=identity,
                subject_id=subject_id,
                requested_capability="GENERATE_RECOMMENDATION",
                resource_scope=grant.scope,
                data_mode="SIMULATION",
            )
            # Must strictly fail closed: ALLOW without audit persistence is forbidden
            self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
            self.assertEqual(decision.reason_code, AutonomyReasonCode.EVALUATION_ERROR)
            self.assertIn("Mandatory audit persistence failed", decision.reason)

    # -------------------------------------------------------------------------
    # 9. Idempotency conflict detection includes every security-relevant field
    # -------------------------------------------------------------------------
    def test_idempotency_conflict_detection_includes_all_security_fields(self):
        """Altering any security-relevant field with a reused idempotency key raises a 409 conflict."""
        idem_key = f"idem_sec_{uuid.uuid4().hex[:12]}"
        base_payload = {
            "subject_type": "AGENT",
            "subject_id": f"agent_idem_sec_{uuid.uuid4().hex[:6]}",
            "autonomy_level": "RECOMMEND",
            "workspace_id": "workspace_default",
            "plant_id": "plant_01",
            "data_mode": "SIMULATION",
            "permitted_capabilities": ["GENERATE_RECOMMENDATION"],
            "constraints": {"max_cost_limit_usd": 100.0},
        }

        # 1. Initial creation -> 201 Created
        resp1 = self.client.post(
            "/api/v3/autonomy/grants",
            json=base_payload,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertEqual(resp1.status_code, 201)
        original_grant_id = resp1.json()["grant_id"]

        # 2. Exact retry -> 200/201 returns existing grant
        resp_retry = self.client.post(
            "/api/v3/autonomy/grants",
            json=base_payload,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertIn(resp_retry.status_code, [200, 201])
        self.assertEqual(resp_retry.json()["grant_id"], original_grant_id)

        # 3. Conflict on data_mode -> 409 Conflict
        conflicting_data_mode = dict(base_payload)
        conflicting_data_mode["data_mode"] = "REAL"
        resp_cm = self.client.post(
            "/api/v3/autonomy/grants",
            json=conflicting_data_mode,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertEqual(resp_cm.status_code, 409)

        # 4. Conflict on level -> 409 Conflict
        conflicting_level = dict(base_payload)
        conflicting_level["autonomy_level"] = "ANALYZE"
        resp_cl = self.client.post(
            "/api/v3/autonomy/grants",
            json=conflicting_level,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertEqual(resp_cl.status_code, 409)

        # 5. Conflict on constraints -> 409 Conflict
        conflicting_constraints = dict(base_payload)
        conflicting_constraints["constraints"] = {"max_cost_limit_usd": 9999.0}
        resp_cc = self.client.post(
            "/api/v3/autonomy/grants",
            json=conflicting_constraints,
            headers=self._auth_headers(token="manager_token", idempotency_key=idem_key),
        )
        self.assertEqual(resp_cc.status_code, 409)

    # -------------------------------------------------------------------------
    # 10. A denied canonical permission prevents ALLOW
    # -------------------------------------------------------------------------
    def test_denied_canonical_permission_prevents_allow(self):
        """Underlying RBAC permission denial must prevent autonomy ALLOW (both must pass)."""
        subject_id = f"agent_perm_check_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],  # Maps to action.create
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        # Viewer role identity does NOT hold action.create permission
        viewer_identity = Identity(
            user_id="view_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["viewer"],
            assigned_plants=["plant_01"],
            clearance_level=1,
        )

        decision = self.service.evaluate_autonomy(
            identity=viewer_identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.AUTHORIZATION_DENIED)
        self.assertIn("Underlying authorization denied", decision.reason)

    # -------------------------------------------------------------------------
    # 11. Capability updates reject unknown capability identifiers
    # -------------------------------------------------------------------------
    def test_capability_updates_reject_unknown_capability_identifiers(self):
        """Updating an existing grant with unknown capability IDs must be strictly rejected."""
        create_resp = self.client.post(
            "/api/v3/autonomy/grants",
            json={
                "subject_type": "AGENT",
                "subject_id": f"agent_cap_upd_{uuid.uuid4().hex[:6]}",
                "autonomy_level": "ANALYZE",
                "workspace_id": "workspace_default",
                "plant_id": "plant_01",
                "data_mode": "SIMULATION",
                "permitted_capabilities": ["ANALYZE_EVIDENCE"],
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(create_resp.status_code, 201)
        grant_id = create_resp.json()["grant_id"]

        # Update with unknown permitted capability
        resp_perm = self.client.put(
            f"/api/v3/autonomy/grants/{grant_id}",
            json={
                "expected_revision": 1,
                "permitted_capabilities": ["BOGUS_NONEXISTENT_CAP_999"],
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_perm.status_code, 400)
        self.assertIn("Unknown capability", resp_perm.json()["detail"])

        # Update with unknown restricted capability
        resp_restr = self.client.put(
            f"/api/v3/autonomy/grants/{grant_id}",
            json={
                "expected_revision": 1,
                "restricted_capabilities": ["ANOTHER_BOGUS_CAP"],
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_restr.status_code, 400)
        self.assertIn("Unknown capability", resp_restr.json()["detail"])

    # -------------------------------------------------------------------------
    # 12. Levels 4 and 5 remain disabled
    # -------------------------------------------------------------------------
    def test_levels_4_and_5_remain_disabled(self):
        """Levels 4 & 5 cannot be granted or updated in SageCommand V3."""
        # Level 4 on create
        resp_l4_create = self.client.post(
            "/api/v3/autonomy/grants",
            json={
                "subject_type": "AGENT",
                "subject_id": f"agent_l4_{uuid.uuid4().hex[:6]}",
                "autonomy_level": "SUPERVISED_EXECUTION",
                "workspace_id": "workspace_default",
                "plant_id": "plant_01",
                "data_mode": "SIMULATION",
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_l4_create.status_code, 400)
        self.assertIn("DISABLED and NOT_IMPLEMENTED", resp_l4_create.json()["detail"])

        # Level 5 on create
        resp_l5_create = self.client.post(
            "/api/v3/autonomy/grants",
            json={
                "subject_type": "AGENT",
                "subject_id": f"agent_l5_{uuid.uuid4().hex[:6]}",
                "autonomy_level": "BOUNDED_AUTONOMY",
                "workspace_id": "workspace_default",
                "plant_id": "plant_01",
                "data_mode": "SIMULATION",
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_l5_create.status_code, 400)
        self.assertIn("DISABLED and NOT_IMPLEMENTED", resp_l5_create.json()["detail"])

        # Valid grant update to Level 4
        create_resp = self.client.post(
            "/api/v3/autonomy/grants",
            json={
                "subject_type": "AGENT",
                "subject_id": f"agent_l1_{uuid.uuid4().hex[:6]}",
                "autonomy_level": "OBSERVE",
                "workspace_id": "workspace_default",
                "plant_id": "plant_01",
                "data_mode": "SIMULATION",
            },
            headers=self._auth_headers(token="manager_token"),
        )
        grant_id = create_resp.json()["grant_id"]

        resp_l4_upd = self.client.put(
            f"/api/v3/autonomy/grants/{grant_id}",
            json={
                "expected_revision": 1,
                "autonomy_level": "SUPERVISED_EXECUTION",
            },
            headers=self._auth_headers(token="manager_token"),
        )
        self.assertEqual(resp_l4_upd.status_code, 400)
        self.assertIn("DISABLED and NOT_IMPLEMENTED", resp_l4_upd.json()["detail"])

    # -------------------------------------------------------------------------
    # 13. No new execution endpoint or operational side effect
    # -------------------------------------------------------------------------
    def test_no_new_execution_endpoint_or_operational_side_effect(self):
        """Operational execution endpoints do not exist; execution capabilities evaluate to EXECUTION_DISABLED."""
        for path in ["/api/v3/autonomy/execute", "/api/v3/autonomy/run", "/api/v3/autonomy/dispatch"]:
            resp = self.client.post(path, json={}, headers=self._auth_headers())
            self.assertIn(resp.status_code, [404, 405])

        # Execution capabilities permanently evaluate to EXECUTION_DISABLED
        identity = Identity(
            user_id="mgr_456",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["administrator"],
            clearance_level=3,
        )
        for exec_cap in ["EXECUTE_SQL", "EXECUTE_COMMAND", "CONTROL_PLC"]:
            dec = self.service.evaluate_autonomy(
                identity=identity,
                subject_id="agent_exec_test",
                requested_capability=exec_cap,
                resource_scope=AutonomyScope(tenant_id="tenant_default", workspace_id="workspace_default"),
                data_mode="REAL",
            )
            self.assertEqual(dec.decision, AutonomyDecisionEffect.DENY)
            self.assertEqual(dec.reason_code, AutonomyReasonCode.EXECUTION_DISABLED)


class TestV3AutonomyPrompt38BCorrections(unittest.TestCase):
    """
    Prompt 38B Security Corrections Test Suite:
    1. Removal of implicit LOW-risk fallback (action capabilities require authoritative action/risk).
    2. Session scope derived exclusively from trusted identity.
    3. Action-bound risk evaluation (consistency, workspace containment, mandatory action record).
    4. Authoritative cost constraints (understated client cost cannot bypass limits, missing cost fails closed).
    5. Explicit authorization ALLOW requirement (DENY, indeterminate, exceptions fail closed).
    """

    @classmethod
    def setUpClass(cls):
        cls.service = autonomy_service
        cls.repo = autonomy_repository
        cls.client = TestClient(app)

    def _auth_headers(self, token="admin_token"):
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "tenant_default",
            "X-Workspace-ID": "workspace_default",
        }

    # =========================================================================
    # 1. REMOVE IMPLICIT LOW-RISK FALLBACK
    # =========================================================================

    def test_missing_action_context_for_action_capability_fails_closed(self):
        """Requesting an action capability without action details cannot default to LOW; fails closed to REQUIRES_REVIEW."""
        subject_id = f"agent_no_ctx_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # Omit all action details
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={},
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)
        self.assertEqual(decision.risk_status, "UNKNOWN")

    def test_invalid_action_type_fails_closed(self):
        """An unrecognized action type cannot establish authoritative risk; fails closed to REQUIRES_REVIEW."""
        subject_id = f"agent_inv_act_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "NONEXISTENT_BOGUS_ACTION_TYPE",
                "risk_level": "LOW",
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)
        self.assertEqual(decision.risk_status, "UNKNOWN")

    def test_malformed_parameters_fails_closed(self):
        """Malformed action parameters fail server-side schema validation and return REQUIRES_REVIEW with RISK_UNKNOWN."""
        subject_id = f"agent_bad_params_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "ADJUST_REORDER_POINT",
                "target_resource_id": "SKU-01",
                "parameters": {"new_reorder_point": -500},  # Negative value violates ge=0
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)

    def test_missing_target_context_fails_closed(self):
        """Missing target resource and plant context fails closed to REQUIRES_REVIEW."""
        subject_id = f"agent_no_target_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            clearance_level=2,
        )

        scope_no_target = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id=None,
            equipment_id=None,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=scope_no_target,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "ADJUST_REORDER_POINT",
                "parameters": {"new_reorder_point": 100},
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)

    def test_observation_and_analysis_capabilities_preserve_analytical_rules(self):
        """Legitimate observation and analysis capabilities succeed without action records under explicit analytical rules."""
        subject_id = f"agent_obs_analytical_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.ANALYZE,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["OBSERVE_TELEMETRY", "ANALYZE_EVIDENCE"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        for cap in ["OBSERVE_TELEMETRY", "ANALYZE_EVIDENCE"]:
            decision = self.service.evaluate_autonomy(
                identity=identity,
                subject_id=subject_id,
                requested_capability=cap,
                resource_scope=grant.scope,
                data_mode="SIMULATION",
            )
            self.assertEqual(decision.decision, AutonomyDecisionEffect.ALLOW)
            self.assertEqual(decision.risk_status, "LOW")

    # =========================================================================
    # 2. DERIVE SESSION SCOPE EXCLUSIVELY FROM TRUSTED IDENTITY
    # =========================================================================

    def test_caller_with_no_session_submitting_session_scope_rejected(self):
        """Caller with no trusted session submitting another session ID in scope must fail closed (SESSION_MISMATCH)."""
        subject_id = f"agent_no_sess_spoof_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity_no_session = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id=None,  # No trusted session
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        scope_with_spoofed_session = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_spoofed_123",  # Client-supplied session scope
            plant_id="plant_01",
        )

        decision = self.service.evaluate_autonomy(
            identity=identity_no_session,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_with_spoofed_session,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.SESSION_MISMATCH)
        self.assertIn("caller has no trusted session", decision.reason)

    def test_caller_session_mismatch_with_scope_session_rejected(self):
        """Caller with trusted session A supplying session B in scope must fail closed (SESSION_MISMATCH)."""
        subject_id = f"agent_sess_mismatch_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_alpha",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity_alpha = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_alpha",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        scope_beta = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_beta_conflicting",
            plant_id="plant_01",
        )

        decision = self.service.evaluate_autonomy(
            identity=identity_alpha,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_beta,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.SESSION_MISMATCH)

    def test_unsessioned_caller_cannot_access_session_bound_grant_via_scope(self):
        """Un-sessioned caller cannot unlock a session-bound grant by injecting session_id into AutonomyScope."""
        subject_id = f"agent_sess_unlock_attempt_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_bound_target",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["GENERATE_RECOMMENDATION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity_un_sessioned = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id=None,
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        scope_attempt = AutonomyScope(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_bound_target",
            plant_id="plant_01",
        )

        decision = self.service.evaluate_autonomy(
            identity=identity_un_sessioned,
            subject_id=subject_id,
            requested_capability="GENERATE_RECOMMENDATION",
            resource_scope=scope_attempt,
            data_mode="SIMULATION",
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.SESSION_MISMATCH)

    # =========================================================================
    # 3. BIND RISK EVALUATION TO THE AUTHORITATIVE ACTION
    # =========================================================================

    def test_action_id_mandatory_for_validation_and_approval_capabilities(self):
        """VALIDATE_ACTION, PREPARE_APPROVAL_PACKAGE, and REQUEST_HUMAN_REVIEW require an action_id."""
        subject_id = f"agent_act_req_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.PREPARE_FOR_APPROVAL,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["VALIDATE_ACTION", "PREPARE_APPROVAL_PACKAGE", "REQUEST_HUMAN_REVIEW"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["OPERATOR", "PLANT_MANAGER"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        for cap in ["VALIDATE_ACTION", "PREPARE_APPROVAL_PACKAGE", "REQUEST_HUMAN_REVIEW"]:
            decision = self.service.evaluate_autonomy(
                identity=identity,
                subject_id=subject_id,
                requested_capability=cap,
                resource_scope=grant.scope,
                data_mode="SIMULATION",
                risk_context={"action_type": "ADJUST_REORDER_POINT"},  # No action_id
            )
            self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
            self.assertEqual(decision.reason_code, AutonomyReasonCode.RISK_UNKNOWN)
            self.assertIn("Authoritative persisted action record ('action_id') is required", decision.reason)

    def test_cross_workspace_action_reference_rejected(self):
        """Referencing an action stored in another workspace must fail closed with WORKSPACE_MISMATCH."""
        # Store an action in workspace_finance
        act = Action(
            action_id=f"act_fin_{uuid.uuid4().hex[:8]}",
            tenant_id="tenant_default",
            workspace_id="workspace_finance",
            session_id="session_01",
            action_type=ActionType.ADJUST_REORDER_POINT,
            version="1.0",
            target=ActionTarget(resource_type=ResourceType.SKU, resource_id="SKU-FIN", plant_id="plant_01"),
            parameters={"new_reorder_point": 100},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Finance inventory adjustment"),
            data_mode="REAL",
            system_risk_level=RiskLevel.LOW,
            status=ActionStatus.PROPOSED,
        )
        action_store.save(act)

        # Grant and caller in workspace_default
        subject_id = f"agent_cross_act_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="operator_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={"action_id": act.action_id},
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.WORKSPACE_MISMATCH)

    def test_action_type_inconsistency_rejected(self):
        """Submitting an action_type that mismatches the stored action record fails closed with ACTION_VALIDATION_FAILED."""
        act = Action(
            action_id=f"act_type_mismatch_{uuid.uuid4().hex[:8]}",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_01",
            action_type=ActionType.ADJUST_REORDER_POINT,
            version="1.0",
            target=ActionTarget(resource_type=ResourceType.SKU, resource_id="SKU-01", plant_id="plant_01"),
            parameters={"new_reorder_point": 100},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Reorder adjust"),
            data_mode="REAL",
            system_risk_level=RiskLevel.LOW,
            status=ActionStatus.PROPOSED,
        )
        action_store.save(act)

        subject_id = f"agent_inconsistent_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={
                "action_id": act.action_id,
                "action_type": "RESCHEDULE_PRODUCTION",  # Inconsistent with stored ADJUST_REORDER_POINT
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.ACTION_VALIDATION_FAILED)

    def test_target_inconsistency_rejected(self):
        """Submitting a target resource that mismatches the stored action record fails closed with SCOPE_MISMATCH."""
        act = Action(
            action_id=f"act_tgt_mismatch_{uuid.uuid4().hex[:8]}",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_01",
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            version="1.0",
            target=ActionTarget(resource_type=ResourceType.MACHINE, resource_id="MACHINE-01", plant_id="plant_01"),
            parameters={"machine_id": "MACHINE-01", "scheduled_start": "2026-11-01T08:00:00Z", "estimated_duration_minutes": 60},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Scheduled maintenance"),
            data_mode="REAL",
            system_risk_level=RiskLevel.MEDIUM,
            status=ActionStatus.PROPOSED,
        )
        action_store.save(act)

        subject_id = f"agent_tgt_inc_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={
                "action_id": act.action_id,
                "target_resource_id": "MACHINE-99",  # Mismatch with MACHINE-01
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.SCOPE_MISMATCH)

    def test_data_mode_inconsistency_rejected(self):
        """Evaluating an action with a data mode that mismatches the stored action fails closed with DATA_MODE_MISMATCH."""
        act = Action(
            action_id=f"act_mode_mismatch_{uuid.uuid4().hex[:8]}",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_01",
            action_type=ActionType.ADJUST_REORDER_POINT,
            version="1.0",
            target=ActionTarget(resource_type=ResourceType.SKU, resource_id="SKU-01", plant_id="plant_01"),
            parameters={"new_reorder_point": 100},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="Simulated adjustment"),
            data_mode="SIMULATION",  # Stored as SIMULATION
            system_risk_level=RiskLevel.LOW,
            status=ActionStatus.PROPOSED,
        )
        action_store.save(act)

        subject_id = f"agent_mode_inc_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",  # Evaluating in REAL mode against SIMULATION action
            risk_context={"action_id": act.action_id},
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.DATA_MODE_MISMATCH)

    # =========================================================================
    # 4. USE AUTHORITATIVE COST FOR COST CONSTRAINTS
    # =========================================================================

    def test_understated_client_cost_cannot_bypass_max_cost_limit(self):
        """Understated client cost cannot bypass a grant maximum cost constraint; authoritative stored cost prevails."""
        act = Action(
            action_id=f"act_expensive_{uuid.uuid4().hex[:8]}",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_01",
            action_type=ActionType.REORDER_INVENTORY,
            version="1.0",
            target=ActionTarget(resource_type=ResourceType.SKU, resource_id="SKU-EXPENSIVE", plant_id="plant_01"),
            parameters={"sku_id": "SKU-EXPENSIVE", "quantity": 1000},
            reason=ActionReason(reason_code="MAINT_SCHEDULE", summary="High-cost bulk order"),
            data_mode="REAL",
            system_risk_level=RiskLevel.MEDIUM,
            estimated_cost=CostEstimate(value=50000.0, currency="USD"),  # Authoritative cost $50,000
            status=ActionStatus.PROPOSED,
        )
        action_store.save(act)

        subject_id = f"agent_cost_bypass_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            constraints=AutonomyConstraints(max_cost_limit_usd=5000.0),  # Limit is $5,000
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # Caller attempts to submit understated cost_estimate_usd=50.0
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={
                "action_id": act.action_id,
                "cost_estimate_usd": 50.0,  # Understated attempt
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.POLICY_REVIEW_REQUIRED)
        self.assertIn("Authoritative cost ($50,000.00) exceeds grant maximum cost threshold ($5,000.00)", decision.reason)

    def test_missing_cost_for_mandatory_cost_limit_fails_closed(self):
        """When grant has a mandatory max cost limit but action cost cannot be evaluated, evaluation returns REQUIRES_REVIEW."""
        subject_id = f"agent_cost_missing_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            constraints=AutonomyConstraints(max_cost_limit_usd=5000.0),  # Mandatory cost limit
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        # Evaluating without cost
        decision = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
            risk_context={
                "action_type": "ADJUST_REORDER_POINT",
                "parameters": {"new_reorder_point": 100},
                "target_resource_id": "SKU-01",
                # cost_estimate_usd omitted
            },
        )
        self.assertEqual(decision.decision, AutonomyDecisionEffect.REQUIRES_REVIEW)
        self.assertEqual(decision.reason_code, AutonomyReasonCode.POLICY_REVIEW_REQUIRED)
        self.assertIn("action cost cannot be authoritatively evaluated", decision.reason)

    # =========================================================================
    # 5. REQUIRE EXPLICIT AUTHORIZATION ALLOW
    # =========================================================================

    def test_authorization_deny_rejects_grant_permission(self):
        """When authorization_service.evaluate returns DENY, _require_grant_permission raises AutonomyRepositoryError."""
        identity = Identity(
            user_id="guest_user",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["guest"],  # Not an authorized role
            clearance_level=1,
        )

        with self.assertRaises(AutonomyRepositoryError):
            self.service._require_grant_permission(identity, "grant")

    def test_authorization_indeterminate_or_review_rejects_grant_permission(self):
        """When authorization_service.evaluate returns an unexpected/indeterminate effect, it must not authorize."""
        identity = Identity(
            user_id="guest_user",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["guest"],
            clearance_level=1,
        )

        mock_decision = MagicMock()
        mock_decision.effect = "INDETERMINATE"
        mock_decision.reason = "Manual approval required"

        with patch("services.authorization_service.authorization_service.evaluate", return_value=mock_decision):
            with self.assertRaises(AutonomyRepositoryError):
                self.service._require_grant_permission(identity, "grant")

    def test_authorization_exception_fails_closed(self):
        """When authorization_service.evaluate raises an exception, it must fail closed and raise AutonomyRepositoryError."""
        identity = Identity(
            user_id="guest_user",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["guest"],
            clearance_level=1,
        )

        with patch("services.authorization_service.authorization_service.evaluate", side_effect=RuntimeError("Authorization DB connection timeout")):
            with self.assertRaises(AutonomyRepositoryError):
                self.service._require_grant_permission(identity, "grant")

    def test_underlying_authorization_exception_in_capability_evaluation_fails_closed(self):
        """When evaluating a capability with canonical permission and authz raises an exception, evaluate_autonomy returns DENY."""
        subject_id = f"agent_authz_ex_{uuid.uuid4().hex[:6]}"
        grant = AutonomyGrant(
            grant_id=f"grant_{uuid.uuid4().hex[:8]}",
            subject_type=SubjectType.AGENT,
            subject_id=subject_id,
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="SIMULATION",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_01",
        )
        self.repo.save_grant(grant)

        identity = Identity(
            user_id="mgr_01",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            roles=["operator", "manager"],
            assigned_plants=["plant_01"],
            clearance_level=2,
        )

        with patch("services.authorization_service.authorization_service.evaluate", side_effect=RuntimeError("Authz network failure")):
            decision = self.service.evaluate_autonomy(
                identity=identity,
                subject_id=subject_id,
                requested_capability="PROPOSE_ACTION",
                resource_scope=grant.scope,
                data_mode="SIMULATION",
                risk_context={
                    "action_type": "ADJUST_REORDER_POINT",
                    "parameters": {"new_reorder_point": 100},
                    "target_resource_id": "SKU-01",
                },
            )
            self.assertEqual(decision.decision, AutonomyDecisionEffect.DENY)
            self.assertEqual(decision.reason_code, AutonomyReasonCode.AUTHORIZATION_DENIED)
            self.assertIn("Underlying authorization evaluation failed", decision.reason)


if __name__ == "__main__":
    unittest.main()

