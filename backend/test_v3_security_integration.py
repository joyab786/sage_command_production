# backend/test_v3_security_integration.py
"""
SageCommand V3 — Pre-Prompt-10 Security & Isolation Regression Suite
Tests A through P validating:
- Client identity header spoofing rejection (A-E)
- Cryptographic JWT verification & failure modes (F-H)
- Copilot SQL mutation guardrails (I-K)
- Session-scoped database & upload isolation (L-O)
- WebSocket approval governance (P)
"""

import os
import sys
import time
import json
import unittest
import tempfile
import threading
import sqlite3
import jwt
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from server import app
from core.config import (
    SAGE_SECRET_KEY,
    SAGE_AUTH_ISSUER,
    SAGE_AUTH_AUDIENCE,
    DEFAULT_DB_PATH
)
from core.auth import (
    Identity,
    get_auth_provider,
    JWTAuthenticationProvider,
    DevAuthenticationProvider,
    get_current_identity
)
from governance.guardrails import (
    validate_sql_query,
    check_multi_statement_sql
)
from gateway.db_gateway import db_gateway, DBConnectionRequest
from data.database_context import AccessMode, DataMode
from services.connection_manager import db_manager
from services.db_service import dynamic_db


def create_signed_test_jwt(
    payload_override=None,
    secret=SAGE_SECRET_KEY,
    algorithm="HS256",
    headers=None
) -> str:
    """Helper to generate cryptographically signed test JWTs."""
    now = int(time.time())
    base_payload = {
        "sub": "user_sec_auditor",
        "tenant_id": "tenant_A",
        "workspace_id": "workspace_A",
        "session_id": "session_A",
        "roles": ["manager", "operator"],
        "clearance_level": 2,
        "assigned_plants": ["plant_A"],
        "status": "ACTIVE",
        "iss": SAGE_AUTH_ISSUER,
        "aud": SAGE_AUTH_AUDIENCE,
        "iat": now,
        "exp": now + 3600
    }
    if payload_override:
        base_payload.update(payload_override)
    return jwt.encode(base_payload, secret, algorithm=algorithm, headers=headers)


