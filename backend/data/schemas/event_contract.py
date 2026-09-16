# backend/data/schemas/event_contract.py
"""
SageCommand V3 — Canonical Event Model
Prompt 16 Foundation layer for immutable event records, deterministic fingerprinting,
and standardized scoping.
"""
import uuid
import json
import hashlib
from enum import Enum
from typing import Dict, Any, Optional, Literal, List
from datetime import datetime
from pydantic import BaseModel, Field


class EventSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventLifecycle(str, Enum):
    RECORDED = "RECORDED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class EventCategory(str, Enum):
    SYSTEM = "SYSTEM"
    TELEMETRY = "TELEMETRY"
    STATE_CHANGE = "STATE_CHANGE"
    ANOMALY = "ANOMALY"
    QUALITY = "QUALITY"
    MAINTENANCE = "MAINTENANCE"
    PRODUCTION = "PRODUCTION"
    INVENTORY = "INVENTORY"
    SECURITY = "SECURITY"
    OPERATOR = "OPERATOR"
    SIMULATION = "SIMULATION"
    KNOWLEDGE = "KNOWLEDGE"
    TWIN = "TWIN"


class EventReferences(BaseModel):
    """Structured references to objects/entities related to an event."""
    ontology_id: Optional[str] = Field(None, description="Ontology entity canonical ID")
    twin_id: Optional[str] = Field(None, description="Digital Twin entity ID")
    kg_node_id: Optional[str] = Field(None, description="Knowledge Graph node ID")
    anomaly_id: Optional[str] = Field(None, description="Related Anomaly Detection ID")
    source_system: Optional[str] = Field(None, description="System emitting this event")
    source_record_id: Optional[str] = Field(None, description="ID in the source system")


class CanonicalEvent(BaseModel):
    """
    The Canonical Event Contract for SageCommand V3.
    Represents an immutable occurrence within the enterprise environment.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = Field(default="event.v1")
    event_fingerprint: str = Field(default="")

    # Scope boundaries (MANDATORY)
    tenant_id: str = Field(..., description="Authoritative tenant isolation boundary")
    workspace_id: str = Field(default="global", description="Workspace isolation boundary")
    plant_id: str = Field(default="global", description="Physical plant boundary")

    # Classification
    category: EventCategory = Field(...)
    event_type: str = Field(..., description="Specific event type, e.g. inventory.depleted")
    severity: EventSeverity = Field(default=EventSeverity.INFO)
    lifecycle: EventLifecycle = Field(default=EventLifecycle.RECORDED)

    # Temporal Semantics
    occurred_at: str = Field(..., description="ISO timestamp when the event actually happened")
    observed_at: str = Field(..., description="ISO timestamp when the event was observed by a system")
    recorded_at: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z", 
        description="ISO timestamp when the event was permanently recorded in SageCommand"
    )

    # Correlation / Causation
    correlation_id: Optional[str] = Field(None, description="Identifier linking related events")
    causation_id: Optional[str] = Field(None, description="Identifier of the event that directly caused this one")

    # Provenance
    provenance: str = Field(default="system", description="Origin of the event, e.g. operator, telemetry, discovery")

    # Object References
    references: EventReferences = Field(default_factory=EventReferences)

    # Payload
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured data payload")

    def compute_fingerprint(self) -> str:
        """
        Computes a deterministic SHA-256 fingerprint from the canonicalized event content.
        Excludes transient/database fields. Focuses on the essence of the event.
        """
        # We sort keys to be insensitive to dictionary ordering.
        payload_str = json.dumps(self.payload, sort_keys=True)
        
        # Include fields that uniquely define the event in reality
        # tenant_id ensures fingerprints are tenant-aware and isolated.
        components = [
            self.schema_version,
            self.tenant_id,
            self.category.value,
            self.event_type,
            self.occurred_at,
            self.provenance,
            payload_str
        ]
        
        canonical_string = "|".join(str(c) for c in components)
        return hashlib.sha256(canonical_string.encode('utf-8')).hexdigest()

    def apply_fingerprint(self):
        """Sets the event_fingerprint field using compute_fingerprint."""
        self.event_fingerprint = self.compute_fingerprint()
