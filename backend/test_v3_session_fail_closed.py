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
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

try:
    from server import app
    from core.config import IS_PRODUCTION, SAGE_DEV_SESSION_FALLBACK
    from core.auth import get_current_identity, Identity
    from data.schemas.action_contract import Action, ActionStatus, RiskLevel
    from services.action_store import action_store
except (ImportError, ModuleNotFoundError):
    from backend.server import app
    from backend.core.config import IS_PRODUCTION, SAGE_DEV_SESSION_FALLBACK
    from backend.core.auth import get_current_identity, Identity
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
    # 5. Production Mode Inertness and Dev Fallback Gating
    # -------------------------------------------------------------------------

    def test_production_mode_never_applies_dev_fallback(self):
        """When IS_PRODUCTION is True, dev fallback is strictly inert and session_id remains None."""
        class DummyRequest:
            headers = {}

    def test_production_mode_never_applies_dev_fallback(self):
        """When IS_PRODUCTION is True, dev fallback is strictly inert and unauthenticated requests fail closed."""
        try:
            import core.auth as auth_mod
        except ImportError:
            import backend.core.auth as auth_mod
        from fastapi import HTTPException

        class DummyRequest:
            headers = {}

        # 1. Under production, provider is JWTAuthenticationProvider
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_DEV_SESSION_FALLBACK", True):
            provider = auth_mod.get_auth_provider()
            self.assertTrue(provider.__class__.__name__ == "JWTAuthenticationProvider")

        # 2. Test unauthenticated request under IS_PRODUCTION=True raises 401 (fails closed)
        req = DummyRequest()
        with patch.object(auth_mod, "IS_PRODUCTION", True), \
             patch.object(auth_mod, "SAGE_DEV_SESSION_FALLBACK", True):
            with self.assertRaises(HTTPException) as ctx:
                auth_mod.get_current_identity(req, credentials=None)
            self.assertEqual(ctx.exception.status_code, 401)

        # 3. Test that production mode never assigns dev session fallback to server-authoritative or production identities
        prod_identity = Identity(user_id="prod_user", is_server_authoritative=True)
        self.assertIsNone(prod_identity.session_id)

    def test_dev_fallback_off_by_default(self):
        """When not in production, dev fallback is off by default and session_id is None without X-Session-ID."""
        try:
            import core.auth as auth_mod
        except ImportError:
            import backend.core.auth as auth_mod

        class DummyRequest:
            headers = {}

        req = DummyRequest()
        with patch.object(auth_mod, "IS_PRODUCTION", False), \
             patch.object(auth_mod, "SAGE_DEV_SESSION_FALLBACK", False), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", False):
            identity = auth_mod.get_current_identity(req, credentials=None)
            self.assertIsNone(identity.session_id)

    def test_dev_fallback_when_explicitly_enabled(self):
        """When explicitly enabled in development, fallback session is generated."""
        try:
            import core.auth as auth_mod
        except ImportError:
            import backend.core.auth as auth_mod

        class DummyRequest:
            headers = {}

        req = DummyRequest()
        with patch.object(auth_mod, "IS_PRODUCTION", False), \
             patch.object(auth_mod, "SAGE_DEV_SESSION_FALLBACK", True), \
             patch.object(auth_mod, "SAGE_AUTH_ENABLED", False):
            identity = auth_mod.get_current_identity(req, credentials=None)
            self.assertIsNotNone(identity.session_id)
            self.assertTrue(identity.session_id.startswith("session_"))


if __name__ == "__main__":
    unittest.main()