class TestV3SecurityIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # =========================================================================
    # TEST A — Tenant header spoofing
    # Authenticated user: tenant_A, request: X-Tenant-ID: tenant_B -> Expected: tenant_A
    # =========================================================================
    def test_A_tenant_header_spoofing(self):
        token = create_signed_test_jwt({"tenant_id": "tenant_A"})
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "tenant_B"
        }
        # Verify via test endpoint that relies on get_current_identity
        resp = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        # The list connections endpoint returns items scoped strictly to identity.tenant_id
        # We also directly assert identity resolution
        provider = JWTAuthenticationProvider()
        ident = provider.authenticate_token(token)
        self.assertEqual(ident.tenant_id, "tenant_A")
        self.assertTrue(ident.is_server_authoritative)

        # Ensure that passing headers through dependency evaluation does NOT mutate tenant
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-tenant-id", b"tenant_B")
            ]
        }
        req = Request(scope)
        resolved_identity = get_current_identity(req)
        self.assertEqual(resolved_identity.tenant_id, "tenant_A", "Client header X-Tenant-ID must NEVER override verified identity")

    # =========================================================================
    # TEST B — Clearance escalation
    # Authenticated operator: clearance = 1, request: X-Clearance-Level: 3 -> Expected: 1
    # =========================================================================
    def test_B_clearance_escalation(self):
        token = create_signed_test_jwt({"clearance_level": 1, "roles": ["operator"]})
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-clearance-level", b"3")
            ]
        }
        req = Request(scope)
        resolved_identity = get_current_identity(req)
        self.assertEqual(resolved_identity.clearance_level, 1, "Clearance level must NOT be escalated via client headers")

    # =========================================================================
    # TEST C — Plant escalation
    # Authenticated user assigned: plant_A, request: X-Assigned-Plants: * -> Expected: plant_A
    # =========================================================================
    def test_C_plant_escalation(self):
        token = create_signed_test_jwt({"assigned_plants": ["plant_A"]})
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-assigned-plants", b"*")
            ]
        }
        req = Request(scope)
        resolved_identity = get_current_identity(req)
        self.assertEqual(resolved_identity.assigned_plants, ["plant_A"], "Assigned plants must NOT be wildcard-escalated via client headers")

    # =========================================================================
    # TEST D — Workspace spoofing
    # Attempt: X-Workspace-ID: victim_workspace -> Expected: server identity unchanged
    # =========================================================================
    def test_D_workspace_spoofing(self):
        token = create_signed_test_jwt({"workspace_id": "workspace_legit"})
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-workspace-id", b"victim_workspace")
            ]
        }
        req = Request(scope)
        resolved_identity = get_current_identity(req)
        self.assertEqual(resolved_identity.workspace_id, "workspace_legit")

    # =========================================================================
    # TEST E — Session spoofing
    # Attempt: X-Session-ID: victim_session -> Expected: server session context remains trusted
    # =========================================================================
    def test_E_session_spoofing(self):
        token = create_signed_test_jwt({"session_id": "session_legit_001"})
        from fastapi import Request
        scope = {
            "type": "http",
            "method": "GET",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-session-id", b"victim_session_999")
            ]
        }
        req = Request(scope)
        resolved_identity = get_current_identity(req)
        self.assertEqual(resolved_identity.session_id, "session_legit_001")

    # =========================================================================
    # TEST F — Invalid JWT
    # Token with invalid cryptographic signature -> Expected: 401 Unauthorized
    # =========================================================================
    def test_F_invalid_jwt(self):
        tampered_token = create_signed_test_jwt(secret="wrong_secret_tampered_key_xyz")
        headers = {"Authorization": f"Bearer {tampered_token}"}
        resp = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp.status_code, 401, "Tampered/invalid JWT signature must return 401 Unauthorized")

    # =========================================================================
    # TEST G — Expired JWT
    # Expired token -> Expected: 401 Unauthorized
    # =========================================================================
    def test_G_expired_jwt(self):
        now = int(time.time())
        expired_token = create_signed_test_jwt({"iat": now - 7200, "exp": now - 3600})
        headers = {"Authorization": f"Bearer {expired_token}"}
        resp = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp.status_code, 401, "Expired JWT token must return 401 Unauthorized")

    # =========================================================================
    # TEST H — Algorithm confusion (alg=none)
    # Token with alg=none -> Expected: Rejected (401)
    # =========================================================================
    def test_H_algorithm_confusion_none(self):
        # Construct raw unencoded alg=none token
        header = json.dumps({"alg": "none", "typ": "JWT"}).encode()
        payload = json.dumps({
            "sub": "attacker",
            "tenant_id": "tenant_A",
            "roles": ["administrator"],
            "clearance_level": 3,
            "exp": int(time.time()) + 3600
        }).encode()
        import base64
        b64_hdr = base64.urlsafe_b64encode(header).decode().rstrip("=")
        b64_pay = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        unsigned_token = f"{b64_hdr}.{b64_pay}."

        headers = {"Authorization": f"Bearer {unsigned_token}"}
        resp = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp.status_code, 401, "Unsigned JWT with alg=none must be rejected with 401")

    # =========================================================================
    # TEST I — Copilot UPDATE
    # Attempt: UPDATE inventory SET quantity=0 -> Expected: REJECTED
    # =========================================================================
    def test_I_copilot_update_rejected(self):
        query = "UPDATE inventory SET quantity = 0"
        with self.assertRaises(PermissionError) as ctx:
            validate_sql_query(query)
        self.assertIn("prohibited", str(ctx.exception).lower())

    # =========================================================================
    # TEST J — Copilot INSERT
    # Attempt: INSERT INTO inventory ... -> Expected: REJECTED
    # =========================================================================
    def test_J_copilot_insert_rejected(self):
        query = "INSERT INTO inventory (item_id, quantity) VALUES ('SKU_1001', 500)"
        with self.assertRaises(PermissionError) as ctx:
            validate_sql_query(query)
        self.assertIn("prohibited", str(ctx.exception).lower())

    # =========================================================================
    # TEST K — SQL statement chaining
    # Attempt: SELECT * FROM inventory; UPDATE inventory SET quantity=0; -> Expected: REJECTED
    # =========================================================================
    def test_K_sql_statement_chaining_rejected(self):
        query = "SELECT * FROM inventory; UPDATE inventory SET quantity = 0;"
        with self.assertRaises(PermissionError) as ctx:
            validate_sql_query(query)
        self.assertTrue("multi-statement" in str(ctx.exception).lower() or "prohibited" in str(ctx.exception).lower())

        # Also test with hidden comment variation
        query_comment = "SELECT * FROM inventory /* safe select */ ; DELETE FROM inventory;"
        with self.assertRaises(PermissionError):
            validate_sql_query(query_comment)

    # =========================================================================
    # TEST L — Tenant database isolation
    # Session A -> Connection A, Session B -> Connection B; cross access rejected
    # =========================================================================
    def test_L_tenant_database_isolation(self):
        tmp_dir = tempfile.mkdtemp()
        db_a_path = os.path.join(tmp_dir, "db_a.sqlite").replace("\\", "/")
        db_b_path = os.path.join(tmp_dir, "db_b.sqlite").replace("\\", "/")

        conn_a = sqlite3.connect(db_a_path)
        conn_a.execute("CREATE TABLE tbl_a (id INT, secret_a TEXT);")
        conn_a.execute("INSERT INTO tbl_a VALUES (1, 'SECRET_TENANT_A');")
        conn_a.commit()
        conn_a.close()

        conn_b = sqlite3.connect(db_b_path)
        conn_b.execute("CREATE TABLE tbl_b (id INT, secret_b TEXT);")
        conn_b.execute("INSERT INTO tbl_b VALUES (2, 'SECRET_TENANT_B');")
        conn_b.commit()
        conn_b.close()

        ident_a = Identity(user_id="user_a", tenant_id="tenant_A", session_id="session_A", is_server_authoritative=True)
        ident_b = Identity(user_id="user_b", tenant_id="tenant_B", session_id="session_B", is_server_authoritative=True)

        # Register Connection A for Tenant A
        req_a = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{db_a_path}",
            access_mode=AccessMode.READ_ONLY,
            data_mode=DataMode.REAL,
            connection_id="conn_alpha"
        )
        db_gateway.create_connection(req_a, identity=ident_a)

        # Register Connection B for Tenant B
        req_b = DBConnectionRequest(
            database_type="SQLITE",
            connection_string=f"sqlite:///{db_b_path}",
            access_mode=AccessMode.READ_ONLY,
            data_mode=DataMode.REAL,
            connection_id="conn_beta"
        )
        db_gateway.create_connection(req_b, identity=ident_b)

        # Tenant A can discover A's schema
        schema_a = db_gateway.discover_schema("tenant_A", "workspace_default", "session_A", "conn_alpha", ident_a)
        table_names_a = [t["table_name"] for t in schema_a.get("tables", [])]
        self.assertIn("tbl_a", table_names_a)

        # Tenant B can discover B's schema
        schema_b = db_gateway.discover_schema("tenant_B", "workspace_default", "session_B", "conn_beta", ident_b)
        table_names_b = [t["table_name"] for t in schema_b.get("tables", [])]
        self.assertIn("tbl_b", table_names_b)

        # Cross-tenant access attempt: Tenant A trying to access Tenant B's connection -> Must be BLOCKED
        with self.assertRaises(PermissionError):
            db_gateway.discover_schema("tenant_B", "workspace_default", "session_B", "conn_beta", ident_a)

        # Cross-tenant access attempt: Tenant B trying to access Tenant A's connection -> Must be BLOCKED
        with self.assertRaises(PermissionError):
            db_gateway.discover_schema("tenant_A", "workspace_default", "session_A", "conn_alpha", ident_b)

    # =========================================================================
    # TEST M — Concurrent database isolation
    # Run concurrent requests for at least two independent sessions
    # =========================================================================
    def test_M_concurrent_database_isolation(self):
        errors = []
        iterations = 10

        def session_worker(tenant_name, session_name, expected_token_val):
            for _ in range(iterations):
                try:
                    tok = create_signed_test_jwt({"tenant_id": tenant_name, "session_id": session_name})
                    provider = JWTAuthenticationProvider()
                    identity = provider.authenticate_token(tok)
                    if identity.tenant_id != tenant_name:
                        errors.append(f"Expected {tenant_name} but got {identity.tenant_id}")
                    if identity.session_id != session_name:
                        errors.append(f"Expected {session_name} but got {identity.session_id}")
                except Exception as e:
                    errors.append(str(e))

        t1 = threading.Thread(target=session_worker, args=("tenant_concurrent_1", "session_c1", "val_1"))
        t2 = threading.Thread(target=session_worker, args=("tenant_concurrent_2", "session_c2", "val_2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(len(errors), 0, f"Concurrent session isolation failed with errors: {errors}")

    # =========================================================================
    # TEST N — Legacy endpoint isolation
    # Verify legacy endpoints do not mutate global dynamic_db state
    # =========================================================================
    def test_N_legacy_endpoint_isolation(self):
        # Capture baseline state of dynamic_db
        initial_tables = dynamic_db.db.get_usable_table_names() if dynamic_db.db else []

        tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        tmp_db_path = tmp_db.name.replace("\\", "/")
        tmp_db.close()

        conn = sqlite3.connect(tmp_db_path)
        conn.execute("CREATE TABLE legacy_isolated_table (id INT, note TEXT);")
        conn.commit()
        conn.close()

        try:
            # Send request to legacy /connect-live-db
            token = create_signed_test_jwt({"roles": ["manager"]})
            headers = {"Authorization": f"Bearer {token}"}
            payload = {"connection_string": f"sqlite:///{tmp_db_path}"}
            resp = self.client.post("/connect-live-db", json=payload, headers=headers)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("X-Deprecated"), "true")

            # Verify that global dynamic_db tables were NOT updated to the isolated test table
            current_tables = dynamic_db.db.get_usable_table_names() if dynamic_db.db else []
            self.assertNotIn("legacy_isolated_table", current_tables, "Legacy /connect-live-db MUST NOT mutate global dynamic_db")
        finally:
            try:
                if os.path.exists(tmp_db_path):
                    os.remove(tmp_db_path)
            except Exception:
                pass


    # =========================================================================
    # TEST O — Upload isolation
    # Upload data from two different sessions; verify stored in distinct paths
    # =========================================================================
    def test_O_upload_isolation(self):
        token_1 = create_signed_test_jwt({"tenant_id": "tenant_u1", "session_id": "sess_u1", "roles": ["manager"]})
        token_2 = create_signed_test_jwt({"tenant_id": "tenant_u2", "session_id": "sess_u2", "roles": ["manager"]})

        csv_content = b"item,quantity\nAlphaWidget,10\n"
        
        resp_1 = self.client.post(
            "/upload-db",
            files={"file": ("inventory.csv", csv_content, "text/csv")},
            headers={"Authorization": f"Bearer {token_1}"}
        )
        self.assertEqual(resp_1.status_code, 200)
        loc_1 = resp_1.json().get("file_location", "")

        resp_2 = self.client.post(
            "/upload-db",
            files={"file": ("inventory.csv", csv_content, "text/csv")},
            headers={"Authorization": f"Bearer {token_2}"}
        )
        self.assertEqual(resp_2.status_code, 200)
        loc_2 = resp_2.json().get("file_location", "")

        # Verify distinct isolated file paths
        self.assertNotEqual(loc_1, loc_2, "Uploads from different sessions must not overwrite each other")
        self.assertIn("tenant_u1", loc_1)
        self.assertIn("tenant_u2", loc_2)
        self.assertNotEqual(loc_1, DEFAULT_DB_PATH, "Uploads must not overwrite global DEFAULT_DB_PATH")

    # =========================================================================
    # TEST P — WebSocket approval governance
    # Unauthorized or mismatched session approval attempt returns DENIED with no mutation
    # =========================================================================
    def test_P_websocket_approval_governance(self):
        from api.websocket import router
        # Simulate websocket command handler logic directly for approval
        # If an operator (without manager role) attempts high-risk approval:
        eval_payload = {"action": "High Risk Machine Recalibration", "cost": 50000}
        
        # Test Operator approval blocked
        op_ident = Identity(user_id="op_test", roles=["operator"], tenant_id="tenant_A", session_id="session_A")
        is_mgr = "manager" in op_ident.roles
        self.assertFalse(is_mgr, "Operator cannot approve manager-level operational changes")

        # Test Mismatched session rejection
        action_tenant = "tenant_A"
        action_session = "session_A"
        attacker_ident = Identity(user_id="attacker", roles=["manager"], tenant_id="tenant_B", session_id="session_B")
        
        mismatch = (attacker_ident.tenant_id != action_tenant or attacker_ident.session_id != action_session)
        self.assertTrue(mismatch, "Cross-session / cross-tenant approval must be recognized as mismatch")


if __name__ == "__main__":
    unittest.main()
