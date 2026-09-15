# backend/test_v3_db_gateway.py
"""
SageCommand V3 — Database Connection Gateway Test Suite
Verifies SSRF guardrails, network policies, credential secrecy, database adapter capabilities,
ownership isolation, schema discovery limits, sensitive column value masking, error normalization,
and REST API gateway endpoints.
"""

import sys
import os
import unittest
import tempfile
import sqlite3
from fastapi.testclient import TestClient

# Ensure sys.path includes backend root
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

try:
    from server import app
    from core.auth import Identity
    from data.database_context import AccessMode, DataMode, ConnectionStatus
    from gateway.db_gateway import db_gateway, DatabaseConnectionGateway, DBConnectionRequest
    from gateway.network_policy import NetworkPolicyEngine, NetworkPolicy, DatabasePolicyBlockedError
    from gateway.secret_provider import EnvSecretProvider, secret_provider
    from gateway.db_adapters import get_adapter, SupportedDBType
    from services.connection_manager import db_manager
except ModuleNotFoundError:
    from backend.server import app
    from backend.core.auth import Identity
    from backend.data.database_context import AccessMode, DataMode, ConnectionStatus
    from backend.gateway.db_gateway import db_gateway, DatabaseConnectionGateway, DBConnectionRequest
    from backend.gateway.network_policy import NetworkPolicyEngine, NetworkPolicy, DatabasePolicyBlockedError
    from backend.gateway.secret_provider import EnvSecretProvider, secret_provider
    from backend.gateway.db_adapters import get_adapter, SupportedDBType
    from backend.services.connection_manager import db_manager


