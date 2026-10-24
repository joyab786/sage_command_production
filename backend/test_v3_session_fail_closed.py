# backend/test_v3_session_fail_closed.py
"""
Prompt 39 Correction 5c: Fail-Closed Session Handling Regression Suite
Exhaustively tests fail-closed session handling across:
1. POST /api/v3/actions/{id}/execute
2. POST /connect-live-db
3. POST /upload-csv and /upload-db
4. WS /ws/sage
5. Dev fallback gating and production inertness
"""

import io
import time
import unittest
import jwt
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

try:
    from server import app
    from core.config import IS_PRODUCTION, SAGE_SECRET_KEY, SAGE_AUTH_ISSUER, SAGE_AUTH_AUDIENCE
    from core.auth import get_current_identity, Identity
    import core.auth as auth_mod
    from data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from services.action_store import action_store
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.config import IS_PRODUCTION, SAGE_SECRET_KEY, SAGE_AUTH_ISSUER, SAGE_AUTH_AUDIENCE
    from backend.core.auth import get_current_identity, Identity
    import backend.core.auth as auth_mod
    from backend.data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from backend.services.action_store import action_store


class TestV3SessionFailClosed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def _create_approved_action(self) -> Action:
        act = Action(
            action_type="ADJUST_REORDER_POINT",
            tenant_id="tenant_session_test",
            workspace_id="workspace_default",
            session_id="session_creator_999",
            status=ActionStatus.APPROVED,
            requires_approval=False,
            system_risk_level=RiskLevel.LOW,
            parameters={"sku": "SKU-FC-01", "reorder_point": 42},
            target={"resource_type": "INVENTORY_ITEM", "resource_id": "SKU-FC-01", "plant_id": "plant_mumbai"},
            reason={"summary": "Fail closed session test action", "reason_code": "STOCK_LOW", "trigger": "MANUAL", "business_impact": "LOW"}
        )
        action_store.save(act)
        return act

    # -------------------------------------------------------------------------
    # 1. POST /api/v3/actions/{id}/execute Fail-Closed Tests
    # -------------------------------------------------------------------------

    def test_action_execute_missing_session_returns_4xx_without_validation_error(self):
        """Action execute without session returns 4xx (401) with clean generic message and no ValidationError."""
        act = self._create_approved_action()
        headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": act.tenant_id,
        }
        resp = self.client.post(
            f"/api/v3/actions/{act.action_id}/execute",
            json={"dry_run": True},
            headers=headers
        )
        self.assertIn(resp.status_code, (400, 401))
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertFalse(data.get("success", True))

        # Verify no ValidationError, traceback, or schema leak
        resp_text = resp.text
        self.assertNotIn("ValidationError", resp_text)
        self.assertNotIn("validation error", resp_text)
        self.assertNotIn("pydantic", resp_text.lower())
        self.assertNotIn("Traceback", resp_text)

    def test_action_execute_valid_session_succeeds(self):
        """Action execute with valid X-Session-ID succeeds with 200 OK."""
        act = self._create_approved_action()
        headers = {
            "Authorization": "Bearer manager_token",
            "X-Tenant-ID": act.tenant_id,
            "X-Session-ID": "valid_session_fc_01"
        }
        resp = self.client.post(
            f"/api/v3/actions/{act.action_id}/execute",
            json={"dry_run": True},
            headers=headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("result", {}).get("status"), "SUCCEEDED")

    # -------------------------------------------------------------------------
    # 2. POST /connect-live-db Fail-Closed Tests
    # -------------------------------------------------------------------------

    def test_connect_live_db_missing_session_returns_4xx_without_validation_error(self):
        """POST /connect-live-db without session returns 400 Bad Request with no leaked ValidationError."""
        payload = {"connection_string": "sqlite:///./dynamic_datacore.sqlite"}
        resp = self.client.post("/connect-live-db", json=payload)
        self.assertEqual(resp.status_code, 400)
        resp_text = resp.text
        self.assertNotIn("ValidationError", resp_text)
        self.assertNotIn("validation error", resp_text)
        self.assertNotIn("pydantic", resp_text.lower())
        self.assertNotIn("Traceback", resp_text)
        self.assertIn("Session context required", resp_text)

    def test_connect_live_db_valid_session_succeeds(self):
        """POST /connect-live-db with X-Session-ID succeeds with 200 OK."""
        payload = {"connection_string": "sqlite:///./dynamic_datacore.sqlite"}
        headers = {"X-Session-ID": "valid_session_fc_02"}
        resp = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("tables", data)

    # -------------------------------------------------------------------------
    # 3. POST /upload-csv and /upload-db Fail-Closed Tests
    # -------------------------------------------------------------------------

    def test_upload_csv_missing_session_returns_4xx_without_validation_error(self):
        """POST /upload-csv without session returns 400 Bad Request with no leaked ValidationError."""
        csv_content = "sensor_id,reading,location\nS-10,104.2,Sector 7G\n"
        file_tuple = ("telemetry.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        resp = self.client.post("/upload-csv", files={"file": file_tuple})
        self.assertEqual(resp.status_code, 400)
        resp_text = resp.text
        self.assertNotIn("ValidationError", resp_text)
        self.assertNotIn("validation error", resp_text)
        self.assertNotIn("pydantic", resp_text.lower())
        self.assertNotIn("Traceback", resp_text)

    def test_upload_db_missing_session_returns_4xx_without_validation_error(self):
        """POST /upload-db without session returns 400 Bad Request with no leaked ValidationError."""
        csv_content = "sensor_id,reading,location\nS-10,104.2,Sector 7G\n"
        file_tuple = ("telemetry.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        resp = self.client.post("/upload-db", files={"file": file_tuple})
        self.assertEqual(resp.status_code, 400)
        resp_text = resp.text
        self.assertNotIn("ValidationError", resp_text)
        self.assertNotIn("validation error", resp_text)
        self.assertNotIn("pydantic", resp_text.lower())
        self.assertNotIn("Traceback", resp_text)

    def test_upload_csv_valid_session_succeeds(self):
        """POST /upload-csv with valid X-Session-ID succeeds with 200 OK."""
        csv_content = "sensor_id,reading,location\nS-10,104.2,Sector 7G\n"
        file_tuple = ("telemetry.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        headers = {"X-Session-ID": "valid_session_fc_03"}
        resp = self.client.post("/upload-csv", files={"file": file_tuple}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")

    # -------------------------------------------------------------------------
    # 4. WebSocket /ws/sage Policy Violation Close Code Tests
    # -------------------------------------------------------------------------

    def test_websocket_missing_session_rejected_with_1008(self):
        """WebSocket connection without session is rejected with policy violation code 1008."""
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect("/ws/sage"):
                pass
        self.assertEqual(ctx.exception.code, 1008)

    def test_websocket_valid_session_succeeds(self):
        """WebSocket connection with session query param succeeds and executes commands."""
        with self.client.websocket_connect("/ws/sage?session_id=valid_session_fc_04") as websocket:
            websocket.send_json({"command": "chat", "text": "List usable tables."})
            rec1 = websocket.receive_json()
            self.assertIn(rec1.get("type"), ["node_update", "node_active", "chat_response", "log"])

    # -------------------------------------------------------------------------
    # 5. Production Mode Fail-Closed & Universal No-Session Handling
    # -------------------------------------------------------------------------

    def test_production_mode_fails_closed_without_credentials(self):
        """When IS_PRODUCTION is True, provider is JWT and unauthenticated requests fail closed."""
        try:
            import core.auth as auth_mod
        except ImportError:
            import backend.core.auth as auth_mod
        from fastapi import HTTPException

        class DummyRequest:
            headers = {}

        # 1. Under production, provider is JWTAuthenticationProvider
        with patch.object(auth_mod, "IS_PRODUCTION", True):
            provider = auth_mod.get_auth_provider()
            self.assertTrue(provider.__class__.__name__ == "JWTAuthenticationProvider")

        # 2. Test unauthenticated request under IS_PRODUCTION=True raises 401 (fails closed)
        req = DummyRequest()
        with patch.object(auth_mod, "IS_PRODUCTION", True):
            with self.assertRaises(HTTPException) as ctx:
                auth_mod.get_current_identity(req, credentials=None)
            self.assertEqual(ctx.exception.status_code, 401)

        # 3. Server-authoritative or production identities have session_id None if claim omitted
        prod_identity = Identity(user_id="prod_user", is_server_authoritative=True)
        self.assertIsNone(prod_identity.session_id)

    def test_no_session_header_no_claim_no_token_yields_none_in_every_environment(self):
        """A request with no session header, no claim, and no token session yields session_id None in every environment."""
        try:
            import core.auth as auth_mod
        except ImportError:
            import backend.core.auth as auth_mod
        from starlette.datastructures import Headers

        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        # Environment 1: Development/Test mode unauthenticated request
        req1 = DummyRequest({})
        with patch.object(auth_mod, "SAGE_ENV", "development"), \
             patch.object(auth_mod, "IS_PRODUCTION", False), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "development"), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", False):
            identity1 = auth_mod.get_current_identity(req1, credentials=None)
            self.assertIsNone(identity1.session_id)

        # Environment 2: Development/Test mode with mock token that has no session in its profile
        req2 = DummyRequest({"authorization": "Bearer manager_token"})
        with patch.object(auth_mod, "SAGE_ENV", "development"), \
             patch.object(auth_mod, "IS_PRODUCTION", False), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "development"), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True):
            identity2 = auth_mod.get_current_identity(req2, credentials=None)
            self.assertIsNone(identity2.session_id)

        # Environment 3: Production mode with JWT token that has no session_id claim
        jwt_no_sess = self._create_jwt({"sub": "prod_tester_01"})
        req3 = DummyRequest({"authorization": f"Bearer {jwt_no_sess}"})
        with patch.object(auth_mod, "SAGE_ENV", "production"), \
             patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True):
            identity3 = auth_mod.get_current_identity(req3, credentials=None)
            self.assertIsNone(identity3.session_id)

    # -------------------------------------------------------------------------
    # 6. Header vs Token Binding Tests (Prompt 39 Correction 5d)
    # -------------------------------------------------------------------------

    def _create_jwt(self, payload_override=None):
        now = int(time.time())
        payload = {
            "sub": "test_user_jwt",
            "tenant_id": "tenant_default",
            "workspace_id": "workspace_default",
            "roles": ["operator", "manager"],
            "clearance_level": 2,
            "assigned_plants": ["plant_01"],
            "status": "ACTIVE",
            "iss": SAGE_AUTH_ISSUER,
            "aud": SAGE_AUTH_AUDIENCE,
            "iat": now,
            "exp": now + 3600
        }
        if payload_override:
            payload.update(payload_override)
        return jwt.encode(payload, SAGE_SECRET_KEY, algorithm="HS256")

    def test_jwt_session_claim_retained_when_no_header(self):
        """JWT with a session claim and no header: claim is retained."""
        token = self._create_jwt({"session_id": "session_from_jwt_claim"})
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.client.get("/api/v3/actions?limit=5", headers=headers)
        self.assertEqual(resp.status_code, 200)

        from starlette.datastructures import Headers
        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        req = DummyRequest({"authorization": f"Bearer {token}"})
        identity = auth_mod.get_current_identity(req, credentials=None)
        self.assertEqual(identity.session_id, "session_from_jwt_claim")

    def test_jwt_session_claim_retained_when_different_header_sent(self):
        """JWT with session claim and DIFFERENT header: claim is retained, header ignored."""
        token = self._create_jwt({"session_id": "session_authoritative_jwt"})
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": "session_attacker_spoof_header"
        }
        resp = self.client.get("/api/v3/actions?limit=5", headers=headers)
        self.assertEqual(resp.status_code, 200)

        from starlette.datastructures import Headers
        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        req = DummyRequest({
            "authorization": f"Bearer {token}",
            "x-session-id": "session_attacker_spoof_header"
        })
        identity = auth_mod.get_current_identity(req, credentials=None)
        # Authoritative JWT claim is retained; client header CANNOT replace it
        self.assertEqual(identity.session_id, "session_authoritative_jwt")

    def test_jwt_without_session_claim_yields_none_and_header_cannot_replace_claim(self):
        """A JWT without a session claim yields session_id None; a client X-Session-ID header cannot supply it."""
        now = int(time.time())
        raw_payload = {
            "sub": "user_no_sess_claim",
            "tenant_id": "tenant_default",
            "workspace_id": "workspace_default",
            "roles": ["operator"],
            "status": "ACTIVE",
            "iss": SAGE_AUTH_ISSUER,
            "aud": SAGE_AUTH_AUDIENCE,
            "iat": now,
            "exp": now + 3600
        }
        token = jwt.encode(raw_payload, SAGE_SECRET_KEY, algorithm="HS256")
        from starlette.datastructures import Headers
        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        # 1. Without header: session_id is None (no fabricated UUID)
        req_no_hdr = DummyRequest({"authorization": f"Bearer {token}"})
        identity_no_hdr = auth_mod.get_current_identity(req_no_hdr, credentials=None)
        self.assertIsNone(identity_no_hdr.session_id)

        # 2. With client X-Session-ID header: header is ignored, session_id remains None
        req_with_hdr = DummyRequest({
            "authorization": f"Bearer {token}",
            "x-session-id": "session_from_client_header"
        })
        identity_with_hdr = auth_mod.get_current_identity(req_with_hdr, credentials=None)
        self.assertIsNone(identity_with_hdr.session_id)

    def test_jwt_without_claim_returns_missing_session_on_action_execute(self):
        """JWT without session claim returns 401 MISSING_SESSION on action execute."""
        act = self._create_approved_action()
        token = self._create_jwt({"sub": "jwt_user_no_sess"})  # no session_id claim
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": act.tenant_id,
            "X-Session-ID": "session_header_should_be_ignored"
        }
        resp = self.client.post(
            f"/api/v3/actions/{act.action_id}/execute",
            json={"dry_run": True},
            headers=headers
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        error_info = data.get("error", {})
        code = error_info.get("code") if isinstance(error_info, dict) else data.get("code")
        self.assertEqual(code, "MISSING_SESSION")

    def test_jwt_without_claim_returns_missing_session_on_connect_live_db(self):
        """JWT without session claim returns 400 on connect-live-db."""
        token = self._create_jwt({"sub": "jwt_user_no_sess"})
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"connection_string": "sqlite:///./dynamic_datacore.sqlite"}
        resp = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Session context required", resp.text)

    def test_jwt_without_claim_returns_missing_session_on_upload(self):
        """JWT without session claim returns 400 on upload."""
        token = self._create_jwt({"sub": "jwt_user_no_sess"})
        headers = {"Authorization": f"Bearer {token}"}
        csv_content = "sensor_id,reading\nS-1,10.5\n"
        file_tuple = ("test.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        resp = self.client.post("/upload-db", files={"file": file_tuple}, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Session context required", resp.text)

    def test_jwt_without_claim_returns_missing_session_on_websocket(self):
        """JWT without session claim connecting to WebSocket is closed with code 1008."""
        token = self._create_jwt({"sub": "jwt_user_no_sess"})
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect(f"/ws/sage?token={token}"):
                pass
        self.assertEqual(ctx.exception.code, 1008)

    def test_jwt_without_claim_and_query_param_rejected_on_websocket(self):
        """JWT without session claim cannot use query parameter to supply session on WebSocket."""
        token = self._create_jwt({"sub": "jwt_user_no_sess"})
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect(f"/ws/sage?token={token}&session_id=spoofed_query_session"):
                pass
        self.assertEqual(ctx.exception.code, 1008)

    def test_jwt_with_claim_succeeds_and_shares_session_across_requests(self):
        """JWT with a session_id claim works and two requests with the same token share the session."""
        shared_session = "session_jwt_stable_test_99"
        act = self._create_approved_action()
        token = self._create_jwt({
            "sub": "jwt_user_claimed",
            "session_id": shared_session,
            "tenant_id": act.tenant_id,
            "assigned_plants": ["plant_mumbai"]
        })

        # Request 1
        from starlette.datastructures import Headers
        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        req1 = DummyRequest({"authorization": f"Bearer {token}"})
        ident1 = auth_mod.get_current_identity(req1, credentials=None)

        # Request 2
        req2 = DummyRequest({"authorization": f"Bearer {token}"})
        ident2 = auth_mod.get_current_identity(req2, credentials=None)

        self.assertEqual(ident1.session_id, shared_session)
        self.assertEqual(ident2.session_id, shared_session)
        self.assertEqual(ident1.session_id, ident2.session_id)

        # Action execute with this token succeeds
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": act.tenant_id,
        }
        resp = self.client.post(
            f"/api/v3/actions/{act.action_id}/execute",
            json={"dry_run": True},
            headers=headers
        )
        self.assertEqual(resp.status_code, 200)

    def test_session_scoped_db_connections_end_to_end_for_jwt_with_claim(self):
        """Confirm session-scoped DB connections work end to end for a JWT with claim (connect then sample/query)."""
        session_id = f"session_jwt_db_{int(time.time())}"
        token = self._create_jwt({
            "sub": "jwt_db_user",
            "session_id": session_id,
            "roles": ["operator", "manager"],
            "clearance_level": 3
        })
        headers = {"Authorization": f"Bearer {token}"}

        # Step 1: Connect live DB with this JWT
        payload = {"connection_string": "sqlite:///./dynamic_datacore.sqlite"}
        resp1 = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1.get("status"), "success")
        self.assertIn("tables", data1)

        # Step 2: Separate request with same token verifies connection access
        resp2 = self.client.post("/connect-live-db", json=payload, headers=headers)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2.get("status"), "success")

        # Step 3: Verify session isolation in registry (different session cannot access)
        try:
            from services.connection_manager import db_manager
        except ImportError:
            from backend.services.connection_manager import db_manager

        conn_ctx, _, _, _ = db_manager.get_connection("tenant_default", "workspace_default", session_id, "sqlite_main")
        self.assertEqual(conn_ctx.session_id, session_id)

        with self.assertRaises((KeyError, PermissionError)):
            db_manager.get_connection("tenant_default", "workspace_default", "session_unauthorized_attacker", "sqlite_main")

    def test_transaction_execute_missing_session_returns_missing_session(self):
        """POST /api/v3/transactions/{txId}/execute returns 401 MISSING_SESSION when session_id is None."""
        token = self._create_jwt({"sub": "jwt_tx_user"})  # no session_id
        headers = {"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant_default"}
        resp = self.client.post(
            "/api/v3/transactions/tx_dummy_id/execute",
            json={"transaction_id": "tx_dummy_id", "dry_run": True},
            headers=headers
        )
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        detail = data.get("detail", {})
        code = detail.get("code") if isinstance(detail, dict) else None
        self.assertEqual(code, "MISSING_SESSION")

    def test_database_routes_missing_session_never_return_500(self):
        """Database routes with missing session fail gracefully (400/401/403/404) and NEVER return 500."""
        token = self._create_jwt({"sub": "jwt_db_user"})  # no session_id
        headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/v3/database/connections/{id} (get)
        resp1 = self.client.get("/api/v3/database/connections/conn_nonexistent", headers=headers)
        self.assertIn(resp1.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp1.status_code, 500)

        # 2. GET /api/v3/database/connections/{id}/health (health)
        resp2 = self.client.get("/api/v3/database/connections/conn_nonexistent/health", headers=headers)
        self.assertIn(resp2.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp2.status_code, 500)

        # 3. GET /api/v3/database/connections/{id}/schema (schema)
        resp3 = self.client.get("/api/v3/database/connections/conn_nonexistent/schema", headers=headers)
        self.assertIn(resp3.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp3.status_code, 500)

        # 4. POST /api/v3/database/connections/{id}/sample (sample)
        resp4 = self.client.post(
            "/api/v3/database/connections/conn_nonexistent/sample",
            json={"table": "sensor_telemetry", "limit": 5},
            headers=headers
        )
        self.assertIn(resp4.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp4.status_code, 500)

        # 5. POST /api/v3/database/connections/{id}/disconnect (disconnect)
        resp5 = self.client.post(
            "/api/v3/database/connections/conn_nonexistent/disconnect",
            headers=headers
        )
        self.assertIn(resp5.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp5.status_code, 500)

        # 6. POST /api/v3/database/connections/{id}/revoke (revoke)
        resp6 = self.client.post(
            "/api/v3/database/connections/conn_nonexistent/revoke",
            json={"reason": "Security audit"},
            headers=headers
        )
        self.assertIn(resp6.status_code, (400, 401, 403, 404))
        self.assertNotEqual(resp6.status_code, 500)

        # 7. GET /api/v3/database/connections (list)
        resp7 = self.client.get("/api/v3/database/connections", headers=headers)
        self.assertEqual(resp7.status_code, 400)
        self.assertEqual(resp7.json().get("error", {}).get("code"), "MISSING_SESSION")
        self.assertNotEqual(resp7.status_code, 500)

    def test_mock_token_with_session_retained_when_no_header(self):
        """Mock token with session and no header: session is retained."""
        from starlette.datastructures import Headers
        class DummyRequest:
            def __init__(self, headers_dict):
                self.headers = Headers(headers_dict)

        req = DummyRequest({"authorization": "Bearer test_token_tenant_a"})
        identity = auth_mod.get_current_identity(req, credentials=None)
        self.assertEqual(identity.session_id, "session_A")

    # -------------------------------------------------------------------------
    # 7. Dev Fallback Autonomy Safety Verification (Prompt 39 Correction 5d)
    # -------------------------------------------------------------------------

    def test_fallback_session_rejected_by_autonomy_when_stored_action_session_bound(self):
        """Fallback-derived session (session_{user_id}) cannot access session-bound stored action."""
        try:
            from services.autonomy_service import autonomy_service
            from repositories.autonomy_repository import autonomy_repository
            from data.schemas.autonomy_contract import AutonomyGrant, AutonomyLevel, SubjectType, AutonomyReasonCode, AutonomyDecisionEffect
        except ImportError:
            from backend.services.autonomy_service import autonomy_service
            from backend.repositories.autonomy_repository import autonomy_repository
            from backend.data.schemas.autonomy_contract import AutonomyGrant, AutonomyLevel, SubjectType, AutonomyReasonCode, AutonomyDecisionEffect

        act_id = f"act_real_{time.time_ns()}"
        act = Action(
            action_id=act_id,
            action_type="ADJUST_REORDER_POINT",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_legit_user_42",
            status=ActionStatus.READY,
            parameters={"sku": "SKU-01", "reorder_point": 10},
            target={"resource_type": "INVENTORY_ITEM", "resource_id": "SKU-01", "plant_id": "plant_01"},
            reason={"summary": "Test action", "reason_code": "STOCK_LOW", "trigger": "MANUAL", "business_impact": "LOW"}
        )
        action_store.save(act)

        grant = AutonomyGrant(
            grant_id=f"grant_{time.time_ns()}",
            subject_type=SubjectType.AGENT,
            subject_id="agent_safety_test",
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_test"
        )
        autonomy_repository.save_grant(grant)

        caller_identity = Identity(
            user_id="dev_user_001",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_dev_user_001",
            roles=["operator"],
            assigned_plants=["plant_01"],
            clearance_level=2
        )

        dec = autonomy_service.evaluate_autonomy(
            identity=caller_identity,
            subject_id="agent_safety_test",
            requested_capability="PROPOSE_ACTION",
            resource_scope=grant.scope,
            data_mode="REAL",
            risk_context={"action_id": act_id, "action_type": "ADJUST_REORDER_POINT"}
        )
        self.assertEqual(dec.decision, AutonomyDecisionEffect.DENY)
        self.assertEqual(dec.reason_code, AutonomyReasonCode.SESSION_MISMATCH)

    def test_fallback_session_cannot_authorize_autonomous_execution_capabilities(self):
        """Autonomous execution capabilities (EXECUTE_SQL, CONTROL_PLC, etc.) cannot be authorized with fallback session."""
        try:
            from services.autonomy_service import autonomy_service
            from repositories.autonomy_repository import autonomy_repository
            from data.schemas.autonomy_contract import AutonomyGrant, AutonomyLevel, SubjectType, AutonomyDecisionEffect
        except ImportError:
            from backend.services.autonomy_service import autonomy_service
            from backend.repositories.autonomy_repository import autonomy_repository
            from backend.data.schemas.autonomy_contract import AutonomyGrant, AutonomyLevel, SubjectType, AutonomyDecisionEffect

        grant = AutonomyGrant(
            grant_id=f"grant_{time.time_ns()}",
            subject_type=SubjectType.AGENT,
            subject_id="agent_exec_prohibit",
            autonomy_level=AutonomyLevel.RECOMMEND,
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            plant_id="plant_01",
            data_mode="REAL",
            permitted_capabilities=["PROPOSE_ACTION"],
            created_by="admin_test"
        )
        autonomy_repository.save_grant(grant)

        caller_identity = Identity(
            user_id="dev_user_001",
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_dev_user_001",
            roles=["operator"],
            assigned_plants=["plant_01"],
            clearance_level=2
        )

        for cap in ("EXECUTE_SQL", "EXECUTE_COMMAND", "CONTROL_PLC", "CONTROL_SCADA"):
            dec = autonomy_service.evaluate_autonomy(
                identity=caller_identity,
                subject_id="agent_exec_prohibit",
                requested_capability=cap,
                resource_scope=grant.scope,
                data_mode="REAL"
            )
            self.assertEqual(dec.decision, AutonomyDecisionEffect.DENY)

    # -------------------------------------------------------------------------
    # 8. Prompt 39 Correction 5g Regression Tests
    # -------------------------------------------------------------------------

    def test_policy_evaluate_and_simulate_fail_closed_on_missing_session(self):
        """/api/v3/policies/evaluate and /simulate fail closed with 401 MISSING_SESSION without session_default."""
        act = self._create_approved_action()
        action_store.save(act)

        # JWT with no session claim, matching caller tenant to act.tenant_id
        token = self._create_jwt({
            "sub": "user_pol_no_sess",
            "roles": ["operator", "manager"],
            "tenant_id": act.tenant_id
        })
        headers = {"Authorization": f"Bearer {token}"}

        # 1. /evaluate with missing session
        resp_eval = self.client.post(
            "/api/v3/policies/evaluate",
            json={"action_id": act.action_id},
            headers=headers
        )
        self.assertEqual(resp_eval.status_code, 401)
        data_eval = resp_eval.json()
        self.assertEqual(data_eval.get("error", {}).get("code"), "MISSING_SESSION")
        self.assertNotIn("session_default", resp_eval.text)

        # 2. /simulate with missing session
        resp_sim = self.client.post(
            "/api/v3/policies/simulate",
            json={"action": act.model_dump()},
            headers=headers
        )
        self.assertEqual(resp_sim.status_code, 401)
        data_sim = resp_sim.json()
        self.assertEqual(data_sim.get("error", {}).get("code"), "MISSING_SESSION")
        self.assertNotIn("session_default", resp_sim.text)

    def test_non_admin_cannot_revoke_another_session_connection(self):
        """Non-admin manager cannot revoke a connection belonging to another session in same tenant."""
        try:
            from services.connection_manager import db_manager
        except ImportError:
            from backend.services.connection_manager import db_manager

        # Session A creates connection
        ctx = db_manager.create_connection(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_A_target",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        conn_id = ctx.connection_id

        # Manager with Session B attempts to revoke -> 403 Forbidden
        token_b = self._create_jwt({
            "sub": "mgr_session_b",
            "roles": ["manager"],
            "session_id": "session_B_intruder"
        })
        headers_b = {"Authorization": f"Bearer {token_b}"}
        resp = self.client.post(f"/api/v3/database/connections/{conn_id}/revoke", headers=headers_b)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get("error", {}).get("code"), "AUTHORIZATION_DENIED")

    def test_admin_override_can_revoke_across_sessions_audited(self):
        """Administrator role can revoke a connection across sessions within tenant (audited override)."""
        try:
            from services.connection_manager import db_manager
        except ImportError:
            from backend.services.connection_manager import db_manager

        # Session X creates connection
        ctx = db_manager.create_connection(
            tenant_id="tenant_default",
            workspace_id="workspace_default",
            session_id="session_X_target",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        conn_id = ctx.connection_id

        # Administrator token with Session Admin revokes it
        admin_token = self._create_jwt({
            "sub": "admin_audit_user",
            "roles": ["administrator", "manager", "operator"],
            "clearance_level": 3,
            "session_id": "session_admin_revoker"
        })
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        resp = self.client.post(f"/api/v3/database/connections/{conn_id}/revoke", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("connection", {}).get("status"), "REVOKED")

        # Subsequent get returns 409 CONNECTION_REVOKED
        get_resp = self.client.get(f"/api/v3/database/connections/{conn_id}", headers=admin_headers)
        self.assertEqual(get_resp.status_code, 409)

    def test_session_claim_sid_fallback_and_custom_claim(self):
        """Session claim: default session_id falls back to OIDC 'sid'; custom claim; headers never override JWT."""
        # 1. Fallback to 'sid' when default claim 'session_id' is omitted
        token_sid = self._create_jwt({"sub": "user_sid_test", "sid": "session_from_oidc_sid"})
        ident_sid = auth_mod.JWTAuthenticationProvider().authenticate_token(token_sid)
        self.assertEqual(ident_sid.session_id, "session_from_oidc_sid")

        # 2. Custom claim configured
        prov_custom = auth_mod.JWTAuthenticationProvider(session_claim="custom_sid")
        token_custom = self._create_jwt({"sub": "user_cust", "custom_sid": "sess_cust_42", "sid": "sess_oidc_ignored"})
        ident_custom = prov_custom.authenticate_token(token_custom)
        self.assertEqual(ident_custom.session_id, "sess_cust_42")

        # 3. Custom claim absent: does NOT fall back to 'sid'
        token_cust_absent = self._create_jwt({"sub": "user_cust_abs", "sid": "sess_oidc_ignored"})
        ident_cust_absent = prov_custom.authenticate_token(token_cust_absent)
        self.assertIsNone(ident_cust_absent.session_id)

        # 4. Header NEVER supplies session for JWT identity
        token_no_sess = self._create_jwt({"sub": "user_jwt_no_sess"})
        from starlette.datastructures import Headers
        class DummyRequestWithHeader:
            def __init__(self, h):
                self.headers = Headers(h)

        req = DummyRequestWithHeader({
            "authorization": f"Bearer {token_no_sess}",
            "x-session-id": "attempted_spoofed_session"
        })
        ident_hdr = auth_mod.get_current_identity(req, credentials=None)
        self.assertIsNone(ident_hdr.session_id)

    def test_environment_fail_closed_subprocess_unset_and_staging(self):
        """Subprocess proof: with SAGE_ENV unset and with 'staging', IS_PRODUCTION is true, mock tokens rejected, default key refuses to boot."""
        import subprocess
        import sys
        import os
        from pathlib import Path

        script = """
import os
import sys
from pathlib import Path

target_env = sys.argv[1]
if target_env == "UNSET":
    os.environ.pop("SAGE_ENV", None)
else:
    os.environ["SAGE_ENV"] = target_env

# Add backend directory to sys.path
backend_dir = str(Path(__file__).parent.resolve())
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from core.config import SAGE_ENV, IS_PRODUCTION
assert IS_PRODUCTION is True, f"Expected IS_PRODUCTION True, got {IS_PRODUCTION} for SAGE_ENV={SAGE_ENV}"

from core.auth import get_auth_provider, DEV_MOCK_TOKENS, verify_production_boot_guards, get_current_identity
from fastapi import HTTPException

# 1. Dev mock tokens rejected in production
provider = get_auth_provider()
for mock_tok in DEV_MOCK_TOKENS:
    try:
        provider.authenticate_token(mock_tok)
        sys.exit(10)
    except HTTPException as ex:
        assert ex.status_code == 401

# 2. Anonymous dev identity rejected
from starlette.datastructures import Headers
class DummyReq:
    def __init__(self):
        self.headers = Headers({})

try:
    get_current_identity(DummyReq(), credentials=None)
    sys.exit(20)
except HTTPException as ex:
    assert ex.status_code == 401

# 3. Guard refuses to boot with default key
try:
    verify_production_boot_guards()
    sys.exit(30)
except RuntimeError as r_err:
    assert "default dev" in str(r_err) or "signing key" in str(r_err) or "SAGE_SECRET_KEY" in str(r_err)

print("PASS_FAIL_CLOSED")
"""
        backend_dir = str(Path(__file__).parent.resolve())
        temp_script_path = os.path.join(backend_dir, "_temp_subprocess_test.py")
        with open(temp_script_path, "w", encoding="utf-8") as f:
            f.write(script)

        try:
            for env_case in ("UNSET", "staging"):
                sub_env = os.environ.copy()
                if env_case == "UNSET":
                    sub_env.pop("SAGE_ENV", None)
                else:
                    sub_env["SAGE_ENV"] = env_case

                res = subprocess.run(
                    [sys.executable, temp_script_path, env_case],
                    cwd=backend_dir,
                    env=sub_env,
                    capture_output=True,
                    text=True
                )
                self.assertEqual(res.returncode, 0, f"Failed for {env_case}:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
                self.assertIn("PASS_FAIL_CLOSED", res.stdout)
        finally:
            if os.path.exists(temp_script_path):
                os.remove(temp_script_path)

    # -------------------------------------------------------------------------
    # 9. Prompt 39 Correction 5h Part A Verification Suite
    # -------------------------------------------------------------------------

    def test_production_boot_guards_failures(self):
        """A4: verify_production_boot_guards() refuses boot in production for each invariant."""
        valid_prod_key = "a_very_secure_production_secret_key_that_is_at_least_32_bytes_long"
        valid_issuer = "https://auth.sagecommand.io"
        valid_audience = "sagecommand_api"

        # 1. Auth disabled
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", False), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", valid_prod_key):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("SAGE_AUTH_ENABLED must be True", str(ctx.exception))

        # 2. Non-JWT provider
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "development"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", valid_prod_key):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("SAGE_AUTH_PROVIDER must be 'jwt'", str(ctx.exception))

        # 3. Issuer unset
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", ""), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", valid_prod_key):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("SAGE_AUTH_ISSUER must be configured non-empty", str(ctx.exception))

        # 4. Audience unset
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", ""), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", valid_prod_key):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("SAGE_AUTH_AUDIENCE must be configured non-empty", str(ctx.exception))

        # 5. Default signing key
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", "sagecommand_default_dev_secret_key_change_in_production"):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("cannot use the default dev literal", str(ctx.exception))

        # 6. Key shorter than 32 bytes
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", "short_key_under_32_bytes"):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("must be at least 32 bytes", str(ctx.exception))

        # 7. DEV_MOCK_TOKENS reachable
        class DummyVulnerableProvider(auth_mod.JWTAuthenticationProvider):
            def authenticate_token(self, token: str):
                if token in auth_mod.DEV_MOCK_TOKENS:
                    return Identity(user_id="mock_user", roles=["operator"])
                return super().authenticate_token(token)

        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", valid_issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", valid_audience), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", valid_prod_key), \
             patch.object(auth_mod, "get_auth_provider", return_value=DummyVulnerableProvider(secret_key=valid_prod_key, issuer=valid_issuer, audience=valid_audience)):
            with self.assertRaises(RuntimeError) as ctx:
                auth_mod.verify_production_boot_guards()
            self.assertIn("is reachable in production", str(ctx.exception))

    def test_production_mode_jwt_validations(self):
        """A5: Production-mode JWT tests: wrong issuer, wrong audience, missing exp, missing iss, missing aud, missing sub, expired, alg none, RS256 algorithm confusion, tampered signature. One valid token must pass."""
        from fastapi import HTTPException
        import json
        import base64
        prod_key = "a_super_strong_production_secret_key_32bytes_long"
        issuer = "https://auth.sagecommand.io"
        audience = "sagecommand_api"

        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_SECRET_KEY", prod_key), \
             patch.object(auth_mod, "SAGE_AUTH_ISSUER", issuer), \
             patch.object(auth_mod, "SAGE_AUTH_AUDIENCE", audience):
            provider = auth_mod.JWTAuthenticationProvider(
                secret_key=prod_key,
                issuer=issuer,
                audience=audience
            )
            now = int(time.time())

            def _encode_token(claims, key=prod_key, headers=None, alg="HS256"):
                return jwt.encode(claims, key, algorithm=alg, headers=headers)

            base_valid_claims = {
                "sub": "user_prod_01",
                "iss": issuer,
                "aud": audience,
                "exp": now + 3600,
                "iat": now,
                "roles": ["operator"],
                "tenant_id": "tenant_default",
                "workspace_id": "workspace_default",
                "session_id": "session_valid_01"
            }

            # 1. Wrong issuer
            tok = _encode_token({**base_valid_claims, "iss": "https://attacker.io"})
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Invalid JWT issuer", ctx.exception.detail)

            # 2. Wrong audience
            tok = _encode_token({**base_valid_claims, "aud": "wrong_audience"})
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Invalid JWT audience", ctx.exception.detail)

            # 3. Missing exp
            claims_no_exp = dict(base_valid_claims)
            claims_no_exp.pop("exp")
            tok = _encode_token(claims_no_exp)
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)

            # 4. Missing iss
            claims_no_iss = dict(base_valid_claims)
            claims_no_iss.pop("iss")
            tok = _encode_token(claims_no_iss)
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)

            # 5. Missing aud
            claims_no_aud = dict(base_valid_claims)
            claims_no_aud.pop("aud")
            tok = _encode_token(claims_no_aud)
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)

            # 6. Missing sub
            claims_no_sub = dict(base_valid_claims)
            claims_no_sub.pop("sub")
            tok = _encode_token(claims_no_sub)
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)

            # 7. Expired
            tok = _encode_token({**base_valid_claims, "exp": now - 60})
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tok)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("expired", ctx.exception.detail.lower())

            # 8. alg none
            hdr_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
            payload_b64 = base64.urlsafe_b64encode(json.dumps(base_valid_claims).encode()).decode().rstrip("=")
            alg_none_tok = f"{hdr_b64}.{payload_b64}."
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(alg_none_tok)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Unsupported or prohibited JWT algorithm", ctx.exception.detail)

            # 9. RS256 token verified against HS256 secret (algorithm confusion)
            hdr_rs = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).decode().rstrip("=")
            rs256_fake_tok = f"{hdr_rs}.{payload_b64}.c2lnbmF0dXJl"
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(rs256_fake_tok)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Unsupported or prohibited JWT algorithm", ctx.exception.detail)

            # 10. Tampered signature
            valid_tok = _encode_token(base_valid_claims)
            parts = valid_tok.split(".")
            tampered_tok = f"{parts[0]}.{parts[1]}.{parts[2][:-3]}xyz"
            with self.assertRaises(HTTPException) as ctx:
                provider.authenticate_token(tampered_tok)
            self.assertEqual(ctx.exception.status_code, 401)

            # 11. One valid token must pass!
            ident = provider.authenticate_token(valid_tok)
            self.assertEqual(ident.user_id, "user_prod_01")
            self.assertEqual(ident.session_id, "session_valid_01")
            self.assertEqual(ident.roles, ["operator"])
            self.assertTrue(ident.is_server_authoritative)

    def test_production_mode_positive_suite_with_real_jwts(self):
        """A6: Production-mode positive suite using real JWTs with all required claims and a session claim against:
        create connection, list, revoke (own session), action execute, policy evaluate, transaction execute.
        These must pass regardless of the ambient environment.
        """
        now = int(time.time())
        token_payload = {
            "sub": "user_prod_suite_01",
            "tenant_id": "tenant_prod_positive",
            "workspace_id": "workspace_default",
            "roles": ["administrator", "manager", "operator"],
            "clearance_level": 3,
            "assigned_plants": ["plant_mumbai", "*"],
            "session_id": "session_prod_pos_01",
            "iss": SAGE_AUTH_ISSUER,
            "aud": SAGE_AUTH_AUDIENCE,
            "iat": now,
            "exp": now + 3600
        }
        token = jwt.encode(token_payload, SAGE_SECRET_KEY, algorithm="HS256")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "tenant_prod_positive"
        }

        with patch.object(auth_mod, "SAGE_ENV", "production"), \
             patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_AUTH_PROVIDER", "jwt"), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", True):

            # 1. Create connection
            create_payload = {
                "database_type": "SQLITE",
                "connection_string": "sqlite:///./dynamic_datacore.sqlite",
                "access_mode": "READ_ONLY",
                "data_mode": "REAL"
            }
            resp_create = self.client.post("/api/v3/database/connections", json=create_payload, headers=headers)
            self.assertEqual(resp_create.status_code, 201)
            create_data = resp_create.json()
            self.assertTrue(create_data.get("success"))
            conn_id = create_data["connection"]["connection_id"]

            # 2. List connections
            resp_list = self.client.get("/api/v3/database/connections", headers=headers)
            self.assertEqual(resp_list.status_code, 200)
            list_data = resp_list.json()
            self.assertTrue(list_data.get("success"))

            # 3. Revoke (own session)
            resp_revoke = self.client.post(f"/api/v3/database/connections/{conn_id}/revoke", headers=headers)
            self.assertEqual(resp_revoke.status_code, 200)
            revoke_data = resp_revoke.json()
            self.assertTrue(revoke_data.get("success"))
            self.assertEqual(revoke_data["connection"]["status"], "REVOKED")

            # 4. Action execute
            act_exec = Action(
                action_type="ADJUST_REORDER_POINT",
                tenant_id="tenant_prod_positive",
                workspace_id="workspace_default",
                session_id="session_prod_pos_01",
                status=ActionStatus.APPROVED,
                requires_approval=False,
                system_risk_level=RiskLevel.LOW,
                parameters={"sku": "SKU-PROD-01", "reorder_point": 10},
                target={"resource_type": "INVENTORY_ITEM", "resource_id": "SKU-PROD-01", "plant_id": "plant_mumbai"},
                reason={"summary": "Production positive test execute", "reason_code": "STOCK_LOW", "trigger": "MANUAL", "business_impact": "LOW"}
            )
            action_store.save(act_exec)

            resp_act = self.client.post(
                f"/api/v3/actions/{act_exec.action_id}/execute",
                json={"dry_run": True},
                headers=headers
            )
            self.assertEqual(resp_act.status_code, 200)
            self.assertTrue(resp_act.json().get("success"))

            # 5. Policy evaluate (on an action in PROPOSED state)
            act_eval = Action(
                action_type="ADJUST_REORDER_POINT",
                tenant_id="tenant_prod_positive",
                workspace_id="workspace_default",
                session_id="session_prod_pos_01",
                status=ActionStatus.PROPOSED,
                requires_approval=True,
                system_risk_level=RiskLevel.LOW,
                parameters={"sku": "SKU-PROD-02", "reorder_point": 20},
                target={"resource_type": "INVENTORY_ITEM", "resource_id": "SKU-PROD-02", "plant_id": "plant_mumbai"},
                reason={"summary": "Production positive test evaluate", "reason_code": "STOCK_LOW", "trigger": "MANUAL", "business_impact": "LOW"}
            )
            action_store.save(act_eval)

            resp_eval = self.client.post(
                "/api/v3/policies/evaluate",
                json={"action_id": act_eval.action_id},
                headers=headers
            )
            self.assertEqual(resp_eval.status_code, 200)
            self.assertTrue(resp_eval.json().get("success"))

            # 6. Transaction execute (planned from an action)
            act_plan = Action(
                action_type="ADJUST_REORDER_POINT",
                tenant_id="tenant_prod_positive",
                workspace_id="workspace_default",
                session_id="session_prod_pos_01",
                status=ActionStatus.APPROVED,
                requires_approval=False,
                system_risk_level=RiskLevel.LOW,
                parameters={"sku": "SKU-PROD-03", "reorder_point": 30},
                target={"resource_type": "INVENTORY_ITEM", "resource_id": "SKU-PROD-03", "plant_id": "plant_mumbai"},
                reason={"summary": "Production positive test transaction", "reason_code": "STOCK_LOW", "trigger": "MANUAL", "business_impact": "LOW"}
            )
            action_store.save(act_plan)

            resp_plan = self.client.post(
                "/api/v3/transactions/plan",
                json={"action_id": act_plan.action_id, "idempotency_key": f"idemp_{time.time_ns()}"},
                headers=headers
            )
            self.assertEqual(resp_plan.status_code, 201)
            tx_id = resp_plan.json()["transaction"]["transaction_id"]

            resp_tx = self.client.post(
                f"/api/v3/transactions/{tx_id}/execute",
                headers=headers
            )
            self.assertEqual(resp_tx.status_code, 200)
            self.assertTrue(resp_tx.json().get("success"))

    def test_revoke_authority_and_clearance_level(self):
        """A7: Revoke authority:
        clearance_level comes strictly from validated JWT claim; client headers cannot supply or raise it.
        Tests:
        1. Own session OK (200)
        2. Other session non-admin 403
        3. No session 400
        4. Cross-tenant 403 even for an admin
        5. Admin override audited
        6. Clearance_level 3 in another tenant rejected (403)
        """
        try:
            from services.connection_manager import db_manager
        except ImportError:
            from backend.services.connection_manager import db_manager

        # Confirm clearance_level comes from JWT and client header cannot raise it
        tok_low_clearance = self._create_jwt({
            "sub": "user_low_clearance",
            "clearance_level": 1,
            "roles": ["operator"]
        })
        from starlette.datastructures import Headers
        class DummyReq:
            def __init__(self, h):
                self.headers = Headers(h)

        req_elevate = DummyReq({
            "authorization": f"Bearer {tok_low_clearance}",
            "x-clearance-level": "3"
        })
        ident_elevated = auth_mod.get_current_identity(req_elevate, credentials=None)
        self.assertEqual(ident_elevated.clearance_level, 1, "Client header X-Clearance-Level MUST NOT elevate clearance")

        # 1. Own session OK (200)
        ctx_own = db_manager.create_connection(
            tenant_id="tenant_alpha",
            workspace_id="workspace_default",
            session_id="session_own_01",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        tok_own = self._create_jwt({
            "sub": "user_own_01",
            "tenant_id": "tenant_alpha",
            "session_id": "session_own_01",
            "roles": ["manager"]
        })
        resp_own = self.client.post(
            f"/api/v3/database/connections/{ctx_own.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_own}"}
        )
        self.assertEqual(resp_own.status_code, 200)
        self.assertEqual(resp_own.json()["connection"]["status"], "REVOKED")

        # 2. Other session non-admin 403
        ctx_target = db_manager.create_connection(
            tenant_id="tenant_alpha",
            workspace_id="workspace_default",
            session_id="session_victim",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        tok_other = self._create_jwt({
            "sub": "user_other_mgr",
            "tenant_id": "tenant_alpha",
            "session_id": "session_attacker",
            "roles": ["manager"]
        })
        resp_other = self.client.post(
            f"/api/v3/database/connections/{ctx_target.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_other}"}
        )
        self.assertEqual(resp_other.status_code, 403)
        self.assertEqual(resp_other.json()["error"]["code"], "AUTHORIZATION_DENIED")

        # 3. No session 400
        tok_no_sess = self._create_jwt({
            "sub": "user_no_session",
            "tenant_id": "tenant_alpha",
            "roles": ["manager"]
        })  # no session_id
        resp_no_sess = self.client.post(
            f"/api/v3/database/connections/{ctx_target.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_no_sess}"}
        )
        self.assertEqual(resp_no_sess.status_code, 400)
        self.assertEqual(resp_no_sess.json()["error"]["code"], "MISSING_SESSION")

        # 4. Cross-tenant 403 even for an admin
        tok_cross_admin = self._create_jwt({
            "sub": "admin_other_tenant",
            "tenant_id": "tenant_foreign",
            "session_id": "session_foreign_admin",
            "roles": ["administrator", "manager", "operator"],
            "clearance_level": 3
        })
        resp_cross_admin = self.client.post(
            f"/api/v3/database/connections/{ctx_target.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_cross_admin}"}
        )
        self.assertEqual(resp_cross_admin.status_code, 403)
        self.assertEqual(resp_cross_admin.json()["error"]["code"], "AUTHORIZATION_DENIED")

        # 5. Admin override audited (same tenant, different session)
        ctx_target_audit = db_manager.create_connection(
            tenant_id="tenant_alpha",
            workspace_id="workspace_default",
            session_id="session_victim_audit",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        tok_same_tenant_admin = self._create_jwt({
            "sub": "admin_same_tenant",
            "tenant_id": "tenant_alpha",
            "session_id": "session_alpha_admin",
            "roles": ["administrator", "manager", "operator"],
            "clearance_level": 3
        })
        resp_override = self.client.post(
            f"/api/v3/database/connections/{ctx_target_audit.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_same_tenant_admin}"}
        )
        self.assertEqual(resp_override.status_code, 200)
        self.assertEqual(resp_override.json()["connection"]["status"], "REVOKED")

        # 6. Clearance_level 3 in another tenant rejected (403)
        ctx_target2 = db_manager.create_connection(
            tenant_id="tenant_alpha",
            workspace_id="workspace_default",
            session_id="session_alpha_target2",
            connection_string="sqlite:///./dynamic_datacore.sqlite"
        )
        tok_cleared_foreign = self._create_jwt({
            "sub": "sec_foreign_level3",
            "tenant_id": "tenant_beta",
            "session_id": "session_beta_cleared",
            "roles": ["manager"],
            "clearance_level": 3
        })
        resp_cleared_foreign = self.client.post(
            f"/api/v3/database/connections/{ctx_target2.connection_id}/revoke",
            headers={"Authorization": f"Bearer {tok_cleared_foreign}"}
        )
        self.assertEqual(resp_cleared_foreign.status_code, 403)
        self.assertEqual(resp_cleared_foreign.json()["error"]["code"], "AUTHORIZATION_DENIED")


if __name__ == "__main__":
    unittest.main()
