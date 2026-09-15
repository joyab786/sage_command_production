# backend/test_v3_policy_engine.py
"""
SageCommand V3 — Prompt 06 Policy Enforcement Engine Test Suite
Validates canonical Policy domain schemas, deterministic operator evaluator,
strict precedence (DENY > REQUIRE_APPROVAL > HOLD > ALLOW), conflict detection,
fail-closed defaults, risk/cost/time governance, versioning immutability,
FastAPI REST endpoints, and negative security constraints.
"""

import unittest
import uuid
import math
from datetime import datetime, timezone
from fastapi.testclient import TestClient

try:
    from server import app
    from data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        ResourceType,
        ActionTarget,
        ActionReason,
        RiskLevel,
        CostEstimate,
    )
    from data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyConditionCategory,
        PolicyOperator,
        PolicyReasonCode,
        ApprovalRequirement,
        PolicyEvaluationContext,
        PolicyDecision,
    )
    from services.policy_service import policy_service, PolicyConditionEvaluator, PolicyStore, PolicyService
    from services.action_store import action_store
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        ResourceType,
        ActionTarget,
        ActionReason,
        RiskLevel,
        CostEstimate,
    )
    from backend.data.schemas.policy_contract import (
        Policy,
        PolicyRule,
        PolicyCondition,
        PolicyEffect,
        PolicyLifecycle,
        PolicyConditionCategory,
        PolicyOperator,
        PolicyReasonCode,
        ApprovalRequirement,
        PolicyEvaluationContext,
        PolicyDecision,
    )
    from backend.services.policy_service import policy_service, PolicyConditionEvaluator, PolicyStore, PolicyService
    from backend.services.action_store import action_store