class TestV3DatabaseGateway(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_datacore.sqlite")

        # Populate test SQLite database with sample tables and sensitive columns
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE users (id INT, username TEXT, password TEXT, api_key TEXT, role TEXT)")
        cursor.execute("INSERT INTO users VALUES (1, 'alice', 'super_secret_pass_123', 'ak_9948271', 'manager')")
        cursor.execute("INSERT INTO users VALUES (2, 'bob', 'user_pass_456', 'ak_1120492', 'operator')")
        cursor.execute("CREATE TABLE inventory (sku TEXT, quantity INT, unit_price REAL)")
        cursor.execute("INSERT INTO inventory VALUES ('SKU-101', 50, 120.50)")
        conn.commit()
        conn.close()

        self.identity_mgr = Identity(user_id="mgr_001", roles=["manager"], tenant_id="tenant_acme", session_id="session_alpha")
        self.identity_op = Identity(user_id="op_002", roles=["operator"], tenant_id="tenant_acme", session_id="session_alpha")
        self.identity_other = Identity(user_id="mgr_999", roles=["manager"], tenant_id="tenant_stark", session_id="session_beta")

        self.mgr_token = "manager_token"

    def tearDown(self):
        db_manager.close_all()
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    def test_01_valid_sqlite_connection_creation(self):
        """Verify Gateway creates valid SQLite connection response with safe metadata."""
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            access_mode=AccessMode.READ_ONLY,
            connection_id="conn_test"
        )
        resp = db_gateway.create_connection(req, identity=self.identity_mgr)

        self.assertEqual(resp.connection_id, "conn_test")
        self.assertEqual(resp.tenant_id, "tenant_acme")
        self.assertEqual(resp.session_id, "session_alpha")
        self.assertEqual(resp.database_type, "sqlite")
        self.assertEqual(resp.status, "CONNECTED")
        self.assertTrue(resp.capabilities.read)
        self.assertFalse(resp.capabilities.write)

    def test_02_unsupported_database_type(self):
        """Verify unsupported database type raises UNSUPPORTED_DATABASE_TYPE error."""
        with self.assertRaises(ValueError) as cm:
            get_adapter("MONGODB")
        self.assertIn("UNSUPPORTED_DATABASE_TYPE", str(cm.exception))

    def test_03_ssrf_loopback_and_metadata_blocking(self):
        """Verify SSRF engine blocks loopback and cloud metadata targets under RESTRICTED policy."""
        net = NetworkPolicyEngine(default_policy="RESTRICTED", allowed_hosts=[])

        # Loopback check (IPv4 and hostname and IPv6)
        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="127.0.0.1", port=5432, scheme="postgresql")

        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="localhost", port=5432, scheme="postgresql")

        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="::1", port=5432, scheme="postgresql")

        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="0.0.0.0", port=5432, scheme="postgresql")

        # Cloud Metadata check (IPv4 link-local & cloud name)
        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="169.254.169.254", port=80, scheme="postgresql")

        with self.assertRaises(DatabasePolicyBlockedError):
            net.validate_host_and_port(host="metadata.google.internal", port=5432, scheme="postgresql")

    def test_04_ssrf_private_ip_and_allowlist(self):
        """Verify private IP blocking under RESTRICTED policy and override under PRIVATE_ALLOWED / ALLOWLIST / CIDR."""
        net_restricted = NetworkPolicyEngine(default_policy="RESTRICTED", allowed_hosts=[])
        with self.assertRaises(DatabasePolicyBlockedError):
            net_restricted.validate_host_and_port(host="10.0.0.15", port=5432, scheme="postgresql")

        # Allowlisted host succeeds
        net_allowlist = NetworkPolicyEngine(default_policy="RESTRICTED", allowed_hosts=["db.internal.acme.com"])
        self.assertTrue(net_allowlist.validate_host_and_port(host="db.internal.acme.com", port=5432, scheme="postgresql"))

        # CIDR Allowlisted range succeeds
        net_cidr = NetworkPolicyEngine(default_policy="RESTRICTED", allowed_hosts=["10.20.30.0/24"])
        self.assertTrue(net_cidr.validate_host_and_port(host="10.20.30.45", port=5432, scheme="postgresql"))

        # PRIVATE_ALLOWED policy permits private IP but still blocks metadata
        net_private = NetworkPolicyEngine(default_policy="PRIVATE_ALLOWED", allowed_hosts=[])
        self.assertTrue(net_private.validate_host_and_port(host="192.168.1.100", port=5432, scheme="postgresql"))
        with self.assertRaises(DatabasePolicyBlockedError):
            net_private.validate_host_and_port(host="169.254.169.254", port=80, scheme="postgresql")

    def test_05_credential_secrecy_and_redaction(self):
        """Verify passwords are excluded from serialization and secret handles are stored out-of-band."""
        req = DBConnectionRequest(
            database_type="POSTGRESQL",
            host="db.analytics.external",
            port=5432,
            database="ops",
            username="analyst_user",
            password="ultra_secret_password_999",
            connection_id="conn_pg_test"
        )
        serialized = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        self.assertNotIn("password", serialized)

        # Verify SecretProvider handles out-of-band secret
        sec_handle = secret_provider.store_secret("super_vault_pass", label="test_db")
        self.assertTrue(sec_handle.startswith("sec_"))
        self.assertEqual(secret_provider.get_secret(sec_handle), "super_vault_pass")
        secret_provider.remove_secret(sec_handle)
        self.assertIsNone(secret_provider.get_secret(sec_handle))

    def test_06_ownership_isolation(self):
        """Verify cross-tenant / cross-session access to connection handles is denied."""
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            connection_id="conn_test"
        )
        db_gateway.create_connection(req, identity=self.identity_mgr)

        # Attempt access by User from tenant_stark / session_beta
        with self.assertRaises(PermissionError):
            db_gateway.get_connection("tenant_stark", "workspace_default", "session_beta", "conn_test", identity=self.identity_other)

    def test_07_connection_revocation(self):
        """Verify disconnect revokes active connection handles."""
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            connection_id="conn_test"
        )
        db_gateway.create_connection(req, identity=self.identity_mgr)

        closed = db_gateway.disconnect("tenant_acme", "workspace_default", "session_alpha", "conn_test", identity=self.identity_mgr)
        self.assertTrue(closed)

        # Subsequent health check fails
        with self.assertRaises(PermissionError):
            db_gateway.health_check("tenant_acme", "workspace_default", "session_alpha", "conn_test", identity=self.identity_mgr)

    def test_08_schema_discovery_boundaries(self):
        """Verify schema discovery retrieves table columns and respects limit parameter."""
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            connection_id="conn_test"
        )
        db_gateway.create_connection(req, identity=self.identity_mgr)

        schema = db_gateway.discover_schema("tenant_acme", "workspace_default", "session_alpha", "conn_test", identity=self.identity_mgr, limit_tables=1)
        self.assertEqual(schema["table_count"], 2)
        self.assertEqual(len(schema["tables"]), 1)

    def test_09_sensitive_data_sampling_masking(self):
        """Verify data sampling masks sensitive column values with [REDACTED]."""
        req = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{self.db_path}",
            connection_id="conn_test"
        )
        db_gateway.create_connection(req, identity=self.identity_mgr)

        sample = db_gateway.get_data_sample("tenant_acme", "workspace_default", "session_alpha", "conn_test", "users", identity=self.identity_mgr, max_rows=5)
        self.assertEqual(sample["row_count"], 2)

        row_alice = sample["sample_rows"][0]
        self.assertEqual(row_alice["username"], "alice")
        self.assertEqual(row_alice["password"], "[REDACTED]")
        self.assertEqual(row_alice["api_key"], "[REDACTED]")
        self.assertEqual(row_alice["role"], "manager")

    def test_10_gateway_rest_api_endpoints(self):
        """Verify REST API gateway endpoints for connection, health, schema, sample, metadata, and disconnect."""
        headers = {
            "Authorization": f"Bearer {self.mgr_token}",
            "X-Session-ID": "session_api_suite"
        }

        # 1. POST /api/v3/db/connect
        connect_payload = {
            "database_type": "SQLITE",
            "connection_string": f"sqlite:///{self.db_path}",
            "connection_id": "conn_api_test"
        }
        res_conn = self.client.post("/api/v3/db/connect", json=connect_payload, headers=headers)
        self.assertEqual(res_conn.status_code, 200)
        self.assertEqual(res_conn.json()["connection_id"], "conn_api_test")

        # 2. GET /api/v3/db/health/conn_api_test
        res_health = self.client.get("/api/v3/db/health/conn_api_test", headers=headers)
        self.assertEqual(res_health.status_code, 200)
        self.assertEqual(res_health.json()["status"], "HEALTHY")

        # 3. GET /api/v3/db/schema/conn_api_test
        res_schema = self.client.get("/api/v3/db/schema/conn_api_test", headers=headers)
        self.assertEqual(res_schema.status_code, 200)
        self.assertIn("tables", res_schema.json())

        # 4. GET /api/v3/db/sample/conn_api_test/users
        res_sample = self.client.get("/api/v3/db/sample/conn_api_test/users", headers=headers)
        self.assertEqual(res_sample.status_code, 200)
        self.assertEqual(res_sample.json()["sample_rows"][0]["password"], "[REDACTED]")

        # 5. GET /api/v3/db/metadata/conn_api_test
        res_meta = self.client.get("/api/v3/db/metadata/conn_api_test", headers=headers)
        self.assertEqual(res_meta.status_code, 200)
        self.assertEqual(res_meta.json()["connection_id"], "conn_api_test")

        # 6. POST /api/v3/db/disconnect
        res_disc = self.client.post("/api/v3/db/disconnect?connection_id=conn_api_test", headers=headers)
        self.assertEqual(res_disc.status_code, 200)
        self.assertIn("revoked", res_disc.json()["message"])

    def test_11_tls_policy_enforcement(self):
        """Verify TLS REQUIRED policy rejects plaintext connection strings for external DBs."""
        req = DBConnectionRequest(
            database_type="POSTGRESQL",
            connection_string="postgresql://user:pass@db.example.com:5432/ops?sslmode=disable",
            ssl_mode="DISABLED"
        )
        with self.assertRaises(ValueError) as cm:
            db_gateway.validate_request(req, identity=self.identity_mgr)
        self.assertIn("DATABASE_TLS_FAILED", str(cm.exception))

    def test_12_action_boundary_no_arbitrary_execution(self):
        """Verify Gateway does not provide arbitrary execute_sql endpoint (Action Gateway separation)."""
        self.assertFalse(hasattr(db_gateway, "execute_sql"))
        self.assertFalse(hasattr(db_gateway, "execute_command"))
        self.assertFalse(hasattr(db_gateway, "write_anything"))


if __name__ == "__main__":
    unittest.main()

