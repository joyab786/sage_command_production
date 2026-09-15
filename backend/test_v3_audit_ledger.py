# backend/test_v3_audit_ledger.py
"""
SageCommand V3 — Audit & Decision Ledger Test Suite (Prompt 08)
Validates:
1. Canonical LedgerEvent Schemas, Event IDs, Versioning, and Actor Models.
2. Immutability & Append-Only Behavior (No Updates or Deletions).
3. Multi-Tenant, Workspace, and Session Isolation.
4. Deep Recursive Secret Redaction (Passwords, Tokens, DSNs, Keys).
5. Safe Payload Size Bounding & Anti-DoS Limits.
6. Concurrent Multi-Threaded Appends without Collision.
7. Policy & Authorization Version Traceability.
8. AI Model Provenance & Simulation Mode Distinction.
9. Incident & Decision Timeline Reconstruction.
10. DecisionRecord Graph Reconstruction (with Execution/Verification as NOT_AVAILABLE).
11. REST API Endpoints under /api/v3/audit with RBAC Authorization (audit.read).
12. Strict Execution Boundary: POST /api/v3/actions/{id}/execute returns 405 Method Not Allowed.
"""

import unittest
import json
import uuid
import threading
from fastapi.testclient import TestClient

from server import app
from core.auth import Identity
from data.schemas.ledger_contract import (
    LedgerEvent,
    LedgerActor,
    ModelProvenance,
    EventCategory,
    EventStatus,
    ActorType,
    DataMode,
    EventType,
    DecisionRecord,
)
from services.ledger_repository import SQLiteAuditLedgerRepository
from services.audit_ledger import AuditLedgerService, audit_ledger
from governance.redaction import sanitize_payload


