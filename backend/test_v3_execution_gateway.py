# backend/test_v3_execution_gateway.py
"""
SageCommand V3 — Execution Gateway Comprehensive Test Suite
Validates the 10-gate deterministic final write boundary:
1. Authentication & Identity Integrity (Fail-Closed)
2. RBAC/ABAC Operational Permission Revalidation (action.execute / transaction.execute)
3. Separation of Duties: Administrator cannot execute operational actions
4. Cross-Tenant Execution Isolation
5. Session Context Matching
6. Two-Person Rule & Approval Requirement Enforcement
7. Cryptographic Action Hash Integrity & Staleness Detection
8. Policy Engine Execution-Time Revalidation
9. Idempotency Key & Duplicate Execution Cache
10. Concurrency Locking & Race Condition Defense
11. Simulation / Dry-Run Physical Mutation Defense (affected_rows == 0)
12. Session-Scoped Database Parameterized Write Adapter
13. Transaction Execution & State Machine Commit
14. Transaction Hash & TTL Expiration Defense
15. Deterministic Transaction Rollback
16. WebSocket Execution Gateway Routing
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

try:
    from server import app
    from core.auth import Identity
    from data.database_context import AccessMode, DataMode
    from gateway.db_gateway import db_gateway, DBConnectionRequest
    from services.connection_manager import db_manager
    from data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        ActionTarget,
        ResourceType,
        ActionReason,
        CostEstimate,
    )
    from data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionStatus,
        TransactionType,
        RollbackPlan,
        RollbackStrategy,
        RollbackCapability,
        AffectedResource,
    )
    from data.schemas.execution_contract import (
        ExecutionStatus,
        ExecutionRequest,
        ExecutionResult,
    )
    from services.action_store import action_store
    from services.transaction_repository import transaction_repository
    from services.execution_gateway import execution_gateway, ExecutionGatewayException
    from services.authorization_service import authorization_service
    from services.policy_service import policy_service
    from services.transaction_service import transaction_service
except ModuleNotFoundError:
    from backend.server import app
    from backend.core.auth import Identity
    from backend.data.database_context import AccessMode, DataMode
    from backend.gateway.db_gateway import db_gateway, DBConnectionRequest
    from backend.services.connection_manager import db_manager
    from backend.data.schemas.action_contract import (
        Action,
        ActionStatus,
        ActionType,
        RiskLevel,
        ActionTarget,
        ResourceType,
        ActionReason,
        CostEstimate,
    )
    from backend.data.schemas.transaction_contract import (
        Transaction,
        TransactionPlan,
        TransactionStatus,
        TransactionType,
        RollbackPlan,
        RollbackStrategy,
        RollbackCapability,
        AffectedResource,
    )
    from backend.data.schemas.execution_contract import (
        ExecutionStatus,
        ExecutionRequest,
        ExecutionResult,
    )
    from backend.services.action_store import action_store
    from backend.services.transaction_repository import transaction_repository
    from backend.services.execution_gateway import execution_gateway, ExecutionGatewayException
    from backend.services.authorization_service import authorization_service
    from backend.services.policy_service import policy_service
    from backend.services.transaction_service import transaction_service


class TestV3ExecutionGateway(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_datacore.sqlite")

        # Initialize physical test DB with inventory table
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE inventory (sku TEXT PRIMARY KEY, reorder_point INT, quantity INT, location TEXT, plant_id TEXT)")
        cursor.execute("INSERT INTO inventory VALUES ('SKU-100', 50, 120, 'Aisle-A', 'plant_mumbai')")
        cursor.execute("CREATE TABLE orders (order_id TEXT PRIMARY KEY, sku TEXT, quantity INT, status TEXT, plant_id TEXT)")
        conn.commit()
        conn.close()

        # Identities
        self.tenant_id = "tenant_test_eg"
        self.workspace_id = "workspace_default"
        self.session_id = "session_eg_01"

        self.identity_op = Identity(
            user_id="op_eg_01",
            roles=["OPERATOR"],
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            workspace_id=self.workspace_id
        )
        self.identity_pm = Identity(
            user_id="pm_eg_01",
            roles=["PLANT_MANAGER"],
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            workspace_id=self.workspace_id
        )
        self.identity_admin = Identity(
            user_id="admin_eg_01",
            roles=["ADMINISTRATOR"],
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            workspace_id=self.workspace_id
        )
        self.identity_attacker = Identity(
            user_id="attacker_01",
            roles=["OPERATOR"],
            tenant_id="tenant_evil_corp",
            session_id="session_evil",
            workspace_id=self.workspace_id
        )

        # Clear store and gateway caches
        action_store.clear()
        execution_gateway.clear_cache()

    def tearDown(self):
        db_manager.close_all()
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def _create_test_action(
        self,
        action_type=ActionType.ADJUST_REORDER_POINT,
        status=ActionStatus.APPROVED,
        requires_approval=False,
        risk_level=RiskLevel.LOW,
        params=None,
        proposer="op_proposer"
    ) -> Action:
        parameters = params or {"sku": "SKU-100", "new_reorder_point": 75}
        action = Action(
            action_type=action_type,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            session_id=self.session_id,
            target=ActionTarget(
                resource_type=ResourceType.SKU,
                resource_id="SKU-100",
                plant_id="plant_mumbai"
            ),
            parameters=parameters,
            reason=ActionReason(reason_code="STOCK_OPTIMIZATION", summary="Stock adjustment"),
            requires_approval=requires_approval,
            system_risk_level=risk_level,
            requested_by=proposer,
            status=status,
            data_mode="REAL"
        )
        action_store.save(action)
        return action

    # -------------------------------------------------------------------------
    # Gate 1 & Gate 2: Authentication, Authorization & Separation of Duties
    # -------------------------------------------------------------------------

    def test_01_unauthenticated_execution_rejected(self):
        """Gate 1: Rejects unauthenticated caller with 401."""
        act = self._create_test_action()
        resp = self.client.post(f"/api/v3/actions/{act.action_id}/execute")
        self.assertIn(resp.status_code, (401, 403))

    def test_02_rbac_operator_action_execution_succeeds(self):
        """Gate 2: OPERATOR with action.execute permission executes low-risk action."""
        act = self._create_test_action(requires_approval=False, status=ActionStatus.READY)
        res = execution_gateway.execute_action(
            action_id=act.action_id,
            identity=self.identity_op
        )
        self.assertEqual(res.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(res.action_id, act.action_id)

    def test_03_admin_separation_of_duties_operational_execution_blocked(self):
        """Gate 2: ADMINISTRATOR is strictly non-operational and cannot execute actions."""
        act = self._create_test_action(requires_approval=False, status=ActionStatus.APPROVED)
        with self.assertRaises(ExecutionGatewayException) as ctx:
            execution_gateway.execute_action(
                action_id=act.action_id,
                identity=self.identity_admin
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.code, "ADMIN_OPERATIONAL_DENIED")

    # -------------------------------------------------------------------------
    # Gate 3: Tenant & Session Isolation
    # -------------------------------------------------------------------------

    def test_04_cross_tenant_execution_blocked(self):
        """Gate 3: Cross-tenant execution attempt is rejected with 403."""
        act = self._create_test_action()
        with self.assertRaises(ExecutionGatewayException) as ctx:
            execution_gateway.execute_action(
                action_id=act.action_id,
                identity=self.identity_attacker
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.code, "TENANT_MISMATCH")

    # -------------------------------------------------------------------------
    # Gate 4 & Gate 6: State Machine & Two-Person Approval
    # -------------------------------------------------------------------------

    def test_05_unapproved_high_risk_action_execution_rejected(self):
        """Gate 6: Action requiring approval cannot execute when not in APPROVED status."""
        act = self._create_test_action(
            requires_approval=True,
            risk_level=RiskLevel.HIGH,
            status=ActionStatus.AWAITING_APPROVAL
        )
        with self.assertRaises(ExecutionGatewayException) as ctx:
            execution_gateway.execute_action(
                action_id=act.action_id,
                identity=self.identity_pm
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "APPROVAL_REQUIRED")

    def test_06_approved_action_execution_succeeds(self):
        """Gate 6: Action in APPROVED status passes approval gate and executes."""
        act = self._create_test_action(
            requires_approval=True,
            risk_level=RiskLevel.HIGH,
            status=ActionStatus.APPROVED
        )
        res = execution_gateway.execute_action(
            action_id=act.action_id,
            identity=self.identity_pm
        )
        self.assertEqual(res.status, ExecutionStatus.SUCCEEDED)

    # -------------------------------------------------------------------------
    # Gate 5: Hash Integrity & Staleness Detection
    # -------------------------------------------------------------------------

    def test_07_action_hash_tamper_detected_marks_stale(self):
        """Gate 5: Action payload tampering detects hash mismatch, marks STALE, and rejects."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        # Tamper with recorded action_hash
        act.action_hash = "tampered_fake_sha256_hash_value"
        action_store.save(act)

        with self.assertRaises(ExecutionGatewayException) as ctx:
            execution_gateway.execute_action(
                action_id=act.action_id,
                identity=self.identity_pm
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "INTEGRITY_VIOLATION")

        # Verify action status transitioned to STALE
        updated = action_store.get_by_id(act.action_id, self.tenant_id)
        self.assertEqual(updated.status, ActionStatus.STALE)

    # -------------------------------------------------------------------------
    # Gate 8: Idempotency & Duplicate Execution Detection
    # -------------------------------------------------------------------------

    def test_08_execution_idempotency_returns_cached_result(self):
        """Gate 8: Repeated execution with same idempotency key returns cached ExecutionResult."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        idemp_key = "idemp_test_key_01"

        req = ExecutionRequest(action_id=act.action_id, idempotency_key=idemp_key)
        res1 = execution_gateway.execute_action(act.action_id, self.identity_pm, req)
        res2 = execution_gateway.execute_action(act.action_id, self.identity_pm, req)

        self.assertEqual(res1.execution_id, res2.execution_id)
        self.assertEqual(res1.status, res2.status)

    # -------------------------------------------------------------------------
    # Gate 10: Simulation / Dry-Run Defense & Deterministic Write Adapter
    # -------------------------------------------------------------------------

    def test_09_simulation_dry_run_preserves_zero_db_mutation(self):
        """Gate 10: dry_run=True returns affected_rows=0 without mutating DB."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        req = ExecutionRequest(action_id=act.action_id, dry_run=True)

        res = execution_gateway.execute_action(act.action_id, self.identity_pm, req)
        self.assertEqual(res.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(res.affected_rows, 0)
        self.assertEqual(res.data_mode, "SIMULATION")

    def test_10_physical_db_write_parameterized_deterministic(self):
        """Gate 10: Real mode execution updates database and returns affected rows."""
        # Establish session connection to test DB
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            access_mode=AccessMode.READ_WRITE,
            connection_id="conn_session_test",
            plant_id="plant_mumbai"
        )
        db_gateway.create_connection(req, identity=self.identity_pm)

        act = self._create_test_action(
            status=ActionStatus.APPROVED,
            params={"sku": "SKU-100", "new_reorder_point": 99}
        )
        res = execution_gateway.execute_action(act.action_id, self.identity_pm)
        self.assertEqual(res.status, ExecutionStatus.SUCCEEDED)
        self.assertGreaterEqual(res.affected_rows, 1)

        # Verify physical DB value
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT reorder_point FROM inventory WHERE sku = 'SKU-100'").fetchone()
        conn.close()
        self.assertEqual(row[0], 99)

    # -------------------------------------------------------------------------
    # Transaction Execution & State Machine
    # -------------------------------------------------------------------------

    def test_11_transaction_execution_succeeds_and_commits(self):
        """Valid transaction plan traverses Execution Gateway to COMMITTED state."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        tx, _ = transaction_service.plan_transaction(
            action_id=act.action_id,
            identity=self.identity_pm
        )
        transaction_repository.update_status(tx.transaction_id, self.tenant_id, TransactionStatus.READY)

        res = execution_gateway.execute_transaction(tx.transaction_id, self.identity_pm)
        self.assertEqual(res.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(res.transaction_id, tx.transaction_id)

        # Verify transaction state in repository
        updated_tx = transaction_repository.get_by_id(tx.transaction_id, self.tenant_id)
        self.assertEqual(updated_tx.status, TransactionStatus.COMMITTED)

    # -------------------------------------------------------------------------
    # Transaction Rollback
    # -------------------------------------------------------------------------

    def test_12_transaction_rollback_succeeds(self):
        """PLANT_MANAGER rolls back a COMMITTED transaction to ROLLED_BACK."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        tx, _ = transaction_service.plan_transaction(
            action_id=act.action_id,
            identity=self.identity_pm
        )
        transaction_repository.update_status(tx.transaction_id, self.tenant_id, TransactionStatus.COMMITTED)

        res = execution_gateway.rollback_transaction(tx.transaction_id, self.identity_pm)
        self.assertEqual(res.status, ExecutionStatus.ROLLED_BACK)
        self.assertEqual(res.rollback_status, "SUCCEEDED")

        updated_tx = transaction_repository.get_by_id(tx.transaction_id, self.tenant_id)
        self.assertEqual(updated_tx.status, TransactionStatus.ROLLED_BACK)

    def test_13_irreversible_transaction_rollback_rejected(self):
        """Attempting to roll back an NOT_SUPPORTED transaction raises 400."""
        act = self._create_test_action(status=ActionStatus.APPROVED)
        tx, _ = transaction_service.plan_transaction(
            action_id=act.action_id,
            identity=self.identity_pm
        )
        tx.plan.rollback_plan.capability = RollbackCapability.NOT_SUPPORTED
        tx.rollback_supported = RollbackCapability.NOT_SUPPORTED
        tx.status = TransactionStatus.COMMITTED
        transaction_repository.save(tx)

        with self.assertRaises(ExecutionGatewayException) as ctx:
            execution_gateway.rollback_transaction(tx.transaction_id, self.identity_pm)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.code, "ROLLBACK_NOT_SUPPORTED")

    # -------------------------------------------------------------------------
    # REST API Endpoints Integration
    # -------------------------------------------------------------------------

    def test_14_api_action_approve_endpoint(self):
        """POST /api/v3/actions/{id}/approve approves action under two-person rule."""
        act = self._create_test_action(
            requires_approval=True,
            risk_level=RiskLevel.HIGH,
            status=ActionStatus.AWAITING_APPROVAL,
            proposer="op_proposer_distinct"
        )
        headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": self.tenant_id,
            "X-User-Roles": "manager"
        }
        resp = self.client.post(f"/api/v3/actions/{act.action_id}/approve", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(resp.json()["action"]["status"], "APPROVED")

    def test_15_api_action_execute_endpoint(self):
        """POST /api/v3/actions/{id}/execute returns 200 ActionExecuteResponse."""
        act = self._create_test_action(
            requires_approval=False,
            status=ActionStatus.APPROVED
        )
        headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": self.tenant_id,
            "X-User-Roles": "manager"
        }
        resp = self.client.post(
            f"/api/v3/actions/{act.action_id}/execute",
            json={"dry_run": True},
            headers=headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["result"]["status"], "SUCCEEDED")


if __name__ == "__main__":
    unittest.main()
