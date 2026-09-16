import pytest
import os
import uuid
import ast
import inspect
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app
from core.auth import Identity, require_permission
from data.schemas.incident_contract import (
    IncidentContract, IncidentCategory, IncidentSeverity, IncidentPriority, IncidentLifecycle,
    EventRelationshipType, EvidenceType, IncidentTimelineEntryType
)
from services.incident_repository import IncidentRepository
from services.incident_service import IncidentService

client = TestClient(app)

def get_test_auth_headers(tenant_id="tenant_A", role="manager"):
    # Using fixed server-authoritative token for tenant isolation testing
    if tenant_id == "tenant_A":
        return {"Authorization": "Bearer test_token_tenant_a"}
    elif tenant_id == "tenant_B":
        return {"Authorization": "Bearer test_token_tenant_b"}
    return {"Authorization": f"Bearer {role}_token"}


class TestV3IncidentManagement:
    
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.db_path = f"test_incidents_{uuid.uuid4().hex}.sqlite"
        self.repo = IncidentRepository(db_path=self.db_path)
        self.service = IncidentService(repository=self.repo)
        yield
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_01_incident_contract_validation(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.SAFETY,
            title="Fire Alarm Triggered",
            actor="test_user",
            description="Smoke detected in Sector 4",
            severity=IncidentSeverity.CRITICAL,
            priority=IncidentPriority.URGENT
        )
        assert incident.incident_id.startswith("inc_")
        assert incident.schema_version == "3.0"
        assert incident.category == IncidentCategory.SAFETY
        assert incident.severity == IncidentSeverity.CRITICAL
        assert incident.priority == IncidentPriority.URGENT
        assert incident.status == IncidentLifecycle.OPEN
        assert incident.opened_at is not None

    def test_02_lifecycle_transitions(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.OPERATIONAL,
            title="Conveyor Belt Jam",
            actor="test_user"
        )
        
        # Valid: OPEN -> ACKNOWLEDGED
        incident = self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.ACKNOWLEDGED, "op_user")
        assert incident.status == IncidentLifecycle.ACKNOWLEDGED
        assert incident.acknowledged_by == "op_user"
        
        # Valid: ACKNOWLEDGED -> INVESTIGATING
        incident = self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, "op_user")
        assert incident.status == IncidentLifecycle.INVESTIGATING
        
        # Valid: INVESTIGATING -> MITIGATED
        incident = self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.MITIGATED, "op_user")
        assert incident.status == IncidentLifecycle.MITIGATED
        
        # Valid: MITIGATED -> RESOLVED
        incident = self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, "op_user")
        assert incident.status == IncidentLifecycle.RESOLVED
        assert incident.resolved_at is not None

    def test_03_invalid_lifecycle_transition_rejected(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.QUALITY,
            title="Defect Rate Spike",
            actor="test_user"
        )
        # Invalid: OPEN -> RESOLVED
        with pytest.raises(ValueError, match="Invalid transition"):
            self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, "test_user")

    def test_04_history_and_timeline_append_only(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.SYSTEM,
            title="Database Latency",
            actor="test_user"
        )
        self.service.transition_lifecycle(incident.incident_id, "tenant_A", IncidentLifecycle.ACKNOWLEDGED, "test_user")
        
        details = self.service.get_incident_details(incident.incident_id, "tenant_A")
        timeline = details["timeline"]
        
        assert len(timeline) == 2
        assert timeline[0].entry_type == IncidentTimelineEntryType.CREATED
        assert timeline[1].entry_type == IncidentTimelineEntryType.LIFECYCLE_TRANSITION

    def test_05_tenant_isolation(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.SECURITY,
            title="Unauthorized Access Attempt",
            actor="sec_user"
        )
        
        # Tenant B cannot retrieve Tenant A's incident
        with pytest.raises(ValueError, match="not found for tenant tenant_B"):
            self.service.get_incident_details(incident.incident_id, "tenant_B")
            
        # Tenant B cannot modify Tenant A's incident
        with pytest.raises(ValueError, match="not found for tenant tenant_B"):
            self.service.transition_lifecycle(incident.incident_id, "tenant_B", IncidentLifecycle.ACKNOWLEDGED, "sec_user")

    def test_06_concurrency_optimistic_locking(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.MAINTENANCE,
            title="Pump Failure",
            actor="test_user"
        )
        
        # Simulate race condition: Fetch incident directly, mutate version to simulate stale read
        stale_incident = self.repo.get_incident(incident.incident_id, "tenant_A")
        
        # Valid update
        self.service.update_metadata(incident.incident_id, "tenant_A", "test_user", severity=IncidentSeverity.HIGH)
        
        # Stale update attempt
        with pytest.raises(ValueError, match="Concurrency conflict"):
            self.repo.save_incident(stale_incident)

    def test_07_event_association(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.OPERATIONAL,
            title="Sensor Offline",
            actor="test_user"
        )
        
        self.service.associate_event(incident.incident_id, "tenant_A", "evt_12345", "test_user", EventRelationshipType.TRIGGER)
        
        details = self.service.get_incident_details(incident.incident_id, "tenant_A")
        assert len(details["events"]) == 1
        assert details["events"][0].event_id == "evt_12345"
        assert details["events"][0].relationship_type == EventRelationshipType.TRIGGER

    def test_08_evidence_and_notes(self):
        incident = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.PRODUCTION,
            title="Production Line Halt",
            actor="test_user"
        )
        
        self.service.add_evidence(incident.incident_id, "tenant_A", EvidenceType.ANOMALY, "anom_999", "test_user")
        self.service.add_note(incident.incident_id, "tenant_A", "Operator confirmed halt via manual E-STOP", "op_user")
        
        details = self.service.get_incident_details(incident.incident_id, "tenant_A")
        assert len(details["evidence"]) == 1
        assert details["evidence"][0].source_id == "anom_999"
        
        assert len(details["notes"]) == 1
        assert details["notes"][0].text == "Operator confirmed halt via manual E-STOP"
        
        timeline = details["timeline"]
        # CREATED, EVIDENCE_ADDED, NOTE_ADDED
        assert len(timeline) == 3
        
    def test_09_deterministic_fingerprint(self):
        incident_1 = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.OPERATIONAL,
            title="Duplicate Test 1",
            actor="test_user",
            deduplication_key="pump_01_failure"
        )
        assert incident_1.incident_fingerprint is not None
        
        with pytest.raises(ValueError, match="already exists"):
            self.service.create_incident(
                tenant_id="tenant_A",
                category=IncidentCategory.OPERATIONAL,
                title="Duplicate Test 2",
                actor="test_user",
                deduplication_key="pump_01_failure"
            )

    def test_10_execution_gateway_isolation(self):
        """CRITICAL: Ensures Incident Management has zero coupling to physical execution."""
        import services.incident_service
        import api.incident_routes
        
        service_source = inspect.getsource(services.incident_service)
        routes_source = inspect.getsource(api.incident_routes)
        
        assert "ExecutionGateway" not in service_source, "Incident Service MUST NOT import ExecutionGateway"
        assert "ExecutionGateway" not in routes_source, "Incident Routes MUST NOT import ExecutionGateway"
        
        service_ast = ast.parse(service_source)
        for node in ast.walk(service_ast):
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                names = [n.name for n in node.names]
                for name in names:
                    assert "ExecutionGateway" not in name
                    assert "adapters" not in name

    def test_11_api_integration_create_and_list(self):
        headers = get_test_auth_headers(tenant_id="tenant_A")
        
        # Replace the global service injected in routes with our isolated test service
        import api.incident_routes
        api.incident_routes.service = self.service
        
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="test",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="Test Bypass",
                decision_hash="test",
                required_permission="incidents.create"
            )
            
            response = client.post("/api/v3/incidents", json={
                "category": "OPERATIONAL",
                "title": "API Test Incident",
                "severity": "HIGH",
                "priority": "URGENT"
            }, headers=headers)
            
        assert response.status_code == 201
        
        inc_id = response.json()["incident_id"]
        
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="test",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="Test Bypass",
                decision_hash="test",
                required_permission="incidents.read"
            )
            response = client.get("/api/v3/incidents", headers=headers)
            
        assert response.status_code == 200
        assert len(response.json()) > 0
        assert response.json()[0]["incident_id"] == inc_id

    def test_12_api_integration_tenant_isolation(self):
        headers_a = get_test_auth_headers(tenant_id="tenant_A")
        headers_b = get_test_auth_headers(tenant_id="tenant_B")
        
        import api.incident_routes
        api.incident_routes.service = self.service
        
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="test",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="Test Bypass",
                decision_hash="test",
                required_permission="incidents.create"
            )
            
            # A creates incident
            response = client.post("/api/v3/incidents", json={
                "category": "SECURITY",
                "title": "Tenant A Secret",
            }, headers=headers_a)
            
        assert response.status_code == 201
        inc_id = response.json()["incident_id"]
        
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="test",
                effect=AuthzDecisionEffect.ALLOW,
                reason_code=AuthzReasonCode.ALLOWED,
                reason="Test Bypass",
                decision_hash="test",
                required_permission="incidents.read"
            )
            
            # B tries to read - Auth passes but Tenant isolation in service should reject
            response = client.get(f"/api/v3/incidents/{inc_id}", headers=headers_b)
            assert response.status_code == 404
            
            # B tries to transition
            response = client.patch(f"/api/v3/incidents/{inc_id}/lifecycle", json={"new_state": "ACKNOWLEDGED"}, headers=headers_b)
            assert response.status_code == 404
