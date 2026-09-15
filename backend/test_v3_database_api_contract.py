# backend/test_v3_database_api_contract.py
"""
SageCommand V3 — Database Connection Gateway Canonical API Contract Test Suite
Validates all 10 canonical endpoints under /api/v3/database, request ID handling,
idempotency, pagination, error contract, tenant isolation, LLM protection, and 501 rotate-credentials.
"""

import unittest
import os
import tempfile
import sqlite3
import json
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from server import app
from core.auth import Identity
from services.connection_manager import db_manager
from gateway.db_gateway import db_gateway
from tools.db_tools import database_tool


class TestDatabaseAPIContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.manager_token = "manager_token"
        cls.operator_token = "operator_token"
        cls.tenant_beta_token = "manager_token"

    def setUp(self):
        # Create temp sqlite database with test table
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "contract_test.db").replace("\\", "/")
        engine = create_engine(f"sqlite:///{self.db_path}")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE inventory (sku VARCHAR PRIMARY KEY, quantity INTEGER, reorder_point INTEGER)"))
            conn.execute(text("INSERT INTO inventory VALUES ('SKU-001', 1250, 500), ('SKU-002', 300, 100)"))
            conn.execute(text("CREATE TABLE credentials_vault (username VARCHAR, password_hash VARCHAR, api_secret VARCHAR)"))
            conn.execute(text("INSERT INTO credentials_vault VALUES ('admin', 'argon2$supersecret', 'sk_live_9999')"))
            conn.commit()
        engine.dispose()
        db_gateway.clear_cache()

    def tearDown(self):
        db_manager.close_all()
        db_gateway.clear_cache()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.tmp_dir):
                os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_01_create_connection_contract(self):
        """Validates POST /api/v3/database/connections returns 201 Created with canonical structure."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        payload = {
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY",
            "data_mode": "REAL",
            "plant_id": "plant_mumbai"
        }
        resp = self.client.post("/api/v3/database/connections", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 201, f"Expected 201 Created, got {resp.status_code}: {resp.text}")
        data = resp.json()

        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("request_id", "").startswith("req_"))

        conn = data.get("connection", {})
        self.assertTrue(conn.get("connection_id", "").startswith("conn_"))
        self.assertEqual(conn.get("tenant_id"), "tenant_alpha")
        self.assertEqual(conn.get("session_id"), "session_alpha")
        self.assertEqual(conn.get("database_type"), "SQLITE")
        self.assertEqual(conn.get("status"), "CONNECTED")
        self.assertEqual(conn.get("access_mode"), "READ_ONLY")
        self.assertEqual(conn.get("data_mode"), "REAL")

        caps = conn.get("capabilities", {})
        self.assertTrue(caps.get("read"))
        self.assertFalse(caps.get("write"))
        self.assertTrue(caps.get("schema_inspection"))

        # Strict Credential Redaction Assertion
        raw_str = json.dumps(data)
        self.assertNotIn("password", raw_str.lower())
        self.assertNotIn("argon2", raw_str)
        self.assertNotIn("secret", raw_str.lower())

    def test_02_idempotency_key_prevents_duplicate_creation(self):
        """Validates that repeating POST /connections with Idempotency-Key returns cached response."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha",
            "Idempotency-Key": "idemp_test_key_001"
        }
        payload = {
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY",
            "data_mode": "REAL"
        }
        resp1 = self.client.post("/api/v3/database/connections", json=payload, headers=headers)
        self.assertEqual(resp1.status_code, 201)
        conn_id_1 = resp1.json()["connection"]["connection_id"]

        resp2 = self.client.post("/api/v3/database/connections", json=payload, headers=headers)
        self.assertEqual(resp2.status_code, 201)
        conn_id_2 = resp2.json()["connection"]["connection_id"]

        self.assertEqual(conn_id_1, conn_id_2, "Idempotent requests must return the identical connection_id")

    def test_03_x_request_id_propagation(self):
        """Validates that X-Request-ID header is propagated safely in response."""
        headers = {
            "Authorization": f"Bearer {self.operator_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha",
            "X-Request-ID": "req_custom_tracer_999"
        }
        resp = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("request_id"), "req_custom_tracer_999")

    def test_04_test_connection_endpoint(self):
        """Validates POST /api/v3/database/connections/test performs reachability check without registration."""
        headers = {
            "Authorization": f"Bearer {self.operator_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        payload = {
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}"
        }
        resp = self.client.post("/api/v3/database/connections/test", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        result = data.get("result", {})
        self.assertTrue(result.get("reachable"))
        self.assertTrue(result.get("authenticated"))
        self.assertEqual(result.get("database_type"), "SQLITE")
        self.assertGreater(result.get("latency_ms", 0), -1)

    def test_05_list_connections_pagination_and_filters(self):
        """Validates GET /api/v3/database/connections with pagination and filtering."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        # Create connection
        self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY",
            "data_mode": "REAL",
            "plant_id": "plant_pune"
        }, headers=headers)

        # List with filter
        resp = self.client.get("/api/v3/database/connections?limit=10&offset=0&plant_id=plant_pune", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertGreaterEqual(data.get("total", 0), 1)
        self.assertGreaterEqual(len(data.get("connections", [])), 1)

    def test_06_get_connection_metadata(self):
        """Validates GET /api/v3/database/connections/{connection_id}."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        get_resp = self.client.get(f"/api/v3/database/connections/{conn_id}", headers=headers)
        self.assertEqual(get_resp.status_code, 200)
        conn_data = get_resp.json()["connection"]
        self.assertEqual(conn_data["connection_id"], conn_id)
        self.assertEqual(conn_data["status"], "CONNECTED")

    def test_07_health_check_endpoint(self):
        """Validates GET /api/v3/database/connections/{connection_id}/health."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        health_resp = self.client.get(f"/api/v3/database/connections/{conn_id}/health", headers=headers)
        self.assertEqual(health_resp.status_code, 200)
        health = health_resp.json()["health"]
        self.assertEqual(health["status"], "HEALTHY")
        self.assertGreaterEqual(health["latency_ms"], 0)

    def test_08_schema_discovery_endpoint(self):
        """Validates GET /api/v3/database/connections/{connection_id}/schema."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        schema_resp = self.client.get(f"/api/v3/database/connections/{conn_id}/schema", headers=headers)
        self.assertEqual(schema_resp.status_code, 200)
        data = schema_resp.json()
        tables = data.get("schema", {}).get("tables", [])
        table_names = [t["name"] for t in tables]
        self.assertIn("inventory", table_names)
        self.assertIn("credentials_vault", table_names)

    def test_09_sample_data_endpoint_with_sensitive_masking(self):
        """Validates POST /api/v3/database/connections/{connection_id}/sample masks passwords to [REDACTED]."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        sample_resp = self.client.post(
            f"/api/v3/database/connections/{conn_id}/sample",
            json={"table": "credentials_vault", "limit": 5},
            headers=headers
        )
        self.assertEqual(sample_resp.status_code, 200)
        sample = sample_resp.json()["sample"]
        self.assertEqual(sample["table"], "credentials_vault")
        rows = sample["rows"]
        self.assertGreaterEqual(len(rows), 1)

        # Assert sensitive columns are masked
        self.assertEqual(rows[0]["username"], "admin")
        self.assertEqual(rows[0]["password_hash"], "[REDACTED]")
        self.assertEqual(rows[0]["api_secret"], "[REDACTED]")

    def test_10_disconnect_endpoint(self):
        """Validates POST /api/v3/database/connections/{connection_id}/disconnect."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        disc_resp = self.client.post(f"/api/v3/database/connections/{conn_id}/disconnect", headers=headers)
        self.assertEqual(disc_resp.status_code, 200)
        self.assertEqual(disc_resp.json()["connection"]["status"], "DISCONNECTED")

    def test_11_revoke_endpoint_blocks_future_access(self):
        """Validates POST /api/v3/database/connections/{connection_id}/revoke blocks future access."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        revoke_resp = self.client.post(f"/api/v3/database/connections/{conn_id}/revoke", headers=headers)
        self.assertEqual(revoke_resp.status_code, 200)
        self.assertEqual(revoke_resp.json()["connection"]["status"], "REVOKED")

        # Future attempts to access must be rejected
        health_resp = self.client.get(f"/api/v3/database/connections/{conn_id}/health", headers=headers)
        self.assertIn(health_resp.status_code, [404, 409])
        self.assertEqual(health_resp.json()["error"]["code"], "CONNECTION_REVOKED")

    def test_12_rotate_credentials_returns_501_not_implemented(self):
        """Validates POST /connections/{connection_id}/rotate-credentials returns 501 Not Implemented."""
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        resp = self.client.post("/api/v3/database/connections/conn_dummy/rotate-credentials", headers=headers)
        self.assertEqual(resp.status_code, 501)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "NOT_IMPLEMENTED")

    def test_13_cross_tenant_access_blocked(self):
        """Security Contract Test: Tenant B cannot query or access Tenant A's connection."""
        # Tenant A creates connection
        headers_a = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers_a)
        conn_id = create_resp.json()["connection"]["connection_id"]

        # Tenant B attempts access
        headers_b = {
            "Authorization": f"Bearer {self.tenant_beta_token}",
            "X-Session-ID": "session_beta",
            "X-Tenant-ID": "tenant_beta"
        }
        get_resp = self.client.get(f"/api/v3/database/connections/{conn_id}", headers=headers_b)
        self.assertEqual(get_resp.status_code, 403)
        self.assertEqual(get_resp.json()["error"]["code"], "AUTHORIZATION_DENIED")

    def test_14_llm_contract_credentials_isolation(self):
        """Validates DatabaseTool provides credential-free representation for LLM prompt context."""
        # Register connection in gateway
        headers = {
            "Authorization": f"Bearer {self.manager_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        create_resp = self.client.post("/api/v3/database/connections", json={
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "access_mode": "READ_ONLY"
        }, headers=headers)
        conn_id = create_resp.json()["connection"]["connection_id"]

        llm_context = database_tool.get_llm_connection_context(
            connection_id=conn_id,
            tenant_id="tenant_alpha",
            session_id="session_alpha"
        )
        self.assertEqual(llm_context["connection_id"], conn_id)
        self.assertEqual(llm_context["database_type"], "SQLITE")
        self.assertEqual(llm_context["access_mode"], "READ_ONLY")
        self.assertIn("capabilities", llm_context)

        raw_str = json.dumps(llm_context).lower()
        self.assertNotIn("password", raw_str)
        self.assertNotIn("token", raw_str)
        self.assertNotIn("sqlite:///", raw_str)
        self.assertNotIn("secret", raw_str)

    def test_15_error_contract_consistency(self):
        """Validates that non-existent connection returns canonical ErrorResponse without internals."""
        headers = {
            "Authorization": f"Bearer {self.operator_token}",
            "X-Session-ID": "session_alpha",
            "X-Tenant-ID": "tenant_alpha"
        }
        resp = self.client.get("/api/v3/database/connections/conn_nonexistent_999", headers=headers)
        self.assertEqual(resp.status_code, 404)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertTrue(data.get("request_id", "").startswith("req_"))
        self.assertEqual(data.get("error", {}).get("code"), "CONNECTION_NOT_FOUND")
        # Ensure no stack trace or SQLAlchemy internal in message
        self.assertNotIn("traceback", data["error"]["message"].lower())
        self.assertNotIn("sqlalchemy", data["error"]["message"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