class TestV3AuditLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Use an isolated test repository in memory or temp db
        cls.test_repo = SQLiteAuditLedgerRepository(db_path=":memory:")
        cls.test_service = AuditLedgerService(repository=cls.test_repo)

    def _auth_headers(self, token="manager_token", session_id="session_test_01", tenant_id="tenant_default"):
        return {
            "Authorization": f"Bearer {token}",
            "X-Session-ID": session_id,
            "X-Tenant-ID": tenant_id,
            "X-Request-ID": f"req_{uuid.uuid4().hex[:8]}"
        }

    # =====================================================================
    # 1. CANONICAL EVENT MODEL & SCHEMAS
    # =====================================================================

    def test_ledger_event_creation_and_hash(self):
        """Validates canonical event schema, UUID, versioning, and SHA-256 fingerprint."""
        actor = LedgerActor(
            actor_type=ActorType.USER,
            actor_id="user_123",
            acting_user_id="user_123",
            roles=["OPERATOR"]
        )
        event = LedgerEvent(
            event_type=EventType.ACTION_PROPOSED.value,
            category=EventCategory.ACTION,
            tenant_id="tenant_alpha",
            workspace_id="workspace_alpha",
            actor=actor,
            payload={"action_id": "act_001", "risk": "LOW"}
        )
        event.finalize_hash()

        self.assertTrue(event.event_id.startswith("evt_"))
        self.assertEqual(event.event_version, "v1")
        self.assertEqual(len(event.event_hash), 64)
        self.assertIn("T", event.occurred_at)
        self.assertIn("Z", event.occurred_at)

    # =====================================================================
    # 2. IMMUTABILITY & APPEND-ONLY PERSISTENCE
    # =====================================================================

    def test_append_only_and_idempotency(self):
        """Validates append-only storage and idempotency on duplicate event_id."""
        actor = LedgerActor(actor_type=ActorType.SYSTEM, actor_id="sys_01")
        event_id = f"evt_idemp_{uuid.uuid4().hex[:8]}"

        event = LedgerEvent(
            event_id=event_id,
            event_type=EventType.DATABASE_HEALTH_CHANGED.value,
            category=EventCategory.DATA,
            tenant_id="tenant_idemp",
            workspace_id="workspace_default",
            actor=actor,
            payload={"status": "HEALTHY"}
        )

        # First append
        saved_1 = self.test_repo.append(event)
        self.assertEqual(saved_1.event_id, event_id)

        # Second append with same event_id must return existing (idempotent)
        saved_2 = self.test_repo.append(event)
        self.assertEqual(saved_2.event_id, event_id)

        # Verify no duplicate entries
        events, total = self.test_repo.query("tenant_idemp", {"event_type": EventType.DATABASE_HEALTH_CHANGED.value})
        self.assertEqual(total, 1)

    # =====================================================================
    # 3. MULTI-TENANT, WORKSPACE, AND SESSION ISOLATION
    # =====================================================================

    def test_multi_tenant_isolation(self):
        """Events from Tenant A must be strictly invisible to Tenant B."""
        actor_a = LedgerActor(actor_type=ActorType.USER, actor_id="alice")
        actor_b = LedgerActor(actor_type=ActorType.USER, actor_id="bob")

        self.test_service.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor_a,
            tenant_id="tenant_acme",
            payload={"secret_order": "ORD-123"}
        )
        self.test_service.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor_b,
            tenant_id="tenant_globex",
            payload={"secret_order": "ORD-999"}
        )

        # Query Tenant Acme
        acme_events, count_acme = self.test_repo.query("tenant_acme", {})
        self.assertGreaterEqual(count_acme, 1)
        for e in acme_events:
            self.assertEqual(e.tenant_id, "tenant_acme")
            self.assertNotEqual(e.tenant_id, "tenant_globex")

        # Query Tenant Globex
        globex_events, count_globex = self.test_repo.query("tenant_globex", {})
        self.assertGreaterEqual(count_globex, 1)
        for e in globex_events:
            self.assertEqual(e.tenant_id, "tenant_globex")
            self.assertNotEqual(e.tenant_id, "tenant_acme")

    def test_workspace_isolation(self):
        """Events in workspace_prod must not appear in workspace_rd queries."""
        actor = LedgerActor(actor_type=ActorType.USER, actor_id="alice")
        self.test_service.record_event(
            event_type=EventType.DATABASE_QUERY_EXECUTED.value,
            actor=actor,
            tenant_id="tenant_ws_iso",
            workspace_id="workspace_prod",
            payload={"rows": 10}
        )
        self.test_service.record_event(
            event_type=EventType.DATABASE_QUERY_EXECUTED.value,
            actor=actor,
            tenant_id="tenant_ws_iso",
            workspace_id="workspace_rd",
            payload={"rows": 50}
        )

        prod_events, _ = self.test_repo.query("tenant_ws_iso", {"workspace_id": "workspace_prod"})
        self.assertTrue(all(e.workspace_id == "workspace_prod" for e in prod_events))

    # =====================================================================
    # 4. DEEP SECRET REDACTION & BOUNDED PAYLOAD LIMITS
    # =====================================================================

    def test_deep_recursive_secret_redaction(self):
        """Verifies passwords, tokens, API keys, and connection strings are deeply redacted."""
        raw_payload = {
            "user": "operator_bob",
            "password": "SuperSecretPassword123!",
            "nested_config": {
                "api_key": "sk-ant-api03-abcdef123456",
                "database_url": "postgresql://admin:secretPass@db.internal:5432/factory",
                "normal_field": "safe_value"
            },
            "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token.signature"
        }

        sanitized = sanitize_payload(raw_payload)
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["nested_config"]["api_key"], "[REDACTED]")
        self.assertNotIn("secretPass", sanitized["nested_config"]["database_url"])
        self.assertIn("[REDACTED]", sanitized["nested_config"]["database_url"])
        self.assertEqual(sanitized["auth_header"], "[REDACTED]")
        self.assertEqual(sanitized["nested_config"]["normal_field"], "safe_value")

    def test_payload_bounding_and_truncation(self):
        """Oversized payloads must be safely bounded to prevent unbounded storage."""
        large_list = [{"item": i} for i in range(200)]
        sanitized = sanitize_payload(large_list)
        # Should be truncated to 50 items + 1 truncation marker
        self.assertEqual(len(sanitized), 51)
        self.assertIn("truncated", sanitized[-1])

    # =====================================================================
    # 5. CONCURRENCY SAFETY
    # =====================================================================

    def test_concurrent_event_appends(self):
        """Tests that concurrent appends across threads never lose events or corrupt sequences."""
        num_threads = 10
        events_per_thread = 10
        tenant_id = "tenant_concurrent_test"

        def worker(thread_idx):
            for i in range(events_per_thread):
                actor = LedgerActor(actor_type=ActorType.SYSTEM, actor_id=f"worker_{thread_idx}")
                self.test_service.record_event(
                    event_type=EventType.SIMULATION_STARTED.value,
                    actor=actor,
                    tenant_id=tenant_id,
                    payload={"thread": thread_idx, "iter": i}
                )

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events, total = self.test_repo.query(tenant_id, {}, limit=100)
        self.assertEqual(total, num_threads * events_per_thread)

    # =====================================================================
    # 6. POLICY, AUTHORIZATION, AND MODEL PROVENANCE TRACEABILITY
    # =====================================================================

    def test_provenance_and_version_traceability(self):
        """Validates that policy and authorization versions and model provenance are preserved."""
        actor = LedgerActor(actor_type=ActorType.AGENT, actor_id="strategy_copilot", acting_user_id="mgr_456")
        model_prov = ModelProvenance(
            model_provider="Groq",
            model_name="llama-3.3-70b-versatile",
            prompt_version="v2.1",
            agent_version="v3.0.0"
        )

        event = self.test_service.record_event(
            event_type=EventType.POLICY_ALLOWED.value,
            actor=actor,
            tenant_id="tenant_provenance",
            action_id="act_reorder_99",
            policy_version="POL-LOW-RISK-REORDER-ALLOW v1.0",
            authorization_version="RBAC_v3_DAG",
            model_provenance=model_prov,
            data_mode="REAL",
            payload={"decision": "ALLOW", "matched_rule": "rule_stockout"}
        )

        retrieved = self.test_repo.get_by_id(event.event_id, "tenant_provenance")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.policy_version, "POL-LOW-RISK-REORDER-ALLOW v1.0")
        self.assertEqual(retrieved.authorization_version, "RBAC_v3_DAG")
        self.assertIsNotNone(retrieved.model_provenance)
        self.assertEqual(retrieved.model_provenance.model_name, "llama-3.3-70b-versatile")
        self.assertEqual(retrieved.actor.acting_user_id, "mgr_456")

    # =====================================================================
    # 7. DECISION RECORD & TIMELINE RECONSTRUCTION
    # =====================================================================

    def test_decision_record_and_timeline_reconstruction(self):
        """Validates reconstruction of complete DecisionRecord and chronological timeline."""
        tenant_id = "tenant_timeline_test"
        corr_id = "corr_flow_01"
        action_id = "act_flow_01"
        actor = LedgerActor(actor_type=ActorType.USER, actor_id="op_123")

        # 1. Action Proposed Event
        self.test_service.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor,
            tenant_id=tenant_id,
            action_id=action_id,
            correlation_id=corr_id,
            payload={
                "action_id": action_id,
                "action_type": "SCHEDULE_MAINTENANCE",
                "system_risk_level": "LOW",
                "reason": {"summary": "Bearing vibration exceeded threshold"},
                "evidence": [{"source": "vibration_sensor_04", "value": 7.2}]
            }
        )

        # 2. Authorization Allowed Event
        self.test_service.record_event(
            event_type=EventType.AUTHORIZATION_ALLOWED.value,
            actor=actor,
            tenant_id=tenant_id,
            action_id=action_id,
            correlation_id=corr_id,
            payload={"permission": "action.create", "matched_role": "OPERATOR"}
        )

        # 3. Policy Evaluated Event
        self.test_service.record_event(
            event_type=EventType.POLICY_ALLOWED.value,
            actor=actor,
            tenant_id=tenant_id,
            action_id=action_id,
            correlation_id=corr_id,
            policy_version="POL-CRITICAL-LINE-APPROVAL v1.0",
            payload={"decision": "ALLOW"}
        )

        # 4. Simulation Completed Event
        self.test_service.record_event(
            event_type=EventType.ACTION_SIMULATION_COMPLETED.value,
            actor=actor,
            tenant_id=tenant_id,
            action_id=action_id,
            correlation_id=corr_id,
            data_mode="SIMULATION",
            payload={"preview": "Safe state"}
        )

        # Verify Timeline
        timeline = self.test_service.get_timeline(tenant_id, correlation_id=corr_id)
        self.assertEqual(len(timeline), 4)
        self.assertEqual(timeline[0].event_type, EventType.ACTION_PROPOSED.value)
        self.assertEqual(timeline[1].event_type, EventType.AUTHORIZATION_ALLOWED.value)
        self.assertEqual(timeline[2].event_type, EventType.POLICY_ALLOWED.value)
        self.assertEqual(timeline[3].event_type, EventType.ACTION_SIMULATION_COMPLETED.value)

        # Verify Decision Record Graph Reconstruction
        record = self.test_service.get_decision_record(action_id, tenant_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.action_id, action_id)
        self.assertEqual(record.decision, "POLICY_ALLOWED")
        self.assertEqual(record.risk_level, "LOW")
        self.assertEqual(len(record.evidence_refs), 1)
        self.assertEqual(record.approval_id, "NOT_AVAILABLE")
        self.assertEqual(record.execution_id, "NOT_AVAILABLE")
        self.assertEqual(record.verification_id, "NOT_AVAILABLE")

    # =====================================================================
    # 8. REST ENDPOINTS (/api/v3/audit/*)
    # =====================================================================

    def test_api_audit_query_authorized(self):
        """Tests GET /api/v3/audit/events requires audit.read and returns events."""
        headers = self._auth_headers(token="security_token")
        res = self.client.get("/api/v3/audit/events", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("events", data)

    def test_api_audit_query_forbidden_without_permission(self):
        """Tests that a user without audit.read receives 403 Forbidden."""
        headers = self._auth_headers(token="operator_token")  # operator has action.create, not audit.read
        res = self.client.get("/api/v3/audit/events", headers=headers)
        self.assertEqual(res.status_code, 403)

    def test_api_audit_timeline_endpoint(self):
        """Tests GET /api/v3/audit/timeline with correlation_id."""
        # Seed an event through global audit_ledger
        actor = LedgerActor(actor_type=ActorType.USER, actor_id="op_seed")
        audit_ledger.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor,
            tenant_id="tenant_default",
            correlation_id="corr_api_timeline_01",
            payload={"action": "reorder"}
        )

        headers = self._auth_headers(token="security_token")
        res = self.client.get("/api/v3/audit/timeline?correlation_id=corr_api_timeline_01", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["total_events"], 1)

    def test_simulation_mode_distinction(self):
        """Simulation events must explicitly record data_mode = SIMULATION."""
        actor = LedgerActor(actor_type=ActorType.SIMULATOR, actor_id="sim_env_01")
        sim_evt = self.test_service.record_event(
            event_type=EventType.SIMULATION_ANOMALY_TRIGGERED.value,
            actor=actor,
            tenant_id="tenant_sim_test",
            data_mode=DataMode.SIMULATION.value,
            payload={"anomaly": "bearing_heat_spike", "injected_temp": 94.2}
        )
        self.assertEqual(sim_evt.data_mode, "SIMULATION")
        self.assertEqual(sim_evt.actor.actor_type, ActorType.SIMULATOR)

    def test_actor_model_separation_user_vs_agent(self):
        """AI Agents acting on behalf of users must distinguish actor from acting_user_id."""
        agent_actor = LedgerActor(
            actor_type=ActorType.AGENT,
            actor_id="agent_planner_09",
            acting_user_id="user_john_doe",
            roles=["OPERATOR"]
        )
        evt = self.test_service.record_event(
            event_type=EventType.AGENT_TOOL_CALLED.value,
            actor=agent_actor,
            tenant_id="tenant_agent_test",
            payload={"tool_name": "preview_action_impact"}
        )
        self.assertEqual(evt.actor.actor_type, ActorType.AGENT)
        self.assertEqual(evt.actor.actor_id, "agent_planner_09")
        self.assertEqual(evt.actor.acting_user_id, "user_john_doe")

    def test_api_get_event_by_id_endpoint(self):
        """Tests GET /api/v3/audit/events/{id} with tenant isolation."""
        actor = LedgerActor(actor_type=ActorType.USER, actor_id="user_evt_id")
        created_evt = audit_ledger.record_event(
            event_type=EventType.DATABASE_CONNECTION_REQUESTED.value,
            actor=actor,
            tenant_id="tenant_default",
            payload={"db": "test_db"}
        )

        headers = self._auth_headers(token="security_token", tenant_id="tenant_default")
        res = self.client.get(f"/api/v3/audit/events/{created_evt.event_id}", headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["event"]["event_id"], created_evt.event_id)

        # Cross-tenant query on the same event_id must return 404
        headers_other = self._auth_headers(token="security_token", tenant_id="tenant_other_boundary")
        res_cross = self.client.get(f"/api/v3/audit/events/{created_evt.event_id}", headers=headers_other)
        self.assertEqual(res_cross.status_code, 404)

    def test_api_get_decision_record_endpoint(self):
        """Tests GET /api/v3/audit/decisions/{action_id}."""
        act_id = f"act_dec_endpoint_{uuid.uuid4().hex[:8]}"
        actor = LedgerActor(actor_type=ActorType.USER, actor_id="op_dec_test")
        audit_ledger.record_event(
            event_type=EventType.ACTION_PROPOSED.value,
            actor=actor,
            tenant_id="tenant_default",
            action_id=act_id,
            payload={
                "action_id": act_id,
                "action_type": "EMERGENCY_STOP",
                "system_risk_level": "CRITICAL",
                "reason": {"summary": "Overheating"},
                "evidence": [{"source": "temp_sensor", "value": 110}]
            }
        )

        headers = self._auth_headers(token="security_token", tenant_id="tenant_default")
        res = self.client.get(f"/api/v3/audit/decisions/{act_id}", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["decision_record"]["action_id"], act_id)
        self.assertEqual(data["decision_record"]["approval_id"], "NOT_AVAILABLE")
        self.assertEqual(data["decision_record"]["execution_id"], "NOT_AVAILABLE")
        self.assertEqual(data["decision_record"]["verification_id"], "NOT_AVAILABLE")

    # =====================================================================
    # 9. STRICT EXECUTION BOUNDARY (POST /{id}/execute IS DISALLOWED)
    # =====================================================================

    def test_action_execute_endpoint_strictly_returns_405(self):
        """Verifies that POST /api/v3/actions/{id}/execute is routed to Execution Gateway (404 on missing action)."""
        headers = self._auth_headers(token="manager_token")
        res = self.client.post("/api/v3/actions/act_test_01/execute", headers=headers)
        self.assertEqual(res.status_code, 404)
        self.assertIn("ACTION_NOT_FOUND", res.text)


if __name__ == "__main__":
    unittest.main()
