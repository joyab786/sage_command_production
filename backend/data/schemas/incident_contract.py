import hashlib
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from pydantic import BaseModel, Field

class IncidentCategory(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    SAFETY = "SAFETY"
    QUALITY = "QUALITY"
    MAINTENANCE = "MAINTENANCE"
    PRODUCTION = "PRODUCTION"
    INVENTORY = "INVENTORY"
    SECURITY = "SECURITY"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SYSTEM = "SYSTEM"
    OTHER = "OTHER"

class IncidentSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class IncidentPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"

class IncidentLifecycle(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"

class EventRelationshipType(str, Enum):
    TRIGGER = "TRIGGER"
    SUPPORTING = "SUPPORTING"
    RELATED = "RELATED"
    FOLLOW_UP = "FOLLOW_UP"
    RESOLUTION = "RESOLUTION"

class EvidenceType(str, Enum):
    EVENT = "EVENT"
    ANOMALY = "ANOMALY"
    TWIN_STATE = "TWIN_STATE"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    DATA_QUALITY = "DATA_QUALITY"
    OPERATOR_NOTE = "OPERATOR_NOTE"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"

class IncidentTimelineEntryType(str, Enum):
    CREATED = "CREATED"
    EVENT_ASSOCIATED = "EVENT_ASSOCIATED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    LIFECYCLE_TRANSITION = "LIFECYCLE_TRANSITION"
    ASSIGNMENT_CHANGED = "ASSIGNMENT_CHANGED"
    SEVERITY_CHANGED = "SEVERITY_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    NOTE_ADDED = "NOTE_ADDED"

class IncidentContract(BaseModel):
    incident_id: str = Field(description="Unique deterministic incident ID")
    schema_version: str = Field(default="3.0", description="Schema version identifier")
    incident_fingerprint: Optional[str] = Field(default=None, description="Deterministic deduplication fingerprint")
    
    # Scope
    tenant_id: str = Field(description="Authoritative tenant scope")
    workspace_id: Optional[str] = Field(default=None, description="Optional workspace scope")
    plant_id: Optional[str] = Field(default=None, description="Optional plant scope")
    
    # Classification
    category: IncidentCategory = Field(default=IncidentCategory.OPERATIONAL)
    severity: IncidentSeverity = Field(default=IncidentSeverity.LOW)
    priority: IncidentPriority = Field(default=IncidentPriority.NORMAL)
    status: IncidentLifecycle = Field(default=IncidentLifecycle.OPEN)
    
    # Description
    title: str = Field(description="Short title")
    description: str = Field(default="", description="Detailed description")
    
    # Timestamps
    detected_at: Optional[str] = Field(default=None, description="When the issue was first detected")
    opened_at: str = Field(description="When the incident was created")
    acknowledged_at: Optional[str] = Field(default=None, description="When the incident was acknowledged")
    resolved_at: Optional[str] = Field(default=None, description="When the incident was resolved")
    closed_at: Optional[str] = Field(default=None, description="When the incident was closed")
    updated_at: str = Field(description="Last update timestamp")
    
    # Ownership
    assigned_user: Optional[str] = Field(default=None, description="Assigned user identity")
    assigned_team: Optional[str] = Field(default=None, description="Assigned team/group")
    acknowledged_by: Optional[str] = Field(default=None, description="Identity who acknowledged")
    
    # Concurrency
    version: int = Field(default=1, description="Optimistic concurrency version")

    def generate_fingerprint(self, deduplication_key: str) -> str:
        """
        Deterministically fingerprint the incident for deduplication purposes.
        Uses tenant, category, and a deterministic business key (like an entity ID or alert rule ID).
        """
        raw = f"{self.tenant_id}|{self.category.value}|{deduplication_key}"
        fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self.incident_fingerprint = fingerprint
        return fingerprint


class IncidentHistory(BaseModel):
    history_id: str = Field(default_factory=lambda: f"hist_{uuid.uuid4().hex}")
    incident_id: str
    previous_state: str
    new_state: str
    actor: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    reason: Optional[str] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentEventAssociation(BaseModel):
    incident_id: str
    event_id: str
    relationship_type: EventRelationshipType = Field(default=EventRelationshipType.RELATED)
    added_by: str
    added_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class IncidentEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evid_{uuid.uuid4().hex}")
    incident_id: str
    evidence_type: EvidenceType
    source_id: str = Field(description="Reference ID to the source (e.g. twin_id, anomaly_id)")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    provenance: str = Field(default="system")
    actor: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentNote(BaseModel):
    note_id: str = Field(default_factory=lambda: f"note_{uuid.uuid4().hex}")
    incident_id: str
    author: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    text: str = Field(max_length=4096)
    provenance: str = Field(default="manual")


class IncidentTimelineEntry(BaseModel):
    entry_id: str = Field(default_factory=lambda: f"tln_{uuid.uuid4().hex}")
    incident_id: str
    entry_type: IncidentTimelineEntryType
    actor: str
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    metadata: Dict[str, Any] = Field(default_factory=dict)
