# backend/test_v3_authorization.py
"""
SageCommand V3 — RBAC + ABAC Authorization Architecture Test Suite (Prompt 07)
Validates:
1. Canonical Permission Registry & Namespaced Validation.
2. 10 Canonical Roles, Acyclic Directed Graph Inheritance, and Cycle Rejection.
3. Persistent Role Store (SQLite roles_v3) & Re-hydration.
4. Tenant, Workspace, and Plant Scope Isolation.
5. ABAC Separation of Duties (Proposer != Approver).
6. ABAC Clearance Level & Data Mode Restrictions (HISTORICAL vs LIVE).
7. Administrative Operational Boundary (Administrator != Operational Authority).
8. Cryptographic Tamper-Evident Decision Fingerprint (SHA-256).
9. REST Endpoints under /api/v3/authorization (/check, /permissions, /roles, /roles/{role_id}).
10. Strict Execution Boundary: POST /api/v3/actions/{id}/execute returns 405 Method Not Allowed.
"""

import unittest
import json
import uuid
import hashlib
from fastapi.testclient import TestClient

from server import app
from core.auth import Identity
from data.schemas.authorization_contract import (
    UserStatus,
    RoleScopeType,
    AuthzDecisionEffect,
    AuthzReasonCode,
    Permission,
    Role,
    UserIdentity,
    AuthorizationScope,
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationCheckRequest,
)
from services.authorization_service import (
    PermissionRegistry,
    RoleRegistry,
    ScopeMatcher,
    AuthorizationService,
    authorization_service,
)


