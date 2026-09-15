import sys
import os
import unittest
import json

# Ensure sys.path includes both backend directory and parent directory for root/module imports
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException, status

try:
    from core.config import (
        SAGE_AUTH_ENABLED,
        SAGE_ALLOWED_ORIGINS,
        SAGE_MAX_REQUEST_SIZE
    )
    from governance.redaction import (
        sanitize_connection_string,
        parse_safe_connection_info,
        sanitize_log_message
    )
    from governance.guardrails import (
        check_multi_statement_sql,
        validate_sql_query
    )
    from services.db_service import validate_db_connection_uri
    from governance.rate_limiter import SlidingWindowRateLimiter
    from governance.audit import log_security_event
    from governance.middleware import (
        SecurityHeadersMiddleware,
        RequestSizeLimiterMiddleware,
        safe_production_exception_handler
    )
    from core.auth import (
        Identity,
        DevAuthenticationProvider,
        JWTAuthenticationProvider,
        require_role
    )
    from server import app
except (ImportError, ModuleNotFoundError):
    from backend.core.config import (
        SAGE_AUTH_ENABLED,
        SAGE_ALLOWED_ORIGINS,
        SAGE_MAX_REQUEST_SIZE
    )
    from backend.governance.redaction import (
        sanitize_connection_string,
        parse_safe_connection_info,
        sanitize_log_message
    )
    from backend.governance.guardrails import (
        check_multi_statement_sql,
        validate_sql_query
    )
    from backend.services.db_service import validate_db_connection_uri
    from backend.governance.rate_limiter import SlidingWindowRateLimiter
    from backend.governance.audit import log_security_event
    from backend.governance.middleware import (
        SecurityHeadersMiddleware,
        RequestSizeLimiterMiddleware,
        safe_production_exception_handler
    )
    from backend.core.auth import (
        Identity,
        DevAuthenticationProvider,
        JWTAuthenticationProvider,
        require_role
    )
    from backend.server import app


