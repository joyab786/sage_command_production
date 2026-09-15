# backend/test_websocket_endpoints.py
"""
FastAPI Server & WebSocket Integration Test Suite
Tests FastAPI endpoints and live WebSocket communications using TestClient:
1. POST /trigger-anomaly
2. POST /upload-db (CSV uplink and SQL compilation)
3. POST /connect-live-db (Hot-swap tether)
4. WS /ws/sage (Duplex WebSocket commands: chat, telemetry, RBAC approval, state history)
"""

import unittest
import io
from fastapi.testclient import TestClient
from server import app

class TestServerEndpoints(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    # --- 1. POST /trigger-anomaly ---
    def test_endpoint_trigger_anomaly(self):
        """Test manually triggering an event-driven telemetry anomaly."""
        response = self.client.post("/trigger-anomaly")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("anomaly", data)

    # --- 2. POST /upload-db ---
    def test_endpoint_upload_csv(self):
        """Test uploading a CSV file to compile into SQL table and hot-swap cortex."""
        csv_content = "sensor_id,reading,location\nS-1,104.2,Sector 7G\nS-2,98.6,Sector 4B\n"
        file_tuple = ("telemetry.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
        
        response = self.client.post("/upload-db", files={"file": file_tuple})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("mounted successfully", data.get("message", ""))

    # --- 3. POST /connect-live-db ---
    def test_endpoint_connect_live_db(self):
        """Test live database URI tether and schema inspection."""
        payload = {"connection_string": "sqlite:///./dynamic_datacore.sqlite"}
        response = self.client.post("/connect-live-db", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("tables", data)

    # --- 4. WEBSOCKET /ws/sage COMMUNICATOR ---
    def test_websocket_chat_and_history(self):
        """Test duplex WebSocket protocol for chat commands and checkpoint history."""
        with self.client.websocket_connect("/ws/sage") as websocket:
            # Test chat command
            websocket.send_json({"command": "chat", "text": "List usable tables."})
            
            # Receive initial node_update / node_active telemetry
            rec1 = websocket.receive_json()
            self.assertIn(rec1.get("type"), ["node_update", "node_active", "chat_response", "log"])
            
            # Test get_history command
            websocket.send_json({"command": "get_history"})
            rec_hist = None
            for _ in range(5):
                msg = websocket.receive_json()
                if msg.get("type") == "checkpoint_history":
                    rec_hist = msg
                    break
            self.assertIsNotNone(rec_hist, "Should receive checkpoint_history payload over WebSocket")
            self.assertIn("history", rec_hist)

    def test_websocket_rbac_approval(self):
        """Test WebSocket RBAC enforcement when Operator attempts approval."""
        with self.client.websocket_connect("/ws/sage") as websocket:
            # Send approve command with Operator role
            websocket.send_json({"command": "approve", "user_role": "operator"})
            
            # Read unauthorized response and security warning log
            msg1 = websocket.receive_json()
            msg2 = websocket.receive_json()
            
            self.assertEqual(msg1.get("type"), "unauthorized")
            self.assertEqual(msg1.get("required_role"), "manager")
            self.assertEqual(msg2.get("type"), "log")
            self.assertIn("SECURITY WARNING", msg2.get("message", ""))

if __name__ == "__main__":
    unittest.main(verbosity=2)
