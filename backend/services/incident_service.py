import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, UTC

from data.schemas.incident_contract import (
    IncidentContract, IncidentCategory, IncidentSeverity, IncidentPriority, IncidentLifecycle,
    IncidentHistory, IncidentEventAssociation, IncidentEvidence, IncidentNote, IncidentTimelineEntry,
    EvidenceType, IncidentTimelineEntryType, EventRelationshipType
)
from services.incident_repository import IncidentRepository

logger = logging.getLogger(__name__)

# Valid state transitions mapping
VALID_TRANSITIONS = {
    IncidentLifecycle.OPEN: [IncidentLifecycle.ACKNOWLEDGED, IncidentLifecycle.CLOSED, IncidentLifecycle.CANCELLED],
    IncidentLifecycle.ACKNOWLEDGED: [IncidentLifecycle.INVESTIGATING, IncidentLifecycle.MITIGATED, IncidentLifecycle.RESOLVED, IncidentLifecycle.CLOSED],
    IncidentLifecycle.INVESTIGATING: [IncidentLifecycle.MITIGATED, IncidentLifecycle.RESOLVED, IncidentLifecycle.CLOSED],
    IncidentLifecycle.MITIGATED: [IncidentLifecycle.RESOLVED, IncidentLifecycle.INVESTIGATING, IncidentLifecycle.CLOSED],
    IncidentLifecycle.RESOLVED: [IncidentLifecycle.CLOSED, IncidentLifecycle.REOPENED],
    IncidentLifecycle.CLOSED: [IncidentLifecycle.REOPENED],
    IncidentLifecycle.REOPENED: [IncidentLifecycle.ACKNOWLEDGED, IncidentLifecycle.INVESTIGATING, IncidentLifecycle.CLOSED],
    IncidentLifecycle.CANCELLED: []
}