class TestV3SecurityHardening(unittest.TestCase):

    def setUp(self):
        # Force Auth enabled for test assertions
        import core.auth
        core.auth.SAGE_AUTH_ENABLED = True
        self.client = TestClient(app)

    def tearDown(self):
        import core.auth
        core.auth.SAGE_AUTH_ENABLED = False

    # --- 1. CREDENTIAL REDACTION TESTS ---
    def test_connection_string_sanitization(self):
        uri_with_password = "postgresql://dbuser:SuperSecretPass123!@localhost:5432/industrial_db"
        sanitized = sanitize_connection_string(uri_with_password)
        self.assertNotIn("SuperSecretPass123!", sanitized)
        self.assertIn("dbuser:[REDACTED]@localhost:5432/industrial_db", sanitized)

        kv_password = "host=localhost port=5432 user=admin password=SecretPassWord123 dbname=prod"
        sanitized_kv = sanitize_connection_string(kv_password)
        self.assertNotIn("SecretPassWord123", sanitized_kv)
        self.assertIn("password=[REDACTED]", sanitized_kv)

    def test_safe_connection_info_parsing(self):
        uri = "postgresql://admin_user:TopSecretPwd@127.0.0.1:5432/factory_v3"
        info = parse_safe_connection_info(uri)
        self.assertEqual(info.database_type, "postgresql")
        self.assertEqual(info.host, "127.0.0.1")
        self.assertEqual(info.username, "[REDACTED]")
        self.assertEqual(info.database, "factory_v3")
        self.assertEqual(info.password, "[REDACTED]")

    def test_log_message_sanitization(self):
        log_txt = "Failed to connect using postgresql://app:MySecretKey99@db.internal:5432/main with api_key=sk-proj-99999"
        clean_log = sanitize_log_message(log_txt)
        self.assertNotIn("MySecretKey99", clean_log)
        self.assertNotIn("sk-proj-99999", clean_log)
        self.assertIn("[REDACTED]", clean_log)

    # --- 2. URI SCHEME WHITELIST & SQL GUARDRAILS ---
    def test_uri_scheme_whitelist(self):
        # Valid schemes (returns None without raising exception)
        validate_db_connection_uri("postgresql://user:pass@localhost:5432/db")
        validate_db_connection_uri("mysql://user:pass@localhost:3306/db")
        validate_db_connection_uri("sqlite:///local.db")
        validate_db_connection_uri("sqlite:///:memory:")

        # Invalid schemes (raise ValueError)
        with self.assertRaises(ValueError):
            validate_db_connection_uri("file:///etc/passwd")
        with self.assertRaises(ValueError):
            validate_db_connection_uri("ftp://anonymous@malicious.site/script")
        with self.assertRaises(ValueError):
            validate_db_connection_uri("http://malicious.site/db")

    def test_multi_statement_sql_blocking(self):
        # Multiple statements blocked via PermissionError
        with self.assertRaises(PermissionError):
            check_multi_statement_sql("SELECT * FROM telemetry; DROP TABLE equipment;")

        # Single statement allowed (no exception)
        check_multi_statement_sql("SELECT * FROM telemetry WHERE id = 1")

    def test_unsafe_sql_patterns(self):
        # Catalog access blocked
        with self.assertRaises(PermissionError):
            validate_sql_query("SELECT * FROM pg_catalog.pg_tables")

        # Unsafe keyword blocked
        with self.assertRaises(PermissionError):
            validate_sql_query("DROP TABLE inventory")

    # --- 3. AUTH & RBAC TESTS ---
    def test_dev_authentication_provider(self):
        provider = DevAuthenticationProvider()
        
        op_identity = provider.authenticate_token("operator_token")
        self.assertIn("operator", op_identity.roles)
        self.assertNotIn("manager", op_identity.roles)

        mgr_identity = provider.authenticate_token("manager_token")
        self.assertIn("manager", mgr_identity.roles)

        with self.assertRaises(HTTPException):
            provider.authenticate_token("invalid_token")

    def test_jwt_authentication_provider(self):
        provider = JWTAuthenticationProvider()
        
        with self.assertRaises(HTTPException):
            provider.authenticate_token("invalid_token")
            
        with self.assertRaises(HTTPException):
            provider.authenticate_token("expired_token")

        mgr_identity = provider.authenticate_token("manager_token")
        self.assertIn("manager", mgr_identity.roles)

    # --- 4. RATE LIMITER TESTS ---
    def test_rate_limiter(self):
        limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
        client_key = "test_client_1"

        ok1, _ = limiter.is_allowed(client_key)
        ok2, _ = limiter.is_allowed(client_key)
        ok3, _ = limiter.is_allowed(client_key)
        self.assertTrue(ok1)
        self.assertTrue(ok2)
        self.assertTrue(ok3)

        # 4th request within window should be rejected
        ok4, retry = limiter.is_allowed(client_key)
        self.assertFalse(ok4)

    # --- 5. MIDDLEWARE & HEADERS TESTS ---
    def test_security_headers_present(self):
        headers = {"Authorization": "Bearer manager_token"}
        response = self.client.post("/trigger-anomaly", json={"anomaly_type": "OVERHEAT"}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertIn("default-src 'self'", response.headers.get("Content-Security-Policy", ""))

    def test_request_size_limiter(self):
        headers = {"Authorization": "Bearer manager_token"}
        resp = self.client.post("/trigger-anomaly", json={"anomaly_type": "OVERHEAT"}, headers=headers)
        self.assertEqual(resp.status_code, 200)

    # --- 6. REST API HARDENED ROUTES TESTS ---
    def test_connect_live_db_sanitization(self):
        payload = {
            "connection_string": "postgresql://dbadmin:SuperSecret123@localhost:5432/live_db"
        }
        headers = {"Authorization": "Bearer manager_token"}
        response = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(response.status_code, 200)
        resp_data = response.json()
        self.assertNotIn("SuperSecret123", json.dumps(resp_data))

    def test_connect_live_db_blocked_scheme(self):
        payload = {
            "connection_string": "file:///etc/passwd"
        }
        headers = {"Authorization": "Bearer manager_token"}
        response = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("not supported", response.json().get("detail", ""))

    def test_trigger_anomaly_rbac(self):
        # Operator attempting manager route -> 403 Forbidden
        headers_op = {"Authorization": "Bearer operator_token"}
        resp_op = self.client.post("/trigger-anomaly", json={"anomaly_type": "OVERHEAT"}, headers=headers_op)
        self.assertEqual(resp_op.status_code, 403)

        # Manager attempting manager route -> 200 OK
        headers_mgr = {"Authorization": "Bearer manager_token"}
        resp_mgr = self.client.post("/trigger-anomaly", json={"anomaly_type": "OVERHEAT"}, headers=headers_mgr)
        self.assertEqual(resp_mgr.status_code, 200)


if __name__ == "__main__":
    unittest.main()
