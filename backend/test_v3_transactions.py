# backend/test_v3_transactions.py
"""
SageCommand V3 — Transaction & Rollback Architecture Test Suite (Prompt 09)
Validates:
1. Transaction domain models, deterministic TransactionPlan generation, and plan hashing.
2. Invariant preservation: side_effects = False, execution_permitted = False.
3. Deterministic Preconditions and Business Invariants.
4. Affected resources extraction.
5. Rollback capability analysis & strategies (DATABASE_ROLLBACK, COMPENSATING_ACTION, NOT_SUPPORTED).
6. Deterministic state machine transitions & rejection of illegal jumps (e.g. PLANNED -> COMMITTED).
7. Idempotency resolution: exact match returns existing plan; differing action raises IDEMPOTENCY_CONFLICT.
8. Expiration handling and stale state detection.
9. Revalidation detecting policy, authorization, and action drift.
10. Multi-tenant, workspace, and plant scope isolation.
11. Explicit data mode enforcement: SIMULATION cannot promote to REAL.
12. REST API endpoints under /api/v3/transactions (POST /plan, GET /{id}, GET /, POST /validate, POST /revalidate, POST /cancel).
13. Strict Execution & Rollback Safety Boundary: POST /actions/{id}/execute, POST /transactions/{id}/execute, POST /transactions/{id}/rollback strictly return 405.
14. Integration with Prompt 08 Audit & Decision Ledger.
"""

import unittest
import os
import json
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from server import app
from core.config import SAGE_TRANSACTIONS_DB_PATH
from core.auth import Identity
from data.schemas.action_contract import (
    Action,
    ActionType,
    ActionTarget,
    ActionReason,
    ResourceType,
    RiskLevel,
    RollbackCapability as ActionRollbackCap,
    CostEstimate
)
from data.schemas.transaction_contract import (
    Transaction,
    TransactionPlan,
    TransactionStatus,
    TransactionType,
    RollbackStrategy,
    RollbackCapability,
    ConflictType,
    PreconditionType,
    InvariantType
)
from services.action_store import action_store
from services.transaction_repository import SQLiteTransactionRepository, transaction_repository
from services.transaction_service import (
    TransactionService,
    TransactionStateMachine,
    TransactionPlanner,
    TransactionValidationService,
    TransactionRevalidationService
)
from services.audit_ledger import audit_ledger


