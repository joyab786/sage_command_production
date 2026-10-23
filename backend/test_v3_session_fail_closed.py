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
        with patch.object(auth_mod, "IS_PRODUCTION", False), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", False):
            identity1 = auth_mod.get_current_identity(req1, credentials=None)
            self.assertIsNone(identity1.session_id)

        # Environment 2: Development/Test mode with mock token that has no session in its profile
        req2 = DummyRequest({"authorization": "Bearer manager_token"})
        with patch.object(auth_mod, "IS_PRODUCTION", False):
            identity2 = auth_mod.get_current_identity(req2, credentials=None)
            self.assertIsNone(identity2.session_id)

        # Environment 3: Production mode with JWT token that has no session_id claim
        jwt_no_sess = self._create_jwt({"sub": "prod_tester_01"})
        req3 = DummyRequest({"authorization": f"Bearer {jwt_no_sess}"})
        with patch.object(auth_mod, "IS_PRODUCTION", True):
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
        """Database routes with missing session fail gracefully (404/403/200) and NEVER return 500."""
        token = self._create_jwt({"sub": "jwt_db_user"})  # no session_id
        headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/v3/database/connections/{id}
        resp1 = self.client.get("/api/v3/database/connections/conn_nonexistent", headers=headers)
        self.assertIn(resp1.status_code, (401, 403, 404))
        self.assertNotEqual(resp1.status_code, 500)

        # 2. POST /api/v3/database/connections/{id}/sample
        resp2 = self.client.post(
            "/api/v3/database/connections/conn_nonexistent/sample",
            json={"table": "sensor_telemetry", "limit": 5},
            headers=headers
        )
        self.assertIn(resp2.status_code, (401, 403, 404))
        self.assertNotEqual(resp2.status_code, 500)

        # 3. POST /api/v3/database/connections/{id}/revoke
        resp3 = self.client.post(
            "/api/v3/database/connections/conn_nonexistent/revoke",
            json={"reason": "Security audit"},
            headers=headers
        )
        self.assertIn(resp3.status_code, (200, 401, 403, 404))
        self.assertNotEqual(resp3.status_code, 500)

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


if __name__ == "__main__":
    unittest.main()
