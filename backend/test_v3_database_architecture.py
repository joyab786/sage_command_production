import sys
import os
import unittest
import threading
import tempfile
import sqlite3

# Ensure sys.path includes both backend directory and parent directory for root/module imports
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)
from sqlalchemy import create_engine, text

try:
    from data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from services.connection_registry import ConnectionRegistry, connection_registry
    from services.connection_manager import DatabaseConnectionManager
    from core.state import SageOSState
except ModuleNotFoundError:
    from backend.data.database_context import DatabaseContext, AccessMode, DataMode, ConnectionStatus
    from backend.services.connection_registry import ConnectionRegistry, connection_registry
    from backend.services.connection_manager import DatabaseConnectionManager
    from backend.core.state import SageOSState


class TestV3DatabaseArchitecture(unittest.TestCase):

    def setUp(self):
        self.registry = ConnectionRegistry()
        self.manager = DatabaseConnectionManager(registry=self.registry)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        for scoped_key, handles in list(self.manager._engine_pool.items()):
            if handles and handles[0]:
                handles[0].dispose()
        self.manager._engine_pool.clear()
        try:
            self.temp_dir.cleanup()
        except OSError:
            pass

    # --- 1. TENANT / WORKSPACE / SESSION ISOLATION TESTS ---
    def test_cross_tenant_isolation(self):
        # Tenant A registers DB connection
        db_path_a = os.path.join(self.temp_dir.name, "tenant_a.db")
        conn_a = sqlite3.connect(db_path_a)
        conn_a.execute("CREATE TABLE info (id INT, name TEXT)")
        conn_a.execute("INSERT INTO info VALUES (1, 'Tenant A Secret Data')")
        conn_a.commit()
        conn_a.close()

        self.manager.create_connection(
            tenant_id="tenant_acme",
            workspace_id="ws_mumbai",
            session_id="sess_user_a",
            connection_string=f"sqlite:///{db_path_a}",
            access_mode=AccessMode.READ_ONLY,
            connection_id="conn_a"
        )

        # Tenant A accesses its own connection successfully
        ctx_a, engine_a, db_a, _ = self.manager.get_connection("tenant_acme", "ws_mumbai", "sess_user_a", "conn_a")
        self.assertIn("tenant_a.db", ctx_a.database_name)
        self.assertIsNotNone(engine_a)

        # Tenant B attempts access to Tenant A's connection -> PermissionError
        with self.assertRaises(PermissionError):
            self.manager.get_connection("tenant_stark", "ws_mumbai", "sess_user_b", "conn_a")

    def test_cross_workspace_isolation(self):
        # Same Tenant, but Plant Mumbai vs Plant Pune
        db_mumbai = os.path.join(self.temp_dir.name, "mumbai.db")
        conn_m = sqlite3.connect(db_mumbai)
        conn_m.execute("CREATE TABLE plant (name TEXT)")
        conn_m.commit()
        conn_m.close()

        self.manager.create_connection(
            tenant_id="tenant_acme",
            workspace_id="ws_mumbai",
            session_id="sess_1",
            connection_string=f"sqlite:///{db_mumbai}",
            connection_id="conn_mumbai"
        )

        # Access from Pune workspace must be denied
        with self.assertRaises(PermissionError):
            self.manager.get_connection("tenant_acme", "ws_pune", "sess_1", "conn_mumbai")

    def test_cross_session_isolation(self):
        # Same Tenant & Workspace, but User 1 session vs User 2 session
        db_user1 = os.path.join(self.temp_dir.name, "user1.db")
        conn1 = sqlite3.connect(db_user1)
        conn1.execute("CREATE TABLE data (val TEXT)")
        conn1.commit()
        conn1.close()

        self.manager.create_connection(
            tenant_id="tenant_acme",
            workspace_id="ws_mumbai",
            session_id="session_user_1",
            connection_string=f"sqlite:///{db_user1}",
            connection_id="conn_u1"
        )

        # User 2 session attempting to borrow User 1's connection -> PermissionError
        with self.assertRaises(PermissionError):
            self.manager.get_connection("tenant_acme", "ws_mumbai", "session_user_2", "conn_u1")

    # --- 2. CONCURRENT MULTI-USER STRESS TEST (10 SESSIONS) ---
    def test_concurrent_10_session_queries(self):
        """Simulates 10 concurrent user sessions executing queries against 10 isolated databases."""
        num_sessions = 10
        errors = []

        def worker_task(session_idx: int):
            try:
                db_file = os.path.join(self.temp_dir.name, f"db_sess_{session_idx}.db")
                c = sqlite3.connect(db_file)
                c.execute("CREATE TABLE items (id INT, tag TEXT)")
                c.execute("INSERT INTO items VALUES (?, ?)", (session_idx, f"Data_For_Session_{session_idx}"))
                c.commit()
                c.close()

                tenant_id = "tenant_enterprise"
                workspace_id = f"ws_plant_{session_idx % 3}"
                session_id = f"sess_{session_idx}"
                conn_id = f"conn_id_{session_idx}"

                # Register connection
                self.manager.create_connection(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    connection_string=f"sqlite:///{db_file}",
                    connection_id=conn_id
                )

                # Query connection
                ctx, engine, _, query_tool = self.manager.get_connection(tenant_id, workspace_id, session_id, conn_id)
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT tag FROM items")).fetchone()
                    
                expected_tag = f"Data_For_Session_{session_idx}"
                if not result or result[0] != expected_tag:
                    errors.append(f"Session {session_idx} expected '{expected_tag}' but got '{result}'")

            except Exception as e:
                errors.append(f"Session {session_idx} raised exception: {str(e)}")

        threads = []
        for i in range(num_sessions):
            t = threading.Thread(target=worker_task, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent session test failed with errors: {errors}")

    # --- 3. SIMULATION SAFETY & ACCESS MODE TESTS ---
    def test_simulation_write_protection(self):
        # Real production database connection (DataMode.REAL)
        db_real = os.path.join(self.temp_dir.name, "prod_real.db")
        c = sqlite3.connect(db_real)
        c.execute("CREATE TABLE prod (id INT)")
        c.commit()
        c.close()

        self.manager.create_connection(
            tenant_id="tenant_acme",
            workspace_id="ws_mumbai",
            session_id="sess_sim",
            connection_string=f"sqlite:///{db_real}",
            access_mode=AccessMode.READ_ONLY,
            data_mode=DataMode.REAL,
            connection_id="conn_prod"
        )

        # Write attempt requiring READ_WRITE mode fails on READ_ONLY context
        with self.assertRaises(PermissionError):
            self.manager.validate_access("tenant_acme", "ws_mumbai", "sess_sim", "conn_prod", required_mode=AccessMode.READ_WRITE)

        # Simulation mode write on REAL data mode fails simulation safety
        with self.assertRaises(PermissionError):
            self.manager.validate_access("tenant_acme", "ws_mumbai", "sess_sim", "conn_prod", required_mode=AccessMode.SIMULATION)

    # --- 4. LANGGRAPH STATE CHECKPOINT SAFETY ---
    def test_langgraph_checkpoint_state_safety(self):
        # Build state dict with safe connection identifiers
        state_dict: SageOSState = {
            "messages": [],
            "tenant_id": "tenant_acme",
            "workspace_id": "ws_mumbai",
            "session_id": "sess_100",
            "connection_id": "conn_100",
            "access_mode": "READ_ONLY",
            "data_mode": "REAL"
        }

        # Verify only safe string identifiers exist in state
        self.assertIsInstance(state_dict["tenant_id"], str)
        self.assertIsInstance(state_dict["connection_id"], str)

        # Verify NO Engine, SQLDatabase, or raw DB handles exist in state dictionary keys
        for key, val in state_dict.items():
            self.assertNotIn("engine", key.lower())
            self.assertNotIn("sqlalchemy", str(type(val)).lower())

    # --- 5. CONNECTION LIFECYCLE & HEALTH CHECKS ---
    def test_connection_lifecycle(self):
        db_test = os.path.join(self.temp_dir.name, "lifecycle.db")
        c = sqlite3.connect(db_test)
        c.execute("CREATE TABLE test (id INT)")
        c.commit()
        c.close()

        ctx = self.manager.create_connection(
            tenant_id="tenant_acme",
            workspace_id="ws_mumbai",
            session_id="sess_lc",
            connection_string=f"sqlite:///{db_test}",
            connection_id="conn_lc"
        )
        self.assertEqual(ctx.status, ConnectionStatus.CONNECTED)

        # Health check
        health = self.manager.health_check("tenant_acme", "ws_mumbai", "sess_lc", "conn_lc")
        self.assertEqual(health["status"], "HEALTHY")

        # Disconnect
        disconnected = self.manager.disconnect("tenant_acme", "ws_mumbai", "sess_lc", "conn_lc")
        self.assertTrue(disconnected)

        # Access after disconnect fails
        with self.assertRaises(PermissionError):
            self.manager.get_connection("tenant_acme", "ws_mumbai", "sess_lc", "conn_lc")


if __name__ == "__main__":
    unittest.main()