class IncidentService:
    """
    Core business logic for Incident Management.
    Enforces lifecycle transitions, ownership, tenant isolation.
    CRITICAL: Does NOT contain or import Execution System or physical remediation adapters.
    """
    def __init__(self, repository: IncidentRepository):
        self.repo = repository

    def _ensure_tenant_access(self, incident_id: str, tenant_id: str) -> IncidentContract:
        incident = self.repo.get_incident(incident_id, tenant_id)
        if not incident:
            raise ValueError(f"Incident {incident_id} not found for tenant {tenant_id}")
        return incident

    def _now(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def create_incident(self, 
                        tenant_id: str, 
                        category: IncidentCategory, 
                        title: str, 
                        actor: str,
                        description: str = "",
                        severity: IncidentSeverity = IncidentSeverity.LOW,
                        priority: IncidentPriority = IncidentPriority.NORMAL,
                        deduplication_key: Optional[str] = None,
                        workspace_id: Optional[str] = None,
                        plant_id: Optional[str] = None) -> IncidentContract:
        
        now_ts = self._now()
        incident_id = f"inc_{uuid.uuid4().hex}"
        
        incident = IncidentContract(
            incident_id=incident_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            plant_id=plant_id,
            category=category,
            severity=severity,
            priority=priority,
            status=IncidentLifecycle.OPEN,
            title=title,
            description=description,
            detected_at=now_ts,
            opened_at=now_ts,
            updated_at=now_ts
        )
        
        if deduplication_key:
            incident.generate_fingerprint(deduplication_key)
            
        saved = self.repo.save_incident(incident)
        
        self.repo.append_history(IncidentHistory(
            incident_id=saved.incident_id,
            previous_state="NONE",
            new_state=IncidentLifecycle.OPEN.value,
            actor=actor,
            reason="Incident Created"
        ))
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=saved.incident_id,
            entry_type=IncidentTimelineEntryType.CREATED,
            actor=actor,
            metadata={"title": title}
        ))
        
        return saved

    def transition_lifecycle(self, incident_id: str, tenant_id: str, new_state: IncidentLifecycle, actor: str, reason: str = "") -> IncidentContract:
        incident = self._ensure_tenant_access(incident_id, tenant_id)
        
        if new_state not in VALID_TRANSITIONS.get(incident.status, []):
            raise ValueError(f"Invalid transition from {incident.status} to {new_state}")
            
        previous_state = incident.status
        incident.status = new_state
        now_ts = self._now()
        incident.updated_at = now_ts
        
        if new_state == IncidentLifecycle.ACKNOWLEDGED and not incident.acknowledged_at:
            incident.acknowledged_at = now_ts
            incident.acknowledged_by = actor
        elif new_state == IncidentLifecycle.RESOLVED:
            incident.resolved_at = now_ts
        elif new_state == IncidentLifecycle.CLOSED:
            incident.closed_at = now_ts
            
        incident.version += 1
        
        saved = self.repo.save_incident(incident)
        
        self.repo.append_history(IncidentHistory(
            incident_id=saved.incident_id,
            previous_state=previous_state.value,
            new_state=new_state.value,
            actor=actor,
            reason=reason
        ))
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=saved.incident_id,
            entry_type=IncidentTimelineEntryType.LIFECYCLE_TRANSITION,
            actor=actor,
            metadata={"previous_state": previous_state.value, "new_state": new_state.value, "reason": reason}
        ))
        
        return saved

    def update_metadata(self, incident_id: str, tenant_id: str, actor: str, 
                        severity: Optional[IncidentSeverity] = None, 
                        priority: Optional[IncidentPriority] = None) -> IncidentContract:
        incident = self._ensure_tenant_access(incident_id, tenant_id)
        
        updated = False
        now_ts = self._now()
        
        if severity and incident.severity != severity:
            old_sev = incident.severity
            incident.severity = severity
            updated = True
            self.repo.append_timeline(IncidentTimelineEntry(
                incident_id=incident_id,
                entry_type=IncidentTimelineEntryType.SEVERITY_CHANGED,
                actor=actor,
                metadata={"old": old_sev.value, "new": severity.value}
            ))
            
        if priority and incident.priority != priority:
            old_pri = incident.priority
            incident.priority = priority
            updated = True
            self.repo.append_timeline(IncidentTimelineEntry(
                incident_id=incident_id,
                entry_type=IncidentTimelineEntryType.PRIORITY_CHANGED,
                actor=actor,
                metadata={"old": old_pri.value, "new": priority.value}
            ))
            
        if updated:
            incident.updated_at = now_ts
            incident.version += 1
            incident = self.repo.save_incident(incident)
            
        return incident

    def assign_incident(self, incident_id: str, tenant_id: str, actor: str, assigned_user: Optional[str] = None, assigned_team: Optional[str] = None) -> IncidentContract:
        incident = self._ensure_tenant_access(incident_id, tenant_id)
        
        incident.assigned_user = assigned_user
        incident.assigned_team = assigned_team
        incident.updated_at = self._now()
        incident.version += 1
        
        saved = self.repo.save_incident(incident)
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=incident_id,
            entry_type=IncidentTimelineEntryType.ASSIGNMENT_CHANGED,
            actor=actor,
            metadata={"assigned_user": assigned_user, "assigned_team": assigned_team}
        ))
        
        return saved

    def associate_event(self, incident_id: str, tenant_id: str, event_id: str, actor: str, relationship: EventRelationshipType = EventRelationshipType.RELATED):
        self._ensure_tenant_access(incident_id, tenant_id)
        
        assoc = IncidentEventAssociation(
            incident_id=incident_id,
            event_id=event_id,
            relationship_type=relationship,
            added_by=actor
        )
        self.repo.add_event_association(assoc)
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=incident_id,
            entry_type=IncidentTimelineEntryType.EVENT_ASSOCIATED,
            actor=actor,
            metadata={"event_id": event_id, "relationship": relationship.value}
        ))

    def add_evidence(self, incident_id: str, tenant_id: str, evidence_type: EvidenceType, source_id: str, actor: str, metadata: Dict[str, Any] = None):
        self._ensure_tenant_access(incident_id, tenant_id)
        
        evidence = IncidentEvidence(
            incident_id=incident_id,
            evidence_type=evidence_type,
            source_id=source_id,
            actor=actor,
            metadata=metadata or {}
        )
        self.repo.add_evidence(evidence)
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=incident_id,
            entry_type=IncidentTimelineEntryType.EVIDENCE_ADDED,
            actor=actor,
            metadata={"evidence_type": evidence_type.value, "source_id": source_id}
        ))

    def add_note(self, incident_id: str, tenant_id: str, text: str, actor: str):
        self._ensure_tenant_access(incident_id, tenant_id)
        
        note = IncidentNote(
            incident_id=incident_id,
            author=actor,
            text=text
        )
        self.repo.add_note(note)
        
        self.repo.append_timeline(IncidentTimelineEntry(
            incident_id=incident_id,
            entry_type=IncidentTimelineEntryType.NOTE_ADDED,
            actor=actor,
            metadata={"note_id": note.note_id}
        ))

    def get_incident_details(self, incident_id: str, tenant_id: str) -> Dict[str, Any]:
        incident = self._ensure_tenant_access(incident_id, tenant_id)
        return {
            "incident": incident,
            "events": self.repo.get_event_associations(incident_id),
            "evidence": self.repo.get_evidence(incident_id),
            "notes": self.repo.get_notes(incident_id),
            "timeline": self.repo.get_timeline(incident_id)
        }

    def list_incidents(self, tenant_id: str, limit: int = 100) -> List[IncidentContract]:
        return self.repo.list_incidents(tenant_id, limit)