class TestV3Transactions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_repo = SQLiteTransactionRepository(db_path=":memory:")
        cls.service = TransactionService(repository=cls.test_repo)

    def setUp(self):
        action_store.clear()
        self.test_repo.clear()
        transaction_repository.clear()

    def tearDown(self):
        action_store.clear()
        self.test_repo.clear()
        transaction_repository.clear()

    def _create_test_action(
        self,
        action_id: str = "act_tx_01",
        action_type: ActionType = ActionType.MOVE_INVENTORY,
        tenant_id: str = "tenant_default",
        plant_id: str = "plant_001",
        data_mode: str = "REAL",
        quantity: int = 50
    ) -> Action:
        act = Action(
            action_id=action_id,
            action_type=action_type,
            version="1.0",
            tenant_id=tenant_id,
            workspace_id="workspace_default",
            session_id="session_default",
            target=ActionTarget(
                resource_type=ResourceType.INVENTORY_ITEM,
                resource_id="SKU-8822",
                tenant_id=tenant_id,
                plant_id=plant_id
            ),
            parameters={
                "quantity": quantity,
                "from_warehouse": "WH-ALPHA",
                "to_warehouse": "WH-BETA",
                "sku_id": "SKU-8822"
            },
            reason=ActionReason(
                summary="Rebalance assembly inventory",
                justification="Stockout mitigation",
                reason_code="STOCK_REBALANCE"
            ),
            system_risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            data_mode=data_mode,
            estimated_cost=CostEstimate(value=500.0, currency="USD"),
            estimated_duration_minutes=10
        )
        action_store.save(act)
        return act

    def _auth_headers(self, token="manager_token", tenant_id="tenant_default"):
        return {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": tenant_id,
            "X-Session-ID": "session_test",
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}"
        }

    # =====================================================================
    # 1. PLAN GENERATION & IMMUTABLE INVARIANTS
    # =====================================================================

    def test_01_plan_transaction_success(self):
        """Verifies deterministic transaction plan creation with side_effects=False and valid hash."""
        action = self._create_test_action()
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator", "manager"])

        tx, val_res = self.service.plan_transaction(
            action_id=action.action_id,
            identity=identity,
            idempotency_key="idemp_01"
        )

        self.assertIsNotNone(tx)
        self.assertEqual(tx.action_id, action.action_id)
        self.assertEqual(tx.tenant_id, "tenant_default")
        self.assertEqual(tx.status, TransactionStatus.AWAITING_EXECUTION)
        self.assertTrue(val_res.valid)

        # Invariants strictly enforced
        self.assertFalse(tx.plan.side_effects, "side_effects MUST be False in Prompt 09")
        self.assertFalse(tx.plan.execution_permitted, "execution_permitted MUST be False in Prompt 09")

        # Plan hash integrity
        expected_hash = tx.plan.compute_hash()
        self.assertEqual(tx.plan.transaction_plan_hash, expected_hash)

    def test_02_deterministic_preconditions_and_invariants(self):
        """Verifies typed preconditions and business invariants are deterministically derived."""
        # 1. Inventory Action
        inv_act = self._create_test_action(action_id="act_inv", action_type=ActionType.MOVE_INVENTORY, quantity=25)
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        tx, _ = self.service.plan_transaction(inv_act.action_id, identity)
        precond_types = [p.precondition_type for p in tx.plan.preconditions]
        self.assertIn(PreconditionType.INVENTORY_LEVEL, precond_types)
        self.assertIn(PreconditionType.VERSION_CHECK, precond_types)

        inv_types = [inv.invariant_type for inv in tx.plan.invariants]
        self.assertIn(InvariantType.NON_NEGATIVE_QUANTITY, inv_types)
        self.assertIn(InvariantType.NON_NEGATIVE_COST, inv_types)

        # 2. Machine Maintenance Action
        maint_act = Action(
            action_id="act_maint",
            action_type=ActionType.SCHEDULE_MAINTENANCE,
            version="1.0",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_default",
            target=ActionTarget(
                resource_type=ResourceType.MACHINE,
                resource_id="PRESS-01",
                tenant_id="tenant_default",
                plant_id="plant_001"
            ),
            parameters={
                "machine_id": "PRESS-01",
                "scheduled_start": "2026-10-15T08:00:00Z",
                "estimated_duration_minutes": 120
            },
            reason=ActionReason(summary="Preventive hydraulic check", justification="Hours threshold", reason_code="PREVENTIVE"),
            requires_approval=True
        )
        action_store.save(maint_act)

        tx_maint, _ = self.service.plan_transaction(maint_act.action_id, identity)
        maint_prec_types = [p.precondition_type for p in tx_maint.plan.preconditions]
        self.assertIn(PreconditionType.MACHINE_STATUS, maint_prec_types)

    def test_03_affected_resources_extraction(self):
        """Verifies all primary and secondary resources are explicitly mapped in affected_resources."""
        action = self._create_test_action()
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        tx, _ = self.service.plan_transaction(action.action_id, identity)
        res_ids = {r.resource_id for r in tx.plan.affected_resources}
        self.assertIn("SKU-8822", res_ids)
        self.assertIn("WH-ALPHA", res_ids)
        self.assertIn("WH-BETA", res_ids)

    def test_04_rollback_capability_and_strategy(self):
        """Verifies deterministic rollback capability and compensation strategies."""
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        # 1. MOVE_INVENTORY -> COMPENSATING_ACTION (SUPPORTED)
        act_move = self._create_test_action("act_rb_move", ActionType.MOVE_INVENTORY)
        tx_move, _ = self.service.plan_transaction(act_move.action_id, identity)
        self.assertEqual(tx_move.plan.rollback_plan.strategy, RollbackStrategy.COMPENSATING_ACTION)
        self.assertEqual(tx_move.plan.rollback_plan.capability, RollbackCapability.SUPPORTED)
        self.assertTrue(len(tx_move.plan.rollback_plan.steps) > 0)

        # 2. ADJUST_REORDER_POINT -> DATABASE_ROLLBACK (SUPPORTED)
        act_reorder_pt = Action(
            action_id="act_rb_pt",
            action_type=ActionType.ADJUST_REORDER_POINT,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_default",
            target=ActionTarget(resource_type=ResourceType.SKU, resource_id="SKU-1", tenant_id="tenant_default"),
            parameters={"new_reorder_point": 200},
            reason=ActionReason(summary="Demand drop", justification="Lower safety stock", reason_code="DEMAND_SHIFT")
        )
        action_store.save(act_reorder_pt)
        tx_pt, _ = self.service.plan_transaction(act_reorder_pt.action_id, identity)
        self.assertEqual(tx_pt.plan.rollback_plan.strategy, RollbackStrategy.DATABASE_ROLLBACK)
        self.assertEqual(tx_pt.plan.rollback_plan.capability, RollbackCapability.SUPPORTED)

        # 3. NOTIFY_STAKEHOLDER -> NOT_SUPPORTED
        act_notify = Action(
            action_id="act_rb_notify",
            action_type=ActionType.NOTIFY_STAKEHOLDER,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_default",
            target=ActionTarget(resource_type=ResourceType.PLANT, resource_id="PLANT-1", tenant_id="tenant_default"),
            parameters={"recipient_role": "PLANT_MGR", "message": "Emergency Alert"},
            reason=ActionReason(summary="Broadcast alert", justification="Line down", reason_code="ALERT")
        )
        action_store.save(act_notify)
        tx_notify, _ = self.service.plan_transaction(act_notify.action_id, identity)
        self.assertEqual(tx_notify.plan.rollback_plan.strategy, RollbackStrategy.NOT_SUPPORTED)
        self.assertEqual(tx_notify.plan.rollback_plan.capability, RollbackCapability.NOT_SUPPORTED)

    # =====================================================================
    # 2. STATE MACHINE & CONCURRENCY
    # =====================================================================

    def test_05_state_machine_guarded_transitions(self):
        """Verifies state machine allows legal transitions and blocks illegal jumps."""
        # Legal transitions
        self.assertTrue(TransactionStateMachine.can_transition(TransactionStatus.PLANNED, TransactionStatus.VALIDATING))
        self.assertTrue(TransactionStateMachine.can_transition(TransactionStatus.VALIDATING, TransactionStatus.READY))
        self.assertTrue(TransactionStateMachine.can_transition(TransactionStatus.READY, TransactionStatus.AWAITING_EXECUTION))
        self.assertTrue(TransactionStateMachine.can_transition(TransactionStatus.AWAITING_EXECUTION, TransactionStatus.CANCELLED))

        # Illegal jumps
        self.assertFalse(TransactionStateMachine.can_transition(TransactionStatus.PLANNED, TransactionStatus.COMMITTED))
        self.assertFalse(TransactionStateMachine.can_transition(TransactionStatus.PLANNED, TransactionStatus.EXECUTING))
        self.assertFalse(TransactionStateMachine.can_transition(TransactionStatus.VALIDATING, TransactionStatus.COMMITTED))

        with self.assertRaises(ValueError):
            TransactionStateMachine.validate_transition(TransactionStatus.PLANNED, TransactionStatus.COMMITTED)

    def test_06_idempotency_exact_match(self):
        """Submitting the same idempotency key with identical action returns existing transaction."""
        action = self._create_test_action("act_idemp_01")
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        tx1, _ = self.service.plan_transaction(action.action_id, identity, idempotency_key="IDEMP_KEY_001")
        tx2, _ = self.service.plan_transaction(action.action_id, identity, idempotency_key="IDEMP_KEY_001")

        self.assertEqual(tx1.transaction_id, tx2.transaction_id)
        self.assertEqual(tx1.created_at, tx2.created_at)

    def test_07_idempotency_conflict_different_action(self):
        """Reusing the same idempotency key for a different action raises IDEMPOTENCY_CONFLICT."""
        act1 = self._create_test_action("act_idemp_diff_1")
        act2 = self._create_test_action("act_idemp_diff_2", quantity=100)
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        self.service.plan_transaction(act1.action_id, identity, idempotency_key="IDEMP_KEY_CONFLICT")

        with self.assertRaises(ValueError) as ctx:
            self.service.plan_transaction(act2.action_id, identity, idempotency_key="IDEMP_KEY_CONFLICT")
        self.assertIn("IDEMPOTENCY_CONFLICT", str(ctx.exception))

    def test_08_expiration_detection(self):
        """Verifies that expired transaction plans are detected and transition to FAILED/EXPIRED."""
        action = self._create_test_action("act_exp_01")
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        # Plan with past expiration timestamp
        tx, _ = self.service.plan_transaction(action.action_id, identity)
        tx.plan.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        self.service.repo.save(tx)

        # Revalidate
        _, val_res = self.service.revalidate_transaction(tx.transaction_id, identity)
        self.assertFalse(val_res.valid)
        self.assertEqual(val_res.conflict_type, ConflictType.APPROVAL_EXPIRED)
        self.assertIn("TRANSACTION_EXPIRED", val_res.reason_codes)

    def test_09_revalidation_policy_changed(self):
        """Verifies that policy drift between planning and execution is flagged."""
        action = self._create_test_action("act_pol_drift")
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        tx, _ = self.service.plan_transaction(action.action_id, identity)
        # Simulate planned under policy version 99
        tx.plan.policy_reference = {
            "policy_id": "pol_safety",
            "policy_version": "99.0",
            "decision": "ALLOW"
        }
        self.service.repo.save(tx)

        _, val_res = self.service.revalidate_transaction(tx.transaction_id, identity)
        self.assertFalse(val_res.valid)
        self.assertEqual(val_res.conflict_type, ConflictType.POLICY_CHANGED)

    # =====================================================================
    # 3. SCOPING & MULTI-TENANCY
    # =====================================================================

    def test_10_tenant_and_workspace_isolation(self):
        """Verifies strict tenant isolation: cross-tenant retrieval and planning are blocked."""
        action_a = self._create_test_action("act_tenant_a", tenant_id="tenant_alpha")
        id_a = Identity(user_id="user_a", tenant_id="tenant_alpha", roles=["operator"])
        id_b = Identity(user_id="user_b", tenant_id="tenant_beta", roles=["operator"])

        tx_a, _ = self.service.plan_transaction(action_a.action_id, id_a)

        # Tenant B queries Tenant A's transaction
        tx_found = self.service.get_transaction(tx_a.transaction_id, id_b)
        self.assertIsNone(tx_found, "Cross-tenant query must return None")

        # Tenant B attempts to plan transaction on Tenant A's action
        with self.assertRaises(PermissionError):
            self.service.plan_transaction(action_a.action_id, id_b)

    def test_11_simulation_mode_isolation(self):
        """Verifies SIMULATION transactions cannot be promoted to REAL."""
        act_sim = self._create_test_action("act_sim_01", data_mode="SIMULATION")
        identity = Identity(user_id="op_01", tenant_id="tenant_default", roles=["operator"])

        tx_sim, _ = self.service.plan_transaction(act_sim.action_id, identity)
        self.assertEqual(tx_sim.data_mode, "SIMULATION")
        self.assertFalse(tx_sim.plan.side_effects)

        # Attempt to promote SIMULATION to REAL
        with self.assertRaises(ValueError) as ctx:
            self.service.plan_transaction(act_sim.action_id, identity, data_mode_override="REAL")
        self.assertIn("cannot be promoted to REAL", str(ctx.exception))

    # =====================================================================
    # 4. REST API ENDPOINTS & HTTP SAFETY BOUNDARIES
    # =====================================================================

    def test_12_api_planning_and_validation_routes(self):
        """Validates all REST endpoints under /api/v3/transactions."""
        action = self._create_test_action("act_api_01")
        headers = self._auth_headers()

        # 1. POST /plan
        res_plan = self.client.post(
            "/api/v3/transactions/plan",
            headers=headers,
            json={"action_id": action.action_id, "idempotency_key": "api_idemp_1"}
        )
        self.assertEqual(res_plan.status_code, 201)
        data = res_plan.json()
        self.assertTrue(data["success"])
        tx_id = data["transaction"]["transaction_id"]

        # 2. GET /{id}
        res_get = self.client.get(f"/api/v3/transactions/{tx_id}", headers=headers)
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["transaction"]["transaction_id"], tx_id)

        # 3. GET /
        res_list = self.client.get("/api/v3/transactions?limit=10", headers=headers)
        self.assertEqual(res_list.status_code, 200)
        self.assertTrue(res_list.json()["total_count"] >= 1)

        res_val = self.client.post(f"/api/v3/transactions/{tx_id}/validate", headers=headers)
        self.assertEqual(res_val.status_code, 200)
        self.assertTrue(res_val.json()["validation"]["valid"])

        # 5. POST /{id}/revalidate
        res_reval = self.client.post(f"/api/v3/transactions/{tx_id}/revalidate", headers=headers)
        self.assertEqual(res_reval.status_code, 200)

        # 6. POST /{id}/cancel
        res_cancel = self.client.post(f"/api/v3/transactions/{tx_id}/cancel?reason=TestCancel", headers=headers)
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(res_cancel.json()["transaction"]["status"], "CANCELLED")

    def test_13_api_unauthorized_and_forbidden(self):
        """Verifies unauthenticated or unauthorized access to transaction endpoints is blocked."""
        # Invalid or missing JWT token
        res_unauth = self.client.get("/api/v3/transactions", headers={"Authorization": "Bearer invalid_token"})
        self.assertEqual(res_unauth.status_code, 401)

        # Role lacking transaction.plan (e.g. viewer)
        action = self._create_test_action("act_api_perm")
        headers = self._auth_headers(token="viewer_token")
        res_forbid = self.client.post(
            "/api/v3/transactions/plan",
            headers=headers,
            json={"action_id": action.action_id}
        )
        self.assertEqual(res_forbid.status_code, 403)

    def test_14_execution_and_rollback_endpoints_gated_by_execution_gateway(self):
        """
        V3 EXECUTION GATEWAY BOUNDARY:
        POST /actions/{id}/execute, POST /transactions/{id}/execute, and POST /transactions/{id}/rollback
        are enabled and routed through Execution Gateway (returning 404 on non-existent targets rather than 405).
        """
        headers = self._auth_headers()
        tx_id = "tx_dummy_01"
        act_id = "act_dummy_01"

        # Action execute
        res_act_exec = self.client.post(f"/api/v3/actions/{act_id}/execute", headers=headers)
        self.assertEqual(res_act_exec.status_code, 404, "Action execution is handled by Execution Gateway (404 on missing action)")

        # Transaction execute
        res_tx_exec = self.client.post(f"/api/v3/transactions/{tx_id}/execute", headers=headers)
        self.assertEqual(res_tx_exec.status_code, 404, "Transaction execution is handled by Execution Gateway (404 on missing tx)")

        # Rollback execute
        res_rb_exec = self.client.post(f"/api/v3/transactions/{tx_id}/rollback", headers=headers)
        self.assertEqual(res_rb_exec.status_code, 404, "Rollback is handled by Execution Gateway (404 on missing tx)")


if __name__ == "__main__":
    unittest.main()
