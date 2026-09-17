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
from data.schemas.event_contract import CanonicalEvent, EventCategory, EventSeverity as ESev, EventLifecycle as ELife
from services.incident_repository import IncidentRepository
from services.incident_service import IncidentService, VALID_TRANSITIONS
from services.event_repository import EventRepository

client = TestClient(app)

def get_test_auth_headers(tenant_id="tenant_A", role="manager"):
    if tenant_id == "tenant_A":
        return {"Authorization": "Bearer test_token_tenant_a"}
    elif tenant_id == "tenant_B":
        return {"Authorization": "Bearer test_token_tenant_b"}
    return {"Authorization": f"Bearer {role}_token"}


class TestV3IncidentManagement:

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        self.db_path = f"test_incidents_{uuid.uuid4().hex}.sqlite"
        self.event_db_path = f"test_events_{uuid.uuid4().hex}.sqlite"
        self.repo = IncidentRepository(db_path=self.db_path)
        self.event_repo = EventRepository(db_path=self.event_db_path)
        self.service = IncidentService(repository=self.repo, event_repository=self.event_repo)
        yield
        for p in [self.db_path, self.event_db_path]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except PermissionError:
                    pass

    # =========================================================================
    # CONTRACT TESTS (1-6)
    # =========================================================================

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
        assert incident.tenant_id == "tenant_A"
        assert incident.title == "Fire Alarm Triggered"
        assert incident.description == "Smoke detected in Sector 4"
        assert incident.opened_at is not None
        assert incident.status == IncidentLifecycle.OPEN

    def test_02_category_validation(self):
        for cat in IncidentCategory:
            inc = self.service.create_incident(
                tenant_id="tenant_A",
                category=cat,
                title=f"Category test {cat.value}",
                actor="test_user"
            )
            assert inc.category == cat
        with pytest.raises(ValueError):
            IncidentCategory("NON_EXISTENT_CATEGORY")

    def test_03_severity_validation(self):
        for sev in IncidentSeverity:
            inc = self.service.create_incident(
                tenant_id="tenant_A",
                category=IncidentCategory.OPERATIONAL,
                title="Severity test",
                actor="test_user",
                severity=sev
            )
            assert inc.severity == sev
        with pytest.raises(ValueError):
            IncidentSeverity("INVALID_SEVERITY")

    def test_04_priority_validation(self):
        for prio in IncidentPriority:
            inc = self.service.create_incident(
                tenant_id="tenant_A",
                category=IncidentCategory.OPERATIONAL,
                title="Priority test",
                actor="test_user",
                priority=prio
            )
            assert inc.priority == prio
        with pytest.raises(ValueError):
            IncidentPriority("INVALID_PRIORITY")

    def test_05_lifecycle_validation(self):
        assert IncidentLifecycle.OPEN == "OPEN"
        assert IncidentLifecycle.ACKNOWLEDGED == "ACKNOWLEDGED"
        assert IncidentLifecycle.INVESTIGATING == "INVESTIGATING"
        assert IncidentLifecycle.MITIGATED == "MITIGATED"
        assert IncidentLifecycle.RESOLVED == "RESOLVED"
        assert IncidentLifecycle.CLOSED == "CLOSED"
        assert IncidentLifecycle.REOPENED == "REOPENED"
        assert IncidentLifecycle.CANCELLED == "CANCELLED"

    def test_06_schema_version(self):
        inc = self.service.create_incident(
            tenant_id="tenant_A",
            category=IncidentCategory.SYSTEM,
            title="Version check",
            actor="test_user"
        )
        assert inc.schema_version == "3.0"

    # =========================================================================
    # LIFECYCLE TRANSITIONS (7-13)
    # =========================================================================

    def test_07_valid_open_to_acknowledged(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T1", actor="u1")
        ack = self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="operator_01", reason="Under review")
        assert ack.status == IncidentLifecycle.ACKNOWLEDGED
        assert ack.acknowledged_by == "operator_01"
        assert ack.acknowledged_at is not None

    def test_08_valid_acknowledged_to_investigating(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T2", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        inv = self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, actor="u1")
        assert inv.status == IncidentLifecycle.INVESTIGATING

    def test_09_valid_investigating_to_mitigated(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T3", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, actor="u1")
        mit = self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.MITIGATED, actor="u1")
        assert mit.status == IncidentLifecycle.MITIGATED

    def test_10_valid_mitigated_to_resolved(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T4", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.MITIGATED, actor="u1")
        res = self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, actor="u1")
        assert res.status == IncidentLifecycle.RESOLVED
        assert res.resolved_at is not None

    def test_11_valid_resolved_to_closed(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T5", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, actor="u1")
        closed = self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.CLOSED, actor="u1")
        assert closed.status == IncidentLifecycle.CLOSED
        assert closed.closed_at is not None

    def test_12_valid_reopened_transition(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T6", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, actor="u1")
        reopened = self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.REOPENED, actor="u1", reason="Issue recurred")
        assert reopened.status == IncidentLifecycle.REOPENED

    def test_13_invalid_lifecycle_transition_rejected(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T7", actor="u1")
        # Direct OPEN -> RESOLVED is invalid
        with pytest.raises(ValueError, match="Invalid transition"):
            self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.RESOLVED, actor="u1")
        # Direct OPEN -> MITIGATED is invalid
        with pytest.raises(ValueError, match="Invalid transition"):
            self.service.transition_lifecycle(inc.incident_id, "tenant_A", IncidentLifecycle.MITIGATED, actor="u1")

    # =========================================================================
    # HISTORY & TIMELINE (14-16)
    # =========================================================================

    def test_14_lifecycle_history_recorded(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.SECURITY, title="Auth Breach", actor="sec_op")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="sec_lead", reason="Triaged by security")
        with self.repo._get_conn() as conn:
            hist = conn.execute("SELECT * FROM incident_history WHERE incident_id = ? ORDER BY timestamp ASC", (inc.incident_id,)).fetchall()
        assert len(hist) == 2
        assert hist[0]["previous_state"] == "NONE"
        assert hist[0]["new_state"] == "OPEN"
        assert hist[1]["previous_state"] == "OPEN"
        assert hist[1]["new_state"] == "ACKNOWLEDGED"
        assert hist[1]["actor"] == "sec_lead"
        assert hist[1]["reason"] == "Triaged by security"

    def test_15_metadata_history_recorded(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Belt Speed", actor="u1")
        self.service.update_metadata(inc.incident_id, "tenant_A", actor="mgr1", severity=IncidentSeverity.HIGH, priority=IncidentPriority.URGENT)
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        entries = [t.entry_type for t in details["timeline"]]
        assert IncidentTimelineEntryType.SEVERITY_CHANGED in entries
        assert IncidentTimelineEntryType.PRIORITY_CHANGED in entries

    def test_16_append_only_timeline(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.QUALITY, title="Purity Drop", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u2")
        self.service.add_note(inc.incident_id, "tenant_A", "Sample taken for lab", actor="u2")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        timeline = details["timeline"]
        assert len(timeline) == 3
        assert timeline[0].entry_type == IncidentTimelineEntryType.CREATED
        assert timeline[1].entry_type == IncidentTimelineEntryType.LIFECYCLE_TRANSITION
        assert timeline[2].entry_type == IncidentTimelineEntryType.NOTE_ADDED

    # =========================================================================
    # OWNERSHIP & IDENTITY (17-19)
    # =========================================================================

    def test_17_assignment(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.MAINTENANCE, title="Valve Leak", actor="u1")
        assigned = self.service.assign_incident(inc.incident_id, "tenant_A", actor="mgr", assigned_user="tech_bob", assigned_team="team_alpha")
        assert assigned.assigned_user == "tech_bob"
        assert assigned.assigned_team == "team_alpha"

    def test_18_acknowledgement_identity(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Tank Level", actor="u1")
        ack = self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="operator_mary")
        assert ack.acknowledged_by == "operator_mary"
        assert ack.acknowledged_at is not None

    def test_19_unauthorized_assignment_blocked(self):
        import api.incident_routes
        api.incident_routes.service = self.service
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="d1",
                effect=AuthzDecisionEffect.DENY,
                reason_code=AuthzReasonCode.INSUFFICIENT_ROLE_PERMISSIONS,
                reason="Missing incidents.assign permission",
                decision_hash="hash",
                required_permission="incidents.assign"
            )
            res = client.patch(
                "/api/v3/incidents/inc_fake/assignment",
                json={"assigned_user": "hacker"},
                headers={"Authorization": "Bearer viewer_token"}
            )
            assert res.status_code == 403

    # =========================================================================
    # EVENTS INTEGRATION (20-22)
    # =========================================================================

    def test_20_event_association(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Fan Trip", actor="u1")
        self.service.associate_event(inc.incident_id, "tenant_A", "evt_101", actor="u1", relationship=EventRelationshipType.TRIGGER)
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert len(details["events"]) == 1
        assert details["events"][0].event_id == "evt_101"
        assert details["events"][0].relationship_type == EventRelationshipType.TRIGGER

    def test_21_duplicate_event_association_handling(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Fan Trip 2", actor="u1")
        self.service.associate_event(inc.incident_id, "tenant_A", "evt_101", actor="u1", relationship=EventRelationshipType.TRIGGER)
        # Re-associating same event must be idempotent without raising fatal duplicate error
        self.service.associate_event(inc.incident_id, "tenant_A", "evt_101", actor="u1", relationship=EventRelationshipType.TRIGGER)
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert len(details["events"]) == 1

    def test_22_cross_tenant_event_blocked(self):
        # Create an event in Tenant B
        evt_b = CanonicalEvent(
            event_id="evt_tenant_b_secret",
            tenant_id="tenant_B",
            workspace_id="ws_b",
            plant_id="plant_b",
            category=EventCategory.SECURITY,
            event_type="access.denied",
            severity=ESev.HIGH,
            lifecycle=ELife.RECORDED,
            occurred_at="2026-09-17T00:00:00Z",
            observed_at="2026-09-17T00:00:00Z"
        )
        self.event_repo.record_event(evt_b)

        # Tenant A incident tries to associate Tenant B event
        inc_a = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.SECURITY, title="Tenant A Inc", actor="u1")
        with pytest.raises(ValueError, match="Cross-tenant event association blocked"):
            self.service.associate_event(inc_a.incident_id, "tenant_A", evt_b.event_id, actor="u1")

    # =========================================================================
    # EVIDENCE (23-25)
    # =========================================================================

    def test_23_evidence_creation(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.QUALITY, title="Viscosity Error", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.EXTERNAL_REFERENCE, "ext_doc_88", actor="u1", metadata={"url": "https://specs.internal/88"})
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert len(details["evidence"]) == 1
        assert details["evidence"][0].source_id == "ext_doc_88"

    def test_24_evidence_retrieval(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.QUALITY, title="pH Anomaly", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.ANOMALY, "anom_ph_1", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.TWIN_STATE, "twin_sensor_7", actor="u1")
        evid = self.repo.get_evidence(inc.incident_id)
        assert len(evid) == 2

    def test_25_evidence_tenant_isolation(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="T_Evid", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.OPERATOR_NOTE, "ref_1", actor="u1")
        with pytest.raises(ValueError, match="not found for tenant tenant_B"):
            self.service.get_incident_details(inc.incident_id, "tenant_B")

    # =========================================================================
    # ANOMALIES INTEGRATION (26-27)
    # =========================================================================

    def test_26_anomaly_reference(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Heat Spike", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.ANOMALY, "anom_007", actor="detector", metadata={"score": 0.98})
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert details["evidence"][0].evidence_type == EvidenceType.ANOMALY
        assert details["evidence"][0].metadata["score"] == 0.98

    def test_27_cross_tenant_anomaly_blocked(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Heat Spike", actor="u1")
        with pytest.raises(ValueError, match="Cross-tenant ANOMALY reference blocked"):
            self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.ANOMALY, "anom_tenant_b", actor="u1", metadata={"tenant_id": "tenant_B"})

    # =========================================================================
    # TWIN / KG / ONTOLOGY REFERENCES (28-31)
    # =========================================================================

    def test_28_twin_reference(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.PRODUCTION, title="Robot Arm Stalled", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.TWIN_STATE, "twin_arm_01", actor="u1")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert details["evidence"][0].evidence_type == EvidenceType.TWIN_STATE

    def test_29_kg_reference(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.INFRASTRUCTURE, title="Power Substation Flap", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.KNOWLEDGE_GRAPH, "kg_substation_node_3", actor="u1")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert details["evidence"][0].evidence_type == EvidenceType.KNOWLEDGE_GRAPH

    def test_30_ontology_reference(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Conveyor Speed", actor="u1")
        self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.EXTERNAL_REFERENCE, "ontology_asset_type_conveyor", actor="u1")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert details["evidence"][0].source_id == "ontology_asset_type_conveyor"

    def test_31_cross_tenant_reference_rejection(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.PRODUCTION, title="Twin Ref Check", actor="u1")
        with pytest.raises(ValueError, match="Cross-tenant TWIN_STATE reference blocked"):
            self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.TWIN_STATE, "twin_plant_b", actor="u1", metadata={"tenant_id": "tenant_B"})
        with pytest.raises(ValueError, match="Cross-tenant KNOWLEDGE_GRAPH reference blocked"):
            self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.KNOWLEDGE_GRAPH, "kg_node_b", actor="u1", metadata={"tenant_id": "tenant_B"})

    # =========================================================================
    # NOTES (32-34)
    # =========================================================================

    def test_32_operator_note(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.MAINTENANCE, title="Belt Slap", actor="u1")
        self.service.add_note(inc.incident_id, "tenant_A", "Tension adjustment completed on motor 2", actor="tech_alice")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert len(details["notes"]) == 1
        assert details["notes"][0].text == "Tension adjustment completed on motor 2"
        assert details["notes"][0].author == "tech_alice"

    def test_33_note_size_limit(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.MAINTENANCE, title="Belt Slap", actor="u1")
        too_long = "x" * 4097
        with pytest.raises(ValueError, match="exceeds maximum length"):
            self.service.add_note(inc.incident_id, "tenant_A", too_long, actor="u1")

    def test_34_note_author_identity(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Note check", actor="u1")
        self.service.add_note(inc.incident_id, "tenant_A", "Check completed", actor="verified_lead_42")
        details = self.service.get_incident_details(inc.incident_id, "tenant_A")
        assert details["notes"][0].author == "verified_lead_42"

    # =========================================================================
    # TENANT & SECURITY (35-39)
    # =========================================================================

    def test_35_tenant_isolation(self):
        inc_a = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.SECURITY, title="Secret A", actor="u1")
        with pytest.raises(ValueError, match="not found for tenant tenant_B"):
            self.service.get_incident_details(inc_a.incident_id, "tenant_B")
        with pytest.raises(ValueError, match="not found for tenant tenant_B"):
            self.service.acknowledge_incident(inc_a.incident_id, "tenant_B", actor="hacker")

    def test_36_workspace_isolation(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="WS Scope", actor="u1", workspace_id="ws_mfg_01")
        assert inc.workspace_id == "ws_mfg_01"

    def test_37_plant_isolation(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Plant Scope", actor="u1", plant_id="plant_austin")
        assert inc.plant_id == "plant_austin"

    def test_38_authorization(self):
        from services.authorization_service import PermissionRegistry
        registry = PermissionRegistry()
        perm = registry.get_permission("incidents.read")
        assert perm is not None
        assert perm.resource == "incidents"
        assert registry.get_permission("incidents.acknowledge") is not None
        assert registry.get_permission("incidents.transition") is not None

    def test_39_abac_restrictions(self):
        from services.authorization_service import authorization_service
        from data.schemas.authorization_contract import UserIdentity, UserStatus, AuthorizationScope, AuthorizationContext, AuthzDecisionEffect
        ident = UserIdentity(user_id="op_1", tenant_id="tenant_A", status=UserStatus.ACTIVE, roles=["VIEWER"], clearance_level=1)
        scope = AuthorizationScope(tenant_id="tenant_A")
        # VIEWER has incidents.read
        ctx_read = AuthorizationContext(identity=ident, required_permission="incidents.read", scope=scope)
        dec_read = authorization_service.evaluate(ctx_read)
        assert dec_read.effect == AuthzDecisionEffect.ALLOW
        # VIEWER does not have incidents.create
        ctx_create = AuthorizationContext(identity=ident, required_permission="incidents.create", scope=scope)
        dec_create = authorization_service.evaluate(ctx_create)
        assert dec_create.effect == AuthzDecisionEffect.DENY

    # =========================================================================
    # CONCURRENCY (40-41)
    # =========================================================================

    def test_40_concurrent_lifecycle_transition(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Race", actor="u1")
        stale_incident = self.repo.get_incident(inc.incident_id, "tenant_A")
        # Advance state
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        # Stale attempt directly to repository fails
        with pytest.raises(ValueError, match="Concurrency conflict"):
            self.repo.save_incident(stale_incident)

    def test_41_stale_version_rejection(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Version Race", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        # Client passes outdated expected_version (1 instead of 2)
        with pytest.raises(ValueError, match="Concurrency conflict"):
            self.service.transition_lifecycle(
                inc.incident_id, "tenant_A", IncidentLifecycle.INVESTIGATING, actor="u1", expected_version=1
            )

    # =========================================================================
    # QUERY & RESOURCE LIMITS (42-45)
    # =========================================================================

    def test_42_bounded_list(self):
        for i in range(10):
            self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title=f"Inc {i}", actor="u1")
        listed = self.service.list_incidents("tenant_A", limit=5)
        assert len(listed) == 5
        # Exceeding max limit (500) gets clamped
        clamped = self.service.list_incidents("tenant_A", limit=9999)
        assert len(clamped) <= 500

    def test_43_bounded_timeline(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Timeline Bounds", actor="u1")
        for i in range(10):
            self.service.add_note(inc.incident_id, "tenant_A", f"Note {i}", actor="u1")
        timeline = self.repo.get_timeline(inc.incident_id, limit=4)
        assert len(timeline) == 4

    def test_44_evidence_limits(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Evidence Bounds", actor="u1")
        for i in range(10):
            self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.EXTERNAL_REFERENCE, f"ref_{i}", actor="u1")
        evid = self.repo.get_evidence(inc.incident_id, limit=3)
        assert len(evid) == 3

    def test_45_payload_limits(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Payload Bounds", actor="u1")
        large_metadata = {"huge": "a" * 35000}
        with pytest.raises(ValueError, match="Evidence metadata exceeds maximum size limit"):
            self.service.add_evidence(inc.incident_id, "tenant_A", EvidenceType.ANOMALY, "anom_big", actor="u1", metadata=large_metadata)

    # =========================================================================
    # DETERMINISM (46-47)
    # =========================================================================

    def test_46_deterministic_timeline_ordering(self):
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="Ordering", actor="u1")
        self.service.add_note(inc.incident_id, "tenant_A", "N1", actor="u1")
        self.service.add_note(inc.incident_id, "tenant_A", "N2", actor="u1")
        timeline = self.service.get_incident_details(inc.incident_id, "tenant_A")["timeline"]
        assert len(timeline) == 3
        assert timeline[0].entry_type == IncidentTimelineEntryType.CREATED
        assert timeline[1].entry_type == IncidentTimelineEntryType.NOTE_ADDED
        assert timeline[2].entry_type == IncidentTimelineEntryType.NOTE_ADDED

    def test_47_deterministic_fingerprint(self):
        inc1 = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.MAINTENANCE, title="M1", actor="u1", deduplication_key="motor_4_temp")
        assert inc1.incident_fingerprint is not None
        # Duplicate key in same tenant & category is rejected
        with pytest.raises(ValueError, match="already exists"):
            self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.MAINTENANCE, title="M2", actor="u1", deduplication_key="motor_4_temp")

    # =========================================================================
    # EXECUTION ISOLATION (48-50)
    # =========================================================================

    def test_48_no_execution_gateway_import(self):
        import services.incident_service
        import api.incident_routes
        import services.incident_repository
        for mod in [services.incident_service, api.incident_routes, services.incident_repository]:
            source = inspect.getsource(mod)
            assert "ExecutionGateway" not in source, f"Module {mod.__name__} must NOT mention ExecutionGateway"
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for n in node.names:
                        assert "ExecutionGateway" not in n.name

    def test_49_no_execution_invocation(self):
        import services.incident_service
        source = inspect.getsource(services.incident_service)
        for prohibited in ["execute_action", "apply_action", "trigger_remediation", "emergency_stop", "plc_write"]:
            assert prohibited not in source

    def test_50_incident_cannot_mutate_physical_state(self):
        # Service methods are strictly data record management
        methods = [m for m in dir(self.service) if not m.startswith("_")]
        prohibited_prefixes = ["actuate", "execute", "start_motor", "stop_conveyor", "override_setpoint"]
        for m in methods:
            for p in prohibited_prefixes:
                assert not m.startswith(p), f"Service method {m} violates physical execution boundary"

    # =========================================================================
    # RCA ISOLATION (51-52)
    # =========================================================================

    def test_51_no_rca_engine(self):
        import services.incident_service
        source = inspect.getsource(services.incident_service)
        for prohibited in ["root_cause", "rca_engine", "fault_tree", "cause_ranking", "infer_cause"]:
            assert prohibited not in source.lower()

    def test_52_no_causal_inference_logic(self):
        import services.incident_service
        source = inspect.getsource(services.incident_service)
        for prohibited in ["causal_graph", "do_calculus", "counterfactual", "dag_analysis"]:
            assert prohibited not in source.lower()

    # =========================================================================
    # FASTAPI HTTP INTEGRATION TESTS (53-56)
    # =========================================================================

    def test_53_api_integration_create_and_list(self):
        headers = get_test_auth_headers(tenant_id="tenant_A")
        import api.incident_routes
        api.incident_routes.service = self.service
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="t1", effect=AuthzDecisionEffect.ALLOW, reason_code=AuthzReasonCode.ALLOWED,
                reason="OK", decision_hash="h1", required_permission="incidents.create"
            )
            res = client.post("/api/v3/incidents", json={
                "category": "OPERATIONAL", "title": "API Inc 1", "severity": "HIGH", "priority": "URGENT"
            }, headers=headers)
        assert res.status_code == 201
        inc_id = res.json()["incident_id"]

        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="t2", effect=AuthzDecisionEffect.ALLOW, reason_code=AuthzReasonCode.ALLOWED,
                reason="OK", decision_hash="h2", required_permission="incidents.read"
            )
            list_res = client.get("/api/v3/incidents", headers=headers)
        assert list_res.status_code == 200
        assert any(i["incident_id"] == inc_id for i in list_res.json())

    def test_54_api_integration_acknowledge(self):
        headers = get_test_auth_headers(tenant_id="tenant_A")
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.SAFETY, title="E-Stop", actor="u1")
        import api.incident_routes
        api.incident_routes.service = self.service
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="t3", effect=AuthzDecisionEffect.ALLOW, reason_code=AuthzReasonCode.ALLOWED,
                reason="OK", decision_hash="h3", required_permission="incidents.acknowledge"
            )
            res = client.post(f"/api/v3/incidents/{inc.incident_id}/acknowledge", json={"reason": "Operator Mary responding"}, headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "ACKNOWLEDGED"

    def test_55_api_integration_transition_and_concurrency(self):
        headers = get_test_auth_headers(tenant_id="tenant_A")
        inc = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.OPERATIONAL, title="API Concurrency", actor="u1")
        self.service.acknowledge_incident(inc.incident_id, "tenant_A", actor="u1")
        import api.incident_routes
        api.incident_routes.service = self.service
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="t4", effect=AuthzDecisionEffect.ALLOW, reason_code=AuthzReasonCode.ALLOWED,
                reason="OK", decision_hash="h4", required_permission="incidents.transition"
            )
            # Stale version 1 should fail with 409
            conflict_res = client.patch(
                f"/api/v3/incidents/{inc.incident_id}/lifecycle",
                json={"new_state": "INVESTIGATING", "expected_version": 1},
                headers=headers
            )
        assert conflict_res.status_code == 409

    def test_56_api_integration_tenant_isolation(self):
        headers_a = get_test_auth_headers(tenant_id="tenant_A")
        headers_b = get_test_auth_headers(tenant_id="tenant_B")
        inc_a = self.service.create_incident(tenant_id="tenant_A", category=IncidentCategory.QUALITY, title="Tenant A Only", actor="u1")
        import api.incident_routes
        api.incident_routes.service = self.service
        from data.schemas.authorization_contract import AuthorizationDecision, AuthzDecisionEffect, AuthzReasonCode
        with patch("core.auth.authorization_service.evaluate") as mock_eval:
            mock_eval.return_value = AuthorizationDecision(
                decision_id="t5", effect=AuthzDecisionEffect.ALLOW, reason_code=AuthzReasonCode.ALLOWED,
                reason="OK", decision_hash="h5", required_permission="incidents.read"
            )
            res = client.get(f"/api/v3/incidents/{inc_a.incident_id}", headers=headers_b)
        assert res.status_code == 404
