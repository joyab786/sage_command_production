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
import uuid
import time
import os
import tempfile
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
from data.schemas.action_contract import ActionType, ResourceType


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

        # PROPOSE_ACTION allowed
        decision_allowed = self.service.evaluate_autonomy(
            identity=identity,
            subject_id=grant.subject_id,
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="SIMULATION",
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
            "workspace_id": "workspace_root",
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


if __name__ == "__main__":
    unittest.main()