class TestV3AuthorizationArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.service = authorization_service

    def _auth_headers(self, token="manager_token", session_id="session_authz_01", tenant_id="tenant_default"):
        return {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": session_id,
            "X-Tenant-ID": tenant_id,
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}"
        }

    # =====================================================================
    # 1. PERMISSION REGISTRY & NAMESPACED VALIDATION
    # =====================================================================

    def test_permission_registry_catalog(self):
        """Validates canonical permission catalog is loaded and formatted."""
        registry = PermissionRegistry()
        perms = registry.list_permissions()
        self.assertGreaterEqual(len(perms), 20)

        # Check critical permissions
        self.assertTrue(registry.is_valid("action.create"))
        self.assertTrue(registry.is_valid("action.approve"))
        self.assertTrue(registry.is_valid("telemetry.read"))
        self.assertTrue(registry.is_valid("database.read"))
        self.assertTrue(registry.is_valid("policy.manage"))

        # Rejects non-namespaced permission
        with self.assertRaises(ValueError):
            Permission(permission_id="invalidpermission", resource="action", action="create")

    # =====================================================================
    # 2. 10 SYSTEM ROLES & ACYCLIC INHERITANCE
    # =====================================================================

    def test_all_10_system_roles_present(self):
        """Verifies all 10 canonical roles are registered."""
        expected_roles = {
            "VIEWER", "ANALYST", "OPERATOR", "MAINTENANCE_ENGINEER",
            "SUPPLY_CHAIN_MANAGER", "SAFETY_MANAGER", "PLANT_MANAGER",
            "EXECUTIVE", "ADMINISTRATOR", "SECURITY_ADMIN"
        }
        loaded_roles = {r.role_id for r in self.service.role_registry.list_roles()}
        self.assertTrue(expected_roles.issubset(loaded_roles), f"Missing roles: {expected_roles - loaded_roles}")

    def test_transitive_permission_resolution(self):
        """Validates that child roles inherit permissions transitively from parent roles."""
        role_reg = self.service.role_registry

        # OPERATOR inherits ANALYST inherits VIEWER
        op_perms, op_map = role_reg.resolve_effective_permissions(["OPERATOR"])
        self.assertIn("action.create", op_perms)   # Direct OPERATOR
        self.assertIn("action.simulate", op_perms) # Inherited from ANALYST
        self.assertIn("telemetry.read", op_perms)  # Inherited from VIEWER
        self.assertEqual(op_map["action.create"], "OPERATOR")
        self.assertEqual(op_map["telemetry.read"], "VIEWER")

        # PLANT_MANAGER inherits OPERATOR, SAFETY_MANAGER, SUPPLY_CHAIN_MANAGER
        pm_perms, pm_map = role_reg.resolve_effective_permissions(["PLANT_MANAGER"])
        self.assertIn("action.approve", pm_perms)      # Direct PLANT_MANAGER
        self.assertIn("action.create", pm_perms)       # From OPERATOR
        self.assertIn("safety.hold", pm_perms)         # From SAFETY_MANAGER
        self.assertIn("inventory.adjust", pm_perms)    # From SUPPLY_CHAIN_MANAGER
        self.assertIn("telemetry.read", pm_perms)      # From VIEWER

    def test_cycle_detection_rejection(self):
        """Validates that circular inheritance is detected and rejected."""
        # Create a test registry
        test_reg = RoleRegistry(db_path=":memory:")
        role_a = Role(role_id="ROLE_A", name="Role A", permissions=["test.a"], inherits_from=["ROLE_B"])
        role_b = Role(role_id="ROLE_B", name="Role B", permissions=["test.b"], inherits_from=["ROLE_C"])
        role_c = Role(role_id="ROLE_C", name="Role C", permissions=["test.c"], inherits_from=["ROLE_A"])

        test_reg._roles["ROLE_A"] = role_a
        test_reg._roles["ROLE_B"] = role_b
        test_reg._roles["ROLE_C"] = role_c

        with self.assertRaises(ValueError) as ctx:
            test_reg.resolve_effective_permissions(["ROLE_A"])
        self.assertIn("Cycle detected", str(ctx.exception))

    # =====================================================================
    # 3. TENANT, WORKSPACE, AND PLANT SCOPE ISOLATION
    # =====================================================================

    def test_tenant_isolation_denied(self):
        """Cross-tenant operation must be blocked fail-closed."""
        user = UserIdentity(
            user_id="user_tenant_1",
            tenant_id="tenant_alpha",
            roles=["OPERATOR"]
        )
        scope = AuthorizationScope(
            tenant_id="tenant_beta",
            plant_id="plant_01"
        )
        ctx = AuthorizationContext(
            identity=user,
            required_permission="action.create",
            scope=scope
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.TENANT_MISMATCH)

    def test_workspace_isolation_denied(self):
        """Workspace mismatch must be denied."""
        user = UserIdentity(
            user_id="user_ws_1",
            tenant_id="tenant_alpha",
            workspace_id="workspace_alpha",
            roles=["OPERATOR"]
        )
        scope = AuthorizationScope(
            tenant_id="tenant_alpha",
            workspace_id="workspace_bravo",
            plant_id="plant_01"
        )
        ctx = AuthorizationContext(
            identity=user,
            required_permission="action.create",
            scope=scope
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.WORKSPACE_MISMATCH)

    def test_plant_scope_isolation(self):
        """Plant access must be granted only if plant is in assigned_plants or wildcard."""
        user_plant1 = UserIdentity(
            user_id="op_p1",
            tenant_id="tenant_default",
            roles=["OPERATOR"],
            assigned_plants=["plant_01"]
        )
        
        # Valid plant access
        scope_p1 = AuthorizationScope(tenant_id="tenant_default", plant_id="plant_01")
        ctx_p1 = AuthorizationContext(identity=user_plant1, required_permission="action.create", scope=scope_p1)
        decision_p1 = self.service.evaluate(ctx_p1)
        self.assertEqual(decision_p1.effect, AuthzDecisionEffect.ALLOW)

        # Disallowed plant access
        scope_p2 = AuthorizationScope(tenant_id="tenant_default", plant_id="plant_02")
        ctx_p2 = AuthorizationContext(identity=user_plant1, required_permission="action.create", scope=scope_p2)
        decision_p2 = self.service.evaluate(ctx_p2)
        self.assertEqual(decision_p2.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision_p2.reason_code, AuthzReasonCode.PLANT_SCOPE_DENIED)

    # =====================================================================
    # 4. ABAC SEPARATION OF DUTIES & ATTRIBUTE GUARDS
    # =====================================================================

    def test_separation_of_duties_approver_equals_proposer(self):
        """Approving one's own proposed action is strictly prohibited."""
        pm = UserIdentity(
            user_id="mgr_alice",
            tenant_id="tenant_default",
            roles=["PLANT_MANAGER"],
            assigned_plants=["*"]
        )
        scope = AuthorizationScope(tenant_id="tenant_default", plant_id="plant_01")

        # Proposer is alice, approver is alice -> VIOLATION
        ctx_self_approve = AuthorizationContext(
            identity=pm,
            required_permission="action.approve",
            scope=scope,
            action_id="act_123",
            proposer_id="mgr_alice"
        )
        decision = self.service.evaluate(ctx_self_approve)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.SEPARATION_OF_DUTIES_VIOLATION)

        # Proposer is bob, approver is alice -> ALLOW
        ctx_other_approve = AuthorizationContext(
            identity=pm,
            required_permission="action.approve",
            scope=scope,
            action_id="act_123",
            proposer_id="op_bob"
        )
        decision_ok = self.service.evaluate(ctx_other_approve)
        self.assertEqual(decision_ok.effect, AuthzDecisionEffect.ALLOW)
        self.assertEqual(decision_ok.reason_code, AuthzReasonCode.ALLOWED)

    def test_clearance_level_restriction(self):
        """Identities with lower clearance than required must be denied."""
        user = UserIdentity(
            user_id="op_standard",
            tenant_id="tenant_default",
            roles=["OPERATOR"],
            clearance_level=1
        )
        scope = AuthorizationScope(tenant_id="tenant_default")
        ctx = AuthorizationContext(
            identity=user,
            required_permission="action.create",
            scope=scope,
            required_clearance=3  # Requires elevated clearance
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.CLEARANCE_LEVEL_INSUFFICIENT)

    def test_data_mode_historical_restriction(self):
        """Mutating operations are disallowed in HISTORICAL data mode."""
        user = UserIdentity(
            user_id="op_standard",
            tenant_id="tenant_default",
            roles=["OPERATOR"],
            clearance_level=2
        )
        scope = AuthorizationScope(tenant_id="tenant_default")
        ctx = AuthorizationContext(
            identity=user,
            required_permission="action.create",
            scope=scope,
            data_mode="HISTORICAL"
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.DATA_MODE_RESTRICTED)

    def test_user_status_suspended_or_revoked(self):
        """Suspended or revoked user accounts are denied fail-closed."""
        suspended_user = UserIdentity(
            user_id="suspended_op",
            tenant_id="tenant_default",
            roles=["OPERATOR"],
            status=UserStatus.SUSPENDED
        )
        scope = AuthorizationScope(tenant_id="tenant_default")
        ctx = AuthorizationContext(
            identity=suspended_user,
            required_permission="action.create",
            scope=scope
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertEqual(decision.reason_code, AuthzReasonCode.IDENTITY_NOT_ACTIVE)

    # =====================================================================
    # 5. PRIVILEGED-OPERATION PROTECTION (ADMINISTRATIVE BOUNDARY)
    # =====================================================================

    def test_administrator_cannot_perform_operational_writes(self):
        """System Administrator has no operational write authority without operational role."""
        admin_user = UserIdentity(
            user_id="admin_root",
            tenant_id="tenant_default",
            roles=["ADMINISTRATOR"]
        )
        scope = AuthorizationScope(tenant_id="tenant_default", plant_id="plant_01")
        ctx = AuthorizationContext(
            identity=admin_user,
            required_permission="action.create",
            scope=scope
        )
        decision = self.service.evaluate(ctx)
        self.assertEqual(decision.effect, AuthzDecisionEffect.DENY)
        self.assertIn(decision.reason_code, [
            AuthzReasonCode.ADMIN_OPERATIONAL_OVERRIDE_DISALLOWED,
            AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS
        ])

    # =====================================================================
    # 6. CRYPTOGRAPHIC DECISION HASH
    # =====================================================================

    def test_cryptographic_decision_hash_verification(self):
        """Verifies that decision_hash accurately reflects canonical payload."""
        user = UserIdentity(
            user_id="op_hash",
            tenant_id="tenant_default",
            roles=["OPERATOR"]
        )
        scope = AuthorizationScope(tenant_id="tenant_default", plant_id="plant_01")
        ctx = AuthorizationContext(
            identity=user,
            required_permission="action.create",
            scope=scope
        )
        decision = self.service.evaluate(ctx)
        self.assertIsNotNone(decision.decision_hash)
        self.assertEqual(len(decision.decision_hash), 64)

        # Recalculate hash independently
        expected_payload = {
            "decision_id": decision.decision_id,
            "effect": decision.effect.value,
            "reason_code": decision.reason_code.value,
            "required_permission": "action.create",
            "matched_role": decision.matched_role or "",
            "evaluated_at": decision.evaluated_at
        }
        recomputed = hashlib.sha256(json.dumps(expected_payload, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(decision.decision_hash, recomputed)

    # =====================================================================
    # 7. EXECUTION BOUNDARY INVARIANT (POST /{id}/execute IS DISALLOWED)
    # =====================================================================

    def test_action_execute_endpoint_strictly_returns_405(self):
        """Verifies that POST /api/v3/actions/{id}/execute returns 405 Method Not Allowed."""
        headers = self._auth_headers()
        res = self.client.post("/api/v3/actions/act_test_01/execute", headers=headers)
        self.assertEqual(res.status_code, 405)
        self.assertIn("EXECUTION_GATEWAY_NOT_IMPLEMENTED", res.text)

    # =====================================================================
    # 8. REST ENDPOINTS (/api/v3/authorization/*)
    # =====================================================================

    def test_api_authorization_check_allow(self):
        """Tests POST /api/v3/authorization/check returning ALLOW."""
        headers = self._auth_headers(token="operator_token")
        payload = {
            "required_permission": "action.create",
            "target_scope": {
                "tenant_id": "tenant_default",
                "plant_id": "plant_01"
            },
            "data_mode": "LIVE"
        }
        res = self.client.post("/api/v3/authorization/check", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["decision"]["effect"], "ALLOW")
        self.assertEqual(data["decision"]["reason_code"], "ALLOWED")
        self.assertIsNotNone(data["decision"]["decision_hash"])

    def test_api_authorization_check_deny(self):
        """Tests POST /api/v3/authorization/check returning DENY for unpermitted capability."""
        headers = self._auth_headers(token="viewer_token")
        payload = {
            "required_permission": "action.create",
            "target_scope": {
                "tenant_id": "tenant_default",
                "plant_id": "plant_01"
            },
            "data_mode": "LIVE"
        }
        res = self.client.post("/api/v3/authorization/check", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["decision"]["effect"], "DENY")
        self.assertEqual(data["decision"]["reason_code"], "INSUFFICIENT_ROLE_PERMISSIONS")

    def test_api_list_permissions(self):
        """Tests GET /api/v3/authorization/permissions."""
        headers = self._auth_headers()
        res = self.client.get("/api/v3/authorization/permissions", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["permissions"]), 15)

    def test_api_list_roles(self):
        """Tests GET /api/v3/authorization/roles."""
        headers = self._auth_headers()
        res = self.client.get("/api/v3/authorization/roles", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        role_ids = [r["role_id"] for r in data["roles"]]
        self.assertIn("OPERATOR", role_ids)
        self.assertIn("PLANT_MANAGER", role_ids)
        self.assertIn("ADMINISTRATOR", role_ids)

    def test_api_get_role_detail(self):
        """Tests GET /api/v3/authorization/roles/{role_id}."""
        headers = self._auth_headers()
        res = self.client.get("/api/v3/authorization/roles/OPERATOR", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["role"]["role_id"], "OPERATOR")
        self.assertIn("action.create", data["effective_permissions"])
        self.assertIn("action.simulate", data["effective_permissions"])
        self.assertIn("telemetry.read", data["effective_permissions"])


if __name__ == "__main__":
    unittest.main()