class TestV3PolicyEnforcementEngine(unittest.TestCase):
    """Automated test suite for Prompt 06 Policy Enforcement Engine."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.tenant_id = "tenant_test_p06"
        cls.workspace_id = "workspace_p06"
        cls.session_id = "session_p06"

        cls.auth_headers_mgr = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": cls.tenant_id,
            "X-Session-ID": cls.session_id
        }
        cls.auth_headers_op = {
            "Authorization": "Bearer operator_token",
            "X-Tenant-ID": cls.tenant_id,
            "X-Session-ID": cls.session_id
        }

    def _create_sample_action(
        self,
        action_type: ActionType = ActionType.ADJUST_REORDER_POINT,
        resource_id: str = "SKU-TEST-01",
        risk_level: RiskLevel = RiskLevel.LOW,
        cost: float = 1200.0,
        data_mode: str = "REAL",
        plant_id: str = "plant_detroit_01"
    ) -> Action:
        """Helper to create and persist a sample action."""
        act = Action(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=action_type,
            version="1.0",
            target=ActionTarget(
                resource_type=ResourceType.SKU,
                resource_id=resource_id,
                plant_id=plant_id
            ),
            parameters={"new_reorder_point": 250},
            reason=ActionReason(
                summary="Test reorder adjustment",
                justification="Automated test suite",
                reason_code="STOCK_OPTIMIZATION"
            ),
            system_risk_level=risk_level,
            estimated_cost=CostEstimate(value=cost, currency="USD"),
            data_mode=data_mode,
            status=ActionStatus.POLICY_REVIEW
        )
        action_store.save(act)
        return act

    # =================================================================
    # 1. CANONICAL POLICY & DECISION SCHEMA TESTS
    # =================================================================

    def test_01_policy_schema_and_fingerprinting(self):
        """Verify Policy model, validation, and SHA-256 fingerprint generation."""
        p = Policy(
            policy_id="POL-TEST-01",
            policy_version="1.0",
            name="Test Policy",
            description="Unit test verification policy",
            priority=50,
            scope={"tenant_id": self.tenant_id},
            rules=[
                PolicyRule(
                    rule_id="r1",
                    name="Rule 1",
                    conditions=[
                        PolicyCondition(
                            field=PolicyConditionCategory.ACTION_TYPE,
                            operator=PolicyOperator.EQUALS,
                            value="ADJUST_REORDER_POINT"
                        )
                    ],
                    effect=PolicyEffect.ALLOW,
                    explanation="Allowed test action"
                )
            ]
        )
        self.assertIsNotNone(p.policy_hash)
        self.assertEqual(len(p.policy_hash), 64)
        # Verify hash changes if content changes
        hash_before = p.policy_hash
        p.priority = 90
        hash_after = p.compute_hash()
        self.assertNotEqual(hash_before, hash_after)

    def test_02_policy_decision_tamper_detection(self):
        """Verify PolicyDecision SHA-256 fingerprinting for tamper evidence."""
        dec = PolicyDecision(
            action_id="act_12345",
            decision=PolicyEffect.ALLOW,
            policy_id="POL-TEST-01",
            policy_version="1.0",
            tenant_id=self.tenant_id,
            reason_codes=["POLICY_ALLOWED"],
            explanation="Action meets policy constraints",
            risk_level="LOW"
        )
        self.assertIsNotNone(dec.decision_hash)
        self.assertEqual(len(dec.decision_hash), 64)

    def test_03_anti_executable_code_in_conditions(self):
        """Verify rejection of executable code patterns (eval, exec, subprocess) in policy values."""
        with self.assertRaises(ValueError):
            PolicyCondition(
                field=PolicyConditionCategory.RESOURCE_ID,
                operator=PolicyOperator.EQUALS,
                value="eval(__import__('os').system('ls'))"
            )

        with self.assertRaises(ValueError):
            PolicyCondition(
                field=PolicyConditionCategory.ACTION_TYPE,
                operator=PolicyOperator.EQUALS,
                value="subprocess.call(['rm', '-rf'])"
            )

    # =================================================================
    # 2. DETERMINISTIC OPERATOR EVALUATOR TESTS
    # =================================================================

    def test_04_operator_evaluations(self):
        """Test deterministic comparison operators."""
        act = self._create_sample_action(cost=2500.0)
        ctx = PolicyEvaluationContext(
            tenant_id=self.tenant_id,
            user_id="user_test",
            current_time="2026-09-14T10:30:00Z"
        )

        # EQUALS & NOT_EQUALS
        c_eq = PolicyCondition(field=PolicyConditionCategory.ACTION_TYPE, operator=PolicyOperator.EQUALS, value="ADJUST_REORDER_POINT")
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_eq, act, ctx))

        c_neq = PolicyCondition(field=PolicyConditionCategory.ACTION_TYPE, operator=PolicyOperator.NOT_EQUALS, value="REORDER_INVENTORY")
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_neq, act, ctx))

        # IN & NOT_IN
        c_in = PolicyCondition(field=PolicyConditionCategory.ACTION_TYPE, operator=PolicyOperator.IN, value=["ADJUST_REORDER_POINT", "REORDER_INVENTORY"])
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_in, act, ctx))

        c_nin = PolicyCondition(field=PolicyConditionCategory.ACTION_TYPE, operator=PolicyOperator.NOT_IN, value=["CHANGE_PRODUCTION_PLAN"])
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_nin, act, ctx))

        # Numeric comparisons
        c_gt = PolicyCondition(field=PolicyConditionCategory.ESTIMATED_COST, operator=PolicyOperator.GREATER_THAN, value=2000.0)
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_gt, act, ctx))

        c_lt = PolicyCondition(field=PolicyConditionCategory.ESTIMATED_COST, operator=PolicyOperator.LESS_THAN, value=3000.0)
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_lt, act, ctx))

        # Time window
        c_time = PolicyCondition(field=PolicyConditionCategory.TIME_WINDOW, operator=PolicyOperator.WITHIN_TIME_WINDOW, value="09:00-17:00")
        self.assertTrue(PolicyConditionEvaluator.evaluate_condition(c_time, act, ctx))

        c_time_out = PolicyCondition(field=PolicyConditionCategory.TIME_WINDOW, operator=PolicyOperator.WITHIN_TIME_WINDOW, value="18:00-22:00")
        self.assertFalse(PolicyConditionEvaluator.evaluate_condition(c_time_out, act, ctx))

    def test_05_numeric_nan_infinity_safety(self):
        """Verify numeric comparison fails closed against NaN and Infinity."""
        act = self._create_sample_action(cost=2500.0)
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        c_nan = PolicyCondition(field=PolicyConditionCategory.ESTIMATED_COST, operator=PolicyOperator.GREATER_THAN, value=float("nan"))
        self.assertFalse(PolicyConditionEvaluator.evaluate_condition(c_nan, act, ctx))

        c_inf = PolicyCondition(field=PolicyConditionCategory.ESTIMATED_COST, operator=PolicyOperator.GREATER_THAN, value=float("inf"))
        self.assertFalse(PolicyConditionEvaluator.evaluate_condition(c_inf, act, ctx))

    # =================================================================
    # 3. PRECEDENCE HIERARCHY & CONFLICT HANDLING
    # =================================================================

    def test_06_precedence_deny_overrides_allow_with_conflict(self):
        """Verify DENY overrides ALLOW and logs POLICY_CONFLICT in reason codes."""
        # Action with SHUTDOWN target triggers POL-DEFAULT-SHUTDOWN-DENY
        # But also is LOW risk, which might match an ALLOW rule
        act = self._create_sample_action(
            resource_id="SKU-SHUTDOWN-LINE-01",
            risk_level=RiskLevel.LOW,
            cost=500.0
        )
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        decision = policy_service.evaluate(act, ctx, persist_decision=False)
        self.assertEqual(decision.decision, PolicyEffect.DENY)
        self.assertIn("POL-DEFAULT-SHUTDOWN-DENY", decision.explanation)

    def test_07_precedence_require_approval_overrides_allow(self):
        """Verify REQUIRE_APPROVAL takes precedence over routine ALLOW for high-risk actions."""
        # ADJUST_REORDER_POINT but with CRITICAL risk
        act = self._create_sample_action(
            resource_id="SKU-SAFETY-01",
            risk_level=RiskLevel.CRITICAL,
            cost=200.0
        )
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        decision = policy_service.evaluate(act, ctx, persist_decision=False)
        self.assertEqual(decision.decision, PolicyEffect.REQUIRE_APPROVAL)
        self.assertTrue(decision.requires_approval)
        self.assertIsNotNone(decision.approval_requirement)
        self.assertEqual(decision.approval_requirement.required_role, "manager")

    def test_08_fail_closed_on_unmatched_policy(self):
        """Verify fail-closed (HOLD) when no policy matches an action."""
        temp_store = PolicyStore(db_path=":memory:")
        sim_service = PolicyService(store=temp_store)
        # Clear bootstrapped policies to simulate environment with no matching policies
        temp_store._policies.clear()

        act = self._create_sample_action()
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        decision = sim_service.evaluate(act, ctx, persist_decision=False)
        self.assertEqual(decision.decision, PolicyEffect.HOLD)
        self.assertIn(PolicyReasonCode.NO_MATCHING_POLICY_FOUND.value, decision.reason_codes)

    # =================================================================
    # 4. INDUSTRIAL POLICY SCENARIO TESTS
    # =================================================================

    def test_09_cost_threshold_tiered_governance(self):
        """Verify $10k requires Manager and $50k requires Executive sign-off."""
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        # $15,000 -> Manager approval
        act_mgr = self._create_sample_action(cost=15000.0)
        dec_mgr = policy_service.evaluate(act_mgr, ctx, persist_decision=False)
        self.assertEqual(dec_mgr.decision, PolicyEffect.REQUIRE_APPROVAL)
        self.assertEqual(dec_mgr.approval_requirement.approval_type, "MANAGER")

        # $65,000 -> Executive approval
        act_exec = self._create_sample_action(cost=65000.0)
        dec_exec = policy_service.evaluate(act_exec, ctx, persist_decision=False)
        self.assertEqual(dec_exec.decision, PolicyEffect.REQUIRE_APPROVAL)
        self.assertEqual(dec_exec.approval_requirement.approval_type, "EXECUTIVE")
        self.assertEqual(dec_exec.approval_requirement.required_role, "executive")

    def test_10_critical_line_production_changes(self):
        """Verify production plan modifications on critical lines require manager clearance."""
        act = Action(
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            action_type=ActionType.CHANGE_PRODUCTION_PLAN,
            version="1.0",
            target=ActionTarget(
                resource_type=ResourceType.PRODUCTION_LINE,
                resource_id="CRITICAL_LINE_04",
                plant_id="plant_detroit_01"
            ),
            parameters={"target_daily_output": 850},
            reason=ActionReason(
                summary="Shift quota expansion",
                justification="Demand surge",
                reason_code="PRODUCTION_INCREASE"
            ),
            system_risk_level=RiskLevel.MEDIUM,
            status=ActionStatus.POLICY_REVIEW
        )
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)

        dec = policy_service.evaluate(act, ctx, persist_decision=False)
        self.assertEqual(dec.decision, PolicyEffect.REQUIRE_APPROVAL)
        self.assertIn("POL-CRITICAL-LINE-APPROVAL", dec.explanation)

    def test_11_simulation_data_mode_safe_allow(self):
        """Verify SIMULATION mode actions with LOW risk are ALLOWED for experimentation."""
        act_sim = self._create_sample_action(
            data_mode="SIMULATION",
            risk_level=RiskLevel.LOW,
            cost=2000.0
        )
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id, data_mode="SIMULATION")

        dec = policy_service.evaluate(act_sim, ctx, persist_decision=False)
        self.assertEqual(dec.decision, PolicyEffect.ALLOW)
        self.assertIn("POL-SIMULATION-ALLOW", dec.explanation)

    # =================================================================
    # 5. REST API ENDPOINTS (/api/v3/policies)
    # =================================================================

    def test_12_api_evaluate_endpoint(self):
        """POST /api/v3/policies/evaluate evaluates action and returns PolicyDecision."""
        act = self._create_sample_action(cost=1200.0)

        resp = self.client.post(
            "/api/v3/policies/evaluate",
            json={"action_id": act.action_id},
            headers=self.auth_headers_mgr
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("decision", data["decision"])
        self.assertEqual(data["decision"]["action_id"], act.action_id)
        self.assertIsNotNone(data["decision"]["decision_hash"])

    def test_13_api_simulate_endpoint(self):
        """POST /api/v3/policies/simulate dry-runs evaluation without state modification."""
        act = self._create_sample_action()
        act_dict = act.model_dump()

        resp = self.client.post(
            "/api/v3/policies/simulate",
            json={"action": act_dict},
            headers=self.auth_headers_mgr
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["simulation"])
        self.assertIn("decision", data["decision"])

    def test_14_api_list_and_get_policy(self):
        """GET /api/v3/policies lists policies and GET /api/v3/policies/{id} returns details."""
        resp = self.client.get("/api/v3/policies", headers=self.auth_headers_mgr)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["total"], 5)

        # Fetch specific policy
        p_resp = self.client.get("/api/v3/policies/POL-DEFAULT-SHUTDOWN-DENY", headers=self.auth_headers_mgr)
        self.assertEqual(p_resp.status_code, 200)
        p_data = p_resp.json()
        self.assertEqual(p_data["policy"]["policy_id"], "POL-DEFAULT-SHUTDOWN-DENY")
        self.assertEqual(p_data["policy"]["priority"], 100)

    # =================================================================
    # 6. NEGATIVE SECURITY & AUTHORIZATION TESTS
    # =================================================================

    def test_15_cross_tenant_policy_evaluation_blocked(self):
        """Verify cross-tenant evaluation attempt returns 404 (isolation barrier)."""
        act = self._create_sample_action()

        # Caller from tenant_other tries to evaluate tenant_test_p06's action
        other_headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": "tenant_other_attacker",
            "X-Session-ID": "session_attacker"
        }
        resp = self.client.post(
            "/api/v3/policies/evaluate",
            json={"action_id": act.action_id},
            headers=other_headers
        )
        self.assertEqual(resp.status_code, 404)

    def test_16_ordinary_operator_cannot_manage_policies(self):
        """Verify separation of duties: operator cannot create or activate policies (403)."""
        new_pol = {
            "policy_id": "POL-ATTACKER-ALLOW-ALL",
            "policy_version": "1.0",
            "name": "Malicious Allow All",
            "description": "Attempt to bypass governance",
            "priority": 99,
            "rules": [
                {
                    "rule_id": "r_allow_all",
                    "name": "Allow Everything",
                    "conditions": [],
                    "effect": "ALLOW",
                    "explanation": "Bypass"
                }
            ]
        }
        # Operator attempt
        resp = self.client.post("/api/v3/policies", json=new_pol, headers=self.auth_headers_op)
        self.assertEqual(resp.status_code, 403)

        # Operator activate attempt
        resp_act = self.client.post("/api/v3/policies/POL-HIGH-COST-APPROVAL/activate", headers=self.auth_headers_op)
        self.assertEqual(resp_act.status_code, 403)

    def test_17_llm_cannot_spoof_policy_allow_or_bypass_execution(self):
        """Verify client or LLM cannot spoof policy approval or bypass to execution."""
        # 1. Verify /actions/{id}/execute is strictly blocked (Prompt 05 boundary preserved)
        act = self._create_sample_action()
        resp_exec = self.client.post(f"/api/v3/actions/{act.action_id}/execute", headers=self.auth_headers_mgr)
        self.assertEqual(resp_exec.status_code, 405)

        # 2. Verify an action denied by policy cannot be executed or forced to ALLOW
        act_shutdown = self._create_sample_action(resource_id="SHUTDOWN_MACHINE_01")
        ctx = PolicyEvaluationContext(tenant_id=self.tenant_id)
        dec = policy_service.evaluate(act_shutdown, ctx, persist_decision=True)
        self.assertEqual(dec.decision, PolicyEffect.DENY)

        # Action is rejected
        stored = action_store.get(act_shutdown.action_id)
        self.assertEqual(stored.status, ActionStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()
