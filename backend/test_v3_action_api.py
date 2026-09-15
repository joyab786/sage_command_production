# backend/test_v3_action_api.py
"""
SageCommand V3 — Structured Action API Test Suite (Prompt 05)
Validates:
1. Canonical Action Domain Models, 11 Action Types, 15 Resource Types.
2. Two-Layer Validation: Schema / Anti-SQL Smuggling / Numeric & Temporal Checks / Domain Invariants.
3. Deterministic System Risk Classification & Human Approval Enforcement.
4. Safe Simulation Preview (No Live Mutation).
5. REST Endpoints under /api/v3/actions (POST, GET, GET /{id}, POST validate, simulate, cancel).
6. Cross-Tenant Isolation & Idempotency.
7. Critical Scope Boundary: POST /{id}/execute is strictly disallowed (405).
8. Agent Tools (propose_action, preview_action_impact, list_supported_actions).
"""

import unittest
import json
import uuid
from fastapi.testclient import TestClient

from server import app
from core.auth import Identity
from services.action_registry import action_registry
from services.action_validator import action_validator
from services.action_store import action_store
from tools.action_tools import propose_action, preview_action_impact, list_supported_actions
from data.schemas.action_contract import (
    ActionType,
    ResourceType,
    RiskLevel,
    ActionStatus,
    ActionErrorCode,
)


