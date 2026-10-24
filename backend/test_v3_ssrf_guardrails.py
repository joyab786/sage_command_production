# backend/test_v3_ssrf_guardrails.py
"""
SageCommand V3 — SSRF Guardrails and Network Policy Test Suite (B7)
Verifies:
1. Blocked IP categories including cloud metadata, multicast, unspecified, reserved, unusual encodings.
2. IPv4-mapped IPv6 unwrapping and policy application.
3. Hostname resolving to loopback via mock getaddrinfo.
4. Mixed DNS records with one public and one blocked address (rejects if any is blocked).
5. Address pinning preventing DNS rebinding (pinned IP passed as hostaddr).
6. Private ranges in production (blocked by default, allowed only when explicitly in SAGE_DB_ALLOWED_HOSTS).
7. Loopback permitted only in development and test, blocked in production.
8. Rate limit keyed by (tenant, user) with 429 and Retry-After header.
9. Uniform 503 DATABASE_UNREACHABLE response across blocked and unreachable targets without IP leaks.
10. Existing localhost behavior preserved in test environment.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import socket
import ipaddress
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from server import app
from core.auth import Identity
from core.config import SAGE_SECRET_KEY, SAGE_AUTH_ISSUER, SAGE_AUTH_AUDIENCE
from gateway.network_policy import (
    NetworkPolicyEngine,
    NetworkPolicy,
    DatabasePolicyBlockedError,
    normalize_and_unwrap_ip,
    resolve_all_ip_records,
    UNIFORM_SSRF_ERROR_MESSAGE,
    NEVER_ALLOWLISTABLE_NETWORKS
)
from gateway.db_gateway import db_gateway, DBConnectionRequest, GatewayAPIException
from governance.rate_limiter import SlidingWindowRateLimiter, db_test_rate_limiter, db_connect_rate_limiter
from data.schemas.database_contract import (
    TestConnectionRequest as SchemaTestConnectionRequest,
    CreateConnectionRequest,
    DatabaseType,
    AccessMode as ContractAccessMode,
    DataMode as ContractDataMode,
    GatewayErrorCode
)
import jwt
import time


class TestV3SSRFGuardrails(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.policy_engine = NetworkPolicyEngine()
        self.identity_mgr = Identity(
            user_id="mgr_ssrf_001",
            roles=["manager", "operator"],
            tenant_id="tenant_ssrf_test",
            session_id="session_ssrf_001"
        )
        self.headers_mgr = {
            "X-Tenant-ID": "tenant_ssrf_test",
            "X-User-ID": "mgr_ssrf_001",
            "X-Session-ID": "session_ssrf_001",
            "Authorization": "Bearer manager_token"
        }

    def _make_jwt(self, user_id="mgr_ssrf_001", tenant_id="tenant_ssrf_test", roles=None, session_id="session_ssrf_001"):
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "roles": roles or ["manager", "operator"],
            "iss": SAGE_AUTH_ISSUER,
            "aud": SAGE_AUTH_AUDIENCE,
            "exp": time.time() + 3600,
            "clearance_level": 2,
            "assigned_plants": ["plant_001", "*"]
        }
        return jwt.encode(payload, SAGE_SECRET_KEY, algorithm="HS256")


    # =========================================================================
    # 1. BLOCKED CATEGORIES (B3)
    # =========================================================================

    def test_01_blocked_categories_never_allowlistable(self):
        """Verify each blocked category is rejected unconditionally: metadata, multicast, unspecified, reserved."""
        blocked_targets = [
            # Cloud metadata
            ("169.254.169.254", 5432),
            ("169.254.0.1", 5432),
            ("fd00:ec2::254", 5432),
            ("100.100.100.200", 5432),
            ("fe80::1", 5432),
            # Multicast
            ("224.0.0.1", 5432),
            ("239.255.255.250", 5432),
            ("ff02::1", 5432),
            # Unspecified
            ("0.0.0.0", 5432),
            ("0.1.2.3", 5432),
            ("::", 5432),
            # Reserved
            ("240.0.0.1", 5432),
            ("255.255.255.255", 5432),
        ]
        for host, port in blocked_targets:
            with self.subTest(host=host, port=port):
                with self.assertRaises(DatabasePolicyBlockedError) as cm:
                    self.policy_engine.validate_host_and_port(host, port)
                self.assertIn(UNIFORM_SSRF_ERROR_MESSAGE, str(cm.exception))

    def test_02_unusual_ip_encodings_rejected(self):
        """Verify unusual IP encodings (octal, integer, hex) are rejected."""
        unusual_targets = [
            "0177.0.0.1",       # Octal
            "2130706433",       # Integer representation of 127.0.0.1
            "0x7f.0.0.1",       # Hex representation
            "017700000001",     # Pure octal
        ]
        for target in unusual_targets:
            with self.subTest(target=target):
                with self.assertRaises(DatabasePolicyBlockedError):
                    self.policy_engine.validate_host_and_port(target, 5432)

    # =========================================================================
    # 2. IPV4-MAPPED IPV6 (B1)
    # =========================================================================

    def test_03_ipv4_mapped_ipv6_unwrapping(self):
        """Verify IPv4-mapped IPv6 and 6to4 unwraps to underlying IPv4 and applies policy."""
        # ::ffff:169.254.169.254 -> metadata (never allowlistable)
        with self.assertRaises(DatabasePolicyBlockedError):
            self.policy_engine.validate_host_and_port("::ffff:169.254.169.254", 5432)

        # ::ffff:127.0.0.1 in production -> loopback blocked
        with patch.dict(os.environ, {"SAGE_ENV": "production"}):
            with self.assertRaises(DatabasePolicyBlockedError):
                self.policy_engine.validate_host_and_port("::ffff:127.0.0.1", 5432)

        # ::ffff:10.0.0.1 in production without allowlist -> private blocked
        with patch.dict(os.environ, {"SAGE_ENV": "production"}):
            with self.assertRaises(DatabasePolicyBlockedError):
                self.policy_engine.validate_host_and_port("::ffff:10.0.0.1", 5432)

        # 6to4 unwrap (2002:a9fe:a9fe:: corresponds to 169.254.169.254)
        with self.assertRaises(DatabasePolicyBlockedError):
            self.policy_engine.validate_host_and_port("2002:a9fe:a9fe::", 5432)

    # =========================================================================
    # 3. HOSTNAME RESOLVING TO LOOPBACK (B1, B4)
    # =========================================================================

    def test_04_hostname_resolving_to_loopback_mocked(self):
        """Verify hostname resolving to loopback via socket.getaddrinfo is blocked in production."""
        mock_addrinfo = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5432))]
        with patch("socket.getaddrinfo", return_value=mock_addrinfo):
            with patch.dict(os.environ, {"SAGE_ENV": "production"}):
                with self.assertRaises(DatabasePolicyBlockedError):
                    self.policy_engine.validate_host_and_port("internal.service.local", 5432)

    # =========================================================================
    # 4. MIXED DNS RECORDS (B1)
    # =========================================================================

    def test_05_mixed_dns_records_rejects_if_any_is_blocked(self):
        """Verify that if a hostname resolves to one public and one blocked IP, it is rejected."""
        mock_mixed = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 5432)),     # public
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 5432)),  # metadata (blocked)
        ]
        with patch("socket.getaddrinfo", return_value=mock_mixed):
            with self.assertRaises(DatabasePolicyBlockedError):
                self.policy_engine.validate_host_and_port("dual-homed.example.com", 5432)

        # Mixed public and loopback in production
        mock_mixed_loopback = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 5432)),     # public
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5432)),        # loopback
        ]
        with patch("socket.getaddrinfo", return_value=mock_mixed_loopback):
            with patch.dict(os.environ, {"SAGE_ENV": "production"}):
                with self.assertRaises(DatabasePolicyBlockedError):
                    self.policy_engine.validate_host_and_port("dual-homed.example.com", 5432)

    # =========================================================================
    # 5. ADDRESS PINNING PREVENTING DNS REBINDING (B2)
    # =========================================================================

    def test_06_address_pinning_prevents_dns_rebinding(self):
        """Verify that the validated IP is pinned and passed as hostaddr for postgres."""
        mock_public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 5432))]
        with patch("socket.getaddrinfo", return_value=mock_public):
            pinned_ip = self.policy_engine.validate_host_and_port("db.example.com", 5432)
            self.assertEqual(pinned_ip, "93.184.216.34")

        # Now test that db_gateway injects hostaddr with the pinned IP
        req = DBConnectionRequest(
            database_type="POSTGRESQL",
            host="db.example.com",
            port=5432,
            database="ops",
            username="testuser",
            password="testpassword",
            ssl_mode="REQUIRED"
        )
        with patch("socket.getaddrinfo", return_value=mock_public):
            raw_uri, adapter, pinned = db_gateway.validate_request(req, self.identity_mgr)
            self.assertEqual(pinned, "93.184.216.34")

        # In test_canonical_connection, verify create_engine receives connect_args with hostaddr
        canon_req = SchemaTestConnectionRequest(
            database_type=DatabaseType.POSTGRESQL,
            host="db.example.com",
            port=5432,
            database="ops",
            username="testuser",
            password="testpassword"
        )
        with patch("socket.getaddrinfo", return_value=mock_public):
            with patch("gateway.db_gateway.create_engine") as mock_engine:
                mock_conn = MagicMock()
                mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
                res = db_gateway.test_canonical_connection(canon_req, self.identity_mgr)
                self.assertTrue(res.reachable)
                # Verify hostaddr was passed to create_engine
                called_args, called_kwargs = mock_engine.call_args
                self.assertIn("connect_args", called_kwargs)
                self.assertEqual(called_kwargs["connect_args"].get("hostaddr"), "93.184.216.34")

    # =========================================================================
    # 6. PRIVATE RANGES IN PRODUCTION (B4)
    # =========================================================================

    def test_07_private_ranges_in_production_require_allowlist(self):
        """Verify private ranges (10/8, 172.16/12, 192.168/16, 100.64/10, fc00::/7) require allowlist in production."""
        private_ips = ["10.0.1.5", "172.16.2.1", "192.168.1.100", "100.64.0.1", "fc00::1"]

        with patch.dict(os.environ, {"SAGE_ENV": "production"}):
            # Without allowlist: must fail
            engine_no_allow = NetworkPolicyEngine(allowed_hosts=[])
            for pip in private_ips:
                with self.subTest(pip=pip, state="blocked"):
                    with self.assertRaises(DatabasePolicyBlockedError):
                        engine_no_allow.validate_host_and_port(pip, 5432)

            # With explicit allowlist: must succeed
            engine_with_allow = NetworkPolicyEngine(allowed_hosts=["10.0.1.5", "172.16.0.0/12", "192.168.1.0/24", "100.64.0.1", "fc00::/7"])
            for pip in private_ips:
                with self.subTest(pip=pip, state="allowlisted"):
                    pinned = engine_with_allow.validate_host_and_port(pip, 5432)
                    self.assertIsNotNone(pinned)

    # =========================================================================
    # 7. LOOPBACK PERMITTED ONLY IN DEV AND TEST (B4)
    # =========================================================================

    def test_08_loopback_allowed_in_dev_test_blocked_in_prod(self):
        """Verify loopback is allowed when SAGE_ENV is development or test, blocked in production."""
        loopback_hosts = ["127.0.0.1", "localhost", "::1"]

        # In test mode: allowed
        with patch.dict(os.environ, {"SAGE_ENV": "test"}):
            for h in loopback_hosts:
                with self.subTest(host=h, env="test"):
                    pinned = self.policy_engine.validate_host_and_port(h, 5432)
                    self.assertIsNotNone(pinned)

        # In development mode: allowed
        with patch.dict(os.environ, {"SAGE_ENV": "development"}):
            for h in loopback_hosts:
                with self.subTest(host=h, env="development"):
                    pinned = self.policy_engine.validate_host_and_port(h, 5432)
                    self.assertIsNotNone(pinned)

        # In production mode: blocked
        with patch.dict(os.environ, {"SAGE_ENV": "production"}):
            for h in loopback_hosts:
                with self.subTest(host=h, env="production"):
                    with self.assertRaises(DatabasePolicyBlockedError):
                        self.policy_engine.validate_host_and_port(h, 5432)

    # =========================================================================
    # 8. RATE LIMITING (B6)
    # =========================================================================

    def test_09_rate_limiting_test_and_create_endpoints(self):
        """Verify rate limiting keyed by (tenant, user) returns 429 with Retry-After header."""
        test_limiter = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
        rate_key = "tenant_test:user_test"

        # 10 requests allowed
        for i in range(10):
            allowed, count, retry_after = test_limiter.is_allowed_with_retry_after(rate_key)
            self.assertTrue(allowed, f"Request {i+1} should be allowed")
            self.assertEqual(retry_after, 0)

        # 11th request rejected with 429 Retry-After
        allowed, count, retry_after = test_limiter.is_allowed_with_retry_after(rate_key)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

        # Different user in same tenant is allowed
        diff_user_key = "tenant_test:user_other"
        allowed, _, _ = test_limiter.is_allowed_with_retry_after(diff_user_key)
        self.assertTrue(allowed)

        # Different tenant is allowed
        diff_tenant_key = "tenant_other:user_test"
        allowed, _, _ = test_limiter.is_allowed_with_retry_after(diff_tenant_key)
        self.assertTrue(allowed)

    def test_10_api_rate_limiting_returns_429_retry_after_header(self):
        """Verify API endpoints return HTTP 429 and Retry-After header when rate limit exceeded."""
        client_key = "tenant_limit_test:user_limit_test"
        db_test_rate_limiter.clear(client_key)

        token = self._make_jwt(user_id="user_limit_test", tenant_id="tenant_limit_test", roles=["operator"])
        headers = {
            "X-Tenant-ID": "tenant_limit_test",
            "X-User-ID": "user_limit_test",
            "X-Session-ID": "session_limit_test",
            "Authorization": f"Bearer {token}"
        }

        # Exhaust 10 requests
        for _ in range(10):
            db_test_rate_limiter.is_allowed_with_retry_after(client_key)


        # Next call to /api/v3/database/connections/test should return 429
        payload = {
            "database_type": "POSTGRESQL",
            "host": "localhost",
            "port": 5432,
            "database": "ops"
        }
        res = self.client.post("/api/v3/database/connections/test", json=payload, headers=headers)
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res.headers)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "RATE_LIMITED")

    # =========================================================================
    # 9. UNIFORM 503 DATABASE_UNREACHABLE ERROR (B5)
    # =========================================================================

    def test_11_uniform_503_across_blocked_and_unreachable_targets(self):
        """Verify identical 503 response and code across SSRF blocked, connection refused, and timeout."""
        headers = {
            "X-Tenant-ID": "tenant_uniform_test",
            "X-User-ID": "user_uniform_test",
            "X-Session-ID": "session_uniform_test",
            "Authorization": "Bearer operator_token"
        }
        db_test_rate_limiter.clear("tenant_uniform_test:user_uniform_test")

        # 1. SSRF Blocked Target (e.g. metadata)
        blocked_payload = {
            "database_type": "POSTGRESQL",
            "host": "169.254.169.254",
            "port": 5432,
            "database": "ops"
        }
        res_blocked = self.client.post("/api/v3/database/connections/test", json=blocked_payload, headers=headers)
        self.assertEqual(res_blocked.status_code, 503)
        body_blocked = res_blocked.json()
        self.assertFalse(body_blocked["success"])
        self.assertEqual(body_blocked["error"]["code"], "DATABASE_UNREACHABLE")
        self.assertEqual(body_blocked["error"]["message"], "Database host connection refused, blocked, or unreachable.")
        # Ensure no resolved IP in message
        self.assertNotIn("169.254.169.254", body_blocked["error"]["message"])

        # 2. Connection Refused / Unreachable Target (valid public IP but unreachable port/host)
        # Mock create_engine to simulate connection refused
        unreachable_payload = {
            "database_type": "POSTGRESQL",
            "host": "93.184.216.34",
            "port": 5432,
            "database": "ops"
        }
        with patch("gateway.db_gateway.create_engine", side_effect=Exception("could not connect to server: Connection refused")):
            res_unreachable = self.client.post("/api/v3/database/connections/test", json=unreachable_payload, headers=headers)
            self.assertEqual(res_unreachable.status_code, 503)
            body_unreachable = res_unreachable.json()
            self.assertFalse(body_unreachable["success"])
            self.assertEqual(body_unreachable["error"]["code"], "DATABASE_UNREACHABLE")
            self.assertEqual(body_unreachable["error"]["message"], "Database host connection refused, blocked, or unreachable.")
            # Ensure no internal driver text leaked
            self.assertNotIn("Connection refused", body_unreachable["error"]["message"])

        # Responses must be identical in structure and message
        self.assertEqual(body_blocked["error"]["code"], body_unreachable["error"]["code"])
        self.assertEqual(body_blocked["error"]["message"], body_unreachable["error"]["message"])

    # =========================================================================
    # 10. PRESERVATION OF EXISTING LOCALHOST TESTS IN TEST ENV (B7)
    # =========================================================================

    def test_12_existing_localhost_functionality_preserved_in_test_env(self):
        """Verify existing localhost SQLite / test connections continue to work seamlessly in test environment."""
        with patch.dict(os.environ, {"SAGE_ENV": "test"}):
            sqlite_payload = {
                "database_type": "SQLITE",
                "database": ":memory:"
            }
            res = self.client.post(
                "/api/v3/database/connections/test",
                json=sqlite_payload,
                headers=self.headers_mgr
            )
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertTrue(body["success"])
            self.assertTrue(body["result"]["reachable"])


if __name__ == "__main__":
    unittest.main()