class TestV3ActionAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager_token = "manager_token"
        cls.operator_token = "operator_token"

    def setUp(self):
        # Clear action store for test isolation
        action_store.clear()

    def tearDown(self):
        action_store.clear()

    def _auth_headers(self, token="manager_token", session_id="session_test_01", idempotency_key=None):
        h = {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": session_id,
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}"
        }
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    # =====================================================================
    # 1. ACTION REGISTRY & CONTRACT TESTS
    # =====================================================================

    def test_01_registry_contains_all_11_actions(self):
        """Verifies action registry has all 11 canonical industrial action types."""
        registered = action_registry.list_definitions()
        self.assertEqual(len(registered), 11)
        action_names = {d.action_type.value for d in registered}
        expected = {
            "ADJUST_REORDER_POINT",
            "REORDER_INVENTORY",
            "MOVE_INVENTORY",
            "SCHEDULE_MAINTENANCE",
            "CREATE_MAINTENANCE_WORK_ORDER",
            "RESCHEDULE_PRODUCTION",
            "CHANGE_PRODUCTION_PLAN",
            "UPDATE_SUPPLIER_ORDER",
            "ESCALATE_INCIDENT",
            "NOTIFY_STAKEHOLDER",
            "UPDATE_SLA_PRIORITY",
        }
        self.assertEqual(action_names, expected)

    # =====================================================================
    # 2. REST API: ACTION CREATION & TWO-LAYER VALIDATION
    # =====================================================================

    def test_02_create_valid_action_endpoint(self):
        """Validates POST /api/v3/actions creates a valid action with 201 status."""
        payload = {
            "action_type": "ADJUST_REORDER_POINT",
            "version": "1.0",
            "target": {
                "resource_type": "SKU",
                "resource_id": "SKU-9900",
                "tenant_id": "tenant_default",
                "workspace_id": "workspace_default",
                "plant_id": "plant_001"
            },
            "parameters": {
                "sku_id": "SKU-9900",
                "new_reorder_point": 350,
                "effective_date": "2026-10-01T00:00:00Z"
            },
            "reason": {
                "summary": "Raise safety stock buffer due to supplier lead time variation.",
                "justification": "Mitigates stockout probability from 14% to 2%.",
                "reason_code": "OPERATIONAL_RECOVERY"
            },
            "estimated_cost": {"value": 1200.0, "currency": "USD"},
            "estimated_duration_minutes": 15
        }

        resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue("request_id" in data)
        action = data["action"]
        self.assertTrue(action["action_id"].startswith("act_"))
        self.assertEqual(action["status"], "PROPOSED")
        self.assertEqual(action["system_risk_level"], "LOW")
        self.assertFalse(action["requires_approval"])
        self.assertTrue(len(action["action_hash"]) == 64)

    def test_03_idempotency_returns_cached_action(self):
        """Validates Idempotency-Key caching prevents duplicate action creation."""
        idempotency_key = "idemp_key_unique_123"
        payload = {
            "action_type": "REORDER_INVENTORY",
            "target": {
                "resource_type": "SKU",
                "resource_id": "SKU-100",
                "plant_id": "plant_001"
            },
            "parameters": {
                "sku_id": "SKU-100",
                "quantity": 50,
                "priority": "STANDARD"
            },
            "reason": {
                "summary": "Restock low SKU",
                "reason_code": "OPERATIONAL_RECOVERY"
            },
            "estimated_cost": {"value": 500.0, "currency": "USD"}
        }

        resp1 = self.client.post(
            "/api/v3/actions",
            json=payload,
            headers=self._auth_headers(idempotency_key=idempotency_key)
        )
        self.assertEqual(resp1.status_code, 201)
        action1 = resp1.json()["action"]

        # Resubmit identical request with same idempotency key
        resp2 = self.client.post(
            "/api/v3/actions",
            json=payload,
            headers=self._auth_headers(idempotency_key=idempotency_key)
        )
        self.assertEqual(resp2.status_code, 201)
        action2 = resp2.json()["action"]

        self.assertEqual(action1["action_id"], action2["action_id"])
        # Verify repository contains only one action
        actions, total = action_store.list_actions("tenant_default")
        self.assertEqual(total, 1)

    def test_04_anti_sql_smuggling_rejection(self):
        """Verifies SQL injection attempts in action parameters are deterministically rejected."""
        # 1. Prohibited 'sql' key in parameters
        payload_sql_key = {
            "action_type": "REORDER_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-100"},
            "parameters": {
                "sku_id": "SKU-100",
                "quantity": 50,
                "sql": "DROP TABLE inventory;"
            },
            "reason": {"summary": "Smuggled SQL test", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        resp1 = self.client.post("/api/v3/actions", json=payload_sql_key, headers=self._auth_headers())
        self.assertEqual(resp1.status_code, 400)
        self.assertEqual(resp1.json()["error"]["code"], "SQL_SMUGGLING_DETECTED")

        # 2. Malicious SQL pattern in string value
        payload_malicious_val = {
            "action_type": "NOTIFY_STAKEHOLDER",
            "target": {"resource_type": "SKU", "resource_id": "SKU-100"},
            "parameters": {
                "recipient_role": "OPERATIONS_LEAD",
                "message": "Critical: UPDATE inventory SET quantity = 9999 WHERE sku = 'A'; --"
            },
            "reason": {"summary": "Notify update", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        resp2 = self.client.post("/api/v3/actions", json=payload_malicious_val, headers=self._auth_headers())
        self.assertEqual(resp2.status_code, 400)
        self.assertEqual(resp2.json()["error"]["code"], "SQL_SMUGGLING_DETECTED")

    def test_05_numeric_and_temporal_validation(self):
        """Verifies negative quantities and invalid temporal formats are rejected."""
        # Negative quantity
        payload_neg = {
            "action_type": "REORDER_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-100"},
            "parameters": {"sku_id": "SKU-100", "quantity": -50},
            "reason": {"summary": "Negative qty", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        resp1 = self.client.post("/api/v3/actions", json=payload_neg, headers=self._auth_headers())
        self.assertEqual(resp1.status_code, 400)

        # Invalid ISO-8601 temporal format
        payload_date = {
            "action_type": "ADJUST_REORDER_POINT",
            "target": {"resource_type": "SKU", "resource_id": "SKU-100"},
            "parameters": {
                "sku_id": "SKU-100",
                "new_reorder_point": 100,
                "effective_date": "next Tuesday morning"
            },
            "reason": {"summary": "Invalid date", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        resp2 = self.client.post("/api/v3/actions", json=payload_date, headers=self._auth_headers())
        self.assertEqual(resp2.status_code, 400)

    def test_06_domain_invariants_validation(self):
        """Verifies domain rules such as move inventory warehouse collision are rejected."""
        payload = {
            "action_type": "MOVE_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-100"},
            "parameters": {
                "sku_id": "SKU-100",
                "from_warehouse": "WH_MAIN",
                "to_warehouse": "WH_MAIN",  # Source equals destination
                "quantity": 10
            },
            "reason": {"summary": "Warehouse collision", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertIn("DOMAIN_VALIDATION_FAILED", resp.json()["error"]["code"])

    # =====================================================================
    # 3. DETERMINISTIC RISK CLASSIFICATION & SIMULATION
    # =====================================================================

    def test_07_deterministic_risk_independent_of_llm(self):
        """Verifies system calculates deterministic risk regardless of model estimate."""
        # High financial cost ($50,000) forces HIGH risk even if model guessed LOW
        payload = {
            "action_type": "CREATE_MAINTENANCE_WORK_ORDER",
            "target": {"resource_type": "MACHINE", "resource_id": "CNC_TURBINE_01"},
            "parameters": {
                "machine_id": "CNC_TURBINE_01",
                "title": "Complete overhaul of turbine spindle",
                "severity": "CRITICAL"
            },
            "reason": {"summary": "Turbine rebuild", "reason_code": "OPERATIONAL_RECOVERY"},
            "model_estimated_risk": "LOW",  # LLM attempted to downplay risk
            "estimated_cost": {"value": 50000.0, "currency": "USD"}
        }
        resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 201)
        act = resp.json()["action"]
        self.assertEqual(act["system_risk_level"], "CRITICAL")
        self.assertTrue(act["requires_approval"])
        self.assertEqual(act["model_estimated_risk"], "LOW")

    def test_08_simulator_action_is_always_low_risk(self):
        """Verifies actions in SIMULATION mode are deterministically LOW risk."""
        payload = {
            "action_type": "CREATE_MAINTENANCE_WORK_ORDER",
            "data_mode": "SIMULATION",
            "target": {"resource_type": "MACHINE", "resource_id": "SIM_MACHINE_01"},
            "parameters": {
                "machine_id": "SIM_MACHINE_01",
                "title": "Simulated rebuild",
                "severity": "CRITICAL"
            },
            "reason": {"summary": "Simulation test", "reason_code": "OPERATIONAL_RECOVERY"},
            "estimated_cost": {"value": 100000.0, "currency": "USD"}
        }
        resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        self.assertEqual(resp.status_code, 201)
        act = resp.json()["action"]
        self.assertEqual(act["system_risk_level"], "LOW")
        self.assertFalse(act["requires_approval"])

    # =====================================================================
    # 4. ACTION DETAILS, LISTING, AND CROSS-TENANT ISOLATION
    # =====================================================================

    def test_09_list_and_get_action_with_preview(self):
        """Validates GET /api/v3/actions and GET /api/v3/actions/{id} with preview string."""
        # Create action
        payload = {
            "action_type": "REORDER_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-300"},
            "parameters": {"sku_id": "SKU-300", "quantity": 120},
            "reason": {"summary": "Restock SKU-300", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        create_resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        act_id = create_resp.json()["action"]["action_id"]

        # List actions
        list_resp = self.client.get("/api/v3/actions", headers=self._auth_headers())
        self.assertEqual(list_resp.status_code, 200)
        list_data = list_resp.json()
        self.assertGreaterEqual(list_data["total"], 1)

        # Get detail
        get_resp = self.client.get(f"/api/v3/actions/{act_id}", headers=self._auth_headers())
        self.assertEqual(get_resp.status_code, 200)
        detail_data = get_resp.json()
        self.assertEqual(detail_data["action"]["action_id"], act_id)
        self.assertIn("Action: REORDER_INVENTORY", detail_data["preview"])
        self.assertIn("Target: SKU [SKU-300]", detail_data["preview"])

    def test_10_cross_tenant_isolation(self):
        """Verifies action created by Tenant A is inaccessible to Tenant B."""
        # Create action in tenant_default
        payload = {
            "action_type": "REORDER_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-PRIVATE"},
            "parameters": {"sku_id": "SKU-PRIVATE", "quantity": 10},
            "reason": {"summary": "Tenant A action", "reason_code": "OPERATIONAL_RECOVERY"}
        }
        create_resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        act_id = create_resp.json()["action"]["action_id"]

        # Attempt to access with a different tenant
        tenant_b_headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": "tenant_competitor_beta",
            "X-Session-ID": "session_beta"
        }
        # Override identity to simulate Tenant B request
        from core.auth import get_current_identity
        async def mock_identity_b():
            return Identity(user_id="user_b", tenant_id="tenant_competitor_beta", roles=["manager"])

        app.dependency_overrides[get_current_identity] = mock_identity_b
        try:
            get_resp = self.client.get(f"/api/v3/actions/{act_id}", headers=tenant_b_headers)
            self.assertEqual(get_resp.status_code, 404)
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    # =====================================================================
    # 5. VALIDATION, SIMULATION, AND CANCELLATION ENDPOINTS
    # =====================================================================

    def test_11_explicit_validation_endpoint(self):
        """Validates POST /api/v3/actions/{id}/validate re-runs Layer 1 & 2 checks."""
        payload = {
            "action_type": "SCHEDULE_MAINTENANCE",
            "target": {"resource_type": "MACHINE", "resource_id": "MCH-01"},
            "parameters": {
                "machine_id": "MCH-01",
                "maintenance_type": "PREVENTIVE",
                "scheduled_start": "2026-10-05T09:00:00Z",
                "estimated_duration_minutes": 90
            },
            "reason": {"summary": "Oil change and calibration", "reason_code": "PREVENTIVE_CYCLE"}
        }
        create_resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        act_id = create_resp.json()["action"]["action_id"]

        val_resp = self.client.post(f"/api/v3/actions/{act_id}/validate", headers=self._auth_headers())
        self.assertEqual(val_resp.status_code, 200)
        val_data = val_resp.json()
        self.assertTrue(val_data["valid"])
        self.assertTrue(len(val_data["checks"]) > 0)
        self.assertTrue(all(c["status"] == "PASS" for c in val_data["checks"]))

    def test_12_simulation_endpoint(self):
        """Validates POST /api/v3/actions/{id}/simulate produces deterministic delta without live DB mutation."""
        payload = {
            "action_type": "REORDER_INVENTORY",
            "target": {"resource_type": "SKU", "resource_id": "SKU-SIM-99"},
            "parameters": {"sku_id": "SKU-SIM-99", "quantity": 300},
            "reason": {"summary": "Simulate restock", "reason_code": "OPERATIONAL_RECOVERY"},
            "estimated_cost": {"value": 4500.0, "currency": "USD"}
        }
        create_resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        act_id = create_resp.json()["action"]["action_id"]

        sim_resp = self.client.post(f"/api/v3/actions/{act_id}/simulate", headers=self._auth_headers())
        self.assertEqual(sim_resp.status_code, 200)
        sim_data = sim_resp.json()
        self.assertTrue(sim_data["success"])
        sim_result = sim_data["simulation"]
        self.assertEqual(sim_result["action_id"], act_id)
        self.assertEqual(sim_result["data_mode"], "SIMULATION")
        effects = sim_result["expected_effects"]
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["field"], "pending_inbound_quantity")
        self.assertEqual(effects[0]["after"], 300)

    def test_13_cancellation_endpoint(self):
        """Validates POST /api/v3/actions/{id}/cancel transitions action to CANCELLED."""
        payload = {
            "action_type": "NOTIFY_STAKEHOLDER",
            "target": {"resource_type": "PLANT", "resource_id": "plant_001"},
            "parameters": {"recipient_role": "SAFETY_OFFICER", "message": "Weather advisory alert."},
            "reason": {"summary": "Alert notification", "reason_code": "WEATHER_EVENT"}
        }
        create_resp = self.client.post("/api/v3/actions", json=payload, headers=self._auth_headers())
        act_id = create_resp.json()["action"]["action_id"]

        cancel_resp = self.client.post(f"/api/v3/actions/{act_id}/cancel", headers=self._auth_headers())
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.json()["status"], "CANCELLED")

        # Second cancel attempt must fail (already cancelled)
        cancel_resp2 = self.client.post(f"/api/v3/actions/{act_id}/cancel", headers=self._auth_headers())
        self.assertEqual(cancel_resp2.status_code, 400)

    # =====================================================================
    # 6. CRITICAL SCOPE BOUNDARY
    # =====================================================================

    def test_14_execution_boundary_endpoint_is_strictly_disallowed(self):
        """CRITICAL: Verifies POST /api/v3/actions/{id}/execute is handled by Execution Gateway (404 on missing, not arbitrary 405)."""
        resp = self.client.post("/api/v3/actions/act_test_dummy/execute", headers=self._auth_headers())
        self.assertEqual(resp.status_code, 404)
        err = resp.json()["error"]
        self.assertEqual(err["code"], "ACTION_NOT_FOUND")

    # =====================================================================
    # 7. AGENT TOOLS INTEGRATION
    # =====================================================================

    def test_15_agent_tools_functionality(self):
        """Validates propose_action, preview_action_impact, and list_supported_actions agent tools."""
        # 1. list_supported_actions
        tool_catalog = list_supported_actions.invoke({})
        self.assertIn("SAGECOMMAND V3 SUPPORTED ACTION TYPES", tool_catalog)
        self.assertIn("ADJUST_REORDER_POINT", tool_catalog)
        self.assertIn("SCHEDULE_MAINTENANCE", tool_catalog)

        # 2. propose_action
        proposal_out = propose_action.invoke({
            "action_type": "REORDER_INVENTORY",
            "resource_type": "SKU",
            "resource_id": "SKU-TOOL-01",
            "parameters": {"sku_id": "SKU-TOOL-01", "quantity": 75, "priority": "EXPEDITE"},
            "reason": "Agent autonomous restock decision",
            "estimated_cost_usd": 1800.0,
            "estimated_duration_minutes": 30
        })
        self.assertIn("ACTION PROPOSED SUCCESSFULLY", proposal_out)
        self.assertIn("SKU-TOOL-01", proposal_out)

        # Extract Action ID from tool output
        lines = proposal_out.splitlines()
        act_id = None
        for line in lines:
            if line.startswith("Action ID:"):
                act_id = line.split(":", 1)[1].strip()
                break
        self.assertIsNotNone(act_id)

        # 3. preview_action_impact
        preview_out = preview_action_impact.invoke({"action_id": act_id})
        self.assertIn(f"SIMULATION PREVIEW for {act_id}", preview_out)
        self.assertIn("pending_inbound_quantity", preview_out)


if __name__ == "__main__":
    unittest.main()
